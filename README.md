# RNA-Gym

<p align="center">
  <img src="site/assets/rna-gym-overview.svg" width="1120"
       alt="RNA-Gym: traceable RNA datasets, GPU embeddings and reproducible evaluation">
</p>

<p align="center">
  <strong>One Python interface. Traceable data. Honest model comparisons.</strong><br>
  面向 RNA 基础模型的原生评测接口：从真实数据与标签，到可复现的能力比较。
</p>

<p align="center">
  <a href="#quick-start"><strong>Quick start</strong></a> ·
  <a href="docs/NATIVE_SDK.md">Python API</a> ·
  <a href="docs/DATASET_TASK_LABEL_AUDIT.md">Data &amp; labels</a> ·
  <a href="#capabilities">Capabilities</a> ·
  <a href="#workstreams">Task workstreams / 任务分块</a> ·
  <a href="#fine-tasks">Task types &amp; metrics / 任务与指标</a> ·
  <a href="#中文">中文</a> · <a href="#english">English</a> ·
  <a href="https://mondragondeiontonio-sketch.github.io/RNA-GYM/">Website</a>
</p>

<p align="center">
  <a href="https://github.com/mondragondeiontonio-sketch/RNA-GYM/actions/workflows/pages.yml">
    <img alt="Main verification workflow" src="https://github.com/mondragondeiontonio-sketch/RNA-GYM/actions/workflows/pages.yml/badge.svg?branch=main">
  </a>
  <img alt="Python 3.10 or newer" src="https://img.shields.io/badge/Python-3.10%2B-3776ab">
  <img alt="Native local Python API" src="https://img.shields.io/badge/API-local_Python-247a91">
  <img alt="Formal core: 0 admitted tasks" src="https://img.shields.io/badge/formal_core-0-a56a23">
</p>

> [!IMPORTANT]
> **Research infrastructure, not an admitted benchmark release.** Updated
> **2026-10-28**: **206 upstream split protocols** pass the user-authorized reuse
> policy; **formal core: 0 admitted tasks**, with no reviewed real-assay model scores.
> The native SDK and real RNA-FM GPU encoding are verified.
> Data acquisition, label evidence, scientific admission and ranking eligibility
> are separate milestones. 本地已有数据与标签；科学 HOLD 不等于“没有数据”。
>
> Upstream protocol reuse is separate from formal task/score admission.
> See the [split and admission audit](docs/SPLIT_ADMISSION_AUDIT.md).
> The website is an audit preview with its own dated snapshots.

## At a glance · 项目概览

| What | Verified scope | What it does **not** mean |
|---|---|---|
| Registry | **198 task rows · 123 source families · 47 acquisition groups** | These are not counts of independently verified assays. |
| Original RNA-Gym source snapshot | **50 file versions · 16 package groups** | UTR extension is counted separately; raw files are not shipped. |
| UTR read-only extension | **102 dataset views · 1,020 verified fold files · 3,986,838 CV records** | The revised 87-entry metadata catalog is not an additional 87 local datasets. |
| Target evidence | **26 files/archives** with targets or reference structures | An observed target is not necessarily an admitted experimental label. |
| Native encoder | **RNA-FM**, real CUDA encoding from source and an installed wheel | Other registered models are not silently substituted. |
| Evaluation & ranking | Fixed-budget readouts and compatible-panel ranking contracts | No fabricated scores, missing-as-zero entries or unofficial main leaderboard. |

Explore the [Dataset Atlas][atlas], [QC Dashboard][qc] and
[task/label audit][label-audit]. Local-file figures describe the publisher's
snapshot, not data automatically available on a fresh clone.

<a id="workstreams"></a>

## Task workstreams · 按任务分块推进

我们按生物学输入与输出拆分工作，而不是同时启动198条任务。
下面的分块**只用于工作分配**，不新增实验、不改变旧T/X任务ID，也不合并不同测量或排行榜。
Every registered row belongs to exactly one workstream; these are not independent
assay counts or a claim that every dataset is ready to train.

<!-- WORKSTREAMS:START -->

| Workstream / 工作块 | Registered rows / 注册行 | Admitted / 准入 |
|---|---:|---:|
| 序列与调控 / Sequence & regulation | 68 | 0 |
| 二级结构 / Secondary structure | 13 | 0 |
| 三级结构 / Tertiary structure | 16 | 0 |
| 突变效应 / Variant effects | 9 | 0 |
| 逐核苷酸读出 / Nucleotide probing | 10 | 0 |
| RNA–RNA 相互作用 / RNA pairs | 6 | 0 |
| RNA–配体 / RNA–ligand | 15 | 0 |
| 逆折叠与设计 / Inverse folding & design | 34 | 0 |
| 原始信号 / Direct-RNA signals | 4 | 0 |
| 方法与待解析项 / Methods & unresolved | 23 | 0 |
| **Total / 合计** | **198** | **0** |

<!-- WORKSTREAMS:END -->



- **序列与调控 / Sequence:** first close one assay's source, units, conditions and
  split; keep MRL, TE, RSS, half-life and annotation targets distinct.
- **二级结构 / 2D:** verify paired/unpaired versus pair-edge labels, residue/token
  maps, masks and decoder. Chemical probing is a separate task, not pair truth.
- **三级结构 / 3D:** verify assembly/model/chain, missing residues, geometry and
  sequence/structure homology before model evaluation.
- **突变 / Variants:** verify RNA substrate, WT/variant round-trip, readout
  orientation and RNAGym/NABench experimental reuse; no cosine-as-fitness shortcut.
- **Other workstreams:** paired RNA, ligands, design and raw signal keep their
  own identities, labels and evaluation contracts; scalar heads do not cover them.

[完整工作块说明](docs/TASK_WORKSTREAMS.md) ·
[机器可读任务分块索引](data/registries/task_workstream_index.json)

```bash
# No downloads, model loading or training.
python tools/build_workstream_index.py --verify
python tools/build_workstream_index.py --task T0021
```

**Current continuation:** W00 hash/version reconciliation is complete. W01 is
still blocked by original-assay/rights/reviewer evidence. W02 now addresses file
version identity and work allocation; unresolved assay fields remain unknown.
The independent review still flags ranking-result identity/label-budget checks,
native execution budgets and bootstrap instability reporting. **This is not a
formal benchmark release or a declaration that those blockers are fixed.**

<!-- FINE_TASKS:START -->

<a id="fine-tasks"></a>

## 细粒度任务、数据集数量与评价指标

本表按 **52 个生物学 readout 细分类** 划分，不把 MRL、TE、半衰期、RNA/DNA activity、
蛋白 reporter output 混为“序列回归”。原 198 行与上面的 10 个工作分块保持不变。

- 原有本地 QC：**175 个 source-context/readout 数据单元**。
- UTR_bench 本地接入：**102 个 dataset/readout-condition 视图**，
  继承 1,020 个十折文件；它们不是 1,020 个数据集，也不新增 102 个已批准 assay。
- 两者合计 **277 个数据视图**；不是已完成跨来源去重的独立实验数。
- UTR 的另一份 **87 项修订目录**只接入元数据，不再加到 102 上：
  它包含 81 个 existing handles 和 6 个补充视图；与本地 102 目录相比，不含 21 个 CoM 视图。
  这是目录差异，不是已证明的直接版本迁移；相同家族/handle 不代表文件或标签版本相同。
