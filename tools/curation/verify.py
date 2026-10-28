"""Independently validate frozen assignment files against curated observations.

Does not trust a reported zero-leakage field: recomputes it from actual Parquet
bytes. Freezing here is a data-version freeze, never scientific admission.
"""
import argparse
import collections
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .core import ROOT,RUN,write_json,file_sha,write_tsv
from .review import read_reports


def verify_unit(report,freeze=False):
    path=ROOT/report['output_path'];directory=path.parent
    data=pq.read_table(path,columns=['record_id','observation_id','input_hash','label_json'])
    errors=[];checks={}
    def check(name,ok,detail=None):
        checks[name]={'pass':bool(ok),'detail':detail}
        if not ok:errors.append(name)
    check('curated_row_count',len(data)==report['valid_n'],len(data))
    check('curated_sha256',file_sha(path)==report['output_sha256'])
    check('unique_record_ids',pc.count_distinct(data['record_id']).as_py()==len(data))
    check('unique_observation_ids',pc.count_distinct(data['observation_id']).as_py()==len(data))
    mapping=pq.ParquetFile(directory/'observation_mapping.parquet')
    check('every_source_row_has_mapping',mapping.metadata.num_rows==report['actual_n'])
    check('mass_balance',report['actual_n']==report['valid_n']+report['excluded_n']+report['quarantined_n']+report['duplicate_n'])
    splits=directory/'splits';summary=json.loads((splits/'split_summary.json').read_text())
    manifest_path=splits/'split_manifest.parquet'
    check('split_sha256',file_sha(manifest_path)==summary['split_manifest_sha256'])
    manifest=pq.read_table(manifest_path)
    protocols={}
    expected_total=0
    for name,r in summary['protocols'].items():
        expected=report['valid_n'] if r.get('n_folds',0)>0 else 0
        expected_total+=expected
        subset=manifest.filter(pc.equal(manifest['protocol'],name))
        detail={'status':r['status'],'expected_n':expected,'actual_n':len(subset)}
        check(name+':row_count',len(subset)==expected)
        if not expected:
            protocols[name]=detail;continue
        check(name+':observation_exactly_once',pc.count_distinct(subset['observation_id']).as_py()==expected)
        membership=pc.is_in(subset['observation_id'],value_set=data['observation_id'])
        check(name+':all_observations_in_curated',pc.all(membership).as_py())
        folds=subset['outer_fold']
        check(name+':fold_bounds',pc.min(folds).as_py()>=0 and pc.max(folds).as_py()<r['n_folds'])
        bad_groups=subset.group_by('group_id').aggregate([('outer_fold','count_distinct')])
        nbad=pc.sum(pc.cast(pc.greater(bad_groups['outer_fold_count_distinct'],1),pa.int64())).as_py()
        check(name+':group_disjoint',nbad==0,nbad)
        bad_inputs=subset.group_by('input_hash').aggregate([('outer_fold','count_distinct')])
        input_overlap=pc.sum(pc.cast(pc.greater(bad_inputs['outer_fold_count_distinct'],1),pa.int64())).as_py()
        detail['actual_input_cross_fold_groups']=input_overlap
        if name=='OOD_split':check(name+':exact_input_disjoint',input_overlap==0,input_overlap)
        if r.get('leakage'):
            check(name+':reported_input_overlap_matches',input_overlap==r['leakage']['input_cross_fold_groups'],input_overlap)
        fold_counts={v['values']:v['counts'] for v in pc.value_counts(folds).to_pylist()}
        detail['actual_fold_counts']=fold_counts
        check(name+':all_folds_nonempty',len(fold_counts)==r['n_folds'])
        check(name+':reported_fold_counts_match',all(fold_counts.get(f['fold'],0)==f['n'] for f in r['folds']))
        if report.get('binary'):
            indices=pc.index_in(subset['observation_id'],value_set=data['observation_id'])
            labels=pc.take(data['label_json'],indices)
            cl=pa.table({'fold':folds,'label':labels}).group_by(['fold','label']).aggregate([('label','count')])
            class_support=collections.Counter(x['fold'] for x in cl.to_pylist())
            check(name+':binary_classes_per_fold',all(class_support.get(f,0)>=2 for f in range(r['n_folds'])),dict(class_support))
        detail['observation_cross_fold']=0 # follows independently checked unique observation membership
        detail['enforced_group_cross_fold']=nbad
        detail['validation_rule']='for outer f: test=f, validation=(f+1)%k, train=remaining; sets disjoint by construction'
        protocols[name]=detail
    check('no_unexpected_manifest_rows',len(manifest)==expected_total)
    provenance=json.loads((directory/'provenance.json').read_text())
    artifact_audit={'status':'PASS' if not errors else 'FAIL','unit_id':report['unit_id'],'checks':checks,
                    'protocols':protocols,'errors':errors,
                    'producer_binding':provenance.get('producer_binding','WORKING_TREE_AT_COMPLETION_ONLY'),
                    'scope':'DATA_INTEGRITY_AND_SPLIT_ONLY_NOT_HUMAN_SCIENTIFIC_ADMISSION'}
    audit_path=splits/'independent_validation.json'
    if (directory/'freeze.json').exists() and audit_path.exists():
        if json.loads(audit_path.read_text())!=artifact_audit:
            raise ValueError('FROZEN_VALIDATION_FACTS_CHANGED:'+report['unit_id'])
    else:
        write_json(audit_path,artifact_audit)
    if freeze and not errors:
        important=['curated_data.parquet','qc_report.json','provenance.json','exclusion_log.tsv',
                   'observation_mapping.parquet','splits/split_manifest.parquet','splits/split_summary.json',
                   'splits/leakage_report.json','splits/independent_validation.json']
        freeze_doc={'state':'FROZEN_DATA_VERSION_NOT_ADMISSION','files':{f:file_sha(directory/f) for f in important},
                    'unit_id':report['unit_id'],'admitted':False,'human_reviewer':None}
        freeze_path=directory/'freeze.json'
        if freeze_path.exists() and json.loads(freeze_path.read_text())!=freeze_doc:
            raise ValueError('FROZEN_OUTPUT_CHANGED:'+report['unit_id'])
        write_json(freeze_path,freeze_doc)
    return artifact_audit


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--freeze',action='store_true');p.add_argument('--units',nargs='*')
    args=p.parse_args();results=[]
    for r in read_reports():
        if args.units and r['unit_id'] not in args.units:continue
        try:result=verify_unit(r,args.freeze)
        except Exception as exc:result={'unit_id':r['unit_id'],'status':'FAIL','errors':[str(exc)]}
        results.append(result);print(json.dumps({'unit':r['unit_id'],'status':result['status'],'errors':result['errors']}),flush=True)
    write_json(RUN/'independent_validation_summary.json',{'units':len(results),
        'pass':sum(r['status']=='PASS' for r in results),'fail':sum(r['status']!='PASS' for r in results),'results':results})
    if any(r['status']!='PASS' for r in results):raise SystemExit(1)

if __name__=='__main__':main()
