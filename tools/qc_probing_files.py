#!/usr/bin/env python3
"""Nucleotide probing QC with exact input/split checks; never pairing/3D QC.

Original reactivity/error strings remain untouched in raw. Parsed missing tokens
are QC masks only. Negative reactivity is counted, not automatically excluded.
"""
import argparse,collections,hashlib,json,math,re,sqlite3,warnings
from pathlib import Path
from rnagym import ROOT,StateDB,get_target,immutable_json,read_manifest,sha256


def vector(value):
 import numpy as np
 if isinstance(value,list):return np.asarray(value,dtype=float)
 if not isinstance(value,str):raise ValueError('reactivity must be list or serialized string')
 text=value.strip()
 if text.startswith('[') and text.endswith(']'):text=text[1:-1].strip()
 elif text.startswith('(') and text.endswith(')'):text=text[1:-1].strip()
 if not text:return np.array([],dtype=float)
 text=re.sub(r'\bNone\b','nan',text)
 sep=',' if ',' in text else ' '
 expected=len(text.split(',')) if sep==',' else len(text.split())
 with warnings.catch_warnings():
  warnings.simplefilter('error')
  arr=np.fromstring(text,sep=sep,dtype=float)
 if len(arr)!=expected:raise ValueError('partial vector parse refused')
 return arr


def hashrow(row):return hashlib.sha256(json.dumps(['RNA-GYM:probing-raw-row:v1',row],ensure_ascii=False,allow_nan=True,separators=(',',':')).encode()).digest()


