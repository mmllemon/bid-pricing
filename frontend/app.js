const message = document.querySelector('#message');
const quoteView = document.querySelector('#quoteView');
const moduleView = document.querySelector('#moduleView');
const workbenchView = document.querySelector('#workbenchView');
const modulePages = {
  cost: { icon: '◫', title: '实施成本', subtitle: '归集项目执行阶段的人工、材料、机械和分包成本。', phase: 'Phase 3 · 实施成本', cards: [['成本计划', '建立目标成本与责任成本基线'], ['成本归集', '按清单、合同和实际发生额归集成本'], ['成本偏差', '对比预算成本与实际成本，定位超支项目']] },
  ledger: { icon: '▤', title: '项目台账', subtitle: '统一维护项目基本信息、合同信息和关键节点。', phase: 'Phase 4 · 项目台账', cards: [['项目档案', '集中查看项目基本信息与合同状态'], ['节点跟踪', '记录开工、完工、验收和付款节点'], ['经营指标', '汇总合同额、成本、回款和利润指标']] },
  settlement: { icon: '◴', title: '结算管理', subtitle: '跟踪变更签证、过程计量和最终结算数据。', phase: 'Phase 5 · 结算管理', cards: [['变更签证', '登记变更原因、金额和审批状态'], ['过程计量', '管理申报工程量与审核工程量'], ['结算审核', '核对合同价、调整项和最终结算金额']] },
};
function showModule(module) {
  if (module === 'workbench') {
    quoteView.classList.add('hidden'); moduleView.classList.add('hidden');
    workbenchView.classList.remove('hidden');
    if (window.__wbResurface) window.__wbResurface(); // 切回工作台即重渲染（经营概览重新拉取）
    location.hash = 'workbench';
    return;
  }
  workbenchView.classList.add('hidden');
  const page = modulePages[module];
  if (!page) { quoteView.classList.remove('hidden'); moduleView.classList.add('hidden'); return; }
  quoteView.classList.add('hidden'); moduleView.classList.remove('hidden');
  moduleView.innerHTML = `<div class="breadcrumb">${page.title} / 模块首页</div><header class="page-header"><div><span class="status-pill">${page.phase}</span><h1>${page.title}</h1><p>${page.subtitle}</p></div></header><section class="module-empty"><div class="module-icon">${page.icon}</div><h2>模块正在建设中</h2><p>该模块的页面入口已经建立，后续将接入真实业务数据和操作流程。</p><div class="module-cards">${page.cards.map(([title, text]) => `<article><strong>${title}</strong><span>${text}</span><em>即将上线</em></article>`).join('')}</div><button class="btn-primary module-back" data-module="quote">返回投标报价</button></section>`;
  location.hash = module;
  moduleView.querySelector('.module-back').addEventListener('click', () => selectModule('quote'));
}
function selectModule(module) {
  document.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.module === module));
  if (module === 'quote') { location.hash = ''; quoteView.classList.remove('hidden'); moduleView.classList.add('hidden'); workbenchView.classList.add('hidden'); }
  else showModule(module);
}
document.querySelectorAll('.nav-item').forEach(button => {
  button.addEventListener('click', () => selectModule(button.dataset.module));
});
window.addEventListener('hashchange', () => selectModule(location.hash.slice(1) || 'quote'));
if (location.hash) { const h = location.hash.slice(1); if (h === 'workbench' || h === 'quote' || modulePages[h]) selectModule(h); }
else selectModule('workbench');

