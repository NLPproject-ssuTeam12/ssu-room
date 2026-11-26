// 서버 모드의 데이터 한 곳. 서버에서 받은 값을 들고 있고, 바뀌면 새 객체로 바꿔 화면을 다시 그린다 (data.test.ts).
// - 조회마다 순번을 매겨 늦게 도착한 옛 조회 결과는 버린다 (최신 상태를 덮지 않게).
// - 희망 저장은 한 줄로 세워 하나씩 보낸다 (건물처럼 교수 단위 값이 서로 덮이지 않게).
import { useSyncExternalStore } from 'react'
import { api } from '../api/client'
import { toast } from '../ui'
import type {
  CoordItem, DraftResult, Health, PairRequest, PairResponse, Room, Section, TimetableResponse, Wish, WishesResponse,
} from '../api/types'

export interface ServerData {
  health: Health
  sections: Section[]
  rooms: Room[]
  wishes: Wish[]
  professors: WishesResponse['professors']
  /** 초안이 생기기 전(COLLECT)에는 null */
  timetable: TimetableResponse | null
  coord: CoordItem[]
  /** 분반별로 조교에게 남겨 둘 알림 (직접 배치 규칙 경고, 보내기 실패 등). 다시 불러와도 유지한다 */
  notes: Record<string, string[]>
}

export type LoadState =
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'ready'; data: ServerData }

let state: LoadState = { status: 'loading' }
let loadSeq = 0
let wishQueue: Promise<unknown> = Promise.resolve()
const subscribers = new Set<() => void>()

function setState(next: LoadState): void {
  state = next
  subscribers.forEach((fn) => fn())
}

export function useServerData(): LoadState {
  return useSyncExternalStore(
    (cb) => {
      subscribers.add(cb)
      return () => subscribers.delete(cb)
    },
    () => state,
  )
}

/** 테스트용: 상태를 처음으로 */
export function resetForTest(): void {
  state = { status: 'loading' }
  loadSeq = 0
  wishQueue = Promise.resolve()
}

export const getState = (): LoadState => state

const errorText = (e: unknown): string => (e instanceof Error ? e.message : '알 수 없는 오류')
const currentNotes = (): Record<string, string[]> => (state.status === 'ready' ? state.data.notes : {})

/** 처음 불러오기·다시 불러오기. 더 늦게 시작한 조회나 저장이 있으면 이 결과는 버린다 */
export async function loadAll(): Promise<void> {
  const seq = ++loadSeq
  if (state.status !== 'ready') setState({ status: 'loading' })
  try {
    const [health, sections, rooms, w] = await Promise.all([api.health(), api.sections(), api.rooms(), api.wishes()])
    // 시간표는 초안을 만든 뒤에만 있다 (COLLECT에서 부르면 409)
    const hasDraft = health.stage !== 'COLLECT'
    const [timetable, coord] = hasDraft ? await Promise.all([api.timetable(), api.coord()]) : [null, []]
    if (seq !== loadSeq) return
    setState({
      status: 'ready',
      data: { health, sections, rooms, wishes: w.wishes, professors: w.professors, timetable, coord, notes: currentNotes() },
    })
  } catch (e: unknown) {
    if (seq !== loadSeq) return
    // 이미 화면이 있으면 지우지 않는다 (다시 불러오기만 실패)
    if (state.status !== 'ready') setState({ status: 'error', error: errorText(e) })
    else throw e
  }
}

function readyData(): ServerData {
  if (state.status !== 'ready') throw new Error('서버 데이터를 아직 불러오지 않았습니다.')
  return state.data
}

/** 저장 결과를 캐시에 반영. 서버는 건물을 교수 단위로 저장하므로 같은 교수의 다른 희망 건물도 맞춘다 */
export function applySavedWish(data: ServerData, saved: Wish): ServerData {
  const mine = new Set(saved.professor ? data.professors[saved.professor]?.sections ?? [] : [])
  const others = data.wishes
    .filter((w) => w.section_id !== saved.section_id)
    .map((w) => (mine.has(w.section_id) ? { ...w, building: saved.building } : w))
  return { ...data, wishes: [...others, saved] }
}

function enqueueWish<T>(task: () => Promise<T>): Promise<T> {
  const run = wishQueue.then(task, task)
  wishQueue = run.catch(() => undefined)
  return run
}

async function sendWish(wish: Wish): Promise<Wish> {
  const { saved } = await api.saveWish(wish)
  loadSeq += 1 // 저장 전에 시작한 조회 결과가 늦게 와서 덮지 않게
  setState({ status: 'ready', data: applySavedWish(readyData(), saved) })
  return saved
}

/** 희망 하나 저장 (차례대로). 성공하면 서버가 돌려준 값으로 바꾼다. 실패하면 에러를 그대로 던진다 */
export function saveWish(wish: Wish): Promise<Wish> {
  return enqueueWish(() => sendWish(wish))
}

/** 교수 희망 건물 바꾸기. 서버는 희망 하나만 저장해도 교수 건물을 바꾸므로, 차례가 왔을 때의 최신 희망 하나만 보낸다 */
export function saveProfBuilding(prof: string, building: string | null): Promise<void> {
  return enqueueWish(async () => {
    const data = readyData()
    const mine = new Set(data.professors[prof]?.sections ?? [])
    const latest = data.wishes.find((w) => mine.has(w.section_id))
    if (!latest) throw new Error('먼저 분반 희망을 하나 이상 저장해 주세요.')
    await sendWish({ ...latest, building })
  })
}

/** 분반별 알림 남기기·지우기 (다시 불러와도 남는다) */
export function addNote(sectionId: string, text: string): void {
  const data = readyData()
  setState({ status: 'ready', data: { ...data, notes: { ...data.notes, [sectionId]: [...(data.notes[sectionId] ?? []), text] } } })
}

export function clearNotes(sectionId: string): void {
  const data = readyData()
  const notes = Object.fromEntries(Object.entries(data.notes).filter(([k]) => k !== sectionId))
  setState({ status: 'ready', data: { ...data, notes } })
}

/** 초안 만들기 (솔버, 몇 초 걸린다). 끝나면 전부 다시 불러온다 */
export function makeDraft(): Promise<DraftResult> {
  return mutate(() => api.draft())
}

export const savePair = (pair: PairRequest): Promise<PairResponse> => api.savePair(pair)

/** 서버 상태를 바꾸는 호출 (조율·차수 등). 성공이든 실패든 끝나면 다시 불러와 서버와 맞춘다.
 *  실패하면 호출의 에러를 그대로 던진다 (다시 불러오기 실패는 덮지 않는다) */
export async function mutate<T>(call: () => Promise<T>): Promise<T> {
  try {
    return await call()
  } finally {
    await loadAll().catch((e: unknown) => toast(`화면을 새로 불러오지 못했습니다: ${errorText(e)}`))
  }
}
