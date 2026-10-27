# 原生 Python SDK：RNAHub、DatasetHub、RNABenchmark 与排名

## 这才是主 API

接口直接在本地 Python 进程中加载模型、读数据和执行协议，**不是 OpenAI API，也不需要
HTTP 服务、网络请求或 API key**。先前 HTTP 控制台降为可选传输层，不是 SDK 主入口。

```python
from rna_gym import RNAHub, DatasetHub, RNABenchmark

# Supply this reviewed local manifest yourself; it is not shipped or downloaded.
model = RNAHub.load(
    "RNA-FM", manifest="runs/local/rnafm_manifest.json", device="cuda:0",
)
embeddings = model.encode(
    sequences=["AUGCUACGUACG", "GGCAUUACGU"],
    layer="last",
    pooling="masked_mean",
)

runner = RNABenchmark(
    dataset="utr_translation",
    protocol="frozen_mlp",
    split="official",
    seed=42,
)
results = runner.evaluate(model)
print(results.as_dict())
```

该模型调用已使用真实本地权重/GPU 执行。`utr_translation` 是明确的旧任务集合
`T0009/T0017`，不被偷偷缩成一个最容易跑的 assay。当前返回逐任务科学 BLOCKED，
不是虚构成绩。已有真实标签证据的单任务可用 `dataset="T0021"` 或 `"mrl_sugimoto"`。

## 环境和本地资产

### 公开克隆不是已经配置好的模型节点

公开仓库只有代码和 registry，不含权重、上游模型源码、原始观察或本机 pinned manifest。
从 checkout 可直接 `DatasetHub()` / `RNAHub.list()` 查看 metadata，不需 GPU、HTTP 或 key。
只有已有的已审核模型节点才能使用默认 manifest；新机器请显式传 `manifest=`。
相对 manifest 路径以 `root=` / `RNA_GYM_ROOT` / checkout 为基准，不随工作目录漂移；
绝对路径保持不变。缺失时明确报 `PINNED_LOCAL_MODEL_MANIFEST_MISSING_NO_DOWNLOAD`。

本地 manifest 的关键字段由 `tools/rnafm_adapter.py` 校验：

| 字段 | 要求 |
|---|---|
| `model_id` / `dtype` | `RNA-FM` / `float32` |
| `source_root` / `source_tree_sha256` | 已审阅的本地 `fm` 源码根与源码树 hash |
| `checkpoint` / `checkpoint_sha256` | 具体本地 checkpoint 与字节 SHA256 |
| `model_card` / `model_card_sha256` | 实际模型卡与字节 SHA256，保留上游许可声明 |
| `rights_scope` | 必须来自真实本地研究授权；不是自动签署许可或再分发授权 |

manifest 内的资产路径应使用本机绝对路径；不要复制发布者的私有路径、补猜 hash 或
许可。具体 checkpoint、源码、模型卡、访问权利与 CUDA 环境全部匹配后才可加载。
所有 FM forward 必须在 GPU；纯软件契约测试不代表 GPU 或真实 assay 证据。

### 已验证节点与安装

默认读取本节点既有 pinned model manifest；所有 FM forward 强制 CUDA，CPU 不作
fallback。请选择已验证的 `mrna-core-cu124` 环境。当前通用 QC venv 的 Torch 2.13
对本节点驱动出现 CUDA 兼容警告；它可做 CPU 软件测试，不是本轮模型推理环境。
本轮真实 FM 使用既有 Torch 2.5.1/CUDA 12.4 环境，没有安装/下载或修改驱动。

源码目录可直接 import。环境已具备 `setuptools>=61` 和 `wheel` 时，离线安装可使用：

```bash
python -m pip install --no-deps --no-build-isolation -e .
```

安装不拉取 Torch、权重或数据。非 editable/wheel 使用时，传 `root=` 或设置
`RNA_GYM_ROOT` 指向实际 checkout；模型/原始数据仍需当地提供并 hash pin。
包只含代码，不能伪装成已经随 Git 分发了私有数据或权重。

## 数据目录：存在、标签和准入分别查询

```python
hub = DatasetHub()
all_tasks = hub.list()                       # 保留全部 198 个旧 ID
local_labelled = hub.list(with_local_labels=True)
print(hub.get("T0021").describe())
preview = hub.get("T0021").preview(rows=2)
print(preview["scope"])                      # inspection，不等于 admission
```

- 目录读取 `data/registries/dataset_catalog.json`，由已有 registry/QC/provenance 派生。
- 当前本机原始路径存放 ignored 的 private manifest；公开目录不含逐样本数据。
- `preview` 重新核验原始字节 SHA256，最多 8 行，不下载，不改 T/U、大小写或 split。
- Parquet、配对 TSV/CSV、明确选择的 archive CSV member 有 reader。NPZ 仅显式读取
  小 primitive `y`，不为预览展开大 X 或执行 pickle。
- 多资产/归档 member 要明确选择，避免从一个 umbrella task 猜一个 assay。
- 原始镜像、同序列不同条件、重复观察均保留，不自动序列去重。
- `preview_asset` 可查看尚未映射旧任务的本地文件，不创造虚假的 assay/独立来源。

参见 [任务类型与标签审计](DATASET_TASK_LABEL_AUDIT.md)。旧 NO 标志和科学 HOLD 不能
再用来声称“没有标签”。公开目录历史 snapshot 与当前机器是否有字节也分别记录。

