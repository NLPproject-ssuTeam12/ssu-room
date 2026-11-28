// 서버 호출은 이 파일 한 곳에서만 한다. 에러는 서버의 {detail}을 그대로 사람이 읽는 글로 바꾼다.
import type {
  AssistantHistoryItem, AssistantResponse, CoordItem, DecideRequest, DraftResult, FinalizeResult, Health, ManualRequest, MessageRecord, OtherRequest, PairRequest, PairResponse, ReplyChoice, Room,
  RoundResult, RuleWarning, Section, Settings, TimetableResponse, Wish, WishesResponse,
} from './types'

const DEFAULT_BASE = 'http://localhost:8000'
const API_PORT = 8000

/** 서버 주소. VITE_API_BASE가 있으면 그것, 없으면 화면을 연 주소의 8000 포트.
 *  컴퓨터 2대 시연: B가 http://A의IP:5173 으로 열면 서버도 A의IP:8000 으로 간다 (B 자신이 아니라) */
export function apiBase(envBase: string | undefined, loc: { protocol: string; hostname: string } | undefined): string {
  if (envBase) return envBase.replace(/\/+$/, '')
  if (!loc?.hostname) return DEFAULT_BASE
  const protocol = loc.protocol === 'https:' ? 'https:' : 'http:'
  return `${protocol}//${loc.hostname}:${API_PORT}`
}

export const API_BASE: string = apiBase(import.meta.env.VITE_API_BASE, typeof window === 'undefined' ? undefined : window.location)

/** 확정한 시간표 엑셀. 링크로 내려받는다 (확정 전에는 서버가 409) */
export const EXPORT_URL = `${API_BASE}/export.xlsx`

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

type PydanticIssue = { loc?: unknown[]; msg?: string }

/** FastAPI 에러 본문의 detail(글 또는 Pydantic 검사 목록)을 한 줄로 */
export function detailText(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((d: PydanticIssue) => {
        const where = (d.loc ?? []).filter((x) => x !== 'body').join('.')
        return where ? `${where}: ${d.msg ?? ''}` : (d.msg ?? '')
      })
      .join(' / ')
  }
  return `서버 오류 (${status})`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new ApiError(0, `서버(${API_BASE})에 연결하지 못했습니다. 서버가 켜져 있는지 확인해 주세요.`)
  }
  const body: unknown = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, detailText(body, res.status))
  return body as T
}

/** 분반 id에 괄호·한글이 들어가므로 경로에 넣을 때 인코딩한다 (예: 2150164403-(공통-재수강)) */
export const coordPath = (id: string): string => `/coord/${encodeURIComponent(id)}`

const post = <T>(path: string, data: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(data) })

export const api = {
  health: () => request<Health>('/health'),
  sections: () => request<Section[]>('/sections'),
  rooms: () => request<Room[]>('/rooms'),
  wishes: () => request<WishesResponse>('/wishes'),
  saveWish: (wish: Wish) => post<{ saved: Wish }>('/wishes', wish),
  savePair: (pair: PairRequest) => post<PairResponse>('/wishes/pair', pair),
  draft: () => post<DraftResult>('/draft', {}),
  timetable: () => request<TimetableResponse>('/timetable'),
  coord: () => request<CoordItem[]>('/coord'),
  nextRound: () => post<RoundResult>('/rounds/next', {}),
  sendMessage: (id: string) => post<MessageRecord>(`${coordPath(id)}/message`, {}),
  hold: (id: string, send: boolean) => post<{ coord: CoordItem }>(`${coordPath(id)}/hold`, { send }),
  ack: (id: string) => post<{ coord: CoordItem }>(`${coordPath(id)}/ack`, {}),
  reply: (id: string, choices: ReplyChoice[], text: string) => post<unknown>(`${coordPath(id)}/reply`, { choices, text }),
  decide: (id: string, body: DecideRequest) => post<{ coord: CoordItem }>(`${coordPath(id)}/decide`, body),
  assistant: (text: string, history: AssistantHistoryItem[]) => post<AssistantResponse>('/assistant', { text, history }),
  assistantApply: (proposalId: string, reason: string) => post<unknown>('/assistant/apply', { proposal_id: proposalId, reason }),
  finalize: () => post<FinalizeResult>('/finalize', {}),
  reset: () => post<{ stage: string }>('/reset', {}),
  settings: () => request<Settings>('/settings'),
  saveSettings: (patch: Partial<Settings>) => post<Settings>('/settings', patch),
  requests: () => request<OtherRequest[]>('/requests'),
  confirmRequest: (id: number, memo: string) => post<OtherRequest>(`/requests/${id}/confirm`, { memo: memo.trim() || null }),
  manual: (id: string, body: ManualRequest) => post<{ coord: CoordItem; warnings?: RuleWarning[] }>(`${coordPath(id)}/manual`, body),
}
