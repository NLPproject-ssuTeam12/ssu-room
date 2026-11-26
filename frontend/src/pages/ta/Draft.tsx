import { S, altLabel, full, genAlts, openMsgs, publish, violations, wishLabel } from '../../mock/demo'
import { act } from '../../store'
import { askConfirm, toast } from '../../ui'
import { Chip, Stub } from '../../components/common'
import PeekBtns from '../../components/PeekBtns'
import Timetable from '../../components/Timetable'

const LEAD: Record<string, string> = {
  draft: '자동으로 만든 초안입니다. 밀린 분반은 대안 A에 임시로 두었습니다.',
  final: '모든 교수님이 확정한 시간표입니다.',
}

function OpenCourse({ c }: { c: any }) {
  const m = S.msgs.filter((x: any) => x.cid === c.id).slice(-1)[0]
  const alts = m ? m.alts : genAlts(c, S.conds[c.id] || {})
  return (
    <div className="card" style={{ marginBottom: 10, padding: 14 }}>
      <b>{full(c)}</b> <span className="muted small">{c.prof} 교수</span>
      <div className="small" style={{ margin: '6px 0' }}>희망: {wishLabel(c)}</div>
      <div className="small muted">{S.reason[c.id] || ''}</div>
      <div className="lbl">대안</div>
      {alts.map((a: any) => <div key={a.k} className="small">{a.k} · {altLabel(a)}</div>)}
      {m && openMsgs().includes(m) && <PeekBtns m={m} />}
    </div>
  )
}

export default function Draft() {
  if (S.stage === 'collect') {
    return (
      <>
        <h1 tabIndex={-1}>시간표</h1>
        <div className="card">아직 초안이 없습니다. 희망을 확인한 뒤 초안을 만듭니다.</div>
      </>
    )
  }
  const open = S.courses.filter((c: any) => S.status[c.id] === 'open')
  const v = violations()
  const lead = LEAD[S.stage] ?? (S.stage === 'round' ? `${S.round}차 조율 중인 시간표입니다.` : '조율이 끝난 시간표입니다. 교수님 확정을 받으면 끝납니다.')
  const onPublish = () =>
    askConfirm(
      {
        title: '초안을 공개할까요?',
        body: '모든 교수님께 초안을 공개하고, 밀린 분반의 조율 메시지 초안을 만듭니다.\n메시지는 조율 화면에서 확인하고 [보내기]를 눌러야 갑니다.',
        ok: '공개',
      },
      () => {
        act(() => { publish(); S.view = 'coord' })
        toast('초안을 공개했습니다')
      },
    )
  return (
    <>
      <h1 tabIndex={-1}>시간표</h1>
      <p className="lead">
        <Stub text="배정 엔진 흉내" tip="실제는 OR-Tools CP-SAT 배정 엔진입니다. 시연 화면은 우선순위 순서 배정으로 흉내 냅니다." /> {lead}
      </p>
      <div className="row" style={{ marginBottom: 12 }}>
        <Chip k={v ? 'bad' : 'good'}>하드 규칙 위반 {v}건</Chip>
        <Chip k="warn">조율 중 {open.length}개</Chip>
        {S.lastChanged.length > 0 && <Chip k="good">방금 바뀐 분반 {S.lastChanged.length}개</Chip>}
      </div>
      <div className="card"><Timetable /></div>
      {open.length > 0 && (
        <>
          <h2>조율이 필요한 분반 <span className="small muted">(조교만 보는 이유 포함)</span></h2>
          {open.map((c: any) => <OpenCourse key={c.id} c={c} />)}
        </>
      )}
      {S.stage === 'draft' && (
        <div className="card">
          <div className="row">
            <button className="btn primary" onClick={onPublish}>초안 공개 + 1차 조율 메시지 보내기</button>
            <span className="small muted">초안은 모든 교수에게 공개하고, 메시지는 밀린 분반 교수에게만 보냅니다.</span>
          </div>
        </div>
      )}
    </>
  )
}
