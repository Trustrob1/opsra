/**
 * frontend/src/modules/admin/WebChatAdLinks.jsx
 * OPENING-CTA-2 — "Links for ads": one entry per ad. For each ad the owner picks the starting button and (optionally) writes
 * a greeting, then copies what that kind of ad needs:
 *   1. An ad with no website         -> the chat link, tagged with the ad
 *   2. An ad that opens WhatsApp     -> a ready automatic-reply text with the tagged chat link
 *   3. An ad that goes to a website  -> the website address with ?chioma=<tag>, plus a button that opens the chat on that action
 * The ad's words live on the server (cfg.campaigns); the link only carries the tag. Results per ad show in Chat insights, by source.
 */
import { useState } from 'react'
import { ds } from '../../utils/ds'
import { uploadWebchatAdImage, uploadWebchatAdVideo, chatErrorMessage } from '../../services/webchat.service'
import { shrinkImage } from './imageShrink'

const card = { background: '#fff', border: `1px solid ${ds.border}`, borderRadius: ds.radius.lg, padding: 16, marginBottom: 16, boxShadow: ds.cardShadow }
const label = { display: 'block', fontSize: 12, fontWeight: 600, color: ds.dark, margin: '10px 0 4px', fontFamily: ds.fontDm }
const input = { width: '100%', boxSizing: 'border-box', minHeight: 40, padding: '8px 10px', border: `1px solid ${ds.border}`, borderRadius: ds.radius.sm, fontSize: 14, fontFamily: ds.fontDm }
const btn = (primary) => ({ minHeight: 40, padding: '8px 16px', borderRadius: ds.radius.sm, border: primary ? 0 : `1px solid ${ds.teal}`, background: primary ? ds.teal : '#fff', color: primary ? '#fff' : ds.teal, fontWeight: 600, fontSize: 14, cursor: 'pointer', fontFamily: ds.fontDm })
const small = { fontSize: 12, color: ds.gray, margin: '4px 0 8px', lineHeight: 1.5 }

// Same names the stats already use for the built-in links; an ad cannot take them (the server drops them too).
const RESERVED = ['instagram', 'qr', 'site', 'facebook', 'google', 'whatsapp_status', 'email', 'sms', 'whatsapp', 'website', 'link']
const slug = (v) => String(v || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 30)
const esc = (v) => String(v || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

function problem(c, i, all) {
  if (!c.tag) return 'Give the ad a name.'
  if (RESERVED.includes(c.tag)) return 'This name is used for a built-in link. Choose another.'
  if (all.some((o, j) => j !== i && o.tag === c.tag)) return 'Another ad already uses this name.'
  return ''
}

function CopyRow({ title, hint, value, copy, rows }) {
  return (
    <div style={{ margin: '10px 0' }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: ds.dark }}>{title}</div>
      {hint && <p style={{ ...small, margin: '2px 0 4px' }}>{hint}</p>}
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        {rows ? (
          <textarea readOnly rows={rows} aria-label={title} style={{ ...input, flex: 1 }} value={value} onFocus={(e) => e.target.select()} />
        ) : (
          <input readOnly aria-label={title} style={{ ...input, flex: 1 }} value={value} onFocus={(e) => e.target.select()} />
        )}
        <button type="button" style={btn(false)} onClick={() => copy(value)}>Copy</button>
      </div>
    </div>
  )
}

