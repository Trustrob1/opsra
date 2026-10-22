/**
 * frontend/src/modules/admin/useCatalogSetup.js
 * STORE-13: loads what the "Get started" checklist needs (products, categories, settings, link) and keeps
 * what the owner skipped. Nothing here writes to the server.
 */
import { useCallback, useEffect, useState } from 'react'
import * as adminSvc from '../../services/admin.service'
import { setupSteps, setupComplete, showGetStarted, loadSkipped, saveSkipped } from './catalogSetupLogic'

function store() {
  try { return window.localStorage } catch { return undefined }
}

async function load() {
  try {
    const [items, config, cats, share] = await Promise.all([
      adminSvc.getCatalogItems(),
      adminSvc.getCatalogConfig(),
      adminSvc.getCatalogCategories().catch(() => ({ categories: [] })),
      adminSvc.getCatalogShare().catch(() => null),
    ])
    return {
      ready: true, items: items || [], config: config || {},
      categories: (cats && cats.categories) || [], link: (share && share.short_link) || '',
    }
  } catch {
    // the checklist is a help, never a blocker: if it cannot load, the other tabs still work
    return { ready: true, failed: true, items: [], categories: [], config: {}, link: '' }
  }
}

export default function useCatalogSetup(org, enabled) {
  const [data, setData] = useState({ ready: false, items: [], categories: [], config: {}, link: '' })
  const [skipped, setSkipped] = useState(() => loadSkipped(store(), org))

  const refresh = useCallback(() => load().then(setData), [])

  // the first load; later loads come from refresh()
  useEffect(() => {
    if (!enabled) return undefined
    let alive = true
    load().then((d) => { if (alive) setData(d) })
    return () => { alive = false }
  }, [enabled])

  const skip = useCallback((id) => {
    setSkipped((prev) => {
      const next = { ...prev, [id]: true }
      saveSkipped(store(), org, next)
      return next
    })
  }, [org])

  const steps = setupSteps({ items: data.items, categories: data.categories, config: data.config, skipped })
  const show = data.ready && !data.failed && showGetStarted(data.config) && !setupComplete(steps)
  return { ...data, steps, show, refresh, skip, markShared: () => skip('share') }
}
