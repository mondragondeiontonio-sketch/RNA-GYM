# Phase 2 audit website

> Independent evidence-first preview; no model scores, deployment or downloads.

## Scope and verification status

**PROVISIONAL integration:** the standalone page and exporter are ready for
integration testing. A real Phase 2 snapshot is not bundled here. Main must
review the audit evidence and approve public aggregates before generating a
served snapshot. No claim of a deployed page, admitted task or successful model
run is made by this workstream.

The owned implementation consists only of:

- `site/phase2.html`
- `site/phase2.js`
- `site/phase2.css`
- `tools/build_phase2_site.py`
- `tests/test_phase2_site.py`
- `docs/PHASE2_WEBSITE.md`

The existing homepage, JavaScript, CSS, generator and `site/data` are unchanged.
No snapshot is copied into the public site automatically.

## Design and navigation

The page serves RNA benchmark reviewers who need to distinguish a registered
task from an original experiment. Its central visual is the required provenance
chain, not a simulated score or a claim that every link has been verified.

The visual system uses mist blue `#f2f6fb`, white `#ffffff`, ink `#1c3352`,
indigo `#394aa5`, teal `#126d68` and amber `#8a5010`. A local display stack
(`Avenir Next`, `Trebuchet MS`) contrasts with the body and monospace evidence
stacks. No external fonts, analytics or raster assets are requested.

Sections include:

- Dataset Atlas: paginated task table and separate assay provenance cards.
- QC dashboard: exact current stages, categorized HOLDs and optional historical
  technical counts.
- Baseline Explorer: searchable protocol families, explicitly not task-validated
  executable configurations or completed experiments.
- RNA-FM leaderboard: six distinct adaptation tracks, with no results.
- RNA-LLM leaderboard and RNA-Agent arena: independent, empty result sections.
- Methods and reproducibility: identity, split, readout and publication rules.

The interface supports search, categorical filters, keyboard focus, labeled
controls, live result counts, a skip link, reduced motion and small screens.
Tables scroll inside their own panel instead of overflowing the document.

## Input contract

Pass a Phase 2 **report directory**, not the whole run root, to `--audit`.
The directory must contain all four files below, even when a TSV has only a
header. UTF-8/UTF-8-BOM and properly quoted TSV are accepted; malformed or
ragged inputs, duplicate identities and symlinked input files are blocked.
Inputs are capped at 16 MiB each; this is an aggregate interface, not a sample
identity or raw measurement export.

### Task scientific registry

`task_scientific_registry.tsv` requires these columns:

```text
task_id
package_group_id
scientific_stage
disposition
verification_status
blocking_reasons
evidence_paths
```

Scientific stages are `NOT_REVIEWED`, `FILE_QC_PASS`, `SOURCE_VERIFIED`,
`ASSAY_VERIFIED`, `SPLIT_QC_PASS`, `ADMISSION_CANDIDATE`, `ADMITTED`, `HOLD`
and `EXCLUDED`.

Verification is `VERIFIED`, `PROVISIONAL` or `BLOCKED`. Disposition accepts
`HOLD_*`, `EXCLUDED_*`, `ADMITTED_CORE`, `ADMITTED_EXTENDED`, `ADMITTED`,
`SECONDARY_PROXY`, `ADMISSION_CANDIDATE`, `REVIEW_READY` or `NOT_REVIEWED`.
Plain `HOLD` and `EXCLUDED` are also accepted.

`evidence_paths` is never serialized. It contributes only an evidence-present
boolean. Each public record has a metadata input filename, a data-row reference
and that input's SHA256. Row references start at 2; they are record positions,
not physical line numbers when quoted TSV values span multiple lines.

`blocking_reasons` is private free text. The exporter emits only categories:
rights, original source, assay identity, label semantics, split/leakage, QC,
human review, safe format, acquisition or other review required. It never
publishes the original reason or a path embedded in it. One task can contribute
to several HOLD reason categories; these counts need not sum to held tasks.

### Assay registry

`assay_master_registry.tsv` requires these columns:

```text
canonical_assay_id
original_assay_id
source_project
source_doi
experiment_accession
biological_readout
label_definition
label_unit
data_license
qc_status
verification_status
evidence_url
```

Empty or explicitly unknown source values remain null. A DOI must have DOI
syntax; a reachable link is not used to invent an accession, original DOI or
license. Public semantic descriptions are allowed; raw labels and sequence
records are not. Source URLs must use HTTPS, have no credentials, query string
or fragment, and match an explicit public-source domain allowlist. Unrecognized
sources require a reviewed code change; the builder never falls back to copying
unvalidated URLs.

The public assay and task lists remain **unlinked** unless an independently
reviewed mapping is provided in a future contract. Equality of package names
is not used to invent assay-to-task relationships.

### Execution audit and hold log

`execution_audit.json` requires a `summary` object and may contain a safe
`run_id`. Only known integer count keys are considered. Unknown fields,
reviewers, signatures, raw labels, model scores and private paths are ignored.

All public current counts are computed from the task and assay rows. If the
summary declares one of those counts, it must match. In particular,
`file_qc_pass_tasks`, `source_verified_tasks`, `assay_verified_tasks` and
`split_qc_pass_tasks` count **exact stage states**, not cumulative coverage.
A task at `ASSAY_VERIFIED` is not also counted as currently `FILE_QC_PASS`.
`admission_candidate_tasks` excludes candidates with HOLD/EXCLUDED disposition.

