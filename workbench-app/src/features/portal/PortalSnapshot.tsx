import { getItems } from './portalData';

/**
 * 舞台下方的「工程快照」段（P1 迁移：由 portal-view.js buildSnapshot 迁入 React）。
 * 数据全部取自 PORTAL_DATA（本机演示数据，不造假）。
 */
export function PortalSnapshot({ onGoBiz, onGoTodos }: { onGoBiz: () => void; onGoTodos: () => void }) {
  const projects = getItems('biz', 'projects');
  const todos = [...getItems('todos', 'p0'), ...getItems('todos', 'regular')];

  const atBid = projects.filter((p) => p.stage === '投标').length;
  const building = projects.filter((p) => p.stage === '中标在建').length;
  const totalBid = projects.reduce((s, p) => s + (Number(String(p.bidAmount).replace(/,/g, '')) || 0), 0);
  const won = projects.filter((p) => p.stage === '中标在建' || p.stage === '已竣工').length;
  const winRate = projects.length ? Math.round((won / projects.length) * 100) : 0;

  const kpis: [string, string, number | string][] = [
    ['在库项目', 'Projects', projects.length],
    ['在投标', 'Bidding', atBid],
    ['在建中', 'In progress', building],
    ['中标率', 'Win rate', `${winRate}%`],
  ];

  const maxBid = Math.max(1, ...projects.map((p) => Number(String(p.bidAmount).replace(/,/g, '')) || 0));

  return (
    <section className="portal-snapshot">
      <header className="snap-head">
        <p className="hero-eyebrow">SNAPSHOT <span>工程快照</span></p>
        <p className="snap-source">数据源自本机工作台 · 演示用途 <em>Local data · demo</em></p>
      </header>

      <div className="snap-kpi-band">
        {kpis.map((k) => (
          <div key={k[0]}><span>{k[0]} <em>{k[1]}</em></span><strong>{k[2]}</strong></div>
        ))}
      </div>

      <div className="snap-grid">
        <section className="snap-card snap-perf">
          <header>
            <h2>在库项目表现 <em>Projects</em></h2>
            <button type="button" className="pixel-pill-btn" onClick={onGoBiz}>进入经营 →</button>
          </header>
          <table>
            <thead>
              <tr><th>项目 <em>Project</em></th><th>阶段 <em>Stage</em></th><th>报价 <em>Bid</em></th><th>进度 <em>Progress</em></th></tr>
            </thead>
            <tbody>
              {projects.map((p) => {
                const amt = Number(String(p.bidAmount).replace(/,/g, '')) || 0;
                const tagCls = p.stage === '投标' ? 'tag-bid' : p.stage === '中标在建' ? 'tag-build' : 'tag-done';
                return (
                  <tr key={p.id}>
                    <td>
                      <span className="t-title">{p.title}</span>
                      <span className="t-bar"><i style={{ width: `${Math.round((amt / maxBid) * 100)}%` }} /></span>
                    </td>
                    <td><span className={`stage-tag ${tagCls}`}>{p.stage}</span></td>
                    <td className="t-num">{p.bidAmount}</td>
                    <td className="t-num">{p.progress}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="snap-foot">共 {projects.length} 个在库项目 · 累计报价额 {totalBid.toLocaleString('zh-CN')} 元 <em>Total bid amount</em></p>
        </section>

        <section className="snap-card snap-plan">
          <header><h2>近期待办 <em>Up next</em></h2></header>
          <ul className="snap-todo-list">
            {todos.length === 0 && <li className="snap-todo">暂无待推进事项</li>}
            {todos.slice(0, 5).map((t) => (
              <li className="snap-todo" key={t.id}>
                <span className="snap-dot" />{t.title}
                <em>{(t.taskDetail?.deadline as string) || ''}</em>
              </li>
            ))}
          </ul>
          <button type="button" className="pixel-btn-action" onClick={onGoTodos}>查看全部待办 →</button>
        </section>
      </div>
    </section>
  );
}
