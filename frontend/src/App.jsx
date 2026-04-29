/**
 * App.jsx — Opsra application shell
 *
 * Replaces the default Vite scaffold.
 *
 * Structure:
 *   ┌─ LoginScreen     (shown when token === null)
 *   └─ AppShell        (shown when authenticated)
 *       ├─ Topbar      (fixed 60px)
 *       ├─ Sidebar     (fixed 248px)
 *       ├─ Main
 *       │   ├─ view === 'leads'        → LeadsPipeline
 *       │   └─ view === 'lead-profile' → LeadProfile
 *       ├─ AriaButton  (fixed FAB — always visible)  ← M01-10b
 *       ├─ AriaPanel   (fixed slide-in panel)         ← M01-10b
 *       └─ OnboardingChecklist (fixed right panel)   ← ORG-ONBOARDING-B
 *
 * Routing: Zustand view-state (no react-router — not in package.json).
 *
 * SECURITY (Technical Spec §11.1):
 *   - JWT stored in Zustand memory only.  Never localStorage / sessionStorage.
 *   - Auth state is lost on page refresh (by design — token in memory).
 *   - 401 responses from any API call clear auth via the axios interceptor
 *     in leads.service.js, which causes this component to re-render to LoginScreen.
 */
import { useState, useEffect } from 'react'
import axios from 'axios'
import useAuthStore from './store/authStore'
import { ds } from './utils/ds'
import LeadsPipeline from './modules/leads/LeadsPipeline'
import LeadProfile   from './modules/leads/LeadProfile'
import WhatsAppModule from './modules/whatsapp/WhatsAppModule'
import SupportModule from './modules/support/SupportModule'
import RenewalModule from './modules/renewal/RenewalModule'
import OpsModule     from './modules/ops/OpsModule'
import TaskBoard     from './modules/tasks/TaskBoard'
import AdminModule   from './modules/admin/AdminModule'
import NotificationsDrawer from './modules/notifications/NotificationsDrawer'
import CommissionsModule   from './modules/commissions/CommissionsModule'
import DemoQueue from './modules/leads/DemoQueue'
import AriaButton from './modules/assistant/AriaButton'   // ← M01-10b
import AriaPanel  from './modules/assistant/AriaPanel'    // ← M01-10b
import OnboardingChecklist from './modules/onboarding/OnboardingChecklist'  // ← ORG-ONBOARDING-B
import { getBriefing } from './services/assistant.service' // ← M01-10b
import CreateOrg from "./modules/superadmin/CreateOrg.jsx";

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// ─── Session timeout (Phase 9D) ───────────────────────────────────────────────
// Module-level flag: set true before clearAuth() so LoginScreen can show the
// inactivity message.  Not stored in any browser storage — F1/F2 compliant.
let _idleLogout = false
const IDLE_MS = 30 * 60 * 1000  // 30 minutes

// ─── Sidebar navigation definition ───────────────────────────────────────────
const NAV = [
  { id: 'leads',    label: 'Lead Command Center', icon: '🎯', module: '01', active: true  },
  { id: 'whatsapp', label: 'WhatsApp Engine',      icon: '💬', module: '02', active: true },
  { id: 'support',  label: 'Support Tickets',      icon: '🎫', module: '03', active: true },
  { id: 'renewal',  label: 'Renewal & Upsell',     icon: '🔄', module: '04', active: true  },
  { id: 'ops',      label: 'Operations Intel',     icon: '📊', module: '05', active: true  },
  { id: 'tasks',    label: 'Task Board',            icon: '✅', module: '—',  active: true  },
  { id: 'commissions', label: 'Commissions',        icon: '💼', module: '—',  active: true  },
]

// ─── Root ─────────────────────────────────────────────────────────────────────

export default function App() {
  const { token, setAuth } = useAuthStore()

  // Inject Google Fonts once on mount
  useEffect(() => {
    if (document.getElementById('opsra-fonts')) return
    const link  = document.createElement('link')
    link.id     = 'opsra-fonts'
    link.rel    = 'stylesheet'
    link.href   = 'https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap'
    document.head.appendChild(link)
  }, [])

  // Inject global keyframe for spinner animation used across modules
  // Also inject login-spinner keyframe
  useEffect(() => {
    if (document.getElementById('opsra-keyframes')) return
    const style = document.createElement('style')
    style.id    = 'opsra-keyframes'
    style.textContent = `
      @keyframes spin { to { transform: rotate(360deg); } }
      @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
      @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
      @keyframes pulse-badge { 0%,100% { transform: scale(1); } 50% { transform: scale(1.2); } }
    `
    document.head.appendChild(style)
  }, [])

  if (!token) return <LoginScreen onAuth={setAuth} />
  return <AppShell />
}

