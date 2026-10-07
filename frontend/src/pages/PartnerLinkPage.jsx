/**
 * frontend/src/pages/PartnerLinkPage.jsx
 * PARTNER-1A — a Launch Partner's permanent link: /p/:slug.
 *
 * Standalone page, no auth. Each visit asks the backend for a fresh single-client brief form and
 * sends the visitor straight to it (/f/:token). The page itself only shows a short loading or error state.
 */
import { useEffect, useRef, useState } from 'react'
import { openPartnerLink } from '../services/site_forms.service'

const S = {
  page: { minHeight: '100vh', background: '#f0f4f7', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, fontFamily: "'DM Sans', system-ui, sans-serif" },
  card: { background: 'white', borderRadius: 14, boxShadow: '0 2px 12px rgba(0,0,0,0.08)', padding: '28px 24px', maxWidth: 420, width: '100%', textAlign: 'center', boxSizing: 'border-box' },
  logo: { fontFamily: "'Syne', system-ui, sans-serif", fontWeight: 800, fontSize: 20, color: '#028090', marginBottom: 14 },
  h1: { fontSize: 19, fontWeight: 700, color: '#0a1f2e', margin: '0 0 8px' },
  p: { fontSize: 14, lineHeight: 1.5, color: '#4a6375', margin: 0 },
}

function errorText(err) {
  const status = err?.response?.status
  if (status === 410) return ['This link is not active', 'Please contact the person who sent it to you.']
  if (status === 429) return ['This link is busy', 'Please try again in a few minutes.']
  if (status === 404) return ['This link isn’t valid', 'Please check the link or ask the person who sent it for a new one.']
  return ['We couldn’t open this link', 'Please check your connection and try again.']
}

export default function PartnerLinkPage({ slug }) {
  const [error, setError] = useState(null)
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return          // React strict mode runs effects twice: open once only
    started.current = true
    openPartnerLink(slug)
      .then((data) => {
        const path = (() => { try { return new URL(data?.url, window.location.origin).pathname } catch { return '' } })()
        if (/^\/f\/[A-Za-z0-9_-]{20,80}$/.test(path)) window.location.replace(path)
        else setError(['We couldn’t open this link', 'Please try again in a minute.'])
      })
      .catch((err) => setError(errorText(err)))
  }, [slug])

  return (
    <div style={S.page}>
      <div style={S.card}>
        <div style={S.logo}>opsra</div>
        {error ? (
          <>
            <h1 style={S.h1}>{error[0]}</h1>
            <p style={S.p}>{error[1]}</p>
          </>
        ) : (
          <>
            <h1 style={S.h1}>Opening your form…</h1>
            <p style={S.p}>One moment, please.</p>
          </>
        )}
      </div>
    </div>
  )
}
