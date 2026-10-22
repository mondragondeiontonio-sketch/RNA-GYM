#!/usr/bin/env python3
"""Catalog public HF datasets through an explicitly authorized mirror.

Only metadata is read. Collection license claims are not original-assay rights
approval. Git blob object IDs are NEVER recorded as expected file SHA-256.
"""
import concurrent.futures
import csv
import hashlib
import json
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from rnagym import ROOT, now, immutable_json


def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url,
            headers={'User-Agent':'RNA-Gym-public-audit/0.2'}),timeout=20) as r:
        data=r.read(4*1024*1024+1)
        if len(data)>4*1024*1024:raise ValueError('metadata cap')
        return json.loads(data)


def catalog(row):
    p=urlsplit(row['preferred_download_url'])
    parts=p.path.strip('/').split('/')
    if p.hostname!='huggingface.co' or len(parts)<3 or parts[0]!='datasets':return None
    repo='/'.join(parts[1:3]);meta={'package_group_id':row['package_group_id'],
          'hf_repository':repo,'official_source_url':'https://huggingface.co/datasets/'+repo,
          'metadata_transport':'https://hf-mirror.com','checked_at_utc':now(),
          'license_scope':'COLLECTION_CLAIM_ONLY_NOT_ORIGINAL_ASSAY_APPROVAL'}
    try:
        info=get_json('https://hf-mirror.com/api/datasets/'+repo)
        commit=info.get('sha')
        if not commit:raise ValueError('missing release commit')
        meta.update({'upstream_commit':commit,'gated':info.get('gated'),
                     'data_license_claim':(info.get('cardData') or {}).get('license'),
                     'state':'CATALOGED_NOT_DOWNLOADED'})
        if info.get('gated'):
            return {**meta,'state':'HOLD_AUTH','files':[]}
        tree=get_json(f'https://hf-mirror.com/api/datasets/{repo}/tree/{commit}?recursive=true')
        files=[]
        prefix = {'RNAGYM_3D':'tertiary_structure_prediction/', 'RNAGYM_RMDB':'secondary_structure_prediction/', 'RNAGYM_DMS':'fitness_prediction/'}.get(row['package_group_id'], '')
        tree_by_path = {x.get('path'):x for x in tree}
        for sibling in info.get('siblings', []):
            name = sibling.get('rfilename')
            if name and name not in tree_by_path:
                tree_by_path[name] = {'path':name, 'type':'file', 'size':None, 'tree_metadata_missing':True}
        meta['tree_metadata_complete'] = not any(x.get('tree_metadata_missing') for x in tree_by_path.values() if x.get('path','').startswith(prefix))
        for item in tree_by_path.values():
            name=item.get('path','')
            if not name.startswith(prefix) or item.get('type')!='file' or not any(name.endswith(s) for s in
                 ['.parquet','.csv','.tsv','.gz','.zip','.xz','.fasta','.fa','.jsonl']):continue
            lfs=item.get('lfs') or {}
            files.append({'relative_path':name,'size_bytes':item.get('size'),
                'official_download_url':f'https://huggingface.co/datasets/{repo}/resolve/{commit}/{name}',
                'mirror_download_url':f'https://hf-mirror.com/datasets/{repo}/resolve/{commit}/{name}',
                'git_blob_object_id_not_sha256':item.get('oid'),
                'lfs_sha256_claim_not_observed':lfs.get('oid'),
                'actual_sha256':None,'downloaded':False})
        meta['files']=files
        return meta
    except Exception as e:
        return {**meta,'state':'HOLD_SOURCE','error':f'{type(e).__name__}: {str(e)[:150]}','files':[]}


def main():
    run=ROOT/'runs'/(ROOT/'runs/LATEST').read_text().strip()
    with (ROOT/'data/registries/download_packages_47.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
    selected=[r for r in rows if 'huggingface.co/datasets/' in r['preferred_download_url']]
    selected.append({'package_group_id':'RNAGYM_DMS', 'preferred_download_url':'https://huggingface.co/datasets/Marks-lab/RNAgym'})
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results=[r for r in pool.map(catalog,selected) if r]
    path=ROOT/'data/audit/hf_mirror_catalog.json';path.write_text(json.dumps(results,indent=2)+'\n')
    immutable_json(run/'manifests'/('hf_mirror_catalog-' + hashlib.sha256(json.dumps(results,sort_keys=True).encode()).hexdigest()[:16] + '.json'),results)
    fields=['asset_id','package_group_id','relative_filename','direct_url','sha256_expected',
      'rights_status','size_band','official_source_url','transport_role','upstream_commit','release_tag',
      'collection_license_claim','declared_size_bytes','upstream_relative_path']
    assets=[]
    for row in results:
        for f in row['files']:
            aid='HF_'+hashlib.sha256((row['package_group_id']+':'+f['relative_path']).encode()).hexdigest()[:20]
            assets.append({'asset_id':aid,'package_group_id':row['package_group_id'],
             'relative_filename':Path(f['relative_path']).name,'direct_url':f['mirror_download_url'],
             'sha256_expected':'','rights_status':'REVIEW_REQUIRED','size_band':'SIZE_RECORDED_METADATA_ONLY',
             'official_source_url':f['official_download_url'],'transport_role':'USER_AUTHORIZED_MIRROR',
             'upstream_commit':row.get('upstream_commit'),'release_tag':'COMMIT_PINNED_METADATA_ONLY',
             'collection_license_claim':row.get('data_license_claim') or 'unknown',
             'declared_size_bytes':f.get('size_bytes'),'upstream_relative_path':f['relative_path']})
    with (ROOT/'data/audit/hf_file_candidates.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fields);w.writeheader();w.writerows(assets)
    print(json.dumps({'packages_attempted':len(results),'packages_cataloged':sum(r['state']=='CATALOGED_NOT_DOWNLOADED' for r in results),'file_link_candidates':len(assets),'files_downloaded_by_catalog':0,'unknown_licenses':sum(r.get('data_license_claim') in (None,'unknown') for r in results)}))


if __name__=='__main__':main()