/* 侧栏收起：窄屏抽屉式（汉堡按钮 + 遮罩），点导航项/遮罩/Esc 均关闭 */
(function () {
  const shell = document.querySelector('.app-shell');
  const toggle = document.getElementById('sbToggle');
  const backdrop = document.getElementById('sbBackdrop');
  if (!shell || !toggle || !backdrop) return;
  const set = (open) => {
    shell.classList.toggle('sb-open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    toggle.setAttribute('aria-label', open ? '关闭导航菜单' : '打开导航菜单');
  };
  toggle.addEventListener('click', () => set(!shell.classList.contains('sb-open')));
  backdrop.addEventListener('click', () => set(false));
  document.querySelectorAll('.nav-item').forEach(n => n.addEventListener('click', () => set(false)));
  window.addEventListener('keydown', e => { if (e.key === 'Escape') set(false); });
})();

/* 侧栏用户名可自定义：点击后内联编辑，回车/失焦保存（localStorage 持久化，工作台问候同步读取） */
(function () {
  const NAME_KEY = 'gc_user_name';
  const el = document.getElementById('userName');
  if (!el || !window.localStorage) return;
  const saved = localStorage.getItem(NAME_KEY);
  if (saved) el.textContent = saved;
  el.title = '点击修改用户名';
  el.style.cursor = 'text';
  el.onclick = () => {
    const input = document.createElement('input');
    input.type = 'text'; input.maxLength = 20;
    input.value = el.textContent;
    input.className = 'name-input';
    input.style.cssText = 'width:100%;max-width:150px;padding:2px 6px;border:1px solid var(--border-input);border-radius:8px;font-size:13px;font-weight:600;color:var(--text);background:var(--surface-card);font-family:var(--font);outline:none';
    input.addEventListener('focus', () => input.select());
    const commit = () => {
      const v = input.value.trim();
      if (v) localStorage.setItem(NAME_KEY, v);
      el.textContent = v || '未命名';
      input.replaceWith(el);
    };
    const onKey = e => {
      if (e.key === 'Enter') commit();
      else if (e.key === 'Escape') { input.value = ''; commit(); }
    };
    input.addEventListener('blur', commit);
    input.addEventListener('keydown', onKey);
    el.replaceWith(input);
    input.focus();
  };
})();
document.querySelectorAll('.upload-card input').forEach(input => {
  input.addEventListener('change', () => {
    const name = document.querySelector(`[data-for="${input.id}"]`);
    name.textContent = input.files[0] ? input.files[0].name : '选择 Excel 文件';
    name.classList.toggle('selected', Boolean(input.files[0]));
  });
});

let currentPlanId = null;
let plans = [];
let lastResult = null;
let overviewProjects = [];   // 项目经营概览数据集（用于关联与定稿回写）
let activeOverviewId = '';    // 当前关联的经营项目 id（非空才显示定稿回写按钮）
const fmt = (value, digits = 2) => value === null || value === undefined || value === '' ? '—' : Number(value).toFixed(digits);
// 安全转义：所有来自 Excel / 用户输入的字符串在进入 innerHTML 前必须过 esc，防止清单注入。
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const escList = (arr) => (arr || []).map(esc).join('、');

function fillParams(params) {
  if (!params) return;
  const map = { target_total:'targetTotal', fixed_pretax:'fixedPretax', vat_rate:'vatRate', surtax_rate:'surtaxRate', ratio_min:'ratioMin', ratio_max:'ratioMax' };
  Object.entries(map).forEach(([key, id]) => { const el = document.querySelector(`#${id}`); if (params[key] !== undefined) el.value = params[key]; });
  const conf = document.querySelector('#lowRatioConfirmed');
  if (params.low_ratio_confirmed !== undefined) conf.checked = Boolean(params.low_ratio_confirmed);
  const by = document.querySelector('#lowPriceConfirmedBy');
  if (params.low_price_confirmed_by !== undefined) by.value = params.low_price_confirmed_by || '';
  // H-002：恢复成本税口径（抵扣方式 + 分项构成）
  const m = document.querySelector('#taxMode');
  if (m && params.input_vat_credit_mode) m.value = params.input_vat_credit_mode;
  if (params.cost_composition) applyComposition(params.cost_composition);
  else renderCompositionRows();
  toggleComposeWrap();
  updateCompositionLive();
}

function renderPreview(res) {
  const panel = document.querySelector('#previewPanel');
  document.querySelector('#resultPanel').classList.add('hidden');
  const uw = (ws) => Object.entries(ws).map(([k, v]) => `${k}(${v}行)`).join('、') || '—';
  const chip = (k, label) => `<span style="${res.fields[k] ? 'color:var(--success);font-weight:600' : 'color:var(--warn);font-weight:600'}">${label}${res.fields[k] ? '✓' : '−'}</span>`;
  const m = res.match;
  panel.innerHTML = `<div class="result-head"><div><h3>导入资料预览</h3><p>项目：${esc(res.project_id)} ｜ 优化前核对：行数 / 字段 / 匹配覆盖 / 异常 / 文件哈希</p></div></div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px;margin-top:10px;">
    <div style="padding:10px;background:var(--surface-nested);border:1px solid var(--border);border-radius:8px;"><b>限价清单</b><br>${res.cap.rows} 行 ｜ ${esc(uw(res.cap.unit_works))}<br><small style="color:var(--text-tertiary)">哈希 ${esc(res.cap.hash_sha256 || '—')}</small></div>
    <div style="padding:10px;background:var(--surface-nested);border:1px solid var(--border);border-radius:8px;"><b>成本清单</b><br>${res.cost.rows} 行 ｜ ${esc(uw(res.cost.unit_works))}<br><small style="color:var(--text-tertiary)">哈希 ${esc(res.cost.hash_sha256 || '—')}</small></div>
    <div style="padding:10px;background:var(--surface-nested);border:1px solid var(--border);border-radius:8px;"><b>匹配覆盖</b><br>master ${m.master_keys} 键：匹配 ${m.matched}、仅限价 ${m.only_cap}、仅成本 ${m.only_cost}${m.blocked ? '<br><strong style="color:var(--danger)">重复 key 已阻断，禁止自动合并</strong>' : ''}</div>
    <div style="padding:10px;background:var(--surface-nested);border:1px solid var(--border);border-radius:8px;"><b>可优化 / 人工</b><br>可优化 ${res.optimizable_count} 项 ｜ 人工 ${res.manual_count} 项${res.missing_cap_ids.length ? `<br><small style="color:var(--warn)">无最高限价：${escList(res.missing_cap_ids)}</small>` : ''}${res.missing_cost_ids.length ? `<br><small style="color:var(--warn)">缺成本锚点：${escList(res.missing_cost_ids)}</small>` : ''}${res.duplicate_item_id_across_unit_work.length ? `<br><strong style="color:var(--danger)">跨单位工程重复编码：${escList(res.duplicate_item_id_across_unit_work)}（优化将被阻断）</strong>` : ''}</div>
    <div style="padding:10px;background:var(--surface-nested);border:1px solid var(--border);border-radius:8px;"><b>字段适配</b><br>${chip('item_id', '编码')} ${chip('item_name', '名称')} ${chip('unit', '单位')} ${chip('q0', '工程量')} ${chip('cap', '限价')} ${chip('q1_point', '结算量')} ${chip('c_i', '成本')}</div>
    <div style="padding:10px;background:var(--surface-nested);border:1px solid var(--border);border-radius:8px;"><b>异常</b> ${res.anomaly_count} 条${res.anomalies.length ? `：${res.anomalies.map(a => `${esc(a.kind)}@${esc(a.item_id)}`).join('、')}` : ''}<br><small style="color:var(--text-tertiary)">仅限价侧 ${res.match.only_cap_ids.length ? '：' + escList(res.match.only_cap_ids) : '—'}</small></div>
    </div>`;
  panel.classList.remove('hidden');
}

function renderResult(result, { savedPlan = false } = {}) {
  const panel = document.querySelector('#resultPanel'); panel.classList.remove('hidden');
  document.querySelector('#previewPanel').classList.add('hidden');
  const rows = result.items || [];
  const savedPill = savedPlan ? '<span class="plan-saved-pill">方案已保存</span>' : '';
  // 下载兜底：历史方案 result 可能未带 excel_download_url，按 plan_id 推导
  const dlUrl = result.excel_download_url || (result.plan_id ? '/api/quote/download/' + result.plan_id : '');
  panel.innerHTML = `<div class="result-head"><div><h3>报价结果明细${savedPill}</h3><p>共 ${result.item_count ?? rows.length} 个优化项目${result.manual_item_count ? `，另有 ${result.manual_item_count} 个项目需人工报价` : ''}${result.low_ratio_review_required ? '，存在低于50%的报价比率' : ''}</p></div><div class="download-actions"><a class="download-button" href="${dlUrl ? 'http://localhost:8000' + esc(dlUrl) : '#'}" ${dlUrl ? `download="${esc(dlUrl.split('/').pop())}"` : ''}>下载 Excel</a><button class="btn-secondary" id="downloadResult">下载 JSON</button>${activeOverviewId ? '<button class="btn-primary" id="finalizeBid" title="将目标总报价写回为该项目投标报价金额，竞争性预算写回为投标成本测算">定稿并回写项目</button>' : ''}</div></div><div class="table-wrap"><table><thead><tr><th>项目编码</th><th>项目名称</th><th>单位</th><th class="num">工程量</th><th class="num">结算量</th><th class="num">含税成本单价</th><th>成本税口径</th><th class="num">有效成本单价</th><th class="num">最高限价</th><th class="num">最优报价单价</th><th class="num">报价比率</th><th class="num">报价合价</th><th class="num">单项毛利</th><th>状态</th><th>说明</th></tr></thead><tbody>${rows.map(row => `<tr class="${row['报价状态'] === 'MANUAL_REVIEW' ? 'manual-row' : ((Number(row['单项毛利'] ?? 0) < 0 || Number(row['报价比率'] ?? 1) < 0.5) ? 'loss-row' : '')}"><td>${esc(row['项目编码'] ?? '')}</td><td title="${esc(row['项目名称'] ?? '')}">${esc(row['项目名称'] ?? '')}</td><td>${esc(row['单位'] ?? '—')}</td><td class="num">${fmt(row['工程量'],3)}</td><td class="num">${fmt(row['成本工程量'],3)}</td><td class="num">${fmt(row['含税成本单价'])}</td><td>${esc(row['成本税口径'] ?? '')}</td><td class="num">${fmt(row['有效成本单价'])}</td><td class="num">${fmt(row['最高限价'])}</td><td class="num price-cell">${fmt(row['最优报价单价'])}</td><td class="num">${row['报价比率'] == null ? '' : fmt(Number(row['报价比率'])*100,2) + '%'}</td><td class="num">${fmt(row['报价合价'])}</td><td class="num">${fmt(row['单项毛利'])}</td><td>${row['报价状态'] === 'MANUAL_REVIEW' ? '人工报价' : ((Number(row['单项毛利'] ?? 0) < 0 || Number(row['报价比率'] ?? 1) < 0.5) ? '需复核' : '通过')}</td><td>${esc(row['说明'] ?? '')}</td></tr>`).join('')}</tbody></table></div>`;
  document.querySelector('#downloadResult').addEventListener('click', () => { const blob = new Blob([JSON.stringify(result,null,2)], {type:'application/json'}); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = '报价结果_结算调整版.json'; link.click(); URL.revokeObjectURL(link.href); });
  const finBtn = document.querySelector('#finalizeBid');
  if (finBtn) finBtn.addEventListener('click', () => { finalizeToOverview(targetTotalVal(), result); });
}

// 读取当前目标总报价输入（含占位兜底），toFixed(2) 格式化
function targetTotalVal() { return Number(numVal('targetTotal')); }

// 警告：定稿只把投标报价金额写回项目经营概览，投标成本测算由用户在概览手动填写，不回写。
async function finalizeToOverview(bidAmount, result) {
  const ok = await new Promise(res => {
    const body = `将本次目标总报价 <b>${Number(bidAmount).toLocaleString('zh-CN',{minimumFractionDigits:2})}</b> 元写回为「${activeOverviewProjects && activeOverviewProjects[activeOverviewId] ? esc(activeOverviewProjects[activeOverviewId].name) : ''}」的投标报价金额？投标成本测算不随本次回写，请在「项目经营概览」中手动填写。`;
    const modal = document.createElement('div');
    modal.className = 'modal-mask';
    modal.innerHTML = `<div class="modal"><h3>确认定稿并回写</h3><p>${body}</p><div class="modal-actions"><button class="btn-secondary" id="finCancel">取消</button><button class="btn-primary" id="finOk">确认回写</button></div></div>`;
    modal.addEventListener('click', e => { if (e.target === modal) { close(); res(false); } });
    const close = () => modal.remove();
    document.body.appendChild(modal);
    modal.querySelector('#finCancel').addEventListener('click', () => { close(); res(false); });
    modal.querySelector('#finOk').addEventListener('click', () => { close(); res(true); });
  });
  if (!ok) return;
  try {
    const data = new FormData();
    data.append('id', activeOverviewId);
    data.append('bid_amount', bidAmount);
    const resp = await fetch('http://localhost:8000/api/project/overview/finalize', {method:'POST', body:data});
    const res = await resp.json();
    if (!resp.ok || res.status !== 'PASS') throw new Error(res.reason || '回写未通过');
    if (activeOverviewProjects[activeOverviewId]) activeOverviewProjects[activeOverviewId].bid_amount = bidAmount;
    setMessage(`已定稿并回写项目经营概览：该项目的投标报价金额已更新为 <b>${Number(bidAmount).toLocaleString('zh-CN',{minimumFractionDigits:2})}</b> 元。投标成本测算请到「项目经营概览」手动填写。`, 'success');
    // 定稿成功后，把当前方案标记为『已定稿』，方案卡片显示徽标，防止误删。
    // write=0：投标报价金额刚已手动回写，避免 mark 再次按方案存储值二次覆盖（值不一致/跨项目污染）。
    if (currentPlanId) {
      try {
        await fetch(`http://localhost:8000/api/project/mark-finalized?id=${encodeURIComponent(currentPlanId)}&write=0`, {method:'POST'});
        refreshPlans();
      } catch (e) { /* 标记失败不阻断回写 */ }
    }
  } catch (error) {
    setMessage(`定稿回写失败：${error.message}`, 'error');
  }
}

// 从项目经营概览拉取处于投标阶段的项目，填入「关联投标项目」自定义下拉；选中后带入目标总报价（取项目投标报价金额，元）。
// 下拉 value 存项目真实 id（UUID，作为项目唯一凭证），label 显示项目名；提交时 project_id=id、project_name=名。
let activeOverviewProjects = {};
let nameToId = {};   // 项目名 → 真实 id，用于旧方案（project_id=名称）归一化
async function loadBidProjectOptions() {
  try {
    const resp = await fetch('http://localhost:8000/api/project/overview/list');
    if (!resp.ok) return;
    const res = await resp.json();
    if (!res.projects) return;
    overviewProjects = (res.projects || []).filter(p => (p.stage || '') === '投标');
    activeOverviewProjects = {}; nameToId = {};
    const opts = [{ value: '', label: '— 选择投标项目 —' }];
    overviewProjects.forEach(p => { activeOverviewProjects[p.id] = p; nameToId[p.name] = p.id; opts.push({ value: p.id, label: p.name }); });
    const sel = document.querySelector('#projectId');
    if (!sel) return;
    if (sel.__cs) sel.__cs.setOptions(opts);
    else { sel.innerHTML = opts.map(o => '<option value="' + esc(o.value) + '">' + esc(o.label) + '</option>').join(''); initCustomSelect('#projectId'); }
    const apply = () => {
      const hit = overviewProjects.find(p => p.id === sel.value);
      activeOverviewId = hit ? hit.id : '';
      const tEl = document.querySelector('#targetTotal');
      if (hit && tEl && hit.bid_amount != null && hit.bid_amount !== '') tEl.value = Number(hit.bid_amount).toFixed(2);
    };
    sel.addEventListener('change', apply);
    apply();
  } catch (e) { /* 后端未启动时静默降级为手动填写 */ }
}
// 当前选中的关联项目：{uuid, name}
function selectedOverviewProject() {
  const sel = document.querySelector('#projectId');
  if (!sel) return { uuid: '', name: '' };
  const idx = sel.selectedIndex;
  const name = idx > 0 && sel.options[idx] ? sel.options[idx].text : '';
  return { uuid: sel.value, name };
}
loadBidProjectOptions();

// H-002：成本构成面板初始化见文件末尾（须在所有 const 定义之后执行，避免 TDZ）。

// H-002：结果提示里必须交代「这个利润是按哪个成本口径算的」。
// 成本清单综合单价是含税口径，限价与报价是不含税口径；不说明换算方式，
// 读结果的人无法判断毛利是否被低估——这正是 H-002 要根除的口径含糊。
function costBasisNote(result) {
  const tax = result && result.cost_input_tax;
  if (!tax) return '';
  const parts = [];
  if (tax.input_vat_credit_mode) parts.push(`抵扣方式 ${esc(String(tax.input_vat_credit_mode))}`);
  if (tax.cost_composition && tax.cost_composition.length) parts.push(`分项构成 ${tax.cost_composition.length} 项精算`);
  if (tax.credit_ratio != null) parts.push(`可抵扣占比 ${(Number(tax.credit_ratio) * 100).toFixed(1)}%`);
  if (tax.multiplier != null) parts.push(`换算系数 k=${Number(tax.multiplier).toFixed(6)}`);
  return `成本已由含税换算为不含税有效成本（${parts.join('，') || '见结果 JSON'}）。`;
}

// ---- H-002：成本构成（分项多税率精算）前端 ----
// 默认构成匹配 config/project_quote_policy.json 的 cost_composition；
// 用户可在前端逐项目自定义，提交时作为覆盖优先于 config 默认。
const COMP_DEFAULTS = [
  {key:'goods', label:'材料设备', proportion:0.65, input_vat_rate:0.13},
  {key:'service', label:'劳务及措施', proportion:0.35, input_vat_rate:0.09},
];

function _composeRowsHtml(comp) {
  return comp.map(c => `
    <div class="compose-row">
      <span class="comp-label">${esc(c.label || c.key || '')}</span>
      <input class="comp-prop" type="number" step="0.01" min="0" max="100" value="${(Number(c.proportion) * 100).toFixed(0)}" data-key="${esc(c.key || '')}" data-field="proportion" />
      <input class="comp-rate" type="number" step="0.01" min="0" max="100" value="${(Number(c.input_vat_rate) * 100).toFixed(0)}" data-key="${esc(c.key || '')}" data-field="rate" />
    </div>`).join('');
}

function renderCompositionRows() {
  document.querySelector('#composeRows').innerHTML = _composeRowsHtml(COMP_DEFAULTS);
  document.querySelectorAll('#composeRows input').forEach(el => el.addEventListener('input', updateCompositionLive));
}

function applyComposition(comp) {
  if (!Array.isArray(comp) || !comp.length) { renderCompositionRows(); return; }
  document.querySelector('#composeRows').innerHTML = _composeRowsHtml(comp);
  document.querySelectorAll('#composeRows input').forEach(el => el.addEventListener('input', updateCompositionLive));
}

function toggleComposeWrap() {
  const mode = document.querySelector('#taxMode').value;
  const wrap = document.querySelector('#composeWrap');
  if (mode === 'NONE') wrap.classList.add('hidden');
  else wrap.classList.remove('hidden');
}

function updateCompositionLive() {
  const mode = document.querySelector('#taxMode').value;
  const sumEl = document.querySelector('#composeSum');
  const kEl = document.querySelector('#composeK');
  if (mode === 'NONE') {
    sumEl.textContent = '占比合计：—（不可抵扣，不读构成）';
    sumEl.className = 'compose-sum';
    kEl.textContent = '换算系数 k = 1.000000（含税即有效成本）';
    return;
  }
  let total = 0, credit = 0, k = 1.0;
  document.querySelectorAll('#composeRows .compose-row').forEach(row => {
    const p = Number(row.querySelector('[data-field="proportion"]').value) / 100;
    const r = Number(row.querySelector('[data-field="rate"]').value) / 100;
    if (!Number.isNaN(p)) total += p;
    if (!Number.isNaN(p) && !Number.isNaN(r)) {
      if (r > 0) credit += p;
      k -= p * r / (1 + r);
    }
  });
  const sumOk = Math.abs(total - 1) < 0.005;
  const dev = ((total - 1) * 100);
  sumEl.textContent = `占比合计：${(total * 100).toFixed(1)}%${sumOk ? '' : '（须=100%' + (Math.abs(dev) >= 0.05 ? `，偏差 ${dev > 0 ? '+' : ''}${dev.toFixed(1)}%` : '') + '）'}`;
  sumEl.className = 'compose-sum ' + (sumOk ? 'ok' : 'bad');
  kEl.textContent = `可抵扣占比 ${(credit * 100).toFixed(1)}% ｜ 换算系数 k = ${k.toFixed(6)}`;
}

// 汇总当前表单的税口径覆盖，返回注入 FormData 的字段。
function readTaxOverride() {
  const mode = document.querySelector('#taxMode').value;
  if (mode === 'NONE') {
    return {mode, creditRatio: 0, compositionJson: ''};
  }
  const comp = [];
  document.querySelectorAll('#composeRows .compose-row').forEach(row => {
    const p = Number(row.querySelector('[data-field="proportion"]').value) / 100;
    const r = Number(row.querySelector('[data-field="rate"]').value) / 100;
    comp.push({
      key: row.querySelector('[data-field="proportion"]').dataset.key || row.querySelector('.comp-label').textContent,
      label: row.querySelector('.comp-label').textContent,
      proportion: Number.isNaN(p) ? 0 : p,
      input_vat_rate: Number.isNaN(r) ? 0 : r,
    });
  });
  let credit = 0;
  comp.forEach(c => { if (c.input_vat_rate > 0) credit += c.proportion; });
  return {mode, creditRatio: credit, compositionJson: JSON.stringify(comp)};
}

function setMessage(text, kind = '') { message.className = kind ? `message ${kind}` : 'message'; message.innerHTML = text; }

// 即时校验：比率区间非法在提交前拦截，并给对应输入框加错误态/焦点，避免空跑服务端再 422。
function clearInvalid() { document.querySelectorAll('.invalid').forEach(el => { el.classList.remove('invalid'); el.removeAttribute('aria-invalid'); }); }
function markInvalid(el, msg) { el.classList.add('invalid'); el.setAttribute('aria-invalid', 'true'); el.focus(); setMessage(msg, 'error'); }
function validateParams() {
  clearInvalid();
  const loEl = document.querySelector('#ratioMin'); const hiEl = document.querySelector('#ratioMax');
  const lo = Number(loEl.value); const hi = Number(hiEl.value);
  if (Number.isNaN(lo) || lo < 0 || lo > 1) { markInvalid(loEl, '单项报价比率下限非法：须为 0～1 之间的数值。'); return false; }
  if (Number.isNaN(hi) || hi > 1 || hi < lo) { markInvalid(hiEl, `报价比率区间非法：上限须 ≥ 下限（${lo}）且 ≤ 1.00。`); return false; }
  // 税率采用小数口径（0.09 = 9%），必须落在 (0, 1]，避免把 9 当作 9% 变成 900%
  const vtEl = document.querySelector('#vatRate'); const stEl = document.querySelector('#surtaxRate');
  const vt = Number(vtEl.value); const st = Number(stEl.value);
  if (Number.isNaN(vt) || vt <= 0 || vt > 1) { markInvalid(vtEl, '增值税率须为 0～1 之间的小数（如 0.09 表示 9%）。'); return false; }
  if (Number.isNaN(st) || st <= 0 || st > 1) { markInvalid(stEl, '附加税率须为 0～1 之间的小数（如 0.12 表示 12%）。'); return false; }
  return true;
}
// 比率输入实时校验：输完即标红，不必等提交
document.querySelectorAll('#ratioMin,#ratioMax').forEach(el => el.addEventListener('input', validateParams));
// 读取数字输入：留空时回落到浅灰占位默认值（目标总报价/固定税前项）
function numVal(id) { const el = document.querySelector(`#${id}`); return el.value.trim() !== '' ? el.value : el.placeholder; }

document.querySelector('#previewBtn').addEventListener('click', async () => {
  const cap = document.querySelector('#capFile').files[0];
  const cost = document.querySelector('#costFile').files[0];
  if (!cap || !cost) { setMessage('请先上传限价清单和成本清单。'); return; }
  const button = document.querySelector('#previewBtn');
  button.disabled = true; button.setAttribute('aria-busy', 'true'); button.innerHTML = '预览中…'; setMessage('正在识别文件并核对导入资料，请稍候。');
  const data = new FormData();
  data.append('limit_file', cap); data.append('cost_file', cost);
  const ovp = selectedOverviewProject();
  data.append('project_id', ovp.uuid); data.append('project_name', ovp.name);
  try {
    const response = await fetch('http://localhost:8000/api/quote/preview', {method:'POST', body:data});
    const res = await response.json();
    if (!response.ok || res.status !== 'PASS') throw new Error(res.reason || '预览未通过');
    renderPreview(res);
    setMessage(`预览完成：限价 ${res.cap.rows} 行、成本 ${res.cost.rows} 行，可优化 ${res.optimizable_count} 项。`, 'success');
  } catch (error) {
    setMessage(`预览失败：${error.message}`, 'error');
  } finally { button.disabled = false; button.removeAttribute('aria-busy'); button.innerHTML = '预览导入资料'; }
});

document.querySelector('#calculateBtn').addEventListener('click', async () => {
  const cap = document.querySelector('#capFile').files[0];
  const cost = document.querySelector('#costFile').files[0];
  if (!validateParams()) return;
  if (!cap || !cost) { setMessage('请先上传限价清单和成本清单。'); return; }
  const button = document.querySelector('#calculateBtn');
  button.disabled = true; button.setAttribute('aria-busy', 'true'); button.innerHTML = '正在计算…'; setMessage('正在识别清单并运行 Phase 2 MILP，请稍候。');
  const data = new FormData();
  data.append('limit_file', cap); data.append('cost_file', cost);
  const fields = {project_id:'projectId', target_total:'targetTotal', fixed_pretax:'fixedPretax', vat_rate:'vatRate', surtax_rate:'surtaxRate', ratio_min:'ratioMin', ratio_max:'ratioMax'};
  Object.entries(fields).forEach(([name, id]) => data.append(name, numVal(id)));
  data.append('project_name', selectedOverviewProject().name);
  data.append('overview_id', activeOverviewId);
  data.append('low_ratio_confirmed', document.querySelector('#lowRatioConfirmed').checked ? 'true' : 'false');
  data.append('low_price_confirmed_by', (document.querySelector('#lowPriceConfirmedBy') || {}).value || '');
  data.append('clause_enabled', document.querySelector('#clauseEnabled').checked ? 'true' : 'false');
  // H-002：成本税口径（分项构成）覆盖，优先于 config 默认
  const taxCalc = readTaxOverride();
  data.append('input_vat_credit_mode', taxCalc.mode);
  data.append('cost_input_vat_rate', '0.13');
  data.append('credit_ratio', taxCalc.creditRatio);
  data.append('cost_composition', taxCalc.compositionJson);
  try {
    const response = await fetch('http://localhost:8000/api/quote/optimize', {method:'POST', body:data});
    const result = await response.json();
    if (!response.ok || result.status !== 'PASS') {
      // H-002：成本税口径未声明时后端在**出数之前**阻断；把原因与「该怎么办」
      // 一并展示，避免用户只看到一句无法行动的报错。
      const hint = result.cost_input_tax && result.cost_input_tax.user_hint;
      const err = new Error(result.reason || '计算未通过');
      err.hint = hint || '';
      throw err;
    }
    currentPlanId = result.plan_id || null;
    lastResult = result;
    setMessage(`计算完成：竞争性预算 <b>${Number(result.competitive_budget).toLocaleString('zh-CN',{minimumFractionDigits:2})}</b> 元，结算调整后利润（不含增值税）<b>${Number(result.objective).toLocaleString('zh-CN',{minimumFractionDigits:2})}</b> 元。${costBasisNote(result)}${result.low_ratio_review_required ? '<br><strong>警告：存在低于50%的报价比率，请人工复核招标文件条款。系统未作出废标判定，以招标文件为准；已记录确认留痕（确认人/时间/条款依据，见结果 JSON）。</strong>' : ''}`, 'success');
    renderResult(result, { savedPlan: Boolean(currentPlanId) });
    refreshPlans();
  } catch (error) {
    setMessage(`计算失败：${error.message}${error.hint ? `<br>${esc(error.hint)}` : ''}`, 'error');
  } finally { button.disabled = false; button.removeAttribute('aria-busy'); button.innerHTML = '重新计算 <span>→</span>'; }
});

// ---- 自定义下拉：毛玻璃选项面板，替代原生 select ----
function initCustomSelect(selId) {
  const sel = document.querySelector(selId);
  if (!sel || sel.__cs) return sel;
  sel.classList.add('cs-hidden');                 // 隐藏原生 select，仍保留为 value 载体
  const wrap = document.createElement('div');
  wrap.className = 'cs';
  wrap.innerHTML =
    '<button type="button" class="cs-trigger" aria-haspopup="listbox">' +
    '<span class="cs-label"></span>' +
    '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8l4 4 4-4"/></svg>' +
    '</button>' +
    '<ul class="cs-list hidden" role="listbox"></ul>';
  sel.parentNode.insertBefore(wrap, sel.nextSibling);
  const label = wrap.querySelector('.cs-label');
  const list = wrap.querySelector('.cs-list');
  const trigger = wrap.querySelector('.cs-trigger');
  let data = [];

  function populate() {
    list.innerHTML = '';
    data.forEach((o, i) => {
      const li = document.createElement('li');
      li.className = 'cs-opt' + (o.value === sel.value ? ' cs-selected' : '');
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', String(o.value === sel.value));
      li.dataset.i = String(i);
      li.textContent = o.label;                    // textContent：防注入
      list.appendChild(li);
    });
  }
  function render() {
    const hit = data.find(o => o.value === sel.value);
    label.textContent = hit ? hit.label : (sel.value || '— 请选择 —');
  }
  function close() { list.classList.add('hidden'); wrap.classList.remove('open'); document.removeEventListener('click', onDoc); }
  function open() { populate(); render(); list.classList.remove('hidden'); wrap.classList.add('open'); setTimeout(() => document.addEventListener('click', onDoc), 0); }
  function onDoc(e) { if (!wrap.contains(e.target)) close(); }

  trigger.addEventListener('click', e => { e.stopPropagation(); wrap.classList.contains('open') ? close() : open(); });
  list.addEventListener('click', e => {
    const li = e.target.closest('.cs-opt');
    if (!li) return;
    const o = data[+li.dataset.i];
    if (o && o.value !== sel.value) {
      sel.value = o.value; render();
      sel.dispatchEvent(new Event('change', { bubbles: true }));
    }
    close();
  });

  data = Array.from(sel.options).map(o => ({ value: o.value, label: o.textContent }));
  render();
  sel.__cs = {
    setOptions(opts) {
      data = opts || [];
      // 先记住重建前的选中值：清空 sel.innerHTML 会把 sel.value 重置为 ''，
      // 而占位符 option 的 value 也是 ''，会导致『当前值有效』误判、回读丢失。
      const prev = sel.value;
      sel.innerHTML = '';
      data.forEach(o => { const op = document.createElement('option'); op.value = o.value; op.textContent = o.label; sel.appendChild(op); });
      // 新数据里仍在则还原选中，否则落回首个(占位符)选项。
      if (data.some(o => o.value === prev)) sel.value = prev;
      else if (data[0]) sel.value = data[0].value;
      render();
    },
    refresh: render
  };
  return sel;
}
initCustomSelect('#planSelect');
initCustomSelect('#baseSelect');

// ---- 方案库：下拉选项目 → 下方列该项目方案卡片，卡片可打开/删除 ----
let planGroups = [];       // [{name, plan_count, plans:[summary]}]
let curProject = '';       // 当前选中的项目名（用 JS 变量持有，避免依赖脆弱的下拉值回读）
let selectedPlanId = '';   // 当前选中的方案卡片 id

// 应用内确认框：删除只在用户明确点「确认删除」后才执行。
// 不依赖原生 confirm——某些环境下原生 confirm 会被浏览器静默拦截/自动放行，
// 造成「还没点确定就删了」的误删。返回 Promise<boolean>。
function uiConfirm(message, options = {}) {
  return new Promise(resolve => {
    let ov = document.getElementById('ui-confirm');
    if (ov) ov.remove();
    ov = document.createElement('div');
    ov.id = 'ui-confirm';
    ov.className = 'ui-confirm-overlay' + (options.danger ? ' danger' : '');
    ov.innerHTML = `<div class="ui-confirm-box" role="alertdialog" aria-modal="true" aria-label="${options.danger ? '删除已定稿方案' : '确认删除'}">
      ${options.danger ? '<div class="ui-confirm-title">删除已定稿方案</div><div class="ui-confirm-sub">该方案已定稿并回写项目，删除后需重新计算与回写，请谨慎操作。</div>' : ''}
      <div class="ui-confirm-msg">${esc(message)}</div>
      <div class="ui-confirm-actions">
        <button type="button" class="btn-ghost" data-act="cancel">取消</button>
        <button type="button" class="btn-danger" data-act="ok">${options.danger ? '仍要删除' : '确认删除'}</button>
      </div></div>`;
    document.body.appendChild(ov);
    const done = val => { ov.remove(); resolve(val); };
    ov.querySelector('[data-act="cancel"]').addEventListener('click', () => done(false));
    ov.querySelector('[data-act="ok"]').addEventListener('click', () => done(true));
    ov.addEventListener('mousedown', e => { if (e.target === ov) done(false); });
  });
}

async function refreshPlans() {
  try {
    const res = await (await fetch('http://localhost:8000/api/project/list')).json();
    if (!res || res.status !== 'PASS') throw new Error('列表加载失败');
    planGroups = res.projects || [];
    // 对比功能仍需要全量扁平方案列表：[(group…) => flatten]
    plans = planGroups.flatMap(g => (g.plans || []));
    renderProjectOptions();
    renderPlanCards();
  } catch (error) { setMessage(`方案列表加载失败：${error.message}`, 'error'); }
}

function renderProjectOptions() {
  const select = document.querySelector('#planSelect');
  if (!select || !select.__cs) return;
  // 当前项目仍在方案库则保持选中；若其方案已被删空（从列表消失），
  // 自动落到剩余第一个项目，而不是回到『未选择项目』占位符让用户重选。
  if (!planGroups.some(g => g.name === curProject)) {
    curProject = planGroups.length ? planGroups[0].name : '';
  }
  select.value = curProject;
  select.__cs.setOptions([{ value: '', label: '— 选择项目 —' }].concat(planGroups.map(g => ({
    value: g.name,
    label: `${g.name}（${g.plan_count} 个方案）`
  }))));
}

function currentProjectPlans() {
  const g = planGroups.find(x => x.name === curProject);
  return g ? (g.plans || []) : [];
}

function renderPlanCards() {
  const box = document.querySelector('#planCards');
  if (!box) return;
  if (!curProject) {
    box.innerHTML = '<p class="hint">请在上方选择一个项目，查看其已保存的方案。</p>';
    selectedPlanId = '';
    return;
  }
  const list = currentProjectPlans();
  if (!list.length) {
    box.innerHTML = '<p class="hint">该项目暂无已保存方案。执行「识别文件并计算」成功后会自动保存。</p>';
    selectedPlanId = '';
    return;
  }
  if (!list.some(p => p.id === selectedPlanId)) selectedPlanId = list[0].id;
  box.innerHTML = list.map(p => {
    const sel = p.id === selectedPlanId ? ' sel' : '';
    const finalized = p.finalized ? ' finalized' : '';
    const badge = p.finalized ? '<span class="plan-card-badge" title="此方案已定稿，删除功能已锁定，请先取消定稿">已定稿 · 锁定</span>' : '';
    const budget = p.competitive_budget != null ? Number(p.competitive_budget).toLocaleString('zh-CN',{minimumFractionDigits:2}) : '—';
    const profit = p.objective != null ? Number(p.objective).toLocaleString('zh-CN',{minimumFractionDigits:2}) : '—';
    const quoteAmt = p.target_total != null ? Number(p.target_total).toLocaleString('zh-CN',{minimumFractionDigits:2}) : '—';
    return `<div class="plan-card${sel}${finalized}" data-id="${esc(p.id)}" tabindex="0" role="button" aria-label="打开方案 ${esc(p.id)}">
      <div class="plan-card-main">
        <div class="plan-card-title">${esc(p.name || p.id)}${badge}<span class="plan-card-meta">项数 ${p.item_count}</span></div>
        <div class="plan-card-info">投标报价 <b>${quoteAmt}</b> 元 ｜ 预算 ${budget} 元 ｜ 利润 ${profit} 元 ｜ 保存 ${esc((p.saved_at || '').slice(0, 16))}</div>
      </div>
      <div class="plan-card-actions">
        <button type="button" class="plan-card-fin${p.finalized ? ' is-on' : ''}" data-fin="${esc(p.id)}" aria-pressed="${p.finalized ? 'true' : 'false'}" aria-label="${p.finalized ? '取消方案定稿' : '标记方案为定稿'}">${p.finalized ? '取消定稿' : '标为定稿'}</button>
        <button type="button" class="plan-card-del${p.finalized ? ' is-disabled' : ''}" data-del="${esc(p.id)}"${p.finalized ? ' disabled' : ''} title="${p.finalized ? '此方案已定稿，请先取消定稿后再删除' : '删除该方案'}" aria-label="删除方案 ${esc(p.id)}" ${p.finalized ? 'aria-disabled="true"' : ''}>删除</button>
      </div>
    </div>`;
  }).join('');
  box.querySelectorAll('.plan-card').forEach(card => {
    card.addEventListener('click', () => {
      selectedPlanId = card.dataset.id;
      renderPlanCards();
      openPlanById(selectedPlanId);
    });
    card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); card.click(); } });
  });
  box.querySelectorAll('.plan-card-fin').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = btn.dataset.fin;
      const plan = list.find(x => x.id === id);
      const nowOn = Boolean(plan && plan.finalized);
      try {
        const res = await (await fetch(`http://localhost:8000/api/project/mark-finalized?id=${encodeURIComponent(id)}&finalized=${nowOn ? 0 : 1}`, { method:'POST' })).json();
        if (!res || res.status !== 'PASS') throw new Error(res.reason || '操作失败');
        setMessage(nowOn ? '已取消该方案的定稿。' : (res.wrote_back ? `方案已标记为「已定稿」并回写经营概览的投标报价金额。` : `已标为「已定稿」，但该方案未关联可回写的经营项目或尚无目标报价，经营概览金额未更新。`), 'success');
        refreshPlans();
      } catch (error) { setMessage(`定稿状态切换失败：${error.message}`, 'error'); }
    });
  });
  box.querySelectorAll('.plan-card-del').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (btn.disabled || btn.classList.contains('is-disabled')) return; // 定稿锁定：取消定稿后此按钮才可点
      const id = btn.dataset.del;
      const plan = list.find(x => x.id === id);
      const ok = await uiConfirm(`确定删除方案「${id}」？该操作不可撤销。`, { danger: Boolean(plan && plan.finalized) });
      if (!ok) return;
      try {
        const res = await (await fetch(`http://localhost:8000/api/project/delete?id=${encodeURIComponent(id)}`, { method:'POST' })).json();
        if (!res || res.status !== 'PASS') throw new Error(res.reason || '删除失败');
        if (selectedPlanId === id) selectedPlanId = '';
        setMessage('方案已删除。', 'success');
        refreshPlans();
      } catch (error) { setMessage(`删除方案失败：${error.message}`, 'error'); }
    });
  });
}

