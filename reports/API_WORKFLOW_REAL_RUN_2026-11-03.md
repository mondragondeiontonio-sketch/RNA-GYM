# RNA-FM-HF API 真实运行与验收 — 2026-11-03

> 状态：**TECHNICAL API PASS / SCIENTIFIC HOLD**。以下是任务级探索指标，
> 不是正式排行榜分数，不生成 Universal Score。

## 1. 本轮完成内容

- 完成上一轮验收：449 discovered = 437 passed + 12 skipped；232 个旧文件哈希一致。
- 新建候选面板 V1.2，只修正 Danio / Andreasson 旧说明及证据指针；不改成员与分层。
- 新增原生 Python `AdaptationPilot`：检查 → 授权预算 → 真实 GPU worker →
  逐 ID 预测 → 指标重放 → 统一 `BenchmarkResults` JSON。
- 支持 `RNAHub.load("RNA-FM-HF")` 明确部署别名；backend 仍为原 pinned RNA-FM，
  没有换 checkpoint、下载新权重或引入 HTTP/OpenAI 依赖。
- 在真实 GPU 上完成此前未成功的 LoRA 小样本流程，不重跑已完成 Frozen Pilot。
- 正式 `RNABenchmark` 的准入 gate 未修改，实际 probe 仍为 BLOCKED。

## 2. 实验身份与固定设置

| 项目 | 本轮设置 |
|---|---|
| 数据 | Andreasson 2020 ribozyme variants |
| 原始标签 | kcat，s⁻¹；不是浓度特异 kobs 或生长 fitness |
| 任务 | DMS_FITNESS canonical ID 保留；assay label_variant=kcat |
| Parent split | 原 EAZY_fold_0，不创建或改写原 split |
| 子集 | train 64 / validation 16 / test 32；原 label-blind 子集 |
| 模态 | LoRA rank 4 / alpha 8，q_proj 与 v_proj |
| 训练 | seed 42，1 epoch，16 steps，batch 4；HPO=0 |
| 标准化 | 只在 train 拟合；预测反变换后按原始标签评分 |
| 可训练参数 | 123,521 |
| 科学范围 | 同 WT/library 的小型技术实验，不声称 unseen-WT 泛化 |

既有 Fixed recipe 与 subset SHA256 在新 scope 中绑定。
正式多 seed 设计、所有原始标签、既有 split 与 Frozen 结果均未改变。

## 3. 本轮真实指标

| Role | n | Spearman | Pearson | RMSE（s⁻¹） | MAE（s⁻¹） | R² |
|---|---:|---:|---:|---:|---:|---:|
| validation | 16 | 0.226471 | 0.237053 | 0.00735692 | 0.00273630 | -0.041701 |
| test | 32 | 0.109604 | 0.232504 | 0.00227126 | 0.00162277 | 0.018705 |

验证和测试预测均重新读取、核对 record ID / role / 原标签，并重算所有指标通过。
不从当前分数推断科学 PASS，也不据此调整候选 panel。

### 同一固定子集的已有参考

| 方法 | Test Spearman | Test RMSE（s⁻¹） | 执行状态 |
|---|---:|---:|---|
| kmer123_ridge | -0.133431 | 0.01665044 | 既有结果，未重跑 |
| cached_frozen_ridge_same_subset | 0.128666 | 0.01152916 | 既有结果，未重跑 |
| scratch | 0.351540 | 0.00644284 | 既有结果，未重跑 |
| full_ft | 0.321848 | 0.00229527 | 既有结果，未重跑 |
| RNA-FM-HF LoRA | 0.109604 | 0.00227126 | 本轮真实 API 执行 |

旧 full-fold Frozen Linear/MLP 的标签预算不同，不混入这张 matched-subset 表。
单 seed、32 条 test 记录、无正式 CI，不能据此宣称某种适配方式胜出。

## 4. GPU 和持久预算

- 用户新请求是跑一次任务流程；执行器将上限定为 1 卡 / 180 wall seconds / 1 attempt。
  数值上限由执行器保守设定，没有伪称用户逐项指定了这些数字。
