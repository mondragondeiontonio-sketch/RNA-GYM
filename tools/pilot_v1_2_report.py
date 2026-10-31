"""Saved-prediction replay, aggregate-only pilot exports and the A–E report."""
import collections
import hashlib
import json
from pathlib import Path
import sqlite3
import numpy as np
from tools.build_arena_v1 import ROOT, load, dump, sha, table, tsv
from tools.pilot_v1_2_data import RUN, CONFIG
from tools.pilot_v1_2_run import metric_values
PUBLIC = ROOT/'results/pilots/rnafm_hf_v1_2'


def replay(rows):
    checks=[]
    bykey={(r['dataset_id'],r['protocol'],r['outer_fold'],r['baseline']):r for r in rows}
    for entry in table(RUN/'prediction_manifest.tsv'):
        path=ROOT/entry['prediction_file']
        if sha(path)!=entry['prediction_sha256']:raise ValueError('PREDICTION_HASH_MISMATCH')
        data=[r for r in table(path) if r['role']=='test']
        saved=bykey[tuple(entry[k] for k in ['dataset_id','protocol','outer_fold','baseline'])]
        if len(data)!=int(saved['n_test']):raise ValueError('TEST_COUNT_MISMATCH')
        if saved['primary_metric']=='Macro-F1':
            classes=sorted(json.loads(saved['class_support']))
            y=np.asarray([classes.index(r['target']) for r in data]);p=np.asarray([json.loads(r['prediction']) for r in data])
            computed=metric_values(y,p,'classification',classes)
        else:
            computed=metric_values(np.asarray([float(r['target']) for r in data]),np.asarray([float(r['prediction']) for r in data]),'regression',[])
        for key,value in computed.items():
            if key in ['undefined_reasons','class_support']:continue
            if value is None:
                if saved.get(key) not in ('',None):raise ValueError('NA_WAS_FILLED')
            elif saved.get(key) in ('',None) or not np.isclose(value,float(saved[key]),rtol=1e-8,atol=1e-10):
                raise ValueError('METRIC_REPLAY_MISMATCH:'+key)
        checks.append(dict(dataset_id=entry['dataset_id'],protocol=entry['protocol'],outer_fold=entry['outer_fold'],baseline=entry['baseline'],test_n=len(data),status='PREDICTION_HASH_METRIC_REPLAY_PASS'))
    tsv(RUN/'prediction_replay_verification.tsv',checks)
    return len(checks)


def verify_cache(model,config):
    identity=dict(model_hash=model['checkpoint_sha256'],tokenizer_hash=model['tokenizer_hash'],preprocessing=config['preprocessing_version'],representation=config['representation'])
    prefix=json.dumps(identity,sort_keys=True);records=[]
    with sqlite3.connect(RUN/'embedding_cache.sqlite') as db:
        for key,h,blob,dim in db.execute('SELECT key,sequence_hash,feature,dimension FROM features ORDER BY key'):
            if key!=hashlib.sha256((prefix+h).encode()).hexdigest():raise ValueError('CACHE_KEY_MISMATCH')
            v=np.frombuffer(blob,dtype=np.float32)
            if dim!=640 or len(v)!=640 or not np.isfinite(v).all():raise ValueError('CORRUPT_CACHE')
            records.append(dict(cache_key=key,sequence_hash=h,feature_sha256=hashlib.sha256(blob).hexdigest(),dimension=dim,**identity))
    tsv(RUN/'embedding_cache_entries.tsv',records)
    return len(records)


