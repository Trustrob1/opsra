/**
 * frontend/src/modules/sites/SitesOptionsTab.jsx
 * SITE-OPTIONS OPT-2 - staff "Options" tab: every builder's option sets, or one builder's. Staff can create sets for a
 * builder, add or remove designs, record a client's pick, and close a set. Read-only for roles that cannot edit.
 */
import { useEffect, useMemo, useState } from 'react'
import OptionSetsPanel from './OptionSetsPanel'
import { Field } from './sitesUi'
import { INPUT } from './sitesKit'
import * as svc from '../../services/sites.service'

export default function SitesOptionsTab({ canEdit, showToast }) {
  const [builders, setBuilders] = useState([])
  const [builderId, setBuilderId] = useState('')
  useEffect(() => { svc.listBuilders().then(setBuilders).catch(() => {}) }, [])
  const names = useMemo(
    () => Object.fromEntries(builders.map((b) => [b.id, b.business_name || b.full_name || b.phone_number])), [builders])

  const api = useMemo(() => ({
    list: () => svc.listOptionSets(builderId || undefined),
    eligible: () => svc.listOptionEligibleSites(builderId),
    create: (p) => svc.createOptionSet({ ...p, builder_id: builderId }),
    get: (id) => svc.getOptionSet(id),
    attach: (id, siteId, label) => svc.attachOptionSite(id, siteId, label),
    detach: (id, siteId) => svc.detachOptionSite(id, siteId),
    choose: (id, itemId) => svc.chooseOptionItem(id, itemId),
    close: (id) => svc.closeOptionSet(id),
  }), [builderId])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <Field label="Builder" style={{ maxWidth: 360 }}>
        <select value={builderId} onChange={(e) => setBuilderId(e.target.value)} style={INPUT}>
          <option value="">All builders</option>
          {builders.map((b) => <option key={b.id} value={b.id}>{b.full_name} — {b.business_name || b.phone_number}</option>)}
        </select>
      </Field>
      <OptionSetsPanel key={builderId} api={api} errorMessage={svc.errorMessage} canEdit={canEdit} builderId={builderId} builderNames={names}
        showToast={showToast} />
    </div>
  )
}
