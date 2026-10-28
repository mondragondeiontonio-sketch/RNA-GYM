"""Explicit adapters for acquired author-processed resources.

Each adapter separates the measured construct claim from the literal input.
No pickle or author code from an archive is executed.
"""
import collections
import csv
import gzip
import io
import json
import math
import re
import tarfile
import zipfile
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from .core import ROOT, RUN, Curator, sha


def parquet_rows(path):
    for batch in pq.ParquetFile(path).iter_batches(batch_size=256):
        yield from batch.to_pylist()


def mrna_jobs(all_assets):
    evidence = json.loads((ROOT/'data/audit/phase2_mrna_source_evidence.json').read_text())
    schemas = json.loads((ROOT/'configs/full_qc_schemas.json').read_text())['packages']
    for ev in evidence['records']:
        aid = ev['asset_id']
        asset = all_assets[aid]
        package = asset['package_group_id']
        spec = schemas[package]
        schema = pq.ParquetFile(asset['raw_path']).schema_arrow.names
        targets = dict(spec.get('targets',{}))
        if spec.get('target_prefix'):
            targets.update({k:spec.get('target_kind') for k in schema if k.startswith(spec['target_prefix'])})
        proxy = ev.get('task_kind') in ['ANNOTATION_PROXY','VARIANT_PROXY'] or package in [
            'MRNA_GO_MF','MRNA_PROTEIN_LOCALIZATION','MRNA_VEP_TRAITGYM_MRNA','MRNA_UTR_VARIANTS_BOHN']
        binary = len(targets)==1 and all(x=='binary' or x=='categorical_unverified' for x in targets.values())
        unit = asset['filename'].replace('.parquet','')
        identity_status = 'VERIFIED_STUDY_NOT_UNIQUE_EXPERIMENT'
        plan = dict(unit_id='MRNA_'+unit, package_group_id=package, task_ids=ev['registered_task_ids'],
            assay_id='STUDY:'+ev['source_doi']+':'+unit, assay_identity_status=identity_status,
            independently_verified_assay=False, source=ev['source_project'], source_doi=ev['source_doi'],
            input_schema={'sequence':'literal mature transcript or synthetic construct string',
                          'annotations':['cds','splice'], 'construct_boundary_claim': 'SOURCE_SPECIFIC_NOT_ASSUMED_FULL_UTR'},
            target_schema=targets, readout_id=unit, label_definition=ev['label_definition'],
            label_unit=ev.get('label_unit') or 'UNRESOLVED_SOURCE_SCALE',
            experimental_context=ev.get('experimental_conditions'), modality='regulatory',
            problem_type='binary_classification' if binary else 'multilabel_classification' if proxy else 'regression_or_multioutput',
            metric='AUROC+AUPRC+MCC' if binary else 'per_head AUROC+AUPRC' if proxy else 'per_readout Spearman+RMSE',
            proxy=proxy,binary=binary,upstream_processed=True,
            evidence_path='data/audit/phase2_mrna_source_evidence.json#'+aid,
            scientific_gaps=['source-specific conditions/replicates', 'data-specific rights', 'manual review']+
                            (['source assay identity'] if ev.get('original_assay_id') is None else []),
            reported_n=ev.get('original_sample_count'))
        def rows(aid=aid,asset=asset,targets=targets):
            for n,row in enumerate(parquet_rows(asset['raw_path']),1):
                errors=[]
                seq=row.get('sequence')
                for track in ['cds','splice']:
                    v=row.get(track)
                    if not isinstance(v,list) or len(v)!=len(seq or '') or set(v)-{0,1}:
                        errors.append('INVALID_ANNOTATION_TRACK:'+track)
                label={k:row.get(k) for k in targets}
                if len(label)==1 and next(iter(targets.values())).startswith('categorical'):
                    label=next(iter(label.values()))
                ident={k:row[k] for k in ['transcript_id','gene','gene_id','variant_id'] if k in row and row[k] is not None}
                groups={}
                for key in ['gene','gene_id']:
                    if row.get(key):groups['gene']=row[key]
                # Transcript identity: conservatively isolate its declared ID,
                # but do not guess gene IDs by truncating arbitrary strings.
                if row.get('transcript_id'):groups['transcript']=row['transcript_id']
                yield dict(sequence=seq,label=label,identity={'released_row':n,'asset_id':aid,'construct_id':ident},
                    group_metadata=groups,context={},errors=errors),aid,n,'',row.get('split')
        yield plan,rows


