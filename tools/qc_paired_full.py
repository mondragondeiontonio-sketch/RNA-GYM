#!/usr/bin/env python3
"""Streaming exact identity/leakage QC across ALL acquired paired-RNA splits.

No sequence normalization or record removal. A disk-backed sample map avoids
holding millions of rows in RAM. Exact checks do not establish assay identity,
biological negative validity, homology split compliance or human admission.
"""
import argparse,collections,csv,gzip,hashlib,itertools,json,sqlite3
from pathlib import Path
from rnagym import ROOT,StateDB,get_target,immutable_json,read_manifest,sha256
from qc_paired import hash_parts


def identity(row):
 return bytes.fromhex(hash_parts(['RNA-GYM:paired-raw:v1',row['gene'],row['noncodingRNA']]))


def row_issues(row):
 issues=[]
 if not row.get('gene') or not row.get('noncodingRNA'):issues.append('EMPTY_PAIR')
 elif not set(row['gene']+row['noncodingRNA'])<=set('ACGTUN'):issues.append('INVALID_PAIR_ALPHABET')
 if row.get('label') not in ('0','1'):issues.append('NONBINARY_LABEL')
 return issues


def connect(path):
 db=sqlite3.connect(path,timeout=60)
 db.execute('PRAGMA journal_mode=DELETE');db.execute('PRAGMA cache_size=-131072');db.execute('PRAGMA synchronous=NORMAL')
 db.executescript('''CREATE TABLE IF NOT EXISTS samples(
 asset_id TEXT,dataset_alias TEXT,original_split TEXT,file_sha256 TEXT,row_number INTEGER,
 input_hash BLOB,observation_hash BLOB,raw_label TEXT,gene_group TEXT,mirna_family TEXT,qc_mask TEXT,
 source_assay_key TEXT,PRIMARY KEY(asset_id,row_number));''')
 return db


def descriptor(row):
 name=row['relative_filename']
 aliases=['AGO2_CLASH_Hejret2023','AGO2_eCLIP_Klimentova2022','AGO2_eCLIP_Manakov2022']
 dataset=next((a for a in aliases if a in name),None)
 if not dataset:raise ValueError('unknown paired dataset alias')
 split='leftout' if 'leftout' in name else 'train' if '_train.' in name else 'test'
 return dataset,split


def scan(raw,row,db,output,max_expanded=8*1024**3):
 digest=sha256(raw);aid=row['asset_id'];dataset,split=descriptor(row)
 if output.exists():
  doc=json.loads(output.read_text())
  if doc['source_sha256']!=digest:raise ValueError('checkpoint raw hash changed')
  if db.execute('SELECT count(*) FROM samples WHERE asset_id=?',(aid,)).fetchone()[0]!=doc['actual_n']:raise ValueError('identity DB/checkpoint disagree')
  return doc
 with db:db.execute('DELETE FROM samples WHERE asset_id=?',(aid,))
 labels=collections.Counter();issues=collections.Counter();seq_lengths=collections.Counter();mir_lengths=collections.Counter();first=[];expanded=0;n=0;batch=[]
 with gzip.open(raw,'rt',encoding='utf-8-sig',newline='') as source:
  def lines():
   nonlocal expanded
   while True:
    line=source.readline(1024*1024+1)
    if not line:break
    if len(line)>1024*1024:raise ValueError('decompressed line budget exceeded')
    expanded+=len(line.encode())
    if expanded>max_expanded:raise ValueError('decompression budget exceeded')
    yield line
  reader=csv.DictReader(lines(),delimiter='\t' if '.tsv' in raw.name else ',')
  if not {'gene','noncodingRNA','label'}.issubset(reader.fieldnames or []):raise ValueError('paired schema missing')
  fields=reader.fieldnames
  for n,r in enumerate(reader,1):
   errors=row_issues(r);issues.update(errors)
   if errors and len(first)<20:first.append({'row':n,'issues':errors})
   labels[r.get('label')]+=1;seq_lengths[len(r.get('gene') or '')]+=1;mir_lengths[len(r.get('noncodingRNA') or '')]+=1
   # The source row is preserved by raw file+row and this full-field digest.
   obs=hashlib.sha256(json.dumps(['RNA-GYM:raw-row:v1',[(c,r.get(c)) for c in fields]],ensure_ascii=False,separators=(',',':')).encode()).digest()
   batch.append((aid,dataset,split,digest,n,identity(r),obs,r.get('label'),r.get('gene_cluster_ID') or '',r.get('noncodingRNA_fam') or '',json.dumps(errors)))
   if len(batch)>=20000:
    with db:db.executemany('INSERT INTO samples VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)',batch)
    batch=[]
  if batch:
   with db:db.executemany('INSERT INTO samples VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)',batch)
 report={'asset_id':aid,'dataset_alias':dataset,'original_split':split,'source_sha256':digest,'actual_n':n,
  'label_distribution':dict(labels),'row_issues':dict(issues),'first_issues':first,
  'target_length_counts':dict(seq_lengths),'mirna_length_counts':dict(mir_lengths),'expanded_bytes_read':expanded,
  'sequence_transformation':'NONE; exact ordered RNA roles, T/U and case preserved',
  'identity_hash':'SHA-256 of UTF-8 compact JSON [RNA-GYM:paired-raw:v1,target,miRNA]',
  'scope':'all rows parsed; exact identity and leakage pending aggregation','admitted':False,'admission_gate_pass':False}
 immutable_json(output,report)
 print(json.dumps({'asset_id':aid,'stage':'ALL_ROWS_SCANNED','actual_n':n,'issues':dict(issues)}),flush=True)
 return report


