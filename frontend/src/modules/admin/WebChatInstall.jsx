/**
 * frontend/src/modules/admin/WebChatInstall.jsx
 * WEBCHAT-EMBED-2 — put the chat on a website without writing code, or share it where there is no website.
 *   1. a step-by-step guide per website platform, with the one line of code ready to copy
 *   2. "Send to my web person": emails the code and instructions
 *   3. "Check installation": which websites have shown the bubble (the bubble reports itself when a visitor loads it)
 *   4. no website: ready-made links for Instagram, Facebook, Google, WhatsApp status, email and SMS
 * Advanced: websites allowed to show the bubble (empty = any) and the bubble's corner.
 */
import { useState } from 'react'
import { getWebchatEmbedSeen, sendWebchatEmbedEmail } from '../../services/webchat.service'
import { ds } from '../../utils/ds'

const card = { background: '#fff', border: `1px solid ${ds.border}`, borderRadius: ds.radius.lg, padding: 16, marginBottom: 16, boxShadow: ds.cardShadow }
const label = { display: 'block', fontSize: 12, fontWeight: 600, color: ds.dark, margin: '10px 0 4px', fontFamily: ds.fontDm }
const input = { width: '100%', boxSizing: 'border-box', minHeight: 40, padding: '8px 10px', border: `1px solid ${ds.border}`, borderRadius: ds.radius.sm, fontSize: 14, fontFamily: ds.fontDm }
const btn = (primary) => ({ minHeight: 40, padding: '8px 16px', borderRadius: ds.radius.sm, border: primary ? 0 : `1px solid ${ds.teal}`, background: primary ? ds.teal : '#fff', color: primary ? '#fff' : ds.teal, fontWeight: 600, fontSize: 14, cursor: 'pointer', fontFamily: ds.fontDm })
const small = { fontSize: 12, color: ds.gray, margin: '4px 0 8px', lineHeight: 1.5 }

// Menu names change now and then; the last line of each guide says what to look for if they have moved.
const PLATFORMS = [
  { id: 'wordpress', name: 'WordPress', steps: [
    'In WordPress, go to Plugins, Add New, and install the free plugin called "WPCode" (also named Insert Headers and Footers).',
    'Open Code Snippets, then Header & Footer.',
    'Paste the code into the Footer box and press Save Changes.',
    'Open your website in a new tab. The chat bubble appears in the corner.'] },
  { id: 'wix', name: 'Wix', steps: [
    'In your Wix dashboard, go to Settings, then Custom Code (under Advanced).',
    'Press Add Custom Code and paste the code.',
    'Choose "All pages" and "Body - end", then press Apply.',
    'Publish your site. Custom code needs a Wix plan with a connected domain.'] },
  { id: 'shopify', name: 'Shopify', steps: [
    'In Shopify, go to Online Store, Themes, then the three dots next to your theme, then Edit code.',
    'Open the file layout/theme.liquid.',
    'Paste the code just above the closing </body> line and press Save.',
    'Open your shop. The chat bubble appears in the corner.'] },
  { id: 'squarespace', name: 'Squarespace', steps: [
    'In Squarespace, go to Settings, Developer Tools, then Code Injection.',
    'Paste the code into the Footer box and press Save.',
    'Code Injection needs a Business plan or higher.'] },
  { id: 'webflow', name: 'Webflow', steps: [
    'In Webflow, open Site settings, then Custom code.',
    'Paste the code into "Footer code" and press Save.',
    'Press Publish. The bubble only shows on the published site.'] },
  { id: 'gtm', name: 'Google Tag Manager', steps: [
    'In Tag Manager, create a new Tag and choose "Custom HTML".',
    'Paste the code, set the trigger to "All Pages", and save.',
    'Press Submit, then Publish.'] },
  { id: 'other', name: 'Other / my developer', steps: [
    'Paste the code on every page, just above the closing </body> tag.',
    'No website builder, or not sure? Use "Send to my web person" below and they will know what to do.'] },
]

const CHANNELS = [
  ['instagram', 'Instagram bio or story', 'Put it in your bio link or a story link sticker.'],
  ['facebook', 'Facebook page or post', 'Use it as your page button link or in posts.'],
  ['google', 'Google Business Profile', 'Add it as the website or appointment link.'],
  ['whatsapp_status', 'WhatsApp status or channel', 'Paste it in your status or broadcast text.'],
  ['email', 'Email signature', 'Add "Chat with us: link" under your name.'],
  ['sms', 'SMS or flyers', 'Short and tagged, so you see which one brought people.'],
]

function ago(iso) {
  const m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000))
  if (m < 2) return 'just now'
  if (m < 60) return `${m} minutes ago`
  if (m < 60 * 24) return `${Math.round(m / 60)} hours ago`
  return `${Math.round(m / 1440)} days ago`
}