def dms_metadata():
    p=RUN/'reference_sheet_final.complete.csv'
    result={}
    if p.is_file() and p.stat().st_size==60608:
        with p.open(encoding='utf-8-sig') as f:
            result={r['DMS_ID']:r for r in csv.DictReader(f)}
    # The local official secondary-source metadata is a fallback, not claimed
    # as an original assay Methods audit.
    return result


def dms_jobs(all_assets):
    meta=dms_metadata()
    aid='P0_RNAGYM_PROCESSED'
    with zipfile.ZipFile(all_assets[aid]['raw_path']) as z:
        members=sorted(n for n in z.namelist() if n.startswith('assays/') and n.endswith('.csv'))
    for member in members:
        alias=Path(member).stem
        ev=meta.get(alias,{})
        category=ev.get('RNA_TYPE','UNKNOWN')
        direct=category.lower() not in ['mrna-coding','mrna','unknown',''] and not re.search(r'protein',category,re.I)
        task_ids=['T0014','T0108'] + (['T0032'] if category.lower() in ['ribozyme','trna','aptamer'] else [])
        if direct:
            task_ids+=['T0086' if 'trna' in category.lower() else 'T0087' if 'aptamer' in category.lower() else 'T0085' if category.lower().startswith('mrna') else 'T0088']
        else:task_ids+=['T0085']
        plan=dict(unit_id='DMS_'+alias,package_group_id='RNAGYM_DMS',task_ids=task_ids,
            assay_id='DMS:'+alias,assay_identity_status='AUTHOR_ASSAY_METADATA_MATCH' if ev else 'ASSAY_ALIAS_ONLY',
            independently_verified_assay=bool(ev),source=ev.get('TITLE',alias),
            source_doi='UNKNOWN',readout_id='DMS_score',
            input_schema={'sequence':'released full construct variant, DNA or RNA alphabet',
                'wild_type':ev.get('RAW_CONSTRUCT_SEQ')},
            target_schema={'DMS_score':'continuous'},
            label_definition=ev.get('ASSAY_DESCRIPTION','unresolved original experimental phenotype'),
            label_unit='author assay-specific DMS score; not harmonized across assays',
            modality='dms',problem_type='regression',metric='per-assay Spearman; RMSE secondary',
            binary=False,proxy=not direct, rna_type=category,
            evidence_path='runs/20261028_scientific_curation/reference_sheet_final.complete.csv#'+alias,
            reported_n=None,
            scientific_gaps=['original source Methods QC not fully re-audited','assay-specific score direction/unit',
                             'data-specific rights','manual review'])
        def rows(member=member,ev=ev,aid=aid):
            wt=ev.get('RAW_CONSTRUCT_SEQ','').upper().replace('T','U')
            with zipfile.ZipFile(all_assets[aid]['raw_path']) as z:
                with z.open(member) as f:
                    reader=csv.DictReader(io.TextIOWrapper(f,encoding='utf-8-sig'))
                    if not {'sequence','DMS_score','mutant'}<=set(reader.fieldnames or []):
                        raise ValueError('DMS_SCHEMA_MISMATCH')
                    for n,r in enumerate(reader,1):
                        flags=[];errors=[]
                        seq=r['sequence'];normalized=seq.upper().replace('T','U')
                        mutation=r['mutant'] or ''
                        toks=[t for t in re.split(r'[,;:]',mutation) if t]
                        substitutions=[]
                        for t in toks:
                            m=re.fullmatch(r'([ACGTU])(\d+)([ACGTU])',t.strip())
                            if not m:
                                flags.append('NON_SUBSTITUTION_OR_UNRESOLVED_MUTATION_NOTATION');continue
                            a,pos,b=m.groups();pos=int(pos)
                            substitutions.append([a,pos,b])
                            if wt:
                                if not 1<=pos<=len(wt):errors.append('MUTATION_OUT_OF_WT_BOUNDS');continue
                                if wt[pos-1]!=a.replace('T','U'):errors.append('MUTATION_REFERENCE_MISMATCH')
                                if len(normalized)==len(wt) and normalized[pos-1]!=b.replace('T','U'):
                                    errors.append('VARIANT_MUTATION_IDENTITY_MISMATCH')
                        if wt and len(wt)!=len(normalized):
                            flags.append('VARIANT_LENGTH_DIFFERS_FROM_WT_INDEL_REVIEW')
                        if not wt:flags.append('WT_REFERENCE_UNBOUND')
                        if not mutation and wt and normalized!=wt:
                            flags.append('EMPTY_MUTANT_NON_WT_SEQUENCE')
                        try:label=float(r['DMS_score'])
                        except (ValueError,TypeError):label=None
                        yield dict(sequence=seq,label=label,identity={'mutation':mutation,'sequence':seq},
                            context={},group_metadata={},flags=flags,errors=errors),aid,n,member,None
        yield plan,rows

    yield from cv_only_jobs(all_assets)

