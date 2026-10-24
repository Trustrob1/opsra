/**
 * WaSetupWizard.jsx - WA-AUTO-3. First-login set-up for a WhatsApp-automation-only business.
 * Steps: 1 About your business, 2 Connect WhatsApp, 3 Test it, 4 Go live.
 * Teaching the bot from documents, websites and stores arrives with the knowledge phase; until then the answers from step 1
 * are what the bot knows (they are saved where the bot already reads).
 */
import { useEffect, useState } from 'react'
import { ds } from '../../utils/ds'
import { connectWhatsApp } from '../../services/admin.service'
import { getPlan, ngn } from '../../services/accountPlan.service'
import { getCreditSummary } from '../../services/credits.service'
import {
  getWaOnboarding, saveWaBasics, requestWaSetup, getWaTestStatus, completeWaOnboarding, waError,
} from '../../services/waOnboarding.service'

const STEPS = ['About your business', 'Connect WhatsApp', 'Test it', 'Go live']
const CHECKLIST = [
  'The number is not signed in on the normal WhatsApp or WhatsApp Business app on a phone. Meta only lets a number live in one place.',
  'You can receive a call or text on that number (Meta sends a code).',
  'Your business name is ready: it is what customers see.',
  'You have a Meta business account and a payment card added to it. Meta bills you directly for conversations.',
]

const box = { background: ds.white, border: `1px solid ${ds.border}`, borderRadius: 14, padding: 22, maxWidth: 640, margin: '0 auto' }
const label = { display: 'block', fontSize: 13, fontWeight: 600, color: ds.dark, margin: '14px 0 5px' }
const input = { width: '100%', boxSizing: 'border-box', border: `1.5px solid ${ds.border}`, borderRadius: 9, padding: '10px 12px', fontSize: 14, fontFamily: ds.fontDm, color: ds.dark, background: ds.light }
const primary = (off) => ({ background: off ? ds.gray : ds.teal, color: '#fff', border: 'none', borderRadius: 9, padding: '11px 18px', fontSize: 14, fontWeight: 600, cursor: off ? 'default' : 'pointer', minHeight: 44 })
const ghost = { background: 'none', border: `1px solid ${ds.border}`, borderRadius: 9, padding: '10px 16px', fontSize: 14, color: ds.dark, cursor: 'pointer', minHeight: 44 }

