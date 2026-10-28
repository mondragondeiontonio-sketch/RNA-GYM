import tempfile
import unittest
from pathlib import Path

import importlib.util
HAS_QC=all(importlib.util.find_spec(m) for m in ('numpy','pyarrow'))
if HAS_QC:
    from tools.curation.splits import select_folds,role,biological_groups
    from tools.curation.core import Curator


@unittest.skipUnless(HAS_QC,'Optional numpy/pyarrow QC dependencies absent')
class SplitTests(unittest.TestCase):
    def test_ten_fold_and_validation_is_not_test(self):
        groups=[f'o{i}' for i in range(123)]
        assigned,k,_=select_folds(groups)
        self.assertEqual(k,10)
        self.assertEqual(len(assigned),123)
        self.assertLessEqual(max(__import__('collections').Counter(assigned.values()).values())-
                             min(__import__('collections').Counter(assigned.values()).values()),1)
        for outer in range(10):
            self.assertEqual(sum(role(f,outer,10)=='test' for f in range(10)),1)
            self.assertEqual(sum(role(f,outer,10)=='validation' for f in range(10)),1)
    def test_stable_under_row_reordering(self):
        gs=['a','b','c','d','e','f','g','h','i','j']
        self.assertEqual(select_folds(gs)[0],select_folds(gs[::-1])[0])
    def test_single_wt_like_cluster_not_forced_apart(self):
        self.assertEqual(select_folds(['one']*100)[1],0)
    def test_minority_support_reduces_fold_count(self):
        gs=[str(i) for i in range(25)]
        labels=[0]*20+[1]*5
        a,k,_=select_folds(gs,labels)
        self.assertEqual(k,5)
        for f in range(k):
            self.assertEqual({y for g,y in zip(gs,labels) if a[g]==f},{0,1})
    def test_rare_class_not_fabricated(self):
        self.assertEqual(select_folds(list('abcdefghij'),[0]*9+[1])[1],0)
    def test_transitive_gene_sequence_groups(self):
        rows=[{'observation_id':'a','input_hash':'a','sequence':'AT','group_metadata':{'gene':'X'}},
              {'observation_id':'b','input_hash':'b','sequence':'CG','group_metadata':{'gene':'X'}},
              {'observation_id':'c','input_hash':'c','sequence':'UU','group_metadata':{}}]
        gs=biological_groups(rows,{'AU':'cluster1','CG':'cluster2','UU':'cluster2'})
        self.assertEqual(len(set(gs)),1)
    def test_different_conditions_are_not_observation_dedup(self):
        with tempfile.TemporaryDirectory() as td:
            a={'x':{'sha256':'s'}}
            spec={'unit_id':'test','assay_id':'A','readout_id':'r','modality':'regulatory'}
            # Construct without creating production paths.
            obj=Curator.__new__(Curator)
            import collections
            for k,v in dict(spec=spec,all_assets=a,records=[],actual_n=0,logs=[],lengths=[],gc=[],
                sequence_chars=collections.Counter(),raw_row_mapping=[],exact_raw={},
                observation_labels=collections.defaultdict(set),label_sets=collections.defaultdict(set),
                input_counts=collections.Counter(),input_label_counts=collections.Counter(),
                failure_counts=collections.Counter(),duplicate_n=0,source_members=set()).items():setattr(obj,k,v)
            obj.add({'sequence':'ACGU','label':1,'identity':'same','context':{'cell':'A'}},'x',1)
            obj.add({'sequence':'ACGU','label':2,'identity':'same','context':{'cell':'B'}},'x',2)
            self.assertNotEqual(obj.records[0]['observation_id'],obj.records[1]['observation_id'])
            self.assertEqual(obj.duplicate_n,0)
            obj.add({'sequence':'ACGU','label':1,'identity':'same','context':{'cell':'A'}},'x',3)
            self.assertEqual(obj.duplicate_n,1)
    def test_missing_identity_not_silently_collapsed(self):
        # Literal equal sequences do not prove the same original observation.
        from tools.curation.core import sha
        self.assertNotEqual(sha(['a','member',1]),sha(['a','member',2]))

if __name__=='__main__':unittest.main()


@unittest.skipUnless(HAS_QC,'Optional numpy/pyarrow QC dependencies absent')
class SafeDataDecoderTests(unittest.TestCase):
    def test_primitive_containers(self):
        import pickle
        from tools.curation.safe_pickle import decode
        value=[('f','id','ACGU'),{'x':[1,None,2.5]}]
        self.assertEqual(decode(pickle.dumps(value,protocol=4)),value)
    def test_numpy_numeric_protocols(self):
        import pickle
        import numpy as np
        from tools.curation.safe_pickle import decode
        a=np.arange(12,dtype=np.int64).reshape(3,4)
        for protocol in [4,5]:
            self.assertTrue(np.array_equal(decode(pickle.dumps([a],protocol=protocol))[0],a))
    def test_reject_arbitrary_callable(self):
        import pickle
        import os
        from tools.curation.safe_pickle import decode
        class Bad:
            def __reduce__(self):return os.system,('false',)
        with self.assertRaisesRegex(ValueError,'FORBIDDEN_GLOBAL'):decode(pickle.dumps(Bad()))
    def test_reject_object_dtype(self):
        import pickle
        import numpy as np
        from tools.curation.safe_pickle import decode
        with self.assertRaises(ValueError):decode(pickle.dumps(np.array([object()],dtype=object)))
    def test_size_budget(self):
        from tools.curation.safe_pickle import decode
        with self.assertRaisesRegex(ValueError,'BYTE_BUDGET'):decode(b'123456789',max_bytes=2)
