#!/usr/bin/env python3
"""Reconcile registered task claims with actual local, hash-bound QC evidence.

Derived catalog only: never renumbers tasks, rewrites admission, removes repeated
observations, downloads data or exports individual sequence/measurement values.
"""
import argparse
from collections import Counter,defaultdict
import csv
import hashlib
import json
from pathlib import Path

if __package__:
 from .asset_identity import artifact_uid
else:
 from asset_identity import artifact_uid

ROOT=Path(__file__).resolve().parents[1]
TYPE_MAP={
 'RNA 2D':('secondary_structure','rna_secondary_structure'),
 'RNA 3D':('tertiary_geometry','rna_tertiary_structure'),
 '逐核苷酸回归':('token_regression','chemical_reactivity'),
 '二/多/多标签分类':('sequence_classification','rna_annotation_or_classification'),
 '标量回归':('scalar_regression','rna_scalar_phenotype'),
 '突变效应与排序':('variant_fitness','rna_variant_effect'),
 'RNA–蛋白结合':('protein_binding','rna_protein_binding'),
 '排除/仅方法学':('methodology_or_unresolved','methodology_or_controls'),
 'RNA 逆折叠与生成设计':('conditional_generation','rna_inverse_folding_and_design'),
 'RNA–小分子结合':('ligand_binding','rna_ligand_binding'),
 'RNA–RNA 相互作用':('paired_rna','rna_rna_interaction'),
 'Nanopore 原始信号':('raw_signal','rna_signal_decoding')}
CAPABILITIES={
 'MRNA_MRL_SAMPLE':'translation_mrl','MRNA_MRL_SUGIMOTO':'translation_mrl',
 'MRNA_MRL_HL_LBKWK':'joint_mrl_half_life_REQUIRES_ENDPOINT_SELECTION',
 'MRNA_RNAHL_SALUKI_HUMAN':'rna_half_life','MRNA_RNAHL_SALUKI_MOUSE':'rna_half_life',
 'MRNA_GO_MF':'encoded_protein_go_annotation','MRNA_PROTEIN_LOCALIZATION':'protein_localization_proxy',
 'MRNA_RNA_LOC_FAZAL':'rna_localization','MRNA_VEP_TRAITGYM_MRNA':'variant_annotation_proxy',
 'MRNA_UTR_VARIANTS_BOHN':'utr_variant_annotation_proxy','MRNA_MIRNA_TARGET':'mirna_target_annotation',
 'MIR_BENCH':'paired_mirna_binding','RNAGYM_DMS':'rna_variant_effect',
 'RNAGYM_RMDB':'chemical_reactivity','RNA3DB':'rna_tertiary_structure'}


def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def table(path,delimiter=','):
 with Path(path).open(encoding='utf-8-sig') as handle:return list(csv.DictReader(handle,delimiter=delimiter))
def save(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+'\n')


def _sequence_evidence(report,ref):
 stats=report.get('target_stats',{})
 targets=[]
 for name,info in stats.items():
  targets.append({'column':name,'finite_values':info.get('finite_values',0),
    'missing':info.get('missing',0),'invalid_or_nonfinite':info.get('invalid_or_nonfinite',0)})
 hist=report.get('sequence_length_histogram',{})
 lengths=[int(k) for k,v in hist.items() if v]
 return {'kind':'FULL_FILE_TARGET_VALUES_VERIFIED','evidence_ref':ref,'evidence_sha256':None,
    'source_sha256':report['source_sha256'],'n_file_rows':report['actual_n'],
    'target_columns':targets,'target_vector_length_counts':report.get('target_vector_length_counts',{}),'readout':report.get('readout'),'label_origin':report.get('assay_kind','SOURCE_SEMANTICS_PENDING'),
    'units_verified':report.get('units_verified',False),'official_split_present':not report.get('missing_official_split',True),
    'raw_alphabet':sorted(report.get('sequence_alphabet_counts',{})),
    'minimum_sequence_length':min(lengths) if lengths else None,
    'maximum_sequence_length':max(lengths) if lengths else None,
    'rows_over_rnafm_1022nt':sum(v for k,v in hist.items() if int(k)>1022),
    'unique_raw_sequences':report.get('n_unique_raw_sequences'),
    'sequence_transform':'NONE','observations_removed':0,'scientific_admission':False}


