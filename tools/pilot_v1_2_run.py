import argparse
import collections
import contextlib
import hashlib
import json
import math
import os
import pickle
import sqlite3
import subprocess
import time
from pathlib import Path
import numpy as np
from tools.build_arena_v1 import ROOT, load, dump, sha, table, tsv
from tools.pilot_v1_2_data import RUN, CONFIG, digest


def gpu_guard():
    if not os.getenv("SLURM_JOB_ID"): raise ValueError("NO_CURRENT_ALLOCATION")
    visible=os.getenv("CUDA_VISIBLE_DEVICES","").split(",")
    if len(visible)!=1 or not visible[0]: raise ValueError("EXACTLY_ONE_ALLOCATED_VISIBLE_GPU_REQUIRED")
    raw=subprocess.check_output(["nvidia-smi","--query-gpu=index,uuid,name,memory.used,utilization.gpu","--format=csv,noheader,nounits"],text=True)
    gpus=[r.split(",") for r in raw.strip().splitlines()]
    match=[r for r in gpus if r[0].strip()==visible[0] or r[1].strip()==visible[0]]
    if len(match)!=1: raise ValueError("ALLOCATION_GPU_MAPPING_AMBIGUOUS")
    gpu=match[0]; uuid=gpu[1].strip()
    processes=subprocess.check_output(["nvidia-smi","--query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory","--format=csv,noheader"],text=True)
    if any(r.split(",")[0].strip()==uuid for r in processes.splitlines()): raise ValueError("BLOCKED_GPU_UNAVAILABLE")
    if float(gpu[3])>128: raise ValueError("BLOCKED_GPU_MEMORY_IN_USE")
    step=os.getenv("SLURM_STEP_GPUS","").split(",")
    if not visible[0].startswith("GPU-") and visible[0] not in step: raise ValueError("GPU_NOT_IN_CURRENT_SLURM_STEP")
    result=dict(hostname=os.uname().nodename,user=os.getenv("USER"),slurm_job_id=os.getenv("SLURM_JOB_ID"),
        slurm_step_gpus=os.getenv("SLURM_STEP_GPUS"),cuda_visible_devices=os.getenv("CUDA_VISIBLE_DEVICES"),
        physical_gpu_uuid=uuid,inventory=raw,processes_before=processes,status="PASS_ONE_IDLE_ALLOCATED_GPU",pid=os.getpid())
    dump(RUN/"gpu_guard.json",result)
    return result


