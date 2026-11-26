import { useState } from 'react'
import {
  ACT, C, MAX_SECTIONS, PROFS, S, SECMODE, courseGroups, emptyF, etcTodo, full, log, makeDraft, mkClaim, secKey,
  setSecCount, sync, todo, wishText,
} from '../../mock/demo'
import { act } from '../../store'
import { askConfirm, toast } from '../../ui'
import { Chip, Legend, MiniMap, WishChips } from '../../components/common'

function RawLine({ x }: { x: any }) {
  return (
    <>
      <div className="raw">
        <div><span>희망</span>{wishText(x.f)}</div>
        <div><span>인원</span>{x.f.size}명{x.f.lab ? ' · 실습실 필요' : ''}</div>
        {x.f.etc && <div><span>기타</span>{x.f.etc}</div>}
      </div>
      <MiniMap f={x.f} />
    </>
  )
}

function NoOwner({ c, locked }: { c: any; locked: boolean }) {
  const [prof, setProf] = useState(PROFS[0])
  return (
    <div className="note" style={{ marginBottom: 8, background: 'var(--warn-soft)' }}>
      <b style={{ color: 'var(--ink)' }}>{full(c)}</b> <Chip k="warn">담당 없음</Chip>
      <span className="small">아무도 고르지 않았습니다</span>
      <div className="row" style={{ marginTop: 8 }}>
        <select aria-label="담당 교수" value={prof} onChange={(e) => setProf(e.target.value)}>
          {PROFS.map((p: string) => <option key={p} value={p}>{p} 교수</option>)}
        </select>
        <button className="btn small primary" disabled={locked} onClick={() => act(() => {
          S.claims.push({ ...mkClaim(c.id, prof, emptyF()), byTA: true })
          S.pick[c.id] = prof
          sync()
          log('희망 수집', `${full(c)}: 담당 없음 → 조교가 ${prof} 교수로 지정했습니다 (희망 없음).`)
        })}>담당 지정 (희망 없음 → 아무 시간)</button>
        <button className="btn small" disabled={locked} onClick={() => act(() => {
          S.excl[c.id] = true
          sync()
          log('희망 수집', `${full(c)}: 이번 학기 제외`)
        })}>이번 학기 제외</button>
      </div>
    </div>
  )
}

