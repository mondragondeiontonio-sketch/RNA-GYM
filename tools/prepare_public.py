#!/usr/bin/env python3
"""Create a metadata-only public candidate from an explicit audited allowlist.

Never invokes Git, uses credentials, creates a remote, or pushes by itself.
The output must be a new directory to prevent accidental stale/private files.
"""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = ['README.md', 'requirements-qc.txt', 'LICENSE_NOTICE.md', '.gitignore', '.github/workflows/pages.yml',
       'docs/PUBLIC_PROTOCOL.md', 'docs/CURRENT_AUDIT_STATUS.md',
       'docs/EVALUATION_PROTOCOL.md', 'docs/PHASE2_WEBSITE.md', 'docs/INTERACTIVE_API.md',
       'tools/api_console/api-console.html', 'tools/api_console/api-console.css',
       'tools/api_console/api-console.js', 'pyproject.toml',
       'docs/NATIVE_SDK.md', 'docs/DATASET_TASK_LABEL_AUDIT.md',
       'data/registries/dataset_catalog.json']
REGISTRIES = ['search_level_task_crosswalk_198.csv', 'download_packages_47.csv',
    'source_family_crosswalk_123.csv', 'task_baselines_and_admission_198.csv',
    'RNAGym_NABench_DMS_ID_91.csv', 'miRBench_splits_3.csv']
AUDIT = ['task_status.tsv', 'task_master.tsv', 'assay_master.tsv', 'alias_map.tsv',
    'rights_audit.tsv', 'census_summary.json', 'package_source_status.json',
    'p0_assets.csv', 'rights_decisions.json', 'asset_evidence.json',
    'poc_summary.json', 'poc_overlap_summary.json', 'rna3db_version_review.json',
    'rnagym_archive_inventory.json', 'rnagym_rna_member_allowlist.json',
    'rnagym_file_counts.tsv', 'task_download_index.jsonl', 'hf_mirror_catalog.json', 'hf_file_candidates.csv', 'licensed_small_batch.csv', 'downloaded_file_counts.json', 'observed_pinned_assets.csv']
SECRET_PATTERNS = [
    re.compile(r'gh[pousr]_[A-Za-z0-9_]{20,}'),
    re.compile(r'github_pat_[A-Za-z0-9_]{20,}'),
    re.compile(r'hf_[A-Za-z0-9]{20,}'),
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    re.compile(r'(?i)(?:X-Amz-Signature|[?&]token|[?&]access_token)=[A-Za-z0-9%_/+.-]{8,}'),
    re.compile(r'/(?:home|sibcb1)/[A-Za-z0-9_./-]+'),
    re.compile(r'(?<![A-Z])[ACGTUN]{40,}(?![A-Z])'),
]


def selected_files(root):
    selected = list(TOP)
    selected += ['data/registries/' + f for f in REGISTRIES]
    selected += ['data/assets/download_assets.csv']
    selected += ['data/audit/' + f for f in AUDIT]
    for folder, suffix in [('tools', '.py'), ('tests', '.py'), ('configs', '.json'), ('configs', '.yaml')]:
        selected += [str(p.relative_to(root)) for p in sorted((root / folder).glob('*' + suffix))]
    selected += [str(p.relative_to(root)) for p in sorted((root / 'rna_gym').glob('*.py'))]
    selected += [str(p.relative_to(root)) for p in sorted((root / 'data/task_bundles').glob('*.json'))]
    selected += [str(p.relative_to(root)) for p in sorted((root / 'site').rglob('*'))
                 if p.is_file()]
    return sorted(set(selected))


def scan_file(path):
    if path.is_symlink():
        return ['symlink refused']
    if path.stat().st_size > 8 * 1024 * 1024:
        return ['public metadata/code file too large']
    text = path.read_text(encoding='utf-8-sig')
    problems = []
    for i, pattern in enumerate(SECRET_PATTERNS):
        if pattern.search(text):
            problems.append(f'sensitive-content pattern {i + 1}')
    return problems


def build(root, output):
    if output.exists():
        raise ValueError('output must be new; inspect existing candidate rather than overwrite')
    if not output.resolve().is_relative_to(root.resolve() / 'runs'):
        raise ValueError('publication candidate must be inside ignored local runs/')
    manifests = []
    selected = selected_files(root)
    for name in selected:
        path = root / name
        if not path.is_file():
            raise ValueError('missing public input: ' + name)
        if any(part in {'raw_cache', 'private', 'raw_data', '.venv', '.git', '__pycache__'}
               for part in Path(name).parts):
            raise ValueError('private path in allowlist')
        problems = scan_file(path)
        if problems:
            raise ValueError(f'publication scan failed: {name}: {problems}')
        manifests.append({'path': name, 'bytes': path.stat().st_size,
                          'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    output.mkdir(parents=True)
    for row in manifests:
        target = output / row['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / row['path'], target)
    result = {'state': 'LOCAL_CANDIDATE_NOT_PUBLISHED', 'secret_scan': 'PASS',
              'selection': 'explicit metadata/code allowlist',
              'raw_and_experimental_observations_included': False,
              'original_audit_markdown_included': False,
              'file_count': len(manifests), 'files': manifests}
    (output / 'PUBLIC_FILE_MANIFEST.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    result = build(ROOT, args.out)
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, indent=2))


if __name__ == '__main__':
    main()
