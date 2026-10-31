#!/usr/bin/env python3
"""Detailed endpoint taxonomy over existing QC units and read-only UTR sources.

Does not replace the frozen 198-row registry, source assay identities, existing
scores or splits. Dataset/readout references can appear in multiple categories.
"""
import argparse
import collections
import csv
import hashlib
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUTPUT='data/registries/fine_task_catalog.json'
START='<!-- FINE_TASKS:START -->'
END='<!-- FINE_TASKS:END -->'
# Metrics are explicit proposed RNA-Gym reporting contracts, not fabricated
# source-reported metrics or retrospective changes to existing result receipts.
DEFINITIONS=[
 ('seq.mrl.native','序列/翻译','MRL（原尺度）','平均核糖体负载，不等于 TE','r2','spearman,pearson,rmse,mae'),
 ('seq.mrl.log2','序列/翻译','MRL（log₂）','已发布 log₂(MRL)，不重复 log','r2','spearman,pearson,rmse,mae'),
 ('seq.te.measured','序列/翻译','TE（实测定义）','蛋白输出/RNA 或明确的 RPF/RNA 效率，需核实具体定义','r2','spearman,pearson,rmse,mae'),
 ('seq.te.reporter_proxy','序列/翻译','TE/translation reporter score','translation_score 的实验/归一化定义待核，不冒称实测 TE','spearman','r2,pearson,rmse'),
 ('seq.half_life.native','序列/稳定性','半衰期（时间原尺度）','分钟/小时必须按数据版本分别记录','r2','spearman,pearson,rmse,mae'),
 ('seq.half_life.log','序列/稳定性','半衰期（log 尺度）','ln(t/1 min) 与 ln(t/1 h) 分开，不冒称时间值','r2','spearman,pearson,rmse,mae'),
 ('seq.half_life.pc1','序列/稳定性','半衰期共识 PC1','unitless 已发布主成分，不是小时','spearman','r2,pearson,rmse'),
 ('seq.decay.transformed','序列/稳定性','衰减率及其变换','beta/k/log decay/−ln(1+k) 保留各自方向与单位','r2','spearman,pearson,rmse,mae'),
 ('seq.stability.retention','序列/稳定性','RNA retention/stability index','固定时间的保留比例/指数，不等于半衰期','r2','spearman,rmse,mae'),
 ('seq.stability.log_retention','序列/稳定性','RNA log-retention score','时间点 RNA 比值；viral-genome proxy 单独标记','r2','spearman,rmse,mae'),
 ('seq.rna_abundance','序列/表达','RNA abundance/expression','RNA 丰度及既有 log/ln1p 标签，保留其时间/条件','r2','spearman,pearson,rmse,mae'),
 ('seq.reporter.rna_dna','序列/表达','RNA/DNA reporter activity','RNA/DNA 归一化 reporter activity，不等于 TE','r2','spearman,pearson,rmse,mae'),
 ('seq.reporter.protein_com','序列/蛋白输出代理','Protein reporter CoM','流式分箱 center-of-mass，不等于 MRL 或 TE','r2','spearman,pearson,rmse,mae'),
 ('seq.reporter.protein_yfp','序列/蛋白输出代理','Protein/YFP reporter output','归一化蛋白输出，不推断为翻译效率','r2','spearman,pearson,rmse,mae'),
 ('seq.reporter.hp_free','序列/翻译代理','HP_Free fraction','保留原字段含义；实验 pool 定义待核','r2','spearman,rmse,mae'),
 ('seq.apa.usage','序列/加工','APA/isoform usage','近端 poly(A) isoform 比例','r2','spearman,rmse,mae'),
 ('ann.go','功能注释','GO 分子功能多标签','编码产物的 GO 注释，代理轨道','macro_auprc','macro_auroc,macro_f1'),
 ('ann.protein_location','功能注释','Protein localization 多标签','蛋白定位，不是 RNA 定位','macro_auprc','macro_auroc,macro_f1'),
 ('ann.rna_location','RNA 定位','RNA subcellular localization（schema 待核）','分类用 macro F1/AUPRC；比例/富集量用回归指标，先核实标签','unconfirmed',''),
 ('ann.family','家族注释','RNA family/type annotation','原始家族类别；不是已构造的 homology 正负 pair','macro_f1','accuracy'),
 ('ann.mirna_target_pu','相互作用注释','miRNA target presence 多标签','0=列表未检出，不等于实验不结合','macro_auprc','macro_auroc,macro_f1'),
 ('interaction.mirna_site','RNA–RNA','miRNA–target-site binding','有序两端输入与各自负样本来源','auprc','auroc,binary_f1,mcc'),
 ('interaction.rna_rna','RNA–RNA','其他 RNA–RNA interaction/duplex','pair、家族与正负来源需绑定','auprc','auroc,binary_f1,mcc'),
 ('interaction.homology','RNA 同源性','Sequence-pair homology/retrieval','家族 annotation 不能直接当作 pair labels','auroc','auprc,top_k_recall'),
 ('interaction.rbp_binding','RNA–蛋白','RBP/CLIP/eCLIP binding','按 RBP/细胞/窗口定义的结合标签','auprc','auroc,binary_f1,mcc'),
 ('struct.secondary_pair','结构预测','2D base-pair prediction','配对索引、假结和 canonical/noncanonical 范围需固定','pair_f1','mcc,precision,recall'),
 ('struct.contact','结构预测','RNA binary contact graph','保留有向/无向原表示，不默认是 secondary pairing','contact_f1','mcc,precision,recall'),
 ('struct.distance','结构预测','Residue distance/map regression','核苷酸距离或几何数值，不用分类 F1 替代','mae','rmse,r2'),
 ('struct.tertiary','结构预测','3D coordinate prediction','链、残基/缺失坐标 mask 与 assembly 需绑定','lddt','tm_score,rmsd'),
 ('struct.quality','结构评估','Model quality/decoy ranking','候选结构质量/排序，不是新原始实验','spearman','pearson,mae'),
 ('probe.dms','化学探针','DMS reactivity（逐核苷酸）','化学 DMS，不是 deep mutational scanning','pearson','spearman,mae,rmse'),
 ('probe.2a3','化学探针','2A3 reactivity','按实际 modifier=2A3 分组，不默认等于 icSHAPE','pearson','spearman,mae,rmse'),
 ('probe.shape_other','化学探针','SHAPE/icSHAPE/其他 modifier','区分具体试剂与 assay；未绑定 modifier 的登记不冒认 2A3','pearson','spearman,mae,rmse'),
 ('variant.ribozyme','突变效应','Ribozyme RNA activity DMS','RNA 催化/功能活性，按 assay 评测','spearman','pearson,r2'),
 ('variant.trna','突变效应','tRNA fitness DMS','明确 tRNA 原实验表型','spearman','pearson,r2'),
 ('variant.aptamer','突变效应','Aptamer fitness/activity DMS','结合/活性 readout，按 assay 定义','spearman','pearson,r2'),
 ('variant.splicing','突变效应','RNA splicing DMS','RNA 加工表型，不混同编码蛋白功能','spearman','pearson,r2'),
 ('variant.protein_proxy','突变效应代理','Coding-protein phenotype DMS','RNA/DNA 序列编码的蛋白表型，独立代理轨道','spearman','pearson,r2'),
 ('variant.unresolved','突变效应待核','DMS score，RNA 机制待核','CV-only 等未绑定 assay，不能按名称冒认机制','spearman','pearson'),
 ('variant.clinical_proxy','变异注释代理','Clinical/Trait variant annotation','临床/性状分类，不是直接 RNA 实验标签','auprc','auroc,binary_f1,mcc'),
 ('variant.growth_proxy','功能代理','Growth/enrichment score','生长富集表型，不冒称 TE 或 RNA-specific fitness','spearman','r2,pearson'),
 ('ligand.affinity','RNA–配体','Binding affinity Kd/Ki','单位、条件和既有 log 变换必须明确','spearman','mae,rmse'),
 ('ligand.binding','RNA–配体','Binding/native–decoy classification','compound/scaffold、decoy 来源需固定','auprc','auroc,binary_f1,enrichment_factor'),
 ('ligand.docking_proxy','RNA–配体代理','Docking/derived score','计算 docking score，不是实测 affinity','spearman','r2,mae'),
 ('design.inverse2d','RNA 设计','2D inverse folding','目标结构→序列；合法替代序列不因序列不同判错','fold_success','structure_f1,sequence_recovery'),
 ('design.inverse3d','RNA 设计','3D inverse folding','backbone→sequence；结构族分组','sequence_recovery','perplexity,structure_consistency'),
 ('design.conditional','RNA 设计','Conditional RNA generation/editing','条件目标成功率与多样性，非单一回归分数','target_success','diversity,novelty'),
 ('signal.modification','修饰/测序','RNA modification/site detection','window 标签与逐位点/原始 read 不混算','auprc','auroc,binary_f1'),
 ('signal.basecalling','修饰/测序','Direct-RNA signal/basecalling','按 read/molecule 隔离，错误率越低越好','cer','identity_rate'),
 ('method.control','控制/方法','Sanity control / method-only','不计入 RNA-specific 主榜独立数据集','not_applicable',''),
 ('scope.dna_only','范围外','DNA-only task','不进入 RNA-specific 主榜','source_specific',''),
 ('scope.unresolved','待核','输入/目标尚未确认','不凭 benchmark 名称指定正式指标','unconfirmed',''),
]
# Keep rank reporting aligned with the existing sequence-regression protocol.
DEFINITIONS=[tuple(list(x[:4])+['spearman','r2,'+x[5]]) if x[4]=='r2' else x for x in DEFINITIONS]
CATEGORIES={x[0]:{'category_id':x[0],'parent':x[1],'name':x[2],'biological_target':x[3],
    'primary_metric':x[4],'secondary_metrics':list(dict.fromkeys(m for m in x[5].split(',') if m and m!=x[4])),
    'metric_status':'PROPOSED_REPORTING_CONTRACT_NOT_FORMAL_ADMISSION'} for x in DEFINITIONS}
