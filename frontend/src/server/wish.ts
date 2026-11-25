// 서버 모드 희망 화면이 쓰는 순수 함수. 상태를 바꾸지 않고 새 값을 돌려준다 (wish.test.ts).
import { DAYS, STARTS } from '../api/types'
import type { CellKey, CellMark, Cells, Day, Section, Start, Wish } from '../api/types'

export const cellKey = (day: Day, start: Start): CellKey => `${day}-${start}`

/** 칸을 누를 때 순서: 빈칸 → 희망 → 불가 → 빈칸 */
export function nextMark(m: CellMark | undefined): CellMark | null {
  if (!m) return 'PREFER'
  return m === 'PREFER' ? 'BLOCK' : null
}

/** 칸 하나를 바꾼 새 cells. mark가 null이면 그 칸을 지운다 */
export function withCell(cells: Cells, key: CellKey, mark: CellMark | null): Cells {
  const rest = Object.fromEntries(Object.entries(cells).filter(([k]) => k !== key)) as Cells
  return mark ? { ...rest, [key]: mark } : rest
}

export const MARK_LABEL: Record<CellMark, string> = { PREFER: '희망', BLOCK: '불가' }
export const MARK_CLASS: Record<CellMark, string> = { PREFER: 'm-want', BLOCK: 'm-no' }

export function emptyWish(section: Section, building: string | null): Wish {
  return {
    section_id: section.id,
    professor: section.professor,
    cells: {},
    must: false,
    lab: section.lab_need,
    single_day: 'NONE',
    building,
    room: null,
    note: '',
  }
}

const countOf = (cells: Cells, mark: CellMark): number => Object.values(cells).filter((v) => v === mark).length

/** 희망 칸을 요일별로 모아 같은 시각끼리 묶는다. 예: "월·수 15:00 / 화 09:00, 10:30" */
export function preferText(cells: Cells): string {
  const groups: { days: Day[]; key: string }[] = []
  for (const d of DAYS) {
    const starts = STARTS.filter((s) => cells[cellKey(d, s)] === 'PREFER')
    if (!starts.length) continue
    const key = starts.join(', ')
    const g = groups.find((x) => x.key === key)
    if (g) g.days.push(d)
    else groups.push({ days: [d], key })
  }
  return groups.map((g) => `${g.days.join('·')} ${g.key}`).join(' / ')
}

export type ChipKind = '' | 'good' | 'bad' | 'warn' | 'lab'
export type ChipItem = [text: string, kind: ChipKind]

/** 접수한 희망을 칩으로 */
export function wishChips(wish: Wish): ChipItem[] {
  const prefer = preferText(wish.cells)
  const out: ChipItem[] = [prefer ? [`희망 ${prefer}`, 'good'] : ['희망 시간 없음 (아무 때나)', '']]
  const blocked = countOf(wish.cells, 'BLOCK')
  if (blocked) out.push([`불가 ${blocked}칸`, 'bad'])
  if (wish.lab === 'MUST') out.push(['실습실 필요', 'lab'])
  if (wish.single_day === 'MUST') out.push(['주 1회 연강', ''])
  if (wish.single_day === 'PREFER') out.push(['주 1회 연강 선호', ''])
  if (wish.building) out.push([`${wish.building} 선호`, ''])
  if (wish.note.trim()) out.push(['기타 요청 있음', 'warn'])
  return out
}

export const sectionTitle = (s: Section): string => (s.division ? `${s.name} ${s.division}` : s.name)

/** 조교 희망 확인 순서: 기타 요청 있는 분반 → 나머지 (원래 순서 유지) */
export function reviewOrder(sections: Section[], wishOf: (id: string) => Wish | undefined): Section[] {
  const hasNote = (s: Section) => !!wishOf(s.id)?.note.trim()
  return [...sections.filter(hasNote), ...sections.filter((s) => !hasNote(s))]
}

/** 한 교수가 같은 과목 분반을 둘 이상 맡은 경우만, 과목 이름 → 분반 목록 */
export function multiSectionCourses(sections: Section[]): Map<string, Section[]> {
  const byName = new Map<string, Section[]>()
  for (const s of sections) byName.set(s.name, [...(byName.get(s.name) ?? []), s])
  return new Map([...byName].filter(([, list]) => list.length >= 2))
}

const sortedCells = (cells: Cells): [string, string][] =>
  Object.entries(cells).filter((e): e is [string, CellMark] => !!e[1]).sort(([a], [b]) => a.localeCompare(b))

/** 저장할 값이 같은지 (칸 순서는 무시) */
export function wishEquals(a: Wish | undefined, b: Wish): boolean {
  if (!a) return false
  const { cells: ca, ...ra } = a
  const { cells: cb, ...rb } = b
  const keys = Object.keys(ra) as (keyof typeof ra)[]
  return keys.every((k) => ra[k] === rb[k]) && JSON.stringify(sortedCells(ca)) === JSON.stringify(sortedCells(cb))
}

/** 교수가 낸 희망 중 첫 건물 (서버는 건물을 교수당 하나로 저장한다) */
export function profBuilding(wishes: Wish[]): string | null {
  return wishes.find((w) => w.building)?.building ?? null
}