- 同一多输出数据单元可在多个 readout 类别出现；“198 登记引用”也是多对多引用，
  **各分类行不能直接相加当作独立数据集/实验数**。0 表示该口径下尚无数据，不能凭名称补数。

### 各细分类的数量与指标

“主指标”是本轮明确写出的 **RNA-Gym 建议报告协议**，不是伪造的原论文主指标、
不是已运行分数，也不修改旧训练 receipt。机器清单的 `source_metrics_at_snapshot`
保留相应来源元信息，`metric_origin` 明确区分旧 RNA-Gym QC 建议与 UTR 代码实际输出，
不能将两者一概叫作原论文指标或已算出的分数；198 登记声称的指标也单独保留。
未确认输入/标签的登记仍需源证据核实。
表中“原尺度”指当前发布文件的数值尺度，不等于原始实验 reads 或原始仪器量；
单位/变换尚未证实的 QC 单元仍保留其 `UNRESOLVED_SOURCE_SCALE`，不得冒称已核实的小时值。

| 类别 | RNA-Gym QC 单元 | UTR 本地视图 | 87 修订目录（仅元数据） | 198 登记引用 | 主指标（本轮建议） | 次指标 |
|---|---|---|---|---|---|---|
| 序列/翻译 / MRL（原尺度） | 3 | 8 | 8 | 6 | Spearman ρ | R², Pearson r, RMSE, MAE |
| 序列/翻译 / MRL（log₂） | 0 | 4 | 4 | 0 | Spearman ρ | R², Pearson r, RMSE, MAE |
| 序列/翻译 / TE（实测定义） | 0 | 0 | 0 | 3 | Spearman ρ | R², Pearson r, RMSE, MAE |
| 序列/翻译 / TE/translation reporter score | 3 | 0 | 0 | 2 | Spearman ρ | R², Pearson r, RMSE |
| 序列/稳定性 / 半衰期（时间原尺度） | 5 | 1 | 1 | 4 | Spearman ρ | R², Pearson r, RMSE, MAE |
| 序列/稳定性 / 半衰期（log 尺度） | 1 | 4 | 10 | 2 | Spearman ρ | R², Pearson r, RMSE, MAE |
| 序列/稳定性 / 半衰期共识 PC1 | 2 | 0 | 0 | 2 | Spearman ρ | R², Pearson r, RMSE |
| 序列/稳定性 / 衰减率及其变换 | 2 | 30 | 30 | 3 | Spearman ρ | R², Pearson r, RMSE, MAE |
| 序列/稳定性 / RNA retention/stability index | 0 | 2 | 2 | 0 | Spearman ρ | R², RMSE, MAE |
| 序列/稳定性 / RNA log-retention score | 0 | 2 | 2 | 0 | Spearman ρ | R², RMSE, MAE |
| 序列/表达 / RNA abundance/expression | 4 | 16 | 16 | 3 | Spearman ρ | R², Pearson r, RMSE, MAE |
| 序列/表达 / RNA/DNA reporter activity | 0 | 12 | 12 | 0 | Spearman ρ | R², Pearson r, RMSE, MAE |
| 序列/蛋白输出代理 / Protein reporter CoM | 0 | 21 | 0 | 0 | Spearman ρ | R², Pearson r, RMSE, MAE |
| 序列/蛋白输出代理 / Protein/YFP reporter output | 3 | 1 | 1 | 2 | Spearman ρ | R², Pearson r, RMSE, MAE |
| 序列/翻译代理 / HP_Free fraction | 1 | 0 | 0 | 2 | Spearman ρ | R², RMSE, MAE |
| 序列/加工 / APA/isoform usage | 1 | 0 | 0 | 2 | Spearman ρ | R², RMSE, MAE |
| 功能注释 / GO 分子功能多标签 | 1 | 0 | 0 | 1 | macro-AUPRC | macro-AUROC, macro F1 |
| 功能注释 / Protein localization 多标签 | 1 | 0 | 0 | 1 | macro-AUPRC | macro-AUROC, macro F1 |
| RNA 定位 / RNA subcellular localization（schema 待核） | 0 | 0 | 0 | 2 | 待 schema 核实 | — |
| 家族注释 / RNA family/type annotation | 3 | 0 | 0 | 0 | macro F1 | accuracy |
| 相互作用注释 / miRNA target presence 多标签 | 1 | 0 | 0 | 1 | macro-AUPRC | macro-AUROC, macro F1 |
| RNA–RNA / miRNA–target-site binding | 3 | 0 | 0 | 1 | AUPRC | AUROC, binary F1, MCC |
| RNA–RNA / 其他 RNA–RNA interaction/duplex | 0 | 0 | 0 | 4 | AUPRC | AUROC, binary F1, MCC |
| RNA 同源性 / Sequence-pair homology/retrieval | 0 | 0 | 0 | 2 | AUROC | AUPRC, top_k_recall |
| RNA–蛋白 / RBP/CLIP/eCLIP binding | 54 | 0 | 0 | 30 | AUPRC | AUROC, binary F1, MCC |
| 结构预测 / 2D base-pair prediction | 0 | 0 | 0 | 8 | pair F1 | MCC, precision, recall |
| 结构预测 / RNA binary contact graph | 2 | 0 | 0 | 3 | contact F1 | MCC, precision, recall |
| 结构预测 / Residue distance/map regression | 0 | 0 | 0 | 2 | MAE | RMSE, R² |
| 结构预测 / 3D coordinate prediction | 1 | 0 | 0 | 12 | lDDT | TM-score, RMSD |
| 结构评估 / Model quality/decoy ranking | 0 | 0 | 0 | 3 | Spearman ρ | Pearson r, MAE |
| 化学探针 / DMS reactivity（逐核苷酸） | 1 | 0 | 0 | 4 | Pearson r | Spearman ρ, MAE, RMSE |
| 化学探针 / 2A3 reactivity | 1 | 0 | 0 | 4 | Pearson r | Spearman ρ, MAE, RMSE |
| 化学探针 / SHAPE/icSHAPE/其他 modifier | 0 | 0 | 0 | 8 | Pearson r | Spearman ρ, MAE, RMSE |
| 突变效应 / Ribozyme RNA activity DMS | 26 | 0 | 0 | 5 | Spearman ρ | Pearson r, R² |
| 突变效应 / tRNA fitness DMS | 3 | 0 | 0 | 4 | Spearman ρ | Pearson r, R² |
| 突变效应 / Aptamer fitness/activity DMS | 2 | 0 | 0 | 5 | Spearman ρ | Pearson r, R² |
| 突变效应 / RNA splicing DMS | 2 | 0 | 0 | 3 | Spearman ρ | Pearson r, R² |
| 突变效应代理 / Coding-protein phenotype DMS | 37 | 0 | 0 | 3 | Spearman ρ | Pearson r, R² |
| 突变效应待核 / DMS score，RNA 机制待核 | 5 | 0 | 0 | 6 | Spearman ρ | Pearson r |
| 变异注释代理 / Clinical/Trait variant annotation | 4 | 0 | 0 | 2 | AUPRC | AUROC, binary F1, MCC |
| 功能代理 / Growth/enrichment score | 0 | 1 | 1 | 0 | Spearman ρ | R², Pearson r |
| RNA–配体 / Binding affinity Kd/Ki | 0 | 0 | 0 | 2 | Spearman ρ | MAE, RMSE |
| RNA–配体 / Binding/native–decoy classification | 0 | 0 | 0 | 5 | AUPRC | AUROC, binary F1, enrichment_factor |
| RNA–配体代理 / Docking/derived score | 0 | 0 | 0 | 1 | Spearman ρ | R², MAE |
| RNA 设计 / 2D inverse folding | 0 | 0 | 0 | 25 | folding success | structure_f1, sequence recovery |
| RNA 设计 / 3D inverse folding | 0 | 0 | 0 | 11 | sequence recovery | perplexity, structure_consistency |
| RNA 设计 / Conditional RNA generation/editing | 0 | 0 | 0 | 1 | target_success | diversity, novelty |
| 修饰/测序 / RNA modification/site detection | 9 | 0 | 0 | 13 | AUPRC | AUROC, binary F1 |
| 修饰/测序 / Direct-RNA signal/basecalling | 0 | 0 | 0 | 0 | CER | identity_rate |
| 控制/方法 / Sanity control / method-only | 0 | 0 | 0 | 8 | 不适用 | — |
| 范围外 / DNA-only task | 0 | 0 | 0 | 6 | 依源协议确认 | — |
| 待核 / 输入/目标尚未确认 | 0 | 0 | 0 | 20 | 待 schema 核实 | — |

