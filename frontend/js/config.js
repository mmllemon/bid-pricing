/* ===== 全站 origin/基址单一事实源（F-P0-4）=====
 * 此前 app.js（WB_ORIGIN）、agent-panel.js（AGENT_BASE）、tool-well.js（API_BASE）
 * 各自按主机名推导——三处逻辑同义但无共享，出问题要改三处。本文件是唯一推导处，
 * 其余脚本一律引用 window.__BID.host/port/probe，不再各自拼串。
 * 加载顺序：escape.js 之后、其余业务脚本之前（各页面 script 顺序见 index.html 注释）。
 */
(function () {
  'use strict';
  if (window.__BID) return; // 幂等
  const proto = location.protocol.startsWith('http') ? location.protocol : 'http:';
  const host = location.hostname || '127.0.0.1';
  const wbHost = window.__WORKBENCH_HOST__ || host;
  window.__BID = {
    proto: proto,
    host: host,
    // 后端 API（:8000）：window.__API_BASE__ 显式覆盖优先（部署钩子）
    apiBase: window.__API_BASE__ || (proto + '//' + host + ':8000'),
    // 个人工作台（:3456）：window.__WORKBENCH_ORIGIN__ 显式覆盖优先
    wbOrigin: window.__WORKBENCH_ORIGIN__ || (proto + '//' + wbHost + ':3456'),
    // agent 边车挂在工作台进程 /agent 前缀下（P0 架构收敛后无独立端口）
    agentBase: function () { return window.__BID.wbOrigin + '/agent'; },
  };
})();
