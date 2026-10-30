#!/usr/bin/env python3
"""Full-row, column-pruned input-compatibility audit, not model admission.

Counts complete sequences under the explicitly declared RNA-FM-HF input view.
Never confuses a passing 12-record smoke with full-dataset model coverage.
"""
from pathlib import Path
import collections
import json
import gzip
import csv
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
from rna_gym import DatasetHub
from tools.build_arena_v1 import ROOT, QC, table, load, dump, tsv

OUT=ROOT/'runs/20261030_structure_engineering_smoke_v1'


def compatible(array):
    upper=pc.utf8_upper(array)
    return pc.fill_null(pc.and_(pc.match_substring_regex(upper,'^[ACGTU]+$'),
        pc.less_equal(pc.utf8_length(upper),1022)),False)


def run():
    hub=DatasetHub(root=ROOT)
    stats={r['unit_id']:r for r in table(ROOT/'data/audit/dataset_statistics.tsv')}
    first=table(OUT/'gpu_smoke/dataset_smoke_results.tsv')
    repaired=OUT/'gpu_smoke_parser_repair/dataset_smoke_results.tsv'
    latest={r['dataset_id']:r for r in first}
    if repaired.exists(): latest.update({r['dataset_id']:r for r in table(repaired)})
    rows=[]
    for view in hub.dataset_views():
        did,unit=view['dataset_id'],view['unit_id'];total=0;ok=0
        if did.startswith('UTR102:'):
            path=hub.utr(did)._fold_path(0)
            try:
                with gzip.open(path,'rt',encoding='utf-8-sig',newline='') as handle:
                    reader=csv.DictReader(handle)
                    for row in reader:
                        seq=row.get('sequence','').upper().replace('T','U'); total+=1
                        if seq and len(seq)<=1022 and set(seq)<=set('ACGU'): ok+=1
                full_qc_n='NOT_RECOMPUTED_LEGACY_PROFILE_ONLY'
            except Exception as exc:
                total=int(view['n_records']); ok=None; full_qc_n='LEGACY_SCAN_PENDING:'+str(exc)[:120]
        else:
            path=ROOT/'data/processed'/unit/QC/'curated_data.parquet'
            pf=pq.ParquetFile(path);cols=[c for c in ['sequence','sequence_b','sequence_b_kind'] if c in pf.schema_arrow.names]
            for batch in pf.iter_batches(batch_size=8192,columns=cols):
                b=pa.Table.from_batches([batch]); mask=compatible(b['sequence'])
                if 'sequence_b' in cols:
                    present=pc.and_(pc.is_valid(b['sequence_b']),pc.greater(pc.utf8_length(pc.fill_null(b['sequence_b'],'')),0))
                    pair_ok=compatible(b['sequence_b'])
                    if 'sequence_b_kind' in cols:
                        pair_ok=pc.and_(pair_ok,pc.fill_null(pc.not_equal(b['sequence_b_kind'],'protein'),True))
                    mask=pc.and_(mask,pc.or_(pc.invert(pc.fill_null(present,False)),pair_ok))
                total+=batch.num_rows;ok+=pc.sum(pc.cast(mask,pa.int64())).as_py()
            full_qc_n=stats[unit]['valid_n']
        if total!=int(view['n_records']): raise ValueError('FULL_COUNT_MISMATCH:'+did)
        result=latest[did];st=stats.get(unit,{})
        rows.append(dict(dataset_id=did,source_collection=view['source_collection'],
            reported_original_n=st.get('author_reported_n','UNKNOWN'),actual_source_n=st.get('actual_n','UNKNOWN_LEGACY_SOURCE'),
            qc_valid_n=full_qc_n,local_view_n=total,unique_observations_n=st.get('unique_n','UNKNOWN'),
            duplicate_observations_n=st.get('duplicate_n','UNKNOWN'),
            full_sequence_model_compatible_n=ok,full_sequence_model_coverage=ok/total if total else None,
            technical_smoke_status=result['status'],smoke_n=result.get('n_smoke_records',''),
            epochs_completed=result['epochs_completed'],scientific_admission='HOLD_OR_SECONDARY_PROXY_NOT_CHANGED',
            model_id='RNA-FM-HF',length_policy='complete sequence <=1022, no truncation',
            source_identity_review='PENDING_WHERE_PROVENANCE_INCOMPLETE',
            input_compatibility_does_not_imply_output_task_compatibility=True))
        print(len(rows),did,'N',total,'compatible',ok,flush=True)
    tsv(ROOT/'data/audit/dataset_api_smoke_sizes_admission_v1_1.tsv',rows)
    dump(OUT/'native_coverage_summary.json',dict(views=len(rows),
        qc_scope_records=sum(r['local_view_n'] for r in rows if r['source_collection']=='RNAGYM_QC'),
        legacy_utr_scope_records=sum(r['local_view_n'] for r in rows if r['source_collection']=='UTR_LEGACY_102'),
        fully_native_input_compatible_views=sum(r['full_sequence_model_coverage']==1 for r in rows),
        partially_compatible_views=sum(0<r['full_sequence_model_coverage']<1 for r in rows),
        zero_native_input_compatible_views=sum(r['full_sequence_model_coverage']==0 for r in rows),
        independent_observation_union='NOT_COMPUTED; these are view-level counts',
        scientific_admitted=0))


if __name__=='__main__': run()
