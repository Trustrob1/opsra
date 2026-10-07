/**
 * frontend/src/modules/sites/SitesSettingsTab.jsx
 * SITE-1A part 2 — Settings: enable/disable the whole feature (spec L1 — ships for
 * Trust's own org only) and edit the pricing JSON (spec §12.1) as a reviewed textarea,
 * since the shape of `pricing` is a free-form settings blob, not a fixed schema yet.
 */
import { useCallback, useEffect, useState } from 'react'
import { Save } from 'lucide-react'
import { getSiteSettings, updateSiteSettings, errorMessage } from '../../services/sites.service'
import { Card, SectionTitle, Button, Toggle, Notice, Spinner, Field } from './sitesUi'
import { T, TEXTAREA } from './sitesKit'
import PricingForm from './PricingForm'
import DiscountCodesCard from './DiscountCodesCard'

const DESIGN_TOOLS = [
  { key: 'premium_enabled', title: 'Premium designs',
    hint: 'Lets builders order a custom-designed Premium page for their site.' },
  { key: 'site_import_enabled', title: 'Import a finished site',
    hint: 'Lets you upload a site made elsewhere and host it (and make it editable) like a built one.' },
  { key: 'site_library_enabled', title: 'Design library',
    hint: 'Lets you save good imported designs and reuse them on new sites, filled with each site\u2019s own content.' },
]

export default function SitesSettingsTab({ isActive, canEdit, isOwner = false, showToast, onEnabledChange }) {
  const [settings, setSettings] = useState(null)
  const [pricingText, setPricingText] = useState('{}')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [jsonError, setJsonError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const row = await getSiteSettings()
      setSettings(row)
      setPricingText(JSON.stringify(row?.pricing ?? {}, null, 2))
    } catch (e) {
      setError(errorMessage(e, 'Could not load settings.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (isActive) load() }, [isActive, load])

  const toggleEnabled = async (checked) => {
    if (!canEdit) return
    setSaving(true)
    try {
      const row = await updateSiteSettings({ enabled: checked })
      setSettings(row)
      onEnabledChange?.(checked)
      showToast(checked ? 'Site engine turned on' : 'Site engine turned off')
    } catch (e) {
      showToast(errorMessage(e, 'Could not save.'), 'bad')
    } finally {
      setSaving(false)
    }
  }

  const toggleOpenSignup = async (checked) => {
    if (!canEdit) return
    setSaving(true)
    try {
      // Open sign-up ON means members_only OFF.
      const row = await updateSiteSettings({ members_only: !checked })
      setSettings(row)
      showToast(checked ? 'Open sign-up turned on' : 'Open sign-up turned off')
    } catch (e) {
      showToast(errorMessage(e, 'Could not save.'), 'bad')
    } finally {
      setSaving(false)
    }
  }

  const toggleTool = async (tool, checked) => {
    if (!isOwner) return
    setSaving(true)
    try {
      const row = await updateSiteSettings({ [tool.key]: checked })
      setSettings(row)
      showToast(`${tool.title} turned ${checked ? 'on' : 'off'}`)
    } catch (e) {
      showToast(errorMessage(e, 'Could not save.'), 'bad')
    } finally {
      setSaving(false)
    }
  }

  const savePricingObject = async (parsed) => {
    setSaving(true)
    try {
      const row = await updateSiteSettings({ pricing: parsed })
      setSettings(row)
      setPricingText(JSON.stringify(row?.pricing ?? {}, null, 2))
      showToast('Pricing saved')
    } catch (e) {
      showToast(errorMessage(e, 'Could not save.'), 'bad')
    } finally {
      setSaving(false)
    }
  }

  const savePricing = async () => {
    setJsonError(null)
    let parsed
    try {
      parsed = JSON.parse(pricingText)
    } catch {
      setJsonError('That is not valid JSON — check for a missing comma or bracket.')
      return
    }
    setSaving(true)
    try {
      const row = await updateSiteSettings({ pricing: parsed })
      setSettings(row)
      setPricingText(JSON.stringify(row?.pricing ?? {}, null, 2))
      showToast('Pricing saved')
    } catch (e) {
      showToast(errorMessage(e, 'Could not save.'), 'bad')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Spinner />
  if (error) return <Notice tone="bad">{error}</Notice>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18, maxWidth: 760 }}>
      <Card>
        <SectionTitle title="Site engine" hint="Ships for this org only for now (spec L1). While off, Sites list still shows what's there, but building or rendering a new site is blocked." />
        <Toggle checked={!!settings?.enabled} onChange={toggleEnabled} disabled={!canEdit || saving}
          label={settings?.enabled ? 'On — builders can build and preview sites' : 'Off — building is blocked'} />
        {!canEdit && <p style={{ margin: '10px 0 0', fontSize: 12, color: T.muted }}>Only an owner or ops manager can change this.</p>}
      </Card>

      <Card>
        <SectionTitle title="Who can start building" hint="Controls what happens when a new number messages the Site Builder WhatsApp (for example from the Start building button on /sites)." />
        <Toggle checked={settings?.members_only === false} onChange={toggleOpenSignup} disabled={!canEdit || saving}
          label={settings?.members_only === false
            ? 'Open sign-up — anyone who messages is registered and can start building straight away'
            : 'Invite only — new numbers wait for your approval and get the join-link reply'} />
        {!canEdit && <p style={{ margin: '10px 0 0', fontSize: 12, color: T.muted }}>Only an owner or ops manager can change this.</p>}
      </Card>

      <Card>
        <SectionTitle title="Design tools" hint="Switch the extra design features on or off for this org." />
        {DESIGN_TOOLS.map((tool) => (
          <div key={tool.key} style={{ margin: '0 0 14px' }}>
            <Toggle checked={!!settings?.[tool.key]} onChange={(c) => toggleTool(tool, c)} disabled={!isOwner || saving}
              label={`${tool.title} — ${settings?.[tool.key] ? 'on' : 'off'}`} />
            <p style={{ margin: '4px 0 0', fontSize: 12, color: T.muted }}>{tool.hint}</p>
          </div>
        ))}
        {!isOwner && <p style={{ margin: '4px 0 0', fontSize: 12, color: T.muted }}>Only the owner can change these.</p>}
      </Card>

      <PricingForm pricing={settings?.pricing ?? {}} canEdit={canEdit} saving={saving} onSave={savePricingObject} />

      <DiscountCodesCard isActive={isActive} canEdit={canEdit} showToast={showToast} />

      <Card>
        <details>
          <summary style={{ cursor: 'pointer', fontSize: 13.5, fontWeight: 700, color: T.ink }}>Advanced: edit the raw pricing JSON</summary>
          <p style={{ margin: '10px 0 12px', fontSize: 12.5, color: T.muted }}>
            The fields above cover everything in day-to-day use. Only use this if you need a setting the form doesn't show.
            A mistake here can break price calculations.
          </p>
          <Field label="pricing (JSON)" error={jsonError}>
            <textarea style={TEXTAREA} value={pricingText} spellCheck={false} disabled={!canEdit}
              onChange={(e) => setPricingText(e.target.value)} rows={12} />
          </Field>
          {canEdit && (
            <div style={{ marginTop: 12 }}>
              <Button variant="primary" icon={Save} loading={saving} onClick={savePricing}>Save raw JSON</Button>
            </div>
          )}
        </details>
      </Card>
    </div>
  )
}
