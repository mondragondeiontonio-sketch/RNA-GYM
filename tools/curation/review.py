"""Compile full 198-row current audit without mutating formal approval state."""
import collections
import csv
import itertools
import json
from pathlib import Path

from .core import ROOT,RUN,VERSION,file_sha,write_json,write_tsv


def read_reports():
    result=[]
    for p in sorted((ROOT/'data/processed').glob('*/'+VERSION+'/qc_report.json')):
        if not (p.parent/'complete.json').exists():continue
        report=json.loads(p.read_text())
        if file_sha(ROOT/report['output_path'])!=report['output_sha256']:
            raise ValueError('CURATED_HASH_CHANGED:'+report['unit_id'])
        result.append(report)
    return result


def text(value):
    if isinstance(value,(dict,list)):value=json.dumps(value,ensure_ascii=False,separators=(',',':'))
    return str(value if value is not None else 'UNKNOWN').replace('|',' / ').replace('\n',' ')


def md_table(rows,fields):
    return '| '+' | '.join(fields)+' |\n|'+ '|'.join(['---']*len(fields))+'|\n'+''.join(
        '| '+' | '.join(text(r.get(k,'UNKNOWN')) for k in fields)+' |\n' for r in rows)


def source_primary_lookup():
    p=RUN/'primary_methods/index.json'
    result={}
    if p.exists():
        for item in json.loads(p.read_text()):
            for alias in item['assay_ids']:result[alias]=item
    return result


