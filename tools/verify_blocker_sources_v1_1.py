"""Replay local source bindings without downloads, training, or any label edits."""
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"runs/20261102_blocker_optimization_v1"


def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024**2),b""): h.update(b)
    return h.hexdigest()


def run():
    raw=ROOT/"raw_cache/quarantine/RNAGYM_DMS/A0002/17705ef3534bce614d5d280eaeff17744929439fe9951d0924fe6710879ff5b8/fitness_raw_data.zip"
    processed=ROOT/"raw_cache/quarantine/RNAGYM_DMS/P0_RNAGYM_PROCESSED/56a91b52bfd9537abb4b5e8f5f9bbb663fd712e95e404e26338e4aa3090e2279/fitness_processed_assays.zip"
    assert sha(raw)=="17705ef3534bce614d5d280eaeff17744929439fe9951d0924fe6710879ff5b8"
    assert sha(processed)=="56a91b52bfd9537abb4b5e8f5f9bbb663fd712e95e404e26338e4aa3090e2279"
    with zipfile.ZipFile(processed) as z:
        rows=list(csv.DictReader(io.TextIOWrapper(z.open("assays/Andreasson_2020_ribozyme.csv"),encoding="utf-8-sig")))
    scores={r["sequence"]:float(r["DMS_score"]) for r in rows}; counts={s:0 for s in scores}; exact=0; finite_kcat=0
    with zipfile.ZipFile(raw) as z:
        name="raw_data/andreasson_2020/dataframe1_kobs_kcat_KM_rescues.csv"
        for r in csv.DictReader(io.TextIOWrapper(z.open(name),encoding="utf-8-sig")):
            s=r["glmS_variant_sequence"].upper().replace("T","U")
            value=float(r["kcat"]) if r["kcat"] else float("nan")
            finite_kcat+=math.isfinite(value)
            if s in scores:
                counts[s]+=1
                if value==scores[s]: exact+=1
    assert exact==len(rows)==7343 and all(v==1 for v in counts.values())
    a=dict(processed_n=len(rows),unique_original_sequence_joins=len(counts),exact_kcat_matches=exact,source_finite_kcat_n=finite_kcat,source_column="kcat",unit="s^-1 from original kinetic Methods",input_view="original DNA table TtoU only; full retained74nt construct")
    source=Path(json.loads((OUT/"danio_source_binding.json").read_text())["source_table"])
    raw_rows=list(csv.DictReader(source.open(),delimiter="\t")); byseq={}
    for r in raw_rows:
        s=r["insert_seq"].upper().replace("T","U")
        if s in byseq: raise ValueError("AMBIGUOUS_SOURCE_SEQUENCE")
        byseq[s]=r
    obsfile=ROOT/"runs/rnagym_rnafm_hf_pilot_v1_2/datasets/35eec65a06723185/observations.jsonl"
    observations=[json.loads(x) for x in obsfile.read_text().splitlines()]
    exact=0; partial_native=0
    for r in observations:
        x=byseq[r["model_sequence"]]
        exact+=float(x["log2_MRL_6hpf"])==r["raw_label"]
        assert len(x["insert_seq"])==int(x["insert_length"])
        partial_native+=int(x["insert_length"])<int(x["utr_length"])
    assert exact==len(observations)==len(raw_rows)==18021
    d=dict(source_table_sha256=sha(source),source_n=len(raw_rows),pilot_n=len(observations),exact_log2_MRL6hpf_matches=exact,tested_insert_shorter_than_native_UTR_n=partial_native,sequence_region="5UTR_derived_tested_insert_NOT_assumed_complete_native_UTR",publisher_accession_chain="UNVERIFIED")
    result=dict(status="PASS_LOCAL_SOURCE_BINDING_REPLAY",andreasson=a,danio=d,source_files_modified=False,scientific_admitted=False)
    path=OUT/"original_source_row_replay_verification.json"; text=json.dumps(result,indent=2)+"\n"
    if path.exists() and path.read_text()!=text: raise ValueError("IMMUTABLE_EVIDENCE_CONFLICT")
    if not path.exists(): path.write_text(text)
    print(result)

if __name__=="__main__":run()
