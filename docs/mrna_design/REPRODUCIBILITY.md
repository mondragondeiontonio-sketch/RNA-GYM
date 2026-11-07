# V0.6 reproducibility

## Scope and installation

This is an incremental, CPU-only research layer over the existing RNAHub/UTR
registries and evaluation/publication primitives, not a replacement benchmark.
The original SDK remains dependency-free. Use Python 3.10 or 3.11 and a clean
virtual environment; numerical analyses use the pinned optional CPU extra:

```bash
python -m pip install -e '.[research-v06]'
python -m tools.mrna_design --help
python -m unittest discover -s tests -v
```

## Public synthetic end-to-end run

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  python -m tools.mrna_design e2e --out runs/v06-fixture-001
python -m tools.mrna_design e2e --out runs/v06-fixture-001/import --verify-only
python -m tools.mrna_design e2e --out runs/v06-fixture-001/split --verify-only
python -m tools.mrna_design e2e --out runs/v06-fixture-001/baseline --verify-only
```

The fixture is **synthetic, additive-only and never biological evidence**. It
executes schema/QC, group split, B0–B4 fitting, private saved predictions,
per-cell metric replay and output hash verification. Publication safety has
separate tests and the release verifier below. No weights, model download,
GPU device or external dataset is needed. Reusing a completed output directory
for a different computation fails; use a new version. Verify receipts without
recomputing. A corrupted/partial output is not silently repaired or overwritten.

## Authorized local data

1. Copy `configs/studies/mrna_design_v06/source_template.json` into ignored
   `runs/`; set the actual release, raw filename, SHA256 and measurement identity.
2. Confirm local research/evaluation rights. Public-copy rights are a separate
   approval, never inherited from a dataset name or license string.
3. Supply a local raw root. Downloads are not implemented in the importer.
4. Select cells from metadata before reading outcomes. Full 47-cell import is
   supported; the executed V0.6 CPU pilot deliberately uses only three cells.

```bash
python -m tools.mrna_design import-therna \
  --config runs/source.json --raw-root "$RAW_ROOT" \
  --out runs/tria-import-001 --dry-run
python -m tools.mrna_design import-therna \
  --config runs/source.json --raw-root "$RAW_ROOT" --out runs/tria-import-001
python -m tools.mrna_design split-therna \
  --input runs/tria-import-001/long.tsv.gz \
  --config configs/studies/mrna_design_v06/split_sout.json \
  --out runs/tria-split-001
python -m tools.mrna_design run-baselines \
  --input runs/tria-import-001/long.tsv.gz --split-root runs/tria-split-001 \
  --config configs/studies/mrna_design_v06/models.yaml \
  --out runs/tria-baseline-001
python -m tools.mrna_design replay \
  --input runs/tria-baseline-001/B3_ADDITIVE.predictions.private.json
python -m tools.mrna_design.analyze_therna \
  --input runs/tria-import-001/long.tsv.gz \
  --config configs/studies/mrna_design_v06/models.yaml --out runs/controls-001
```

Configurations with `.yaml` suffix use the repository's existing JSON-compatible
YAML subset. A full default 47-cell table can exceed the bounded in-memory
baseline scope; select cells at import or adjust an explicitly reviewed CPU
scope, never silently sample by label or test performance. Cell OOD inputs must
satisfy the [THERNA protocol](THERNA_PROTOCOL.md).

## Reproduce source and historical audits

```bash
python -m tools.mrna_design.inventory --out runs/source-inventory-001
python -m tools.mrna_design audit-utr \
  --input data/registries/utr_legacy_102.json --raw-root "$UTR_RAW_ROOT" \
  --out runs/utr-audit-001
python -m tools.mrna_design.verify_release --base origin/main
```

UTR audit checks all 1,020 historical gzip hashes, scans fold 0 without changing
labels or roles, diagnoses train-fitted z-score consistency, and builds a local
SQLite exact/U–T overlap index. Length eligibility is a **1022-nt screen only**,
not tokenizer/checkpoint validation. The raw inverse replay for old predictions
remains pending; no old metric is promoted into the V2 main panel.

## Immutable stages and scientific limits

Raw files are read-only. Bronze is the long table with source row/column and
original values; silver eligibility excludes declared missing targets only for
fitting, retaining the original long table/QC; gold is a new immutable split plus
model-input adaptation. Every completed stage writes a content-addressed receipt
with inputs, config hash, output hashes and row counts. Sequences are normalized
only for model identity (uppercase and U→T); `source_sequence` is retained.
No missing value is filled, labels are not rescaled or sign-flipped, and context
parameters absent from source material are NOT_REPORTED, not inferred controls.

CI/fixture PASS establishes engineering behavior, **not assay admission**.

## Reuse completed UTR_bench Frozen predictions without GPU

The user's original ten-fold files and frozen 6+6 panel can be reused directly.
The three-fold pilot is a distinct protocol and is not silently substituted.
`replay_legacy_frozen` never loads a model, creates a split or changes an old
prediction. Install the optional Parquet reader with:

```bash
python -m pip install -e '.[research-v06,legacy-replay]'
CUDA_VISIBLE_DEVICES='' OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
python -m tools.mrna_design.replay_legacy_frozen \
  --matrix "$MATRIX" --project-root "$FROZEN_PROJECT" --raw-root "$UTR_RAW_ROOT" \
  --registry data/registries/utr_legacy_102.json \
  --historical data/registries/utr_historical_result_status.json \
  --dataset 3UTR/007_com_HepG2_Set2 --out runs/legacy-raw-replay-001
```

Every original fold hash, completed-summary/OOF receipt, sequence hash, row ID,
raw/scaled truth and original test membership must match. Inverse parameters
are computed from **original train rows only** and verified against all source
z-scores with fixed tolerances. No scale/offset is fitted on test truth.
The new output is `TRAIN_ONLY_RECONSTRUCTED_NOT_ORIGINAL_STORED_METADATA`:
this is an independently reproducible reconstruction, **not recovery of missing
original stored metadata**. Historical `RAW_INVERSE_PENDING`, admission and
source review remain unchanged. Raw-label scale may itself be logarithmic or a
transformed readout; no additional log or sign conversion is performed.

All reconstructed predictions and assay statistics remain local-only pending
copy-specific rights and scientific review. This CPU work requires no MD job
termination, GPU allocation, CUDA context, model forward pass or new training.
