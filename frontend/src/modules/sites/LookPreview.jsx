/**
 * frontend/src/modules/sites/LookPreview.jsx
 * SITE-1C-1b — a small live picture of a site in a chosen look (colour, fonts and the nine
 * design options). An approximation for staff to judge a look at a glance; the real page is
 * rendered by the server.
 */
import { previewStyles } from './lookKit'

export default function LookPreview({ cur }) {
  const s = previewStyles(cur)
  const divider = (key) => (
    <div key={key} style={s.divRow} aria-hidden="true">
      <span style={s.divSeg} /><span style={s.divMarkSt}>{s.divMark}</span><span style={s.divSeg} />
    </div>
  )
  const items = [['Ankara Wrap Dress', '₦35,000'], ['Office Blazer', 'From ₦48,000'], ['Two-piece Set', '₦42,000']]
  return (
    <div style={s.root} aria-label="Preview of this look">
      <div style={s.nav}>
        <span style={s.brand}>Adaeze Styles</span>
        <span style={s.links}>Shop &nbsp; Our story &nbsp; How to order</span>
        <span style={s.btn}>Order on WhatsApp</span>
      </div>
      <div style={s.hero}>
        <div style={s.eyebrow}>Lekki, Lagos</div>
        <h1 style={s.h1}>Ankara and corporate wear</h1>
        <p style={s.sub}>Ready-to-wear and made-to-order, delivered nationwide.</p>
        <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}><span style={s.btn1}>Chat on WhatsApp</span><span style={s.btn2}>See more</span></div>
      </div>
      {divider('d1')}
      <div style={s.sec(true)}>
        <h2 style={s.h2}>Find what you need</h2>
        <div style={{ display: 'flex', gap: 14 }}>
          {['Dresses', 'Corporate', 'Kaftans'].map((c) => (
            <div key={c} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}><div style={s.tile} /><span style={s.cap}>{c}</span></div>
          ))}
        </div>
      </div>
      <div style={s.sec(false)}>
        <h2 style={s.h2}>Popular pieces</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 12 }}>
          {items.map(([n, p]) => (
            <div key={n} style={{ ...s.card, display: 'flex', flexDirection: 'column', gap: 7 }}>
              <div style={s.cardImg} /><span style={s.name}>{n}</span><span style={s.price}>{p}</span>
              <span style={{ ...s.btn, alignSelf: 'flex-start' }}>Order</span>
            </div>
          ))}
        </div>
      </div>
      <div style={s.sec(true)}>
        <h2 style={s.h2}>What people say</h2>
        <div style={{ ...s.card, font: `500 12px ${s.bf}` }}>&ldquo;Perfect fit and fast delivery.&rdquo;<div style={{ ...s.cap, marginTop: 6 }}>Ngozi</div></div>
      </div>
      <div style={s.foot}>Chat with us on WhatsApp</div>
    </div>
  )
}