async function openPlanById(id) {
  try {
    const res = await (await fetch(`http://localhost:8000/api/project/get?id=${encodeURIComponent(id)}`)).json();
    if (!res || res.status !== 'PASS') throw new Error(res.reason || '方案不存在');
    const plan = res.plan;
    currentPlanId = plan.id;
    // 打开方案时按该方案自己的关联重建 activeOverviewId（精确 id 优先、项目名兜底），
    // 避免沿用上一次下拉的旧值，导致『定稿并回写』按钮指向错误项目或不显示。
    // 匹配优先级：overview_id 精确 → project_id（可能是真 id 或项目名，副本保留原值不变）→ name → 去「（副本）」后缀的 name
    const pidSel = document.querySelector('#projectId');
    if (pidSel) {
      const name = plan.name || plan.id || '';
      const ovId = String((plan.params || {}).overview_id || '').trim();
      const projId = String(plan.project_id || '').trim();
      const bareName = name.replace(/（副本）\s*$/, '');
      let hit = (ovId && overviewProjects.find(p => p.id === ovId)) ||
                (projId && overviewProjects.find(p => p.id === projId)) ||
                (projId && overviewProjects.find(p => p.name === projId)) ||
                overviewProjects.find(p => p.name === name) ||
                (bareName !== name && overviewProjects.find(p => p.name === bareName)) ||
                null;
      activeOverviewId = hit ? hit.id : '';
      pidSel.value = hit ? hit.id : '';   // 下拉 value 为真实项目 id；label 自动显示项目名
      if (pidSel.__cs) pidSel.__cs.refresh();
    }
    fillParams(plan.params || {});
    if (plan.preview) renderPreview(plan.preview);
    if (plan.result) { setMessage(`已打开方案「${plan.name}」。${plan.result.low_ratio_review_required ? '该结果存在低于50%的报价比率，未作出废标判定，以招标文件为准。' : ''}`, 'success'); renderResult(plan.result); }
    else { setMessage('已打开方案，但该方案尚未生成结果，可点击「按当前参数重算」。', 'success'); document.querySelector('#resultPanel').classList.add('hidden'); }
  } catch (error) { setMessage(`打开方案失败：${error.message}`, 'error'); }
}

