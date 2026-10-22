#!/usr/bin/env python3
"""Reassemble author's downstream-data parts after upstream SHA256 verification.

Binary lossless reassembly only. This does not derive experimental labels,
rewrite raw chunks, unpack data, approve rights for redistribution, or train.
"""
import argparse,csv,hashlib,json,re
from pathlib import Path
from rnagym import ROOT,StateDB,get_target,immutable_json,read_manifest,sha256,verify,now


def checksums(text):
 result={}
 for line in text.splitlines():
  m=re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?([^\s]+)',line.strip())
  if not m:raise ValueError('invalid author SHA256SUMS line')
  result[m[2]]=m[1].lower()
 return result


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',required=True,type=Path);a=p.parse_args();run=a.run.resolve()
 manifest=read_manifest(ROOT/'data/audit/additional_source_assets.csv');rows=[r for r in manifest.values() if r['package_group_id']=='EUKAUTR']
 checksum_row=next(r for r in rows if r['relative_filename'].endswith('parts_SHA256SUMS.txt'))
 full_row=next(r for r in rows if r['relative_filename'].endswith('.tar.gz.sha256'))
 checksum_file=get_target(checksum_row,ROOT/'raw_cache');full_file=get_target(full_row,ROOT/'raw_cache')
 expected_parts=checksums(checksum_file.read_text());expected_full=checksums(full_file.read_text())
 parts=sorted([r for r in rows if re.search(r'\.part-\d+$',r['relative_filename'])],key=lambda r:r['relative_filename'])
 if len(parts)!=5 or set(r['relative_filename'] for r in parts)!=set(expected_parts):raise ValueError('author multipart list must match exactly5known parts')
 input_evidence=[]
 for r in parts:
  path=get_target(r,ROOT/'raw_cache');actual=sha256(path)
  if actual!=expected_parts[r['relative_filename']] or actual!=path.parent.name:raise ValueError('part hash mismatch')
  input_evidence.append({'asset_id':r['asset_id'],'part_name':r['relative_filename'],'sha256':actual,'bytes':path.stat().st_size})
 name='downstream_data_20260813.tar.gz';expected=expected_full[name]
 row={'asset_id':'EUKA_DOWNSTREAM_ASSEMBLED','package_group_id':'EUKAUTR','relative_filename':name,
      'direct_url':'https://zenodo.org/records/21790090','official_source_url':'https://zenodo.org/records/21790090',
      'transport_role':'AUTHOR_MULTIPART_REASSEMBLY','release_tag':'21790090/downstream_data_20260813',
      'upstream_commit':'','sha256_expected':expected,'sha256_pin_basis':'AUTHOR_UPSTREAM_FULL_ARCHIVE_SHA256_FILE',
      'rights_status':'REVIEW_REQUIRED','size_band':'LOSSLESS_LOCAL_ASSEMBLY','qc_modality':'downstream_archive'}
 folder=ROOT/'raw_cache/quarantine'/row['package_group_id']/row['asset_id'];target=folder/expected/name;folder.mkdir(parents=True,exist_ok=True)
 with StateDB(ROOT/'run-state.sqlite') as state:
  key=state.ensure(row)
  if not target.exists():
   state.transition(key,'FETCHING',detail={'method':'LOSSLESS_BINARY_REASSEMBLY_NOT_NETWORK'})
   part=folder/(name+'.part');h=hashlib.sha256()
   with part.open('wb') as dst:
    for r in parts:
     with get_target(r,ROOT/'raw_cache').open('rb') as src:
      for block in iter(lambda:src.read(1024**2),b''):dst.write(block);h.update(block);state.heartbeat(key)
   if h.hexdigest()!=expected:raise ValueError('full archive differs from author SHA256')
   target.parent.mkdir(exist_ok=True);part.rename(target);target.chmod(0o444)
   rights=json.loads((ROOT/'data/audit/rights_decisions.json').read_text())[parts[0]['asset_id']]
   receipt={'asset_id':row['asset_id'],'package_group_id':'EUKAUTR','observed_sha256':expected,'bytes':target.stat().st_size,
     'expected_sha256':expected,'requested_url':row['direct_url'],'downloaded_at_utc':now(),'rights':rights,
     'acquisition_method':'AUTHOR_MULTIPART_REASSEMBLY','assembly_inputs':input_evidence,
     'author_part_manifest_sha256':sha256(checksum_file),'author_full_manifest_sha256':sha256(full_file),
     'acquisition_state':'QUARANTINED','admitted':False}
   immutable_json(target.parent/'download.json',receipt);(folder/'latest.json').write_text(json.dumps({'sha256':expected})+'\n')
   state.artifact(row['asset_id'],expected,target);state.transition(key,'DOWNLOADED',digest=expected,evidence=[str(target.parent/'download.json')])
  result=verify(row,ROOT/'raw_cache',db=state)
 with (ROOT/'data/audit/assembled_assets.csv').open('w',newline='') as f:w=csv.DictWriter(f,list(row));w.writeheader();w.writerow(row)
 immutable_json(run/'reports/multipart_assembly.json',{'state':'AUTHOR_PART_AND_FULL_SHA256_MATCH','assembly_inputs':input_evidence,'output_sha256':expected,'output_bytes':target.stat().st_size,'admitted':False})
 print(json.dumps(result),flush=True)


if __name__=='__main__':main()
