import { describe, expect, test } from 'vitest'
import type { CoordItem } from '../api/types'
import { condText, groupCoord, manualError, notCarried, replyError, roundStep, rowsToMeetings, toggleChoice } from './coord'

const item = (id: string, state: string): CoordItem => ({
  section_id: id, name: null, professor: null, kind: 'MISMATCH', reason: null, round_no: 1, state, alternatives: [],
  current: null, message: null, proposal: null, last_parse: null, prev_conditions: null, next_conditions: null,
})

describe('groupCoord', () => {
  test('splits items into todo, waiting and done', () => {
    const g = groupCoord(['OPEN', 'HOLD', 'NO_OPTION', 'PROPOSED', 'OFFLINE', 'SENT', 'NEXT', 'RESOLVED', 'KEPT'].map((s) => item(s, s)))
    expect(g.todo.map((c) => c.state)).toEqual(['OPEN', 'HOLD', 'NO_OPTION', 'PROPOSED', 'OFFLINE'])
    expect(g.waiting.map((c) => c.state)).toEqual(['SENT'])
    expect(g.done.map((c) => c.state)).toEqual(['NEXT', 'RESOLVED', 'KEPT'])
  })
})

describe('roundStep', () => {
  test('publishes the draft from DRAFT', () => {
    expect(roundStep('DRAFT', 0)).toMatchObject({ label: '초안 공개 + 1차 조율 시작', enabled: true })
  })

  test('moves to the next round until round 3', () => {
    expect(roundStep('ROUND', 1)).toMatchObject({ label: '2차 조율 시작', enabled: true })
    expect(roundStep('ROUND', 3).enabled).toBe(false)
  })

  test('is disabled outside DRAFT and ROUND', () => {
    expect(roundStep('COLLECT', 0).enabled).toBe(false)
    expect(roundStep('FINAL', 3).enabled).toBe(false)
  })
})

describe('toggleChoice', () => {
  test('adds and removes a choice', () => {
    expect(toggleChoice(['A'], 'B')).toEqual(['A', 'B'])
    expect(toggleChoice(['A', 'B'], 'A')).toEqual(['B'])
  })

  test('KEEP removes A, B, C but keeps ETC', () => {
    expect(toggleChoice(['A', 'ETC'], 'KEEP')).toEqual(['ETC', 'KEEP'])
  })

  test('picking an alternative removes KEEP', () => {
    expect(toggleChoice(['KEEP', 'ETC'], 'C')).toEqual(['ETC', 'C'])
  })
})

describe('replyError', () => {
  test('needs at least one choice', () => {
    expect(replyError([], '', true)).not.toBe('')
  })

  test('needs text when ETC is picked', () => {
    expect(replyError(['ETC'], '  ', true)).toMatch(/기타/)
    expect(replyError(['ETC'], '화요일 오전', true)).toBe('')
  })

  test('KEEP only when the section already has a place', () => {
    expect(replyError(['KEEP'], '', false)).toMatch(/지금 자리/)
    expect(replyError(['KEEP'], '', true)).toBe('')
  })
})

describe('condText', () => {
  test('writes day slots and end-before limits', () => {
    expect(condText({ day_slots: { 3: [], 1: ['09:00', '10:30'] }, end_before: [{ day: 2, time: '17:00' }] }))
      .toBe('화 09:00·10:30, 목 아무 교시 / 수 17:00 전 종료')
  })

  test('is empty for missing or empty conditions', () => {
    expect(condText(null)).toBe('')
    expect(condText({ day_slots: {}, end_before: [] })).toBe('')
  })
})

describe('manual placement', () => {
  test('rowsToMeetings computes end times with the break for long lessons', () => {
    expect(rowsToMeetings([{ day: 0, start: '13:30', slots: 1, room: 'R' }, { day: 2, start: '09:00', slots: 2, room: 'R' }]))
      .toEqual([{ day: 0, start: '13:30', end: '14:45', room: 'R' }, { day: 2, start: '09:00', end: '11:45', room: 'R' }])
  })

  test('manualError checks rooms, starts and duplicates', () => {
    expect(manualError([])).not.toBe('')
    expect(manualError([{ day: 0, start: '09:00', slots: 1, room: '' }])).toMatch(/강의실/)
    expect(manualError([{ day: 0, start: '09:10', slots: 1, room: 'R' }])).toMatch(/시작/)
    expect(manualError([{ day: 0, start: '09:00', slots: 1, room: 'R' }, { day: 0, start: '09:00', slots: 1, room: 'R' }])).toMatch(/두 번/)
    expect(manualError([{ day: 0, start: '09:00', slots: 1, room: 'R' }])).toBe('')
  })
})

describe('notCarried', () => {
  test('lists waiting and proposed items that the next round will not carry over', () => {
    const items = ['SENT', 'PROPOSED', 'NEXT', 'OPEN', 'RESOLVED'].map((s) => item(s, s))
    expect(notCarried(items).map((c) => c.state)).toEqual(['SENT', 'PROPOSED'])
  })
})