def paired_jobs(all_assets):
    datasets=collections.defaultdict(list)
    for aid,a in all_assets.items():
        if a['package_group_id']=='MIR_BENCH' and 'MIRROR' not in aid:
            dataset=re.sub(r'_(train|test|leftout)\.tsv\.gz$','',a['filename'])
            datasets[dataset].append(aid)
    for name,aids in sorted(datasets.items()):
        plan=dict(unit_id='PAIR_'+name, package_group_id='MIR_BENCH',
            task_ids=['T0062','T0063'] if 'Manakov' in name else [],
            assay_id='MIRBENCH:'+name, independently_verified_assay=False,
            assay_identity_status='STUDY_AND_ASSAY_TYPE_NOT_ACCESSION',source=name,
            readout_id='label', label_definition='miRNA + target-window interaction; negative sampling must remain source-specific',
            label_unit='binary 0/1', modality='paired',problem_type='binary_classification',metric='AUPRC+AUROC+MCC',
            input_schema={'sequence':'gene column is a target RNA window, NOT gene symbol',
                          'sequence_b':'noncodingRNA column is miRNA sequence'},
            target_schema={'label':'binary'},binary=True,proxy=False,
            evidence_path='runs/20261022_212625/reports/paired_full_qc_summary.json',
            scientific_gaps=['negative-sample experimental interpretation','original assay accession','rights','manual review'])
        def rows(aids=aids):
            for aid in sorted(aids):
                a=all_assets[aid];split=a['filename'].split('_')[-1].split('.')[0]
                with gzip.open(a['raw_path'],'rt',encoding='utf-8-sig') as f:
                    reader=csv.DictReader(f,delimiter='\t')
                    if not {'gene','noncodingRNA','label'}<=set(reader.fieldnames or []):
                        raise ValueError('PAIR_SCHEMA_MISMATCH')
                    for n,r in enumerate(reader,1):
                        try:label=float(r['label'])
                        except (TypeError,ValueError):label=None
                        ctx={k:r[k] for k in ['chr','start','end','strand','feature'] if k in r}
                        ident={k:r[k] for k in ['chr','start','end','strand','noncodingRNA_name'] if k in r}
                        groups={}
                        if r.get('gene_cluster_ID') not in (None,'','unknown','nan'):
                            groups['gene_cluster']=r['gene_cluster_ID']
                        if r.get('noncodingRNA_fam') not in (None,'','unknown','nan'):
                            groups['mirna_family']=r['noncodingRNA_fam']
                        yield dict(sequence=r['gene'],sequence_b=r['noncodingRNA'],label=label,
                            identity=ident or None,context=ctx,group_metadata=groups),aid,n,'',split
        yield plan,rows


