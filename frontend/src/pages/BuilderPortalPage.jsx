/**
 * frontend/src/pages/BuilderPortalPage.jsx
 * SITE-2B (frontend) — the builder web editor/portal. Spec §10.
 *
 * Standalone page — no AppShell, no sidebar, no staff auth. Registered in
 * App.jsx via URL pattern match: `/b/*` (same family as SiteBriefFormPage's
 * `/f/:token` and PublicLogPage's `/log/:token`).
 *
 * Entry point is always a magic link: `/b/login?t=<token>`. This component
 * reads the `t` query param itself (no react-router in this app — see
 * App.jsx's own routing comment), exchanges it once for a builder session,
 * then owns every other screen (My sites / Editor / Account) as in-memory
 * view state — a small self-contained SPA, the same shape as App.jsx's own
 * Zustand-view-state pattern but scoped locally since nothing here needs to
 * be shared outside this page.
 *
 * SECURITY (mirrors Technical Spec §11.1 for the staff app): the builder JWT
 * lives in React state only, never localStorage/sessionStorage. A page
 * refresh loses the session by design — same trade-off the staff app makes.
 * Since the only way in is a fresh magic link, and links are single-use,
 * a refreshed/bookmarked `/b/login` with no `t=` (or an already-used one)
 * correctly lands on the "ask for a new link" error state rather than
 * silently failing.
 *
 * Content-editing cards deliberately are NOT shared with
 * modules/sites/SiteEditorPanel.jsx (the staff editor) — that file is already
 * tested and deployed; duplicating its ~9 small card components here is a
 * safer trade than refactoring it mid-flight. Both read/write the exact same
 * `content`/`recipe` JSON shape (models/sites.py) so they stay compatible by
 * construction, not by shared code.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ArrowLeft, Building2, ChevronDown, CreditCard, Eye, ExternalLink, ImagePlus, LogOut, Plus,
  RefreshCw, Save, ShoppingCart, Trash2, Undo2, User,
} from 'lucide-react'
import {
  exchangeBuilderToken, renewalCheckout, getMyAccount, updateMyAccount, listMySites, getMySite,
  patchMySiteContent, patchMySiteRecipe, renderMySite, undoMySite, uploadMySiteAsset,
  checkDomain, getQuote, checkout, errorMessage,
} from '../services/builder_portal.service'
import { T, INPUT, TEXTAREA, money, dateTime, dateOnly, THEMES, PALETTES, SECTION_LABELS, SITE_STATUS, useToast } from '../modules/sites/sitesKit'
import { Card, Button, Badge, Notice, Spinner, Field, Segmented, SectionTitle, Toast, Empty } from '../modules/sites/sitesUi'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export default function BuilderPortalPage() {
  const [session, setSession] = useState(null)      // { token, builder }
  const [stage, setStage] = useState('exchanging')   // exchanging | error | app
  const [error, setError] = useState('')
  const [view, setView] = useState('mysites')        // mysites | editor | account
  const [selectedSiteId, setSelectedSiteId] = useState(null)
  const [toast, showToast] = useToast()

  useEffect(() => {
    const q = new URLSearchParams(window.location.search)
    const t = q.get('t')
    if (!t) {
      setError("This link is missing its access code. Please open the exact link your team sent you.")
      setStage('error')
      return
    }
    exchangeBuilderToken(t)
      .then((data) => {
        setSession({ token: data.access_token, builder: data.builder })
        setStage('app')
      })
      .catch((e) => {
        setError(errorMessage(e, "This link isn't valid — ask for a new one."))
        setStage('error')
      })
  }, [])

  useEffect(() => {
    if (document.getElementById('bp-keyframes')) return
    const style = document.createElement('style')
    style.id = 'bp-keyframes'
    style.textContent = `
      @keyframes bpspin { to { transform: rotate(360deg); } }
      .spin { animation: bpspin 1s linear infinite; }
      @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
    `
    document.head.appendChild(style)
  }, [])

  function logOut() {
    setSession(null)
    setStage('error')
    setError('You have been signed out. Ask your team for a fresh edit link when you need to come back.')
  }

  return (
    <div style={{ minHeight: '100vh', background: '#F5FAFB', fontFamily: "'DM Sans', system-ui, sans-serif" }}>
      <Header builder={session?.builder} view={view} setView={setView} onBack={() => setSelectedSiteId(null)} onLogOut={logOut} showNav={stage === 'app'} />
      <main style={{ maxWidth: view === 'editor' || view === 'checkout' ? 1320 : 720, margin: '0 auto', padding: '20px 16px 60px' }}>
        {stage === 'exchanging' && <Spinner label="Signing you in…" />}

        {stage === 'error' && (
          <Card style={{ marginTop: 12 }}>
            <Notice tone="bad">{error}</Notice>
          </Card>
        )}

        {stage === 'app' && view === 'mysites' && (
          <MySitesView token={session.token} onOpen={(id) => { setSelectedSiteId(id); setView('editor') }} showToast={showToast} />
        )}

        {stage === 'app' && view === 'editor' && selectedSiteId && (
          <EditorView token={session.token} siteId={selectedSiteId} onBack={() => setView('mysites')}
            onCheckout={() => setView('checkout')} showToast={showToast} />
        )}

        {stage === 'app' && view === 'checkout' && selectedSiteId && (
          <CheckoutView token={session.token} siteId={selectedSiteId} onBack={() => setView('editor')} showToast={showToast} />
        )}

        {stage === 'app' && view === 'account' && (
          <AccountView token={session.token} builder={session.builder}
            onUpdated={(b) => setSession((s) => ({ ...s, builder: b }))} showToast={showToast} />
        )}
      </main>
      <Toast t={toast} />
    </div>
  )
}

function Header({ builder, view, setView, onBack, onLogOut, showNav }) {
  return (
    <header style={{ background: '#0a1f2e', padding: '14px 16px', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
      <div style={{ fontFamily: "'Syne', system-ui, sans-serif", fontWeight: 800, fontSize: 17, color: '#1dc8a4', letterSpacing: '-0.4px' }}>
        Opsra
      </div>
      <div style={{ fontSize: 12, color: '#9fb4c0' }}>Builder portal{builder?.full_name ? ` — ${builder.full_name}` : ''}</div>
      {showNav && (
        <div style={{ display: 'flex', gap: 8, marginLeft: 'auto' }}>
          <button type="button" onClick={() => { onBack(); setView('mysites') }}
            style={navBtn(view === 'mysites')}>My sites</button>
          <button type="button" onClick={() => setView('account')} style={navBtn(view === 'account')}>Account</button>
          <button type="button" onClick={onLogOut}
            style={{ ...navBtn(false), display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <LogOut size={13} aria-hidden="true" /> Sign out
          </button>
        </div>
      )}
    </header>
  )
}

function navBtn(active) {
  return {
    border: 'none', borderRadius: 8, padding: '7px 12px', fontSize: 12.5, fontWeight: 600, cursor: 'pointer',
    background: active ? '#1dc8a4' : 'transparent', color: active ? '#0a1f2e' : '#c7d7de', fontFamily: 'inherit',
  }
}

// ─────────────────────────────── My sites ───────────────────────────────

function MySitesView({ token, onOpen, showToast }) {
  const [sites, setSites] = useState(null)
  const [error, setError] = useState(null)
  const [renewing, setRenewing] = useState(null)

  async function renew(site) {
    setRenewing(site.id)
    try {
      const res = await renewalCheckout(token, site.id)
      window.location.assign(res.checkout_url)
    } catch (e) {
      showToast(errorMessage(e, 'Could not start the renewal.'), 'bad')
      setRenewing(null)
    }
  }

  useEffect(() => {
    listMySites(token)
      .then(setSites)
      .catch((e) => setError(errorMessage(e, 'Could not load your sites.')))
  }, [token])

  if (error) return <Notice tone="bad">{error}</Notice>
  if (sites === null) return <Spinner />

  if (sites.length === 0) {
    return (
      <Card>
        <Empty icon={Building2} title="No sites yet" text="Once a site has been started for one of your clients, it will show up here for you to edit." />
      </Card>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {sites.map((s) => {
        const st = SITE_STATUS[s.status] || SITE_STATUS.brief_in_progress
        return (
          <div key={s.id} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <button type="button" onClick={() => onOpen(s.id)}
            style={{ textAlign: 'left', background: '#fff', border: `1px solid ${T.line}`, borderRadius: 12,
              padding: 16, cursor: 'pointer', fontFamily: 'inherit', display: 'flex', alignItems: 'center',
              justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <div>
              <p style={{ margin: 0, fontSize: 15, fontWeight: 700, color: T.ink }}>{s.client_business_name}</p>
              <p style={{ margin: '3px 0 0', fontSize: 12, color: T.muted }}>
                {s.updated_at ? `Updated ${dateTime(s.updated_at)}` : null}
              </p>
            </div>
            <Badge tone={st.tone}>{st.label}</Badge>
          </button>
          {s.renews_on && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', padding: '0 4px' }}>
              <span style={{ fontSize: 12.5, color: s.renewal_status === 'lapsed' ? T.bad : T.muted }}>
                {s.renewal_status === 'lapsed' ? 'Hosting lapsed' : 'Hosting renews'} {dateOnly(s.renews_on)}
              </span>
              {(s.renewal_status === 'lapsed' || (s.days_to_renewal != null && s.days_to_renewal <= 60)) && (
                <Button loading={renewing === s.id} onClick={() => renew(s)}>Renew now</Button>
              )}
            </div>
          )}
          </div>
        )
      })}
    </div>
  )
}

// ─────────────────────────────── Account ───────────────────────────────

function AccountView({ token, builder, onUpdated, showToast }) {
  const [fullName, setFullName] = useState(builder?.full_name || '')
  const [businessName, setBusinessName] = useState(builder?.business_name || '')
  const [email, setEmail] = useState(builder?.email || '')
  const [saving, setSaving] = useState(false)

  async function save() {
    setSaving(true)
    try {
      const row = await updateMyAccount(token, { full_name: fullName, business_name: businessName, email })
      onUpdated(row)
      showToast('Account updated')
    } catch (e) {
      showToast(errorMessage(e, 'Could not save your account.'), 'bad')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <SectionTitle title="Account" hint="Shown to your clients and used to reach you." />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="Your name"><input style={INPUT} value={fullName} onChange={(e) => setFullName(e.target.value)} /></Field>
        <Field label="Business name"><input style={INPUT} value={businessName} onChange={(e) => setBusinessName(e.target.value)} /></Field>
        <Field label="Email"><input style={INPUT} type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Phone number" hint="Contact your team to change your WhatsApp number.">
          <input style={{ ...INPUT, background: '#F5FAFB', color: T.muted }} value={builder?.phone_number || ''} disabled />
        </Field>
      </div>
      <div style={{ marginTop: 16 }}>
        <Button variant="primary" icon={User} loading={saving} onClick={save}>Save changes</Button>
      </div>
    </Card>
  )
}

// ─────────────────────────────── Editor ───────────────────────────────

function EditorView({ token, siteId, onBack, onCheckout, showToast }) {
  const [site, setSite] = useState(null)
  const [content, setContent] = useState(null)
  const [recipe, setRecipe] = useState(null)
  const [assetUrls, setAssetUrls] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [savingContent, setSavingContent] = useState(false)
  const [savingRecipe, setSavingRecipe] = useState(false)
  const [rendering, setRendering] = useState(false)
  const [undoing, setUndoing] = useState(false)
  // Mobile-only: which pane is showing (Edit vs Preview) since a phone screen
  // has no room for both side by side. Ignored at desktop widths, where the
  // CSS below forces both panes visible at once â see the <style> block in
  // the return.
  const [mobileTab, setMobileTab] = useState('edit')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const s = await getMySite(token, siteId)
      setSite(s)
      setContent(s.content)
      setRecipe(s.recipe)
      const urls = {}
      for (const a of s.assets || []) urls[a.id] = a.public_url
      setAssetUrls(urls)
    } catch (e) {
      setError(errorMessage(e, 'Could not load this site.'))
    } finally {
      setLoading(false)
    }
  }, [token, siteId])

  useEffect(() => { load() }, [load])

  const saveContent = async () => {
    setSavingContent(true)
    try {
      const s = await patchMySiteContent(token, siteId, content)
      setSite(s)
      showToast('Content saved — render to refresh the preview')
    } catch (e) {
      showToast(errorMessage(e, 'Could not save your changes.'), 'bad')
    } finally {
      setSavingContent(false)
    }
  }

  const saveRecipe = async () => {
    setSavingRecipe(true)
    try {
      const s = await patchMySiteRecipe(token, siteId, recipe)
      setSite(s)
      showToast('Design saved — render to refresh the preview')
    } catch (e) {
      showToast(errorMessage(e, 'Could not save your design.'), 'bad')
    } finally {
      setSavingRecipe(false)
    }
  }

  const doRender = async () => {
    setRendering(true)
    try {
      const s = await renderMySite(token, siteId)
      setSite(s)
      showToast('Preview rendered')
    } catch (e) {
      showToast(errorMessage(e, 'Could not render — check the fields above for errors.'), 'bad')
    } finally {
      setRendering(false)
    }
  }

  const doUndo = async () => {
    setUndoing(true)
    try {
      const s = await undoMySite(token, siteId)
      setSite(s)
      setContent(s.content)
      setRecipe(s.recipe)
      showToast('Last change undone')
    } catch (e) {
      showToast(errorMessage(e, 'Nothing to undo yet.'), 'bad')
    } finally {
      setUndoing(false)
    }
  }

  const uploadFor = async (slot, file, onSet) => {
    try {
      const asset = await uploadMySiteAsset(token, siteId, slot, file)
      setAssetUrls((m) => ({ ...m, [asset.id]: asset.public_url }))
      onSet(asset.id)
      showToast('Photo uploaded')
    } catch (e) {
      showToast(errorMessage(e, 'Could not upload this photo.'), 'bad')
    }
  }

  if (loading) return <Spinner />
  if (error) return (<><BackLink onBack={onBack} /><Notice tone="bad">{error}</Notice></>)
  if (!site) return null
  if (!content || !recipe) {
    return (
      <>
        <BackLink onBack={onBack} />
        <Notice tone="info">This site doesn't have its page content ready yet — check back once it's finished generating.</Notice>
      </>
    )
  }

  const st = SITE_STATUS[site.status] || SITE_STATUS.brief_in_progress
  const previewUrl = `${BASE}/s/${site.slug}`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/*
        Split view: on a wide screen the editor and the live preview sit side
        by side, always visible - no separate "open preview" step. Below
        980px there isn't room for both, so a small Edit/Preview segmented
        control (rendered further down, mobile-only) switches which single
        pane shows; `data-active` on each pane is what that control drives,
        and the desktop media query below simply overrides it back to
        "always show both". Kept as a scoped <style> tag (matching this
        page's convention of inline T-token styles everywhere else) rather
        than a new stylesheet, since real CSS media queries are the only
        reliable way to do this without a JS resize listener.
      */}
      <style>{`
        .bp-editor-shell{display:flex;flex-direction:column;gap:16px}
        .bp-pane{display:none}
        .bp-pane[data-active="true"]{display:flex;flex-direction:column;gap:16px}
        .bp-preview-pane{border:1px solid ${T.line};border-radius:10px;overflow:hidden;background:#fff}
        .bp-preview-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;border-bottom:1px solid ${T.line}}
        .bp-preview-frame-wrap{height:62vh;overflow:auto;background:#F6F8F9}
        .bp-mobile-tabs{display:block;position:sticky;top:0;z-index:5;background:#F5FAFB;padding:8px 0;margin:0 -16px;padding-left:16px;padding-right:16px;box-shadow:0 1px 0 ${T.line}}
        @media (min-width:980px){
          .bp-editor-shell{display:grid;grid-template-columns:minmax(380px,1fr) minmax(360px,480px);align-items:start;gap:24px}
          .bp-mobile-tabs{display:none}
          .bp-pane{display:flex !important;flex-direction:column;gap:16px}
          .bp-preview-pane{position:sticky;top:16px;max-height:calc(100vh - 32px)}
          .bp-preview-frame-wrap{height:calc(100vh - 190px)}
        }
      `}</style>

      <BackLink onBack={onBack} />
      <header style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <h1 style={{ margin: 0, fontSize: 19, fontWeight: 700, color: T.ink }}>{site.client_business_name}</h1>
        <Badge tone={st.tone}>{st.label}</Badge>
      </header>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Button variant="secondary" icon={ExternalLink} onClick={() => window.open(previewUrl, '_blank', 'noopener')} disabled={!site.rendered_html}>
          Open live preview
        </Button>
        <Button variant="primary" icon={RefreshCw} loading={rendering} onClick={doRender}>Render preview</Button>
        <Button variant="secondary" icon={Undo2} loading={undoing} onClick={doUndo}>Undo last change</Button>
        {site.status !== 'live' && (
          <Button variant="primary" icon={ShoppingCart} onClick={onCheckout} disabled={!site.rendered_html}
            style={{ marginLeft: 'auto' }}>
            Check out &amp; go live
          </Button>
        )}
      </div>
      <p style={{ margin: 0, fontSize: 11.5, color: T.muted }}>
        {site.updated_at ? `Last saved ${dateTime(site.updated_at)}` : null}
      </p>

      <div className="bp-mobile-tabs">
        <Segmented value={mobileTab} onChange={setMobileTab}
          options={[{ value: 'edit', label: 'Edit' }, { value: 'preview', label: 'Preview' }]} ariaLabel="Edit or preview" />
      </div>

      <div className="bp-editor-shell">
        <div className="bp-pane" data-active={mobileTab === 'edit'}>
          {/* Business and Hero start open (the two you touch almost every visit); the rest start
              collapsed so the form doesn't read as one very long scroll - click a title to open it. */}
          <BusinessCard content={content} setContent={setContent} defaultOpen />
          <HeroCard content={content} setContent={setContent} assetUrls={assetUrls} onUpload={uploadFor} defaultOpen />
          <AboutCard content={content} setContent={setContent} assetUrls={assetUrls} onUpload={uploadFor} />
          <ItemsCard content={content} setContent={setContent} assetUrls={assetUrls} onUpload={uploadFor} />
          <CategoriesCard content={content} setContent={setContent} />
          <ReviewsCard content={content} setContent={setContent} />
          <HoursLocationCard content={content} setContent={setContent} />
          <OrderSeoCard content={content} setContent={setContent} />

          <div><Button variant="primary" icon={Save} loading={savingContent} onClick={saveContent}>Save content</Button></div>

          <DesignCard recipe={recipe} setRecipe={setRecipe} />
          <div><Button variant="primary" icon={Save} loading={savingRecipe} onClick={saveRecipe}>Save design</Button></div>
        </div>

        <div className="bp-pane bp-preview-pane" data-active={mobileTab === 'preview'}>
          <div className="bp-preview-head">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12.5, fontWeight: 700, color: T.ink }}>
              <Eye size={14} aria-hidden="true" /> Live preview
            </span>
            <span style={{ fontSize: 11, color: T.muted }}>Updates after Render preview</span>
          </div>
          <div className="bp-preview-frame-wrap">
            {site.rendered_html
              ? <iframe title="Site preview" srcDoc={site.rendered_html} style={{ width: '100%', height: '100%', minHeight: '60vh', border: 'none', display: 'block' }} />
              : <div style={{ padding: 24 }}>
                  <p style={{ fontSize: 13, color: T.muted, margin: 0 }}>Click <strong>Render preview</strong> above to see how your site looks.</p>
                </div>}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────── Hosting checkout (SITE-3) ───────────────────────────────
