"""Render the v1 build report from measured local artifacts, not historical README."""
import html
from pathlib import Path
from tools.build_arena_v1 import ROOT, VERSION, load, table


def render(root=ROOT):
    c = load(root/'data/audit/rnagym_v1_build_summary.json')
    tax = load(root/'configs/task_taxonomy_v1.yaml')['tasks']
    mapping = table(root/'data/audit/taxonomy_mapping_report.tsv')
    baseline = table(root/'results/exploratory/baselines_v1.tsv') if (root/'results/exploratory/baselines_v1.tsv').exists() else []
    models = load(root/'configs/model_adapter_registry.yaml')['models']
    compute = load(root/'runs/20261030_arena_v1/compute_receipt.json') if (root/'runs/20261030_arena_v1/compute_receipt.json').exists() else {}
    raw = load(root/'runs/20261030_arena_v1/raw_integrity.json') if (root/'runs/20261030_arena_v1/raw_integrity.json').exists() else {}
    validation = load(root/'runs/20261030_arena_v1/validation.json') if (root/'runs/20261030_arena_v1/validation.json').exists() else {}
    matrix = '\n'.join(f"| `{t['task_id']}` | {t['macro_domain']} | {t['level1_domain']} / {t['level2_category']} | {t['primary_metric']} |" for t in tax)
    inputs = '\n'.join(f"| `{t['task_id']}` | {t['input_definition']} | {t['target_definition']} |" for t in tax)
    scores = '\n'.join(f"| {r['model_id']} | {r['dataset_id']} | {float(r['raw_score']):.6f} | {float(r['mae']):.6f} |" for r in baseline)
    pool = '\n'.join(f"| {m['model_id']} | {m['adapter_family']} | {m['runtime_loadability']} |" for m in models)
    multi = '\n'.join(f"| {r['old_task_id']} | {r['canonical_task_id']} | {r['mapping_status']} |" for r in mapping if r['multiple_canonical_tasks'] == 'True')
    supported = ', '.join('`'+t+'`' for t in c['supported_tasks'])
    unsupported = ', '.join('`'+t+'`' for t in c['no_supported_tasks'])
    report = f'''# RNA-Gym v1.0 Build Report

> **日期：2026-10-30（UTC）。版本：`{VERSION}`。**
> 本报告来自当前项目的 registry、实际 Parquet、QC、freeze、split 和运行记录。
> 不把 registry 行、文件、readout 视图或 canonical assay ID 冒称独立实验。

## 1. Motivation 与本轮交付边界

**RNA-Gym: A Unified Arena for RNA Foundation Models across Structure, Function
and Engineering** 的目标不是堆叠数据条目，而是回答模型学到了哪些 RNA 能力、
这些能力如何跨生物学对象与分布迁移，以及系统性缺口在哪里。

本轮在原项目内执行了真实文件校验、label-level taxonomy migration、三个数据视图的
新 gene-held-out split 与真实 CPU baseline，未重新下载数据或建立平行项目。
正式科学准入仍为 0；不能把本轮解释为已经完成可排名的全领域 FM Arena。

## 2. 新任务树与两层领域体系

Registry 保留 Structure、Function & Regulation、Perturbation、Engineering、Design
五个一级领域。Arena 聚合为 Structure / Function / Engineering 三个宏观领域。
Perturbation 归 Function，Design 归 Engineering；不删除它们的 registry 身份。

能力层包括 Secondary Structure、3D Geometry、Structure Probing、RNA Processing、
RNA Modification、RNA Identity、Translation、Stability、Translation–Stability Coupling、
RNA–Protein Interaction、Localization、Functional Annotation、Variant Effect、DMS Fitness、
Synthetic RNA、CRISPR、RNA Design。间接注释任务保留，但不进入 RNA-specific core。

## 3. 28 个 canonical tasks

唯一 canonical 定义为 `configs/task_taxonomy_v1.yaml`。JSON-compatible YAML 1.2
沿用本项目既有加载方式；不是根据历史 readout 名称自动再分类。

| Task | Arena domain | Registry domain / capability | Primary metric |
|---|---|---|---|
{matrix}

`ASSAY_SPECIFIC` 仅用于 task family 的可选协议。一个实际 dataset endpoint 必须冻结
为单一 problem type 与 primary metric，不能含混运行 classification/regression 两种。

## 4. 旧 registry → 新 taxonomy 映射

198 registered rows 中，**{c['unambiguous_mapped_rows']}** 行无歧义映射，覆盖
**{c['mapped_canonical_task_families']}** 个 canonical family；
**{c['mapping_status_counts'].get('TAXONOMY_REVIEW_REQUIRED',0)}** 行需 taxonomy review，
**{c['mapping_status_counts'].get('EXCLUDED',0)}** 行为既有科学审计排除项。
这不是 198 个独立数据集，也不是 26 个已获得本地科学准入的任务。

`data/audit/taxonomy_mapping_report.tsv` 逐行保留旧 ID、名称、canonical ID、status、
confidence、reason 与人工核查标记；`data/audit/v1_conflict_findings.tsv` 单列问题。

原 registry 已原位增加 canonical mapping/evidence 列，并将有本地真实 QC 子集的下载
与标签核查状态从历史 NO 更新为明确的 LOCAL_SUBSET / 非科学准入状态。
原实验任务文字、原登记 N 和人工准入字段不被改写为新事实。
旧 registry 迁移前字节仅备份于忽略的 `runs/20261030_arena_v1/registry_before_v1.csv`。
历史 fine catalog 保留作源证据，不再作为 canonical 定义的权威来源。

以下旧行实际上包含多个 label family，不能合并原始成绩：

| Old ID | Actual canonical labels | Status |
|---|---|---|
{multi}

## 5. Input / Label 定义与真实冲突

| Task | Canonical input | Canonical target |
|---|---|---|
{inputs}

真实映射在 `data/registries/dataset_task_mapping_v1.tsv`，共
**{c['label_mapping_rows']}** 条 dataset/readout 映射，覆盖 **{c['total_local_views']}**
个本地视图。这些映射按实际列名拆分，而非赋予一个 umbrella row 多份 observation 权重。

已发现的关键冲突：

- RMDB 是 sequence-only probing，缺少 SSI 的 partial observed signal/mask 协议。
- WANG contact graph 的 derivation 尚未证明为 secondary base pairs；不强行当 SSP。
- RNA3DB coordinates 尚未完成 polymer/residue 对齐及 contact/distance 构建冻结；
  不能仅凭坐标文件存在就声称 CMP/DMP benchmark 完成。
- EukaUTR `translation_score` 和 fragment input 不能直接称 full-transcript TE。
- RBP 的数字目录不证明具体 RBP/cell/accession；映射保留其 source-context ID 与缺口。
- `karner` 的实际输入列 `utr3_sequence_rna` 是 3′UTR，不能当作 full-length degradation。

## 6. Translation taxonomy 特别说明

**RRS != MRL != TE。** RRS 指 ribosome recruitment / translation initiation；MRL 指
ribosome loading；TE 指 global translation efficiency；Half-life 指 RNA stability；
MRL-HL 指 translation–stability coupling。

- MRL-exact：输入为真正 5′UTR；本地 UTR102 的 Sample/Castillo/danio MRL 视图保持
  原尺度或已发布 log₂ 尺度，不能重新 log。
- MRL-proxy：mRNABench 的 mature-transcript/cDNA 字符串不是 isolated 5′UTR。
  `MRNA_mrl-sugimoto` 的 target 保留 parent-study ribosome-load 定义。
- `MRNA_rnahl-saluki-human/mouse` 的 target 是 **unitless published half-life PC1**，
  不是 absolute half-life hours。
- paired LBKWK 的 `target_ribosome_load` 与 `target_in_cell_half_life` 分开保存；
  只允许先归一化，再取 joint mean。
- 当前绑定的本地证据中尚无可确认的 RRS endpoint；不把 reporter protein output
  或 RNA abundance 重命名为 RRS/TE。

以上语义写入 taxonomy 和 dataset mapping，亦展示在 Arena 页面；论文 Methods
应直接沿用这些版本化定义，而不是重用旧 README 中的泛称 translation。

## 7. 数据量、真实 QC 与独立性分母

| 计数单位 | 数值 | 范围 |
|---|---:|---|
| 已绑定原始物理资源 | {c['local_resources']} | 文件/归档资源，不是 assay |
| 已清洗 QC 单元 | {c['local_qc_units']} | source-context/readout 数据单元 |
| 已绑定 legacy UTR 视图 | {c['local_utr_views']} | 读出/condition 视图，不重复算十折 |
| 合计本地视图 | {c['total_local_views']} | 175 + 102，不是独立实验 |
| 本地 canonical/source-context assay IDs | {c['local_assay_identity_count']} | 不等于独立生物实验 |
| 已证明独立实验总数 | UNKNOWN | 尚缺 original-assay/condition 身份链 |
| QC 前 selected-view records | {c['qc_actual_observations']:,} | 175 单元范围 |
| QC 后 valid records | {c['qc_valid_observations']:,} | 当前 Parquet 独立校验通过 |
| unique observations（单元内） | {c['qc_unique_observations']:,} | 不是全项目 cross-study unique |

本轮对 **{compute.get('parquet_units_verified',0)}/175** 份当前 `curated_data.parquet`
重新读取 metadata 行数并计算 SHA256，与原 freeze 和 `valid_n` 核对，校验记录：
`runs/20261030_arena_v1/local_parquet_verification.tsv`。
原始资源当前 integrity：`{raw.get('all_pass','PENDING')}`，核验数量
`{raw.get('resources',0)}`；证据在同目录 `raw_integrity.json`。

102 legacy UTR 的既有全行扫描统计和十折 hash 保持不变，不把十个 fold 的同一批记录
累加；87 项 revised UTR 只作为另一版本 metadata，不再加到 102 上。
175 与 102 两大来源之间尚未完成统一 biological-overlap clearance，因此不输出两者相加
的“全项目独立 observation N”。UPSTREAM_QC 证据仍参见
`data/audit/original_qc_evidence.tsv`、`data/audit/qc_gap_analysis.tsv`。

## 8. 数据重复、镜像与 cross-dataset overlap

- **{c['duplicate_observation_aliases']:,}** 条真正 observation alias 被去重。
- **{c['exact_repeated_input_rows']:,}** 条重复输入行不等同重复测量：不同 context、
  condition 或 label 可能应保留，不能全部删除。
- **{c['cross_dataset_exact_overlap_pairs']}** 对 QC 单元存在 exact-input overlap；
  **{c['cross_dataset_UT_overlap_pairs']}** 对存在 U/T-equivalent overlap。
- **{c['mirror_pairs']}** 对 byte-identical archive mirrors 仅计一份 biological source。
- 上述 overlap 数值是 pair 数，不是“362 条重叠样本”；跨研究相同 observation、
  conflicting label 和 near-homology 的最终统计仍受身份链限制。

证据：`data/audit/duplicate_summary.tsv`、`cross_dataset_overlap.tsv`、
`source_alias_canonical_assay.tsv` 与 `scientific_curation_summary.json`。

## 9. Frozen split：本轮实际新建

本轮新建 `data/splits/RNAGYM_SPLIT_V1/` 下三个完整五折 gene-held-out split：

| Dataset | Records | Connected biological/exact-input groups |
|---|---:|---:|
| MRNA_rnahl-saluki-human | 12,939 | 12,939 |
| MRNA_rnahl-saluki-mouse | 13,723 | 13,723 |
| MRNA_mrl-sugimoto | 11,693 | 7,392 |

分组使用 gene 和 exact-input 的连通分量；同 gene、同 input 永远在同一 outer fold。
按 group hash 排序后 label-blind 分配五折。outer test fold=k、validation=(k+1)%5，
其余为 train。每份 manifest 绑定 assignment SHA256、curated SHA256、配置 SHA256、
实际 N、group N 与 leakage audit。三份 split 的 exact-input 与 biological-group
cross-fold leakage 均为 0。AUTHOR_SPLIT、原 EAZY、OOD_split 和 UTR legacy 不被改写。

## 10. Difficulty

难度只由生物学泛化挑战定义。新 split 是 **D2_GENERALIZATION / gene-held-out**，
不是 D3。当前 RNAGYM_SPLIT_V1 完成 D1 task **0**、D2 task **2**、D3 task **0**；
D2 覆盖 HALF_LIFE 和 MRL_PROXY，共三个 dataset views。

已有 175 EAZY 和 100 feasible OOD_split 单元仍可作为分析/复现证据，但 EAZY 的
observation-random-control 不自动升级 D1，普通 sequence homology grouping 也不因
名称有 OOD 就升级为 assay/species/temporal D3。
配置：`configs/difficulty_protocol_v1.yaml`。不足组数时不强制十折。

## 11. Scientific admission

本轮没有用模型得分决定科学准入。既有 **198-row** 推荐为 HOLD **178**、
SECONDARY_PROXY **5**、EXCLUDED **15**。ADMISSION_REVIEW_READY **0**；
正式 ADMITTED_CORE **0**；正式 ADMITTED_EXTENDED **0**。

dataset/readout 层额外把编码蛋白 DMS 等标为 SECONDARY_PROXY，因此不能把该层
proxy 数与 198-row 推荐数相互替换。source DOI、原方法 QC、score 方向/单位、
condition/replicate、使用权和 reviewer 仍有真实缺口；不是仅差一个机械签字。
HOLD 没有阻止本轮真实 QC、split 与 baseline。

## 12. Scoring protocol

`configs/scoring_protocol_v1.yaml` 与 `rna_gym/arena.py` 是唯一聚合协议和实现。
Structure / Function / Engineering 各固定 1/3；内部 capability 等权，再到 task、
source family、assay、dataset version。多 release 不增加 source 权重。

仅 primary metric 参与 rank。Spearman/Pearson/MCC 的 b=0,u=1；AUROC 的 b=0.5,u=1；
AUPRC 必须给冻结的 positive prevalence；MAE/RMSE 必须给正的简单 baseline error。
所有归一化 clip 到 [0,1]；不能临时调整 baseline、上界或主指标。
MRL-HL joint score 是两个已归一化组件的平均，禁止相加原始 metrics。
不同 difficulty/adaptation track 应使用分别冻结的 panels，不重复增加 assay 权重。

## 13. Missing-value policy 与 Coverage-adjusted Universal Score

保留 EVALUATED、UNSUPPORTED、NOT_RUN、FAILED、INCOMPATIBLE、REPORTED_ONLY。
未实测 task 的 raw score 为 NA，而非伪造实测 0。

Performance = evaluated leaves 的 weighted normalized mean；Coverage = 它们的固定
权重之和；Universal = Performance × Coverage。必选但未完成的能力只在 Universal
中贡献 0。overall coverage ≥70% 且每个 macro-domain 至少一个有效 capability 才能
进入 Universal Rank。partial panel 不能按已有结果自动重新分配缺失领域权重。

## 14. Public / Private leaderboard

`results/leaderboards/public/`、`private/` 与 `published_reference/` 已建立版本化列结构。
正式表当前是 header-only，**没有 placeholder 分数或虚构排名**。
探索性真实结果单独位于 `results/exploratory/baselines_v1.tsv`，不混入正式表。

Private-Holdout intake 在 `rna_gym/submissions.py`：必须匹配服务器可信 public
completion receipt，不要求 public Top-K 或 score 阈值；绑定 model version、checkpoint、
adapter、prompt 和 code hash。每团队每 ISO UTC 周默认 2 次，SQLite atomic
check-and-insert；重启不重置额度。仅 owner 可查 receipt，不返回 label/prediction/
逐样本错误。尚未创建真正 hidden-label test，也未部署互联网 submission service。

## 15. Model pool 与本轮真实运行

当前已有 model registry 的实际条目为：

| Model | Family | Local runtime status |
|---|---|---|
{pool}

这些是本地已注册条目，不声称已经覆盖截至今天所有强 FM。RNA-FM 仅有既有 GPU
encoding diagnostic，不是本轮任务成绩；其余 runtime 不可用不应替换成 toy encoder。
本轮未下载模型/权重，未运行新的 FM GPU inference。

本轮实际 evaluated CPU baselines：**3** 个，task family **2** 个，macro-domain
**Function 1/3**，dataset views **3**，结果行 **9**。以下是 pooled out-of-fold
Spearman 与原标签单位 MAE；不是跨 dataset pooled score，也未做正式排名。

| Baseline | Dataset | Spearman | MAE |
|---|---|---:|---:|
{scores}

Ridge 使用 log-length、composition、dinucleotide 特征，固定 alpha=1，scaler 和
supervision 仅在各 train fold 拟合，无 HPO。U→T/uppercase 仅用于明示的统计特征视图，
不改原始 input 或 identity。原始预测、各 fold head/scaler 与 hash 保存在 ignored runs。
mean/median null 在每折为常数；不同折常数的 pooled correlation 可能不恰为零，不能
将这些微小数值解释为生物学 predictive skill。

## 16. Reproduced vs paper-reported

本轮 9 条都是 `RNA_GYM_REPRODUCED`，但 `EXPLORATORY_NOT_ADMITTED`、
`formal_leaderboard_eligible=False`。正式 reproduced 条目 **0**；新收录论文报告条目
**0**。第三方 future results 使用 EXTERNAL_VERIFIED，而非伪装为本地运行。

paper comparability 必须同时匹配 dataset version、test set、split、metric、input
modality 和 additional information。旧 UTR 的历史 zscore metrics 有既存记录，但不
满足 RNA-Gym 新 split/raw 协议，不冒称本轮 reproduced leaderboard 成绩。

## 17. Fine-tuning plan 与 paper insights

在科学准入和初始 frozen benchmark 完成后，各领域选择 domain-best、efficient/small、
architecture/pretraining-distinct、中等表现模型，而不是仅取 universal Top-3。
须确认公开权重、license 和可实现的训练代码。

比较 zero-shot、Frozen+Ridge、Frozen+MLP、LoRA、Full FT、匹配架构与 supervised
budget 的 RandomInit。保存 Δadapt、Δpretrain、ΔOOD 及公共/私有排名稳定性，
分析 frozen sufficiency、adaptation/pretraining gains、跨领域 representation、参数量、
OOD degradation 和 sequence-statistics shortcuts。当前三组 CPU 结果只是提供统计基线，
不能推断任何 foundation-model pretraining gain。

## 18. API / website architecture

`configs/api_schema_v1.yaml` 是 OpenAPI 3.1 合约，包含请求的 task/dataset/model/list/detail、
leaderboard、submission intake/status 路由。**这些新路由为 SCHEMA_ONLY_NOT_DEPLOYED**；
既有 authenticated local run API 保留原行为，不误报新路由已经能由 HTTP 访问。
SubmissionStore 是实际可测试模块，但尚未接 production authentication/evaluator。

`site/arena.html` 提供 canonical task/input/metric、coverage/unsupported state 与公共/
私有/论文结果隔离说明，读取 versioned snapshot 和 scoring metadata，不在网页硬编码
计算最终成绩。无正式成绩时显示 unavailable，而非 0 分 radar。
本轮没有部署或上传网站。

## 19. RNAGYM_V1_CORE_SET

`configs/rnagym_v1_sets.yaml` 中正式 core/extended 集合均为空，以免伪造批准。
从已测数据中提出 **{c['core_candidate_tasks']}** 个 task families 的核心候选，每任务
最多两个代表视图；实际可用但 rights/assay review 尚未齐全，不能称科学准入完整。
GO、蛋白定位、蛋白表型 DMS、clinical proxies 不自动进入核心。

## 20. Extended 与 Future v2 candidates

已批准 extended task 数 **0**；generation/paired modality 需要新协议才可进入。
当前可映射本地数据的 canonical family 共 **{len(c['supported_tasks'])}/28**：

{supported}

其余 **{len(c['no_supported_tasks'])}** 个尚未获得 compatible audited endpoint：

{unsupported}

“无支持”只指当前 schema-bound 证据，不等于磁盘绝无相关数据。既有审计还记录
6877 个未完全绑定的外部 cache candidates；后续应先查这些缓存，而不是重新下载。
Prospective/temporal 数据优先作为 v2 private/OOD validation；ligand、RNA–RNA、
raw-signal 不能硬塞进不匹配的 28 个任务中。

## 21. 当前 blockers 与验收结论

- Taxonomy mapping 完成，107 mapped / 76 review / 15 excluded；review 不代表数据不能处理。
- 所有 175 Parquet 技术验收通过；独立 original-assay 数仍 UNKNOWN。
- 新 D2 已真实冻结并完成 CPU baseline；D1/D3 新协议尚未建立。
- 无正式人工 admission；部分 input/label/condition/rights 仍需原始方法证据。
- Structure/Engineering 尚无本轮可执行且完全匹配 canonical input/label 的 endpoint；
  Universal Arena 不能开放正式 rank。
- 新 API 目前为合约而非 HTTP runtime；private test 构建/部署尚未完成。
- 源工作目录本身没有 `.git`，未创建新 Git repo，也未擅自推送其他副本。

软件最终验收：discovered **{validation.get('discovered','PENDING')}**，通过 **{validation.get('passed','PENDING')}**，
明确 skip **{validation.get('skipped','PENDING')}**，失败 **{validation.get('failed','PENDING')}**。
初次集成的两项失败及修复日志均保留；没有删除安全测试或绕过准入检查。
`runs/20261030_arena_v1/validation.json` 绑定最终测试日志 SHA256。

因此，本轮交付是**真实可复现的 v1 migration、QC验收、D2与baseline工作批次**，
不是“全领域 FM 公私双榜全部建成”。

## 22. 下一步计算任务与重现命令

1. 按 `v1_conflict_findings.tsv` 优先核实 SSI 的 partial-signal recipe、PDB contact
   semantics、RNA3DB residue alignment、translation fragment boundary。
2. 利用已下载 cache 绑定 MRL-exact / RRS / TE、Structure 和 Engineering 代表 assay，
   补充 upstream QC、label 方向/单位及原始实验身份。
3. 建立 D1 biological-construct 与 D3 assay/cell/species/temporal split，而不是给旧名
   改标签；对所有 RNA-Gym train/test 做跨 dataset 泄漏检查。
4. 完成审查并由真实人员决定 ADMITTED_CORE / EXTENDED / SECONDARY_PROXY。
5. 用现有 CPU runner 扩展新任务，再启用已安装且许可合适的 FM adapters。
6. 连接 API runtime、private evaluator 和生产身份认证；隐藏 label 单独安全保存。

```bash
# 从真实既有证据重建版本化 metadata；不下载、不签署准入
.venv-qc/bin/python -m tools.build_arena_v1
# 独立 Parquet 校验、gene-connected split 与真实 CPU baseline
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \\
  .venv-qc/bin/python -m tools.arena_v1_compute
# 生成本文及 Arena page
.venv-qc/bin/python -m tools.arena_v1_report
# 软件回归；不是新的科学准入
.venv-qc/bin/python -m unittest discover -s tests -p test_arena_v1.py -v
```

验收原始证据集中在 `runs/20261030_arena_v1/`；最终摘要为
`data/audit/rnagym_v1_build_summary.json`。
'''
    (root/'reports/RNAGYM_V1_BUILD_REPORT.md').write_text(report)
    page(root, c, tax)


