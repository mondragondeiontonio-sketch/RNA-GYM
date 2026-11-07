# ThernaBench target-derived feature audit V0.6

## Disposition: UNVERIFIED

The supplied scientifically audited taskbook identifies an official-card risk:
full context may include RBP/miRNA `spearman_corr` against cross-cell MPRA
expression, while expression bins may use per-type/cell quintile thresholds.
This is a **risk to investigate**, not evidence that another study is contaminated.

Official Hugging Face API/card retrieval was attempted without downloading
assay files or bypassing gated access. Attempts timed out or failed TLS hostname
validation. TLS checks were not disabled. No independently pinned current card,
full/gated table, raw correlation computation or bin-edge fit population was
acquired. Source-card statements from the taskbook remain secondary inputs,
not independently verified source evidence.

## Required empirical checks

- Trace correlation sample/cell populations and whether test MPRA y contributed.
- Trace quintile edges: train-only versus evaluated population.
- Trace cell expression/binding inputs and availability at prediction time.
- Rebuild lawful features from independent metadata or training-only fitting.
- Retain AUTHOR_ORIGINAL_PROTOCOL separately; do not mix with strict fair track.

Implemented feature-audit canaries reject test-fitted or target-using features,
including measured covariates not available at design time. Tests establish
software rejection, not an actual leakage finding in ThernaBench.
