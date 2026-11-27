import { describe, expect, test } from 'vitest'
import { isTyping, shouldPoll } from './poll'

const el = (tagName: string, extra: Record<string, unknown> = {}) => ({ tagName, ...extra }) as unknown as Element

describe('isTyping', () => {
  test('text boxes, text areas and drop-downs count as typing', () => {
    expect(isTyping(el('INPUT', { type: 'text' }))).toBe(true)
    expect(isTyping(el('INPUT', { type: 'number' }))).toBe(true)
    expect(isTyping(el('TEXTAREA'))).toBe(true)
    expect(isTyping(el('SELECT'))).toBe(true)
    expect(isTyping(el('DIV', { isContentEditable: true }))).toBe(true)
  })

  test('buttons, radios and nothing focused do not', () => {
    expect(isTyping(null)).toBe(false)
    expect(isTyping(el('BUTTON'))).toBe(false)
    expect(isTyping(el('INPUT', { type: 'radio' }))).toBe(false)
    expect(isTyping(el('BODY'))).toBe(false)
  })
})

describe('shouldPoll', () => {
  const idle = { hidden: false, activeElement: el('BODY') }

  test('polls when the tab is visible and nothing is being edited', () => {
    expect(shouldPoll(idle, false)).toBe(true)
  })

  test('skips while a confirm dialog is open, while typing, or in a background tab', () => {
    expect(shouldPoll(idle, true)).toBe(false)
    expect(shouldPoll({ hidden: false, activeElement: el('TEXTAREA') }, false)).toBe(false)
    expect(shouldPoll({ ...idle, hidden: true }, false)).toBe(false)
  })
})
