/**
 * frontend/src/modules/ops/DataSourcesTab.jsx
 * REPORTS-DEPT-1 Phase 4b — Data Sources tab inside Business Activities.
 *
 * Sales revenue (daily-aggregate import) RETIRED — client confirmed the
 * Lagos/Abuja transaction workbook is the complete sales picture, so the
 * aggregate-only path (day-totals, no per-sale detail) added nothing on
 * top of it and only risked double-counting. Backend routes
 * (import_daily_aggregate_excel/sheets) deliberately left in place,
 * unreachable now that no UI calls them — safer than deleting code with
 * unverified downstream dependencies. The 7 rows it had produced were
 * removed via a one-time SQL cleanup, scoped to import_source in
 * ('agg_excel','agg_sheets') only.
 *
 * Sales transactions (per-sale workbook, one tab per region) is now the
 * single source feeding Sales Record and Commissions.
 *
 * REPORTS-DEPT-1 Phase 4b — Live Google Sheet sync added alongside the
 * existing file-upload card. Admin saves a sheet URL plus one
 * {region name, tab GID} pair per region tab, then triggers a manual
 * "Sync now" any time the sheet's been updated. GID is entered by hand
 * (copied from the browser URL when that tab is open in Google Sheets) —
 * no Google API key/auto-discovery, and deliberately no periodic/
 * background schedule (opsra-celery-beat is not yet deployed, so a
 * scheduled sync would silently never fire).
 *
 * REPORTS-DEPT-1 Phase 4b (this update) — region config is no longer
 * Sheets-only. The Excel upload route used to filter workbook tabs
 * against a hardcoded ALLOWED_REGIONS set in the backend; that's gone
 * now, replaced by reading the SAME region list saved here. Sheet URL
 * and each region's GID are optional — they're only required to run a
 * live Sync; an org that only ever uploads Excel files can save just
 * region names and leave the rest blank. This card's save/validate flow
 * was relaxed accordingly (previously required sheet URL + gid on every
 * region before it would let you save anything).
 *
 * Rep -> team -> department attribution happens automatically (same
 * mechanism as REPORTS-DEPT-1 Phase 0) — this card doesn't ask which
 * department the import is "for".
 *
 * NOT yet built, deliberately out of scope for this component:
 *   - Per-department native-vs-external source toggle
 *   - Manual lead-count entry
 *   - Periodic/background sheet sync (needs opsra-celery-beat deployed first)
 *
 * Pattern 51: full rewrite if editing this file — never partial sed.
 */
import { useState, useEffect } from 'react'
import {
  UploadCloud, RotateCcw, CheckCircle2, AlertTriangle, Loader2, Table2,
  Link2, Plus, Trash2, RefreshCw,
} from 'lucide-react'
import { ds } from '../../utils/ds'
import {
  importTransactionSalesExcel,
  resetImportWatermark,
  clearImportedSales,
  getTransactionSheetSource,
  saveTransactionSheetSource,
  syncTransactionSalesSheets,
} from '../../services/growth.service'

