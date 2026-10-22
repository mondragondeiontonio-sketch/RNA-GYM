'use strict';
(() => {
  const el = id => document.getElementById(id);
  const state = {tasks: [], cards: new Map(), filtered: [], page: 0};
  const labels = {
    RELEASE_REVIEW_NOT_ADMITTED: '来源待核验 · 未准入',
    HOLD_LABEL_REVIEW: 'HOLD · 标签待审', MODALITY_REVIEW: '输入模态待审',
    SHARED_SOURCE_PENDING_SAMPLE_DEDUP: '共享来源 · 样本待去重',
    HOLD_ASSAY_IDENTITY: 'HOLD · 实验身份待审', HOLD_SOURCE: 'HOLD · 来源待核实',
    PROTOCOL_OR_SPLIT_NOT_INDEPENDENT: '仅协议 / 非独立实验',
    EXCLUDE_FROM_CORE: '不进入核心榜'
  };
  const node = (tag, value, cls) => {
    const result = document.createElement(tag);
    if (value !== undefined && value !== null) result.textContent = String(value);
    if (cls) result.className = cls;
    return result;
  };
  function link(value, title) {
    if (!value) return node('span', 'unknown · 未核验', 'unknown');
    try {
      const parsed = new URL(value);
      if (parsed.protocol !== 'https:' || parsed.username || parsed.password) throw new Error('unsafe URL');
    } catch (_) { return node('span', 'unknown · 无公开链接', 'unknown'); }
    const a = node('a', title || value);
    a.href = value; a.target = '_blank'; a.rel = 'noopener noreferrer';
    return a;
  }
  function options(id, values) {
    for (const value of [...new Set(values)].sort()) {
      const option = node('option', id === 'status' ? (labels[value] || value) : value);
      option.value = value; el(id).append(option);
    }
  }
  function field(list, title, value, isLink = false) {
    const box = node('div'); box.append(node('dt', title));
    const dd = node('dd');
    if (isLink) dd.append(link(value));
    else if (value === null || value === undefined || value === '') dd.append(node('span', 'unknown · 未核验', 'unknown'));
    else dd.textContent = String(value);
    box.append(dd); list.append(box);
  }
  function showCard(taskId, focus = false) {
    const item = state.tasks.find(task => task.id === taskId);
    const card = state.cards.get(taskId);
    if (!item || !card) return;
    el('cardSelect').value = taskId;
    const root = el('assayCard'); root.replaceChildren();
    const header = node('div', null, 'card-title');
    const title = node('div'); title.append(node('p', `${item.id} / ${item.package}`), node('h3', item.title));
    header.append(title, node('span', 'NOT_ADMITTED · 非准入卡', 'status')); root.append(header);
    root.append(node('p', `Registry: ${item.registry_status}${item.audit_status ? ` · Audit: ${item.audit_status}` : ''}${item.stage ? ` · Stage: ${item.stage}` : ''}`, 'utility'));
    if (card.package_audit) {
      const audit = card.package_audit;
      root.append(node('p', `RNAGym 文件级科学审查：${audit.reference_count} 个参考文件中，${audit.mrna_coding_fitness_proxy_candidates} 个 mRNA-coding / protein-fitness / DNA 字母代理候选不属于直接 RNA 核心；其余 ${audit.noncoding_or_splicing_candidate_files} 个仅为 RNA-readout 候选。文件分类不是独立 assay 计数；全部 HOLD / NOT_ADMITTED。`, 'data-note'));
    }
    if (card.package_audit && card.package_audit.ncRNA_candidate_files !== undefined) {
      const audit = card.package_audit;
      root.append(node('p', `候选文件细分：${audit.ncRNA_candidate_files} ncRNA / ${audit.mrna_splicing_candidate_files ?? 'unknown'} mRNA-splicing；安全解压 ${audit.rna_candidate_files_safely_extracted ?? 'unknown'} 文件。候选文件行数 ${audit.rna_candidate_file_records ?? 'unknown'}：仅处理后文件的行数总和，未做独立观测去重，不是 task N，也不是准入样本量。`, 'data-note'));
    }
    const list = node('dl', null, 'card-grid');
    field(list, 'Dataset / 来源候选', item.dataset);
    field(list, 'Source family / 不是 assay ID', card.source_family_id);
    field(list, 'Canonical assay ID', card.canonical_assay_id);
    field(list, 'Original assay DOI / 非 benchmark DOI', card.original_assay_doi);
    field(list, 'Experimental accession', card.experimental_accession);
    field(list, 'Identity / Split verification', `${card.identity_status} / ${card.split_status}`);
    field(list, 'Rights / 不能从代码许可推断数据许可', card.rights_status);
    field(list, 'Rights evidence URL', card.rights_evidence_url, true);
    field(list, 'Task-linked raw SHA256 / 不从包级资产继承', card.raw_file_sha256);
    field(list, 'Release / commit', card.release_or_commit);
    field(list, 'Source entry / 链接不代表下载', card.source_url, true);
    field(list, 'Benchmark reference / 不是原始 assay DOI', card.benchmark_reference_url, true);
    const count = item.dataset_n;
    field(list, 'Actual task sample N / 不继承 PoC 文件统计', item.actual_n);
    field(list, 'Reported sample N / unverified', count.value === null ? null : `${count.value} · reported/unverified`);
    field(list, 'Original N wording / 不一定是样本量', count.reported ? `${count.reported} [${count.unit || 'unknown unit'}] · reported/unverified` : null);
    root.append(list);
    const files = node('details'); files.append(node('summary', `文件证据 / ${card.files.length} evidence · ${card.candidate_assets.length} candidate links`));
    files.append(node('p', '包级文件不能替代 file → assay → task 的身份映射；候选链接不是下载成功。显示 SHA 也不自动表示 SHA 已验证。'));
    for (const file of card.files) {
      const block = node('div', null, 'file-entry');
      block.append(node('strong', `${file.asset_id} · ${file.evidence_state || file.stage}`));
      block.append(node('p', `Byte stage: ${file.stage} · Assay identity verified: ${file.assay_identity_verified ? 'file-scoped assertion only' : 'NO'} · Admitted: NO`));
      block.append(node('p', file.scope === 'explicit_task_mapping' ? `明确任务关联：${file.task_ids.join(', ')}` : '仅 package 级证据；不据此认定本任务已下载。'));
      block.append(node('p', `Bytes: ${file.file_size_bytes === null ? 'unknown' : file.file_size_bytes} · SHA256 verified: ${file.sha256_verified ? 'explicitly reported by audit' : 'NO'}`));
      block.append(node('code', file.file_sha256 || 'SHA256: unknown'));
      if (file.verification_method) block.append(node('p', `Hash method: ${file.verification_method}`));
      if (file.actual_n !== null) block.append(node('p', `File/split N: ${file.actual_n} [${file.actual_n_scope}] · 仅此文件，不是任务 N，不可跨镜像相加。`));
      if (file.dataset_alias || file.original_split) block.append(node('p', `Dataset alias: ${file.dataset_alias || 'unknown'} · Original split: ${file.original_split || 'unknown'}`));
      if (file.exact_qc_state) block.append(node('p', `Exact QC: ${file.exact_qc_state} · 非完整科学 QC / 非 review-ready。`));
      block.append(node('p', `Rights: ${file.rights_status} · Assay DOI: ${file.assay_doi || 'unknown'} · Accession: ${file.experimental_accession || 'unknown'}`));
      const urls = node('p'); urls.append(link(file.source_url, '文件来源 ↗'), document.createTextNode(' · '), link(file.download_url, '下载入口 ↗'), document.createTextNode(' · '), link(file.rights_proof_url, '许可证据 ↗')); block.append(urls);
      files.append(block);
    }
    for (const asset of card.candidate_assets) {
      const p = node('p'); p.append(node('span', `${asset.asset_id} · LINK ONLY / BYTES UNVERIFIED · `), link(asset.url, '候选文件 ↗')); files.append(p);
    }
    if (!card.files.length) files.append(node('p', 'unknown · 尚无可展示的实际字节证据；不会把 README 文件链接标为已下载。'));
    root.append(files);
    const baseline = node('details'); baseline.open = true;
    baseline.append(node('summary', `任务声明 / Baseline: ${item.baseline_status}`));
    const config = node('dl', null, 'card-grid');
    for (const [name, value] of [['Input track', item.input_track], ['Readout', item.readout], ['Loss', item.loss], ['Metric', item.metric], ['低信息对照', item.control_baseline], ['经典 baseline', item.baseline], ['Scratch DL', item.model_baseline], ['Leakage checks', item.leakage]]) field(config, name, value);
    baseline.append(config); root.append(baseline);
    root.append(node('p', `当前风险：${item.hold_reason || item.reason || 'unknown · 待审查'}`, 'data-note'));
    if (item.next_action) root.append(node('p', `下一步：${item.next_action}`, 'footnote'));
    if (focus) {
      window.location.hash = `assay-${encodeURIComponent(taskId)}`;
      el('provenance').scrollIntoView({block: 'start'});
      el('cardHeading').focus({preventScroll: true});
    }
  }
  function render() {
    const body = el('taskbody'); body.replaceChildren();
    const pageSize = Number(el('pageSize').value);
    const pages = Math.max(1, Math.ceil(state.filtered.length / pageSize));
    state.page = Math.max(0, Math.min(state.page, pages - 1));
    for (const task of state.filtered.slice(state.page * pageSize, (state.page + 1) * pageSize)) {
      const tr = node('tr');
      const first = node('td');
      const id = node('a', task.id, 'id'); id.href = `#assay-${encodeURIComponent(task.id)}`;
      id.addEventListener('click', event => {event.preventDefault(); showCard(task.id, true);});
      first.append(id, node('strong', task.title), node('span', task.dataset || task.package, 'dataset'));
      const family = node('td', task.family); family.append(node('small', task.readout));
      const count = node('td');
      count.append(node('span', task.dataset_n.value === null ? 'unknown sample N' : task.dataset_n.value.toLocaleString('en-US'), 'n-value'));
      if (task.dataset_n.reported) {
        count.append(node('small', `原登记: ${task.dataset_n.reported} [${task.dataset_n.unit || 'unknown unit'}]`), node('span', 'reported/unverified', 'unverified'));
      } else count.append(node('small', '无已核实登记数字'));
      const status = node('td'); status.append(node('span', labels[task.status] || task.status, 'status'), node('small', task.status));
      if (task.stage) status.append(node('span', `Stage: ${task.stage} ≠ admission`, 'stage'));
      const source = node('td'); source.append(link(task.source, '来源 ↗'));
      tr.append(first, family, count, status, source); body.append(tr);
    }
    if (!state.filtered.length) {
      const tr = node('tr'); const cell = node('td', '没有匹配任务。请缩短关键词或使用“清除筛选”。'); cell.colSpan = 5; tr.append(cell); body.append(tr);
    }
    el('filteredCount').textContent = `显示 ${state.filtered.length} / ${state.tasks.length} 条注册任务 · 非独立 assay 数`;
    el('pageLabel').textContent = state.filtered.length ? `${state.page + 1} / ${pages}` : '0 / 0';
    el('prev').disabled = state.page === 0 || !state.filtered.length;
    el('next').disabled = state.page >= pages - 1 || !state.filtered.length;
  }
  function filter() {
    const query = el('search').value.trim().toLocaleLowerCase();
    state.filtered = state.tasks.filter(task =>
      (!el('family').value || task.family === el('family').value) &&
      (!el('package').value || task.package === el('package').value) &&
      (!el('status').value || task.status === el('status').value) &&
      (!query || [task.id, task.title, task.dataset, task.family, task.package, task.readout, task.baseline, task.status].join(' ').toLocaleLowerCase().includes(query)));
    state.page = 0; render();
  }
  async function fetchJSON(path) {
    const response = await fetch(path, {cache: 'no-store'});
    if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
    return response.json();
  }
  async function init() {
    const desktop = window.matchMedia('(min-width: 1081px)');
    const menu = document.querySelector('.navigation');
    const syncMenu = () => {menu.open = desktop.matches;}; syncMenu(); desktop.addEventListener('change', syncMenu);
    try {
      const [tasks, cards, summary] = await Promise.all(['tasks', 'provenance', 'summary'].map(name => fetchJSON(`data/${name}.json`)));
      const statuses = tasks.reduce((counts, task) => {counts[task.status] = (counts[task.status] || 0) + 1; return counts;}, {});
      if (tasks.length !== summary.registered_task_rows || cards.length !== tasks.length || summary.final_admitted_tasks !== 0 ||
          Object.keys(statuses).length !== Object.keys(summary.status_counts).length ||
          Object.entries(statuses).some(([key, value]) => summary.status_counts[key] !== value) ||
          tasks.some(task => task.admission_status !== 'NOT_ADMITTED') || new Set(cards.map(card => card.id)).size !== tasks.length ||
          tasks.some(task => !cards.some(card => card.id === task.id)) ||
          tasks.filter(task => task.stage === 'REVIEW_READY').length !== summary.review_ready_tasks) throw new Error('registry / summary / provenance mismatch');
      state.tasks = tasks; state.cards = new Map(cards.map(card => [card.id, card]));
      for (const [id, key] of [['nTasks', 'registered_task_rows'], ['nFamilies', 'source_families'], ['nPackages', 'download_packages'], ['nReview', 'review_ready_tasks'], ['nAdmitted', 'final_admitted_tasks']]) el(id).textContent = summary[key];
      el('snapshot').textContent = `Registry snapshot: ${summary.as_of || 'unknown'} · Explicitly SHA256-verified files: ${summary.raw_files_sha256_verified} · 审计输入与数据摘要见 summary.json`;
      el('citationDate').textContent = summary.as_of || 'unknown';
      el('auditSummary').replaceChildren(node('p', `任务处置：${summary.excluded_task_rows} EXCLUDED / ${summary.held_task_rows} HOLD；${summary.review_ready_tasks} review-ready / ${summary.final_admitted_tasks} admitted。这里统计注册任务行，不是独立 assay。`));
      if (summary.poc_audit) {
        const audit = summary.poc_audit;
        el('auditSummary').append(node('p', `PoC 范围：${audit.files_downloaded_and_sha256_verified} 个下载并计算 SHA256 的文件 / ${audit.compressed_bytes_downloaded} 压缩字节；${audit.paired_files_exact_qc_pass} 个文件通过 exact paired QC。`));
        el('auditSummary').append(node('p', `已完成 exact 身份扫描的四个小型 miRBench PoC 文件版本中的精确唯一有序 paired 输入：${audit.unique_paired_inputs_across_downloaded_mirbench}。仅此小型 PoC 范围；后续较大文件未纳入此精确去重计数。不是任务 N，不等于独立实验观测；镜像与官方文件不因配对相同而自动合并或双倍计权。独立 assay 核验：${audit.independent_assays_verified}；P0 完整验收：${audit.all_p0_dod_met ? '见主线程审查' : '尚未满足'}。`));
      }

      options('family', tasks.map(task => task.family)); options('package', tasks.map(task => task.package)); options('status', tasks.map(task => task.status));
      el('cardSelect').replaceChildren();
      for (const task of tasks) {const option = node('option', `${task.id} · ${task.dataset || task.title}`); option.value = task.id; el('cardSelect').append(option);}
      for (const id of ['search', 'family', 'package', 'status']) el(id).addEventListener(id === 'search' ? 'input' : 'change', filter);
      el('reset').addEventListener('click', () => {for (const id of ['search', 'family', 'package', 'status']) el(id).value = ''; filter();});
      el('pageSize').addEventListener('change', () => {state.page = 0; render();});
      el('prev').addEventListener('click', () => {state.page--; render();});
      el('next').addEventListener('click', () => {state.page++; render();});
      el('cardSelect').addEventListener('change', () => showCard(el('cardSelect').value));
      const hashCard = () => {
        if (!window.location.hash.startsWith('#assay-')) return;
        let id; try {id = decodeURIComponent(window.location.hash.slice(7));} catch (_) {return;}
        if (state.cards.has(id)) showCard(id, true);
      };
      window.addEventListener('hashchange', hashCard);
      filter(); showCard(tasks[0].id); hashCard();
    } catch (error) {
      for (const id of ['nTasks', 'nFamilies', 'nPackages', 'nReview', 'nAdmitted']) el(id).textContent = '—';
      const row = node('tr'); const cell = node('td', '索引无法验证。请用 python -m http.server 8000 --directory site 打开，并运行 python tools/generate_site.py --verify 检查快照。'); cell.colSpan = 5; row.append(cell); el('taskbody').replaceChildren(row);
      el('filteredCount').textContent = '未加载有效索引 · 未显示统计';
      el('snapshot').textContent = `数据读取 / 一致性检查失败：${error.message}`;
      el('assayCard').replaceChildren(node('p', 'unknown · 未加载来源证据；请先修复索引读取错误。'));
    }
  }
  init();
})();
