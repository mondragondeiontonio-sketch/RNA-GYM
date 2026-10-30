"""Config-driven metric normalization and frozen-panel hierarchical scoring.

This module does not grant scientific admission and cannot promote exploratory or
paper-reported results into a reproduced leaderboard. Missing raw scores stay None.
"""
import math
from collections import defaultdict


STATUSES = {'EVALUATED', 'UNSUPPORTED', 'NOT_RUN', 'FAILED', 'INCOMPATIBLE', 'REPORTED_ONLY'}
SOURCES = {'RNA_GYM_REPRODUCED', 'EXTERNAL_VERIFIED', 'PAPER_REPORTED'}


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('FINITE_NUMBER_REQUIRED')
    return float(value)


def normalize_score(metric, value, config, *, baseline=None, upper=None):
    value = finite(value)
    norm = config['normalization']
    if metric in ('MAE', 'RMSE'):
        b = finite(baseline)
        if b <= 0 or value < 0:
            raise ValueError('POSITIVE_FROZEN_ERROR_BASELINE_REQUIRED')
        return max(0.0, min(1.0, 1-value/b))
    if metric in ('AUPRC', 'Macro-AUPRC'):
        b, u = finite(baseline), 1.0 if upper is None else finite(upper)
        if not 0 < b < 1:
            raise ValueError('NONDEGENERATE_POSITIVE_PREVALENCE_REQUIRED')
    else:
        defaults = norm['higher_defaults'].get(metric)
        if defaults is None and (baseline is None or upper is None):
            raise ValueError('METRIC_NORMALIZATION_NOT_FROZEN')
        b = defaults[0] if baseline is None else finite(baseline)
        u = defaults[1] if upper is None else finite(upper)
    if u <= b:
        raise ValueError('UPPER_MUST_EXCEED_BASELINE')
    return max(0.0, min(1.0, (value-b)/(u-b)))


def joint_score(components):
    if set(components) != {'MRL', 'Half-life'}:
        raise ValueError('SEPARATE_MRL_AND_HALF_LIFE_REQUIRED')
    values = [finite(v) for v in components.values()]
    if any(not 0 <= v <= 1 for v in values):
        raise ValueError('NORMALIZED_COMPONENTS_REQUIRED')
    return sum(values)/2


def leaf_weights(panel, config):
    """Panel is frozen independently of model results. Missing leaves still count.

    Distinct biological source families receive equal weight. Multiple releases or
    mirrors within an assay divide the same assay weight instead of adding weight.
    Difficulty/track are separate frozen panels, not additional assay weights.
    """
    if not panel:
        raise ValueError('NONEMPTY_FROZEN_PANEL_REQUIRED')
    keys = config['hierarchy']
    if len({r['cell_id'] for r in panel}) != len(panel):
        raise ValueError('DUPLICATE_PANEL_CELL')
    tree = {}
    for row in panel:
        if row.get('scientific_role') == 'SECONDARY_PROXY':
            raise ValueError('SECONDARY_PROXY_CANNOT_ENTER_CORE_PANEL')
        node = tree
        for key in keys:
            value = row.get(key)
            if not isinstance(value, str) or not value:
                raise ValueError('FULL_PANEL_IDENTITY_REQUIRED:'+key)
            node = node.setdefault(value, {})
        if node:
            raise ValueError('DUPLICATE_ASSAY_RELEASE_MIRROR')
        node['cell_id'] = row['cell_id']
    weights = {}
    def walk(node, depth, weight, domain=None, capability=None):
        if depth == len(keys):
            weights[node['cell_id']] = weight
            return
        for key, child in node.items():
            if depth == 0:
                factor = config['macro_domain_weights'].get(key)
                if factor is None:
                    raise ValueError('UNKNOWN_MACRO_DOMAIN')
            elif depth == 1:
                factor = config['capability_weights'][domain].get(key)
                if factor is None:
                    raise ValueError('UNKNOWN_CAPABILITY')
            elif depth == 2:
                factor = config['task_weights'][domain][capability].get(key)
                if factor is None:
                    raise ValueError('UNKNOWN_CANONICAL_TASK')
            else:
                factor = 1/len(node)
            walk(child, depth+1, weight*factor,
                 key if depth == 0 else domain, key if depth == 1 else capability)
    walk(tree, 0, 1.0)
    # A partial panel cannot silently renormalize away missing mandatory capabilities.
    if sum(weights.values()) > 1+1e-9:
        raise ValueError('PANEL_WEIGHT_EXCEEDS_ONE')
    return weights


def aggregate(panel, results, config, *, result_source='RNA_GYM_REPRODUCED'):
    if result_source not in {'RNA_GYM_REPRODUCED', 'EXTERNAL_VERIFIED'}:
        raise ValueError('PAPER_RESULTS_NOT_RANKABLE')
    weights = leaf_weights(panel, config)
    result_map = {}
    for row in results:
        cid = row['cell_id']
        if cid not in weights or cid in result_map:
            raise ValueError('UNREGISTERED_OR_DUPLICATE_RESULT_CELL')
        if row.get('evaluation_status') not in STATUSES or row.get('result_source') not in SOURCES:
            raise ValueError('INVALID_RESULT_STATUS_OR_SOURCE')
        result_map[cid] = row
    weighted, coverage = 0.0, 0.0
    evaluated_capabilities = defaultdict(set)
    cells = []
    for leaf in panel:
        cid = leaf['cell_id']
        result = result_map.get(cid, {'evaluation_status': 'NOT_RUN', 'raw_score': None})
        status = result['evaluation_status']
        score = None
        if status == 'EVALUATED':
            if result.get('result_source') != result_source or result.get('formal_leaderboard_eligible') is not True:
                raise ValueError('UNVERIFIED_OR_EXPLORATORY_RESULT')
            if leaf.get('human_admitted') is not True or leaf.get('scientific_role') == 'SECONDARY_PROXY':
                raise ValueError('HUMAN_ADMITTED_CORE_PANEL_REQUIRED')
            if result.get('raw_metric') != leaf.get('primary_metric'):
                raise ValueError('FROZEN_PRIMARY_METRIC_MISMATCH')
            if leaf.get('primary_metric') == 'Joint-normalized':
                score = joint_score(result['normalized_components'])
            else:
                score = normalize_score(result['raw_metric'], result.get('raw_score'), config,
                    baseline=leaf.get('baseline'), upper=leaf.get('upper'))
            weighted += weights[cid]*score
            coverage += weights[cid]
            evaluated_capabilities[leaf['macro_domain']].add(leaf['level2_category'])
        elif status == 'REPORTED_ONLY':
            if result.get('result_source') != 'PAPER_REPORTED':
                raise ValueError('REPORTED_ONLY_REQUIRES_PAPER_SOURCE')
            if result.get('raw_score') is not None:
                finite(result['raw_score'])
        elif result.get('raw_score') is not None or result.get('normalized_score') is not None:
            raise ValueError('MISSING_STATUS_MUST_KEEP_NA')
        cells.append(dict(cell_id=cid, evaluation_status=status, raw_score=result.get('raw_score'),
            normalized_score=score, weight=weights[cid]))
    rule = config['universal_eligibility']
    eligible = coverage >= rule['minimum_coverage'] and all(
        len(evaluated_capabilities[m]) >= rule['minimum_capabilities_per_macro_domain']
        for m in config['macro_domain_weights'])
    return dict(performance=weighted/coverage if coverage else None, coverage=coverage,
        universal_score=weighted, universal_rank_eligible=eligible, cells=cells)