document.querySelector('#refreshPlansBtn').addEventListener('click', refreshPlans);
refreshPlans(); // 页面加载即自动拉取方案库，避免首次下拉为空

document.querySelector('#planSelect').addEventListener('change', () => {
  curProject = document.querySelector('#planSelect').value;
  selectedPlanId = '';
  renderPlanCards();
});

document.querySelector('#openPlanBtn').addEventListener('click', () => {
  if (!selectedPlanId) { setMessage('请先在下方选择一个方案卡片再打开。'); return; }
  openPlanById(selectedPlanId);
});

document.querySelector('#copyPlanBtn').addEventListener('click', async () => {
  if (!selectedPlanId) { setMessage('请先在下方选择一个方案卡片再复制。'); return; }
  try {
    const res = await (await fetch(`http://localhost:8000/api/project/copy?id=${encodeURIComponent(selectedPlanId)}`, {method:'POST'})).json();
    if (!res || res.status !== 'PASS') throw new Error(res.reason || '复制失败');
    currentPlanId = res.plan_id;
    setMessage(`已复制方案「${res.name}」，并打开副本。副本结果已清空，可重算生成新结果。`, 'success');
    refreshPlans();
  } catch (error) { setMessage(`复制方案失败：${error.message}`, 'error'); }
});

