"""Public SDK usability regressions; no FM forward or assay scores are mocked."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from rna_gym import BenchmarkResults, RNABenchmark, RNAHub

ROOT = Path(__file__).resolve().parents[1]


class ResultStatusTests(unittest.TestCase):
    def test_execution_failure_is_not_scientific_blocking(self):
        for statuses in [('FAILED',), ('FAILED', 'FAILED'),
                         ('FAILED', 'BLOCKED'), ('NOT_APPLICABLE', 'FAILED')]:
            with self.subTest(statuses=statuses):
                result = BenchmarkResults([{'status': state} for state in statuses])
                self.assertEqual(result.status, 'FAILED')
                self.assertEqual(result.as_dict()['status'], 'FAILED')

    def test_existing_success_blocking_and_na_semantics_remain(self):
        for statuses, expected in [([], 'BLOCKED'), (['EXECUTED'], 'EXECUTED'),
                                   (['BLOCKED'], 'BLOCKED'),
                                   (['NOT_APPLICABLE'], 'NOT_APPLICABLE'),
                                   (['BLOCKED', 'NOT_APPLICABLE'], 'BLOCKED'),
                                   (['EXECUTED', 'FAILED'], 'PARTIAL'),
                                   (['EXECUTED', 'BLOCKED'], 'PARTIAL')]:
            with self.subTest(statuses=statuses):
                result = BenchmarkResults([{'status': state} for state in statuses])
                self.assertEqual(result.status, expected)
                self.assertFalse(result.as_dict()['formal_leaderboard_eligible'])

    def test_saved_failure_keeps_its_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'failure_summary.json'
            BenchmarkResults([{'status': 'FAILED'}]).save(path)
            self.assertEqual(json.loads(path.read_text())['status'], 'FAILED')


class CheckoutFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'checkout'
        for name in ['configs/native_sdk.json', 'configs/model_adapter_registry.yaml',
                     'data/registries/dataset_catalog.json']:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)


class OutputDirectoryTests(CheckoutFixture):
    def runner(self, output):
        return RNABenchmark(dataset='T0021', root=self.root, output=output)

    def test_relative_output_is_checkout_relative_not_cwd_relative(self):
        self.assertEqual(self.runner('runs/pilot').output, self.root / 'runs/pilot')

    def test_absolute_output_inside_ignored_runs_is_accepted(self):
        path = self.root / 'runs/pilot'
        self.assertEqual(self.runner(path).output, path)

    def test_external_output_is_rejected_before_execution(self):
        with self.assertRaisesRegex(ValueError, 'OUTPUT_MUST_BE_INSIDE_CHECKOUT_RUNS'):
            self.runner(Path(self.temp.name) / 'public_results')

    def test_traversal_and_tracked_directories_are_rejected(self):
        for path in ['runs/../../outside', 'data/predictions', 'site/results', '']:
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, 'OUTPUT_MUST_BE_INSIDE_CHECKOUT_RUNS'):
                    self.runner(path)

    def test_symlink_escape_is_rejected(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        runs = self.root / 'runs'
        runs.mkdir()
        (runs / 'escape').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'OUTPUT_MUST_BE_INSIDE_CHECKOUT_RUNS'):
            self.runner('runs/escape/pilot')

    def test_default_output_remains_lazy_and_local(self):
        self.assertIsNone(self.runner(None).output)
        self.assertFalse((self.root / 'runs').exists())


class ManifestResolutionTests(CheckoutFixture):
    def assert_manifest_reaches_adapter(self, manifest, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {'routing_test_only': True}
        path.write_text(json.dumps(data))
        # Stop at the adapter constructor: this tests path routing, never
        # substitutes a fake encoder or claims successful model inference.
        with patch('tools.rnafm_adapter.RNAFMAdapter',
                   side_effect=RuntimeError('PATH_REACHED_ADAPTER')) as adapter:
            with self.assertRaisesRegex(RuntimeError, 'PATH_REACHED_ADAPTER'):
                RNAHub.load('RNA-FM', root=self.root, manifest=manifest)
        adapter.assert_called_once_with(data, device='cuda:0',
                                        initialization='pretrained', seed=0)

    def test_relative_manifest_uses_explicit_checkout_root(self):
        self.assert_manifest_reaches_adapter('runs/pinned.json',
                                             self.root / 'runs/pinned.json')

    def test_absolute_manifest_is_preserved(self):
        path = Path(self.temp.name) / 'external/pinned.json'
        self.assert_manifest_reaches_adapter(path, path)

    def test_default_pinned_manifest_is_preserved(self):
        config = json.loads((self.root / 'configs/native_sdk.json').read_text())
        self.assert_manifest_reaches_adapter(None, self.root / config['model_manifest'])


class PublicEntryPointTests(unittest.TestCase):
    def test_sdk_only_changes_trigger_push_and_pr_verification(self):
        workflow = (ROOT / '.github/workflows/pages.yml').read_text()
        for path in ['rna_gym/**', 'pyproject.toml', 'configs/**']:
            with self.subTest(path=path):
                self.assertEqual(workflow.count("      - '" + path + "'"), 2)

    def test_readme_python_examples_parse_without_placeholder_syntax(self):
        import ast
        import re
        blocks = re.findall(r'```python\n(.*?)```',
                            (ROOT / 'README.md').read_text(), re.S)
        self.assertGreaterEqual(len(blocks), 2)
        for block in blocks:
            ast.parse(block)


if __name__ == '__main__':
    unittest.main()
