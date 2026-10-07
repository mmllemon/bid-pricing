/* 报价页交互路径的回归判据（node:test + jsdom）。
 *
 * 这一批判据针对三类**交互路径**问题——它们都不是「代码写错」，而是「状态没跟着走」：
 *   R5：焦点陷阱栈不平衡——关闭一个**并未打开**的弹层会弹掉别人压在栈里的那一项，
 *       于是仍然开着的方案中心失去焦点陷阱（切页/切项目时会串行关闭三个弹层）。
 *   R7：预览把右栏切回「无结果」态，却没跟上 `lastResult`，于是「重算」置灰了、
 *       「导出」还可点——点了导出的是**上一轮**的结果。
 *   R8：`numVal` 用 placeholder 兜底，目标总报价留空时被静默填成 `0.00` 提交；
 *       而后端 `target_total: float = Form(...)` 是**必填**且校验 `> 0`，
 *       结果是「用户没填」变成一次服务端报错，而不是就地提示。
 *
 * 每个用例都断言**可观察的后果**（DOM 状态 / 是否发出请求），不断言内部变量。
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  loadPage, makeFetchStub, settle, setInputFiles, waitForInit,
} from './_harness.mjs';

const RESULT_FIXTURE = {
  status: 'PASS', plan_id: 'plan-A', group_id: 'grp-1',
  excel_download_url: '/api/quote/download/plan-A',
  target_total: 1000000, objective: 123456.78, competitive_budget: 900000,
  low_ratio_review_required: false, cost_input_tax: null, items: [],
};

const PREVIEW_FIXTURE = {
  status: 'PASS', project_id: 'p-1',
  cap: { rows: 83, unit_works: { 电气设备安装工程: 83 }, hash_sha256: 'c32b4b70' },
  cost: { rows: 83, unit_works: { 电气设备安装工程: 83 }, hash_sha256: '441a40be' },
  match: { master_keys: 82, matched: 82, only_cap: 1, only_cost: 0, blocked: false, only_cap_ids: [] },
  optimizable_count: 80, manual_count: 2,
  missing_cap_ids: [], missing_cost_ids: [], duplicate_item_id_across_unit_work: [],
  anomaly_count: 0, anomalies: [],
  fields: { item_id: true, item_name: true, unit: true, q0: true, cap: true, q1_point: true, c_i: true },
};

const PROJECTS_FIXTURE = {
  status: 'PASS',
  projects: [{ id: 'p-1', uuid: 'p-1', name: '测试项目', stage: '投标', bid_amount: 1000000 }],
};

function defaultRoutes() {
  return {
    '/api/project/overview/list': { json: PROJECTS_FIXTURE },
    '/api/quote/optimize': { json: RESULT_FIXTURE },
    '/api/quote/preview': { json: PREVIEW_FIXTURE },
    '/api/group/list': { json: { status: 'PASS', groups: [] } },
  };
}

async function waitFor(pred, ticks = 60) {
  for (let i = 0; i < ticks; i += 1) {
    if (pred()) return true;
    await settle(0);
  }
  return false;
}

/** 起一个报价页：桩好 fetch、加载即落在报价页、等初始化尾部与关联项目下拉就绪。 */
async function bootQuotePage(routes = defaultRoutes()) {
  const calls = [];
  const stub = makeFetchStub(routes, calls);
  // hash 在**加载时**就带上：加载后再改 location.hash 会让 jsdom 排入额外的
  // hashchange 任务，它们在用例点击之后才跑 selectModule → closeOverlays()，
  // 把刚打开的弹层关掉（症状与「弹层打不开」无法区分）。
  const loaded = loadPage('index.html', { fetchStub: stub, hash: '#quote' });
  const { window } = loaded;
  // 初始化尾部（含被 setTimeout 延后的初始模块选择）会调用 closeOverlays()，
  // 并把 activeGroup/dashActive/lastResult 清空——交互用例动手前必须等它结束。
  assert.ok(await waitForInit(window), '初始化尾部未在预期轮次内落定');
  await waitFor(() => window.document.querySelector('#projectId').options.length > 1);
  return { ...loaded, calls };
}

function selectProject(window, value = 'p-1') {
  const sel = window.document.querySelector('#projectId');
  sel.value = value;
  sel.dispatchEvent(new window.Event('change', { bubbles: true }));
}

/** 走完整链路的前半：选项目 + 上传两份清单 + 点算，等到**结果态真正建立**。 */
async function runToResult(window) {
  const doc = window.document;
  selectProject(window);
  await settle(0);
  setInputFiles(window, 'capFile', 'cap.xlsx');
  setInputFiles(window, 'costFile', 'cost.xlsx');
  doc.querySelector('#calculateBtn').click();
  // 不能只等「optimize 请求已发出」：请求发出后还要经历 响应解析 → renderResult →
  // setDashboardVisible(true) 才进入结果态。以可观察标志为准（主 CTA 由置灰转可点）。
  return waitFor(() => doc.querySelector('#dockCalcBtn').disabled === false);
}

