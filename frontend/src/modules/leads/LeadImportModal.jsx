/**
 * LeadImportModal
 *
 * POST /api/v1/leads/import  →  { job_id }
 * Then polls GET /api/v1/leads/import/{job_id} every 2 seconds until
 *   status === 'done' | 'failed'
 *
 * LeadImportStatus shape (from Build Status models/leads.py):
 *   { job_id, status, total_rows, processed, succeeded, failed, errors }
 */
import { useState, useRef } from 'react'
import { importLeads, getImportStatus } from '../../services/leads.service'
import { ds } from '../../utils/ds'

const POLL_INTERVAL_MS = 2000

export default function LeadImportModal({ onClose, onImported }) {
  const [file, setFile]       = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [jobStatus, setJobStatus] = useState(null) // LeadImportStatus
  const [error, setError]     = useState(null)
  const pollRef               = useRef(null)
  const inputRef              = useRef(null)

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  const startPolling = (jobId) => {
    pollRef.current = setInterval(async () => {
      try {
        const res = await getImportStatus(jobId)
        if (res.success) {
          setJobStatus(res.data)
          if (res.data.status === 'done' || res.data.status === 'failed') {
            stopPolling()
            // Do NOT call onImported here — calling parent state setter
            // from inside setInterval while modal is still mounted
            // causes React unmount crash. Let the button handle closing.
          }
        }
      } catch {
        // keep polling — transient errors shouldn't abort the job
      }
    }, POLL_INTERVAL_MS)
  }

  const handleUpload = async () => {
    if (!file) return
    setUploading(true)
    setError(null)
    setJobStatus(null)

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await importLeads(formData)
      if (res.success) {
        setJobStatus(res.data)
        startPolling(res.data.job_id)
      } else {
        setError(res.error ?? 'Upload failed')
      }
    } catch (err) {
      setError(err?.response?.data?.error ?? 'Upload failed — please try again')
    } finally {
      setUploading(false)
    }
  }

  const handleClose = () => {
    stopPolling()
    onClose()
  }

  const handleFileDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f && (f.name.endsWith('.csv') || f.name.endsWith('.xlsx'))) setFile(f)
    else setError('Please upload a CSV file.')
  }

  const isDone    = jobStatus?.status === 'done'
  const isFailed  = jobStatus?.status === 'failed'
  const isRunning = jobStatus && !isDone && !isFailed
  const progress  = jobStatus
    ? Math.round((jobStatus.processed / (jobStatus.total_rows || 1)) * 100)
    : 0

  return (
    <ModalOverlay onClose={handleClose}>
      {/* Header */}
      <div style={headerStyle}>
        <div>
          <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: ds.dark, margin: 0 }}>
            Import Leads from CSV
          </h2>
          <p style={{ fontSize: 13, color: ds.gray, margin: '2px 0 0' }}>
            Duplicate phone/email addresses will be detected and skipped
          </p>
        </div>
        <button onClick={handleClose} style={closeBtn}>✕</button>
      </div>

      <div style={{ padding: '24px' }}>

        {/* File drop zone — hidden when job is running */}
        {!jobStatus && (
          <>
            <div
              onClick={() => inputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleFileDrop}
              style={{
                border:         `2px dashed ${dragOver ? ds.teal : ds.border}`,
                borderRadius:   ds.radius.lg,
                padding:        '36px 24px',
                textAlign:      'center',
                cursor:         'pointer',
                background:     dragOver ? ds.mint : ds.light,
                transition:     'all 0.2s',
                marginBottom:   16,
              }}
            >
              <div style={{ fontSize: 32, marginBottom: 10 }}>📂</div>
              {file ? (
                <p style={{ fontWeight: 600, color: ds.teal, fontSize: 14, margin: 0 }}>
                  {file.name}
                </p>
              ) : (
                <>
                  <p style={{ fontWeight: 600, color: ds.dark, fontSize: 14, margin: '0 0 4px' }}>
                    Drag & drop a CSV file here
                  </p>
                  <p style={{ fontSize: 13, color: ds.gray, margin: 0 }}>
                    or click to browse · CSV files only
                  </p>
                </>
              )}
            </div>
            <input
              ref={inputRef}
              type="file"
              accept=".csv"
              style={{ display: 'none' }}
              onChange={(e) => {
                const f = e.target.files[0]
                if (f) setFile(f)
                e.target.value = ''
              }}
            />
          </>
        )}

        {/* Progress section */}
        {jobStatus && (
          <div style={{
            background:   ds.light,
            border:       `1px solid ${ds.border}`,
            borderRadius: ds.radius.lg,
            padding:      '18px 20px',
            marginBottom: 16,
          }}>
            {/* Status line */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
              {isRunning && <Spinner />}
              {isDone    && <span style={{ fontSize: 18 }}>✅</span>}
              {isFailed  && <span style={{ fontSize: 18 }}>❌</span>}
              <span style={{ fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 14, color: ds.dark }}>
                {isRunning ? 'Processing…' : isDone ? 'Import Complete' : 'Import Failed'}
              </span>
            </div>

            {/* Progress bar */}
            {jobStatus.total_rows > 0 && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: ds.gray, marginBottom: 4 }}>
                  <span>{jobStatus.processed} / {jobStatus.total_rows} rows</span>
                  <span>{progress}%</span>
                </div>
                <div style={{ height: 7, background: ds.border, borderRadius: 10, overflow: 'hidden' }}>
                  <div style={{
                    height:       '100%',
                    width:        `${progress}%`,
                    background:   isFailed ? ds.red : ds.teal,
                    borderRadius: 10,
                    transition:   'width 0.4s ease',
                  }} />
                </div>
              </div>
            )}

            {/* Stats */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
              <StatChip label="Succeeded" value={jobStatus.succeeded ?? 0} color={ds.green} />
              <StatChip label="Failed"    value={jobStatus.failed ?? 0}    color={jobStatus.failed > 0 ? ds.red : ds.gray} />
              <StatChip label="Total"     value={jobStatus.total_rows ?? 0} color={ds.teal} />
            </div>

            {/* Row-level errors */}
            {jobStatus.errors && jobStatus.errors.length > 0 && (
              <div style={{ marginTop: 14, maxHeight: 120, overflowY: 'auto' }}>
                <p style={{ fontSize: 11, fontWeight: 600, color: ds.red, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 6 }}>
                  Row Errors
                </p>
                {jobStatus.errors.map((e, i) => (
                  <p key={i} style={{ fontSize: 12, color: ds.gray, margin: '0 0 4px', lineHeight: 1.5 }}>
                    • Row {e.row}: {e.message}
                  </p>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Errors */}
        {error && <p style={{ color: ds.red, fontSize: 13, marginBottom: 14 }}>⚠ {error}</p>}

        {/* Actions */}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button
            onClick={() => {
              stopPolling()
              if (isDone) onImported?.()
              onClose()
            }}
            style={secondaryBtn}
          >
            {isDone ? 'Done ✓' : 'Cancel'}
          </button>
          {!jobStatus && (
            <button
              onClick={handleUpload}
              disabled={!file || uploading}
              style={{ ...primaryBtn, opacity: (!file || uploading) ? 0.5 : 1 }}
            >
              {uploading ? 'Uploading…' : '⬆ Upload & Import'}
            </button>
          )}
        </div>
      </div>
    </ModalOverlay>
  )
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatChip({ label, value, color }) {
  return (
    <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: 8, padding: '8px 12px', textAlign: 'center' }}>
      <p style={{ fontSize: 10, fontWeight: 600, color: ds.gray, textTransform: 'uppercase', letterSpacing: '0.5px', margin: '0 0 4px' }}>{label}</p>
      <p style={{ fontSize: 20, fontWeight: 800, color, fontFamily: ds.fontSyne, margin: 0 }}>{value}</p>
    </div>
  )
}

function Spinner() {
  return (
    <span style={{
      display: 'inline-block', width: 16, height: 16,
      border: `2px solid rgba(2,128,144,0.2)`, borderTop: `2px solid ${ds.teal}`,
      borderRadius: '50%', animation: 'spin 0.7s linear infinite', flexShrink: 0,
    }} />
  )
}

function ModalOverlay({ children, onClose }) {
  return (
    <div
      onClick={(e) => e.target === e.currentTarget && onClose()}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: ds.z.modal, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
    >
      <div style={{ background: 'white', borderRadius: ds.radius.xxl, width: 560, maxWidth: '100%', maxHeight: '88vh', overflowY: 'auto', boxShadow: ds.modalShadow }}>
        {children}
      </div>
    </div>
  )
}

const headerStyle  = { padding: '20px 24px', borderBottom: `1px solid ${ds.border}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between', position: 'sticky', top: 0, background: 'white', zIndex: 10 }
const closeBtn     = { background: 'none', border: 'none', fontSize: 20, color: ds.gray, cursor: 'pointer', padding: '4px 8px' }
const primaryBtn   = { display: 'inline-flex', alignItems: 'center', gap: 8, padding: '11px 22px', borderRadius: ds.radius.md, border: 'none', background: ds.teal, color: 'white', fontSize: 13.5, fontWeight: 600, fontFamily: ds.fontSyne, cursor: 'pointer' }
const secondaryBtn = { ...primaryBtn, background: ds.mint, color: ds.tealDark, border: `1px solid ${ds.border}` }
