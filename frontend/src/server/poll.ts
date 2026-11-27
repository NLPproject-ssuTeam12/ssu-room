// 컴퓨터 2대 시연: 몇 초마다 서버를 다시 읽어, 다른 컴퓨터(교수)가 바꾼 것이 이 화면(조교)에도 보이게 한다.
// 입력 중인 칸·확인창이 날아가지 않게, 그동안에는 건너뛴다 (poll.test.ts).
import { getDialog } from '../ui'
import { refresh } from './data'

export const POLL_MS = 3000

const TYPING_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT'])
const NOT_TYPING_INPUTS = new Set(['button', 'checkbox', 'radio', 'submit', 'reset'])

type DocLike = { hidden: boolean; activeElement: Element | null }

/** 글을 적거나 고르는 중인지 (입력 칸에 커서가 있음) */
export function isTyping(el: Element | null): boolean {
  if (!el) return false
  if ((el as HTMLElement).isContentEditable) return true
  if (!TYPING_TAGS.has(el.tagName)) return false
  return el.tagName !== 'INPUT' || !NOT_TYPING_INPUTS.has((el as HTMLInputElement).type)
}

/** 지금 다시 불러와도 되는지: 탭이 보이고, 확인창이 없고, 입력 중이 아닐 때 */
export function shouldPoll(doc: DocLike, dialogOpen: boolean): boolean {
  return !doc.hidden && !dialogOpen && !isTyping(doc.activeElement)
}

/** 자동 새로 고침 시작. 돌려준 함수를 부르면 멈춘다 */
export function startPolling(ms: number = POLL_MS): () => void {
  const id = setInterval(() => {
    if (shouldPoll(document, !!getDialog())) void refresh()
  }, ms)
  return () => clearInterval(id)
}
