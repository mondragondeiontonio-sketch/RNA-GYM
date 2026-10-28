"""Shared record QC, identity mapping, statistics and immutable derived data."""
import collections
import csv
import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .splits import build_splits

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'rnagym-qc-2026-10-28-v1'
RUN = ROOT/'runs/20261028_scientific_curation'
PRODUCER_SCRIPTS = None

def capture_producer():
    global PRODUCER_SCRIPTS
    PRODUCER_SCRIPTS={}
    directory=RUN/'producer_code'
    directory.mkdir(parents=True,exist_ok=True)
    for p in list((ROOT/'tools/curation').glob('*.py'))+[ROOT/'tools/curate_scientific.py']:
        data=p.read_bytes()
        digest=hashlib.sha256(data).hexdigest()
        (directory/(digest+'.py')).write_bytes(data)
        PRODUCER_SCRIPTS[str(p.relative_to(ROOT))]=digest


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=True)


def sha(value):
    return hashlib.sha256((value if isinstance(value, bytes) else canonical(value).encode())).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(data)
    temp.replace(path)


def write_tsv(path, rows, fields=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if fields is None:
        fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w') as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter='\t', lineterminator='\n', extrasaction='ignore')
        w.writeheader()
        for row in rows:
            w.writerow({k:canonical(v) if isinstance(v, (dict,list,tuple)) else v for k,v in row.items()})


def assets():
    # State is read-only; do not create migrations or review records here.
    con = sqlite3.connect('file:'+str(ROOT/'run-state.sqlite')+'?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    catalog = json.loads((ROOT/'data/registries/dataset_catalog.json').read_text())
    meta = {a['asset_id']: a for a in catalog['assets']}
    result = {}
    for row in con.execute('select * from artifacts'):
        r = dict(row)
        r.update(package_group_id=meta[r['asset_id']]['package_group_id'],
                 filename=meta[r['asset_id']]['filename'])
        result[r['asset_id']] = r
    con.close()
    return result


def inventory(all_assets):
    """Hash only raw resources changed after the most recent full verification.

    Cached proof is accepted only for the same hash, byte size, content-addressed
    parent and file mtime strictly before the verification command started.
    This assumes the existing append-only content-addressed cache contract;
    explicitly backdating a file would violate that contract.
    """
    from datetime import datetime
    previous = ROOT/'runs/20261028_split_admission_main'
    proof = json.loads((previous/'current_raw_hashes.json').read_text())
    command = json.loads((previous/'hash_current_raw.command.json').read_text())
    cutoff = datetime.fromisoformat(command['started_at']).timestamp()
    by_sha = {r['sha256']: r for r in proof['assets'] if r.get('hash_matches')}
    rows = []
    for aid, r in sorted(all_assets.items()):
        p = Path(r['raw_path'])
        if not p.is_file():
            rows.append(dict(asset_id=aid, package_group_id=r['package_group_id'],
                             path=str(p), status='MISSING_LOCAL_FILE'))
            continue
        st = p.stat()
        cached = by_sha.get(r['sha256'])
        reuse = bool(cached and st.st_size == cached['bytes'] == r['bytes']
                     and st.st_mtime < cutoff and p.parent.name == r['sha256'])
        actual = r['sha256'] if reuse else file_sha(p)
        if actual != r['sha256']:
            raise ValueError('RAW_HASH_MISMATCH:'+aid)
        rows.append(dict(asset_id=aid, package_group_id=r['package_group_id'],
            path=str(p.relative_to(ROOT)), bytes=st.st_size, sha256=actual,
            mtime_ns=st.st_mtime_ns, status='PRESENT_HASH_VERIFIED',
            hash_mode='REUSED_CONTENT_BOUND_PROOF' if reuse else 'FULL_BYTES_REHASHED',
            hash_evidence=str((previous/'current_raw_hashes.json').relative_to(ROOT)) if reuse else 'current_run',
            file_role='transport_part_or_checksum' if '.part-' in p.name or 'SHA256' in p.name or p.suffix=='.sha256' else 'resource'))
    write_tsv(ROOT/'data/audit/local_inventory.tsv', rows)
    return rows


def numeric_values(label):
    values = []
    if isinstance(label, dict):
        for v in label.values():
            values.extend(numeric_values(v))
    elif isinstance(label, (list,tuple)):
        for v in label:
            values.extend(numeric_values(v))
    else:
        try:
            v = float(label)
            if math.isfinite(v):
                values.append(v)
        except (TypeError,ValueError,OverflowError):
            pass
    return values


def distribution(values):
    v = np.asarray(values, dtype=float)
    return {'n': int(v.size), 'min':float(v.min()) if v.size else None,
            'p25':float(np.quantile(v,.25)) if v.size else None,
            'median':float(np.median(v)) if v.size else None,
            'p75':float(np.quantile(v,.75)) if v.size else None,
            'p95':float(np.quantile(v,.95)) if v.size else None,
            'max':float(v.max()) if v.size else None,
            'mean':float(v.mean()) if v.size else None,
            'std':float(v.std()) if v.size else None}


SCHEMA = pa.schema([
    ('record_id',pa.string()), ('observation_id',pa.string()), ('sequence',pa.string()),
    ('sequence_b',pa.string()), ('sequence_b_kind',pa.string()), ('sequence_model_view',pa.string()), ('input_hash',pa.string()), ('label_json',pa.string()),
    ('finite_label_mask_json',pa.string()), ('source_asset_id',pa.string()),
    ('source_member',pa.string()), ('source_row',pa.int64()), ('original_split',pa.string()),
    ('context_json',pa.string()), ('group_metadata_json',pa.string()),
    ('qc_disposition',pa.string()), ('qc_flags_json',pa.string()),
    ('valid_nucleotide_labels',pa.int64())])


class Curator:
    def __init__(self, spec, all_assets):
        self.spec = spec
        self.all_assets = all_assets
        self.output = ROOT/'data/processed'/spec['unit_id']/VERSION
        self.output.mkdir(parents=True, exist_ok=True)
        if (self.output/'freeze.json').exists():
            raise ValueError('FROZEN_DATA_VERSION_CANNOT_BE_REFRESHED:'+spec['unit_id'])
        self.records = []
        self.actual_n = 0
        self.logs = []
        self.lengths = []
        self.gc = []
        self.sequence_chars = collections.Counter()
        self.raw_row_mapping = []
        self.exact_raw = {}
        self.observation_labels = collections.defaultdict(set)
        self.label_sets = collections.defaultdict(set)
        self.input_counts = collections.Counter()
        self.input_label_counts = collections.Counter()
        self.nucleotide_labels = 0
        self.failure_counts = collections.Counter()
        self.duplicate_n = 0
        self.source_members = set()
        self.target_distributions = collections.defaultdict(list)

    def add(self, row, asset_id, source_row, member='', original_split=None):
        """Adapter supplies explicit schema and context, not name-based inference."""
        self.actual_n += 1
        self.source_members.add((asset_id, member))
        seq = row.get('sequence')
        second = row.get('sequence_b')
        label = row.get('label')
        context = row.get('context', {})
        identity = row.get('identity')
        groups = row.get('group_metadata', {})
        flags = list(row.get('flags', []))
        reasons = list(row.get('errors', []))
        disposition = row.get('error_disposition', 'QUARANTINE')
        for endpoint, s in [('sequence',seq), ('sequence_b',second)]:
            if endpoint=='sequence_b' and self.spec.get('modality') not in ('paired','rna_protein'):
                continue
            if not isinstance(s,str) or not s:
                reasons.append('EMPTY_OR_NONSTRING_'+endpoint.upper())
                continue
            self.sequence_chars.update(s)
            allowed = set('ACGTUNacgtun')
            checked = row.get('sequence_model_view', s) if endpoint=='sequence' else s
            if endpoint=='sequence_b' and row.get('sequence_b_kind')=='protein':
                allowed=set('ACDEFGHIKLMNPQRSTVWYXBZOUacdefghiklmnpqrstvwyxbzou')
            if set(checked)-allowed:
                reasons.append('UNSUPPORTED_SEQUENCE_CHARACTERS_'+endpoint.upper())
            if 'N' in s.upper() and not (endpoint=='sequence_b' and row.get('sequence_b_kind')=='protein'):
                flags.append('AMBIGUOUS_BASES_'+endpoint.upper())
            if s != s.upper():
                flags.append('LOWERCASE_SEQUENCE_PRESERVED')
        if isinstance(seq,str) and seq:
            self.lengths.append(len(seq))
            self.gc.append((seq.upper().count('G')+seq.upper().count('C'))/len(seq))
        values = row.get('finite_labels', numeric_values(label))
        if not values and not row.get('structured_target_valid') and not row.get('categorical_target_valid'):
            reasons.append('NO_FINITE_TARGET')
            if label is None:
                disposition = 'EXCLUDE'
        if self.spec.get('binary') and any(v not in (0,1) for v in values):
            reasons.append('NONBINARY_TARGET')
        input_hash = sha([seq,second])
        # Identity includes *known* readout and context, never label value.
        # Missing construct/locus identity is not interpreted as identical assay.
        observation = sha([self.spec['assay_id'], self.spec['readout_id'],
                           input_hash, context, identity if identity is not None else [asset_id,member,source_row]])
        record_id = sha([asset_id,self.all_assets[asset_id]['sha256'],member,source_row])
        lh = sha(label)
        self.input_counts[input_hash] += 1
        self.input_label_counts[(input_hash,lh)] += 1
        self.label_sets[input_hash].add(lh)
        self.observation_labels[observation].add(lh)
        self.raw_row_mapping.append({'record_id':record_id, 'observation_id':observation,
            'asset_id':asset_id, 'member':member, 'source_row':source_row})
        duplicate_key = (observation,lh)
        if not reasons and duplicate_key in self.exact_raw:
            self.duplicate_n += 1
            self.logs.append({'record_id':record_id,'observation_id':observation,
                'disposition':'DEDUP_ALIAS', 'reason':'SAME_KNOWN_OBSERVATION_AND_LABEL',
                'representative_record_id':self.exact_raw[duplicate_key]})
            return
        self.exact_raw[duplicate_key] = record_id
        r = {'record_id':record_id,'observation_id':observation,'sequence':seq,
             'sequence_b':second,'sequence_b_kind':row.get('sequence_b_kind','rna'),
             'sequence_model_view':row.get('sequence_model_view',seq),'input_hash':input_hash,'label':label,
             'finite_labels':values, 'source_asset_id':asset_id,'source_member':member,
             'source_row':source_row,'original_split':original_split,
             'context':context,'group_metadata':groups,'qc_flags':flags,
             'qc_disposition':disposition if reasons else 'FLAG' if flags else 'KEEP',
             'valid_nucleotide_labels':row.get('valid_nucleotide_labels',0),
             'finite_label_mask':row.get('finite_label_mask')}
        if reasons:
            for reason in reasons:
                self.failure_counts[reason]+=1
            self.logs.append({'record_id':record_id,'observation_id':observation,
                              'disposition':disposition,'reason':';'.join(reasons)})
        self.records.append(r)

    def finish(self, mmseqs, do_splits=True):
        conflicting = {key for key, vals in self.observation_labels.items() if len(vals)>1}
        for r in self.records:
            if len(self.label_sets[r['input_hash']])>1 and r['qc_disposition'] in ('KEEP','FLAG'):
                r['qc_flags'].append('SAME_INPUT_DIFFERENT_LABEL_CONTEXT_NOT_COLLAPSED')
                r['qc_disposition']='FLAG'
            if r['observation_id'] in conflicting and r['qc_disposition'] in ('KEEP','FLAG'):
                r['qc_disposition'] = 'QUARANTINE'
                r['qc_flags'].append('KNOWN_OBSERVATION_CONFLICTING_LABELS')
                self.logs.append({'record_id':r['record_id'],'observation_id':r['observation_id'],
                    'disposition':'QUARANTINE','reason':'KNOWN_OBSERVATION_CONFLICTING_LABELS'})
        counts = collections.Counter(r['qc_disposition'] for r in self.records)
        good = [r for r in self.records if r['qc_disposition'] in ('KEEP','FLAG')]
        for r in good:
            label = r['label']
            if self.spec.get('modality') in ('structure3d','structure2d','annotation_family'):
                continue
            if self.spec.get('modality')=='probing':
                self.target_distributions['per_sequence_mean_reactivity'].extend(r['finite_labels'])
                continue
            if isinstance(label,dict):
                for k,v in label.items():
                    self.target_distributions[k].extend(numeric_values(v))
            else:
                self.target_distributions['target'].extend(r['finite_labels'])
        self.nucleotide_labels = sum(r['valid_nucleotide_labels'] for r in good)
        output_rows = []
        for r in good:
            out = {k:v for k,v in r.items() if k in SCHEMA.names}
            out.update(label_json=canonical(r['label']), context_json=canonical(r['context']),
                group_metadata_json=canonical(r['group_metadata']),qc_flags_json=canonical(r['qc_flags']),
                finite_label_mask_json=canonical(r['finite_label_mask'] if r.get('finite_label_mask') is not None else _finite_mask(r['label'])))
            output_rows.append(out)
        curated = self.output/'curated_data.parquet'
        pq.write_table(pa.Table.from_pylist(output_rows, schema=SCHEMA),curated,compression='zstd')
        # Quarantined/excluded original row identities are retained in logs and
        # source pointers. No raw data are deleted; only eligible views filter.
        write_tsv(self.output/'exclusion_log.tsv',self.logs,
                  ['record_id','observation_id','disposition','reason','representative_record_id'])
        pq.write_table(pa.Table.from_pylist(self.raw_row_mapping),self.output/'observation_mapping.parquet',compression='zstd')
        split = build_splits(good,self.output/'splits',mmseqs,self.spec.get('binary',False),linear=self.spec.get('clustering_algorithm')=='easy-linclust') if do_splits and good else {}
        report = dict(self.spec, version=VERSION, actual_n=self.actual_n,
            valid_n=len(good), unique_n=len({r['observation_id'] for r in good}),
            duplicate_n=self.duplicate_n, exact_input_repeated_rows=self.actual_n-len(self.input_counts),
            exact_input_duplicate_groups=sum(v>1 for v in self.input_counts.values()),
            input_label_conflict_groups=sum(len(v)>1 for v in self.label_sets.values()),
            observation_label_conflict_groups=len(conflicting),
            status_counts=dict(counts), dedup_alias_n=self.duplicate_n,
            excluded_n=counts['EXCLUDE'],quarantined_n=counts['QUARANTINE'],
            length=distribution(self.lengths),gc=distribution(self.gc),
            alphabet_counts=dict(self.sequence_chars),target_statistics={k:distribution(v) for k,v in self.target_distributions.items()},
            valid_nucleotide_labels=self.nucleotide_labels,
            class_counts=dict(collections.Counter(str(r['label']) for r in good)) if self.spec.get('binary') or self.spec.get('categorical') else None,
            qc_rules={'missing_sequence':'QUARANTINE','missing_target':'EXCLUDE',
                'unsupported_characters':'QUARANTINE','known_observation_conflict':'QUARANTINE',
                'identical_sequence_different_context':'KEEP_OR_FLAG; not deduplicated',
                'extreme_finite_label':'KEEP','negative_reactivity':'KEEP',
                'N':'FLAG; not imputed','label_normalization':'NONE'},
            failure_counts=dict(self.failure_counts),
            record_qc_status='PASS' if good else 'FAIL_NO_ELIGIBLE_OBSERVATIONS',
            split=split.get('protocols',{}),
            transitions=['DISCOVERED','SCHEMA_VERIFIED','QC_DONE','DEDUP_DONE']+
                        (['SPLIT_DONE'] if split else []),
            output_sha256=file_sha(curated),
            output_path=str(curated.relative_to(ROOT)),formal_admitted=False,human_signed=False)
        write_json(self.output/'qc_report.json',report)
        prov = {'version':VERSION,'specification':self.spec,
            'inputs':[{'asset_id':aid,'path':str(Path(self.all_assets[aid]['raw_path']).relative_to(ROOT)),
                       'sha256':self.all_assets[aid]['sha256'],'member':member} for aid,member in sorted(self.source_members)],
            'pipeline':['Original Raw (availability source-specific)','Author Processed/QC release',
                        'RNA-Gym QC','Observation deduplication mapping','Independent frozen splits'],
            'author_processed_not_raw':True,'raw_modified':False,
            'script_hashes':PRODUCER_SCRIPTS or {str(p.relative_to(ROOT)):file_sha(p) for p in sorted((ROOT/'tools/curation').glob('*.py'))},
            'producer_binding':'CAPTURED_AT_RUN_START' if PRODUCER_SCRIPTS else 'WORKING_TREE_AT_COMPLETION_ONLY',
            'output_files':{str(p.relative_to(self.output)):file_sha(p) for p in self.output.rglob('*')
                            if p.is_file() and p.name not in ('provenance.json',) and 'clustering' not in p.parts},
            'counts':{k:report[k] for k in ['actual_n','valid_n','unique_n','duplicate_n','excluded_n','quarantined_n']}}
        write_json(self.output/'provenance.json',prov)
        write_json(self.output/'complete.json', {'spec_sha256':sha(self.spec),'curated_sha256':file_sha(curated),
             'script_sha256':sha(prov['script_hashes'])})
        return report


def _finite_mask(value):
    if isinstance(value,dict):
        return {k:_finite_mask(v) for k,v in value.items()}
    if isinstance(value,list):
        return [_finite_mask(v) for v in value]
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError,ValueError,OverflowError):
        return False