def _probing_partition_jobs(all_assets):
    # Both files contain both probes; preserve modifier and reaction condition.
    for aid in ['HF_077f265b2add15269941','HF_e567b1f79ef75075abec']:
        asset=all_assets[aid]
        plan=dict(unit_id='PROBING_'+asset['filename'].replace('.parquet',''),
            package_group_id='RNAGYM_RMDB',task_ids=['T0015','T0035','T0036','T0109'],
            assay_id='RMDB:conditioned_sequence_measurements',independently_verified_assay=False,
            assay_identity_status='AGGREGATED_MULTIPLE_ORIGINAL_ASSAYS',source='RMDB s40 author-processed release',
            readout_id='reactivity_per_modifier',label_definition='per-nucleotide chemical probing reactivity, not base-pair labels',
            label_unit='author-normalized reactivity; modifier-specific',
            input_schema={'sequence':'released assayed construct, including constant regions',
                'context':['modifier','temperature','chemical','reverse_transcriptase']},
            target_schema={'reactivity':'serialized per-nucleotide array','reactivity_error':'serialized error array'},
            modality='probing',problem_type='per_nucleotide_regression',metric='per-sequence Pearson+MAE; mask nonfinite positions',
            binary=False,proxy=False,evidence_path='runs/20261022_212625/reports/probing_qc_summary.json',
            label_distribution_scope='distribution of per-sequence mean reactivity; not pooled nucleotide quantiles',
            scientific_gaps=['original RMDB experiment accession mapping','per-study upstream QC/units','rights','manual review'])
        def rows(aid=aid,asset=asset):
            vector=_probing_vector
            for n,r in enumerate(parquet_rows(asset['raw_path']),1):
                errors=[];flags=[];mask={};finite=[];valid_count=0
                for col in ['reactivity','reactivity_error']:
                    try:
                        a=vector(r[col])
                        if len(a)!=len(r.get('sequence') or ''):errors.append('VECTOR_LENGTH_MISMATCH:'+col)
                        good=np.isfinite(a)&(a!=-999.0)
                        mask[col]={'finite_indices':np.flatnonzero(good).tolist()}
                        if col=='reactivity':
                            valid_count=int(good.sum())
                            finite=[float(a[good].mean())] if valid_count else []
                            if (~good).any():flags.append('MISSING_OR_AUTHOR_SENTINEL_NUCLEOTIDE_LABELS_MASKED')
                            if (a[good]<0).any():flags.append('NEGATIVE_FINITE_REACTIVITY_RETAINED')
                    except (ValueError,TypeError,Warning):errors.append('VECTOR_PARSE_FAILED:'+col)
                if r.get('SNR') is None or not math.isfinite(r['SNR']):flags.append('SNR_UNAVAILABLE')
                # No invented low-coverage threshold: original evidence and
                # raw SNR/reads remain attached to each usable record.
                ctx={k:r.get(k) for k in ['modifier','temperature','chemical','reverse_transcriptase']}
                ctx.update(reads=r.get('reads'),SNR=r.get('SNR'))
                # Read depth/SNR are measurement metadata, not condition IDs.
                ident={'seqID':r.get('seqID')}
                yield dict(sequence=r.get('sequence'),label={k:r[k] for k in ['reactivity','reactivity_error']},
                    identity=ident,context=ctx,finite_labels=finite,finite_label_mask=mask,
                    valid_nucleotide_labels=valid_count,flags=flags,errors=errors),aid,n,'',('train' if 'train' in asset['filename'] else 'test')
        yield plan,rows


