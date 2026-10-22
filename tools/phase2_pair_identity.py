#!/usr/bin/env python3
"""Bounded miRBench compound identity audit; never changes labels or observations.

One *new* projected CSV pass is needed because the previous identity SQLite map
has neither miRNA names nor genomic coordinates. Existing raw SHA proof, full QC,
ordered input hashes and raw-row hashes are reused, not recomputed. Completed
source SHA/algorithm checkpoints avoid rereading unchanged compressed files.
All outputs are local-only identity evidence, not a public measurement snapshot.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat

ALGORITHM = 'mirbench-compound-raw-v1'
PROJECTED_FIELDS = ('gene', 'noncodingRNA', 'noncodingRNA_name', 'chr',
                    'start', 'end', 'strand', 'label')
DEFAULT_PRIOR = 'runs/20261022_212625/reports'
DEFAULT_OUTPUT = 'runs/20261023_043639/reports/pair_identity'
MIRROR_ASSETS = frozenset(('P0_MIR_KLIMENTOVA_ZENODO', 'P0_MIR_KLIMENTOVA_MIRROR'))
PAIR_SCHEMA_VERSION = 'RNA-GYM:paired-raw:v1'  # Existing DB: target first, miRNA second.


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def digest_parts(parts):
    return hashlib.sha256(compact(parts).encode('utf-8')).digest()


def small_sha(path):
    """For code/evidence/output only; never invoked on raw acquisition files."""
    sha = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def snapshot(path):
    info = Path(path).stat()
    return dict(bytes=info.st_size, mtime_ns=info.st_mtime_ns,
                ctime_ns=info.st_ctime_ns, mode=stat.S_IMODE(info.st_mode))


def write_json(path, value):
    path = Path(path)
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    if path.exists():
        if path.read_text() != text:
            raise ValueError(f'immutable evidence conflict: {path}')
        return
    temporary = path.with_name(path.name + f'.part.{os.getpid()}')
    with temporary.open('x', encoding='utf-8') as stream:
        stream.write(text)
    temporary.chmod(0o444)
    temporary.replace(path)


def identities(row, dataset, assay_id=None, condition_id=None,
               assay_verified=False, condition_verified=False):
    """Role-preserving identities; raw strings, T/U, case and coordinates unchanged.

    A name containing '|' remains a set-valued raw identifier, not multiple rows.
    Unknown assembly/coordinate convention prevent a definitive locus identity.
    Dataset-scoped TEMP keys are explicitly NOT real assay/batch/condition IDs.
    """
    assay_id = assay_id or 'TEMP_DATASET:miRBench:' + dataset
    condition_id = condition_id or 'TEMP_UNKNOWN_CONDITION:miRBench:' + dataset
    mirna_id = row.get('noncodingRNA_name') or 'UNKNOWN_MIRNA_ID'
    coordinates = [row.get(key, '') for key in ('chr', 'start', 'end', 'strand')]
    target_id = compact(['genomic_interval', 'assembly:UNKNOWN',
                         'coordinate_system:UNKNOWN', *coordinates])
    flags = ['UNKNOWN_ASSEMBLY', 'UNKNOWN_COORDINATE_CONVENTION']
    if not assay_verified:
        flags.append('UNVERIFIED_ASSAY')
    if not condition_verified:
        flags.append('UNVERIFIED_CONDITION')
    if mirna_id == 'UNKNOWN_MIRNA_ID':
        flags.append('MISSING_MIRNA_ID')
    elif '|' in mirna_id:
        flags.append('MULTIVALUED_MIRNA_ID')
    if any(not x for x in coordinates):
        flags.append('INCOMPLETE_TARGET_COORDINATES')
    pair = [mirna_id, row['noncodingRNA'], target_id, row['gene']]
    return {
        'mirna_id': mirna_id, 'target_id': target_id,
        'original_assay_id': assay_id, 'condition_id': condition_id,
        'assay_identity_verified': assay_verified,
        'condition_identity_verified': condition_verified,
        'cross_assay_pair_sha256': digest_parts([ALGORITHM + ':pair', *pair]),
        'compound_identity_sha256': digest_parts([ALGORITHM + ':observation',
                                                 *pair, assay_id, condition_id]),
        'ambiguity_flags': '|'.join(flags), 'identity_status': 'PROVISIONAL',
    }


def classify(left, right, representation_alias=False):
    """Non-exclusive flags; ambiguity must not be upgraded into a same-assay fact."""
    verified = left['assay_identity_verified'] and right['assay_identity_verified']
    same_assay = verified and left['original_assay_id'] == right['original_assay_id']
    condition_verified = (left['condition_identity_verified'] and
                          right['condition_identity_verified'])
    same_condition = condition_verified and left['condition_id'] == right['condition_id']
    labels_differ = left['raw_label'] != right['raw_label']
    cross_split = left['original_split'] != right['original_split']
    role_mixed = cross_split and ('train' in (left['original_split'], right['original_split']))
    different_scope = left['dataset_alias'] != right['dataset_alias']
    different_assay = verified and not same_assay
    candidate_different_scope = different_scope and not verified
    same_raw_row = left['raw_row_sha256'] == right['raw_row_sha256']
    same_assay_duplicate = bool(same_assay and same_condition and same_raw_row)
    ambiguous = bool(not verified or not condition_verified or
                     left['identity_status'] != 'VERIFIED' or
                     right['identity_status'] != 'VERIFIED')
    categories = []
    if representation_alias:
        categories.append('same_data_representation_alias')
    if same_assay_duplicate:
        categories.append('same_assay_duplicate')
    if different_assay or candidate_different_scope:
        categories.append('same_pair_different_assay')
    if cross_split:
        categories.append('cross_split_same_pair')
    if labels_differ:
        categories.append('conflicting_labels')
    if ambiguous:
        categories.append('ambiguous_identity')
    return dict(categories='|'.join(categories), same_assay_verified=bool(same_assay),
                same_assay_duplicate=same_assay_duplicate,
                same_pair_different_assay=bool(different_assay or candidate_different_scope),
                assay_difference_status='VERIFIED' if different_assay else
                    'PROVISIONAL_DATASET_SCOPE_ONLY' if candidate_different_scope else
                    'SAME_ASSAY_VERIFIED' if same_assay else 'UNRESOLVED',
                cross_split_same_pair=cross_split, train_heldout_input_sharing=role_mixed,
                same_dataset_split_contamination=bool(role_mixed and not different_scope),
                conflicting_labels=labels_differ,
                conflict_interpretation='RAW_LABEL_DISAGREEMENT_NOT_BIOLOGICAL_CONTRADICTION'
                    if labels_differ else 'NONE',
                ambiguous_identity=ambiguous,
                representation_alias=representation_alias,
                same_raw_row_sha256=same_raw_row, rows_removed=0, labels_merged=0,
                decision='KEEP_ALL_SOURCE_ROWS; ALIAS_NOT_INDEPENDENT_OBSERVATION'
                    if representation_alias else 'KEEP_DISTINCT_OBSERVATIONS; REVIEW_IDENTITY',
                status='PROVISIONAL' if ambiguous else 'VERIFIED')


def load_sources(root, prior):
    proof_file = prior / 'final_raw_byte_verification.json'
    proof = json.loads(proof_file.read_text())
    if not proof['all_sha256_match']:
        raise ValueError('previous completed raw-byte proof is not passing')
    sources = []
    for item in proof['artifacts']:
        if item['package_group_id'] != 'MIR_BENCH':
            continue
        aid = item['asset_id']
        report = prior / 'paired_full_qc' / (aid + '-scan.json')
        qc = prior / 'paired_full_qc' / (aid + '-qc.json')
        doc = json.loads(report.read_text())
        qc_doc = json.loads(qc.read_text())
        folder = root / 'raw_cache/quarantine/MIR_BENCH' / aid / item['sha256']
        files = list(folder.glob('*.gz'))
        if len(files) != 1:
            raise ValueError(f'exactly one compressed raw file required: {aid}')
        raw = files[0]
        info = snapshot(raw)
        provenance = json.loads((folder / 'provenance.json').read_text())
        if not item['actual_raw_bytes_verified'] or not item['raw_readonly']:
            raise ValueError(f'completed immutable byte proof missing: {aid}')
        if info['bytes'] != item['bytes'] or info['mode'] & 0o222:
            raise ValueError(f'cached byte size/read-only contract differs: {aid}')
        if not (doc['source_sha256'] == qc_doc['source_sha256'] ==
                provenance['sha256'] == item['sha256']):
            raise ValueError(f'cached SHA evidence disagrees: {aid}')
        if qc_doc['state'] != 'PASS_FULL_FILE_EXACT_PAIRED_QC_ONLY':
            raise ValueError(f'prior file QC not passing: {aid}')
        sources.append(dict(asset_id=aid, raw=raw, raw_snapshot=info,
                            source_sha256=item['sha256'], actual_n=doc['actual_n'],
                            dataset_alias=doc['dataset_alias'],
                            original_split=doc['original_split'],
                            evidence=[str(p.relative_to(root)) for p in (proof_file, report, qc)],
                            source_url=item['source_url']))
    if len(sources) != 7:
        raise ValueError(f'expected seven acquired miRBench file versions, found {len(sources)}')
    return sorted(sources, key=lambda source: source['asset_id'])


def cached_edges(db, sources, overlap_path):
    """Resolve prior exact overlap to row references; no new raw/whole-file QC scan."""
    expected = json.loads(overlap_path.read_text())['comparisons']
    source_ids = {source['asset_id'] for source in sources}
    if any(not {item['left_asset'], item['right_asset']} <= source_ids for item in expected):
        raise ValueError('old overlap report contains an unknown asset')
    if len({(item['left_asset'], item['right_asset']) for item in expected}) != len(expected):
        raise ValueError('duplicate prior overlap comparison')
    edges, wanted = [], collections.defaultdict(set)
    for item in expected:
        left, right = item['left_asset'], item['right_asset']
        rows = db.execute('''SELECT a.row_number,b.row_number,a.input_hash,
                a.observation_hash,b.observation_hash,a.raw_label,b.raw_label
            FROM samples a JOIN samples b ON a.input_hash=b.input_hash
            WHERE a.asset_id=? AND b.asset_id=? ORDER BY a.row_number,b.row_number''',
                          (left, right)).fetchall()
        if len(rows) != item['shared_exact_ordered_pairs']:
            raise ValueError('cached DB overlap disagrees with completed report')
        if sum(row[5] != row[6] for row in rows) != item['label_disagreement_pairs']:
            raise ValueError('cached DB label disagreements disagree with report')
        for row in rows:
            edges.append(dict(left_asset=left, right_asset=right,
                              left_row=row[0], right_row=row[1], input_hash=row[2]))
            wanted[left].add(row[0]); wanted[right].add(row[1])
    # Zero comparisons are inherited from the completed all-file exact scan.
    return edges, wanted


def parquet_schema():
    import pyarrow as pa
    strings = ('asset_id', 'dataset_alias', 'original_split', 'mirna_id', 'target_id',
               'original_assay_id', 'condition_id', 'raw_label', 'identity_status',
               'ambiguity_flags')
    fields = [(name, pa.string()) for name in strings]
    fields += [('row_number', pa.int64())]
    fields += [(name, pa.binary(32)) for name in
               ('raw_asset_sha256', 'raw_row_sha256', 'exact_input_pair_sha256',
                'cross_assay_pair_sha256', 'compound_identity_sha256')]
    fields += [(name, pa.bool_()) for name in
               ('assay_identity_verified', 'condition_identity_verified')]
    return pa.schema(fields, metadata={b'algorithm': ALGORITHM.encode(),
        b'privacy': b'LOCAL_ONLY_IDENTITY_EVIDENCE; NOT_PUBLIC_RELEASE_APPROVAL',
        b'raw_row_reference': b'prior paired_sample_identity.sqlite samples(asset_id,row_number)',
        b'canonicalization': b'NONE; exact raw strings, no T/U, case, ID or coordinate rewriting'})


def checkpoint_key(source):
    return digest_parts([ALGORITHM, source['asset_id'], source['source_sha256'],
                         source['dataset_alias'], source['original_split']]).hex()


def load_checkpoint(path, source, evidence_fingerprint):
    import pyarrow.parquet as pq
    path = Path(path)
    if not path.exists():
        return None
    doc = json.loads(path.read_text())
    if doc['algorithm'] != ALGORITHM or doc['idempotency_key'] != checkpoint_key(source):
        raise ValueError('identity checkpoint algorithm/source mismatch')
    if doc['evidence_fingerprint'] != evidence_fingerprint:
        raise ValueError('checkpoint prior evidence changed')
    if doc['raw_snapshot'] != snapshot(source['raw']):
        raise ValueError('raw stat changed; require a separate byte re-verification, not silent reuse')
    output = path.parent / doc['parquet_filename']
    if not output.exists() or snapshot(output) != doc['output_snapshot']:
        raise ValueError('identity output changed; immutable checkpoint cannot be reused')
    if pq.read_metadata(output).num_rows != doc['actual_n']:
        raise ValueError('identity output footer/checkpoint count mismatch')
    return doc


def audit_source(source, db, output, wanted, evidence_fingerprint):
    import pyarrow as pa
    import pyarrow.csv as pacsv
    import pyarrow.parquet as pq
    aid = source['asset_id']
    basename = aid + '.' + source['source_sha256'] + '.' + ALGORITHM
    checkpoint = output / (basename + '.checkpoint.json')
    cached = load_checkpoint(checkpoint, source, evidence_fingerprint)
    if cached:
        print(compact(dict(asset_id=aid, state='CHECKPOINT_REUSED', n=cached['actual_n'])), flush=True)
        return cached, True
    parquet = output / (basename + '.parquet')
    if parquet.exists():
        raise ValueError(f'output exists without checkpoint: {parquet}; preserve and inspect')
    part = parquet.with_name(parquet.name + '.part')
    # A previous interrupted file is never treated as a completed audit. Preserve it.
    if part.exists():
        part.rename(part.with_name(part.name + f'.interrupted.{os.getpid()}'))
    cursor = db.execute('''SELECT row_number,input_hash,observation_hash,raw_label
        FROM samples WHERE asset_id=? ORDER BY row_number''', (aid,))
    schema = parquet_schema()
    matched = {}
    ambiguities = collections.Counter()
    count = 0
    selected = {field: pa.string() for field in PROJECTED_FIELDS}
    with pa.input_stream(str(source['raw']), compression='gzip') as raw:
        reader = pacsv.open_csv(raw,
            read_options=pacsv.ReadOptions(block_size=8 * 1024 * 1024, use_threads=False),
            parse_options=pacsv.ParseOptions(delimiter='\t' if '.tsv' in source['raw'].name else ','),
            convert_options=pacsv.ConvertOptions(include_columns=list(PROJECTED_FIELDS),
                column_types=selected, strings_can_be_null=False, null_values=[]))
        with pq.ParquetWriter(part, schema, compression='zstd') as writer:
            for batch in reader:
                values = [batch.column(field).to_pylist() for field in PROJECTED_FIELDS]
                cached_rows = cursor.fetchmany(batch.num_rows)
                if len(cached_rows) != batch.num_rows:
                    raise ValueError('new projected rows exceed cached identity map')
                records = []
                for fields, previous in zip(zip(*values), cached_rows):
                    count += 1
                    row = dict(zip(PROJECTED_FIELDS, fields))
                    if previous[0] != count or previous[3] != row['label']:
                        raise ValueError('row-number/label join to prior identity map is not aligned')
                    record = identities(row, source['dataset_alias'])
                    record.update(asset_id=aid, dataset_alias=source['dataset_alias'],
                        original_split=source['original_split'], row_number=count,
                        raw_asset_sha256=bytes.fromhex(source['source_sha256']),
                        raw_row_sha256=previous[2], exact_input_pair_sha256=previous[1],
                        raw_label=row['label'])
                    ambiguities.update(record['ambiguity_flags'].split('|'))
                    if count in wanted:
                        matched[str(count)] = {key: value.hex() if isinstance(value, bytes) else value
                                              for key, value in record.items()}
                    records.append(record)
                writer.write_table(pa.Table.from_pylist(records, schema=schema))
                if count % 200000 < batch.num_rows:
                    print(compact(dict(asset_id=aid, state='NEW_IDENTITY_FIELDS', rows=count)), flush=True)
    if count != source['actual_n'] or cursor.fetchone() is not None:
        raise ValueError('new identity row count differs from previous completed QC')
    if snapshot(source['raw']) != source['raw_snapshot']:
        raise ValueError('raw stat changed while reading projected fields')
    if set(map(int, matched)) != wanted:
        raise ValueError('not all prior shared-row references resolved')
    part.chmod(0o444)
    part.replace(parquet)
    doc = dict(algorithm=ALGORITHM, idempotency_key=checkpoint_key(source),
               asset_id=aid, source_sha256=source['source_sha256'],
               raw_snapshot=source['raw_snapshot'], output_snapshot=snapshot(parquet),
               parquet_filename=parquet.name, output_sha256=small_sha(parquet),
               actual_n=count, status='PROVISIONAL', file_identity_join_status='VERIFIED',
               prior_byte_sha_reused=True, raw_sha_recalculated=False,
               fields_read=list(PROJECTED_FIELDS), evidence=source['evidence'],
               evidence_fingerprint=evidence_fingerprint,
               identity_ambiguity_counts=dict(ambiguities), overlap_row_metadata=matched,
               rows_removed=0, labels_merged=0, admitted=False)
    write_json(checkpoint, doc)
    print(compact(dict(asset_id=aid, state='IDENTITY_AUDIT_COMPLETE', rows=count)), flush=True)
    return doc, False


def overlap_decisions(edges, checkpoints):
    rows = []
    for edge in edges:
        left = checkpoints[edge['left_asset']]['overlap_row_metadata'][str(edge['left_row'])]
        right = checkpoints[edge['right_asset']]['overlap_row_metadata'][str(edge['right_row'])]
        if left['exact_input_pair_sha256'] != right['exact_input_pair_sha256']:
            raise ValueError('overlap references do not share exact role-ordered raw sequences')
        mirror = frozenset((edge['left_asset'], edge['right_asset'])) == MIRROR_ASSETS
        if mirror and left['raw_label'] != right['raw_label']:
            raise ValueError('previously verified mirror representation has changed labels')
        decision = classify(left, right, representation_alias=mirror)
        decision.update(left_asset=edge['left_asset'], left_row=edge['left_row'],
                        right_asset=edge['right_asset'], right_row=edge['right_row'],
                        exact_input_pair_sha256=edge['input_hash'].hex())
        for prefix, value in (('left', left), ('right', right)):
            for name in ('dataset_alias', 'original_split', 'raw_label', 'raw_row_sha256',
                         'raw_asset_sha256', 'compound_identity_sha256',
                         'cross_assay_pair_sha256', 'original_assay_id', 'condition_id',
                         'mirna_id', 'target_id'):
                decision[prefix + '_' + name] = value[name]
        decision['same_compound_key'] = left['compound_identity_sha256'] == right['compound_identity_sha256']
        decision['same_cross_assay_pair_key'] = left['cross_assay_pair_sha256'] == right['cross_assay_pair_sha256']
        decision['evidence'] = 'paired_sample_identity.sqlite:samples(asset_id,row_number); per-source checkpoint; paired_all_split_overlap.json'
        rows.append(decision)
    return rows


def write_tsv(path, records):
    import csv
    fields = list(records[0]) if records else ['status', 'categories']
    temporary = path.with_name(path.name + f'.part.{os.getpid()}')
    with temporary.open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)
    if path.exists():
        if small_sha(path) != small_sha(temporary):
            raise ValueError(f'overlap audit conflict: {path}')
        temporary.unlink()
    else:
        temporary.chmod(0o444)
        temporary.replace(path)


def aggregate_counts(rows):
    flags = ('same_assay_duplicate', 'same_pair_different_assay', 'cross_split_same_pair',
             'conflicting_labels', 'ambiguous_identity', 'representation_alias',
             'train_heldout_input_sharing', 'same_dataset_split_contamination')
    raw_counts = {flag: sum(bool(row[flag]) for row in rows) for flag in flags}
    logical = {}
    for row in rows:
        if row['representation_alias']:
            continue
        sides = sorted(((row['left_dataset_alias'], row['left_original_split']),
                        (row['right_dataset_alias'], row['right_original_split'])))
        key = (tuple(sides), row['exact_input_pair_sha256'])
        if key in logical:
            for flag in flags:
                if bool(row[flag]) != bool(logical[key][flag]):
                    raise ValueError('mirror representation changes an overlap decision')
        logical[key] = row
    return dict(file_row_comparison_counts=raw_counts,
                representation_alias_collapsed_comparison_counts={
                    flag: sum(bool(row[flag]) for row in logical.values()) for flag in flags},
                shared_file_row_comparisons=len(rows),
                distinct_nonmirror_dataset_split_input_comparisons=len(logical),
                unique_shared_exact_input_keys_including_alias=len({row['exact_input_pair_sha256'] for row in rows}),
                unique_shared_exact_input_keys_excluding_alias=len({row['exact_input_pair_sha256'] for row in logical.values()}))


def key_layer_audit(rows):
    """A raw sequence match must not imply matching biological identifiers."""
    counters = collections.Counter()
    for row in rows:
        if row['representation_alias']:
            counters['mirror_input_identity_label_representation_matches'] += 1
            counters['mirror_equal_compound_keys'] += row['same_compound_key']
            counters['mirror_equal_full_raw_row_hashes'] += row['same_raw_row_sha256']
            continue
        counters['nonmirror_exact_sequence_pair_comparisons'] += 1
        counters['nonmirror_equal_identifier_qualified_pair_keys'] += row['same_cross_assay_pair_key']
        counters['nonmirror_equal_compound_keys'] += row['same_compound_key']
        mirna_diff = row['left_mirna_id'] != row['right_mirna_id']
        target_diff = row['left_target_id'] != row['right_target_id']
        counters['nonmirror_different_raw_mirna_id_strings'] += mirna_diff
        counters['nonmirror_different_raw_coordinate_target_id_strings'] += target_diff
        counters['nonmirror_both_raw_id_roles_differ'] += mirna_diff and target_diff
    return dict(status='PROVISIONAL', exact_key_comparison_status='VERIFIED',
                counts=dict(counters),
                unit='source-file row comparisons; mirror representation edges are shown separately',
                interpretation='same_pair_different_assay in the decision table is ONLY a provisional different-dataset-scope candidate based on exact role-ordered sequence input, NOT a verified same miRNA/target identity or distinct assay claim. Different raw names/coordinates may reflect ambiguity or representation differences, not necessarily different biological entities.',
                coordinate_canonicalization='NONE; raw strings including decimal formatting preserved; assembly and convention UNKNOWN',
                no_sequence_or_observation_merge=True,
                evidence='overlap_decisions.tsv plus source-SHA/version checkpoints')


def comparison_counts(rows, sources):
    """All 21 file pairs, including inherited zero overlaps, with scoped counts."""
    flags = ('same_assay_duplicate', 'same_pair_different_assay', 'cross_split_same_pair',
             'conflicting_labels', 'ambiguous_identity', 'representation_alias',
             'train_heldout_input_sharing', 'same_dataset_split_contamination')
    grouped = collections.defaultdict(list)
    for row in rows:
        grouped[tuple(sorted((row['left_asset'], row['right_asset'])))].append(row)
    result = []
    for i, left in enumerate(sources):
        for right in sources[i + 1:]:
            records = grouped[tuple(sorted((left['asset_id'], right['asset_id']))) ]
            item = dict(left_asset=left['asset_id'], right_asset=right['asset_id'],
                        left_dataset_alias=left['dataset_alias'],
                        right_dataset_alias=right['dataset_alias'],
                        left_split=left['original_split'], right_split=right['original_split'],
                        shared_exact_input_pair_count=len(records),
                        same_pair_different_assay_verified_count=sum(
                            row['same_pair_different_assay'] and
                            row['assay_difference_status'] == 'VERIFIED' for row in records),
                        same_pair_different_assay_candidate_dataset_scope_count=sum(
                            row['assay_difference_status'] == 'PROVISIONAL_DATASET_SCOPE_ONLY'
                            for row in records))
            item.update({flag + '_count': sum(bool(row[flag]) for row in records)
                         for flag in flags})
            item.update(status='PROVISIONAL',
                        exact_input_count_status='VERIFIED_FROM_CACHED_FULL_QC',
                        assay_identity_verified=False,
                        evidence='runs/20261022_212625/reports/paired_all_split_overlap.json; overlap_decisions.tsv',
                        action='KEEP_ALL_ROWS; NO_LABEL_MERGE; NO_ASSAY_ID_INFERENCE')
            result.append(item)
    return result


def execute(root, prior, output, dry_run=False):
    root, prior, output = Path(root).resolve(), Path(prior).resolve(), Path(output).resolve()
    sources = load_sources(root, prior)
    db_path = prior / 'paired_sample_identity.sqlite'
    # Job state remains owned by the main worker. This DB is read-only sample evidence.
    evidence = {str(path.relative_to(root)): small_sha(path) for path in
                [prior / 'final_raw_byte_verification.json', prior / 'paired_all_split_overlap.json'] +
                [prior / 'paired_full_qc' / (source['asset_id'] + suffix)
                 for source in sources for suffix in ('-scan.json', '-qc.json')]}
    evidence['prior_identity_db_stat'] = snapshot(db_path)
    fingerprint = digest_parts([ALGORITHM, evidence]).hex()
    db = sqlite3.connect('file:' + db_path.as_posix() + '?mode=ro', uri=True)
    try:
        edges, wanted = cached_edges(db, sources, prior / 'paired_all_split_overlap.json')
        if dry_run:
            return dict(algorithm=ALGORITHM, sources=len(sources),
                        source_file_rows=sum(item['actual_n'] for item in sources),
                        prior_overlap_row_comparisons=len(edges), raw_sha_recalculated=False,
                        required_new_fields=['noncodingRNA_name', 'chr', 'start', 'end', 'strand'],
                        new_projection_justification=__doc__, planned_output=str(output.relative_to(root)))
        output.mkdir(parents=True, exist_ok=True)
        checkpoints, reused = {}, 0
        for source in sources:
            doc, cache_hit = audit_source(source, db, output, wanted[source['asset_id']], fingerprint)
            checkpoints[source['asset_id']] = doc
            reused += cache_hit
    finally:
        db.close()
    rows = overlap_decisions(edges, checkpoints)
    decisions_file = output / 'overlap_decisions.tsv'
    write_tsv(decisions_file, rows)
    write_tsv(output / 'overlap_comparison_counts.tsv', comparison_counts(rows, sources))
    counts = aggregate_counts(rows)
    ambiguity = collections.Counter()
    for checkpoint in checkpoints.values():
        ambiguity.update(checkpoint['identity_ambiguity_counts'])
    datasets = sorted({source['dataset_alias'] for source in sources})
    same_file_hash_groups = collections.defaultdict(list)
    for source in sources:
        same_file_hash_groups[source['source_sha256']].append(source['asset_id'])
    summary = dict(algorithm=ALGORITHM, status='PROVISIONAL',
        completed_file_identity_audits=len(checkpoints),
        all_source_file_rows=sum(doc['actual_n'] for doc in checkpoints.values()),
        official_dataset_rows_excluding_mirror=sum(source['actual_n'] for source in sources
            if source['asset_id'] != 'P0_MIR_KLIMENTOVA_MIRROR'),
        source_file_versions=7, dataset_scopes=len(datasets),
        dataset_scopes_are_not_verified_assays=True,
        verified_original_assays=0, verified_conditions=0, admitted_tasks=0,
        compound_identity_rows_provisional=sum(doc['actual_n'] for doc in checkpoints.values()),
        identity_ambiguity_counts=dict(ambiguity),
        exact_raw_file_duplicate_groups=[group for group in same_file_hash_groups.values() if len(group) > 1],
        new_projected_pass_justification='Prior SQLite omits miRNA names and genomic coordinates; read only eight required identity/label columns once, retain all prior input/raw-row hashes. This is a new compound-identity audit, not rerun file QC.',
        raw_hash_policy='Reuse previous completed byte SHA proof plus current read-only size/stat snapshot; raw bytes were NOT freshly rehashed in this run. A changed stat fails closed.',
        sequence_canonicalization='NONE: raw sequence T/U and case preserved; role order explicit',
        id_policy='noncodingRNA_name is the raw miRNA ID, including unresolved | alternatives. gene is target SEQUENCE, never target ID. Target ID is raw chr/start/end/strand with assembly and coordinate system explicitly UNKNOWN. gene_cluster_ID is NOT a biological gene ID and is not used in compound identity.',
        assay_condition_policy='TEMP_DATASET and TEMP_UNKNOWN_CONDITION are internal unresolved namespaces, NOT experiment accessions or proof of shared assay/batch.',
        hash_algorithms={
            'compound_identity_sha256': 'SHA256(UTF8 compact JSON [algorithm+:observation,miRNA_id,miRNA_sequence,target_id,target_sequence,temporary_assay_id,temporary_condition_id])',
            'cross_assay_pair_sha256': 'SHA256(UTF8 compact JSON [algorithm+:pair,miRNA_id,miRNA_sequence,target_id,target_sequence]); excludes assay AND condition',
            'exact_input_pair_sha256': 'REUSED prior SHA256(UTF8 compact JSON [RNA-GYM:paired-raw:v1,target_sequence,miRNA_sequence]); IDs/conditions excluded for all cross-source exact-input auditing',
            'raw_row_sha256': 'REUSED original full-field raw-row SHA; reference is prior samples(asset_id,row_number), row numbering starts at 1 excluding header',
        },
        overlap_count_semantics='Flags overlap and must not be summed. File comparisons count mirror representation edges; separate dataset/split/input comparisons collapse mirror alias only, never merge observations or labels.',
        mirror_alias={'status': 'VERIFIED_INPUT_LABEL_REPRESENTATION_ALIAS_ONLY',
            'asset_ids': sorted(MIRROR_ASSETS),
            'shared_exact_inputs_same_label': sum(row['representation_alias'] for row in rows),
            'equal_full_raw_row_hashes': sum(row['representation_alias'] and row['same_raw_row_sha256'] for row in rows),
            'not_independent_experimental_observations': True,
            'raw_file_bytes_or_full_row_hashes_identical': False},
        split_interpretation='Original split names unchanged. Cross-dataset train/heldout sharing is a potential pooled/transfer leakage route, not proof of within-dataset official split contamination or same-assay duplication.',
        unresolved=['original assay/accession/batch', 'biological condition and replicate identity',
                    'genome assembly and genomic coordinate convention',
                    'multi-valued miRNA names', 'negative sampling and label semantics',
                    'gene/family homology split policy', 'source rights and human admission review'],
        decisions_sha256=small_sha(decisions_file),
        prior_evidence=evidence,
        artifacts=[{key: doc[key] for key in ('asset_id', 'source_sha256', 'actual_n',
                     'parquet_filename', 'output_sha256', 'status', 'file_identity_join_status')}
                   for doc in checkpoints.values()],
        rows_removed=0, labels_merged=0, splits_changed=0, models_run=0,
        new_downloads=0, pickle_deserialization=False, **counts)
    write_json(output / 'summary.json', summary)
    write_json(output / 'identity_key_layer_audit.json', key_layer_audit(rows))
    # Runtime reuse is separate from immutable scientific summary.
    print(compact(dict(status=summary['status'], rows=summary['all_source_file_rows'],
                       source_checkpoints_reused=reused, summary=str((output / 'summary.json').relative_to(root)))), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--prior', type=Path, default=Path(DEFAULT_PRIOR))
    parser.add_argument('--output', type=Path, default=Path(DEFAULT_OUTPUT))
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    prior = args.prior if args.prior.is_absolute() else root / args.prior
    output = args.output if args.output.is_absolute() else root / args.output
    result = execute(root, prior, output, args.dry_run)
    if args.dry_run:
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
