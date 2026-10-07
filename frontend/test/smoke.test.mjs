/* frontend/ 的回归冒烟（node:test + jsdom）。
 *
 * 为什么需要它：本仓对 Python 侧的口径是「闸门是代码，不是约定」，而前端此前没有任何
 * 自动判据。实测踩到的三类问题**静态看代码都不像有问题**：
 *   1. 初始化顺序（TDZ）：tool-well.js 的 recalcUnitKgPerM 声明在启动调用之后，
 *      只因为「启动瞬间钢筋表恰好为空」才没炸（换成非空输入即 ReferenceError）。
 *   2. 脚本加载顺序：四个工具页不加载 js/escape.js，于是各脚本各自长出一份转义副本
 *      （最多 6 份），一份漏改就开洞。
 *   3. 破缓存令牌：同一份共享脚本在不同页面用不同 ?v=，改了只有部分页面生效。
 *
 * 本文件把这三类做成机械判据：把页面的 <script src> 按**原顺序**内联后交给 jsdom 真实
 * 执行，未捕获错误即失败；另加纯文本判据（加载顺序、令牌一致性、引用文件存在性）。
 *
 * 边界（如实标注）：jsdom 不是浏览器——没有布局与绘制，SVG/DOM API 覆盖有限。
 * 它能拦「运行就炸」，拦不住任何视觉回归；视觉仍需人看。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import assert from 'node:assert/strict';
import jsdomPkg from 'jsdom';

const { JSDOM, VirtualConsole } = jsdomPkg;

const FE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/** 需要冒烟的全部页面（脚本顺序即站点真实加载顺序） */
const PAGES = [
  'index.html',
  'tools.html',
  'tool-cable.html',
  'tool-duct.html',
  'tool-earth.html',
  'tool-well.html',
];

/** 一行的钢筋明细表行（用于把「启动瞬间钢筋表非空」这个 TDZ 触发条件造出来） */
const REBAR_ROW = '<tr><td><input type="text" data-rf="no" value="①"></td>'
  + '<td><select data-rf="d"><option value="14" selected>14</option></select></td>'
  + '<td><input data-rf="len" type="number" value="1000"></td><td class="row-tw">—</td>'
  + '<td><input data-rf="span" type="number" value="0"></td>'
  + '<td><input data-rf="sp" type="number" value="150"></td>'
  + '<td><input data-rf="n" type="number" value="1"></td><td class="row-kg">0.0</td>'
  + '<td><input type="text" data-rf="note" value=""></td><td><button class="row-del">×</button></td></tr>';

const SCRIPT_RE = /<script src="([^"]+)"\s*><\/script>/g;

function readPage(page) {
  return fs.readFileSync(path.join(FE_DIR, page), 'utf8');
}

function scriptSrcs(html) {
  return [...html.matchAll(SCRIPT_RE)].map((m) => m[1]);
}