// ─── Login screen ─────────────────────────────────────────────────────────────

function LoginScreen({ onAuth }) {
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)

  // Show inactivity message once if session was terminated by idle timer
  const [idleMsg] = useState(() => {
    if (_idleLogout) { _idleLogout = false; return true }
    return false
  })

  // MFA state — Phase 9E
  const [mfaStep, setMfaStep]       = useState(false)
  const [mfaCode, setMfaCode]       = useState('')
  const [pendingAuth, setPendingAuth] = useState(null)

  const handleLogin = async () => {
    if (!email || !password) { setError('Email and password are required.'); return }
    setLoading(true)
    setError(null)
    try {
      const res = await axios.post(`${BASE}/api/v1/auth/login`, { email, password })
      if (res.data.success) {
        const { access_token, user, mfa_required, factor_id } = res.data.data

        if (mfa_required && factor_id) {
          setPendingAuth({ access_token, factor_id, user })
          setMfaStep(true)
          return
        }

        await _finishLogin(access_token, user)
      } else {
        setError(res.data.error ?? 'Login failed')
      }
    } catch (err) {
      const status = err?.response?.status
      if (status === 401 || status === 400) setError('Invalid email or password.')
      else setError('Unable to connect — please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleMfaVerify = async () => {
    if (!mfaCode || mfaCode.length !== 6) { setError('Enter the 6-digit code from your authenticator app.'); return }
    setLoading(true)
    setError(null)
    try {
      const { access_token, factor_id, user } = pendingAuth

      const challengeRes = await axios.post(
        `${BASE}/api/v1/auth/mfa/challenge`,
        { factor_id },
        { headers: { Authorization: `Bearer ${access_token}` } },
      )
      const { challenge_id } = challengeRes.data.data

      const verifyRes = await axios.post(
        `${BASE}/api/v1/auth/mfa/verify`,
        { factor_id, challenge_id, code: mfaCode },
        { headers: { Authorization: `Bearer ${access_token}` } },
      )
      const aal2Token = verifyRes.data.data.access_token

      await _finishLogin(aal2Token, user)
    } catch (err) {
      const status = err?.response?.status
      if (status === 422) setError('Invalid code. Please try again.')
      else setError('Verification failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const _finishLogin = async (access_token, user) => {
    try {
      const meRes = await axios.get(`${BASE}/api/v1/auth/me`, {
        headers: { Authorization: `Bearer ${access_token}` },
      })
      onAuth(access_token, meRes.data?.data ?? user)
    } catch {
      onAuth(access_token, user)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') mfaStep ? handleMfaVerify() : handleLogin()
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: ds.dark, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{
        background:   ds.dark2,
        border:       '1px solid #1e3a4f',
        borderRadius: 16,
        padding:      '48px 44px',
        width:        420,
        boxShadow:    '0 32px 80px rgba(0,0,0,0.5)',
      }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 32 }}>
          <div style={{ width: 44, height: 44, background: ds.teal, borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: ds.fontSyne, fontWeight: 800, fontSize: 20, color: 'white' }}>
            O
          </div>
          <div>
            <p style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: 'white', margin: 0 }}>Opsra</p>
            <p style={{ fontSize: 11, color: '#6B8FA0', letterSpacing: '1px', textTransform: 'uppercase', margin: 0 }}>AI Growth System</p>
          </div>
        </div>

        <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 26, color: 'white', margin: '0 0 8px' }}>
          Welcome back
        </h1>
        <p style={{ fontSize: 14, color: '#7A9BAD', marginBottom: 28, lineHeight: 1.6 }}>
          Sign in to access your operations dashboard.
        </p>

        {mfaStep ? (
          <>
            <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: 'white', margin: '0 0 8px' }}>
              Two-factor authentication
            </h1>
            <p style={{ fontSize: 13, color: '#7A9BAD', marginBottom: 24, lineHeight: 1.6 }}>
              Enter the 6-digit code from your authenticator app.
            </p>

            <label style={loginLabel}>Authentication code</label>
            <input
              type="text"
              inputMode="numeric"
              placeholder="000000"
              maxLength={6}
              value={mfaCode}
              onChange={e => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              onKeyDown={handleKeyDown}
              autoComplete="one-time-code"
              style={{ ...loginInput, marginBottom: 24, letterSpacing: '0.3em', textAlign: 'center', fontSize: 22 }}
            />

            {error && (
              <p style={{ fontSize: 13, color: '#FF9A9A', marginBottom: 16, lineHeight: 1.5 }}>⚠ {error}</p>
            )}

            <button
              onClick={handleMfaVerify}
              disabled={loading}
              style={{
                width: '100%', background: loading ? '#015F6B' : ds.teal,
                color: 'white', border: 'none', borderRadius: 10, padding: 15,
                fontSize: 15, fontWeight: 600, fontFamily: ds.fontSyne,
                cursor: loading ? 'not-allowed' : 'pointer', transition: 'background 0.2s',
              }}
            >
              {loading ? (
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                  <span style={{
                    width: 16, height: 16, border: '2px solid rgba(255,255,255,0.35)',
                    borderTopColor: 'white', borderRadius: '50%',
                    display: 'inline-block',
                    animation: 'spin 0.7s linear infinite',
                  }} />
                  Verifying…
                </span>
              ) : 'Verify code'}
            </button>

            <button
              onClick={() => { setMfaStep(false); setPendingAuth(null); setMfaCode(''); setError(null) }}
              style={{ width: '100%', background: 'none', border: 'none', marginTop: 12,
                fontSize: 13, color: '#7A9BAD', cursor: 'pointer', textDecoration: 'underline' }}
            >
              ← Back to sign in
            </button>
          </>
        ) : (
          <>
            <label style={loginLabel}>Email address</label>
            <input
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              onKeyDown={handleKeyDown}
              autoComplete="email"
              style={loginInput}
            />

            <label style={loginLabel}>Password</label>
            <input
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={e => setPassword(e.target.value)}
              onKeyDown={handleKeyDown}
              autoComplete="current-password"
              style={{ ...loginInput, marginBottom: 24 }}
            />

            {idleMsg && (
              <div style={{
                background: '#0e2a38', border: '1px solid #1e4a60',
                borderRadius: 8, padding: '10px 14px', marginBottom: 16,
                fontSize: 13, color: '#7ecfea', lineHeight: 1.5,
              }}>
                🔒 You have been logged out due to inactivity.
              </div>
            )}

            {error && (
              <p style={{ fontSize: 13, color: '#FF9A9A', marginBottom: 16, lineHeight: 1.5 }}>
                ⚠ {error}
              </p>
            )}

            <button
              onClick={handleLogin}
              disabled={loading}
              style={{
                width:        '100%',
                background:   loading ? '#015F6B' : ds.teal,
                color:        'white',
                border:       'none',
                borderRadius: 10,
                padding:      15,
                fontSize:     15,
                fontWeight:   600,
                fontFamily:   ds.fontSyne,
                cursor:       loading ? 'not-allowed' : 'pointer',
                transition:   'background 0.2s',
              }}
            >
              {loading ? (
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                  <span style={{
                    width: 16, height: 16, border: '2px solid rgba(255,255,255,0.35)',
                    borderTopColor: 'white', borderRadius: '50%',
                    display: 'inline-block',
                    animation: 'spin 0.7s linear infinite',
                  }} />
                  Signing in…
                </span>
              ) : 'Sign In'}
            </button>

            <p style={{ fontSize: 12, color: '#3a5a6a', textAlign: 'center', marginTop: 16, lineHeight: 1.5 }}>
              Forgot your password? Contact your administrator.
            </p>
          </>
        )}
      </div>
    </div>
  )
}

