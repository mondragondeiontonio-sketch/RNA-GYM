#!/usr/bin/env python3
"""Real local, exploratory QC/split/baseline runs. Never grants formal admission.

The user explicitly authorizes processing HOLD data. Existing formal runners and
admission gates are not modified. Outputs are not formal leaderboard entries.
"""
import itertools
import hashlib
import json
import math
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

from tools.build_arena_v1 import ROOT, QC, dump, load, sha, table, tsv


def groups(rows, fields):
    """Connected components of exact input and explicit biological identities."""
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    seen = {}
    for i, row in enumerate(rows):
        keys = [('input', row['input_hash'])]
        meta = json.loads(row['group_metadata_json'] or '{}')
        for field in fields:
            value = meta.get(field)
            if value not in (None, '', 'UNKNOWN'):
                keys.append((field, str(value)))
        for key in keys:
            if key in seen:
                parent[find(i)] = find(seen[key])
            else:
                seen[key] = i
    components = defaultdict(list)
    for i in range(len(rows)):
        components[find(i)].append(rows[i]['record_id'])
    ids = {k: hashlib.sha256('\n'.join(sorted(v)).encode()).hexdigest() for k, v in components.items()}
    return [ids[find(i)] for i in range(len(rows))]


def features(sequence):
    # Explicit feature view only. Original sequences and input identity unchanged.
    s = sequence.upper().replace('U', 'T')
    n = len(s)
    counts = Counter(s[i:i+2] for i in range(max(0, n-1)))
    return [math.log1p(n)] + [s.count(b)/max(1,n) for b in 'ACGTN'] + [
        counts[a+b]/max(1,n-1) for a,b in itertools.product('ACGT', repeat=2)]


