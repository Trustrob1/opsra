/**
 * frontend/src/pages/giveawayTerms.jsx
 * GIVEAWAY-1 — the fee, renewal and edit terms, shown the same way on the giveaway page and the winner page.
 * Every number comes from the API (the giveaway's own fee/renewal and the live care-plan settings), never typed here.
 */
export const naira = (n) => `₦${Number(n || 0).toLocaleString('en-NG')}`

const li = { fontSize: 14, lineHeight: 1.5, color: '#2c4152', margin: '0 0 8px' }

export function TermsList({ fee, renewal, terms }) {
  const t = terms || {}
  return (
    <ul style={{ paddingLeft: 18, margin: '0 0 14px' }}>
      <li style={li}>You pay <strong>only {naira(fee)}</strong> for domain and hosting, and only after you have seen your website.</li>
      <li style={li}>From the second year, the domain and hosting renewal is <strong>{naira(renewal)} a year</strong>.</li>
      <li style={li}><strong>{t.free_edits ?? 5} free edits</strong> to your site. One edit can change up to {t.edit_item_cap ?? 10} items; a bigger change counts as more than one edit.</li>
      <li style={li}>After that: a <strong>care plan at {naira(t.care_price_ngn)} a month</strong> gives you {t.care_edits_per_month} edits a month, or buy <strong>{t.pack_edits} extra edits for {naira(t.pack_price_ngn)}</strong> whenever you need them.</li>
      <li style={li}>Simple business websites only{t.max_items ? `, up to ${t.max_items} products or services listed` : ''}. Web apps and full online stores are not included.</li>
      <li style={li}>Your finished website will be shown in the group.</li>
    </ul>
  )
}
