# 上游数据划分与科学复用准入审计 — 2026-10-28

## 本轮授权与两种准入

用户明确允许：**已有数据划分且使用流程清楚的上游数据集/benchmark，可通过科学
复用准入**。本轮据此冻结 `USER_SPLIT_WORKFLOW_REUSE_20261028`，不是自动伪造旧
human-review gate 所需的逐 assay 签署。

| 范围 | 本轮结论 | 不代表什么 |
|---|---|---|
| `UPSTREAM_PROTOCOL_REUSE` | 206 个版本化上游划分协议通过；171 个保留 | 不是 206 个独立 assay、正式任务或实际模型分数。 |
| `ADMITTED_CORE` / 原正式 gate | 本轮没有授予；仍为 0 | 不把划分存在等同于完整来源独立性、许可、条件身份和正式结果审核。 |

两个范围使用不同字段：`admitted_upstream_reuse` 与原 `admitted` 不混用。
原 198 个任务 ID、正式五种子、原始标签、原始 split 和 `tools/admission_gate.py`
均未改写。公开代码不附带原始数据、权重、私有定位表或人工审批记录。

## 实际检查结果

重新完整 SHA256 核验 **50 个本地文件版本，6,593,181,246 bytes**，全部匹配。
实际解析归档内的分区内容；复用 hash-bound 的全文件 QC 时保留其范围说明。

| 来源包 | 观察到的协议变体 | 复用准入通过 | 保留 | 已通过协议的 held-out 角色 |
|---|---:|---:|---:|---|
| RNAGYM_DMS | 62 | 56 | 6 | 0 test / 56 dev |
| EUKAUTR | 310 | 147 | 163 | 86 test / 61 dev |
| MIR_BENCH | 2 | 2 | 0 | 2 test / 0 dev |
| RNA3DB | 2 | 1 | 1 | 1 test / 0 dev |
| RNAGYM_RMDB | 1 | 0 | 1 | 0 test / 0 dev |

**377 是版本化划分协议数，不是独立实验数。** 同一来源的 fold、随机/相似度策略、
长度设置和 endpoint 变体不会因此获得独立 assay 权重；来源簇映射仍需另审。
所有候选都保留，未为完成任务删掉失败分母。

### RNAGym DMS

本地 `fitness_CV_splits.zip` 中确有 **62 组 train/validation 协议**。
56 组满足当前复用条件；4 组存在声明键的跨分区共享，2 组有无效输入/标签行，保留。
文件内角色是 **validation，不是 test**。通过项明确标为
`DEVELOPMENT_HOLDOUT_ONLY_NOT_TEST`，不称隐藏测试、正式主榜或无测试调参。
`DMS_score`、`sequence`、原始 mutant/成员身份和数据字母均保留。

### EukaUTR

实际读取归档中带显式 train/validation/test token 的 CSV，核对成员 hash、输入/目标
列、非空分区和 exact raw sequence 共享。147 组通过；其余保留原因包括输入或目标列
不明、分区不完整、跨分区共享，以及 **33 组编辑器 `.ipynb_checkpoints` 候选**。
编辑器备份不被当成作者正式协议。通过项中 86 组有 test，61 组只有 dev heldout。

### miRBench

Hejret2023：train **8,140** / test **1,018**。
Manakov2022：train **2,495,535** / test **324,171** / leftout **20,054**。
复用已完成的全文件 binary/pair QC 和全 21 对文件比较，当前原始文件 SHA256 与
QC hash 都匹配。两个来源内部的 role-ordered exact RNA pair 共享为 0。

跨来源 pooled/transfer 仍有输入共享；不得自动混池训练或当独立验证。Klimentova
只有独立 test 文件及镜像版本，未补造训练分区，也不把镜像计为第二个实验。

### RNA3DB

两版归档都实际包含 `split.json`。2026-01-05 版本有匹配的本地 coordinate release，
通过上游结构协议复用：train **1,539** chain entries / valid **0** / test **660**。
核对键为 **发布的 chain ID 与 component ID**，不是新做的 sequence-homology 审查。
空 valid 原样保留，不自动生成。2025 版本缺匹配 coordinate release，继续保留。
3D 对应关系、mask、assembly 和结构 adapter 是模型执行前的独立要求。

### RMDB 与 mRNA 文件