def probing(raw,row,run):
 import numpy as np,pyarrow.parquet as pq
 aid=row['asset_id'];output=run/'reports/probing_qc'/(aid+'.json')
 if output.exists():return json.loads(output.read_text())
 output.parent.mkdir(parents=True,exist_ok=True);digest=sha256(raw)
 pf=pq.ParquetFile(raw);required={'seqID','sequence','modifier','reactivity','reactivity_error'}
 if not required.issubset(pf.schema_arrow.names):raise ValueError('missing probing schema')
 db=sqlite3.connect(run/'reports/probing_sample_identity.sqlite',timeout=60)
 db.execute('PRAGMA cache_size=-65536');db.execute('PRAGMA synchronous=NORMAL')
 db.execute('''CREATE TABLE IF NOT EXISTS samples(asset_id TEXT,row_number INTEGER,input_hash BLOB,observation_hash BLOB,seq_id TEXT,probe TEXT,temperature TEXT,qc_mask TEXT,file_sha256 TEXT,source_assay_key TEXT,PRIMARY KEY(asset_id,row_number))''')
 with db:db.execute('DELETE FROM samples WHERE asset_id=?',(aid,))
 issues=collections.Counter();first=[];probes=collections.Counter();nt=collections.defaultdict(collections.Counter);ranges={};batch=[];n=0;lengths=collections.Counter();metadata_missing=collections.Counter()
 for batch_arrow in pf.iter_batches(batch_size=128):
  for r in batch_arrow.to_pylist():
   n+=1;seq=r.get('sequence');mask=[];probe=str(r.get('modifier') or 'UNSPECIFIED');probes[probe]+=1
   def fail(reason):
    issues[reason]+=1;mask.append(reason)
    if len(first)<20:first.append({'row':n,'reason':reason})
   if not isinstance(seq,str) or not seq:fail('EMPTY_SEQUENCE');seq=seq if isinstance(seq,str) else ''
   lengths[len(seq)]+=1
   if not set(seq)<=set('ACGTUN'):fail('NONCANONICAL_ALPHABET')
   for c in ['reactivity','reactivity_error']:
    try:
     arr=vector(r.get(c))
     if len(arr)!=len(seq):fail('NUCLEOTIDE_LENGTH_MISMATCH:'+c)
     finite=np.isfinite(arr);sentinel=finite&(arr==-999.0)
     nt[probe][c+'_positions']+=len(arr);nt[probe][c+'_nonfinite']+=int((~finite).sum());nt[probe][c+'_raw_minus999']+=int(sentinel.sum())
     nt[probe][c+'_negative_non_sentinel']+=int((finite&~sentinel&(arr<0)).sum())
     vals=arr[finite]
     if len(vals):
      lo,hi=float(vals.min()),float(vals.max());key=probe+':'+c
      old=ranges.get(key);ranges[key]={'raw_finite_min':lo if old is None else min(lo,old['raw_finite_min']),'raw_finite_max':hi if old is None else max(hi,old['raw_finite_max'])}
    except (ValueError,TypeError,Warning):fail('VECTOR_PARSE_FAILED:'+c)
   for c in ['reads','SNR']:
    v=r.get(c)
    if v is None or not isinstance(v,(int,float)) or not math.isfinite(v):metadata_missing[c]+=1
    elif v<0:issues['NEGATIVE_METADATA:'+c]+=1
   key=hashlib.sha256(json.dumps(['RNA-GYM:raw-sequence:v1',seq],separators=(',',':')).encode()).digest()
   batch.append((aid,n,key,hashrow(r),str(r.get('seqID') or ''),probe,str(r.get('temperature') or ''),json.dumps(mask),digest))
   if len(batch)>=10000:
    with db:db.executemany('INSERT INTO samples VALUES (?,?,?,?,?,?,?,?,?,NULL)',batch)
    batch=[]
  if n and n%50000<128:print(json.dumps({'asset_id':aid,'probing_rows_scanned':n}),flush=True)
 if batch:
  with db:db.executemany('INSERT INTO samples VALUES (?,?,?,?,?,?,?,?,?,NULL)',batch)
 if n!=pf.metadata.num_rows:raise ValueError('Parquet row count mismatch')
 db.execute('CREATE INDEX IF NOT EXISTS probing_asset_input ON samples(asset_id,input_hash)');db.commit()
 unique=db.execute('SELECT count(*) FROM (SELECT input_hash FROM samples WHERE asset_id=? GROUP BY input_hash)',(aid,)).fetchone()[0]
 report={'asset_id':aid,'state':'HOLD_QC' if issues else 'PASS_FULL_FILE_NUCLEOTIDE_SCHEMA_ONLY',
  'source_sha256':digest,'actual_n':n,'schema_columns':pf.schema_arrow.names,'n_unique_raw_sequences':unique,
  'repeated_input_rows':n-unique,'rows_removed':0,'probe_distribution':dict(probes),
  'nucleotide_qc_by_probe':{k:dict(v) for k,v in nt.items()},'raw_finite_ranges':ranges,
  'metadata_missing_or_nonfinite':dict(metadata_missing),'sequence_length_histogram':dict(lengths),
  'issues':dict(issues),'first_issues':first,'sequence_transformation':'NONE; no T/U conversion',
  'missing_tokens':'NaN/nonfinite and exact raw -999 counted separately; no labels rewritten or rows filtered',
  'vector_parser':'numpy numeric token parser with full-consumption check; literal None mapped to parse-only NaN mask',
  'units_verified':False,'assay_identity_verified':False,'admission_gate_pass':False,'admitted':False,
  'not_checked':['original assay/batch/probe semantics and units','experimental replicate/uncertainty protocol','official 40-percent homology split reconstruction','full 2D base-pair structure QC (this is reactivity data)','source-specific terms and human review']}
 immutable_json(output,report);db.close();return report