### 指标的含义与汇总边界

- **R²**：`1 − Σ(y−ŷ)² / Σ(y−ȳ)²`，允许负值，**不是 Pearson r 的平方**。
  定量回归在该版本已声明的 label 尺度上报告，不能混合小时、分钟、log 或 PC1。
- **Spearman ρ**：排序相关性；DMS 和无量纲共识分数优先看排序。
  常数标签/预测导致的未定义值记录 NA，不补成 0；R² 的零方差与 AUROC 的单类情况也需报告 NA。
- **F1**：区分 binary F1、macro-F1、base-pair F1 与 contact F1；阈值只由 validation
  决定。严重不平衡的结合/修饰任务以 AUPRC 为建议主指标，同时报 AUROC/F1/MCC。
- **逐核苷酸 probing**：按序列、modifier 与有效位置 mask 分别算 Pearson/MAE 等；
  化学 DMS 不等于 deep mutational scanning，不混用两个术语的标签。
- R²、相关系数、AUC 与 F1 通常越高越好；MSE/MAE/RMSE/RMSD/CER 越低越好。
- **结构和生成任务**不能统一用 R²/F1：3D 用 lDDT/TM-score/RMSD，
  inverse folding 用结构成功率或 sequence recovery，并保留具体协议条件。
- 先按 assay/readout/条件给分数；不能按样本量把镜像、多个 CV 版本或多个 readout
  重复加权。跨折 z-score 预测不能直接拼成 raw-unit pooled 指标。

### UTR_bench 已接入的 102 个本地视图

本地目录包含 **61 个 3′UTR 文件夹视图、41 个 5′UTR 文件夹视图**，
合计 **3,986,838 条 CV 记录（按任务视图计数）**，不是十折展开后的重复行数。

继承数据的 `sequence / raw_label / zscore_label / set / fold` 五列，不改 raw label、
不再次 log、不重新拟合 z-score，也不覆盖原 train/val/test。原 protected 数据继续排除。
这些 split 名为 `UTR_LEGACY_10FOLD`，**不冒充本项目新建的 EAZY 或 OOD_split**。
既有 RNA-Gym 数据仍有独立 EAZY/OOD；旧 UTR 数据的新 OOD 尚未构造。

| 来源家族 | 本地数据集视图 | 细分类 | label 单位/尺度 | 主指标 | 次指标 |
|---|---|---|---|---|---|
| castillo | 4 | MRL（原尺度） | MRL | Spearman ρ | R², Pearson r, RMSE, MAE |
| com | 21 | Protein reporter CoM | fraction/bin CoM [1,4] | Spearman ρ | R², Pearson r, RMSE, MAE |
| danio | 4 | MRL（log₂） | log2 mean ribosome load | Spearman ρ | R², Pearson r, RMSE, MAE |
| david | 2 | RNA retention/stability index | dimensionless ratio | Spearman ρ | R², RMSE, MAE |
| geisberg | 1 | 半衰期（时间原尺度） | min | Spearman ρ | R², Pearson r, RMSE, MAE |
| maputr | 6 | RNA/DNA reporter activity | ln RNA/DNA allele activity | Spearman ρ | R², Pearson r, RMSE, MAE |
| penta | 16 | RNA abundance/expression | ln1p normalized reporter RNA expression | Spearman ρ | R², Pearson r, RMSE, MAE |
| rabani | 2 | 半衰期（log 尺度） | ln(half-life / 1 hour) | Spearman ρ | R², Pearson r, RMSE, MAE |
| sabeti | 6 | RNA/DNA reporter activity | log2 RNA/DNA activity | Spearman ρ | R², Pearson r, RMSE, MAE |
| sample | 4 | MRL（原尺度） | MRL | Spearman ρ | R², Pearson r, RMSE, MAE |
| su | 2 | 半衰期（log 尺度） | ln(half-life / 1 minute) | Spearman ρ | R², Pearson r, RMSE, MAE |
| tria | 30 | 衰减率及其变换 | dimensionless negative log1p decay-rate score | Spearman ρ | R², Pearson r, RMSE, MAE |
| virus197 | 2 | RNA log-retention score | log2 ratio | Spearman ρ | R², RMSE, MAE |
| yeast_leaders | 1 | Protein/YFP reporter output | author normalized YFP reporter expression | Spearman ρ | R², Pearson r, RMSE, MAE |
| yeast_random | 1 | Growth/enrichment score | growth/enrichment | Spearman ρ | R², Pearson r |

**关键区分：**本地 UTR 包有 12 个 MRL 视图，但没有经该清单确认的独立实测 TE 视图。
RNA/DNA activity、protein CoM、YFP 与 growth score 不会为了填充 TE 类别而改名。
旧 Geisberg 102 包使用 **min**，87 修订元数据写为 **h**；两版本不换算、不合并、不互用结果。
旧目录中的 viral-genome proxy 保留该输入限定，不能仅凭 `3UTR/` 文件夹名冒称精确 3′UTR。

<details>
<summary>展开：102 个本地 UTR 数据视图的细分类与主指标</summary>

