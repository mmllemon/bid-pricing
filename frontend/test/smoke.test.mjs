/* frontend/ 的静态与启动冒烟（node:test + jsdom）。
 *
 * 为什么需要它：本仓对 Python 侧的口径是「闸门是代码，不是约定」，而前端此前没有任何
 * 自动判据。实测踩到的三类问题**静态看代码都不像有问题**：
 *   1. 初始化顺序（TDZ）：tool-well.js 的 rebarUnitKgPerM 声明在启动调用之后，
 *      只因为「启动瞬间钢筋表恰好为空」才没炸（换成非空输入即 ReferenceError）。
 *   2. 脚本加载顺序：四个工具页不加载 js/escape.js，于是各脚本各自长出一份转义副本
 *      （最多 6 份），一份漏改就开洞。
 *   3. 破缓存令牌：同一份共享脚本在不同页面用不同 ?v=，改了只有部分页面生效。
 *
 * 本文件把这三类做成机械判据。运行：`npm test`（工作目录 frontend/）。
 * 边界：jsdom 不是浏览器——能拦「运行就炸」，**拦不住视觉回归**。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

import {
  FE_DIR, PAGES, loadPage, readPage, scriptSrcs, settle,
} from './_harness.mjs';

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
    for (const m of readPage(page).matchAll(/(?:src|href)="\.\/([^"?]+)(?:\?[^"]*)?"/g)) {
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

// ---------------------------------------------------------------- 静态契约（R9/R12/R14）

const JS_FILES = ['app.js', 'agent-panel.js',
  ...['escape', 'workbench-nav', 'sidebar', 'toast', 'dropdown', 'confirm', 'tool-common',
    'tool-cable', 'tool-duct', 'tool-earth', 'tool-well'].map((n) => `js/${n}.js`)];
const TOOL_PAGES = ['tools.html', 'tool-cable.html', 'tool-duct.html', 'tool-earth.html', 'tool-well.html'];
const CSS_FILES = ['tokens.css', 'styles.css', 'quote-dashboard.css', 'results.css', 'tools.css', 'agent.css'];

/* 静态判据必须只看**代码**，不看注释。
 * 本轮实测：两条判据先是被自己的说明性注释绊红（注释里为讲清历史写了 `calculateBtn.click()`
 * 与 `quote-dashboard.css`）——这正是本仓已记录两次的同一教训（CC-12 / BB-05：要拦的是
 * 代码路径上的硬拷贝，不是文档里提到这个词）。
 * 注意 JS 里只剥「行首 //」与块注释，避免把字符串里的 `http://` 当成注释切掉。 */
