"""Independent random-observation CV and nucleotide-cluster OOD CV.

Fold assignment never fits a target transform. Validation is another outer fold
from the training pool, not a globally fitted or reused official validation set.
MMseqs clustering is approximate: cluster disjointness is not proof that every
pair below its search sensitivity is nonhomologous.
"""
import collections
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def select_folds(groups, labels=None, seed=20261028, max_folds=10):
    """Balanced deterministic assignment, at most one fold per stable group."""
    counts = collections.Counter(groups)
    n = len(counts)
    if n < 3:
        return {}, 0, 'FEWER_THAN_THREE_INDEPENDENT_GROUPS'
    k = 10 if n >= 10 and max_folds >= 10 else 5 if n >= 5 and max_folds >= 5 else 3
    if labels is not None:
        support = collections.defaultdict(set)
        for g, y in zip(groups, labels):
            support[str(y)].add(g)
        smallest = min(map(len, support.values()))
        if len(support) < 2 or smallest < 3:
            return {}, 0, 'INSUFFICIENT_CLASS_GROUP_SUPPORT'
        k = min(k, 10 if smallest >= 10 else 5 if smallest >= 5 else 3)
    loads = [0]*k
    class_loads = collections.defaultdict(lambda: [0]*k)
    hist = collections.defaultdict(collections.Counter)
    if labels is not None:
        for g, y in zip(groups, labels):
            hist[g][str(y)] += 1
    ordered = sorted(counts, key=lambda g: (-counts[g], digest(f'{seed}:{g}')))
    assigned = {}
    for g in ordered:
        candidates = range(k)
        if labels is not None:
            # Relative per-class allocation; no observations copied.
            def cost(f):
                return (sum(class_loads[y][f]/max(1, len(support[y])) for y in hist[g]),
                        loads[f], f)
            f = min(candidates, key=cost)
        else:
            f = min(candidates, key=lambda f: (loads[f], f))
        assigned[g] = f
        loads[f] += counts[g]
        for y, v in hist[g].items():
            class_loads[y][f] += v
    return assigned, k, 'TEN_FOLD' if k == 10 else 'REDUCED_FOR_GROUP_OR_CLASS_SUPPORT'


def role(outer_fold, test_fold, k):
    if outer_fold == test_fold:
        return 'test'
    if outer_fold == (test_fold+1) % k:
        return 'validation'
    return 'train'


