# Audit status — 2026-10-22

## Completed and bounded

- Initial 4 starter unit tests passed before changes.
- A local venv, run evidence directories, quarantine and SQLite state exist.
- 47 source-entry probes were recorded; HTTP reachability is not file verification.
- All 198 task rows have a current HOLD or EXCLUDED disposition and next action.
- Nineteen public artifacts (774,074,831 compressed bytes) were downloaded and SHA-256
  verified; four small miRBench file versions passed exact paired QC only.
  All six official miRBench split files were stream-counted. Eleven explicitly
  licensed mRNABench files have Parquet footer row counts, not full scientific QC.
- Thirty-three RNAGym noncoding/splicing candidate CSV files were selectively
  extracted with a 160 MiB expanded-byte cap and counted. The other 37 members
  are mRNA-coding fitness proxies requiring separate modality/readout review.
- An incomplete review packet is deliberately rejected by the admission gate.
- No training, GPU job or foundation-model inference was started.

## Important findings

The two Klimentova compressed artifacts have different byte SHA-256 values but
954 identical ordered RNA pairs and labels. They must not be counted as two
independent assay/sample sets. There are two exact pair overlaps between the
Klimentova test file and the Hejret train file; broader homology leakage is not
checked. The Hejret train/test exact pair overlap is zero, not proof of absence
of gene/miRNA-family leakage.

The Pitt ribozyme file passes entry-level exact QC with 186 rows, 162 unique
sequences and 24 repeated sequence rows. No repeated sequences were deleted:
observation-level duplicate identity and replicate semantics are unresolved.

The RNAGym archive expands to 488,553,295 bytes, larger than the README's displayed
estimate. Two over-budget extraction attempts were stopped and retained as
failed quarantine evidence. Successful selective extraction is a new directory,
not an overwrite of raw data. A sum of 862,377 candidate file rows is **not** a
count of independent original measurements or a verified per-task sample N.

RNA3DB's 2026-01-05 full release and 2025-10-01 incremental release are both
recorded. No version is adopted: sample ID/PDB-chain differences are not yet
computed. No silent replacement of an old leaderboard has occurred.

## Remaining HOLD conditions

There are 189 HOLD task rows and 9 excluded non-assay/control rows. Original
assay DOI/accession, identity, rights, split/group leakage, full modality QC and
human review remain incomplete. No assay is REVIEW_READY or ADMITTED. This is
not full P0 acceptance and not completion of all 47 resource packages.

The mRNABench MRL-Sample mirror card declares an unknown data license and points
to GSE114002 / PRJNA454863. Those accessions are upstream claims, not reviewed
approval. Competition access/terms, unreleased SELEX and hidden labels remain
asset-specific holds. Mirrors do not override any of these restrictions.

The miRNA-only shortcut row remains a registered control, not an independent
paired-input assay and not eligible for assay/source-family weight.

## Recovery and next steps

Re-run `tools/rnagym.py download` with the same manifest, asset, explicit cap and
rights evidence to resume a failed transfer. Re-run `verify` before parsing.
For an extraction-budget change use a new named quarantine output directory;
never consume an `EXTRACTION_FAILED.json` directory as complete.

`data/audit/p0_assets.csv` identifies the actual acquired file versions.
`asset_evidence.json`, `rnagym_file_counts.tsv`, `task_status.tsv`,
`rights_audit.tsv`, `poc_overlap_summary.json`, `downloaded_file_counts.json`,
`hf_mirror_catalog.json` and `rna3db_version_review.json`
contain public aggregate evidence. Local run reports additionally hold hashes,
provenance, exact sample identity maps and the intentionally incomplete reviewer
packet. Raw experimental files and sample maps are not included in publication.

GitHub authorization was verified against the user-selected owner before any
remote change. Live deployment status must be checked in the release record and
GitHub Actions, not inferred from local verification. No access token is stored
in project files, remote URLs or publication artifacts.
