// 로그인 상태 (조교 / 교수 + 이름). 서버에 계정 기능이 없어 비밀번호 없이 역할만 고른다.
// 브라우저 탭마다 따로 기억한다(sessionStorage): 새로고침해도 유지, 탭을 닫으면 로그아웃.
// 그래서 한 탭은 조교, 다른 탭은 교수로 열어 시연할 수 있다.
import type { ServerData } from './data'

export type Session = { role: 'ta' } | { role: 'prof'; prof: string }

type KeyStore = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

const KEY = 'ssuroom-session'

function browserStore(): KeyStore | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

export function parseSession(raw: string | null): Session | null {
  if (!raw) return null
  try {
    const v: unknown = JSON.parse(raw)
    if (typeof v !== 'object' || v === null) return null
    const o = v as Record<string, unknown>
    if (o.role === 'ta') return { role: 'ta' }
    if (o.role === 'prof' && typeof o.prof === 'string' && o.prof) return { role: 'prof', prof: o.prof }
    return null
  } catch {
    return null
  }
}

export function loadSession(store: KeyStore | null = browserStore()): Session | null {
  try {
    return parseSession(store?.getItem(KEY) ?? null)
  } catch {
    return null
  }
}

/** null이면 로그아웃 */
export function saveSession(s: Session | null, store: KeyStore | null = browserStore()): void {
  try {
    if (s) store?.setItem(KEY, JSON.stringify(s))
    else store?.removeItem(KEY)
  } catch {
    /* 저장이 막힌 브라우저: 이번 화면에서만 로그인 */
  }
}

/** 로그인할 수 있는 교수: 자동 배정 분반이 있는 교수만, 이름 순 */
export function loginProfessors(data: ServerData): string[] {
  const auto = new Set(data.sections.filter((s) => s.shape !== 'MANUAL').map((s) => s.id))
  return Object.entries(data.professors)
    .filter(([, v]) => v.sections.some((id) => auto.has(id)))
    .map(([p]) => p)
    .sort((a, b) => a.localeCompare(b, 'ko'))
}

/** 데이터가 바뀌어(처음부터 다시 등) 없는 교수로 로그인돼 있으면 로그아웃 상태로 */
export function checkSession(s: Session | null, data: ServerData): Session | null {
  if (!s || s.role === 'ta') return s
  return loginProfessors(data).includes(s.prof) ? s : null
}
