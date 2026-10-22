#!/usr/bin/env python3
"""Validate molecular composite keys, not just reused source serial numbers.

No coordinates are changed, atoms removed, altloc/model chosen or assemblies
invented. This supplements (does not rewrite) the earlier coordinate scan.
"""
import argparse,collections,json,tarfile
from pathlib import Path
from rnagym import ROOT,get_target,immutable_json,read_manifest,safe_member,sha256

TAGS=['_atom_site.pdbx_PDB_model_num','_atom_site.label_asym_id','_atom_site.auth_asym_id',
 '_atom_site.label_seq_id','_atom_site.auth_seq_id','_atom_site.pdbx_PDB_ins_code',
 '_atom_site.label_comp_id','_atom_site.label_atom_id','_atom_site.label_alt_id']


def check_block(block):
 import gemmi,numpy as np
 n=len(block.find_values('_atom_site.Cartn_x'));coded=[];missing=[];normalized_seen=[]
 for tag in TAGS:
  raw_values=list(block.find_values(tag))
  if len(raw_values)!=n:
   if not raw_values:missing.append(tag);raw_values=['']*n
   else:raise ValueError('atom-key field length mismatch')
  # Decode each distinct CIF token once. Constant/redundant columns retain
  # their per-file context but need not be repeated in every row equality key.
  decoded={v:gemmi.cif.as_string(v) for v in set(raw_values)}
  values=[decoded[v] for v in raw_values]
  if len(set(values))<=1 or any(values==old for old in normalized_seen):
   continue
  normalized_seen.append(values)
  encoding={v:i for i,v in enumerate(set(values))}
  coded.append(np.fromiter((encoding[v] for v in values),dtype=np.int32,count=n))
 unique=len(np.unique(np.stack(coded,axis=1),axis=0)) if coded else int(n>0)
 serial=block.find_values('_atom_site.id')
 unique_serial={gemmi.cif.as_string(v) for v in set(serial)}
 return {'atom_rows':n,'unique_composite_atom_keys':unique,'duplicate_composite_atom_rows':n-unique,
  'reused_serial_numbers':n-len(unique_serial) if len(serial)==n else None,
  'missing_key_columns':missing,'atom_rows_removed':0}


def main():
 import gemmi
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run.resolve()
 row=next(r for r in read_manifest(ROOT/'data/audit/additional_source_assets.csv').values() if 'mmcifs' in r['relative_filename'])
 raw=get_target(row,ROOT/'raw_cache');n=0;issues=0;serial_reuse=0;atoms=0;duplicates=0;missing=collections.Counter();completed=set()
 logfile=run/'reports/rna3db_atom_identity_entries.jsonl'
 if logfile.exists():
  for line in logfile.open():
   if not line.strip():continue
   old=json.loads(line);completed.add(old['member']);n+=1;atoms+=old['atom_rows'];duplicates+=old['duplicate_composite_atom_rows'];issues+=int(old['duplicate_composite_atom_rows']>0);serial_reuse+=int(bool(old['reused_serial_numbers']));missing.update(old['missing_key_columns'])
 with tarfile.open(raw,'r|xz') as archive,logfile.open('a') as log:
  for m in archive:
   if m.isdir():continue
   safe_member(m.name,Path('/tmp/rnagym-cif-validation'))
   if not m.isfile() or m.size>128*1024**2:raise ValueError('CIF type/size budget')
   if not m.name.endswith('.cif') or m.name in completed:continue
   data=archive.extractfile(m).read();block=gemmi.cif.read_string(data.decode('utf-8'))[0]
   result=check_block(block);result['member']=m.name;log.write(json.dumps(result)+'\n')
   n+=1;atoms+=result['atom_rows'];duplicates+=result['duplicate_composite_atom_rows'];issues+=int(result['duplicate_composite_atom_rows']>0);serial_reuse+=int(bool(result['reused_serial_numbers']));missing.update(result['missing_key_columns'])
   if n%500==0:log.flush();print(json.dumps({'files_scanned':n,'files_with_duplicate_composite_keys':issues}),flush=True)
 report={'source_sha256':sha256(raw),'coordinate_files_scanned':n,'atom_rows_scanned':atoms,
  'composite_key_columns':TAGS,'completed_checkpoint_entries_reused':len(completed),'equality_implementation':'lossless per-column CIF token dictionary coding, constants and duplicate columns omitted only within one file','files_with_reused_serial_numbers':serial_reuse,'files_with_duplicate_composite_keys':issues,
  'duplicate_composite_atom_rows':duplicates,'missing_key_column_counts':dict(missing),
  'state':'ATOM_IDENTITY_REVIEW_REQUIRED' if issues else 'COMPOSITE_ATOM_KEYS_UNIQUE_SOURCE_SERIAL_REUSE_RECORDED',
  'biological_assembly_verified':False,'all_atoms_retained':True,'admission_gate_pass':False,'admitted':False}
 immutable_json(run/'reports/rna3db_atom_identity_qc.json',report);print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
