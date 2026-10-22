#!/usr/bin/env python3
"""Bounded, streaming file-level row census, not full scientific QC or admission.

Parquet counts are read from footer metadata. Gzip TSV/CSV records are actually
parsed with a decompression budget. No sequences/measurements are exported.
"""
import argparse
import collections
import csv
import gzip
import json
from pathlib import Path

from rnagym import ROOT, StateDB, get_target, immutable_json, read_manifest, sha256


def count_gzip(path, max_expanded):
    expanded=0
    with gzip.open(path,'rt',encoding='utf-8-sig',newline='') as f:
        def lines():
            nonlocal expanded
            while True:
                line=f.readline(1024*1024+1)
                if not line:break
                if len(line)>1024*1024:raise ValueError('decompressed line cap')
                expanded+=len(line.encode())
                if expanded>max_expanded:raise ValueError('decompression cap')
                yield line
        reader=csv.DictReader(lines(),delimiter='\t' if '.tsv' in path.name else ',')
        fields=reader.fieldnames or []
        n=0;labels=collections.Counter();invalid_pairs=0
        paired={'gene','noncodingRNA','label'}.issubset(fields)
        for row in reader:
            n+=1
            if paired:
                labels[row['label']]+=1
                if not row['gene'] or not row['noncodingRNA'] or not set(row['gene']+row['noncodingRNA'])<=set('ACGTUN'):
                    invalid_pairs+=1
        return {'actual_n':n,'schema_columns':fields,'parse_method':'STREAMED_CSV_RECORDS',
                'expanded_bytes_read':expanded,'paired_schema':paired,
                'label_distribution':dict(labels),'invalid_pair_alphabet_rows':invalid_pairs,
                'sequence_transform':'NONE'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',required=True,type=Path)
    p.add_argument('--max-expanded-gb',type=int,default=8)
    args=p.parse_args()
    rows={}
    for name in ['p0_assets.csv','licensed_small_batch.csv']:
        path=ROOT/'data/audit'/name
        if path.exists():rows.update(read_manifest(path))
    result=[]
    with StateDB(ROOT/'run-state.sqlite') as db:
        for aid,row in rows.items():
            path=get_target(row,ROOT/'raw_cache')
            if not path.is_file() or path.suffix not in ('.gz','.parquet'):continue
            if not (path.parent/'provenance.json').is_file():
                print(json.dumps({'asset_id':aid,'state':'SKIP_NOT_YET_HASH_VERIFIED'}),flush=True)
                continue
            digest=sha256(path)
            if digest!=path.parent.name:raise ValueError('raw hash mismatch')
            checkpoint=args.run/'reports'/('file_count-'+digest+'.json')
            if checkpoint.exists():doc=json.loads(checkpoint.read_text())
            else:
                if path.suffix=='.parquet':
                    import pyarrow.parquet as pq
                    f=pq.ParquetFile(path)
                    info={'actual_n':f.metadata.num_rows,'schema_columns':f.schema.names,
                          'parse_method':'PARQUET_FOOTER_METADATA_ONLY'}
                else:info=count_gzip(path,args.max_expanded_gb*1024**3)
                doc={'asset_id':aid,'package_group_id':row['package_group_id'],
                     'source_sha256':digest,'actual_n_scope':'ONE_FILE_NOT_ASSAY_OR_TASK_N',
                     'state':'FILE_SCHEMA_AND_COUNT_ONLY','admission_gate_pass':False,
                     'assay_identity_verified':False,'admitted':False,**info}
                immutable_json(checkpoint,doc)
            result.append(doc)
            key=db.ensure(row)
            if db.job(key)['stage']=='HASHED':db.transition(key,'PARSED',evidence=[str(checkpoint)],detail={'scope':'FILE_SCHEMA_AND_COUNT_ONLY','actual_n':doc['actual_n']})
            print(json.dumps({'asset_id':aid,'actual_n':doc['actual_n'],'scope':doc['actual_n_scope'],'state':'PARSED_NOT_ADMITTED'}),flush=True)
    (ROOT/'data/audit/downloaded_file_counts.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'file_count':len(result),'admitted':0}),flush=True)


if __name__=='__main__':main()
