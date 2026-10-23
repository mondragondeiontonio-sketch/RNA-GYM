import copy,importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('build_persist_site',ROOT/'tools/build_persist_site.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

def fixture():
 plan=json.loads((ROOT/'configs/persist_source_review.json').read_text());commit=plan['assets'][0]['upstream_commit']
 summary=dict(admitted=0,admission_candidates=0,scientific_disposition='HOLD',raw_labels_changed=False,raw_sequences_changed=False,rows_deleted=0,official_split_changed=False,real_models_run=0,gpu_jobs=0,source_commit=commit,input_fingerprint='b'*64,source_population_selection=dict(acquired_rows=10,source_construct_rows=12,acquired_ID_set_matches_finite_source_outcome_set=True),source_row_and_representation_counts=dict(sequence_mapping_matches=10),label_comparison={'target_ribosome_load':dict(exact_float32_rows=8,within_one_ulp_rows=10,maximum_ulp_distance=1,maximum_absolute_float32_error=1e-7),'target_in_cell_half_life':dict(exact_float32_rows=5,within_one_ulp_rows=5,maximum_ulp_distance=16000,maximum_absolute_float32_error=.03)},author_protocol_split=dict(seed=2541,split_origin='AUTHOR_CODE_PROTOCOL_REPRODUCTION_NOT_OFFICIAL_FIXED_MANIFEST',split_counts=dict(train=7,validation=1,test=2),evaluation_enabled=False,scientific_split_pass=False,exact_input_keys_shared_across_splits=0),component_disjoint_stress_test=dict(component_sizes=[8,1,1]))
 return summary,plan

class PersistSiteTests(unittest.TestCase):
 def test_approval_required(self):
  s,p=fixture()
  with self.assertRaises(PermissionError):b.build(s,p)
 def test_safe_deterministic_aggregate_export(self):
  s,p=fixture();s['private_path']='/private/DO_NOT_EXPORT';s['raw_labels']=['DO_NOT_EXPORT_LABEL'];s['reviewer']='DO_NOT_EXPORT_PERSON'
  page=b.build(s,p,True);self.assertEqual(page,b.build(s,p,True));self.assertIn('ADMITTED=0',page);self.assertIn('8/10',page);self.assertIn('script-src \'none\'',page)
  for private in ['DO_NOT_EXPORT','raw_labels','DO_NOT_EXPORT_PERSON','transcript_id\t']:self.assertNotIn(private,page)
 def test_admitted_or_changed_data_not_supported(self):
  for key,value in [('admitted',1),('scientific_disposition','ADMITTED'),('raw_labels_changed',True),('raw_sequences_changed',True),('real_models_run',1),('rows_deleted',1),('official_split_changed',True)]:
   s,p=fixture();s[key]=value
   with self.subTest(key=key),self.assertRaises(ValueError):b.build(s,p,True)
 def test_bad_counts_or_metrics_fail_closed(self):
  for field,value in [('exact_float32_rows',11),('maximum_absolute_float32_error',float('nan')),('maximum_ulp_distance',-1)]:
   s,p=fixture();s['label_comparison']['target_ribosome_load'][field]=value
   with self.subTest(field=field),self.assertRaises(ValueError):b.build(s,p,True)
 def test_nonofficial_provenance_required(self):
  s,p=fixture();s['author_protocol_split']['split_origin']='OFFICIAL_FIXED'
  with self.assertRaises(ValueError):b.build(s,p,True)
 def test_source_links_and_filenames_are_exact(self):
  for key,value in [('direct_url','https://github.com/public/repo?token='+'SYNTHETIC'),('relative_filename','PRIVATE_LABEL.tsv'),('sha256_expected','not-a-sha')]:
   s,p=fixture();p['assets'][0][key]=value
   with self.subTest(key=key),self.assertRaises(ValueError):b.build(s,p,True)
 def test_duplicate_or_missing_source_file_refused(self):
  for duplicate in [False,True]:
   s,p=fixture()
   if duplicate:p['assets'].append(copy.deepcopy(p['assets'][0]))
   else:p['assets'].pop()
   with self.assertRaises(ValueError):b.build(s,p,True)
 def test_component_counts_consistent(self):
  s,p=fixture();s['component_disjoint_stress_test']['component_sizes']=[1]
  with self.assertRaises(ValueError):b.build(s,p,True)
 def test_write_once_and_symlink_protection(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'page.html';b.write_once(p,'page');b.write_once(p,'page')
   with self.assertRaises(ValueError):b.write_once(p,'changed')
   link=Path(d)/'link.html';link.symlink_to(p)
   with self.assertRaises(ValueError):b.write_once(link,'page')
if __name__=='__main__':unittest.main()