UTR_FAMILY={
 'castillo':'seq.mrl.native','sample':'seq.mrl.native','danio':'seq.mrl.log2',
 'geisberg':'seq.half_life.native','rabani':'seq.half_life.log','su':'seq.half_life.log',
 'david':'seq.stability.retention','virus197':'seq.stability.log_retention',
 'maputr':'seq.reporter.rna_dna','sabeti':'seq.reporter.rna_dna',
 'com':'seq.reporter.protein_com','yeast_leaders':'seq.reporter.protein_yfp',
 'penta':'seq.rna_abundance','tria':'seq.decay.transformed','yeast_random':'variant.growth_proxy'}


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+'\n')


def tsv(path,rows):
    if not rows:return
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w') as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter='\t',lineterminator='\n');w.writeheader()
        for r in rows:w.writerow({k:json.dumps(v,ensure_ascii=False,sort_keys=True) if isinstance(v,(dict,list)) else v for k,v in r.items()})


def classify_curated(r):
    """Explicit released target schemas and reviewed source-context bindings."""
    unit=r['unit_id'];mod=r['modality'];targets=r['target_schema']
    if mod=='dms':
        if r.get('proxy'):return {'variant.protein_proxy':list(targets)}
        kind=r.get('rna_type','').lower()
        cat={'ribozyme':'variant.ribozyme','trna':'variant.trna','aptamer':'variant.aptamer',
             'mrna-splicing':'variant.splicing'}.get(kind,'variant.unresolved')
        return {cat:list(targets)}
    if mod=='paired':return {'interaction.mirna_site':list(targets)}
    if mod=='probing':return {'probe.dms':['reactivity:modifier=DMS'],'probe.2a3':['reactivity:modifier=2A3']}
    if mod=='structure3d':return {'struct.tertiary':['coordinates']}
    if mod=='structure2d':return {'struct.contact':['contact']}
    if mod=='annotation_family':return {'ann.family':['family']}
    pkg=r['package_group_id']
    if pkg=='MRNA_GO_MF':return {'ann.go':['target[20]']}
    if pkg=='MRNA_PROTEIN_LOCALIZATION':return {'ann.protein_location':['target[12]']}
    if pkg=='MRNA_MIRNA_TARGET':return {'ann.mirna_target_pu':list(targets)}
    if pkg in ('MRNA_UTR_VARIANTS_BOHN','MRNA_VEP_TRAITGYM_MRNA'):return {'variant.clinical_proxy':list(targets)}
    if pkg.startswith('MRNA_RNAHL_SALUKI_'):return {'seq.half_life.pc1':list(targets)}
    if pkg=='MRNA_MRL_SUGIMOTO':return {'seq.mrl.native':['target']}
    if pkg=='MRNA_MRL_HL_LBKWK':return {'seq.mrl.native':['target_ribosome_load'],'seq.half_life.native':['target_in_cell_half_life']}
    if pkg=='EUKAUTR':
        # Conditions and units are source-specific. These classify the released
        # target columns without claiming missing original-assay semantics.
        source=r['source']
        if '/APA_Isoform' in source:return {'seq.apa.usage':list(targets)}
        if '/RNA_protein_interaction/' in source:return {'interaction.rbp_binding':list(targets)}
        if '/m6A_modification/' in source:return {'signal.modification':list(targets)}
        if '/Rabani_degradation_rate/' in source:
            return {'seq.decay.transformed':[x for x in targets if x=='beta'],
                    'seq.half_life.native':[x for x in targets if x=='half_life'],
                    'seq.half_life.log':[x for x in targets if x=='log_half_life']}
        if '/Zhao_half-life' in source:return {'seq.half_life.native':list(targets)}
        if '/karner_decay_rate/' in source:return {'seq.decay.transformed':list(targets)}
        if '/seo_viromics' in source:return {'seq.rna_abundance':['RNA_logFC'],'seq.mrl.native':['MRL'],'seq.reporter.hp_free':['HP_Free']}
        if '/west_2025/' in source:
            if '/protein_score/' in source:return {'seq.reporter.protein_yfp':['label']}
            if '/rna_abundance/' in source:return {'seq.rna_abundance':['label']}
            if '/translation_score/' in source:return {'seq.te.reporter_proxy':['label']}
    raise ValueError('UNCLASSIFIED_CURATED_SCHEMA:'+unit)


