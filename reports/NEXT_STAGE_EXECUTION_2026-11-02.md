# RNA-Gym 下一阶段执行报告 — 2026-11-02

> **状态：工程验收通过；科学准入仍为 0。**
> 本报告只汇总真实已运行的本地操作和可追溯证据，不把技术 PASS、Pilot 分数或候选面板当作科学授权。

## 1. 执行范围与保护状态

- 实际工程根：`RNA-Gym_Codex_Starter_2026-10-22/` 内层目录。该源码目录无 `.git`，因此没有初始化或伪造 Git HEAD。
- PR #6：只读核查为 **OPEN / 未合并**；head `66f7338822b82e2e25b9837bcc4422a614b5959c`，base `54b0e1feace7fc4650dabbf528b427a6f7518f0a`。
- 原 RNA-FM-HF Frozen Pilot v1.2 未重跑、未重新编码；8 个既有视图及 162 行指标保留。8 个 `frozen_features.npy` 均通过原 `embedding_receipt.json` SHA256 复核，详见 `runs/20261102_taxonomy_admission_adaptation_v1/frozen_features_verification.json`。
- 原有 split、正式 gate、198 行 registry 和既有结果未覆盖。启动前保护文件 37 个，最终均 unchanged：`protected_verification.json`。
- 当地 V100 上存在 GROMACS 进程；未停止、未共享、未重启。只在已有 Slurm allocation `53118/vgpu002` 的空闲 GPU 上执行受控小实验；未新提交作业。最终 live 状态保存在 `final_live_state.json`。
- 当前没有生成 Universal Score，正式可评分集合为空。

## 2. Taxonomy V1

### 2.1 新版本

新文件：`configs/task_taxonomy_v1_20261102.yaml`。

- 保留全部 **28 个 canonical task ID**，没有重编号。
- 一级领域固定为四个：`Structure`、`Function & Regulation`、`Perturbation`、`Engineering & Design`。
- 八个二级类别：
  1. Secondary Structure
  2. 3D Geometry
  3. Structure Probing
  4. RNA Processing & Modification
  5. Translation & Stability
  6. RNA Identity & Interactions
  7. Variant Effects & Fitness
  8. Engineering & Design
- 原有更细的 17 个旧 category 保留在 `legacy_level2_category`，所以这是层级归并而不是删除任务。
- MRL-exact 固定为 5′UTR 输入；MRL-proxy 固定为 cDNA 输入，并要求记录实际覆盖区域，禁止自动称作 CDS。
- MRL、RRS、TE 分开；PC1 保持 dimensionless，不能转成小时或 Half-life；Decay Rate 和 Half-life 不转换、不互换。MRL-HL Pair 明确为联合任务、一个 assay/source 权重。
- GO、Protein Localization、临床代理和蛋白编码表型带有 RNA-specific 范围标记；RBP、RNA–RNA、CRISPR 使用独立 input schema。SSI 明确要求 sequence + partial signal + observation/evaluation mask，不能把 sequence-only probing 伪装成 imputation。

### 2.2 76 条 taxonomy review

逐项结果：`runs/20261102_taxonomy_admission_adaptation_v1/taxonomy_review_76.tsv`。

| 状态 | 数量 | 含义 |
|---|---:|---|
| MAPPED | 0 | 本轮没有把缺证据项自动批准为已完成映射 |
| SPLIT_REQUIRED | 14 | 输入/标签/条件/终点需要拆成独立 assay 或 schema |
| EVIDENCE_HOLD | 52 | 缺原始来源、标签定义、输入边界、来源映射或权限证据 |
| EXCLUDED | 10 | 方法、控制、元数据或非独立 endpoint，不能作为当前 frozen assay |

198 行交叉表：`data/registries/taxonomy_v1_20261102_crosswalk.tsv`。原 `data/audit/taxonomy_mapping_report.tsv` 未被覆盖。

## 3. 九个优先对象的科学证据包

九个对象均生成 evidence pack、README 和人工审核 checklist；全部仍为 `HOLD`，没有真实审核人签署，没有正式准入。总索引：`runs/20261102_taxonomy_admission_adaptation_v1/scientific_evidence/priority_nine_summary.tsv`；人工清单：`human_admission_checklist_9.tsv`。