def structure_jobs(all_assets):
    aid='RNA3DB_20260105_rna3db_jsons'
    coords='RNA3DB_20260105_rna3db_mmcifs'
    cache=ROOT/'runs/20261022_212625/reports'
    summary=json.loads((cache/'rna3db_atom_identity_qc.json').read_text())
    if summary['source_sha256']!=all_assets[coords]['sha256']:
        raise ValueError('COORDINATE_QC_HASH_MISMATCH')
    coordinate_rows=[json.loads(x) for x in (cache/'rna3db_coordinate_entries.jsonl').read_text().splitlines()]
    by_member={x['member']:x for x in coordinate_rows}
    by_chain=collections.defaultdict(list)
    for x in coordinate_rows:
        parts=Path(x['member']).parts
        for chain_alias in {x.get('entry_id'),Path(x['member']).stem.replace('-','')}:
            by_chain[(parts[1],parts[2],chain_alias)].append(x)
    with tarfile.open(all_assets[aid]['raw_path']) as archive:
        filtered=json.load(archive.extractfile('rna3db-jsons/filter.json'))
        split=json.load(archive.extractfile('rna3db-jsons/split.json'))
    membership={}
    for role,components in split.items():
        for component,clusters in components.items():
            for representative,chains in clusters.items():
                for chain in chains:membership[chain]=(role,component,representative)
    plan=dict(unit_id='RNA3DB_20260105',package_group_id='RNA3DB',task_ids=['T0033','T0034','T0074'],
        assay_id='PDB:RNA_chain_observations',independently_verified_assay=False,
        assay_identity_status='PDB_CHAIN_IDENTITY_NOT_EXPERIMENT_INDEPENDENCE',source='RNA3DB 2026-01-05 matched metadata+coordinates',
        readout_id='chain_coordinates',label_definition='experimental chain coordinates; missing atom/residue and assembly interpretation require review',
        label_unit='angstrom; full mmCIF coordinate member referenced by SHA256',modality='structure3d',
        input_schema={'sequence':'RNA3DB filtered chain polymer sequence, NOT assumed all resolved residues',
                      'structure':'matched coordinate member reference'},
        target_schema={'coordinates':'content-addressed mmCIF member, model/chain identifiers in cached evidence'},
        problem_type='structure_prediction',metric='RNA-aware lDDT/TM-score; coordinate mask and chain mapping required',
        binary=False,proxy=False,evidence_path='runs/20261022_212625/reports/rna3db_atom_identity_qc.json',
        scientific_gaps=['full polymer-to-observed-residue alignment','biological assembly selection',
                         'clash/stereochemical QC','rights','manual review'])
    def rows():
        for n,(chain,r) in enumerate(sorted(filtered.items()),1):
            if chain not in membership:
                yield dict(sequence=r['sequence'],label=None,errors=['CHAIN_WITHOUT_RELEASE_MEMBERSHIP']),aid,n,'rna3db-jsons/filter.json',None
                continue
            role,component,representative=membership[chain]
            # RNA3DB encodes case-sensitive chain IDs in its path. Use existing
            # observed paths; no coordinate residue mapping inferred from names.
            expected_prefix=f'rna3db-mmcifs/{role}/{component}/'
            candidates=by_chain.get((role,component,chain),[])
            flags=['ASSEMBLY_AND_RESIDUE_MAPPING_REVIEW_PENDING']
            if len(candidates)!=1:
                yield dict(sequence=r['sequence'],label=None,identity=chain,
                    errors=['COORDINATE_MEMBER_MAPPING_NOT_UNIQUE']),aid,n,'rna3db-jsons/filter.json',role
                continue
            coordinate=candidates[0]
            if coordinate['nonfinite_coordinate_values']:
                errors=['NONFINITE_COORDINATES']
            else:errors=[]
            resolution=r.get('resolution')
            if not isinstance(resolution,(int,float)) or not math.isfinite(resolution):resolution=None
            yield dict(sequence=r['sequence'],label={'coordinate_asset_id':coords,
                'archive_sha256':all_assets[coords]['sha256'],'member':coordinate['member'],
                'member_sha256':coordinate['member_sha256']},structured_target_valid=True,
                finite_labels=[],identity=chain,context={'pdb_chain':chain,'structure_method':r.get('structure_method'),
                    'resolution':resolution,'n_atoms':coordinate['atom_rows']},
                group_metadata={'rna3db_component':component,'structure_cluster':representative},
                errors=errors,flags=flags),aid,n,'rna3db-jsons/filter.json',role
    yield plan,rows


