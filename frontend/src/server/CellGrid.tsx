// 서버 모양(cells["월-09:00"] = "PREFER")의 시간 칠하기 격자와 작은 격자.
import { useEffect, useRef } from 'react'
import type { KeyboardEvent, PointerEvent } from 'react'
import { DAYS, STARTS } from '../api/types'
import type { CellKey, CellMark, Cells, Day, Start } from '../api/types'
import { MARK_CLASS, MARK_LABEL, cellKey, nextMark, withCell } from './wish'

const ARROWS: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }

const label = (m: CellMark | undefined): string => (m ? MARK_LABEL[m] : '가능')
const klass = (m: CellMark | undefined): string => (m ? MARK_CLASS[m] : '')

interface PaintGridProps {
  id: string
  title: string
  cells: Cells
  locked: boolean
  onChange: (cells: Cells) => void
}

/** 누르면 희망 → 불가 → 빈칸, 끌면 같은 값으로 여러 칸을 칠한다 */
export function PaintGrid({ id, title, cells, locked, onChange }: PaintGridProps) {
  // 끌기 중에는 최신 cells를 ref로 읽는다 (그리는 사이 props가 늦게 올 수 있다)
  const latest = useRef(cells)
  latest.current = cells
  const painting = useRef<{ mark: CellMark | null; last: CellKey } | null>(null)

  const paint = (key: CellKey, mark: CellMark | null) => {
    const next = withCell(latest.current, key, mark)
    latest.current = next
    onChange(next)
  }

  useEffect(() => {
    const onMove = (e: globalThis.PointerEvent) => {
      const p = painting.current
      if (!p) return
      const el = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLButtonElement>('[data-cell]')
      if (!el || el.disabled || el.dataset.grid !== id) return
      const key = el.dataset.cell as CellKey
      if (key === p.last) return
      p.last = key
      paint(key, p.mark)
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

  const start = (key: CellKey) => {
    const mark = nextMark(latest.current[key])
    painting.current = { mark, last: key }
    paint(key, mark)
  }
  const onPointerDown = (e: PointerEvent, key: CellKey) => {
    e.preventDefault()
    start(key)
  }
  // 키보드(Enter·Space)는 click으로만 온다. 마우스는 pointerdown에서 이미 처리했다
  const onClick = (detail: number, key: CellKey) => {
    if (detail !== 0) return
    start(key)
    painting.current = null
  }
  const onKeyDown = (e: KeyboardEvent) => {
    const el = (e.target as HTMLElement).closest<HTMLButtonElement>('[data-cell]')
    const mv = ARROWS[e.key]
    if (!el || !mv) return
    e.preventDefault()
    const d = DAYS.indexOf(el.dataset.day as Day) + mv[0]
    const s = STARTS.indexOf(el.dataset.start as Start) + mv[1]
    if (d < 0 || d >= DAYS.length || s < 0 || s >= STARTS.length) return
    document.querySelector<HTMLButtonElement>(`[data-grid="${id}"][data-cell="${cellKey(DAYS[d], STARTS[s])}"]`)?.focus()
  }

  return (
    <div className="pg" role="group" aria-label={`${title} 수업 가능 시간 (화살표로 이동)`} onKeyDown={onKeyDown}>
      <div />
      {DAYS.map((d) => <div key={d} className="pgh">{d}</div>)}
      {STARTS.map((t) => [
        <div key={`t${t}`} className="pgt">{t}</div>,
        ...DAYS.map((d) => {
          const key = cellKey(d, t)
          const m = cells[key]
          return (
            <button key={key} type="button" className={`pc ${klass(m)}`} disabled={locked}
              data-grid={id} data-cell={key} data-day={d} data-start={t} aria-label={`${d} ${t} ${label(m)}`}
              onPointerDown={(e) => onPointerDown(e, key)} onClick={(e) => onClick(e.detail, key)}>
              {m ? MARK_LABEL[m] : ''}
            </button>
          )
        }),
      ])}
    </div>
  )
}

/** 희망을 작은 격자로 (요일 × 교시) */
export function MiniGrid({ cells }: { cells: Cells }) {
  return (
    <div className="mm" aria-hidden="true">
      <span />
      {DAYS.map((d) => <span key={d}>{d}</span>)}
      {STARTS.map((t) => [
        <span key={`t${t}`}>{t.slice(0, 2)}</span>,
        ...DAYS.map((d) => {
          const m = cells[cellKey(d, t)]
          return <span key={`${d}-${t}`} className={`mc ${klass(m)}`} title={`${d} ${t} ${label(m)}`} />
        }),
      ])}
    </div>
  )
}

export function CellLegend() {
  return (
    <div className="legend">
      <span><i className="m-want" />희망</span>
      <span><i className="m-no" />불가</span>
      <span><i />가능 (안 칠함)</span>
    </div>
  )
}
