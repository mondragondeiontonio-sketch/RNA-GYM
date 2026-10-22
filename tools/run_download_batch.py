#!/usr/bin/env python3
"""Execute an explicit finite queue, with transfer caps and independent failures.

Two worker processes at most. Downloads remain quarantine; this orchestrator
never approves original assays or writes human reviewer fields.
"""
import argparse
import concurrent.futures
import datetime
import json
import math
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

from rnagym import ROOT, StateDB, get_target, immutable_json, read_manifest, sha256


def execute_one(row, manifest, run, max_mb):
    aid=row['asset_id']
    log=run/'logs'/('download-'+aid+'.log')
    cmd=[sys.executable,str(ROOT/'tools/rnagym.py'),'download','--manifest',str(manifest),
         '--asset',aid,'--execute','--allow-unpinned','--max-mb',str(max_mb),
         '--rate-kbps','8192','--retries','2','--out',str(ROOT/'raw_cache')]
    with log.open('a') as f:
        p=subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
        code=p.returncode
        if code==0:
            p=subprocess.run([sys.executable,str(ROOT/'tools/rnagym.py'),'verify',
               '--manifest',str(manifest),'--asset',aid,'--out',str(ROOT/'raw_cache')],
               cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
            code=p.returncode
    target=get_target(row,ROOT/'raw_cache')
    result={'asset_id':aid,'package_group_id':row['package_group_id'],'exit_code':code,
        'log':str(log.relative_to(ROOT)),'state':'HASHED_QUARANTINED' if code==0 else 'HOLD_DOWNLOAD',
        'sha256':sha256(target) if code==0 and target.is_file() else None,
        'bytes':target.stat().st_size if code==0 and target.is_file() else None,'admitted':False}
    history=run/'reports'/('download-'+aid+'-'+hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()[:12]+'.json')
    immutable_json(history,result)
    (run/'reports'/('download-'+aid+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--probe-snapshot',type=Path,required=True)
    p.add_argument('--execute',action='store_true')
    a=p.parse_args()
    if not a.execute:p.error('explicit --execute required')
    run=a.run.resolve();manifest=a.manifest.resolve()
    rows=list(read_manifest(manifest).values())
    snapshots=json.loads(a.probe_snapshot.read_text())['results']
    sizes={r['url']:r.get('size_bytes') for r in snapshots if r.get('http_status')==200}
    pending=[]
    for r in rows:
        size=sizes.get(r['direct_url'])
        if size is None or size<=0 or size>3*1024**3:
            raise ValueError('fresh known size <=3GiB required: '+r['asset_id'])
        pending.append((r,math.ceil(size/1024**2)+1))
    total=sum(sizes[r['direct_url']] for r,_ in pending)
    if total>12*1024**3:raise ValueError('12GiB batch cap exceeded')
    if shutil.disk_usage(ROOT).free<total+20*1024**3:raise OSError('20GiB reserve plus queue bytes required')
    print(json.dumps({'stage':'FINITE_QUEUE_START','asset_count':len(rows),
        'declared_total_bytes':total,'worker_count':2,'raw_redistribution':False}),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(execute_one,r,manifest,run,cap) for r,cap in pending]
        results=[future.result() for future in concurrent.futures.as_completed(futures)]
    immutable_json(run/'reports'/('download_batch_summary-'+manifest.stem+'.json'),{'results':results,
        'downloaded_and_hashed':sum(r['exit_code']==0 for r in results),
        'held':sum(r['exit_code']!=0 for r in results),'admitted':0})
    raise SystemExit(1 if any(r['exit_code'] for r in results) else 0)


if __name__=='__main__':main()
