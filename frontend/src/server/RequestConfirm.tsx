// 조교: 교수가 '기타'에 쓴 요청을 읽고 [확인함] (서버 GET /requests, POST /requests/{id}/confirm).
// 배정 엔진은 기타 요청을 읽지 않으므로 조교가 직접 처리하고 메모를 남긴다.
import { useState } from 'react'
import type { OtherRequest } from '../api/types'
import { Chip } from '../components/common'
import { toast } from '../ui'
import type { ServerData } from './data'
import { confirmRequest } from './data'

const errorText = (e: unknown): string => (e instanceof Error ? e.message : '확인하지 못했습니다.')

/** 미확인 기타 요청 수 (메뉴 배지) */
export const pendingRequests = (requests: OtherRequest[] | null): number =>
  (requests ?? []).filter((r) => r.status === 'PENDING').length

/** 요청 하나: 상태, 메모 칸, [확인함] 또는 [메모 저장] */
export function RequestConfirm({ req }: { req: OtherRequest }) {
  const [memo, setMemo] = useState(req.ta_memo ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const done = req.status === 'CONFIRMED'
  const unchanged = done && memo.trim() === (req.ta_memo ?? '').trim()

  const onConfirm = async () => {
    setBusy(true)
    setError('')
    try {
      await confirmRequest(req.id, memo)
      toast(done ? '메모를 저장했습니다' : '기타 요청을 확인했습니다')
    } catch (e: unknown) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="reqbox">
      <Chip k={done ? 'good' : 'warn'}>{done ? '확인함' : '미확인'}</Chip>
      <div className="row" style={{ marginTop: 6, gap: 6 }}>
        <input type="text" aria-label={`메모, ${req.course ?? req.section_id}`} placeholder="메모 (선택) 예: 대강 일정 받음"
          value={memo} disabled={busy} maxLength={200} onChange={(e) => setMemo(e.target.value)} />
        <button className={`btn small ${done ? '' : 'primary'}`} disabled={busy || unchanged} onClick={onConfirm}>
          {busy ? '저장 중…' : done ? '메모 저장' : '확인함'}
        </button>
      </div>
      {error && <p className="small bad-text" role="alert" style={{ margin: '4px 0 0' }}>{error}</p>}
    </div>
  )
}

/** 조율 답장에서 '기타'로 받은 시간표 밖 요청 (조율 화면 위) */
export function ReplyRequests({ data }: { data: ServerData }) {
  const list = (data.requests ?? []).filter((r) => r.source === 'reply')
  if (!list.length) return null
  const pending = list.filter((r) => r.status === 'PENDING').length
  return (
    <div className="card">
      <h2>답장의 기타 요청 <span className="small muted">{list.length}건 · 미확인 {pending}건 · 시간표 밖 요청이라 조교가 직접 처리합니다</span></h2>
      {list.map((r) => (
        <div key={r.id} className="reqrow">
          <div><b>{r.course ?? r.section_id}</b> <span className="small muted">{r.professor ?? ''}</span></div>
          <div className="small">{r.body}</div>
          <RequestConfirm req={r} />
        </div>
      ))}
    </div>
  )
}
