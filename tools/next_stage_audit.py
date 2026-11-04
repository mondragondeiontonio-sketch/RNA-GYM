"""Priority assay identity/label/leakage audit. Engineering evidence is NOT admission."""
from collections import Counter, defaultdict
import csv
import hashlib
import io
import itertools
import json
from pathlib import Path
import re
import zipfile
import numpy as np
import pyarrow.parquet as pq
from tools.next_stage_taxonomy import ROOT, OUT, read_table, write_json, write_tsv

QC="rnagym-qc-2026-10-28-v1"
PILOT=ROOT/"runs/rnagym_rnafm_hf_pilot_v1_2"


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def source_replay(unit,d,curated,prov,destination):
    proof=dict(mode="NOT_REPLAYED_FROM_ORIGINAL_EXPERIMENT",original_experiment_row_mapping="UNVERIFIED")
    spec=prov["specification"]
    if unit.startswith("DMS_"):
        src=prov["inputs"][0]; path=ROOT/src["path"]
        if sha(path)!=src["sha256"]: raise ValueError("SOURCE_HASH_MISMATCH")
        with zipfile.ZipFile(path) as z: original=list(csv.DictReader(io.StringIO(z.read(src["member"]).decode("utf-8-sig"))))
        wt=spec["input_schema"]["wild_type"].replace("T","U"); replay=[]
        for row in curated:
            x=original[int(row["source_row"])-1]; seq=x["sequence"]
            same=seq==row["sequence"] and float(x["DMS_score"])==json.loads(row["label_json"])
            rebuilt=list(wt); valid=True; mutant=x["mutant"]
            for mutation in re.split("[:,]",mutant):
                match=re.fullmatch("([ACGUT])([0-9]+)([ACGUT])",mutation)
                if not match: valid=False; break
                a,i,b=match.groups(); i=int(i)-1; a=a.replace("T","U"); b=b.replace("T","U")
                if not 0<=i<len(wt) or wt[i]!=a: valid=False; break
                rebuilt[i]=b
            if mutant.lower() in ["wt","wildtype",""]: valid=True
            roundtrip=valid and "".join(rebuilt)==seq.replace("T","U")
            replay.append(dict(record_id=row["record_id"],source_row=row["source_row"],source_sequence_label_exact=same,wt_variant_roundtrip=roundtrip))
        write_tsv(destination/"source_row_replay.tsv",replay)
        proof.update(mode="FULL_RELEASE_TO_CURATED_SEQUENCE_AND_LABEL_REPLAY",n=len(replay),source_release_n=len(original),release_sequence_label_exact_n=sum(r["source_sequence_label_exact"] for r in replay),wt_variant_roundtrip_n=sum(r["wt_variant_roundtrip"] for r in replay),original_experiment_row_mapping="PUBLISHED_ASSAY_TO_SECONDARY_RELEASE_CHAIN_STILL_REQUIRES_REVIEW")
    elif unit.startswith("MRNA_"):
        src=prov["inputs"][0]; path=ROOT/src["path"]
        if sha(path)!=src["sha256"]: raise ValueError("SOURCE_HASH_MISMATCH")
        original=pq.read_table(path).to_pylist(); replay=[]; coverage=[]
        for row in curated:
            x=original[int(row["source_row"])-1]
            same=x["sequence"]==row["sequence"] and float(x["target"])==json.loads(row["label_json"])["target"]
            replay.append(dict(record_id=row["record_id"],source_row=row["source_row"],source_sequence_label_exact=same))
            cds=x.get("cds",[]); positions=[i for i,v in enumerate(cds) if v]
            coverage.append(dict(record_id=row["record_id"],source_row=row["source_row"],sequence_length=len(x["sequence"]),source_cds_track_length=len(cds),nonzero_cds_markers=len(positions),first_marker_0=positions[0] if positions else "",last_marker_0=positions[-1] if positions else "",actual_input="released_cDNA_sequence",coverage_interpretation="codon-marker track preserved; transcript boundary completeness and 5UTR/CDS/3UTR spans NOT_INDEPENDENTLY_VERIFIED; NOT_CDS_ONLY"))
        write_tsv(destination/"source_row_replay.tsv",replay); write_tsv(destination/"sequence_region_coverage.tsv",coverage)
        proof.update(mode="FULL_SECONDARY_PARQUET_TO_CURATED_REPLAY",n=len(replay),source_release_n=len(original),release_sequence_label_exact_n=sum(r["source_sequence_label_exact"] for r in replay),original_experiment_row_mapping="TRANSCRIPT_CONDITION_AND_PARENT_ASSAY_JOIN_NOT_VERIFIED")
    else:
        proof.update(mode="CURATED_FREEZE_AND_OBSERVATION_ALIAS_MAPPING_VERIFIED_ONLY",reason="Karner raw tar/ArchiveII restricted pickle derivation not reinterpreted; original experiment mapping still HOLD")
    return proof