## 模型接口

`RNAHub.list()` 返回六个已有模型登记及实现状态；当前真实验证的 native backend
只有 RNA-FM。其它模型未接入时明确抛 `ModelUnavailableError`，不换成 RNA-FM 或 mock。

`encode` 支持预先指定的 `layer="last"`；`pooling="masked_mean"` 返回 `[N,640]`
数组，`pooling="none"` 返回逐序列 `[L,640]` nucleotide 数组。BOS/EOS/pad 不进入
masked mean。DNA、空序列、超长和未声明 pooling/layer 均拒绝，不截断或隐式转换。
表示不是 native fitness、pair graph 或三维预测。

## 协议和真实评测链路

`frozen_mlp` 使用 last-layer masked-mean frozen 特征、train-only scaler/target
z-score，128 隐藏单元、GELU、dropout 0.2、AdamW lr 3e-4 / weight decay 0.01、
100 epochs、batch 64。严格低标签预算不大于 64 时 HPO=0、无 early stopping，fit、
tune、calibration 并集明确计数；test 标签只评分，不选择层、epoch、阈值或超参数。

`frozen_ridge` 用于回归；`frozen_linear` 在二分类使用 fixed-C logistic。
多标签、token、pair、3D、生成和 native variant 需要独立 head/协议；不会将它们
静默压成 MLP 标量问题。超过 64 的预算要求后续 grouped inner-CV，不偷偷降预算。

真实任务通过原 `admission_gate.py` 与 exact task/input/split/label binding 后才进入
编码与拟合。现有 resolved bindings 暂从本地 `configs/interactive_api.json` 的
`task_bindings` 字段复用；这是读配置，不会连接 HTTP 服务，也不另建平行 registry。
需要明确 `split_id` 和真实 inference groups；不自动创建所谓 official split。

执行时保存同预算 CPU controls、逐 ID 预测、plain-JSON head、signed metrics、
配对 group bootstrap、真实资源和失败文件。回归使用 signed Spearman，分类 AP 为
non-interpolated AP；undefined 不补零。`seed=42` 原样记录，不替换为其它种子。
原正式五种子 `[11,23,47,71,101]` 和两种初始化设计没有因此减少。

当前没有 admitted assay；head 和排名数学的合成契约测试不等于真实数据模型成绩。
可用标签的数据仍需补齐原 assay/单位、使用权利、split/group 审查及真实人审。

## 输出目录与状态语义

`RNABenchmark(output="runs/pilots/mrl", ...)` 将路径解析为 checkout 下的目录；
相对路径不依赖 shell 的 cwd，显式绝对路径也必须在该 checkout 的 `runs/` 内。
`site/`、`data/`、外部路径、`..` 越界和 symlink 越界在执行前拒绝，避免逐样本预测被
误写到公开目录。默认不指定 `output` 时仍使用 ignored `runs/native_sdk_evaluations/`。
`BenchmarkResults.save(path)` 是调用者显式导出摘要的操作，不会自动公开任何文件。

汇总状态不把工程失败冒充科学阻塞：全部执行为 `EXECUTED`；有成功和未完成项为
`PARTIAL`；没有成功且存在失败为 `FAILED`；全部不适用为 `NOT_APPLICABLE`；其余
未执行情况为 `BLOCKED`。逐任务 `runs` 始终保留各自状态和原因，不删除失败分母。

## 两类排名，不是异质任务总分

```python
from rna_gym import RNALeaderboard, RankingPanel

panel = RankingPanel(
    dataset_ids=("T0021",),
    model_ids=("RNA-FM", "RiNALMo"),
    seeds=(42,),
    protocol="frozen_mlp",
    metric="spearman",
    initialization="pretrained",
    label_budget=64,
    split="official",
)
board = RNALeaderboard(scope="exploratory").add(results)
by_dataset = board.by_dataset(panel=panel)
```

当前没有合格分数，返回覆盖/阻塞状态和 `None`，不生成排名数字。

1. **按数据集**：相同 dataset/endpoint、split、input context、protocol、初始化、
   标签预算与预注册种子比较。只完整共同面板才给 rank；不能临时删失败模型或选最好 head。
2. **按能力**：使用 `by_capability`，需要同能力、同主指标的冻结 dataset 面板，以及
   来自审核后 manifest 的 `source_groups` 和唯一 `assay_ids`。先来源簇等权，再簇内
   assay 等权。镜像/子集/同 assay 不变成新增实验，缺项不补零。

能力不混合 Spearman、AP、pair-F1 和几何指标，更没有任意“总能力分”。Spearman
不取绝对值。覆盖率、failed/blocked/N/A/not-run 和分数并列公开。

榜单 loader 会重验预测/配置/数据 hash、原 gate、精确训练标签集合和指标回放。
默认 formal 拒绝 exploratory、synthetic、无审核和不完整种子面板；本轮没有正式
result-review 或 confirmatory score，因此不得声称正式主榜已经建立。

## Git 整合边界

本地发布白名单纳入 SDK、配置、metadata 目录、测试和文档。原始序列/测量、数据包、
checkpoint、私有路径 manifest、逐样本预测和人工审批文件继续留在 ignored 目录。
本地 Git 候选保存代码整合；不替用户 push，不篡改历史快照或原始准入记录。
