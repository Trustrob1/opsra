/**
 * frontend/src/modules/admin/CatalogGetStarted.jsx
 * STORE-13: the "Get started" tab. Five steps with one clear next action, a progress bar, and the catalog link.
 */
import { ds } from '../../utils/ds'
import { doneCount, progressPct, setupHeadline } from './catalogSetupLogic'

const CARD = { background: 'white', borderRadius: 14, border: '1px solid #E2EFF4', padding: 20 }
const PRIMARY = { background: ds.teal, color: 'white', border: 'none', borderRadius: 10, padding: '0 20px', minHeight: 46, fontFamily: ds.fontDm, fontSize: 13.5, fontWeight: 600, cursor: 'pointer' }
const OUTLINE = { background: 'white', border: '1.5px solid #0a1a24', borderRadius: 10, padding: '0 18px', minHeight: 46, fontFamily: ds.fontDm, fontSize: 13.5, fontWeight: 600, color: '#0a1a24', cursor: 'pointer' }
const SMALL = { background: 'white', border: '1px solid #D0E8F0', borderRadius: 10, padding: '0 16px', minHeight: 40, fontFamily: ds.fontDm, fontSize: 13, fontWeight: 600, color: '#0a1a24', cursor: 'pointer', flexShrink: 0 }
const TEXT_BTN = { background: 'none', border: 'none', padding: '0 8px', minHeight: 44, fontFamily: ds.fontDm, fontSize: 13, fontWeight: 600, color: '#4a7a8a', cursor: 'pointer', textDecoration: 'underline' }