class Cache:
    def __init__(self, encoder, config):
        self.encoder=encoder;self.config=config
        self.db=sqlite3.connect(RUN/"embedding_cache.sqlite")
        self.db.execute("CREATE TABLE IF NOT EXISTS features (key TEXT PRIMARY KEY, sequence_hash TEXT, feature BLOB, dimension INTEGER)")
        c=encoder.contract
        self.identity=dict(model_hash=c["checkpoint_sha256"],tokenizer_hash=c["tokenizer_sha256"],preprocessing=config["preprocessing_version"],representation=config["representation"])
        self.prefix=json.dumps(self.identity,sort_keys=True)
        self.requests=[]
    def key(self,r): return digest(self.prefix+r["sequence_hash"])
    def extract(self,rows,directory):
        keys={r["sequence_hash"]:r for r in rows}; missing=[]
        for r in keys.values():
            if self.db.execute("SELECT 1 FROM features WHERE key=?",(self.key(r),)).fetchone() is None: missing.append(r)
        missing.sort(key=lambda r:(len(r["model_sequence"]),r["sequence_hash"]))
        i=0;retries=[];started=time.monotonic()
        while i<len(missing):
            length=len(missing[i]["model_sequence"])
            bs=16 if length<=256 else 8 if length<=512 else 4 if length<=768 else 2
            chunk=missing[i:i+bs]
            # Batches straddling length thresholds use the conservative upper-length rule.
            maxlen=max(len(r["model_sequence"]) for r in chunk)
            bs=min(bs,16 if maxlen<=256 else 8 if maxlen<=512 else 4 if maxlen<=768 else 2)
            chunk=missing[i:i+bs]
            while True:
                try:
                    values=self.encoder.encode(sequences=[r["model_sequence"] for r in chunk],batch_size=len(chunk));break
                except RuntimeError as exc:
                    if "out of memory" not in str(exc).lower() or len(chunk)==1: raise
                    import torch
                    torch.cuda.empty_cache();retries.append(dict(start=i,batch_before=len(chunk),reason="OOM_BATCH_HALVED_NO_SAMPLE_DROPPED"));chunk=chunk[:max(1,len(chunk)//2)]
            for r,value in zip(chunk,values):
                v=np.asarray(value,dtype=np.float32)
                if v.shape!=(self.encoder._adapter.dimension,) or not np.isfinite(v).all(): raise ValueError("INVALID_EMBEDDING")
                self.db.execute("INSERT INTO features VALUES (?,?,?,?)",(self.key(r),r["sequence_hash"],v.tobytes(),len(v)))
            self.db.commit();i+=len(chunk)
            if i%256<len(chunk) or i==len(missing):
                print("EMBED",directory.name,i,"/",len(missing),"seconds",round(time.monotonic()-started,1),flush=True)
                dump(RUN/"embedding_progress.json",dict(dataset=directory.name,completed=i,expected=len(missing),wall_seconds=time.monotonic()-started))
        x=[]
        for r in rows:
            blob,dim=self.db.execute("SELECT feature,dimension FROM features WHERE key=?",(self.key(r),)).fetchone()
            x.append(np.frombuffer(blob,dtype=np.float32).copy())
        result=np.asarray(x,dtype=np.float32);np.save(directory/"frozen_features.npy",result)
        receipt=dict(dataset=directory.name,rows=len(rows),unique_inputs=len(keys),cache_hits=len(keys)-len(missing),new_inputs=len(missing),feature_dim=result.shape[1],
            features_sha256=sha(directory/"frozen_features.npy"),seconds=time.monotonic()-started,oom_adjustments=retries,**self.identity)
        self.requests.append(receipt);dump(directory/"embedding_receipt.json",receipt)
        return result


def stats_features(rows):
    import itertools
    kmers=["".join(x) for x in itertools.product("ACGU",repeat=3)]
    result=[]
    for r in rows:
        s=r["model_sequence"];n=len(s);count=collections.Counter(s[i:i+3] for i in range(max(0,n-2)))
        result.append([math.log1p(n)]+[s.count(b)/n for b in "ACGU"]+[count[k]/max(1,n-2) for k in kmers])
    return np.asarray(result,dtype=np.float64)


def metric_values(y,pred,problem,classes):
    from sklearn.metrics import mean_absolute_error, mean_squared_error, f1_score, matthews_corrcoef, average_precision_score, roc_auc_score, ndcg_score
    from scipy.stats import spearmanr,pearsonr
    result={};undefined={}
    if problem=="regression":
        result.update(MAE=float(mean_absolute_error(y,pred)),RMSE=float(np.sqrt(mean_squared_error(y,pred))))
        for name,fn in [("Spearman",spearmanr),("Pearson",pearsonr)]:
            if len(y)<3 or np.ptp(y)==0 or np.ptp(pred)==0:
                result[name]=None;undefined[name]="constant target/prediction or insufficient support"
            else: result[name]=float(fn(y,pred).statistic)
        if np.min(y)>=0 and np.max(y)>0:
            result["NDCG"]=float(ndcg_score(y[None,:],pred[None,:]))
        else: result["NDCG"]=None;undefined["NDCG"]="negative/undefined relevance; no arbitrary label shifting"
    else:
        labels=list(range(len(classes)));chosen=np.argmax(pred,axis=1)
        result["Macro-F1"]=float(f1_score(y,chosen,labels=labels,average="macro",zero_division=0))
        result["MCC"]=float(matthews_corrcoef(y,chosen)) if len(set(y))>1 and len(set(chosen))>1 else None
        if result["MCC"] is None: undefined["MCC"]="degenerate true or predicted classes"
        auprc=[];auroc=[];perclass={}
        for k,name in enumerate(classes):
            binary=(y==k).astype(int);n=int(binary.sum());m=len(y)-n
            ap=float(average_precision_score(binary,pred[:,k])) if n and m else None
            auc=float(roc_auc_score(binary,pred[:,k])) if n and m else None
            perclass[name]=dict(positive=n,negative=m,prevalence=n/len(y),AUPRC=ap,AUROC=auc)
            if ap is not None:auprc.append(ap)
            if auc is not None:auroc.append(auc)
        result["Macro-AUPRC"]=float(np.mean(auprc)) if len(auprc)==len(classes) else None
        result["Macro-AUROC"]=float(np.mean(auroc)) if len(auroc)==len(classes) else None
        result["class_support"]=perclass
        if len(auprc)!=len(classes):undefined["Macro-AUPRC"]="one or more classes missing positive/negative test support"
        if len(auroc)!=len(classes):undefined["Macro-AUROC"]="one or more classes missing positive/negative test support"
    result["undefined_reasons"]=undefined
    return result


def fit_mlp(x,y,train,validation,problem,classes,config,directory):
    import torch
    from torch import nn
    from sklearn.preprocessing import StandardScaler
    torch.manual_seed(config["seed"])
    np.random.seed(config["seed"])
    scaler=StandardScaler().fit(x[train]); scaled=scaler.transform(x).astype(np.float32)
    is_reg=problem=="regression"
    mu=float(y[train].mean()) if is_reg else 0.0
    sigma=max(float(y[train].std()),1e-6) if is_reg else 1.0
    targets=(y-mu)/sigma if is_reg else y
    tensors=torch.tensor(scaled,device="cuda:0")
    target=torch.tensor(targets,dtype=torch.float32 if is_reg else torch.long,device="cuda:0")
    output_dim=1 if is_reg else len(classes)
    head=nn.Sequential(nn.Linear(x.shape[1],config["hidden_width"]),nn.GELU(),nn.Dropout(config["dropout"]),nn.Linear(config["hidden_width"],output_dim)).cuda()
    optimizer=torch.optim.AdamW(head.parameters(),lr=config["head_lr"],weight_decay=config["weight_decay"])
    loss_fn=nn.MSELoss() if is_reg else nn.CrossEntropyLoss()
    train_i=np.flatnonzero(train);val_i=torch.tensor(np.flatnonzero(validation),device="cuda:0")
    best=float("inf");wait=0;best_epoch=0;history=[];checkpoint=directory/"mlp_best.pt"
    for epoch in range(1,config["mlp_max_epochs"]+1):
        head.train();rng=np.random.default_rng(config["seed"]+epoch);permutation=rng.permutation(train_i)
        total=0.0
        for start in range(0,len(permutation),config["head_batch_size"]):
            index=torch.tensor(permutation[start:start+config["head_batch_size"]],device="cuda:0")
            optimizer.zero_grad(set_to_none=True);pred=head(tensors[index]);pred=pred.squeeze(-1) if is_reg else pred
            loss=loss_fn(pred,target[index])
            if not torch.isfinite(loss):raise ValueError("NONFINITE_HEAD_LOSS")
            loss.backward()
            if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in head.parameters()):raise ValueError("NONFINITE_HEAD_GRADIENT")
            optimizer.step();total+=float(loss.detach())*len(index)
        head.eval()
        with torch.inference_mode():
            v=head(tensors[val_i]);v=v.squeeze(-1) if is_reg else v
            vloss=float(loss_fn(v,target[val_i]))
        history.append(dict(epoch=epoch,train_loss=total/len(train_i),validation_loss=vloss))
        if vloss<best-1e-8:
            best=vloss;best_epoch=epoch;wait=0
            torch.save(dict(state_dict=head.state_dict(),feature_mean=scaler.mean_.tolist(),feature_scale=scaler.scale_.tolist(),target_mean=mu,target_scale=sigma,epoch=epoch),checkpoint)
        else:wait+=1
        if wait>=config["early_stopping_patience"]:break
    saved=torch.load(checkpoint,map_location="cuda:0",weights_only=True);head.load_state_dict(saved["state_dict"]);head.eval()
    with torch.inference_mode():
        prediction=head(tensors)
        prediction=prediction.squeeze(-1)*sigma+mu if is_reg else torch.softmax(prediction,dim=-1)
        result=prediction.cpu().numpy()
    tsv(directory/"training_validation_log.tsv",history)
    dump(directory/"training_receipt.json",dict(best_epoch=best_epoch,epochs_ran=len(history),early_stopping_metric="validation loss only",best_validation_loss=best,
        seed=config["seed"],checkpoint_sha256=sha(checkpoint),encoder_optimizer_parameters=0,head_parameter_count=sum(p.numel() for p in head.parameters())))
    return result,dict(best_epoch=best_epoch,epochs_ran=len(history),checkpoint_hash=sha(checkpoint))


def execute():
    import fcntl
    RUN.mkdir(parents=True,exist_ok=True)
    lock=(RUN/"execution.lock").open("a")
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    config=load(CONFIG);panel=load(RUN/"prepared_panel.json")
    if panel["config_sha256"]!=sha(CONFIG):raise ValueError("FROZEN_CONFIG_CHANGED")
    guard=gpu_guard()
    from rna_gym import RNAHub
    import torch
    torch.set_num_threads(2)
    if torch.cuda.device_count()!=1:raise ValueError("MORE_THAN_ONE_VISIBLE_GPU")
    started=time.monotonic()
    encoder=RNAHub.load("RNA-FM",root=ROOT,manifest=config["model_manifest"],device="cuda:0",seed=config["seed"])
    if encoder._adapter.model.training or any(p.requires_grad for p in encoder._adapter.model.parameters()):raise ValueError("ENCODER_NOT_FROZEN")
    initial_parameter_versions=[p._version for p in encoder._adapter.model.parameters()]
    manifest=load(ROOT/config["model_manifest"])
    dump(RUN/"model_manifest.json",dict(**manifest,verified_contract=encoder.contract,
        parameter_count=sum(p.numel() for p in encoder._adapter.model.parameters()),embedding_dimension=encoder._adapter.dimension,
        tokenizer_hash=encoder.contract["tokenizer_sha256"],pretrain_overlap="PRETRAIN_OVERLAP_UNKNOWN",
        load_api="rna_gym.RNAHub.load -> pinned RNA-FM-HF checkpoint via reviewed RNAFMAdapter"))
    cache=Cache(encoder,config)
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge,LogisticRegression
    metric_rows=[];prediction_manifest=[];fold_records=[]
    for manifest_path in panel["datasets"]:
        m=load(ROOT/manifest_path);d=(ROOT/manifest_path).parent;spec=m["spec"]
        rows=[json.loads(line) for line in (d/"observations.jsonl").read_text().splitlines()]
        if sha(Path(m["source"]))!=m["source_sha256"]:raise ValueError("SOURCE_DATA_CHANGED")
        x=cache.extract(rows,d);simple=stats_features(rows);y=np.asarray([r["label"] for r in rows]);problem=spec["type"];classes=m["classes"]
        for entry in m["protocols"]:
            path=ROOT/entry["split_path"]
            if sha(path)!=entry["split_hash"]:raise ValueError("FROZEN_SPLIT_CHANGED")
            role={r["record_id"]:r["role"] for r in table(path)}
            train=np.asarray([role[r["record_id"]]=="train" for r in rows]);validation=np.asarray([role[r["record_id"]]=="validation" for r in rows]);test=np.asarray([role[r["record_id"]]=="test" for r in rows])
            fd=d/(entry["protocol"]+"_"+str(entry["outer_fold"]));fd.mkdir(exist_ok=True)
            predictions={};checkpoints={}
            if problem=="regression":
                predictions["B0_mean"]=np.full(len(rows),y[train].mean());predictions["B0_median"]=np.full(len(rows),np.median(y[train]))
            else:
                prevalence=np.bincount(y[train].astype(int),minlength=len(classes))/train.sum()
                predictions["B0_prevalence"]=np.tile(prevalence,(len(rows),1))
            for name,features in [("B0_kmer_linear",simple),("B1_frozen_linear",x)]:
                head=Ridge(alpha=config["ridge_alpha"]) if problem=="regression" else LogisticRegression(C=config["logistic_C"],max_iter=2000,random_state=config["seed"])
                pipeline=make_pipeline(StandardScaler(),head);pipeline.fit(features[train],y[train])
                predictions[name]=pipeline.predict(features) if problem=="regression" else pipeline.predict_proba(features)
                model_file=fd/(name+".pkl")
                with model_file.open("wb") as f:pickle.dump(pipeline,f)
                checkpoints[name]=sha(model_file)
            # No encoder tensor is passed to or owned by the head optimizer.
            predictions["B2_frozen_mlp"],training=fit_mlp(x,y,train,validation,problem,classes,config,fd)
            checkpoints["B2_frozen_mlp"]=training["checkpoint_hash"]
            for name,pred in predictions.items():
                if not np.isfinite(pred).all():raise ValueError("NONFINITE_MODEL_PREDICTIONS")
                metrics=metric_values(y[test],pred[test],problem,classes)
                primary="Macro-F1" if problem=="classification" else "Spearman"
                identity=dict(dataset_id=spec["unit"],task_id=spec["task"],protocol=entry["protocol"],difficulty=entry["difficulty"],outer_fold=entry["outer_fold"],baseline=name,
                    phase="EXPLORATORY_PILOT",result_source="RNA_GYM_REPRODUCED",primary_metric=primary,n_train=int(train.sum()),n_validation=int(validation.sum()),n_test=int(test.sum()),
                    split_hash=entry["split_hash"],model_hash=manifest["checkpoint_sha256"],source_hash=m["source_sha256"],preprocessing=config["preprocessing_version"],formal_leaderboard_eligible=False)
                scalar={k:v for k,v in metrics.items() if k not in ["class_support","undefined_reasons"]}
                record=dict(**identity,**scalar,undefined_reasons=json.dumps(metrics["undefined_reasons"],sort_keys=True),class_support=json.dumps(metrics.get("class_support",{}),sort_keys=True))
                metric_rows.append(record);dump(fd/(name+"_score.json"),dict(**identity,metrics=metrics,training=training if name=="B2_frozen_mlp" else {}))
                prediction_rows=[]
                for i in np.flatnonzero(test|validation):
                    prediction_rows.append(dict(record_id=rows[i]["record_id"],sequence_hash=rows[i]["sequence_hash"],biological_group=rows[i]["biological_group"],role=role[rows[i]["record_id"]],
                        target=float(y[i]) if problem=="regression" else classes[int(y[i])],prediction=float(pred[i]) if problem=="regression" else json.dumps(pred[i].tolist())))
                pp=fd/(name+"_predictions.tsv");tsv(pp,prediction_rows)
                prediction_manifest.append(dict(**identity,prediction_file=str(pp.relative_to(ROOT)),prediction_sha256=sha(pp),checkpoint_hash=checkpoints.get(name,"TRAIN_ONLY_CONSTANT"),predictions=len(prediction_rows)))
            fold_records.append(dict(dataset_id=spec["unit"],protocol=entry["protocol"],outer_fold=entry["outer_fold"],mlp_best_epoch=training["best_epoch"],mlp_epochs_ran=training["epochs_ran"]))
            tsv(RUN/"fold_metrics.tsv",metric_rows,list(dict.fromkeys(k for r in metric_rows for k in r)))
            tsv(RUN/"prediction_manifest.tsv",prediction_manifest)
            dump(RUN/"progress.json",dict(last_dataset=spec["unit"],last_protocol=entry["protocol"],last_outer_fold=entry["outer_fold"],completed_protocol_folds=len(fold_records),result_rows=len(metric_rows),wall_seconds=time.monotonic()-started))
            print("FIT_DONE",spec["unit"],entry["protocol"],entry["outer_fold"],training,flush=True)
        tsv(RUN/"embedding_cache_manifest.tsv",cache.requests)
    if initial_parameter_versions!=[p._version for p in encoder._adapter.model.parameters()]:raise ValueError("ENCODER_PARAMETER_MODIFIED")
    dump(RUN/"execution_audit.json",dict(status="EXECUTED",phase="EXPLORATORY_PILOT",datasets=panel["selected_n"],protocol_folds=len(fold_records),result_rows=len(metric_rows),
        unique_cached_sequences=cache.db.execute("SELECT count(*) FROM features").fetchone()[0],wall_seconds=time.monotonic()-started,
        gpu=guard,resources=encoder.resources(),encoder_frozen_verified=True,encoder_parameter_version_unchanged=True,utrlm_loaded=False,
        new_slurm_jobs_submitted=0,raw_modified=False,human_approval_generated=False,formal_leaderboard_written=False,
        config_sha256=sha(CONFIG),runner_sha256=sha(Path(__file__)),data_preparer_sha256=sha(ROOT/"tools/pilot_v1_2_data.py")))
    tsv(RUN/"training_summary.tsv",fold_records)
    print("PILOT_EXECUTED",load(RUN/"execution_audit.json"),flush=True)

if __name__=="__main__": execute()