const stripJsComments = (src) => src
  .replace(/\/\*[\s\S]*?\*\//g, ' ')
  .replace(/^[ \t]*\/\/[^\n]*$/gm, ' ');
const stripHtmlComments = (src) => src.replace(/<!--[\s\S]*?-->/g, ' ');

test('R6 坞主 CTA 的不可达回退分支已删', () => {
  const app = stripJsComments(readPage('app.js'));
  assert.ok(!app.includes('calculateBtn.click()'),
    '坞主 CTA（#dockCalcBtn）空态置灰（syncDockCta: btn.disabled = !dashActive），'
    + '原先那条「else → 转发到 preparePanel 主 CTA」永远走不到；留着会让后人误以为空态可用，'
    + '且若真被走到会绕过 preparePanel 的就绪门控。请保持删除状态。');
});

test('R9 确认框只有一个创建点：不得再有第二份 #ui-confirm 实现', () => {
  const creators = JS_FILES.filter((f) => /id\s*=\s*['"]ui-confirm['"]/.test(stripJsComments(readPage(f))));
  assert.deepEqual(creators, ['js/confirm.js'],
    '创建 #ui-confirm 的文件应当只有 js/confirm.js（两处实现各自 createElement 同一个 id，'
    + '靠「永不同页加载」侥幸不冲突）；如新增了调用方，请传 options 而不是再写一份实现');
  // 两个使用方都必须**委托**给共享实现，而不是各写一份
  assert.ok(readPage('app.js').includes('window.gcConfirm('),
    'app.js 的 uiConfirm 应委托给 window.gcConfirm');
  assert.ok(readPage('js/tool-well.js').includes('window.gcConfirm('),
    'tool-well.js 应委托给 window.gcConfirm');
  // 使用方必须先在脚本顺序里拿到它
  for (const [page, consumer] of [['index.html', 'app.js'], ['tool-well.html', 'js/tool-well.js']]) {
    const order = scriptSrcs(readPage(page)).map((s) => s.split('?')[0].replace(/^\.\//, ''));
    assert.ok(order.includes('js/confirm.js'), `${page} 应加载 js/confirm.js`);
    assert.ok(order.indexOf('js/confirm.js') < order.indexOf(consumer),
      `${page}：confirm.js 必须在 ${consumer} 之前加载`);
  }
});

test('R12 孤儿样式表已删除，且 :root 只剩 tokens.css 一处', () => {
  assert.equal(fs.existsSync(path.join(FE_DIR, 'workbench-standalone.css')), false,
    'workbench-standalone.css 无任何引用（文档已登记为孤儿），已删除；不要以任何理由恢复它');
  const referenced = [...PAGES, ...JS_FILES]
    .filter((f) => stripHtmlComments(stripJsComments(readPage(f))).includes('workbench-standalone'));
  assert.deepEqual(referenced, [], '不应再有任何页面/脚本引用 workbench-standalone');
  const rootOwners = CSS_FILES.filter((f) => /:root\s*\{/.test(readPage(f)));
  assert.deepEqual(rootOwners, ['tokens.css'],
    '「一处改色、整站换肤」的前提是 :root 只有一份（UI_REFACTOR_V2_PLAN 自陈的判据）');
});

test('R14 工具页不得依赖报价页视图层；三个共用基础件由 styles.css 提供', () => {
  for (const page of TOOL_PAGES) {
    assert.ok(!stripHtmlComments(readPage(page)).includes('quote-dashboard.css'),
      `${page} 不应加载 quote-dashboard.css（报价页视图层）——实测只用 3 个基础件`);
  }
  assert.ok(stripHtmlComments(readPage('index.html')).includes('quote-dashboard.css'),
    '报价页仍需要 quote-dashboard.css（那是它的视图层）');
  const styles = readPage('styles.css');
  for (const cls of ['.title-dot', '.card-subtitle', '.tabular']) {
    assert.ok(styles.includes(`${cls}{`), `${cls} 应由 styles.css 提供（工具页也用它）`);
  }

  // 依赖面交叉核对：工具页用到、且**仅**由 quote-dashboard.css 以「简单类选择器」定义的类。
  // （DOM 探测会漏掉只在 JS 模板串里出现、点开才渲染的类，所以用源码级核对。）
  // 只认简单类选择器（.cls / .cls:hover）：复合选择器（如 .plan-hub.open）不算独立定义——
  // 依赖它必然同时依赖 .plan-hub，那个类会在下面被单独抓到，否则会把 `.open` 这类
  // 纯状态名误报成「工具页依赖报价页样式」。
  const simpleOwners = new Map();
  const own = (cls, f) => { if (!simpleOwners.has(cls)) simpleOwners.set(cls, new Set()); simpleOwners.get(cls).add(f); };
  for (const f of CSS_FILES) {
    const src = readPage(f).replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/@(media|supports|layer|container)[^{]*\{/g, ' ');
    for (const chunk of src.split('}')) {
      if (!chunk.includes('{')) continue;
      for (const one of chunk.split('{')[0].split(',')) {
        const m = one.trim().match(/^\.([-\w]+)((?::?:?[-\w]+(\([^)]*\))?)*)$/);
        if (m) own(m[1], f);
      }
    }
  }

  const used = new Map();
  const add = (cls, f) => { if (!used.has(cls)) used.set(cls, new Set()); used.get(cls).add(f); };
  const toolSources = [...TOOL_PAGES, ...JS_FILES.filter((f) => f.startsWith('js/tool') || f === 'js/dropdown.js')];
  for (const f of toolSources) {
    const src = stripHtmlComments(readPage(f));
    for (const m of src.matchAll(/class(?:Name)?\s*=\s*["'`]([^"'`]+)["'`]/g)) m[1].split(/\s+/).forEach((c) => add(c, f));
    for (const m of src.matchAll(/classList\.(?:add|remove|toggle)\(([^)]*)\)/g)) {
      for (const q of m[1].matchAll(/['"`]([^'"`]+)['"`]/g)) q[1].split(/\s+/).forEach((c) => add(c, f));
    }
  }

  const offenders = [];
  for (const [cls, files] of used) {
    const owners = simpleOwners.get(cls);
    if (owners && owners.size && [...owners].every((f) => f === 'quote-dashboard.css')) {
      offenders.push(`.${cls} ← ${[...files].join(', ')}`);
    }
  }
  assert.deepEqual(offenders, [],
    `工具页不得依赖只存在于 quote-dashboard.css 的类：\n${offenders.join('\n')}`);
});
