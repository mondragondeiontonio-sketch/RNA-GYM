import csv,importlib.util,io,json,sys,tempfile,unittest,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import audit_mrl_group_splits as m
NUMPY=importlib.util.find_spec('numpy') is not None

def cache_keys(n):return [m.stable(['synthetic',i]) for i in range(n)]
class MRLGroupTests(unittest.TestCase):
 def test_unknown_gene_is_not_assumed_homology_clear(self):
  q,_,_=m.audit_split(['unknown','unknown'],cache_keys(2),[],{0:'train',1:'test'})
  self.assertEqual(q['gene_overlap']['shared_keys'],1);self.assertEqual(q['unmapped_gene_annotations_shared'],1);self.assertFalse(q['independent_RNA_homology_checked']);self.assertFalse(q['admission_gate_pass'])
 @unittest.skipUnless(NUMPY,'optional numpy')
 def test_author_row_fallback_can_share_same_unknown_gene(self):
  genes=['unknown']*10;train,test=m.reproduce_author_two_way(genes,[],.5,2541)
  self.assertEqual(len(train),5);self.assertEqual(len(test),5);self.assertEqual(sorted(train+test),list(range(10)))
  a={i:'train' if i in train else 'test' for i in range(10)};q,_,_=m.audit_split(genes,cache_keys(10),[],a)
  self.assertEqual(q['pairwise_overlap_counts']['train__test']['shared_gene_keys'],1)
 @unittest.skipUnless(NUMPY,'optional numpy')
 def test_known_author_groups_never_separated(self):
  genes=['A','A','B','B','C','C','D','D'];pairs=[('A',1),('B',1),('C',2),('D',3)];train,test=m.reproduce_author_two_way(genes,pairs,.5,2541)
  self.assertFalse(set(train)&set(test));self.assertTrue(set(range(4))<=set(train) or set(range(4))<=set(test))
 def test_custom_unknown_same_gene_is_joined(self):
  groups=m.custom_groups(['x','x','y'],cache_keys(3),[]);self.assertIn([0,1],groups);self.assertEqual(sum(map(len,groups)),3)
 def test_custom_cross_gene_exact_input_is_joined(self):
  groups=m.custom_groups(['A','B','C'],['same','same','different'],[]);self.assertIn([0,1],groups)
 def test_custom_known_homology_is_joined(self):
  groups=m.custom_groups(['A','B','C'],cache_keys(3),[('A',12),('B',12)]);self.assertIn([0,1],groups)
 def test_ambiguous_gene_groups_bridge_conservatively(self):
  groups=m.custom_groups(['A','B','C'],cache_keys(3),[('A',1),('A',2),('B',1),('C',2)]);self.assertEqual(groups,[[0,1,2]])
 def test_no_gene_casefold_or_implicit_alias_merge(self):
  groups=m.custom_groups(['Abc','ABC'],cache_keys(2),[]);self.assertEqual(len(groups),2)
 def test_empty_gene_blocks_not_dropped(self):
  with self.assertRaises(ValueError):m.custom_groups([''],cache_keys(1),[])
 def test_stable_assignment_covers_all_rows_and_respects_groups(self):
  groups=[[0,1],[2],[3],[4],[5],[6],[7],[8],[9]];a,k=m.assign_custom(groups,10,'a'*64)
  self.assertEqual(a,m.assign_custom(groups,10,'a'*64)[0]);self.assertEqual(a[0],a[1]);self.assertEqual(k[0],k[1]);self.assertEqual(set(a),set(range(10)))
 def test_custom_observed_constraints_zero_overlap(self):
  genes=['A','A','B','C','D','E','F','G','H','I'];keys=['k0','k1','k2','k2']+cache_keys(6);pairs=[('A',1),('D',1)]
  groups=m.custom_groups(genes,keys,pairs);a,_=m.assign_custom(groups,10,'a'*64);q,_,_=m.audit_split(genes,keys,pairs,a)
  self.assertEqual(q['gene_overlap']['shared_keys'],0);self.assertEqual(q['exact_input_overlap']['shared_keys'],0);self.assertEqual(q['known_homology_groups_shared'],0);self.assertFalse(q['evaluation_enabled'])
 def test_assignment_does_not_take_label_values(self):
  import inspect
  self.assertEqual(list(inspect.signature(m.assign_custom).parameters),['components','n','source_sha','seed'])
 def make_zip(self,root,text,name='homology_maps_homologene/human_homology_map.csv'):
  p=root/'map.zip'
  with zipfile.ZipFile(p,'w') as z:z.writestr(name,text)
  return p
 def test_original_empty_index_header_preserved_not_repaired(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.make_zip(Path(d),',gene_name,gene_group\n0,A,0\n1,B,1\n');pairs,info=m.read_map(p);self.assertEqual(pairs,[('A',0),('B',1)]);self.assertEqual(info['header_columns'][0],'')
 def test_duplicate_ragged_and_bad_group_rejected(self):
  examples=['gene_name,gene_name,gene_group\nA,B,1\n','gene_name,gene_group\nA\n','gene_name,gene_group\nA,1.5\n','gene_name,gene_group\nA,NaN\n']
  for text in examples:
   with self.subTest(text=text),tempfile.TemporaryDirectory() as d:
    with self.assertRaises(ValueError):m.read_map(self.make_zip(Path(d),text))
 def test_zip_escape_rejected_without_extraction(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):m.read_map(self.make_zip(Path(d),'gene_name,gene_group\nA,1\n','../human_homology_map.csv'))
 def test_immutable_output_and_pairwise_counts(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'out.tsv';h=m.write_tsv(p,[{'row':1}],['row']);self.assertEqual(h,m.write_tsv(p,[{'row':1}],['row']))
   with self.assertRaises(ValueError):m.write_tsv(p,[{'row':2}],['row'])
  q,_,_=m.audit_split(['A','A','B'],['same','same','other'],[],{0:'train',1:'test',2:'validation'})
  self.assertEqual(q['pairwise_overlap_counts']['train__test'],{'shared_gene_keys':1,'shared_exact_input_keys':1})
if __name__=='__main__':unittest.main()
