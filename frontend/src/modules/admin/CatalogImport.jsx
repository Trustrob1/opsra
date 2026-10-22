/**
 * frontend/src/modules/admin/CatalogImport.jsx
 * STORE-10: add many products from a spreadsheet. Pick a file -> see exactly what will happen -> add them.
 * Photo links in the sheet are fetched one at a time with a progress count. Nothing is added until the owner says so.
 */
import { useRef, useState } from 'react'
import { ds } from '../../utils/ds'
import * as adminSvc from '../../services/admin.service'
import CatalogDialog from './CatalogDialog'
import { catalogErrorText } from './catalogErrors'
import { previewSummary, statusView, photoJobs, runPool, finishedSummary, withoutPhotos } from './catalogImportLogic'

const BTN = { minHeight: 48, padding: '0 20px', border: 'none', borderRadius: 12, background: ds.teal, color: 'white', fontFamily: ds.fontDm, fontSize: 14, fontWeight: 700, cursor: 'pointer' }
const GHOST = { minHeight: 48, padding: '0 18px', border: '1px solid #14181B', borderRadius: 12, background: 'white', color: '#14181B', fontFamily: ds.fontDm, fontSize: 14, fontWeight: 700, cursor: 'pointer' }
const P = { fontFamily: ds.fontDm, fontSize: 13.5, lineHeight: 1.55, color: '#3A3F44', margin: '0 0 10px' }
const TONE = { good: '#1B6B3A', muted: '#5C6166', bad: '#B3261E' }

