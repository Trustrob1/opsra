/**
 * frontend/src/modules/billing/BillingBanner.jsx
 * ACCOUNT-PLANS AP-3 — a slim banner for owners / admins / ops managers when their plan is ending, ended or paused.
 * Shows nothing for anyone else, for a business that has no plan, or if anything fails.
 */
import { useEffect, useState } from 'react'
import { getPlan } from '../../services/accountPlan.service'
import { ds } from '../../utils/ds'

export default function BillingBanner({ role, onOpen }) {
  const [cur, setCur] = useState(null)
  useEffect(() => {
    if (!['owner', 'ops_manager', 'admin'].includes(role)) return undefined
    let live = true
    getPlan().then((d) => { if (live) setCur(d.current) }).catch(() => {})
    return () => { live = false }
  }, [role])
  if (!cur || cur.source !== 'paid') return null
  let text = null
  let tone = '#b45309'
  if (cur.status === 'paused') { text = `Your ${cur.label} plan is paused and its features are off. Renew to switch it back on.`; tone = '#b91c1c' }
  else if (cur.status === 'grace') text = `Your ${cur.label} plan has ended. Renew soon to keep everything on.`
  else if (cur.status === 'active' && cur.days_left <= 5) text = `Your ${cur.label} plan ends in ${cur.days_left} day${cur.days_left === 1 ? '' : 's'}.`
  if (!text) return null
  return (
    <div role="status" style={{ background: '#FFF7E6', borderBottom: `2px solid ${tone}`, color: tone, padding: '8px 16px', fontSize: 13, fontFamily: ds.fontDm, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
      <span style={{ flex: 1 }}>{text}</span>
      <button type="button" onClick={onOpen} style={{ minHeight: 36, padding: '4px 14px', borderRadius: 8, border: 0, background: tone, color: '#fff', fontWeight: 600, cursor: 'pointer' }}>Open Billing</button>
    </div>
  )
}