An `ADMITTED` stage must have an admitted disposition, `VERIFIED` evidence,
no declared blockers and an explicit matching `summary.admitted_tasks` count.
This only checks source-audit consistency. It does **not** verify a private
reviewer signature or create scientific admission: main must enforce the real
admission gate before presenting that status. The explicit public export flag
is never a substitute for scientific review or data redistribution rights.

`hold_and_exclusion_log.tsv` requires `task_id`; other columns are never
published. Nonempty task references must exist in the scientific registry.
Its hash and row count are public evidence that the log was included, not a
claim that its private free text can be redistributed.

### Optional previous technical summary

`--previous-qc-summary` may point to an existing prior `qc_summary.json`.
Only allowlisted nonnegative technical counts, safe run ID and the input hash
are exported. The UI labels this **previous technical snapshot, not current
admission**. Prior admission fields and private paths are not exported.

For example, the prior 45 acquired artifacts and 6,573,002,784 artifact bytes
may be shown only when explicitly supplied from that existing evidence file.
They must not be described as 45 assays or substituted for task sample counts.
No historical numbers are hardcoded into the UI or default snapshot.

## Build and inspect

Start with a dry run; replace `<new_run>` with the real Phase 2 run ID:

```bash
.venv-qc/bin/python tools/build_phase2_site.py \
  --audit runs/<new_run>/reports \
  --output runs/<new_run>/website-candidate/phase2-data \
  --approve-public-aggregates \
  --dry-run
```

After reviewing the intended public metadata, build the candidate:

```bash
.venv-qc/bin/python tools/build_phase2_site.py \
  --audit runs/<new_run>/reports \
  --output runs/<new_run>/website-candidate/phase2-data \
  --approve-public-aggregates \
  --previous-qc-summary runs/20261022_212625/reports/qc_summary.json
```

Output is `phase2-snapshot.json` in the specified directory. Missing explicit
approval exits with code 2 and writes nothing, including for a dry run.
Validation happens before any output directory is created. The builder:

- Publishes only explicit field allowlists, with no raw-data traversal.
- Rejects credential-like strings, personal email addresses, absolute local
  paths, HTML, raw sequence-like strings and raw numeric vectors in public
  semantic fields.
- Produces deterministic content and a content-derived `snapshot_id`.
- Records SHA256 of the exact metadata inputs, not Git object IDs.
- Writes a read-only snapshot atomically and reuses identical output.
- Refuses to replace different output; choose a new versioned directory.
- Refuses any output inside the protected existing `site/data` tree.
- Performs no downloads, training, inference, Git operations or deployment.

Rejection is safer than silently sanitizing a field whose public meaning might
change. Unknown columns are discarded rather than passed through.

For a local candidate preview, copy the three Phase 2 frontend assets into the
same `website-candidate` directory as its new `phase2-data` child, then serve:

```bash
python -m http.server 8000 --directory runs/<new_run>/website-candidate
```

Open `/phase2.html` on that local server. Opening HTML with a `file:` URL is not
a supported fetch workflow. The frontend expects only
`phase2-data/phase2-snapshot.json` relative to the page. Without an approved,
compatible snapshot it shows **N/A**, not fabricated zero counts. All three
leaderboards stay empty even when a snapshot is loaded.

A subsequent reviewed integration may add the approved new Phase 2 target to
the served site. This worker neither copies it into `site` nor edits existing
navigation, publication allowlists, CI configuration or approved snapshots.

## Tests

Run only the new tests:

```bash
.venv-qc/bin/python -m unittest discover -s tests -p 'test_phase2_site.py' -v
```

Run actual Chrome desktop/mobile integration tests if Chrome is installed:

```bash
RNAGYM_BROWSER_TESTS=1 .venv-qc/bin/python -m unittest discover \
  -s tests -p 'test_phase2_site.py' -v
```

Run the entire existing and extended suite before integration:

```bash
RNAGYM_BROWSER_TESTS=1 .venv-qc/bin/python -m unittest discover -s tests -v
```

The new tests use synthetic fixtures, a temporary HTTP server and temporary
browser profiles. They check approval, count consistency, no inference of
admission, strict metadata allowlists, secrets/path/raw-label isolation,
unsafe URLs, empty result lists, immutable output, dry runs, source hashes,
search, filters, pagination, mobile overflow and unavailable-snapshot behavior.
No raw experimental files are rescanned. No real audit is approved by a test.

## Known integration boundary

**BLOCKED outside this worker's write scope:** the legacy
`test_static_publication_allowlist_and_accessible_markup` in
`tests/test_site.py` compares every file in `site/` with an exact old allowlist.
The three explicitly requested new files (`phase2.html`, `phase2.js`,
`phase2.css`) necessarily make that assertion fail until main reviews and
extends the allowlist. This worker does not edit or bypass that test.

The original 81-test suite passed before these additions (its opt-in browser
test was skipped). The new real-Chrome test validates desktop and a 375-pixel
mobile iframe using synthetic approved aggregates only. Main should rerun
the full expanded suite after its publication allowlist change. Other parallel
workers may add tests, so the full test count is not fixed here.

## Integration checklist

- [ ] Review the actual four Phase 2 report inputs and underlying admission gate.
- [ ] Confirm semantic source text is licensed public metadata.
- [ ] Dry-run the actual inputs and resolve contract errors without guessing.
- [ ] Explicitly approve only the intended public aggregates.
- [ ] Build into a new candidate directory and inspect its hashes and counts.
- [ ] Run real browser tests and review the candidate at a mobile viewport.
- [ ] Add publication allowlist/navigation changes in the main workstream.
- [ ] Publish only after a separate secret and redistribution review.
- [ ] Record the actual commit, CI result and deployment URL in main's report.
