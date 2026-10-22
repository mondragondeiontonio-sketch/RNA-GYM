#!/usr/bin/env python3
"""Full-file sequence/label/annotation scan. NOT full assay admission.

All rows are retained. Original values stay in immutable raw files; row identity
and QC masks are stored locally. Readouts are never merged. No scaler/split/HPO.
"""
from __future__ import annotations
import argparse,collections,csv,hashlib,json,math,platform,sqlite3
from pathlib import Path
from rnagym import ROOT,StateDB,get_target,immutable_json,read_manifest,sha256


def digest(parts):
 return hashlib.sha256(json.dumps(parts,ensure_ascii=False,separators=(',',':'),allow_nan=True).encode()).digest()


class Numeric:
 def __init__(self):
  self.n=0;self.missing=0;self.invalid=0;self.minimum=None;self.maximum=None;self.total=0.0;self.values=collections.Counter()
 def add(self,value,kind):
  if value is None:self.missing+=1;return
  if isinstance(value,bool):value=int(value)
  if not isinstance(value,(int,float)) or not math.isfinite(value):self.invalid+=1;return
  if kind=='binary' and value not in (0,1):self.invalid+=1;return
  self.n+=1;self.total+=value
  self.minimum=value if self.minimum is None else min(self.minimum,value)
  self.maximum=value if self.maximum is None else max(self.maximum,value)
  if len(self.values)<33 or str(value) in self.values:self.values[str(value)]+=1
 def result(self):
  return {'finite_values':self.n,'missing':self.missing,'invalid_or_nonfinite':self.invalid,
   'min':self.minimum,'max':self.maximum,'mean':self.total/self.n if self.n and math.isfinite(self.total) else None,
   'observed_value_counts_up_to_33':dict(self.values) if len(self.values)<=32 else None}


class RowQC:
 def __init__(self,spec):
  self.spec=spec;self.n=0;self.issues=collections.Counter();self.first=[];self.chars=collections.Counter();self.lengths=collections.Counter();self.vector_lengths=collections.defaultdict(collections.Counter);self.stats={};self.inputs={};self.observations=set();self.label_sets=collections.defaultdict(set);self.identity_rows=[]
 def issue(self,name,row):
  self.issues[name]+=1
  if len(self.first)<20:self.first.append({'row':row,'reason':name})
 def add(self,row,row_index):
  self.n+=1;seq=row.get(self.spec.get('sequence','sequence'));mask=[]
  if not isinstance(seq,str) or not seq:
   self.issue('EMPTY_OR_NONSTRING_SEQUENCE',row_index);mask.append('SEQUENCE');seq=seq if isinstance(seq,str) else ''
  self.chars.update(seq);self.lengths[len(seq)]+=1
  if not set(seq)<=set('ACGTUN'):
   self.issue('NONCANONICAL_SEQUENCE_ALPHABET',row_index);mask.append('ALPHABET')
  for col in self.spec.get('tracks',[]):
   track=row.get(col)
   if not isinstance(track,list) or len(track)!=len(seq):
    self.issue('TRACK_LENGTH_OR_TYPE:'+col,row_index);mask.append('TRACK:'+col)
   elif not set(track)<={0,1}:
    self.issue('TRACK_NONBINARY:'+col,row_index);mask.append('TRACK:'+col)
  targets=dict(self.spec.get('targets',{}))
  if self.spec.get('target_prefix'):
   targets.update({c:self.spec.get('target_kind','continuous') for c in row if c.startswith(self.spec['target_prefix'])})
  if not targets:
   self.issue('NO_DECLARED_TARGETS',row_index);mask.append('TARGET')
  payload={}
  for col,kind in targets.items():
   value=row.get(col);payload[col]=value
   if kind=='binary_vector':
    if not isinstance(value,list):
     self.stats.setdefault(col,Numeric()).missing+=1;self.issue('TARGET_VECTOR_TYPE:'+col,row_index);continue
    self.vector_lengths[col][len(value)]+=1
    for v in value:self.stats.setdefault(col,Numeric()).add(v,'binary')
   else:self.stats.setdefault(col,Numeric()).add(value,kind)
  key=digest(['RNA-GYM:raw-sequence:v1',seq]);label=digest(['RNA-GYM:targets:v1',payload]);obs=digest(['RNA-GYM:raw-row:v1',row])
  self.inputs[key]=self.inputs.get(key,0)+1;self.label_sets[key].add(label);self.observations.add(obs)
  self.identity_rows.append((row_index,key,obs,label,str(row.get('gene') or row.get('transcript_id') or ''),str(row.get('split') or 'UNSPECIFIED'),json.dumps(mask)))
 def report(self):
  invalid=sum(s.invalid for s in self.stats.values())
  vector_inconsistent={k:dict(v) for k,v in self.vector_lengths.items() if len(v)>1}
  passed=bool(self.n) and not self.issues and not invalid and not vector_inconsistent
  return {'state':'PASS_FULL_FILE_SCHEMA_ONLY' if passed else 'ROW_QC_ISSUES_DETECTED',
   'scope':'all rows scanned; assay identity, units, homology/group splits and human review NOT passed',
   'actual_n':self.n,'rows_removed':0,'sequence_length_histogram':dict(self.lengths),
   'sequence_alphabet_counts':dict(self.chars),'sequence_transformation':'NONE; raw T/U and case preserved',
   'n_unique_raw_sequences':len(self.inputs),'repeated_input_rows':self.n-len(self.inputs),
   'exact_repeated_raw_record_rows':self.n-len(self.observations),
   'inputs_with_different_target_payloads':sum(len(v)>1 for v in self.label_sets.values()),
   'target_stats':{k:v.result() for k,v in self.stats.items()},
   'target_vector_length_counts':{k:dict(v) for k,v in self.vector_lengths.items()},
   'issues':dict(self.issues),'first_issues':self.first,
   'missing_official_split':all(x[5]=='UNSPECIFIED' for x in self.identity_rows),
   'readout':self.spec.get('readout'),'assay_kind':self.spec.get('assay_kind','UNVERIFIED'),
   'units':None,'units_verified':False,'label_transformation':'NONE',
   'species_claim':self.spec.get('species_claim'),'cell_type':None,
   'admission_gate_pass':False,'admitted':False,
   'not_checked':['original assay DOI/accession and experimental identity','original label direction/units/negative generation','biological replicates and uncertainty','author original splits and gene/homology leakage','source-assay rights and human review']}


