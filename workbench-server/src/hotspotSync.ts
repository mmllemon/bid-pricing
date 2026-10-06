import crypto from 'node:crypto';
import { XMLParser } from 'fast-xml-parser';
import {
  getCimiAccount,
  getTodayArticles,
  getArticleBody,
  normalizeWechatUrl,
  wechatExternalKey,
  countCjkChars,
  getCallStats,
  CIMIDATA_PRICE,
  CimiError,
} from './cimidata';
import { cleanWechatHtml, hasDangerousHtml } from './htmlCleaner';
import {
  getAllHotspotSources,
  getHotspotSource,
  updateHotspotSourceInfo,
  markHotspotFetch,
  upsertHotspotArticle,
  updateHotspotArticleBody,
  markArticleBodyPending,
  createFetchRun,
  finishFetchRun,
  type HotspotSourceRow,
} from './db';

// sync 防重入：进程内锁
let syncing = false;
export function isSyncing(): boolean {
  return syncing;
}

function hashBody(text: string): string {
  return crypto.createHash('sha256').update(text).digest('hex').slice(0, 24);
}

type CallKind = 'token' | 'account_info' | 'current' | 'body' | 'long2short';

function diffCalls(before: ReturnType<typeof getCallStats>, after: ReturnType<typeof getCallStats>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const key of ['token', 'account_info', 'current', 'body', 'long2short'] as CallKind[]) {
    const n = after[key] - before[key];
    if (n > 0) out[key] = n;
  }
  return out;
}

function callsCost(calls: Record<string, number>): number {
  return (
    (calls.account_info ?? 0) * CIMIDATA_PRICE.account_info +
    (calls.current ?? 0) * CIMIDATA_PRICE.current +
    (calls.body ?? 0) * CIMIDATA_PRICE.body +
    (calls.long2short ?? 0) * CIMIDATA_PRICE.long2short
  );
}

/**
 * 抓取单个来源的当天发文并入库。
 * 返回该来源的运行统计。即使某来源失败也不阻断整体。
 */
// ===== RSS 源同步（非微信链路）=====
// source_key 形如 'rss:https://aihot.news/feed.xml'。抓 feed → 逐条去重入库；
// 正文直接用 feed 的 description/summary（清洗后），不做额外的正文抓取。
const RSS_TIMEOUT_MS = 15000;
const RSS_MAX_ITEMS = 100;

function stripHtmlToText(html: string): string {
  return String(html || '')
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/\s+/g, ' ')
    .trim();
}

interface RssItem {
  title: string;
  url: string;
  publishTime: string | null;
  author: string | null;
  text: string;
}

function rssItemLink(link: unknown): string {
  if (typeof link === 'string') return link.trim();
  if (Array.isArray(link)) {
    const alt = link.find(
      (l) => l && typeof l === 'object' && ((l as Record<string, unknown>).rel === 'alternate' || !(l as Record<string, unknown>).rel),
    ) as Record<string, unknown> | undefined;
    const href = alt?.href ?? (link[0] as Record<string, unknown> | undefined)?.href;
    return typeof href === 'string' ? href.trim() : '';
  }
  if (link && typeof link === 'object') {
    const href = (link as Record<string, unknown>).href;
    return typeof href === 'string' ? href.trim() : '';
  }
  return '';
}

function parseRssItems(doc: unknown): RssItem[] {
  const d = doc as Record<string, any>;
  let raw: any[] = [];
  // RSS 2.0
  const channel = d?.rss?.channel;
  if (channel?.item) raw = Array.isArray(channel.item) ? channel.item : [channel.item];
  // Atom
  else if (d?.feed?.entry) raw = Array.isArray(d.feed.entry) ? d.feed.entry : [d.feed.entry];
  const items: RssItem[] = [];
  for (const it of raw.slice(0, RSS_MAX_ITEMS)) {
    const title = String(it?.title ?? '').trim();
    const url = rssItemLink(it?.link);
    if (!title || !url) continue;
    let publishTime: string | null = null;
    const rawTime = it?.pubDate ?? it?.published ?? it?.updated ?? null;
    if (rawTime) {
      const t = new Date(String(rawTime));
      if (!Number.isNaN(t.getTime())) publishTime = t.toISOString();
    }
    const descRaw = it?.description ?? it?.summary ?? it?.['content:encoded'] ?? '';
    const descStr = typeof descRaw === 'string' ? descRaw : String((descRaw as Record<string, unknown>)?.['#text'] ?? '');
    const text = stripHtmlToText(descStr).slice(0, 20000);
    const authorRaw = it?.author;
    const author = typeof authorRaw === 'string'
      ? authorRaw.trim() || null
      : String((authorRaw as Record<string, unknown> | undefined)?.name ?? '').trim() || null;
    items.push({ title, url, publishTime, author, text });
  }
  return items;
}

