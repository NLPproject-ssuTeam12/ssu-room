// 조교: 희망 확인 (서버 GET /sections, GET /wishes) + 초안 만들기 (POST /draft)
import { useState } from 'react'
import type { OtherRequest, Section, Wish } from '../../api/types'
import { Chip } from '../../components/common'
import { askConfirm, toast } from '../../ui'
import type { ServerData } from '../data'
import { makeDraft } from '../data'
import { CellLegend, MiniGrid } from '../CellGrid'
import { reviewOrder, sectionTitle, wishChips } from '../wish'
import { RequestConfirm } from '../RequestConfirm'

function SectionCell({ s }: { s: Section }) {
  return (
    <td>
      <b>{sectionTitle(s)}</b>
      <div className="small muted">
        {s.professor ?? '담당 미정'} · {s.year ? `${s.year}학년` : '전체 학년'} · {s.category || '구분 없음'}
      </div>
      <div className="small muted">{s.id}{s.enrollment ? ` · ${s.enrollment}명` : ''}</div>
    </td>
  )
}

function WishRow({ s, w, req }: { s: Section; w: Wish | undefined; req: OtherRequest | undefined }) {
  if (!w) {
    return (
      <tr className="flag">
        <SectionCell s={s} />
        <td colSpan={3}><Chip k="warn">희망 없음</Chip> <span className="small">아직 희망을 내지 않았습니다.</span></td>
      </tr>
    )
  }
  return (
    <tr className={w.note.trim() ? 'flag' : ''}>
      <SectionCell s={s} />
      <td><MiniGrid cells={w.cells} /></td>
      <td>{wishChips(w).map(([t, k]) => <Chip key={t} k={k}>{t}</Chip>)}</td>
      <td style={{ minWidth: 170 }}>
        {w.note.trim() ? <div className="small">{w.note}</div> : <span className="small muted">없음</span>}
        {w.note.trim() && req && <RequestConfirm key={req.id} req={req} />}
      </td>
    </tr>
  )
}

function DraftButton({ data, onDrafted }: { data: ServerData; onDrafted: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const collecting = data.health.stage === 'COLLECT'
  const run = async () => {
    setBusy(true)
    setError('')
    try {
      const r = await makeDraft()
      toast(`초안을 만들었습니다 · 조율 대상 ${r.coord.length}개`)
      onDrafted()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '초안을 만들지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }
  const onClick = () => askConfirm({
    title: '초안을 만들까요?',
    body: '지금 희망으로 초안을 만듭니다 (몇 초 걸립니다).\n만들면 희망 수집이 끝나서 교수님 희망 입력이 잠깁니다.',
    ok: '초안 만들기',
  }, () => { void run() })
  return (
    <>
      <div className="row" style={{ marginTop: 14 }}>
        <button className="btn primary" disabled={!collecting || busy} onClick={onClick}>{busy ? '초안 만드는 중…' : '초안 만들기'}</button>
        <span className="small muted">{collecting ? '규칙을 지키는 초안을 만듭니다.' : '초안을 이미 만들었습니다.'}</span>
      </div>
      {error && <p className="note" role="alert" style={{ background: 'var(--bad-soft)', marginTop: 8 }}>{error}</p>}
    </>
  )
}

export default function WishReview({ data, onDrafted }: { data: ServerData; onDrafted: () => void }) {
  const wishBy = new Map(data.wishes.map((w) => [w.section_id, w]))
  const auto = data.sections.filter((s) => s.shape !== 'MANUAL')
  const manual = data.sections.filter((s) => s.shape === 'MANUAL')
  const rows = reviewOrder(auto, (id) => wishBy.get(id))
  const missing = auto.filter((s) => !wishBy.has(s.id)).length
  const noteN = auto.filter((s) => wishBy.get(s.id)?.note.trim()).length
  const reqBy = new Map((data.requests ?? []).filter((r) => r.source === 'wish').map((r) => [r.section_id, r]))
  const notePending = [...reqBy.values()].filter((r) => r.status === 'PENDING').length
  const noProf = auto.filter((s) => !s.professor).length

  return (
    <>
      <h1 tabIndex={-1}>희망 확인</h1>
      <p className="lead">교수님이 낸 희망입니다. 이 값으로 시간표를 배정합니다. 기타 요청은 자동 배정에 들어가지 않아서 조교가 직접 확인합니다.</p>
      <div className="card">
        <div className="row" style={{ gap: 8 }}>
          <Chip>자동 배정 분반 {auto.length}개</Chip>
          <Chip k={missing ? 'warn' : 'good'}>희망 접수 {auto.length - missing}/{auto.length}</Chip>
          {noteN > 0 && <Chip k={notePending ? 'warn' : 'good'}>기타 요청 {noteN}건{data.requests ? ` · 미확인 ${notePending}` : ''}</Chip>}
          {noProf > 0 && <Chip k="warn">담당 미정 {noProf}개</Chip>}
          <Chip>직접 배정 분반 {manual.length}개</Chip>
          <Chip>강의실 {data.rooms.length}개 (실습실 {data.rooms.filter((r) => r.is_lab).length}개)</Chip>
        </div>
      </div>
      <div className="card">
        <div style={{ marginBottom: 10 }}><CellLegend /></div>
        <div className="tblwrap">
          <table>
            <tbody>
              <tr><th style={{ width: 190 }}>분반</th><th style={{ width: 110 }}>시간 칠하기</th><th>배정 조건</th><th>기타 요청 (조교 확인)</th></tr>
              {rows.map((s) => <WishRow key={s.id} s={s} w={wishBy.get(s.id)} req={reqBy.get(s.id)} />)}
            </tbody>
          </table>
        </div>
        <DraftButton data={data} onDrafted={onDrafted} />
      </div>
      <details className="card">
        <summary><b>직접 배정 분반 {manual.length}개</b> <span className="small muted">자동 배정·조율 대상이 아닙니다 (교양, 캡스톤 등)</span></summary>
        <ul className="small" style={{ marginTop: 8 }}>
          {manual.map((s) => <li key={s.id}>{sectionTitle(s)} · {s.professor ?? '담당 미정'} · {s.id}</li>)}
        </ul>
      </details>
    </>
  )
}
