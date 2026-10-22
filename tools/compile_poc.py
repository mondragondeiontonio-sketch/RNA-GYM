#!/usr/bin/env python3
"""Compile public aggregate evidence from locally verified quarantine bytes.

Does not copy raw sequences, labels, local paths, signatures or reviewer identities
into public audit snapshots. Canonical assay IDs remain pending, never synthesized.
"""
import argparse
import collections
import csv
import gzip
import hashlib
import json
from pathlib import Path

from rnagym import ROOT, StateDB, get_target, immutable_json, read_manifest, sha256
from qc_paired import hash_parts
from audit_sources import write_tsv


PAIRED = {
    'P0_MIR_KLIMENTOVA_ZENODO': ('klimentova_zenodo', 'AGO2_eCLIP_Klimentova2022', 'test'),
    'P0_MIR_KLIMENTOVA_MIRROR': ('klimentova_mirror', 'AGO2_eCLIP_Klimentova2022', 'test'),
    'P0_MIR_HEJRET_TEST_ZENODO': ('hejret_test', 'AGO2_CLASH_Hejret2023', 'test'),
    'P0_MIR_HEJRET_TRAIN_ZENODO': ('hejret_train', 'AGO2_CLASH_Hejret2023', 'train'),
}


def collect_pairs(path):
    with gzip.open(path, 'rt', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter='\t' if '.tsv' in path.name else ',')
        return {hash_parts(['RNA-GYM:paired-raw:v1', r['gene'], r['noncodingRNA']]): r['label']
                for r in reader}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--parquet', action='store_true', help='Optional local-only pyarrow export')
    args = p.parse_args()
    audit = ROOT / 'data/audit'
    rows = read_manifest(audit / 'p0_assets.csv')
    extra = audit / 'licensed_small_batch.csv'
    if extra.exists():
        rows.update(read_manifest(extra))
    counts_path=audit/'downloaded_file_counts.json'
    counts={r['asset_id']:r for r in json.loads(counts_path.read_text())} if counts_path.exists() else {}
    evidence, pairsets, identities = [], {}, []
    for aid, row in rows.items():
        raw = get_target(row, ROOT / 'raw_cache')
        if not raw.is_file() or not (raw.parent/'provenance.json').is_file():
            continue
        digest = sha256(raw)
        if digest != raw.parent.name:
            raise ValueError('raw hash changed')
        prov = json.loads((raw.parent / 'provenance.json').read_text())
        item = {'asset_id': aid, 'package_group_id': row['package_group_id'],
            'source_url': row['official_source_url'], 'download_url': row['direct_url'],
            'transport_role': row['transport_role'], 'release_version': row['release_tag'],
            'upstream_commit': row['upstream_commit'] or None,
            'state': 'HASHED_UNPINNED_QUARANTINED', 'sha256': digest,
            'actual_sha256': digest, 'sha256_verified': True,
            'verification_method': 'SHA-256 of actual downloaded raw bytes',
            'size_bytes': raw.stat().st_size, 'actual_n': None,
            'data_license_claim': prov['rights']['license'],
            'license_evidence_url': prov['rights']['evidence_url'],
            'license_evidence_sha256': prov['rights']['evidence_sha256'],
            'rights_decision': 'LOCAL_QUARANTINE_ONLY_NOT_HUMAN_ADMISSION',
            'raw_hash_verified': True, 'admitted': False,
            'human_reviewer': None, 'assay_identity_verified': False,
            'assay_doi': None, 'assay_accession': None}
        if aid in counts:
            item.update({'actual_n':counts[aid]['actual_n'],'actual_n_scope':counts[aid]['actual_n_scope'],'parse_method':counts[aid]['parse_method']})
        if aid in PAIRED:
            folder, dataset, split = PAIRED[aid]
            report = json.loads((args.run / 'reports' / folder / 'qc_paired.json').read_text())
            item.update({'actual_n': report['n_rows'], 'actual_n_scope': 'ONE_FILE_ONE_SPLIT',
                         'dataset_alias': dataset, 'original_split': split,
                         'exact_qc_state': report['exact_qc_state'],
                         'state': 'QC_PASS_EXACT_ONLY_NOT_ADMITTED'})
            pairsets[aid] = collect_pairs(raw)
            identity_file = args.run / 'reports' / folder / 'sample_identity_map.jsonl'
            identities.extend(json.loads(line) for line in identity_file.read_text().splitlines())
        evidence.append(item)
    (audit / 'asset_evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    comparisons = []
    for left, right in [('P0_MIR_KLIMENTOVA_ZENODO', 'P0_MIR_KLIMENTOVA_MIRROR'),
                        ('P0_MIR_HEJRET_TRAIN_ZENODO', 'P0_MIR_HEJRET_TEST_ZENODO'),
                        ('P0_MIR_KLIMENTOVA_ZENODO', 'P0_MIR_HEJRET_TEST_ZENODO'),
                        ('P0_MIR_KLIMENTOVA_ZENODO', 'P0_MIR_HEJRET_TRAIN_ZENODO')]:
        if left not in pairsets or right not in pairsets:
            continue
        shared = pairsets[left].keys() & pairsets[right].keys()
        comparisons.append({'left_asset': left, 'right_asset': right,
            'n_shared_exact_pairs': len(shared),
            'n_shared_pair_label_disagreements': sum(pairsets[left][k] != pairsets[right][k] for k in shared),
            'same_experiment_verified': False,
            'dedup_action': 'none; preserve versions, prohibit double weighting until assay identity review'})
    overlap = {'algorithm': 'exact ordered pair SHA-256; no T/U/case/whitespace canonicalization',
               'comparisons': comparisons, 'admission_gate_pass': False,
               'homology_leakage_checked': False}
    immutable_json(args.run / 'reports/overlap_report.json', overlap)
    (audit / 'poc_overlap_summary.json').write_text(json.dumps(overlap, indent=2) + '\n')
    # A local file/row/split map, never a publicly released experimental observation table.
    if args.parquet:
        import pyarrow as pa
        import pyarrow.parquet as pq
        pq.write_table(pa.Table.from_pylist(identities), args.run / 'reports/sample_identity_map.parquet')
    immutable_json(args.run / 'reports/exclusion_log.json', {
        'rows_removed': 0, 'reason': 'No assay-level duplicate observations proven.',
        'not_core_candidates': '37 RNAGym mRNA-coding protein/genomic fitness proxies pending readout review',
        'admitted': False})
    releases = json.loads((args.run / 'manifests/rna3db-releases.json').read_text())
    snapshot = {'selected_version': None, 'freeze_status': 'HOLD_VERSION_DIFF',
        'reason': 'Sample/PDB-chain comparison required before adoption; old benchmark not replaced.',
        'versions': [{
            'tag': r['tag_name'], 'release_url': r['html_url'],
            'published_at': r['published_at'], 'upstream_target_commitish': r['target_commitish'],
            'assets': [{'filename': a['name'], 'size_bytes': a['size'],
                        'download_url': a['browser_download_url'],
                        'upstream_digest_claim': a.get('digest'),
                        'actual_sha256': None, 'downloaded': False} for a in r['assets']],
        } for r in releases if r['tag_name'] in
            ('2026-01-05-full-release', '2025-10-01-incremental-release')],
        'sample_id_diff': None, 'pdb_chain_diff': None}
    (audit / 'rna3db_version_review.json').write_text(json.dumps(snapshot, indent=2) + '\n')
    # Aggregate per-file N is not an assay-wide N, and a mirror copy is not a new sample set.
    summary = {'files_downloaded_and_sha256_verified': len(evidence),
        'compressed_bytes_downloaded': sum(e['size_bytes'] for e in evidence),
        'paired_files_exact_qc_pass': sum(e.get('exact_qc_state') == 'PASS_EXACT_PAIRED_QC_ONLY' for e in evidence),
        'unique_paired_inputs_across_downloaded_mirbench': len(set().union(*(p.keys() for p in pairsets.values()))),
        'unique_paired_input_scope':'FOUR_SMALL_POC_FILE_VERSIONS_ONLY_LARGE_FILES_NOT_EXACT_DEDUPED',
        'pair_identity_scanned_asset_ids':sorted(pairsets),
        'independent_assays_verified': 0, 'review_ready': 0, 'admitted': 0,
        'all_p0_dod_met': False, 'gpu_used': False, 'training_started': False}
    (audit / 'poc_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    versioned = args.run / 'reports' / ('poc_summary-' + hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest()[:16] + '.json')
    immutable_json(versioned, summary)
    print(json.dumps(summary, indent=2))
    print(json.dumps(comparisons, indent=2))


if __name__ == '__main__':
    main()