def compile_review(reports,overlap_summary=None):
    registry=list(csv.DictReader((ROOT/'data/registries/search_level_task_crosswalk_198.csv').open(encoding='utf-8-sig')))
    if len(registry)!=198:raise ValueError('REGISTERED_TASK_COUNT_CHANGED')
    physical=list(csv.DictReader((ROOT/'data/audit/local_inventory.tsv').open(),delimiter='\t'))
    present={r['package_group_id'] for r in physical if r['status']=='PRESENT_HASH_VERIFIED'}
    by_task=collections.defaultdict(list)
    primary=source_primary_lookup()
    assays=[];mapping=[];statistics=[];duplicates=[];gaps=[];aliases=[]
    mrna_evidence={r['relative_filename']:r for r in json.loads((ROOT/'data/audit/phase2_mrna_source_evidence.json').read_text())['records']}
    for r in reports:
        unit=r['unit_id'];split=r.get('split',{})
        if unit=='MRNA_mirna_preprocessed':
            r['problem_type']='positive_unlabeled_multilabel_classification'
            r['metric']='per-head AUPRC/AUROC only with explicit absence-label caveat; not regression; see modality_findings.tsv'
        easy=split.get('EAZY',{});ood=split.get('OOD_split',{})
        # A truthful narrow technical pass: schemas/retained records, not raw
        # experiment validation, rights approval or human admission.
        r['technical_qc_pass']=r['record_qc_status']=='PASS'
        r['split_pass']=easy.get('status')=='PASS'
        r['scientific_qc_pass']=False # computed from unresolved critical evidence below
        r['admission_review_ready']=False # never inferred from file QC alone
        r['formal_admitted']=False
        r['technical_stage']='SPLIT_DONE' if r['split_pass'] else 'DEDUP_DONE'
        if r.get('proxy'):recommendation='SECONDARY_PROXY'
        else:recommendation='HOLD'
        # This is a track recommendation, not automatic ADMITTED status.
        track='SECONDARY_PROXY' if r.get('proxy') else 'CORE_CANDIDATE'
        if r['modality'] in ['rna_protein']:track='EXTENDED_CANDIDATE'
        original=primary.get(unit.removeprefix('DMS_'),{})
        doc=original.get('xml_path')
        ev=mrna_evidence.get(unit.removeprefix('MRNA_')+'.parquet')
        remaining=list(r.get('scientific_gaps',[]))
        if ev:
            remaining.extend(x['code'] for x in ev.get('remaining_blockers',[])
                if x['code']!='SPLIT_MANIFEST_AND_LEAKAGE_NOT_VERIFIED')
        remaining=list(dict.fromkeys(remaining))
        if r['modality']=='dms' and not r['unit_id'].startswith('DMS_CVONLY_'):
            remaining+=['processed score transformation/direction is not established by a paper-title match']
        approval_only=lambda value: any(token in str(value).lower() for token in ['manual review','human review','data-specific rights','rights','review_approval_required'])
        unresolved_scientific=[b for b in remaining if not approval_only(b)]
        r['scientific_qc_criteria']={'record_qc':r['technical_qc_pass'],
            'critical_input_target_identity_gaps_resolved':not unresolved_scientific,
            'source_version_sha256_bound':bool(r.get('output_sha256'))}
        r['scientific_qc_pass']=all(r['scientific_qc_criteria'].values())
        rights_documented=bool(ev and ev.get('data_license',{}).get('data_license_evidence_status','').startswith('VERIFIED'))
        r['admission_review_ready']=r['scientific_qc_pass'] and r['split_pass'] and rights_documented
        if r['admission_review_ready'] and not r.get('proxy'):
            recommendation='ADMITTED_EXTENDED' if track=='EXTENDED_CANDIDATE' else 'ADMITTED_CORE'
        r['current_blockers']=remaining
        r['admission_recommendation']=recommendation
        r['recommended_track']=track
        assays.append({'canonical_assay_id':r['assay_id'],'source_assay_id':unit,
            'origin_paper_doi':original.get('doi',r.get('source_doi','UNKNOWN')),
            'source':r['source'],'identity_status':r['assay_identity_status'],
            'canonical_release_assay_id_verified':r.get('independently_verified_assay',False),
            'experimental_independence_verified':False,
            'valid_n':r['valid_n'],'row_count_unit':'eligible curated observations in this source-context/readout view',
            'biological_replicates':'UNKNOWN','primary_methods':doc or (ev or {}).get('source_doi','UNKNOWN'),
            'original_raw_qc_reperformed':False,'version':VERSION,'qc_report':r['output_path'].replace('curated_data.parquet','qc_report.json')})
        for tid in r['task_ids']:
            by_task[tid].append(r)
            mapping.append({'task_id':tid,'canonical_assay_id':r['assay_id'],'curation_unit':unit,
                'input_view':'sequence_b_only_negative_control' if tid=='T0063' else 'full_declared_input',
                'mapping_scope':'AVAILABLE_LOCAL_SUBSET; not proof of full registered benchmark coverage',
                'version':VERSION,'curated_path':r['output_path']})
        statistics.append({k:r.get(k) for k in ['unit_id','assay_id','package_group_id','modality','actual_n','valid_n','unique_n',
            'duplicate_n','excluded_n','quarantined_n','length','gc','target_statistics','class_counts','valid_nucleotide_labels']}|
            {'biological_replicate_n':'UNKNOWN','condition_count':'UNKNOWN_WHEN_NOT_EXPLICIT','author_reported_n':4176 if unit=='DMS_Domingo_2018_tRNA' else r.get('reported_n') or 'UNKNOWN',
             'paper_minus_local_n':4176-r['actual_n'] if unit=='DMS_Domingo_2018_tRNA' else 'UNKNOWN',
             'N_discrepancy_explanation':'UNKNOWN: primary Methods S11 reports 4176 genotypes, released processed assay has 4175; no missing variant fabricated' if unit=='DMS_Domingo_2018_tRNA' else 'UNKNOWN_OR_NOT_APPLICABLE',
             'count_reconciliation':'Actual published release rows; paper N not replaced by benchmark registry N.'})
        duplicates.append({k:r.get(k) for k in ['unit_id','actual_n','exact_input_repeated_rows','exact_input_duplicate_groups',
            'duplicate_n','input_label_conflict_groups','observation_label_conflict_groups','excluded_n','quarantined_n']}|
            {'same_gene_transcript':'preserved via available group metadata; not silently treated as duplicate observations',
             'near_duplicate_homology':ood.get('n_groups','UNKNOWN'),'homology_basis':'MMseqs2 .8 identity/.8 bidirectional coverage plus declared groups'})
        gaps.append({'unit_id':unit,'upstream_qc_status':'PRIMARY_FULLTEXT_AVAILABLE_PARTIALLY_REVIEWED' if doc else 'SOURCE_SPECIFIC_EVIDENCE_OR_GAPS',
            'rnagym_qc_required':r['qc_rules'],'new_qc_completed':['record QC','observation mapping','duplicate/conflict audit',
                'EAZY' if r['split_pass'] else 'EAZY_NOT_FEASIBLE','OOD_split:'+ood.get('status','MISSING')],
            'remaining_qc_gaps':remaining,'scientific_qc_status':'PARTIAL_SCIENTIFIC_EVIDENCE; NOT_FULL_SCIENTIFIC_QC_PASS'})
    # Source aliases with actual mirror content vs metadata-only identity.
    old=json.loads((ROOT/'runs/20261022_212625/reports/cross_benchmark_representation_duplicates.json').read_text())
    for x in old['comparisons']:
        aliases.append({'source_alias':'WANG:'+x['source_alias'],'canonical_assay_id':'DMS:'+x['source_alias'],
            'evidence':'EXACT_MEMBER_SHA256_EQUAL','left_sha256':x['rnagym_member_sha256'],'right_sha256':x['wang_member_sha256'],
            'independent_experiment_weight':0,'sample_level_verified':True})
    for x in csv.DictReader((ROOT/'data/registries/RNAGym_NABench_DMS_ID_91.csv').open(encoding='utf-8-sig')):
        aliases.append({'source_alias':'NABENCH:'+x['assay_dms_id'],'canonical_assay_id':'DMS:'+x['assay_dms_id'],
            'evidence':x['assay_identity_evidence'],'sample_level_verified':False,
            'sample_level_gap':'NABench file bytes not present in bound cache; no new download performed',
            'independent_experiment_weight':'NOT_RESOLVED_BY_METADATA_ONLY'})
    write_tsv(ROOT/'data/audit/assay_master.tsv',assays)
    write_tsv(ROOT/'data/audit/task_assay_mapping.tsv',mapping)
    write_tsv(ROOT/'data/audit/source_alias_canonical_assay.tsv',aliases)
    write_tsv(ROOT/'data/audit/dataset_statistics.tsv',statistics)
    write_tsv(ROOT/'data/audit/duplicate_summary.tsv',duplicates)
    write_tsv(ROOT/'data/audit/qc_gap_analysis.tsv',gaps)
    overview=[];schema=[];admission=[]
    nondata={'T0106','T0107','T0033'}
    for task in registry:
        tid=task['row_id'];units=by_task[tid]
        local=task['package_group_id'] in present
        excluded=task['search_dedup_decision'].startswith('EXCLUDE_') or task['package_group_id']=='METHODOLOGY_ONLY' or tid in nondata
        proxy=bool(units) and all(r.get('proxy') for r in units) or tid=='T0063'
        recommend='EXCLUDED' if excluded else 'SECONDARY_PROXY' if proxy else 'HOLD'
        unit_ids=[r['unit_id'] for r in units]
        actual=sum(r['actual_n'] for r in units) if units else 'UNKNOWN'
        valid=sum(r['valid_n'] for r in units) if units else 'UNKNOWN'
        unique=sum(r['unique_n'] for r in units) if units else 'UNKNOWN'
        split_counts={name:dict(collections.Counter(r['split'].get(name,{}).get('status','NOT_RUN') for r in units)) for name in ['EAZY','OOD_split']}
        blockers=sorted({b for r in units for b in r['current_blockers']})
        if not units:blockers=['NO_SCHEMA_BOUND_CURATED_DATA_FOR_THIS_TASK; package file existence alone is not task data']
        if excluded:blockers=['outside RNA-specific experimental benchmark scope or method-only row']
        row={'task_id':tid,'source':task['dataset'],'assay_id':sorted({r['assay_id'] for r in units}) or 'UNRESOLVED',
             'input':{'view':'miRNA sequence_b only' if tid=='T0063' else [r['input_schema'] for r in units[:3]],
                      'length_range':([min(r['length']['min'] for r in units if r['length']['min'] is not None),
                                       max(r['length']['max'] for r in units if r['length']['max'] is not None)] if units else 'UNKNOWN')},
             'label':sorted({r['label_definition'] for r in units}) or 'UNVERIFIED_LOCAL_LABEL',
             'label_unit':sorted({r['label_unit'] for r in units}) or 'UNKNOWN',
             'problem_type':sorted({r['problem_type'] for r in units}) or task['task_type'],
             'reported_n':task['reported_n'] or 'UNKNOWN',
             'reported_n_scope':'existing search registry / benchmark report, NOT independently reverified original-paper N',
             'original_paper_n':'UNKNOWN_UNLESS_SOURCE_SPECIFIC_EVIDENCE',
             'actual_n':actual,'valid_n':valid,'unique_n':unique,
             'duplicate_n':sum(r['duplicate_n'] for r in units) if units else 'UNKNOWN',
             'original_qc':'primary evidence matrix: data/audit/original_qc_evidence.tsv; gaps explicitly retained',
             'rnagym_qc':'RECORD_QC_DONE' if units else 'NO_BOUND_DATA',
             'split':split_counts,'leakage':'per-unit exact observation/group audited; cross-source pooled split NOT certified' if units else 'NOT_RUN',
             'admission':recommend,'blocker':blockers,
             'physical_package_local':local,'curated_data_local':bool(units),
             'curation_unit_count':len(units),'curation_units':unit_ids,
             'technical_qc_pass':bool(units) and all(r['technical_qc_pass'] for r in units),
             'split_pass':bool(units) and all(r['split_pass'] for r in units),
             'scientific_qc_pass':bool(units) and all(r['scientific_qc_pass'] for r in units),
             'admission_review_ready':bool(units) and all(r['admission_review_ready'] for r in units),'admitted':False,
             'scope':'AVAILABLE_LOCAL_SUBSET; counts are task views and MUST NOT be summed across task IDs'}
        overview.append(row)
        schema.append({'task_id':tid,'curation_units':unit_ids,'input_schema':row['input'],
            'target_schema':{r['unit_id']:r['target_schema'] for r in units},
            'experimental_context':{r['unit_id']:r.get('experimental_context','see curated context_json') for r in units},
            'task_type':row['problem_type'],'metric':{r['unit_id']:r['metric'] for r in units},
            'baseline_spec':'train-only mean/median for continuous readouts; prevalence/majority for binary; no baseline trained',
            'loss':'NOT_AUTOMATICALLY_ASSIGNED'})
        admission.append({k:row[k] for k in ['task_id','physical_package_local','curated_data_local','technical_qc_pass',
            'split_pass','scientific_qc_pass','admission_review_ready','admitted','admission','blocker']}|
            {'recommended_track':'SECONDARY_PROXY' if proxy else 'EXCLUDED' if excluded else 'MIXED_CORE_PROXY_MUST_SEPARATE' if units and any(r.get('proxy') for r in units) else 'CORE_OR_EXTENDED_CANDIDATE',
             'human_reviewer':None,'review_policy':'No fabricated reviewer or formal gate modification'})
    write_tsv(ROOT/'data/audit/task_input_label_schema.tsv',schema)
    write_tsv(ROOT/'data/audit/scientific_admission.tsv',admission)
    # Keep a machine-readable *198-row* counterpart of the full Markdown table.
    write_tsv(ROOT/'data/audit/task_dataset_overview.tsv',overview)
    summary={'version':VERSION,'registered_tasks':len(registry),'local_physical_resources':len(physical),
        'raw_bytes':sum(int(r.get('bytes') or 0) for r in physical),
        'all_bound_raw_resources_hash_verified':all(r['status']=='PRESENT_HASH_VERIFIED' for r in physical),
        'tasks_with_local_package_files':sum(r['physical_package_local'] for r in overview),
        'tasks_with_schema_bound_curated_data':sum(r['curated_data_local'] for r in overview),
        'curation_units':len(reports),'canonical_author_DMS_assay_IDs':sum(r.get('independently_verified_assay',False) for r in reports),
        'fully_verified_independent_original_experiments':'UNKNOWN; canonical author assay IDs are not experimental-independence proof',
        'registered_source_families':len(list(csv.DictReader((ROOT/'data/registries/source_family_crosswalk_123.csv').open(encoding='utf-8-sig')))),
        'registered_resource_groups':len(list(csv.DictReader((ROOT/'data/registries/download_packages_47.csv').open(encoding='utf-8-sig')))),
        'actual_rows_in_selected_canonical_release_views':sum(r['actual_n'] for r in reports),
        'valid_curated_records':sum(r['valid_n'] for r in reports),
        'record_count_scope':'sum over selected source-context/readout views; NOT total independent biological samples',
        'excluded_records':sum(r['excluded_n'] for r in reports),
        'quarantined_records':sum(r['quarantined_n'] for r in reports),
        'dedup_alias_records':sum(r['duplicate_n'] for r in reports),
        'units_with_exact_duplicate_inputs':sum(r['exact_input_repeated_rows']>0 for r in reports),
        'units_with_true_observation_aliases':sum(r['duplicate_n']>0 for r in reports),
        'valid_nucleotide_labels':sum(r['valid_nucleotide_labels'] for r in reports),
        'units_EAZY_pass':sum(r['split_pass'] for r in reports),
        'units_OOD_split_pass':sum(r['split'].get('OOD_split',{}).get('status')=='PASS' for r in reports),
        'units_OOD_not_feasible':sum(r['split'].get('OOD_split',{}).get('status')=='NOT_FEASIBLE' for r in reports),
        'units_OOD_blocked':sum(r['split'].get('OOD_split',{}).get('status')=='BLOCKED' for r in reports),
        'tasks_technical_QC_pass':sum(r['technical_qc_pass'] for r in overview),
        'tasks_all_available_units_EAZY_pass':sum(r['split_pass'] for r in overview),
        'tasks_SCIENTIFIC_QC_PASS':sum(r['scientific_qc_pass'] for r in overview),
        'tasks_ADMISSION_REVIEW_READY':sum(r['admission_review_ready'] for r in overview),
        'tasks_ADMITTED':sum(r['admitted'] for r in overview),
        'recommendation_counts':dict(collections.Counter(r['admission'] for r in overview)),
        'modality_unit_counts':dict(collections.Counter(r['modality'] for r in reports)),
        'task_biological_capability_counts':dict(collections.Counter(r['scoring_family'] for r in registry)),
        'source_package_unit_counts':dict(collections.Counter(r['package_group_id'] for r in reports)),
        'overlap':overlap_summary or {},'raw_modified':False,'formal_gate_modified':False,
        'models_trained':0,'human_signatures_created':0,
        'full_user_scientific_audit_complete':False,
        'external_cache_binding_complete':False,
        'unbound_external_cache_candidates':sum(1 for _ in (ROOT/'data/audit/external_cache_candidates.tsv').open())-1}
    if summary['actual_rows_in_selected_canonical_release_views'] != summary['valid_curated_records']+summary['excluded_records']+summary['quarantined_records']+summary['dedup_alias_records']:
        raise ValueError('RECORD_RECONCILIATION_FAILED')
    summary['EAZY_fold_count_distribution']=dict(collections.Counter(str(r['split'].get('EAZY',{}).get('n_folds')) for r in reports))
    summary['OOD_fold_count_distribution']=dict(collections.Counter(str(r['split'].get('OOD_split',{}).get('n_folds')) for r in reports))
    for name,filename in [('independent_validation','independent_validation_summary.json'),('multilabel_support','multilabel_support_summary.json')]:
        p=RUN/filename
        if p.exists():summary[name]={k:v for k,v in json.loads(p.read_text()).items() if k not in ('results','failures')}
    write_json(ROOT/'data/audit/scientific_curation_summary.json',summary)
    write_reports(summary,overview,reports,gaps)
    return summary


