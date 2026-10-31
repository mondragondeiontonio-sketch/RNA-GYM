#!/usr/bin/env python3
"""Versioned Structure bindings/splits from already-downloaded source bytes.

Does not edit the v1 freeze, raw data, author splits or human admission. Temporal
membership is not proof that every sequence was absent from FM pretraining.
"""
import collections
import csv
import hashlib
import json
from pathlib import Path
import tarfile
import zipfile

from tools.build_arena_v1 import ROOT, QC, table, load, dump, sha, tsv

OUT=ROOT/'runs/20261030_structure_engineering_smoke_v1'


def groups(records, component=False):
    parent=list(range(len(records)));seen={}
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i,row in enumerate(records):
        seq=row['sequence'].upper().replace('T','U')
        keys=[('pdb',row['pdb_entry'].lower()),('sequence',hashlib.sha256(seq.encode()).hexdigest())]
        if component and row.get('component_id'): keys.append(('component',row['component_id']))
        for key in keys:
            if key in seen: parent[find(i)]=find(seen[key])
            else: seen[key]=i
    buckets=collections.defaultdict(list)
    for i,r in enumerate(records): buckets[find(i)].append(r['observation_id'])
    ids={k:hashlib.sha256('\n'.join(sorted(v)).encode()).hexdigest() for k,v in buckets.items()}
    return [ids[find(i)] for i in range(len(records))]


def verify_leakage(assignments):
    keys=('group_id','pdb_entry','equivalent_input_sha256')
    leakage={}
    for key in keys:
        roles=collections.defaultdict(set)
        for row in assignments:
            if row['role']!='QUARANTINE': roles[row[key]].add(row['role'])
        leakage[key+'_cross_role']=sum(len(v)>1 for v in roles.values())
    if any(leakage.values()): raise ValueError('CROSS_SPLIT_LEAKAGE')
    return leakage


def split(records,name,difficulty,*,component=False,temporal=False):
    gids=groups(records,component=component)
    unique=sorted(set(gids))
    if len(unique)<3: return dict(protocol=name,status='NOT_FEASIBLE',n_groups=len(unique))
    if temporal:
        dates=collections.defaultdict(set)
        for r,g in zip(records,gids):
            date=r['release_date']
            dates[g].add('train' if date<='2022-12-31' else 'validation' if date<='2023-12-31' else 'test')
        role={g:next(iter(v)) if len(v)==1 else 'QUARANTINE' for g,v in dates.items()}
    else:
        # Label-blind 60/20/20 assignment of connected biological groups.
        role={g:'test' if i%5==0 else 'validation' if i%5==1 else 'train' for i,g in enumerate(unique)}
    assignments=[]
    for r,g in zip(records,gids):
        assignments.append(dict(observation_id=r['observation_id'],pdb_entry=r['pdb_entry'],
            equivalent_input_sha256=hashlib.sha256(r['sequence'].upper().replace('T','U').encode()).hexdigest(),
            group_id=g,component_id=r.get('component_id',''),release_date=r.get('release_date',''),role=role[g]))
    counts=collections.Counter(r['role'] for r in assignments)
    feasible=all(counts[k]>0 for k in ('train','validation','test'))
    directory=ROOT/'data/splits'/name
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/'assignments.tsv'
    if target.exists():
        # Any new split membership must get a new version.
        candidate=OUT/(name+'_assignments.candidate.tsv');tsv(candidate,assignments)
        if sha(candidate)!=sha(target): raise ValueError('IMMUTABLE_SPLIT_CONFLICT')
    else: tsv(target,assignments)
    metadata=dict(protocol=name,difficulty=difficulty,status='SPLIT_PASS' if feasible else 'NOT_FEASIBLE',
        n_records=len(records),n_groups=len(unique),role_counts=dict(counts),
        assignment_sha256=sha(target),leakage=verify_leakage(assignments),
        group_policy='PDB-entry + U/T-equivalent exact sequence connected components'+(' + official RNA3DB Infernal/Rfam homology components' if component else ''),
        temporal_cutoffs={'train_end':'2022-12-31','validation_end':'2023-12-31','test_start':'2024-01-01'} if temporal else None,
        boundary_policy='quarantine ENTIRE cross-boundary connected component; never move old structures into a temporal test' if temporal else None,
        raw_or_author_splits_modified=False,human_admitted=False,
        scientific_label_admission='SEPARATE_REVIEW_REQUIRED',pretraining_exposure='UNKNOWN_NOT_PROVEN_ABSENT')
    dump(directory/'manifest.json',metadata)
    return metadata