def build(root):
 root=Path(root)
 evidence=defaultdict(list)
 qcroot=root/'runs/20261022_212625/reports'
 inputs={}
 def add(aid,item,ref):
  path=root/ref;item={**item,'evidence_ref':ref,'evidence_sha256':digest(path)}
  evidence[aid].append(item);inputs[ref]=digest(path)
 for path in sorted((qcroot/'sequence_qc').glob('*.json')):
  report=read_json(path);ref=str(path.relative_to(root))
  if report.get('target_stats') and report.get('source_sha256'):
   add(report['asset_id'],_sequence_evidence(report,ref),ref)
 for path in sorted((qcroot/'paired_full_qc').glob('*-qc.json')):
  report=read_json(path)
  if report.get('label_distribution') and report.get('source_sha256'):
   add(report['asset_id'],{'kind':'FULL_FILE_BINARY_TARGET_VALUES_VERIFIED',
     'source_sha256':report['source_sha256'],'n_file_rows':report['actual_n'],
     'target_columns':[{'column':'label','count':sum(report['label_distribution'].values())}],
     'readout':'paired miRNA/target binding label; negative construction/assay review still required',
     'label_origin':'EXPERIMENTAL_DERIVED_LABEL_SEMANTICS_PENDING',
     'official_split_present':bool(report.get('original_split')),'original_split':report.get('original_split'),
     'unique_ordered_pairs':report.get('n_unique_ordered_pairs'),'scientific_admission':False},str(path.relative_to(root)))
 # Full probing scans are reused, not re-scanning hundreds of millions of values.
 probe=qcroot/'probing_qc_summary.json'
 if probe.exists():
  for report in read_json(probe).get('results',[]):
   if 'EXCLUDED' in report.get('state',''):continue
   aid=report.get('asset_id')
   if aid in ('HF_077f265b2add15269941','HF_e567b1f79ef75075abec'):
    ref=str(probe.relative_to(root))
    add(aid,{'kind':'PROBING_SEQUENCE_TARGET_SCAN_REUSED','source_sha256':report.get('source_sha256'),
      'n_file_rows':report.get('actual_n'),'target_columns':[{'column':'reactivity_or_position_labels','semantics':'See source QC; not scalar fitness'}],
      'label_origin':'CHEMICAL_PROBING_SOURCE_REVIEW_PENDING','scientific_admission':False},ref)
 # This is an independently selected primitive y array, not a second assay.
 path=root/'runs/20261023_131628/reports/t0021_selective_npz_review_v2.json'
 if path.exists():
  r=read_json(path);member=next((x for x in r['members'] if x['member']=='y.npy'),{})
  add(r['asset_id'],{'kind':'BOUNDED_SOURCE_NUMERIC_TARGET_VERIFIED','source_sha256':r['source_sha256'],
     'n_file_rows':member.get('shape',[None])[0], 'target_columns':[{'column':'y.npy','finite_values':member.get('finite_elements')}],
     'label_origin':'SOURCE_MRL_VALUES_IDENTICAL_TO_PARQUET_NOT_AN_INDEPENDENT_ASSAY',
     'pickle_deserialized':False,'feature_matrix_loaded':False,'scientific_admission':False},str(path.relative_to(root)))
 # Reuse archive member QC with explicit target columns/structural schemas.
 # Numeric features/MSAs/checksums/result tables are not automatically labels.
 for path in sorted((qcroot/'archive_qc').glob('*.json')):
  report=read_json(path);aid=report.get('asset_id')
  if not aid or not report.get('source_sha256'):continue
  members=[]
  for member in report.get('scanned_members',[]):
   columns=member.get('numeric_columns_separate',{})
   target_names=[name for name in columns if name in ('DMS_score','reactivity','label','target')]
   if target_names and any(columns[name].get('finite_values',0)>0 for name in target_names):
    members.append({'member':member.get('member'),'format':member.get('format'),
      'file_rows':member.get('actual_rows'),'target_columns':target_names,
      'member_sha256':member.get('member_sha256')})
  if members:
   add(aid,{'kind':'ARCHIVE_MEMBER_TARGET_COLUMNS_VERIFIED','source_sha256':report['source_sha256'],
       'target_members':members,'n_target_members':len(members),
       'label_origin':'SOURCE_TARGET_VALUES_NOT_YET_CANONICAL_ASSAY_REVIEWED',
       'held_members':len(report.get('held_members',[])),'scientific_admission':False},str(path.relative_to(root)))
 path=qcroot/'rna3db_atom_identity_qc.json'
 if path.exists():
  report=read_json(path)
  add('RNA3DB_20260105_rna3db_mmcifs',{'kind':'STRUCTURAL_COORDINATE_TARGETS_PARSED',
      'source_sha256':report['source_sha256'],'coordinate_files':report['coordinate_files_scanned'],
      'atom_rows_not_sample_n':report['atom_rows_scanned'],'label_origin':'PDB_COORDINATE_REFERENCE',
      'pair_labels_extracted':False,'biological_assembly_verified':report['biological_assembly_verified'],
      'scientific_admission':False},str(path.relative_to(root)))
 counts=root/'data/audit/rnagym_file_counts.tsv'
 if counts.exists():
  rows=table(counts,'\t');inputs[str(counts.relative_to(root))]=digest(counts)
  if rows:
   evidence['P0_RNAGYM_PROCESSED'].append({'kind':'RNA_SCOPE_PROCESSED_DMS_MEMBERS_VERIFIED',
      'source_sha256':rows[0]['archive_sha256'],'n_rna_scope_members':len(rows),
      'n_file_rows_not_independent_observations':sum(int(r['actual_n']) for r in rows),
      'target_columns':[{'column':'DMS_score'}],
      'label_origin':'RNA_DMS_SOURCE_ASSAY_IDENTITY_AND_UNITS_PENDING',
      'evidence_ref':str(counts.relative_to(root)),'evidence_sha256':digest(counts),
      'scientific_admission':False,'task_member_mapping_verified':False})
 assets=[];private={}
 for path in sorted((root/'raw_cache').rglob('provenance.json')):
  p=read_json(path);aid=p.get('asset_id');name=p.get('raw_filename')
  if not aid:continue
  physical=path.parent/name if name and Path(name).name==name else None
  if physical is None:
   candidates=[f for f in path.parent.iterdir() if f.is_file() and f.name not in ('provenance.json',) and f.suffix not in ('.json','.lock','.partial')]
   physical=candidates[0] if len(candidates)==1 else None
  observed=p.get('sha256',p.get('observed_sha256'))
  uid=artifact_uid(aid,observed)
  size_ok=bool(physical and physical.is_file() and physical.stat().st_size==p.get('bytes'))
  ev=[x for x in evidence.get(aid,[]) if x.get('source_sha256') in (None,observed)]
  state='LABEL_VALUES_VERIFIED_IN_HASH_BOUND_QC' if ev else 'LABELS_NOT_ESTABLISHED_BY_SELECTED_EVIDENCE'
  if aid.startswith('RNA3DB_') and 'mmcif' in str(name):state='STRUCTURAL_COORDINATE_TARGETS_PRESENT_PAIR_LABEL_EXTRACTION_SEPARATE'
  if aid in ('HF_287b2797cface258321d','HF_51b53dab485ecb3d7409'):state='EXCLUDED_MODEL_RESULT_TABLE_NOT_GROUND_TRUTH'
  item={'artifact_uid':uid,'asset_id':aid,'provenance_record_count':1,'package_group_id':p.get('package_group_id'),'filename':name,
    'source_sha256':observed,'file_bytes':p.get('bytes'),'physical_file_present':bool(physical and physical.is_file()),
    'physical_file_size_matches_provenance':size_ok,'source_url':p.get('official_source_url',p.get('requested_url')),
    'label_state':state,'label_evidence':ev,'rights_decision':p.get('rights',{}).get('decision','UNRESOLVED'),
    'scientific_admission':False,'count_scope':'PHYSICAL_FILE_VERSION_NOT_INDEPENDENT_ASSAY'}
  locator={'path':str(physical.relative_to(root)) if physical else None,
    'provenance':str(path.relative_to(root)),'source_sha256':observed,'bytes':p.get('bytes')}
  if uid in private:
   previous=next(a for a in assets if a['artifact_uid']==uid)
   if previous['package_group_id']!=item['package_group_id']:
    raise ValueError('SAME_ARTIFACT_CONFLICTING_PACKAGE_REQUIRES_SOURCE_REVIEW')
   previous['provenance_record_count']+=1
   private[uid]['provenance_aliases'].append(locator['provenance'])
   private[uid]['path_aliases'].append(locator['path'])
   if not previous['physical_file_present'] and item['physical_file_present']:
    previous['physical_file_present']=True
    previous['physical_file_size_matches_provenance']=size_ok
    private[uid].update(locator)
  else:
   assets.append(item)
   private[uid]={**locator,'provenance_aliases':[locator['provenance']],
                 'path_aliases':[locator['path']]}
  inputs[str(path.relative_to(root))]=digest(path)
 registry=root/'data/registries/task_baselines_and_admission_198.csv';rows=table(registry)
 current={r['task_id']:r for r in table(root/'data/audit/task_master.tsv','\t')}
 by_package=defaultdict(list)
 for asset in assets:by_package[asset['package_group_id']].append(asset)
 schemas=read_json(root/'configs/full_qc_schemas.json').get('sequence_parquet',{})
 # Some old schema versions use a differently named top-level section.
 if not schemas:
  config=read_json(root/'configs/full_qc_schemas.json')
  schemas=next((v for v in config.values() if isinstance(v,dict) and 'MRNA_MRL_SUGIMOTO' in v),{})
 tasks=[]
 for row in rows:
  tid=row['task_id'];package=row['下载包ID'];linked=by_package[package]
  kind,capability=TYPE_MAP.get(row['标准任务类别'],('UNRESOLVED','UNRESOLVED'))
  capability=CAPABILITIES.get(package,capability)
  if tid=='T0009':capability='translation_mrl'
  present=[a for a in linked if a['physical_file_present']]
  label_files=[a for a in present if a['label_evidence']]
  task={'task_id':tid,'benchmark':row['Benchmark'],'dataset_name':row['原始数据集候选'],
    'registered_task_type':row['标准任务类别'],'task_type':kind,'capability':capability,
    'capability_assignment_scope':'REGISTERED_DESCRIPTION_NOT_SCIENTIFIC_IDENTITY_APPROVAL',
    'input_track':row['公平输入轨道'],'registered_label_description':row['标签/计数(原登记)'],
    'registered_label_verified_flag':row['已有标签是否实测核验'],'registered_downloaded_flag':row['源数据已下载'],
    'package_group_id':package,'source_family_id':row['来源族ID'],'asset_ids':list(dict.fromkeys(a['asset_id'] for a in linked)),
    'artifact_uids':[a['artifact_uid'] for a in linked],
    'local_package_files':len(present),'label_files_in_package':len(label_files),
    'label_values_present_in_source_package':bool(label_files),
    'exact_assay_mapping_verified':current[tid]['state'].startswith('ADMITTED'),'task_level_sample_n':None,
    'scientific_state':current[tid]['state'],'is_excluded_non_assay':current[tid]['state'].startswith('EXCLUDED'),
    'schema':schemas.get(package), 'reported_n':row['N(原登记)'],'reported_n_scope':'REPORTED_NOT_ASSAY_VERIFIED',
    'has_dataset_is_not_admission':True,'admitted':current[tid]['state'].startswith('ADMITTED')}
  tasks.append(task)
 inputs[str(registry.relative_to(root))]=digest(registry)
 inputs['data/audit/task_master.tsv']=digest(root/'data/audit/task_master.tsv')
 result={'schema_version':'rna_gym.dataset_catalog.v2',
   'artifact_identity':'asset_id+source_sha256-v1',
   'producer_sha256':digest(Path(__file__)),'snapshot_scope':'RECONCILED_LOCAL_PROVENANCE_AND_PRIOR_FULL_QC',
   'task_count':len(tasks),'task_type_counts':dict(Counter(t['registered_task_type'] for t in tasks)),
   'physical_file_versions':len(assets),'physical_files_present':sum(a['physical_file_present'] for a in assets),
   'package_groups_with_local_files':len({a['package_group_id'] for a in assets if a['physical_file_present']}),
   'assets_with_label_evidence':sum(bool(a['label_evidence']) for a in assets),
   'tasks_with_local_package_files':sum(t['local_package_files']>0 for t in tasks),
   'tasks_with_labelled_source_package':sum(t['label_values_present_in_source_package'] for t in tasks),
   'scientifically_admitted_tasks':sum(t['admitted'] for t in tasks),
   'stale_initial_download_no_flags':sum(t['registered_downloaded_flag']=='NO' and t['local_package_files']>0 for t in tasks),
   'unmapped_local_package_groups':sorted(set(by_package)-{r['下载包ID'] for r in rows}),
   'count_caveat':'File versions, overlapping source packages and task rows are NOT independent assays.',
   'tasks':tasks,'assets':assets,'evidence_input_sha256':inputs}
 return result,private


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--root',type=Path,default=ROOT)
 parser.add_argument('--out',type=Path,default=ROOT/'data/registries/dataset_catalog.json')
 parser.add_argument('--private-out',type=Path,required=True)
 args=parser.parse_args()
 if not args.private_out.resolve().is_relative_to(args.root.resolve()/'runs'):
  parser.error('Private raw paths must remain in ignored runs/')
 catalog,private=build(args.root)
 save(args.out,catalog);save(args.private_out,{'schema_version':'rna_gym.private_asset_paths.v2','artifacts':private})
 print(json.dumps({k:v for k,v in catalog.items() if k not in ('tasks','assets','evidence_input_sha256')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
