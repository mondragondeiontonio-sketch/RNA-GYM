#!/usr/bin/env python3
"""Explicitly approved, aggregate-only T0022 source review page; no labels export."""
import argparse,hashlib,html,json,math,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def integer(x,maximum=100000):
 if type(x) is not int or not 0<=x<=maximum:raise ValueError('invalid aggregate integer')
 return x

def build(summary,plan,approve=False):
 if approve is not True:raise PermissionError('explicit public-aggregate approval required')
 if summary.get('admitted')!=0 or summary.get('admission_candidates')!=0 or summary.get('scientific_disposition')!='HOLD' or summary.get('raw_labels_changed') is not False:raise ValueError('this page only supports unadmitted source reviews')
 if summary.get('real_models_run')!=0 or summary.get('gpu_jobs')!=0 or summary.get('raw_sequences_changed') is not False or summary.get('rows_deleted')!=0 or summary.get('official_split_changed') is not False:raise ValueError('unsupported real execution or data modification')
 population=summary['source_population_selection'];n=integer(population['acquired_rows']);source_n=integer(population['source_construct_rows']);mapped=integer(summary['source_row_and_representation_counts']['sequence_mapping_matches'])
 if n==0 or mapped>n or n>source_n or population['acquired_ID_set_matches_finite_source_outcome_set'] is not True:raise ValueError('inconsistent population')
 if not re.fullmatch('[a-f0-9]{40}',summary['source_commit']):raise ValueError('unverified commit')
 labels=[]
 for key,title in [('target_ribosome_load','Ribosome-load index'),('target_in_cell_half_life','In-cell half-life')]:
  r=summary['label_comparison'][key];exact=integer(r['exact_float32_rows']);within=integer(r['within_one_ulp_rows']);ulp=integer(r['maximum_ulp_distance'],2**32)
  if not exact<=within<=n:raise ValueError('label aggregate mismatch')
  error=r['maximum_absolute_float32_error']
  if type(error) not in (int,float) or not math.isfinite(error) or error<0:raise ValueError('invalid source difference')
  labels.append(f'<tr><th scope="row">{title}</th><td>{exact}/{n}</td><td>{within}/{n}</td><td>{ulp:,}</td><td>{error:.9g}</td></tr>')
 split=summary['author_protocol_split'];split_counts={k:integer(split['split_counts'][k]) for k in ['train','validation','test']}
 if split.get('seed')!=2541 or split.get('split_origin')!='AUTHOR_CODE_PROTOCOL_REPRODUCTION_NOT_OFFICIAL_FIXED_MANIFEST':raise ValueError('unsupported split provenance')
 if sum(split_counts.values())!=n or split.get('evaluation_enabled') is not False or split.get('scientific_split_pass') is not False:raise ValueError('split not an audit-only reproduction')
 groups=summary['component_disjoint_stress_test'];sizes=[integer(x) for x in groups['component_sizes']]
 if not sizes or sum(sizes)!=n:raise ValueError('inconsistent component counts')
 links=[];expected_files={'PERSIST_CONSTRUCTS':'constructs.tsv','PERSIST_COUNTS':'joined.txt','PERSIST_SAMPLES':'samples.csv'};seen=set()
 for row in plan['assets']:
  aid=row.get('asset_id')
  if aid not in expected_files or aid in seen or row['relative_filename']!=expected_files[aid]:raise ValueError('unsafe filename or duplicate asset')
  seen.add(aid)
  if row.get('redistribution_permission')!='NOT_APPROVED' or not re.fullmatch('[a-f0-9]{64}',row['sha256_expected']):raise ValueError('unsafe plan rights or hash')
  commit=summary['source_commit'];url=row['direct_url']
  if url!='https://raw.githubusercontent.com/barnalab/persist/'+commit+'/analysis/'+expected_files[aid]:raise ValueError('unsafe source URL')
  links.append(f'<li><a href="{html.escape(url,quote=True)}" rel="noreferrer">{html.escape(row["relative_filename"])}</a><br><code>{row["sha256_expected"]}</code></li>')
 if seen!=set(expected_files):raise ValueError('source plan incomplete')
 adjacent=summary['label_comparison']['target_ribosome_load']['within_one_ulp_rows']-summary['label_comparison']['target_ribosome_load']['exact_float32_rows']
 fingerprint=summary['input_fingerprint']
 if not re.fullmatch('[a-f0-9]{64}',fingerprint):raise ValueError('invalid evidence fingerprint')
 return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; style-src 'self'; script-src 'none'; object-src 'none'; base-uri 'self'">
