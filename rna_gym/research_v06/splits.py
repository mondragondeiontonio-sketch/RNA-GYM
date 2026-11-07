"""Label-blind axis splits with connected sequence/construct/homology groups."""
from collections import defaultdict
from .provenance import ProtocolError, canonical_sequence, digest_json, validate_features

ROLES = ('train', 'val', 'test')

def identity_hash(rows):
    return digest_json(sorted([r['observation_id'], r['sequence_id'],
        canonical_sequence(r['sequence']), r['cell_id'], str(r['timepoint_value']),
        r.get('assay_id', 'UNKNOWN'), r.get('readout_id', 'UNKNOWN'),
        r.get('construct_id', 'UNKNOWN'), r.get('homology_group_id', 'UNKNOWN')]
        for r in rows))



def sequence_groups(rows):
    parent = {}
    def find(k):
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    for row in rows:
        key = 'seq:' + canonical_sequence(row['sequence'])
        find(key)
        for field in ('construct_id', 'homology_group_id', 'split_group_id'):
            value = row.get(field)
            if value and value not in ('UNKNOWN', 'NOT_REPORTED'):
                other = field + ':' + value
                a, b = find(key), find(other)
                parent[max(a, b)] = min(a, b)
    return {r['sequence_id']: find('seq:' + canonical_sequence(r['sequence'])) for r in rows}


def assign_axis(values, seed, *, train_fraction=0.7, val_fraction=0.15):
    values = sorted(set(values), key=lambda v: digest_json([seed, v]))
    if len(values) < 3:
        raise ProtocolError('AT_LEAST_THREE_AXIS_GROUPS_REQUIRED')
    ntrain = max(1, min(len(values)-2, int(len(values)*train_fraction)))
    nval = max(1, min(len(values)-ntrain-1, int(len(values)*val_fraction)))
    return {v: ROLES[0 if i < ntrain else 1 if i < ntrain+nval else 2]
            for i, v in enumerate(values)}


def make_split(rows, *, protocol='S-OUT', seed=6, cell_descriptor=None):
    if protocol not in ('S-OUT', 'C-OUT-ID', 'C-OUT-DESC', 'SC-OUT', 'TIME-OUT'):
        raise ProtocolError('UNSUPPORTED_SPLIT_PROTOCOL')
    validate_features([], protocol=protocol, cell_descriptor=cell_descriptor)
    groups = sequence_groups(rows)
    seq_roles = assign_axis(groups.values(), seed) if protocol in ('S-OUT', 'SC-OUT') else {}
    cell_roles = assign_axis([r['cell_id'] for r in rows], seed+1) if protocol.startswith('C-OUT') or protocol == 'SC-OUT' else {}
    times = sorted({float(r['timepoint_value']) for r in rows}) if protocol == 'TIME-OUT' else []
    if protocol == 'TIME-OUT' and len(times) < 3:
        raise ProtocolError('TIME_OUT_NEEDS_THREE_TIMES_FOR_TRAIN_VAL_TEST')
    result = []
    seen = set()
    for row in rows:
        oid = row['observation_id']
        if oid in seen:
            raise ProtocolError('DUPLICATE_OBSERVATION_ID')
        seen.add(oid)
        sg = groups[row['sequence_id']]
        if protocol == 'S-OUT':
            role = seq_roles[sg]
        elif protocol.startswith('C-OUT'):
            role = cell_roles[row['cell_id']]
        elif protocol == 'SC-OUT':
            a, b = seq_roles[sg], cell_roles[row['cell_id']]
            role = a if a == b else 'quarantine'
        else:
            t = float(row['timepoint_value'])
            role = 'test' if t == times[-1] else 'val' if t == times[-2] else 'train'
        result.append({'observation_id': oid, 'sequence_group': sg,
                       'cell_id': row['cell_id'], 'role': role})
    report = audit_split(result, protocol)
    manifest = {'synthetic': any(r.get('source_id', '').startswith('SYNTHETIC') for r in rows),
                'schema': 'rnagym.research_v06.split.v1', 'protocol': protocol,
                'seed': seed, 'label_blind': True, 'group_fields': ['canonical_sequence',
                'construct_id', 'homology_group_id', 'split_group_id'],
                'near_homology_status': 'ONLY_IF_SUPPLIED_NO_INFERRED_INDEPENDENCE',
                'observation_id_hash': digest_json(sorted(seen)),
                'identity_hash': identity_hash(rows), 'assignment_hash': digest_json(result), 'no_leakage_report': report,
                'cell_descriptor': cell_descriptor,
                'input_contract': 'CELL_AGNOSTIC_ONLY' if protocol == 'C-OUT-ID' else protocol}
    manifest['split_hash'] = digest_json(manifest)
    return result, manifest


def audit_split(assignment, protocol):
    seq_roles, cell_roles = defaultdict(set), defaultdict(set)
    for row in assignment:
        if row['role'] == 'quarantine':
            continue
        if row['role'] not in ROLES:
            raise ProtocolError('INVALID_SPLIT_ROLE')
        seq_roles[row['sequence_group']].add(row['role'])
        cell_roles[row['cell_id']].add(row['role'])
    if protocol in ('S-OUT', 'SC-OUT') and any(len(v) > 1 for v in seq_roles.values()):
        raise ProtocolError('SEQUENCE_GROUP_CROSSES_ROLES')
    if (protocol.startswith('C-OUT') or protocol == 'SC-OUT') and any(len(v) > 1 for v in cell_roles.values()):
        raise ProtocolError('CELL_CROSSES_ROLES')
    counts = {r: sum(x['role'] == r for x in assignment) for r in (*ROLES, 'quarantine')}
    if any(counts[r] == 0 for r in ROLES):
        raise ProtocolError('EMPTY_SPLIT_ROLE')
    return {'status': 'PASS', 'counts': counts}
