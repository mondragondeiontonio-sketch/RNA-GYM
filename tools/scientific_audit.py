#!/usr/bin/env python3
"""Compile scientific evidence without promoting file QC or generating approval.

Read-only raw inputs; immutable, content-bound outputs; authoritative state stays
in run-state.sqlite. Assay candidates are explicitly not independent assays.
"""
import argparse,collections,csv,hashlib,io,json,sqlite3
from pathlib import Path
from rnagym import ROOT,StateDB,immutable_json,now
VERSION='RNA-GYM:scientific-evidence:v1'
REPORTS=['QC_REPORT.md','qc_summary.json','qc_issue_log.tsv','qc_asset_status.tsv','task_qc_coverage_198.tsv','package_qc_status_47.tsv']
REGISTRIES=['search_level_task_crosswalk_198.csv','task_baselines_and_admission_198.csv','download_packages_47.csv','source_family_crosswalk_123.csv','RNAGym_NABench_DMS_ID_91.csv','miRBench_splits_3.csv','package_audit_47.csv','priority_issue_log_20.csv']
MANIFESTS=['p0_assets.csv','licensed_small_batch.csv','full_download_assets.csv','additional_source_assets.csv','assembled_assets.csv']
ASSAY_FIELDS=['canonical_assay_id','original_assay_id','source_assay_id','source_project','source_doi','experiment_accession','organism','cell_line','experimental_conditions','biological_readout','label_definition','label_unit','original_sample_count','upstream_release_version','raw_asset_sha256','upstream_checksum','data_license','redistribution_permission','split_source','dedup_group_id','qc_status','evidence_url','verification_status','identity_resolution','evidence_paths','candidate_kind','parent_study_accession']

def digest(data):return hashlib.sha256(data).hexdigest()
def stable(parts):return digest(json.dumps(parts,ensure_ascii=False,separators=(',',':')).encode())
def rel(path):return str(Path(path).resolve().relative_to(ROOT))
def read_complete(path,manifest):
 b=path.read_bytes();s=b.decode('utf-8-sig',errors='strict')
 m=dict(path=rel(path),sha256=digest(b),bytes=len(b),line_count=len(s.splitlines()),read_scope='FULL_BYTES_STRICT_UTF8')
 if path.suffix in ('.csv','.tsv'):
  reader=csv.DictReader(io.StringIO(s),delimiter='\t' if path.suffix=='.tsv' else ',');out=list(reader)
  if any(None in r for r in out):raise ValueError('ragged table '+str(path))
  m.update(parsed_rows=len(out),columns=reader.fieldnames)
 elif path.suffix=='.json':out=json.loads(s)
 else:out=s
 manifest.append(m);return out

def table(path,rows,fields):
 out=io.StringIO(newline='');w=csv.DictWriter(out,fieldnames=fields,delimiter='\t',lineterminator='\n');w.writeheader()
 for r in rows:w.writerow({k:json.dumps(v,ensure_ascii=False,sort_keys=True) if isinstance(v,(dict,list)) else '' if v is None else v for k,v in r.items()})
 b=out.getvalue().encode();path.parent.mkdir(parents=True,exist_ok=True)
 if path.exists():
  if path.read_bytes()!=b:raise FileExistsError('immutable output differs '+str(path))
 else:
  with path.open('xb') as f:f.write(b)
 return digest(b)

def assess(e):
 required=['source_verified','rights_verified','label_verified','sample_identity_verified','split_verified','qc_verified','dedup_verified','leakage_verified','raw_hash_verified']
 gaps=[k for k in required if e.get(k) is not True]
 if not gaps:return 'ADMISSION_CANDIDATE',[]
 for flag,stage in [('assay_verified','ASSAY_VERIFIED'),('source_verified','SOURCE_VERIFIED'),('file_qc_verified','FILE_QC_PASS')]:
  if e.get(flag) is True:return stage,gaps
 return 'NOT_REVIEWED',gaps

def candidate(project,alias,**kw):
 r=dict.fromkeys(ASSAY_FIELDS,'')
 r.update(canonical_assay_id='TMP_'+stable([project,alias])[:20],source_assay_id=alias,source_project=project,
  dedup_group_id='UNRESOLVED_'+stable([project,alias])[:16],verification_status='PROVISIONAL',qc_status='HOLD',
  identity_resolution='UNRESOLVED_EXPERIMENT_NOT_AN_ADMITTED_ASSAY',candidate_kind='EXPERIMENT_CANDIDATE')
 r.update(kw);return r

