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
  // 操作坞只挂在「投标报价」页；其余页面隐藏（各模块后续接入各自专属操作坞）
  const dock = document.querySelector('.floating-dock');
  if (dock) dock.classList.toggle('hidden', module !== 'quote');
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
// ---- 双通道资产舱：选择/拖拽/成功态/重新上传 ----
document.querySelectorAll('.intake-slot input[type=file]').forEach(input => {
  input.addEventListener('change', () => {
    const slot = input.closest('.intake-slot');
    const cta = slot.querySelector('[data-for="' + input.id + '"]');
    const fn = input.files[0];
    if (cta) cta.textContent = fn ? fn.name : '选择 Excel 文件';
    slot.classList.toggle('loaded', Boolean(fn));
    // 文件变化即清空旧解析摘要：预览重解析后再回填，避免「未解析却显示上轮数据」
    slot.querySelectorAll('.intake-stat').forEach(s => { s.innerHTML = ''; });
    refreshPrepare();
  });
});
// 双通道资产舱：键盘可达 —— Enter/Space 打开文件选择（P1-5）
document.querySelectorAll('.intake-slot[role="button"]').forEach(slot => {
  slot.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      const input = slot.querySelector('input[type=file]');
      if (input) input.click();
    }
  });
});
// 拖拽高亮脉冲
document.querySelectorAll('.intake-slot').forEach(slot => {
  ['dragenter', 'dragover'].forEach(ev => slot.addEventListener(ev, e => { e.preventDefault(); slot.classList.add('dragging'); }));
  ['dragleave', 'drop'].forEach(ev => slot.addEventListener(ev, e => { e.preventDefault(); slot.classList.remove('dragging'); }));
  slot.addEventListener('drop', e => {
    const input = slot.querySelector('input[type=file]');
    if (input && e.dataTransfer.files.length) { input.files = e.dataTransfer.files; input.dispatchEvent(new Event('change', { bubbles: true })); }
  });
});
// 重新上传徽标：清空选择并重新打开文件框
document.querySelectorAll('.intake-reup').forEach(btn => {
  btn.addEventListener('click', e => {
    e.preventDefault(); e.stopPropagation();
    const input = document.querySelector('#' + btn.dataset.reup);
    if (input) { input.value = ''; const slot = slotFor(input); slot.classList.remove('loaded'); slot.querySelectorAll('.intake-stat').forEach(s => { s.innerHTML = ''; }); refreshPrepare(); input.click(); }
    function slotFor(el) { return el.closest('.intake-slot'); }
  });
});

let currentPlanId = null;
let plans = [];
let lastResult = null;
// 后端服务基址：单一配置点，换域名/环境只改这一处（下载与所有 API 调用共用）
const API_BASE = 'http://localhost:8000';
let overviewProjects = [];   // 项目经营概览数据集（用于关联与定稿回写）
let activeOverviewId = '';    // 当前关联的经营项目 id（非空才显示定稿回写按钮）
const fmt = (value, digits = 2) => {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (Number.isNaN(n)) return '—';
  // 千分位 + 固定小数位：金额/数量列小数点与位权对齐
  return n.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
};
// 安全转义：所有来自 Excel / 用户输入的字符串在进入 innerHTML 前必须过 esc，防止清单注入。
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const escList = (arr) => (arr || []).map(esc).join('、');

function fillParams(params) {
  if (!params) return;
  const map = { target_total:'targetTotal', fixed_pretax:'fixedPretax', vat_rate:'vatRate', surtax_rate:'surtaxRate', ratio_min:'ratioMin', ratio_max:'ratioMax' };
  Object.entries(map).forEach(([key, id]) => { const el = document.querySelector(`#${id}`); if (params[key] !== undefined) el.value = (key === 'vat_rate' || key === 'surtax_rate') ? Math.round(Number(params[key]) * 100) : params[key]; });
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
  const rlo = document.querySelector('#ratioLow'), rhi = document.querySelector('#ratioHigh');
  if (rlo && params.ratio_min !== undefined) rlo.value = Math.round(Number(params.ratio_min) * 100);
  if (rhi && params.ratio_max !== undefined) rhi.value = Math.round(Number(params.ratio_max) * 100);
  refreshRatioUI();
}

// P0：预览渲染进右栏 #previewStage（唯一真相源）；就绪态 preparePanel 仍可见。
function renderPreview(res) {
  const panel = document.querySelector('#previewStage');
  if (!panel) return;
  setDashboardVisible(false); // 回到就绪态：preparePanel 可见，KPI/明细表隐藏
  const uw = (ws) => Object.entries(ws).map(([k, v]) => `${k}(${v}行)`).join('、') || '—';
  const chip = (k, label) => `<span style="${res.fields[k] ? 'color:var(--success);font-weight:600' : 'color:var(--warn);font-weight:600'}">${label}${res.fields[k] ? '✓' : '−'}</span>`;
  const m = res.match;
  panel.innerHTML = `<div class="result-head"><div><h3>导入资料预览</h3><p>项目：${esc(res.project_id)} ｜ 优化前核对：行数 / 字段 / 匹配覆盖 / 异常 / 文件哈希</p></div></div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px;">
    <div style="padding:10px;background:var(--surface-nested);border:1px solid var(--border);border-radius:8px;"><b>限价清单</b><br>${res.cap.rows} 行 ｜ ${esc(uw(res.cap.unit_works))}<br><small style="color:var(--text-tertiary)">哈希 ${esc(res.cap.hash_sha256 || '—')}</small></div>
    <div style="padding:10px;background:var(--surface-nested);border:1px solid var(--border);border-radius:8px;"><b>成本清单</b><br>${res.cost.rows} 行 ｜ ${esc(uw(res.cost.unit_works))}<br><small style="color:var(--text-tertiary)">哈希 ${esc(res.cost.hash_sha256 || '—')}</small></div>
    <div style="padding:10px;background:var(--surface-nested);border:1px solid var(--border);border-radius:8px;"><b>匹配覆盖</b><br>master ${m.master_keys} 键：匹配 ${m.matched}、仅限价 ${m.only_cap}、仅成本 ${m.only_cost}${m.blocked ? '<br><strong style="color:var(--danger)">重复 key 已阻断，禁止自动合并</strong>' : ''}</div>
    <div style="padding:10px;background:var(--surface-nested);border:1px solid var(--border);border-radius:8px;"><b>可优化 / 人工</b><br>可优化 ${res.optimizable_count} 项 ｜ 人工 ${res.manual_count} 项${res.missing_cap_ids.length ? `<br><small style="color:var(--warn)">无最高限价：${escList(res.missing_cap_ids)}</small>` : ''}${res.missing_cost_ids.length ? `<br><small style="color:var(--warn)">缺成本锚点：${escList(res.missing_cost_ids)}</small>` : ''}${res.duplicate_item_id_across_unit_work.length ? `<br><strong style="color:var(--danger)">跨单位工程重复编码：${escList(res.duplicate_item_id_across_unit_work)}（优化将被阻断）</strong>` : ''}</div>
    <div style="padding:10px;background:var(--surface-nested);border:1px solid var(--border);border-radius:8px;"><b>字段适配</b><br>${chip('item_id', '编码')} ${chip('item_name', '名称')} ${chip('unit', '单位')} ${chip('q0', '工程量')} ${chip('cap', '限价')} ${chip('q1_point', '结算量')} ${chip('c_i', '成本')}</div>
    <div style="padding:10px;background:var(--surface-nested);border:1px solid var(--border);border-radius:8px;"><b>异常</b> ${res.anomaly_count} 条${res.anomalies.length ? `：${res.anomalies.map(a => `${esc(a.kind)}@${esc(a.item_id)}`).join('、')}` : ''}<br><small style="color:var(--text-tertiary)">仅限价侧 ${res.match.only_cap_ids.length ? '：' + escList(res.match.only_cap_ids) : '—'}</small></div>
    </div>`;
  applyIntakeSummary(res);
  panel.classList.remove('hidden');
}

// 上传资产舱即时摘要：预览解析后回填「已解析行数 / 匹配 / 未匹配」凭证
function applyIntakeSummary(res) {
  if (!res) return;
  // 摘要只回填到「当前已加载文件」的槽位：打开已存方案时文件不可还原，槽位
  // 未加载即不显示解析凭证（预览右栏仍展示全部解析明细，无信息损失）。
  const capStat = document.querySelector('#capStat'), costStat = document.querySelector('#costStat');
  const capLoaded = !!document.querySelector('#capSlot') && document.querySelector('#capSlot').classList.contains('loaded');
  const costLoaded = !!document.querySelector('#costSlot') && document.querySelector('#costSlot').classList.contains('loaded');
  if (capStat && res.cap && capLoaded) capStat.innerHTML = `已解析 <b class="tabular">${Number(res.cap.rows) || 0}</b> 行`;
  if (costStat && res.cost && costLoaded) costStat.innerHTML = `已解析 <b class="tabular">${Number(res.cost.rows) || 0}</b> 行`;
  const m = res.match;
  if (m && capStat && capLoaded) {
    const miss = (Number(m.only_cap) || 0) + (Number(m.only_cost) || 0);
    capStat.innerHTML += ` ｜ 匹配 <b class="tabular">${Number(m.matched) || 0}</b>${miss ? ` · 未匹配 <b class="tabular">${miss}</b>` : ''}`;
  }
}

// KPI 穿透清除徽标：毛利/风险钻取激活时显示，一键回到全部子目
function syncDrillClear() {
  const chip = document.querySelector('#clearDrillChip');
  if (!chip) return;
  chip.classList.toggle('hidden', !(dashSortMargin || dashFilter === 'risk'));
}

// P0：结果不再渲染 #resultPanel 大表，统一走 renderDashTable（KPI 联动明细表）。
// 原来 #resultPanel 里的动作（下载 Excel / 下载 JSON / 定稿并回写）搬进 .table-toolbar 右侧小按钮组。
function renderResult(result, { savedPlan = false, animate = true } = {}) {
  fillResultToolbar(result, savedPlan);
  renderDashboard(result, { animate });
  refreshSchemeTabs();
}

