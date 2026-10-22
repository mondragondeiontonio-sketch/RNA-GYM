import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import scientific_audit as a
from phase2_probing_review import compare,known_equal,load_selected

class ScientificAuditTests(unittest.TestCase):
 def test_file_qc_never_admits(self):
  stage,gaps=a.assess(dict(file_qc_verified=True));self.assertEqual(stage,'FILE_QC_PASS');self.assertIn('source_verified',gaps)
 def test_source_only_never_assay_verified(self):
  stage,gaps=a.assess(dict(source_verified=True,file_qc_verified=True));self.assertEqual(stage,'SOURCE_VERIFIED');self.assertIn('split_verified',gaps)
 def test_all_automated_evidence_only_candidate(self):
  keys=['source_verified','rights_verified','label_verified','sample_identity_verified','split_verified','qc_verified','dedup_verified','leakage_verified','raw_hash_verified']
  self.assertEqual(a.assess(dict.fromkeys(keys,True)),('ADMISSION_CANDIDATE',[]))
  self.assertNotEqual(a.assess(dict.fromkeys(keys,'True'))[0],'ADMISSION_CANDIDATE')
 def test_temporary_ids_do_not_fabricate_experiments(self):
  c=a.candidate('project','alias');self.assertTrue(c['canonical_assay_id'].startswith('TMP_'));self.assertEqual(c['original_assay_id'],'');self.assertEqual(c['original_sample_count'],'')
  self.assertEqual(c,a.candidate('project','alias'));self.assertNotEqual(c['canonical_assay_id'],a.candidate('other','alias')['canonical_assay_id'])
 def test_immutable_table(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'e.tsv';a.table(p,[{'k':'a\tb'}],['k']);a.table(p,[{'k':'a\tb'}],['k'])
   with self.assertRaises(FileExistsError):a.table(p,[{'k':'changed'}],['k'])
 def test_complete_required_input_reads_and_ids(self):
  if not (ROOT/'runs/20261022_212625/reports/qc_summary.json').exists():self.skipTest('local-only historical QC evidence intentionally not published')
  d,m=a.inventory(ROOT/'runs/20261022_212625');self.assertEqual(len(d['search_level_task_crosswalk_198.csv']),198)
  self.assertTrue(all(x['sha256'] and x['read_scope']=='FULL_BYTES_STRICT_UTF8' for x in m))
  self.assertTrue(set(a.REPORTS).issubset({Path(x['path']).name for x in m}))
  self.assertEqual(sum(r['row_id'].startswith('X') for r in d['search_level_task_crosswalk_198.csv']),57)
 def test_dry_run_no_output_and_single_task(self):
  if not (ROOT/'runs/20261022_212625/reports/qc_summary.json').exists():self.skipTest('local-only historical QC evidence intentionally not published')
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'nonexistent';r=a.compile_run(ROOT/'runs/20261022_212625',p,'T0021',True)
   self.assertEqual(r['selected_tasks'],1);self.assertFalse(p.exists())
   with self.assertRaises(ValueError):a.compile_run(ROOT/'runs/20261022_212625',p,'BOGUS',True)
 def test_missing_conditions_never_equal(self):
  self.assertEqual(known_equal(None,None),'UNKNOWN');self.assertEqual(known_equal('DMS','DMS'),'SAME');self.assertEqual(known_equal('DMS','NMIA'),'DIFFERENT')
 def test_probing_labels_and_masks_not_changed(self):
  try:import numpy
  except ImportError:self.skipTest('optional numpy unavailable')
  l=dict(seqID='a',sequence='ACG',modifier='DMS',reactivity='[1 nan -999]',reactivity_error='[0.1 nan -999]')
  r={**l,'seqID':'b','reactivity':'[1 0.2 -999]'}
  before=json.dumps([l,r]);c=compare(l,r);self.assertEqual(c['same_original_assay'],'UNKNOWN');self.assertFalse(c['reactivity_valid_mask_equal']);self.assertEqual(json.dumps([l,r]),before)
 def test_selective_parquet_rows(self):
  try:import pyarrow as pa;import pyarrow.parquet as pq
  except ImportError:self.skipTest('optional pyarrow unavailable')
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'r.parquet';pq.write_table(pa.table({'a':list(range(10))}),p,row_group_size=2)
   r,n=load_selected(p,{3,4,10});self.assertEqual(n,2);self.assertEqual(r[3]['a'],2)
   with self.assertRaises(ValueError):load_selected(p,{11})
if __name__=='__main__':unittest.main()
