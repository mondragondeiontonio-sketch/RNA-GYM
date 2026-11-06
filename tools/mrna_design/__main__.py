"""Public CPU-only V0.6 CLI: python -m tools.mrna_design --help."""
import argparse
import csv
import json
from pathlib import Path
import random
from rna_gym.research_v06.provenance import (ProtocolError, read_json, write_immutable,
    sha256_file, digest_json, write_table, receipt, public_scan)
from rna_gym.research_v06.therna import import_therna, iter_long
from rna_gym.research_v06.splits import make_split
from rna_gym.research_v06.baselines import run_baselines
from rna_gym.research_v06.scoring import score_predictions


def verify_receipt(out):
    out = Path(out)
    record = read_json(out/'receipt.json')
    copy = dict(record)
    claimed = copy.pop('receipt_id')
    if digest_json(copy) != claimed:
        raise ProtocolError('RECEIPT_ID_MISMATCH')
    for name, expected in record['outputs'].items():
        if Path(name).name != name or sha256_file(out/name) != expected:
            raise ProtocolError('RECEIPT_OUTPUT_HASH_MISMATCH')
    return {'status':'VERIFIED', 'stage':record['stage'], 'receipt_id':claimed}


def split_stage(long_path, config, out):
    rows = list(iter_long(long_path))
    assignment, manifest = make_split(rows, **config)
    out = Path(out); out.mkdir(parents=True,exist_ok=True)
    write_immutable(out/'split_manifest.json',manifest)
    write_immutable(out/'no_leakage_report.json',manifest['no_leakage_report'])
    write_table(out/'group_assignment.tsv', assignment)
    receipt(out,'axis_split',{'long_sha256':sha256_file(long_path),'config':config},
            [out/'split_manifest.json',out/'group_assignment.tsv',out/'no_leakage_report.json'],
            manifest['no_leakage_report']['counts'], synthetic=manifest.get('synthetic', False))
    return assignment, manifest


def baseline_stage(long_path, split_root, config, out):
    rows = list(iter_long(long_path))
    split_root=Path(split_root)
    verify_receipt(split_root)
    split_receipt=read_json(split_root/'receipt.json')
    if split_receipt['inputs']['long_sha256'] != sha256_file(long_path):
        raise ProtocolError('SPLIT_RAW_LONG_HASH_MISMATCH')
    with (split_root/'group_assignment.tsv').open() as handle:
        assignment = list(csv.DictReader(handle,delimiter='\t'))
    predictions, metrics = run_baselines(rows,assignment,read_json(split_root/'split_manifest.json'),config)
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    files=[]
    for model, records in predictions.items():
        path=out/(model+'.predictions.private.json')
        write_immutable(path,records);files.append(path)
    write_immutable(out/'metrics.private.json',metrics);files.append(out/'metrics.private.json')
    write_immutable(out/'model_config.json',config);files.append(out/'model_config.json')
    receipt(out,'cpu_baselines',{'long_sha256':sha256_file(long_path),
        'split_hash':metrics['split_hash'],'config_sha256':digest_json(config)},files,
        metrics['role_observations'], synthetic=read_json(split_root/'split_manifest.json').get('synthetic', False))
    return metrics


