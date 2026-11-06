/**
 * frontend/src/modules/admin/AdQuestionsConfig.jsx
 * AD-Q-1 - route the preset questions on a click-to-WhatsApp ad.
 *
 * Each row: the exact question shown on the ad, what happens (bot answers + catalogue link, or straight to a rep),
 * and the reply the customer gets. Pattern 50: service calls via admin.service.js only.
 */
import { useState, useEffect } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'

const ACTION_LABELS = {
  bot_catalog: 'Bot replies with the catalogue link (no rep)',
  rep:         'Send straight to a sales rep',
}
const BLANK = { question: '', action: 'rep', reply: '' }

const card  = { background: '#0a1a24', border: '1px solid #1e3a4f', borderRadius: 12, padding: '18px 20px', marginBottom: 14 }
const label = { display: 'block', fontSize: 11, color: '#7A9BAD', margin: '0 0 5px', fontFamily: ds.fontDm }
const input = {
  width: '100%', boxSizing: 'border-box', background: '#06131b', color: 'white', border: '1px solid #1e3a4f',
  borderRadius: 8, padding: '9px 11px', fontSize: 13, fontFamily: ds.fontDm,
}

export default function AdQuestionsConfig() {
  const [rules,   setRules]   = useState([])
  const [loading, setLoading] = useState(true)
  const [saving,  setSaving]  = useState(false)
  const [msg,     setMsg]     = useState('')
  const [err,     setErr]     = useState('')

  useEffect(() => {
    adminSvc.getAdQuestions()
      .then(r => setRules(r?.rules || []))
      .catch(() => setErr('Could not load your ad questions.'))
      .finally(() => setLoading(false))
  }, [])

  const edit = (i, patch) => { setMsg(''); setRules(rs => rs.map((r, j) => (j === i ? { ...r, ...patch } : r))) }
  const remove = (i) => { setMsg(''); setRules(rs => rs.filter((_, j) => j !== i)) }
  const add = () => { setMsg(''); setRules(rs => [...rs, { ...BLANK }]) }

  const save = async () => {
    setSaving(true); setErr(''); setMsg('')
    try {
      const res = await adminSvc.setAdQuestions(rules)
      setRules(res?.rules || [])
      setMsg('Saved.')
    } catch (e) {
      const d = e?.response?.data?.detail
      setErr(typeof d === 'string' ? d : e?.response?.status === 403
        ? 'Only owners and ops managers can change this.' : 'Could not save. Try again.')
    }
    setSaving(false)
  }

  if (loading) return <div style={{ padding: 32, color: '#7A9BAD', fontSize: 13 }}>Loading…</div>

  return (
    <div style={{ maxWidth: 720, fontFamily: ds.fontDm }}>
      <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: 'white', margin: '0 0 6px' }}>
        Ad questions
      </h3>
      <p style={{ fontSize: 12, color: '#7A9BAD', margin: '0 0 16px', lineHeight: 1.5 }}>
        When someone taps a question on your click-to-WhatsApp ad, that question arrives as their first message.
        Type each question exactly as it appears on the ad and choose what happens. Messages that don't match
        any question follow your normal WhatsApp menu.
      </p>

      {err && <div style={{ ...card, borderColor: '#ef444444', color: '#ef4444', fontSize: 13 }}>{err}</div>}

      {rules.map((r, i) => (
        <div key={i} style={card}>
          <label style={label} htmlFor={`adq-q-${i}`}>Question on the ad</label>
          <input id={`adq-q-${i}`} style={input} value={r.question} maxLength={200}
                 onChange={e => edit(i, { question: e.target.value })} />
          <label style={{ ...label, marginTop: 12 }} htmlFor={`adq-a-${i}`}>What happens</label>
          <select id={`adq-a-${i}`} style={input} value={r.action} onChange={e => edit(i, { action: e.target.value })}>
            {Object.entries(ACTION_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <label style={{ ...label, marginTop: 12 }} htmlFor={`adq-r-${i}`}>
            {r.action === 'bot_catalog' ? 'Reply shown with the catalogue link' : 'Short reply to the customer (optional)'}
          </label>
          <textarea id={`adq-r-${i}`} style={{ ...input, minHeight: 74, resize: 'vertical' }} value={r.reply}
                    maxLength={1000} onChange={e => edit(i, { reply: e.target.value })} />
          <button type="button" onClick={() => remove(i)}
                  style={{ marginTop: 10, background: 'transparent', color: '#ef4444', border: 'none', fontSize: 12, cursor: 'pointer', padding: 0 }}>
            Remove question
          </button>
        </div>
      ))}

      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 4 }}>
        <button type="button" onClick={add} disabled={rules.length >= 10}
                style={{ background: 'transparent', color: ds.teal, border: `1.5px solid ${ds.teal}`, borderRadius: 10,
                         padding: '10px 16px', fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 13, cursor: 'pointer' }}>
          Add question
        </button>
        <button type="button" onClick={save} disabled={saving}
                style={{ background: ds.teal, color: 'white', border: 'none', borderRadius: 10, padding: '10px 20px',
                         fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 13, cursor: saving ? 'not-allowed' : 'pointer' }}>
          {saving ? 'Saving…' : 'Save'}
        </button>
        {msg && <span style={{ fontSize: 12, color: '#22d3a5' }}>{msg}</span>}
      </div>
    </div>
  )
}
