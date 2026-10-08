import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import PageHead from '../components/PageHead';
import { api } from '../api/client';
import type {
  KnowledgeStatus,
  KnowledgeDocument,
  KnowledgeSearchHit,
} from '../types';
import ActionProgress from '../components/ActionProgress';
import { useActionProgress } from '../lib/actionProgress';

// ===== 工具 =====
function formatTime(t: string | null): string {
  if (!t) return '—';
  const d = new Date(t);
  if (Number.isNaN(d.getTime())) return t;
  return d.toLocaleString();
}

function formatChars(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1)} 万`;
  return n.toLocaleString();
}

function formatSize(chars: number): string {
  // 粗略按 1 字符 ≈ 1 字节估算显示（仅展示用途）
  if (chars >= 1024 * 1024) return `${(chars / 1024 / 1024).toFixed(1)} MB`;
  if (chars >= 1024) return `${(chars / 1024).toFixed(1)} KB`;
  return `${chars} B`;
}

/** 示例搜索词 */
const EXAMPLE_QUERIES = ['清单计价', '定额套项', '工程签证', '电缆敷设'];

type Tab = 'search' | 'library';

export default function KnowledgePage() {
  const [activeTab, setActiveTab] = useState<Tab>('search');
  const [status, setStatus] = useState<KnowledgeStatus | null>(null);
  const [statusMsg, setStatusMsg] = useState('');

  // ===== 搜知识库（本地全文检索，不带 AI 问答）=====
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<KnowledgeSearchHit[]>([]);
  const [total, setTotal] = useState(0);
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchMsg, setSearchMsg] = useState('');
  const [lastTerms, setLastTerms] = useState<string[]>([]);

  // ===== 资料库 =====
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [docLoading, setDocLoading] = useState(false);
  const [docSearch, setDocSearch] = useState('');
  const [docFilter, setDocFilter] = useState<'all' | 'small' | 'large'>('all');
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState('');
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadProgress = useActionProgress();

  // ===== 状态加载（本地恒在线）=====
  const loadStatus = useCallback(async () => {
    setStatusMsg('');
    try {
      const s = await api.getKnowledgeStatus();
      setStatus(s);
    } catch (e) {
      setStatus(null);
      setStatusMsg((e as Error).message);
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  // ===== 检索 =====
  const doSearch = useCallback(
    async (q?: string) => {
      const finalQ = (q ?? query).trim();
      if (!finalQ || searching) return;
      setSearching(true);
      setSearchMsg('');
      try {
        const r = await api.searchKnowledge(finalQ);
        setHits(r.hits);
        setTotal(r.total);
        setSearched(true);
        // 关键词高亮用：按空白/标号分词 + 整词
        const terms = Array.from(
          new Set(
            [finalQ, ...finalQ.split(/[\s,，、。；;：:！!？?（）()【】]+/)]
              .map((t) => t.trim())
              .filter((t) => t.length >= 1)
          )
        ).slice(0, 10);
        setLastTerms(terms);
        if (r.total === 0) setSearchMsg('没有找到匹配的片段，换个关键词试试。');
      } catch (e) {
        setSearchMsg(`检索失败：${(e as Error).message ?? '未知错误'}`);
      } finally {
        setSearching(false);
      }
    },
    [query, searching]
  );

  /** 摘要关键词高亮 */
  const highlight = useCallback(
    (text: string) => {
      if (lastTerms.length === 0) return text;
      const pattern = lastTerms
        .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
        .sort((a, b) => b.length - a.length)
        .join('|');
      const parts = text.split(new RegExp(`(${pattern})`, 'gi'));
      return parts.map((p, i) =>
        lastTerms.some((t) => t.toLowerCase() === p.toLowerCase()) ? (
          <mark key={i}>{p}</mark>
        ) : (
          <span key={i}>{p}</span>
        )
      );
    },
    [lastTerms]
  );

  // ===== 资料库 =====
  const loadDocuments = useCallback(async () => {
    setDocLoading(true);
    try {
      const r = await api.getKnowledgeDocuments();
      setDocuments(r.documents);
    } catch (e) {
      setDocLoading(false);
      setUploadMsg((e as Error).message);
      return;
    }
    setDocLoading(false);
  }, []);

  useEffect(() => {
    loadDocuments();
  }, [activeTab, loadDocuments]);

  const handleUpload = useCallback(
    async (file: File) => {
      if (!file) return;
      if (!file.name.toLowerCase().endsWith('.md')) {
        setUploadMsg('目前仅支持 .md Markdown 文件');
        return;
      }
      if (file.size > 10 * 1024 * 1024) {
        setUploadMsg('文件不能超过 10 MB');
        return;
      }
      setUploading(true);
      setUploadMsg('');
      try {
        await uploadProgress.run(async () => {
          const r = await api.uploadKnowledge(file);
          setUploadMsg(`已上传「${r.document.name}」，切分 ${r.document.chunks} 个片段。`);
          await loadDocuments();
          await loadStatus();
        }, { label: '正在导入 Markdown', successMessage: '文档已导入' });
      } catch (e) {
        const err = e as { message?: string };
        setUploadMsg(`上传失败：${err.message ?? '未知错误'}`);
      } finally {
        setUploading(false);
        if (fileInputRef.current) fileInputRef.current.value = '';
      }
    },
    [loadDocuments, loadStatus, uploadProgress.run]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      setDeletingId(id);
      setUploadMsg('');
      try {
        const r = await api.deleteKnowledgeDoc(id);
        setUploadMsg(r.message);
        setDeleteConfirm(null);
        await loadDocuments();
        await loadStatus();
      } catch (e) {
        const err = e as { message?: string };
        setUploadMsg(`删除失败：${err.message ?? '未知错误'}`);
      } finally {
        setDeletingId(null);
      }
    },
    [loadDocuments, loadStatus]
  );

  // 文档筛选
  const filteredDocs = useMemo(() => {
    let list = documents;
    if (docSearch.trim()) {
      const kw = docSearch.trim().toLowerCase();
      list = list.filter((d) => d.name.toLowerCase().includes(kw));
    }
    if (docFilter !== 'all') {
      const threshold = 10 * 1024;
      list = list.filter((d) => (docFilter === 'small' ? d.characters < threshold : d.characters >= threshold));
    }
    return list;
  }, [documents, docSearch, docFilter]);

  // 计数汇总
  const totalDocs = status?.documents ?? documents.length;
  const totalChars = status?.characters ?? documents.reduce((n, d) => n + d.characters, 0);
  const totalChunks = status?.chunks ?? documents.reduce((n, d) => n + d.chunks, 0);

  return (
    <div className="ui-page">
      <PageHead zh="知识大脑" en="Knowledge" sub="你的知识，随时可搜。" subEn="Your knowledge, searchable in seconds.">
        <div className="flex items-center gap-2">
          <span className="nb-badge nb-badge--olive">本地全文检索</span>
          {status && (
            <button className="nb-btn nb-btn--ghost" style={{ fontSize: 13, padding: '6px 14px' }} onClick={loadStatus}>
              刷新状态
            </button>
          )}
        </div>
      </PageHead>

      {statusMsg && (
        <div className="ui-alert ui-alert--error">
          <p style={{ fontSize: 14 }}>状态加载失败：{statusMsg}</p>
          <button className="nb-btn nb-btn--denim" style={{ marginTop: 10 }} onClick={loadStatus}>
            重试
          </button>
        </div>
      )}

      {/* 页签 */}
      <div className="nb-tabs">
        <button className={`nb-tab ${activeTab === 'search' ? 'nb-tab--active' : ''}`} onClick={() => setActiveTab('search')}>
          搜知识库
        </button>
        <button className={`nb-tab ${activeTab === 'library' ? 'nb-tab--active' : ''}`} onClick={() => setActiveTab('library')}>
          资料库
        </button>
      </div>

      {/* ===== 搜知识库 ===== */}
      {activeTab === 'search' && (
        <>
          {status && (
            <div className="ui-receipt">
              <div className="flex gap-2" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
                <span className="nb-muted" style={{ fontSize: 13 }}>
                  文档 {status.documents} · 片段 {status.chunks} · 共 {formatChars(status.characters)} 字
                </span>
                <span className="nb-muted" style={{ fontSize: 13 }}>
                  · 关键词按文件名/标题/正文加权排序，不带 AI 问答
                </span>
              </div>
            </div>
          )}

          {/* 搜索框 */}
          <div className="nb-card mb-4">
            <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
              <input
                className="nb-input"
                style={{ flex: 1, minWidth: 200 }}
                placeholder="输入关键词，如：定额套项、工程签证…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    doSearch();
                  }
                }}
                disabled={searching}
              />
              <button
                className="nb-btn nb-btn--primary"
                style={{ flexShrink: 0 }}
                onClick={() => doSearch()}
                disabled={searching || !query.trim()}
              >
                {searching ? '检索中…' : '检索'}
              </button>
            </div>
            {!searched && (
              <div className="flex gap-2 mt-3" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
                <span className="nb-muted" style={{ fontSize: 13 }}>试试：</span>
                {EXAMPLE_QUERIES.map((q) => (
                  <button key={q} className="nb-chip" onClick={() => { setQuery(q); doSearch(q); }}>
                    {q}
                  </button>
                ))}
              </div>
            )}
            {searchMsg && (
              <div className="nb-muted" style={{ fontSize: 13, marginTop: 10 }}>
                {searchMsg}
              </div>
            )}
          </div>

          {/* 检索结果 */}
          {searched && (
            <div className="nb-card">
              <h2 className="nb-section-title" style={{ fontSize: 18 }}>
                命中片段（{total}）
              </h2>
              {hits.length === 0 ? (
                <div className="empty-state">
                  <p>没有匹配的片段。</p>
                </div>
              ) : (
                <div className="note-table">
                  {hits.map((h, i) => (
                    <div key={`${h.document_id}-${i}`} className="note-row" style={{ padding: '12px' }}>
                      <div className="flex items-center gap-2" style={{ flexWrap: 'wrap', marginBottom: 6 }}>
                        <span className="nb-badge nb-badge--denim" style={{ fontSize: 11 }}>
                          {h.score.toFixed(0)}
                        </span>
                        <span style={{ fontWeight: 700, fontSize: 14 }}>{h.document_name}</span>
                        <span className="nb-muted" style={{ fontSize: 12 }}>／ {h.heading}</span>
                      </div>
                      <div style={{ fontSize: 13, lineHeight: 1.8 }}>{highlight(h.excerpt)}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* ===== 资料库 ===== */}
      {activeTab === 'library' && (
        <>
          {/* 统计 */}
          <div className="grid-auto mb-4">
            {[
              { label: '文档', value: totalDocs },
              { label: '知识片段', value: totalChunks },
              { label: '总字符', value: formatChars(totalChars) },
            ].map((m) => (
              <div key={m.label} className="ui-metric">
                <div className="ui-metric-label">{m.label}</div>
                <div className="ui-data">{m.value}</div>
              </div>
            ))}
          </div>

          {/* 上传区 */}
          <div className="nb-card mb-4">
            <div className="flex items-center justify-between mb-2" style={{ flexWrap: 'wrap', gap: 12 }}>
              <h2 className="nb-section-title" style={{ fontSize: 18 }}>上传新文档</h2>
              <span className="nb-muted" style={{ fontSize: 13 }}>.md · 最大 10 MB · 存本机可检索</span>
            </div>
            <div className="flex gap-2" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
              <input
                ref={fileInputRef}
                type="file"
                accept=".md"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleUpload(f);
                }}
              />
              <button className="nb-btn nb-btn--denim" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
                {uploading ? '上传中…' : '选择 .md 文件'}
              </button>
              <span className="nb-muted" style={{ fontSize: 13 }}>
                上传后按标题自动切分片段，建立本地全文索引。
              </span>
            </div>
            <ActionProgress progress={uploadProgress.progress} />
            {uploadMsg && (
              <div className="nb-muted" style={{ fontSize: 13, marginTop: 10 }}>
                {uploadMsg}
              </div>
            )}
          </div>

          {/* 搜索筛选 */}
          <div className="nb-card mb-4">
            <div className="flex gap-2" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
              <input
                className="nb-input"
                style={{ maxWidth: 260 }}
                placeholder="搜索文件名…"
                value={docSearch}
                onChange={(e) => setDocSearch(e.target.value)}
              />
              <select className="nb-input" style={{ maxWidth: 150 }} value={docFilter} onChange={(e) => setDocFilter(e.target.value as 'all' | 'small' | 'large')}>
                <option value="all">全部大小</option>
                <option value="small">小文件（&lt;10KB）</option>
                <option value="large">大文件（≥10KB）</option>
              </select>
            </div>
          </div>

          {/* 文档列表 */}
          <div className="nb-card">
            <div className="flex items-center justify-between mb-3">
              <h2 className="nb-section-title" style={{ fontSize: 22 }}>文档列表（{filteredDocs.length}）</h2>
            </div>
            {docLoading ? (
              <div className="empty-state"><p>加载文档中…</p></div>
            ) : filteredDocs.length === 0 ? (
              <div className="empty-state">
                <p>{docSearch || docFilter !== 'all' ? '没有匹配的文档。' : '暂无文档。点击上方「选择 .md 文件」上传第一个文档（比如从 ima 导出的造价资料）。'}</p>
              </div>
            ) : (
              <div className="note-table">
                {filteredDocs.map((d) => (
                  <div key={d.id} className="note-row" style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 12, alignItems: 'center', padding: '10px 12px' }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.name}</div>
                      <div className="nb-muted" style={{ fontSize: 12, marginTop: 2 }}>
                        上传于 {formatTime(d.uploaded_at)} · {d.chunks} 片段 · {formatSize(d.characters)}
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      <span className="nb-badge nb-badge--denim">片段 {d.chunks}</span>
                    </div>
                    <div>
                      {deleteConfirm === d.id ? (
                        <div className="flex gap-2">
                          <button className="nb-btn nb-btn--primary" style={{ fontSize: 12, padding: '5px 10px' }} onClick={() => handleDelete(d.id)} disabled={deletingId === d.id}>
                            {deletingId === d.id ? '删除中…' : '确认删除'}
                          </button>
                          <button className="nb-btn nb-btn--ghost" style={{ fontSize: 12, padding: '5px 10px' }} onClick={() => setDeleteConfirm(null)}>
                            取消
                          </button>
                        </div>
                      ) : (
                        <button className="nb-btn nb-btn--ghost" style={{ fontSize: 12, padding: '5px 10px', color: 'var(--red)' }} onClick={() => setDeleteConfirm(d.id)}>
                          删除
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
            <p className="nb-muted" style={{ fontSize: 12, marginTop: 12 }}>
              说明：文档存在本机（随工作台数据目录备份），删除后不可恢复，请谨慎操作。
            </p>
          </div>
        </>
      )}
    </div>
  );
}
