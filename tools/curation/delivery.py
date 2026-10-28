"""Delivery ledger and remaining-work list, all numbers from current products."""
import collections
import csv
import hashlib
import json
import platform
import subprocess
from pathlib import Path
import numpy
import pyarrow
from .core import ROOT,RUN,VERSION,file_sha,write_json,write_tsv
from .review import read_reports


def main():
    summary=json.loads((ROOT/'data/audit/scientific_curation_summary.json').read_text())
    tasks=list(csv.DictReader((ROOT/'data/audit/task_dataset_overview.tsv').open(),delimiter='\t'))
    progress=[]
    for r in tasks:
        has=r['curated_data_local']=='True'
        state='EXCLUDED' if r['admission']=='EXCLUDED' else 'SPLIT_DONE' if r['split_pass']=='True' else 'DEDUP_DONE' if has else 'DISCOVERED'
        progress.append({'task_id':r['task_id'],'current_state':state,
            'schema_verified':has,'qc_done':has,'dedup_done':has,'split_done':r['split_pass']=='True',
            'review_ready':r['admission_review_ready']=='True','admitted':False,'remaining':r['blocker']})
    write_tsv(ROOT/'data/audit/curation_progress_198.tsv',progress)
    write_tsv(ROOT/'data/audit/supplementary_resource_gaps.tsv',[
        {'resource':'NABench per-assay CSV bytes','local_state':'not in bound 50-resource cache; external candidates not fully bound',
         'required_for':'RNAGym/NABench sample-level equality and nonoverlapping assays',
         'next_action':'Bind existing caches first; request only unresolved files, NOT a full re-download'},
        {'resource':'Original assay Supplements/processing recipes','local_state':'22 acquired primary XMLs, partial explicit QC extraction',
         'required_for':'per-assay filters, score transformation, sample/condition identities',
         'next_action':'Inspect existing evidence and author supplementary URLs; no bulk raw download authorized'},
        {'resource':'Other 198-row modalities and external cached tables','local_state':'6877 external candidates indexed, provenance binding incomplete',
         'required_for':'coverage of remaining schema-unbound registered rows',
         'next_action':'Match accession/construct/readout/version before copying, registering or downloading'}])
    write_tsv(ROOT/'data/audit/modality_findings.tsv',[
        {'unit':'EUKA_APA_Isoform_ac4368d20e3b','finding':'26331 sequences have a ten-X unknown prefix; input representation quarantined, measurement not declared false',
         'action':'No X-to-N conversion; original rows remain available'},
        {'unit':'DMS_Domingo_2018_tRNA','finding':'Primary Methods S11 reports 4176 retained genotypes; actual processed local table has 4175',
         'action':'One-variant difference UNKNOWN; do not fabricate a missing variant'},
        {'unit':'WANG_ts_70_key_seq_contact_idx','finding':'All source contact matrices are asymmetric',
         'action':'Keep all directed edges; no automatic symmetrization or upper-triangle deletion; base-pair interpretation pending'},
        {'unit':'PROBING_RMDB_s40','finding':'Nonfinite positions and author -999 sentinels are not valid nucleotide labels',
         'action':'Keep original vector strings; explicit finite-index masks; no label imputation'},
        {'unit':'EUKA_RNA_protein_interaction RNA-protein inputs','finding':'Protein N is asparagine, not an ambiguous nucleotide',
         'action':'Ignore the early generic AMBIGUOUS_BASES_SEQUENCE_B flag when sequence_b_kind=protein; stored protein letters, eligibility and labels are unchanged'},
        {'unit':'MRNA_mirna_preprocessed','finding':'20 binary presence/absence heads, not continuous regression or measured nonbinding labels',
         'action':'Authoritative task schema is positive-unlabeled multilabel classification; proposed regression metric in the early unit QC metadata is superseded by this erratum'}])
    reports=read_reports();manifest=[];bindings=collections.Counter()
    for r in reports:
        p=ROOT/r['output_path'];directory=p.parent
        provenance=json.loads((directory/'provenance.json').read_text())
        bindings[provenance.get('producer_binding','WORKING_TREE_AT_COMPLETION_ONLY')]+=1
        manifest.append({'unit_id':r['unit_id'],'curated_path':r['output_path'],'curated_sha256':r['output_sha256'],
            'qc_report_sha256':file_sha(directory/'qc_report.json'),
            'split_sha256':file_sha(directory/'splits/split_manifest.parquet'),
            'freeze_sha256':file_sha(directory/'freeze.json') if (directory/'freeze.json').exists() else None})
    config=json.loads((ROOT/'configs/scientific_curation.json').read_text());binary=ROOT/config['mmseqs']
    inputs=[ROOT/'configs/scientific_curation.json',RUN/'reference_sheet_final.complete.csv',
            ROOT/'data/registries/search_level_task_crosswalk_198.csv',ROOT/'data/registries/source_family_crosswalk_123.csv',
            ROOT/'data/registries/download_packages_47.csv',ROOT/'data/registries/RNAGym_NABench_DMS_ID_91.csv']
    toolchain={'python':platform.python_version(),'numpy':numpy.__version__,'pyarrow':pyarrow.__version__,
              'mmseqs_version':subprocess.check_output([str(binary),'version'],text=True).strip(),
              'mmseqs_sha256':file_sha(binary),'GPU_used':False}
    write_json(ROOT/'data/audit/curation_run_manifest.json',{'version':VERSION,'summary':summary,'toolchain':toolchain,
        'auxiliary_input_sha256':{str(p.relative_to(ROOT)):file_sha(p) for p in inputs},'datasets':manifest,
        'producer_binding_counts':dict(bindings),
        'reproducibility_limit':'Earlier development batches recorded working-tree hashes at completion, not a captured runtime snapshot. '
            'Their data and split hashes are independently validated; bitwise producer replay is NOT certified. '
            'Later batches retain start-of-run content-addressed code snapshots. No scientific admission is inferred.'})
    print(json.dumps({'datasets':len(manifest),'producer_binding_counts':dict(bindings),'toolchain':toolchain},indent=2))

if __name__=='__main__':main()
