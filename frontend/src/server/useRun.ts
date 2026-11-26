// 서버를 바꾸는 버튼에 쓰는 훅: 누르는 동안 busy, 실패하면 error 글, 성공하면 다시 불러오고 알림
import { useState } from 'react'
import { toast } from '../ui'
import { mutate } from './data'

export interface Runner {
  busy: boolean
  error: string
  run: <T>(call: () => Promise<T>, okMessage?: string) => Promise<T | undefined>
}

export function useRun(): Runner {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const run = async <T,>(call: () => Promise<T>, okMessage?: string): Promise<T | undefined> => {
    setBusy(true)
    setError('')
    try {
      const out = await mutate(call)
      if (okMessage) toast(okMessage)
      return out
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '처리하지 못했습니다.')
      return undefined
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, run }
}
