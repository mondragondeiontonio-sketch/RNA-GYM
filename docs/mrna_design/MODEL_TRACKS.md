# Fair model tracks and compute V0.6

## Frozen historical evidence

Do not re-encode or rerun the completed Frozen Pilot. The existing eight-view
RNA-FM-HF pilot, the historical 12-task/4-model/2-head matrix, and the tiny
Andreasson 64/16/32 LoRA pilot remain exploratory, distinct experiments.
The historical 960 fold metrics use z-scored labels and retain
`RAW_INVERSE_PENDING`. Existing ledger and split files are immutable.

## Matched comparisons

Traditional baselines → Matched Scratch → Frozen Ridge/MLP → LoRA → Full FT
must match architecture/tokenizer (for pretraining attribution), input
availability, supervised samples, split, tuning budget and stopping rule.
CNN-versus-FM differences are not an identified pretraining benefit.
Downstream-supervised UTR encoders and MSA-augmented models need separate tracks.
Pooling is fixed using development tasks, not selected by held-out test scores.

Sample efficiency uses 128/512/2048/8192/Full label-blind nested train subsets,
three fixed seeds (6,17,29), and only feasible sizes. Control optimizer steps,
time and HPO budget, not merely epochs. Inputs exceeding a verified model limit
are ineligible, never silently truncated. Every run must save predictions,
resource usage, model revision, label identity, split hash and failure state.

## Next minimal matrix, not an authorization

1. Resolve Tria rate definition, copy-specific rights and assay identity;
   replicate B0–B4 on S-OUT for three seeds, then expand metadata-fixed cells.
2. Restore an authorized pinned Penta source and repeat its separate reporter
   protocol. No pooling with Tria y.
3. Obtain target-independent cell descriptors for C-OUT-DESC/SC-OUT; otherwise
   keep only cell-agnostic C-OUT-ID and a separately specified few-shot study.
4. Reuse eligible existing Frozen caches. Request at most **0.25 GPU-hour of
   profiling scope**, not new adaptation, only after explicit approval.
5. Profile throughput/VRAM on the actual authorized GPU and then price the
   matched Scratch/Frozen/LoRA/FT matrix before any training authorization.

The compute request has unknown throughput and `expected_gpu_hours: null`.
A hard requested profile cap is **not** a measured budget estimate. V100 FP32/
FP16 constraints must not inherit 4090 BF16/TF32 assumptions. No prior 150/670
GPU-hour plan or exhausted scope is renewed. New GPU usage in V0.6 is zero.