//
// Concept C ("Docked summary") from the 3-mockup review: on a wide screen the
// form sits on the left and a fixed-width price panel stays docked on the
// right (always visible, no separate "review" step). Below 980px there's no
// room for a 400px docked column, so it collapses to the SAME
// stacked/sticky-bar shape the editor above already uses — the price
// breakdown becomes an ordinary card in the normal flow (bp-checkout-summary-
// inline), and a slim sticky bar pinned to the bottom of the viewport keeps
// the total + Proceed button reachable while scrolling (borrowed from the
// "Compare & confirm" mockup's sticky bottom bar), so the one thing every
// screen size keeps is "you can always see the price and pay".
//
// Express is intentionally rendered as a locked/disabled second option
// (spec §11.5 / SITE-3B) rather than omitted — quote_both_routes() already
// returns express: null when it isn't enabled for the org, so the UI has a
// stable branch to light up later with no layout change.

function CheckoutView({ token, siteId, onBack, showToast }) {
  const [domain, setDomain] = useState('')
  const [domainCheck, setDomainCheck] = useState(null)
  const [checkingDomain, setCheckingDomain] = useState(false)
  const [backupDomain, setBackupDomain] = useState('')
  const [backupCheck, setBackupCheck] = useState(null)
  const [checkingBackup, setCheckingBackup] = useState(false)

  const [quote, setQuote] = useState(null)
  const [renewalQuote, setRenewalQuote] = useState(null)
  const [quoting, setQuoting] = useState(false)
  const [quoteError, setQuoteError] = useState(null)

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [address, setAddress] = useState('')
  const [acceptedTerms, setAcceptedTerms] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const isDomainLike = (d) => /^[a-z0-9-]+(\.[a-z0-9-]+)+$/i.test((d || '').trim())

  // Auto-price as soon as the domain field looks like a complete domain —
  // debounced so every keystroke doesn't fire a request.
  useEffect(() => {
    if (!isDomainLike(domain)) { setQuote(null); setRenewalQuote(null); setQuoteError(null); return }
    const d = domain.trim().toLowerCase()
    setQuoting(true)
    const t = setTimeout(() => {
      Promise.all([getQuote(token, d, 'initial'), getQuote(token, d, 'renewal')])
        .then(([q, rq]) => { setQuote(q); setRenewalQuote(rq); setQuoteError(null) })
        .catch((e) => { setQuote(null); setRenewalQuote(null); setQuoteError(errorMessage(e, 'Could not price this domain.')) })
        .finally(() => setQuoting(false))
    }, 500)
    return () => clearTimeout(t)
  }, [domain, token])

  async function runCheck(value, setChecking, setResult) {
    if (!isDomainLike(value)) { showToast('Enter a full domain, e.g. business.com.ng', 'bad'); return }
    setChecking(true)
    try {
      const r = await checkDomain(token, value.trim().toLowerCase())
      setResult(r)
    } catch (e) {
      showToast(errorMessage(e, 'Could not check this domain.'), 'bad')
    } finally {
      setChecking(false)
    }
  }

  const standard = quote?.standard && !quote.standard.error ? quote.standard : null
  const standardError = quote?.standard?.error || quoteError
  const renewalStandard = renewalQuote?.standard && !renewalQuote.standard.error ? renewalQuote.standard : null

  const domainOk = domainCheck?.domain === domain.trim().toLowerCase() && domainCheck?.status === 'available'  // .ng names come back available but unconfirmed — that is allowed
  const backupOk = backupCheck?.domain === backupDomain.trim().toLowerCase() && backupCheck?.status === 'available'
  const sameDomain = domain.trim() !== '' && domain.trim().toLowerCase() === backupDomain.trim().toLowerCase()
  const detailsOk = fullName.trim() && email.trim() && phone.trim() && address.trim()
  const canSubmit = Boolean(domainOk && backupOk && !sameDomain && standard && detailsOk && acceptedTerms && !submitting)

  async function submit() {
    if (!canSubmit) return
    setSubmitting(true)
    try {
      const result = await checkout(token, {
        site_id: siteId,
        route: 'standard',
        domain: domain.trim().toLowerCase(),
        backup_domain: backupDomain.trim().toLowerCase(),
        legal_owner: { full_name: fullName.trim(), email: email.trim(), phone: phone.trim(), address: address.trim() },
        accepted_terms: true,
      })
      showToast('Redirecting to payment…')
      window.location.href = result.checkout_url
    } catch (e) {
      showToast(errorMessage(e, 'Could not start checkout.'), 'bad')
      setSubmitting(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <style>{`
        .bp-checkout-shell{display:flex;flex-direction:column;gap:20px}
        .bp-checkout-summary-inline{display:block}
        .bp-checkout-summary-docked{display:none}
        .bp-checkout-sticky-bar{position:sticky;bottom:0;background:#fff;border-top:1px solid ${T.line};
          padding:12px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px;
          margin:8px -16px -60px;box-shadow:0 -4px 16px rgba(10,26,36,.06);z-index:5}
        @media (min-width:980px){
          .bp-checkout-shell{display:grid;grid-template-columns:minmax(380px,1fr) 400px;align-items:start;gap:24px}
          .bp-checkout-summary-inline{display:none}
          .bp-checkout-summary-docked{display:block;position:sticky;top:16px}
          .bp-checkout-sticky-bar{display:none}
        }
      `}</style>

      <BackLink onBack={onBack} label="Back to editor" />
      <header>
        <h1 style={{ margin: 0, fontSize: 19, fontWeight: 700, color: T.ink }}>Hosting checkout</h1>
      </header>

      <div className="bp-checkout-shell">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Card>
            <SectionTitle title="Domain" hint="Confirm the domain and a backup, in case the first is taken." />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <DomainField label="Domain" value={domain} onChange={(v) => { setDomain(v); setDomainCheck(null) }}
                checking={checkingDomain} result={domainCheck}
                onCheck={() => runCheck(domain, setCheckingDomain, setDomainCheck)}
                onPickAlt={(d) => { setDomain(d); setDomainCheck(null) }} />
              <DomainField label="Backup domain" value={backupDomain} onChange={(v) => { setBackupDomain(v); setBackupCheck(null) }}
                checking={checkingBackup} result={backupCheck}
                onCheck={() => runCheck(backupDomain, setCheckingBackup, setBackupCheck)}
                onPickAlt={(d) => { setBackupDomain(d); setBackupCheck(null) }} />
              {sameDomain && <Notice tone="bad">The backup domain must be different from the main domain.</Notice>}
            </div>
          </Card>

          <Card>
            <SectionTitle title="Hosting route" />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <Segmented value="standard" onChange={() => {}} ariaLabel="Hosting route"
                options={[
                  { value: 'standard', label: standard ? `Standard · ${money(standard.price.total)}` : 'Standard' },
                  { value: 'express', label: 'Express (not enabled)' },
                ]} />
              <p style={{ margin: 0, fontSize: 11.5, color: T.muted }}>
                Express hosting (automatic, live within minutes) isn't turned on for your team yet — it'll appear
                here as a second option once it is.
              </p>
              {quoting && <Spinner label="Pricing this domain…" />}
              {standardError && !quoting && <Notice tone="bad">{standardError}</Notice>}
            </div>
          </Card>

          <div className="bp-checkout-summary-inline">
            {standard && <SummaryCard quote={standard} renewalTotal={renewalStandard?.price?.total} />}
          </div>

          <Card>
            <SectionTitle title="Client's legal-owner details" hint="Used only to register the domain — never shared beyond that." />
            <Grid2>
              <Field label="Full name"><input style={INPUT} value={fullName} onChange={(e) => setFullName(e.target.value)} /></Field>
              <Field label="Email"><input style={INPUT} type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
              <Field label="Phone"><input style={INPUT} value={phone} onChange={(e) => setPhone(e.target.value)} /></Field>
              <Field label="Address"><input style={INPUT} value={address} onChange={(e) => setAddress(e.target.value)} /></Field>
            </Grid2>
          </Card>

          <Card>
            <label style={{ display: 'flex', gap: 10, alignItems: 'flex-start', cursor: 'pointer' }}>
              <input type="checkbox" checked={acceptedTerms} onChange={(e) => setAcceptedTerms(e.target.checked)} style={{ marginTop: 3 }} />
              <span style={{ fontSize: 12.5, color: T.soft, lineHeight: 1.55 }}>
                I've read and accept the refund rule and renewal contact clause.
              </span>
            </label>
          </Card>
        </div>

        <div className="bp-checkout-summary-docked">
          {standard
            ? <SummaryCard quote={standard} renewalTotal={renewalStandard?.price?.total} docked
                onSubmit={submit} submitting={submitting} canSubmit={canSubmit} />
            : <Card><p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>Enter a domain above to see pricing.</p></Card>}
        </div>
      </div>

      {standard && (
        <div className="bp-checkout-sticky-bar">
          <div>
            <p style={{ margin: 0, fontSize: 10.5, color: T.muted, fontWeight: 600 }}>Total due today</p>
            <p className="tnum" style={{ margin: 0, fontSize: 18, fontWeight: 700, color: T.ink }}>{money(standard.price.total)}</p>
          </div>
          <Button variant="primary" icon={CreditCard} loading={submitting} disabled={!canSubmit} onClick={submit}>
            Proceed to payment
          </Button>
        </div>
      )}
    </div>
  )
}

function DomainField({ label, value, onChange, checking, result, onCheck, onPickAlt }) {
  const tone = result?.status === 'available' ? 'good' : result?.status === 'taken' ? 'bad' : result ? 'warn' : null
  const unconfirmed = result?.status === 'available' && result?.confirmed === false
  const statusLabel = result?.status === 'available' ? (unconfirmed ? 'Available (unconfirmed)' : 'Available')
    : result?.status === 'taken' ? 'Taken' : 'Could not check';
  return (
    <Field label={label}>
      <div style={{ display: 'flex', gap: 8 }}>
        <input style={INPUT} placeholder="business.com.ng" value={value} onChange={(e) => onChange(e.target.value)} />
        <Button variant="secondary" loading={checking} onClick={onCheck} style={{ flexShrink: 0 }}>Check</Button>
      </div>
      {result && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div><Badge tone={tone}>{statusLabel}</Badge></div>
          {unconfirmed && (
            <p style={{ margin: 0, fontSize: 12, color: T.muted }}>
              This name looks free, but we'll confirm it again just before we register it. If it's gone, we'll use your backup domain.
            </p>
          )}
          {result.status === 'unknown' && (
            <p style={{ margin: 0, fontSize: 12, color: T.muted }}>We couldn't check this name right now. Try again in a moment.</p>
          )}
          {result.status === 'taken' && (result.alternatives || []).length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {result.alternatives.filter((a) => a.available).map((a) => (
                <button key={a.domain} type="button" onClick={() => onPickAlt(a.domain)}
                  style={{ fontSize: 11.5, fontWeight: 600, color: T.teal, background: T.mint, border: 'none',
                    borderRadius: 20, padding: '4px 10px', cursor: 'pointer', fontFamily: 'inherit' }}>
                  {a.domain}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </Field>
  )
}

function SummaryCard({ quote, renewalTotal, docked, onSubmit, submitting, canSubmit }) {
  const p = quote.price
  return (
    <Card>
      <p style={{ margin: 0, fontSize: 10.5, fontWeight: 700, color: T.muted, textTransform: 'uppercase', letterSpacing: '.8px' }}>
        Order summary
      </p>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 10 }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: T.ink }}>Standard hosting</span>
        <Badge tone="info">{quote.live_within_hours}h</Badge>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 16 }}>
        <SummaryRow label={`Domain (${quote.tld})`} value={money(p.domain)} />
        {p.hosting > 0 && <SummaryRow label="Hosting bundle" value={money(p.hosting)} />}
        {p.service_fee > 0 && <SummaryRow label="Service fee" value={money(p.service_fee)} />}
      </div>
      <div style={{ height: 1, background: T.line, margin: '16px 0' }} />
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 13, color: T.soft, fontWeight: 600 }}>Total, first year</span>
        <span className="tnum" style={{ fontSize: 24, fontWeight: 700, color: T.ink }}>{money(p.total)}</span>
      </div>
      <p style={{ margin: '4px 0 0', fontSize: 11.5, color: T.muted }}>
        then {renewalTotal != null ? money(renewalTotal) : '—'} each renewal
      </p>
      <div style={{ background: T.page, borderRadius: 10, padding: '12px 14px', marginTop: 14 }}>
        <p style={{ margin: 0, fontSize: 11, color: T.soft }}>Suggested price to charge your client</p>
        <p className="tnum" style={{ margin: '2px 0 0', fontSize: 16, fontWeight: 700, color: T.teal }}>
          ~{money(quote.suggested_client_price)}
        </p>
      </div>
      {docked && (
        <div style={{ marginTop: 20 }}>
          <Button variant="primary" icon={CreditCard} loading={submitting} disabled={!canSubmit} onClick={onSubmit} style={{ width: '100%' }}>
            Proceed to payment
          </Button>
          <p style={{ margin: '10px 0 0', fontSize: 11, color: T.muted, textAlign: 'center', lineHeight: 1.5 }}>
            You'll be redirected to Paystack to pay {money(p.total)} securely.
          </p>
        </div>
      )}
    </Card>
  )
}

