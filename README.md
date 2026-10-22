# RNA-Gym — auditable RNA benchmark registry

> **Audit preview, not an admitted benchmark.** 198 registered task rows,
> 123 source families and 47 acquisition groups are different counting units.
> There are currently **0 review-ready assays and 0 admitted assays**.

This project maintains a public source index, task/baseline design, conservative
acquisition tools and a static audit website. It does not publish experimental
sequences, labels, internal UTR benchmark data, private folds or model weights.
No GPU job, model inference or training is run by the acquisition workflow.

## Current local evidence

The 2026-10-22 run downloaded and SHA-256 verified **19 public files** totalling
774,074,831 compressed bytes. A curated miRBench mirror and the official Zenodo
release are preserved as separate byte versions, not independent samples.

| File scope | Actual rows | Status |
|---|---:|---|
| Klimentova official test | 954 | Exact paired QC only |
| Klimentova curated mirror test | 954 | Same 954 pairs/labels; do not count twice |
| Hejret official test | 1,018 | Exact paired QC only |
| Hejret official train | 8,140 | Exact paired QC only |
| Manakov official train | 2,495,535 | Stream-parsed file count; full identity/QC pending |
| Manakov official test | 324,171 | Stream-parsed file count; full identity/QC pending |
| Manakov official leftout | 20,054 | Stream-parsed file count; full identity/QC pending |
| 11 explicitly licensed mRNABench files | See file-count JSON | Parquet footer counts; full QC pending |
| RNAGym processed collection | 70 CSV members | Archive hashed; assay review pending |

The RNAGym reference classifies 31 ncRNA, 2 mRNA-splicing and 37 mRNA-coding
items. The coding items can involve protein/genomic fitness; they are **not**
automatically direct RNA readout tasks. The 33 noncoding/splicing candidates
were selectively extracted and have 862,377 total file rows, **not** 862,377
verified independent experimental observations. Per-file counts are in
`data/audit/rnagym_file_counts.tsv`. All other acquired file counts are
in `data/audit/downloaded_file_counts.json` with explicit file-level scopes.

Reported registry N remains `REPORTED_UNVERIFIED`; file-level measured counts
never silently become task-wide N. The current task disposition is 189 HOLD
rows and 9 excluded non-assay/control rows. See the machine-readable audit
snapshots and [current audit status](docs/CURRENT_AUDIT_STATUS.md).

## Local setup and smoke tests

Python 3.10+ and the standard library suffice for acquisition, QC and the site.
Optional Parquet export requires `pyarrow`; browser testing is optional and
requires a local Playwright/Chrome installation.

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
