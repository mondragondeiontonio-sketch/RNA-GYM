#!/usr/bin/env python3
"""Freeze or verify the exact local Arena v1 build; never modifies source data.

A changed artifact requires a new freeze version, not overwriting this receipt.
Raw and processed integrity have their own independent content-bound receipts.
"""
import argparse
from pathlib import Path
from tools.build_arena_v1 import ROOT, VERSION, load, dump, sha


def verify(root=ROOT, freeze=False):
    receipt=root/'data/registries/arena_v1_freeze.json'
    if freeze and not receipt.exists():
        names=set()
        patterns=['configs/*v1*.yaml', 'tools/*arena_v1*.py', 'tools/build_arena_v1.py',
            'rna_gym/arena.py', 'rna_gym/submissions.py', 'rna_gym/datasets.py',
            'tests/test_arena_v1.py', 'data/splits/RNAGYM_SPLIT_V1/*/manifest.json',
            'data/audit/taxonomy_mapping_report.tsv', 'data/audit/v1_conflict_findings.tsv',
            'data/audit/rnagym_v1_build_summary.json', 'data/registries/dataset_task_mapping_v1.tsv',
            'data/registries/task_baselines_and_admission_198.csv', 'data/task_bundles/*.json',
            'site/arena.html', 'site/data/arena-v1.json', 'reports/RNAGYM_V1_BUILD_REPORT.md',
            'results/leaderboards/*/*.tsv', 'results/exploratory/baselines_v1.tsv']
        for pattern in patterns:
            names.update(p.relative_to(root).as_posix() for p in root.glob(pattern) if p.is_file())
        dump(receipt, dict(version=VERSION, frozen_date='2026-10-30',
            state='FROZEN_LOCAL_BUILD_NOT_SCIENTIFIC_ADMISSION',
            files={name:sha(root/name) for name in sorted(names)},
            raw_integrity_receipt_sha256=sha(root/'runs/20261030_arena_v1/raw_integrity.json'),
            processed_integrity_receipt_sha256=sha(root/'runs/20261030_arena_v1/local_parquet_verification.tsv'),
            human_admitted=False))
    data=load(receipt)
    for name,expected in data['files'].items():
        path=root/name
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
            raise ValueError('FREEZE_PATH_INVALID:'+name)
        if not path.is_file() or sha(path) != expected:
            raise ValueError('FROZEN_ARTIFACT_CHANGED_CREATE_NEW_VERSION:'+name)
        if '/RNAGYM_SPLIT_V1/' in name and path.name == 'manifest.json':
            manifest = load(path)
            if sha(path.with_name('assignments.tsv')) != manifest['assignments_sha256']:
                raise ValueError('FROZEN_SPLIT_ASSIGNMENTS_CHANGED:'+name)
    for filename, key in [('raw_integrity.json', 'raw_integrity_receipt_sha256'),
                          ('local_parquet_verification.tsv', 'processed_integrity_receipt_sha256')]:
        if sha(root/'runs/20261030_arena_v1'/filename) != data[key]:
            raise ValueError('INTEGRITY_RECEIPT_CHANGED:'+filename)
    print(f"VERIFIED {len(data['files'])} Arena v1 files; no scientific admission granted")
    return data


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--freeze', action='store_true')
    args=p.parse_args()
    verify(freeze=args.freeze)
