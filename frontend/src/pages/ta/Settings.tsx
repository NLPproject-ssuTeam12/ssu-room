import { PRIO, ROOMS, RULES, S, log, reset } from '../../mock/demo'
import { act } from '../../store'
import { THEMES, applyTheme, askConfirm, savedTheme, toast } from '../../ui'
import { Chip } from '../../components/common'

export function ThemeSeg() {
  const cur = savedTheme()
  return (
    <div className="seg" role="group" aria-label="테마">
      {THEMES.map(([k, t]) => (
        <button key={k} type="button" className={cur === k ? 'on' : ''} aria-pressed={cur === k} onClick={() => applyTheme(k)}>{t}</button>
      ))}
    </div>
  )
}

const BOT_RULES = [
  '시간표는 배정 규칙으로 계산하고, AI 도우미는 그 결과만 전합니다',
  '바꾸는 요청은 결과를 먼저 보여 주고, 조교가 [적용]을 눌러야 반영합니다',
  '교수가 불가로 칠한 시간으로는 옮기지 않습니다',
  '시간표와 상관없는 질문에는 답하지 않습니다',
]

export default function Settings() {
  const onReset = () =>
    askConfirm({ title: '처음부터 다시 할까요?', body: '시연 상태를 모두 지웁니다.', ok: '다시 시작' }, () => {
      act(() => reset())
      toast('처음 상태로 돌렸습니다')
    })
  return (
    <>
      <h1 tabIndex={-1}>설정</h1>
      <p className="lead">학과마다 다른 규칙은 여기서 바꿉니다.</p>
      <div className="card">
        <h2>조율 메시지</h2>
        <label className="switch">
          <input type="checkbox" checked={S.reveal} onChange={(e) => act(() => {
            S.reveal = e.target.checked
            log('설정', `상대 교수 이름 알리기: ${S.reveal ? '켬' : '끔'}`)
          })} />
          <span>
            <b>겹친 상대 교수 이름 알리기</b>
            <br />
            <span className="small muted">켜면 "가 교수님의 자료구조 01 분반과 겹칩니다", 끄면 "다른 강의와 겹칩니다". 연차·우선순위 이유와 상대의 사정은 어느 쪽이든 쓰지 않습니다. 이미 보낸 메시지는 바뀌지 않습니다.</span>
          </span>
        </label>
        <div className="row" style={{ marginTop: 14 }}>
          <Chip>회신 기한 1주</Chip><Chip>기한 전 자동 재알림</Chip><Chip>최대 3차</Chip><Chip>메시지는 밀린 분반 교수에게만</Chip>
        </div>
      </div>
      <div className="cols">
        <div className="card">
          <h2>하드 규칙 (반드시 지킴)</h2>
          {RULES.map((r: string) => <div key={r} className="small" style={{ marginBottom: 4 }}>✓ {r}</div>)}
        </div>
        <div className="card">
          <h2>겹칠 때 우선순위 (예)</h2>
          {PRIO.map((p: string, i: number) => <div key={p} className="small" style={{ marginBottom: 4 }}>{i + 1}. {p}</div>)}
          <p className="small muted" style={{ margin: '8px 0 0' }}>항목과 가중치는 학과에서 정합니다. 교수에게 보내는 메시지에는 나오지 않습니다.</p>
        </div>
      </div>
      <div className="card">
        <h2>AI 도우미</h2>
        {BOT_RULES.map((t) => <div key={t} className="small" style={{ marginBottom: 4 }}>✓ {t}</div>)}
        <p className="note" style={{ margin: '10px 0 0' }}>
          AI 도우미가 하는 일: 의도 파악(이유 설명 · 이동 · 가정 실행 · 현황) → 정보 뽑기(과목 · 교수 · 요일 · 시각 · 강의실, "그 강의" 같은 말 포함) → 모자라면 되묻기 → 시간표 계산 → 결과 설명. 답 아래 'AI가 읽은 내용'을 펼치면 이 과정이 보입니다. 시안에서는 키워드 규칙으로 흉내 냅니다.
        </p>
      </div>
      <div className="card">
        <h2>강의실 목록</h2>
        <p className="small muted" style={{ margin: '-4px 0 10px' }}>학과사무실이 미리 넣어 둡니다. 실습실 여부와 정원을 보고 호수를 자동으로 정합니다. 바꿀 때는 AI 도우미에게 말하면 됩니다 (예: "알고리즘 미래관 410으로").</p>
        <div className="tblwrap">
          <table>
            <tbody>
              <tr><th>강의실</th><th>건물</th><th>실습실</th><th>정원</th></tr>
              {ROOMS.map((r: any) => (
                <tr key={r.id}>
                  <td><b>{r.id}</b></td><td>{r.bldg}</td>
                  <td>{r.lab ? <Chip k="lab">실습실</Chip> : <span className="muted">일반</span>}</td>
                  <td>{r.cap}명</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="card">
        <h2>화면</h2>
        <div className="row"><span className="small">테마</span><ThemeSeg /></div>
        <p className="small muted" style={{ margin: '8px 0 0' }}>시간표·확정 화면은 인쇄하면 메뉴와 버튼을 빼고 찍힙니다.</p>
      </div>
      <div className="card"><h2>시연</h2><button className="btn" onClick={onReset}>처음부터 다시</button></div>
    </>
  )
}
