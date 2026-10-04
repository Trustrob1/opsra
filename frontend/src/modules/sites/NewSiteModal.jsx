/**
 * frontend/src/modules/sites/NewSiteModal.jsx
 * SITE-WEB-1 - "New site" in the builder portal: choose who fills in the details (you or your client) and the
 * business type, then get the form link. The link is shown once (the server keeps only its hash).
 *
 *   token       builder session token
 *   onCreated() called after a link is made, so the parent can refresh its lists
 *   onSubscribe() called when the builder has used their free sites and wants to subscribe
 */
import { useEffect, useState } from 'react'
import { Check, Copy, ExternalLink } from 'lucide-react'
import { Button, Field, Modal, Notice, Segmented, Spinner } from './sitesUi'
import { INPUT, T } from './sitesKit'
import { accessLimit, createMyForm, errorMessage, listPresets } from '../../services/builder_portal.service'

export default function NewSiteModal({ open, onClose, token, onCreated, onSubscribe }) {
  const [presets, setPresets] = useState(null)
  const [audience, setAudience] = useState('builder')
  const [presetId, setPresetId] = useState('')
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [limited, setLimited] = useState(false)
  const [result, setResult] = useState(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!open) return
    setResult(null); setError(''); setLimited(false); setCopied(false); setLabel('')
    listPresets(token)
      .then((rows) => { setPresets(rows); setPresetId((cur) => cur || rows[0]?.id || '') })
      .catch((e) => { setPresets([]); setError(errorMessage(e, 'Could not load the business types.')) })
  }, [open, token])

  async function create() {
    setBusy(true); setError(''); setLimited(false)
    try {
      const res = await createMyForm(token, {
        audience, ...(presetId ? { preset_id: presetId } : {}), ...(label.trim() ? { client_label: label.trim() } : {}),
      })
      setResult(res)
      onCreated && onCreated()
    } catch (e) {
      const lim = accessLimit(e)
      setLimited(!!lim)
      setError(lim ? lim.message : errorMessage(e, 'Could not create the link. Please try again.'))
    } finally {
      setBusy(false)
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(result.url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setError('Could not copy automatically. Select the link and copy it by hand.')
    }
  }

  const forClient = audience === 'client'

  return (
    <Modal open={open} onClose={onClose} title={result ? 'Your link is ready' : 'Start a new site'} width={520}
      footer={result ? (
        <Button variant="primary" onClick={onClose}>Done</Button>
      ) : (
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!presets || (presets.length > 0 && !presetId)} onClick={create}>
            {forClient ? 'Get a link for my client' : 'Get my form link'}
          </Button>
        </>
      )}>
      {presets === null && !result && <Spinner />}

      {presets !== null && !result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Field label="Who will fill in the details?" group>
            <Segmented ariaLabel="Who fills in the form" value={audience} onChange={setAudience}
              options={[{ value: 'builder', label: 'I will' }, { value: 'client', label: 'My client will' }]} />
          </Field>

          {presets.length > 0 ? (
            <Field label="What kind of business is it for?">
              <select value={presetId} onChange={(e) => setPresetId(e.target.value)} style={INPUT}>
                {presets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </Field>
          ) : (
            <Notice tone="warn">No business types are set up yet, so the form will ask for it. You can still continue.</Notice>
          )}

          {forClient && (
            <Field label="Your note for this client (optional)" hint="Only you see this, for example “Adaeze, boutique”.">
              <input value={label} maxLength={120} onChange={(e) => setLabel(e.target.value)} style={INPUT} />
            </Field>
          )}

          <p style={{ margin: 0, fontSize: 12.5, color: T.soft, lineHeight: 1.5 }}>
            {forClient
              ? 'Send them the link. They fill it in on their own phone, with no login. You get the preview first.'
              : 'You get a form that saves as you go. When you submit it, the site appears in My sites.'}
          </p>

          {error && (
            <Notice tone={limited ? 'warn' : 'bad'}>
              {error}
              {limited && onSubscribe && (
                <div style={{ marginTop: 8 }}><Button variant="primary" size="sm" onClick={onSubscribe}>Subscribe to keep building</Button></div>
              )}
            </Notice>
          )}
        </div>
      )}

      {result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Field label={result.audience === 'client' ? 'Send this link to your client' : 'Your form link'}>
            <input readOnly value={result.url} onFocus={(e) => e.target.select()} style={INPUT} aria-label="Form link" />
          </Field>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Button variant="primary" icon={copied ? Check : Copy} onClick={copy}>{copied ? 'Copied' : 'Copy link'}</Button>
            {result.audience !== 'client' && (
              <Button icon={ExternalLink} onClick={() => window.open(result.url, '_blank', 'noopener')}>Open the form</Button>
            )}
          </div>
          <Notice tone="info">
            Copy it now. For safety, the link is only shown once. If you lose it, cancel it and make a new one.
            Your site appears in My sites as soon as the form is submitted.
          </Notice>
          {error && <Notice tone="bad">{error}</Notice>}
        </div>
      )}
    </Modal>
  )
}
