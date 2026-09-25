/**
 * frontend/src/modules/funnels/CreateFunnelModal.jsx
 * FUNNEL-1B — "New funnel" form. Creates a DRAFT; messages and follow-ups start
 * from the Option B defaults (editable later in Messages). Going live happens in Setup.
 */
import { useEffect, useState } from 'react'
import { Info } from 'lucide-react'
import { createFunnel, errorMessage } from '../../services/funnels.service'
import { getWhatsAppNumbers } from '../../services/admin.service'
import { Modal, Button, Field, Segmented, Toggle, Notice } from './funnelUi'
import { T, INPUT, fromLocalInput, asList } from './funnelKit'

const EMPTY = {
  name: '', event_title: '', event_starts_at: '', registration_closes_at: '',
  pricing_mode: 'window', window_hours: 24, early_deadline_at: '',
  early_price: 5000, regular_price: 7500, group_on: true, group_size: 3, group_price: 12000,
  whatsapp_number_id: '', ad_codes: 'B1, B3, S2, S4, ST5, ST6, F7, F8',
}

export function PricingExplainer({ mode, windowHours, early, regular }) {
  return (
    <Notice tone="info" icon={Info}>
      {mode === 'window'
        ? <>Each lead gets <strong>their own {windowHours || 24}-hour clock</strong> from their first message. Pay inside it: {early}. After it: {regular}. Matches fliers that say “pay within 24 hrs”.</>
        : <>Everyone pays {early} until <strong>one fixed date and time</strong>, then {regular}. Simpler to explain; fliers must show the date.</>}
    </Notice>
  )
}

export default function CreateFunnelModal({ open, onClose, onCreated }) {
  const [f, setF] = useState(EMPTY)
  const [numbers, setNumbers] = useState([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!open) return
    setF(EMPTY)
    setError(null)
    getWhatsAppNumbers()
      .then((r) => setNumbers(asList(r).filter((n) => n.wa_sales_mode === 'event_funnel')))
      .catch(() => setNumbers([]))
  }, [open])

  const set = (k) => (e) => setF((p) => ({ ...p, [k]: e?.target ? e.target.value : e }))
  const naira = (v) => `₦${Number(v || 0).toLocaleString('en-NG')}`

  const submit = async () => {
    setError(null)
    if (!f.name.trim() || !f.event_title.trim() || !f.event_starts_at || !f.registration_closes_at) {
      setError('Fill in the name, event title, event start and registration close.')
      return
    }
    if (f.pricing_mode === 'deadline' && !f.early_deadline_at) {
      setError('Deadline pricing needs the date the early price ends.')
      return
    }
    const codes = f.ad_codes.split(/[\s,]+/).map((c) => c.trim()).filter(Boolean)
    const payload = {
      name: f.name.trim(), event_title: f.event_title.trim(),
      event_starts_at: fromLocalInput(f.event_starts_at), registration_closes_at: fromLocalInput(f.registration_closes_at),
      pricing_mode: f.pricing_mode, early_price: Number(f.early_price), regular_price: Number(f.regular_price),
      ad_codes: codes.map((code) => ({ code })),
      ...(f.pricing_mode === 'window' ? { window_hours: Number(f.window_hours) } : { early_deadline_at: fromLocalInput(f.early_deadline_at) }),
      ...(f.group_on ? { group_size: Number(f.group_size), group_price: Number(f.group_price) } : {}),
      ...(f.whatsapp_number_id ? { whatsapp_number_id: f.whatsapp_number_id } : {}),
    }
    setSaving(true)
    try {
      onCreated(await createFunnel(payload))
    } catch (e) {
      setError(errorMessage(e, 'Could not create the funnel.'))
    } finally {
      setSaving(false)
    }
  }

  const grid2 = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 14 }

  return (
    <Modal open={open} onClose={onClose} title="New event funnel" width={640}
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" loading={saving} onClick={submit}>Create draft</Button>
      </>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={grid2}>
          <Field label="Funnel name" hint="Only you see this.">
            <input style={INPUT} value={f.name} onChange={set('name')} placeholder="Website class — 10 Oct" maxLength={120} />
          </Field>
          <Field label="Event title" hint="Leads see this in every message.">
            <input style={INPUT} value={f.event_title} onChange={set('event_title')} placeholder="Build a Professional Website with ChatGPT" maxLength={200} />
          </Field>
          <Field label="Event starts (Lagos time)">
            <input type="datetime-local" style={INPUT} value={f.event_starts_at} onChange={set('event_starts_at')} />
          </Field>
          <Field label="Registration closes" hint="No payments after this.">
            <input type="datetime-local" style={INPUT} value={f.registration_closes_at} onChange={set('registration_closes_at')} />
          </Field>
        </div>

        <Field label="How the early price works" group>
          <Segmented ariaLabel="Pricing mode" value={f.pricing_mode} onChange={set('pricing_mode')}
            options={[{ value: 'window', label: 'Per-lead window' }, { value: 'deadline', label: 'Fixed deadline' }]} />
        </Field>
        <PricingExplainer mode={f.pricing_mode} windowHours={f.window_hours} early={naira(f.early_price)} regular={naira(f.regular_price)} />

        <div style={grid2}>
          {f.pricing_mode === 'window' ? (
            <Field label="Window length (hours)">
              <input type="number" min={1} max={168} style={INPUT} value={f.window_hours} onChange={set('window_hours')} />
            </Field>
          ) : (
            <Field label="Early price ends">
              <input type="datetime-local" style={INPUT} value={f.early_deadline_at} onChange={set('early_deadline_at')} />
            </Field>
          )}
          <Field label="Early price (₦)">
            <input type="number" min={1} style={INPUT} value={f.early_price} onChange={set('early_price')} />
          </Field>
          <Field label="Regular price (₦)">
            <input type="number" min={1} style={INPUT} value={f.regular_price} onChange={set('regular_price')} />
          </Field>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <Toggle checked={f.group_on} onChange={set('group_on')} label="Offer a group deal" />
          {f.group_on && (
            <div style={grid2}>
              <Field label="Seats in the group"><input type="number" min={2} max={20} style={INPUT} value={f.group_size} onChange={set('group_size')} /></Field>
              <Field label="Group price (₦)"><input type="number" min={1} style={INPUT} value={f.group_price} onChange={set('group_price')} /></Field>
            </div>
          )}
        </div>

        <div style={grid2}>
          <Field label="WhatsApp number" hint={numbers.length ? 'Only numbers in Event Funnel mode are listed.' : 'None yet — set a number to Event Funnel mode in Admin → WhatsApp Numbers. You can link it later.'}>
            <select style={INPUT} value={f.whatsapp_number_id} onChange={set('whatsapp_number_id')}>
              <option value="">Link later</option>
              {numbers.map((n) => <option key={n.id} value={n.id}>{n.label}</option>)}
            </select>
          </Field>
          <Field label="Ad codes" hint="The code in each ad’s pre-filled message, separated by commas.">
            <input style={INPUT} value={f.ad_codes} onChange={set('ad_codes')} />
          </Field>
        </div>

        {error && <Notice tone="bad">{error}</Notice>}
        <p style={{ margin: 0, fontSize: 12, color: T.muted }}>
          Messages and follow-ups start from the recommended set. You can edit every word in Messages before going live.
        </p>
      </div>
    </Modal>
  )
}
