#!/usr/bin/env python3
"""Archive bounded public GitHub source text, never execute source or fetch weights."""
import argparse,base64,hashlib,json,re,subprocess
from pathlib import Path

def api(endpoint):
 p=subprocess.run(['gh','api',endpoint],capture_output=True,timeout=45)
 if p.returncode:raise RuntimeError(p.stderr.decode()[-250:])
 if len(p.stdout)>8*1024**2:raise ValueError('metadata cap exceeded')
 return json.loads(p.stdout)

def collect(repo,paths,out):
 if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('invalid repository')
 folder=out/repo.replace('/','__')
 checkpoint=folder/'snapshot.json'
 if checkpoint.exists():
  cached=json.loads(checkpoint.read_text())
  for r in cached['files']:
   if r.get('verification_status')=='VERIFIED' and hashlib.sha256(Path(r['local_path']).read_bytes()).hexdigest()!=r['sha256']:raise ValueError('source snapshot changed')
  return cached
 info=api('repos/'+repo)
 if info['private']:raise ValueError('private source refused')
 commit=api('repos/'+repo+'/commits/'+info['default_branch'])['sha']
 folder=out/repo.replace('/','__');folder.mkdir(parents=True,exist_ok=True)
 tree=api('repos/'+repo+'/git/trees/'+commit+'?recursive=1')
 data=json.dumps(tree,sort_keys=True,indent=2).encode();(folder/'tree.json').write_bytes(data)
 records=[]
 for path in paths:
  try:
   doc=api(f'repos/{repo}/contents/{path}?ref={commit}')
   if doc.get('size',0)>1024**2:raise ValueError('text cap exceeded')
   raw=base64.b64decode(doc['content'],validate=False);raw.decode('utf-8',errors='strict')
   target=folder/path.replace('/','__');target.write_bytes(raw)
   records.append(dict(path=path,local_path=str(target),source_url=f'https://github.com/{repo}/blob/{commit}/{path}',sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),verification_status='VERIFIED'))
  except Exception as e:records.append(dict(path=path,verification_status='BLOCKED',error=str(e)[:250]))
 doc=dict(repository=repo,commit=commit,code_executed=False,measurements_downloaded=False,files=records)
 (folder/'snapshot.json').write_text(json.dumps(doc,indent=2)+'\n');return doc

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 sources={'BioGeMT/miRBench_paper':['README.md','RUNME.sh','code/data_preparation/README.md','code/post_process/README.md','code/post_process/postprocess_3_make_negatives_README.md','code/post_process/postprocess_4_train_test_splits_README.md','code/scripts_to_download_eCLIP_Manakov_2022/README.md','code/scripts_to_download_eCLIP_Manakov_2022/download_eCLIP_Manakov_2022_data.sh','code/clustering/README.md'], 'katarinagresova/miRBench':['src/miRBench/dataset.py']}
 for repo,paths in sources.items():print(json.dumps(collect(repo,paths,a.out)),flush=True)
if __name__=='__main__':main()
