#!/usr/bin/env python3
"""T0021 author/custom group-split audit using cached exact-input identities.

No raw RNA rescan, large X load, labels for split assignment, training, row merge
or admission. Custom output is an exploratory version, never an official fold.
"""
import argparse,collections,csv,hashlib,io,json,sqlite3,stat,zipfile
from decimal import Decimal
from pathlib import Path,PurePosixPath
from rnagym import ROOT,StateDB,immutable_json,now

VERSION='RNA-GYM:T0021:group-audit:v1.1'
HF_ASSET='HF_214a7f32ac346e79b8b1';MAP_ASSET='HOMOLOGENE_13910050'

def digest(data):return hashlib.sha256(data).hexdigest()
def stable(data):return digest(json.dumps(data,ensure_ascii=False,separators=(',',':')).encode())

def read_map(path):
 """Bounded read of one CSV, no extraction, links, pickle or header repair."""
 with zipfile.ZipFile(path) as z:
  infos=z.infolist()
  if len(infos)>32 or sum(i.file_size for i in infos)>16*1024**2:raise ValueError('mapping ZIP expansion budget')
  for i in infos:
   n=PurePosixPath(i.filename)
   if n.is_absolute() or '..' in n.parts or '\\' in i.filename or ':' in i.filename or stat.S_ISLNK(i.external_attr>>16):raise ValueError('unsafe mapping member')
  selected=[i for i in infos if PurePosixPath(i.filename).name=='human_homology_map.csv']
  if len(selected)!=1 or selected[0].file_size>4*1024**2:raise ValueError('missing/ambiguous human CSV or member budget')
  raw=z.read(selected[0]);reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig',errors='strict')))
  if not reader.fieldnames or len(set(reader.fieldnames))!=len(reader.fieldnames) or not {'gene_name','gene_group'}.issubset(reader.fieldnames):raise ValueError('mapping schema missing')
  pairs=[]
  for line,row in enumerate(reader,2):
   if None in row or any(v is None for v in row.values()) or not row['gene_name']:raise ValueError('ragged/empty map name')
   number=Decimal(row['gene_group'])
   if not number.is_finite() or number!=number.to_integral_value():raise ValueError('invalid homology group')
   pairs.append((row['gene_name'],int(number)))
 return pairs,dict(member=selected[0].filename,member_sha256=digest(raw),rows=len(pairs),header_columns=reader.fieldnames,raw_strings_preserved=True,case_or_alias_normalization=False)

def reproduce_author_two_way(genes,pairs,test_size,seed):
 import numpy as np
 # Last-value-wins exactly mirrors author's set_index(...).to_dict(). Unknown
 # genes intentionally remain row-wise here so the original behavior is audited.
 mapping=dict(pairs);groups=[mapping.get(gene) for gene in genes];members=collections.defaultdict(list)
 for i,g in enumerate(groups):
  if g is not None:members[g].append(i)
 order=np.arange(len(genes));np.random.RandomState(seed).shuffle(order)
 boundary=int(len(genes)*(1-test_size));seen=set();train=[];test=[]
 for raw_i in order:
  i=int(raw_i);group=groups[i]
  if group is not None and group in seen:continue
  seen.add(group);target=train if len(train)<boundary else test;target.extend(members.get(group,[i]))
 if sorted(train+test)!=list(range(len(genes))):raise ValueError('author reproduction lost/duplicated rows')
 return train,test

def reproduce_author(genes,pairs,seed=2541):
 train,tv=reproduce_author_two_way(genes,pairs,0.3,seed)
 vi,ti=reproduce_author_two_way([genes[i] for i in tv],pairs,0.5,seed)
 out={i:'train' for i in train};out.update({tv[i]:'validation' for i in vi});out.update({tv[i]:'test' for i in ti});return out

