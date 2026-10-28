# 已整理数据的任务类型与标签审计

## 口径修正

初始登记表的 198 行“已下载/标签实测核验”均为 NO，是历史快照，不能代表
后续下载和 QC 的实际状态。HOLD 也不等于没有数据或没有标签。本目录将以下状态分开：
原始文件存在、目标值被观察/扫描、实验/注释来源、序列与 split 兼容、科学准入、排名资格。

当前本地有 **50 个物理文件版本、16 个来源包组**；
**26 个文件/归档有 hash-bound 目标值或参考结构证据**。
41 个旧任务行可关联到本地来源包，其中 40 行关联来源存在目标证据；
这些不是 40 个独立 assay。正式 admitted 仍为 0。

## 198 行原始任务类型

| 原始类别 | 登记行数 | 不能混用的目标/评测形状 |
|---|---:|---|
| Nanopore 原始信号 | 4 | signal/逐 read/修饰标签，不是纯序列基准 |
| RNA 2D | 13 | 配对边/矩阵；不是 pooled 标量回归 |
| RNA 3D | 16 | 坐标/距离/接触；需要结构 mask 和对应指标 |
| RNA 逆折叠与生成设计 | 34 | 条件生成/设计约束，不可全部塞入 MLP |
| RNA–RNA 相互作用 | 6 | 双 RNA 有序输入及真实 pair 标签 |
| RNA–小分子结合 | 15 | 配体条件输入；binding/affinity/screening 分开 |
| RNA–蛋白结合 | 31 | 位点标签与亲和力回归分开 |
| 二/多/多标签分类 | 14 | 区分 binary/multiclass/multihot 与注释代理 |
| 排除/仅方法学 | 23 | 原分类 23 行，不等于最终排除 23 行 |
| 标量回归 | 23 | MRL、TE、half-life 等 readout/单位分开 |
| 突变效应与排序 | 9 | 逐原始 assay、WT/变体映射与方向 |
| 逐核苷酸回归 | 10 | 逐位置 reactivity，必须保留位置 mask |

最终登记处置仍是 189 HOLD、9 EXCLUDED_NON_ASSAY。不能根据粗类别直接删掉 23 行。

## 已有标签的具体证据

| 数据/文件 | 已核验文件行数 | 标签形状/来源 | 当前边界 |
|---|---:|---|---|
| go_dna_dataset_mf.parquet | 5737 | multihot {'target': {'20': 5737}}；GO molecular function annotation | 原始单位、身份、split/权利仍未全部准入 |
| mirna_preprocessed.parquet | 12865 | 20 个独立 target head；miRNA-specific target heads; keep each head separate | 原始单位、身份、split/权利仍未全部准入 |
| mrl-hl-lbkwk.parquet | 203 | 2 个独立 target head；MRL and half-life are separate readouts; never merge | 原始单位、身份、split/权利仍未全部准入 |
| mrl-sugimoto.parquet | 11693 | 标量/类别 target，见 schema；MRL | 原始单位、身份、split/权利仍未全部准入 |
| prot-loc.parquet | 9769 | multihot {'target': {'12': 9769}}；protein localization annotation | 原始单位、身份、split/权利仍未全部准入 |
| rnahl-saluki-human.parquet | 12939 | 标量/类别 target，见 schema；RNA half-life; units/transformation unresolved | 原始单位、身份、split/权利仍未全部准入 |
| rnahl-saluki-mouse.parquet | 13723 | 标量/类别 target，见 schema；RNA half-life; units/transformation unresolved | 原始单位、身份、split/权利仍未全部准入 |
| utr-variants-bohn-utr5.parquet | 128 | 标量/类别 target，见 schema；UTR variant annotation; label meaning pending | 原始单位、身份、split/权利仍未全部准入 |
| utr-variants-bohn-utr3.parquet | 107 | 标量/类别 target，见 schema；UTR variant annotation; label meaning pending | 原始单位、身份、split/权利仍未全部准入 |
| vep-traitgym-mendelian.parquet | 2616 | 标量/类别 target，见 schema；variant effect annotation; label meaning pending | 原始单位、身份、split/权利仍未全部准入 |
| vep-traitgym-complex.parquet | 1707 | 标量/类别 target，见 schema；variant effect annotation; label meaning pending | 原始单位、身份、split/权利仍未全部准入 |