// 结果动作工具栏：渲染进 .table-toolbar 右侧 #resultActions（下载 Excel / 下载 JSON / 定稿并回写）
function fillResultToolbar(result, savedPlan) {
  const box = document.querySelector('#resultActions');
  if (!box) return;
  const savedPill = savedPlan ? '<span class="plan-saved-pill">方案已保存</span>' : '';
  // 下载兜底：历史方案 result 可能未带 excel_download_url，按 plan_id 推导
  const dlUrl = result.excel_download_url || (result.plan_id ? '/api/quote/download/' + result.plan_id : '');
  box.innerHTML = savedPill +
    (dlUrl ? `<a class="download-button" href="${API_BASE}${esc(dlUrl)}" ${`download="${esc(dlUrl.split('/').pop())}"`}>下载 Excel</a>` : '') +
    '<button class="btn-secondary" id="downloadResult">下载 JSON</button>' +
    (activeOverviewId ? '<button class="btn-primary" id="finalizeBid" title="将目标总报价写回为该项目投标报价金额，竞争性预算写回为投标成本测算">定稿并回写项目</button>' : '');
  const jbtn = box.querySelector('#downloadResult');
  if (jbtn) jbtn.addEventListener('click', () => { const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = '报价结果_结算调整版.json'; link.click(); URL.revokeObjectURL(link.href); });
  const finBtn = box.querySelector('#finalizeBid');
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
    const resp = await fetch(API_BASE + '/api/project/overview/finalize', {method:'POST', body:data});
    const res = await resp.json();
    if (!resp.ok || res.status !== 'PASS') throw new Error(res.reason || '回写未通过');
    if (activeOverviewProjects[activeOverviewId]) activeOverviewProjects[activeOverviewId].bid_amount = bidAmount;
    setMessage(`已定稿并回写项目经营概览：该项目的投标报价金额已更新为 <b>${Number(bidAmount).toLocaleString('zh-CN',{minimumFractionDigits:2})}</b> 元。投标成本测算请到「项目经营概览」手动填写。`, 'success');
    // 定稿成功后，把当前方案标记为『已定稿』，方案卡片显示徽标，防止误删。
    // write=0：投标报价金额刚已手动回写，避免 mark 再次按方案存储值二次覆盖（值不一致/跨项目污染）。
    if (currentPlanId) {
      try {
        await fetch(`${API_BASE}/api/project/mark-finalized?id=${encodeURIComponent(currentPlanId)}&write=0`, {method:'POST'});
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
    const resp = await fetch(API_BASE + '/api/project/overview/list');
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
    // 全局项目上下文：切换关联项目 → 右侧主舞台切换到该项目「最近方案组/槽位」并刷新方案中心
    sel.addEventListener('change', onGlobalProjectChange);
    apply();
    syncProjectGate();
    refreshPrepare();
  } catch (e) { /* 后端未启动时静默降级为手动填写 */ }
}
// 关联项目门控：未选择关联项目时，报价页全部按钮/输入框/下拉框不可交互（唯一例外：项目选择本身）
function syncProjectGate() {
  const sel = document.querySelector('#projectId');
  document.body.classList.toggle('project-locked', !(sel && sel.value));
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
  document.querySelectorAll('#composeRows input').forEach(el => el.addEventListener('input', () => { updateCompositionLive(); refreshPrepare(); }));
}

function applyComposition(comp) {
  if (!Array.isArray(comp) || !comp.length) { renderCompositionRows(); return; }
  document.querySelector('#composeRows').innerHTML = _composeRowsHtml(comp);
  document.querySelectorAll('#composeRows input').forEach(el => el.addEventListener('input', () => { updateCompositionLive(); refreshPrepare(); }));
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
  const creditPct = document.querySelector('#compCreditPct');
  const ledgerPct = document.querySelector('#compLedgerPct');
  const stkCredit = document.querySelector('#compStkCredit');
  const stkLedger = document.querySelector('#compStkLedger');
  const kBadgeVal = document.querySelector('#kInlineVal');
  const setBarCredit = (c, k) => {
    if (stkCredit) stkCredit.style.width = (c * 100).toFixed(1) + '%';
    if (stkLedger) stkLedger.style.width = ((1 - c) * 100).toFixed(1) + '%';
    if (creditPct) creditPct.textContent = (c * 100).toFixed(1) + '%';
    if (ledgerPct) ledgerPct.textContent = ((1 - c) * 100).toFixed(1) + '%';
    if (kBadgeVal) kBadgeVal.textContent = Number.isFinite(k) ? k.toFixed(6) : '—';
  };
  if (mode === 'NONE') {
    sumEl.textContent = '占比合计：—（不可抵扣，不读构成）';
    sumEl.className = 'compose-sum';
    setBarCredit(0, 1);
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
  setBarCredit(credit, k);
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

// ---- 提示 Toast（P0：消息从左栏内联提示改为顶部 Toast 气泡） ----
// 保留 setMessage(text, kind) 签名（40+ 处调用点不动），内部实现为顶部 toast-pill。
// kind ∈ {success,error,warn,''}：success=模块绿、error=赤陶、warn=赭石、默认墨灰；
// 自动消失（success 3.5s / error 6s / 其他 4s）；内容可含 HTML（现有调用含 <b>）。
let toastTimer = null;
function setMessage(text, kind = '') {
  const tp = document.querySelector('#toastPill');
  const tm = document.querySelector('#toastMsg');
  if (!tp || !tm) return;
  tp.className = 'toast-pill' + (kind ? ' toast-' + kind : '');
  tm.innerHTML = text;
  tp.classList.add('show');
  clearTimeout(toastTimer);
  const ms = kind === 'success' ? 3500 : kind === 'error' ? 6000 : 4000;
  toastTimer = setTimeout(() => tp.classList.remove('show'), ms);
}

// 即时校验：比率区间非法在提交前拦截，并给对应输入框加错误态/焦点，避免空跑服务端再 422。
function clearInvalid() { document.querySelectorAll('.invalid').forEach(el => { el.classList.remove('invalid'); el.removeAttribute('aria-invalid'); }); }
function markInvalid(el, msg) { el.classList.add('invalid'); el.setAttribute('aria-invalid', 'true'); el.focus(); setMessage(msg, 'error'); }
function validateParams() {
  clearInvalid();
  const loEl = document.querySelector('#ratioMin'); const hiEl = document.querySelector('#ratioMax');
  const lo = Number(loEl.value); const hi = Number(hiEl.value);
  if (Number.isNaN(lo) || lo < 0 || lo > 1) { markInvalid(loEl, '单项报价比率下限非法：须为 0～1 之间的数值。'); return false; }
  if (Number.isNaN(hi) || hi > 1 || hi < lo) { markInvalid(hiEl, `报价比率区间非法：上限须 ≥ 下限（${lo}）且 ≤ 1.00。`); return false; }
  // 税率采用整数百分比口径（9 = 9%），提交时 /100 转小数（0.09）；须落在 (0, 100]
  const vtEl = document.querySelector('#vatRate'); const stEl = document.querySelector('#surtaxRate');
  const vt = Number(vtEl.value); const st = Number(stEl.value);
  if (Number.isNaN(vt) || vt <= 0 || vt > 100) { markInvalid(vtEl, '增值税率须为 0～100 之间的百分比整数（如 9 表示 9%）。'); return false; }
  if (Number.isNaN(st) || st <= 0 || st > 100) { markInvalid(stEl, '附加税率须为 0～100 之间的百分比整数（如 12 表示 12%）。'); return false; }
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
    const response = await fetch(API_BASE + '/api/quote/preview', {method:'POST', body:data});
    const res = await response.json();
    if (!response.ok || res.status !== 'PASS') throw new Error(res.reason || '预览未通过');
    renderPreview(res);
    setMessage(`预览完成：限价 ${res.cap.rows} 行、成本 ${res.cost.rows} 行，可优化 ${res.optimizable_count} 项。`, 'success');
  } catch (error) {
    setMessage(`预览失败：${error.message}`, 'error');
  } finally { button.disabled = false; button.removeAttribute('aria-busy'); button.innerHTML = '预览导入资料'; }
});

// 组装 /api/quote/optimize 的表单体；strategy ∈ {"optimal","uniform"}（后端并行开发中，未实现时忽略该字段 = 优雅降级）。
function buildOptimizeForm(strategy) {
  const data = new FormData();
  data.append('limit_file', document.querySelector('#capFile').files[0]);
  data.append('cost_file', document.querySelector('#costFile').files[0]);
  const fields = {project_id:'projectId', target_total:'targetTotal', fixed_pretax:'fixedPretax', vat_rate:'vatRate', surtax_rate:'surtaxRate', ratio_min:'ratioMin', ratio_max:'ratioMax'};
  Object.entries(fields).forEach(([name, id]) => data.append(name, numVal(id)));
  // 增值税率/附加税率：页面按整数百分比录入（9 / 12），后端按小数接收（0.09 / 0.12）
  ['vat_rate', 'surtax_rate'].forEach(k => data.set(k, String(Number(data.get(k)) / 100)));
  data.append('project_name', selectedOverviewProject().name);
  data.append('overview_id', activeOverviewId);
  data.append('low_ratio_confirmed', document.querySelector('#lowRatioConfirmed').checked ? 'true' : 'false');
  data.append('low_price_confirmed_by', [ (document.querySelector('#lowPriceConfirmedBy') || {}).value, (document.querySelector('#lowPriceBasisBy') || {}).value ].filter(Boolean).join('；'));
  data.append('clause_enabled', document.querySelector('#clauseEnabled').checked ? 'true' : 'false');
  // H-002：成本税口径（分项构成）覆盖，优先于 config 默认
  const taxCalc = readTaxOverride();
  data.append('input_vat_credit_mode', taxCalc.mode);
  data.append('cost_input_vat_rate', '0.13');
  data.append('credit_ratio', taxCalc.creditRatio);
  data.append('cost_composition', taxCalc.compositionJson);
  data.append('strategy', strategy);
  // H-008 方案组：带当前组 id，后端归入该组对应策略槽位（可空，空则并入既有组或新建组）
  data.append('group_id', activeGroupId || '');
  return data;
}
// 单次 optimize 请求：返回 {result} 或抛 {message, hint}
async function postOptimize(strategy) {
  const response = await fetch(API_BASE + '/api/quote/optimize', {method:'POST', body: buildOptimizeForm(strategy)});
  const result = await response.json();
  if (!response.ok || result.status !== 'PASS') {
    // H-002：成本税口径未声明时后端在**出数之前**阻断；把原因与「该怎么办」
    // 一并展示，避免用户只看到一句无法行动的报错。
    const hint = result.cost_input_tax && result.cost_input_tax.user_hint;
    const err = new Error(result.reason || '计算未通过');
    err.hint = hint || '';
    throw err;
  }
  result.strategy = strategy; // 契约并行开发中：PASS 响应缺省按本次提交的策略回填
  return result;
}
// P0：一键生成三方案——顺序执行两次：A=optimal（逐项最优，主舞台 A 视图）、B=uniform（等比下浮）。
// 第二次失败不阻断第一次成功（Toast 提示「方案B生成失败，原因…」）；lastResult 存 A 结果。
document.querySelector('#calculateBtn').addEventListener('click', async () => {
  const cap = document.querySelector('#capFile').files[0];
  const cost = document.querySelector('#costFile').files[0];
  if (!validateParams()) return;
  if (!cap || !cost) { setMessage('请先上传限价清单和成本清单。'); return; }
  const button = document.querySelector('#calculateBtn');
  button.disabled = true; button.setAttribute('aria-busy', 'true'); button.innerHTML = '正在计算…'; setMessage('正在识别清单并运行 Phase 2 MILP（方案 A：逐项最优），请稍候。'); setDockBusy(true);
  try {
    const resultA = await postOptimize('optimal');
    currentPlanId = resultA.plan_id || null;
    lastResult = resultA;
    if (resultA.plan_id) planStrategyOverride[resultA.plan_id] = 'optimal';
    activeGroupId = resultA.group_id || activeGroupId;   // A/B 归入同一方案组
    renderResult(resultA, { savedPlan: Boolean(currentPlanId) });
    setMessage(`方案 A 计算完成：竞争性预算 <b>${Number(resultA.competitive_budget).toLocaleString('zh-CN',{minimumFractionDigits:2})}</b> 元，结算调整后利润（不含增值税）<b>${Number(resultA.objective).toLocaleString('zh-CN',{minimumFractionDigits:2})}</b> 元。${costBasisNote(resultA)}${resultA.low_ratio_review_required ? '<br><strong>警告：存在低于50%的报价比率，请人工复核招标文件条款。系统未作出废标判定，以招标文件为准；已记录确认留痕（确认人/时间/条款依据，见结果 JSON）。</strong>' : ''}`, 'success');
    // 第二步：方案 B（uniform）——失败不阻断 A 的成功结果（同组 B 槽位）
    try {
      const resultB = await postOptimize('uniform');
      planStrategyOverride[resultB.plan_id] = 'uniform';
      setMessage(`方案 A/B 均已生成：A=逐项最优，B=等比下浮（利润 <b>${Number(resultB.objective).toLocaleString('zh-CN',{minimumFractionDigits:2})}</b> 元）。${costBasisNote(resultB)}`, 'success');
    } catch (errorB) {
      setMessage(`方案 B（等比下浮）生成失败，原因：${errorB.message}${errorB.hint ? `（${esc(errorB.hint)}）` : ''}。方案 A 已可用。`, 'warn');
    }
    await refreshPlans();
    activeGroup = groups.find(g => g.group_id === activeGroupId) || activeGroup;
    openGroupById(activeGroupId);
    refreshSchemeTabs();
    updateSchemeBalance();
    syncDockCta();
  } catch (error) {
    setMessage(`计算失败：${error.message}${error.hint ? `<br>${esc(error.hint)}` : ''}`, 'error');
  } finally { button.disabled = false; button.removeAttribute('aria-busy'); button.innerHTML = '识别文件并计算 <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>'; setDockBusy(false); }
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
// 注：旧左栏 #planSelect/#baseSelect 已随 P1 重构移除（方案库迁移到底部方案条，使用原生 select）。

// ---- 方案中心：方案组（当前关联项目）→ A/B/C 槽位 ----
let groups = [];              // 当前关联项目的方案组列表
let activeGroup = null;       // 右栏当前展示的方案组对象
let activeGroupId = '';       // 右栏当前展示的方案组 id
let dashActive = false;       // 右栏是否处于结果态（renderDashboard 之后）
let expandedGroups = new Set(); // 方案中心已展开的组 id
let hubSelected = new Set();   // 方案中心已勾选对比的槽位方案 id 集合
let hubView = 'list';          // 方案中心视图：list=方案组卡片 / compare=对比结果

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

// 当前「关联投标项目」的 id（#projectId 全局上下文）
function curProjectIdUuid() { return selectedOverviewProject().uuid; }

// 当前项目方案组 → 扁平槽位方案列表（对比/策略映射复用）
function currentProjectPlans() {
  const out = [];
  (groups || []).forEach(g => {
    Object.entries(g.strategy_slots || {}).forEach(([letter, s]) => {
      const sm = (s && s.summary) || {};
      const planId = (s && (s.plan_id || sm.plan_id)) || sm.plan_id;
      if (!planId) return;
      out.push({
        id: planId, group_id: g.group_id, strategy: sm.strategy || letter.toLowerCase(),
        name: (g.group_name || g.group_id || '') + ' · ' + letter,
        project_id: g.project_id || g.project_name || '',
        finalized: !!(g.finalized), saved_at: sm.saved_at,
        target_total: sm.target_total, objective: sm.objective,
        item_count: sm.item_count, competitive_budget: sm.competitive_budget,
      });
    });
  });
  return out;
}

// 拉取当前关联项目的方案组并渲染方案中心；无项目时清空并渲染空态。
async function loadProjectGroups() {
  const pid = curProjectIdUuid();
  if (!pid) { groups = []; plans = []; renderHubCards(); return []; }
  try {
    const res = await (await fetch(API_BASE + '/api/group/list?project_id=' + encodeURIComponent(pid))).json();
    groups = (res && res.groups) || [];
    plans = currentProjectPlans();
    renderHubCards();
    return groups;
  } catch (error) { setMessage(`方案组加载失败：${error.message}`, 'error'); return []; }
}

async function refreshPlans() {
  await loadProjectGroups();
  refreshSchemeTabs();
  syncSchemeSwitcher();
}

/* ---- 方案中心（#planHub）方案组 → A/B/C 槽位渲染 ----
   每组一张卡：组名 / 目标报价 / 已算槽数 / 定稿锁 + 操作（改名·复制整组·定稿·删除）+ 展开出槽位。
   槽位：pending 灰置「未测算·点算」；computed 显示利润 + 竞争预算 + 量化，带「打开」「勾选对比」。 */
const HUB_SLOT_DEFS = [
  { key: 'A', label: '逐项最优', strategy: 'optimal' },
  { key: 'B', label: '等比下浮', strategy: 'uniform' },
  { key: 'C', label: '策略待定', strategy: null },
];
function _fmtMoney(v) { return v != null && v !== '' ? '¥' + Number(v).toLocaleString('zh-CN',{minimumFractionDigits:2}) : '—'; }

function renderPlanHub() {
  const body = document.querySelector('#planHubBody');
  if (!body) return;
  if (hubView === 'compare') return;   // 对比结果视图不重渲染卡片
  renderHubCards();
}

function renderHubCards() {
  const body = document.querySelector('#planHubBody');
  if (!body) return;
  const cur = document.querySelector('#planHubCurrent');
  const pid = curProjectIdUuid();
  if (cur) cur.textContent = pid ? ('当前项目：' + (selectedOverviewProject().name || pid)) : '未选择项目';
  if (!pid) { body.innerHTML = '<div class="ph-empty">请先在左侧选择关联投标项目</div>'; updateHubSelection(); return; }
  if (!groups.length) { body.innerHTML = '<div class="ph-empty">该项目暂无方案组，请先在上方识别并计算</div>'; updateHubSelection(); return; }
  body.innerHTML = groups.map(renderGroupCard).join('');
  bindHubGroupEvents();
}

function renderGroupCard(g) {
  const computed = Object.values(g.strategy_slots || {}).filter(s => s && (s.plan_id || (s.summary && s.summary.plan_id))).length;
  const expanded = expandedGroups.has(g.group_id);
  const slotsHtml = expanded ? HUB_SLOT_DEFS.map(def => renderSlotRow(g, def)).join('') : '';
  const lock = g.finalized ? '<span class="phg-lock on" title="已定稿，整组锁定"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="11" width="16" height="9" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>已定稿</span>' : '<span class="phg-lock">未定稿</span>';
  const finLabel = g.finalized ? '取消定稿' : '定稿锁定';
  return `<div class="phg-card${g.finalized ? ' finalized' : ''}${expanded ? ' expanded' : ''}" data-gid="${esc(g.group_id)}">
    <div class="phg-head">
      <button type="button" class="phg-expand" data-gid="${esc(g.group_id)}" aria-expanded="${expanded}" title="${expanded ? '收起槽位' : '展开 A/B/C 槽位'}"><span class="arr">▸</span></button>
      <span class="phg-name" title="${esc(g.group_name || '')}">${esc(g.group_name || g.group_id || '未命名组')}</span>
      ${lock}
    </div>
    <div class="phg-meta">
      <span>目标报价 <b class="tabular">${_fmtMoney(_groupTarget(g))}</b></span>
      <span>已算 <b class="tabular">${computed}/3</b> 槽</span>
    </div>
    <div class="phg-ops">
      <button type="button" class="phg-op" data-rename="${esc(g.group_id)}">改名</button>
      <button type="button" class="phg-op" data-copy="${esc(g.group_id)}">复制整组</button>
      <button type="button" class="phg-op fin${g.finalized ? ' is-on' : ''}" data-fin="${esc(g.group_id)}">${finLabel}</button>
      <button type="button" class="phg-op${g.finalized ? ' is-disabled' : ''}" data-del="${esc(g.group_id)}"${g.finalized ? ' disabled' : ''}>删除</button>
    </div>
    ${slotsHtml ? '<div class="phg-slots">' + slotsHtml + '</div>' : ''}
  </div>`;
}

function _groupTarget(g) {
  for (const def of HUB_SLOT_DEFS) {
    const t = (g.strategy_slots || {})[def.key] && (g.strategy_slots[def.key].summary || {}).target_total;
    if (t != null) return t;
  }
  return null;
}

function renderSlotRow(g, def) {
  const s = (g.strategy_slots || {})[def.key] || { plan_id: null, status: 'pending' };
  const sm = s.summary || {};
  const planId = s.plan_id || sm.plan_id;
  const letter = def.key.toLowerCase();
  if (!planId) {
    return `<div class="phg-slot pending letter-${letter}">
      <span class="letter">${def.key}</span>
      <div class="phg-slot-info">
        <div class="phg-slot-title">${def.key} · ${def.label}</div>
        <div class="phg-slot-stat">未测算 · 可点算</div>
      </div>
      ${def.strategy ? `<button type="button" class="slot-act" data-calc="${esc(g.group_id)}" data-strategy="${def.strategy}">点算</button>` : ''}
    </div>`;
  }
  const checked = hubSelected.has(planId) ? ' checked' : '';
  const stat = `利润 <b class="tabular">${_fmtMoney(sm.objective)}</b> ｜ 竞争预算 <b>${_fmtMoney(sm.competitive_budget)}</b> ｜ ${sm.item_count != null ? sm.item_count + ' 项' : '—'}`;
  return `<div class="phg-slot letter-${letter}">
    <span class="letter">${def.key}</span>
    <div class="phg-slot-info">
      <div class="phg-slot-title">${def.key} · ${def.label}</div>
      <div class="phg-slot-stat">${stat}</div>
    </div>
    <button type="button" class="slot-act" data-open="${esc(planId)}" title="打开该槽位方案">打开</button>
    <label class="slot-check" title="勾选对比"><input type="checkbox" value="${esc(planId)}"${checked}/></label>
  </div>`;
}

function bindHubGroupEvents() {
  const body = document.querySelector('#planHubBody');
  if (!body) return;
  body.querySelectorAll('.phg-expand').forEach(btn => {
    btn.addEventListener('click', () => {
      const gid = btn.dataset.gid;
      expandedGroups.has(gid) ? expandedGroups.delete(gid) : expandedGroups.add(gid);
      renderHubCards();
    });
  });
  body.querySelectorAll('.phg-slot .slot-check input').forEach(cb => cb.addEventListener('change', () => updateHubSelection()));
  body.querySelectorAll('.phg-slot .slot-act[data-open]').forEach(btn => {
    btn.addEventListener('click', () => {
      const gid = btn.closest('.phg-slot').closest('.phg-card').dataset.gid;
      closePlanHub();
      openSlot(btn.dataset.open, groups.find(g => g.group_id === gid) || activeGroup);
    });
  });
  body.querySelectorAll('.phg-slot .slot-act[data-calc]').forEach(btn => {
    btn.addEventListener('click', () => runSlotCalc(btn.dataset.calc, btn.dataset.strategy));
  });
  body.querySelectorAll('.phg-op[data-rename]').forEach(btn => {
    btn.addEventListener('click', () => beginGroupRename(btn.dataset.rename));
  });
  body.querySelectorAll('.phg-op[data-copy]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const ok = await uiConfirm('复制整组为独立新组（深拷贝组内已算槽位方案，可独立改参）？');
      if (!ok) return;
      try {
        const fd = new FormData(); fd.append('group_id', btn.dataset.copy);
        const res = await (await fetch(API_BASE + '/api/group/copy', { method:'POST', body: fd })).json();
        if (!res || res.status !== 'PASS') throw new Error(res.reason || '复制失败');
        setMessage('已复制整组为「' + (((res.group || {}).group_name) || '') + '」。', 'success');
        await refreshPlans();
      } catch (error) { setMessage(`复制整组失败：${error.message}`, 'error'); }
    });
  });
  body.querySelectorAll('.phg-op[data-fin]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const gid = btn.dataset.fin;
      const nowOn = Boolean(groups.find(x => x.group_id === gid) && groups.find(x => x.group_id === gid).finalized);
      try {
        const fd = new FormData(); fd.append('group_id', gid); fd.append('finalized', nowOn ? '0' : '1');
        const res = await (await fetch(API_BASE + '/api/group/finalize', { method:'POST', body: fd })).json();
        if (!res || res.status !== 'PASS') throw new Error(res.reason || '操作失败');
        setMessage(nowOn ? '已取消整组定稿。' : '已整组定稿锁定（组内槽位不可删改）。', 'success');
        await refreshPlans();
      } catch (error) { setMessage(`定稿切换失败：${error.message}`, 'error'); }
    });
  });
  body.querySelectorAll('.phg-op[data-del]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (btn.disabled || btn.classList.contains('is-disabled')) return;   // 定稿整组锁定
      const gid = btn.dataset.del;
      const g = groups.find(x => x.group_id === gid);
      const ok = await uiConfirm('删除该方案组？组内已算槽位方案将一并删除。', { danger: Boolean(g && g.finalized) });
      if (!ok) return;
      try {
        const fd = new FormData(); fd.append('group_id', gid);
        const res = await (await fetch(API_BASE + '/api/group/delete', { method:'POST', body: fd })).json();
        if (!res || res.status !== 'PASS') throw new Error(res.reason || '删除失败');
        hubSelected.clear(); expandedGroups.delete(gid);
        if (activeGroupId === gid) { activeGroupId = ''; activeGroup = null; syncSchemeSwitcher(); }
        setMessage('方案组已删除。', 'success');
        await refreshPlans();
      } catch (error) { setMessage(`删除方案组失败：${error.message}`, 'error'); }
    });
  });
}