class UnionFind:
 def __init__(self,n):self.parent=list(range(n))
 def find(self,x):
  while self.parent[x]!=x:self.parent[x]=self.parent[self.parent[x]];x=self.parent[x]
  return x
 def union(self,a,b):
  a,b=self.find(a),self.find(b)
  if a!=b:self.parent[a]=b

def custom_groups(genes,input_keys,pairs):
 by_gene=collections.defaultdict(set)
 for gene,group in pairs:by_gene[gene].add(group)
 uf=UnionFind(len(genes));gene_seen={};input_seen={};homology_seen={}
 for i,(gene,key) in enumerate(zip(genes,input_keys)):
  if not gene:raise ValueError('empty acquired gene annotation')
  if gene in gene_seen:uf.union(i,gene_seen[gene])
  else:gene_seen[gene]=i
  if key in input_seen:uf.union(i,input_seen[key])
  else:input_seen[key]=i
  for group in by_gene.get(gene,[]):
   if group in homology_seen:uf.union(i,homology_seen[group])
   else:homology_seen[group]=i
 components=collections.defaultdict(list)
 for i in range(len(genes)):components[uf.find(i)].append(i)
 return list(components.values())

def assign_custom(components,n,source_sha,seed=2541):
 names=['train','validation','test'];targets=[n*.7,n*.15,n*.15];counts=[0,0,0];out={};group_keys={}
 prepared=[]
 for rows in components:
  key=stable(['RNA-GYM:T0021:connected-component:v1',source_sha,sorted(i+1 for i in rows)])
  prepared.append((rows,key,stable([seed,key])))
 for rows,key,_ in sorted(prepared,key=lambda x:(-len(x[0]),x[2])):
  slot=max(range(3),key=lambda i:targets[i]-counts[i]);counts[slot]+=len(rows)
  for row in rows:out[row]=names[slot];group_keys[row]=key
 if set(out)!=set(range(n)):raise ValueError('custom partition coverage mismatch')
 return out,group_keys

def overlaps(values,assignment):
 by_value=collections.defaultdict(lambda:collections.defaultdict(list))
 for i,v in enumerate(values):by_value[v][assignment[i]].append(i+1)
 shared={k:dict(v) for k,v in by_value.items() if len(v)>1}
 return dict(shared_keys=len(shared),rows_in_shared_keys=sum(sum(map(len,v.values())) for v in shared.values())),shared

def audit_split(genes,input_keys,pairs,assignment):
 mapping=dict(pairs);homo_splits=collections.defaultdict(set)
 for i,gene in enumerate(genes):
  if gene in mapping:homo_splits[mapping[gene]].add(assignment[i])
 gene_counts,gene_examples=overlaps(genes,assignment);input_counts,input_examples=overlaps(input_keys,assignment)
 unknown=[i for i,g in enumerate(genes) if g not in mapping];unknown_sets=collections.defaultdict(set)
 for i in unknown:unknown_sets[genes[i]].add(assignment[i])
 pairwise={}
 for left,right in [('train','validation'),('train','test'),('validation','test')]:
  pairwise[left+'__'+right]=dict(shared_gene_keys=sum(left in x and right in x for x in gene_examples.values()),shared_exact_input_keys=sum(left in x and right in x for x in input_examples.values()))
 return dict(pairwise_overlap_counts=pairwise,split_counts=dict(collections.Counter(assignment.values())),row_coverage=len(assignment),gene_overlap=gene_counts,exact_input_overlap=input_counts,known_homology_groups_shared=sum(len(x)>1 for x in homo_splits.values()),unmapped_gene_annotations_shared=sum(len(x)>1 for x in unknown_sets.values()),unmapped_row_count=len(unknown),unmapped_gene_annotation_count=len({genes[i] for i in unknown}),independent_RNA_homology_checked=False,cross_dataset_exposure_cleared=False,original_assay_condition_verified=False,evaluation_enabled=False,admission_gate_pass=False),gene_examples,input_examples

