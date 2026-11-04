# RNA-Gym 阻塞优化与更新 — 2026-11-02 V1.1

> 工程推进和来源证据更新；不是科学准入。九个对象仍为 HOLD，正式评分集合为空，不生成 Universal Score。

## 1. 本轮完成的关键改进

| 阻塞 | 新证据 / 改进 | 当前边界 |
|---|---|---|
| 原生 SDK 可绕过预算 runner | `RNAHub.load`、直接 `RNAFMAdapter` 构造和逐 batch encode 均增加 approved durable lease、supervisor PID、timer、scope/ledger/cap 检查 | 既有 scope 不重置；没有新增 GPU 尝试 |
| Andreasson DMS_score 原始含义不明 | 7,343/7,343 序列与本地原始动力学表唯一匹配；DMS_score 全部严格等于原表 `kcat` | 标签身份已明确；权利、人工签署及同-WT适用范围仍需审核 |
| Danio 无逐行来源和基因信息 | 找到已有本地 annotation；18,021/18,021 序列唯一匹配，`log2_MRL_6hpf` 完全相等 | 本地 annotation 到出版商/accession 的链条及权利仍未确认 |
| Danio 旧 split 不支持 gene-OOD | 恢复 10,257 个 gene groups；fold0/3/7 分别有 958/949/963 个 train-test shared genes | 旧结果只能解释为随机 ID；旧 split 原样保留 |
| Danio 缺合法 gene-held-out 候选 | 新建 `RNAGYM_DANIO_GENE_GROUPED_V1_1`，18,021 条记录、10,257 groups、十折 gene/exact-sequence/component 跨 role 为 0 | 候选版本，未跑模型、未完成全同源性及科学准入 |
| Structure 只有无训练几何 null | 从本地 archive prefix 找到 2 条原 split 的 train chains，训练真实 CPU Ridge/Logistic CMP/DMP，held-out 预测和指标复算通过 | 仍是极小技术 anchor，不是正式 Structure 排行榜 |
| PERSIST 缺样本/GSM线索 | 完整 GEO metadata 共70样本，25/25 author-selected libraries 获得唯一 title candidates | barcode/index未验证；不能把 title candidate 当 exact library identity |
| PERSIST half-life 差异可能被任意缩放修复 | 比值范围 0.998941–1.000959，不是单一常数比例 | 保持 source-version HOLD，不修补标签 |
| Sugimoto/Saluki overlap 解释混淆 | 量化18个协议组合的实际 train/test overlap | 相同输入不等于重复 assay；pooled/transfer training 需要额外共享输入分组控制 |
| LoRA 旧输出/ledger 写死 | 支持新 output + 只读引用原固定 recipe/subset；准备180秒/1 attempt独立预算请求 | 请求未获批、未执行；旧 ledger 字节不变 |

## 2. 新的 Danio gene-held-out 候选 split

文件：`data/splits/RNAGYM_DANIO_GENE_GROUPED_V1_1/assignments.tsv` 和 `split_summary.json`。

- 仅使用 recovered gene/Ensembl IDs、gene symbol、exact normalized sequence 建立 connected components。
- 标签盲 SHA256 group assignment；test fold=f，validation=(f+1)%10，其余 train。
- 全部18,021条记录保留，0 quarantine。
- 十折均验证 gene、sequence、component 不跨 role。
- 不覆盖 legacy UTR folds；未重新编码 Frozen，也未生成新模型分数。
- gene isolation 不等于 homology clearance，且 publisher source identity/rights/reviewer 仍需人工审核。

构建与复核：

```bash
python -m tools.danio_gene_candidate_v1_1
python -m tools.verify_blocker_sources_v1_1
```

第一条命令对相同内容幂等，不允许替换冲突 split。

## 3. 真实 learned Structure Anchor

输出：`runs/20261102_blocker_optimization_v1/structure_learned_anchor/`。

从已存在的 2.14 GB RNA3DB archive 只读取131,072 compressed bytes / 593,920 decompressed bytes，访问18个members，找到：

- `3nvk_K`：原 D1 split 的 train group。
- `8ked_A`：另一个原 D1 train group。

这不是新下载，也没有将 held-out chain 改作 train。

训练使用2,488个有效核苷酸对，10个contact positives；19维 sequence-derived features，StandardScaler只在train上fit；DMP为Ridge(alpha=1)，CMP为固定C=1的LogisticRegression。没有根据validation/test调参。

| chain | 原 role | MAE Å | RMSE Å | AUPRC | F1 | replay |
|---|---|---:|---:|---:|---:|---|
| 8bvm_u | validation | 11.67023 | 13.86605 | 0.001576 | 0 | PASS |
| 7zjw_S | test | 10.75864 | 13.59931 | 0.001120 | 0 | PASS |
| 7zjx_S | test | 10.72623 | 13.59929 | 0.002759 | 0 | PASS |

