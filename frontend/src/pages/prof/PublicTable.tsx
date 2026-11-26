import { ACT, S, altLabel, full } from '../../mock/demo'
import { act } from '../../store'
import { Chip } from '../../components/common'
import Timetable from '../../components/Timetable'

export default function PublicTable() {
  if (S.stage === 'collect' || S.stage === 'draft') {
    return (
      <>
        <h1 tabIndex={-1}>공개 시간표</h1>
        <div className="card">조교가 초안을 확인하고 있습니다. 공개되면 여기서 볼 수 있습니다.</div>
      </>
    )
  }
  const mine = ACT().filter((c: any) => c.prof === S.prof && S.assign[c.id])
  return (
    <>
      <h1 tabIndex={-1}>공개 시간표</h1>
      <p className="lead">모든 교수님께 같은 시간표가 공개됩니다.</p>
      <div className="row" style={{ marginBottom: 12 }}>
        <div className="seg" role="group" aria-label="보기">
          {([[false, '전체 보기'], [true, '내 강의만']] as [boolean, string][]).map(([v, t]) => (
            <button key={t} type="button" className={S.mineOnly === v ? 'on' : ''} aria-pressed={S.mineOnly === v}
              onClick={() => act(() => { S.mineOnly = v })}>{t}</button>
          ))}
        </div>
      </div>
      {S.mineOnly && (
        <div className="card">
          <h2>{S.prof} 교수님 강의 {mine.length}개</h2>
          {mine.length ? mine.map((c: any) => (
            <div key={c.id} className="small" style={{ marginBottom: 4 }}>
              <b>{full(c)}</b> · {altLabel(S.assign[c.id])} {S.status[c.id] === 'open' && <Chip k="warn">조율 중</Chip>}
            </div>
          )) : <div className="small muted">배정된 강의가 없습니다.</div>}
        </div>
      )}
      <div className="card"><Timetable prof={S.prof} mine={S.mineOnly} /></div>
    </>
  )
}
