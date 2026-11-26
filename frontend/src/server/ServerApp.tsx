// 서버 모드 화면 (기본). 가짜 데이터 시연은 주소 뒤에 ?demo (App.tsx).
// 연결된 화면: 조교 희망 확인·시간표·조율·확정·설정·AI 도우미, 교수 희망 입력·공개 시간표·조율 메시지.
import { useEffect, useState } from 'react'
import type { Stage } from '../api/types'
import { useVersion } from '../store'
import { THEMES, applyTheme, getDialog, savedTheme, toast } from '../ui'
import { ConfirmDialog, Toast } from '../components/Feedback'
import { loadAll, useServerData } from './data'
import type { ServerData } from './data'
import TimetablePanel from './TimetablePanel'
import AssistantPanel from './AssistantPanel'
import type { Turn } from './assistant'
import WishReview from './pages/WishReview'
import DraftView from './pages/DraftView'
import CoordView from './pages/CoordView'
import FinalView from './pages/FinalView'
import SettingsView from './pages/SettingsView'
import ProfWishes from './pages/ProfWishes'
import ProfTable from './pages/ProfTable'
import ProfMessages, { profItems } from './pages/ProfMessages'
import { groupCoord } from './coord'

type Role = 'ta' | 'prof'
type TaView = 'wishes' | 'timetable' | 'coord' | 'final' | 'settings'
type ProfView = 'pwish' | 'ptable' | 'pmsg'

const STEPS: [Stage, string][] = [['COLLECT', '희망 수집'], ['DRAFT', '초안'], ['ROUND', '조율 중'], ['FINAL', '확정']]
const TA_VIEWS: [TaView, string][] = [
  ['wishes', '희망 확인'], ['timetable', '시간표'], ['coord', '조율'], ['final', '확정·내보내기'], ['settings', '설정'],
]
const PROF_VIEWS: [ProfView, string][] = [['pwish', '희망 입력'], ['ptable', '공개 시간표'], ['pmsg', '조율 메시지']]

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

