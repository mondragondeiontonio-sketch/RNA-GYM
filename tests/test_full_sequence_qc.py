import math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from qc_sequence_files import RowQC

class FullSequenceQCTests(unittest.TestCase):
 def spec(self):return {'sequence':'sequence','tracks':['cds','splice'],'targets':{'target':'continuous'}}
 def row(self,label=1.0):return {'sequence':'ACGT','cds':[1,1,0,0],'splice':[0,0,0,0],'target':label}
 def test_preserve_dna_letters_no_admission(self):
  q=RowQC(self.spec());q.add(self.row(),1);r=q.report()
  self.assertEqual(r['actual_n'],1);self.assertEqual(r['state'],'PASS_FULL_FILE_SCHEMA_ONLY');self.assertFalse(r['admission_gate_pass']);self.assertIn('T',r['sequence_alphabet_counts'])
 def test_track_and_nonfinite_detected(self):
  q=RowQC(self.spec());r=self.row(float('nan'));r['cds']=[1];q.add(r,1);out=q.report()
  self.assertEqual(out['state'],'ROW_QC_ISSUES_DETECTED');self.assertEqual(out['target_stats']['target']['invalid_or_nonfinite'],1);self.assertIn('TRACK_LENGTH_OR_TYPE:cds',out['issues'])
 def test_different_labels_not_deleted(self):
  q=RowQC(self.spec());q.add(self.row(1),1);q.add(self.row(2),2);r=q.report()
  self.assertEqual(r['actual_n'],2);self.assertEqual(r['rows_removed'],0);self.assertEqual(r['inputs_with_different_target_payloads'],1)
 def test_empty_not_passed(self):
  self.assertEqual(RowQC(self.spec()).report()['state'],'ROW_QC_ISSUES_DETECTED')
 def test_multireadouts_kept_separate(self):
  spec=self.spec();spec['targets']={'mrl':'continuous','half_life':'continuous'};q=RowQC(spec);row=self.row();row.update(mrl=2.0,half_life=3.0);q.add(row,1)
  self.assertEqual(set(q.report()['target_stats']),{'mrl','half_life'})
