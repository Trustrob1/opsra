/**
 * frontend/src/modules/sites/SitesHostingTab.jsx
 * SITE-3 part 3 — Hosting queue (spec §13, §11.4): Standard jobs done by hand at QServers.
 * Each job shows a live SLA countdown (green → amber 12 h before due → red when overdue),
 * the 6-step checklist, and the actions: take the job, download the zip, re-check the domain,
 * use the backup, mark live.
 *
 * Pattern 26: stays mounted; fetches (and ticks the countdown) only while `isActive`.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { CloudUpload, Download, RefreshCw, ArrowLeftRight, Rocket, UserPlus, UserMinus, Server, Clock, TriangleAlert } from 'lucide-react'
import {
  listHostingJobs, patchHostingJob, recheckJobDomain, switchToBackupDomain, markJobLive, markJobRenewed, downloadSiteExport, publishSite, errorMessage,
} from '../../services/sites.service'
import { Card, Button, Badge, Notice, Spinner, Empty, Field, Modal, Segmented, Toggle } from './sitesUi'
import { Fact } from './sitesOpsUi'
import { T, INPUT, TEXTAREA, money, dateTime, JOB_STATUS, SLA, formatCountdown, useNow } from './sitesKit'

const AMBER_MS = 12 * 3600 * 1000

/** Mirrors site_ops_service._sla_state so colours change live between fetches. */
function slaState(job, nowMs) {
  if (job.status === 'done') return 'done'
  if (!job.sla_due_at) return 'none'
  const left = Date.parse(job.sla_due_at) - nowMs
  if (left <= 0) return 'red'
  return left <= AMBER_MS ? 'amber' : 'green'
}

export default function SitesHostingTab({ isActive, user, canEdit, showToast, onGoOrders, onChanged }) {
  const now = useNow(isActive)
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [scope, setScope] = useState('all')
  const [showDone, setShowDone] = useState(false)
  const [liveJob, setLiveJob] = useState(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      setJobs(await listHostingJobs({ mine: scope === 'mine', include_done: showDone }))
    } catch (e) {
      setError(errorMessage(e, 'Could not load the hosting queue.'))
    } finally {
      setLoading(false)
    }
  }, [scope, showDone])

  useEffect(() => {
    if (!isActive) return undefined
    setLoading(true)
    load()
    const t = setInterval(load, 60000) // pick up new jobs and other people's changes
    return () => clearInterval(t)
  }, [isActive, load])

  const replaceJob = useCallback((job) => setJobs((rows) => rows.map((r) => (r.id === job.id ? job : r))), [])
  const changed = useCallback(async () => { await load(); onChanged?.() }, [load, onChanged])

  const overdue = useMemo(() => jobs.filter((j) => slaState(j, now) === 'red').length, [jobs, now])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
        <Segmented ariaLabel="Which jobs to show" value={scope} onChange={setScope}
          options={[{ value: 'all', label: 'All jobs' }, { value: 'mine', label: 'Assigned to me' }]} />
        <Toggle checked={showDone} onChange={setShowDone} label="Show finished jobs" />
      </div>

      {overdue > 0 && (
        <Notice tone="bad" icon={TriangleAlert}>
          <strong>{overdue} job{overdue === 1 ? ' is' : 's are'} past the 24-hour deadline.</strong> The builder was promised “live within 24 hours”.
        </Notice>
      )}
      {error && <Notice tone="bad">{error}</Notice>}

      {loading ? <Spinner /> : jobs.length === 0 ? (
        <Card>
          <Empty icon={Server} title={scope === 'mine' ? 'Nothing assigned to you' : 'The queue is clear'}
            text={scope === 'mine' ? 'Take a job from “All jobs” and it will show up here.'
              : 'A job appears here when a paid Standard order is approved — with a 24-hour clock that starts at payment.'}
            action={scope === 'mine' && <Button onClick={() => setScope('all')}>Show all jobs</Button>} />
        </Card>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {jobs.map((job) => (
            <JobCard key={job.id} job={job} nowMs={now} user={user} canEdit={canEdit} showToast={showToast}
              onReplace={replaceJob} onReload={changed} onMarkLive={() => setLiveJob(job)} onGoOrders={onGoOrders} />
          ))}
        </div>
      )}

      <MarkLiveModal job={liveJob} onClose={() => setLiveJob(null)} showToast={showToast}
        onDone={async () => { setLiveJob(null); showToast('Marked live — the builder has been told'); await changed() }} />
    </div>
  )
}

