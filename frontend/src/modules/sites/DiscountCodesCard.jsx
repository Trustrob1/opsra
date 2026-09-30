/**
 * frontend/src/modules/sites/DiscountCodesCard.jsx
 * SITE-DISCOUNT — create and manage discount codes for site-hosting orders.
 * A code takes a percentage or a fixed naira amount off the WHOLE order total (first orders only).
 */
import { useCallback, useEffect, useState } from 'react'
import { Pencil, Plus, Tag, Trash2 } from 'lucide-react'
import {
  listDiscountCodes, createDiscountCode, updateDiscountCode, deleteDiscountCode, errorMessage,
} from '../../services/sites.service'
import { Card, SectionTitle, Button, Field, Segmented, Toggle, Badge, Notice, Spinner, Empty, Modal } from './sitesUi'
import { T, INPUT, money, dateOnly } from './sitesKit'

const EMPTY = { code: '', kind: 'percent', value: '', expires: '', max_uses: '', one_per_builder: false, note: '', active: true }

// Lagos is UTC+1 all year — the date picker's day ends at 23:59 Lagos time.
const toIso = (d) => (d ? `${d}T23:59:59+01:00` : null)
const toDay = (iso) => (iso ? new Date(new Date(iso).getTime() + 3600000).toISOString().slice(0, 10) : '')

const describe = (c) => (c.kind === 'percent' ? `${Number(c.value)}% off` : `${money(c.value)} off`)

function status(c) {
  if (!c.active) return { tone: 'neutral', text: 'Off' }
  if (c.expires_at && new Date(c.expires_at) <= new Date()) return { tone: 'warn', text: 'Expired' }
  if (c.max_uses != null && c.uses >= c.max_uses) return { tone: 'warn', text: 'Used up' }
  return { tone: 'good', text: 'Active' }
}

