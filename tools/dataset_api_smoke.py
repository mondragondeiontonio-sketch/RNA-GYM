#!/usr/bin/env python3
"""Single allocated GPU, real RNA-FM-HF API, exactly two head epochs per view.

Uses local datasets only. It does NOT fine-tune the pretrained encoder, admit
assays, publish labels, or reinterpret raw contact/probing data as canonical SSP/SSI.
"""
import argparse
import collections
import contextlib
import csv
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time

from tools.build_arena_v1 import ROOT, QC, load, dump, sha, table, tsv


def model_sequence(raw, max_nt):
    if not isinstance(raw,str) or not raw:
        raise ValueError('MISSING_SEQUENCE')
    value=raw.upper().replace('T','U')
    if set(value)-set('ACGU'):
        raise ValueError('UNSUPPORTED_NUCLEOTIDE_NO_IMPUTATION')
    if len(value)>max_nt:
        raise ValueError('TOO_LONG_NO_TRUNCATION')
    return value


def decode(value):
    return json.loads(value) if isinstance(value,str) else value


def probe_vector(value):
    """Parse inert comma-separated numeric arrays, including author nan sentinels."""
    if isinstance(value,list): return value
    if not isinstance(value,str) or not value.strip().startswith('[') or not value.strip().endswith(']'):
        raise ValueError('PROBING_VECTOR_SCHEMA')
    fields=value.strip()[1:-1].split(',')
    if len(fields)>1022: raise ValueError('PROBING_VECTOR_TOO_LONG')
    return [None if x.strip().lower() in ('null','none') else float(x.strip()) for x in fields]


def flat_numeric(value):
    """A complete scalar/vector endpoint; never replace a structured target."""
    value=decode(value)
    if isinstance(value,dict):
        if any(isinstance(v,dict) for v in value.values()):
            raise ValueError('STRUCTURED_TARGET_NEEDS_DEDICATED_ADAPTER')
        result=[]
        for key in sorted(value):
            result.extend(flat_numeric(value[key]))
        return result
    if isinstance(value,list):
        result=[]
        for item in value: result.extend(flat_numeric(item))
        return result
    if isinstance(value,(float,int,bool)) and math.isfinite(float(value)):
        return [float(value)]
    raise ValueError('NONNUMERIC_OR_NONFINITE_TARGET')


def record_groups(rows):
    parent=list(range(len(rows))); seen={}
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i,r in enumerate(rows):
        keys=[('input',r['input_hash'])]
        meta=decode(r.get('group_metadata_json') or '{}')
        for field in ['gene','transcript','pdb_entry']:
            if meta.get(field): keys.append((field,str(meta[field])))
        for key in keys:
            if key in seen: parent[find(i)]=find(seen[key])
            else: seen[key]=i
    members=collections.defaultdict(list)
    for i,r in enumerate(rows): members[find(i)].append(r['record_id'])
    ids={k:hashlib.sha256('\n'.join(sorted(v)).encode()).hexdigest() for k,v in members.items()}
    return [ids[find(i)] for i in range(len(rows))]


def roles(rows):
    groups=record_groups(rows); unique=sorted(set(groups))
    if len(unique)<3: raise ValueError('INSUFFICIENT_INDEPENDENT_SMOKE_GROUPS')
    assigned={g:('test' if i==0 else 'validation' if i==1 else 'train') for i,g in enumerate(unique)}
    return [assigned[g] for g in groups],groups


