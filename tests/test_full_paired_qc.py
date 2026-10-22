import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from qc_paired_full import identity,row_issues,connect,overlaps

class FullPairedQCTests(unittest.TestCase):
 def test_order_and_tu_preserved(self):
  a={'gene':'ACGT','noncodingRNA':'ACGU','label':'1'};b={**a,'gene':'ACGU','noncodingRNA':'ACGT'}
  self.assertNotEqual(identity(a),identity(b));self.assertEqual(row_issues(a),[])
 def test_invalid_label_and_empty(self):
  self.assertIn('EMPTY_PAIR',row_issues({'gene':'','noncodingRNA':'A','label':'2'}))
 def test_cross_split_and_mirror_not_double_counted(self):
  with tempfile.TemporaryDirectory() as temp:
   db=connect(Path(temp)/'samples.sqlite');key=identity({'gene':'ACGT','noncodingRNA':'AAAA'})
   for aid,split in [('A','train'),('B','test'),('C','test')]:db.execute('INSERT INTO samples VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)',(aid,'same',split,'a'*64,1,key,b'x','1','g','m','[]'))
   db.commit();pairs,leak=overlaps(db)
   self.assertEqual(len(pairs),3);self.assertEqual(next(x for x in pairs if x['left_asset']=='B' and x['right_asset']=='C')['shared_exact_ordered_pairs'],1)
   self.assertEqual(leak,{'A','B','C'});db.close()
