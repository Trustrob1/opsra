/**
 * frontend/src/modules/sites/BuilderOptionsView.jsx
 * SITE-OPTIONS OPT-2 - the builder portal's "Design options" screen: the shared OptionSetsPanel wired to the builder
 * API (token first), plus the "make a new design for this set" form.
 *
 *   token         builder session token
 *   onPayLink(siteId)  go to checkout for the picked design
 */
import { useMemo, useState } from 'react'
import OptionSetsPanel from './OptionSetsPanel'
import NewSiteModal from './NewSiteModal'
import * as svc from '../../services/builder_portal.service'

export default function BuilderOptionsView({ token, onPayLink, showToast }) {
  const [newFor, setNewFor] = useState(null)       // option set id a new design is being made for
  const [reloadKey, setReloadKey] = useState(0)
  const api = useMemo(() => ({
    list: () => svc.listOptionSets(token),
    eligible: () => svc.listOptionEligibleSites(token),
    create: (p) => svc.createOptionSet(token, p),
    get: (id) => svc.getOptionSet(token, id),
    attach: (id, siteId, label) => svc.attachOptionSite(token, id, siteId, label),
    detach: (id, siteId) => svc.detachOptionSite(token, id, siteId),
    choose: (id, itemId) => svc.chooseOptionItem(token, id, itemId),
    close: (id) => svc.closeOptionSet(token, id),
  }), [token])

  return (
    <>
      <OptionSetsPanel api={api} errorMessage={svc.errorMessage} reloadKey={reloadKey} showToast={showToast}
        onPayLink={onPayLink} onNewDesign={(setId) => setNewFor(setId)} />
      <NewSiteModal open={!!newFor} optionSetId={newFor} token={token} onClose={() => { setNewFor(null); setReloadKey((k) => k + 1) }}
        onCreated={() => setReloadKey((k) => k + 1)} />
    </>
  )
}
