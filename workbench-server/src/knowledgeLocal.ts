// ============================================================
// 本地全文检索知识库（轻量版，不带 AI 问答）
// 2026-10-06 起替代已下线的外部 :8765 RAG 服务。
// 文档落盘 DATA_DIR/knowledge/<id>.md + index.json，不新增进程，
// 随 WORKBENCH_DATA_DIR 现有备份体系走（run.ps1 已覆盖该目录）。
// 检索：query 分词 → 文件名×3/小节标题×2/正文×1 加权计分，返回命中片段。
// ============================================================
import { existsSync, mkdirSync, readFileSync, writeFileSync, unlinkSync } from 'node:fs';
import { join, basename } from 'node:path';
import { randomUUID } from 'node:crypto';
import { DATA_DIR } from './db';
import { ensurePrivateDir } from './config/filePermissions';

const KB_DIR = join(DATA_DIR, 'knowledge');
ensurePrivateDir(KB_DIR);

export interface LocalKnowledgeDocument {
  id: string;
  name: string;
  uploaded_at: string;
  characters: number;
  chunks: number;
}

export interface LocalSearchHit {
  document_id: string;
  document_name: string;
  heading: string;
  excerpt: string;
  score: number;
}

interface Chunk {
  heading: string;
  text: string;
}

const INDEX_FILE = join(KB_DIR, 'index.json');
const ID_RE = /^[A-Za-z0-9-]{1,64}$/;

function readIndex(): LocalKnowledgeDocument[] {
  try {
    if (!existsSync(INDEX_FILE)) return [];
    const raw = JSON.parse(readFileSync(INDEX_FILE, 'utf-8'));
    return Array.isArray(raw) ? raw.filter((d) => d && ID_RE.test(d.id)) : [];
  } catch {
    return [];
  }
}

function writeIndex(docs: LocalKnowledgeDocument[]): void {
  mkdirSync(KB_DIR, { recursive: true });
  writeFileSync(INDEX_FILE, JSON.stringify(docs, null, 2), 'utf-8');
}

function docPath(id: string): string {
  return join(KB_DIR, `${id}.md`);
}

/** 按 markdown 标题切分知识片段；标题本身也进正文，保证标题可被检索 */
function chunkMarkdown(name: string, text: string): Chunk[] {
  const fallback = name.replace(/\.md$/i, '');
  const chunks: Chunk[] = [];
  let heading = fallback;
  let buf: string[] = [];
  const flush = () => {
    const t = buf.join('\n').trim();
    if (t) chunks.push({ heading, text: t.slice(0, 4000) });
    buf = [];
  };
  for (const line of text.split('\n')) {
    const m = /^(#{1,4})\s+(.+?)\s*$/.exec(line);
    if (m) {
      flush();
      heading = m[2].slice(0, 120);
      buf.push(m[2]);
    } else {
      buf.push(line);
    }
  }
  flush();
  return chunks;
}

/** 中文无空格：全 query 本身也作为一个 term；英文按空白/标点分词 */
function splitTerms(query: string): string[] {
  const full = query.trim().toLowerCase();
  if (!full) return [];
  const set = new Set<string>();
  if (full.length >= 2) set.add(full);
  for (const t of full.split(/[\s,，、。；;：:！!？?「」『』（）()【】[\]""''·—…\-_]+/)) {
    const w = t.trim();
    if (w.length >= 2) set.add(w);
  }
  return [...set].slice(0, 10);
}

function countOcc(hay: string, needle: string): number {
  if (!needle) return 0;
  let n = 0;
  let i = 0;
  while ((i = hay.indexOf(needle, i)) !== -1) {
    n++;
    i += needle.length;
  }
  return n;
}

function makeExcerpt(text: string, terms: string[]): string {
  const clean = text.replace(/\s+/g, ' ');
  const low = clean.toLowerCase();
  let pos = -1;
  for (const t of terms) {
    const p = low.indexOf(t);
    if (p !== -1 && (pos === -1 || p < pos)) pos = p;
  }
  if (pos === -1) return clean.slice(0, 160);
  const start = Math.max(0, pos - 70);
  const end = Math.min(clean.length, pos + 90);
  return (start > 0 ? '…' : '') + clean.slice(start, end) + (end < clean.length ? '…' : '');
}

export function getLocalKnowledgeStatus() {
  const docs = readIndex();
  return {
    online: true,
    mode: 'local' as const,
    documents: docs.length,
    chunks: docs.reduce((n, d) => n + d.chunks, 0),
    characters: docs.reduce((n, d) => n + d.characters, 0),
    checkedAt: new Date().toISOString(),
  };
}

export function listLocalKnowledgeDocuments(): LocalKnowledgeDocument[] {
  return readIndex();
}

export function addLocalKnowledgeDocument(buf: Buffer, filename: string): { document: LocalKnowledgeDocument } {
  const safe = basename(filename)
    .replace(/[^\w.\-() \u4e00-\u9fa5]/g, '_')
    .slice(0, 120) || 'unnamed.md';
  const name = safe.toLowerCase().endsWith('.md') ? safe : `${safe}.md`;
  const id = randomUUID().replace(/-/g, '');
  const text = buf.toString('utf-8');
  mkdirSync(KB_DIR, { recursive: true });
  writeFileSync(docPath(id), text, 'utf-8');
  const chunks = chunkMarkdown(name, text);
  const document: LocalKnowledgeDocument = {
    id,
    name,
    uploaded_at: new Date().toISOString(),
    characters: text.length,
    chunks: chunks.length,
  };
  const docs = readIndex();
  docs.unshift(document);
  writeIndex(docs);
  return { document };
}

export function deleteLocalKnowledgeDocument(id: string): { message: string } {
  if (!ID_RE.test(id)) throw new Error('文档 ID 格式不合法');
  const docs = readIndex();
  const ix = docs.findIndex((d) => d.id === id);
  if (ix === -1) throw new Error('文档不存在');
  const name = docs[ix].name;
  try {
    unlinkSync(docPath(id));
  } catch {
    /* 文件已不在，仅清索引 */
  }
  docs.splice(ix, 1);
  writeIndex(docs);
  return { message: `已删除「${name}」` };
}

export function searchLocalKnowledge(
  query: string,
  limit = 20
): { hits: LocalSearchHit[]; total: number } {
  const terms = splitTerms(query);
  if (terms.length === 0) return { hits: [], total: 0 };
  const docs = readIndex();
  const hits: LocalSearchHit[] = [];
  for (const d of docs) {
    let raw: string;
    try {
      raw = readFileSync(docPath(d.id), 'utf-8');
    } catch {
      continue;
    }
    const nameLow = d.name.toLowerCase();
    for (const c of chunkMarkdown(d.name, raw)) {
      const headLow = c.heading.toLowerCase();
      const textLow = c.text.toLowerCase();
      let score = 0;
      for (const t of terms) {
        score += countOcc(nameLow, t) * 3 + countOcc(headLow, t) * 2 + countOcc(textLow, t);
      }
      if (score > 0) {
        hits.push({
          document_id: d.id,
          document_name: d.name,
          heading: c.heading,
          excerpt: makeExcerpt(c.text, terms),
          score,
        });
      }
    }
  }
  hits.sort((a, b) => b.score - a.score);
  return { hits: hits.slice(0, Math.min(Math.max(limit, 1), 50)), total: hits.length };
}
