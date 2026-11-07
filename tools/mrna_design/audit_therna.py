"""Descriptive long-table QC; never fits prediction-time target-derived features."""
import argparse
from pathlib import Path
from collections import defaultdict, Counter
from rna_gym.research_v06.therna import iter_long
from rna_gym.research_v06.provenance import (ProtocolError,write_immutable,write_table,
                                            sha256_file,receipt)


def audit(path,out):
    import numpy as np
    from scipy.stats import spearmanr
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    values=defaultdict(list);coverage=defaultdict(Counter);sequences={}
    for row in iter_long(path):
        sequence=row['sequence'];sid=row['sequence_id'];missing=row['missing_reason']!='NOT_MISSING'
        length=len(sequence);gc=(sequence.count('G')+sequence.count('C'))/length
        state=sequences.setdefault(sid,{'length':length,'GC':gc,'total':0,'missing':0})
        state['total']+=1;state['missing']+=missing
        key=(row['cell_id'],row['timepoint_value'])
        coverage[key]['total']+=1;coverage[key]['missing']+=missing
        if not missing:values[key].append(float(row['label_raw']))
    rows=[]
    for (cell,time),counts in sorted(coverage.items()):
        y=np.array(values[(cell,time)])
        rows.append({'cell_id':cell,'timepoint':time,'n_observations':counts['total'],
          'missing_n':counts['missing'],'valid_n':len(y),'zero_n':int(sum(y==0)),
          'negative_n':int(sum(y<0)),'mean':float(y.mean()) if len(y) else None,
          'std_population':float(y.std()) if len(y) else None,
          'quantiles_01_25_50_75_99':','.join(map(str,np.quantile(y,[.01,.25,.5,.75,.99]))) if len(y) else '',
          'replicate_uncertainty':'NOT_IDENTIFIABLE','batch':'NOT_REPORTED'})
    fraction=np.array([s['missing']/s['total'] for s in sequences.values()])
    association={}
    for feature in ('length','GC'):
        x=np.array([s[feature] for s in sequences.values()])
        association[feature]={'min':float(x.min()),'max':float(x.max()),
          'missingness_spearman_descriptive':float(spearmanr(x,fraction).statistic)
           if np.ptp(x)>0 and np.ptp(fraction)>0 else None}
    write_table(out/'coverage_and_dynamic_range.private.tsv',rows)
    summary={'unique_sequences':len(sequences),'cell_time_groups':len(rows),
      'sequence_feature_missingness':association,
      'sequence_qc':'DESCRIPTIVE_ONLY_NOT_MODEL_INPUT_FITTING',
      'replicates':'NOT_AVAILABLE_NO_TECHNICAL_VARIANCE_ESTIMATED',
      'dna_t0':'NOT_USED_AS_SEQUENCE_FEATURE',
      'low_count_strata':'NOT_IDENTIFIABLE_WITHOUT_BOUND_RAW_COUNT_METADATA',
      'batch_confounding':'NOT_IDENTIFIABLE_FROM_AGGREGATE_RELEASE'}
    write_immutable(out/'qc_summary.private.json',summary)
    receipt(out,'therna_descriptive_qc',{'long_sha256':sha256_file(path)},
       [out/'coverage_and_dynamic_range.private.tsv',out/'qc_summary.private.json'],
       {'unique_sequences':len(sequences),'cell_time_groups':len(rows)})
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args();print(audit(a.input,a.out))


if __name__=='__main__':main()
