#!/usr/bin/env python3
"""Export approved T0021 split-audit aggregates, never fold rows or labels."""
import argparse,hashlib,html,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def count(x):
 if type(x) is not int or not 0<=x<=1000000:raise ValueError('invalid aggregate count')
 return x

def build(s,approved=False):
 if approved is not True:raise PermissionError('explicit public aggregate approval required')
 for key in ['admission_candidates','admitted','real_models_run','GPU_jobs']:
  if type(s.get(key)) is not int or s[key]!=0:raise ValueError('only zero-admission, no-model audit supported')
 if s.get('scientific_disposition')!='HOLD_SOURCE_IDENTITY' or s.get('raw_labels_read_for_split') is not False or s.get('original_split_changed') is not False or s.get('labels_merged') is not False or s.get('all_observations_preserved') is not True:raise ValueError('unsupported data/approval change')
 c=s['coverage'];n=count(c['rows']);genes=count(c['unique_gene_annotations']);mapped=count(c['mapped_gene_annotations']);unmapped=count(c['unmapped_gene_annotations'])
 if not n or mapped+unmapped!=genes or genes>n:raise ValueError('inconsistent coverage')
 author=s['author_protocol_reproduction'];custom=s['custom_exploratory_split'];table=[]
 for label,q in [('Author code logic reproduction',author),('RNA-Gym custom exploratory version',custom)]:
  splits={key:count(q['split_counts'][key]) for key in ['train','validation','test']}
  if sum(splits.values())!=n or q['evaluation_enabled'] is not False or q['admission_gate_pass'] is not False:raise ValueError('inconsistent split/approval')
  g=count(q['gene_overlap']['shared_keys']);i=count(q['exact_input_overlap']['shared_keys']);h=count(q['known_homology_groups_shared'])
  table.append(f'<tr><th scope="row">{label}</th><td>{splits["train"]:,} / {splits["validation"]:,} / {splits["test"]:,}</td><td>{g:,}</td><td>{i:,}</td><td>{h:,}</td></tr>')
 for x in [custom['gene_overlap']['shared_keys'],custom['exact_input_overlap']['shared_keys'],custom['known_homology_groups_shared']]:
  if x!=0:raise ValueError('custom page requires observed constraints actually pass')
 pair=author['pairwise_overlap_counts']['train__test'];ttg=count(pair['shared_gene_keys']);tti=count(pair['shared_exact_input_keys']);groups=count(s['custom_component_count']);largest=count(s['largest_component_rows'])
 sha=s['source_input_sha256']['HOMOLOGENE_13910050'];protocol=s['protocol_sha256']
 if not re.fullmatch('[a-f0-9]{64}',sha) or not re.fullmatch('[a-f0-9]{64}',protocol):raise ValueError('invalid proof hashes')
 return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'self'; style-src 'self'; script-src 'none'; object-src 'none'; base-uri 'self'"><title>RNA-Gym · T0021 group split audit</title><link rel="stylesheet" href="phase2.css"></head><body>