function StageBar({ stage, round }: { stage: Stage; round: number }) {
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

/** 자동 배정 분반이 있는 교수만, 이름 순 */
function profList(data: ServerData): string[] {
  const auto = new Set(data.sections.filter((s) => s.shape !== 'MANUAL').map((s) => s.id))
  return Object.entries(data.professors)
    .filter(([, v]) => v.sections.some((id) => auto.has(id)))
    .map(([p]) => p)
    .sort((a, b) => a.localeCompare(b, 'ko'))
}

export default function ServerApp() {
  useVersion() // 알림·테마가 바뀌면 다시 그린다
  const load = useServerData()
  const [role, setRole] = useState<Role>('ta')
  const [view, setView] = useState<TaView>('wishes')
  const [pview, setPview] = useState<ProfView>('pwish')
  const [prof, setProf] = useState('')
  const [ttOpen, setTtOpen] = useState(false)
  const [botOpen, setBotOpen] = useState(false)
  const [turns, setTurns] = useState<Turn[]>([])
  const theme = savedTheme()
  const themeName = THEMES.find((x) => x[0] === theme)?.[1] ?? '시스템'

  useEffect(() => { applyTheme(savedTheme()); void loadAll() }, [])
  useEffect(() => { document.title = 'SSU:room' }, [])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !getDialog()) { setBotOpen(false); setTtOpen(false) } }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const data = load.status === 'ready' ? load.data : null
  const profs = data ? profList(data) : []
  const curProf = profs.includes(prof) ? prof : (profs[0] ?? '')
  const isTA = role === 'ta'
  const canPanel = isTA && !!data?.timetable && view !== 'timetable'
  const panelOn = canPanel && ttOpen
  const botOn = isTA && botOpen
  const openBot = () => { setTtOpen(false); setBotOpen(true) }
  const openTt = () => { setBotOpen(false); setTtOpen(true) }

  const nextTheme = () => {
    const n = THEMES[(THEMES.findIndex((x) => x[0] === theme) + 1) % THEMES.length]
    applyTheme(n[0])
    toast(`테마: ${n[1]}`)
  }
  const openTimetablePage = () => { setTtOpen(false); setView('timetable') }
  // 메뉴 숫자: 조교 = 할 일, 교수 = 답장할 메시지
  const taBadge: Record<string, number> = { coord: data ? groupCoord(data.coord).todo.length : 0 }
  const profBadge: Record<string, number> = { pmsg: data ? profItems(data, curProf).filter((c) => c.state === 'SENT').length : 0 }

  return (
    <div id="app" className={[panelOn ? 'ttopen' : '', botOn ? 'botopen' : ''].join(' ').trim()}>
      <a className="skip" href="#main">본문으로 건너뛰기</a>
      <header className="top">
        <div className="wrap">
          <div className="logo">SSU<b>:</b>room</div>
          <span className="sub">강의시간표 편성·조율 도우미</span>
          <span className="virt" title="실제 강의 목록에 교수 가명과 가상 희망을 넣은 데이터">가명·가상 데이터</span>
          <div className="spacer" />
          <button type="button" className="tog" aria-label={`테마 바꾸기, 지금 ${themeName}`} onClick={nextTheme}>테마: {themeName}</button>
          <div className="seg" role="group" aria-label="역할">
            {([['ta', '조교'], ['prof', '교수']] as const).map(([r, t]) => (
              <button key={r} className={role === r ? 'on' : ''} aria-pressed={role === r} onClick={() => setRole(r)}>{t}</button>
            ))}
          </div>
          {!isTA && profs.length > 0 && (
            <select aria-label="교수 고르기" value={curProf} onChange={(e) => setProf(e.target.value)}>
              {profs.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          )}
        </div>
      </header>
      <div className="wrap">
        {data && <StageBar stage={data.health.stage} round={data.health.round_no} />}
        <div className="main">
          <nav aria-label="메뉴">
            {isTA ? (
              <>
                {TA_VIEWS.map(([k, t]) => (
                  <button key={k} className={view === k ? 'on' : ''} aria-current={view === k ? 'page' : undefined} onClick={() => setView(k)}>
                    <span>{t}</span>
                    {!!taBadge[k] && <span className="badge new" aria-label={`할 일 ${taBadge[k]}건`}>{taBadge[k]}</span>}
                  </button>
                ))}
              </>
            ) : (
              PROF_VIEWS.map(([k, t]) => (
                <button key={k} className={pview === k ? 'on' : ''} aria-current={pview === k ? 'page' : undefined} onClick={() => setPview(k)}>
                  <span>{t}</span>
                  {!!profBadge[k] && <span className="badge new" aria-label={`답장할 메시지 ${profBadge[k]}건`}>{profBadge[k]}</span>}
                </button>
              ))
            )}
          </nav>
          <main id="main" tabIndex={-1}>
            {load.status === 'loading' && <div className="card muted">서버에서 불러오는 중…</div>}
            {load.status === 'error' && (
              <div className="card" role="alert">
                <h2>서버에 연결하지 못했습니다</h2>
                <p className="small">{load.error}</p>
                <p className="small muted">잠시 뒤 다시 시도하세요.</p>
                <button className="btn primary" onClick={() => void loadAll()}>다시 시도</button>
              </div>
            )}
            {data && !isTA && pview === 'pwish' && <ProfWishes key={curProf} data={data} prof={curProf} />}
            {data && !isTA && pview === 'ptable' && <ProfTable key={curProf} data={data} prof={curProf} />}
            {data && !isTA && pview === 'pmsg' && <ProfMessages key={curProf} data={data} prof={curProf} />}
            {data && isTA && view === 'wishes' && <WishReview data={data} onDrafted={openTimetablePage} />}
            {data && isTA && view === 'timetable' && <DraftView data={data} onGoWishes={() => setView('wishes')} onGoCoord={() => setView('coord')} />}
            {data && isTA && view === 'coord' && <CoordView data={data} />}
            {data && isTA && view === 'final' && <FinalView data={data} />}
            {data && isTA && view === 'settings' && <SettingsView />}
          </main>
        </div>
      </div>
      {data && panelOn && <TimetablePanel data={data} onClose={() => setTtOpen(false)} onOpenPage={openTimetablePage} />}
      {data && botOn && <AssistantPanel stage={data.health.stage} turns={turns} setTurns={setTurns} onClose={() => setBotOpen(false)} />}
      {isTA && (
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
      )}
      <ConfirmDialog />
      <Toast />
    </div>
  )
}
