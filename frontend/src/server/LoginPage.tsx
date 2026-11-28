// 통합 로그인: 조교 / 교수를 고르고, 교수면 이름까지 고른다.
// 서버에 계정 기능이 없어 비밀번호는 받지 않는다 (시연용).
import { useState } from 'react'
import type { FormEvent } from 'react'
import type { ServerData } from './data'
import { loginProfessors } from './session'
import type { Session } from './session'

type Role = Session['role']

const ROLES: { role: Role; title: string; desc: string }[] = [
  { role: 'ta', title: '학과사무실 조교', desc: '희망 확인 · 시간표 초안 · 조율 · 확정' },
  { role: 'prof', title: '교수', desc: '희망 시간 입력 · 공개 시간표 · 조율 메시지 답장' },
]

export default function LoginPage({ data, onLogin }: { data: ServerData; onLogin: (s: Session) => void }) {
  const profs = loginProfessors(data)
  const [role, setRole] = useState<Role>('ta')
  const [prof, setProf] = useState(profs[0] ?? '')
  const canLogin = role === 'ta' || profs.includes(prof)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!canLogin) return
    onLogin(role === 'ta' ? { role: 'ta' } : { role: 'prof', prof })
  }

  return (
    <form className="card login" onSubmit={submit} aria-labelledby="login-t">
      <h1 id="login-t" tabIndex={-1}>로그인</h1>
      <p className="lead">누구로 들어갈지 고르세요.</p>
      <div className="roles" role="radiogroup" aria-label="역할">
        {ROLES.map((r) => (
          <label key={r.role} className={`role${role === r.role ? ' on' : ''}`}>
            <input type="radio" name="role" value={r.role} checked={role === r.role} onChange={() => setRole(r.role)} />
            <b>{r.title}</b>
            <span className="small muted">{r.desc}</span>
          </label>
        ))}
      </div>
      {role === 'prof' && (
        <>
          <label className="lbl" htmlFor="login-prof">교수 이름</label>
          {profs.length > 0 ? (
            <select id="login-prof" value={prof} onChange={(e) => setProf(e.target.value)}>
              {profs.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          ) : <p className="small muted">희망을 받을 교수가 없습니다.</p>}
        </>
      )}
      <div className="row" style={{ marginTop: 16 }}>
        <button type="submit" className="btn primary" disabled={!canLogin}>로그인</button>
        <span className="small muted">시연용이라 비밀번호 없이 들어갑니다.</span>
      </div>
    </form>
  )
}
