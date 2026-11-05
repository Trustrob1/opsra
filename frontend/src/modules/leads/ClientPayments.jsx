/**
 * ClientPayments - REALTOR-LINE-1
 * Managers record money received in the company account for a lead.
 * Recording a payment creates the realtor's commission and tells them on WhatsApp.
 */
import { useState, useEffect, useCallback } from 'react'
import { getLeadPayments, recordLeadPayment } from '../../services/leads.service'
import { ds } from '../../utils/ds'

const naira = (n) => '₦' + Number(n || 0).toLocaleString('en-NG', { maximumFractionDigits: 2 })
const field = { width: '100%', padding: '10px 12px', border: '1.5px solid #D9E2EC', borderRadius: 8, fontSize: 14, fontFamily: ds.fontDm, boxSizing: 'border-box' }
const label = { fontSize: 12, fontWeight: 600, color: ds.gray, display: 'block', marginBottom: 4 }

export default function ClientPayments({ leadId }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [amount, setAmount]   = useState('')
  const [reference, setRef]   = useState('')
  const [note, setNote]       = useState('')
  const [saving, setSaving]   = useState(false)
  const [done, setDone]       = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    getLeadPayments(leadId)
      .then((d) => { setData(d); setError(null) })
      .catch(() => setError('Could not load payments. Please try again.'))
      .finally(() => setLoading(false))
  }, [leadId])
  useEffect(() => { load() }, [load])

  const save = async () => {
    const value = Number(String(amount).replace(/,/g, ''))
    if (!value || value <= 0) { setError('Enter the amount received.'); return }
    setSaving(true); setError(null); setDone(null)
    try {
      const out = await recordLeadPayment(leadId, { amount_ngn: value, reference: reference.trim() || null, note: note.trim() || null })
      setDone(out?.commission ? `Payment recorded. Commission of ${naira(out.commission.amount_ngn)} created.` : 'Payment recorded.')
      setAmount(''); setRef(''); setNote('')
      load()
    } catch (e) {
      setError(e?.response?.data?.detail?.message || 'Could not record the payment. Please try again.')
    } finally { setSaving(false) }
  }

  const rows = data?.payments || []
  return (
    <div style={{ display: 'grid', gap: 16, maxWidth: 560 }}>
      <div style={{ background: 'white', border: '1px solid #E5ECF2', borderRadius: ds.radius.lg, padding: 16 }}>
        <p style={{ margin: '0 0 4px', fontWeight: 700, fontFamily: ds.fontSyne, fontSize: 14 }}>Record payment received</p>
        <p style={{ margin: '0 0 12px', fontSize: 12.5, color: ds.gray }}>
          {data?.realtor ? `${data.realtor} earns commission on this payment and is told on WhatsApp.` : 'No realtor is linked to this lead, so no commission is created for a realtor.'}
        </p>
        <label style={label} htmlFor="cp-amount">Amount received (₦)</label>
        <input id="cp-amount" style={field} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        <label style={{ ...label, marginTop: 10 }} htmlFor="cp-ref">Bank reference (optional)</label>
        <input id="cp-ref" style={field} value={reference} onChange={(e) => setRef(e.target.value)} maxLength={120} />
        <label style={{ ...label, marginTop: 10 }} htmlFor="cp-note">Note (optional)</label>
        <input id="cp-note" style={field} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
        {error && <p role="alert" style={{ color: '#C53030', fontSize: 13, margin: '10px 0 0' }}>{error}</p>}
        {done && <p style={{ color: '#2F855A', fontSize: 13, margin: '10px 0 0' }}>{done}</p>}
        <button onClick={save} disabled={saving}
          style={{ marginTop: 12, background: ds.teal, color: 'white', border: 'none', borderRadius: ds.radius.md, padding: '10px 18px', fontWeight: 700, fontFamily: ds.fontSyne, fontSize: 13.5, cursor: saving ? 'default' : 'pointer', minHeight: 44, opacity: saving ? 0.7 : 1 }}>
          {saving ? 'Recording…' : 'Record payment'}
        </button>
      </div>

      <div style={{ background: 'white', border: '1px solid #E5ECF2', borderRadius: ds.radius.lg, padding: 16 }}>
        <p style={{ margin: '0 0 10px', fontWeight: 700, fontFamily: ds.fontSyne, fontSize: 14 }}>
          Payments{rows.length ? ` · ${naira(data.total_ngn)} total` : ''}
        </p>
        {loading && <p style={{ color: ds.gray, fontSize: 13, margin: 0 }}>Loading…</p>}
        {!loading && rows.length === 0 && <p style={{ color: ds.gray, fontSize: 13, margin: 0 }}>No payments recorded yet. Use the form above when money reaches the company account.</p>}
        {rows.map((p) => (
          <div key={p.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '8px 0', borderTop: '1px solid #EEF2F6', fontSize: 13 }}>
            <span style={{ color: ds.gray }}>{new Date(p.received_at).toLocaleDateString('en-NG', { day: 'numeric', month: 'short', year: 'numeric' })}{p.reference ? ` · ${p.reference}` : ''}</span>
            <strong>{naira(p.amount_ngn)}</strong>
          </div>
        ))}
      </div>
    </div>
  )
}
