#!/usr/bin/env python3
"""Resolve only indexed RMDB overlaps; retain all labels, probes and splits."""
import argparse,collections,hashlib,itertools,json,sqlite3
from pathlib import Path
from qc_probing_files import hashrow,vector
from rnagym import immutable_json

VERSION='RNA-GYM:probing-overlap-review:v1'
def digest(value):
 return hashlib.sha256(json.dumps(value,ensure_ascii=False,allow_nan=True,separators=(',',':')).encode()).hexdigest()

def known_equal(a,b):
 # Equal missing metadata is NOT evidence of equal experimental conditions.
 if a in (None,'','None','nan','NaN') or b in (None,'','None','nan','NaN'):return 'UNKNOWN'
 return 'SAME' if a==b else 'DIFFERENT'

def compare(left,right):
 import numpy as np
 result={}
 for c in ['modifier','chemical','temperature','reverse_transcriptase']:
  result[c]=known_equal(left.get(c),right.get(c))
 for c in ['reactivity','reactivity_error']:
  a,b=vector(left[c]),vector(right[c])
  result[c+'_same_length']=len(a)==len(b)
  result[c+'_equal_with_nan']=bool(len(a)==len(b) and np.array_equal(a,b,equal_nan=True))
  ma,mb=np.isfinite(a)&(a!=-999.0),np.isfinite(b)&(b!=-999.0)
  result[c+'_valid_mask_equal']=bool(len(a)==len(b) and np.array_equal(ma,mb))
  result[c+'_finite_non_sentinel_positions']=[int(ma.sum()),int(mb.sum())]
 result.update(same_original_assay='UNKNOWN',same_replicate='UNKNOWN',units='NOT_VERIFIED',
  original_observation_ids=[left.get('seqID'),right.get('seqID')],
  decision='RETAIN_DISTINCT_OBSERVATIONS_BLOCK_INPUT_DISJOINT_EVALUATION',
  same_raw_row=hashrow(left)==hashrow(right))
 return result

def load_selected(raw,indices):
 import pyarrow.parquet as pq
 pf=pq.ParquetFile(raw);out={};start=1;groups_read=0
 for group in range(pf.metadata.num_row_groups):
  end=start+pf.metadata.row_group(group).num_rows
  selected=[i for i in indices if start<=i<end]
  if selected:
   table=pf.read_row_group(group);groups_read+=1
   for i in selected:out[i]=table.slice(i-start,1).to_pylist()[0]
  start=end
 if set(out)!=set(indices):raise ValueError('indexed row out of range')
 return out,groups_read

def run(prior,state_db,output):
 identity=prior/'reports/probing_sample_identity.sqlite'
 with sqlite3.connect('file:'+str(identity)+'?mode=ro',uri=True) as c:
  keys=[r[0] for r in c.execute('SELECT DISTINCT a.input_hash FROM samples a JOIN samples b ON a.input_hash=b.input_hash AND a.asset_id<b.asset_id')]
  entries={key:c.execute('SELECT asset_id,row_number,hex(observation_hash),seq_id,file_sha256 FROM samples WHERE input_hash=?',(key,)).fetchall() for key in keys}
 fingerprint=digest([VERSION,[(k.hex(),v) for k,v in sorted(entries.items())]])
 if output.exists():
  cached=json.loads(output.read_text())
  if cached.get('input_fingerprint')!=fingerprint:raise ValueError('immutable output has changed inputs; choose new run')
  return cached
 selected=collections.defaultdict(set)
 for rows in entries.values():
  for aid,n,*_ in rows:selected[aid].add(n)
 loaded={};groups=0;bytes_on_disk={}
 with sqlite3.connect('file:'+str(state_db)+'?mode=ro',uri=True) as db:
  for aid,indices in selected.items():
   expected={r[4] for rows in entries.values() for r in rows if r[0]==aid}
   if len(expected)!=1:raise ValueError('mixed input versions')
   sha=next(iter(expected));record=db.execute('SELECT raw_path,bytes FROM artifacts WHERE asset_id=? AND sha256=?',(aid,sha)).fetchone()
   if not record:raise ValueError('missing indexed raw artifact')
   raw=Path(record[0])
   if raw.stat().st_size!=record[1]:raise ValueError('raw size changed; rerun byte verification')
   rows,count=load_selected(raw,indices);groups+=count
   for n,r in rows.items():loaded[aid,n]=r
   bytes_on_disk[aid]=sha
 comparisons=[];observations=[]
 for key,rows in entries.items():
  for aid,n,obs,sid,sha in rows:
   r=loaded[aid,n]
   if hashrow(r).hex().upper()!=obs or r['seqID']!=sid:raise ValueError('raw row/identity mismatch')
   observations.append(dict(asset_id=aid,row_number=n,seq_id=sid,raw_asset_sha256=sha,input_hash=key.hex(),raw_row_sha256=obs.lower(),
    label_sha256=digest(r['reactivity']),label_error_sha256=digest(r['reactivity_error']),probe=r.get('modifier'),chemical=r.get('chemical'),
    temperature=r.get('temperature'),reverse_transcriptase=r.get('reverse_transcriptase'),sequence_length=len(r['sequence']),
    assay_identity='PROVISIONAL_RMDB_OBSERVATION_NOT_EXPERIMENT_ACCESSION',replicate_identity='UNKNOWN',label_unit='UNKNOWN'))
  for a,b in itertools.combinations(rows,2):
   if a[0]==b[0]:continue
   comparisons.append(dict(input_hash=key.hex(),left_asset=a[0],left_row=a[1],right_asset=b[0],right_row=b[1],**compare(loaded[a[0],a[1]],loaded[b[0],b[1]])))
 result=dict(algorithm=VERSION,input_fingerprint=fingerprint,verification_status='VERIFIED',scientific_identity_status='BLOCKED',
  shared_exact_inputs=len(keys),reviewed_observations=len(observations),cross_split_observation_pairs=len(comparisons),
  source_raw_sha256=bytes_on_disk,selected_parquet_row_groups_read=groups,full_raw_rescan=False,
  observations=observations,comparisons=comparisons,rows_removed=0,raw_labels_changed=False,splits_changed=False,
  input_disjoint_split_pass=False,admission_gate_pass=False,
  evidence=[str(prior/'reports/probing_exact_split_overlap.json'),str(identity)],
  next_action='Resolve RMDB experiment/replicate accession and units. Official split retained; any strict-input alternative must be independently versioned.')
 immutable_json(output,result);return result

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--prior',type=Path,required=True);p.add_argument('--state-db',type=Path,default=Path('run-state.sqlite'));p.add_argument('--output',type=Path,required=True);p.add_argument('--dry-run',action='store_true');a=p.parse_args()
 if a.dry_run:print(json.dumps(dict(action='review_indexed_shared_inputs_only',writes=False,gpu=False)));return
 r=run(a.prior,a.state_db,a.output);print(json.dumps({k:r[k] for k in ['shared_exact_inputs','reviewed_observations','cross_split_observation_pairs','selected_parquet_row_groups_read','scientific_identity_status']}))
if __name__=='__main__':main()