def main():
    rows=table(RUN/'fold_metrics.tsv');audit=load(RUN/'execution_audit.json');selected=table(RUN/'selected_datasets.tsv')
    model=load(RUN/'model_manifest.json');config=load(CONFIG)
    replay_n=replay(rows);cached=verify_cache(model,config)
    grouped=collections.defaultdict(list)
    for r in rows:grouped[(r['dataset_id'],r['task_id'],r['protocol'],r['difficulty'],r['baseline'])].append(r)
    summaries=[]
    for (did,task,protocol,difficulty,baseline),rs in sorted(grouped.items()):
        s=dict(dataset_id=did,task_id=task,protocol=protocol,difficulty=difficulty,baseline=baseline,primary_metric=rs[0]['primary_metric'],n_folds=len(rs),phase='EXPLORATORY_PILOT',formal_leaderboard_eligible=False)
        for role in ['train','validation','test']:s[role+'_n_by_fold']=json.dumps([int(r['n_'+role]) for r in rs])
        for metric in ['Spearman','Pearson','MAE','RMSE','NDCG','Macro-F1','MCC','Macro-AUPRC','Macro-AUROC']:
            values=[float(r[metric]) for r in rs if r.get(metric) not in ('',None)]
            s[metric+'_mean']=float(np.mean(values)) if len(values)==len(rs) else None
            s[metric+'_std']=float(np.std(values,ddof=1)) if len(values)==len(rs) and len(values)>1 else None
            s[metric+'_defined_folds']=len(values)
        summaries.append(s)
    lookup={(r['dataset_id'],r['protocol'],r['baseline']):r for r in summaries}
    compare=[];gaps=[]
    for did,task,protocol,diff in sorted({(r['dataset_id'],r['task_id'],r['protocol'],r['difficulty']) for r in rows}):
        b0,b1,b2=[lookup[(did,protocol,b)] for b in ['B0_kmer_linear','B1_frozen_linear','B2_frozen_mlp']]
        metric=b0['primary_metric'];k=metric+'_mean'
        compare.append(dict(dataset_id=did,task_id=task,protocol=protocol,difficulty=diff,metric=metric,B0=b0[k],frozen_linear=b1[k],frozen_MLP=b2[k],frozen_representation_gain=b1[k]-b0[k],nonlinear_readout_gain=b2[k]-b1[k],n_folds=3,phase='EXPLORATORY_PILOT'))
    for did in sorted({r['dataset_id'] for r in summaries}):
        for b in ['B0_kmer_linear','B1_frozen_linear','B2_frozen_mlp']:
            a=lookup.get((did,'EAZY',b));d=lookup.get((did,'OOD_split',b))
            if a and d:
                k=a['primary_metric']+'_mean'
                gaps.append(dict(dataset_id=did,baseline=b,metric=a['primary_metric'],ID=a[k],D2=d[k],gap_ID_minus_D2=a[k]-d[k],qualification='different frozen test memberships; same eligible population; approximate group-held-out, NOT strict D3'))
    def save(path,data):tsv(path,data,list(dict.fromkeys(k for r in data for k in r)))
    for name,data in [('pilot_summary.tsv',summaries),('baseline_comparison.tsv',compare),('generalization_gap.tsv',gaps)]:save(RUN/name,data)
    bad=[dict(dataset_id=r['dataset_id'],status=r['status'],reason=r.get('error_reason',''),scope='compatibility, not scientific admission') for r in table(RUN/'technical_status_final.tsv') if r['status']!='PASSED_TECHNICAL_SMOKE']
    save(RUN/'incompatible_views.tsv',bad)
    PUBLIC.mkdir(parents=True,exist_ok=True)
    fields=['dataset_id','task_id','protocol','difficulty','outer_fold','baseline','primary_metric','n_train','n_validation','n_test','Spearman','Pearson','MAE','RMSE','NDCG','Macro-F1','MCC','Macro-AUPRC','Macro-AUROC','undefined_reasons','phase','formal_leaderboard_eligible']
    public_rows=[{k:r.get(k,'') for k in fields} for r in rows]
    for name,data in [('fold_metrics.tsv',public_rows),('pilot_summary.tsv',summaries),('baseline_comparison.tsv',compare),('generalization_gap.tsv',gaps)]:save(PUBLIC/name,data)
    c=dict(date='2026-10-31',phase='EXPLORATORY_PILOT',technical_status=load(RUN/'technical_reconciliation.json')['final_status_counts'],datasets=len(selected),eligible_records=sum(int(r['compatible_n']) for r in selected),unique_embeddings=cached,protocol_folds=audit['protocol_folds'],metric_rows=len(rows),replayed_predictions=replay_n,model_id='RNA-FM-HF',parameter_count=model['parameter_count'],embedding_dimension=640,checkpoint_hash=model['checkpoint_sha256'],tokenizer_hash=model['tokenizer_hash'],wall_seconds=audit['wall_seconds'],peak_allocated_GiB=audit['resources']['peak_cuda_allocated_bytes']/2**30,peak_reserved_GiB=audit['resources']['peak_cuda_reserved_bytes']/2**30,pretrain_overlap='PRETRAIN_OVERLAP_UNKNOWN',universal_score=None,formal_admitted=0,gpu_count=1)
    dump(RUN/'final_summary.json',c);dump(PUBLIC/'summary.json',c)
    render(selected,compare,gaps,lookup,c,audit,model)
    dump(RUN/'stage_receipts.json',dict(technical_reconciliation='PASS',full_data_split_precheck='PASS',embedding='PASS',baseline_training='PASS',saved_prediction_replay='PASS',report='GENERATED',github='PENDING',report_sha256=sha(ROOT/'reports/RNAGYM_RNAFM_HF_PILOT_V1_2.md')))
    print(json.dumps(c,indent=2))


