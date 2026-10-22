#!/usr/bin/env python3
"""Deterministic, allowlisted public audit preview; never an admission authority.

Optional audit adapters (owned by the audit pipeline):
* data/audit/task_status.tsv: task_id, package_group_id, assay_id, state,
  hold_reason, next_action, reported_n, reported_n_verification, actual_n,
  actual_n_scope. stage/status/admission_status are also accepted. Original
  registry reported N is authoritative; PoC file counts never become task N.
* data/audit/asset_evidence.json: a list, {"assets": [...]}, or an asset-ID
  keyed object. Fields: asset_id, package_group_id, task_id/task_ids,
  file_sha256/raw_sha256/sha256/actual_sha256, file_size_bytes/size_bytes,
  stage/state, sha256_verified/raw_hash_verified (JSON booleans), source_url,
  download_url, resolved_url, assay_doi, experimental_accession, rights_status,
  rights_proof_url/license_evidence_url, release_or_commit, actual_n,
  actual_n_scope, dataset_alias, original_split, exact_qc_state. File-scoped
  counts and identity assertions never become task counts or task identity.
* data/audit/rnagym_archive_inventory.json: optional numeric file-level
  classification only; no member contents, sequences, or assay admission.
* data/audit/poc_summary.json: file/byte and exact paired-input aggregates
  only. Its declared file/byte totals must match the asset evidence snapshot.

Package membership alone is NOT a file -> task/assay identity mapping. A
reported SHA is not promoted to verified without an explicit boolean, bytes
and a hashed stage. artifact_sha256 is deliberately NOT a raw-file checksum.
Unknown fields (including local paths, HTTP headers and reviewers) stay local.
The v0.1 preview rejects admission escalation: a future reviewed release must
explicitly replace this lock rather than silently change the frozen preview.
"""
import argparse
from collections import Counter
import csv
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, parse_qsl

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = 'data/registries/task_baselines_and_admission_198.csv'
FAMILIES = 'data/registries/source_family_crosswalk_123.csv'
PACKAGES = 'data/registries/download_packages_47.csv'
ASSETS = 'data/assets/download_assets.csv'
AUDIT_TASKS = 'data/audit/task_status.tsv'
AUDIT_ASSETS = 'data/audit/asset_evidence.json'
AUDIT_RNAGYM_INVENTORY = 'data/audit/rnagym_archive_inventory.json'
AUDIT_POC = 'data/audit/poc_summary.json'
OUTPUTS = ('tasks.json', 'provenance.json', 'summary.json')
STAGES = ('QUEUED', 'FETCHING', 'DOWNLOADED', 'HASHED', 'PARSED', 'QC_PASS',
          'DEDUP_PASS', 'REVIEW_READY', 'ADMITTED')
HASHED_STAGES = set(STAGES[3:])
# These describe bytes/exact-only QC, NOT full modality QC or admission.
FILE_STAGE_ALIASES = {'QC_PASS_EXACT_ONLY_NOT_ADMITTED': 'HASHED',
                      'HASHED_UNPINNED_QUARANTINED': 'HASHED'}
UNKNOWN = {'', 'UNKNOWN', 'NOT_VERIFIED', 'NOT_DOWNLOADED', 'NOT_PINNED',
           'N/A', 'NONE', 'NULL', '未核实', '待核实'}


def text(value):
    return '' if value is None else str(value).strip()


def known(value):
    value = text(value)
    return None if value.upper() in UNKNOWN else value


def public_url(value):
    """Allow public links, not credentials, signed URLs, or local resources."""
    value = known(value)
    if not value or any(c.isspace() for c in value):
        return None
    try:
        parts = urlsplit(value)
        host = parts.hostname or ''
        if parts.scheme != 'https' or not host or parts.username or parts.password:
            return None
        if host == 'localhost' or host.endswith(('.local', '.internal')):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if '.' not in host:
                return None
        forbidden = ('token', 'secret', 'password', 'signature', 'credential', 'api_key')
        if any(any(word in key.lower() for word in forbidden)
               for key, _ in parse_qsl(parts.query)):
            return None
        return value
    except ValueError:
        return None


def checksum(value):
    value = known(value)
    if value is None:
        return None
    if not re.fullmatch(r'[0-9a-fA-F]{64}', value):
        raise ValueError('raw checksum must be a 64-character SHA256, not a Git blob SHA')
    return value.lower()