def write_tsv(path,rows,fields):
 buf=io.StringIO(newline='');w=csv.DictWriter(buf,fieldnames=fields,delimiter='\t',lineterminator='\n');w.writeheader()
 for row in rows:w.writerow({k:json.dumps(v,ensure_ascii=False,sort_keys=True) if isinstance(v,(dict,list)) else v for k,v in row.items()})
 b=buf.getvalue().encode()
 if path.exists():
  if path.read_bytes()!=b:raise ValueError('immutable output differs; choose new run')
 else:
  with path.open('xb') as f:f.write(b)
  path.chmod(0o444)
 return digest(b)

def load_inputs(run_dir,state_db):
 import pyarrow.parquet as pq
 with sqlite3.connect('file:'+str(state_db)+'?mode=ro',uri=True) as db:
  found={}
  for aid in [HF_ASSET,MAP_ASSET]:
   records=db.execute('SELECT sha256,bytes,raw_path FROM artifacts WHERE asset_id=?',(aid,)).fetchall()
   if len(records)!=1:raise ValueError('missing or ambiguous source artifact '+aid)
   sha,n,p=records[0];path=Path(p)
   if not path.resolve().is_relative_to(ROOT/'raw_cache') or path.stat().st_size!=n:raise ValueError('quarantine/size binding failed')
   found[aid]=dict(sha256=sha,bytes=n,path=path)
 mapping=found[MAP_ASSET];raw=mapping['path'].read_bytes()
 if len(raw)>2*1024**2 or digest(raw)!=mapping['sha256']:raise ValueError('small mapping SHA mismatch/budget')
 metadata=json.loads((run_dir/'manifests/zenodo_13910050.json').read_text());f=next(f for f in metadata['files'] if f['key']=='homology_maps_homologene.zip')
 expected=f['checksum']
 if not expected.startswith('md5:') or hashlib.md5(raw).hexdigest()!=expected.split(':',1)[1]:raise ValueError('publisher MD5 mismatch')
 hf=found[HF_ASSET];prior=ROOT/'runs/20261022_212625/reports/sequence_qc'/str(HF_ASSET+'.json')
 qc=json.loads(prior.read_text())
 if qc['source_sha256']!=hf['sha256']:raise ValueError('prior full QC does not bind current version')
 table=pq.read_table(hf['path'],columns=['gene','chromosome']);genes=table['gene'].to_pylist();chrs=table['chromosome'].to_pylist()
 with sqlite3.connect('file:'+str(ROOT/'runs/20261022_212625/reports/sequence_sample_identity.sqlite')+'?mode=ro',uri=True) as c:
  rows=c.execute('SELECT row_number,input_hash,observation_hash,file_sha256 FROM samples WHERE asset_id=? ORDER BY row_number',(HF_ASSET,)).fetchall()
 if len(rows)!=len(genes) or not rows:raise ValueError('cached exact-input key coverage mismatch')
 for i,(row,key,obs,sha) in enumerate(rows,1):
  if row!=i or sha!=hf['sha256'] or len(key)!=32 or len(obs)!=32:raise ValueError('invalid cached identity binding')
 key_hash=stable([[i,k.hex(),o.hex(),sha] for i,k,o,sha in rows]);inputs=[k.hex() for _,k,_,_ in rows]
 return found,genes,chrs,inputs,[o.hex() for _,_,o,_ in rows],key_hash

