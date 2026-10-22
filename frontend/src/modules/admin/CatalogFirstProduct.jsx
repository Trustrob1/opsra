/**
 * frontend/src/modules/admin/CatalogFirstProduct.jsx
 * STORE-13: what the Products tab shows before the first product. Two clear ways in, and how the spreadsheet works.
 */
import { useState } from 'react'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import { catalogErrorText } from './catalogErrors'
import { downloadImportTemplate } from './catalogTemplateDownload'

const CARD = { background: 'white', borderRadius: 14, border: '1px solid #E2EFF4', padding: 24, display: 'flex', flexDirection: 'column' }
const PRIMARY = { background: ds.teal, color: 'white', border: 'none', borderRadius: 10, padding: '0 20px', minHeight: 46, fontFamily: ds.fontDm, fontSize: 13.5, fontWeight: 600, cursor: 'pointer' }
const OUTLINE = { background: 'white', border: '1.5px solid #0a1a24', borderRadius: 10, padding: '0 18px', minHeight: 46, fontFamily: ds.fontDm, fontSize: 13.5, fontWeight: 600, color: '#0a1a24', cursor: 'pointer' }
const H3 = { margin: '14px 0 0', fontFamily: ds.fontSyne, fontSize: 17, fontWeight: 700, color: '#0a1a24' }
const P = { margin: '6px 0 0', fontFamily: ds.fontDm, fontSize: 13.5, lineHeight: 1.5, color: '#3a5a6a' }

const HOW = [
  ['Download the template', 'It already has the right columns, with two example rows to show you how.'],
  ['Fill in one row per product', 'Name and price are enough. Rows that start with the word EXAMPLE are ignored.'],
  ['Upload and check', 'You see what will be added, then confirm. Add photos afterwards, in bulk if you like.'],
]

function Icon({ children }) {
  return (
    <span aria-hidden="true" style={{ width: 46, height: 46, borderRadius: 12, background: '#E4F1F3', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <svg width="23" height="23" viewBox="0 0 24 24" fill="none" stroke={ds.teal} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
    </span>
  )
}

export default function CatalogFirstProduct({ itemWord, creating, onAdd, onImport }) {
  const [error, setError] = useState('')
  const phone = useIsMobile(640)
  const word = itemWord || 'product'

  async function template() {
    setError('')
    try { await downloadImportTemplate() } catch (e) { setError(catalogErrorText(e, 'Could not download the template. Please try again.')) }
  }

  return (
    <div style={{ paddingBottom: 40 }}>
      <div style={{ textAlign: 'center', marginTop: 8 }}>
        <h2 style={{ margin: 0, fontFamily: ds.fontSyne, fontSize: 22, fontWeight: 700, color: '#0a1a24' }}>Add your first {word}</h2>
        <p style={{ margin: '8px auto 0', maxWidth: 520, fontFamily: ds.fontDm, fontSize: 13.5, lineHeight: 1.5, color: '#3a5a6a' }}>Choose the way that suits you. You can use the other one any time later.</p>
      </div>

      {error && (
        <div role="alert" style={{ margin: '16px auto 0', maxWidth: 760, background: '#fff2f2', border: '1px solid #e05c5c', borderRadius: 8, padding: '10px 16px', fontFamily: ds.fontDm, fontSize: 13.5, color: '#c0392b' }}>{error}</div>
      )}

      <div style={{ marginTop: 24, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(280px, 100%), 1fr))', gap: 20, maxWidth: 900, marginLeft: 'auto', marginRight: 'auto' }}>
        <div style={CARD}>
          <Icon><path d="M12 5v14M5 12h14" /></Icon>
          <h3 style={H3}>Add one {word}</h3>
          <p style={P}>Best when you have a few. Type a name and price, and add a photo from your phone or computer.</p>
          <div style={{ flexGrow: 1, minHeight: 18 }} />
          <div><button style={{ ...PRIMARY, width: phone ? '100%' : undefined, opacity: creating ? 0.6 : 1 }} disabled={creating} onClick={onAdd}>{creating ? 'Creating…' : `Add a ${word}`}</button></div>
        </div>

        <div style={CARD}>
          <Icon><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></Icon>
          <h3 style={H3}>Import many at once</h3>
          <p style={P}>Best when you already have a list. Fill in our spreadsheet and upload it. Nothing is added until you have reviewed it.</p>
          <div style={{ flexGrow: 1, minHeight: 18 }} />
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button style={{ ...PRIMARY, flex: phone ? '1 1 100%' : undefined }} onClick={template}>Download the template</button>
            <button style={{ ...OUTLINE, flex: phone ? '1 1 100%' : undefined }} onClick={onImport}>Upload my spreadsheet</button>
          </div>
        </div>
      </div>

      <div style={{ ...CARD, marginTop: 20, maxWidth: 900, marginLeft: 'auto', marginRight: 'auto', boxSizing: 'border-box' }}>
        <div style={{ fontFamily: ds.fontDm, fontSize: 12, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: '#4a7a8a' }}>How the spreadsheet works</div>
        <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(220px, 100%), 1fr))', gap: 20 }}>
          {HOW.map(([title, text], i) => (
            <div key={title} style={{ display: 'flex', gap: 12 }}>
              <span aria-hidden="true" style={{ width: 30, height: 30, borderRadius: '50%', border: '1.5px solid #C9D9E0', flexShrink: 0, boxSizing: 'border-box', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: ds.fontDm, fontSize: 13, fontWeight: 700, color: '#0a1a24' }}>{i + 1}</span>
              <div style={{ fontFamily: ds.fontDm, fontSize: 13, lineHeight: 1.5, color: '#3a5a6a' }}>
                <b style={{ display: 'block', fontSize: 14, color: '#0a1a24' }}>{title}</b>{text}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
