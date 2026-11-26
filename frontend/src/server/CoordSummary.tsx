// 조율 안건 한 개의 요약 (분반, 종류·상태, 이유, 지금 자리, 대안). 시간표 화면과 조율 화면이 같이 쓴다.
import type { ReactNode } from 'react'
import type { CoordItem, Section } from '../api/types'
import { Chip } from '../components/common'
import { condText } from './coord'
import { clearNotes } from './data'
import { COORD_KIND_LABEL, COORD_STATE_LABEL, altText } from './timetable'
import { sectionTitle } from './wish'

interface Props {
  c: CoordItem
  section: Section | undefined
  /** 이 분반에 남겨 둔 알림 (규칙 경고, 보내기 실패) */
  notes?: string[]
  children?: ReactNode
}

export default function CoordSummary({ c, section, notes = [], children }: Props) {
  const kind = c.kind ? COORD_KIND_LABEL[c.kind] ?? c.kind : null
  const prev = condText(c.prev_conditions)
  return (
    <div className="card" style={{ marginBottom: 10, padding: 14 }}>
      <b>{section ? sectionTitle(section) : (c.name ?? c.section_id)}</b>{' '}
      <span className="muted small">{c.professor ?? '담당 미정'} · {c.section_id} · {c.round_no}차</span>
      <div className="row" style={{ gap: 6, margin: '6px 0' }}>
        {kind && <Chip k={c.kind === 'UNPLACED' ? 'bad' : 'warn'}>{kind}</Chip>}
        <Chip>{COORD_STATE_LABEL[c.state] ?? c.state}</Chip>
        {prev && <Chip k="warn">지난 답장 조건 {prev}</Chip>}
      </div>
      {c.reason && <div className="small muted">{c.reason}</div>}
      {c.current && <div className="small" style={{ marginTop: 4 }}>지금 자리: {c.current}</div>}
      <div className="lbl">대안</div>
      {c.alternatives.length
        ? c.alternatives.map((a) => <div key={a.key} className="small">{a.key} · {altText(a)}</div>)
        : <div className="small muted">대안이 없습니다. 조교가 교수님과 따로 정해야 합니다.</div>}
      {c.message && (
        <details style={{ marginTop: 6 }}>
          <summary className="small">보낸 조율 메시지</summary>
          <p className="small" style={{ whiteSpace: 'pre-wrap' }}>{c.message}</p>
        </details>
      )}
      {notes.length > 0 && (
        <div className="note" role="status" style={{ background: 'var(--warn-soft)', marginTop: 8 }}>
          {notes.map((n, i) => <div key={i} className="small">{n}</div>)}
          <button className="btn small" style={{ marginTop: 6 }} onClick={() => clearNotes(c.section_id)}>확인함</button>
        </div>
      )}
      {children}
    </div>
  )
}
