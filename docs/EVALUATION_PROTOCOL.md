# RNA-Gym evaluation protocol infrastructure

## Scope and evidence status

This module is **not** a dataset admission decision or a model leaderboard.
It does not download datasets/checkpoints, execute remote model code, access
`raw_cache`, write the scientific registries, or update `run-state.sqlite`.
Its per-run checkpoints are evaluation artifacts, **not** an alternative source
of truth for acquisition or scientific admission jobs.

| Component | Status | Evidence and limits |
|---|---|---|
| CPU prepare/run/evaluate | VERIFIED | Synthetic tests and CLI smoke only |
| Train-only null/Ridge/logistic controls | VERIFIED | `tests/test_evaluation_protocol.py` |
| Pair seed and single-role negative controls | VERIFIED | Exact synthetic inputs, not biological claims |
| Real task execution | BLOCKED by default | No real task is enabled in the baseline registry |
| Six FM evaluation tracks | PROVISIONAL | Contracts only; no encoder loaded or trained |
| RNA-LLM and RNA-Agent interfaces | PROVISIONAL | Schema validators only |
| Model loadability | BLOCKED_LOADABILITY | No local checkpoints verified or loaded |
| Carbon-X metadata | BLOCKED | Exact model card/version could not be verified |
| Real rankings | BLOCKED | No real performance numbers produced |

The two `.yaml` registries use JSON-compatible YAML 1.2. The stdlib JSON parser
reads them without a PyYAML dependency. Each model/source status is explicitly
scoped: verifying an official README is **not** checkpoint loadability,
checkpoint licensing approval, or benchmark task admission.

## Executable CPU controls

| Input/label | Executable baseline IDs | Fitting rule |
|---|---|---|
| Sequence/scalar regression | `mean_null`, `median_null` | Train labels only |
| Sequence/scalar regression | `sequence_stats_ridge` | Train scaler and Ridge |
| Scalar binary classification | `prevalence_null`, `majority_null` | Train prevalence; fixed tie rule |
| Sequence/binary classification | `sequence_kmer_logistic` | Train vocabulary/scaler/logistic |
| RNA pair/binary classification | `pair_seed_match` | No fitting; exact seed match |
| RNA pair/binary classification | `pair_mirna_only` | miRNA-only train k-mer logistic |
| RNA pair/binary classification | `pair_target_only` | Target-only train k-mer logistic |
| RNA pair/binary classification | `pair_stats_logistic` | Role-ordered statistics/logistic |

Sequence statistics are length, A/C/G/U/T fractions, and adjacent identical-base
frequency. Overlapping k-mer frequencies use a sorted **train-only** vocabulary;
unseen held-out k-mers are ignored, not added to the feature space. Population
mean/standard deviation are fitted on train only; zero-variance scales are one.
Ridge alpha and logistic C default to fixed 1.0. No HPO or label transformation
runs. Model parameters, scalers and vocabularies are plain JSON, never pickle.

The seed rule searches the target for the exact reverse complement of miRNA
positions 2–8 (one-based, inclusive). It does not model wobble, accessibility,
site context or affinity. Its binary output is **not calibrated probability**;
log loss is reported using the documented epsilon clipping. The miRNA-only and
target-only controls deliberately omit the other RNA and measure shortcuts;
they do not establish mechanistic generalization.

XGBoost, RNAcofold, RNAfold, RNAstructure, nucleotide-level models, scratch CNNs,
and 3D predictors are registered as **BLOCKED**, not working implementations.
Applying them requires installed/pinned dependencies and task-specific scientific
applicability review. Scalar controls must not be substituted for 2D, 3D,
per-nucleotide or distance-regression targets. MRL, TE, RSS, half-life, splicing,
and eCLIP remain distinct readouts.

## Input and identity contract

The bounded runner accepts UTF-8 JSONL scalar observations and an explicit JSON
mapping of observation IDs to `train`, `validation`, or `test`.

```json
{"observation_id":"synthetic_1","sequence":"ACGUACGU","assay_id":"SYNTHETIC_NOT_AN_ASSAY","label":0.25}
```

Pair records instead require `mirna_id`, `mirna_sequence`, `target_id`,
`target_sequence`, `assay_id`, and `condition_id`. Missing/sentinel IDs block
execution. The role-ordered observation hash includes all six fields. A separate
cross-assay input hash uses only the exact miRNA and target strings.

