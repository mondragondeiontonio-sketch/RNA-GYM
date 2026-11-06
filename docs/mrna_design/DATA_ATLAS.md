# Assay-aware mRNA design atlas V0.6

## Count semantics

| Collection | Count | Meaning |
|---|---|---|
| Original registry | 198 | Task rows, not independent assays |
| Canonical identifiers | 28 | Different aggregation unit |
| Legacy UTR | 102 = 41 5′ + 61 3′ | Inherited dataset views |
| Legacy UTR view records | 3,986,838 | Repeated views/conditions, not independent molecules |
| Revised UTR | 87 | Metadata inventory, not added to 102 |
| Historical deep matrix | 12 × 4 × 2 = 96 | Task/model/head combinations, 960 fold metric rows |
| Candidate audit table | 248 reference rows | Table not located; not 248 THERNA assays |
| PERSIST | 203 reference matched constructs | Same-construct paired labels; version/confounding holds |
| Formal core | 0 | No automatically admitted tasks or universal ranking |

## Provenance chain

Source → original experiment → assay → construct → readout × cell × time ×
replicate → versioned view → split → model run → figure. Same sequence in a
new cell is a distinct observation, not an independent source. Exact/U–T and
source/construct edges are explicit; near-homology is NOT_RUN unless supplied.
Unknown CDS, cap, delivery, dose and batch are not assumed constant.

The read-only UTR audit verifies original gzip hashes, per-view fold-0 QC,
train-normalization consistency and local cross-view sequence identities.
The importer preserves row/column/raw-hash mappings. Original readout units and
formulas remain distinct: MRL, reporter CoM, RNA/DNA activity, abundance,
transformed decay, half-life and growth/enrichment are not interchangeable y.

## Scientific gaps

Source/assay independence for pooled views remains unresolved. The missing 248
candidate table prevents its row-level reconciliation. Penta's local source
link is broken. Tria raw files are locally available but biological replicate,
rate-fitting and public-release review are incomplete. ThernaBench contextual
feature provenance is unverified. PERSIST half-life bindings and component-
sharing require resolution before joint-model claims. No tail-design factorial
training evidence is available. These gaps do not prevent CPU engineering tests,
but do prevent a formal benchmark ranking or vaccine-effectiveness claim.
