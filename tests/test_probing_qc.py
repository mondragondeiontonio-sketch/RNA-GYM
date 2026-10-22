import sys,unittest,importlib.util
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from qc_probing_files import vector

@unittest.skipUnless(importlib.util.find_spec('numpy'), 'optional QC numpy dependency unavailable')
class ProbingQCTests(unittest.TestCase):
 def test_missing_and_sentinel_kept_distinct(self):
  import numpy as np
  v=vector('[0.1, nan, -999, None, -0.2]')
  self.assertEqual(len(v),5);self.assertTrue(np.isnan(v[1]));self.assertEqual(v[2],-999)
 def test_partial_parse_refused(self):
  with self.assertRaises((ValueError,Warning)):vector('[0.1, garbage, 0.2]')
 def test_no_code_evaluation(self):
  with self.assertRaises((ValueError,Warning)):vector("__import__('os').system('false')")
 def test_empty_vector(self):self.assertEqual(len(vector('[]')),0)
