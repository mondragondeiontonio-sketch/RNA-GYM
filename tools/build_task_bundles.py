#!/usr/bin/env python3
"""Build one source/download/baseline card per registered task, without inventing files."""
import argparse
import csv
import json
from pathlib import Path

from rnagym import ROOT, read_manifest


def read(path, delimiter=','):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f, delimiter=delimiter))


def build():
    tasks = read(ROOT / 'data/registries/search_level_task_crosswalk_198.csv')
    statuses = {r['task_id']: r for r in read(ROOT / 'data/audit/task_status.tsv', '\t')}
    baselines = read(ROOT / 'data/registries/task_baselines_and_admission_198.csv')
    baseline_by_id = {r['task_id']: r for r in baselines}
    if len(tasks)!=198 or len(baseline_by_id)!=198 or len(statuses)!=198:
        raise ValueError('all198task registries must align')
    taxonomy_path = ROOT/'configs/task_taxonomy_v1.yaml'
    canonical = {r['task_id']: r for r in json.loads(taxonomy_path.read_text())['tasks']} if taxonomy_path.exists() else {}
    assets = list(read_manifest().values())
    poc_path = ROOT / 'data/audit/p0_assets.csv'
    if poc_path.exists():
        assets += list(read_manifest(poc_path).values())
    hf_path = ROOT / 'data/audit/hf_file_candidates.csv'
    if hf_path.exists():
        assets += list(read_manifest(hf_path).values())
    evidence_path=ROOT/'data/audit/asset_evidence.json'
    observed={a['asset_id']:a for a in json.loads(evidence_path.read_text())} if evidence_path.exists() else {}
    folder = ROOT / 'data/task_bundles'
    folder.mkdir(exist_ok=True)
    index = []
    for t in tasks:
        tid, group = t['row_id'], t['package_group_id']
        status, baseline = statuses[tid], baseline_by_id[tid]
        cards = []
        seen_urls=set()
        for a in assets:
            if a['package_group_id'] != group:
                continue
            if a['direct_url'] in seen_urls:
                continue
            seen_urls.add(a['direct_url'])
            evidence=observed.get(a['asset_id'],{})
            cards.append({'asset_id': a['asset_id'], 'source_url': a.get('official_source_url') or a['direct_url'],
                'download_url': a['direct_url'], 'filename': a['relative_filename'],
                'link_type': 'FILE_LINK_CANDIDATE', 'expected_sha256': a.get('sha256_expected') or None,
                'identity_scope': 'PACKAGE_ONLY_NOT_PROVEN_TASK_INPUT',
                'downloaded_bytes_verified':evidence.get('raw_hash_verified') is True,
                'observed_sha256':evidence.get('actual_sha256'),
                'actual_file_n':evidence.get('actual_n'),
                'actual_file_n_scope':evidence.get('actual_n_scope'),
                'task_input_identity_verified':False,
                'rights_scope': 'Requires asset-specific acquisition decision, never blanket task approval'})
        card = {'task_id': tid, 'package_group_id': group, 'source_family_id': t['source_family_id'],
            'dataset': t['dataset'], 'task': t['task'], 'input_modality': t['input_modality'],
            'status': status['state'], 'hold_reason': status['hold_reason'], 'next_action': status['next_action'],
            'canonical_assay_id': None, 'reported_n': t['reported_n'], 'count_unit': t['count_unit'],
            'reported_n_status': 'REPORTED_UNVERIFIED', 'actual_task_n': None,
            'source_entry_urls': list(dict.fromkeys(u for u in [t['preferred_package_url'],
                                     t['data_download_url'],t['evidence_url'],t['code_url']] if u)),
            'benchmark_paper_url_not_original_assay': t['paper_url'],
            'assets': cards, 'task_download_completed': False, 'admitted': False,
            'baseline_plan': {k:v for k,v in baseline.items() if any(s in k for s in
                            ['Baseline', 'Loss', '指标', 'Metric', 'modality', '输入', '泄露', 'baseline运行'])},
            'plan_command': f'python tools/task_download.py plan --task {tid}',
            'download_policy': 'Source-entry links are not file bytes. Explicit package-only opt-in required before file candidates can be acquired for audit.'}
        if baseline.get('canonical_mapping_registry'):
            ids = baseline.get('canonical_task_ids_v1', '').split(';')
            card['arena_v1'] = {
                'mapping_status': baseline.get('taxonomy_mapping_status_v1'),
                'canonical_task_ids': [i for i in ids if i],
                'canonical_task_definitions': [canonical[i] for i in ids if i in canonical],
                'local_dataset_mapping': 'data/registries/dataset_task_mapping_v1.tsv',
                'scientific_admission_unchanged': True,
                'reported_task_n_not_replaced_by_local_subset': True}
        (folder / (tid + '.json')).write_text(json.dumps(card,ensure_ascii=False,indent=2)+'\n')
        index.append(card)
    target=ROOT / 'data/audit/task_download_index.jsonl'
    target.write_text(''.join(json.dumps(c, ensure_ascii=False, separators=(',',':'))+'\n' for c in index))
    return index


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--verify',action='store_true');a=p.parse_args()
    if a.verify:
        tasks=read(ROOT/'data/registries/search_level_task_crosswalk_198.csv')
        cards=[json.loads(p.read_text()) for p in sorted((ROOT/'data/task_bundles').glob('*.json'))]
        if {t['row_id'] for t in tasks}!={c['task_id'] for c in cards} or len(cards)!=198:
            raise SystemExit('Task bundle mismatch')
        if any(c['admitted'] or c['actual_task_n'] is not None for c in cards):
            raise SystemExit('Unreviewed task escalation refused')
        print('Task bundle verification: 198 metadata-only cards, no invented actual task N/admission')
    else:
        print('Built',len(build()),'task cards')


if __name__=='__main__':main()
