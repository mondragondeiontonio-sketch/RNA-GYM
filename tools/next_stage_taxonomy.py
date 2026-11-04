"""Non-destructive Taxonomy V1.1 migration; never changes admission."""
import copy
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"runs/20261102_taxonomy_admission_adaptation_v1"
DOMAINS = ["Structure", "Function & Regulation", "Perturbation", "Engineering & Design"]
CATEGORIES = {
    "Secondary Structure": ["SSP"],
    "3D Geometry": ["CMP", "DMP"],
    "Structure Probing": ["SSI"],
    "RNA Processing & Modification": ["SPL", "APA", "RNA_MODIFICATION"],
    "Translation & Stability": ["MRL_EXACT", "MRL_PROXY", "RRS", "TE", "HALF_LIFE", "FULL_LENGTH_DEGRADATION", "UTR3_STABILITY", "DEGRADATION_SITE", "MRL_HL_PAIR"],
    "RNA Identity & Interactions": ["NCRNA_FAMILY", "RBP_BINDING", "RNA_LOC_SR", "RNA_LOC_LR", "GO_FUNCTION", "PROTEIN_LOCALIZATION"],
    "Variant Effects & Fitness": ["VEP", "DMS_FITNESS"],
    "Engineering & Design": ["RNA_SWITCH", "CRISPR_ON_TARGET", "CRISPR_OFF_TARGET", "RNA_DESIGN"],
}


def read_table(path):
    with Path(path).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter="\t" if str(path).endswith(".tsv") else ","))


def write_json(path, obj):
    path=Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    data=json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+"\n"
    if path.exists():
        if path.read_text() != data: raise ValueError("VERSION_CONFLICT: "+str(path))
    else: path.write_text(data)