function SummaryRow({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
      <span style={{ color: T.muted }}>{label}</span>
      <span className="tnum" style={{ color: T.ink, fontWeight: 600 }}>{value}</span>
    </div>
  )
}

function CollapseToggle({ open, onToggle }) {
  return (
    <button type="button" onClick={onToggle} aria-expanded={open}
      style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 30, height: 30,
        borderRadius: 8, border: `1px solid ${T.lineStrong}`, background: '#fff', cursor: 'pointer', flexShrink: 0 }}>
      <ChevronDown size={15} color={T.ink} aria-hidden="true"
        style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }} />
    </button>
  )
}

function BackLink({ onBack, label = 'My sites' }) {
  return (
    <button type="button" onClick={onBack}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minHeight: 36, padding: '0 4px', border: 'none', background: 'none',
        color: T.teal, fontSize: 13, fontWeight: 600, fontFamily: 'inherit', cursor: 'pointer' }}>
      <ArrowLeft size={15} aria-hidden="true" /> {label}
    </button>
  )
}

function PhotoField({ label, assetId, assetUrls, onPick }) {
  const url = assetId ? assetUrls[assetId] : null
  return (
    <Field label={label}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {url
          ? <img src={url} alt="" style={{ width: 56, height: 56, borderRadius: 8, objectFit: 'cover', border: `1px solid ${T.line}` }} />
          : <div style={{ width: 56, height: 56, borderRadius: 8, background: '#F1F6F8', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <ImagePlus size={18} color={T.muted} aria-hidden="true" />
            </div>}
        <label style={{ fontSize: 12.5, fontWeight: 600, color: T.teal, cursor: 'pointer' }}>
          {assetId ? 'Replace photo' : 'Upload photo'}
          <input type="file" accept="image/jpeg,image/png,image/webp" style={{ display: 'none' }}
            onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) onPick(f) }} />
        </label>
      </div>
    </Field>
  )
}

