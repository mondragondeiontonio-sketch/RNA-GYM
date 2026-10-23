#!/usr/bin/env python3
"""Inspect source NPZ headers and bounded numeric labels; never load object arrays."""
import argparse,hashlib,json,math,stat,sqlite3,zipfile
from pathlib import Path,PurePosixPath
from rnagym import ROOT,immutable_json

def inspect_archive(path,expected_md5=None,max_expanded=128*1024**2,selective=False,max_numeric=4*1024**2):
 import numpy as np
 sha=hashlib.sha256();md5=hashlib.md5()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024**2),b''):sha.update(chunk);md5.update(chunk)
 if expected_md5 and md5.hexdigest()!=expected_md5:raise ValueError('upstream MD5 mismatch; not source data verification')
 report=dict(verification_status='VERIFIED_ZIP_DIRECTORY_ONLY',selective_mode=selective,inspector_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),full_archive_expanded=False,maximum_numeric_member_bytes=max_numeric,source_sha256=sha.hexdigest(),upstream_md5=md5.hexdigest(),pickle_deserialized=False,object_arrays_loaded=0,numeric_arrays_loaded=0,plain_string_arrays_loaded=0,members=[],state='HOLD_SOURCE_IDENTITY_REVIEW')
 numeric={}
 with zipfile.ZipFile(path) as z:
  infos=z.infolist()
  if len(infos)>64 or len({i.filename for i in infos})!=len(infos):raise ValueError('NPZ entry budget/duplicate member')
  total=sum(i.file_size for i in infos);report['declared_expanded_bytes']=total
  if total>max_expanded and not selective:report['state']='HOLD_EXPANSION_BUDGET';return report,numeric
  expanded_read_budget=0
  for info in infos:
   name=PurePosixPath(info.filename);mode=info.external_attr>>16
   if name.is_absolute() or '..' in name.parts or '\\' in info.filename or ':' in info.filename or stat.S_ISLNK(mode) or not info.filename.endswith('.npy'):raise ValueError('unsafe/non-NPY NPZ member')
   with z.open(info) as stream:
    version=np.lib.format.read_magic(stream)
    if version==(1,0):shape,fortran,dtype=np.lib.format.read_array_header_1_0(stream,max_header_size=8192)
    elif version==(2,0):shape,fortran,dtype=np.lib.format.read_array_header_2_0(stream,max_header_size=8192)
    else:raise ValueError('unsupported bounded NPY header version')
    header_bytes=stream.tell()
   expanded_read_budget+=16384  # Includes bounded ZipExtFile header read-ahead, not just parser-consumed bytes.
   if expanded_read_budget>max_expanded:raise ValueError('actual selected read budget exceeded')
   report['verification_status']='VERIFIED_BOUNDED_HEADERS_AND_SELECTED_PRIMITIVE_ARRAYS_ONLY'
   obj=bool(dtype.hasobject);record=dict(member=info.filename,shape=list(shape),dtype=str(dtype),contains_object=obj,loaded=False)
   if obj:record['status']='HOLD_SAFE_FORMAT_EXPORT';report['state']='HOLD_SAFE_FORMAT_EXPORT'
   elif (dtype.kind in 'biuf' or info.filename=='genes.npy' and dtype.kind in 'US') and math.prod(shape)*dtype.itemsize<=max_numeric and info.file_size<=max_numeric+8192:
    expanded_read_budget+=info.file_size
    if expanded_read_budget>max_expanded:raise ValueError('actual numeric read budget exceeded')
    # Only this previously header-validated numeric member can be loaded.
    with np.load(path,allow_pickle=False) as safe:array=safe[info.filename[:-4]]
    if array.dtype.hasobject or array.dtype.kind in 'biuf' and not np.isfinite(array).all():raise ValueError('nonfinite/non-numeric source outcome')
    numeric[info.filename[:-4]]=array;record.update(loaded=True,status='BOUNDED_NUMERIC_ARRAY_READ' if dtype.kind in 'biuf' else 'BOUNDED_PLAIN_STRING_METADATA_READ',finite_elements=int(array.size) if dtype.kind in 'biuf' else None);report['numeric_arrays_loaded']+=int(dtype.kind in 'biuf');report['plain_string_arrays_loaded']+=int(dtype.kind in 'US')
   else:record['status']='NOT_LOADED_UNNEEDED_OR_OVER_NUMERIC_BUDGET'
   report['members'].append(record)
 report['selected_expanded_read_budget_upper_bound_bytes']=expanded_read_budget
 return report,numeric

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--asset',default='ORTHRUS_MRL_ISOFORM_14708163');p.add_argument('--output',type=Path,required=True);p.add_argument('--state-db',type=Path,default=ROOT/'run-state.sqlite');p.add_argument('--selective',action='store_true',help='Do not expand archive; bounded NPY headers and <=4 MiB numeric members only');a=p.parse_args()
 with sqlite3.connect('file:'+str(a.state_db)+'?mode=ro',uri=True) as c:
  rows=c.execute('SELECT sha256,raw_path FROM artifacts WHERE asset_id=?',(a.asset,)).fetchall()
  if len(rows)!=1:raise ValueError('missing or ambiguous asset version')
  expected,path=rows[0];path=Path(path)
  if a.output.exists():
   cached=json.loads(a.output.read_text())
   if cached.get('source_sha256')!=expected or cached.get('selective_mode')!=a.selective or cached.get('inspector_code_sha256')!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():raise ValueError('checkpoint source differs')
   print(json.dumps(cached,indent=2));return
  report,arrays=inspect_archive(path,'65fb24de489e947892b2a077f89f62ba',selective=a.selective)
  if report['source_sha256']!=expected:raise ValueError('artifact SHA mismatch')
  report.update(asset_id=a.asset,task_id='T0021',admitted=False,source_license='Zenodo dataset metadata MIT; quarantine only, not human assay admission')
  if 'y' in arrays:
   import numpy as np,pyarrow.parquet as pq
   raw=c.execute('SELECT sha256,bytes,raw_path FROM artifacts WHERE asset_id=?',('HF_214a7f32ac346e79b8b1',)).fetchall()
   if len(raw)!=1:raise ValueError('ambiguous existing HF version')
   sha,n,target=raw[0]
   if Path(target).stat().st_size!=n:raise ValueError('existing target size changed; reverify bytes')
   table=pq.read_table(target,columns=['target','gene']);y=arrays['y'];values=np.asarray(table['target'].to_pylist());same_shape=y.reshape(-1).shape==values.shape
   report['acquired_target_comparison']=dict(source_target_shape=list(y.shape),acquired_target_rows=len(values),acquired_asset_sha256=sha,comparison='ROW_ORDER_NUMERIC_ONLY_NOT_ASSAY_IDENTITY',same_scalar_shape=same_shape,exact_values_after_float32_cast=int(np.equal(y.reshape(-1).astype('float32'),values.astype('float32')).sum()) if same_shape else None,source_id_condition_mapping_verified=False,benchmark_labels_changed=False)
  if 'genes' in arrays and 'y' in arrays:
   genes=arrays['genes'].reshape(-1).astype(str).tolist();ids=table['gene'].to_pylist()
   report['source_gene_metadata_comparison']=dict(safe_string_dtype=str(arrays['genes'].dtype),source_rows=len(genes),unique_source_gene_annotations=len(set(genes)),exact_row_order_matches_to_acquired_gene=sum(x==str(y) for x,y in zip(genes,ids)),not_original_transcript_or_condition_identifiers=True)
 immutable_json(a.output,report);print(json.dumps(report,indent=2))
if __name__=='__main__':main()
