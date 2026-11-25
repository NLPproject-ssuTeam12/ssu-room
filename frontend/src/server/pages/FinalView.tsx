// 조교: 확정·내보내기 (서버 POST /finalize, GET /export.xlsx)
import { EXPORT_URL, api } from '../../api/client'
import type { FinalizeResult } from '../../api/types'
import { Chip } from '../../components/common'
import { askConfirm, toast } from '../../ui'
import type { ServerData } from '../data'
import { groupCoord } from '../coord'
import { COORD_STATE_LABEL, countStatus } from '../timetable'
import { useRun } from '../useRun'
import { sectionTitle } from '../wish'

function FinalizeCard({ data }: { data: ServerData }) {
  const r = useRun()
  const g = groupCoord(data.coord)
  const open = [...g.todo, ...g.waiting]
  const go = async () => {
    const out = await r.run<FinalizeResult>(() => api.finalize())
    if (out) toast(`시간표를 확정했습니다${out.unresolved.length ? ` · 임시 자리 ${out.unresolved.length}개` : ''}`)
  }
  const onClick = () => askConfirm({
    title: '시간표를 확정할까요?',
    body: open.length
      ? `아직 끝나지 않은 조율 안건 ${open.length}개는 지금 임시 자리 그대로 확정됩니다.\n확정하면 더 이상 조율·옮기기를 할 수 없습니다 (설정의 처음부터 다시로만 되돌릴 수 있음).`
      : '모든 조율 안건이 끝났습니다.\n확정하면 더 이상 조율·옮기기를 할 수 없습니다 (설정의 처음부터 다시로만 되돌릴 수 있음).',
    ok: '확정',
  }, () => { void go() })
  return (
    <div className="card">
      <h2>시간표 확정</h2>
      {open.length > 0 ? (
        <>
          <p className="small"><Chip k="warn">끝나지 않은 안건 {open.length}개</Chip> 확정하면 지금 자리(임시 배치) 그대로 들어갑니다.</p>
          <ul className="small">
            {open.map((c) => <li key={c.section_id}>{c.name ?? c.section_id} · {c.professor ?? '담당 미정'} · {COORD_STATE_LABEL[c.state] ?? c.state}</li>)}
          </ul>
        </>
      ) : <p className="small"><Chip k="good">모든 조율 안건이 끝났습니다</Chip></p>}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn primary" disabled={r.busy} onClick={onClick}>{r.busy ? '확정하는 중…' : '시간표 확정'}</button>
        <span className="small muted">확정한 뒤에 엑셀로 내보낼 수 있습니다.</span>
      </div>
      {r.error && <p className="note" role="alert" style={{ background: 'var(--bad-soft)', marginTop: 8 }}>{r.error}</p>}
    </div>
  )
}

function ExportCard({ data }: { data: ServerData }) {
  const tt = data.timetable
  const bySection = new Map(data.sections.map((s) => [s.id, s]))
  const temp = tt ? tt.assignments.filter((a) => a.status === 'COORD') : []
  const n = tt ? countStatus(tt.assignments) : null
  return (
    <div className="card">
      <h2>확정한 시간표</h2>
      {n && (
        <div className="row" style={{ marginBottom: 10 }}>
          <Chip k="good">배정 {n.DONE}개</Chip>
          <Chip>직접 배정 {n.MANUAL}개</Chip>
          {n.COORD > 0 && <Chip k="warn">임시 자리로 확정 {n.COORD}개</Chip>}
        </div>
      )}
      {temp.length > 0 && (
        <ul className="small">
          {temp.map((a) => {
            const s = bySection.get(a.section_id)
            return <li key={a.section_id}>{s ? sectionTitle(s) : a.section_id} · {s?.professor ?? '담당 미정'}{a.reason ? ` · ${a.reason}` : ''}</li>
          })}
        </ul>
      )}
      <div className="row" style={{ marginTop: 10 }}>
        <a className="btn primary" href={EXPORT_URL} download="ssuroom_timetable.xlsx">엑셀 내려받기</a>
        <span className="small muted">가명 데이터이고, 학교 시스템의 실제 양식이 아닌 제안 양식입니다.</span>
      </div>
    </div>
  )
}

export default function FinalView({ data }: { data: ServerData }) {
  const stage = data.health.stage
  return (
    <>
      <h1 tabIndex={-1}>확정·내보내기</h1>
      {stage === 'COLLECT' && <div className="card">아직 초안이 없습니다. 희망 확인에서 초안을 먼저 만드세요.</div>}
      {(stage === 'DRAFT' || stage === 'ROUND') && (
        <>
          <p className="lead">{stage === 'ROUND' ? `${data.health.round_no}차 조율 중입니다.` : '초안 단계입니다.'} 조율을 마치면 시간표를 확정합니다.</p>
          <FinalizeCard data={data} />
        </>
      )}
      {stage === 'FINAL' && (
        <>
          <p className="lead">시간표를 확정했습니다. 엑셀로 내려받을 수 있습니다.</p>
          <ExportCard data={data} />
        </>
      )}
    </>
  )
}