function BusinessCard({ content, setContent, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen)
  const b = content.business
  const set = (k) => (e) => setContent((c) => ({ ...c, business: { ...c.business, [k]: e.target.value } }))
  return (
    <Card>
      <SectionTitle title="Business" right={<CollapseToggle open={open} onToggle={() => setOpen((o) => !o)} />} />
      {open && (
        <Grid2>
          <Field label="Name"><input style={INPUT} value={b.name} onChange={set('name')} /></Field>
          <Field label="City"><input style={INPUT} value={b.city} onChange={set('city')} /></Field>
          <Field label="Tagline" style={{ gridColumn: '1 / -1' }}><input style={INPUT} value={b.tagline} onChange={set('tagline')} /></Field>
          <Field label="WhatsApp number"><input style={INPUT} value={b.whatsapp_e164} onChange={set('whatsapp_e164')} /></Field>
          <Field label="Phone (display)"><input style={INPUT} value={b.phone_display} onChange={set('phone_display')} /></Field>
          <Field label="Instagram handle"><input style={INPUT} value={b.instagram} onChange={set('instagram')} /></Field>
          <Field label="Delivery note"><input style={INPUT} value={b.delivery_note} onChange={set('delivery_note')} /></Field>
        </Grid2>
      )}
    </Card>
  )
}

