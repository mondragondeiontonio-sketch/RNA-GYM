"""Assay/cell metrics and paired sequence-cluster CI. Never a universal score."""
import math
from collections import defaultdict
from .provenance import ProtocolError


def regression(y, p):
    import numpy as np
    from scipy.stats import spearmanr, pearsonr
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    if not len(y) or y.shape != p.shape or not np.isfinite(y).all() or not np.isfinite(p).all():
        raise ProtocolError('INVALID_METRIC_INPUT')
    nonconstant = len(y) >= 3 and np.ptp(y) > 0 and np.ptp(p) > 0
    squared = float(np.mean((y-p)**2))
    return {'n': len(y), 'mae': float(np.mean(abs(y-p))), 'rmse': math.sqrt(squared),
            'spearman': float(spearmanr(y, p).statistic) if nonconstant else None,
            'pearson': float(pearsonr(y, p).statistic) if nonconstant else None,
            'r2': float(1-np.sum((y-p)**2)/np.sum((y-y.mean())**2)) if np.ptp(y) > 0 else None}


def score_predictions(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['cell_id']].append(row)
    if not grouped:
        raise ProtocolError('EMPTY_PREDICTIONS')
    per_cell = {c: regression([float(r['label']) for r in rs],
                              [float(r['prediction']) for r in rs]) for c, rs in sorted(grouped.items())}
    macro, defined = {}, {}
    for metric in ('spearman', 'pearson', 'mae', 'rmse', 'r2'):
        values = [s[metric] for s in per_cell.values() if s[metric] is not None]
        defined[metric] = len(values)
        # A partially undefined panel must not silently gain a different denominator.
        macro[metric] = sum(values)/len(values) if len(values) == len(per_cell) else None
    return {'per_cell': per_cell, 'cell_macro': macro, 'defined_cells': defined,
            'n_cells': len(per_cell), 'n_observations': len(rows),
            'n_sequences': len({r['sequence_id'] for r in rows}),
            'worst_cell_spearman': min((v['spearman'] for v in per_cell.values()), default=None)
             if all(v['spearman'] is not None for v in per_cell.values()) else None,
            'undefined_policy': 'NA_UNDEFINED_NOT_ZERO_NO_WEIGHT_RENORMALIZATION'}


def interaction_gain(additive, interaction, *, replicates=200, seed=6):
    import numpy as np
    if not 1 <= replicates <= 10000:
        raise ProtocolError('INVALID_BOOTSTRAP_REPLICATES')
    def keyed(rows):
        result = {r['observation_id']: r for r in rows}
        if len(result) != len(rows):
            raise ProtocolError('DUPLICATE_PREDICTION_ID')
        return result
    a, b = keyed(additive), keyed(interaction)
    if set(a) != set(b) or not a:
        raise ProtocolError('UNPAIRED_TEST_OBSERVATIONS')
    for oid in a:
        if any(a[oid][k] != b[oid][k] for k in ('label', 'cell_id', 'sequence_id', 'split_hash')):
            raise ProtocolError('MISMATCHED_TEST_TRUTH_OR_SPLIT')
    ids = sorted(a)
    arows, brows = [a[i] for i in ids], [b[i] for i in ids]
    sa, sb = score_predictions(arows), score_predictions(brows)
    groups = defaultdict(list)
    for i, r in enumerate(arows):
        # Caller supplies connected split group; never count cell/time as independent.
        groups[r.get('sequence_group', r['sequence_id'])].append(i)
    def delta(x, y):
        corr = None if x['cell_macro']['spearman'] is None or y['cell_macro']['spearman'] is None else y['cell_macro']['spearman']-x['cell_macro']['spearman']
        return corr, x['cell_macro']['mae']-y['cell_macro']['mae']
    point = delta(sa, sb)
    rng = np.random.default_rng(seed)
    draws = [[], []]
    keys = sorted(groups)
    if len(keys) >= 2:
        for _ in range(replicates):
            indices = [i for k in rng.choice(keys, len(keys), replace=True) for i in groups[k]]
            values = delta(score_predictions([arows[i] for i in indices]),
                           score_predictions([brows[i] for i in indices]))
            for j, v in enumerate(values):
                if v is not None:
                    draws[j].append(v)
    return {'delta_int_spearman': point[0], 'delta_error_mae': point[1],
            'conditional_ci95_spearman': np.quantile(draws[0], [.025, .975]).tolist() if draws[0] else None,
            'conditional_ci95_mae': np.quantile(draws[1], [.025, .975]).tolist() if draws[1] else None,
            'bootstrap_valid': [len(x) for x in draws], 'replicates': replicates,
            'n_groups': len(keys), 'seed': seed, 'formal_ci_eligible': False,
            'ci_scope': 'FIXED_MODELS_CONNECTED_SEQUENCE_GROUPS_NOT_BIOLOGICAL_REPLICATES',
            'replicate_noise': 'NOT_IDENTIFIABLE_WITHOUT_BIOLOGICAL_REPLICATES'}


def require_admitted(evidence):
    if evidence.get('scientific_review_status') != 'ADMITTED' or evidence.get('synthetic'):
        raise ProtocolError('SCIENTIFIC_HOLD_CANNOT_ENTER_FORMAL_SCORE')
    for field in ('assay_review', 'label_review', 'split_review', 'rights_review'):
        if evidence.get(field) != 'APPROVED':
            raise ProtocolError('MISSING_INDEPENDENT_REVIEW:' + field)
    if not evidence.get('reviewer_evidence'):
        raise ProtocolError('NO_REVIEWER_EVIDENCE')
    # Reuse the existing full assay/hash/rights/split human-evidence gate.
    # Bare APPROVED strings are never sufficient to open a new formal track.
    from pathlib import Path
    from tools.admission_gate import evaluate
    bound = evidence.get('admission_evidence')
    if not isinstance(bound, dict):
        raise ProtocolError('EXISTING_ADMISSION_GATE_EVIDENCE_REQUIRED')
    gate = evaluate(bound, base=Path(evidence.get('evidence_root', '.')))
    if gate.get('admitted') is not True:
        raise ProtocolError('EXISTING_ADMISSION_GATE_REJECTED')


def source_macro(records):
    """Only unique assay-level entries; expansion into cell/time views is rejected."""
    source = defaultdict(list)
    seen = set()
    for r in records:
        key = (r['source_family'], r['assay_id'])
        if key in seen:
            raise ProtocolError('DUPLICATE_ASSAY_VOTES_USE_CELL_MACRO_FIRST')
        seen.add(key)
        require_admitted(r)
        source[r['source_family']].append(r['score'])
    return {s: sum(v)/len(v) if all(x is not None for x in v) else None
            for s, v in source.items()}
