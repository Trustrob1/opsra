/**
 * BulkUploadModal.jsx — Bulk payment confirmation via CSV/Excel upload (Method 3)
 *
 * Flow:
 *   1. User selects a CSV or XLSX file
 *   2. POST /api/v1/subscriptions/bulk-confirm → 202 + job_id
 *   3. Poll GET /api/v1/subscriptions/bulk-confirm/{job_id} every 2s
 *   4. Display results: confirmed, failed, per-row errors
 *
 * Backend enforces:
 *   - MIME allowlist (CSV/XLSX only) and 25 MB cap (§11.5)
 *   - Duplicate reference check per row (DRD §6.4)
 *   - Phone fallback matching when subscription_id absent
 */
import { useState, useRef, useEffect } from 'react'
import { ds } from '../../utils/ds'
import { bulkConfirmUpload, pollBulkConfirmJob } from '../../services/renewal.service'

const ACCEPTED_TYPES = '.csv,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const POLL_INTERVAL_MS = 2000

// ─────────────────────────────────────────────────────────────────────────────

export default function BulkUploadModal({ onClose, onComplete }) {
  const [file, setFile]           = useState(null)
  const [phase, setPhase]         = useState('select')  // 'select' | 'uploading' | 'polling' | 'done' | 'error'
  const [jobStatus, setJobStatus] = useState(null)      // full job response data
  const [uploadError, setUploadError] = useState(null)
  const pollRef                   = useRef(null)
  const fileInputRef              = useRef(null)

  // Clean up polling on unmount
  useEffect(() => () => clearInterval(pollRef.current), [])

  const handleFileChange = (e) => {
    const f = e.target.files?.[0]
    if (!f) return
    setFile(f)
    setUploadError(null)
  }

  const handleUpload = async () => {
    if (!file) { setUploadError('Please select a file first.'); return }
    setPhase('uploading')
    setUploadError(null)

    try {
      const res = await bulkConfirmUpload(file)
      if (!res.success) throw new Error(res.error ?? 'Upload failed')
      const jobId = res.data?.job_id
      if (!jobId) throw new Error('No job ID returned by server')
      setPhase('polling')
      startPolling(jobId)
    } catch (err) {
      const detail = err?.response?.data?.detail
      setUploadError(
        typeof detail === 'string'
          ? detail
          : err.message ?? 'Upload failed. Check the file format and try again.',
      )
      setPhase('select')
    }
  }

  const startPolling = (jobId) => {
    pollRef.current = setInterval(async () => {
      try {
        const res = await pollBulkConfirmJob(jobId)
        if (!res.success) return
        const job = res.data
        setJobStatus(job)
        if (job.status === 'done' || job.status === 'failed') {
          clearInterval(pollRef.current)
          setPhase('done')
        }
      } catch {
        // Transient network error — keep polling
      }
    }, POLL_INTERVAL_MS)
  }

  const handleReset = () => {
    setFile(null)
    setJobStatus(null)
    setUploadError(null)
    setPhase('select')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  return (
    <div style={overlay} onClick={(e) => { if (e.target === e.currentTarget && phase !== 'polling') onClose() }}>
      <div style={modal}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
          <div>
            <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: ds.dark, margin: 0 }}>
              Bulk Payment Upload
            </h2>
            <p style={{ fontSize: 12, color: ds.gray, margin: '4px 0 0' }}>
              Upload a CSV or Excel file to confirm multiple payments at once
            </p>
          </div>
          {phase !== 'polling' && (
            <button onClick={onClose} style={closeBtn}>✕</button>
          )}
        </div>

        {/* ── Phase: select ── */}
        {(phase === 'select' || phase === 'uploading') && (
          <>
            {/* Format guide */}
            <div style={infoBox}>
              <p style={{ fontWeight: 600, margin: '0 0 6px', fontSize: 13 }}>Required CSV columns:</p>
              <code style={{ fontSize: 12, color: '#2d5a70', lineHeight: 1.8, display: 'block' }}>
                subscription_id, amount_paid, payment_channel, payment_date, payment_reference (optional)
              </code>
              <p style={{ fontSize: 11, color: ds.gray, margin: '8px 0 0' }}>
                If subscription_id is blank, the backend will attempt to match by phone number.
                Maximum file size: 25 MB.
              </p>
            </div>

            {/* File drop zone */}
            <div
              onClick={() => fileInputRef.current?.click()}
              style={{
                border: `2px dashed ${file ? ds.teal : '#c8d8e0'}`,
                borderRadius: 12,
                padding: '32px 24px',
                textAlign: 'center',
                cursor: 'pointer',
                transition: 'border-color 0.2s, background 0.2s',
                background: file ? 'rgba(0,140,160,0.04)' : '#f8fbfc',
                marginBottom: 16,
              }}
            >
              <div style={{ fontSize: 32, marginBottom: 8 }}>📄</div>
              {file ? (
                <>
                  <p style={{ fontWeight: 600, fontSize: 14, color: ds.teal, margin: 0 }}>{file.name}</p>
                  <p style={{ fontSize: 12, color: ds.gray, margin: '4px 0 0' }}>
                    {(file.size / 1024).toFixed(1)} KB — click to change
                  </p>
                </>
              ) : (
                <>
                  <p style={{ fontWeight: 600, fontSize: 14, color: ds.dark, margin: 0 }}>
                    Click to select a CSV or Excel file
                  </p>
                  <p style={{ fontSize: 12, color: ds.gray, margin: '4px 0 0' }}>.csv or .xlsx</p>
                </>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED_TYPES}
                onChange={handleFileChange}
                style={{ display: 'none' }}
              />
            </div>

            {uploadError && <div style={errorBox}>⚠ {uploadError}</div>}

            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
              <button onClick={onClose} disabled={phase === 'uploading'} style={cancelBtn}>Cancel</button>
              <button
                onClick={handleUpload}
                disabled={!file || phase === 'uploading'}
                style={{ ...submitBtn, opacity: (!file || phase === 'uploading') ? 0.6 : 1 }}
              >
                {phase === 'uploading' ? '⏳ Uploading…' : '⬆ Upload & Process'}
              </button>
            </div>
          </>
        )}

        {/* ── Phase: polling ── */}
        {phase === 'polling' && (
          <div style={{ textAlign: 'center', padding: '24px 0' }}>
            <div style={spinner} />
            <p style={{ fontWeight: 600, fontSize: 15, color: ds.dark, margin: '16px 0 4px' }}>
              Processing payments…
            </p>
            <p style={{ fontSize: 13, color: ds.gray }}>
              This may take a moment. Please do not close this window.
            </p>
            {jobStatus && (
              <div style={{ marginTop: 20, textAlign: 'left' }}>
                <ProgressBar
                  confirmed={jobStatus.confirmed ?? 0}
                  failed={jobStatus.failed ?? 0}
                  total={jobStatus.total ?? 0}
                />
              </div>
            )}
          </div>
        )}

        {/* ── Phase: done ── */}
        {phase === 'done' && jobStatus && (
          <>
            <ResultsSummary jobStatus={jobStatus} />

            {/* Per-row errors */}
            {Array.isArray(jobStatus.errors) && jobStatus.errors.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <p style={{ fontSize: 13, fontWeight: 600, color: ds.dark, marginBottom: 8 }}>
                  Row errors ({jobStatus.errors.length}):
                </p>
                <div style={{ maxHeight: 180, overflowY: 'auto', border: '1px solid #e2ecf0', borderRadius: 8 }}>
                  {jobStatus.errors.map((e, i) => (
                    <div
                      key={i}
                      style={{
                        padding: '8px 14px',
                        fontSize: 12,
                        color: '#5a2020',
                        background: i % 2 === 0 ? '#FEF2F2' : '#FFF5F5',
                        borderBottom: i < jobStatus.errors.length - 1 ? '1px solid #FECACA' : 'none',
                      }}
                    >
                      {/* Pattern 21: render e.row and e.message, not the object */}
                      <strong>Row {e.row}:</strong> {e.message}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end', marginTop: 24 }}>
              <button onClick={handleReset} style={cancelBtn}>Upload Another</button>
              <button onClick={onComplete} style={submitBtn}>Done</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function ProgressBar({ confirmed, failed, total }) {
  const pct = total > 0 ? Math.round(((confirmed + failed) / total) * 100) : 0
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: ds.gray, marginBottom: 6 }}>
        <span>{confirmed + failed} / {total} processed</span>
        <span>{pct}%</span>
      </div>
      <div style={{ height: 8, background: '#e2ecf0', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: ds.teal, transition: 'width 0.4s ease', borderRadius: 4 }} />
      </div>
    </div>
  )
}

function ResultsSummary({ jobStatus }) {
  const allOk = (jobStatus.failed ?? 0) === 0
  return (
    <div style={{ background: allOk ? '#F0FDF4' : '#FEF9EC', border: `1px solid ${allOk ? '#BBF7D0' : '#FDE68A'}`, borderRadius: 12, padding: '20px 24px', marginBottom: 16 }}>
      <p style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: ds.dark, margin: '0 0 12px' }}>
        {allOk ? '✅ Bulk upload complete' : '⚠ Completed with errors'}
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
        {[
          { label: 'Total rows',  value: jobStatus.total     ?? 0, color: ds.dark },
          { label: 'Confirmed',   value: jobStatus.confirmed  ?? 0, color: ds.green },
          { label: 'Failed',      value: jobStatus.failed     ?? 0, color: '#B91C1C' },
        ].map(({ label, value, color }) => (
          <div key={label} style={{ textAlign: 'center' }}>
            <p style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 24, color, margin: 0 }}>{value}</p>
            <p style={{ fontSize: 12, color: ds.gray, margin: '2px 0 0' }}>{label}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const overlay = {
  position: 'fixed', inset: 0,
  background: 'rgba(0,0,0,0.45)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  zIndex: ds.z?.modal ?? 1000,
  padding: 24,
}

const modal = {
  background: 'white', borderRadius: 16,
  padding: '28px 32px',
  width: '100%', maxWidth: 580,
  boxShadow: '0 24px 64px rgba(0,0,0,0.18)',
  fontFamily: ds.fontDm,
  maxHeight: '90vh', overflowY: 'auto',
}

const closeBtn = {
  background: 'none', border: 'none', fontSize: 18,
  color: ds.gray, cursor: 'pointer', padding: 4, lineHeight: 1,
}

const infoBox = {
  background: '#f0f8fb', border: '1px solid #c8e0eb',
  borderRadius: 10, padding: '14px 18px', marginBottom: 16,
  color: ds.dark,
}

const errorBox = {
  background: '#FEF2F2', border: '1px solid #FECACA',
  borderRadius: 8, padding: '10px 14px',
  fontSize: 13, color: '#B91C1C', marginBottom: 16,
}

const cancelBtn = {
  background: 'white', border: '1.5px solid #d1dde4',
  borderRadius: 9, padding: '10px 20px',
  fontSize: 14, fontWeight: 500, color: ds.gray,
  cursor: 'pointer', fontFamily: ds.fontDm,
}

const submitBtn = {
  background: ds.teal, color: 'white',
  border: 'none', borderRadius: 9,
  padding: '10px 22px', fontSize: 14,
  fontWeight: 600, cursor: 'pointer',
  fontFamily: ds.fontSyne,
}

const spinner = {
  width: 40, height: 40,
  border: `4px solid rgba(0,140,160,0.2)`,
  borderTopColor: ds.teal,
  borderRadius: '50%',
  animation: 'spin 0.9s linear infinite',
  margin: '0 auto',
}
