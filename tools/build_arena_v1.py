#!/usr/bin/env python3
"""Evidence-driven migration of the existing RNA-Gym project (no downloads).

JSON-compatible YAML is intentional, consistent with the existing config loader.
Historical registries, processed freezes, raw data and admission gates are read-only.
"""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QC = 'rnagym-qc-2026-10-28-v1'
VERSION = 'rnagym-arena-1.0'


def load(path):
    return json.loads(Path(path).read_text())


def table(path):
    path = Path(path)
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f, delimiter='\t' if path.suffix == '.tsv' else ','))


def dump(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def tsv(path, rows, fields=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or list(rows[0])
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fields, delimiter='\t', extrasaction='ignore', lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()


def taxonomy():
    # Explicit user-defined taxonomy, never inferred from historical task names.
    # id|display|macro|registry domain|capability|input|target|type|primary|secondary|role
    definitions = '''SSP|Secondary Structure|Structure|Structure|Secondary Structure|RNA sequence|base-pair relationship / secondary structure|pairwise classification|F1|MCC|CORE
CMP|Contact Map|Structure|Structure|3D Geometry|RNA sequence|spatial contact of nucleotide pairs|pairwise classification|AUPRC|F1|CORE
DMP|Distance Map|Structure|Structure|3D Geometry|RNA sequence|pairwise nucleotide Euclidean distance|pairwise regression|MAE|RMSE|CORE
SSI|icSHAPE Imputation|Structure|Structure|Structure Probing|RNA sequence + partial probing signal + observation mask|missing icSHAPE reactivity|site-level regression|Pearson|Spearman,MAE|CORE
SPL|Splicing|Function|Function & Regulation|RNA Processing|pre-mRNA sequence|donor / acceptor / background|site-level classification|Macro-F1|AUPRC|CORE
APA|Poly(A) Usage|Function|Function & Regulation|RNA Processing|3′UTR / transcript sequence|proximal poly(A) site usage|regression|Spearman|Pearson|CORE
RNA_MODIFICATION|RNA Modification|Function|Function & Regulation|RNA Modification|RNA sequence|RNA modification site/type, chemistry retained|site-level classification|AUPRC|MCC|CORE
NCRNA_FAMILY|ncRNA Family|Function|Function & Regulation|RNA Identity|ncRNA sequence|RNA family|multi-class classification|Macro-F1|MCC|CORE
MRL_EXACT|MRL-exact|Function|Function & Regulation|Translation|genuine 5′UTR sequence|Mean Ribosome Load|regression|Spearman|Pearson|CORE
MRL_PROXY|MRL-proxy|Function|Function & Regulation|Translation|cDNA sequence|MRL-associated translation phenotype|regression|Spearman|Pearson|CORE
RRS|Ribosome Recruitment Score|Function|Function & Regulation|Translation|5′UTR sequence|Ribosome Recruitment Score|regression|Spearman|Pearson|CORE
TE|Translation Efficiency|Function|Function & Regulation|Translation|full transcript / mRNA|Translation Efficiency|regression|Spearman|Pearson|CORE
HALF_LIFE|RNA Half-life|Function|Function & Regulation|Stability|transcript / UTR / full RNA; record actual region|RNA half-life; retain PC1 or transformed labels explicitly|regression|Spearman|Pearson|CORE
FULL_LENGTH_DEGRADATION|Full-length Degradation|Function|Function & Regulation|Stability|full-length RNA|whole-RNA degradation rate / stability|regression|Spearman|MAE|CORE
UTR3_STABILITY|3′UTR Stability|Function|Function & Regulation|Stability|3′UTR|3′UTR-driven stability / degradation phenotype|regression|Spearman|Pearson|CORE
DEGRADATION_SITE|Site-level Degradation|Function|Function & Regulation|Stability|RNA sequence|per-nucleotide degradation / hydrolysis signal|site-level regression|MAE|RMSE|CORE
MRL_HL_PAIR|MRL-HL Pair|Function|Function & Regulation|Translation–Stability Coupling|same RNA sequence|separate MRL and half-life targets|multi-task regression|Joint-normalized|MRL-Spearman,HL-Spearman|CORE
RBP_BINDING|RBP Binding|Function|Function & Regulation|RNA–Protein Interaction|RNA sequence|RBP binding / binding site|classification|AUPRC|AUROC|CORE
RNA_LOC_SR|RNA-Loc-SR|Function|Function & Regulation|Localization|transcript sequence|RNA subcellular localization, short-read assay|multi-label classification|Macro-AUPRC||CORE
RNA_LOC_LR|RNA-Loc-LR|Function|Function & Regulation|Localization|transcript / isoform sequence|RNA subcellular localization, long-read assay|multi-label classification|Macro-AUPRC||CORE
GO_FUNCTION|GO Function|Function|Function & Regulation|Functional Annotation|coding transcript / mRNA|GO terms of encoded protein|multi-label classification|AUPRC|Fmax|SECONDARY_PROXY
PROTEIN_LOCALIZATION|Protein Localization|Function|Function & Regulation|Functional Annotation|coding mRNA|encoded protein localization|multi-label classification|AUPRC||SECONDARY_PROXY
VEP|Variant Effect|Function|Perturbation|Variant Effect|WT / mutant UTR or RNA|functional effect / pathogenicity|ASSAY_SPECIFIC|ASSAY_SPECIFIC|ASSAY_SPECIFIC|CORE
DMS_FITNESS|DMS Fitness|Function|Perturbation|DMS Fitness|WT + mutant sequence|relative functional fitness|regression|Spearman|NDCG|CORE
RNA_SWITCH|RNA Switch|Engineering|Engineering|Synthetic RNA|switch sequence + trigger sequence|toehold / riboswitch activation|ASSAY_SPECIFIC|ASSAY_SPECIFIC|ASSAY_SPECIFIC|CORE
CRISPR_ON_TARGET|CRISPR On-target|Engineering|Engineering|CRISPR|sgRNA + target DNA|editing efficiency|regression|Spearman|Pearson|CORE
CRISPR_OFF_TARGET|CRISPR Off-target|Engineering|Engineering|CRISPR|sgRNA + off-target DNA|off-target activity|ASSAY_SPECIFIC|ASSAY_SPECIFIC|ASSAY_SPECIFIC|CORE
RNA_DESIGN|RNA Design|Engineering|Design|RNA Design|target property / structure / constraints|generated RNA sequence|conditional generation|Success Rate|functional score,structural recovery,novelty,diversity|EXTENDED'''
    tasks = []
    for line in definitions.splitlines():
        tid, name, macro, domain, category, inp, target, problem, primary, secondary, role = line.split('|')
        norm = {'direction': 'lower', 'baseline': 'FROZEN_TRAIN_ONLY_SIMPLE_ERROR', 'optimum': 0} if primary == 'MAE' else {
            'direction': 'higher', 'baseline': 'PER_LABEL_PREVALENCE' if 'AUPRC' in primary else 0, 'upper': 1}
        if primary in ('ASSAY_SPECIFIC', 'Joint-normalized'):
            norm = {'rule': 'freeze assay variant or normalize components separately'}
        tasks.append(dict(task_id=tid, display_name=name, macro_domain=macro,
            level1_domain=domain, level2_category=category,
            input_modality=('rna_dna_pair' if tid.startswith('CRISPR') else
                'sequence_plus_partial_signal' if tid == 'SSI' else
                'conditional_generation' if tid == 'RNA_DESIGN' else
                'sequence_pair' if tid in ('RNA_SWITCH', 'VEP', 'DMS_FITNESS') else 'sequence'),
            input_definition=inp, target_definition=target, problem_type=problem,
            primary_metric=primary, secondary_metrics=secondary.split(',') if secondary else [],
            normalization=norm, difficulty_supported=['D1_STANDARD', 'D2_GENERALIZATION', 'D3_OOD'],
            core_or_extended=role, notes=[]))
    byid = {t['task_id']: t for t in tasks}
    notes = {
        'SSI': ['Imputation only. Sequence-only probing requires a separate future ID.'],
        'MRL_EXACT': ['RRS != MRL != TE', 'MRL: ribosome loading; actual model input is genuine 5′UTR.'],
        'MRL_PROXY': ['RRS != MRL != TE', 'cDNA input is not genuine 5′UTR MRL.'],
        'RRS': ['RRS != MRL != TE', 'Translation initiation / ribosome recruitment.'],
        'TE': ['RRS != MRL != TE', 'Global translation efficiency, not reporter protein output alone.'],
        'HALF_LIFE': ['Record 5′UTR, 3′UTR, transcript or full RNA explicitly; PC1 is not hours.'],
        'RNA_MODIFICATION': ['Never combine chemistries or assays silently.'],
        'MRL_HL_PAIR': ['Separate MRL and half-life normalized scores before joint averaging.'],
        'RBP_BINDING': ['Require RBP, cell line, accession, positive definition and negative construction.'],
        'RNA_LOC_SR': ['SR and LR assay/isoform/compartment definitions are not interchangeable.'],
        'RNA_LOC_LR': ['SR and LR assay/isoform/compartment definitions are not interchangeable.'],
        'GO_FUNCTION': ['INDIRECT_RNA_FUNCTION_TASK=TRUE'],
        'PROTEIN_LOCALIZATION': ['SECONDARY_PROXY_CANDIDATE=TRUE; not RNA localization.'],
        'DMS_FITNESS': ['Separate direct RNA, ribozyme, aptamer, splicing and coding protein phenotypes; coding protein is SECONDARY_PROXY.'],
        'RNA_DESIGN': ['Generation success, not ordinary scalar regression.'],
    }
    for tid, values in notes.items():
        byid[tid]['notes'] = values
    for tid in ('VEP', 'CRISPR_OFF_TARGET', 'RNA_SWITCH'):
        byid[tid]['assay_variants'] = {
            'classification': {'primary_metric': 'AUPRC', 'secondary_metrics': ['AUROC']},
            'regression': {'primary_metric': 'Spearman', 'secondary_metrics': ['Pearson']}}
        byid[tid]['notes'].append('Every dataset freezes exactly one problem type before evaluation.')
    return {'version': VERSION, 'status': 'FROZEN_SPECIFICATION_NOT_DATA_ADMISSION',
        'registry_level1_domains': ['Structure', 'Function & Regulation', 'Perturbation', 'Engineering', 'Design'],
        'tasks': tasks}


def configs(root):
    tax = taxonomy()
    dump(root/'configs/task_taxonomy_v1.yaml', tax)
    categories = defaultdict(set)
    for task in tax['tasks']:
        if task['core_or_extended'] != 'SECONDARY_PROXY':
            categories[task['macro_domain']].add(task['level2_category'])
    scoring = {
        'version': VERSION, 'status': 'FROZEN_PROTOCOL_NO_FORMAL_RESULTS',
        'macro_domain_weights': {m: 1/3 for m in ('Structure', 'Function', 'Engineering')},
        'secondary_proxy_policy': 'retain registry/specialist reference tracks; exclude proxy-only capabilities from RNA-specific core weights',
        'capability_weights': {m: {c: 1/len(cs) for c in sorted(cs)} for m, cs in categories.items()},
        'hierarchy': ['macro_domain', 'level2_category', 'canonical_task_id', 'source_family_id', 'assay_id', 'dataset_version'],
        'aggregation': 'equal at every level; dataset versions within an assay do not add source weight',
        'panel': {'must_freeze_before_results': True, 'absent_tasks_do_not_renormalize_weights': True,
            'formal_requires_human_admission': True, 'exclude_secondary_proxy_from_core': True},
        'normalization': {'higher': 'clip((metric-baseline)/(upper-baseline),0,1)',
            'lower': 'clip(1-error/baseline_error,0,1)',
            'higher_defaults': {'Spearman': [0, 1], 'Pearson': [0, 1], 'MCC': [0, 1],
                'F1': [0, 1], 'Macro-F1': [0, 1], 'AUROC': [0.5, 1], 'Success Rate': [0, 1]},
            'AUPRC': 'per-label positive prevalence; freeze evaluation population and prevalence before model outputs',
            'MAE_RMSE': 'frozen train-only simple baseline error, >0',
            'noise_floor': 'optional pre-frozen metadata; never fitted from model results'},
        'task_weights': {m: {c: {t['task_id']: 1/sum(x['macro_domain'] == m and x['level2_category'] == c for x in tax['tasks']) for t in tax['tasks'] if t['macro_domain'] == m and t['level2_category'] == c} for c in sorted(cs)} for m,cs in categories.items()},
        'primary_metric_only': True,
        'evaluation_statuses': ['EVALUATED', 'UNSUPPORTED', 'NOT_RUN', 'FAILED', 'INCOMPATIBLE', 'REPORTED_ONLY'],
        'missing_value_policy': 'UNSUPPORTED/NOT_RUN/FAILED/INCOMPATIBLE keep raw and normalized NA; REPORTED_ONLY preserves reported raw values outside reproduced score; zero only as coverage penalty',
        'coverage': {'performance': 'sum(w*s)/sum(w) over evaluated cells',
            'coverage': 'sum(w) over evaluated cells', 'universal': 'performance*coverage'},
        'universal_eligibility': {'minimum_coverage': 0.70, 'minimum_capabilities_per_macro_domain': 1},
        'specialist': {'domains': ['Structure', 'Function', 'Engineering'], 'canonical_task_boards': True},
        'joint_task_score': {'MRL_HL_PAIR': {'components': ['MRL', 'Half-life'], 'aggregation': 'mean_of_normalized_components'}},
        'result_sources': ['RNA_GYM_REPRODUCED', 'EXTERNAL_VERIFIED', 'PAPER_REPORTED'],
        'paper_comparability_fields': ['dataset_version', 'test_set_hash', 'split_hash', 'metric', 'input_modality', 'additional_information'],
        'adaptation_tracks': ['zero_shot', 'frozen_ridge', 'frozen_mlp', 'lora', 'full_fine_tuning', 'random_initialization']}
    dump(root/'configs/scoring_protocol_v1.yaml', scoring)
    dump(root/'configs/difficulty_protocol_v1.yaml', {
        'version': VERSION, 'difficulty_cannot_depend_on_model_results': True,
        'levels': {'D1_STANDARD': ['group-aware standard', 'construct/exact-input leakage controls'],
            'D2_GENERALIZATION': ['gene-held-out', 'WT-held-out', 'family-held-out', 'target-held-out', 'transcript-held-out'],
            'D3_OOD': ['assay-held-out', 'cell-line-held-out', 'species-held-out', 'temporal',
                'structure-cluster-held-out', 'ligand-scaffold-held-out', 'independent validation', 'private prospective']},
        'legacy_rules': {'EAZY': 'LEGACY_RANDOM_CONTROL_NOT_AUTOMATIC_D1',
            'OOD_split': 'GROUP_GENERALIZATION_CANDIDATE_NOT_AUTOMATIC_D3',
            'AUTHOR_SPLIT': 'REPRODUCTION_ONLY', 'UTR_LEGACY_10FOLD': 'PRESERVED_NOT_RNAGYM_SPLIT'},
        'folds': [10, 5, 3, 'fixed_holdout'], 'too_few_groups': 'NOT_FEASIBLE; never split a biological group'})
    dump(root/'configs/private_protocol_v1.yaml', {
        'version': VERSION, 'status': 'INFRASTRUCTURE_ONLY_NO_PRIVATE_TEST_CREATED',
        'max_private_submissions_per_team_per_week': 2,
        'qualification': 'at least one server-verified successful Public benchmark; no score or rank threshold',
        'model_version_bound': True, 'submission_hash_required': True,
        'bindings': ['checkpoint_hash', 'code_version', 'adapter_hash', 'prompt_hash', 'protocol_hash'],
        'labels_in_api': False, 'per_sample_errors_in_api': False,
        'storage': 'private evaluation labels outside public/site roots with restricted service permissions',
        'v1': 'Private-Holdout infrastructure', 'v2': 'prospective / temporal experimental validation'})
    return tax


def local_task(category, dataset):
    """Use the actual label category AND input, not historical task names."""
    unit = dataset['unit_id']
    if category in ('seq.mrl.native', 'seq.mrl.log2'):
        if dataset.get('input_type') == '5UTR':
            return 'MRL_EXACT', 'MAPPED', ''
        if unit.startswith('MRNA_'):
            return 'MRL_PROXY', 'MAPPED', 'mature transcript/cDNA input, not isolated 5′UTR'
        return '', 'TAXONOMY_REVIEW_REQUIRED', 'MRL measured; actual input region/cDNA identity unresolved'
    if category.startswith('seq.half_life.'):
        return 'HALF_LIFE', 'MAPPED', 'retain native/log/PC1 label and actual input region'
    if category.startswith('seq.stability.') or category == 'seq.decay.transformed':
        if dataset.get('input_type') == '3UTR' or 'karner' in unit:
            return 'UTR3_STABILITY', 'MAPPED', '3′UTR readout, not whole-RNA half-life'
        return '', 'TAXONOMY_REVIEW_REQUIRED', 'decay/stability input extent unresolved'
    direct = {'seq.apa.usage': 'APA', 'ann.go': 'GO_FUNCTION',
        'ann.protein_location': 'PROTEIN_LOCALIZATION', 'ann.family': 'NCRNA_FAMILY',
        'interaction.rbp_binding': 'RBP_BINDING', 'signal.modification': 'RNA_MODIFICATION',
        'variant.clinical_proxy': 'VEP', 'variant.protein_proxy': 'DMS_FITNESS',
        'variant.ribozyme': 'DMS_FITNESS', 'variant.aptamer': 'DMS_FITNESS',
        'variant.trna': 'DMS_FITNESS', 'variant.splicing': 'DMS_FITNESS',
        'design.inverse2d': 'RNA_DESIGN', 'design.inverse3d': 'RNA_DESIGN'}
    if category in direct:
        return direct[category], 'MAPPED', ''
    if category.startswith('probe.'):
        return '', 'TAXONOMY_REVIEW_REQUIRED', 'sequence-only probing is NOT SSI imputation; no partial-signal protocol'
    if category in ('struct.contact', 'struct.secondary_pair', 'struct.tertiary'):
        return '', 'TAXONOMY_REVIEW_REQUIRED', 'contact/base-pair semantics or coordinate-derived targets not frozen'
    if category == 'seq.te.reporter_proxy':
        return '', 'TAXONOMY_REVIEW_REQUIRED', 'reporter translation_score/fragment input is not proven full-transcript TE'
    return '', 'TAXONOMY_REVIEW_REQUIRED', 'no exact target/input match among 28 tasks'


def datasets(root, tax):
    tasks = {t['task_id']: t for t in tax['tasks']}
    catalog = load(root/'data/registries/fine_task_catalog.json')['datasets']
    stats = {r['unit_id']: r for r in table(root/'data/audit/dataset_statistics.tsv')}
    out, specs = [], {}
    for d in catalog:
        if d['source_collection'] not in ('RNAGYM_QC', 'UTR_LEGACY_102'):
            continue
        unit = d['unit_id']
        evidence = ('data/registries/utr_legacy_102.json' if d['source_collection'] == 'UTR_LEGACY_102'
                    else f'data/processed/{unit}/{QC}/qc_report.json')
        q = load(root/evidence) if d['source_collection'] == 'RNAGYM_QC' else {}
        if q:
            specs[unit] = q
        st = stats.get(unit, {})
        groups = d.get('target_columns_by_category', {})
        for category in d['category_ids']:
            for target in groups.get(category, ['UNRESOLVED']):
                tid, status, reason = local_task(category, d)
                if q.get('modality') == 'regulatory' and 'm6A' in unit:
                    tid, status, reason = 'RNA_MODIFICATION', 'MAPPED', ''
                spec = tasks.get(tid, {})
                problem = q.get('problem_type', 'regression')
                if problem == 'regression_or_multioutput':
                    problem = 'regression'
                if tid in ('GO_FUNCTION', 'PROTEIN_LOCALIZATION'):
                    problem = 'multi-label classification'
                if tid in ('VEP', 'RNA_MODIFICATION'):
                    problem = 'binary_classification'
                if tid == 'NCRNA_FAMILY':
                    problem = 'multi-class classification'
                metric = spec.get('primary_metric', '')
                if metric == 'ASSAY_SPECIFIC':
                    metric = 'AUPRC' if 'classification' in problem else 'Spearman'
                proxy = category in ('ann.go', 'ann.protein_location', 'variant.protein_proxy', 'variant.clinical_proxy', 'variant.growth_proxy')
                input_def = json.dumps({k: ('available_in_local_provenance' if k == 'wild_type' else v) for k,v in q.get('input_schema', {}).items()}, ensure_ascii=False, separators=(',', ':')) if q else d.get('input_type', '')+'; '+d.get('sequence_context', '')
                family = d.get('source_family') or q.get('source_doi')
                if family in (None, '', 'UNKNOWN'):
                    family = 'PROVISIONAL_SOURCE:'+hashlib.sha256(str(q.get('source') or d.get('source_assay_id') or unit).encode()).hexdigest()[:16]
                out.append(dict(dataset_id=d['dataset_id'], dataset_version=QC if q else 'UTR_LEGACY_102_20261019',
                    assay_id=q.get('assay_id') or 'UNVERIFIED_UTR_SOURCE:'+d.get('source_dataset', unit),
                    source_family_id=family, canonical_task_id=tid,
                    macro_domain=spec.get('macro_domain', ''), level1_domain=spec.get('level1_domain', ''),
                    level2_category=spec.get('level2_category', ''), input_definition=input_def,
                    label_definition=target+' :: '+d.get('label_definition', ''), label_unit=d.get('label_unit', 'UNKNOWN'),
                    problem_type=problem, reported_n=q.get('reported_n') or 'UNKNOWN',
                    actual_n=st.get('actual_n', d.get('n_records', '')),
                    qc_valid_n=st.get('valid_n', ''), unique_n=st.get('unique_n', ''),
                    duplicate_n=st.get('duplicate_n', ''), split_protocol=';'.join(d.get('split_protocols', {})),
                    difficulty='', admission_status='SECONDARY_PROXY' if proxy else 'HOLD', evidence_path=evidence,
                    mapping_status=status, mapping_reason=reason, target_column=target,
                    source_category=category, old_task_ids=';'.join(d.get('related_registered_task_ids', [])),
                    scientific_role='SECONDARY_PROXY' if proxy else spec.get('core_or_extended', 'FUTURE_V2_CANDIDATES'),
                    primary_metric=metric, scientific_gaps=';'.join(q.get('scientific_gaps', [])),
                    condition=d.get('condition', ''), source_identity_status='PROVISIONAL_NOT_INDEPENDENCE_PROOF',
                    admission_review_ready=False, formal_admitted=False))
        if unit == 'MRNA_mrl-hl-lbkwk':
            row = dict(out[-1])
            row.update(canonical_task_id='MRL_HL_PAIR', level2_category=tasks['MRL_HL_PAIR']['level2_category'],
                target_column='target_ribosome_load;target_in_cell_half_life',
                label_definition='MRL and half-life separately; joint uses normalized components',
                problem_type='multi-task regression', primary_metric='Joint-normalized', mapping_status='MAPPED')
            out.append(row)
    return out, specs


def old_mapping(root, rows):
    old = table(root/'data/registries/task_baselines_and_admission_198.csv')
    admission = {r['task_id']: r for r in table(root/'data/audit/scientific_admission.tsv')}
    groups = {
        'SSP': [1, 38, 39, 49, 70, 71, 72, 97, 98], 'CMP': [2], 'DMP': [3], 'SSI': [4],
        'SPL': [5, 81, 82], 'APA': [6], 'NCRNA_FAMILY': [7], 'RNA_MODIFICATION': [8],
        'MRL_EXACT': [9], 'DEGRADATION_SITE': [10, 37, 68], 'RNA_SWITCH': [11],
        'CRISPR_ON_TARGET': [12], 'CRISPR_OFF_TARGET': [13], 'DMS_FITNESS': [14, 32, 85, 86, 87, 88, 108],
        'VEP': [18], 'RBP_BINDING': [19, 54, 55, 75, 101], 'HALF_LIFE': [20],
        'MRL_PROXY': [21], 'MRL_HL_PAIR': [22], 'GO_FUNCTION': [23], 'PROTEIN_LOCALIZATION': [24],
        'RNA_LOC_SR': [25], 'RNA_LOC_LR': [26],
        'RNA_DESIGN': [50, 51, 52, 53, 104, 112, 113, 114, 115, 117, 118, 132], 'TE': [120]}
    explicit = {f'T{n:04d}': task for task, ns in groups.items() for n in ns}
    explicit.update({'XMRNA_translation_efficiency_human': 'TE', 'XMRNA_translation_efficiency_mouse': 'TE',
        'XMRNA_rnahl_saluki_mouse': 'HALF_LIFE', 'XMRNA_utr_variants_bohn': 'VEP',
        'XEUKA_01': 'RBP_BINDING', 'XEUKA_02': 'RBP_BINDING', 'XEUKA_03': 'RNA_MODIFICATION', 'XEUKA_04': 'APA'})
    links = defaultdict(list)
    for row in rows:
        for task in row['old_task_ids'].split(';'):
            if task:
                links[task].append(row)
    output = []
    for row in old:
        tid = row['task_id']
        local = links[tid]
        ids = {r['canonical_task_id'] for r in local if r['canonical_task_id']}
        unresolved = any(r['mapping_status'] != 'MAPPED' for r in local)
        declared = explicit.get(tid)
        if tid.startswith('XSCOPE_'):
            declared = 'RBP_BINDING'
        if tid.startswith('XINV_'):
            declared = 'RNA_DESIGN'
        conflict = bool(declared and ids and declared not in ids)
        if not ids and declared:
            ids.add(declared)
        status = 'MAPPED' if ids else 'TAXONOMY_REVIEW_REQUIRED'
        reason = 'Explicit match to user taxonomy. Availability/admission are separate.'
        if local:
            reason = 'Per-unit input/target schemas and local label evidence, not old names.'
        if unresolved or conflict or tid in ('T0017', 'T0069', 'T0089', 'T0090'):
            status = 'TAXONOMY_REVIEW_REQUIRED'
            reason = 'Actual input/label incompletely compatible or row combines unresolved labels.'
        if tid == 'T0017':
            ids.clear()
            reason = 'MRL-MPRA input not schema-bound; do not guess exact versus proxy.'
        if not ids:
            reason += ' No exact canonical assignment; future definition or primary-source review required.'
        if admission.get(tid, {}).get('admission') == 'EXCLUDED':
            ids.clear()
            status = 'EXCLUDED'
            reason = 'Existing audit: non-assay/method-only or DNA-only row.'
        output.append(dict(old_task_id=tid, old_task_name=row['实验任务'], canonical_task_id=';'.join(sorted(ids)),
            mapping_status=status, mapping_confidence='high' if local and status == 'MAPPED' else 'medium' if ids else 'not_assigned',
            reason=reason, manual_review_required=status == 'TAXONOMY_REVIEW_REQUIRED',
            evidence_path=';'.join(sorted({r['evidence_path'] for r in local})) or 'data/registries/task_baselines_and_admission_198.csv',
            multiple_canonical_tasks=len(ids) > 1, input_label_conflict=bool(conflict or unresolved)))
    return output


RESULT_FIELDS = ['model_id', 'model_version', 'parameter_count', 'pretraining_type',
    'result_source', 'adaptation_track', 'task_id', 'dataset_id', 'difficulty', 'raw_metric',
    'raw_score', 'normalized_score', 'evaluation_status', 'coverage', 'compute',
    'checkpoint_hash', 'code_version', 'error_reason', 'evaluation_phase', 'formal_leaderboard_eligible']


def leaderboard_schemas(root):
    # Never truncate existing results on rebuild.
    for scope in ('public', 'private'):
        for board in ('universal', 'structure', 'function', 'engineering', 'task_level'):
            p = root/f'results/leaderboards/{scope}/{board}.tsv'
            if not p.exists():
                tsv(p, [], RESULT_FIELDS)
    p = root/'results/leaderboards/published_reference/paper_reported.tsv'
    if not p.exists():
        tsv(p, [], RESULT_FIELDS + ['paper_doi', 'test_set_hash', 'protocol_matches', 'COMPARABLE_TO_RNAGYM'])
    paths = {}
    schemas = {
        'Task': {'type': 'object', 'required': ['task_id', 'input_definition', 'target_definition', 'primary_metric']},
        'Dataset': {'type': 'object', 'required': ['dataset_id', 'label_definition', 'admission_status']},
        'Model': {'type': 'object', 'required': ['model_id', 'model_version']},
        'Leaderboard': {'type': 'object', 'required': ['scope', 'rows', 'protocol_version']},
        'Submission': {'type': 'object', 'additionalProperties': False,
            'required': ['model_id', 'model_version', 'checkpoint_hash', 'adapter_hash', 'prompt_hash', 'code_version', 'protocol_hash', 'scope'],
            'properties': {k: {'type': 'string'} for k in ['model_id', 'model_version', 'checkpoint_hash',
                'adapter_hash', 'prompt_hash', 'code_version', 'protocol_hash', 'scope']}},
        'SubmissionReceipt': {'type': 'object', 'required': ['id', 'submission_hash', 'status']}}
    definitions = [('/v1/tasks', 'get', 'Task'), ('/v1/tasks/{task_id}', 'get', 'Task'),
        ('/v1/datasets', 'get', 'Dataset'), ('/v1/datasets/{dataset_id}', 'get', 'Dataset'),
        ('/v1/models', 'get', 'Model'), ('/v1/models/{model_id}', 'get', 'Model'),
        ('/v1/leaderboard', 'get', 'Leaderboard'), ('/v1/leaderboard/{domain}', 'get', 'Leaderboard'),
        ('/v1/submissions', 'post', 'SubmissionReceipt'), ('/v1/submissions/{id}', 'get', 'SubmissionReceipt')]
    for name in ('Task', 'Dataset', 'Model'):
        schemas[name+'List'] = {'type': 'object', 'properties': {'items': {'type': 'array', 'items': {'$ref': '#/components/schemas/'+name}}}, 'required': ['items']}
    for path, method, schema in definitions:
        if path in ('/v1/tasks', '/v1/datasets', '/v1/models'):
            schema += 'List'
        op = {'summary': method.upper()+' '+path, 'responses': {'200' if method == 'get' else '202': {
            'description': 'Versioned metadata; no hidden labels or per-sample private errors',
            'content': {'application/json': {'schema': {'$ref': '#/components/schemas/'+schema}}}}},
            'x-runtime-status': 'SCHEMA_ONLY_NOT_DEPLOYED'}
        if '{' in path:
            name = path.split('{')[1].split('}')[0]
            op['parameters'] = [{'name': name, 'in': 'path', 'required': True, 'schema': {'type': 'string'}}]
        if method == 'post':
            op['requestBody'] = {'required': True, 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Submission'}}}}
            op['description'] = 'Team identity comes from authenticated principal, never client body. Qualification and atomic quota checks required.'
        paths.setdefault(path, {})[method] = op
    dump(root/'configs/api_schema_v1.yaml', {'openapi': '3.1.0', 'info': {'title': 'RNA-Gym Arena', 'version': '1.0'},
        'paths': paths, 'components': {'schemas': schemas, 'securitySchemes': {'BearerAuth': {'type': 'http', 'scheme': 'bearer'}}},
        'security': [{'BearerAuth': []}],
        'x-private-labels-exposed': False, 'x-status': 'CONTRACT_ONLY_EXISTING_RUN_API_UNCHANGED'})


def build(root=ROOT):
    tax = configs(root)
    rows, specs = datasets(root, tax)
    for r in rows:
        split = root/'data/splits/RNAGYM_SPLIT_V1'/r['dataset_id'].removeprefix('QC:')/'manifest.json'
        if split.exists():
            r['split_protocol'] += ';RNAGYM_SPLIT_V1'
            r['difficulty'] = load(split)['difficulty']
    mapped = old_mapping(root, rows)
    tsv(root/'data/registries/dataset_task_mapping_v1.tsv', rows)
    tsv(root/'data/audit/taxonomy_mapping_report.tsv', mapped)
    findings = []
    for r in mapped:
        for typ, present in [('TAXONOMY_REVIEW_REQUIRED', r['mapping_status'] == 'TAXONOMY_REVIEW_REQUIRED'),
            ('ONE_TO_MULTIPLE_TASKS', r['multiple_canonical_tasks']), ('INPUT_LABEL_CONFLICT', r['input_label_conflict'])]:
            if present:
                findings.append(dict(finding_type=typ, entity_id=r['old_task_id'],
                    canonical_task_ids=r['canonical_task_id'], finding=r['reason'], evidence_path=r['evidence_path']))
    by_dataset = defaultdict(set)
    for r in rows:
        by_dataset[r['dataset_id']].add(r['target_column'])
    for did, columns in by_dataset.items():
        if len(columns) > 1:
            findings.append(dict(finding_type='MULTIPLE_ACTUAL_LABELS', entity_id=did,
                canonical_task_ids=';'.join(sorted({r['canonical_task_id'] for r in rows if r['dataset_id'] == did and r['canonical_task_id']})),
                finding='Separate label columns: '+';'.join(sorted(columns)), evidence_path='data/registries/dataset_task_mapping_v1.tsv'))
    tsv(root/'data/audit/v1_conflict_findings.tsv', findings)
    # Annotate the EXISTING registry rather than creating a parallel 198-row registry.
    p = root/'data/registries/task_baselines_and_admission_198.csv'
    old = table(p)
    backup = root/'runs/20261030_arena_v1/registry_before_v1.csv'
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        backup.write_bytes(p.read_bytes())
    for r, mapping in zip(old, mapped):
        r.update(canonical_task_ids_v1=mapping['canonical_task_id'], taxonomy_mapping_status_v1=mapping['mapping_status'],
            taxonomy_evidence_v1=mapping['evidence_path'], canonical_mapping_registry='dataset_task_mapping_v1.tsv')
        local = [v for v in rows if r['task_id'] in v['old_task_ids'].split(';')]
        if local:
            r['源数据已下载'] = 'YES_LOCAL_SUBSET'
            r['已有标签是否实测核验'] = 'LOCAL_QC_SCHEMA_VERIFIED_NOT_SCIENTIFIC_ADMISSION'
    with p.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, list(old[0]), lineterminator='\n')
        w.writeheader()
        w.writerows(old)
    leaderboard_schemas(root)
    summary = load(root/'data/audit/scientific_curation_summary.json')
    supported = sorted({r['canonical_task_id'] for r in rows if r['canonical_task_id'] and r['mapping_status'] == 'MAPPED'})
    candidate_core = []
    for tid in supported:
        choices = [r for r in rows if r['canonical_task_id'] == tid and r['mapping_status'] == 'MAPPED'
            and r['scientific_role'] == 'CORE']
        # At most two representative views per task; not all 277 views in the core.
        ids = sorted({r['dataset_id'] for r in choices})[:2]
        candidate_core.extend(dict(task_id=tid, dataset_id=did, status='CANDIDATE_NOT_ADMITTED') for did in ids)
    dump(root/'configs/rnagym_v1_sets.yaml', {'version': VERSION,
        'RNAGYM_V1_CORE_SET': [], 'core_candidates': candidate_core,
        'RNAGYM_V1_EXTENDED': [], 'extended_candidates': [],
        'secondary_proxy_candidates': sorted({r['dataset_id'] for r in rows if r['scientific_role'] == 'SECONDARY_PROXY'}),
        'FUTURE_V2_CANDIDATES': [t['task_id'] for t in tax['tasks'] if t['task_id'] not in supported],
        'note': 'Formal sets remain empty pending scientific review and human admission. Candidate selection is not score-based.'})
    receipt_path = root/'runs/20261030_arena_v1/compute_receipt.json'
    receipt = load(receipt_path) if receipt_path.exists() else {}
    split_paths = list((root/'data/splits/RNAGYM_SPLIT_V1').glob('*/manifest.json')) if (root/'data/splits/RNAGYM_SPLIT_V1').exists() else []
    splits = [load(p) for p in split_paths]
    stats = table(root/'data/audit/dataset_statistics.tsv')
    dup = table(root/'data/audit/duplicate_summary.tsv')
    counts = dict(version=VERSION, date='2026-10-30', registered_rows=len(mapped),
        mapping_status_counts=dict(Counter(r['mapping_status'] for r in mapped)),
        unambiguous_mapped_rows=sum(r['mapping_status'] == 'MAPPED' for r in mapped),
        mapped_canonical_task_families=len({x for r in mapped if r['mapping_status'] == 'MAPPED' for x in r['canonical_task_id'].split(';') if x}),
        local_resources=summary['local_physical_resources'], local_qc_units=len(specs),
        local_utr_views=102, total_local_views=len({r['dataset_id'] for r in rows}),
        label_mapping_rows=len(rows), local_assay_identity_count=len({q['assay_id'] for q in specs.values()}),
        independent_assays='UNKNOWN; canonical/source-context IDs are not experimental-independence proof',
        qc_pass_units=sum(q.get('record_qc_status') == 'PASS' for q in specs.values()),
        qc_valid_observations=sum(int(r['valid_n']) for r in stats),
        qc_actual_observations=sum(int(r['actual_n']) for r in stats),
        qc_unique_observations=sum(int(r['unique_n']) for r in stats),
        exact_repeated_input_rows=sum(int(r['exact_input_repeated_rows']) for r in dup),
        duplicate_observation_aliases=sum(int(r['duplicate_n']) for r in stats),
        cross_dataset_exact_overlap_pairs=summary['overlap']['curated_unit_pairs_with_exact_overlap'],
        cross_dataset_UT_overlap_pairs=summary['overlap']['curated_unit_pairs_with_UT_equivalent_overlap'],
        mirror_pairs=summary['overlap']['exact_archive_mirror_pairs'],
        supported_tasks=supported, no_supported_tasks=[t['task_id'] for t in tax['tasks'] if t['task_id'] not in supported],
        core_admitted_tasks=0, core_candidate_tasks=len({r['task_id'] for r in candidate_core}),
        extended_admitted_tasks=0, extended_candidate_tasks=0, secondary_proxy_candidate_tasks=len({r['canonical_task_id'] for r in rows if r['scientific_role'] == 'SECONDARY_PROXY' and r['canonical_task_id']}),
        completed_split_task_counts={d: len({s['canonical_task_id'] for s in splits if s['difficulty'] == d})
            for d in ('D1_STANDARD', 'D2_GENERALIZATION', 'D3_OOD')},
        completed_split_dataset_count=len(splits), legacy_EAZY_units=summary['units_EAZY_pass'],
        legacy_OOD_feasible_units=summary['units_OOD_split_pass'],
        admission_recommendation_counts=summary['recommendation_counts'], review_ready=0,
        formal_admitted_core=0, formal_admitted_extended=0,
        exploratory_compute=receipt, formal_reproduced_rows=0, paper_reported_rows=0,
        raw_integrity_verified=load(root/'runs/20261030_arena_v1/raw_integrity.json').get('all_pass') if (root/'runs/20261030_arena_v1/raw_integrity.json').exists() else False,
        raw_modified=False, human_approval_created=False)
    dump(root/'data/audit/rnagym_v1_build_summary.json', counts)
    dump(root/'site/data/arena-v1.json', dict(summary=counts, tasks=tax['tasks'], scoring=load(root/'configs/scoring_protocol_v1.yaml'),
        scoring_version=VERSION, results={'formal_reproduced': [], 'paper_reported': []}))
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    return counts


if __name__ == '__main__':
    build()