def registered_categories(row):
    """Registry-description association only; never proof of acquired labels."""
    tid=row['row_id'];tax=row['output_taxonomy'];s=(row['task']+' '+row['dataset']+' '+row['scoring_family']).lower()
    if row['package_group_id']=='METHODOLOGY_ONLY' or tid in ('T0033','T0063','T0106','T0107'):
        return ['method.control']
    if row['search_dedup_decision'].startswith('EXCLUDE_DNA'):return ['scope.dna_only']
    explicit={'T0022':['seq.mrl.native','seq.half_life.native'],
      'T0020':['seq.half_life.pc1'],'XMRNA_rnahl_saluki_mouse':['seq.half_life.pc1'],
      'XMRNA_mirna_target':['ann.mirna_target_pu'],'T0023':['ann.go'],'T0024':['ann.protein_location'],
      'T0018':['variant.clinical_proxy'],'XMRNA_utr_variants_bohn':['variant.clinical_proxy'],
      'XMRNA_translation_efficiency_human':['seq.te.measured'],'XMRNA_translation_efficiency_mouse':['seq.te.measured'],
      'T0030':['interaction.homology'],'T0031':['interaction.homology'],
      'T0027':['struct.contact'],'T0028':['struct.contact'],'T0029':['struct.contact'],
      'T0035':['probe.dms'],'T0036':['probe.2a3'],'T0062':['interaction.mirna_site'],
      'XEUKA_04':['seq.apa.usage'],'XEUKA_05':['seq.half_life.log','seq.decay.transformed'],
      'XEUKA_06':['seq.half_life.native'],'XEUKA_07':['seq.decay.transformed'],
      'XEUKA_08':['seq.reporter.protein_yfp','seq.rna_abundance','seq.te.reporter_proxy'],
      'XEUKA_09':['seq.rna_abundance','seq.mrl.native','seq.reporter.hp_free']}
    if tid in explicit:return explicit[tid]
    if 'MRNA_MRL' in row['package_group_id'] or re.search(r'\bmrl\b|核糖体负载',s):return ['seq.mrl.native']
    if 'TRANSLATION_EFFICIENCY' in tax or re.search(r'(^|_)TE($|_)',tax) or 'translation-efficiency' in s or '翻译效率' in s:return ['seq.te.measured']
    if 'half-life' in s or 'half_life' in s or '半衰期' in s:return ['seq.half_life.native']
    if 'riboz' in s:return ['variant.ribozyme']
    if 'trna fitness' in s:return ['variant.trna']
    if 'aptamer fitness' in s:return ['variant.aptamer']
    if 'fitness' in s or 'dms' in s and 'chemical' not in s:return ['variant.unresolved']
    if 'protein localization' in s:return ['ann.protein_location']
    if 'rna-loc' in s or 'rna 定位' in s:return ['ann.rna_location']
    if 'go' in tax.lower() and 'annotation' in tax.lower():return ['ann.go']
    if 'eclip' in s or 'clip' in s or 'rbp' in s or 'RNA_PROTEIN' in tax:return ['interaction.rbp_binding']
    if 'modification' in s or 'm6a' in s or '甲基' in s or '位点检测' in s:return ['signal.modification']
    if 'nanopore' in s or 'signal' in tax.lower() or 'current' in s:return ['signal.basecalling']
    if 'kd' in s or 'affinity' in s or 'ki ' in s:return ['ligand.affinity']
    if 'dock' in s:return ['ligand.docking_proxy']
    if 'ligand' in s or 'smiles' in s or '小分子' in s:return ['ligand.binding']
    if 'inverse' in s or 'backbone→' in s or 'backbone' in s and '序列' in s:
        return ['design.inverse3d'] if '3d' in s or 'backbone' in s else ['design.inverse2d']
    if '序列生成' in s or 'joint' in s or 'co-design' in s:return ['design.conditional']
    if 'rna–rna' in s or 'rna-rna' in s or 'duplex' in s or 'rri' in s or 'rnarna' in s:return ['interaction.rna_rna']
    if 'miRNA' in tax or 'mirna' in s:return ['interaction.mirna_site']
    if 'distance' in s or '距离' in s:return ['struct.distance']
    if 'quality' in s or 'lddt' in s or 'decoy' in s:return ['struct.quality']
    if 'reactivity' in s or 'chemical probing' in s or 'icshape' in s or 'shape' in s or '反应性' in s:return ['probe.shape_other']
    if '3d' in tax.lower() or '3d' in s or '三级结构' in s:return ['struct.tertiary']
    if 'structure_2d' in tax.lower() or '二级结构' in s or '2d' in s or 'bprna' in s:return ['struct.secondary_pair']
    return ['scope.unresolved']


