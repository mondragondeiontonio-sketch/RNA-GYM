# 持久预算入口守卫 V1.1

## 作用与覆盖

`RNAHub.load()`、直接 `RNAFMAdapter` 构造和 `encode()` 的每个 batch 均先检查持久 lease。缺少 approved scope、匹配 ledger、ACTIVE reservation、supervised PID 或 child wall timer 时，必须在读取权重/执行 FM forward 前失败。

元数据查询、数据 QC、来源审核和普通 CPU 基线不需要 GPU lease。没有 CPU FM fallback。

这用于防止意外的无预算执行；不是面向恶意本机文件所有者的安全沙箱，也不能阻止用户在项目之外自行运行模型。

## 配置与状态

- 策略：`configs/compute_budget_policy_v1.json`。
- 当前只登记上一轮 scope；其 3 次 attempts 已全部使用。
- 检查策略和 ledger 是只读操作，不能初始化新 scope、修改 cap、释放 crash reservation 或重置已用预算。
- 失败/崩溃按原 reservation 保守计费。
- 新 LoRA 请求在 `runs/20261102_blocker_optimization_v1/lora_retry_request.json`；状态是 PENDING，不是授权。

## 未来获批后的执行方式

1. 真实用户明确批准新的 GPU 秒数、attempts、并发和目的。
2. 将新 scope 和审批证据登记到 approved policy；不要修改上一轮 scope 的 limits 或 ledger。
3. 确认单 GPU allocation 空闲；不要停止或共享其他 workload。
4. 只通过 `BudgetLedger.run_supervised()` 启动 worker。它设置持久 reservation 环境和 child 独立 timer，父死时 child 退出。
5. LoRA worker 使用新 `--output` 路径，并用 `--reference-work` 只读引用上一轮固定 recipe/subset；旧失败目录不能覆盖。

当前没有执行上述新 GPU scope。单次建议请求为 180 秒 / 1 attempt；需要明确批准后才可执行。

## 常见拒绝原因

| 错误 | 含义 |
|---|---|
| PERSISTENT_APPROVED_COMPUTE_LEASE_REQUIRED | 没有完整 lease 环境 |
| COMPUTE_SCOPE_NOT_AUTHORIZED | scope 不在授权策略 |
| APPROVED_LEDGER_BINDING_MISMATCH | ledger 路径与策略不一致 |
| SUPERVISED_CHILD_REQUIRED | 不是当前受监督子进程 |
| INDEPENDENT_CHILD_WALL_TIMER_REQUIRED | child timer 缺失 |
| ACTIVE_PERSISTENT_RESERVATION_REQUIRED | lease 不存在或已结算 |
| PERSISTENT_LEASE_EXPIRED | reservation 已过期 |
| ATTEMPTS_EXHAUSTED | 原 scope 次数已用完，不能静默重置 |

## 验证

```bash
python -m unittest tests.test_compute_guard tests.test_budget_r03 -v
```

这些测试只使用自己的临时 CPU 子进程/临时 ledger，不执行真实 FM，不申请新 Slurm 作业，不消耗既有 GPU scope。
