/**
 * KnowledgeModule.jsx - WA-AUTO-4a. What the bot knows.
 * Add a file (PDF, Word, text) or type answers -> see a preview -> "Start using this". Nothing is used by the bot until then.
 * WA-AUTO-4c: websites and Google Docs update themselves weekly; "Not answered" lists what customers asked that the bot could not answer.
 */
import { useEffect, useRef, useState } from 'react'
import { ds } from '../../utils/ds'
import { listKnowledge, addKnowledgeFile, addKnowledgeText, addKnowledgeWebsite, addKnowledgeGdoc, getKnowledgeSource, activateKnowledge, removeKnowledge, refreshKnowledge, setKnowledgeAutoRefresh, listKnowledgeGaps, answerKnowledgeGap, dismissKnowledgeGap, getKnowledgeCatalog, knowledgeError } from '../../services/knowledge.service'

const card = { background: ds.white, border: `1px solid ${ds.border}`, borderRadius: 14, padding: 20, marginBottom: 16 }
const input = { width: '100%', boxSizing: 'border-box', border: `1.5px solid ${ds.border}`, borderRadius: 9, padding: '10px 12px', fontSize: 14, fontFamily: ds.fontDm, color: ds.dark, background: ds.light }
const btn = (primary, off) => ({ background: primary ? (off ? ds.gray : ds.teal) : 'none', color: primary ? '#fff' : ds.dark, border: primary ? 'none' : `1px solid ${ds.border}`, borderRadius: 9, padding: '10px 16px', fontSize: 14, fontWeight: 600, cursor: off ? 'default' : 'pointer', minHeight: 44 })
const day = (v) => (v ? String(v).slice(0, 10) : '')