<title>RNA-Gym · T0022 source review</title><link rel="stylesheet" href="phase2.css"></head>
<body><a class="skip-link" href="#evidence">跳转到审计事实</a><header class="masthead"><a class="brand" href="index.html">RNA-Gym</a><nav aria-label="审计导航"><a href="phase2.html">Dataset Atlas / QC</a></nav></header>
<main><section class="hero"><div class="hero-copy"><p class="eyebrow">T0022 · PERSIST-seq · SOURCE REVIEW</p><h1>{mapped} 条输入已回溯。<br>标签版本仍待核对。</h1><p>VERIFIED 是具体审计事实，不是最终科学准入。两个 readout 保持分开，所有排行榜仍为空。</p></div><aside class="lineage-panel"><p class="eyebrow">SOURCE → REPRESENTATION → REVIEW</p><h2>{source_n} → {n}</h2><p>原作者构件 → 已取得输入</p><p>来源映射通过，不等于标签与实验准入通过。</p></aside></section>
<section id="evidence" class="section"><div class="notice"><strong>HOLD · ADMISSION_CANDIDATE=0 · ADMITTED=0</strong><p>没有修正标签、删除观测、改变原始 split，或运行真实 baseline / FM。</p></div>
<h2>来源与表示：{source_n} → {n}</h2><p>{mapped}/{n} 个 transcript_id 与原作者 SequenceID 对应。当前输入精确等于来源 RNA 移除已验证的 3 nt GGG 前缀，再显式 U→T 表示映射后的序列。原 RNA 和派生输入的哈希分别保存，不视为未经记录的相同样本。</p>
<p>{source_n-n} 个来源构件缺少 half-life；取得文件的 ID 集合与两列 outcome 均有限的来源子集完全一致。source rows、样本重复和 assay 数不是同一单位。</p>
<h2>标签源列比对，不是模型分数</h2><div class="table-scroll"><table><thead><tr><th>Readout</th><th>Float32 exact</th><th>Within 1 ULP</th><th>Max ULP</th><th>Max absolute difference</th></tr></thead><tbody>{''.join(labels)}</tbody></table></div>
<p>{adjacent} 条 ribosome-load 标签为相邻 float32 值，并未静默舍入。half-life 版本差异仍待作者转换代码／发表 source table 核对；未拟合缩放参数或放宽通过阈值。</p>
<h2>作者协议复现，不是假冒官方固定 split</h2><p>Seed 2541；train / validation / test = {split_counts['train']} / {split_counts['validation']} / {split_counts['test']}。全输入跨折精确重合为 {integer(split['exact_input_keys_shared_across_splits'])}，但来源构件组合仍跨折共享。</p>
<p>保守的共享 UTR5 / CDS / UTR3 连通压力测试得到 {len(sizes)} 个组，最大组 {max(sizes)} 条。它既不证明同源已清除，也不代表重复实验观测应被删除。没有为凑比例强制生成自定义分组 split。</p>
<h2>输入轨道与剩余阻断</h2><p>CDS 特征标记每个 codon 的首位，不是整个编码区覆盖。所有位置验证和显式 CDS fallback 保留在本地证据中。样本表虽为 .csv 后缀，真实分隔符是 TAB。</p>
<p>GEO 父研究关联不自动核实每个 count-library index。原作者仓库没有独立数据许可；本轮仅授权本地隔离审计，没有批准 raw 再分发，也没有最终人工科学审批。</p>
<h2>可公开来源索引与可复现性</h2><p>原论文：<a href="https://doi.org/10.1038/s41467-022-28776-w" rel="noreferrer">PERSIST-seq original paper</a>；<a href="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE173083" rel="noreferrer">GSE173083 parent study</a>。</p><p>固定作者 commit：<code>{summary['source_commit']}</code>。以下为原站链接和本轮观测 SHA256，不是数据镜像，也不是上游发布的 checksum。</p><ul>{''.join(links)}</ul>
<p>单任务零下载计划：<code>python tools/audit_persist.py --plan</code>。下载前仍需独立核对权利，代码不会从计划自动授予许可。</p><p>本地审计输入指纹：<code>{fingerprint}</code>。本页只发布聚合事实；不含原始标签、序列、行级身份表、私人路径或 reviewer 记录。</p></section></main></body></html>\n'''

def write_once(path,content):
 path=Path(path)
 if path.is_symlink():raise ValueError('symlink refused')
 data=content.encode()
 if path.exists():
  if path.read_bytes()!=data:raise ValueError('immutable page differs; choose new versioned filename')
 else:
  path.parent.mkdir(parents=True,exist_ok=True)
  with path.open('xb') as f:f.write(data)
 return hashlib.sha256(data).hexdigest()

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--audit',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--approve-public-aggregates',action='store_true');p.add_argument('--dry-run',action='store_true');a=p.parse_args()
 if a.audit.stat().st_size>1024**2:raise ValueError('summary cap')
 s=json.loads(a.audit.read_text());plan=json.loads((ROOT/'configs/persist_source_review.json').read_text());text=build(s,plan,a.approve_public_aggregates)
 if not a.dry_run:write_once(a.output,text)
 print(json.dumps(dict(verification_status='VERIFIED',public_export='AGGREGATES_ONLY_NOT_ADMISSION',admitted=0,model_scores=0,created=not a.dry_run,sha256=hashlib.sha256(text.encode()).hexdigest())))
if __name__=='__main__':main()
