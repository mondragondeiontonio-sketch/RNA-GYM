"""Real train-only linear CMP/DMP baselines on unchanged RNA3DB D1 roles. No FM/GPU."""
import hashlib
import json
import time
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.preprocessing import StandardScaler
from tools.structure_anchor_v1 import load_cif, labels_from_columns, POLICY
from tools.next_stage_verify import average_precision
from tools.next_stage_taxonomy import ROOT, read_table
OUT=ROOT/"runs/20261102_blocker_optimization_v1"
OLD=ROOT/"runs/20261102_taxonomy_admission_adaptation_v1/structure_anchor"


def features(sequence,pairs):
    a=pairs[:,0]; b=pairs[:,1]; gap=(b-a).astype(float)
    bases=np.array(["ACGU".find(x) for x in sequence])
    if (bases<0).any(): raise ValueError("UNKNOWN_BASE_NOT_SILENTLY_ENCODED")
    combinations=np.eye(16)[bases[a]*4+bases[b]]
    return np.column_stack([np.log1p(gap),gap/len(sequence),(a+b)/max(1,2*len(sequence)),combinations])


def metrics(distance,contact,xyz,pairs,prediction,probability):
    direct=np.array([float(np.sqrt(np.sum((xyz[i]-xyz[j])**2))) for i,j in pairs])
    y=(direct<8).astype(int); error=prediction-distance; direct_error=prediction-direct
    mae=float(np.mean(abs(error))); replay_mae=float(np.mean(abs(direct_error)))
    assert abs(mae-replay_mae)<1e-4 and np.array_equal(y,contact)
    predicted_contact=probability>=.5; tp=int(np.sum(predicted_contact&y.astype(bool))); fp=int(np.sum(predicted_contact&~y.astype(bool))); fn=int(np.sum(~predicted_contact&y.astype(bool)))
    return dict(n_pairs=len(y),positive_contacts=int(y.sum()),MAE=mae,RMSE=float(np.sqrt(np.mean(error**2))),AUPRC=average_precision(y.tolist(),probability.tolist()),F1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.0,replay_MAE=replay_mae,replay_pass=True)


