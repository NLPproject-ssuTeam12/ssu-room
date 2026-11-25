// 서버 시간표(GET /timetable)를 요일 × 교시 격자로 그린다. 조교 시간표 화면과 오른쪽 패널이 같이 쓴다.
import { useState } from 'react'
import { DAYS, STARTS } from '../api/types'
import type { Assignment, Section } from '../api/types'
import { Chip } from '../components/common'
import { blockText, gridKey, layoutGrid, usedRooms } from './timetable'
import type { Placed } from './timetable'
import { sectionTitle } from './wish'

const STATUS_CLASS: Record<string, string> = { COORD: 'temp', MANUAL: 'manual', DONE: '' }
const endOf = (t: string): string => {
  const [h, m] = t.split(':').map(Number)
  const v = h * 60 + m + 75
  return `${String(Math.floor(v / 60)).padStart(2, '0')}:${String(v % 60).padStart(2, '0')}`
}

interface Props {
  assignments: Assignment[]
  sections: Section[]
  /** 오른쪽 패널용 (강의실 고르기 id만 다르게) */
  drawer?: boolean
  /** 교수 화면: 이 교수의 강의를 강조하고, mine이면 그 강의만 */
  prof?: string
  mine?: boolean
}

export default function TimetableGrid({ assignments, sections, drawer = false, prof, mine = false }: Props) {
  const [room, setRoom] = useState('all')
  const byId = new Map(sections.map((s) => [s.id, s]))
  const title = (id: string) => { const s = byId.get(id); return s ? sectionTitle(s) : id }
  const isMine = (id: string) => !!prof && byId.get(id)?.professor === prof
  const shown = prof && mine ? assignments.filter((a) => isMine(a.section_id)) : assignments
  const { cells, offGrid, empty } = layoutGrid(shown, room)
  const rooms = usedRooms(assignments)
  const selId = `roomsel-server${drawer ? '-d' : ''}`

  const Blk = ({ p }: { p: Placed }) => {
    const s = byId.get(p.sectionId)
    return (
      <div className={`blk ${STATUS_CLASS[p.status] ?? ''}${prof ? (isMine(p.sectionId) ? ' mine' : ' dim') : ''}`}>
        <b>{title(p.sectionId)}{p.cont ? ' (이어서)' : ''}</b>
        {!p.cont && <>{p.room ?? '강의실 미정'}<br /></>}
        <span className="muted">
          {s?.professor ?? '담당 미정'}{s?.year ? ` · ${s.year}학년` : ''}
          {p.status === 'COORD' ? ' · 조율 중' : p.status === 'MANUAL' ? ' · 직접 배정' : ''}
        </span>
      </div>
    )
  }

  return (
    <>
      <div className="row" style={{ marginBottom: 10 }}>
        <label className="small muted" htmlFor={selId}>강의실</label>
        <select id={selId} value={room} onChange={(e) => setRoom(e.target.value)}>
          <option value="all">전체</option>
          {rooms.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <Chip k="warn">조율 중(임시 배치)</Chip>
        <Chip>직접 배정</Chip>
        {prof && !mine && <Chip k="accent">내 강의</Chip>}
      </div>
      <div className="ttwrap">
        <div className="tt">
          <div />
          {DAYS.map((d) => <div key={d} className="h">{d}</div>)}
          {STARTS.map((t, i) => [
            <div key={`t${t}`} className="t">{t}<br /><span>~{endOf(t)}</span></div>,
            ...DAYS.map((d) => (
              <div key={`${d}-${t}`} className="cell">
                {(cells.get(gridKey(d, i)) ?? []).map((p, n) => <Blk key={`${p.sectionId}-${n}`} p={p} />)}
              </div>
            )),
          ])}
        </div>
      </div>
      {offGrid.length > 0 && (
        <details style={{ marginTop: 12 }}>
          <summary className="small"><b>격자 밖 수업 {offGrid.length}개</b> <span className="muted">토요일이나 교시와 다른 시각 (직접 배정)</span></summary>
          <ul className="small">
            {offGrid.map((o, n) => <li key={`${o.sectionId}-${n}`}>{title(o.sectionId)} · {blockText(o.block)}</li>)}
          </ul>
        </details>
      )}
      {empty.length > 0 && room === 'all' && (
        <details style={{ marginTop: 8 }}>
          <summary className="small"><b>자리가 없는 분반 {empty.length}개</b> <span className="muted">못 놓았거나 직접 배정 시간이 없음</span></summary>
          <ul className="small">
            {empty.map((a) => <li key={a.section_id}>{title(a.section_id)} · {a.status === 'COORD' ? `조율 대상${a.reason ? ` (${a.reason})` : ''}` : '직접 배정'}</li>)}
          </ul>
        </details>
      )}
    </>
  )
}