async function syncRssSource(
  source: HotspotSourceRow,
  triggeredBy: string,
): Promise<{
  status: 'ok' | 'error';
  article_found: number;
  inserted: number;
  updated: number;
  duplicate: number;
  body_fetched: number;
  error_message?: string;
}> {
  const runId = createFetchRun(source.id, triggeredBy);
  const stats = {
    article_found: 0,
    inserted: 0,
    updated: 0,
    duplicate: 0,
    body_fetched: 0,
    status: 'ok' as 'ok' | 'error',
  };
  try {
    const feedUrl = source.source_key.slice('rss:'.length).trim();
    if (!/^https?:\/\//i.test(feedUrl)) throw new Error('RSS 地址不合法');
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), RSS_TIMEOUT_MS);
    let xml: string;
    try {
      const res = await fetch(feedUrl, {
        headers: {
          'User-Agent': 'bid-pricing-hotspot/1.0 (+local rss reader)',
          Accept: 'application/rss+xml, application/xml, text/xml',
        },
        signal: ctrl.signal,
      });
      if (!res.ok) throw new Error(`RSS HTTP ${res.status}`);
      xml = await res.text();
    } finally {
      clearTimeout(timer);
    }
    const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '', trimValues: true });
    const items = parseRssItems(parser.parse(xml));
    stats.article_found = items.length;
    for (const it of items) {
      const externalKey = 'rss:' + hashBody(it.url);
      const result = upsertHotspotArticle({
        source_id: source.id,
        external_key: externalKey,
        title: it.title,
        url: it.url,
        digest: it.text ? it.text.slice(0, 200) : null,
        author: it.author,
        publish_time: it.publishTime,
      });
      if (result.status === 'inserted') stats.inserted += 1;
      else stats.duplicate += 1;
      // RSS 正文即 feed 摘要：新入库直接落盘，不另行抓取
      if (result.status === 'inserted' && it.text) {
        updateHotspotArticleBody(result.id, {
          body_text: it.text,
          body_hash: hashBody(it.text),
          too_short: countCjkChars(it.text) < 200,
        });
        stats.body_fetched += 1;
      }
    }
    markHotspotFetch(source.id, stats.article_found);
    finishFetchRun(runId, { ...stats, cost: 0, calls: {} });
    return { ...stats, status: 'ok' as const };
  } catch (e) {
    const msg = (e as Error).message;
    stats.status = 'error';
    finishFetchRun(runId, { ...stats, status: 'error', error_message: msg, cost: 0, calls: {} });
    return { ...stats, status: 'error' as const, error_message: msg };
  }
}