def run():
    start=time.monotonic(); directory=OUT/"structure_learned_anchor"; directory.mkdir(exist_ok=False)
    selection=json.loads((OUT/"structure_train_prefix_selection.json").read_text()); xs=[]; ds=[]; cs=[]; train_audit=[]; groups=set()
    for item in selection["train_chains"]:
        path=ROOT/item["path"]; assert hashlib.sha256(path.read_bytes()).hexdigest()==item["member_sha256"]
        sequence,xyz,distance,contact,valid,residues,audit=labels_from_columns(load_cif(path))
        assert hashlib.sha256(sequence.encode()).hexdigest()==item["equivalent_input_sha256"]
        assert item["role"]=="train"; groups.add(item["group_id"])
        pairs=np.argwhere(np.triu(valid,1))
        if len(pairs)>20000:
            # deterministic positions-only subsample; never uses distance/contact labels.
            rng=np.random.default_rng(42); pairs=pairs[np.sort(rng.choice(len(pairs),20000,replace=False))]
        if not len(pairs): raise ValueError("NO_VALID_TRAIN_PAIRS")
        x=features(sequence,pairs); idx=tuple(pairs.T); xs.append(x); ds.append(distance[idx]); cs.append(contact[idx])
        train_audit.append(dict(entry=item["entry"],role="train",group_id=item["group_id"],used_pairs=len(pairs),positive_contacts=int(contact[idx].sum()),**audit))
        np.savez_compressed(directory/(item["entry"]+"_labels.npz"),sequence=np.array(sequence),coordinates=xyz,distance=distance,contact=contact,valid_mask=valid)
    X=np.concatenate(xs); distance_y=np.concatenate(ds); contact_y=np.concatenate(cs)
    scaler=StandardScaler().fit(X); z=scaler.transform(X); dmodel=Ridge(alpha=1.0).fit(z,distance_y)
    if len(set(contact_y))==2:
        cmodel=LogisticRegression(C=1.0,class_weight="balanced",max_iter=300,random_state=42).fit(z,contact_y); contact_kind="logistic_regression"
    else: cmodel=None; contact_kind="train_prevalence_constant_due_to_missing_class"
    params=dict(distance_model="Ridge(alpha=1.0)",contact_model=contact_kind,scaler_mean=scaler.mean_.tolist(),scaler_scale=scaler.scale_.tolist(),ridge_coef=dmodel.coef_.tolist(),ridge_intercept=float(dmodel.intercept_),contact_coef=cmodel.coef_.tolist() if cmodel is not None else None,contact_intercept=cmodel.intercept_.tolist() if cmodel is not None else None,contact_train_prevalence=float(np.mean(contact_y)),feature_schema="log1p(sequence_gap),gap/L,mean_relative_position,16_base_combination_onehots",fit_scope="EXISTING_TRAIN_CHAINS_ONLY",hyperparameters="fixed_not_selected_on_validation_or_test")
    (directory/"model_parameters.json").write_text(json.dumps(params,indent=2)+"\n")
    (directory/"train_alignment_audit.json").write_text(json.dumps(train_audit,indent=2)+"\n")
    metrics_rows=[]
    testmeta={a["entry_id"]:a for a in json.loads((OLD/"alignment_audit.json").read_text())}
    for previous in read_table(OLD/"metrics.tsv"):
        entry=previous["entry_id"]; audit=testmeta[entry]; assert audit["group_id"] not in groups
        labels=np.load(OLD/(entry+".npz"),allow_pickle=False); sequence=str(labels["sequence"]); pairs=np.argwhere(np.triu(labels["valid_mask"],1)); idx=tuple(pairs.T); x=features(sequence,pairs); z=scaler.transform(x)
        prediction=dmodel.predict(z); probability=cmodel.predict_proba(z)[:,1] if cmodel is not None else np.full(len(pairs),np.mean(contact_y))
        # Reconstruct predictions independently from exported coefficients, no pickle.
        manual_z=(x-np.asarray(params["scaler_mean"]))/np.asarray(params["scaler_scale"])
        assert np.allclose(prediction,manual_z@np.asarray(params["ridge_coef"])+params["ridge_intercept"])
        if cmodel is not None:
            logits=manual_z@np.asarray(params["contact_coef"])[0]+params["contact_intercept"][0]
            assert np.allclose(probability,1/(1+np.exp(-logits)))
        np.savez_compressed(directory/(entry+"_predictions.npz"),pairs=pairs,distance=prediction,contact_probability=probability)
        result=metrics(labels["distance"][idx],labels["contact"][idx],labels["coordinates"],pairs,prediction,probability)
        metrics_rows.append(dict(entry=entry,role=audit["role"],group_id=audit["group_id"],**result))
    import csv
    with (directory/"metrics.tsv").open("w") as f:
        w=csv.DictWriter(f,fieldnames=list(metrics_rows[0]),delimiter="\t"); w.writeheader(); w.writerows(metrics_rows)
    summary=dict(status="REAL_TRAIN_LABEL_PREDICTION_METRIC_REPLAY_PASS",train_chains=len(train_audit),train_groups=len(groups),train_pairs=len(X),training_contact_positives=int(contact_y.sum()),evaluation_chains=len(metrics_rows),cpu_wall_seconds=time.monotonic()-start,gpu_seconds=0,policy=POLICY,existing_split="RNAGYM_RNA3DB_RANDOM_D1_V1_1",existing_splits_modified=False,source_downloads=0,validation_or_test_used_for_fitting=False,formal_admitted=False,limitations=["tiny technical anchor; no representative scientific score","related heldout chains share a group and are not independently weighted","source rights, assembly and full homology/contamination admission remain HOLD"])
    (directory/"summary.json").write_text(json.dumps(summary,indent=2)+"\n"); print(summary); print(metrics_rows)

if __name__=="__main__":run()
