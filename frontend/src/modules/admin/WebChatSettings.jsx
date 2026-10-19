/**
 * frontend/src/modules/admin/WebChatSettings.jsx
 * WEBCHAT-1/2 — Admin > WhatsApp > Web Chat. Switch the chat on, copy the link for Instagram / QR / your site,
 * write the greeting, the menu answers and the text sent to people who message the WhatsApp number.
 * (The fuller admin screen with funnel and cost numbers is WEBCHAT-5.)
 * Backend: routers/webchat.py (owner / ops manager only).
 */
import { useEffect, useState } from 'react'
import { getWebchatSettings, saveWebchatSettings, applyWebchatTemplate, getWebchatStats } from '../../services/webchat.service'
import { ds } from '../../utils/ds'

const card = { background: '#fff', border: `1px solid ${ds.border}`, borderRadius: ds.radius.lg, padding: 16, marginBottom: 16, boxShadow: ds.cardShadow }
const label = { display: 'block', fontSize: 12, fontWeight: 600, color: ds.dark, margin: '10px 0 4px', fontFamily: ds.fontDm }
const input = { width: '100%', boxSizing: 'border-box', minHeight: 40, padding: '8px 10px', border: `1px solid ${ds.border}`, borderRadius: ds.radius.sm, fontSize: 14, fontFamily: ds.fontDm }
const btn = (primary) => ({ minHeight: 40, padding: '8px 16px', borderRadius: ds.radius.sm, border: primary ? 0 : `1px solid ${ds.teal}`, background: primary ? ds.teal : '#fff', color: primary ? '#fff' : ds.teal, fontWeight: 600, fontSize: 14, cursor: 'pointer', fontFamily: ds.fontDm })

const blankItem = () => ({ id: `item${Date.now().toString(36).slice(-5)}`, label: '', answer: '', keywords: [], link: undefined })

