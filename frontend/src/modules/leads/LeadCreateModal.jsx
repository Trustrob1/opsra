/**
 * LeadCreateModal
 *
 * Calls POST /api/v1/leads
 * Required: full_name, source
 * All other fields optional — matches LeadCreate Pydantic model in models/leads.py
 *
 * Field names come from the `leads` table schema (Technical Spec §3.2).
 * org_id is NEVER in the payload — derived from JWT server-side.
 *
 * Sources (LeadSource enum): facebook_ad | instagram_ad | landing_page |
 *   whatsapp_inbound | manual_phone | manual_referral | import
 *
 * Branches (LeadBranches): 1 | 2-3 | 4-10 | 10+
 */
import { useState } from 'react'
import { createLead } from '../../services/leads.service'
import { ds, SOURCE_LABELS, BRANCHES_OPTIONS } from '../../utils/ds'

const SOURCES = Object.entries(SOURCE_LABELS)

const INITIAL = {
  full_name:      '',
  source:         '',
  phone:          '',
  whatsapp:       '',
  email:          '',
  business_name:  '',
  business_type:  '',
  location:       '',
  branches:       '',
  problem_stated: '',
  referrer:       '',
}

export default function LeadCreateModal({ onClose, onCreated }) {
  const [form, setForm]         = useState(INITIAL)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]       = useState(null)

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const handleSubmit = async () => {
    if (!form.full_name.trim()) { setError('Full name is required.'); return }
    if (!form.source)            { setError('Source is required.'); return }

    setSubmitting(true)
    setError(null)

    // Build payload — omit empty strings so optional fields are truly absent
    const payload = Object.fromEntries(
      Object.entries(form).filter(([, v]) => v !== ''),
    )

    try {
      const res = await createLead(payload)
      if (res.success) {
        onCreated?.(res.data)
        onClose()
      } else {
        setError(res.error ?? 'Could not create lead')
      }
    } catch (err) {
      const detail = err?.response?.data
      setError(detail?.error ?? detail?.message ?? 'Something went wrong')
    } finally {
      setSubmitting(false)
    }
  }

  const showReferrer = form.source === 'manual_referral'

  return (
    <ModalOverlay onClose={onClose}>
      {/* Header */}
      <div style={headerStyle}>
        <div>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: ds.dark, margin: 0 }}>
            New Lead
          </h2>
          <p style={{ fontSize: 13, color: ds.gray, margin: '2px 0 0' }}>
            Required fields marked with *
          </p>
        </div>
        <button onClick={onClose} style={closeBtn}>✕</button>
      </div>

      {/* Body */}
      <div style={{ padding: '24px' }}>

        {/* Required section */}
        <SectionLabel>Contact Details</SectionLabel>

        <TwoCol>
          <Field label="Full Name *">
            <input
              type="text"
              placeholder="e.g. Amaka Johnson"
              value={form.full_name}
              onChange={set('full_name')}
              style={inputStyle}
              autoFocus
            />
          </Field>
          <Field label="Lead Source *">
            <select value={form.source} onChange={set('source')} style={inputStyle}>
              <option value="">— Select source —</option>
              {SOURCES.map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
          </Field>
        </TwoCol>

        <TwoCol>
          <Field label="Phone">
            <input
              type="tel"
              placeholder="+234 800 000 0000"
              value={form.phone}
              onChange={set('phone')}
              style={inputStyle}
            />
          </Field>
          <Field label="WhatsApp Number">
            <input
              type="tel"
              placeholder="+234 800 000 0000"
              value={form.whatsapp}
              onChange={set('whatsapp')}
              style={inputStyle}
            />
          </Field>
        </TwoCol>

        <Field label="Email Address">
          <input
            type="email"
            placeholder="amaka@business.com"
            value={form.email}
            onChange={set('email')}
            style={inputStyle}
          />
        </Field>

        {/* Referrer — only shown for manual_referral source */}
        {showReferrer && (
          <Field label="Referred By">
            <input
              type="text"
              placeholder="Name of person who referred this lead"
              value={form.referrer}
              onChange={set('referrer')}
              style={inputStyle}
            />
          </Field>
        )}

        <SectionLabel>Business Details</SectionLabel>

        <TwoCol>
          <Field label="Business Name">
            <input
              type="text"
              placeholder="e.g. Amaka Supermarket"
              value={form.business_name}
              onChange={set('business_name')}
              style={inputStyle}
            />
          </Field>
          <Field label="Business Type">
            <input
              type="text"
              placeholder="e.g. Supermarket, Pharmacy"
              value={form.business_type}
              onChange={set('business_type')}
              style={inputStyle}
            />
          </Field>
        </TwoCol>

        <TwoCol>
          <Field label="Location">
            <input
              type="text"
              placeholder="e.g. Ikeja, Lagos"
              value={form.location}
              onChange={set('location')}
              style={inputStyle}
            />
          </Field>
          <Field label="Number of Branches">
            <select value={form.branches} onChange={set('branches')} style={inputStyle}>
              <option value="">— Select —</option>
              {BRANCHES_OPTIONS.map((b) => (
                <option key={b} value={b}>{b}</option>
              ))}
            </select>
          </Field>
        </TwoCol>

        <Field label="Problem / Need Stated">
          <textarea
            placeholder="What challenge or problem did they describe?"
            value={form.problem_stated}
            onChange={set('problem_stated')}
            style={{ ...inputStyle, minHeight: 80, resize: 'vertical' }}
          />
        </Field>

        {/* Error */}
        {error && (
          <p style={{ color: ds.red, fontSize: 13, marginBottom: 14 }}>⚠ {error}</p>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
          <button onClick={onClose} disabled={submitting} style={secondaryBtn}>
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting || !form.full_name || !form.source}
            style={{
              ...primaryBtn,
              opacity: (!form.full_name || !form.source || submitting) ? 0.5 : 1,
              cursor:  (!form.full_name || !form.source || submitting) ? 'not-allowed' : 'pointer',
            }}
          >
            {submitting ? 'Creating…' : '+ Create Lead'}
          </button>
        </div>
      </div>
    </ModalOverlay>
  )
}