const CARD = {
  background:   'white',
  border:       '1px solid #E4EEF2',
  borderRadius: 12,
  padding:      '20px 22px',
  maxWidth:     640,
  marginBottom: 24,
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
  fontSize:     13,
  padding:      '8px 10px',
  border:       '1px solid #E4EEF2',
  borderRadius: 6,
  fontFamily:   'inherit',
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

function PreviewErrors({ errors }) {
  if (!errors || errors.length === 0) return null
  return (
    <div style={{ marginBottom: 14, maxHeight: 140, overflowY: 'auto', border: '1px solid #FCA5A5', borderRadius: 8, padding: '8px 12px', background: '#FEF2F2' }}>
      {errors.map((e, i) => (
        <p key={i} style={{ fontSize: 12, color: '#B91C1C', margin: '4px 0' }}>
          Row {e.row}{e.region ? ` (${e.region})` : ''}: {e.message}
        </p>
      ))}
    </div>
  )
}

// ─── Sales transactions (per-sale workbook, multi-region — file upload) ────

function SalesTransactionsCard() {
  const [file, setFile]               = useState(null)
  const [fromBeginning, setFromBeginning] = useState(false)
  const [preview, setPreview]         = useState(null)
  const [result, setResult]           = useState(null)
  const [loading, setLoading]         = useState(false)
  const [error, setError]             = useState(null)

  const reset = () => { setPreview(null); setResult(null); setError(null) }

  const handlePreview = async () => {
    if (!file) { setError('Choose a workbook first.'); return }
    setLoading(true); setError(null); setResult(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const data = await importTransactionSalesExcel(formData, false, fromBeginning)
      setPreview(data)
    } catch (e) {
      setError(e?.response?.data?.detail?.message ?? 'Failed to read the workbook. Check the file and try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleConfirm = async () => {
    setLoading(true); setError(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const data = await importTransactionSalesExcel(formData, true, fromBeginning)
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
      await resetImportWatermark('txn_excel', null)
      reset()
    } catch {
      setError('Failed to reset sync point.')
    }
  }

  const handleClearAndReset = async () => {
    if (!window.confirm('Delete every sale previously imported from this source, and reset its sync point? This cannot be undone — do this before re-uploading a corrected sheet.')) return
    try {
      await clearImportedSales('txn_excel')
      await resetImportWatermark('txn_excel', null)
      reset()
    } catch {
      setError('Failed to clear previously imported data.')
    }
  }

  return (
    <div style={CARD}>
      <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#0a1a24', margin: '0 0 4px', display: 'flex', alignItems: 'center', gap: 8 }}>
        <Table2 size={16} color={ds.teal} /> Sales transactions
      </h3>
      <p style={{ fontSize: 12.5, color: '#7A9BAD', margin: '0 0 16px' }}>
        Individual sales — one workbook, one tab per region (e.g. Lagos, Abuja). Expected columns: Date, Sales Rep,
        Customer Name, Model, Units, Amount, Status. Feeds Sales Record and Commissions. Region names must be
        configured in the "Region tabs" card below first — an upload only reads tabs matching a saved region name.
      </p>

      <div style={{ marginBottom: 14 }}>
        <input type="file" accept=".xlsx,.xls" onChange={e => { setFile(e.target.files?.[0] ?? null); reset() }} style={{ fontSize: 13 }} />
        {file && <p style={{ fontSize: 12, color: '#7A9BAD', margin: '6px 0 0' }}>{file.name}</p>}
      </div>

      <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: '#4a7a8a', marginBottom: 16, cursor: 'pointer' }}>
        <input type="checkbox" checked={fromBeginning} onChange={e => { setFromBeginning(e.target.checked); reset() }} />
        Start from the beginning (ignore what's already been synced)
      </label>

      {error && <p style={{ color: '#DC2626', fontSize: 13, margin: '0 0 14px', display: 'flex', alignItems: 'center', gap: 6 }}><AlertTriangle size={14} /> {error}</p>}

      {!preview && !result && (
        <button onClick={handlePreview} disabled={loading} style={{ ...BTN_PRIMARY, opacity: loading ? 0.6 : 1 }}>
          {loading ? <Loader2 size={15} style={{ animation: 'spin 0.8s linear infinite' }} /> : <UploadCloud size={15} />}
          {loading ? 'Reading…' : 'Preview import'}
        </button>
      )}

      {preview && (
        <div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
            <SourceBadge text={`${preview.total_valid} row${preview.total_valid !== 1 ? 's' : ''} ready`} tone="ok" />
            {preview.regions?.length > 0 && <SourceBadge text={`Regions: ${preview.regions.join(', ')}`} tone="ok" />}
            {preview.errors?.length > 0 && <SourceBadge text={`${preview.errors.length} skipped (errors)`} tone="err" />}
            {preview.duplicate_warnings?.length > 0 && <SourceBadge text={`${preview.duplicate_warnings.length} possible duplicate${preview.duplicate_warnings.length !== 1 ? 's' : ''}`} tone="warn" />}
            {preview.already_imported?.length > 0 && <SourceBadge text={`${preview.already_imported.length} already synced`} tone="warn" />}
          </div>
          <PreviewErrors errors={preview.errors} />
          {preview.total_valid > 0 ? (
            <button onClick={handleConfirm} disabled={loading} style={{ ...BTN_PRIMARY, opacity: loading ? 0.6 : 1 }}>
              {loading ? 'Importing…' : `Confirm — import ${preview.total_valid} row${preview.total_valid !== 1 ? 's' : ''}`}
            </button>
          ) : (
            <p style={{ fontSize: 13, color: '#7A9BAD' }}>Nothing new to import from this source.</p>
          )}
        </div>
      )}

      {result && (
        <div>
          <p style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13.5, color: '#059669', fontWeight: 600, margin: '0 0 4px' }}>
            <CheckCircle2 size={16} /> {result.inserted} sale{result.inserted !== 1 ? 's' : ''} imported
          </p>
          {result.regions?.length > 0 && (
            <p style={{ fontSize: 12, color: '#7A9BAD', margin: '0 0 4px' }}>Regions found: {result.regions.join(', ')}</p>
          )}
          <p style={{ fontSize: 12, color: '#7A9BAD', margin: 0 }}>
            Synced through {result.watermark_date ?? 'today'}. Re-run this import any time — already-synced rows are skipped automatically.
          </p>
        </div>
      )}

      <div style={{ marginTop: 18, paddingTop: 14, borderTop: '1px solid #F0F7FA', display: 'flex', gap: 8 }}>
        <button onClick={handleResetWatermark} style={{ ...BTN_OUTLINE, fontSize: 12.5, padding: '6px 12px', display: 'flex', alignItems: 'center', gap: 6 }}>
          <RotateCcw size={13} /> Reset sync point for this source
        </button>
        <button onClick={handleClearAndReset} style={{ ...BTN_OUTLINE, fontSize: 12.5, padding: '6px 12px', display: 'flex', alignItems: 'center', gap: 6, color: '#DC2626', borderColor: '#DC2626' }}>
          Clear previously imported data &amp; reset
        </button>
      </div>
    </div>
  )
}