function beginGroupRename(groupId) {
  const card = document.querySelector('.phg-card[data-gid="' + CSS.escape(groupId) + '"] .phg-name');
  if (!card) return;
  const g = groups.find(x => x.group_id === groupId);
  const input = document.createElement('input');
  input.className = 'phg-rename-input'; input.maxLength = 60;
  input.value = g ? (g.group_name || '') : '';
  const render = () => { card.textContent = g ? (g.group_name || '') : ''; };
  const commit = async (save) => {
    const v = input.value.trim();
    render(); input.replaceWith(card);
    if (!save || !v || !g || v === g.group_name) return;
    try {
      const fd = new FormData(); fd.append('group_id', groupId); fd.append('name', v);
      const res = await (await fetch(API_BASE + '/api/group/rename', { method:'POST', body: fd })).json();
      if (!res || res.status !== 'PASS') throw new Error(res.reason || '改名失败');
      setMessage('已重命名方案组。', 'success');
      await refreshPlans();
    } catch (error) { setMessage(`重命名失败：${error.message}`, 'error'); render(); }
  };
  input.addEventListener('keydown', e => { if (e.key === 'Enter') commit(true); else if (e.key === 'Escape') commit(false); });
  input.addEventListener('blur', () => commit(true));
  card.replaceWith(input);
  input.focus(); input.select();
}

