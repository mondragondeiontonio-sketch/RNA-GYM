#!/usr/bin/env python3
"""Append a measured next-step report to the v1 build without overwriting it."""
from pathlib import Path
import json,csv
from tools.build_arena_v1 import ROOT, load, table, dump

OUT=ROOT/'runs/20261030_structure_engineering_smoke_v1'
def run():
 smoke=load(OUT/'gpu_smoke/summary.json')
 repaired=load(OUT/'gpu_smoke_parser_repair/summary.json') if (OUT/'gpu_smoke_parser_repair/summary.json').exists() else {}
 cov=load(OUT/'native_coverage_summary.json') if (OUT/'native_coverage_summary.json').exists() else {}
 binding=load(OUT/'structure_split_summary.json') if (OUT/'structure_split_summary.json').exists() else {}
 results=table(OUT/'gpu_smoke/dataset_smoke_results.tsv')
 repaired_rows=table(OUT/'gpu_smoke_parser_repair/dataset_smoke_results.tsv') if (OUT/'gpu_smoke_parser_repair/dataset_smoke_results.tsv').exists() else []
 next_rows={r['dataset_id']:r for r in results};next_rows.update({r['dataset_id']:r for r in repaired_rows})
 counts={}
 for r in next_rows.values(): counts[r['status']]=counts.get(r['status'],0)+1
 report=f'''# RNA-Gym v1.1 Next-Step Report: Structure / Engineering / FM Smoke

> **Date:** 2026-10-30 UTC  
> **Model:** `RNA-FM-HF` from the pinned local RNA-FM manifest.  
> **Explicit exclusion:** UTR-LM was not loaded or executed.  
> **Purpose:** API/input/label compatibility and two-epoch head integration only; no scientific admission or leaderboard score.

## Executive conclusion

The native dataset API was exercised on **{smoke['expected']} local dataset views** using one
allocated, idle V100. **{smoke['datasets_passed']}** views completed the two-epoch technical
head smoke; **{counts.get('INCOMPATIBLE',0)}** were incompatible under the no-truncation
RNA-FM-HF contract, **{counts.get('NOT_RUN',0)}** were not run because their stored label
encoding needs an adapter, and **{counts.get('FAILED',0)}** failed an integration guard.
These are not benchmark scores and do not change admission.

A first attempt selected GPU 0, but the safety guard found a live process and refused to
start. That attempt is preserved as a blocked safety event. The completed run used only the
idle GPU 1 UUID; no process was killed and the three MD workloads were not touched.

## 1. Task-system decisions that should survive peer review

### 1.1 Pyramid taxonomy

The next public release should show three macro capability layers:

1. **Structure:** SSP/contact/distance/probing, with distinct input contracts.
2. **Function and Regulation:** processing, modification, translation, stability,
   localization, annotation and interaction.
3. **Engineering:** RNA switches, CRISPR paired-input tasks and design/generation.

Each leaf is a **canonical task**, not a dataset name. The website should show a pyramid:
macro-domain → capability → canonical task → source family → dataset version.
A dataset can appear in more than one leaf only when it has independently defined labels;
source-family weight is not duplicated.

### 1.2 Representative first release

Do not put all ~230 views into the first public panel. Freeze a small representative set
only after human review:

| Tier | Selection rule | Intended use |
|---|---|---|
| Anchor | Classic, widely reused, complete input/label provenance, license and stable split | Public headline panel |
| Generalization | Same task family with gene/family/target-held-out grouping | Public robustness panel |
| Challenge | Assay/cell/species/temporal/private holdout | Private/OOD validation |
| Extended | Useful but proxy, multimodal, raw-signal or less standardized | Specialist board, not universal core |

A task needs **1–3 dataset versions**, not 1–3 arbitrary files. Versions are selected to
represent assay/source families, not to increase sample count or weight.

The candidate v1 core remains empty until review; current measured candidates are not
silently promoted by the two-epoch smoke.

### 1.3 Difficulty and two complementary scores

Every public task should expose two fixed panels:

- **D1-ID / standard:** group-aware random or construct-aware split. This measures in-domain
  learnability, not biological novelty.
- **D2/D3-generalization:** family/gene/target/assay/cell/species/temporal holdout according
  to the task. This measures transfer.

A model card must report both `S_ID` and `S_GEN/OOD`, plus:

`Generalization gap = S_ID - S_GEN/OOD`.

Do not average random and relatedness-held-out scores into one hidden mixture. The headline
Arena score should use the preregistered generalization panel; ID remains a diagnostic
specialist score. This is more defensible than allowing a large easy random split to hide
homology leakage.

### 1.4 Hierarchical weighting

For the formal public panel, use:

- equal macro-domain weights: Structure / Function / Engineering = 1/3 each;
- equal capability weights inside each macro-domain;
- equal canonical-task weights inside each capability;
- equal biological source-family weights inside a task;
- releases/folds/mirrors never add biological weight;
- sample size changes confidence intervals, not point-estimate weight.

Report bootstrap confidence intervals over source families and a leave-one-source-family-out
sensitivity analysis. If ranking changes under equal-task versus equal-source weighting,
show both and explain why the headline rule was frozen before model results.

## 2. Structure source binding

### 2.1 RNA3DB

Existing RNA3DB metadata confirms PDB-chain sequence, release date, structure method,
resolution and Infernal/Rfam clustering metadata. New local manifests were prepared:

- `RNAGYM_RNA3DB_RANDOM_D1_V1_1`;
- `RNAGYM_RNA3DB_HOMOLOGY_D2_V1_1`;
- `RNAGYM_RNA3DB_TEMPORAL_D3_V1_1`.

They use content-addressed sequence/PDB groups, official RNA3DB component metadata and a
2022/2023/2024 release-date temporal boundary. This is split infrastructure, not evidence
that the nucleotide-coordinate target has already been fully aligned or scientifically
admitted. RNA3DB coordinates still require polymer-to-resolved-residue, assembly,
coordinate-label and rights review.

### 2.2 Wang/RNA-MSM VL1/TS

The downloaded supplement is CC-BY-4.0 at the Zenodo release level, while original source
and chain-level derivation remain separately recorded. Its released matrices are directed/
undirected contact graphs; the source evaluator applies a strict upper-triangle mask. The
current audit preserves orientation, index mapping, asymmetric edges and partial mappings.
It does not symmetrize or call every contact a canonical secondary base pair.

Therefore the public task should be:

- `SSP` only if the original derivation is verified as secondary/base-pair labels;
- otherwise a separate future `STRUCT_CONTACT` extension, not silently SSP;
- no CMP/DMP claim from a contact graph alone.

## 3. Model/API test and dataset-size evidence

The two-epoch test used:

- pinned `RNA-FM-HF` checkpoint and source hashes;
- no UTR-LM;
- frozen encoder plus a bounded MLP head;
- full sequences only up to the model's 1,022 nt contract;
- 12 real examples per view after bounded compatibility scan;
- no hyperparameter search;
- no label imputation or sequence truncation.

The full-size table is `data/audit/dataset_api_smoke_sizes_admission_v1_1.tsv`.
It separates:

- reported original N;
- local actual N;
- QC-valid N;
- unique/duplicate N;
- full RNA-FM-compatible input N;
- 12-record smoke N and epoch status;
- scientific admission.

The small smoke passing only means the adapter and head can consume the selected labels. It
cannot be used as a model benchmark score or as evidence of scientific admission.

## 4. Why some datasets did not pass the smoke

### Long sequences

Several coding-protein DMS views exceed 1,022 nt. They are not truncated. They should either
use a preregistered window/region adapter with a biologically defensible target definition,
or remain `INCOMPATIBLE` for the sequence-only RNA-FM track. A shorter arbitrary crop would
create an unreviewed task.

### RNA3DB coordinates

The current input includes a coordinate reference, not an aligned scalar/vector target for
RNA-FM. It correctly remains incompatible until a residue-aligned coordinate/contact/distance
adapter is reviewed.

### RMDB probing

Stored labels are author arrays containing `nan`/sentinel positions. The repaired parser now
preserves the missing mask; it does not impute. SSI remains blocked until the partial-signal
input is actually supplied and the mask protocol is frozen.

### ArchiveII-n3864

The class ontology is present in the QC report, but the bounded smoke sample did not contain
all train/held-out label support for its selected subsample. The adapter should stratify the
smoke sample using the published ontology without using test labels to change the task head.

## 5. Private data and anti-gaming design

The local `therna` directory should not be copied into the public repository. It can support a
server-side private board only after a separate rights/access record contains:

- source owner or collaboration permission;
- immutable dataset hash and version;
- input/label schema and assay identity;
- hidden-test generation and leakage audit;
- submission quota, model hash and adapter hash;
- no per-sample label/error response.

Private data are not automatically “harder” or “cleaner”. They are a hidden qualification /
prospective OOD panel only when the provenance and access chain are documented.

## 6. Fair model pool and tuning policy

The first model pool should include:

- fixed classical baselines: prevalence/mean/median, k-mer or sequence-statistics Ridge,
  logistic regression, RNAfold/RNAstructure where the input contract permits;
- RNA-FM-HF as the currently approved open local FM;
- other open SOTA only after official repository, checkpoint, tokenizer, max length and
  license are pinned;
- paper-reported models in a visually separate reference table.

For each model freeze before seeing test labels:

- checkpoint/source/tokenizer hashes;
- parameter count from the official model/config, not marketing text;
- input length and alphabet policy;
- optimizer, learning rate, batch size, epochs, early stopping rule and seed list;
- maximum tuning trials and whether validation is allowed;
- one adaptation budget shared across models.

If official tuning is documented, reproduce it exactly and cite the source. If not documented,
use a small declared grid (for example three learning rates × two heads) and give every model
the same budget. Never tune on private labels.

## 7. Fine-tuning study and multi-task insight

For headline models, compare zero-shot/frozen representation against frozen Ridge/MLP,
LoRA and full fine-tuning under the same task budget. Use the same source-family-level split
and report:

- `Δ_adapt = S_FT - S_Frozen`;
- `Δ_pretrain = S_FM,FT - S_RandomInit,FT`;
- `Δ_OOD = S_OOD - S_ID`.

A credible multi-task architecture should have shared nucleotide encoder layers plus task-
family-specific heads, with explicit pairwise/site/generation adapters rather than a single
regression head. MRL/TE/half-life and structure/contact should remain separate heads until
multi-task gains are demonstrated without cross-label leakage.

## 8. Fig. 1 / summary comparison table

The paper should contain an evidence-backed horizontal comparison, not a marketing claim:

| Dimension | Existing benchmark families | RNA-Gym v1 contract | Evidence/status |
|---|---|---|---|
| Structure | secondary structure / RNA3DB / contact studies | SSP, CMP, DMP, SSI with input guards | RNA3DB/Wang source audits; CMP/DMP pending aligned labels |
| Function/regulation | splice, APA, modification, localization, translation/stability | canonical readout separation and source-family aggregation | local catalog/QC; admission pending |
| Perturbation | DMS/VEP panels | direct/proxy role separation | local DMS and VEP schemas |
| Engineering/design | RNA design / inverse folding / CRISPR / switches | separate Engineering and Design registry domains | RNAInvBench metadata; local acquisition/admission pending |
| Random vs relatedness split | many benchmarks publish one split | ID + generalization/OOD panels | new RNA3DB split manifests; remaining tasks pending |
| Public/private | usually public evaluation | public reproducibility + private holdout | private protocol/API schema |
| Missing/unsupported status | often coerced to zero | NA + explicit status + coverage penalty | scoring config and arena implementation |
| Source/assay weighting | dataset-count averages are common risk | hierarchical source-family equal weighting | scoring protocol |
| API | benchmark-specific scripts | versioned catalog/leaderboard/submission schema | OpenAPI contract; deployment pending |

Every “existing benchmark” cell needs a checked citation and exact protocol match. “RNA-Gym
only has” should be used only when the comparison audit proves the absence, not because a search
was incomplete.

## 9. Current problems and proposed solutions

| Problem | Current state | Proposed resolution |
|---|---|---|
| Reviewer trust in weights | protocol exists but no sensitivity analysis yet | preregister weights, bootstrap source families, show alternate weighting |
| Too many datasets | 277 local views and ~230 candidates | anchor/generalization/challenge tiers; 1–3 source-family versions per task |
| Generalization | old EAZY/OOD names mixed | separate D1/D2/D3 manifests and report ID-vs-OOD gap |
| Leakage | sequence overlap and FM pretraining overlap incomplete | exact/homology/source overlap audit plus model corpus disclosure |
| Structure labels | contact/coordinate semantics unresolved | source-specific label derivation and residue alignment review |
| Engineering coverage | most candidates not locally schema-bound | bind real switch/CRISPR/design data before public core |
| Model fairness | official tuning metadata uneven | pinned config, equal tuning budget, paper/reference separation |
| Score gaming | public labels and repeated submissions risk overfit | hidden private holdout, rate limits, model/version hashes |
| Private rights | local therna is not automatically publishable | access/rights manifest and private evaluator isolation |
| API usability | contract exists, production evaluator does not | implement read-only catalog then authenticated submission worker |
| FM contamination | UTR-LM has UTR-pretraining concern | exclude UTR-LM; use RNA-FM-HF and disclose pretraining overlap unknown |

## 10. Immediate next actions

1. Keep RNA-FM-HF smoke artifacts separate from official leaderboard results.
2. Complete the repaired RMDB/ArchiveII parser run and record full-view compatible counts.
3. Ask a scientific reviewer to approve the RNA3DB/Wang SSP derivation before `ADMISSION_REVIEW_READY`.
4. Bind at least one classic, public, source-complete Engineering task; do not infer CRISPR/switch labels from missing cache files.
5. Freeze the representative core panel and two scoring views before any SOTA model tuning.
6. Add the private therna access manifest only in private storage; never export labels to the public site.
7. Add a reviewer-facing benchmark comparison table with primary source/protocol citations.

## 11. Acceptance boundary

The only statuses that can enter a formal public leaderboard are server-verified,
scientifically admitted, primary-metric results on a frozen panel. `PASSED_TECHNICAL_SMOKE`
is not one of them. Current formal admitted count remains zero.
 '''
 (ROOT/'reports/RNAGYM_V1_1_NEXT_STEP_REPORT.md').write_text(report)
 dump(ROOT/'data/audit/rnagym_v1_1_next_step_summary.json',dict(smoke=smoke,repaired_smoke=repaired,coverage=cov,structure_binding=binding,status_counts=counts,formal_admitted=0,utrlm_executed=False))

if __name__=='__main__':run()