function JobCard({ job, nowMs, user, canEdit, showToast, onReplace, onReload, onMarkLive, onGoOrders }) {
  const [busy, setBusy] = useState(null)
  const [notes, setNotes] = useState(job.notes || '')
  const [result, setResult] = useState(null)
  useEffect(() => { setNotes(job.notes || '') }, [job.notes])

  const state = slaState(job, nowMs)
  const sla = SLA[state]
  const st = JOB_STATUS[job.status] || JOB_STATUS.queued
  const done = job.status === 'done'
  const waitingOnBuilder = job.order_status === 'needs_builder_choice'
  const isRenewal = job.order_kind === 'renewal'
  const locked = !canEdit || done || waitingOnBuilder
  const steps = job.checklist || []
  const stepsDone = steps.filter((s) => s.done).length
  const registered = steps.some((s) => s.key === 'register_domain' && s.done)
  const usingBackup = job.backup_domain && job.domain_used === job.backup_domain
  const mine = job.assigned_to && job.assigned_to === user?.id
  const secondsLeft = job.sla_due_at ? Math.round((Date.parse(job.sla_due_at) - nowMs) / 1000) : null

  const run = async (key, fn, okText) => {
    setBusy(key)
    try {
      const res = await fn()
      if (res?.job) { onReplace(res.job); setResult({ tone: res.available === false ? 'warn' : 'info', text: res.message }) }
      else if (res?.id) onReplace(res)
      if (okText) showToast(okText)
      return res
    } catch (e) {
      showToast(errorMessage(e), 'bad')
      await onReload() // the job may have changed under us
      return null
    } finally {
      setBusy(null)
    }
  }

  const toggleStep = (step) => run(`step:${step.key}`, () => patchHostingJob(job.id, { step: step.key, step_done: !step.done }))
  const assign = (uid) => run('assign', () => patchHostingJob(job.id, { assigned_to: uid }), uid ? 'Job assigned to you' : 'Job unassigned')
  const saveNotes = () => { if (!locked && notes !== (job.notes || '')) run('notes', () => patchHostingJob(job.id, { notes })) }
  const renewed = () => run('renewed', () => markJobRenewed(job.id), 'Marked renewed — the builder has been told')
  const recheck = () => run('recheck', () => recheckJobDomain(job.id))
  const backup = async () => { const res = await run('backup', () => switchToBackupDomain(job.id)); if (res) onReload() }
  const publish = async () => {
    setBusy('publish')
    try {
      const r = await publishSite(job.site_id)
      showToast(`Published to Cloudflare: ${r.files} files for ${r.domain}`)
    } catch (e) { showToast(errorMessage(e, 'Could not publish the site.'), 'bad') } finally { setBusy(null) }
  }
  const zip = async () => {
    setBusy('zip')
    try { await downloadSiteExport(job.site_id, job.site_slug) } catch (e) { showToast(errorMessage(e, 'Could not build the zip.'), 'bad') } finally { setBusy(null) }
  }

  return (
    <Card pad={0} style={{ borderLeft: `4px solid ${state === 'red' ? T.bad : state === 'amber' ? '#E0A030' : state === 'green' ? T.good : T.line}` }}>
      <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <div style={{ minWidth: 0 }}>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: T.ink, overflowWrap: 'anywhere' }}>{job.domain_used || job.domain}</h3>
            <p style={{ margin: '3px 0 0', fontSize: 12.5, color: T.muted }}>
              {job.client_business_name || 'Unnamed site'} · {money(job.order_amount)} · {job.route === 'express' ? 'Express' : 'Standard'}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <Badge tone={sla.tone} icon={Clock}>
              {done ? 'Done' : `${sla.label} · ${formatCountdown(secondsLeft)}`}
            </Badge>
            <Badge tone={st.tone}>{st.label}</Badge>
            {isRenewal && <Badge tone="info">Renewal</Badge>}
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
          <Fact label="Assigned to">{job.assigned_name || 'Nobody yet'}</Fact>
          <Fact label="Deadline">{job.sla_due_at ? dateTime(job.sla_due_at) : '—'}</Fact>
          <Fact label="Main domain">{job.domain}</Fact>
          <Fact label="Backup domain">{job.backup_domain ? <>{job.backup_domain}{usingBackup && <> <Badge tone="warn">in use</Badge></>}</> : '—'}</Fact>
        </div>

        {waitingOnBuilder && (
          <Notice tone="warn" icon={TriangleAlert}>
            Both domains were taken, so this job is paused until the builder picks a new one.{' '}
            {onGoOrders && <a href="#" onClick={(e) => { e.preventDefault(); onGoOrders() }} style={{ color: T.teal, fontWeight: 600 }}>Open the order →</a>}
          </Notice>
        )}
        {result && <Notice tone={result.tone}>{result.text}</Notice>}

        <div>
          <p className="tnum" style={{ margin: '0 0 6px', fontSize: 12, fontWeight: 700, color: T.muted, textTransform: 'uppercase', letterSpacing: '.6px' }}>
            Checklist · {stepsDone} of {steps.length} done
          </p>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column' }}>
            {steps.map((s) => (
              <li key={s.key}>
                <button type="button" role="checkbox" aria-checked={!!s.done} disabled={locked || busy === `step:${s.key}`} onClick={() => toggleStep(s)}
                  style={{ all: 'unset', boxSizing: 'border-box', display: 'flex', alignItems: 'center', gap: 10, width: '100%', minHeight: 44, cursor: locked ? 'default' : 'pointer',
                    opacity: locked && !s.done ? 0.65 : 1 }}>
                  <span aria-hidden="true" style={{ width: 20, height: 20, borderRadius: 6, flexShrink: 0, border: `1.5px solid ${s.done ? T.teal : T.lineStrong}`,
                    background: s.done ? T.teal : '#fff', color: '#fff', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700 }}>
                    {s.done ? '✓' : ''}
                  </span>
                  <span style={{ fontSize: 13.5, color: s.done ? T.muted : T.ink, textDecoration: s.done ? 'line-through' : 'none' }}>{s.label}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <Field label="Notes" hint="Saved when you click away.">
          <textarea style={{ ...TEXTAREA, minHeight: 64 }} value={notes} disabled={locked} maxLength={5000}
            onChange={(e) => setNotes(e.target.value)} onBlur={saveNotes} />
        </Field>

        {!done && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {canEdit && !mine && <Button icon={UserPlus} loading={busy === 'assign'} onClick={() => assign(user?.id)}>Take job</Button>}
            {canEdit && job.assigned_to && <Button variant="ghost" icon={UserMinus} loading={busy === 'assign'} onClick={() => assign(null)}>Unassign</Button>}
            {!isRenewal && <Button icon={Download} loading={busy === 'zip'} onClick={zip}>Download zip</Button>}
            {canEdit && !isRenewal && <Button icon={CloudUpload} loading={busy === 'publish'} onClick={publish}>Publish to Cloudflare</Button>}
            {canEdit && !waitingOnBuilder && !registered && !isRenewal && (<>
              <Button icon={RefreshCw} loading={busy === 'recheck'} onClick={recheck}>Re-check domain</Button>
              {job.backup_domain && !usingBackup && <Button icon={ArrowLeftRight} loading={busy === 'backup'} onClick={backup}>Use backup domain</Button>}
            </>)}
            {canEdit && !waitingOnBuilder && !isRenewal && <Button variant="primary" icon={Rocket} onClick={onMarkLive}>Mark live</Button>}
            {canEdit && isRenewal && <Button variant="primary" icon={Rocket} loading={busy === 'renewed'} onClick={renewed}>Mark renewed</Button>}
          </div>
        )}
        {done && job.live_url && (
          <p style={{ margin: 0, fontSize: 13 }}>Live at <a href={job.live_url} target="_blank" rel="noreferrer noopener" style={{ color: T.teal, fontWeight: 600 }}>{job.live_url}</a></p>
        )}
      </div>
    </Card>
  )
}

