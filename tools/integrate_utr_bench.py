#!/usr/bin/env python3
"""Bind existing UTR fold data read-only. No download, training or source edits."""
import argparse
import ast
import collections
import concurrent.futures
import csv
import gzip
import hashlib
import json
import math
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'runs/20261028_utr_taxonomy'


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()


def write(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+'\n')


def inspect_fold0(path):
    n=0;sets=collections.Counter();badseq=badlabel=0;lo=None;hi=None;minlen=None;maxlen=None
    with gzip.open(path,'rt',encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if reader.fieldnames!=['sequence','raw_label','zscore_label','set','fold']:
            raise ValueError('UNEXPECTED_FIVE_COLUMN_SCHEMA')
        for row in reader:
            n+=1;sets[row['set']]+=1
            if row['set'] not in ('train','val','test') or row['fold']!='0':raise ValueError('INVALID_FOLD_ROLE')
            seq=row['sequence'];badseq+=int(not seq or bool(set(seq)-set('ACGTUNacgtun')))
            length=len(seq);minlen=length if minlen is None else min(minlen,length);maxlen=length if maxlen is None else max(maxlen,length)
            try:
                raw=float(row['raw_label']);scaled=float(row['zscore_label'])
                if not math.isfinite(raw) or not math.isfinite(scaled):raise ValueError('nonfinite')
                lo=raw if lo is None else min(lo,raw);hi=raw if hi is None else max(hi,raw)
            except (TypeError,ValueError):badlabel+=1
    return {'n':n,'fold0_roles':dict(sets),'invalid_sequence_rows':badseq,'invalid_label_rows':badlabel,
            'length_min':minlen,'length_max':maxlen,'raw_label_min':lo,'raw_label_max':hi,
            'row_scan_scope':'ALL_FOLD_0_ROWS; other nine source files SHA256-bound to existing frozen fingerprint'}


def integrate(source_root,workers=4):
    source_root=Path(source_root).expanduser().resolve();RUN.mkdir(parents=True,exist_ok=True)
    data=source_root/'data';index=data/'data_index.csv'
    fingerprints=source_root/'UTR_benchmark/data/FINGERPRINTS.json'
    fp=json.loads(fingerprints.read_text())
    if digest(index)!=fp['index_sha256']:raise ValueError('UTR_INDEX_FINGERPRINT_MISMATCH')
    rows=list(csv.DictReader(index.open(encoding='utf-8-sig')))
    previous_path=RUN/'utr_local_manifest.private.json'
    previous=json.loads(previous_path.read_text()).get('datasets',{}) if previous_path.exists() else {}
    def one(row):
        dataset=row['dataset'];paths={};errors=[]
        if Path(dataset).is_absolute() or '..' in Path(dataset).parts:raise ValueError('UNSAFE_DATASET_ID')
        for k in range(10):
            rel=f'{dataset}/fold_{k}.csv.gz';p=(data/rel).resolve()
            proof=fp['folds'].get(rel)
            if not proof or not p.is_file() or not p.is_relative_to(data):
                errors.append('MISSING_FOLD:'+str(k));continue
            stat=p.stat();old=previous.get(dataset,{}).get('folds',{}).get(str(k),{})
            reuse=(old.get('sha256')==proof['sha256'] and old.get('mtime_ns')==stat.st_mtime_ns and
                   old.get('bytes')==stat.st_size==proof['bytes'])
            actual=proof['sha256'] if reuse else digest(p)
            if actual!=proof['sha256'] or stat.st_size!=proof['bytes']:
                errors.append('FOLD_CHECKSUM_MISMATCH:'+str(k));continue
            paths[str(k)]={'path':str(p),'sha256':actual,'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns,
                           'hash_mode':'REUSED_UNCHANGED_VERIFIED_BYTES' if reuse else 'FULL_BYTES_SHA256'}
        profile=None
        if len(paths)==10:
            old=previous.get(dataset,{})
            if old.get('profile') and set(old.get('folds',{}))==set(paths) and all(all(old['folds'][k].get(a)==v.get(a) for a in ('sha256','mtime_ns','bytes','path')) for k,v in paths.items()):profile=old['profile']
            else:
                try:profile=inspect_fold0(paths['0']['path'])
                except Exception as exc:errors.append('SCHEMA_SCAN:'+str(exc))
            if profile and profile['n']!=int(row['samples']):errors.append('INDEX_SAMPLE_COUNT_MISMATCH')
        result={'dataset':dataset,'dataset_id':'UTR102:'+dataset,'source_release':'UTR_LEGACY_102_20261019',
            'row':row,'folds':paths,'profile':profile,'errors':errors,
            'local_verified':not errors and len(paths)==10,'formal_admitted':False,
            'split_kind':'INHERITED_LEGACY_OUTER_TEN_FOLD_NOT_RNAGYM_EAZY_OR_OOD'}
        print(json.dumps({'dataset':dataset,'state':'BOUND' if result['local_verified'] else 'GAP',
                          'n':profile['n'] if profile else None,'errors':errors}),flush=True)
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:results=list(pool.map(one,rows))
    private={'source_root':str(source_root),'allowed_data_root':str(data.resolve()),
        'index_sha256':digest(index),'fingerprint_sha256':digest(fingerprints),
        'datasets':{r['dataset']:r for r in results},'external_files_modified':False,'data_downloaded':False}
    write(previous_path,private)
    metric_code=source_root/'ML/data_io.py'
    tree=ast.parse(metric_code.read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='metrics')
    returns=[n for n in ast.walk(function) if isinstance(n,ast.Return) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='dict']
    reported_metrics=[k.arg for k in returns[-1].value.keywords if k.arg!='n']
    public=[]
    for r in results:
        public.append({k:v for k,v in r.items() if k not in ('folds','errors')}|
            {'fold_files':{k:{a:v[a] for a in ('sha256','bytes')} for k,v in r['folds'].items()},
             'source_reported_metrics':reported_metrics,
             'binding_gaps':r['errors']})
    write(ROOT/'data/registries/utr_legacy_102.json',{'schema':'rna_gym.utr_legacy_extension.v1','datasets':public,
        'original_198_registry_modified':False,'not_independent_experiment_count':True,
        'metric_code_evidence':{'relative_path':'ML/data_io.py','sha256':digest(metric_code),'fields':reported_metrics,'primary_metric_declared':False}})
    catalog=source_root/'public_release_work/github_setup_work/data_metadata__dataset_catalog_87.csv'
    current=source_root/'public_release_work/github_setup_work/data_current_catalog.json'
    if catalog.exists():
        newer=list(csv.DictReader(catalog.open(encoding='utf-8-sig')))
        write(ROOT/'data/registries/utr_revised_87_metadata.json',{'schema':'rna_gym.utr_catalog_metadata.v1',
            'scope':'METADATA_ONLY_NOT_BOUND_LOCAL_DATA; DO_NOT_ADD_TO_102',
            'source_catalog_sha256':digest(catalog),'release':json.loads(current.read_text()),
            'datasets':newer,'data_bytes_bound':False})
    # Existing training results: copy only bounded status/metric-scale evidence,
    # never model weights, OOF predictions, score values or raw data.
    matrix=source_root/'trains/migration/restored/UTR_Selected12_Frozen_Results_20261028_1245/project/reports/migration/model_dataset_matrix_20261028.csv'
    historic={'status':'NOT_FOUND','models_trained_this_integration':0}
    if matrix.exists():
        values=list(csv.DictReader(matrix.open()))
        historic={'status':'EXISTING_EXTERNAL_RESULTS_NOT_RNAGYM_SCORES','matrix_sha256':digest(matrix),
            'matrix_rows':len(values),'unique_datasets':len({x['dataset'] for x in values}),
            'unique_models':len({x['model'] for x in values}),'heads':sorted({x['head'] for x in values}),
            'metric_scales':dict(collections.Counter(x['metric_scale'] for x in values)),
            'reporting_status':dict(collections.Counter(x['reporting_status'] for x in values)),
            'full_compute_status':dict(collections.Counter(x['full_compute_status'] for x in values)),
            'fold_metrics_available':[x.removeprefix('foldmean_') for x in values[0] if x.startswith('foldmean_')],
            'raw_pooled_scores_present':sum(x.get('pooled_raw_spearman') not in ('null','',None) for x in values),
            'formal_results':sum(x['formal_result']=='True' for x in values),'models_trained_this_integration':0}
        selected=source_root/'trains/UTR_Benchmark_v1_Selected12/data/manifests'
        n_bindings=0;binding_gaps=[];by_id={r['dataset']:r for r in results}
        for dataset in sorted({x['dataset'] for x in values}):
            source_manifest=selected/(Path(dataset).name.split('_',1)[0]+'.json')
            if not source_manifest.exists():
                binding_gaps.append(dataset+':MISSING_SOURCE_MANIFEST');continue
            d=json.loads(source_manifest.read_text())
            if d['dataset_uid']!=dataset or d['N']!=by_id[dataset]['profile']['n']:
                binding_gaps.append(dataset+':IDENTITY_OR_N_MISMATCH');continue
            for k,proof in by_id[dataset]['folds'].items():
                if d['folds'][k]['file_sha256']==proof['sha256']:n_bindings+=1
                else:binding_gaps.append(dataset+':FOLD_SHA_MISMATCH:'+k)
        historic['selected12_fold_files_bound_to_legacy102']=n_bindings
        historic['selected12_source_binding_gaps']=binding_gaps
        fold_table=matrix.with_name('fold_metrics_selected12_20261028.csv')
        if fold_table.exists():
            with fold_table.open() as handle:fold_values=list(csv.DictReader(handle))
            historic['full_fold_metric_rows']=len(fold_values)
            historic['fold_metric_table_sha256']=digest(fold_table)
        write(RUN/'historical_results_source.private.json',{'matrix_path':str(matrix),'sha256':digest(matrix)})
    write(ROOT/'data/registries/utr_historical_result_status.json',historic)
    summary={'datasets':len(results),'local_verified':sum(r['local_verified'] for r in results),
        'fold_files_verified':sum(len(r['folds']) for r in results),
        'actual_fold0_records':sum((r['profile'] or {}).get('n',0) for r in results),
        'count_scope':'unique dataset/readout-condition views, not 10x repeated fold CSV rows or independent experiments',
        'families':dict(collections.Counter(r['row']['family'] for r in results)),
        'regions':dict(collections.Counter(r['row']['region'] for r in results)),
        'protected_excluded_upstream':sum(int(r['row']['protected_excluded']) for r in results),
        'invalid_sequence_rows_in_fold0':sum((r['profile'] or {}).get('invalid_sequence_rows',0) for r in results),
        'invalid_label_rows_in_fold0':sum((r['profile'] or {}).get('invalid_label_rows',0) for r in results),
        'raw_and_scaled_labels_changed':False,'existing_splits_changed':False,
        'new_RNAGYM_EAZY_or_OOD_splits_created':False,'formal_admitted':0,'historical_results':historic}
    write(RUN/'integration_summary.json',summary)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',type=Path,default=Path(os.environ.get('RNA_GYM_UTR_BENCH_ROOT',Path.home()/'mRNAbench/UTR_bench_20261019')))
    p.add_argument('--workers',type=int,default=4)
    args=p.parse_args();print(json.dumps(integrate(args.source_root,args.workers),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
