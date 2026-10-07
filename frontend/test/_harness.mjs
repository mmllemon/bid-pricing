/* frontend/test/ 的共享加载器：把页面脚本按真实顺序内联后交给 jsdom 执行。
 *
 * 单独一份的理由与 escape.js 同一原则：加载器不能有第二份实现——两份会各自漂移，
 * 于是「A 测试绿、B 测试红」而没人知道哪个反映了真实页面。
 *
 * 边界：jsdom 不是浏览器（无布局/绘制，SVG 与部分 DOM API 覆盖有限）。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import jsdomPkg from 'jsdom';

const { JSDOM, VirtualConsole } = jsdomPkg;

export const FE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/** 需要冒烟的全部页面（脚本顺序即站点真实加载顺序） */
export const PAGES = [
  'index.html',
  'tools.html',
  'tool-cable.html',
  'tool-duct.html',
  'tool-earth.html',
  'tool-well.html',
];

/** 一行的钢筋明细表行（把「启动瞬间钢筋表非空」这个 TDZ 触发条件造出来） */
export const REBAR_ROW = '<tr><td><input type="text" data-rf="no" value="①"></td>'
  + '<td><select data-rf="d"><option value="14" selected>14</option></select></td>'
  + '<td><input data-rf="len" type="number" value="1000"></td><td class="row-tw">—</td>'
  + '<td><input data-rf="span" type="number" value="0"></td>'
  + '<td><input data-rf="sp" type="number" value="150"></td>'
  + '<td><input data-rf="n" type="number" value="1"></td><td class="row-kg">0.0</td>'
  + '<td><input type="text" data-rf="note" value=""></td><td><button class="row-del">×</button></td></tr>';

const SCRIPT_RE = /<script src="([^"]+)"\s*><\/script>/g;

export const readPage = (page) => fs.readFileSync(path.join(FE_DIR, page), 'utf8');

export const scriptSrcs = (html) =>
  [...html.matchAll(SCRIPT_RE)].map((m) => m[1]);

/** 把外链脚本就地替换成内联内容，保留原有先后顺序。 */
export function inlineScripts(html, { omit = null } = {}) {
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
 * 按 URL 片段路由的 fetch 桩。返回的 `calls` 记录每次请求，便于断言
 * 「不该发的请求没发」——这比断言 UI 文案可靠得多。
 */
export function makeFetchStub(routes, calls = []) {
  const stub = (url, opts = {}) => {
    const u = String(url);
    const body = opts.body;
    const isForm = Boolean(body && typeof body.get === 'function');
    calls.push({ url: u, formData: isForm ? body : null });
    for (const [frag, payload] of Object.entries(routes)) {
      if (u.includes(frag)) {
        return Promise.resolve({
          ok: payload.ok !== false,
          status: payload.ok === false ? 422 : 200,
          json: async () => payload.json,
          text: async () => JSON.stringify(payload.json),
        });
      }
    }
    return Promise.resolve({
      ok: false, status: 0,
      json: async () => ({ status: 'BLOCKED', reason: `jsdom: 端点未桩化 ${u}` }),
    });
  };
  stub.calls = calls;
  return stub;
}

/**
 * 在 jsdom 里加载一个页面。
 *
 * @param {string} page
 * @param {object} opts
 * @param {object}  opts.seed        预置 localStorage（键 → 值字符串）
 * @param {boolean} opts.injectRebar 是否往 #rebarRows 预置一行
 * @param {string}  opts.omit        故意不加载某个脚本（负向验证用）
 * @param {Function} opts.fetchStub  替换 window.fetch（默认「永远不可达」）
 * @param {string}  opts.hash        加载时带的 hash（如 '#quote'）。
 *   交互用例应当**在加载时就带 hash**，而不是加载后再改 `location.hash`：
 *   jsdom 会为 hash 赋值再排入额外的 hashchange 任务，那些任务会在用例点击之后
 *   才跑 selectModule → closeOverlays()，把刚打开的弹层关掉（实测踩过，
 *   症状与「弹层打不开」无法区分）。
 */
export function loadPage(page, opts = {}) {
  const {
    seed = {}, injectRebar = false, omit = null, fetchStub = null, hash = '',
  } = opts;
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
    url: `http://localhost:8080/${page}${hash}`,
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(window) {
      // 页面初始化会调后端 API，而 jsdom 没有 fetch。默认给一个「永远不可达」的桩，
      // 让判据聚焦脚本自身的初始化错误；需要走流程的用例传入自己的路由桩。
      window.fetch = fetchStub || (() => Promise.resolve({
        ok: false, status: 0, json: async () => ({ status: 'BLOCKED', reason: 'jsdom: 无后端' }),
      }));
      if (!window.matchMedia) {
        window.matchMedia = () => ({
          matches: false, addListener() {}, removeListener() {},
          addEventListener() {}, removeEventListener() {},
        });
      }
      for (const [k, v] of Object.entries(seed)) {
        try { window.localStorage.setItem(k, v); } catch { /* 存储不可用则忽略 */ }
      }
    },
  });

  return { dom, window: dom.window, errors, inlined: inlined.count };
}

/** 让已排入的宏任务跑完（fetch 桩、防抖等），再判定错误。 */
export const settle = (ms = 0) => new Promise((resolve) => setTimeout(resolve, ms));

/** 多轮让出事件循环，等链式 await（如 initDashboard → loadBidProjectOptions）跑完。 */
export async function settleTicks(n = 4) {
  for (let i = 0; i < n; i += 1) await settle(0);
}

/**
 * 等「初始化尾部」跑完 —— 交互类用例动手前**必须**先过这一步。
 *
 * 为什么：app.js 的 initDashboard 把**初始模块选择**放进了一个 setTimeout 宏任务
 * （注释里写明是为避开模块级 let 的 TDZ），而 selectModule → closeOverlays() →
 * closePlanHub()。若用例在这个宏任务之前就打开弹层，它会被紧随其后的初始化关掉——
 * 实测症状极具误导性：点击后**立即**读出 `plan-hub open` / `body[tabindex=-1]`，
 * 一个 tick 之后就全没了，于是判据会得出「弹层打不开」这种与事实相反的错误结论。
 * 同一个尾部还会把 `activeGroup/dashActive/lastResult` 清空，所以凡是走「先出结果、
 * 再看结果态」的用例都必须等它结束。
 *
 * 判定信号：初始模块选择完成后，`location.hash` 非空且导航项出现 `.active`。
 */
export async function waitForInit(window, ticks = 60) {
  for (let i = 0; i < ticks; i += 1) {
    if (window.location.hash !== '' && window.document.querySelector('.nav-item.active')) return true;
    await settle(0);
  }
  return false;
}

/** 给 <input type=file> 装上文件并触发 change（jsdom 里 files 是只读的，需 defineProperty）。 */
export function setInputFiles(window, id, name = 'x.xlsx') {
  const el = window.document.querySelector(`#${id}`);
  const file = new window.File([new window.Uint8Array([1, 2, 3])], name);
  Object.defineProperty(el, 'files', { value: [file], configurable: true });
  el.dispatchEvent(new window.Event('change', { bubbles: true }));
  return el;
}
