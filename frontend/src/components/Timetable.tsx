import { C, D5, DAYN, PAT, ROOMS, S, SLOTS, endOf, full, isGenCell, livePreview, peekInfo } from '../mock/demo'
import { act } from '../store'
import { Chip } from './common'

type Props = { prof?: string; mine?: boolean; drawer?: boolean }
type Ghost = { cid: string; to: any; tag: string; bad: boolean }

/** 시간표 격자. prof가 있으면 교수 화면(내 강의 강조), drawer면 오른쪽 패널용 */
export default function Timetable({ prof, mine = false, drawer = false }: Props) {
  const pv = prof ? null : livePreview()
  const pk = prof ? null : peekInfo()
  const moving = new Set<string>([
    ...(pv ? pv.changes.map((x: any) => x.cid) : []),
    ...(pk && !pk.same ? [pk.cid] : []),
  ])
  const ghosts: Ghost[] = [
    ...(pv ? pv.changes.map((x: any) => ({ cid: x.cid, to: x.to, tag: 'AI 도우미 미리보기', bad: false })) : []),
    ...(pk
      ? [{
          cid: pk.cid,
          to: pk.to,
          tag: pk.same ? `${pk.k}안 = 지금 자리` : `${pk.k}안으로 옮기면${pk.hit ? ` · ${pk.hit.why}` : ''}`,
          bad: !!pk.hit,
        }]
      : []),
  ]
  const roomShown = (room: string) => S.room === 'all' || room === S.room
  const selId = `roomsel${drawer ? '-d' : ''}`

  const blocksAt = (d: number, i: number) =>
    S.courses.flatMap((c: any) => {
      const a = S.assign[c.id]
      if (!a || a.slot !== i) return []
      const k = PAT[a.pat].days.indexOf(d)
      if (k < 0 || (mine && c.prof !== prof)) return []
      const room = a.rooms[k]
      if (!roomShown(room)) return []
      const cls = [
        'blk',
        a.temp ? 'temp' : '',
        S.lastChanged.includes(c.id) ? 'changed' : '',
        moving.has(c.id) ? 'leave' : '',
        prof ? (c.prof === prof ? 'mine' : 'dim') : '',
      ].join(' ')
      return [
        <div key={c.id} className={cls}>
          <b>{full(c)}</b>
          {room}
          <br />
          <span className="muted">
            {c.prof} 교수 · {c.year}학년{c.req ? ' 전필' : ''}
            {a.temp ? ' · 조율 중' : ''}
            {moving.has(c.id) ? ' · 옮겨질 자리' : ''}
          </span>
        </div>,
      ]
    })

  const ghostsAt = (d: number, i: number) =>
    ghosts.flatMap((x, n) => {
      const k = PAT[x.to.pat].days.indexOf(d)
      if (x.to.slot !== i || k < 0) return []
      const room = x.to.rooms[k]
      if (!roomShown(room)) return []
      return [
        <div key={`g${n}`} className={`blk ghost${x.bad ? ' bad' : ''}`}>
          <b>→ {full(C(x.cid))}</b>
          {room}
          <br />
          <span>{x.tag}</span>
        </div>,
      ]
    })

  return (
    <>
      <div className="row" style={{ marginBottom: 10 }}>
        <label className="small muted" htmlFor={selId}>강의실</label>
        <select id={selId} value={S.room} onChange={(e) => act(() => { S.room = e.target.value })}>
          <option value="all">전체</option>
          {ROOMS.map((r: any) => <option key={r.id}>{r.id}</option>)}
        </select>
        <Chip k="warn">조율 중(임시 배치)</Chip>
        {S.lastChanged.length > 0 && <Chip k="good">방금 바뀜</Chip>}
        {prof && !mine && <Chip k="accent">내 강의</Chip>}
        {pv && <Chip k="accent">점선 = AI 도우미 미리보기 (적용 전)</Chip>}
        {pk && <Chip k="accent">점선 = {full(C(pk.cid))} {pk.k}안 미리 보기 (반영 전)</Chip>}
      </div>
      <div className="ttwrap">
        <div className="tt">
          <div />
          {D5.map((d: number) => <div key={d} className="h">{DAYN[d]}</div>)}
          {SLOTS.map((s: string, i: number) => [
            <div key={`t${i}`} className="t">
              {s}
              <br />
              <span>~{endOf(i)}</span>
            </div>,
            ...D5.map((d: number) => {
              const blks = blocksAt(d, i)
              const gs = ghostsAt(d, i)
              return (
                <div key={`${d}-${i}`} className="cell">
                  {blks}
                  {gs}
                  {isGenCell(d, i) && !blks.length && !gs.length && (
                    <div className="blk gen">
                      교양필수
                      <br />
                      <span className="small">가상 규칙</span>
                    </div>
                  )}
                </div>
              )
            }),
          ])}
        </div>
      </div>
    </>
  )
}
