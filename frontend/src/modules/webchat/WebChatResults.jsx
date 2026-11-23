/**
 * frontend/src/modules/webchat/WebChatResults.jsx — WEBCHAT-RESULTS-1
 * The Web chat page's Results view (was the "How the chat is doing" card buried in Admin > Web chat). One headline, a funnel strip with the
 * biggest drop marked, sources ranked with bars, a Goals menu (what counts as a win, start counting from now), and the old chat / AI-cost
 * numbers under "More detail". Same data as before (GET /webchat/analytics); nothing new is stored.
 */
import { useEffect, useMemo, useState } from 'react'
import { getWebchatAnalytics, getWebchatSettings, getWebchatProducts, saveWebchatSettings } from '../../services/webchat.service'
import { ds } from '../../utils/ds'
import { biggestDrop, headline, sourceRows, funnelWidths } from './resultsView'

const card = { background: '#fff', border: `1px solid ${ds.border}`, borderRadius: ds.radius.lg, padding: 20, marginBottom: 16, boxShadow: ds.cardShadow }
const input = { boxSizing: 'border-box', minHeight: 40, padding: '8px 10px', border: `1px solid ${ds.border}`, borderRadius: ds.radius.sm, fontSize: 14, fontFamily: ds.fontDm }
const btn = (primary) => ({ minHeight: 40, padding: '8px 16px', borderRadius: ds.radius.sm, border: primary ? 0 : `1px solid ${ds.teal}`, background: primary ? ds.teal : '#fff', color: primary ? '#fff' : ds.teal, fontWeight: 600, fontSize: 14, cursor: 'pointer', fontFamily: ds.fontDm })
const h = { fontSize: 15, fontWeight: 700, color: ds.dark, margin: '0 0 8px', fontFamily: ds.fontDm }
const small = { fontSize: 12, color: ds.gray, margin: '6px 0 0' }

const naira = (kobo) => (kobo == null ? 'n/a' : `₦${(kobo / 100).toLocaleString('en-NG', { maximumFractionDigits: 2 })}`)
const when = (iso) => { try { return new Date(iso).toLocaleDateString('en-NG', { day: 'numeric', month: 'short', year: 'numeric' }) } catch { return '' } }

const GOAL_OPTIONS = [
  ['booking', 'Booking requests'],
  ['order', 'Orders started (shop)'],
  ['paid', 'Orders paid (shop)'],
  ['whatsapp', 'Moved to WhatsApp'],
  ['tap', 'Tapped a link in the chat'],
]

function Stat({ label, value, sub, tone }) {
  return (
    <div style={{ flex: '1 1 130px', minWidth: 120, padding: '10px 12px', borderRadius: ds.radius.sm, background: tone ? '#FFF6E0' : '#F5F7F9' }}>
      <div style={{ fontSize: 12, color: ds.gray }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: ds.dark }}>{value}</div>
      {sub != null && <div style={{ fontSize: 11, color: tone ? '#8A5A00' : ds.gray }}>{sub}</div>}
    </div>
  )
}

