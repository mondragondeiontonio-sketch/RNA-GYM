"""Bounded exploratory adaptation; never bypasses formal benchmark admission."""
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess

from ._paths import project_root
from .benchmarks import BenchmarkResults
from .budget import BudgetDenied, BudgetLedger


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _allocated_idle_gpu(inventory, processes, *, visible, step, gpu_uuid):
    """Validate both allocation membership and idleness; no CUDA initialization."""
    rows = [list(map(str.strip, row.split(','))) for row in inventory.splitlines() if row.strip()]
    matches = [r for r in rows if len(r) == 4 and r[1] == gpu_uuid]
    if len(matches) != 1:
        raise ValueError('GPU_UUID_NOT_UNIQUELY_VISIBLE')
    row = matches[0]
    visible, step = set(visible.split(',')), set(step.split(','))
    if not ({row[0], row[1]} & visible) or not ({row[0], row[1]} & step):
        raise ValueError('GPU_OUTSIDE_CURRENT_SLURM_ALLOCATION')
    if any(line.split(',')[0].strip() == gpu_uuid for line in processes.splitlines()):
        raise ValueError('GPU_HAS_EXISTING_COMPUTE_PROCESS')
    if float(row[2]) > 128 or float(row[3]) >= 10:
        raise ValueError('GPU_NOT_IDLE_NO_INTERFERENCE_ALLOWED')
    return {'physical_gpu_uuid': gpu_uuid, 'physical_index': row[0],
            'memory_used_mib_before': float(row[2]), 'utilization_before': float(row[3])}


