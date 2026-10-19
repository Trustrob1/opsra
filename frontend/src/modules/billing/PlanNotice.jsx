/**
 * frontend/src/modules/billing/PlanNotice.jsx
 * ACCOUNT-PLANS AP-6 - a small notice that appears when something the person tried is not in their plan.
 * Owners, admins and ops managers get a button to Billing; everyone else is told to ask their account owner.
 * Appears once per burst of failed calls, goes away by itself, and can be closed.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { PLAN_EVENT, PLAN_FALLBACK } from '../../utils/planNotice'
import { ds } from '../../utils/ds'

const SHOW_MS = 9000

export default function PlanNotice({ role, onOpenBilling }) {
  const [msg, setMsg] = useState(null)
  const timer = useRef(null)
  const canBill = ['owner', 'ops_manager', 'admin'].includes(role)

  const close = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    setMsg(null)
  }, [])

  useEffect(() => {
    const on = (e) => {
      setMsg((e && e.detail && e.detail.message) || PLAN_FALLBACK)
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => setMsg(null), SHOW_MS)
    }
    window.addEventListener(PLAN_EVENT, on)
    return () => { window.removeEventListener(PLAN_EVENT, on); if (timer.current) clearTimeout(timer.current) }
  }, [])

  useEffect(() => {
    if (!msg) return undefined
    const onKey = (e) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [msg, close])

  if (!msg) return null
  const text = canBill ? msg : "This isn't included in your plan. Ask your account owner to upgrade."
  return (
    <div role="status" aria-live="polite" style={{
      position: 'fixed', left: 16, right: 16, bottom: 16, margin: '0 auto', maxWidth: 520, zIndex: 3000,
      background: ds.dark, color: '#fff', borderRadius: 12, padding: '12px 14px', display: 'flex', gap: 12, alignItems: 'center',
      boxShadow: '0 8px 28px rgba(13,27,42,0.35)', fontFamily: ds.fontDm, fontSize: 13, lineHeight: 1.45,
      borderLeft: `4px solid ${ds.accent}`,
    }}>
      <span style={{ flex: 1 }}>{text}</span>
      {canBill && (
        <button type="button" onClick={() => { close(); onOpenBilling && onOpenBilling() }}
          style={{ minHeight: 36, padding: '4px 14px', borderRadius: 8, border: 0, background: ds.accent, color: ds.dark, fontWeight: 700, fontFamily: ds.fontDm, cursor: 'pointer' }}>
          Open Billing
        </button>
      )}
      <button type="button" onClick={close} aria-label="Dismiss"
        style={{ minHeight: 36, minWidth: 36, borderRadius: 8, border: 0, background: 'transparent', color: '#fff', fontSize: 18, cursor: 'pointer' }}>×</button>
    </div>
  )
}
