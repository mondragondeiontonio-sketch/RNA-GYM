#!/usr/bin/env python3
"""Deterministic work allocation over existing IDs; not a new assay registry."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = 'data/registries/dataset_catalog.json'
OUTPUT = 'data/registries/task_workstream_index.json'
START = '<!-- WORKSTREAMS:START -->'
END = '<!-- WORKSTREAMS:END -->'
WORKSTREAMS = (
    ('sequence', '序列与调控 / Sequence & regulation',
     ('标量回归', '二/多/多标签分类', 'RNA–蛋白结合'),
     'MRL / TE / half-life / annotation / RBP: distinct endpoints and conditions.'),
    ('secondary', '二级结构 / Secondary structure', ('RNA 2D',),
     'Paired-state, pair-edge and decoded structure are different targets.'),
    ('tertiary', '三级结构 / Tertiary structure', ('RNA 3D',),
     'Assembly, chain, residue mapping, coordinate QC and structure homology.'),
    ('variant', '突变效应 / Variant effects', ('突变效应与排序',),
     'RNA substrate, WT/mutant mapping, orientation and assay/source reuse.'),
    ('probing', '逐核苷酸读出 / Nucleotide probing', ('逐核苷酸回归',),
     'Probe, condition, valid-position masks and raw measurement units.'),
    ('rna_pair', 'RNA–RNA 相互作用 / RNA pairs', ('RNA–RNA 相互作用',),
     'Role-ordered pairs, assay conditions, shared pairs and shortcut controls.'),
    ('ligand', 'RNA–配体 / RNA–ligand', ('RNA–小分子结合',),
     'Compound identity, stereo/scaffold, assay labels and decoy definitions.'),
    ('design', '逆折叠与设计 / Inverse folding & design', ('RNA 逆折叠与生成设计',),
     'Conditioned target structures, design validity and independent evaluation.'),
    ('signal', '原始信号 / Direct-RNA signals', ('Nanopore 原始信号',),
     'Flowcell/chemistry and molecule/read groups; no signal-to-sequence proxy.'),
    ('methodology', '方法与待解析项 / Methods & unresolved', ('排除/仅方法学',),
     'A coarse registered category, not a declaration that every row is excluded.'),
)


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                       allow_nan=False) + '\n').encode('utf-8')


def build(root=ROOT):
    root = Path(root)
    source = (root / CATALOG).read_bytes()
    catalog = json.loads(source)
    groups = []
    remaining = {row['task_id']: row for row in catalog['tasks']}
    if len(remaining) != len(catalog['tasks']):
        raise ValueError('DUPLICATE_LEGACY_TASK_ID')
    for wid, name, types, focus in WORKSTREAMS:
        rows = [row for row in catalog['tasks'] if row['registered_task_type'] in types]
        for row in rows:
            if row['task_id'] not in remaining:
                raise ValueError('TASK_ASSIGNED_TO_MORE_THAN_ONE_WORKSTREAM')
            remaining.pop(row['task_id'])
        groups.append({
            'workstream_id': wid, 'name': name, 'registered_task_types': list(types),
            'scientific_focus': focus, 'registered_task_rows': len(rows),
            'task_ids': [row['task_id'] for row in rows],
            'package_group_ids': sorted({row['package_group_id'] for row in rows}),
            'source_family_ids': sorted({row['source_family_id'] for row in rows}),
            'scientific_state_counts': dict(Counter(row['scientific_state'] for row in rows)),
            'admitted_task_rows': sum(row['admitted'] for row in rows),
            'tasks': [{key: row[key] for key in (
                'task_id', 'dataset_name', 'package_group_id', 'source_family_id',
                'capability', 'scientific_state', 'is_excluded_non_assay',
                'admitted', 'reported_n', 'reported_n_scope', 'task_level_sample_n',
                'artifact_uids')} for row in rows]})
    if remaining:
        raise ValueError('UNASSIGNED_TASK_TYPES_REQUIRE_EXPLICIT_REVIEW:' + ','.join(remaining))
    return {
        'schema_version': 'rna_gym.task_workstreams.v1',
        'scope': 'WORK_ALLOCATION_ONLY_NOT_NEW_TASKS_ASSAYS_OR_RANKING_WEIGHTS',
        'source_catalog_sha256': hashlib.sha256(source).hexdigest(),
        'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'registered_task_rows': len(catalog['tasks']),
        'admitted_task_rows': sum(row['admitted'] for row in catalog['tasks']),
        'count_policy': 'Every legacy task row occurs exactly once; package/source sets can overlap across groups.',
        'sample_count_policy': 'reported_n is source-reported, not actual assay N; task_level_sample_n remains unknown.',
        'workstreams': groups}


def readme_table(index):
    lines = [START, '', '| Workstream / 工作块 | Registered rows / 注册行 | Admitted / 矫正 |',
             '|---|---:|---:|']
    for group in index['workstreams']:
        lines.append(f"| {group['name']} | {group['registered_task_rows']} | {group['admitted_task_rows']} |")
    lines += [f"| **Total / 合计** | **{index['registered_task_rows']}** | **{index['admitted_task_rows']}** |", '', END]
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='Read-only deterministic metadata/README check')
    parser.add_argument('--task', help='Inspect one original task ID without downloads or fitting')
    args = parser.parse_args(argv)
    index = build()
    if args.task:
        found = [(group['workstream_id'], row) for group in index['workstreams']
                 for row in group['tasks'] if row['task_id'] == args.task]
        if len(found) != 1:
            parser.error('Unknown original task ID')
        print(json.dumps({'workstream_id': found[0][0], 'task': found[0][1]},
                         ensure_ascii=False, indent=2))
        return 0
    expected = canonical(index)
    readme = ROOT / 'README.md'
    text = readme.read_text()
    if text.count(START) != 1 or text.count(END) != 1:
        parser.error('README workstream markers must exist exactly once')
    begin, end = text.index(START), text.index(END) + len(END)
    table = readme_table(index)
    if args.verify:
        if not (ROOT / OUTPUT).is_file() or (ROOT / OUTPUT).read_bytes() != expected or text[begin:end] != table:
            parser.error('Stale workstream metadata or README table; rebuild explicitly')
        print('VERIFIED: 198 stable registered IDs, 10 workstreams; no assay or score promotion')
    else:
        (ROOT / OUTPUT).write_bytes(expected)
        readme.write_text(text[:begin] + table + text[end:])
        print('Generated versioned work allocation metadata and README table; original registry unchanged')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
