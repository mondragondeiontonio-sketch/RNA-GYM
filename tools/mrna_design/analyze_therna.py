"""Local-only sensitivity analyses. No replicate or causal claims are inferred."""
import argparse
import itertools
from pathlib import Path
from collections import defaultdict
import random
from rna_gym.research_v06.provenance import (ProtocolError, read_json, write_immutable,
                                            digest_json, sha256_file, receipt)
from rna_gym.research_v06.therna import iter_long
from rna_gym.research_v06.baselines import run_baselines
from rna_gym.research_v06.splits import make_split


def rank_diagnostics(rows, seed=6):
    import numpy as np
    from scipy.stats import spearmanr, kendalltau
    by_sequence=defaultdict(dict)
    for r in rows:
        if r['missing_reason']!='NOT_MISSING':continue
        if r['cell_id'] in by_sequence[r['sequence_id']]:
            raise ProtocolError('RANK_DIAGNOSTICS_REQUIRES_SINGLE_TIME_PER_CELL')
        by_sequence[r['sequence_id']][r['cell_id']]=float(r['label_raw'])
    cells=sorted({r['cell_id'] for r in rows})
    complete=[v for v in by_sequence.values() if set(v)==set(cells)]
    matrix=np.array([[r[c] for c in cells] for r in complete]);rng=np.random.default_rng(seed)
    results=[]
    for i,j in itertools.combinations(range(len(cells)),2):
        x,y=matrix[:,i],matrix[:,j]
        corr=float(spearmanr(x,y).statistic)
        draws=[float(spearmanr(x[idx],y[idx]).statistic) for idx in
               (rng.integers(0,len(x),len(x)) for _ in range(200))]
        k=max(1,int(len(x)*.1));a=set(np.argsort(x)[-k:]);b=set(np.argsort(y)[-k:])
        sensitivity={}
        for fraction in (.01,.05,.1):
            xx=x+rng.normal(0,fraction*np.subtract(*np.quantile(x,[.75,.25])),len(x))
            yy=y+rng.normal(0,fraction*np.subtract(*np.quantile(y,[.75,.25])),len(y))
            sensitivity[str(fraction)]=float(spearmanr(xx,yy).statistic)
        tau=float(kendalltau(x,y).statistic)
        results.append({'cells':[cells[i],cells[j]],'complete_sequences':len(x),'spearman':corr,
            'conditional_sequence_ci95':np.quantile(draws,[.025,.975]).tolist(),
            'kendall_tau_b':tau,'discordance_proxy':(1-tau)/2,
            'discordance_note':'TAU_B_PROXY_NOT_EXACT_TIE_ADJUSTED_PAIR_FRACTION',
            'top_decile_jaccard':len(a&b)/len(a|b),'IQR_noise_sensitivity':sensitivity})
    return {'pairs':results,'biological_replicates':'NOT_AVAILABLE',
            'null_noise_calibration':'NOT_IDENTIFIABLE_SENSITIVITY_IS_NOT_MEASUREMENT_ERROR',
            'evidence_grade':'PRELIMINARY_SIGNAL_NOT_CAUSAL','seed':seed}


def analyze(long_path, config, out):
    rows=list(iter_long(long_path));out=Path(out);out.mkdir(parents=True,exist_ok=True)
    assignment,manifest=make_split(rows,protocol='S-OUT',seed=config['seed'])
    base_predictions,base=run_baselines(rows,assignment,manifest,config)
    permutation_config=dict(config,negative_control='TRAIN_CELL_PERMUTATION')
    _,permuted=run_baselines(rows,assignment,manifest,permutation_config)
    shuffle_config=dict(config,negative_control='MONONUCLEOTIDE_SHUFFLE')
    _,shuffled=run_baselines(rows,assignment,manifest,shuffle_config)
    rank=rank_diagnostics(rows,config['seed'])
    # Explicit null-control experiment on a synthetic additive panel, not scientific observations.
    from rna_gym.research_v06.fixtures import additive_panel
    null_rows=additive_panel();a,m=make_split(null_rows,seed=config['seed'])
    _,null=run_baselines(null_rows,a,m,config)
    result={'schema':'rnagym.research_v06.local_analysis.v1','raw_long_sha256':sha256_file(long_path),
            'baseline':base,'cell_identity_permutation':permuted,'mononucleotide_shuffle':shuffled,
            'additive_synthetic_null':null,'rank_diagnostics':rank,
            'scope':'EXPLORATORY_LOCAL_ONLY_NOT_SCIENTIFIC_ADMISSION',
            'confounders':['UNAVAILABLE_REPLICATES','UNVERIFIED_DECAY_UNIT_AND_FIT',
                          'THREE_METADATA_SELECTED_CELLS','EXACT_GROUPS_NOT_HOMOLOGY',
                          'SINGLE_TRAINING_SEED','AUTHOR_NORMALIZATION_NOT_REVIEWED']}
    write_immutable(out/'analysis.private.json',result)
    receipt(out,'exploratory_controls',{'long_sha256':sha256_file(long_path),'config':config},
            [out/'analysis.private.json'],{'real_cells':3,'new_gpu_hours':0})
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    analyze(a.input,read_json(a.config),a.out)
    print('EXPLORATORY_LOCAL_ANALYSIS_COMPLETE_NOT_FORMAL')


if __name__=='__main__':main()