export default function WaSetupWizard({ onDone, onSkip, onOpenBilling }) {
  const [st, setSt] = useState(null)
  const [step, setStep] = useState(0)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [basics, setBasics] = useState({ what_you_sell: '', hours: '', language: 'English' })
  const [conn, setConn] = useState({ whatsapp_phone_id: '', whatsapp_waba_id: '', whatsapp_access_token: '' })
  const [help, setHelp] = useState({ phone: '', note: '' })
  const [helpSent, setHelpSent] = useState(false)
  const [test, setTest] = useState(null)

  useEffect(() => {
    let live = true
    getWaOnboarding().then((s) => {
      if (!live) return
      setSt(s)
      if (s.basics?.what_you_sell) setBasics({ what_you_sell: s.basics.what_you_sell, hours: s.basics.hours || '', language: s.basics.language || 'English' })
      setHelpSent(!!s.setup_requested)
      setStep(!s.basics?.what_you_sell ? 0 : !s.connected ? 1 : 2)
    }).catch((e) => { if (live) setErr(waError(e)) })
    return () => { live = false }
  }, [])

  // Step 3 checks for a message and a reply every few seconds.
  useEffect(() => {
    if (step !== 2) return undefined
    let live = true
    const tick = () => getWaTestStatus().then((t) => { if (live) setTest(t) }).catch(() => {})
    tick()
    const id = setInterval(tick, 5000)
    return () => { live = false; clearInterval(id) }
  }, [step])

  const run = async (fn) => {
    setBusy(true); setErr(null)
    try { await fn() } catch (e) { setErr(waError(e)) } finally { setBusy(false) }
  }

  const saveAbout = () => run(async () => { await saveWaBasics(basics); setStep(1) })
  const connect = () => run(async () => {
    await connectWhatsApp(conn)
    setConn({ whatsapp_phone_id: '', whatsapp_waba_id: '', whatsapp_access_token: '' })
    setSt(await getWaOnboarding())
    setStep(2)
  })
  const askHelp = () => run(async () => { await requestWaSetup(help); setHelpSent(true) })
  // Go live (WA-AUTO-5): show the plan (free trial or paid) and the credit balance, with a way to pay for either.
  const [money, setMoney] = useState(null)
  useEffect(() => {
    if (step !== 3) return undefined
    let live = true
    Promise.all([getPlan().catch(() => null), getCreditSummary().catch(() => null)]).then(([plan, credits]) => { if (live) setMoney({ plan, credits }) })
    return () => { live = false }
  }, [step])
  const finish = () => run(async () => { await completeWaOnboarding(); onDone && onDone() })

  if (!st && !err) return <div style={{ padding: 28, color: ds.gray }}>Loading…</div>

  return (
    <div style={{ padding: '24px 16px' }}>
      <div style={box}>
        <ol style={{ display: 'flex', gap: 6, listStyle: 'none', padding: 0, margin: '0 0 6px', flexWrap: 'wrap' }} aria-label="Set-up steps">
          {STEPS.map((s, i) => (
            <li key={s} aria-current={i === step ? 'step' : undefined}
              style={{ fontSize: 12.5, fontWeight: i === step ? 700 : 500, color: i === step ? ds.teal : i < step ? ds.dark : ds.gray }}>
              {i + 1}. {s}{i < STEPS.length - 1 ? ' ›' : ''}
            </li>
          ))}
        </ol>
        {err && <div role="alert" style={{ background: '#FDECEC', color: ds.red, borderRadius: 8, padding: '9px 12px', fontSize: 13, margin: '10px 0' }}>{err}</div>}

        {step === 0 && (
          <div>
            <h2 style={{ fontFamily: ds.fontSyne, fontSize: 20, margin: '8px 0 2px', color: ds.dark }}>Tell us about {st?.business_name || 'your business'}</h2>
            <p style={{ color: ds.gray, fontSize: 13.5, margin: 0 }}>Your bot will use this to answer customers from the first message.</p>
            <label style={label} htmlFor="wa-sell">What do you sell, and what do customers usually ask?</label>
            <textarea id="wa-sell" rows={5} style={input} value={basics.what_you_sell} maxLength={1500}
              onChange={(e) => setBasics({ ...basics, what_you_sell: e.target.value })} />
            <label style={label} htmlFor="wa-hours">Opening hours</label>
            <input id="wa-hours" style={input} value={basics.hours} maxLength={300} placeholder="Mon-Sat, 9am to 6pm"
              onChange={(e) => setBasics({ ...basics, hours: e.target.value })} />
            <label style={label} htmlFor="wa-lang">Reply to customers in</label>
            <select id="wa-lang" style={input} value={basics.language} onChange={(e) => setBasics({ ...basics, language: e.target.value })}>
              {(st?.languages || ['English']).map((l) => <option key={l}>{l}</option>)}
            </select>
            <div style={{ marginTop: 18 }}>
              <button type="button" style={primary(busy || !basics.what_you_sell.trim() || !basics.hours.trim())}
                disabled={busy || !basics.what_you_sell.trim() || !basics.hours.trim()} onClick={saveAbout}>Save and continue</button>
            </div>
          </div>
        )}

        {step === 1 && (
          <div>
            <h2 style={{ fontFamily: ds.fontSyne, fontSize: 20, margin: '8px 0 2px', color: ds.dark }}>Connect your WhatsApp number</h2>
            {st?.connected ? (
              <p style={{ color: ds.green, fontSize: 14 }}>Your number is connected.</p>
            ) : (
              <>
                <p style={{ color: ds.gray, fontSize: 13.5, margin: '0 0 8px' }}>Check these first:</p>
                <ul style={{ paddingLeft: 18, margin: 0, fontSize: 13.5, color: ds.dark, lineHeight: 1.6 }}>
                  {CHECKLIST.map((c) => <li key={c}>{c}</li>)}
                </ul>
                <h3 style={{ fontSize: 15, margin: '20px 0 0', color: ds.dark }}>Do it yourself</h3>
                <p style={{ color: ds.gray, fontSize: 13, margin: '4px 0 0' }}>
                  In Meta, open your WhatsApp account and copy the Phone number ID, the WhatsApp Business Account ID and a permanent access token. We check them with Meta when you save, and the token is never shown again.
                </p>
                <label style={label} htmlFor="wa-pid">Phone number ID</label>
                <input id="wa-pid" style={input} value={conn.whatsapp_phone_id} onChange={(e) => setConn({ ...conn, whatsapp_phone_id: e.target.value.trim() })} />
                <label style={label} htmlFor="wa-waba">WhatsApp Business Account ID</label>
                <input id="wa-waba" style={input} value={conn.whatsapp_waba_id} onChange={(e) => setConn({ ...conn, whatsapp_waba_id: e.target.value.trim() })} />
                <label style={label} htmlFor="wa-tok">Permanent access token</label>
                <input id="wa-tok" type="password" autoComplete="off" style={input} value={conn.whatsapp_access_token}
                  onChange={(e) => setConn({ ...conn, whatsapp_access_token: e.target.value.trim() })} />
                <div style={{ marginTop: 14 }}>
                  <button type="button" style={primary(busy || !conn.whatsapp_phone_id || !conn.whatsapp_waba_id || !conn.whatsapp_access_token)}
                    disabled={busy || !conn.whatsapp_phone_id || !conn.whatsapp_waba_id || !conn.whatsapp_access_token} onClick={connect}>
                    {busy ? 'Checking with Meta…' : 'Connect'}
                  </button>
                </div>
                <h3 style={{ fontSize: 15, margin: '24px 0 0', color: ds.dark }}>Or let us do it for you</h3>
                {helpSent ? (
                  <p style={{ color: ds.green, fontSize: 13.5 }}>Thanks. We have your request and will contact you to finish the connection.</p>
                ) : (
                  <>
                    <p style={{ color: ds.gray, fontSize: 13, margin: '4px 0 0' }}>Tell us the number and we will connect it with you.</p>
                    <label style={label} htmlFor="wa-hnum">WhatsApp number (with country code)</label>
                    <input id="wa-hnum" style={input} inputMode="tel" value={help.phone} placeholder="2348012345678" onChange={(e) => setHelp({ ...help, phone: e.target.value })} />
                    <label style={label} htmlFor="wa-hnote">Anything we should know? (optional)</label>
                    <input id="wa-hnote" style={input} value={help.note} maxLength={500} onChange={(e) => setHelp({ ...help, note: e.target.value })} />
                    <div style={{ marginTop: 14 }}>
                      <button type="button" style={ghost} disabled={busy || !help.phone.trim()} onClick={askHelp}>Ask us to connect it</button>
                    </div>
                  </>
                )}
              </>
            )}
            <div style={{ marginTop: 20, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <button type="button" style={ghost} onClick={() => setStep(0)}>Back</button>
              {st?.connected && <button type="button" style={primary(false)} onClick={() => setStep(2)}>Continue</button>}
            </div>
          </div>
        )}

        {step === 2 && (
          <div>
            <h2 style={{ fontFamily: ds.fontSyne, fontSize: 20, margin: '8px 0 2px', color: ds.dark }}>Test it</h2>
            <p style={{ color: ds.gray, fontSize: 13.5, margin: 0 }}>From your own phone, send a message to your business number, such as "Hello, what do you sell?". This page notices it.</p>
            <ul style={{ listStyle: 'none', padding: 0, margin: '14px 0', fontSize: 14, color: ds.dark, lineHeight: 1.9 }} aria-live="polite">
              <li>{test?.inbound_at ? '✓ We received your message' : '… Waiting for your message'}</li>
              <li>{test?.reply_at ? '✓ A reply was sent' : '… Waiting for the reply'}</li>
            </ul>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <button type="button" style={ghost} onClick={() => setStep(1)}>Back</button>
              <button type="button" style={primary(false)} onClick={() => setStep(3)}>{test?.ok ? 'Continue' : 'Skip the test'}</button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div>
            <h2 style={{ fontFamily: ds.fontSyne, fontSize: 20, margin: '8px 0 2px', color: ds.dark }}>Go live</h2>
            <p style={{ color: ds.gray, fontSize: 13.5, margin: 0 }}>
              Your bot answers customers on your number. Replies from the AI use your credit balance, so add credits before you start. You can change everything later in Admin.
            </p>
            {money && (() => {
              const cur = money.plan?.current
              const trial = cur && cur.source === 'trial'
              const live = cur && ['active', 'grace'].includes(cur.status)
              const bal = money.credits ? ngn((money.credits.balance_kobo || 0) / 100) : null
              return (
                <div style={{ marginTop: 14, background: ds.light, borderRadius: 10, padding: '12px 14px', fontSize: 14, color: ds.dark, lineHeight: 1.7 }} aria-live="polite">
                  <div>
                    Plan: <strong>{cur ? cur.label : 'none yet'}</strong>
                    {live ? (trial ? ` (free trial, ${cur.days_left} day${cur.days_left === 1 ? '' : 's'} left)` : ` (paid, ${cur.days_left} days left)`) : cur ? ' (not active)' : ''}
                  </div>
                  {bal !== null && <div>Credit balance: <strong>{bal}</strong></div>}
                  {trial && <div style={{ fontSize: 13, color: ds.gray }}>Pay for the plan before the trial ends so the bot keeps answering.</div>}
                </div>
              )
            })()}
            {onOpenBilling && (
              <div style={{ marginTop: 12 }}>
                <button type="button" style={ghost} onClick={onOpenBilling}>Choose a plan or buy credits</button>
              </div>
            )}
            <div style={{ marginTop: 18, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <button type="button" style={ghost} onClick={() => setStep(2)}>Back</button>
              <button type="button" style={primary(busy)} disabled={busy} onClick={finish}>Finish set-up</button>
            </div>
          </div>
        )}

        {onSkip && step !== 3 && (
          <p style={{ margin: '18px 0 0', fontSize: 12.5 }}>
            <button type="button" onClick={onSkip} style={{ background: 'none', border: 'none', padding: 0, color: ds.gray, textDecoration: 'underline', cursor: 'pointer', fontSize: 12.5 }}>Set up later</button>
          </p>
        )}
      </div>
    </div>
  )
}
