// 초안 공개 + 1차 / 다음 차수 시작 (서버 POST /rounds/next). DB 모드는 보내기 전 안건의 메시지를 자동으로 보낸다.
import { api } from '../api/client'
import type { RoundResult } from '../api/types'
import { askConfirm, toast } from '../ui'
import type { ServerData } from './data'
import { notCarried, roundStep } from './coord'
import { useRun } from './useRun'

interface Props {
  data: ServerData
  onDone?: () => void
}

export default function RoundButton({ data, onDone }: Props) {
  const r = useRun()
  const step = roundStep(data.health.stage, data.health.round_no)
  const left = data.health.stage === 'ROUND' ? notCarried(data.coord) : []
  const leftWarn = left.length
    ? `\n\n주의: 답장 대기·처리안 확인 중인 안건 ${left.length}개(${left.map((c) => c.name ?? c.section_id).join(', ')})는 다음 차수로 넘어가지 않습니다. 나중에 이 안건에서 조건이 생겨도 새 대안을 받지 못하니, 가능하면 먼저 정한 뒤 넘어가세요.`
    : ''
  const go = async () => {
    const out = await r.run<RoundResult>(() => api.nextRound())
    if (!out) return
    const sent = out.sent?.length ?? 0
    toast(`${out.round_no}차 조율을 시작했습니다 · 메시지 ${sent}건 보냄`)
    onDone?.()
  }
  const onClick = () => askConfirm({
    title: `${step.label}할까요?`,
    body: data.health.stage === 'DRAFT'
      ? '초안을 모든 교수님께 공개하고, 조율 대상 교수님께 1차 조율 메시지를 보냅니다.\n일부 어긋남·대안 없음 안건은 조교가 조율 화면에서 정합니다.'
      : `조건을 받은 안건에 새 대안을 만들어 다음 차수 메시지를 보냅니다.${leftWarn}`,
    ok: '시작',
  }, () => { void go() })
  return (
    <div className="card">
      <div className="row">
        <button className="btn primary" disabled={!step.enabled || r.busy} onClick={onClick}>{r.busy ? '진행 중…' : step.label}</button>
        <span className="small muted">{step.hint}</span>
      </div>
      {r.error && <p className="note" role="alert" style={{ background: 'var(--bad-soft)', marginTop: 8 }}>{r.error}</p>}
    </div>
  )
}