export default function WebChatInstall({ data, cfg, set, setMsg }) {
  const [platform, setPlatform] = useState('wordpress')
  const [seen, setSeen] = useState(data.embed?.seen || [])
  const [checked, setChecked] = useState(false)
  const [mail, setMail] = useState({ to: '', note: '' })
  const [busy, setBusy] = useState(false)
  const tag = data.embed?.tag || ''
  const guide = PLATFORMS.find((p) => p.id === platform)
  const copy = (t, what) => { try { navigator.clipboard.writeText(t); setMsg(`${what} copied.`) } catch { setMsg(t) } }

  const check = async () => {
    setBusy(true)
    try { setSeen(await getWebchatEmbedSeen()); setChecked(true) } catch { setMsg('Could not check right now. Try again in a moment.') } finally { setBusy(false) }
  }
  const send = async (e) => {
    e.preventDefault()
    setBusy(true)
    try { await sendWebchatEmbedEmail(mail.to, mail.note); setMsg(`Instructions sent to ${mail.to}.`); setMail({ to: '', note: '' }) }
    catch (err) { setMsg(err?.response?.data?.detail || 'Could not send the email.') } finally { setBusy(false) }
  }

  return (
    <>
      <div style={card}>
        <h3 style={{ fontSize: 15, color: ds.dark, margin: '0 0 4px' }}>Add the chat to your website</h3>
        <p style={small}>
          One line of code puts a chat bubble in the corner of your website. Visitors open it, chat, send photos and voice notes, and you reply from Conversations. Pick where your website is built and follow the steps.
        </p>
        <div role="tablist" aria-label="Website platform" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '8px 0 12px' }}>
          {PLATFORMS.map((p) => (
            <button key={p.id} type="button" role="tab" aria-selected={platform === p.id} onClick={() => setPlatform(p.id)}
              style={{ ...btn(platform === p.id), minHeight: 36, padding: '6px 12px', fontSize: 13 }}>{p.name}</button>
          ))}
        </div>

        <ol style={{ margin: '0 0 12px', paddingLeft: 20, fontSize: 13, color: ds.dark, lineHeight: 1.6 }}>
          {guide.steps.map((s, i) => <li key={i}>{s}</li>)}
        </ol>

        <label style={label} htmlFor="wc-embed-code">Your code (the same on every platform)</label>
        <textarea id="wc-embed-code" readOnly rows={2} style={{ ...input, fontFamily: 'monospace', fontSize: 12 }} value={tag} onFocus={(e) => e.target.select()} />
        <div style={{ margin: '6px 0 4px' }}><button type="button" style={btn(true)} onClick={() => copy(tag, 'Code')}>Copy code</button></div>
        <p style={small}>Menu names change now and then. If you cannot find a step, look for "custom code", "header and footer" or "code injection", or send it to your web person below.</p>

        <hr style={{ border: 0, borderTop: `1px solid ${ds.border}`, margin: '12px 0' }} />
        <h4 style={{ fontSize: 14, color: ds.dark, margin: '0 0 4px' }}>Someone else looks after your website?</h4>
        <form onSubmit={send}>
          <label style={label} htmlFor="wc-mail-to">Their email address</label>
          <input id="wc-mail-to" type="email" required style={input} value={mail.to} maxLength={200} onChange={(e) => setMail({ ...mail, to: e.target.value })} placeholder="webperson@example.com" />
          <label style={label} htmlFor="wc-mail-note">A message for them (optional)</label>
          <input id="wc-mail-note" style={input} value={mail.note} maxLength={500} onChange={(e) => setMail({ ...mail, note: e.target.value })} placeholder="Please add this before Friday" />
          <div style={{ margin: '8px 0 0' }}><button type="submit" style={btn(false)} disabled={busy || !mail.to}>Send instructions</button></div>
          <p style={small}>They get the code and plain steps by email. Nothing about your customers is included.</p>
        </form>

        <hr style={{ border: 0, borderTop: `1px solid ${ds.border}`, margin: '12px 0' }} />
        <h4 style={{ fontSize: 14, color: ds.dark, margin: '0 0 4px' }}>Is it working?</h4>
        <p style={small}>After you save the code, open your website once, wait a few seconds, then press Check. The bubble reports in when anyone loads it.</p>
        <button type="button" style={btn(false)} onClick={check} disabled={busy}>{busy ? 'Checking…' : 'Check installation'}</button>
        {seen.length > 0 && (
          <ul style={{ listStyle: 'none', margin: '10px 0 0', padding: 0, fontSize: 13 }} aria-live="polite">
            {seen.map((s) => (
              <li key={s.host} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 0' }}>
                <span aria-hidden="true" style={{ color: '#1E7A44', fontWeight: 700 }}>✓</span>
                <strong>{s.host}</strong><span style={{ color: ds.gray }}>last seen {ago(s.last_seen_at)}</span>
              </li>
            ))}
          </ul>
        )}
        {seen.length === 0 && checked && <p style={{ ...small, color: ds.dark }}>Not seen yet. Check that the code was saved on the live site (not only a draft), reload your website, then check again.</p>}

        <p style={{ ...small, marginTop: 14 }}><strong>Websites built in Opsra:</strong> the "Chat with us" button is switched on per website. Open Sites, choose the website, and use its Chat button switch. It is off for every website until you switch it on.</p>

        <hr style={{ border: 0, borderTop: `1px solid ${ds.border}`, margin: '12px 0' }} />
        <h4 style={{ fontSize: 14, color: ds.dark, margin: '0 0 4px' }}>Offer a quick answer before the team</h4>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14, minHeight: 44 }}>
          <input type="checkbox" checked={!!cfg.human_offer} onChange={(e) => set('human_offer', e.target.checked)} />
          When a visitor's first tap is Talk to the team, Chioma offers to help first
        </label>
        <p style={small}>She asks what it is about and shows your top buttons, with a clear "No, connect me to the team" button. It happens once per chat and never when someone types that they want a person. Press Save at the bottom after changing this.</p>
        <hr style={{ border: 0, borderTop: `1px solid ${ds.border}`, margin: '12px 0' }} />
        <h4 style={{ fontSize: 14, color: ds.dark, margin: '0 0 4px' }}>Ask bar on your website</h4>
        <p style={small}>A clear "Ask Chioma" bar with your first chat buttons, so visitors see it without hunting for the bubble. Visitors can minimize it, and it then becomes the round bubble.</p>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14, minHeight: 44 }}>
          <input type="checkbox" checked={!!cfg.ask_bar} onChange={(e) => set('ask_bar', e.target.checked)} />
          Show the ask bar on my website
        </label>
        {cfg.ask_bar && (
          <>
            <label style={label} htmlFor="wc-bar-text">Words inside the bar</label>
            <input id="wc-bar-text" style={input} maxLength={60} value={cfg.ask_bar_text || ''} onChange={(e) => set('ask_bar_text', e.target.value)} placeholder="Ask me anything…" />
            <p style={small}>Where it appears: add <code>{'<div data-chioma-slot></div>'}</code> to your page, under your main button for example. On a dark section use <code>{'<div data-chioma-slot data-chioma-theme="dark"></div>'}</code>. Without it, the bar sits at the bottom of the screen. Press Save at the bottom after changing these.</p>
          </>
        )}

        <details style={{ marginTop: 14 }}>
          <summary style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600, color: ds.dark }}>Advanced: corner and allowed websites</summary>
          <label style={label} htmlFor="wc-side">Corner for the bubble</label>
          <select id="wc-side" style={{ ...input, width: 160 }} value={cfg.widget_side || 'right'} onChange={(e) => set('widget_side', e.target.value)}>
            <option value="right">Bottom right</option>
            <option value="left">Bottom left</option>
          </select>
          <label style={label} htmlFor="wc-domains">Only show the bubble on these websites (one per line)</label>
          <textarea id="wc-domains" rows={3} style={input} placeholder={'royalrest.com\nshop.royalrest.com'}
            value={(cfg.allowed_domains || []).join('\n')} onChange={(e) => set('allowed_domains', e.target.value.split('\n'))} />
          <p style={small}>Leave this empty (the normal setting) and the bubble works on any website that has your code. Fill it in only if you want to stop others copying your code. Press Save at the bottom after changing these.</p>
        </details>
      </div>

      <div style={card}>
        <h3 style={{ fontSize: 15, color: ds.dark, margin: '0 0 4px' }}>No website? Share your chat link</h3>
        <p style={small}>Visitors open the chat as a full page, on any phone, no app needed. Each link tags where people came from, so your chat stats show which one works.</p>
        {CHANNELS.map(([k, name, tip]) => (
          <div key={k} style={{ margin: '8px 0' }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ width: 170, fontSize: 12, fontWeight: 600, color: ds.dark }}>{name}</span>
              <input readOnly aria-label={`${name} link`} style={{ ...input, flex: 1 }} value={data.links[k] || ''} onFocus={(e) => e.target.select()} />
              <button type="button" style={btn(false)} onClick={() => copy(data.links[k], 'Link')}>Copy</button>
            </div>
            <p style={{ ...small, margin: '2px 0 0 178px' }}>{tip}</p>
          </div>
        ))}
        <p style={small}>The QR code for flyers, shop windows and receipts is in "Links to share" at the top.</p>
      </div>
    </>
  )
}
