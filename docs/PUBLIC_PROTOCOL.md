# Public acquisition and admission protocol

## Counting and identity

A registered task is not an admitted assay. An acquisition group is not an
independent experiment. Source reuse, benchmark aliases and release versions
must map to a verified original assay before source-family weighting.

Preserve file SHA-256, original accession/batch, construct, replicate, timepoint,
probe, readout, cell, exact input representation and split group separately.
Hash ordered paired inputs without silently substituting RNA U and DNA T.
Identical inputs in different conditions are not duplicate observations.

Do not create canonical assay IDs from filenames or benchmark publication DOIs.
The current canonical assay master and alias map intentionally contain no
confirmed mappings: original accession/batch identity is still unresolved.

## Acquisition stages

`run-state.sqlite` records task/package/asset identifiers, nullable assay ID,
artifact digest, stage, retries, exit code, heartbeat, evidence paths and a
stable idempotency key. Event rows retain previous states. The normal sequence
is QUEUED, FETCHING, DOWNLOADED, HASHED, PARSED, QC_PASS, DEDUP_PASS,
REVIEW_READY, then human-controlled admission. HOLD states are local, not global.

Each command performs one stage. `download` stores read-only content-addressed
quarantine bytes; `verify` writes immutable checksum/provenance records.
`extract` rechecks raw hashes and validates paths, regular-file types, file
counts, expanded sizes and compression budgets. Symlinks, hardlinks, devices,
ZipSlip and unapproved redirects are refused. Partial/failed extractions remain
explicitly failed and must not be parsed as complete data.

Downloads require an explicit asset, execution flag, finite byte cap, disk
reserve and asset-specific acquisition-rights evidence. Unknown expected SHA
requires explicit `--allow-unpinned` and remains quarantine. Resume requires a
matching ETag or Last-Modified plus size, and a valid Content-Range. On upstream
change, preserve the old partial rather than concatenate versions. Retries are
bounded and use exponential backoff. Never bypass authentication or terms.

The operating-system read-only flag is an integrity aid, not immutable storage:
the file owner can change permissions. Rehash raw artifacts before reuse and
review. File digest, upstream Git commit and upstream digest claims are distinct.

## Scientific QC and splits

Exact sequence/label or paired-input QC is only an entry check. Require modality-
specific structural/ligand/raw-read QC, label units/direction, replicates,
negative generation and RNA/protein/DNA readout interpretation before admission.

Official splits remain original splits. Never use test/heldout samples to fit
scalers, tune thresholds, select hyperparameters, fine-tune representations or
build task-specific pretraining caches. Gene, WT/backbone, homology, PDB-chain,
miRNA family/RBP, ligand scaffold and read/molecule grouping need separate review.

Report exact-pair overlaps even when two files have different compressed hashes.
Do not delete same-sequence/different-condition observations. No aggregate
Spearman, AUROC, F1 and structural scores are summed into one uncalibrated rank.
RSS, MRL and TE are separate readouts. Paired RNA, sequence, structure-conditioned,
ligand-conditioned and generation tracks remain separate.

## Admission and public release

Admission requires an original assay DOI or accession, observed raw-byte hash,
release identity, assay identity, rights, sample-level dedup, full leakage/split
and QC JSON reports, all bound to the same assay and raw hash, and an actual
human reviewer decision. Exact-only QC and placeholder signatures fail closed.
Final tiers are ADMITTED_CORE, ADMITTED_EXTENDED, SECONDARY_PROXY, HOLD_* and
EXCLUDED_NON_ASSAY. No automated process writes a fabricated human approval.

Only code, approved metadata, source URLs and aggregate statistics are public
in this preview. Raw files, measurements, identities, private UTR material,
internal audit narratives, credentials and model weights stay local. The static
site shows no leaderboard scores. Existing frozen releases cannot be silently
replaced after an upstream change.
