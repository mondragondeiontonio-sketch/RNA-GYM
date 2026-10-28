"""CPU contract tests only; no real FM inference, weights, downloads or GPU."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import evaluation_protocol as ep
import rnafm_adapter as adapter
import frozen_pilot as pilot

ROOT = Path(__file__).resolve().parents[1]


class AdapterContractTests(unittest.TestCase):
    def test_exact_alphabet_and_no_silent_truncation(self):
        adapter.validate_records([{'observation_id':'a', 'sequence':'ACGU'}], 4)
        for seq in ('', 'ACGT', 'acgu', 'ACGUN', 'A'*5):
            with self.assertRaises(ep.ProtocolError):
                adapter.validate_records([{'observation_id':'a', 'sequence':seq}], 4)

    def test_duplicate_or_missing_ids_rejected(self):
        for records in ([], [{'sequence':'A'}], [{'observation_id':'a', 'sequence':'A'}]*2):
            with self.assertRaises(ep.ProtocolError):
                adapter.validate_records(records, 4)

    def test_gpu_only_and_respects_visible_allocation(self):
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True, device_count=lambda:1))
        self.assertEqual(adapter.validate_device('cuda:0', torch), 0)
        for device in ('cpu', 'cuda', 'cuda:1', 'cuda:-1'):
            with self.assertRaises(ep.ProtocolError):
                adapter.validate_device(device, torch)
        torch.cuda.is_available = lambda:False
        with self.assertRaises(ep.ProtocolError):
            adapter.validate_device('cuda:0', torch)

    def test_cache_identity_covers_model_tokenizer_pooling_initialization(self):
        instance = adapter.RNAFMAdapter.__new__(adapter.RNAFMAdapter)
        instance.contract = {key:'original' for key in ('checkpoint_sha256', 'tokenizer_sha256', 'pooling', 'initialization', 'initialization_seed', 'layer', 'dtype', 'adapter_sha256')}
        key = instance.cache_key('ACGU')
        self.assertNotEqual(key, instance.cache_key('ACGA'))
        for field in instance.contract:
            old = instance.contract[field]
            instance.contract[field] = 'changed'
            self.assertNotEqual(key, instance.cache_key('ACGU'), field)
            instance.contract[field] = old

    def test_cache_corruption_fails_closed_without_model_forward(self):
        instance = adapter.RNAFMAdapter.__new__(adapter.RNAFMAdapter)
        instance.contract, instance.max_nt, instance.dimension = {'synthetic_cache_contract':True}, 4, 2
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)/(instance.cache_key('ACGU')+'.json')
            p.write_text(json.dumps({'cache_key':instance.cache_key('ACGU'), 'contract':instance.contract,
                                     'pooled_embedding':[0.0, 1.0], 'payload_sha256':'invalid'}))
            with self.assertRaisesRegex(ep.ProtocolError, 'CACHE_INTEGRITY'):
                instance.pooled([{'observation_id':'a', 'sequence':'ACGU'}], Path(temp))

    def test_current_candidate_is_gated_before_reading_labels_or_loading_fm(self):
        config = ep.read_json(ROOT/'configs/rnafm_frozen_pilot.json')
        with tempfile.TemporaryDirectory() as temp, patch.object(pilot, 'RNAFMAdapter') as fm:
            out = Path(temp)/'not_created'
            with self.assertRaisesRegex(ep.ProtocolError, 'REAL_TASK_DISABLED_PENDING_ADMISSION'):
                pilot.run_pilot(config, Path(temp)/'missing_labels', Path(temp)/'missing_split', {}, out)
            fm.assert_not_called()
            self.assertFalse(out.exists())

    def test_legacy_plan_exposes_bounded_adapter_without_running_it(self):
        result = ep.adapter_plan('RNA-FM', 'frozen_ridge')
        self.assertEqual(result['reason'], 'BLOCKED_LOADABILITY')
        self.assertFalse(result['weights_loaded'])
        self.assertEqual(result['bounded_local_adapter']['implementation'], 'tools/rnafm_adapter.py')
        self.assertTrue(result['bounded_local_adapter']['existing_admission_gate_required'])

    def test_resource_caps_fail_rather_than_shrink_protocol(self):
        import time
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            with self.assertRaisesRegex(ep.ProtocolError, 'WALL_BUDGET_EXCEEDED'):
                pilot.check_caps(out, time.monotonic()-2, {'max_wall_seconds':1, 'max_output_bytes':100})
            (out/'bytes').write_bytes(b'x'*101)
            with self.assertRaisesRegex(ep.ProtocolError, 'DISK_BUDGET_EXCEEDED'):
                pilot.check_caps(out, time.monotonic(), {'max_wall_seconds':1, 'max_output_bytes':100})

    def test_real_runner_rejects_synthetic_substitution(self):
        config = ep.read_json(ROOT/'configs/rnafm_frozen_pilot.json')
        config['task']['synthetic'] = True
        with self.assertRaisesRegex(ep.ProtocolError, 'NO_SYNTHETIC_SUBSTITUTION'):
            pilot.prepare_pilot(config, Path('unused'), Path('unused'))


@unittest.skipUnless(ep.importlib.util.find_spec('sklearn'), 'optional sklearn absent')
class FrozenHeadTests(unittest.TestCase):
    def fixture(self):
        return ([[0, 1], [1, 3], [2, 2], [99, 200], [-200, 100]],
                [{'observation_id':str(i), 'label':float(i+1)} for i in range(5)],
                {str(i):'train' if i < 3 else ('validation' if i == 3 else 'test') for i in range(5)})

    def test_heldout_label_permutation_and_features_do_not_change_fit(self):
        features, rows, splits = self.fixture()
        got = pilot.fit_head(features, rows, splits, ['0', '1', '2'])
        other = copy.deepcopy(rows)
        other[3]['label'], other[4]['label'] = -1e9, 1e9
        other_features = copy.deepcopy(features)
        other_features[3], other_features[4] = [1e10, -1e10], [-1e11, 1e11]
        self.assertEqual(got, pilot.fit_head(other_features, other, splits, ['0', '1', '2']))
        self.assertEqual(got['total_unique_target_labels'], 3)
        self.assertEqual(got['tune_labels'], 0)
        self.assertEqual(got['calibration_labels'], 0)
        self.assertEqual(got['test_selection_labels'], 0)

    def test_budget_never_selects_validation_or_test(self):
        features, rows, splits = self.fixture()
        for ids in (['0', '3'], ['0', '4'], ['0', '0'], []):
            with self.assertRaises(ep.ProtocolError):
                pilot.fit_head(features, rows, splits, ids)

    def test_predictions_are_raw_units_with_constant_target_safe(self):
        features, rows, splits = self.fixture()
        for row in rows[:3]:
            row['label'] = 17.0
        head = pilot.fit_head(features, rows, splits, ['0', '1', '2'])
        self.assertEqual(pilot.predict_head(head, features), [17.0]*5)


class FrozenArtifactSerializationTests(unittest.TestCase):
    def test_nested_cell_directories_are_created_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temp:
            cell = Path(temp)/'seed_11'/'mean_null'
            head = {'scope':'SYNTHETIC_SERIALIZATION_CONTRACT_ONLY'}
            predictions = [{'observation_id':'synthetic','prediction':0.25}]
            metrics = {'scope':'SYNTHETIC_SERIALIZATION_CONTRACT_ONLY','rankable_real_result':False}
            pilot.persist_cell(cell, head, predictions, metrics)
            self.assertEqual(ep.read_json(cell/'head.json'),head)
            self.assertEqual(ep.read_json(cell/'predictions.json'),predictions)
            self.assertEqual(ep.read_json(cell/'metrics.json'),metrics)
            with self.assertRaises(FileExistsError):
                pilot.persist_cell(cell, head, predictions, metrics)
            self.assertEqual(ep.read_json(cell/'predictions.json'),predictions)


if __name__ == '__main__':
    unittest.main()