def run(run_dir,state_db,dry_run=False):
 found,genes,chrs,inputs,observations,keys_sha=load_inputs(run_dir,state_db)
 protocol_path=run_dir/'manifests/group_split_protocol.json';protocol=json.loads(protocol_path.read_text())
 if protocol['seed']!=2541 or protocol['source_labels_used_for_assignment'] is not False or protocol['ratios']!=[.7,.15,.15]:raise ValueError('unsupported registered protocol')
 pairs,map_info=read_map(found[MAP_ASSET]['path'])
 source_code=ROOT/'runs/20261023_043639/manifests/mrna_sources/repo__mrna_bench__data_splitter__homology_split.py'
 if digest(source_code.read_bytes())!='eb4ac79786e5962a2779157c7f29efc8f59fdcd5d043a3af14709ca3cecdbef8':raise ValueError('pinned author source changed; do not assume logic equivalence')
 versions={}
 import importlib.metadata
 for package in ['numpy','pyarrow']:versions[package]=importlib.metadata.version(package)
 fingerprint=stable([VERSION,{a:x['sha256'] for a,x in found.items()},keys_sha,digest(protocol_path.read_bytes()),digest(source_code.read_bytes()),digest(Path(__file__).read_bytes()),versions])
 if dry_run:return dict(dry_run=True,verification_status='VERIFIED',rows=len(genes),protocol_sha256=digest(protocol_path.read_bytes()),cached_identity_sha256=keys_sha,raw_sequence_scan=False,labels_read=False,writes=False)
 reports=run_dir/'reports';reports.mkdir(parents=True,exist_ok=True);summary_path=reports/'t0021_group_split_summary.json'
 if summary_path.exists():
  prior=json.loads(summary_path.read_text())
  if prior['input_fingerprint']!=fingerprint:raise ValueError('changed inputs/code; choose a new run')
  for name,h in prior['output_sha256'].items():
   if digest((reports/name).read_bytes())!=h:raise ValueError('immutable output changed')
  return prior
 author=reproduce_author(genes,pairs);components=custom_groups(genes,inputs,pairs);custom,group_keys=assign_custom(components,len(genes),found[HF_ASSET]['sha256'])
 author_qc,author_genes,author_inputs=audit_split(genes,inputs,pairs,author);custom_qc,_,_=audit_split(genes,inputs,pairs,custom)
 if custom_qc['gene_overlap']['shared_keys'] or custom_qc['exact_input_overlap']['shared_keys'] or custom_qc['known_homology_groups_shared']:raise ValueError('custom split violates registered constraints')
 by_gene=collections.defaultdict(set)
 for gene,group in pairs:by_gene[gene].add(group)
 coverage=dict(rows=len(genes),unique_gene_annotations=len(set(genes)),mapped_gene_annotations=sum(g in by_gene for g in set(genes)),unmapped_gene_annotations=sum(g not in by_gene for g in set(genes)),mapped_rows=sum(g in by_gene for g in genes),ambiguous_multi_group_gene_annotations=sum(len(by_gene[g])>1 for g in set(genes)),exact_input_keys=len(set(inputs)))
 assignments=[dict(benchmark_row=i+1,observation_id=stable(['RNA-GYM:raw-file-row:v1',found[HF_ASSET]['sha256'],i+1]),source_gene_annotation=g,source_chromosome_annotation=chrs[i],raw_input_key=inputs[i],prior_raw_observation_hash=observations[i],known_homology_groups=sorted(by_gene.get(g,[])),author_protocol_fold=author[i],custom_exploratory_fold=custom[i],custom_component_id=group_keys[i],mapping_status='ORIGINAL_ISOFORM_AND_CONDITION_UNVERIFIED') for i,g in enumerate(genes)]
 decisions=[]
 for category,examples in [('AUTHOR_CROSS_SPLIT_GENE',author_genes),('AUTHOR_CROSS_SPLIT_EXACT_INPUT',author_inputs)]:
  for key,folds in sorted(examples.items()):decisions.append(dict(category=category,key=key,fold_rows=folds,action='KEEP_ORIGINAL_AUTHOR_REPRODUCTION; CUSTOM_VERSION_GROUPS_OBSERVATIONS_NOT_LABELS',verification_status='VERIFIED_OBSERVED_OVERLAP'))
 output={}
 for name,rows,fields in [('t0021_split_assignments.tsv',assignments,list(assignments[0])),('t0021_author_leakage_cases.tsv',decisions,['category','key','fold_rows','action','verification_status'])]:output[name]=write_tsv(reports/name,rows,fields)
 custom_manifest=dict(protocol_id=protocol['protocol_id'],origin=protocol['origin'],registration_timing=protocol['registration_timing'],source_asset_sha256=found[HF_ASSET]['sha256'],map_asset_sha256=found[MAP_ASSET]['sha256'],seed=2541,group_policy=protocol['group_policy'],split_assignments_sha256=output['t0021_split_assignments.tsv'],split_counts=custom_qc['split_counts'],original_split_untouched=True,evaluation_enabled=False,not_full_homology_clearance=True,admission_gate_pass=False)
 immutable_json(reports/'t0021_custom_split_manifest.json',custom_manifest);output['t0021_custom_split_manifest.json']=digest((reports/'t0021_custom_split_manifest.json').read_bytes())
 source_map=dict(verification_status='VERIFIED_SOURCE_METADATA',task_id='T0021',map_release='Zenodo 13910050 v1.0',source_dataset_license='MIT per record',map_asset_sha256=found[MAP_ASSET]['sha256'],publisher_checksum=dict(algorithm='MD5',value=hashlib.md5(found[MAP_ASSET]['path'].read_bytes()).hexdigest()),**map_info)
 immutable_json(reports/'homology_map_provenance.json',source_map);output['homology_map_provenance.json']=digest((reports/'homology_map_provenance.json').read_bytes())
 sizes=sorted([len(c) for c in components],reverse=True)
 summary=dict(verification_status='VERIFIED_AUDIT_FACTS',scientific_stage='SOURCE_VERIFIED',scientific_disposition='HOLD_SOURCE_IDENTITY',task_id='T0021',algorithm=VERSION,input_fingerprint=fingerprint,protocol_sha256=digest(protocol_path.read_bytes()),source_input_sha256={a:x['sha256'] for a,x in found.items()},source_input_hash_algorithm='prior full-QC SHA256 of compact UTF8 JSON [RNA-GYM:raw-sequence:v1,raw_sequence]; no U/T or case normalization',cached_exact_identity_subset_sha256=keys_sha,author_logic_source_sha256=digest(source_code.read_bytes()),versions=versions,coverage=coverage,author_protocol_reproduction=author_qc,custom_exploratory_split=custom_qc,custom_component_count=len(components),largest_component_rows=sizes[0],custom_component_size_counts=dict(collections.Counter(sizes)),source_assay_identity_verified=False,full_RNA_sequence_homology_verified=False,pretraining_exposure_cleared=False,all_observations_preserved=True,original_split_changed=False,raw_sequences_scanned=False,large_X_loaded=False,raw_labels_read_for_split=False,labels_merged=False,scaler_or_HPO_fitted=False,real_models_run=0,GPU_jobs=0,human_approval_generated=False,admission_candidates=0,admitted=0,output_sha256=output)
 report=make_report(summary);p=reports/'T0021_GROUP_SPLIT_REPORT.md'
 if p.exists() and p.read_text()!=report:raise ValueError('immutable report differs')
 if not p.exists():p.write_text(report);p.chmod(0o444)
 output[p.name]=digest(p.read_bytes())
 with StateDB(state_db) as db:
  with db.transaction():
   key=stable([VERSION,run_dir.name,'T0021',fingerprint]);cursor=db.db.execute('INSERT OR IGNORE INTO scientific_reviews VALUES (?,?,?,?,?,?,?,?,0,0)',(key,run_dir.name,'T0021','SOURCE_VERIFIED','HOLD_SOURCE_IDENTITY',fingerprint,str(summary_path.relative_to(ROOT)),now()))
   if cursor.rowcount:db.db.execute('INSERT INTO scientific_review_events(idempotency_key,at_utc,detail_json) VALUES (?,?,?)',(key,now(),json.dumps(dict(event='AUTHOR_AND_CUSTOM_GROUP_SPLIT_AUDIT',admitted=False,labels_read_for_split=False))))
 immutable_json(summary_path,summary);return summary

