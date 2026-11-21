import io

path = "BuilderPortalPage.jsx"
with io.open(path, "r", encoding="utf-8") as f:
    content = f.read()

old3 = '''  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <BackLink onBack={onBack} />
      <header style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <h1 style={{ margin: 0, fontSize: 19, fontWeight: 700, color: T.ink }}>{site.client_business_name}</h1>
        <Badge tone={st.tone}>{st.label}</Badge>
      </header>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Button variant="secondary" icon={Eye} onClick={() => setPreviewOpen(true)} disabled={!site.rendered_html}>
          {site.rendered_html ? 'View preview' : 'Render to preview'}
        </Button>
        <Button variant="secondary" icon={ExternalLink} onClick={() => window.open(previewUrl, '_blank', 'noopener')} disabled={!site.rendered_html}>
          Open live preview
        </Button>
        <Button variant="primary" icon={RefreshCw} loading={rendering} onClick={doRender}>Render preview</Button>
        <Button variant="secondary" icon={Undo2} loading={undoing} onClick={doUndo}>Undo last change</Button>
      </div>
      <p style={{ margin: 0, fontSize: 11.5, color: T.muted }}>
        {site.updated_at ? `Last saved ${dateTime(site.updated_at)}` : null}
      </p>

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

      <Modal open={previewOpen} onClose={() => setPreviewOpen(false)} title="Preview" width={420}>
        {site.rendered_html
          ? <iframe title="Site preview" srcDoc={site.rendered_html} style={{ width: '100%', height: '70vh', border: `1px solid ${T.line}`, borderRadius: 8 }} />
          : <p style={{ fontSize: 13, color: T.muted }}>Render the preview first.</p>}
      </Modal>
    </div>
  )
}'''

new3 = '''  return (
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
        .bp-pane[data-active="false"]{display:none}
        .bp-preview-pane{border:1px solid ${T.line};border-radius:10px;overflow:hidden;background:#fff}
        .bp-preview-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;border-bottom:1px solid ${T.line}}
        .bp-preview-frame-wrap{height:62vh;overflow:auto;background:#F6F8F9}
        .bp-mobile-tabs{display:block}
        @media (min-width:980px){
          .bp-editor-shell{display:grid;grid-template-columns:minmax(380px,1fr) minmax(360px,480px);align-items:start;gap:24px}
          .bp-mobile-tabs{display:none}
          .bp-pane[data-active="false"]{display:block}
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
      </div>
      <p style={{ margin: 0, fontSize: 11.5, color: T.muted }}>
        {site.updated_at ? `Last saved ${dateTime(site.updated_at)}` : null}
      </p>

      <div className="bp-mobile-tabs">
        <Segmented value={mobileTab} onChange={setMobileTab}
          options={[{ value: 'edit', label: 'Edit' }, { value: 'preview', label: 'Preview' }]} ariaLabel="Edit or preview" />
      </div>

      <div className="bp-editor-shell" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
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
}'''

assert content.count(old3) == 1, "return-block: %d matches" % content.count(old3)
content = content.replace(old3, new3)

with io.open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("OK - part 2/2 done")