def euka_jobs(all_assets):
    staged=json.loads((RUN/'euka_stage.json').read_text())
    groups={}
    for r in staged['chosen']:
        name=r['source_protocol']
        if 'checkpoint' in name:continue
        # Choose one full outer partition representation, not ten copies of it.
        key=re.sub(r'(?:/|[.])cv_10fold.*$','',name)
        if '/m6A_modification/' in name:key=re.sub(r'/[0-9]+$','',name)
        if '/Rabani_degradation_rate/' in name:
            key='downstream_data/Rabani_degradation_rate/1022/all_readouts'
        rank=('cv_10fold' in name,len(name),name)
        if key not in groups or rank<groups[key][0]:groups[key]=(rank,r)
    for base,(_,protocol) in sorted(groups.items()):
        parts=protocol['partitions']
        fields=staged['members'][parts[0]['member']]['fields']
        family=base.split('/')[1]
        task_ids=['T0103']
        binary=False;paired=False;protein=False;flags=[]
        context={'release_context_path':base}
        if family=='APA_Isoform':
            seqcol='seq';targets=['proximal_isoform_proportion'];task_ids+=['XEUKA_04']
            definition='proximal polyadenylation isoform proportion (fraction, not expression level)'
            unit='fraction [0,1]'
        elif family=='RNA_protein_interaction':
            seqcol='sequence' if 'sequence' in fields else 'sequence_1'
            targets=['label'];binary=True
            protein='sequence_2' in fields
            definition='binding/nonbinding author labels; RBP/window and negative-generation interpretation source-specific'
            task_ids+=['XEUKA_01']
            if 'gene_disjoint' in base:task_ids+=['XEUKA_02']
            unit='binary class'
        elif family=='m6A_modification':
            seqcol='sequence';targets=['label'];binary=True;task_ids+=['XEUKA_03']
            definition='author m6A site/window binary label; chemistry and source peak mapping unresolved';unit='binary class'
        elif family=='Rabani_degradation_rate':
            seqcol='sequence';targets=[k for k in ['beta','half_life','log_half_life'] if k in fields]
            task_ids+=['XEUKA_05'];definition='separate decay coefficient, half-life and log-half-life columns; not interchangeable'
            unit='source-specific beta / half-life / log scale; exact time unit requires primary Methods'
        elif family=='Zhao_half-life':
            seqcol='seq';targets=['label'];task_ids+=['XEUKA_06'];definition='fast-UTR stability/half-life label; no time-unit inference from filename'
            unit='UNRESOLVED_SOURCE_SCALE'
        elif family=='karner_decay_rate':
            seqcol='utr3_sequence_rna';targets=[k for k in fields if k.startswith('log_decay_')]+['mean_log_decay']
            task_ids+=['XEUKA_07'];definition='cell-specific log decay estimates; each cell readout distinct'
            unit='log decay rate, base/time unit unresolved'
        elif family=='seo_viromics':
            seqcol='sequence';targets=['RNA_logFC','MRL','HP_Free'];task_ids+=['XEUKA_09']
            definition='viral reporter tile RNA abundance logFC, MRL and HP_Free; separate outputs, not TE'
            unit='RNA_logFC: log fold change; MRL: ribosome load; HP_Free: fraction'
        elif family=='west_2025':
            seqcol='sequence';targets=['label'];task_ids+=['XEUKA_08'];definition='3UTR reporter '+base.split('/')[-2]+' in '+base.split('/')[-1]
            unit='author-normalized reporter score; RNA/protein/translation endpoints not merged'
        else:continue
        if seqcol not in fields or not set(targets)<=set(fields):continue
        plan=dict(unit_id='EUKA_'+family+'_'+sha(base)[:12],package_group_id='EUKAUTR',
            task_ids=task_ids,assay_id='EUKA_SOURCE_CONTEXT:'+base,
            independently_verified_assay=False,assay_identity_status='RELEASE_CONTEXT_NOT_ORIGINAL_ASSAY_ACCESSION',
            source=base,readout_id='|'.join(targets),label_definition=definition,label_unit=unit,
            input_schema={'sequence_column':seqcol,'literal_construct':'source-specific fragment; do not assume full UTR',
                          'protein_input':protein},target_schema={k:'binary' if binary else 'continuous' for k in targets},
            modality='rna_protein' if protein else 'regulatory',problem_type='binary_classification' if binary else 'regression_or_multioutput',
            binary=binary,proxy=False,metric='AUROC+AUPRC+MCC' if binary else 'per-readout Spearman+RMSE',
            evidence_path='runs/20261028_scientific_curation/euka_stage.json',
            scientific_gaps=['original experimental QC/rights','assay and fragment identity','source label direction/scale','manual review'],
            author_partition_recipe=protocol['source_protocol'])
        def rows(parts=parts,seqcol=seqcol,targets=targets,protein=protein,binary=binary,context=context,family=family):
            for part in parts:
                member=part['member'];p=ROOT/staged['members'][member]['path']
                with p.open(encoding='utf-8-sig') as f:
                    for n,r in enumerate(csv.DictReader(f),1):
                        values={}
                        flags=[];errors=[]
                        for target in targets:
                            try:v=float(r[target])
                            except (TypeError,ValueError):v=None
                            values[target]=v
                        label=values[targets[0]] if binary else values
                        seq=r[seqcol]
                        metadata={k:r[k] for k in ['gene_id','transcript_id','canonical_id','TILE_ID','library','id','seq_id'] if r.get(k)}
                        ctx=dict(context)
                        if r.get('library'):ctx['library']=r['library']
                        # The exact row payload (excluding role/index columns)
                        # disambiguates unknown experiment conditions. Identical
                        # row representations in alternative author splits map.
                        ident={'released_sample_fields':metadata,'row_payload_sha256':sha(r)}
                        groups={}
                        if r.get('gene_id'):groups['gene']=r['gene_id']
                        if r.get('transcript_id'):groups['transcript']=r['transcript_id']
                        if r.get('accession'):groups['viral_genome_accession']=r['accession']
                        # Do not group every APA construct by reporter-library
                        # backbone: this is not a requested backbone-held-out track.
                        out=dict(sequence=seq,label=label,identity=ident,context=ctx,
                                 group_metadata=groups,errors=errors,flags=flags)
                        if protein:
                            out.update(sequence_b=r['sequence_2'],sequence_b_kind='protein',
                                sequence_model_view=seq.replace(' ',''))
                            out['flags'].append('RNA_SPACE_TOKENIZATION_MODEL_VIEW_ONLY')
                        yield out,'EUKA_DOWNSTREAM_ASSEMBLED',n,member,part['split']
        yield plan,rows