export default function CatalogImport({ onClose, onDone, onAddPhotos }) {
  const [step, setStep] = useState('pick')
  const [file, setFile] = useState(null)
  const [plan, setPlan] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [result, setResult] = useState(null)
  const input = useRef(null)

  async function download() {
    try {
      const text = await adminSvc.getCatalogImportTemplate()
      const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
      const a = document.createElement('a')
      a.href = url; a.download = 'opsra-products-template.csv'
      document.body.appendChild(a); a.click(); a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) { setError(catalogErrorText(e, 'Could not download the template. Please try again.')) }
  }

  async function choose(e) {
    const f = e.target.files && e.target.files[0]
    e.target.value = ''
    if (!f) return
    setError(''); setBusy(true); setFile(f)
    try {
      setPlan(await adminSvc.previewCatalogImport(f))
      setStep('review')
    } catch (err) {
      setError(catalogErrorText(err, 'Could not read that file. Please check it and try again.'))
    } finally { setBusy(false) }
  }

  async function addThem() {
    setStep('working'); setError(''); setProgress('Adding your products…')
    let created = [], failed = [], categoriesAdded = []
    try {
      const r = await adminSvc.importCatalogProducts(file)
      created = r.created || []; failed = r.failed || []; categoriesAdded = r.categories_added || []
    } catch (err) {
      setError(catalogErrorText(err, 'Could not add the products. Nothing was changed. Please try again.'))
      setStep('review')
      return
    }
    const jobs = photoJobs(created)
    let results = []
    if (jobs.length) {
      setProgress(`Adding photos: 0 of ${jobs.length}`)
      results = await runPool(jobs, 3, async (j) => {
        try { await adminSvc.addCatalogImageFromUrl(j.itemId, j.url); return { ok: true } } catch (err) {
          return { ok: false, message: catalogErrorText(err, 'We could not download that picture.') }
        }
      }, (d, t) => setProgress(`Adding photos: ${d} of ${t}`))
    }
    const photoFailures = jobs.map((j, i) => ({ ...j, ...(results[i] || {}) })).filter((j) => !j.ok)
    setResult({
      created, failed, categoriesAdded, photoFailures,
      photosOk: jobs.length - photoFailures.length, photosFailed: photoFailures.length,
      needPhotos: withoutPhotos(created, results),
    })
    setStep('done')
    if (onDone) onDone()
  }

  const working = step === 'working'
  const counts = plan && plan.counts
  let footer = null
  if (step === 'pick') footer = <button style={GHOST} onClick={onClose}>Cancel</button>
  if (step === 'review') footer = (
    <>
      <button style={GHOST} onClick={() => { setStep('pick'); setPlan(null); setFile(null); setError('') }}>Choose another file</button>
      <button style={{ ...BTN, opacity: counts && counts.ok ? 1 : 0.5 }} disabled={!counts || !counts.ok} onClick={addThem}>
        {counts && counts.ok ? `Add ${counts.ok} ${counts.ok === 1 ? 'product' : 'products'}` : 'Nothing to add'}
      </button>
    </>
  )
  if (step === 'done') footer = (
    <>
      {result && result.needPhotos.length > 0 && onAddPhotos && <button style={GHOST} onClick={() => { onClose(); onAddPhotos() }}>Add photos in bulk</button>}
      <button style={BTN} onClick={onClose}>Done</button>
    </>
  )

  return (
    <CatalogDialog title="Add products from a spreadsheet" onClose={onClose} locked={working} footer={footer}>
      {step === 'pick' && (
        <div>
          <p style={P}>Make a spreadsheet with one product per row. Excel (.xlsx) and CSV files both work. Only <b>Title</b> is required.</p>
          <ul style={{ ...P, paddingLeft: 20 }}>
            <li><b>Title</b>, <b>Price</b>, <b>Description</b></li>
            <li><b>Category</b>: more than one is fine, separated by commas</li>
            <li><b>Sizes</b>: like <code>Single=120000; Queen=180000</code>, or just <code>Single, Queen</code> to use the product price</li>
            <li><b>Photos</b>: web links starting with https:// (optional). You can also add photos afterwards by dropping a folder of pictures named after your products.</li>
            <li><b>In stock</b>: yes or no (empty means yes)</li>
          </ul>
          <p style={P}>You will see exactly what will happen before anything is added. Products that already exist are never duplicated or changed.</p>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 16 }}>
            <button style={GHOST} onClick={download}>Download the template</button>
            <button style={BTN} disabled={busy} onClick={() => input.current && input.current.click()}>{busy ? 'Reading your file…' : 'Choose your file'}</button>
            <input ref={input} type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={choose} aria-label="Spreadsheet file" style={{ display: 'none' }} />
          </div>
        </div>
      )}

      {step === 'review' && plan && (
        <div>
          <p style={{ ...P, fontWeight: 700, color: '#0a1a24', fontSize: 15 }}>{previewSummary(plan.counts)}</p>
          {plan.categories.length > 0 && <p style={P}>Categories used: {plan.categories.join(', ')}. Any that you do not have yet will be created.</p>}
          {plan.photo_links > 0 && <p style={P}>{plan.photo_links} photo {plan.photo_links === 1 ? 'link' : 'links'} will be downloaded after the products are added.</p>}
          {plan.unknown.length > 0 && <p style={{ ...P, color: '#5C6166' }}>Columns we did not use: {plan.unknown.join(', ')}.</p>}
          <div style={{ overflowX: 'auto', border: '1px solid #E6E4DF', borderRadius: 12 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: ds.fontDm, fontSize: 13 }}>
              <thead><tr style={{ textAlign: 'left', color: '#5C6166', background: '#F7F6F3' }}>
                {['Row', 'Product', 'Price', 'Sizes', 'Categories', 'Photos', 'What happens'].map((h) => <th key={h} style={{ padding: '8px 10px', fontWeight: 700, whiteSpace: 'nowrap' }}>{h}</th>)}
              </tr></thead>
              <tbody>{plan.rows.map((r) => {
                const sv = statusView(r.status)
                return (
                  <tr key={r.row} style={{ borderTop: '1px solid #E6E4DF', verticalAlign: 'top' }}>
                    <td style={{ padding: '8px 10px', color: '#5C6166' }}>{r.row}</td>
                    <td style={{ padding: '8px 10px', fontWeight: 600 }}>{r.title || '(no title)'}</td>
                    <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>{r.price != null ? `₦${Number(r.price).toLocaleString()}` : '—'}</td>
                    <td style={{ padding: '8px 10px' }}>{r.sizes.length || '—'}</td>
                    <td style={{ padding: '8px 10px' }}>{r.categories.join(', ') || '—'}</td>
                    <td style={{ padding: '8px 10px' }}>{r.photos.length || '—'}</td>
                    <td style={{ padding: '8px 10px', color: TONE[sv.tone] }}>
                      <b>{sv.label}</b>
                      {[...r.problems, ...r.notes].map((m, i) => <div key={i} style={{ fontSize: 12, color: r.problems.includes(m) ? '#B3261E' : '#5C6166' }}>{m}</div>)}
                    </td>
                  </tr>)
              })}</tbody>
            </table>
          </div>
        </div>
      )}

      {step === 'working' && <p role="status" style={{ ...P, fontSize: 15, fontWeight: 700 }}>{progress}</p>}

      {step === 'done' && result && (
        <div>
          {finishedSummary(result).map((l) => <p key={l} style={{ ...P, fontSize: 15, fontWeight: 600, color: '#0a1a24' }}>{l}</p>)}
          {result.failed.length > 0 && (
            <div><p style={{ ...P, fontWeight: 700 }}>Not added:</p>
              {result.failed.map((f) => <p key={f.row} style={{ ...P, color: '#B3261E', margin: '0 0 4px' }}>Row {f.row}, {f.title}: {f.message}</p>)}</div>
          )}
          {result.photoFailures.length > 0 && (
            <div style={{ marginTop: 10 }}><p style={{ ...P, fontWeight: 700 }}>Photo links that did not work:</p>
              {result.photoFailures.map((f, i) => <p key={i} style={{ ...P, margin: '0 0 6px' }}><b>{f.title}</b>: {f.message}<br /><span style={{ color: '#5C6166', wordBreak: 'break-all' }}>{f.url}</span></p>)}</div>
          )}
          {result.needPhotos.length > 0 && <p style={{ ...P, marginTop: 12 }}>{result.needPhotos.length} {result.needPhotos.length === 1 ? 'product has' : 'products have'} no photo yet. You can add them in bulk by dropping a folder of pictures.</p>}
        </div>
      )}

      {error && <p role="alert" style={{ ...P, color: '#B3261E', marginTop: 14 }}>{error}</p>}
    </CatalogDialog>
  )
}
