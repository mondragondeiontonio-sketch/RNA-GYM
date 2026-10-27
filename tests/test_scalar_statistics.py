"""Synthetic, hand-computable metric and paired uncertainty contracts."""
import importlib.util
import itertools
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import evaluation_protocol as ep
from paired_statistics import paired_group_bootstrap


class ScalarMetricTests(unittest.TestCase):
    def test_signed_spearman_and_ties(self):
        self.assertAlmostEqual(ep.scalar_metrics([1, 2, 2, 4], [4, 2, 2, 1], 'regression')['spearman'], -1)
        self.assertIsNone(ep.scalar_metrics([1, 1], [0, 1], 'regression')['spearman'])

    def test_ap_is_not_trapezoidal_pr_auc(self):
        result = ep.scalar_metrics([1, 0, 1], [0.9, 0.8, 0.1], 'binary_classification')
        self.assertAlmostEqual(result['average_precision'], (1 + 2/3)/2)
        # TP=1, FP=1, FN=1, TN=0: MCC is negative, not absolute.
        self.assertAlmostEqual(result['mcc'], -0.5)
        self.assertEqual(result['positive_class'], 1)

    def test_ap_ties_order_invariance(self):
        for permutation in itertools.permutations([1, 0, 1, 0]):
            result = ep.scalar_metrics(list(permutation), [0.5]*4, 'binary_classification')
            self.assertAlmostEqual(result['average_precision'], 0.5)
            self.assertIsNone(result['mcc'])
            self.assertEqual(result['undefined_reasons']['mcc'], 'ZERO_CONFUSION_MARGIN')

    def test_absent_classes_and_perfect_inverse(self):
        zero = ep.scalar_metrics([0, 0], [0.1, 0.7], 'binary_classification')
        self.assertIsNone(zero['average_precision'])
        self.assertIsNone(zero['auroc'])
        self.assertIsNone(zero['mcc'])
        self.assertEqual(ep.scalar_metrics([1, 1], [0.1, 0.7], 'binary_classification')['average_precision'], 1)
        self.assertEqual(ep.scalar_metrics([0, 1], [0, 1], 'binary_classification')['mcc'], 1)
        self.assertEqual(ep.scalar_metrics([0, 1], [1, 0], 'binary_classification')['mcc'], -1)

    @unittest.skipUnless(importlib.util.find_spec('sklearn'), 'optional sklearn reference absent')
    def test_reference_implementations(self):
        from sklearn.metrics import average_precision_score, matthews_corrcoef
        for y in ([0, 1, 0, 1], [1, 1, 0, 1], [0, 0, 1, 0]):
            for p in ([0.2, 0.8, 0.4, 0.8], [0.1, 0.1, 0.9, 0.2]):
                got = ep.scalar_metrics(list(y), list(p), 'binary_classification')
                self.assertAlmostEqual(got['average_precision'], average_precision_score(y, p))
                self.assertAlmostEqual(got['mcc'], matthews_corrcoef(y, [int(v >= 0.5) for v in p]))
        from scipy.stats import spearmanr
        self.assertAlmostEqual(ep.scalar_metrics([1, 2, 2, 4], [4, 2, 1, 3], 'regression')['spearman'],
                               spearmanr([1, 2, 2, 4], [4, 2, 1, 3]).statistic)

    def test_invalid_metrics_rejected(self):
        for y, p in (([], []), ([1], []), ([1], [float('nan')]), ([True], [0.5]), ([2], [0.5])):
            with self.assertRaises(ep.ProtocolError):
                ep.scalar_metrics(y, p, 'binary_classification')


class PairedBootstrapTests(unittest.TestCase):
    def call(self, **kwargs):
        args = dict(labels=[0, 1, 2, 3], predictions_a=[0, 1, 2, 3],
                    predictions_b=[3, 2, 1, 0], groups=['a', 'a', 'b', 'b'],
                    problem='regression', metric='spearman', replicates=100, seed=17)
        args.update(kwargs)
        return paired_group_bootstrap(**args)

    def test_deterministic_paired_groups(self):
        self.assertEqual(self.call(), self.call())
        result = self.call()
        self.assertEqual(result['difference'], 2)
        self.assertEqual(result['n_groups'], 2)
        self.assertEqual(result['valid_replicates']+result['undefined_replicates'], 100)
        self.assertEqual(result['ci'], [2, 2])

    def test_identical_methods_zero_difference(self):
        result = self.call(predictions_b=[0, 1, 2, 3])
        self.assertEqual(result['difference'], 0)
        self.assertEqual(result['ci'], [0, 0])

    def test_degenerate_draws_counted_not_redrawn(self):
        result = self.call(labels=[0, 0, 1, 1], predictions_a=[0, 0, 1, 1],
                           predictions_b=[1, 1, 0, 0])
        self.assertGreater(result['undefined_replicates'], 0)
        self.assertEqual(result['valid_replicates']+result['undefined_replicates'], 100)

    def test_single_group_not_independent(self):
        result = self.call(groups=['same']*4)
        self.assertEqual(result['status'], 'UNDEFINED')
        self.assertIsNone(result['ci'])

    def test_malformed_pair_or_group_rejected(self):
        for kwargs in ({'groups':['a']}, {'groups':['a', None, 'b', 'b']}, {'metric':'n'},
                       {'replicates':True}, {'seed':False}):
            with self.assertRaises(ep.ProtocolError):
                self.call(**kwargs)


if __name__ == '__main__':
    unittest.main()
