# RNA-Gym

<p align="center">
  <img src="site/assets/rna-gym-overview.svg" width="1120"
       alt="RNA-Gym: from traceable RNA data to reproducible evaluation and biological understanding">
</p>

<p align="center">
  <strong>面向 RNA 生物学能力与模型适配的开放评测平台</strong><br>
  An open evaluation and adaptation platform for RNA foundation models.
</p>

<p align="center">
  <a href="#中文"><strong>中文</strong></a> ·
  <a href="#english"><strong>English</strong></a> ·
  <a href="https://mondragondeiontonio-sketch.github.io/RNA-GYM/">Website</a> ·
  <a href="https://mondragondeiontonio-sketch.github.io/RNA-GYM/phase2.html#atlas">Dataset Atlas</a> ·
  <a href="https://mondragondeiontonio-sketch.github.io/RNA-GYM/phase2.html#qc">QC Dashboard</a> ·
  <a href="#quick-start">Quick Start</a>
</p>

<p align="center">
  <img alt="Registered task rows: 198" src="https://img.shields.io/badge/registered_task_rows-198-247a91">
  <img alt="Source families: 123" src="https://img.shields.io/badge/source_families-123-247a91">
  <img alt="Acquisition groups: 47" src="https://img.shields.io/badge/acquisition_groups-47-247a91">
  <img alt="Admitted tasks: 0" src="https://img.shields.io/badge/admitted_tasks-0-a56a23">
</p>

> [!IMPORTANT]
> **研究平台建设中，尚非正式发布的已准入 Benchmark。** 截至 **2026-10-23**，
> 198 个注册任务行、123 个来源族、47 个资源包是不同统计口径；它们均不等于
> 已核实的独立实验数量。**正式准入任务为 0，尚无经审核的真实模型成绩。**
>
> **Active research infrastructure, not an admitted benchmark release.**
> Registration, file acquisition, technical QC and scientific admission are
> separate milestones. The leaderboards intentionally contain no real scores.

---

<a id="中文"></a>

## 中文

### 为什么做 RNA-Gym

RNA Foundation Models 正在覆盖序列、结构、调控与分子功能，但现有评测通常分散在
不同生物学领域，采用不同的数据处理、模型适配与泛化评估协议。
即使两个模型都得到更高分，我们仍需要回答：**提升究竟来自预训练知识、更多标签、
更强的适配器，还是数据重叠与评测捷径？**

RNA-Gym 希望连接 **可溯源数据 → 可靠任务 → 公平评测 → 生物学理解 → 模型创新**。
我们不是把已有榜单拼在一起，而是先弄清楚每个任务“测量了什么、来自哪个实验、
在什么条件下成立”，再建立可解释的模型比较。

### 我们的 idea 与愿景

| 核心想法 | 我们希望交付什么 |
|---|---|
| **实验优先，而非文件优先** | 从原始 assay、条件与 readout 定义任务，保留完整来源链。 |
| **能力优先，而非单一总分** | 分开评估序列、结构、调控、相互作用与条件依赖能力。 |
| **公平适配，而非混合赛道** | 让预训练、适配策略、标签量与计算预算可以被分别比较。 |
| **泛化优先，而非记忆捷径** | 审计同源性、实验复用、跨数据集重叠和预训练暴露。 |
| **资源到方法的连续研究** | 用可信评测发现能力缺口，再设计预训练策略与新模型。 |

**长期愿景**：以高质量 Benchmark 为基础，系统研究 RNA 模型的能力边界，
并在独立评测数据与未来的实验验证中检验方法创新，形成
“数据资源—评测体系—模型方法—生物学验证”的连续研究路线。
这是一项研究目标，而非已经完成的实验结论。

### 我们要回答的科学问题

