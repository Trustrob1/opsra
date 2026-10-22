/**
 * frontend/src/modules/admin/CatalogPhotoDrop.jsx
 * STORE-12: add photos to many products at once. Pick (or drop) pictures named after your products, check the
 * matches, place any that did not match by hand, then upload. Nothing is uploaded until the owner says so.
 */
import { useMemo, useRef, useState } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'
import CatalogDialog from './CatalogDialog'
import { catalogErrorText } from './catalogErrors'
import { matchPhotos, photoCount } from './photoMatch'
import { runPool } from './catalogImportLogic'
import { shrinkImage } from './imageShrink'

const BTN = { minHeight: 48, padding: '0 20px', border: 'none', borderRadius: 12, background: ds.teal, color: 'white', fontFamily: ds.fontDm, fontSize: 14, fontWeight: 700, cursor: 'pointer' }
const GHOST = { minHeight: 48, padding: '0 18px', border: '1px solid #14181B', borderRadius: 12, background: 'white', color: '#14181B', fontFamily: ds.fontDm, fontSize: 14, fontWeight: 700, cursor: 'pointer' }
const P = { fontFamily: ds.fontDm, fontSize: 13.5, lineHeight: 1.55, color: '#3A3F44', margin: '0 0 10px' }
const H = { fontFamily: ds.fontDm, fontSize: 14, fontWeight: 800, color: '#0a1a24', margin: '18px 0 8px' }
const SELECT = { minHeight: 44, padding: '0 10px', borderRadius: 10, border: '1px solid #C9C6BF', fontFamily: ds.fontDm, fontSize: 13.5, background: 'white', maxWidth: '100%' }