def probing_jobs(all_assets):
    partitions=list(_probing_partition_jobs(all_assets))
    plan=dict(partitions[0][0])
    plan['unit_id']='PROBING_RMDB_s40'
    plan['clustering_algorithm']='easy-linclust'
    plan['original_files']=[p[0]['unit_id'] for p in partitions]
    def rows():
        for _,read in partitions:
            yield from read()
    yield plan,rows


def _probing_vector(value):
    import warnings
    text=value.strip()
    if text[:1] in ('[','(') and text[-1:] in (']',')'):text=text[1:-1].strip()
    text=re.sub(r'\bNone\b','nan',text)
    separator=',' if ',' in text else ' '
    if not text:return np.array([],dtype=float)
    expected=len(text.split(',')) if separator==',' else len(text.split())
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        result=np.fromstring(text,sep=separator,dtype=float)
    if len(result)!=expected:raise ValueError('PARTIAL_VECTOR_PARSE_REFUSED')
    return result


def cv_only_jobs(all_assets):
    """Keep CV-only assay aliases separate unless actual identity is resolved."""
    aid='A0003'
    with zipfile.ZipFile(all_assets['P0_RNAGYM_PROCESSED']['raw_path']) as z:
        present={Path(n).stem for n in z.namelist() if n.startswith('assays/') and n.endswith('.csv')}
    protocols=json.loads((ROOT/'data/registries/upstream_split_audit.json').read_text())['protocols']
    selected={}
    for p in protocols:
        if p['package_group_id']!='RNAGYM_DMS':continue
        alias=Path(p['source_protocol']).name
        if alias not in present and (alias not in selected or p['source_protocol']<selected[alias]['source_protocol']):selected[alias]=p
    for alias,p in sorted(selected.items()):
        plan=dict(unit_id='DMS_CVONLY_'+alias,package_group_id='RNAGYM_DMS',task_ids=['T0014','T0032','T0108'],
            assay_id='UNRESOLVED_CV_ALIAS:'+alias,assay_identity_status='CV_ONLY_ALIAS_NOT_AUTOMERGED',
            independently_verified_assay=False,source='RNAGym CV-only released alias '+alias,readout_id='DMS_score',
            input_schema={'sequence':'released RNA variant; WT binding unresolved'},target_schema={'DMS_score':'continuous'},
            label_definition='released assay score; original assay identity, direction and construct require resolution',
            label_unit='author-specific DMS score, unresolved',modality='dms',problem_type='regression',
            metric='Spearman candidate only; phenotype semantics pending',binary=False,proxy=False,
            evidence_path='data/registries/upstream_split_audit.json#'+p['protocol_id'],
            scientific_gaps=['CV-only alias is not resolved to a unique original experimental assay','WT/mutation mapping',
                             'readout meaning/direction','rights','manual review'])
        def rows(parts=p['partitions']):
            with zipfile.ZipFile(all_assets[aid]['raw_path']) as z:
                for part in parts:
                    with z.open(part['member']) as f:
                        for n,r in enumerate(csv.DictReader(io.TextIOWrapper(f,encoding='utf-8-sig')),1):
                            try:label=float(r['DMS_score'])
                            except (ValueError,TypeError):label=None
                            yield dict(sequence=r['sequence'],label=label,identity={'mutation':r.get('mutant'),
                                'sequence':r['sequence']},context={},flags=['ORIGINAL_ASSAY_ALIAS_AND_WT_UNRESOLVED']),aid,n,part['member'],part['split']
        yield plan,rows


