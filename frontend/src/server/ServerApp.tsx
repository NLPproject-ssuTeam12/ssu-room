// 화면 전체 (서버에 연결). 로그인 전에는 통합 로그인, 로그인하면 조교 페이지 또는 교수 페이지.
import { useEffect, useState } from 'react'
import { useVersion } from '../store'
import { applyTheme, savedTheme } from '../ui'
import { loadAll, useServerData } from './data'
import { startPolling } from './poll'
import { Frame, LoadStatus } from './layout'
import LoginPage from './LoginPage'
import TaApp from './TaApp'
import ProfApp from './ProfApp'
import { checkSession, loadSession, saveSession } from './session'
import type { Session } from './session'

export default function ServerApp() {
  useVersion() // 알림·테마가 바뀌면 다시 그린다
  const load = useServerData()
  const [session, setSession] = useState<Session | null>(() => loadSession())

  useEffect(() => { applyTheme(savedTheme()); void loadAll() }, [])
  useEffect(() => { document.title = 'SSU:room' }, [])
  useEffect(() => startPolling(), []) // 컴퓨터 2대 시연: 다른 컴퓨터에서 바꾼 것이 보이게

  const login = (s: Session | null) => {
    saveSession(s)
    setSession(s)
    window.scrollTo(0, 0)
  }
  const logout = () => login(null)

  if (load.status !== 'ready') return <Frame><LoadStatus load={load} /></Frame>

  const data = load.data
  const who = checkSession(session, data)
  if (!who) return <Frame><LoginPage data={data} onLogin={login} /></Frame>
  if (who.role === 'ta') return <TaApp data={data} onLogout={logout} />
  return <ProfApp key={who.prof} data={data} prof={who.prof} onLogout={logout} />
}
