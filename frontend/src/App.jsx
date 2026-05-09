/**
 * App.jsx — Opsra application shell
 *
 * PWA-1 additions:
 *   - Mobile-responsive layout (useIsMobile hook)
 *   - Sidebar becomes a slide-in drawer on mobile (hamburger toggle)
 *   - Topbar adapts: hamburger left, simplified right on mobile
 *   - Drawer overlay + close-on-outside-tap
 *   - Push notification subscription triggered after login
 *   - Main content full-width on mobile (no sidebar offset)
 *
 * Structure:
 *   ┌─ ErrorBoundary   (9E-H: wraps entire app — catches render errors)
 *   ├─ LoginScreen     (shown when token === null)
 *   └─ AppShell        (shown when authenticated)
 *       ├─ Topbar      (fixed 60px — hamburger on mobile)
 *       ├─ Sidebar     (fixed 248px desktop / slide drawer mobile)
 *       ├─ Main
 *       │   ├─ view === 'leads'        → LeadsPipeline
 *       │   └─ view === 'lead-profile' → LeadProfile
 *       ├─ AriaButton  (fixed FAB — always visible)
 *       ├─ AriaPanel   (fixed slide-in panel)
 *       └─ OnboardingChecklist
 *
 * Routing: Zustand view-state (no react-router — not in package.json).
 *
 * SECURITY (Technical Spec §11.1):
 *   - JWT stored in Zustand memory only.  Never localStorage / sessionStorage.
 *   - Auth state is lost on page refresh (by design — token in memory).
 *   - 401 responses trigger silent JWT refresh via the global interceptor in
 *     frontend/src/services/api.js (9E-H).  If refresh fails, clearAuth() is
 *     called and this component re-renders to LoginScreen.
 */
import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import useAuthStore from './store/authStore'
import { ds } from './utils/ds'
import { useIsMobile } from './hooks/useIsMobile'
import ErrorBoundary from './components/ErrorBoundary'
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
import AriaButton from './modules/assistant/AriaButton'
import AriaPanel  from './modules/assistant/AriaPanel'
import OnboardingChecklist from './modules/onboarding/OnboardingChecklist'
import { getBriefing } from './services/assistant.service'
import PrivacyPolicy from './pages/PrivacyPolicy'
import CreateOrg from "./modules/superadmin/CreateOrg.jsx"
import HealthDashboard from "./modules/superadmin/HealthDashboard.jsx"
import ConversationsModule from './modules/conversations/ConversationsModule'
import TermsOfService from './pages/TermsOfService'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// ─── Session timeout (Phase 9D) ───────────────────────────────────────────────
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
  { id: 'conversations', label: 'Conversations',      icon: '📨', module: '—',  active: true  },
  { id: 'commissions', label: 'Commissions',        icon: '💼', module: '—',  active: true  },
]

// ─── Root ─────────────────────────────────────────────────────────────────────

export default function App() {
  const { token, setAuth } = useAuthStore()

  useEffect(() => {
    if (document.getElementById('opsra-fonts')) return
    const link  = document.createElement('link')
    link.id     = 'opsra-fonts'
    link.rel    = 'stylesheet'
    link.href   = 'https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap'
    document.head.appendChild(link)
  }, [])

  useEffect(() => {
    if (document.getElementById('opsra-keyframes')) return
    const style = document.createElement('style')
    style.id    = 'opsra-keyframes'
    style.textContent = `
      @keyframes spin { to { transform: rotate(360deg); } }
      @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
      @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
      @keyframes pulse-badge { 0%,100% { transform: scale(1); } 50% { transform: scale(1.2); } }
      @keyframes slideInLeft { from { transform: translateX(-100%); } to { transform: translateX(0); } }
    `
    document.head.appendChild(style)
  }, [])

  if (window.location.pathname === '/privacy') return <PrivacyPolicy />
  if (window.location.pathname === '/terms') return <TermsOfService />
  if (!token) return <LoginScreen onAuth={setAuth} />
  return (
    <ErrorBoundary>
      <AppShell />
    </ErrorBoundary>
  )
}

// ─── Login screen ─────────────────────────────────────────────────────────────