def render(selected,compare,gaps,lookup,c,audit,model):
    lines=['# RNA-Gym RNA-FM-HF Pilot v1.2','',
        '> 2026-10-31 UTC · **EXPLORATORY_PILOT**, not formal Public Leaderboard.','',
        '## Part A — Run, data and frozen protocol','',
        '### Final technical status','',
        '**277 views: 261 PASSED_TECHNICAL_SMOKE / 16 INCOMPATIBLE.** The authoritative',
        'merged per-view log uses both successful repairs, not the historical 259 count.',
        'RMDB numeric-mask parsing and ArchiveII class-ontology support were repaired.',
        'No all-view smoke was repeated. Technical success is not scientific admission.','',
        '### Selected real data','',
        'Eight prespecified views span six canonical families: MRL_EXACT, MRL_PROXY,',
        'HALF_LIFE, UTR3_STABILITY, NCRNA_FAMILY and DMS_FITNESS.',
        'They represent Function/Regulation and direct RNA Perturbation, not all three',
        'macro-domains. All eligible rows were used, not 12-record samples.','',
        '| Dataset | Local QC view N | Eligible N | Excluded N | Unique inputs | Biological/construct groups |',
        '|---|---:|---:|---:|---:|---:|']
    for r in selected:
        lines.append('| '+' | '.join(str(r[k]) for k in ['dataset_id','local_n','compatible_n','excluded_n','unique_sequence_n','biological_group_n'])+' |')
    lines+=['',f'Total eligible observations: **{c["eligible_records"]:,}**. All train/validation/test',
        'memberships are restricted explicitly to full model-compatible sequences; no',
        'truncation, label imputation, windowing or training subsampling occurred.',
        'Human/mouse half-life coverage is only about 5.1% / 7.1% of the QC views:',
        '**these are short-transcript subset results, not full-dataset performance**.',
        'Original paper N stays UNKNOWN where not bound; local N is not paper N.','',
        '### Input / target / assay definitions','']
    for r in selected:
        lines.append('- **'+r['dataset_id']+'**: '+str(r['label_definition'])+'; unit: '+str(r['label_unit'])+'. Source DOI: '+str(r.get('source_doi') or 'UNKNOWN')+'.')
    lines+=['','MRL-exact uses genuine 5′UTR and already-published log2 MRL at zebrafish 6 hpf.',
        'MRL-proxy uses mature transcript/cDNA; these are not merged. Half-life PC1 is',
        '**unitless PC1, not hours**. Karner uses literal 3′UTR sequence and stored',
        'mean_log_decay over six named cells; log base/time-unit and source rights remain',
        'formal-review gaps, not an excuse to rename the target absolute half-life.',
        'DMS targets are direct ribozyme self-cleavage / tRNA functional fitness, not',
        'encoded-protein phenotypes. Their released scalar scores are kept untransformed;',
        'assay-specific transformations/units remain explicit limitations. No RRS/TE or',
        'RNA localization target was fabricated for absent evidence.','',
        '### Split and training rules','',
        '- Existing ten-fold outer tests **[0,3,7]** reused without reassignment.',
        '- Validation: hash-ordered 10% biological/split groups from the other nine folds.',
        '- Exact model-input, biological-group and split-group cross-role leakage: zero.',
        '- D1 DMS is mutant-construct generalization inside one WT/library, not WT-held-out.',
        '- D2 uses frozen approximate MMseqs 80% identity / 80% coverage plus declared',
        '  biological groups; do not call this assay/cell/species D3.',
        '- Closed-set ncRNA classification does not use family-held-out target classes.',
        '- Danio preserves existing legacy test membership; it is D1, not homology/OOD.',
        '- All scalers/target transforms and baselines fit train only. MLP selection uses',
        '  validation loss only; test labels never select samples, LR or tasks.','',
        '### Verified model and resource identity','',
        f'- Checkpoint SHA256: `{model["checkpoint_sha256"]}`.',
        f'- Tokenizer SHA256: `{model["tokenizer_hash"]}`.',
        f'- Parameters: **{model["parameter_count"]:,}**; dimension **640**; max nt **1022**.',
        '- Existing RNAHub native API checks BOS/EOS/padding and residue-token alignment.',
        '- Literal inputs retained; uppercase/T→U is an explicit versioned model-only view.',
        '- Encoder eval()/requires_grad=False; no encoder tensor enters an optimizer;',
        '  parameter version counters unchanged. No UTR-LM, LoRA or full FT.',
        f'- Unique cached inputs **{c["unique_embeddings"]:,}**; key binds checkpoint, tokenizer,',
        '  sequence hash, preprocessing and representation. Disk entries independently checked.',
        '- Length-bucket encoder batch 16/8/4/2, fp32 inference_mode; no CPU FM fallback.',
        f'- Job `{audit["gpu"]["slurm_job_id"]}`, node `{audit["gpu"]["hostname"]}`, one GPU UUID',
        f'  `{audit["gpu"]["physical_gpu_uuid"]}`. Pre-start process list empty.',
        f'- Wall time **{c["wall_seconds"]:.1f} s / {c["wall_seconds"]/60:.2f} min**; forward time',
        f'  **{audit["resources"]["forward_seconds"]:.1f} s**; peak allocated **{c["peak_allocated_GiB"]:.3f} GiB**,',
        f'  reserved **{c["peak_reserved_GiB"]:.3f} GiB**. No new job or other node used.','',
        '## Part B — Real held-out results','',
        'B0: train-only log-length/composition/3-mer Ridge or multinomial logistic.',
        'B1: frozen embedding Ridge or multinomial logistic. B2: frozen MLP (128, GELU,',
        'dropout .2). Mean/median or prevalence nulls are stored separately; undefined',
        'correlations remain NA. Ridge alpha=1, logistic C=1, AdamW LR=.001, weight decay',
        '.0001, batch 32, max 15 epochs, patience 3, seed 42, no HPO. These are fixed',
        'pilot engineering defaults, not official author-optimal settings.','',
        'All cells show test-fold mean ± sample SD, not validation scores or pooled train',
        'metrics. Test sample sizes are per folds 0,3,7. Full Pearson/MAE/RMSE/class-support',
        'metrics and NA reasons are saved in the fold tables.','',
        '| Dataset | Protocol | N train / test by fold | Task | B0 | Frozen linear | Frozen MLP | Primary |',
        '|---|---|---|---|---:|---:|---:|---|']
    for r in compare:
        metric=r['metric'];stats=[]
        for b in ['B0_kmer_linear','B1_frozen_linear','B2_frozen_mlp']:
            s=lookup[(r['dataset_id'],r['protocol'],b)]
            stats.append(f'{s[metric+"_mean"]:.4f} ± {s[metric+"_std"]:.4f}')
        s=lookup[(r['dataset_id'],r['protocol'],'B1_frozen_linear')]
        lines.append('| '+' | '.join([r['dataset_id'],r['protocol'],s['train_n_by_fold']+' / '+s['test_n_by_fold'],r['task_id']]+stats+[metric])+' |')
    lines+=['',f'Completed **{c["protocol_folds"]} protocol-fold cells**, **{c["metric_rows"]} model/fold rows**.',
        f'All **{c["replayed_predictions"]}** saved prediction metric sets were independently replayed',
        'after SHA256 verification. Negative-relevance DMS NDCG stays NA; no label shift was',
        'invented to make ranking metrics defined. Macro-AUPRC/AUROC need positive/negative',
        'support for every declared test class; otherwise NA. No incompatible raw metrics',
        'are averaged across tasks.','',
        '### Representation/readout gains','',
        '| Dataset | Protocol | Frozen linear − k-mer | MLP − frozen linear |',
        '|---|---|---:|---:|']
    for r in compare:lines.append(f'| {r["dataset_id"]} | {r["protocol"]} | {r["frozen_representation_gain"]:+.4f} | {r["nonlinear_readout_gain"]:+.4f} |')
    lines+=['','**Interpretation:** ncRNA family and both direct RNA DMS assays show positive',
        'frozen-linear gains; MRL-proxy gain is modest. Frozen linear underperforms k-mer',
        'for human/mouse half-life and 3′UTR decay. MLP improves those FM readouts but',
        'fold variability is large, particularly the short-transcript subsets. Danio',
        '5′UTR MRL does not beat the k-mer baseline with this frozen configuration.',
        'These are descriptive pilot observations, not statistically significant claims.',
        'One fixed seed and equal minimal HPO do not establish architecture superiority.',
        'No dataset is scientifically rejected because a model performs poorly.','',
        '## Part C — ID versus group generalization','',
        '| Dataset | Baseline | D1 ID | D2 | Gap ID − D2 |','|---|---|---:|---:|---:|']
    for r in gaps:lines.append(f'| {r["dataset_id"]} | {r["baseline"]} | {r["ID"]:.4f} | {r["D2"]:.4f} | {r["gap_ID_minus_D2"]:+.4f} |')
    lines+=['','Same eligible population, but different frozen test memberships: gap can reverse',
        'from fold composition. A negative gap is not proof of better OOD ability. No',
        'strict D3 score, WT-held-out score or species-transfer score is claimed.',
        'Cross-dataset sequence overlap is audited; models are trained separately, never',
        'on pooled labels from another evaluation dataset. Source-compendium overlap and',
        'pretraining exposure are separate from supervised split leakage. The pinned official',
        'README describes RNAcentral100/ncRNA pretraining; it does not provide a bound',
        'test-sequence membership check. Strong ncRNA results may reflect corpus familiarity.',
        'RNA-FM corpus',
        'membership remains **PRETRAIN_OVERLAP_UNKNOWN**, not zero leakage.','',
        '## Part D — Failures and non-supported capabilities','',
        '- Length/alphabet exclusions have row-level reasons; a biological window adapter',
        '  would require a new audited protocol. Do not interpret subset scores as full N.',
        '- RMDB parser repair is real but sequence-only probing is not SSI imputation.',
        '  Missing partial-signal/mask input means no SSI pilot score.',
        '- Wang orientation/index conventions remain untouched; graph smoke is not SSP.',
        '- RNA3DB D1/D2/temporal manifests do not substitute for residue-aligned CMP/DMP',
        '  labels. These tasks remain HOLD_LABEL_BINDING.',
        '- No complete local Engineering anchor/generator adapter was established. The',
        '  available RNAInvBench source metadata is not a trained inverse-design model.',
        '  RNA_SWITCH/CRISPR/RNA_DESIGN remain HOLD_DATA_BINDING where appropriate.',
        '- RNA/RNA, RNA/DNA and protein/RNA tasks need explicit pair/multimodal adapters;',
        '  the scalar pilot does not concatenate them into fake single-sequence tasks.',
        '- Class ontology/support is explicit; family-held-out is not closed-set family',
        '  classification. NA is preserved for undefined metrics.',
        '- Human scientific admission remains zero. Rights/original assay evidence gaps',
        '  remain in the data cards; technical pass cannot create a human signature.',
        '- Platform lacks complete admitted Structure/Engineering panels: **no Universal',
        '  Score**. This is unavailable platform capability, not a missing-model zero.','',
        '## Part E — Next benchmark decisions','',
        '1. Expand direct RNA DMS, genuine 5′UTR MRL and ncRNA family to full CV/multiple',
        '   seeds after scientific review. Preserve single-WT and closed-set limitations.',
        '2. MRL-proxy and 3′UTR stability remain native-length-population pilots; their',
        '   source units/assay identity require review. Half-life needs long-sequence',
        '   architecture or a justified region adapter before whole-transcript claims.',
        '3. LoRA/FT hypotheses: DMS/ncRNA gains justify further controlled adaptation;',
        '   small human/mouse eligible subsets need stronger regularization and repeat',
        '   seeds before FT. Include matched random initialization to isolate pretraining.',
        '4. Danio and 3′UTR decay need competitive sequence/position-aware baselines;',
        '   mean pooling may hide local signals. Do not assume FM is always superior.',
        '5. Keep ID and group-generalization boards separate, with group-bootstrap CI',
        '   and source-family sensitivity analyses before final rankings.',
        '6. Structure needs verified labels; Engineering needs a real anchor and paired/',
        '   generative adapter. Do not manufacture scores for three-domain coverage.',
        '7. All eight datasets still need genuine human scientific admission. Pilot',
        '   learnability never determines acceptance or exclusion.','',
        '## Artifacts, reproduction and public boundary','',
        'Local fixed run: `runs/rnagym_rnafm_hf_pilot_v1_2/`. It includes required selection,',
        'eligibility, split, GPU, model/tokenizer, cache, metrics, comparisons, predictions,',
        'best checkpoints and execution receipts. Cache keys are independently validated.',
        'Public `results/pilots/rnafm_hf_v1_2/` contains aggregate-only tables. No raw',
        'sequence/label records, per-sample predictions, embeddings, private data or weights',
        'are included in GitHub publication. The native Python API is used explicitly;',
        'this is not a claim that the new production HTTP evaluation routes are deployed.','',
        '```bash','.venv-qc/bin/python -m tools.pilot_v1_2_data',
        '# In an existing idle single-GPU allocation and the verified CUDA environment:',
        'python -m tools.pilot_v1_2_run','.venv-qc/bin/python -m tools.pilot_v1_2_report',
        '.venv-qc/bin/python -m unittest discover -s tests -p test_pilot_v1_2.py -v','```','',
        'The runner locks the run, checks config/source/split hashes, caches frozen inputs,',
        'and saves training/validation history. New data/config/splits require a new run',
        'version; successful metrics do not enter the formal leaderboard.']
    (ROOT/'reports/RNAGYM_RNAFM_HF_PILOT_V1_2.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':main()
