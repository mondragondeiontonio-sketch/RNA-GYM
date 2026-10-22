#!/usr/bin/env python3
"""Finish safe-format QC of held text/Excel/profile/nested gzip members.

Pickles are disassembled ONLY with pickletools, NEVER unpickled or executed.
Unknown biological semantics remain explicit holds despite successful parsing.
"""
import argparse,collections,csv,gzip,hashlib,io,json,math,pickletools,re,tarfile,zipfile
from pathlib import Path
from rnagym import ROOT,get_target,immutable_json,read_manifest,safe_member


def table(stream,name,sep='\t',max_bytes=16*1024**3):
 size=0;h=hashlib.sha256();n=0;ragged=0;stats={};fields=None
 def lines():
  nonlocal size
  first=True
  while True:
   raw=stream.readline(16*1024**2+1)
   if not raw:break
   if len(raw)>16*1024**2:raise ValueError('text line cap')
   size+=len(raw)
   if size>max_bytes:raise ValueError('nested expansion cap')
   h.update(raw);yield raw.decode('utf-8-sig' if first else 'utf-8');first=False
 reader=csv.reader(lines(),delimiter=sep)
 fields=next(reader,[])
 if not fields:raise ValueError('empty table')
 for n,row in enumerate(reader,1):
  ragged+=int(len(row)!=len(fields))
  for col,value in zip(fields,row):
   st=stats.setdefault(col,{'numeric':0,'nonfinite':0,'missing':0,'nonnumeric':0,'min':None,'max':None})
   if value=='':st['missing']+=1;continue
   try:x=float(value)
   except (TypeError,ValueError):st['nonnumeric']+=1;continue
   if not math.isfinite(x):st['nonfinite']+=1;continue
   st['numeric']+=1;st['min']=x if st['min'] is None else min(st['min'],x);st['max']=x if st['max'] is None else max(st['max'],x)
 return {'member':name,'state':'TABLE_FULLY_PARSED_ASSAY_SCHEMA_REVIEW_PENDING','actual_rows':n,'row_unit':'file records, not independently verified assay observations','fields':fields,'ragged_rows':ragged,'column_value_types_and_ranges':stats,'expanded_bytes_read':size,'member_sha256':h.hexdigest(),'labels_transformed':False,'rows_removed':0,'admission_gate_pass':False}


def inspect(stream,name):
 lower=name.lower()
 if lower.endswith('.tsv.gz'):
  with gzip.GzipFile(fileobj=stream) as gz:return table(gz,name)
 if lower.endswith('.txt'):
  return table(stream,name)
 if lower.endswith('.xls'):
  import xlrd
  raw=stream.read(128*1024**2+1)
  if len(raw)>128*1024**2:raise ValueError('xls size cap')
  book=xlrd.open_workbook(file_contents=raw,on_demand=True);sheets=[]
  try:
   for sheet in book.sheets():
    cells=0;nonfinite=0
    for row in sheet.get_rows():
     for c in row:
      if c.ctype==xlrd.XL_CELL_NUMBER:cells+=1;nonfinite+=int(not math.isfinite(c.value))
    sheets.append({'name':sheet.name,'rows_including_headers':sheet.nrows,'columns':sheet.ncols,'numeric_cells':cells,'nonfinite_numeric_cells':nonfinite})
  finally:book.release_resources()
  return {'member':name,'state':'XLS_VALUES_PARSED_ASSAY_SCHEMA_PENDING','sheets':sheets,'macros_or_formulas_executed':False,'admission_gate_pass':False}
 if lower.endswith('.hmm'):
  data=stream.read(8*1024**2+1)
  if len(data)>8*1024**2:raise ValueError('profile budget')
  text=data.decode('utf-8');meta={}
  for line in text.splitlines():
   parts=line.split(maxsplit=1)
   if parts and parts[0] in ['NAME','ACC','LENG','ALPH']:meta[parts[0]]=parts[1] if len(parts)>1 else ''
  return {'member':name,'state':'PROFILE_ANNOTATION_NOT_EXPERIMENTAL_ASSAY','format_header_valid':text.startswith('HMMER'),'end_marker_valid':text.rstrip().endswith('//'),'profile_metadata':meta,'profile_executed':False,'admission_gate_pass':False}
 if lower.endswith('.clstr'):
  groups=0;members=0;unknown=0
  for raw in stream:
   line=raw.decode('utf-8').strip()
   if line.startswith('>Cluster '):groups+=1
   elif line and re.match(r'\d+\s+',line):members+=1
   elif line:unknown+=1
  return {'member':name,'state':'AUTHOR_CLUSTER_TEXT_PARSED_MAPPING_REVIEW_PENDING','cluster_count':groups,'member_records':members,'unrecognized_lines':unknown,'threshold_fitted_or_optimized':False,'admission_gate_pass':False}
 if lower.endswith('.id'):
  values=[line.strip() for line in stream if line.strip()]
  return {'member':name,'state':'SOURCE_SAMPLE_INDEX_NOT_ASSAY','id_records':len(values),'unique_ids':len(set(values)),'admission_gate_pass':False}
 if lower.endswith('.pkl'):
  data=stream.read(128*1024**2+1)
  if len(data)>128*1024**2:raise ValueError('static pickle inspection cap')
  counts=collections.Counter();globals_seen=set();ops=0
  for opcode,arg,pos in pickletools.genops(data):
   ops+=1
   if ops>50000000:raise ValueError('pickle opcode budget')
   counts[opcode.name]+=1
   if opcode.name=='GLOBAL':globals_seen.add(str(arg))
  return {'member':name,'state':'HOLD_SAFE_FORMAT_EXPORT_FOR_BIOLOGICAL_QC','format_integrity':'PICKLE_OPCODES_PARSED_WITHOUT_EXECUTION','opcode_count':ops,'opcode_types':dict(counts),'global_symbol_names_not_loaded':sorted(globals_seen),'unpickled_or_code_executed':False,'semantic_data_loaded':False,'next_action':'Obtain CSV/NPZ/Parquet export or explicitly reviewed isolated loader before structural/label QC.','admission_gate_pass':False}
 raise ValueError('unsupported supplemental type')