| 数据集 ID | 类别 | 条件 | N（当前本地） | label 单位 | 建议主指标 |
|---|---|---|---|---|---|
| 3UTR/001_com_SW480_Set3 | Protein reporter CoM | SW480 | 7358 | fraction/bin CoM [1,4] | Spearman ρ |
| 3UTR/002_com_NALM6_Set1 | Protein reporter CoM | NALM6 | 28124 | fraction/bin CoM [1,4] | Spearman ρ |
| 3UTR/003_com_MDAMB231_Set3 | Protein reporter CoM | MDAMB231 | 6836 | fraction/bin CoM [1,4] | Spearman ρ |
| 3UTR/004_com_Jurkat_Set1 | Protein reporter CoM | Jurkat | 28141 | fraction/bin CoM [1,4] | Spearman ρ |
| 3UTR/005_com_NALM6_Set2 | Protein reporter CoM | NALM6 | 6250 | fraction/bin CoM [1,4] | Spearman ρ |
| 3UTR/006_com_SW480_Set1 | Protein reporter CoM | SW480 | 27467 | fraction/bin CoM [1,4] | Spearman ρ |
| 3UTR/007_com_HepG2_Set2 | Protein reporter CoM | HepG2 | 7412 | fraction/bin CoM [1,4] | Spearman ρ |
| 3UTR/008_com_HepG2_Set1 | Protein reporter CoM | HepG2 | 27697 | fraction/bin CoM [1,4] | Spearman ρ |
| 3UTR/009_com_PA1_Set1 | Protein reporter CoM | PA1 | 27996 | fraction/bin CoM [1,4] | Spearman ρ |
| 3UTR/010_com_Jurkat_Set2 | Protein reporter CoM | Jurkat | 7019 | fraction/bin CoM [1,4] | Spearman ρ |
| 3UTR/011_david_Beas2B_NOT_APPLICABLE_OR_UNKNOWN | RNA retention/stability index | Beas2B | 7231 | dimensionless ratio | Spearman ρ |
| 3UTR/012_david_Jurkat_NOT_APPLICABLE_OR_UNKNOWN | RNA retention/stability index | Jurkat | 28739 | dimensionless ratio | Spearman ρ |
| 3UTR/013_geisberg_yeast_NOT_APPLICABLE_OR_UNKNOWN | 半衰期（时间原尺度） | yeast | 21244 | min | Spearman ρ |
| 3UTR/014_maputr_HeLa_NOT_APPLICABLE_OR_UNKNOWN | RNA/DNA reporter activity | HeLa | 13700 | ln RNA/DNA allele activity | Spearman ρ |
| 3UTR/015_maputr_HeLa_NOT_APPLICABLE_OR_UNKNOWN | RNA/DNA reporter activity | HeLa | 8805 | ln RNA/DNA allele activity | Spearman ρ |
| 3UTR/016_maputr_HEK293_NOT_APPLICABLE_OR_UNKNOWN | RNA/DNA reporter activity | HEK293 | 13696 | ln RNA/DNA allele activity | Spearman ρ |
| 3UTR/017_maputr_HEK293_NOT_APPLICABLE_OR_UNKNOWN | RNA/DNA reporter activity | HEK293 | 13769 | ln RNA/DNA allele activity | Spearman ρ |
| 3UTR/018_maputr_HeLa_NOT_APPLICABLE_OR_UNKNOWN | RNA/DNA reporter activity | HeLa | 13774 | ln RNA/DNA allele activity | Spearman ρ |
| 3UTR/019_maputr_HeLa_NOT_APPLICABLE_OR_UNKNOWN | RNA/DNA reporter activity | HeLa | 8805 | ln RNA/DNA allele activity | Spearman ρ |
| 3UTR/020_rabani_embryo_NOT_APPLICABLE_OR_UNKNOWN | 半衰期（log 尺度） | embryo | 89044 | ln(half-life / 1 hour) | Spearman ρ |
| 3UTR/021_rabani_oocyte_NOT_APPLICABLE_OR_UNKNOWN | 半衰期（log 尺度） | oocyte | 43591 | ln(half-life / 1 hour) | Spearman ρ |
| 3UTR/022_sabeti_HMEC_NOT_APPLICABLE_OR_UNKNOWN | RNA/DNA reporter activity | HMEC | 29816 | log2 RNA/DNA activity | Spearman ρ |
| 3UTR/023_sabeti_GM12878_NOT_APPLICABLE_OR_UNKNOWN | RNA/DNA reporter activity | GM12878 | 29816 | log2 RNA/DNA activity | Spearman ρ |
| 3UTR/024_sabeti_HEK293FT_NOT_APPLICABLE_OR_UNKNOWN | RNA/DNA reporter activity | HEK293FT | 29812 | log2 RNA/DNA activity | Spearman ρ |
| 3UTR/025_sabeti_HEPG2_NOT_APPLICABLE_OR_UNKNOWN | RNA/DNA reporter activity | HEPG2 | 29816 | log2 RNA/DNA activity | Spearman ρ |
| 3UTR/026_sabeti_SKNSH_NOT_APPLICABLE_OR_UNKNOWN | RNA/DNA reporter activity | SKNSH | 29816 | log2 RNA/DNA activity | Spearman ρ |
| 3UTR/027_sabeti_K562_NOT_APPLICABLE_OR_UNKNOWN | RNA/DNA reporter activity | K562 | 29816 | log2 RNA/DNA activity | Spearman ρ |
| 3UTR/028_su_HEK293T_NOT_APPLICABLE_OR_UNKNOWN | 半衰期（log 尺度） | HEK293T | 2280 | ln(half-life / 1 minute) | Spearman ρ |
| 3UTR/029_su_SHSY5Y_NOT_APPLICABLE_OR_UNKNOWN | 半衰期（log 尺度） | SHSY5Y | 3198 | ln(half-life / 1 minute) | Spearman ρ |
| 3UTR/030_tria_AsPC-1_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | AsPC-1 | 23008 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/031_tria_A549_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | A549 | 24400 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/032_tria_A498_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | A498 | 23138 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/033_tria_LOX-IMVI_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | LOX-IMVI | 23708 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/034_tria_RPMI-7951_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | RPMI-7951 | 19740 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/035_tria_LS_180_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | LS_180 | 22960 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/036_tria_LoVo_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | LoVo | 23280 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/037_tria_KATO_III_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | KATO_III | 19738 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/038_tria_NCI-H460_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | NCI-H460 | 24737 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/039_tria_SW480_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | SW480 | 23177 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/040_tria_H4_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | H4 | 23103 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/041_tria_SW_900_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | SW_900 | 23552 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/042_tria_Hs_766T_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | Hs_766T | 23221 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/043_tria_MIA_PaCa-2_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | MIA_PaCa-2 | 21488 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/044_tria_NCI-H23_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | NCI-H23 | 24150 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/045_tria_hTERT-HPNE_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | hTERT-HPNE | 24199 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/046_tria_A-427_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | A-427 | 20311 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/047_tria_A-172_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | A-172 | 23840 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/048_tria_SW48_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | SW48 | 23078 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/049_tria_HT-29_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | HT-29 | 21666 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/050_tria_NCI-H2030_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | NCI-H2030 | 24503 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/051_tria_NCI-H2122_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | NCI-H2122 | 23221 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/052_tria_HOP62_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | HOP62 | 24311 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/053_tria_PANC-1_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | PANC-1 | 19046 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/054_tria_J82_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | J82 | 23994 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/055_tria_NCI-H1792_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | NCI-H1792 | 23476 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/056_tria_C-33A_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | C-33A | 21197 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/057_tria_BT-474_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | BT-474 | 22480 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/058_tria_SW_1271_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | SW_1271 | 24306 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/059_tria_C32_NOT_APPLICABLE_OR_UNKNOWN | 衰减率及其变换 | C32 | 24482 | dimensionless negative log1p decay-rate score | Spearman ρ |
| 3UTR/060_virus197_UNVERIFIED_NOT_APPLICABLE_OR_UNKNOWN | RNA log-retention score | UNVERIFIED | 4655 | log2 ratio | Spearman ρ |
| 3UTR/061_virus197_UNVERIFIED_NOT_APPLICABLE_OR_UNKNOWN | RNA log-retention score | UNVERIFIED | 3059 | log2 ratio | Spearman ρ |
| 5UTR/062_castillo_HepG2_NOT_APPLICABLE_OR_UNKNOWN | MRL（原尺度） | HepG2 | 288572 | MRL | Spearman ρ |
| 5UTR/063_castillo_HEK293T_NOT_APPLICABLE_OR_UNKNOWN | MRL（原尺度） | HEK293T | 148689 | MRL | Spearman ρ |
| 5UTR/064_castillo_HEK293T_NOT_APPLICABLE_OR_UNKNOWN | MRL（原尺度） | HEK293T | 113199 | MRL | Spearman ρ |
| 5UTR/065_castillo_T_cell_NOT_APPLICABLE_OR_UNKNOWN | MRL（原尺度） | T_cell | 349632 | MRL | Spearman ρ |
| 5UTR/066_com_MDAMB231_Set1 | Protein reporter CoM | MDAMB231 | 18919 | fraction/bin CoM [1,4] | Spearman ρ |
| 5UTR/067_com_PA1_Set2 | Protein reporter CoM | PA1 | 10187 | fraction/bin CoM [1,4] | Spearman ρ |
| 5UTR/068_com_NALM6_Set1 | Protein reporter CoM | NALM6 | 21163 | fraction/bin CoM [1,4] | Spearman ρ |
| 5UTR/069_com_SW480_Set3 | Protein reporter CoM | SW480 | 6913 | fraction/bin CoM [1,4] | Spearman ρ |
| 5UTR/070_com_MDAMB231_Set3 | Protein reporter CoM | MDAMB231 | 9835 | fraction/bin CoM [1,4] | Spearman ρ |
| 5UTR/071_com_Jurkat_Set2 | Protein reporter CoM | Jurkat | 10852 | fraction/bin CoM [1,4] | Spearman ρ |
| 5UTR/072_com_HepG2_Set2 | Protein reporter CoM | HepG2 | 10888 | fraction/bin CoM [1,4] | Spearman ρ |
| 5UTR/073_com_Jurkat_Set1 | Protein reporter CoM | Jurkat | 19493 | fraction/bin CoM [1,4] | Spearman ρ |
| 5UTR/074_com_SW480_Set1 | Protein reporter CoM | SW480 | 20824 | fraction/bin CoM [1,4] | Spearman ρ |
| 5UTR/075_com_NALM6_Set3 | Protein reporter CoM | NALM6 | 10897 | fraction/bin CoM [1,4] | Spearman ρ |
| 5UTR/076_com_HepG2_Set1 | Protein reporter CoM | HepG2 | 17079 | fraction/bin CoM [1,4] | Spearman ρ |
| 5UTR/077_danio_embryo_NOT_APPLICABLE_OR_UNKNOWN | MRL（log₂） | embryo | 18021 | log2 mean ribosome load | Spearman ρ |
| 5UTR/078_danio_embryo_NOT_APPLICABLE_OR_UNKNOWN | MRL（log₂） | embryo | 18021 | log2 mean ribosome load | Spearman ρ |
| 5UTR/079_danio_embryo_NOT_APPLICABLE_OR_UNKNOWN | MRL（log₂） | embryo | 18021 | log2 mean ribosome load | Spearman ρ |
| 5UTR/080_danio_embryo_NOT_APPLICABLE_OR_UNKNOWN | MRL（log₂） | embryo | 18021 | log2 mean ribosome load | Spearman ρ |
| 5UTR/081_penta_PANC-1_NOT_APPLICABLE_OR_UNKNOWN | RNA abundance/expression | PANC-1 | 17820 | ln1p normalized reporter RNA expression | Spearman ρ |
| 5UTR/082_penta_SW48_NOT_APPLICABLE_OR_UNKNOWN | RNA abundance/expression | SW48 | 20559 | ln1p normalized reporter RNA expression | Spearman ρ |
| 5UTR/083_penta_LS_180_NOT_APPLICABLE_OR_UNKNOWN | RNA abundance/expression | LS_180 | 21047 | ln1p normalized reporter RNA expression | Spearman ρ |
| 5UTR/084_penta_HEC-1-A_NOT_APPLICABLE_OR_UNKNOWN | RNA abundance/expression | HEC-1-A | 21083 | ln1p normalized reporter RNA expression | Spearman ρ |
| 5UTR/085_penta_NCI-H2122_NOT_APPLICABLE_OR_UNKNOWN | RNA abundance/expression | NCI-H2122 | 19546 | ln1p normalized reporter RNA expression | Spearman ρ |
| 5UTR/086_penta_HT-29_NOT_APPLICABLE_OR_UNKNOWN | RNA abundance/expression | HT-29 | 17793 | ln1p normalized reporter RNA expression | Spearman ρ |
| 5UTR/087_penta_BT-474_NOT_APPLICABLE_OR_UNKNOWN | RNA abundance/expression | BT-474 | 19305 | ln1p normalized reporter RNA expression | Spearman ρ |
| 5UTR/088_penta_SW480_NOT_APPLICABLE_OR_UNKNOWN | RNA abundance/expression | SW480 | 21617 | ln1p normalized reporter RNA expression | Spearman ρ |
| 5UTR/089_penta_LoVo_NOT_APPLICABLE_OR_UNKNOWN | RNA abundance/expression | LoVo | 19525 | ln1p normalized reporter RNA expression | Spearman ρ |
| 5UTR/090_penta_NCI-H23_NOT_APPLICABLE_OR_UNKNOWN | RNA abundance/expression | NCI-H23 | 19565 | ln1p normalized reporter RNA expression | Spearman ρ |
| 5UTR/091_penta_NCI-H460_NOT_APPLICABLE_OR_UNKNOWN | RNA abundance/expression | NCI-H460 | 20675 | ln1p normalized reporter RNA expression | Spearman ρ |
| 5UTR/092_penta_NCI-H2030_NOT_APPLICABLE_OR_UNKNOWN | RNA abundance/expression | NCI-H2030 | 19826 | ln1p normalized reporter RNA expression | Spearman ρ |
| 5UTR/093_penta_HCT15_NOT_APPLICABLE_OR_UNKNOWN | RNA abundance/expression | HCT15 | 19966 | ln1p normalized reporter RNA expression | Spearman ρ |
| 5UTR/094_penta_NCI-H1573_NOT_APPLICABLE_OR_UNKNOWN | RNA abundance/expression | NCI-H1573 | 19061 | ln1p normalized reporter RNA expression | Spearman ρ |
| 5UTR/095_penta_SW1417_NOT_APPLICABLE_OR_UNKNOWN | RNA abundance/expression | SW1417 | 19475 | ln1p normalized reporter RNA expression | Spearman ρ |
| 5UTR/096_penta_KATO_III_NOT_APPLICABLE_OR_UNKNOWN | RNA abundance/expression | KATO_III | 20381 | ln1p normalized reporter RNA expression | Spearman ρ |
| 5UTR/097_sample_HEK293T_NOT_APPLICABLE_OR_UNKNOWN | MRL（原尺度） | HEK293T | 308882 | MRL | Spearman ρ |
| 5UTR/098_sample_HEK293T_NOT_APPLICABLE_OR_UNKNOWN | MRL（原尺度） | HEK293T | 99301 | MRL | Spearman ρ |
| 5UTR/099_sample_HEK293T_FULL_LIBRARY_subset_column_retained | MRL（原尺度） | HEK293T | 106522 | MRL | Spearman ρ |
| 5UTR/100_sample_HEK293T_NOT_APPLICABLE_OR_UNKNOWN | MRL（原尺度） | HEK293T | 210641 | MRL | Spearman ρ |
| 5UTR/101_yeast_leaders_yeast_NOT_APPLICABLE_OR_UNKNOWN | Protein/YFP reporter output | yeast | 9382 | author normalized YFP reporter expression | Spearman ρ |
| 5UTR/102_yeast_random_BY4741_NOT_APPLICABLE_OR_UNKNOWN | Growth/enrichment score | BY4741 | 489348 | growth/enrichment | Spearman ρ |