def run():
    destination=OUT/"scientific_evidence"; destination.mkdir(exist_ok=False)
    manifests=[json.loads((ROOT/p).read_text()) for p in json.loads((PILOT/"prepared_panel.json").read_text())["datasets"]]
    summaries=[]; overlaps=defaultdict(set); split_results=[]; homology=[]
    for manifest in manifests:
        unit=manifest["spec"]["unit"]; key=hashlib.sha256(unit.encode()).hexdigest()[:16]; dest=destination/key; dest.mkdir()
        mpath=PILOT/"datasets"/key; eligible=[json.loads(s) for s in (mpath/"observations.jsonl").read_text().splitlines()]
        for r in eligible: overlaps[r["sequence_hash"]].add(unit)
        is_utr=unit.startswith("5UTR/")
        if not is_utr:
            d=ROOT/"data/processed"/unit/QC; prov=json.loads((d/"provenance.json").read_text()); freeze=json.loads((d/"freeze.json").read_text()); curated=pq.read_table(d/"curated_data.parquet").to_pylist()
            assert sha(d/"curated_data.parquet")==freeze["files"]["curated_data.parquet"]==manifest["source_sha256"]
            mapping=pq.read_table(d/"observation_mapping.parquet").to_pylist(); mapped={r["record_id"] for r in mapping}
            assert all(r["record_id"] in mapped for r in curated)
            literal=Counter(r["sequence"] for r in curated); equivalent=Counter(r["sequence"].upper().replace("T","U") for r in curated)
            label_groups=defaultdict(set)
            for r in curated: label_groups[r["sequence"].upper().replace("T","U")].add(r["label_json"])
            proof=source_replay(unit,d,curated,prov,dest)
            counts=dict(curated_n=len(curated),mapping_alias_n=len(mapping),mapped_records_n=len(mapped),missing_mapping_n=sum(r["record_id"] not in mapped for r in curated),literal_unique_n=len(literal),equivalent_unique_n=len(equivalent),equivalent_repeated_rows=sum(v-1 for v in equivalent.values()),input_multiple_label_groups=sum(len(v)>1 for v in label_groups.values()),curated_sha256=sha(d/"curated_data.parquet"),source_release_to_curated=proof)
            write_json(dest/"source_lineage.json",prov)
        else:
            registry=json.loads((ROOT/"data/registries/utr_legacy_102.json").read_text()); source=next(r for r in registry["datasets"] if r["dataset"]==unit)
            counts=dict(curated_n=manifest["n_local"],mapping_alias_n=None,equivalent_unique_n=len({r["sequence_hash"] for r in eligible}),equivalent_repeated_rows=len(eligible)-len({r["sequence_hash"] for r in eligible}),source_release_to_curated=dict(mode="INHERITED_LEGACY_FOLD_HASH_BINDINGS",raw_label_formula=source["row"]["raw_label_formula"],source_original_experiment_row_mapping="UNVERIFIED"))
            write_json(dest/"source_lineage.json",source)
        for protocol in manifest["protocols"]:
            split=read_table(ROOT/protocol["split_path"]); assert sha(ROOT/protocol["split_path"])==protocol["split_hash"]
            byid={r["record_id"]:r for r in eligible}; observations=[dict(byid[r["record_id"]],role=r["role"],split_group=r["split_group"]) for r in split]
            leakage={}
            for field in ["sequence_hash","biological_group","split_group","gene","transcript","construct_id"]:
                groups=defaultdict(set)
                for r in observations:
                    value=r.get(field) if field in r else r["metadata"].get(field)
                    if value not in [None,"","UNKNOWN"]: groups[str(value)].add(r["role"])
                leakage[field]=sum(len(v)>1 for v in groups.values()) if groups else "UNKNOWN_NO_IDENTIFIERS"
            split_results.append(dict(unit=unit,protocol=protocol["protocol"],fold=protocol["outer_fold"],split_sha256=protocol["split_hash"],**leakage,wt_scope="SAME_WT_ACROSS_ROLES_BY_DESIGN_NOT_WT_GENERALIZATION" if unit.startswith("DMS_") else "NOT_APPLICABLE_OR_UNVERIFIED",homology_clearance="NOT_PROVEN"))
            if unit.startswith("DMS_") and protocol["outer_fold"]==0:
                queries=sorted([r for r in observations if r["role"]=="train"],key=lambda r:r["record_id"])[:64]; targets=[r for r in observations if r["role"]=="test"]
                lengths={len(r["model_sequence"]) for r in queries+targets}; assert len(lengths)==1
                target=np.array([list(r["model_sequence"].encode()) for r in targets],dtype=np.uint8)
                best=[float(np.max(np.mean(target==np.frombuffer(r["model_sequence"].encode(),dtype=np.uint8),axis=1))) for r in queries]
                homology.append(dict(unit=unit,scope="bounded64TRAIN_vs_ALL_TEST_same_length_ungapped_identity_NOT_FULL_HOMOLOGY_CLUSTERING",queries=len(queries),test_targets=len(targets),nearest_identity_min=min(best),nearest_identity_median=float(np.median(best)),nearest_identity_max=max(best),fraction_nearest_ge_95percent=float(np.mean(np.array(best)>=.95)),interpretation="Near-WT variants cross roles; legitimate within-library smoke only, no unseen-WT claim"))
        write_json(dest/"technical_audit.json",counts)
        summaries.append(dict(unit=unit,evidence_directory=str(dest.relative_to(ROOT)),local_n=manifest["n_local"],eligible_n=manifest["n_eligible"],excluded_n=manifest["n_excluded"],equivalent_unique_n=counts["equivalent_unique_n"],equivalent_repeated_rows=counts["equivalent_repeated_rows"],disposition="HOLD",formal_admitted=False,human_review="NOT_REVIEWED"))
    persist=json.loads((ROOT/"runs/20261023_131628/reports/persist_summary.json").read_text()); dest=destination/"persist"; dest.mkdir()
    write_json(dest/"prior_audit_revalidated.json",dict(prior_summary_sha256=sha(ROOT/"runs/20261023_131628/reports/persist_summary.json"),prior_audit=persist,interpretation="203 matched construct sequences; half-life values do not match pinned source;179-row shared-component cluster. No repair or relabeling",scientific_admitted=False))
    summaries.append(dict(unit="PERSIST_MRL_HL_PAIR",evidence_directory=str(dest.relative_to(ROOT)),local_n=203,eligible_n=203,excluded_n=30,equivalent_unique_n="SEE_PRIOR_COMPONENT_AUDIT",equivalent_repeated_rows="SHARED_PARTS179_CONNECTED_COMPONENT",disposition="HOLD_SOURCE_LABEL_VERSION_AND_GROUP_LEAKAGE",formal_admitted=False,human_review="NOT_REVIEWED"))
    cross=[]
    for a,b in itertools.combinations(sorted(m["spec"]["unit"] for m in manifests),2): cross.append(dict(unit_a=a,unit_b=b,shared_exact_normalized_sequences=sum(a in s and b in s for s in overlaps.values()),scope="ELIGIBLE_PILOT_SEQUENCE_VIEWS_ONLY",homology_clearance="NOT_ESTABLISHED"))
    write_tsv(destination/"priority_nine_summary.tsv",summaries); write_tsv(destination/"split_gene_exact_audit.tsv",split_results); write_tsv(destination/"bounded_dms_homology_screen.tsv",homology); write_tsv(destination/"cross_dataset_overlap.tsv",cross)
    print(summaries); print(homology)

if __name__=="__main__":run()
