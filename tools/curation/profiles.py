"""Descriptive quality/diversity profiles, never admission cutoffs."""
import collections
import json
import math
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from .core import ROOT,RUN,distribution,write_json,write_tsv


def profiles(reports):
    output=[]
    for r in reports:
        cache=RUN/'profiles'/(r['unit_id']+'.json')
        if cache.exists() and json.loads(cache.read_text())['curated_sha256']==r['output_sha256']:
            output.append(json.loads(cache.read_text()));continue
        a=[];b=[];groups=collections.defaultdict(set);kmers=collections.Counter();sampled=0
        pf=pq.ParquetFile(ROOT/r['output_path'])
        for batch in pf.iter_batches(batch_size=10000,columns=['sequence','sequence_b','input_hash','group_metadata_json']):
            a.extend(pc.utf8_length(batch.column(0)).to_pylist())
            b.extend(v for v in pc.utf8_length(batch.column(1)).to_pylist() if v is not None)
            for row in batch.to_pylist():
                for k,v in json.loads(row['group_metadata_json']).items():groups[k].add(str(v))
                if sampled<10000 and int(row['input_hash'][:4],16)<1024:
                    seq=row['sequence'].upper().replace('T','U')
                    kmers.update(seq[i:i+3] for i in range(max(0,len(seq)-2)) if set(seq[i:i+3])<=set('ACGU'))
                    sampled+=1
        total=sum(kmers.values());entropy=-sum((v/total)*math.log2(v/total) for v in kmers.values()) if total else None
        p={'unit_id':r['unit_id'],'curated_sha256':r['output_sha256'],'n_valid':r['valid_n'],
           'invalid_or_quarantined_fraction':(r['excluded_n']+r['quarantined_n'])/max(1,r['actual_n']),
           'observation_alias_fraction':r['duplicate_n']/max(1,r['actual_n']),
           'exact_input_repeat_fraction':r['exact_input_repeated_rows']/max(1,r['actual_n']),
           'known_observation_conflict_groups':r['observation_label_conflict_groups'],
           'same_input_different_label_groups':r['input_label_conflict_groups'],
           'retained_sequence_length':distribution(a),'retained_second_input_length':distribution(b),
           'retained_total_RNA_positions':sum(a),'GC_distribution_scope':'see qc_report raw input GC distribution',
           'retained_group_coverage':{k:len(v) for k,v in groups.items()},
           'kmer_profile':{'k':3,'sampled_sequences':sampled,'distinct_kmers':len(kmers),'shannon_bits':entropy,
               'sampling':'stable input-hash prefix <1024/65536, capped at first 10000 qualifying records; descriptive sample, not exhaustive'},
           'valid_nucleotide_labels':r['valid_nucleotide_labels'],
           'nucleotide_label_observed_fraction':r['valid_nucleotide_labels']/max(1,sum(a)) if r['modality']=='probing' else None,
           'class_counts':r.get('class_counts'),
           'regression_or_label_statistics':r.get('target_statistics'),
           'replicate_consistency':'UNKNOWN_WHEN_NO_BOUND_REPLICATE_ID',
           'source_evidence_completeness':'see original_qc_evidence.tsv and qc_gap_analysis.tsv; not reduced to an admission score',
           'EAZY_groups':r.get('split',{}).get('EAZY',{}).get('n_groups'),
           'OOD_groups':r.get('split',{}).get('OOD_split',{}).get('n_groups')}
        write_json(cache,p);output.append(p)
    write_tsv(ROOT/'data/audit/dataset_quality_profiles.tsv',output)
    return output
