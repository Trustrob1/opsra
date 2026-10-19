/**
 * WebChatInsights.jsx — WEBCHAT-5
 * Link and QR builder (any source tag) plus the numbers: funnel, by source, chat facts, cost per chat, AI budget.
 */
import { useEffect, useMemo, useState } from 'react'
import { getWebchatAnalytics, getWebchatQr } from '../../services/webchat.service'
import { ds } from '../../utils/ds'

const card = { background: '#fff', border: `1px solid ${ds.border}`, borderRadius: ds.radius.lg, padding: 16, marginBottom: 16, boxShadow: ds.cardShadow }
const input = { boxSizing: 'border-box', minHeight: 40, padding: '8px 10px', border: `1px solid ${ds.border}`, borderRadius: ds.radius.sm, fontSize: 14, fontFamily: ds.fontDm }
const btn = (primary) => ({ minHeight: 40, padding: '8px 16px', borderRadius: ds.radius.sm, border: primary ? 0 : `1px solid ${ds.teal}`, background: primary ? ds.teal : '#fff', color: primary ? '#fff' : ds.teal, fontWeight: 600, fontSize: 14, cursor: 'pointer', fontFamily: ds.fontDm })
const h = { fontSize: 15, fontWeight: 700, color: ds.dark, margin: '0 0 8px', fontFamily: ds.fontDm }
const small = { fontSize: 12, color: ds.gray, margin: '6px 0 0' }

const naira = (kobo) => (kobo == null ? 'n/a' : `₦${(kobo / 100).toLocaleString('en-NG', { maximumFractionDigits: 2 })}`)
const pct = (v) => (v == null ? 'n/a' : `${v}%`)
const cleanTag = (v) => (v || '').toLowerCase().replace(/[^a-z0-9_-]/g, '').slice(0, 30)

function Stat({ label, value, sub }) {
  return (
    <div style={{ flex: '1 1 130px', minWidth: 120, padding: '8px 10px', border: `1px solid ${ds.border}`, borderRadius: ds.radius.sm }}>
      <div style={{ fontSize: 11, color: ds.gray }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: ds.dark }}>{value}</div>
      {sub != null && <div style={{ fontSize: 11, color: ds.gray }}>{sub}</div>}
    </div>
  )
}

