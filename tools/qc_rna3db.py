#!/usr/bin/env python3
"""RNA3DB version/sample and streaming mmCIF QC. No adoption or score generation.

PDB-chain IDs and raw residue names are preserved. Assemblies/models/altlocs are
reported, not silently collapsed. Metadata and coordinate checks stay distinct.
"""
import argparse,collections,hashlib,heapq,json,math,re,tarfile
from pathlib import Path
from rnagym import ROOT,StateDB,get_target,immutable_json,read_manifest,safe_member,sha256


def read_json_bundle(raw):
 docs={}
 with tarfile.open(raw,'r:gz') as tar:
  for member in tar:
   if member.isdir():continue
   safe_member(member.name,Path('/tmp/rnagym-rna3db-validation'))
   if not member.isfile() or member.size>256*1024**2:raise ValueError('JSON bundle entry type/size refused')
   if member.name.endswith('.json'):docs[Path(member.name).name]=json.load(tar.extractfile(member))
 return docs


def validate_jsons(docs):
 parsed=docs['parse.json'];filtered=docs['filter.json'];clusters=docs['cluster.json'];split=docs['split.json']
 if not all(isinstance(x,dict) for x in [parsed,filtered,clusters,split]):raise ValueError('RNA3DB dict schemas required')
 issues=collections.Counter();alphabet=collections.Counter();resolutions=collections.Counter();methods=collections.Counter()
 for chain,meta in parsed.items():
  if not re.fullmatch(r'[0-9][A-Za-z0-9]{3}_.+',chain):issues['BAD_PDB_CHAIN_ID']+=1
  seq=meta.get('sequence');length=meta.get('length')
  if not isinstance(seq,str):issues['MISSING_SEQUENCE']+=1;continue
  alphabet.update(seq)
  if len(seq)!=length:issues['LENGTH_METADATA_MISMATCH']+=1
  methods[str(meta.get('structure_method'))]+=1
  resolution=meta.get('resolution')
  resolutions['missing_or_not_numeric' if not isinstance(resolution,(int,float)) else 'nonfinite' if not math.isfinite(resolution) else 'finite']+=1
 if not set(filtered)<=set(parsed):issues['FILTER_IDS_NOT_IN_PARSE']+=len(set(filtered)-set(parsed))
 component_for={};component_reuse=0
 for component,chains in clusters.items():
  for key in chains:
   if key in component_for:component_reuse+=1
   component_for[key]=component
 sets={};components={}
 for label,groups in split.items():
  components[label]=set(groups);sets[label]={key for members in groups.values() for key in members}
 pair_overlap=[]
 labels=sorted(sets)
 for i,a in enumerate(labels):
  for b in labels[i+1:]:pair_overlap.append({'left':a,'right':b,'shared_exact_chain_ids':len(sets[a]&sets[b]),'shared_component_ids':len(components[a]&components[b])})
 return {'parse_chain_count':len(parsed),'filtered_chain_count':len(filtered),'component_count':len(clusters),
  'chains_reused_across_components':component_reuse,'original_split_chain_counts':{k:len(v) for k,v in sets.items()},
  'original_split_component_counts':{k:len(v) for k,v in components.items()},'original_split_overlap':pair_overlap,
  'raw_sequence_alphabet_counts':dict(alphabet),'experimental_method_claims':dict(methods),'resolution_metadata_counts':dict(resolutions),
  'schema_issues':dict(issues),'raw_sequences_transformed':False,'admission_gate_pass':False,'admitted':False}


def compare_versions(old,new):
 result={}
 for kind in ['parse.json','filter.json']:
  a,b=old[kind],new[kind];shared=set(a)&set(b)
  changed=[key for key in shared if a[key].get('sequence')!=b[key].get('sequence')]
  result[kind]={'old_ids':len(a),'new_ids':len(b),'added_chain_ids':sorted(set(b)-set(a)),
   'removed_chain_ids':sorted(set(a)-set(b)),'shared_chain_ids_with_changed_raw_sequence':sorted(changed),
   'pdb_id_added':sorted({x.split('_',1)[0] for x in b}-{x.split('_',1)[0] for x in a}),
   'pdb_id_removed':sorted({x.split('_',1)[0] for x in a}-{x.split('_',1)[0] for x in b})}
 result.update(selected_version=None,freeze_status='VERSION_DIFF_COMPUTED_HUMAN_REVIEW_REQUIRED',
  canonicalization='Exact upstream chain key and sequence strings; no T/U or case replacement',admission_gate_pass=False)
 return result


