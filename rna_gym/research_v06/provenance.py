"""V0.6 provenance and immutable stage receipts; reuse the public protocol primitives."""
from pathlib import Path
import csv
import io
import json
import re
from collections import defaultdict
from tools.evaluation_protocol import (ProtocolError, canonical_bytes, digest_json,
                                       sha256_file, read_json, write_immutable)

UNKNOWN = {'', None, 'UNKNOWN', 'NOT_REPORTED'}
RIGHTS = ('rights_research', 'rights_evaluate', 'rights_redistribute', 'rights_aggregate')


def canonical_sequence(sequence):
    value = sequence.strip().upper().replace('U', 'T')
    if not value or set(value) - set('ACGT'):
        raise ProtocolError('INVALID_SEQUENCE_NO_SILENT_BASE_REPLACEMENT')
    return value


def validate_source(config, raw_root):
    for field in ('source_id', 'source_release', 'assay_id', 'readout_id',
                  'label_raw_unit', 'label_direction', 'label_formula', 'raw_files', *RIGHTS):
        if field not in config:
            raise ProtocolError('MISSING_SOURCE_FIELD:' + field)
    if config['rights_research'] is not True or config['rights_evaluate'] is not True:
        raise ProtocolError('LOCAL_RESEARCH_AND_EVALUATION_RIGHTS_REQUIRED')
    root = Path(raw_root).resolve()
    bound = []
    for entry in config['raw_files']:
        name = Path(entry['path'])
        path = (root / name).resolve()
        if name.is_absolute() or not path.is_relative_to(root):
            raise ProtocolError('RAW_PATH_ESCAPE')
        if not path.is_file():
            raise ProtocolError('RAW_FILE_MISSING:' + str(name))
        actual = sha256_file(path)
        if actual != entry.get('sha256'):
            raise ProtocolError('RAW_HASH_MISMATCH:' + str(name))
        bound.append({'path': str(name), 'sha256': actual, 'bytes': path.stat().st_size})
    if not bound:
        raise ProtocolError('NO_BOUND_RAW_FILES')
    return bound


def require_public_rights(config, *, row_level=False):
    # A license string or public upstream URL cannot authorize a private copy.
    key = 'rights_redistribute' if row_level else 'rights_aggregate'
    if config.get(key) is not True or config.get('rights_review_status') != 'APPROVED':
        raise ProtocolError('PUBLIC_RIGHTS_NOT_APPROVED')
    if config.get('local_only', True):
        raise ProtocolError('LOCAL_ONLY_SOURCE_CANNOT_BE_PUBLISHED')


def immutable_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode('utf-8')
    try:
        with path.open('xb') as f:
            f.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ProtocolError('IMMUTABLE_OUTPUT_CONFLICT:' + path.name)


def write_table(path, rows, fields=None):
    rows = list(rows)
    fields = fields or (list(rows[0]) if rows else [])
    buf = io.StringIO(newline='')
    writer = csv.DictWriter(buf, fieldnames=fields, delimiter='\t', lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    immutable_text(path, buf.getvalue())


def receipt(out, stage, inputs, outputs, counts, *, synthetic=False):
    """No timestamps or absolute paths: repeatable, output-content bound receipt."""
    out = Path(out)
    result = {'schema': 'rnagym.research_v06.receipt.v1', 'stage': stage,
              'inputs': inputs, 'outputs': {Path(p).name: sha256_file(p) for p in outputs},
              'code_sha256': digest_json({str(p.relative_to(Path(__file__).parents[2])): sha256_file(p)
                  for folder in (Path(__file__).parent, Path(__file__).parents[2]/'tools/mrna_design')
                  for p in sorted(folder.glob('*.py'))}),
              'counts': counts, 'synthetic': synthetic,
              'scientific_status': 'SYNTHETIC_NOT_SCIENTIFIC' if synthetic else 'EXPLORATORY_HOLD'}
    result['receipt_id'] = digest_json(result)
    write_immutable(out / 'receipt.json', result)
    return result


def overlap_graph(records):
    """Indexed identity edges; no quadratic all-pairs sequence search or dedup of conditions."""
    fields = {'source_sequence': 'exact-seq', 'sequence_id': 'U/T-equivalent',
              'assay_id': 'same-assay', 'design_group_id': 'same-design-library',
              'construct_id': 'same-construct', 'backbone_id': 'same-vector',
              'source_release': 'shared-author-release'}
    index = defaultdict(list)
    for row in records:
        for field, kind in fields.items():
            value = row.get(field)
            if value in UNKNOWN:
                continue
            index[(kind, value)].append(row['observation_id'])
    # Hyperedges avoid N^2 expansion for large libraries; identity != independence.
    edges = [{'edge_type': k[0], 'identity_hash': digest_json(k[1]),
             'members': sorted(set(v)), 'independent_assay_evidence': False}
            for k, v in sorted(index.items()) if len(set(v)) > 1]
    for row in records:
        if row.get('derived_from') not in UNKNOWN:
            edges.append({'edge_type': 'derived-readout', 'source': row['derived_from'],
                          'target': row['observation_id'], 'directed': True,
                          'independent_assay_evidence': False})
    return edges


def validate_features(features, *, protocol, cell_descriptor=None):
    if protocol in ('C-OUT-DESC', 'SC-OUT') and not cell_descriptor:
        raise ProtocolError('NOT_FEASIBLE_INDEPENDENT_CELL_DESCRIPTOR_REQUIRED')
    for f in features:
        if f.get('fit_role') not in ('train', 'independent', 'author_frozen'):
            raise ProtocolError('TARGET_DERIVED_OR_TEST_FITTED_FEATURE')
        if f.get('uses_target') is not False or f.get('available_at_design') is not True:
            raise ProtocolError('UNAVAILABLE_OR_TARGET_DERIVED_FEATURE')
    if cell_descriptor:
        if (cell_descriptor.get('uses_target') is not False or
                cell_descriptor.get('available_at_design') is not True or
                cell_descriptor.get('fit_role') != 'independent' or
                not cell_descriptor.get('source_sha256')):
            raise ProtocolError('CELL_DESCRIPTOR_NOT_INDEPENDENT')


def public_scan(paths):
    """Extend (not weaken) the existing publication scanner to new nested artifacts."""
    from tools.prepare_public import scan_file
    problems = {}
    for path in map(Path, paths):
        issues = scan_file(path)
        text = path.read_text(encoding='utf-8-sig')
        if re.search(r'/(?:Users|mnt|scratch|gpfs|lustre)/[A-Za-z0-9_./-]+', text):
            issues.append('private absolute path')
        if path.suffix == '.json':
            def inspect(value):
                if isinstance(value, dict):
                    if any(k in value for k in ('hidden_test_labels', 'private_predictions', 'api_key')):
                        issues.append('private structured content')
                    if isinstance(value.get('sequence'), str) and any(k in value for k in ('label', 'label_raw')):
                        issues.append('row-level sequence/label artifact')
                    for item in value.values(): inspect(item)
                elif isinstance(value, list):
                    for item in value: inspect(item)
            inspect(json.loads(text))
        if re.search(r'(?:^|/)(?:runs|raw_data|private_data|checkpoints)/', path.as_posix()):
            issues.append('private-output path')
        if issues:
            problems[str(path)] = issues
    if problems:
        raise ProtocolError('PUBLIC_SAFETY_FAILED:' + json.dumps(problems, sort_keys=True))
    return {'status': 'PASS', 'files_scanned': len(paths)}
