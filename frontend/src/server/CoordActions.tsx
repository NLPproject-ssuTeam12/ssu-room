// 조교 조율: 안건 상태마다 누를 수 있는 버튼 (서버 /coord/{id}/message·hold·ack·decide·manual)
import { useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '../api/client'
import { DAYS, STARTS } from '../api/types'
import type { AltKey, CoordItem, MessageRecord, Room } from '../api/types'
import { Chip } from '../components/common'
import { askConfirm, toast } from '../ui'
import { ACTION_LABEL, PARSE_KIND_CLASS, condText, manualError, rowsToMeetings } from './coord'
import { addNote } from './data'
import type { ManualRow } from './coord'
import { useRun } from './useRun'
import type { Runner } from './useRun'

const ErrorNote = ({ text }: { text: string }) =>
  text ? <p className="note" role="alert" style={{ background: 'var(--bad-soft)', marginTop: 8 }}>{text}</p> : null

function Bar({ children, r }: { children: ReactNode; r: Runner }) {
  return (
    <>
      <div className="row" style={{ marginTop: 10 }}>{children}</div>
      <ErrorNote text={r.error} />
    </>
  )
}

/** 보내기 전 (OPEN): 메시지를 쓰고 검사해서 보낸다. 검사에 걸리면 보내지 않고 이유를 보여 준다 */
function OpenActions({ c }: { c: CoordItem }) {
  const r = useRun()
  const [issues, setIssues] = useState<string[]>([])
  const send = async () => {
    const rec = await r.run<MessageRecord>(() => api.sendMessage(c.section_id))
    setIssues(rec && !rec.sent ? rec.issues : [])
  }
  return (
    <Bar r={r}>
      <button className="btn primary small" disabled={r.busy || !c.alternatives.length} onClick={() => void send()}>
        {r.busy ? '보내는 중…' : '조율 메시지 보내기'}
      </button>
      {!c.alternatives.length && <span className="small muted">대안이 없어 보낼 수 없습니다.</span>}
      {issues.length > 0 && <span className="small" style={{ color: 'var(--bad)' }}>검사에 걸려 보내지 않았습니다: {issues.join(', ')}</span>}
    </Bar>
  )
}

/** 일부 어긋남 (HOLD): 보낼지 조교가 정한다 */
function HoldActions({ c }: { c: CoordItem }) {
  const r = useRun()
  // 보내기 대기를 푼 뒤 메시지가 실패하면 안건은 '보내기 전'이 된다. 카드가 바뀌어도 이유가 남도록 알림으로 남긴다
  const send = () => r.run(async () => {
    await api.hold(c.section_id, true)
    try {
      return await api.sendMessage(c.section_id)
    } catch (e: unknown) {
      addNote(c.section_id, `메시지를 보내지 못했습니다: ${e instanceof Error ? e.message : '알 수 없는 오류'}. [조율 메시지 보내기]로 다시 보내 주세요.`)
      throw e
    }
  }, '조율 메시지를 보냈습니다')
  const keep = () => askConfirm(
    { title: '보내지 않을까요?', body: '이 분반은 지금 자리 그대로 둡니다 (지금 자리 유지).', ok: '보내지 않음' },
    () => { void r.run(() => api.hold(c.section_id, false), '지금 자리로 두었습니다') },
  )
  return (
    <Bar r={r}>
      <button className="btn primary small" disabled={r.busy} onClick={() => void send()}>조율 메시지 보내기</button>
      <button className="btn small" disabled={r.busy} onClick={keep}>보내지 않음 (지금 자리 유지)</button>
    </Bar>
  )
}

/** 대안 없음 (NO_OPTION): 확인하면 따로 연락으로 넘어간다 */
function NoOptionActions({ c }: { c: CoordItem }) {
  const r = useRun()
  return (
    <Bar r={r}>
      <button className="btn primary small" disabled={r.busy} onClick={() => void r.run(() => api.ack(c.section_id), '따로 연락으로 넘겼습니다')}>
        확인 → 따로 연락
      </button>
      <span className="small muted">교수님과 직접 정한 뒤 자리를 넣습니다.</span>
    </Bar>
  )
}

/** 처리안 확인 (PROPOSED): [확인]·[수정]·[현재대로 유지]·[따로 연락] */
function ProposedActions({ c }: { c: CoordItem }) {
  const r = useRun()
  const [editing, setEditing] = useState(false)
  const [choice, setChoice] = useState<AltKey>(c.alternatives[0]?.key ?? 'A')
  const [reason, setReason] = useState('')
  const p = c.proposal
  const parse = c.last_parse
  const canConfirm = !!p && p.action !== 'decide'
  const decide = (action: 'confirm' | 'keep', ok: string) => r.run(() => api.decide(c.section_id, { action }), ok)
  const offline = () => askConfirm(
    { title: '따로 연락할까요?', body: '시스템 밖에서 교수님과 정한 뒤, 정한 자리를 직접 넣습니다.', ok: '따로 연락', reason: true, placeholder: '사유 (예: 전화로 정하기로 함)' },
    (why) => { void r.run(() => api.decide(c.section_id, { action: 'offline', reason: why }), '따로 연락으로 넘겼습니다') },
  )
  return (
    <>
      {parse && (
        <div className="small" style={{ marginTop: 8 }}>
          <b>답장 해석</b> <Chip k={PARSE_KIND_CLASS[parse.kind] ?? ''}>{parse.kind}</Chip>
          {parse.keep && <Chip>지금 자리 그대로</Chip>}
          {parse.picks.length > 0 && <Chip>고른 안 {parse.picks.join(', ')}{parse.ordered ? ' (순서 있음)' : ''}</Chip>}
          {condText(parse.conditions) && <Chip k="warn">조건 {condText(parse.conditions)}</Chip>}
          {parse.note && <div className="muted">조교 확인: {parse.note}</div>}
        </div>
      )}
      {p && (
        <div className="note" style={{ marginTop: 8 }}>
          <b>처리안 · {ACTION_LABEL[p.action] ?? p.action}</b>
          <div>{p.text}</div>
          {p.checks.length > 0 && <div className="small muted">{p.checks.map((k) => `${k.key}: ${k.ok ? '되는 안' : '안 되는 안'} (${k.why})`).join(' · ')}</div>}
        </div>
      )}
      <Bar r={r}>
        <button className="btn primary small" disabled={r.busy || !canConfirm} onClick={() => void decide('confirm', '처리안대로 했습니다')}>확인</button>
        <button className="btn small" disabled={r.busy || !c.alternatives.length} onClick={() => setEditing((v) => !v)}>수정</button>
        <button className="btn small" disabled={r.busy} onClick={() => void decide('keep', '지금 자리로 두었습니다')}>현재대로 유지</button>
        <button className="btn small" disabled={r.busy} onClick={offline}>따로 연락</button>
      </Bar>
      {editing && (
        <div className="row" style={{ marginTop: 8 }}>
          <select aria-label="고를 안" value={choice} onChange={(e) => setChoice(e.target.value as AltKey)}>
            {c.alternatives.map((a) => <option key={a.key} value={a.key}>{a.key}안</option>)}
          </select>
          <input aria-label="수정 사유" placeholder="사유 (필수)" value={reason} onChange={(e) => setReason(e.target.value)} style={{ minWidth: 220 }} />
          <button className="btn small primary" disabled={r.busy || !reason.trim()}
            onClick={() => void r.run(() => api.decide(c.section_id, { action: 'edit', choice, reason: reason.trim() }), `${choice}안으로 옮겼습니다`)}>
            {choice}안으로 정하기
          </button>
        </div>
      )}
    </>
  )
}

const emptyRow = (room: string): ManualRow => ({ day: 0, start: STARTS[0], slots: 1, room })

/** 따로 연락 (OFFLINE): 교수님과 정한 자리를 조교가 직접 넣는다. 규칙 위반은 막지 않고 경고만 */
function ManualForm({ c, rooms }: { c: CoordItem; rooms: Room[] }) {
  const r = useRun()
  const firstRoom = rooms[0]?.id ?? ''
  const [rows, setRows] = useState<ManualRow[]>([emptyRow(firstRoom), { ...emptyRow(firstRoom), day: 2 }])
  const [reason, setReason] = useState('')
  const err = manualError(rows)
  const setRow = (i: number, patch: Partial<ManualRow>) => setRows((xs) => xs.map((x, k) => (k === i ? { ...x, ...patch } : x)))
  const save = async () => {
    // 규칙 위반은 막지 않고 경고만 온다. 안건이 '정해짐'으로 바뀌어도 보이도록 알림으로 남긴다
    const out = await r.run(() => api.manual(c.section_id, { meetings: rowsToMeetings(rows), reason: reason.trim() || undefined }))
    if (!out) return
    const warnings = out.warnings ?? []
    warnings.forEach((w) => addNote(c.section_id, `직접 배치 규칙 경고 · ${w.rule}: ${w.detail}`))
    toast(warnings.length ? `자리를 넣었습니다 · 규칙 경고 ${warnings.length}건` : '자리를 넣었습니다')
  }
  return (
    <div style={{ marginTop: 10 }}>
      <div className="lbl">교수님과 정한 자리</div>
      {rows.map((row, i) => (
        <div key={i} className="row" style={{ marginBottom: 6 }}>
          <select aria-label={`수업 ${i + 1} 요일`} value={row.day} onChange={(e) => setRow(i, { day: Number(e.target.value) })}>
            {DAYS.map((d, k) => <option key={d} value={k}>{d}</option>)}
          </select>
          <select aria-label={`수업 ${i + 1} 시작`} value={row.start} onChange={(e) => setRow(i, { start: e.target.value })}>
            {STARTS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select aria-label={`수업 ${i + 1} 길이`} value={row.slots} onChange={(e) => setRow(i, { slots: Number(e.target.value) })}>
            <option value={1}>75분</option><option value={2}>연강 (2교시)</option>
          </select>
          <select aria-label={`수업 ${i + 1} 강의실`} value={row.room} onChange={(e) => setRow(i, { room: e.target.value })}>
            {rooms.map((x) => <option key={x.id} value={x.id}>{x.id}{x.is_lab ? ' (실습실)' : ''}</option>)}
          </select>
          {rows.length > 1 && <button className="btn small" onClick={() => setRows((xs) => xs.filter((_, k) => k !== i))}>빼기</button>}
        </div>
      ))}
      <div className="row">
        {rows.length < 2 && <button className="btn small" onClick={() => setRows((xs) => [...xs, emptyRow(firstRoom)])}>수업 더하기</button>}
        <input aria-label="직접 배치 사유" placeholder="사유 (선택)" value={reason} onChange={(e) => setReason(e.target.value)} style={{ minWidth: 200 }} />
        <button className="btn primary small" disabled={r.busy || !!err} onClick={() => void save()}>이 자리로 정하기</button>
        {err && <span className="small muted">{err}</span>}
      </div>
      <ErrorNote text={r.error} />
    </div>
  )
}

export default function CoordActions({ c, rooms }: { c: CoordItem; rooms: Room[] }) {
  switch (c.state) {
    case 'OPEN': return <OpenActions c={c} />
    case 'HOLD': return <HoldActions c={c} />
    case 'NO_OPTION': return <NoOptionActions c={c} />
    case 'PROPOSED': return <ProposedActions c={c} />
    case 'OFFLINE': return <ManualForm c={c} rooms={rooms} />
    default: return null
  }
}