def read_csv(root, relative, optional=False, delimiter=','):
    path = root / relative
    if optional and not path.exists():
        return []
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def indexed(rows, key):
    result = {}
    for row in rows:
        value = text(row.get(key))
        if not value or value in result:
            raise ValueError(f'missing or duplicate {key}: {value!r}')
        result[value] = row
    return result


def no_admission(value):
    if text(value).upper().startswith('ADMITTED'):
        raise ValueError('v0.1 preview admission lock: reviewed release required before ADMITTED')


def dataset_size(row):
    """Retain original wording. Only unambiguous sample units get numeric N."""
    raw = known(row.get('N(原登记)'))
    unit = known(row.get('N单位'))
    numeric = raw is not None and bool(re.fullmatch(r'\d+(?:,\d{3})*', raw))
    # These are counts of tasks/cohorts/methods, not observations. The original
    # ambiguous 'task records' unit is preserved but never called sample N.
    unit_head = (unit or '').split(';', 1)[0].lower()
    non_sample = any(word in unit_head for word in
                     ('task records', 'downstream tasks', 'assays', 'datasets',
                      'suites', 'algorithms', 'targets / groups'))
    value = int(raw.replace(',', '')) if numeric and unit and not non_sample else None
    return {'value': value, 'reported': raw, 'unit': unit,
            'status': 'reported/unverified' if raw else 'unknown',
            'sample_n_status': 'reported/unverified' if value is not None else 'unknown',
            'source': {'file': REGISTRY, 'task_id': row['task_id'],
                       'column': 'N(原登记)', 'unit_column': 'N单位'}}


def load_evidence(root):
    path = root / AUDIT_ASSETS
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if isinstance(data, dict):
        if 'assets' in data:
            data = data['assets']
        elif 'asset_id' in data:
            data = [data]
        elif all(isinstance(v, dict) for v in data.values()):
            data = [dict(v, asset_id=v.get('asset_id', k)) for k, v in data.items()]
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise ValueError('asset_evidence.json must contain an assets list or asset-ID map')
    return data


def public_asset(row, candidates, packages, tasks):
    aid = known(row.get('asset_id'))
    if not aid:
        raise ValueError('asset evidence requires asset_id')
    candidate = candidates.get(aid, {})
    package = known(row.get('package_group_id')) or candidate.get('package_group_id')
    if package not in packages:
        raise ValueError(f'unknown asset package: {package!r}')
    task_ids = row.get('task_ids', [])
    if isinstance(task_ids, str):
        task_ids = [s for s in re.split(r'[,;\s]+', task_ids) if s]
    if not isinstance(task_ids, list):
        raise ValueError('task_ids must be a list or delimited task IDs')
    task_ids = sorted(set(task_ids + ([row['task_id']] if row.get('task_id') else [])))
    for task_id in task_ids:
        if task_id not in tasks or tasks[task_id]['下载包ID'] != package:
            raise ValueError(f'invalid file -> task mapping: {aid} -> {task_id}')
    evidence_state = known(row.get('stage')) or known(row.get('state')) or known(row.get('download_state')) or 'NOT_DOWNLOADED'
    stage = FILE_STAGE_ALIASES.get(evidence_state, evidence_state)
    no_admission(evidence_state)
    no_admission(row.get('admission_status'))
    if row.get('admitted') is True:
        raise ValueError('v0.1 preview admission lock: file admitted=true is not allowed')
    hashes = {checksum(row[key]) for key in ('file_sha256', 'raw_sha256', 'sha256', 'actual_sha256')
              if known(row.get(key))}
    if len(hashes) > 1:
        raise ValueError('conflicting actual raw SHA256 fields')
    sha = next(iter(hashes), None)
    size = row.get('file_size_bytes', row.get('size_bytes'))
    if size is not None:
        if isinstance(size, bool) or not re.fullmatch(r'\d+', str(size)):
            raise ValueError('file_size_bytes must be a nonnegative integer')
        size = int(size)
    verified = row.get('sha256_verified') is True
    if verified and row.get('raw_hash_verified') is False:
        raise ValueError('contradictory sha256_verified / raw_hash_verified')
    if verified and not (sha and size and stage in HASHED_STAGES):
        raise ValueError('sha256_verified requires actual SHA256, positive bytes and HASHED+ stage')
    file_n = row.get('actual_n')
    file_n_scope = known(row.get('actual_n_scope'))
    if file_n is not None:
        if isinstance(file_n, bool) or not isinstance(file_n, int) or file_n < 0 or not file_n_scope:
            raise ValueError('file actual_n requires a nonnegative integer and explicit actual_n_scope')
    return {'asset_id': aid, 'package_group_id': package, 'task_ids': task_ids,
            'scope': 'explicit_task_mapping' if task_ids else 'package_only',
            'stage': stage, 'evidence_state': evidence_state,
            'file_sha256': sha, 'file_size_bytes': size,
            'sha256_verified': verified, 'raw_hash_verified': row.get('raw_hash_verified') is True,
            'verification_method': known(row.get('verification_method')),
            'assay_identity_verified': row.get('assay_identity_verified') is True,
            'admitted': False, 'actual_n': file_n, 'actual_n_scope': file_n_scope,
            'dataset_alias': known(row.get('dataset_alias')),
            'original_split': known(row.get('original_split')),
            'exact_qc_state': known(row.get('exact_qc_state')),
            'source_url': public_url(row.get('source_url') or candidate.get('direct_url')),
            'download_url': public_url(row.get('download_url')),
            'resolved_url': public_url(row.get('resolved_url')),
            'release_or_commit': known(row.get('release_or_commit')),
            'assay_doi': known(row.get('assay_doi')),
            'experimental_accession': known(row.get('experimental_accession')),
            'rights_status': known(row.get('rights_status')) or 'NOT_VERIFIED',
            'rights_proof_url': public_url(row.get('rights_proof_url') or row.get('license_evidence_url'))}


