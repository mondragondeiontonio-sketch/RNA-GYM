import importlib.util,json,tempfile,unittest,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location('build_mrl_split_site',ROOT/'tools/build_mrl_split_site.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
def fixture():
 def quality(shared):return dict(split_counts={'train':7,'validation':1,'test':2},gene_overlap={'shared_keys':shared},exact_input_overlap={'shared_keys':shared},known_homology_groups_shared=0,evaluation_enabled=False,admission_gate_pass=False,pairwise_overlap_counts={'train__test':dict(shared_gene_keys=shared,shared_exact_input_keys=shared)})
 return dict(coverage={'rows':10,'unique_gene_annotations':8,'mapped_gene_annotations':4,'unmapped_gene_annotations':4},author_protocol_reproduction=quality(1),custom_exploratory_split=quality(0),custom_component_count=8,largest_component_rows=2,source_input_sha256={'HOMOLOGENE_13910050':'a'*64},protocol_sha256='b'*64,scientific_disposition='HOLD_SOURCE_IDENTITY',raw_labels_read_for_split=False,original_split_changed=False,labels_merged=False,all_observations_preserved=True,admission_candidates=0,admitted=0,real_models_run=0,GPU_jobs=0)
class MRLPageTests(unittest.TestCase):
 def test_approval_required(self):
  with self.assertRaises(PermissionError):b.build(fixture())
 def test_deterministic_export_no_private_payload(self):
  x=fixture();x.update(raw_labels=['PRIVATE_LABEL'],gene_list=['PRIVATE_GENE'],fold_rows=['PRIVATE_FOLD'],reviewer='PRIVATE_PERSON');page=b.build(x,True)
  self.assertEqual(page,b.build(x,True));self.assertNotIn('PRIVATE_',page);self.assertIn('ADMITTED=0',page);self.assertIn('script-src \'none\'',page)
 def test_admission_and_model_execution_refused(self):
  for k in ['admitted','real_models_run','GPU_jobs']:
   x=fixture();x[k]=1
   with self.assertRaises(ValueError):b.build(x,True)
 def test_unsupported_data_changes_refused(self):
  x=fixture();x['raw_labels_read_for_split']=True
  with self.assertRaises(ValueError):b.build(x,True)
 def test_bad_counts_refused(self):
  x=fixture();x['coverage']['mapped_gene_annotations']=100
  with self.assertRaises(ValueError):b.build(x,True)
 def test_custom_leak_cannot_be_called_strict(self):
  x=fixture();x['custom_exploratory_split']['exact_input_overlap']['shared_keys']=1
  with self.assertRaises(ValueError):b.build(x,True)
 def test_bad_hash_refused(self):
  x=fixture();x['protocol_sha256']='not-sha256'
  with self.assertRaises(ValueError):b.build(x,True)
 def test_immutable_and_symlink(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'r.html';b.write_once(p,'page');b.write_once(p,'page')
   with self.assertRaises(ValueError):b.write_once(p,'changed')
   link=Path(d)/'l.html';link.symlink_to(p)
   with self.assertRaises(ValueError):b.write_once(link,'page')
if __name__=='__main__':unittest.main()
