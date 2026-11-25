/**
 * frontend/src/pages/InvoicePublicPage.jsx
 * INV-3 — /i/<token>: the customer's own page for a quote or invoice from a business on Opsra.
 * Shows the document, a PDF download, the business's bank details (invoices), and Accept / Decline (open quotes).
 * INV-4: Pay now (card / transfer / USSD through the business's own Paystack) when the business has it connected; after
 * Paystack sends the customer back here (?reference=...) the payment is checked and the receipt shows at once.
 * No login, no Opsra menus; styled with the business's own colour.
 */
import { useCallback, useEffect, useState } from 'react'
import { Download, CheckCircle2, XCircle, Copy, Check, CreditCard } from 'lucide-react'
import { getPublicDoc, answerQuote, publicPdfUrl, publicError, startPayment, verifyPayment, publicReceiptUrl } from '../services/invoicesPublic.service'

const naira = (n) => `₦${Number(n || 0).toLocaleString('en-NG', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const day = (v) => (v ? new Date(`${String(v).slice(0, 10)}T12:00:00`).toLocaleDateString('en-NG', { day: 'numeric', month: 'short', year: 'numeric' }) : '')
const HEX = /^#[0-9a-fA-F]{6}$/
const FONT = "'Hanken Grotesk', system-ui, -apple-system, 'Segoe UI', sans-serif"
const STATUS = {
  issued: null, accepted: ['Accepted', '#E6F6EF', '#11643F'], declined: ['Declined', '#FDECEC', '#9B1C1C'],
  paid: ['Paid', '#E6F6EF', '#11643F'], part_paid: ['Part paid', '#FFF4DB', '#7A4B00'], overdue: ['Overdue', '#FDECEC', '#9B1C1C'],
  expired: ['Expired', '#F1F2F4', '#4B5563'], void: ['Cancelled', '#F1F2F4', '#4B5563'],
}

export default function InvoicePublicPage({ token }) {
  const [doc, setDoc] = useState(null)
  const [gone, setGone] = useState('')
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState(null)
  const [confirmDecline, setConfirmDecline] = useState(false)
  const [copied, setCopied] = useState(false)

  const load = useCallback(() => getPublicDoc(token).then(setDoc).catch((e) => {
    setGone(e?.response?.status === 404 ? 'This link is not valid. Please ask the business to send it again.' : publicError(e, 'Could not load this page. Please try again.'))
  }), [token])
  useEffect(() => {
    // INV-4: back from Paystack? Check the payment first, then show the page.
    const ref = new URLSearchParams(window.location.search).get('reference')
    if (!ref || !/^inv_[0-9a-f]{32}_[0-9a-f]{8}$/.test(ref)) { load(); return }
    window.history.replaceState(null, '', window.location.pathname)
    verifyPayment(token, ref).then((r) => {
      setDoc(r.doc)
      setMsg(r.paid ? { ok: true, text: 'Payment received. Thank you! Your receipt is below.' }
        : { ok: false, text: 'We could not confirm the payment yet. If money left your account, it will show here shortly.' })
    }).catch(() => load())
  }, [load, token])

  const payNow = async () => {
    setBusy('pay'); setMsg(null)
    try { const r = await startPayment(token); window.location.assign(r.checkout_url) }
    catch (e) { setMsg({ ok: false, text: publicError(e) }); setBusy('') }
  }
  useEffect(() => {
    if (!doc) return
    const kind = doc.doc_type === 'quote' ? 'Quote' : 'Invoice'
    document.title = `${kind} ${doc.number || ''} · ${doc.issuer?.business_name || ''}`.trim()
  }, [doc])

  const answer = async (accept) => {
    setBusy(accept ? 'accept' : 'decline'); setMsg(null)
    try {
      setDoc(await answerQuote(token, accept))
      setMsg({ ok: true, text: accept ? 'Thank you. The business has been told you accepted, and will send your invoice.' : 'Thank you. The business has been told.' })
    } catch (e) { setMsg({ ok: false, text: publicError(e) }) } finally { setBusy(''); setConfirmDecline(false) }
  }

  if (gone) return <Shell><div style={{ ...box, textAlign: 'center' }}><p style={{ margin: 0, color: '#4B5563' }}>{gone}</p></div></Shell>
  if (!doc) return <Shell><p style={{ color: '#6B7280', textAlign: 'center' }}>Loading…</p></Shell>

  const iss = doc.issuer || {}
  const colour = HEX.test(iss.brand_colour || '') ? iss.brand_colour : '#0d9488'
  const quote = doc.doc_type === 'quote'
  const pill = STATUS[doc.status]
  const due = quote ? doc.total : doc.balance_due
  const bank = !quote && !doc.voided && doc.status !== 'paid' && iss.account_number
  const btn = (bg, fg, border) => ({ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8, minHeight: 48, padding: '0 20px', borderRadius: 10, border: border || 'none', background: bg, color: fg, fontWeight: 700, fontSize: 15, cursor: 'pointer', fontFamily: FONT, textDecoration: 'none' })

  return (
    <Shell>
      <div style={{ ...box, padding: 0, overflow: 'hidden' }}>
        <div style={{ height: 6, background: colour }} />
        <div style={{ padding: '20px 20px 4px', display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          {iss.logo_url && <img src={iss.logo_url} alt="" style={{ maxHeight: 56, maxWidth: 160, objectFit: 'contain' }} />}
          <div style={{ flex: 1, minWidth: 180 }}>
            <div style={{ fontWeight: 800, fontSize: 18, color: '#111827' }}>{iss.business_name}</div>
            <div style={{ color: '#6B7280', fontSize: 13.5, lineHeight: 1.5 }}>{[iss.address, iss.phone, iss.email].filter(Boolean).join(' · ')}</div>
          </div>
        </div>
        <div style={{ padding: 20, display: 'grid', gap: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <h1 style={{ margin: 0, fontSize: 22, color: '#111827' }}>{quote ? 'Quote' : 'Invoice'} {doc.number}</h1>
            {pill && <span style={{ padding: '3px 10px', borderRadius: 999, background: pill[1], color: pill[2], fontSize: 13, fontWeight: 700 }}>{pill[0]}</span>}
          </div>
          <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', fontSize: 14 }}>
            <Fact k={quote ? 'For' : 'Bill to'} v={doc.customer?.name} />
            <Fact k="Date" v={day(doc.issue_date)} />
            {doc.due_date && <Fact k={quote ? 'Valid until' : 'Due by'} v={day(doc.due_date)} />}
          </div>

          <div style={{ border: '1px solid #E5E7EB', borderRadius: 10, overflow: 'hidden' }}>
            {(doc.items || []).map((it, i) => (
              <div key={i} style={{ display: 'flex', gap: 12, padding: '12px 14px', borderTop: i ? '1px solid #E5E7EB' : 'none', fontSize: 14.5 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ color: '#111827', wordBreak: 'break-word' }}>{it.description}</div>
                  <div style={{ color: '#6B7280', fontSize: 13 }}>{Number(it.quantity)} × {naira(it.unit_price)}</div>
                </div>
                <div style={{ fontWeight: 600, whiteSpace: 'nowrap', color: '#111827' }}>{naira(it.line_total)}</div>
              </div>
            ))}
          </div>

          <div style={{ marginLeft: 'auto', width: '100%', maxWidth: 320, display: 'grid', gap: 6, fontSize: 14.5 }}>
            <Line k="Subtotal" v={naira(doc.subtotal)} />
            {Number(doc.discount) > 0 && <Line k="Discount" v={`-${naira(doc.discount)}`} />}
            {Number(doc.vat_amount) > 0 && <Line k={`VAT (${Number(doc.vat_rate)}%)`} v={naira(doc.vat_amount)} />}
            <div style={{ borderTop: `2px solid ${colour}`, paddingTop: 6 }}><Line k={<b>Total</b>} v={<b>{naira(doc.total)}</b>} /></div>
            {!quote && Number(doc.amount_paid) > 0 && <><Line k="Paid" v={naira(doc.amount_paid)} /><Line k={<b>Balance due</b>} v={<b>{naira(doc.balance_due)}</b>} /></>}
          </div>

          {!quote && doc.can_pay && (
            <button type="button" disabled={!!busy} onClick={payNow} style={{ ...btn(colour, '#fff'), opacity: busy ? 0.6 : 1 }}>
              <CreditCard size={18} />{busy === 'pay' ? 'Opening payment…' : `Pay ${naira(doc.balance_due)} now`}</button>
          )}

          {bank && (
            <div style={{ background: '#F9FAFB', border: '1px solid #E5E7EB', borderRadius: 10, padding: 14, display: 'grid', gap: 6 }}>
              <b style={{ color: '#111827' }}>{doc.can_pay ? 'Or pay' : 'Pay'} {naira(due)} by bank transfer</b>
              <Line k="Bank" v={iss.bank_name} />
              <Line k="Account name" v={iss.account_name} />
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <span style={{ color: '#6B7280' }}>Account number</span>
                <button type="button" onClick={async () => { try { await navigator.clipboard.writeText(iss.account_number); setCopied(true); setTimeout(() => setCopied(false), 2000) } catch { /* the number is on screen to copy by hand */ } }}
                  style={{ border: 'none', background: 'none', cursor: 'pointer', fontFamily: FONT, fontSize: 16, fontWeight: 700, color: '#111827', display: 'flex', alignItems: 'center', gap: 6, minHeight: 44 }}
                  aria-label="Copy account number">{iss.account_number}{copied ? <Check size={16} color="#11643F" /> : <Copy size={16} color="#6B7280" />}</button>
              </div>
              <small style={{ color: '#6B7280' }}>Use {doc.number} as the payment reference, then send the receipt to {iss.business_name}.</small>
            </div>
          )}

          {!quote && (doc.receipts || []).length > 0 && (
            <div style={{ display: 'grid', gap: 6 }}>
              <div style={{ color: '#6B7280', fontSize: 12.5, fontWeight: 600 }}>Payments received</div>
              {doc.receipts.map((r) => (
                <div key={r.token} style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', fontSize: 14 }}>
                  <span style={{ color: '#111827', fontWeight: 600 }}>{naira(r.amount)}</span>
                  <span style={{ color: '#6B7280' }}>{day(r.paid_at)} · {r.number}</span>
                  <a href={publicReceiptUrl(r.token)} rel="nofollow" style={{ marginLeft: 'auto', color: colour, fontWeight: 700, minHeight: 44, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <Download size={16} />Receipt</a>
                </div>
              ))}
            </div>
          )}

          {doc.notes && <Para k="Note" v={doc.notes} />}
          {doc.terms && <Para k="Terms" v={doc.terms} />}

          {doc.can_answer && !confirmDecline && (
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <button type="button" disabled={!!busy} onClick={() => answer(true)} style={{ ...btn(colour, '#fff'), flex: '1 1 200px', opacity: busy ? 0.6 : 1 }}>
                <CheckCircle2 size={18} />{busy === 'accept' ? 'Sending…' : 'Accept this quote'}</button>
              <button type="button" disabled={!!busy} onClick={() => setConfirmDecline(true)} style={{ ...btn('#fff', '#374151', '1.5px solid #D1D5DB'), flex: '0 1 160px' }}>
                <XCircle size={18} />Decline</button>
            </div>
          )}
          {confirmDecline && (
            <div style={{ border: '1px solid #E5E7EB', borderRadius: 10, padding: 14, display: 'grid', gap: 10 }}>
              <span style={{ color: '#111827' }}>Decline this quote? {iss.business_name} will be told.</span>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <button type="button" disabled={!!busy} onClick={() => answer(false)} style={btn('#9B1C1C', '#fff')}>{busy === 'decline' ? 'Sending…' : 'Yes, decline'}</button>
                <button type="button" onClick={() => setConfirmDecline(false)} style={btn('#fff', '#374151', '1.5px solid #D1D5DB')}>Keep it</button>
              </div>
            </div>
          )}
          {msg && <div role="status" style={{ color: msg.ok ? '#11643F' : '#9B1C1C', fontSize: 14.5 }}>{msg.text}</div>}

          <a href={publicPdfUrl(token)} style={{ ...btn('#fff', '#111827', '1.5px solid #D1D5DB'), justifySelf: 'start' }} rel="nofollow">
            <Download size={18} />Download PDF</a>
          {(iss.rc_number || iss.tin || iss.footer) && (
            <div style={{ color: '#9CA3AF', fontSize: 12.5, lineHeight: 1.6 }}>
              {[iss.rc_number && `RC ${String(iss.rc_number).replace(/^(RC|BN)\s*/i, '')}`, iss.tin && `TIN ${iss.tin}`].filter(Boolean).join(' · ')}
              {iss.footer && <div>{iss.footer}</div>}
            </div>
          )}
        </div>
      </div>
      <p style={{ textAlign: 'center', color: '#9CA3AF', fontSize: 12, marginTop: 14 }}>Sent with Opsra</p>
    </Shell>
  )
}

const box = { background: '#fff', border: '1px solid #E5E7EB', borderRadius: 14, padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }
function Shell({ children }) {
  return <div style={{ minHeight: '100vh', background: '#F3F4F6', padding: '24px 14px 40px', fontFamily: FONT, boxSizing: 'border-box' }}><div style={{ maxWidth: 680, margin: '0 auto' }}>{children}</div></div>
}
function Fact({ k, v }) { return <div><div style={{ color: '#6B7280', fontSize: 12.5, fontWeight: 600 }}>{k}</div><div style={{ color: '#111827', fontWeight: 600 }}>{v || '—'}</div></div> }
function Line({ k, v }) { return <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}><span style={{ color: '#4B5563' }}>{k}</span><span style={{ textAlign: 'right' }}>{v}</span></div> }
function Para({ k, v }) { return <div><div style={{ color: '#6B7280', fontSize: 12.5, fontWeight: 600 }}>{k}</div><div style={{ whiteSpace: 'pre-wrap', color: '#374151', fontSize: 14 }}>{v}</div></div> }
