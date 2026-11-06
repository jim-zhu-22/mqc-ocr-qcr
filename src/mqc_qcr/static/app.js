const $ = id => document.getElementById(id);
let active = null, current = null, results = [], pages = [], preview = '';
let selectedArtifact = '', inputMode = 'single', polling = false, configDirty = false;
let publicConfig = null, loadedScore = '', previousScoreCount = 0;
let visibleRules = [], visibleChecks = [], loadedRules = '';
let selectedRuleId = '', rulePage = 1;
const rulePageSize = 10;
const dimensions = ['necessity', 'completeness', 'accuracy', 'uniqueness', 'final'];
const qualityLabels = {NECESSITY:'必要性', COMPLETENESS:'完整性', ACCURACY:'准确性', UNIQUENESS:'唯一性'};
const states = {queued:'排队中', running:'处理中', completed:'已完成', failed:'失败', interrupted:'已中断'};
const stages = {input:'等待处理', ocr:'逐页OCR', sections:'章节切分', rules:'规则提取', compile:'DSL编译', ready_to_score:'可进行评分', scoring:'正在评分', scored:'评分完成'};
const message = (text, error = false) => {
  $('notice').textContent = text;
  $('notice').className = error ? 'notice error' : 'notice';
  if ($('config-dialog').open) {
    $('config-status').textContent = text;
    $('config-status').className = error ? 'inline-status failed' : 'inline-status ok';
  }
};
async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || data.error || data.detail || `HTTP ${response.status}`);
  return data;
}
const jsonOptions = (method, data) => ({method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
function action(id, fn) {
  $(id).addEventListener('click', async () => {
    $(id).disabled = true;
    try { await fn(); } catch (error) { message(error.message, true); }
    finally { $(id).disabled = false; }
  });
}
function setView(view) {
  if (!['ocr','score','rules'].includes(view)) view = 'ocr';
  for (const node of document.querySelectorAll('.view')) node.classList.toggle('active', node.id === 'view-' + view);
  for (const button of document.querySelectorAll('.nav-list [data-view]')) {
    const selected = button.dataset.view === view;
    button.classList.toggle('active', selected);
    if (selected) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  }
  $('page-title').textContent = {ocr:'OCR识别',score:'四性评分',rules:'四性评分 / 规则查找'}[view];
  if (location.hash !== '#' + view) location.hash = view;
}
for (const button of document.querySelectorAll('.nav-list [data-view], [data-open-view]')) button.onclick = () => {
  setView(button.dataset.view || button.dataset.openView); window.scrollTo({top:0});
};
window.addEventListener('hashchange', () => setView(location.hash.slice(1)));
setView(location.hash.slice(1));
function setInputMode(mode) {
  inputMode = mode;
  $('single-input').hidden = mode !== 'single';
  $('batch-input').hidden = mode !== 'batch';
  $('material-count').hidden = mode !== 'batch';
  for (const button of document.querySelectorAll('[data-input]')) {
    button.classList.toggle('active', button.dataset.input === mode);
    button.setAttribute('aria-selected', String(button.dataset.input === mode));
  }
}
for (const button of document.querySelectorAll('[data-input]')) button.onclick = () => setInputMode(button.dataset.input);
$('open-config').onclick = () => $('config-dialog').showModal();
$('close-config').onclick = () => $('config-dialog').close();
$('close-source').onclick = () => $('source-dialog').close();
for (const field of document.querySelectorAll('#config-dialog input')) field.addEventListener('input', () => { configDirty = true; });
function configValue() {
  const data = {};
  for (const kind of ['ocr', 'text']) data[kind] = {
    base_url:$(kind+'-url').value, api_key:$(kind+'-key').value, model:$(kind+'-model').value,
    timeout_seconds:Number($(kind+'-timeout').value), retries:Number($(kind+'-retries').value), max_tokens:Number($(kind+'-tokens').value)
  };
  return data;
}
function configBadge() {
  const ready = publicConfig && ['ocr','text'].every(k => publicConfig[k].base_url && publicConfig[k].model);
  $('api-status').textContent = ready ? '模型API已配置' : '模型API未配置';
}
async function saveConfig() {
  publicConfig = await api('/api/config', jsonOptions('PUT', configValue()));
  configDirty = false;
  configBadge();
  message('模型配置已保存；密钥仅保存在服务内存中。');
}
action('save-config', saveConfig);
action('clear-config', async () => {
  for (const kind of ['ocr','text']) $(kind+'-key').value = '';
  await saveConfig();
  message('内存配置中的密钥已清除。');
});
for (const kind of ['ocr','text']) action('check-'+kind, async () => {
  if (configDirty) await saveConfig();
  message('正在发送连接检查请求…');
  const data = await api('/api/config/check/'+kind, {method:'POST'});
  message(`${kind === 'ocr' ? 'OCR' : '文本'}连接成功：${data.response}`);
});
function modeNote() {
  const replay = $('mode').value === 'replay';
  $('mode-note').textContent = replay ? '重放已保存识别结果，不调用OCR或文本模型。' : '使用配置的视觉与文本模型处理所选文件。';
  $('start').textContent = replay ? '开始演示重放' : '上传并 OCR 识别';
}
$('mode').addEventListener('change', modeNote);
$('document-file').addEventListener('change', () => {
  $('selected-file').textContent = $('document-file').files[0]?.name || '未选择文件';
});
async function startRun(mode) {
  if (mode === 'live') {
    if (configDirty) await saveConfig();
    if (!publicConfig || !['ocr','text'].every(k => publicConfig[k].base_url && publicConfig[k].model)) {
      $('config-dialog').showModal();
      throw new Error('请先填写OCR与文本模型的API地址和模型名称。');
    }
    if (!$('document-file').files[0]) throw new Error('请选择质量控制单PDF或图像。');
  }
  const form = new FormData();
  form.append('mode', mode);
  form.append('document_id', $('document-id').value);
  if (mode === 'live') form.append('file', $('document-file').files[0]);
  const data = await api('/api/runs', {method:'POST', body:form});
  await selectRun(data.run_id);
  message(mode === 'replay' ? '演示控制单已加载；正在重放已保存的识别与规则。' : '识别任务已创建，正在逐页处理。');
}
action('start', () => startRun($('mode').value));
action('start-replay', () => startRun('replay'));
action('go-score', () => {
  if (!active || !current?.revision) throw new Error('请先完成识别或加载演示控制单。');
  setView('score');
  window.scrollTo({top:0, behavior:'smooth'});
});
function clearRunViews() {
  visibleRules = []; visibleChecks = []; loadedRules = ''; selectedRuleId = ''; rulePage = 1;
  $('rules-search').value = ''; $('rules-quality').value = ''; $('rules-status').value = '';
  renderRuleBrowsers();
  current = null; results = []; pages = []; loadedScore = ''; previousScoreCount = 0;
  selectedArtifact = ''; $('details').replaceChildren();
  $('score-history').replaceChildren(new Option('暂无评分', ''));
  $('score-download').hidden = true;
  $('rules-editor').value = '[]';
  $('ocr-page').replaceChildren(new Option('等待识别', ''));
  renderPage(); renderScores();
}
async function selectRun(id) {
  if (active !== id) { active = id; clearRunViews(); }
  await refresh();
}
async function refresh() {
  const data = await api('/api/runs');
  $('runs').replaceChildren();
  $('score-run').replaceChildren(new Option('请选择已解析的控制单', ''));
  $('rules-run').replaceChildren(new Option('请选择已解析的控制单', ''));
  for (const run of data.runs) {
    const button = document.createElement('button');
    button.className = 'run' + (active === run.id ? ' selected' : '');
    button.textContent = `${run.document_id} · ${run.mode === 'replay' ? '演示重放' : '模型识别'}`;
    const meta = document.createElement('small');
    meta.textContent = `${states[run.status] || run.status} / ${stages[run.stage] || run.stage} · ${run.id.slice(0,8)}`;
    button.append(meta);
    button.onclick = () => selectRun(run.id).catch(e => message(e.message, true));
    $('runs').append(button);
    if (run.revision) for (const id of ['score-run','rules-run']) $(id).add(new Option(`${run.document_id} · ${run.id.slice(0,8)} · 规则v${run.revision}`, run.id));
  }
  if (!data.runs.length) {
    const p = document.createElement('p'); p.className = 'empty-state'; p.textContent = '尚未创建质量单解析任务'; $('runs').append(p);
  }
  if (active) await loadRun();
}
action('refresh', refresh);
for (const selector of ['score-run','rules-run']) $(selector).addEventListener('change', async () => {
  try {
    const id = $(selector).value;
    if (id) await selectRun(id);
    else { active = null; clearRunViews(); $('score-run').value = ''; $('rules-run').value = ''; $('score-run-note').textContent = '请选择已解析的控制单。'; }
  } catch (e) { message(e.message, true); }
});
async function loadRun() {
  const rid = active;
  const run = await api('/api/runs/'+rid);
  if (rid !== active) return;
  current = run;
  $('meta-document').textContent = run.document_id;
  $('meta-mode').textContent = run.mode === 'replay' ? '演示重放' : '模型API识别';
  $('meta-status').textContent = `${states[run.status] || run.status} · ${stages[run.stage] || run.stage}`;
  $('meta-revision').textContent = run.revision ? 'v' + run.revision : '等待生成';
  $('run-state').textContent = `任务：${run.id} · ${states[run.status] || run.status}`;
  $('score-run').value = run.revision ? rid : '';
  $('rules-run').value = run.revision ? rid : '';
  $('score-run-note').textContent = `${run.document_id} · 规则v${run.revision} · ${run.mode === 'replay' ? '重放样例' : '模型识别'}。物料控制单编号应与当前控制单一致。`;
  if (run.status === 'failed') message(run.error?.message || '处理失败，请查看阶段错误JSON。', true);
  if (run.revision && run.artifacts.includes(`dsl-v${run.revision}.json`)) await loadVisibleRules();
  if (rid !== active) return;
  $('export').hidden = false; $('export').href = `/api/runs/${rid}/export`;
  $('artifact').replaceChildren(...run.artifacts.map(name => new Option(name,name)));
  selectedArtifact = run.artifacts.includes(selectedArtifact) ? selectedArtifact : (run.artifacts.includes('ocr.json') ? 'ocr.json' : 'run.json');
  $('artifact').value = selectedArtifact;
  await loadArtifact();
  if (run.artifacts.includes('ocr.json')) {
    const ocr = await api(`/api/runs/${rid}/artifacts/ocr.json`);
    if (rid !== active) return;
    pages = ocr.data.pages || [];
    const old = $('ocr-page').value;
    $('ocr-page').replaceChildren(...pages.map(p => new Option(`第 ${p.page_num} 页`, String(p.page_num))));
    $('ocr-page').value = pages.some(p => String(p.page_num) === old) ? old : String(pages[0]?.page_num || '');
    renderPage();
  }
  const oldScore = $('score-history').value;
  $('score-history').replaceChildren(...run.scores.map(s => new Option(`规则v${s.revision} · ${s.id}`,s.artifact)));
  if (run.scores.length) {
    $('score-history').value = run.scores.length === previousScoreCount && run.scores.some(s => s.artifact === oldScore) ? oldScore : run.scores.at(-1).artifact;
    previousScoreCount = run.scores.length;
    await loadScores();
  } else {
    $('score-history').replaceChildren(new Option('暂无评分',''));
    results = []; loadedScore = ''; renderScores();
  }
}
function renderPage() {
  const page = pages.find(p => String(p.page_num) === $('ocr-page').value);
  $('ocr-image').replaceChildren();
  if (!page) {
    const span = document.createElement('span'); span.textContent = '识别后显示对应页图'; $('ocr-image').append(span);
    $('ocr-text').textContent = '尚无识别结果'; $('ocr-page-label').textContent = '等待识别'; return;
  }
  const img = document.createElement('img'); img.src = `/api/runs/${active}/pages/${page.page_num}`; img.alt = `控制单第${page.page_num}页`;
  $('ocr-image').append(img); $('ocr-text').textContent = page.text_content;
  $('ocr-page-label').textContent = `第${page.page_num}页 / 已识别${pages.length}页`;
}
$('ocr-page').addEventListener('change', renderPage);
async function loadArtifact() {
  if (!active) return;
  const rid = active, name = $('artifact').value;
  if (!name) return;
  const data = await api(`/api/runs/${rid}/artifacts/${name}`);
  if (rid !== active || name !== $('artifact').value) return;
  selectedArtifact = name; preview = JSON.stringify(data,null,2); showPreview();
  $('download').hidden = false; $('download').href = `/api/runs/${rid}/artifacts/${name}?download=true`;
}
function showPreview() {
  const term = $('search').value.toLowerCase(), lines = preview.split('\n');
  const matches = term ? lines.filter(l => l.toLowerCase().includes(term)) : lines;
  $('preview').textContent = matches.join('\n'); $('search-count').textContent = term ? `匹配${matches.length}行，下载包含完整内容` : '';
}
$('search').addEventListener('input', showPreview);
$('artifact').addEventListener('change', () => loadArtifact().catch(e => message(e.message,true)));
action('load-sample', async () => {
  const data = await api('/api/samples/input');
  $('materials').value = JSON.stringify(data,null,2);
  $('material-count').textContent = '输入：50条合成物料与合成参考证据';
  setInputMode('batch'); message('50条合成物料已加载，请点击开始四性评分。');
});
$('materials-file').addEventListener('change', async () => {
  try {
    const file = $('materials-file').files[0]; if (!file) return;
    const value = JSON.parse(await file.text()), payload = Array.isArray(value) ? {materials:value,catalog:{}} : value;
    if (!Array.isArray(payload.materials)) throw new Error('输入须为物料数组或含materials的对象。');
    $('materials').value = JSON.stringify(payload,null,2);
    $('material-count').textContent = `输入：${payload.materials.length}条物料`;
    message('物料已导入，需手动发起评分。');
  } catch (e) { message(e.message,true); }
});
function scorePayload() {
  if (inputMode === 'batch') return JSON.parse($('materials').value);
  const evidence = JSON.parse($('single-evidence').value);
  if (!$('material-code').value.trim() && !$('material-description').value.trim()) throw new Error('请至少填写物料编码或物料描述。');
  const material = {
    sample_id:$('material-code').value.trim() || 'SINGLE-001',
    material_code:$('material-code').value.trim(), cn_description:$('material-description').value.trim(),
    level3_category:$('material-entity').value.trim(), model:$('material-model').value.trim(),
    manufacturer:$('material-manufacturer').value.trim(), cn_po_text:$('material-po').value.trim(),
    key_parameters:JSON.parse($('material-parameters').value), kzd:current.document_id,
    source_evidence:evidence.source_evidence || []
  };
  const payload = {materials:[material],catalog:evidence.catalog || {},ml:evidence.ml || {}};
  if (current.mode === 'replay' && current.revision === 1 && evidence.catalog) {
    material._selection_catalog = evidence.catalog;
  }
  if (evidence.dimension_weights) payload.dimension_weights = evidence.dimension_weights;
  return payload;
}
action('score', async () => {
  if (!active || !current?.revision) throw new Error('请先选择已解析的控制单。');
  const data = await api(`/api/runs/${active}/score`,jsonOptions('POST',scorePayload()));
  message(`评分已启动，使用规则v${data.rule_revision}。`); await refresh();
});
async function loadScores() {
  const rid = active, name = $('score-history').value;
  if (!name || loadedScore === `${rid}/${name}`) return;
  const data = await api(`/api/runs/${rid}/artifacts/${name}`);
  if (rid !== active || name !== $('score-history').value) return;
  results = data.data.results; loadedScore = `${rid}/${name}`;
  $('details').replaceChildren();
  $('score-download').hidden = false; $('score-download').href = `/api/runs/${rid}/artifacts/${name}?download=true`;
  renderScores();
}
function renderScores() {
  const term = $('filter-text').value.trim().toLowerCase(), dimension = $('filter-dimension').value;
  const operator = $('filter-operator').value, value = Number($('filter-value').value);
  const filtered = results.filter(r => {
    const matches = `${r.sample_id} ${r.material_code}`.toLowerCase().includes(term);
    const score = r.scores_0_to_1[dimension] * 100;
    return matches && (!operator || (operator === 'below' ? score < value : score > value));
  });
  $('score-summary').textContent = results.length ? `共${results.length}条记录，当前显示${filtered.length}条；分数范围0–100。点击明细查看规则与来源。` : '暂无评分结果';
  const body = $('scores').querySelector('tbody'); body.replaceChildren();
  for (const record of filtered) {
    const row = document.createElement('tr');
    for (const value of [record.sample_id,record.material_code,...dimensions.map(k => (100*record.scores_0_to_1[k]).toFixed(2))]) {
      const td = document.createElement('td'); td.textContent = value; row.append(td);
    }
    row.children[6].className = 'score-value';
    const td = document.createElement('td'), button = document.createElement('button');
    button.className = 'text-btn'; button.textContent = '评分明细';
    button.setAttribute('aria-label', `查看${record.sample_id}评分明细`);
    button.onclick = () => showDetails(record); td.append(button); row.append(td); body.append(row);
  }
  if (!filtered.length) {
    const row = document.createElement('tr'), td = document.createElement('td'); td.colSpan = 8; td.className = 'empty-state';
    td.textContent = results.length ? '没有符合条件的评分记录' : '请选择任务并手动评分'; row.append(td); body.append(row);
  }
}
action('filter-score', renderScores);
$('score-history').addEventListener('change', () => loadScores().catch(e => message(e.message,true)));
function showDetails(record) {
  $('details').replaceChildren();
  const heading = document.createElement('h3'); heading.textContent = `${record.sample_id} · 评分规则明细`; $('details').append(heading);
  for (const d of record.details) {
    const box = document.createElement('div'); box.className = 'check ' + d.result;
    const title = document.createElement('strong'); title.textContent = `${d.dsl_id} · ${d.rule_title}`;
    const p = document.createElement('p');
    p.textContent = `${qualityLabels[d.quality_type] || d.quality_type} · ${d.result === 'PASS' ? '通过' : d.result === 'EXCLUDED' ? '不适用，不进分母' : '计0分'} · ${d.reason}`;
    const button = document.createElement('button'); button.className = 'secondary-btn';
    button.textContent = `查看 ${d.rule_id} / 页 ${d.source_pages.join(', ')}`; button.onclick = () => showSource(d);
    box.append(title,p,button); $('details').append(box);
  }
  $('details').scrollIntoView({behavior:'smooth',block:'start'});
}
function showSource(d) {
  $('source-text').textContent = `${d.rule_title}\n章节 ${d.source_sections.join(', ')}\n${d.source_text}`;
  $('source-pages').replaceChildren();
  for (const page of d.source_pages) {
    const a = document.createElement('a'); a.href = `/api/runs/${active}/pages/${page}`; a.target = '_blank'; a.rel = 'noopener';
    a.textContent = `第 ${page} 页`;
    const img = document.createElement('img'); img.src = a.href; img.alt = `控制单第${page}页`; a.append(img); $('source-pages').append(a);
  }
  $('source-dialog').showModal();
}
async function loadVisibleRules() {
  const rid = active, revision = current.revision, key = `${rid}/${revision}/${current.status}`;
  if (loadedRules === key && !['queued','running'].includes(current.status)) return;
  const [rules, dsl] = await Promise.all([
    api(`/api/runs/${rid}/artifacts/rules-v${revision}.json`),
    api(`/api/runs/${rid}/artifacts/dsl-v${revision}.json`)
  ]);
  if (rid !== active || revision !== current?.revision) return;
  visibleRules = rules.data.rules;
  visibleChecks = dsl.data.dsl;
  loadedRules = key;
  renderRuleBrowsers();
}
const fieldLabels = {material_code:'物料编码', cn_description:'中文描述', cn_po_text:'中文采购文本', en_description:'英文描述', en_po_text:'英文采购文本', manufacturer:'制造商', model:'型号', key_parameters:'关键参数'};
const operatorLabels = {required:'必填', exists:'存在', equals:'等于', contains:'包含', starts_with:'开头为', ends_with:'结尾为', regex:'匹配格式', required_any:'至少一项必填', required_all:'全部必填', regex_any:'至少一项匹配格式', source_consistent:'与指定来源一致', semantic_assertion:'语义核验', identification_complete:'识别信息完整', identity_unique:'身份唯一确定', UNKNOWN:'待人工核实'};
function ruleText(tag, value, className = '') {
  const node = document.createElement(tag); node.textContent = value; node.className = className; return node;
}
function checksForRule(rule) {
  return visibleChecks.filter(check => (check.rule_key || check.source_rule_id) === rule.id);
}
function ruleStatus(rule) {
  const checks = checksForRule(rule);
  return !rule.enabled ? 'disabled' : !checks.length || checks.some(c => c.operator === 'UNKNOWN' || c.execution_status === 'pending_review') ? 'pending' : 'ready';
}
const ruleStatusLabels = {ready:'可执行', pending:'待核实', disabled:'已停用'};
function renderRuleBrowsers() {
  const tokens = $('rules-search').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const quality = $('rules-quality').value, status = $('rules-status').value;
  const filtered = visibleRules.filter(rule => {
    const checks = checksForRule(rule);
    const haystack = [rule.id,rule.rule_title,rule.rule_text,rule.material_entity,rule.condition_text,qualityLabels[rule.quality_type],...checks.flatMap(c => [c.field_name,fieldLabels[c.field_name],c.operator,operatorLabels[c.operator],JSON.stringify(c.expected_value)])].join(' ').toLowerCase();
    return (!quality || rule.quality_type === quality) && (!status || ruleStatus(rule) === status) && tokens.every(term => haystack.includes(term));
  });
  $('rules-version').textContent = loadedRules ? `当前规则 v${loadedRules.split('/')[1]}` : '等待规则生成';
  $('rules-counts').replaceChildren(...Object.entries(qualityLabels).map(([key,label]) => ruleText('span',`${label} ${visibleRules.filter(r => r.quality_type === key).length}`, 'rule-count')));
  $('rules-summary').textContent = loadedRules ? `匹配 ${filtered.length} / 共 ${visibleRules.length} 条` : '请选择已解析的控制单';
  const pageCount = Math.ceil(filtered.length / rulePageSize);
  rulePage = Math.max(1, Math.min(rulePage,pageCount));
  const pageRules = filtered.slice((rulePage-1)*rulePageSize, rulePage*rulePageSize);
  if (!pageRules.some(rule => rule.id === selectedRuleId)) selectedRuleId = pageRules[0]?.id || '';
  const body = $('rules-table').querySelector('tbody'); body.replaceChildren();
  for (const rule of pageRules) {
    const row = document.createElement('tr'); row.className = rule.id === selectedRuleId ? 'selected-rule' : '';
    const idCell = document.createElement('td'), button = ruleText('button',rule.id,'text-btn');
    button.setAttribute('aria-label',`查看规则 ${rule.id}`); button.setAttribute('aria-pressed',String(rule.id === selectedRuleId));
    const select = () => {
      selectedRuleId = rule.id; renderRuleBrowsers();
      $('rules-table').querySelector('[aria-pressed="true"]').focus({preventScroll:true});
      if (window.matchMedia('(max-width:1100px)').matches) $('rule-detail').scrollIntoView({behavior:'smooth',block:'start'});
    };
    button.onclick = event => { event.stopPropagation(); select(); };
    row.onclick = select; idCell.append(button);
    const nameCell = document.createElement('td'); nameCell.append(ruleText('strong',rule.rule_title),ruleText('small',rule.material_entity || '未指定物料'));
    const stateCell = document.createElement('td'); stateCell.append(ruleText('span',ruleStatusLabels[ruleStatus(rule)],'rule-state '+ruleStatus(rule)));
    row.append(idCell,nameCell,ruleText('td',qualityLabels[rule.quality_type] || '待确认'),stateCell); body.append(row);
  }
  if (!pageRules.length) {
    const row = document.createElement('tr'), cell = ruleText('td',loadedRules ? '没有匹配的规则，请更换关键词或清空筛选。' : '请先选择已解析的控制单。','empty-state'); cell.colSpan=4; row.append(cell); body.append(row);
  }
  $('rules-page').textContent = `第 ${pageCount ? rulePage : 0} / ${pageCount} 页 · 每页 ${rulePageSize} 条`;
  $('rules-prev').disabled = rulePage <= 1; $('rules-next').disabled = rulePage >= pageCount;
  renderRuleDetail(pageRules.find(rule => rule.id === selectedRuleId));
}
function renderRuleDetail(rule) {
  const detail = $('rule-detail'); detail.replaceChildren();
  if (!rule) { detail.append(ruleText('p',loadedRules ? '暂无匹配规则' : '选择控制单后，点击列表查看规则详情','empty-state')); return; }
  detail.append(ruleText('span',`${rule.id} · ${qualityLabels[rule.quality_type]}`,'rule-detail-kicker'),ruleText('h2',rule.rule_title));
  const meta = document.createElement('dl'); meta.className='rule-detail-meta';
  for (const [label,value] of [['适用物料',rule.material_entity || '未指定'],['状态',ruleStatusLabels[ruleStatus(rule)]],['权重',rule.weight],['来源页码',rule.source_pages.join('、')]]) {
    const group = document.createElement('div'); group.append(ruleText('dt',label),ruleText('dd',value));meta.append(group);
  }
  detail.append(meta,ruleText('h3','规则内容'),ruleText('p',rule.rule_text,'rule-content'),ruleText('h3','适用条件'),ruleText('p',rule.condition_text || '未设置额外条件，仍需匹配控制单及物料对象。','rule-content'));
  const source = document.createElement('div'); source.className = 'rule-source-bar';
  const sourceButton = ruleText('button','查看控制单原文','secondary-btn'); sourceButton.onclick = () => showSource({...rule,source_text:rule.rule_text});
  source.append(ruleText('span',`来源章节 ${rule.source_sections.join('、')}`),sourceButton); detail.append(source);
  const checks = checksForRule(rule), execution = document.createElement('details'); execution.className='rule-conditions';
  execution.append(ruleText('summary',`判断条件（${checks.length} 项）`));
  if (!checks.length) execution.append(ruleText('p',rule.enabled ? '暂无执行条件，需完成编译后核验。' : '已停用，不参与评分。'));
  for (const check of checks) {
    const box = document.createElement('div'); box.className='rule-check';
    let expected = check.expected_value;
    if (typeof expected === 'string') { try { expected = JSON.parse(expected); } catch {} }
    const value = typeof expected === 'object' ? JSON.stringify(expected,null,2) : String(expected ?? '');
    box.append(ruleText('strong',`${check.dsl_id} · ${fieldLabels[check.field_name] || check.field_name} · ${operatorLabels[check.operator] || check.operator}`),ruleText('p',`字段：${check.field_name}；判断方式：${check.operator}`),ruleText('pre',`预期值：${value || '未设置'}`));
    if (check.offline_handler) box.append(ruleText('p','演示重放使用确定性参考库核验，不调用模型评分。'));
    if (check.semantic) box.append(ruleText('p',check.semantic)); execution.append(box);
  }
  detail.append(execution);
}
for (const [id,event] of [['rules-search','input'],['rules-quality','change'],['rules-status','change']]) $(id).addEventListener(event,() => { rulePage=1; renderRuleBrowsers(); });
$('rules-reset').onclick = () => { $('rules-search').value=''; $('rules-quality').value=''; $('rules-status').value=''; rulePage=1; renderRuleBrowsers(); };
$('rules-prev').onclick = () => { rulePage--; renderRuleBrowsers(); };
$('rules-next').onclick = () => { rulePage++; renderRuleBrowsers(); };
renderRuleBrowsers();

action('load-rules', async () => {
  if (!active || !current?.revision) throw new Error('请选择已解析的控制单。');
  const data = await api(`/api/runs/${active}/artifacts/rules-v${current.revision}.json`);
  $('rules-editor').value = JSON.stringify(data.data.rules,null,2); message('已加载当前规则；修改后保存生成新版本。');
});
action('save-rules', async () => {
  if (!active || !current?.revision) throw new Error('请选择已解析的控制单。');
  const data = await api(`/api/runs/${active}/rules`,jsonOptions('PUT',JSON.parse($('rules-editor').value)));
  message(data.message); await refresh();
});
async function init() {
  await api('/api/health'); $('server-status').textContent = '本地服务已连接'; $('service-dot').classList.add('online');
  publicConfig = await api('/api/config');
  for (const kind of ['ocr','text']) {
    for (const [field,key] of [['url','base_url'],['model','model'],['timeout','timeout_seconds'],['retries','retries'],['tokens','max_tokens']]) $(kind+'-'+field).value = publicConfig[kind][key];
  }
  if (publicConfig.ocr.key_configured || publicConfig.text.key_configured) $('config-status').textContent = '服务内存中已有密钥；修改配置时请重新填写密钥。';
  configBadge(); await refresh();
}
init().catch(e => { $('server-status').textContent = '连接失败'; message(e.message,true); });
setInterval(async () => {
  if (polling || !active || !current || !['queued','running'].includes(current.status)) return;
  polling = true;
  try { await refresh(); } catch (e) { message(e.message,true); } finally { polling = false; }
},1800);
