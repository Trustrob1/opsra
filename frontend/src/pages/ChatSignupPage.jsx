/**
 * frontend/src/pages/ChatSignupPage.jsx - WEB-ONLY-1b. Public page /start/chat.
 * Step 1 details -> emailed 6-digit code. Step 2 code + a password -> the account exists; the owner signs in on the normal page.
 * Same flow as WaSignupPage; the words, the free credit and the plan line are about Chioma on the website.
 */
import { useEffect, useId, useState } from 'react'
import { getChatSignupInfo, startChatSignup, verifyChatSignup, signupError } from '../services/chatSignup.service'
import { validateDetails, validateCode, creditLine, planLine } from './chatSignupLogic'

const SALES_WA = '2348056055896'
const C = { blue: '#2F5BEA', dark: '#0B1B3A', gray: '#5B6B75', border: '#D5DEE3', red: '#B3261E', light: '#F4F7FC' }
const wrap = { minHeight: '100vh', background: C.light, display: 'flex', justifyContent: 'center', padding: '32px 16px', fontFamily: 'Hanken Grotesk, DM Sans, system-ui, sans-serif' }
const card = { background: '#fff', border: `1px solid ${C.border}`, borderRadius: 16, padding: 24, width: '100%', maxWidth: 440, alignSelf: 'flex-start', boxSizing: 'border-box' }
const label = { display: 'block', fontSize: 13, fontWeight: 600, color: C.dark, margin: '14px 0 5px' }
const input = { width: '100%', boxSizing: 'border-box', border: `1.5px solid ${C.border}`, borderRadius: 9, padding: '11px 12px', fontSize: 15, color: C.dark, background: C.light }
const primary = (off) => ({ width: '100%', marginTop: 18, background: off ? C.gray : C.blue, color: '#fff', border: 'none', borderRadius: 12, padding: '13px 16px', fontSize: 15, fontWeight: 700, cursor: off ? 'default' : 'pointer', minHeight: 46 })

export default function ChatSignupPage() {
  const uid = useId()
  const [info, setInfo] = useState(null)
  const [stage, setStage] = useState('details')       // details | sending | code | verifying | done
  const [form, setForm] = useState({ business_name: '', full_name: '', email: '', phone: '', accept_terms: false, website: '' })
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [requestId, setRequestId] = useState('')
  const [hint, setHint] = useState('')
  const [error, setError] = useState('')

  useEffect(() => { getChatSignupInfo().then(setInfo).catch(() => setInfo({ open: false })) }, [])
  const set = (k) => (e) => { setForm((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })); setError('') }

  async function submitDetails(e) {
    e.preventDefault()
    const problem = validateDetails(form)
    if (problem) return setError(problem)
    setStage('sending'); setError('')
    try {
      const res = await startChatSignup({ ...form, business_name: form.business_name.trim(), full_name: form.full_name.trim(), email: form.email.trim(), phone: form.phone.trim() })
      setRequestId(res.request_id); setHint(res.email_hint || ''); setStage('code')
    } catch (err) {
      setStage('details'); setError(signupError(err, 'We could not start that just now. Please try again in a moment.'))
    }
  }

  async function submitCode(e) {
    e.preventDefault()
    const problem = validateCode(code, password)
    if (problem) return setError(problem)
    setStage('verifying'); setError('')
    try {
      await verifyChatSignup(requestId, code.replace(/\D/g, ''), password)
      setStage('done')
    } catch (err) {
      setStage('code'); setError(signupError(err, 'That did not work. Check the code and try again.'))
    }
  }

  const waLink = `https://wa.me/${SALES_WA}?text=${encodeURIComponent("Hi, I'd like to start free with Chioma on my website.")}`
  return (
    <main style={wrap}>
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          <img src="/images/chioma.jpg" alt="" width={52} height={52} style={{ borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }} />
          <h1 style={{ fontSize: 22, lineHeight: 1.2, margin: 0, color: C.dark }}>Put Chioma on your website</h1>
        </div>
        {info && info.open && (
          <p style={{ color: C.gray, fontSize: 14, margin: '0 0 4px' }}>
            {creditLine(info)} {planLine(info.plan)}
          </p>
        )}

        {info === null && <p style={{ color: C.gray, fontSize: 14 }}>Loading…</p>}
        {info && !info.open && stage !== 'done' && (
          <div role="status" style={{ background: C.light, borderRadius: 10, padding: 14, color: C.dark, fontSize: 14 }}>
            <p style={{ margin: '0 0 8px' }}>Sign-ups are not open yet. Please check back soon.</p>
            <a href={waLink} target="_blank" rel="noopener noreferrer" style={{ color: C.blue, fontWeight: 600 }}>Message us on WhatsApp and we will tell you when it opens</a>
          </div>
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
            <input id={`${uid}-p`} style={input} type="tel" inputMode="tel" value={form.phone} maxLength={20} onChange={set('phone')} autoComplete="tel" placeholder="0803 123 4567" aria-describedby={`${uid}-ph`} />
            <p id={`${uid}-ph`} style={{ fontSize: 12.5, color: C.gray, margin: '6px 0 0' }}>So we can reach you if you need help. Chioma works on your website, not on this number.</p>
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
              Sign in with your email and password. Then open Admin, then Web Chat, to tell Chioma about your business and put her on your website.
            </p>
            <a href="/" style={{ ...primary(false), display: 'block', textAlign: 'center', textDecoration: 'none', boxSizing: 'border-box', lineHeight: '20px' }}>Sign in</a>
          </div>
        )}
      </div>
    </main>
  )
}