def write_tsv(path, rows):
    path=Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    import io
    text=io.StringIO(); writer=csv.DictWriter(text, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader(); writer.writerows(rows)
    if path.exists():
        if path.read_text()!=text.getvalue(): raise ValueError("VERSION_CONFLICT: "+str(path))
    else: path.write_text(text.getvalue())


def build():
    old=json.loads((ROOT/"configs/task_taxonomy_v1.yaml").read_text())
    tax=copy.deepcopy(old); tax.update(version="rnagym-taxonomy-v1.1-20261102", status="ENGINEERING_SPEC_NOT_SCIENTIFIC_ADMISSION", registry_level1_domains=DOMAINS, level2_categories=list(CATEGORIES),
        hierarchy_note="Eight consolidated level-2 categories; all prior finer capabilities retained as legacy_level2_category. Earlier registry had 17 unique level2 labels, not eight. No IDs renumbered.",
        universal_score_enabled=False, human_admitted=False)
    changes=[]
    for t in tax["tasks"]:
        tid=t["task_id"]; before=copy.deepcopy(t)
        t["legacy_level2_category"]=t["level2_category"]
        t["level2_category"]=next(c for c,ids in CATEGORIES.items() if tid in ids)
        if t["level1_domain"] in ["Engineering","Design"]: t["level1_domain"]="Engineering & Design"
        t["macro_domain"]=t["level1_domain"]
        t["input_schema_id"]="rna_sequence_v1"
        t["rna_specific_scope"]="RNA_DIRECT_WITH_ASSAY_EVIDENCE_REQUIRED"
        if tid=="MRL_EXACT":
            t.update(input_definition="5′UTR sequence with experimentally verified insert boundaries", sequence_source_region="5UTR", label_identity="MRL; record original transform and condition; never TE/RRS")
        if tid=="MRL_PROXY":
            t.update(input_definition="cDNA sequence; record actual 5UTR/CDS/3UTR coverage and truncation per record", sequence_source_region="cDNA_COVERAGE_REQUIRED_NOT_AUTOMATIC_CDS", label_identity="MRL proxy; not exact 5UTR MRL, TE or RRS")
        if tid=="HALF_LIFE":
            t.update(label_variants=["absolute_half_life_original_units","published_PC1_dimensionless_SEPARATE_ENDPOINT"], label_identity="PC1 is not hours; no conversion or shared normalization with absolute half-life", aggregation_requires="same_assay_label_variant_units_transform")
        if tid in ["UTR3_STABILITY","FULL_LENGTH_DEGRADATION","DEGRADATION_SITE"]:
            t["label_identity"]="Preserve original decay rate, curve or half-life and direction; no silent ln(2)/k conversion"
        if tid=="MRL_HL_PAIR":
            t.update(output_schema_id="joint_mrl_half_life_v1", source_weight_policy="one joint assay/source weight; component endpoints do not add votes")
        if tid in ["GO_FUNCTION","PROTEIN_LOCALIZATION"]:
            t["rna_specific_scope"]="SECONDARY_PROXY_PROTEIN_CODING_PHENOTYPE_NOT_DIRECT_RNA_FUNCTION"
        if tid=="VEP": t["rna_specific_scope"]="RNA_MECHANISM_REQUIRED_CLINICAL_PROXY_HELD_OUT_OF_CORE"
        if tid=="RBP_BINDING": t["input_schema_id"]="rna_protein_condition_v1"
        if tid.startswith("CRISPR_"): t["input_schema_id"]="guide_target_pam_nuclease_v1"
        if tid=="DMS_FITNESS":
            t.update(input_schema_id="wt_variant_assay_v1", rna_specific_scope="RNA_SUBSTRATE_DIRECT; protein-coding DNA/protein fitness excluded from RNA core")
        changes.append(dict(task_id=tid,old_domain=before["level1_domain"],new_domain=t["level1_domain"],old_category=before["level2_category"],new_category=t["level2_category"],input_schema_id=t["input_schema_id"],notes=t.get("label_identity",t["rna_specific_scope"])))
    tax["input_schemas"]={
        "rna_sequence_v1": {"required":["sequence","sequence_region_coverage"]},
        "rna_protein_condition_v1": {"required":["rna_sequence","protein_id","condition_id"],"optional":["protein_sequence"],"no_implicit_protein_substitution":True},
        "rna_rna_pair_v1": {"required":["sequence_a","sequence_b","pair_orientation","condition_id"],"canonical_task_id":None,"status":"EVIDENCE_HOLD_NO_NEW_ID"},
        "guide_target_pam_nuclease_v1":{"required":["guide_rna","target_sequence","target_alphabet","pam","nuclease","condition_id"]},
        "wt_variant_assay_v1": {"required":["wt_sequence","variant_sequence","mutation_spec","assay_id"]},
        "partial_probing_v1":{"required":["sequence","partial_signal","observed_mask","evaluation_mask"],"disjoint_observation_evaluation_masks":True}}
    next(t for t in tax["tasks"] if t["task_id"]=="SSI")["input_schema_id"]="partial_probing_v1"
    write_json(ROOT/"configs/task_taxonomy_v1_20261102.yaml",tax)
    write_tsv(OUT/"taxonomy_canonical_changes.tsv",changes)
    original={r["task_id"]:r for r in read_table(ROOT/"data/registries/task_baselines_and_admission_198.csv")}
    prior=read_table(ROOT/"data/audit/taxonomy_mapping_report.tsv")
    reviews=read_table(ROOT/"reports/HUMAN_REVIEW_TAXONOMY_2026-10-31.tsv")
    split_ids={"T0014","T0015","T0016","T0017","T0032","T0074","T0102","T0103","T0108","T0109","T0116","XEUKA_05","XEUKA_08","XEUKA_09"}
    method_ids={"T0034","T0065","T0067","T0105","T0123","T0126","T0129","T0133","T0140","T0141"}
    special={
        "T0017":"MRL_EXACT/MRL_PROXY cannot be chosen from a mature-mRNA title; verify cDNA coverage and split six assay labels",
        "T0027":"Stored VL contact labels are not demonstrated secondary base pairs; threshold-selection data not an independent test",
        "T0028":"Stored TS contact labels require base-pair annotation provenance, not 3D distance relabeling",
        "T0029":"TS-Hard needs independent family-holdout evidence and actual base-pair truth",
        "T0030":"RNA pair homology similarity is not single-sequence ncRNA family classification; use separate pair schema",
        "T0031":"RNA type pair similarity requires explicit pair negatives/orientation and homology grouping",
        "T0035":"Sequence-only DMS reactivity is not SSI partial-signal imputation; no compatible frozen canonical ID",
        "T0036":"Sequence-only 2A3/SHAPE reactivity is not SSI; chemistry and signal masks require source evidence",
        "T0045":"Input contains candidate coordinates, unlike sequence-only CMP; incompatible input track",
        "T0046":"Decoy distance-error bins are not observed pairwise distances in DMP",
        "T0062":"miRNA plus target needs independent RNA-RNA pair schema and verified negative construction",
        "T0063":"miRNA-only negative-control label cannot establish RNA-RNA binding without target",
        "T0074":"RNA3DB supports CMP and DMP only after chain/residue alignment; separate targets, shared source weight",
        "T0079":"GFP protein reporter is not direct RNA function; establish RNA substrate mechanism or secondary proxy",
        "T0099":"eCLIP read-start distribution differs from binary RBP binding; preserve observed count target",
        "T0100":"SMI background counts do not establish RBP binding labels",
        "T0103":"Thirteen labels span processing/stability/interaction; bind each source readout separately",
        "T0121":"Clinical/protein-coding variant pathogenicity requires RNA-specific mechanism; no automatic RNA VEP",
        "T0122":"Inter-chain base pairing requires two RNA sequences and pair-index schema, not intrachain SSP",
        "T0138":"Sequence-only probing is not partial-signal SSI; no target conversion",
        "T0139":"Probing-informed folding has extra input versus sequence-only SSP; separate track",
        "XMRNA_mirna_target":"Independent RNA-RNA pair schema and original target/negative provenance required",
        "XMRNA_rna_lifecycle_ietswaart":"Lifecycle compendium combines production, transport and decay; retain original endpoint definitions",
        "XEUKA_05":"Decay rate and half-life must remain distinct original labels, units and directions",
        "XEUKA_08":"Protein, RNA abundance and TE are distinct; split per original readout without renaming to MRL",
        "XEUKA_09":"Viral RNA abundance and MRL are distinct endpoints; verify actual input coverage"}
    result=[]
    for r in reviews:
        tid=r["entity_id"]; src=original[tid]
        status="SPLIT_REQUIRED" if tid in split_ids else "EXCLUDED" if tid in method_ids else "EVIDENCE_HOLD"
        reason=special.get(tid, ("Mixed RNA/protein or multiple input/readout identities must be resolved per assay" if tid in split_ids else "Method/control/metadata/proposed evaluation, not an independently sourced frozen assay endpoint" if tid in method_ids else "No exact frozen task definition with verified primary-source input/label semantics: "+src["实验任务"]))
        result.append(dict(entity_id=tid,old_task_name=src["实验任务"],status=status,canonical_task_ids_proposed=r["canonical_task_ids"],reason=reason,evidence_path="data/audit/taxonomy_mapping_report.tsv#"+tid,source_evidence_status="PRIMARY_ASSAY_REVIEW_NOT_COMPLETE",scientific_admitted=False,human_review_status="NOT_REVIEWED"))
    assert len(result)==76 and len({r["entity_id"] for r in result})==76
    write_tsv(OUT/"taxonomy_review_76.tsv",result)
    byid={r["entity_id"]:r for r in result}
    migrated=[]
    for r in prior:
        status=byid[r["old_task_id"]]["status"] if r["old_task_id"] in byid else r["mapping_status"]
        if status not in ["MAPPED","SPLIT_REQUIRED","EVIDENCE_HOLD","EXCLUDED"]: status="EVIDENCE_HOLD"
        migrated.append(dict(old_task_id=r["old_task_id"],old_task_name=r["old_task_name"],canonical_task_ids=r["canonical_task_id"],status=status,reason=byid.get(r["old_task_id"],{}).get("reason",r["reason"]),scientific_admitted=False))
    write_tsv(ROOT/"data/registries/taxonomy_v1_20261102_crosswalk.tsv",migrated)
    write_json(OUT/"taxonomy_summary.json",dict(canonical_tasks=len(tax["tasks"]),level1=4,level2=8,old_rows=len(migrated),review_rows=len(result),review_counts={s:sum(r["status"]==s for r in result) for s in ["MAPPED","SPLIT_REQUIRED","EVIDENCE_HOLD","EXCLUDED"]},human_admitted=0))
    print(json.loads((OUT/"taxonomy_summary.json").read_text()))

if __name__=="__main__": build()