def inventory(prior):
 m=[];d={}
 for n in REPORTS:d[n]=read_complete(prior/'reports'/n,m)
 for n in REGISTRIES:d[n]=read_complete(ROOT/'data/registries'/n,m)
 for n in ['docs/ORIGINAL_PHASE1_AUDIT.md','data/audit/assay_master.tsv','data/audit/alias_map.tsv','data/audit/rights_audit.tsv','data/audit/rights_decisions.json','configs/full_qc_schemas.json']:
  d[n]=read_complete(ROOT/n,m)
 for n in MANIFESTS:d[n]=read_complete(ROOT/'data/audit'/n,m)
 for n in ['final_raw_byte_verification.json','sequence_qc_summary.json','paired_full_qc_summary.json','paired_all_split_overlap.json','probing_qc_summary.json','probing_exact_split_overlap.json','cluster_mapping_review.json','cross_benchmark_representation_duplicates.json','rna3db_actual_version_diff.json','rna3db_atom_identity_qc.json','format_recovery_qc.json']:
  d[n]=read_complete(prior/'reports'/n,m)
 t=d['search_level_task_crosswalk_198.csv'];b=d['task_baselines_and_admission_198.csv']
 if len(t)!=198 or len(b)!=198 or len(d['download_packages_47.csv'])!=47:raise ValueError('frozen count drift')
 if {r['row_id'] for r in t}!={r['task_id'] for r in b}:raise ValueError('task ID mismatch')
 for q in d['sequence_qc_summary.json']['results']:
  path=ROOT/q['report'];report=read_complete(path,m)
  expected=next(a['sha256'] for a in d['qc_asset_status.tsv'] if a['asset_id']==q['asset_id'])
  if report.get('source_sha256')!=expected:raise ValueError('unbound mRNA schema evidence')
 return d,m

