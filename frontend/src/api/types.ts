// 서버(backend/app/contracts.py, main.py)와 같은 모양. 이름·값을 바꾸면 서버 쪽과 같이 바꾼다.

export const DAYS = ['월', '화', '수', '목', '금'] as const
export type Day = (typeof DAYS)[number]
export const STARTS = ['09:00', '10:30', '12:00', '13:30', '15:00', '16:30', '18:00', '19:30'] as const
export type Start = (typeof STARTS)[number]

/** "월-09:00" 같은 칸 이름 */
export type CellKey = `${Day}-${Start}`
export type CellMark = 'PREFER' | 'BLOCK'
export type Cells = Partial<Record<CellKey, CellMark>>

export type LabNeed = 'MUST' | 'NONE'
export type SingleDay = 'MUST' | 'PREFER' | 'NONE'
export type Shape = 'TWICE' | 'ONCE_LONG' | 'MANUAL'
export type Stage = 'COLLECT' | 'DRAFT' | 'ROUND' | 'FINAL'

export interface Section {
  id: string
  code: string
  name: string
  division: string | null
  year: number | null
  category: string
  enrollment: number | null
  weekly_blocks: number
  professor: string | null
  lab_need: LabNeed
  shape: Shape
}

export interface Room {
  id: string
  building: string
  room_no: string
  capacity: number | null
  is_lab: boolean
  estimated: boolean
}

export interface Wish {
  section_id: string
  professor: string | null
  cells: Cells
  must: boolean
  lab: LabNeed
  single_day: SingleDay
  building: string | null
  room: string | null
  note: string
}

export interface WishesResponse {
  wishes: Wish[]
  professors: Record<string, { sections: string[] }>
}

export interface Health {
  ok: boolean
  data_set: string
  stage: Stage
  round_no: number
  engine: Record<string, string>
  load_warnings: string[]
}

export type PairMode = 'NONE' | 'BACK_TO_BACK' | 'CROSS'

export interface PairRequest {
  section_id: string
  mode: PairMode
  order?: string[]
}

export interface PairResponse {
  section_id: string
  mode: PairMode
  order: string[]
}

// ---------- 초안·시간표 (GET /timetable, POST /draft) ----------

export type BlockDay = Day | '토'
export type AssignmentStatus = 'DONE' | 'COORD' | 'MANUAL'

/** 수업 한 번. start는 보통 STARTS 중 하나지만 직접 배정 분반은 16:00 같은 다른 시각도 온다 */
export interface Block {
  day: BlockDay
  start: string
  slots: number
  room: string | null
}

export interface Assignment {
  section_id: string
  blocks: Block[]
  room: string | null
  status: AssignmentStatus
  reason: string | null
}

export interface TimetableResponse {
  stage: Stage
  round_no: number
  status: 'DRAFT' | 'ROUND' | 'FINAL'
  assignments: Assignment[]
}

export interface DraftResult {
  stage: Stage
  assignments: number
  status_count: Partial<Record<AssignmentStatus, number>>
  coord: string[]
  coord_status?: Record<string, number>
  solver?: { status: string; seconds: number | null; unplaced: number; unsupported: string[] }
  violations: number
}

// ---------- 조율 (GET /coord). 요일은 숫자 0=월 … 4=금 ----------

export interface Meeting {
  day: number
  start: string
  end: string
  room: string
}

export interface Alternative {
  key: 'A' | 'B' | 'C'
  meetings: Meeting[]
}

/** UNPLACED = 못 놓음, MISMATCH = 희망에서 어긋남, PARTIAL = 일부 어긋남 */
export type CoordKind = 'UNPLACED' | 'MISMATCH' | 'PARTIAL'

export type AltKey = Alternative['key']

/** 교수 답장에서 뽑은 조건. day_slots 키는 요일 숫자 문자열 ("1" = 화), 빈 목록 = 그 요일은 아무 교시나 */
export interface Conditions {
  day_slots: Record<string, string[]>
  end_before: { day: number; time: string }[]
}

export interface ReplyParse {
  kind: '수용' | '조건부' | '거절' | '확인 필요'
  picks: AltKey[]
  ordered: boolean
  keep: boolean
  conditions: Conditions
  note: string
  method: 'keyword' | 'llm'
  fallback: boolean
  fallback_reason: string
}

/** 처리안: move = 고른 안으로, next = 조건 넣어 다음 차수, decide = 조교가 직접, keep = 지금 자리 그대로 */
export interface Proposal {
  action: 'move' | 'next' | 'decide' | 'keep'
  key: AltKey | null
  conditions: Conditions
  text: string
  checks: { key: string; ok: boolean; why: string }[]
}

export type CoordState = 'OPEN' | 'HOLD' | 'NO_OPTION' | 'SENT' | 'PROPOSED' | 'NEXT' | 'RESOLVED' | 'KEPT' | 'OFFLINE'

export interface CoordItem {
  section_id: string
  name: string | null
  professor: string | null
  kind?: CoordKind | string
  reason: string | null
  round_no: number
  state: CoordState | string
  alternatives: Alternative[]
  current: string | null
  message: string | null
  proposal: Proposal | null
  last_parse: ReplyParse | null
  prev_conditions: Conditions | null
  next_conditions: Conditions | null
}

// ---------- 조율 요청 (POST /coord/{id}/…, /rounds/next) ----------

export type ReplyChoice = AltKey | 'ETC' | 'KEEP'
export type DecideAction = 'confirm' | 'edit' | 'keep' | 'offline'

export interface MessageRecord {
  section_id: string
  round_no: number
  text: string
  sent: boolean
  issues: string[]
}

export interface RoundResult {
  stage: Stage
  round_no: number
  open: string[]
  sent?: string[]
}

export interface DecideRequest {
  action: DecideAction
  reason?: string
  choice?: AltKey
}

/** 직접 배치 뒤 서버가 돌려주는 규칙 경고 (solver check_timetable) */
export interface RuleWarning {
  rule: string
  detail: string
}

export interface ManualRequest {
  meetings: Meeting[]
  reason?: string
}

// ---------- AI 도우미 (POST /assistant, /assistant/apply) ----------

export type AssistantIntent = 'explain' | 'move' | 'what_if' | 'status' | 'out_of_scope'

/** 도우미가 보여 주는 바뀜 한 줄. status 답에서는 before·after가 없고 note에 상태가 온다 */
export interface AssistantChange {
  section_id: string
  name: string
  before: string | null
  after: string | null
  note: string
}

export interface AssistantResponse {
  command: { intent: AssistantIntent | string; method: string; fallback: boolean; ask_back: string | null }
  section_id: string | null
  answer: string
  proposal_id: string | null
  changes: AssistantChange[]
  needs_apply: boolean
}

/** 앞선 대화 (서버가 "그 강의" 같은 말을 풀 때 쓴다) */
export interface AssistantHistoryItem {
  role: 'user' | 'assistant'
  text: string
  section_id?: string | null
}

// ---------- 확정·내보내기·설정 (POST /finalize, GET /export.xlsx, GET·POST /settings, POST /reset) ----------

export interface FinalizeResult {
  stage: Stage
  round_no: number
  /** 확정할 때 아직 조율 중(임시 자리)이던 분반 */
  unresolved: string[]
  violations: number
}

/** 학과 설정 (서버 메모리에만 있어서 서버를 다시 켜면 기본값으로 돌아간다) */
export interface Settings {
  reveal_opponent: boolean
}
