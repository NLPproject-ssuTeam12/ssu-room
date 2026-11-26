// 조교: 시간표 (서버 GET /timetable, GET /coord) + 초안 공개 (POST /rounds/next)
import { Chip } from '../../components/common'
import type { ServerData } from '../data'
import CoordSummary from '../CoordSummary'
import RoundButton from '../RoundButton'
import TimetableGrid from '../TimetableGrid'
import { countStatus } from '../timetable'

const STAGE_LEAD: Record<string, string> = {
  DRAFT: '배정 엔진(CP-SAT)이 만든 초안입니다. 조율 대상은 임시 자리에 두었습니다.',
  ROUND: '조율 중인 시간표입니다.',
  FINAL: '확정한 시간표입니다.',
}

interface Props {
  data: ServerData
  onGoWishes: () => void
  onGoCoord: () => void
}

export default function DraftView({ data, onGoWishes, onGoCoord }: Props) {
  const tt = data.timetable
  if (!tt) {
    return (
      <>
        <h1 tabIndex={-1}>시간표</h1>
        <div className="card">
          아직 초안이 없습니다. 희망을 확인한 뒤 초안을 만듭니다.{' '}
          <button className="btn small" onClick={onGoWishes}>희망 확인으로</button>
        </div>
      </>
    )
  }
  const n = countStatus(tt.assignments)
  const bySection = new Map(data.sections.map((s) => [s.id, s]))
  const stageLead = tt.stage === 'ROUND' ? `${tt.round_no}차 ${STAGE_LEAD.ROUND}` : STAGE_LEAD[tt.stage] ?? ''
  return (
    <>
      <h1 tabIndex={-1}>시간표</h1>
      <p className="lead">{stageLead}</p>
      <div className="row" style={{ marginBottom: 12 }}>
        <Chip k="good">배정 {n.DONE}개</Chip>
        <Chip k="warn">조율 대상 {data.coord.length}개</Chip>
        <Chip>직접 배정 {n.MANUAL}개</Chip>
      </div>
      <div className="card"><TimetableGrid assignments={tt.assignments} sections={data.sections} /></div>
      {data.coord.length > 0 && (
        <>
          <h2>조율이 필요한 분반 <span className="small muted">(조교만 보는 이유 포함)</span></h2>
          {tt.stage !== 'DRAFT' && <p className="small muted">답장 처리는 <button className="btn small" onClick={onGoCoord}>조율 화면</button>에서 합니다.</p>}
          {data.coord.map((c) => <CoordSummary key={c.section_id} c={c} section={bySection.get(c.section_id)} notes={data.notes[c.section_id]} />)}
        </>
      )}
      {tt.stage === 'DRAFT' && <RoundButton data={data} onDone={onGoCoord} />}
    </>
  )
}