// ─── Layout helpers ───────────────────────────────────────────────────────────

function ModalOverlay({ children, onClose }) {
  return (
    <div
      onClick={(e) => e.target === e.currentTarget && onClose()}
      style={{
        position:       'fixed',
        inset:          0,
        background:     'rgba(0,0,0,0.45)',
        zIndex:         ds.z.modal,
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'center',
        padding:        16,
      }}
    >
      <div style={{
        background:   'white',
        borderRadius: ds.radius.xxl,
        width:        680,
        maxWidth:     '100%',
        maxHeight:    '90vh',
        overflowY:    'auto',
        boxShadow:    ds.modalShadow,
      }}>
        {children}
      </div>
    </div>
  )
}

function TwoCol({ children }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 0 }}>
      {children}
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14 }}>
      <label style={labelStyle}>{label}</label>
      {children}
    </div>
  )
}

function SectionLabel({ children }) {
  return (
    <div style={{
      display:       'flex',
      alignItems:    'center',
      gap:           12,
      margin:        '4px 0 16px',
      fontFamily:    ds.fontSyne,
      fontWeight:    600,
      fontSize:      12,
      color:         ds.teal,
      textTransform: 'uppercase',
      letterSpacing: '0.8px',
    }}>
      {children}
      <span style={{ flex: 1, height: 1, background: ds.border }} />
    </div>
  )
}

const headerStyle = {
  padding:        '20px 24px',
  borderBottom:   `1px solid ${ds.border}`,
  display:        'flex',
  alignItems:     'center',
  justifyContent: 'space-between',
  position:       'sticky',
  top:            0,
  background:     'white',
  zIndex:         10,
}

const labelStyle = {
  fontSize:      12,
  fontWeight:    500,
  color:         ds.gray,
  textTransform: 'uppercase',
  letterSpacing: '0.6px',
}

const inputStyle = {
  width:        '100%',
  border:       `1.5px solid ${ds.border}`,
  borderRadius: ds.radius.md,
  padding:      '11px 14px',
  fontSize:     13.5,
  color:        ds.dark,
  fontFamily:   ds.fontDm,
  background:   'white',
  outline:      'none',
  boxSizing:    'border-box',
  transition:   'border-color 0.2s',
}

const closeBtn  = { background: 'none', border: 'none', fontSize: 20, color: ds.gray, cursor: 'pointer', padding: '4px 8px' }
const primaryBtn = {
  display: 'inline-flex', alignItems: 'center', gap: 8,
  padding: '11px 22px', borderRadius: ds.radius.md, border: 'none',
  background: ds.teal, color: 'white', fontSize: 13.5, fontWeight: 600,
  fontFamily: ds.fontSyne, cursor: 'pointer', transition: 'all 0.15s',
}
const secondaryBtn = { ...primaryBtn, background: ds.mint, color: ds.tealDark, border: `1px solid ${ds.border}` }