def build_candidates(d,extra,prior):
 assets=d['qc_asset_status.tsv'];sources={r['asset_id']:r for n in MANIFESTS for r in d[n]}
 assays=[];aliases=[];mapping=collections.defaultdict(list)
 for line,r in enumerate(d['RNAGym_NABench_DMS_ID_91.csv'],2):
  for project,flag in [('RNAGym','in_RNAGym_reference_sheet'),('NABench','in_NABench_public_data_files')]:
   if r[flag]!='YES':continue
   a=candidate(project,r['assay_dms_id'],biological_readout=r['assay_category'],candidate_kind='DMS_ALIAS_CANDIDATE',
    evidence_url=r['rnagym_metadata_url'] if project=='RNAGym' else r['nabench_metadata_url'],
    evidence_paths=f'data/registries/RNAGym_NABench_DMS_ID_91.csv:{line}')
   a['dedup_group_id']='DMS_ALIAS_'+stable([r['assay_dms_id']])[:16];assays.append(a)
   aliases.append(dict(dataset_alias=r['assay_dms_id'],source_project=project,canonical_assay_id=a['canonical_assay_id'],identity_status=r['metadata_raw_construct_sequence_equality'],merge_decision='NO_MERGE_PENDING_ORIGINAL_ASSAY',verification_status='PROVISIONAL',evidence_paths=a['evidence_paths']))
   if project=='RNAGym':mapping['P0_RNAGYM_PROCESSED'].append(a)
 pairresults=d['paired_full_qc_summary.json']['results'];pairmap={r['asset_id']:r for r in pairresults}
 for alias in sorted({r['dataset_alias'] for r in pairresults}):
  a=candidate('miRBench',alias,biological_readout='miRNA-target binding site classification',label_definition='raw binary curated positives/negatives; original generation protocol review pending',label_unit='binary_class_not_binding_affinity',
   upstream_release_version='Zenodo 20540907; HF v1 separate',data_license='CC-BY-4.0 collection claim',redistribution_permission='NOT_HUMAN_REVIEWED',
   split_source='AUTHOR_PROVIDED_SPLIT_FILES',evidence_url='https://zenodo.org/records/20540907',evidence_paths=rel(prior/'reports/paired_full_qc_summary.json'))
  if 'Manakov' in alias and extra.get('mir_geo',{}).get('verification_status')=='VERIFIED':
   a['parent_study_accession']='GSE198250'
   a['evidence_paths']+=';'+rel(extra['mir_geo_path'])
  assays.append(a)
  for r in pairresults:
   if r['dataset_alias']==alias:mapping[r['asset_id']].append(a)
 for asset in assets:
  aid=asset['asset_id'];p=asset['package_group_id'];s=sources.get(aid,{})
  if not p.startswith('MRNA_'):continue
  schema=d['configs/full_qc_schemas.json']['packages'].get(p,{})
  q=next((r for r in d['sequence_qc_summary.json']['results'] if r['asset_id']==aid),{})
  a=candidate('mRNABench:'+p,s.get('upstream_relative_path') or asset['file_name'],biological_readout=schema.get('readout','NOT_VERIFIED'),
   label_definition=json.dumps(schema.get('targets') or {'target_prefix':schema.get('target_prefix')},ensure_ascii=False),label_unit='NOT_VERIFIED',
   upstream_release_version=s.get('upstream_commit',''),data_license=s.get('collection_license_claim','NOT_VERIFIED'),redistribution_permission='NOT_HUMAN_REVIEWED',split_source='NO_SPLIT_COLUMN; AUTHOR_CODE_REVIEW_REQUIRED',
   qc_status=q.get('state','HOLD'),evidence_url=s.get('official_source_url',''),evidence_paths=q.get('report',''),candidate_kind=schema.get('assay_kind','READOUT_CONTAINER_NOT_CONFIRMED_ASSAY'))
  # Never copy a file row count into original experimental N.
  mrna=extra.get('mrna',{});records=mrna.get('records',[]) if isinstance(mrna,dict) else []
  source=next((r for r in records if r.get('asset_id')==aid),None)
  if source:
   license=source.get('data_license',{})
   if isinstance(license,dict):a['data_license']=license.get('hf_data_license_declaration','UNKNOWN')+'; '+license.get('data_license_evidence_status','UNKNOWN')
   a['redistribution_permission']=source.get('redistribution_permission','NOT_HUMAN_REVIEWED')
   split=source.get('split_source',{})
   if isinstance(split,dict):a['split_source']=split.get('author_protocol','UNKNOWN')+'; '+split.get('protocol_status','UNVERIFIED')
   a['evidence_paths']+=';data/audit/phase2_mrna_source_evidence.json#'+aid
   for k,v in source.get('verified_fields',{}).items():
    if k in ASSAY_FIELDS and v:a[k]=v
  assays.append(a);mapping[aid].append(a)
 encode_by_task=collections.defaultdict(list)
 for e in extra.get('encode',{}).get('source_experiments',[]):
  a=candidate('ENCODE',e['source_assay_id'],original_assay_id=e['source_assay_id'],experiment_accession=e['source_assay_id'],organism=e.get('species_claim',''),cell_line=e.get('cell_line',''),
   biological_readout='eCLIP binding peaks; negative generation/sequence windows pending',label_definition='NOT_PREPARED',data_license='ENCODE released-data use policy',redistribution_permission='PUBLIC_USE_POLICY_VERIFIED; no raw redistributed',
   evidence_url=e['source_url'],evidence_paths=rel(extra['encode_path']),qc_status='SOURCE_VERIFIED',verification_status='VERIFIED',identity_resolution='SOURCE_EXPERIMENT_VERIFIED_TASK_PREPARATION_PENDING')
  assays.append(a);encode_by_task[e['task_id']].append(a)
 for a in assays:
  a['raw_asset_sha256']=';'.join(sorted({x['sha256'] for x in assets if a in mapping[x['asset_id']]}))
 crosswalk=[];splits=[]
 for asset in assets:
  aid=asset['asset_id'];bound=mapping[aid]
  for a in bound or [None]:
   crosswalk.append(dict(asset_id=aid,raw_asset_sha256=asset['sha256'],canonical_assay_id=a['canonical_assay_id'] if a else '',relationship='FILE_TO_ALIAS_CANDIDATE' if a else 'METADATA_OR_UNRESOLVED_CONTAINER_NOT_ASSAY',relationship_verified=False,verification_status='PROVISIONAL',evidence_paths=a['evidence_paths'] if a else rel(prior/'reports/qc_asset_status.tsv')))
  if aid in pairmap or asset['package_group_id'].startswith('MRNA_'):
   r=pairmap.get(aid,{});q=next((q for q in d['sequence_qc_summary.json']['results'] if q['asset_id']==aid),{})
   splits.append(dict(split_id=r.get('dataset_alias',aid)+':'+r.get('original_split','UNRESOLVED'),asset_id=aid,canonical_assay_id=bound[0]['canonical_assay_id'],split_origin='OFFICIAL_RELEASE_FILE' if r else 'AUTHOR_CODE_PROTOCOL_UNREPRODUCED_ASSIGNMENTS',
    split_source_url=sources.get(aid,{}).get('official_source_url',''),raw_asset_sha256=asset['sha256'],sample_count=r.get('actual_n',q.get('actual_n','')),exact_input_cross_split_count=0 if r else '',group_leakage_status='NOT_PASSED_GENE_TRANSCRIPT_FAMILY_REVIEW',
    transform_policy='FIT_TRAIN_ONLY; no fitting performed',split_manifest_sha256='',verification_status='PROVISIONAL' if r else 'BLOCKED',evidence_paths=rel(prior/'reports/paired_full_qc_summary.json') if r else q.get('report','')))
 return assays,aliases,crosswalk,splits,mapping,encode_by_task

