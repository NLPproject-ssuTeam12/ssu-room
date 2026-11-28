// 조교·교수 페이지와 로그인 화면이 같이 쓰는 틀: 머리글, 진행 바, 왼쪽 메뉴, 불러오기 상태.
import type { ReactNode } from 'react'
import type { Stage } from '../api/types'
import { THEMES, applyTheme, savedTheme, toast } from '../ui'
import { ConfirmDialog, Toast } from '../components/Feedback'
import { loadAll } from './data'
import type { LoadState } from './data'

const STEPS: [Stage, string][] = [['COLLECT', '희망 수집'], ['DRAFT', '초안'], ['ROUND', '조율 중'], ['FINAL', '확정']]

export function StageBar({ stage, round }: { stage: Stage; round: number }) {
  const k = STEPS.findIndex(([s]) => s === stage)
  return (
    <ol className="steps" aria-label="진행 단계">
      {STEPS.map(([s, n], i) => (
        <li key={s} className={i < k ? 'done' : i === k ? 'now' : ''}>
          <span className="st" aria-current={i === k ? 'step' : undefined}>
            {n}
            {s === 'ROUND' && stage === 'ROUND' && <small>{round}차</small>}
            {i < k && <span className="sr"> (끝남)</span>}
          </span>
          {i < STEPS.length - 1 && <span className="ln" aria-hidden="true" />}
        </li>
      ))}
    </ol>
  )
}

export interface MenuItem<K extends string> {
  key: K
  label: string
  badge?: number
  badgeLabel?: string
}

interface SideMenuProps<K extends string> {
  items: MenuItem<K>[]
  current: K
  onPick: (k: K) => void
}

export function SideMenu<K extends string>({ items, current, onPick }: SideMenuProps<K>) {
  return (
    <nav aria-label="메뉴">
      {items.map((m) => (
        <button key={m.key} className={current === m.key ? 'on' : ''} aria-current={current === m.key ? 'page' : undefined} onClick={() => onPick(m.key)}>
          <span>{m.label}</span>
          {!!m.badge && <span className="badge new" aria-label={m.badgeLabel ?? `${m.badge}건`}>{m.badge}</span>}
        </button>
      ))}
    </nav>
  )
}

interface FrameProps {
  /** 머리글 오른쪽에 보일 로그인한 사람. 없으면 로그인 전 */
  user?: string
  onLogout?: () => void
  stage?: { stage: Stage; round: number } | null
  /** 왼쪽 메뉴. 없으면 본문만 가운데에 */
  nav?: ReactNode
  className?: string
  children: ReactNode
  /** 본문 밖에 띄우는 것 (패널, 떠 있는 버튼) */
  floating?: ReactNode
}

export function Frame({ user, onLogout, stage, nav, className, children, floating }: FrameProps) {
  const theme = savedTheme()
  const themeName = THEMES.find((x) => x[0] === theme)?.[1] ?? '시스템'
  const nextTheme = () => {
    const n = THEMES[(THEMES.findIndex((x) => x[0] === theme) + 1) % THEMES.length]
    applyTheme(n[0])
    toast(`테마: ${n[1]}`)
  }
  return (
    <div id="app" className={className}>
      <a className="skip" href="#main">본문으로 건너뛰기</a>
      <header className="top">
        <div className="wrap">
          <div className="logo">SSU<b>:</b>room</div>
          <span className="sub">강의시간표 편성·조율 도우미</span>
          <span className="virt" title="실제 강의 목록에 교수 가명과 가상 희망을 넣은 데이터">가명·가상 데이터</span>
          <div className="spacer" />
          <button type="button" className="tog" aria-label={`테마 바꾸기, 지금 ${themeName}`} onClick={nextTheme}>테마: {themeName}</button>
          {user && <span className="who">{user}</span>}
          {user && onLogout && <button type="button" className="btn small" onClick={onLogout}>로그아웃</button>}
        </div>
      </header>
      <div className="wrap">
        {stage && <StageBar stage={stage.stage} round={stage.round} />}
        {nav ? (
          <div className="main">
            {nav}
            <main id="main" tabIndex={-1}>{children}</main>
          </div>
        ) : (
          <main id="main" tabIndex={-1} className="solo">{children}</main>
        )}
      </div>
      {floating}
      <ConfirmDialog />
      <Toast />
    </div>
  )
}

/** 서버에서 불러오는 중이거나 실패했을 때 본문 */
export function LoadStatus({ load }: { load: Exclude<LoadState, { status: 'ready' }> }) {
  if (load.status === 'loading') return <div className="card muted">서버에서 불러오는 중…</div>
  return (
    <div className="card" role="alert">
      <h2>서버에 연결하지 못했습니다</h2>
      <p className="small">{load.error}</p>
      <p className="small muted">잠시 뒤 다시 시도하세요.</p>
      <button className="btn primary" onClick={() => void loadAll()}>다시 시도</button>
    </div>
  )
}