def cmscan(raw,row,run):
 members=0;hits=0;bad=0;no_hits=0;families=set();verbose=[]
 with tarfile.open(raw,'r|gz') as tar:
  for m in tar:
   if m.isdir():continue
   safe_member(m.name,Path('/tmp/rnagym-supplemental-validation'))
   if not m.isfile():raise ValueError('cmscan links/special entries refused')
   if not m.name.endswith('.tbl'):
    verbose.append({'member':m.name,'bytes':m.size,'role':'EXISTING_VERBOSE_PROFILE_OUTPUT_NOT_ASSAY_NOT_EXECUTED'})
    continue
   if m.size>16*1024**2:raise ValueError('cmscan table member budget exceeded')
   members+=1;this_hits=0
   for line in tar.extractfile(m):
    line=line.decode('utf-8').strip()
    if not line or line.startswith('#'):continue
    bits=line.split(maxsplit=17)
    if len(bits)<17:bad+=1;continue
    try:
     score=float(bits[14]);evalue=float(bits[15])
     if not math.isfinite(score) or not math.isfinite(evalue) or evalue<0:bad+=1
    except ValueError:bad+=1
    if re.fullmatch(r'RF\d+',bits[1]):families.add(bits[1])
    hits+=1;this_hits+=1
   no_hits+=int(this_hits==0)
 report={'asset_id':row['asset_id'],'state':'CMSCAN_ANNOTATION_SCHEMA_SCANNED_NOT_ASSAY','files_scanned':members,'hit_records':hits,'malformed_or_nonfinite_hits':bad,'no_hit_files':no_hits,'rfam_accession_count':len(families),'verbose_output_artifacts_excluded':verbose,'external_profile_program_run':False,'admission_gate_pass':False,'admitted':False}
 immutable_json(run/'reports/rna3db_cmscan_qc.json',report);return report


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run.resolve();rows={}
 for name in ['p0_assets.csv','full_download_assets.csv','additional_source_assets.csv','assembled_assets.csv']:
  f=ROOT/'data/audit'/name
  if f.exists():rows.update(read_manifest(f))
 results=[]
 for path in sorted((run/'reports/archive_qc').glob('*.json')):
  old=json.loads(path.read_text());aid=old['asset_id'];held=[h for h in old['held_members'] if h['state'].startswith('HOLD') and not h['member'].endswith('.parquet')]
  if not held:continue
  output=run/'reports'/('supplemental-'+aid+'.json')
  if output.exists():results.append(json.loads(output.read_text()));continue
  raw=get_target(rows[aid],ROOT/'raw_cache');zip_mode=zipfile.is_zipfile(raw);archive=zipfile.ZipFile(raw) if zip_mode else tarfile.open(raw,'r:gz');records=[]
  try:
   for h in held:
    name=h['member'];safe_member(name,Path('/tmp/rnagym-supplemental-validation'))
    try:
     with (archive.open(name) if zip_mode else archive.extractfile(name)) as stream:records.append(inspect(stream,name))
    except Exception as e:records.append({'member':name,'state':'HOLD_FORMAT_OR_SCHEMA','error':type(e).__name__+': '+str(e)[:200],'admission_gate_pass':False})
  finally:archive.close()
  doc={'asset_id':aid,'members':records,'admission_gate_pass':False,'admitted':False};immutable_json(output,doc);results.append(doc)
 for row in rows.values():
  if 'rna3db-cmscans' in row['relative_filename']:
   raw=get_target(row,ROOT/'raw_cache')
   if raw.is_file() and not (run/'reports/rna3db_cmscan_qc.json').exists():cmscan(raw,row,run)
 immutable_json(run/'reports/supplemental_format_qc_summary.json',{'assets':results,'admitted':0,'unsafe_code_executed':False})
 print(json.dumps({'supplemental_archive_assets':len(results),'members_inspected':sum(len(d['members']) for d in results),'unsafe_pickle_execution':False}),flush=True)


if __name__=='__main__':main()