export default function WebChatInsights({ baseLink }) {
  const [days, setDays] = useState(30)
  const [an, setAn] = useState(null)
  const [err, setErr] = useState('')
  const [tag, setTag] = useState('flyer')
  const [qr, setQr] = useState('')
  const [qrErr, setQrErr] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let live = true
    setErr('')
    getWebchatAnalytics(days).then((d) => live && setAn(d)).catch(() => live && setErr('Could not load the numbers. Try again in a moment.'))
    return () => { live = false }
  }, [days])

  const t = cleanTag(tag) || 'link'
  const link = useMemo(() => (baseLink ? `${baseLink.split('?')[0]}?s=${t}` : ''), [baseLink, t])

  useEffect(() => {
    let live = true
    setQrErr('')
    const id = setTimeout(() => {
      getWebchatQr(t).then((svg) => live && setQr(svg)).catch(() => live && (setQr(''), setQrErr('QR code did not load.')))
    }, 300)
    return () => { live = false; clearTimeout(id) }
  }, [t])

  const qrUrl = useMemo(() => (qr ? URL.createObjectURL(new Blob([qr], { type: 'image/svg+xml' })) : ''), [qr])
  useEffect(() => () => { if (qrUrl) URL.revokeObjectURL(qrUrl) }, [qrUrl])

  const copy = async () => {
    try { await navigator.clipboard.writeText(link); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch (_e) { /* ignore */ }
  }
  const save = () => {
    if (!qrUrl) return
    const a = document.createElement('a'); a.href = qrUrl; a.download = `chat-qr-${t}.svg`; a.click()
  }

  const f = an?.funnel, c = an?.chats, cost = an?.cost, w = an?.wallet
  const budget = w?.ai_monthly_budget_kobo
  const used = w?.month_ai_spend_kobo || 0
  const usedPct = budget ? Math.min(100, Math.round((100 * used) / budget)) : 0

  return (
    <>
      <div style={card}>
        <p style={h}>Make a tagged link or QR code</p>
        <p style={small}>Pick a name for where you will put it (flyer, shop-door, tiktok, radio). The numbers below then show how many people came from it.</p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 8 }}>
          <input aria-label="Source tag" style={{ ...input, width: 160 }} value={tag} maxLength={30} onChange={(e) => setTag(e.target.value)} />
          <input readOnly aria-label="Tagged link" style={{ ...input, flex: 1, minWidth: 220 }} value={link} onFocus={(e) => e.target.select()} />
          <button type="button" style={btn(false)} onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 12 }}>
          {qrUrl ? <img src={qrUrl} alt={`QR code for ${t}`} style={{ width: 120, height: 120, border: `1px solid ${ds.border}`, borderRadius: ds.radius.sm }} /> : <div style={{ width: 120, height: 120, background: '#f3f5f7', borderRadius: ds.radius.sm }} />}
          <div>
            <button type="button" style={btn(true)} onClick={save} disabled={!qrUrl}>Download QR (SVG)</button>
            <p style={small}>SVG stays sharp at any print size.</p>
            {qrErr && <p style={{ ...small, color: ds.red }}>{qrErr}</p>}
          </div>
        </div>
      </div>

      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <p style={{ ...h, margin: 0 }}>How the chat is doing</p>
          <select aria-label="Period" style={input} value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option>
          </select>
        </div>
        {err && <p style={{ ...small, color: ds.red }}>{err}</p>}
        {!an && !err && <p style={small}>Loading…</p>}
        {an && (
          <>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
              <Stat label="Visits" value={f.totals.visit} />
              <Stat label="Started chatting" value={f.totals.started} sub={`${pct(f.rates.started_of_visit)} of visits`} />
              <Stat label="Gave contact" value={f.totals.contact} sub={`${pct(f.rates.contact_of_started)} of started`} />
              <Stat label="Booked" value={f.totals.booked} sub={`${pct(f.rates.booked_of_contact)} of contacts`} />
            </div>

            <p style={{ ...h, marginTop: 16 }}>By where they came from</p>
            {f.sources.length === 0 ? <p style={small}>No visits yet in this period.</p> : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead><tr style={{ textAlign: 'left', color: ds.gray }}>
                    {['Source', 'Visits', 'Started', 'Contact', 'Booked'].map((x) => <th key={x} style={{ padding: '4px 8px', fontWeight: 600 }}>{x}</th>)}
                  </tr></thead>
                  <tbody>{f.sources.map((s) => (
                    <tr key={s.source} style={{ borderTop: `1px solid ${ds.border}` }}>
                      <td style={{ padding: '6px 8px', fontWeight: 600 }}>{s.source}</td>
                      <td style={{ padding: '6px 8px' }}>{s.visit}</td><td style={{ padding: '6px 8px' }}>{s.started}</td>
                      <td style={{ padding: '6px 8px' }}>{s.contact}</td><td style={{ padding: '6px 8px' }}>{s.booked}</td>
                    </tr>))}</tbody>
                </table>
              </div>
            )}

            <p style={{ ...h, marginTop: 16 }}>What happened in the chats</p>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Stat label="Chats" value={c.chats} />
              <Stat label="Answered by AI" value={c.ai_chats} sub={`${c.ai_turns} replies`} />
              <Stat label="Passed to your team" value={c.handed_to_team} />
              <Stat label="Orders started" value={c.checkouts} />
              <Stat label="Email replies sent" value={c.reply_emails} />
              <Stat label="WhatsApp templates" value={c.whatsapp_templates} />
            </div>

            <p style={{ ...h, marginTop: 16 }}>What the AI costs</p>
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
          </>
        )}
      </div>
    </>
  )
}
