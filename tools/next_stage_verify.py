"""Read-only prediction/coordinate replay and frozen-file verification. No model run."""
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from tools.next_stage_taxonomy import ROOT, OUT, read_table, write_json, write_tsv


def ranks(values):
    result=[0.0]*len(values); ordered=sorted(range(len(values)),key=values.__getitem__); i=0
    while i<len(values):
        j=i+1
        while j<len(values) and values[ordered[j]]==values[ordered[i]]: j+=1
        for k in ordered[i:j]: result[k]=(i+j-1)/2+1
        i=j
    return result


def correlation(a,b):
    ma=sum(a)/len(a); mb=sum(b)/len(b)
    da=[x-ma for x in a]; db=[x-mb for x in b]
    den=math.sqrt(sum(x*x for x in da)*sum(x*x for x in db))
    return sum(x*y for x,y in zip(da,db))/den if den else None


def average_precision(y,score):
    pairs=sorted(zip(score,y),reverse=True); positives=sum(y)
    if not positives or positives==len(y): return None
    tp=0; examined=0; ap=0; i=0
    while i<len(pairs):
        j=i+1
        while j<len(pairs) and pairs[j][0]==pairs[i][0]: j+=1
        new=sum(p[1] for p in pairs[i:j]); tp+=new; examined=j
        ap+=(new/positives)*(tp/examined); i=j
    return ap


def run():
    before=json.loads((OUT/"protected_before.json").read_text())
    after={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in before}
    mismatches=[p for p in before if before[p]!=after[p]]
    write_json(OUT/"protected_after.json",after)
    write_json(OUT/"protected_verification.json",dict(n_files=len(before),mismatches=mismatches,unchanged=not mismatches))
    if mismatches: raise AssertionError(mismatches)
    work=OUT/"adaptation"; replay=[]
    cpu={r["model"]:r for r in read_table(work/"cpu_reference_metrics.tsv")}
    for model in ["kmer123_ridge","cached_frozen_ridge_same_subset","scratch","full_ft"]:
        file=work/(model+"_predictions.tsv") if model in cpu else work/model/"test_predictions.tsv"
        saved=cpu[model] if model in cpu else json.loads((work/model/"result.json").read_text())["metrics"]["test"]
        rows=read_table(file); y=[float(r["label"]) for r in rows]; p=[float(r["prediction"]) for r in rows]
        rho=correlation(ranks(y),ranks(p)); rmse=math.sqrt(sum((a-b)**2 for a,b in zip(y,p))/len(y))
        mae=sum(abs(a-b) for a,b in zip(y,p))/len(y)
        passed=abs(rho-float(saved["Spearman"]))<1e-10 and abs(rmse-float(saved["RMSE"]))<1e-10 and abs(mae-float(saved["MAE"]))<1e-10
        replay.append(dict(model=model,n=len(y),Spearman=rho,RMSE=rmse,MAE=mae,passed=passed))
        assert passed
    write_tsv(OUT/"adaptation_prediction_replay.tsv",replay)
    structure=[]; directory=OUT/"structure_anchor"
    for row in read_table(directory/"metrics.tsv"):
        entry=row["entry_id"]; labels=np.load(directory/(entry+".npz"),allow_pickle=False); pred=np.load(directory/(entry+"_predictions.npz"),allow_pickle=False)
        mask=np.triu(labels["valid_mask"],1); pairs=np.argwhere(mask); xyz=labels["coordinates"]
        direct=np.array([math.sqrt(sum((float(xyz[i,k])-float(xyz[j,k]))**2 for k in range(3))) for i,j in pairs])
        contact=(direct<8).astype(int); prediction=pred["distance"][mask]; probability=pred["contact_probability"][mask]
        errors=prediction-direct; mae=float(np.mean(abs(errors))); rmse=float(np.sqrt(np.mean(errors**2)))
        ap=average_precision(contact.tolist(),probability.tolist()); binary=prediction<8; tp=int(sum(binary&contact.astype(bool))); fp=int(sum(binary&~contact.astype(bool))); fn=int(sum(~binary&contact.astype(bool))); f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.0
        passed=abs(mae-float(row["MAE"]))<1e-4 and abs(rmse-float(row["RMSE"]))<1e-4 and abs(ap-float(row["AUPRC"]))<1e-12 and f1==float(row["F1"]) and np.array_equal(contact,labels["contact"][mask])
        assert passed
        structure.append(dict(entry_id=entry,n_pairs=len(direct),MAE=mae,RMSE=rmse,AUPRC=ap,F1=f1,passed=passed,method="coordinate_norm_plus_independent_tie_grouped_AP"))
    write_tsv(OUT/"structure_prediction_replay.tsv",structure)
    panel=json.loads((ROOT/"configs/benchmark_panel_candidate_20261102_v1.yaml").read_text()); assert not panel["universal_score_enabled"] and not panel["model_scores_used_for_selection"] and not any(panel["formal_scoring_sets"].values())
    packs=list((OUT/"scientific_evidence").glob("*/evidence_pack.json")); assert len(packs)==9
    assert all(not json.loads(p.read_text())["scientific_admitted"] for p in packs)
    # Verify no changes to the completed frozen feature arrays, source-bound hashes
    # from its receipts are retained separately; no new encoding was executed.
    result=dict(status="PASS_SCOPED_ENGINEERING_ACCEPTANCE",protected_files_unchanged=len(before),adaptation_replay_n=len(replay),structure_replay_n=len(structure),evidence_packs=len(packs),formal_score_eligible=0,universal_score_generated=False,lora_gpu_status="FAILED_FIRST_ATTEMPT_FIXED_CPU_ONLY_RETRY_REQUIRES_NEW_BUDGET_APPROVAL",r03_scope="NEW_SUPERVISED_ADAPTATION_PATH_ONLY_LEGACY_DIRECT_SDK_NOT_UNIVERSALLY_BOUND")
    write_json(OUT/"acceptance_summary.json",result); print(result)

if __name__=="__main__":run()
