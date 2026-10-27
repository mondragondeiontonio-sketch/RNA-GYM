"""Paired cluster bootstrap for one prespecified scalar assay comparison.

Not an across-assay aggregate or a substitute for independent assay replication.
Undefined draws remain in the denominator and are never silently redrawn.
"""
import math
import random

if __package__:
    from .evaluation_protocol import ProtocolError, scalar_metrics
else:
    from evaluation_protocol import ProtocolError, scalar_metrics


def _percentile(values, q):
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    lo, hi = math.floor(index), math.ceil(index)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def paired_group_bootstrap(labels, predictions_a, predictions_b, groups, *,
                           problem, metric, replicates=2000, seed=0,
                           confidence=0.95):
    """Resample independent declared groups, paired across the two methods.

    The caller must resolve independence scientifically. Grouping by row IDs
    does not establish gene/homology/source independence. CIs condition on the
    supplied panel and fixed fitted models; they omit training-seed variance.
    """
    if (type(replicates) is not int or not 1 <= replicates <= 100000 or
            type(seed) is not int or not 0 < confidence < 1):
        raise ProtocolError('INVALID_BOOTSTRAP_CONFIGURATION')
    if not (len(labels) == len(predictions_a) == len(predictions_b) == len(groups)):
        raise ProtocolError('UNPAIRED_BOOTSTRAP_INPUT')
    allowed = {'regression': {'spearman', 'pearson', 'mse', 'mae', 'r2'},
               'binary_classification': {'average_precision', 'mcc', 'auroc', 'brier', 'log_loss', 'accuracy', 'f1'}}
    if metric not in allowed.get(problem, set()):
        raise ProtocolError('UNSUPPORTED_BOOTSTRAP_METRIC')
    a = scalar_metrics(labels, predictions_a, problem)[metric]
    b = scalar_metrics(labels, predictions_b, problem)[metric]
    clusters = {}
    for i, group in enumerate(groups):
        if not isinstance(group, str) or not group.strip():
            raise ProtocolError('EXPLICIT_NONEMPTY_GROUP_ID_REQUIRED')
        clusters.setdefault(group, []).append(i)
    report = {'schema_version': 'rna_gym.paired_group_bootstrap.v1',
              'metric': metric, 'difference_definition': 'A_MINUS_B_RAW_METRIC',
              'n_observations': len(labels), 'n_groups': len(clusters),
              'replicates_requested': replicates, 'replicates_attempted': 0, 'seed': seed,
              'confidence': confidence, 'difference': a-b if a is not None and b is not None else None,
              'ci': None, 'valid_replicates': 0, 'undefined_replicates': 0,
              'scope': 'CONDITIONAL_ON_FIXED_MODELS_AND_DECLARED_GROUPS',
              'undefined_draw_policy': 'COUNT_WITHOUT_REDRAW_REPORT_CONDITIONAL_CI'}
    if a is None or b is None or len(clusters) < 2:
        report.update(status='UNDEFINED', reason='UNDEFINED_POINT_OR_FEWER_THAN_TWO_GROUPS')
        return report
    keys = sorted(clusters)
    rng, differences = random.Random(seed), []
    for _ in range(replicates):
        report['replicates_attempted'] += 1
        indices = [i for key in rng.choices(keys, k=len(keys)) for i in clusters[key]]
        y = [labels[i] for i in indices]
        av = scalar_metrics(y, [predictions_a[i] for i in indices], problem)[metric]
        bv = scalar_metrics(y, [predictions_b[i] for i in indices], problem)[metric]
        if av is None or bv is None:
            report['undefined_replicates'] += 1
        else:
            differences.append(av-bv)
    report['valid_replicates'] = len(differences)
    report['status'] = 'OK' if differences else 'UNDEFINED'
    if differences:
        tail = (1-confidence)/2
        report['ci'] = [_percentile(differences, tail), _percentile(differences, 1-tail)]
    return report
