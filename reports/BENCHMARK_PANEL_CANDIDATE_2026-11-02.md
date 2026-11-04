# RNA-Gym 第一版候选 Benchmark Panel

**候选面板，不是已准入/可评分面板。** 选择函数只读生物学身份、来源、输入/标签、质量和权利缺口，不读取任何模型指标。Core代表候选定位，不代表PASS。

| 数据对象 | Canonical任务 | 候选层 | 专项 | 准入 |
|---|---|---|---|---|
| 5UTR/077_danio_embryo_NOT_APPLICABLE_OR_UNKNOWN | MRL_EXACT | Core | Function & Regulation | HOLD |
| DMS_Andreasson_2020_ribozyme | DMS_FITNESS | Core | Perturbation | HOLD |
| DMS_Domingo_2018_tRNA | DMS_FITNESS | Core | Perturbation | HOLD |
| EUKA_karner_decay_rate_763b01f0f301 | UTR3_STABILITY | Core | Function & Regulation | HOLD |
| MRNA_mrl-sugimoto | MRL_PROXY | Secondary Proxy | Function & Regulation | HOLD |
| MRNA_rnahl-saluki-human | HALF_LIFE | Secondary Proxy | Function & Regulation | HOLD |
| MRNA_rnahl-saluki-mouse | HALF_LIFE | Secondary Proxy | Function & Regulation | HOLD |
| WANG_Archivell_Nr | NCRNA_FAMILY | Extended | Function & Regulation | HOLD |
| PERSIST_MRL_HL_PAIR | MRL_HL_PAIR | Extended | Function & Regulation | HOLD |
| RNA3DB_REAL_COORDINATE_ANCHOR_V1 | CMP, DMP | Core | Structure | HOLD |

Structure、Function & Regulation、Perturbation分别维护专项；Engineering & Design独立且当前为空。全部正式scoring集合为空，不计算Universal Score。

PERSIST联合输出计一次source权重；Saluki两物种不当成两份独立来源；RNA3DB两条相同序列相关链不重复加权。不存在按当前分数反选成员。
