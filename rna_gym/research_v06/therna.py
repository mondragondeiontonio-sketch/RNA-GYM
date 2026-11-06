"""Explicit wide-to-long THERNA import. Raw values and missing observations survive."""
import csv
import gzip
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from .provenance import (ProtocolError, canonical_sequence, digest_json, validate_source,
                         write_immutable, receipt)

ENDPOINTS = {'penta': 'GEX_NORMALIZED_REPORTER',
             'tria_abundance': 'NORMALIZED_RNA_ABUNDANCE',
             'tria_decay': 'FITTED_DECAY_RATE'}
FIELDS = ['observation_id', 'sequence_id', 'sequence', 'source_sequence', 'source_id',
          'source_release', 'raw_sha256', 'source_row', 'original_column', 'assay_id',
          'construct_id', 'design_group_id', 'cell_id', 'cell_alias', 'timepoint_value',
          'timepoint_unit', 'readout_id', 'unit', 'label_raw', 'missing_reason',
          'biological_replicate', 'technical_replicate', 'batch_id', 'dna_t0']


def column_map(header, kind, config):
    if len(header) != len(set(header)) or 'sequence' not in header:
        raise ProtocolError('DUPLICATE_COLUMNS_OR_MISSING_SEQUENCE')
    mapping = {}
    aliases = config.get('cell_aliases', {})
    originals = defaultdict(set)
    for column in header:
        if column in ('sequence', 'DNA_T0_pooled_count'):
            continue
        if kind == 'tria_decay':
            cell, hour = column, 'NOT_APPLICABLE'
        else:
            match = re.fullmatch(r'(.+)__(\d+)h', column)
            if not match:
                raise ProtocolError('UNMAPPED_TIME_COLUMN:' + column)
            cell, hour = match.group(1), int(match.group(2))
            expected = [24, 36] if kind == 'penta' else [0, 2, 4, 6, 12, 24]
            if hour not in expected:
                raise ProtocolError('UNEXPECTED_TIMEPOINT')
        canonical = aliases.get(cell, cell)
        originals[canonical].add(cell)
        mapping[column] = (canonical, cell, hour)
    if any(len(v) > 1 for v in originals.values()):
        raise ProtocolError('CELL_ALIAS_COLLISION')
    if len(originals) != config['expected_cells']:
        raise ProtocolError('CELL_COUNT_MISMATCH')
    if kind != 'tria_decay':
        expected = {24, 36} if kind == 'penta' else {0, 2, 4, 6, 12, 24}
        for cell in originals:
            if {v[2] for v in mapping.values() if v[0] == cell} != expected:
                raise ProtocolError('INCOMPLETE_CELL_TIME_GRID')
    selected = config.get('selected_cells', sorted(originals))
    if not set(selected) <= set(originals):
        raise ProtocolError('REQUESTED_CELL_MISSING')
    return {k: v for k, v in mapping.items() if v[0] in selected}, sorted(originals)


def iter_long(path):
    with gzip.open(path, 'rt', newline='') as handle:
        yield from csv.DictReader(handle, delimiter='\t')


