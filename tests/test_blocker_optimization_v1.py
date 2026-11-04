import csv
import hashlib
import json
from pathlib import Path
import unittest
from tools.danio_gene_candidate_v1_1 import build_assignments, ROOT, OUT, SPLIT


class CandidateGeneSplitTests(unittest.TestCase):
    def fixture(self):
        return [dict(record_id="a",sequence_sha256="same",source_insert_ids=["ENSDARG0001_tx"],source_genes=["g1"]),dict(record_id="b",sequence_sha256="same",source_insert_ids=["ENSDARG0002_tx"],source_genes=["g2"]),dict(record_id="c",sequence_sha256="other",source_insert_ids=["ENSDARG0002_tx"],source_genes=["g2"])]
    def test_connected_gene_and_sequence_components(self):
        result=build_assignments(self.fixture())
        self.assertEqual(len({r["group_id"] for r in result}),1); self.assertEqual(len({r["outer_fold"] for r in result}),1)
    def test_label_blind_and_order_independent(self):
        rows=self.fixture(); first={r["record_id"]:r for r in build_assignments(rows)}
        for i,r in enumerate(rows): r["label"]=1000*i; r["unread_test_label"]=-999
        second={r["record_id"]:r for r in build_assignments(list(reversed(rows)))}
        self.assertEqual(first,second)
    def test_missing_gene_identity_quarantined_not_faked(self):
        result=build_assignments([dict(record_id="z",sequence_sha256="unique",source_insert_ids=["unknown"],source_genes=["NA"])])
        self.assertEqual(result[0]["outer_fold"],-1)


@unittest.skipUnless((OUT/"danio_gene_candidate_summary.json").exists(),"local scientific evidence not shipped")
class BlockerArtifactTests(unittest.TestCase):
    def test_real_candidate_all_ten_folds_and_identity(self):
        result=json.loads((OUT/"danio_gene_candidate_summary.json").read_text())
        self.assertEqual(result["n_records"],18021); self.assertEqual(result["n_groups"],10257)
        self.assertEqual(len(result["audits"]),10)
        self.assertTrue(all(r["cross_role_gene_sequence_component_keys"]==0 for r in result["audits"]))
        self.assertEqual(hashlib.sha256((SPLIT/"assignments.tsv").read_bytes()).hexdigest(),result["assignments_sha256"])
        self.assertFalse(result["human_approved"])
    def test_source_mappings_exact_without_admission(self):
        a=json.loads((OUT/"andreasson_kcat_binding.json").read_text()); self.assertEqual(a["kcat_exact_matches"],7343); self.assertEqual(a["ambiguous_sequence_joins"],0); self.assertFalse(a["scientific_admitted"])
        d=json.loads((OUT/"danio_source_binding.json").read_text()); self.assertEqual(d["label_compatible_n"],18021); self.assertEqual(d["max_all_alias_abs_error"],0); self.assertEqual(d["multiple_compatible_source_rows_n"],0)
        self.assertTrue(all(r["train_test_shared_genes"]>0 for r in d["gene_audit"]))
    def test_candidate_panel_and_review_still_not_admitted(self):
        old=json.loads((ROOT/"configs/benchmark_panel_candidate_20261102_v1.yaml").read_text()); new=json.loads((ROOT/"configs/benchmark_panel_candidate_20261102_v1_1.yaml").read_text())
        self.assertEqual([r["dataset"] for r in old["members"]],[r["dataset"] for r in new["members"]])
        self.assertFalse(any(new["formal_scoring_sets"].values())); self.assertFalse(new["universal_score_enabled"])
        packs=list((OUT/"scientific_evidence_v1_1").glob("*/evidence_update.json")); self.assertEqual(len(packs),9)
        self.assertTrue(all(json.loads(p.read_text())["authorized_reviewer_id"] is None for p in packs))
    def test_retry_request_is_not_an_authorized_scope(self):
        request=json.loads((OUT/"lora_retry_request.json").read_text()); policy=json.loads((ROOT/"configs/compute_budget_policy_v1.json").read_text())
        self.assertFalse(request["executed"]); self.assertFalse(request["reset_old_scope"])
        self.assertNotIn(request["proposed_scope"],policy["authorized_scopes"])
    def test_learned_structure_predictions_replay_from_parameters(self):
        try:
            import numpy as np
            from tools.structure_learned_anchor_v1_1 import features
        except ImportError: self.skipTest("optional scientific dependencies unavailable")
        directory=OUT/"structure_learned_anchor"; params=json.loads((directory/"model_parameters.json").read_text())
        train=json.loads((directory/"train_alignment_audit.json").read_text()); groups={r["group_id"] for r in train}
        old=ROOT/"runs/20261102_taxonomy_admission_adaptation_v1/structure_anchor"
        for r in csv.DictReader((directory/"metrics.tsv").open(),delimiter="\t"):
            self.assertNotIn(r["group_id"],groups)
            labels=np.load(old/(r["entry"]+".npz"),allow_pickle=False); predicted=np.load(directory/(r["entry"]+"_predictions.npz"),allow_pickle=False)
            x=features(str(labels["sequence"]),predicted["pairs"]); z=(x-np.asarray(params["scaler_mean"]))/np.asarray(params["scaler_scale"])
            np.testing.assert_allclose(predicted["distance"],z@np.asarray(params["ridge_coef"])+params["ridge_intercept"])
            logits=z@np.asarray(params["contact_coef"])[0]+params["contact_intercept"][0]
            np.testing.assert_allclose(predicted["contact_probability"],1/(1+np.exp(-logits)))
