import { describe, expect, test } from 'vitest'
import type { Assignment, Block } from '../api/types'
import { altText, blockText, countStatus, gridKey, layoutGrid, meetingText, usedRooms } from './timetable'

const blk = (day: Block['day'], start: string, slots = 1, room: string | null = 'R1'): Block => ({ day, start, slots, room })
const asg = (id: string, blocks: Block[], status: Assignment['status'] = 'DONE'): Assignment => ({
  section_id: id, blocks, room: blocks[0]?.room ?? null, status, reason: null,
})

describe('layoutGrid', () => {
  test('places twice-a-week lessons in both day cells', () => {
    const { cells } = layoutGrid([asg('s1', [blk('월', '09:00'), blk('수', '09:00')])])
    expect(cells.get(gridKey('월', 0))?.map((p) => p.sectionId)).toEqual(['s1'])
    expect(cells.get(gridKey('수', 0))?.map((p) => p.sectionId)).toEqual(['s1'])
  })

  test('spreads a long lesson over two slots and marks the second as continued', () => {
    const { cells } = layoutGrid([asg('s1', [blk('화', '10:30', 2)])])
    expect(cells.get(gridKey('화', 1))?.[0].cont).toBe(false)
    expect(cells.get(gridKey('화', 2))?.[0].cont).toBe(true)
  })

  test('clips a long lesson at the last slot', () => {
    const { cells } = layoutGrid([asg('s1', [blk('금', '19:30', 2)])])
    expect(cells.get(gridKey('금', 7))).toHaveLength(1)
    expect([...cells.keys()]).toEqual([gridKey('금', 7)])
  })

  test('sends Saturday and off-slot starts to the off-grid list', () => {
    const { cells, offGrid } = layoutGrid([asg('m1', [blk('토', '09:00'), blk('수', '16:00')], 'MANUAL')])
    expect(cells.size).toBe(0)
    expect(offGrid.map((o) => o.block.day)).toEqual(['토', '수'])
  })

  test('collects sections without lessons', () => {
    expect(layoutGrid([asg('u1', [], 'COORD')]).empty.map((a) => a.section_id)).toEqual(['u1'])
  })

  test('filters by room and falls back to the assignment room', () => {
    const a: Assignment = { section_id: 's1', blocks: [blk('월', '09:00', 1, null), blk('수', '09:00', 1, 'R2')], room: 'R1', status: 'DONE', reason: null }
    const { cells } = layoutGrid([a], 'R1')
    expect([...cells.keys()]).toEqual([gridKey('월', 0)])
    expect(cells.get(gridKey('월', 0))?.[0].room).toBe('R1')
  })
})

describe('text helpers', () => {
  test('blockText adds the break for long lessons', () => {
    expect(blockText(blk('월', '09:00', 2, '정보과학관 21305'))).toBe('월 09:00~11:45 정보과학관 21305')
    expect(blockText(blk('수', '16:00', 1, null))).toBe('수 16:00~17:15')
  })

  test('meetingText and altText use numeric days', () => {
    const m = { day: 0, start: '09:00', end: '10:15', room: 'R1' }
    expect(meetingText(m)).toBe('월 09:00~10:15 R1')
    expect(altText({ key: 'A', meetings: [m, { ...m, day: 3 }] })).toBe('월 09:00~10:15 R1 / 목 09:00~10:15 R1')
  })
})

describe('summaries', () => {
  test('countStatus counts each status', () => {
    expect(countStatus([asg('a', []), asg('b', [], 'COORD'), asg('c', [], 'MANUAL'), asg('d', [])])).toEqual({ DONE: 2, COORD: 1, MANUAL: 1 })
  })

  test('usedRooms lists distinct rooms in order', () => {
    expect(usedRooms([asg('a', [blk('월', '09:00', 1, '나동 2'), blk('수', '09:00', 1, '가동 1')]), asg('b', [blk('화', '09:00', 1, '가동 1')])]))
      .toEqual(['가동 1', '나동 2'])
  })
})
