"""Read-only replay of all legacy fold hashes and fold-0 QC. Never edits old splits."""
import csv
import gzip
import math
from pathlib import Path
from collections import Counter
from rna_gym.research_v06.provenance import (ProtocolError, canonical_sequence, digest_json,
    sha256_file, read_json, write_immutable, write_table, receipt)


def audit_utr(registry, raw_root, out):
    records = read_json(registry)['datasets']
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    result = []
    bindings = []
    # Independent group identities can be investigated locally without exporting sequences.
    import sqlite3
    db = sqlite3.connect(out / 'sequence_identity.private.sqlite')
    db.execute('CREATE TABLE IF NOT EXISTS identity(view TEXT, seq TEXT, PRIMARY KEY(view,seq)) WITHOUT ROWID')
    if db.execute('SELECT count(*) FROM identity').fetchone()[0]:
        raise ProtocolError('OUTPUT_ALREADY_CONTAINS_IDENTITY_SCAN_USE_NEW_VERSION')
    for item in records:
        dataset = item['dataset']
        files = []
        for fold, expected in item['fold_files'].items():
            path = Path(raw_root) / dataset / ('fold_' + fold + '.csv.gz')
            if not path.is_file():
                raise ProtocolError('LEGACY_FOLD_MISSING:' + dataset)
            actual = sha256_file(path)
            if actual != expected['sha256']:
                raise ProtocolError('LEGACY_FOLD_CHANGED:' + dataset)
            files.append(actual)
        bindings.append({'dataset': dataset, 'verified_folds': len(files), 'hashes': files})
        n = invalid = eligible = 0
        lengths = Counter()
        role_counts = Counter()
        seen = {}
        rawmin, rawmax = math.inf, -math.inf
        sums = Counter()
        norm_points = []
        with gzip.open(Path(raw_root)/dataset/'fold_0.csv.gz', 'rt', newline='') as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ['sequence', 'raw_label', 'zscore_label', 'set', 'fold']:
                raise ProtocolError('UTR_SCHEMA_CHANGED')
            for row in reader:
                n += 1
                role = row['set']
                if role not in ('train', 'val', 'test') or row['fold'] != '0':
                    raise ProtocolError('INVALID_LEGACY_ROLE_OR_FOLD')
                role_counts[role] += 1
                try:
                    sequence = canonical_sequence(row['sequence'])
                    y, z = float(row['raw_label']), float(row['zscore_label'])
                    if not math.isfinite(y) or not math.isfinite(z):
                        raise ValueError()
                except (ValueError, ProtocolError):
                    invalid += 1
                    continue
                h = digest_json(sequence)
                seen[h] = seen.get(h, 0) | {'train': 1, 'val': 2, 'test': 4}[role]
                lengths[len(sequence)] += 1
                eligible += len(sequence) <= 1022
                rawmin, rawmax = min(rawmin, y), max(rawmax, y)
                if role == 'train':
                    sums['y'] += y; sums['y2'] += y*y
                    sums['z'] += z; sums['z2'] += z*z
                if len(norm_points) < 50:
                    norm_points.append((y, z))
        nt = role_counts['train']
        mean = sums['y']/nt
        std = math.sqrt(max(0, sums['y2']/nt-mean*mean))
        zmean = sums['z']/nt
        zstd = math.sqrt(max(0, sums['z2']/nt-zmean*zmean))
        max_error = max(abs((y-mean)/std-z) for y,z in norm_points) if std else None
        db.executemany('INSERT INTO identity VALUES (?,?)', [(dataset,h) for h in seen])
        db.commit()
        meta = item['row']
        result.append({'dataset_id': item['dataset_id'], 'region': meta['region'],
            'source_family': meta['family'], 'cell': meta['condition'],
            'assay': 'UNKNOWN_REQUIRES_ORIGINAL_ASSAY_BINDING', 'n': n,
            'unique_sequence_n': len(seen), 'duplicate_rows': n-len(seen)-invalid,
            'cross_role_sequence_groups': sum(v not in (1,2,4) for v in seen.values()),
            'invalid_rows': invalid, 'length_min': min(lengths), 'length_max': max(lengths),
            'eligible_length_1022_n': eligible, 'tokenizer_verified': False,
            'raw_min': rawmin, 'raw_max': rawmax, 'raw_label_unit': meta['raw_label_unit'],
            'raw_label_formula': meta['raw_label_formula'], 'train_raw_mean': mean,
            'train_raw_std_population': std, 'train_z_mean': zmean, 'train_z_std': zstd,
            'sample_train_fit_z_max_error': max_error,
            'license': 'UNKNOWN_COPY_SPECIFIC_REVIEW_REQUIRED', 'formal_admitted': False})
        print(dataset, n, flush=True)
    db.execute('CREATE INDEX IF NOT EXISTS by_seq ON identity(seq)')
    overlaps = [{'left': a, 'right': b, 'shared_UT_equivalent_sequences': n,
                 'same_independent_assay': 'UNKNOWN', 'near_homology': 'NOT_RUN'}
                for a,b,n in db.execute('SELECT a.view,b.view,count(*) FROM identity a JOIN identity b ON a.seq=b.seq AND a.view<b.view GROUP BY a.view,b.view')]
    db.close()
    write_table(out/'utr102_qc.tsv', result)
    write_table(out/'utr102_overlap.tsv', overlaps, ['left','right','shared_UT_equivalent_sequences','same_independent_assay','near_homology'])
    write_immutable(out/'fold_hash_verification.json', {'datasets':bindings})
    counts = {'views': len(result), 'view_records_fold0':sum(r['n'] for r in result),
              'fold_files_verified':sum(r['verified_folds'] for r in bindings),
              'overlapping_view_pairs':len(overlaps), 'formal_admitted':0}
    return receipt(out, 'utr102_readonly_audit', {'registry_sha256':sha256_file(registry)},
                   [out/'utr102_qc.tsv',out/'utr102_overlap.tsv',out/'fold_hash_verification.json'],counts)
