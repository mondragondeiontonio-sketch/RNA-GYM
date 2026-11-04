"""Fixed tiny adaptation recipe; no HPO, no formal ranking, no frozen reencoding."""
import argparse
from collections import Counter
import hashlib
import itertools
import json
import os
from pathlib import Path
import time
import numpy as np
from tools.next_stage_taxonomy import ROOT, OUT, read_table, write_json, write_tsv

PILOT=ROOT/"runs/rnagym_rnafm_hf_pilot_v1_2/datasets/de383a87b2e3bf38"
WORK=OUT/"adaptation"


def digest(s): return hashlib.sha256(s.encode()).hexdigest()


def metrics(y,p):
    from scipy.stats import spearmanr, pearsonr
    from sklearn.metrics import r2_score
    y=np.asarray(y); p=np.asarray(p)
    return dict(Spearman=float(spearmanr(y,p).statistic) if np.std(p)>0 else None,Pearson=float(pearsonr(y,p).statistic) if np.std(p)>0 else None,RMSE=float(np.sqrt(np.mean((p-y)**2))),MAE=float(np.mean(abs(p-y))),R2=float(r2_score(y,p)))


def prepare():
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline
    WORK.mkdir(exist_ok=False)
    rows=[json.loads(s) for s in (PILOT/"observations.jsonl").read_text().splitlines()]
    roles={r["record_id"]:r["role"] for r in read_table(PILOT/"EAZY_fold_0.tsv")}
    selected=[]
    for role,n in [("train",64),("validation",16),("test",32)]:
        candidates=sorted([dict(r,role=role,feature_index=i) for i,r in enumerate(rows) if roles[r["record_id"]]==role],key=lambda r:digest("adaptation-v1-label-blind"+r["record_id"]))
        if len(candidates)<n: raise ValueError("INSUFFICIENT_FIXED_ROLE")
        selected.extend(candidates[:n])
    assert len({r["sequence_hash"] for r in selected})==112
    train=np.array([r["role"]=="train" for r in selected]); test=np.array([r["role"]=="test" for r in selected])
    y=np.array([r["label"] for r in selected]); mean=float(y[train].mean()); scale=float(y[train].std())
    assert scale>0
    write_json(WORK/"fixed_recipe.json",dict(dataset="DMS_Andreasson_2020_ribozyme",canonical_task="DMS_FITNESS",subset_counts=dict(Counter(r["role"] for r in selected)),parent_split="EAZY_fold_0",parent_split_sha256=digest((PILOT/"EAZY_fold_0.tsv").read_text()),selection="sha256(seed+record_id), label blind within EXISTING roles",seed=42,epochs=1,batch_size=4,steps=16,hpo_trials=0,encoder_lr=1e-4,head_lr=1e-3,lora_rank=4,lora_alpha=8,lora_targets=["q_proj","v_proj"],train_label_mean=mean,train_label_std=scale,normalization_fit="TRAIN_ONLY",label_transform="none except explicit train standardization inverted for metrics",scope="within SAME WT/library only; not WT-heldout generalization",frozen_reencoding=False,full_ft_conditional=True,formal_eligible=False,checkpoint_saved_for_full_or_scratch=False))
    write_json(WORK/"subset.json",selected)
    def kmer(s):
        values=[]
        for n in [1,2,3]:
            counts=Counter(s[i:i+n] for i in range(len(s)-n+1))
            values += [counts[k]/max(1,len(s)-n+1) for k in map("".join,itertools.product("ACGU",repeat=n))]
        return values
    result=[]
    frozen=np.load(PILOT/"frozen_features.npy",mmap_mode="r")
    for model,x in [("kmer123_ridge",np.array([kmer(r["model_sequence"]) for r in selected])),("cached_frozen_ridge_same_subset",np.array([frozen[r["feature_index"]] for r in selected]))]:
        start=time.monotonic(); estimator=make_pipeline(StandardScaler(),Ridge(alpha=1.0)); estimator.fit(x[train],(y[train]-mean)/scale)
        pred=estimator.predict(x[test])*scale+mean
        write_tsv(WORK/(model+"_predictions.tsv"),[dict(record_id=r["record_id"],label=float(a),prediction=float(b)) for r,a,b in zip([r for r in selected if r["role"]=="test"],y[test],pred)])
        result.append(dict(model=model,**metrics(y[test],pred),cpu_seconds=time.monotonic()-start,gpu_seconds=0.0,test_n=32,train_n=64,formal_eligible=False))
    write_tsv(WORK/"cpu_reference_metrics.tsv",result)
    # Reuse the actual old Linear/MLP receipts as full-population reference, NEVER
    # compare their scores as if they used the tiny adaptation training subset.
    old=[r for r in read_table(ROOT/"runs/rnagym_rnafm_hf_pilot_v1_2/fold_metrics.tsv") if "Andreasson" in str(r) and (r.get("outer_fold")=="0" or r.get("fold")=="0")]
    write_json(WORK/"frozen_linear_mlp_existing_reference.json",dict(rows=old,comparison_scope="existing full-fold results; different label budget; not a matched comparison",rerun=False))
    print(result)


