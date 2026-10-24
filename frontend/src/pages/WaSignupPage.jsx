/**
 * frontend/src/pages/WaSignupPage.jsx - WA-AUTO-5. Public page /start/whatsapp.
 * Step 1 details -> emailed 6-digit code. Step 2 code + a password -> the account exists; the owner signs in on the normal page.
 */
import { useEffect, useId, useState } from 'react'
import { getSignupInfo, startWaSignup, verifyWaSignup, signupError } from '../services/waSignup.service'

const C = { teal: '#0F8F8A', dark: '#0A1A24', gray: '#5B6B75', border: '#D5DEE3', red: '#B3261E', light: '#F4F8F9' }
const wrap = { minHeight: '100vh', background: C.light, display: 'flex', justifyContent: 'center', padding: '32px 16px', fontFamily: 'DM Sans, system-ui, sans-serif' }
const card = { background: '#fff', border: `1px solid ${C.border}`, borderRadius: 16, padding: 24, width: '100%', maxWidth: 440, alignSelf: 'flex-start', boxSizing: 'border-box' }
const label = { display: 'block', fontSize: 13, fontWeight: 600, color: C.dark, margin: '14px 0 5px' }
const input = { width: '100%', boxSizing: 'border-box', border: `1.5px solid ${C.border}`, borderRadius: 9, padding: '11px 12px', fontSize: 15, color: C.dark, background: C.light }
const primary = (off) => ({ width: '100%', marginTop: 18, background: off ? C.gray : C.teal, color: '#fff', border: 'none', borderRadius: 10, padding: '13px 16px', fontSize: 15, fontWeight: 700, cursor: off ? 'default' : 'pointer', minHeight: 46 })
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s.]{2,}$/
const naira = (n) => `₦${Number(n || 0).toLocaleString('en-NG')}`