// ─── Region tabs + Live Google Sheet sync (shared config) ─────────────────
//
// This card's saved config (region name + optional tab GID, plus an
// optional sheet URL) is now used by BOTH import paths:
//   - SalesTransactionsCard's Excel upload filters workbook tabs against
//     the region NAMES saved here (replacing the old backend-hardcoded
//     ALLOWED_REGIONS set).
//   - This card's own "Sync now" additionally needs a saved sheet URL and
//     at least one region with a GID, to fetch that tab live.
// An Excel-only org can save just region names and leave Sheet URL/GID
// blank — "Sync now" simply won't be enabled until those are filled in.

function SheetsSyncCard() {
  const [loadingConfig, setLoadingConfig] = useState(true)
  const [sheetUrl, setSheetUrl]       = useState('')
  const [regions, setRegions]         = useState([{ name: '', gid: '' }])
  const [savedSource, setSavedSource] = useState(null)
  const [savingConfig, setSavingConfig] = useState(false)
  const [configError, setConfigError] = useState(null)
  const [configSaved, setConfigSaved] = useState(false)

  const [fromBeginning, setFromBeginning] = useState(false)
  const [preview, setPreview]         = useState(null)
  const [result, setResult]           = useState(null)
  const [loading, setLoading]         = useState(false)
  const [error, setError]             = useState(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const data = await getTransactionSheetSource()
        if (cancelled) return
        if (data?.source) {
          setSavedSource(data.source)
          setSheetUrl(data.source.sheet_url || '')
          setRegions(data.source.regions?.length ? data.source.regions : [{ name: '', gid: '' }])
        }
      } catch {
        // No saved source yet, or fetch failed — start from a blank config.
      } finally {
        if (!cancelled) setLoadingConfig(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  const resetSyncState = () => { setPreview(null); setResult(null); setError(null) }

  const updateRegion = (idx, field, value) => {
    setRegions(prev => prev.map((r, i) => (i === idx ? { ...r, [field]: value } : r)))
  }
  const addRegion = () => setRegions(prev => [...prev, { name: '', gid: '' }])
  const removeRegion = (idx) => setRegions(prev => prev.filter((_, i) => i !== idx))

  // Region names are the only hard requirement now — Sheet URL and each
  // region's GID are optional, and only needed to enable live "Sync now".
  const handleSaveConfig = async () => {
    setConfigError(null); setConfigSaved(false)
    const cleanRegions = regions
      .map(r => ({ name: (r.name || '').trim(), gid: (r.gid || '').trim() }))
      .filter(r => r.name)
      .map(r => ({ name: r.name, gid: r.gid || null }))
    if (cleanRegions.length === 0) { setConfigError('Add at least one region name.'); return }
    setSavingConfig(true)
    try {
      const data = await saveTransactionSheetSource(sheetUrl.trim() || null, cleanRegions)
      setSavedSource(data.source)
      setConfigSaved(true)
      resetSyncState()
    } catch (e) {
      setConfigError(e?.response?.data?.detail?.message ?? 'Failed to save region config.')
    } finally {
      setSavingConfig(false)
    }
  }

  const handlePreview = async () => {
    setLoading(true); setError(null); setResult(null)
    try {
      const data = await syncTransactionSalesSheets(false, fromBeginning)
      setPreview(data)
    } catch (e) {
      setError(e?.response?.data?.detail?.message ?? 'Failed to read the sheet. Check the source config and try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleConfirm = async () => {
    setLoading(true); setError(null)
    try {
      const data = await syncTransactionSalesSheets(true, fromBeginning)
      setResult(data)
      setPreview(null)
    } catch (e) {
      setError(e?.response?.data?.detail?.message ?? 'Sync failed. Nothing was saved — try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleResetWatermark = async () => {
    if (!window.confirm('Reset the sync point for this source? The next sync will re-check every row from the beginning.')) return
    try {
      await resetImportWatermark('txn_sheets', savedSource?.sheet_url ?? null)
      resetSyncState()
    } catch {
      setError('Failed to reset sync point.')
    }
  }

  const handleClearAndReset = async () => {
    if (!window.confirm('Delete every sale previously synced from this source, and reset its sync point? This cannot be undone.')) return
    try {
      await clearImportedSales('txn_sheets')
      await resetImportWatermark('txn_sheets', savedSource?.sheet_url ?? null)
      resetSyncState()
    } catch {
      setError('Failed to clear previously synced data.')
    }
  }

  if (loadingConfig) {
    return (
      <div style={CARD}>
        <p style={{ fontSize: 13, color: '#7A9BAD' }}>Loading region config…</p>
      </div>
    )
  }

  // "Sync now" needs a saved sheet URL AND at least one region with a
  // real GID — region names alone (the Excel-only case) aren't enough.
  const canSync = !!(savedSource?.sheet_url) && (savedSource?.regions || []).some(r => (r.gid || '').trim())

  return (
    <div style={CARD}>
      <h3 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: '#0a1a24', margin: '0 0 4px', display: 'flex', alignItems: 'center', gap: 8 }}>
        <Link2 size={16} color={ds.teal} /> Region tabs &amp; Live Google Sheet sync
      </h3>
      <p style={{ fontSize: 12.5, color: '#7A9BAD', margin: '0 0 16px' }}>
        Region names saved here are used by BOTH the Excel upload above and live Sheets sync — an uploaded workbook
        only reads tabs matching one of these names. Sheet URL and each region's tab GID (the number after
        <code> gid=</code> in the browser URL when that tab is open) are optional — leave them blank if you only
        upload Excel files. Set the sheet to "Anyone with link can view" to enable live sync. There's no automatic
        background sync yet — use "Sync now" whenever the sheet's been updated.
      </p>

      <div style={{ marginBottom: 14 }}>
        <label style={{ display: 'block', fontSize: 12.5, color: '#4a7a8a', marginBottom: 6, fontWeight: 600 }}>
          Google Sheet URL <span style={{ fontWeight: 400, color: '#9BB4C0' }}>(optional — required only for live sync)</span>
        </label>
        <input
          type="text"
          value={sheetUrl}
          onChange={e => setSheetUrl(e.target.value)}
          placeholder="https://docs.google.com/spreadsheets/d/..."
          style={{ ...INPUT, width: '100%' }}
        />
      </div>

      <div style={{ marginBottom: 14 }}>
        <label style={{ display: 'block', fontSize: 12.5, color: '#4a7a8a', marginBottom: 6, fontWeight: 600 }}>
          Region tabs
        </label>
        {regions.map((r, idx) => (
          <div key={idx} style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center' }}>
            <input
              type="text"
              value={r.name}
              onChange={e => updateRegion(idx, 'name', e.target.value)}
              placeholder="Region name (e.g. Lagos Sales)"
              style={{ ...INPUT, flex: 2 }}
            />
            <input
              type="text"
              value={r.gid || ''}
              onChange={e => updateRegion(idx, 'gid', e.target.value)}
              placeholder="Tab GID (optional)"
              style={{ ...INPUT, flex: 1 }}
            />
            {regions.length > 1 && (
              <button
                onClick={() => removeRegion(idx)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, display: 'flex' }}
                aria-label="Remove region"
              >
                <Trash2 size={15} color="#DC2626" />
              </button>
            )}
          </div>
        ))}
        <button onClick={addRegion} style={{ ...BTN_OUTLINE, fontSize: 12, padding: '6px 12px', display: 'flex', alignItems: 'center', gap: 6 }}>
          <Plus size={13} /> Add another region tab
        </button>
      </div>

      {configError && <p style={{ color: '#DC2626', fontSize: 13, margin: '0 0 12px', display: 'flex', alignItems: 'center', gap: 6 }}><AlertTriangle size={14} /> {configError}</p>}
      {configSaved && !configError && <p style={{ color: '#059669', fontSize: 12.5, margin: '0 0 12px' }}>Region config saved.</p>}

      <button onClick={handleSaveConfig} disabled={savingConfig} style={{ ...BTN_OUTLINE, opacity: savingConfig ? 0.6 : 1, marginBottom: 18 }}>
        {savingConfig ? 'Saving…' : savedSource ? 'Update region config' : 'Save region config'}
      </button>

      <div style={{ paddingTop: 14, borderTop: '1px solid #F0F7FA' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: '#4a7a8a', marginBottom: 14, cursor: 'pointer' }}>
          <input type="checkbox" checked={fromBeginning} onChange={e => { setFromBeginning(e.target.checked); resetSyncState() }} />
          Start from the beginning (ignore what's already been synced)
        </label>

        {error && <p style={{ color: '#DC2626', fontSize: 13, margin: '0 0 14px', display: 'flex', alignItems: 'center', gap: 6 }}><AlertTriangle size={14} /> {error}</p>}

        {!preview && !result && (
          <button onClick={handlePreview} disabled={loading || !canSync} style={{ ...BTN_PRIMARY, opacity: (loading || !canSync) ? 0.6 : 1 }}>
            {loading ? <Loader2 size={15} style={{ animation: 'spin 0.8s linear infinite' }} /> : <RefreshCw size={15} />}
            {loading ? 'Checking sheet…' : 'Sync now'}
          </button>
        )}
        {!canSync && (
          <p style={{ fontSize: 12, color: '#7A9BAD', margin: '6px 0 0' }}>
            {savedSource
              ? 'Add a Sheet URL and at least one region\'s tab GID above to enable live sync.'
              : 'Save a region config above before syncing.'}
          </p>
        )}

        {preview && (
          <div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
              <SourceBadge text={`${preview.total_valid} row${preview.total_valid !== 1 ? 's' : ''} ready`} tone="ok" />
              {preview.regions?.length > 0 && <SourceBadge text={`Regions: ${preview.regions.join(', ')}`} tone="ok" />}
              {preview.errors?.length > 0 && <SourceBadge text={`${preview.errors.length} skipped (errors)`} tone="err" />}
              {preview.duplicate_warnings?.length > 0 && <SourceBadge text={`${preview.duplicate_warnings.length} possible duplicate${preview.duplicate_warnings.length !== 1 ? 's' : ''}`} tone="warn" />}
              {preview.already_imported?.length > 0 && <SourceBadge text={`${preview.already_imported.length} already synced`} tone="warn" />}
            </div>
            <PreviewErrors errors={preview.errors} />
            {preview.total_valid > 0 ? (
              <button onClick={handleConfirm} disabled={loading} style={{ ...BTN_PRIMARY, opacity: loading ? 0.6 : 1 }}>
                {loading ? 'Syncing…' : `Confirm — sync ${preview.total_valid} row${preview.total_valid !== 1 ? 's' : ''}`}
              </button>
            ) : (
              <p style={{ fontSize: 13, color: '#7A9BAD' }}>Nothing new to sync from this sheet.</p>
            )}
          </div>
        )}

        {result && (
          <div>
            <p style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13.5, color: '#059669', fontWeight: 600, margin: '0 0 4px' }}>
              <CheckCircle2 size={16} /> {result.inserted} sale{result.inserted !== 1 ? 's' : ''} synced
            </p>
            {result.regions?.length > 0 && (
              <p style={{ fontSize: 12, color: '#7A9BAD', margin: '0 0 4px' }}>Regions found: {result.regions.join(', ')}</p>
            )}
            <p style={{ fontSize: 12, color: '#7A9BAD', margin: 0 }}>
              Synced through {result.watermark_date ?? 'today'}. Click "Sync now" any time — already-synced rows are skipped automatically.
            </p>
          </div>
        )}
      </div>

      <div style={{ marginTop: 18, paddingTop: 14, borderTop: '1px solid #F0F7FA', display: 'flex', gap: 8 }}>
        <button onClick={handleResetWatermark} style={{ ...BTN_OUTLINE, fontSize: 12.5, padding: '6px 12px', display: 'flex', alignItems: 'center', gap: 6 }}>
          <RotateCcw size={13} /> Reset sync point for this source
        </button>
        <button onClick={handleClearAndReset} style={{ ...BTN_OUTLINE, fontSize: 12.5, padding: '6px 12px', display: 'flex', alignItems: 'center', gap: 6, color: '#DC2626', borderColor: '#DC2626' }}>
          Clear previously synced data &amp; reset
        </button>
      </div>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function DataSourcesTab() {
  return (
    <div style={{ padding: 28 }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: '#0a1a24', margin: '0 0 6px' }}>
        Data Sources
      </h2>
      <p style={{ fontSize: 13, color: '#7A9BAD', margin: '0 0 24px', maxWidth: 640, lineHeight: 1.6 }}>
        Connect external sheets for metrics Opsra doesn't track natively. Rep and team attribution is matched
        automatically — no need to say which department this is for.
      </p>

      <SalesTransactionsCard />
      <SheetsSyncCard />
    </div>
  )
}