def identity_db(path):
 db=sqlite3.connect(path,timeout=60)
 db.execute('''CREATE TABLE IF NOT EXISTS samples (
 asset_id TEXT,file_sha256 TEXT,row_number INTEGER,input_hash BLOB,observation_hash BLOB,label_hash BLOB,
 gene_group TEXT,original_split TEXT,qc_mask TEXT,source_assay_key TEXT,
 PRIMARY KEY(asset_id,row_number))''')
 return db


def qc_parquet(path,spec,asset_id,output,db):
 import pyarrow,pyarrow.parquet as pq
 digest_file=sha256(path);pf=pq.ParquetFile(path)
 columns=pf.schema_arrow.names
 required={spec.get('sequence','sequence')}|set(spec.get('tracks',[]))|set(spec.get('targets',{}))
 if not required.issubset(columns):raise ValueError('missing declared columns: '+repr(required-set(columns)))
 scan=RowQC(spec);index=0
 for batch in pf.iter_batches(batch_size=64):
  for row in batch.to_pylist():index+=1;scan.add(row,index)
 if index!=pf.metadata.num_rows:raise ValueError('actual parsed row count differs from Parquet footer')
 report=scan.report();report.update(asset_id=asset_id,source_sha256=digest_file,
  parser='pyarrow record batches, all columns/all rows',parser_version=pyarrow.__version__,schema_columns=columns)
 with db:
  db.execute('DELETE FROM samples WHERE asset_id=?',(asset_id,))
  db.executemany('INSERT INTO samples VALUES (?,?,?,?,?,?,?,?,?,NULL)',
    [(asset_id,digest_file,*row) for row in scan.identity_rows])
 immutable_json(output,report)
 return report


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
 p.add_argument('--manifest',type=Path,default=ROOT/'data/audit/licensed_small_batch.csv');p.add_argument('--schemas',type=Path,default=ROOT/'configs/full_qc_schemas.json');a=p.parse_args()
 specs=json.loads(a.schemas.read_text())['packages'];rows=read_manifest(a.manifest)
 run=a.run.resolve();reports=run/'reports/sequence_qc';reports.mkdir(parents=True,exist_ok=True)
 db=identity_db(run/'reports/sequence_sample_identity.sqlite');results=[]
 with StateDB(ROOT/'run-state.sqlite') as state:
  for row in rows.values():
   if row['package_group_id'] not in specs:continue
   raw=get_target(row,ROOT/'raw_cache');key=state.ensure(row)
   if not raw.is_file() or not (raw.parent/'provenance.json').is_file():continue
   if sha256(raw)!=raw.parent.name:raise ValueError('raw checksum mismatch')
   output=reports/(row['asset_id']+'.json')
   if output.exists():report=json.loads(output.read_text())
   else:report=qc_parquet(raw,specs[row['package_group_id']],row['asset_id'],output,db)
   old=state.job(key)['stage']
   if old=='HASHED':state.transition(key,'PARSED',evidence=[str(output)])
   stage='QC_PASS' if report['state']=='PASS_FULL_FILE_SCHEMA_ONLY' else 'HOLD_QC'
   if state.job(key)['stage'] in ('PARSED','QC_PASS','HOLD_QC'):
    state.transition(key,stage,evidence=[str(output)],detail={'scope':report['scope'],'actual_n':report['actual_n'],'not_final_assay_qc':True})
   results.append({'asset_id':row['asset_id'],'package_group_id':row['package_group_id'],'report':str(output.relative_to(ROOT)),**{k:report[k] for k in ['state','actual_n','repeated_input_rows','exact_repeated_raw_record_rows','inputs_with_different_target_payloads','missing_official_split']}})
   print(json.dumps(results[-1]),flush=True)
 # Cross-task exact input reuse is reported, not deleted or called biological duplicates.
 overlap=[]
 for left,right,n in db.execute('''SELECT a.asset_id,b.asset_id,count(DISTINCT a.input_hash)
 FROM samples a JOIN samples b ON a.input_hash=b.input_hash AND a.asset_id<b.asset_id
 GROUP BY a.asset_id,b.asset_id'''):
  overlap.append({'left_asset':left,'right_asset':right,'shared_exact_raw_sequence_inputs':n,'rows_removed':0,'same_assay_verified':False})
 immutable_json(run/'reports/sequence_cross_task_overlap.json',{'comparisons':overlap,'admission_gate_pass':False,'note':'Different readouts/conditions are retained; official split/homology review remains required.'})
 immutable_json(run/'reports/sequence_qc_summary.json',{'files_scanned':len(results),'results':results,'admitted':0})
 db.close()


if __name__=='__main__':main()
