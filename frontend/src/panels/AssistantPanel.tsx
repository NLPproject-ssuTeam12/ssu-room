import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { BOT_EX, C, S, altLabel, applyBot, botRun, full, wishOkAt } from '../mock/demo'
import { act } from '../store'
import { askConfirm } from '../ui'
import { Chip, Stub } from '../components/common'

function Preview({ t, i }: { t: any; i: number }) {
  const p = t.preview
  const onApply = () =>
    askConfirm(
      {
        title: '시간표에 적용할까요?',
        body: `바뀌는 분반 ${p.changes.length}개 · 하드 규칙 위반 ${p.v}건${p.notice ? `\n이미 정해진 강의 ${p.notice}개가 바뀌어 교수님께 변경 안내가 필요합니다.` : ''}`,
        ok: '적용', reason: true, placeholder: '예: 305 공사 일정이 확정됨',
      },
      (reason) => act(() => applyBot(i, reason)),
    )
  return (
    <>
      <div className="tblwrap">
        <table className="chg">
          <tbody>
            <tr><th>분반</th><th>지금 → 바꾸면</th><th>희망</th></tr>
            {p.changes.map((x: any) => {
              const c = C(x.cid)
              const ok = wishOkAt(c, x.to.pat, x.to.slot)
              return (
                <tr key={x.cid}>
                  <td style={{ minWidth: 104 }}><b>{full(c)}</b><div className="small muted">{c.prof} 교수</div></td>
                  <td><span className="muted">{altLabel(x.from)}</span><br />→ <b>{altLabel(x.to)}</b></td>
                  <td><Chip k={ok ? 'good' : 'warn'}>{ok ? '안' : '밖'}</Chip></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {p.state === 'applied' ? <div className="decided">적용했습니다</div>
        : p.state === 'cancel' ? <div className="note" style={{ marginTop: 8 }}>취소했습니다</div>
        : p.state === 'stale' ? <div className="note" style={{ marginTop: 8 }}>그사이 시간표가 바뀌어 다시 계산해야 합니다</div>
        : (
          <>
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn primary small" onClick={onApply}>적용</button>
              <button className="btn small" onClick={() => act(() => { p.state = 'cancel' })}>취소</button>
              {S.view !== 'draft' && <button className="btn small" onClick={() => act(() => { S.view = 'draft' })}>시간표에서 보기</button>}
            </div>
            <div className="small muted" style={{ marginTop: 6 }}>적용을 누르면 사유를 받고 다시 확인합니다. 그전에는 시간표가 바뀌지 않습니다.</div>
          </>
        )}
    </>
  )
}

function BotTurn({ t, i }: { t: any; i: number }) {
  const ik = t.intent === '범위 밖' || t.intent === '확인 필요' ? 'warn' : 'accent'
  return (
    <div className="turn bot">
      <div>{t.text}</div>
      {t.preview && <Preview t={t} i={i} />}
      <details className="trace">
        <summary>AI가 읽은 내용</summary>
        <div>
          <span className="who ai">AI</span>의도 <Chip k={ik}>{t.intent}</Chip>
          {t.ask && <Chip k="warn">되묻기</Chip>}
          {Object.entries(t.info).map(([k, v]) => <Chip key={k}>{k}: {String(v)}</Chip>)}
        </div>
        {t.tool && <div><span className="who ai">AI</span>도구 호출 <code>{t.tool}</code></div>}
        {t.solver && <div><span className="who sv">계산</span>{t.solver}</div>}
      </details>
    </div>
  )
}

export default function AssistantPanel({ onClose }: { onClose: () => void }) {
  const [q, setQ] = useState('')
  const chat = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const turns = S.bot.turns.length

  useEffect(() => { input.current?.focus() }, [])
  useEffect(() => {
    if (chat.current) chat.current.scrollTop = chat.current.scrollHeight
  }, [turns])

  const ask = (text: string) => {
    act(() => botRun(text))
    input.current?.focus()
  }
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    const v = q.trim()
    if (!v) { input.current?.focus(); return }
    setQ('')
    ask(v)
  }
  return (
    <aside className="botpanel" role="complementary" aria-labelledby="bot-t">
      <div className="bph">
        <b id="bot-t">AI 도우미</b><Stub /><span className="small muted">[적용]을 눌러야 바뀝니다</span>
        <div className="spacer" />
        <button className="btn small" aria-label="AI 도우미 닫기" onClick={onClose}>닫기</button>
      </div>
      <div className="chat" ref={chat} role="log" aria-live="polite">
        {turns ? S.bot.turns.map((t: any, i: number) => t.who === 'ta'
          ? <div key={i} className="turn ta">{t.text}</div>
          : <BotTurn key={i} t={t} i={i} />)
          : <div className="muted small">말로 물어보면 AI가 뜻을 읽고 시간표를 다시 계산해 결과를 알려 줍니다. 아래 예시를 눌러 보거나 직접 물어보세요.</div>}
      </div>
      <form onSubmit={onSubmit}>
        {S.stage === 'collect' && <div className="note" style={{ marginBottom: 8 }}>초안을 만든 뒤에 옮기기·가정 질문을 할 수 있습니다. 지금은 현황 질문만 됩니다.</div>}
        <div className="botex">
          {BOT_EX.map((x: string) => <button key={x} type="button" className="btn small" onClick={() => ask(x)}>{x}</button>)}
        </div>
        <div className="row" style={{ flexWrap: 'nowrap' }}>
          <input ref={input} type="text" autoComplete="off" aria-label="AI 도우미에게 물어보기" placeholder="예: 화요일 오전 비우면?"
            value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="btn primary" type="submit">보내기</button>
        </div>
      </form>
    </aside>
  )
}
