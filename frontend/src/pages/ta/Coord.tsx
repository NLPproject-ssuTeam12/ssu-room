import { useState } from 'react'
import {
  C, S, SCRIPT, altLabel, check, checkMessage, condLabel, emptyCond, full, hasCond, later, autoReply, log,
  openMsgs, receive, resolveRound, sendOne, toDecision,
} from '../../mock/demo'
import { act } from '../../store'
import { askConfirm, toast } from '../../ui'
import { Chip } from '../../components/common'
import PeekBtns, { togglePeek } from '../../components/PeekBtns'

const KINDC: Record<string, string> = { 수용: 'good', 조건부: 'accent', 거절: 'bad', '확인 필요': 'warn' }

function MsgPart({ m }: { m: any }) {
  if (m.sent) {
    return (
      <>
        <div className="lbl">보낸 조율 메시지</div>
        <div className="msg">{m.text}</div>
      </>
    )
  }
  const problems: string[] = checkMessage(m.text, m)
  const onSend = () => {
    if (!sendOne(m)) {
      toast('메시지 검사에 걸려 보내지 않았습니다')
      document.getElementById(`mt-${m.id}`)?.focus()
      return
    }
    act(() => undefined)
    toast('보냈습니다')
  }
  return (
    <>
      <label className="lbl" htmlFor={`mt-${m.id}`}>
        조율 메시지 미리 보기 <span className="muted small">(고칠 수 있음 · 보내기 전에 검사)</span>
      </label>
      <textarea className="msgedit" id={`mt-${m.id}`} value={m.text} onChange={(e) => act(() => { m.text = e.target.value })} />
      <div aria-live="polite">
        {problems.length
          ? problems.map((t) => <div key={t} className="prob">✗ {t}</div>)
          : <div className="chk ok">✓ 메시지 검사 통과 (check_message)</div>}
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn primary small" onClick={onSend}>보내기</button>
        <button className="btn small" onClick={() => act(() => { m.text = m.text0 })}>처음 문장으로</button>
      </div>
    </>
  )
}

/** [수정]·[현재대로 유지]: 사유를 꼭 받는다 */
function EditBox({ m }: { m: any }) {
  const [why, setWhy] = useState('')
  const [err, setErr] = useState('')
  const mode = S.editing.mode
  const onSel = (v: string) =>
    act(() => {
      S.editing.sel = v
      S.peek = v === 'next' ? null : { m: m.id, k: v }
      if (v !== 'next') { S.ttOpen = true; S.botOpen = false }
    })
  const onSave = () => {
    const reason = why.trim()
    if (!reason) { setErr('사유를 적어 주세요.'); document.getElementById('ed-why')?.focus(); return }
    act(() => {
      if (mode === 'keep') m.decision = { kind: '현재대로 유지', action: { type: 'keep' }, reason }
      else {
        const v = S.editing.sel
        m.decision = {
          kind: '수정',
          action: v === 'next' ? { type: 'next', conds: m.parsed ? m.parsed.conditions : emptyCond() } : { type: 'move', k: v },
          reason,
        }
      }
      log(`${S.round}차 조율`, `${full(C(m.cid))}: 조교 ${m.decision.kind} · 사유 "${reason}"`)
      S.editing = null
    })
  }
  return (
    <div style={{ marginTop: 10 }}>
      {mode === 'edit' && (
        <>
          <label className="lbl" htmlFor="ed-sel">어떻게 처리할까요? <span className="muted small">(고르면 오른쪽 시간표에 점선으로 보입니다)</span></label>
          <select id="ed-sel" value={S.editing.sel} onChange={(e) => onSel(e.target.value)}>
            {m.alts.map((a: any) => <option key={a.k} value={a.k}>{a.k}안 · {altLabel(a)}</option>)}
            {S.round < 3 && <option value="next">다음 차수에 다시 묻기</option>}
          </select>
        </>
      )}
      <label className="lbl" htmlFor="ed-why">사유 (필수, 기록에 남음)</label>
      <input type="text" id="ed-why" value={why} onChange={(e) => setWhy(e.target.value)}
        placeholder={mode === 'edit' ? '예: 교수님과 통화로 B안 확인' : '예: 교수님이 임시 배치도 괜찮다고 하심'} />
      <div className="prob" role="alert">{err}</div>
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn primary small" onClick={onSave}>저장</button>
        <button className="btn small" onClick={() => act(() => { S.editing = null })}>취소</button>
      </div>
    </div>
  )
}

