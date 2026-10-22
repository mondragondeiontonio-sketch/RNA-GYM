#!/usr/bin/env python3
"""Small, conservative QC for sequence+label CSV; NOT a complete assay admission engine."""
from pathlib import Path
import argparse,csv,gzip,json,hashlib,collections,math,re,sys

def opencsv(path):
    return gzip.open(path,'rt',encoding='utf-8-sig',newline='') if str(path).endswith('.gz') else path.open(encoding='utf-8-sig',newline='')

def run(source:Path, spec:dict):
    seqcol=spec.get('sequence_col','sequence');labelcol=spec.get('label_col','label');splitcol=spec.get('split_col','split')
    split_explicit=bool(spec.get('require_split_column',True))
    alphabet=spec.get('alphabet','RNA');valid=set('ACGUN') if alphabet=='RNA' else set('ACGTN') if alphabet=='DNA' else set('ACGTUN')
    groupcols=spec.get('group_cols',[])
    seen={}; bysplit=collections.Counter(); groupmap={};fail=[]; rows=0; exact_identical=0; sequence_mixed_splits=0
    normalization_changed_rows=0
    digest=hashlib.sha256()
    with source.open('rb') as raw:
        for blob in iter(lambda:raw.read(1024*1024),b''):digest.update(blob)
    with opencsv(source) as fh:
        reader=csv.DictReader(fh)
        required={seqcol,labelcol}|({splitcol} if split_explicit else set())|set(groupcols)
        if not required.issubset(reader.fieldnames or []):
            return {'state':'SCHEMA_FAIL','missing_columns':sorted(required-set(reader.fieldnames or [])),'source_sha256':digest.hexdigest()}
        for n,r in enumerate(reader,2):
            rows+=1;raw_sequence=(r[seqcol] or '');seq=raw_sequence.strip().upper().replace(' ','');raw_label=r[labelcol]
            normalization_changed_rows+=int(seq!=raw_sequence)
            split=(r.get(splitcol) or 'UNSPECIFIED').strip()
            if not seq or not set(seq)<=valid:
                if len(fail)<20:fail.append({'line':n,'reason':'INVALID_OR_EMPTY_SEQUENCE'})
            try:
                val=float(raw_label)
                if not math.isfinite(val):raise ValueError('non-finite')
            except (TypeError,ValueError):
                if len(fail)<20:fail.append({'line':n,'reason':'INVALID_LABEL'})
            if split in ('','UNSPECIFIED') and split_explicit and len(fail)<20:fail.append({'line':n,'reason':'SPLIT_MISSING'})
            if seq in seen:
                exact_identical+=1
                if seen[seq]!=split:sequence_mixed_splits+=1
            else:seen[seq]=split
            group=tuple((r.get(c) or '').strip() for c in groupcols)
            if groupcols:
                if group in groupmap and groupmap[group]!=split and len(fail)<20:fail.append({'line':n,'reason':'GROUP_CROSS_SPLIT'})
                else:groupmap[group]=split
            bysplit[split]+=1
    if not rows:fail.append({'reason':'EMPTY_FILE'})
    state='SCHEMA_OR_LABEL_FAIL' if fail else 'EXACT_SPLIT_LEAKAGE_FAIL' if sequence_mixed_splits else 'PASS_EXACT_QC_ONLY'
    return {'state':state,'n_rows':rows,'n_unique_sequences':len(seen),'repeated_sequence_rows':exact_identical,'cross_split_sequence_rows':sequence_mixed_splits,'split_distribution':dict(bysplit),'first_issues':fail,'source_sha256':digest.hexdigest(), 'not_checked':['experimental identity','cross-benchmark sample matching','homology/structural leakage','source rights','assay label semantics','bioreplicate and uncertainty','in-distribution bias','full 2D/3D structural QC'], 'canonicalization':{'sequence':'strip outer whitespace, uppercase, remove ASCII spaces for exact scan only','changed_rows':normalization_changed_rows,'T_U_substitution':False,'raw_file_modified':False}, 'admission_gate_pass':False, 'admitted':False}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--file',required=True,type=Path);p.add_argument('--schema',required=True,type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args();res=run(a.file,json.loads(a.schema.read_text(encoding='utf-8')))
    content=json.dumps(res,ensure_ascii=False,indent=2)
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(content,encoding='utf-8')
    print(content)
    if res['state']!='PASS_EXACT_QC_ONLY':sys.exit(2)
if __name__=='__main__':main()
