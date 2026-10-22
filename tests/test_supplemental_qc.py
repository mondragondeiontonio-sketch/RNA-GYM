import io,pickle,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from qc_supplemental_formats import inspect
class SupplementalQCTests(unittest.TestCase):
 def test_pickle_is_only_statically_inspected(self):
  r=inspect(io.BytesIO(pickle.dumps({'sequence':'ACGU','label':1})),'toy.pkl')
  self.assertFalse(r['unpickled_or_code_executed']);self.assertFalse(r['semantic_data_loaded']);self.assertTrue(r['state'].startswith('HOLD_'))
 def test_text_missing_and_nonfinite_retained(self):
  r=inspect(io.BytesIO(b'id\tlabel\na\t1\nb\tnan\n'),'toy.txt')
  self.assertEqual(r['actual_rows'],2);self.assertEqual(r['column_value_types_and_ranges']['label']['nonfinite'],1)
 def test_profile_not_mistaken_for_assay(self):
  r=inspect(io.BytesIO(b'HMMER3/f\nNAME RF00001\nLENG 10\nALPH RNA\n//\n'),'profile.hmm')
  self.assertTrue(r['format_header_valid']);self.assertIn('NOT_EXPERIMENTAL_ASSAY',r['state'])
