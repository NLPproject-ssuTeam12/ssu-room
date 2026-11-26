// 교수: 조율 메시지와 답장 (서버 GET /coord, POST /coord/{id}/reply)
import { useState } from 'react'
import { api } from '../../api/client'
import type { CoordItem, ReplyChoice, Section } from '../../api/types'
import { Chip } from '../../components/common'
import type { ServerData } from '../data'
import { replyError, toggleChoice } from '../coord'
import { COORD_STATE_LABEL, altText } from '../timetable'
import { useRun } from '../useRun'
import { sectionTitle } from '../wish'

const STATUS_TEXT: Record<string, string> = {
  PROPOSED: '답장을 보냈습니다. 학과사무실이 확인하고 있습니다.',
  NEXT: '보내 주신 조건으로 다음 차수에 새 안을 드립니다.',
  RESOLVED: '시간이 정해졌습니다.',
  KEPT: '지금 자리 그대로 두었습니다.',
  OFFLINE: '학과사무실에서 따로 연락드립니다.',
}

function ReplyForm({ c }: { c: CoordItem }) {
  const r = useRun()
  const [choices, setChoices] = useState<ReplyChoice[]>([])
  const [text, setText] = useState('')
  const canKeep = !!c.current
  const err = replyError(choices, text, canKeep)
  const options: [ReplyChoice, string][] = [
    ...c.alternatives.map((a): [ReplyChoice, string] => [a.key, `${a.key}안 · ${altText(a)}`]),
    ...(canKeep ? [['KEEP', `지금 자리 그대로 · ${c.current}`] as [ReplyChoice, string]] : []),
    ['ETC', '기타 (모두 어렵거나 다른 시간이 필요함)'],
  ]
  const send = () => r.run(() => api.reply(c.section_id, choices, text.trim()), '답장을 보냈습니다')
  return (
    <div style={{ marginTop: 10 }}>
      <div className="lbl">가능한 것을 모두 골라 주세요</div>
      {options.map(([k, label]) => (
        <label key={k} className="small" style={{ display: 'block', marginBottom: 4 }}>
          <input type="checkbox" checked={choices.includes(k)} onChange={() => setChoices((xs) => toggleChoice(xs, k))} /> {label}
        </label>
      ))}
      <textarea aria-label="답장 내용" value={text} onChange={(e) => setText(e.target.value)}
        placeholder={choices.includes('ETC') ? '가능한 요일·시간을 적어 주세요 (예: 화요일 오전이면 됩니다)' : '덧붙일 말 (선택, 예: A가 더 좋습니다)'} />
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn primary" disabled={!!err || r.busy} onClick={() => void send()}>{r.busy ? '보내는 중…' : '답장 보내기'}</button>
        {err && <span className="small muted">{err}</span>}
      </div>
      {r.error && <p className="note" role="alert" style={{ background: 'var(--bad-soft)', marginTop: 8 }}>{r.error}</p>}
    </div>
  )
}

function MessageCard({ c, section, canReply }: { c: CoordItem; section: Section | undefined; canReply: boolean }) {
  return (
    <div className="card">
      <h2>{section ? sectionTitle(section) : (c.name ?? c.section_id)} <span className="small muted">{c.round_no}차 조율</span></h2>
      <Chip k={c.state === 'SENT' ? 'warn' : 'good'}>{c.state === 'SENT' ? '답장 필요' : COORD_STATE_LABEL[c.state] ?? c.state}</Chip>
      {c.message && <p className="small" style={{ whiteSpace: 'pre-wrap' }}>{c.message}</p>}
      {c.state === 'SENT' && canReply ? <ReplyForm c={c} />
        : <p className="small muted">{c.state === 'SENT' ? '조율이 끝나 답장을 받지 않습니다.' : STATUS_TEXT[c.state] ?? ''}</p>}
    </div>
  )
}

/** 교수에게 보이는 안건: 메시지를 받은 적이 있는 것만 (보내기 전·조교 선택 대기는 안 보인다) */
export const profItems = (data: ServerData, prof: string): CoordItem[] =>
  data.coord.filter((c) => c.professor === prof && !!c.message)

export default function ProfMessages({ data, prof }: { data: ServerData; prof: string }) {
  const items = profItems(data, prof)
  const bySection = new Map(data.sections.map((s) => [s.id, s]))
  return (
    <>
      <h1 tabIndex={-1}>조율 메시지</h1>
      <p className="lead">{prof} · 받은 조율 메시지 {items.length}건</p>
      {!items.length && <div className="card muted">받은 조율 메시지가 없습니다.</div>}
      {items.map((c) => <MessageCard key={`${c.section_id}-${c.round_no}`} c={c} section={bySection.get(c.section_id)} canReply={data.health.stage === 'ROUND'} />)}
    </>
  )
}
