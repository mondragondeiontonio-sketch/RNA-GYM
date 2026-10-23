import copy,csv,importlib.util,json,tempfile,unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import audit_persist as a
NUMPY=importlib.util.find_spec('numpy') is not None
SKLEARN=importlib.util.find_spec('sklearn') is not None

def fixture():
 source={'SequenceID':'s1','RNA.sequence':'GGG'+'AAC'+'AUGGCUUAA'+'CC','CDS.sequence':'ATGGCTTAA','CDS.sequence.longest':'ATGGCTTAA','X5UTR.sequence':'AAC','X3UTR.sequence':'CC','group':'synthetic_group','CDS':'synthetic_reporter','X5UTR':'synthetic_5','X3UTR':'synthetic_3','ribosome_load':'1.25','half_life_in_cell':'2.75','ribosome_load_error':'0.1','degradation_coef_in_cell_error':'0.2'}
 seq=a.reconstruct_input(source);mask=[int(i in [3,6,9]) for i in range(len(seq))]
 row={'transcript_id':'s1','sequence':seq,'cds':mask,'splice':[0]*len(seq),'target_ribosome_load':1.25,'target_in_cell_half_life':2.75}
 return row,source

class PersistAuditTests(unittest.TestCase):
 def test_plan_has_real_hashes_but_no_approval(self):
  d=json.loads((ROOT/'configs/persist_source_review.json').read_text());self.assertEqual(d['task_id'],'T0022');self.assertFalse(d['automatic_download']);self.assertEqual(len(d['assets']),3)
  for r in d['assets']:self.assertRegex(r['sha256_expected'],r'^[0-9a-f]{64}$');self.assertEqual(r['redistribution_permission'],'NOT_APPROVED')
 def test_explicit_representation_not_silent_equivalence(self):
  row,s=fixture();before=copy.deepcopy(s);self.assertEqual(row['sequence'],'AACATGGCTTAACC');self.assertEqual(s,before);self.assertNotEqual(a.hash_bytes(row['sequence'].encode()),a.hash_bytes(s['RNA.sequence'].encode()))
 def test_wrong_prefix_or_dna_source_refused(self):
  _,s=fixture()
  for seq in ['AAC','GGGATGT','gggACGU','']:
   with self.subTest(seq=seq),self.assertRaises(ValueError):a.reconstruct_input({**s,'RNA.sequence':seq})
 def test_invalid_numbers_not_silently_missing(self):
  self.assertFalse(a.finite('NA'));self.assertFalse(a.finite('nan'));self.assertTrue(a.finite('1.2'))
  with self.assertRaises(ValueError):a.finite('unparsed-data')
 @unittest.skipUnless(NUMPY,'optional numpy')
 def test_ulp_comparison_exact_adjacent_and_sign(self):
  import numpy as np
  self.assertTrue(a.float32_compare(1.0,1.0)['exact_float32_bits'])
  self.assertEqual(a.float32_compare(1.0,np.nextafter(np.float32(1),np.float32(2)))['ulp_distance'],1)
  self.assertEqual(a.float32_compare(-1.0,np.nextafter(np.float32(-1),np.float32(0)))['ulp_distance'],1)
  self.assertFalse(a.float32_compare(-0.0,0.0)['exact_float32_bits'])
  with self.assertRaises(ValueError):a.float32_compare(float('nan'),1)
 @unittest.skipUnless(NUMPY,'optional numpy')
 def test_exact_rows_and_exclusion_with_unchanged_inputs(self):
  row,s=fixture();excluded={**s,'SequenceID':'missing','half_life_in_cell':'NA'};before=copy.deepcopy([row,s,excluded]);obs,labels,ex,counts,selection=a.audit_rows([row],[s,excluded])
  self.assertEqual(counts['sequence_mapping_matches'],1);self.assertEqual(len(labels),2);self.assertTrue(selection['acquired_ID_set_matches_finite_source_outcome_set']);self.assertEqual(ex[0]['reason'],'MISSING_SOURCE_HALF_LIFE');self.assertEqual([row,s,excluded],before)
 @unittest.skipUnless(NUMPY,'optional numpy')
 def test_source_label_difference_not_repaired(self):
  row,s=fixture();row['target_in_cell_half_life']=2.9;_,labels,_,_,_=a.audit_rows([row],[s]);self.assertEqual(labels[1]['decision'],'HOLD_SOURCE_LABEL_VERSION_MISMATCH');self.assertEqual(row['target_in_cell_half_life'],2.9)
 @unittest.skipUnless(NUMPY,'optional numpy')
 def test_codon_track_not_coding_coverage(self):
  row,s=fixture();self.assertTrue(a.cds_review(row,s)['pass_codon_track']);row['cds'][4]=1;self.assertFalse(a.cds_review(row,s)['pass_codon_track'])
 @unittest.skipUnless(NUMPY,'optional numpy')
 def test_empty_CDS_fallback_never_vacuous_match(self):
  row,s=fixture();self.assertTrue(a.cds_review(row,{**s,'CDS.sequence':''})['pass_codon_track']);self.assertFalse(a.cds_review(row,{**s,'CDS.sequence':'','CDS.sequence.longest':''})['pass_codon_track'])
 def test_duplicate_source_ids_rejected(self):
  _,s=fixture()
  with self.assertRaises(ValueError):a.unique_index([s,s],'SequenceID')
 @unittest.skipUnless(NUMPY,'optional numpy')
 def test_unknown_benchmark_id_rejected(self):
  row,s=fixture()
  with self.assertRaises(ValueError):a.audit_rows([{**row,'transcript_id':'absent'}],[s])
 def test_tabular_suffix_and_encoding_are_explicit(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'samples.csv';p.write_text('index\tvalue\nID\t2\n');self.assertEqual(a.strict_table(p,{'index','value'})[0]['value'],'2')
   with self.assertRaises(ValueError):a.strict_table(p,{'index','value'},',')
   p.write_bytes(b'index\tvalue\n\xff\t2\n')
   with self.assertRaises(UnicodeDecodeError):a.strict_table(p,{'index','value'})
 def test_ragged_table_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'r.tsv';p.write_text('a\tb\nx\n')
   with self.assertRaises(ValueError):a.strict_table(p,{'a','b'})
 def test_immutable_outputs(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'r.tsv';h=a.write_table(p,[{'a':'1'}],['a']);self.assertEqual(h,a.write_table(p,[{'a':'1'}],['a']))
   with self.assertRaises(ValueError):a.write_table(p,[{'a':'2'}],['a'])
 def test_components_do_not_merge_observations(self):
  row,s=fixture();rows=[row,{**row,'transcript_id':'s2'}];sources=[s,{**s,'SequenceID':'s2'}];r=a.component_audit(rows,sources);self.assertEqual(r['component_sizes'],[2]);self.assertFalse(r['three_way_component_disjoint_feasible']);self.assertEqual(len(rows),2)
 @unittest.skipUnless(SKLEARN,'optional sklearn')
 def test_split_reproduction_does_not_read_labels(self):
  rows=[];obs=[]
  for i in range(203):
   rows.append(dict(transcript_id='toy_'+str(i),target_ribosome_load=i))
   obs.append(dict(input_sequence_sha256=a.hash_bytes(str(i).encode()),source_group='synthetic_group',source_CDS_id='synthetic_reporter',source_UTR5_id=str(i),source_UTR3_id=str(i)))
  splits,q=a.reproduce_author_split(rows,obs);self.assertEqual(q['split_counts'],{'train':142,'validation':30,'test':31});self.assertEqual(q['exact_input_keys_shared_across_splits'],0);self.assertFalse(q['scientific_split_pass']);self.assertFalse(q['evaluation_enabled'])
  for r in rows:r['target_ribosome_load']=-r['target_ribosome_load']
  self.assertEqual(a.reproduce_author_split(rows,obs)[0],splits)
if __name__=='__main__':unittest.main()
