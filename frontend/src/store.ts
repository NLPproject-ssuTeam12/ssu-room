import { useSyncExternalStore } from 'react'

// 시연 상태(mock/demo.js의 S)는 한 곳에서 바뀌고, 바뀔 때마다 버전을 올려 화면을 다시 그린다.
// 2단계에서 서버 데이터로 바뀌면 이 파일은 fetch 결과를 들고 있는 곳이 된다.
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

/** 상태를 바꾸는 함수를 실행하고 화면을 다시 그린다 */
export function act(fn: () => void): void {
  fn()
  notify()
}