def make_report(s):
 return '\n'.join(['# T0021 source and homology-split audit','',
 '**VERIFIED: source-group coverage, author-code reproduction and observed overlaps.**',
 '**PROVISIONAL: custom exploratory split. BLOCKED: original assay admission.**','',
 'No large X expansion, raw RNA rescan, target read for assignment, scaler/HPO,',
 'training, label merge or raw-data alteration was performed. The original',
 'benchmark/author split is not overwritten. Existing exact-input identities',
 'are reused and explicitly bound to the prior full-file QC SHA.','',
 '## Source and group coverage','', '```json',json.dumps(s['coverage'],indent=2),'```','',
 'Human map is the exact file used by the pinned mRNABench author implementation:',
 'Zenodo 13910050 v1.0, not a silent replacement with another release. The data',
 'record declares MIT; final assay/rights approval is still not generated.',
 'The source CSV index column is preserved in provenance, not silently repaired.',
 'HomoloGene groups are not an independent RNA sequence-homology validation.','',
 '## Original author logic — reproduced, not called an official fixed split','',
 'Known groups are co-assigned by the pinned author function. Genes absent from',
 'the map fall back to per-row assignment. Identical missing-map gene names are',
 'therefore not guaranteed to remain in one fold. The data-specific counts are:',
 '```json',json.dumps(s['author_protocol_reproduction'],indent=2),'```','',
 'The original code is not executed, patched or silently replaced. The local',
 'logic-equivalent reproduction uses the same legacy NumPy shuffle/seed and',
 'two-stage ratios. Actual published fold IDs remain unverified.','',
 '## Separate exploratory strict grouping version','',
 'The protocol was frozen before reading the actual mapping and before any',
 'model run, but AFTER original task registration. It is NOT described as',
 'prior-to-assay-selection preregistration or an official split.',
 'The custom version unions same exact gene, all known source homology groups,',
 'and identical exact whole-input hashes. Multiple-source-group gene aliases',
 'bridge conservatively; unknown genes never split row-wise. Every observation',
 'and its label remains intact; grouping does not mean duplicate-label merging.',
 '```json',json.dumps(s['custom_exploratory_split'],indent=2),'```','',
 f'Connected groups: {s["custom_component_count"]}; largest: {s["largest_component_rows"]} rows.',
 'Unmapped gene families, independent RNA homology, pretraining exposure, and',
 'cross-dataset sharing remain unverified. Zero observed source-group overlap',
 'is NOT a full PASS_GROUP_AND_CROSS_BENCHMARK_LEAKAGE or admission decision.',
 'Cell/condition and original isoform mapping remain source-specific HOLD.','',
 '## Evidence and recovery','',
 't0021_split_assignments.tsv: all rows, original and custom assignments together.',
 't0021_author_leakage_cases.tsv: overlap keys/row memberships and no-delete decision.',
 't0021_custom_split_manifest.json; homology_map_provenance.json;',
 't0021_group_split_summary.json; ../manifests/group_split_protocol.json.',
 'Use --resume with the same immutable inputs/code. Changed inputs require a',
 'new run. ADMISSION_CANDIDATE=0, ADMITTED=0, model scores=0.',''])

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--state-db',type=Path,default=ROOT/'run-state.sqlite');p.add_argument('--dry-run',action='store_true');p.add_argument('--resume',action='store_true');a=p.parse_args()
 if not a.run.resolve().is_relative_to(ROOT/'runs'):p.error('run must remain in local ignored runs')
 s=run(a.run.resolve(),a.state_db.resolve(),a.dry_run)
 print(json.dumps(s if a.dry_run else {k:s[k] for k in ['coverage','author_protocol_reproduction','custom_exploratory_split','custom_component_count','largest_component_rows','admission_candidates','admitted']},indent=2))
if __name__=='__main__':main()
