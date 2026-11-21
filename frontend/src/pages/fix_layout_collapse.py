import io

path = "BuilderPortalPage.jsx"
with io.open(path, "r", encoding="utf-8") as f:
    content = f.read()

def apply(old, new, label):
    global content
    n = content.count(old)
    assert n == 1, "%s: expected 1 match, found %d" % (label, n)
    content = content.replace(old, new)

# 1. main width
apply(
"""      <Header builder={session?.builder} view={view} setView={setView} onBack={() => setSelectedSiteId(null)} onLogOut={logOut} showNav={stage === 'app'} />
      <main style={{ maxWidth: 720, margin: '0 auto', padding: '20px 16px 60px' }}>""",
"""      <Header builder={session?.builder} view={view} setView={setView} onBack={() => setSelectedSiteId(null)} onLogOut={logOut} showNav={stage === 'app'} />
      <main style={{ maxWidth: view === 'editor' ? 1320 : 720, margin: '0 auto', padding: '20px 16px 60px' }}>""",
"main-width")

# 2. import ChevronDown
apply(
"""import {
  ArrowLeft, Building2, Eye, ExternalLink, ImagePlus, LogOut, Plus,
  RefreshCw, Save, Trash2, Undo2, User,
} from 'lucide-react'""",
"""import {
  ArrowLeft, Building2, ChevronDown, Eye, ExternalLink, ImagePlus, LogOut, Plus,
  RefreshCw, Save, Trash2, Undo2, User,
} from 'lucide-react'""",
"import")

# 3. CollapseToggle component before BackLink
apply(
"""function BackLink({ onBack }) {""",
"""function CollapseToggle({ open, onToggle }) {
  return (
    <button type="button" onClick={onToggle} aria-expanded={open}
      style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 30, height: 30,
        borderRadius: 8, border: `1px solid ${T.lineStrong}`, background: '#fff', cursor: 'pointer', flexShrink: 0 }}>
      <ChevronDown size={15} color={T.ink} aria-hidden="true"
        style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }} />
    </button>
  )
}

function BackLink({ onBack }) {""",
"CollapseToggle-insert")

# 4. sticky mobile tabs CSS
apply(
"""        .bp-mobile-tabs{display:block}
        @media (min-width:980px){""",
"""        .bp-mobile-tabs{display:block;position:sticky;top:0;z-index:5;background:#F5FAFB;padding:8px 0;margin:0 -16px;padding-left:16px;padding-right:16px;box-shadow:0 1px 0 ${T.line}}
        @media (min-width:980px){""",
"sticky-tabs")

# 5. EditorView call sites: defaultOpen wiring
apply(
"""      <div className="bp-editor-shell" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div className="bp-pane" data-active={mobileTab === 'edit'} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <BusinessCard content={content} setContent={setContent} />
          <HeroCard content={content} setContent={setContent} assetUrls={assetUrls} onUpload={uploadFor} />
          <AboutCard content={content} setContent={setContent} assetUrls={assetUrls} onUpload={uploadFor} />
          <ItemsCard content={content} setContent={setContent} assetUrls={assetUrls} onUpload={uploadFor} />
          <CategoriesCard content={content} setContent={setContent} />
          <ReviewsCard content={content} setContent={setContent} />
          <HoursLocationCard content={content} setContent={setContent} />
          <OrderSeoCard content={content} setContent={setContent} />

          <div><Button variant="primary" icon={Save} loading={savingContent} onClick={saveContent}>Save content</Button></div>

          <DesignCard recipe={recipe} setRecipe={setRecipe} />
          <div><Button variant="primary" icon={Save} loading={savingRecipe} onClick={saveRecipe}>Save design</Button></div>
        </div>""",
"""      <div className="bp-editor-shell" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div className="bp-pane" data-active={mobileTab === 'edit'} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
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
        </div>""",
"editorview-callsites")

