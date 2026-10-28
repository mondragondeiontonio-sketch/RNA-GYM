"""W02 file-version identities: synthetic bytes only, no assay approvals."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.build_dataset_catalog import build
from rna_gym import DatasetHub, DatasetResolutionError

ROOT = Path(__file__).resolve().parents[1]


class AssetVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('data/registries/task_baselines_and_admission_198.csv',
                     'data/audit/task_master.tsv', 'configs/full_qc_schemas.json',
                     'configs/native_sdk.json', 'configs/model_adapter_registry.yaml'):
            dest = self.root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, dest)
        self.config = json.loads((self.root / 'configs/native_sdk.json').read_text())
        self.config['private_assets_manifest'] = 'runs/private.json'
        (self.root / 'configs/native_sdk.json').write_text(json.dumps(self.config))

    def source(self, folder, text, asset_id='VERSION_TEST'):
        parent = self.root / 'raw_cache' / folder
        parent.mkdir(parents=True)
        raw = parent / 'same.csv'
        raw.write_text(text)
        digest = hashlib.sha256(raw.read_bytes()).hexdigest()
        (parent / 'provenance.json').write_text(json.dumps({
            'asset_id': asset_id, 'package_group_id': 'MRNA_MRL_SUGIMOTO',
            'raw_filename': raw.name, 'bytes': raw.stat().st_size, 'sha256': digest}))
        return digest

    def hub(self):
        catalog, private = build(self.root)
        path = self.root / 'data/registries/dataset_catalog.json'
        path.write_text(json.dumps(catalog))
        path = self.root / self.config['private_assets_manifest']
        path.parent.mkdir(parents=True, exist_ok=True)
        # The reader also accepts old manifests whose assets dictionary is
        # keyed by an explicit version, so old callers remain usable.
        path.write_text(json.dumps({'assets': private}))
        return catalog, private, DatasetHub(root=self.root)

    def test_two_different_hashes_remain_addressable_without_assay_promotion(self):
        first = self.source('v1', 'condition,label\ncold,1\n')
        second = self.source('v2', 'condition,label\nhot,2\n')
        catalog, private, hub = self.hub()
        self.assertEqual(len(catalog['assets']), 2)
        self.assertEqual(len(private), 2)
        self.assertEqual(len(hub.artifacts), 2)
        self.assertEqual(len(hub.assets), 2)
        with self.assertRaisesRegex(DatasetResolutionError, 'AMBIGUOUS_ASSET_VERSION'):
            hub.preview_asset('VERSION_TEST')
        cold = hub.preview_asset('VERSION_TEST', source_sha256=first)
        hot = hub.preview_asset('VERSION_TEST', source_sha256=second)
        self.assertEqual(cold['records'][0]['condition'], 'cold')
        self.assertEqual(hot['records'][0]['condition'], 'hot')
        self.assertNotEqual(cold['artifact_uid'], hot['artifact_uid'])
        self.assertFalse(cold['rankable_real_result'])
        self.assertFalse(hub.records['T0021']['admitted'])
        self.assertIsNone(hub.records['T0021']['task_level_sample_n'])

    def test_task_references_versions_but_logical_asset_id_is_not_duplicated(self):
        self.source('v1', 'x,label\na,1\n')
        self.source('v2', 'x,label\nb,2\n')
        _, _, hub = self.hub()
        task = hub.records['T0021']
        self.assertEqual(task['asset_ids'], ['VERSION_TEST'])
        self.assertEqual(len(task['artifact_uids']), 2)
        self.assertEqual(task['local_package_files'], 2)
        self.assertEqual(len(hub.get('T0021').assets), 2)

    def test_same_hash_copy_records_aliases_not_an_extra_version(self):
        digest = self.source('v1', 'condition,label\nsame,1\n')
        self.source('v1_copy', 'condition,label\nsame,1\n')
        catalog, private, hub = self.hub()
        self.assertEqual(len(catalog['assets']), 1)
        self.assertEqual(len(private), 1)
        item = hub.resolve_asset('VERSION_TEST')
        self.assertEqual(item['source_sha256'], digest)
        self.assertEqual(item['provenance_record_count'], 2)
        self.assertEqual(len(next(iter(private.values()))['provenance_aliases']), 2)
        self.assertEqual(hub.records['T0021']['local_package_files'], 1)

    def test_legacy_unique_asset_lookup_and_preview_remain_compatible(self):
        digest = self.source('v1', 'x,label\na,1\n')
        _, _, hub = self.hub()
        self.assertEqual(hub.assets['VERSION_TEST']['source_sha256'], digest)
        self.assertEqual(hub.preview_asset('VERSION_TEST')['source_sha256'], digest)
        item = hub.resolve_asset('VERSION_TEST')
        self.assertEqual(hub.preview_asset(item['artifact_uid'])['source_sha256'], digest)

    def test_wrong_locator_hash_is_not_used_for_a_version(self):
        self.source('v1', 'x,label\na,1\n')
        self.source('v2', 'x,label\nb,2\n')
        catalog, private, _ = self.hub()
        first, second = list(private)
        damaged = copy.deepcopy(private)
        damaged[first] = dict(private[second])
        path = self.root / self.config['private_assets_manifest']
        path.write_text(json.dumps({'artifacts': damaged}))
        with self.assertRaisesRegex(ValueError, 'ARTIFACT_LOCATOR_HASH_MISMATCH'):
            DatasetHub(root=self.root)


    def test_v1_catalog_and_private_locator_with_unique_version_still_load(self):
        digest = self.source('v1', 'x,label\na,1\n')
        catalog, private, _ = self.hub()
        catalog['schema_version'] = 'rna_gym.dataset_catalog.v1'
        for asset in catalog['assets']:
            asset.pop('artifact_uid')
        for task in catalog['tasks']:
            task.pop('artifact_uids')
        (self.root / 'data/registries/dataset_catalog.json').write_text(json.dumps(catalog))
        path = self.root / self.config['private_assets_manifest']
        path.write_text(json.dumps({'assets': {'VERSION_TEST': next(iter(private.values()))}}))
        hub = DatasetHub(root=self.root)
        self.assertEqual(hub.preview_asset('VERSION_TEST')['source_sha256'], digest)

    def test_ambiguous_legacy_locator_requires_rebuild_not_last_version(self):
        self.source('v1', 'x,label\na,1\n')
        self.source('v2', 'x,label\nb,2\n')
        _, private, _ = self.hub()
        path = self.root / self.config['private_assets_manifest']
        path.write_text(json.dumps({'assets': {'VERSION_TEST': next(iter(private.values()))}}))
        with self.assertRaisesRegex(ValueError, 'AMBIGUOUS_LEGACY_ARTIFACT_LOCATOR'):
            DatasetHub(root=self.root)

    def test_locator_points_to_wrong_bytes_but_claims_right_hash_is_rejected(self):
        self.source('v1', 'x,label\na,1\n')
        self.source('v2', 'x,label\nb,2\n')
        _, private, _ = self.hub()
        first, second = list(private)
        damaged = copy.deepcopy(private)
        damaged[first]['path'] = private[second]['path']
        path = self.root / self.config['private_assets_manifest']
        path.write_text(json.dumps({'artifacts': damaged}))
        hub = DatasetHub(root=self.root)
        with self.assertRaisesRegex(ValueError, 'RAW_CHECKSUM_MISMATCH'):
            hub.preview_asset(first)


if __name__ == '__main__':
    unittest.main()
