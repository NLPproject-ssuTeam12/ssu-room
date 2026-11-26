import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { closeDialog, getDialog, getToast } from '../ui'

export function Toast() {
  const text = getToast()
  return (
    <div id="toast" role="status" aria-live="polite" className={text ? 'on' : ''}>
      {text}
    </div>
  )
}

/** 적용·확정 전에 한 번 더 묻는 창. reason이면 사유를 꼭 받는다 */
export function ConfirmDialog() {
  const dlg = getDialog()
  const ref = useRef<HTMLDialogElement>(null)
  const [reason, setReason] = useState('')
  const [err, setErr] = useState('')

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (dlg && !el.open) {
      setReason('')
      setErr('')
      el.showModal()
    } else if (!dlg && el.open) el.close()
  }, [dlg])

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!dlg) return
    const r = reason.trim()
    if (dlg.opts.reason && !r) {
      setErr('사유를 적어 주세요.')
      return
    }
    const cb = dlg.onOk
    closeDialog()
    cb(r)
  }

  return (
    <dialog id="dlg" ref={ref} aria-labelledby="dlg-t" onClose={() => { if (getDialog()) closeDialog() }}>
      {dlg && (
        <form onSubmit={onSubmit}>
          <h2 id="dlg-t">{dlg.opts.title}</h2>
          <p className="small" style={{ margin: '0 0 6px', whiteSpace: 'pre-line' }}>{dlg.opts.body}</p>
          {dlg.opts.reason && (
            <>
              <label className="lbl" htmlFor="dlg-r">사유 (필수, 기록에 남음)</label>
              <input type="text" id="dlg-r" autoComplete="off" autoFocus value={reason}
                placeholder={dlg.opts.placeholder || ''} onChange={(e) => setReason(e.target.value)} />
              <div className="prob" role="alert">{err}</div>
            </>
          )}
          <div className="row" style={{ justifyContent: 'flex-end', marginTop: 14 }}>
            <button type="button" className="btn" onClick={closeDialog}>취소</button>
            <button type="submit" className="btn primary" autoFocus={!dlg.opts.reason}>{dlg.opts.ok || '확인'}</button>
          </div>
        </form>
      )}
    </dialog>
  )
}