<a class="skip-link" href="#evidence">跳转到审计事实</a><header class="masthead"><a class="brand" href="index.html">RNA-Gym</a><nav aria-label="来源审计导航"><a href="phase2.html">Dataset Atlas</a><a href="persist-audit.html">T0022 source review</a></nav></header>
<main><section class="hero"><div class="hero-copy"><p class="eyebrow">T0021 · MRL · SPLIT AUDIT</p><h1>同源映射未覆盖的基因，<br>不能默认跨折独立。</h1><p>{n:,} 条固定输入；原作者代码逻辑复现与独立探索版本对照。没有重扫 RNA 大文件，也没有读取标签来选择分折。</p></div><aside class="lineage-panel"><p class="eyebrow">SCOPE BEFORE SCORE</p><h2>HOLD</h2><p>ADMISSION_CANDIDATE=0 · ADMITTED=0</p><p>原始 isoform／细胞／条件身份仍未核实，所有模型排行榜仍为空。</p></aside></section>
<section class="section" id="evidence"><div class="notice"><strong>这不是对论文实际运行结果的重新评测。</strong><p>未取得论文实际固定 fold manifest。以下数字仅适用于本轮固定输入、作者代码版本和 seed 2541 的本地逻辑复现，不能断言论文所有运行都相同。</p></div>
<h2>映射覆盖：{mapped:,} / {genes:,}</h2><p>gene 注释计数指来源注释字符串，不是实验数、transcript ID 或可靠的基因组位点数。当前固定输入共有 {genes:,} 个不同注释，其中 {unmapped:,} 个未命中作者指定的 HomoloGene 映射。</p>
<h2>三折之间的共享键，不是模型成绩</h2><div class="table-scroll"><table><thead><tr><th>Protocol</th><th>train / validation / test</th><th>Shared gene keys</th><th>Shared exact whole-input keys</th><th>Shared known map groups</th></tr></thead><tbody>{''.join(table)}</tbody></table></div>
<p>仅看作者逻辑复现的 train 对 test：共享 {ttg:,} 个 gene 键、{tti:,} 个完整输入键。三折合并口径与这个 pairwise 口径不同，不可相加。</p>
<h2>为什么产生风险</h2><p>固定版本作者函数对已知同源组整体分配；未命中映射的 gene 退回逐行分配，同一未知 gene 的不同观测因而可能跨折。原作者代码和复现文件均保留，没有静默修补或删除观测。</p>
<p>新版本联合同 gene、已知 HomoloGene group 和相同完整输入键，得到 {groups:,} 个连通分组，最大 {largest:,} 条。只是分组观测，不合并标签；未知基因也不退回逐行拆分。</p>
<h2>版本和边界</h2><p>新折为 <strong>RNA_GYM_CUSTOM_EXPLORATORY_VERSION_NOT_OFFICIAL</strong>。协议在实际查看映射和任何模型运行前冻结，但在原任务登记之后；不伪称任务选择前预注册，也不伪称官方固定折。</p>
<p>检查范围内的 gene／完整输入／已知 map group 重合为 0，不等于独立 RNA 序列同源已清除。未映射家族、跨数据集和预训练暴露，以及原始 assay 条件仍待审查。评测开关保持关闭。</p>
<h2>可复现来源</h2><ul><li><a href="https://zenodo.org/records/13910050" rel="noreferrer">作者实际指定的 HomoloGene 映射 v1.0</a>：metadata 声明数据 MIT；不自动授予原 assay 准入。</li><li><a href="https://github.com/morrislab/mRNABench/blob/778d691ab91c51c03addeb9219229f2ec81d195c/mrna_bench/data_splitter/homology_split.py" rel="noreferrer">已固定的作者 split 逻辑</a>。</li></ul>
<p>本轮观测 ZIP SHA256：<code>{sha}</code>；协议 SHA256：<code>{protocol}</code>。Git commit 对象 ID 不是文件 SHA256。</p>
<p>单任务本地审计：<code>python tools/audit_mrl_group_splits.py --run runs/YOUR_LOCAL_RUN --dry-run</code>。需要已审查来源和既有精确身份缓存，命令不会下载、训练或批准数据。</p><p>仅公开代码、来源索引和聚合事实；原始序列、标签、gene 列表、fold 行表及 reviewer 记录保留本地。</p></section></main></body></html>\n'''

def write_once(path,text):
 b=text.encode();path=Path(path)
 if path.is_symlink():raise ValueError('symlink refused')
 if path.exists():
  if path.read_bytes()!=b:raise ValueError('immutable page differs; use a new versioned filename')
 else:
  path.parent.mkdir(parents=True,exist_ok=True)
  with path.open('xb') as f:f.write(b)
 return hashlib.sha256(b).hexdigest()

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--audit',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--approve-public-aggregates',action='store_true');p.add_argument('--dry-run',action='store_true');a=p.parse_args()
 if a.audit.stat().st_size>1024**2:raise ValueError('summary cap')
 s=json.loads(a.audit.read_text());text=build(s,a.approve_public_aggregates)
 if not a.dry_run:write_once(a.output,text)
 print(json.dumps(dict(status='VERIFIED_APPROVED_AGGREGATES_ONLY',admitted=0,real_scores=0,created=not a.dry_run,sha256=hashlib.sha256(text.encode()).hexdigest())))
if __name__=='__main__':main()