1. **预训练到底学到了什么？** 在相同架构、任务与预算下，比较预训练模型和随机初始化。
2. **如何高效适配？** 比较 zero-shot、冻结表征、参数高效微调与全量微调。
3. **需要多少标签？** 用受控的低资源学习曲线衡量数据效率与结果稳定性。
4. **能否跨生物学背景迁移？** 按 gene、family、cell、assay 或结构同源关系设计泛化测试。
5. **能否超越单序列？** 独立评估 RNA–RNA、结构条件、配体条件与工具辅助推理。

### 已整理的数据集版图

下面是**来源级整理范围**，不是全部完成下载或科学准入的声明。
同一来源可能支持多个任务，同一 assay 也可能被多个 benchmark 复用，不能重复计权。

| 生物学领域 | 已登记的代表性来源 | 需要区分的任务与测量 |
|---|---|---|
| mRNA 调控与命运 | mRNABench、EukaUTR | MRL、TE、half-life、定位、UTR 变异分别建卡。 |
| RNA–蛋白相互作用 | ENCODE eCLIP、RNA-Scope、PARNET | RBP、细胞条件、结合标签与来源复用。 |
| RNA–RNA / miRNA | miRBench、mRNABench miRNA-target | 双 RNA 输入、assay 身份、pair 重叠与 shortcut。 |
| 突变效应 | RNAGym DMS、NABench DMS | 构件、WT、RNA/DNA 边界及同名 assay 冲突。 |
| 逐核苷酸测量 | RNAGym/RMDB、Ribonanza、OpenVaccine | 探针、条件、位置 mask、反应性与降解标签。 |
| 二级结构 | BEACON、RNAInvBench、Wang 2D/homology 来源 | 配对索引、假结、非经典边与同源划分。 |
| 三级结构 | RNA3DB、NC-Bench、RNAGym 3D、CASP、ROMET | assembly、chain、坐标质量与结构同源性。 |
| 逆折叠与设计 | RNAInvBench、gRNAde、RDesign | 目标结构条件、序列设计与独立验证。 |
| RNA–配体 | RNAmigos2、R-BIND、Ribocentre、SMRTnet | 化合物身份、实验读出、scaffold 与 decoy。 |
| 直接 RNA 测序 | NanOlympicsMod、Dorado 修改基准 | chemistry、read/molecule 分组与修饰标签。 |

