/**
 * frontend/src/pages/WinnerPage.jsx
 * GIVEAWAY-1 — a giveaway winner's private page: /w/:token. Shows where the site is (being built, preview ready,
 * going live, live), the terms, and — once the preview is ready — the form to pay the giveaway fee with Paystack.
 * The amount is set by the server from the giveaway; nothing here sends a price.
 */
import { useCallback, useEffect, useState } from 'react'
import { getGiveawayWinner, checkWinnerDomain, payGiveawayWinner, buyWinnerItems, errorMessage } from '../services/site_forms.service'
import { TermsList, naira } from './giveawayTerms'

const TEAL = '#028090'
const S = {
  page: { minHeight: '100vh', background: '#f0f4f7', display: 'flex', justifyContent: 'center', padding: '24px 16px', fontFamily: "'DM Sans', system-ui, sans-serif", boxSizing: 'border-box' },
  card: { background: '#fff', borderRadius: 14, boxShadow: '0 2px 12px rgba(0,0,0,0.08)', padding: '24px 20px', width: '100%', maxWidth: 520, alignSelf: 'flex-start', boxSizing: 'border-box' },
  logo: { fontWeight: 800, fontSize: 20, color: TEAL, marginBottom: 2 },
  tag: { fontSize: 12, color: '#6b7f8d', margin: '0 0 14px' },
  h1: { fontSize: 22, fontWeight: 800, color: '#0a1f2e', margin: '0 0 6px', lineHeight: 1.25 },
  h2: { fontSize: 16, fontWeight: 800, color: '#0a1f2e', margin: '18px 0 8px' },
  p: { fontSize: 14, lineHeight: 1.55, color: '#4a6375', margin: '0 0 12px' },
  input: { width: '100%', boxSizing: 'border-box', minHeight: 44, padding: '10px 12px', border: '1px solid #c9d6de', borderRadius: 8, fontSize: 15, fontFamily: 'inherit', marginBottom: 8 },
  btn: { width: '100%', minHeight: 48, marginTop: 12, background: TEAL, color: '#fff', border: 0, borderRadius: 8, fontSize: 16, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit', textAlign: 'center', textDecoration: 'none', display: 'block', boxSizing: 'border-box', lineHeight: '48px' },
  err: { color: '#b3261e', fontSize: 13, margin: '8px 0 0', minHeight: 18 },
  note: { background: '#eef7f8', borderRadius: 10, padding: 14, fontSize: 14, lineHeight: 1.5, color: '#2c4152', margin: '12px 0' },
}

export default function WinnerPage({ token }) {
  const [v, setV] = useState(null)
  const [state, setState] = useState('loading')       // loading | ready | notfound | error
  const [f, setF] = useState({ domain: '', backup_domain: '', full_name: '', email: '', phone: '', address: '', accepted: false })
  const [dom, setDom] = useState(null)                // domain check result
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    getGiveawayWinner(token)
      .then((d) => {
        setV(d); setState('ready')
        setF((x) => ({ ...x, full_name: x.full_name || d.contact?.name || '', email: x.email || d.contact?.email || '', phone: x.phone || d.contact?.phone || '' }))
      })
      .catch((e) => setState(e?.response?.status === 404 ? 'notfound' : 'error'))
  }, [token])
  useEffect(() => {
    load()
    const id = setInterval(load, 60000)      // the page updates itself while it is waiting for the preview
    return () => clearInterval(id)
  }, [load])

  const set = (k) => (e) => { setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }); setError('') }

  async function check() {
    setError(''); setDom(null)
    if (f.domain.trim().length < 3) return setError('Type the domain you want first, for example yourbusiness.ng')
    try { setDom(await checkWinnerDomain(token, f.domain.trim())) } catch (e) { setError(errorMessage(e)) }
  }

  async function moreItems() {
    setBusy(true); setError('')
    try {
      const r = await buyWinnerItems(token)
      const url = (() => { try { return new URL(r?.checkout_url) } catch { return null } })()
      if (url && url.protocol === 'https:') { window.location.assign(url.href); return }
      setError('We couldn’t open the payment page. Please try again.')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }

  async function pay() {
    if (!f.domain.trim() || !f.backup_domain.trim()) return setError('Please enter the domain you want and a backup domain.')
    if (!f.full_name.trim() || !f.email.trim() || !f.phone.trim() || !f.address.trim()) return setError('Please fill in the owner details. They are used only to register the domain.')
    if (!f.accepted) return setError('Please tick the box to accept the terms.')
    setBusy(true); setError('')
    try {
      const r = await payGiveawayWinner(token, {
        domain: f.domain.trim(), backup_domain: f.backup_domain.trim(), accepted_terms: true,
        legal_owner: { full_name: f.full_name.trim(), email: f.email.trim(), phone: f.phone.trim(), address: f.address.trim() },
      })
      const url = (() => { try { return new URL(r?.checkout_url) } catch { return null } })()
      if (url && url.protocol === 'https:') { window.location.assign(url.href); return }
      setError('We couldn’t open the payment page. Please try again.')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }

  return (
    <div style={S.page}>
      <div style={S.card}>
        <div style={S.logo}>opsra</div>
        <p style={S.tag}>In collaboration with Trust Robert Digital Empowerment Initiative</p>
        {state === 'loading' && <p style={S.p} role="status">Loading…</p>}
        {state === 'notfound' && (<><h1 style={S.h1}>This link isn’t valid</h1><p style={S.p}>Please use the link we sent you by email or WhatsApp. If you can’t find it, contact the group admin.</p></>)}
        {state === 'error' && (<><h1 style={S.h1}>We couldn’t load this page</h1><p style={S.p}>Please check your connection and try again.</p></>)}
        {state === 'ready' && v && (
          <>
            <h1 style={S.h1}>{v.stage === 'expired' ? 'Your free website slot' : v.business_name ? `${v.business_name}: your free website slot` : 'Your free website slot'}</h1>
            <p style={S.p}>{v.position ? `Slot ${v.position} · ` : ''}{v.group_name}. Keep this link private. Anyone with it can see this page.</p>

            {v.stage === 'expired' && (
              <div style={{ ...S.note, background: '#fdf1f0', color: '#8a1c13' }} role="status">
                This slot was released because the domain and hosting fee wasn’t paid within {v.pay_by_days} days of the preview. Thank you for taking part.
              </div>
            )}
            {v.stage === 'building' && (
              <div style={S.note} role="status">We’re building your website now. Your preview will appear on this page within 24 hours. You pay nothing until you’ve seen it.</div>
            )}
            {v.stage === 'going_live' && (
              <div style={S.note} role="status">Payment received. Your website is being set up on your domain and will be live within 24 hours.</div>
            )}
            {v.stage === 'live' && (
              <div style={S.note} role="status">Your website is live{v.live_url ? <>: <a href={v.live_url} target="_blank" rel="noopener noreferrer">{v.live_url}</a></> : '.'}</div>
            )}

            {v.preview_url && v.stage !== 'live' && (
              <a href={v.preview_url} target="_blank" rel="noopener noreferrer" style={S.btn}>See my website preview</a>
            )}

            {v.stage === 'preview' && v.pay_by && (
              <div style={S.note} role="status">Pay by <strong>{new Date(v.pay_by).toLocaleString('en-NG', { dateStyle: 'medium', timeStyle: 'short' })}</strong>, or the slot is given to someone else.</div>
            )}

            <h2 style={S.h2}>The terms</h2>
            <TermsList fee={v.fee_ngn} renewal={v.renewal_ngn} terms={v.terms} payByDays={v.pay_by_days} />

            {v.can_buy_items && v.terms?.catalog_pack_items ? (
              <>
                <button type="button" onClick={moreItems} disabled={busy} style={{ ...S.btn, marginTop: 0, background: '#fff', color: TEAL, border: `1px solid ${TEAL}`, minHeight: 44, lineHeight: '42px', opacity: busy ? 0.7 : 1 }}>
                  Add {v.terms.catalog_pack_items} more items · {naira(v.terms.catalog_pack_price_ngn)}
                </button>
                <p style={S.err} aria-live="polite">{error}</p>
              </>
            ) : null}

            {v.can_pay && (
              <>
                <h2 style={S.h2}>Happy with it? Choose your domain and pay {naira(v.fee_ngn)}</h2>
                <input style={S.input} placeholder="Domain you want, e.g. yourbusiness.ng" value={f.domain} onChange={set('domain')} autoCapitalize="none" />
                <button type="button" onClick={check} style={{ ...S.btn, marginTop: 0, background: '#fff', color: TEAL, border: `1px solid ${TEAL}`, minHeight: 40, lineHeight: '38px' }}>Check if it’s available</button>
                {dom && (
                  <p style={{ ...S.p, marginTop: 8, color: dom.available === false ? '#b3261e' : '#1f7a4d' }} role="status">
                    {dom.available === false ? `${dom.domain} is taken.` : dom.available ? `${dom.domain} looks available.` : `We couldn’t confirm ${dom.domain} yet; we’ll confirm before buying.`}
                    {dom.available === false && dom.alternatives?.length ? ` Try: ${dom.alternatives.filter((a) => a.available).slice(0, 3).map((a) => a.domain).join(', ')}` : ''}
                  </p>
                )}
                <input style={{ ...S.input, marginTop: 8 }} placeholder="A backup domain, in case the first is taken" value={f.backup_domain} onChange={set('backup_domain')} autoCapitalize="none" />
                <p style={{ ...S.p, fontSize: 12.5, margin: '4px 0 8px' }}>Owner details (used only to register the domain in your name):</p>
                <input style={S.input} placeholder="Full name" value={f.full_name} onChange={set('full_name')} />
                <input style={S.input} placeholder="Email" inputMode="email" value={f.email} onChange={set('email')} />
                <input style={S.input} placeholder="Phone" inputMode="tel" value={f.phone} onChange={set('phone')} />
                <input style={S.input} placeholder="Address" value={f.address} onChange={set('address')} />
                <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13.5, color: '#2c4152', lineHeight: 1.45 }}>
                  <input type="checkbox" checked={f.accepted} onChange={set('accepted')} style={{ marginTop: 3 }} />
                  <span>I accept the terms above, including the refund rule and the yearly renewal of {naira(v.renewal_ngn)}.</span>
                </label>
                <p style={S.err} aria-live="polite">{error}</p>
                <button type="button" style={{ ...S.btn, border: 0, opacity: busy ? 0.7 : 1 }} disabled={busy} onClick={pay}>{busy ? 'Opening payment…' : `Pay ${naira(v.fee_ngn)} securely`}</button>
              </>
            )}
            {!v.can_pay && error && <p style={S.err}>{error}</p>}
          </>
        )}
      </div>
    </div>
  )
}
