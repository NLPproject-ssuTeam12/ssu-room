import { S, peekInfo, violations } from '../mock/demo'
import { act } from '../store'
import Timetable from '../components/Timetable'

const STAGE_LABEL: Record<string, string> = { draft: '초안', final: '확정' }

/** 현재 시간표: AI 도우미처럼 어느 화면에서나 오른쪽에 열어 두고 본다 (둘 중 하나만 열림) */
export default function TimetablePanel({ onClose }: { onClose: () => void }) {
  const pk = peekInfo()
  const stage = S.stage === 'round' ? `${S.round}차 조율 중` : STAGE_LABEL[S.stage] ?? '조율 끝'
  return (
    <aside className="ttpanel" role="complementary" aria-labelledby="ttd-t">
      <div className="bph">
        <b id="ttd-t">현재 시간표</b>
        <span className="small muted">{stage} · 하드 규칙 위반 {violations()}건</span>
        {pk && <button className="btn small" onClick={() => act(() => { S.peek = null })}>미리 보기 끄기</button>}
        <div className="spacer" />
        <button className="btn small" onClick={() => act(() => { S.view = 'draft' })}>시간표 화면</button>
        <button className="btn small" aria-label="현재 시간표 닫기" onClick={onClose}>닫기</button>
      </div>
      <div className="ttbody"><Timetable drawer /></div>
    </aside>
  )
}