完整的 **47 个资源包清单**见[下方可展开索引](#source-package-index)。
全部 **198 个任务行**可在 [Dataset Atlas][atlas] 搜索，或直接读取
[任务注册表][tasks]、[资源包注册表][packages]、[来源族注册表][families]。
各任务的链接、reported N、baseline 计划与 HOLD 状态保存在
[独立任务卡][task-cards]和[机器可读下载索引][task-index]中；
**文献报告的 N 不等于已核实的原始实验样本量。**

### 当前真正完成了什么

**状态快照：2026-10-23。** 以下统计不能相互替代，也不能用测试通过推断科学准入。

| 层级 | 已核实的进度 | 边界 |
|---|---|---|
| 来源与任务登记 | 198 个任务行、123 个来源族、47 个资源包 | 不是 198 个独立、合格的 assay。 |
| 本地取得文件 | 50 个文件版本，共 6,593,181,246 bytes，约 6.59 GB | 不是 50 个实验；原始文件不随仓库再分发。 |
| 已冻结的文件 QC 快照 | 45 个资产，6,573,002,784 bytes，SHA256 匹配 | 后续小规模来源审计单独记录，不冒充全量重做 QC。 |
| 科学准入 | **0 个 admission candidates；0 个 ADMITTED** | 来源、许可、身份、split、QC 与人工审批仍需逐任务闭环。 |
| Baseline 与接口 | 可执行的廉价 CPU 对照；FM/LLM/Agent 协议 | 仅有合成数据 smoke，未运行真实模型评测或 GPU 训练。 |

近期的有界审计包括：

- **mRNABench**：核查 11 个已取得文件的论文/资源链，保持 MRL、TE、half-life
  和其他读出独立；Saluki 目标中的 half-life PC1 不冒充小时。
- **miRBench**：复合 pair 身份、跨任务重叠与标签冲突分开记录，不跨 assay 合并标签。
- **RMDB probing**：追踪 train/test 共享的 3 条完全相同序列，不把条件缺失当作条件相同。
- **RNA3DB**：保留版本差异与 PDB/chain 同源审计；有界坐标检查不等于全量立体化学验证。
- **T0021 / MRL**：本地固定代码与 seed 的作者逻辑复现发现 382 个跨折共享 exact-input
  键；独立 exploratory 分组版本将已检查的 exact-input、gene 与已知 homology-group
  共享数降为 0。**这不是论文官方固定 split 的结论，也不是完整 RNA 同源性清除。**
  assay/条件身份尚未闭环，因此任务继续 HOLD。

详见 [QC Dashboard][qc]、[公开审计状态][audit-status]、
[T0022 来源审计][persist-audit]与 [T0021 分组审计][mrl-audit]。
各页面保留自己的快照日期和检查范围，不能将历史统计视为最新的全量复核。

### 评测设计：统一协议，独立赛道

我们规划六条独立 FM 评测轨道，而不是把不同适配预算混为一个排行榜：

| 轨道 | 比较对象 | 当前状态 |
|---|---|---|
| Zero-shot likelihood | 不拟合下游标签的序列打分 | 协议已登记；真实模型执行未开启。 |
| Frozen + Ridge | 固定表征与线性读出 | 协议已登记；真实 encoder 未加载。 |
| Frozen + MLP | 固定表征与非线性读出 | 协议已登记；真实训练未开启。 |
| LoRA | 参数高效适配 | 独立授权与预算后执行。 |
| Full fine-tuning | 全参数适配 | 独立授权与预算后执行。 |
| Random initialization | 匹配架构与预算的从零训练对照 | 作为预训练贡献的独立对照。 |

- **RNA-FM**：登记 RiNALMo、RNA-FM、ERNIE-RNA 等候选接口；登记不等于已加载。
- **RNA-LLM**：独立定义输入、prompt、输出与版本；Qwen、Carbon-X 等候选不冒充
  RNA-native 能力。Carbon-X 版本/模型卡未核实，不宣称可用；适用时必须记录 U→T。
- **RNA-Agent**：独立记录允许使用的 RNA tools、调用轨迹与资源预算。

当前可执行的 CPU 对照包含 mean/median、prevalence/majority、序列统计 + Ridge、
k-mer Logistic Regression，以及 seed-match、miRNA-only、target-only 等负控。
XGBoost、RNAfold/RNAcofold、逐核苷酸 CNN 与结构预测方法仍需依赖和适用性审查，
**不是已经跑通的真实任务成绩**。见 [Baseline Explorer][baselines]、
[baseline 注册表][baseline-registry]与[模型适配器注册表][model-registry]。

### 研究路线与数据原则

1. **正在推进：可信数据底座。** 补齐 assay 来源、许可、测量语义、样本身份与泄露审计。
2. **近期目标：首批 5–10 个代表性任务。** 逐任务审查，证据不足就报告实际数量，不凑数。
3. **随后：受控评测。** 先廉价 CPU 基线，再按批准预算开展 frozen 与其他适配实验。
4. **中期：泛化与效率研究。** 比较低资源、跨域、条件依赖能力及适配成本。
5. **长期：模型与实验闭环。** 用独立任务和未来实验验证针对性预训练与新型 RNA FM。

所有阶段遵守：**原始数据不可变；不同条件不静默合并；RNA U 与 DNA T 的变换须留痕；
MRL、TE、RSS 不混为一个标签；标准化/HPO/阈值仅用训练数据；人工准入不由自动化代签。**

---

<a id="english"></a>

## English

### Why RNA-Gym?

RNA foundation models span sequence, structure, regulation and molecular function.
Yet benchmarks often use different processing, adaptation and generalization
protocols. Higher scores alone do not tell us whether gains come from
**pretraining, more labels, a stronger adapter, data overlap or shortcuts**.

RNA-Gym aims to connect **traceable data → reliable tasks → fair evaluation →
biological understanding → model innovation**. We start with what each
experiment measured, under which conditions, and with which provenance—not
with a merged leaderboard.

### Our idea and vision

- **Experiment-first:** define tasks through original assays, conditions and
  readouts, not filenames or benchmark aliases.
- **Capability-oriented:** evaluate sequence, structure, regulation, interactions
  and conditional reasoning as distinct biological capabilities.
- **Adaptation-aware:** disentangle pretraining, model scale, adaptation strategy,
  label availability and compute budget.
- **Generalization-focused:** audit homology, experiment reuse, cross-dataset
  overlap and potential pretraining exposure.
- **A continuous research loop:** use reliable evaluation to identify gaps,
  motivate targeted pretraining and test new models on independent evidence.

Our long-term goal is a connected research program spanning **data resources,
evaluation infrastructure, model development and future experimental validation**.
This is a research agenda, not a claim of completed biological validation.

### Scientific questions

1. What does pretraining contribute beyond matched random-initialization controls?
2. When are frozen representations sufficient, and when is adaptation necessary?
3. How does label availability affect performance, stability and sample efficiency?
4. Can models transfer across genes, families, cells, assays and structure clusters?
5. What changes when tasks require paired RNA, structure, ligand or tool context?

### Curated dataset landscape

The [bilingual dataset table above](#已整理的数据集版图) covers mRNA regulation,
RNA–protein and RNA–RNA interactions, mutation effects, nucleotide-level readouts,
2D/3D structure, inverse design, RNA–ligand tasks and direct RNA sequencing.
Sources include **mRNABench, miRBench, RNAGym, NABench, BEACON, ENCODE,
RMDB/Ribonanza, RNA3DB, NC-Bench and RNAInvBench**, among others.

The registry contains **198 task rows, 123 source families and 47 acquisition
groups**. These are different units, not counts of independently verified assays.
Use the [Dataset Atlas][atlas], [task registry][tasks], [package registry][packages]
and [per-task cards][task-cards] to inspect provenance, source-reported N,
readouts, baseline plans and unresolved holds. The
[complete package index below](#source-package-index) lists all 47 groups.
Registration does not establish availability, licensing or scientific admission.

### Evidence-backed progress

As of **2026-10-23**:

- **50 locally acquired file versions:** 6,593,181,246 bytes, approximately
  6.59 GB. They are not 50 independent experiments and are not redistributed here.
- **A frozen 45-asset technical-QC snapshot:** 6,573,002,784 bytes with matching
  SHA256 evidence. Later bounded source audits are recorded separately;
  no claim is made that all 50 assets received identical scientific QC.
- **0 admission candidates and 0 admitted tasks.** Original assay identity,
  rights, labels, splits, QC and auditable human approval remain task-specific gates.
- **Executable low-cost CPU controls and adapter contracts.** Only synthetic
  baseline smokes have run; no real FM/LLM loading, real-task scores or GPU training.

Recent work separates pair overlap from same-assay duplication in miRBench,
reviews shared probing inputs in RMDB, records RNA3DB structure/version issues,
and investigates original mRNABench readout provenance.

For T0021, a local reproduction of pinned author logic found **382 exact-input
keys shared across folds**. A separate label-blind exploratory split removes
observed exact-input, gene and known-map-group sharing. It is **not an official
published fold manifest**, does not prove full RNA homology clearance, and does
not release the task from its original-assay/condition HOLD.

Read the [QC Dashboard][qc], [public audit status][audit-status],
[T0022 source review][persist-audit] and [T0021 group audit][mrl-audit].
Each page retains its own snapshot date and evidence scope.

### Evaluation and model interfaces

Six independent FM tracks are specified: **Zero-shot likelihood, Frozen + Ridge,
Frozen + MLP, LoRA, Full fine-tuning and Random initialization**. These are
protocol contracts, not completed real-model evaluations.

**RNA-FM, RNA-LLM and RNA-Agent are separate protocol families.** Candidate model
registrations include RiNALMo, RNA-FM, ERNIE-RNA and Qwen; registration is not
checkpoint loadability or license approval. Carbon-X remains blocked pending
verified model identity/version; any U→T mapping and DNA-pretraining context must
be declared rather than presented as RNA-native evidence. Agent evaluations must
record tool access, traces and budgets.

Implemented synthetic CPU controls include null predictors, sequence-statistics
Ridge, k-mer logistic regression and paired-RNA seed/role-only controls.
XGBoost, folding tools, nucleotide-level neural models and structure predictors
remain subject to dependency and scientific-applicability review. See the
[evaluation protocol][evaluation], [baseline registry][baseline-registry] and
[model adapter registry][model-registry].

### Roadmap and non-negotiables

1. **Now:** close original-assay, rights, identity and leakage evidence gaps.
2. **First release target:** 5–10 representative admitted tasks, only if evidence
   supports them; report fewer rather than fill a quota.
3. **Next:** verified CPU baselines, then separately authorized frozen/adaptation
   experiments with explicit budgets.
4. **Research:** low-resource learning, distribution shifts, mechanism-oriented
   generalization and adaptation efficiency.
5. **Long term:** targeted pretraining and new RNA models, evaluated independently
   and eventually tested experimentally.

Keep raw data immutable. Do not merge observations across conditions or collapse
MRL, TE and RSS into one readout. Record sequence canonicalization explicitly.
Fit preprocessing, HPO and thresholds on training data only. Preserve official
splits where defensible and version any custom split separately. Never replace
human admission approval with an automated signature.

---

<a id="quick-start"></a>

## Quick start · 快速开始

Python **3.10+**; the basic CLI, metadata checks and static site use the standard
library. Full local modality QC uses the optional pinned dependencies in
[`requirements-qc.txt`](requirements-qc.txt). Ridge/logistic smokes additionally
require scikit-learn. No command below downloads model weights or starts real-model training.

```bash
git clone https://github.com/mondragondeiontonio-sketch/RNA-GYM.git
cd RNA-GYM
python -m venv .venv
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/generate_site.py --verify
.venv/bin/python tools/build_task_bundles.py --verify

# Read-only acquisition plans; no downloads.
.venv/bin/python tools/rnagym.py plan
.venv/bin/python tools/task_download.py plan --task T0014

# Synthetic CPU baseline plan; no execution or model loading.
.venv/bin/python tools/evaluation_protocol.py smoke --dry-run

# Preview the public static site locally.
.venv/bin/python -m http.server 8000 --directory site
```

Open the local preview on port **8000**. Optional browser/local-evidence tests may
skip when their dependencies or private local artifacts are absent; a skipped
test is not a passed scientific review.

下载为独立的显式操作：先核对资产许可，再设置文件大小与磁盘预算；默认拒绝未 pin SHA
的文件。镜像只改变传输入口，不替代原始来源、许可或实验身份验证。
实际下载命令与恢复约束见 [Public protocol][public-protocol]。

Downloads require a separate, explicit action with asset-specific rights review,
size/disk caps and hash verification. A Hugging Face mirror is a transport option,
not evidence of original-source equivalence or permission to redistribute.

## Project map · 项目结构

```text
RNA-GYM/
├── data/registries/       # Source, package and task metadata
├── data/task_bundles/     # One JSON card per registered task row
├── data/audit/            # Approved public metadata and aggregate evidence
├── configs/               # Baseline, adapter and QC contracts
├── tools/                 # Acquisition, provenance, QC and evaluation CLI
├── tests/                 # Safety and reproducibility regression tests
├── docs/                  # Methods, governance and public audit status
└── site/                  # Dataset Atlas, QC dashboard and empty leaderboards
```

Local raw caches, sample maps, private evidence, credentials and model weights
are not part of the public repository.

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

欢迎贡献原始来源核对、许可澄清、assay 映射、可复现 QC、适用 baseline 与适配器。
提交时请附固定版本、证据链接、实际字节 SHA256、测量语义及测试；
缺失证据请明确标为 unknown / HOLD，不要补猜 DOI、accession、许可或样本量。

Contributions are welcome for source verification, licensing clarification,
assay mapping, reproducible QC, suitable baselines and model adapters. Include
versioned evidence and tests; retain unknowns rather than inventing metadata.
Use [GitHub Issues][issues] to propose a bounded contribution. Please never
post access tokens, private experiment records or hidden test labels.

## License, attribution and citation · 许可与引用

See [LICENSE_NOTICE.md](LICENSE_NOTICE.md). This repository does **not** grant
a blanket license to upstream datasets or checkpoints. Public availability is
not permission to redistribute; each asset and original assay needs its own
rights review. The public repository distributes code, source indexes and
approved aggregate metadata—not the local raw experimental collection.

请引用实际使用的原始论文和固定数据版本，并按各来源要求署名。
RNA-Gym 暂无可引用的正式项目论文或 DOI；我们不会编造引用信息。
For now, reference this repository and the exact commit used, alongside the
upstream publications/releases. No project paper, DOI or benchmark score is
claimed.

RNA-Gym is an independent project. References to RNAGym, NABench, BEACON,
mRNABench and other sources do not imply affiliation or endorsement.

[atlas]: https://mondragondeiontonio-sketch.github.io/RNA-GYM/phase2.html#atlas
[qc]: https://mondragondeiontonio-sketch.github.io/RNA-GYM/phase2.html#qc
[baselines]: https://mondragondeiontonio-sketch.github.io/RNA-GYM/phase2.html#baselines
[persist-audit]: https://mondragondeiontonio-sketch.github.io/RNA-GYM/persist-audit.html
[mrl-audit]: https://mondragondeiontonio-sketch.github.io/RNA-GYM/mrl-split-audit.html
[tasks]: data/registries/search_level_task_crosswalk_198.csv
[packages]: data/registries/download_packages_47.csv
[families]: data/registries/source_family_crosswalk_123.csv
[task-cards]: data/task_bundles/
[task-index]: data/audit/task_download_index.jsonl
[audit-status]: docs/CURRENT_AUDIT_STATUS.md
[evaluation]: docs/EVALUATION_PROTOCOL.md
[baseline-registry]: configs/baseline_registry.yaml
[model-registry]: configs/model_adapter_registry.yaml
[public-protocol]: docs/PUBLIC_PROTOCOL.md
[issues]: https://github.com/mondragondeiontonio-sketch/RNA-GYM/issues


## Native Python SDK — 原生接口与数据标签对账（2026-10-27）

The primary API is local Python, **not OpenAI and not an HTTP client**.
See [native SDK](docs/NATIVE_SDK.md) and
[task/label audit](docs/DATASET_TASK_LABEL_AUDIT.md).
The initial registry's NO flags are historical: local data/target evidence exists,
but scientific admission, supported input contracts and formal ranking eligibility
remain separate. No real assay scores are invented.

```python
from rna_gym import RNAHub, DatasetHub, RNABenchmark

model = RNAHub.load("RNA-FM", device="cuda:0")
embeddings = model.encode(
    sequences=["AUGCUACGUACG", "GGCAUUACGU"],
    layer="last", pooling="masked_mean",
)
runner = RNABenchmark(
    dataset="mrl_sugimoto", protocol="frozen_mlp",
    split="official", seed=42,
)
results = runner.evaluate(model)
```

Current `evaluate` correctly reports scientific HOLD with available label evidence,
not a fake score. Dataset and capability rankings require compatible frozen panels,
real admitted predictions, source independence and separate review. The HTTP console
is optional legacy transport, not required by this SDK.
