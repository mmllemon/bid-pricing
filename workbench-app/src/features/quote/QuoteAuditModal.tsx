import { useEffect, useState } from 'react';
import { listAudit, type AuditRow } from './quoteApi';

/**
 * 审计日志弹层（P3 块4c：由 app.js openAuditModal/loadAudit/renderAudit + #auditModal 迁入 React）
 * 操作坞「审计日志」→ GET /api/audit/list（经 :3456 同源反代）。
 */
const AUDIT_ACTIONS: Record<string, string> = {
  'quote.optimize': '测算优化', 'plan.save': '保存方案', 'plan.finalize': '方案定稿',
  'plan.delete': '删除方案', 'group.create': '新建方案组', 'group.copy': '复制方案组',
  'group.delete': '删除方案组', 'group.rename': '重命名方案组', 'plan.compare': '方案对比',
  'group.finalize': '方案组定稿', 'plan.recompute': '方案重算', 'plan.copy': '复制方案',
};

function detailText(d: unknown): string {
  let t = d;
  if (typeof t === 'string') {
    try { const o = JSON.parse(t); t = (o && o.title) || t; } catch { /* raw */ }
  }
  return String(t ?? '').slice(0, 60);
}

export function QuoteAuditModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (!open) return;
    setRows(null); setErr('');
    listAudit(100).then(setRows).catch((e) => setErr((e as Error).message));
  }, [open]);

  if (!open) return null;
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;

  return (
    <div className="cmp-modal open" id="auditModal" role="dialog" aria-modal="true" aria-label="审计日志" aria-hidden={false}>
      <div className="cmp-mask" id="auditModalMask" data-close onClick={onClose} />
      <div className="cmp-panel" role="document">
        <div className="cmp-head">
          <h3>审计日志</h3>
          <button type="button" className="ph-close" id="auditModalCloseBtn" aria-label="关闭审计日志" onClick={onClose}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" width={14} height={14} aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
        <div className="cmp-body" id="auditModalBody" aria-live="polite">
          {err ? (
            <p className="audit-empty">审计日志读取失败：{err}</p>
          ) : rows === null ? (
            <p className="audit-empty">正在读取审计日志…</p>
          ) : rows.length === 0 ? (
            <p className="audit-empty">暂无审计记录</p>
          ) : (
            <>
              <div className="table-wrap">
                <table className="audit-table">
                  <thead><tr>
                    <th scope="col">时间</th><th scope="col">操作</th><th scope="col">状态</th>
                    <th scope="col">项目</th><th scope="col">方案</th><th scope="col">说明</th>
                  </tr></thead>
                  <tbody>
                    {rows.map((r, i) => {
                      let ts = r.ts || '';
                      try { ts = new Date(ts).toLocaleString('zh-CN', { timeZone: tz }); } catch { /* 原样 */ }
                      return (
                        <tr key={i}>
                          <td className="num">{ts}</td>
                          <td>{AUDIT_ACTIONS[r.action || ''] || r.action || ''}</td>
                          <td>{r.status ? <span className={`audit-${r.status}`}>{r.status}</span> : <span className="md">—</span>}</td>
                          <td>{r.project_id || ''}</td>
                          <td className="num">{(r.plan_id || '').slice(0, 8)}</td>
                          <td className="sec">{detailText(r.detail)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="audit-meta">共 {rows.length} 条（最近 100）· 本地时区 {tz}</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}