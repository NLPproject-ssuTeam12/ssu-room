import { useSyncExternalStore } from 'react'

// 알림·확인창·테마·서버 데이터가 바뀔 때마다 버전을 올려 화면을 다시 그린다.
let version = 0
const subscribers = new Set<() => void>()

export function notify(): void {
  version += 1
  subscribers.forEach((fn) => fn())
}

export function useVersion(): number {
  return useSyncExternalStore(
    (cb) => {
      subscribers.add(cb)
      return () => subscribers.delete(cb)
    },
    () => version,
  )
}
