/**
 * frontend/src/pages/PartnerPage.jsx
 * PARTNER-1B — Launch Partners.
 *   /partner              Sign in (email or WhatsApp number → link sent to both) | Apply (details → emailed code → waits for approval)
 *   /partner/login?t=…    the single-use sign-in link → partner portal (client link + referrals)
 * Standalone page, no staff auth. The session token is kept in memory only.
 */
import { useEffect, useState } from 'react'
import {
  startApplication, verifyApplication, requestPartnerLink, exchangeBuilderToken,
  getPartnerMe, getPartnerReferrals, previewUrl, errorMessage,
} from '../services/partner_portal.service'

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s.]{2,}$/
const TEAL = '#028090'
const S = {
  page: { minHeight: '100vh', background: '#f0f4f7', display: 'flex', justifyContent: 'center', padding: '24px 16px', fontFamily: "'DM Sans', system-ui, sans-serif", boxSizing: 'border-box' },
  card: { background: '#fff', borderRadius: 14, boxShadow: '0 2px 12px rgba(0,0,0,0.08)', padding: '24px 20px', width: '100%', maxWidth: 460, alignSelf: 'flex-start', boxSizing: 'border-box' },
  wide: { maxWidth: 820 },
  logo: { fontWeight: 800, fontSize: 20, color: TEAL, marginBottom: 4 },
  h1: { fontSize: 20, fontWeight: 700, color: '#0a1f2e', margin: '0 0 6px' },
  p: { fontSize: 14, lineHeight: 1.5, color: '#4a6375', margin: '0 0 14px' },
  label: { display: 'block', fontSize: 13, fontWeight: 600, color: '#0a1f2e', margin: '12px 0 4px' },
  input: { width: '100%', boxSizing: 'border-box', minHeight: 44, padding: '0 12px', fontSize: 16, border: '1px solid #c9d6de', borderRadius: 8, fontFamily: 'inherit' },
  btn: { width: '100%', minHeight: 46, marginTop: 16, background: TEAL, color: '#fff', border: 0, borderRadius: 8, fontSize: 15, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit' },
  ghost: { background: 'none', border: 0, color: TEAL, fontWeight: 600, cursor: 'pointer', fontSize: 13, padding: '10px 0', fontFamily: 'inherit' },
  err: { color: '#b3261e', fontSize: 13, margin: '10px 0 0', minHeight: 18 },
  hint: { fontSize: 12.5, color: '#6b7f8d', margin: '8px 0 0', lineHeight: 1.45 },
  tabs: { display: 'flex', gap: 4, borderBottom: '1px solid #dde6ec', margin: '12px 0 4px' },
  tab: (on) => ({ flex: 1, minHeight: 44, background: 'none', border: 0, borderBottom: `2px solid ${on ? TEAL : 'transparent'}`, marginBottom: -1, color: on ? TEAL : '#6b7f8d', fontWeight: on ? 700 : 500, fontSize: 14, cursor: 'pointer', fontFamily: 'inherit' }),
}

function SignIn() {
  const [ident, setIdent] = useState('')
  const [stage, setStage] = useState('idle')
  const [error, setError] = useState('')
  async function submit(e) {
    e.preventDefault()
    const v = ident.trim()
    const digits = v.replace(/\D/g, '')
    if (!(EMAIL_RE.test(v) || (!v.includes('@') && digits.length >= 9 && digits.length <= 15))) {
      return setError('Enter your email or your WhatsApp number.')
    }
    setStage('sending'); setError('')
    try { await requestPartnerLink(v); setStage('sent') }
    catch (err) { setStage('idle'); setError(errorMessage(err, 'We couldn’t send that just now. Please try again.')) }
  }
  if (stage === 'sent') {
    return (
      <div role="status" aria-live="polite">
        <h2 style={{ ...S.h1, fontSize: 17, marginTop: 14 }}>Check your email and WhatsApp.</h2>
        <p style={S.p}>If that’s a registered partner, your sign-in link is on its way. It works once and expires in 60 minutes. Email is the surest place to look.</p>
        <button type="button" style={S.ghost} onClick={() => { setStage('idle'); setIdent('') }}>Use different details</button>
      </div>
    )
  }
  return (
    <form onSubmit={submit} noValidate>
      <label style={S.label} htmlFor="pp-ident">Email or WhatsApp number</label>
      <input id="pp-ident" style={S.input} type="text" inputMode="email" autoComplete="username" placeholder="you@example.com or 0803 123 4567"
        value={ident} onChange={(e) => { setIdent(e.target.value); setError('') }} />
      <p style={S.hint}>We’ll send a one-time link to both your email and your WhatsApp. No password needed.</p>
      <p style={S.err} aria-live="polite">{error}</p>
      <button type="submit" style={S.btn} disabled={stage === 'sending'}>{stage === 'sending' ? 'Sending…' : 'Send my sign-in link'}</button>
    </form>
  )
}

function Apply() {
  const [stage, setStage] = useState('details') // details | sending | code | verifying | done
  const [f, setF] = useState({ full_name: '', email: '', phone: '', agency_name: '', accept_terms: false, website: '' })
  const [code, setCode] = useState('')
  const [rid, setRid] = useState('')
  const [hint, setHint] = useState('')
  const [error, setError] = useState('')
  const set = (k) => (e) => { setF((x) => ({ ...x, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })); setError('') }

  async function submitDetails(e) {
    e.preventDefault()
    const digits = f.phone.replace(/\D/g, '')
    if (f.full_name.trim().length < 2) return setError('Please enter your name.')
    if (!EMAIL_RE.test(f.email.trim())) return setError('Please enter a valid email address.')
    if (digits.length < 9 || digits.length > 15) return setError('Enter your WhatsApp number, for example 0803 123 4567.')
    if (!f.accept_terms) return setError('Please accept the terms to continue.')
    setStage('sending'); setError('')
    try {
      const res = await startApplication({ ...f, full_name: f.full_name.trim(), email: f.email.trim(), phone: f.phone.trim() })
      setRid(res.request_id); setHint(res.email_hint || ''); setStage('code')
    } catch (err) { setStage('details'); setError(errorMessage(err, 'We couldn’t start that just now. Please try again.')) }
  }
  async function submitCode(e) {
    e.preventDefault()
    const d = code.replace(/\D/g, '')
    if (d.length !== 6) return setError('Enter the 6-digit code from your email.')
    setStage('verifying'); setError('')
    try { await verifyApplication(rid, d); setStage('done') }
    catch (err) { setStage('code'); setError(errorMessage(err, 'That didn’t work. Check the code and try again.')) }
  }

  if (stage === 'done') {
    return (
      <div role="status" aria-live="polite">
        <h2 style={{ ...S.h1, fontSize: 17, marginTop: 14 }}>Application received.</h2>
        <p style={S.p}>Thank you. The Opsra team will review it and email you at {hint || 'your email'} once you’re approved. Then you can sign in here.</p>
      </div>
    )
  }
  if (stage === 'code' || stage === 'verifying') {
    return (
      <form onSubmit={submitCode} noValidate>
        <label style={S.label} htmlFor="pp-code">Enter your code</label>
        <input id="pp-code" style={{ ...S.input, letterSpacing: 6, textAlign: 'center', fontSize: 22 }} type="text" inputMode="numeric"
          autoComplete="one-time-code" maxLength={7} placeholder="000000" autoFocus value={code} onChange={(e) => { setCode(e.target.value); setError('') }} />
        <p style={S.hint}>We emailed a 6-digit code to {hint || 'you'}. It works for 15 minutes. If it hasn’t arrived, check spam. If you’re already a partner, we sent a sign-in link instead.</p>
        <p style={S.err} aria-live="polite">{error}</p>
        <button type="submit" style={S.btn} disabled={stage === 'verifying'}>{stage === 'verifying' ? 'Checking…' : 'Submit my application'}</button>
        <button type="button" style={S.ghost} onClick={() => { setStage('details'); setCode(''); setError('') }}>Use different details</button>
      </form>
    )
  }
  return (
    <form onSubmit={submitDetails} noValidate>
      <label style={S.label} htmlFor="pp-name">Your name</label>
      <input id="pp-name" style={S.input} type="text" autoComplete="name" value={f.full_name} onChange={set('full_name')} />
      <label style={S.label} htmlFor="pp-agency">Agency or business name <span style={{ fontWeight: 400, color: '#6b7f8d' }}>(optional)</span></label>
      <input id="pp-agency" style={S.input} type="text" autoComplete="organization" value={f.agency_name} onChange={set('agency_name')} />
      <label style={S.label} htmlFor="pp-email">Email</label>
      <input id="pp-email" style={S.input} type="email" autoComplete="email" inputMode="email" value={f.email} onChange={set('email')} />
      <label style={S.label} htmlFor="pp-phone">WhatsApp number</label>
      <input id="pp-phone" style={S.input} type="tel" autoComplete="tel" inputMode="tel" placeholder="0803 123 4567" value={f.phone} onChange={set('phone')} />
      <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13, color: '#4a6375', marginTop: 14 }}>
        <input type="checkbox" checked={f.accept_terms} onChange={set('accept_terms')} style={{ marginTop: 3 }} />
        <span>I agree to the <a href="/terms" target="_blank" rel="noopener noreferrer">terms</a> and <a href="/privacy" target="_blank" rel="noopener noreferrer">privacy policy</a>.</span>
      </label>
      <div style={{ position: 'absolute', left: -9999, height: 0, overflow: 'hidden' }} aria-hidden="true">
        <label htmlFor="pp-web">Website</label>
        <input id="pp-web" type="text" tabIndex={-1} autoComplete="off" value={f.website} onChange={set('website')} />
      </div>
      <p style={S.hint}>We’ll email a code to confirm it’s you. The Opsra team then reviews your application.</p>
      <p style={S.err} aria-live="polite">{error}</p>
      <button type="submit" style={S.btn} disabled={stage === 'sending'}>{stage === 'sending' ? 'Sending your code…' : 'Email me a code'}</button>
    </form>
  )
}

