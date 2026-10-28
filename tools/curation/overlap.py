"""Disk-backed, content-bound exact input overlap across curated units.

Observation independence is never inferred from matching sequences alone.
No cross-study numeric labels are declared conflicting without matched readout,
conditions and experimental identity.
"""
import collections
import itertools
import json
import sqlite3
from pathlib import Path

import pyarrow.parquet as pq

from .core import ROOT,RUN,VERSION,sha,write_json,write_tsv,file_sha


def audit_overlap(reports):
    db=sqlite3.connect(RUN/'curated_identity.sqlite',timeout=120)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=NORMAL')
    db.execute('PRAGMA cache_size=-131072')
    db.execute('CREATE TABLE IF NOT EXISTS inputs(unit TEXT,h BLOB,normalized BLOB,n INTEGER,label BLOB,PRIMARY KEY(unit,h)) WITHOUT ROWID')
    db.execute('CREATE TABLE IF NOT EXISTS checkpoints(unit TEXT PRIMARY KEY,fingerprint TEXT)')
    profiles={}
    for report in reports:
        unit=report['unit_id'];fingerprint=report['output_sha256']
        previous=db.execute('SELECT fingerprint FROM checkpoints WHERE unit=?',(unit,)).fetchone()
        if previous and previous[0]==fingerprint:continue
        p=ROOT/report['output_path']
        if file_sha(p)!=fingerprint:raise ValueError('CURATED_HASH_MISMATCH:'+unit)
        print(json.dumps({'overlap_index_unit':unit,'n':report['valid_n']}),flush=True)
        with db:
            db.execute('DELETE FROM inputs WHERE unit=?',(unit,))
            pf=pq.ParquetFile(p)
            wanted=[c for c in ['input_hash','label_json','sequence','sequence_b','sequence_model_view','sequence_b_kind'] if c in pf.schema_arrow.names]
            for batch in pf.iter_batches(batch_size=10000,columns=wanted):
                aggregated=collections.Counter()
                for r in batch.to_pylist():
                    a=(r.get('sequence_model_view') or r['sequence']).upper().replace('T','U')
                    b=r.get('sequence_b')
                    if b is not None:b=b.upper() if r.get('sequence_b_kind')=='protein' else b.upper().replace('T','U')
                    aggregated[(r['input_hash'],sha([a,b]),sha(r['label_json']))]+=1
                db.executemany('INSERT INTO inputs VALUES (?,?,?,?,?) ON CONFLICT(unit,h) DO UPDATE SET n=n+excluded.n',
                    [(unit,bytes.fromhex(h),bytes.fromhex(normal),n,bytes.fromhex(lh)) for (h,normal,lh),n in aggregated.items()])
            db.execute('INSERT OR REPLACE INTO checkpoints VALUES (?,?)',(unit,fingerprint))
    db.execute('CREATE INDEX IF NOT EXISTS by_input ON inputs(h)')
    db.execute('CREATE INDEX IF NOT EXISTS by_normalized ON inputs(normalized)');db.commit()
    units={r['unit_id']:r for r in reports}
    # Ignore stale units left behind by an explicitly revised curation version.
    available=set(units)
    nkeys=dict(db.execute('SELECT unit,count(*) FROM inputs GROUP BY unit'))
    shared={(a,b):n for a,b,n in db.execute('SELECT a.unit,b.unit,count(*) FROM inputs a JOIN inputs b ON a.h=b.h AND a.unit<b.unit GROUP BY a.unit,b.unit')
            if a in available and b in available}
    normalized={(a,b):n for a,b,n in db.execute('WITH u AS (SELECT DISTINCT unit,normalized FROM inputs) SELECT a.unit,b.unit,count(*) FROM u a JOIN u b ON a.normalized=b.normalized AND a.unit<b.unit GROUP BY a.unit,b.unit') if a in available and b in available}
    output=[]
    for a,b in itertools.combinations(sorted(units),2):
        n=shared.get((a,b),0)
        ra,rb=units[a],units[b]
        assay=ra['assay_id']==rb['assay_id']
        output.append({'left':a,'right':b,'comparison_scope':'CURATED_LITERAL_ORDERED_INPUT',
            'shared_exact_input':n,'shared_UT_equivalent_model_input':normalized.get((a,b),0),'left_unique_inputs':nkeys.get(a,0),'right_unique_inputs':nkeys.get(b,0),
            'overlap_pct_left':100*n/max(1,nkeys.get(a,0)), 'overlap_pct_right':100*n/max(1,nkeys.get(b,0)),
            'shared_observation':'UNKNOWN_NEEDS_ORIGINAL_CONDITION_AND_OBSERVATION_ID' if n else 0,
            'shared_original_assay':assay if ra.get('independently_verified_assay') and rb.get('independently_verified_assay') else 'UNKNOWN',
            'conflicting_labels':'NOT_COMPARED_ACROSS_UNBOUND_READOUTS' if n else 0,
            'near_duplicate_homology_overlap':'NOT_RUN_CROSS_DATASET',
            'recommendation':'KEEP_READOUTS_SEPARATE; GLOBAL_TRAIN_TEST_GROUPING_REQUIRED_BEFORE_POOLING' if n else 'NO_LITERAL_EXACT_INPUT_OVERLAP_OBSERVED'})
    # Cross-benchmark mirrors are mapped to the canonical curated dataset rather
    # than materializing and counting an identical second dataset.
    prior=ROOT/'runs/20261022_212625/reports/cross_benchmark_representation_duplicates.json'
    mirror=json.loads(prior.read_text())
    for r in mirror['comparisons']:
        unit='DMS_'+r['source_alias'];report=units.get(unit)
        if not report:continue
        output.append({'left':unit,'right':'WANG:'+r['source_alias'],'comparison_scope':'EXACT_ARCHIVE_MEMBER_BYTES_PRIOR_HASH_BOUND',
            'shared_exact_input':nkeys[unit], 'shared_observation':report['unique_n'],
            'shared_original_assay':'SAME_PUBLISHED_REPRESENTATION_NOT_ADDITIONAL_EXPERIMENT',
            'conflicting_labels':0,'near_duplicate_homology_overlap':'EXACT_MIRROR',
            'overlap_pct_left':100,'overlap_pct_right':100,
            'left_member_sha256':r['rnagym_member_sha256'],'right_member_sha256':r['wang_member_sha256'],
            'recommendation':'ONE_CANONICAL_DATASET; DO_NOT_DUPLICATE_WEIGHT'})
    write_tsv(ROOT/'data/audit/cross_dataset_overlap.tsv',output)
    summary={'curated_units_compared':len(units),'all_pairs_computed':len(units)*(len(units)-1)//2,
             'curated_unit_pairs_with_exact_overlap':sum(n>0 for n in shared.values()),
             'curated_unit_pairs_with_UT_equivalent_overlap':sum(n>0 for n in normalized.values()),
             'exact_archive_mirror_pairs':sum(r['comparison_scope'].startswith('EXACT_ARCHIVE') for r in output),
             'near_homology_cross_dataset_audit_complete':False,
             'literal_input_view':'verbatim sequence or ordered sequence pair; no U/T conversion',
             'limitations':['Cross-study same-observation and conflicting-label counts require experiment/condition matching.',
                            'Random and OOD splits are frozen per unit, not a globally leak-free pooled training benchmark.',
                            'NABench file bytes not acquired; metadata identity is not sample-level content verification.']}
    write_json(RUN/'overlap_summary.json',summary)
    db.close()
    return output,summary