class AdaptationPilot:
    """Run the existing 64/16/32 fixed recipe, not arbitrary/formal datasets.

    The caller must already have a separately authorized persistent scope. This
    API never approves budgets, scientific admission, retries, or new splits.
    """
    def __init__(self, *, mode='lora', output, root=None,
                 reference_work='runs/20261102_taxonomy_admission_adaptation_v1/adaptation'):
        if mode not in ('scratch', 'lora', 'full_ft'):
            raise ValueError('UNSUPPORTED_ADAPTATION_MODE')
        self.root, self.mode = project_root(root), mode
        self.output = self._local_runs_path(output)
        self.reference = self._local_runs_path(reference_work)

    def _local_runs_path(self, value):
        path = (self.root / Path(value).expanduser()).resolve()
        if not path.is_relative_to(self.root / 'runs') or path == self.root / 'runs':
            raise ValueError('PATH_MUST_REMAIN_INSIDE_CHECKOUT_RUNS')
        return path

    def _reference_file(self, name):
        path = self.reference / name
        if not path.is_file():
            raise ValueError('ADAPTATION_REFERENCE_NOT_SHIPPED:' + name)
        return path

    def inspect(self):
        recipe = json.loads(self._reference_file('fixed_recipe.json').read_text())
        return {'mode': self.mode, 'requested_model': 'RNA-FM-HF',
                'dataset': recipe['dataset'], 'parent_split': recipe['parent_split'],
                'subset_counts': recipe['subset_counts'], 'label_definition': 'original kcat, s^-1',
                'phase': 'EXPLORATORY_ADAPTATION_PILOT', 'scientific_admitted': False,
                'formal_leaderboard_eligible': False, 'frozen_reencoding': False,
                'output': str(self.output), 'gpu_execution_started': False}

    def _approved_spec(self, scope, seconds):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('FINITE_POSITIVE_RESERVATION_REQUIRED')
        policy = json.loads((self.root / 'configs/compute_budget_policy_v1.json').read_text())
        spec = policy.get('authorized_scopes', {}).get(scope)
        if spec is None:
            raise BudgetDenied('COMPUTE_SCOPE_NOT_AUTHORIZED')
        if spec.get('workflow') != 'fixed_adaptation_pilot' or spec.get('mode') != self.mode:
            raise BudgetDenied('SCOPE_WORKFLOW_OR_MODE_MISMATCH')
        if seconds > spec['gpu_seconds'] or spec['parallel'] != 1:
            raise BudgetDenied('APPROVED_SCOPE_LIMITS_EXCEEDED')
        evidence = self.root / spec['authorization_evidence']
        if _sha(evidence) != spec['authorization_evidence_sha256']:
            raise BudgetDenied('AUTHORIZATION_EVIDENCE_HASH_MISMATCH')
        for name in ('fixed_recipe.json', 'subset.json'):
            if _sha(self._reference_file(name)) != spec['reference_sha256'][name]:
                raise BudgetDenied('APPROVED_RECIPE_OR_SUBSET_MISMATCH')
        ledger = self._local_runs_path(spec['ledger'])
        return spec, ledger

    def run(self, *, scope, gpu_uuid, seconds=180):
        spec, ledger_path = self._approved_spec(scope, seconds)
        # Validate the private fixed recipe before touching Slurm/GPU state.
        self._reference_file('fixed_recipe.json')
        self._reference_file('subset.json')
        if self.root != Path(__file__).resolve().parents[1]:
            raise ValueError('EXECUTION_REQUIRES_THIS_CHECKOUT_ROOT')
        if self.output.exists():
            raise FileExistsError('OUTPUT_ALREADY_EXISTS_USE_A_NEW_VERSION')
        if not os.environ.get('SLURM_JOB_ID'):
            raise ValueError('CURRENT_SLURM_ALLOCATION_REQUIRED')
        inventory = subprocess.check_output(['nvidia-smi',
            '--query-gpu=index,uuid,memory.used,utilization.gpu',
            '--format=csv,noheader,nounits'], text=True)
        processes = subprocess.check_output(['nvidia-smi',
            '--query-compute-apps=gpu_uuid,pid', '--format=csv,noheader'], text=True)
        gpu = _allocated_idle_gpu(inventory, processes,
            visible=os.environ.get('CUDA_VISIBLE_DEVICES', ''),
            step=os.environ.get('SLURM_STEP_GPUS', ''), gpu_uuid=gpu_uuid)
        environment = json.loads((self.root / 'runs/20261027_gpu_continuation/environment_gpu.json').read_text())
        executable = Path(environment['executable'])
        if not executable.is_file():
            raise FileNotFoundError('VERIFIED_LOCAL_GPU_PYTHON_MISSING_NO_INSTALL')
        self.output.mkdir(parents=True, exist_ok=False)
        ledger = BudgetLedger(ledger_path, scope, gpu_seconds=spec['gpu_seconds'],
                              attempts=spec['attempts'], parallel=spec['parallel'])
        command = [str(executable), '-m', 'tools.adaptation_smoke_v1', self.mode,
                   '--output', str(self.output), '--reference-work', str(self.reference)]
        env = dict(os.environ, CUDA_VISIBLE_DEVICES=gpu_uuid, OMP_NUM_THREADS='4',
                   OPENBLAS_NUM_THREADS='1')
        base = {**self.inspect(), 'gpu_execution_started': True, 'scope': scope,
                'gpu': gpu, 'model_id': 'RNA-FM', 'deployment': 'RNA-FM-HF',
                'formal_leaderboard_eligible': False, 'metrics': None}
        try:
            rc = ledger.run_supervised(command, seconds=seconds,
                log_path=self.output / 'worker.log', cwd=self.root, env=env)
            if rc:
                raise RuntimeError('SUPERVISED_WORKER_FAILED_EXIT_' + str(rc))
            engine = json.loads((self.output / self.mode / 'result.json').read_text())
            replay = self._replay_scores(engine)
            result = {**base, 'status': 'EXECUTED', 'reason_codes': [],
                      'metrics': engine['metrics'], 'score_replay': replay,
                      'resources': {k: engine[k] for k in ('train_gpu_wall_seconds',
                          'training_sequences_per_second', 'total_gpu_process_seconds',
                          'peak_allocated_bytes', 'peak_reserved_bytes')},
                      'trainable_parameters': engine['trainable_parameters'],
                      'model_contract': engine['model_contract']}
        except Exception as exc:
            result = {**base, 'status': 'FAILED',
                      'reason_codes': [type(exc).__name__ + ':' + str(exc)]}
        result['budget'] = ledger.snapshot()
        results = BenchmarkResults([result])
        results.save(self.output / 'api_result.json')
        return results

    def _replay_scores(self, engine):
        from tools.adaptation_smoke_v1 import metrics
        if engine['mode'] != self.mode or engine['recipe_sha256'] != _sha(self.reference / 'fixed_recipe.json'):
            raise ValueError('WORKER_RESULT_IDENTITY_MISMATCH')
        rows = json.loads((self.reference / 'subset.json').read_text())
        replay = {}
        for role in ('validation', 'test'):
            path = self.output / self.mode / (role + '_predictions.tsv')
            with path.open() as stream:
                predictions = list(csv.DictReader(stream, delimiter='\t'))
            expected = [r for r in rows if r['role'] == role]
            if [r['record_id'] for r in predictions] != [r['record_id'] for r in expected]:
                raise ValueError('PREDICTION_RECORD_OR_SPLIT_MISMATCH')
            if [float(r['label']) for r in predictions] != [r['label'] for r in expected]:
                raise ValueError('PREDICTION_LABEL_MUTATION')
            actual = metrics([float(r['label']) for r in predictions],
                             [float(r['prediction']) for r in predictions])
            for key, value in actual.items():
                saved = engine['metrics'][role][key]
                if not (value is None and saved is None) and not (
                    value is not None and saved is not None and math.isfinite(value)
                    and math.isclose(value, saved, rel_tol=1e-9, abs_tol=1e-12)):
                    raise ValueError('SAVED_METRIC_REPLAY_MISMATCH_' + role + '_' + key)
            replay[role] = {'n': len(predictions), 'prediction_sha256': _sha(path),
                            'status': 'PASS', 'metrics': actual}
        return replay