def build(root=ROOT):
    root=Path(root);datasets=[];edges=[]
    with (root/'data/registries/search_level_task_crosswalk_198.csv').open(encoding='utf-8-sig') as handle:
        registry=list(csv.DictReader(handle))
    taskmap={r['row_id']:set(registered_categories(r)) for r in registry}
    for p in sorted((root/'data/processed').glob('*/rnagym-qc-2026-10-28-v1/qc_report.json')):
        if not (p.parent/'complete.json').exists():continue
        r=json.loads(p.read_text());cats={k:v for k,v in classify_curated(r).items() if v}
        for tid in r['task_ids']:
            if tid not in ('T0033','T0063'):taskmap[tid].update(cats)
        ds={'dataset_id':'QC:'+r['unit_id'],'source_collection':'RNAGYM_QC','unit_id':r['unit_id'],
            'category_ids':sorted(cats),'target_columns_by_category':cats,'n_records':r['valid_n'],
            'input_type':r['modality'],'label_definition':r['label_definition'],'label_unit':r['label_unit'],
            'source_metrics_at_snapshot':r['metric'],
            'metric_origin':'PRIOR_RNAGYM_QC_PROPOSAL_NOT_ORIGINAL_PAPER_OR_MEASURED_SCORE','split_protocols':{k:{a:v.get(a) for a in ('status','n_folds','n_groups')} for k,v in r['split'].items()},
            'source_assay_id':r['assay_id'],'experimental_independence_verified':False,
            'curated_sha256':r['output_sha256'],'related_registered_task_ids':r['task_ids'],
            'formal_admitted':False,'local_data_binding':'CHECKOUT_PROCESSED_CANDIDATE',
            'metadata_limitations':'Apply modality_findings.tsv errata; record QC is not scientific admission'}
        datasets.append(ds)
    utr=json.loads((root/'data/registries/utr_legacy_102.json').read_text())
    for item in utr['datasets']:
        r=item['row'];cat=UTR_FAMILY[r['family']]
        datasets.append({'dataset_id':item['dataset_id'],'source_collection':'UTR_LEGACY_102',
            'unit_id':item['dataset'],'category_ids':[cat],'target_columns_by_category':{cat:['raw_label']},
            'n_records':(item['profile'] or {}).get('n'), 'input_type':r['region'],
            'source_family':r['family'],'condition':r['condition'],'library_set':r['library_set'],
            'label_definition':r['raw_label_formula'],'label_unit':r['raw_label_unit'],
            'sequence_context':r['sequence_context'],'source_dataset':r['source_dataset'],
            'source_metrics_at_snapshot':item['source_reported_metrics'],
            'metric_origin':'LEGACY_UTR_ML_CODE_STATIC_AST_NOT_NEW_MODEL_EVALUATION',
            'source_primary_metric_declared':False,'formal_admitted':False,
            'local_data_binding':'BOUND_EXTERNAL_READ_ONLY' if item['local_verified'] else 'EXTERNAL_BINDING_GAP',
            'split_protocols':{'UTR_LEGACY_10FOLD':{'status':'PRESERVED_NOT_NEW_RNAGYM_SPLIT','n_folds':10}},
            'experimental_independence_verified':False,'related_registered_task_ids':[],
            'cross_source_identity':'NOT_SAMPLE_LEVEL_EQUIVALENCE_CERTIFIED; do not weight as a new independent assay'})
    revised=json.loads((root/'data/registries/utr_revised_87_metadata.json').read_text())
    metadata_counts=collections.Counter(UTR_FAMILY[r['family']] for r in revised['datasets'])
    # Public checkouts do not ship raw/processed records. A content-bound,
    # sanitized source projection keeps metadata/README verification offline.
    snapshot=root/'data/registries/curated_endpoint_units.json'
    local_qc={r['dataset_id']:r for r in datasets if r['source_collection']=='RNAGYM_QC'}
    if snapshot.exists():
        frozen={r['dataset_id']:r for r in json.loads(snapshot.read_text())['datasets']}
        frozen.update(local_qc)
        datasets=[frozen[k] for k in sorted(frozen)]+[r for r in datasets if r['source_collection']!='RNAGYM_QC']
        for r in frozen.values():
            for tid in r['related_registered_task_ids']:
                if tid not in ('T0033','T0063'):taskmap[tid].update(r['category_ids'])
    for row in registry:
        for cat in sorted(taskmap[row['row_id']]):
            if cat not in CATEGORIES:raise ValueError('UNKNOWN_CATEGORY:'+cat)
            edges.append({'task_id':row['row_id'],'category_id':cat,'source_declared_metric':row['evaluation_metric'],
                'scope':'REGISTERED_DESCRIPTION_OR_AVAILABLE_SUBSET_ASSOCIATION_NOT_FULL_SOURCE_VALIDATION'})
    categories=[]
    for cat,definition in CATEGORIES.items():
        local=[r for r in datasets if cat in r['category_ids']]
        qc=[r for r in local if r['source_collection']=='RNAGYM_QC'];old=[r for r in local if r['source_collection']=='UTR_LEGACY_102']
        categories.append({**definition,'rnagym_qc_dataset_units':len(qc),'utr_local_dataset_views':len(old),
            'utr_revised_metadata_views':metadata_counts[cat],
            'registered_task_references':sum(e['category_id']==cat for e in edges),
            'dataset_ids':[r['dataset_id'] for r in local],
            'dataset_count_scope':'unique data/readout-condition views within category, NOT independent experiments; multi-category dataset references overlap'})
    value={'schema':'rna_gym.fine_endpoint_taxonomy.v1','categories':categories,'datasets':datasets,
        'registered_task_category_relations':edges,
        'summary':{'original_registered_task_rows':len(registry),'tasks_covered':len(taskmap),
            'fine_categories':len(categories),'rnagym_qc_units':sum(r['source_collection']=='RNAGYM_QC' for r in datasets),
            'utr_local_views':sum(r['source_collection']=='UTR_LEGACY_102' for r in datasets),
            'utr_revised_metadata_only_views':len(revised['datasets']),
            'combined_data_views':len(datasets),
            'utr_cv_records':sum(r['n_records'] or 0 for r in datasets if r['source_collection']=='UTR_LEGACY_102'),
            'utr_verified_local_views':sum(r['local_data_binding']=='BOUND_EXTERNAL_READ_ONLY' for r in datasets),
            'globally_independent_datasets':'UNKNOWN_NOT_SUMMED',
            'formal_admitted':0,'training_started_this_task':False},
        'metric_rules':{'status':'PROPOSED_ENDPOINT_CONTRACT; preserve historical source metrics separately',
            'r2':'1 - sum((y-yhat)^2)/sum((y-mean(y))^2); may be negative; NOT Pearson squared',
            'spearman':'rank correlation; constant targets/predictions yield undefined, not zero',
            'f1':'binary/macro/pair F1 distinguished; thresholds chosen on validation only',
            'aggregation':'report per assay/readout, condition and target scale; no pooling different fold z-score scales as raw units',
            'no_new_scores':True}}
    return value


