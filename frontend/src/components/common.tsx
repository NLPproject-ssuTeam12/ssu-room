import type { ReactNode } from 'react'

export function Chip({ k = '', children }: { k?: string; children: ReactNode }) {
  return <span className={`chip ${k}`}>{children}</span>
}