export default function KnowledgeModule() {
  const [items, setItems] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState('file')          // file | text | url | gdoc
  const [link, setLink] = useState('')
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [draft, setDraft] = useState(null)          // the source being previewed
  const fileRef = useRef(null)
  const [gaps, setGaps] = useState([])
  const [products, setProducts] = useState(0)
  const [answering, setAnswering] = useState(null)   // id of the question being answered
  const [reply, setReply] = useState('')

  const load = () => listKnowledge().then(setItems).catch((e) => setErr(knowledgeError(e)))
  const loadGaps = () => listKnowledgeGaps().then(setGaps).catch(() => {})
  useEffect(() => { load(); loadGaps(); getKnowledgeCatalog().then((c) => setProducts(c.product_count || 0)).catch(() => {}) }, [])
  // A website or Google Doc is read after you add it; check back every few seconds until it is done.
  const reading = (items || []).some((s) => s.status === 'processing')
  useEffect(() => {
    if (!reading) return undefined
    const id = setInterval(load, 4000)
    return () => clearInterval(id)
  }, [reading])

  const run = async (fn) => {
    setBusy(true); setErr(null)
    try { await fn() } catch (e) { setErr(knowledgeError(e)) } finally { setBusy(false) }
  }
  const upload = () => run(async () => {
    const f = fileRef.current?.files?.[0]
    if (!f) { setErr('Choose a file first.'); return }
    setDraft(await addKnowledgeFile(f, title.trim()))
    if (fileRef.current) fileRef.current.value = ''
    await load()
  })
  const saveText = () => run(async () => { setDraft(await addKnowledgeText(title.trim(), text)); setText(''); await load() })
  const addLink = () => run(async () => {
    if (mode === 'url') await addKnowledgeWebsite(link.trim()); else await addKnowledgeGdoc(link.trim())
    setLink(''); await load()
  })
  const review = (id) => run(async () => { setDraft(await getKnowledgeSource(id)) })
  const start = () => run(async () => { await activateKnowledge(draft.id); setDraft(null); setTitle(''); await load() })
  const refreshNow = (id) => run(async () => { await refreshKnowledge(id); await load(); setTimeout(load, 8000) })
  const toggleAuto = (s) => run(async () => { await setKnowledgeAutoRefresh(s.id, s.auto_refresh === false); await load() })
  const sendAnswer = (id) => run(async () => { await answerKnowledgeGap(id, reply.trim()); setAnswering(null); setReply(''); await Promise.all([loadGaps(), load()]) })
  const dismissGap = (id) => run(async () => { await dismissKnowledgeGap(id); await loadGaps() })
  const discard = (id) => run(async () => { await removeKnowledge(id); if (draft?.id === id) setDraft(null); await load() })

  return (
    <div style={{ padding: '20px 16px', maxWidth: 760, margin: '0 auto' }}>
      <h1 style={{ fontFamily: ds.fontSyne, fontSize: 22, color: ds.dark, margin: '0 0 4px' }}>What your bot knows</h1>
      <p style={{ color: ds.gray, fontSize: 13.5, margin: '0 0 16px' }}>
        Add price lists, FAQs, brochures or answers you type. The bot looks up the few most relevant parts for each question, so a bigger library does not make replies cost more.
      </p>
      {err && <div role="alert" style={{ background: '#FDECEC', color: ds.red, borderRadius: 8, padding: '9px 12px', fontSize: 13, marginBottom: 12 }}>{err}</div>}

      {products > 0 && (
        <p style={{ fontSize: 13, color: ds.gray, margin: '0 0 16px' }}>
          The bot can already look up your {products.toLocaleString('en-NG')} product{products === 1 ? '' : 's'} (your catalogue and Shopify), so you do not need to upload them here.
        </p>
      )}

      {gaps.length > 0 && !draft && (
        <div style={card}>
          <h2 style={{ fontSize: 16, margin: '0 0 4px', color: ds.dark }}>Not answered ({gaps.length})</h2>
          <p style={{ fontSize: 13, color: ds.gray, margin: '0 0 8px' }}>Customers asked these and the bot did not know, so a person had to step in. Type the answer once and the bot will use it from now on.</p>
          {gaps.map((g) => (
            <div key={g.id} style={{ padding: '10px 0', borderTop: `1px solid ${ds.border}` }}>
              <div style={{ fontSize: 14, color: ds.dark, fontWeight: 600 }}>{g.question}</div>
              <div style={{ fontSize: 12.5, color: ds.gray, margin: '2px 0 8px' }}>Asked {g.times_asked} time{g.times_asked === 1 ? '' : 's'} · last {day(g.last_asked_at)}</div>
              {answering === g.id ? (
                <>
                  <label htmlFor={`gap-${g.id}`} style={{ display: 'block', fontSize: 13, fontWeight: 600, color: ds.dark, marginBottom: 5 }}>Your answer</label>
                  <textarea id={`gap-${g.id}`} rows={3} style={input} value={reply} maxLength={2000} onChange={(e) => setReply(e.target.value)} />
                  <div style={{ display: 'flex', gap: 10, marginTop: 8, flexWrap: 'wrap' }}>
                    <button type="button" style={btn(true, busy || reply.trim().length < 2)} disabled={busy || reply.trim().length < 2} onClick={() => sendAnswer(g.id)}>Save answer</button>
                    <button type="button" style={btn(false, busy)} disabled={busy} onClick={() => { setAnswering(null); setReply('') }}>Cancel</button>
                  </div>
                </>
              ) : (
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  <button type="button" style={btn(true, busy)} disabled={busy} onClick={() => { setAnswering(g.id); setReply('') }}>Answer this</button>
                  <button type="button" style={btn(false, busy)} disabled={busy} onClick={() => dismissGap(g.id)}>Ignore</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {draft ? (
        <div style={card}>
          <h2 style={{ fontSize: 16, margin: '0 0 6px', color: ds.dark }}>Check before the bot uses this</h2>
          <p style={{ fontSize: 13.5, color: ds.gray, margin: '0 0 10px' }}>
            “{draft.title}” was read as {draft.chunk_count} part{draft.chunk_count === 1 ? '' : 's'} ({draft.char_count.toLocaleString('en-NG')} characters). The start of it looks like this:
          </p>
          {(draft.samples || []).map((s, i) => (
            <p key={i} style={{ fontSize: 13, color: ds.dark, background: ds.light, borderRadius: 8, padding: '8px 10px', margin: '0 0 8px', whiteSpace: 'pre-wrap' }}>{s}{s.length >= 400 ? '…' : ''}</p>
          ))}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 12 }}>
            <button type="button" style={btn(true, busy)} disabled={busy} onClick={start}>Start using this</button>
            <button type="button" style={btn(false, busy)} disabled={busy} onClick={() => discard(draft.id)}>Discard</button>
          </div>
        </div>
      ) : (
        <div style={card}>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <button type="button" style={btn(mode === 'file', false)} onClick={() => setMode('file')}>Upload a file</button>
            <button type="button" style={btn(mode === 'text', false)} onClick={() => setMode('text')}>Type answers</button>
            <button type="button" style={btn(mode === 'url', false)} onClick={() => setMode('url')}>Website</button>
            <button type="button" style={btn(mode === 'gdoc', false)} onClick={() => setMode('gdoc')}>Google Doc</button>
          </div>
          {(mode === 'file' || mode === 'text') && (<>
          <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: ds.dark, marginBottom: 5 }} htmlFor="k-title">Name {mode === 'file' ? '(optional)' : ''}</label>
          <input id="k-title" style={input} value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} placeholder={mode === 'file' ? 'Price list 2026' : 'Delivery and returns'} />
          </>)}
          {(mode === 'url' || mode === 'gdoc') && (
            <>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: ds.dark, marginBottom: 5 }} htmlFor="k-link">{mode === 'url' ? 'Your website address' : 'Link of the Google Doc'}</label>
              <input id="k-link" style={input} value={link} maxLength={500} inputMode="url" onChange={(e) => setLink(e.target.value)}
                placeholder={mode === 'url' ? 'https://www.yourshop.com' : 'https://docs.google.com/document/d/...'} />
              <p style={{ fontSize: 12.5, color: ds.gray, margin: '8px 0 0' }}>
                {mode === 'url' ? 'We read up to 20 pages of this website only. It takes under a minute.' : 'In Google Docs choose Share and set General access to Anyone with the link (Viewer).'}
              </p>
              <div style={{ marginTop: 14 }}><button type="button" style={btn(true, busy || !link.trim())} disabled={busy || !link.trim()} onClick={addLink}>{busy ? 'Starting…' : 'Read it'}</button></div>
            </>
          )}
          {mode === 'url' || mode === 'gdoc' ? null : mode === 'file' ? (
            <>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: ds.dark, margin: '14px 0 5px' }} htmlFor="k-file">PDF, Word (.docx), .txt, .md or .csv, up to 10 MB</label>
              <input id="k-file" ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md,.csv" />
              <div style={{ marginTop: 14 }}><button type="button" style={btn(true, busy)} disabled={busy} onClick={upload}>{busy ? 'Reading…' : 'Add and preview'}</button></div>
            </>
          ) : (
            <>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: ds.dark, margin: '14px 0 5px' }} htmlFor="k-text">Answers the bot should know</label>
              <textarea id="k-text" rows={7} style={input} value={text} onChange={(e) => setText(e.target.value)} />
              <div style={{ marginTop: 14 }}><button type="button" style={btn(true, busy || !title.trim() || text.trim().length < 20)} disabled={busy || !title.trim() || text.trim().length < 20} onClick={saveText}>Add and preview</button></div>
            </>
          )}
        </div>
      )}

      <div style={card}>
        <h2 style={{ fontSize: 16, margin: '0 0 10px', color: ds.dark }}>In your library</h2>
        {items === null && <p style={{ color: ds.gray, fontSize: 13.5 }}>Loading…</p>}
        {items && items.length === 0 && <p style={{ color: ds.gray, fontSize: 13.5, margin: 0 }}>Nothing added yet.</p>}
        {(items || []).map((s) => (
          <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0', borderTop: `1px solid ${ds.border}`, flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 180 }}>
              <div style={{ fontWeight: 600, fontSize: 14, color: ds.dark }}>{s.title}</div>
              <div style={{ fontSize: 12.5, color: ds.gray }}>{({ file: 'File', text: 'Typed', url: 'Website', gdoc: 'Google Doc' })[s.kind] || 'Item'} · {s.chunk_count} parts{s.page_count > 1 ? ` · ${s.page_count} pages` : ''} · {day(s.created_at)}</div>
              {s.status === 'failed' && s.error && <div role="alert" style={{ fontSize: 12.5, color: ds.red, marginTop: 2 }}>{s.error}</div>}
              {s.status === 'active' && (s.kind === 'url' || s.kind === 'gdoc') && (
                <div style={{ fontSize: 12.5, color: ds.gray, marginTop: 2 }}>
                  {s.auto_refresh === false ? 'Not updating by itself' : `Updates itself weekly${s.last_refreshed_at ? ` · checked ${day(s.last_refreshed_at)}` : ''}`}
                  {s.refresh_error && <span role="alert" style={{ display: 'block', color: ds.red }}>{s.refresh_error}</span>}
                </div>
              )}
            </div>
            {s.status === 'active' && (s.kind === 'url' || s.kind === 'gdoc') && (<>
              <button type="button" style={btn(false, busy)} disabled={busy} onClick={() => refreshNow(s.id)}>Update now</button>
              <button type="button" style={btn(false, busy)} disabled={busy} onClick={() => toggleAuto(s)}>{s.auto_refresh === false ? 'Turn weekly update on' : 'Turn weekly update off'}</button>
            </>)}
            <span style={{ fontSize: 12.5, fontWeight: 600, color: s.status === 'active' ? ds.green : ds.gray }}>{s.status === 'active' ? 'In use' : s.status === 'draft' ? 'Waiting for you' : s.status === 'processing' ? 'Reading…' : 'Failed'}</span>
            <button type="button" style={btn(false, busy)} disabled={busy || s.status === 'processing'} onClick={() => (s.status === 'draft' ? review(s.id) : discard(s.id))}>
              {s.status === 'draft' ? 'Review' : 'Remove'}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
