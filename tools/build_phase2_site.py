#!/usr/bin/env python3
"""Build an opt-in, aggregate-only Phase 2 snapshot; never publish or admit data."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import unquote, urlsplit

SCHEMA = "rnagym.phase2.public.v1"
SNAPSHOT_NAME = "phase2-snapshot.json"
ROOT = Path(__file__).resolve().parents[1]
MAX_INPUT_BYTES = 16 * 1024 * 1024
TASK_FIELDS = {
    "task_id", "package_group_id", "scientific_stage", "disposition",
    "verification_status", "blocking_reasons", "evidence_paths",
}
ASSAY_FIELDS = {
    "canonical_assay_id", "original_assay_id", "source_project", "source_doi",
    "experiment_accession", "biological_readout", "label_definition", "label_unit",
    "data_license", "qc_status", "verification_status", "evidence_url",
}
STAGES = {
    "NOT_REVIEWED", "FILE_QC_PASS", "SOURCE_VERIFIED", "ASSAY_VERIFIED",
    "SPLIT_QC_PASS", "ADMISSION_CANDIDATE", "ADMITTED", "HOLD", "EXCLUDED",
}
VERIFICATIONS = {"VERIFIED", "PROVISIONAL", "BLOCKED"}
ADMITTED = {"ADMITTED", "ADMITTED_CORE", "ADMITTED_EXTENDED"}
PUBLIC_SUMMARY_COUNTS = {
    "registered_tasks", "package_groups", "assays", "admitted_tasks",
    "admission_candidate_tasks", "file_qc_pass_tasks", "held_tasks", "excluded_tasks",
    "source_verified_tasks", "assay_verified_tasks", "split_qc_pass_tasks",
}
PRIOR_COUNTS = {
    "registered_tasks", "package_groups", "local_acquired_artifacts",
    "local_raw_artifact_bytes_including_reassembly", "network_downloaded_artifacts",
    "lossless_reassembled_artifacts", "groups_with_acquired_artifacts",
    "mrna_file_rows_scanned", "mrna_files_all_rows_scanned",
    "paired_file_rows_including_versions", "paired_files_all_rows_scanned",
    "probing_sequence_records_scanned", "probing_exact_shared_train_test_sequences",
    "coordinate_files_scanned", "coordinate_atom_rows_scanned",
}
URL_DOMAINS = {
    "github.com", "raw.githubusercontent.com", "huggingface.co", "hf.co", "doi.org",
    "zenodo.org", "ncbi.nlm.nih.gov", "ebi.ac.uk", "encodeproject.org", "rcsb.org",
    "wwpdb.org", "rmdb.stanford.edu", "rmdb.org", "rna3db.org", "rna3db.com",
    "nature.com", "science.org", "cell.com", "academic.oup.com", "biorxiv.org",
    "arxiv.org", "pmc.ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov", "figshare.com",
    "datadryad.org", "kaggle.com", "rnacentral.org", "rfam.org", "rfam.xfam.org",
}
SENSITIVE = re.compile(
    r"github_pat_|gh[pousr]_[A-Za-z0-9]{12,}|hf_[A-Za-z0-9]{16,}|"
    r"\bsk-[A-Za-z0-9_-]{16,}|\bAKIA[A-Z0-9]{16}|-----BEGIN .*PRIVATE KEY|"
    r"\b(?:authorization|bearer)\b|(?:api[_-]?key|access[_-]?token|password)\s*[:=]|"
    r"(?:^|[\s\"'=])/(?:home|users|root|tmp|private|mnt|media|sibcb\w*|data|work|scratch|"
    r"srv|opt|var|internal)(?:/|\b)|(?:^|[\s\"'=])[A-Za-z]:[\\/]|\\\\|file://|"
    r"(?<![\w.:/])/(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+|"
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", re.IGNORECASE,
)
UNKNOWN = {"", "unknown", "not_verified", "n/a", "na", "none", "null", "[]"}
REASON_TERMS = {
    "RIGHTS": r"licen[cs]e|rights|redistribut|permission",
    "SOURCE": r"source|citation|doi|accession|paper",
    "ASSAY_IDENTITY": r"assay|identity|condition|replicate|construct",
    "LABEL_SEMANTICS": r"label|readout|unit|transform|measurement",
    "SPLIT_LEAKAGE": r"split|leakage|overlap|homology|dedup",
    "QC": r"\bqc\b|schema|quality|mask|stereo|clash",
    "HUMAN_REVIEW": r"review|approv|signoff|sign.off",
    "SAFE_FORMAT": r"pickle|format|encod|delimiter|safe.export",
    "ACQUISITION": r"download|bytes|missing.file|release|auth|credential",
}
BASELINE_PROTOCOLS = [
    {"family": "regression", "title": "Sequence-level regression",
     "methods": ["Mean / median null", "Sequence statistics + Ridge", "XGBoost"],
     "requirements": "Keep MRL, TE, RSS and half-life separate; fit transforms on training data only."},
    {"family": "classification", "title": "Classification / binding",
     "methods": ["Majority / prevalence null", "k-mer Logistic Regression", "XGBoost"],
     "requirements": "Verify experimental label and negative generation before choosing a loss."},
    {"family": "paired_rna", "title": "RNA–RNA / miRNA pairs",
     "methods": ["miRNA-only negative control", "Target-only negative control", "Seed matching",
                 "RNAcofold (when applicable)", "Pairwise sequence model"],
     "requirements": "Keep assay and condition in observation identity; do not merge cross-assay labels."},
    {"family": "mutation_effect", "title": "Mutation effects",
     "methods": ["WT / no-change null", "Mutation / sequence features + Ridge"],
     "requirements": "Verify RNA readout and WT/backbone grouping; DNA fitness proxies are not RNA assays."},
    {"family": "nucleotide_regression", "title": "Nucleotide-level regression",
     "methods": ["Position / assay null", "RNAplfold + Ridge (when applicable)", "Scratch 1D CNN"],
     "requirements": "Respect effective-position masks, probe, units and original vectors."},
    {"family": "rna_2d", "title": "RNA secondary structure",
     "methods": ["RNAfold", "RNAstructure", "Lightweight scratch model (task-dependent)"],
     "requirements": "Audit pseudoknots, indexing and supported pair types; never force an incompatible solver."},
    {"family": "rna_3d", "title": "RNA tertiary structure",
     "methods": ["Task-reviewed geometric baseline", "Task-reviewed structure prediction baseline"],
     "requirements": "Assembly, chain, stereochemistry and homology review required before baseline selection."},
]
FM_TRACKS = ["Zero-shot likelihood", "Frozen + Ridge", "Frozen + MLP", "LoRA",
             "Full fine-tuning", "Random initialization"]


class PublicSnapshotError(ValueError):
    """Unsafe or inconsistent evidence; no output may be written."""


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise PublicSnapshotError(f"Missing or symlinked input: {path.name}")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise PublicSnapshotError(f"Input too large for aggregate contract: {path.name}")
    with path.open("rb") as handle:
        data = handle.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise PublicSnapshotError("Aggregate input grew beyond the permitted size")
    return data


def _json(data: bytes, name: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PublicSnapshotError(f"Duplicate JSON key in {name}")
            result[key] = value
        return result
    try:
        result = json.loads(data.decode("utf-8-sig"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PublicSnapshotError(f"Invalid UTF-8 JSON in {name}") from exc
    if not isinstance(result, dict):
        raise PublicSnapshotError(f"Expected JSON object in {name}")
    return result


def _tsv(data: bytes, name: str, required: set[str]) -> list[dict]:
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""), delimiter="\t")
        headers = reader.fieldnames
        if not headers or len(set(headers)) != len(headers) or not required.issubset(headers):
            raise PublicSnapshotError(f"Missing or duplicate required TSV columns in {name}")
        rows = list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise PublicSnapshotError(f"Invalid UTF-8 TSV in {name}") from exc
    if len(rows) > 100_000 or any(None in row or any(v is None for v in row.values()) for row in rows):
        raise PublicSnapshotError(f"Ragged or oversized TSV in {name}")
    return rows


def _text(value, field: str, maximum: int = 1000, nullable: bool = True):
    if not isinstance(value, str):
        raise PublicSnapshotError(f"Expected text in public field {field}")
    text = value.strip()
    if nullable and text.lower() in UNKNOWN:
        return None
    decoded = text
    for _ in range(3):
        decoded = unquote(decoded)
    if (len(text) > maximum or SENSITIVE.search(decoded) or
            any(ord(c) < 32 or ord(c) == 127 for c in text) or "<" in text or ">" in text or
            decoded.lstrip().startswith(("/", "~", "\\")) or
            re.search(r"(?:^|[^A-Za-z])[ACGTUNacgtun]{30,}(?:$|[^A-Za-z])", decoded) or
            re.fullmatch(r"\[\s*-?\d+(?:\.\d+)?(?:\s*,\s*-?\d+(?:\.\d+)?)+\s*\]", text)):
        raise PublicSnapshotError(f"Unsafe value in public field {field}")
    return text


def _id(value, field: str) -> str:
    text = _text(value, field, 180, nullable=False)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:+-]*", text):
        raise PublicSnapshotError(f"Invalid identifier in {field}")
    return text


def _verification(value: str) -> str:
    if value not in VERIFICATIONS:
        raise PublicSnapshotError("Invalid verification_status")
    return value


def _url(value: str):
    text = _text(value, "evidence_url", 2000)
    if text is None:
        return None
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError as exc:
        raise PublicSnapshotError("Invalid evidence_url") from exc
    host = (parsed.hostname or "").lower()
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or
            parsed.fragment or port not in (None, 443) or not any(
                host == d or host.endswith("." + d) for d in URL_DOMAINS)):
        raise PublicSnapshotError("Only allowlisted, unsigned public HTTPS evidence URLs are accepted")
    return text


def _reason_codes(text: str) -> list[str]:
    # Free-form reasons are private input, never public output.
    found = [code for code, expression in REASON_TERMS.items()
             if re.search(expression, text, re.IGNORECASE)]
    return found or (["OTHER_REVIEW_REQUIRED"] if text.strip() else [])


def _count(value, name: str) -> int:
    if type(value) is not int or value < 0:
        raise PublicSnapshotError(f"Expected nonnegative integer for summary {name}")
    return value


def _reference(name: str, row: int, sha: str) -> dict:
    return {"source_file": name, "row": row, "input_sha256": sha}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_snapshot(audit: Path, *, approve_public_aggregates: bool = False,
                   previous_qc_summary: Path | None = None) -> dict:
    """Pure build: explicit opt-in, allowlisted fields, counts from actual rows.

    The caller is responsible for scientific approval in the source audit. This
    exporter neither validates private approval records nor issues approval.
    """
    if approve_public_aggregates is not True:
        raise PublicSnapshotError("Public aggregate export requires --approve-public-aggregates")
    audit = Path(audit)
    names = ("execution_audit.json", "assay_master_registry.tsv",
             "task_scientific_registry.tsv", "hold_and_exclusion_log.tsv")
    raw = {name: _read(audit / name) for name in names}
    digests = {name: _digest(data) for name, data in raw.items()}
    execution = _json(raw[names[0]], names[0])
    if not isinstance(execution.get("summary"), dict):
        raise PublicSnapshotError("execution_audit.json requires a summary object")
    declared = {k: _count(v, k) for k, v in execution["summary"].items()
                if k in PUBLIC_SUMMARY_COUNTS}
    task_rows = _tsv(raw[names[2]], names[2], TASK_FIELDS)
    assay_rows = _tsv(raw[names[1]], names[1], ASSAY_FIELDS)
    hold_rows = _tsv(raw[names[3]], names[3], {"task_id"})
    tasks, assays, task_ids, assay_ids = [], [], set(), set()
    for row_number, row in enumerate(task_rows, 2):
        task_id = _id(row["task_id"], "task_id")
        if task_id in task_ids:
            raise PublicSnapshotError("Duplicate task_id")
        task_ids.add(task_id)
        stage, disposition = row["scientific_stage"], row["disposition"]
        if stage not in STAGES:
            raise PublicSnapshotError("Unknown scientific_stage")
        if not re.fullmatch(r"(?:HOLD|EXCLUDED)(?:_[A-Z0-9_]+)?|SECONDARY_PROXY|"
                            r"ADMITTED(?:_CORE|_EXTENDED)?|ADMISSION_CANDIDATE|"
                            r"NOT_REVIEWED|REVIEW_READY", disposition):
            raise PublicSnapshotError("Unknown scientific disposition")
        verification = _verification(row["verification_status"])
        if ((stage == "ADMITTED") != (disposition in ADMITTED) or
                disposition in ADMITTED and verification != "VERIFIED"):
            raise PublicSnapshotError("Inconsistent ADMITTED state; scientific approval cannot be inferred")
        reasons = _reason_codes(row["blocking_reasons"])
        if disposition in ADMITTED and reasons:
            raise PublicSnapshotError("ADMITTED task still declares blocking reasons")
        tasks.append({"task_id": task_id,
                      "package_group_id": _id(row["package_group_id"], "package_group_id"),
                      "scientific_stage": stage, "disposition": disposition,
                      "verification_status": verification, "blocking_categories": reasons,
                      "evidence_available": bool(row["evidence_paths"].strip()),
                      "evidence_reference": _reference(names[2], row_number, digests[names[2]])})
    for row_number, row in enumerate(assay_rows, 2):
        assay_id = _id(row["canonical_assay_id"], "canonical_assay_id")
        if assay_id in assay_ids:
            raise PublicSnapshotError("Duplicate canonical_assay_id")
        assay_ids.add(assay_id)
        item = {field: _text(row[field], field) for field in (
            "original_assay_id", "source_project", "source_doi", "experiment_accession",
            "biological_readout", "label_definition", "label_unit", "data_license", "qc_status")}
        if item["source_doi"] and not re.fullmatch(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", item["source_doi"]):
            raise PublicSnapshotError("source_doi must be a DOI, not an unverified substitute URL")
        item.update(canonical_assay_id=assay_id,
                    verification_status=_verification(row["verification_status"]),
                    evidence_url=_url(row["evidence_url"]),
                    evidence_reference=_reference(names[1], row_number, digests[names[1]]))
        assays.append(item)
    for row in hold_rows:
        if row["task_id"].strip() and row["task_id"] not in task_ids:
            raise PublicSnapshotError("Hold log references an unknown task_id")
    stages = Counter(t["scientific_stage"] for t in tasks)
    dispositions = Counter(t["disposition"] for t in tasks)
    counts = {
        "registered_tasks": len(tasks), "package_groups": len({t["package_group_id"] for t in tasks}),
        "assays": len(assays), "admitted_tasks": sum(dispositions[s] for s in ADMITTED),
        "admission_candidate_tasks": sum(t["scientific_stage"] == "ADMISSION_CANDIDATE" and
                                          not t["disposition"].startswith(("HOLD", "EXCLUDED")) for t in tasks),
        "file_qc_pass_tasks": stages["FILE_QC_PASS"],
        "held_tasks": sum(v for k, v in dispositions.items() if k.startswith("HOLD")),
        "excluded_tasks": sum(v for k, v in dispositions.items() if k.startswith("EXCLUDED")),
        "source_verified_tasks": stages["SOURCE_VERIFIED"],
        "assay_verified_tasks": stages["ASSAY_VERIFIED"],
        "split_qc_pass_tasks": stages["SPLIT_QC_PASS"],
    }
    for key, value in declared.items():
        if value != counts[key]:
            raise PublicSnapshotError(f"Audit summary disagrees with source rows for {key}")
    if counts["admitted_tasks"] and "admitted_tasks" not in declared:
        raise PublicSnapshotError("ADMITTED requires an explicit matching source-audit summary count")
    held_reasons = Counter(code for t in tasks if t["disposition"].startswith("HOLD")
                          for code in t["blocking_categories"])
    snapshot = {
        "schema_version": SCHEMA,
        "public_aggregate_approval": {"explicit": True, "scope": "PUBLIC_AGGREGATES_ONLY_NOT_ASSAY_APPROVAL"},
        "run_id": _id(execution["run_id"], "run_id") if execution.get("run_id") else None,
        "counts": counts,
        "stage_counts": dict(sorted(stages.items())),
        "disposition_counts": dict(sorted(dispositions.items())),
        "hold_reason_counts": dict(sorted(held_reasons.items())),
        "tasks": sorted(tasks, key=lambda t: t["task_id"]),
        "assays": sorted(assays, key=lambda a: a["canonical_assay_id"]),
        "sources": [{"file": name, "sha256": digests[name], "row_count": count}
                    for name, count in zip(names, (None, len(assays), len(tasks), len(hold_rows)))],
        "baseline_protocols": [dict(p, methods=list(p["methods"]),
                                    status="PROTOCOL_ONLY_NOT_TASK_VALIDATED") for p in BASELINE_PROTOCOLS],
        "fm_tracks": list(FM_TRACKS),
        "leaderboards": {"rna_fm": [], "rna_llm": [], "rna_agent": []},
        "results_publication_enabled": False,
        "previous_technical_snapshot": None,
        "warnings": [
            "File QC and regression-test success are not scientific admission.",
            "Assay candidates/source records are NOT an independent experimental assay count.",
            "Assay and task lists are separate; package equality does not establish assay identity.",
            "No sample counts, raw labels, sample identity maps, private paths or approval records are exported.",
            "Stage counts are exact declared states, not cumulative QC coverage.",
            "Public aggregate approval does not grant data redistribution or scientific admission.",
            "Protocol catalogue entries are not executed baselines or task-validated configurations.",
        ],
    }
    if previous_qc_summary is not None:
        data = _read(Path(previous_qc_summary))
        prior = _json(data, "previous QC summary")
        snapshot["previous_technical_snapshot"] = {
            "scope": "PREVIOUS_TECHNICAL_SNAPSHOT_NOT_CURRENT_ADMISSION",
            "run_id": _id(prior["run_id"], "previous run_id") if prior.get("run_id") else None,
            "source_sha256": _digest(data),
            "counts": {k: _count(v, k) for k, v in prior.items() if k in PRIOR_COUNTS},
        }
    encoded = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    snapshot["snapshot_id"] = "p2-" + _digest(encoded)
    return snapshot


def write_snapshot(snapshot: dict, output: Path) -> tuple[Path, bool]:
    """Write once without clobbering a different approved snapshot."""
    payload = {key: value for key, value in snapshot.items() if key != "snapshot_id"}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    if (snapshot.get("schema_version") != SCHEMA or
            snapshot.get("public_aggregate_approval") != {
                "explicit": True, "scope": "PUBLIC_AGGREGATES_ONLY_NOT_ASSAY_APPROVAL"} or
            snapshot.get("snapshot_id") != "p2-" + _digest(encoded) or
            snapshot.get("results_publication_enabled") is not False or
            snapshot.get("leaderboards") != {"rna_fm": [], "rna_llm": [], "rna_agent": []}):
        raise PublicSnapshotError("Only an intact approved builder snapshot may be written")
    output = Path(output)
    protected = (ROOT / "site" / "data").resolve()
    resolved = output.resolve()
    if resolved == protected or protected in resolved.parents:
        raise PublicSnapshotError("Existing site/data is protected; use a new Phase 2 data target")
    data = (json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / SNAPSHOT_NAME
    if destination.is_symlink():
        raise PublicSnapshotError("Refusing symlinked snapshot destination")
    if destination.exists():
        if destination.read_bytes() != data:
            raise PublicSnapshotError("Immutable snapshot differs; choose a new versioned output directory")
        return destination, False
    fd, temporary = tempfile.mkstemp(prefix=".phase2-", dir=output)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o444)
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            if destination.is_symlink() or destination.read_bytes() != data:
                raise PublicSnapshotError("Concurrent snapshot differs; refusing replacement") from exc
        return destination, True
    finally:
        os.unlink(temporary)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True, help="Phase 2 report directory")
    parser.add_argument("--output", type=Path, required=True, help="New aggregate-only site data directory")
    parser.add_argument("--approve-public-aggregates", action="store_true",
                        help="Explicitly authorize only this allowlisted metadata export, not scientific admission")
    parser.add_argument("--previous-qc-summary", type=Path,
                        help="Optional prior QC JSON; counts are labeled as historical technical evidence")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report counts without writing")
    args = parser.parse_args(argv)
    try:
        snapshot = build_snapshot(args.audit, approve_public_aggregates=args.approve_public_aggregates,
                                  previous_qc_summary=args.previous_qc_summary)
        if not args.dry_run:
            _, created = write_snapshot(snapshot, args.output)
        else:
            created = False
        print(json.dumps({"snapshot_id": snapshot["snapshot_id"], "counts": snapshot["counts"],
                          "dry_run": args.dry_run, "created": created,
                          "public_export": "APPROVED_AGGREGATES_ONLY", "model_scores": 0}, sort_keys=True))
        return 0
    except (OSError, PublicSnapshotError) as exc:
        # Avoid echoing local input values or paths in CI/public logs.
        message = str(exc) if isinstance(exc, PublicSnapshotError) else "Local input/output unavailable"
        print(f"Phase 2 snapshot blocked: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
