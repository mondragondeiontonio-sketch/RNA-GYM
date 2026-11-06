"""Train-only inverse and immutable original OOF identity counterexamples."""
import importlib.util
import unittest
from rna_gym.research_v06.provenance import ProtocolError
from tools.mrna_design.replay_legacy_frozen import train_inverse,replay_arrays


@unittest.skipUnless(importlib.util.find_spec('numpy'),'Optional numpy required')
class LegacyInverseTests(unittest.TestCase):
    def test_only_train_fits_inverse(self):
        mean=2.;std=1.
        r=train_inverse([1,3,100,200],[-1,1,98,198],['train','train','val','test'])
        self.assertEqual(r['mean'],mean);self.assertEqual(r['std_population'],std)

    def test_global_or_test_scaler_refused(self):
        with self.assertRaises(ProtocolError):
            train_inverse([1,3,100,200],[-1,1,0,0],['train','train','val','test'])

    def test_constant_train_refused(self):
        with self.assertRaises(ProtocolError):
            train_inverse([2,2,100,200],[0,0,0,0],['train','train','val','test'])

    def test_source_version_mismatch_refused(self):
        import numpy as np
        source={'raw':np.array([1.,3.]),'sequence_sha':np.array(['a','b']),
          'test_fold':np.array([0,1]),'test_z':np.array([0.,1.]),
          'stats':{'0':{'mean':1.,'std_population':2.},'1':{'mean':1.,'std_population':2.}}}
        table={'sample_id':['0','1'],'outer_fold':[0,1],'sequence_sha':['a','b'],
               'y_true_raw':[1.,3.],'y_true_scaled':[0.,1.],'y_pred_scaled':[.5,1.5]}
        _,_,p=replay_arrays(table,source);self.assertEqual(p.tolist(),[2.,4.])
        for key,bad in [('sample_id',['0','0']),('outer_fold',[1,0]),
                        ('sequence_sha',['a','x']),('y_true_raw',[1.,4.]),
                        ('y_true_scaled',[0.,9.])]:
            altered=dict(table);altered[key]=bad
            with self.assertRaises(ProtocolError):replay_arrays(altered,source)
