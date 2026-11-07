"""Evidence gates: APA, measured tail length and designed-tail function are distinct."""
from .provenance import ProtocolError

TASKS = ('APA_USAGE', 'TAIL_LENGTH_DYNAMICS', 'TAIL_DESIGN_FUNCTION')


def validate_polya(evidence, *, formal=False):
    task = evidence.get('task_id')
    if task not in TASKS:
        raise ProtocolError('UNKNOWN_POLYA_TASK')
    if evidence.get('label_origin') in (None, 'THERNA_EXPRESSION', 'MODEL_SCORE', 'SYNTHETIC'):
        raise ProtocolError('REAL_INDEPENDENT_POLYA_LABEL_REQUIRED')
    fields = ['source_doi', 'raw_sha256', 'construct_id', 'cell_id', 'readout_method']
    if task == 'APA_USAGE':
        fields += ['site_id', 'usage_measurement']
    elif task == 'TAIL_LENGTH_DYNAMICS':
        fields += ['measured_tail_length', 'measurement_platform', 'selection_method',
                   'caller_version', 'biological_sample_id', 'timepoint_value']
    else:
        fields += ['design_tail_length', 'tail_topology', 'tail_linkage',
                   'tail_modification', 'measured_function', 'backbone_id']
    missing = [f for f in fields if evidence.get(f) in (None, '', 'UNKNOWN', 'NOT_REPORTED')]
    if missing:
        raise ProtocolError('SCIENTIFIC_HOLD_MISSING:' + ','.join(missing))
    if formal:
        from .scoring import require_admitted
        require_admitted(evidence)
    return {'status': 'EVIDENCE_SCHEMA_COMPLETE_NOT_AUTOMATIC_ADMISSION', 'task_id': task}


def require_factorial(evidence):
    if evidence.get('crossed_UTR_TAIL_CELL_same_system') is not True:
        raise ProtocolError('NOT_IDENTIFIABLE_POLYA_UTR_CELL_INTERACTION')
