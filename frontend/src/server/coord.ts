// 조율 화면이 쓰는 순수 함수 (coord.test.ts). 답장 검사 규칙은 서버 main.py _check_reply와 같다.
import { DAYS, STARTS } from '../api/types'
import type { Conditions, CoordItem, Meeting, ReplyChoice, Stage } from '../api/types'

export const MAX_ROUND = 3
const LESSON_MIN = 75
const BREAK_MIN = 15

// ---------- 안건 묶기 ----------

const TODO_STATES = ['OPEN', 'HOLD', 'NO_OPTION', 'PROPOSED', 'OFFLINE']
const WAIT_STATES = ['SENT']

export interface CoordGroups {
  todo: CoordItem[]
  waiting: CoordItem[]
  done: CoordItem[]
}

/** 조교가 할 일 / 교수 답장 대기 / 끝남(다음 차수로·정해짐·유지) */
export function groupCoord(items: CoordItem[]): CoordGroups {
  return {
    todo: items.filter((c) => TODO_STATES.includes(c.state)),
    waiting: items.filter((c) => WAIT_STATES.includes(c.state)),
    done: items.filter((c) => !TODO_STATES.includes(c.state) && !WAIT_STATES.includes(c.state)),
  }
}

// ---------- 차수 ----------

export interface RoundStep {
  label: string
  enabled: boolean
  hint: string
}

/** 다음 차수 버튼: 초안 → 1차(공개), 1·2차 → 다음 차수, 3차 → 더 없음 */
export function roundStep(stage: Stage, round: number): RoundStep {
  if (stage === 'DRAFT') return { label: '초안 공개 + 1차 조율 시작', enabled: true, hint: '조율 메시지는 보내기 전 안건에 자동으로 나갑니다.' }
  if (stage === 'ROUND' && round < MAX_ROUND) {
    return { label: `${round + 1}차 조율 시작`, enabled: true, hint: '조건을 받은 안건(다음 차수로)에 새 대안을 만들어 보냅니다.' }
  }
  if (stage === 'ROUND') return { label: `${MAX_ROUND}차가 마지막입니다`, enabled: false, hint: '남은 분반은 조교가 정한 뒤 확정합니다.' }
  return { label: '다음 차수 없음', enabled: false, hint: '' }
}

// ---------- 교수 답장 ----------

const ALT_KEYS: ReplyChoice[] = ['A', 'B', 'C']

/** 답장 버튼 누르기. '지금 자리 그대로'(KEEP)는 A·B·C와 같이 고를 수 없어서 서로 빼 준다 */
export function toggleChoice(choices: ReplyChoice[], c: ReplyChoice): ReplyChoice[] {
  if (choices.includes(c)) return choices.filter((x) => x !== c)
  if (c === 'KEEP') return [...choices.filter((x) => !ALT_KEYS.includes(x)), c]
  if (ALT_KEYS.includes(c)) return [...choices.filter((x) => x !== 'KEEP'), c]
  return [...choices, c]
}

/** 보내기 전에 검사. 문제가 없으면 빈 글 */
export function replyError(choices: ReplyChoice[], text: string, canKeep: boolean): string {
  if (!choices.length) return 'A·B·C·기타·지금 자리 그대로 중 하나 이상을 골라 주세요.'
  if (choices.includes('ETC') && !text.trim()) return '기타를 골랐으면 내용을 적어 주세요.'
  if (choices.includes('KEEP') && !canKeep) return "'지금 자리 그대로'는 이미 자리가 있는 분반에서만 고를 수 있습니다."
  return ''
}

// ---------- 조건 글로 ----------

/** 조건을 사람이 읽는 글로: "화 09:00·10:30, 목 아무 교시 / 수 17:00 전 종료" */
export function condText(c: Conditions | null | undefined): string {
  if (!c) return ''
  const days = Object.keys(c.day_slots).map(Number).sort((a, b) => a - b)
  const parts = days.map((d) => {
    const slots = c.day_slots[String(d)]
    return `${DAYS[d] ?? d} ${slots.length ? slots.join('·') : '아무 교시'}`
  })
  const ends = c.end_before.map((e) => `${DAYS[e.day] ?? e.day} ${e.time} 전 종료`)
  return [parts.join(', '), ends.join(', ')].filter(Boolean).join(' / ')
}

// ---------- 조교 직접 배치 ----------

export interface ManualRow {
  day: number
  start: string
  slots: number
  room: string
}

const toMin = (t: string): number => {
  const [h, m] = t.split(':').map(Number)
  return h * 60 + m
}
const toHM = (v: number): string => `${String(Math.floor(v / 60)).padStart(2, '0')}:${String(v % 60).padStart(2, '0')}`

/** 직접 배치 칸 → 서버 Meeting (끝 시각 = 75분 × 칸 수 + 쉬는 시간) */
export function rowsToMeetings(rows: ManualRow[]): Meeting[] {
  return rows.map((r) => ({
    day: r.day,
    start: r.start,
    end: toHM(toMin(r.start) + LESSON_MIN * r.slots + BREAK_MIN * (r.slots - 1)),
    room: r.room,
  }))
}

/** 직접 배치 검사. 문제가 없으면 빈 글 */
export function manualError(rows: ManualRow[]): string {
  if (!rows.length) return '수업을 하나 이상 넣어 주세요.'
  if (rows.some((r) => !r.room)) return '강의실을 골라 주세요.'
  if (rows.some((r) => !(STARTS as readonly string[]).includes(r.start))) return '시작 시각이 교시와 맞지 않습니다.'
  const seen = new Set(rows.map((r) => `${r.day}-${r.start}`))
  if (seen.size !== rows.length) return '같은 요일·시각이 두 번 들어 있습니다.'
  return ''
}

export const PARSE_KIND_CLASS: Record<string, string> = { 수용: 'good', 조건부: 'warn', 거절: 'bad', '확인 필요': 'warn' }
export const ACTION_LABEL: Record<string, string> = { move: '고른 안으로 옮기기', next: '조건 넣어 다음 차수로', decide: '조교가 직접 정하기', keep: '지금 자리 그대로' }

/** 다음 차수로 넘어갈 때 이어받지 못하는 안건: 답장 대기·처리안 확인 중인 것.
 *  서버(dbmode.next_round)는 바로 앞 차수에서 '다음 차수로'가 된 안건만 이어받기 때문에,
 *  이 안건들은 나중에 조건이 생겨도 다음 차수 대안을 받지 못한다. */
export function notCarried(items: CoordItem[]): CoordItem[] {
  return items.filter((c) => c.state === 'SENT' || c.state === 'PROPOSED')
}
