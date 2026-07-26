/**
 * frontend/src/modules/ops/DataSourcesTab.jsx
 * REPORTS-DEPT-1 Phase 4 — Data Sources tab inside Business Activities.
 *
 * Currently wires ONE concrete source: Sales revenue, imported from a
 * daily-aggregate sheet (Date / Sales Rep / Mattress Revenue / Pillow
 * Revenue) into direct_sales, via the daily-aggregate import routes
 * built in Phase 4. Rep -> team -> department attribution happens
 * automatically at read time (same mechanism as REPORTS-DEPT-1 Phase 0)
 * — this panel does NOT ask which department the import is "for", since
 * the import itself is org-wide and attribution is derived per row.
 *
 * NOT yet built, deliberately out of scope for this component:
 *   - Per-department native-vs-external source toggle
 *   - Manual lead-count entry
 * Both flagged as open follow-ups, not silently omitted.
 *
 * Pattern 51: full rewrite if editing this file — never partial sed.
 */
import { useState, useRef } from 'react'
import { UploadCloud, Link2, RotateCcw, CheckCircle2, AlertTriangle, Loader2 } from 'lucide-react'
import { ds } from '../../utils/ds'
import {
  importDailyAggregateExcel,
  importDailyAggregateSheets,
  resetImportWatermark,
} from '../../services/growth.service'

const CARD = {
  background:   'white',
  border:       '1px solid #E4EEF2',
  borderRadius: 12,
  padding:      '20px 22px',
  maxWidth:     640,
}

const BTN_PRIMARY = {
  background:   ds.teal,
  color:        'white',
  border:       'none',
  borderRadius: 8,
  padding:      '9px 18px',
  fontSize:     13.5,
  fontWeight:   600,
  cursor:       'pointer',
  fontFamily:   'inherit',
  display:      'flex',
  alignItems:   'center',
  gap:          6,
}

const BTN_OUTLINE = {
  background:   'white',
  color:        ds.teal,
  border:       `1px solid ${ds.teal}`,
  borderRadius: 8,
  padding:      '9px 18px',
  fontSize:     13.5,
  fontWeight:   600,
  cursor:       'pointer',
  fontFamily:   'inherit',
}

const INPUT = {
  padding:      '9px 12px',
  border:       '1px solid #D4E6EC',
  borderRadius: 8,
  fontSize:     13.5,
  fontFamily:   'inherit',
  color:        '#0a1a24',
  background:   'white',
  outline:      'none',
  width:        '100%',
  boxSizing:    'border-box',
}

function SourceBadge({ text, tone }) {
  const colours = {
    ok:   { bg: '#ECFDF5', text: '#059669' },
    warn: { bg: '#FDF4E3', text: '#92601A' },
    err:  { bg: '#FEF2F2', text: '#DC2626' },
  }[tone]
  return (
    <span style={{
      background: colours.bg, color: colours.text,
      fontSize: 11.5, fontWeight: 600, padding: '3px 9px', borderRadius: 20,
    }}>
      {text}
    </span>
  )
}

