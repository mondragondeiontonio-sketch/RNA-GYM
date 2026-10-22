#!/usr/bin/env python3
"""Locate released GRCh38 eCLIP peak files for explicitly registered RBP/cell pairs.

Does not fetch BAM/FASTQ, controlled data, all ENCODE experiments or measurements.
An ENCODE experiment accession is a real source key, not a benchmark DOI.
"""
import argparse,csv,hashlib,json,urllib.request,urllib.parse,urllib.error
from pathlib import Path
from rnagym import ROOT,immutable_json,now


def metadata(url,cap=16*1024**2):
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'RNA-Gym-audit/0.2','Accept':'application/json'}),timeout=30) as r:b=r.read(cap+1)
 if len(b)>cap:raise ValueError('metadata budget exceeded')
 return json.loads(b),b


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run.resolve()
 targets={}
 with (ROOT/'data/registries/search_level_task_crosswalk_198.csv').open(encoding='utf-8-sig') as f:
  for t in csv.DictReader(f):
   if t['row_id'].startswith('XSCOPE_') and t['package_group_id']=='ENCODE_ECLIP':
    body=t['row_id'].removeprefix('XSCOPE_');rbp,cell=body.rsplit('_',1);targets[(rbp,cell)]=t['row_id']
 policy_url='https://www.encodeproject.org/help/citing-encode/'
 with urllib.request.urlopen(urllib.request.Request(policy_url,headers={'User-Agent':'RNA-Gym-audit/0.2'}),timeout=30) as r:policy=r.read(2*1024**2)
 if not (b'freely download' in policy and b'without restrictions' in policy):raise ValueError('ENCODE use-policy text not established')
 proof=run/'manifests/encode_data_policy.html';proof.write_bytes(policy)
 params=[('type','Experiment'),('assay_title','eCLIP'),('status','released'),('limit','all'),('format','json')]
 for field in ['accession','target.label','biosample_ontology.term_name']:params.append(('field',field))
 query='https://www.encodeproject.org/search/?'+urllib.parse.urlencode(params)
 data,raw=metadata(query);(run/'manifests/encode_eclip_catalog.json').write_bytes(raw)
 selected=[];experiments=[];holds=[]
 for exp in data.get('@graph',[]):
  target=exp.get('target',{}).get('label');cell=exp.get('biosample_ontology',{}).get('term_name')
  if (target,cell) not in targets:continue
  accession=exp['accession'];d,b=metadata(f'https://www.encodeproject.org/experiments/{accession}/?format=json',4*1024**2)
  (run/'manifests'/('encode-'+accession+'.json')).write_bytes(b)
  experiments.append({'source_assay_id':accession,'canonical_assay_candidate':'ENCODE:'+accession,
   'task_id':targets[(target,cell)],'target_rbp':target,'cell_line':cell,'species_claim':'Homo sapiens','status':d.get('status'),
   'references':d.get('references',[]),'dbxrefs':d.get('dbxrefs',[]),'source_url':'https://www.encodeproject.org'+d['@id'],
   'identity_status':'SOURCE_ACCESSION_RBP_CELL_VERIFIED_TASK_PREPARATION_PENDING','human_review_approved':False})
  files=[]
  for f in d.get('files',[]):
   if not isinstance(f,dict):continue
   output=(f.get('output_type') or '').lower()
   if f.get('status')!='released' or f.get('assembly')!='GRCh38' or f.get('file_format')!='bed' or 'peak' not in output:continue
   if f.get('file_size',0)>32*1024**2:continue
   files.append(f)
  preferred=[f for f in files if 'idr thresholded' in (f.get('output_type') or '').lower()]
  chosen=preferred or [f for f in files if 'replicated' in (f.get('output_type') or '').lower()]
  # Preserve distinct analysis files; no arbitrary replacement of another experiment.
  for f in chosen:
   file_id=f['accession'];url='https://www.encodeproject.org'+f['href']
   selected.append({'asset_id':'ENCODE_'+file_id,'package_group_id':'ENCODE_ECLIP','relative_filename':url.rsplit('/',1)[1],
    'direct_url':url,'official_source_url':url,'transport_role':'OFFICIAL','sha256_expected':'','rights_status':'REVIEW_REQUIRED','size_band':'RELEASED_PEAK_FILE_MAX32MIB',
    'release_tag':f.get('date_created') or 'ENCODE_RELEASED','upstream_commit':'','declared_size_bytes':f['file_size'],
    'source_assay_id':accession,'task_id':targets[(target,cell)],'target_rbp':target,'cell_line':cell,'assembly':'GRCh38','output_type':f['output_type'],
    'upstream_md5_claim_not_sha256':f.get('md5sum'),'file_format_type':f.get('file_format_type'),'qc_modality':'genomic_peak_coordinates'})
  if not chosen:holds.append({'source_assay_id':accession,'task_id':targets[(target,cell)],'state':'HOLD_SOURCE','reason':'No released GRCh38 IDR/replicated peak BED selected; raw BAM/FASTQ not silently substituted'})
 if len(selected)>100 or sum(r['declared_size_bytes'] for r in selected)>256*1024**2:raise ValueError('ENCODE bounded batch exceeded')
 fields=list(dict.fromkeys(k for r in selected for k in r))
 with (ROOT/'data/audit/encode_assets.csv').open('w',newline='') as f:w=csv.DictWriter(f,fields);w.writeheader();w.writerows(selected)
 rights_path=ROOT/'data/audit/rights_decisions.json';rights=json.loads(rights_path.read_text())
 for r in selected:
  rights[r['asset_id']]={'decision':'ALLOW_PUBLIC_QUARANTINE_POC','license':'ENCODE consortium released-data policy: freely available with no restrictions on use',
    'evidence_url':policy_url,'evidence_sha256':hashlib.sha256(policy).hexdigest(),'scope':'Local public released peak acquisition and QC; no raw redistribution, no human assay approval','human_reviewer':None}
 rights_path.write_text(json.dumps(rights,indent=2)+'\n')
 immutable_json(run/'reports/encode_source_assays.json',{'registered_rbp_cell_pairs':len(targets),'source_experiments':experiments,'file_candidates':selected,'holds':holds,'admitted':0})
 print(json.dumps({'matched_original_experiments':len(experiments),'selected_peak_files':len(selected),'declared_bytes':sum(r['declared_size_bytes'] for r in selected),'all_files_max32MiB':True,'task_sequences_prepared':False}),flush=True)


if __name__=='__main__':main()