document.querySelector('#recomputeBtn').addEventListener('click', async () => {
  if (!currentPlanId) { setMessage('请先打开或选择一个方案再重算。'); return; }
  if (!validateParams()) return;
  const button = document.querySelector('#recomputeBtn');
  button.disabled = true; button.setAttribute('aria-busy', 'true'); setMessage('正在按当前参数重算，请稍候。');
  const data = new FormData();
  // id 走 query（后端 id: str 为查询参数），其余数值走表单体
  const fields = {target_total:'targetTotal', fixed_pretax:'fixedPretax', vat_rate:'vatRate', surtax_rate:'surtaxRate', ratio_min:'ratioMin', ratio_max:'ratioMax'};
  Object.entries(fields).forEach(([name, id]) => data.append(name, numVal(id)));
  data.append('low_ratio_confirmed', document.querySelector('#lowRatioConfirmed').checked ? 'true' : 'false');
  data.append('low_price_confirmed_by', (document.querySelector('#lowPriceConfirmedBy') || {}).value || '');
  data.append('clause_enabled', document.querySelector('#clauseEnabled').checked ? 'true' : 'false');
  // H-002：成本税口径（分项构成）覆盖，优先于 config 默认
  const taxRec = readTaxOverride();
  data.append('input_vat_credit_mode', taxRec.mode);
  data.append('cost_input_vat_rate', '0.13');
  data.append('credit_ratio', taxRec.creditRatio);
  data.append('cost_composition', taxRec.compositionJson);
  try {
    const response = await fetch(`http://localhost:8000/api/project/recompute?id=${encodeURIComponent(currentPlanId)}`, {method:'POST', body:data});
    const result = await response.json();
    if (!response.ok || result.status !== 'PASS') throw new Error(result.reason || '重算未通过');
    setMessage(`重算完成：竞争性预算 <b>${Number(result.competitive_budget).toLocaleString('zh-CN',{minimumFractionDigits:2})}</b> 元，结算调整后利润（不含增值税）<b>${Number(result.objective).toLocaleString('zh-CN',{minimumFractionDigits:2})}</b> 元。${costBasisNote(result)}${result.low_ratio_review_required ? '<br><strong>警告：存在低于50%的报价比率，未作出废标判定，以招标文件为准。</strong>' : ''}`, 'success');
    renderResult(result, { savedPlan: true });
    refreshPlans();
  } catch (error) { setMessage(`重算失败：${error.message}`, 'error'); }
  finally { button.disabled = false; button.removeAttribute('aria-busy'); button.innerHTML = '按当前参数重算'; }
});

