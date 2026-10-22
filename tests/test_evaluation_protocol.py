"""Synthetic protocol tests only: never read raw_cache or download weights."""
import copy
import contextlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import evaluation_protocol as ep


class EvaluationProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rnagym_protocol_")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def fixture(self, baseline="mean_null", rows=None, splits=None):
        config = ep.toy_config(baseline)
        originals, original_splits = ep.toy_data(config["problem_type"], config["input_mode"])
        rows = originals if rows is None else rows
        splits = original_splits if splits is None else splits
        input_path = self.base / (baseline + ".jsonl")
        input_path.write_bytes(b"".join(ep.canonical_bytes(r) for r in rows))
        split_path = self.base / (baseline + "_splits.json")
        split_path.write_bytes(ep.canonical_bytes(splits))
        return config, input_path, split_path

    def prepared(self, baseline="mean_null"):
        return ep.prepare(*self.fixture(baseline))

    def test_null_prepare_run_evaluate_actual_metrics(self):
        prepared = self.prepared()
        result = ep.run(prepared)
        expected = sum(r["label"] for r in prepared["rows"][:32]) / 32
        self.assertAlmostEqual(result["model"]["value"], expected)
        self.assertEqual(len(result["predictions"]), 16)
        metrics = ep.evaluate(prepared, result["predictions"])
        self.assertEqual(metrics["metrics"]["test"]["n"], 8)
        self.assertFalse(metrics["rankable_real_result"])
        self.assertEqual(metrics["scope"], "SYNTHETIC_PROTOCOL_ONLY")
        self.assertIsNone(metrics["metrics"]["test"]["spearman"])

    def test_median_majority_prevalence(self):
        for baseline in ("median_null", "majority_null", "prevalence_null"):
            with self.subTest(baseline=baseline):
                prepared = self.prepared(baseline)
                model = ep.fit(prepared)
                self.assertEqual(model["fit_n"], 32)
                if baseline == "majority_null":
                    self.assertEqual(model["value"], 1.0)  # explicit tie policy
                elif baseline == "prevalence_null":
                    self.assertEqual(model["value"], 0.5)

    def test_null_fits_train_only(self):
        prepared = self.prepared()
        model = ep.fit(prepared)
        other = copy.deepcopy(prepared)
        for r in other["rows"][32:]:
            r["label"] = 1e9
        self.assertEqual(model, ep.fit(other))

    def test_sklearn_models_train_only_parameters_vocab_scaler(self):
        if not ep.importlib.util.find_spec("sklearn"):
            self.skipTest("optional scikit-learn absent")
        for baseline in ep.SKLEARN_BASELINES:
            with self.subTest(baseline=baseline):
                prepared = self.prepared(baseline)
                model = ep.fit(prepared)
                other = copy.deepcopy(prepared)
                for row in other["rows"][32:]:
                    row["label"] = (1 - row["label"]) if model["problem_type"] != "regression" else 1e8
                    if "sequence" in row:
                        row["sequence"] = "U" * 100
                    else:
                        row["mirna_sequence"] = "U" * 30
                        row["target_sequence"] = "C" * 200
                self.assertEqual(model, ep.fit(other))
                output = ep.run(prepared)
                self.assertTrue(all(math.isfinite(p["prediction"]) for p in output["predictions"]))
                self.assertEqual(ep.evaluate(prepared, output["predictions"])["status"], "VERIFIED")

    def test_train_only_vocabulary_drops_heldout_only_words(self):
        if not ep.importlib.util.find_spec("sklearn"):
            self.skipTest("optional scikit-learn absent")
        prepared = self.prepared("sequence_kmer_logistic")
        for r in prepared["rows"][:32]:
            r["sequence"] = r["sequence"].replace("U", "A")
        for r in prepared["rows"][32:]:
            r["sequence"] = "UUUUUUUU"
        model = ep.fit(prepared)
        self.assertNotIn("UU", model["vocabulary"])
        self.assertTrue(all("U" not in k for k in model["vocabulary"]))

    def test_seed_direction_and_exact_positions(self):
        prepared = self.prepared("pair_seed_match")
        model = ep.fit(prepared)
        row = {"mirna_sequence": "AACGUACGAAAA", "target_sequence": "UUUCGUACGUAAA"}
        self.assertEqual(ep.predict(model, row), 1.0)
        row["target_sequence"] = "ACGUACG"  # not reverse complement
        self.assertEqual(ep.predict(model, row), 0.0)
        outputs = ep.run(prepared)
        self.assertEqual(ep.evaluate(prepared, outputs["predictions"])["metrics"]["test"]["accuracy"], 1)

    def test_negative_controls_ignore_other_role(self):
        if not ep.importlib.util.find_spec("sklearn"):
            self.skipTest("optional scikit-learn absent")
        for baseline, changed in (("pair_mirna_only", "target_sequence"),
                                  ("pair_target_only", "mirna_sequence")):
            prepared = self.prepared(baseline)
            model = ep.fit(prepared)
            row = prepared["rows"][-1]
            other = {**row, changed: "A" * 90}
            self.assertEqual(ep.predict(model, row), ep.predict(model, other))

    def test_cross_split_same_sequence_rejected(self):
        rows, splits = ep.toy_data()
        rows[-1]["sequence"] = rows[0]["sequence"]
        with self.assertRaisesRegex(ep.ProtocolError, "CROSS_SPLIT_IDENTICAL_INPUT"):
            ep.prepare(*self.fixture(rows=rows, splits=splits))

    def test_cross_split_same_pair_even_different_assay_rejected(self):
        rows, splits = ep.toy_data("binary_classification", "rna_pair")
        for field in ("mirna_sequence", "target_sequence"):
            rows[-1][field] = rows[0][field]
        rows[-1]["assay_id"] = "DIFFERENT_SYNTHETIC_CONDITION"
        with self.assertRaisesRegex(ep.ProtocolError, "CROSS_SPLIT_IDENTICAL_INPUT"):
            ep.prepare(*self.fixture("pair_seed_match", rows, splits))

    def test_same_split_different_condition_preserved_no_silent_merge(self):
        rows, splits = ep.toy_data("binary_classification", "rna_pair")
        for field in ("mirna_sequence", "target_sequence", "mirna_id", "target_id"):
            rows[1][field] = rows[0][field]
        rows[1]["condition_id"] = "OTHER_SYNTHETIC_CONDITION"
        rows[1]["label"] = 1 - rows[0]["label"]
        prepared = ep.prepare(*self.fixture("pair_seed_match", rows, splits))
        self.assertEqual(len(prepared["rows"]), 48)
        self.assertEqual(ep.input_key(rows[0], "rna_pair"), ep.input_key(rows[1], "rna_pair"))
        self.assertNotEqual(ep.observation_key(rows[0], "rna_pair"), ep.observation_key(rows[1], "rna_pair"))

    def test_group_disjointness(self):
        config, ip, sp = self.fixture()
        rows = [json.loads(s) for s in ip.read_text().splitlines()]
        for r in rows:
            r["family"] = r["observation_id"]
        rows[-1]["family"] = rows[0]["family"]
        ip.write_bytes(b"".join(ep.canonical_bytes(r) for r in rows))
        config["group_fields"] = ["family"]
        with self.assertRaisesRegex(ep.ProtocolError, "CROSS_SPLIT_PREREGISTERED_GROUP"):
            ep.prepare(config, ip, sp)

    def test_pair_identity_cannot_omit_target_id(self):
        rows, splits = ep.toy_data("binary_classification", "rna_pair")
        del rows[0]["target_id"]
        with self.assertRaisesRegex(ep.ProtocolError, "AMBIGUOUS_PAIR_IDENTITY"):
            ep.prepare(*self.fixture("pair_seed_match", rows, splits))

    def test_no_implicit_T_U_or_case_conversion(self):
        rows, splits = ep.toy_data()
        for bad in ("ACGT", "acgu"):
            rows[0]["sequence"] = bad
            with self.assertRaisesRegex(ep.ProtocolError, "EXACT_ALPHABET"):
                ep.prepare(*self.fixture(rows=rows, splits=splits))
        config, ip, sp = self.fixture()
        config["sequence_transform"] = "U_TO_T"
        with self.assertRaisesRegex(ep.ProtocolError, "UNIMPLEMENTED_SEQUENCE_TRANSFORM"):
            ep.prepare(config, ip, sp)

    def test_split_extra_missing_duplicate_ids(self):
        rows, splits = ep.toy_data()
        for mode in ("extra", "missing", "duplicate_observation"):
            other_rows, other_splits = copy.deepcopy(rows), dict(splits)
            if mode == "extra":
                other_splits["nonexistent"] = "test"
            elif mode == "missing":
                del other_splits["toy_000"]
            else:
                other_rows[1]["observation_id"] = "toy_000"
            with self.subTest(mode=mode), self.assertRaises(ep.ProtocolError):
                ep.prepare(*self.fixture(rows=other_rows, splits=other_splits))

    def test_nonfinite_invalid_binary_labels_and_duplicate_json_keys(self):
        rows, splits = ep.toy_data()
        rows[0]["label"] = None
        with self.assertRaisesRegex(ep.ProtocolError, "LABEL_NOT_FINITE"):
            ep.prepare(*self.fixture(rows=rows, splits=splits))
        with self.assertRaisesRegex(ep.ProtocolError, "DUPLICATE_JSON_KEY"):
            ep.strict_json_loads('{"x":1,"x":2}')
        with self.assertRaisesRegex(ep.ProtocolError, "NONFINITE_JSON"):
            ep.strict_json_loads('{"x":NaN}')
        with self.assertRaisesRegex(ep.ProtocolError, "INVALID_BINARY"):
            ep.scalar_metrics([0, 2], [0.1, 0.9], "binary_classification")

    def test_actual_metrics_ties_and_undefined_cases(self):
        metrics = ep.scalar_metrics([0, 1, 0, 1], [0.5] * 4, "binary_classification")
        self.assertEqual(metrics["auroc"], 0.5)
        self.assertEqual(metrics["accuracy"], 0.5)
        self.assertAlmostEqual(metrics["log_loss"], math.log(2))
        self.assertIsNone(ep.scalar_metrics([1, 1], [0.2, 0.3], "binary_classification")["auroc"])
        metrics = ep.scalar_metrics([1.0, 2.0, 3.0], [2.0, 2.0, 2.0], "regression")
        self.assertAlmostEqual(metrics["mse"], 2 / 3)
        self.assertIsNone(metrics["spearman"])
        self.assertEqual(ep.scalar_metrics([0, 1], [0.1, 0.9], "binary_classification")["auroc"], 1)
        self.assertEqual(ep.scalar_metrics([0, 1], [0.9, 0.1], "binary_classification")["auroc"], 0)

    def test_evaluate_rejects_misaligned_or_missing_predictions(self):
        prepared = self.prepared()
        predictions = ep.run(prepared)["predictions"]
        for altered in (predictions[:-1], predictions + predictions[:1],
                        [{**predictions[0], "split": "train"}] + predictions[1:],
                        [{**predictions[0], "prediction": float("nan")}] + predictions[1:]):
            with self.assertRaises(ep.ProtocolError):
                ep.evaluate(prepared, altered)

    def test_real_tasks_fail_closed_even_if_state_claims_admitted(self):
        config, ip, sp = self.fixture()
        config.update(task_id="T0001", synthetic=False, enabled=False)
        with self.assertRaisesRegex(ep.ProtocolError, "REAL_TASK_DISABLED"):
            ep.create_run(config, ip, sp, self.base / "runs")
        with self.assertRaises(ep.ProtocolError):
            ep.prepare(config, ip, sp)
        config.update(enabled=True, admission_state="ADMITTED", canonical_assay_id="SYNTHETIC_NOT_AN_ASSAY")
        with self.assertRaisesRegex(ep.ProtocolError, "ADMITTED_EVIDENCE_REQUIRED"):
            ep.create_run(config, ip, sp, self.base / "runs")
        self.assertFalse((self.base / "runs").exists())

    def test_real_claim_with_empty_gate_evidence_rejected(self):
        config, ip, sp = self.fixture()
        evidence = self.base / "not_an_approval.json"
        evidence.write_text("{}")
        config.update(task_id="T0001", synthetic=False, enabled=True,
                      admission_state="ADMITTED", admission_evidence=str(evidence))
        with self.assertRaisesRegex(ep.ProtocolError, "ADMISSION_GATE_REJECTED"):
            ep.create_run(config, ip, sp, self.base / "not_created")
        self.assertFalse((self.base / "not_created").exists())

    def test_optional_sklearn_failure_blocked_not_fallback_fake_score(self):
        prepared = self.prepared("sequence_stats_ridge")
        with mock.patch.dict(sys.modules, {"sklearn": None}):
            with self.assertRaisesRegex(ep.ProtocolError, "BLOCKED_DEPENDENCY"):
                ep.fit(prepared)

    def test_concurrent_run_lock_rejects_second_worker(self):
        config, ip, sp = self.fixture()
        directory = ep.create_run(config, ip, sp, self.base / "runs")
        with ep._run_lock(directory):
            with self.assertRaisesRegex(ep.ProtocolError, "RUN_ALREADY_ACTIVE"):
                ep.advance(directory)

    def test_crash_orphan_complete_artifact_reused(self):
        config, ip, sp = self.fixture()
        directory = ep.create_run(config, ip, sp, self.base / "runs")
        metadata = ep._prepare_inputs(config, ip, sp)["metadata"]
        ep.write_immutable(directory / "prepared.json", metadata)
        self.assertEqual(ep.advance(directory)["stage"], "PREPARED")
        self.assertEqual(ep.read_json(directory / "prepared.json"), metadata)

    def test_smoke_executes_real_synthetic_work_and_writes_summary(self):
        summary = ep.smoke(self.base / "smoke")
        self.assertEqual(summary["rankable_real_results"], 0)
        self.assertEqual(summary["real_admitted_tasks"], 0)
        self.assertEqual(len(summary["runs"]), 10)
        self.assertTrue(Path(summary["summary_path"]).is_file())
        for run in summary["runs"]:
            if run["status"] == "VERIFIED":
                self.assertEqual(run["metrics"]["test"]["n"], 8)
                directory = Path(summary["summary_path"]).parent / run["run_id"]
                self.assertEqual(run["metrics_sha256"], ep.sha256_file(directory / "metrics.json"))
        expected = 10 if ep.importlib.util.find_spec("sklearn") else 5
        self.assertEqual(summary["verified_toy_runs"], expected)

    def test_modality_and_resource_contracts_fail_closed(self):
        config, ip, sp = self.fixture()
        config["problem_type"] = "binary_classification"
        with self.assertRaisesRegex(ep.ProtocolError, "MODALITY_OR_LABEL"):
            ep.prepare(config, ip, sp)
        config = ep.toy_config("mean_null")
        config["max_rows"] = 3
        with self.assertRaisesRegex(ep.ProtocolError, "CPU_ROW_BUDGET"):
            ep.prepare(config, ip, sp)
        config["max_rows"] = ep.MAX_ROWS + 1
        with self.assertRaises(ep.ProtocolError):
            ep.prepare(config, ip, sp)

    def test_immutable_run_stage_resume_hashes_and_no_refit(self):
        config, ip, sp = self.fixture()
        directory = ep.create_run(config, ip, sp, self.base / "runs", run_id="toy_bound_run")
        first = ep.advance(directory, "prepare")
        self.assertEqual(first["stage"], "PREPARED")
        self.assertEqual(first, ep.advance(directory, "prepare"))
        with self.assertRaisesRegex(ep.ProtocolError, "PREREQUISITE_STAGE"):
            ep.advance(directory, "evaluate")
        ep.advance(directory, "run")
        with mock.patch.object(ep, "fit", side_effect=AssertionError("must not refit")):
            result = ep.advance(directory, "evaluate")
            self.assertEqual(ep.advance(directory, "next"), result)
        for artifact, expected in result["artifacts"].items():
            self.assertEqual(ep.sha256_file(directory / artifact), expected)
        metrics = ep.read_json(directory / "metrics.json")
        self.assertEqual(metrics["provenance"]["run_id"], "toy_bound_run")
        self.assertEqual(metrics["provenance"]["input_sha256"], ep.sha256_file(ip))
        self.assertEqual(ep.read_json(directory / "request.json")["approval"]["admitted"], False)
        self.assertFalse(os.stat(directory / "metrics.json").st_mode & 0o222)

    def test_run_id_and_path_cannot_be_reused_or_traversed(self):
        config, ip, sp = self.fixture()
        ep.create_run(config, ip, sp, self.base, run_id="fixed")
        with self.assertRaises(FileExistsError):
            ep.create_run(config, ip, sp, self.base, run_id="fixed")
        with self.assertRaisesRegex(ep.ProtocolError, "INVALID_RUN_ID"):
            ep.create_run(config, ip, sp, self.base, run_id="../escape")

    def test_resume_rejects_changed_input_output_code_and_event(self):
        for variant in ("input", "output", "code", "event"):
            with self.subTest(variant=variant):
                config, ip, sp = self.fixture()
                directory = ep.create_run(config, ip, sp, self.base / variant)
                ep.advance(directory, "prepare")
                if variant == "input":
                    ip.write_text(ip.read_text() + "\n")
                elif variant == "output":
                    path = directory / "prepared.json"
                    path.chmod(0o644)
                    path.write_text("{}")
                elif variant == "event":
                    path = sorted((directory / "events").glob("*.json"))[-1]
                    path.chmod(0o644)
                    event = ep.read_json(path)
                    event["previous_event_sha256"] = "0" * 64
                    path.write_bytes(ep.canonical_bytes(event))
                else:
                    # Mutate request but not its checkpoint digest: always fail closed.
                    path = directory / "request.json"
                    path.chmod(0o644)
                    request = ep.read_json(path)
                    request["code_sha256"] = "0" * 64
                    path.write_bytes(ep.canonical_bytes(request))
                with self.assertRaises(ep.ProtocolError):
                    ep.advance(directory)

    def test_transient_retry_is_finite_and_audited(self):
        config, ip, sp = self.fixture()
        directory = ep.create_run(config, ip, sp, self.base / "runs")
        original = ep._prepare_inputs
        with mock.patch.object(ep, "_prepare_inputs", side_effect=[OSError("transient"), original(config, ip, sp)]), mock.patch.object(ep.time, "sleep"):
            checkpoint = ep.advance(directory, "prepare", retries=1)
        self.assertEqual(checkpoint["retry_count"], 1)
        self.assertEqual(checkpoint["attempts"]["PREPARED"], 2)
        events = [ep.read_json(p) for p in sorted((directory / "events").glob("*.json"))]
        self.assertTrue(any(e["event"] == "FAILED" for e in events))
        self.assertEqual(ep._verify_resume(directory)[1]["stage"], "PREPARED")

    def test_persistent_retry_budget_survives_restart(self):
        config, ip, sp = self.fixture()
        directory = ep.create_run(config, ip, sp, self.base / "runs")
        with mock.patch.object(ep, "_prepare_inputs", side_effect=OSError("outage")) as worker, mock.patch.object(ep.time, "sleep"):
            with self.assertRaises(OSError):
                ep.advance(directory, retries=1)
            self.assertEqual(worker.call_count, 2)
            with self.assertRaisesRegex(ep.ProtocolError, "RETRY_BUDGET_EXHAUSTED"):
                ep.advance(directory, retries=1)
            self.assertEqual(worker.call_count, 2)
        for invalid in (-1, 4, True):
            with self.assertRaises(ep.ProtocolError):
                ep.advance(directory, retries=invalid)

    def test_interrupt_has_recoverable_checkpoint(self):
        config, ip, sp = self.fixture()
        directory = ep.create_run(config, ip, sp, self.base / "runs")
        with mock.patch.object(ep, "_prepare_inputs", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                ep.advance(directory)
        self.assertEqual(ep.read_json(directory / "checkpoint.json")["status"], "INTERRUPTED")
        self.assertEqual(ep.advance(directory)["stage"], "PREPARED")

    def test_immutable_artifact_identical_reuse_not_overwrite(self):
        path = self.base / "artifact.json"
        digest = ep.write_immutable(path, {"x": 1})
        self.assertEqual(ep.write_immutable(path, {"x": 1}), digest)
        with self.assertRaisesRegex(ep.ProtocolError, "IMMUTABLE_ARTIFACT_CONFLICT"):
            ep.write_immutable(path, {"x": 2})

    def test_encoder_protocol_and_failures(self):
        rows = [{"observation_id": "toy", "sequence": "ACGU"}]
        output = [{"observation_id": "toy", "nucleotide_embeddings": [[1.0, 0.0]] * 4,
                   "valid_position_mask": [True] * 4}]
        self.assertEqual(ep.validate_encoding(rows, output)["dimension"], 2)
        for field, value in (("observation_id", "wrong"), ("valid_position_mask", [1] * 4),
                             ("nucleotide_embeddings", [[float("nan")]] * 4),
                             ("nucleotide_embeddings", [[1.0]] * 3)):
            other = [{**output[0], field: value}]
            with self.assertRaises(ep.ProtocolError):
                ep.validate_encoding(rows, other)

    def test_llm_agent_protocol_not_model_result(self):
        response = [{"observation_id": "toy", "prediction": 0.2}]
        self.assertEqual(ep.validate_llm_response(["toy"], response)["scope"], "PROTOCOL_VALIDATION_ONLY")
        with self.assertRaises(ep.ProtocolError):
            ep.validate_llm_response(["toy"], [{"observation_id": "toy", "prediction": "0.2"}])
        trace = [{"tool": "RNAfold", "input_sha256": "a" * 64, "output_sha256": "b" * 64}]
        self.assertEqual(ep.validate_agent_trace(trace, ("RNAfold",))["steps"], 1)
        with self.assertRaises(ep.ProtocolError):
            ep.validate_agent_trace(trace, ("RNAcofold",))
        with self.assertRaises(ep.ProtocolError):
            ep.validate_agent_trace([{**trace[0], "input_sha256": "git_sha"}], ("RNAfold",))

    def test_registries_all_real_tasks_disabled_and_tracks_separate(self):
        baselines = ep.read_json(ROOT / "configs/baseline_registry.yaml")
        models = ep.read_json(ROOT / "configs/model_adapter_registry.yaml")
        self.assertEqual(baselines["real_task_configs"], [])
        self.assertTrue(all(not b["real_task_enabled"] for b in baselines["baselines"]))
        self.assertEqual({t["track_id"] for t in models["tracks"]}, set(ep.TRACKS))
        self.assertEqual(len(ep.TRACKS), 6)
        for model in models["models"]:
            track = model["protocol_tracks"][0]
            result = ep.adapter_plan(model["model_id"], track)
            self.assertEqual(result["reason"], "BLOCKED_LOADABILITY")
            self.assertFalse(result["weights_loaded"])
            self.assertFalse(result["real_smoke_performed"])
        carbon = next(m for m in models["models"] if m["model_id"] == "Carbon-X")
        for field in ("tokenizer", "maximum_sequence_length", "prompt_format", "checkpoint_revision"):
            self.assertIsNone(carbon[field])
        self.assertFalse(carbon["sequence_transform"]["approved"])
        self.assertEqual(ep.adapter_plan("Qwen", "frozen_ridge")["reason"], "TRACK_INCOMPATIBLE")

    def test_dry_run_zero_writes(self):
        out = self.base / "not_created"
        plan = ep.smoke(out, dry_run=True)
        self.assertFalse(out.exists())
        self.assertEqual(plan["real_tasks"], 0)
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            self.assertEqual(ep.main(["smoke", "--out", str(out), "--dry-run"]), 0)
        self.assertTrue(json.loads(captured.getvalue())["dry_run"])
        self.assertFalse(out.exists())

    def test_cli_external_fake_admission_and_synthetic_bypass_blocked(self):
        config, ip, sp = self.fixture()
        path = self.base / "task.json"
        path.write_bytes(ep.canonical_bytes(config))
        argv = ["task", config["task_id"], "--config", str(path), "--input", str(ip),
                "--splits", str(sp), "--out", str(self.base / "out")]
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ep.main(argv), 2)
        self.assertFalse((self.base / "out").exists())
        config.update(task_id="T0001", synthetic=False, enabled=False)
        path.write_bytes(ep.canonical_bytes(config))
        argv[1] = "T0001"
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(ep.main(argv + ["--dry-run"]), 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "BLOCKED")

    def test_subprocess_cli_help_and_smoke_plan(self):
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        cmd = [sys.executable, str(ROOT / "tools/evaluation_protocol.py")]
        result = subprocess.run(cmd + ["smoke", "--out", str(self.base / "cli"), "--dry-run"],
                                text=True, capture_output=True, env=env, check=True)
        self.assertTrue(json.loads(result.stdout)["synthetic_only"])
        self.assertFalse((self.base / "cli").exists())


if __name__ == "__main__":
    unittest.main()