def table(rows,fields):
    def clean(x):return str(x).replace('|',' / ').replace('\n',' ')
    return '| '+' | '.join(fields)+' |\n|'+ '|'.join(['---']*len(fields))+'|\n'+''.join('| '+' | '.join(clean(r.get(f,'')) for f in fields)+' |\n' for r in rows)


def pretty_metric(name):
    return {'spearman':'Spearman ρ','r2':'R²','pearson':'Pearson r','rmse':'RMSE','mae':'MAE',
        'auprc':'AUPRC','auroc':'AUROC','macro_auprc':'macro-AUPRC','macro_auroc':'macro-AUROC',
        'binary_f1':'binary F1','macro_f1':'macro F1','pair_f1':'pair F1','contact_f1':'contact F1',
        'mcc':'MCC','lddt':'lDDT','tm_score':'TM-score','rmsd':'RMSD',
        'unconfirmed':'待 schema 核实','not_applicable':'不适用','source_specific':'依源协议确认',
        'fold_success':'folding success','sequence_recovery':'sequence recovery','cer':'CER'}.get(name,name)


def render(value,root=ROOT):
    counts=value['summary'];rows=[]
    for c in value['categories']:
        rows.append({'类别':c['parent']+' / '+c['name'],'RNA-Gym QC 单元':c['rnagym_qc_dataset_units'],
            'UTR 本地视图':c['utr_local_dataset_views'],'87 修订目录（元数据）':c['utr_revised_metadata_views'],
            '198 登记引用':c['registered_task_references'],'主指标':pretty_metric(c['primary_metric']),
            '次指标':', '.join(pretty_metric(x) for x in c['secondary_metrics']) or '—'})
    old=[r for r in value['datasets'] if r['source_collection']=='UTR_LEGACY_102']
    family=[]
    for name in sorted(UTR_FAMILY):
        ds=[r for r in old if r['source_family']==name]
        cat=CATEGORIES[UTR_FAMILY[name]]
        family.append({'来源家族':name,'本地数据集视图':len(ds),'细分类':cat['name'],
            'label 单位/尺度':' / '.join(sorted({r['label_unit'] for r in ds})) or '—',
            '主指标':pretty_metric(cat['primary_metric']),'次指标':', '.join(pretty_metric(x) for x in cat['secondary_metrics'])})
    history=json.loads((Path(root)/'data/registries/utr_historical_result_status.json').read_text())
    text=f'''{START}

<a id="fine-tasks"></a>

## 细粒度任务、数据集数量与评价指标

本表按 **{counts['fine_categories']} 个生物学 readout 细分类** 划分，不把 MRL、TE、半衰期、RNA/DNA activity、
蛋白 reporter output 混为“序列回归”。原 198 行与上面的 10 个工作分块保持不变。

- 原有本地 QC：**{counts['rnagym_qc_units']} 个 source-context/readout 数据单元**。
- UTR_bench 本地接入：**{counts['utr_local_views']} 个 dataset/readout-condition 视图**，
  继承 1,020 个十折文件；它们不是 1,020 个数据集，也不新增 102 个已批准 assay。
- 两者合计 **{counts['combined_data_views']} 个数据视图**；不是已完成跨来源去重的独立实验数。
- UTR 的另一份 **87 项修订目录**只接入元数据，不再加到 102 上：
  它包含 81 个 existing handles 和 6 个补充视图；与本地 102 目录相比，不含 21 个 CoM 视图。
  这是目录差异，不是已证明的直接版本迁移；相同家族/handle 不代表文件或标签版本相同。
- 同一多输出数据单元可在多个 readout 类别出现；“198 登记引用”也是多对多引用，
  **各分类行不能直接相加当作独立数据集/实验数**。0 表示该口径下尚无数据，不能凭名称补数。

### 各细分类的数量与指标

“主指标”是本轮明确写出的 **RNA-Gym 建议报告协议**，不是伪造的原论文主指标、
不是已运行分数，也不修改旧训练 receipt。机器清单的 `source_metrics_at_snapshot`
保留相应来源元信息，`metric_origin` 明确区分旧 RNA-Gym QC 建议与 UTR 代码实际输出，
不能将两者一概叫作原论文指标或已算出的分数；198 登记声称的指标也单独保留。
未确认输入/标签的登记仍需源证据核实。
表中“原尺度”指当前发布文件的数值尺度，不等于原始实验 reads 或原始仪器量；
单位/变换尚未证实的 QC 单元仍保留其 `UNRESOLVED_SOURCE_SCALE`，不得冒称已核实的小时值。

'''+table(rows,['类别','RNA-Gym QC 单元','UTR 本地视图','87 修订目录（元数据）','198 登记引用','主指标','次指标'])+'''
### 指标的含义与汇总边界

- **R²**：`1 − Σ(y−ŷ)² / Σ(y−ȳ)²`，允许负值，**不是 Pearson r 的平方**。
  定量回归在该版本已声明的 label 尺度上报告，不能混合小时、分钟、log 或 PC1。
- **Spearman ρ**：排序相关性；DMS 和无量纲共识分数优先看排序。
  常数标签/预测导致的未定义值记录 NA，不补成 0；R² 的零方差与 AUROC 的单类情况也需报告 NA。
- **F1**：区分 binary F1、macro-F1、base-pair F1 与 contact F1；阈值只由 validation
  决定。严重不平衡的结合/修饰任务以 AUPRC 为建议主指标，同时报 AUROC/F1/MCC。
- **逐核苷酸 probing**：按序列、modifier 与有效位置 mask 分别算 Pearson/MAE 等；
  化学 DMS 不等于 deep mutational scanning，不混用两个术语的标签。
- R²、相关系数、AUC 与 F1 通常越高越好；MSE/MAE/RMSE/RMSD/CER 越低越好。
- **结构和生成任务**不能统一用 R²/F1：3D 用 lDDT/TM-score/RMSD，
  inverse folding 用结构成功率或 sequence recovery，并保留具体协议条件。
- 先按 assay/readout/条件给分数；不能按样本量把镜像、多个 CV 版本或多个 readout
  重复加权。跨折 z-score 预测不能直接拼成 raw-unit pooled 指标。

### UTR_bench 已接入的 102 个本地视图

本地目录包含 **61 个 3′UTR 文件夹视图、41 个 5′UTR 文件夹视图**，
合计 **__UTR_CV_N__ 条 CV 记录（按任务视图计数）**，不是十折展开后的重复行数。

继承数据的 `sequence / raw_label / zscore_label / set / fold` 五列，不改 raw label、
不再次 log、不重新拟合 z-score，也不覆盖原 train/val/test。原 protected 数据继续排除。
这些 split 名为 `UTR_LEGACY_10FOLD`，**不冒充本项目新建的 EAZY 或 OOD_split**。
既有 RNA-Gym 数据仍有独立 EAZY/OOD；旧 UTR 数据的新 OOD 尚未构造。

'''+table(family,['来源家族','本地数据集视图','细分类','label 单位/尺度','主指标','次指标'])+'''
**关键区分：**本地 UTR 包有 12 个 MRL 视图，但没有经该清单确认的独立实测 TE 视图。
RNA/DNA activity、protein CoM、YFP 与 growth score 不会为了填充 TE 类别而改名。
旧 Geisberg 102 包使用 **min**，87 修订元数据写为 **h**；两版本不换算、不合并、不互用结果。
旧目录中的 viral-genome proxy 保留该输入限定，不能仅凭 `3UTR/` 文件夹名冒称精确 3′UTR。

<details>
<summary>展开：102 个本地 UTR 数据视图的细分类与主指标</summary>

'''+table([{'数据集 ID':r['unit_id'],'类别':CATEGORIES[r['category_ids'][0]]['name'],
            '条件':r['condition'],'N（当前本地）':r['n_records'],'label 单位':r['label_unit'],
            '主指标':pretty_metric(CATEGORIES[r['category_ids'][0]]['primary_metric'])} for r in old],
            ['数据集 ID','类别','条件','N（当前本地）','label 单位','主指标'])+f'''
</details>

### 旧 UTR 评测结果究竟报告什么

本地旧 102 包 ML 代码实际计算 **Spearman、MSE、MAE**，完整十折才汇总 raw-unit OOF；
Selected12 迁移结果另有 **Spearman、Pearson、MSE、RMSE、MAE、R²** 六项，
不能把后一套字段冒称旧 102 包已全部计算。
这不意味着旧实验曾声明本表的新建议主指标。Selected12 迁移矩阵实际有
**{history.get('matrix_rows','UNKNOWN')} 个 model×dataset×head 记录**、
**{history.get('unique_datasets','UNKNOWN')} 个数据集**，记录的是 fold-mean 指标及其 label 尺度。
其中 **{history.get('full_fold_metric_rows','UNKNOWN')} 条 Full fold 指标**均是既有结果，
Selected12 的 **{history.get('selected12_fold_files_bound_to_legacy102','UNKNOWN')} 个源 fold 文件 SHA256**
匹配本轮接入的旧 102 包，而不是 87 项修订目录。96 个矩阵记录均为 `zscore_label` 尺度。
该矩阵的 `reporting_status` 为 `RAW_INVERSE_PENDING`，raw pooled 分数为空；
**这些是旧项目的非主榜中间结果，不是新 RNA-Gym 正式分数**。本轮没有训练、重算或换算这些分数。

### 查询与复用

```python
from rna_gym import DatasetHub

hub = DatasetHub()
hub.categories()                          # 每类数量、主指标、次指标
hub.dataset_views(category="seq.mrl.native")
hub.dataset_views(source="UTR_LEGACY_102")

# 仅在已绑定本地 UTR 数据的环境可读；fresh clone 不自动下载数据。
data = hub.utr("UTR102:5UTR/102_yeast_random_BY4741_NOT_APPLICABLE_OR_UNKNOWN")
data.preview(fold=0, rows=3)
for row in data.iter_fold(fold=0, split="test"):
    break  # 保留原始标签与既有划分；读取不是科学准入或训练授权。
```

机器入口：
[fine taxonomy](data/registries/fine_task_catalog.json)、
[UTR 本地 102 清单](data/registries/utr_legacy_102.json)、
[UTR 87 版本元数据](data/registries/utr_revised_87_metadata.json)、
[旧结果状态](data/registries/utr_historical_result_status.json)。
原 198 行、175 个 QC 数据版本、已有 split、标签、正式 gate 和人工审批均未改写。

{END}'''
    return text.replace('__UTR_CV_N__',format(counts['utr_cv_records'],','))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--verify',action='store_true');args=p.parse_args()
    value=build();expected=json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+'\n'
    readme=ROOT/'README.md';text=readme.read_text();section=render(value)
    if START in text:
        current=text[text.index(START):text.index(END)+len(END)]
        updated=text.replace(current,section)
    else:
        marker='## Existing splits · 现有划分与复用准入'
        updated=text.replace(marker,section+'\n\n'+marker,1)
    if args.verify:
        if (ROOT/OUTPUT).read_text()!=expected or updated!=text:raise SystemExit('STALE_FINE_TAXONOMY_OR_README')
    else:
        write(ROOT/OUTPUT,value);readme.write_text(updated)
        write(ROOT/'data/registries/curated_endpoint_units.json',{'scope':'SANITIZED_LOCAL_QC_ENDPOINT_SNAPSHOT_NOT_RAW_DATA',
            'datasets':[r for r in value['datasets'] if r['source_collection']=='RNAGYM_QC']})
        tsv(ROOT/'data/registries/fine_task_category_mapping.tsv',value['registered_task_category_relations'])
    print(json.dumps(value['summary'],ensure_ascii=False,indent=2))

if __name__=='__main__':main()
