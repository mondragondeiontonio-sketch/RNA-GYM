# RNA-Gym RNA-FM-HF Pilot v1.2

> 2026-10-31 UTC · **EXPLORATORY_PILOT**, not formal Public Leaderboard.

## Part A — Run, data and frozen protocol

### Final technical status

**277 views: 261 PASSED_TECHNICAL_SMOKE / 16 INCOMPATIBLE.** The authoritative
merged per-view log uses both successful repairs, not the historical 259 count.
RMDB numeric-mask parsing and ArchiveII class-ontology support were repaired.
No all-view smoke was repeated. Technical success is not scientific admission.

### Selected real data

Eight prespecified views span six canonical families: MRL_EXACT, MRL_PROXY,
HALF_LIFE, UTR3_STABILITY, NCRNA_FAMILY and DMS_FITNESS.
They represent Function/Regulation and direct RNA Perturbation, not all three
macro-domains. All eligible rows were used, not 12-record samples.

| Dataset | Local QC view N | Eligible N | Excluded N | Unique inputs | Biological/construct groups |
|---|---:|---:|---:|---:|---:|
| DMS_Andreasson_2020_ribozyme | 7343 | 7343 | 0 | 7343 | 7343 |
| DMS_Domingo_2018_tRNA | 4175 | 4175 | 0 | 4175 | 4175 |
| MRNA_rnahl-saluki-human | 12939 | 656 | 12283 | 656 | 656 |
| MRNA_rnahl-saluki-mouse | 13723 | 968 | 12755 | 968 | 968 |
| MRNA_mrl-sugimoto | 11693 | 3349 | 8344 | 2977 | 2491 |
| EUKA_karner_decay_rate_763b01f0f301 | 4918 | 3310 | 1608 | 3310 | 3310 |
| WANG_Archivell_Nr | 1273 | 1273 | 0 | 1273 | 1273 |
| 5UTR/077_danio_embryo_NOT_APPLICABLE_OR_UNKNOWN | 18021 | 18021 | 0 | 18021 | 18021 |

Total eligible observations: **39,095**. All train/validation/test
memberships are restricted explicitly to full model-compatible sequences; no
truncation, label imputation, windowing or training subsampling occurred.
Human/mouse half-life coverage is only about 5.1% / 7.1% of the QC views:
**these are short-transcript subset results, not full-dataset performance**.
Original paper N stays UNKNOWN where not bound; local N is not paper N.

### Input / target / assay definitions

- **DMS_Andreasson_2020_ribozyme**: Deep mutational scanning assay measuring the self-cleavage rates of ribozyme variants; unit: author assay-specific DMS score; not harmonized across assays. Source DOI: UNKNOWN.
- **DMS_Domingo_2018_tRNA**: Deep mutational scanning assay measuring the fitness effects of tRNA variants in yeast cells using a competitive growth assay and high-throughput sequencing; unit: author assay-specific DMS score; not harmonized across assays. Source DOI: UNKNOWN.
- **MRNA_rnahl-saluki-human**: First principal-component target from the transformed/imputed half-life gene-by-experiment matrix; NOT half-life in hours; unit: unitless published half-life PC1 score. Source DOI: 10.1186/s13059-022-02811-x.
- **MRNA_rnahl-saluki-mouse**: First principal-component target from the transformed/imputed half-life gene-by-experiment matrix; NOT half-life in hours; unit: unitless published half-life PC1 score. Source DOI: 10.1186/s13059-022-02811-x.
- **MRNA_mrl-sugimoto**: Mean ribosome number associated with a transcript isoform estimated from fraction-normalized HP5 read counts; not ribosome-footprint TE or RSS; unit: ribosomes per transcript (parent-study MRL definition); exact HF target scale pending. Source DOI: 10.1038/s41594-022-00819-2.
- **EUKA_karner_decay_rate_763b01f0f301**: cell-specific log decay estimates; each cell readout distinct; unit: log decay rate, base/time unit unresolved. Source DOI: UNKNOWN.
- **WANG_Archivell_Nr**: published RNA family/type annotation; precursor to a pair homology task, not pre-existing binary pair labels; unit: categorical family string. Source DOI: UNKNOWN.
- **5UTR/077_danio_embryo_NOT_APPLICABLE_OR_UNKNOWN**: log2(author MRL_6hpf); unit: log2 mean ribosome load. Source DOI: UNKNOWN.

MRL-exact uses genuine 5′UTR and already-published log2 MRL at zebrafish 6 hpf.
MRL-proxy uses mature transcript/cDNA; these are not merged. Half-life PC1 is
**unitless PC1, not hours**. Karner uses literal 3′UTR sequence and stored
mean_log_decay over six named cells; log base/time-unit and source rights remain
formal-review gaps, not an excuse to rename the target absolute half-life.
DMS targets are direct ribozyme self-cleavage / tRNA functional fitness, not
encoded-protein phenotypes. Their released scalar scores are kept untransformed;
assay-specific transformations/units remain explicit limitations. No RRS/TE or
RNA localization target was fabricated for absent evidence.

