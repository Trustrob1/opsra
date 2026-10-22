/**
 * frontend/src/modules/sites/PricingView.jsx
 * UI-2 - the builder portal's "Pricing" screen: the full line-by-line cost for each domain ending, the own-domain price,
 * renewals and the discount-code note. Data: GET /api/v1/public/host/pricing (the same pricing engine as checkout), so these
 * figures always match what is charged. Nothing is typed in here.
 *
 *   onHost()  go to the Host a site screen
 */
import { useEffect, useState } from 'react'
import { hostPublicPricing, errorMessage } from '../../services/builder_portal.service'
import { T } from './sitesKit'
import { Card, Button, Notice, Spinner } from './sitesUi'
import { ds } from '../../utils/ds'

const naira = (n) => `₦${Math.round(Number(n) || 0).toLocaleString('en-NG')}`
const OWN = 'own'

function Line({ title, hint, value, included }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, padding: '14px 0', borderBottom: `1px solid ${T.line}` }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: T.ink }}>{title}</div>
        <div style={{ fontSize: 13, color: T.soft, marginTop: 2 }}>{hint}</div>
      </div>
      {included
        ? <span style={{ alignSelf: 'flex-start', fontSize: 12, fontWeight: 700, borderRadius: 99, padding: '3px 10px', background: '#E3F5EC', color: '#0B6B43' }}>Included</span>
        : <b style={{ fontSize: 15, color: T.ink, whiteSpace: 'nowrap' }}>{value}</b>}
    </div>
  )
}

