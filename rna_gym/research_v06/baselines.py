"""Bounded CPU sequence/context baselines. No GPU, model loading or downloads."""
from collections import defaultdict
from itertools import product
import time
from .provenance import ProtocolError, digest_json, validate_features
from .splits import audit_split
from .scoring import score_predictions, interaction_gain


def kmer_features(sequences, max_k=3):
    import numpy as np
    if not 1 <= max_k <= 6:
        raise ProtocolError('INVALID_KMER_SIZE')
    vocabulary = [''.join(x) for k in range(1, max_k+1) for x in product('ACGT', repeat=k)]
    values = np.zeros((len(sequences), len(vocabulary)), dtype=float)
    indices = {k: i for i, k in enumerate(vocabulary)}
    for j, seq in enumerate(sequences):
        for k in range(1, max_k+1):
            denominator = max(1, len(seq)-k+1)
            for i in range(len(seq)-k+1):
                values[j, indices[seq[i:i+k]]] += 1/denominator
    return values


def run_baselines(rows, assignment, manifest, config):
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    from sklearn.decomposition import TruncatedSVD
    begin = time.process_time()
    audit_split(assignment, manifest['protocol'])
    if digest_json(assignment) != manifest['assignment_hash']:
        raise ProtocolError('SPLIT_ASSIGNMENT_HASH_MISMATCH')
    verify = dict(manifest)
    claimed = verify.pop('split_hash')
    if digest_json(verify) != claimed:
        raise ProtocolError('SPLIT_MANIFEST_HASH_MISMATCH')
    if digest_json(sorted(r['observation_id'] for r in rows)) != manifest['observation_id_hash']:
        raise ProtocolError('SPLIT_DATASET_ID_MISMATCH')
    from .splits import identity_hash
    if identity_hash(rows) != manifest['identity_hash']:
        raise ProtocolError('FROZEN_OBSERVATION_IDENTITY_CHANGED')
    validate_features(config.get('features', []), protocol=manifest['protocol'],
                      cell_descriptor=manifest.get('cell_descriptor'))
    index = {r['observation_id']: r for r in assignment}
    observed = [r for r in rows if r.get('missing_reason', 'NOT_MISSING') == 'NOT_MISSING'
                and index[r['observation_id']]['role'] != 'quarantine']
    readouts = {(r['assay_id'], r['readout_id'], r['unit']) for r in observed}
    if len(readouts) != 1:
        raise ProtocolError('NO_POOLING_DISTINCT_ASSAYS_READOUTS_OR_UNITS')
    # Bounded label-blind subsets are fixed per outer role, never chosen using y.
    keep = {}
    for role, maximum in config.get('max_sequences_per_role', {}).items():
        ids = {r['sequence_id'] for r in observed if index[r['observation_id']]['role'] == role}
        keep[role] = set(sorted(ids, key=lambda s: digest_json([config['seed'], s]))[:maximum])
    if config.get('max_sequences_per_role'):
        observed = [r for r in observed if r['sequence_id'] in keep.get(index[r['observation_id']]['role'], set())]
    # Keep frozen scientific identities intact; negative controls alter only model inputs.
    import random
    control = config.get('negative_control')
    if control not in (None, 'TRAIN_CELL_PERMUTATION', 'MONONUCLEOTIDE_SHUFFLE'):
        raise ProtocolError('UNKNOWN_NEGATIVE_CONTROL')
    if control:
        observed = [dict(r) for r in observed]
        rng = random.Random(config['seed'])
        if control == 'TRAIN_CELL_PERMUTATION':
            strata = defaultdict(list)
            for i, r in enumerate(observed):
                if index[r['observation_id']]['role'] == 'train':
                    strata[(r['assay_id'], r['timepoint_value'], r.get('batch_id', 'UNKNOWN'))].append(i)
            for indices in strata.values():
                cells = [observed[i]['cell_id'] for i in indices]
                rng.shuffle(cells)
                for i, c in zip(indices, cells):
                    observed[i]['cell_id'] = c
        else:
            mapping = {}
            for r in observed:
                if r['sequence_id'] not in mapping:
                    bases = list(r['sequence']); rng.shuffle(bases)
                    mapping[r['sequence_id']] = ''.join(bases)
                r['sequence'] = mapping[r['sequence_id']]
    roles = np.array([index[r['observation_id']]['role'] for r in observed])
    train, val, test = [np.where(roles == role)[0] for role in ('train', 'val', 'test')]
    if min(len(train), len(val), len(test)) == 0 or len(observed) > config.get('max_observations', 50000):
        raise ProtocolError('EMPTY_ROLE_OR_CPU_SCOPE_EXCEEDED')
    y = np.array([float(r['label_raw']) for r in observed])
    if not np.isfinite(y).all():
        raise ProtocolError('NONFINITE_LABEL')
    xraw = kmer_features([r['sequence'] for r in observed], config.get('max_k', 3))
    scaler = StandardScaler().fit(xraw[train])
    x = scaler.transform(xraw)
    times = np.array([0 if r['timepoint_value'] == 'NOT_APPLICABLE' else float(r['timepoint_value'])
                      for r in observed]).reshape(-1, 1)
    times = StandardScaler().fit(times[train]).transform(times)
    if manifest['protocol'] in ('C-OUT-DESC', 'SC-OUT'):
        descriptor = manifest['cell_descriptor']['values']
        try:
            context = np.array([descriptor[r['cell_id']] for r in observed], dtype=float)
        except KeyError:
            raise ProtocolError('MISSING_PREDICTION_TIME_CELL_DESCRIPTOR')
        context = StandardScaler().fit(context[train]).transform(context)
    else:
        encoder = OneHotEncoder(handle_unknown='ignore', sparse_output=False)
        cells = np.array([r['cell_id'] for r in observed]).reshape(-1, 1)
        context = encoder.fit(cells[train]).transform(cells)
    context = np.column_stack([context, times])
    rank = min(config.get('interaction_rank', 4), len(train)-1, x.shape[1]-1)
    svd = TruncatedSVD(n_components=rank, random_state=config['seed']).fit(x[train])
    factors = svd.transform(x)
    interaction = (factors[:, :, None] * context[:, None, :]).reshape(len(y), -1)
    design = {'B2_SEQUENCE': x, 'B3_ADDITIVE': np.column_stack([x, context]),
              'B4_INTERACTION_LOW_RANK': np.column_stack([x, context, interaction])}
    if manifest['protocol'] == 'C-OUT-ID':
        design = {'B2_SEQUENCE': x}  # ID-only zero-shot is cell-agnostic, not an embedding trick.
    predicted = {'B0_GLOBAL': np.full(len(y), y[train].mean())}
    selected = {}
    if manifest['protocol'] not in ('C-OUT-ID', 'C-OUT-DESC', 'SC-OUT'):
        sums = defaultdict(list)
        for i in train:
            sums[(observed[i]['cell_id'], observed[i]['timepoint_value'])].append(y[i])
        predicted['B1_CELL_TIME'] = np.array([np.mean(sums[(r['cell_id'], r['timepoint_value'])])
              if (r['cell_id'], r['timepoint_value']) in sums else y[train].mean() for r in observed])
    for name, matrix in design.items():
        best = None
        for alpha in config.get('ridge_alphas', [1.0, 10.0]):
            model = Ridge(alpha=alpha).fit(matrix[train], y[train])
            loss = float(np.mean(abs(y[val]-model.predict(matrix[val]))))
            if best is None or loss < best[0]:
                best = loss, alpha, model
        selected[name] = {'alpha': best[1], 'validation_mae': best[0]}
        predicted[name] = best[2].predict(matrix)
    predictions, scores = {}, {}
    for name, p in predicted.items():
        output = [{'observation_id': observed[i]['observation_id'],
                   'sequence_id': observed[i]['sequence_id'],
                   'sequence_group': index[observed[i]['observation_id']]['sequence_group'],
                   'cell_id': observed[i]['cell_id'], 'label': float(y[i]),
                   'prediction': float(p[i]), 'model': name, 'split_hash': manifest['split_hash']}
                  for i in test]
        predictions[name] = output
        scores[name] = score_predictions(output)
    gain = interaction_gain(predictions['B3_ADDITIVE'], predictions['B4_INTERACTION_LOW_RANK'],
                            replicates=config.get('bootstrap_replicates', 200), seed=config['seed']) if 'B3_ADDITIVE' in predictions else None
    return predictions, {'models': scores, 'interaction_gain': gain, 'selection': selected,
            'role_observations': {r: int(sum(roles == r)) for r in ('train', 'val', 'test')},
            'role_sequences': {r: len({observed[i]['sequence_id'] for i in np.where(roles == r)[0]})
                               for r in ('train', 'val', 'test')},
            'split_hash': manifest['split_hash'], 'config_hash': digest_json(config),
            'cpu_process_seconds': time.process_time()-begin, 'gpu_hours': 0,
            'synthetic': manifest.get('synthetic', False),
            'B5_CONDITIONED_FM': 'NOT_RUN_NO_NEW_ENCODING_OR_AUTHORIZED_CACHE',
            'B6_ADAPT': 'BLOCKED_NO_NEW_GPU_SCOPE', 'formal_admitted': False,
            'interaction_method': 'TRAIN_ONLY_SVD_KMER_FACTORS_TIMES_CONTEXT_RIDGE',
            'training_statistics_hash': digest_json({'mean': scaler.mean_.tolist(),
                   'scale': scaler.scale_.tolist(), 'train_y_mean': float(y[train].mean())})}