// ---- H-008 多方案对比（限定同一项目的方案变体） ----
function groupByProject() {
  const g = {};
  (plans || []).forEach(p => { const k = p.project_name || p.project_id || p.name || p.id; (g[k] = g[k] || []).push(p); });
  return g;
}

function populateCompare() {
  const checks = document.querySelector('#compareChecks');
  const base = document.querySelector('#baseSelect');
  const g = groupByProject();
  const keys = Object.keys(g);
  if (!keys.length) { checks.innerHTML = '<p class="hint">暂无方案可对比，请先执行『识别文件并计算』生成方案。</p>'; base.__cs.setOptions([{ value: '', label: '— 基准方案 —' }]); return; }
  checks.innerHTML = keys.map(proj => `
    <label class="compare-group-title">${proj}（${g[proj].length} 个方案）</label>
    ${g[proj].map(p => `<label class="compare-check"><input type="checkbox" value="${p.id}" ${p.id === currentPlanId ? 'checked' : ''}/><span>${p.name || p.id}${p.objective != null ? ` ｜ 利润 ${Number(p.objective).toLocaleString('zh-CN',{maximumFractionDigits:0})}` : ''}</span></label>`).join('')}`).join('');
  base.__cs.setOptions([{ value: '', label: '— 基准方案（缺省首个）—' }].concat(plans.map(p => ({ value: p.id, label: p.name || p.id }))));
}