另有以下来源，不能把格式或计数当作完整科学准入：

- **miRBench**：7 个配对文件版本，含 `gene`、`noncodingRNA`、`label`，
  完成完整文件 binary/schema/exact-pair QC。Hejret train/test 为 8,140/1,018 行；
  Klimentova 两个版本各 954 行且样本重合，不能计为两个独立实验。
  Manakov train/test/leftout 为 2,495,535/324,171/20,054 行。
  负样本构建、原 assay 和更广 group/homology 泄漏仍需审查。
- **RNAGym processed DMS**：归档有 70 个带 `DMS_score` 的 member；已有 RNA 范围
  清单是 33 个文件，另外 37 个 coding/proxy 不直接混入 RNA 主面板。33 个文件的行数
  不是独立观测/实验数。`Pitt_2019` 的旧 exact QC 为 186 行、162 个不同序列，
  重复观察未自动删除。变体/WT、条件、单位和方向必须逐 assay 绑定。
- **RMDB**：train/test Parquet 有逐位置目标的全文件 schema 扫描证据；不是标量
  fitness。`cluster_40` 是映射元数据，不算监督标签。
- **T0021 原源 NPZ**：安全读取了 11,693 个 `y` 及 gene metadata，和 Parquet 的
  target 在 float32 后逐行相等；这不是第二个独立 assay。`X` 为
  `[11693,12288,6]` 的 primitive array，不是无条件的短 5′UTR；没有为预览展开 X。
- **RNA3DB**：已有 15,441 coordinate 文件和 254,196,469 atom rows 的解析/身份
  QC；atom rows 不是样本数。三维坐标可以是参考目标，但不能直接冒充已冻结的
  secondary-pair 标签，assembly/mapping/mask 仍有科学边界。
- **Wang / 其它归档**：按 member 记录显式 target 列。归档内存在目标不等于已建立
  旧任务到原始 assay 的一对一映射；pickle/未解析结构保持未核验，不执行反序列化。
- **monomer/multimer Parquet**：旧审计明确是模型结果表，不能当 ground-truth 标签。

## 数据整合时必须保留的区别

- GO、protein localization、部分 VEP/miRNA 数据的 target 是注释或代理，不自动声称
  原始 RNA 功能实验。标签“存在”和标签“生物学语义已准入”是两件事。
- T0022 的 `target_ribosome_load` 与 `target_in_cell_half_life` 不合并为一个 label。
- mRNA Parquet 大量序列为 DNA 存储字母 A/C/G/T、全长可能超过 RNA-FM 的 1022 nt
  范围。SDK 不自动 T→U、不截断；需要单独版本化的输入处理和上下文策略。
- 大部分 Parquet 不内置官方 split。不能据此断言上游没有 split；T0021 的作者协议和
  homology 审计已有另外的证据。任何重建 split 均单独命名/hash，不能覆盖作者协议。
- 同序列不同条件/重复观测不删除；文件版本、镜像、来源包、task row 和 assay 分开。
- 50 文件不是“47 个来源包均完成”，更不是 50 个独立 benchmark。

## 目录与证据

公开的 `data/registries/dataset_catalog.json` 是旧 registry、provenance 和既有 QC
的派生 metadata，不覆盖旧 ID/准入状态，不含逐样本序列或测量值。文件 checksum 在
实际 `DatasetHub.preview` 使用时重新核验；已有全文件 QC 证据被复用而不是全部重扫。

原始路径另存 ignored 本地 manifest；新机器只有代码/目录时，SDK 正确报告当前无本地
字节，不拿发布者的历史 snapshot 冒充当前可用数据。原始数据和权重不放进 Git。

本轮还实际通过原生 SDK 读取了 MRL、双 endpoint half-life/MRL、paired binary、
NPZ y 和 DMS 的小范围真实样本。输出只保存校验摘要，不导出原始观察。