# 6. BusinessCard
apply(
"""function BusinessCard({ content, setContent }) {
  const b = content.business
  const set = (k) => (e) => setContent((c) => ({ ...c, business: { ...c.business, [k]: e.target.value } }))
  return (
    <Card>
      <SectionTitle title="Business" />
      <Grid2>
        <Field label="Name"><input style={INPUT} value={b.name} onChange={set('name')} /></Field>
        <Field label="City"><input style={INPUT} value={b.city} onChange={set('city')} /></Field>
        <Field label="Tagline" style={{ gridColumn: '1 / -1' }}><input style={INPUT} value={b.tagline} onChange={set('tagline')} /></Field>
        <Field label="WhatsApp number"><input style={INPUT} value={b.whatsapp_e164} onChange={set('whatsapp_e164')} /></Field>
        <Field label="Phone (display)"><input style={INPUT} value={b.phone_display} onChange={set('phone_display')} /></Field>
        <Field label="Instagram handle"><input style={INPUT} value={b.instagram} onChange={set('instagram')} /></Field>
        <Field label="Delivery note"><input style={INPUT} value={b.delivery_note} onChange={set('delivery_note')} /></Field>
      </Grid2>
    </Card>
  )
}""",
"""function BusinessCard({ content, setContent, defaultOpen }) {
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
}""",
"BusinessCard")

# 7. HeroCard
apply(
"""function HeroCard({ content, setContent, assetUrls, onUpload }) {
  const h = content.hero
  const set = (k) => (e) => setContent((c) => ({ ...c, hero: { ...c.hero, [k]: e.target.value } }))
  return (
    <Card>
      <SectionTitle title="Hero" />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="Headline"><input style={INPUT} value={h.headline} onChange={set('headline')} /></Field>
        <Field label="Subhead"><input style={INPUT} value={h.subhead} onChange={set('subhead')} /></Field>
        <PhotoField label="Hero photo" assetId={h.image_asset_id} assetUrls={assetUrls}
          onPick={(f) => onUpload('hero', f, (id) => setContent((c) => ({ ...c, hero: { ...c.hero, image_asset_id: id } })))} />
      </div>
    </Card>
  )
}""",
"""function HeroCard({ content, setContent, assetUrls, onUpload, defaultOpen }) {
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
}""",
"HeroCard")

# 8. AboutCard
apply(
"""function AboutCard({ content, setContent, assetUrls, onUpload }) {
  const a = content.about
  const set = (k) => (e) => setContent((c) => ({ ...c, about: { ...c.about, [k]: e.target.value } }))
  return (
    <Card>
      <SectionTitle title="About" />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="Title"><input style={INPUT} value={a.title} onChange={set('title')} /></Field>
        <Field label="Story" hint="One paragraph per line, up to 6">
          <textarea style={TEXTAREA} value={a.body.join('\\n')}
            onChange={(e) => setContent((c) => ({ ...c, about: { ...c.about, body: e.target.value.split('\\n').slice(0, 6) } }))} />
        </Field>
        <Field label="Owner name"><input style={INPUT} value={a.owner} onChange={set('owner')} /></Field>
        <Field label="Pull quote"><input style={INPUT} value={a.pull_quote} onChange={set('pull_quote')} /></Field>
        <PhotoField label="About photo" assetId={a.image_asset_id} assetUrls={assetUrls}
          onPick={(f) => onUpload('about', f, (id) => setContent((c) => ({ ...c, about: { ...c.about, image_asset_id: id } })))} />
      </div>
    </Card>
  )
}""",
"""function AboutCard({ content, setContent, assetUrls, onUpload, defaultOpen }) {
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
            <textarea style={TEXTAREA} value={a.body.join('\\n')}
              onChange={(e) => setContent((c) => ({ ...c, about: { ...c.about, body: e.target.value.split('\\n').slice(0, 6) } }))} />
          </Field>
          <Field label="Owner name"><input style={INPUT} value={a.owner} onChange={set('owner')} /></Field>
          <Field label="Pull quote"><input style={INPUT} value={a.pull_quote} onChange={set('pull_quote')} /></Field>
          <PhotoField label="About photo" assetId={a.image_asset_id} assetUrls={assetUrls}
            onPick={(f) => onUpload('about', f, (id) => setContent((c) => ({ ...c, about: { ...c.about, image_asset_id: id } })))} />
        </div>
      )}
    </Card>
  )
}""",
"AboutCard")

