/**
 * frontend/src/catalog/storefront/CartDrawer.jsx
 * STORE-4: the Storefront cart drawer and the details step. Opens from the header cart button, or right after
 * "Add to cart". Checkout sends the visitor to Paystack; if no payment link can be made, a person finishes the order.
 */
import { useEffect, useRef, useState } from 'react'
import { Icon, WhatsAppIcon } from './StorefrontChrome'
import { readableOn } from './storefrontLogic'
import { INK, MUTED, LINE, placeholder } from './storefrontTheme'
import { validateContact, moneyText, safePayUrl, MAX_QTY } from './storefrontCart'

const FIELD = { marginTop: 6, width: '100%', height: 52, boxSizing: 'border-box', border: '1px solid #C9C6BF', borderRadius: 12, padding: '0 14px', fontSize: 15, color: INK, background: '#fff' }
const LABEL = { display: 'block', fontSize: 13, fontWeight: 700 }
const ghost = { height: 44, border: 0, background: 'transparent', cursor: 'pointer', fontSize: 14, fontWeight: 600, color: '#3A3F44', padding: '0 12px' }

function focusables(root) {
  return [...root.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])')]
}

export default function CartDrawer({
  open, onClose, accent, orgName, waNumber, template, lines, total, count, busy, error, hasContact,
  onSetQty, onRemove, onSubmitContact, onCheckout, onClearError, onOpenItem,
}) {
  const onAccent = readableOn(accent)
  const [step, setStep] = useState('cart')            // cart | details | done
  const [form, setForm] = useState({ name: '', phone: '', email: '', consent: false })
  const [formError, setFormError] = useState('')
  const [result, setResult] = useState(null)          // {url} | {human:true}
  const panel = useRef(null)
  const returnTo = useRef(null)

  // Every time the drawer opens it starts on the cart (or the answer, if we already have one).
  useEffect(() => {
    if (!open) return undefined
    returnTo.current = document.activeElement
    const t = setTimeout(() => { if (panel.current) panel.current.focus() }, 0)
    let prev = ''
    try { prev = document.body.style.overflow; document.body.style.overflow = 'hidden' } catch { /* not important */ }
    return () => {
      clearTimeout(t)
      try { document.body.style.overflow = prev } catch { /* not important */ }
      if (returnTo.current && returnTo.current.focus) returnTo.current.focus()
    }
  }, [open])

  if (!open) return null

  const close = () => { if (!busy) { setStep('cart'); setResult(null); setFormError(''); onClearError(); onClose() } }

  function onKeyDown(e) {
    if (e.key === 'Escape') { e.stopPropagation(); close(); return }
    if (e.key !== 'Tab' || !panel.current) return
    const f = focusables(panel.current)
    if (!f.length) return
    const first = f[0], last = f[f.length - 1]
    if (e.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { e.preventDefault(); last.focus() }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
  }

  async function pay() {
    const r = await onCheckout()
    if (r.ok && r.url) {
      const url = safePayUrl(r.url)
      setResult({ url: url || null })
      setStep('done')
      if (url) window.location.assign(url)
    } else if (r.ok) {
      setResult({ human: true })
      setStep('done')
    } else if (r.askContact) {
      setStep('details')
    }
  }

  async function startCheckout() {
    onClearError()
    if (hasContact) await pay(); else setStep('details')
  }

  async function submitDetails(e) {
    e.preventDefault()
    const v = validateContact(form)
    if (v.error) { setFormError(v.error); return }
    setFormError('')
    const ok = await onSubmitContact(v.payload)
    if (ok) await pay()
  }

  const empty = lines.length === 0
  const shownError = formError || error
  const waHref = waNumber ? `https://wa.me/${String(waNumber).replace(/\D/g, '')}` : null

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1000 }} onKeyDown={onKeyDown}>
      <div onClick={close} style={{ position: 'absolute', inset: 0, background: 'rgba(20,24,27,0.45)' }} />
      <div ref={panel} role="dialog" aria-modal="true" aria-label="Your cart" tabIndex={-1}
        style={{ position: 'absolute', top: 0, right: 0, bottom: 0, width: 'min(440px, 100%)', background: '#fff', display: 'flex', flexDirection: 'column', outline: 'none', boxShadow: '-8px 0 32px rgba(0,0,0,0.12)' }}>

        {step === 'cart' && (
          <>
            <div style={{ height: 68, padding: '0 12px 0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: `1px solid ${LINE}`, flexShrink: 0 }}>
              <div style={{ fontSize: 20, fontWeight: 800 }}>Your cart <span style={{ fontSize: 14, fontWeight: 600, color: MUTED }}>({count})</span></div>
              <button onClick={close} aria-label="Close cart" style={{ width: 44, height: 44, border: 0, background: 'transparent', cursor: 'pointer' }}>
                <Icon size={20} width={1.9}><path d="M6 6l12 12M18 6L6 18" /></Icon>
              </button>
            </div>

            <div style={{ flexGrow: 1, overflowY: 'auto', padding: '8px 24px 0' }}>
              {empty ? (
                <div style={{ padding: '48px 0', textAlign: 'center' }}>
                  <p style={{ margin: 0, fontSize: 17, fontWeight: 700 }}>Your cart is empty</p>
                  <p style={{ margin: '8px 0 20px', fontSize: 14, color: MUTED }}>Add something you like and it will wait for you here.</p>
                  <button onClick={close} style={{ height: 48, padding: '0 24px', borderRadius: 14, border: `1px solid #C9C6BF`, background: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer' }}>Keep shopping</button>
                </div>
              ) : (
                <>
                  {lines.map((l, i) => (
                    <div key={l.key} style={{ display: 'flex', gap: 16, padding: '20px 0', borderBottom: `1px solid ${LINE}` }}>
                      <div style={{ width: 84, height: 92, borderRadius: 12, flexShrink: 0, background: l.image ? `#F4F2EE url(${l.image}) center/cover` : placeholder(i, 16) }} />
                      <div style={{ flexGrow: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                          <div style={{ fontSize: 15, fontWeight: 700, minWidth: 0 }}>
                            {onOpenItem && l.slug ? (
                              <button onClick={() => onOpenItem(l)} style={{ border: 0, background: 'transparent', padding: 0, font: 'inherit', fontWeight: 700, textAlign: 'left', cursor: 'pointer', color: INK }}>{l.name}</button>
                            ) : l.name}
                          </div>
                          <div style={{ fontSize: 15, fontWeight: 800 }}>{moneyText(l.lineTotal, template)}</div>
                        </div>
                        <div style={{ marginTop: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <div style={{ display: 'flex', alignItems: 'center', border: '1px solid #C9C6BF', borderRadius: 12, height: 44 }}>
                            <button aria-label={`Fewer ${l.name}`} disabled={busy} onClick={() => onSetQty(l, l.qty - 1)} style={{ width: 40, height: 42, border: 0, background: 'transparent', fontSize: 18, cursor: 'pointer' }}>-</button>
                            <span aria-live="polite" style={{ minWidth: 24, textAlign: 'center', fontWeight: 700, fontSize: 14 }}>{l.qty}</span>
                            <button aria-label={`More ${l.name}`} disabled={busy || l.qty >= MAX_QTY} onClick={() => onSetQty(l, l.qty + 1)} style={{ width: 40, height: 42, border: 0, background: 'transparent', fontSize: 18, cursor: 'pointer' }}>+</button>
                          </div>
                          <button disabled={busy} onClick={() => onRemove(l)} aria-label={`Remove ${l.name}`} style={{ height: 44, padding: '0 6px', border: 0, background: 'transparent', fontSize: 13, fontWeight: 600, color: MUTED, textDecoration: 'underline', cursor: 'pointer' }}>Remove</button>
                        </div>
                      </div>
                    </div>
                  ))}
                  <div style={{ margin: '20px 0 24px', padding: '14px 16px', borderRadius: 12, background: '#F6F5F2', fontSize: 13, lineHeight: 1.5, color: '#3A3F44' }}>
                    Prices are checked again when you pay. If something sells out, we remove it and tell you.
                  </div>
                </>
              )}
            </div>

            {!empty && (
              <div style={{ flexShrink: 0, padding: '20px 24px 24px', borderTop: `1px solid ${LINE}`, background: '#fff' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span style={{ fontSize: 15, fontWeight: 600 }}>Total</span>
                  <span style={{ fontSize: 24, fontWeight: 800 }}>{moneyText(total, template)}</span>
                </div>
                <div style={{ marginTop: 4, fontSize: 12, color: MUTED }}>Delivery is arranged with you after payment.</div>
                {shownError && <p role="alert" style={{ margin: '12px 0 0', fontSize: 13, color: '#B3261E' }}>{shownError}</p>}
                <button onClick={startCheckout} disabled={busy} style={{ marginTop: 16, width: '100%', height: 56, border: 0, borderRadius: 14, background: accent, color: onAccent, fontSize: 16, fontWeight: 700, cursor: busy ? 'wait' : 'pointer', opacity: busy ? 0.7 : 1 }}>
                  {busy ? 'One moment…' : 'Checkout'}
                </button>
                <button onClick={close} style={{ ...ghost, marginTop: 10, width: '100%', height: 48 }}>Keep shopping</button>
              </div>
            )}
          </>
        )}

        {step === 'details' && (
          <form onSubmit={submitDetails} noValidate style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <div style={{ height: 68, padding: '0 12px 0 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: `1px solid ${LINE}`, flexShrink: 0 }}>
              <button type="button" onClick={() => { setStep('cart'); setFormError(''); onClearError() }} style={{ ...ghost, display: 'flex', alignItems: 'center', gap: 6 }}>
                <Icon size={18} stroke="#3A3F44" width={1.9}><path d="M15 6l-6 6 6 6" /></Icon>Back to cart
              </button>
              <button type="button" onClick={close} aria-label="Close" style={{ width: 44, height: 44, border: 0, background: 'transparent', cursor: 'pointer' }}>
                <Icon size={20} width={1.9}><path d="M6 6l12 12M18 6L6 18" /></Icon>
              </button>
            </div>
            <div style={{ flexGrow: 1, overflowY: 'auto', padding: '24px 24px 0' }}>
              <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: accent }}>Step 2 of 2</div>
              <h2 style={{ margin: '8px 0 0', fontSize: 26, lineHeight: 1.15, fontWeight: 800 }}>Your details</h2>
              <p style={{ margin: '8px 0 0', fontSize: 14, lineHeight: 1.5, color: '#3A3F44' }}>We use these to send your payment link and confirm your order.</p>

              <div style={{ marginTop: 22 }}>
                <label htmlFor="sf-name" style={LABEL}>Full name</label>
                <input id="sf-name" autoComplete="name" style={FIELD} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div style={{ marginTop: 16 }}>
                <label htmlFor="sf-phone" style={LABEL}>WhatsApp number</label>
                <input id="sf-phone" type="tel" autoComplete="tel" style={FIELD} value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
              </div>
              <div style={{ marginTop: 16 }}>
                <label htmlFor="sf-email" style={LABEL}>Email <span style={{ fontWeight: 500, color: MUTED }}>(optional)</span></label>
                <input id="sf-email" type="email" autoComplete="email" style={FIELD} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                <div style={{ marginTop: 6, fontSize: 12, color: MUTED }}>We will also email your payment link.</div>
              </div>
              <label style={{ marginTop: 20, display: 'flex', gap: 12, alignItems: 'flex-start', fontSize: 13, lineHeight: 1.5, color: '#3A3F44', cursor: 'pointer' }}>
                <input type="checkbox" checked={form.consent} onChange={(e) => setForm({ ...form, consent: e.target.checked })} style={{ margin: '2px 0 0', width: 20, height: 20, accentColor: accent, flexShrink: 0 }} />
                <span>I agree that {orgName} may contact me about this order on WhatsApp and email.</span>
              </label>

              <div style={{ margin: '24px 0', padding: 16, borderRadius: 14, background: '#F6F5F2' }}>
                {lines.map((l, i) => (
                  <div key={l.key} style={{ marginTop: i ? 8 : 0, display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13, color: '#3A3F44' }}>
                    <span>{l.name} x{l.qty}</span><span style={{ fontWeight: 700, color: INK }}>{moneyText(l.lineTotal, template)}</span>
                  </div>
                ))}
              </div>
            </div>
            <div style={{ flexShrink: 0, padding: '18px 24px 24px', borderTop: `1px solid ${LINE}`, background: '#fff' }}>
              {shownError && <p role="alert" style={{ margin: '0 0 12px', fontSize: 13, color: '#B3261E' }}>{shownError}</p>}
              <button type="submit" disabled={busy} style={{ width: '100%', height: 58, border: 0, borderRadius: 14, background: accent, color: onAccent, fontSize: 16, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, cursor: busy ? 'wait' : 'pointer', opacity: busy ? 0.7 : 1 }}>
                <Icon size={20} stroke={onAccent} width={1.9}><rect x="4" y="10" width="16" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></Icon>
                {busy ? 'One moment…' : `Pay ${moneyText(total, template)} with Paystack`}
              </button>
              <div style={{ marginTop: 10, textAlign: 'center', fontSize: 12, color: MUTED }}>You will be taken to Paystack to pay securely.</div>
            </div>
          </form>
        )}

        {step === 'done' && (
          <div style={{ padding: '40px 24px', display: 'flex', flexDirection: 'column', gap: 16, flexGrow: 1 }}>
            {result && result.human ? (
              <>
                <h2 style={{ margin: 0, fontSize: 24, fontWeight: 800 }}>Thank you</h2>
                <p style={{ margin: 0, fontSize: 15, lineHeight: 1.6, color: '#3A3F44' }}>
                  We could not make a payment link just now, so a team member will complete your order with you. We have your details.
                </p>
                {waHref && (
                  <a href={waHref} target="_blank" rel="noopener noreferrer" style={{ height: 52, borderRadius: 14, background: accent, color: onAccent, fontSize: 15, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
                    <WhatsAppIcon stroke={onAccent} />Message us on WhatsApp
                  </a>
                )}
              </>
            ) : (
              <>
                <h2 style={{ margin: 0, fontSize: 24, fontWeight: 800 }}>Taking you to Paystack…</h2>
                <p style={{ margin: 0, fontSize: 15, lineHeight: 1.6, color: '#3A3F44' }}>Your order is ready to pay. If the page does not open by itself, use the button below.</p>
                {result && result.url && (
                  <a href={result.url} style={{ height: 52, borderRadius: 14, background: accent, color: onAccent, fontSize: 15, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>Open the payment page</a>
                )}
              </>
            )}
            <button onClick={close} style={{ ...ghost, alignSelf: 'flex-start' }}>Close</button>
          </div>
        )}
      </div>
    </div>
  )
}
