#!/usr/bin/env python3
"""Per-task source planning and explicit package-quarantine acquisition.

A successful download never changes task admission or claims a package artifact
is the verified input of a task. Metadata cards preserve unknown sample counts.
"""
import argparse
import json
import re
from pathlib import Path

from rnagym import ROOT, REGISTRY, StateDB, fetch, read_manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['plan', 'download'])
    p.add_argument('--task', required=True)
    p.add_argument('--asset')
    p.add_argument('--package-evidence-only', action='store_true')
    p.add_argument('--execute', action='store_true')
    p.add_argument('--allow-unpinned', action='store_true')
    p.add_argument('--max-mb', type=int, default=16)
    p.add_argument('--rate-kbps', type=int, default=1024)
    p.add_argument('--out', type=Path, default=ROOT / 'raw_cache')
    args = p.parse_args()
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,99}', args.task):
        p.error('expected exact registered task ID; both T... and X... namespaces are preserved')
    card_path = ROOT / 'data/task_bundles' / (args.task + '.json')
    if not card_path.is_file():
        p.error('unknown task; run build_task_bundles.py')
    card = json.loads(card_path.read_text())
    if args.command == 'plan':
        print(json.dumps(card, ensure_ascii=False, indent=2))
        return
    if not (args.asset and args.execute and args.package_evidence_only):
        p.error('unresolved task identities: --asset --execute --package-evidence-only required')
    if args.max_mb <= 0:
        p.error('positive explicit file cap required')
    if card['status'].startswith('EXCLUDED_'):
        p.error('excluded software/control row is not a downloadable assay')
    manifests = [REGISTRY, ROOT / 'data/audit/p0_assets.csv', ROOT / 'data/audit/hf_file_candidates.csv']
    found = [(path, read_manifest(path)[args.asset]) for path in manifests
             if path.exists() and args.asset in read_manifest(path)]
    if len(found) != 1:
        p.error('asset must occur in exactly one registered manifest')
    manifest, row = found[0]
    if row['package_group_id'] != card['package_group_id']:
        p.error('asset belongs to another package; mismatched task provenance refused')
    rights = json.loads((ROOT / 'data/audit/rights_decisions.json').read_text())
    with StateDB(ROOT / 'run-state.sqlite') as db:
        target = fetch(row, args.out, args.max_mb * 1024 * 1024,
                       args.allow_unpinned, db=db, decisions=rights, rate_kbps=args.rate_kbps)
    print(json.dumps({'task_id': args.task, 'asset_id': args.asset,
        'scope': 'PACKAGE_EVIDENCE_ONLY', 'raw_file': str(target),
        'task_download_completed': False, 'assay_identity_verified': False,
        'admitted': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