- Hash algorithm: SHA256 of sorted-key, UTF-8 canonical JSON plus a newline.
- Raw-string sequence identity: no U/T replacement, case folding or trimming.
- Accepted alphabet must be declared as `ACGU` or `ACGT`; pair controls require
  `ACGU`. Declaring `ACGT` does not confer RNA-native biological interpretation.
- Identical sequence/pair inputs across **any** splits are rejected.
- Preregistered `group_fields` such as gene/transcript/family must be present
  and disjoint across splits. Omitting a field does not certify family leakage
  absent; upstream/cross-dataset reviews remain external admission evidence.
- Observations with identical input within one split are retained, including
  genuinely different conditions/assays/labels. No label merging occurs.
- IDs must be unique; split coverage must be exact; train and test are nonempty.
- Scalars must be finite and binary labels must be 0/1. Invalid UTF-8, duplicate
  JSON keys, nonfinite JSON values, and blank observation lines are rejected.
- No official split is changed. Custom splits must carry their own versioned
  `split_source`; the module never infers or invents official split provenance.

The initial CPU budget is at most 10,000 observations, 10,000 nucleotides per
input sequence, and 32 MiB per input/split file. Oversized input is rejected,
not silently sampled or truncated.

## Real-task admission gate

`configs/baseline_registry.yaml` contains no enabled real tasks. A future
single-task config requires `enabled: true`, `ADMITTED`, `ADMITTED_CORE`, or
`ADMITTED_EXTENDED`, and the actual evidence JSON accepted by the existing
`tools/admission_gate.py`. `FILE_QC_PASS`, `ADMISSION_CANDIDATE`, and
`SECONDARY_PROXY` do not unlock this runner.

The evidence must additionally contain an exact human-approved
`approved_evaluation_binding` object with these keys:

```json
{
  "task_id": "<stable registered task ID>",
  "input_sha256": "<actual evaluation-input file SHA256>",
  "split_sha256": "<actual split-manifest file SHA256>",
  "label_definition": "<reviewed real measurement definition>",
  "label_unit": "<reviewed real measurement unit>",
  "problem_type": "regression",
  "input_mode": "sequence",
  "split_source": "<reviewed official or custom version>"
}
```

This example is a **schema**, not evidence or approval. Automation must not fill
in a reviewer or set a real approval boolean. Every real observation must bind
to the config's approved `canonical_assay_id`. Current execution supports a
single approved assay per task config; multi-assay tasks need an explicitly
reviewed extension, not an implicit union.

The gate checks original raw bytes once when a run is created. Resuming pins
approval/report JSON hashes and the small evaluation input/split hashes,
without rescanning the original large raw archive. A changed code version,
registry, input, split, or approval requires a new versioned run. Public API
`prepare()` also requires actual admission evidence for non-synthetic inputs;
CLI `task` cannot pass external real data through the synthetic-only route.

## CLI, checkpoints and actual output

Dry-run has no file writes and does not assert admission or model loadability:

```bash
python tools/evaluation_protocol.py smoke --dry-run
python tools/evaluation_protocol.py adapter --model RNA-FM --track frozen_ridge
python tools/evaluation_protocol.py adapter --model Carbon-X --track rna_llm
```

Adapter plans intentionally exit 2 with `BLOCKED_LOADABILITY`; package discovery
is not an import test and certainly not a checkpoint-loading test.

Run bounded synthetic examples only:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv-qc/bin/python tools/evaluation_protocol.py smoke \
  --out /tmp/rnagym-evaluation-smoke
```

For an independently admitted task, without changing scientific metadata:

```bash
python tools/evaluation_protocol.py task TASK_ID \
  --config approved_task.json --input approved_observations.jsonl \
  --splits approved_splits.json --out runs/evaluation --dry-run
