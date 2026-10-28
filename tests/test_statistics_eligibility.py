"""Conditional bootstrap intervals must never masquerade as formal support."""
import unittest
from tools.paired_statistics import paired_group_bootstrap


class IntervalEligibilityTests(unittest.TestCase):
    def call(self, **kw):
        args=dict(labels=[0,0,1],predictions_a=[0,0,1],predictions_b=[1,1,0],
                  groups=['a','b','c'],problem='regression',metric='spearman',replicates=2000,seed=17)
        args.update(kw);return paired_group_bootstrap(**args)

    def test_one_third_undefined_draws_is_unstable_without_redraw(self):
        value=self.call()
        self.assertGreater(value['invalid_fraction'],0.05)
        self.assertEqual(value['ci_status'],'UNSTABLE_RESAMPLING')
        self.assertFalse(value['formal_ci_eligible'])
        self.assertIsNone(value['formal_ci'])
        self.assertEqual(value['valid_replicates']+value['undefined_replicates'],2000)

    def test_two_group_interval_is_explicitly_conditional(self):
        value=self.call(labels=[0,1,2,3],predictions_a=[0,1,2,3],predictions_b=[3,2,1,0],groups=['a','a','b','b'])
        self.assertEqual(value['conditional_ci'],[2,2])
        self.assertEqual(value['ci'],value['conditional_ci'])
        self.assertIsNone(value['formal_ci'])
        self.assertFalse(value['formal_ci_eligible'])

    def test_same_method_delta_zero_and_ten_group_rule(self):
        value=self.call(labels=list(range(10)),predictions_a=list(range(10)),predictions_b=list(range(10)),groups=[str(i) for i in range(10)])
        self.assertEqual(value['conditional_ci'],[0,0])
        self.assertEqual(value['formal_ci'],[0,0])
        self.assertTrue(value['formal_ci_eligible'])


if __name__=='__main__':unittest.main()
