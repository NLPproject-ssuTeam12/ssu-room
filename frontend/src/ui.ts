import { notify } from './store'

// 알림(토스트)과 확인창. 시안의 toast()·askConfirm()과 같다.
export type ConfirmOptions = {
  title: string
  body: string
  ok?: string
  reason?: boolean
  placeholder?: string
}

const TOAST_MS = 2800
let toastText = ''
let toastTimer: ReturnType<typeof setTimeout> | null = null
let dialog: { opts: ConfirmOptions; onOk: (reason: string) => void } | null = null

export const getToast = (): string => toastText
export const getDialog = () => dialog

export function toast(msg: string): void {
  toastText = msg
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toastText = ''
    notify()
  }, TOAST_MS)
  notify()
}

/** 확인을 누르면 onOk(사유). reason이 true면 사유를 꼭 받는다 */
export function askConfirm(opts: ConfirmOptions, onOk: (reason: string) => void): void {
  dialog = { opts, onOk }
  notify()
}

export function closeDialog(): void {
  dialog = null
  notify()
}

// ---------------- 테마 (시스템 · 라이트 · 다크, 이 브라우저에만 기억) ----------------
const THEME_KEY = 'ssuroom-v4-theme'
export type Theme = 'system' | 'light' | 'dark'
export const THEMES: [Theme, string][] = [['light', '라이트'], ['dark', '다크'], ['system', '시스템']]

const DEFAULT_THEME: Theme = 'light'

/** 고른 적이 없으면 라이트 */
export function savedTheme(): Theme {
  try {
    const v = localStorage.getItem(THEME_KEY)
    return v === 'light' || v === 'dark' || v === 'system' ? v : DEFAULT_THEME
  } catch {
    return DEFAULT_THEME
  }
}

export function applyTheme(v: Theme): void {
  const root = document.documentElement
  if (v === 'system') delete root.dataset.theme
  else root.dataset.theme = v
  try {
    localStorage.setItem(THEME_KEY, v)
  } catch {
    /* 저장이 막힌 브라우저: 이번 화면에서만 적용 */
  }
  notify()
}