// ─── App shell ────────────────────────────────────────────────────────────────

function AppShell() {
  const { user, clearAuth }       = useAuthStore()
  const org = user
  const [activeNav, setActiveNav] = useState('leads')

  // ── Session idle timeout (Phase 9D) ─────────────────────────────────────
  useEffect(() => {
    let timer = null

    const resetTimer = () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        _idleLogout = true
        clearAuth()
      }, IDLE_MS)
    }

    const EVENTS = ['mousemove', 'keydown', 'mousedown', 'touchstart', 'scroll']
    EVENTS.forEach(ev => window.addEventListener(ev, resetTimer, { passive: true }))
    resetTimer()

    return () => {
      if (timer) clearTimeout(timer)
      EVENTS.forEach(ev => window.removeEventListener(ev, resetTimer))
    }
  }, [clearAuth])

  // Phase 9B: filter nav items based on role template
  const _userTemplate = user?.roles?.template ?? ''
  const visibleNav = NAV.filter(item => {
    if (item.id === 'ops'     && ['sales_agent', 'affiliate_partner'].includes(_userTemplate)) return false
    if (item.id === 'renewal' && _userTemplate === 'affiliate_partner') return false
    if (item.id === 'commissions') {
      return ['owner', 'ops_manager', 'sales_agent', 'affiliate_partner'].includes(_userTemplate)
        || useAuthStore.getState().hasPermission('is_admin')
    }
    return true
  })

  const [view, setView]           = useState('leads')
  const [selectedLeadId, setSelectedLeadId] = useState(null)
  const [showNotif, setShowNotif]     = useState(false)
  const [unreadCount, setUnreadCount] = useState(0)

  // ── Aria state (M01-10b) ─────────────────────────────────────────────────
  const [ariaOpen,    setAriaOpen]    = useState(false)
  const [ariaBriefing, setAriaBriefing] = useState(null)
  const [ariaBadge,   setAriaBadge]   = useState(false)

  useEffect(() => {
    const token = useAuthStore.getState().token
    if (!token) return
    getBriefing().then(result => {
      if (result?.show && result?.content) {
        setAriaBriefing(result.content)
        setAriaBadge(true)
        setAriaOpen(true)
      }
    }).catch(() => {})
  }, [])

  useEffect(() => {
    const token = useAuthStore.getState().token
    if (!token) return
    axios.get(`${BASE}/api/v1/notifications?page_size=1`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(res => {
      setUnreadCount(res.data?.data?.unread_count ?? 0)
    }).catch(() => {})
  }, [showNotif])

  const openLeadProfile = (leadId) => {
    setSelectedLeadId(leadId)
    setView('lead-profile')
  }

  const backToPipeline = () => {
    setSelectedLeadId(null)
    setView('leads')
  }

  const openDemoQueue = () => {
    setActiveNav('leads')
    setView('demo-queue')
    setSelectedLeadId(null)
  }

  const handleNavClick = (navId) => {
    if (!visibleNav.find(n => n.id === navId)?.active) return
    setActiveNav(navId)
    setView(navId)
    setSelectedLeadId(null)
  }

  const [loggingOut, setLoggingOut] = useState(false)

  const handleLogout = async () => {
    setLoggingOut(true)
    try {
      const token = useAuthStore.getState().token
      await axios.post(`${BASE}/api/v1/auth/logout`, {}, {
        headers: { Authorization: `Bearer ${token}` },
      })
    } catch {}
    clearAuth()
  }

  const userInitial = user?.full_name?.[0]?.toUpperCase() ?? user?.email?.[0]?.toUpperCase() ?? '?'
  const userName    = user?.full_name ?? user?.email ?? 'User'

  return (
    <div style={{ fontFamily: ds.fontDm, background: ds.light, minHeight: '100vh' }}>

      {/* ── Topbar ────────────────────────────────────────────────── */}
      <header style={{
        position: 'fixed', top: 0, left: 0, right: 0,
        height: 60, background: ds.dark, zIndex: ds.z.topbar,
        borderBottom: '1px solid #1a2f3f',
        display: 'flex', alignItems: 'center', padding: '0 24px', gap: 16,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: 'white' }}>
          <div style={{ width: 32, height: 32, background: ds.teal, borderRadius: 7, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 800, color: 'white' }}>
            O
          </div>
          Opsra
          <span style={{ background: ds.teal, color: 'white', fontSize: 10, fontWeight: 600, padding: '3px 9px', borderRadius: 20, textTransform: 'uppercase', letterSpacing: '0.8px', marginLeft: 4 }}>
            Leads
          </span>
        </div>

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ width: 8, height: 8, background: ds.green, borderRadius: '50%', animation: 'pulse 2s infinite' }} />
            <span style={{ fontSize: 12, color: '#7A9BAD' }}>Live</span>
          </div>
          <button
            onClick={() => setShowNotif(true)}
            style={{
              position: 'relative', background: 'none',
              border: '1px solid #2a4a5a', borderRadius: 7,
              padding: '5px 10px', cursor: 'pointer',
              fontSize: 16, lineHeight: 1, color: '#7A9BAD',
              transition: 'all 0.15s',
            }}
          >
            🔔
            {unreadCount > 0 && (
              <span style={{
                position: 'absolute', top: -6, right: -6,
                background: '#EF4444', color: 'white',
                borderRadius: '50%', width: 18, height: 18,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 10, fontWeight: 700, fontFamily: ds.fontSyne,
              }}>
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
          </button>
          {org?.org_id === "00000000-0000-0000-0000-000000000001" && (
            <button
              onClick={() => {
                setView('superadmin_create_org')
                setActiveNav(null)
              }}
              style={{
                background: 'none',
                border: '1px solid #2a4a5a',
                borderRadius: 7,
                padding: '5px 10px',
                fontSize: 12,
                color: '#7A9BAD',
                cursor: 'pointer',
                fontFamily: ds.fontDm,
                transition: 'all 0.15s'
              }}
            >
              + Org
            </button>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 30, height: 30, background: ds.tealDark, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 13, color: 'white' }}>
              {userInitial}
            </div>
            <span style={{ fontSize: 13, color: '#B0CDD8', fontWeight: 500 }}>{userName}</span>
          </div>
          <button
            onClick={handleLogout}
            disabled={loggingOut}
            style={{ background: 'none', border: '1px solid #2a4a5a', borderRadius: 7, padding: '6px 12px', fontSize: 12, color: '#7A9BAD', cursor: loggingOut ? 'not-allowed' : 'pointer', fontFamily: ds.fontDm, transition: 'all 0.15s', display: 'flex', alignItems: 'center', gap: 6, opacity: loggingOut ? 0.7 : 1 }}
          >
            {loggingOut ? (
              <>
                <span style={{
                  width: 11, height: 11, border: '2px solid rgba(122,155,173,0.35)',
                  borderTopColor: '#7A9BAD', borderRadius: '50%',
                  display: 'inline-block',
                  animation: 'spin 0.7s linear infinite',
                }} />
                Signing out…
              </>
            ) : 'Sign out'}
          </button>
        </div>
      </header>

      {/* ── Sidebar ───────────────────────────────────────────────── */}
      <nav style={{
        position: 'fixed', top: 60, left: 0, bottom: 0,
        width: 248, background: ds.dark2,
        borderRight: '1px solid #1a2f3f',
        overflowY: 'auto', zIndex: ds.z.sidebar,
      }}>
        <div style={{ padding: '20px 16px 8px', fontSize: 10, fontWeight: 600, color: '#3a5a6a', textTransform: 'uppercase', letterSpacing: '1.2px' }}>
          Modules
        </div>
        {visibleNav.map(item => {
          const isActive = activeNav === item.id
          return (
            <div
              key={item.id}
              onClick={() => handleNavClick(item.id)}
              title={!item.active ? 'Coming soon' : undefined}
              style={{
                display:    'flex',
                alignItems: 'center',
                gap:        12,
                padding:    '11px 16px',
                margin:     '2px 8px',
                borderRadius: 9,
                cursor:     item.active ? 'pointer' : 'default',
                transition: 'all 0.18s',
                fontSize:   13.5,
                fontWeight: 500,
                color:      isActive ? 'white' : (item.active ? '#7A9BAD' : '#3a5a6a'),
                background: isActive ? ds.teal : 'none',
                opacity:    item.active ? 1 : 0.5,
              }}
            >
              <div style={{
                width:          30,
                height:         30,
                borderRadius:   7,
                display:        'flex',
                alignItems:     'center',
                justifyContent: 'center',
                fontSize:       15,
                background:     isActive ? 'rgba(255,255,255,0.2)' : 'rgba(255,255,255,0.07)',
                flexShrink:     0,
              }}>
                {item.icon}
              </div>
              <span style={{ flex: 1, lineHeight: 1.3 }}>{item.label}</span>
              <span style={{ fontSize: 10, fontWeight: 700, color: isActive ? 'rgba(255,255,255,0.6)' : '#3a5a6a' }}>
                {item.module}
              </span>
            </div>
          )
        })}

        {/* Admin section */}
        <div style={{ padding: '20px 16px 8px', fontSize: 10, fontWeight: 600, color: '#3a5a6a', textTransform: 'uppercase', letterSpacing: '1.2px', marginTop: 8 }}>
          Admin
        </div>
        {(() => {
          const isActive = activeNav === 'admin'
          return (
            <div
              onClick={() => { setActiveNav('admin'); setView('admin'); setSelectedLeadId(null) }}
              style={{
                display: 'flex', alignItems: 'center', gap: 12,
                padding: '11px 16px', margin: '2px 8px', borderRadius: 9,
                cursor: 'pointer', transition: 'all 0.18s',
                fontSize: 13.5, fontWeight: 500,
                color:      isActive ? 'white'  : '#7A9BAD',
                background: isActive ? ds.teal  : 'none',
              }}
            >
              <div style={{
                width: 30, height: 30, borderRadius: 7,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 15, flexShrink: 0,
                background: isActive ? 'rgba(255,255,255,0.2)' : 'rgba(255,255,255,0.07)',
              }}>
                ⚙️
              </div>
              <span style={{ flex: 1 }}>Admin Dashboard</span>
            </div>
          )
        })()}
      </nav>

      {/* ── Main content ──────────────────────────────────────────── */}
      <main style={{ marginLeft: 248, marginTop: 60, minHeight: 'calc(100vh - 60px)' }}>
        {view === 'leads' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            <LeadsPipeline onOpenLead={openLeadProfile} onOpenDemoQueue={openDemoQueue} />
          </div>
        )}
        {view === 'demo-queue' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            <DemoQueue
              onBack={() => { setView('leads'); setActiveNav('leads') }}
              onOpenLead={(leadId) => { openLeadProfile(leadId) }}
            />
          </div>
        )}
        {view === 'lead-profile' && selectedLeadId && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            <LeadProfile leadId={selectedLeadId} onBack={backToPipeline} />
          </div>
        )}
        {view === 'whatsapp' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            <WhatsAppModule org={org} />
          </div>
        )}
        {view === 'support' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            <SupportModule user={user} />
          </div>
        )}
        {view === 'renewal' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            <RenewalModule user={user} />
          </div>
        )}
        {view === 'ops' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            <OpsModule user={user} />
          </div>
        )}
        {view === 'tasks' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            <TaskBoard user={user} />
          </div>
        )}
        {view === 'admin' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            <AdminModule user={user} />
          </div>
        )}
        {view === 'commissions' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            <CommissionsModule user={user} />
          </div>
        )}
        {view === 'superadmin_create_org' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            <CreateOrg />
          </div>
        )}
        {!['leads', 'lead-profile', 'demo-queue', 'whatsapp', 'support', 'renewal', 'ops', 'tasks', 'admin', 'commissions','superadmin_create_org'].includes(view) && (
          <ComingSoon navId={view} />
        )}
      </main>

      {/* Notifications drawer */}
      {showNotif && (
        <NotificationsDrawer
          onClose={() => setShowNotif(false)}
          onUnreadChange={setUnreadCount}
        />
      )}

      {/* ── Aria AI Assistant (M01-10b) ───────────────────────────── */}
      <AriaButton
        onClick={() => setAriaOpen(prev => !prev)}
        hasBadge={ariaBadge}
        panelOpen={ariaOpen}
      />

      {/* AriaPanel: Pattern 26 — always mounted, display:none when closed */}
      <AriaPanel
        open={ariaOpen}
        onClose={() => setAriaOpen(false)}
        briefing={ariaBriefing}
        onBadgeClear={() => { setAriaBadge(false); setAriaBriefing(null) }}
      />

      {/* ── Onboarding Checklist (ORG-ONBOARDING-B) ──────────────── */}
      {/* Self-manages visibility based on org.is_live + role template */}
      <OnboardingChecklist
        setView={(v) => { setView(v); setActiveNav(v); setSelectedLeadId(null) }}
        setActiveNav={setActiveNav}
      />
    </div>
  )
}

// ─── Placeholder for future modules ──────────────────────────────────────────

function ComingSoon({ navId }) {
  const item = NAV.find(n => n.id === navId)
  return (
    <div style={{ padding: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh' }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>{item?.icon ?? '🔧'}</div>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: ds.dark, margin: '0 0 8px' }}>
          {item?.label ?? 'Module'} — Coming Soon
        </h2>
        <p style={{ fontSize: 14, color: ds.gray }}>This module is under construction.</p>
      </div>
    </div>
  )
}

// ─── Login screen styles ──────────────────────────────────────────────────────

const loginLabel = {
  display: 'block', fontSize: 12, fontWeight: 500,
  color: '#7A9BAD', textTransform: 'uppercase',
  letterSpacing: '0.8px', marginBottom: 8,
}

const loginInput = {
  width: '100%', background: ds.dark, border: '1.5px solid #1e3a4f',
  borderRadius: 10, padding: '14px 16px', fontSize: 14,
  color: 'white', fontFamily: ds.fontDm, outline: 'none',
  transition: 'border-color 0.2s', marginBottom: 20, boxSizing: 'border-box',
}
