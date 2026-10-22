/* RNA-Gym Phase 2: read only an explicitly approved aggregate contract. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const state = {snapshot: null, taskPage: 1, assayPage: 1};
  const TASK_PAGE_SIZE = 20;
  const ASSAY_PAGE_SIZE = 12;
  const stageOrder = ['NOT_REVIEWED', 'FILE_QC_PASS', 'SOURCE_VERIFIED', 'ASSAY_VERIFIED',
    'SPLIT_QC_PASS', 'ADMISSION_CANDIDATE', 'ADMITTED', 'HOLD', 'EXCLUDED'];
  const reasonNames = {
    RIGHTS: 'Data rights / license', SOURCE: 'Original source evidence',
    ASSAY_IDENTITY: 'Assay / observation identity', LABEL_SEMANTICS: 'Label definition / units',
    SPLIT_LEAKAGE: 'Split / leakage / deduplication', QC: 'Scientific QC',
    HUMAN_REVIEW: 'Human review / approval', SAFE_FORMAT: 'Safe format / encoding',
    ACQUISITION: 'Acquisition / access', OTHER_REVIEW_REQUIRED: 'Other review required'
  };
  const priorNames = {
    registered_tasks: 'Registered task rows', package_groups: 'Management packages',
    local_acquired_artifacts: 'Acquired artifacts (not assays)',
    local_raw_artifact_bytes_including_reassembly: 'Local artifact bytes, including reassembly',
    network_downloaded_artifacts: 'Network-downloaded artifacts', lossless_reassembled_artifacts: 'Reassembled artifacts',
    groups_with_acquired_artifacts: 'Groups with acquired artifacts', mrna_file_rows_scanned: 'mRNA file rows scanned',
    mrna_files_all_rows_scanned: 'mRNA files scanned', paired_file_rows_including_versions: 'Pair file rows, including versions',
    paired_files_all_rows_scanned: 'Pair files scanned', probing_sequence_records_scanned: 'Probing sequence records scanned',
    probing_exact_shared_train_test_sequences: 'Exact probing sequences shared across train/test',
    coordinate_files_scanned: 'Coordinate files scanned', coordinate_atom_rows_scanned: 'Coordinate atom rows scanned'
  };
  const number = (n) => new Intl.NumberFormat('en-US').format(n);
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = String(text);
    if (className) element.className = className;
    return element;
  };
  function badge(value) {
    const style = value.startsWith('HOLD') || value === 'BLOCKED' ? 'hold' :
      value.startsWith('EXCLUDED') ? 'excluded' : value === 'VERIFIED' || value.startsWith('ADMITTED') ? 'verified' : '';
    return node('span', value, `badge ${style}`);
  }
  function options(id, values) {
    const select = $(id);
    [...new Set(values)].sort().forEach((value) => {
      const option = node('option', value);
      option.value = value;
      select.append(option);
    });
  }
  function evidence(reference) {
    return `${reference.source_file} · data row ${reference.row} · SHA256 ${reference.input_sha256.slice(0, 12)}…`;
  }
  function validate(snapshot) {
    if (!snapshot || snapshot.schema_version !== 'rnagym.phase2.public.v1' ||
        snapshot.public_aggregate_approval?.explicit !== true ||
        snapshot.public_aggregate_approval.scope !== 'PUBLIC_AGGREGATES_ONLY_NOT_ASSAY_APPROVAL' ||
        snapshot.results_publication_enabled !== false || !Array.isArray(snapshot.tasks) ||
        !Array.isArray(snapshot.assays) || !Array.isArray(snapshot.baseline_protocols) ||
        !Array.isArray(snapshot.sources) || !snapshot.counts ||
        snapshot.counts.registered_tasks !== snapshot.tasks.length ||
        snapshot.counts.assays !== snapshot.assays.length ||
        ['rna_fm', 'rna_llm', 'rna_agent'].some((key) => !Array.isArray(snapshot.leaderboards?.[key]) ||
          snapshot.leaderboards[key].length !== 0)) throw new Error('Unapproved or incompatible aggregate contract');
    return snapshot;
  }
  function renderTasks() {
    if (!state.snapshot) return;
    const query = $('taskSearch').value.trim().toLowerCase();
    const rows = state.snapshot.tasks.filter((task) =>
      (!query || [task.task_id, task.package_group_id, task.scientific_stage, task.disposition,
        ...task.blocking_categories.map((reason) => reasonNames[reason] || reason)].join(' ').toLowerCase().includes(query)) &&
      (!$('stageFilter').value || task.scientific_stage === $('stageFilter').value) &&
      (!$('dispositionFilter').value || task.disposition === $('dispositionFilter').value) &&
      (!$('packageFilter').value || task.package_group_id === $('packageFilter').value));
    const pages = Math.max(1, Math.ceil(rows.length / TASK_PAGE_SIZE));
    state.taskPage = Math.min(pages, Math.max(1, state.taskPage));
    $('taskRows').replaceChildren();
    rows.slice((state.taskPage - 1) * TASK_PAGE_SIZE, state.taskPage * TASK_PAGE_SIZE).forEach((task) => {
      const tr = node('tr');
      const identity = node('td');
      identity.append(node('strong', task.task_id, 'task-id'), node('span', task.package_group_id, 'package-id'));
      const stage = node('td'); stage.append(badge(task.scientific_stage));
      const disposition = node('td'); disposition.append(badge(task.disposition));
      const audit = node('td'); audit.append(badge(task.verification_status));
      const reasons = node('ul', null, 'reason-list');
      task.blocking_categories.forEach((reason) => reasons.append(node('li', reasonNames[reason] || 'Other review required')));
      audit.append(reasons, node('p', evidence(task.evidence_reference), 'evidence-ref'));
      if (!task.evidence_available) audit.append(node('p', 'No task evidence reference declared.', 'microcopy'));
      tr.append(identity, stage, disposition, audit);
      $('taskRows').append(tr);
    });
    if (!rows.length) {
      const row = node('tr'); const cell = node('td', 'No tasks match. Clear the search or reset filters.');
      cell.colSpan = 4; row.append(cell); $('taskRows').append(row);
    }
    $('taskResultCount').textContent = `${number(rows.length)} of ${number(state.snapshot.tasks.length)} registered tasks match.`;
    $('pageStatus').textContent = `Page ${state.taskPage} of ${pages}`;
    $('previousPage').disabled = state.taskPage === 1;
    $('nextPage').disabled = state.taskPage === pages;
  }
  function safeSourceLink(url, text) {
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== 'https:' || parsed.username || parsed.password || parsed.search || parsed.hash) return null;
      const link = node('a', text, 'source-link');
      link.href = parsed.href;
      link.rel = 'noopener noreferrer';
      link.target = '_blank';
      return link;
    } catch (_) { return null; }
  }
  function renderAssays() {
    if (!state.snapshot) return;
    const query = $('assaySearch').value.trim().toLowerCase();
    const rows = state.snapshot.assays.filter((assay) =>
      (!query || [assay.canonical_assay_id, assay.original_assay_id, assay.source_project, assay.source_doi,
        assay.experiment_accession, assay.biological_readout, assay.data_license].join(' ').toLowerCase().includes(query)) &&
      (!$('assayVerificationFilter').value || assay.verification_status === $('assayVerificationFilter').value));
    const pages = Math.max(1, Math.ceil(rows.length / ASSAY_PAGE_SIZE));
    state.assayPage = Math.min(pages, Math.max(1, state.assayPage));
    $('assayCards').replaceChildren();
    rows.slice((state.assayPage - 1) * ASSAY_PAGE_SIZE, state.assayPage * ASSAY_PAGE_SIZE).forEach((assay) => {
      const card = node('article', null, 'assay-card');
      card.append(badge(assay.verification_status), node('h4', assay.canonical_assay_id));
      const dl = node('dl');
      const fields = [['Source project', 'source_project'], ['Original assay', 'original_assay_id'],
        ['DOI', 'source_doi'], ['Accession', 'experiment_accession'], ['Readout', 'biological_readout'],
        ['Label meaning', 'label_definition'], ['Label unit', 'label_unit'], ['Data license', 'data_license'], ['QC state', 'qc_status']];
      fields.forEach(([label, key]) => dl.append(node('dt', label), node('dd', assay[key] || 'Unknown / not verified')));
      card.append(dl);
      if (assay.evidence_url) {
        const link = safeSourceLink(assay.evidence_url, 'Open public source evidence ↗');
        if (link) card.append(link);
      }
      card.append(node('p', evidence(assay.evidence_reference), 'evidence-ref'));
      $('assayCards').append(card);
    });
    if (!rows.length) $('assayCards').append(node('p', state.snapshot.assays.length ?
      'No assays match. Clear the search or change evidence status.' : 'No assay records supplied in this audit snapshot. Task rows are not substituted for assays.', 'microcopy'));
    $('assayResultCount').textContent = `${number(rows.length)} of ${number(state.snapshot.assays.length)} assay records match.`;
    $('assayPageStatus').textContent = `Page ${state.assayPage} of ${pages}`;
    $('previousAssayPage').disabled = state.assayPage === 1;
    $('nextAssayPage').disabled = state.assayPage === pages;
  }
  function renderBars(id, entries, labeler) {
    const target = $(id); target.replaceChildren();
    const max = Math.max(1, ...entries.map(([, count]) => count));
    entries.forEach(([key, count]) => {
      const row = node('div', null, 'bar-row');
      const meter = node('span', null, 'bar-track');
      const fill = node('span', null, 'bar-fill');
      // SVG geometry, rather than inline style, keeps the strict CSP intact.
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', '0 0 100 10');
      svg.setAttribute('width', '100%'); svg.setAttribute('height', '100%');
      svg.setAttribute('preserveAspectRatio', 'none'); svg.setAttribute('aria-hidden', 'true');
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('width', String(100 * count / max)); rect.setAttribute('height', '10');
      rect.setAttribute('fill', '#8b9bcb'); svg.append(rect); fill.append(svg); meter.append(fill);
      row.append(node('span', labeler(key), 'bar-label'), meter, node('span', number(count), 'bar-number'));
      target.append(row);
    });
    if (!entries.length) target.append(node('p', 'No entries declared in this snapshot.', 'microcopy'));
  }
  function renderBaselines() {
    if (!state.snapshot) return;
    const query = $('baselineSearch').value.trim().toLowerCase();
    const protocols = state.snapshot.baseline_protocols.filter((protocol) =>
      (!$('baselineFamily').value || protocol.family === $('baselineFamily').value) &&
      (!query || [protocol.title, ...protocol.methods, protocol.requirements].join(' ').toLowerCase().includes(query)));
    $('baselineCards').replaceChildren();
    protocols.forEach((protocol) => {
      const card = node('article', null, 'baseline-card');
      card.append(badge('PROTOCOL ONLY'), node('h3', protocol.title));
      const methods = node('ul'); protocol.methods.forEach((method) => methods.append(node('li', method)));
      card.append(methods, node('p', protocol.requirements), node('p', 'Task binding and executable smoke test: not certified by this catalogue.', 'microcopy'));
      $('baselineCards').append(card);
    });
    $('baselineResultCount').textContent = `${protocols.length} protocol families match. No baseline scores are published.`;
    if (!protocols.length) $('baselineCards').append(node('p', 'No protocol matches. Clear the search or change family.', 'microcopy'));
  }
  function renderSnapshot(snapshot) {
    state.snapshot = snapshot;
    $('registeredCount').textContent = number(snapshot.counts.registered_tasks);
    $('assayCount').textContent = number(snapshot.counts.assays);
    $('candidateCount').textContent = number(snapshot.counts.admission_candidate_tasks);
    $('admittedCount').textContent = number(snapshot.counts.admitted_tasks);
    options('stageFilter', snapshot.tasks.map((task) => task.scientific_stage));
    options('dispositionFilter', snapshot.tasks.map((task) => task.disposition));
    options('packageFilter', snapshot.tasks.map((task) => task.package_group_id));
    options('assayVerificationFilter', snapshot.assays.map((assay) => assay.verification_status));
    options('baselineFamily', snapshot.baseline_protocols.map((protocol) => protocol.family));
    renderTasks(); renderAssays(); renderBaselines();
    renderBars('stageCounts', stageOrder.filter((key) => snapshot.stage_counts[key] !== undefined)
      .map((key) => [key, snapshot.stage_counts[key]]), (key) => key.replaceAll('_', ' '));
    renderBars('holdCounts', Object.entries(snapshot.hold_reason_counts), (key) => reasonNames[key] || 'Other review required');
    const prior = snapshot.previous_technical_snapshot;
    if (prior && prior.scope === 'PREVIOUS_TECHNICAL_SNAPSHOT_NOT_CURRENT_ADMISSION') {
      $('previousSnapshotStatus').textContent = `Historical technical run ${prior.run_id || '(unspecified)'}. File rows, chunks, versions and atom positions are not independent assays or verified task sample counts.`;
      Object.entries(prior.counts).forEach(([key, count]) => {
        if (Object.hasOwn(priorNames, key)) $('previousCounts').append(node('dt', priorNames[key]), node('dd', number(count)));
      });
    }
    $('snapshotId').textContent = `Snapshot: ${snapshot.snapshot_id}`;
    snapshot.sources.forEach((source) => $('sourceHashes').append(node('li', `${source.file} · SHA256 ${source.sha256}${source.row_count === null ? '' : ` · ${number(source.row_count)} records`}`)));
    $('snapshotStatus').textContent = `Approved public aggregates loaded · ${snapshot.run_id || 'run not specified'} · ${number(snapshot.counts.registered_tasks)} task rows. Public snapshot approval is not scientific admission.`;
    $('snapshotStatus').dataset.state = 'ready';
  }
  ['taskSearch', 'stageFilter', 'dispositionFilter', 'packageFilter'].forEach((id) => $(id).addEventListener(id === 'taskSearch' ? 'input' : 'change', () => { state.taskPage = 1; renderTasks(); }));
  $('taskFilters').addEventListener('submit', (event) => event.preventDefault());
  $('taskFilters').addEventListener('reset', () => { setTimeout(() => { state.taskPage = 1; renderTasks(); }, 0); });
  $('assaySearch').addEventListener('input', () => { state.assayPage = 1; renderAssays(); });
  $('assayVerificationFilter').addEventListener('change', () => { state.assayPage = 1; renderAssays(); });
  $('baselineSearch').addEventListener('input', renderBaselines);
  $('baselineFamily').addEventListener('change', renderBaselines);
  $('previousPage').addEventListener('click', () => { state.taskPage -= 1; renderTasks(); });
  $('nextPage').addEventListener('click', () => { state.taskPage += 1; renderTasks(); });
  $('previousAssayPage').addEventListener('click', () => { state.assayPage -= 1; renderAssays(); });
  $('nextAssayPage').addEventListener('click', () => { state.assayPage += 1; renderAssays(); });
  async function load() {
    try {
      const path = document.body.dataset.snapshot;
      if (path !== 'phase2-data/phase2-snapshot.json') throw new Error('Unexpected snapshot target');
      const response = await fetch(path, {cache: 'no-store', credentials: 'omit', redirect: 'error'});
      if (!response.ok) throw new Error('Approved snapshot is unavailable');
      renderSnapshot(validate(await response.json()));
    } catch (_) {
      state.snapshot = null;
      ['assayCards', 'baselineCards', 'sourceHashes', 'previousCounts'].forEach((id) => $(id).replaceChildren());
      const row = node('tr'); const cell = node('td', 'No approved snapshot loaded.');
      cell.colSpan = 4; row.append(cell); $('taskRows').replaceChildren(row);
      ['stageCounts', 'holdCounts'].forEach((id) => $(id).replaceChildren(node('p', 'No compatible audit loaded.')));
      ['stageFilter', 'dispositionFilter', 'packageFilter', 'assayVerificationFilter', 'baselineFamily'].forEach((id) => {
        while ($(id).options.length > 1) $(id).remove(1);
      });
      ['previousPage', 'nextPage', 'previousAssayPage', 'nextAssayPage'].forEach((id) => { $(id).disabled = true; });
      $('taskResultCount').textContent = 'Load an approved snapshot to inspect task rows.';
      $('assayResultCount').textContent = 'No approved assay records loaded.';
      $('baselineResultCount').textContent = 'Protocol catalogue requires an approved compatible snapshot.';
      $('previousSnapshotStatus').textContent = 'No compatible historical technical snapshot loaded.';
      $('snapshotId').textContent = 'Snapshot ID unavailable.';
      $('pageStatus').textContent = 'Page —'; $('assayPageStatus').textContent = 'Page —';
      ['registeredCount', 'assayCount', 'candidateCount', 'admittedCount'].forEach((id) => { $(id).textContent = 'N/A'; });
      $('snapshotStatus').textContent = 'No compatible approved Phase 2 snapshot is available. Build and review the aggregate export, then supply phase2-data/phase2-snapshot.json. Counts remain N/A; no scores are displayed.';
      $('snapshotStatus').dataset.state = 'unavailable';
    }
  }
  load();
})();
