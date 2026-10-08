import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api/client';

/**
 * AI 测算助手（P4 前端整合：由 frontend/agent-panel.js + agent.css 迁入 React）
 * 全站悬浮：FAB + 面板 + 模型设置抽屉。后端 agent-service 已并入 :3456 的 /agent 前缀。
 *
 * 契约（与 agent-panel.js 完全一致）：
 *   POST /agent/submit        提交
 *   GET  /agent/watch   SSE   frame 工作指示 + approval_* 审批
 *   GET  /agent/health        健康
 *   GET  /agent/model-config  + POST /agent/apply-model 模型设置
 *   POST /agent/approve       审批裁定
 * 网络策略：懒连接——首次展开面板才探活与订阅 SSE。
 */

const ICON_BOT = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x={4} y={7} width={16} height={12} rx={2.5} /><path d="M12 7V4M8 4h8" /><circle cx={9} cy={12} r={1.1} fill="currentColor" stroke="none" /><circle cx={15} cy={12} r={1.1} fill="currentColor" stroke="none" /><path d="M9 16h6" /></svg>;
const ICON_GEAR = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx={12} cy={12} r={3.2} /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.9 19.4a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h.01A1.7 1.7 0 0 0 10 3.09V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1.03 1.56h.01a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.01a1.7 1.7 0 0 0 1.56 1.03H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1.03Z" /></svg>;
const ICON_X = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>;
const ICON_SEND = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M22 2 11 13" /><path d="M22 2 15 22l-4-7-7-4 18-9z" /></svg>;

const S_ICONS = {
  compare: <svg viewBox="0 0 24 24" width={15} height={15} fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3v18M8 21h8M4 7h16" /><path d="M4 7l-2.5 5h5z" /><path d="M20 7l-2.5 5h5z" /></svg>,
  recompute: <svg viewBox="0 0 24 24" width={15} height={15} fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.64-6.36" /><polyline points="21 3 21 9 15 9" /></svg>,
  remind: <svg viewBox="0 0 24 24" width={15} height={15} fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx={12} cy={12} r={9} /><path d="M12 7.5V12l3 2" /></svg>,
};
const SUGGESTIONS: [keyof typeof S_ICONS, string][] = [
  ['compare', '对比西永L和旅游学校两个项目的利润空间，哪个更值得报'],
  ['recompute', '把西永L的 optimal 方案按 uniform 策略重算一遍（需要你批准）'],
  ['remind', '给石船安置设一个「开标前 3 天检查低价红线」的提醒'],
];

const now = () => new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });

/* token：只放内存 + sessionStorage；localStorage 旧存量一次性迁移后清除。 */
let memToken: string | null = null;
function getToken(): string {
  if (memToken !== null) return memToken;
  let t = '';
  try { t = sessionStorage.getItem('agent_api_token') || ''; } catch { t = ''; }
  if (!t) {
    try {
      t = localStorage.getItem('agent_api_token') || '';
      if (t) { sessionStorage.setItem('agent_api_token', t); localStorage.removeItem('agent_api_token'); }
    } catch { t = ''; }
  }
  memToken = t;
  return memToken;
}
function setToken(t: string) {
  memToken = t || '';
  try {
    if (memToken) sessionStorage.setItem('agent_api_token', memToken);
    else sessionStorage.removeItem('agent_api_token');
    localStorage.removeItem('agent_api_token');
  } catch { /* ignore */ }
}
/** P2-7：headers() 已废弃，token 改由 apiClient 自动透传（X-API-Token）。SSE 仍用 getToken() 拼 query。 */

type Msg = { role: 'user' | 'bot' | 'err'; text: string; time: string };
type Approval = { key: string; tool: string; args: Record<string, unknown>; decided?: boolean; result?: string; resultKind?: '' | 'ok' | 'bad' };

