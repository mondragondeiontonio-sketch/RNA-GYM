"""Rebuild only an UNFROZEN unit's split from its verified curated bytes."""
import argparse
import json
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
from .core import ROOT,RUN,VERSION,file_sha,write_json,sha,capture_producer
from .splits import build_splits


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--unit',required=True);p.add_argument('--linear',action='store_true')
    args=p.parse_args();capture_producer()
    directory=ROOT/'data/processed'/args.unit/VERSION
    if (directory/'freeze.json').exists():raise ValueError('CANNOT_REBUILD_FROZEN_VERSION')
    report=json.loads((directory/'qc_report.json').read_text());curated=directory/'curated_data.parquet'
    if file_sha(curated)!=report['output_sha256']:raise ValueError('CURATED_HASH_MISMATCH')
    records=[]
    from .sources import _probing_vector,probing_jobs
    from .core import assets
    spec=next(s for s,_ in probing_jobs(assets()) if s['unit_id']==args.unit)
    if args.linear:
        old=directory/'splits/clustering'
        previous=RUN/(args.unit+'_regular_search_attempt')
        if old.exists() and not previous.exists():old.rename(previous)
    for batch in pq.ParquetFile(curated).iter_batches(batch_size=512):
        for r in batch.to_pylist():
            label=json.loads(r['label_json']);values=[]
            if report['modality']=='probing':
                a=_probing_vector(label['reactivity']);valid=np.isfinite(a)&(a!=-999.)
                if valid.any():values=[float(a[valid].mean())]
            records.append({'record_id':r['record_id'],'observation_id':r['observation_id'],
                'input_hash':r['input_hash'],'sequence':r['sequence'],'sequence_b':r['sequence_b'],
                'sequence_model_view':r.get('sequence_model_view') or r['sequence'],
                'sequence_b_kind':r.get('sequence_b_kind','rna'),
                'group_metadata':json.loads(r['group_metadata_json']),
                'finite_labels':values,'label':None})
    print(json.dumps({'unit':args.unit,'records_reused_without_raw_rescan':len(records)}),flush=True)
    mmseqs=ROOT/json.loads((ROOT/'configs/scientific_curation.json').read_text())['mmseqs']
    split=build_splits(records,directory/'splits',mmseqs,linear=args.linear)
    report.update(split=split['protocols'],clustering_algorithm='easy-linclust' if args.linear else 'easy-cluster')
    write_json(directory/'qc_report.json',report)
    provenance=json.loads((directory/'provenance.json').read_text())
    provenance['specification']=spec
    provenance['split_reconstruction']={'from_curated_sha256':report['output_sha256'],'raw_rescanned':False,
        'algorithm':report['clustering_algorithm'],'code_sha256':file_sha(Path(__file__)),
        'split_manifest_sha256':split['split_manifest_sha256']}
    for f in ['qc_report.json','splits/split_manifest.parquet','splits/split_summary.json','splits/leakage_report.json']:
        provenance['output_files'][f]=file_sha(directory/f)
    write_json(directory/'provenance.json',provenance)
    completion=json.loads((directory/'complete.json').read_text());completion['spec_sha256']=sha(spec)
    write_json(directory/'complete.json',completion)
    if (directory/'failure.json').exists():(directory/'failure.json').rename(RUN/(args.unit+'_historical_import_failure.json'))
    print(json.dumps({k:v['status'] for k,v in split['protocols'].items()}),flush=True)

if __name__=='__main__':main()