def overlaps(db):
 counts=collections.Counter();conflicts=collections.Counter();within_split=set()
 query='''SELECT input_hash FROM samples GROUP BY input_hash HAVING count(DISTINCT asset_id)>1'''
 for (key,) in db.execute(query):
  members=db.execute('SELECT DISTINCT asset_id,dataset_alias,original_split,raw_label FROM samples WHERE input_hash=?',(key,)).fetchall()
  by_asset=collections.defaultdict(set);meta={}
  for aid,dataset,split,label in members:by_asset[aid].add(label);meta[aid]=(dataset,split)
  for left,right in itertools.combinations(sorted(by_asset),2):
   pair=(left,right);counts[pair]+=1
   if by_asset[left]!=by_asset[right]:conflicts[pair]+=1
   if meta[left][0]==meta[right][0] and meta[left][1]!=meta[right][1]:within_split.update(pair)
 return [{'left_asset':a,'right_asset':b,'shared_exact_ordered_pairs':n,
   'label_disagreement_pairs':conflicts[(a,b)],'same_assay_verified':False,'rows_removed':0}
   for (a,b),n in sorted(counts.items())],within_split


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
 p.add_argument('--manifest',type=Path,default=ROOT/'data/audit/p0_assets.csv');p.add_argument('--export-parquet',action='store_true');a=p.parse_args()
 run=a.run.resolve();folder=run/'reports/paired_full_qc';folder.mkdir(parents=True,exist_ok=True)
 db=connect(run/'reports/paired_sample_identity.sqlite');docs=[];manifest=read_manifest(a.manifest)
 for row in manifest.values():
  if row['package_group_id']!='MIR_BENCH' or not row['relative_filename'].endswith('.gz'):continue
  raw=get_target(row,ROOT/'raw_cache')
  if not raw.is_file() or not (raw.parent/'provenance.json').is_file():continue
  if sha256(raw)!=raw.parent.name:raise ValueError('immutable raw hash mismatch')
  docs.append(scan(raw,row,db,folder/(row['asset_id']+'-scan.json')))
 print('BUILDING_IDENTITY_INDEXES',flush=True)
 db.execute('CREATE INDEX IF NOT EXISTS paired_input ON samples(input_hash)')
 db.execute('CREATE INDEX IF NOT EXISTS paired_asset_input ON samples(asset_id,input_hash)');db.commit()
 comparisons,leaky_assets=overlaps(db)
 immutable_json(run/'reports/paired_all_split_overlap.json',{'comparisons':comparisons,'exact_split_leakage_assets':sorted(leaky_assets),
    'scope':'All acquired paired files; group/homology and original experimental identity unresolved',
    'rows_removed':0,'admission_gate_pass':False})
 summary=[]
 with StateDB(ROOT/'run-state.sqlite') as state:
  for doc in docs:
   aid=doc['asset_id'];n=doc['actual_n']
   unique=db.execute('SELECT count(*) FROM (SELECT input_hash FROM samples WHERE asset_id=? GROUP BY input_hash)',(aid,)).fetchone()[0]
   unique_records=db.execute('SELECT count(*) FROM (SELECT observation_hash FROM samples WHERE asset_id=? GROUP BY observation_hash)',(aid,)).fetchone()[0]
   contradictory=db.execute('SELECT count(*) FROM (SELECT input_hash FROM samples WHERE asset_id=? GROUP BY input_hash HAVING count(DISTINCT raw_label)>1)',(aid,)).fetchone()[0]
   groups={}
   for col in ['gene_group','mirna_family']:
    groups[col]=db.execute(f'''SELECT count(*) FROM (SELECT {col} FROM samples WHERE dataset_alias=? AND {col}!='' GROUP BY {col} HAVING count(DISTINCT original_split)>1)''',(doc['dataset_alias'],)).fetchone()[0]
   result={**doc,'n_unique_ordered_pairs':unique,'repeated_input_rows':n-unique,
    'exact_repeated_raw_rows':n-unique_records,'pairs_with_conflicting_labels':contradictory,
    'groups_shared_across_original_splits':groups,'exact_split_leakage_detected':aid in leaky_assets,
    'state':'HOLD_EXACT_SPLIT_LEAKAGE' if aid in leaky_assets else 'ROW_QC_ISSUES_DETECTED' if doc['row_issues'] else 'PASS_FULL_FILE_EXACT_PAIRED_QC_ONLY',
    'scope':'all rows, exact inputs/records/labels and cross-file exact split overlap scanned; not full biological assay QC',
    'not_checked':['original assay/accession/construct/condition identity','negative generation and experimental label semantics','homology-level leakage and split policy compliance','source rights and human review']}
   output=folder/(aid+'-qc.json');immutable_json(output,result)
   key=state.ensure(manifest[aid]);old=state.job(key)['stage']
   if old=='HASHED':state.transition(key,'PARSED',evidence=[str(output)])
   stage='HOLD_LEAKAGE' if aid in leaky_assets else 'HOLD_QC' if doc['row_issues'] else 'QC_PASS'
   if state.job(key)['stage'] in ['PARSED','QC_PASS','HOLD_QC','HOLD_LEAKAGE']:state.transition(key,stage,evidence=[str(output)],detail={'scope':result['scope'],'actual_n':n,'not_final_assay_qc':True})
   summary.append({k:result[k] for k in ['asset_id','dataset_alias','original_split','actual_n','n_unique_ordered_pairs','repeated_input_rows','exact_repeated_raw_rows','pairs_with_conflicting_labels','groups_shared_across_original_splits','state']})
   print(json.dumps(summary[-1]),flush=True)
 if a.export_parquet:
  import pyarrow as pa,pyarrow.parquet as pq
  cursor=db.execute('SELECT asset_id,dataset_alias,original_split,file_sha256,row_number,input_hash,observation_hash,raw_label,gene_group,mirna_family,qc_mask,source_assay_key FROM samples')
  names=[d[0] for d in cursor.description];writer=None
  try:
   while True:
    rows=cursor.fetchmany(20000)
    if not rows:break
    table=pa.Table.from_pydict({name:[r[i] for r in rows] for i,name in enumerate(names)},schema=None if writer is None else writer.schema)
    if writer is None:writer=pq.ParquetWriter(run/'reports/sample_identity_map.parquet',table.schema,compression='zstd')
    writer.write_table(table)
  finally:
   if writer:writer.close()
 immutable_json(run/'reports/paired_full_qc_summary.json',{'files_scanned':len(summary),'actual_file_rows_including_versions':sum(d['actual_n'] for d in summary),'results':summary,'admitted':0,'rows_removed':0})
 db.close()


if __name__=='__main__':main()