</details>

### 旧 UTR 评测结果究竟报告什么

本地旧 102 包 ML 代码实际计算 **Spearman、MSE、MAE**，完整十折才汇总 raw-unit OOF；
Selected12 迁移结果另有 **Spearman、Pearson、MSE、RMSE、MAE、R²** 六项，
不能把后一套字段冒称旧 102 包已全部计算。
这不意味着旧实验曾声明本表的新建议主指标。Selected12 迁移矩阵实际有
**96 个 model×dataset×head 记录**、
**12 个数据集**，记录的是 fold-mean 指标及其 label 尺度。
其中 **960 条 Full fold 指标**均是既有结果，
Selected12 的 **120 个源 fold 文件 SHA256**
匹配本轮接入的旧 102 包，而不是 87 项修订目录。96 个矩阵记录均为 `zscore_label` 尺度。
该矩阵的 `reporting_status` 为 `RAW_INVERSE_PENDING`，raw pooled 分数为空；
**这些是旧项目的非主榜中间结果，不是新 RNA-Gym 正式分数**。本轮没有训练、重算或换算这些分数。

### 查询与复用

```python
from rna_gym import DatasetHub

hub = DatasetHub()
hub.categories()                          # 每类数量、主指标、次指标
hub.dataset_views(category="seq.mrl.native")
hub.dataset_views(source="UTR_LEGACY_102")

# 仅在已绑定本地 UTR 数据的环境可读；fresh clone 不自动下载数据。
data = hub.utr("UTR102:5UTR/102_yeast_random_BY4741_NOT_APPLICABLE_OR_UNKNOWN")
data.preview(fold=0, rows=3)
for row in data.iter_fold(fold=0, split="test"):
    break  # 保留原始标签与既有划分；读取不是科学准入或训练授权。
```