export default function CatalogPhotoDrop({ items, onClose, onDone }) {
  const [step, setStep] = useState('pick')
  const [files, setFiles] = useState([])
  const [placed, setPlaced] = useState({})
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [progress, setProgress] = useState('')
  const [result, setResult] = useState(null)
  const filesInput = useRef(null)
  const folderInput = useRef(null)

  const sorted = useMemo(() => [...(items || [])].sort((a, b) => String(a.title).localeCompare(String(b.title))), [items])
  const matched = useMemo(() => matchPhotos(files, items, placed), [files, items, placed])
  const total = photoCount(matched)

  async function take(list) {
    const picked = [...list]
    if (!picked.length) return
    setError(''); setBusy('Preparing your pictures…')
    const prepared = []
    for (const f of picked) prepared.push(await shrinkImage(f))        // big phone photos are made smaller first
    setFiles(prepared); setPlaced({}); setBusy(''); setStep('review')
  }
  const onPick = (e) => { const l = e.target.files || []; take(l); e.target.value = '' }
  const onDrop = (e) => { e.preventDefault(); take(e.dataTransfer.files || []) }

  async function upload() {
    setStep('working'); setError('')
    const groups = matched.matched
    const all = groups.reduce((n, g) => n + g.files.length, 0)
    let done = 0
    setProgress(`Uploading photos: 0 of ${all}`)
    const results = await runPool(groups, 3, async (g) => {
      const out = { item: g.item, ok: 0, failed: [] }
      for (const f of g.files) {                                          // one product's pictures go up in order, so the first is its cover
        try {
          const form = new FormData(); form.append('file', f.file)
          await adminSvc.uploadCatalogImage(g.item.id, form)
          out.ok += 1
        } catch (err) {
          out.failed.push({ name: f.file.name, message: catalogErrorText(err, 'Upload failed.') })
        }
        done += 1
        setProgress(`Uploading photos: ${done} of ${all}`)
      }
      return out
    })
    setResult({
      ok: results.reduce((n, r) => n + (r.ok || 0), 0),
      failed: results.flatMap((r) => (r.failed || []).map((f) => ({ ...f, title: r.item && r.item.title }))),
      products: results.filter((r) => r.ok).length,
    })
    setStep('done')
    if (onDone) onDone()
  }

  const working = step === 'working'
  let footer = <button style={GHOST} onClick={onClose}>Cancel</button>
  if (step === 'review') footer = (
    <>
      <button style={GHOST} onClick={() => { setStep('pick'); setFiles([]); setPlaced({}) }}>Start again</button>
      <button style={{ ...BTN, opacity: total ? 1 : 0.5 }} disabled={!total} onClick={upload}>{total ? `Upload ${total} ${total === 1 ? 'photo' : 'photos'}` : 'Nothing to upload'}</button>
    </>
  )
  if (step === 'done') footer = <button style={BTN} onClick={onClose}>Done</button>
  if (working) footer = null

  return (
    <CatalogDialog title="Add photos in bulk" onClose={onClose} locked={working} footer={footer}>
      {step === 'pick' && (
        <div>
          <p style={P}>Name each picture after its product, for example <code>cloud-9-mattress.jpg</code>. Extra pictures of the same product end with a number: <code>cloud-9-mattress-2.jpg</code>, <code>cloud-9-mattress-3.jpg</code>. Capitals and spaces do not matter.</p>
          <p style={P}>JPEG, PNG or WebP. Big phone photos are made smaller for you. Pictures that do not match a product are listed so you can place them yourself.</p>
          <div onDragOver={(e) => e.preventDefault()} onDrop={onDrop} style={{
            marginTop: 14, border: '2px dashed #C9C6BF', borderRadius: 14, padding: '28px 16px', textAlign: 'center', fontFamily: ds.fontDm, color: '#5C6166',
          }}>
            <div style={{ marginBottom: 14, fontSize: 14 }}>{busy || 'Drop pictures here, or'}</div>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
              <button style={BTN} disabled={!!busy} onClick={() => filesInput.current && filesInput.current.click()}>Choose pictures</button>
              <button style={GHOST} disabled={!!busy} onClick={() => folderInput.current && folderInput.current.click()}>Choose a folder</button>
            </div>
            <input ref={filesInput} type="file" multiple accept="image/*" onChange={onPick} aria-label="Pictures" style={{ display: 'none' }} />
            <input ref={folderInput} type="file" multiple webkitdirectory="" directory="" onChange={onPick} aria-label="Folder of pictures" style={{ display: 'none' }} />
          </div>
        </div>
      )}

      {step === 'review' && (
        <div>
          <p style={{ ...P, fontWeight: 700, color: '#0a1a24', fontSize: 15 }}>
            {total} of {files.length} {files.length === 1 ? 'picture' : 'pictures'} matched to {matched.matched.length} {matched.matched.length === 1 ? 'product' : 'products'}.
          </p>
          {matched.matched.length > 0 && (
            <>
              <h3 style={H}>Matched</h3>
              {matched.matched.map((g) => {
                const had = (g.item.catalog_images || []).length
                return (
                  <div key={g.item.id} style={{ padding: '10px 0', borderTop: '1px solid #E6E4DF', fontFamily: ds.fontDm, fontSize: 13.5 }}>
                    <b>{g.item.title}</b>{had > 0 && <span style={{ color: '#5C6166' }}> (already has {had}; these are added after)</span>}
                    <div style={{ color: '#5C6166', marginTop: 4 }}>{g.files.map((f) => f.file.name).join(', ')}</div>
                  </div>)
              })}
            </>
          )}
          {matched.unmatched.length > 0 && (
            <>
              <h3 style={H}>Needs a product</h3>
              {matched.unmatched.map((u) => (
                <div key={u.pos} style={{ padding: '10px 0', borderTop: '1px solid #E6E4DF', fontFamily: ds.fontDm, fontSize: 13.5, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={{ flex: '1 1 180px', minWidth: 0, wordBreak: 'break-all' }}>
                    {u.file.name}<span style={{ color: '#5C6166' }}> {u.reason === 'several' ? '(matches more than one product)' : '(no product with this name)'}</span>
                  </span>
                  <select aria-label={`Product for ${u.file.name}`} value="" style={SELECT} onChange={(e) => e.target.value && setPlaced((p) => ({ ...p, [u.pos]: e.target.value }))}>
                    <option value="">Choose a product…</option>
                    {sorted.map((it) => <option key={it.id} value={it.id}>{it.title}</option>)}
                  </select>
                </div>))}
              <p style={{ ...P, marginTop: 8 }}>Pictures you leave here will not be uploaded.</p>
            </>
          )}
          {matched.problems.length > 0 && (
            <>
              <h3 style={H}>Cannot be used</h3>
              {matched.problems.map((p, i) => <p key={i} style={{ ...P, margin: '0 0 6px', color: '#B3261E' }}><b>{p.file.name}</b>: {p.message}</p>)}
            </>
          )}
        </div>
      )}

      {working && <p role="status" style={{ ...P, fontSize: 15, fontWeight: 700 }}>{progress}</p>}

      {step === 'done' && result && (
        <div>
          <p style={{ ...P, fontSize: 15, fontWeight: 600, color: '#0a1a24' }}>
            {result.ok} {result.ok === 1 ? 'photo was' : 'photos were'} added to {result.products} {result.products === 1 ? 'product' : 'products'}.
          </p>
          {result.failed.length > 0 && (
            <div><p style={{ ...P, fontWeight: 700 }}>These did not upload:</p>
              {result.failed.map((f, i) => <p key={i} style={{ ...P, margin: '0 0 6px', color: '#B3261E' }}><b>{f.title}</b>, {f.name}: {f.message}</p>)}</div>
          )}
        </div>
      )}

      {error && <p role="alert" style={{ ...P, color: '#B3261E', marginTop: 14 }}>{error}</p>}
    </CatalogDialog>
  )
}