def gpu_guard(config):
    uuid=config['gpu_physical_uuid']
    if not os.environ.get('SLURM_JOB_ID'):
        raise ValueError('SCHEDULER_ALLOCATION_REQUIRED')
    visible=os.environ.get('CUDA_VISIBLE_DEVICES','').split(',')
    if visible!=[uuid]: raise ValueError('EXACT_ONE_AUTHORIZED_GPU_UUID_REQUIRED')
    inventory=subprocess.check_output(['nvidia-smi','--query-gpu=index,uuid,memory.used,utilization.gpu',
        '--format=csv,noheader,nounits'],text=True)
    processes=subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory',
        '--format=csv,noheader'],text=True)
    if any(line.split(',')[0].strip()==uuid for line in processes.splitlines()):
        raise ValueError('SELECTED_GPU_ALREADY_BUSY_DO_NOT_TOUCH_MD')
    return dict(slurm_job_id=os.environ['SLURM_JOB_ID'], host=os.uname().nodename,
        selected_uuid=uuid, visible_devices=os.environ['CUDA_VISIBLE_DEVICES'],
        inventory_before=inventory, processes_before=processes, other_gpus_used=False)


def local_rows(view,hub,config):
    """Read bounded examples, preserving all roles and full target values."""
    did=view['dataset_id']; unit=view['unit_id']
    if did.startswith('UTR102:'):
        source=hub.utr(did)
        stream=source.iter_fold(fold=0)
        p=source._fold_path(0)
        source_hash=sha(p)
        def convert():
            for i,r in enumerate(stream):
                h=hashlib.sha256(r['sequence'].encode()).hexdigest()
                yield dict(record_id='utr0:'+str(i),observation_id='utr0:'+str(i),
                    input_hash=h,sequence=r['sequence'],sequence_b=None,label_json=json.dumps(r['raw_label']),
                    group_metadata_json='{}',source_original_role=r['set'])
        return convert(),source_hash,'regression',int(view['n_records']),p
    p=ROOT/'data/processed'/unit/QC/'curated_data.parquet'
    import pyarrow.parquet as pq
    pf=pq.ParquetFile(p)
    def stream():
        for batch in pf.iter_batches(batch_size=128):
            yield from batch.to_pylist()
    q=load(p.with_name('qc_report.json'))
    problem=q['problem_type']
    if unit=='MRNA_mirna_preprocessed' or 'binary_vector' in str(q.get('target_schema')):
        problem='multilabel_classification'
    return stream(),sha(p),problem,pf.metadata.num_rows,p


def prepare(view,hub,config):
    stream,source_hash,problem,full_n,path=local_rows(view,hub,config)
    selected=[]; skipped=collections.Counter(); inspected=0
    for row in stream:
        inspected+=1
        if inspected>config['scan_cap_per_dataset']: break
        try:
            row=dict(row)
            row['model_sequence']=model_sequence(row['sequence'],config['maximum_sequence_length'])
            if row.get('sequence_b'):
                if row.get('sequence_b_kind')=='protein':
                    raise ValueError('PROTEIN_INPUT_UNSUPPORTED_BY_RNA_ENCODER')
                row['model_sequence_b']=model_sequence(row['sequence_b'],config['maximum_sequence_length'])
            if problem in ('structure_prediction',):
                raise ValueError('COORDINATE_REFERENCE_NEEDS_RESIDUE_ALIGNED_LABEL_ADAPTER')
            if problem=='family_annotation_source':
                if not isinstance(decode(row['label_json']),str): raise ValueError('FAMILY_LABEL_NOT_STRING')
            elif problem=='nucleotide_regression' or view['input_type']=='probing':
                problem='site_regression'
                label=decode(row['label_json'])
                signal=probe_vector(label['reactivity'])
                if len(signal)!=len(row['sequence']): raise ValueError('SITE_LENGTH_MISMATCH')
                row['site_label']=[float(v) if v is not None and math.isfinite(float(v)) and float(v)!=-999 else None for v in signal]
                if not any(v is not None for v in row['site_label']): raise ValueError('NO_VALID_SITE_LABELS')
            elif problem=='structured_contact_prediction':
                label=decode(row['label_json'])
                if not {'index_mapping','directed_contact_edges_local_zero_based'}.issubset(label):
                    raise ValueError('CONTACT_SCHEMA_MISMATCH')
            else:
                row['numeric_target']=flat_numeric(row['label_json'])
            selected.append(row)
            if len(selected)>=config['sample_cap_per_dataset']: break
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            skipped[str(exc)]+=1
    if len(selected)<4:
        raise ValueError('TOO_FEW_COMPATIBLE_ROWS:'+json.dumps(dict(skipped),sort_keys=True))
    split,groups=roles(selected)
    ontology=[]
    if problem=='family_annotation_source':
        q=load(ROOT/'data/processed'/view['unit_id']/QC/'qc_report.json')
        ontology=sorted((q.get('class_counts') or {}).keys())
    return dict(label_vocabulary=ontology,rows=selected,roles=split,groups=groups,problem=problem,full_n=full_n,
        inspected=min(inspected,config['scan_cap_per_dataset']),skipped=dict(skipped),source_hash=source_hash,
        source_path=str(path))


