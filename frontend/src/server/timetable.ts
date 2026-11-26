// 시간표 격자에 수업을 놓는 순수 함수 (timetable.test.ts).
// 격자는 월~금 × 8교시. 토요일·다른 시각(16:00 등)에 놓인 직접 배정 수업은 격자 밖 목록으로 따로 보여 준다.
import { DAYS, STARTS } from '../api/types'
import type { Alternative, Assignment, AssignmentStatus, Block, Day, Meeting } from '../api/types'

const LESSON_MIN = 75
const BREAK_MIN = 15

/** 격자 한 칸에 놓이는 수업 한 조각. 연강(slots 2)은 두 칸에 나뉘어 들어가고 둘째 칸은 cont = true */
export interface Placed {
  sectionId: string
  status: AssignmentStatus
  room: string | null
  cont: boolean
}

export interface OffGrid {
  sectionId: string
  status: AssignmentStatus
  block: Block
}

export interface GridLayout {
  /** key = "요일|교시 번호" */
  cells: Map<string, Placed[]>
  offGrid: OffGrid[]
  /** 수업이 하나도 없는 분반 (못 놓음·직접 배정 미정) */
  empty: Assignment[]
}

export const gridKey = (day: Day, slot: number): string => `${day}|${slot}`

const isDay = (d: string): d is Day => (DAYS as readonly string[]).includes(d)

/** 강의실 고르기: 'all'이면 전부, 아니면 그 강의실 수업만 */
export function layoutGrid(assignments: Assignment[], room = 'all'): GridLayout {
  const cells = new Map<string, Placed[]>()
  const offGrid: OffGrid[] = []
  const empty: Assignment[] = []
  for (const a of assignments) {
    if (!a.blocks.length) { empty.push(a); continue }
    for (const b of a.blocks) {
      const r = b.room ?? a.room
      if (room !== 'all' && r !== room) continue
      const slot = (STARTS as readonly string[]).indexOf(b.start)
      if (!isDay(b.day) || slot < 0) { offGrid.push({ sectionId: a.section_id, status: a.status, block: b }); continue }
      const span = Math.min(Math.max(b.slots, 1), STARTS.length - slot)
      for (let i = 0; i < span; i++) {
        const key = gridKey(b.day, slot + i)
        cells.set(key, [...(cells.get(key) ?? []), { sectionId: a.section_id, status: a.status, room: r, cont: i > 0 }])
      }
    }
  }
  return { cells, offGrid, empty }
}

const toMin = (t: string): number => {
  const [h, m] = t.split(':').map(Number)
  return h * 60 + m
}
const toHM = (v: number): string => `${String(Math.floor(v / 60)).padStart(2, '0')}:${String(v % 60).padStart(2, '0')}`

/** 수업 하나를 글로: "월 09:00~11:45 정보과학관 21305" (연강은 쉬는 시간 포함) */
export function blockText(b: Block): string {
  const end = toHM(toMin(b.start) + LESSON_MIN * b.slots + BREAK_MIN * (b.slots - 1))
  return `${b.day} ${b.start}~${end}${b.room ? ` ${b.room}` : ''}`
}

/** 조율 대안의 수업(요일 숫자)을 글로: "월 09:00~10:15 정보과학관 21501" */
export function meetingText(m: Meeting): string {
  return `${DAYS[m.day] ?? `?${m.day}`} ${m.start}~${m.end} ${m.room}`
}

export const altText = (a: Alternative): string => a.meetings.map(meetingText).join(' / ')

export function countStatus(assignments: Assignment[]): Record<AssignmentStatus, number> {
  const out: Record<AssignmentStatus, number> = { DONE: 0, COORD: 0, MANUAL: 0 }
  for (const a of assignments) out[a.status] += 1
  return out
}

/** 강의실 고르기 목록: 시간표에 실제로 쓰인 강의실, 이름 순 */
export function usedRooms(assignments: Assignment[]): string[] {
  const set = new Set<string>()
  for (const a of assignments) {
    for (const b of a.blocks) {
      const r = b.room ?? a.room
      if (r) set.add(r)
    }
  }
  return [...set].sort((x, y) => x.localeCompare(y, 'ko'))
}

export const COORD_KIND_LABEL: Record<string, string> = { UNPLACED: '못 놓음', MISMATCH: '희망에서 어긋남', PARTIAL: '일부 어긋남' }
export const COORD_STATE_LABEL: Record<string, string> = {
  OPEN: '보내기 전', HOLD: '조교 선택 대기', NO_OPTION: '대안 없음', SENT: '답장 대기', PROPOSED: '처리안 확인',
  NEXT: '다음 차수로', RESOLVED: '정해짐', KEPT: '지금 자리 유지', OFFLINE: '따로 연락',
}
