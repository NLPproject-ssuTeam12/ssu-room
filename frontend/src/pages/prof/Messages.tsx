import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { C, S, SCRIPT, altLabel, full, log, receive, receiveConfirm } from '../../mock/demo'
import { act } from '../../store'
import { toast } from '../../ui'
import { Chip } from '../../components/common'

function ConfirmForm({ k }: { k: any }) {
  const [text, setText] = useState('')
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (k.reply) return
    act(() => receiveConfirm(k, text.trim(), `${k.prof} 교수님`))
    if (S.stage !== 'final') toast('확정 회신을 보냈습니다')
  }
  return (
    <form className="card" style={{ borderColor: 'var(--accent)' }} onSubmit={onSubmit}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <b>최종 시간표 확정 요청</b>
        {k.reply ? <Chip k="good">확정함</Chip> : <Chip k="warn">확정 필요</Chip>}
      </div>
      <div className="msg" style={{ marginTop: 10 }}>{k.text}</div>
      {k.reply ? (
        <div className="note" style={{ marginTop: 10 }}>확정했습니다{k.reply.note ? ` · 메모: ${k.reply.note}` : ''}.</div>
      ) : (
        <>
          <label className="lbl" htmlFor={`ct-${k.id}`}>하실 말씀 (선택)</label>
          <textarea id={`ct-${k.id}`} value={text} onChange={(e) => setText(e.target.value)} placeholder="예: 확인했습니다." />
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn primary" type="submit">확정</button>
            <span className="small muted">누르면 학과사무실에 확정 회신이 갑니다.</span>
          </div>
        </>
      )}
    </form>
  )
}

function ReplyForm({ m }: { m: any }) {
  const [choice, setChoice] = useState<string | null>(null)
  const [text, setText] = useState('')
  const live = S.stage === 'round' && m.round === S.round && !m.reply
  const example: string | undefined = SCRIPT[m.round]?.[m.cid]
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    const t = text.trim()
    if (!choice && !t) { document.getElementById(`rt-${m.id}`)?.focus(); return }
    act(() => {
      receive(m, t, choice, `${C(m.cid).prof} 교수님`)
      log(`${m.round}차 조율`, `${full(C(m.cid))}: ${C(m.cid).prof} 교수님 답장 도착`)
    })
    toast('답장을 보냈습니다')
  }
  const opt = (v: string, label: ReactNode, k: ReactNode, muted = false) => (
    <label key={v} className="alt">
      <input type="radio" name={`ch-${m.id}`} value={v} checked={choice === v} onChange={() => setChoice(v)} />
      <span className="k" style={muted ? { background: 'var(--muted)' } : undefined}>{k}</span>
      {label}
    </label>
  )
  return (
    <form className="card" onSubmit={onSubmit}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <b>{m.round}차 조율 · {full(C(m.cid))}</b>
        {m.reply ? <Chip k="good">답장함</Chip> : live ? <Chip k="warn">답장 필요</Chip> : <Chip>지난 차수</Chip>}
      </div>
      <div className="msg" style={{ marginTop: 10 }}>{m.text}</div>
      {live ? (
        <>
          <div className="lbl">안 고르기</div>
          {m.alts.map((a: any) => opt(a.k, altLabel(a), a.k))}
          {opt('none', '모두 어려움', '–', true)}
          <label className="lbl" htmlFor={`rt-${m.id}`}>하실 말씀 (선택)</label>
          <textarea id={`rt-${m.id}`} value={text} onChange={(e) => setText(e.target.value)} placeholder="예: A나 B 괜찮아요. 수요일은 17시 전에 끝나야 해요." />
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn primary" type="submit">보내기</button>
            {example && <button className="btn small" type="button" onClick={() => setText(example)}>예시 답장 넣기</button>}
          </div>
        </>
      ) : m.reply ? (
        <div className="note" style={{ marginTop: 10 }}>
          보낸 답장: {m.reply.choice ? `${m.reply.choice === 'none' ? '모두 어려움' : `${m.reply.choice}안`} · ` : ''}{m.reply.text || ''} · 조교 확인 후 반영됩니다.
        </div>
      ) : null}
    </form>
  )
}

export default function Messages() {
  const ms = S.msgs.filter((m: any) => m.sent && C(m.cid).prof === S.prof)
  const k = S.confirms.find((x: any) => x.prof === S.prof)
  if (!ms.length && !k) {
    return (
      <>
        <h1 tabIndex={-1}>조율 메시지</h1>
        <div className="card">받은 조율 메시지가 없습니다. {S.stage !== 'collect' && S.stage !== 'draft' ? '희망하신 대로 배정되었습니다.' : ''}</div>
      </>
    )
  }
  return (
    <>
      <h1 tabIndex={-1}>조율 메시지</h1>
      <p className="lead">{S.prof} 교수님께 온 메시지입니다.</p>
      {k && <ConfirmForm key={`${S.prof}-${k.id}`} k={k} />}
      {ms.slice().reverse().map((m: any) => <ReplyForm key={m.id} m={m} />)}
    </>
  )
}