function HeroCard({ content, setContent, assetUrls, onUpload, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen)
  const h = content.hero
  const set = (k) => (e) => setContent((c) => ({ ...c, hero: { ...c.hero, [k]: e.target.value } }))
  return (
    <Card>
      <SectionTitle title="Hero" right={<CollapseToggle open={open} onToggle={() => setOpen((o) => !o)} />} />
      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Field label="Headline"><input style={INPUT} value={h.headline} onChange={set('headline')} /></Field>
          <Field label="Subhead"><input style={INPUT} value={h.subhead} onChange={set('subhead')} /></Field>
          <PhotoField label="Hero photo" assetId={h.image_asset_id} assetUrls={assetUrls}
            onPick={(f) => onUpload('hero', f, (id) => setContent((c) => ({ ...c, hero: { ...c.hero, image_asset_id: id } })))} />
        </div>
      )}
    </Card>
  )
}

function AboutCard({ content, setContent, assetUrls, onUpload, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen)
  const a = content.about
  const set = (k) => (e) => setContent((c) => ({ ...c, about: { ...c.about, [k]: e.target.value } }))
  return (
    <Card>
      <SectionTitle title="About" right={<CollapseToggle open={open} onToggle={() => setOpen((o) => !o)} />} />
      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Field label="Title"><input style={INPUT} value={a.title} onChange={set('title')} /></Field>
          <Field label="Story" hint="One paragraph per line, up to 6">
            <textarea style={TEXTAREA} value={a.body.join('\n')}
              onChange={(e) => setContent((c) => ({ ...c, about: { ...c.about, body: e.target.value.split('\n').slice(0, 6) } }))} />
          </Field>
          <Field label="Owner name"><input style={INPUT} value={a.owner} onChange={set('owner')} /></Field>
          <Field label="Pull quote"><input style={INPUT} value={a.pull_quote} onChange={set('pull_quote')} /></Field>
          <PhotoField label="About photo" assetId={a.image_asset_id} assetUrls={assetUrls}
            onPick={(f) => onUpload('about', f, (id) => setContent((c) => ({ ...c, about: { ...c.about, image_asset_id: id } })))} />
        </div>
      )}
    </Card>
  )
}

