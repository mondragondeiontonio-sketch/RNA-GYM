import importlib.util,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import inspect_npz_source as s
NUMPY=importlib.util.find_spec('numpy') is not None
@unittest.skipUnless(NUMPY,'optional numpy')
class NPZSourceTests(unittest.TestCase):
 def setUp(self):
  import numpy as np
  self.np=np;self.d=tempfile.TemporaryDirectory();self.addCleanup(self.d.cleanup);self.p=Path(self.d.name)/'source.npz'
 def test_object_array_is_not_loaded(self):
  self.np.savez(self.p,X=self.np.array([{'synthetic':'only'}],dtype=object))
  with patch.object(self.np,'load',side_effect=AssertionError('object must never be loaded')):r,arrays=s.inspect_archive(self.p)
  self.assertFalse(r['pickle_deserialized']);self.assertEqual(r['object_arrays_loaded'],0);self.assertEqual(r['state'],'HOLD_SAFE_FORMAT_EXPORT');self.assertEqual(arrays,{})
 def test_only_bounded_numeric_loaded(self):
  self.np.savez(self.p,X=self.np.array(['synthetic'],dtype=object),y=self.np.array([1.0,2.0],dtype='float32'));r,arrays=s.inspect_archive(self.p)
  self.assertEqual(r['numeric_arrays_loaded'],1);self.assertEqual(arrays['y'].tolist(),[1,2]);self.assertFalse(r['pickle_deserialized'])
 def test_md5_not_mislabeled_sha256(self):
  self.np.savez(self.p,y=self.np.array([1.0]));r,_=s.inspect_archive(self.p);self.assertEqual(len(r['upstream_md5']),32);self.assertEqual(len(r['source_sha256']),64)
  with self.assertRaises(ValueError):s.inspect_archive(self.p,'0'*32)
 def test_expansion_budget_stops_numeric_loading(self):
  self.np.savez(self.p,y=self.np.ones(100));r,arrays=s.inspect_archive(self.p,max_expanded=1);self.assertEqual(r['state'],'HOLD_EXPANSION_BUDGET');self.assertFalse(arrays)
 def test_selective_mode_skips_large_array_keeps_bounded_y(self):
  self.np.savez_compressed(self.p,X=self.np.ones(200000,dtype='int8'),y=self.np.array([1,2],dtype='int8'))
  default,_=s.inspect_archive(self.p,max_expanded=64*1024);self.assertEqual(default['state'],'HOLD_EXPANSION_BUDGET')
  r,arrays=s.inspect_archive(self.p,max_expanded=64*1024,selective=True,max_numeric=32)
  self.assertNotIn('X',arrays);self.assertEqual(arrays['y'].tolist(),[1,2]);self.assertLess(r['selected_expanded_read_budget_upper_bound_bytes'],64*1024);self.assertFalse(r['full_archive_expanded'])
 def test_fixed_unicode_gene_metadata_is_safe_not_pickle(self):
  self.np.savez(self.p,genes=self.np.array(['SYN1','SYN2'],dtype='<U10'))
  r,arrays=s.inspect_archive(self.p);self.assertEqual(arrays['genes'].tolist(),['SYN1','SYN2']);self.assertEqual(r['plain_string_arrays_loaded'],1);self.assertEqual(r['numeric_arrays_loaded'],0);self.assertFalse(r['pickle_deserialized'])
 def test_zip_path_and_duplicate_rejected(self):
  with zipfile.ZipFile(self.p,'w') as z:z.writestr('../bad.npy',b'bad')
  with self.assertRaises(ValueError):s.inspect_archive(self.p)
 def test_nonfinite_labels_rejected(self):
  self.np.savez(self.p,y=self.np.array([self.np.nan]))
  with self.assertRaises(ValueError):s.inspect_archive(self.p)
if __name__=='__main__':unittest.main()