function DecisionBox({ m }: { m: any }) {
  if (!m.sent) return <div className="note">아직 보내지 않았습니다. 메시지를 확인하고 [보내기]를 누르면 교수님께 갑니다.</div>
  if (!m.reply) return <div className="note">회신 대기 중 · 기한 1주, 기한 전 자동 재알림</div>
  const ck = check(m)
  const r = m.parsed
  const ch = m.reply.choice
  const pick = ch ? (ch === 'none' ? '모두 어려움' : `${ch}안`) : ''
  const drop: string[] = ck.checks.filter((x: any) => !x.ok).map((x: any) => `${x.key}안: ${x.why}`)
  const editing = S.editing && S.editing.m === m.id
  const onConfirm = () =>
    askConfirm({ title: '처리안을 확인할까요?', body: `${full(C(m.cid))} · ${ck.text}\n[재배정]을 누를 때 시간표에 반영됩니다.` }, () =>
      act(() => {
        m.decision = toDecision(ck, '확인')
        S.editing = null
        log(`${S.round}차 조율`, `${full(C(m.cid))}: 조교 확인 · ${ck.text}`)
      }),
    )
  const onEdit = (mode: 'edit' | 'keep') =>
    act(() => {
      const k0 = ck.key || m.alts[0].k
      S.editing = { m: m.id, mode, sel: k0 }
      if (mode === 'edit') { S.peek = { m: m.id, k: k0 }; S.ttOpen = true; S.botOpen = false }
    })
  const d = m.decision
  const what = d ? (d.action.type === 'move' ? `${d.action.k}안으로 이동` : d.action.type === 'keep' ? '현재 배치 유지' : '다음 차수에 다시 묻기') : ''
  return (
    <div>
      <div className="lbl">교수님 답장</div>
      <div className="msg">
        {m.reply.text ? <>"{m.reply.text}"{pick && <span className="muted small"> ({pick} 버튼)</span>}</> : `${pick} 버튼`}
      </div>
      <div className="row" style={{ marginTop: 8, gap: 4 }}>
        <Chip k={KINDC[r.kind]}>{r.kind}</Chip>
        {r.picks.length > 0 && <Chip>고른 안 {r.picks.join('·')}</Chip>}
        {hasCond(r.conditions) && <Chip k="accent">조건: {condLabel(r.conditions)}</Chip>}
      </div>
      {r.note && (
        <div className="small" style={{ marginTop: 4 }}>
          <b>교수님 요청</b> · {r.note} <span className="muted">— 배정 엔진은 읽지 않고 조교가 확인합니다</span>
        </div>
      )}
      <div className="prop">
        <div className="big">{ck.text}</div>
        {ck.action === 'move' && (
          <button type="button" className="btn small" style={{ marginTop: 6 }} onClick={() => togglePeek(m.id, ck.key)}>시간표에서 {ck.key}안 보기</button>
        )}
        {drop.map((t) => <div key={t} className="small" style={{ marginTop: 4 }}>{t}</div>)}
        {r.note && ck.action !== 'decide' && <div className="small" style={{ marginTop: 4 }}>교수님 요청: {r.note}</div>}
        {d ? (
          <div className="decided">
            {d.kind} · {what}{d.reason ? ` · 사유: ${d.reason}` : ''}{' '}
            <button className="btn small" style={{ marginLeft: 6 }} onClick={() => act(() => { m.decision = null })}>되돌리기</button>
          </div>
        ) : (
          <>
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn primary small" disabled={ck.action === 'decide'} onClick={onConfirm}>확인</button>
              <button className="btn small" onClick={() => onEdit('edit')}>수정</button>
              <button className="btn small" onClick={() => onEdit('keep')}>현재대로 유지</button>
            </div>
            {ck.action === 'decide' && <div className="small muted" style={{ marginTop: 4 }}>처리안이 "직접 결정"이라 [확인]을 쓸 수 없습니다.</div>}
            {editing && <EditBox key={`${m.id}-${S.editing.mode}`} m={m} />}
          </>
        )}
      </div>
    </div>
  )
}