def import_therna(config, raw_root, out, *, dry_run=False):
    kind = config['kind']
    if kind not in ENDPOINTS or config['readout_id'] != ENDPOINTS[kind]:
        raise ProtocolError('ASSAY_ENDPOINT_MISMATCH')
    files = validate_source(config, raw_root)
    out = Path(out)
    if not dry_run:
        out.mkdir(parents=True, exist_ok=True)
        if (out / 'long.tsv.gz').exists():
            raise ProtocolError('OUTPUT_EXISTS_VERIFY_RECEIPT_OR_USE_NEW_VERSION')
    counts = Counter()
    cell_qc = defaultdict(Counter)
    sequences = Counter()
    mapping_report = []
    output_handle = None
    if not dry_run:
        output_handle = gzip.open(out / 'long.tsv.gz', 'xt', newline='')
        writer = csv.DictWriter(output_handle, FIELDS, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        rejects_handle = (out / 'rejects.tsv').open('x', newline='')
        rejects = csv.writer(rejects_handle, delimiter='\t')
        rejects.writerow(['raw_sha256', 'source_row', 'reason'])
    try:
        for entry in files:
            with (Path(raw_root) / entry['path']).open(newline='', encoding='utf-8-sig') as handle:
                reader = csv.DictReader(handle)
                mapping, all_cells = column_map(reader.fieldnames, kind, config)
                mapping_report.append({'raw_sha256': entry['sha256'], 'all_cells': all_cells,
                                       'selected_columns': mapping})
                if dry_run:
                    continue
                for number, row in enumerate(reader, 2):
                    counts['raw_rows'] += 1
                    if None in row or any(v is None for v in row.values()):
                        raise ProtocolError('RAGGED_RAW_ROW')
                    try:
                        sequence = canonical_sequence(row['sequence'])
                    except ProtocolError:
                        counts['rejected_sequence_rows'] += 1
                        rejects.writerow([entry['sha256'], number, 'INVALID_SEQUENCE'])
                        continue
                    seq_id = digest_json(sequence)
                    sequences[seq_id] += 1
                    for column, (cell, alias, hour) in mapping.items():
                        value = row[column].strip()
                        missing = 'NOT_MISSING'
                        if value in config.get('missing_values', ['', 'NaN', 'nan', 'NA']):
                            missing = 'SOURCE_MISSING'
                        else:
                            try:
                                numeric = float(value)
                                if not math.isfinite(numeric):
                                    raise ValueError()
                            except ValueError:
                                raise ProtocolError('NONFINITE_OR_UNDECLARED_SENTINEL')
                            cell_qc[cell]['zero'] += numeric == 0
                            cell_qc[cell]['negative'] += numeric < 0
                        cell_qc[cell]['total'] += 1
                        cell_qc[cell]['missing'] += missing != 'NOT_MISSING'
                        counts['long_rows'] += 1
                        counts['missing_observations'] += missing != 'NOT_MISSING'
                        observation = [entry['sha256'], number, column]
                        writer.writerow(dict(zip(FIELDS, [digest_json(observation), seq_id,
                            sequence, row['sequence'], config['source_id'], config['source_release'],
                            entry['sha256'], number, column, config['assay_id'],
                            'UNKNOWN', seq_id, cell, alias, hour, 'h' if isinstance(hour, int)
                            else 'NOT_APPLICABLE', config['readout_id'], config['label_raw_unit'],
                            value if missing == 'NOT_MISSING' else '', missing,
                            'REPLICATES_NOT_AVAILABLE', 'REPLICATES_NOT_AVAILABLE',
                            'NOT_REPORTED', row.get('DNA_T0_pooled_count', 'NOT_REPORTED')])))
    finally:
        if output_handle:
            output_handle.close()
            rejects_handle.close()
    if dry_run:
        return {'status': 'VALIDATED_NO_WRITE', 'files': files, 'columns': mapping_report}
    counts['unique_sequences'] = len(sequences)
    counts['duplicate_sequence_rows'] = sum(v - 1 for v in sequences.values())
    qc = {'counts': dict(counts), 'per_cell': dict(cell_qc), 'columns': mapping_report,
          'normalization': 'AUTHOR_VALUES_UNCHANGED_NO_FILL_NO_RENORMALIZATION',
          'replicate_uncertainty': 'NOT_IDENTIFIABLE_FROM_AGGREGATED_TABLE',
          'near_homology': 'NOT_RUN_EXACT_IDENTITY_ONLY',
          'rights': {k: config[k] for k in config if k.startswith('rights_')},
          'formal_admitted': False}
    write_immutable(out / 'qc.json', qc)
    write_immutable(out / 'source_config.json', config)
    return receipt(out, 'therna_import', {'files': files, 'config_sha256': digest_json(config)},
                   [out / p for p in ('long.tsv.gz', 'rejects.tsv', 'qc.json', 'source_config.json')],
                   dict(counts), synthetic=config.get('synthetic', False))
