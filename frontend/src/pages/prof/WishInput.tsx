import { useEffect, useRef } from 'react'
import type { KeyboardEvent, PointerEvent } from 'react'
import {
  ACT, BLDGS, C, CONSN, D5, DAYN, S, SECMODE, SECMODE_TIP, SIZES, SLOTS, blockedCell, claimOf, emptyF, full, kindOf,
  log, mcls, mk, mkClaim, multiSecNames, nextMark, secKey, setMark, sync,
} from '../../mock/demo'
import { act } from '../../store'
import { Legend, WishChips } from '../../components/common'

type Paint = { cid: string; mark: string | null; last: string }
const ARROWS: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }

/** 시간 칠하기 격자. 누르면 희망 → 불가 → 빈칸, 끌면 여러 칸을 한 번에 */
function PaintGrid({ cid, f, locked }: { cid: string; f: any; locked: boolean }) {
  const painting = useRef<Paint | null>(null)
  const year = C(cid).year

  const paintAt = (d: number, k: number) => {
    const x = claimOf(cid, S.prof)
    const p = painting.current
    if (!x || !p) return
    act(() => setMark(x, d, k, p.mark))
  }

  useEffect(() => {
    const onMove = (e: globalThis.PointerEvent) => {
      const p = painting.current
      if (!p) return
      const el = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLButtonElement>('[data-paint]')
      if (!el || el.disabled || el.dataset.paint !== p.cid) return
      const key = `${el.dataset.d}-${el.dataset.s}`
      if (key === p.last) return
      p.last = key
      paintAt(Number(el.dataset.d), Number(el.dataset.s))
    }
    const onUp = () => { painting.current = null }
    document.addEventListener('pointermove', onMove)
    document.addEventListener('pointerup', onUp)
    document.addEventListener('pointercancel', onUp)
    return () => {
      document.removeEventListener('pointermove', onMove)
      document.removeEventListener('pointerup', onUp)
      document.removeEventListener('pointercancel', onUp)
    }
  })

  const start = (d: number, k: number) => {
    painting.current = { cid, mark: nextMark(mk(f, d, k)), last: `${d}-${k}` }
    paintAt(d, k)
  }
  const onPointerDown = (e: PointerEvent, d: number, k: number) => {
    e.preventDefault()
    start(d, k)
  }
  const onKeyClick = (detail: number, d: number, k: number) => {
    if (detail !== 0) return // 마우스는 pointerdown에서 처리했다
    start(d, k)
    painting.current = null
  }
  // 화살표로 옮기기 (막힌 칸은 건너뜀)
  const onKeyDown = (e: KeyboardEvent) => {
    const el = (e.target as HTMLElement).closest<HTMLButtonElement>('[data-paint]')
    const mv = ARROWS[e.key]
    if (!el || !mv) return
    e.preventDefault()
    let d = Number(el.dataset.d)
    let k = Number(el.dataset.s)
    for (;;) {
      d += mv[0]; k += mv[1]
      if (d < 0 || d > 4 || k < 0 || k >= SLOTS.length) return
      const n = document.querySelector<HTMLButtonElement>(`[data-paint="${cid}"][data-d="${d}"][data-s="${k}"]`)
      if (n && !n.disabled) { n.focus(); return }
    }
  }

  return (
    <div className="pg" role="group" aria-label={`${full(C(cid))} 수업 가능 시간 (화살표로 이동)`} onKeyDown={onKeyDown}>
      <div />
      {D5.map((d: number) => <div key={d} className="pgh">{DAYN[d]}</div>)}
      {SLOTS.map((t: string, k: number) => [
        <div key={`t${k}`} className="pgt">{t}</div>,
        ...D5.map((d: number) => {
          const bl = blockedCell(year, d, k)
          if (bl) {
            return <button key={`${d}-${k}`} type="button" className="pc blocked" disabled aria-label={`${DAYN[d]} ${t} ${bl} 시간이라 고를 수 없음`}>{bl}</button>
          }
          const m = mk(f, d, k)
          return (
            <button key={`${d}-${k}`} type="button" className={`pc ${mcls(m)}`} disabled={locked}
              data-paint={cid} data-d={d} data-s={k} aria-label={`${DAYN[d]} ${t} ${m || '가능'}`}
              onPointerDown={(e) => onPointerDown(e, d, k)} onClick={(e) => onKeyClick(e.detail, d, k)}>
              {m || ''}
            </button>
          )
        }),
      ])}
    </div>
  )
}

