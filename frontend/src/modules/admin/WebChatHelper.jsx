/**
 * frontend/src/modules/admin/WebChatHelper.jsx
 * SMART-1 — helps the owner make Chioma useful with or without AI: a setup checklist, starter menus by kind of business,
 * and the questions she could not answer with a one-tap "add this word to a button".
 */
import { useCallback, useEffect, useState } from 'react'
import { getWebchatChecklist, getWebchatStarters, getWebchatUnanswered, teachWebchat, dismissWebchatUnanswered, applyWebchatTemplate } from '../../services/webchat.service'
import { ds } from '../../utils/ds'
import WhyDisabled from '../../shared/WhyDisabled'   // HINT-1

const card = { background: '#fff', border: `1px solid ${ds.border}`, borderRadius: ds.radius.lg, padding: 16, marginBottom: 16, boxShadow: ds.cardShadow }
const input = { boxSizing: 'border-box', minHeight: 40, padding: '8px 10px', border: `1px solid ${ds.border}`, borderRadius: ds.radius.sm, fontSize: 14, fontFamily: ds.fontDm }
const btn = (primary) => ({ minHeight: 40, padding: '8px 16px', borderRadius: ds.radius.sm, border: primary ? 0 : `1px solid ${ds.teal}`, background: primary ? ds.teal : '#fff', color: primary ? '#fff' : ds.teal, fontWeight: 600, fontSize: 14, cursor: 'pointer', fontFamily: ds.fontDm })

function Row({ gap, buttons, onDone, setMsg }) {
  const [menuId, setMenuId] = useState(buttons[0]?.id || '')
  const [kw, setKw] = useState(gap.suggest || '')
  const [busy, setBusy] = useState(false)
  const run = async (fn, okMsg) => {
    setBusy(true)
    try { await fn(); setMsg(okMsg); onDone() }
    catch (e) { setMsg(e?.response?.data?.detail || 'Could not do that. Please try again.') }
    finally { setBusy(false) }
  }
  return (
    <div style={{ borderTop: `1px solid ${ds.border}`, paddingTop: 10, marginTop: 10 }}>
      <div style={{ fontSize: 14, color: ds.dark }}>“{gap.question}”{gap.times_asked > 1 ? <span style={{ color: ds.gray }}> · asked {gap.times_asked} times</span> : null}</div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 8 }}>
        <label style={{ fontSize: 12, color: ds.gray }} htmlFor={`g-w-${gap.id}`}>Add the word</label>
        <input id={`g-w-${gap.id}`} aria-label="Word to add" style={{ ...input, width: 140 }} value={kw} maxLength={30} onChange={(e) => setKw(e.target.value)} />
        <label style={{ fontSize: 12, color: ds.gray }} htmlFor={`g-b-${gap.id}`}>to</label>
        <select id={`g-b-${gap.id}`} style={{ ...input, minWidth: 160 }} value={menuId} onChange={(e) => setMenuId(e.target.value)}>
          {buttons.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
        </select>
        <button type="button" style={btn(true)} disabled={busy || !kw.trim() || !menuId} onClick={() => run(() => teachWebchat(gap.id, menuId, kw), 'Added. Chioma will now match that word.')}>Add</button>
        <button type="button" style={btn(false)} disabled={busy} onClick={() => run(() => dismissWebchatUnanswered(gap.id), 'Removed from the list.')}>Dismiss</button>
      </div>
      <WhyDisabled reason={!busy && kw.trim() && !menuId ? 'Choose the button the word should lead to.' : ''} />
    </div>
  )
}

export default function WebChatHelper({ cfg, setCfg, setMsg }) {
  const [list, setList] = useState(null)
  const [gaps, setGaps] = useState([])
  const [starters, setStarters] = useState([])
  const [pick, setPick] = useState('')
  const load = useCallback(() => {
    getWebchatChecklist().then(setList).catch(() => setList(null))
    getWebchatUnanswered().then(setGaps).catch(() => setGaps([]))
  }, [])
  useEffect(() => { load(); getWebchatStarters().then((s) => { setStarters(s); setPick(s[0]?.id || '') }).catch(() => {}) }, [load])

  const buttons = (cfg.menu || []).filter((m) => m.action !== 'human')
  const applyStarter = async () => {
    if (!pick) return
    if ((cfg.menu || []).length && !window.confirm('Replace your current menu with this starter menu?')) return
    try {
      const c = await applyWebchatTemplate(pick); setCfg(c)
      setMsg('Starter menu added. Replace the [bracketed] answers with your own before you switch the chat on.'); load()
    } catch { setMsg('Could not add the starter menu.') }
  }

  return (
    <>
      {list && (
        <div style={card}>
          <strong style={{ fontSize: 14, color: ds.dark }}>Make Chioma more useful ({list.done} of {list.total} done)</strong>
          <ul style={{ listStyle: 'none', margin: '8px 0 0', padding: 0 }}>
            {list.items.map((i) => (
              <li key={i.id} style={{ display: 'flex', gap: 8, alignItems: 'baseline', fontSize: 13, color: i.done ? ds.gray : ds.dark, padding: '3px 0' }}>
                <span aria-hidden="true" style={{ color: i.done ? ds.teal : ds.red, fontWeight: 700 }}>{i.done ? '✓' : '○'}</span>
                <span><span style={{ textDecoration: i.done ? 'line-through' : 'none' }}>{i.label}</span>{!i.done && <span style={{ color: ds.gray }}> — {i.hint}</span>}</span>
              </li>
            ))}
          </ul>
          {starters.length > 0 && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 12 }}>
              <label htmlFor="wc-starter" style={{ fontSize: 12, color: ds.gray }}>Start from a ready-made menu</label>
              <select id="wc-starter" style={{ ...input, minWidth: 200 }} value={pick} onChange={(e) => setPick(e.target.value)}>
                {starters.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
              </select>
              <button type="button" style={btn(false)} onClick={applyStarter}>Use this menu</button>
            </div>
          )}
        </div>
      )}
      {gaps.length > 0 && (
        <div style={card}>
          <strong style={{ fontSize: 14, color: ds.dark }}>Questions Chioma could not answer</strong>
          <p style={{ fontSize: 12, color: ds.gray, margin: '4px 0 0' }}>Add a word from the question to the button that should answer it, and she will match it next time.</p>
          {gaps.slice(0, 10).map((g) => <Row key={g.id} gap={g} buttons={buttons} onDone={load} setMsg={setMsg} />)}
        </div>
      )}
    </>
  )
}