function Tick() {
  return (
    <span aria-hidden="true" style={{ width: 34, height: 34, borderRadius: '50%', background: ds.teal, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
    </span>
  )
}

function Num({ n, active }) {
  return (
    <span aria-hidden="true" style={{ width: 34, height: 34, borderRadius: '50%', flexShrink: 0, boxSizing: 'border-box', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: ds.fontDm, fontSize: 14, fontWeight: 700, background: 'white', color: active ? '#0a1a24' : '#4a7a8a', border: active ? `2px solid ${ds.teal}` : '1.5px solid #C9D9E0' }}>{n}</span>
  )
}

function Optional() {
  return <span style={{ padding: '2px 8px', borderRadius: 10, border: '1px solid #C9D9E0', fontFamily: ds.fontDm, fontSize: 11, fontWeight: 700, color: '#4a7a8a' }}>Optional</span>
}

function Step({ s, onAction, onSkip }) {
  if (s.done) {
    return (
      <div style={{ ...CARD, display: 'flex', alignItems: 'center', gap: 14, padding: '14px 18px' }}>
        <Tick />
        <div style={{ flexGrow: 1, minWidth: 0 }}>
          <div style={{ fontFamily: ds.fontDm, fontSize: 14.5, fontWeight: 700, color: '#0a1a24' }}>{s.title}</div>
          <div style={{ fontFamily: ds.fontDm, fontSize: 13, color: '#4a7a8a', marginTop: 2 }}>{s.summary}</div>
        </div>
        <button style={SMALL} onClick={() => onAction(s.id, 'review')}>Review</button>
      </div>
    )
  }
  if (s.now) {
    return (
      <div style={{ ...CARD, display: 'flex', gap: 14, border: `2px solid ${ds.teal}`, background: '#F1F8F9' }}>
        <Num n={s.n} active />
        <div style={{ flexGrow: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <div style={{ fontFamily: ds.fontSyne, fontSize: 16, fontWeight: 700, color: '#0a1a24' }}>{s.title}</div>
            {s.optional && <Optional />}
          </div>
          <p style={{ margin: '6px 0 0', fontFamily: ds.fontDm, fontSize: 13.5, lineHeight: 1.5, color: '#3a5a6a' }}>{s.desc}</p>
          <div style={{ marginTop: 14, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <button style={PRIMARY} onClick={() => onAction(s.id, 'primary')}>{s.primary}</button>
            {s.secondary && <button style={OUTLINE} onClick={() => onAction(s.id, 'secondary')}>{s.secondary}</button>}
            {s.optional && <button style={TEXT_BTN} onClick={() => onSkip(s.id)}>Skip for now</button>}
          </div>
        </div>
      </div>
    )
  }
  return (
    <div style={{ ...CARD, display: 'flex', alignItems: 'center', gap: 14, padding: '14px 18px' }}>
      <Num n={s.n} />
      <div style={{ flexGrow: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ fontFamily: ds.fontDm, fontSize: 14.5, fontWeight: 700, color: '#0a1a24' }}>{s.title}</div>
          {s.optional && <Optional />}
        </div>
        <div style={{ fontFamily: ds.fontDm, fontSize: 13, lineHeight: 1.45, color: '#4a7a8a', marginTop: 2 }}>{s.desc}</div>
      </div>
      <button style={SMALL} onClick={() => onAction(s.id, 'primary')}>{s.primary}</button>
    </div>
  )
}

export default function CatalogGetStarted({ steps, link, copied, onAction, onSkip, onCopy, onOpenLink, onOpenSettings }) {
  const done = doneCount(steps)
  const hasProducts = !!(steps[0] && steps[0].done)
  const shortLink = (link || '').replace(/^https?:\/\//, '')

  return (
    <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', flexWrap: 'wrap', paddingBottom: 40 }}>
      <div style={{ flex: '1 1 460px', minWidth: 0, maxWidth: 720, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={CARD}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ fontFamily: ds.fontSyne, fontSize: 15, fontWeight: 700, color: '#0a1a24' }}>{setupHeadline(steps)}</div>
            <div style={{ fontFamily: ds.fontDm, fontSize: 13, fontWeight: 600, color: '#4a7a8a' }}>{done} of {steps.length} steps done</div>
          </div>
          <div role="progressbar" aria-valuemin={0} aria-valuemax={steps.length} aria-valuenow={done} aria-label="Setup progress" style={{ marginTop: 12, height: 8, borderRadius: 4, background: '#E2EFF4', overflow: 'hidden' }}>
            <div style={{ height: 8, borderRadius: 4, background: ds.teal, width: progressPct(steps) }} />
          </div>
        </div>
        {steps.map((s) => <Step key={s.id} s={s} onAction={onAction} onSkip={onSkip} />)}
      </div>

      <div style={{ flex: '0 1 320px', minWidth: 260, display: 'flex', flexDirection: 'column', gap: 16 }}>
        {hasProducts ? (
          <div style={CARD}>
            <div style={{ fontFamily: ds.fontSyne, fontSize: 15, fontWeight: 700, color: '#0a1a24' }}>Your catalog link</div>
            <p style={{ margin: '8px 0 0', fontFamily: ds.fontDm, fontSize: 13, lineHeight: 1.5, color: '#4a7a8a' }}>Customers can already open this and order.</p>
            <div style={{ marginTop: 12, minHeight: 46, border: '1px solid #D0E8F0', borderRadius: 10, display: 'flex', alignItems: 'center', padding: '0 14px', fontFamily: ds.fontDm, fontSize: 13, fontWeight: 600, color: '#0a1a24', overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis', boxSizing: 'border-box' }}>
              {shortLink || 'Loading your link…'}
            </div>
            <div style={{ marginTop: 10, display: 'flex', gap: 10 }}>
              <button style={{ ...PRIMARY, flex: 1, opacity: link ? 1 : 0.5 }} disabled={!link} onClick={onCopy}>{copied ? 'Copied' : 'Copy link'}</button>
              <button style={{ ...OUTLINE, flex: 1, opacity: link ? 1 : 0.5 }} disabled={!link} onClick={onOpenLink}>Open page</button>
            </div>
          </div>
        ) : (
          <div style={{ ...CARD, border: '1px dashed #C9D9E0' }}>
            <div style={{ fontFamily: ds.fontSyne, fontSize: 15, fontWeight: 700, color: '#0a1a24' }}>Your catalog link</div>
            <p style={{ margin: '8px 0 0', fontFamily: ds.fontDm, fontSize: 13, lineHeight: 1.5, color: '#4a7a8a' }}>Your link and QR code appear here as soon as you add your first product.</p>
          </div>
        )}

        <div style={CARD}>
          <div style={{ fontFamily: ds.fontSyne, fontSize: 15, fontWeight: 700, color: '#0a1a24' }}>Change the wording</div>
          <p style={{ margin: '8px 0 0', fontFamily: ds.fontDm, fontSize: 13, lineHeight: 1.5, color: '#4a7a8a' }}>Rename what you sell, change how prices look, and edit the stock text. The defaults work for most shops.</p>
          <button style={{ ...OUTLINE, marginTop: 14, minHeight: 44 }} onClick={onOpenSettings}>Open settings</button>
        </div>
      </div>
    </div>
  )
}