def write_reports(summary,overview,reports,gaps):
    directory=ROOT/'reports/scientific_admission';directory.mkdir(parents=True,exist_ok=True)
    fields=['task_id','source','assay_id','input','label','label_unit','problem_type','reported_n','actual_n','valid_n','unique_n','duplicate_n',
            'original_qc','rnagym_qc','split','leakage','admission','blocker']
    intro='''# RNA-Gym 本地数据与任务总览\n\n## 计数口径\n\n本表完整覆盖 198 个注册行。`reported_n` 保留检索注册表的论文/benchmark 声称数，\n不伪称逐原始论文重新核实。`actual_n` 等计数来自实际处理结果。\n同一数据可服务多个任务；**禁止将任务表的 N 再相加**。\n`unique_n` 是保守记录身份规则下的 observation 数，不是已证明独立的 biological replicate 数。\n官方 assay ID、原始独立实验、下游任务、物理文件四种单位严格分开。\n未知实验条件不会因为相同序列而自动合并；OOD 组仅表达所声明的聚类协议。\n\n'''
    (directory/'DATASET_OVERVIEW.md').write_text(intro+'## 实际运行汇总\n\n```json\n'+json.dumps(summary,ensure_ascii=False,indent=2)+'\n```\n\n## 全部任务\n\n'+md_table(overview,fields))
    (directory/'README.md').write_text('''# RNA-Gym 科学清洗当前版本\n\n## 本轮实质产物\n\n- 已在原有工程与原始缓存上执行记录 QC、保守身份映射、去重和独立分折。\n- 主版本：`rnagym-qc-2026-10-28-v1`，真实数据位于 `data/processed/`。\n- `data/audit/scientific_curation_summary.json` 为运行数字的机器权威入口。\n- `DATASET_OVERVIEW.md` 完整列出 198 个任务；每个数据版本有一个主 `qc_report.json`。\n- `EAZY` 是随机 observation 对照，`OOD_split` 是声明阈值的序列聚类分组；\n  二者不是作者 split。原作者分区仍保存在 `original_split`。\n\n## 当前不能宣称完成的内容\n\n完整原始实验 Methods/Supplement、逐记录实验身份、上游 score 变换、\n全部跨来源同源性、权利链和人工科学审批仍有未解决项。\n**RECORD_QC_PASS 不等于 SCIENTIFIC_QC_PASS，更不等于 ADMITTED。**\n本轮没有篡改原正式 gate，也没有伪造 reviewer。\n不为了避免 HOLD 而虚构证据或将原始实验数写成 assay 别名数。\n\n## 复现\n\n```bash\n.venv-qc/bin/python -m tools.curate_scientific\n.venv-qc/bin/python -m tools.curation.finalize\n.venv-qc/bin/python -m unittest tests.test_scientific_curation -v\n```\n\n在冻结完成后禁止刷新既有数据版本；对受影响版本显式另行审核。\n未绑定的外部本机缓存列于 `data/audit/external_cache_candidates.tsv`，\n不能把未绑定候选当作已经缺失、也不能自动合并为新原始实验。\n''')
    (directory/'ORIGINAL_QC_COMPARISON.md').write_text('''# 原作者 QC 与 RNA-Gym 差异\n\n## 一手证据\n\n逐项证据：`data/audit/original_qc_evidence.tsv`；缺口：`data/audit/qc_gap_analysis.tsv`。\n每个主文档检查 12 类 QC。`unknown` 表示待核实；`not_reported` 只表示取得的主文 XML\n中未找到，不能解释为作者没有执行。关键词候选不会自动标为 performed。\n`not_performed` 仅用于 HP5 Methods 明确表示 UMI 多样性不足、未用于去重。\n\n## 已核实的方法示例\n\n- HP5/Sugimoto：UMI 提取、拆分文库、Cutadapt、非基因组 G 与低丰度 TSS 过滤。\n- Saluki 原始 compendium：跨研究一致性、异常研究检查、标准化/PCA 补值与分位数归一化。\n  发布的 PC1 不是小时；本轮没有重新全数据拟合这些变换。\n- Domingo tRNA：Cutadapt/PEAR；任一 input replicate 少于 9 reads、意外突变、\n  output 零 reads 等过滤；Methods 报告 4,176 genotypes，未自动替换为任何注册任务 N。\n- Andreasson glmS：barcode consensus 至少 66% 同意度，逐位二项检验，\n  以及序列到 barcode consensus 的 Hamming 距离约束。\n- Kobori：报告 library 重复制备/测序及独立生化测定一致性。\n\n## 不可复现的上游步骤\n\n本轮主要输入为作者已处理数据。原始测序 reads、barcode 图像、完整原始仪器读数\n没有全部绑定，不能冒称重新执行上游实验 QC。新做的是 schema、数值/字符、\n向量/构件身份、冲突/重复、真实数据输出及独立划分。\n\n## 新 QC 与剩余缺口\n\n'''+md_table(gaps,['unit_id','upstream_qc_status','new_qc_completed','remaining_qc_gaps']))
    duplicate_rows=[{k:r[k] for k in ['unit_id','actual_n','exact_input_repeated_rows','duplicate_n','input_label_conflict_groups','quarantined_n']} for r in reports]
    (directory/'DUPLICATION_AND_OVERLAP.md').write_text('''# 重复、镜像与跨数据集重叠\n\n## 处理规则\n\n- 相同序列不是相同实验。不同条件、replicate 或身份未确认的记录保留。\n- 相同已知 observation 与相同标签的重复表示只计一次，并保留 alias 映射。\n- 同一已知 observation 标签冲突进入 QUARANTINE，不多数表决或平均标签。\n- mRNA transcript ID 本身不能证明同一次测量；未知条件下不同标签保留为 FLAG。\n- 70 对 RNAGym/Wang 同名成员已有真实逐字节 SHA256 相同证据，复用一份 canonical data。
- APA 的 26,331 条序列有十个 X 的未知前缀：隔离的是当前无法可靠表示的输入，
  不是宣布实验标签无效；不将 X 擅自替换为 N，也不删除原始测量。
- Domingo tRNA 原 Methods S11 报告 4,176 genotypes，本地 released processed 表为
  4,175 条；缺失的一个 variant 原因 UNKNOWN，不通过补造记录消除差异。\n- RNAGym/NABench 91 行仅提供身份映射证据；没有本地 NABench bytes 的部分\n  不谎称已经做完样本级内容核验。\n- 跨单位 exact 与 U/T 等价输入矩阵见 `data/audit/cross_dataset_overlap.tsv`。\n  同输入、不同 readout 不自动标作标签冲突；跨来源同源性全量比对尚未完成。\n- 冻结的是各单位内的两套 split，**不是已证明全局跨来源训练池无泄露**。\n\n## 单位内重复\n\n'''+md_table(duplicate_rows,['unit_id','actual_n','exact_input_repeated_rows','duplicate_n','input_label_conflict_groups','quarantined_n']))
    splitrows=[]
    for r in reports:
        for name,s in r['split'].items():splitrows.append({'unit_id':r['unit_id'],'protocol':name,'status':s['status'],
            'n_folds':s.get('n_folds'),'n_groups':s.get('n_groups'),'reason':s.get('reason'),
            'leakage':s.get('leakage','NOT_APPLICABLE')})
    (directory/'SPLIT_AUDIT.md').write_text('''# RNA-Gym 独立分折验收\n\n## EAZY\n\n固定 seed `20261028`。独立 observation 身份先随机排序并均衡分折；\n二分类尽可能保留各类支持。10-fold 不可行时降至 5 或 3；不足则明确失败。\nEAZY 允许相关序列及不同条件的相同输入跨折，这是随机对照，不能冒称同源泛化。\n\n## OOD_split\n\nMMseqs2 核酸模式（大型 RMDB 使用 easy-linclust，其余使用 easy-cluster），`min-seq-id=0.8`、双向覆盖度 `0.8`、`k=10`，\n加上 exact input 和可用 gene/transcript/family/结构 component 的传递约束。\nRNA 字母 U/T 等价只用于聚类视图，原始字符串不改变。蛋白输入不当作 RNA 聚类。\n配对数据按任一 RNA 端和可用 gene/miRNA family 约束，巨大连通群不被强拆。\n这是近似搜索的 cluster-disjoint OOD，不是穷尽比对证明的无任何远同源性。\n仅有一个或两个独立群时报告 NOT_FEASIBLE，不伪造十个折。\n\n## 冻结 manifest 与 validation\n\n每个可用 observation 在每套可行协议中有一个 `outer_fold`。外层 test 为 f 时，\nvalidation 为 `(f+1)%k`，其余折为训练；validation 从该轮非 test 的训练池取得。\n10-fold Pilot 仅用 test fold 0/3/7，不改 test membership。\n任何未来 scaler/阈值只能在 train 上拟合；本轮没有拟合任何标准化参数。\n每单位 `split_summary.json` 含 manifest SHA256 和每折样本/标签支持。\n\n## 实际验收结果\n\n'''+md_table(splitrows,['unit_id','protocol','status','n_folds','n_groups','reason','leakage']))
    (directory/'ADMISSION_RECOMMENDATIONS.md').write_text('''# 科学准入建议与明确剩余问题\n\n## 本轮推进与审批边界\n\n技术上已交付真实 QC 数据和独立 split；不再只是登记来源或列出 HOLD。\n但完整科学准入的关键事实尚未满足，不能把新脚本运行成功或文件 QC 通过当作\n完整 SCIENTIFIC_QC_PASS。当前严格计数中 SCIENTIFIC_QC_PASS、\nADMISSION_REVIEW_READY 与 ADMITTED 均保持 0，详见机器表的逐任务 blocker。\n这是证据不足的审计结论，不是因为没有人签字而停止清洗。\n\n## 首批优先补证候选（不是已准入）\n\n1. Saluki human/mouse：两套独立 split 已实际生成；PC1 目标明确，\n   继续核对 compendium/逐记录身份与已发布全局目标预处理的评估含义。\n2. PERSIST paired MRL/half-life：203 构件真实数据；需解决既有源表版本/ULP 差异\n   与实验样本映射，MRL、TE、half-life 严格分离。\n3. Andreasson、Domingo、Kobori RNA 功能 DMS：优先利用本轮取得的一手 Methods；\n   补齐 processed score 的具体变换和方向。单 WT 高同源库的 OOD 往往不可行。\n4. miRBench：完整 pair 数据已整理，但负样本生成、原 assay accession 与\n   miRNA-only shortcut 解释需逐来源完成；Manakov pair 图巨大，不强拆 OOD 群。\n5. RNA3DB：坐标 hash/atom identity 已复用，新的两套 split 已生成；\n   polymer-to-resolved-residue、assembly 与立体化学未验收，不能当作正式结构标签完成。\n\n## 必须隔离的代理轨道\n\n编码蛋白功能 DMS、GO、protein localization、临床/复杂性状变异标签\n不得混入 RNA-specific 主榜。miRNA-only sanity test 是控制任务，不是完整相互作用能力。\n明确 DNA-only 或方法/流程注册行归 EXCLUDED；不扩大解释为所有扩展模态均排除。\n\n## 尚未完成\n\n- 全部源论文 Supplements/官方处理代码逐检查项核验。\n- 各 EukaUTR、RMDB、miRBench 原始实验条件/replicate/readout 版本绑定。\n- NABench 原文件、外部本机缓存的可靠身份绑定；不先安排全量重下载。\n- 跨数据集同源性、原 observation/label 变换匹配与全局 pooled split 隔离。\n- 所有已知权利冲突与源数据重分发链的人工核准。\n- 特殊结构/信号/配体等未绑定输入、未解析的安全格式。\n\n## 全任务建议\n\n'''+md_table(overview,['task_id','admission','technical_qc_pass','split_pass','scientific_qc_pass','admission_review_ready','blocker']))
