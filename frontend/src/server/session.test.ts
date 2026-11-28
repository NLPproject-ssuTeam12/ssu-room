import { afterEach, describe, expect, test } from 'vitest'
import type { ServerData } from './data'
import { checkSession, loadSession, loginProfessors, parseSession, saveSession } from './session'

const store = new Map<string, string>()
const fakeStorage = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => { store.set(k, v) },
  removeItem: (k: string) => { store.delete(k) },
}

afterEach(() => store.clear())

describe('parseSession', () => {
  test('reads a TA session', () => {
    expect(parseSession('{"role":"ta"}')).toEqual({ role: 'ta' })
  })

  test('reads a professor session with a name', () => {
    expect(parseSession('{"role":"prof","prof":"교수07"}')).toEqual({ role: 'prof', prof: '교수07' })
  })

  test('rejects broken or incomplete values', () => {
    expect(parseSession(null)).toBeNull()
    expect(parseSession('not json')).toBeNull()
    expect(parseSession('{"role":"prof"}')).toBeNull()
    expect(parseSession('{"role":"prof","prof":""}')).toBeNull()
    expect(parseSession('{"role":"admin"}')).toBeNull()
  })
})

describe('save and load', () => {
  test('round-trips through storage and clears on logout', () => {
    saveSession({ role: 'prof', prof: '교수07' }, fakeStorage)
    expect(loadSession(fakeStorage)).toEqual({ role: 'prof', prof: '교수07' })
    saveSession(null, fakeStorage)
    expect(loadSession(fakeStorage)).toBeNull()
  })

  test('returns null when storage throws', () => {
    const broken = { getItem: () => { throw new Error('blocked') }, setItem: () => {}, removeItem: () => {} }
    expect(loadSession(broken)).toBeNull()
  })
})

const data = {
  sections: [
    { id: 'a1', shape: 'TWO_DAY' },
    { id: 'm1', shape: 'MANUAL' },
  ],
  professors: {
    교수09: { sections: ['a1'] },
    교수02: { sections: ['a1'] },
    교수30: { sections: ['m1'] },
  },
} as unknown as ServerData

describe('loginProfessors', () => {
  test('lists professors with auto-placed sections in name order', () => {
    expect(loginProfessors(data)).toEqual(['교수02', '교수09'])
  })
})

describe('checkSession', () => {
  test('keeps TA and known professors', () => {
    expect(checkSession({ role: 'ta' }, data)).toEqual({ role: 'ta' })
    expect(checkSession({ role: 'prof', prof: '교수09' }, data)).toEqual({ role: 'prof', prof: '교수09' })
  })

  test('drops a professor who is not in the data any more', () => {
    expect(checkSession({ role: 'prof', prof: '교수30' }, data)).toBeNull()
    expect(checkSession(null, data)).toBeNull()
  })
})
