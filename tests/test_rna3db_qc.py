import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from qc_rna3db import compare_versions,validate_jsons
class RNA3DBQCTests(unittest.TestCase):
 def docs(self,seq='ACGU'):
  meta={'sequence':seq,'length':len(seq),'resolution':2.0,'structure_method':'X-RAY DIFFRACTION'}
  return {'parse.json':{'1abc_A':meta},'filter.json':{'1abc_A':meta},'cluster.json':{'component_1':{'1abc_A':meta}},'split.json':{'train_set':{'component_1':{'1abc_A':meta}},'test_set':{}}}
 def test_diff_preserves_tu(self):
  d=compare_versions(self.docs('ACGT'),self.docs('ACGU'))
  self.assertEqual(d['parse.json']['shared_chain_ids_with_changed_raw_sequence'],['1abc_A']);self.assertIsNone(d['selected_version'])
 def test_split_not_rebuilt_or_admitted(self):
  d=validate_jsons(self.docs());self.assertFalse(d['admission_gate_pass']);self.assertEqual(d['original_split_overlap'][0]['shared_exact_chain_ids'],0)
