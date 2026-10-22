#!/usr/bin/env python3
"""Exact paired-input audit; no training, normalization, filtering or admission.

DNA-letter representation of RNA pairs is kept unchanged and explicitly tagged.
Exact repeated inputs are not necessarily repeated experimental observations.
"""
import argparse
import collections
import csv
import gzip
import hashlib
import json
from pathlib import Path

from rnagym import ROOT, StateDB, get_target, immutable_json, read_manifest, sha256


def hash_parts(parts):
    # Domain-separated JSON tuple, UTF-8, exact strings, ordered RNA roles.
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False,
                          separators=(',', ':')).encode('utf-8')).hexdigest()


def audit(path, *, dataset, split, output, max_expanded=64 * 1024 * 1024):
    path, output = Path(path), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if path.suffix == '.gz' else open
    delimiter = '\t' if '.tsv' in path.name else ','
    inputs = collections.Counter()
    observations = collections.Counter()
    labels = collections.Counter()
    members = []
    errors = []
    n = expanded = 0
    observed_chars = set()
    rawsha = sha256(path)
    # Bound every decompressed line before CSV parsing (no gzip bomb expansion).
    with opener(path, 'rt', encoding='utf-8-sig', newline='') as f:
        def limited_lines():
            nonlocal expanded
            while True:
                line = f.readline(1024 * 1024 + 1)
                if not line:
                    break
                if len(line) > 1024 * 1024:
                    raise ValueError('expanded line exceeds 1 MiB')
                expanded += len(line.encode('utf-8'))
                if expanded > max_expanded:
                    raise ValueError('expanded file budget exceeded')
                yield line
        rd = csv.DictReader(limited_lines(), delimiter=delimiter)
        fields = rd.fieldnames or []
        required = {'gene', 'noncodingRNA', 'label'}
        if not required.issubset(fields):
            raise ValueError('paired schema missing columns: ' + repr(required - set(fields)))
        for idx, row in enumerate(rd, 1):
            n += 1
            target, mirna, label = row['gene'], row['noncodingRNA'], row['label']
            # Preserve original case, whitespace and T/U. Invalid representations fail.
            observed_chars.update(target + mirna)
            if not target or not mirna or not set(target + mirna) <= set('ACGTUN'):
                if len(errors) < 20:
                    errors.append({'row': idx, 'error': 'INVALID_PAIR_ALPHABET'})
            if label not in ('0', '1'):
                if len(errors) < 20:
                    errors.append({'row': idx, 'error': 'NON_BINARY_LABEL'})
            pairkey = hash_parts(['RNA-GYM:paired-raw:v1', target, mirna])
            # Exact record signature includes all original columns (not only label/input).
            observation = hash_parts(['RNA-GYM:raw-row:v1',
                                      [(k, row.get(k)) for k in fields]])
            inputs[pairkey] += 1
            observations[observation] += 1
            labels[label] += 1
            members.append({'file_sha256': rawsha, 'source_assay_key': None,
                'dataset_alias': dataset, 'row_number': idx, 'original_split': split,
                'input_key': pairkey, 'observation_key': observation,
                'observation_key_scope': 'full raw row, assay identity still unverified',
                'miRNA_family': row.get('noncodingRNA_fam'),
                'gene_group': row.get('gene_cluster_ID'),
                'split_group_status': 'ORIGINAL_SPLIT_PRESERVED_GROUP_LEAKAGE_UNCHECKED'})
    if not n:
        errors.append({'error': 'EMPTY_FILE'})
    report = {'source_sha256': rawsha, 'n_rows': n,
        'n_unique_paired_inputs': len(inputs),
        'repeated_paired_input_rows': n - len(inputs),
        'exact_repeated_record_rows': n - len(observations),
        'label_distribution': dict(labels), 'dataset_alias': dataset,
        'original_split': split, 'split_preserved': True,
        'observed_alphabet': ''.join(sorted(observed_chars)),
        'sequence_representation': 'DNA_LETTERS_FOR_RNA_PAIRS' if 'T' in observed_chars and 'U' not in observed_chars else 'RAW_MIXED_OR_RNA_LETTERS',
        'canonicalization': 'none; exact raw strings; no T/U substitution, case or whitespace changes',
        'identity_hash_algorithm': 'SHA-256(domain-separated JSON ordered tuple UTF-8 compact separators)',
        'exact_qc_state': 'FAIL' if errors else 'PASS_EXACT_PAIRED_QC_ONLY',
        'dedup_action': 'NONE; repeated inputs are not proof of duplicate observations',
        'first_errors': errors, 'admission_gate_pass': False, 'admitted': False,
        'not_checked': ['original assay/batch/construct identity', 'negative generation',
            'cross-split and cross-benchmark pair matching', 'gene/miRNA-family homology leakage',
            'replicate/read counts and biological interpretation', 'human rights and admission review']}
    immutable_json(output / 'qc_paired.json', report)
    identity_path = output / 'sample_identity_map.jsonl'
    text = ''.join(json.dumps(x, sort_keys=True) + '\n' for x in members)
    if identity_path.exists() and identity_path.read_text() != text:
        raise ValueError('identity map conflict')
    if not identity_path.exists():
        identity_path.write_text(text)
        identity_path.chmod(0o444)
    immutable_json(output / 'dedup_report.json', {'state': 'EXACT_RECORD_SCAN_ONLY',
        'actual_n': n, 'repeated_input_rows': n - len(inputs),
        'repeated_record_rows': n - len(observations), 'rows_removed': 0,
        'admission_gate_pass': False})
    immutable_json(output / 'split_manifest.json', {'original_split': split,
        'file_sha256': rawsha, 'seed': None, 'reconstructed': False,
        'group_leakage_checked': False, 'train_transform_fit': False,
        'admission_gate_pass': False})
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--asset', required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--out', type=Path, default=ROOT / 'raw_cache')
    p.add_argument('--dataset', required=True)
    p.add_argument('--split', required=True)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    row = read_manifest(args.manifest)[args.asset]
    with StateDB(ROOT / 'run-state.sqlite') as db:
        key = db.ensure(row)
        old = db.job(key)['stage']
        if old not in ('HASHED', 'PARSED', 'QC_PASS'):
            raise ValueError('HASHED raw file required; run verify first')
        report = audit(get_target(row, args.out), dataset=args.dataset,
                       split=args.split, output=args.output)
        if old == 'HASHED':
            db.transition(key, 'PARSED', evidence=[str(args.output / 'qc_paired.json')])
        if report['exact_qc_state'] == 'PASS_EXACT_PAIRED_QC_ONLY':
            if db.job(key)['stage'] == 'PARSED':
                db.transition(key, 'QC_PASS', detail={'scope': 'exact paired QC only',
                    'NOT_FINAL_ASSAY_QC': True, 'n_rows': report['n_rows']})
        else:
            db.transition(key, 'HOLD_QC', exit_code=2, detail={'error': 'paired QC failed'})
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['exact_qc_state'] == 'PASS_EXACT_PAIRED_QC_ONLY' else 2)


if __name__ == '__main__':
    main()