def cluster_sequences(sequences, directory, mmseqs, threads=4, linear=False):
    """Representative-based MMseqs2 clustering; sensitivity limitations explicit."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    unique = sorted({s.upper().replace('T', 'U') for s in sequences if s})
    fingerprint = digest('\n'.join(unique))
    config = {'identity': 0.8, 'bidirectional_coverage': 0.8, 'cluster_mode': 0, 'kmer_length': 10,
              'alphabet_view': 'uppercase, U/T equivalent for clustering ONLY',
              'sequence_order_sha256': fingerprint,
              'mmseqs_binary_sha256': hashlib.sha256(Path(mmseqs).read_bytes()).hexdigest()}
    if linear:config['algorithm']='easy-linclust'
    cache = directory/'clusters.json'
    if cache.exists():
        previous = json.loads(cache.read_text())
        if previous['parameters'] == config:
            return previous['mapping'], previous['report']
        raise ValueError('CLUSTER_CACHE_FINGERPRINT_MISMATCH')
    if len(unique) == 1:
        mapping = {unique[0]: digest(unique[0])}
        report = {'parameters': config, 'n_sequences': 1, 'n_clusters': 1,
                  'state': 'SINGLE_SEQUENCE_NO_ALIGNMENT_NEEDED'}
    else:
        fasta = directory/'sequences.fasta'
        with fasta.open('w') as f:
            for i, seq in enumerate(unique):
                f.write(f'>s{i}\n{seq.replace("U", "T")}\n')
        command = [str(mmseqs), 'easy-cluster', str(fasta), str(directory/'result'),
                   str(directory/'tmp'), '--dbtype', '2', '--min-seq-id', '0.8',
                   '-c', '0.8', '--cov-mode', '0', '--cluster-mode', '0',
                   '--single-step-clustering', '1', '--threads', str(threads),
                   '--split-memory-limit', '4G', '-k', '10', '--spaced-kmer-mode', '0', '--max-seqs', '1000', '-s', '7.5',
                   '-v', '1']
        if linear:
            command[1]='easy-linclust'
            for flag in ['--single-step-clustering','-s','--max-seqs']:
                i=command.index(flag);del command[i:i+2]
        (directory/'command.json').write_text(json.dumps(command, indent=2))
        with (directory/'stdout.log').open('w') as out, (directory/'stderr.log').open('w') as err:
            proc = subprocess.run(command, stdout=out, stderr=err, timeout=1800)
        if proc.returncode:
            raise RuntimeError(f'MMSEQS_EXIT_{proc.returncode}: {directory}/stderr.log')
        memberships = {}
        for line in (directory/'result_cluster.tsv').read_text().splitlines():
            representative, member = line.split('\t')
            if member in memberships:
                raise ValueError('MMSEQS_MULTIPLE_MEMBERSHIP')
            memberships[member] = representative
        if set(memberships) != {f's{i}' for i in range(len(unique))}:
            raise ValueError('MMSEQS_INCOMPLETE_MEMBERSHIP')
        # Stable cluster identity independent of numerical representative IDs.
        grouped = collections.defaultdict(list)
        for i, seq in enumerate(unique):
            grouped[memberships[f's{i}']].append(seq)
        ids = {rep: digest('\n'.join(sorted(seqs))) for rep, seqs in grouped.items()}
        mapping = {seq: ids[memberships[f's{i}']] for i, seq in enumerate(unique)}
        report = {'parameters': config, 'n_sequences': len(unique), 'n_clusters': len(grouped),
                  'largest_cluster': max(map(len, grouped.values())),
                  'state': 'MMSEQS_LINEAR_REPRESENTATIVE_CLUSTERS' if linear else 'MMSEQS_REPRESENTATIVE_CLUSTERS',
                  'limitation': 'Approximate alignment search; not exhaustive pairwise homology clearance. '
                                'Both-strand nucleotide matches are conservatively grouped. '
                                '0.8 identity/0.8 coverage is a declared protocol, not a universal RNA family definition.'}
    cache.write_text(json.dumps({'parameters': config, 'mapping': mapping, 'report': report}))
    return mapping, report


class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))
    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x
    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[max(a,b)] = min(a,b)


def biological_groups(records, cluster_map):
    """Link identical input, sequence clusters, and declared biological identity.

    For pairs, either endpoint links observations. Shared miRNA/target families
    are additionally enforced when explicitly present. Giant components are
    reported, never split to manufacture OOD feasibility.
    """
    uf = UnionFind(len(records))
    seen = {}
    for i, row in enumerate(records):
        keys = [('input', row['input_hash'])]
        for endpoint in ['sequence', 'sequence_b']:
            seq = row.get('sequence_model_view', row.get(endpoint)) if endpoint=='sequence' else row.get(endpoint)
            if endpoint=='sequence_b' and row.get('sequence_b_kind')=='protein':
                continue
            if seq:
                normalized = seq.upper().replace('T', 'U')
                keys.append((endpoint, cluster_map[normalized]))
        for name, value in row.get('group_metadata', {}).items():
            if value not in (None, '', 'unknown', 'nan', 'UNKNOWN'):
                keys.append((name, str(value)))
        for key in keys:
            if key in seen:
                uf.union(i, seen[key])
            else:
                seen[key] = i
    parts = collections.defaultdict(list)
    for i, row in enumerate(records):
        parts[uf.find(i)].append(row['observation_id'])
    ids = {g: digest('\n'.join(sorted(v))) for g, v in parts.items()}
    return [ids[uf.find(i)] for i in range(len(records))]


def build_splits(records, output, mmseqs, binary=False, seed=20261028, linear=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    labels = [r['label'] for r in records] if binary else None
    protocols = {}
    manifest = []
    # All representations of the same observation have already been mapped to
    # exactly one retained row. Randomness is deterministic per stable identity.
    easy = [r['observation_id'] for r in records]
    try:
        sequences = [s for r in records for s in (r.get('sequence_model_view',r.get('sequence')), r.get('sequence_b') if r.get('sequence_b_kind')!='protein' else None) if s]
        cluster_map, cluster_report = cluster_sequences(sequences, output/'clustering', mmseqs,linear=linear)
        ood = biological_groups(records, cluster_map)
        cluster_error = None
    except Exception as exc:
        ood, cluster_report, cluster_error = [], {}, f'{type(exc).__name__}: {exc}'
    for name, groups in [('EAZY', easy), ('OOD_split', ood)]:
        if not groups:
            protocols[name] = {'status': 'BLOCKED', 'reason': cluster_error or 'NO_USABLE_RECORDS'}
            continue
        assigned, k, reason = select_folds(groups, labels, seed)
        summary = {'status': 'PASS' if k else 'NOT_FEASIBLE', 'n_folds': k,
                   'reason': reason, 'n_records': len(records), 'n_groups': len(set(groups)),
                   'seed': seed, 'group_basis': 'independent observation identity' if name == 'EAZY'
                       else 'sequence homology components + exact input + declared biological group',
                   'validation_rule': 'validation_fold=(test_fold+1)%n_folds; remaining folds train',
                   'pilot_test_folds': [0,3,7] if k == 10 else [],
                   'normalization': 'NONE; any future fitted transform must fit only the train rows',
                   'folds': [], 'classification_support_pass': True}
        if k:
            fold_records = collections.defaultdict(list)
            input_folds = collections.defaultdict(set)
            for r, g in zip(records, groups):
                f = assigned[g]
                manifest.append({'protocol': name, 'observation_id': r['observation_id'],
                                 'record_id': r['record_id'], 'outer_fold': f,
                                 'group_id': g, 'input_hash': r['input_hash']})
                fold_records[f].append(r)
                input_folds[r['input_hash']].add(f)
            for f in range(k):
                rows = fold_records[f]
                values = np.asarray([v for r in rows for v in r.get('finite_labels', [])], dtype=float)
                classes = dict(collections.Counter(str(r['label']) for r in rows)) if binary else None
                if binary and len(classes) < 2:
                    summary['classification_support_pass'] = False
                summary['folds'].append({'fold': f, 'n': len(rows), 'classes': classes,
                    'label_mean': float(values.mean()) if values.size else None,
                    'label_quantiles': np.quantile(values, [0,.25,.5,.75,.95,1]).tolist() if values.size else []})
            summary['leakage'] = {'observation_cross_fold': 0, 'enforced_group_cross_fold': 0,
                'input_cross_fold_groups': sum(len(v)>1 for v in input_folds.values()),
                'exact_input_is_enforced': name == 'OOD_split',
                'homology_clearance': 'CLUSTER_MEMBERSHIP_ONLY_APPROXIMATE' if name == 'OOD_split'
                                      else 'NOT_ENFORCED_RANDOM_CONTROL',
                'train_test_joint_transform_fit': False}
            if not summary['classification_support_pass'] or any(not x['n'] for x in summary['folds']):
                summary['status'] = 'FAIL_FOLD_SUPPORT'
        protocols[name] = summary
    table = pa.Table.from_pylist(manifest, schema=pa.schema([
        ('protocol',pa.string()),('observation_id',pa.string()),('record_id',pa.string()),
        ('outer_fold',pa.int16()),('group_id',pa.string()),('input_hash',pa.string())]))
    target = output/'split_manifest.parquet'
    pq.write_table(table, target, compression='zstd')
    report = {'protocols': protocols, 'clustering': cluster_report,
              'split_manifest_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
              'manifest_semantics': 'one assignment per observation per feasible protocol; '
                  'for each outer test fold use role() or validation_rule to obtain train/validation/test',
              'raw_author_split_modified': False}
    (output/'split_summary.json').write_text(json.dumps(report, indent=2))
    (output/'leakage_report.json').write_text(json.dumps({p:r.get('leakage', {'reason':r['reason']})
                                                     for p,r in protocols.items()}, indent=2))
    return report