// ------------------------------------------------------------------ R5

test('R5 焦点陷阱与模态状态一致：关「没开的」弹层不得弹掉别人那一项', async () => {
  const { window, errors } = await bootQuotePage();
  const doc = window.document;

  doc.querySelector('#diffDrawerBtn').click();
  await settle(0);
  const hub = doc.querySelector('#planHub');
  assert.ok(hub.classList.contains('open'), '方案中心应已打开');
  assert.equal(doc.body.getAttribute('tabindex'), '-1',
    '打开模态应锁背景（body[tabindex=-1]），这是焦点陷阱激活的可观察标志');

  // 切项目：onGlobalProjectChange 会调用 closeCompareModal()，但对比弹层并未打开。
  selectProject(window, '');
  await waitFor(() => doc.querySelector('#planHub').classList.contains('open') === false, 5);
  await settle(0);

  assert.ok(hub.classList.contains('open'), '方案中心应当仍然开着（切项目不关它）');
  assert.equal(doc.body.getAttribute('tabindex'), '-1',
    'R5：仍有模态打开 ⇒ 焦点陷阱必须仍激活。'
    + '关闭一个未打开的弹层时弹栈（releaseTrap 无条件 pop），会把别人压在栈里的项弹掉，'
    + '于是开着的方案中心失去 Tab 陷阱、body 也提前解锁。');

  // 真正关闭后必须解锁：防止「永不弹栈」式的过度修复。
  doc.querySelector('#planHubCloseBtn').click();
  await settle(0);
  assert.equal(hub.classList.contains('open'), false, '应已关闭');
  assert.equal(doc.body.getAttribute('tabindex'), null,
    '关闭最后一个模态后必须移除 body[tabindex]');
  assert.deepEqual(errors, []);
  window.close();
});

// ------------------------------------------------------------------ R7

test('R7 预览后「导出」不得仍指向上一轮结果', async () => {
  const { window, errors, calls } = await bootQuotePage();
  const doc = window.document;

  assert.ok(await runToResult(window), '点算后应进入结果态（主 CTA 可点）');
  assert.ok(calls.some((c) => c.url.includes('/api/quote/optimize')), '应已发出 optimize 请求');
  assert.equal(doc.querySelector('#dockExportBtn').disabled, false,
    '有 excel_download_url 时导出应可点（先确认结果态真的建立了）');

  doc.querySelector('#previewBtn').click();
  assert.ok(await waitFor(() => calls.some((c) => c.url.includes('/api/quote/preview'))),
    '应已发出 preview 请求');
  // 等右栏真的回到空态（主 CTA 重新置灰），再断言导出——否则断言会跑在渲染之前
  assert.ok(await waitFor(() => doc.querySelector('#dockCalcBtn').disabled === true),
    '预览后主 CTA 应回到置灰（空态）');

  assert.equal(doc.querySelector('#dockExportBtn').disabled, true,
    'R7：预览后右栏已无结果 ⇒ 导出必须一并置灰；'
    + '否则「重算」点不动而「导出」仍可点，导出的还是上一轮结果。');
  assert.deepEqual(errors, []);
  window.close();
});

// ------------------------------------------------------------------ R8

test('R8 目标总报价留空不得被占位默认值兜成 0.00 提交', async () => {
  const { window, errors, calls } = await bootQuotePage();
  const doc = window.document;

  selectProject(window);
  await settle(0);
  setInputFiles(window, 'capFile', 'cap.xlsx');
  setInputFiles(window, 'costFile', 'cost.xlsx');

  const el = doc.querySelector('#targetTotal');
  el.value = '';
  assert.equal(el.placeholder, '0.00',
    '本判据的前提：#targetTotal 的占位默认值是 0.00（numVal 会回落到它）');

  assert.equal(window.validateParams(), false,
    'R8：目标总报价为空必须被提交前校验拦住（它是必填项，后端 Form(...) 且校验 > 0）');
  assert.ok(el.classList.contains('invalid'), '应给输入框加错误态');
  assert.equal(el.getAttribute('aria-invalid'), 'true');
  assert.match(doc.querySelector('#toastStack').textContent, /目标总报价/,
    '就地给出可行动的提示，而不是让后端返回一次「必填项」错误');

  doc.querySelector('#calculateBtn').click();
  assert.ok(await waitFor(() => doc.querySelector('#toastStack').textContent.length > 0, 10));
  await settle(0);
  assert.equal(calls.some((c) => c.url.includes('/api/quote/optimize')), false,
    'R8：空输入不得静默补 0.00 发出去；应在前端就地拦住');
  assert.deepEqual(errors, []);
  window.close();
});
