/**
 * frontend/src/modules/sites/BuilderOptionsView.jsx
 * SITE-OPTIONS OPT-2/OPT-3 - the builder portal's "Design options" screen: the shared hub wired to the builder API
 * (token first), plus the "make a new design for this set" form.
 *
 *   token         builder session token
 *   onPayLink(siteId)  go to checkout for the picked site
 */
import { useMemo, useState } from 'react'
import DesignOptionsHub from './DesignOptionsHub'
import NewSiteModal from './NewSiteModal'
import * as svc from '../../services/builder_portal.service'

export default function BuilderOptionsView({ token, onPayLink, showToast }) {
  const [newFor, setNewFor] = useState(null)       // option set id a new design is being made for
  const [reloadKey, setReloadKey] = useState(0)
  const setsApi = useMemo(() => ({
    list: () => svc.listOptionSets(token),
    eligible: () => svc.listOptionEligibleSites(token),
    create: (p) => svc.createOptionSet(token, p),
    get: (id) => svc.getOptionSet(token, id),
    attach: (id, siteId, label) => svc.attachOptionSite(token, id, siteId, label),
    detach: (id, siteId) => svc.detachOptionSite(token, id, siteId),
    choose: (id, itemId) => svc.chooseOptionItem(token, id, itemId),
    close: (id) => svc.closeOptionSet(token, id),
  }), [token])
  const versionsApi = useMemo(() => ({
    list: () => svc.listVersionShares(token),
    sites: () => svc.listVersionableSites(token),
    versions: (siteId) => svc.listSiteVersions(token, siteId),
    create: (p) => svc.createVersionShare(token, p),
    get: (id) => svc.getVersionShare(token, id),
    add: (id, designId, label) => svc.addShareVersion(token, id, designId, label),
    remove: (id, itemId) => svc.removeShareVersion(token, id, itemId),
    choose: (id, itemId) => svc.chooseShareVersion(token, id, itemId),
    close: (id) => svc.closeVersionShare(token, id),
  }), [token])

  return (
    <>
      <DesignOptionsHub versionsApi={versionsApi} setsApi={setsApi} errorMessage={svc.errorMessage} reloadKey={reloadKey}
        showToast={showToast} onPayLink={onPayLink} onNewDesign={(setId) => setNewFor(setId)} />
      <NewSiteModal open={!!newFor} optionSetId={newFor} token={token} onClose={() => { setNewFor(null); setReloadKey((k) => k + 1) }}
        onCreated={() => setReloadKey((k) => k + 1)} />
    </>
  )
}