机器入口：
[fine taxonomy](data/registries/fine_task_catalog.json)、
[UTR 本地 102 清单](data/registries/utr_legacy_102.json)、
[UTR 87 版本元数据](data/registries/utr_revised_87_metadata.json)、
[旧结果状态](data/registries/utr_historical_result_status.json)。
原 198 行、175 个 QC 数据版本、已有 split、标签、正式 gate 和人工审批均未改写。

<!-- FINE_TASKS:END -->

## Existing splits · 现有划分与复用准入

**50 local files rehashed · 377 protocol variants checked · 206 accepted for upstream reuse.**
This is **not** 206 independent experiments or formal leaderboard entries.

| Source | Scoped reuse passes | Important boundary |
|---|---:|---|
| RNAGym DMS | 56 | Train/validation, **development only**; never renamed test. |
| EukaUTR | 147 | 86 test protocols + 61 dev protocols; editor checkpoints excluded. |
| miRBench | 2 | Original Hejret/Manakov splits; no unreviewed cross-source pooling. |
| RNA3DB | 1 | Matching 2026-01-05 split/reference release; empty valid kept. |
| RMDB / unresolved sources | HOLD | Shared inputs, unresolved recipe or unmatched release remain explicit. |

```python
from rna_gym import DatasetHub

hub = DatasetHub()
protocols = hub.protocols(admitted=True)
print(len(protocols))                        # 206 in the 2026-10-28 snapshot
protocol = next(iter(protocols))
print(protocol["admission_scope"])           # UPSTREAM_PROTOCOL_REUSE
print(protocol["raw_bytes_available_now"])
```

每个协议保留成员文件、角色、行数、hash、输入/标签列与固定作者工作流。
通过复用准入不等于旧 T/X 任务已完成 exact binding、模态 adapter、执行预算或正式结果审查。
原始数据不随 Git 分发；所有 377 项候选（包括 171 项 HOLD）均保留。
完整检查与恢复方法见 [划分与科学复用准入审计](docs/SPLIT_ADMISSION_AUDIT.md)。

<a id="quick-start"></a>

## Quick start · 快速开始

### 1. Explore datasets — no GPU, weights or API key required

Use **Python 3.10+**. Catalog inspection from the checkout needs only the standard
library; it does not download data or contact a model service.

```bash
git clone https://github.com/mondragondeiontonio-sketch/RNA-GYM.git
cd RNA-GYM
```

```python
from rna_gym import DatasetHub, RNAHub

hub = DatasetHub()
print(len(hub.list()))                  # 198 original task IDs
print(hub.get("T0021").describe())       # MRL task, label evidence and HOLD reasons
print(RNAHub.list())                    # Registered models != implemented adapters
```

For editable installation in an existing environment with `setuptools>=61` and
`wheel`, use `python -m pip install --no-deps --no-build-isolation -e .`.
A wheel contains code, not the registries or private assets: set `RNA_GYM_ROOT`
or pass `root=` to the checkout when using a non-editable installation.

### 2. Encode RNA — bring a verified local checkpoint and CUDA runtime

This step requires a reviewed, hash-pinned RNA-FM source/checkpoint/model-card
manifest and a compatible local GPU environment. The manifest below is a
**user-provided file**, not a bundled example or an automatic download.
See the [native SDK setup][sdk] for requirements.

```python
from rna_gym import RNAHub, RNABenchmark

model = RNAHub.load(
    "RNA-FM",
    manifest="runs/local/rnafm_manifest.json",
    device="cuda:0",
)
embeddings = model.encode(
    sequences=["AUGCUACGUACG", "GGCAUUACGU"],
    layer="last",
    pooling="masked_mean",
)
print(embeddings.shape)                 # (2, 640)

runner = RNABenchmark(
    dataset="mrl_sugimoto",
    protocol="frozen_mlp",
    split="official",
    seed=42,
    output="runs/pilots/mrl",
)
results = runner.evaluate(model)
print(results.status)                  # BLOCKED until this assay is admitted
```

- Every FM forward runs on **CUDA**; there is no CPU fallback or model download.
- Exact `A/C/G/U` input only: no silent T→U conversion, normalization or truncation.
- Relative manifest and run-output paths resolve against the checkout, not the
  current shell directory. Evaluation artifacts stay inside ignored `runs/`.