def leakage_rows(d,extra,prior):
 rows=[]
 def add(cat,left,right,n='',conflicts='',sha='',status='VERIFIED',evidence='',decision='KEEP_RAW_NO_OBSERVATION_MERGE'):
  rows.append(dict(category=cat,left_id=left,right_id=right,shared_input_count=n,conflicting_label_count=conflicts,file_sha256=sha,decision=decision,verification_status=status,evidence_paths=evidence))
 for r in d['cross_benchmark_representation_duplicates.json']['comparisons']:
  add('SAME_MEMBER_BYTES_MULTIPLE_BENCHMARKS','RNAGym:'+r['source_alias'],'Wang:'+r['source_alias'],sha=r['rnagym_member_sha256'],evidence=rel(prior/'reports/cross_benchmark_representation_duplicates.json'),decision='FORBID_DOUBLE_CONTENT_WEIGHT; NOT_ASSAY_IDENTITY_PROOF')
 pairmap={r['asset_id']:r for r in d['paired_full_qc_summary.json']['results']}
 for r in d['paired_all_split_overlap.json']['comparisons']:
  left,right=r['left_asset'],r['right_asset'];same=pairmap[left]['dataset_alias']==pairmap[right]['dataset_alias']
  cats=['AMBIGUOUS_ASSAY_IDENTITY']
  cats+=['MIRROR_REPRESENTATION_REUSE' if same else 'SAME_PAIR_DIFFERENT_DATASET_ASSAY_UNVERIFIED']
  if pairmap[left]['original_split']!=pairmap[right]['original_split']:cats+=['CROSS_SPLIT_SAME_PAIR']
  if r['label_disagreement_pairs']:cats+=['CONFLICTING_LABELS']
  for cat in cats:add(cat,left,right,r['shared_exact_ordered_pairs'],r['label_disagreement_pairs'],status='PROVISIONAL' if cat=='AMBIGUOUS_ASSAY_IDENTITY' else 'VERIFIED',evidence=rel(prior/'reports/paired_all_split_overlap.json'))
 for r in extra.get('probing',{}).get('comparisons',[]):
  add('RMDB_CROSS_SPLIT_EXACT_INPUT',r['left_asset']+':'+str(r['left_row']),r['right_asset']+':'+str(r['right_row']),1,int(not r['reactivity_equal_with_nan']),evidence=rel(extra['probing_path']),decision=r['decision'])
 return rows