// 点算指定组 + 策略的暂未计算槽位（A/B）：带 group_id 提交 optimize。
async function runSlotCalc(groupId, strategy) {
  if (!curProjectIdUuid()) { setMessage('请先选择关联投标项目。', 'warn'); return; }
  const cap = document.querySelector('#capFile').files[0];
  const cost = document.querySelector('#costFile').files[0];
  if (!cap || !cost) { setMessage('请先在左栏导入限价清单与成本清单后再点算该槽位。', 'warn'); return; }
  const prev = activeGroupId;
  activeGroupId = groupId;   // buildOptimizeForm 据此带上 group_id
  setMessage('正在测算方案 ' + (strategy === 'optimal' ? 'A' : 'B') + ' 槽位，请稍候。', '');
  try {
    const result = await postOptimize(strategy);
    activeGroupId = result.group_id || groupId;
    if (result.plan_id) { currentPlanId = result.plan_id; planStrategyOverride[result.plan_id] = strategy; lastResult = result; }
    renderResult(result, { savedPlan: Boolean(currentPlanId) });
    await openSlot(result.plan_id, groups.find(g => g.group_id === activeGroupId) || activeGroup);
    setMessage(`方案 ${strategy === 'optimal' ? 'A' : 'B'} 槽位测算完成。${costBasisNote(result)}`, 'success');
    await refreshPlans();
    openGroupById(activeGroupId);
  } catch (error) {
    setMessage(`测算失败：${error.message}${error.hint ? '<br>' + esc(error.hint) : ''}`, 'error');
    activeGroupId = prev;
  }
}

// 打开某槽位方案：/api/project/get 拉取后渲染右栏，并设定「当前组」上下文。
async function openSlot(planId, group, opts = {}) {
  try {
    const res = await (await fetch(`${API_BASE}/api/project/get?id=${encodeURIComponent(planId)}`)).json();
    if (!res || res.status !== 'PASS') throw new Error(res.reason || '方案不存在');
    const plan = res.plan;
    currentPlanId = plan.id;
    if (group) { activeGroup = group; activeGroupId = group.group_id || ''; }
    else { activeGroupId = plan.group_id || findGroupIdByPlan(plan.id) || ''; activeGroup = groups.find(x => x.group_id === activeGroupId) || null; }
    // 按该方案自身关联重建 activeOverviewId / #projectId（精确 id 优先、项目名兜底）
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
                (bareName !== name && overviewProjects.find(p => p.name === bareName)) || null;
      activeOverviewId = hit ? hit.id : '';
      pidSel.value = hit ? hit.id : '';
      if (pidSel.__cs) pidSel.__cs.refresh();
    }
    fillParams(plan.params || {});
    if (plan.preview) renderPreview(plan.preview);
    if (plan.result) {
      setMessage(`已打开方案「${plan.name || plan.id}」。${plan.result.low_ratio_review_required ? '该结果存在低于50%的报价比率，未作出废标判定，以招标文件为准。' : ''}`, 'success');
      renderResult(plan.result, { animate: opts.animate !== false });
    } else {
      setMessage('已打开方案，但该槽位尚未生成结果，可点击「按当前参数重算」。', 'success');
      setDashboardVisible(false);
      const ps = document.querySelector('#previewStage'); if (ps) ps.classList.add('hidden');
    }
    refreshSchemeTabs();
    // 同步方案 Tab 高亮：以当前方案在槽位映射中的位置为准（缺省 A），避免 renderDashboard 重置导致点击态与数据脱节
    const sidx = schemePlanIds.indexOf(planId);
    document.querySelectorAll('.scheme-tab').forEach(t => {
      const on = Number(t.dataset.scheme) === (sidx >= 0 ? sidx : 0);
      t.classList.toggle('active', on);
      t.setAttribute('aria-selected', String(on));
    });
    updateSchemeBalance();
  } catch (error) { setMessage(`打开方案失败：${error.message}`, 'error'); }
}

function findGroupIdByPlan(planId) {
  const g = (groups || []).find(x => Object.values(x.strategy_slots || {}).some(s => (s && (s.plan_id || (s.summary && s.summary.plan_id))) === planId));
  return g ? g.group_id : null;
}

// 兼容旧调用：按方案 id 打开（自动定位其所属组）
function openPlanById(id) {
  const g = (groups || []).find(x => Object.values(x.strategy_slots || {}).some(s => (s && (s.plan_id || (s.summary && s.summary.plan_id))) === id)) || activeGroup;
  return openSlot(id, g);
}
refreshPlans(); // 页面加载即自动拉取当前关联项目的方案组供方案中心使用

/* P1：按当前参数重算（原左栏 #recomputeBtn 逻辑抽成独立函数）。
   调用方：dockCalcBtn 情境「按当前参数重算」。
   校验 currentPlanId → validateParams → POST /api/project/recompute → renderResult → refreshPlans。 */
async function runRecompute() {
  if (!currentPlanId) { setMessage('请先打开或选择一个方案再重算。'); return; }
  if (!validateParams()) return;
  setDockBusy(true); setMessage('正在按当前参数重算，请稍候。');
  const data = new FormData();
  // id 走 query（后端 id: str 为查询参数），其余数值走表单体
  const fields = {target_total:'targetTotal', fixed_pretax:'fixedPretax', vat_rate:'vatRate', surtax_rate:'surtaxRate', ratio_min:'ratioMin', ratio_max:'ratioMax'};
  Object.entries(fields).forEach(([name, id]) => data.append(name, numVal(id)));
  // 增值税率/附加税率：页面按整数百分比录入（9 / 12），后端按小数接收（0.09 / 0.12）
  ['vat_rate', 'surtax_rate'].forEach(k => data.set(k, String(Number(data.get(k)) / 100)));
  data.append('low_ratio_confirmed', document.querySelector('#lowRatioConfirmed').checked ? 'true' : 'false');
  data.append('low_price_confirmed_by', [ (document.querySelector('#lowPriceConfirmedBy') || {}).value, (document.querySelector('#lowPriceBasisBy') || {}).value ].filter(Boolean).join('；'));
  data.append('clause_enabled', document.querySelector('#clauseEnabled').checked ? 'true' : 'false');
  // H-002：成本税口径（分项构成）覆盖，优先于 config 默认
  const taxRec = readTaxOverride();
  data.append('input_vat_credit_mode', taxRec.mode);
  data.append('cost_input_vat_rate', '0.13');
  data.append('credit_ratio', taxRec.creditRatio);
  data.append('cost_composition', taxRec.compositionJson);
  // 重算保留该方案策略（A=optimal / B=uniform），后端缺省回退 optimal
  const cur = currentProjectPlans().find(x => x.id === currentPlanId);
  data.append('strategy', _planStrategy(cur));
  try {
    const response = await fetch(`${API_BASE}/api/project/recompute?id=${encodeURIComponent(currentPlanId)}`, {method:'POST', body:data});
    const result = await response.json();
    if (!response.ok || result.status !== 'PASS') throw new Error(result.reason || '重算未通过');
    planStrategyOverride[currentPlanId] = result.strategy || _planStrategy(cur);
    setMessage(`重算完成：竞争性预算 <b>${Number(result.competitive_budget).toLocaleString('zh-CN',{minimumFractionDigits:2})}</b> 元，结算调整后利润（不含增值税）<b>${Number(result.objective).toLocaleString('zh-CN',{minimumFractionDigits:2})}</b> 元。${costBasisNote(result)}${result.low_ratio_review_required ? '<br><strong>警告：存在低于50%的报价比率，未作出废标判定，以招标文件为准。</strong>' : ''}`, 'success');
    renderResult(result, { savedPlan: true });
    refreshPlans();
  } catch (error) { setMessage(`重算失败：${error.message}`, 'error'); }
  finally { setDockBusy(false); }
}