# 9. ItemsCard
apply(
"""function ItemsCard({ content, setContent, assetUrls, onUpload }) {
  const items = content.items
  const max = 60
  const update = (i, patch) => setContent((c) => ({ ...c, items: c.items.map((it, idx) => (idx === i ? { ...it, ...patch } : it)) }))
  const add = () => { if (items.length < max) setContent((c) => ({ ...c, items: [...c.items, blankItem()] })) }
  const remove = (i) => setContent((c) => ({ ...c, items: c.items.filter((_, idx) => idx !== i) }))
  function blankItem() { return { name: '', desc: '', price_ngn: 0, price_style: 'exact', tag: null, image_asset_id: null } }

  return (
    <Card>
      <SectionTitle title="Items / Shop" hint={`Up to ${max} items`}
        right={items.length < max && <Button size="sm" variant="secondary" icon={Plus} onClick={add}>Add item</Button>} />
      {items.length === 0 ? (
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
      )}
    </Card>
  )
}""",
"""function ItemsCard({ content, setContent, assetUrls, onUpload, defaultOpen }) {
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
}""",
"ItemsCard")

# 10. CategoriesCard
apply(
"""function CategoriesCard({ content, setContent }) {
  const rows = content.categories
  const update = (i, patch) => setContent((c) => ({ ...c, categories: c.categories.map((r, idx) => (idx === i ? { ...r, ...patch } : r)) }))
  const add = () => { if (rows.length < 20) setContent((c) => ({ ...c, categories: [...c.categories, { name: '', teaser: '' }] })) }
  const remove = (i) => setContent((c) => ({ ...c, categories: c.categories.filter((_, idx) => idx !== i) }))
  return (
    <Card>
      <SectionTitle title="Categories" right={<Button size="sm" variant="secondary" icon={Plus} onClick={add}>Add category</Button>} />
      {rows.length === 0 ? <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>No categories yet.</p> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {rows.map((r, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <Field label="Name" style={{ flex: 1, minWidth: 140 }}><input style={INPUT} value={r.name} onChange={(e) => update(i, { name: e.target.value })} /></Field>
              <Field label="Teaser" style={{ flex: 2, minWidth: 160 }}><input style={INPUT} value={r.teaser} onChange={(e) => update(i, { teaser: e.target.value })} /></Field>
              <Button size="sm" variant="danger" icon={Trash2} onClick={() => remove(i)}>Remove</Button>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}""",
"""function CategoriesCard({ content, setContent, defaultOpen }) {
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
}""",
"CategoriesCard")

# 11. ReviewsCard
apply(
"""function ReviewsCard({ content, setContent }) {
  const rows = content.reviews
  const update = (i, patch) => setContent((c) => ({ ...c, reviews: c.reviews.map((r, idx) => (idx === i ? { ...r, ...patch } : r)) }))
  const add = () => { if (rows.length < 20) setContent((c) => ({ ...c, reviews: [...c.reviews, { text: '', who: '' }] })) }
  const remove = (i) => setContent((c) => ({ ...c, reviews: c.reviews.filter((_, idx) => idx !== i) }))
  return (
    <Card>
      <SectionTitle title="Reviews" hint="Only ever your own words — never invented."
        right={<Button size="sm" variant="secondary" icon={Plus} onClick={add}>Add review</Button>} />
      {rows.length === 0 ? <p style={{ margin: 0, fontSize: 12.5, color: T.muted }}>No reviews yet.</p> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {rows.map((r, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <Field label="Review text" style={{ flex: 2, minWidth: 200 }}><input style={INPUT} value={r.text} onChange={(e) => update(i, { text: e.target.value })} /></Field>
              <Field label="Who" style={{ flex: 1, minWidth: 120 }}><input style={INPUT} value={r.who} onChange={(e) => update(i, { who: e.target.value })} /></Field>
              <Button size="sm" variant="danger" icon={Trash2} onClick={() => remove(i)}>Remove</Button>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}""",
"""function ReviewsCard({ content, setContent, defaultOpen }) {
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
}""",
"ReviewsCard")