def compile_run(prior,run,task_filter=None,dry_run=False):
 d,manifest=inventory(prior);reports=run/'reports'
 tasks=d['search_level_task_crosswalk_198.csv'];assets=d['qc_asset_status.tsv'];base={r['task_id']:r for r in d['task_baselines_and_admission_198.csv']}
 coverage={r['task_id']:r for r in d['task_qc_coverage_198.tsv']};proof={r['asset_id']:r for r in d['final_raw_byte_verification.json']['artifacts']}
 for a in assets:
  if proof.get(a['asset_id'],{}).get('sha256')!=a['sha256'] or proof[a['asset_id']].get('actual_raw_bytes_verified') is not True:raise ValueError('raw proof mismatch')
 if task_filter and task_filter not in base:raise ValueError('unknown task ID')
 extra={}
 optional={'mrna':ROOT/'data/audit/phase2_mrna_source_evidence.json','encode':reports/'encode_source_assays.json','probing':reports/'probing_observation_review.json','pairs':reports/'pair_identity/summary.json','structure':reports/'structure_review/summary.json','mir_geo':run/'manifests/sources/GSE198250/snapshot.json'}
 for k,p in optional.items():
  if p.exists():extra[k]=read_complete(p,manifest);extra[k+'_path']=p
 fingerprint=stable([VERSION,task_filter,[(m['path'],m['sha256']) for m in manifest]])
 if dry_run:return dict(dry_run=True,verification_status='VERIFIED',registered_tasks=198,selected_tasks=1 if task_filter else 198,assets=len(assets),input_fingerprint=fingerprint,writes=False,training=False)
 completion=reports/'execution_audit.json'
 if completion.exists():
  r=json.loads(completion.read_text())
  if r['input_fingerprint']!=fingerprint:raise ValueError('input changes require new immutable run_id')
  for name,h in r['output_sha256'].items():
   if digest((reports/name).read_bytes())!=h:raise ValueError('compiled output changed '+name)
  return r
 reports.mkdir(parents=True,exist_ok=True);(run/'manifests').mkdir(exist_ok=True)
 immutable_json(run/'manifests/required_read_manifest.json',dict(verification_status='VERIFIED',full_required_reads=True,inputs=manifest))
 assays,aliases,crosswalk,splits,mapping,encode=build_candidates(d,extra,prior)
 statuses=[];holds=[];edges=[];observations=[];by_package=collections.defaultdict(list)
 for a in assets:by_package[a['package_group_id']].append(a)
 sequenceqc={r['asset_id']:r for r in d['sequence_qc_summary.json']['results']}
 for line,t in enumerate(tasks,2):
  tid=t['row_id'];p=t['package_group_id'];old=coverage[tid];excluded=old['status'].startswith('EXCLUDED')
  file_pass=p.startswith('MRNA_') and bool(by_package[p]) and all(sequenceqc.get(a['asset_id'],{}).get('state','').startswith('PASS_') for a in by_package[p])
  mrna_records=[r for r in extra.get('mrna',{}).get('records',[]) if r.get('package_group_id')==p]
  mrna_source=bool(mrna_records) and all(r.get('source_doi_status','').startswith('VERIFIED') for r in mrna_records)
  mir_study=tid=='T0062' and extra.get('mir_geo',{}).get('verification_status')=='VERIFIED'
  stage,gaps=assess(dict(source_verified=bool(encode[tid]) or mrna_source or mir_study,file_qc_verified=file_pass))
  rights_conflict=any(r.get('redistribution_permission')=='HOLD_LICENSE_DO_NOT_REDISTRIBUTE' for r in mrna_records)
  if rights_conflict:gaps+=['HOLD_LICENSE_CONFLICT_DO_NOT_REDISTRIBUTE']
  if excluded:stage='EXCLUDED';gaps=[]
  refs=[f'data/registries/search_level_task_crosswalk_198.csv:{line}',rel(prior/'reports/task_qc_coverage_198.tsv')+':'+str(list(coverage).index(tid)+2)]
  if encode[tid]:refs.append(rel(extra['encode_path']))
  if mrna_records:refs.append('data/audit/phase2_mrna_source_evidence.json#'+p)
  if mir_study:refs.append(rel(extra['mir_geo_path']))
  actions=[]
  if not excluded:
   if not by_package[p]:actions+=['ACQUIRE_SCOPED_PUBLIC_RAW_AFTER_SOURCE_RIGHTS_REVIEW']
   if rights_conflict:actions+=['OBTAIN_RIGHTSHOLDER_CLARIFICATION_NO_REDISTRIBUTION']
   actions+=['VERIFY_ORIGINAL_EXPERIMENT_AND_LABEL_UNITS','REVIEW_DATA_SPECIFIC_RIGHTS','VERIFY_OBSERVATION_IDENTITY_SPLIT_AND_LEAKAGE','HUMAN_APPROVAL_ONLY_AFTER_ALL_SCIENTIFIC_EVIDENCE_PASSES']
  r=dict(task_id=tid,package_group_id=p,source_family_id=t['source_family_id'],scientific_stage=stage,disposition='EXCLUDED' if excluded else 'HOLD_LICENSE_CONFLICT' if rights_conflict else 'HOLD',previous_disposition=old['status'],verification_status='VERIFIED' if excluded or encode[tid] else 'PROVISIONAL',blocking_reasons=';'.join(gaps) if not excluded else old['next_action'],evidence_paths=';'.join(refs),original_assay_evidence=bool(encode[tid]),source_paper_resource_evidence=mrna_source,parent_study_evidence=mir_study,local_package_artifacts_not_task_completion=len(by_package[p]),task_raw_file_qc_verified=file_pass,actual_task_sample_count='',registered_reported_n=t['reported_n'],reported_n_status='REPORTED_UNVERIFIED',next_action=';'.join(actions))
  statuses.append(r)
  holds.append(dict(task_id=tid,package_group_id=p,disposition=r['disposition'],reason=r['blocking_reasons'],requires_new_raw_download=not bool(by_package[p]) and not excluded,requires_human_final_review=not excluded,ready_for_human_final_review=False,action=r['next_action'],verification_status='VERIFIED' if excluded else 'BLOCKED',evidence_paths=r['evidence_paths']))
  bound=encode[tid]+[a for x in by_package[p] for a in mapping[x['asset_id']]]
  if excluded:bound=[]
  seen=set()
  for a in bound:
   if a['canonical_assay_id'] in seen:continue
   seen.add(a['canonical_assay_id'])
   edges.append(dict(source=a['source_project'],release=a['upstream_release_version'],asset_sha256=a['raw_asset_sha256'],original_assay=a['original_assay_id'],canonical_assay_candidate=a['canonical_assay_id'],observation_evidence='IDENTITY_UNRESOLVED',benchmark_task=tid,split=a['split_source'],relationship_status='PROVISIONAL_PACKAGE_MAPPING_NOT_FULL_ASSAY_IDENTITY',evidence_paths=a['evidence_paths']))
 for o in extra.get('probing',{}).get('observations',[]):
  observations.append(dict(observation_id='RMDB:'+o['seq_id'],asset_id=o['asset_id'],row_number=o['row_number'],canonical_assay_id='',condition_id='',input_hash=o['input_hash'],observation_hash=o['raw_row_sha256'],identity_algorithm='RNA-GYM:probing-raw-row:v1',identity_resolution='OBSERVATION_VERIFIED_EXPERIMENT_REPLICATE_UNRESOLVED',verification_status='PROVISIONAL',evidence_paths=rel(extra['probing_path'])))
 outputs={}
 def out(name,rows,fields):outputs[name]=table(reports/name,rows,fields)
 readouts=[]
 for source in extra.get('mrna',{}).get('records',[]):
  for claim in source.get('label_specific_task_claims',[]):
   readouts.append(dict(readout_id=claim['claim_id'],task_ids=';'.join(claim.get('registered_task_ids',[])),asset_id=source['asset_id'],raw_asset_sha256=source['raw_asset_sha256'],target_column=claim['target_column'],biological_readout=claim['biological_readout'],label_definition=claim['label_definition'],label_unit=claim.get('label_unit',''),transformation=claim.get('transformation',''),verification_status='PROVISIONAL',disposition='HOLD',evidence_paths='data/audit/phase2_mrna_source_evidence.json#'+claim['claim_id']))
 if readouts:out('readout_registry.tsv',readouts,list(readouts[0]))
 out('assay_master_registry.tsv',assays,ASSAY_FIELDS)
 out('asset_to_assay_crosswalk.tsv',crosswalk,list(crosswalk[0]))
 out('alias_map.tsv',aliases,list(aliases[0]))
 out('observation_identity_audit.tsv',observations,['observation_id','asset_id','row_number','canonical_assay_id','condition_id','input_hash','observation_hash','identity_algorithm','identity_resolution','verification_status','evidence_paths'])
 leaks=leakage_rows(d,extra,prior);out('cross_dataset_leakage_report.tsv',leaks,list(leaks[0]))
 out('split_provenance_registry.tsv',splits,list(splits[0]))
 out('task_scientific_registry.tsv',statuses,list(statuses[0]))
 out('lineage_edges.tsv',edges,list(edges[0]))
 out('hold_and_exclusion_log.tsv',holds,list(holds[0]))
 out('admitted_tasks_v1.tsv',[],['task_id','canonical_assay_id','tier','approval_record','raw_asset_sha256','split_manifest_sha256','verification_status','evidence_paths'])
 summary=dict(registered_tasks=198,download_packages=47,assets=len(assets),raw_bytes=sum(int(a['bytes']) for a in assets),asset_state_counts=dict(collections.Counter(a['job_stage'] for a in assets)),previous_task_state_counts=dict(collections.Counter(r['status'] for r in coverage.values())),scientific_stage_counts=dict(collections.Counter(r['scientific_stage'] for r in statuses)),tasks_with_original_assay_source_evidence=sum(r['original_assay_evidence'] for r in statuses),tasks_with_source_paper_resource_evidence=sum(r['source_paper_resource_evidence'] for r in statuses),tasks_with_parent_study_evidence=sum(r['parent_study_evidence'] for r in statuses),tasks_with_local_package_artifacts=sum(r['local_package_artifacts_not_task_completion']>0 for r in statuses),tasks_with_file_qc_pass_missing_scientific_evidence=sum(r['task_raw_file_qc_verified'] and r['disposition'].startswith('HOLD') for r in statuses),admission_candidates=0,admitted=0,hold_tasks=sum(r['disposition'].startswith('HOLD') for r in statuses),excluded_tasks=sum(r['disposition']=='EXCLUDED' for r in statuses),require_new_download=sum(r['requires_new_raw_download'] for r in holds),ready_for_human_final_review=0,source_evidence_holds_resolved_only=sum(r['scientific_stage']=='SOURCE_VERIFIED' for r in statuses),final_admission_holds_resolved=0,candidate_registry_rows_not_independent_assay_count=len(assays))
 report=make_report(summary,prior,run,extra).encode();p=reports/'scientific_admission_report.md'
 if p.exists() and p.read_bytes()!=report:raise FileExistsError('immutable report differs')
 if not p.exists():p.write_bytes(report)
 outputs[p.name]=digest(report)
 record_state(run,statuses,fingerprint)
 result=dict(verification_status='VERIFIED',scientific_admission_status='BLOCKED',algorithm_version=VERSION,run_id=run.name,input_fingerprint=fingerprint,summary=summary,output_sha256=outputs,required_read_manifest=rel(run/'manifests/required_read_manifest.json'),raw_qc_reused=True,new_raw_downloads=0,raw_labels_changed=False,rows_deleted=0,original_splits_changed=False,human_approvals_generated=0,training_started=False,gpu_jobs_started=False,model_scores=[],complete_scientific_admission=False,optional_evidence_present=[k for k in optional if k in extra])
 immutable_json(completion,result);return result

