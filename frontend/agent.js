/* ===== AI 测算助手（Pi Durable 边车 8010） =====
 * 聊天 POST /submit；SSE /watch（frame=工作指示，approval_*=审批卡片）；
 * 模型 /model-config + /apply-model（设置抽屉，支持自定义 OpenAI 兼容端点）。
 */
(function () {
  'use strict';
  const esc = window.gcEsc;
  const AGENT_BASE = location.protocol.startsWith('http')
    ? location.protocol + '//' + location.hostname + ':8010'
    : 'http://127.0.0.1:8010';

  const chat = document.querySelector('#agentChat');
  const input = document.querySelector('#agentInput');
  const sendBtn = document.querySelector('#agentSendBtn');
  const pill = document.querySelector('#agentStatusPill');
  const modelText = document.querySelector('#agentModelText');
  if (!chat || !input || !sendBtn) return;

  let hasConversation = false; // 是否有过真实对话（欢迎空态只在没有时显示）

  // ---------------------------------------------------------------- 渲染
  // 建议项图标：统一走单色线性 SVG（DESIGN §3.2 禁止 emoji 充当 UI 图标）。
  // 原先用的是 ⚖ / ⟳ / ⏰ 三个 Unicode 字符，属 emoji/图标字符，与像素网格图标语言不一致。
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

  function now() { return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }); }

  function removeWelcome() { const w = chat.querySelector('.agent-welcome'); if (w) w.remove(); }

  function appendWelcome() {
    removeWelcome();
    const div = document.createElement('div');
    div.className = 'agent-welcome';
    div.innerHTML =
      '<div class="wv-icon"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="7" width="16" height="12" rx="2.5"/><path d="M12 7V4M8 4h8"/><circle cx="9" cy="12" r="1.1" fill="currentColor" stroke="none"/><circle cx="15" cy="12" r="1.1" fill="currentColor" stroke="none"/><path d="M9 16.5h6"/></svg></div>' +
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
    try { es = new EventSource(AGENT_BASE + '/watch'); } catch { return; }
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
      '<div class="ap-btns"><button class="ap-btn ap-allow">批准</button><button class="ap-btn ap-deny">拒绝</button></div>' +
      '<div class="ap-result"></div>';
    const post = (allow) => fetch(AGENT_BASE + '/approve', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
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
  const settings = document.querySelector('#agentSettings');
  const mask = document.querySelector('#agentDrawerMask');
  const providerSel = document.querySelector('#agentProviderSel');
  const modelSel = document.querySelector('#agentModelSel');
  const customProvider = document.querySelector('#agentCustomProvider');
  const customBase = document.querySelector('#agentCustomBase');
  const customKey = document.querySelector('#agentCustomKey');
  const customModel = document.querySelector('#agentCustomModel');
  const testConn = document.querySelector('#agentTestConn');
  const applyMsg = document.querySelector('#agentApplyMsg');
  const currentModel = document.querySelector('#agentCurrentModel');
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
  }

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
        headers: { 'content-type': 'application/json' },
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

  // ---------------------------------------------------------------- 事件
  document.querySelector('#agentSettingsBtn').addEventListener('click', () => setDrawer(true));
  document.querySelector('#agentSettingsClose').addEventListener('click', () => setDrawer(false));
  document.querySelector('#agentSettingsClose2').addEventListener('click', () => setDrawer(false));
  mask.addEventListener('click', () => setDrawer(false));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !settings.classList.contains('hidden')) setDrawer(false);
  });
  document.querySelector('#agentApplyModel').addEventListener('click', applyModel);

  // ---------------------------------------------------------------- 初始化
  appendWelcome();
  refreshHealth();
  connectSSE();

  window.__agentResurface = () => {
    refreshHealth();
    if (!hasConversation) appendWelcome();
    chat.scrollTop = chat.scrollHeight;
  };
})();
