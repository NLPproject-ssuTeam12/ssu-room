// 교수 페이지: 희망 입력 · 공개 시간표 · 조율 메시지. 로그인한 교수 한 명의 것만 보인다.
import { useState } from 'react'
import type { ServerData } from './data'
import { Frame, SideMenu } from './layout'
import type { MenuItem } from './layout'
import ProfWishes from './pages/ProfWishes'
import ProfTable from './pages/ProfTable'
import ProfMessages, { profItems } from './pages/ProfMessages'

type ProfView = 'pwish' | 'ptable' | 'pmsg'

export default function ProfApp({ data, prof, onLogout }: { data: ServerData; prof: string; onLogout: () => void }) {
  const [view, setView] = useState<ProfView>('pwish')
  const unanswered = profItems(data, prof).filter((c) => c.state === 'SENT').length

  const menu: MenuItem<ProfView>[] = [
    { key: 'pwish', label: '희망 입력' },
    { key: 'ptable', label: '공개 시간표' },
    { key: 'pmsg', label: '조율 메시지', badge: unanswered, badgeLabel: `답장할 메시지 ${unanswered}건` },
  ]

  return (
    <Frame
      user={`${prof} 교수님`}
      onLogout={onLogout}
      stage={{ stage: data.health.stage, round: data.health.round_no }}
      nav={<SideMenu items={menu} current={view} onPick={setView} />}
    >
      {view === 'pwish' && <ProfWishes data={data} prof={prof} />}
      {view === 'ptable' && <ProfTable data={data} prof={prof} />}
      {view === 'pmsg' && <ProfMessages data={data} prof={prof} />}
    </Frame>
  )
}
