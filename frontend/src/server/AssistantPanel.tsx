// AI 도우미 (서버 POST /assistant, /assistant/apply). 옮기기는 제안만 받고, [적용] + 사유를 넣어야 반영된다.
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../api/client'
import type { AssistantResponse, Stage } from '../api/types'
import { Chip } from '../components/common'
import { askConfirm, toast } from '../ui'
import { mutate } from './data'
import { EXAMPLES, INTENT_LABEL, addBotTurn, hasMoves, setApply, toHistory } from './assistant'
import type { Turn } from './assistant'

const errorText = (e: unknown): string => (e instanceof Error ? e.message : '도우미가 답하지 못했습니다.')

function Changes({ res }: { res: AssistantResponse }) {
  if (!res.changes.length) return null
  if (!hasMoves(res)) {
    return (
      <ul className="small" style={{ margin: '6px 0 0', paddingLeft: 18 }}>
        {res.changes.map((c) => <li key={c.section_id}>{c.name} · {c.note}</li>)}
      </ul>
    )
  }
  return (
    <div className="tblwrap">
      <table className="chg">
        <tbody>
          {res.changes.map((c) => (
            <tr key={c.section_id}>
              <td style={{ minWidth: 104 }}><b>{c.name}</b><div className="small muted">{c.note}</div></td>
              <td><span className="muted">{c.before ?? '—'}</span><br />→ <b>{c.after ?? '—'}</b></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface BotTurnProps {
  turn: Extract<Turn, { role: 'bot' }>
  onApply: () => void
  onCancel: () => void
}

function BotTurn({ turn, onApply, onCancel }: BotTurnProps) {
  const { res, apply } = turn
  const intent = res.command.intent
  return (
    <div className="turn bot">
      <div className="row" style={{ gap: 6, marginBottom: 4 }}>
        <Chip k={intent === 'out_of_scope' ? 'warn' : ''}>{INTENT_LABEL[intent] ?? intent}</Chip>
      </div>
      <div style={{ whiteSpace: 'pre-wrap' }}>{res.answer}</div>
      <Changes res={res} />
      {apply === 'applied' && <div className="decided">적용했습니다</div>}
      {apply === 'cancelled' && <div className="note" style={{ marginTop: 8 }}>이 제안은 쓰지 않습니다</div>}
      {apply === 'pending' && (
        <>
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn primary small" onClick={onApply}>적용</button>
            <button className="btn small" onClick={onCancel}>취소</button>
          </div>
          <div className="small muted" style={{ marginTop: 6 }}>적용을 누르면 사유를 받습니다. 그전에는 시간표가 바뀌지 않습니다.</div>
        </>
      )}
    </div>
  )
}

interface Props {
  stage: Stage
  turns: Turn[]
  setTurns: (fn: (t: Turn[]) => Turn[]) => void
  onClose: () => void
}

export default function AssistantPanel({ stage, turns, setTurns, onClose }: Props) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const chat = useRef<HTMLDivElement>(null)
  useEffect(() => { chat.current?.scrollTo({ top: chat.current.scrollHeight }) }, [turns])

  const ask = async (q: string) => {
    const question = q.trim()
    if (!question || busy) return
    const history = toHistory(turns)
    setTurns((t) => [...t, { role: 'user', text: question }])
    setText('')
    setBusy(true)
    try {
      const res = await api.assistant(question, history)
      setTurns((t) => addBotTurn(t, res))
    } catch (e: unknown) {
      setTurns((t) => [...t, { role: 'error', text: errorText(e) }])
    } finally {
      setBusy(false)
    }
  }
  const apply = (index: number, proposalId: string) => askConfirm(
    { title: '이 제안을 적용할까요?', body: '시간표에 바로 반영하고 수정 기록에 사유를 남깁니다.', ok: '적용', reason: true, placeholder: '사유 (예: 교수님 요청으로 옮김)' },
    (reason) => {
      void (async () => {
        try {
          await mutate(() => api.assistantApply(proposalId, reason))
          setTurns((t) => setApply(t, index, 'applied'))
          toast('도우미 제안을 적용했습니다')
        } catch (e: unknown) {
          setTurns((t) => [...setApply(t, index, 'cancelled'), { role: 'error', text: `적용하지 못했습니다: ${errorText(e)}` }])
        }
      })()
    },
  )
  const onSubmit = (e: FormEvent) => { e.preventDefault(); void ask(text) }

  return (
    <aside className="botpanel" role="complementary" aria-labelledby="bot-t">
      <div className="bph">
        <b id="bot-t">AI 도우미</b><span className="small muted">[적용]을 눌러야 바뀝니다</span>
        <div className="spacer" />
        <button className="btn small" aria-label="AI 도우미 닫기" onClick={onClose}>닫기</button>
      </div>
      <div className="chat" ref={chat} role="log" aria-live="polite">
        {!turns.length && <div className="muted small">시간표를 말로 물어보면 다시 계산해 알려 줍니다. 아래 예시를 눌러 보거나 직접 물어보세요.</div>}
        {turns.map((t, i) => {
          if (t.role === 'user') return <div key={i} className="turn ta">{t.text}</div>
          if (t.role === 'error') return <div key={i} className="note" role="alert" style={{ background: 'var(--bad-soft)' }}>{t.text}</div>
          return <BotTurn key={i} turn={t} onApply={() => t.res.proposal_id && apply(i, t.res.proposal_id)} onCancel={() => setTurns((x) => setApply(x, i, 'cancelled'))} />
        })}
        {busy && <div className="muted small">계산하는 중…</div>}
      </div>
      <form className="botin" onSubmit={onSubmit}>
        {stage === 'COLLECT' && <div className="note" style={{ marginBottom: 8 }}>초안을 만든 뒤에 옮기기·가정 질문을 할 수 있습니다. 지금은 현황 질문만 됩니다.</div>}
        <div className="botex">
          {EXAMPLES.map((x) => <button key={x} type="button" className="btn small" disabled={busy} onClick={() => void ask(x)}>{x}</button>)}
        </div>
        <div className="row" style={{ flexWrap: 'nowrap' }}>
          <input aria-label="도우미에게 물어보기" value={text} onChange={(e) => setText(e.target.value)} placeholder="예: 운영체제 02 왜 밀렸어?" style={{ flex: 1 }} />
          <button className="btn primary" type="submit" disabled={busy || !text.trim()}>보내기</button>
        </div>
      </form>
    </aside>
  )
}