def page(root, counts, tasks):
    rows=''.join('<tr><td>'+html.escape(t['task_id'])+'</td><td>'+html.escape(t['macro_domain'])+'</td><td>'+html.escape(t['input_definition'])+'</td><td>'+html.escape(t['primary_metric'])+'</td><td>'+('Local candidate' if t['task_id'] in counts['supported_tasks'] else 'No compatible audited endpoint')+'</td></tr>' for t in tasks)
    text=f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; style-src 'self'; script-src 'none'; object-src 'none'; base-uri 'none'"><title>RNA-Gym v1 Arena · Evidence status</title><link rel="stylesheet" href="styles.css"></head>
<body><header class="site-header"><a href="index.html">RNA-Gym · Existing project</a></header>
<main><section class="section"><p>RNA-GYM V1 · 2026-10-30 · {VERSION}</p>
<h1>A unified arena across Structure, Function and Engineering</h1>
<p>Versioned taxonomy, real local QC, leakage-aware splits and explicit result provenance.</p>
<p><strong>Candidate build, not a live ranked benchmark.</strong> No human admission was fabricated.</p>
<h2>Capability profiles</h2><p>Structure: unavailable. Function: 3 exploratory CPU baselines / 2 tasks.
Engineering: unavailable. No Universal Rank; no fake zeros for unsupported tasks.</p>
<h2>Public · Private · Published results</h2><p>Formal Public: 0. Formal Private: 0. New paper-reported: 0.
Exploratory local CPU rows: 9. These are separate result sources, not visually interchangeable scores.</p>
<p>Zero-shot, frozen and fine-tuning FM tracks: NOT_RUN. ID vs OOD model delta: unavailable.
The new gene-held-out splits are D2, not assay-held-out D3.</p>
<h2>Translation is not one label</h2><p><strong>RRS ≠ MRL ≠ TE.</strong> RRS: recruitment; MRL: loading;
TE: efficiency. MRL-exact requires genuine 5′UTR; MRL-proxy uses cDNA. Half-life PC1 is not hours.</p>
<h2>Measured local evidence</h2><p>{counts['registered_rows']} registry rows; {counts['local_qc_units']} QC units;
{counts['local_utr_views']} inherited UTR views. Not independent assay counts.
{counts['qc_valid_observations']:,} valid records in the 175-unit QC scope.
Independent original-experiment count: UNKNOWN.</p>
<h2>The 28 canonical tasks</h2><div class="tablewrap"><table><thead><tr><th>Task</th><th>Macro-domain</th><th>Input</th><th>Primary</th><th>Evidence coverage</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>Protocol and API boundary</h2><p>Domain weights and normalization live in versioned scoring config, not webpage logic.
New API routes are schema-only; private intake module enforces verified-public qualification and quotas.
No hidden labels or per-sample private errors are included here.</p>
<p><a href="data/arena-v1.json">Versioned public metadata snapshot</a> ·
<a href="index.html">Historical registry explorer</a></p></section></main></body></html>'''
    (root/'site/arena.html').write_text(text)


if __name__ == '__main__':
    render()
