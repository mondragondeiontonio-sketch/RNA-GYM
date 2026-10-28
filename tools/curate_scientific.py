#!/usr/bin/env python3
"""Curate actual acquired data and construct independent EAZY / OOD_split.

Usage: .venv-qc/bin/python -m tools.curate_scientific --modalities mrna dms
"""
import argparse
import json
import traceback
from pathlib import Path
from tools.curation.core import ROOT,RUN,VERSION,Curator,assets,inventory,write_json,sha,capture_producer,file_sha
from tools.curation import sources


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--modalities',nargs='+',default=['mrna','dms','paired','euka','probing','structure','wang'])
    p.add_argument('--limit',type=int)
    p.add_argument('--skip-splits',action='store_true')
    p.add_argument('--refresh-unit',nargs='*',default=[])
    p.add_argument('--units',nargs='*',default=[])
    args=p.parse_args()
    RUN.mkdir(parents=True,exist_ok=True)
    capture_producer()
    all_assets=assets()
    inv=inventory(all_assets)
    config=json.loads((ROOT/'configs/scientific_curation.json').read_text())
    mmseqs=ROOT/config['mmseqs']
    n=0; failures=[]
    for modality in args.modalities:
        get_jobs=getattr(sources,modality+'_jobs',None)
        if get_jobs is None:
            failures.append({'modality':modality,'error':'ADAPTER_NOT_IMPLEMENTED'});continue
        for spec,rows in get_jobs(all_assets):
            if args.units and spec['unit_id'] not in args.units:continue
            done=ROOT/'data/processed'/spec['unit_id']/VERSION/'complete.json'
            if done.exists() and spec['unit_id'] not in args.refresh_unit:
                saved=json.loads(done.read_text())
                if saved['curated_sha256']!=file_sha(done.parent/'curated_data.parquet'):
                    raise ValueError('CURATED_OUTPUT_HASH_CHANGED:'+spec['unit_id'])
                if saved['spec_sha256']!=sha(spec):
                    raise ValueError('SPEC_CHANGED_AFTER_COMPLETION:'+spec['unit_id'])
                print(json.dumps({'unit':spec['unit_id'],'state':'REUSED_CURATED_OUTPUT'}),flush=True)
                continue
            try:
                curator=Curator(spec,all_assets)
                for i,items in enumerate(rows(),1):
                    row,aid,index,member,split=items
                    curator.add(row,aid,index,member,split)
                    if i%100000==0:
                        print(json.dumps({'unit':spec['unit_id'],'scanned':i}),flush=True)
                print(json.dumps({'unit':spec['unit_id'],'state':'QC_DONE','actual_n':curator.actual_n}),flush=True)
                report=curator.finish(mmseqs,do_splits=not args.skip_splits)
                print(json.dumps({'unit':spec['unit_id'],'state':'SPLIT_DONE','valid_n':report['valid_n'],
                                  'splits':{k:v['status'] for k,v in report['split'].items()}}),flush=True)
                del curator
            except Exception as exc:
                failure={'unit':spec['unit_id'],'modality':modality,'error':str(exc),'traceback':traceback.format_exc()}
                failures.append(failure)
                write_json(ROOT/'data/processed'/spec['unit_id']/VERSION/'failure.json',failure)
                print(json.dumps({'unit':spec['unit_id'],'state':'FAILED','error':str(exc)}),flush=True)
            n+=1
            if args.limit and n>=args.limit:break
        if args.limit and n>=args.limit:break
    write_json(RUN/('execution_'+'_'.join(args.modalities)+'.json'),{'processed_this_call':n,'failures':failures,'inventory_assets':len(inv)})

if __name__=='__main__':main()