```

Removing `--dry-run` creates an immutable run ID and completes **prepare only**.
Advance one stage at a time using the returned run directory:

```bash
python tools/evaluation_protocol.py resume --run-dir RUN_DIR --stage run
python tools/evaluation_protocol.py resume --run-dir RUN_DIR --stage evaluate
python tools/evaluation_protocol.py resume --run-dir RUN_DIR --dry-run
```

The public API is `prepare(config, input_path, split_path)`, `run(prepared)`, and
`evaluate(prepared, predictions)`. `create_run()`/`advance()` add bound approval,
immutability, locking, finite retries, and resumable stage artifacts. Production
integration should use these staged entrypoints, rather than repeatedly calling
`prepare()` and revalidating the original raw asset.

Each run contains immutable `request.json`, `prepared.json`, `model.json`,
`predictions.json`, `metrics.json`, and hash-chained event JSONs. Publication of
immutable outputs uses an exclusive atomic hardlink, so interrupted writes
cannot publish a partial final artifact. The mutable `checkpoint.json` is
atomically replaced; it stores completed stage, attempts, retry count, heartbeat,
request/output SHA256 and failure status. A process lock rejects concurrent
writers. Crash-orphan complete outputs are reused only if bytes are identical.

Only transient I/O errors retry, with exponential backoff and at most three
retries. Attempt counts survive restarts; deterministic protocol failures do
not loop. Ctrl+C records `INTERRUPTED` and preserves the last completed stage.
Repeating a completed stage verifies hashes and does not refit. The acquisition
DB is deliberately untouched; orchestration must register the task/run ID in
its existing job-state layer rather than treating this checkpoint as a second
scientific state database.

Predictions include only held-out observation IDs, split, exact input hash and
finite prediction; labels are not copied into prediction files. Evaluation
rejects missing/duplicate IDs and split/input mismatches. Regression reports
MSE, MAE, R², Pearson and tie-aware Spearman. Binary tasks report accuracy, F1,
tie-aware AUROC, Brier and log loss, at fixed threshold 0.5. Undefined metrics
are `null`, not invented zeros. No raw cross-metric sum or ranking is produced.
Even future admitted CPU metrics remain unrankable until separate result review.

> **Warning:** Local run artifacts contain absolute local input/evidence paths,
> observation IDs and fitted parameters. Do not publish entire run directories,
> hidden labels or unapproved per-observation data. Export only separately
> approved public aggregate snapshots through the main publication workflow.

## Independent model and agent protocols

The six FM contracts are independent: zero-shot likelihood, frozen + Ridge,
frozen + MLP, LoRA, full fine-tuning, and random initialization. None executes
here. Zero-shot causal likelihood and masked pseudo-likelihood require explicit
separate scoring/token-normalization semantics, not a shared raw-score ranking.
Frozen encoders must remain eval/no-grad; any scaler, head, threshold, adapter,
HPO, or representation adaptation fits train only. Test inference through an
already frozen encoder is not permission for test-guided adaptation.

`RNAEncoderAdapter` returns ID-aligned nucleotide embeddings with special tokens
removed and a boolean valid-position mask. `RNALLMAdapter` returns separate
structured scalar predictions, with a pinned prompt hash. `RNAAgentAdapter`
uses allowlisted tools and bounded hashed tool traces; no shell/network/tool
execution is implemented by the validator. Validation of a synthetic structure
is only `PROTOCOL_VALIDATION_ONLY`, not actual encoder/LLM/Agent performance.

Official primary README bytes were inspected on October 23, 2026 for
[RiNALMo](https://github.com/lbcb-sci/RiNALMo),
[RNA-FM](https://github.com/ml4bio/RNA-FM),
[ERNIE-RNA](https://github.com/Bruce-ywj/ERNIE-RNA), and
[Qwen3](https://github.com/QwenLM/Qwen3). The registry records source-text SHA256
and documented API snippets. Checkpoint revision, tokenizer vocabulary/hash,
maximum accepted sequence length and licensed local availability still need
verification; no model was imported or loaded for a real smoke test.

The [official Carbon repository](https://github.com/huggingface/carbon)
documents Carbon-500M/3B/8B, not the exact requested Carbon-X model. The attempted
Carbon-X Hugging Face card/config lookup failed at the network level, not as a
verified 404 or proof of nonexistence. Carbon-X therefore has unknown tokenizer,
length, prompt, checkpoint revision and RNA-native pretraining status. A proposed
RNA U→DNA T route is registered as **unapproved and unimplemented**; it requires
original/transformed hashes and cannot be equated with RNA-native ability.
Metadata from another Carbon checkpoint is not silently substituted.

## Reproducible checks and limitations

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv-qc/bin/python -m unittest discover -s tests \
  -p test_evaluation_protocol.py -v
```

The bounded worker's module tests verify train-only fitting/vocabulary/scaling,
seed direction, negative controls, identity/group split rejection, preserved
same-split conditions, finite metrics, failed admission, immutable hashes,
crash recovery, process locks, finite persistent retries, interrupted runs,
zero-write dry-runs and blocked real-model loadability. Actual synthetic smoke
writes its own `smoke_summary.json` and SHA-bound metrics; tests do not consume
any of the 45 previously acquired artifacts.

This worker does not assert the previous 81-test regression suite passed again,
resolve scientific Task 0–2, enable real assays, rebuild splits, deploy a site,
or launch frozen/GPU inference. Those remain separate main-thread workstreams.
