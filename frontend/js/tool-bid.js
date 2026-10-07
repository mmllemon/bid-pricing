/* ===== 不平衡报价工具页 =====
 * 流程：解析招标清单 xlsx（后端 /api/bid/parse）→ 填成本单价/打策略标签 →
 *       一键分配（后端 /api/bid/allocate）→ 手工微调（锁定）→ 保存报价包 / 导出。
 * 数据模型见 docs/BID_DESIGN.md。
 */
(function () {
  'use strict';

  /* P1（与 cable/well/earth/duct 对齐）：tool-common.js 加载失败时整页静默死亡 →
     断言加载标记 + 可见提示后提前返回 */
  if (!window.__toolCommonLoaded) {
    document.addEventListener('DOMContentLoaded', () => {
      const host = document.querySelector('.tool-card') || document.body;
      const bar = document.createElement('div');
      bar.style.cssText = 'margin:12px;padding:12px 16px;border:2px solid #c00;border-radius:8px;background:#fff5f5;color:#a00;font-size:14px;line-height:1.7;';
      bar.textContent = '页面初始化失败：公共脚本 tool-common.js 未加载（可能 404 或被拦截），后续计算全部不可用。请确认文件存在后刷新重试。';
      host.prepend(bar);
    });
    return;
  }

  /* 后端基地址：优先 window.__API_BASE__ 覆盖；否则按当前主机名推导（支持局域网 IP 访问），
     file:// 直接打开时回退 localhost（与 tool-cable.js 同口径） */
  const API_BASE = window.__API_BASE__
    || (location.hostname ? location.protocol + '//' + location.hostname + ':8000' : 'http://localhost:8000');

  const STRATEGIES = { early: '前期', increase: '预计增', normal: '正常', decrease: '预计减' };

  const $ = (id) => document.getElementById(id);
  const rowsEl = $('bRows'), kpisEl = $('bKpis'), probsEl = $('bProblems');

  /** 当前工作态：items 为解析/载入的清单项（含用户填写） */
  let items = [];          // [{key,item_id,name,unit,qty,cap,cost,strategy,price,locked,bound_hit}]
  let lastTotals = null;

  function esc(s) { return window.toolEsc(String(s == null ? '' : s)); }
  function fmt(v, d) { return window.toolFmt(v, d == null ? 2 : d); }
  /* 轻提示：写进解析 hint 区（工具页无 toast，不用 alert 打断） */
  function say(msg) { const h = $('bParseHint'); if (h) h.textContent = msg; }

  function readTableInputs() {
    // 把表格里的成本/策略/报价/锁定读回 items（分配前同步）
    const trs = rowsEl.querySelectorAll('tr[data-key]');
    trs.forEach((tr) => {
      const key = tr.getAttribute('data-key');
      const it = items.find((x) => x.key === key);
      if (!it) return;
      const costEl = tr.querySelector('.in-cost');
      const stEl = tr.querySelector('.in-strategy');
      const priceEl = tr.querySelector('.in-price');
      const lockEl = tr.querySelector('.in-lock');
      it.cost = costEl.value === '' ? null : parseFloat(costEl.value);
      it.strategy = stEl.value || 'normal';
      const pv = parseFloat(priceEl.value);
      it.price = isFinite(pv) ? pv : null;
      it.locked = !!(lockEl && lockEl.checked);
    });
  }

  function renderRows() {
    if (!items.length) {
      rowsEl.innerHTML = '<tr><td colspan="11" class="c" style="color:var(--muted,#888)">先解析招标清单，或载入已保存的报价包</td></tr>';
      return;
    }
    rowsEl.innerHTML = items.map((it) => {
      const costCls = (it.cost == null || !isFinite(it.cost)) ? 'cost-missing' : '';
      const status = it.locked
        ? '<span class="lock-tag">锁定</span>'
        : (it.bound_hit === 'upper' ? '<span class="bound-tag">顶限价</span>'
          : it.bound_hit === 'lower' ? '<span class="bound-tag">到底线</span>' : '');
      const opts = Object.keys(STRATEGIES).map((k) =>
        `<option value="${k}"${(it.strategy || 'normal') === k ? ' selected' : ''}>${STRATEGIES[k]}</option>`).join('');
      return `<tr data-key="${esc(it.key)}">
        <td class="l">${esc(it.item_id)}</td>
        <td class="l" title="${esc(it.name)}">${esc(it.name.length > 26 ? it.name.slice(0, 26) + '…' : it.name)}</td>
        <td class="c">${esc(it.unit)}</td>
        <td class="tabular">${fmt(it.qty, 3)}</td>
        <td class="tabular">${it.cap == null ? '—' : fmt(it.cap)}</td>
        <td><input class="in-cost tabular ${costCls}" type="number" min="0" step="0.01"
            value="${it.cost == null ? '' : it.cost}" placeholder="必填" /></td>
        <td class="c"><select class="in-strategy">${opts}</select></td>
        <td><input class="in-price tabular" type="number" min="0" step="0.01"
            value="${it.price == null ? '' : it.price}" /></td>
        <td class="tabular" data-amount>${it.amount == null ? '—' : fmt(it.amount)}</td>
        <td class="c">${status}</td>
        <td class="c"><input class="in-lock" type="checkbox"${it.locked ? ' checked' : ''} title="锁定后分配时不再调整该项" /></td>
      </tr>`;
    }).join('');
  }

  function renderKpis(t) {
    lastTotals = t || null;
    const set = (id, txt, cls) => {
      const el = $(id);
      el.textContent = txt;
      el.parentElement.classList.remove('bad', 'good');
      if (cls) el.parentElement.classList.add(cls);
    };
    if (!t) { ['kCap', 'kCost', 'kTarget', 'kActual', 'kProfit', 'kResidual'].forEach((id) => set(id, '—')); return; }
    const capTotal = items.reduce((s, it) => s + (it.cap == null ? 0 : it.cap * it.qty), 0);
    set('kCap', fmt(capTotal));
    set('kCost', fmt(t.cost_total));
    set('kTarget', fmt(t.target_total));
    set('kActual', fmt(t.actual_total), Math.abs(t.residual) < 0.005 ? 'good' : 'bad');
    set('kProfit', `${fmt(t.profit)} / ${fmt(t.profit_rate, 2)}%`, t.profit >= 0 ? 'good' : 'bad');
    set('kResidual', fmt(t.residual), Math.abs(t.residual) < 0.005 ? '' : 'bad');
  }

  function renderProblems(problems) {
    if (!problems || !problems.length) { probsEl.hidden = true; probsEl.innerHTML = ''; return; }
    probsEl.hidden = false;
    probsEl.innerHTML = problems.map((p) => `<li>${esc(p)}</li>`).join('');
  }

  async function apiJson(url, opts) {
    const r = await fetch(API_BASE + url, opts);
    const d = await r.json().catch(() => ({}));
    if (!r.ok || d.status === 'BLOCKED') throw new Error(d.reason || ('HTTP ' + r.status));
    return d;
  }

  /* ---------- 解析清单 ---------- */
  $('bParseBtn').addEventListener('click', async () => {
    const f = $('bFile').files[0];
    if (!f) { say('请先选择招标清单 xlsx'); return; }
    readTableInputs();
    const fd = new FormData();
    fd.append('bid_file', f);
    fd.append('project_id', $('bProjName').value.trim() || '当前项目');
    $('bParseHint').textContent = '解析中…';
    try {
      const d = await apiJson('/api/bid/parse', { method: 'POST', body: fd });
      // 保留已填的成本/策略（按 key 匹配），其余重置
      const old = new Map(items.map((it) => [it.key, it]));
      items = d.items.map((it) => {
        const o = old.get(it.key);
        return o ? Object.assign({}, it, { cost: o.cost, strategy: o.strategy }) : it;
      });
      renderRows(); renderKpis(null); renderProblems([]);
      $('bParseHint').textContent =
        `解析完成：${d.parse.n_items} 项参与（源 ${d.parse.n_rows} 行，失败 ${d.parse.n_failed} 行，无控制价 ${d.parse.no_cap} 项）`;
    } catch (e) {
      $('bParseHint').textContent = '解析失败：' + e.message;
    }
  });

  /* ---------- 一键分配 ---------- */
  $('bAllocBtn').addEventListener('click', async () => {
    readTableInputs();
    if (!items.length) { say('先解析清单'); return; }
    const target = parseFloat($('bTarget').value);
    if (!isFinite(target) || target <= 0) { say('请填写目标总价 T'); return; }
    const missing = items.filter((it) => it.cost == null || !isFinite(it.cost));
    if (missing.length && !window.confirm(`有 ${missing.length} 项成本单价未填（将按 0 参与分配），继续吗？`)) return;
    // 锁定的项：报价单价必须已填，否则按成本价锁定
    const locked = {};
    items.forEach((it) => {
      if (it.locked) locked[it.key] = (it.price == null || !isFinite(it.price)) ? (it.cost || 0) : it.price;
    });
    try {
      const d = await apiJson('/api/bid/allocate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: items.map((it) => ({
            key: it.key, qty: it.qty, cost: it.cost, cap: it.cap, strategy: it.strategy,
            name: it.name, unit: it.unit, item_id: it.item_id,
          })),
          target_total: target,
          m_min: parseFloat($('bMMin').value) || 0,
          m_max: parseFloat($('bMMax').value) || 0,
          locked,
        }),
      });
      const byKey = new Map(d.rows.map((r) => [r.key, r]));
      items.forEach((it) => {
        const r = byKey.get(it.key);
        if (r) { it.price = r.price; it.amount = r.amount; it.bound_hit = r.bound_hit; it.locked = r.locked; }
      });
      renderRows(); renderKpis(d.totals); renderProblems(d.problems);
    } catch (e) {
      renderProblems([e.message]);
    }
  });

  /* ---------- 批量策略 ---------- */
  $('bKwBtn').addEventListener('click', () => {
    readTableInputs();
    const kw = $('bKw').value.trim();
    if (!kw || !items.length) return;
    let n = 0;
    items.forEach((it) => {
      if ((it.name + it.item_id).includes(kw)) { it.strategy = $('bKwStrategy').value; n++; }
    });
    renderRows();
    say(`已对 ${n} 项应用策略`);
  });

  /* ---------- 导出 ---------- */
  function tsv() {
    readTableInputs();
    const head = ['项目编码', '项目名称', '单位', '工程量', '控制价', '成本单价', '策略', '报价单价', '合价'].join('\t');
    const lines = items.map((it) => [
      it.item_id, it.name, it.unit, it.qty,
      it.cap == null ? '' : it.cap, it.cost == null ? '' : it.cost,
      STRATEGIES[it.strategy] || it.strategy,
      it.price == null ? '' : it.price, it.amount == null ? '' : it.amount,
    ].join('\t'));
    return head + '\n' + lines.join('\n');
  }
  $('bCopyBtn').addEventListener('click', async () => {
    if (!items.length) return;
    const ok = await window.toolCopyText(tsv());
    say(ok ? '投标清单 TSV 已复制' : '复制失败');
  });
  $('bCsvBtn').addEventListener('click', () => {
    if (!items.length) return;
    const q = (s) => { s = String(s == null ? '' : s); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    const csv = tsv().split('\n').map((ln) => ln.split('\t').map(q).join(',')).join('\n');
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = ($('bProjName').value.trim() || '投标清单') + '.csv';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  });

  /* ---------- 报价包存取 ---------- */
  async function refreshPkgList(selectId) {
    const sel = $('bPkgSel');
    try {
      const d = await apiJson('/api/bid/packages');
      const cur = selectId || sel.value;
      sel.innerHTML = '<option value="">（新建）</option>' + d.items.map((p) =>
        `<option value="${esc(p.bid_id)}">${esc(p.project_name || p.bid_id)} · ${esc(p.version || '')} · ${p.item_count}项 · ${esc(p.updated_at || '')}</option>`).join('');
      if (cur) sel.value = cur;
    } catch (e) { /* 后端不可用时静默 */ }
  }

  $('bSaveBtn').addEventListener('click', async () => {
    readTableInputs();
    if (!items.length) { say('没有可保存的内容'); return; }
    const existId = $('bPkgSel').value;
    const bidId = existId || ('BID-' + new Date().toISOString().slice(0, 10).replace(/-/g, '') + '-' +
      Math.random().toString(36).slice(2, 6).toUpperCase());
    const version = existId ? ('v' + (new Date().toTimeString().slice(0, 5).replace(':', ''))) : 'v1';
    try {
      await apiJson('/api/bid/packages', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bid_id: bidId,
          project_name: $('bProjName').value.trim(),
          version,
          status: '测算中',
          target_total: parseFloat($('bTarget').value) || null,
          m_min: parseFloat($('bMMin').value) || 0,
          m_max: parseFloat($('bMMax').value) || 0,
          totals: lastTotals,
          items,
        }),
      });
      await refreshPkgList(bidId);
      say('报价包已保存：' + bidId);
    } catch (e) { say('保存失败：' + e.message); }
  });

  $('bPkgSel').addEventListener('change', async () => {
    const bidId = $('bPkgSel').value;
    if (!bidId) return;
    try {
      const d = await apiJson('/api/bid/packages/' + encodeURIComponent(bidId));
      const p = d.package;
      items = p.items || [];
      $('bProjName').value = p.project_name || '';
      $('bTarget').value = p.target_total == null ? '' : p.target_total;
      $('bMMin').value = p.m_min == null ? 0 : p.m_min;
      $('bMMax').value = p.m_max == null ? 0.3 : p.m_max;
      renderRows(); renderKpis(p.totals || null); renderProblems([]);
    } catch (e) { say('载入失败：' + e.message); }
  });

  $('bDelBtn').addEventListener('click', async () => {
    const bidId = $('bPkgSel').value;
    if (!bidId) return;
    const ok = window.toolConfirm
      ? await window.toolConfirm(`删除报价包 ${bidId}？此操作不可恢复。`)
      : confirm(`删除报价包 ${bidId}？`);
    if (!ok) return;
    try {
      await apiJson('/api/bid/packages/' + encodeURIComponent(bidId), { method: 'DELETE' });
      await refreshPkgList('');
      say('已删除');
    } catch (e) { say('删除失败：' + e.message); }
  });

  /* ---------- 初始化 ---------- */
  window.__toolBidLoaded = true;
  refreshPkgList('');
})();
