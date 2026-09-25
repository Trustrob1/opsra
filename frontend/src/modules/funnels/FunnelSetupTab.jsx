/**
 * frontend/src/modules/funnels/FunnelSetupTab.jsx
 * FUNNEL-1B — event details, pricing mode (window | deadline), prices + group deal,
 * links, ad codes, WhatsApp number, spend & budget settings, behaviour, go-live
 * checklist, Activate / Close, Duplicate as test funnel.
 */
import { useEffect, useMemo, useState } from 'react'
import {
  Save, Rocket, PauseCircle, Copy, CircleCheck, CircleAlert, Plus, Trash2, AlertTriangle, FlaskConical,
} from 'lucide-react'
import { updateFunnel, duplicateAsTest, errorMessage } from '../../services/funnels.service'
import { getWhatsAppNumbers } from '../../services/admin.service'
import { listTemplates } from '../../services/whatsapp.service'
import { Card, SectionTitle, Button, Field, Segmented, Toggle, Notice, Modal, Badge } from './funnelUi'
import { T, INPUT, toLocalInput, fromLocalInput, money, asList } from './funnelKit'
import { PricingExplainer } from './CreateFunnelModal'

function fromFunnel(f) {
  const s = f.effective_settings || f.settings || {}
  return {
    name: f.name || '', event_title: f.event_title || '',
    event_starts_at: toLocalInput(f.event_starts_at), registration_closes_at: toLocalInput(f.registration_closes_at),
    pricing_mode: f.pricing_mode || 'window', window_hours: f.window_hours ?? 24, early_deadline_at: toLocalInput(f.early_deadline_at),
    early_price: f.early_price ?? '', regular_price: f.regular_price ?? '',
    group_on: !!(f.group_size && f.group_price), group_size: f.group_size ?? 3, group_price: f.group_price ?? '',
    paid_group_link: f.paid_group_link || '', prep_group_link: f.prep_group_link || '', bonus_link: f.bonus_link || '',
    whatsapp_number_id: f.whatsapp_number_id || '',
    ad_codes: (f.ad_codes || []).map((c) => ({ code: c.code, label: c.label || '' })),
    pause_spend_threshold: s.pause_spend_threshold ?? 10000,
    budget_on: !!(s.template_cost_estimate && s.template_budget_cap),
    template_cost_estimate: s.template_cost_estimate ?? '', template_budget_cap: s.template_budget_cap ?? '',
    pause_minutes_after_reply: s.pause_minutes_after_reply ?? 60, respect_quiet_hours: s.respect_quiet_hours ?? true,
    max_auto_per_day_after_window: s.max_auto_per_day_after_window ?? 1, stale_after_minutes: s.stale_after_minutes ?? 360,
    convert_on_paid: !!s.convert_on_paid,
  }
}

function toPayload(v) {
  return {
    name: v.name.trim(), event_title: v.event_title.trim(),
    event_starts_at: fromLocalInput(v.event_starts_at), registration_closes_at: fromLocalInput(v.registration_closes_at),
    pricing_mode: v.pricing_mode, window_hours: Number(v.window_hours),
    early_deadline_at: v.pricing_mode === 'deadline' ? fromLocalInput(v.early_deadline_at) : undefined,
    early_price: Number(v.early_price), regular_price: Number(v.regular_price),
    ...(v.group_on ? { group_size: Number(v.group_size), group_price: Number(v.group_price) } : { group_size: null, group_price: null }),
    paid_group_link: v.paid_group_link.trim() || null, prep_group_link: v.prep_group_link.trim() || null, bonus_link: v.bonus_link.trim() || null,
    whatsapp_number_id: v.whatsapp_number_id || null,
    ad_codes: v.ad_codes.filter((c) => c.code.trim()).map((c) => ({ code: c.code.trim().toUpperCase(), ...(c.label.trim() ? { label: c.label.trim() } : {}) })),
    settings: {
      pause_spend_threshold: Number(v.pause_spend_threshold) || 0,
      template_cost_estimate: v.budget_on && v.template_cost_estimate !== '' ? Number(v.template_cost_estimate) : null,
      template_budget_cap: v.budget_on && v.template_budget_cap !== '' ? Number(v.template_budget_cap) : null,
      pause_minutes_after_reply: Number(v.pause_minutes_after_reply), respect_quiet_hours: v.respect_quiet_hours,
      max_auto_per_day_after_window: Number(v.max_auto_per_day_after_window), stale_after_minutes: Number(v.stale_after_minutes),
      convert_on_paid: v.convert_on_paid,
    },
  }
}

