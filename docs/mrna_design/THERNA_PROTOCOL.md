# THERNA Sequence × Cell × Time protocol V0.6

## Independent identities and endpoints

Penta reporter expression, Tria normalized abundance and Tria fitted decay are
separate endpoints. Abundance and fitted rate from the same Tria library are
correlated readouts, not independent assay votes. DNA T0 is measurement-side
metadata and is not an available input when designing a new RNA. Two Penta times
do not identify a free decay model. No new biological replicates are inferred
from cells, times, sequences, sequencing reads or already-aggregated columns.

The importer checks complete time grids, all expected cell IDs before selecting
a subset, alias collisions, raw SHA256, sequence validity, explicit sentinels,
zero and negative values. Unknown rate units/directions remain unresolved.
Penta is currently blocked by a missing local raw target. Authorized Tria
copies were imported locally; public upstream revision/license revalidation
failed due to source-network timeout/TLS validation errors. No bypass was used.

## Legal splits

| Protocol | Input contract | Implemented / executed |
|---|---|---|
| S-OUT | Connected exact/U–T/construct/supplied-homology groups stay together | Real 3-cell pilot and fixtures |
| C-OUT-ID | Only B0 and sequence-only B2; no new learned ID embedding | Real cell-agnostic pilot and fixtures |
| C-OUT-DESC | Independently sourced, design-time available descriptors | Implemented; real NOT_FEASIBLE |
| SC-OUT | Both axes held out; off-diagonal rectangles quarantined | Fixture-tested; real NOT_FEASIBLE |
| TIME-OUT | Train earlier times, validate penultimate, test final | Fixture-tested; real NOT_RUN |
| C-OUT-FEW | Fixed support excluded from query, report k and cost | PLANNED, not implemented |

Sequence grouping is connected-component based. Near-homology must be supplied;
exact disjointness alone is never described as complete homology clearance.
Splits use identities and fixed seeds, never outcomes. Same sequences in other
cells are legal in C-OUT, whose claim is cell transfer, not unseen-sequence
prediction. SC-OUT requires real independent descriptors and no query-derived
cell statistics. Each split has a manifest, assignment table, hash and leakage
report. SC-OUT cross-rectangles are excluded, not reused as training data.

## CPU model decomposition

- B0: training global mean.
- B1: training cell/time mean; seen-cell track only.
- B2: sequence 1–3-mer frequencies and training-standardized Ridge.
- B3: B2 plus cell/time context, no interaction terms.
- B4: B3 plus train-only SVD sequence factors × context and Ridge.
- B5: conditioned Frozen FM is NOT_RUN without an authorized bound cache.
- B6: LoRA/FT are blocked without a new GPU authorization scope.

B4 is a **fixed-factor low-rank bilinear basis**, not a jointly learned
factorization or a mechanistic model. Rank 4 is pre-fixed; alpha in {1,10} is
selected on validation only. Encoder standardization, SVD, cell coding and
target means use train only. The training panel is label-blind nested within
the outer split: 512/128/512 sequences, seed 6, three metadata-selected cells.
This bounded pilot is not a 47-cell model comparison or a power calculation.

## Metrics and controls

Primary comparisons use identical held-out observation IDs, truths and split
hashes. Report each cell then strict cell macro; undefined correlations are NA,
not 0, and a partially undefined macro is not reweighted. Interaction gain is
Spearman(interaction) − Spearman(additive); error gain is
MAE(additive) − MAE(interaction). Cluster bootstrap resamples whole connected
sequence groups across cells/times; conditional CI omits model-seed uncertainty
and biological replicate noise. Never call this a biological-replicate CI.

Executed local controls include train-only cell-identity permutation within
assay/time/batch strata, a mononucleotide-preserving sequence shuffle, a separate
synthetic additive-only panel, feature-leak canaries and IQR-scaled noise
sensitivity. Mononucleotide shuffle is not a 3-mer-matched control. The supplied
synthetic null is a diagnostic, not a multi-seed calibrated false-positive-rate
study. Missing biological replicates prevent proving the observed interaction
exceeds measurement noise. Rank diagnostics report complete-case coverage,
per-cell ranks, correlation, top-decile overlap and perturbation sensitivity;
Kendall tau-b is not misrepresented as an exact tie-free inversion fraction.
No causal RBP/miRNA, LNP or vaccine-immunity claims are supported.
