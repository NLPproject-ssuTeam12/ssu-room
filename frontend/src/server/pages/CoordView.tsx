// 조교: 조율 (서버 GET /coord + 안건별 처리, POST /rounds/next)
import type { CoordItem } from '../../api/types'
import { Chip } from '../../components/common'
import type { ServerData } from '../data'
import CoordActions from '../CoordActions'
import CoordSummary from '../CoordSummary'
import RoundButton from '../RoundButton'
import { groupCoord } from '../coord'

function Group({ title, note, items, data }: { title: string; note: string; items: CoordItem[]; data: ServerData }) {
  const bySection = new Map(data.sections.map((s) => [s.id, s]))
  if (!items.length) return null
  return (
    <>
      <h2>{title} <span className="small muted">{items.length}개 · {note}</span></h2>
      {items.map((c) => (
        <CoordSummary key={c.section_id} c={c} section={bySection.get(c.section_id)} notes={data.notes[c.section_id]}>
          {data.health.stage === 'ROUND' || data.health.stage === 'DRAFT' ? <CoordActions c={c} rooms={data.rooms} /> : null}
        </CoordSummary>
      ))}
    </>
  )
}

export default function CoordView({ data }: { data: ServerData }) {
  const { stage, round_no: round } = data.health
  if (stage === 'COLLECT') {
    return (
      <>
        <h1 tabIndex={-1}>조율</h1>
        <div className="card">아직 초안이 없습니다. 희망 확인에서 초안을 먼저 만드세요.</div>
      </>
    )
  }
  const g = groupCoord(data.coord)
  return (
    <>
      <h1 tabIndex={-1}>조율</h1>
      <p className="lead">
        {stage === 'DRAFT' ? '초안을 공개하면 1차 조율이 시작됩니다.' : stage === 'FINAL' ? '확정한 시간표의 조율 기록입니다.' : `${round}차 조율 중입니다.`}{' '}
        조교가 [확인]·[수정]·[현재대로 유지]를 누르기 전에는 시간표가 바뀌지 않습니다.
      </p>
      <div className="row" style={{ marginBottom: 12 }}>
        <Chip k={g.todo.length ? 'warn' : 'good'}>조교가 할 일 {g.todo.length}</Chip>
        <Chip>답장 대기 {g.waiting.length}</Chip>
        <Chip k="good">끝남 {g.done.length}</Chip>
      </div>
      {stage === 'FINAL' ? <div className="card small">시간표를 확정해서 더 이상 조율할 수 없습니다.</div> : <RoundButton data={data} />}
      <Group title="조교가 할 일" note="보내기·처리안 확인·직접 배치" items={g.todo} data={data} />
      <Group title="교수 답장 대기" note="교수님 화면에서 답장하면 처리안이 생깁니다" items={g.waiting} data={data} />
      {g.done.length > 0 && (
        <details className="card">
          <summary><b>끝난 안건 {g.done.length}개</b> <span className="small muted">다음 차수로·정해짐·지금 자리 유지</span></summary>
          <div style={{ marginTop: 10 }}>
            <Group title="끝난 안건" note="" items={g.done} data={data} />
          </div>
        </details>
      )}
    </>
  )
}
