/**
 * frontend/src/modules/admin/SalesLog.jsx
 * Quick Sales Log + Bulk Import — GPM-1E (watermark update).
 *
 * Changes from previous version:
 *   - Preview table has checkbox column (valid rows pre-checked, error rows disabled)
 *   - Select all / deselect all header checkbox
 *   - Duplicate rows unchecked by default, shown in separate collapsible section
 *   - Already-imported rows (behind watermark) unchecked by default, shown in
 *     separate collapsible section with "Import from beginning" override
 *   - Watermark date badge shown on both import cards
 *   - Confirm sends only checked row indices
 *   - Reset watermark button per card
 *
 * Pattern 50: all API calls via growth.service.js (axios + _h()).
 * Pattern 51: full rewrite required for any future edit — never sed.
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { ds } from '../../utils/ds'
import * as growthSvc from '../../services/growth.service'

// ---------------------------------------------------------------------------
// Constants + helpers
// ---------------------------------------------------------------------------
const TODAY = new Date().toISOString().slice(0, 10)

const CHANNEL_OPTIONS = [
  { value: 'phone_call', label: 'Phone Call' },
  { value: 'walk_in',    label: 'Walk-in' },
  { value: 'referral',   label: 'Referral' },
  { value: 'whatsapp',   label: 'WhatsApp' },
  { value: 'other',      label: 'Other' },
]

const IMPORT_COLUMNS = ['customer_name', 'phone', 'region', 'amount', 'sale_date', 'channel', 'source_team', 'notes']

function fmt(amount) {
  return Number(amount).toLocaleString('en-NG', { minimumFractionDigits: 2 })
}

function sourceLabel(src) {
  if (src === 'excel')  return { label: 'Excel',  bg: '#E8F5E9', color: '#2E7D32' }
  if (src === 'sheets') return { label: 'Sheets', bg: '#E3F2FD', color: '#1565C0' }
  return                        { label: 'Manual', bg: '#F3F4F6', color: '#4B5563' }
}

const inputStyle = {
  width: '100%', padding: '8px 10px', border: '1px solid #C8DDE6', borderRadius: 6,
  fontSize: 13.5, fontFamily: ds.fontDm, color: '#0a1a24', background: 'white',
  boxSizing: 'border-box', outline: 'none',
}

// ---------------------------------------------------------------------------
// Shared UI primitives
// ---------------------------------------------------------------------------
function SectionCard({ title, children, action }) {
  return (
    <div style={{ background: 'white', borderRadius: 10, border: '1px solid #E2EFF4', marginBottom: 28, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', borderBottom: '1px solid #E2EFF4', background: '#F8FBFC' }}>
        <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#0a1a24', margin: 0 }}>{title}</h3>
        {action}
      </div>
      <div style={{ padding: 20 }}>{children}</div>
    </div>
  )
}

function Field({ label, required, children }) {
  return (
    <div>
      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#4a7a8a', marginBottom: 4 }}>
        {label}{required && <span style={{ color: '#E53E3E' }}> *</span>}
      </label>
      {children}
    </div>
  )
}

function WatermarkBadge({ date, onReset, loading }) {
  if (!date) return null
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10,
      background: '#EFF6FF', border: '1px solid #BFDBFE', borderRadius: 6, padding: '7px 12px', fontSize: 12 }}>
      <span style={{ color: '#1D4ED8' }}>
        📅 Last imported up to <strong>{date}</strong>. Only rows after this date will be shown.
      </span>
      <button onClick={onReset} disabled={loading} style={{
        marginLeft: 'auto', fontSize: 11, color: '#DC2626', background: 'none',
        border: 'none', cursor: 'pointer', textDecoration: 'underline', padding: 0,
      }}>
        Reset
      </button>
    </div>
  )
}

function Collapsible({ title, count, color = '#D69E2E', bg = '#FFFDE7', children }) {
  const [open, setOpen] = useState(false)
  if (count === 0) return null
  return (
    <div style={{ border: `1px solid ${color}`, borderRadius: 6, marginTop: 12, overflow: 'hidden' }}>
      <button onClick={() => setOpen(o => !o)} style={{
        width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '8px 12px', background: bg, border: 'none', cursor: 'pointer',
        fontFamily: ds.fontDm, fontSize: 13, fontWeight: 600, color: '#78350F',
      }}>
        <span>{title} ({count})</span>
        <span>{open ? '▲' : '▼'}</span>
      </button>
      {open && <div style={{ padding: 12, background: 'white' }}>{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// CheckboxPreviewTable — used by both import cards
// ---------------------------------------------------------------------------
function CheckboxPreviewTable({ validRows, errorRows, checkedSet, onToggle, onToggleAll, dupRowNums, alreadyRowNums }) {
  const allChecked = validRows.length > 0 && validRows.every((_, i) => checkedSet.has(i))
  const someChecked = validRows.some((_, i) => checkedSet.has(i))

  return (
    <div style={{ overflowX: 'auto', marginTop: 10 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ background: '#F0F7FA' }}>
            <th style={{ padding: '6px 8px', borderBottom: '1px solid #C8DDE6', width: 32 }}>
              <input
                type="checkbox"
                checked={allChecked}
                ref={el => { if (el) el.indeterminate = someChecked && !allChecked }}
                onChange={() => onToggleAll(!allChecked)}
              />
            </th>
            {['#', 'Customer', 'Phone', 'Amount', 'Date', 'Channel'].map(h => (
              <th key={h} style={{ padding: '6px 8px', textAlign: 'left', color: '#4a7a8a', fontWeight: 600, borderBottom: '1px solid #C8DDE6' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {validRows.map((r, i) => {
            const isDup      = dupRowNums.has(r._row_num)
            const isAlready  = alreadyRowNums.has(r._row_num)
            const isChecked  = checkedSet.has(i)
            let bg = 'white'
            if (isDup)     bg = '#FFFDE7'
            if (isAlready) bg = '#EFF6FF'
            return (
              <tr key={i} style={{ background: bg, borderBottom: '1px solid #E2EFF4', opacity: isChecked ? 1 : 0.55 }}>
                <td style={{ padding: '5px 8px', textAlign: 'center' }}>
                  <input type="checkbox" checked={isChecked} onChange={() => onToggle(i)} />
                </td>
                <td style={{ padding: '5px 8px', color: '#7A9BAD' }}>{r._row_num || i + 2}</td>
                <td style={{ padding: '5px 8px' }}>{r.customer_name || '—'}</td>
                <td style={{ padding: '5px 8px', color: '#7A9BAD' }}>{r.phone || '—'}</td>
                <td style={{ padding: '5px 8px', fontWeight: 600 }}>{r.amount != null ? fmt(r.amount) : '—'}</td>
                <td style={{ padding: '5px 8px' }}>{r.sale_date || '—'}</td>
                <td style={{ padding: '5px 8px', color: '#7A9BAD' }}>{r.channel || '—'}</td>
              </tr>
            )
          })}
          {errorRows.map((e, i) => (
            <tr key={`err-${i}`} style={{ background: '#FFF5F5', borderBottom: '1px solid #E2EFF4' }}>
              <td style={{ padding: '5px 8px', textAlign: 'center' }}>
                <input type="checkbox" disabled checked={false} />
              </td>
              <td style={{ padding: '5px 8px', color: '#E53E3E' }}>{e.row}</td>
              <td colSpan={5} style={{ padding: '5px 8px', color: '#E53E3E', fontStyle: 'italic' }}>⚠ {e.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// useImportState — shared logic for both import cards
// ---------------------------------------------------------------------------
function useImportState() {
  const [preview, setPreview]           = useState(null)
  const [checkedSet, setCheckedSet]     = useState(new Set())
  const [result, setResult]             = useState(null)
  const [loading, setLoading]           = useState(false)
  const [error, setError]               = useState('')
  const [fromBeginning, setFromBeginning] = useState(false)

  function setPreviewData(data) {
    const rows = data.preview || []
    // Attach _row_num to each row for cross-referencing with warnings
    const dupNums = new Set((data.duplicate_warnings || []).map(d => d.row))
    const alrNums = new Set((data.already_imported || []).map(a => a.row))
    // Pre-check: valid rows that are NOT already_imported and NOT duplicates
    const initialChecked = new Set()
    rows.forEach((_, i) => {
      const rowNum = i + 2
      if (!dupNums.has(rowNum) && !alrNums.has(rowNum)) {
        initialChecked.add(i)
      }
    })
    setPreview({ ...data, rows })
    setCheckedSet(initialChecked)
  }

  function toggleRow(i) {
    setCheckedSet(prev => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i); else next.add(i)
      return next
    })
  }

  function toggleAll(checked) {
    if (!preview) return
    setCheckedSet(checked ? new Set(preview.rows.map((_, i) => i)) : new Set())
  }

  function reset() {
    setPreview(null); setCheckedSet(new Set()); setResult(null); setError('')
  }

  return {
    preview, setPreviewData,
    checkedSet, toggleRow, toggleAll,
    result, setResult,
    loading, setLoading,
    error, setError,
    fromBeginning, setFromBeginning,
    reset,
  }
}

// ---------------------------------------------------------------------------
// Section 1 — Quick Sale Entry
// ---------------------------------------------------------------------------
function QuickSaleForm({ teams, onSaleLogged }) {
  const blank = { customer_name: '', phone: '', region: '', amount: '', sale_date: TODAY, channel: 'other', source_team: '', notes: '' }
  const [form, setForm]   = useState(blank)
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState('')
  const [flash, setFlash]   = useState(false)

  function set(k, v) { setForm(f => ({ ...f, [k]: v })) }

  async function handleSubmit() {
    if (!form.customer_name.trim()) return setError('Customer name is required.')
    if (!form.phone.trim())         return setError('Phone is required.')
    if (!form.region.trim())        return setError('Region / Area is required.')
    if (!form.amount || isNaN(Number(form.amount)) || Number(form.amount) <= 0)
      return setError('A valid amount is required.')
    if (!form.sale_date) return setError('Sale date is required.')
    setError(''); setSaving(true)
    try {
      const newRow = await growthSvc.createDirectSale({
        customer_name: form.customer_name.trim(),
        phone:         form.phone.trim(),
        region:        form.region.trim(),
        amount:        parseFloat(form.amount),
        sale_date:     form.sale_date,
        channel:       form.channel,
        source_team:   form.source_team || null,
        notes:         form.notes.trim() || null,
        import_source: 'manual',
      })
      setForm(blank); setFlash(true)
      setTimeout(() => setFlash(false), 2500)
      onSaleLogged(newRow)
    } catch (err) {
      setError(err?.response?.data?.detail?.message || 'Failed to log sale.')
    } finally { setSaving(false) }
  }

  return (
    <SectionCard title="Log a Sale">
      {flash && (
        <div style={{ background: '#E6F9F0', border: '1px solid #68D391', borderRadius: 6, padding: '10px 14px', marginBottom: 14, color: '#276749', fontSize: 13.5, fontWeight: 600 }}>
          ✅ Sale logged!
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12, marginBottom: 12 }}>
        <Field label="Customer Name" required>
          <input style={inputStyle} value={form.customer_name} maxLength={255} onChange={e => set('customer_name', e.target.value)} placeholder="e.g. Emeka Okafor" />
        </Field>
        <Field label="Phone" required>
          <input style={inputStyle} type="tel" value={form.phone} maxLength={20} onChange={e => set('phone', e.target.value)} placeholder="e.g. 08012345678" />
        </Field>
        <Field label="Region / Area" required>
          <input style={inputStyle} value={form.region} maxLength={255} onChange={e => set('region', e.target.value)} placeholder="e.g. Ikeja, Lagos" />
        </Field>
        <Field label="Amount (NGN)" required>
          <input style={inputStyle} type="number" min="0" step="0.01" value={form.amount} onChange={e => set('amount', e.target.value)} placeholder="0.00" />
        </Field>
        <Field label="Sale Date" required>
          <input style={inputStyle} type="date" value={form.sale_date} onChange={e => set('sale_date', e.target.value)} />
        </Field>
        <Field label="Channel">
          <select style={inputStyle} value={form.channel} onChange={e => set('channel', e.target.value)}>
            {CHANNEL_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </Field>
        {teams.length > 0 && (
          <Field label="Source Team">
            <select style={inputStyle} value={form.source_team} onChange={e => set('source_team', e.target.value)}>
              <option value="">— None —</option>
              {teams.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}
            </select>
          </Field>
        )}
        <Field label="Notes">
          <input style={inputStyle} value={form.notes} onChange={e => set('notes', e.target.value)} placeholder="Optional note" />
        </Field>
      </div>
      {error && <p style={{ color: '#E53E3E', fontSize: 13, margin: '8px 0 0' }}>{error}</p>}
      <button onClick={handleSubmit} disabled={saving} style={{
        marginTop: 14, padding: '9px 22px', background: saving ? '#7A9BAD' : ds.teal,
        color: 'white', border: 'none', borderRadius: 6, cursor: saving ? 'not-allowed' : 'pointer',
        fontFamily: ds.fontDm, fontWeight: 600, fontSize: 14,
      }}>
        {saving ? 'Logging…' : 'Log Sale'}
      </button>
    </SectionCard>
  )
}

// ---------------------------------------------------------------------------
// ImportCard — shared by Excel and Sheets
// ---------------------------------------------------------------------------
function ImportCard({ title, watermarkDate, onResetWatermark, children, state }) {
  const { preview, checkedSet, toggleRow, toggleAll, result, loading, error, fromBeginning, setFromBeginning } = state

  const dupRowNums   = new Set((preview?.duplicate_warnings || []).map(d => d.row))
  const alrRowNums   = new Set((preview?.already_imported   || []).map(a => a.row))
  const checkedCount = checkedSet.size

  return (
    <div style={{ border: '1px solid #E2EFF4', borderRadius: 10, padding: 20, background: 'white', flex: 1, minWidth: 280 }}>
      <h4 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 14, color: '#0a1a24', margin: '0 0 12px' }}>{title}</h4>

      <WatermarkBadge date={watermarkDate} onReset={onResetWatermark} loading={loading} />

      {watermarkDate && (
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#4a7a8a', marginBottom: 10, cursor: 'pointer' }}>
          <input type="checkbox" checked={fromBeginning} onChange={e => setFromBeginning(e.target.checked)} />
          Import from beginning (override watermark)
        </label>
      )}

      {children}

      {loading && <p style={{ fontSize: 13, color: '#7A9BAD', marginTop: 8 }}>Processing…</p>}
      {error   && <p style={{ fontSize: 13, color: '#E53E3E', marginTop: 8 }}>{error}</p>}

      {result && (
        <div style={{ background: '#E6F9F0', border: '1px solid #68D391', borderRadius: 6, padding: '9px 12px', fontSize: 13, color: '#276749', fontWeight: 600, marginTop: 10 }}>
          ✅ {result.inserted} imported, {result.skipped} skipped
        </div>
      )}

      {preview && !result && (
        <>
          {/* Summary line */}
          <p style={{ fontSize: 13, color: '#4a7a8a', margin: '10px 0 0' }}>
            <strong>{preview.total_valid}</strong> rows ready
            {preview.errors?.length > 0 && <span style={{ color: '#E53E3E' }}> · {preview.errors.length} errors</span>}
            {preview.duplicate_warnings?.length > 0 && <span style={{ color: '#D69E2E' }}> · {preview.duplicate_warnings.length} possible duplicates</span>}
            {preview.already_imported?.length > 0 && <span style={{ color: '#1D4ED8' }}> · {preview.already_imported.length} already imported</span>}
          </p>

          {/* Preview table with checkboxes */}
          <CheckboxPreviewTable
            validRows={preview.rows}
            errorRows={preview.errors || []}
            checkedSet={checkedSet}
            onToggle={toggleRow}
            onToggleAll={toggleAll}
            dupRowNums={dupRowNums}
            alreadyRowNums={alrRowNums}
          />

          {/* Duplicates collapsible */}
          <Collapsible
            title="⚠ Possible Duplicates"
            count={preview.duplicate_warnings?.length || 0}
            color="#D69E2E" bg="#FFFDE7"
          >
            <p style={{ fontSize: 12, color: '#78350F', margin: '0 0 8px' }}>
              These rows match an existing record (same phone + date + amount). They are unchecked by default. Check any you want to import anyway.
            </p>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr>
                  {['Row', 'Phone', 'Date', 'Amount'].map(h => (
                    <th key={h} style={{ padding: '4px 8px', textAlign: 'left', color: '#78350F', borderBottom: '1px solid #FDE68A' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(preview.duplicate_warnings || []).map((d, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #FEF3C7' }}>
                    <td style={{ padding: '4px 8px' }}>{d.row}</td>
                    <td style={{ padding: '4px 8px' }}>{d.phone}</td>
                    <td style={{ padding: '4px 8px' }}>{d.sale_date}</td>
                    <td style={{ padding: '4px 8px' }}>{fmt(d.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Collapsible>

          {/* Already imported collapsible */}
          <Collapsible
            title="📅 Already Imported (behind watermark)"
            count={preview.already_imported?.length || 0}
            color="#93C5FD" bg="#EFF6FF"
          >
            <p style={{ fontSize: 12, color: '#1E40AF', margin: '0 0 8px' }}>
              These rows have a sale_date on or before the last import date. They are unchecked by default. Check "Import from beginning" above to include all of them, or check individual rows above.
            </p>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr>
                  {['Row', 'Customer', 'Date'].map(h => (
                    <th key={h} style={{ padding: '4px 8px', textAlign: 'left', color: '#1E40AF', borderBottom: '1px solid #BFDBFE' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(preview.already_imported || []).map((a, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #DBEAFE' }}>
                    <td style={{ padding: '4px 8px' }}>{a.row}</td>
                    <td style={{ padding: '4px 8px' }}>{a.customer}</td>
                    <td style={{ padding: '4px 8px' }}>{a.sale_date}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Collapsible>

          {/* Import button */}
          <button
            onClick={() => state.onConfirm([...checkedSet])}
            disabled={loading || checkedCount === 0}
            style={{
              marginTop: 14, padding: '8px 18px',
              background: checkedCount === 0 ? '#C8DDE6' : ds.teal,
              color: 'white', border: 'none', borderRadius: 6,
              cursor: checkedCount === 0 ? 'not-allowed' : 'pointer',
              fontFamily: ds.fontDm, fontWeight: 600, fontSize: 13.5,
            }}
          >
            {loading ? 'Importing…' : `Import ${checkedCount} row${checkedCount !== 1 ? 's' : ''}`}
          </button>
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section 2A — Excel Upload
// ---------------------------------------------------------------------------
function ExcelImportCard({ onImported }) {
  const state   = useImportState()
  const fileRef = useRef(null)
  const [watermarkDate, setWatermarkDate] = useState(null)

  function downloadTemplate() {
    const blob = new Blob([IMPORT_COLUMNS.join(',') + '\n'], { type: 'text/csv' })
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: 'sales_import_template.csv' })
    a.click(); URL.revokeObjectURL(a.href)
  }

  async function handleFileChange(e) {
    const file = e.target.files?.[0]
    if (!file) return
    state.reset(); state.setLoading(true)
    try {
      const fd = new FormData(); fd.append('file', file)
      const data = await growthSvc.importSalesExcel(fd, false, null, state.fromBeginning)
      setWatermarkDate(data.watermark_date || null)
      state.setPreviewData(data)
    } catch (err) {
      state.setError(err?.response?.data?.detail?.message || 'Failed to parse file.')
    } finally { state.setLoading(false) }
  }

  async function handleConfirm(selectedIndices) {
    if (!fileRef.current?.files?.[0]) return
    state.setLoading(true); state.setError('')
    try {
      const fd = new FormData(); fd.append('file', fileRef.current.files[0])
      const data = await growthSvc.importSalesExcel(fd, true, selectedIndices, state.fromBeginning)
      state.setResult({ inserted: data.inserted, skipped: data.skipped })
      setWatermarkDate(data.watermark_date || null)
      if (fileRef.current) fileRef.current.value = ''
      onImported()
      setTimeout(() => state.reset(), 5000)
    } catch (err) {
      state.setError(err?.response?.data?.detail?.message || 'Import failed.')
    } finally { state.setLoading(false) }
  }

  async function handleResetWatermark() {
    try {
      await growthSvc.resetImportWatermark('excel', null)
      setWatermarkDate(null); state.reset()
    } catch {}
  }

  return (
    <ImportCard
      title="📊 Upload Excel / CSV"
      watermarkDate={watermarkDate}
      onResetWatermark={handleResetWatermark}
      state={{ ...state, onConfirm: handleConfirm }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
          {IMPORT_COLUMNS.map(col => (
            <span key={col} style={{ fontSize: 11, background: '#F0F7FA', color: '#2D6A7A', borderRadius: 4, padding: '2px 6px' }}>{col}</span>
          ))}
        </div>
        <button onClick={downloadTemplate} style={{ fontSize: 11, color: ds.teal, background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', whiteSpace: 'nowrap', marginLeft: 8 }}>
          Template
        </button>
      </div>
      <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv" onChange={handleFileChange} style={{ fontSize: 13, display: 'block', marginTop: 8 }} />
    </ImportCard>
  )
}

// ---------------------------------------------------------------------------
// Section 2B — Google Sheets
// ---------------------------------------------------------------------------
function SheetsImportCard({ onImported }) {
  const state = useImportState()
  const STORAGE_KEY = 'opsra_sheets_sales_url'
  const [url, setUrl]             = useState(() => { try { return localStorage.getItem(STORAGE_KEY) || '' } catch { return '' } })
  const [lastUsed, setLastUsed]   = useState(() => { try { return localStorage.getItem(STORAGE_KEY + '_date') || '' } catch { return '' } })
  const [watermarkDate, setWatermarkDate] = useState(null)

  function clearSaved() {
    try { localStorage.removeItem(STORAGE_KEY); localStorage.removeItem(STORAGE_KEY + '_date') } catch {}
    setUrl(''); setLastUsed(''); state.reset()
  }

  async function handlePreview() {
    if (!url.trim()) return state.setError('Please paste a Google Sheets URL.')
    state.reset(); state.setLoading(true)
    try {
      const data = await growthSvc.importSalesSheets(url.trim(), false, null, state.fromBeginning)
      setWatermarkDate(data.watermark_date || null)
      state.setPreviewData(data)
      try {
        localStorage.setItem(STORAGE_KEY, url.trim())
        const d = new Date().toLocaleDateString()
        localStorage.setItem(STORAGE_KEY + '_date', d); setLastUsed(d)
      } catch {}
    } catch (err) {
      state.setError(err?.response?.data?.detail?.message || 'Failed to fetch sheet.')
    } finally { state.setLoading(false) }
  }

  async function handleConfirm(selectedIndices) {
    state.setLoading(true); state.setError('')
    try {
      const data = await growthSvc.importSalesSheets(url.trim(), true, selectedIndices, state.fromBeginning)
      state.setResult({ inserted: data.inserted, skipped: data.skipped })
      setWatermarkDate(data.watermark_date || null)
      onImported()
      setTimeout(() => state.reset(), 5000)
    } catch (err) {
      state.setError(err?.response?.data?.detail?.message || 'Import failed.')
    } finally { state.setLoading(false) }
  }

  async function handleResetWatermark() {
    try {
      await growthSvc.resetImportWatermark('sheets', url.trim() || null)
      setWatermarkDate(null); state.reset()
    } catch {}
  }

  return (
    <ImportCard
      title="🔗 Pull from Google Sheets"
      watermarkDate={watermarkDate}
      onResetWatermark={handleResetWatermark}
      state={{ ...state, onConfirm: handleConfirm }}
    >
      <p style={{ fontSize: 12.5, color: '#7A9BAD', margin: '0 0 8px', lineHeight: 1.5 }}>
        Set your sheet to <strong>"Anyone with link can view"</strong>, then paste the URL.
      </p>
      {lastUsed && (
        <p style={{ fontSize: 12, color: '#7A9BAD', margin: '0 0 6px' }}>
          Last used: {lastUsed} — <button onClick={clearSaved} style={{ fontSize: 12, color: '#E53E3E', background: 'none', border: 'none', cursor: 'pointer', padding: 0, textDecoration: 'underline' }}>Clear</button>
        </p>
      )}
      <input
        style={{ ...inputStyle, marginBottom: 8 }}
        value={url} onChange={e => { setUrl(e.target.value); state.reset() }}
        placeholder="https://docs.google.com/spreadsheets/d/..."
      />
      <button onClick={handlePreview} disabled={state.loading} style={{
        padding: '8px 18px', background: state.loading ? '#7A9BAD' : '#1a3a4f',
        color: 'white', border: 'none', borderRadius: 6,
        cursor: state.loading ? 'not-allowed' : 'pointer',
        fontFamily: ds.fontDm, fontWeight: 600, fontSize: 13.5,
      }}>
        {state.loading ? 'Fetching…' : 'Preview'}
      </button>
    </ImportCard>
  )
}

// ---------------------------------------------------------------------------
// Paginator
// ---------------------------------------------------------------------------
function Paginator({ page, totalPages, onPage }) {
  function pages() {
    if (totalPages <= 7) return Array.from({ length: totalPages }, (_, i) => i + 1)
    const result = [], left = Math.max(2, page - 2), right = Math.min(totalPages - 1, page + 2)
    result.push(1)
    if (left > 2) result.push('l')
    for (let i = left; i <= right; i++) result.push(i)
    if (right < totalPages - 1) result.push('r')
    result.push(totalPages)
    return result
  }
  const btn = { minWidth: 32, height: 32, padding: '0 8px', border: '1px solid #C8DDE6', borderRadius: 6, fontSize: 13, fontFamily: ds.fontDm, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 4, marginTop: 16, flexWrap: 'wrap' }}>
      <button onClick={() => onPage(Math.max(1, page - 1))} disabled={page === 1} style={{ ...btn, color: page === 1 ? '#B0C8D4' : '#4a7a8a', background: 'white', cursor: page === 1 ? 'not-allowed' : 'pointer' }}>‹</button>
      {pages().map((p, i) =>
        typeof p === 'string' ? <span key={i} style={{ fontSize: 13, color: '#7A9BAD', padding: '0 4px' }}>...</span>
        : <button key={p} onClick={() => onPage(p)} style={{ ...btn, background: p === page ? ds.teal : 'white', color: p === page ? 'white' : '#4a7a8a', border: `1px solid ${p === page ? ds.teal : '#C8DDE6'}`, fontWeight: p === page ? 700 : 400, cursor: p === page ? 'default' : 'pointer' }}>{p}</button>
      )}
      <button onClick={() => onPage(Math.min(totalPages, page + 1))} disabled={page === totalPages} style={{ ...btn, color: page === totalPages ? '#B0C8D4' : '#4a7a8a', background: 'white', cursor: page === totalPages ? 'not-allowed' : 'pointer' }}>›</button>
      <span style={{ fontSize: 12, color: '#7A9BAD', marginLeft: 8 }}>Page {page} of {totalPages}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section 3 — Sales History
// ---------------------------------------------------------------------------
function SalesHistory({ refreshTick }) {
  const [items, setItems]     = useState([])
  const [total, setTotal]     = useState(0)
  const [page, setPage]       = useState(1)
  const [loading, setLoading] = useState(false)
  const [deleting, setDeleting] = useState(null)
  const PAGE_SIZE = 20

  const load = useCallback(async (p = 1) => {
    setLoading(true)
    try {
      const data = await growthSvc.getDirectSales(p, PAGE_SIZE)
      setItems(data.items || []); setTotal(data.total || 0)
    } catch {}
    setLoading(false)
  }, [])

  useEffect(() => { load(page) }, [page, refreshTick, load])

  async function handleDelete(id) {
    if (!window.confirm('Delete this sale record? This cannot be undone.')) return
    setDeleting(id)
    try { await growthSvc.deleteDirectSale(id); load(page) } catch {}
    setDeleting(null)
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return (
    <SectionCard title={`Sales History${total ? ` (${total})` : ''}`}>
      {loading && <p style={{ fontSize: 13, color: '#7A9BAD' }}>Loading…</p>}
      {!loading && items.length === 0 && (
        <div style={{ textAlign: 'center', padding: '32px 0', color: '#7A9BAD', fontSize: 14 }}>No sales logged yet.</div>
      )}
      {items.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#F0F7FA' }}>
                {['Date', 'Customer', 'Phone', 'Region', 'Amount', 'Channel', 'Team', 'Via', ''].map((h, i) => (
                  <th key={i} style={{ padding: '8px 12px', textAlign: 'left', color: '#4a7a8a', fontWeight: 600, borderBottom: '1px solid #C8DDE6', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map(row => {
                const src = sourceLabel(row.import_source)
                return (
                  <tr key={row.id} style={{ borderBottom: '1px solid #E2EFF4' }}>
                    <td style={{ padding: '8px 12px', whiteSpace: 'nowrap', color: '#4a7a8a' }}>{row.sale_date}</td>
                    <td style={{ padding: '8px 12px' }}>{row.customer_name || '—'}</td>
                    <td style={{ padding: '8px 12px', color: '#7A9BAD' }}>{row.phone || '—'}</td>
                    <td style={{ padding: '8px 12px', color: '#7A9BAD' }}>{row.region || '—'}</td>
                    <td style={{ padding: '8px 12px', fontWeight: 600, whiteSpace: 'nowrap' }}>₦{fmt(row.amount)}</td>
                    <td style={{ padding: '8px 12px', color: '#7A9BAD' }}>{row.channel || '—'}</td>
                    <td style={{ padding: '8px 12px', color: '#7A9BAD' }}>{row.source_team || '—'}</td>
                    <td style={{ padding: '8px 12px' }}>
                      <span style={{ fontSize: 11, fontWeight: 600, borderRadius: 4, padding: '2px 7px', background: src.bg, color: src.color }}>{src.label}</span>
                    </td>
                    <td style={{ padding: '8px 12px' }}>
                      <button onClick={() => handleDelete(row.id)} disabled={deleting === row.id} title="Delete"
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#E53E3E', fontSize: 16, padding: 0, opacity: deleting === row.id ? 0.4 : 1 }}>🗑</button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {totalPages > 1 && <Paginator page={page} totalPages={totalPages} onPage={setPage} />}
    </SectionCard>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------
export default function SalesLog() {
  const [teams, setTeams]           = useState([])
  const [refreshTick, setRefreshTick] = useState(0)

  useEffect(() => {
    growthSvc.getGrowthTeams()
      .then(data => setTeams((data || []).filter(t => t.is_active)))
      .catch(() => {})
  }, [])

  return (
    <div style={{ maxWidth: 1100 }}>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 800, fontSize: 18, color: '#0a1a24', margin: '0 0 4px' }}>💰 Sales Log</h2>
        <p style={{ fontSize: 13, color: '#7A9BAD', margin: 0 }}>Log offline revenue — phone sales, walk-ins, referrals — outside the lead pipeline.</p>
      </div>

      <QuickSaleForm teams={teams} onSaleLogged={() => setRefreshTick(t => t + 1)} />

      <div style={{ border: '1px solid #E2EFF4', borderRadius: 10, overflow: 'hidden', marginBottom: 28, background: '#F8FBFC' }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #E2EFF4' }}>
          <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#0a1a24', margin: 0 }}>Bulk Import</h3>
        </div>
        <div style={{ padding: 20, display: 'flex', gap: 20, flexWrap: 'wrap' }}>
          <ExcelImportCard onImported={() => setRefreshTick(t => t + 1)} />
          <SheetsImportCard onImported={() => setRefreshTick(t => t + 1)} />
        </div>
      </div>

      <SalesHistory refreshTick={refreshTick} />
    </div>
  )
}