def train(mode, *, reference_work=None):
    from rna_gym.budget import BudgetDenied
    if not os.environ.get("RNA_GYM_BUDGET_TOKEN"):
        raise BudgetDenied("SUPERVISED_PERSISTENT_BUDGET_REQUIRED")
    from rna_gym.compute_guard import require_compute_lease
    require_compute_lease()
    import torch
    from torch import nn
    from tools.pilot_v1_2_run import gpu_guard
    # Reuse safety logic without allowing it to overwrite the completed Pilot receipt.
    import tools.pilot_v1_2_run as legacy
    legacy.RUN=WORK/mode; legacy.RUN.mkdir(parents=True,exist_ok=False)
    guard=gpu_guard()
    recipe_dir=Path(reference_work).resolve() if reference_work is not None else WORK
    recipe=json.loads((recipe_dir/"fixed_recipe.json").read_text()); rows=json.loads((recipe_dir/"subset.json").read_text())
    torch.set_num_threads(4); torch.manual_seed(42); np.random.seed(42); torch.cuda.manual_seed_all(42)
    started=time.monotonic()
    from rna_gym import RNAHub
    encoder=RNAHub.load("RNA-FM-HF",root=ROOT,initialization="random" if mode=="scratch" else "pretrained",seed=42)
    adapter=encoder._adapter; backbone=adapter.model
    for p in backbone.parameters(): p.requires_grad_(mode!="lora")
    # Language/contact heads are not the supervised task and have no loss here.
    for name,p in backbone.named_parameters():
        if name.startswith(("lm_head.","contact_head.","embed_out")): p.requires_grad_(False)
    targets=[]
    if mode=="lora":
        from rna_gym.lora import LoRALinear
        for name,module in list(backbone.named_modules()):
            if isinstance(module,nn.Linear) and name.split(".")[-1] in ["q_proj","v_proj"]:
                parent,leaf=name.rsplit(".",1); setattr(backbone.get_submodule(parent),leaf,LoRALinear(module)); targets.append(name)
        if not targets: raise ValueError("NO_LORA_TARGETS_NO_SUBSTITUTION")
    head=nn.Linear(adapter.dimension,1).cuda()
    parameters=[p for p in backbone.parameters() if p.requires_grad]+list(head.parameters())
    optimizer=torch.optim.AdamW([dict(params=[p for p in backbone.parameters() if p.requires_grad],lr=1e-4),dict(params=head.parameters(),lr=1e-3)],weight_decay=1e-4)
    mean=recipe["train_label_mean"]; scale=recipe["train_label_std"]
    subsets={role:[r for r in rows if r["role"]==role] for role in ["train","validation","test"]}
    def forward(batch):
        _,strings,tokens=adapter.converter([(r["record_id"],r["model_sequence"]) for r in batch])
        offset=int(adapter.alphabet.prepend_bos)
        for i,r in enumerate(batch):
            seq=r["model_sequence"]; expected=[adapter.alphabet.get_idx(nt) for nt in seq]
            if strings[i]!=seq or tokens[i,offset:offset+len(seq)].tolist()!=expected: raise ValueError("TOKEN_ALIGNMENT")
        tokens=tokens.cuda(); reps=backbone(tokens,repr_layers=[adapter.layer],return_contacts=False)["representations"][adapter.layer]
        pooled=torch.stack([reps[i,offset:offset+len(r["model_sequence"])].mean(0) for i,r in enumerate(batch)])
        return head(pooled).squeeze(-1)
    torch.cuda.reset_peak_memory_stats(); backbone.train(); head.train(); losses=[]
    order=np.random.default_rng(42).permutation(64); trainstart=time.monotonic()
    for start in range(0,64,4):
        batch=[subsets["train"][int(i)] for i in order[start:start+4]]
        optimizer.zero_grad(set_to_none=True); pred=forward(batch)
        label=torch.tensor([(r["label"]-mean)/scale for r in batch],device="cuda",dtype=torch.float32)
        loss=torch.mean((pred-label)**2)
        if not torch.isfinite(loss): raise ValueError("NONFINITE_LOSS")
        loss.backward(); torch.nn.utils.clip_grad_norm_(parameters,1.0,error_if_nonfinite=True); optimizer.step(); losses.append(float(loss.detach()))
    torch.cuda.synchronize(); trainseconds=time.monotonic()-trainstart
    backbone.eval(); head.eval(); scores={}
    for role in ["validation","test"]:
        predictions=[]
        with torch.no_grad():
            for start in range(0,len(subsets[role]),4): predictions.extend((forward(subsets[role][start:start+4]).cpu().numpy()*scale+mean).tolist())
        labels=[r["label"] for r in subsets[role]]
        write_tsv(WORK/mode/(role+"_predictions.tsv"),[dict(record_id=r["record_id"],label=float(a),prediction=float(b)) for r,a,b in zip(subsets[role],labels,predictions)])
        scores[role]=metrics(labels,predictions)
    torch.cuda.synchronize(); total=time.monotonic()-started
    if mode=="lora": torch.save({"adapter":{k:v.detach().cpu() for k,v in backbone.state_dict().items() if k.endswith((".A",".B"))},"head":head.state_dict()},WORK/mode/"adapter.pt")
    write_json(WORK/mode/"result.json",dict(mode=mode,recipe_sha256=digest((recipe_dir/"fixed_recipe.json").read_text()),model_contract=adapter.contract,requested_model="RNA-FM-HF",deployment=encoder.deployment,architecture="EXACT_PINNED_RNAFM_ENCODER_PLUS_IDENTICAL_LINEAR_HEAD",model_parameters=sum(p.numel() for p in backbone.parameters()),trainable_parameters=sum(p.numel() for p in parameters),lora_targets=targets,train_steps=len(losses),losses=losses,metrics=scores,train_gpu_wall_seconds=trainseconds,training_sequences_per_second=64/trainseconds,total_gpu_process_seconds=total,peak_allocated_bytes=torch.cuda.max_memory_allocated(),peak_reserved_bytes=torch.cuda.max_memory_reserved(),gpu_uuid=guard["physical_gpu_uuid"],formal_eligible=False))
    print(mode,scores,"seconds",total,flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("mode",choices=["prepare","scratch","lora","full_ft"]); parser.add_argument("--output",type=Path); parser.add_argument("--reference-work",type=Path); args=parser.parse_args()
    if args.output is not None:
        WORK=args.output.resolve()
        if not WORK.is_relative_to(ROOT): raise ValueError("OUTPUT_MUST_REMAIN_IN_PROJECT")
    if args.mode=="prepare": prepare()
    else: train(args.mode,reference_work=args.reference_work)
