#!/usr/bin/env python3
"""Vectorized scan of every raw nucleotide row without loading whole tables.

Public upstream bundles can contain competition solution labels or predictions;
neither is promoted to experimental training data or a leaderboard by this QC.
"""
import argparse,collections,json,math
from pathlib import Path
from rnagym import ROOT,StateDB,get_target,immutable_json,read_manifest,sha256


def scan(path):
 import numpy as np,pyarrow.parquet as pq,pyarrow.compute as pc
 pf=pq.ParquetFile(path);n=0;stats={};usage=collections.Counter();previous=None;unsorted=0;noninteger=0
 for batch in pf.iter_batches(batch_size=262144):
  n+=batch.num_rows
  for index,name in enumerate(batch.schema.names):
   arr=batch.column(index)
   if name=='Usage':
    for r in pc.value_counts(arr).to_pylist():usage[str(r['values'])]+=r['counts']
    continue
   values=arr.to_numpy(zero_copy_only=False);finite=np.isfinite(values)
   st=stats.setdefault(name,{'finite':0,'null':0,'nonfinite_including_null':0,'raw_minus999':0,'negative_non_sentinel':0,'min':None,'max':None})
   st['finite']+=int(finite.sum());st['null']+=arr.null_count;st['nonfinite_including_null']+=int((~finite).sum());st['raw_minus999']+=int((finite&(values==-999)).sum());st['negative_non_sentinel']+=int((finite&(values<0)&(values!=-999)).sum())
   valid=values[finite]
   if len(valid):
    lo,hi=float(valid.min()),float(valid.max());st['min']=lo if st['min'] is None else min(lo,st['min']);st['max']=hi if st['max'] is None else max(hi,st['max'])
   if name=='id':
    noninteger+=int((finite&(values!=np.floor(values))).sum())
    if len(values):
     if previous is not None and values[0]<=previous:unsorted+=1
     unsorted+=int((np.diff(values)<=0).sum());previous=values[-1]
  if n%10000000<262144:print(json.dumps({'member':path.name,'nucleotide_rows_scanned':n}),flush=True)
 if n!=pf.metadata.num_rows:raise ValueError('parsed count differs from footer')
 prediction='ribonanzanet' in path.name.lower();role='UPSTREAM_MODEL_PREDICTIONS_NOT_EXPERIMENTAL_ASSAY' if prediction else 'COMPETITION_SOLUTION_LABELS_RELEASE_TERMS_UNVERIFIED'
 return {'member':path.name,'member_sha256':sha256(path),'actual_rows':n,'row_unit':'nucleotide-index rows, NOT RNA molecules or independent assays',
  'numeric_column_stats_separate':stats,'usage_distribution':dict(usage),'noninteger_id_rows':noninteger,
  'non_increasing_id_steps':unsorted,'strictly_increasing_ids':not unsorted,
  'id_to_rna_sequence_position_mapping_verified':False,'artifact_role':role,
  'state':'EXCLUDED_MODEL_PREDICTIONS_FROM_ASSAY_COUNTS' if prediction else 'HOLD_COMPETITION_LABEL_TERMS',
  'raw_values_changed':False,'rows_removed':0,'model_inference_or_metrics_run':False,'admission_gate_pass':False,'admitted':False}


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run.resolve();row=read_manifest(ROOT/'data/audit/full_download_assets.csv')['A0006'];raw=get_target(row,ROOT/'raw_cache');base=raw.parent/'raw_parquet_qc';results=[]
 for path in sorted(base.rglob('*.parquet')):
  output=run/'reports'/('raw-parquet-'+path.stem+'.json')
  result=json.loads(output.read_text()) if output.exists() else scan(path)
  immutable_json(output,result);results.append(result)
 immutable_json(run/'reports/raw_nucleotide_parquet_qc.json',{'asset_id':'A0006','source_sha256':sha256(raw),'results':results,'admission_gate_pass':False,'admitted':False})
 with StateDB(ROOT/'run-state.sqlite') as db:
  db.transition(db.ensure(row),'HOLD_COMPETITION_LABEL_TERMS',detail={'scope':'all raw nucleotide rows scanned, labels not approved for training or redistribution'},evidence=[str(run/'reports/raw_nucleotide_parquet_qc.json')])
 print(json.dumps({'raw_parquet_members_scanned':len(results),'nucleotide_rows_scanned':sum(r['actual_rows'] for r in results),'model_predictions_excluded':True,'competition_labels_not_admitted':True}),flush=True)


if __name__=='__main__':main()
