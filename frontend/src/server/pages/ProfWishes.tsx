// 교수: 희망 입력 (서버 POST /wishes, POST /wishes/pair)
import { useState } from 'react'
import type { LabNeed, PairMode, Section, SingleDay, Wish } from '../../api/types'
import { Chip } from '../../components/common'
import { toast } from '../../ui'
import type { ServerData } from '../data'
import { saveProfBuilding, savePair, saveWish } from '../data'
import { CellLegend, PaintGrid } from '../CellGrid'
import { emptyWish, multiSectionCourses, profBuilding, sectionTitle, wishChips, wishEquals } from '../wish'

const errorText = (e: unknown): string => (e instanceof Error ? e.message : '저장하지 못했습니다.')

interface WishFormProps {
  section: Section
  saved: Wish | undefined
  building: string | null
  locked: boolean
}

function WishForm({ section, saved, building, locked }: WishFormProps) {
  const [draft, setDraft] = useState<Wish>(() => saved ?? emptyWish(section, building))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const toSave: Wish = { ...draft, building }
  const dirty = !wishEquals(saved, toSave)
  const update = (patch: Partial<Wish>) => setDraft((w) => ({ ...w, ...patch }))
  // 저장하는 동안 입력을 잠근다 (늦게 온 응답이 그사이 입력을 덮지 않게)
  const frozen = locked || busy

  const onSave = async () => {
    setBusy(true)
    setError('')
    try {
      const got = await saveWish(toSave)
      setDraft(got)
      toast(`${sectionTitle(section)} 희망을 저장했습니다`)
    } catch (e: unknown) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <h2>{sectionTitle(section)} <span className="small muted">{section.year ? `${section.year}학년` : '전체 학년'} · {section.category}</span></h2>
      <div className="pw">
        <div>
          <span className="lbl">수업 가능 시간</span>
          <PaintGrid id={section.id} title={sectionTitle(section)} cells={draft.cells} locked={frozen}
            onChange={(cells) => update({ cells })} />
          <div style={{ marginTop: 8 }}><CellLegend /></div>
          <p className="small muted" style={{ margin: '6px 0 0' }}>안 칠한 칸은 수업 가능입니다. 누를 때마다 희망 → 불가 → 빈칸으로 바뀌고, 끌면 여러 칸을 한 번에 칠합니다. 키보드는 화살표로 옮기고 Enter로 바꿉니다.</p>
        </div>
        <div>
          <div className="row" style={{ gap: 14, alignItems: 'flex-end' }}>
            <div>
              <div className="lbl">실습실</div>
              <select aria-label="실습실" value={draft.lab} disabled={frozen} onChange={(e) => update({ lab: e.target.value as LabNeed })}>
                <option value="NONE">필요 없음</option><option value="MUST">필요</option>
              </select>
            </div>
            <div>
              <div className="lbl">주 1회 연강</div>
              <select aria-label="주 1회 연강" value={draft.single_day === 'MUST' ? 'MUST' : 'NONE'} disabled={frozen}
                onChange={(e) => update({ single_day: e.target.value as SingleDay })}>
                <option value="NONE">주 2회 (기본)</option><option value="MUST">주 1회 연강</option>
              </select>
            </div>
          </div>
          <div className="lbl">기타 요청 <span className="muted small">(위 칸으로 정할 수 없는 것만)</span></div>
          <textarea value={draft.note} disabled={frozen} placeholder="예: 학기 중 두 번 대강이 필요합니다. 학과사무실에서 직접 확인합니다."
            onChange={(e) => update({ note: e.target.value })} />
          <div className="lbl">접수 내용</div>
          <div>{wishChips(toSave).map(([t, k]) => <Chip key={t} k={k}>{t}</Chip>)}</div>
          {!locked && (
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn primary" disabled={!dirty || busy} onClick={onSave}>{busy ? '저장 중…' : '저장'}</button>
              <span className="small muted">{dirty ? '저장하지 않은 변경이 있습니다.' : saved ? '저장했습니다.' : '아직 낸 희망이 없습니다.'}</span>
            </div>
          )}
          {error && <p className="note" role="alert" style={{ background: 'var(--bad-soft)', marginTop: 8 }}>{error}</p>}
        </div>
      </div>
    </div>
  )
}

interface BuildingCardProps {
  prof: string
  buildings: string[]
  saved: string | null
  hasWishes: boolean
  locked: boolean
  onChange: (b: string | null) => void
  value: string | null
}

