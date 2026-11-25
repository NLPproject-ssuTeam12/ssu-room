// 조교: 설정 (서버 GET·POST /settings, POST /reset) + 서버 상태 보기 (/health)
import { useEffect, useState } from 'react'
import { API_BASE, api } from '../../api/client'
import type { Settings } from '../../api/types'
import { Chip } from '../../components/common'
import { askConfirm, toast } from '../../ui'
import type { ServerData } from '../data'
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
      <p className="small muted" style={{ marginTop: 6 }}>다음에 쓰는 조율 메시지부터 적용됩니다. 서버 메모리에만 저장되어 서버를 다시 켜면 기본값(알림)으로 돌아갑니다.</p>
      {error && <p className="note" role="alert" style={{ background: 'var(--bad-soft)', marginTop: 8 }}>{error}</p>}
    </div>
  )
}

function ServerCard({ data }: { data: ServerData }) {
  const h = data.health
  return (
    <div className="card">
      <h2>서버 상태</h2>
      <div className="row" style={{ marginBottom: 8 }}>
        <Chip>{API_BASE}</Chip>
        <Chip>데이터 {h.data_set}</Chip>
        <Chip>단계 {h.stage}{h.stage === 'ROUND' ? ` ${h.round_no}차` : ''}</Chip>
        <Chip>분반 {data.sections.length}개 · 강의실 {data.rooms.length}개</Chip>
      </div>
      <details>
        <summary className="small">배정·조율 함수 ({Object.values(h.engine).filter((v) => v !== 'stub').length}/{Object.keys(h.engine).length}개 진짜)</summary>
        <ul className="small">
          {Object.entries(h.engine).map(([k, v]) => <li key={k}><code>{k}</code> · {v === 'stub' ? <Chip k="warn">가짜</Chip> : v}</li>)}
        </ul>
      </details>
      {h.load_warnings.length > 0 && (
        <details style={{ marginTop: 6 }}>
          <summary className="small">데이터 읽기 경고 {h.load_warnings.length}건</summary>
          <ul className="small">{h.load_warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </details>
      )}
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
      <p className="small muted">시연을 다시 할 때 씁니다. 서버 DB의 시간표·조율 기록을 지웁니다.</p>
      <button className="btn" disabled={r.busy} onClick={onClick}>{r.busy ? '지우는 중…' : '처음부터 다시'}</button>
      {r.error && <p className="note" role="alert" style={{ background: 'var(--bad-soft)', marginTop: 8 }}>{r.error}</p>}
    </div>
  )
}

export default function SettingsView({ data }: { data: ServerData }) {
  return (
    <>
      <h1 tabIndex={-1}>설정</h1>
      <RevealCard />
      <ServerCard data={data} />
      <ResetCard />
    </>
  )
}
