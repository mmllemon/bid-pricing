/* ===== AI 测算助手：全局悬浮面板（全站可唤起） =====
 * 自包含：运行时把 FAB + 面板 + 模型设置抽屉注入 <body>，不依赖任何页面预先写好 DOM。
 * 因此 index 的 6 个视图与 5 个工具页共用同一份实现——改造前它是 index.html 里的整页
 * section（#agentView），工具页无法共存。
 *
 * 后端仍为 Pi Durable 边车（agent-service，:8010），交互契约与改造前完全一致：
 *   POST /submit 提交、GET /watch SSE（frame 工作指示 + approval_* 审批卡片）、
 *   GET /health 健康、GET /model-config + POST /apply-model 模型设置。
 *
 * 网络策略：懒连接。首次展开面板才去探活与订阅 SSE——否则每个工具页都会在
 * 8010 未启动时向控制台刷连接错误，这对「增值组件、故障不阻断」的定位不合适。
 */
(function () {
  'use strict';
  if (window.__agentPanelReady) return;   // 幂等：重复引入不叠加第二份面板
  window.__agentPanelReady = true;

  // 自带转义实现，避免依赖 js/escape.js（工具页不加载它）。
  const esc = window.gcEsc || (function () {
    const MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
    return (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => MAP[c]);
  })();

  const AGENT_BASE = location.protocol.startsWith('http')
    ? location.protocol + '//' + location.hostname + ':8010'
    : 'http://127.0.0.1:8010';

  // P0-1: 边车鉴权 token（与服务端 AGENT_API_TOKEN 对应）。未设置服务端 token 时留空即可；
  // 设置后 /approve、/apply-model 走请求头，/watch（SSE 不支持自定义头）走 ?token= 查询参数。
  const agentToken = () => {
    try { return sessionStorage.getItem('agent_api_token') || ''; } catch { return ''; }
  };
  const agentHeaders = (extra) => {
    const h = Object.assign({}, extra);
    const t = agentToken();
    if (t) h['X-API-Token'] = t;
    return h;
  };
  const watchUrl = () => {
    const t = agentToken();
    return AGENT_BASE + '/watch' + (t ? '?token=' + encodeURIComponent(t) : '');
  };

  const ICON_BOT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="7" width="16" height="12" rx="2.5"/><path d="M12 7V4M8 4h8"/><circle cx="9" cy="12" r="1.1" fill="currentColor" stroke="none"/><circle cx="15" cy="12" r="1.1" fill="currentColor" stroke="none"/><path d="M9 16h6"/></svg>';
  const ICON_GEAR = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.9 19.4a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h.01A1.7 1.7 0 0 0 10 3.09V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1.03 1.56h.01a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.01a1.7 1.7 0 0 0 1.56 1.03H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1.03Z"/></svg>';
  const ICON_X = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
  const ICON_SEND = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-7-7-4 18-9z"/></svg>';

  // ---------------------------------------------------------------- 注入 DOM
  const host = document.createElement('div');
  host.id = 'agentPanelRoot';
  host.innerHTML =
    '<button id="agentFab" class="agent-fab" type="button" aria-label="打开 AI 测算助手" aria-expanded="false" title="AI 测算助手">' + ICON_BOT + '</button>' +

    '<section id="agentPanel" class="agent-panel hidden" role="dialog" aria-label="AI 测算助手">' +
      '<header class="agent-panel-head">' +
        '<span class="agent-panel-title">AI 测算助手</span>' +
        '<span id="agentStatusPill" class="agent-status-pill"><span class="dot"></span><span id="agentModelText">未连接</span></span>' +
        '<button id="agentSettingsBtn" class="agent-settings-btn" type="button" title="模型设置">' + ICON_GEAR + '模型</button>' +
        '<button id="agentPanelClose" class="agent-panel-close" type="button" aria-label="收起面板">' + ICON_X + '</button>' +
      '</header>' +
      '<div class="agent-shell">' +
        '<div id="agentChat" class="agent-chat"></div>' +
        '<div class="agent-input-row">' +
          '<textarea id="agentInput" rows="1" placeholder="例如：对比西永L和旅游学校两个项目的利润空间；给石船安置设一个开标前 3 天的提醒"></textarea>' +
          '<button id="agentSendBtn" class="btn-primary agent-send" type="button">发送' + ICON_SEND + '</button>' +
        '</div>' +
      '</div>' +
    '</section>' +

    '<div id="agentDrawerMask" class="agent-drawer-mask hidden"></div>' +
    '<aside id="agentSettings" class="agent-settings hidden" aria-label="模型设置">' +
      '<div class="agent-settings-head">' +
        '<h2>模型设置</h2>' +
        '<button id="agentSettingsClose" class="agent-settings-close" type="button" aria-label="关闭">' + ICON_X + '</button>' +
      '</div>' +
      '<div class="agent-settings-body">' +
        '<div><div class="sec-title">当前模型</div>' +
          '<div class="as-active"><span class="dot"></span><span id="agentCurrentModel" class="as-active-name">加载中…</span></div></div>' +
        '<div><div class="sec-title">内置 / models.json 可选</div>' +
          '<div class="row" style="margin-bottom:10px"><select id="agentProviderSel"></select></div>' +
          '<label>模型</label><select id="agentModelSel"></select></div>' +
        '<div><div class="sec-title">自定义 OpenAI 兼容端点</div>' +
          '<label>Provider ID（端点名）</label><input id="agentCustomProvider" type="text" placeholder="my-provider" style="margin-bottom:10px" />' +
          '<label>Base URL</label><input id="agentCustomBase" type="text" placeholder="https://api.xxx.com/v1" style="margin-bottom:10px" />' +
          '<label>API Key</label><input id="agentCustomKey" type="password" placeholder="sk-..." style="margin-bottom:10px" />' +
          '<label>模型 ID</label><input id="agentCustomModel" type="text" placeholder="my-model" /></div>' +
        '<div><div class="sec-title">边车鉴权（可选）</div>' +
          '<label>AGENT_API_TOKEN</label><input id="agentApiToken" type="password" placeholder="与服务端 AGENT_API_TOKEN 一致；未设置服务端时留空" />' +
          '<div class="as-hint" style="font-size:12px;opacity:.65;line-height:1.6;margin-top:4px">服务端设置 AGENT_API_TOKEN 后，审批与模型设置需鉴权；此处填同一值，保存在本次会话（sessionStorage，关标签页即清除，不进 localStorage）。</div></div>' +
        '<label class="chk"><input type="checkbox" id="agentTestConn" checked /> 应用后自动测试连接</label>' +
        '<div id="agentApplyMsg" class="as-test"></div>' +
      '</div>' +
      '<div class="agent-settings-foot">' +
        '<button id="agentApplyModel" class="as-apply" type="button">应用模型</button>' +
        '<button id="agentSettingsClose2" class="as-close" type="button">关闭</button>' +
      '</div>' +
    '</aside>';
  document.body.appendChild(host);

  const fab = document.getElementById('agentFab');
  const panel = document.getElementById('agentPanel');
  const chat = document.getElementById('agentChat');
  const input = document.getElementById('agentInput');
  const sendBtn = document.getElementById('agentSendBtn');
  const pill = document.getElementById('agentStatusPill');
  const modelText = document.getElementById('agentModelText');

  // ---------------------------------------------------------------- 渲染
  // 建议项图标：统一走单色线性 SVG（DESIGN §3.2 禁止 emoji 充当 UI 图标）。
  const S_ICONS = {
    compare: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v18M8 21h8M4 7h16"/><path d="M4 7l-2.5 5h5z"/><path d="M20 7l-2.5 5h5z"/></svg>',
    recompute: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><polyline points="21 3 21 9 15 9"/></svg>',
    remind: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 2"/></svg>',
  };
  const SUGGESTIONS = [
    [S_ICONS.compare, '对比西永L和旅游学校两个项目的利润空间，哪个更值得报'],
    [S_ICONS.recompute, '把西永L的 optimal 方案按 uniform 策略重算一遍（需要你批准）'],
    [S_ICONS.remind, '给石船安置设一个「开标前 3 天检查低价红线」的提醒'],
  ];
  let hasConversation = false;   // 是否有过真实对话（欢迎空态只在没有时显示）

  function now() { return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }); }

  function removeWelcome() { const w = chat.querySelector('.agent-welcome'); if (w) w.remove(); }

  function appendWelcome() {
    removeWelcome();
    const div = document.createElement('div');
    div.className = 'agent-welcome';
    div.innerHTML =
      '<div class="wv-icon">' + ICON_BOT + '</div>' +
      '<h2>投标报价测算助手</h2>' +
      '<p>可以查项目方案、经营概览，重算/新算报价（需你批准），还能设持久提醒。<br>会话保存在本地，服务重启不丢。</p>' +
      '<div class="agent-suggests">' +
      SUGGESTIONS.map(([ic, t], i) => '<div class="agent-suggest" data-i="' + i + '"><span class="s-ic">' + ic + '</span><span>' + esc(t) + '</span></div>').join('') +
      '</div>';
    div.querySelectorAll('.agent-suggest').forEach((el) => {
      el.addEventListener('click', () => {
        input.value = SUGGESTIONS[el.dataset.i][1];
        autoGrow();
        input.focus();
      });
    });
    chat.appendChild(div);
  }

  function appendMsg(role, text) {
    const div = document.createElement('div');
    const time = '<span class="msg-time">' + now() + '</span>';
    if (role === 'user') {
      div.className = 'agent-msg user';
      div.innerHTML = esc(text) + time;
    } else if (role === 'err') {
      div.className = 'agent-msg err';
      div.innerHTML = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:5px" aria-hidden="true"><path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/></svg>' + esc(text) + time;
    } else {
      div.className = 'agent-msg bot';
      div.innerHTML = '<div class="msg-line"><div class="bot-avatar">AI</div><div class="bot-text">' + esc(text) + time + '</div></div>';
    }
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
    return div;
  }

  let workLine = null;
  function setWorking(on) {
    if (on && !workLine) {
      workLine = document.createElement('div');
      workLine.className = 'agent-work';
      workLine.innerHTML = '<span class="dot"></span>agent 正在工作（推理 / 工具调用）…';
      chat.appendChild(workLine);
      chat.scrollTop = chat.scrollHeight;
    } else if (!on && workLine) { workLine.remove(); workLine = null; }
  }

  // ---------------------------------------------------------------- 展开 / 收起
  let opened = false;
  function openPanel() {
    panel.classList.remove('hidden');
    fab.setAttribute('aria-expanded', 'true');
    if (!opened) {          // 首次展开：补上欢迎态并建立与边车的连接（懒连接）
      opened = true;
      if (!hasConversation) appendWelcome();
      refreshHealth();
      connectSSE();
    }
    chat.scrollTop = chat.scrollHeight;
    input.focus();
  }
  function closePanel() {
    panel.classList.add('hidden');
    fab.setAttribute('aria-expanded', 'false');
    fab.focus();
  }
  fab.addEventListener('click', () => {
    if (panel.classList.contains('hidden')) openPanel(); else closePanel();
  });
  document.getElementById('agentPanelClose').addEventListener('click', closePanel);
  // 侧栏「AI 测算助手」等入口：任何带 data-agent-open 的元素都唤起面板。
  document.querySelectorAll('[data-agent-open]').forEach((el) => el.addEventListener('click', openPanel));

  // ---------------------------------------------------------------- 发送
  let busy = false;
  async function send() {
    const content = input.value.trim();
    if (!content || busy) return;
    busy = true;
    sendBtn.disabled = true;
    input.value = '';
    autoGrow();
    removeWelcome();
    hasConversation = true;
    appendMsg('user', content);
    setWorking(true);
    try {
      const res = await fetch(AGENT_BASE + '/submit', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ content }),
      });
      const data = await res.json();
      if (data.status === 'done' && data.answer) appendMsg('bot', data.answer);
      else if (data.error) appendMsg('err', data.error + (res.status === 503 ? '（agent-service 未就绪，请确认 8010 已启动）' : ''));
      else appendMsg('err', '提交未成功：' + JSON.stringify(data).slice(0, 400));
    } catch (e) {
      appendMsg('err', '连接 agent-service 失败：' + e.message + '（请确认 8010 已启动）');
    } finally {
      busy = false;
      sendBtn.disabled = false;
      setWorking(false);
      input.focus();
    }
  }
  sendBtn.addEventListener('click', send);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  function autoGrow() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 140) + 'px';
  }
  input.addEventListener('input', autoGrow);

  // ---------------------------------------------------------------- SSE：审批与工作指示
  const approvalCards = new Map();
  let es = null;
  function connectSSE() {
    if (es) return;
    try { es = new EventSource(watchUrl()); } catch { return; }
    es.onmessage = (ev) => {
      let data;
      try { data = JSON.parse(ev.data); } catch { return; }
      if (data.type === 'frame') {
        if (!busy && data.ops && data.ops.length) setWorking(true);
      } else if (data.type === 'approval_request') {
        renderApproval(data);
      } else if (data.type === 'approval_decided') {
        settleApproval(data);
      }
    };
  }
  function renderApproval(data) {
    if (approvalCards.has(data.key)) return;
    removeWelcome();
    const card = document.createElement('div');
    card.className = 'agent-approval';
    card.innerHTML =
      '<div class="ap-title"><span class="ap-badge">待批准</span> ' + esc(data.tool) + '</div>' +
      '<div class="ap-args">' + esc(JSON.stringify(data.args || {}, null, 1)) + '</div>' +
      '<div class="ap-btns"><button class="ap-btn ap-allow" type="button">批准</button><button class="ap-btn ap-deny" type="button">拒绝</button></div>' +
      '<div class="ap-result"></div>';
    const post = (allow) => fetch(AGENT_BASE + '/approve', {
      method: 'POST',
      headers: agentHeaders({ 'content-type': 'application/json' }),
      body: JSON.stringify({ key: data.key, allow }),
    });
    card.querySelector('.ap-allow').onclick = async () => {
      card.classList.add('decided');
      card.querySelector('.ap-result').textContent = '已批准，执行中…';
      card.querySelector('.ap-result').className = 'ap-result ok';
      await post(true);
    };
    card.querySelector('.ap-deny').onclick = async () => {
      card.classList.add('decided');
      card.querySelector('.ap-result').textContent = '已拒绝，该操作不会执行';
      card.querySelector('.ap-result').className = 'ap-result bad';
      await post(false);
    };
    approvalCards.set(data.key, card);
    chat.appendChild(card);
    chat.scrollTop = chat.scrollHeight;
  }
  function settleApproval(data) {
    const card = approvalCards.get(data.key);
    if (!card || data.type !== 'approval_decided') return;
    const r = card.querySelector('.ap-result');
    if (!r.textContent || r.textContent.startsWith('已')) return; // 已本地更新过
    r.textContent = data.allow ? '（已通过）' : '（已拒绝）';
    setTimeout(() => card.remove(), 4000);
  }

  // ---------------------------------------------------------------- 健康
  async function refreshHealth() {
    try {
      const h = await (await fetch(AGENT_BASE + '/health')).json();
      pill.classList.remove('warn', 'off');
      if (!h.model_available) pill.classList.add('warn');
      modelText.textContent = (h.provider || 'unknown') + '/' + (h.model || '—') +
        (h.pending_approvals ? ' · 待批 ' + h.pending_approvals : '');
    } catch {
      pill.classList.add('off');
      modelText.textContent = 'agent-service 离线（8010）';
    }
  }

  // ---------------------------------------------------------------- 设置抽屉
  const settings = document.getElementById('agentSettings');
  const mask = document.getElementById('agentDrawerMask');
  const providerSel = document.getElementById('agentProviderSel');
  const modelSel = document.getElementById('agentModelSel');
  const customProvider = document.getElementById('agentCustomProvider');
  const customBase = document.getElementById('agentCustomBase');
  const customKey = document.getElementById('agentCustomKey');
  const customModel = document.getElementById('agentCustomModel');
  const agentApiToken = document.getElementById('agentApiToken');
  const testConn = document.getElementById('agentTestConn');
  const applyMsg = document.getElementById('agentApplyMsg');
  const currentModel = document.getElementById('agentCurrentModel');
  let configCache = null;

  function setDrawer(open) {
    settings.classList.toggle('hidden', !open);
    mask.classList.toggle('hidden', !open);
    if (open) openSettings();
  }

  function fillModelSelect(provider) {
    const found = (configCache && configCache.available || []).find((a) => a.provider === provider);
    modelSel.innerHTML = (found && found.models ? found.models : []).map((m) =>
      '<option value="' + esc(m) + '">' + esc(m) + '</option>'
    ).join('');
  }

  async function openSettings() {
    applyMsg.textContent = '';
    applyMsg.className = 'as-test';
    try {
      configCache = await (await fetch(AGENT_BASE + '/model-config')).json();
      currentModel.textContent = configCache.active.provider + '/' + configCache.active.model;
      const avail = configCache.available || [];
      providerSel.innerHTML = avail.map((a) =>
        '<option value="' + esc(a.provider) + '">' + esc(a.provider) + '（' + a.models.length + ' 个模型）</option>'
      ).join('') + '<option value="__custom__">— 自定义端点（填下方）—</option>';
      const activeIn = avail.find((a) => a.provider === configCache.active.provider);
      providerSel.value = activeIn ? activeIn.provider : '__custom__';
      if (providerSel.value === '__custom__') {
        const c = configCache.custom || {};
        customProvider.value = c.id || '';
        customBase.value = c.baseUrl || '';
        customModel.value = (c.models && c.models[0]) || '';
        customKey.placeholder = c.apiKey ? '已保存（留空沿用）' : 'sk-...';
        modelSel.innerHTML = '';
      } else {
        fillModelSelect(providerSel.value);
      }
    } catch (e) {
      applyMsg.textContent = '读取配置失败：' + e.message;
      applyMsg.className = 'as-test bad';
    }
    // P0-1: 边车鉴权 token 回填（本次会话 sessionStorage）
    agentApiToken.value = agentToken();
  }

  agentApiToken.addEventListener('change', () => {
    try { sessionStorage.setItem('agent_api_token', agentApiToken.value.trim()); } catch {}
    // token 变更后重建 SSE 连接，使其携带新 token；面板已展开时立即重连
    if (es) { try { es.close(); } catch {} es = null; }
    if (opened && !panel.classList.contains('hidden')) connectSSE();
  });

  providerSel.addEventListener('change', () => {
    if (providerSel.value === '__custom__') {
      modelSel.innerHTML = '';
      modelSel.disabled = true;
      modelSel.placeholder = '在下方填写模型 ID';
    } else {
      modelSel.disabled = false;
      fillModelSelect(providerSel.value);
    }
  });

  async function applyModel() {
    applyMsg.textContent = '应用中…';
    applyMsg.className = 'as-test';
    const useCustom = providerSel.value === '__custom__' || (!providerSel.value && customProvider.value.trim());
    let provider, model, extra = {};
    if (useCustom) {
      provider = customProvider.value.trim();
      model = customModel.value.trim();
      extra = { baseUrl: customBase.value.trim(), apiKey: customKey.value.trim(), name: provider };
      if (!provider || !model || !extra.baseUrl) {
        applyMsg.textContent = '自定义端点需要：Provider ID + Base URL + 模型 ID';
        applyMsg.className = 'as-test bad';
        return;
      }
    } else {
      provider = providerSel.value;
      model = modelSel.value;
      if (!provider || !model) {
        applyMsg.textContent = '请先选择 provider 与模型';
        applyMsg.className = 'as-test bad';
        return;
      }
    }
    try {
      const res = await fetch(AGENT_BASE + '/apply-model', {
        method: 'POST',
        headers: agentHeaders({ 'content-type': 'application/json' }),
        body: JSON.stringify(Object.assign({ provider, model }, extra, { test: testConn.checked })),
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        applyMsg.textContent = '已切换到 ' + data.active.provider + '/' + data.active.model +
          (data.test ? ' · 测试' + (data.test === 'pong' ? '通过 ✓' : '：' + String(data.test).slice(0, 120)) : '');
        applyMsg.className = 'as-test ok';
        currentModel.textContent = data.active.provider + '/' + data.active.model;
        refreshHealth();
      } else {
        applyMsg.textContent = '应用失败：' + (data.error || JSON.stringify(data).slice(0, 300));
        applyMsg.className = 'as-test bad';
      }
    } catch (e) {
      applyMsg.textContent = '应用失败：' + e.message;
      applyMsg.className = 'as-test bad';
    }
  }

  document.getElementById('agentSettingsBtn').addEventListener('click', () => setDrawer(true));
  document.getElementById('agentSettingsClose').addEventListener('click', () => setDrawer(false));
  document.getElementById('agentSettingsClose2').addEventListener('click', () => setDrawer(false));
  mask.addEventListener('click', () => setDrawer(false));
  document.getElementById('agentApplyModel').addEventListener('click', applyModel);
  // Esc：抽屉优先（它盖在面板之上），抽屉没开才收面板。
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!settings.classList.contains('hidden')) setDrawer(false);
    else if (!panel.classList.contains('hidden')) closePanel();
  });

  // 对外暴露：其他脚本/调试可直接唤起
  window.__agentOpen = openPanel;
  window.__agentClose = closePanel;
})();