def rnagym_classification(root):
    """Publish only numeric, explicitly file-scoped inventory conclusions."""
    path = root / AUDIT_RNAGYM_INVENTORY
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding='utf-8-sig'))
    if raw.get('admitted') is True:
        raise ValueError('v0.1 preview admission lock: inventory is not admission')
    keys = ('reference_count', 'mrna_coding_fitness_proxy_candidates',
            'noncoding_or_splicing_candidate_files')
    counts = {key: raw.get(key) for key in keys}
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in counts.values()):
        raise ValueError('RNAGym classification requires nonnegative integer file counts')
    if counts[keys[0]] != counts[keys[1]] + counts[keys[2]]:
        raise ValueError('RNAGym reference classification file counts do not sum')
    optional_keys = ('ncRNA_candidate_files', 'mrna_splicing_candidate_files',
                     'mrna_coding_proxy_candidate_files', 'rna_candidate_files_safely_extracted',
                     'rna_candidate_file_records')
    for key in optional_keys:
        value = raw.get(key)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError('RNAGym inventory counts must be nonnegative integers')
            counts[key] = value
    if all(k in counts for k in optional_keys[:2]):
        if counts['ncRNA_candidate_files'] + counts['mrna_splicing_candidate_files'] != counts[keys[2]]:
            raise ValueError('RNAGym ncRNA/splicing file counts do not sum')
    if counts.get('mrna_coding_proxy_candidate_files', counts[keys[1]]) != counts[keys[1]]:
        raise ValueError('RNAGym coding proxy file counts disagree')
    if counts.get('rna_candidate_files_safely_extracted', 0) > counts[keys[2]]:
        raise ValueError('RNAGym extracted candidate files exceed classified candidates')
    return dict(counts, scope='REFERENCE_FILES_NOT_VERIFIED_ASSAYS',
                record_count_scope='PROCESSED_FILE_ROWS_NOT_DEDUPLICATED_NOT_TASK_N',
                status='ALL_HOLD_NOT_ADMITTED', source=AUDIT_RNAGYM_INVENTORY)


