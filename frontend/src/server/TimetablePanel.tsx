// 현재 시간표: 어느 조교 화면에서나 오른쪽에 열어 두고 본다 (서버 GET /timetable)
import type { ServerData } from './data'
import TimetableGrid from './TimetableGrid'

const STAGE_LABEL: Record<string, string> = { DRAFT: '초안', FINAL: '확정' }

interface Props {
  data: ServerData
  onClose: () => void
  onOpenPage: () => void
}

export default function TimetablePanel({ data, onClose, onOpenPage }: Props) {
  const tt = data.timetable
  if (!tt) return null
  const stage = tt.stage === 'ROUND' ? `${tt.round_no}차 조율 중` : STAGE_LABEL[tt.stage] ?? tt.stage
  return (
    <aside className="ttpanel" role="complementary" aria-labelledby="ttd-t">
      <div className="bph">
        <b id="ttd-t">현재 시간표</b>
        <span className="small muted">{stage} · 조율 대상 {data.coord.length}개</span>
        <div className="spacer" />
        <button className="btn small" onClick={onOpenPage}>시간표 화면</button>
        <button className="btn small" aria-label="현재 시간표 닫기" onClick={onClose}>닫기</button>
      </div>
      <div className="ttbody"><TimetableGrid assignments={tt.assignments} sections={data.sections} drawer /></div>
    </aside>
  )
}
