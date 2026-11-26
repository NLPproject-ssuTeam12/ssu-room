import { ACT, PAT, S, SLOTS, confirmText, endOf, exportCsv, full, log, profsWithCourses, receiveConfirm, roomText, sendConfirms } from '../../mock/demo'
import { act } from '../../store'
import { askConfirm, toast } from '../../ui'
import { Chip } from '../../components/common'

const LEAD: Record<string, string> = {
  collect: '아직 초안이 없습니다.',
  draft: '아직 조율 전입니다.',
  round: '조율 중입니다. 조율이 끝나면 교수님께 확정을 요청합니다.',
  review: '조율이 끝났습니다. 최종 시간표를 교수님께 보내 확정을 받아 주세요.',
  confirm: '교수님 확정을 기다리고 있습니다. 모두 확정하면 내보낼 수 있습니다.',
  final: '모든 교수님이 확정한 시간표입니다. 엑셀로 내보내 SAP에 직접 입력합니다.',
}

/** 확정 요청: 보내기 전엔 미리 보기, 보낸 뒤엔 교수님별 확정 현황 */
function ConfirmCard() {
  if (S.stage === 'review') {
    const ps: string[] = profsWithCourses()
    const onSend = () =>
      askConfirm(
        { title: '확정 요청을 보낼까요?', body: `교수님 ${ps.length}명께 최종 시간표와 확정 요청 메시지를 보냅니다.\n모두 [확정]을 누르면 내보낼 수 있습니다.`, ok: '보내기' },
        () => { act(() => sendConfirms()); toast('확정 요청을 보냈습니다') },
      )
    return (
      <div className="card">
        <h2>최종 시간표 확정 요청</h2>
        <p className="small muted" style={{ margin: '-4px 0 10px' }}>강의가 있는 교수님 {ps.length}명께 각자의 최종 시간표와 확정 요청 메시지를 보냅니다. 교수님이 [확정]을 눌러 회신하면 끝납니다.</p>
        <div className="lbl">메시지 예시 ({ps[0]} 교수님)</div>
        <div className="msg">{confirmText(ps[0])}</div>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn primary" onClick={onSend}>확정 요청 보내기 ({ps.length}명)</button>
        </div>
      </div>
    )
  }
  if (S.stage !== 'confirm' && S.stage !== 'final') return null
  const done = S.confirms.filter((k: any) => k.reply).length
  const onManual = (k: any) =>
    askConfirm(
      { title: `${k.prof} 교수님 확정을 직접 처리할까요?`, body: '회신 없이 확정한 것으로 기록합니다.', ok: '확정 처리', reason: true, placeholder: '예: 전화로 확인함' },
      (reason) => act(() => {
        receiveConfirm(k, '', '조교 직접 처리')
        k.reply.reason = reason
        log('확정 요청', `${k.prof} 교수님: 조교 직접 처리 · 사유 "${reason}"`)
      }),
    )
  return (
    <div className="card">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0 }}>교수님 확정 {done}/{S.confirms.length}</h2>
        {S.stage === 'confirm' ? (
          <button className="btn" disabled={done >= S.confirms.length} onClick={() => act(() =>
            S.confirms.filter((k: any) => !k.reply).forEach((k: any) => receiveConfirm(k, '', '가상 회신')))}>가상 확정 받기 (시연용)</button>
        ) : <Chip k="good">모두 확정</Chip>}
      </div>
      <div className="tblwrap" style={{ marginTop: 8 }}>
        <table>
          <tbody>
            <tr><th>교수</th><th>강의</th><th>상태</th><th></th></tr>
            {S.confirms.map((k: any) => (
              <tr key={k.id}>
                <td><b>{k.prof} 교수</b></td>
                <td className="small">{ACT().filter((c: any) => c.prof === k.prof).map(full).join(', ')}</td>
                <td>
                  {k.reply ? <Chip k="good">{k.reply.from === '조교 직접 처리' ? '확정 (조교 처리)' : '확정함'}</Chip> : <Chip k="warn">회신 대기</Chip>}
                  {k.reply?.note && <div className="small">메모: {k.reply.note}</div>}
                  {k.reply?.reason && <div className="small muted">사유: {k.reply.reason}</div>}
                </td>
                <td>{!k.reply && S.stage === 'confirm' && <button className="btn small" onClick={() => onManual(k)}>직접 확정 처리</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="small muted" style={{ margin: '8px 0 0' }}>회신이 없으면 전화 등으로 확인한 뒤 [직접 확정 처리]를 누릅니다. 사유는 기록에 남습니다.</p>
    </div>
  )
}

export default function Final() {
  const onCsv = () => {
    try { exportCsv(); toast('CSV 파일을 내려받았습니다') } catch { toast('내려받지 못했습니다. 다시 눌러 주세요') }
  }
  return (
    <>
      <h1 tabIndex={-1}>확정·내보내기</h1>
      <p className="lead">{LEAD[S.stage]}</p>
      <ConfirmCard />
      <div className="card">
        {S.stage === 'collect' ? '초안이 없습니다.' : (
          <div className="tblwrap">
            <table>
              <tbody>
                <tr><th>학년</th><th>과목</th><th>분반</th><th>교수</th><th>요일</th><th>시간</th><th>강의실</th><th>비고</th></tr>
                {S.courses.filter((c: any) => S.assign[c.id]).map((c: any) => {
                  const a = S.assign[c.id]
                  return (
                    <tr key={c.id}>
                      <td>{c.year}</td><td>{c.name}</td><td>{c.sec}</td><td>{c.prof} 교수</td>
                      <td>{PAT[a.pat].label}</td><td>{SLOTS[a.slot]}~{endOf(a.slot)}</td><td>{roomText(a.pat, a.rooms)}</td>
                      <td>{S.moved[c.id] ? <Chip k="accent">AI 도우미로 조정</Chip> : S.reason[c.id] ? <Chip k="good">조율 후 확정</Chip> : null}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="row" style={{ marginTop: 14 }}>
          <button className="btn primary" disabled={S.stage !== 'final'} onClick={onCsv}>엑셀(CSV) 내보내기</button>
          <button className="btn" disabled={S.stage === 'collect'} onClick={() => window.print()}>인쇄</button>
          <span className="small muted">
            {S.stage === 'final' ? '' : '교수님이 모두 확정해야 내보낼 수 있습니다. '}SAP 직접 연동은 범위 밖입니다. 엑셀(.xlsx) 내보내기는 서버 연결 뒤에 붙입니다.
          </span>
        </div>
      </div>
    </>
  )
}