export default function AgentPanel() {
  const [panelOpen, setPanelOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [working, setWorking] = useState(false);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [pending, setPending] = useState(0);
  const [health, setHealth] = useState({ off: false, warn: false, text: '未连接' });
  const [hasConversation, setHasConversation] = useState(false);
  const [applyMsg, setApplyMsg] = useState<{ text: string; kind: '' | 'ok' | 'bad' }>({ text: '', kind: '' });

  // 配置抽屉
  const [cfg, setCfg] = useState<{ active: { provider: string; model: string }; available: { provider: string; models: string[] }[]; custom: { id?: string; baseUrl?: string; apiKey?: string; models?: string[] } | null } | null>(null);
  const [selProvider, setSelProvider] = useState('');
  const [selModel, setSelModel] = useState('');
  const [cust, setCust] = useState({ id: '', base: '', key: '', model: '' });
  const [tokenInput, setTokenInput] = useState('');
  const [testConn, setTestConn] = useState(true);

  const esRef = useRef<EventSource | null>(null);
  const chatRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fabRef = useRef<HTMLButtonElement>(null);
  const busyRef = useRef(false);
  const decidedRef = useRef<Set<string>>(new Set());

  useEffect(() => { busyRef.current = busy; }, [busy]);

  // 聊天滚动到底
  useEffect(() => { const el = chatRef.current; if (el) el.scrollTop = el.scrollHeight; }, [msgs, approvals, working]);

  const refreshHealth = useCallback(async () => {
    try {
      const h = await api.request<{ [k: string]: unknown }>('/agent/health');
      setHealth({
        off: false,
        warn: !h.model_available,
        text: `${h.provider || 'unknown'}/${h.model || '—'}${h.pending_approvals ? ' · 待批 ' + h.pending_approvals : ''}`,
      });
    } catch {
      setHealth({ off: true, warn: false, text: 'agent 离线' });
    }
  }, []);

  const noteDecided = useCallback((key: string) => {
    if (decidedRef.current.has(key)) return;
    decidedRef.current.add(key);
    setPending((n) => Math.max(0, n - 1));
  }, []);

  const connectSSE = useCallback(() => {
    if (esRef.current) return;
    const t = getToken();
    let es: EventSource;
    try { es = new EventSource('/agent/watch' + (t ? '?token=' + encodeURIComponent(t) : '')); } catch { return; }
    esRef.current = es;
    es.onmessage = (ev) => {
      let data: { type?: string; ops?: unknown[]; key?: string; tool?: string; args?: Record<string, unknown>; allow?: boolean };
      try { data = JSON.parse(ev.data); } catch { return; }
      if (data.type === 'frame') {
        if (!busyRef.current && data.ops && data.ops.length) setWorking(true);
      } else if (data.type === 'approval_request' && data.key) {
        setHasConversation(true);
        setApprovals((list) => list.some((a) => a.key === data.key) ? list
          : [...list, { key: data.key!, tool: data.tool || '', args: data.args || {} }]);
        setPending((n) => n + 1);
      } else if (data.type === 'approval_decided' && data.key) {
        setApprovals((list) => list.map((a) => {
          if (a.key !== data.key) return a;
          if (a.result && a.result.startsWith('已')) return a;
          return { ...a, result: data.allow ? '（已通过）' : '（已拒绝）' };
        }));
        noteDecided(data.key);
        setTimeout(() => setApprovals((list) => list.filter((a) => a.key !== data.key)), 4000);
      }
    };
  }, [noteDecided]);

  const openPanel = useCallback(() => {
    setPanelOpen(true);
    if (!esRef.current) connectSSE();
    setPending(0);
    decidedRef.current.clear();
    void refreshHealth();
    setTimeout(() => inputRef.current?.focus(), 0);
  }, [connectSSE, refreshHealth]);

  const closePanel = useCallback(() => {
    setPanelOpen(false);
    fabRef.current?.focus();
  }, []);

  // Esc：抽屉优先（盖在面板之上），否则收面板
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (settingsOpen) setSettingsOpen(false);
      else if (panelOpen) closePanel();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [settingsOpen, panelOpen, closePanel]);

  // 对外暴露（与旧实现一致，供调试/其他脚本唤起）
  useEffect(() => {
    (window as unknown as Record<string, unknown>).__agentOpen = openPanel;
    (window as unknown as Record<string, unknown>).__agentClose = closePanel;
  }, [openPanel, closePanel]);

  const send = useCallback(async () => {
    const content = input.trim();
    if (!content || busy) return;
    setBusy(true);
    setInput('');
    setHasConversation(true);
    setMsgs((m) => [...m, { role: 'user', text: content, time: now() }]);
    setWorking(true);
    try {
      const data = await api.request<{ status?: string; answer?: string; error?: string }>('/agent/submit', {
        method: 'POST',
        body: JSON.stringify({ content }),
      });
      if (data.status === 'done' && data.answer) setMsgs((m) => [...m, { role: 'bot', text: data.answer as string, time: now() }]);
      else if (data.error) setMsgs((m) => [...m, { role: 'err', text: data.error as string, time: now() }]);
      else setMsgs((m) => [...m, { role: 'err', text: '提交未成功：' + JSON.stringify(data).slice(0, 400), time: now() }]);
    } catch (e) {
      const msg = (e as Error).message || '';
      const hint = msg.includes('503') ? '（agent 未就绪）' : '';
      setMsgs((m) => [...m, { role: 'err', text: '连接 agent 失败：' + msg + hint, time: now() }]);
    } finally {
      setBusy(false);
      setWorking(false);
      inputRef.current?.focus();
    }
  }, [input, busy]);

  const decide = useCallback(async (key: string, allow: boolean) => {
    setApprovals((list) => list.map((a) => a.key === key
      ? { ...a, decided: true, result: allow ? '已批准，执行中…' : '已拒绝，该操作不会执行', resultKind: allow ? 'ok' : 'bad' } : a));
    try {
      await api.request('/agent/approve', { method: 'POST', body: JSON.stringify({ key, allow }) });
    } catch { /* ignore */ }
    noteDecided(key);
  }, [noteDecided]);

  const openSettings = useCallback(async () => {
    setApplyMsg({ text: '', kind: '' });
    setSettingsOpen(true);
    try {
      const c = await api.request<{ active: { provider: string; model: string }; available: { provider: string; models: string[] }[]; custom: { id?: string; baseUrl?: string; apiKey?: string; models?: string[] } | null }>('/agent/model-config');
      setCfg(c);
      const avail: { provider: string; models: string[] }[] = c.available || [];
      const activeIn = avail.find((a) => a.provider === c.active.provider);
      setSelProvider(activeIn ? activeIn.provider : '__custom__');
      setSelModel(activeIn ? (activeIn.models[0] || '') : '');
      if (activeIn) {
        setSelModel(c.active.model || activeIn.models[0] || '');
      } else {
        const cu = c.custom || {};
        setCust({ id: cu.id || '', base: cu.baseUrl || '', key: '', model: (cu.models && cu.models[0]) || '' });
      }
    } catch (e) {
      setApplyMsg({ text: '读取配置失败：' + (e as Error).message, kind: 'bad' });
    }
    setTokenInput(getToken());
  }, []);

  const applyModel = useCallback(async () => {
    setApplyMsg({ text: '应用中…', kind: '' });
    const useCustom = selProvider === '__custom__';
    let body: Record<string, unknown>;
    if (useCustom) {
      if (!cust.id || !cust.model || !cust.base) { setApplyMsg({ text: '自定义端点需要：Provider ID + Base URL + 模型 ID', kind: 'bad' }); return; }
      body = { provider: cust.id, model: cust.model, baseUrl: cust.base, apiKey: cust.key, name: cust.id, test: testConn };
    } else {
      if (!selProvider || !selModel) { setApplyMsg({ text: '请先选择 provider 与模型', kind: 'bad' }); return; }
      body = { provider: selProvider, model: selModel, test: testConn };
    }
    try {
      const data = await api.request<{ ok?: boolean; active: { provider: string; model: string }; test?: string; error?: string }>('/agent/apply-model', { method: 'POST', body: JSON.stringify(body) });
      if (data.ok) {
        setApplyMsg({
          text: `已切换到 ${data.active.provider}/${data.active.model}${data.test ? ' · 测试' + (data.test === 'pong' ? '通过 ✓' : '：' + String(data.test).slice(0, 120)) : ''}`,
          kind: 'ok',
        });
        setCfg((c) => (c ? { ...c, active: data.active } : c));
        void refreshHealth();
      } else {
        setApplyMsg({ text: '应用失败：' + (data.error || JSON.stringify(data).slice(0, 300)), kind: 'bad' });
      }
    } catch (e) {
      setApplyMsg({ text: '应用失败：' + (e as Error).message, kind: 'bad' });
    }
  }, [selProvider, selModel, cust, testConn, refreshHealth]);

  const modelsForProvider = (p: string) => (cfg?.available || []).find((a) => a.provider === p)?.models || [];

  return (
    <>
      <button ref={fabRef} id="agentFab" className="agent-fab" type="button" aria-label="打开 AI 测算助手" aria-expanded={panelOpen} title="AI 测算助手"
        onClick={() => (panelOpen ? closePanel() : openPanel())}>
        {ICON_BOT}
        {pending > 0 && !panelOpen && <span className="agent-fab-badge" aria-label="有待批准的请求">{pending > 9 ? '9+' : pending}</span>}
      </button>

      <section id="agentPanel" className={`agent-panel${panelOpen ? '' : ' hidden'}`} role="dialog" aria-label="AI 测算助手">
        <header className="agent-panel-head">
          <span className="agent-panel-title">AI 测算助手</span>
          <span id="agentStatusPill" className={`agent-status-pill${health.off ? ' off' : health.warn ? ' warn' : ''}`}>
            <span className="dot" /><span id="agentModelText">{health.text}</span>
          </span>
          <button id="agentSettingsBtn" className="agent-settings-btn" type="button" title="模型设置" onClick={openSettings}>{ICON_GEAR}模型</button>
          <button id="agentPanelClose" className="agent-panel-close" type="button" aria-label="收起面板" onClick={closePanel}>{ICON_X}</button>
        </header>
        <div className="agent-shell">
          <div id="agentChat" className="agent-chat" ref={chatRef}>
            {!hasConversation && (
              <div className="agent-welcome">
                <div className="wv-icon">{ICON_BOT}</div>
                <h2>投标报价测算助手</h2>
                <p>可以查项目方案、经营概览，重算/新算报价（需你批准），还能设持久提醒。<br />会话保存在本地，服务重启不丢。</p>
                <div className="agent-suggests">
                  {SUGGESTIONS.map(([ic, t]) => (
                    <div className="agent-suggest" key={t} onClick={() => { setInput(t); inputRef.current?.focus(); }}>
                      <span className="s-ic">{S_ICONS[ic]}</span><span>{t}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {msgs.map((m, i) => (
              m.role === 'user' ? (
                <div className="agent-msg user" key={i}>{m.text}<span className="msg-time">{m.time}</span></div>
              ) : m.role === 'err' ? (
                <div className="agent-msg err" key={i}>
                  <svg viewBox="0 0 24 24" width={13} height={13} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" style={{ verticalAlign: -2, marginRight: 5 }} aria-hidden="true"><path d="M12 4l9 16H3z" /><path d="M12 10v4M12 17h.01" /></svg>
                  {m.text}<span className="msg-time">{m.time}</span>
                </div>
              ) : (
                <div className="agent-msg bot" key={i}>
                  <div className="msg-line"><div className="bot-avatar">AI</div><div className="bot-text">{m.text}<span className="msg-time">{m.time}</span></div></div>
                </div>
              )
            ))}

            {approvals.map((a) => (
              <div className={`agent-approval${a.decided ? ' decided' : ''}`} key={a.key}>
                <div className="ap-title"><span className="ap-badge">待批准</span> {a.tool}</div>
                <div className="ap-args">{JSON.stringify(a.args || {}, null, 1)}</div>
                {!a.decided && (
                  <div className="ap-btns">
                    <button className="ap-btn ap-allow" type="button" onClick={() => decide(a.key, true)}>批准</button>
                    <button className="ap-btn ap-deny" type="button" onClick={() => decide(a.key, false)}>拒绝</button>
                  </div>
                )}
                {a.result && <div className={`ap-result ${a.resultKind || ''}`}>{a.result}</div>}
              </div>
            ))}

            {working && <div className="agent-work"><span className="dot" />agent 正在工作（推理 / 工具调用）…</div>}
          </div>

          <div className="agent-input-row">
            <textarea id="agentInput" ref={inputRef} rows={1} placeholder="例如：对比西永L和旅游学校两个项目的利润空间；给石船安置设一个开标前 3 天的提醒"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(); } }} />
            <button id="agentSendBtn" className="btn-primary agent-send" type="button" disabled={busy} onClick={send}>发送{ICON_SEND}</button>
          </div>
        </div>
      </section>

      <div id="agentDrawerMask" className={`agent-drawer-mask${settingsOpen ? '' : ' hidden'}`} onClick={() => setSettingsOpen(false)} />
      <aside id="agentSettings" className={`agent-settings${settingsOpen ? '' : ' hidden'}`} aria-label="模型设置">
        <div className="agent-settings-head">
          <h2>模型设置</h2>
          <button id="agentSettingsClose" className="agent-settings-close" type="button" aria-label="关闭" onClick={() => setSettingsOpen(false)}>{ICON_X}</button>
        </div>
        <div className="agent-settings-body">
          <div>
            <div className="sec-title">当前模型</div>
            <div className="as-active"><span className="dot" /><span id="agentCurrentModel" className="as-active-name">{cfg ? `${cfg.active.provider}/${cfg.active.model}` : '加载中…'}</span></div>
          </div>
          <div>
            <div className="sec-title">内置 / models.json 可选</div>
            <div className="row" style={{ marginBottom: 10 }}>
              <select id="agentProviderSel" value={selProvider} onChange={(e) => {
                const p = e.target.value;
                setSelProvider(p);
                setSelModel(modelsForProvider(p)[0] || '');
              }}>
                {(cfg?.available || []).map((a) => <option key={a.provider} value={a.provider}>{a.provider}（{a.models.length} 个模型）</option>)}
                <option value="__custom__">— 自定义端点（填下方）—</option>
              </select>
            </div>
            <label>模型</label>
            <select id="agentModelSel" value={selModel} disabled={selProvider === '__custom__'} onChange={(e) => setSelModel(e.target.value)}>
              {selProvider === '__custom__' ? null : modelsForProvider(selProvider).map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div>
            <div className="sec-title">自定义 OpenAI 兼容端点</div>
            <label>Provider ID（端点名）</label>
            <input id="agentCustomProvider" type="text" placeholder="my-provider" style={{ marginBottom: 10 }} value={cust.id} onChange={(e) => setCust({ ...cust, id: e.target.value })} />
            <label>Base URL</label>
            <input id="agentCustomBase" type="text" placeholder="https://api.xxx.com/v1" style={{ marginBottom: 10 }} value={cust.base} onChange={(e) => setCust({ ...cust, base: e.target.value })} />
            <label>API Key</label>
            <input id="agentCustomKey" type="password" placeholder={cfg?.custom?.apiKey ? '已保存（留空沿用）' : 'sk-...'} style={{ marginBottom: 10 }} value={cust.key} onChange={(e) => setCust({ ...cust, key: e.target.value })} />
            <label>模型 ID</label>
            <input id="agentCustomModel" type="text" placeholder="my-model" value={cust.model} onChange={(e) => setCust({ ...cust, model: e.target.value })} />
          </div>
          <div>
            <div className="sec-title">边车鉴权（可选）</div>
            <label>AGENT_API_TOKEN</label>
            <input id="agentApiToken" type="password" placeholder="与服务端 AGENT_API_TOKEN 一致；未设置服务端时留空" value={tokenInput}
              onChange={(e) => {
                setTokenInput(e.target.value);
                setToken(e.target.value.trim());
                if (esRef.current) { try { esRef.current.close(); } catch { /* ignore */ } esRef.current = null; }
                if (panelOpen) connectSSE();
              }} />
            <div className="as-hint" style={{ fontSize: 12, opacity: 0.65, lineHeight: 1.6, marginTop: 4 }}>服务端设置 AGENT_API_TOKEN 后，审批与模型设置需鉴权；此处填同一值。</div>
          </div>
          <label className="chk"><input type="checkbox" id="agentTestConn" checked={testConn} onChange={(e) => setTestConn(e.target.checked)} /> 应用后自动测试连接</label>
          <div id="agentApplyMsg" className={`as-test ${applyMsg.kind}`}>{applyMsg.text}</div>
        </div>
        <div className="agent-settings-foot">
          <button id="agentApplyModel" className="as-apply" type="button" onClick={applyModel}>应用模型</button>
          <button id="agentSettingsClose2" className="as-close" type="button" onClick={() => setSettingsOpen(false)}>关闭</button>
        </div>
      </aside>
    </>
  );
}