### Split and training rules

- Existing ten-fold outer tests **[0,3,7]** reused without reassignment.
- Validation: hash-ordered 10% biological/split groups from the other nine folds.
- Exact model-input, biological-group and split-group cross-role leakage: zero.
- D1 DMS is mutant-construct generalization inside one WT/library, not WT-held-out.
- D2 uses frozen approximate MMseqs 80% identity / 80% coverage plus declared
  biological groups; do not call this assay/cell/species D3.
- Closed-set ncRNA classification does not use family-held-out target classes.
- Danio preserves existing legacy test membership; it is D1, not homology/OOD.
- All scalers/target transforms and baselines fit train only. MLP selection uses
  validation loss only; test labels never select samples, LR or tasks.

### Verified model and resource identity

- Checkpoint SHA256: `5b5d7d87b37c291ef42c140ef9edf7aea29f255fa2a4fd435f776c52e93d5e99`.
- Tokenizer SHA256: `3fda088d6fa8a55dd28bea5ddc6307b10453d711dc60aba9780328e08f17a232`.
- Parameters: **99,521,546**; dimension **640**; max nt **1022**.
- Existing RNAHub native API checks BOS/EOS/padding and residue-token alignment.
- Literal inputs retained; uppercase/T→U is an explicit versioned model-only view.
- Encoder eval()/requires_grad=False; no encoder tensor enters an optimizer;
  parameter version counters unchanged. No UTR-LM, LoRA or full FT.
- Unique cached inputs **38,692**; key binds checkpoint, tokenizer,
  sequence hash, preprocessing and representation. Disk entries independently checked.
- Length-bucket encoder batch 16/8/4/2, fp32 inference_mode; no CPU FM fallback.
- Job `53139`, node `vgpu001`, one GPU UUID
  `GPU-dc4db36b-db01-307d-2fae-593418399b4f`. Pre-start process list empty.
- Wall time **1037.5 s / 17.29 min**; forward time
  **306.9 s**; peak allocated **0.794 GiB**,
  reserved **7.852 GiB**. No new job or other node used.

## Part B — Real held-out results

B0: train-only log-length/composition/3-mer Ridge or multinomial logistic.
B1: frozen embedding Ridge or multinomial logistic. B2: frozen MLP (128, GELU,
dropout .2). Mean/median or prevalence nulls are stored separately; undefined
correlations remain NA. Ridge alpha=1, logistic C=1, AdamW LR=.001, weight decay
.0001, batch 32, max 15 epochs, patience 3, seed 42, no HPO. These are fixed
pilot engineering defaults, not official author-optimal settings.

All cells show test-fold mean ± sample SD, not validation scores or pooled train
metrics. Test sample sizes are per folds 0,3,7. Full Pearson/MAE/RMSE/class-support
metrics and NA reasons are saved in the fold tables.

