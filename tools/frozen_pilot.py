#!/usr/bin/env python3
"""Bounded MRL frozen+Ridge pilot reusing the existing scientific admission gate.

No admission override, downloads, test-guided selection or leaderboard writes.
The CLI is deliberately limited to the declared 64-label development protocol;
it does not claim the full learning-curve/HPO/finetuning work packages.
"""
import argparse
import json
from pathlib import Path
import sys
import time

if __package__:
    from . import evaluation_protocol as ep
    from .paired_statistics import paired_group_bootstrap
    from .rnafm_adapter import RNAFMAdapter, validate_records
else:
    import evaluation_protocol as ep
    from paired_statistics import paired_group_bootstrap
    from rnafm_adapter import RNAFMAdapter, validate_records


def fit_head(features, rows, splits, selected_ids, *, alpha=1.0):
    """Train-only scaler/target transform; return numeric JSON, no pickle."""
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    if len(features) != len(rows) or len({r['observation_id'] for r in rows}) != len(rows):
        raise ep.ProtocolError('FEATURE_ROW_ALIGNMENT_FAILURE')
    ids = [r['observation_id'] for r in rows]
    if len(set(selected_ids)) != len(selected_ids) or not selected_ids or any(
            oid not in ids or splits[oid] != 'train' for oid in selected_ids):
        raise ep.ProtocolError('TRAIN_ONLY_UNIQUE_LABEL_BUDGET_REQUIRED')
    x = np.asarray(features, dtype=np.float64)
    if x.ndim != 2 or not np.isfinite(x).all():
        raise ep.ProtocolError('FINITE_MATRIX_FEATURES_REQUIRED')
    indices = [i for i, oid in enumerate(ids) if oid in set(selected_ids)]
    y = np.asarray([rows[i]['label'] for i in indices], dtype=np.float64)
    if not np.isfinite(y).all():
        raise ep.ProtocolError('FINITE_TRAIN_LABELS_REQUIRED')
    scaler = StandardScaler().fit(x[indices])
    mean, scale = float(y.mean()), float(y.std()) or 1.0
    estimator = Ridge(alpha=alpha, solver='svd').fit(scaler.transform(x[indices]), (y-mean)/scale)
    return {'schema_version':'rna_gym.frozen_ridge_head.v1', 'alpha':alpha,
            'scaler_mean':scaler.mean_.tolist(), 'scaler_scale':scaler.scale_.tolist(),
            'coefficients':estimator.coef_.tolist(), 'intercept':float(estimator.intercept_),
            'label_mean':mean, 'label_scale':scale,
            'fit_observation_ids':sorted(selected_ids), 'fit_labels':len(selected_ids),
            'target_transform':'TRAIN_ONLY_ZSCORE_INVERSE_TO_RAW_UNITS',
            'hpo_candidates':0, 'tune_labels':0, 'calibration_labels':0,
            'total_unique_target_labels':len(selected_ids), 'test_selection_labels':0}


def predict_head(head, features):
    import numpy as np
    x = np.asarray(features, dtype=np.float64)
    z = (x-np.asarray(head['scaler_mean']))/np.asarray(head['scaler_scale'])
    return ((z@np.asarray(head['coefficients'])+head['intercept'])*head['label_scale']+head['label_mean']).tolist()


def prepare_pilot(config, input_path, split_path):
    task = config['task']
    if task.get('synthetic') is not False:
        raise ep.ProtocolError('REAL_PILOT_REQUIRES_REAL_TASK_NO_SYNTHETIC_SUBSTITUTION')
    # Reject disabled real tasks before opening any label files or loading models.
    if task.get('enabled') is not True or task.get('admission_state') not in (
            'ADMITTED', 'ADMITTED_CORE', 'ADMITTED_EXTENDED'):
        ep._approval(task, None, None)
    for key in ('max_observations', 'maximum_nt', 'batch_size', 'max_wall_seconds', 'max_output_bytes'):
        if type(config.get(key)) is not int or config[key] <= 0:
            raise ep.ProtocolError('EXPLICIT_POSITIVE_RESOURCE_CAP_REQUIRED:'+key)
    if config['max_observations'] > 512 or config['batch_size'] > 4 or config['max_wall_seconds'] > 1800:
        raise ep.ProtocolError('PILOT_RESOURCE_CAP_EXCEEDS_IMPLEMENTED_SCOPE')
    prepared = ep.prepare(task, input_path, split_path)
    if (task['input_mode'] != 'sequence' or task['alphabet'] != 'ACGU' or
            task['problem_type'] != 'regression' or config.get('panel_role') != 'development_only'):
        raise ep.ProtocolError('ONLY_EXPLICIT_DEVELOPMENT_RNA_REGRESSION_PILOT_IMPLEMENTED')
    if (config.get('seeds') != [11, 23] or config.get('initializations') != ['pretrained', 'random'] or
            config.get('target_label_budget') != 64 or config.get('ridge_alpha') != 1.0):
        raise ep.ProtocolError('RESOLVED_PILOT_PROTOCOL_MISMATCH_NO_SILENT_SEED_OR_BUDGET_CHANGE')
    if (config.get('bootstrap_replicates') != 2000 or config.get('bootstrap_seed') != 20261026):
        raise ep.ProtocolError('RESOLVED_PILOT_BOOTSTRAP_MISMATCH')
    field = config.get('inference_group_field')
    for row in prepared['rows']:
        if not isinstance(field, str) or not isinstance(row.get(field), str) or not row[field]:
            raise ep.ProtocolError('RESOLVED_INFERENCE_GROUP_REQUIRED')
    if len(prepared['rows']) > config['max_observations']:
        raise ep.ProtocolError('OBSERVATION_RESOURCE_CAP_EXCEEDED')
    validate_records(prepared['rows'], config['maximum_nt'])
    if sum(prepared['splits'][r['observation_id']] == 'train' for r in prepared['rows']) < 64:
        raise ep.ProtocolError('INSUFFICIENT_LABEL_BUDGET_NO_REPLACEMENT_OR_REDRAW')
    return prepared


