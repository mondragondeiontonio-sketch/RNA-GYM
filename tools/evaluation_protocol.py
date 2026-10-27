#!/usr/bin/env python3
"""Bounded, fail-closed CPU evaluation protocol; no model/weight downloads.

The YAML registries intentionally use the JSON-compatible subset of YAML 1.2.
Run ``smoke --dry-run`` for a zero-write plan. Only smoke creates synthetic data.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import re
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Protocol

ROOT = Path(__file__).resolve().parents[1]
TRACKS = ("zero_shot_likelihood", "frozen_ridge", "frozen_mlp", "lora",
          "full_fine_tuning", "random_initialization")
STAGES = ("CREATED", "PREPARED", "RAN", "EVALUATED")
SCHEMA_VERSION = "rnagym.evaluation.v1"
MAX_ROWS = 10000
MAX_INPUT_BYTES = 32 * 1024 * 1024
EXECUTABLES = {
    "mean_null": ("regression", "sequence"),
    "median_null": ("regression", "sequence"),
    "sequence_stats_ridge": ("regression", "sequence"),
    "prevalence_null": ("binary_classification", "any"),
    "majority_null": ("binary_classification", "any"),
    "sequence_kmer_logistic": ("binary_classification", "sequence"),
    "pair_seed_match": ("binary_classification", "rna_pair"),
    "pair_mirna_only": ("binary_classification", "rna_pair"),
    "pair_target_only": ("binary_classification", "rna_pair"),
    "pair_stats_logistic": ("binary_classification", "rna_pair"),
}
SKLEARN_BASELINES = {"sequence_stats_ridge", "sequence_kmer_logistic",
                     "pair_mirna_only", "pair_target_only", "pair_stats_logistic"}


class ProtocolError(ValueError):
    """Invalid scientific protocol, binding, artifact or unsupported capability."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest_json(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def strict_json_loads(text):
    def reject_constant(value):
        raise ProtocolError("NONFINITE_JSON:" + value)
    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ProtocolError("DUPLICATE_JSON_KEY:" + key)
            obj[key] = value
        return obj
    return json.loads(text, parse_constant=reject_constant, object_pairs_hook=unique_object)


def read_json(path):
    return strict_json_loads(Path(path).read_text(encoding="utf-8"))


def write_immutable(path, value):
    """Atomic exclusive publication; identical crash-orphan outputs are reusable."""
    path = Path(path)
    content = canonical_bytes(value)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".partial")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o444)
        try:
            os.link(temporary, path)  # Exclusive; never replace an existing path.
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != content:
                raise ProtocolError("IMMUTABLE_ARTIFACT_CONFLICT:" + path.name)
    finally:
        if temporary.exists():
            temporary.unlink()
    return hashlib.sha256(content).hexdigest()


