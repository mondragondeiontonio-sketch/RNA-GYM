import importlib.util,unittest,tempfile,json,csv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('qctab',ROOT/'tools/qc_tabular.py');q=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(q)
SPEC2=importlib.util.spec_from_file_location('dl',ROOT/'tools/rnagym.py');d=importlib.util.module_from_spec(SPEC2);SPEC2.loader.exec_module(d)
class TestScaffold(unittest.TestCase):
 def test_registry_len_and_invariant(self):
  with (ROOT/'data/registries/task_baselines_and_admission_198.csv').open(encoding='utf-8-sig') as fh:records=list(csv.DictReader(fh))
  self.assertEqual(len(records),198)
  self.assertFalse(any(t['当前准入状态']=='ADMITTED' for t in records))
 def test_plan(self):
  self.assertEqual(len(d.read_manifest()),12)
  self.assertFalse(any(z['sha256_expected'] for z in d.read_manifest().values()))
 def test_clean_split(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'small.csv';p.write_text('sequence,raw_label,split,construct_id\nACGU,1.4,train,c1\nCCGA,0.2,test,c2\n',encoding='utf-8')
   res=q.run(p,{'sequence_col':'sequence','label_col':'raw_label','split_col':'split','group_cols':['construct_id']})
   self.assertEqual(res['state'],'PASS_EXACT_QC_ONLY');self.assertFalse(res['admitted'])
 def test_crosssplit_leakage(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'leak.csv';p.write_text('sequence,raw_label,split\nACGU,1,train\nACGU,3,test\n',encoding='utf-8')
   self.assertEqual(q.run(p,{'sequence_col':'sequence','label_col':'raw_label','split_col':'split'})['state'],'EXACT_SPLIT_LEAKAGE_FAIL')
if __name__=='__main__':unittest.main()