def persist_cell(directory, head, predictions, metrics):
    """Create a new cell atomically by name; never overwrite an old cell."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    ep.write_immutable(directory/'head.json', head)
    ep.write_immutable(directory/'predictions.json', predictions)
    ep.write_immutable(directory/'metrics.json', metrics)


def check_caps(out, started, config):
    if time.monotonic()-started > config['max_wall_seconds']:
        raise ep.ProtocolError('PILOT_WALL_BUDGET_EXCEEDED_NO_PROTOCOL_CHANGE')
    used = sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
    if used > config['max_output_bytes']:
        raise ep.ProtocolError('PILOT_DISK_BUDGET_EXCEEDED_NO_PROTOCOL_CHANGE')


def run_pilot(config, input_path, split_path, manifest, out, *, device='cuda:0'):
    prepared = prepare_pilot(config, input_path, split_path)
    if manifest['maximum_nt'] != config['maximum_nt']:
        raise ep.ProtocolError('MODEL_PROTOCOL_LENGTH_MISMATCH')
    out = Path(out)
    if out.exists():
        raise ep.ProtocolError('PILOT_OUTPUT_MUST_BE_NEW')
    out.mkdir(parents=True)
    started = time.monotonic()
    ep.write_immutable(out/'resolved_config.json', config)
    ep.write_immutable(out/'model_manifest.json', manifest)
    ep.write_immutable(out/'prepare.json', prepared['metadata'])
    all_results, resources = [], []
    for seed in config['seeds']:
        train_ids = [r['observation_id'] for r in prepared['rows'] if prepared['splits'][r['observation_id']] == 'train']
        selected = sorted(train_ids, key=lambda oid: ep.digest_json({'seed':seed, 'observation_id':oid}))[:64]
        subset = {**prepared, 'rows':[r for r in prepared['rows'] if prepared['splits'][r['observation_id']] != 'train' or r['observation_id'] in selected]}
        # Three CPU baselines use exactly the same target labels as the FM head.
        for baseline in ('mean_null', 'sequence_stats_ridge', 'sequence_kmer_ridge'):
            check_caps(out, started, config)
            ep._event(out, {'stage':'BASELINE_STARTED', 'seed':seed, 'method':baseline})
            p = {**subset, 'config':{**subset['config'], 'baseline_id':baseline, 'alpha':1.0, 'kmer_k':3}}
            result = ep.run(p)
            result['model']['label_accounting'] = {'total_unique_target_labels':64, 'tune_labels':0,
                'calibration_labels':0, 'test_selection_labels':0, 'fit_observation_ids':sorted(selected)}
            directory = out/f'seed_{seed}'/baseline
            persist_cell(directory, result['model'], result['predictions'], ep.evaluate(p, result['predictions']))
            ep._event(out, {'stage':'BASELINE_COMPLETED', 'seed':seed, 'method':baseline})
        for initialization in config['initializations']:
            check_caps(out, started, config)
            ep._event(out, {'stage':'FM_STARTED', 'seed':seed, 'initialization':initialization})
            adapter = RNAFMAdapter(manifest, device=device, initialization=initialization, seed=seed)
            encoded, cache = adapter.pooled(prepared['rows'], out/'feature_cache', batch_size=config['batch_size'])
            if [x['observation_id'] for x in encoded] != [r['observation_id'] for r in prepared['rows']]:
                raise ep.ProtocolError('ENCODING_ID_JOIN_FAILURE')
            features = [x['pooled_embedding'] for x in encoded]
            head = fit_head(features, prepared['rows'], prepared['splits'], selected)
            values = predict_head(head, features)
            predictions = [{'observation_id':r['observation_id'], 'split':prepared['splits'][r['observation_id']],
                'input_sha256':ep.input_key(r, 'sequence'), 'prediction':p}
                for r, p in zip(prepared['rows'], values) if prepared['splits'][r['observation_id']] != 'train']
            method = 'RNA-FM_frozen_ridge_'+initialization
            p = {**prepared, 'config':{**prepared['config'], 'baseline_id':method}}
            metrics = ep.evaluate(p, predictions)
            metrics.update(gpu_used=True, seed=seed, initialization=initialization,
                           protocol_scope='EXPLORATORY_DEVELOPMENT_ONLY',
                           label_accounting={key:head[key] for key in ('fit_labels', 'tune_labels',
                               'calibration_labels', 'total_unique_target_labels', 'test_selection_labels')})
            directory = out/f'seed_{seed}'/method
            persist_cell(directory, head, predictions, metrics)
            baseline_predictions = ep.read_json(out/f'seed_{seed}'/'sequence_kmer_ridge/predictions.json')
            # Strict heldout ID joins, never positional assumptions across files.
            bp = {x['observation_id']:x for x in baseline_predictions}
            for split in ('validation', 'test'):
                rows = [r for r in prepared['rows'] if prepared['splits'][r['observation_id']] == split]
                if not rows:
                    continue
                fp = {x['observation_id']:x for x in predictions}
                comparison = paired_group_bootstrap([r['label'] for r in rows],
                    [fp[r['observation_id']]['prediction'] for r in rows],
                    [bp[r['observation_id']]['prediction'] for r in rows],
                    [r[config['inference_group_field']] for r in rows], problem='regression',
                    metric='spearman', replicates=2000, seed=20261026)
                comparison.update(formal_comparison=False, inference_group_field=config['inference_group_field'])
                attempted = comparison['replicates_attempted']
                invalid_fraction = comparison['undefined_replicates']/attempted if attempted else None
                comparison['invalid_fraction'] = invalid_fraction
                comparison['minimum_formal_group_count_met'] = comparison['n_groups'] >= 10
                comparison['conditional_ci'] = comparison['ci']
                if invalid_fraction is None or invalid_fraction > 0.05 or comparison['n_groups'] < 10:
                    comparison['ci'] = None
                    comparison['formal_support_status'] = 'INSUFFICIENT_GROUPS_OR_VALID_REPLICATES'
                else:
                    comparison['formal_support_status'] = 'TECHNICAL_SUPPORT_ONLY_NOT_FORMAL_PROTOCOL_APPROVAL'
                ep.write_immutable(directory/(split+'_paired_comparison.json'), comparison)
            resources.append({'seed':seed, 'initialization':initialization, **adapter.resources(), **cache})
            all_results.append({'seed':seed, 'initialization':initialization, 'metrics':str(directory/'metrics.json')})
            ep._event(out, {'stage':'FM_COMPLETED', 'seed':seed, 'initialization':initialization})
            del adapter
    check_caps(out, started, config)
    if (ep.sha256_file(input_path) != prepared['metadata']['input_sha256'] or
            ep.sha256_file(split_path) != prepared['metadata']['split_sha256']):
        raise ep.ProtocolError('INPUT_OR_SPLIT_CHANGED_DURING_EXECUTION')
    ep._approval(config['task'], prepared['metadata']['input_sha256'], prepared['metadata']['split_sha256'])
    result = {'schema_version':'rna_gym.frozen_pilot.v1', 'status':'EXECUTED',
              'scope':'EXPLORATORY_DEVELOPMENT_ONLY', 'rankable_real_result':False,
              'results':all_results, 'resources':resources, 'wall_seconds':time.monotonic()-started,
              'model_run_denominator':{'attempted':4, 'completed':len(all_results), 'failed':0}}
    ep.write_immutable(out/'result.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--splits', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--device', default='cuda:0')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    existed = args.out.exists()
    try:
        config = ep.read_json(args.config)
        if args.dry_run:
            prepared = prepare_pilot(config, args.input, args.splits)
            print(json.dumps({'status':'READY_FOR_LOCAL_PILOT', 'metadata':prepared['metadata'], 'gpu_not_loaded':True}))
        else:
            print(json.dumps(run_pilot(config, args.input, args.splits, ep.read_json(args.manifest), args.out, device=args.device)))
    except (ep.ProtocolError, OSError, ValueError, RuntimeError, ImportError) as error:
        failure = {'status':'BLOCKED' if args.dry_run else 'NOT_COMPLETED',
                   'reason':str(error), 'rankable_real_result':False}
        if not existed and args.out.exists() and not args.dry_run:
            events = [ep.read_json(p) for p in sorted((args.out/'events').glob('*.json'))]
            attempted = sum(e['stage'] == 'FM_STARTED' for e in events)
            completed = sum(e['stage'] == 'FM_COMPLETED' for e in events)
            failure['model_run_denominator'] = {'planned':4, 'attempted':attempted,
                'completed':completed, 'failed_or_interrupted':attempted-completed,
                'not_run':4-attempted}
            ep.write_immutable(args.out/'failure.json', failure)
        print(json.dumps(failure), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