function WishForm({ c, x, locked }: { c: any; x: any; locked: boolean }) {
  const pair = S.pair[c.id] || {}
  const setF = (fn: (f: any) => void) => act(() => fn(x.f))
  return (
    <div className="card">
      <h2>{full(c)} <span className="small muted">{c.year}학년 {kindOf(c)}</span></h2>
      <div className="pw">
        <div>
          <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
            <span className="lbl" style={{ margin: 0 }}>수업 가능 시간</span>
            {!locked && (
              <span className="row" style={{ gap: 6 }}>
                {[['mw', '월·수 묶기'], ['tt', '화·목 묶기']].map(([k, t]) => (
                  <button key={k} type="button" className="tog" aria-pressed={!!pair[k]}
                    onClick={() => act(() => { S.pair = { ...S.pair, [c.id]: { ...pair, [k]: !pair[k] } } })}>{t}</button>
                ))}
              </span>
            )}
          </div>
          <PaintGrid cid={c.id} f={x.f} locked={locked} />
          <div style={{ marginTop: 8 }}><Legend /></div>
          <p className="small muted" style={{ margin: '6px 0 0' }}>안 칠한 칸은 수업 가능입니다. 누를 때마다 희망 → 불가 → 빈칸으로 바뀌고, 끌면 여러 칸을 한 번에 칠합니다. 묶기를 켜면 짝 요일 칸도 같이 바뀝니다. 키보드는 화살표로 옮기고 Enter로 바꿉니다.</p>
        </div>
        <div>
          <div className="row" style={{ gap: 14, alignItems: 'flex-end' }}>
            <div>
              <div className="lbl">인원</div>
              <select aria-label="인원" value={x.f.size} disabled={locked} onChange={(e) => setF((f) => { f.size = Number(e.target.value) })}>
                {SIZES.map((n: number) => <option key={n} value={n}>{n}명</option>)}
              </select>
            </div>
            <div>
              <div className="lbl">실습실</div>
              <select aria-label="실습실" value={x.f.lab ? '1' : '0'} disabled={locked} onChange={(e) => setF((f) => { f.lab = e.target.value === '1' })}>
                <option value="0">필요 없음</option><option value="1">필요</option>
              </select>
            </div>
          </div>
          <div className="lbl">건물 선호 <span className="muted small">(강의실 호수는 학과사무실에서 정합니다)</span></div>
          <select aria-label="건물 선호" value={x.f.pref || ''} disabled={locked} onChange={(e) => setF((f) => { f.pref = e.target.value || null })}>
            <option value="">상관없음</option>
            {BLDGS.map((b: string) => <option key={b} value={b}>{b}</option>)}
          </select>
          <div className="lbl">기타 요청 <span className="muted small">(위 칸으로 정할 수 없는 것만)</span></div>
          <textarea value={x.f.etc} disabled={locked} placeholder="예: 학기 중 두 번 대강이 필요합니다. 학과사무실에서 직접 확인합니다."
            onChange={(e) => setF((f) => { f.etc = e.target.value; f.etcOk = false })} />
          <div className="lbl">접수 내용</div>
          <div><WishChips f={x.f} prof={S.prof} /></div>
        </div>
      </div>
    </div>
  )
}