def structure_table(raw,row,run):
 import pyarrow.parquet as pq
 pf=pq.ParquetFile(raw);n=0;bad=0;ids=set();columns=pf.schema_arrow.names
 for batch in pf.iter_batches(batch_size=128):
  for r in batch.to_pylist():
   n+=1;pdb=str(r.get('pdb_id') or '');chain=str(r.get('asym_chain_id') or '')
   bad+=int(not re.fullmatch(r'[0-9][A-Za-z0-9]{3}',pdb) or not chain);ids.add((pdb,chain))
 report={'asset_id':row['asset_id'],'state':'EXCLUDED_NON_ASSAY_RESULT_TABLE','artifact_role':'UPSTREAM_MODEL_RESULT_TABLE_NOT_STRUCTURE_COORDINATES',
 'source_sha256':sha256(raw),'actual_entry_count':n,'unique_pdb_chain_keys':len(ids),'invalid_pdb_chain_rows':bad,
 'columns':columns,'upstream_metric_columns_not_used_for_ranking':[c for c in columns if c not in ['pdb_id','asym_chain_id','auth_chain_id']],
 'admitted':False,'admission_gate_pass':False,'note':'Rows are upstream model evaluation results, not new measured assays or coordinate-based 3D QC.'}
 immutable_json(run/'reports'/(row['asset_id']+'-artifact-classification.json'),report);return report


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--manifest',type=Path,default=ROOT/'data/audit/full_download_assets.csv');a=p.parse_args();run=a.run.resolve();rows=read_manifest(a.manifest);results=[]
 with StateDB(ROOT/'run-state.sqlite') as state:
  for row in rows.values():
   raw=get_target(row,ROOT/'raw_cache')
   if not raw.is_file() or raw.suffix!='.parquet' or not (raw.parent/'provenance.json').is_file():continue
   if sha256(raw)!=raw.parent.name:raise ValueError('raw hash mismatch')
   if row['package_group_id']=='RNAGYM_3D':report=structure_table(raw,row,run);stage='EXCLUDED_NON_ASSAY_RESULT_TABLE'
   elif row['relative_filename']=='cluster_40.parquet':
    import pyarrow.parquet as pq
    pf=pq.ParquetFile(raw);cols=pf.schema_arrow.names
    report={'asset_id':row['asset_id'],'source_sha256':sha256(raw),'actual_n':pf.metadata.num_rows,'columns':cols,
     'state':'HOLD_CLUSTER_SCHEMA','issue':'Column names resemble RNA observation IDs and may be a data row interpreted as a header. Verify original two-column clustering source before trusting homology groups.',
     'admission_gate_pass':False,'admitted':False}
    immutable_json(run/'reports/cluster_mapping_review.json',report);stage='HOLD_SCHEMA'
   else:report=probing(raw,row,run);stage='QC_PASS' if report['state']=='PASS_FULL_FILE_NUCLEOTIDE_SCHEMA_ONLY' else 'HOLD_QC'
   key=state.ensure(row);old=state.job(key)['stage']
   if old=='HASHED':state.transition(key,'PARSED')
   state.transition(key,stage,evidence=[str(run/'reports')],detail={'scope':report['state'],'not_final_assay_qc':True})
   results.append({k:report[k] for k in ['asset_id','state','source_sha256']});print(json.dumps({**results[-1],'actual_n':report.get('actual_n',report.get('actual_entry_count'))}),flush=True)
 # Exact train/test input reuse is separate from unresolved homology grouping.
 dbpath=run/'reports/probing_sample_identity.sqlite'
 if dbpath.exists():
  db=sqlite3.connect(dbpath);db.execute('CREATE INDEX IF NOT EXISTS probing_input ON samples(input_hash)');db.commit()
  pairs=db.execute('''SELECT a.asset_id,b.asset_id,count(DISTINCT a.input_hash) FROM samples a JOIN samples b ON a.input_hash=b.input_hash AND a.asset_id<b.asset_id GROUP BY a.asset_id,b.asset_id''').fetchall()
  immutable_json(run/'reports/probing_exact_split_overlap.json',{'comparisons':[{'left_asset':x,'right_asset':y,'shared_exact_sequences':n} for x,y,n in pairs],'homology_clusters_verified':False,'admission_gate_pass':False});db.close()
 immutable_json(run/'reports/probing_qc_summary.json',{'results':results,'admitted':0})


if __name__=='__main__':main()
