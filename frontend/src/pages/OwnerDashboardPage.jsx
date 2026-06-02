/**
 * frontend/src/pages/OwnerDashboardPage.jsx
 *
 * PERF-1C — External owner dashboard.
 * Accessed via /owner-dashboard/:token (public URL, no JWT).
 * PIN gate → session token stored in sessionStorage (clears on tab close).
 * Session token sent as Authorization header for all subsequent requests.
 */
import { useState, useEffect } from 'react'
import { verifyOwnerDashboardPin } from '../services/performance.service'
import OwnerDashboardContent from './OwnerDashboardContent'

const SESSION_KEY = 'owner_dash_session'

export default function OwnerDashboardPage() {
  // Extract token from URL path: /owner-dashboard/:token
  const token = window.location.pathname.split('/owner-dashboard/')[1]?.split('/')[0] || ''

  const [sessionToken, setSessionToken] = useState(() => {
    try { return sessionStorage.getItem(SESSION_KEY) || null } catch { return null }
  })
  const [orgName,  setOrgName]  = useState('')
  const [pin,      setPin]      = useState('')
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)
  const [attempts, setAttempts] = useState(0)

  // Validate stored session on mount — if expired the dashboard will 401 and clear it
  const handleVerify = async () => {
    if (!pin || pin.length < 4) { setError('Enter your 4–6 digit PIN.'); return }
    setLoading(true)
    setError(null)
    try {
      const data = await verifyOwnerDashboardPin(token, pin)
      try { sessionStorage.setItem(SESSION_KEY, data.session_token) } catch {}
      setSessionToken(data.session_token)
      setOrgName(data.org_name || '')
    } catch (e) {
      const status = e?.response?.status
      setAttempts(p => p + 1)
      if (status === 429) {
        setError('Too many failed attempts. Please wait 15 minutes and try again.')
      } else if (status === 401) {
        setError('Incorrect PIN. Please try again.')
      } else {
        setError('Could not connect. Please check your link and try again.')
      }
    } finally {
      setLoading(false)
      setPin('')
    }
  }

  const handleSessionExpired = () => {
    try { sessionStorage.removeItem(SESSION_KEY) } catch {}
    setSessionToken(null)
    setError('Your session has expired. Please enter your PIN again.')
  }

  if (!token) {
    return (
      <div style={SHELL}>
        <div style={CARD}>
          <p style={{ color: '#ef4444', fontSize: 14 }}>Invalid dashboard link.</p>
        </div>
      </div>
    )
  }

  if (sessionToken) {
    return (
      <OwnerDashboardContent
        token={token}
        sessionToken={sessionToken}
        orgName={orgName}
        onSessionExpired={handleSessionExpired}
      />
    )
  }

  return (
    <div style={SHELL}>
      <div style={CARD}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 28 }}>
          <div style={{ width: 40, height: 40, background: '#01919E', borderRadius: 9, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 18, color: 'white' }}>O</div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 18, color: '#0f2535' }}>Opsra</div>
            <div style={{ fontSize: 11, color: '#6b7280', letterSpacing: '0.8px', textTransform: 'uppercase' }}>Owner Dashboard</div>
          </div>
        </div>

        <h1 style={{ fontWeight: 700, fontSize: 20, color: '#0f2535', margin: '0 0 6px' }}>Enter your PIN</h1>
        <p style={{ fontSize: 13, color: '#6b7280', marginBottom: 24, lineHeight: 1.6 }}>
          This dashboard is PIN-protected. Enter the PIN you set in Opsra to continue.
        </p>

        {error && (
          <div style={{ background: '#fee2e2', border: '1px solid #fca5a5', borderRadius: 8, padding: '10px 14px', marginBottom: 16, fontSize: 13, color: '#991b1b' }}>
            ⚠ {error}
          </div>
        )}

        <label style={LABEL}>PIN</label>
        <input
          type="password"
          inputMode="numeric"
          placeholder="••••"
          maxLength={6}
          value={pin}
          onChange={e => setPin(e.target.value.replace(/\D/g, '').slice(0, 6))}
          onKeyDown={e => { if (e.key === 'Enter') handleVerify() }}
          disabled={attempts >= 5}
          style={PIN_INPUT}
        />

        <button
          onClick={handleVerify}
          disabled={loading || attempts >= 5}
          style={{
            width: '100%', background: loading || attempts >= 5 ? '#9ca3af' : '#01919E',
            color: 'white', border: 'none', borderRadius: 9, padding: '13px',
            fontSize: 15, fontWeight: 600, cursor: loading || attempts >= 5 ? 'not-allowed' : 'pointer',
            marginTop: 8,
          }}
        >
          {loading ? 'Verifying…' : 'Access Dashboard'}
        </button>
      </div>
    </div>
  )
}

const SHELL = {
  position: 'fixed', inset: 0, background: '#f1f5f9',
  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
}
const CARD = {
  background: 'white', borderRadius: 14, padding: '40px 36px',
  width: '100%', maxWidth: 380, boxShadow: '0 8px 32px rgba(0,0,0,0.08)',
  border: '1px solid #e5e7eb',
}
const LABEL = {
  display: 'block', fontSize: 12, fontWeight: 500,
  color: '#374151', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.5px',
}
const PIN_INPUT = {
  width: '100%', border: '1.5px solid #e5e7eb', borderRadius: 9,
  padding: '13px 16px', fontSize: 22, letterSpacing: '0.4em',
  textAlign: 'center', boxSizing: 'border-box', fontFamily: 'inherit',
  outline: 'none',
}