- `split="official"` requests a reviewed binding; it does not invent an official
  split. `seed=42` is exploratory, not the formal five-seed matrix.
- `BLOCKED`, `FAILED`, `NOT_APPLICABLE` and partial execution remain distinct.
  A model forward passing is not a real functional-assay score.

<a id="capabilities"></a>

## What works today · 能力状态

| Component | Implemented / verified | Remaining boundary |
|---|---|---|
| `DatasetHub` | 198-task catalog, bounded preview and 206 scoped upstream split protocols | Local bytes and assay-level identity/rights must be supplied and reviewed. |
| `RNAHub.load` / `encode` | RNA-FM on CUDA; last-layer masked mean or per-nucleotide arrays | Other five registered backends are not yet native-verified. |
| `RNABenchmark.evaluate` | Existing admission gate, frozen scalar heads, predictions/metrics/statistics artifact path | No assay currently passes all scientific gates. |
| Fixed-label readouts | Ridge, binary linear/logistic and MLP; train-only preprocessing, budget ≤64 | Numerical contract tests are synthetic software tests, not biological results. |
| `RNALeaderboard` | Dataset panels and source-aware capability aggregation contracts | Real admitted predictions, a complete fixed panel and independent review required. |
| Optional HTTP console | Existing local transport layer | Not the primary API; no OpenAI dependency or API key needed for the SDK. |

### Evaluation tracks

| Track | Current implementation boundary |
|---|---|
| **Zero-shot likelihood** | Registered protocol; no native functional likelihood pilot. |
| **Frozen + Ridge** | Real RNA-FM encoder verified; fixed scalar readout tested. |
| **Frozen + MLP** | Real RNA-FM encoder verified; fixed scalar readout tested, no admitted assay fit. |
| **LoRA** | Separate adapter, protocol and execution budget still required. |
| **Full fine-tuning** | Separate implementation and execution budget still required. |
| **Random initialization** | Encoder initialization is an explicit factor; no real task comparison claimed. |

Multilabel, token, pair, structure, ligand-conditioned and generation tasks need
modality-specific heads and protocols. They are **not** converted into scalar MLP
problems. Persistent shared native execution budgets (review R03) remain incomplete; do not
launch an unbounded real-data matrix. See the [evaluation protocol][evaluation] and
[model registry][model-registry].

## Two views of model quality · 两种排名，不拼凑总分

| View | Comparable unit | Fairness rule |
|---|---|---|
| **By dataset** | Same assay/endpoint, split, input context, protocol, initialization, label budget and seed panel | No best-head selection, dropped failures or post-hoc common subset. |
| **By capability** | Same capability and primary metric, with reviewed assay/source mapping | Average assays within a source cluster, then weight source clusters equally. |

Signed Spearman stays signed. Average precision (AP) uses the threshold-step
precision–recall definition in the [evaluation protocol][evaluation], not
trapezoidal PR-AUC. Spearman, AP, pair-F1 and geometry metrics are not mixed into
an arbitrary global score. Missing or blocked cells remain `None`, never zero.
The ranking API example and panel requirements are in the [SDK guide][sdk].

## Data & labels · 数据与标签

Our catalog integrates existing sources without claiming ownership of their data:

| Domain | Representative registered sources | Keep separate |
|---|---|---|
| mRNA regulation & fate | mRNABench, EukaUTR | MRL, TE, half-life, localization and variant effects. |
| Binding & interactions | miRBench, ENCODE eCLIP, RNA-Scope, RNAmigos2 | Paired RNA, protein/site and ligand-conditioned tasks. |
| Variant & nucleotide measurements | RNAGym DMS, NABench, RMDB, Ribonanza | WT/variant context, native fitness and token-level readouts. |
| Structure & design | RNA3DB, bpRNA, RNAStrAlign, RNAInvBench | 2D pairs, 3D coordinates and conditional generation. |

These are source-level registrations, not a claim that every benchmark is
fully downloaded, labeled, licensed or admitted. Annotation targets, proxy labels,
experimental measurements and model-result tables are not interchangeable.
The [complete label audit][label-audit] explains all original task types, observed
targets and unresolved input/split issues.

**A concrete gate, not a vague disclaimer:** the T0021 audit found 382 shared
exact-input keys across folds in a local author-logic reconstruction. This is
**not an official** fixed-split conclusion or **full RNA homology clearance**.
A separately named exploratory grouped split removes the checked overlaps, but
**original-assay/condition HOLD** remains. See the [MRL split audit][mrl-audit].

<a id="中文"></a>

## 中文

### 我们的 idea 与愿景

RNA-Gym 连接 **可溯源数据 → 可靠任务 → 公平评测 → 生物学理解 → 模型创新**。
我们不只拼接现有榜单，而是先弄清每个标签测量了什么、来自哪个 assay、在什么条件下
成立，再比较预训练知识、适配方法、标签量和计算预算的贡献。

科学问题包括：预训练相对随机初始化学到了什么；冻结表征与适配方法如何比较；
需要多少标签；能否跨 gene/family/cell/assay 迁移；以及单序列以外的条件是否真正
改善预测。结构 native 输出与标签校准输出分轨，不把不同信息预算混为一种能力。

近期目标是完成首个真实 assay 的完整链路，再扩展到首批 5–10 个代表任务；实际数量
以准入证据为准，不为凑数删除任务、减少种子或跳过 gate。长期希望用可信评测识别
能力缺口，支持针对性预训练、新模型和独立实验验证。这是研究路线，不是已完成结论。

<a id="english"></a>

## English

### Our idea and vision

RNA-Gym connects **traceable data → reliable tasks → fair evaluation → biological
understanding → model innovation**. The goal is not another merged score table:
we distinguish what was measured, in which assay and context, before attributing
improvement to pretraining, adaptation, label count or compute.

### Scientific questions

1. What does pretraining contribute beyond matched random initialization?
2. Which frozen or trainable adaptation strategy is effective at the same budget?
3. How many labels are needed, including labels spent on tuning and calibration?
4. Does performance transfer across genes, families, cells and assays?
5. When do paired inputs, structure, ligands or tools add genuine predictive value?

The near-term milestone is one real, admitted end-to-end assay, followed by a
representative panel only where evidence supports it. Longer-term model and
experimental work are research goals, not completed findings. Preserve upstream
splits when defensible, version custom splits, require asset-specific
rights review and never replace human admission approval with an automated signature.

## Verify locally · 本地验证

```bash
python -m unittest discover -s tests -v
python tools/generate_site.py --verify
python tools/build_task_bundles.py --verify
python tools/rnagym.py plan
python tools/evaluation_protocol.py smoke --dry-run
python -m http.server 8000 --directory site
```

These commands do not download data or launch FM training. Optional numeric,
browser and private-evidence tests explicitly skip when requirements are absent;
skips are not scientific passes. Full local QC dependencies are documented in
[requirements-qc.txt](requirements-qc.txt). Acquisition is a separate explicit,
budgeted action described in the [public protocol][public-protocol].

## Project map · 项目结构