function Landing() {
  const [tab, setTab] = useState(() => (window.location.hash === '#apply' ? 'apply' : 'signin'))
  return (
    <div style={S.page}>
      <div style={S.card}>
        <div style={S.logo}>opsra</div>
        <h1 style={S.h1}>Launch Partners</h1>
        <p style={S.p}>For CAC registration agents who help new businesses go live online.</p>
        <div style={S.tabs} role="tablist" aria-label="Sign in or apply">
          <button type="button" role="tab" aria-selected={tab === 'signin'} style={S.tab(tab === 'signin')} onClick={() => setTab('signin')}>Sign in</button>
          <button type="button" role="tab" aria-selected={tab === 'apply'} style={S.tab(tab === 'apply')} onClick={() => setTab('apply')}>Apply</button>
        </div>
        {tab === 'signin' ? <SignIn /> : <Apply />}
        <p style={{ ...S.hint, marginTop: 18 }}><a href="/sites" style={{ color: TEAL }}>← Back to Opsra Sites</a></p>
      </div>
    </div>
  )
}

function Portal({ token, name }) {
  const [me, setMe] = useState(null)
  const [rows, setRows] = useState(null)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    getPartnerMe(token).then(setMe).catch((e) => setError(errorMessage(e, 'We couldn’t load your account.')))
    getPartnerReferrals(token).then(setRows).catch((e) => setError(errorMessage(e, 'We couldn’t load your referrals.')))
  }, [token])
  async function copy() {
    try { await navigator.clipboard.writeText(me.link_url); setCopied(true); setTimeout(() => setCopied(false), 2000) } catch (_) { /* select by hand */ }
  }
  return (
    <div style={S.page}>
      <div style={{ ...S.card, ...S.wide }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
          <div style={S.logo}>opsra <span style={{ color: '#6b7f8d', fontWeight: 600, fontSize: 14 }}>Partner</span></div>
          <button type="button" style={S.ghost} onClick={() => { window.location.href = '/partner' }}>Sign out</button>
        </div>
        <h1 style={S.h1}>Hi {(me?.full_name || name || '').split(' ')[0] || 'there'}</h1>
        {error && <p style={S.err} role="alert">{error}</p>}
        {me && (
          <div style={{ background: '#eef7f8', borderRadius: 10, padding: 14, margin: '8px 0 18px' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#0a1f2e' }}>Your client link</div>
            <p style={{ ...S.hint, margin: '2px 0 8px' }}>Send this to your clients. It never expires, and each person who opens it gets their own form.</p>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <input readOnly aria-label="Your client link" style={{ ...S.input, flex: '1 1 240px', fontSize: 14 }} value={me.link_url} onFocus={(e) => e.target.select()} />
              <button type="button" style={{ ...S.btn, width: 'auto', marginTop: 0, padding: '0 18px' }} onClick={copy}>{copied ? 'Copied' : 'Copy link'}</button>
            </div>
          </div>
        )}
        <h2 style={{ ...S.h1, fontSize: 16 }}>Your referrals</h2>
        {rows === null ? <p style={S.p}>Loading…</p> : rows.length === 0 ? (
          <p style={S.p}>No referrals yet. When a client submits their form through your link, they’ll appear here.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14, minWidth: 520 }}>
              <thead><tr>{['Business', 'Phone', 'Website', 'Status'].map((h) => <th key={h} style={{ textAlign: 'left', padding: '8px 10px', fontSize: 12, color: '#6b7f8d', borderBottom: '1px solid #dde6ec' }}>{h}</th>)}</tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} style={{ borderBottom: '1px solid #eef2f5' }}>
                    <td style={{ padding: '10px', fontWeight: 600, color: '#0a1f2e' }}>{r.business_name}</td>
                    <td style={{ padding: '10px' }}>{r.phone || '—'}</td>
                    <td style={{ padding: '10px' }}>
                      {r.website ? <a href={r.website} target="_blank" rel="noopener noreferrer" style={{ color: TEAL }}>{r.website.replace(/^https?:\/\//, '')}</a>
                        : r.preview_path ? <a href={previewUrl(r.preview_path)} target="_blank" rel="noopener noreferrer" style={{ color: TEAL }}>View preview</a> : '—'}
                    </td>
                    <td style={{ padding: '10px' }}><span style={{ background: '#e6f2f4', color: '#0b5560', fontSize: 12, fontWeight: 600, padding: '3px 9px', borderRadius: 20, whiteSpace: 'nowrap' }}>{r.status_label}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

export default function PartnerPage() {
  const isLogin = window.location.pathname === '/partner/login'
  const t = new URLSearchParams(window.location.search).get('t')
  const [session, setSession] = useState(null)
  const [failed, setFailed] = useState('')
  useEffect(() => {
    if (!isLogin) return
    if (!t) { setFailed('This link is missing its access code. Please request a new one.'); return }
    exchangeBuilderToken(t)
      .then((d) => { setSession({ token: d.access_token, name: d.builder?.full_name }); window.history.replaceState(null, '', '/partner/login') })
      .catch((e) => setFailed(errorMessage(e, 'This link isn’t valid — please request a new one.')))
  }, [isLogin, t])
  if (!isLogin) return <Landing />
  if (session) return <Portal token={session.token} name={session.name} />
  return (
    <div style={S.page}>
      <div style={S.card}>
        <div style={S.logo}>opsra</div>
        {failed ? (
          <>
            <h1 style={S.h1}>We couldn’t sign you in</h1>
            <p style={S.p}>{failed}</p>
            <a href="/partner" style={{ color: TEAL, fontWeight: 600 }}>Get a new sign-in link</a>
          </>
        ) : <p style={S.p} role="status">Signing you in…</p>}
      </div>
    </div>
  )
}
