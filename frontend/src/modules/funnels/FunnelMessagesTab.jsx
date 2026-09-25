/**
 * frontend/src/modules/funnels/FunnelMessagesTab.jsx
 * FUNNEL-1B — edit every message and the follow-up sequence, with a live
 * phone-style preview rendered by the backend (/preview) from UNSAVED edits.
 *
 * Sequence editor: per step — on/off, timing in plain words (amount · unit ·
 * before/after · anchor), who gets it, text, template (+ params), "only while the
 * early price is on", "add the pay button". Add custom steps; reset to defaults.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Plus, Trash2, RotateCcw, Save, Smartphone, AlertTriangle, Info } from 'lucide-react'
import { previewMessage, updateFunnel, getFunnelDefaults, errorMessage } from '../../services/funnels.service'
import { listTemplates } from '../../services/whatsapp.service'
import { Card, SectionTitle, Button, Field, Toggle, Badge, Notice, Modal, Eyebrow } from './funnelUi'
import { T, INPUT, asList } from './funnelKit'

const MESSAGE_FIELDS = [
  { key: 'greeting', label: 'Greeting', hint: 'First reply to every new lead. Sent with the pay button, then the question buttons.', rows: 9 },
  { key: 'pay_button', label: 'Pay button text', hint: 'Shows on the button. Max 20 characters.', max: 20, single: true },
  { key: 'faq_prompt', label: 'Question buttons intro', rows: 2 },
  { key: 'pay_link_resend', label: 'When they ask for the link', hint: 'Sent with a fresh pay button.', rows: 3 },
  { key: 'group_offer', label: 'Group deal', hint: 'Sent when they mention a group or friends.', rows: 3 },
  { key: 'paid_confirmation', label: 'Payment confirmation', hint: 'Sent the moment Paystack confirms. Include the group link and the Gmail request.', rows: 9 },
  { key: 'already_paid', label: 'Already registered', rows: 2 },
  { key: 'email_thanks', label: 'Gmail received', rows: 2 },
  { key: 'handoff_ack', label: 'When you need to reply personally', hint: 'Sent at most once every 6 hours.', rows: 2 },
  { key: 'closed', label: 'Registration closed', rows: 2 },
  { key: 'opted_out', label: 'Unsubscribed', rows: 2 },
]
const SAVE_KEYS = [...MESSAGE_FIELDS.map((f) => f.key), 'faq']

const PLACEHOLDERS = [
  ['{name}', 'First name'], ['{event}', 'Event title'], ['{date}', 'Event date and time'],
  ['{price}', 'Their price right now'], ['{price_line}', 'Price with deadline, or just price'],
  ['{deadline}', 'When their early price ends'], ['{early_price}', 'Early price'], ['{regular_price}', 'Regular price'],
  ['{group_price}', 'Group price'], ['{group_size}', 'Seats in group'], ['{pay_link}', 'Their pay link'],
  ['{group_link}', 'Paid class group'], ['{prep_link}', 'Free prep group'], ['{bonus_link}', 'Prompt Pack link'],
  ['{ref_code}', 'Their referral code'], ['{event_day}', 'Event weekday'], ['{event_time}', 'Event time'],
  ['{close_time}', 'Registration close time'], ['{email}', 'Their Gmail'],
]

const ANCHORS = [
  { value: 'first_message', label: 'their first message', modes: ['window', 'deadline'] },
  { value: 'window_end', label: 'their early price ends', modes: ['window'] },
  { value: 'early_deadline', label: 'the early-price deadline', modes: ['deadline'] },
  { value: 'event_start', label: 'the event starts', modes: ['window', 'deadline'] },
  { value: 'registration_close', label: 'registration closes', modes: ['window', 'deadline'] },
]
const UNITS = [{ value: 1, label: 'minutes' }, { value: 60, label: 'hours' }, { value: 1440, label: 'days' }]
const AUDIENCE = [{ value: 'unpaid', label: 'Not paid yet' }, { value: 'paid', label: 'Paid' }, { value: 'all', label: 'Everyone' }]

function splitOffset(mins) {
  const abs = Math.abs(mins)
  const unit = abs && abs % 1440 === 0 ? 1440 : abs && abs % 60 === 0 ? 60 : 1
  return { amount: abs / unit, unit, dir: mins < 0 ? -1 : 1 }
}

export default function FunnelMessagesTab({ funnel, isActive, canEdit, isMobile, showToast, onSaved }) {
  const [msgs, setMsgs] = useState(() => funnel.effective_messages || {})
  const [steps, setSteps] = useState(() => funnel.effective_sequence || [])
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [target, setTarget] = useState({ message_key: 'greeting' })
  const [templates, setTemplates] = useState([])
  const [confirmReset, setConfirmReset] = useState(false)
  const lastField = useRef(null) // { el, apply(newValue) }

  // Re-seed from the saved funnel whenever it reloads and there are no local edits.
  useEffect(() => {
    if (dirty) return
    setMsgs(funnel.effective_messages || {})
    setSteps(funnel.effective_sequence || [])
  }, [funnel, dirty])

  useEffect(() => {
    if (!isActive) return
    listTemplates().then((r) => setTemplates(asList(r))).catch(() => setTemplates([]))
  }, [isActive])

  const setMsg = (k, v) => { setMsgs((p) => ({ ...p, [k]: v })); setDirty(true) }
  const setStep = (i, patch) => { setSteps((p) => p.map((s, j) => (j === i ? { ...s, ...patch } : s))); setDirty(true) }

  const insertPlaceholder = (ph) => {
    const f = lastField.current
    if (!f?.el) { showToast('Click into a message box first', 'bad'); return }
    const el = f.el
    const start = el.selectionStart ?? el.value.length
    const end = el.selectionEnd ?? el.value.length
    const next = el.value.slice(0, start) + ph + el.value.slice(end)
    f.apply(next)
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(start + ph.length, start + ph.length) })
  }
  const track = (el, apply, tgt) => { lastField.current = { el, apply }; if (tgt) setTarget(tgt) }

  const save = async () => {
    setSaving(true)
    try {
      const messages = Object.fromEntries(SAVE_KEYS.filter((k) => msgs[k] !== undefined).map((k) => [k, msgs[k]]))
      await updateFunnel(funnel.id, { messages, sequence: steps })
      setDirty(false)
      showToast('Messages saved')
      onSaved?.()
    } catch (e) {
      showToast(errorMessage(e, 'Could not save'), 'bad')
    } finally {
      setSaving(false)
    }
  }

  const resetDefaults = async () => {
    try {
      const d = await getFunnelDefaults()
      setMsgs(d.messages)
      setSteps(funnel.pricing_mode === 'deadline' ? d.sequence_deadline : d.sequence_window)
      setDirty(true)
      setConfirmReset(false)
      showToast('Defaults loaded — review, then Save')
    } catch (e) {
      showToast(errorMessage(e), 'bad')
    }
  }

  const addStep = () => {
    let n = 1
    while (steps.some((s) => s.key === `custom_${n}`)) n += 1
    setSteps((p) => [...p, { key: `custom_${n}`, anchor: 'first_message', offset_minutes: 360, audience: 'unpaid', text: 'Hi {name}, ',
      template_name: null, template_params: [], only_if_early: false, include_pay_button: true, enabled: true }])
    setDirty(true)
    setTarget({ step_key: `custom_${n}` })
  }

  const faq = msgs.faq || []
  const setFaq = (i, patch) => setMsg('faq', faq.map((f, j) => (j === i ? { ...f, ...patch } : f)))

  const approved = templates.filter((t) => t.meta_status === 'approved').map((t) => t.name)
  const allTemplateNames = templates.map((t) => t.name)

  return (
    <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'minmax(0, 1fr) 340px', gap: 20, alignItems: 'start', paddingBottom: 0 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 18, minWidth: 0 }}>
        <Card>
          <SectionTitle title="Placeholders" hint="Click a message box, then a placeholder to insert it. Lines whose placeholders are all empty (e.g. no bonus link) are dropped automatically." />
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {PLACEHOLDERS.map(([ph, label]) => (
              <button key={ph} type="button" title={label} disabled={!canEdit} onMouseDown={(e) => e.preventDefault()} onClick={() => insertPlaceholder(ph)}
                style={{ border: `1px solid ${T.line}`, background: '#F7FBFC', borderRadius: 7, padding: '5px 8px', fontSize: 12, fontFamily: 'ui-monospace, Menlo, monospace', color: T.tealDark, cursor: canEdit ? 'pointer' : 'default', minHeight: 30 }}>
                {ph}
              </button>
            ))}
          </div>
        </Card>

        <Card>
          <SectionTitle title="Messages" hint="WhatsApp formatting works: *bold*, _italic_." />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {MESSAGE_FIELDS.map((f) => (
              <Field key={f.key} label={f.label} hint={f.hint} max={f.max || 1000} count={(msgs[f.key] || '').length}>
                {f.single ? (
                  <input style={INPUT} disabled={!canEdit} value={msgs[f.key] || ''} maxLength={f.max}
                    onFocus={(e) => track(e.target, (v) => setMsg(f.key, v.slice(0, f.max)), { message_key: 'greeting' })}
                    onChange={(e) => setMsg(f.key, e.target.value)} />
                ) : (
                  <textarea rows={f.rows} disabled={!canEdit} value={msgs[f.key] || ''} maxLength={1000}
                    style={{ ...INPUT, resize: 'vertical', lineHeight: 1.5 }}
                    onFocus={(e) => track(e.target, (v) => setMsg(f.key, v), { message_key: f.key })}
                    onChange={(e) => setMsg(f.key, e.target.value)} />
                )}
              </Field>
            ))}

            <div>
              <Eyebrow style={{ marginBottom: 8 }}>Question buttons (max 3)</Eyebrow>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {faq.map((q, i) => (
                  <div key={q.id || i} style={{ border: `1px solid ${T.line}`, borderRadius: 10, padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end' }}>
                      <Field label={`Button ${i + 1}`} max={20} count={(q.title || '').length} style={{ flex: 1 }}>
                        <input style={INPUT} disabled={!canEdit} value={q.title || ''} maxLength={20}
                          onFocus={() => setTarget({ message_key: 'greeting' })} onChange={(e) => setFaq(i, { title: e.target.value })} />
                      </Field>
                      {canEdit && <Button size="sm" variant="danger" icon={Trash2} aria-label={`Remove button ${i + 1}`}
                        onClick={() => setMsg('faq', faq.filter((_, j) => j !== i))} />}
                    </div>
                    <Field label="Answer" max={1000} count={(q.answer || '').length}>
                      <textarea rows={3} disabled={!canEdit} value={q.answer || ''} maxLength={1000} style={{ ...INPUT, resize: 'vertical', lineHeight: 1.5 }}
                        onFocus={(e) => track(e.target, (v) => setFaq(i, { answer: v }), null)}
                        onChange={(e) => setFaq(i, { answer: e.target.value })} />
                    </Field>
                  </div>
                ))}
                {canEdit && faq.length < 3 && (
                  <Button size="sm" icon={Plus} style={{ alignSelf: 'flex-start' }}
                    onClick={() => setMsg('faq', [...faq, { id: `faq_${Date.now().toString(36)}`, title: '', answer: '' }])}>Add question button</Button>
                )}
              </div>
            </div>
          </div>
        </Card>

        <Card>
          <SectionTitle title="Follow-up sequence"
            hint="Each step sends once per lead. Replies pause the sequence for an hour. Outside the free 24-hour window a step only goes out as its approved template."
            right={canEdit && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Button size="sm" icon={RotateCcw} onClick={() => setConfirmReset(true)}>Reset to defaults</Button>
              <Button size="sm" variant="primary" icon={Plus} onClick={addStep}>Add step</Button>
            </div>} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {steps.map((s, i) => (
              <StepEditor key={s.key} step={s} mode={funnel.pricing_mode} canEdit={canEdit} selected={target.step_key === s.key}
                approved={approved} allTemplates={allTemplateNames}
                onChange={(patch) => setStep(i, patch)} onRemove={() => { setSteps((p) => p.filter((_, j) => j !== i)); setDirty(true) }}
                onFocusText={(el) => track(el, (v) => setStep(i, { text: v }), { step_key: s.key })}
                onSelect={() => setTarget({ step_key: s.key })} />
            ))}
            {!steps.length && <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>No follow-ups. Leads only get the greeting.</p>}
          </div>
        </Card>
      </div>

      <div style={{ position: isMobile ? 'static' : 'sticky', top: 16 }}>
        <PreviewPanel funnel={funnel} target={target} msgs={msgs} steps={steps} isActive={isActive} />
      </div>

      {dirty && canEdit && (
        <div style={{ position: 'sticky', bottom: 12, gridColumn: '1 / -1', zIndex: 20, background: '#fff', border: `1px solid ${T.line}`, borderRadius: 12,
          boxShadow: '0 6px 24px rgba(10,26,36,.12)', padding: '10px 16px', display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, color: T.soft, marginRight: 'auto' }}>Unsaved changes</span>
          <Button onClick={() => { setDirty(false); setMsgs(funnel.effective_messages || {}); setSteps(funnel.effective_sequence || []) }}>Discard</Button>
          <Button variant="primary" icon={Save} loading={saving} onClick={save}>Save messages</Button>
        </div>
      )}

      <Modal open={confirmReset} onClose={() => setConfirmReset(false)} title="Reset messages and follow-ups?" width={460}
        footer={<><Button onClick={() => setConfirmReset(false)}>Cancel</Button><Button variant="primary" onClick={resetDefaults}>Load defaults</Button></>}>
        <p style={{ margin: 0, fontSize: 13.5 }}>Every message and step goes back to the recommended set for <strong>{funnel.pricing_mode === 'deadline' ? 'fixed-deadline' : 'per-lead window'}</strong> pricing. Nothing is saved until you press Save.</p>
      </Modal>
    </div>
  )
}

function StepEditor({ step, mode, canEdit, selected, approved, allTemplates, onChange, onRemove, onFocusText, onSelect }) {
  const { amount, unit, dir } = splitOffset(step.offset_minutes)
  const anchor = ANCHORS.find((a) => a.value === step.anchor)
  const applicable = anchor?.modes.includes(mode)
  const setTiming = (a, u, d) => onChange({ offset_minutes: Math.round(Number(a || 0) * u) * d })
  const params = step.template_params || []
  const tplApproved = !step.template_name || approved.includes(step.template_name)

  return (
    <div onClick={onSelect} style={{ border: `1px solid ${selected ? T.teal : T.line}`, borderRadius: 12, padding: 14,
      background: step.enabled ? '#fff' : '#FAFBFC', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Toggle checked={step.enabled !== false} disabled={!canEdit} onChange={(v) => onChange({ enabled: v })} />
        <code style={{ fontSize: 12.5, color: T.ink, fontWeight: 600 }}>{step.key}</code>
        {!applicable && <Badge tone="warn" icon={AlertTriangle}>Not used with {mode === 'deadline' ? 'deadline' : 'window'} pricing</Badge>}
        {step.template_name && !tplApproved && <Badge tone="warn" icon={AlertTriangle}>Template not approved yet</Badge>}
        {canEdit && <Button size="sm" variant="ghost" icon={Trash2} style={{ marginLeft: 'auto', color: T.bad }} aria-label={`Delete step ${step.key}`} onClick={onRemove}>Delete</Button>}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 13, color: T.ink }}>
        <span>Send</span>
        <input type="number" min={0} aria-label="Amount" disabled={!canEdit} className="tnum" style={{ ...INPUT, width: 78 }} value={amount}
          onChange={(e) => setTiming(e.target.value, unit, dir)} />
        <select aria-label="Unit" disabled={!canEdit} style={{ ...INPUT, width: 'auto' }} value={unit} onChange={(e) => setTiming(amount, Number(e.target.value), dir)}>
          {UNITS.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
        </select>
        <select aria-label="Before or after" disabled={!canEdit} style={{ ...INPUT, width: 'auto' }} value={dir} onChange={(e) => setTiming(amount, unit, Number(e.target.value))}>
          <option value={1}>after</option><option value={-1}>before</option>
        </select>
        <select aria-label="Anchor" disabled={!canEdit} style={{ ...INPUT, width: 'auto', maxWidth: '100%' }} value={step.anchor} onChange={(e) => onChange({ anchor: e.target.value })}>
          {ANCHORS.map((a) => <option key={a.value} value={a.value}>{a.label}{a.modes.includes(mode) ? '' : ' (other mode)'}</option>)}
        </select>
        <span>to</span>
        <select aria-label="Audience" disabled={!canEdit} style={{ ...INPUT, width: 'auto' }} value={step.audience} onChange={(e) => onChange({ audience: e.target.value })}>
          {AUDIENCE.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
        </select>
      </div>

      <Field label="Message (inside the 24-hour window)" max={1000} count={(step.text || '').length}>
        <textarea rows={3} disabled={!canEdit} value={step.text || ''} maxLength={1000} style={{ ...INPUT, resize: 'vertical', lineHeight: 1.5 }}
          onFocus={(e) => onFocusText(e.target)} onChange={(e) => onChange({ text: e.target.value })} />
      </Field>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
        <Field label="Template (outside the window)" hint="Without one, the step is skipped for leads who haven’t replied in 24 h.">
          <select disabled={!canEdit} style={INPUT} value={step.template_name || ''} onChange={(e) => onChange({ template_name: e.target.value || null })}>
            <option value="">No template</option>
            {step.template_name && !allTemplates.includes(step.template_name) && <option value={step.template_name}>{step.template_name} (not in your templates)</option>}
            {allTemplates.map((n) => <option key={n} value={n}>{n}{approved.includes(n) ? '' : ' (pending)'}</option>)}
          </select>
        </Field>
        {step.template_name && (
          <Field label="Template values {{1}}, {{2}}…" hint="Placeholders work here, e.g. {pay_link}." group>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {params.map((p, i) => (
                <div key={i} style={{ display: 'flex', gap: 6 }}>
                  <input aria-label={`Template value ${i + 1}`} disabled={!canEdit} style={INPUT} value={p}
                    onChange={(e) => onChange({ template_params: params.map((x, j) => (j === i ? e.target.value : x)) })} />
                  {canEdit && <Button size="sm" icon={Trash2} aria-label="Remove value" onClick={() => onChange({ template_params: params.filter((_, j) => j !== i) })} />}
                </div>
              ))}
              {canEdit && params.length < 10 && <Button size="sm" icon={Plus} style={{ alignSelf: 'flex-start' }} onClick={() => onChange({ template_params: [...params, ''] })}>Add value</Button>}
            </div>
          </Field>
        )}
      </div>

      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
        <Toggle checked={!!step.include_pay_button} disabled={!canEdit} onChange={(v) => onChange({ include_pay_button: v })} label="Add the pay button" />
        <Toggle checked={!!step.only_if_early} disabled={!canEdit} onChange={(v) => onChange({ only_if_early: v })} label="Only while their early price is on" />
      </div>
    </div>
  )
}

// ── Preview ────────────────────────────────────────────────────────────────

function PreviewPanel({ funnel, target, msgs, steps, isActive }) {
  const [sample, setSample] = useState({ name: 'Ada Obi', hours_since_first: 0, paid: false })
  const [out, setOut] = useState(null)
  const [err, setErr] = useState(null)
  const timer = useRef(null)

  const run = useCallback(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      try {
        const faq = (msgs.faq || []).filter((q) => q.title && q.answer)
        const messages = Object.fromEntries(SAVE_KEYS.filter((k) => msgs[k] !== undefined && msgs[k] !== '').map((k) => [k, k === 'faq' ? faq : msgs[k]]))
        setOut(await previewMessage(funnel.id, { ...target, messages, sequence: steps, sample: { ...sample, hours_since_first: Number(sample.hours_since_first) } }))
        setErr(null)
      } catch (e) {
        setErr(errorMessage(e, 'Preview unavailable'))
      }
    }, 400)
  }, [funnel.id, target, msgs, steps, sample])

  useEffect(() => { if (isActive) run() }, [isActive, run])
  useEffect(() => () => clearTimeout(timer.current), [])

  const title = target.step_key ? `Step: ${target.step_key}` : (MESSAGE_FIELDS.find((f) => f.key === target.message_key)?.label || 'Greeting')

  return (
    <Card pad={16}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <Smartphone size={16} color={T.muted} aria-hidden="true" />
        <h3 style={{ margin: 0, fontSize: 13.5, fontWeight: 700, color: T.ink, flex: 1, minWidth: 0 }}>Preview · {title}</h3>
      </div>

      <div style={{ background: '#E9E3DA', backgroundImage: 'radial-gradient(rgba(0,0,0,.035) 1px, transparent 1px)', backgroundSize: '12px 12px',
        borderRadius: 14, padding: 12, minHeight: 200 }} aria-live="polite">
        {err ? <Notice tone="warn" icon={Info}>{err}</Notice> : !out ? <span style={{ fontSize: 12.5, color: T.soft }}>Loading…</span> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-start' }}>
            {out.closed && <Badge tone="warn">Registration closed: leads get the closed message instead</Badge>}
            <div style={{ background: '#fff', borderRadius: '2px 10px 10px 10px', padding: '8px 10px 6px', maxWidth: '100%', boxShadow: '0 1px 1px rgba(0,0,0,.08)', minWidth: 120 }}>
              <WaText text={out.text || '(empty)'} />
              <div style={{ fontSize: 10, color: '#8696A0', textAlign: 'right', marginTop: 2 }}>now</div>
            </div>
            {out.button && (
              <div style={{ background: '#fff', borderRadius: 10, padding: '9px 10px', width: '100%', boxSizing: 'border-box', textAlign: 'center', color: '#0B8AD6', fontSize: 13.5, fontWeight: 600, boxShadow: '0 1px 1px rgba(0,0,0,.08)' }}>
                {out.button}
              </div>
            )}
            {out.faq_buttons?.length > 0 && out.faq_buttons.map((b) => (
              <div key={b} style={{ background: '#fff', borderRadius: 10, padding: '8px 10px', width: '100%', boxSizing: 'border-box', textAlign: 'center', color: '#0B8AD6', fontSize: 13, boxShadow: '0 1px 1px rgba(0,0,0,.08)' }}>{b}</div>
            ))}
          </div>
        )}
      </div>

      {out?.template && (
        <Notice tone="info" icon={Info} style={{ marginTop: 10 }}>
          If they haven’t replied in 24 h this sends template <code>{out.template}</code>{out.template_params?.length ? <> with {out.template_params.map((p, i) => <span key={i}><br />{`{{${i + 1}}}`} = {p || '(empty)'}</span>)}</> : null}
        </Notice>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 14 }}>
        <Eyebrow>Sample lead</Eyebrow>
        <input aria-label="Sample name" style={INPUT} value={sample.name} onChange={(e) => setSample((p) => ({ ...p, name: e.target.value }))} />
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12.5, color: T.ink }}>
          <span className="tnum">{sample.hours_since_first} h since their first message</span>
          <input type="range" min={0} max={72} step={1} value={sample.hours_since_first}
            onChange={(e) => setSample((p) => ({ ...p, hours_since_first: Number(e.target.value) }))} />
        </label>
        <Toggle checked={sample.paid} onChange={(v) => setSample((p) => ({ ...p, paid: v }))} label="Has paid" />
        {out && <span className="tnum" style={{ fontSize: 12, color: T.muted }}>Price now: {out.price} ({out.tier || 'closed'})</span>}
      </div>
    </Card>
  )
}

/** WhatsApp-style text: *bold*, _italic_, ~strike~, line breaks, links. Built as React nodes (no innerHTML). */
function WaText({ text }) {
  const lines = String(text).split('\n')
  return (
    <div style={{ fontSize: 13.5, lineHeight: 1.45, color: '#111B21', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
      {lines.map((line, i) => <span key={i}>{renderInline(line)}{i < lines.length - 1 && <br />}</span>)}
    </div>
  )
}
function renderInline(line) {
  const out = []
  const re = /(\*[^*\n]+\*|_[^_\n]+_|~[^~\n]+~|https?:\/\/\S+)/g
  let last = 0
  let m
  let k = 0
  while ((m = re.exec(line))) {
    if (m.index > last) out.push(line.slice(last, m.index))
    const tok = m[0]
    if (tok.startsWith('*')) out.push(<strong key={k++}>{tok.slice(1, -1)}</strong>)
    else if (tok.startsWith('_')) out.push(<em key={k++}>{tok.slice(1, -1)}</em>)
    else if (tok.startsWith('~')) out.push(<s key={k++}>{tok.slice(1, -1)}</s>)
    else out.push(<span key={k++} style={{ color: '#027EB5', textDecoration: 'underline' }}>{tok}</span>)
    last = m.index + tok.length
  }
  if (last < line.length) out.push(line.slice(last))
  return out
}
