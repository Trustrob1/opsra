/**
 * frontend/src/modules/billing/billingUi.js
 * BILLING-UI-1 — the look shared by every Billing tab (and Admin > Credits): soft panels, small buttons, pill tabs.
 */
import { ds } from '../../utils/ds'

export const B = { deep: '#0B3D42', line: '#DBE5E3', soft: '#F4F8F7', page: '#EEF3F2', muted: '#4D6361', mint: '#E3F1F0', tick: '#5FD4A0' }

export const panel = { background: '#fff', border: `1px solid ${B.line}`, borderRadius: 20, padding: 28, marginBottom: 16 }
export const panelTitle = { fontSize: 17, fontWeight: 700, color: ds.dark, margin: 0, fontFamily: ds.fontDm }
export const panelSub = { fontSize: 13.5, color: B.muted, margin: '4px 0 0', lineHeight: 1.5 }

/** Buttons are 40px tall, not 44+: primary is filled teal, secondary is a quiet outline. */
export const button = (primary) => ({
  minHeight: 40, padding: '0 18px', borderRadius: 12, border: primary ? 0 : `1px solid #CFDCDA`,
  background: primary ? ds.teal : '#fff', color: primary ? '#fff' : ds.dark, fontWeight: 600, fontSize: 13.5, cursor: 'pointer', fontFamily: ds.fontDm,
})

export const tile = { background: '#fff', border: `1px solid ${B.line}`, borderRadius: 20, padding: 24, display: 'flex', flexDirection: 'column', gap: 14, justifyContent: 'space-between' }
export const tileDark = { ...tile, background: B.deep, border: `1px solid ${B.deep}`, color: '#fff' }
export const tileLabel = { fontSize: 13.5, color: B.muted }
export const tileValue = { fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', color: ds.dark, fontFamily: ds.fontDm }

export const emptyBox = { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, padding: '32px 16px', textAlign: 'center', background: B.soft, borderRadius: 14, fontSize: 13.5, color: B.muted }

export const BILLING_CSS = `
.bl-tabs{display:flex;gap:2px;background:#fff;border:1px solid ${B.line};border-radius:999px;padding:4px;overflow-x:auto;max-width:100%}
.bl-tab{padding:0 16px;min-height:36px;border-radius:999px;border:0;background:transparent;color:${B.muted};font:inherit;font-size:13.5px;cursor:pointer;white-space:nowrap}
.bl-tab[aria-selected="true"]{background:${B.deep};color:#fff;font-weight:600}
.bl-tab:focus-visible,.bl-pack:focus-visible,.bl-btn:focus-visible{outline:2px solid ${ds.teal};outline-offset:2px}
.bl-bento{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-bottom:16px}
.bl-bento-hero{grid-column:span 2}
@media (max-width:620px){.bl-bento-hero{grid-column:span 1}}
.bl-packs{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px}
.bl-pack{text-align:left;padding:14px;border:1px solid #CFDCDA;background:#fff;border-radius:14px;cursor:pointer;display:flex;flex-direction:column;gap:2px;font-family:inherit;color:${ds.dark}}
.bl-pack:disabled{opacity:.6;cursor:default}
.bl-pack:not(:disabled):hover{border-color:${ds.teal}}
.bl-split{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start}
.bl-split>.bl-main{flex:2 1 520px;min-width:0}
.bl-split>.bl-side{flex:1 1 300px;min-width:0}
`