def poc_audit_summary(root, assets):
    """Report public PoC aggregates without turning input identity into assay N."""
    path = root / AUDIT_POC
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding='utf-8-sig'))
    keys = ('files_downloaded_and_sha256_verified', 'compressed_bytes_downloaded',
            'paired_files_exact_qc_pass', 'unique_paired_inputs_across_downloaded_mirbench',
            'independent_assays_verified', 'review_ready', 'admitted')
    result = {key: raw.get(key) for key in keys}
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in result.values()):
        raise ValueError('PoC summary requires nonnegative integer scoped counts')
    verified = [a for a in assets if a['sha256_verified']]
    if result[keys[0]] != len(verified) or result[keys[1]] != sum(a['file_size_bytes'] for a in verified):
        raise ValueError('PoC file/byte counts disagree with asset evidence; regenerate audit snapshots together')
    if result['admitted'] or result['review_ready'] or result['independent_assays_verified']:
        raise ValueError('v0.1 preview admission lock: PoC must not assert assay verification/review/admission')
    result.update(scope='DOWNLOADED_POC_FILES_ONLY_NOT_TASK_N',
                  paired_count_scope='EXACT_UNIQUE_ORDERED_INPUT_PAIRS_NOT_INDEPENDENT_ASSAYS',
                  unique_paired_input_scope='FOUR_SMALL_POC_FILE_VERSIONS_ONLY_LARGE_FILES_NOT_EXACT_DEDUPED',
                  all_p0_dod_met=raw.get('all_p0_dod_met') is True, source=AUDIT_POC)
    return result


