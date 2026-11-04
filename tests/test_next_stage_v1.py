import json
import unittest
try:
    import numpy as np
except ImportError:
    np=None
from tools.next_stage_taxonomy import ROOT, OUT, CATEGORIES, read_table
if np is not None:
    from tools.structure_anchor_v1 import labels_from_columns


def columns():
    n=8
    d={"_entity_poly.pdbx_seq_one_letter_code_can":["ACGUACGU"]}
    values=dict(label_seq_id=[str(i+1) for i in range(n)],auth_seq_id=[str(i+11) for i in range(n)],label_comp_id=list("ACGUACGU"),label_atom_id=["C4\'"]*n,label_asym_id=["X"]*n,auth_asym_id=["A"]*n,label_alt_id=["."]*n,pdbx_PDB_ins_code=["?"]*n,Cartn_x=[str(i) for i in range(n)],Cartn_y=["0"]*n,Cartn_z=["0"]*n,occupancy=["1"]*n,pdbx_PDB_model_num=["1"]*n)
    d.update({"_atom_site."+k:v for k,v in values.items()}); return d


class TaxonomyV1Tests(unittest.TestCase):
    def test_no_renumber_and_exact_hierarchy(self):
        old=json.loads((ROOT/"configs/task_taxonomy_v1.yaml").read_text()); new=json.loads((ROOT/"configs/task_taxonomy_v1_20261102.yaml").read_text())
        self.assertEqual({t["task_id"] for t in old["tasks"]},{t["task_id"] for t in new["tasks"]})
        self.assertEqual(len(new["registry_level1_domains"]),4); self.assertEqual(len(new["level2_categories"]),8)
        self.assertFalse(new["universal_score_enabled"]); self.assertFalse(new["human_admitted"])
    @unittest.skipUnless((OUT/"taxonomy_review_76.tsv").exists(),
                         "local taxonomy evidence not shipped")
    def test_all_reviews_have_dispositions_and_reasons(self):
        rows=read_table(OUT/"taxonomy_review_76.tsv"); self.assertEqual(len(rows),76)
        self.assertTrue(all(r["status"] in ["MAPPED","SPLIT_REQUIRED","EVIDENCE_HOLD","EXCLUDED"] and r["reason"] and r["human_review_status"]=="NOT_REVIEWED" for r in rows))
        self.assertEqual(len(read_table(ROOT/"data/registries/taxonomy_v1_20261102_crosswalk.tsv")),198)
    def test_label_identity_contracts(self):
        tasks={t["task_id"]:t for t in json.loads((ROOT/"configs/task_taxonomy_v1_20261102.yaml").read_text())["tasks"]}
        self.assertEqual(tasks["MRL_EXACT"]["sequence_source_region"],"5UTR")
        self.assertIn("NOT_AUTOMATIC_CDS",tasks["MRL_PROXY"]["sequence_source_region"])
        self.assertIn("SEPARATE_ENDPOINT",tasks["HALF_LIFE"]["label_variants"][1])
        self.assertNotEqual(tasks["CRISPR_ON_TARGET"]["input_schema_id"],tasks["RBP_BINDING"]["input_schema_id"])


@unittest.skipIf(np is None, "optional numpy unavailable")
class StructureAnchorTests(unittest.TestCase):
    def test_missing_positions_not_deleted_and_near_pairs_masked(self):
        d=columns(); d["_atom_site.occupancy"][3]="0"
        seq,xyz,dist,c,m,rows,a=labels_from_columns(d)
        self.assertEqual(len(seq),8); self.assertFalse(m[3].any()); self.assertTrue(np.isnan(dist[3]).all())
        self.assertFalse(np.diag(m).any()); self.assertFalse(m[0,3]); self.assertTrue(m[0,4]); self.assertEqual(dist[0,4],4); self.assertEqual(c[0,4],1)
        self.assertEqual(rows[0]["auth_seq_id"],"11")
    def test_shifted_label_fails_not_silent_realignment(self):
        d=columns(); d["_atom_site.label_seq_id"][0]="2"
        with self.assertRaisesRegex(ValueError,"RESIDUE_SEQUENCE_MISMATCH"): labels_from_columns(d)
    def test_unknown_modified_parent_mask_and_known_parent(self):
        d=columns(); d["_atom_site.label_comp_id"][0]="MOD"
        self.assertFalse(labels_from_columns(d)[4][0].any())
        d["_chem_comp.id"]=["MOD"]; d["_chem_comp.mon_nstd_parent_comp_id"]=["A"]
        self.assertTrue(labels_from_columns(d)[4][0,4])
    def test_altloc_equal_occupancy_distinct_coordinates_mask(self):
        d=columns()
        for key in list(d):
            if key.startswith("_atom_site."): d[key].append(d[key][0])
        d["_atom_site.Cartn_x"][-1]="99"; d["_atom_site.label_alt_id"][-1]="B"
        self.assertFalse(labels_from_columns(d)[4][0].any())
        d["_atom_site.occupancy"][-1]="0.5"
        self.assertTrue(labels_from_columns(d)[4][0,4])
    def test_contact_boundary_is_strict_and_multichain_refused(self):
        d=columns(); d["_atom_site.Cartn_x"][4]="8"
        self.assertEqual(labels_from_columns(d)[3][0,4],0)
        d["_atom_site.label_asym_id"][0]="Y"
        with self.assertRaisesRegex(ValueError,"MULTICHAIN"): labels_from_columns(d)
