# RNA Gym 交互 API

## 范围与安全边界

本地 HTTP/JSON API 包装现有任务 registry、StateDB、admission gate 和 GPU adapter。
它不是另一套任务编号或准入系统。没有下载、远端发布、任意 shell、任意文件读取、
客户端批准覆盖或 CPU FM fallback。默认只监听 `127.0.0.1`，不对外网开放。

`/` 和 `/docs` 是交互控制台；`/openapi.json` 是 OpenAPI 3.1 文档。
控制台资产保存在 `tools/api_console/`，不改变历史静态预览站点的文件 allowlist。
无外部 CDN 或前端框架依赖。控制台通过真实 HTTP 操作，并非只显示示例结果。

所有 `/v1/` 接口要求 `Authorization: Bearer <TOKEN>`。服务生成的 `api_token`
权限为 0600，运行目录为 0700。token 不嵌入页面、URL、请求日志或浏览器持久存储。
网页的 token 输入只保存在当前页面内存。服务校验 loopback Host 和同源 Origin；
不要把它配置成无鉴权的公网模型服务。

## 启动和连接

在实际工程目录执行：

```bash
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  OPENBLAS_NUM_THREADS=6 .venv-qc/bin/python tools/interactive_api.py \
  --config configs/interactive_api.json \
  --run-root runs/interactive_api --state-db run-state.sqlite --port 8765
```

服务只监听本机。若客户端不在该节点，使用现有环境的端口转发，不直接扩大监听范围。
从本地运行目录读取 `api_token`，粘贴到控制台密码输入框。不要将 token 发到公开日志。

`configs/interactive_api.json` 是管理员配置，引用已存在的模型 manifest 和 GPU
环境记录；HTTP 请求不能指定 Python 解释器、模型文件路径或人为批准字段。
缺少本地模型资产时 API 不会联网补齐或换 mock。默认任务配置仍为 HOLD。

## HTTP 接口

| 方法 | 路径 | 语义 |
|---|---|---|
| GET | `/v1/health` | 调度器、可见 GPU、run 状态和独立的预算预留 |
| GET | `/v1/tasks` | 全部登记任务及真实缺项，不是已完成 assay 数 |
| GET | `/v1/models` | 已登记模型与当前 API 实现能力，不冒称所有模型可运行 |
| GET | `/v1/tasks/{task_id}/readiness` | 指定任务的 registry/gate/binding 检查 |
| POST | `/v1/tasks/{task_id}/pilot` | 空 JSON body；提交该任务，不能覆盖准入/协议 |
| POST | `/v1/tasks/pilots` | `{"task_ids":"all"}` 或明确的唯一 ID 列表 |
| POST | `/v1/runs` | 提交 encoder、diagnostic、assay 或白名单 checks |
| GET | `/v1/runs` | 历史 run 状态 |
| GET | `/v1/runs/{run_id}` | 阶段、尝试次数、错误、资源观测是否完整 |
| GET | `/v1/runs/{run_id}/events` | 持久化状态事件，不包含 bearer token |
| GET | `/v1/runs/{run_id}/logs` | 有界日志尾部及失败原因 |
| GET | `/v1/runs/{run_id}/result` | 仅成功完成 run 的真实输出 |
| GET | `/v1/runs/{run_id}/predictions` | 仅真实 assay 的逐样本预测；不把表示当成绩 |
| POST | `/v1/runs/{run_id}/cancel` | 取消排队或本服务拥有的运行进程 |
| POST | `/v1/runs/{run_id}/resume` | 同请求、同源/输入 hash 的有界恢复 |
| POST | `/v1/runs/{run_id}/replay` | 冻结源码/输出完整性；assay 另重算保存预测的指标 |

提交 run 和任务 pilot 要求 `Idempotency-Key`。同 key、同内容返回同一个 run；
同 key、不同内容返回 409。恢复另要求幂等 key，不能改变种子、预算、初始化或协议。
成功/失败/中断/取消不覆盖旧尝试目录，最多两次执行尝试。

- 202：已排队，不是已执行。
- 409：包括科学 HOLD、幂等冲突、无可回放结果；读取具体 reason。
- 207：批量逐项返回；必须统计每项状态，不能把 HTTP 成功当全部模型成功。
- 400/422：无效/超范围输入，未执行 FM。
- `BLOCKED`：条件或资源阻塞；不补零分。
- `NOT_APPLICABLE`：明确非 assay/control 排除，不等于模型失败。
- `FAILED`：实际尝试失败；`INTERRUPTED`/`CANCELLED` 单独保留。

