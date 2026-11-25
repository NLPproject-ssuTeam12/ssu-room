// Codex 리뷰(2026-11-26)에서 재현된 순서를 회귀 테스트로 둔다.
import { beforeEach, describe, expect, test, vi } from 'vitest'
import type { Health, Section, Wish } from '../api/types'

const api = vi.hoisted(() => ({
  health: vi.fn(), sections: vi.fn(), rooms: vi.fn(), wishes: vi.fn(), timetable: vi.fn(), coord: vi.fn(),
  saveWish: vi.fn(), draft: vi.fn(),
}))
vi.mock('../api/client', () => ({ api }))

const data = await import('./data')

const health = (stage: Health['stage'] = 'COLLECT'): Health => ({ ok: true, data_set: 'real', stage, round_no: 0, engine: {}, load_warnings: [] })
const sec = (id: string): Section => ({
  id, code: id, name: id, division: null, year: 1, category: '', enrollment: 30, weekly_blocks: 2, professor: 'P', lab_need: 'NONE', shape: 'TWICE',
})
const wish = (id: string, extra: Partial<Wish> = {}): Wish => ({
  section_id: id, professor: 'P', cells: {}, must: false, lab: 'NONE', single_day: 'NONE', building: '문화관', room: null, note: '', ...extra,
})
const deferred = <T,>() => {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}
const professors = { P: { sections: ['a', 'b'] } }

function serverReturns(wishes: Wish[], stage: Health['stage'] = 'COLLECT') {
  api.health.mockResolvedValue(health(stage))
  api.sections.mockResolvedValue([sec('a'), sec('b')])
  api.rooms.mockResolvedValue([])
  api.wishes.mockResolvedValue({ wishes, professors })
  api.timetable.mockResolvedValue(null)
  api.coord.mockResolvedValue([])
}

const ready = () => {
  const s = data.getState()
  if (s.status !== 'ready') throw new Error(`not ready: ${s.status}`)
  return s.data
}

beforeEach(() => {
  vi.clearAllMocks()
  data.resetForTest()
})

describe('loadAll', () => {
  test('drops a slower older load that finishes after a newer one', async () => {
    serverReturns([wish('a', { note: 'old' })])
    const slow = deferred<Health>()
    api.health.mockReturnValueOnce(slow.promise)
    const first = data.loadAll()
    api.wishes.mockResolvedValue({ wishes: [wish('a', { note: 'new' })], professors })
    await data.loadAll()
    slow.resolve(health())
    await first
    expect(ready().wishes[0].note).toBe('new')
  })

  test('keeps section notes across reloads', async () => {
    serverReturns([wish('a')])
    await data.loadAll()
    data.addNote('a', '규칙 경고')
    await data.loadAll()
    expect(ready().notes).toEqual({ a: ['규칙 경고'] })
    data.clearNotes('a')
    expect(ready().notes).toEqual({})
  })
})

describe('applySavedWish', () => {
  test('copies the saved building to the same professor’s other wishes', async () => {
    serverReturns([wish('a'), wish('b')])
    await data.loadAll()
    const next = data.applySavedWish(ready(), wish('a', { building: '정보과학관' }))
    expect(next.wishes.find((w) => w.section_id === 'b')?.building).toBe('정보과학관')
  })
})

describe('saveWish and saveProfBuilding', () => {
  test('a load started before a save cannot overwrite the saved wish', async () => {
    serverReturns([wish('a')])
    await data.loadAll()
    const slow = deferred<Health>()
    api.health.mockReturnValueOnce(slow.promise)
    const load = data.loadAll()
    api.saveWish.mockResolvedValueOnce({ saved: wish('a', { note: 'saved' }) })
    await data.saveWish(wish('a', { note: 'saved' }))
    slow.resolve(health())
    await load
    expect(ready().wishes.find((w) => w.section_id === 'a')?.note).toBe('saved')
  })

  test('building change waits for a pending save and sends only the latest wish once', async () => {
    serverReturns([wish('a'), wish('b')])
    await data.loadAll()
    const first = deferred<{ saved: Wish }>()
    api.saveWish.mockReturnValueOnce(first.promise)
    api.saveWish.mockImplementation(async (w: Wish) => ({ saved: w }))
    const cellsSaved = data.saveWish(wish('a', { cells: { '월-09:00': 'BLOCK' } }))
    const buildingSaved = data.saveProfBuilding('P', '정보과학관')
    first.resolve({ saved: wish('a', { cells: { '월-09:00': 'BLOCK' } }) })
    await cellsSaved
    await buildingSaved
    expect(api.saveWish).toHaveBeenCalledTimes(2)
    const sent = api.saveWish.mock.calls[1][0] as Wish
    expect(sent.building).toBe('정보과학관')
    expect(ready().wishes.every((w) => w.building === '정보과학관')).toBe(true)
    expect(ready().wishes.find((w) => w.section_id === 'a')?.cells).toEqual({ '월-09:00': 'BLOCK' })
  })

  test('building change without any saved wish is an error', async () => {
    serverReturns([])
    await data.loadAll()
    await expect(data.saveProfBuilding('P', '문화관')).rejects.toThrow(/먼저/)
  })
})

describe('mutate', () => {
  test('reloads from the server even when the call fails, then rethrows', async () => {
    serverReturns([wish('a')])
    await data.loadAll()
    api.health.mockResolvedValue(health('DRAFT'))
    await expect(data.mutate(() => Promise.reject(new Error('message failed')))).rejects.toThrow('message failed')
    expect(ready().health.stage).toBe('DRAFT')
  })
})
