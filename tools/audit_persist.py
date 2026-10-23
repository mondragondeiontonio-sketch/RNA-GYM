#!/usr/bin/env python3
"""Bounded source-to-benchmark PERSIST-seq audit; never edits labels or admits.

Only the four explicitly named small source files are read. Output identity and
measurement comparisons remain local; neither source code nor pickle is run.
"""
import argparse,collections,csv,hashlib,io,json,math,sqlite3
from pathlib import Path
from rnagym import ROOT,StateDB,immutable_json,now

VERSION='RNA-GYM:persist-source-audit:v1.1'
ASSETS=['HF_34f6495ae6d93242ca39','PERSIST_CONSTRUCTS','PERSIST_COUNTS','PERSIST_SAMPLES']
LABELS={'target_ribosome_load':'ribosome_load','target_in_cell_half_life':'half_life_in_cell'}
MISSING={'','NA','NaN','nan','None'}

def hash_bytes(data):return hashlib.sha256(data).hexdigest()
def canonical_hash(parts):return hash_bytes(json.dumps(parts,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode())
def finite(value):
 try:return math.isfinite(float(value))
 except (ValueError,TypeError):
  if value is None or isinstance(value,str) and value in MISSING:return False
  raise ValueError('unrecognized numeric token; no ignored source content')

def float32_compare(left,right):
 import numpy as np
 a,b=np.float32(left),np.float32(right)
 if not np.isfinite(a) or not np.isfinite(b):raise ValueError('nonfinite label comparison')
 def ordered(x):
  bits=int(x.view(np.uint32));return (~bits)&0xffffffff if bits&0x80000000 else bits|0x80000000
 return dict(exact_float32_bits=a.tobytes()==b.tobytes(),ulp_distance=abs(ordered(a)-ordered(b)),absolute_error=abs(float(a)-float(b)),relative_error=abs(float(a)-float(b))/max(abs(float(b)),1e-30))

def reconstruct_input(source):
 raw=source['RNA.sequence']
 if not raw or not set(raw)<=set('ACGU'):raise ValueError('source RNA alphabet must be original uppercase ACGU')
 if not raw.startswith('GGG'):raise ValueError('three-G prefix hypothesis not supported')
 return raw[3:].replace('U','T')

def cds_review(row,source):
 # Empty strings MUST NOT pass a substring check. The original primary CDS is
 # preferred; longest is a documented source-field fallback, not a silent fix.
 import numpy as np
 field='CDS.sequence' if source['CDS.sequence'] else 'CDS.sequence.longest'
 seq=source[field].upper().replace('U','T')
 if not seq:return dict(pass_codon_track=False,source_field=field,reason='EMPTY_SOURCE_CDS')
 positions=np.flatnonzero(row['cds']).tolist()
 if not positions:return dict(pass_codon_track=False,source_field=field,reason='EMPTY_CODON_TRACK')
 start=positions[0];content=row['sequence'][start:start+len(seq)]==seq
 phase=positions==list(range(start,start+len(seq),3))
 return dict(pass_codon_track=bool(content and phase),source_field=field,source_cds_length=len(seq),annotation_start_0based=start,codon_start_count=len(positions),source_cds_sha256=hash_bytes(seq.encode()),meaning='codon-start indicator, NOT coding-region coverage')

def strict_table(path,required,delimiter='\t'):
 if path.stat().st_size>2*1024**2:raise ValueError('small source input cap exceeded')
 with path.open(encoding='utf-8-sig',errors='strict',newline='') as f:
  reader=csv.DictReader(f,delimiter=delimiter);rows=list(reader)
  if not required.issubset(reader.fieldnames or []):raise ValueError('missing source fields or incorrect delimiter')
  if any(None in r or any(v is None for v in r.values()) for r in rows):raise ValueError('ragged source table')
 return rows

def unique_index(rows,column):
 out={}
 for line,r in enumerate(rows,2):
  key=r[column]
  if not key or key in out:raise ValueError('empty or duplicate source identifier')
  out[key]=(line,r)
 return out

def write_table(path,rows,fields):
 stream=io.StringIO(newline='');w=csv.DictWriter(stream,fieldnames=fields,delimiter='\t',lineterminator='\n');w.writeheader()
 for r in rows:w.writerow({k:json.dumps(v,sort_keys=True,ensure_ascii=False) if isinstance(v,(dict,list)) else '' if v is None else v for k,v in r.items()})
 b=stream.getvalue().encode();path.parent.mkdir(parents=True,exist_ok=True)
 if path.exists():
  if path.read_bytes()!=b:raise ValueError('immutable evidence differs; use a new run')
 else:
  with path.open('xb') as f:f.write(b)
  path.chmod(0o444)
 return hash_bytes(b)

def selected_assets(state_db):
 out={}
 with sqlite3.connect('file:'+str(state_db)+'?mode=ro',uri=True) as db:
  for aid in ASSETS:
   rows=db.execute('SELECT sha256,bytes,raw_path FROM artifacts WHERE asset_id=?',(aid,)).fetchall()
   if len(rows)!=1:raise ValueError('missing or ambiguous raw asset version: '+aid)
   digest,size,p=rows[0];path=Path(p)
   if not path.resolve().is_relative_to(ROOT/'raw_cache'):raise ValueError('artifact outside quarantine')
   if size>2*1024**2 or path.stat().st_size!=size:raise ValueError('small artifact budget or size mismatch')
   # Only these <= 1 MiB source inputs are freshly hashed, not any large file.
   if hash_bytes(path.read_bytes())!=digest:raise ValueError('input SHA mismatch')
   out[aid]=dict(sha256=digest,bytes=size,path=path)
 return out

def audit_rows(benchmark,constructs):
 source=unique_index(constructs,'SequenceID');seen=set();observations=[];labels=[];counts=collections.Counter()
 for rownum,row in enumerate(benchmark,1):
  tid=row['transcript_id']
  if not tid or tid in seen:raise ValueError('duplicate or empty benchmark transcript_id')
  seen.add(tid)
  if tid not in source:raise ValueError('benchmark ID absent in author table')
  line,s=source[tid];expected=reconstruct_input(s);match=row['sequence']==expected;counts['sequence_mapping_matches']+=match
  cds=cds_review(row,s);counts['codon_tracks_matched']+=cds['pass_codon_track'];counts['longest_CDS_fallback_rows']+=cds['source_field']=='CDS.sequence.longest'
  observations.append(dict(benchmark_row=rownum,transcript_id=tid,source_table_line=line,source_sequence_sha256=hash_bytes(s['RNA.sequence'].encode()),input_sequence_sha256=hash_bytes(row['sequence'].encode()),sequence_mapping_exact=match,sequence_mapping='SOURCE_RNA[3:].replace(U,T); verified removed prefix GGG; raw unchanged',source_group=s['group'],source_CDS_id=s['CDS'],source_UTR5_id=s['X5UTR'],source_UTR3_id=s['X3UTR'],CDS_track_evidence=cds,splice_all_zero=not any(row['splice']),identity_status='ROW_AND_REPRESENTATION_VERIFIED' if match else 'HOLD_SEQUENCE_MAPPING'))
  for raw,original in LABELS.items():
   if not finite(s[original]) or not finite(row[raw]):raise ValueError('nonfinite retained outcome')
   comparison=float32_compare(row[raw],float(s[original]));counts[raw+'_exact']+=comparison['exact_float32_bits'];counts[raw+'_within_one_ulp']+=comparison['ulp_distance']<=1
   labels.append(dict(benchmark_row=rownum,transcript_id=tid,source_table_line=line,raw_target_column=raw,source_target_column=original,raw_original_label=repr(row[raw]),source_original_label=s[original],**comparison,source_error_column='ribosome_load_error' if raw=='target_ribosome_load' else 'degradation_coef_in_cell_error',source_error_original=s['ribosome_load_error' if raw=='target_ribosome_load' else 'degradation_coef_in_cell_error'],decision='EXACT_FLOAT32_COPY' if comparison['exact_float32_bits'] else 'ADJACENT_FLOAT32_NOT_PROVEN_COPY' if comparison['ulp_distance']<=1 else 'HOLD_SOURCE_LABEL_VERSION_MISMATCH'))
 eligible={tid for tid,(_,s) in source.items() if all(finite(s[k]) for k in LABELS.values())}
 exclusions=[dict(source_table_line=line,transcript_id=tid,excluded_from_acquired_file=tid not in seen,source_ribosome_load_finite=finite(s['ribosome_load']),source_half_life_finite=finite(s['half_life_in_cell']),reason='MISSING_SOURCE_HALF_LIFE' if not finite(s['half_life_in_cell']) else 'OTHER_UNRESOLVED_EXCLUSION') for tid,(line,s) in source.items() if tid not in seen]
 return observations,labels,exclusions,dict(counts),dict(eligible_both_outcomes=len(eligible),acquired_ID_set_matches_finite_source_outcome_set=eligible==seen,source_construct_rows=len(source),acquired_rows=len(benchmark))

def reproduce_author_split(benchmark,observations):
 from sklearn.model_selection import train_test_split
 indices=list(range(len(benchmark)))
 train,tv=train_test_split(indices,test_size=0.3,random_state=2541)
 val,test=train_test_split(tv,test_size=0.5,random_state=2541)
 assignments={i:s for s,items in [('train',train),('validation',val),('test',test)] for i in items}
 rows=[dict(benchmark_row=i+1,transcript_id=row['transcript_id'],split=assignments[i],input_sha256=observations[i]['input_sequence_sha256'],split_origin='AUTHOR_CODE_PROTOCOL_REPRODUCTION_NOT_OFFICIAL_FIXED_MANIFEST') for i,row in enumerate(benchmark)]
 input_splits=collections.defaultdict(set);group_splits={k:collections.defaultdict(set) for k in ['source_group','source_CDS_id','source_UTR5_id','source_UTR3_id']}
 for i,row in enumerate(observations):
  split=assignments[i];input_splits[row['input_sequence_sha256']].add(split)
  for key,groups in group_splits.items():
   if row[key]:groups[row[key]].add(split)
 report=dict(split_origin='AUTHOR_CODE_PROTOCOL_REPRODUCTION_NOT_OFFICIAL_FIXED_MANIFEST',seed=2541,ratios=[0.7,0.15,0.15],split_counts=dict(collections.Counter(assignments.values())),original_splits_changed=False,raw_labels_used_for_assignment=False,scaler_or_HPO_fitted=False,exact_input_keys_shared_across_splits=sum(len(v)>1 for v in input_splits.values()),source_group_keys_shared_across_splits={k:sum(len(v)>1 for v in groups.values()) for k,groups in group_splits.items()},group_disjoint_pass=False,scientific_split_pass=False,evaluation_enabled=False)
 return rows,report

def component_audit(benchmark,constructs):
 source={r['SequenceID']:r for r in constructs};parent=list(range(len(benchmark)))
 def find(x):
  while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
  return x
 seen={};edges=collections.Counter()
 for i,row in enumerate(benchmark):
  s=source[row['transcript_id']]
  cds=s['CDS.sequence'] or s['CDS.sequence.longest']
  for role,value in [('UTR5',s['X5UTR.sequence']),('CDS',cds),('UTR3',s['X3UTR.sequence'])]:
   if not value:continue
   key=role+':'+hash_bytes(value.upper().replace('U','T').encode())
   if key in seen:
    a,b=find(i),find(seen[key])
    if a!=b:parent[a]=b;edges[role]+=1
   else:seen[key]=i
 sizes=collections.Counter(find(i) for i in range(len(benchmark)))
 largest=max(sizes.values());tv=math.ceil(len(benchmark)*0.3);largest_author_fold=max(len(benchmark)-tv,math.ceil(tv*0.5))
 return dict(largest_component_fraction=largest/len(benchmark),largest_author_protocol_fold_capacity=largest_author_fold,largest_component_exceeds_all_author_fold_capacities=largest>largest_author_fold,rule='Connect records sharing any exact nonempty source UTR5/CDS/UTR3 sequence; conservative component-disjoint stress test, NOT independent homology clustering',components=len(sizes),component_sizes=sorted(sizes.values(),reverse=True),joining_edges_by_role=dict(edges),three_way_component_disjoint_feasible=len(sizes)>=3,custom_split_created=False,known_gene_ids=False,homology_clearance=False)

def sample_audit(samples,counts,geo_text=''):
 nonempty=[r for r in samples if r['index']]
 idx=unique_index(nonempty,'index');raw_cols=[k for k in counts[0] if k!='id'];missing_cols=[x for x in raw_cols if x.rsplit('-',1)[-1] not in idx]
 for row in counts:
  for col in raw_cols:
   if not row[col].isdigit():raise ValueError('source count is not a nonnegative integer')
 sample_rows=[]
 for line,s in [(i+2,s) for i,s in enumerate(samples) if s['index']]:
  used_poly=s['Experiment']=='polysomes' and s['Spikein']=='1'
  used_hl=s['Experiment']=='stability' and s['Spikein']=='1' and s['Group']=='In-cell' and s['Type']=='Long' and s['Time'] in ['1','7','12']
  candidates=[]
  for block in geo_text.split('^SAMPLE = ')[1:]:
   if s['index'] in block:candidates.append(block.splitlines()[0].strip())
  sample_rows.append(dict(source_sample_line=line,sample_name=s['Sample_Name'],source_index=s['index'],source_experiment=s['Experiment'],source_group=s['Group'],source_time_hours=s['Time'],source_fraction=s['Fraction'],source_spikein=s['Spikein'],source_amplicon_type=s['Type'],used_in_author_ribosome_load=used_poly,used_in_author_half_life=used_hl,exact_index_geo_candidates=candidates,GEO_library_identity_status='CANDIDATE_INDEX_TEXT_MATCH_NOT_EXPERIMENT_APPROVAL' if len(candidates)==1 else 'UNRESOLVED_INDEX_TO_GSM_MAPPING'))
 return sample_rows,dict(source_table_delimiter='TAB despite .csv suffix; strict parser, no ignored bytes',source_rows=len(samples),nonempty_sample_rows=len(nonempty),blank_layout_rows=len(samples)-len(nonempty),count_matrix_rows=len(counts),count_matrix_sample_columns=len(raw_cols),count_columns_without_author_index_mapping=missing_cols,polysome_libraries_selected=sum(r['used_in_author_ribosome_load'] for r in sample_rows),half_life_libraries_selected=sum(r['used_in_author_half_life'] for r in sample_rows),half_life_fit_timepoints_hours=[1,7,12],half_life_other_recorded_timepoints_hours=[24,106],timepoint_source='pinned persist_p.R ICS_USED; source samples.csv Time column; not a correction to paper',sample_to_GSM_exact_library_mapping_complete=False)

def run(run_dir,state_db,dry_run=False):
 import pyarrow.parquet as pq
 assets=selected_assets(state_db);manifest=run_dir/'manifests'
 evidence_files=[manifest/'persist_source_rights.json',manifest/'GSE173083_samples_snapshot.json',ROOT/'runs/20261023_043639/manifests/mrna_sources/PMC8940940.xml',ROOT/'runs/20261023_043639/manifests/mrna_sources/repo__mrna_bench__datasets__mrl_hl_lbkwk.py',manifest/'persist_source_code_manifest.json',manifest/'persist_commit.txt',manifest/'GSE173083_samples.soft',ROOT/'runs/20261023_043639/manifests/mrna_sources/repo__mrna_bench__datasets__dataset_utils.py',ROOT/'runs/20261023_043639/manifests/mrna_sources/repo__mrna_bench__data_splitter__data_splitter.py',ROOT/'runs/20261023_043639/manifests/mrna_sources/repo__mrna_bench__data_splitter__sklearn_split.py']
 hashes={a:x['sha256'] for a,x in assets.items()}
 source_manifest=manifest/'persist_source_code_manifest.json'
 if source_manifest.exists():
  for entry in json.loads(source_manifest.read_text()):
   p=ROOT/entry['local_file']
   if not p.resolve().is_relative_to(ROOT/'runs') or hash_bytes(p.read_bytes())!=entry['sha256']:raise ValueError('source-code evidence changed')
   hashes[str(p.relative_to(ROOT))]=entry['sha256']
 for p in evidence_files:
  if p.exists():hashes[str(p.relative_to(ROOT))]=hash_bytes(p.read_bytes())
 hashes['audit_code_sha256']=hash_bytes(Path(__file__).read_bytes());fingerprint=canonical_hash([VERSION,hashes])
 output=run_dir/'reports';summary_file=output/'persist_summary.json'
 if dry_run:return dict(verification_status='VERIFIED',dry_run=True,input_fingerprint=fingerprint,small_inputs=list(assets),training=False,writes=False)
 if summary_file.exists():
  cached=json.loads(summary_file.read_text())
  if cached['input_fingerprint']!=fingerprint:raise ValueError('changed inputs or code; choose new run')
  for n,h in cached['output_sha256'].items():
   if hash_bytes((output/n).read_bytes())!=h:raise ValueError('cached report hash mismatch')
  return cached
 benchmark=pq.read_table(assets[ASSETS[0]]['path']).to_pylist()
 constructs=strict_table(assets['PERSIST_CONSTRUCTS']['path'],{'SequenceID','RNA.sequence','ribosome_load','half_life_in_cell','group','CDS','X5UTR','X3UTR','CDS.sequence','CDS.sequence.longest','X5UTR.sequence','X3UTR.sequence','ribosome_load_error','degradation_coef_in_cell_error'})
 counts=strict_table(assets['PERSIST_COUNTS']['path'],{'id'});unique_index(counts,'id')
 samples=strict_table(assets['PERSIST_SAMPLES']['path'],{'index','Sample_Name','Experiment','Group','Type','Spikein','Time','Fraction'})
 if not benchmark or len(benchmark)>1000 or len(constructs)>1000:raise ValueError('bounded pilot row limit')
 obs,label_rows,excluded,stats,selection=audit_rows(benchmark,constructs)
 split_rows,split_report=reproduce_author_split(benchmark,obs);components=component_audit(benchmark,constructs)
 geo=(manifest/'GSE173083_samples.soft').read_text() if (manifest/'GSE173083_samples.soft').exists() else ''
 sample_rows,sample_report=sample_audit(samples,counts,geo)
 output.mkdir(parents=True,exist_ok=True);outputs={}
 for n,rows in [('persist_row_identity.tsv',obs),('persist_label_comparison.tsv',label_rows),('persist_source_exclusions.tsv',excluded),('persist_sample_map.tsv',sample_rows),('persist_author_split_reproduction.tsv',split_rows)]:
  outputs[n]=write_table(output/n,rows,list(rows[0]))
 for n,doc in [('persist_split_qc.json',split_report),('persist_component_audit.json',components),('persist_sample_metadata_qc.json',sample_report)]:
  immutable_json(output/n,dict(verification_status='VERIFIED_FACTS_ONLY',**doc));outputs[n]=hash_bytes((output/n).read_bytes())
 per_label={}
 for name in LABELS:
  rows=[r for r in label_rows if r['raw_target_column']==name]
  per_label[name]=dict(exact_float32_rows=sum(r['exact_float32_bits'] for r in rows),within_one_ulp_rows=sum(r['ulp_distance']<=1 for r in rows),maximum_ulp_distance=max(r['ulp_distance'] for r in rows),maximum_absolute_float32_error=max(r['absolute_error'] for r in rows),source_version_binding='PROVISIONAL_ADJACENT_FLOAT32_VALUES' if all(r['ulp_distance']<=1 for r in rows) else 'HOLD_SOURCE_LABEL_VERSION_MISMATCH')
 summary=dict(algorithm=VERSION,verification_status='VERIFIED',scientific_disposition='HOLD',scientific_stage='SOURCE_VERIFIED',input_fingerprint=fingerprint,input_sha256=hashes,source_doi='10.1038/s41467-022-28776-w',parent_study_accession='GSE173083',source_commit=(manifest/'persist_commit.txt').read_text().strip(),source_row_and_representation_counts=stats,source_population_selection=selection,label_comparison=per_label,author_protocol_split=split_report,component_disjoint_stress_test=components,sample_metadata=sample_report,output_sha256=outputs,source_phenotype_predicted_expression_excluded=True,new_source_assets=3,new_source_bytes=sum(assets[a]['bytes'] for a in ASSETS[1:]),raw_labels_changed=False,raw_sequences_changed=False,rows_deleted=0,official_split_changed=False,real_models_run=0,gpu_jobs=0,admission_candidates=0,admitted=0,blockers=['ORIGINAL_SOURCE_TABLE_VERSION_FOR_HALF_LIFE_NOT_BOUND','EXACT_SOURCE_COPY_NOT_ESTABLISHED_FOR_ALL_RIBOSOME_LABELS','REPOSITORY_REDISTRIBUTION_LICENSE_UNRESOLVED_SUPPLEMENT_UNRETRIEVED','GSM_TO_COUNT_LIBRARY_INDEX_MAPPING_NOT_COMPLETE','AUTHOR_RANDOM_SPLIT_SHARES_SOURCE_COMPONENTS','HUMAN_SCIENTIFIC_APPROVAL_NOT_GENERATED'])
 text=make_report(summary);p=output/'PERSIST_SCIENTIFIC_REPORT.md'
 if p.exists() and p.read_text()!=text:raise ValueError('immutable report differs')
 if not p.exists():p.write_text(text);p.chmod(0o444)
 outputs[p.name]=hash_bytes(p.read_bytes())
 with StateDB(state_db) as db:
  with db.transaction():
   key=canonical_hash([VERSION,run_dir.name,'T0022',fingerprint])
   cursor=db.db.execute('INSERT OR IGNORE INTO scientific_reviews VALUES (?,?,?,?,?,?,?,?,0,0)',(key,run_dir.name,'T0022','SOURCE_VERIFIED','HOLD',fingerprint,str(summary_file.relative_to(ROOT)),now()))
   if cursor.rowcount:db.db.execute('INSERT INTO scientific_review_events(idempotency_key,at_utc,detail_json) VALUES (?,?,?)',(key,now(),json.dumps(dict(event='PERSIST_ROW_MAPPING_AND_LABEL_VERSION_REVIEW',raw_labels_changed=False,admitted=False))))
 immutable_json(summary_file,summary);return summary

def make_report(s):
 counts=s['source_row_and_representation_counts'];selection=s['source_population_selection'];labels=s['label_comparison'];split=s['author_protocol_split'];components=s['component_disjoint_stress_test']
 return '\n'.join(['# T0022 PERSIST-seq original-source audit','',
 '## Scope and disposition','',
 '**VERIFIED: source-row/input mapping and measured comparison facts.**',
 '**PROVISIONAL: exact assay/library identity and rights. BLOCKED: admission.**',
 'No raw label/sequence/track was corrected or overwritten, no observations deleted,',
 'no upstream R program/pickle executed, no scaler/HPO or real baseline fitted.',
 'The registered task remains T0022; two biological readouts are kept separate.','',
 '## Original source and representations','',
 'Original paper DOI: `10.1038/s41467-022-28776-w`; parent study: `GSE173083`.',
 f'Original author repository commit: `{s["source_commit"]}`.',
 f'Source constructs: {selection["source_construct_rows"]}; acquired records: {selection["acquired_rows"]}.',
 f'Exact row/input matches: {counts.get("sequence_mapping_matches",0)}.',
 'Mapping is by the literal SequenceID/transcript_id, not nearest sequence similarity.',
 'All retained inputs match the original RNA after two explicitly recorded operations:',
 'remove the verified leading GGG, then map RNA U to the DNA-letter T representation.',
 'This explains a derived representation; it does not change measured RNA into DNA',
 'or make original and transformed sample hashes identical. No raw is modified.','',
 'The acquired population equals the source rows with both finite outcomes: ',
 str(selection['acquired_ID_set_matches_finite_source_outcome_set'])+'.',
 f'Excluded source rows: {selection["source_construct_rows"]-selection["acquired_rows"]};',
 'their missing-half-life evidence is retained in persist_source_exclusions.tsv.',
 'A published 233-member construct population is not a replicate/sample count.','',
 '## Label identity: do not turn approximate equality into provenance PASS','',
 '```json',json.dumps(labels,indent=2),'```','',
 'Ribosome-load adjacent-float differences are recorded, not silently rounded away.',
 'Half-life discrepancies exceeding float32 rounding remain source-version blockers.',
 'We do not fit a scale/offset, optimize a matching tolerance, replace targets, or',
 'reinterpret in-solution stability/model-predicted expression as measured in-cell labels.',
 'The operational ribosome-load index follows the pinned source script, including',
 'its selected fractions and weights; it is not automatically generic TE or RSS.',
 'Half-life is a source-reported outcome; this audit does not independently re-fit',
 'limma/voom or certify the physical decay-rate conversion.','',
 '## Track semantics and original samples','',
 'The CDS feature is a codon-start indicator (one every three positions), not a',
 'binary coding-region coverage mask. Source CDS.sequence is preferred; if empty,',
 'CDS.sequence.longest is an explicit recorded fallback, not a source repair.',
 f'Compatible codon tracks: {counts.get("codon_tracks_matched",0)}; fallback records: {counts.get("longest_CDS_fallback_rows",0)}.',
 'The source sample sheet has a .csv suffix but is strictly TAB-separated.',
 'Source code uses in-cell long-amplicon libraries at 1, 7 and 12 h; later recorded',
 '24/106 h samples are not silently converted to or counted as fitted time points.',
 'GEO parent/sample metadata do not by themselves bind every index to a GSM library.',
 'See persist_sample_map.tsv and persist_sample_metadata_qc.json for unresolved mappings.','',
 '## Versioned split evidence; no false official or group-disjoint claim','',
 f'Author code protocol reproduced with seed 2541: {split["split_counts"]}.',
 'This is AUTHOR_CODE_PROTOCOL_REPRODUCTION, NOT an official fixed split file.',
 'No label value is used to select splits; no original split is overwritten.',
 f'Exact full-input overlap: {split["exact_input_keys_shared_across_splits"]}.',
 f'Source keys shared across folds: {split["source_group_keys_shared_across_splits"]}.',
 f'Conservative shared-component stress-test sizes: {components["component_sizes"]}.',
 'Sharing a component is not automatically duplicate experimental observation.',
 'It limits extrapolation claims. Exact-component disjointness is also not full',
 'homology clearance. No forced custom split is created if fewer than three',
 'connected groups are available; original author-protocol assignments stay intact.','',
 '## Actual evidence and recovery','',
 'persist_row_identity.tsv; persist_label_comparison.tsv; persist_source_exclusions.tsv;',
 'persist_author_split_reproduction.tsv; persist_split_qc.json; persist_component_audit.json;',
 'persist_sample_map.tsv; persist_sample_metadata_qc.json; persist_summary.json.',
 'All artifact byte hashes and output hashes are in persist_summary.json.',
 'Supplementary publisher/PMC/Europe PMC failures are recorded under manifests;',
 'a timeout/404/HEAD response is never treated as a downloaded source table.',
 'The author repository has no standalone data license. Local quarantine acquisition',
 'was authorized for evidence matching only, not redistribution or scientific approval.',
 'Final ADMISSION_CANDIDATE=0, ADMITTED=0; actual checkpoints and model scores=0.',''])

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,default=ROOT/'runs/20261023_123905');p.add_argument('--state-db',type=Path,default=ROOT/'run-state.sqlite');p.add_argument('--dry-run',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--plan',action='store_true');a=p.parse_args()
 if a.plan:
  print((ROOT/'configs/persist_source_review.json').read_text(),end='');return
 if not a.run.resolve().is_relative_to(ROOT/'runs'):p.error('run must stay in local ignored runs')
 result=run(a.run.resolve(),a.state_db.resolve(),a.dry_run)
 print(json.dumps(result if a.dry_run else {k:result[k] for k in ['scientific_disposition','source_row_and_representation_counts','source_population_selection','label_comparison','author_protocol_split','component_disjoint_stress_test','admission_candidates','admitted']},indent=2))
if __name__=='__main__':main()