| Dataset | Protocol | N train / test by fold | Task | B0 | Frozen linear | Frozen MLP | Primary |
|---|---|---|---|---:|---:|---:|---|
| 5UTR/077_danio_embryo_NOT_APPLICABLE_OR_UNKNOWN | UTR_LEGACY_10FOLD | [14598, 14598, 14598] / [1802, 1802, 1802] | MRL_EXACT | 0.7391 ± 0.0061 | 0.7190 ± 0.0165 | 0.7198 ± 0.0108 | Spearman |
| DMS_Andreasson_2020_ribozyme | EAZY | [5948, 5949, 5949] / [735, 734, 734] | DMS_FITNESS | 0.4807 ± 0.0179 | 0.5237 ± 0.0119 | 0.5727 ± 0.0693 | Spearman |
| DMS_Domingo_2018_tRNA | EAZY | [3382, 3382, 3383] / [418, 418, 417] | DMS_FITNESS | 0.7790 ± 0.0088 | 0.8216 ± 0.0028 | 0.8356 ± 0.0050 | Spearman |
| EUKA_karner_decay_rate_763b01f0f301 | EAZY | [2686, 2678, 2662] / [326, 335, 353] | UTR3_STABILITY | 0.2971 ± 0.0574 | 0.1972 ± 0.0423 | 0.2806 ± 0.0572 | Spearman |
| EUKA_karner_decay_rate_763b01f0f301 | OOD_split | [2684, 2673, 2680] / [328, 340, 333] | UTR3_STABILITY | 0.3164 ± 0.0199 | 0.1933 ± 0.0783 | 0.3146 ± 0.0415 | Spearman |
| MRNA_mrl-sugimoto | OOD_split | [2700, 2692, 2683] / [355, 359, 378] | MRL_PROXY | 0.1649 ± 0.0296 | 0.1976 ± 0.0346 | 0.1870 ± 0.0695 | Spearman |
| MRNA_rnahl-saluki-human | EAZY | [518, 533, 541] / [81, 64, 55] | HALF_LIFE | 0.3292 ± 0.0771 | 0.1273 ± 0.0878 | 0.3461 ± 0.1361 | Spearman |
| MRNA_rnahl-saluki-human | OOD_split | [532, 544, 529] / [65, 52, 69] | HALF_LIFE | 0.2573 ± 0.1310 | 0.1766 ± 0.1076 | 0.3214 ± 0.2039 | Spearman |
| MRNA_rnahl-saluki-mouse | EAZY | [783, 788, 786] / [99, 93, 95] | HALF_LIFE | 0.1635 ± 0.0256 | 0.0939 ± 0.0464 | 0.2828 ± 0.0980 | Spearman |
| MRNA_rnahl-saluki-mouse | OOD_split | [795, 781, 778] / [87, 102, 105] | HALF_LIFE | 0.1319 ± 0.0686 | -0.0158 ± 0.0764 | 0.2010 ± 0.1518 | Spearman |
| WANG_Archivell_Nr | EAZY | [1031, 1032, 1032] / [128, 127, 127] | NCRNA_FAMILY | 0.6513 ± 0.0342 | 0.8777 ± 0.1229 | 0.8656 ± 0.1126 | Macro-F1 |

Completed **33 protocol-fold cells**, **162 model/fold rows**.
All **162** saved prediction metric sets were independently replayed
after SHA256 verification. Negative-relevance DMS NDCG stays NA; no label shift was
invented to make ranking metrics defined. Macro-AUPRC/AUROC need positive/negative
support for every declared test class; otherwise NA. No incompatible raw metrics
are averaged across tasks.

### Representation/readout gains

| Dataset | Protocol | Frozen linear − k-mer | MLP − frozen linear |
|---|---|---:|---:|
| 5UTR/077_danio_embryo_NOT_APPLICABLE_OR_UNKNOWN | UTR_LEGACY_10FOLD | -0.0201 | +0.0009 |
| DMS_Andreasson_2020_ribozyme | EAZY | +0.0430 | +0.0490 |
| DMS_Domingo_2018_tRNA | EAZY | +0.0427 | +0.0140 |
| EUKA_karner_decay_rate_763b01f0f301 | EAZY | -0.1000 | +0.0835 |
| EUKA_karner_decay_rate_763b01f0f301 | OOD_split | -0.1231 | +0.1212 |
| MRNA_mrl-sugimoto | OOD_split | +0.0327 | -0.0106 |
| MRNA_rnahl-saluki-human | EAZY | -0.2019 | +0.2188 |
| MRNA_rnahl-saluki-human | OOD_split | -0.0807 | +0.1448 |
| MRNA_rnahl-saluki-mouse | EAZY | -0.0696 | +0.1889 |
| MRNA_rnahl-saluki-mouse | OOD_split | -0.1477 | +0.2167 |
| WANG_Archivell_Nr | EAZY | +0.2264 | -0.0120 |

**Interpretation:** ncRNA family and both direct RNA DMS assays show positive
frozen-linear gains; MRL-proxy gain is modest. Frozen linear underperforms k-mer
for human/mouse half-life and 3′UTR decay. MLP improves those FM readouts but
fold variability is large, particularly the short-transcript subsets. Danio
5′UTR MRL does not beat the k-mer baseline with this frozen configuration.
These are descriptive pilot observations, not statistically significant claims.
One fixed seed and equal minimal HPO do not establish architecture superiority.
No dataset is scientifically rejected because a model performs poorly.

## Part C — ID versus group generalization

| Dataset | Baseline | D1 ID | D2 | Gap ID − D2 |
|---|---|---:|---:|---:|
| EUKA_karner_decay_rate_763b01f0f301 | B0_kmer_linear | 0.2971 | 0.3164 | -0.0192 |
| EUKA_karner_decay_rate_763b01f0f301 | B1_frozen_linear | 0.1972 | 0.1933 | +0.0038 |
| EUKA_karner_decay_rate_763b01f0f301 | B2_frozen_mlp | 0.2806 | 0.3146 | -0.0340 |
| MRNA_rnahl-saluki-human | B0_kmer_linear | 0.3292 | 0.2573 | +0.0719 |
| MRNA_rnahl-saluki-human | B1_frozen_linear | 0.1273 | 0.1766 | -0.0493 |
| MRNA_rnahl-saluki-human | B2_frozen_mlp | 0.3461 | 0.3214 | +0.0247 |
| MRNA_rnahl-saluki-mouse | B0_kmer_linear | 0.1635 | 0.1319 | +0.0315 |
| MRNA_rnahl-saluki-mouse | B1_frozen_linear | 0.0939 | -0.0158 | +0.1097 |
| MRNA_rnahl-saluki-mouse | B2_frozen_mlp | 0.2828 | 0.2010 | +0.0818 |

