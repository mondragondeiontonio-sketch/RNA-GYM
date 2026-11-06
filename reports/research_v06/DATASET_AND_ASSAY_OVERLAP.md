# Dataset and assay overlap V0.6

## Actual audit and identity units

The local UTR audit scans all fold-0 records after verifying all ten fold hashes
per view. It checks within-view canonical sequence disjointness and builds a
SQLite cross-view identity index. Numerical overlap tables remain local because
copy-specific aggregate-publication rights were not established. The public
code can reproduce them from authorized local data. Near-homology is explicitly
NOT_RUN and construct/assay independence remains UNKNOWN.

`overlap_graph` represents exact, U/T-equivalent, same-assay, same-construct,
shared-library/backbone/release and derived-readout relationships as indexed
hyperedges; it does not delete repeated conditions or assert independent assays.
The inherited database-scale `tools/curation/overlap.py` is preserved for existing
curation. The new graph accepts explicit provenance records for the mRNA layer.

The reference 248 tables are missing, so 102↔248↔THERNA construct matching is
BLOCKED_INPUT, not silently marked no-overlap. Tria abundance and decay were
sequence/cell aligned locally with the dedicated alignment script: different
population sizes require explicit overlap/selection analysis, not an automatic
same-row join. Both remain correlated endpoints of a source library rather than
independent votes.

## PERSIST reuse, not reanalysis by relabeling

The existing source audit reports 203 matched constructs, near-float-equivalent
ribosome-load targets and an in-cell half-life source-version mismatch. Its
conservative shared-component stress test contains a large connected component
that exceeds original fold capacities. Those are prior source-bound audit
observations, not new biological discoveries. New joint training or Pareto
claims are held until source version, conditions, labels, rights and a new
component-safe split are reviewed. No labels or author split were changed.
