/**
 * frontend/src/modules/sites/SitesOptionsTab.jsx
 * SITE-OPTIONS OPT-2/OPT-3 - staff "Design options" tab: versions of one site, or different sites, for every builder or
 * one builder. Staff can create links for a builder, add or remove, record a client's pick, and close. Read-only for
 * roles that cannot edit.
 */
import { useEffect, useMemo, useState } from 'react'
import DesignOptionsHub from './DesignOptionsHub'
import { Field } from './sitesUi'
import { INPUT } from './sitesKit'
import * as svc from '../../services/sites.service'

export default function SitesOptionsTab({ canEdit, showToast }) {
  const [builders, setBuilders] = useState([])
  const [builderId, setBuilderId] = useState('')
  useEffect(() => { svc.listBuilders().then(setBuilders).catch(() => {}) }, [])
  const names = useMemo(
    () => Object.fromEntries(builders.map((b) => [b.id, b.business_name || b.full_name || b.phone_number])), [builders])

  const setsApi = useMemo(() => ({
    list: () => svc.listOptionSets(builderId || undefined),
    eligible: () => svc.listOptionEligibleSites(builderId),
    create: (p) => svc.createOptionSet({ ...p, builder_id: builderId }),
    get: (id) => svc.getOptionSet(id),
    attach: (id, siteId, label) => svc.attachOptionSite(id, siteId, label),
    detach: (id, siteId) => svc.detachOptionSite(id, siteId),
    choose: (id, itemId) => svc.chooseOptionItem(id, itemId),
    close: (id) => svc.closeOptionSet(id),
  }), [builderId])
  const versionsApi = useMemo(() => ({
    list: () => svc.listVersionShares(builderId || undefined),
    sites: () => svc.listVersionableSites(builderId || undefined),
    versions: (siteId) => svc.listSiteVersions(siteId),
    preview: (siteId, designId) => svc.previewPremiumDesign(siteId, designId),
    create: (p) => svc.createVersionShare(p),
    get: (id) => svc.getVersionShare(id),
    add: (id, designId, label) => svc.addShareVersion(id, designId, label),
    remove: (id, itemId) => svc.removeShareVersion(id, itemId),
    choose: (id, itemId) => svc.chooseShareVersion(id, itemId),
    close: (id) => svc.closeVersionShare(id),
  }), [builderId])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <Field label="Builder" style={{ maxWidth: 360 }}>
        <select value={builderId} onChange={(e) => setBuilderId(e.target.value)} style={INPUT}>
          <option value="">All builders</option>
          {builders.map((b) => <option key={b.id} value={b.id}>{b.full_name} — {b.business_name || b.phone_number}</option>)}
        </select>
      </Field>
      <DesignOptionsHub key={builderId} versionsApi={versionsApi} setsApi={setsApi} errorMessage={svc.errorMessage} canEdit={canEdit}
        canCreate builderId={builderId} builderNames={names} showToast={showToast} />
    </div>
  )
}