export default function PricingView({ onHost }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [pick, setPick] = useState(null)

  useEffect(() => {
    let alive = true
    hostPublicPricing()
      .then((d) => { if (alive) { setData(d); setPick((d.endings.find((e) => e.tld === '.com') || d.endings[0] || {}).tld || (d.own_domain ? OWN : null)) } })
      .catch((e) => { if (alive) setError(errorMessage(e, 'Prices could not be loaded just now.')) })
    return () => { alive = false }
  }, [])

  const head = (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center', justifyContent: 'space-between' }}>
      <div>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, color: T.ink, fontFamily: ds.fontSyne }}>Pricing</h1>
        <p style={{ margin: '4px 0 0', fontSize: 14, color: T.soft }}>Everything you pay for, line by line. Your domain name is included in the price.</p>
      </div>
      {onHost && <Button variant="primary" onClick={onHost}>Host a site</Button>}
    </div>
  )

  if (error) return <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>{head}<Notice tone="bad">{error}</Notice></div>
  if (!data) return <Spinner />
  if (!data.endings.length && !data.own_domain) {
    return <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>{head}<Notice tone="info">Prices are being updated. Please check back shortly.</Notice></div>
  }

  const ending = data.endings.find((e) => e.tld === pick)
  const own = data.own_domain
  const showOwn = pick === OWN && own
  const setup = ending ? ending.first_year.setup : 0
  const renewal = showOwn ? own.renewal : ending ? ending.renewal.total : 0
  const firstYear = showOwn ? own.first_year : ending ? ending.first_year.total : 0

  const pills = [...data.endings.map((e) => [e.tld, e.tld]), ...(own ? [[OWN, 'I already own my domain']] : [])]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {head}
      <div role="tablist" aria-label="Domain ending" style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        {pills.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={pick === key} onClick={() => setPick(key)}
            style={{ minHeight: 40, padding: '0 16px', borderRadius: 99, fontSize: 14, fontWeight: 600, fontFamily: 'inherit', cursor: 'pointer',
              border: `1px solid ${pick === key ? ds.dark : T.line}`, background: pick === key ? ds.dark : '#fff', color: pick === key ? '#fff' : T.ink }}>
            {label}
          </button>
        ))}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24, alignItems: 'flex-start' }}>
        <Card style={{ flex: '999 1 520px', minWidth: 0 }} pad="8px 28px 24px">
          {showOwn ? (
            <>
              <Line title="Domain name" hint="You bought it elsewhere. You keep renewing it there." value="Yours" />
              <Line title="Hosting, 1 year" hint="Keeps your site online, day and night." value={naira(own.first_year)} />
            </>
          ) : ending && (
            <>
              <Line title="Domain name" hint={`Your address, for example yourname${ending.tld}. We register it for you for one year.`} value={naira(ending.first_year.domain)} />
              <Line title="Hosting, 1 year" hint="Keeps your site online, day and night." value={naira(ending.first_year.hosting)} />
              {setup > 0 && <Line title="Setup fee" hint="Charged once, in the first year." value={naira(setup)} />}
            </>
          )}
          <Line title="SSL padlock" hint="Shows visitors your site is safe." included />
          <Line title="DNS management" hint="Points your address to your site. We look after it." included />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', paddingTop: 18, gap: 12, flexWrap: 'wrap' }}>
            <b style={{ fontSize: 18, color: T.ink }}>First year, all in</b>
            <b style={{ fontSize: 34, letterSpacing: '-0.02em', color: T.ink }}>{naira(firstYear)}</b>
          </div>
        </Card>

        <div style={{ flex: '1 1 320px', maxWidth: 440, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Card>
            <b style={{ fontSize: 15, color: T.ink }}>From year two</b>
            <div style={{ fontSize: 30, fontWeight: 800, letterSpacing: '-0.02em', color: T.ink, marginTop: 4 }}>
              {naira(renewal)} <span style={{ fontSize: 14, fontWeight: 500, color: T.soft }}>a year</span>
            </div>
            <p style={{ margin: '8px 0 0', fontSize: 13, color: T.soft, lineHeight: 1.5 }}>
              {showOwn
                ? 'Hosting renews once a year. Your registrar keeps renewing your domain.'
                : 'Your domain and hosting renew together once a year. We email and WhatsApp you before it is due.'}
            </p>
          </Card>
          {own && !showOwn && (
            <Card style={{ background: '#E0F4F6', borderColor: '#BFD9DD' }}>
              <b style={{ fontSize: 15, color: T.ink }}>Already own a domain?</b>
              <p style={{ margin: '6px 0 0', fontSize: 13, color: '#2B4655', lineHeight: 1.5 }}>
                Bought it elsewhere? Use it here. You pay for hosting only: <b>{naira(own.first_year)}</b> the first year, <b>{naira(own.renewal)}</b> to renew.
              </p>
            </Card>
          )}
          <Card>
            <b style={{ fontSize: 15, color: T.ink }}>Have a discount code?</b>
            <p style={{ margin: '6px 0 0', fontSize: 13, color: T.soft }}>Enter it at checkout, before you pay. The new total shows at once.</p>
          </Card>
        </div>
      </div>

      <Card pad={0} style={{ overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', minWidth: 640, borderCollapse: 'collapse', fontSize: 14 }}>
            <caption style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>All options side by side</caption>
            <thead>
              <tr style={{ background: '#F5FAFB' }}>
                {['Option', 'Domain', 'Hosting', 'First year', 'Renews at'].map((h, i) => (
                  <th key={h} scope="col" style={{ textAlign: i === 0 ? 'left' : 'right', padding: '12px 18px', fontSize: 12, letterSpacing: '.04em', textTransform: 'uppercase', color: T.soft, borderBottom: `1px solid ${T.line}` }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.endings.map((e) => (
                <tr key={e.tld}>
                  <th scope="row" style={{ textAlign: 'left', padding: '14px 18px', borderBottom: `1px solid ${T.line}`, color: T.ink }}>{e.tld}</th>
                  <td style={{ textAlign: 'right', padding: '14px 18px', borderBottom: `1px solid ${T.line}` }}>{naira(e.first_year.domain)}</td>
                  <td style={{ textAlign: 'right', padding: '14px 18px', borderBottom: `1px solid ${T.line}` }}>{naira(e.first_year.hosting + (e.first_year.setup || 0))}</td>
                  <td style={{ textAlign: 'right', padding: '14px 18px', borderBottom: `1px solid ${T.line}`, fontWeight: 700 }}>{naira(e.first_year.total)}</td>
                  <td style={{ textAlign: 'right', padding: '14px 18px', borderBottom: `1px solid ${T.line}` }}>{naira(e.renewal.total)}</td>
                </tr>
              ))}
              {own && (
                <tr>
                  <th scope="row" style={{ textAlign: 'left', padding: '14px 18px', color: T.ink }}>I own my domain</th>
                  <td style={{ textAlign: 'right', padding: '14px 18px' }}>Yours</td>
                  <td style={{ textAlign: 'right', padding: '14px 18px' }}>{naira(own.first_year)}</td>
                  <td style={{ textAlign: 'right', padding: '14px 18px', fontWeight: 700 }}>{naira(own.first_year)}</td>
                  <td style={{ textAlign: 'right', padding: '14px 18px' }}>{naira(own.renewal)}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