def wang_jobs(all_assets):
    """Recover plain data and numeric buffers without executing pickle."""
    from .safe_pickle import decode
    aid='WANG_ZERO_738bc3a1b453'
    definitions=[('bib/Task_ss/data/vl_40_key_seq_contact_idx.pkl',['T0027'],'structure2d'),
                 ('bib/Task_ss/data/ts_70_key_seq_contact_idx.pkl',['T0028','T0029'],'structure2d'),
                 ('bib/Task_class/data/Archivell_n3864_dataset.pkl',[],'annotation_family'),
                 ('bib/Task_class/data/Archivell_Nr.pkl',[],'annotation_family'),
                 ('bib/Task_class/data/RfamSample_s42_rf561_n5610.pkl',[],'annotation_family')]
    for member,task_ids,modality in definitions:
        with zipfile.ZipFile(all_assets[aid]['raw_path']) as z:
            data=decode(z.read(member))
            hard_ids=set(z.read('bib/Task_ss/data/TS-Hard.id').decode().split()) if modality=='structure2d' else set()
        name=Path(member).stem
        # TS-Hard is explicitly a subset, not a second copy of the whole TS.
        tasks=task_ids if name.startswith('vl_') else ['T0028'] if modality=='structure2d' else []
        plan=dict(unit_id='WANG_'+name,package_group_id='WANG_ZERO_SHOT',task_ids=tasks,
            assay_id='PDB_CONTACT_RELEASE:'+name if modality=='structure2d' else 'ANNOTATION_RELEASE:'+name,
            assay_identity_status='RELEASED_CHAIN_OR_FAMILY_IDENTITIES_NOT_INDEPENDENT_EXPERIMENTS',
            independently_verified_assay=False,source='Wang released '+member,
            readout_id='contact_array_and_index_mapping' if modality=='structure2d' else 'family_annotation',
            input_schema={'sequence':'literal released sequence','ID':'PDB-chain key' if modality=='structure2d' else 'source annotation identity'},
            target_schema={'contact':'original directed/undirected binary adjacency + residue index mapping; all orientations preserved, not assumed base-pair-only'} if modality=='structure2d' else {'family':'published string class, no synthetic positive/negative pairs'},
            label_definition='released binary RNA contact graph; derivation/threshold must be bound before claiming base pairs' if modality=='structure2d' else 'published RNA family/type annotation; precursor to a pair homology task, not pre-existing binary pair labels',
            label_unit='binary contact edges' if modality=='structure2d' else 'categorical family string',
            modality=modality,problem_type='structured_contact_prediction' if modality=='structure2d' else 'family_annotation_source',
            metric='contact F1/MCC candidate; coordinate/contact derivation pending' if modality=='structure2d' else 'NOT_BOUND: original pair construction required',
            binary=False,categorical=modality=='annotation_family',proxy=modality=='annotation_family',
            evidence_path='raw archive member '+member,scientific_gaps=['original structural/annotation source release mapping',
                'contact construction semantics or original pair task construction','rights','manual review'])
        def rows(data=data,member=member,modality=modality,hard_ids=hard_ids):
            for n,r in enumerate(data,1):
                errors=[];flags=[]
                if modality=='structure2d':
                    key,seq,matrix,idx=r
                    if not isinstance(matrix,np.ndarray) or matrix.ndim!=2 or matrix.shape!=(len(idx),len(idx)):
                        errors.append('CONTACT_INDEX_SHAPE_MISMATCH')
                    if any(type(i) is not int or not 0<=i<len(seq) for i in idx) or len(set(idx))!=len(idx):errors.append('INVALID_RESIDUE_INDEX_MAPPING')
                    if not np.isin(matrix,[0,1]).all():errors.append('NONBINARY_CONTACT')
                    if matrix.shape[0]==matrix.shape[1] and not np.array_equal(matrix,matrix.T):flags.append('ASYMMETRIC_CONTACT_REPRESENTATION_PRESERVED_NO_SYMMETRIZATION')
                    if np.diag(matrix).any():errors.append('SELF_CONTACT')
                    edges=np.argwhere(matrix>0)
                    label={'index_mapping':idx,'directed_contact_edges_local_zero_based':edges.tolist(),'n_resolved_positions':len(idx)}
                    if matrix.shape[0]!=len(seq):flags.append('PARTIAL_RESIDUE_MAPPING_NOT_FULL_SEQUENCE_STRUCTURE')
                    if (matrix.sum(axis=1)>1).any():flags.append('MULTIPLE_CONTACTS_NOT_ASSUMED_SECONDARY_PAIRING')
                    ctx={'source_chain':key,'ts_hard_subset':key in hard_ids}
                    group={'pdb_entry':key.split('_')[0]}
                    yield dict(sequence=seq,label=label,identity=key,context=ctx,group_metadata=group,
                        structured_target_valid=True,finite_labels=[],flags=flags,errors=errors),aid,n,member,None
                else:
                    family,key,seq=r
                    yield dict(sequence=seq,label=family,identity=key,context={'annotation_family':family},
                        group_metadata={'annotation_family':family},categorical_target_valid=bool(family),
                        finite_labels=[]),aid,n,member,None
        yield plan,rows
