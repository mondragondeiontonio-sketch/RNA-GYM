import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'tools/phase2_pair_identity.py'
SPEC = importlib.util.spec_from_file_location('phase2_pair_identity', MODULE)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def raw(**changes):
    row = dict(gene='ACGT', noncodingRNA='UGCA', noncodingRNA_name='hsa-miR-1',
               chr='1', start='100', end='103', strand='+', label='1', gene_cluster_ID='99')
    row.update(changes)
    return row


def observation(dataset='A', split='train', **kwargs):
    row = audit.identities(raw(), dataset, **kwargs)
    row.update(dataset_alias=dataset, original_split=split, raw_label='1', raw_row_sha256='a' * 64)
    return row


class PairIdentityTests(unittest.TestCase):
    def test_tu_case_and_role_order_preserved(self):
        original = audit.identities(raw(), 'A')
        for changed in (raw(gene='ACGU'), raw(gene='acgt'), raw(gene='UGCA', noncodingRNA='ACGT')):
            result = audit.identities(changed, 'A')
            self.assertNotEqual(original['compound_identity_sha256'], result['compound_identity_sha256'])
            self.assertNotEqual(original['cross_assay_pair_sha256'], result['cross_assay_pair_sha256'])

    def test_target_id_is_coordinates_not_gene_sequence_or_cluster(self):
        original = audit.identities(raw(), 'A')
        self.assertIn('assembly:UNKNOWN', original['target_id'])
        self.assertNotIn('ACGT', original['target_id'])
        self.assertNotIn('99', original['target_id'])
        self.assertEqual(original['target_id'], audit.identities(raw(gene_cluster_ID='different'), 'A')['target_id'])
        self.assertNotEqual(original['target_id'], audit.identities(raw(start='100.0'), 'A')['target_id'])
        self.assertNotEqual(original['compound_identity_sha256'],
                            audit.identities(raw(noncodingRNA_name='hsa-miR-2'), 'A')['compound_identity_sha256'])

    def test_ambiguous_assay_not_same_assay_duplicate(self):
        left, right = observation(), observation()
        result = audit.classify(left, right)
        self.assertFalse(result['same_assay_duplicate'])
        self.assertFalse(result['same_assay_verified'])
        self.assertTrue(result['ambiguous_identity'])
        self.assertFalse(left['assay_identity_verified'])
        self.assertTrue(left['original_assay_id'].startswith('TEMP_DATASET:'))

    def test_different_assay_only_provisional_dataset_scope(self):
        result = audit.classify(observation('A'), observation('B'))
        self.assertTrue(result['same_pair_different_assay'])
        self.assertEqual(result['assay_difference_status'], 'PROVISIONAL_DATASET_SCOPE_ONLY')
        self.assertEqual(result['rows_removed'], 0)
        self.assertEqual(result['labels_merged'], 0)

    def test_different_conditions_kept_separate(self):
        left = observation(assay_id='real', assay_verified=True,
                           condition_id='cold', condition_verified=True)
        right = observation(assay_id='real', assay_verified=True,
                            condition_id='warm', condition_verified=True)
        self.assertNotEqual(left['compound_identity_sha256'], right['compound_identity_sha256'])
        self.assertEqual(left['cross_assay_pair_sha256'], right['cross_assay_pair_sha256'])
        self.assertFalse(audit.classify(left, right)['same_assay_duplicate'])
        self.assertEqual(audit.classify(left, right)['labels_merged'], 0)

    def test_same_assay_duplicate_requires_verified_condition_and_raw_row(self):
        left = observation(assay_id='real', assay_verified=True,
                           condition_id='cold', condition_verified=True)
        right = dict(left)
        self.assertTrue(audit.classify(left, right)['same_assay_duplicate'])
        right['condition_identity_verified'] = False
        self.assertFalse(audit.classify(left, right)['same_assay_duplicate'])

    def test_verified_same_assay_reused_by_different_benchmarks(self):
        left = observation('benchmark_A', assay_id='original_accession', assay_verified=True,
                           condition_id='cold', condition_verified=True)
        right = observation('benchmark_B', assay_id='original_accession', assay_verified=True,
                            condition_id='cold', condition_verified=True)
        result = audit.classify(left, right)
        self.assertTrue(result['same_assay_verified'])
        self.assertFalse(result['same_pair_different_assay'])
        self.assertEqual(result['assay_difference_status'], 'SAME_ASSAY_VERIFIED')

    def test_crosssplit_and_conflict_are_independent(self):
        left, right = observation('A', 'train'), observation('B', 'test')
        right['raw_label'] = '0'
        result = audit.classify(left, right)
        self.assertTrue(result['cross_split_same_pair'])
        self.assertTrue(result['train_heldout_input_sharing'])
        self.assertTrue(result['conflicting_labels'])
        self.assertFalse(result['same_dataset_split_contamination'])
        right['dataset_alias'] = 'A'
        self.assertTrue(audit.classify(left, right)['same_dataset_split_contamination'])
        right['original_split'] = 'train'
        self.assertFalse(audit.classify(left, right)['cross_split_same_pair'])

    def test_mirror_representation_not_independent_same_assay(self):
        left, right = observation('A', 'test'), observation('A', 'test')
        right['raw_row_sha256'] = 'b' * 64
        result = audit.classify(left, right, representation_alias=True)
        self.assertTrue(result['representation_alias'])
        self.assertFalse(result['same_raw_row_sha256'])
        self.assertFalse(result['same_assay_duplicate'])
        self.assertFalse(result['same_pair_different_assay'])

    def test_multivalued_mirna_name_not_exploded(self):
        result = audit.identities(raw(noncodingRNA_name='hsa-miR-1|hsa-miR-2'), 'A')
        self.assertEqual(result['mirna_id'], 'hsa-miR-1|hsa-miR-2')
        self.assertIn('MULTIVALUED_MIRNA_ID', result['ambiguity_flags'])

    def test_projected_pass_and_checkpoint_skip_raw(self):
        try:
            import pyarrow  # noqa: F401
            import pyarrow.parquet as pq
        except ImportError:
            self.skipTest('optional QC environment pyarrow required')
        import gzip
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_raw = root / 'example.tsv.gz'
            with gzip.open(source_raw, 'wt', encoding='utf-8') as stream:
                stream.write('\t'.join(audit.PROJECTED_FIELDS) + '\n')
                stream.write('\t'.join(raw()[key] for key in audit.PROJECTED_FIELDS) + '\n')
            source_raw.chmod(0o444)
            source = dict(asset_id='toy', source_sha256='a' * 64, raw=source_raw,
                          dataset_alias='toy_scope', original_split='test', actual_n=1,
                          raw_snapshot=audit.snapshot(source_raw), evidence=['toy_prior_proof'])
            db = sqlite3.connect(':memory:')
            db.execute('CREATE TABLE samples(asset_id,row_number,input_hash,observation_hash,raw_label)')
            db.execute('INSERT INTO samples VALUES(?,?,?,?,?)', ('toy', 1, b'x' * 32, b'y' * 32, '1'))
            checkpoint, reused = audit.audit_source(source, db, root, {1}, 'proof')
            self.assertFalse(reused)
            table = pq.read_table(root / checkpoint['parquet_filename'])
            self.assertEqual(table.num_rows, 1)
            self.assertEqual(table['raw_row_sha256'][0].as_py(), b'y' * 32)
            with patch('pyarrow.input_stream', side_effect=AssertionError('raw must not reopen')):
                again, reused = audit.audit_source(source, db, root, {1}, 'proof')
            self.assertTrue(reused)
            self.assertEqual(checkpoint, again)
            checkpoint_file = next(root.glob('*.checkpoint.json'))
            with self.assertRaisesRegex(ValueError, 'prior evidence changed'):
                audit.load_checkpoint(checkpoint_file, source, 'changed')
            source_raw.chmod(0o644)
            with self.assertRaisesRegex(ValueError, 'raw stat changed'):
                audit.load_checkpoint(checkpoint_file, source, 'proof')
            db.close()

    def test_sequence_match_does_not_imply_identifier_match(self):
        row = dict(representation_alias=False, same_cross_assay_pair_key=False,
                   same_compound_key=False, left_mirna_id='name_1', right_mirna_id='name_2',
                   left_target_id='UNKNOWN:chr1:100', right_target_id='UNKNOWN:chr2:100')
        report = audit.key_layer_audit([row])
        self.assertEqual(report['counts']['nonmirror_exact_sequence_pair_comparisons'], 1)
        self.assertEqual(report['counts']['nonmirror_equal_identifier_qualified_pair_keys'], 0)
        self.assertTrue(report['no_sequence_or_observation_merge'])

    def test_all_comparison_counts_include_zero_pairs(self):
        sources = [dict(asset_id=value, dataset_alias=value, original_split='test')
                   for value in ('A', 'B', 'C')]
        rows = audit.comparison_counts([], sources)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row['shared_exact_input_pair_count'] == 0 for row in rows))
        self.assertTrue(all(row['same_pair_different_assay_verified_count'] == 0 for row in rows))
        self.assertTrue(all(not row['assay_identity_verified'] for row in rows))

    def test_checkpoint_key_separates_source_versions(self):
        source = dict(asset_id='toy', source_sha256='a' * 64,
                      dataset_alias='toy_scope', original_split='test')
        self.assertNotEqual(audit.checkpoint_key(source),
                            audit.checkpoint_key({**source, 'source_sha256': 'b' * 64}))

    def test_immutable_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'evidence.json'
            audit.write_json(path, {'x': 1})
            audit.write_json(path, {'x': 1})
            with self.assertRaisesRegex(ValueError, 'immutable evidence conflict'):
                audit.write_json(path, {'x': 2})


if __name__ == '__main__':
    unittest.main()
