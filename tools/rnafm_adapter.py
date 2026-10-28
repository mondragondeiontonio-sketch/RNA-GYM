#!/usr/bin/env python3
"""Local, GPU-only RNA-FM frozen encoder. No downloads or scientific admission.

The model manifest pins reviewed local Python bytes, checkpoint and model card.
CPU checkpoint deserialization is permitted; every encoder forward uses CUDA.
This adapter exposes representations, NOT a native functional/pair score.
"""
import argparse
import copy
import importlib
import json
import os
from pathlib import Path
import re
import resource
import sys
import time

if __package__:
    from . import evaluation_protocol as ep
else:
    import evaluation_protocol as ep


def source_hash(root):
    root = Path(root)
    files = sorted(p for p in (root / 'fm').rglob('*.py') if '__pycache__' not in p.parts)
    if not files:
        raise ep.ProtocolError('RNAFM_SOURCE_MISSING')
    return ep.digest_json({str(p.relative_to(root)): ep.sha256_file(p) for p in files})


def validate_records(records, max_nt):
    if not isinstance(records, list) or not records:
        raise ep.ProtocolError('NONEMPTY_RECORD_LIST_REQUIRED')
    seen = set()
    for record in records:
        oid, seq = record.get('observation_id'), record.get('sequence')
        if not isinstance(oid, str) or not oid or oid in seen:
            raise ep.ProtocolError('MISSING_OR_DUPLICATE_OBSERVATION_ID')
        seen.add(oid)
        if not isinstance(seq, str) or not seq or set(seq) - set('ACGU'):
            raise ep.ProtocolError('EXACT_ACGU_REQUIRED_NO_SILENT_NORMALIZATION')
        if len(seq) > max_nt:
            raise ep.ProtocolError('SEQUENCE_TOO_LONG_NO_TRUNCATION')


def validate_device(device, torch):
    if not isinstance(device, str) or not re.fullmatch(r'cuda:[0-9]+', device):
        raise ep.ProtocolError('GPU_ONLY_EXPLICIT_CUDA_INDEX_REQUIRED')
    index = int(device.split(':')[1])
    if not torch.cuda.is_available() or index >= torch.cuda.device_count():
        raise ep.ProtocolError('REQUESTED_GPU_NOT_ALLOCATED_NO_CPU_FALLBACK')
    return index


