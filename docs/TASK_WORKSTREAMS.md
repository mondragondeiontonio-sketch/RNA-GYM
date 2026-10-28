# Task workstreams · RNA-Gym 任务分块

> **工作分配与身份工程，不是科学准入。** 198个旧任务行全部保留，正式准入仍为0。

## What changed · 本轮范围

本轮恢复 W00 对账，并按依赖继续 W02（仅依赖W00）的文件身份与任务契约部分。
W01 缺原始 assay/条件/单位/rights 与真实 reviewer，不伪造许可或人工签署。
W02 尚未完成原实验及 observation 的全面绑定，状态为 **PARTIAL**，不是 DONE。

The workstreams below are a deterministic view of the existing task catalog,
not a parallel registry, new experimental assays or new leaderboard weights.
Source packages may appear in several workstreams; their counts are not additive.

| Workstream | Registered rows | Scope |
|---|---:|---|
| 序列与调控 / Sequence & regulation | 68 | MRL / TE / half-life / annotation / RBP: distinct endpoints and conditions. |
| 二级结构 / Secondary structure | 13 | Paired-state, pair-edge and decoded structure are different targets. |
| 三级结构 / Tertiary structure | 16 | Assembly, chain, residue mapping, coordinate QC and structure homology. |
| 突变效应 / Variant effects | 9 | RNA substrate, WT/mutant mapping, orientation and assay/source reuse. |
| 逐核苷酸读出 / Nucleotide probing | 10 | Probe, condition, valid-position masks and raw measurement units. |
| RNA–RNA 相互作用 / RNA pairs | 6 | Role-ordered pairs, assay conditions, shared pairs and shortcut controls. |
| RNA–配体 / RNA–ligand | 15 | Compound identity, stereo/scaffold, assay labels and decoy definitions. |
| 逆折叠与设计 / Inverse folding & design | 34 | Conditioned target structures, design validity and independent evaluation. |
| 原始信号 / Direct-RNA signals | 4 | Flowcell/chemistry and molecule/read groups; no signal-to-sequence proxy. |
| 方法与待解析项 / Methods & unresolved | 23 | A coarse registered category, not a declaration that every row is excluded. |

**合计198行，不等于198个独立assay。** 方法/待解析粗类别23行并非最终排除23行；
实际全局处置仍是189 HOLD与9 EXCLUDED。公开目录内的reported N也不等于核实的assay N。

## Identity layers · 身份层次

```text
source → release → asset_id → artifact_uid (asset_id + SHA256)
       → original assay [unresolved stays unknown/HOLD]
       → observation + condition + endpoint → benchmark task → split
```

- `asset_id` remains the stable logical acquisition ID.
- `artifact_uid` identifies a specific immutable file version, not an experiment.
- Same logical ID + different SHA256: retain both versions; require explicit selection.
- Same logical ID + same SHA256: retain provenance/path aliases, not another independent version.
- Same bytes via two benchmark aliases do not become two independent experiments.
- Different conditions/readouts remain different observations; this change does not merge or drop raw rows.

The v2 catalog and private locator use `asset_id+source_sha256-v1`.
Old v1 catalogs/locators with a single unambiguous version remain readable.
Ambiguous legacy locators fail closed and must be rebuilt from original provenance.
Old snapshots and the previous private manifest are retained in local ignored runs.

## Native lookup · 兼容入口与版本消歧

For a unique version, existing calls remain unchanged:

```python
from rna_gym import DatasetHub

hub = DatasetHub()
asset = hub.resolve_asset("HF_214a7f32ac346e79b8b1")
print(asset["artifact_uid"])
```

When a logical asset has several versions, call `resolve_asset(asset_id,
source_sha256=...)` or supply the exact `artifact_uid` from the catalog.
`preview_asset` accepts the same selectors and still hashes actual local bytes before parsing.
`hub.artifacts` is the canonical version map. `hub.assets[asset_id]` remains a
compatibility lookup for a unique version; ambiguous IDs expose explicit version keys instead.
Private paths, raw observations and model weights are never exported with this index.

## Next package · 接下来的顺序

1. W02：补齐 original assay / endpoint / observation crosswalk；不能靠文件身份取代实验身份。
2. W01：挑证据最充分的单assay补齐来源与权利链；真实 reviewer 审批仍独立。
3. W03：只在相关依赖闭环后冻结 author-reproduction 与 custom split 的独立版本。
4. W04/W05：复用已核实的指标/adapter证据；改变代码或checkpoint后只重验受影响项。
5. W06：准入与预算都通过，才允许真实 baseline/FM 闭环；本轮没有训练、GPU或数据下载。

Before formal ranking or new native GPU execution, the independent review still
requires result-envelope/artifact binding, label-ledger validation, native budget
enforcement and bootstrap instability status. None is silently declared fixed by W02.
The publication CI now explicitly covers catalog/index-only changes.

## Reproducibility · 复现命令

```bash
python tools/build_workstream_index.py --verify
python tools/build_workstream_index.py --task T0021
python -m unittest discover -s tests -p test_asset_versions.py -v
python -m unittest discover -s tests -p test_workstream_index.py -v
```

These tests are software guards on synthetic fixtures, not admitted experimental results.
No GPU job, hidden-label access, downstream training or scientific approval is implied.