function LoginScreen({ onAuth }) {
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)

  const [idleMsg] = useState(() => {
    if (_idleLogout) { _idleLogout = false; return true }
    return false
  })

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
      await _finishLogin(verifyRes.data.data.access_token, user)
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
    // PWA-1: subscribe to push notifications after login (non-blocking)
    if (typeof window.opsraSubscribeToPush === 'function') {
      window.opsraSubscribeToPush(access_token)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') mfaStep ? handleMfaVerify() : handleLogin()
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: ds.dark, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
      <div style={{
        background:   ds.dark2,
        border:       '1px solid #1e3a4f',
        borderRadius: 16,
        padding:      '48px 44px',
        width:        '100%',
        maxWidth:     420,
        boxShadow:    '0 32px 80px rgba(0,0,0,0.5)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 32 }}>
          <div style={{ width: 44, height: 44, background: ds.teal, borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: ds.fontSyne, fontWeight: 800, fontSize: 20, color: 'white' }}>O</div>
          <div>
            <p style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: 'white', margin: 0 }}>Opsra</p>
            <p style={{ fontSize: 11, color: '#6B8FA0', letterSpacing: '1px', textTransform: 'uppercase', margin: 0 }}>AI Growth System</p>
          </div>
        </div>

        {mfaStep ? (
          <>
            <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: 'white', margin: '0 0 8px' }}>Two-factor authentication</h1>
            <p style={{ fontSize: 13, color: '#7A9BAD', marginBottom: 24, lineHeight: 1.6 }}>Enter the 6-digit code from your authenticator app.</p>
            <label style={loginLabel}>Authentication code</label>
            <input
              type="text" inputMode="numeric" placeholder="000000" maxLength={6}
              value={mfaCode} onChange={e => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              onKeyDown={handleKeyDown} autoComplete="one-time-code"
              style={{ ...loginInput, marginBottom: 24, letterSpacing: '0.3em', textAlign: 'center', fontSize: 22 }}
            />
            {error && <p style={{ fontSize: 13, color: '#FF9A9A', marginBottom: 16 }}>⚠ {error}</p>}
            <button onClick={handleMfaVerify} disabled={loading} style={loginBtn(loading)}>
              {loading ? <Spinner label="Verifying…" /> : 'Verify code'}
            </button>
            <button onClick={() => { setMfaStep(false); setPendingAuth(null); setMfaCode(''); setError(null) }}
              style={{ width: '100%', background: 'none', border: 'none', marginTop: 12, fontSize: 13, color: '#7A9BAD', cursor: 'pointer', textDecoration: 'underline' }}>
              ← Back to sign in
            </button>
          </>
        ) : (
          <>
            <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 26, color: 'white', margin: '0 0 8px' }}>Welcome back</h1>
            <p style={{ fontSize: 14, color: '#7A9BAD', marginBottom: 28, lineHeight: 1.6 }}>Sign in to access your operations dashboard.</p>
            <label style={loginLabel}>Email address</label>
            <input type="email" placeholder="you@example.com" value={email} onChange={e => setEmail(e.target.value)} onKeyDown={handleKeyDown} autoComplete="email" style={loginInput} />
            <label style={loginLabel}>Password</label>
            <input type="password" placeholder="••••••••" value={password} onChange={e => setPassword(e.target.value)} onKeyDown={handleKeyDown} autoComplete="current-password" style={{ ...loginInput, marginBottom: 24 }} />
            {idleMsg && (
              <div style={{ background: '#0e2a38', border: '1px solid #1e4a60', borderRadius: 8, padding: '10px 14px', marginBottom: 16, fontSize: 13, color: '#7ecfea', lineHeight: 1.5 }}>
                🔒 You have been logged out due to inactivity.
              </div>
            )}
            {error && <p style={{ fontSize: 13, color: '#FF9A9A', marginBottom: 16 }}>⚠ {error}</p>}
            <button onClick={handleLogin} disabled={loading} style={loginBtn(loading)}>
              {loading ? <Spinner label="Signing in…" /> : 'Sign In'}
            </button>
            <p style={{ fontSize: 12, color: '#3a5a6a', textAlign: 'center', marginTop: 16 }}>Forgot your password? Contact your administrator.</p>
            <p style={{ fontSize: 11, color: '#2a4a5a', textAlign: 'center', marginTop: 8 }}>
              <a href="/privacy" style={{ color: '#3a6a7a', textDecoration: 'none' }}>Privacy Policy</a>
              {" · "}
              <a href="/terms" style={{ color: '#3a6a7a', textDecoration: 'none' }}>Terms of Service</a>
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
  const isMobile                  = useIsMobile()
  const [activeNav, setActiveNav] = useState('leads')
  const [sidebarOpen, setSidebarOpen] = useState(false)    // mobile drawer state
  const sidebarRef = useRef(null)

  // Close drawer when tapping backdrop on mobile
  const handleBackdropClick = () => setSidebarOpen(false)

  // Close drawer on nav click on mobile
  const closeSidebarOnMobile = () => { if (isMobile) setSidebarOpen(false) }

  // ── Session idle timeout (Phase 9D) ─────────────────────────────────────
  useEffect(() => {
    let timer = null
    const resetTimer = () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => { _idleLogout = true; clearAuth() }, IDLE_MS)
    }
    const EVENTS = ['mousemove', 'keydown', 'mousedown', 'touchstart', 'scroll']
    EVENTS.forEach(ev => window.addEventListener(ev, resetTimer, { passive: true }))
    resetTimer()
    return () => {
      if (timer) clearTimeout(timer)
      EVENTS.forEach(ev => window.removeEventListener(ev, resetTimer))
    }
  }, [clearAuth])

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

  const [view, setView]                     = useState('leads')
  const [selectedLeadId, setSelectedLeadId] = useState(null)
  const [showNotif, setShowNotif]           = useState(false)
  const [unreadCount, setUnreadCount]       = useState(0)

  const [ariaOpen,     setAriaOpen]    = useState(false)
  const [ariaBriefing, setAriaBriefing] = useState(null)
  const [ariaBadge,    setAriaBadge]   = useState(false)
  const [ariaMinimised, setAriaMinimised] = useState(() => {
    try { return localStorage.getItem('aria_minimised') === '1' } catch { return false }
  })

  useEffect(() => {
    const token = useAuthStore.getState().token
    if (!token) return
    getBriefing().then(result => {
      if (result?.show && result?.content) {
        setAriaBriefing(result.content)
        setAriaBadge(true)
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

  const openLeadProfile = (leadId) => { setSelectedLeadId(leadId); setView('lead-profile') }
  const backToPipeline  = () => { setSelectedLeadId(null); setView('leads') }
  const openDemoQueue   = () => { setActiveNav('leads'); setView('demo-queue'); setSelectedLeadId(null) }

  const handleNavClick = (navId) => {
    if (!visibleNav.find(n => n.id === navId)?.active) return
    setActiveNav(navId)
    setView(navId)
    setSelectedLeadId(null)
    closeSidebarOnMobile()
  }

  const [loggingOut, setLoggingOut] = useState(false)
  const handleLogout = async () => {
    setLoggingOut(true)
    try {
      const token = useAuthStore.getState().token
      await axios.post(`${BASE}/api/v1/auth/logout`, {}, { headers: { Authorization: `Bearer ${token}` } })
    } catch {}
    clearAuth()
  }

  const userInitial = user?.full_name?.[0]?.toUpperCase() ?? user?.email?.[0]?.toUpperCase() ?? '?'
  const userName    = user?.full_name ?? user?.email ?? 'User'

  // Sidebar nav content — shared between desktop sidebar and mobile drawer
  const SidebarContent = () => (
    <>
      {/* Mobile drawer header */}
      {isMobile && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 16px 8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 32, height: 32, background: ds.teal, borderRadius: 7, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 800, color: 'white' }}>O</div>
            <span style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: 'white' }}>Opsra</span>
          </div>
          <button
            onClick={() => setSidebarOpen(false)}
            style={{ background: 'none', border: 'none', color: '#7A9BAD', fontSize: 20, cursor: 'pointer', padding: 4, lineHeight: 1 }}
          >✕</button>
        </div>
      )}

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
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '11px 16px', margin: '2px 8px', borderRadius: 9,
              cursor: item.active ? 'pointer' : 'default', transition: 'all 0.18s',
              fontSize: 13.5, fontWeight: 500,
              color:      isActive ? 'white' : (item.active ? '#7A9BAD' : '#3a5a6a'),
              background: isActive ? ds.teal : 'none',
              opacity:    item.active ? 1 : 0.5,
              minHeight:  44,   // 44px tap target on mobile
            }}
          >
            <div style={{ width: 30, height: 30, borderRadius: 7, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 15, background: isActive ? 'rgba(255,255,255,0.2)' : 'rgba(255,255,255,0.07)', flexShrink: 0 }}>
              {item.icon}
            </div>
            <span style={{ flex: 1, lineHeight: 1.3 }}>{item.label}</span>
            <span style={{ fontSize: 10, fontWeight: 700, color: isActive ? 'rgba(255,255,255,0.6)' : '#3a5a6a' }}>{item.module}</span>
          </div>
        )
      })}

      <div style={{ padding: '20px 16px 8px', fontSize: 10, fontWeight: 600, color: '#3a5a6a', textTransform: 'uppercase', letterSpacing: '1.2px', marginTop: 8 }}>
        Admin
      </div>

      {(() => {
        const isActive = activeNav === 'admin'
        return (
          <div
            onClick={() => { setActiveNav('admin'); setView('admin'); setSelectedLeadId(null); closeSidebarOnMobile() }}
            style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 16px', margin: '2px 8px', borderRadius: 9, cursor: 'pointer', transition: 'all 0.18s', fontSize: 13.5, fontWeight: 500, color: isActive ? 'white' : '#7A9BAD', background: isActive ? ds.teal : 'none', minHeight: 44 }}
          >
            <div style={{ width: 30, height: 30, borderRadius: 7, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 15, flexShrink: 0, background: isActive ? 'rgba(255,255,255,0.2)' : 'rgba(255,255,255,0.07)' }}>⚙️</div>
            <span style={{ flex: 1 }}>Admin Dashboard</span>
          </div>
        )
      })()}

      {/* Mobile-only: user info + sign out at bottom of drawer */}
      {isMobile && (
        <div style={{ marginTop: 'auto', padding: '16px', borderTop: '1px solid #1a2f3f' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
            <div style={{ width: 36, height: 36, borderRadius: '50%', background: ds.teal, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 700, color: 'white', fontFamily: ds.fontSyne, flexShrink: 0 }}>
              {userInitial}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, color: '#A0BDC8', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{userName}</div>
            </div>
          </div>
          <button
            onClick={handleLogout}
            disabled={loggingOut}
            style={{ width: '100%', background: 'none', border: '1px solid #2a4a5a', borderRadius: 8, padding: '10px', fontSize: 13, color: '#7A9BAD', cursor: 'pointer' }}
          >
            {loggingOut ? 'Signing out…' : 'Sign out'}
          </button>
        </div>
      )}
    </>
  )

  return (
    <div style={{ fontFamily: ds.fontDm, background: ds.light, minHeight: '100vh' }}>

      {/* ── Topbar ─────────────────────────────────────────────────────────── */}
      <header style={{
        position: 'fixed', top: 0, left: 0, right: 0,
        height: 60, background: ds.dark, zIndex: ds.z.topbar,
        borderBottom: '1px solid #1a2f3f',
        display: 'flex', alignItems: 'center', padding: '0 16px', gap: 12,
      }}>
        {/* Mobile: hamburger */}
        {isMobile ? (
          <>
            <button
              onClick={() => setSidebarOpen(true)}
              style={{ background: 'none', border: 'none', color: '#7A9BAD', fontSize: 20, cursor: 'pointer', padding: '6px', lineHeight: 1, display: 'flex', alignItems: 'center' }}
              aria-label="Open menu"
            >☰</button>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: 'white', flex: 1 }}>
              <div style={{ width: 28, height: 28, background: ds.teal, borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 800, color: 'white' }}>O</div>
              Opsra
            </div>
          </>
        ) : (
          /* Desktop: logo */
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: 'white' }}>
            <div style={{ width: 32, height: 32, background: ds.teal, borderRadius: 7, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 800, color: 'white' }}>O</div>
            Opsra
            <span style={{ background: ds.teal, color: 'white', fontSize: 10, fontWeight: 600, padding: '3px 9px', borderRadius: 20, textTransform: 'uppercase', letterSpacing: '0.8px', marginLeft: 4 }}>Leads</span>
          </div>
        )}

        <div style={{ marginLeft: isMobile ? 0 : 'auto', display: 'flex', alignItems: 'center', gap: isMobile ? 10 : 16 }}>
          {!isMobile && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{ width: 8, height: 8, background: ds.green, borderRadius: '50%', animation: 'pulse 2s infinite' }} />
                <span style={{ fontSize: 12, color: '#7A9BAD' }}>Live</span>
              </div>
              {['owner', 'ops_manager'].includes(_userTemplate) && (
                <>
                  <button onClick={() => { setView('superadmin_health'); setActiveNav('') }} style={topbarBtn}>⚡ Health</button>
                  <button onClick={() => { setView('superadmin_create_org'); setActiveNav('') }} style={topbarBtn}>+ Org</button>
                </>
              )}
            </>
          )}

          {/* Notification bell — always visible */}
          <button
            onClick={() => setShowNotif(true)}
            style={{ position: 'relative', background: 'none', border: '1px solid #2a4a5a', borderRadius: 7, padding: '5px 10px', cursor: 'pointer', fontSize: 16, lineHeight: 1, color: '#7A9BAD', minWidth: 40, minHeight: 40, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >
            🔔
            {unreadCount > 0 && (
              <span style={{ position: 'absolute', top: -6, right: -6, background: '#EF4444', color: 'white', borderRadius: '50%', width: 18, height: 18, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700, fontFamily: ds.fontSyne }}>
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
          </button>

          {/* Desktop: user + sign out */}
          {!isMobile && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                <div style={{ width: 32, height: 32, borderRadius: '50%', background: ds.teal, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700, color: 'white', fontFamily: ds.fontSyne }}>
                  {userInitial}
                </div>
                <span style={{ fontSize: 13, color: '#A0BDC8', fontWeight: 500 }}>{userName}</span>
              </div>
              <button onClick={handleLogout} disabled={loggingOut} style={topbarBtn}>
                {loggingOut ? 'Signing out…' : 'Sign out'}
              </button>
            </>
          )}
        </div>
      </header>

      {/* ── Sidebar (desktop) ─────────────────────────────────────────────── */}
      {!isMobile && (
        <nav style={{
          position: 'fixed', top: 60, left: 0, bottom: 0,
          width: 248, background: ds.dark2,
          borderRight: '1px solid #1a2f3f',
          overflowY: 'auto', zIndex: ds.z.sidebar,
          display: 'flex', flexDirection: 'column',
        }}>
          <SidebarContent />
        </nav>
      )}

      {/* ── Mobile sidebar drawer ─────────────────────────────────────────── */}
      {isMobile && (
        <>
          {/* Backdrop */}
          {sidebarOpen && (
            <div
              onClick={handleBackdropClick}
              style={{
                position: 'fixed', inset: 0,
                background: 'rgba(0,0,0,0.55)',
                zIndex: ds.z.mobileDrawer - 1,
                animation: 'fadeIn 0.15s ease',
              }}
            />
          )}
          {/* Drawer */}
          <nav style={{
            position: 'fixed', top: 0, left: 0, bottom: 0,
            width: 280, background: ds.dark2,
            borderRight: '1px solid #1a2f3f',
            overflowY: 'auto',
            zIndex: ds.z.mobileDrawer,
            transform: sidebarOpen ? 'translateX(0)' : 'translateX(-100%)',
            transition: 'transform 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
            display: 'flex', flexDirection: 'column',
          }}
            ref={sidebarRef}
          >
            <SidebarContent />
          </nav>
        </>
      )}

      {/* ── Main content ──────────────────────────────────────────────────── */}
      <main style={{
        marginLeft:   isMobile ? 0 : 248,
        marginTop:    60,
        minHeight:    'calc(100vh - 60px)',
        // Bottom padding on mobile to not clip content behind potential bottom bars
        paddingBottom: isMobile ? 16 : 0,
      }}>
        {view === 'leads' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            <LeadsPipeline onOpenLead={openLeadProfile} onOpenDemoQueue={openDemoQueue} />
          </div>
        )}
        {view === 'demo-queue' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            <DemoQueue onBack={() => { setView('leads'); setActiveNav('leads') }} onOpenLead={(leadId) => openLeadProfile(leadId)} />
          </div>
        )}
        {view === 'lead-profile' && selectedLeadId && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            <LeadProfile leadId={selectedLeadId} onBack={backToPipeline} />
          </div>
        )}
        {view === 'whatsapp' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><WhatsAppModule org={org} /></div>
        )}
        {view === 'support' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><SupportModule user={user} /></div>
        )}
        {view === 'renewal' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><RenewalModule user={user} /></div>
        )}
        {view === 'ops' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><OpsModule user={user} /></div>
        )}
        {view === 'tasks' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><TaskBoard user={user} /></div>
        )}
        {view === 'admin' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><AdminModule user={user} /></div>
        )}
        {view === 'conversations' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            <ConversationsModule user={user} onOpenAria={() => setAriaOpen(true)} />
          </div>
        )}
        {view === 'commissions' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><CommissionsModule user={user} /></div>
        )}
        {view === 'superadmin_create_org' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><CreateOrg /></div>
        )}
        {view === 'superadmin_health' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><HealthDashboard /></div>
        )}
        {!['leads', 'lead-profile', 'demo-queue', 'whatsapp', 'support', 'renewal', 'ops', 'tasks', 'admin', 'conversations', 'commissions', 'superadmin_create_org', 'superadmin_health'].includes(view) && (
          <ComingSoon navId={view} />
        )}
      </main>

      {/* Notifications drawer */}
      {showNotif && (
        <NotificationsDrawer onClose={() => setShowNotif(false)} onUnreadChange={setUnreadCount} />
      )}

      {/* Aria AI Assistant (M01-10b) */}
      <AriaButton
        onClick={() => setAriaOpen(prev => !prev)}
        hasBadge={ariaBadge}
        panelOpen={ariaOpen}
        view={view}
        minimised={ariaMinimised}
        onMinimise={() => {
          const next = !ariaMinimised
          setAriaMinimised(next)
          try { localStorage.setItem('aria_minimised', next ? '1' : '0') } catch {}
        }}
      />
      <AriaPanel open={ariaOpen} onClose={() => setAriaOpen(false)} briefing={ariaBriefing} onBadgeClear={() => { setAriaBadge(false); setAriaBriefing(null) }} />

      {/* Onboarding Checklist (ORG-ONBOARDING-B) */}
      <OnboardingChecklist setView={(v) => { setView(v); setActiveNav(v); setSelectedLeadId(null) }} setActiveNav={setActiveNav} />
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

// ─── Small helpers ────────────────────────────────────────────────────────────

function Spinner({ label }) {
  return (
    <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
      <span style={{ width: 16, height: 16, border: '2px solid rgba(255,255,255,0.35)', borderTopColor: 'white', borderRadius: '50%', display: 'inline-block', animation: 'spin 0.7s linear infinite' }} />
      {label}
    </span>
  )
}

// ─── Styles ───────────────────────────────────────────────────────────────────

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

const loginBtn = (loading) => ({
  width: '100%', background: loading ? '#015F6B' : ds.teal,
  color: 'white', border: 'none', borderRadius: 10, padding: 15,
  fontSize: 15, fontWeight: 600, fontFamily: ds.fontSyne,
  cursor: loading ? 'not-allowed' : 'pointer', transition: 'background 0.2s',
})

const topbarBtn = {
  background: 'none', border: '1px solid #2a4a5a',
  borderRadius: 7, padding: '5px 12px',
  fontSize: 12, color: '#7A9BAD', cursor: 'pointer',
  transition: 'all 0.15s', fontFamily: ds.fontDm,
}