# 12. HoursLocationCard
apply(
"""function HoursLocationCard({ content, setContent }) {
  const hours = content.hours
  const loc = content.location
  const updateHour = (i, patch) => setContent((c) => ({ ...c, hours: c.hours.map((r, idx) => (idx === i ? { ...r, ...patch } : r)) }))
  const addHour = () => { if (hours.length < 7) setContent((c) => ({ ...c, hours: [...c.hours, { days: '', time: '' }] })) }
  const removeHour = (i) => setContent((c) => ({ ...c, hours: c.hours.filter((_, idx) => idx !== i) }))
  const setLoc = (k) => (e) => setContent((c) => ({ ...c, location: { ...c.location, [k]: e.target.value } }))

  return (
    <Card>
      <SectionTitle title="Hours & location" right={hours.length < 7 && <Button size="sm" variant="secondary" icon={Plus} onClick={addHour}>Add hours row</Button>} />
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
    </Card>
  )
}""",
"""function HoursLocationCard({ content, setContent, defaultOpen }) {
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
}""",
"HoursLocationCard")

# 13. OrderSeoCard
apply(
"""function OrderSeoCard({ content, setContent }) {
  const o = content.order_section
  const seo = content.seo
  return (
    <Card>
      <SectionTitle title="How to order & SEO" />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="Order section title"><input style={INPUT} value={o.title}
          onChange={(e) => setContent((c) => ({ ...c, order_section: { ...c.order_section, title: e.target.value } }))} /></Field>
        <Field label="Steps" hint="One per line, up to 6">
          <textarea style={TEXTAREA} value={o.steps.join('\\n')}
            onChange={(e) => setContent((c) => ({ ...c, order_section: { ...c.order_section, steps: e.target.value.split('\\n').slice(0, 6) } }))} />
        </Field>
        <Field label="SEO title"><input style={INPUT} value={seo.title}
          onChange={(e) => setContent((c) => ({ ...c, seo: { ...c.seo, title: e.target.value } }))} /></Field>
        <Field label="SEO description"><input style={INPUT} value={seo.description}
          onChange={(e) => setContent((c) => ({ ...c, seo: { ...c.seo, description: e.target.value } }))} /></Field>
      </div>
    </Card>
  )
}""",
"""function OrderSeoCard({ content, setContent, defaultOpen }) {
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
            <textarea style={TEXTAREA} value={o.steps.join('\\n')}
              onChange={(e) => setContent((c) => ({ ...c, order_section: { ...c.order_section, steps: e.target.value.split('\\n').slice(0, 6) } }))} />
          </Field>
          <Field label="SEO title"><input style={INPUT} value={seo.title}
            onChange={(e) => setContent((c) => ({ ...c, seo: { ...c.seo, title: e.target.value } }))} /></Field>
          <Field label="SEO description"><input style={INPUT} value={seo.description}
            onChange={(e) => setContent((c) => ({ ...c, seo: { ...c.seo, description: e.target.value } }))} /></Field>
        </div>
      )}
    </Card>
  )
}""",
"OrderSeoCard")

# 14. DesignCard
apply(
"""function DesignCard({ recipe, setRecipe }) {
  const sections = Object.keys(SECTION_LABELS)
  const toggleHidden = (key) => setRecipe((r) => ({
    ...r, hidden: r.hidden.includes(key) ? r.hidden.filter((x) => x !== key) : [...r.hidden, key],
  }))

  return (
    <Card>
      <SectionTitle title="Design" hint="Theme and colour palette. Uncheck a section to hide it without losing its content." />
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
    </Card>
  )
}""",
"""function DesignCard({ recipe, setRecipe, defaultOpen }) {
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
}""",
"DesignCard")

with io.open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("ALL OK - 14 edits applied")