/** 把外链脚本就地替换成内联内容，保留原有先后顺序。 */
function inlineScripts(html, { omit = null } = {}) {
  let count = 0;
  const out = html.replace(SCRIPT_RE, (_m, src) => {
    const rel = src.split('?')[0].replace(/^\.\//, '');
    if (rel === omit) return '';
    count += 1;
    return `<script>${fs.readFileSync(path.join(FE_DIR, rel), 'utf8')}</script>`;
  });
  return { html: out, count };
}

/**
 * 在 jsdom 里加载一个页面。
 *
 * @param {string} page                    页面文件名
 * @param {object} opts
 * @param {object} opts.seed             预置 localStorage（键 → 值字符串）
 * @param {boolean} opts.injectRebar     是否往 #rebarRows 预置一行
 * @param {string|null} opts.omit        故意不加载某个脚本（负向验证用）
 */
function loadPage(page, opts = {}) {
  const { seed = {}, injectRebar = false, omit = null } = opts;
  let html = readPage(page);
  if (injectRebar) {
    html = html.replace('<tbody id="rebarRows"></tbody>', `<tbody id="rebarRows">${REBAR_ROW}</tbody>`);
  }
  const inlined = inlineScripts(html, { omit });

  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', (e) => errors.push(e.message + (e.detail ? ` | ${e.detail}` : '')));

  const dom = new JSDOM(inlined.html, {
    runScripts: 'dangerously',
    url: `http://localhost:8080/${page}`,
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(window) {
      // 页面初始化会调后端 API，而 jsdom 没有 fetch。给一个「永远不可达」的桩，
      // 让判据聚焦在脚本自身的初始化错误上，而不是网络可达性。
      window.fetch = () => Promise.resolve({
        ok: false, status: 0, json: async () => ({ status: 'BLOCKED', reason: 'jsdom: 无后端' }),
      });
      if (!window.matchMedia) {
        window.matchMedia = () => ({
          matches: false, addListener() {}, removeListener() {},
          addEventListener() {}, removeEventListener() {},
        });
      }
      for (const [k, v] of Object.entries(seed)) {
        try { window.localStorage.setItem(k, v); } catch { /* 忽略存储不可用 */ }
      }
    },
  });

  return { dom, window: dom.window, errors, inlined: inlined.count };
}

/** 让已排入的微/宏任务跑完（fetch 桩、防抖等），再判定错误。 */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

// ---------------------------------------------------------------- 运行判据


test('每个页面按真实顺序执行脚本，且无未捕获错误', async (t) => {
  for (const page of PAGES) {
    await t.test(page, async () => {
      const { window, errors, inlined } = loadPage(page);
      await settle();
      assert.ok(inlined > 0, `${page} 应当有外链脚本`);
      assert.deepEqual(errors, [], `${page} 出现未捕获错误`);
      assert.ok(window.document.querySelector('.sidebar, .main-content'),
        `${page} 主结构未渲染`);
      window.close();
    });
  }
});

test('js/escape.js 必须是每个页面的第一个脚本（R1 契约）', async (t) => {
  for (const page of PAGES) {
    await t.test(page, () => {
      const srcs = scriptSrcs(readPage(page)).map((s) => s.split('?')[0].replace(/^\.\//, ''));
      assert.equal(srcs[0], 'js/escape.js',
        `${page} 第一个脚本应为 js/escape.js，实际是 ${srcs[0]}`);
    });
  }
});

test('转义实现唯一：toolEsc 与 gcEsc 是同一个函数，五个字符都被转义', async () => {
  const { window, errors } = loadPage('tool-well.html');
  await settle();
  assert.deepEqual(errors, []);
  assert.equal(typeof window.gcEsc, 'function', 'escape.js 应导出 gcEsc');
  assert.equal(window.gcEsc, window.gcAttr, 'gcAttr 应与 gcEsc 同一实现');
  assert.equal(window.toolEsc, window.gcEsc, 'toolEsc 应直接引用 gcEsc（不得自带副本）');
  assert.equal(window.gcEsc('<a href="x">&\'</a>'),
    '&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;');
  assert.equal(window.gcEsc(null), '', 'null 应转义为空串（调用点无需自己判空）');
  assert.equal(window.gcEsc(undefined), '');
  window.close();
});

test('破缓存令牌：同一资产在所有引用页用同一个 ?v=（R10）', () => {
  const byAsset = new Map();
  for (const page of PAGES) {
    for (const m of readPage(page).matchAll(/(?:src|href)="\.?\/?([^"?]+)\?v=([^"]+)"/g)) {
      const asset = m[1].replace(/^\.\//, '');
      if (!byAsset.has(asset)) byAsset.set(asset, new Map());
      const tokens = byAsset.get(asset);
      if (!tokens.has(m[2])) tokens.set(m[2], []);
      tokens.get(m[2]).push(page);
    }
  }
  const bad = [];
  for (const [asset, tokens] of byAsset) {
    if (tokens.size > 1) {
      bad.push(`${asset} 有 ${tokens.size} 个令牌：`
        + [...tokens].map(([tok, pages]) => `${tok}(${pages.join(',')})`).join(' vs '));
    }
  }
  assert.deepEqual(bad, [], `令牌不一致：\n${bad.join('\n')}`);
});

test('页面引用的本地资产都存在（防改名/删除后留死链）', () => {
  const missing = [];
  for (const page of PAGES) {
    const html = readPage(page);
    for (const m of html.matchAll(/(?:src|href)="\.\/([^"?]+)(?:\?[^"]*)?"/g)) {
      const rel = m[1];
      if (!fs.existsSync(path.join(FE_DIR, rel))) missing.push(`${page} → ${rel}`);
    }
  }
  assert.deepEqual(missing, [], `死链：\n${missing.join('\n')}`);
});

test('tool-well 初始化顺序：钢筋表非空 + 支室数 > 0 也不得抛错（R4 回归）', async () => {
  const { window, errors } = loadPage('tool-well.html', {
    injectRebar: true,
    seed: { 'bidpricing.tool-well.v1': JSON.stringify({ wBrN: '1', wL: '3.5', wW: '2', wD: '1.5' }) },
  });
  await settle();
  assert.deepEqual(errors, [],
    '启动路径不得依赖「钢筋表恰好在首调时为空」这一数据巧合（TDZ）');
  assert.equal(window.document.querySelector('#wBrN').value, '1',
    '预置状态应被 applyWellState 恢复，否则这条用例没有真的走到 nB>0 分支');
  assert.ok(window.document.querySelector('#wellTotal').textContent.trim() !== '',
    'recalcWell 应完成并写出合计');
  window.close();
});