export default function WebChatSettings() {
  const [data, setData] = useState(null)
  const [cfg, setCfg] = useState(null)
  const [stats, setStats] = useState(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const load = async () => {
    try {
      const d = await getWebchatSettings()
      setData(d); setCfg(d.config)
      getWebchatStats().then(setStats).catch(() => {})
    } catch (e) {
      setMsg(e?.response?.data?.detail || 'Only the owner or an operations manager can open this.')
    }
  }
  useEffect(() => { load() }, [])

  if (!cfg) return <div style={{ padding: 20, color: ds.gray, fontFamily: ds.fontDm }}>{msg || 'Loading…'}</div>

  const set = (k, v) => setCfg((c) => ({ ...c, [k]: v }))
  const setItem = (i, patch) => set('menu', cfg.menu.map((m, n) => (n === i ? { ...m, ...patch } : m)))
  const save = async () => {
    setBusy(true); setMsg('')
    try { const c = await saveWebchatSettings(cfg); setCfg(c); setMsg('Saved.') }
    catch (e) { setMsg(e?.response?.data?.detail || 'Could not save. Please try again.') }
    finally { setBusy(false) }
  }
  const template = async () => {
    if (cfg.menu.length && !window.confirm('Replace your current menu with the salon starter menu?')) return
    setBusy(true)
    try { const c = await applyWebchatTemplate('salon'); setCfg(c); setMsg('Starter menu added. Replace the [bracketed] answers with your own before you switch the chat on.') }
    catch { setMsg('Could not add the starter menu.') }
    finally { setBusy(false) }
  }
  const copy = (t) => { try { navigator.clipboard.writeText(t); setMsg('Link copied.') } catch { setMsg(t) } }
  const hasPlaceholder = cfg.menu.some((m) => /\[.*\]/.test(m.answer || ''))

  return (
    <div style={{ maxWidth: 760, fontFamily: ds.fontDm }}>
      <h2 style={{ fontSize: 20, color: ds.dark, margin: '0 0 4px' }}>Web Chat</h2>
      <p style={{ fontSize: 13, color: ds.gray, margin: '0 0 16px' }}>
        Your own chat page. Customers who open it get your menu and answers, then you reply from the Conversations inbox.
        No WhatsApp message fees apply to chats held here.
      </p>

      <div style={card}>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14, fontWeight: 600 }}>
          <input type="checkbox" checked={!!cfg.enabled} onChange={(e) => set('enabled', e.target.checked)} /> Chat page is on
        </label>
        {cfg.enabled && hasPlaceholder && <p style={{ color: ds.red, fontSize: 12 }}>Some answers still contain [brackets]. Replace them before you share the link.</p>}
        <label style={label}>Links to share (each one tags where visitors came from)</label>
        {[['Main link', data.link], ['Instagram bio or story', data.links.instagram], ['QR code', data.links.qr], ['Your website', data.links.site]].map(([n, u]) => (
          <div key={n} style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '4px 0' }}>
            <span style={{ width: 150, fontSize: 12, color: ds.gray }}>{n}</span>
            <input readOnly style={{ ...input, flex: 1 }} value={u} onFocus={(e) => e.target.select()} />
            <button type="button" style={btn(false)} onClick={() => copy(u)}>Copy</button>
          </div>
        ))}
        {stats && <p style={{ fontSize: 12, color: ds.gray, margin: '10px 0 0' }}>
          Last 30 days: {stats.counts.visit || 0} visits, {stats.counts.started || 0} started chatting, {stats.counts.contact || 0} gave contact, {stats.counts.booked || 0} booked, {stats.counts.redirect_sent || 0} WhatsApp redirects.
        </p>}
      </div>

      <div style={card}>
        <label style={label} htmlFor="wc-bn">Business name shown at the top</label>
        <input id="wc-bn" style={input} value={cfg.business_name} maxLength={120} onChange={(e) => set('business_name', e.target.value)} />
        <label style={label} htmlFor="wc-gr">Greeting</label>
        <textarea id="wc-gr" style={{ ...input, minHeight: 60 }} value={cfg.greeting} maxLength={400} onChange={(e) => set('greeting', e.target.value)} />
        <label style={label} htmlFor="wc-col">Colour</label>
        <input id="wc-col" type="color" value={cfg.brand_color} onChange={(e) => set('brand_color', e.target.value)} style={{ width: 60, height: 36 }} />
      </div>

      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <strong style={{ fontSize: 14, color: ds.dark }}>Menu (what visitors can tap)</strong>
          <button type="button" style={btn(false)} onClick={template} disabled={busy}>Use salon starter menu</button>
        </div>
        {cfg.menu.map((m, i) => (
          <div key={m.id} style={{ borderTop: `1px solid ${ds.border}`, marginTop: 12, paddingTop: 8 }}>
            <label style={label} htmlFor={`m-l-${i}`}>Button text</label>
            <input id={`m-l-${i}`} style={input} value={m.label} maxLength={60} onChange={(e) => setItem(i, { label: e.target.value })} />
            <label style={label} htmlFor={`m-t-${i}`}>What it does</label>
            <select id={`m-t-${i}`} style={input} value={m.action || 'answer'}
              onChange={(e) => setItem(i, e.target.value === 'answer' ? { action: undefined } : { action: e.target.value })}>
              <option value="answer">Shows an answer</option>
              <option value="booking">Opens the booking form</option>
              <option value="human">Hands over to your team</option>
            </select>
            {!m.action && (
              <>
                <label style={label} htmlFor={`m-a-${i}`}>Answer</label>
                <textarea id={`m-a-${i}`} style={{ ...input, minHeight: 70 }} value={m.answer || ''} maxLength={1000} onChange={(e) => setItem(i, { answer: e.target.value })} />
                <label style={label} htmlFor={`m-u-${i}`}>Link to show with the answer (optional, starts with https://)</label>
                <input id={`m-u-${i}`} style={input} value={m.link?.url || ''} maxLength={500}
                  onChange={(e) => setItem(i, { link: e.target.value ? { label: m.link?.label || 'See more', url: e.target.value } : undefined })} />
              </>
            )}
            <label style={label} htmlFor={`m-k-${i}`}>Words that should trigger it when typed (comma separated)</label>
            <input id={`m-k-${i}`} style={input} value={(m.keywords || []).join(', ')}
              onChange={(e) => setItem(i, { keywords: e.target.value.split(',').map((k) => k.trim()).filter(Boolean) })} />
            <button type="button" style={{ ...btn(false), marginTop: 8, borderColor: ds.red, color: ds.red }}
              onClick={() => set('menu', cfg.menu.filter((_, n) => n !== i))}>Remove “{m.label || 'this item'}”</button>
          </div>
        ))}
        {cfg.menu.length < 12 && <button type="button" style={{ ...btn(false), marginTop: 12 }} onClick={() => set('menu', [...cfg.menu, blankItem()])}>Add a menu item</button>}
      </div>

      <div style={card}>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14, fontWeight: 600 }}>
          <input type="checkbox" checked={!!cfg.shop_enabled} onChange={(e) => set('shop_enabled', e.target.checked)} /> Let visitors shop in the chat
        </label>
        <p style={{ fontSize: 12, color: ds.gray, margin: '4px 0 0' }}>
          Adds a Shop button with your products, a cart, and a Paystack payment link at checkout. Prices always come from your catalog. Checkout needs your Paystack storefront to be connected; if it is not, the chat hands the order to your team. Shopping itself is free and uses no AI credits. If AI answers are on, it can also suggest products from your catalog.
        </p>
      </div>

      <div style={card}>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14, fontWeight: 600 }}>
          <input type="checkbox" checked={!!cfg.ai_enabled} onChange={(e) => set('ai_enabled', e.target.checked)} /> AI answers typed questions
        </label>
        <p style={{ fontSize: 12, color: ds.gray, margin: '4px 0 0' }}>
          Menu taps and keyword matches are always answered free from your menu. AI only handles other typed questions, only after the visitor has given their contact details, and only from what you have written here. When it cannot answer, it hands the chat to your team. AI replies use your credits.
        </p>
        {cfg.ai_enabled && (
          <>
            <label style={label} htmlFor="wc-aim">AI model</label>
            <select id="wc-aim" style={input} value={cfg.ai_model} onChange={(e) => set('ai_model', e.target.value)}>
              <option value="haiku">Fast and low cost (recommended)</option>
              <option value="sonnet">Smarter, costs about twice as much</option>
            </select>
            <label style={label} htmlFor="wc-ain">Extra guidance for the AI (optional)</label>
            <textarea id="wc-ain" style={{ ...input, minHeight: 70 }} value={cfg.ai_instructions} maxLength={800}
              onChange={(e) => set('ai_instructions', e.target.value)}
              placeholder="e.g. We do not do home visits. Always suggest booking a call for custom quotes." />
            <label style={label} htmlFor="wc-aimt">Most AI replies in one chat (1 to 30)</label>
            <input id="wc-aimt" type="number" min={1} max={30} style={{ ...input, width: 120 }} value={cfg.ai_max_turns}
              onChange={(e) => set('ai_max_turns', Number(e.target.value) || 12)} />
          </>
        )}
      </div>

      <div style={card}>
        <strong style={{ fontSize: 14, color: ds.dark }}>When someone messages your WhatsApp number</strong>
        <p style={{ fontSize: 12, color: ds.gray, margin: '4px 0 0' }}>
          Applies to numbers set to “Web chat redirect” in WA Numbers. They get ONE reply with the chat link; after that nothing is sent automatically and your team is notified here.
        </p>
        <label style={label} htmlFor="wc-rt">Reply text (use {'{name}'} and {'{link}'}; the link is added at the end if you leave it out)</label>
        <textarea id="wc-rt" style={{ ...input, minHeight: 70 }} value={cfg.redirect_text} maxLength={600} onChange={(e) => set('redirect_text', e.target.value)}
          placeholder="Hi {name}! To get your answer fastest, please continue here: {link}" />
        <label style={label} htmlFor="wc-rm">Reply style</label>
        <select id="wc-rm" style={input} value={cfg.redirect_mode} onChange={(e) => set('redirect_mode', e.target.value)}>
          <option value="always">Text and link only</option>
          <option value="menu_first">Text, a list of what the chat offers, and the link</option>
        </select>
      </div>

      <button type="button" style={btn(true)} onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save web chat settings'}</button>
      {msg && <span role="status" style={{ marginLeft: 12, fontSize: 13, color: ds.gray }}>{msg}</span>}
    </div>
  )
}