保存了数值模型参数、train alignment audit、labels、predictions 和指标。可只用导出系数复算预测；不依赖pickle。两条test chain同组，不当成两个独立source。

这是普通CPU基线，不是CPU FM fallback，也不是RNA-FM structure模型。本轮GPU训练秒数为0。

## 4. 预算守卫覆盖与兼容性

详见 `docs/COMPUTE_BUDGET_GUARD_V1_1.md`。

- 新增 `rna_gym/compute_guard.py` 与 `configs/compute_budget_policy_v1.json`。
- 未授权调用必须在权重读取/forward前失败。
- guard只读检查旧ledger；原3次attempt和保守计费记录不变。
- 直接adapter路径和encode逐batch也检查，避免只保护高层runner。
- 真实无GPU supervised child测试通过；过期/settled lease、scope/cap/path/PID/timer不一致均拒绝。
- 原path-routing tests现在明确mock授权，只测试路由；独立安全测试仍确认生产入口无lease时拒绝。

不对恶意本机文件所有者声称安全沙箱；作用是预防项目正常调用中的无预算执行。

## 5. 九个 evidence pack 与候选 panel V1.1

证据增量：`runs/20261102_blocker_optimization_v1/scientific_evidence_v1_1/`；每个文件保留 parent evidence路径和SHA256，没有覆盖旧证据。

人工清单：`human_review_update_9.tsv`，reviewer/signature为空，scientific_admitted=false。

候选配置：`configs/benchmark_panel_candidate_20261102_v1_1.yaml`。成员和Core/Extended/Secondary Proxy定位未按分数改变；加入新来源和协议证据，正式专项评分集合仍全部为空。

明确纠正：Sugimoto与Saluki有31条相同输入，说明跨数据集pool/transfer时需要防训练测试污染，但不能仅凭相同输入断言它们是同一assay或不独立的原始研究。

## 6. 不可用证据与仍需人工/预算的事项

- Danio PMC页面和Domingo supplement请求返回HTML而非所需正文/表格；BioC返回明确错误。都已拒绝作为科学证据，见 `payload_validation.json`。
- 原Methods/Supplement与版权许可的未解决部分没有猜测、没有自动PASS。
- PERSIST25条title candidates不是barcode/GSM exact join；half-life source-version和179-rowcomponent仍HOLD。
- LoRA只有修复后的CPU组件测试，没有新GPU成功结果；`lora_retry_request.json` 是180秒/1 attempt建议，不是授权。
- RNA3DB全量坐标、assembly、modified residues、homology、rights、预训练暴露和representativeness仍需准入审核。
- Engineering & Design没有新增已准入anchor。

## 7. 验收和复算

- 全量测试收据：`runs/20261102_blocker_optimization_v1/full_tests_final_cpu_v2.log`。
- focused收据：`focused_tests.log`。
- 来源全量重放：`original_source_row_replay_verification.json`。
- 保护旧文件核验：`protected_verification.json`。
- 最终状态：`acceptance_summary.json`。

以前一次交接中“433 passed /12 skipped”的说法不精确：原日志实际上是433 discovered，即421 passed +12 skipped；本轮测试统计一律从真实log解析，不把skips算作passed。

### 2026-11-03 收尾验收

- 实际全量测试：449 discovered = 437 passed + 12 skipped；失败和错误均为 0。
- 232 个受保护旧文件（含旧 split、Frozen 结果及 R03 账本）全部 SHA256 一致。
- `full_tests_final.log` 的 14 个 HTTP 契约测试环境错误已保留；
  仅固定关闭派发的合成 GPU 分配夹具，没有降低生产资源或预算校验。
- 新版候选面板为 `configs/benchmark_panel_candidate_20261103_v1_2.yaml`；
  只修正 Danio、Andreasson 旧说明并补证据指针，成员与分层不变。
- 九个证据包的 parent SHA256 均匹配；审核签名仍为空，正式集合仍为空。

## 8. 下一轮最小工作

1. 由真实授权审核人确认Danio出版商source链、Andreasson权利/最终标签版本、PERSIST barcode-GSM和half-life版本，逐assay签署。
2. 独立批准LoRA的180秒/1 attempt新scope后，使用新目录和原固定subset重试一次；不重置原scope。
3. 在新Danio gene-grouped候选上完成经批准的模型比较，并独立检查homology；不改写旧random-ID结果。
4. 将RNA3DB技术anchor扩展为权利清楚、source/chain/assembly审查完成的代表性structure集合。
5. 单独建立Engineering anchor，不提前汇总Universal Score。
