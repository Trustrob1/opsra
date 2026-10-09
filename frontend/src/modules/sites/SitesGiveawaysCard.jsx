/**
 * frontend/src/modules/sites/SitesGiveawaysCard.jsx
 * GIVEAWAY-1 — staff: create a group giveaway for a partner (group owner), watch the slot counter, copy the link,
 * close or reopen it, and see who won which slot. Shown inside the Partners tab.
 */
import { Fragment, useCallback, useEffect, useState } from 'react'
import { Gift, Plus } from 'lucide-react'
import { listGiveaways, createGiveaway, closeGiveaway, reopenGiveaway, listGiveawayEntries, voidGiveawaySlot, resendGiveawayLink, errorMessage } from '../../services/sites.service'
import { Card, Button, Badge, Notice, Spinner, Empty } from './sitesUi'
import GiveawayFlier from './GiveawayFlier'
import { T, INPUT } from './sitesKit'

const Th = ({ children }) => <th style={{ textAlign: 'left', padding: '10px 14px', fontSize: 11.5, color: T.muted, fontWeight: 600 }}>{children}</th>
const Td = ({ children, ...r }) => <td style={{ padding: '10px 14px', verticalAlign: 'middle' }} {...r}>{children}</td>

export default function SitesGiveawaysCard({ isActive, canEdit, partners, showToast }) {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ partner_id: '', title: 'Free Website Giveaway', total_slots: 5, fee_ngn: 24500, renewal_ngn: 25000, pay_by_days: 3, full_price_ngn: 65000, full_price_days: 4, campaign_name: '', ends_at: '' })
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(null)       // giveaway id whose winners are shown
  const [winners, setWinners] = useState([])
  const [flier, setFlier] = useState(null)       // the giveaway whose flier is open

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try { setRows(await listGiveaways() || []) } catch (e) { setError(errorMessage(e, 'Could not load giveaways.')) } finally { setLoading(false) }
  }, [])
  useEffect(() => { if (isActive) load() }, [isActive, load])

  async function create() {
    setBusy(true)
    try {
      await createGiveaway({ partner_id: form.partner_id, title: form.title.trim(), total_slots: Number(form.total_slots),
        fee_ngn: Number(form.fee_ngn) || undefined, renewal_ngn: Number(form.renewal_ngn) || undefined, pay_by_days: Number(form.pay_by_days) || undefined,
        full_price_ngn: Number(form.full_price_ngn) || undefined, full_price_days: Number(form.full_price_days) || undefined,
        campaign_name: form.campaign_name.trim() || undefined, ends_at: form.ends_at ? new Date(form.ends_at).toISOString() : undefined })
      showToast('Giveaway created'); setAdding(false); await load()
    } catch (e) { showToast(errorMessage(e, 'Could not create the giveaway.'), 'bad') } finally { setBusy(false) }
  }
  async function toggle(g) {
    try { await (g.status === 'active' ? closeGiveaway(g.id) : reopenGiveaway(g.id)); showToast(g.status === 'active' ? 'Giveaway closed' : 'Giveaway reopened'); await load() }
    catch (e) { showToast(errorMessage(e, 'That did not work.'), 'bad') }
  }
  async function resend(g, w) {
    try {
      const r = await resendGiveawayLink(g.id, w.position)
      showToast(r?.emailed ? `New link sent to ${r.email}` : 'New link created. The email did not go, so check the WhatsApp message', r?.emailed ? undefined : 'bad')
    } catch (e) { showToast(errorMessage(e, 'Could not send the link.'), 'bad') }
  }
  async function voidSlot(g, w) {
    if (!window.confirm(`Void slot #${w.position} (${w.business_name || w.contact_name || 'winner'})? Their private link stops working and the slot opens for the next member.`)) return
    try { await voidGiveawaySlot(g.id, w.position); showToast('Slot voided'); setWinners(await listGiveawayEntries(g.id) || []); await load() }
    catch (e) { showToast(errorMessage(e, 'Could not void that slot.'), 'bad') }
  }
  async function showWinners(g) {
    if (open === g.id) { setOpen(null); return }
    try { setWinners(await listGiveawayEntries(g.id) || []); setOpen(g.id) } catch (e) { showToast(errorMessage(e, 'Could not load winners.'), 'bad') }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, fontSize: 14, color: T.ink }}>Giveaways ({rows.length})</h3>
        {canEdit && <Button variant="primary" icon={Plus} onClick={() => setAdding((v) => !v)} disabled={partners.length === 0}>New giveaway</Button>}
      </div>
      {partners.length === 0 && <Notice tone="info">Approve a partner first. A giveaway belongs to a group owner.</Notice>}
      {adding && (
        <Card>
          <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', alignItems: 'end' }}>
            <label style={{ fontSize: 12.5, color: T.muted }}>Group owner
              <select style={{ ...INPUT, marginTop: 4 }} value={form.partner_id} onChange={(e) => setForm({ ...form, partner_id: e.target.value })}>
                <option value="">Choose…</option>
                {partners.filter((p) => p.status === 'active').map((p) => <option key={p.id} value={p.id}>{p.agency_name || p.full_name}</option>)}
              </select></label>
            <label style={{ fontSize: 12.5, color: T.muted }}>Title
              <input style={{ ...INPUT, marginTop: 4 }} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
            <label style={{ fontSize: 12.5, color: T.muted }}>Free slots
              <input style={{ ...INPUT, marginTop: 4 }} type="number" min="1" max="100" value={form.total_slots} onChange={(e) => setForm({ ...form, total_slots: e.target.value })} /></label>
            <label style={{ fontSize: 12.5, color: T.muted }}>Domain + hosting fee (₦)
              <input style={{ ...INPUT, marginTop: 4 }} type="number" min="1000" value={form.fee_ngn} onChange={(e) => setForm({ ...form, fee_ngn: e.target.value })} /></label>
            <label style={{ fontSize: 12.5, color: T.muted }}>Yearly renewal (₦)
              <input style={{ ...INPUT, marginTop: 4 }} type="number" min="1000" value={form.renewal_ngn} onChange={(e) => setForm({ ...form, renewal_ngn: e.target.value })} /></label>
            <label style={{ fontSize: 12.5, color: T.muted }}>Campaign name (on the flier and page)
              <input style={{ ...INPUT, marginTop: 4 }} maxLength={60} placeholder="e.g. Lagos Hustlers Free Website Week" value={form.campaign_name} onChange={(e) => setForm({ ...form, campaign_name: e.target.value })} /></label>
            <label style={{ fontSize: 12.5, color: T.muted }}>Closes on (optional)
              <input style={{ ...INPUT, marginTop: 4 }} type="datetime-local" value={form.ends_at} onChange={(e) => setForm({ ...form, ends_at: e.target.value })} /></label>
            <label style={{ fontSize: 12.5, color: T.muted }}>Days to pay after preview
              <input style={{ ...INPUT, marginTop: 4 }} type="number" min="1" max="30" value={form.pay_by_days} onChange={(e) => setForm({ ...form, pay_by_days: e.target.value })} /></label>
            <label style={{ fontSize: 12.5, color: T.muted }}>Normal rate after that (₦)
              <input style={{ ...INPUT, marginTop: 4 }} type="number" min="1000" value={form.full_price_ngn} onChange={(e) => setForm({ ...form, full_price_ngn: e.target.value })} /></label>
            <label style={{ fontSize: 12.5, color: T.muted }}>Days at the normal rate before takedown
              <input style={{ ...INPUT, marginTop: 4 }} type="number" min="1" max="30" value={form.full_price_days} onChange={(e) => setForm({ ...form, full_price_days: e.target.value })} /></label>
            <Button variant="primary" loading={busy} disabled={!form.partner_id || form.title.trim().length < 3} onClick={create}>Create giveaway</Button>
          </div>
        </Card>
      )}
      {error && <Notice tone="bad">{error}</Notice>}
      {loading ? <Spinner /> : rows.length === 0 ? (
        <Card><Empty icon={Gift} title="No giveaways yet" text="Create one for a group owner and share its link in their group." /></Card>
      ) : (
        <Card pad={0}><div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, minWidth: 700 }}>
            <thead><tr>{['Giveaway', 'Group owner', 'Slots', 'Status', ''].map((h) => <Th key={h}>{h}</Th>)}</tr></thead>
            <tbody>{rows.map((g) => (
              <Fragment key={g.id}>
                <tr style={{ borderTop: `1px solid ${T.line}` }}>
                  <Td>{g.campaign_name ? <><strong>{g.campaign_name}</strong><div style={{ fontSize: 11.5, color: T.muted }}>{g.title}</div></> : g.title}{g.ends_at && <div style={{ fontSize: 11.5, color: T.muted }}>Closes {new Date(g.ends_at).toLocaleString('en-NG', { dateStyle: 'medium', timeStyle: 'short' })}</div>}</Td><Td>{g.owner_name || '—'}</Td>
                  <Td><strong>{g.taken}</strong> / {g.total_slots} taken · {g.left} left<div style={{ fontSize: 11.5, color: T.muted }}>Fee ₦{Number(g.fee_ngn || 24500).toLocaleString()} · renewal ₦{Number(g.renewal_ngn || 25000).toLocaleString()} · pay within {g.pay_by_days || 3} days · then ₦{Number(g.full_price_ngn || 65000).toLocaleString()} for {g.full_price_days || 4} days, then taken down</div></Td>
                  <Td><Badge tone={g.status === 'active' && g.left > 0 ? 'good' : 'neutral'}>{g.status !== 'active' ? 'Closed' : g.left === 0 ? 'Full' : 'Open'}</Badge></Td>
                  <Td><div style={{ display: 'flex', gap: 4 }}>
                    <Button size="sm" variant="ghost" onClick={async () => { try { await navigator.clipboard.writeText(g.link_url); showToast('Link copied') } catch (_) { showToast('Could not copy', 'bad') } }}>Copy link</Button>
                    <Button size="sm" variant="ghost" onClick={() => setFlier(g)}>Flier</Button>
                    <Button size="sm" variant="ghost" onClick={() => showWinners(g)}>{open === g.id ? 'Hide winners' : 'Winners'}</Button>
                    {canEdit && <Button size="sm" variant="ghost" onClick={() => toggle(g)}>{g.status === 'active' ? 'Close' : 'Reopen'}</Button>}
                  </div></Td>
                </tr>
                {open === g.id && (
                  <tr><td colSpan={5} style={{ padding: '4px 14px 14px', background: T.card }}>
                    {winners.length === 0 ? <span style={{ fontSize: 12.5, color: T.muted }}>No winners yet.</span> : winners.map((w) => (
                      <div key={w.position || w.id || w.contact_phone} style={{ fontSize: 13, padding: '4px 0', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                        <span>{w.position ? `#${w.position}` : 'Lapsed'} · {w.business_name || '(site not created)'} · {w.site_status || '—'} · {w.paid ? 'paid' : w.state === 'lapsed' ? `slot given back · normal rate${w.takedown_at ? `, taken down ${new Date(w.takedown_at).toLocaleDateString('en-NG', { day: 'numeric', month: 'short' })}` : ''}` : `not paid${w.pay_by ? ` (pay by ${new Date(w.pay_by).toLocaleDateString('en-NG', { day: 'numeric', month: 'short' })})` : ''}`} · {w.contact_name || '—'} {w.contact_phone || ''} {w.contact_email || ''}</span>
                        {canEdit && w.position && <Button size="sm" variant="ghost" onClick={() => resend(g, w)}>Resend link</Button>}
                        {canEdit && w.position && !w.paid && <Button size="sm" variant="ghost" onClick={() => voidSlot(g, w)}>Void slot</Button>}
                      </div>
                    ))}
                  </td></tr>
                )}
              </Fragment>
            ))}</tbody>
          </table></div></Card>
      )}
      {flier && <GiveawayFlier giveaway={flier} onClose={() => setFlier(null)} showToast={showToast} />}
    </div>
  )
}