def _replace_checkpoint(path, value):
    temp = path.with_name("checkpoint." + uuid.uuid4().hex + ".tmp")
    with temp.open("xb") as handle:
        handle.write(canonical_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def _finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def _task_contract(config):
    required = ("task_id", "baseline_id", "problem_type", "input_mode", "alphabet",
                "label_definition", "label_unit", "split_source")
    if not isinstance(config, dict) or any(not config.get(k) for k in required):
        raise ProtocolError("MISSING_TASK_CONTRACT")
    if config.get("sequence_transform", "NONE") != "NONE":
        raise ProtocolError("UNIMPLEMENTED_SEQUENCE_TRANSFORM")
    if config["alphabet"] not in ("ACGU", "ACGT"):
        raise ProtocolError("EXPLICIT_RNA_OR_DNA_REPRESENTATION_REQUIRED")
    if config["input_mode"] == "rna_pair" and config["alphabet"] != "ACGU":
        raise ProtocolError("PAIR_BASELINES_REQUIRE_EXPLICIT_RNA_ALPHABET")
    baseline = config["baseline_id"]
    if baseline not in EXECUTABLES:
        raise ProtocolError("BASELINE_NOT_IMPLEMENTED:" + str(baseline))
    problem, mode = EXECUTABLES[baseline]
    if config["problem_type"] != problem or mode not in ("any", config["input_mode"]):
        raise ProtocolError("BASELINE_MODALITY_OR_LABEL_MISMATCH")
    if config["input_mode"] not in ("sequence", "rna_pair"):
        raise ProtocolError("MODALITY_NOT_IMPLEMENTED")
    for key in ("alpha", "C"):
        value = config.get(key, 1.0)
        if not _finite(value) or value <= 0:
            raise ProtocolError("INVALID_FIXED_HYPERPARAMETER:" + key)
    if type(config.get("kmer_k", 2)) is not int or config.get("kmer_k", 2) not in (1, 2, 3):
        raise ProtocolError("BOUNDED_KMER_K_REQUIRED")
    if type(config.get("max_rows", MAX_ROWS)) is not int or config.get("max_rows", MAX_ROWS) not in range(1, MAX_ROWS + 1):
        raise ProtocolError("CPU_ROW_BUDGET_EXCEEDED")
    if not isinstance(config.get("group_fields", []), list):
        raise ProtocolError("GROUP_FIELDS_MUST_BE_LIST")


def _approval(config, input_hash, split_hash):
    """No generated reviewer. Reuse the existing gate, with exact task bindings."""
    if config.get("synthetic") is True:
        if not config["task_id"].startswith("TOY_"):
            raise ProtocolError("SYNTHETIC_TASK_ID_REQUIRED")
        return {"status": "VERIFIED", "scope": "SYNTHETIC_PROTOCOL_ONLY",
                "admitted": False, "evidence_files": {}}
    if config.get("enabled") is not True or config.get("admission_state") not in (
            "ADMITTED", "ADMITTED_CORE", "ADMITTED_EXTENDED"):
        raise ProtocolError("REAL_TASK_DISABLED_PENDING_ADMISSION")
    if not config.get("admission_evidence"):
        raise ProtocolError("ADMITTED_EVIDENCE_REQUIRED")
    evidence_path = Path(config["admission_evidence"]).resolve()
    evidence = read_json(evidence_path)
    # Import does not execute the gate CLI and cannot set an admission state.
    if __package__:
        from .admission_gate import evaluate, REPORT_STATES
    else:
        from admission_gate import evaluate, REPORT_STATES
    decision = evaluate(evidence, evidence_path.parent)
    if not decision["admitted"]:
        raise ProtocolError("ADMISSION_GATE_REJECTED:" + ",".join(decision["issues"]))
    expected = {k: config[k] for k in ("task_id", "label_definition", "label_unit",
                                      "problem_type", "input_mode", "split_source")}
    expected.update(input_sha256=input_hash, split_sha256=split_hash)
    if evidence.get("approved_evaluation_binding") != expected:
        raise ProtocolError("APPROVED_TASK_INPUT_SPLIT_LABEL_BINDING_REQUIRED")
    if config.get("canonical_assay_id") != evidence.get("canonical_assay_id"):
        raise ProtocolError("TASK_ASSAY_BINDING_MISMATCH")
    files = {str(evidence_path): sha256_file(evidence_path)}
    # Pin all small scientific approvals. Original raw bytes are checked once by
    # admission_gate above, NOT rescanned at every checkpoint resume.
    for key in list(REPORT_STATES) + ["raw_provenance"]:
        path = (evidence_path.parent / evidence[key]).resolve()
        files[str(path)] = sha256_file(path)
    return {"status": "VERIFIED", "scope": "LOCAL_ADMITTED_TASK_BINDING",
            "admitted": True, "evidence_files": files,
            "raw_asset_sha256": evidence["sha256"],
            "reviewer_identity_cryptographically_verified": False}


def input_key(row, mode):
    # Roles/order and exact raw strings are preserved; no U/T/case equivalence.
    values = [row["sequence"]] if mode == "sequence" else [
        row["mirna_sequence"], row["target_sequence"]]
    return digest_json({"algorithm": "exact-role-ordered-json-sha256-v1", "values": values})


def _prepare_inputs(config, input_path, split_path):
    """Validate scalar observations and official/custom split without fitting."""
    _task_contract(config)
    paths = [Path(input_path), Path(split_path)]
    if any(p.stat().st_size > MAX_INPUT_BYTES for p in paths):
        raise ProtocolError("BOUNDED_CPU_INPUT_TOO_LARGE")
    rows = []
    with paths[0].open(encoding="utf-8", errors="strict") as handle:
        for line in handle:
            if not line.strip():
                raise ProtocolError("BLANK_OBSERVATION_LINE")
            rows.append(strict_json_loads(line))
            if len(rows) > config.get("max_rows", MAX_ROWS):
                raise ProtocolError("CPU_ROW_BUDGET_EXCEEDED")
    splits = read_json(paths[1])
    if not isinstance(splits, dict) or not rows:
        raise ProtocolError("EMPTY_INPUT_OR_INVALID_SPLIT")
    ids, key_splits, group_splits = set(), {}, {}
    counts = {k: 0 for k in ("train", "validation", "test")}
    for row in rows:
        if not isinstance(row, dict):
            raise ProtocolError("OBSERVATION_MUST_BE_OBJECT")
        oid = row.get("observation_id")
        if not isinstance(oid, str) or not oid or oid in ids:
            raise ProtocolError("MISSING_OR_DUPLICATE_OBSERVATION_ID")
        ids.add(oid)
        split = splits.get(oid)
        if split not in counts:
            raise ProtocolError("MISSING_OR_INVALID_SPLIT:" + oid)
        counts[split] += 1
        if not _finite(row.get("label")):
            raise ProtocolError("LABEL_NOT_FINITE_SCALAR:" + oid)
        if config["problem_type"] == "binary_classification" and row["label"] not in (0, 1):
            raise ProtocolError("BINARY_LABEL_REQUIRED:" + oid)
        fields = ["sequence"] if config["input_mode"] == "sequence" else [
            "mirna_sequence", "target_sequence"]
        for field in fields:
            seq = row.get(field)
            if not isinstance(seq, str) or not seq or set(seq) - set(config["alphabet"]):
                raise ProtocolError("EXACT_ALPHABET_OR_SEQUENCE_INVALID:" + oid)
            if len(seq) > 10000:
                raise ProtocolError("CPU_SEQUENCE_LENGTH_BUDGET_EXCEEDED")
        if config["input_mode"] == "rna_pair":
            for field in ("mirna_id", "target_id", "assay_id", "condition_id"):
                if not isinstance(row.get(field), str) or not row[field] or row[field].strip().upper() in {
                        "UNKNOWN", "NOT_VERIFIED", "N/A", "NONE", "PENDING", "UNRESOLVED"}:
                    raise ProtocolError("AMBIGUOUS_PAIR_IDENTITY:" + field)
            if len(row["mirna_sequence"]) < 8:
                raise ProtocolError("SEED_REQUIRES_MIRNA_POSITIONS_2_TO_8")
        if config.get("synthetic") is not True and row.get("assay_id") != config.get("canonical_assay_id"):
            raise ProtocolError("OBSERVATION_ASSAY_NOT_APPROVED:" + oid)
        key = input_key(row, config["input_mode"])
        if key in key_splits and key_splits[key] != split:
            raise ProtocolError("CROSS_SPLIT_IDENTICAL_INPUT:" + oid)
        key_splits[key] = split
        for field in config.get("group_fields", []):
            if not isinstance(field, str) or not row.get(field):
                raise ProtocolError("MISSING_PREREGISTERED_GROUP:" + str(field))
            gkey = (field, digest_json(row[field]))
            if gkey in group_splits and group_splits[gkey] != split:
                raise ProtocolError("CROSS_SPLIT_PREREGISTERED_GROUP:" + field)
            group_splits[gkey] = split
    if set(splits) != ids or not counts["train"] or not counts["test"]:
        raise ProtocolError("SPLIT_COVERAGE_OR_NONEMPTY_TRAIN_TEST_REQUIRED")
    hashes = {"input_sha256": sha256_file(paths[0]), "split_sha256": sha256_file(paths[1])}
    metadata = {"schema_version": SCHEMA_VERSION, "status": "VERIFIED",
                "scope": "SYNTHETIC_PROTOCOL_ONLY" if config.get("synthetic") else "LOCAL_TASK_ONLY",
                "counts": counts, "observations": len(rows), "unique_inputs": len(key_splits),
                "identity_algorithm": "exact-role-ordered-json-sha256-v1",
                "cross_split_identical_inputs": 0, "group_fields": config.get("group_fields", []),
                "sequence_transform": "NONE", "split_source": config["split_source"],
                "upstream_or_cross_dataset_leakage_review": "NOT_PERFORMED_BY_THIS_MODULE",
                "observation_identity_algorithm": "observation-role-ordered-json-sha256-v1",
                "observation_identity_map_sha256": digest_json([
                    [r["observation_id"], observation_key(r, config["input_mode"])] for r in rows]),
                **hashes}
    return {"config": config, "rows": rows, "splits": splits, "metadata": metadata}


def prepare(config, input_path, split_path):
    """Public API: scientific approval is mandatory for non-synthetic tasks."""
    prepared = _prepare_inputs(config, input_path, split_path)
    _approval(config, prepared["metadata"]["input_sha256"],
              prepared["metadata"]["split_sha256"])
    return prepared


def observation_key(row, mode):
    if mode == "rna_pair":
        fields = ("mirna_id", "mirna_sequence", "target_id", "target_sequence",
                  "assay_id", "condition_id")
    else:
        fields = ("observation_id", "sequence", "assay_id")
    return digest_json({"algorithm": "observation-role-ordered-json-sha256-v1",
                        "values": [row.get(field) for field in fields]})


def _stats(sequence):
    n = len(sequence)
    return [float(n)] + [sequence.count(c) / n for c in "ACGU" + "T"] + [
        sum(sequence[i] == sequence[i - 1] for i in range(1, n)) / max(1, n - 1)]


def _selected_sequence(row, baseline):
    return row[{"pair_mirna_only": "mirna_sequence",
                "pair_target_only": "target_sequence"}.get(baseline, "sequence")]


def _features(row, model):
    if model["feature_type"] == "pair_stats":
        return _stats(row["mirna_sequence"]) + _stats(row["target_sequence"])
    if model["feature_type"] == "stats":
        return _stats(row["sequence"])
    sequence = _selected_sequence(row, model["baseline_id"])
    k = model["kmer_k"]
    denominator = max(1, len(sequence) - k + 1)
    # Overlapping k-mers, not str.count's nonoverlapping convention.
    observed = {}
    for i in range(len(sequence) - k + 1):
        word = sequence[i:i + k]
        observed[word] = observed.get(word, 0) + 1
    return [observed.get(word, 0) / denominator for word in model["vocabulary"]]


def _normalize(vector, model):
    return [(x - mu) / sigma for x, mu, sigma in zip(
        vector, model["scaler_mean"], model["scaler_scale"])]


def fit(prepared):
    """Fit on train only. Persist numeric JSON parameters, never pickle."""
    config = prepared["config"]
    baseline = config["baseline_id"]
    train = [r for r in prepared["rows"] if prepared["splits"][r["observation_id"]] == "train"]
    labels = [float(r["label"]) for r in train]
    model = {"schema_version": SCHEMA_VERSION, "baseline_id": baseline,
             "problem_type": config["problem_type"], "fit_split": "train",
             "fit_observation_ids_sha256": digest_json(sorted(r["observation_id"] for r in train)),
             "fit_n": len(train), "threshold": 0.5, "threshold_selection": "FIXED_NOT_TUNED",
             "target_transform": "NONE", "sequence_transform": "NONE"}
    if baseline in ("mean_null", "median_null", "prevalence_null", "majority_null"):
        value = statistics.median(labels) if baseline == "median_null" else statistics.mean(labels)
        if baseline == "majority_null":
            value = float(value >= 0.5)
        model.update(kind="constant", value=value)
    elif baseline == "pair_seed_match":
        model.update(kind="seed_match", seed_positions_1based=[2, 8],
                     wobble_allowed=False, calibration="NONE_BINARY_MATCH_NOT_CALIBRATED")
    else:
        try:
            import sklearn
            from sklearn.linear_model import Ridge, LogisticRegression
        except ImportError as exc:
            raise ProtocolError("BLOCKED_DEPENDENCY:scikit-learn") from exc
        model["sklearn_version"] = sklearn.__version__
        model["feature_type"] = "stats" if baseline == "sequence_stats_ridge" else (
            "pair_stats" if baseline == "pair_stats_logistic" else "kmer")
        if model["feature_type"] == "kmer":
            k = config.get("kmer_k", 2)
            model["kmer_k"] = k
            model["vocabulary"] = sorted({s[i:i + k] for r in train
                for s in [_selected_sequence(r, baseline)] for i in range(len(s) - k + 1)})
            if not model["vocabulary"]:
                raise ProtocolError("EMPTY_TRAIN_KMER_VOCABULARY")
        vectors = [_features(r, model) for r in train]
        columns = list(zip(*vectors))
        model["scaler_mean"] = [statistics.mean(c) for c in columns]
        model["scaler_scale"] = [statistics.pstdev(c) or 1.0 for c in columns]
        features = [_normalize(v, model) for v in vectors]
        if config["problem_type"] == "regression":
            estimator = Ridge(alpha=config.get("alpha", 1.0), solver="svd")
            estimator.fit(features, labels)
            model.update(kind="linear", coefficients=estimator.coef_.tolist(),
                         intercept=float(estimator.intercept_), alpha=config.get("alpha", 1.0))
        else:
            if len(set(labels)) != 2:
                raise ProtocolError("LOGISTIC_REQUIRES_TWO_TRAIN_CLASSES")
            estimator = LogisticRegression(C=config.get("C", 1.0), random_state=0,
                                           max_iter=500, solver="liblinear")
            estimator.fit(features, labels)
            if int(estimator.n_iter_[0]) >= estimator.max_iter:
                raise ProtocolError("LOGISTIC_DID_NOT_CONVERGE")
            model.update(kind="logistic", coefficients=estimator.coef_[0].tolist(),
                         intercept=float(estimator.intercept_[0]), C=config.get("C", 1.0))
    return model


def predict(model, row):
    if model["kind"] == "constant":
        return model["value"]
    if model["kind"] == "seed_match":
        seed = row["mirna_sequence"][1:8]
        complement = seed.translate(str.maketrans("ACGU", "UGCA"))[::-1]
        return float(complement in row["target_sequence"])
    vector = _normalize(_features(row, model), model)
    score = model["intercept"] + math.fsum(a * b for a, b in zip(model["coefficients"], vector))
    if model["kind"] == "logistic":
        return 1 / (1 + math.exp(-score)) if score >= 0 else math.exp(score) / (1 + math.exp(score))
    return score


def run(prepared):
    """Prepare/run/evaluate API: returns model and held-out predictions only."""
    model = fit(prepared)
    predictions = [{"observation_id": r["observation_id"],
                    "split": prepared["splits"][r["observation_id"]],
                    "input_sha256": input_key(r, prepared["config"]["input_mode"]),
                    "prediction": predict(model, r)} for r in prepared["rows"]
                   if prepared["splits"][r["observation_id"]] != "train"]
    if any(not _finite(p["prediction"]) for p in predictions):
        raise ProtocolError("NONFINITE_PREDICTION")
    return {"model": model, "predictions": predictions}


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2
        for i in order[start:end]:
            result[i] = rank
        start = end
    return result


def _correlation(y, p):
    if len(y) < 2:
        return None
    ym, pm = statistics.mean(y), statistics.mean(p)
    cov = math.fsum((a - ym) * (b - pm) for a, b in zip(y, p))
    denominator = math.sqrt(math.fsum((a - ym) ** 2 for a in y) *
                            math.fsum((b - pm) ** 2 for b in p))
    return cov / denominator if denominator else None


def scalar_metrics(labels, predictions, problem):
    if len(labels) != len(predictions) or not labels or any(
            not _finite(x) for x in labels + predictions):
        raise ProtocolError("INVALID_METRIC_INPUT")
    n = len(labels)
    if problem == "regression":
        squared = math.fsum((a - b) ** 2 for a, b in zip(labels, predictions))
        total = math.fsum((a - statistics.mean(labels)) ** 2 for a in labels)
        return {"n": n, "mse": squared / n,
                "mae": statistics.mean(abs(a - b) for a, b in zip(labels, predictions)),
                "r2": 1 - squared / total if total else None,
                "pearson": _correlation(labels, predictions),
                "spearman": _correlation(_ranks(labels), _ranks(predictions)),
                "undefined_metric_policy": "NULL_NOT_ZERO_CONSTANT_OR_INSUFFICIENT_INPUT"}
    if problem != "binary_classification" or any(y not in (0, 1) for y in labels) or any(
            p < 0 or p > 1 for p in predictions):
        raise ProtocolError("INVALID_BINARY_METRIC_INPUT")
    predicted = [int(p >= 0.5) for p in predictions]
    tp = sum(y == 1 and p == 1 for y, p in zip(labels, predicted))
    fp = sum(y == 0 and p == 1 for y, p in zip(labels, predicted))
    fn = sum(y == 1 and p == 0 for y, p in zip(labels, predicted))
    tn = sum(y == 0 and p == 0 for y, p in zip(labels, predicted))
    positives = sum(labels)
    negatives = n - positives
    # Non-interpolated AP: equal scores enter together at a single threshold.
    # This is not trapezoidal PR-AUC, and cannot depend on tie row ordering.
    ap = None
    if positives:
        ranked = sorted(zip(predictions, labels), reverse=True)
        seen, true, area, start = 0, 0, 0.0, 0
        while start < n:
            end = start + 1
            while end < n and ranked[end][0] == ranked[start][0]:
                end += 1
            added = sum(y for _, y in ranked[start:end])
            true += added
            seen += end - start
            area += (added / positives) * (true / seen)
            start = end
        ap = area
    mcc_denominator = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = (tp * tn - fp * fn) / mcc_denominator if mcc_denominator else None
    auc = None
    if positives and negatives:
        ranks = _ranks(predictions)
        auc = (sum(r for r, y in zip(ranks, labels) if y == 1) -
               positives * (positives + 1) / 2) / (positives * negatives)
    epsilon = 1e-15
    return {"n": n, "accuracy": sum(y == p for y, p in zip(labels, predicted)) / n,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            "auroc": auc, "average_precision": ap, "mcc": mcc,
            "positive_class": 1,
            "average_precision_definition": "NON_INTERPOLATED_SUM_DELTA_RECALL_TIMES_PRECISION_TIES_GROUPED",
            "undefined_reasons": {
                key: reason for key, value, reason in (
                    ("auroc", auc, "SINGLE_OBSERVED_CLASS"),
                    ("average_precision", ap, "NO_POSITIVE_LABELS"),
                    ("mcc", mcc, "ZERO_CONFUSION_MARGIN")) if value is None},
            "brier": statistics.mean((y - p) ** 2 for y, p in zip(labels, predictions)),
            "log_loss": -statistics.mean(y * math.log(max(epsilon, min(1 - epsilon, p))) +
                (1 - y) * math.log(1 - max(epsilon, min(1 - epsilon, p)))
                for y, p in zip(labels, predictions)),
            "threshold": 0.5, "log_loss_clip_epsilon": epsilon,
            "undefined_metric_policy": "NULL_NOT_ZERO"}


def evaluate(prepared, predictions):
    """Strict ID/split alignment; no threshold or hyperparameter selection."""
    expected = {r["observation_id"]: r for r in prepared["rows"]
                if prepared["splits"][r["observation_id"]] != "train"}
    seen = set()
    grouped = {"validation": ([], []), "test": ([], [])}
    for item in predictions:
        oid = item.get("observation_id")
        if oid not in expected or oid in seen:
            raise ProtocolError("PREDICTION_ID_MISMATCH_OR_DUPLICATE")
        seen.add(oid)
        split = prepared["splits"][oid]
        if item.get("split") != split or item.get("input_sha256") != input_key(
                expected[oid], prepared["config"]["input_mode"]):
            raise ProtocolError("PREDICTION_SPLIT_OR_INPUT_MISMATCH")
        grouped[split][0].append(expected[oid]["label"])
        grouped[split][1].append(item.get("prediction"))
    if set(expected) != seen:
        raise ProtocolError("MISSING_HELDOUT_PREDICTIONS")
    return {"schema_version": SCHEMA_VERSION, "status": "VERIFIED",
            "scope": prepared["metadata"]["scope"],
            "task_id": prepared["config"]["task_id"],
            "baseline_id": prepared["config"]["baseline_id"],
            "label_definition": prepared["config"]["label_definition"],
            "label_unit": prepared["config"]["label_unit"],
            "loss": "MAE" if prepared["config"]["baseline_id"] == "median_null" else (
                "MSE" if prepared["config"]["problem_type"] == "regression" else "BINARY_LOG_LOSS"),
            "loss_scope": "EVALUATION_LOSS_NOT_PENALIZED_TRAIN_OBJECTIVE",
            "metrics": {s: scalar_metrics(y, p, prepared["config"]["problem_type"])
                        for s, (y, p) in grouped.items() if y},
            "rankable_real_result": False,
            "ranking_review": "SEPARATE_HUMAN_RESULT_REVIEW_REQUIRED",
            "transform_fit_split": "train", "hpo": "NONE", "gpu_used": False}


def _event(directory, payload):
    events = directory / "events"
    events.mkdir(exist_ok=True)
    previous = sorted(events.glob("*.json"))
    payload = {**payload, "time": utc_now(), "run_id": directory.name,
               "previous_event_sha256": sha256_file(previous[-1]) if previous else None}
    write_immutable(events / (f"{len(previous):06d}.json"), payload)


def create_run(config, input_path, split_path, out, run_id=None):
    _task_contract(config)
    if config.get("synthetic") is not True and (config.get("enabled") is not True or
            config.get("admission_state") not in ("ADMITTED", "ADMITTED_CORE", "ADMITTED_EXTENDED")):
        raise ProtocolError("REAL_TASK_DISABLED_PENDING_ADMISSION")
    paths = [Path(input_path).resolve(), Path(split_path).resolve()]
    if any(path.stat().st_size > MAX_INPUT_BYTES for path in paths):
        raise ProtocolError("BOUNDED_CPU_INPUT_TOO_LARGE")
    hashes = {"input_sha256": sha256_file(paths[0]), "split_sha256": sha256_file(paths[1])}
    approval = _approval(config, hashes["input_sha256"], hashes["split_sha256"])
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ_") + uuid.uuid4().hex[:8]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
        raise ProtocolError("INVALID_RUN_ID")
    directory = Path(out).resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    request = {"schema_version": SCHEMA_VERSION, "run_id": run_id, "created_at": utc_now(),
               "config": config, "config_sha256": digest_json(config),
               "input_path": str(paths[0]), "split_path": str(paths[1]), **hashes,
               "code_sha256": sha256_file(Path(__file__)), "python_version": sys.version,
               "registry_sha256": {name: sha256_file(ROOT / name) for name in (
                   "configs/baseline_registry.yaml", "configs/model_adapter_registry.yaml")},
               "approval": approval}
    request_hash = write_immutable(directory / "request.json", request)
    checkpoint = {"run_id": run_id, "stage": "CREATED", "status": "READY",
                  "request_sha256": request_hash, "artifacts": {}, "attempts": {},
                  "retry_count": 0, "last_heartbeat": utc_now()}
    _event(directory, {"event": "CREATED", "request_sha256": request_hash})
    _replace_checkpoint(directory / "checkpoint.json", checkpoint)
    return directory


@contextlib.contextmanager
def _run_lock(directory):
    import fcntl
    with (directory / ".run.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProtocolError("RUN_ALREADY_ACTIVE") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _verify_resume(directory):
    directory = Path(directory)
    previous_sha = None
    for i, path in enumerate(sorted((directory / "events").glob("*.json"))):
        event = read_json(path)
        if path.name != f"{i:06d}.json" or event.get("run_id") != directory.name or event.get("previous_event_sha256") != previous_sha:
            raise ProtocolError("EVENT_CHAIN_INVALID")
        previous_sha = sha256_file(path)
    if previous_sha is None:
        raise ProtocolError("EVENT_CHAIN_MISSING")
    checkpoint = read_json(directory / "checkpoint.json")
    request = read_json(directory / "request.json")
    if checkpoint["request_sha256"] != sha256_file(directory / "request.json"):
        raise ProtocolError("REQUEST_CHECKPOINT_HASH_MISMATCH")
    if directory.name != checkpoint["run_id"] or directory.name != request["run_id"]:
        raise ProtocolError("IMMUTABLE_RUN_ID_MISMATCH")
    if request["config_sha256"] != digest_json(request["config"]):
        raise ProtocolError("CONFIG_HASH_MISMATCH")
    if request["code_sha256"] != sha256_file(Path(__file__)):
        raise ProtocolError("CODE_CHANGED_CREATE_NEW_VERSIONED_RUN")
    for name, expected in request["registry_sha256"].items():
        if sha256_file(ROOT / name) != expected:
            raise ProtocolError("REGISTRY_CHANGED_CREATE_NEW_VERSIONED_RUN")
    for path, expected in request["approval"]["evidence_files"].items():
        if sha256_file(path) != expected:
            raise ProtocolError("APPROVAL_EVIDENCE_CHANGED")
    for key in ("input", "split"):
        if sha256_file(request[key + "_path"]) != request[key + "_sha256"]:
            raise ProtocolError("SOURCE_INPUT_CHANGED:" + key)
    for name, expected in checkpoint["artifacts"].items():
        if Path(name).name != name or sha256_file(directory / name) != expected:
            raise ProtocolError("CHECKPOINT_ARTIFACT_HASH_MISMATCH:" + name)
    return request, checkpoint


def advance(directory, stage="next", retries=1):
    """One idempotent stage by default; bounded retry only for transient I/O."""
    directory = Path(directory).resolve()
    if type(retries) is not int or not 0 <= retries <= 3:
        raise ProtocolError("RETRIES_MUST_BE_0_TO_3")
    with _run_lock(directory):
        request, checkpoint = _verify_resume(directory)
        current = STAGES.index(checkpoint["stage"])
        if stage == "next":
            target = min(current + 1, 3)
        elif stage in ("prepare", "run", "evaluate"):
            target = {"prepare": 1, "run": 2, "evaluate": 3}[stage]
        else:
            raise ProtocolError("INVALID_STAGE")
        if target <= current:
            return checkpoint
        if target != current + 1:
            raise ProtocolError("PREREQUISITE_STAGE_REQUIRED")
        name = STAGES[target]
        # This cap persists across process restarts; resume cannot reset retries.
        max_attempts = retries + 1
        attempts = checkpoint["attempts"].get(name, 0)
        if attempts >= max_attempts:
            raise ProtocolError("RETRY_BUDGET_EXHAUSTED_CREATE_NEW_RUN")
        while attempts < max_attempts:
            attempts += 1
            checkpoint["attempts"][name] = attempts
            checkpoint.update(status="RUNNING", last_heartbeat=utc_now())
            _replace_checkpoint(directory / "checkpoint.json", checkpoint)
            _event(directory, {"event": "STAGE_STARTED", "stage": name, "attempt": attempts})
            try:
                prepared = _prepare_inputs(request["config"], request["input_path"], request["split_path"])
                if target == 1:
                    artifacts = {"prepared.json": prepared["metadata"]}
                elif target == 2:
                    result = run(prepared)
                    artifacts = {"model.json": result["model"], "predictions.json": result["predictions"]}
                else:
                    result = evaluate(prepared, read_json(directory / "predictions.json"))
                    result["provenance"] = {"run_id": directory.name,
                        "request_sha256": checkpoint["request_sha256"],
                        "input_sha256": request["input_sha256"], "split_sha256": request["split_sha256"],
                        "model_sha256": checkpoint["artifacts"]["model.json"],
                        "predictions_sha256": checkpoint["artifacts"]["predictions.json"],
                        "code_sha256": request["code_sha256"]}
                    artifacts = {"metrics.json": result}
                for artifact, value in artifacts.items():
                    checkpoint["artifacts"][artifact] = write_immutable(directory / artifact, value)
                checkpoint.update(stage=name, status="DONE", last_heartbeat=utc_now(), last_error=None)
                _event(directory, {"event": "STAGE_COMPLETED", "stage": name,
                                   "artifacts": checkpoint["artifacts"]})
                _replace_checkpoint(directory / "checkpoint.json", checkpoint)
                return checkpoint
            except (Exception, KeyboardInterrupt) as exc:
                interrupted = isinstance(exc, KeyboardInterrupt)
                checkpoint.update(status="INTERRUPTED" if interrupted else "FAILED",
                                  last_error=type(exc).__name__ + ":" + str(exc),
                                  last_heartbeat=utc_now())
                _event(directory, {"event": checkpoint["status"], "stage": name,
                                   "error": checkpoint["last_error"]})
                _replace_checkpoint(directory / "checkpoint.json", checkpoint)
                if interrupted or not isinstance(exc, OSError) or attempts >= max_attempts:
                    raise
                checkpoint["retry_count"] += 1
                _replace_checkpoint(directory / "checkpoint.json", checkpoint)
                time.sleep(min(0.1 * 2 ** (attempts - 1), 1))
    return checkpoint


class RNAEncoderAdapter(Protocol):
    """No automatic .from_pretrained/download in this protocol."""
    def encode(self, records: list[dict], *, track: str) -> list[dict]: ...


class RNALLMAdapter(Protocol):
    """Prompt-only interface, separate from sequence encoder tracks."""
    def predict_json(self, requests: list[dict], *, prompt_sha256: str) -> list[dict]: ...


class RNAAgentAdapter(Protocol):
    """Tools are explicit and allowlisted; no shell execution implemented."""
    def act(self, request: dict, *, allowed_tools: tuple[str, ...]) -> dict: ...


def validate_encoding(records, outputs):
    if len(records) != len(outputs):
        raise ProtocolError("ENCODER_BATCH_SIZE_MISMATCH")
    dimension = None
    for row, output in zip(records, outputs):
        if output.get("observation_id") != row["observation_id"]:
            raise ProtocolError("ENCODER_OBSERVATION_ALIGNMENT")
        vectors = output.get("nucleotide_embeddings")
        mask = output.get("valid_position_mask")
        if not isinstance(vectors, list) or len(vectors) != len(row["sequence"]) or not isinstance(mask, list) or len(mask) != len(vectors):
            raise ProtocolError("ENCODER_NUCLEOTIDE_ALIGNMENT_REQUIRED")
        if any(type(m) is not bool for m in mask):
            raise ProtocolError("ENCODER_BOOLEAN_MASK_REQUIRED")
        for vector in vectors:
            if not isinstance(vector, list) or not vector or any(not _finite(x) for x in vector):
                raise ProtocolError("ENCODER_FINITE_EMBEDDING_REQUIRED")
            dimension = dimension or len(vector)
            if len(vector) != dimension:
                raise ProtocolError("ENCODER_DIMENSION_MISMATCH")
    return {"status": "VERIFIED", "scope": "PROTOCOL_VALIDATION_ONLY", "dimension": dimension}


def validate_llm_response(observation_ids, responses):
    expected = set(observation_ids)
    seen = set()
    if len(expected) != len(observation_ids):
        raise ProtocolError("DUPLICATE_LLM_REQUEST_ID")
    for response in responses:
        oid = response.get("observation_id")
        if oid not in expected or oid in seen or not _finite(response.get("prediction")):
            raise ProtocolError("LLM_STRUCTURED_FINITE_PREDICTION_REQUIRED")
        seen.add(oid)
    if seen != expected:
        raise ProtocolError("LLM_RESPONSE_COVERAGE_MISMATCH")
    return {"status": "VERIFIED", "scope": "PROTOCOL_VALIDATION_ONLY"}


def validate_agent_trace(trace, allowed_tools):
    if not isinstance(trace, list) or len(trace) > 100:
        raise ProtocolError("BOUNDED_AGENT_TRACE_REQUIRED")
    for step in trace:
        if step.get("tool") not in allowed_tools:
            raise ProtocolError("AGENT_TOOL_NOT_ALLOWLISTED")
        for field in ("input_sha256", "output_sha256"):
            if not isinstance(step.get(field), str) or not re.fullmatch("[0-9a-f]{64}", step[field]):
                raise ProtocolError("AGENT_TOOL_HASH_REQUIRED")
    return {"status": "VERIFIED", "scope": "TRACE_SCHEMA_ONLY_NOT_TOOL_REEXECUTION", "steps": len(trace)}


def adapter_plan(model_id, track, registry_path=None):
    registry = read_json(registry_path or ROOT / "configs/model_adapter_registry.yaml")
    if track not in TRACKS + ("rna_llm", "rna_agent"):
        raise ProtocolError("UNKNOWN_INDEPENDENT_TRACK")
    models = {m["model_id"]: m for m in registry["models"]}
    if model_id not in models:
        raise ProtocolError("UNREGISTERED_MODEL")
    model = models[model_id]
    compatible = track in model["protocol_tracks"]
    return {"status": "BLOCKED", "reason": "BLOCKED_LOADABILITY" if compatible else "TRACK_INCOMPATIBLE",
            "model_id": model_id, "track": track, "weights_loaded": False,
            "weights_downloaded": False, "real_smoke_performed": False,
            "package_discovery_only": {name: importlib.util.find_spec(name) is not None
                                       for name in model.get("python_modules", [])},
            "metadata_evidence_status": model["metadata_evidence_status"],
            "plan_scope": "LEGACY_METADATA_ONLY_NO_CHECKPOINT_MANIFEST_ARGUMENT",
            "bounded_local_adapter": model.get("bounded_local_adapter"),
            "unresolved_requirements": model["unresolved_requirements"]}


def toy_data(problem="regression", mode="sequence"):
    """Explicit synthetic labels, not RNA experimental measurements."""
    rng = random.Random(1729)
    rows, splits, used = [], {}, set()
    for i in range(48):
        while True:
            sequence = "".join(rng.choice("ACGU") for _ in range(12 + i % 7))
            if sequence not in used:
                used.add(sequence)
                break
        oid = f"toy_{i:03d}"
        row = {"observation_id": oid, "assay_id": "SYNTHETIC_NOT_AN_ASSAY"}
        if mode == "rna_pair":
            target = "".join(rng.choice("ACGU") for _ in range(32))
            seed = sequence[1:8].translate(str.maketrans("ACGU", "UGCA"))[::-1]
            if i % 2:
                target = target[:10] + seed + target[17:]
            elif seed in target:
                target = "A" * 32 if seed != "A" * 7 else "C" * 32
            row.update(mirna_sequence=sequence, target_sequence=target,
                       mirna_id="SYNTHETIC_MIR_" + str(i), target_id="SYNTHETIC_TARGET_" + str(i),
                       condition_id="SYNTHETIC_IN_SILICO", label=int(seed in target))
        else:
            label = sequence.count("G") / len(sequence) + 0.01 * len(sequence)
            row.update(sequence=sequence, label=label if problem == "regression" else i % 2)
        rows.append(row)
        splits[oid] = "train" if i < 32 else ("validation" if i < 40 else "test")
    return rows, splits


def toy_config(baseline):
    problem, mode = EXECUTABLES[baseline]
    mode = "sequence" if mode == "any" else mode
    return {"task_id": "TOY_" + baseline.upper(), "baseline_id": baseline,
            "synthetic": True, "enabled": True, "problem_type": problem,
            "input_mode": mode, "alphabet": "ACGU", "sequence_transform": "NONE",
            "label_definition": "SYNTHETIC_ENGINEERED_LABEL_NOT_EXPERIMENTAL",
            "label_unit": "synthetic_arbitrary_unit" if problem == "regression" else "binary",
            "split_source": "RNA_GYM_TOY_FIXED_V1_NOT_OFFICIAL", "group_fields": [],
            "alpha": 1.0, "C": 1.0, "kmer_k": 2}


def smoke(out, dry_run=False):
    plan = {"status": "PROVISIONAL" if dry_run else "VERIFIED", "synthetic_only": True,
            "real_tasks": 0, "weights_downloaded": False, "gpu_used": False,
            "baseline_ids": list(EXECUTABLES), "optional_dependency": "scikit-learn",
            "output": str(Path(out)), "dry_run": dry_run}
    if dry_run:
        return plan
    base = Path(out) / ("smoke_" + uuid.uuid4().hex)
    base.mkdir(parents=True, exist_ok=False)
    results = []
    for baseline in EXECUTABLES:
        config = toy_config(baseline)
        rows, splits = toy_data(config["problem_type"], config["input_mode"])
        inputs = base / (baseline + ".jsonl")
        with inputs.open("xb") as handle:
            for row in rows:
                handle.write(canonical_bytes(row))
        inputs.chmod(0o444)
        split_path = base / (baseline + "_splits.json")
        write_immutable(split_path, splits)
        if baseline in SKLEARN_BASELINES and importlib.util.find_spec("sklearn") is None:
            results.append({"baseline_id": baseline, "status": "BLOCKED", "reason": "BLOCKED_DEPENDENCY"})
            continue
        directory = create_run(config, inputs, split_path, base)
        try:
            for stage in ("prepare", "run", "evaluate"):
                advance(directory, stage)
        except (ValueError, OverflowError, ImportError, OSError) as exc:
            results.append({"baseline_id": baseline, "status": "BLOCKED", "run_id": directory.name,
                            "reason": type(exc).__name__ + ":" + str(exc)})
            continue
        metrics = read_json(directory / "metrics.json")
        results.append({"baseline_id": baseline, "status": "VERIFIED", "run_id": directory.name,
                        "scope": "SYNTHETIC_PROTOCOL_ONLY", "metrics": metrics["metrics"],
                        "metrics_sha256": sha256_file(directory / "metrics.json")})
    summary = {**plan, "runs": results, "verified_toy_runs": sum(r["status"] == "VERIFIED" for r in results),
               "blocked_toy_runs": sum(r["status"] == "BLOCKED" for r in results),
               "real_admitted_tasks": 0, "rankable_real_results": 0}
    summary["status"] = "VERIFIED" if not summary["blocked_toy_runs"] else "PROVISIONAL"
    write_immutable(base / "smoke_summary.json", summary)
    return {**summary, "summary_path": str(base / "smoke_summary.json")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("smoke", help="Synthetic CPU prepare/run/evaluate only")
    s.add_argument("--out", type=Path, default=Path("runs/evaluation_protocol"))
    s.add_argument("--dry-run", action="store_true")
    t = sub.add_parser("task", help="One explicitly admitted task; disabled without full gate evidence")
    t.add_argument("task_id")
    for flag in ("config", "input", "splits", "out"):
        t.add_argument("--" + flag, type=Path, required=True)
    t.add_argument("--stage", choices=("prepare", "run", "evaluate"), default="prepare")
    t.add_argument("--dry-run", action="store_true")
    t.add_argument("--retries", type=int, default=1)
    r = sub.add_parser("resume", help="Verify immutable input/output hashes and finish one stage")
    r.add_argument("--run-dir", type=Path, required=True)
    r.add_argument("--stage", choices=("next", "prepare", "run", "evaluate"), default="next")
    r.add_argument("--retries", type=int, default=1)
    r.add_argument("--dry-run", action="store_true")
    a = sub.add_parser("adapter", help="Read-only protocol/dependency plan; never load checkpoints")
    a.add_argument("--model", required=True)
    a.add_argument("--track", required=True, choices=TRACKS + ("rna_llm", "rna_agent"))
    args = parser.parse_args(argv)
    try:
        if args.command == "smoke":
            result = smoke(args.out, args.dry_run)
        elif args.command == "adapter":
            result = adapter_plan(args.model, args.track)
        elif args.command == "resume":
            if args.dry_run:
                request, checkpoint = _verify_resume(args.run_dir)
                result = {"status": "PROVISIONAL", "dry_run": True, "run_id": request["run_id"],
                          "checkpoint": checkpoint, "requested_stage": args.stage}
            else:
                result = advance(args.run_dir, args.stage, args.retries)
        else:
            config = read_json(args.config)
            _task_contract(config)
            if config["task_id"] != args.task_id:
                raise ProtocolError("TASK_ID_CONFIG_MISMATCH")
            # Synthetic entry is only through built-in smoke, not external CLI files.
            if config.get("synthetic"):
                raise ProtocolError("EXTERNAL_TASK_CLI_REQUIRES_REAL_ADMISSION_USE_SMOKE_FOR_TOY")
            if args.dry_run:
                ready = config.get("enabled") is True and config.get("admission_state") in (
                    "ADMITTED", "ADMITTED_CORE", "ADMITTED_EXTENDED")
                result = {"status": "PROVISIONAL" if ready else "BLOCKED", "dry_run": True,
                          "task_id": args.task_id, "stage": args.stage,
                          "admission_verified": False, "reason": "EVIDENCE_CHECK_REQUIRED_AT_EXECUTION" if ready
                          else "REAL_TASK_DISABLED_PENDING_ADMISSION", "writes_performed": False}
            else:
                if args.stage != "prepare":
                    raise ProtocolError("NEW_RUN_MUST_PREPARE_THEN_RESUME")
                directory = create_run(config, args.input, args.splits, args.out)
                result = {"run_dir": str(directory), "checkpoint": advance(directory, args.stage, args.retries)}
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 2 if result.get("status") == "BLOCKED" else 0
    except (ValueError, OverflowError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": type(exc).__name__ + ":" + str(exc),
                          "rankable_real_results": 0}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