- 新 scope：`20261103-rnafm-hf-api-lora-once`；单独 ledger，未重置旧 scope。
- 实查为两个各 2 卡的 Slurm allocation；本进程只可见当前节点的两张卡。
  其中一张有现有计算，本轮只选择另一张空闲、已分配的卡。
- 训练 GPU wall：1.328738 s。
- 训练吞吐：48.166 sequences/s。
- worker 记录的模型阶段 wall：16.627621 s。
- ledger 保守计费（含启动等开销）：25.060750 s。
  这些是单卡 wall-time 口径，不是 CUDA kernel profiler 时间。
- 峰值 allocated：0.743961 GiB；峰值 reserved：0.828125 GiB。
- 新 scope 唯一 attempt 已消耗、没有 ACTIVE reservation；后续不自动重试。
- 旧 scope 仍为 3/3 attempts，账本 SHA256 与本轮前一致。

保存了原始请求、授权范围、GPU 空闲/分配 preflight 和最终 scheduler/GPU snapshot。
不停止或重启其它作业，不运行四卡并行矩阵。

## 5. 代码与验收

- API：`rna_gym/workflows.py`、`rna_gym/models.py`、`rna_gym/__init__.py`。
- 原 worker：`tools/adaptation_smoke_v1.py`，仍使用原 recipe/subset。
- 新 CPU 契约测试：14/14 通过，覆盖授权、GPU 分配/忙卡拒绝、路径、标签和指标重放。
- 全量：**463 discovered = 451 passed + 12 skipped**；无 failures/errors。
  skipped 是明确的可选 CIF parser / browser 检查，不计入 passed。
- 原受保护文件：232/232 SHA256 一致；另单独核验 8/8 Frozen feature 文件与原收据一致。
- LoRA checkpoint 有 48 个 adapter tensors；24 个初始为零的 B tensors 均已非零。
  此项只在 CPU 安全读取，不执行新的 FM forward。
- 九份科学证据 parent SHA256 均匹配，审核签名仍为空；正式集合保持为空。
- `formal_gate_probe.json`：真实未准入任务仍 BLOCKED，metrics=None。
- 本轮未修改 Git 远端、未 push/merge；PR #6 未重新网络查询，旧 OPEN 快照不当作新状态。

## 6. 交付路径和复算

根目录：`runs/20261103_api_workflow_v1/`。

- `adaptation/api_result.json`：API 统一结果。
- `adaptation/lora/result.json`、`*_predictions.tsv`、`adapter.pt`：模型与评分产物。
- `execution_authorization.json`、`gpu_preflight.json`、`r03_api.sqlite`：新 scope 证据。
- `old_scope_preservation.json`、`final_live_state.json`：旧预算保护与实际状态。
- `lora_checkpoint_update_verification.json`、`formal_gate_probe.json`：额外核验。
- `full_tests.log`、`full_tests_execution.json`、`acceptance_summary.json`：验收。
- `configs/benchmark_panel_candidate_20261103_v1_2.yaml`：不按分数选择的候选 panel。
- 上轮收尾：`runs/20261102_blocker_optimization_v1/acceptance_summary.json`。

```bash
# 只读、CPU 数值审计；不会训练或提交 GPU 作业。
python runs/20261103_api_workflow_v1/verify_delivery.py
```

调用方法见 [适配 API](../docs/ADAPTATION_API.md)。当前 API 是固定小样本路径，
不是所有八个任务的全新训练矩阵；已完成 Pilot 仅复用，不重编码。

## 7. 剩余阻塞与下一步

1. 真实授权审核人继续补齐来源、权利、条件与标签版本，逐 assay 签署。
2. Danio 新 gene-grouped 候选需独立 homology 审核与批准后比较；不冒称原结果 gene-OOD。
3. PERSIST barcode/GSM、half-life 版本及 shared component 仍 HOLD。
4. 扩大 RNA3DB 代表性和 assembly/chain/rights 审查；现有 learned anchor 仍为技术实验。
5. 更大模型矩阵、额外 seed、checkpoint reload 的 GPU forward 或新 scope，需另行批准。
   Engineering & Design 独立建设；保持 Universal Score 关闭。
