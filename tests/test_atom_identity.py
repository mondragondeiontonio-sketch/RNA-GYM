import importlib.util,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from qc_atom_identity import check_block
@unittest.skipUnless(importlib.util.find_spec('gemmi'),'optional CIF parser unavailable')
class AtomIdentityTests(unittest.TestCase):
 def test_reused_serial_is_not_duplicate_molecular_atom(self):
  import gemmi
  text='''data_toy
loop_
_atom_site.id
_atom_site.Cartn_x
_atom_site.pdbx_PDB_model_num
_atom_site.label_asym_id
_atom_site.auth_asym_id
_atom_site.label_seq_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.label_comp_id
_atom_site.label_atom_id
_atom_site.label_alt_id
1 0 1 A A 1 1 ? A P .
1 1 1 A A 2 2 ? C P .
'''
  r=check_block(gemmi.cif.read_string(text)[0]);self.assertEqual(r['reused_serial_numbers'],1);self.assertEqual(r['duplicate_composite_atom_rows'],0)
