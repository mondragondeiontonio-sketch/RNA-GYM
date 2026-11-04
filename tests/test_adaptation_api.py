"""CPU-only contracts for bounded GPU workflow orchestration and metric replay."""
import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rna_gym import AdaptationPilot, RNAHub
from rna_gym.budget import BudgetDenied
from rna_gym.workflows import _allocated_idle_gpu, _sha

ROOT = Path(__file__).resolve().parents[1]


class GPUSelectionTests(unittest.TestCase):
    inventory = '0, GPU-busy, 330, 70\n1, GPU-idle, 4, 0\n'

    def select(self, **kwargs):
        args = dict(visible='0,1', step='0,1', gpu_uuid='GPU-idle')
        args.update(kwargs)
        return _allocated_idle_gpu(self.inventory, 'GPU-busy, 123', **args)

    def test_only_idle_allocated_device_selected(self):
        self.assertEqual(self.select()['physical_index'], '1')

    def test_busy_gpu_not_used_even_if_allocated(self):
        with self.assertRaisesRegex(ValueError, 'EXISTING_COMPUTE_PROCESS'):
            self.select(gpu_uuid='GPU-busy')

    def test_both_step_and_visible_allocation_required(self):
        for kw in ({'step': '0'}, {'visible': '0'}, {'step': ''}):
            with self.subTest(kw=kw), self.assertRaisesRegex(ValueError, 'OUTSIDE_CURRENT'):
                self.select(**kw)

    def test_unknown_uuid_rejected(self):
        with self.assertRaisesRegex(ValueError, 'NOT_UNIQUELY_VISIBLE'):
            self.select(gpu_uuid='GPU-other')

    def test_utilization_or_memory_without_process_still_rejected(self):
        for row in ('1, GPU-idle, 129, 0', '1, GPU-idle, 4, 10'):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, 'NOT_IDLE'):
                _allocated_idle_gpu(row, '', visible='1', step='1', gpu_uuid='GPU-idle')


class PilotAPIContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'configs').mkdir()
        (self.root / 'configs/model_adapter_registry.yaml').write_text('{}')
        self.ref = self.root / 'runs/reference'; self.ref.mkdir(parents=True)
        self.rows = [dict(record_id=str(i), role=role, label=float(i))
                     for role, ids in [('validation', range(3)), ('test', range(3, 6))]
                     for i in ids]
        (self.ref / 'fixed_recipe.json').write_text(json.dumps(dict(dataset='contract_only',
            parent_split='unchanged', subset_counts={'train':64,'validation':16,'test':32})))
        (self.ref / 'subset.json').write_text(json.dumps(self.rows))
        evidence = self.root / 'runs/authorization.json'; evidence.write_text('{}')
        self.spec = dict(workflow='fixed_adaptation_pilot',mode='lora',gpu_seconds=180,
            attempts=1, parallel=1, ledger='runs/budget.sqlite',
            authorization_evidence='runs/authorization.json',
            authorization_evidence_sha256=_sha(evidence),
            reference_sha256={f:_sha(self.ref/f) for f in ('fixed_recipe.json','subset.json')})
        self.write_policy()
        self.pilot = AdaptationPilot(output='runs/new', root=self.root,
                                     reference_work='runs/reference')

    def write_policy(self):
        (self.root/'configs/compute_budget_policy_v1.json').write_text(
            json.dumps({'authorized_scopes': {'approved':self.spec}}))

    def test_missing_reference_fails_closed_with_actionable_error(self):
        pilot=AdaptationPilot(output='runs/new', root=self.root, reference_work='runs/missing')
        with self.assertRaisesRegex(ValueError, 'REFERENCE_NOT_SHIPPED'):
            pilot.inspect()

    def test_inspect_never_starts_gpu_or_creates_output(self):
        info = self.pilot.inspect()
        self.assertFalse(info['scientific_admitted'])
        self.assertFalse(info['formal_leaderboard_eligible'])
        self.assertFalse(info['gpu_execution_started'])
        self.assertFalse(self.pilot.output.exists())

    def test_unapproved_scope_refused_before_resources_or_ledger(self):
        with patch('rna_gym.workflows.subprocess.check_output') as command:
            with self.assertRaisesRegex(BudgetDenied, 'NOT_AUTHORIZED'):
                self.pilot.run(scope='unapproved',gpu_uuid='GPU-idle')
            command.assert_not_called()
        self.assertFalse((self.root/'runs/budget.sqlite').exists())

    def test_cap_and_mode_mismatch_fail_closed(self):
        with self.assertRaisesRegex(BudgetDenied, 'LIMITS_EXCEEDED'):
            self.pilot._approved_spec('approved',181)
        self.spec['mode']='full_ft';self.write_policy()
        with self.assertRaisesRegex(BudgetDenied, 'MODE_MISMATCH'):
            self.pilot._approved_spec('approved',180)

    def test_bad_seconds_rejected(self):
        for n in (0,-1,True,float('inf'),float('nan')):
            with self.subTest(n=n), self.assertRaises(ValueError):
                self.pilot._approved_spec('approved',n)

    def test_modified_recipe_and_authorization_rejected(self):
        (self.ref/'subset.json').write_text('[]')
        with self.assertRaisesRegex(BudgetDenied,'RECIPE_OR_SUBSET_MISMATCH'):
            self.pilot._approved_spec('approved',180)
        (self.root/'runs/authorization.json').write_text('{"changed":true}')
        with self.assertRaisesRegex(BudgetDenied,'EVIDENCE_HASH_MISMATCH'):
            self.pilot._approved_spec('approved',180)

    def test_paths_and_modes_are_bounded(self):
        for path in ('../outside','runs/../../outside','configs/output','runs'):
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,'INSIDE_CHECKOUT_RUNS'):
                AdaptationPilot(output=path,root=self.root)
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED'):
            AdaptationPilot(mode='arbitrary-command',output='runs/new',root=self.root)

    def test_scores_replay_and_tampering_rejected(self):
        try:
            from tools.adaptation_smoke_v1 import metrics
        except ImportError:
            self.skipTest('optional scientific dependencies unavailable')
        folder=self.pilot.output/'lora';folder.mkdir(parents=True)
        engine={'mode':'lora','recipe_sha256':_sha(self.ref/'fixed_recipe.json'),'metrics':{}}
        for role in ('validation','test'):
            rows=[r for r in self.rows if r['role']==role]
            with (folder/(role+'_predictions.tsv')).open('w') as f:
                writer=csv.DictWriter(f,fieldnames=['record_id','label','prediction'],delimiter='\t',extrasaction='ignore')
                writer.writeheader();writer.writerows(dict(r,prediction=r['label']+0.5) for r in rows)
            engine['metrics'][role]=metrics([r['label'] for r in rows],[r['label']+0.5 for r in rows])
        self.assertEqual(self.pilot._replay_scores(engine)['test']['status'],'PASS')
        engine['metrics']['test']['RMSE']=100
        with self.assertRaisesRegex(ValueError,'METRIC_REPLAY_MISMATCH'):
            self.pilot._replay_scores(engine)


class HFDeploymentAliasTests(unittest.TestCase):
    def test_alias_resolves_without_bypassing_budget(self):
        with patch.dict(os.environ,{},clear=True),patch('tools.rnafm_adapter.RNAFMAdapter') as adapter:
            with self.assertRaises(BudgetDenied):RNAHub.load('RNA-FM-HF',root=ROOT)
            adapter.assert_not_called()

    def test_alias_loads_same_pinned_native_backend(self):
        manifest=ROOT/'runs/20261027_gpu_continuation/model_manifest.json'
        if not manifest.is_file():self.skipTest('local private model manifest not shipped')
        with patch('rna_gym.compute_guard.require_compute_lease'),patch('tools.rnafm_adapter.RNAFMAdapter') as adapter:
            model=RNAHub.load('RNA-FM-HF',root=ROOT)
            self.assertEqual(model.model_id,'RNA-FM')
            self.assertEqual(model.deployment,'RNA-FM-HF')
            self.assertEqual(adapter.call_args.args[0]['checkpoint_sha256'],json.loads(manifest.read_text())['checkpoint_sha256'])
