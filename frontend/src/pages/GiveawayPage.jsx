/**
 * frontend/src/pages/GiveawayPage.jsx
 * GIVEAWAY-1 — a group giveaway: /g/:slug. Shows the live slots-left counter and the rules, asks for the
 * "my finished site may be shown in the group" consent, then sends the visitor to a fresh brief form (/f/:token).
 * A slot is only taken when the form is submitted, so opening the form never uses one up.
 */
import { useCallback, useEffect, useState } from 'react'
import { getGiveaway, openGiveaway } from '../services/site_forms.service'
import { TermsList } from './giveawayTerms'

const TEAL = '#028090'
const S = {
  page: { minHeight: '100vh', background: '#f0f4f7', display: 'flex', justifyContent: 'center', padding: '24px 16px', fontFamily: "'DM Sans', system-ui, sans-serif", boxSizing: 'border-box' },
  card: { background: '#fff', borderRadius: 14, boxShadow: '0 2px 12px rgba(0,0,0,0.08)', padding: '24px 20px', width: '100%', maxWidth: 480, alignSelf: 'flex-start', boxSizing: 'border-box' },
  logo: { fontWeight: 800, fontSize: 20, color: TEAL, marginBottom: 2 },
  tag: { fontSize: 12, color: '#6b7f8d', margin: '0 0 14px' },
  h1: { fontSize: 22, fontWeight: 800, color: '#0a1f2e', margin: '0 0 6px', lineHeight: 1.25 },
  p: { fontSize: 14, lineHeight: 1.55, color: '#4a6375', margin: '0 0 12px' },
  li: { fontSize: 14, lineHeight: 1.5, color: '#2c4152', margin: '0 0 8px' },
  btn: { width: '100%', minHeight: 48, marginTop: 14, background: TEAL, color: '#fff', border: 0, borderRadius: 8, fontSize: 16, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit' },
  input: { width: '100%', boxSizing: 'border-box', minHeight: 44, padding: '10px 12px', border: '1px solid #c9d6de', borderRadius: 8, fontSize: 15, fontFamily: 'inherit', marginBottom: 10 },
  err: { color: '#b3261e', fontSize: 13, margin: '10px 0 0', minHeight: 18 },
}

function Counter({ g }) {
  const pct = g.total ? Math.round((g.taken / g.total) * 100) : 0
  return (
    <div style={{ background: '#eef7f8', borderRadius: 10, padding: 14, margin: '14px 0' }} role="status" aria-live="polite">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontSize: 28, fontWeight: 800, color: g.left ? TEAL : '#b3261e' }}>{g.left}</span>
        <span style={{ fontSize: 13, color: '#4a6375' }}>of {g.total} free slots left</span>
      </div>
      <div style={{ height: 8, background: '#d3e6ea', borderRadius: 4, marginTop: 8, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: g.left ? TEAL : '#b3261e' }} />
      </div>
    </div>
  )
}

export default function GiveawayPage({ slug }) {
  const [g, setG] = useState(null)
  const [state, setState] = useState('loading')   // loading | ready | notfound | error
  const [consent, setConsent] = useState(false)
  const [who, setWho] = useState({ name: '', phone: '', email: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    getGiveaway(slug)
      .then((d) => { setG(d); setState('ready') })
      .catch((e) => setState(e?.response?.status === 404 ? 'notfound' : 'error'))
  }, [slug])
  useEffect(() => {
    load()
    const id = setInterval(load, 30000)      // keep the counter fresh while the page stays open
    return () => clearInterval(id)
  }, [load])

  async function claim() {
    if (who.name.trim().length < 2) return setError('Please enter your name.')
    if (!/^[^@\s]+@[^@\s]+\.[^@\s.]{2,}$/.test(who.email.trim())) return setError('Please enter a valid email address.')
    if (who.phone.replace(/\D/g, '').length < 9) return setError('Please enter your WhatsApp number.')
    if (!consent) return setError('Please tick the box to continue.')
    setBusy(true); setError('')
    try {
      const data = await openGiveaway(slug, true, { name: who.name.trim(), phone: who.phone.trim(), email: who.email.trim() })
      const path = (() => { try { return new URL(data?.url, window.location.origin).pathname } catch { return '' } })()
      if (/^\/f\/[A-Za-z0-9_-]{20,80}$/.test(path)) { window.location.assign(path); return }
      setError('We couldn’t open the form. Please try again in a minute.')
    } catch (e) {
      const code = e?.response?.data?.detail?.code
      if (code === 'FULL' || code === 'CLOSED') load()
      setError(e?.response?.data?.detail?.message || 'We couldn’t open the form. Please check your connection and try again.')
    } finally { setBusy(false) }
  }

  return (
    <div style={S.page}>
      <div style={S.card}>
        <div style={S.logo}>opsra</div>
        <p style={S.tag}>In collaboration with Trust Robert Digital Empowerment Initiative</p>
        {state === 'loading' && <p style={S.p} role="status">Loading…</p>}
        {state === 'notfound' && (<><h1 style={S.h1}>This link isn’t valid</h1><p style={S.p}>Please check the link or ask the group admin for the right one.</p></>)}
        {state === 'error' && (<><h1 style={S.h1}>We couldn’t load this page</h1><p style={S.p}>Please check your connection and try again.</p></>)}
        {state === 'ready' && g && (
          <>
            <h1 style={S.h1}>{g.title}</h1>
            {g.owner_name && <p style={S.p}>For members of <strong>{g.owner_name}</strong>.</p>}
            <Counter g={g} />
            <ul style={{ paddingLeft: 18, margin: '0 0 8px' }}>
              <li style={S.li}>The <strong>first {g.total} people to submit complete details</strong> win a free website build.</li>
              <li style={S.li}>Use it for your own business, or for another business. One slot per WhatsApp number.</li>
              <li style={S.li}>Opening the form does not use a slot. A slot is taken when you submit.</li>
            </ul>
            <TermsList fee={g.fee_ngn} renewal={g.renewal_ngn} terms={g.terms} payByDays={g.pay_by_days} />
            {g.open ? (
              <>
                <p style={{ ...S.p, fontWeight: 700, margin: '0 0 8px' }}>Your details (we send your private page here)</p>
                <input style={S.input} placeholder="Your name" autoComplete="name" value={who.name} onChange={(e) => { setWho({ ...who, name: e.target.value }); setError('') }} />
                <input style={S.input} placeholder="WhatsApp number" autoComplete="tel" inputMode="tel" value={who.phone} onChange={(e) => { setWho({ ...who, phone: e.target.value }); setError('') }} />
                <input style={S.input} placeholder="Email address" autoComplete="email" inputMode="email" value={who.email} onChange={(e) => { setWho({ ...who, email: e.target.value }); setError('') }} />
                <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13.5, color: '#2c4152', lineHeight: 1.45 }}>
                  <input type="checkbox" checked={consent} onChange={(e) => { setConsent(e.target.checked); setError('') }} style={{ marginTop: 3 }} />
                  <span>I agree that the finished website will be shown in the group.</span>
                </label>
                <p style={S.err} aria-live="polite">{error}</p>
                <button type="button" style={{ ...S.btn, opacity: busy ? 0.7 : 1 }} disabled={busy} onClick={claim}>{busy ? 'Opening…' : 'Start my details form'}</button>
              </>
            ) : (
              <div role="status" style={{ background: '#fdf1f0', color: '#8a1c13', borderRadius: 10, padding: 14, fontSize: 14, lineHeight: 1.5 }}>
                {g.left === 0 ? 'All the free slots have been taken. Thank you for your interest.' : 'This giveaway is closed.'}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
