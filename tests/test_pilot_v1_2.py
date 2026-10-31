import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
NUMERIC=all(importlib.util.find_spec(x) for x in ["numpy","pyarrow","sklearn","scipy"])

@unittest.skipUnless(NUMERIC,"optional numerical dependencies")
class PilotProtocolTests(unittest.TestCase):
    def test_no_truncation_and_explicit_model_view(self):
        from tools.pilot_v1_2_data import sequence_view
        self.assertEqual(sequence_view("acgt")[0],"ACGU")
        self.assertIsNone(sequence_view("A"*1023)[0])
        self.assertIsNone(sequence_view("ACGN")[0])
        self.assertEqual(sequence_view("A"*1022)[1],None)

    def test_exact_and_gene_components(self):
        from tools.pilot_v1_2_data import group_rows
        r=[dict(record_id=str(i),sequence_hash=s,metadata=m) for i,(s,m) in enumerate([
            ("a",{"gene":"g1"}),("b",{"gene":"g1"}),("b",{"gene":"g2"}),("c",{})])]
        group_rows(r)
        self.assertEqual(len({x["biological_group"] for x in r[:3]}),1)
        self.assertNotEqual(r[0]["biological_group"],r[3]["biological_group"])

    def rows(self):
        return [dict(record_id=str(i),sequence_hash=str(i),biological_group=str(i),split_group=str(i),outer_fold=i%10,label=float(i),problem_type="regression") for i in range(240)]

    def test_frozen_outer_test_and_validation_only_from_train_pool(self):
        from tools.pilot_v1_2_data import role_split
        r=self.rows(); roles=role_split(r,3,42)
        self.assertEqual({x["record_id"] for x in r if x["outer_fold"]==3},{k for k,v in roles.items() if v=="test"})
        self.assertEqual(roles,role_split(r,3,42))
        self.assertEqual(roles,role_split([dict(x,label=-x["label"]) for x in r],3,42))

    def test_cross_fold_biological_group_is_rejected(self):
        from tools.pilot_v1_2_data import role_split
        r=self.rows();r[1]["biological_group"]=r[0]["biological_group"]
        with self.assertRaisesRegex(ValueError,"CROSS_ROLE_LEAKAGE"):
            role_split(r,0,42)

    def test_constant_metric_stays_na(self):
        import numpy as np
        from tools.pilot_v1_2_scoring import metric_values
        r=metric_values(np.arange(10.),np.ones(10),"regression",[])
        self.assertIsNone(r["Spearman"])
        self.assertIn("Spearman",r["undefined_reasons"])
        self.assertIsNotNone(r["MAE"])

    def test_negative_dms_does_not_fabricate_ndcg_relevance(self):
        import numpy as np
        from tools.pilot_v1_2_scoring import metric_values
        r=metric_values(np.arange(-5.,5.),np.arange(10.),"regression",[])
        self.assertIsNone(r["NDCG"])

    def test_family_classification_has_declared_support(self):
        import numpy as np
        from tools.pilot_v1_2_scoring import metric_values
        r=metric_values(np.array([0,1,0,1]),np.array([[.9,.1],[.1,.9],[.8,.2],[.2,.8]]),"classification",["a","b"])
        self.assertEqual(r["Macro-F1"],1.)
        self.assertEqual(r["class_support"]["a"]["positive"],2)

    def test_missing_test_class_is_na_not_zero(self):
        import numpy as np
        from tools.pilot_v1_2_scoring import metric_values
        r=metric_values(np.array([0,0,0]),np.array([[.8,.2],[.9,.1],[.7,.3]]),"classification",["a","b"])
        self.assertIsNone(r["Macro-F1"])
        self.assertIn("Macro-F1",r["undefined_reasons"])

    def test_fixed_budget_no_utrlm_or_full_ft(self):
        c=json.loads((ROOT/"configs/rnafm_hf_pilot_v1_2.yaml").read_text())
        self.assertEqual(c["model"],"RNA-FM-HF");self.assertEqual(c["gpu_count"],1)
        self.assertEqual(c["encoder"],"frozen");self.assertEqual(c["hpo_trials"],0)
        self.assertTrue(c["no_test_tuning"]);self.assertFalse(c["compute_universal_score"])
        self.assertEqual(c["outer_folds_10"],[0,3,7])

    @unittest.skipUnless((ROOT/"runs/rnagym_rnafm_hf_pilot_v1_2/technical_status_final.tsv").exists(),"private local run evidence not published")
    def test_repair_status_not_overwritten(self):
        from tools.build_arena_v1 import table
        rows=table(ROOT/"runs/rnagym_rnafm_hf_pilot_v1_2/technical_status_final.tsv")
        self.assertEqual(len(rows),277)
        self.assertEqual(sum(r["status"]=="PASSED_TECHNICAL_SMOKE" for r in rows),261)
        for unit in ["QC:PROBING_RMDB_s40","QC:WANG_Archivell_n3864_dataset"]:
            r=next(r for r in rows if r["dataset_id"]==unit)
            self.assertEqual(r["status"],"PASSED_TECHNICAL_SMOKE")
            self.assertEqual(r["attempt_count"],"2")

    @unittest.skipUnless((ROOT/"runs/rnagym_rnafm_hf_pilot_v1_2/prepared_panel.json").exists(),"private local data not published")
    def test_every_selected_protocol_has_independent_real_test(self):
        from tools.build_arena_v1 import load,table,sha
        panel=load(ROOT/"runs/rnagym_rnafm_hf_pilot_v1_2/prepared_panel.json")
        self.assertEqual(panel["selected_n"],8)
        for path in panel["datasets"]:
            m=load(ROOT/path)
            self.assertGreater(m["n_eligible"],100)
            self.assertFalse(m["formal_admitted"])
            for entry in m["protocols"]:
                p=ROOT/entry["split_path"]; self.assertEqual(sha(p),entry["split_hash"])
                rows=table(p)
                for field in ["sequence_hash","biological_group","split_group"]:
                    groups={}
                    for r in rows:groups.setdefault(r[field],set()).add(r["role"])
                    self.assertTrue(all(len(x)==1 for x in groups.values()))
                self.assertGreater(entry["counts"]["test"],10)

if __name__=="__main__":unittest.main()