| 对象 | 当前身份 | 处理结论 | 关键证据/阻塞 |
|---|---|---|---|
| Danio 5′UTR MRL | `MRL_EXACT` 候选 | HOLD | 已固定为 5′UTR、`log2(author MRL_6hpf)`；原 Methods/Supplement、18,021 行 source-table 逐行映射仍未完成；完整文本请求有 HTTP 500 记录 |
| Andreasson glmS ribozyme DMS | `DMS_FITNESS` 候选 | HOLD | 7,343/7,343 发布版→curated 序列/标签复核与 WT/variant round-trip 通过；仍需把二级 DMS_score 绑定到原始 kinetic column、浓度和单位 |
| Domingo tRNA DMS | `DMS_FITNESS` 候选 | HOLD | 4,175/4,175 复核通过；原论文/`GSE99418` 已定位；论文描述 4,176 个 genotype，而本地发布版 4,175，差异需人工解释 |
| Karner 3′UTR Decay | `UTR3_STABILITY` 候选 | HOLD | `GSE301426`、父项目 `GSE301535`、`PRJNA1285169` 和 2026 原论文已定位；原 Methods 说明 4 h 4sU SLAM-seq 的 log decay rate；本地 secondary release 到原始实验/转录本/六细胞 readout join 仍未完成 |
| Sugimoto MRL-proxy | `MRL_PROXY` / Secondary Proxy | HOLD | 11,693/11,693 secondary parquet 序列/label replay 通过；HP5 MRL 是 fraction 1–8 的 ribosome-number weighted read-count；cDNA CDS-marker 轨道保留但 5′UTR/CDS/3′UTR 完整边界未独立确认；有 1,631 normalized repeated-input rows |
| Saluki Human PC1 | `HALF_LIFE` 的 `PC1_HUMAN` 变体 / Secondary Proxy | HOLD | 12,939/12,939 replay 通过，RNA-FM 合格仅 656；PC1 是标准化、缺失值插补、quantile normalization 后的 dimensionless endpoint；不能转成小时 |
| Saluki Mouse PC1 | `HALF_LIFE` 的 `PC1_MOUSE` 变体 / Secondary Proxy | HOLD | 13,723/13,723 replay 通过，合格 968；需确认 species-specific PCA、parent assay/condition、annotation 和跨物种同源隔离 |
| ArchiveII ncRNA Family | `NCRNA_FAMILY` / Extended | HOLD | 保留分类标签；Wang release 不是原始实验，也没有把 family annotation 伪造成 pair/contact；`Mathews 2019` benchmark DOI 已单独核实，但 secondary subset derivation 和原始序列来源仍未绑定 |
| PERSIST MRL–HL Pair | `MRL_HL_PAIR` / Extended | HOLD | 既有 203 个 construct mapping；MRL 203 行 ≤1 ULP，in-cell half-life 仅 5 行 exact、7 行 ≤1 ULP，最大绝对差 0.0321884；179 行 shared component，不能声明原 split component-disjoint |

每个对象的详细文件在 `scientific_evidence/*/evidence_pack.json` 和同目录 `README.md`。来源检索 receipts 和可取得的 XML 在 `primary_sources/`。

## 4. 数据、重复、基因/同源和 split 审核

- 五个可直接从现有发布版重放的对象：Andreasson、Domingo、Saluki Human、Saluki Mouse、Sugimoto，均完成全量 sequence/label replay，未修改 raw 或 curated parquet。
- Karner 和 ArchiveII 只复核了 freeze、observation alias、当前 release metadata 和既有 provenance；没有猜测原始实验衍生过程。
- 所有保留 split 的 `sequence_hash`、`biological_group`、`split_group` 审核没有发现跨 role 的实际 hash 泄漏；没有 identifier 的字段明确记为 UNKNOWN，而不是当作零泄漏。
- Sugimoto 与 Saluki Human 的 eligible normalized exact sequence overlap 为 **31**；候选面板中不把两者当作独立无关来源。
- DMS 64-train bounded screen 显示 near-WT 跨 role：Andreasson 最近 train/test identity 中位数约 0.973，Domingo 约 0.986；这只是同一文库内的技术屏查，不能称作 unseen-WT 或新家族泛化。
- PERSIST 179-row shared component 和 Saluki/Sugimoto overlap 均进入 HOLD，不通过自动 admission。