export default function DataSourcesTab() {
  const [mode, setMode]               = useState('excel')   // 'excel' | 'sheets'
  const [file, setFile]               = useState(null)
  const [sheetUrl, setSheetUrl]       = useState('')
  const [fromBeginning, setFromBeginning] = useState(false)
  const [preview, setPreview]         = useState(null)   // API response, confirm=false
  const [result, setResult]           = useState(null)    // API response, confirm=true
  const [loading, setLoading]         = useState(false)
  const [error, setError]             = useState(null)
  const fileInputRef = useRef(null)

  const reset = () => {
    setPreview(null); setResult(null); setError(null)
  }

  const handlePreview = async () => {
    setLoading(true); setError(null); setResult(null)
    try {
      let data
      if (mode === 'excel') {
        if (!file) { setError('Choose a file first.'); setLoading(false); return }
        const formData = new FormData()
        formData.append('file', file)
        data = await importDailyAggregateExcel(formData, false, null, fromBeginning)
      } else {
        if (!sheetUrl.trim()) { setError('Paste a Google Sheet URL first.'); setLoading(false); return }
        data = await importDailyAggregateSheets(sheetUrl.trim(), false, null, fromBeginning)
      }
      setPreview(data)
    } catch (e) {
      setError(e?.response?.data?.detail?.message ?? 'Failed to read the sheet. Check the file or URL and try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleConfirm = async () => {
    setLoading(true); setError(null)
    try {
      let data
      if (mode === 'excel') {
        const formData = new FormData()
        formData.append('file', file)
        data = await importDailyAggregateExcel(formData, true, null, fromBeginning)
      } else {
        data = await importDailyAggregateSheets(sheetUrl.trim(), true, null, fromBeginning)
      }
      setResult(data)
      setPreview(null)
    } catch (e) {
      setError(e?.response?.data?.detail?.message ?? 'Import failed. Nothing was saved — try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleResetWatermark = async () => {
    if (!window.confirm('Reset the sync point for this source? The next import will re-check every row from the beginning.')) return
    try {
      const sourceType = mode === 'excel' ? 'daily_aggregate_excel' : 'daily_aggregate_sheets'
      await resetImportWatermark(sourceType, mode === 'sheets' ? sheetUrl.trim() : null)
      reset()
    } catch {
      setError('Failed to reset sync point.')
    }
  }

  return (
    <div style={{ padding: 28 }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: '0 0 6px' }}>
        Data Sources
      </h2>
      <p style={{ fontSize: 13, color: '#7A9BAD', margin: '0 0 24px', maxWidth: 640, lineHeight: 1.6 }}>
        Connect an external sheet for metrics Opsra doesn't track natively.
        Currently supports Sales revenue from a daily-aggregate sheet (one
        row per day per rep). Rep and team attribution is matched
        automatically — no need to say which department this is for.
      </p>

      <div style={CARD}>
        <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#0a1a24', margin: '0 0 4px' }}>
          Sales revenue
        </h3>
        <p style={{ fontSize: 12.5, color: '#7A9BAD', margin: '0 0 16px' }}>
          Expected columns: Date, Sales Rep, Mattress Revenue, Pillow Revenue
          (or your product lines' revenue columns).
        </p>

        {/* Mode toggle */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <button
            onClick={() => { setMode('excel'); reset() }}
            style={{ ...(mode === 'excel' ? BTN_PRIMARY : BTN_OUTLINE), flex: 1, justifyContent: 'center' }}
          >
            <UploadCloud size={15} /> Upload file
          </button>
          <button
            onClick={() => { setMode('sheets'); reset() }}
            style={{ ...(mode === 'sheets' ? BTN_PRIMARY : BTN_OUTLINE), flex: 1, justifyContent: 'center' }}
          >
            <Link2 size={15} /> Google Sheet link
          </button>
        </div>

        {mode === 'excel' ? (
          <div style={{ marginBottom: 14 }}>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xls,.csv"
              onChange={e => { setFile(e.target.files?.[0] ?? null); reset() }}
              style={{ fontSize: 13 }}
            />
            {file && <p style={{ fontSize: 12, color: '#7A9BAD', margin: '6px 0 0' }}>{file.name}</p>}
          </div>
        ) : (
          <input
            value={sheetUrl}
            onChange={e => { setSheetUrl(e.target.value); reset() }}
            placeholder="https://docs.google.com/spreadsheets/d/..."
            style={{ ...INPUT, marginBottom: 14 }}
          />
        )}

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: '#4a7a8a', marginBottom: 16, cursor: 'pointer' }}>
          <input type="checkbox" checked={fromBeginning} onChange={e => { setFromBeginning(e.target.checked); reset() }} />
          Start from the beginning (ignore what's already been synced)
        </label>

        {error && (
          <p style={{ color: '#DC2626', fontSize: 13, margin: '0 0 14px', display: 'flex', alignItems: 'center', gap: 6 }}>
            <AlertTriangle size={14} /> {error}
          </p>
        )}

        {!preview && !result && (
          <button onClick={handlePreview} disabled={loading} style={{ ...BTN_PRIMARY, opacity: loading ? 0.6 : 1 }}>
            {loading ? <Loader2 size={15} style={{ animation: 'spin 0.8s linear infinite' }} /> : null}
            {loading ? 'Reading…' : 'Preview import'}
          </button>
        )}

        {/* Preview state */}
        {preview && (
          <div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
              <SourceBadge text={`${preview.total_valid} row${preview.total_valid !== 1 ? 's' : ''} ready`} tone="ok" />
              {preview.errors?.length > 0 && (
                <SourceBadge text={`${preview.errors.length} skipped (errors)`} tone="err" />
              )}
              {preview.duplicate_warnings?.length > 0 && (
                <SourceBadge text={`${preview.duplicate_warnings.length} possible duplicate${preview.duplicate_warnings.length !== 1 ? 's' : ''}`} tone="warn" />
              )}
              {preview.already_imported?.length > 0 && (
                <SourceBadge text={`${preview.already_imported.length} already synced`} tone="warn" />
              )}
            </div>

            {preview.errors?.length > 0 && (
              <div style={{ marginBottom: 14, maxHeight: 140, overflowY: 'auto', border: '1px solid #FCA5A5', borderRadius: 8, padding: '8px 12px', background: '#FEF2F2' }}>
                {preview.errors.map((e, i) => (
                  <p key={i} style={{ fontSize: 12, color: '#B91C1C', margin: '4px 0' }}>Row {e.row}: {e.message}</p>
                ))}
              </div>
            )}

            {preview.total_valid > 0 ? (
              <button onClick={handleConfirm} disabled={loading} style={{ ...BTN_PRIMARY, opacity: loading ? 0.6 : 1 }}>
                {loading ? 'Importing…' : `Confirm — import ${preview.total_valid} row${preview.total_valid !== 1 ? 's' : ''}`}
              </button>
            ) : (
              <p style={{ fontSize: 13, color: '#7A9BAD' }}>Nothing new to import from this source.</p>
            )}
          </div>
        )}

        {/* Result state */}
        {result && (
          <div>
            <p style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13.5, color: '#059669', fontWeight: 600, margin: '0 0 4px' }}>
              <CheckCircle2 size={16} /> {result.inserted} sale{result.inserted !== 1 ? 's' : ''} imported
            </p>
            <p style={{ fontSize: 12, color: '#7A9BAD', margin: 0 }}>
              Synced through {result.watermark_date ?? 'today'}. Re-run this import any time — already-synced rows are skipped automatically.
            </p>
          </div>
        )}

        <div style={{ marginTop: 18, paddingTop: 14, borderTop: '1px solid #F0F7FA' }}>
          <button onClick={handleResetWatermark} style={{ ...BTN_OUTLINE, fontSize: 12.5, padding: '6px 12px', display: 'flex', alignItems: 'center', gap: 6 }}>
            <RotateCcw size={13} /> Reset sync point for this source
          </button>
        </div>
      </div>
    </div>
  )
}