def make_report(s,prior,run,extra):
 return '\n'.join(['# RNA-Gym Phase 2 科学准入审计','',
 '**VERIFIED：技术证据和注册覆盖；PROVISIONAL：候选实验映射；BLOCKED：最终科学准入。**','',
 '完整读取与内容哈希见 `../manifests/required_read_manifest.json`。',
 '所有任务保留原 ID 和原注册行号；198 行、47 包、文件行数和候选别名不是独立实验计数。','',
 '## 状态统计','', '```json',json.dumps(s,ensure_ascii=False,indent=2),'```','',
 '## 科学身份与去重','',
 '- DMS 来源别名分开保留；26 同名与 7 构件冲突未获原实验确认，未强行合并。',
 '- RNAGym/Wang 70 个 member 字节相同：禁止重复来源计权，不推断实验身份通过。',
 '- miRBench 原始 ordered-pair 保留 T/U，跨 assay 不合并标签；新增复合身份见 pair_identity。',
 '- RMDB 共享输入按既有索引仅读取所需 row group，核对 9 个观测与条件/向量；不删除观测。',
 '- `cluster_40.parquet` 属 RNAGYM_RMDB，不是 RNA3DB 的结构或 Rfam 聚类；原列名问题保留。',
 '- RNA3DB serial 重用不是生物重复；assembly、全量 stereochemistry、跨库同源未通过。',
 '- 5 个 pickle 不执行；competition solution、预测、3D 结果表保持隔离。','',
 '## 本轮解除的具体证据缺口','',
 '11/11 mRNA 文件关联到原论文/资源（8 个 DOI），定位作者 default/homology split 协议，',
 '但固定行级 split manifest 仍为 0；不再将无 split 列误读为不存在作者协议。',
 'Saluki 标签是无量纲 half-life PC1，非小时。Leppek MRL 与 half-life 分开登记。',
 'miRNA-target 的 HF CC-BY 与作者代码禁止再分发声明冲突：HOLD_LICENSE_CONFLICT。',
 'RNA3DB 2026 实际 train/test chains=13451/1990；共享 401 PDB entries，未改 split。',
 'miRBench 新身份审计覆盖 7 文件：261 个跨 dataset 共享 pair 候选、59 个跨 split pair、',
 '15 个不一致标签；这些分类不可相加，原 assay/condition 未核实。','',
 '## 准入候选与阻断','',
 'ADMISSION_CANDIDATE=0、ADMITTED=0。不能为了凑 5–10 个而跳过证据。',
 '优先后续审查 T0020、T0021、T0022、T0062、XMRNA_rnahl_saluki_mouse；',
 '这些只是实验计划候选，不是已准入任务或模型可用标签。',
 '人工审批不能代替未完成的实验身份、来源权利、label 语义和 split 科学审核。',
 '真正需要新增 raw 的任务、可仅用元数据继续的任务见 `hold_and_exclusion_log.tsv`。','',
 '## Split 与 readout','',
 'MRL、TE、RSS、half-life、splicing、eCLIP 保持独立；mRNA 文件行数不填写 original_sample_count。',
 '官方 split 保留。若作者 split 无法复现，先注册 gene/transcript/family 与 exact-input 分组，',
 '生成独立 RNA_GYM_CUSTOM 版本和 hash/seed，不修改或冒充官方 split。',
 'scaler、z-score、阈值、HPO 仅训练数据拟合；本轮没有任何拟合或标签变换。','',
 '## 恢复和运行','',
 f'`python tools/scientific_audit.py compile --prior {rel(prior)} --run {rel(run)} --resume`','',
 '输入变更须使用新 run_id；相同输入验证不可变输出后复用；状态存于 run-state.sqlite。',
 '单任务 `task --task-id T0021 --dry-run` 仅检视证据，不下载、不训练。',
 'Baseline 和 adapter 的 toy smoke 不代表真实 benchmark 结果；GPU frozen 测试需独立资源确认。',''])

