# Poly(A) evidence protocol V0.6

## Three distinct tasks

- `APA_USAGE`: measured cleavage/site usage or isoform proportions; not an IVT
  tail-length design outcome.
- `TAIL_LENGTH_DYNAMICS`: measured tail-length distributions at known cell/time,
  with platform, caller, selection, calibration and sample-level QC.
- `TAIL_DESIGN_FUNCTION`: known initial length, topology, linkage and modification
  paired with a real measured phenotype in a comparable construct background.

Initial design length L0 is not dynamic measured L(t). A branched/modified tail
cannot be represented faithfully by one contiguous string of A bases. Read-level
nanopore measurements are nested in biological samples, not independent
biological replicates. Report distributions/quantiles, not only a mean.

## Fail-closed gates

`rna_gym.research_v06.polya.validate_polya` rejects expression-derived,
model-generated or synthetic labels and missing measurement/design evidence.
No THERNA label is used as a Poly(A) target. Formal scoring additionally requires
the existing independent admission review. Factorial UTR × Tail × Cell claims
are rejected without cross-supported measurements in the same system.

`polyA_assay_catalog.tsv` contains **literature leads**, not admitted datasets.
Referenced TENT5A, branched-tail, measurement-calibration and enrichment-bias
sources were not independently retrieved in this network environment. Their
bibliographic leads are preserved without fabricating labels, release rights,
construct identities or a general “longer is better” conclusion.

No Poly(A) model was trained or scored. Figure 5 falls back to PERSIST paired
MRL/half-life only after resolving the documented half-life source-version
mismatch and shared-component split limitations.