export async function syncOneSource(source: HotspotSourceRow, triggeredBy: string): Promise<{
  status: 'ok' | 'error';
  article_found: number;
  inserted: number;
  updated: number;
  duplicate: number;
  body_fetched: number;
  error_message?: string;
}> {
  // RSS 源（source_key = 'rss:<feed_url>'）：不走次幂/微信链路，直接抓 feed
  if (source.source_key.startsWith('rss:')) {
    return syncRssSource(source, triggeredBy);
  }
  const runId = createFetchRun(source.id, triggeredBy);
  const beforeCalls = getCallStats();
  const stats = {
    article_found: 0,
    inserted: 0,
    updated: 0,
    duplicate: 0,
    body_fetched: 0,
    status: 'ok' as 'ok' | 'error',
  };

  try {
    const nickname = source.source_key === 'wechat:huxiu' ? '虎嗅APP' : source.source_key === 'wechat:36kr' ? '36氪' : source.display_name;

    // 1. 初始化公众号信息（biz/wxid），非阻塞失败
    try {
      const account = await getCimiAccount(nickname);
      if (account) {
        updateHotspotSourceInfo(source.id, {
          biz: account.biz || undefined,
          wxid: account.id || undefined,
          avatar: account.avatar || undefined,
          signature: account.signature || undefined,
          fans: account.fans,
        });
      }
    } catch (e) {
      // 公众号信息拉取失败不阻断当天发文
      console.warn(`[hotspot] ${nickname} 公众号信息失败：${(e as Error).message}`);
    }

    // 2. 当天发文
    const articles = await getTodayArticles(nickname);
    stats.article_found = articles.length;

    // 3. 逐条去重入库
    for (const art of articles) {
      const normalizedUrl = normalizeWechatUrl(art.url);
      const externalKey = wechatExternalKey(art.url);
      const result = upsertHotspotArticle({
        source_id: source.id,
        external_key: externalKey,
        title: art.title,
        url: normalizedUrl,
        digest: art.digest ?? null,
        author: art.author ?? null,
        publish_time: art.publish_time ?? null,
      });
      if (result.status === 'inserted') {
        stats.inserted += 1;
      } else {
        stats.duplicate += 1;
      }

      // 4. 正文：新入库，或已入库但正文未就绪（duplicate 且 body_pending）的文章补抓正文
      //    使初次入库时正文失败（如 detail 报 1002）的文章可在后续同步重试
      const needBody = result.status === 'inserted' || result.bodyPending === true;
      if (needBody) {
        try {
          const body = await getArticleBody(normalizedUrl);
          if (body && body.html && !hasDangerousHtml(body.html)) {
            const clean = cleanWechatHtml(body.html);
            const cjk = countCjkChars(clean.text);
            updateHotspotArticleBody(result.id, {
              body_text: clean.text,
              body_hash: hashBody(clean.text),
              too_short: cjk < 200,
            });
            stats.body_fetched += 1;
          } else {
            markArticleBodyPending(result.id, '正文为空或含危险 HTML');
          }
        } catch (e) {
          markArticleBodyPending(result.id, (e as Error).message);
        }
      }
    }

    markHotspotFetch(source.id, stats.article_found);
    const calls = diffCalls(beforeCalls, getCallStats());
    finishFetchRun(runId, { ...stats, article_found: stats.article_found, cost: callsCost(calls), calls });
    return { status: 'ok', article_found: stats.article_found, inserted: stats.inserted, updated: stats.updated, duplicate: stats.duplicate, body_fetched: stats.body_fetched };
  } catch (e) {
    const msg = (e as Error).message;
    stats.status = 'error';
    const calls = diffCalls(beforeCalls, getCallStats());
    finishFetchRun(runId, { ...stats, status: 'error', error_message: msg, cost: callsCost(calls), calls });
    return { status: 'error', article_found: stats.article_found, inserted: stats.inserted, updated: stats.updated, duplicate: stats.duplicate, body_fetched: stats.body_fetched, error_message: msg };
  }
}

/**
 * 遍历所有启用来源执行一次完整同步。
 * 单来源失败不阻断其他来源。返回汇总。
 */
export async function runHotspotSync(triggeredBy: string): Promise<{
  syncStarted: boolean;
  total: number;
  sources: Array<{ source: string; status: string; article_found: number; inserted: number; duplicate: number; body_fetched: number; error_message?: string }>;
}> {
  if (syncing) {
    return { syncStarted: false, total: 0, sources: [] };
  }
  syncing = true;
  try {
    const sources = getAllHotspotSources().filter((s) => s.enabled === 1);
    const results: Array<{ source: string; status: string; article_found: number; inserted: number; duplicate: number; body_fetched: number; error_message?: string }> = [];
    for (const source of sources) {
      try {
        const r = await syncOneSource(source, triggeredBy);
        results.push({ source: source.display_name, ...r });
      } catch (e) {
        results.push({ source: source.display_name, status: 'error', article_found: 0, inserted: 0, duplicate: 0, body_fetched: 0, error_message: (e as Error).message });
      }
    }
    return { syncStarted: true, total: sources.length, sources: results };
  } finally {
    syncing = false;
  }
}

export { CimiError };
