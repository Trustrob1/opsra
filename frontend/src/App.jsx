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
 *       └─ Main
 *           ├─ view === 'leads'        → LeadsPipeline
 *           └─ view === 'lead-profile' → LeadProfile
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

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// ─── Sidebar navigation definition ───────────────────────────────────────────
const NAV = [
  { id: 'leads',    label: 'Lead Command Center', icon: '🎯', module: '01', active: true  },
  { id: 'whatsapp', label: 'WhatsApp Engine',      icon: '💬', module: '02', active: true },
  { id: 'support',  label: 'Support Tickets',      icon: '🎫', module: '03', active: true },
  { id: 'renewal',  label: 'Renewal & Upsell',     icon: '🔄', module: '04', active: true  },
  { id: 'ops',      label: 'Operations Intel',     icon: '📊', module: '05', active: true  },
  { id: 'tasks',    label: 'Task Board',            icon: '✅', module: '—',  active: true  },
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
  useEffect(() => {
    if (document.getElementById('opsra-keyframes')) return
    const style = document.createElement('style')
    style.id    = 'opsra-keyframes'
    style.textContent = `
      @keyframes spin { to { transform: rotate(360deg); } }
      @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
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

  const handleLogin = async () => {
    if (!email || !password) { setError('Email and password are required.'); return }
    setLoading(true)
    setError(null)
    try {
      const res = await axios.post(`${BASE}/api/v1/auth/login`, { email, password })
      if (res.data.success) {
        const { access_token, user } = res.data.data
        onAuth(access_token, user)
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

  const handleKeyDown = (e) => { if (e.key === 'Enter') handleLogin() }

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

        {/* Email */}
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

        {/* Password */}
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

        {/* Error */}
        {error && (
          <p style={{ fontSize: 13, color: '#FF9A9A', marginBottom: 16, lineHeight: 1.5 }}>
            ⚠ {error}
          </p>
        )}

        {/* Submit */}
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
          {loading ? 'Signing in…' : 'Sign In'}
        </button>

        <p style={{ fontSize: 12, color: '#3a5a6a', textAlign: 'center', marginTop: 16, lineHeight: 1.5 }}>
          Forgot your password? Contact your administrator.
        </p>
      </div>
    </div>
  )
}

// ─── App shell ────────────────────────────────────────────────────────────────

function AppShell() {
  const { user, clearAuth }       = useAuthStore()
  const org = user
  const [activeNav, setActiveNav] = useState('leads')
  const [view, setView]           = useState('leads')          // 'leads' | 'lead-profile'
  const [selectedLeadId, setSelectedLeadId] = useState(null)

  const openLeadProfile = (leadId) => {
    setSelectedLeadId(leadId)
    setView('lead-profile')
  }

  const backToPipeline = () => {
    setSelectedLeadId(null)
    setView('leads')
  }

  const handleNavClick = (navId) => {
    if (!NAV.find(n => n.id === navId)?.active) return // not built yet
    setActiveNav(navId)
    setView(navId)
    setSelectedLeadId(null)
  }

  const handleLogout = async () => {
    try {
      // Attempt server-side logout — ignore errors (token expires anyway)
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
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 17, color: 'white' }}>
          <div style={{ width: 32, height: 32, background: ds.teal, borderRadius: 7, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 800, color: 'white' }}>
            O
          </div>
          Opsra
          <span style={{ background: ds.teal, color: 'white', fontSize: 10, fontWeight: 600, padding: '3px 9px', borderRadius: 20, textTransform: 'uppercase', letterSpacing: '0.8px', marginLeft: 4 }}>
            Leads
          </span>
        </div>

        {/* Right side */}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 16 }}>
          {/* Live dot */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ width: 8, height: 8, background: ds.green, borderRadius: '50%', animation: 'pulse 2s infinite' }} />
            <span style={{ fontSize: 12, color: '#7A9BAD' }}>Live</span>
          </div>
          {/* User chip */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 30, height: 30, background: ds.tealDark, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 13, color: 'white' }}>
              {userInitial}
            </div>
            <span style={{ fontSize: 13, color: '#B0CDD8', fontWeight: 500 }}>{userName}</span>
          </div>
          {/* Logout */}
          <button
            onClick={handleLogout}
            style={{ background: 'none', border: '1px solid #2a4a5a', borderRadius: 7, padding: '6px 12px', fontSize: 12, color: '#7A9BAD', cursor: 'pointer', fontFamily: ds.fontDm, transition: 'all 0.15s' }}
          >
            Sign out
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
        {NAV.map(item => {
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
              {/* Icon box */}
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
              {/* Label */}
              <span style={{ flex: 1, lineHeight: 1.3 }}>{item.label}</span>
              {/* Module number */}
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
        {[
          { label: 'Users & Roles',   icon: '👥' },
          { label: 'Integrations',    icon: '🔌' },
          { label: 'Routing Rules',   icon: '🔀' },
        ].map(item => (
          <div key={item.label} style={{
            display: 'flex', alignItems: 'center', gap: 12,
            padding: '11px 16px', margin: '2px 8px', borderRadius: 9,
            cursor: 'default', opacity: 0.4,
            fontSize: 13.5, fontWeight: 500, color: '#7A9BAD',
          }}>
            <div style={{ width: 30, height: 30, borderRadius: 7, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 15, background: 'rgba(255,255,255,0.07)', flexShrink: 0 }}>
              {item.icon}
            </div>
            <span>{item.label}</span>
          </div>
        ))}
      </nav>

      {/* ── Main content ──────────────────────────────────────────── */}
      <main style={{ marginLeft: 248, marginTop: 60, minHeight: 'calc(100vh - 60px)' }}>
        {view === 'leads' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            <LeadsPipeline onOpenLead={openLeadProfile} />
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
        {/* Placeholder for modules not yet built */}
        {!['leads', 'lead-profile', 'whatsapp', 'support', 'renewal', 'ops', 'tasks'].includes(view) && (
          <ComingSoon navId={view} />
        )}
      </main>
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