function Controls({ ms }: { ms: any[] }) {
  const unsent = ms.filter((m) => !m.sent)
  const allDecided = ms.every((m) => m.decision)
  const onSendAll = () => {
    let n = 0
    const ok = unsent.filter((x) => sendOne(x, n) && ++n).length
    act(() => undefined)
    toast(ok === unsent.length ? `${ok}건 보냈습니다` : `${ok}건 보냄 · ${unsent.length - ok}건은 검사에 걸려 남겼습니다`)
  }
  const onFake = () => {
    act(() => openMsgs().filter((x: any) => x.sent && !x.reply)
      .forEach((x: any) => receive(x, (SCRIPT[S.round] || {})[x.cid] || 'A로 할게요.', null, '가상 회신')))
    toast('가상 회신을 받았습니다')
  }
  const onResolve = () => {
    const done = ms.filter((x) => x.decision).length
    const rest = ms.length - done
    askConfirm(
      {
        title: `${S.round}차 재배정을 할까요?`,
        body: `확인한 처리안 ${done}건만 반영하고 나머지 배정은 그대로 둡니다.${rest ? `\n정하지 않은 ${rest}건은 ${S.round < 3 ? '다음 차수로 넘어갑니다' : '임시 배치로 확정됩니다'}.` : ''}`,
        ok: '재배정',
      },
      () => {
        act(() => { resolveRound(); S.view = S.stage === 'review' ? 'final' : 'coord' })
        toast(S.stage === 'review' ? '조율이 끝났습니다 · 교수님께 확정을 요청하세요' : `${S.round}차 조율로 넘어갔습니다`)
      },
    )
  }
  return (
    <div className="card">
      <div className="row">
        <button className="btn" disabled={!unsent.length} onClick={onSendAll}>전체 보내기{unsent.length ? ` (${unsent.length})` : ''}</button>
        <button className="btn" disabled={!ms.some((m) => m.sent && !m.reply)} onClick={onFake}>가상 회신 받기 (시연용)</button>
        <button className="btn primary" disabled={!ms.length} onClick={onResolve}>재배정 (최소 변경)</button>
        <span className="small muted">{allDecided ? '모든 처리안을 정했습니다.' : '처리안을 정하지 않은 건은 다음 차수로 넘어갑니다.'}</span>
      </div>
      <label className="switch small" style={{ marginTop: 10, gap: 6 }}>
        <input type="checkbox" checked={S.autoReply} onChange={(e) => act(() => {
          S.autoReply = e.target.checked
          if (S.autoReply) openMsgs().filter((m: any) => m.sent && !m.reply).forEach((m: any, i: number) => later(() => autoReply(m), i))
        })} />
        가상 회신 자동 도착 (보내고 몇 초 뒤 · 다른 화면에 있어도 알림과 메뉴 숫자로 알려 줌)
      </label>
      <p className="small muted" style={{ margin: '6px 0 0' }}>교수 화면에서 직접 답장해도 됩니다. 위에서 역할을 '교수'로 바꾸세요.</p>
    </div>
  )
}

export default function Coord() {
  if (S.stage === 'collect' || S.stage === 'draft') {
    return (
      <>
        <h1 tabIndex={-1}>조율</h1>
        <div className="card">초안을 공개하면 밀린 분반의 조율 메시지 초안이 만들어집니다.</div>
      </>
    )
  }
  const inRound = S.stage === 'round'
  const ms: any[] = inRound ? openMsgs() : []
  const past = S.msgs.filter((m: any) => !(inRound && m.round === S.round))
  return (
    <>
      <h1 tabIndex={-1}>조율</h1>
      <p className="lead">{inRound ? `${S.round}차 조율 · 회신 기한 1주 · 최대 3차` : '조율이 끝났습니다.'}</p>
      {inRound && <Controls ms={ms} />}
      {ms.map((m) => {
        const c = C(m.cid)
        return (
          <div key={m.id} className="card">
            <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
              <div><b>{full(c)}</b> <span className="muted">→ {c.prof} 교수님</span></div>
              <span className="row" style={{ gap: 4 }}>
                {m.sent ? <Chip k="good">보냄</Chip> : <Chip k="warn">보내기 전</Chip>}
                <Chip>{m.round}차</Chip>
              </span>
            </div>
            <div className="cols">
              <div><MsgPart m={m} /><PeekBtns m={m} /></div>
              <DecisionBox m={m} />
            </div>
          </div>
        )
      })}
      {past.length > 0 && (
        <div className="card">
          <h2>지난 메시지</h2>
          {past.map((m: any) => (
            <div key={m.id} className="small" style={{ marginBottom: 6 }}>
              <b>{m.round}차 · {full(C(m.cid))}</b> ·{' '}
              {!m.sent ? '보내지 않음' : m.reply ? `답장 "${m.reply.text}" → ${m.decision ? m.decision.kind : '처리 안 함'}` : '회신 없음'}
            </div>
          ))}
        </div>
      )}
    </>
  )
}
