# Existing UTR split reuse: CPU follow-up

## User constraint and scope

The user's GPU molecular-dynamics work must not be terminated, restarted,
preempted or cleaned up. This follow-up used CPU only with CUDA visibility
disabled; it issued no GPU/model forward, GPU allocation, job-control or process-
termination command. Existing GPU scopes and budget ledgers were not modified.

## Actual experiment

The original UTR_bench ten-fold files and frozen six-plus-six panel were located.
The separate three-fold pilot is preserved, not substituted for the ten-fold
Frozen protocol. No new split, task selection, HPO or model training was done.

A new read-only tool verifies original fold hashes, historical completion/OOF
receipts, fixed row IDs, sequence identities, raw/scaled truths and original test
membership. It reconstructs each fold's inverse exclusively from original train
rows and verifies the source z-scores using fixed numerical tolerances.

The actual local run completed all **12 datasets × 4 models × 2 heads = 96
combinations**, replaying **6,370,256 OOF rows**. This row total includes model/head
repetitions and is not a count of independent molecules or biological assays.
Independent read-back of all 96 saved raw-prediction tables reproduces the saved
pooled metrics. Actual label values, predictions and performance tables remain
local-only; they are not included in this public follow-up.

## Interpretation boundary

The new version is `TRAIN_ONLY_RECONSTRUCTED_NOT_ORIGINAL_STORED_METADATA`.
It is a reproducible reconstruction, not recovery of the missing original stored
scaler. Historical `RAW_INVERSE_PENDING` files, metrics, predictions and scientific
review state remain unchanged. Original readouts/units are retained; a raw source
label may itself be logarithmic. No extra exponentiation, sign flip or cross-assay
y harmonization is performed. Scientific admission and formal rankings remain
closed. These results do not identify a matched pretraining or adaptation benefit.

## Validation

- Four new negative/unit tests pass: train-only fitting, wrong-scaler rejection,
  constant-train rejection and OOF identity/label/split mismatch rejection.
- Full local suite: **499 tests, 474 passed, 25 optional skips, zero failures**.
- Public-safety and historical-file checks pass; 65 scoped local protected files,
  including the known budget ledgers, remain unchanged.
- GPU-hours: **0**. Model forward calls: **0**. Splits changed: **false**.

## Reproduction

See the new existing-Frozen section in
[reproducibility](../../docs/mrna_design/REPRODUCIBILITY.md) and
`python -m tools.mrna_design.replay_legacy_frozen --help`.
A new output directory is mandatory; an incomplete/corrupt prior output is not
overwritten. Optional Parquet support is exposed as the `legacy-replay` extra.