核心结果：`scientific_evidence/split_gene_exact_audit.tsv`、`bounded_dms_homology_screen.tsv`、`cross_dataset_overlap.tsv`。

## 5. Structure Anchor：RNA3DB CMP/DMP

脚本：`tools/structure_anchor_v1.py`；输出：`runs/20261102_taxonomy_admission_adaptation_v1/structure_anchor/`。

### 标签合同

- 使用原始 mmCIF 的 full polymer sequence、chain、label/auth residue identity、model、coordinates；不删除缺失残基。
- 坐标原子：C4′。距离：同一 deposited chain/model 中 C4′ 的 Euclidean distance，单位 Å。
- Contact：严格 `distance < 8.0 Å`。
- 对角线排除；序列邻近 `|i-j| <= 3` 排除；只使用 strict upper triangle。
- 缺失代表原子、未知修饰 parent、ambiguous altloc 或 tie 保留为 invalid mask；不补坐标、不把修饰残基猜成 A/C/G/U。
- CMP/DMP 是 3D geometry；没有把 contact relabel 成碱基配对。SSI/SSP 没有被替换或伪造。

### 真实小型闭环

| chain | role | full length | valid C4′ residues | valid upper pairs | contacts | AUPRC | F1 | MAE (Å) | RMSE (Å) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 8bvm_u | validation | 108 | 49 | 1,053 | 2 | 0.001831 | 0 | 14.8794 | 17.3084 |
| 7zjw_S | test | 855 | 46 | 903 | 1 | 0.001120 | 0 | 12.6288 | 14.6968 |
| 7zjx_S | test | 855 | 46 | 903 | 2 | 0.001683 | 0 | 11.8790 | 13.8528 |

结果是固定 sequence-separation geometry null，不是 RNA-FM/learned model；训练标签数为 0。三条链只有两个独立 group，其中两条 test chain 同组，因此不生成 Structure leaderboard。逐坐标独立复算与保存 label 的 MAE/contact 完全通过，最大 distance replay delta 约 `3.74e-6 Å`。

RNA3DB 的 15,441 chain split manifests 已存在，但完整坐标到标签 admission、assembly、CCD/stereochemistry、rights 和预训练暴露仍需人工审核。

## 6. R03 持久预算守卫

新增：`rna_gym/budget.py`、`rna_gym/_budget_child.py`、`tools/adaptation_supervisor_v1.py`。

守卫特性：

- SQLite `BEGIN IMMEDIATE` 事务；共享 scope、固定总 GPU 秒数、固定最大 attempts、固定并发数。
- 崩溃/重启不会把 reservation 当作 0；未 settlement 的 reservation 保留并阻塞 active slot。
- 失败按 reservation cap 计费；超时只杀自己启动的 child。
- Linux `PR_SET_PDEATHSIG` + child timer：父进程死亡时 child 退出；实测通过。
- 第四次真实适配请求被 `ATTEMPTS_EXHAUSTED` 拒绝，没有重置 ledger。

验收：

- `tests/test_budget_r03.py`：7 项通过，包含真实 subprocess restart、8 进程竞争、失败计费、超时和 immutable cap。
- 后续硬化后新增 active-lease/no-bypass 测试；父死 child 死测试 PASS。
- 完整项目 suite 最终：**433 tests，0 failure，12 skipped**，见 `runs/20261102_taxonomy_admission_adaptation_v1/full_tests_final.log`。
- 新增局部 taxonomy/structure/LoRA/budget suite：最终 focused suite **18 tests passed**，见 `runs/20261102_taxonomy_admission_adaptation_v1/focused_tests_final.log`。

## 7. Scratch / PEFT / Full FT 首轮真实实验

固定对象：Andreasson、`DMS_FITNESS`、既有 EAZY fold 0、同一新建 tiny subset：64 train / 16 validation / 32 test，label-blind deterministic selection。训练标准化只使用 train mean/std，其他 role 不参与拟合。

CPU reference：