// ---- H-008 多方案对比（限定同一项目的方案变体） ----
/* ---- H-008 多方案对比（限定同一项目）：方案中心勾选槽位 →「开始对比」 ----
   compareHtml(res) 构建指标矩阵 HTML；
   renderCompare(res) 渲染进居中式对比结果弹层 #cmpModal（不占右栏主舞台）。 */
function compareHtml(res) {
  const ids = res.plan_ids || [];
  const headers = ids.map(id => { const p = res.summary.find(s => s.plan_id === id); return (p && p.name) || id; });
  const get = (id, key) => { const p = res.summary.find(s => s.plan_id === id); return p ? p[key] : undefined; };
  const lossCell = (id) => { const p = get(id, 'loss_items') || []; return p.length ? p.map(x => `${esc(x['项目编码'])}(${fmt(x['单项毛利'])})`).join('<br>') : '<span style="color:var(--text-tertiary)">—</span>'; };
  const riskCell = (id) => { const p = get(id, 'risk_items') || []; return p.length ? p.map(x => `${esc(x['项目编码'])}(${fmt(Number(x['报价比率'])*100,2)}%)`).join('<br>') : '<span style="color:var(--text-tertiary)">—</span>'; };
  const paramsCell = (id) => { const pa = get(id, 'params'); if (!pa) return '<span style="color:var(--text-tertiary)">—</span>'; const f = (pa.target_total != null ? `目标 ${Number(pa.target_total).toLocaleString('zh-CN',{maximumFractionDigits:0})}` : '') + (pa.ratio_min != null ? ` ｜ 区间 ${Number(pa.ratio_min)*100}%~${Number(pa.ratio_max)*100}%` : ''); return f || '<span style="color:var(--text-tertiary)">—</span>'; };
  const baseMark = res.base_id ? `（基准：${esc(res.base_id)}）` : '';
  let html = `<div class="result-head"><div><h3>同一项目方案对比：${esc(res.project || '')}${baseMark}</h3><p>共 ${ids.length} 个同项目方案并列：总利润、亏损项、风险项、单价差异${baseMark}；是否构成废标以招标文件为准。</p></div></div>
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
    html += `<div class="result-head" style="margin-top:16px;"><div><h3>单价差异明细（相对基准）</h3><p>仅列出基准中存在报价的项目；空表示该方案未含此项目。</p></div></div><div class="table-wrap"><table><thead><tr><th>项目编码</th><th>项目名称</th><th class="num">基准单价</th>${ids.map(id => `<th>${esc(headers.find((_, i) => ids[i] === id))} 差异</th>`).join('')}</tr></thead><tbody>${diffEntries.map(([code, e]) => `<tr><td>${esc(code)}</td><td>${esc(e.item_name || '—')}</td><td class="num">${fmt(e.base_price, 4)}</td>${ids.map(id => { const d = e.deltas[id]; return `<td class="num ${d !== null && d < -1e-9 ? 'loss-cell' : (d !== null && d > 1e-9 ? 'gain-cell' : '')}">${d === null ? '—' : fmt(d, 4)}</td>`; }).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  return html;
}
// H-008 多方案对比结果：方案中心「开始对比 →」→ 居中式弹层 #cmpModal（不占右栏主舞台）
function renderCompare(res, { silent = false } = {}) {
  const body = document.querySelector('#cmpModalBody');
  if (!body) return;
  body.innerHTML = compareHtml(res);
  openCompareModal();
}

// H-002：成本构成面板初始化（置于文件末尾，保证 COMP_DEFAULTS 等 const 已定义，规避暂时性死区 ReferenceError）
(function initCompositionPanel() {
  // 抵扣方式下拉与页面其他下拉（项目选择/方案选择）统一为毛玻璃自定义组件，
  // 原生 select 仅作 value 载体（cs-hidden），确保设计语言一致、不再出现浏览器原生框。
  initCustomSelect('#taxMode');
  renderCompositionRows();
  toggleComposeWrap();
  updateCompositionLive();
  const taxModeEl = document.querySelector('#taxMode');
  if (taxModeEl) taxModeEl.addEventListener('change', () => { toggleComposeWrap(); updateCompositionLive(); refreshPrepare(); });
})();

/* =============================================================================
   决策沙盘 · 报价页 KPI 看板 / A/B/C 方案切换 / 明细穿透表 / Diff 抽屉 / FAB
   仅作用于报价视图，接入现有真实后端 renderResult(result)。
   ============================================================================= */
function triggerToast(text) {
  const tp = document.querySelector('#toastPill');
  const tm = document.querySelector('#toastMsg');
  if (!tp) return;
  tm.textContent = text;
  tp.className = 'toast-pill';
  tp.classList.add('show');
  // 与 setMessage 共用 toastTimer，避免旧计时器提前隐藏新 Toast
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => tp.classList.remove('show'), 2200);
}
function setText(id, v) { const el = document.getElementById(id); if (el) el.textContent = v; }

// 派生合规评分：status / violations / anomalies / low_ratio_review_required → 评分+等级
function computeCompliance(result) {
  let score = 100, reasons = [];
  if (!result || result.status !== 'PASS') { return { score: 0, grade: '—', audit: result && result.status || '未通过', badge: 'warn', maxDev: '—', safe:0, early:0, risk:100 }; }
  const isRisk = (r) => (Number(r['报价比率'] ?? 1) < 0.5) || r['报价状态'] === 'MANUAL_REVIEW' || (Number(r['单项毛利'] ?? 0) < 0);
  const riskRows = (result.items || []).filter(isRisk);
  // 三桶互斥：有意提前回笼（≥92%）的项若已属风险桶则不重复计入 early
  const earlyRows = (result.items || []).filter(r => Number(r['报价比率'] ?? 0) >= 0.92 && !isRisk(r));
  const n = (result.items || []).length || 1;
  const failCount = [].concat(result.violations || [], result.anomalies || [], result.low_ratio_items || []).length;
  score -= Math.min(40, failCount * 8);
  score -= Math.min(25, riskRows.length * 5);
  if (result.low_ratio_review_required) { score -= 12; reasons.push('存在低价项'); }
  score = Math.max(0, Math.min(100, Math.round(score)));
  let grade, badge;
  if (score >= 90) { grade = 'AA+'; badge = 'gain'; }
  else if (score >= 75) { grade = 'A'; badge = 'neutral'; }
  else if (score >= 60) { grade = 'B'; badge = 'warn'; }
  else { grade = 'C'; badge = 'warn'; }
  const audit = result.status === 'PASS' ? (score >= 90 ? '合规闸门通过' : (score >= 60 ? '合规待关注' : '需人工复核')) : '闸门未通过';
  const maxDev = (result.items || []).reduce((m, r) => Math.max(m, Math.abs((Number(r['报价比率'] ?? 1) || 0) - 1)), 0);
  return {
    score, grade, audit, badge, maxDev: (maxDev * 100).toFixed(1) + '%',
    safe: Math.round(((n - (earlyRows.length + riskRows.length)) / n) * 100),
    early: Math.round((earlyRows.length / n) * 100),
    // risk 取余数，保证三段恒为 100%（避免分段各自四舍五入造成 >100% 溢出）
    risk: Math.max(0, 100 - Math.round(((n - (earlyRows.length + riskRows.length)) / n) * 100) - Math.round((earlyRows.length / n) * 100)),
  };
}

// 派生进项抵扣总额：与后端分项精算同一口径，直接消费 cost_input_tax.multiplier(k) 反推精确值
//   k = 1 − Σpⱼrⱼ/(1+rⱼ)，抵扣占比 = 1 − k，则抵扣额 = Σ含税成本 × (1 − k)
//   避免用单一 credit_ratio 加权近似（0% 人工行会被误判为全抵）。
function computeInputVat(result) {
  const tax = (result && result.cost_input_tax) || {};
  const k = tax.multiplier != null && isFinite(Number(tax.multiplier)) ? Number(tax.multiplier) : null;
  let credit;
  if (k != null) {
    credit = Math.max(0, 1 - k);               // 权威口径：精确抵扣占比
  } else {
    // 后端未给 k（如被 BLOCKED）时回退单一占比，仅作占位
    credit = Math.max(0, Number(tax.credit_ratio == null ? 0 : tax.credit_ratio)) || 0;
  }
  const raw = (result.items || []).reduce((s, r) => s + (Number(r['含税成本单价'] ?? 0) * Number(r['工程量'] ?? 0)), 0);
  const vat = Math.max(0, credit * raw);
  return { vat, share: (credit * 100).toFixed(1) + '%', k: k != null ? k.toFixed(4) : '—', status: credit > 0 ? '抵扣达标' : '不可抵扣' };
}

// 明细表（收到真实 result.items，中文键）
let dashItems = [];
let dashFilter = 'all';
let dashSortMargin = false;
// 冻结列宽度同步：首列实测宽作为第二列 sticky left 偏移（列宽随内容变化，硬编码会错位）
function syncFrozenCols() {
  const wrap = document.querySelector('.table-scroll');
  if (!wrap) return;
  const first = wrap.querySelector('tbody tr td:nth-child(1):not([colspan])');
  if (first) wrap.style.setProperty('--frozen-w', Math.ceil(first.getBoundingClientRect().width) + 'px');
}

function renderDashTable() {
  const body = document.querySelector('#tableBody');
  const count = document.querySelector('#tableCount');
  if (!body) return;
  let list = (dashItems || []).slice();
  if (dashFilter === 'risk') {
    list = list.filter(r => (Number(r['报价比率'] ?? 1) < 0.5) || r['报价状态'] === 'MANUAL_REVIEW' || (Number(r['单项毛利'] ?? 0) < 0));
  } else if (dashFilter === 'early') {
    list = list.filter(r => Number(r['报价比率'] ?? 0) >= 0.92 && r['报价状态'] !== 'MANUAL_REVIEW');
  }
  if (dashSortMargin) list = list.slice().sort((a, b) => (Number(b['单项毛利'] ?? 0)) - (Number(a['单项毛利'] ?? 0)));
  if (count) count.textContent = `合计清单项: ${(dashItems || []).length} 项（显示 ${list.length}）`;
  if (!list.length) { body.innerHTML = '<tr><td colspan="10" style="text-align:center;color:var(--text-tertiary);padding:24px">当前筛选无子目</td></tr>'; return; }
  body.innerHTML = list.map(row => {
    const ratio = Number(row['报价比率']);
    const qty = Number(row['工程量'] ?? 0);
    const quote = Number(row['最优报价单价'] ?? 0);
    const total = qty * quote;
    const ratioPercent = (ratio * 100).toFixed(1);
    let tagClass = 'safe', tagLabel = '稳健平准';
    const mss = row['报价状态'];
    if (mss === 'MANUAL_REVIEW') { tagClass = 'risk'; tagLabel = '人工报价'; }
    else if (Number(row['单项毛利'] ?? 0) < 0 || ratio < 0.5) { tagClass = 'risk'; tagLabel = '需复核'; }
    else if (ratio >= 0.92) { tagClass = 'early'; tagLabel = '早结倾斜 ' + ratioPercent + '%'; }
    else { tagClass = 'safe'; tagLabel = '平准 ' + ratioPercent + '%'; }
    return `<tr>
      <td class="tabular cell-code">${esc(row['项目编码'] ?? '')}</td>
      <td><strong>${esc(row['项目名称'] ?? '')}</strong></td>
      <td>${esc(row['单位'] ?? '—')}</td>
      <td class="num tabular">${fmt(qty, 3)}</td>
      <td class="cap num tabular">${fmt(row['最高限价'])}</td>
      <td class="cost num tabular">${fmt(row['有效成本单价'] ?? row['含税成本单价'])}</td>
      <td class="quote num tabular">${fmt(quote)}</td>
      <td class="num tabular"><span class="ratio-pill-cell"><span class="mini-progress"><span class="mini-progress-fill" style="width:${Math.min(ratio * 100, 100)}%"></span></span><span>${ratioPercent}%</span></span></td>
      <td class="num tabular cell-total">${fmt(total)}</td>
      <td><span class="status-tag ${tagClass}">${tagLabel}</span><span class="note-cell">${esc(row['说明'] ?? '')}</span></td>
    </tr>`;
  }).join('');
  requestAnimationFrame(syncFrozenCols);
}

// KPI 看板
function renderKpi(result) {
  if (!result) return;
  const total = Number(result.target_total ?? 0);
  const objective = Number(result.objective ?? 0);
  const comp = computeCompliance(result);
  const vatObj = computeInputVat(result);
  const marginRate = total > 0 ? (objective / total) * 100 : 0;
  setText('kpiTotalVal', total ? `¥${total.toLocaleString('zh-CN',{minimumFractionDigits:2})}` : '—');
  setText('kpiTotalCap', result.competitive_budget ? `竞争预算 ${Number(result.competitive_budget).toLocaleString('zh-CN',{maximumFractionDigits:0})}` : '—');
  setText('kpiTotalDelta', result.status === 'PASS' ? '锁定约束' : '未平衡');
  setText('kpiMarginVal', objective ? `¥${objective.toLocaleString('zh-CN',{minimumFractionDigits:2})}` : '—');
  setText('kpiMarginRate', `毛利率 ${marginRate.toFixed(1)}%`);
  setText('kpiCashflowTag', result.status === 'PASS' ? '结算调整后利润 · 不含税' : '待计算');
  // 评分格需让 grade 成为真元素（setText 用 textContent 会把 <span> 当字面文本显示），grade 为固定枚举非用户输入，安全用 innerHTML
  const scoreEl = document.querySelector('#kpiScoreVal');
  if (scoreEl) scoreEl.innerHTML = `${comp.score} <span style="font-size:13px;color:var(--module-3)">${comp.grade}</span>`;
  setText('kpiAuditTag', comp.audit);
  const auditBadge = document.querySelector('#kpiAuditTag');
  if (auditBadge) auditBadge.className = 'delta-badge ' + comp.badge;
  setText('kpiMaxDev', `最大偏离 ${comp.maxDev}`);
  document.querySelector('#scaleSafe').style.width = comp.safe + '%';
  document.querySelector('#scaleEarly').style.width = comp.early + '%';
  document.querySelector('#scaleRisk').style.width = comp.risk + '%';
  setText('kpiVatVal', `¥${vatObj.vat.toLocaleString('zh-CN',{minimumFractionDigits:2})}`);
  setText('kpiVatK', `k: ${vatObj.k}`);
  setText('kpiVatShare', `材料抵扣贡献 ${vatObj.share}`);
  setText('kpiVatStatus', vatObj.status);
  renderDashTable();
}

function renderDashboard(result, { animate = true } = {}) {
  dashItems = (result && result.items) || [];
  dashFilter = 'all';
  dashSortMargin = false;
  setDashboardVisible(true);
  const stage = document.querySelector('.canvas-column');
  if (stage) {
    stage.classList.remove('dash-arrive', 'scheme-fade');
    if (animate) { void stage.offsetWidth; stage.classList.add('dash-arrive'); }
    else { stage.classList.add('scheme-fade'); }
  }
  document.querySelectorAll('.filter-chip').forEach(c => c.classList.toggle('active', c.dataset.filter === 'all'));
  document.querySelectorAll('.kpi-card').forEach(c => c.classList.remove('active-drill'));
  renderKpi(result);
  if (!animate) pulseValues(); // 方案切换：卡片静止，仅 KPI 数值平滑淡入
  refreshSchemeTabs();
  alignDetailTable();
  syncDrillClear();
  triggerToast(result.status === 'PASS' ? '推演完成' : '计算完成（需复核）');
}

// 方案切换时 KPI 数值平滑淡入：.kpi-val 由 setText 原地更新（元素持久），需强制重启动画
function pulseValues() {
  const vals = document.querySelectorAll('#quoteView .kpi-val');
  if (!vals.length) return;
  vals.forEach(v => v.classList.remove('val-fade'));
  const stage = document.querySelector('.canvas-column');
  if (stage) void stage.offsetWidth;
  vals.forEach(v => v.classList.add('val-fade'));
}

// 明细表底部与左栏「报价资料」卡底部对齐：按「报价卡底部 − 明细表顶部」动态限制明细表高度，
// 行多时表内纵向滚动（grid 行高由左栏决定，右栏不再被明细表撑长）。
function alignDetailTable() {
  const ts = document.querySelector('.table-section');
  if (!ts || ts.classList.contains('hidden')) return;
  const qc = Array.from(document.querySelectorAll('.param-column > .card')).pop();
  if (!qc) return;
  const top = (el) => { let y = 0; while (el) { y += el.offsetTop; el = el.offsetParent; } return y; };
  const avail = (top(qc) + qc.offsetHeight) - top(ts);
  ts.style.maxHeight = Math.max(240, Math.round(avail)) + 'px';
}

// ---- A/B/C 方案切换（P0 策略语义）：槽位 A=当前项目 strategy=optimal、槽位 B=strategy=uniform、
// 槽位 C=恒灰显「方案 C · 策略待定」（disabled）。历史方案缺省视为 optimal。
let schemePlanIds = [];
const planStrategyOverride = {}; // 会话内回填：后端尚未持久化 strategy 时，用本会话生成的 plan_id→strategy 兜底
function _planStrategy(p) {
  if (!p) return 'optimal';
  if (p.strategy) return p.strategy;
  if (planStrategyOverride[p.id]) return planStrategyOverride[p.id];
  return (p.result || {}).strategy || 'optimal';
}
function _planByStrategy(strategy) {
  return (currentProjectPlans() || []).find(p => _planStrategy(p) === strategy) || null;
}
// 方案切换条只在「右栏已加载某方案组结果」时显示（A/B/C 槽位轻量切换）
function syncSchemeSwitcher() {
  const bar = document.querySelector('.scheme-switcher-bar');
  if (!bar) return;
  const show = Boolean(dashActive && activeGroupId && activeGroup);
  bar.classList.toggle('hidden', !show);
}
// 最近已算槽位方案：A → B → C 优先返回（按 saved_at 取最新）
function recentSlotPlanId(group) {
  const s = (group && group.strategy_slots) || {};
  const computed = HUB_SLOT_DEFS.map(d => ({ d, slot: s[d.key] }))
    .filter(x => x.slot && (x.slot.plan_id || (x.slot.summary && x.slot.summary.plan_id)));
  if (!computed.length) return null;
  computed.sort((a, b) => String((b.slot.summary || {}).saved_at || '').localeCompare(String((a.slot.summary || {}).saved_at || '')));
  return (computed[0].slot.plan_id || computed[0].slot.summary.plan_id);
}
// 在方案中心定位并展开指定组
function openGroupById(groupId) {
  if (!groupId) return;
  expandedGroups.add(groupId);
  renderHubCards();
}
function refreshSchemeTabs() {
  const tabs = Array.from(document.querySelectorAll('.scheme-tab'));
  if (!tabs.length) return;
  const slotDefs = [
    { slot: 'A', strategy: 'optimal', label: '逐项最优' },
    { slot: 'B', strategy: 'uniform', label: '等比下浮' },
    { slot: 'C', strategy: null, label: '策略待定' },
  ];
  schemePlanIds = [null, null, null];
  const slots = (activeGroup && activeGroup.strategy_slots) || {};
  tabs.forEach((t, i) => {
    const def = slotDefs[i];
    const s = slots[def.slot] || {};
    const pid = s.plan_id || (s.summary && s.summary.plan_id) || null;
    schemePlanIds[i] = pid;
    // 统一重建内容：左侧指示点 + 文字标签
    t.textContent = '';
    const dot = document.createElement('span');
    dot.className = 'tab-indicator';
    dot.setAttribute('aria-hidden', 'true');
    t.appendChild(dot);
    const label = document.createElement('span');
    label.className = 'tab-label';
    label.textContent = `方案 ${def.slot} · ${def.label}`;
    label.title = pid ? String(((s.summary || {}).plan_id) || pid) : '';
    t.appendChild(label);
    t.title = pid ? String(((s.summary || {}).plan_id) || pid) : '';
    if (i === 2) { // 槽位 C：恒灰显「策略待定」，不可点
      t.disabled = true;
      t.setAttribute('aria-disabled', 'true');
      t.classList.remove('active');
    } else {
      t.disabled = false;
      t.removeAttribute('aria-disabled');
    }
  });
  syncSchemeSwitcher();
}
function bindSchemeTabs() {
  const letters = ['A', 'B', 'C'];
  document.querySelectorAll('.scheme-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const idx = Number(tab.dataset.scheme);
      if (tab.disabled) return; // 槽位 C 恒灰显
      document.querySelectorAll('.scheme-tab').forEach(t => { t.classList.toggle('active', t === tab); t.setAttribute('aria-selected', String(t === tab)); });
      document.querySelectorAll('.kpi-card').forEach(c => c.classList.remove('active-drill'));
      const pid = schemePlanIds[idx];
      const bal = document.querySelector('#schemeBalanceText');
      if (pid) { if (bal) bal.textContent = '已映射方案 ' + letters[idx]; openSlot(pid, activeGroup, { animate: false }); triggerToast('已切换至方案 ' + letters[idx]); }
      else { if (bal) bal.textContent = '该槽位暂无方案'; triggerToast('该方案槽位暂无方案'); }
    });
  });
}
function updateSchemeBalance() {
  const bal = document.querySelector('#schemeBalanceText');
  const pidN = (activeGroup && Object.values(activeGroup.strategy_slots || {}).filter(s => s && (s.plan_id || (s.summary && s.summary.plan_id))).length) || 0;
  if (bal) bal.textContent = (activeGroup ? '当前组已算 ' + pidN + ' 槽' : '未加载方案组') + ' ｜ 槽位 A=逐项最优 / B=等比下浮';
}

// ---- 明细筛选 chips + KPI 穿透 ----
function bindFilters() {
  // KPI 穿透激活态与 aria-pressed 同步（P1-6）
  const applyDrillAria = () => {
    document.querySelectorAll('.kpi-card[aria-pressed]').forEach(c =>
      c.setAttribute('aria-pressed', c.classList.contains('active-drill') ? 'true' : 'false'));
  };
  const resetDrill = () => {
    dashFilter = 'all'; dashSortMargin = false;
    document.querySelectorAll('.filter-chip').forEach(c => c.classList.toggle('active', c.dataset.filter === 'all'));
    document.querySelectorAll('.kpi-card').forEach(c => c.classList.remove('active-drill'));
    applyDrillAria();
    renderDashTable(); syncDrillClear();
  };
  document.querySelectorAll('.filter-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-chip').forEach(c => c.classList.toggle('active', c === btn));
      dashFilter = btn.dataset.filter;
      renderDashTable(); syncDrillClear();
    });
  });
  const clearChip = document.querySelector('#clearDrillChip');
  if (clearChip) clearChip.addEventListener('click', resetDrill);
  // KPI 卡即按 role="button"：补 Enter/Space 键盘触发（P1-6）
  document.querySelectorAll('.kpi-card[role="button"]').forEach(card => {
    card.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); card.click(); }
    });
  });
  const total = document.querySelector('#kpiCardTotal');
  if (total) total.addEventListener('click', resetDrill);
  const margin = document.querySelector('#kpiCardMargin');
  if (margin) margin.addEventListener('click', () => { dashSortMargin = !dashSortMargin; margin.classList.toggle('active-drill', dashSortMargin); applyDrillAria(); renderDashTable(); syncDrillClear(); });
  const score = document.querySelector('#kpiCardScore');
  if (score) score.addEventListener('click', () => { dashFilter = dashFilter === 'risk' ? 'all' : 'risk'; document.querySelectorAll('.filter-chip').forEach(c => c.classList.toggle('active', c.dataset.filter === dashFilter)); score.classList.toggle('active-drill', dashFilter === 'risk'); applyDrillAria(); renderDashTable(); syncDrillClear(); });
}

// ---- 比率滑块：同步 ratioMin + 低价警报 ----
// 安全防线双滑块：下限/上限共同驱动 ratio_min/ratio_max，区间值显示在右上角
// 碰撞锁：仅吸附「被拖滑块」到对方边界（下限 ≤ 上限，且物理区间 ≥ 5%），
// 不改写对方 min/max —— 避免改几何导致另一把 thumb 与刻度错位
function refreshRatioUI(ev) {
  const lo = document.querySelector('#ratioLow'), hi = document.querySelector('#ratioHigh');
  if (!lo || !hi) return;
  const t = ev && ev.target;
  let L = +lo.value, H = +hi.value;
  if (t === lo && L > H - 5) L = H - 5;   // 拖下限越界：钳到上限-5
  if (t === hi && H < L + 5) H = L + 5;   // 拖上限越界：钳到下限+5
  if (L > H) { L = H; lo.value = H; }     // 兜底（程序恢复等无拖动方场景）
  if (H < L) { H = L; hi.value = L; }
  L = Math.max(0, Math.min(100, L)); H = Math.max(0, Math.min(100, H));
  lo.value = L; hi.value = H;
  const rm = document.querySelector('#ratioMin'), rM = document.querySelector('#ratioMax');
  if (rm) rm.value = (L / 100).toFixed(2);
  if (rM) rM.value = (H / 100).toFixed(2);
  lo.setAttribute('aria-valuetext', L + '%');
  hi.setAttribute('aria-valuetext', H + '%');
  const text = document.querySelector('#ratioRangeText');
  if (text) text.textContent = `${L}% ~ ${H}%`;
  // 激活区间填充块：紧跟双滑块位置
  const fill = document.querySelector('#ratioFill');
  if (fill) { fill.style.left = L + '%'; fill.style.width = (H - L) + '%'; }
  // 风险反馈：上限逼近（<55%）或区间跌入废标区（<50%）→ 轨道赤赭呼吸态 + 紧凑警示条
  // （不再自动展开大警告框打断操作；留痕表单由用户点击警示条手动展开）
  const risk = L < 50 || H < 55;
  const guard = document.querySelector('.guardrail');
  if (guard) guard.classList.toggle('is-risk', risk);
  const rb = document.querySelector('#riskAlertDrawer');
  if (rb) rb.classList.toggle('active', risk);
}
// 双滑块 z 序提权：单一函数，统一读写（P2-11）。CSS 只留基础 z=2。
function refreshRatioHover(x) {
  const lo = document.querySelector('#ratioLow'), hi = document.querySelector('#ratioHigh');
  if (!lo || !hi) return lo;
  const track = lo.closest('.guardrail-track');
  if (track && x != null) {
    const rect = track.getBoundingClientRect();
    if (rect.width) {
      const p = ((x - rect.left) / rect.width) * 100;
      const dLo = Math.abs(p - lo.value), dHi = Math.abs(p - hi.value);
      lo.style.zIndex = dLo <= dHi ? '4' : '3';
      hi.style.zIndex = dHi < dLo ? '4' : '3';
    }
  }
  return lo;
}
function bindRatioSlider() {
  const lo = document.querySelector('#ratioLow'), hi = document.querySelector('#ratioHigh');
  if (!lo || !hi) return;
  ['#ratioLow', '#ratioHigh'].forEach(s => { const el = document.querySelector(s); if (el) el.addEventListener('input', refreshRatioUI); });
  // 重叠防死锁：pointer 靠近哪把 thumb 就动态提权（基础层 z 相等，由 refreshRatioHover 统一提权）
  const track = lo.closest('.guardrail-track');
  if (track) {
    track.addEventListener('pointermove', (e) => { refreshRatioHover(e.clientX); });
    track.addEventListener('pointerleave', () => { lo.style.zIndex = ''; hi.style.zIndex = ''; });
  }
  // 风险警示条：点击展开/收起留痕表单（aria-expanded 同步）
  const riskBtn = document.querySelector('#riskSummaryBtn');
  if (riskBtn) riskBtn.addEventListener('click', () => {
    const open = riskBtn.closest('.risk-alert-box').classList.toggle('open');
    riskBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  refreshRatioUI();
}

// ---- 测算准备就绪度检查清单（测算前空态）+ 主舞台可见性 ----
function _taxDeclared() {
  const mode = (document.querySelector('#taxMode') || {}).value;
  if (mode === 'NONE') return false;
  return document.querySelectorAll('#composeRows .compose-row').length > 0;
}
function _taxClosed() {
  const mode = (document.querySelector('#taxMode') || {}).value;
  if (mode === 'NONE') return true;
  const rows = document.querySelectorAll('#composeRows .compose-row');
  if (!rows.length) return false;
  let total = 0;
  rows.forEach(r => { const p = Number((r.querySelector('[data-field="proportion"]') || {}).value || 0) / 100; if (!Number.isNaN(p)) total += p; });
  return Math.abs(total - 1) < 0.005;
}
function refreshPrepare() {
  const panel = document.querySelector('#preparePanel');
  if (!panel) return;
  const kpi = document.querySelector('.kpi-row'), table = document.querySelector('.table-section');
  const cs = document.querySelector('#compareStage');
  if (kpi) kpi.classList.add('hidden');
  if (table) table.classList.add('hidden');
  if (cs) cs.classList.add('hidden');
  const cap = document.querySelector('#statusCapsule');
  if (cap) cap.classList.add('hidden');
  panel.classList.remove('hidden');
  const projSel = document.querySelector('#projectId');
  // 门控规则：未选择关联项目即锁死全部控件（原「手动填写」路径需先选项目解锁）
  const projOn = !!(projSel && projSel.value);
  const capF = (document.querySelector('#capFile') || {}).files, costF = (document.querySelector('#costFile') || {}).files;
  const filesOn = (capF && capF.length) && (costF && costF.length);
  const declared = _taxDeclared(), closed = _taxClosed();
  const tag = (s) => ({ ok: '<span class="prep-state ok">就绪</span>', pending: '<span class="prep-state">待就绪</span>', alert: '<span class="prep-state alert">待处理</span>' })[s];
  const set = (id, state, label) => {
    const el = document.getElementById(id);
    if (el) {
      const prev = el.dataset.state;
      el.dataset.state = state;
      el.innerHTML = '<span class="prep-dot"></span><span class="prep-text">' + label + '</span>' + tag(state);
      // 待就绪 → 就绪：打勾弹跳微动效（操作闭环即时反馈）
      if (prev !== 'ok' && state === 'ok') {
        const dot = el.querySelector('.prep-dot');
        if (dot) dot.classList.add('pop');
      }
    }
  };
  set('prepProject', projOn ? 'ok' : 'pending', projOn ? '已完成：关联投标项目，目标总报价与固定税前项可配置' : '待完成：请先选择「关联投标项目」以解锁报价参数');
  set('prepFiles', filesOn ? 'ok' : 'pending', filesOn ? '已完成：限价清单与成本清单均已导入（支持拖拽）' : '待完成：请导入限价清单与成本清单（支持拖拽）');
  set('prepTax', closed ? 'ok' : (declared ? 'alert' : 'pending'), closed ? '已完成：成本进项抵扣已声明且占比合计 100%' : (declared ? '注意：已声明构成但占比合计须为 100%' : '待完成：请声明成本进项抵扣构成（或选不可抵扣）'));
  // 三项全就绪 → 右栏主动作「识别文件并计算」呼吸光晕（视线接力）；Dock 主 CTA 空态置灰唯一化
  const allReady = projOn && filesOn && closed;
  const calc = document.querySelector('#calculateBtn');
  if (calc) calc.classList.toggle('ready-pulse', allReady && !dashActive);
  syncDockCta();
}
function setDashboardVisible(hasResult) {
  dashActive = !!hasResult;
  const panel = document.querySelector('#preparePanel'), ps = document.querySelector('#previewStage'), kpi = document.querySelector('.kpi-row'), table = document.querySelector('.table-section');
  if (panel) panel.classList.toggle('hidden', hasResult);
  if (ps) ps.classList.toggle('hidden', hasResult);
  if (kpi) kpi.classList.toggle('hidden', !hasResult);
  if (table) table.classList.toggle('hidden', !hasResult);
  // 结果态：准备面板折叠为 38px 状态胶囊条（Status Capsule），释放垂直空间给明细表
  const cap = document.querySelector('#statusCapsule');
  if (cap) { cap.classList.toggle('hidden', !hasResult); if (hasResult) fillStatusCapsule(); }
  syncDockCta();
}
// 状态胶囊条文案（口径与结果 toast 一致：PASS=方案就绪，否则需复核）
function fillStatusCapsule() {
  const t = document.querySelector('#statusCapsuleText');
  if (!t) return;
  t.textContent = (lastResult && lastResult.status === 'PASS')
    ? '推演完成 · 方案组已就绪，可切换 A/B/C 或重新推演'
    : '计算完成 · 结果需复核，可切换方案查看';
}

// ---- FAB 操作坞（P0 收敛为 3 键） ----
function setDockBusy(busy) {
  document.querySelectorAll('.floating-dock .dock-btn').forEach(b => b.classList.toggle('dock-busy', busy));
  if (busy) document.querySelectorAll('.floating-dock .dock-btn').forEach(b => b.setAttribute('aria-busy', 'true'));
  else document.querySelectorAll('.floating-dock .dock-btn').forEach(b => b.removeAttribute('aria-busy'));
}
// 主 CTA 文案固定为「一键重新推演」：无结果=识别计算，有结果=按当前参数重算，路由逻辑在 bindDock 中
function syncDockCta() {
  const btn = document.querySelector('#dockCalcBtn');
  const label = document.querySelector('#dockCalcLabel');
  if (!btn) return;
  if (label) label.textContent = '一键重新推演';
  btn.setAttribute('aria-label', '一键重新推演');
  // 状态机主按钮唯一化：空态置灰（主动作聚焦 preparePanel 内「识别文件并计算」），结果态启用（重算）
  btn.disabled = !dashActive;
  btn.classList.remove('ready-pulse'); // 呼吸光晕已转移至 preparePanel 主动作
  // 导出按钮同理：仅在存在可下载的 excel_download_url 时才启用，避免空态点出「暂无可导出」toast
  const expBtn = document.querySelector('#dockExportBtn');
  if (expBtn) {
    expBtn.disabled = !(lastResult && lastResult.excel_download_url);
    expBtn.setAttribute('aria-disabled', expBtn.disabled ? 'true' : 'false');
  }
}
function bindDock() {
  const calc = document.querySelector('#dockCalcBtn');
  if (calc) calc.addEventListener('click', () => {
    // 情境主 CTA：有结果=「按当前参数重算」（runRecompute），无结果=「识别并计算」
    if (lastResult) runRecompute();
    else { const t = document.querySelector('#calculateBtn'); if (t) t.click(); }
  });
  const exportBtn = document.querySelector('#dockExportBtn');
  if (exportBtn) exportBtn.addEventListener('click', () => {
    if (!lastResult) { triggerToast('暂无可导出的结果'); return; }
    if (lastResult.excel_download_url) { window.location.href = API_BASE + lastResult.excel_download_url; triggerToast('已开始下载 Excel 报表'); }
    else triggerToast('暂无可导出的结果');
  });
  // 「方案中心」：操作坞唯一入口，打开全屏方案管理 + 多方案对比覆盖层（空态在 Hub 内提示）
  const diff = document.querySelector('#diffDrawerBtn');
  if (diff) diff.addEventListener('click', () => {
    // 打开状态下再次点击 → 收起弹层（toggle）
    const hub = document.querySelector('#planHub');
    if (hub && hub.classList.contains('open')) closePlanHub();
    else openPlanHub();
  });
  syncDockCta();
}

/* ---- 方案中心（#planHub）右下角吸附弹层 ----
   列表视图：当前关联项目的方案组 → 槽位（勾选对比）；
   勾选 ≥2 个槽位 → POST /api/project/compare → 结果渲染右栏 #compareStage（弹层保持组列表）。 */
function updateHubSelection() {
  hubSelected = new Set(Array.from(document.querySelectorAll('#planHubBody .slot-check input:checked')).map(cb => cb.value));
  const bar = document.querySelector('#planHubCompareBar');
  const count = document.querySelector('#planHubCount');
  const base = document.querySelector('#planHubBase');
  if (count) count.textContent = `已选 ${hubSelected.size} 个槽位`;
  if (base) {
    const opts = currentProjectPlans().filter(p => hubSelected.has(p.id));
    const prev = base.value;
    base.innerHTML = [{ value: '', label: '— 基准（默认首个勾选）—' }].concat(opts.map(p => ({ value: p.id, label: p.name || p.id }))).map(o => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('');
    if (opts.some(p => p.id === prev)) base.value = prev;
    else if (opts.length) base.value = opts[0].id;   // 默认首个勾选
  }
  if (bar) bar.classList.toggle('hidden', hubSelected.size < 2);
}
function openPlanHub() {
  const hub = document.querySelector('#planHub');
  if (!hub) return;
  hubView = 'list';
  hubSelected.clear();
  applyHubWidth();
  loadProjectGroups();
  updateHubSelection();
  hub.classList.add('open');
  hub.setAttribute('aria-hidden', 'false');
  const dock = document.querySelector('#diffDrawerBtn');
  if (dock) dock.setAttribute('aria-expanded', 'true');
  const close = document.querySelector('#planHubCloseBtn');
  if (close) close.focus();
}
function closePlanHub() {
  const hub = document.querySelector('#planHub');
  if (hub) { hub.classList.remove('open'); hub.setAttribute('aria-hidden', 'true'); }
  hubView = 'list';
  hubSelected.clear();
  const dock = document.querySelector('#diffDrawerBtn');
  if (dock) dock.setAttribute('aria-expanded', 'false');
  if (dock) dock.focus();
}
// —— 对比结果弹层（#cmpModal）：方案中心「开始对比」结果的居中式呈现 ——
function openCompareModal() {
  const modal = document.querySelector('#cmpModal');
  if (!modal) return;
  modal.classList.add('open');
  modal.setAttribute('aria-hidden', 'false');
  const closeBtn = document.querySelector('#cmpModalCloseBtn');
  if (closeBtn) closeBtn.focus();
}
function closeCompareModal() {
  const modal = document.querySelector('#cmpModal');
  if (!modal) return;
  modal.classList.remove('open');
  modal.setAttribute('aria-hidden', 'true');
}
// 宽度：默认 = 操作坞宽；可拖至 260~490 并存 localStorage(planHubWidth)
const HUB_W_KEY = 'planHubWidth';
function applyHubWidth() {
  const hub = document.querySelector('#planHub');
  if (!hub) return;
  const saved = localStorage.getItem(HUB_W_KEY);
  let w = saved ? parseInt(saved, 10) : estimateDockWidth();
  if (!w || isNaN(w)) w = 340;
  hub.style.width = Math.min(490, Math.max(260, w)) + 'px';
}
function estimateDockWidth() {
  const d = document.querySelector('.floating-dock');
  return d ? d.offsetWidth : 340;
}
function bindHubResize() {
  const hub = document.querySelector('#planHub');
  const handle = document.querySelector('#planHubResize');
  if (!hub || !handle) return;
  handle.addEventListener('mousedown', (e) => {
    e.preventDefault(); e.stopPropagation();
    const startX = e.clientX, startW = hub.offsetWidth;
    const onMove = (ev) => {
      // 手柄在左缘、右缘锚定：左拖(dx<0)应加宽 → startW - dx
      const w = Math.min(490, Math.max(260, startW - (ev.clientX - startX)));
      hub.style.width = w + 'px';
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      localStorage.setItem(HUB_W_KEY, String(hub.offsetWidth));
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}
async function runHubCompare() {
  const selected = Array.from(hubSelected);
  if (selected.length < 2) { setMessage('多方案对比至少需要勾选 2 个槽位。'); return; }
  // 限定同一项目：槽位均来自当前方案组（同一关联项目），天然同项目；按真实项目 id 兜底
  const byId = Object.fromEntries(currentProjectPlans().map(p => [p.id, p]));
  const projs = new Set(selected.map(id => { const rec = byId[id] || {}; const raw = rec.project_name || rec.project_id || rec.name || ''; return nameToId[raw] || raw; }));
  if (projs.size > 1) { setMessage('多方案对比限定同一项目（单价差异与利润才有可比意义），请仅勾选同一项目的多个槽位。', 'error'); return; }
  const base = document.querySelector('#planHubBase').value;
  const btn = document.querySelector('#planHubRunBtn');
  if (btn) btn.disabled = true;
  setMessage('正在对比方案，请稍候。');
  const data = new FormData();
  data.append('id', selected.join(','));
  if (base) data.append('base', base);
  try {
    const response = await fetch(API_BASE + '/api/project/compare', {method:'POST', body:data});
    const res = await response.json();
    if (!response.ok || res.status !== 'PASS') throw new Error(res.reason || '对比失败');
    renderCompare(res);                         // 右栏 #compareStage 结果落点
    setMessage(`对比完成：${res.plan_ids.length} 个方案。低于 50% 报价比率的为风险项，是否构成废标以招标文件为准。`, 'success');
  } catch (error) { setMessage(`对比失败：${error.message}`, 'error'); }
  finally { if (btn) btn.disabled = false; }
}
function bindPlanHub() {
  const closeBtn = document.querySelector('#planHubCloseBtn');
  if (closeBtn) closeBtn.addEventListener('click', closePlanHub);
  const run = document.querySelector('#planHubRunBtn');
  if (run) run.addEventListener('click', runHubCompare);
  const cmpClose = document.querySelector('#cmpModalCloseBtn');
  if (cmpClose) cmpClose.addEventListener('click', closeCompareModal);
  const cmpMask = document.querySelector('#cmpModalMask');
  if (cmpMask) cmpMask.addEventListener('click', closeCompareModal);
  const hub = document.querySelector('#planHub');
  if (hub) { bindHubResize(); hub.addEventListener('click', e => { if (e.target === hub) closePlanHub(); }); }
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    const modal = document.querySelector('#cmpModal');
    if (modal && modal.classList.contains('open')) { closeCompareModal(); return; }
    const hub = document.querySelector('#planHub');
    if (hub && hub.classList.contains('open')) closePlanHub();
  });
}

// —— 全局项目上下文：#projectId 切换 → 加载该项目「定稿组(无则最近组)」最近槽位到右栏，或回到空态 ——
async function onGlobalProjectChange() {
  syncProjectGate();
  activeGroupId = ''; activeGroup = null; dashActive = false; lastResult = null;
  expandedGroups.clear(); hubSelected.clear();
  closeCompareModal(); // 切换项目后旧对比结果失效，一并收起弹层
  const ps = document.querySelector('#previewStage'); if (ps) { ps.classList.add('hidden'); ps.innerHTML = ''; }
  if (!curProjectIdUuid()) {
    // 未选项目 → 右栏回就绪空态，左栏参数/统计恢复默认
    const kpi = document.querySelector('.kpi-row'); if (kpi) kpi.classList.add('hidden');
    const table = document.querySelector('.table-section'); if (table) table.classList.add('hidden');
    const cs = document.querySelector('#compareStage'); if (cs) cs.classList.add('hidden');
    const pd = document.querySelector('#preparePanel'); if (pd) pd.classList.remove('hidden');
    ['targetTotal', 'fixedPretax'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    renderHubCards();
    syncSchemeSwitcher();
    refreshPrepare();
    syncDockCta();
    return;
  }
  await loadProjectGroups();
  // 优先加载「已定稿组」；无定稿组时回退最近保存的组
  const target = groups.find(g => g.finalized) || groups[0];
  const slotPid = target ? recentSlotPlanId(target) : null;
  if (target && slotPid) await openSlot(slotPid, target);
  else {
    // 项目已选但暂无可用槽位 → 仅显示就绪空态，不显示空预览卡
    const ps = document.querySelector('#previewStage'); if (ps) ps.classList.add('hidden');
    setDashboardVisible(false);
    renderHubCards(); syncSchemeSwitcher();
  }
}

// 初始化：绑定沙盘交互（元素只在 index.html 报价视图存在，缺失时静默跳过）
(function initDashboard() {
  bindSchemeTabs();
  bindFilters();
  bindRatioSlider();
  // 目标总报价 / 固定税前项手动输入 → 实时刷新就绪清单（结果态改参不切回空态）
  ['#targetTotal', '#fixedPretax'].forEach(s => { const el = document.querySelector(s); if (el) el.addEventListener('input', () => { if (!dashActive) refreshPrepare(); }); });
  bindDock();
  bindPlanHub();
  updateSchemeBalance();
  refreshSchemeTabs();
  refreshPrepare();
  // 窗口尺寸变化时重算明细表高度，保持与左栏底部对齐
  let alignT = 0;
  window.addEventListener('resize', () => { clearTimeout(alignT); alignT = setTimeout(alignDetailTable, 120); });
})();