class Features:
    def __init__(self,encoder): self.encoder=encoder;self.pool={}
    def get(self,sequence,site=False):
        import numpy as np
        if site:
            return self.encoder.encode(sequences=[sequence],pooling='none',batch_size=1)[0]
        if sequence not in self.pool:
            self.pool[sequence]=self.encoder.encode(sequences=[sequence],batch_size=1)[0]
        return self.pool[sequence]


def train(prepared,features,config,out):
    import numpy as np
    import torch
    from torch import nn
    torch.manual_seed(config['seed'])
    examples=prepared['rows'];problem=prepared['problem']; xs=[];ys=[];row_roles=[]
    vocab={}
    if problem=='family_annotation_source':
        # Declared labels only; unseen heldout labels do not leak into the training head.
        ontology=prepared.get('label_vocabulary') or sorted({decode(r['label_json']) for r,role in zip(examples,prepared['roles']) if role=='train'})
        vocab={v:i for i,v in enumerate(ontology)}
    for r,role in zip(examples,prepared['roles']):
        if problem in ('site_regression','structured_contact_prediction'):
            nt=features.get(r['model_sequence'],site=True)
            if problem=='site_regression':
                for i,label in enumerate(r['site_label']):
                    if label is not None:
                        xs.append(nt[i]);ys.append([label]);row_roles.append(role)
            else:
                label=decode(r['label_json']); idx=label['index_mapping']; edges={tuple(x) for x in label['directed_contact_edges_local_zero_based']}
                # Bounded raw-directed graph diagnostic; NOT a canonical SSP score.
                candidates=sorted(edges)[:64]
                for i in range(len(idx)):
                    for j in range(i+1,min(len(idx),i+5)):
                        if len(candidates)>=128: break
                        if (i,j) not in edges: candidates.append((i,j))
                    if len(candidates)>=128: break
                for i,j in candidates:
                    xs.append(np.concatenate([nt[idx[i]],nt[idx[j]]]))
                    ys.append([float((i,j) in edges)]);row_roles.append(role)
        else:
            x=features.get(r['model_sequence'])
            if r.get('model_sequence_b'):
                x=np.concatenate([x,features.get(r['model_sequence_b'])])
            if problem=='family_annotation_source':
                value=decode(r['label_json'])
                if value not in vocab: continue
                y=vocab[value]
            else: y=r['numeric_target']
            xs.append(x);ys.append(y);row_roles.append(role)
    if not xs or len({len(x) for x in xs})!=1:
        raise ValueError('INCONSISTENT_INPUT_FEATURE_ROLES')
    x=torch.as_tensor(np.asarray(xs),dtype=torch.float32,device='cuda:0')
    train_mask=torch.tensor([r=='train' for r in row_roles],device=x.device)
    test_mask=torch.tensor([r=='test' for r in row_roles],device=x.device)
    if not train_mask.any(): raise ValueError('EMPTY_TRAIN_GROUPS')
    if not test_mask.any(): raise ValueError('EMPTY_HELDOUT_LABEL_SUPPORT')
    mean=x[train_mask].mean(0);scale=x[train_mask].std(0,unbiased=False).clamp_min(1e-6)
    x=(x-mean)/scale
    categorical=problem=='family_annotation_source'
    binary='classification' in problem or problem=='structured_contact_prediction'
    y=torch.as_tensor(np.asarray(ys),dtype=torch.long if categorical else torch.float32,device=x.device)
    if not torch.isfinite(x).all() or not torch.isfinite(y.float()).all(): raise ValueError('NONFINITE_TRAINING_INPUT')
    width=len(vocab) if categorical else y.shape[1]
    net=nn.Sequential(nn.Linear(x.shape[1],config['head']['hidden_width']),nn.GELU(),
        nn.Dropout(config['head']['dropout']),nn.Linear(config['head']['hidden_width'],width)).to(x.device)
    loss_fn=nn.CrossEntropyLoss() if categorical else nn.BCEWithLogitsLoss() if binary else nn.MSELoss()
    if not categorical and not binary:
        ym=y[train_mask].mean(0);yscale=y[train_mask].std(0,unbiased=False).clamp_min(1e-6)
        target=(y-ym)/yscale
    else: target=y
    optimizer=torch.optim.AdamW(net.parameters(),lr=config['head']['learning_rate'],weight_decay=config['head']['weight_decay'])
    epochs=[]
    for epoch in range(1,config['epochs']+1):
        net.train();optimizer.zero_grad(set_to_none=True)
        loss=loss_fn(net(x[train_mask]),target[train_mask])
        if not torch.isfinite(loss): raise ValueError('NONFINITE_LOSS')
        loss.backward()
        if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in net.parameters()): raise ValueError('NONFINITE_GRADIENT')
        optimizer.step();epochs.append(dict(epoch=epoch,train_loss=float(loss.detach())))
    net.eval()
    with torch.inference_mode():
        prediction=net(x)
    if not torch.isfinite(prediction).all(): raise ValueError('NONFINITE_PREDICTION')
    out.mkdir(parents=True,exist_ok=True)
    torch.save(dict(head={k:v.detach().cpu() for k,v in net.state_dict().items()},
        feature_mean=mean.cpu(),feature_scale=scale.cpu()),out/'head.pt')
    dump(out/'epochs.json',epochs)
    assignments=[dict(record_id=r['record_id'],input_hash=r['input_hash'],role=role,group_id=g,
        model_sequence_sha256=hashlib.sha256(r['model_sequence'].encode()).hexdigest())
        for r,role,g in zip(examples,prepared['roles'],prepared['groups'])]
    tsv(out/'sample_assignments.tsv',assignments)
    return dict(epochs_completed=len(epochs),n_smoke_records=len(examples),n_train_elements=int(train_mask.sum()),
        n_test_elements=int(test_mask.sum()),head_checkpoint_sha256=sha(out/'head.pt'),
        final_train_loss=epochs[-1]['train_loss'],label_vocabulary_train_classes=len(vocab) if categorical else '',
        predictions_finite=True,model_encoder_frozen=True)


