import { S, altLabel } from '../mock/demo'
import { act } from '../store'

/** 조율 대안을 시간표에 점선으로 미리 보기. 시간표 화면이 아니면 오른쪽 '현재 시간표' 패널을 연다 */
export function togglePeek(mid: string, k: string): void {
  act(() => {
    const on = !!S.peek && S.peek.m === mid && S.peek.k === k
    S.peek = on ? null : { m: mid, k }
    if (!on && S.view !== 'draft') {
      S.ttOpen = true
      S.botOpen = false
    }
  })
}

export default function PeekBtns({ m }: { m: any }) {
  return (
    <div className="row" style={{ gap: 6, marginTop: 8 }}>
      <span className="small muted">시간표에서 보기</span>
      {m.alts.map((a: any) => {
        const on = !!S.peek && S.peek.m === m.id && S.peek.k === a.k
        return (
          <button key={a.k} type="button" className="tog" aria-pressed={on} title={altLabel(a)} onClick={() => togglePeek(m.id, a.k)}>
            {a.k}안
          </button>
        )
      })}
    </div>
  )
}