def synthetic_e2e(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    raw=out/'fixture.csv'
    if raw.exists():
        raise ProtocolError('E2E_OUTPUT_EXISTS_USE_NEW_VERSION')
    rng=random.Random(6)
    with raw.open('x',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['sequence']+[c+'__'+str(t)+'h' for c in ('A','B','C') for t in (24,36)])
        for _ in range(96):
            seq=''.join(rng.choices('ACGT',k=30))
            composition=seq.count('G')/30
            # Additive-only negative control, not a scientific data source.
            writer.writerow([seq]+[composition+j*0.3+t*.001+rng.gauss(0,.02)
                                     for j in range(3) for t in (24,36)])
    config={'source_id':'SYNTHETIC_FIXTURE','source_release':'v06-fixture-1',
      'assay_id':'SYNTHETIC_ADDITIVE_ONLY','readout_id':'GEX_NORMALIZED_REPORTER',
      'label_raw_unit':'synthetic_arbitrary','label_direction':'HIGHER_IS_SYNTHETIC',
      'label_formula':'synthetic_seq_plus_cell_plus_time_plus_noise','kind':'penta',
      'expected_cells':3,'raw_files':[{'path':raw.name,'sha256':sha256_file(raw)}],
      'rights_research':True,'rights_evaluate':True,'rights_redistribute':True,
      'rights_aggregate':True,'rights_review_status':'APPROVED','local_only':False,'synthetic':True}
    import_therna(config,out,out/'import')
    split_stage(out/'import/long.tsv.gz',{'protocol':'S-OUT','seed':6},out/'split')
    models={'seed':6,'max_k':2,'interaction_rank':2,'ridge_alphas':[1.,10.],
            'bootstrap_replicates':40,'max_observations':10000}
    metrics=baseline_stage(out/'import/long.tsv.gz',out/'split',models,out/'baseline')
    for name, score in metrics['models'].items():
        replay=score_predictions(read_json(out/'baseline'/(name+'.predictions.private.json')))
        if replay != score:
            raise ProtocolError('METRIC_REPLAY_MISMATCH')
    verification=[verify_receipt(out/p) for p in ('import','split','baseline')]
    summary={'status':'PASS_SYNTHETIC_NOT_SCIENTIFIC','stages':verification,
             'metrics_replayed':len(metrics['models']),'formal_admitted':False,'gpu_hours':0,
             'negative_control':'ADDITIVE_ONLY_NOT_BIOLOGICAL_EVIDENCE'}
    write_immutable(out/'e2e_summary.json',summary)
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['import-therna','split-therna','run-baselines','replay',
                                          'e2e','audit-utr','public-safety','catalog-polya','overlap'])
    parser.add_argument('--config',type=Path)
    parser.add_argument('--raw-root',type=Path,default=Path('.'))
    parser.add_argument('--input',type=Path)
    parser.add_argument('--split-root',type=Path)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.verify_only:
            if not args.out: raise ProtocolError('--out required')
            result=verify_receipt(args.out)
        elif args.command=='public-safety':
            paths=[p for p in args.input.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
            result=public_scan(paths)
        elif args.command=='import-therna':
            result=import_therna(read_json(args.config),args.raw_root,args.out,dry_run=args.dry_run)
        elif args.dry_run:
            result={'status':'NO_WRITE_PLAN','command':args.command,
                    'config':read_json(args.config) if args.config else None}
        elif args.command=='e2e': result=synthetic_e2e(args.out)
        elif args.command=='split-therna':
            _,result=split_stage(args.input,read_json(args.config),args.out)
        elif args.command=='run-baselines':
            result=baseline_stage(args.input,args.split_root,read_json(args.config),args.out)
        elif args.command=='replay': result=score_predictions(read_json(args.input))
        elif args.command=='audit-utr':
            from .audit_utr import audit_utr
            result=audit_utr(args.input,args.raw_root,args.out)
        elif args.command=='catalog-polya':
            from rna_gym.research_v06.polya import validate_polya
            result=validate_polya(read_json(args.config))
        else:
            from rna_gym.research_v06.provenance import overlap_graph
            result=overlap_graph(read_json(args.input))
            if args.out:
                args.out.mkdir(parents=True,exist_ok=True)
                write_immutable(args.out/'source_overlap_graph.json',result)
        print(json.dumps(result,sort_keys=True,allow_nan=False))
        return 0
    except (ProtocolError,FileNotFoundError,TypeError,KeyError) as exc:
        parser.exit(2,'BLOCKED: '+str(exc)+'\n')


if __name__=='__main__':
    main()