export default function WebChatAdLinks({ data, cfg, set, setMsg }) {
  const [open, setOpen] = useState(0)
  const [page, setPage] = useState('')
  const [urls, setUrls] = useState({})          // picture key -> address, for what was just uploaded
  const [busy, setBusy] = useState(-1)
  const [vbusy, setVbusy] = useState(-1)
  const [vurls, setVurls] = useState({})
  const camps = Array.isArray(cfg.campaigns) ? cfg.campaigns : []
  const items = (cfg.menu || []).filter((m) => m.action !== 'human')
  const copy = (t) => { try { navigator.clipboard.writeText(t); setMsg('Copied.') } catch { setMsg(t) } }
  const upd = (i, patch) => set('campaigns', camps.map((c, j) => (j === i ? { ...c, ...patch } : c)))
  const defaultMain = cfg.shop_enabled ? 'shop' : (items[0] && items[0].id) || ''
  const add = () => { set('campaigns', [...camps, { tag: '', label: '', main: defaultMain, main_label: '', greeting: '', shortcuts: items.filter((m) => m.id !== defaultMain).slice(0, 4).map((m) => ({ id: m.id, label: '' })) }]); setOpen(camps.length) }
  const toggleShortcut = (i, c, id, on) => {                               // AD-SHORTCUTS-1: up to four of your chat buttons shown under the main button
    const cur = Array.isArray(c.shortcuts) ? c.shortcuts : []
    upd(i, { shortcuts: on ? (cur.length >= 4 ? cur : [...cur, { id, label: '' }]) : cur.filter((s) => s.id !== id) })
  }
  const renameShortcut = (i, c, id, text) => upd(i, { shortcuts: (c.shortcuts || []).map((s) => (s.id === id ? { ...s, label: text } : s)) })
  const remove = (i) => { if (window.confirm('Remove this ad? Its links will show your normal chat.')) { set('campaigns', camps.filter((_, j) => j !== i)); setOpen(0) } }
  const pick = async (i, file) => {
    if (!file) return
    setBusy(i)
    try {
      const res = await uploadWebchatAdImage(await shrinkImage(file))
      setUrls((u) => ({ ...u, [res.image]: res.url }))
      upd(i, { image: res.image })
      setMsg('Picture added. Press Save to keep it.')
    } catch (e) { setMsg(chatErrorMessage ? chatErrorMessage(e, 'Could not add the picture. Try a JPG, PNG or WebP under 5 MB.') : 'Could not add the picture.') } finally { setBusy(-1) }
  }
  const pickVideo = async (i, file) => {
    if (!file) return
    if (file.size > 25 * 1024 * 1024) { setMsg('That video is over 25 MB. Export a shorter or smaller one.'); return }
    setVbusy(i)
    try {
      const res = await uploadWebchatAdVideo(file)
      setVurls((u) => ({ ...u, [res.video]: res.url }))
      upd(i, { video: res.video })
      setMsg('Video added. Press Save to keep it.')
    } catch (e) { setMsg(chatErrorMessage(e, 'Could not add the video. Use an MP4 or WebM under 25 MB.')) } finally { setVbusy(-1) }
  }
  const base = data.link || ''
  const biz = cfg.business_name || 'us'

  return (
    <div style={card}>
      <h3 style={{ fontSize: 15, color: ds.dark, margin: '0 0 4px' }}>Links for ads</h3>
      <p style={small}>Make one entry for each ad. Visitors from that ad see your greeting for it and a main button for what the ad promised, and your stats show how many chats, contacts and bookings that ad brought. Press Save at the bottom after changing anything, then copy the links.</p>

      {camps.length === 0 && <p style={small}>No ads yet. Press “Add an ad” to start.</p>}

      {camps.map((c, i) => {
        const bad = problem(c, i, camps)
        const isOpen = open === i
        const mainLabel = c.main_label || (c.main === 'shop' ? 'Shop now' : (items.find((m) => m.id === c.main) || {}).label) || 'Chat now'
        const direct = `${base}?s=${c.tag}`
        const wa = `Hi, thanks for messaging ${biz}. Get instant answers, prices and bookings here, any time: ${direct}`
        const pageUrl = page.trim() ? `${page.trim()}${page.includes('?') ? '&' : '?'}chioma=${c.tag}` : ''
        const snippet = c.main === 'shop' ? `<button data-chioma-open="shop">${esc(mainLabel)}</button>` : `<button data-chioma-menu="${esc(c.main)}">${esc(mainLabel)}</button>`
        return (
          <div key={i} style={{ border: `1px solid ${ds.border}`, borderRadius: ds.radius.sm, padding: 12, margin: '10px 0' }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'space-between' }}>
              <strong style={{ fontSize: 14, color: ds.dark }}>{c.label || c.tag || 'New ad'}</strong>
              <span style={{ display: 'flex', gap: 8 }}>
                <button type="button" style={btn(false)} onClick={() => setOpen(isOpen ? -1 : i)}>{isOpen ? 'Hide' : 'Edit and get links'}</button>
                <button type="button" style={btn(false)} aria-label={`Remove ${c.label || 'this ad'}`} onClick={() => remove(i)}>Remove</button>
              </span>
            </div>
            {isOpen && (
              <>
                <label style={label} htmlFor={`ad-name-${i}`}>Name of the ad (you will see this in your stats)</label>
                <input id={`ad-name-${i}`} style={input} maxLength={60} value={c.label || ''} placeholder="Lekki 3-bed duplex"
                  onChange={(e) => upd(i, { label: e.target.value, ...(c.tag === slug(c.label) ? { tag: slug(e.target.value) } : {}) })} />
                <label style={label} htmlFor={`ad-tag-${i}`}>Tag in the link (letters, numbers and dashes)</label>
                <input id={`ad-tag-${i}`} style={{ ...input, maxWidth: 260 }} maxLength={30} value={c.tag || ''} onChange={(e) => upd(i, { tag: slug(e.target.value) })} />
                {bad && <p style={{ ...small, color: ds.red }}>{bad}</p>}
                <label style={label} htmlFor={`ad-main-${i}`}>Main button for people from this ad</label>
                <select id={`ad-main-${i}`} style={{ ...input, maxWidth: 320 }} value={c.main || ''} onChange={(e) => upd(i, { main: e.target.value })}>
                  <option value="">Use my normal first screen</option>
                  {cfg.shop_enabled && <option value="shop">Shop now (opens the shop)</option>}
                  {items.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                </select>
                <label style={label} htmlFor={`ad-ml-${i}`}>Words on that button (optional)</label>
                <input id={`ad-ml-${i}`} style={{ ...input, maxWidth: 320 }} maxLength={40} value={c.main_label || ''} onChange={(e) => upd(i, { main_label: e.target.value })} placeholder="Book inspection" />
                {c.main && (
                  <>
                    <p style={{ ...label, marginBottom: 4 }}>Quick questions under the main button (up to 4)</p>
                    <p style={small}>Visitors tap one to get that answer straight away. A “More options” button after them opens everything else.</p>
                    {items.filter((m) => m.id !== c.main).map((m) => {
                      const sc = (c.shortcuts || []).find((x) => x.id === m.id)
                      const full = !sc && (c.shortcuts || []).length >= 4
                      return (
                        <div key={m.id} style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '4px 0', flexWrap: 'wrap' }}>
                          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14, minWidth: 220 }}>
                            <input type="checkbox" checked={!!sc} disabled={full} onChange={(e) => toggleShortcut(i, c, m.id, e.target.checked)} /> {m.label}
                          </label>
                          {sc && <input aria-label={`Words on the ${m.label} button for this ad`} style={{ ...input, maxWidth: 220 }} maxLength={30} value={sc.label || ''} placeholder={m.label} onChange={(e) => renameShortcut(i, c, m.id, e.target.value)} />}
                        </div>
                      )
                    })}
                  </>
                )}
                <label style={label} htmlFor={`ad-greet-${i}`}>Greeting for this ad (optional)</label>
                <textarea id={`ad-greet-${i}`} rows={2} style={input} maxLength={400} value={c.greeting || ''} onChange={(e) => upd(i, { greeting: e.target.value })}
                  placeholder="Hi, I'm Chioma. Asking about the Lekki 3-bed duplex? I can share prices and book your inspection." />
                <p style={small}>Say only what is true about the ad. Leave it empty to use your normal greeting.</p>
                <label style={label} htmlFor={`ad-pic-${i}`}>Picture from the ad (optional)</label>
                <p style={small}>Use the same picture as your ad, so visitors see it at the top of the chat. JPG, PNG or WebP, up to 5 MB.</p>
                {(urls[c.image] || (data.ad_images || {})[c.tag]) && <img src={urls[c.image] || data.ad_images[c.tag]} alt={`Picture for ${c.label || 'this ad'}`} style={{ display: 'block', maxWidth: 260, maxHeight: 160, objectFit: 'cover', borderRadius: ds.radius.sm, border: `1px solid ${ds.border}`, marginBottom: 8 }} />}
                {c.image && !(urls[c.image] || (data.ad_images || {})[c.tag]) && <p style={small}>A picture is added. It shows here after you press Save.</p>}
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <input id={`ad-pic-${i}`} type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={(e) => { pick(i, e.target.files && e.target.files[0]); e.target.value = '' }} />
                  <button type="button" style={btn(false)} disabled={busy === i} onClick={() => document.getElementById(`ad-pic-${i}`).click()}>{busy === i ? 'Adding…' : c.image ? 'Change picture' : 'Add a picture'}</button>
                  {c.image && <button type="button" style={btn(false)} onClick={() => upd(i, { image: '' })}>Remove picture</button>}
                </div>
                <label style={label} htmlFor={`ad-vid-${i}`}>Video from the ad (optional)</label>
                <p style={small}>For a video ad, use the same video. MP4 (H.264) or WebM, up to 25 MB, so keep it short. Phone videos in .mov format will not work: export an MP4. Visitors tap to play it, so it does not use their data until they do. If you add a picture too, it shows before the video plays.</p>
                {(vurls[c.video] || (data.ad_videos || {})[c.tag]) && <video src={vurls[c.video] || data.ad_videos[c.tag]} controls preload="metadata" playsInline style={{ display: 'block', maxWidth: 260, maxHeight: 180, background: '#000', borderRadius: ds.radius.sm, marginBottom: 8 }} />}
                {c.video && !(vurls[c.video] || (data.ad_videos || {})[c.tag]) && <p style={small}>A video is added. It shows here after you press Save.</p>}
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <input id={`ad-vid-${i}`} type="file" accept="video/mp4,video/webm" hidden onChange={(e) => { pickVideo(i, e.target.files && e.target.files[0]); e.target.value = '' }} />
                  <button type="button" style={btn(false)} disabled={vbusy === i} onClick={() => document.getElementById(`ad-vid-${i}`).click()}>{vbusy === i ? 'Adding… this can take a minute' : c.video ? 'Change video' : 'Add a video'}</button>
                  {c.video && <button type="button" style={btn(false)} onClick={() => upd(i, { video: '' })}>Remove video</button>}
                </div>

                {!bad && c.tag && (
                  <div style={{ marginTop: 6 }}>
                    <strong style={{ fontSize: 13, color: ds.dark }}>What to paste, by kind of ad</strong>
                    <CopyRow title="1. Ad with no website" hint="Paste this as the ad's website address. Visitors open the chat as a full page." value={direct} copy={copy} />
                    <CopyRow title="2. Ad that opens WhatsApp" hint="Paste this as your WhatsApp automatic reply, so people can carry on in the chat. It also works as a greeting message." value={wa} copy={copy} rows={3} />
                    <div style={{ margin: '10px 0' }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: ds.dark }}>3. Ad that goes to your website</div>
                      <p style={{ ...small, margin: '2px 0 4px' }}>Your website needs the chat code (see “Add the chat to your website” above). Type the page the ad sends people to:</p>
                      <input aria-label="Page address the ad goes to" style={input} value={page} onChange={(e) => setPage(e.target.value)} placeholder="https://yourwebsite.com/lekki-3-bed" />
                    </div>
                    {pageUrl && <CopyRow title="Use this as the ad's website address" hint="The ending tells the chat which ad the visitor came from." value={pageUrl} copy={copy} />}
                    {c.main && <CopyRow title="Optional: a button on that page that opens the chat on the same action" hint="Paste it into the page where the button should appear." value={snippet} copy={copy} rows={2} />}
                  </div>
                )}
              </>
            )}
          </div>
        )
      })}

      <button type="button" style={btn(true)} onClick={add} disabled={camps.length >= 30}>Add an ad</button>
    </div>
  )
}