def run():
    import pyarrow as pa
    import pyarrow.parquet as pq
    assets={r['asset_id']:r for r in table(ROOT/'data/audit/local_inventory.tsv')}
    source=assets['RNA3DB_20260105_rna3db_jsons'];path=ROOT/source['path']
    if sha(path)!=source['sha256']: raise ValueError('RNA3DB_METADATA_HASH_CHANGED')
    objects={}
    with tarfile.open(path,'r:gz') as tar:
        for member in tar:
            if member.isfile() and member.name.endswith(('filter.json','cluster.json')):
                if member.size>64*1024*1024: raise ValueError('METADATA_BUDGET')
                objects[Path(member.name).name]=json.load(tar.extractfile(member))
    mapping={}
    for component,families in objects['cluster.json'].items():
        for rep,members in families.items():
            for chain in members: mapping[chain]=(component,rep)
    records=[]
    for chain,r in sorted(objects['filter.json'].items()):
        if chain not in mapping: raise ValueError('CHAIN_COMPONENT_MISSING')
        records.append(dict(observation_id=chain,pdb_entry=chain.split('_')[0],sequence=r['sequence'],
            release_date=r['release_date'],component_id=mapping[chain][0],representative=mapping[chain][1]))
    splits=[]
    splits.append(split(records,'RNAGYM_RNA3DB_RANDOM_D1_V1_1','D1_STANDARD'))
    splits.append(split(records,'RNAGYM_RNA3DB_HOMOLOGY_D2_V1_1','D2_GENERALIZATION',component=True))
    splits.append(split(records,'RNAGYM_RNA3DB_TEMPORAL_D3_V1_1','D3_OOD',temporal=True))
    dump(OUT/'rna3db_source_binding.json',dict(source_asset_id=source['asset_id'],source_sha256=source['sha256'],
        n_chain_records=len(records),n_pdb_entries=len({r['pdb_entry'] for r in records}),
        n_infernal_components=len({r['component_id'] for r in records}),
        release_date_min=min(r['release_date'] for r in records),release_date_max=max(r['release_date'] for r in records),
        split_manifests=splits,coordinate_label_alignment='NOT_COMPLETED_BY_METADATA_SPLITTING',
        canonical_DMP_CMP_admission=False))
    # Canonical candidate view from original released labels and an explicit upper-triangle evaluation view.
    wang=[];audits=[]
    for unit in ['WANG_vl_40_key_seq_contact_idx','WANG_ts_70_key_seq_contact_idx']:
        d=ROOT/'data/processed'/unit/QC
        q=load(d/'qc_report.json');freeze=load(d/'freeze.json')
        if sha(d/'curated_data.parquet')!=freeze['files']['curated_data.parquet']: raise ValueError('WANG_FREEZE_CHANGED')
        rs=pq.read_table(d/'curated_data.parquet').to_pylist()
        lower=0;positive=0
        for r in rs:
            label=json.loads(r['label_json']);idx=label['index_mapping'];edges=label['directed_contact_edges_local_zero_based']
            if len(set(idx))!=len(idx) or any(i<0 or i>=len(r['sequence']) for i in idx): raise ValueError('INVALID_SEQUENCE_RESIDUE_MAP')
            pairs=[]
            for i,j in edges:
                if not (0<=i<len(idx) and 0<=j<len(idx)) or i==j: raise ValueError('INVALID_PAIR_LABEL')
                lower+=int(i>j);positive+=1
                # No automatic symmetrization and no dropping lower-oriented edges.
                pairs.append([idx[i],idx[j]])
            context=json.loads(r['context_json']);chain=context['source_chain']
            wang.append(dict(observation_id=r['observation_id'],pdb_entry=chain.split('_')[0],
                sequence=r['sequence'],source_chain=chain,source_view=unit,pairs_json=json.dumps(pairs),
                resolved_index_json=json.dumps(idx),source_record_id=r['record_id'],source_curated_sha256=freeze['files']['curated_data.parquet']))
        audits.append(dict(unit_id=unit,reported_author_release_n=q['actual_n'],qc_valid_n=len(rs),
            quarantined_n=q.get('quarantined_n'),positive_directed_edges=positive,lower_oriented_edges=lower,
            source_task_declared='secondary structure prediction (Wang README, RNA-MSM source citation)',
            source_evaluation_rule='strict upper triangle (torch.triu(...,1)) with original residue mask',
            label_candidate='SSP' if lower==0 else 'TAXONOMY_REVIEW_REQUIRED',
            release_license='CC-BY-4.0 in official Zenodo metadata; original-source chain separate',
            admission_recommendation='HOLD_PENDING_TARGET_DERIVATION_AND_HUMAN_REVIEW',
            model_smoke_score_used_for_admission=False))
    target=ROOT/'data/processed/WANG_SSP_RELEASE_CANDIDATE_V1_1';target.mkdir(parents=True,exist_ok=True)
    pq.write_table(pa.Table.from_pylist(wang),target/'observations.parquet')
    d1=split(wang,'RNAGYM_WANG_PDB_GROUPED_D1_V1_1','D1_STANDARD')
    dump(target/'provenance.json',dict(source_scope='VL1+TS released RNA-MSM labels in Wang v4 supplement',
        observation_n=len(wang),label_interpretation='secondary-structure source confirmed; original annotation-version/derivation remains explicit review item',
        orientation='preserved; upstream evaluates upper triangle',source_evidence='runs/20261030_structure_engineering_smoke_v1/source_evidence/',
        canonical_task_candidate='SSP',formal_admitted=False,split=d1))
    tsv(OUT/'structure_label_binding_audit.tsv',audits)
    dump(OUT/'structure_split_summary.json',dict(rna3db=splits,wang_d1=d1,
        wang_qc_records=len(wang),human_approvals_generated=0,
        warning='split_pass and technical smoke_pass do NOT grant scientific admission'))
    print(json.dumps(load(OUT/'structure_split_summary.json'),ensure_ascii=False,indent=2))


if __name__=='__main__': run()