def encode(data):
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def build_site(root=ROOT):
    rows = read_csv(root, REGISTRY)
    tasks_by_id = indexed(rows, 'task_id')
    if len(rows) != 198:
        raise ValueError(f'expected 198 search-level task rows; got {len(rows)}')
    families = indexed(read_csv(root, FAMILIES), 'source_family_id')
    packages = indexed(read_csv(root, PACKAGES), 'package_group_id')
    candidates = indexed(read_csv(root, ASSETS, optional=True), 'asset_id')
    audit_tasks = indexed(read_csv(root, AUDIT_TASKS, optional=True, delimiter='\t'), 'task_id')
    if set(audit_tasks) - set(tasks_by_id):
        raise ValueError('task_status.tsv contains an unknown task ID')
    assets = [public_asset(row, candidates, packages, tasks_by_id)
              for row in load_evidence(root)]
    indexed(assets, 'asset_id')
    assets.sort(key=lambda row: row['asset_id'])
    rnagym_audit = rnagym_classification(root)
    poc_audit = poc_audit_summary(root, assets)
    tasks, cards = [], []
    for task_id, row in sorted(tasks_by_id.items()):
        if row['来源族ID'] not in families or row['下载包ID'] not in packages:
            raise ValueError(f'unknown source-family/package foreign key: {task_id}')
        audit = audit_tasks.get(task_id, {})
        registry_status = row['当前准入状态']
        if audit.get('package_group_id') and audit['package_group_id'] != row['下载包ID']:
            raise ValueError(f'task status package mismatch: {task_id}')
        for value in (registry_status, audit.get('status'), audit.get('admission_status'),
                      audit.get('final_status'), audit.get('stage'), audit.get('state')):
            no_admission(value)
        # A lifecycle stage is not an admission decision. Preserve both.
        audit_status = known(audit.get('admission_status') or audit.get('status')
                             or audit.get('final_status') or audit.get('state'))
        status = audit_status if audit_status and audit_status.startswith(('HOLD_', 'EXCLUDED_')) else registry_status
        stage = known(audit.get('stage'))
        if not stage and audit.get('state') in STAGES:
            stage = audit['state']
        if stage and stage not in STAGES and not stage.startswith(('HOLD_', 'QUARANTIN')):
            raise ValueError(f'unrecognized task lifecycle stage: {stage}')
        task = {'id': task_id, 'title': row['实验任务'], 'dataset': row['原始数据集候选'],
                'family': row['标准任务类别'], 'source_family_id': row['来源族ID'],
                'package': row['下载包ID'], 'readout': row['细分readout'],
                'input_track': row['公平输入轨道'], 'metric': row['主指标(建议)'],
                'loss': row['推荐Loss'], 'control_baseline': row['最低信息Baseline'],
                'baseline': row['经典算法Baseline'], 'model_baseline': row['随机初始化Baseline'],
                'baseline_status': row['baseline运行状态'], 'leakage': row['泄露检查重点'],
                'registry_status': registry_status, 'audit_status': audit_status,
                'status': status, 'stage': stage, 'admission_status': 'NOT_ADMITTED',
                'source': public_url(row['核验发布入口']), 'reason': row['暂缓/风险理由'],
                'hold_reason': known(audit.get('hold_reason')), 'next_action': known(audit.get('next_action')),
                'reported_n': row.get('N(原登记)', ''),
                'reported_n_verification': 'reported/unverified' if known(row.get('N(原登记)')) else 'unknown',
                'actual_n': None, 'actual_n_scope': None,
                'dataset_n': dataset_size(row), 'provenance_id': task_id}
        tasks.append(task)
        files = [a for a in assets if a['package_group_id'] == task['package']]
        cards.append({'id': task_id,
                      'canonical_assay_id': known(audit.get('canonical_assay_id') or audit.get('assay_id')),
                      'source_family_id': task['source_family_id'], 'package_group_id': task['package'],
                      'original_assay_doi': known(row.get('原始assay DOI')),
                      'experimental_accession': known(row.get('原始assay accession')),
                      'benchmark_reference_url': public_url(row.get('论文或Benchmark DOI/URL（非原始assay DOI）')),
                      'source_url': task['source'], 'release_or_commit': known(row.get('版本/commit')),
                      'raw_file_sha256': checksum(row.get('原始文件SHA256')),
                      'rights_status': known(row.get('数据重分发许可')) or 'NOT_VERIFIED',
                      'rights_evidence_url': None, 'identity_status': 'NOT_VERIFIED',
                      'split_status': 'NOT_VERIFIED', 'files': files,
                      'package_audit': rnagym_audit if task['package'] == 'RNAGYM_DMS' else None,
                      'candidate_assets': [
                          {'asset_id': a['asset_id'], 'url': public_url(a.get('direct_url')),
                           'status': 'LINK_ONLY_BYTES_UNVERIFIED'}
                          for _, a in sorted(candidates.items()) if a['package_group_id'] == task['package']],
                      'audit_snapshot_present': task_id in audit_tasks})
    inputs = []
    for relative in (REGISTRY, FAMILIES, PACKAGES, ASSETS, AUDIT_TASKS, AUDIT_ASSETS, AUDIT_RNAGYM_INVENTORY, AUDIT_POC):
        path = root / relative
        inputs.append({'path': relative, 'present': path.exists(),
                       'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None})
    payloads = {'tasks.json': encode(tasks), 'provenance.json': encode(cards)}
    dates = sorted({r['search_audit_date'] for r in packages.values() if r.get('search_audit_date')})
    summary = {'schema_version': 1, 'project': 'RNA-Gym', 'as_of': dates[-1] if dates else None,
               'registered_task_rows': len(tasks), 'source_families': len(families),
               'download_packages': len(packages),
               'review_ready_tasks': sum(t['stage'] == 'REVIEW_READY' for t in tasks),
               'final_admitted_tasks': 0,
               'raw_files_sha256_verified': len({a['file_sha256'] for a in assets if a['sha256_verified']}),
               'rnagym_reference_classification': rnagym_audit,
               'poc_audit': poc_audit,
               'held_task_rows': sum(t['status'].startswith('HOLD_') for t in tasks),
               'excluded_task_rows': sum(t['status'].startswith('EXCLUDED_') for t in tasks),
               'tasks_with_reported_sample_n': sum(t['dataset_n']['value'] is not None for t in tasks),
               'status_counts': dict(Counter(t['status'] for t in tasks)),
               'family_counts': dict(Counter(t['family'] for t in tasks)),
               'inputs': inputs,
               'data_sha256': {name: hashlib.sha256(content).hexdigest() for name, content in payloads.items()},
               'note': 'Search-level registry, not independent assays or admitted datasets. Review-ready is not admitted. No scores.'}
    payloads['summary.json'] = encode(summary)
    return payloads


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='read-only byte-for-byte verification of every generated JSON')
    args = parser.parse_args(argv)
    try:
        payloads = build_site(ROOT)
        stale = []
        for name in OUTPUTS:
            out = ROOT / 'site/data' / name
            if args.verify:
                if not out.exists() or out.read_bytes() != payloads[name]:
                    stale.append(str(out.relative_to(ROOT)))
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                # Do not touch unchanged files. No timestamps or network calls.
                if not out.exists() or out.read_bytes() != payloads[name]:
                    temporary = out.with_suffix('.json.tmp')
                    temporary.write_bytes(payloads[name])
                    temporary.replace(out)
        if stale:
            print('STALE: ' + ', '.join(stale) + '; run python tools/generate_site.py', file=sys.stderr)
            return 1
        print(('VERIFIED' if args.verify else 'GENERATED') + ': tasks, provenance, summary; 198 registered, 0 admitted')
        return 0
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(f'Site generation failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
