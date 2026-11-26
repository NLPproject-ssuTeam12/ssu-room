import { useEffect } from 'react'
import type { ComponentType } from 'react'
import { PROFS, S, navItems } from './mock/demo'
import { act, useVersion } from './store'
import { THEMES, applyTheme, getDialog, savedTheme, toast } from './ui'
import StepsBar from './components/StepsBar'
import { ConfirmDialog, Toast } from './components/Feedback'
import Home from './pages/ta/Home'
import Wishes from './pages/ta/Wishes'
import Draft from './pages/ta/Draft'
import Coord from './pages/ta/Coord'
import Final from './pages/ta/Final'
import Settings from './pages/ta/Settings'
import WishInput from './pages/prof/WishInput'
import PublicTable from './pages/prof/PublicTable'
import Messages from './pages/prof/Messages'
import AssistantPanel from './panels/AssistantPanel'
import TimetablePanel from './panels/TimetablePanel'

const go = (v: string) => act(() => { S.view = v })
const WishesPage = () => <Wishes go={go} />

const VIEWS: Record<string, ComponentType> = {
  home: Home, wishes: WishesPage, draft: Draft, coord: Coord, final: Final, settings: Settings,
  pwish: WishInput, ptable: PublicTable, pmsg: Messages,
}

const TT_ICON = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="4" width="18" height="17" rx="2" /><path d="M3 9h18M8 4v17M13 4v17" />
  </svg>
)
const BOT_ICON = (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" /><path d="M8.5 12h.01M12 12h.01M15.5 12h.01" />
  </svg>
)

const focusSoon = (sel: string) => setTimeout(() => document.querySelector<HTMLElement>(sel)?.focus(), 0)
const closeBot = () => { act(() => { S.botOpen = false }); focusSoon('.botfab') }
const closeTT = () => { act(() => { S.ttOpen = false }); focusSoon('.ttfab') }

export default function App() {
  useVersion()
  const isTA = S.role === 'ta'
  // 확정 화면을 보면 새 확정 회신은 읽은 것으로 (메뉴 숫자가 꺼진다)
  if (isTA && S.view === 'final') S.confirms.forEach((k: any) => { if (k.reply) k.seen = true })
  const items: [string, string, number?][] = navItems()
  if (!items.some((i) => i[0] === S.view)) S.view = items[0][0]
  const View = VIEWS[S.view]
  const showTT = isTA && S.stage !== 'collect' && S.view !== 'draft'
  const badgeN = items.reduce((v, x) => v + (x[2] || 0), 0)
  const theme = savedTheme()
  const themeName = THEMES.find((x) => x[0] === theme)?.[1] ?? '시스템'

  useEffect(() => {
    document.title = `${badgeN && isTA ? `(${badgeN}) ` : ''}SSU:room`
  }, [badgeN, isTA])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || getDialog() || S.role !== 'ta') return
      if (S.botOpen) closeBot()
      else if (S.ttOpen) closeTT()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  // 처음 그릴 때 저장된 테마 적용
  useEffect(() => { applyTheme(savedTheme()) }, [])

  const nextTheme = () => {
    const k = THEMES.findIndex((x) => x[0] === theme)
    const n = THEMES[(k + 1) % THEMES.length]
    applyTheme(n[0])
    toast(`테마: ${n[1]}`)
  }
  const setRole = (r: string) => act(() => { S.role = r; S.view = r === 'ta' ? 'home' : 'pwish' })
  const appClass = [isTA && S.botOpen ? 'botopen' : '', showTT && S.ttOpen ? 'ttopen' : ''].join(' ').trim()

  return (
    <div id="app" className={appClass}>
      <a className="skip" href="#main">본문으로 건너뛰기</a>
      <header className="top">
        <div className="wrap">
          <div className="logo">SSU<b>:</b>room</div>
          <span className="sub">강의시간표 편성·조율 도우미</span>
          <span className="virt">가상 데이터</span>
          <div className="spacer" />
          <button type="button" className="tog" aria-label={`테마 바꾸기, 지금 ${themeName}`} onClick={nextTheme}>테마: {themeName}</button>
          <div className="seg" role="group" aria-label="역할">
            {([['ta', '조교'], ['prof', '교수']] as const).map(([r, t]) => (
              <button key={r} className={S.role === r ? 'on' : ''} aria-pressed={S.role === r} onClick={() => setRole(r)}>{t}</button>
            ))}
          </div>
          {!isTA && (
            <select aria-label="교수 고르기" value={S.prof} onChange={(e) => act(() => { S.prof = e.target.value })}>
              {PROFS.map((p: string) => <option key={p} value={p}>{p} 교수</option>)}
            </select>
          )}
        </div>
      </header>
      <div className="wrap">
        <StepsBar />
        <div className="main">
          <nav aria-label="메뉴">
            {items.map(([k, t, n]) => (
              <button key={k} className={S.view === k ? 'on' : ''} aria-current={S.view === k ? 'page' : undefined} onClick={() => go(k)}>
                <span>{t}</span>
                {!!n && <span className={`badge${k === 'coord' || k === 'final' || k === 'pmsg' ? ' new' : ''}`} aria-label={`${n}건`}>{n}</span>}
              </button>
            ))}
          </nav>
          <main id="main" tabIndex={-1}>
            <View key={`${S.view}-${S.role}-${S.prof}`} />
          </main>
        </div>
      </div>
      {showTT && S.ttOpen && <TimetablePanel onClose={closeTT} />}
      {isTA && (
        <>
          <div className="fabs">
            {showTT && !S.ttOpen && (
              <button className="ttfab" aria-label="현재 시간표 열기" onClick={() => act(() => { S.ttOpen = true; S.botOpen = false })}>
                <span className="ic">{TT_ICON}</span>
                <span><b>현재 시간표</b><small>오른쪽에 열어 두고 보기</small></span>
              </button>
            )}
            {!S.botOpen && (
              <button className={`botfab${S.botSeen ? '' : ' new'}`} aria-label="AI 도우미 열기"
                onClick={() => act(() => { S.botOpen = true; S.ttOpen = false; S.botSeen = true })}>
                <span className="ic">{BOT_ICON}</span>
                <span><b>AI 도우미</b><small>시간표를 말로 물어보기</small></span>
              </button>
            )}
          </div>
          {S.botOpen && <AssistantPanel onClose={closeBot} />}
        </>
      )}
      <ConfirmDialog />
      <Toast />
    </div>
  )
}