def run(root=ROOT):
    import numpy as np
    import pyarrow.parquet as pq
    from scipy.stats import pearsonr, spearmanr
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from rna_gym.arena import normalize_score
    scoring = load(root/'configs/scoring_protocol_v1.yaml')
    started = time.monotonic()
    out = root/'runs/20261030_arena_v1'
    out.mkdir(parents=True, exist_ok=True)
    config = load(root/'configs/exploratory_baselines_v1.yaml')
    # First independently check actual local Parquet row counts and freeze hashes.
    checks = []
    for unit in table(root/'data/audit/dataset_statistics.tsv'):
        d = root/'data/processed'/unit['unit_id']/QC
        freeze = load(d/'freeze.json')
        current = sha(d/'curated_data.parquet')
        actual = pq.ParquetFile(d/'curated_data.parquet').metadata.num_rows
        checks.append(dict(unit_id=unit['unit_id'], current_curated_sha256=current,
            expected_curated_sha256=freeze['files']['curated_data.parquet'],
            actual_parquet_rows=actual, audit_valid_n=int(unit['valid_n']),
            passed=current == freeze['files']['curated_data.parquet'] and actual == int(unit['valid_n'])))
    tsv(out/'local_parquet_verification.tsv', checks)
    if not all(r['passed'] for r in checks):
        raise ValueError('LOCAL_FREEZE_OR_COUNT_MISMATCH')
    results, split_summaries = [], []
    for spec in config['datasets']:
        unit, target = spec['unit_id'], spec['target_column']
        d = root/'data/processed'/unit/QC
        cols = ['record_id', 'observation_id', 'input_hash', 'sequence', 'label_json', 'group_metadata_json']
        records = pq.read_table(d/'curated_data.parquet', columns=cols).to_pylist()
        if len(records) > config['max_records_per_dataset']:
            raise ValueError('EXPLORATORY_BUDGET_EXCEEDED')
        fields = spec['group_fields']
        missing = sum(not all(json.loads(r['group_metadata_json'] or '{}').get(f) for f in fields) for r in records)
        if missing:
            raise ValueError('MISSING_REQUIRED_BIOLOGICAL_GROUP')
        gid = groups(records, fields)
        unique = sorted(set(gid))
        if len(unique) < 5:
            raise ValueError('TOO_FEW_GROUPS_NO_FORCED_FOLDS')
        # Group IDs are content-addressed; round-robin of hashed components is label blind.
        fold = {g: i % 5 for i,g in enumerate(unique)}
        assignments = [dict(record_id=r['record_id'], observation_id=r['observation_id'],
            input_hash=r['input_hash'], group_id=g, outer_fold=fold[g]) for r,g in zip(records,gid)]
        split_dir = root/'data/splits/RNAGYM_SPLIT_V1'/unit
        split_dir.mkdir(parents=True, exist_ok=True)
        candidate = out/(unit+'_assignments.candidate.tsv')
        tsv(candidate, assignments)
        existing = split_dir/'assignments.tsv'
        if existing.exists() and existing.read_bytes() != candidate.read_bytes():
            raise ValueError('FROZEN_SPLIT_CONFLICT_CREATE_NEW_PROTOCOL_VERSION')
        if not existing.exists():
            existing.write_bytes(candidate.read_bytes())
        by_input, by_group = defaultdict(set), defaultdict(set)
        for r in assignments:
            by_input[r['input_hash']].add(r['outer_fold'])
            by_group[r['group_id']].add(r['outer_fold'])
        leak = {'exact_input_cross_fold': sum(len(v)>1 for v in by_input.values()),
            'biological_group_cross_fold': sum(len(v)>1 for v in by_group.values())}
        if any(leak.values()):
            raise ValueError('CROSS_SPLIT_LEAKAGE')
        manifest = dict(protocol_id='RNAGYM_SPLIT_V1', unit_id=unit, canonical_task_id=spec['canonical_task_id'],
            difficulty='D2_GENERALIZATION', group_fields=fields, n_records=len(records), n_groups=len(unique),
            n_folds=5, assignments_sha256=sha(split_dir/'assignments.tsv'),
            curated_sha256=sha(d/'curated_data.parquet'), algorithm='exact-input+biological-group-connected-components-hash-order-5fold',
            role_rule='outer_fold=test; (outer_fold+1)%5=validation; remaining=train',
            leakage=leak, author_split_modified=False, formal_admitted=False,
            limitations=['gene-held-out, not assay/species/cell OOD', 'cross-dataset homology not cleared'],
            config_sha256=sha(root/'configs/exploratory_baselines_v1.yaml'))
        frozen_manifest = split_dir/'manifest.json'
        if frozen_manifest.exists() and load(frozen_manifest) != manifest:
            raise ValueError('FROZEN_MANIFEST_CONFLICT_CREATE_NEW_PROTOCOL_VERSION')
        if not frozen_manifest.exists():
            dump(frozen_manifest, manifest)
        split_summaries.append(manifest)
        x = np.asarray([features(r['sequence']) for r in records])
        y = np.asarray([json.loads(r['label_json'])[target] for r in records], dtype=float)
        if not np.isfinite(x).all() or not np.isfinite(y).all():
            raise ValueError('NONFINITE_INPUT_OR_TARGET')
        folds = np.asarray([fold[g] for g in gid])
        predictions = []
        for outer in range(5):
            train = (folds != outer) & (folds != (outer+1)%5)
            test = folds == outer
            model = make_pipeline(StandardScaler(), Ridge(alpha=config['ridge_alpha']))
            model.fit(x[train], y[train])
            dump(out/(unit+'_ridge_fold_'+str(outer)+'.json'), dict(
                scaler_mean=model[0].mean_.tolist(), scaler_scale=model[0].scale_.tolist(),
                coefficients=model[1].coef_.tolist(), intercept=float(model[1].intercept_),
                train_record_ids_sha256=hashlib.sha256('\n'.join(sorted(records[i]['record_id'] for i in np.flatnonzero(train))).encode()).hexdigest()))
            fitted = model.predict(x[test])
            mean = float(np.mean(y[train]))
            median = float(np.median(y[train]))
            for index, value in zip(np.flatnonzero(test), fitted):
                predictions.append(dict(record_id=records[index]['record_id'], outer_fold=outer,
                    prediction=float(value), mean_null=mean, median_null=median))
        predictions.sort(key=lambda r:r['record_id'])
        pred_path = out/(unit+'_predictions.tsv')
        tsv(pred_path, predictions)
        observed = {r['record_id']: float(v) for r,v in zip(records,y)}
        truth = np.asarray([observed[r['record_id']] for r in predictions])
        for baseline, column in [('sequence_stats_ridge', 'prediction'), ('mean_null', 'mean_null'), ('median_null', 'median_null')]:
            pred = np.asarray([r[column] for r in predictions])
            rho = float(spearmanr(truth,pred).statistic) if len(set(pred)) > 1 else None
            pearson = float(pearsonr(truth,pred).statistic) if len(set(pred)) > 1 else None
            results.append(dict(model_id=baseline, model_version='arena-cpu-1.0',
                parameter_count=len(model[1].coef_)+1 if baseline == 'sequence_stats_ridge' else 1,
                pretraining_type='NON_FM_NO_PRETRAINING', coverage=None,
                task_id=spec['canonical_task_id'], dataset_id='QC:'+unit, target_column=target,
                difficulty='D2_GENERALIZATION', raw_metric='Spearman', raw_score=rho,
                pearson=pearson, mae=float(np.mean(np.abs(truth-pred))), rmse=float(np.sqrt(np.mean((truth-pred)**2))),
                normalized_score=normalize_score('Spearman', rho, scoring) if rho is not None else None,
                evaluation_status='EVALUATED' if rho is not None else 'FAILED',
                result_source='RNA_GYM_REPRODUCED', evaluation_phase='EXPLORATORY_NOT_ADMITTED',
                formal_leaderboard_eligible=False, adaptation_track='supervised_non_fm',
                n_test_predictions=len(truth), split_hash=manifest['assignments_sha256'],
                input_hash=manifest['curated_sha256'], checkpoint_hash=hashlib.sha256(''.join(sha(out/(unit+'_ridge_fold_'+str(i)+'.json')) for i in range(5)).encode()).hexdigest() if baseline == 'sequence_stats_ridge' else 'TRAIN_ONLY_CONSTANTS_IN_PREDICTIONS',
                code_version=sha(Path(__file__)), compute='CPU; one thread; fixed alpha; five outer folds; no HPO',
                predictions_hash=sha(pred_path), error_reason='' if rho is not None else 'UNDEFINED_CONSTANT_CORRELATION'))
    tsv(root/'results/exploratory/baselines_v1.tsv', results)
    dump(out/'compute_receipt.json', dict(status='EXECUTED', parquet_units_verified=len(checks),
        parquet_records_verified=sum(r['actual_parquet_rows'] for r in checks),
        split_datasets=len(split_summaries), canonical_tasks=sorted({r['task_id'] for r in results}),
        reproduced_result_rows=len(results), evaluated_models=sorted({r['model_id'] for r in results}),
        formal_results=0, wall_seconds=time.monotonic()-started,
        raw_modified=False, admission_modified=False, models_downloaded=False))
    print(json.dumps(load(out/'compute_receipt.json'), indent=2))


if __name__ == '__main__':
    run()
