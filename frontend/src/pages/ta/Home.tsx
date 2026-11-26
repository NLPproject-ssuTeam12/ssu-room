import { ACT, S, todo, violations } from '../../mock/demo'

export default function Home() {
  const flags = S.stage === 'collect' ? todo() : 0
  const open = Object.values(S.status).filter((s) => s === 'open').length
  const before = S.stage === 'collect'
  return (
    <>
      <h1 tabIndex={-1}>현황</h1>
      <p className="lead">2027-1학기 AI소프트웨어학부 편성 (가상 데이터 {S.courses.length}개 분반)</p>
      <div className="kpis">
        <div className="kpi">
          <div className="n">
            {ACT().length}
            <span className="small muted">/{S.courses.length}</span>
          </div>
          <div className="l">담당 정해진 분반</div>
        </div>
        <div className="kpi"><div className="n">{flags}</div><div className="l">조교가 확인할 것</div></div>
        <div className="kpi"><div className="n">{before ? '–' : open}</div><div className="l">조율 중인 분반</div></div>
        <div className="kpi"><div className="n">{before ? '–' : violations()}</div><div className="l">하드 규칙 위반</div></div>
      </div>
      <div className="card">
        <h2>기록</h2>
        <ul className="log small">
          {S.log.slice().reverse().map((l: any, i: number) => (
            <li key={S.log.length - i}>
              <b>{l.at}</b> · {l.t}
            </li>
          ))}
        </ul>
      </div>
    </>
  )
}