function MarkLiveModal({ job, onClose, onDone, showToast }) {
  const [url, setUrl] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  useEffect(() => { if (job) { setUrl(`https://${job.domain_used || job.domain}`); setError(null) } }, [job])
  if (!job) return null
  const submit = async () => {
    setSaving(true)
    setError(null)
    try {
      await markJobLive(job.id, url.trim())
      onDone()
    } catch (e) {
      const msg = errorMessage(e, 'Could not mark this live.')
      setError(msg) // stays in the dialog next to the field — it's a fixable input problem, not a crash
      showToast(msg, 'bad')
    } finally {
      setSaving(false)
    }
  }
  return (
    <Modal open onClose={onClose} title={`Mark ${job.domain_used || job.domain} live`}
      footer={<><Button onClick={onClose}>Not yet</Button><Button variant="primary" icon={Rocket} loading={saving} onClick={submit}>Mark live</Button></>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Notice tone="info">We'll open this address to check it uses https and loads (HTTP 200). Then the order goes live and the builder gets the link.</Notice>
        <Field label="Live address" error={error}>
          <input style={INPUT} value={url} onChange={(e) => setUrl(e.target.value)} autoCapitalize="none" autoCorrect="off" spellCheck={false}
            inputMode="url" autoFocus />
        </Field>
      </div>
    </Modal>
  )
}
