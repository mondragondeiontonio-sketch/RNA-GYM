# RNA-FM-HF 受控适配 API

## 范围与评分含义

`AdaptationPilot` 是本地 Python API，不需要 HTTP 服务或 API key。
它调用已有真实 GPU worker，将任务指标、逐样本预测、资源与持久预算收据统一返回。
当前只支持已有 Andreasson 固定小样本 recipe 的 Scratch / LoRA / Full FT 模态，
不是任意数据集或任意训练命令接口，也不替代 `RNABenchmark` 的科学准入。

- `RNA-FM-HF` 是当前本地部署名称；原生 backend/model ID 仍为 `RNA-FM`。
- 别名使用同一 pinned checkpoint/source/tokenizer，不下载、不换模型。
- 输入为原固定 74 nt RNA variants；目标为原始 `kcat`（s⁻¹）。
- 既有 `EAZY_fold_0` 内 label-blind 64/16/32 子集保持不变。
- 标准化只在训练集拟合；本轮 1 epoch、16 steps、无 HPO。
- 同 WT/library 的小型技术实验，不声称 unseen-WT 或完整任务泛化。
- `scientific_admitted=False`、`formal_leaderboard_eligible=False`。

## 检查工作流，不启动 GPU

```python
from rna_gym import AdaptationPilot

pilot = AdaptationPilot(
    mode="lora",
    output="runs/my_next_separately_approved_pilot",
)
print(pilot.inspect())
```

本地未提供 recipe、subset、checkpoint 或经验证 GPU Python 时，接口明确报错；
不会下载或生成替代数据。

## 受控执行

执行前必须已有独立批准、落盘且绑定 recipe/subset SHA256 的 scope。
API 不批准预算、不重置 scope、不自动 retry。以下 scope/UUID 是占位符，
不能直接用来执行：

```python
result = pilot.run(
    scope="<separately-approved-new-scope>",
    gpu_uuid="<idle-allocated-GPU-UUID>",
    seconds=180,
)
print(result.status)
print(result.as_dict()["runs"][0]["metrics"]["test"])
```

守卫检查当前 Slurm job、visible allocation、step allocation、GPU UUID、
进程占用、显存和利用率；只选择一张空闲卡，保留其它正在执行的任务。
真正的模型执行在 supervised child 中进行，并受持久 ledger 和独立 wall timer
约束。原生 `RNAHub.load("RNA-FM-HF")` 也必须在该授权 child 内调用，
普通调用不能绕过预算。

失败时保留 `worker.log` 和 `api_result.json`，不隐式补跑或伪造分数。
输出目录已存在则拒绝覆盖。此为项目调用的防误用机制，不是对恶意文件所有者的沙箱。

## 读取本次真实结果，不重跑

```python
import json
from pathlib import Path

path = Path("runs/20261103_api_workflow_v1/adaptation/api_result.json")
result = json.loads(path.read_text())
print(result["status"])  # EXECUTED
print(result["runs"][0]["metrics"]["test"])
```

2026-11-03 的单次流程已经消耗该 scope 唯一一次 attempt；不能复制旧 scope
来重复执行。`run_api_once.py` 也使用不可覆盖收据，不是无界运行入口。

## 输出与复算

- `adaptation/api_result.json`：标准 `BenchmarkResults` JSON，包括任务指标与资源。
- `adaptation/lora/*_predictions.tsv`：固定 ID、原始标签和预测。
- `adaptation/lora/result.json`：checkpoint/source/tokenizer 身份及训练收据。
- `adaptation/lora/adapter.pt`：LoRA 与 readout 参数，不保存整份 FM 权重。
- API 重新读取预测文件，核对 ID、分区、原标签，并重算全部验证/测试指标。
- `lora_checkpoint_update_verification.json`：CPU 安全读取 checkpoint，
  确认 24 个初始为零的 LoRA B tensor 均已成为非零。
- `formal_gate_probe.json`：真实 `RNABenchmark` 对未准入任务仍返回 BLOCKED。

详见 [真实运行和资源报告](../reports/API_WORKFLOW_REAL_RUN_2026-11-03.md)。
这些是探索性任务指标，不是正式排行榜分数，不产生 Universal Score。