```text
RNA-GYM/
├── rna_gym/              # Native model, dataset, benchmark and ranking API
├── configs/              # Existing model, protocol and execution contracts
├── data/registries/       # Public task/source/package catalog, not raw data
├── data/task_bundles/     # All original task cards
├── tools/                 # Acquisition, provenance, QC and execution
├── tests/                 # Safety, numerical and documentation contracts
├── docs/                  # Methods, API and audit status
└── site/                  # Public atlas, QC dashboard and audit preview
```

<a id="source-package-index"></a>

## Source package index · 全部资源包

<details>
<summary><strong>展开 / Expand: 47 registered acquisition groups</strong></summary>

These are management groups, not independent original assays. Task-row counts
come directly from the frozen package registry and include controls and
methodology-only entries. Listing is not an availability or admission claim.

下表直接对应资源包注册表，包含 control / methodology 条目。
同一原始实验可能跨来源复用；不可据此累加独立实验数或样本数。

| Package ID | Source / 来源 | Registered rows / 注册行 |
|---|---|---:|
| `APTAMER_DB` | Ribocentre aptamer experimental records | 2 |
| `BEACON_ALL` | BEACON 13 downstream datasets | 13 |
| `CASP` | CASP Nucleic Acid blind structures | 2 |
| `DORADO_MOD` | Nanopore Dorado modification benchmarks | 2 |
| `ENCODE_ECLIP` | ENCODE CLIP original experiment accessions | 23 |
| `EUKAUTR` | EukaUTR nine UTR task families | 12 |
| `GRNADE` | gRNAde geometric inverse design | 3 |
| `METHODOLOGY_ONLY` | Methodology or tools (no independent assay) | 4 |
| `MIR_BENCH` | miRBench corrected AGO2 CLASH/eCLIP | 2 |
| `MRNA_ECLIP` | mRNABench HF: eclip | 1 |
| `MRNA_GO_MF` | mRNABench HF: go-mf | 1 |
| `MRNA_MIRNA_TARGET` | mRNABench HF: mirna-target | 1 |
| `MRNA_MRL_HL_LBKWK` | mRNABench HF: mrl-hl-lbkwk | 1 |
| `MRNA_MRL_SAMPLE` | mRNABench HF: mrl-sample | 1 |
| `MRNA_MRL_SUGIMOTO` | mRNABench HF: mrl-sugimoto | 1 |
| `MRNA_PROTEIN_LOCALIZATION` | mRNABench HF: protein-localization | 1 |
| `MRNA_RNAHL_SALUKI_HUMAN` | mRNABench HF: rnahl-saluki-human | 1 |
| `MRNA_RNAHL_SALUKI_MOUSE` | mRNABench HF: rnahl-saluki-mouse | 1 |
| `MRNA_RNA_LIFECYCLE_IETSWAART` | mRNABench HF: rna-lifecycle-ietswaart | 1 |
| `MRNA_RNA_LOC_FAZAL` | mRNABench HF: rna-loc-fazal | 1 |
| `MRNA_TRANSLATION_EFFICIENCY_HUMAN` | mRNABench HF: translation-efficiency-human | 1 |
| `MRNA_TRANSLATION_EFFICIENCY_MOUSE` | mRNABench HF: translation-efficiency-mouse | 1 |
| `MRNA_UNRESOLVED_RNA_LOC_LR` | mRNABench RNA-Loc-LR (identity unresolved) | 1 |
| `MRNA_UTR_VARIANTS_BOHN` | mRNABench HF: utr-variants-bohn | 1 |
| `MRNA_VEP_TRAITGYM_MRNA` | mRNABench HF: vep-traitgym-mrna | 1 |
| `NABENCH_DMS` | NABench released DMS individual assay files | 10 |
| `NABENCH_SELEX` | NABench SELEX (processing pending) | 2 |
| `NANOLYMPICS` | NanOlympicsMod direct RNA sequencing | 2 |
| `NC_BENCH` | NC-Bench noncanonical pair edges+orientations | 2 |
| `OPENVACCINE` | OpenVaccine degradation challenge | 3 |
| `PARNET` | PARNET supervised pretraining (not full released dataset) | 4 |
| `RDESIGN` | RDesign tertiary inverse folding | 2 |
| `RIBONANZA_ORIGINAL` | Ribonanza challenge original reference files | 2 |
| `RNA3DB` | RNA3DB release with structure-homology split | 3 |
| `RNABENCH_SOFTWARE` | RnaBench algorithm library | 2 |
| `RNAGYM_3D` | RNAGym 3D PDB structure benchmark | 1 |
| `RNAGYM_DMS` | RNAGym DMS assay processed+raw | 3 |
| `RNAGYM_RMDB` | RNAGym RMDB / Ribonanza probing | 6 |
| `RNAMIGOS2` | RNAmigos2 ligand pockets / docking / ROBIN | 4 |
| `RNA_INV_BENCH` | RNAInvBench inverse design public sets | 26 |
| `RNA_PUZZLE_TOOL` | RNA-Puzzles structure evaluation toolkit | 2 |
| `RNA_SCOPE` | RNA-Scope multi-task benchmark files | 13 |
| `ROMET` | ROMET-RNA structure benchmark | 2 |
| `R_BIND` | R-BIND 2.0 curated RNA-ligand database | 2 |
| `SECONDARY_LITERATURE` | RNA structure/interaction method-specific derived data | 21 |
| `SMRTNET` | SMRTnet processed ligand pairs | 2 |
| `WANG_ZERO_SHOT` | Wang zero-shot 2D/homology study supplement | 5 |

</details>

## Contribute · 参与建设

Contribute a bounded source review, label/assay mapping, reproducible QC or a real
model adapter through [GitHub Issues][issues]. Include pinned versions, hashes,
measurement semantics and tests. Keep unknowns explicit; do not guess a DOI,
license, accession or sample count. See the [current audit status][audit-status].

请勿提交原始实验数据、模型权重、凭据、私有样本映射或人工审批文件。
Scientific gates and the formal seed panel `[11, 23, 47, 71, 101]` must remain
unchanged. Do not tune a formal protocol on test performance.

## License & attribution · 许可与引用

See [LICENSE_NOTICE.md](LICENSE_NOTICE.md). This repository does **not** grant a
blanket license to upstream datasets or checkpoints. Public availability is not
permission to redistribute. Cite the actual upstream publications, fixed data
versions and exact repository commit used. No project paper or DOI is claimed.

RNA-Gym is independent. References to RNAGym, NABench, BEACON, mRNABench and other
sources do not imply affiliation or endorsement. The repository distributes
code, indexes and approved aggregate metadata—not the local experimental collection.

[atlas]: https://mondragondeiontonio-sketch.github.io/RNA-GYM/phase2.html#atlas
[audit-status]: docs/CURRENT_AUDIT_STATUS.md
[evaluation]: docs/EVALUATION_PROTOCOL.md
[issues]: https://github.com/mondragondeiontonio-sketch/RNA-GYM/issues
[label-audit]: docs/DATASET_TASK_LABEL_AUDIT.md
[model-registry]: configs/model_adapter_registry.yaml
[mrl-audit]: https://mondragondeiontonio-sketch.github.io/RNA-GYM/mrl-split-audit.html
[public-protocol]: docs/PUBLIC_PROTOCOL.md
[qc]: https://mondragondeiontonio-sketch.github.io/RNA-GYM/phase2.html#qc
[sdk]: docs/NATIVE_SDK.md