function OwnerCard() {
  const dup = S.courses.filter((c: any) => c.own === 'dup')
  const none = S.courses.filter((c: any) => c.own === 'none')
  const ex = S.courses.filter((c: any) => c.own === 'excl')
  const picked = S.courses.filter((c: any) => c.own === 'ok' && S.pick[c.id])
  if (!dup.length && !none.length && !ex.length && !picked.length) return null
  const locked = S.stage !== 'collect'
  const claimsOf = (cid: string) => S.claims.filter((x: any) => x.cid === cid)
  return (
    <div className="card">
      <h2>담당 확인</h2>
      <p className="small muted" style={{ margin: '-4px 0 12px' }}>
        교수님이 개설 과목에서 맡을 분반을 직접 고릅니다. 선착순이 아니라서, 같은 분반을 여럿이 고르거나 아무도 안 고르면 조교가 정합니다. 담당 교수는 AI나 자동 배정이 정하지 않습니다.
      </p>
      {dup.map((c: any) => (
        <div key={c.id} className="note" style={{ marginBottom: 8, background: 'var(--warn-soft)' }}>
          <b style={{ color: 'var(--ink)' }}>{full(c)}</b> <Chip k="warn">담당 겹침</Chip>
          <span className="small">{claimsOf(c.id).length}명이 골랐습니다</span>
          <div className="cols" style={{ marginTop: 8 }}>
            {claimsOf(c.id).map((x: any) => (
              <div key={x.prof} className="card" style={{ margin: 0, padding: 12 }}>
                <b>{x.prof} 교수</b>
                <RawLine x={x} />
                <div>
                  <button className="btn small primary" style={{ marginTop: 8 }} disabled={locked} onClick={() => act(() => {
                    S.pick[c.id] = x.prof
                    sync()
                    log('희망 수집', `${full(c)}: 담당 겹침 → 조교가 ${x.prof} 교수로 정했습니다.`)
                  })}>{x.prof} 교수로 정하기</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
      {none.map((c: any) => <NoOwner key={c.id} c={c} locked={locked} />)}
      {picked.map((c: any) => (
        <div key={c.id} className="small" style={{ marginBottom: 4 }}>
          ✓ {full(c)} · {c.prof} 교수 <Chip k="good">조교가 정함</Chip>
          {!locked && (
            <button className="btn small" onClick={() => act(() => {
              delete S.pick[c.id]
              S.claims = S.claims.filter((x: any) => !(x.cid === c.id && x.byTA))
              sync()
            })}>되돌리기</button>
          )}
        </div>
      ))}
      {ex.map((c: any) => (
        <div key={c.id} className="small muted" style={{ marginBottom: 4 }}>
          – {full(c)} · 이번 학기 제외{' '}
          {!locked && (
            <button className="btn small" onClick={() => act(() => { delete S.excl[c.id]; sync() })}>되돌리기</button>
          )}
        </div>
      ))}
    </div>
  )
}

function EtcCell({ c }: { c: any }) {
  if (!c.f.etc) return <span className="small muted">없음</span>
  const locked = S.stage !== 'collect'
  return (
    <>
      <div className="small" style={{ marginBottom: 6 }}>{c.f.etc}</div>
      {c.f.etcOk ? (
        <>
          <Chip k="good">조교 확인함</Chip>
          {!locked && <button className="btn small" onClick={() => act(() => { C(c.id).f.etcOk = false })}>되돌리기</button>}
        </>
      ) : (
        <button className="btn small primary" disabled={locked} onClick={() => act(() => {
          c.f.etcOk = true
          log('희망 수집', `${full(c)}: 기타 요청 "${c.f.etc}"을(를) 조교가 확인했습니다.`)
        })}>확인함</button>
      )}
    </>
  )
}

/** 과목마다 분반을 몇 개 열지 (교수님들 회의에서 정해져 내려온 수를 조교가 넣는다) */
function SectionCountCard({ locked }: { locked: boolean }) {
  const groups = courseGroups()
  return (
    <div className="card">
      <h2>개설 분반 수</h2>
      <p className="small muted" style={{ margin: '-4px 0 10px' }}>
        {locked ? '희망 수집이 끝나 바꿀 수 없습니다.' : '교수님들 회의에서 정한 분반 수를 넣으면 교수님 화면에 그만큼 분반이 열립니다. 줄이면 번호가 큰 분반부터 빠집니다.'}
      </p>
      <div className="tblwrap">
        <table>
          <tbody>
            <tr><th>과목</th><th>학년</th><th style={{ width: 110 }}>분반 수</th><th>분반</th></tr>
            {groups.map((g: any) => (
              <tr key={g.name}>
                <td><b>{g.name}</b></td>
                <td>{g.year}</td>
                <td>
                  <input type="number" min={1} max={MAX_SECTIONS} value={g.secs.length} disabled={locked}
                    aria-label={`${g.name} 분반 수`} style={{ width: 64 }}
                    onChange={(e) => {
                      const n = Number(e.target.value)
                      if (!Number.isFinite(n) || n < 1) return
                      const lost = g.secs.slice(n).filter((c: any) => S.claims.some((x: any) => x.cid === c.id))
                      if (!lost.length) { act(() => setSecCount(g.name, n)); return }
                      askConfirm({
                        title: `${g.name} 분반을 ${n}개로 줄일까요?`,
                        body: `${lost.map(full).join(', ')}에 이미 낸 희망이 있습니다. 줄이면 같이 지워집니다.`,
                        ok: '줄이기',
                      }, () => act(() => setSecCount(g.name, n)))
                    }} />
                </td>
                <td className="small muted">{g.secs.map((c: any) => c.sec).join(', ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function Wishes({ go }: { go: (v: string) => void }) {
  const flags = todo()
  // 기타 요청이 있는 분반부터 (확인해도 자리는 그대로)
  const etcFirst = ACT()
    .map((c: any, i: number) => ({ c, i }))
    .sort((a: any, b: any) => (b.c.f.etc ? 1 : 0) - (a.c.f.etc ? 1 : 0) || a.i - b.i)
    .map((x: any) => x.c)
  const etcN = ACT().filter((c: any) => c.f.etc).length
  const done = S.stage !== 'collect'
  return (
    <>
      <h1 tabIndex={-1}>희망 확인</h1>
      <p className="lead">교수님이 선택칸으로 낸 희망입니다. 이 값으로 바로 시간표를 배정합니다. 기타 요청은 자동 배정에 들어가지 않아서 조교가 직접 확인합니다.</p>
      <SectionCountCard locked={done} />
      <OwnerCard />
      <div className="card">
        <div style={{ marginBottom: 10 }}><Legend /></div>
        <div className="tblwrap">
          <table>
            <tbody>
              <tr><th style={{ width: 150 }}>분반</th><th style={{ width: 110 }}>시간 칠하기</th><th>배정 조건</th><th>기타 요청 (조교 확인)</th></tr>
              {etcN > 0 && (
                <tr><td colSpan={4} className="small" style={{ background: 'var(--warn-soft)', padding: '6px 8px' }}>
                  <b>기타 요청이 있는 분반 {etcN}개</b> · 먼저 확인해 주세요 (남은 것 {etcTodo()}개)
                </td></tr>
              )}
              {etcFirst.flatMap((c: any, i: number) => [
                i === etcN && etcN > 0 ? (
                  <tr key="sep"><td colSpan={4} className="small muted" style={{ background: 'var(--sunk)', padding: '6px 8px' }}>기타 요청 없는 분반</td></tr>
                ) : null,
                <tr key={c.id} className={c.f.etc && !c.f.etcOk ? 'flag' : ''}>
                  <td>
                    <b>{full(c)}</b>
                    <div className="small muted">{c.prof} 교수 · {c.year}학년{c.req ? ' 전필' : ''}</div>
                    {c.byTA && <Chip>조교가 담당 지정</Chip>}
                  </td>
                  <td><MiniMap f={c.f} /></td>
                  <td>
                    <WishChips f={c.f} prof={c.prof} />
                    {(S.secMode[secKey(c.prof, c.name)] || 'any') !== 'any' && <Chip>{SECMODE[S.secMode[secKey(c.prof, c.name)]]}</Chip>}
                  </td>
                  <td style={{ minWidth: 170 }}><EtcCell c={c} /></td>
                </tr>,
              ])}
            </tbody>
          </table>
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          <button className="btn primary" disabled={flags > 0 || done} onClick={() => {
            act(() => makeDraft())
            go('draft')
            toast('초안을 만들었습니다')
          }}>초안 만들기</button>
          <span className="small muted">
            {done ? '초안을 이미 만들었습니다.' : flags ? `담당·기타 요청 확인 ${flags}건을 먼저 정해 주세요.` : '규칙을 지키는 초안을 만듭니다.'}
          </span>
        </div>
      </div>
      <p className="note">기타 요청 예: 실습 조교 배정, 대강 일정, 다른 강의와 같은 요일. 시간표에 넣어야 하는 내용이면 조교가 교수님께 칠하기를 고쳐 달라고 요청합니다.</p>
    </>
  )
}
