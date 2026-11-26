// 조교: 설정 (서버 GET·POST /settings, POST /reset)
import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { Settings } from '../../api/types'
import { askConfirm, toast } from '../../ui'
import { useRun } from '../useRun'

const errorText = (e: unknown): string => (e instanceof Error ? e.message : '설정을 불러오지 못했습니다.')

function RevealCard() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    api.settings().then(setSettings).catch((e: unknown) => setError(errorText(e)))
  }, [])
  const toggle = async (reveal: boolean) => {
    setBusy(true)
    setError('')
    try {
      setSettings(await api.saveSettings({ reveal_opponent: reveal }))
      toast(reveal ? '상대 교수 이름을 알립니다' : '상대 교수 이름을 알리지 않습니다')
    } catch (e: unknown) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="card">
      <h2>조율 메시지</h2>
      {settings ? (
        <label className="small">
          <input type="checkbox" checked={settings.reveal_opponent} disabled={busy} onChange={(e) => void toggle(e.target.checked)} />{' '}
          겹친 상대 교수의 이름과 강의를 메시지에 알리기
        </label>
      ) : !error && <p className="small muted">불러오는 중…</p>}
      <p className="small muted" style={{ marginTop: 6 }}>다음에 쓰는 조율 메시지부터 적용됩니다.</p>
      {error && <p className="note" role="alert" style={{ background: 'var(--bad-soft)', marginTop: 8 }}>{error}</p>}
    </div>
  )
}

function ResetCard() {
  const r = useRun()
  const onClick = () => askConfirm({
    title: '처음부터 다시 할까요?',
    body: '초안·조율 기록·확정을 모두 지우고 희망 수집 단계로 돌아갑니다.\n교수님 희망, 과목, 강의실은 그대로 남습니다. 지운 기록은 되돌릴 수 없습니다.',
    ok: '처음부터 다시',
  }, () => { void r.run(() => api.reset(), '희망 수집 단계로 돌아갔습니다') })
  return (
    <div className="card" style={{ borderColor: 'var(--bad)' }}>
      <h2>처음부터 다시</h2>
      <p className="small muted">새로 편성할 때 씁니다. 시간표와 조율 기록을 지웁니다.</p>
      <button className="btn" disabled={r.busy} onClick={onClick}>{r.busy ? '지우는 중…' : '처음부터 다시'}</button>
      {r.error && <p className="note" role="alert" style={{ background: 'var(--bad-soft)', marginTop: 8 }}>{r.error}</p>}
    </div>
  )
}

export default function SettingsView() {
  return (
    <>
      <h1 tabIndex={-1}>설정</h1>
      <RevealCard />
      <ResetCard />
    </>
  )
}