function ItemsCard({ content, setContent, assetUrls, onUpload, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen)
  const items = content.items
  const max = 60
  const update = (i, patch) => setContent((c) => ({ ...c, items: c.items.map((it, idx) => (idx === i ? { ...it, ...patch } : it)) }))
  const add = () => { if (items.length < max) setContent((c) => ({ ...c, items: [...c.items, blankItem()] })) }
  const remove = (i) => setContent((c) => ({ ...c, items: c.items.filter((_, idx) => idx !== i) }))
  function blankItem() { return { name: '', desc: '', price_ngn: 0, price_style: 'exact', tag: null, image_asset_id: null } }

  return (
    <Card>
      <SectionTitle title="Items / Shop" hint={`Up to ${max} items`}
        right={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {items.length < max && <Button size="sm" variant="secondary" icon={Plus} onClick={add}>Add item</Button>}
            <CollapseToggle open={open} onToggle={() => setOpen((o) => !o)} />
          </div>
        } />
      {open && (items.length === 0 ? (
        <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>No items yet.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {items.map((it, i) => (
            <div key={i} style={{ border: `1px solid ${T.line}`, borderRadius: 10, padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <Grid2>
                <Field label="Name"><input style={INPUT} value={it.name} onChange={(e) => update(i, { name: e.target.value })} /></Field>
                <Field label="Price (₦)"><input style={INPUT} type="number" min="0" step="0.01" value={it.price_ngn}
                  onChange={(e) => update(i, { price_ngn: Number(e.target.value) || 0 })} /></Field>
                <Field label="Description" style={{ gridColumn: '1 / -1' }}><input style={INPUT} value={it.desc}
                  onChange={(e) => update(i, { desc: e.target.value })} /></Field>
                <Field label="Price style">
                  <select style={INPUT} value={it.price_style} onChange={(e) => update(i, { price_style: e.target.value })}>
                    <option value="exact">Exact</option><option value="from">From</option><option value="on_request">On request</option>
                  </select>
                </Field>
                <Field label="Tag (optional)"><input style={INPUT} value={it.tag || ''}
                  onChange={(e) => update(i, { tag: e.target.value || null })} /></Field>
              </Grid2>
              <PhotoField label="Item photo" assetId={it.image_asset_id} assetUrls={assetUrls}
                onPick={(f) => onUpload(`item_${i}`, f, (id) => update(i, { image_asset_id: id }))} />
              <div><Button size="sm" variant="danger" icon={Trash2} onClick={() => remove(i)}>Remove</Button></div>
            </div>
          ))}
        </div>
      ))}
    </Card>
  )
}

function CategoriesCard({ content, setContent, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen)
  const rows = content.categories
  const update = (i, patch) => setContent((c) => ({ ...c, categories: c.categories.map((r, idx) => (idx === i ? { ...r, ...patch } : r)) }))
  const add = () => { if (rows.length < 20) setContent((c) => ({ ...c, categories: [...c.categories, { name: '', teaser: '' }] })) }
  const remove = (i) => setContent((c) => ({ ...c, categories: c.categories.filter((_, idx) => idx !== i) }))
  return (
    <Card>
      <SectionTitle title="Categories" right={
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Button size="sm" variant="secondary" icon={Plus} onClick={add}>Add category</Button>
          <CollapseToggle open={open} onToggle={() => setOpen((o) => !o)} />
        </div>
      } />
      {open && (rows.length === 0 ? <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>No categories yet.</p> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {rows.map((r, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <Field label="Name" style={{ flex: 1, minWidth: 140 }}><input style={INPUT} value={r.name} onChange={(e) => update(i, { name: e.target.value })} /></Field>
              <Field label="Teaser" style={{ flex: 2, minWidth: 160 }}><input style={INPUT} value={r.teaser} onChange={(e) => update(i, { teaser: e.target.value })} /></Field>
              <Button size="sm" variant="danger" icon={Trash2} onClick={() => remove(i)}>Remove</Button>
            </div>
          ))}
        </div>
      ))}
    </Card>
  )
}

function ReviewsCard({ content, setContent, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen)
  const rows = content.reviews
  const update = (i, patch) => setContent((c) => ({ ...c, reviews: c.reviews.map((r, idx) => (idx === i ? { ...r, ...patch } : r)) }))
  const add = () => { if (rows.length < 20) setContent((c) => ({ ...c, reviews: [...c.reviews, { text: '', who: '' }] })) }
  const remove = (i) => setContent((c) => ({ ...c, reviews: c.reviews.filter((_, idx) => idx !== i) }))
  return (
    <Card>
      <SectionTitle title="Reviews" hint="Only ever your own words — never invented."
        right={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Button size="sm" variant="secondary" icon={Plus} onClick={add}>Add review</Button>
            <CollapseToggle open={open} onToggle={() => setOpen((o) => !o)} />
          </div>
        } />
      {open && (rows.length === 0 ? <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>No reviews yet.</p> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {rows.map((r, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <Field label="Review text" style={{ flex: 2, minWidth: 200 }}><input style={INPUT} value={r.text} onChange={(e) => update(i, { text: e.target.value })} /></Field>
              <Field label="Who" style={{ flex: 1, minWidth: 120 }}><input style={INPUT} value={r.who} onChange={(e) => update(i, { who: e.target.value })} /></Field>
              <Button size="sm" variant="danger" icon={Trash2} onClick={() => remove(i)}>Remove</Button>
            </div>
          ))}
        </div>
      ))}
    </Card>
  )
}