document.querySelector('#comparePlansBtn').addEventListener('click', () => {
  const bar = document.querySelector('#compareBar');
  bar.classList.toggle('hidden');
  if (!bar.classList.contains('hidden')) populateCompare();
});
document.querySelector('#closeCompareBtn').addEventListener('click', () => {
  document.querySelector('#compareBar').classList.add('hidden');
});

function renderCompare(res) {
  const panel = document.querySelector('#compareResult');
  const ids = res.plan_ids || [];
  const headers = ids.map(id => { const p = res.summary.find(s => s.plan_id === id); return (p && p.name) || id; });
  const get = (id, key) => { const p = res.summary.find(s => s.plan_id === id); return p ? p[key] : undefined; };
  const lossCell = (id) => { const p = get(id, 'loss_items') || []; return p.length ? p.map(x => `${esc(x['项目编码'])}(${fmt(x['单项毛利'])})`).join('<br>') : '<span style="color:var(--text-tertiary)">—</span>'; };
  const riskCell = (id) => { const p = get(id, 'risk_items') || []; return p.length ? p.map(x => `${esc(x['项目编码'])}(${fmt(Number(x['报价比率'])*100,2)}%)`).join('<br>') : '<span style="color:var(--text-tertiary)">—</span>'; };
  const paramsCell = (id) => { const pa = get(id, 'params'); if (!pa) return '<span style="color:var(--text-tertiary)">—</span>'; const f = (pa.target_total != null ? `目标 ${Number(pa.target_total).toLocaleString('zh-CN',{maximumFractionDigits:0})}` : '') + (pa.ratio_min != null ? ` ｜ 区间 ${Number(pa.ratio_min)*100}%~${Number(pa.ratio_max)*100}%` : ''); return f || '<span style="color:var(--text-tertiary)">—</span>'; };
  const baseMark = res.base_id ? `（基准：${esc(res.base_id)}）` : '';
  panel.innerHTML = `<div class="result-head"><div><h3>同一项目方案对比：${esc(res.project || '')}${baseMark}</h3><p>共 ${ids.length} 个同项目方案并列：总利润、亏损项、风险项、单价差异${baseMark}；是否构成废标以招标文件为准。</p></div></div>
    <div class="table-wrap"><table><thead><tr><th>指标</th>${headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>
    <tr><td><b>参数（目标报价/比率区间）</b></td>${ids.map(id => `<td>${paramsCell(id)}</td>`).join('')}</tr>
    <tr><td><b>是否已计算</b></td>${ids.map(id => `<td>${get(id,'computed') ? '✓' : '<span style="color:var(--danger)">未计算</span>'}</td>`).join('')}</tr>
    <tr><td><b>优化项数</b></td>${ids.map(id => `<td>${get(id,'item_count') ?? '—'}</td>`).join('')}</tr>
    <tr><td><b>总利润（结算调整后·不含增值税）</b></td>${ids.map(id => `<td class="${(get(id,'objective') ?? 0) < 0 && get(id,'computed') ? 'loss-cell' : ''}">${get(id,'computed') ? fmt(get(id,'objective')) : '未计算'}</td>`).join('')}</tr>
    <tr><td><b>亏损项（单项毛利<0）</b></td>${ids.map(id => `<td class="${get(id,'loss_items').length ? 'loss-cell' : ''}">${get(id,'loss_items').length ? lossCell(id) + `（${get(id,'loss_items').length}项）` : '—'}</td>`).join('')}</tr>
    <tr><td><b>风险项（报价比率<50%）</b></td>${ids.map(id => `<td class="${get(id,'risk_items').length ? 'warn-cell' : ''}">${get(id,'risk_items').length ? riskCell(id) + `（${get(id,'risk_items').length}项）` : '—'}</td>`).join('')}</tr>
    <tr><td><b>单价 vs 基准 |Δ| 平均</b></td>${ids.map(id => `<td>${get(id,'avg_abs_price_delta') == null ? '—' : fmt(get(id,'avg_abs_price_delta'))}</td>`).join('')}</tr>
    </tbody></table></div>`;
  const diffs = res.price_diffs || {};
  const diffEntries = Object.entries(diffs).filter(([, e]) => ids.some(id => e.deltas[id] != null));
  if (diffEntries.length) {
    panel.innerHTML += `<div class="result-head" style="margin-top:16px;"><div><h3>单价差异明细（相对基准）</h3><p>仅列出基准中存在报价的项目；空表示该方案未含此项目。</p></div></div><div class="table-wrap"><table><thead><tr><th>项目编码</th><th>项目名称</th><th class="num">基准单价</th>${ids.map(id => `<th>${esc(headers.find((_, i) => ids[i] === id))} 差异</th>`).join('')}</tr></thead><tbody>${diffEntries.map(([code, e]) => `<tr><td>${esc(code)}</td><td>${esc(e.item_name || '—')}</td><td class="num">${fmt(e.base_price, 4)}</td>${ids.map(id => { const d = e.deltas[id]; return `<td class="num ${d !== null && d < -1e-9 ? 'loss-cell' : (d !== null && d > 1e-9 ? 'gain-cell' : '')}">${d === null ? '—' : fmt(d, 4)}</td>`; }).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  panel.classList.remove('hidden');
}

document.querySelector('#runCompareBtn').addEventListener('click', async () => {
  const selected = Array.from(document.querySelectorAll('#compareChecks input:checked')).map(cb => cb.value);
  if (selected.length < 2) { setMessage('多方案对比至少需要勾选 2 个方案。'); return; }
  // 限定同一项目：跨项目合并无可比意义（单价差异/利润不可比），前端先行拦截
  const byId = Object.fromEntries((plans || []).map(p => [p.id, p]));
  // 同一项目判定以真实项目 id（UUID）为准：project_name/project_id 先归一化到 overview 的 id，映射不到（项目已删）才回落原值。
  const projs = new Set(selected.map(id => {
    const rec = byId[id] || {};
    const raw = rec.project_name || rec.project_id || rec.name || '';
    return (nameToId[raw] || raw);
  }));
  const showProjs = Array.from(projs).map(k => (activeOverviewProjects[k] && activeOverviewProjects[k].name) || k);
  if (projs.size > 1) { setMessage(`多方案对比限定同一项目（单价差异与利润才有可比意义）：当前勾选涉及 ${showProjs.join('、')}。请仅勾选同一项目的多个方案（可复制后改参数生成同项目的方案变体）。`, 'error'); return; }
  const base = document.querySelector('#baseSelect').value;
  const button = document.querySelector('#runCompareBtn');
  button.disabled = true; setMessage('正在对比方案，请稍候。');
  const data = new FormData();
  data.append('id', selected.join(','));
  if (base) data.append('base', base);
  try {
    const response = await fetch('http://localhost:8000/api/project/compare', {method:'POST', body:data});
    const res = await response.json();
    if (!response.ok || res.status !== 'PASS') throw new Error(res.reason || '对比失败');
    renderCompare(res);
    setMessage(`对比完成：${res.plan_ids.length} 个方案。低于 50% 报价比率的为风险项，是否构成废标以招标文件为准。`, 'success');
  } catch (error) { setMessage(`对比失败：${error.message}`, 'error'); }
  finally { button.disabled = false; button.innerHTML = '开始对比'; }
});

// H-002：成本构成面板初始化（置于文件末尾，保证 COMP_DEFAULTS 等 const 已定义，规避暂时性死区 ReferenceError）
(function initCompositionPanel() {
  // 抵扣方式下拉与页面其他下拉（项目选择/方案选择）统一为毛玻璃自定义组件，
  // 原生 select 仅作 value 载体（cs-hidden），确保设计语言一致、不再出现浏览器原生框。
  initCustomSelect('#taxMode');
  renderCompositionRows();
  toggleComposeWrap();
  updateCompositionLive();
  const taxModeEl = document.querySelector('#taxMode');
  if (taxModeEl) taxModeEl.addEventListener('change', () => { toggleComposeWrap(); updateCompositionLive(); });
})();