export default function WebChatResults() {
  const [days, setDays] = useState(30)
  const [an, setAn] = useState(null)
  const [err, setErr] = useState('')
  const [ads, setAds] = useState([])
  const [products, setProducts] = useState([])
  const [reload, setReload] = useState(0)
  const [goalsOpen, setGoalsOpen] = useState(false)
  const [allCols, setAllCols] = useState(false)
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState('')

  useEffect(() => {
    let live = true
    setErr('')
    getWebchatAnalytics(days).then((d) => live && setAn(d)).catch((e) => live && setErr(e?.response?.status === 403 && typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : 'Could not load the numbers. Try again in a moment.'))
    return () => { live = false }
  }, [days, reload])

  useEffect(() => {
    let live = true
    getWebchatSettings().then((d) => live && setAds(Array.isArray(d?.config?.campaigns) ? d.config.campaigns : [])).catch(() => {})
    getWebchatProducts().then((p) => live && setProducts(p)).catch(() => {})
    return () => { live = false }
  }, [])

  const change = async (changes, done) => {
    setSaving(true); setNote('')
    try { await saveWebchatSettings(changes); setNote(done); setReload((n) => n + 1) } catch { setNote('Could not save. Try again.') } finally { setSaving(false) }
  }
  const toggleGoal = (key) => {
    const cur = an?.goals || []
    const next = cur.includes(key) ? cur.filter((g) => g !== key) : [...cur, key]
    if (next.length === 0) { setNote('Keep at least one.'); return }
    change({ goals: next }, 'Saved.')
  }
  const startFresh = () => {
    if (window.confirm('Start counting from now? Older numbers will be hidden here (nothing is deleted). Use this after you have finished testing.')) change({ stats_from: 'now' }, 'Counting from now.')
  }

  const f = an?.funnel, c = an?.chats, cost = an?.cost, w = an?.wallet
  const drop = useMemo(() => (f ? biggestDrop(f.steps) : null), [f])
  const rows = useMemo(() => (f ? sourceRows(f.sources, ads, products) : []), [f, ads, products])
  const widths = useMemo(() => (f ? funnelWidths(f.steps) : []), [f])
  const top = rows.reduce((m, r) => Math.max(m, r.visit), 0) || 1
  const budget = w?.ai_monthly_budget_kobo
  const used = w?.month_ai_spend_kobo || 0
  const usedPct = budget ? Math.min(100, Math.round((100 * used) / budget)) : 0

  return (
    <div style={{ maxWidth: 980 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        <div style={{ position: 'relative' }}>
          <button type="button" style={btn(false)} aria-expanded={goalsOpen} aria-haspopup="dialog" onClick={() => setGoalsOpen((o) => !o)}>Goals</button>
          {goalsOpen && an && (
            <div role="dialog" aria-label="Goals" style={{ position: 'absolute', right: 0, top: 46, zIndex: 20, width: 300, background: '#fff', border: `1px solid ${ds.border}`, borderRadius: ds.radius.lg, padding: 16, boxShadow: '0 8px 24px rgba(0,0,0,.12)' }}>
              <p style={h}>What counts as a win for you?</p>
              {GOAL_OPTIONS.map(([k, l]) => (
                <label key={k} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14, margin: '6px 0' }}>
                  <input type="checkbox" disabled={saving} checked={an.goals.includes(k)} onChange={() => toggleGoal(k)} /> {l}
                </label>
              ))}
              <p style={small}>{an.goals_auto ? 'Chosen for you from your settings (booking, plus orders and payments when the shop is on). ' : ''}The steps follow what you tick.</p>
              <button type="button" style={{ ...btn(false), marginTop: 10, width: '100%' }} disabled={saving} onClick={startFresh}>Start counting from now</button>
              {note && <p role="status" style={small}>{note}</p>}
            </div>
          )}
        </div>
        <select aria-label="Period" style={input} value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option>
        </select>
      </div>

      {err && <p style={{ ...small, color: ds.red }}>{err}</p>}
      {!an && !err && <p style={small}>Loading…</p>}
      {an && (
        <>
          <div style={card}>
            <p style={{ fontSize: 20, fontWeight: 700, color: ds.dark, margin: '0 0 2px', fontFamily: ds.fontDm }}>{headline(f.steps)}</p>
            <p style={{ ...small, margin: '0 0 14px' }}>
              {an.counting_from ? `Counting from ${when(an.counting_from)}. ` : ''}{drop ? `Biggest drop: ${drop.from.toLowerCase()} to ${drop.to.toLowerCase()} (${drop.people} of ${drop.of} did not go on).` : ''}
            </p>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {f.steps.map((s) => (
                <Stat key={s.key} label={s.label} value={s.count}
                  sub={s.rate == null ? undefined : `${s.rate}% of ${s.of}`} tone={!!drop && drop.to === s.label} />
              ))}
              {f.goals.includes('paid') && <Stat label="Paid in" value={naira(f.revenue_kobo)} />}
            </div>
            <div aria-hidden="true" style={{ display: 'flex', height: 8, gap: 3, marginTop: 10 }}>
              {widths.map((x, i) => <div key={i} style={{ flex: x.flex, background: ds.teal, opacity: x.opacity, borderRadius: 4 }} />)}
            </div>
          </div>

          <div style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <p style={h}>Where visitors came from</p>
              <span style={{ fontSize: 12, color: ds.gray }}>Sorted by visits</span>
            </div>
            {rows.length === 0 ? <p style={small}>No visits yet in this period.</p> : (
              <div style={{ display: 'grid', gap: 12, marginTop: 4 }}>
                {rows.map((r) => (
                  <div key={r.source} style={{ display: 'grid', gridTemplateColumns: 'minmax(120px, 190px) minmax(0, 1fr) minmax(110px, 150px)', gap: 12, alignItems: 'center' }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 14, fontWeight: 600, color: ds.dark, overflowWrap: 'anywhere' }}>{r.name}</div>
                      <div style={{ fontSize: 12, color: ds.gray }}>{r.kind}</div>
                    </div>
                    <div style={{ height: 10, background: '#EEF1F4', borderRadius: 5 }}>
                      <div style={{ width: `${Math.max(r.visit ? 4 : 0, Math.round((100 * r.visit) / top))}%`, height: 10, background: ds.teal, borderRadius: 5 }} />
                    </div>
                    <div style={{ fontSize: 13, textAlign: 'right' }}>{r.visit} {r.visit === 1 ? 'visit' : 'visits'} · {r.orders} {r.orders === 1 ? 'order' : 'orders'}</div>
                  </div>
                ))}
              </div>
            )}
            {rows.length > 0 && (
              <>
                <button type="button" onClick={() => setAllCols((v) => !v)} aria-expanded={allCols}
                  style={{ border: 0, background: 'none', color: ds.teal, fontWeight: 600, fontSize: 13, cursor: 'pointer', padding: '12px 0 0', fontFamily: ds.fontDm }}>
                  {allCols ? 'Hide' : 'Show'} all columns
                </button>
                {allCols && (
                  <div style={{ overflowX: 'auto', marginTop: 8 }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                      <thead><tr style={{ textAlign: 'left', color: ds.gray }}>
                        {['Source', 'Link opens', 'Visits', 'Started', 'Contact', ...f.steps.slice(3).map((s) => s.label), ...(f.goals.includes('paid') ? ['Paid in'] : [])].map((x) => <th key={x} style={{ padding: '4px 8px', fontWeight: 600 }}>{x}</th>)}
                      </tr></thead>
                      <tbody>{rows.map((r) => (
                        <tr key={r.source} style={{ borderTop: `1px solid ${ds.border}` }}>
                          <td style={{ padding: '6px 8px', fontWeight: 600 }}>{r.name}</td>
                          <td style={{ padding: '6px 8px' }}>{r.catalog_visit}</td><td style={{ padding: '6px 8px' }}>{r.visit}</td>
                          <td style={{ padding: '6px 8px' }}>{r.started}</td><td style={{ padding: '6px 8px' }}>{r.contact}</td>
                          {f.steps.slice(3).map((s) => <td key={s.key} style={{ padding: '6px 8px' }}>{r.goalCounts[s.key] || 0}</td>)}
                          {f.goals.includes('paid') && <td style={{ padding: '6px 8px' }}>{naira(r.revenue_kobo)}</td>}
                        </tr>))}</tbody>
                    </table>
                    <p style={small}>Link opens counts each time a tagged store or product link is opened (once per visitor per session). Visits counts people who opened the chat.</p>
                  </div>
                )}
              </>
            )}
          </div>

          <div style={card}>
            <p style={h}>More detail</p>
            <p style={{ ...small, margin: '0 0 6px' }}>What happened in the chats</p>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Stat label="Chats" value={c.chats} />
              <Stat label="Answered by AI" value={c.ai_chats} sub={`${c.ai_turns} replies`} />
              <Stat label="Passed to your team" value={c.handed_to_team} />
              <Stat label="Orders started" value={c.checkouts} />
              <Stat label="Email replies sent" value={c.reply_emails} />
              <Stat label="WhatsApp templates" value={c.whatsapp_templates} />
            </div>
            <p style={{ ...small, margin: '14px 0 6px' }}>What the AI costs</p>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Stat label="Total AI cost" value={naira(cost.cost_kobo)} sub={`${cost.calls} AI calls`} />
              <Stat label="Per chat" value={naira(cost.per_chat_kobo)} />
              <Stat label="Per chat that used AI" value={naira(cost.per_ai_chat_kobo)} />
              <Stat label="Per contact collected" value={naira(cost.per_contact_kobo)} />
            </div>
            {w.metering_enabled ? (
              <div style={{ marginTop: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                  <span>AI this month: {naira(used)}{budget ? ` of ${naira(budget)}` : ' (no monthly limit set)'}</span>
                  <span>Credit balance: {naira(w.balance_kobo)}</span>
                </div>
                {budget ? (
                  <div style={{ height: 10, background: '#eef1f4', borderRadius: 6, marginTop: 4 }} role="progressbar" aria-valuenow={usedPct} aria-valuemin={0} aria-valuemax={100}>
                    <div style={{ width: `${usedPct}%`, height: '100%', borderRadius: 6, background: usedPct >= 100 ? ds.red : usedPct >= 80 ? '#E0A100' : ds.teal }} />
                  </div>
                ) : null}
                {w.ai_level !== 'normal' && <p style={{ ...small, color: ds.red }}>{w.ai_level === 'menu_only' ? 'The chat is answering from the menu only because credits or the monthly limit ran out.' : 'The chat is using a cheaper AI model because you are near your monthly limit.'} Add credits on the Credits page.</p>}
              </div>
            ) : <p style={small}>Credit billing is not switched on for your account yet, so nothing is being charged.</p>}
            {an.notes.map((n) => <p key={n} style={small}>{n}</p>)}
          </div>
        </>
      )}
    </div>
  )
}