| 模型 | Spearman | RMSE | MAE | 备注 |
|---|---:|---:|---:|---|
| k-mer 1–3 Ridge | -0.133431 | 0.0166504 | 0.0135229 | CPU reference |
| cached frozen Ridge | 0.128666 | 0.0115292 | 0.0083162 | 复用既有 frozen features，不重新编码 |

真实 GPU：

| 模型 | test Spearman | test RMSE | test MAE | validation Spearman | GPU process s | train GPU wall s | peak allocated |
|---|---:|---:|---:|---:|---:|---:|---:|
| Matched Architecture Scratch | 0.351540 | 0.00644284 | 0.00611063 | 0.505882 | 30.5202 | 1.51777 | 2,020,300,288 B |
| Full FT | 0.321848 | 0.00229527 | 0.00182510 | -0.217647 | 11.1722 | 1.39588 | 2,020,300,288 B |
| LoRA | **FAILED** | — | — | — | 13.8602 observed / 180 reserved | — | — |

LoRA 失败原因为 RNA-FM fused functional attention 直接读取 `q_proj.weight/bias`；原 wrapper 缺少属性。`rna_gym/lora.py` 已修复并通过 CPU fused-attention gradient tests，但本轮共享 scope 的 3 次 attempt 已消耗，**不进行第四次 GPU retry**。

预算 ledger：`r03_shared.sqlite`。三次 reservation 的 conservative charged total 为 236.1132 GPU seconds；失败尝试按其 180 秒 reservation cap 计费。正式多 seed、多任务矩阵未批准、未执行。

## 8. 第一版候选 Benchmark Panel

配置：`configs/benchmark_panel_candidate_20261102_v1.yaml`；说明：`reports/BENCHMARK_PANEL_CANDIDATE_2026-11-02.md`。

Panel 是 score-independent candidate：

- Core candidates：Danio MRL-exact、Andreasson DMS、Domingo DMS、Karner 3′UTR Decay、RNA3DB CMP/DMP anchor。
- Secondary Proxy：Sugimoto MRL-proxy、Saluki Human PC1、Saluki Mouse PC1。
- Extended：ArchiveII ncRNA Family、PERSIST MRL-HL Pair。
- Structure、Function & Regulation、Perturbation 专项分别维护；Engineering & Design 独立维护，当前没有已准入 anchor。
- 所有 member 当前 `HOLD`；formal scoring sets 为四个空数组；human approved=false；Universal Score=false。
- PERSIST 组件 endpoint 只计一次 assay/source 权重；Saluki 人/鼠不增加独立 source 权重；RNA3DB 相关链不重复投票。

## 9. 未解决问题与下一轮最小工作清单

1. 由真实授权审核人逐一确认九个 evidence pack 的原 assay、Methods/Supplement、输入边界、标签变换、条件、权限和签署。
2. 为 Danio 完成原始 Methods/Supplement/accession 与 legacy fold row mapping；为 Domingo 解释 4,176 vs 4,175；为 Karner 完成六细胞 readout/转录本/condition join。
3. RNA3DB 完成全量/代表性 coordinate-to-label、assembly、modified residue、CCD、rights 和 pretraining exposure admission。
4. PERSIST 解决 half-life source-version mismatch、GSM/count-library mapping 和 179-row component split；不能修改原 split，需另开版本。
5. 新预算批准后最多重跑一次修复后的 LoRA smoke；不能复用本轮 scope 或覆盖本轮失败 receipt。
6. 建立一个 schema-bound Engineering anchor（RNA switch/CRISPR/design）后再考虑 Engineering 专项评分。
7. 最终重跑完整 regression suite，确认 README 链接修复后的 433 tests 全绿，再考虑 PR/文档发布。

## 10. 验收结论

本轮实现了可运行、可复算、可追溯的工程交付：Taxonomy 版本化、76 条 review disposition、九个 evidence pack、RNA3DB 真实 label/score replay、R03 持久预算守卫和首轮 Scratch/Full-FT 真实适配。

**没有实现、也没有声称实现：** 科学 PASS、正式排行榜、Universal Score、LoRA 成功训练、全量 RNA3DB admission、Engineering admission 或正式多 seed 结论。