def cif_check(text,name):
 import gemmi,numpy as np
 doc=gemmi.cif.read_string(text)
 if len(doc)!=1:raise ValueError('expected one CIF data block per structure')
 block=doc[0];dec=gemmi.cif.as_string
 def values(tag):return [dec(v) for v in block.find_values(tag)]
 def single(tag):
  value=block.find_value(tag);return dec(value) if value else None
 x=block.find_values('_atom_site.Cartn_x');y=block.find_values('_atom_site.Cartn_y');z=block.find_values('_atom_site.Cartn_z');n=len(x)
 if not n or len(y)!=n or len(z)!=n:raise ValueError('missing/inconsistent coordinate arrays')
 if n>3000000:raise ValueError('atom-row budget exceeded')
 nonfinite=0
 for col in [x,y,z]:
  arr=np.fromiter((float(dec(v)) for v in col),dtype=float,count=n);nonfinite+=int((~np.isfinite(arr)).sum())
 models=set(values('_atom_site.pdbx_PDB_model_num'));chains=set(values('_atom_site.label_asym_id'))
 auth_chains=set(values('_atom_site.auth_asym_id'));altloc=collections.Counter(values('_atom_site.label_alt_id'))
 ids=values('_atom_site.id');residues=collections.Counter(values('_atom_site.label_comp_id'))
 entities=values('_entity_poly.entity_id');polytypes=values('_entity_poly.type');polymer=dict(zip(entities,polytypes))
 rna_entities=[k for k,v in polymer.items() if 'ribonucleotide' in v and 'deoxy' not in v]
 hybrid=[k for k,v in polymer.items() if 'hybrid' in v or ('deoxy' in v and 'ribo' in v)]
 modified={k:v for k,v in residues.items() if k not in {'A','C','G','U','DA','DC','DG','DT','HOH'}}
 return {'member':name,'entry_id':single('_entry.id'),'atom_rows':n,'nonfinite_coordinate_values':nonfinite,
   'duplicate_atom_site_ids':n-len(set(ids)) if len(ids)==n else None,
   'model_ids':sorted(models),'label_chain_ids':sorted(chains),'auth_chain_ids':sorted(auth_chains),
   'assembly_ids':values('_pdbx_struct_assembly.id'),'assembly_details':values('_pdbx_struct_assembly.details'),
   'assembly_or_model_selected':False,'altloc_atom_counts':dict(altloc),'polymer_types':polymer,
   'rna_entity_ids':rna_entities,'hybrid_entity_ids':hybrid,'nonstandard_residue_atom_counts':modified,
   'experimental_methods':values('_exptl.method'),'modified_residues_mapped_to_canonical':False,
   'state':'HOLD_NONFINITE_COORDINATES' if nonfinite else 'PASS_COORDINATE_SCHEMA_ONLY',
   'admission_gate_pass':False}


