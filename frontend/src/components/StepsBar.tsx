import { S, stageIdx } from '../mock/demo'

const NAMES = ['희망 수집', '초안', '조율 중', '확정']

function subLabel(i: number): string {
  if (i === 2 && S.stage === 'round') return `${S.round}차`
  if (i === 3 && S.stage === 'confirm') return `${S.confirms.filter((x: any) => x.reply).length}/${S.confirms.length}`
  if (i === 3 && S.stage === 'review') return '요청 전'
  return ''
}

/** 진행 바: 희망 수집 ── 초안 ── 조율 중 ── 확정 */
export default function StepsBar() {
  const k = stageIdx()
  return (
    <ol className="steps" aria-label="진행 단계">
      {NAMES.map((n, i) => {
        const sub = subLabel(i)
        return (
          <li key={n} className={i < k ? 'done' : i === k ? 'now' : ''}>
            <span className="st" aria-current={i === k ? 'step' : undefined}>
              {n}
              {sub && <small>{sub}</small>}
              {i < k && <span className="sr"> (끝남)</span>}
            </span>
            {i < NAMES.length - 1 && <span className="ln" aria-hidden="true" />}
          </li>
        )
      })}
    </ol>
  )
}
