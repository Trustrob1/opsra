/**
 * frontend/src/modules/sites/giveawayCaption.js
 * GIVEAWAY-6 — the post text that goes with the flier. Built only from the giveaway's own numbers (slots, fee, normal
 * rate, pay-by days, renewal, closing time, link), so it never disagrees with the flier or the terms on the signup page.
 * WhatsApp bold (*like this*) is used because the caption is mainly pasted into groups.
 */
const naira = (n) => `₦${Number(n || 0).toLocaleString('en-NG')}`

export const INITIATIVE = 'the Digital Empowerment Initiative Program by Trust Robert'

function closesText(iso) {
  try {
    return new Date(iso).toLocaleDateString('en-NG', { timeZone: 'Africa/Lagos', day: 'numeric', month: 'long' })
  } catch { return '' }
}

export function buildCaption(g, freeEdits = 5) {
  const n = Number(g.total_slots) || 5
  const one = n === 1
  const owner = (g.owner_name || '').trim()
  const camp = (g.campaign_name || g.title || '').trim()
  const fee = Number(g.fee_ngn) || 24500
  const full = Number(g.full_price_ngn) || 65000
  const fullDays = Number(g.full_price_days) || 4
  const payBy = Number(g.pay_by_days) || 3
  const renewal = Number(g.renewal_ngn) || 25000
  const edits = Number(freeEdits) || 5
  const sites = one ? 'website' : 'websites'
  const closes = g.ends_at ? closesText(g.ends_at) : ''

  const L = []
  L.push(`*${n} free ${sites}${owner ? ` for ${owner}` : ''}*`)
  L.push(`${camp ? `${camp} · ` : ''}${one ? 'first complete form wins' : `first ${n} complete forms win`}`)
  L.push('')
  L.push(owner
    ? `${owner} is making ${one ? 'a free website' : `${n} free websites`} available to its members, in collaboration with ${INITIATIVE}.`
    : `${one ? 'A free website is' : `${n} free websites are`} being made available through ${INITIATIVE}.`)
  L.push('')
  L.push('*How it works*')
  L.push('1. Open the link and fill the short form about your business.')
  L.push(one ? '2. If yours is the first complete form, you win the slot.' : `2. If you are one of the first ${n} complete forms, you win a slot.`)
  L.push('3. We build your website and you see the preview first.')
  L.push(`4. Happy with it? Pay ${naira(fee)} for your domain + 1 year hosting. That is the only cost.`)
  L.push('')
  L.push('*Good to know*')
  L.push(`- Pay within ${payBy} days of your preview. After that the slot goes to someone else, and the normal rate of ${naira(full)} applies for ${fullDays} more days before the website is taken down.`)
  L.push(`- Renewal from year two: ${naira(renewal)} a year.`)
  L.push(`- ${edits} free edits included.`)
  L.push('- Simple business websites only.')
  L.push('')
  if (closes) L.push(`Closes ${closes}.`)
  L.push(`Claim your slot: ${g.link_url || ''}`)
  return L.join('\n')
}