def coordinate_archive(raw,row,run):
 output=run/'reports/rna3db_coordinate_summary.json'
 if output.exists():return json.loads(output.read_text())
 entry_log=run/'reports/rna3db_coordinate_entries.jsonl';n=0;held=0;atom_rows=0;expanded=0;methods=collections.Counter();models=collections.Counter()
 with tarfile.open(raw,'r|xz') as tar,entry_log.open('w') as log:
  for member in tar:
   if member.isdir():continue
   safe_member(member.name,Path('/tmp/rnagym-rna3db-validation'))
   if not member.isfile():raise ValueError('CIF archive link/special entry refused')
   expanded+=member.size
   if expanded>128*1024**3:raise ValueError('128GiB streamed expansion budget exceeded')
   if member.size>128*1024**2:
    held+=1;log.write(json.dumps({'member':member.name,'state':'HOLD_RESOURCE_PER_CIF_128MIB','declared_bytes':member.size})+'\n');continue
   if not member.name.endswith(('.cif','.mmcif')):
    held+=1;log.write(json.dumps({'member':member.name,'state':'HOLD_NON_CIF_FORMAT'})+'\n');continue
   n+=1
   try:
    data=tar.extractfile(member).read(member.size+1)
    if len(data)!=member.size:raise ValueError('CIF member truncated')
    report=cif_check(data.decode('utf-8'),member.name);report['member_sha256']=hashlib.sha256(data).hexdigest()
    atom_rows+=report['atom_rows'];models[str(len(report['model_ids']))]+=1;methods.update(report['experimental_methods'])
    if report['state']!='PASS_COORDINATE_SCHEMA_ONLY':held+=1
   except Exception as e:held+=1;report={'member':member.name,'state':'HOLD_CIF_PARSE_OR_SCHEMA','error':type(e).__name__+': '+str(e)[:200]}
   log.write(json.dumps(report)+'\n')
   if n%250==0:log.flush();print(json.dumps({'asset_id':row['asset_id'],'coordinate_files_scanned':n,'held':held}),flush=True)
 report={'asset_id':row['asset_id'],'source_sha256':sha256(raw),'state':'COORDINATE_SCHEMA_SCAN_COMPLETE_ASSAY_REVIEW_PENDING',
   'coordinate_files_scanned':n,'files_held':held,'atom_rows_scanned':atom_rows,'expanded_bytes_streamed':expanded,
   'experimental_method_claims':dict(methods),'model_count_distribution':dict(models),
   'not_checked':['biological assembly selection and original experimental identity','Rfam/3D homology and cross-benchmark matching','complete stereochemistry/physical clash validation','source-assay and human admission review'],
   'admission_gate_pass':False,'admitted':False,'model_predictions_or_scores_generated':False}
 immutable_json(output,report);return report


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--coordinates',action='store_true');a=p.parse_args();run=a.run.resolve();rows=read_manifest(ROOT/'data/audit/additional_source_assets.csv');bundles={}
 for row in rows.values():
  if row['package_group_id']!='RNA3DB':continue
  raw=get_target(row,ROOT/'raw_cache')
  if not raw.is_file() or not (raw.parent/'provenance.json').is_file():continue
  if sha256(raw)!=raw.parent.name:raise ValueError('raw hash mismatch')
  if 'jsons' in row['relative_filename']:
   docs=read_json_bundle(raw);bundles[row['release_tag']]=docs;report=validate_jsons(docs)
   report.update(source_sha256=raw.parent.name,release_tag=row['release_tag'],asset_id=row['asset_id'])
   immutable_json(run/'reports'/('rna3db-metadata-'+row['release_tag']+'.json'),report)
   with StateDB(ROOT/'run-state.sqlite') as state:
    key=state.ensure(row)
    if state.job(key)['stage']=='HASHED':state.transition(key,'PARSED')
    state.transition(key,'HOLD_QC' if report['schema_issues'] else 'QC_PASS',detail={'scope':'PDB-chain metadata and official split membership only','not_full_assay_qc':True},evidence=[str(run/'reports'/('rna3db-metadata-'+row['release_tag']+'.json'))])
   print(json.dumps({k:report[k] for k in ['release_tag','parse_chain_count','filtered_chain_count','component_count','schema_issues']}),flush=True)
  elif a.coordinates and 'mmcifs' in row['relative_filename']:
   report=coordinate_archive(raw,row,run)
   with StateDB(ROOT/'run-state.sqlite') as state:
    key=state.ensure(row)
    if state.job(key)['stage']=='HASHED':state.transition(key,'PARSED')
    state.transition(key,'HOLD_QC' if report['files_held'] else 'QC_PASS',detail={'scope':'streamed coordinate schema; not full stereochemistry/homology or assay review'},evidence=[str(run/'reports/rna3db_coordinate_summary.json')])
   print(json.dumps(report),flush=True)
 if len(bundles)==2:
  diff=compare_versions(bundles['2025-10-01-incremental-release'],bundles['2026-01-05-full-release'])
  immutable_json(run/'reports/rna3db_actual_version_diff.json',diff)
  print(json.dumps({'version_diff_computed':True,'new_parse_chain_ids':diff['parse.json']['new_ids'],'added_parse_chain_ids':len(diff['parse.json']['added_chain_ids']),'removed_parse_chain_ids':len(diff['parse.json']['removed_chain_ids'])}),flush=True)
 else:print(json.dumps({'version_diff_computed':False,'available_versions':list(bundles),'state':'WAITING_FOR_HASHED_JSON_BUNDLE'}),flush=True)


if __name__=='__main__':main()
