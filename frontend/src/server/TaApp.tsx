// 조교 페이지: 희망 확인 · 시간표 · 조율 · 확정 · 설정, 오른쪽 현재 시간표 패널, AI 도우미.
import { useEffect, useState } from 'react'
import { getDialog } from '../ui'
import type { ServerData } from './data'
import { Frame, SideMenu } from './layout'
import type { MenuItem } from './layout'
import TimetablePanel from './TimetablePanel'
import AssistantPanel from './AssistantPanel'
import type { Turn } from './assistant'
import WishReview from './pages/WishReview'
import DraftView from './pages/DraftView'
import CoordView from './pages/CoordView'
import FinalView from './pages/FinalView'
import SettingsView from './pages/SettingsView'
import { groupCoord } from './coord'
import { pendingRequests } from './RequestConfirm'

type TaView = 'wishes' | 'timetable' | 'coord' | 'final' | 'settings'

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

export default function TaApp({ data, onLogout }: { data: ServerData; onLogout: () => void }) {
  const [view, setView] = useState<TaView>('wishes')
  const [ttOpen, setTtOpen] = useState(false)
  const [botOpen, setBotOpen] = useState(false)
  const [turns, setTurns] = useState<Turn[]>([])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !getDialog()) { setBotOpen(false); setTtOpen(false) } }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const canPanel = !!data.timetable && view !== 'timetable'
  const panelOn = canPanel && ttOpen
  const openBot = () => { setTtOpen(false); setBotOpen(true) }
  const openTt = () => { setBotOpen(false); setTtOpen(true) }
  const openTimetablePage = () => { setTtOpen(false); setView('timetable') }
  const todo = groupCoord(data.coord).todo.length
  const wishReqs = pendingRequests((data.requests ?? []).filter((r) => r.source === 'wish'))

  const menu: MenuItem<TaView>[] = [
    { key: 'wishes', label: '희망 확인', badge: wishReqs, badgeLabel: `기타 요청 미확인 ${wishReqs}건` },
    { key: 'timetable', label: '시간표' },
    { key: 'coord', label: '조율', badge: todo, badgeLabel: `할 일 ${todo}건` },
    { key: 'final', label: '확정·내보내기' },
    { key: 'settings', label: '설정' },
  ]

  const floating = (
    <>
      {panelOn && <TimetablePanel data={data} onClose={() => setTtOpen(false)} onOpenPage={openTimetablePage} />}
      {botOpen && <AssistantPanel stage={data.health.stage} turns={turns} setTurns={setTurns} onClose={() => setBotOpen(false)} />}
      <div className="fabs">
        {canPanel && !ttOpen && (
          <button className="ttfab" aria-label="현재 시간표 열기" onClick={openTt}>
            <span className="ic">{TT_ICON}</span>
            <span><b>현재 시간표</b><small>오른쪽에 열어 두고 보기</small></span>
          </button>
        )}
        {!botOpen && (
          <button className="botfab" aria-label="AI 도우미 열기" onClick={openBot}>
            <span className="ic">{BOT_ICON}</span>
            <span><b>AI 도우미</b><small>시간표를 말로 물어보기</small></span>
          </button>
        )}
      </div>
    </>
  )

  return (
    <Frame
      user="학과사무실 조교"
      onLogout={onLogout}
      stage={{ stage: data.health.stage, round: data.health.round_no }}
      className={[panelOn ? 'ttopen' : '', botOpen ? 'botopen' : ''].join(' ').trim()}
      nav={<SideMenu items={menu} current={view} onPick={setView} />}
      floating={floating}
    >
      {view === 'wishes' && <WishReview data={data} onDrafted={openTimetablePage} />}
      {view === 'timetable' && <DraftView data={data} onGoWishes={() => setView('wishes')} onGoCoord={() => setView('coord')} />}
      {view === 'coord' && <CoordView data={data} />}
      {view === 'final' && <FinalView data={data} />}
      {view === 'settings' && <SettingsView />}
    </Frame>
  )
}
