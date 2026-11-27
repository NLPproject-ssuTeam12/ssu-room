import { afterEach, describe, expect, test, vi } from 'vitest'
import { ApiError, EXPORT_URL, api, apiBase, coordPath, detailText } from './client'

afterEach(() => vi.unstubAllGlobals())

describe('detailText', () => {
  test('returns string detail as is', () => {
    expect(detailText({ detail: '희망은 수집 단계에서만 받습니다.' }, 409)).toBe('희망은 수집 단계에서만 받습니다.')
  })

  test('joins pydantic validation issues without the body prefix', () => {
    const body = { detail: [{ loc: ['body', 'cells'], msg: '칸 이름이 틀림' }, { loc: ['body'], msg: '필드 없음' }] }
    expect(detailText(body, 422)).toBe('cells: 칸 이름이 틀림 / 필드 없음')
  })

  test('falls back to status code', () => {
    expect(detailText(null, 500)).toBe('서버 오류 (500)')
  })
})

describe('apiBase', () => {
  test('follows the host the page was opened from (two-computer demo)', () => {
    expect(apiBase(undefined, { protocol: 'http:', hostname: '192.168.0.12' })).toBe('http://192.168.0.12:8000')
    expect(apiBase(undefined, { protocol: 'http:', hostname: 'localhost' })).toBe('http://localhost:8000')
  })

  test('uses VITE_API_BASE when set, without a trailing slash', () => {
    expect(apiBase('http://10.0.0.5:9000/', { protocol: 'http:', hostname: 'localhost' })).toBe('http://10.0.0.5:9000')
  })

  test('falls back to localhost when there is no page address', () => {
    expect(apiBase(undefined, undefined)).toBe('http://localhost:8000')
    expect(apiBase(undefined, { protocol: 'file:', hostname: '' })).toBe('http://localhost:8000')
  })
})

describe('api', () => {
  test('throws ApiError with server detail on 409', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: '단계가 아닙니다' }), { status: 409 })))
    await expect(api.health()).rejects.toMatchObject({ status: 409, message: '단계가 아닙니다' })
  })

  test('throws a connection message when fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const err = await api.sections().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(0)
  })

  test('posts JSON body for savePair', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ section_id: 's1', mode: 'NONE', order: [] }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await api.savePair({ section_id: 's1', mode: 'NONE' })
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toMatch(/\/wishes\/pair$/)
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ section_id: 's1', mode: 'NONE' })
  })
})

describe('paths', () => {
  test('encodes section ids with parentheses and Korean', () => {
    expect(coordPath('2150164403-(공통-재수강)')).toBe(`/coord/${encodeURIComponent('2150164403-(공통-재수강)')}`)
  })

  test('export link points at the server', () => {
    expect(EXPORT_URL).toMatch(/\/export\.xlsx$/)
  })
})

describe('step 6 calls', () => {
  test('finalize, reset and saveSettings post to the right paths', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await api.finalize()
    await api.reset()
    await api.saveSettings({ reveal_opponent: false })
    const calls = fetchMock.mock.calls as unknown as [string, RequestInit][]
    expect(calls.map(([u, i]) => `${i.method} ${u.replace(/^.*?:\d+/, '')}`)).toEqual(['POST /finalize', 'POST /reset', 'POST /settings'])
    expect(JSON.parse(String(calls[2][1].body))).toEqual({ reveal_opponent: false })
  })
})
