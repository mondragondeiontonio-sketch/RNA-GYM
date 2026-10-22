"""Independent Phase 2 export tests; fixtures contain no real experimental data."""
from __future__ import annotations

import contextlib
import csv
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_phase2_site", ROOT / "tools/build_phase2_site.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def write_tsv(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def task(task_id="T0001", **updates):
    row = {"task_id": task_id, "package_group_id": "MIR_BENCH", "scientific_stage": "FILE_QC_PASS",
           "disposition": "HOLD_SOURCE", "verification_status": "PROVISIONAL",
           "blocking_reasons": "Original assay source; license; human review",
           "evidence_paths": "/private/local-only/audit.json"}
    row.update(updates)
    return row


def assay(**updates):
    row = {"canonical_assay_id": "TEMP_ASSAY_01", "original_assay_id": "unknown",
           "source_project": "Synthetic fixture only", "source_doi": "unknown",
           "experiment_accession": "unknown", "biological_readout": "Synthetic regression",
           "label_definition": "Synthetic scalar, not a real assay", "label_unit": "unknown",
           "data_license": "unknown", "qc_status": "FILE_QC_PASS",
           "verification_status": "PROVISIONAL", "evidence_url": "https://doi.org/10.0000/fixture"}
    row.update(updates)
    return row


def fixture(root, tasks=None, assays=None, summary=None):
    root.mkdir(parents=True, exist_ok=True)
    tasks = [task()] if tasks is None else tasks
    assays = [assay()] if assays is None else assays
    execution = {"run_id": "fixture_phase2", "summary": summary or {},
                 "private_path": "/private/do-not-publish", "reviewer": "DO_NOT_EXPORT_PERSON"}
    (root / "execution_audit.json").write_text(json.dumps(execution), encoding="utf-8")
    write_tsv(root / "task_scientific_registry.tsv", sorted(builder.TASK_FIELDS), tasks)
    write_tsv(root / "assay_master_registry.tsv", sorted(builder.ASSAY_FIELDS), assays)
    write_tsv(root / "hold_and_exclusion_log.tsv", ["task_id", "reason", "private_path"],
              [{"task_id": t["task_id"], "reason": "Private scientific notes", "private_path": "/private/local-only"}
               for t in tasks if t["disposition"].startswith(("HOLD", "EXCLUDED"))])
    return root


class Phase2SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audit = fixture(self.root / "reports")

    def build(self, **options):
        return builder.build_snapshot(self.audit, approve_public_aggregates=True, **options)

    def test_explicit_approval_required_even_for_dry_run(self):
        with self.assertRaisesRegex(builder.PublicSnapshotError, "approve-public-aggregates"):
            builder.build_snapshot(self.audit)
        output = self.root / "not-created"
        with contextlib.redirect_stderr(io.StringIO()):
            status = builder.main(["--audit", str(self.audit), "--output", str(output), "--dry-run"])
        self.assertEqual(status, 2)
        self.assertFalse(output.exists())

    def test_approved_snapshot_is_deterministic_and_counts_actual_rows(self):
        tasks = [task(), task("XSCOPE_SYNTHETIC", scientific_stage="ADMISSION_CANDIDATE",
                             disposition="ADMISSION_CANDIDATE", blocking_reasons=""),
                 task("X0002", scientific_stage="EXCLUDED", disposition="EXCLUDED_NON_ASSAY")]
        fixture(self.audit, tasks=tasks)
        snapshot = self.build()
        self.assertEqual(snapshot, self.build())
        self.assertEqual(snapshot["counts"]["registered_tasks"], 3)
        self.assertEqual(snapshot["counts"]["admission_candidate_tasks"], 1)
        self.assertEqual(snapshot["counts"]["admitted_tasks"], 0)
        self.assertEqual(snapshot["counts"]["file_qc_pass_tasks"], 1)
        self.assertEqual(snapshot["counts"]["excluded_tasks"], 1)
        self.assertEqual(snapshot["tasks"][0]["evidence_reference"]["row"], 2)
        for source in snapshot["sources"]:
            self.assertEqual(source["sha256"], hashlib.sha256((self.audit / source["file"]).read_bytes()).hexdigest())

    def test_empty_assay_registry_does_not_promote_tasks_to_assays(self):
        fixture(self.audit, assays=[])
        snapshot = self.build()
        self.assertEqual(snapshot["counts"]["assays"], 0)
        self.assertEqual(snapshot["counts"]["registered_tasks"], 1)
        self.assertEqual(snapshot["assays"], [])

    def test_input_summary_mismatch_is_blocked(self):
        fixture(self.audit, summary={"registered_tasks": 198})
        with self.assertRaisesRegex(builder.PublicSnapshotError, "disagrees"):
            self.build()
        fixture(self.audit, summary={"admitted_tasks": True})
        with self.assertRaisesRegex(builder.PublicSnapshotError, "integer"):
            self.build()

    def test_file_qc_and_candidate_never_infer_admission(self):
        for stage, disposition in [("FILE_QC_PASS", "HOLD_SOURCE"),
                                   ("ADMISSION_CANDIDATE", "ADMISSION_CANDIDATE")]:
            fixture(self.audit, tasks=[task(scientific_stage=stage, disposition=disposition)])
            self.assertEqual(self.build()["counts"]["admitted_tasks"], 0)
        fixture(self.audit, tasks=[task(scientific_stage="ADMITTED", disposition="ADMITTED",
                                       verification_status="PROVISIONAL")])
        with self.assertRaisesRegex(builder.PublicSnapshotError, "Inconsistent ADMITTED"):
            self.build()
        fixture(self.audit, tasks=[task(scientific_stage="ADMITTED", disposition="ADMITTED",
                                       verification_status="VERIFIED", blocking_reasons="")])
        with self.assertRaisesRegex(builder.PublicSnapshotError, "explicit matching"):
            self.build()

    def test_verified_admission_is_only_reflected_from_consistent_source_audit(self):
        fixture(self.audit, tasks=[task(scientific_stage="ADMITTED", disposition="ADMITTED_CORE",
                                       verification_status="VERIFIED", blocking_reasons="")],
                summary={"admitted_tasks": 1})
        snapshot = self.build()
        self.assertEqual(snapshot["counts"]["admitted_tasks"], 1)
        self.assertEqual(snapshot["public_aggregate_approval"]["scope"],
                         "PUBLIC_AGGREGATES_ONLY_NOT_ASSAY_APPROVAL")
        self.assertEqual(snapshot["leaderboards"]["rna_fm"], [])

    def test_private_fields_and_evidence_paths_are_never_serialized(self):
        rows = [task(raw_label="HIDDEN_LABEL_SENTINEL", sample_identity="IDENTITY_SENTINEL",
                     approval_secret="APPROVAL_SENTINEL", reviewer="REVIEWER_SENTINEL")]
        write_tsv(self.audit / "task_scientific_registry.tsv", sorted(set(builder.TASK_FIELDS) | set(rows[0])), rows)
        data = json.loads((self.audit / "execution_audit.json").read_text())
        data["summary"].update(raw_labels=["SECRET_LABEL"], sample_identity="SECRET_MAP",
                               approval_secret="SECRET_APPROVAL", secret="SENSITIVE_TOKEN_SENTINEL")
        (self.audit / "execution_audit.json").write_text(json.dumps(data))
        serialized = json.dumps(self.build())
        for private in ["/private/", "DO_NOT_EXPORT_PERSON", "HIDDEN_LABEL_SENTINEL", "IDENTITY_SENTINEL",
                        "APPROVAL_SENTINEL", "REVIEWER_SENTINEL", "SECRET_LABEL", "SECRET_MAP",
                        "SECRET_APPROVAL", "SENSITIVE_TOKEN_SENTINEL", "evidence_paths"]:
            self.assertNotIn(private, serialized)
        self.assertIn("RIGHTS", serialized)
        self.assertIn("SOURCE", serialized)

    def test_secrets_private_paths_raw_sequences_and_vectors_in_allowed_fields_are_blocked(self):
        unsafe = ["github_pat_" + "SYNTHETIC" * 5, "ghp_" + "A" * 36,
                  "hf_" + "SYNTHETIC" * 4, "Bearer SYNTHETIC_SECRET",
                  "/" + "sibcb1/private/lab/raw.tsv", "see /" + "home/person/private.tsv", "C:\\Users\\private.txt",
                  "see /arbitrary/location/raw.tsv", "file:///private/labels", "person@example.org",
                  "%2Fhome%2Fperson%2Fraw.tsv", "AUGC" * 20, "[0.1, 0.3, 0.5]",
                  "<script>unsafe</script>"]
        for value in unsafe:
            with self.subTest(value=value[:20]):
                fixture(self.audit, assays=[assay(label_definition=value)])
                with self.assertRaisesRegex(builder.PublicSnapshotError, "Unsafe"):
                    self.build()

    def test_signed_private_or_unsafe_evidence_urls_are_blocked(self):
        urls = ["http://doi.org/10.0000/fixture", "https://doi.org/10.0000/fixture?" + "token=" + "SYNTHETIC",
                "https://name:password@github.com/public/repo", "https://127.0.0.1/private",
                "file:///private/source", "https://unapproved.example.org/source",
                "https://github.com.evil.example/source", "https://github.com/source#token",
                "https://doi.org:bad/fixture"]
        for value in urls:
            with self.subTest(value=value):
                fixture(self.audit, assays=[assay(evidence_url=value)])
                with self.assertRaises(builder.PublicSnapshotError):
                    self.build()

    def test_doi_and_unknown_source_fields_remain_explicit(self):
        snapshot = self.build()
        self.assertIsNone(snapshot["assays"][0]["source_doi"])
        self.assertIsNone(snapshot["assays"][0]["original_assay_id"])
        fixture(self.audit, assays=[assay(source_doi="https://doi.org/10.0000/fixture")])
        with self.assertRaisesRegex(builder.PublicSnapshotError, "source_doi"):
            self.build()

    def test_all_score_tracks_are_empty_even_if_input_contains_scores(self):
        execution = json.loads((self.audit / "execution_audit.json").read_text())
        execution["leaderboards"] = {"rna_fm": [{"score": 0.99, "model": "NOT_MEASURED"}]}
        (self.audit / "execution_audit.json").write_text(json.dumps(execution))
        snapshot = self.build()
        self.assertFalse(snapshot["results_publication_enabled"])
        self.assertEqual(snapshot["leaderboards"], {"rna_fm": [], "rna_llm": [], "rna_agent": []})
        self.assertNotIn("NOT_MEASURED", json.dumps(snapshot))
        self.assertEqual(len(snapshot["fm_tracks"]), 6)
        self.assertTrue(all(p["status"] == "PROTOCOL_ONLY_NOT_TASK_VALIDATED"
                            for p in snapshot["baseline_protocols"]))

    def test_optional_prior_counts_are_labeled_and_never_current_admission(self):
        prior = self.root / "previous.json"
        prior.write_text(json.dumps({"run_id": "old_fixture", "local_acquired_artifacts": 45,
                                     "local_raw_artifact_bytes_including_reassembly": 6573002784,
                                     "final_admitted_assays": 900, "private_path": "/private/sentinel"}))
        snapshot = self.build(previous_qc_summary=prior)
        historical = snapshot["previous_technical_snapshot"]
        self.assertEqual(historical["scope"], "PREVIOUS_TECHNICAL_SNAPSHOT_NOT_CURRENT_ADMISSION")
        self.assertEqual(historical["counts"]["local_acquired_artifacts"], 45)
        self.assertNotIn("final_admitted_assays", historical["counts"])
        self.assertEqual(snapshot["counts"]["admitted_tasks"], 0)
        self.assertNotIn("/private/", json.dumps(snapshot))

    def test_missing_duplicate_ragged_and_bad_encoding_inputs_fail_closed(self):
        path = self.audit / "task_scientific_registry.tsv"
        original = path.read_bytes()
        invalids = [b"task_id\ttask_id\nT01\tT02\n", b"\xff\xfe invalid", original + b"too\tfew\n"]
        for invalid in invalids:
            path.write_bytes(invalid)
            with self.assertRaises(builder.PublicSnapshotError):
                self.build()
        path.write_bytes(original)
        fixture(self.audit, tasks=[task(), task()])
        with self.assertRaisesRegex(builder.PublicSnapshotError, "Duplicate task_id"):
            self.build()
        fixture(self.audit, assays=[assay(), assay()])
        with self.assertRaisesRegex(builder.PublicSnapshotError, "Duplicate canonical"):
            self.build()
        path.unlink()
        with self.assertRaises(builder.PublicSnapshotError):
            self.build()

    def test_bad_stage_disposition_unknown_hold_task_and_symlink_are_blocked(self):
        for changes in [{"scientific_stage": "AUTOPASS"}, {"verification_status": "PASSED"},
                        {"disposition": "unknown"}, {"task_id": "../../private"}]:
            fixture(self.audit, tasks=[task(**changes)])
            with self.assertRaises(builder.PublicSnapshotError):
                self.build()
        fixture(self.audit)
        write_tsv(self.audit / "hold_and_exclusion_log.tsv", ["task_id"], [{"task_id": "T9999"}])
        with self.assertRaisesRegex(builder.PublicSnapshotError, "unknown task"):
            self.build()
        fixture(self.audit)
        path = self.audit / "assay_master_registry.tsv"
        target = self.root / "elsewhere.tsv"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
        with self.assertRaisesRegex(builder.PublicSnapshotError, "symlinked"):
            self.build()

    def test_immutable_output_is_reused_not_overwritten(self):
        snapshot = self.build()
        output = self.root / "version1"
        path, created = builder.write_snapshot(snapshot, output)
        self.assertTrue(created)
        self.assertEqual(path.name, builder.SNAPSHOT_NAME)
        before = path.read_bytes()
        self.assertEqual(path.stat().st_mode & 0o222, 0)
        _, created = builder.write_snapshot(snapshot, output)
        self.assertFalse(created)
        fixture(self.audit, tasks=[task("T0002")])
        changed = self.build()
        with self.assertRaisesRegex(builder.PublicSnapshotError, "Immutable"):
            builder.write_snapshot(changed, output)
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaisesRegex(builder.PublicSnapshotError, "protected"):
            builder.write_snapshot(snapshot, ROOT / "site/data/phase2")

    def test_writer_rejects_unapproved_or_modified_payload(self):
        output = self.root / "must-not-exist"
        with self.assertRaisesRegex(builder.PublicSnapshotError, "intact approved"):
            builder.write_snapshot({"private_path": "/private/raw-labels"}, output)
        self.assertFalse(output.exists())
        snapshot = self.build()
        snapshot["private_path"] = "/private/approval-secret"
        with self.assertRaisesRegex(builder.PublicSnapshotError, "intact approved"):
            builder.write_snapshot(snapshot, output)
        self.assertFalse(output.exists())

    def test_cli_dry_run_no_output_then_real_opt_in(self):
        output = self.root / "data"
        args = ["--audit", str(self.audit), "--output", str(output), "--approve-public-aggregates"]
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            self.assertEqual(builder.main(args + ["--dry-run"]), 0)
        self.assertFalse(output.exists())
        self.assertTrue(json.loads(capture.getvalue())["dry_run"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(builder.main(args), 0)
        self.assertTrue((output / builder.SNAPSHOT_NAME).is_file())

    def test_duplicate_json_keys_are_rejected(self):
        (self.audit / "execution_audit.json").write_text('{"summary":{},"summary":{}}')
        with self.assertRaisesRegex(builder.PublicSnapshotError, "Duplicate JSON"):
            self.build()

    def test_page_has_accessible_independent_sections_and_no_unsafe_dom_sinks(self):
        page = (ROOT / "site/phase2.html").read_text()
        script = (ROOT / "site/phase2.js").read_text()
        css = (ROOT / "site/phase2.css").read_text()
        for section in ["atlas", "qc", "baselines", "fm", "llm", "agent", "methods"]:
            self.assertIn(f'id="{section}"', page)
        self.assertIn('name="viewport"', page)
        self.assertIn('class="skip-link"', page)
        self.assertIn('aria-live="polite"', page)
        self.assertIn('scope="col"', page)
        self.assertIn('prefers-reduced-motion', css)
        self.assertIn(':focus-visible', css)
        for unsafe in ["innerHTML", "outerHTML", "document.write", "eval("]:
            self.assertNotIn(unsafe, script)
        self.assertNotIn("https://", page)
        self.assertNotIn("data/summary.json", script)
        self.assertEqual(page.count('data-leaderboard='), 3)


BROWSER_SCRIPT = r"""
(async () => {
  const result = document.getElementById('result');
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const wait = async (fn) => { for (let i = 0; i < 150; i++) { if (fn()) return; await new Promise(r => setTimeout(r, 50)); } throw new Error('Timed out'); };
  try {
    const frame = document.getElementById('desktop');
    const mobile = document.getElementById('mobile');
    const empty = document.getElementById('empty');
    await wait(() => [frame, mobile].every(f => f.contentDocument?.getElementById('snapshotStatus')?.dataset.state === 'ready'));
    await wait(() => empty.contentDocument?.getElementById('snapshotStatus')?.dataset.state === 'unavailable');
    const d = frame.contentDocument, m = mobile.contentDocument;
    assert(d.getElementById('registeredCount').textContent === '25', 'Exact registry count');
    assert(d.getElementById('admittedCount').textContent === '0', 'No automatic admission');
    assert(d.querySelectorAll('#taskRows tr').length === 20, 'Task pagination');
    d.getElementById('nextPage').click();
    assert(d.querySelectorAll('#taskRows tr').length === 5, 'Second page');
    const search = d.getElementById('taskSearch');
    search.value = 'T0001'; search.dispatchEvent(new frame.contentWindow.Event('input', {bubbles: true}));
    assert(d.getElementById('taskResultCount').textContent.startsWith('1 of 25'), 'Task search');
    search.value = ''; search.dispatchEvent(new frame.contentWindow.Event('input', {bubbles: true}));
    const filter = d.getElementById('dispositionFilter'); filter.value = 'EXCLUDED_NON_ASSAY';
    filter.dispatchEvent(new frame.contentWindow.Event('change', {bubbles: true}));
    assert(d.getElementById('taskResultCount').textContent.startsWith('1 of 25'), 'Disposition filter');
    d.getElementById('resetFilters').click(); await new Promise(r => setTimeout(r, 30));
    assert(d.getElementById('taskResultCount').textContent.startsWith('25 of 25'), 'Reset filters');
    d.getElementById('assaySearch').value = 'no match';
    d.getElementById('assaySearch').dispatchEvent(new frame.contentWindow.Event('input'));
    assert(d.getElementById('assayResultCount').textContent.startsWith('0 of 1'), 'Assay search');
    d.getElementById('baselineSearch').value = 'seed matching';
    d.getElementById('baselineSearch').dispatchEvent(new frame.contentWindow.Event('input'));
    assert(d.querySelectorAll('.baseline-card').length === 1, 'Baseline search');
    assert(d.querySelectorAll('[data-leaderboard]').length === 3, 'Independent score-free sections');
    assert([...d.querySelectorAll('[data-leaderboard]')].every(e => e.textContent.includes('No reviewed')), 'No score rows');
    assert(m.documentElement.scrollWidth <= mobile.clientWidth + 1, 'Mobile document must not overflow');
    assert(m.getElementById('taskSearch').getBoundingClientRect().width > 200, 'Mobile input fits');
    assert(m.querySelector('.table-scroll').scrollWidth > m.querySelector('.table-scroll').clientWidth, 'Table scrolls inside panel');
    assert(empty.contentDocument.getElementById('registeredCount').textContent === 'N/A', 'Unavailable snapshot is not zero');
    result.dataset.status = 'pass'; result.textContent = 'PASS: real browser search, filters, pagination, mobile and missing-snapshot behavior';
  } catch (error) { result.dataset.status = 'fail'; result.textContent = error.stack; }
})();
"""


@unittest.skipUnless(os.environ.get("RNAGYM_BROWSER_TESTS") == "1", "Set RNAGYM_BROWSER_TESTS=1 for real Chrome")
class Phase2BrowserTests(unittest.TestCase):
    def test_real_browser_accessible_filters_mobile_and_empty_scores(self):
        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        if not chrome:
            self.skipTest("Chrome/Chromium unavailable; no dependency downloaded")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tasks = [task(f"T{i:04d}") for i in range(1, 25)] + [
                task("X0001", scientific_stage="EXCLUDED", disposition="EXCLUDED_NON_ASSAY")]
            audit = fixture(root / "reports", tasks=tasks)
            web = root / "web"
            web.mkdir()
            for name in ("phase2.html", "phase2.js", "phase2.css"):
                shutil.copyfile(ROOT / "site" / name, web / name)
            builder.write_snapshot(builder.build_snapshot(audit, approve_public_aggregates=True), web / "phase2-data")
            # A second directory serves the same page but deliberately no snapshot.
            empty = web / "empty"
            empty.mkdir()
            for name in ("phase2.html", "phase2.js", "phase2.css"):
                shutil.copyfile(web / name, empty / name)
            harness = ('<!doctype html><html><body><pre id="result" data-status="pending"></pre>'
                       '<iframe id="desktop" title="Desktop preview" src="/phase2.html" style="width:1280px;height:900px;border:0"></iframe>'
                       '<iframe id="mobile" title="Mobile preview" src="/phase2.html" style="width:375px;height:900px;border:0"></iframe>'
                       '<iframe id="empty" title="Missing snapshot preview" src="/empty/phase2.html"></iframe>'
                       '<script>' + BROWSER_SCRIPT + '</script></body></html>')
            (web / "harness.html").write_text(harness)

            class Handler(SimpleHTTPRequestHandler):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, directory=str(web), **kwargs)

                def log_message(self, *_):
                    pass

            with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    result = subprocess.run([
                        chrome, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                        "--no-proxy-server", "--disable-background-networking", f"--user-data-dir={root / 'chrome'}",
                        "--virtual-time-budget=20000", "--dump-dom", f"http://127.0.0.1:{server.server_port}/harness.html",
                    ], text=True, capture_output=True, timeout=60)
                    self.assertEqual(result.returncode, 0, result.stderr[-2000:])
                    self.assertIn('id="result" data-status="pass"', result.stdout,
                                  result.stdout.split("</pre>", 1)[0][-3500:])
                finally:
                    server.shutdown()
                    thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