function HoursLocationCard({ content, setContent, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen)
  const hours = content.hours
  const loc = content.location
  const updateHour = (i, patch) => setContent((c) => ({ ...c, hours: c.hours.map((r, idx) => (idx === i ? { ...r, ...patch } : r)) }))
  const addHour = () => { if (hours.length < 7) setContent((c) => ({ ...c, hours: [...c.hours, { days: '', time: '' }] })) }
  const removeHour = (i) => setContent((c) => ({ ...c, hours: c.hours.filter((_, idx) => idx !== i) }))
  const setLoc = (k) => (e) => setContent((c) => ({ ...c, location: { ...c.location, [k]: e.target.value } }))

  return (
    <Card>
      <SectionTitle title="Hours & location" right={
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {hours.length < 7 && <Button size="sm" variant="secondary" icon={Plus} onClick={addHour}>Add hours row</Button>}
          <CollapseToggle open={open} onToggle={() => setOpen((o) => !o)} />
        </div>
      } />
      {open && (
        <>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 14 }}>
            {hours.map((r, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                <Field label="Days" style={{ flex: 1, minWidth: 120 }}><input style={INPUT} value={r.days} onChange={(e) => updateHour(i, { days: e.target.value })} /></Field>
                <Field label="Time" style={{ flex: 1, minWidth: 120 }}><input style={INPUT} value={r.time} onChange={(e) => updateHour(i, { time: e.target.value })} /></Field>
                <Button size="sm" variant="danger" icon={Trash2} onClick={() => removeHour(i)}>Remove</Button>
              </div>
            ))}
          </div>
          <Grid2>
            <Field label="Address"><input style={INPUT} value={loc.address || ''} onChange={setLoc('address')} /></Field>
            <Field label="Landmark"><input style={INPUT} value={loc.landmark || ''} onChange={setLoc('landmark')} /></Field>
          </Grid2>
        </>
      )}
    </Card>
  )
}

