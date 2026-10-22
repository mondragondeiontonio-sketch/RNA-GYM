#!/usr/bin/env python3
"""Compile factual local QC coverage and actionable holds; no assay admission.

Never sums file rows/versions/folds into independent experiments or task N.
Does not publish raw measurements, identity maps, upstream code or private audits.
"""
import argparse,collections,csv,datetime,hashlib,json,sqlite3
from pathlib import Path
from rnagym import ROOT,StateDB,immutable_json,read_manifest


def load(path):return json.loads(path.read_text())
def tsv(path,rows,fields):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fields,delimiter='\t',extrasaction='ignore');w.writeheader();w.writerows(rows)


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run.resolve();reports=run/'reports'
 required=['sequence_qc_summary.json','paired_full_qc_summary.json','probing_qc_summary.json','raw_nucleotide_parquet_qc.json',
  'rna3db_coordinate_summary.json','rna3db_actual_version_diff.json','rna3db_cmscan_qc.json','rna3db_atom_identity_qc.json',
  'supplemental_format_qc_summary.json','format_recovery_qc.json','final_raw_byte_verification.json']
 missing=[name for name in required if not (reports/name).is_file()]
 if missing:raise RuntimeError('QC stages incomplete: '+','.join(missing))
 byte=load(reports/'final_raw_byte_verification.json');artifacts=byte['artifacts'];rows={}
 for name in ['p0_assets.csv','licensed_small_batch.csv','full_download_assets.csv','additional_source_assets.csv','assembled_assets.csv']:
  rows.update(read_manifest(ROOT/'data/audit'/name))
 seq=load(reports/'sequence_qc_summary.json');paired=load(reports/'paired_full_qc_summary.json');probe=load(reports/'probing_qc_summary.json')
 overlaps=load(reports/'paired_all_split_overlap.json')['comparisons'];cross=[]
 with StateDB(ROOT/'run-state.sqlite') as state:
  for r in overlaps:
   left,right=r['left_asset'],r['right_asset']
   def split(aid):
    name=rows[aid]['relative_filename'];return 'train' if '_train.' in name else 'leftout' if 'leftout' in name else 'test'
   if (split(left)=='train')!=(split(right)=='train'):
    item={**r,'left_original_split':split(left),'right_original_split':split(right),'same_experiment_proven':False,'interpretation':'Cross-task exact input exposure requires assay/condition-aware leakage review; do not delete different experimental observations.'};cross.append(item)
    for aid in [left,right]:
     key=state.ensure(rows[aid]);state.transition(key,'HOLD_CROSS_TASK_LEAKAGE_REVIEW',evidence=[str(reports/'paired_all_split_overlap.json')],detail={'scope':'exact ordered pair shared across task train/heldout; source identity/conditions not established','rows_removed':0})
 issues=[]
 def issue(code,severity,scope,reason,action,evidence):issues.append({'issue_id':'QC%03d'%(len(issues)+1),'code':code,'severity':severity,'scope':scope,'finding':reason,'next_action':action,'evidence':evidence})
 issue('OFFICIAL_SPLIT_NOT_IN_MRNA_FILES','HOLD','11 mRNABench files','All11files have no explicit official split column.','Recover author gene/homology split manifests; do not reconstruct or tune on test.','sequence_qc_summary.json')
 issue('RNA_INPUT_SHARED_ACROSS_PROBING_SPLITS','HOLD','RNAGYM_RMDB','3exact raw RNA sequences occur in train and test. Different conditions are not automatically duplicate observations.','Review original sequence/probe/condition split policy; retain original data and log any future exclusion.','probing_exact_split_overlap.json')
 issue('PAIR_CROSS_TASK_TRAIN_HELDOUT_EXPOSURE','HOLD','MIR_BENCH',f'{len(cross)}file-version comparison pairs share exact inputs between train and heldout. Mirror versions are not independent studies.','Establish assay-aware cross-task exclusions before evaluation; never use heldout inputs for adaptation.','paired_all_split_overlap.json')
 issue('CLUSTER_HEADER_RESEMBLES_DATA_IDS','HOLD','RNAGYM_RMDB cluster_40','Column names resemble RNA observation IDs; possible header inference during conversion.','Compare original clustering file and conversion protocol; do not silently repair or trust group leakage claims.','cluster_mapping_review.json')
 issue('SOURCE_COMPETITION_LABEL_TERMS','HOLD','A0006 raw solution','Raw solution table occurs in public upstream bundle but competition release/usage scope is not established.','Review original competition/data release terms; not usable training/evaluation labels merely due to download.','raw_nucleotide_parquet_qc.json')
 issue('UPSTREAM_MODEL_OUTPUT_NOT_ASSAY','EXCLUDED','2 structure result tables and1raw prediction table','Upstream model metrics/predictions are not new measured assays or new leaderboard submissions.','Keep provenance only; exclude from assay counts and ranking.','raw_nucleotide_parquet_qc.json')
 atom=load(reports/'rna3db_atom_identity_qc.json');coords=load(reports/'rna3db_coordinate_summary.json')
 if atom['files_with_reused_serial_numbers']:
  issue('SOURCE_SERIAL_REUSE','REVIEW','RNA3DB coordinate files',f"{atom['files_with_reused_serial_numbers']}files reuse serial numbers; {atom['files_with_duplicate_composite_keys']}files have repeated molecular composite keys.",'Use model/chain/residue/atom/altloc keys, not serial-only identity. Retain all atoms.','rna3db_atom_identity_qc.json')
 if atom['files_with_duplicate_composite_keys']:
  issue('DUPLICATE_MOLECULAR_ATOM_KEYS','HOLD','RNA3DB coordinate files','Composite atom identities repeat in some source files.','Review atom/altloc/assembly provenance before admission; no automatic deletion.','rna3db_atom_identity_entries.jsonl')
 issue('ASSEMBLY_AND_STEREOCHEMISTRY_NOT_PASSED','HOLD','RNA3DB chain-extracted coordinates','Biological assembly metadata are absent; no complete stereochemical/clash or cross-benchmark homology review.','Register chain-only vs assembly-aware tracks and complete structural review.','rna3db_structural_review_flags.json')
 issue('PICKLE_BIOLOGICAL_CONTENT_NOT_EXECUTED','HOLD','5Wang structural/classification pickles','Only safe opcode integrity inspection performed; data not unpickled or biologically validated.','Obtain CSV/NPZ/Parquet export or explicitly reviewed isolated loader.','supplemental-WANG_ZERO_738bc3a1b453.json')
 issue('SOURCE_TEXT_ENCODING_UNVERIFIED','HOLD','GSE111508_FitnessDataMultiEnv.txt','UTF-8 fails. Byte/format audit preserves original; no encoding, delimiter or header semantics was guessed.','Confirm original encoding and column semantics.','format_recovery_qc.json')
 issue('TEXT_FILE_WITH_XLS_SUFFIX','RESOLVED_FORMAT','Clones.xls','File is delimited text rather than binary Excel; strict UTF-8 text parsing used.','Keep original filename and hash; retain parser decision in provenance.','format_recovery_qc.json')
 issue('CODING_FITNESS_PROXY_BOUNDARY','HOLD','37RNAGym mRNA-coding fitness items','Protein/genomic variant fitness is not automatically a direct RNA readout.','Verify original molecule/readout and keep proxy track separate from RNA core.','../manifests/source_metadata')
 header_path=reports/'tabular_header_review.json'
 if header_path.exists():
  header_review=load(header_path)['members_with_ambiguous_headers']
  if header_review:issue('EMPTY_OR_DUPLICATE_COLUMN_HEADERS','HOLD','Source CSV representations',f'{len(header_review)}members have empty or duplicate column headers.','Confirm source column identities; preserve raw and do not silently drop/rename columns.','tabular_header_review.json')
 representation_path=reports/'cross_benchmark_representation_duplicates.json'
 if representation_path.exists():
  reused=load(representation_path)
  issue('CROSS_BENCHMARK_FILE_REPRESENTATION_REUSE','REVIEW','RNAGym vs Wang collection',f"{reused['same_named_variant_files']}same-named source files; {reused['exact_byte_identical_files']}are byte-identical.",'Retain version provenance and forbid double source-family/assay weighting.','cross_benchmark_representation_duplicates.json')
 issue('ASSAY_RIGHTS_UNITS_AND_HUMAN_REVIEW','HOLD','All candidate assays','Full original experimental identity, units/direction/replicates/negative-generation and human review are not complete.','Complete original assay evidence and human-reviewed admission gate; no automated signature.','qc_summary.json')
 tsv(reports/'qc_issue_log.tsv',issues,['issue_id','code','severity','scope','finding','next_action','evidence'])
 # File-level coverage never means task-wide N or assay identity.
 asset_rows=[]
 con=sqlite3.connect(ROOT/'run-state.sqlite');con.row_factory=sqlite3.Row
 for record in artifacts:
  aid=record['asset_id'];r=rows[aid];name=r['relative_filename'];role='DATA_OR_MIXED_SOURCE_ARCHIVE'
  if '.part-' in name:role='AUTHOR_MULTIPART_COMPONENT_NOT_SAMPLE_SET'
  elif name.endswith(('.sha256','SHA256SUMS.txt')):role='AUTHOR_CHECKSUM_MANIFEST_NOT_ASSAY'
  elif aid in ['HF_287b2797cface258321d','HF_51b53dab485ecb3d7409']:role='UPSTREAM_MODEL_RESULT_TABLE_NOT_ASSAY'
  elif 'cmscan' in name or 'jsons' in name:role='STRUCTURAL_SOURCE_INDEX_OR_RFAM_ANNOTATION'
  elif 'cluster_40' in name:role='CLUSTER_MAPPING_SCHEMA_UNVERIFIED'
  elif aid in ['A0004','A0012']:role='ALIGNMENT_OR_PROFILE_NOT_EXPERIMENTAL_LABELS'
  job=con.execute('SELECT stage FROM jobs WHERE asset_id=? AND task_id IS NULL',(aid,)).fetchone()
  assert job is not None
  asset_rows.append({**record,'file_name':name,'role':role,'job_stage':job['stage'],'qc_scope':'TECHNICAL_FORMAT_AND_IDENTITY_SCAN_ONLY; see modality reports and issue log','assay_admitted':False})
 tsv(reports/'qc_asset_status.tsv',asset_rows,['asset_id','package_group_id','file_name','sha256','bytes','raw_readonly','role','job_stage','qc_scope','assay_admitted'])
 with (ROOT/'data/registries/download_packages_47.csv').open(encoding='utf-8-sig') as f:packages=list(csv.DictReader(f))
 with (ROOT/'data/registries/search_level_task_crosswalk_198.csv').open(encoding='utf-8-sig') as f:tasks=list(csv.DictReader(f))
 with (ROOT/'data/audit/task_status.tsv').open() as f:old_status={r['task_id']:r for r in csv.DictReader(f,delimiter='\t')}
 groups=collections.Counter(r['package_group_id'] for r in asset_rows);package_rows=[]
 for group in packages:
  gid=group['package_group_id'];n=groups[gid]
  package_rows.append({'package_group_id':gid,'local_acquired_artifact_count':n,'status':'EXCLUDED_NON_ASSAY_OR_SOFTWARE' if group['download_action']=='NO_DOWNLOAD' else 'ACQUIRED_SCOPED_QC_REVIEW_PENDING' if n else 'HOLD_SOURCE_RIGHTS_OR_RELEASE','original_source_url':group['preferred_download_url'] or group['code_url'],'next_action':'Complete task/assay-specific scientific/rights review; file acquisition is not task completion.' if n else 'Resolve existing source/rights/auth/release blocker before acquisition.','assays_admitted':0})
 tsv(reports/'package_qc_status_47.tsv',package_rows,list(package_rows[0]))
 task_rows=[]
 for task in tasks:
  old=old_status[task['row_id']];gid=task['package_group_id'];status=old['state'];action=old['next_action']
  if not status.startswith('EXCLUDED_') and groups[gid]:
   status='HOLD_ASSAY_TASK_REVIEW'
   if gid=='RNAGYM_RMDB':status='HOLD_LEAKAGE_SCHEMA_AND_ASSAY_REVIEW'
   elif gid=='MIR_BENCH':status='HOLD_CROSS_TASK_LEAKAGE_AND_ASSAY_REVIEW'
   elif gid.startswith('MRNA_'):status='HOLD_ORIGINAL_SPLIT_UNITS_AND_ASSAY_REVIEW'
   elif gid=='RNA3DB':status='HOLD_ASSEMBLY_HOMOLOGY_AND_ASSAY_REVIEW'
   action='Use run QC issue log; bind original assay to task and reviewed official split/rights/units before admission. Do not infer task N from package file counts.'
  task_rows.append({'task_id':task['row_id'],'package_group_id':gid,'status':status,'package_artifact_count_not_task_completion':groups[gid],'reported_n':task['reported_n'],'reported_n_status':'REPORTED_UNVERIFIED','actual_task_n':'','assay_identity_verified':False,'admitted':False,'next_action':action})
 tsv(reports/'task_qc_coverage_198.tsv',task_rows,list(task_rows[0]))
 raw_nt=load(reports/'raw_nucleotide_parquet_qc.json');probe_rows=[]
 for path in (reports/'probing_qc').glob('*.json'):
  d=load(path);probe_rows.append(d)
 summary={'run_id':run.name,'compiled_at_local_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'registered_tasks':198,'package_groups':47,'groups_with_acquired_artifacts':len(groups),'local_acquired_artifacts':len(asset_rows),
  'network_downloaded_artifacts':sum(r['acquisition_method']!='AUTHOR_MULTIPART_REASSEMBLY' for r in artifacts),
  'lossless_reassembled_artifacts':sum(r['acquisition_method']=='AUTHOR_MULTIPART_REASSEMBLY' for r in artifacts),
  'local_raw_artifact_bytes_including_reassembly':sum(r['bytes'] for r in artifacts),'all_raw_sha256_match':byte['all_sha256_match'],
  'mrna_files_all_rows_scanned':seq['files_scanned'],'mrna_file_rows_scanned':sum(r['actual_n'] for r in seq['results']),
  'paired_files_all_rows_scanned':paired['files_scanned'],'paired_file_rows_including_versions':paired['actual_file_rows_including_versions'],
  'probing_sequence_records_scanned':sum(r['actual_n'] for r in probe_rows),'probing_exact_shared_train_test_sequences':3,
  'raw_nucleotide_index_rows_scanned':sum(r['actual_rows'] for r in raw_nt['results']),
  'coordinate_files_scanned':coords['coordinate_files_scanned'],'coordinate_atom_rows_scanned':coords['atom_rows_scanned'],
  'coordinate_schema_parse_holds':coords['files_held'],'composite_atom_identity':atom,
  'qc_issue_count':len(issues),'held_task_rows':sum(r['status'].startswith('HOLD_') for r in task_rows),'excluded_task_rows':sum(r['status'].startswith('EXCLUDED_') for r in task_rows),
  'final_admitted_assays':0,'all47packages_downloaded':False,'all_assays_full_scientific_qc_complete':False,
  'code_executed_from_archives_or_pickle':False,'raw_values_changed':False,'rows_deleted':0,'splits_reconstructed':False,
  'scaler_threshold_or_hpo_fitted':False,'gpu_training_or_fm_inference':False,
  'published_site_snapshot_not_overwritten':True,'scope_warning':'File rows/versions/chunks/folds/nucleotide positions/chain structures are NOT independent assays or task sample counts.'}
 immutable_json(reports/'qc_summary.json',summary)
 # Public-safe local metadata export only. No network/git push here.
 (ROOT/'data/audit/qc_latest_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
 text=f'''# RNA-Gym 本轮数据 QC 报告

## 结论与边界

已完成本轮已获取文件的自动化、模态分层技术 QC。
**这不是所有 assay 的完整科学审核，也不是最终准入。**
当前最终准入为 **0**；{summary['held_task_rows']} 个注册任务保持 HOLD，
{summary['excluded_task_rows']} 个为非 assay／控制项排除。
未修改原始标签、删除观测、重建 split、拟合 scaler／阈值／HPO，
也未进行 GPU 训练、模型推理或运行归档内的代码／pickle。

## 实际覆盖

| 范围 | 实际完成量 | 完成检查 |
|---|---:|---|
| 本地获取产物 | {len(asset_rows)} 个，{summary['local_raw_artifact_bytes_including_reassembly']:,} 字节 | 真实 SHA256 复验与只读原本 |
| mRNABench | {summary['mrna_files_all_rows_scanned']} 文件，{summary['mrna_file_rows_scanned']:,} 行 | 序列、轨道、标签、重复、共享输入 |
| miRBench | {summary['paired_files_all_rows_scanned']} 文件，{summary['paired_file_rows_including_versions']:,} 文件行 | 全量 ordered-pair、标签、重复与跨文件检查 |
| RMDB Parquet | {summary['probing_sequence_records_scanned']:,} 序列记录 | nucleotide 向量长度、缺失、范围、probe 分层 |
| 原始 nucleotide Parquet | {summary['raw_nucleotide_index_rows_scanned']:,} 索引行 | 全量向量化数值、ID、缺失及产物角色检查 |
| RNA3DB mmCIF | {summary['coordinate_files_scanned']:,} 文件 | 坐标有限性、模型／链、残基与原子复合身份 |

文件行、镜像版本、CV 重复表示、分块、核苷酸位置和结构链不是独立实验数。
原始 nucleotide 表中的预测值已排除为非实验 assay，competition solution 标签继续 HOLD。
RNA3DB 新旧版本已计算真实 chain/PDB 变化，但没有自动采用新版或改榜。

## 关键审查项

1. RMDB train/test 共享 **3 条精确 RNA 输入**；未擅自删除或改分折。
2. miRBench 跨任务有 train/heldout 输入共享及跨来源标签不一致；
   不同实验条件不可直接合并，镜像不可重复计权。
3. 11 个 mRNA 文件没有显式官方 split；标签单位／方向及原始 assay 仍需确认。
4. `cluster_40.parquet` 列名疑似样本 ID，需要原始映射核对，未自动修复。
5. 3D 结果表及原始 RibonanzaNet 预测不是新增实验标签或本项目榜单结果。
6. RNA3DB 链提取坐标没有 biological assembly 元数据；
   serial 重用与真正复合原子键重复已分别检查，不按序号直接删除原子。
7. 5 个 pickle 只作静态 opcode 审计，未反序列化；生物学 QC 等待安全格式导出。
8. 一个 TXT 编码仍待源头确认，`Clones.xls` 的文本格式后缀不符已记录并处理。
9. 37 个 mRNA-coding fitness 代理项不自动进入直接 RNA 核心轨道。
10. 完整 stereochemistry、原始实验／权利／replicate／negative-generation、
    跨 benchmark 同源泄漏及人工审核尚未全部完成。

## 可复现证据

- [机器可读总览](qc_summary.json)
- [逐文件状态与真实 SHA256](qc_asset_status.tsv)
- [逐条问题与下一步动作](qc_issue_log.tsv)
- [198 个原始任务的 QC 覆盖／HOLD](task_qc_coverage_198.tsv)
- [47 个管理包的获取与 QC 状态](package_qc_status_47.tsv)
- [全量 paired 输入重叠](paired_all_split_overlap.json)
- [RMDB 精确 split 重叠](probing_exact_split_overlap.json)
- [RNA3DB 真实版本变化](rna3db_actual_version_diff.json)
- [RNA3DB 复合原子身份检查](rna3db_atom_identity_qc.json)
- [作者分块与完整归档 SHA 核对](multipart_assembly.json)

身份 SQLite／Parquet、原始数据、原始测量和这轮详细报告保留在本地。
本轮没有覆盖已发布的网站快照；原网站统计不得理解为这轮最新本地进度。
'''
 (reports/'QC_REPORT.md').write_text(text,encoding='utf-8')
 print(json.dumps({k:summary[k] for k in ['local_acquired_artifacts','mrna_file_rows_scanned','paired_file_rows_including_versions','probing_sequence_records_scanned','raw_nucleotide_index_rows_scanned','coordinate_files_scanned','qc_issue_count','final_admitted_assays']},indent=2))


if __name__=='__main__':main()
