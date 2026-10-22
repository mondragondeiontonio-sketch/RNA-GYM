# RNA-Gym — auditable RNA benchmark registry

> **Audit preview, not an admitted benchmark.** 198 registered task rows,
> 123 source families and 47 acquisition groups are different counting units.
> There are currently **0 review-ready assays and 0 admitted assays**.

This project maintains a public source index, task/baseline design, conservative
acquisition tools and a static audit website. It does not publish experimental
sequences, labels, internal UTR benchmark data, private folds or model weights.
No GPU job, model inference or training is run by the acquisition workflow.

## Current Phase 2 evidence — 2026-10-23

The completed technical snapshot covers **45 acquired artifacts**,
**6,573,002,784 bytes** (44 network files plus one lossless reassembly).
These are not 45 independent experiments. All 45 SHA256 values matched the
previous full-byte audit; this round reused that evidence rather than rescanning
unchanged large files.

- **198 task rows / 47 packages:** 189 HOLD, 9 excluded controls/non-assays.
- **31 source-verified task rows:** 21 actual ENCODE experiment-accession links,
  9 mRNABench paper/resource links, and 1 miRBench parent GEO-study link.
  These evidence types are deliberately not treated as equivalent assay proof.
- **0 admission candidates / 0 admitted:** original assay/condition, rights,
  observation identity, splits and full scientific QC remain incomplete.
- **mRNABench:** all 11 acquired files reviewed against original papers/resources
  and author split code. Fixed row-level split manifests are not yet verified.
  Saluki targets are half-life **PC1 scores, not hours**. MRL and half-life stay
  separate. One miRNA-target license conflict explicitly blocks redistribution.
- **miRBench:** compound identity audited for all 2,850,826 file-version rows;
  the official files contain 2,849,872 rows after excluding the mirror version.
  Mirror-collapsed overlap categories include 261 shared-input comparisons across
  dataset scopes, 59 train/held-out comparisons and 15 label disagreements.
  Categories overlap and do not prove same-assay duplicates. Labels were retained.
- **RMDB:** 3 shared train/test sequences resolve to 9 observations and 8
  cross-split observation pairs. Probe/condition/vector differences were reviewed;
  missing condition metadata is not evidence of identical conditions.
- **RNA3DB:** corrected 2026 split counts are 13,451 train / 1,990 test chains.
  They share 401 PDB entries despite zero exact chain/sequence/component overlap.
  Three bounded coordinate screens are not full stereochemical validation.
- **Engineering:** 179/179 tests passed locally, including real desktop/mobile
  Chrome checks. Ten tiny CPU **synthetic** baseline smokes completed; no real
  task scores, model-weight downloads, foundation-model inference or GPU jobs.

See the [Phase 2 Dataset Atlas and QC dashboard](site/phase2.html),
[evaluation protocol](docs/EVALUATION_PROTOCOL.md), and
[public audit status](docs/CURRENT_AUDIT_STATUS.md).
The old homepage's 19-file snapshot is retained and clearly labeled historical.
The new aggregate snapshot contains no raw labels, sample identity maps,
private evidence paths or reviewer records. All three leaderboards are empty.

## Local setup and smoke tests

Python 3.10+ and the standard library suffice for acquisition, QC and the site.
Full modality QC uses the optional pinned packages in `requirements-qc.txt`.
The executable Ridge/logistic toy controls additionally require scikit-learn.
Browser testing is optional and requires a local Chrome installation.

```bash
python -m venv .venv
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/rnagym.py plan
.venv/bin/python tools/generate_site.py --verify
.venv/bin/python -m http.server 8000 --directory site
```

## Per-task download plans

All 198 original task IDs (including both `T...` and `X...` namespaces) have
separate JSON cards under `data/task_bundles/`. The line-oriented index is
`data/audit/task_download_index.jsonl`. Each card includes input/readout,
baseline/loss/metric plans, source-entry URLs, file-link candidates, reported N,
rights/identity status and an executable plan command.

```bash
.venv/bin/python tools/task_download.py plan --task T0014
.venv/bin/python tools/task_download.py plan --task XMRNA_mirna_target
.venv/bin/python tools/build_task_bundles.py --verify
```

Links catalogued from the authorized mirror keep their official URL, mirror URL,
fixed commit and metadata file size. They are **candidates, not downloaded data**.
Task cards do not invent a download command for a source portal or login page.
Because assay mappings are incomplete, acquisition through the task wrapper
requires explicit `--package-evidence-only` in addition to ordinary file safety
flags; a package download does not complete a task or approve an assay.

## Reproduce a bounded download

The 19 actually observed raw-byte hashes are frozen separately in
`data/audit/observed_pinned_assets.csv`. These are **locally observed SHA-256
pins, not upstream attestations**. Use that manifest to reproduce exact bytes
without `--allow-unpinned`. Original unpinned candidate manifests are preserved.

Asset-specific license evidence is required even with `--allow-unpinned`.
The committed acquisition decisions allow **local quarantine only**, not human
approval or blanket redistribution. The selected Zenodo file has a publicly
claimed CC BY 4.0 license; original assay review remains independent.

```bash
.venv/bin/python tools/rnagym.py download \
  --manifest data/audit/p0_assets.csv \
  --asset P0_MIR_KLIMENTOVA_ZENODO --execute --allow-unpinned \
  --max-mb 2 --rate-kbps 512 --retries 2 --out raw_cache
.venv/bin/python tools/rnagym.py verify \
  --manifest data/audit/p0_assets.csv \
  --asset P0_MIR_KLIMENTOVA_ZENODO --out raw_cache
```

Use `--refresh` only when intentionally checking a new upstream version.
Differing hashes create new versions; raw files are read-only and never
replaced by derived data. A repeated download rehashes an existing object
before reusing it. SQLite `run-state.sqlite` is the local job state authority.

The authorized Hugging Face mirror is supported as a separate transport;
official URL, mirror URL and pinned commit remain distinct. Public signed CDN
redirects are checked before following and transient query signatures are
removed from recorded final URLs. Mirror accessibility is not proof of license,
original experimental identity, or official-byte equivalence.

## Governance and publication

The six official miRBench split files are now locally downloaded and hashed.
This does **not** mean all 47 packages or all 198 task inputs are downloaded.
Six mirrored dataset groups still explicitly report unknown licenses; unrelated
large/competition/unreleased resources retain their own HOLD conditions.

Read the [public protocol](docs/PUBLIC_PROTOCOL.md) before adding assets.
`PASS_EXACT_QC_ONLY` and `QC_PASS` with exact-only scope never imply admission.
`admission_gate.py` requires raw-byte hashes, bound assay/rights/QC/leakage/split
reports and an actual human reviewer assertion. The tool cannot establish the
cryptographic identity of a reviewer and must not fabricate one.

A sanitized public candidate is built with `tools/prepare_public.py`. Only an
explicit metadata/code allowlist is copied; the original audit narratives,
workbooks, raw cache, local state, run logs, sample identity tables and secrets
are excluded. Deployment is blocked until GitHub authorization matches the
intended owner. No live repository or Pages URL is claimed before successful
creation, CI and deployment verification. This project is an independent audit
registry; references to upstream RNAGym do not imply affiliation or endorsement.

## License and citation

`LICENSE_NOTICE.md` explains third-party rights. No new blanket license is
asserted for upstream experimental data. Cite each upstream publication and
release actually used; the website does not invent a project DOI or model scores.
