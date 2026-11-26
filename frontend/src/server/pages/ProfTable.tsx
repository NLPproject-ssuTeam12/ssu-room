// 교수: 공개 시간표 (서버 GET /timetable). 초안을 공개(1차 조율 시작)한 뒤부터 보인다.
import { useState } from 'react'
import type { ServerData } from '../data'
import TimetableGrid from '../TimetableGrid'

export default function ProfTable({ data, prof }: { data: ServerData; prof: string }) {
  const [mine, setMine] = useState(false)
  const tt = data.timetable
  const published = !!tt && (tt.stage === 'ROUND' || tt.stage === 'FINAL')
  return (
    <>
      <h1 tabIndex={-1}>공개 시간표</h1>
      {!published ? (
        <div className="card muted">학과사무실이 초안을 공개하면 여기에 시간표가 나옵니다.</div>
      ) : (
        <>
          <p className="lead">{tt.stage === 'FINAL' ? '확정한 시간표입니다.' : `${tt.round_no}차 조율 중인 시간표입니다. 노란 칸은 아직 조율 중입니다.`}</p>
          <div className="row" style={{ marginBottom: 10 }}>
            <label className="small">
              <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> 내 강의만 보기
            </label>
          </div>
          <div className="card"><TimetableGrid assignments={tt.assignments} sections={data.sections} prof={prof} mine={mine} /></div>
        </>
      )}
    </>
  )
}