RMDB_s40 的 train/test Parquet 确实存在，分别为 **198,411 / 792,526** 行；
实际重查 sequence 列有 **3** 个跨分区相同序列。
条件身份尚不能解释这些重复，所以本轮保留；不删除重复，也不压成 pooled 标量目标。

mRNA Parquet 的实测目标列存在，但单个文件大多没有固定 benchmark role 列。
T0021 的作者规则重建与单独 exploratory 分组证据仍保留：不能把“有生成规则”写成
“文件附带了官方固定 split”，也不把旧分组重建覆盖为 official。
其余 CT/结构/复合 ZIP 里仅有命名线索、尚无明确 reader/recipe 的部分继续保留。
逐文件状态在冻结的公开 registry 中可直接查询。

## 原生 Python 查询

```python
from rna_gym import DatasetHub

hub = DatasetHub()
accepted = hub.protocols(admitted=True)
dms_dev = hub.protocols(package="RNAGYM_DMS", admitted=True)
print(len(accepted))                    # 206 at this frozen snapshot
print(dms_dev[0]["evaluation_partition"])  # validation, not test
print(accepted[0]["raw_bytes_available_now"])
```

新机器可查 metadata，但 `raw_bytes_available_now=False` 时不会自动下载原始数据。
每项保留实际 archive member、角色、行数、SHA256、输入/目标列、作者工作流 commit
与使用 recipe。它们可用于下一步建立精确 execution binding，不自动替换旧 T/X 任务。

`RNABenchmark.evaluate` 还需要 exact task/endpoint/input/split 绑定、适合该模态的
模型 adapter、预算和原正式 gate；本轮没有新增训练、FM forward 或虚构分数。
**R03 的持久共享 native 数量/时间/磁盘预算仍未完成，禁止据此启动无界全矩阵。**

## 可复核与安全

```bash
python tools/audit_dataset_splits.py --verify data/registries/upstream_split_audit.json
python -m unittest discover -s tests -p test_split_reuse_admission.py -v
python -m unittest discover -s tests -p test_ranking_evidence_integrity.py -v
python -m unittest discover -s tests -p test_statistics_eligibility.py -v
```

- 分区检查依据真实现有数据；合成数据只用于软件反例，不替换真实划分证据。
- 已修复 R01/R02：必需产物、native result 原件、模型/协议/初始化和标签账一致性。
- 已修复 R04 的区间状态：无效重采样 >5% 标不稳定；<10 个声明组不出 `formal_ci`。
  `ci` 保留为旧 conditional 别名；组 ID 数本身不是科学独立性的证明。
- 不产生许可、人工签署、权重或数据下载授权；不将声明通过变成正式结果。

## 固定作者工作流证据

以下仅用于源协议/布局说明；当前下载版本以文件 SHA256 为准，不宣称等于最新发布。

- [EUKAUTR / meilanglang/EukaUTR / `2440b7a1875a`](https://github.com/meilanglang/EukaUTR/blob/2440b7a1875aa97d18a91d221ff6351871b7e92c/README.md)，
  README SHA256 `24250384285fba54a69284d48c72afbeaabe7431fde7ba76d35816f39912dbc5`。
- [MIR_BENCH / katarinagresova/miRBench / `6a9c9cca8891`](https://github.com/katarinagresova/miRBench/blob/6a9c9cca8891fc0dea8deab22030fcb6256c2412/README.md)，
  README SHA256 `1375e0164d780af8126a39ae50367d6330edda8a573c0f1a68990695ff0430ca`。
- [RNAGYM / MarksLab-DasLab/RNAGym / `2828cf99316d`](https://github.com/MarksLab-DasLab/RNAGym/blob/2828cf99316d75daaa8d832a2573cbb25bbd35fe/README.md)，
  README SHA256 `2fb1e46b3144e0647ca599a9051f1763a2db69a8179421afda4a0b695e74405b`。
- [RNA3DB / marcellszi/rna3db / `cb62d9d4b2c6`](https://github.com/marcellszi/rna3db/blob/cb62d9d4b2c63261c810d224a2ff37bec3cd528f/README.md)，
  README SHA256 `95550a0975542899219d0b2e8850735e62ebf7aac117c48609cd3c4696f14dc7`。

完整冻结结论：[upstream_split_audit.json](../data/registries/upstream_split_audit.json)。
政策：[upstream_reuse_policy.json](../configs/upstream_reuse_policy.json)。
