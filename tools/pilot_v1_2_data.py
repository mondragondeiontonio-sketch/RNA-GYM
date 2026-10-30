import collections
import hashlib
import json
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
from tools.build_arena_v1 import ROOT, QC, load, dump, sha, table, tsv
from rna_gym import DatasetHub

RUN = ROOT / "runs/rnagym_rnafm_hf_pilot_v1_2"
CONFIG = ROOT / "configs/rnafm_hf_pilot_v1_2.yaml"

def digest(s): return hashlib.sha256(s.encode()).hexdigest()
def sequence_view(s):
    if not isinstance(s, str) or not s: return None, "MISSING_INPUT"
    v = s.upper().replace("T", "U")
    if len(v) > 1022: return None, "TOO_LONG_NO_TRUNCATION"
    if set(v) - set("ACGU"): return None, "UNSUPPORTED_ALPHABET"
    return v, None

def group_rows(rows):
    parent = list(range(len(rows))); seen = {}
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i, row in enumerate(rows):
        keys = [("seq", row["sequence_hash"])]
        keys += [(f, str(row["metadata"][f])) for f in ["gene", "transcript", "construct_id"] if row["metadata"].get(f)]
        for key in keys:
            if key in seen: parent[find(i)] = find(seen[key])
            else: seen[key] = i
    members = collections.defaultdict(list)
    for i, r in enumerate(rows): members[find(i)].append(r["record_id"])
    hashes = {g: digest("\n".join(sorted(ids))) for g, ids in members.items()}
    for i, r in enumerate(rows): r["biological_group"] = hashes[find(i)]

