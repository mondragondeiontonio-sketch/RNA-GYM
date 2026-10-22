import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import qc_paired as q


class PairedQCTests(unittest.TestCase):
    def test_tu_are_distinct_and_order_matters(self):
        self.assertNotEqual(q.hash_parts(['ACGT', 'ACGU']), q.hash_parts(['ACGU', 'ACGT']))
        self.assertNotEqual(q.hash_parts(['ACGT', 'AAAA']), q.hash_parts(['ACGU', 'AAAA']))

    def test_same_sequence_other_mirna_is_not_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'pairs.tsv'
            path.write_text('gene\tnoncodingRNA\tlabel\nACGT\tAAAA\t1\nACGT\tCCCC\t0\n')
            report = q.audit(path, dataset='toy', split='test', output=root / 'qc')
            self.assertEqual(report['n_unique_paired_inputs'], 2)
            self.assertFalse(report['admission_gate_pass'])
            self.assertEqual(report['sequence_representation'], 'DNA_LETTERS_FOR_RNA_PAIRS')

    def test_empty_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'pairs.tsv'
            path.write_text('gene\tnoncodingRNA\tlabel\n')
            self.assertEqual(q.audit(path, dataset='toy', split='test',
                                    output=root / 'qc')['exact_qc_state'], 'FAIL')

    def test_expansion_cap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'pairs.tsv'
            path.write_text('gene\tnoncodingRNA\tlabel\nACGT\tAAAA\t1\n')
            with self.assertRaises(ValueError):
                q.audit(path, dataset='toy', split='test', output=root / 'qc', max_expanded=10)
