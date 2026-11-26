import { describe, expect, test } from 'vitest'
import type { Section, Wish } from '../api/types'
import {
  emptyWish, multiSectionCourses, nextMark, preferText, profBuilding, reviewOrder, sectionTitle, wishChips, wishEquals,
  withCell,
} from './wish'

const sec = (id: string, name: string, extra: Partial<Section> = {}): Section => ({
  id, code: id, name, division: null, year: 2, category: '전필', enrollment: 40, weekly_blocks: 2,
  professor: '교수01', lab_need: 'NONE', shape: 'TWICE', ...extra,
})
const wish = (sid: string, extra: Partial<Wish> = {}): Wish => ({ ...emptyWish(sec(sid, 'x'), null), ...extra })

describe('nextMark', () => {
  test('cycles empty → PREFER → BLOCK → empty', () => {
    expect(nextMark(undefined)).toBe('PREFER')
    expect(nextMark('PREFER')).toBe('BLOCK')
    expect(nextMark('BLOCK')).toBeNull()
  })
})

describe('withCell', () => {
  test('sets a cell without mutating the original', () => {
    const before = { '월-09:00': 'PREFER' } as const
    const after = withCell(before, '화-10:30', 'BLOCK')
    expect(after).toEqual({ '월-09:00': 'PREFER', '화-10:30': 'BLOCK' })
    expect(before).toEqual({ '월-09:00': 'PREFER' })
  })

  test('removes a cell when mark is null', () => {
    expect(withCell({ '월-09:00': 'PREFER' }, '월-09:00', null)).toEqual({})
  })
})

describe('preferText', () => {
  test('groups days that share the same preferred starts', () => {
    const text = preferText({ '월-15:00': 'PREFER', '수-15:00': 'PREFER', '화-09:00': 'PREFER', '화-10:30': 'PREFER', '목-12:00': 'BLOCK' })
    expect(text).toBe('월·수 15:00 / 화 09:00, 10:30')
  })

  test('returns empty string when nothing is preferred', () => {
    expect(preferText({ '월-09:00': 'BLOCK' })).toBe('')
  })
})

describe('wishChips', () => {
  test('lists preference, blocks, lab, single day, building and note', () => {
    const chips = wishChips(wish('s1', {
      cells: { '월-09:00': 'PREFER', '금-18:00': 'BLOCK' }, lab: 'MUST', single_day: 'MUST', building: '정보과학관', note: '대강 2회',
    }))
    expect(chips.map(([t]) => t)).toEqual(['희망 월 09:00', '불가 1칸', '실습실 필요', '주 1회 연강', '정보과학관 선호', '기타 요청 있음'])
  })

  test('says any time when no cells are painted', () => {
    expect(wishChips(wish('s1'))[0]).toEqual(['희망 시간 없음 (아무 때나)', ''])
  })
})

describe('wishEquals', () => {
  test('ignores cell key order', () => {
    const a = wish('s1', { cells: { '월-09:00': 'PREFER', '화-09:00': 'BLOCK' } })
    const b = wish('s1', { cells: { '화-09:00': 'BLOCK', '월-09:00': 'PREFER' } })
    expect(wishEquals(a, b)).toBe(true)
  })

  test('detects changed fields and missing saved value', () => {
    expect(wishEquals(wish('s1'), wish('s1', { note: '변경' }))).toBe(false)
    expect(wishEquals(undefined, wish('s1'))).toBe(false)
  })
})

describe('reviewOrder', () => {
  test('puts sections with a note first and keeps the rest in order', () => {
    const list = [sec('a', 'A'), sec('b', 'B'), sec('c', 'C')]
    const wishes = new Map([['b', wish('b', { note: '요청' })], ['c', wish('c')]])
    expect(reviewOrder(list, (id) => wishes.get(id)).map((s) => s.id)).toEqual(['b', 'a', 'c'])
  })
})

describe('multiSectionCourses', () => {
  test('keeps only course names with two or more sections', () => {
    const got = multiSectionCourses([sec('1', '알고리즘'), sec('2', '알고리즘'), sec('3', '이산수학')])
    expect([...got.keys()]).toEqual(['알고리즘'])
    expect(got.get('알고리즘')?.map((s) => s.id)).toEqual(['1', '2'])
  })
})

describe('small helpers', () => {
  test('sectionTitle adds division when present', () => {
    expect(sectionTitle(sec('1', '알고리즘', { division: '(공통-재수강)' }))).toBe('알고리즘 (공통-재수강)')
    expect(sectionTitle(sec('1', '알고리즘'))).toBe('알고리즘')
  })

  test('profBuilding picks the first saved building', () => {
    expect(profBuilding([wish('a'), wish('b', { building: '문화관' })])).toBe('문화관')
    expect(profBuilding([])).toBeNull()
  })

  test('emptyWish starts from the section lab need', () => {
    expect(emptyWish(sec('1', 'A', { lab_need: 'MUST' }), '문화관')).toMatchObject({ lab: 'MUST', building: '문화관', cells: {} })
  })
})