export default function DiscountCodesCard({ isActive, canEdit, showToast }) {
  const [codes, setCodes] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [form, setForm] = useState(null)        // null = closed; otherwise the modal's values
  const [editingId, setEditingId] = useState(null)
  const [formError, setFormError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [confirmId, setConfirmId] = useState(null)

  const load = useCallback(async () => {
    setLoadError(null)
    try { setCodes(await listDiscountCodes()) } catch (e) { setLoadError(errorMessage(e, 'Could not load discount codes.')) }
  }, [])

  useEffect(() => { if (isActive) load() }, [isActive, load])

  const openNew = () => { setEditingId(null); setForm({ ...EMPTY }); setFormError(null) }
  const openEdit = (c) => {
    setEditingId(c.id)
    setForm({
      code: c.code, kind: c.kind, value: String(Number(c.value)), expires: toDay(c.expires_at),
      max_uses: c.max_uses == null ? '' : String(c.max_uses), one_per_builder: !!c.one_per_builder,
      note: c.note || '', active: !!c.active,
    })
    setFormError(null)
  }
  const close = () => { if (!saving) setForm(null) }
  const set = (patch) => setForm((f) => ({ ...f, ...patch }))

  async function save() {
    const value = Number(form.value)
    if (!form.code.trim()) { setFormError('Give the code a name, e.g. WELCOME10.'); return }
    if (!form.value || Number.isNaN(value) || value <= 0) { setFormError('Enter how much the code takes off.'); return }
    if (form.kind === 'percent' && value > 100) { setFormError('A percentage can\'t be more than 100.'); return }
    const payload = {
      code: form.code, kind: form.kind, value, note: form.note, active: form.active,
      one_per_builder: form.one_per_builder, expires_at: toIso(form.expires),
      max_uses: form.max_uses === '' ? null : Number(form.max_uses),
    }
    setSaving(true)
    setFormError(null)
    try {
      if (editingId) await updateDiscountCode(editingId, payload)
      else await createDiscountCode(payload)
      showToast(editingId ? 'Code saved' : 'Code created')
      setForm(null)
      await load()
    } catch (e) {
      setFormError(errorMessage(e, 'Could not save this code.'))
    } finally {
      setSaving(false)
    }
  }

  async function flip(c) {
    try {
      await updateDiscountCode(c.id, { active: !c.active })
      showToast(c.active ? 'Code switched off' : 'Code switched on')
      await load()
    } catch (e) { showToast(errorMessage(e, 'Could not update the code.'), 'bad') }
  }

  async function remove(c) {
    try {
      await deleteDiscountCode(c.id)
      showToast(c.uses > 0 ? 'Code switched off (it was already used, so it is kept in your history)' : 'Code removed')
      setConfirmId(null)
      await load()
    } catch (e) { showToast(errorMessage(e, 'Could not remove the code.'), 'bad') }
  }

  return (
    <Card>
      <SectionTitle title="Discount codes"
        hint="A builder types a code at checkout. It takes a percentage or a fixed amount off the whole order total of a first order (renewals aren't discounted). A code never takes an order below ₦100."
        right={canEdit && <Button size="sm" variant="primary" icon={Plus} onClick={openNew}>New code</Button>} />
      {loadError && <Notice tone="bad">{loadError}</Notice>}
      {!codes && !loadError && <Spinner />}
      {codes && codes.length === 0 && (
        <Empty icon={Tag} title="No discount codes yet" text="Create one to give a builder money off their first order."
          action={canEdit && <Button size="sm" icon={Plus} onClick={openNew}>New code</Button>} />
      )}
      {codes && codes.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {codes.map((c) => {
            const st = status(c)
            return (
              <div key={c.id} style={{ display: 'flex', gap: 12, alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap',
                padding: '12px 0', borderTop: `1px solid ${T.line}` }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 14, fontWeight: 700, color: T.ink, letterSpacing: '.4px' }}>{c.code}</span>
                    <Badge tone={st.tone}>{st.text}</Badge>
                    <span style={{ fontSize: 13, color: T.soft }}>{describe(c)}</span>
                  </div>
                  <p style={{ margin: '4px 0 0', fontSize: 12, color: T.muted, lineHeight: 1.5 }}>
                    Used {c.uses}{c.max_uses != null ? ` of ${c.max_uses}` : ''} time{c.uses === 1 && c.max_uses == null ? '' : 's'}
                    {c.discount_given_ngn > 0 ? ` · ${money(c.discount_given_ngn)} given away` : ''}
                    {c.expires_at ? ` · ends ${dateOnly(c.expires_at)}` : ''}
                    {c.one_per_builder ? ' · one use per builder' : ''}
                    {c.note ? ` · ${c.note}` : ''}
                  </p>
                </div>
                {canEdit && (
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <Toggle checked={!!c.active} onChange={() => flip(c)} label="On" />
                    <Button size="sm" icon={Pencil} aria-label={`Edit ${c.code}`} onClick={() => openEdit(c)} />
                    {confirmId === c.id ? (
                      <>
                        <Button size="sm" variant="danger" onClick={() => remove(c)}>{c.uses > 0 ? 'Switch off for good' : 'Yes, remove'}</Button>
                        <Button size="sm" onClick={() => setConfirmId(null)}>Keep</Button>
                      </>
                    ) : (
                      <Button size="sm" icon={Trash2} aria-label={`Remove ${c.code}`} onClick={() => setConfirmId(c.id)} />
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      <Modal open={!!form} onClose={close} title={editingId ? 'Edit discount code' : 'New discount code'}
        footer={(
          <>
            <Button onClick={close} disabled={saving}>Cancel</Button>
            <Button variant="primary" loading={saving} onClick={save}>{editingId ? 'Save code' : 'Create code'}</Button>
          </>
        )}>
        {form && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Field label="Code" hint="Letters and numbers, no spaces. Builders can type it in any case.">
              <input style={INPUT} value={form.code} maxLength={40} placeholder="WELCOME10"
                onChange={(e) => set({ code: e.target.value.toUpperCase().replace(/\s/g, '') })} />
            </Field>
            <Field label="Takes off" group>
              <Segmented value={form.kind} onChange={(kind) => set({ kind })} ariaLabel="Discount type"
                options={[{ value: 'percent', label: 'A percentage' }, { value: 'fixed', label: 'A fixed amount (₦)' }]} />
            </Field>
            <Field label={form.kind === 'percent' ? 'Percent off (%)' : 'Amount off (₦)'}>
              <input style={INPUT} type="number" inputMode="decimal" min="0" step="any" value={form.value}
                onChange={(e) => set({ value: e.target.value })} />
            </Field>
            <Field label="Last day it works" hint="Leave empty for no end date.">
              <input style={INPUT} type="date" value={form.expires} onChange={(e) => set({ expires: e.target.value })} />
            </Field>
            <Field label="Most times it can be used" hint="Leave empty for unlimited. Only paid orders count.">
              <input style={INPUT} type="number" inputMode="numeric" min="1" step="1" value={form.max_uses}
                onChange={(e) => set({ max_uses: e.target.value })} />
            </Field>
            <Toggle checked={form.one_per_builder} onChange={(v) => set({ one_per_builder: v })} label="Each builder can use it once" />
            <Field label="Note (only you see this)">
              <input style={INPUT} value={form.note} maxLength={200} placeholder="e.g. Lagos launch event" onChange={(e) => set({ note: e.target.value })} />
            </Field>
            {editingId && <Toggle checked={form.active} onChange={(v) => set({ active: v })} label="Code is switched on" />}
            {formError && <Notice tone="bad">{formError}</Notice>}
          </div>
        )}
      </Modal>
    </Card>
  )
}
