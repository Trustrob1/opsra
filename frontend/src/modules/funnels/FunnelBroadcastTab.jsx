/**
 * frontend/src/modules/funnels/FunnelBroadcastTab.jsx
 * FUNNEL-1B — send an approved template now to a segment (unpaid / paid / everyone,
 * optionally one ad code). Two steps: "Check recipients" (dry run: count + cost vs
 * the template budget) → "Send to N". History with live progress + cancel.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Megaphone, Send, Users, X, AlertTriangle, Info } from 'lucide-react'
import { createBroadcast, listBroadcasts, cancelBroadcast, errorMessage } from '../../services/funnels.service'
import { listTemplates } from '../../services/whatsapp.service'
import { Card, SectionTitle, Button, Field, Segmented, Badge, Notice, Spinner, Empty, Modal } from './funnelUi'
import { T, INPUT, money, num, dateTime, asList } from './funnelKit'

const STATUS = {
  queued: { tone: 'info', label: 'Queued' }, sending: { tone: 'info', label: 'Sending' }, done: { tone: 'good', label: 'Done' },
  cancelled: { tone: 'neutral', label: 'Cancelled' }, capped: { tone: 'warn', label: 'Stopped at budget cap' },
}
const AUD = { unpaid: 'Not paid yet', paid: 'Paid', all: 'Everyone' }

function countVars(body) {
  const m = String(body || '').match(/\{\{\s*(\d+)\s*\}\}/g) || []
  return m.reduce((mx, t) => Math.max(mx, Number(t.replace(/\D/g, ''))), 0)
}

export default function FunnelBroadcastTab({ funnel, isActive, canEdit, showToast, budget, onSent }) {
  const [templates, setTemplates] = useState([])
  const [history, setHistory] = useState(null)
  const [form, setForm] = useState({ template_name: '', params: [], audience: 'unpaid', ad_code: '' })
  const [check, setCheck] = useState(null)
  const [busy, setBusy] = useState(null)
  const [confirm, setConfirm] = useState(false)
  const [error, setError] = useState(null)

  const loadHistory = useCallback(async () => {
    try { setHistory(await listBroadcasts(funnel.id)) } catch { setHistory([]) }
  }, [funnel.id])

  useEffect(() => {
    if (!isActive) return
    loadHistory()
    listTemplates().then((r) => setTemplates(asList(r).filter((t) => t.meta_status === 'approved'))).catch(() => setTemplates([]))
  }, [isActive, loadHistory])

  // Poll while something is still sending (worker drains every 5 minutes).
  const sending = (history || []).some((b) => ['queued', 'sending'].includes(b.status))
  useEffect(() => {
    if (!isActive || !sending) return
    const t = setInterval(loadHistory, 30000)
    return () => clearInterval(t)
  }, [isActive, sending, loadHistory])

  const tpl = useMemo(() => templates.find((t) => t.name === form.template_name), [templates, form.template_name])
  const varCount = countVars(tpl?.body)

  const set = (patch) => { setForm((p) => ({ ...p, ...patch })); setCheck(null); setError(null) }
  const pickTemplate = (name) => {
    const t = templates.find((x) => x.name === name)
    const n = countVars(t?.body)
    set({ template_name: name, params: Array.from({ length: n }, (_, i) => (i === 0 ? '{pay_link}' : '')) })
  }

  const payload = (dry) => ({
    template_name: form.template_name, template_params: form.params, language: tpl?.language || 'en',
    audience: form.audience, ad_code: form.ad_code || null, dry_run: dry,
  })

  const runCheck = async () => {
    setBusy('check')
    setError(null)
    try { setCheck(await createBroadcast(funnel.id, payload(true))) } catch (e) { setError(errorMessage(e)) } finally { setBusy(null) }
  }
  const send = async () => {
    setBusy('send')
    try {
      await createBroadcast(funnel.id, payload(false))
      setConfirm(false)
      setCheck(null)
      showToast('Broadcast queued. Sending starts within 5 minutes.')
      loadHistory()
      onSent?.()
    } catch (e) {
      setConfirm(false)
      setError(errorMessage(e))
    } finally { setBusy(null) }
  }
  const cancel = async (b) => {
    try { await cancelBroadcast(funnel.id, b.id); showToast('Broadcast cancelled'); loadHistory() } catch (e) { showToast(errorMessage(e), 'bad') }
  }

  const codes = (funnel.ad_codes || []).map((c) => c.code)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {canEdit && (
        <Card>
          <SectionTitle title="New broadcast"
            hint="Uses an approved template, so it reaches everyone, even leads who went quiet days ago. Meta charges per message; check the count first." />
          {templates.length === 0 ? (
            <Notice tone="warn" icon={Info}>No approved templates yet. Submit them in WhatsApp Engine → Templates; approval usually takes minutes to a day.</Notice>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14 }}>
                <Field label="Template">
                  <select style={INPUT} value={form.template_name} onChange={(e) => pickTemplate(e.target.value)}>
                    <option value="">Choose an approved template</option>
                    {templates.map((t) => <option key={t.id || t.name} value={t.name}>{t.name}</option>)}
                  </select>
                </Field>
                <Field label="Ad code">
                  <select style={INPUT} value={form.ad_code} onChange={(e) => set({ ad_code: e.target.value })}>
                    <option value="">All codes</option>
                    {codes.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </Field>
              </div>
              <Field label="Send to" group>
                <Segmented ariaLabel="Audience" value={form.audience} onChange={(v) => set({ audience: v })}
                  options={[{ value: 'unpaid', label: 'Not paid yet' }, { value: 'paid', label: 'Paid' }, { value: 'all', label: 'Everyone' }]} />
              </Field>
              {tpl && (
                <div style={{ background: '#F7FBFC', border: `1px solid ${T.line}`, borderRadius: 10, padding: 12 }}>
                  <p style={{ margin: '0 0 8px', fontSize: 12, color: T.muted }}>Template text</p>
                  <p style={{ margin: 0, fontSize: 13, color: T.ink, whiteSpace: 'pre-wrap' }}>{tpl.body}</p>
                </div>
              )}
              {varCount > 0 && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
                  {form.params.map((p, i) => (
                    <Field key={i} label={`{{${i + 1}}}`} hint={i === 0 ? 'e.g. {pay_link}: each lead gets their own link' : 'Placeholders like {name} work'}>
                      <input style={INPUT} value={p} onChange={(e) => set({ params: form.params.map((x, j) => (j === i ? e.target.value : x)) })} />
                    </Field>
                  ))}
                </div>
              )}
              {error && <Notice tone="bad" icon={AlertTriangle}>{error}</Notice>}
              {check && (
                <Notice tone={check.within_budget ? 'info' : 'warn'} icon={Users}>
                  <strong className="tnum">{num(check.recipients)}</strong> {check.recipients === 1 ? 'person' : 'people'} ({AUD[form.audience]}{form.ad_code ? `, ${form.ad_code}` : ''}).
                  {check.estimated_cost != null && <> Estimated cost <strong className="tnum">{money(check.estimated_cost)}</strong>.</>}
                  {check.template_budget?.active && <> Budget left: <span className="tnum">{money(check.template_budget.remaining_amount)}</span>.</>}
                  {!check.within_budget && <> This is over your template budget. Narrow the segment or raise the cap in Setup.</>}
                </Notice>
              )}
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <Button icon={Users} disabled={!form.template_name} loading={busy === 'check'} onClick={runCheck}>Check recipients</Button>
                <Button variant="primary" icon={Send} disabled={!check || !check.recipients || !check.within_budget}
                  onClick={() => setConfirm(true)}>{check?.recipients ? `Send to ${num(check.recipients)}` : 'Send'}</Button>
              </div>
            </div>
          )}
        </Card>
      )}

      <Card pad={0}>
        <div style={{ padding: 18, paddingBottom: 6 }}><SectionTitle title="Sent broadcasts" hint={budget?.active ? `Template budget: ${money(budget.spent)} of ${money(budget.cap)} used.` : null} /></div>
        {history === null ? <Spinner /> : history.length === 0 ? <Empty icon={Megaphone} title="No broadcasts yet" /> : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {history.map((b) => {
              const st = STATUS[b.status] || STATUS.queued
              const pctDone = b.total ? Math.min(100, Math.round(((b.sent + b.failed) / b.total) * 100)) : 0
              return (
                <li key={b.id} style={{ borderTop: `1px solid ${T.line}`, padding: '12px 18px', display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                  <div style={{ flex: '1 1 240px', minWidth: 0 }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <code style={{ fontSize: 12.5, fontWeight: 600 }}>{b.template_name}</code>
                      <Badge tone={st.tone}>{st.label}</Badge>
                    </div>
                    <div className="tnum" style={{ fontSize: 12, color: T.muted, marginTop: 3 }}>
                      {AUD[b.audience]}{b.ad_code ? ` · ${b.ad_code}` : ''} · {dateTime(b.created_at)}
                    </div>
                  </div>
                  <div className="tnum" style={{ fontSize: 12.5, color: T.soft, minWidth: 150 }}>
                    {num(b.sent)} of {num(b.total)} sent{b.failed ? ` · ${num(b.failed)} failed` : ''}
                    <div aria-hidden="true" style={{ height: 5, background: '#EEF4F6', borderRadius: 4, marginTop: 5, overflow: 'hidden' }}>
                      <div style={{ width: `${pctDone}%`, height: '100%', background: T.teal }} />
                    </div>
                  </div>
                  {canEdit && ['queued', 'sending'].includes(b.status) && <Button size="sm" variant="danger" icon={X} onClick={() => cancel(b)}>Cancel</Button>}
                </li>
              )
            })}
          </ul>
        )}
      </Card>

      <Modal open={confirm} onClose={() => setConfirm(false)} title="Send this broadcast?" width={460}
        footer={<><Button onClick={() => setConfirm(false)}>Back</Button><Button variant="primary" icon={Send} loading={busy === 'send'} onClick={send}>Send to {num(check?.recipients)}</Button></>}>
        <p style={{ margin: 0, fontSize: 13.5, color: T.ink }}>
          Template <code>{form.template_name}</code> goes to <strong className="tnum">{num(check?.recipients)}</strong> {AUD[form.audience].toLowerCase()} leads{form.ad_code ? ` from ${form.ad_code}` : ''}
          {check?.estimated_cost != null ? <>, about <strong className="tnum">{money(check.estimated_cost)}</strong></> : null}. It sends in batches of 300 every 5 minutes, outside quiet hours. You can cancel until it finishes.
        </p>
      </Modal>
    </div>
  )
}