class RNAFMAdapter:
    def __init__(self, manifest, *, device='cuda:0', initialization='pretrained', seed=0):
        import torch
        self.torch = torch
        self.gpu = validate_device(device, torch)
        if initialization not in ('pretrained', 'random') or type(seed) is not int:
            raise ep.ProtocolError('EXPLICIT_INITIALIZATION_AND_INTEGER_SEED_REQUIRED')
        if manifest.get('model_id') != 'RNA-FM' or manifest.get('dtype') != 'float32':
            raise ep.ProtocolError('RNAFM_FP32_MANIFEST_REQUIRED')
        self.manifest = copy.deepcopy(manifest)
        root, checkpoint = Path(manifest['source_root']).resolve(), Path(manifest['checkpoint']).resolve()
        card = Path(manifest['model_card']).resolve()
        if ep.sha256_file(checkpoint) != manifest['checkpoint_sha256']:
            raise ep.ProtocolError('CHECKPOINT_HASH_MISMATCH')
        if source_hash(root) != manifest['source_tree_sha256']:
            raise ep.ProtocolError('REVIEWED_SOURCE_HASH_MISMATCH')
        if ep.sha256_file(card) != manifest['model_card_sha256']:
            raise ep.ProtocolError('MODEL_CARD_HASH_MISMATCH')
        if manifest.get('rights_scope') != 'USER_AUTHORIZED_LOCAL_RESEARCH_NO_REDISTRIBUTION':
            raise ep.ProtocolError('EXPLICIT_LOCAL_CHECKPOINT_SCOPE_REQUIRED')
        if not card.read_text(encoding='utf-8').startswith('---\nlicense: apache-2.0\n---'):
            raise ep.ProtocolError('PINNED_MODEL_CARD_LICENSE_DECLARATION_MISMATCH')
        # Import only the pinned local package; never invoke its hub loader.
        if 'fm' in sys.modules and not Path(sys.modules['fm'].__file__).resolve().is_relative_to(root):
            raise ep.ProtocolError('OTHER_FM_PACKAGE_ALREADY_IMPORTED')
        # Upstream __init__ eagerly imports task heads requiring ptflops. Load
        # ONLY actual encoder submodules, not downstream heads or mock modules.
        # Neither original model code nor weights are edited or substituted.
        if 'fm' not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                'fm', root/'fm/__init__.py', submodule_search_locations=[str(root/'fm')])
            package = importlib.util.module_from_spec(spec)
            sys.modules['fm'] = package
            package.Alphabet = importlib.import_module('fm.data').Alphabet
            package.BioBertModel = importlib.import_module('fm.model.esm1').BioBertModel
            package.pretrained = importlib.import_module('fm.pretrained')
        fm = sys.modules['fm']
        # Legacy checkpoints contain argparse.Namespace; do not enable unrestricted pickle.
        with torch.serialization.safe_globals([argparse.Namespace]):
            data = torch.load(checkpoint, map_location='cpu', weights_only=True)
        if not isinstance(data, dict) or not {'args', 'model'}.issubset(data):
            raise ep.ProtocolError('UNEXPECTED_CHECKPOINT_CONTENTS')
        model, alphabet = fm.pretrained.load_model_and_alphabet_core('RNA-FM_pretrained', data, theme='rna')
        if initialization == 'random':
            torch.manual_seed(seed)
            model = type(model)(copy.deepcopy(model.args), alphabet)
        self.device, self.initialization, self.seed = device, initialization, seed
        self.model = model.to(device=device, dtype=torch.float32).eval()
        self.model.requires_grad_(False)
        self.alphabet = alphabet
        self.converter = alphabet.get_batch_converter()
        self.layer = int(self.model.args.layers)
        self.dimension = int(self.model.args.embed_dim)
        self.max_nt = int(self.model.args.max_positions) - int(alphabet.prepend_bos) - int(alphabet.append_eos)
        if self.max_nt != manifest['maximum_nt'] or alphabet.k_mer != 1:
            raise ep.ProtocolError('MANIFEST_MODEL_LENGTH_OR_KMER_MISMATCH')
        self.tokenizer_sha256 = ep.digest_json({'vocab': alphabet.all_toks,
            'bos': alphabet.prepend_bos, 'eos': alphabet.append_eos, 'kmer': alphabet.k_mer})
        self.contract = {'schema_version': 'rna_gym.rnafm_encoding.v1',
            'checkpoint_sha256': manifest['checkpoint_sha256'],
            'source_tree_sha256': manifest['source_tree_sha256'],
            'adapter_sha256': ep.sha256_file(Path(__file__)),
            'tokenizer_sha256': self.tokenizer_sha256, 'layer': self.layer,
            'pooling': 'VALID_NUCLEOTIDE_MEAN_EXCLUDING_BOS_EOS_PADDING',
            'sequence_transform': 'NONE', 'dtype': 'float32',
            'initialization': initialization, 'initialization_seed': seed,
            'maximum_nt': self.max_nt, 'length_policy': 'REJECT_NO_TRUNCATION',
            'torch_version': torch.__version__, 'cuda_version': torch.version.cuda,
            'gpu_name': torch.cuda.get_device_name(self.gpu), 'eval_mode': True}
        self.forward_seconds = 0.0
        self.forward_sequences = 0
        torch.cuda.reset_peak_memory_stats(self.gpu)

    def encode(self, records, *, batch_size=4):
        validate_records(records, self.max_nt)
        if type(batch_size) is not int or not 1 <= batch_size <= 16:
            raise ep.ProtocolError('BATCH_SIZE_OUTSIDE_BOUNDED_RANGE')
        torch = self.torch
        result = []
        for start in range(0, len(records), batch_size):
            batch = records[start:start+batch_size]
            _, strings, tokens = self.converter([(r['observation_id'], r['sequence']) for r in batch])
            offset = int(self.alphabet.prepend_bos)
            for i, row in enumerate(batch):
                seq = row['sequence']
                expected = [self.alphabet.get_idx(nt) for nt in seq]
                if strings[i] != seq or tokens[i, offset:offset+len(seq)].tolist() != expected:
                    raise ep.ProtocolError('NUCLEOTIDE_TOKEN_ALIGNMENT_FAILURE')
                if int(tokens[i].ne(self.alphabet.padding_idx).sum()) != len(seq)+offset+int(self.alphabet.append_eos):
                    raise ep.ProtocolError('SPECIAL_TOKEN_OR_LENGTH_MISMATCH')
            tokens = tokens.to(self.device)
            torch.cuda.synchronize(self.gpu)
            started = time.monotonic()
            with torch.inference_mode():
                output = self.model(tokens, repr_layers=[self.layer], return_contacts=False)
                representations = output['representations'][self.layer]
            torch.cuda.synchronize(self.gpu)
            self.forward_seconds += time.monotonic()-started
            self.forward_sequences += len(batch)
            if representations.device.type != 'cuda' or representations.requires_grad or self.model.training:
                raise ep.ProtocolError('FROZEN_GPU_INFERENCE_CONTRACT_VIOLATION')
            for i, row in enumerate(batch):
                nt = representations[i, offset:offset+len(row['sequence'])].float()
                if nt.shape != (len(row['sequence']), self.dimension) or not torch.isfinite(nt).all():
                    raise ep.ProtocolError('NONFINITE_OR_MISALIGNED_ENCODER_OUTPUT')
                result.append({'observation_id': row['observation_id'],
                    'nucleotide_embeddings': nt.cpu().numpy(),
                    'valid_position_mask': [True]*len(row['sequence']),
                    'token_to_nucleotide': [None]*offset + list(range(len(row['sequence']))) + [None]*int(self.alphabet.append_eos),
                    'pooled_embedding': nt.mean(dim=0).cpu().tolist(),
                    'sequence_sha256': ep.digest_json(row['sequence'])})
        return result

    def cache_key(self, sequence):
        return ep.digest_json({'contract': self.contract, 'sequence': sequence})

    def pooled(self, records, cache_dir, *, batch_size=4):
        validate_records(records, self.max_nt)
        cache = Path(cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
        found, missing = {}, {}
        hits = 0
        for row in records:
            key = self.cache_key(row['sequence'])
            path = cache / (key+'.json')
            if path.exists():
                if path.is_symlink():
                    raise ep.ProtocolError('CACHE_SYMLINK_REJECTED')
                item = ep.read_json(path)
                payload = {k: v for k, v in item.items() if k != 'payload_sha256'}
                if (item.get('payload_sha256') != ep.digest_json(payload) or
                        payload.get('cache_key') != key or payload.get('contract') != self.contract or
                        len(payload.get('pooled_embedding', [])) != self.dimension or
                        any(not ep._finite(v) for v in payload['pooled_embedding'])):
                    raise ep.ProtocolError('CACHE_INTEGRITY_FAILURE')
                found[key] = payload
                hits += 1
            else:
                missing.setdefault(key, row)
        if missing:
            for row, item in zip(missing.values(), self.encode(list(missing.values()), batch_size=batch_size)):
                key = self.cache_key(row['sequence'])
                payload = {'cache_key': key, 'contract': self.contract,
                    'pooled_embedding': item['pooled_embedding'],
                    'length_nt': len(row['sequence']), 'sequence_sha256': item['sequence_sha256']}
                ep.write_immutable(cache / (key+'.json'), {**payload, 'payload_sha256': ep.digest_json(payload)})
                found[key] = payload
        return ([{'observation_id': row['observation_id'], **found[self.cache_key(row['sequence'])]}
                 for row in records], {'cache_hits': hits, 'unique_cache_misses': len(missing),
                                       'observations_requested': len(records)})

    def resources(self):
        torch = self.torch
        return {'device': self.device, 'gpu_name': torch.cuda.get_device_name(self.gpu),
            'visible_gpu_count': torch.cuda.device_count(),
            'cuda_visible_devices': os.getenv('CUDA_VISIBLE_DEVICES'),
            'slurm_job_id': os.getenv('SLURM_JOB_ID'), 'cpu_fm_fallback': False,
            'forward_seconds': self.forward_seconds, 'forward_sequences_including_checks': self.forward_sequences,
            'peak_cuda_allocated_bytes': torch.cuda.max_memory_allocated(self.gpu),
            'peak_cuda_reserved_bytes': torch.cuda.max_memory_reserved(self.gpu),
            'process_max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}


def smoke(manifest, out, *, device='cuda:0', initialization='pretrained', seed=0):
    """Real encoder checks on synthetic unlabeled RNA, never a real assay run."""
    import numpy as np
    out = Path(out)
    if out.exists():
        raise ep.ProtocolError('DIAGNOSTIC_OUTPUT_MUST_BE_NEW')
    out.mkdir(parents=True)
    started = time.monotonic()
    adapter = RNAFMAdapter(manifest, device=device, initialization=initialization, seed=seed)
    records = [{'observation_id': 'DIAGNOSTIC_'+str(i), 'sequence': seq}
               for i, seq in enumerate(('ACGU', 'ACGUACGUACGU', 'G'*31+'UAC', 'A'))]
    batched = adapter.encode(records, batch_size=4)
    single = adapter.encode(records, batch_size=1)
    repeat = adapter.encode(records, batch_size=4)
    max_delta = max(float(np.max(np.abs(a['nucleotide_embeddings']-b['nucleotide_embeddings'])))
                    for a, b in zip(batched, single))
    repeated_delta = max(float(np.max(np.abs(a['nucleotide_embeddings']-b['nucleotide_embeddings'])))
                         for a, b in zip(batched, repeat))
    for a, b in zip(batched, single):
        np.testing.assert_allclose(a['nucleotide_embeddings'], b['nucleotide_embeddings'], rtol=1e-4, atol=2e-5)
    for a, b in zip(batched, repeat):
        np.testing.assert_allclose(a['nucleotide_embeddings'], b['nucleotide_embeddings'], rtol=1e-5, atol=1e-6)
    _, cold = adapter.pooled(records, out/'cache')
    cached, warm = adapter.pooled(records, out/'cache')
    if warm['cache_hits'] != len(records) or warm['unique_cache_misses']:
        raise ep.ProtocolError('CACHE_REPLAY_FAILED')
    boundary = [{'observation_id': 'DIAGNOSTIC_BOUNDARY', 'sequence': ('ACGU'*((adapter.max_nt+3)//4))[:adapter.max_nt]}]
    adapter.encode(boundary, batch_size=1)
    rejected = []
    for name, seq in [('overlength', 'A'*(adapter.max_nt+1)), ('dna', 'ACGT'), ('empty', '')]:
        try:
            adapter.encode([{'observation_id': 'REJECT', 'sequence': seq}])
        except ep.ProtocolError as error:
            rejected.append({'case': name, 'reason': str(error)})
        else:
            raise ep.ProtocolError('INVALID_INPUT_WAS_ACCEPTED:'+name)
    report = {'schema_version': 'rna_gym.adapter_diagnostic.v1', 'status': 'EXECUTED',
        'scope': 'UNLABELED_SYNTHETIC_INPUT_REAL_FM_GPU_DIAGNOSTIC', 'model_id': 'RNA-FM',
        'real_checkpoint_loaded': True, 'real_assay_evaluation': False, 'rankable_real_result': False,
        'contract': adapter.contract, 'resources': adapter.resources(),
        'n_diagnostic_sequences': len(records)+1, 'functional_labels_used': 0,
        'maximum_tested_nt': adapter.max_nt, 'maximum_batch_tested': 4,
        'batch_single_max_abs_delta': max_delta, 'repeat_max_abs_delta': repeated_delta,
        'cache_cold': cold, 'cache_warm': warm, 'invalid_inputs_rejected': rejected,
        'checks': {'completed': 8, 'failed': 0, 'attempted': 8},
        'wall_seconds': time.monotonic()-started,
        'native_functional_score': 'NOT_IMPLEMENTED_NO_SEMANTIC_SUBSTITUTION',
        'pair_prediction': 'NOT_APPLICABLE_TO_POOLED_REPRESENTATION_INTERFACE',
        'pretraining_overlap': 'NOT_ESTABLISHED_BY_THIS_DIAGNOSTIC'}
    ep.write_immutable(out/'pooled_representations.json', cached)
    ep.write_immutable(out/'diagnostic.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--device', default='cuda:0')
    parser.add_argument('--initialization', choices=('pretrained', 'random'), default='pretrained')
    parser.add_argument('--seed', type=int, default=0)
    args = parser.parse_args(argv)
    existed = args.out.exists()
    try:
        report = smoke(ep.read_json(args.manifest), args.out, device=args.device,
                       initialization=args.initialization, seed=args.seed)
    except (ep.ProtocolError, OSError, ValueError, AssertionError, RuntimeError, ImportError) as error:
        failure = {'status': 'FAILED', 'reason': str(error), 'exception_type': type(error).__name__,
                   'rankable_real_result': False, 'scope': 'ADAPTER_DIAGNOSTIC_ONLY'}
        # A failed attempt is evidence; never overwrite a prior successful report.
        failure_path = args.out/'failure.json'
        if not existed and not failure_path.exists():
            ep.write_immutable(failure_path, failure)
        print(json.dumps(failure), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