def run(args):
    config=load(ROOT/args.config)
    if config['model_id'] in config['excluded_model_ids'] or config['epochs']!=2:
        raise ValueError('ONLY_APPROVED_RNA_FM_HF_TWO_EPOCH_SMOKE')
    out=ROOT/args.out;out.mkdir(parents=True,exist_ok=True)
    with (out/'gpu.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        before=gpu_guard(config);dump(out/'gpu_allocation.json',before)
        from rna_gym import RNAHub,DatasetHub
        hub=DatasetHub(root=ROOT)
        views=hub.dataset_views()
        selected={v['dataset_id']:v for v in views}
        if args.dataset_id:
            requested=set(args.dataset_id)
            if requested-set(selected): raise ValueError('UNREGISTERED_DATASET_ID')
            views=[v for v in views if v['dataset_id'] in requested]
        if args.limit: views=views[:args.limit]
        import torch
        if torch.cuda.device_count()!=1: raise ValueError('EXACTLY_ONE_VISIBLE_GPU_REQUIRED')
        encoder=RNAHub.load('RNA-FM',root=ROOT,manifest=config['model_manifest'],device='cuda:0',seed=config['seed'])
        features=Features(encoder);results=[];all_started=time.monotonic()
        manifest=load(ROOT/config['model_manifest'])
        dump(out/'execution_identity.json',dict(model_id='RNA-FM',deployment='RNA-FM-HF',
            checkpoint_sha256=manifest['checkpoint_sha256'],source_sha256=sha(Path(__file__)),
            config_sha256=sha(ROOT/args.config),model_contract=encoder.contract,
            api='rna_gym.RNAHub.load / RNAEncoder.encode / DatasetHub.dataset_views / UTRDataset.iter_fold',
            formal_leaderboard_eligible=False))
        for index,view in enumerate(views):
            started=time.monotonic();did=view['dataset_id'];key=hashlib.sha256(did.encode()).hexdigest()[:20]
            result=dict(dataset_id=did,source_collection=view['source_collection'],unit_id=view['unit_id'],
                full_dataset_n=view.get('n_records'),scientific_admission='HOLD',
                scientific_role='SECONDARY_PROXY' if any(c in ['variant.protein_proxy','ann.go','ann.protein_location','variant.clinical_proxy'] for c in view['category_ids']) else 'REVIEW_REQUIRED',
                model_id='RNA-FM-HF',evaluation_phase='TWO_EPOCH_TECHNICAL_SMOKE',
                epochs_requested=2,epochs_completed=0,formal_leaderboard_eligible=False)
            forward_before=encoder._adapter.forward_sequences
            try:
                p=prepare(view,hub,config)
                result.update(train(p,features,config,out/'datasets'/key))
                result.update(status='PASSED_TECHNICAL_SMOKE',full_dataset_n=p['full_n'],
                    source_sha256=p['source_hash'],rows_inspected=p['inspected'],filtered_rows=json.dumps(p['skipped'],sort_keys=True),
                    n_smoke_groups=len(set(p['groups'])),actual_problem_type=p['problem'])
            except (ValueError,KeyError,RuntimeError,TypeError) as exc:
                reason=str(exc)
                result.update(status='INCOMPATIBLE' if any(t in reason for t in ['UNSUPPORTED','TOO_LONG','COORDINATE_REFERENCE']) else 'NOT_RUN' if 'TOO_FEW' in reason or 'INSUFFICIENT' in reason else 'FAILED',
                    error_reason=reason[:1500])
                if 'out of memory' in reason.lower(): torch.cuda.empty_cache()
            result.update(gpu_forward_sequences=encoder._adapter.forward_sequences-forward_before,
                wall_seconds=time.monotonic()-started)
            dump(out/'datasets'/key/'result.json',result);results.append(result)
            dump(out/'progress.json',dict(completed=len(results),expected=len(views),
                statuses=dict(collections.Counter(r['status'] for r in results)),last_dataset=did,
                wall_seconds=time.monotonic()-all_started))
            print(index+1,len(views),did,result['status'],result.get('epochs_completed'),flush=True)
        fields=list(dict.fromkeys(k for r in results for k in r))
        tsv(out/'dataset_smoke_results.tsv',results,fields)
        dump(out/'summary.json',dict(expected=len(views),completed=len(results),statuses=dict(collections.Counter(r['status'] for r in results)),
            datasets_passed=sum(r['status']=='PASSED_TECHNICAL_SMOKE' for r in results),
            scientific_admitted=0,epochs_per_passed_dataset=2,model_id='RNA-FM-HF',
            resources=encoder.resources(),wall_seconds=time.monotonic()-all_started,
            cpu_fallback=False,other_gpus_used=False,raw_modified=False,formal_results=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='configs/dataset_api_smoke_v1_1.yaml')
    parser.add_argument('--out',default='runs/20261030_structure_engineering_smoke_v1/gpu_smoke')
    parser.add_argument('--limit',type=int)
    parser.add_argument('--dataset-id',action='append')
    run(parser.parse_args())
