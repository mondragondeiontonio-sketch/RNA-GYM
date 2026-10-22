import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from assemble_multipart import checksums
class MultipartTests(unittest.TestCase):
 def test_only_actual_sha256_accepted(self):
  self.assertEqual(checksums('a'*64+'  part-00\n'),{'part-00':'a'*64})
  with self.assertRaises(ValueError):checksums('a'*40+'  git-object\n')
 def test_wrong_manifest_line_refused(self):
  with self.assertRaises(ValueError):checksums('not-a-hash  part')