/** 맡은 강의끼리 놓는 방식: 연강(교수 단위), 같은 과목 분반 둘 이상이면 분반 연강·교차 */
function ArrangeCard({ locked }: { locked: boolean }) {
  const names: string[] = multiSecNames(S.prof)
  const setMode = (name: string, v: string) => act(() => {
    S.secMode = { ...S.secMode, [secKey(S.prof, name)]: v }
    log('희망 수집', `${S.prof} 교수님 ${name}: ${SECMODE[v]}`)
  })
  return (
    <div className="card">
      <h2>맡은 강의끼리</h2>
      <div className="row">
        <b style={{ minWidth: 120 }}>연강</b>
        <select aria-label="연강" disabled={locked} value={S.consec[S.prof] || 'any'} onChange={(e) => act(() => {
          S.consec[S.prof] = e.target.value
          log('희망 수집', `${S.prof} 교수님 연강: ${CONSN[e.target.value]}`)
        })}>
          {Object.entries(CONSN).map(([k, v]) => <option key={k} value={k}>{v as string}</option>)}
        </select>
        <span className="small muted">맡은 강의를 이어서 하는 것</span>
      </div>
      {names.map((name) => {
        const v = S.secMode[secKey(S.prof, name)] || 'any'
        return (
          <div key={name} className="row" style={{ marginTop: 8 }}>
            <b style={{ minWidth: 120 }}>{name} 분반</b>
            <select aria-label={`${name} 분반 배치`} disabled={locked} value={v} onChange={(e) => setMode(name, e.target.value)}>
              {Object.entries(SECMODE).map(([k, t]) => <option key={k} value={k}>{t as string}</option>)}
            </select>
            <span className="small muted">{SECMODE_TIP[v] || '두 분반을 따로 놓습니다'}</span>
          </div>
        )
      })}
    </div>
  )
}

export default function WishInput() {
  const locked = S.stage !== 'collect'
  const mineIds: string[] = S.claims.filter((x: any) => x.prof === S.prof).map((x: any) => x.cid)
  const ids: string[] = locked ? ACT().filter((c: any) => c.prof === S.prof).map((c: any) => c.id) : mineIds
  const forms = ids.map((id) => ({ c: C(id), x: claimOf(id, S.prof) }))
  const lost = locked ? mineIds.filter((id) => C(id).prof !== S.prof) : []
  const onClaim = (cid: string, on: boolean) =>
    act(() => {
      if (on) { if (!claimOf(cid, S.prof)) S.claims.push(mkClaim(cid, S.prof, emptyF())) }
      else {
        S.claims = S.claims.filter((y: any) => !(y.cid === cid && y.prof === S.prof))
        if (S.pick[cid] === S.prof) delete S.pick[cid]
      }
      sync()
      log('희망 수집', `${S.prof} 교수님이 ${full(C(cid))}을(를) ${on ? '골랐습니다' : '뺐습니다'}.`)
    })
  return (
    <>
      <h1 tabIndex={-1}>희망 입력</h1>
      <p className="lead">{S.prof} 교수님 · {locked ? `담당 확정 ${forms.length}개 · 읽기만 됩니다` : `고른 분반 ${forms.length}개 · 입력하면 바로 저장됩니다`}</p>
      <div className="card">
        <h2>2027-1학기 개설 과목</h2>
        <p className="small muted" style={{ margin: '-4px 0 10px' }}>
          {locked ? '접수가 마감되었습니다.' : '맡을 분반을 체크하면 아래에 희망 입력 칸이 생깁니다. 선착순이 아니며, 같은 분반을 여러 분이 고르면 학과사무실에서 정합니다.'}
        </p>
        <div className="tblwrap">
          <table>
            <tbody>
              <tr><th>과목</th><th>분반</th><th>학년</th><th>구분</th><th style={{ width: 80 }}>맡기</th></tr>
              {S.courses.map((c: any) => (
                <tr key={c.id}>
                  <td><b>{c.name}</b></td><td>{c.sec}</td><td>{c.year}</td><td>{kindOf(c)}</td>
                  <td>
                    <input type="checkbox" checked={mineIds.includes(c.id)} disabled={locked} aria-label={`${full(c)} 맡기`}
                      style={{ width: 18, height: 18, accentColor: 'var(--accent)' }} onChange={(e) => onClaim(c.id, e.target.checked)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {lost.length > 0 && <div className="note" style={{ marginBottom: 14 }}>{lost.map((id) => full(C(id))).join(', ')}: 학과사무실에서 다른 교수님으로 정했습니다.</div>}
      {!forms.length ? (
        <div className="card muted">{locked ? '담당 분반이 없습니다.' : '위 목록에서 맡을 분반을 골라 주세요.'}</div>
      ) : forms.length >= 2 && <ArrangeCard locked={locked} />}
      {forms.map(({ c, x }) => <WishForm key={c.id} c={c} x={x} locked={locked} />)}
    </>
  )
}