def role_split(rows, outer, seed):
    bygroup = collections.defaultdict(list)
    for r in rows: bygroup[r["split_group"]].append(r)
    tests = {g for g, rs in bygroup.items() if any(r["outer_fold"] == outer for r in rs)}
    if any(any(r["outer_fold"] != outer for r in bygroup[g]) for g in tests):
        raise ValueError("FROZEN_TEST_GROUP_LEAKAGE")
    pool = sorted(set(bygroup) - tests, key=lambda g: digest(str(seed) + g))
    if len(pool) < 10: raise ValueError("TOO_FEW_TRAIN_GROUPS")
    val = set(pool[:max(1, len(pool)//10)])
    if rows[0]["problem_type"] == "classification":
        for label in {r["label"] for g in pool for r in bygroup[g]}:
            if not any(r["label"] == label for g in set(pool)-val for r in bygroup[g]):
                val.discard(next(g for g in pool if any(r["label"] == label for r in bygroup[g])))
    result = {r["record_id"]: "test" if r["split_group"] in tests else "validation" if r["split_group"] in val else "train" for r in rows}
    for field in ["sequence_hash", "biological_group", "split_group"]:
        seen = collections.defaultdict(set)
        for r in rows: seen[r[field]].add(result[r["record_id"]])
        if any(len(v)>1 for v in seen.values()): raise ValueError("CROSS_ROLE_LEAKAGE:"+field)
    counts = collections.Counter(result.values())
    if min(counts.get(k,0) for k in ["train","validation","test"]) < 10:
        raise ValueError("INSUFFICIENT_VALIDATION_OR_TEST_SIZE")
    return result

def read_candidate(spec, hub):
    unit = spec["unit"]
    if spec["target"] == "raw_label":
        ds = hub.utr("UTR102:"+unit); rec = ds.record
        rows = [dict(record_id="utr:"+str(i), raw_sequence=r["sequence"], raw_label=r["raw_label"], metadata={}) for i,r in enumerate(ds.iter_fold(fold=0))]
        p = ds._fold_path(0)
        q = dict(label_definition=rec["label_definition"], label_unit=rec["label_unit"],
            input_schema={"region":rec["input_type"], "context":rec.get("sequence_context")},
            source=rec["source_dataset"], assay_id="UTR_SOURCE:"+rec["source_dataset"],
            reported_n=None, actual_n=len(rows), valid_n=len(rows), source_doi="UNKNOWN")
        version = "UTR_LEGACY_102_20261019"
    else:
        p = ROOT/"data/processed"/unit/QC/"curated_data.parquet"
        q = load(p.with_name("qc_report.json")); freeze = load(p.with_name("freeze.json"))
        if sha(p) != freeze["files"]["curated_data.parquet"]: raise ValueError("CURATED_HASH_CHANGED")
        raw = pq.read_table(p, columns=["record_id","sequence","sequence_b","label_json","group_metadata_json"]).to_pylist()
        rows=[]
        for r in raw:
            value = json.loads(r["label_json"])
            label = value if spec["target"] in ["scalar","family"] else value.get(spec["target"])
            rows.append(dict(record_id=r["record_id"], raw_sequence=r["sequence"], raw_label=label,
                metadata=json.loads(r["group_metadata_json"] or "{}"), sequence_b=r.get("sequence_b")))
        version=QC
    classes = sorted({str(r["raw_label"]) for r in rows}) if spec["type"]=="classification" else []
    eligible=[]; excluded=[]
    for r in rows:
        seq, reason = sequence_view(r["raw_sequence"])
        if r.get("sequence_b"): reason="PAIRED_INPUT_NEEDS_SEPARATE_PROTOCOL"
        if spec["type"]=="regression" and (type(r["raw_label"]) not in [float,int] or not np.isfinite(r["raw_label"])): reason="INVALID_LABEL"
        if reason:
            excluded.append(dict(record_id=r["record_id"],reason=reason,length=len(r["raw_sequence"] or ""))); continue
        r.update(model_sequence=seq, sequence_hash=digest(seq), literal_sequence_hash=digest(r["raw_sequence"]),
            label=classes.index(str(r["raw_label"])) if classes else float(r["raw_label"]), problem_type=spec["type"])
        eligible.append(r)
    group_rows(eligible)
    return eligible,excluded,q,p,sha(p),version,classes,len(rows)


def prepare():
    RUN.mkdir(parents=True,exist_ok=True)
    config=load(CONFIG); hub=DatasetHub(root=ROOT)
    dump(RUN/"training_config.yaml",config)
    audits=[]; selected=[]; split_audit=[]; panel=[]; overlap=collections.defaultdict(set)
    for spec in config["datasets"]:
        unit=spec["unit"]; directory=RUN/"datasets"/digest(unit)[:16]
        directory.mkdir(parents=True,exist_ok=True)
        try:
            rows,excluded,q,source,source_hash,version,classes,n_local=read_candidate(spec,hub)
            tsv(directory/"excluded_records.tsv",excluded,["record_id","reason","length"])
            if len(rows)<100: raise ValueError("FEWER_THAN_100_ELIGIBLE")
            entries=[]
            if spec["target"]!="raw_label":
                d=source.parent
                frozen=pq.read_table(d/"splits/split_manifest.parquet").to_pylist()
                summaries=load(d/"splits/split_summary.json")["protocols"]
            for protocol in spec["protocols"]:
                if protocol=="UTR_LEGACY_10FOLD":
                    raw_splits={}; source_hashes={}
                    for outer in config["outer_folds_10"]:
                        ds=hub.utr("UTR102:"+unit); source_hashes[str(outer)]=sha(ds._fold_path(outer))
                        records=list(ds.iter_fold(fold=outer))
                        mapping={digest(sequence_view(r["sequence"])[0]):r["set"]=="test" for r in records}
                        if len(mapping)!=len(records): raise ValueError("AMBIGUOUS_LEGACY_DUPLICATES")
                        raw_splits[outer]={r["record_id"]:outer if mapping[r["sequence_hash"]] else -1 for r in rows}
                    group_mapping={r["record_id"]:r["biological_group"] for r in rows}
                    split_source_hash=digest(json.dumps(source_hashes,sort_keys=True))
                    difficulty="D1_STANDARD"
                else:
                    summ=summaries[protocol]
                    if summ["status"]!="PASS": continue
                    byid={r["record_id"]:r for r in frozen if r["protocol"]==protocol}
                    folds=config["outer_folds_10"] if summ["n_folds"]==10 else list(range(min(3,summ["n_folds"])))
                    raw_splits={outer:{r["record_id"]:byid[r["record_id"]]["outer_fold"] for r in rows} for outer in folds}
                    group_mapping={r["record_id"]:byid[r["record_id"]]["group_id"] for r in rows}
                    split_source_hash=sha(d/"splits/split_manifest.parquet")
                    difficulty="D2_GENERALIZATION" if protocol=="OOD_split" else "D1_STANDARD"
                protocol_entries=[]
                try:
                    for outer,assign in raw_splits.items():
                        pr=[dict(r,outer_fold=assign[r["record_id"]],split_group=group_mapping[r["record_id"]]) for r in rows]
                        partition=collections.defaultdict(set)
                        for r in pr: partition[r["biological_group"]].add(r["outer_fold"])
                        if any(len(v)>1 for v in partition.values()): raise ValueError("FROZEN_PROTOCOL_BIOLOGICAL_GROUP_LEAKAGE")
                        roles=role_split(pr,outer,config["seed"])
                        if classes and len({r["label"] for r in rows if roles[r["record_id"]]=="train"})!=len(classes):
                            raise ValueError("TRAIN_ONTOLOGY_SUPPORT_MISSING")
                        path=directory/(protocol+"_fold_"+str(outer)+".tsv")
                        contents=[dict(record_id=r["record_id"],sequence_hash=r["sequence_hash"],biological_group=r["biological_group"],split_group=group_mapping[r["record_id"]],role=roles[r["record_id"]]) for r in rows]
                        if path.exists():
                            if table(path)!=[{k:str(v) for k,v in r.items()} for r in contents]: raise ValueError("IMMUTABLE_SPLIT_CONFLICT")
                        else: tsv(path,contents)
                        counts=dict(collections.Counter(roles.values()))
                        entry=dict(protocol=protocol,difficulty=difficulty,outer_fold=outer,split_path=str(path.relative_to(ROOT)),split_hash=sha(path),source_split_hash=split_source_hash,counts=counts,
                            group_counts={role:len({r["biological_group"] for r in rows if roles[r["record_id"]]==role}) for role in ["train","validation","test"]})
                        protocol_entries.append(entry)
                    entries.extend(protocol_entries)
                    for entry in protocol_entries:
                        split_audit.append(dict(dataset_id=unit,protocol=protocol,difficulty=difficulty,outer_fold=entry["outer_fold"],**entry["counts"],group_cross_role=0,exact_input_cross_role=0,split_hash=entry["split_hash"],source_split_hash=split_source_hash,status="PASS"))
                except ValueError as e:
                    split_audit.append(dict(dataset_id=unit,protocol=protocol,status="REJECTED_PROTOCOL",reason=str(e)))
            if not entries: raise ValueError("NO_QUALIFYING_FROZEN_PROTOCOL")
            for r in rows: overlap[r["sequence_hash"]].add(unit)
            bundle=dict(spec=spec,version=version,source=str(source),source_sha256=source_hash,provenance=q,classes=classes,n_local=n_local,
                n_eligible=len(rows),n_excluded=len(excluded),n_unique=len({r["sequence_hash"] for r in rows}),n_groups=len({r["biological_group"] for r in rows}),protocols=entries,
                phase="EXPLORATORY_PILOT",pilot_science_check="PILOT_SCIENCE_CHECK_PASS",formal_admitted=False,
                scope="all native-length compatible rows, no training subsampling",pretrain_overlap="PRETRAIN_OVERLAP_UNKNOWN")
            dump(directory/"data_manifest.json",bundle)
            with (directory/"observations.jsonl").open("w") as f:
                for r in rows: f.write(json.dumps(r,ensure_ascii=False,allow_nan=False)+"\n")
            panel.append(str((directory/"data_manifest.json").relative_to(ROOT)))
            selected.append(dict(dataset_id=unit,task_id=spec["task"],problem_type=spec["type"],target=spec["target"],original_n=q.get("reported_n") or "UNKNOWN",
                local_n=n_local,source_actual_n=q.get("actual_n"),qc_valid_n=q.get("valid_n"),compatible_n=len(rows),excluded_n=len(excluded),unique_sequence_n=bundle["n_unique"],biological_group_n=bundle["n_groups"],
                input_schema=json.dumps(q.get("input_schema"),ensure_ascii=False),label_definition=q.get("label_definition"),label_unit=q.get("label_unit"),
                source=q.get("source"),source_doi=q.get("source_doi"),assay_id=q.get("assay_id"),source_hash=source_hash,dataset_version=version,
                status="PILOT_SCIENCE_CHECK_PASS",formal_admitted=False))
            audits.append(dict(dataset_id=unit,status="PILOT_SCIENCE_CHECK_PASS",reason="verified local bytes, actual labels, exact/biological groups, frozen outer tests; exploratory use only",eligible_n=len(rows),excluded_n=len(excluded),
                residual_limitations=json.dumps(q.get("scientific_gaps",[]))))
            print("PREPARED",unit,len(rows),len(entries),flush=True)
        except (ValueError,KeyError) as e:
            audits.append(dict(dataset_id=unit,status="HOLD_PILOT_PRECHECK",reason=str(e),eligible_n=0))
            print("REJECTED",unit,str(e),flush=True)
    def save(name,rs,fields=None): tsv(RUN/name,rs,fields or list(dict.fromkeys(k for r in rs for k in r)))
    save("selected_datasets.tsv",selected)
    save("dataset_eligibility_audit.tsv",audits)
    save("split_validation.tsv",split_audit)
    dump(RUN/"prepared_panel.json",dict(config_sha256=sha(CONFIG),datasets=panel,selected_n=len(selected),requested_n=len(config["datasets"]),frozen_before_model_scores=True))
    cross=[dict(sequence_hash=h,datasets=";".join(sorted(ds))) for h,ds in overlap.items() if len(ds)>1]
    save("cross_dataset_overlap.tsv",cross,["sequence_hash","datasets"])
    dump(RUN/"contamination_audit.json",dict(cross_dataset_equivalent_sequence_groups=len(cross),datasets_never_pooled=True,
        exact_fold_leakage=0,biological_group_fold_leakage=0,pretrain_overlap="PRETRAIN_OVERLAP_UNKNOWN",
        D2_scope="prior approximate MMseqs/declared-group membership; not exhaustive identity guarantee",
        DMS_scope="D1 mutant construct split; one-WT family generalization not feasible"))
    return panel

if __name__=="__main__":prepare()