export default function FunnelSetupTab({ funnel, isActive, canEdit, isMobile, showToast, onSaved, onOpenFunnel }) {
  const [v, setV] = useState(() => fromFunnel(funnel))
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [numbers, setNumbers] = useState([])
  const [templates, setTemplates] = useState([])
  const [error, setError] = useState(null)
  const [confirm, setConfirm] = useState(null) // 'active' | 'closed' | 'draft' | 'test'

  useEffect(() => { if (!dirty) setV(fromFunnel(funnel)) }, [funnel, dirty])
  useEffect(() => {
    if (!isActive) return
    getWhatsAppNumbers().then((r) => setNumbers(asList(r))).catch(() => setNumbers([]))
    listTemplates().then((r) => setTemplates(asList(r))).catch(() => setTemplates([]))
  }, [isActive])

  const set = (k) => (e) => { setV((p) => ({ ...p, [k]: e?.target ? (e.target.type === 'checkbox' ? e.target.checked : e.target.value) : e })); setDirty(true) }
  const funnelNumbers = numbers.filter((n) => n.wa_sales_mode === 'event_funnel')
  const linked = numbers.find((n) => n.id === funnel.whatsapp_number_id)

  const checklist = useMemo(() => {
    const approved = new Set(templates.filter((t) => t.meta_status === 'approved').map((t) => t.name))
    const seq = (funnel.effective_sequence || []).filter((s) => s.enabled !== false && s.template_name)
    const missingTpl = [...new Set(seq.map((s) => s.template_name).filter((n) => !approved.has(n)))]
    return [
      { ok: !!linked && linked.wa_sales_mode === 'event_funnel', label: 'WhatsApp number linked and in Event Funnel mode',
        fix: linked ? 'Switch the number to Event Funnel mode in Admin → WhatsApp Numbers.' : 'Pick the number below.' },
      { ok: !!funnel.paid_group_link, label: 'Paid class group link set', fix: 'Buyers get it in the confirmation.' },
      { ok: !!(funnel.ad_codes || []).length, label: 'Ad codes added', fix: 'So you can see which ad sold.' },
      { ok: missingTpl.length === 0, label: 'Templates used by follow-ups are approved',
        fix: missingTpl.length ? `Not approved yet: ${missingTpl.join(', ')}. Those steps are skipped for quiet leads until approved.` : '' },
      { ok: true, label: 'Paystack Storefront connected', fix: 'Check Admin → Integrations. Test one real payment before launch.', info: true },
    ]
  }, [funnel, linked, templates])

  const save = async () => {
    setError(null)
    if (v.pricing_mode === 'deadline' && !v.early_deadline_at) { setError('Deadline pricing needs the date the early price ends.'); return }
    if (v.budget_on && (!v.template_cost_estimate || !v.template_budget_cap)) { setError('For the budget cap, fill in both the cost per message and the cap, or switch the cap off.'); return }
    setSaving(true)
    try {
      await updateFunnel(funnel.id, toPayload(v))
      setDirty(false)
      showToast('Setup saved')
      onSaved?.()
    } catch (e) {
      setError(errorMessage(e, 'Could not save'))
    } finally { setSaving(false) }
  }

  const doStatus = async (status) => {
    try {
      await updateFunnel(funnel.id, { status })
      showToast(status === 'active' ? 'Funnel is live' : status === 'closed' ? 'Funnel closed' : 'Back to draft')
      setConfirm(null)
      onSaved?.()
    } catch (e) {
      setConfirm(null)
      showToast(errorMessage(e), 'bad')
    }
  }

  const doDuplicate = async () => {
    try {
      const copy = await duplicateAsTest(funnel.id)
      setConfirm(null)
      showToast('Test funnel created as a draft')
      onOpenFunnel?.(copy.id)
    } catch (e) {
      setConfirm(null)
      showToast(errorMessage(e), 'bad')
    }
  }

  const grid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 14 }
  const naira = (x) => money(Number(x || 0))
  const ro = !canEdit

  return (
    <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'minmax(0, 1fr) 320px', gap: 20, alignItems: 'start', paddingBottom: 0 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 18, minWidth: 0 }}>
        <Card>
          <SectionTitle title="Event" />
          <div style={grid}>
            <Field label="Funnel name"><input disabled={ro} style={INPUT} value={v.name} onChange={set('name')} maxLength={120} /></Field>
            <Field label="Event title" hint="Shown to leads."><input disabled={ro} style={INPUT} value={v.event_title} onChange={set('event_title')} maxLength={200} /></Field>
            <Field label="Event starts (Lagos time)"><input disabled={ro} type="datetime-local" style={INPUT} value={v.event_starts_at} onChange={set('event_starts_at')} /></Field>
            <Field label="Registration closes"><input disabled={ro} type="datetime-local" style={INPUT} value={v.registration_closes_at} onChange={set('registration_closes_at')} /></Field>
          </div>
        </Card>

        <Card>
          <SectionTitle title="Pricing" />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Field label="How the early price works" group>
              <Segmented ariaLabel="Pricing mode" value={v.pricing_mode} onChange={ro ? () => {} : set('pricing_mode')}
                options={[{ value: 'window', label: 'Per-lead window' }, { value: 'deadline', label: 'Fixed deadline' }]} />
            </Field>
            <PricingExplainer mode={v.pricing_mode} windowHours={v.window_hours} early={naira(v.early_price)} regular={naira(v.regular_price)} />
            {funnel.status === 'active' && v.pricing_mode !== funnel.pricing_mode && (
              <Notice tone="warn" icon={AlertTriangle}>
                Switching while live changes prices from the next click on. Nobody who paid is affected. The follow-ups for the old mode stop applying: check Messages → Reset to defaults after saving.
              </Notice>
            )}
            <div style={grid}>
              {v.pricing_mode === 'window'
                ? <Field label="Window length (hours)"><input disabled={ro} type="number" min={1} max={168} style={INPUT} value={v.window_hours} onChange={set('window_hours')} /></Field>
                : <Field label="Early price ends"><input disabled={ro} type="datetime-local" style={INPUT} value={v.early_deadline_at} onChange={set('early_deadline_at')} /></Field>}
              <Field label="Early price (₦)"><input disabled={ro} type="number" min={1} style={INPUT} value={v.early_price} onChange={set('early_price')} /></Field>
              <Field label="Regular price (₦)"><input disabled={ro} type="number" min={1} style={INPUT} value={v.regular_price} onChange={set('regular_price')} /></Field>
            </div>
            <Toggle checked={v.group_on} disabled={ro} onChange={set('group_on')} label="Group deal" />
            {v.group_on && (
              <div style={grid}>
                <Field label="Seats"><input disabled={ro} type="number" min={2} max={20} style={INPUT} value={v.group_size} onChange={set('group_size')} /></Field>
                <Field label="Group price (₦)"><input disabled={ro} type="number" min={1} style={INPUT} value={v.group_price} onChange={set('group_price')} /></Field>
              </div>
            )}
          </div>
        </Card>

        <Card>
          <SectionTitle title="Links" hint="WhatsApp group invite links and the bonus file. Must start with https://." />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Field label="Paid class group" hint="Sent to buyers in the payment confirmation."><input disabled={ro} style={INPUT} value={v.paid_group_link} onChange={set('paid_group_link')} placeholder="https://chat.whatsapp.com/…" /></Field>
            <Field label="Free prep group" hint="Offered when the early price ends."><input disabled={ro} style={INPUT} value={v.prep_group_link} onChange={set('prep_group_link')} placeholder="https://chat.whatsapp.com/…" /></Field>
            <Field label="Prompt Pack (bonus)"><input disabled={ro} style={INPUT} value={v.bonus_link} onChange={set('bonus_link')} placeholder="https://…" /></Field>
          </div>
        </Card>

        <Card>
          <SectionTitle title="WhatsApp number and ad codes" />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Field label="Funnel number" hint={funnelNumbers.length ? 'One live funnel per number. Replies from Lead Center go out on your organisation’s main number, so make this number the main one too.' : 'No number is in Event Funnel mode yet: Admin → WhatsApp Numbers.'}>
              <select disabled={ro} style={INPUT} value={v.whatsapp_number_id} onChange={set('whatsapp_number_id')}>
                <option value="">Not linked</option>
                {funnelNumbers.map((n) => <option key={n.id} value={n.id}>{n.label}</option>)}
                {linked && linked.wa_sales_mode !== 'event_funnel' && <option value={linked.id}>{linked.label} (not in Event Funnel mode)</option>}
              </select>
            </Field>
            <div>
              <p style={{ margin: '0 0 6px', fontSize: 12.5, fontWeight: 600, color: T.ink }}>Ad codes</p>
              <p style={{ margin: '0 0 10px', fontSize: 11.5, color: T.muted }}>Put the code in each ad’s pre-filled message, e.g. “Hi, I want to join the class (B1)”.</p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {v.ad_codes.map((c, i) => (
                  <div key={i} style={{ display: 'flex', gap: 8 }}>
                    <input aria-label={`Code ${i + 1}`} disabled={ro} style={{ ...INPUT, width: 110, textTransform: 'uppercase' }} maxLength={12} value={c.code}
                      onChange={(e) => { setV((p) => ({ ...p, ad_codes: p.ad_codes.map((x, j) => (j === i ? { ...x, code: e.target.value.replace(/[^A-Za-z0-9]/g, '') } : x)) })); setDirty(true) }} />
                    <input aria-label={`Label for code ${i + 1}`} disabled={ro} style={INPUT} maxLength={100} value={c.label} placeholder="e.g. Business owners, flier 1"
                      onChange={(e) => { setV((p) => ({ ...p, ad_codes: p.ad_codes.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)) })); setDirty(true) }} />
                    {canEdit && <Button icon={Trash2} aria-label={`Remove code ${c.code}`} onClick={() => { setV((p) => ({ ...p, ad_codes: p.ad_codes.filter((_, j) => j !== i) })); setDirty(true) }} />}
                  </div>
                ))}
                {canEdit && v.ad_codes.length < 20 && (
                  <Button size="sm" icon={Plus} style={{ alignSelf: 'flex-start' }} onClick={() => { setV((p) => ({ ...p, ad_codes: [...p.ad_codes, { code: '', label: '' }] })); setDirty(true) }}>Add code</Button>
                )}
              </div>
            </div>
          </div>
        </Card>

        <Card>
          <SectionTitle title="Spend and budget" />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Field label="Pause flag after (₦ spent, no payment)" hint="Overview flags an ad code once it passes this with zero payments.">
              <input disabled={ro} type="number" min={0} style={{ ...INPUT, maxWidth: 220 }} value={v.pause_spend_threshold} onChange={set('pause_spend_threshold')} />
            </Field>
            <Toggle checked={v.budget_on} disabled={ro} onChange={set('budget_on')} label="Cap spending on template messages" />
            {v.budget_on && (
              <>
                <div style={grid}>
                  <Field label="Cost per template message (₦)" hint="Check Meta’s current Nigeria marketing rate with your provider.">
                    <input disabled={ro} type="number" min={0.01} step="0.01" style={INPUT} value={v.template_cost_estimate} onChange={set('template_cost_estimate')} />
                  </Field>
                  <Field label="Budget cap (₦)" hint="Total for this funnel.">
                    <input disabled={ro} type="number" min={1} style={INPUT} value={v.template_budget_cap} onChange={set('template_budget_cap')} />
                  </Field>
                </div>
                <Notice tone="info">When the cap is reached, template reminders are skipped, broadcasts stop, and you get one notification. Free replies inside the 24-hour window keep going.</Notice>
              </>
            )}
          </div>
        </Card>

        <Card>
          <SectionTitle title="Behaviour" />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={grid}>
              <Field label="Pause follow-ups after a reply (minutes)"><input disabled={ro} type="number" min={0} max={1440} style={INPUT} value={v.pause_minutes_after_reply} onChange={set('pause_minutes_after_reply')} /></Field>
              <Field label="Max automatic messages per day after the early price" hint="Per lead."><input disabled={ro} type="number" min={0} max={5} style={INPUT} value={v.max_auto_per_day_after_window} onChange={set('max_auto_per_day_after_window')} /></Field>
              <Field label="Skip a follow-up if it is late by (minutes)"><input disabled={ro} type="number" min={15} max={2880} style={INPUT} value={v.stale_after_minutes} onChange={set('stale_after_minutes')} /></Field>
            </div>
            <Toggle checked={v.respect_quiet_hours} disabled={ro} onChange={set('respect_quiet_hours')} label="Hold follow-ups during your organisation’s quiet hours" />
          </div>
        </Card>
        {error && <Notice tone="bad">{error}</Notice>}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, position: isMobile ? 'static' : 'sticky', top: 16 }}>
        <Card>
          <SectionTitle title="Go-live checklist" />
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
            {checklist.map((c) => (
              <li key={c.label} style={{ display: 'flex', gap: 9 }}>
                {c.info ? <CircleAlert size={17} color={T.muted} aria-hidden="true" style={{ flexShrink: 0, marginTop: 1 }} />
                  : c.ok ? <CircleCheck size={17} color={T.good} aria-hidden="true" style={{ flexShrink: 0, marginTop: 1 }} />
                    : <CircleAlert size={17} color={T.warn} aria-hidden="true" style={{ flexShrink: 0, marginTop: 1 }} />}
                <div>
                  <div style={{ fontSize: 13, color: T.ink }}>{c.label}<span className="sr-only">{c.info ? ' (check manually)' : c.ok ? ' (done)' : ' (to do)'}</span></div>
                  {(!c.ok || c.info) && c.fix && <div style={{ fontSize: 11.5, color: T.muted, marginTop: 2 }}>{c.fix}</div>}
                </div>
              </li>
            ))}
          </ul>
        </Card>

        {canEdit && (
          <Card>
            <SectionTitle title="Status" right={<Badge tone={funnel.status === 'active' ? 'good' : funnel.status === 'closed' ? 'warn' : 'neutral'}>{funnel.status === 'active' ? 'Live' : funnel.status === 'closed' ? 'Closed' : 'Draft'}</Badge>} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {funnel.status !== 'active' && <Button variant="primary" icon={Rocket} disabled={dirty} onClick={() => setConfirm('active')}>Go live</Button>}
              {funnel.status === 'active' && <Button variant="danger" icon={PauseCircle} onClick={() => setConfirm('closed')}>Close funnel</Button>}
              {funnel.status === 'closed' && <Button onClick={() => setConfirm('draft')}>Back to draft</Button>}
              <Button icon={FlaskConical} onClick={() => setConfirm('test')}>Duplicate as test funnel</Button>
              {dirty && <p style={{ margin: 0, fontSize: 11.5, color: T.muted }}>Save your changes before going live.</p>}
            </div>
          </Card>
        )}
      </div>

      {dirty && canEdit && (
        <div style={{ position: 'sticky', bottom: 12, gridColumn: '1 / -1', zIndex: 20, background: '#fff', border: `1px solid ${T.line}`, borderRadius: 12,
          boxShadow: '0 6px 24px rgba(10,26,36,.12)', padding: '10px 16px', display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, color: T.soft, marginRight: 'auto' }}>Unsaved changes</span>
          <Button onClick={() => { setDirty(false); setV(fromFunnel(funnel)); setError(null) }}>Discard</Button>
          <Button variant="primary" icon={Save} loading={saving} onClick={save}>Save setup</Button>
        </div>
      )}

      <Modal open={confirm === 'active'} onClose={() => setConfirm(null)} title="Go live?" width={460}
        footer={<><Button onClick={() => setConfirm(null)}>Cancel</Button><Button variant="primary" icon={Rocket} onClick={() => doStatus('active')}>Go live</Button></>}>
        <p style={{ margin: 0, fontSize: 13.5 }}>From now on, anyone who messages <strong>{linked?.label || 'the funnel number'}</strong> gets the greeting and pay button, and follow-ups start. Only one funnel can be live per number.</p>
      </Modal>
      <Modal open={confirm === 'closed'} onClose={() => setConfirm(null)} title="Close this funnel?" width={460}
        footer={<><Button onClick={() => setConfirm(null)}>Cancel</Button><Button variant="danger" icon={PauseCircle} onClick={() => doStatus('closed')}>Close funnel</Button></>}>
        <p style={{ margin: 0, fontSize: 13.5 }}>Payments stop, follow-ups stop, and new messages get the “registration isn’t open” reply. Paid attendees and all records stay.</p>
      </Modal>
      <Modal open={confirm === 'draft'} onClose={() => setConfirm(null)} title="Move back to draft?" width={440}
        footer={<><Button onClick={() => setConfirm(null)}>Cancel</Button><Button variant="primary" onClick={() => doStatus('draft')}>Back to draft</Button></>}>
        <p style={{ margin: 0, fontSize: 13.5 }}>Nothing is sent while it’s a draft. You can go live again later.</p>
      </Modal>
      <Modal open={confirm === 'test'} onClose={() => setConfirm(null)} title="Create a test funnel?" width={480}
        footer={<><Button onClick={() => setConfirm(null)}>Cancel</Button><Button variant="primary" icon={Copy} onClick={doDuplicate}>Create test funnel</Button></>}>
        <p style={{ margin: '0 0 10px', fontSize: 13.5 }}>A draft copy with a <strong>1-hour</strong> price window and follow-ups squeezed to match (3 hours becomes about 8 minutes, 20 hours about 50). Event reminders are switched off and quiet hours ignored.</p>
        <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>To test: close this funnel (if live), make the test one live, message the number from a second phone, pay with Paystack test keys, then close the test and re-open this one.</p>
      </Modal>
    </div>
  )
}
