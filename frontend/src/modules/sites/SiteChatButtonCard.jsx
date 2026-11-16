/**
 * frontend/src/modules/sites/SiteChatButtonCard.jsx
 * WEBCHAT-SITE-2 - the "Chat with us" button on ONE website. Off for every website until switched on here, so a business that
 * builds sites for clients never puts its own chat on their websites. The button shows on the preview at once and on the
 * live site after the next publish.
 */
import { useCallback, useEffect, useState } from 'react'
import { MessageCircle } from 'lucide-react'
import { getSiteChatButton, setSiteChatButton, errorMessage } from '../../services/sites.service'
import { Card, SectionTitle, Notice, Spinner, Toggle } from './sitesUi'
import { T } from './sitesKit'

export default function SiteChatButtonCard({ siteId, canEdit, showToast }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setError(null)
    try { setData(await getSiteChatButton(siteId)) } catch (e) { setError(errorMessage(e, 'Could not load the chat button setting.')) } finally { setLoading(false) }
  }, [siteId])
  useEffect(() => { setLoading(true); load() }, [load])

  const change = async (next) => {
    setBusy(true); setError(null)
    try {
      setData(await setSiteChatButton(siteId, next))
      showToast?.(next ? 'Chat button on for this website' : 'Chat button off for this website')
    } catch (e) {
      setError(errorMessage(e, 'Could not change the chat button.'))
    } finally { setBusy(false) }
  }

  return (
    <Card>
      <SectionTitle title="Chat button" hint="A Chat with us button on this website that opens your web chat in a new tab." />
      {loading ? <Spinner /> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <Toggle checked={!!data?.enabled} disabled={!canEdit || busy || !data} onChange={change}
            label={data?.enabled ? 'On for this website' : 'Off for this website'} />
          {data?.enabled && !data?.account_ready && (
            <Notice tone="warn" icon={MessageCircle}>Your web chat is not switched on or not in your plan yet, so the button will not show. Open Admin &gt; Web Chat to set it up.</Notice>
          )}
          <p style={{ margin: 0, fontSize: 11.5, color: T.muted }}>Off by default. Switch it on only for a website that belongs to you. It shows on the preview after the next render, and on the live website after the next publish.</p>
          {error && <Notice tone="bad">{error}</Notice>}
        </div>
      )}
    </Card>
  )
}
