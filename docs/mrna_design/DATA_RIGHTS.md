# Data rights and publication boundary V0.6

## Separate permissions

Research, evaluation, redistribution and aggregate-publication permissions are
independent fields. A public dataset URL, source-level CC0 string or authorized
local inspection does not certify a particular private copy for publication.
The importer requires local research/evaluation permission and actual file
SHA256. Public exports additionally require reviewed aggregate/row-level rights,
explicit non-local status and no sensitive content. Approvals are not generated
by this software.

## Public versus local

Public: processing source code, configuration templates, synthetic generation
code, source hashes, already-public registry count summaries, test results,
figure gap manifests, methods, scientific holds and a provenance-only atlas.

Local-only: acquired raw tables, normalized long tables, original sequences,
per-sample labels, split assignments, hidden test truth, predictions, private
rights evidence, model weights, credentials and detailed unapproved statistics.
These remain under ignored `runs/` or existing protected storage. No new raw
file, model weight or dataset was downloaded in this execution.

The V0.6 public scanner extends the existing publication scanner, rejecting
private paths, credentials, long literal sequences and structured hidden-label
artifacts. Changed-path allowlisting and historic-asset hashes are additional
controls, not substitutes for legal review. No automatic main merge is allowed.

## Current source states

| Source | Research | Re-distribution / new phenotype statistics |
|---|---|---|
| Existing public UTR registries | Reuse existing metadata | Public registry counts/hashes only |
| Locally bound legacy UTR folds | Authorized read-only audit | No row-level release; original source review pending |
| Local Tria copies | CPU research authorized by this task | Unreviewed; long tables/predictions/results remain local |
| Penta raw copy | Target not located | BLOCKED_MISSING_RAW |
| PERSIST source evidence | Reuse prior authorized matching audit | Prior rights/version mismatch remains HOLD |
| Poly(A) leads | Bibliographic candidates only | No approved measured training table |
| ThernaBench full/gated files | Not acquired | Access conditions not bypassed |

See the public catalog and execution report for dataset-specific gaps. Formal
admission remains separate from all of the above permissions.
