// AI 도우미 대화의 순수 함수 (assistant.test.ts). 대화 기록은 새 배열로만 바꾼다.
import type { AssistantHistoryItem, AssistantResponse } from '../api/types'

export type ApplyState = 'none' | 'pending' | 'applied' | 'cancelled'

export type Turn =
  | { role: 'user'; text: string }
  | { role: 'bot'; res: AssistantResponse; apply: ApplyState }
  | { role: 'error'; text: string }

export const EXAMPLES = [
  '지금 상태 어때?',
  '인공지능입문 04 왜 밀렸어?',
  '자료구조 02 화·목 09:00으로 옮겨줘',
  '정보과학관 21501 못 쓰면?',
  '점심 메뉴 추천해줘',
]

export const INTENT_LABEL: Record<string, string> = {
  explain: '설명', move: '옮기기 제안', what_if: '가정 계산', status: '현황', out_of_scope: '범위 밖',
}

/** 서버에 보낼 앞선 대화. 오류 줄은 빼고 최근 것만 */
export function toHistory(turns: Turn[], max = 6): AssistantHistoryItem[] {
  const items: AssistantHistoryItem[] = turns.flatMap((t): AssistantHistoryItem[] => {
    if (t.role === 'user') return [{ role: 'user', text: t.text }]
    if (t.role === 'bot') return [{ role: 'assistant', text: t.res.answer, section_id: t.res.section_id }]
    return []
  })
  return items.slice(-max)
}

/** 새 제안이 오면 아직 적용하지 않은 옛 제안은 쓸 수 없게 (서버도 시간표가 바뀌면 옛 제안을 거부한다) */
export function addBotTurn(turns: Turn[], res: AssistantResponse): Turn[] {
  const closed = turns.map((t): Turn => (t.role === 'bot' && t.apply === 'pending' && res.needs_apply ? { ...t, apply: 'cancelled' } : t))
  return [...closed, { role: 'bot', res, apply: res.needs_apply ? 'pending' : 'none' }]
}

export function setApply(turns: Turn[], index: number, apply: ApplyState): Turn[] {
  return turns.map((t, i): Turn => (i === index && t.role === 'bot' ? { ...t, apply } : t))
}

/** 이 바뀜 목록이 옮기기 전후를 보여 주는지 (현황 답은 before·after가 없다) */
export const hasMoves = (res: AssistantResponse): boolean => res.changes.some((c) => c.before !== null || c.after !== null)
