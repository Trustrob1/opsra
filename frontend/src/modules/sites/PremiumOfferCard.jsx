/**
 * frontend/src/modules/sites/PremiumOfferCard.jsx
 * SITE-PREMIUM P5 - "Make it Premium" for a Standard site before go-live (builder portal).
 * Pay the design fee first; payment starts the design. Shows the price, the balance added at go-live, and while
 * the design is being made. If it cannot be made: try again free, or get the fee back.
 */
import { useCallback, useEffect, useState } from 'react'
import { Sparkles, RotateCcw } from 'lucide-react'
import { T } from './sitesKit'
import { Card, Button, Notice, SectionTitle } from './sitesUi'
import { getPremiumOffer, premiumCheckout, retryPremiumDesign, refundPremiumFee, errorMessage } from '../../services/builder_portal.service'

const POLL_MS = 6000
const money = (n) => `₦${Number(n || 0).toLocaleString('en-NG')}`

export default function PremiumOfferCard({ token, siteId, onPremium }) {
  const [offer, setOffer] = useState(null)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [asking, setAsking] = useState(false)

  const load = useCallback(async () => {
    try {
      const r = await getPremiumOffer(token, siteId)
      setOffer(r.offer)
      if (r.tier === 'premium' && onPremium) onPremium()
    } catch (e) { /* the card just stays hidden */ }
  }, [token, siteId, onPremium])

  useEffect(() => { load() }, [load])

  // While the design is made, or after a payment the page has not heard about yet, check every few seconds.
  const waiting = offer?.state === 'designing' || offer?.state === 'awaiting_payment'
  useEffect(() => {
    if (!waiting) return undefined
    const id = setInterval(load, POLL_MS)
    return () => clearInterval(id)
  }, [waiting, load])

  const run = async (name, fn, failText) => {
    setBusy(name); setError(null)
    try { return await fn() } catch (e) { setError(errorMessage(e, failText)); return null } finally { setBusy(null) }
  }

  const pay = async () => {
    const r = await run('pay', () => premiumCheckout(token, siteId, 'design'), 'Could not start the payment.')
    if (r?.checkout_url) window.location.assign(r.checkout_url)
  }
  const retry = async () => {
    const r = await run('retry', () => retryPremiumDesign(token, siteId), 'Could not start the design again.')
    if (r?.offer) setOffer(r.offer)
  }
  const refund = async () => {
    const r = await run('refund', () => refundPremiumFee(token, siteId), 'Could not request the refund.')
    if (r?.offer) { setOffer(r.offer); setAsking(false) }
  }

  if (!offer || !offer.available) return null
  const s = offer.state

  return (
    <Card>
      <SectionTitle title="Make it Premium" hint="A one-of-a-kind design made for your business by Claude, using the same words and photos as your site." />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {(s === 'can_buy' || s === 'awaiting_payment') && (
          <>
            <p style={{ margin: 0, fontSize: 13.5, color: T.ink }}>
              Pay <b>{money(offer.design_fee)}</b> now and your design starts straight away. It covers your first design and {offer.redesigns_included ?? 2} new designs
              if you want to try other looks.
              {offer.golive_balance > 0 && <> The rest, <b>{money(offer.golive_balance)}</b>, is added when you go live (the Premium total is {money(offer.total)}).</>}
            </p>
            <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>
              If we cannot make a design for you, your {money(offer.design_fee)} is returned.
            </p>
            <div><Button variant="primary" icon={Sparkles} loading={busy === 'pay'} disabled={!!busy} onClick={pay}>
              {s === 'awaiting_payment' ? 'Continue to payment' : 'Make it Premium'} · {money(offer.design_fee)}
            </Button></div>
          </>
        )}

        {s === 'designing' && (
          <Notice tone="info">Payment received. Your Premium design is being made. This takes a few minutes, and you can leave this page open.</Notice>
        )}

        {s === 'failed' && (
          <>
            <Notice tone="info">
              Your payment is safe, but the design could not be finished{offer.attempts ? ` (${offer.attempts} ${offer.attempts === 1 ? 'try' : 'tries'})` : ''}.
              {offer.can_retry ? ' You can try again at no charge.' : ' You can get your money back.'}
            </Notice>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {offer.can_retry && <Button variant="primary" icon={RotateCcw} loading={busy === 'retry'} disabled={!!busy} onClick={retry}>Try again, free</Button>}
              {offer.can_refund && !asking && <Button disabled={!!busy} onClick={() => setAsking(true)}>Get my {money(offer.refund_amount)} back</Button>}
            </div>
            {asking && (
              <div style={{ border: `1px solid ${T.lineStrong}`, borderRadius: 10, padding: 12 }}>
                <p style={{ margin: '0 0 10px', fontSize: 13, color: T.ink }}>
                  Return {money(offer.refund_amount)} and stop trying to make a Premium design? Your Standard site stays as it is.
                </p>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <Button variant="primary" loading={busy === 'refund'} disabled={!!busy} onClick={refund}>Yes, return my money</Button>
                  <Button disabled={!!busy} onClick={() => setAsking(false)}>Not now</Button>
                </div>
              </div>
            )}
          </>
        )}

        {s === 'refund_pending' && (
          <Notice tone="info">Your refund of {money(offer.refund_amount)} has been requested. We will send it and message you when it is done.</Notice>
        )}

        {error && <Notice tone="bad">{error}</Notice>}
      </div>
    </Card>
  )
}
