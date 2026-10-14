/**
 * frontend/src/modules/sites/DesignOptionsHub.jsx
 * SITE-OPTIONS OPT-3 - the "Design options" screen: a switch between "Versions of one site" (several saved versions of
 * one Premium site, one link) and "Different sites" (several separate sites for one client, one link). Only the chosen
 * side is mounted. The adapters come from the builder view or the staff tab.
 */
import { useState } from 'react'
import OptionSetsPanel from './OptionSetsPanel'
import VersionSharesPanel from './VersionSharesPanel'
import { Segmented } from './sitesUi'

export default function DesignOptionsHub({ versionsApi, setsApi, errorMessage, canEdit, canCreate = true, builderId, builderNames,
  onPayLink, onNewDesign, reloadKey, showToast }) {
  const [mode, setMode] = useState('versions')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <Segmented ariaLabel="What to show the client" value={mode} onChange={setMode}
        options={[{ value: 'versions', label: 'Versions of one site' }, { value: 'sites', label: 'Different sites' }]} />
      {mode === 'versions' ? (
        <VersionSharesPanel api={versionsApi} errorMessage={errorMessage} canEdit={canEdit} canCreate={canCreate}
          builderNames={builderNames} onPayLink={onPayLink} showToast={showToast} />
      ) : (
        <OptionSetsPanel api={setsApi} errorMessage={errorMessage} canEdit={canEdit} builderId={builderId} builderNames={builderNames}
          onPayLink={onPayLink} onNewDesign={onNewDesign} reloadKey={reloadKey} showToast={showToast} />
      )}
    </div>
  )
}