def record_state(run,rows,fingerprint):
 with StateDB(ROOT/'run-state.sqlite') as state:
  with state.transaction():
   state.db.execute('''CREATE TABLE IF NOT EXISTS scientific_reviews(
    idempotency_key TEXT PRIMARY KEY,run_id TEXT NOT NULL,task_id TEXT NOT NULL,
    scientific_stage TEXT NOT NULL,disposition TEXT NOT NULL,input_sha256 TEXT NOT NULL,
    evidence_paths TEXT NOT NULL,last_heartbeat TEXT NOT NULL,retry_count INTEGER NOT NULL DEFAULT 0,exit_code INTEGER NOT NULL DEFAULT 0)''')
   state.db.execute('''CREATE TABLE IF NOT EXISTS scientific_review_events(
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,idempotency_key TEXT NOT NULL,at_utc TEXT NOT NULL,detail_json TEXT NOT NULL)''')
   for r in rows:
    key=stable([VERSION,run.name,r['task_id'],fingerprint])
    cursor=state.db.execute('INSERT OR IGNORE INTO scientific_reviews VALUES (?,?,?,?,?,?,?,?,0,0)',(key,run.name,r['task_id'],r['scientific_stage'],r['disposition'],fingerprint,r['evidence_paths'],now()))
    if cursor.rowcount:state.db.execute('INSERT INTO scientific_review_events(idempotency_key,at_utc,detail_json) VALUES (?,?,?)',(key,now(),json.dumps(dict(disposition=r['disposition'],human_approval_generated=False))))

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
 for name in ['compile','task']:
  q=sub.add_parser(name);q.add_argument('--prior',type=Path,default=Path('runs/20261022_212625'));q.add_argument('--run',type=Path,default=Path('runs/20261023_043639'));q.add_argument('--dry-run',action='store_true');q.add_argument('--resume',action='store_true')
  if name=='task':q.add_argument('--task-id',required=True)
 a=p.parse_args(argv);tid=getattr(a,'task_id',None)
 if tid and not a.dry_run:p.error('single-task inspection currently requires --dry-run; full scientific stage uses compile')
 result=compile_run((ROOT/a.prior).resolve(),(ROOT/a.run).resolve(),tid,a.dry_run)
 print(json.dumps(result if a.dry_run else result['summary'],ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
