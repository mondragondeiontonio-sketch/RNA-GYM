import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from qc_format_recovery import diagnose
class FormatRecoveryTests(unittest.TestCase):
 def test_xls_suffix_does_not_force_binary_parser(self):
  r=diagnose(b'Clone ID\tcount\na\t1\n','Clones.xls')
  self.assertEqual(r['state'],'PARSED_DELIMITED_TEXT_WITH_MISLEADING_SUFFIX');self.assertEqual(r['actual_rows'],1)
 def test_unknown_delimiter_holds_instead_of_guessing(self):
  r=diagnose(b'header note with spaces\nACGU 1.2\n','source.txt');self.assertTrue(r['state'].startswith('HOLD_TEXT'));self.assertIsNone(r['actual_rows'])
 def test_unknown_encoding_not_claimed_verified(self):
  r=diagnose(b'id\tvalue\na\t1\n\xa1\t2\n','source.txt')
  self.assertTrue(r['state'].startswith('HOLD_ENCODING'));self.assertFalse(r['raw_values_rewritten']);self.assertNotEqual(r['member_sha256'],r['diagnostic_parser_stream_sha256'])