function OrderSeoCard({ content, setContent, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen)
  const o = content.order_section
  const seo = content.seo
  return (
    <Card>
      <SectionTitle title="How to order & SEO" right={<CollapseToggle open={open} onToggle={() => setOpen((o) => !o)} />} />
      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Field label="Order section title"><input style={INPUT} value={o.title}
            onChange={(e) => setContent((c) => ({ ...c, order_section: { ...c.order_section, title: e.target.value } }))} /></Field>
          <Field label="Steps" hint="One per line, up to 6">
            <textarea style={TEXTAREA} value={o.steps.join('\n')}
              onChange={(e) => setContent((c) => ({ ...c, order_section: { ...c.order_section, steps: e.target.value.split('\n').slice(0, 6) } }))} />
          </Field>
          <Field label="SEO title"><input style={INPUT} value={seo.title}
            onChange={(e) => setContent((c) => ({ ...c, seo: { ...c.seo, title: e.target.value } }))} /></Field>
          <Field label="SEO description"><input style={INPUT} value={seo.description}
            onChange={(e) => setContent((c) => ({ ...c, seo: { ...c.seo, description: e.target.value } }))} /></Field>
        </div>
      )}
    </Card>
  )
}

function DesignCard({ recipe, setRecipe, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen)
  const sections = Object.keys(SECTION_LABELS)
  const toggleHidden = (key) => setRecipe((r) => ({
    ...r, hidden: r.hidden.includes(key) ? r.hidden.filter((x) => x !== key) : [...r.hidden, key],
  }))

  return (
    <Card>
      <SectionTitle title="Design" hint="Theme and colour palette. Uncheck a section to hide it without losing its content."
        right={<CollapseToggle open={open} onToggle={() => setOpen((v) => !v)} />} />
      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Field label="Theme" group>
            <Segmented value={recipe.theme} onChange={(v) => setRecipe((r) => ({ ...r, theme: v }))}
              options={THEMES.map((t) => ({ value: t.value, label: t.label, hint: t.hint }))} ariaLabel="Theme" />
          </Field>
          <Field label="Palette" group>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              {PALETTES.map((p) => (
                <button key={p.value} type="button"
                  onClick={() => setRecipe((r) => ({ ...r, palette: p.value, custom_colour: null }))}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', borderRadius: 8,
                    border: `1px solid ${recipe.palette === p.value ? T.teal : T.lineStrong}`, background: recipe.palette === p.value ? '#F0FAFB' : '#fff',
                    cursor: 'pointer', fontFamily: 'inherit', fontSize: 12.5, fontWeight: 600, color: T.ink }}>
                  <span style={{ width: 14, height: 14, borderRadius: '50%', background: p.accent, display: 'inline-block' }} />
                  {p.label}
                </button>
              ))}
            </div>
          </Field>
          <Field label="Or a custom colour" hint="6-digit hex, e.g. #7A2E4A — overrides the palette above">
            <input style={{ ...INPUT, maxWidth: 160 }} placeholder="#7A2E4A" value={recipe.custom_colour || ''}
              onChange={(e) => setRecipe((r) => ({ ...r, custom_colour: e.target.value || null }))} />
          </Field>
          <Field label="Sections shown" group>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
              {sections.map((key) => (
                <label key={key} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: T.ink }}>
                  <input type="checkbox" checked={!recipe.hidden.includes(key)} onChange={() => toggleHidden(key)} />
                  {SECTION_LABELS[key] || key}
                </label>
              ))}
            </div>
          </Field>
        </div>
      )}
    </Card>
  )
}

function Grid2({ children }) {
  return <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>{children}</div>
}