## GPU 表示 API

当前真实实现为 RNA-FM。未知或未验证的模型 ID 返回明确错误，不自动替代模型。
每次请求最多 16 条严格 A/C/G/U 序列，每条最多 1022 nt，batch 为 1–4。
空序列、DNA、lowercase、重复 observation ID、超长、伪标签或 device 覆盖会被拒绝。
无 T→U、uppercase 或静默截断。全部 FM forward 使用显式分配的 `cuda:N`。

`POST /v1/runs` 的表示请求：

```json
{
  "kind": "encoder",
  "model_id": "RNA-FM",
  "initialization": "pretrained",
  "seed": 11,
  "batch_size": 4,
  "records": [
    {"observation_id": "UNLABELED_EXAMPLE", "sequence": "ACGUACGU"}
  ]
}
```

结果包含逐 ID 640 维 pooled 表示、有效 nucleotide mask、token/nt 映射、实际 CUDA
资源和缓存计数；不是功能预测。表示请求不接受 `label`、`task_id` 或伪 assay 信息。
上述序列只是工程输入，没有实验功能标签。

真实模型契约诊断也通过 API 提交：

```json
{"kind":"diagnostic","model_id":"RNA-FM","initialization":"random","seed":23}
```

诊断执行真实模型和 GPU，但使用无标签工程序列；不能称为真实 assay 成绩或正式
预训练收益分析。正式五种子设计不因这里的接口试跑而减少。

## 完整验收也通过 API

```json
{"kind":"checks","suite":"all"}
```

控制台选择「软件 / 合同测试」即可提交。服务内部只运行固定白名单命令，结果通过
API 返回各命令 argv、退出码、stdout/stderr hash、真实耗时和日志。`all` 包括：

- 主项目完整回归，含真实 localhost HTTP 契约测试；不伪造 FM 模型运行。
- 原站点和任务卡 byte-exact 验证。
- 不可变规划包、HOLD 示例 schema 与合同反例测试。
- 本地公开候选 allowlist/敏感信息扫描和源码隔离回归；没有 publish。

浏览器缺失导致的 skip 必须公开，不自动下载 Chrome。源码隔离测试仍使用现有环境，
不是 clean install 或独立科学 reviewer 审核。

## 持久化、恢复与回放

新增的 `eval_api_*` 表位于现有 StateDB，与 acquisition/admission jobs 分开命名。
原 gate 不被 API 代签；任务 registry、人工审核和 exact evaluation binding 仍必需。
任务输入路径只能由管理员的本地 resolved 配置绑定，不能由客户端任意读取。

每个可执行请求冻结完整请求、源码/输入 hash 和实际字节 snapshot。每次尝试保存
独立 command、stdout/stderr、exit、输出和 hash 清单。正常重试复用同一请求并保留
失败分母；源码/输入改变时拒绝恢复，应创建明确的新版本 run。

worker 使用 Linux parent-death signal。API 意外退出后，重启会把旧 RUNNING 标为
INTERRUPTED，不自动当成功；只在原 worker 已消失后允许重新调度，且不杀任意旧 PID。
新 attempt 不覆盖旧文件。失去的资源遥测为未知；预算另保守预留该次完整上限，
`gpu_budget` 区分已观测用量和未观测区间的预留，不能拿预留冒充实际计费用量。

表示/诊断回放仅验证冻结源码 snapshot 与输出完整性，不产生新 FM forward 或功能
指标。真实 assay 的保存预测指标回放还要求当前 scorer、数据、split 和 gate 不变。
不把 transport/UI 升级当作旧输出损坏，也不使用新 scorer 静默重算旧协议。

## 当前科学边界

本轮 198 个任务均可逐项经 API 提交/检查，但现有 registry 仍无 admitted assay。
189 项返回明确科学阻塞，9 项为非 assay 排除；不能将这称为 198 个真实模型试跑成功。
需要补齐原始 assay/标签单位/使用权利/冻结 split 与真实人审绑定，不能只翻转 enabled。
满足条件后，API 调用原 frozen pilot，保留两种子、两初始化、标签预算、逐样本预测和
统计；仍不自动进入正式主榜。
