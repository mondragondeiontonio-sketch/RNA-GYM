# Repository reconciliation V0.6

## Verified starting point

The provided workspace contained a historical engineering copy without a Git
root at its entry point. It was not reinitialized or overwritten. A fresh clone
of the user-specified remote was fetched; both HEAD and origin/main resolved to
`27220368a186f2c4568fede27db963f23b4302dd` on 2026-11-06 UTC.
The implementation branch is `feat/mrna-v06-research-platform`.

The versioned public source snapshot covers 469 tracked baseline files.
An additional ignored local snapshot covers 65 historical configuration,
result/split metadata and budget files, including the two known persistent
SQLite GPU ledgers; no checked file changed. Original local asset roots were
read-only throughout. This is a scoped hash protection, not a claim that every
large cache/weight/prediction file on the server was independently rescanned.

## Baseline and historical evidence

Initial pytest collection: 465 tests. Initial unittest run: 465 total,
440 passed, 25 skipped, zero failures/errors. Skips are pre-existing optional
capability/environment cases, not removed tests. A real CPU numerical
installation is available; the dedicated research CI installs the optional
pinned extra rather than silently skipping the new numerical tests.

The 102-view registry is 41 five-prime and 61 three-prime views, 3,986,838
view records. It is not an independent-assay or unique-molecule count.
All 1,020 local inherited fold file hashes matched the frozen registry.
The 12-task matrix and fold metric file hashes also matched: 96 task/model/head
combinations, 960 fold rows. Labels remain z-scored in those historical metrics;
`RAW_INVERSE_PENDING` is preserved and raw inverse replay was not invented.
The frozen pilot and tiny LoRA pilot were inspected/reused, not rerun.

87 revised metadata views, 198 registry task rows, 28 canonical IDs and the
reference 248 audit rows retain their different meanings. The actual 248 source
audit and split-template files were not located in the inspected input roots.
Formal admission remains zero. Original scoring V1, splits, predictions,
model outputs and ledger authorization policy are unchanged.
