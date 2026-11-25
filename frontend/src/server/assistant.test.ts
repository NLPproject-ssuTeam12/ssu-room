import { describe, expect, test } from 'vitest'
import type { AssistantResponse } from '../api/types'
import { addBotTurn, hasMoves, setApply, toHistory } from './assistant'
import type { Turn } from './assistant'

const res = (extra: Partial<AssistantResponse> = {}): AssistantResponse => ({
  command: { intent: 'explain', method: 'keyword', fallback: false, ask_back: null },
  section_id: 's1', answer: '답', proposal_id: null, changes: [], needs_apply: false, ...extra,
})
const proposal = (id: string) => res({ command: { intent: 'move', method: 'keyword', fallback: false, ask_back: null }, proposal_id: id, needs_apply: true })

describe('toHistory', () => {
  test('keeps user and bot turns, drops errors, and keeps the latest only', () => {
    const turns: Turn[] = [
      { role: 'user', text: 'q1' }, { role: 'bot', res: res({ answer: 'a1' }), apply: 'none' },
      { role: 'error', text: 'boom' }, { role: 'user', text: 'q2' },
    ]
    expect(toHistory(turns)).toEqual([
      { role: 'user', text: 'q1' }, { role: 'assistant', text: 'a1', section_id: 's1' }, { role: 'user', text: 'q2' },
    ])
    expect(toHistory(turns, 1)).toEqual([{ role: 'user', text: 'q2' }])
  })
})

describe('addBotTurn', () => {
  test('marks a proposal as pending and a plain answer as none', () => {
    expect(addBotTurn([], proposal('p1'))[0]).toMatchObject({ apply: 'pending' })
    expect(addBotTurn([], res())[0]).toMatchObject({ apply: 'none' })
  })

  test('cancels an older pending proposal when a new one arrives, without mutating', () => {
    const before: Turn[] = [{ role: 'bot', res: proposal('p1'), apply: 'pending' }]
    const after = addBotTurn(before, proposal('p2'))
    expect(after.map((t) => (t.role === 'bot' ? t.apply : t.role))).toEqual(['cancelled', 'pending'])
    expect(before[0]).toMatchObject({ apply: 'pending' })
  })

  test('keeps an older pending proposal when the new answer is not a proposal', () => {
    const after = addBotTurn([{ role: 'bot', res: proposal('p1'), apply: 'pending' }], res())
    expect(after[0]).toMatchObject({ apply: 'pending' })
  })
})

describe('setApply', () => {
  test('changes only the bot turn at the index', () => {
    const turns: Turn[] = [{ role: 'user', text: 'q' }, { role: 'bot', res: proposal('p1'), apply: 'pending' }]
    expect(setApply(turns, 1, 'applied')[1]).toMatchObject({ apply: 'applied' })
    expect(setApply(turns, 0, 'applied')[0]).toEqual({ role: 'user', text: 'q' })
  })
})

describe('hasMoves', () => {
  test('is false for status lists and true for before/after rows', () => {
    expect(hasMoves(res({ changes: [{ section_id: 's', name: 'n', before: null, after: null, note: 'OPEN' }] }))).toBe(false)
    expect(hasMoves(res({ changes: [{ section_id: 's', name: 'n', before: '월', after: '화', note: '옮김' }] }))).toBe(true)
  })
})
