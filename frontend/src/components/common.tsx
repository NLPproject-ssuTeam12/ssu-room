import type { ReactNode } from 'react'
import { D5, DAYN, MARKS, SLOTS, fChips, mcls, mk } from '../mock/demo'

export function Chip({ k = '', children }: { k?: string; children: ReactNode }) {
  return <span className={`chip ${k}`}>{children}</span>
}

const STUB_TIP =
  '시연 화면은 언어 모델·배정 엔진을 부르지 않고 키워드 규칙으로 흉내 냅니다. 실제 값의 모양은 API 명세와 같습니다.'

/** 시연용 흉내 표시. 2단계(서버 연결)에서 지운다 */
export function Stub({ text = '시연용 흉내', tip = STUB_TIP }: { text?: string; tip?: string }) {
  return (
    <span className="stub" title={tip} tabIndex={0}>
      {text}
    </span>
  )
}

export function Legend() {
  return (
    <div className="legend">
      {MARKS.map((m: string) => (
        <span key={m}>
          <i className={mcls(m)} />
          {m}
        </span>
      ))}
      <span>
        <i />
        가능 (안 칠함)
      </span>
      <span>
        <i className="blocked" />
        고를 수 없음 (교양필수·채플)
      </span>
    </div>
  )
}

/** 희망을 작은 격자로 (요일 × 교시) */
export function MiniMap({ f }: { f: any }) {
  return (
    <div className="mm" aria-hidden="true">
      <span />
      {D5.map((d: number) => (
        <span key={d}>{DAYN[d]}</span>
      ))}
      {SLOTS.map((t: string, k: number) => [
        <span key={`t${k}`}>{t.slice(0, 2)}</span>,
        ...D5.map((d: number) => {
          const m = mk(f, d, k)
          return <span key={`${d}-${k}`} className={`mc ${mcls(m)}`} title={`${DAYN[d]} ${t} ${m || '가능'}`} />
        }),
      ])}
    </div>
  )
}

/** 접수한 희망을 칩으로 */
export function WishChips({ f, prof }: { f: any; prof?: string | null }) {
  return (
    <>
      {fChips(f, prof).map(([t, k]: [string, string]) => (
        <Chip key={t} k={k}>
          {t}
        </Chip>
      ))}
    </>
  )
}
