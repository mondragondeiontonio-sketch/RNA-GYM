#!/usr/bin/env python3
"""Bounded public-source census; HTTP success is NEVER file verification.

Writes append-only source probes to SQLite and public metadata-only audit views.
No canonical assay identities are invented from benchmark or paper names.
"""
import argparse
import concurrent.futures
import csv
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from rnagym import ROOT, StateDB, immutable_json, now


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_tsv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fields, delimiter='\t', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def public_probe(row):
    url = row['preferred_download_url'] or row['code_url']
    result = {'package_group_id': row['package_group_id'], 'source_url': url,
              'checked_at_utc': now(), 'bytes_downloaded': False,
              'file_sha256_verified': False, 'license_verified': False,
              'original_assay_identity_verified': False}
    if not url:
        return {**result, 'probe_state': 'NO_SOURCE_URL', 'error': None}
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password:
        return {**result, 'probe_state': 'HOLD_SOURCE', 'error': 'unsafe source URL'}
    try:
        request = urllib.request.Request(url, method='HEAD',
                   headers={'User-Agent': 'RNA-Gym-source-audit/0.2'})
        with urllib.request.urlopen(request, timeout=12) as response:
            result.update({'probe_state': 'HTTP_ENTRY_REACHABLE',
                           'http_status': response.status, 'final_url': response.url,
                           'etag': response.headers.get('ETag'),
                           'last_modified': response.headers.get('Last-Modified'),
                           'declared_size_bytes': response.headers.get('Content-Length')})
    except Exception as e:
        result.update({'probe_state': 'HTTP_ENTRY_UNVERIFIED',
                       'http_status': getattr(e, 'code', None),
                       'error': f'{type(e).__name__}: {str(e)[:180]}'})
    return result


def create_views(run, probes, db):
    packages = read_csv(ROOT / 'data/registries/download_packages_47.csv')
    tasks = read_csv(ROOT / 'data/registries/search_level_task_crosswalk_198.csv')
    audit = ROOT / 'data/audit'
    audit.mkdir(parents=True, exist_ok=True)
    non_assay = {'METHODOLOGY_ONLY', 'RNABENCH_SOFTWARE', 'RNA_PUZZLE_TOOL'}
    auth = {'OPENVACCINE', 'RIBONANZA_ORIGINAL'}
    release = {'NABENCH_SELEX', 'DORADO_MOD'}
    indexed = {r['package_group_id']: r for r in probes}
    statuses = []
    for t in tasks:
        group = t['package_group_id']
        if group in non_assay:
            state, reason = 'EXCLUDED_NON_ASSAY', 'Software/method resource is not an independent experimental assay.'
        elif group in auth:
            state, reason = 'HOLD_AUTH', 'Competition access/terms and publicly available label scope require approval; hidden labels are unavailable.'
        elif group in release:
            state, reason = 'HOLD_RELEASE', 'Public original assay release/accession not established; no hidden or unreleased data assumed.'
        elif indexed.get(group, {}).get('probe_state') == 'HTTP_ENTRY_REACHABLE':
            state, reason = 'HOLD_LICENSE', 'Entry HTTP probe only; data-specific rights, raw bytes, assay DOI/accession and identity remain unverified.'
        else:
            state, reason = 'HOLD_SOURCE', 'Original source bytes and assay evidence unresolved; upstream entry may be unavailable. Independent tasks continue.'
        if state == 'EXCLUDED_NON_ASSAY':
            action = 'Retain as auxiliary software/method reference; no assay weight.'
        else:
            action = 'Resolve original assay DOI/accession and data-specific rights, select capped public file, then bytes/hash/schema/identity/split/QC and human review.'
        statuses.append({'task_id': t['row_id'], 'package_group_id': group,
                         'assay_id': '', 'state': state, 'hold_reason': reason,
                         'next_action': action, 'reported_n': t['reported_n'],
                         'reported_n_verification': 'REPORTED_UNVERIFIED',
                         'actual_n': '', 'actual_n_scope': 'NOT_MEASURED',
                         'source_family_id': t['source_family_id']})
        row = {'asset_id': 'TASK_' + t['row_id'], 'package_group_id': group,
               'direct_url': t.get('preferred_package_url') or ''}
        key = db.ensure(row, task_id=t['row_id'])
        # Never overwrite a later local task's completed stage on census replay.
        old = db.job(key)['stage']
        if old == 'QUEUED' or old.startswith(('HOLD_', 'EXCLUDED_')):
            db.transition(key, state, detail={'reason': reason, 'not_admitted': True},
                          evidence=['data/audit/task_status.tsv'])
    fields = list(statuses[0])
    write_tsv(audit / 'task_status.tsv', fields, statuses)
    write_tsv(audit / 'task_master.tsv', ['task_id', 'package_group_id', 'assay_id',
              'source_family_id', 'state', 'reported_n', 'reported_n_verification',
              'actual_n', 'actual_n_scope'], statuses)
    immutable_json(run / 'reports/source_probe_snapshot.json', probes)
    (audit / 'package_source_status.json').write_text(json.dumps(probes, indent=2) + '\n')
    write_tsv(audit / 'rights_audit.tsv', ['package_group_id', 'source_url',
              'rights_decision', 'data_license', 'next_action'],
              [{**p, 'rights_decision': 'HOLD_REVIEW', 'data_license': '',
                'next_action': 'Resolve original data terms; code license does not approve underlying assays.'}
               for p in probes])
    for name, fields in {
        'assay_master.tsv': ['canonical_assay_id', 'source_assay_id', 'origin_paper_doi',
            'accession', 'construct_id', 'wt', 'species', 'cell', 'timepoint', 'probe',
            'readout', 'molecule_type', 'review_status'],
        'alias_map.tsv': ['dataset_alias', 'source_assay_id', 'canonical_assay_id',
                          'evidence_path', 'identity_status'],
    }.items():
        path = audit / name
        if not path.exists():
            write_tsv(path, fields, [])
    (audit / 'census_summary.json').write_text(json.dumps({
        'registered_tasks': len(tasks), 'package_groups': len(packages),
        'source_families': len({r['source_family_id'] for r in tasks}),
        'task_status_counts': {s: sum(t['state'] == s for t in statuses)
                               for s in sorted({t['state'] for t in statuses})},
        'admitted': 0, 'review_ready': 0, 'actual_sample_counts_verified': 0,
        'scope': 'source-entry census, not full assay admission',
        'all_47_original_assays_traced': False,
    }, indent=2) + '\n')
    return statuses


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--probe', action='store_true', help='Explicit bounded metadata-only network scan')
    args = p.parse_args()
    rows = read_csv(ROOT / 'data/registries/download_packages_47.csv')
    cache = args.run / 'manifests/package_probes.json'
    if args.probe:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(public_probe, rows))
        immutable_json(cache, results)
    elif cache.exists():
        results = json.loads(cache.read_text())
    else:
        results = [{**r, 'source_url': r['preferred_download_url'] or r['code_url'],
                    'probe_state': 'NOT_CHECKED'} for r in rows]
    with StateDB(ROOT / 'run-state.sqlite') as db:
        tasks = create_views(args.run, results, db)
    print(json.dumps({'packages_recorded': len(results), 'tasks_classified': len(tasks),
                      'admitted': 0, 'review_ready': 0, 'run': str(args.run)}))


if __name__ == '__main__':
    main()
