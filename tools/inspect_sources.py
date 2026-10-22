#!/usr/bin/env python3
"""Bounded metadata/rights inspection. No measurements, labels or weights fetched.

Repository code licensing is explicitly NOT promoted to underlying data rights.
"""
import argparse,base64,concurrent.futures,csv,hashlib,json,subprocess,urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from rnagym import ROOT,immutable_json,now


def gh_json(endpoint):
 p=subprocess.run(['gh','api',endpoint],capture_output=True,text=True,timeout=35)
 if p.returncode:raise RuntimeError(p.stderr[-300:])
 if len(p.stdout.encode())>8*1024*1024:raise ValueError('metadata cap')
 return json.loads(p.stdout)


def inspect_repo(item,run):
 repo,groups=item
 safe=repo.replace('/','__');folder=run/'manifests/source_metadata'/safe;folder.mkdir(parents=True,exist_ok=True)
 result={'repository':repo,'package_groups':groups,'checked_at_utc':now(),'measurements_downloaded':False,'data_rights_approved':False}
 try:
  info=gh_json('repos/'+repo)
  if info['private']:return {**result,'state':'HOLD_AUTH','error':'Source is not public'}
  branch=info['default_branch'];commit=gh_json('repos/'+repo+'/branches/'+branch)['commit']['sha']
  result.update(upstream_commit=commit,code_license_claim=(info.get('license') or {}).get('spdx_id'))
  readme=gh_json('repos/'+repo+'/readme?ref='+commit)
  content=base64.b64decode(readme.get('content',''))
  (folder/'README.source.txt').write_bytes(content)
  result['readme_sha256']=hashlib.sha256(content).hexdigest()
  tree=gh_json('repos/'+repo+'/git/trees/'+commit+'?recursive=1')
  immutable_json(folder/'tree.json',tree)
  result['tree_truncated']=tree.get('truncated',False)
  data=[]
  for f in tree.get('tree',[]):
   path=f['path'];lo=path.lower()
   if f['type']=='blob' and any(lo.endswith(s) for s in ['.csv','.tsv','.parquet','.json','.gz','.zip','.xz','.fasta','.fa','.bpseq','.ct','.dbn','.pdb','.cif','.sdf','.smi']):
    if any(w in lo for w in ['checkpoint','weights','pretrained','prediction','model_state']):continue
    data.append({'path':path,'size_bytes':f.get('size'),'git_blob_object_id_not_sha256':f['sha'],'candidate_url':f'https://raw.githubusercontent.com/{repo}/{commit}/{path}'})
  result.update(state='SOURCE_METADATA_READ_NOT_DATA_ADMISSION',file_candidates=data)
  license_lines=[line.strip()[:500] for line in content.decode('utf-8','replace').splitlines() if any(w in line.lower() for w in ['license','licence','zenodo','figshare','huggingface','dataset','selex'])]
  result['readme_evidence_lines']=license_lines[:60]
 except Exception as e:result.update(state='HOLD_SOURCE',error=type(e).__name__+': '+str(e)[:300])
 immutable_json(folder/'inspection.json',result)
 return result


def inspect_zenodo(record,run):
 url='https://zenodo.org/api/records/'+record
 try:
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'RNA-Gym-audit/0.2'}),timeout=25) as r:b=r.read(4*1024*1024+1)
  if len(b)>4*1024*1024:raise ValueError('metadata cap')
  d=json.loads(b);(run/'manifests'/('zenodo-'+record+'.json')).write_bytes(b)
  return {'record':record,'title':d.get('metadata',{}).get('title'),'license_claim':d.get('metadata',{}).get('license'),'metadata_sha256':hashlib.sha256(b).hexdigest(),'files':[{'name':f['key'],'size_bytes':f['size'],'url':f.get('links',{}).get('self')} for f in d.get('files',[])],'state':'METADATA_ONLY'}
 except Exception as e:return {'record':record,'state':'HOLD_SOURCE','error':type(e).__name__+': '+str(e)[:200]}


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run.resolve()
 with (ROOT/'data/registries/download_packages_47.csv').open(encoding='utf-8-sig') as f:packages=list(csv.DictReader(f))
 repos={}
 for r in packages:
  for url in [r.get('code_url'),r.get('preferred_download_url')]:
   parsed=urlsplit(url or '')
   bits=parsed.path.strip('/').split('/')
   if parsed.hostname=='github.com' and len(bits)>=2:
    repo='/'.join(bits[:2]);repos.setdefault(repo,set()).add(r['package_group_id'])
 print(json.dumps({'source_repositories':len(repos),'all_registry_packages':len(packages),'scope':'metadata and rights only'}),flush=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
  results=list(pool.map(lambda item:inspect_repo((item[0],sorted(item[1])),run),repos.items()))
 zenodo=[inspect_zenodo(i,run) for i in ['14803961','18218776']]
 immutable_json(run/'reports/source_rights_inspection.json',{'repositories':results,'zenodo':zenodo,'data_assays_admitted':0})
 for r in results:print(json.dumps({'repo':r['repository'],'groups':r['package_groups'],'state':r['state'],'code_license':r.get('code_license_claim'),'file_candidates':len(r.get('file_candidates',[]))}),flush=True)
 for r in zenodo:print(json.dumps(r),flush=True)


if __name__=='__main__':main()