export default function WaSignupPage() {
  const uid = useId()
  const [info, setInfo] = useState(null)
  const [stage, setStage] = useState('details')       // details | sending | code | verifying | done
  const [form, setForm] = useState({ business_name: '', full_name: '', email: '', phone: '', accept_terms: false, website: '' })
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [requestId, setRequestId] = useState('')
  const [hint, setHint] = useState('')
  const [error, setError] = useState('')
  const [trial, setTrial] = useState(0)

  useEffect(() => { getSignupInfo().then(setInfo).catch(() => setInfo({ open: false })) }, [])
  const set = (k) => (e) => { setForm((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })); setError('') }

  async function submitDetails(e) {
    e.preventDefault()
    const digits = form.phone.replace(/\D/g, '')
    if (form.business_name.trim().length < 2) return setError('Please enter your business name.')
    if (form.full_name.trim().length < 2) return setError('Please enter your name.')
    if (!EMAIL_RE.test(form.email.trim())) return setError('Please enter a valid email address.')
    if (digits.length < 9 || digits.length > 15) return setError('Enter your WhatsApp number, for example 0803 123 4567.')
    if (!form.accept_terms) return setError('Please accept the terms to continue.')
    setStage('sending'); setError('')
    try {
      const res = await startWaSignup({ ...form, business_name: form.business_name.trim(), full_name: form.full_name.trim(), email: form.email.trim(), phone: form.phone.trim() })
      setRequestId(res.request_id); setHint(res.email_hint || ''); setStage('code')
    } catch (err) {
      setStage('details'); setError(signupError(err, 'We could not start that just now. Please try again in a moment.'))
    }
  }

  async function submitCode(e) {
    e.preventDefault()
    const digits = code.replace(/\D/g, '')
    if (digits.length !== 6) return setError('Enter the 6-digit code from your email.')
    if (password.length < 8) return setError('Choose a password of at least 8 characters.')
    setStage('verifying'); setError('')
    try {
      const res = await verifyWaSignup(requestId, digits, password)
      setTrial(res.trial_days || 0); setStage('done')
    } catch (err) {
      setStage('code'); setError(signupError(err, 'That did not work. Check the code and try again.'))
    }
  }

  const plan = info?.plan
  return (
    <main style={wrap}>
      <div style={card}>
        <h1 style={{ fontSize: 24, margin: '0 0 6px', color: C.dark }}>Let your WhatsApp reply to customers for you</h1>
        {info && info.open && plan && (
          <p style={{ color: C.gray, fontSize: 14, margin: '0 0 4px' }}>
            Opsra {plan.label}{plan.monthly_ngn > 0 ? `: ${naira(plan.monthly_ngn)} a month` : ''}{plan.ai_messages ? `, ${plan.ai_messages} AI replies included` : ''}.
            {info.trial_days ? ` Try it free for ${info.trial_days} days.` : ''} Extra AI replies are paid for with credits. WhatsApp's own charges are billed to you by Meta.
          </p>
        )}

        {info === null && <p style={{ color: C.gray, fontSize: 14 }}>Loading…</p>}
        {info && !info.open && stage !== 'done' && (
          <p role="status" style={{ background: C.light, borderRadius: 10, padding: 14, color: C.dark, fontSize: 14 }}>
            Sign-ups are not open yet. Please check back soon.
          </p>
        )}

        {info?.open && (stage === 'details' || stage === 'sending') && (
          <form onSubmit={submitDetails} noValidate>
            <label style={label} htmlFor={`${uid}-b`}>Business name</label>
            <input id={`${uid}-b`} style={input} value={form.business_name} maxLength={80} onChange={set('business_name')} autoComplete="organization" />
            <label style={label} htmlFor={`${uid}-n`}>Your name</label>
            <input id={`${uid}-n`} style={input} value={form.full_name} maxLength={80} onChange={set('full_name')} autoComplete="name" />
            <label style={label} htmlFor={`${uid}-e`}>Email</label>
            <input id={`${uid}-e`} style={input} type="email" value={form.email} maxLength={255} onChange={set('email')} autoComplete="email" />
            <label style={label} htmlFor={`${uid}-p`}>Your WhatsApp number</label>
            <input id={`${uid}-p`} style={input} type="tel" inputMode="tel" value={form.phone} maxLength={20} onChange={set('phone')} autoComplete="tel" placeholder="0803 123 4567" />
            <input type="text" tabIndex={-1} autoComplete="off" aria-hidden="true" value={form.website} onChange={set('website')} style={{ position: 'absolute', left: '-9999px', height: 0, width: 0, opacity: 0 }} />
            <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13.5, color: C.dark, marginTop: 16 }}>
              <input type="checkbox" checked={form.accept_terms} onChange={set('accept_terms')} style={{ marginTop: 3 }} />
              <span>I agree to the <a href="/terms" target="_blank" rel="noreferrer">Terms</a> and the <a href="/privacy" target="_blank" rel="noreferrer">Privacy Policy</a>.</span>
            </label>
            <div aria-live="polite">{error && <p role="alert" style={{ color: C.red, fontSize: 13.5, margin: '10px 0 0' }}>{error}</p>}</div>
            <button type="submit" style={primary(stage === 'sending')} disabled={stage === 'sending'}>{stage === 'sending' ? 'Sending your code…' : 'Email me a code'}</button>
          </form>
        )}

        {info?.open && (stage === 'code' || stage === 'verifying') && (
          <form onSubmit={submitCode} noValidate>
            <label style={label} htmlFor={`${uid}-c`}>Enter your code</label>
            <input id={`${uid}-c`} style={{ ...input, letterSpacing: 4, fontSize: 20 }} value={code} inputMode="numeric" autoComplete="one-time-code" maxLength={7} placeholder="000000" autoFocus onChange={(e) => { setCode(e.target.value); setError('') }} />
            <p style={{ fontSize: 12.5, color: C.gray, margin: '6px 0 0' }}>We emailed a 6-digit code to {hint || 'you'}. It works for 15 minutes. If it has not arrived, check spam.</p>
            <label style={label} htmlFor={`${uid}-w`}>Choose a password</label>
            <input id={`${uid}-w`} style={input} type="password" value={password} maxLength={72} autoComplete="new-password" onChange={(e) => { setPassword(e.target.value); setError('') }} />
            <p style={{ fontSize: 12.5, color: C.gray, margin: '6px 0 0' }}>At least 8 characters. You will use it with your email to sign in.</p>
            <div aria-live="polite">{error && <p role="alert" style={{ color: C.red, fontSize: 13.5, margin: '10px 0 0' }}>{error}</p>}</div>
            <button type="submit" style={primary(stage === 'verifying')} disabled={stage === 'verifying'}>{stage === 'verifying' ? 'Creating your account…' : 'Create my account'}</button>
            <button type="button" onClick={() => { setStage('details'); setCode(''); setPassword(''); setError('') }}
              style={{ background: 'none', border: 'none', color: C.gray, textDecoration: 'underline', cursor: 'pointer', marginTop: 12, fontSize: 13.5 }}>Use different details</button>
          </form>
        )}

        {stage === 'done' && (
          <div role="status">
            <h2 style={{ fontSize: 18, color: C.dark, margin: '8px 0' }}>Your account is ready</h2>
            <p style={{ color: C.gray, fontSize: 14, margin: '0 0 6px' }}>
              {trial ? `Your ${trial}-day free trial has started. ` : ''}Sign in with your email and password. A short guide will help you tell the bot about your business and connect your WhatsApp number; our team helps with the connection.
            </p>
            <a href="/" style={{ ...primary(false), display: 'block', textAlign: 'center', textDecoration: 'none', boxSizing: 'border-box', lineHeight: '20px' }}>Sign in</a>
          </div>
        )}
      </div>
    </main>
  )
}