Same eligible population, but different frozen test memberships: gap can reverse
from fold composition. A negative gap is not proof of better OOD ability. No
strict D3 score, WT-held-out score or species-transfer score is claimed.
Cross-dataset sequence overlap is audited; models are trained separately, never
on pooled labels from another evaluation dataset. Source-compendium overlap and
pretraining exposure are separate from supervised split leakage. The pinned official
README describes RNAcentral100/ncRNA pretraining; it does not provide a bound
test-sequence membership check. Strong ncRNA results may reflect corpus familiarity.
RNA-FM corpus
membership remains **PRETRAIN_OVERLAP_UNKNOWN**, not zero leakage.

## Part D — Failures and non-supported capabilities

- Length/alphabet exclusions have row-level reasons; a biological window adapter
  would require a new audited protocol. Do not interpret subset scores as full N.
- RMDB parser repair is real but sequence-only probing is not SSI imputation.
  Missing partial-signal/mask input means no SSI pilot score.
- Wang orientation/index conventions remain untouched; graph smoke is not SSP.
- RNA3DB D1/D2/temporal manifests do not substitute for residue-aligned CMP/DMP
  labels. These tasks remain HOLD_LABEL_BINDING.
- No complete local Engineering anchor/generator adapter was established. The
  available RNAInvBench source metadata is not a trained inverse-design model.
  RNA_SWITCH/CRISPR/RNA_DESIGN remain HOLD_DATA_BINDING where appropriate.
- RNA/RNA, RNA/DNA and protein/RNA tasks need explicit pair/multimodal adapters;
  the scalar pilot does not concatenate them into fake single-sequence tasks.
- Class ontology/support is explicit; family-held-out is not closed-set family
  classification. NA is preserved for undefined metrics.
- Human scientific admission remains zero. Rights/original assay evidence gaps
  remain in the data cards; technical pass cannot create a human signature.
- Platform lacks complete admitted Structure/Engineering panels: **no Universal
  Score**. This is unavailable platform capability, not a missing-model zero.

## Part E — Next benchmark decisions

1. Expand direct RNA DMS, genuine 5′UTR MRL and ncRNA family to full CV/multiple
   seeds after scientific review. Preserve single-WT and closed-set limitations.
2. MRL-proxy and 3′UTR stability remain native-length-population pilots; their
   source units/assay identity require review. Half-life needs long-sequence
   architecture or a justified region adapter before whole-transcript claims.
3. LoRA/FT hypotheses: DMS/ncRNA gains justify further controlled adaptation;
   small human/mouse eligible subsets need stronger regularization and repeat
   seeds before FT. Include matched random initialization to isolate pretraining.
4. Danio and 3′UTR decay need competitive sequence/position-aware baselines;
   mean pooling may hide local signals. Do not assume FM is always superior.
5. Keep ID and group-generalization boards separate, with group-bootstrap CI
   and source-family sensitivity analyses before final rankings.
6. Structure needs verified labels; Engineering needs a real anchor and paired/
   generative adapter. Do not manufacture scores for three-domain coverage.
7. All eight datasets still need genuine human scientific admission. Pilot
   learnability never determines acceptance or exclusion.

## Artifacts, reproduction and public boundary

Local fixed run: `runs/rnagym_rnafm_hf_pilot_v1_2/`. It includes required selection,
eligibility, split, GPU, model/tokenizer, cache, metrics, comparisons, predictions,
best checkpoints and execution receipts. Cache keys are independently validated.
Public `results/pilots/rnafm_hf_v1_2/` contains aggregate-only tables. No raw
sequence/label records, per-sample predictions, embeddings, private data or weights
are included in GitHub publication. The native Python API is used explicitly;
this is not a claim that the new production HTTP evaluation routes are deployed.

```bash
.venv-qc/bin/python -m tools.pilot_v1_2_data
# In an existing idle single-GPU allocation and the verified CUDA environment:
python -m tools.pilot_v1_2_run
.venv-qc/bin/python -m tools.pilot_v1_2_report
.venv-qc/bin/python -m unittest discover -s tests -p test_pilot_v1_2.py -v
```

The runner locks the run, checks config/source/split hashes, caches frozen inputs,
and saves training/validation history. New data/config/splits require a new run
version; successful metrics do not enter the formal leaderboard.