/** 희망 건물은 교수당 하나 (#16). 서버는 희망 하나를 저장할 때 교수 건물을 바꾸므로 한 번만 보낸다 */
function BuildingCard({ prof, buildings, saved, hasWishes, locked, onChange, value }: BuildingCardProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const onSave = async () => {
    setBusy(true)
    setError('')
    try {
      await saveProfBuilding(prof, value)
      toast('희망 건물을 저장했습니다')
    } catch (e: unknown) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="card">
      <h2>희망 건물</h2>
      <div className="row">
        <select aria-label="희망 건물" value={value ?? ''} disabled={locked} onChange={(e) => onChange(e.target.value || null)}>
          <option value="">상관없음</option>
          {buildings.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
        {!locked && hasWishes && (
          <button className="btn small" disabled={busy || value === saved} onClick={onSave}>{busy ? '저장 중…' : '이미 낸 희망에 적용'}</button>
        )}
        <span className="small muted">맡은 강의 전체에 하나만 적용됩니다. 강의실 호수는 학과사무실에서 정합니다.</span>
      </div>
      {error && <p className="note" role="alert" style={{ background: 'var(--bad-soft)', marginTop: 8 }}>{error}</p>}
    </div>
  )
}

const PAIR_LABEL: Record<PairMode, string> = { NONE: '따로 놓기', BACK_TO_BACK: '분반 연강', CROSS: '분반 교차' }
const PAIR_TIP: Record<PairMode, string> = {
  NONE: '분반을 따로 놓습니다',
  BACK_TO_BACK: '두 분반을 같은 날 이어서 (첫째→둘째, 첫째→둘째)',
  CROSS: '이어서 하되 날마다 순서를 바꿈 (첫째→둘째, 둘째→첫째)',
}

/** 같은 과목 분반 둘 이상: 연강·교차와 붙일 순서 (최대 두 분반) */
function PairRow({ name, list, locked }: { name: string; list: Section[]; locked: boolean }) {
  const [mode, setMode] = useState<PairMode>('NONE')
  const [first, setFirst] = useState(list[0].id)
  const [second, setSecond] = useState(list[1].id)
  const [busy, setBusy] = useState(false)
  const [savedText, setSavedText] = useState('')
  const [error, setError] = useState('')
  const titleOf = (id: string) => sectionTitle(list.find((s) => s.id === id) ?? list[0])
  const badOrder = mode !== 'NONE' && first === second

  const onSave = async () => {
    setBusy(true)
    setError('')
    try {
      const r = await savePair({ section_id: list[0].id, mode, order: mode === 'NONE' ? undefined : [first, second] })
      setSavedText(r.mode === 'NONE' ? '따로 놓기로 저장함' : `${PAIR_LABEL[r.mode]} 저장함: ${r.order.map(titleOf).join(' → ')}`)
    } catch (e: unknown) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const pick = (value: string, set: (v: string) => void, label: string) => (
    <select aria-label={`${name} ${label}`} value={value} disabled={locked} onChange={(e) => set(e.target.value)}>
      {list.map((s) => <option key={s.id} value={s.id}>{sectionTitle(s)}</option>)}
    </select>
  )
  return (
    <div style={{ marginTop: 8 }}>
      <div className="row">
        <b style={{ minWidth: 120 }}>{name}</b>
        <select aria-label={`${name} 분반 배치`} value={mode} disabled={locked} onChange={(e) => setMode(e.target.value as PairMode)}>
          {(Object.keys(PAIR_LABEL) as PairMode[]).map((k) => <option key={k} value={k}>{PAIR_LABEL[k]}</option>)}
        </select>
        {mode !== 'NONE' && <>{pick(first, setFirst, '첫째 분반')}<span>→</span>{pick(second, setSecond, '둘째 분반')}</>}
        {!locked && <button className="btn small" disabled={busy || badOrder} onClick={onSave}>{busy ? '저장 중…' : '저장'}</button>}
      </div>
      <div className="small muted" style={{ marginTop: 4 }}>
        {badOrder ? '서로 다른 분반 두 개를 골라 주세요.' : PAIR_TIP[mode]}{savedText && <> · <b>{savedText}</b></>}
      </div>
      {error && <p className="note" role="alert" style={{ background: 'var(--bad-soft)', marginTop: 6 }}>{error}</p>}
    </div>
  )
}

export default function ProfWishes({ data, prof }: { data: ServerData; prof: string }) {
  const mine = new Set(data.professors[prof]?.sections ?? [])
  const sections = data.sections.filter((s) => mine.has(s.id))
  const auto = sections.filter((s) => s.shape !== 'MANUAL')
  const manual = sections.filter((s) => s.shape === 'MANUAL')
  const myWishes = data.wishes.filter((w) => mine.has(w.section_id))
  const savedBuilding = profBuilding(myWishes)
  const [building, setBuilding] = useState<string | null>(savedBuilding)
  const buildings = [...new Set(data.rooms.map((r) => r.building))]
  const locked = data.health.stage !== 'COLLECT'
  const pairs = [...multiSectionCourses(auto)]

  return (
    <>
      <h1 tabIndex={-1}>희망 입력</h1>
      <p className="lead">{prof} · 맡은 분반 {auto.length}개{locked ? ' · 접수가 마감되어 읽기만 됩니다' : ' · 분반마다 [저장]을 눌러야 반영됩니다'}</p>
      {!auto.length && <div className="card muted">자동 배정할 담당 분반이 없습니다.</div>}
      {auto.length > 0 && (
        <BuildingCard prof={prof} buildings={buildings} saved={savedBuilding} hasWishes={myWishes.length > 0} locked={locked} value={building} onChange={setBuilding} />
      )}
      {pairs.length > 0 && (
        <div className="card">
          <h2>같은 과목 분반끼리</h2>
          <p className="small muted" style={{ margin: '-4px 0 6px' }}>저장한 값은 아직 서버에서 다시 읽어 올 수 없어서, 새로 열면 &lsquo;따로 놓기&rsquo;로 보입니다.</p>
          {pairs.map(([name, list]) => <PairRow key={name} name={name} list={list} locked={locked} />)}
        </div>
      )}
      {auto.map((s) => (
        <WishForm key={s.id} section={s} saved={data.wishes.find((w) => w.section_id === s.id)} building={building} locked={locked} />
      ))}
      {manual.length > 0 && (
        <p className="note">직접 배정 분반 {manual.length}개({manual.map(sectionTitle).join(', ')})는 학과사무실에서 정해서 희망을 받지 않습니다.</p>
      )}
    </>
  )
}
