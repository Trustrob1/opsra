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
 *       ├─ Sidebar     (fixed 248px desktop, collapsible to 72px / slide drawer mobile)
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
 *   - JWT held in Zustand and mirrored to local/sessionStorage (AUTH-SESSION-1).
 *   - Auth state survives refresh and restart while the session is valid (AUTH-SESSION-1).
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
import BusinessActivitiesModule from './modules/ops/BusinessActivitiesModule'
import ProjectPlannerModule from './modules/projectplanner/ProjectPlannerModule'
import TaskBoard     from './modules/tasks/TaskBoard'
import AdminModule   from './modules/admin/AdminModule'
import NotificationsDrawer from './modules/notifications/NotificationsDrawer'
import CommissionsModule   from './modules/commissions/CommissionsModule'
import DemoQueue from './modules/leads/DemoQueue'
import AriaButton from './modules/assistant/AriaButton'
import AriaPanel  from './modules/assistant/AriaPanel'
import OnboardingChecklist from './modules/onboarding/OnboardingChecklist'
import IOSInstallBanner from './components/IOSInstallBanner'
import { getBriefing } from './services/assistant.service'
import PrivacyPolicy from './pages/PrivacyPolicy'
import DataDeletion from './pages/DataDeletion'
import CreateOrg from "./modules/superadmin/CreateOrg.jsx"
import SuperadminShell from "./modules/superadmin/SuperadminShell.jsx"   // ACCOUNT-PLANS AP-8
import { getPlatformStatus } from "./services/accountPlan.service"      // ACCOUNT-PLANS AP-8
import ConversationsModule from './modules/conversations/ConversationsModule'
import KnowledgeModule from './modules/knowledge/KnowledgeModule'                 // WA-AUTO-4a
import WaSetupWizard from './modules/waonboarding/WaSetupWizard'                // WA-AUTO-3
import { getWaOnboarding } from './services/waOnboarding.service'              // WA-AUTO-3
import TermsOfService from './pages/TermsOfService'
import { _supabase } from './services/api'
import PublicCatalogShell from './catalog/PublicCatalogShell'
import ReportsModule from './modules/reports/ReportsModule'
import PerformanceModule from './modules/performance/PerformanceModule'
import EventFunnelsModule from './modules/funnels/EventFunnelsModule'   // FUNNEL-1B
import WaSignupPage from './pages/WaSignupPage'                      // WA-AUTO-5
import ChatSignupPage from './pages/ChatSignupPage'                  // WEB-ONLY-1b
import SitesModule from './modules/sites/SitesModule'                   // SITE-1A
import BillingModule from './modules/billing/BillingModule'             // ACCOUNT-PLANS AP-3
import BillingBanner from './modules/billing/BillingBanner'             // ACCOUNT-PLANS AP-3
import PlanNotice from './modules/billing/PlanNotice'                   // ACCOUNT-PLANS AP-6
import OpsraMark from './components/OpsraMark'
import {
  Target, MessageSquare, MessageCircle, Ticket, RefreshCw, BarChart2,
  CheckSquare, Briefcase, ClipboardList, Settings, Bell, Circle,
  Menu, X, Eye, EyeOff, Lock, Mail, Lightbulb, Zap, AlertTriangle,
  ChevronRight, ChevronLeft, FolderKanban, Layers, CalendarClock, Globe, CreditCard, BookOpen,
} from 'lucide-react'
import OwnerDashboardPage from './pages/OwnerDashboardPage'
import SiteLandingPage from './pages/SiteLandingPage'   // SITE-LANDING
import HostLandingPage from './pages/HostLandingPage'   // HOST-1
import OwnerLandingPage from './pages/OwnerLandingPage'   // OWNER-LANDING-1
import ChiomaLandingPage from './pages/ChiomaLandingPage'   // CHIOMA-LANDING-1

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// Auth service for password reset (avoids circular dependency with api.js which needs a token)
const _authPost  = (path, body)    => axios.post(`${BASE}${path}`, body)
const _authPatch = (path, body, token) => axios.patch(`${BASE}${path}`, body, { headers: { Authorization: `Bearer ${token}` } })

// ─── Session timeout (Phase 9D) ───────────────────────────────────────────────
let _idleLogout = false
// Idle limits now live in store/authStore.js (30 days when 'Keep me signed in', 12h otherwise)

// ─── Main sidebar collapse widths (desktop only — mobile drawer is unaffected) ─
const SIDEBAR_W_OPEN   = 248
const SIDEBAR_W_CLOSED = 72

// ─── Sidebar navigation definition ───────────────────────────────────────────
// REPORTS-DEPT-1 Phase 3: `group` added to collapse the flat 11-item list
// into 3 sections in the sidebar. Nothing else about each item changed —
// same id/label/icon/module/active fields every existing consumer reads.
const NAV = [
  { id: 'leads',    label: 'Lead Center', icon: 'leads', module: '01', active: true, group: 'sales_marketing' },
  { id: 'conversations', label: 'Conversations',      icon: 'conversations', module: '02',  active: true, group: 'sales_marketing' },
  { id: 'knowledge', label: 'Knowledge', icon: 'knowledge', module: '15', active: true, group: 'sales_marketing' },   // WA-AUTO-4a (WhatsApp-only businesses)
  { id: 'whatsapp', label: 'WhatsApp Engine',      icon: 'whatsapp', module: '03', active: true, group: 'sales_marketing' },
  { id: 'event-funnels', label: 'Event Funnels', icon: 'event-funnels', module: '13', active: true, group: 'sales_marketing' },   // FUNNEL-1B
  { id: 'sites', label: 'Sites', icon: 'sites', module: '14', active: true, group: 'sales_marketing' },   // SITE-1A
  { id: 'business-activities', label: 'Business Activities', icon: 'business-activities', module: '12', active: true, group: 'business_activities' },
  { id: 'support',  label: 'Support Tickets',      icon: 'support', module: '04', active: true, group: 'operations' },
  { id: 'renewal',  label: 'Client Subscription',     icon: 'renewal', module: '05', active: true, group: 'operations' },
  { id: 'ops',      label: 'Operations Hub',     icon: 'ops', module: '06', active: true, group: 'operations' },
  { id: 'tasks',    label: 'Tasks Board',            icon: 'tasks', module: '08', active: true, group: 'operations' },
  { id: 'commissions', label: 'Commissions',        icon: 'commissions', module: '09',  active: true, group: 'operations' },
  { id: 'performance', label: 'Performance Hub',    icon: 'performance', module: '07',  active: true, group: 'insights' },
  { id: 'reports',     label: 'Reports', icon: 'reports', module: '10',  active: true, group: 'insights' },
  { id: 'project-planner', label: 'Project Planner', icon: 'project-planner', module: '11', active: true, group: 'insights' },
]

const NAV_GROUPS = [
  { id: 'sales_marketing', label: 'Sales & Marketing' },
  { id: 'business_activities', label: 'Business Activities' },
  { id: 'operations',      label: 'Operations' },
  { id: 'insights',        label: 'Insights' },
]


// ─── Nav icon map (Lucide components keyed by nav id) ────────────────────────
const NAV_ICONS = {
  leads:         Target,
  conversations: MessageSquare,
  knowledge:     BookOpen,
  whatsapp:      MessageCircle,
  support:       Ticket,
  renewal:       RefreshCw,
  ops:           BarChart2,
  performance:   BarChart2,
  tasks:         CheckSquare,
  commissions:   Briefcase,
  reports:       ClipboardList,
  'project-planner': FolderKanban,
  'business-activities': Layers,
  'event-funnels': CalendarClock,   // FUNNEL-1B
  sites: Globe,   // SITE-1A
}

// ─── Root ─────────────────────────────────────────────────────────────────────

export default function App() {
  const { token, setAuth } = useAuthStore()


  useEffect(() => {
    if (document.getElementById('opsra-fonts')) return
    const link  = document.createElement('link')
    link.id     = 'opsra-fonts'
    link.rel    = 'stylesheet'
    link.href   = 'https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700;800&display=swap'
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
      @keyframes slideInRight { from { transform: translateX(100%); } to { transform: translateX(0); } }
    `
    document.head.appendChild(style)
  }, [])

  if (window.location.pathname.startsWith('/catalog/') || window.location.pathname.startsWith('/shop/')) return <PublicCatalogShell />   // STORE-5: /shop/ is the short link
  if (window.location.pathname === '/privacy') return <PrivacyPolicy />
  if (window.location.pathname === '/data-deletion') return <DataDeletion />
  if (window.location.pathname.startsWith('/owner-dashboard/')) return <OwnerDashboardPage />
  if (window.location.pathname === '/terms') return <TermsOfService />
  if (window.location.pathname === '/auth/update-password') return <UpdatePasswordScreen />
  const _logMatch = window.location.pathname.match(/^\/log\/([a-f0-9]{64})$/)
  if (_logMatch) {
    const PublicLogPage = require('./pages/PublicLogPage').default
    return <PublicLogPage token={_logMatch[1]} />
  }
  // PARTNER-1A — a Launch Partner's permanent link: opens a fresh client brief form.
  const _partnerMatch = window.location.pathname.match(/^\/p\/([A-Za-z0-9_-]{6,64})$/)
  if (_partnerMatch) {
    const PartnerLinkPage = require('./pages/PartnerLinkPage').default
    return <PartnerLinkPage slug={_partnerMatch[1]} />
  }
  // GIVEAWAY-1 — a group giveaway page with the live slot counter.
  const _giveawayMatch = window.location.pathname.match(/^\/g\/([A-Za-z0-9_-]{6,64})$/)
  if (_giveawayMatch) {
    const GiveawayPage = require('./pages/GiveawayPage').default
    return <GiveawayPage slug={_giveawayMatch[1]} />
  }
  // WEBCHAT-1 — a business's public chat page (the key names the business; no login).
  const _chatMatch = window.location.pathname.match(/^\/c\/(wc_[A-Za-z0-9_-]{8,40})$/)
  if (_chatMatch) {
    const WebChatPage = require('./pages/WebChatPage').default
    return <WebChatPage chatKey={_chatMatch[1]} />
  }
  // BILL-4 — a business's invoice-style billing page (the token names the business; no login).
  const _payMatch = window.location.pathname.match(/^\/pay\/([A-Za-z0-9_-]{20,80})$/)
  if (_payMatch) {
    const PayLinkPage = require('./pages/PayLinkPage').default
    return <PayLinkPage token={_payMatch[1]} />
  }
  // BOOKING-1 — a lead's private booking page (the token names the lead and the business; no login).
  const _bookMatch = window.location.pathname.match(/^\/b\/([A-Za-z0-9_-]{20,64})$/)
  if (_bookMatch) {
    const BookingPage = require('./pages/BookingPage').default
    return <BookingPage token={_bookMatch[1]} />
  }
  // GIVEAWAY-1 — a winner's private page: preview, terms and payment.
  const _winnerMatch = window.location.pathname.match(/^\/w\/([A-Za-z0-9_-]{20,128})$/)
  if (_winnerMatch) {
    const WinnerPage = require('./pages/WinnerPage').default
    return <WinnerPage token={_winnerMatch[1]} />
  }
  // PARTNER-1B — Partner sign in / apply (/partner) and the partner portal (/partner/login?t=…).
  if (window.location.pathname === '/partner' || window.location.pathname === '/partner/login') {
    const PartnerPage = require('./pages/PartnerPage').default
    return <PartnerPage />
  }
  // SITE-1B — public brief-form link, spec §7.3. Tokens are secrets.token_urlsafe(32)
  // (~43 URL-safe base64 chars, no padding); the range below is a safe margin.
  const _formMatch = window.location.pathname.match(/^\/f\/([A-Za-z0-9_-]{20,80})$/)
  if (_formMatch) {
    const SiteBriefFormPage = require('./pages/SiteBriefFormPage').default
    return <SiteBriefFormPage token={_formMatch[1]} />
  }
  // SITE-2B — builder web editor/portal. Entry is always a magic link
  // (`/b/login?t=<token>`); the page reads `t` itself and owns every other
  // screen (My sites / Editor / Account) as in-memory view state, same
  // standalone-page pattern as SiteBriefFormPage above.
  // HOST-1 — public "Host with Opsra" page for people who built their site elsewhere: sign in, then upload.
  if (window.location.pathname === '/host') {
    return <HostLandingPage />
  }
  // WA-AUTO-5 — public sign-up for WhatsApp-automation-only businesses.
  if (window.location.pathname === '/start/whatsapp') {
    return <WaSignupPage />
  }
  // WEB-ONLY-1b — public sign-up for web-chat-only businesses (Chioma on the website).
  if (window.location.pathname === '/start/chat') {
    return <ChatSignupPage />
  }
  // OWNER-LANDING-1 — public landing page + pricing for business owners.
  if (window.location.pathname === '/business') {
    return <OwnerLandingPage />
  }
  // CHIOMA-LANDING-1 — public landing page for Chioma, the web chat assistant.
  if (window.location.pathname === '/chioma') {
    return <ChiomaLandingPage />
  }
  // SITE-LANDING — public builder landing page + sign-in. `/b/*` with no magic-link
  // token (bookmarked, or the link was already used) lands here instead of a dead end.
  if (
    window.location.pathname === '/sites' ||
    window.location.pathname === '/builders' ||
    (window.location.pathname.startsWith('/b/') && !new URLSearchParams(window.location.search).get('t'))
  ) {
    return <SiteLandingPage />
  }
  if (window.location.pathname.startsWith('/b/')) {
    const BuilderPortalPage = require('./pages/BuilderPortalPage').default
    return <BuilderPortalPage />
  }
  if (!token) return <LoginScreen onAuth={setAuth} />
  return (
    <ErrorBoundary>
      <AppShell />
    </ErrorBoundary>
  )
}

// ─── Update Password screen (reset link landing page) ────────────────────────

function UpdatePasswordScreen() {
  const { setAuth } = useAuthStore()

  // Supabase embeds the token in the URL hash as access_token
  const [accessToken] = useState(() => {
    const h = new URLSearchParams(window.location.hash.replace('#', ''))
    const q = new URLSearchParams(window.location.search)
    return h.get('access_token') || q.get('access_token') || null
  })
  const [errorCode] = useState(() => {
    const h = new URLSearchParams(window.location.hash.replace('#', ''))
    const q = new URLSearchParams(window.location.search)
    return h.get('error_code') || q.get('error_code') || null
  })
  const [errorDesc] = useState(() => {
    const h = new URLSearchParams(window.location.hash.replace('#', ''))
    const q = new URLSearchParams(window.location.search)
    return h.get('error_description') || q.get('error_description') || null
  })

  const [password, setPassword]   = useState('')
  const [confirm, setConfirm]     = useState('')
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState(
    errorCode ? (errorCode === 'otp_expired'
      ? 'This reset link has expired. Please request a new one.'
      : decodeURIComponent((errorDesc ?? '').replace(/\+/g, ' ')) || 'Invalid reset link.')
    : null
  )
  const [done, setDone]           = useState(false)
  const [showPwd, setShowPwd]     = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)

  const handleSubmit = async () => {
    if (!password || password.length < 8) { setError('Password must be at least 8 characters.'); return }
    if (password !== confirm) { setError('Passwords do not match.'); return }
    if (!accessToken) { setError('Invalid or missing reset token. Please request a new reset link.'); return }
    setLoading(true)
    setError(null)
    try {
      await _authPatch('/api/v1/auth/update-password', { new_password: password }, accessToken)
      setDone(true)
      // Redirect to login after 3 seconds
      setTimeout(() => { window.location.href = '/' }, 3000)
    } catch (e) {
      const msg = e?.response?.data?.detail?.message
      setError(msg || 'Password update failed. The link may have expired — please request a new one.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: ds.light, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
      <div style={{ background: 'white', border: `1px solid ${ds.border}`, borderRadius: 28, padding: '48px 44px', width: '100%', maxWidth: 420, boxShadow: '0 24px 60px rgba(20,24,31,0.10)' }}>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 32 }}>
          <OpsraMark size={44} />
          <div>
            <p style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: ds.dark, margin: 0 }}>Opsra</p>
            <p style={{ fontSize: 11, color: '#5B6270', letterSpacing: '1px', textTransform: 'uppercase', margin: 0 }}>AI Growth System</p>
          </div>
        </div>

        {done ? (
          <>
            <div style={{ display:'flex',justifyContent:'center',marginBottom:16}}><CheckSquare size={40} color={ds.green} strokeWidth={1.5} /></div>
            <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: ds.dark, margin: '0 0 12px', textAlign: 'center' }}>Password updated</h1>
            <p style={{ fontSize: 13, color: '#5B6270', textAlign: 'center', lineHeight: 1.6 }}>
              Your password has been changed successfully.<br />
              Redirecting you to sign in…
            </p>
          </>
        ) : (
          <>
            <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 24, color: ds.dark, margin: '0 0 8px' }}>Set new password</h1>
            <p style={{ fontSize: 13, color: '#5B6270', marginBottom: 28, lineHeight: 1.6 }}>Choose a strong password for your Opsra account.</p>

            {error && (
              <div style={{ background: '#FDECEA', border: '1px solid #F5C6C2', borderRadius: 8, padding: '10px 14px', marginBottom: 20 }}>
                <p style={{ fontSize: 13, color: '#B3261E', margin: 0 }}>{error}</p>
                {(errorCode || !accessToken) && (
                  <a href="/" style={{ fontSize: 12, color: '#1F54B8', display: 'block', marginTop: 8, textDecoration: 'underline' }}>
                    ← Back to sign in to request a new link
                  </a>
                )}
              </div>
            )}

            {!errorCode && accessToken && (
              <>
                {/* AI-SUGGEST-1 eye toggle state */}
            <label style={loginLabel}>New password</label>
            <div style={{ position: 'relative', marginBottom: 20 }}>
              <input
                type={showPwd ? 'text' : 'password'} placeholder="Min 8 characters"
                value={password} onChange={e => { setPassword(e.target.value); setError(null) }}
                onKeyDown={e => { if (e.key === 'Enter') handleSubmit() }}
                style={{ ...loginInput, marginBottom: 0, paddingRight: 44 }}
              />
              <button
                type="button" onClick={() => setShowPwd(p => !p)}
                style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: '#5B6270', fontSize: 16, padding: 4, lineHeight: 1 }}
                title={showPwd ? 'Hide password' : 'Show password'}
              >{showPwd ? <EyeOff size={16} /> : <Eye size={16} />}</button>
            </div>
            <label style={loginLabel}>Confirm new password</label>
            <div style={{ position: 'relative', marginBottom: 28 }}>
              <input
                type={showConfirm ? 'text' : 'password'} placeholder="Repeat your password"
                value={confirm} onChange={e => { setConfirm(e.target.value); setError(null) }}
                onKeyDown={e => { if (e.key === 'Enter') handleSubmit() }}
                style={{ ...loginInput, marginBottom: 0, paddingRight: 44 }}
              />
              <button
                type="button" onClick={() => setShowConfirm(p => !p)}
                style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: '#5B6270', fontSize: 16, padding: 4, lineHeight: 1 }}
                title={showConfirm ? 'Hide password' : 'Show password'}
              >{showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}</button>
            </div>
                <button onClick={handleSubmit} disabled={loading} style={loginBtn(loading)}>
                  {loading ? <Spinner label="Updating…" /> : 'Set New Password'}
                </button>
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ─── Login screen ─────────────────────────────────────────────────────────────

function LoginScreen({ onAuth }) {
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)

  const [keepSignedIn, setKeepSignedIn] = useState(true)   // AUTH-SESSION-1
  const [idleMsg] = useState(() => {
    if (_idleLogout) { _idleLogout = false; return true }
    return false
  })

  // Forgot password flow: 'login' | 'forgot' | 'reset_sent'
  const [forgotView, setForgotView]   = useState('login')
  const [forgotEmail, setForgotEmail] = useState('')
  const [forgotLoading, setForgotLoading] = useState(false)
  const [forgotError, setForgotError]   = useState(null)

  const handleForgotSubmit = async () => {
    if (!forgotEmail.trim()) { setForgotError('Please enter your email address.'); return }
    setForgotLoading(true)
    setForgotError(null)
    try {
      await _authPost('/api/v1/auth/reset-password', { email: forgotEmail.trim().toLowerCase() })
      setForgotView('reset_sent')
    } catch {
      // Always show success — never reveal if email exists
      setForgotView('reset_sent')
    } finally {
      setForgotLoading(false)
    }
  }

  const [showLoginPwd, setShowLoginPwd] = useState(false)
  const [mfaStep, setMfaStep]           = useState(false)
  const [mfaCode, setMfaCode]       = useState('')
  const [pendingAuth, setPendingAuth] = useState(null)

  const handleLogin = async () => {
    if (!email || !password) { setError('Email and password are required.'); return }
    setLoading(true)
    setError(null)
    try {
      const res = await axios.post(`${BASE}/api/v1/auth/login`, { email, password })
      if (res.data.success) {
        const { access_token, refresh_token, user, mfa_required, factor_id } = res.data.data
        if (mfa_required && factor_id) {
          setPendingAuth({ access_token, factor_id, user })
          setMfaStep(true)
          return
        }
        await _finishLogin(access_token, user, refresh_token)
      } else {
        setError(res.data.error?.message ?? res.data.error ?? 'Login failed')
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
      await _finishLogin(verifyRes.data.data.access_token, user, verifyRes.data.data.refresh_token)
    } catch (err) {
      const status = err?.response?.status
      if (status === 422) setError('Invalid code. Please try again.')
      else setError('Verification failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const _finishLogin = async (access_token, user, refresh_token) => {
    // refresh_token may be missing (older API); store null so keep/expiry still apply
    const refresh = refresh_token ?? null
    try {
      const meRes = await axios.get(`${BASE}/api/v1/auth/me`, {
        headers: { Authorization: `Bearer ${access_token}` },
      })
      onAuth(access_token, meRes.data?.data ?? user, refresh, keepSignedIn)
    } catch {
      onAuth(access_token, user, refresh, keepSignedIn)
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
    <div style={{ position: 'fixed', inset: 0, background: ds.light, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
      <div style={{
        background:   'white',
        border:       `1px solid ${ds.border}`,
        borderRadius: 28,
        padding:      '48px 44px',
        width:        '100%',
        maxWidth:     420,
        boxShadow:    '0 24px 60px rgba(20,24,31,0.10)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 32 }}>
          <OpsraMark size={44} />
          <div>
            <p style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: ds.dark, margin: 0 }}>Opsra</p>
            <p style={{ fontSize: 11, color: '#5B6270', letterSpacing: '1px', textTransform: 'uppercase', margin: 0 }}>AI Growth System</p>
          </div>
        </div>

        {mfaStep ? (
          <>
            <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: ds.dark, margin: '0 0 8px' }}>Two-factor authentication</h1>
            <p style={{ fontSize: 13, color: '#5B6270', marginBottom: 24, lineHeight: 1.6 }}>Enter the 6-digit code from your authenticator app.</p>
            <label style={loginLabel}>Authentication code</label>
            <input
              type="text" inputMode="numeric" placeholder="000000" maxLength={6}
              value={mfaCode} onChange={e => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              onKeyDown={handleKeyDown} autoComplete="one-time-code"
              style={{ ...loginInput, marginBottom: 24, letterSpacing: '0.3em', textAlign: 'center', fontSize: 22 }}
            />
            {error && <p style={{ fontSize: 13, color: '#B3261E', marginBottom: 16 }}>{error}</p>}
            <button onClick={handleMfaVerify} disabled={loading} style={loginBtn(loading)}>
              {loading ? <Spinner label="Verifying…" /> : 'Verify code'}
            </button>
            <button onClick={() => { setMfaStep(false); setPendingAuth(null); setMfaCode(''); setError(null) }}
              style={{ width: '100%', background: 'none', border: 'none', marginTop: 12, fontSize: 13, color: '#5B6270', cursor: 'pointer', textDecoration: 'underline' }}>
              ← Back to sign in
            </button>
          </>
        ) : forgotView === 'forgot' ? (
          <>
            <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: ds.dark, margin: '0 0 8px' }}>Reset your password</h1>
            <p style={{ fontSize: 13, color: '#5B6270', marginBottom: 24, lineHeight: 1.6 }}>Enter your email address and we'll send you a reset link.</p>
            <label style={loginLabel}>Email address</label>
            <input
              type="email" placeholder="you@example.com"
              value={forgotEmail} onChange={e => setForgotEmail(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleForgotSubmit() }}
              autoComplete="email"
              style={{ ...loginInput, marginBottom: 24 }}
            />
            {forgotError && <p style={{ fontSize: 13, color: '#B3261E', marginBottom: 16 }}>{forgotError}</p>}
            <button onClick={handleForgotSubmit} disabled={forgotLoading} style={loginBtn(forgotLoading)}>
              {forgotLoading ? <Spinner label="Sending…" /> : 'Send Reset Link'}
            </button>
            <button
              onClick={() => { setForgotView('login'); setForgotError(null) }}
              style={{ width: '100%', background: 'none', border: 'none', marginTop: 12, fontSize: 13, color: '#5B6270', cursor: 'pointer', textDecoration: 'underline' }}
            >
              ← Back to sign in
            </button>
          </>
        ) : forgotView === 'reset_sent' ? (
          <>
            <div style={{ display:'flex',justifyContent:'center',marginBottom: 16 }}><Mail size={40} color={ds.teal} strokeWidth={1.5} /></div>
            <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: ds.dark, margin: '0 0 12px', textAlign: 'center' }}>Check your email</h1>
            <p style={{ fontSize: 13, color: '#5B6270', marginBottom: 24, lineHeight: 1.6, textAlign: 'center' }}>
              If an account exists for <strong style={{ color: '#A0BDC8' }}>{forgotEmail}</strong>, a reset link has been sent.<br />
              The link expires in 1 hour.
            </p>
            <p style={{ fontSize: 12, color: '#5B6270', background: '#F6F7FA', borderRadius: 8, padding: '10px 14px', lineHeight: 1.6, marginBottom: 20 }}>
              Didn't receive it? Check your spam folder, or contact your administrator who can send the link directly.
            </p>
            <button
              onClick={() => { setForgotView('login'); setForgotError(null); setForgotEmail('') }}
              style={loginBtn(false)}
            >
              Back to sign in
            </button>
          </>
        ) : (
          <>
            <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 26, color: ds.dark, margin: '0 0 8px' }}>Welcome back</h1>
            <p style={{ fontSize: 14, color: '#5B6270', marginBottom: 28, lineHeight: 1.6 }}>Sign in to access your operations dashboard.</p>
            <label style={loginLabel}>Email address</label>
            <input type="email" placeholder="you@example.com" value={email} onChange={e => setEmail(e.target.value)} onKeyDown={handleKeyDown} autoComplete="email" style={loginInput} />
            <label style={loginLabel}>Password</label>
            <div style={{ position: 'relative', marginBottom: 24 }}>
              <input
                type={showLoginPwd ? 'text' : 'password'}
                placeholder="••••••••" value={password}
                onChange={e => setPassword(e.target.value)}
                onKeyDown={handleKeyDown} autoComplete="current-password"
                style={{ ...loginInput, marginBottom: 0, paddingRight: 44 }}
              />
              <button
                type="button" onClick={() => setShowLoginPwd(p => !p)}
                style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: '#5B6270', fontSize: 16, padding: 4, lineHeight: 1 }}
                title={showLoginPwd ? 'Hide password' : 'Show password'}
              >{showLoginPwd ? <EyeOff size={16} /> : <Eye size={16} />}</button>
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16, fontSize: 13, color: '#5B6270', cursor: 'pointer', userSelect: 'none' }}>
              <input
                type="checkbox"
                checked={keepSignedIn}
                onChange={(e) => setKeepSignedIn(e.target.checked)}
                style={{ width: 16, height: 16, accentColor: '#2467E3', cursor: 'pointer' }}
              />
              Keep me signed in
            </label>
            {idleMsg && (
              <div style={{ background: '#E4EDFD', border: '1px solid #C9DAF8', borderRadius: 8, padding: '10px 14px', marginBottom: 16, fontSize: 13, color: '#1F54B8', lineHeight: 1.5 }}>
                <span style={{display:'inline-flex',alignItems:'center',gap:6}}><Lock size={14} />You have been logged out due to inactivity.</span>
              </div>
            )}
            {error && <p style={{ fontSize: 13, color: '#B3261E', marginBottom: 16 }}>{error}</p>}
            <button onClick={handleLogin} disabled={loading} style={loginBtn(loading)}>
              {loading ? <Spinner label="Signing in…" /> : 'Sign In'}
            </button>
            <p style={{ fontSize: 12, color: '#5B6270', textAlign: 'center', marginTop: 16 }}>
              <button
                onClick={() => { setForgotView('forgot'); setForgotEmail(''); setForgotError(null) }}
                style={{ background: 'none', border: 'none', color: '#1F54B8', cursor: 'pointer', fontSize: 12, textDecoration: 'underline', padding: 0 }}
              >
                Forgot your password?
              </button>
            </p>
            <p style={{ fontSize: 11, color: '#5B6270', textAlign: 'center', marginTop: 8 }}>
              <a href="/privacy" style={{ color: '#5B6270', textDecoration: 'none' }}>Privacy Policy</a>
              {" · "}
              <a href="/terms" style={{ color: '#5B6270', textDecoration: 'none' }}>Terms of Service</a>
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

  // Desktop sidebar collapsed/expanded — persisted preference (mirrors AdminModule pattern)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem('main_sidebar_collapsed') === 'true'
    } catch { return false }
  })

  function toggleSidebarCollapsed() {
    setSidebarCollapsed(prev => {
      const next = !prev
      try { localStorage.setItem('main_sidebar_collapsed', String(next)) } catch {}
      return next
    })
  }

  // Close drawer when tapping backdrop on mobile
  const handleBackdropClick = () => setSidebarOpen(false)

  // Close drawer on nav click on mobile
  const closeSidebarOnMobile = () => { if (isMobile) setSidebarOpen(false) }

  // ── Session idle timeout (Phase 9D → AUTH-SESSION-1) ────────────────────
  // Timestamp based: record activity (throttled in the store) and check on a
  // timer and whenever the tab becomes visible again.
  useEffect(() => {
    const store = useAuthStore.getState
    const check = () => {
      if (store().isSessionExpired()) { _idleLogout = true; clearAuth() }
    }
    const touch = () => store().touchActivity()
    const EVENTS = ['mousemove', 'keydown', 'mousedown', 'touchstart', 'scroll']
    EVENTS.forEach(ev => window.addEventListener(ev, touch, { passive: true }))
    const onVisible = () => { if (document.visibilityState === 'visible') check() }
    document.addEventListener('visibilitychange', onVisible)
    const iv = setInterval(check, 60 * 1000)
    check()
    return () => {
      clearInterval(iv)
      document.removeEventListener('visibilitychange', onVisible)
      EVENTS.forEach(ev => window.removeEventListener(ev, touch))
    }
  }, [clearAuth])

  const _userTemplate = user?.roles?.template ?? ''
  // AP-8: Sites and Superadmin belong to Opsra's own organisation only. This hides them; the server checks again on every route.
  const [isPlatformOrg, setIsPlatformOrg] = useState(false)
  // WA-AUTO-1: 'wa_automation' orgs see the inbox, billing and admin only. Remembered locally so the first paint is right; the server is the real gate.
  // WEB-ONLY-1b: 'web_chat' orgs (Chioma on the website) see the same trimmed app, with their own admin tabs and no WhatsApp set-up wizard.
  const [productMode, setProductMode] = useState(() => {
    try { const v = localStorage.getItem('opsra_product_mode'); return v === 'wa_automation' || v === 'web_chat' ? v : 'full' } catch { return 'full' }
  })
  const isWaOnly = productMode === 'wa_automation'
  const isChatOnly = productMode === 'web_chat'
  const isNoCrm = isWaOnly || isChatOnly
  // WA-AUTO-3: the owner of a WhatsApp-only business sees the set-up wizard until it is finished (or put off for now).
  const [waWizard, setWaWizard] = useState('unknown')   // unknown | show | hide
  useEffect(() => {
    if (!isWaOnly || !user || !['owner', 'ops_manager'].includes(user?.roles?.template ?? '')) { setWaWizard('hide'); return undefined }
    let live = true
    getWaOnboarding().then((s) => { if (live) setWaWizard(s?.completed ? 'hide' : 'show') }).catch(() => { if (live) setWaWizard('hide') })
    return () => { live = false }
  }, [isWaOnly, user?.id])
  useEffect(() => {
    let live = true
    if (!user) { setIsPlatformOrg(false); return undefined }
    getPlatformStatus().then((r) => {
      if (!live) return
      setIsPlatformOrg(!!r?.is_platform)
      const m = r?.product_mode === 'wa_automation' || r?.product_mode === 'web_chat' ? r.product_mode : 'full'
      setProductMode(m)
      try { localStorage.setItem('opsra_product_mode', m) } catch {}
    }).catch(() => { if (live) setIsPlatformOrg(false) })
    return () => { live = false }
  }, [user?.id])
  // REPORTS-DEPT-1 Phase 2/3: a department-scoped role (department_id set
  // on their role, e.g. "Marketing Lead") can now also see Reports —
  // mirrors ReportsModule.jsx's own RBAC gate exactly, so nav visibility
  // and actual page access never disagree.
  const _departmentId = user?.roles?.department_id ?? null
  const visibleNav = NAV.filter(item => {
    if (isNoCrm) return item.id === 'conversations' || item.id === 'knowledge'
    if (item.id === 'knowledge') return false
    if (item.id === 'ops'     && ['sales_agent', 'affiliate_partner'].includes(_userTemplate)) return false
    // FUNNEL-1B: Event Funnels — owner / ops_manager (edit) and admin (read-only)
    if (item.id === 'event-funnels' && !['owner', 'ops_manager', 'admin'].includes(_userTemplate)) return false
    // SITE-1A: Sites — owner / ops_manager (edit) and admin (read-only), same gate as Event Funnels
    if (item.id === 'sites' && (!isPlatformOrg || !['owner', 'ops_manager', 'admin'].includes(_userTemplate))) return false
    if (item.id === 'reports' && !['owner', 'ops_manager'].includes(_userTemplate) && !_departmentId) return false
    // Project Planner: owner + ops_manager only — a planning tool for leadership, not day-to-day staff
    if (item.id === 'project-planner' && !['owner', 'ops_manager'].includes(_userTemplate)) return false
    // Performance Hub: visible to all roles (each role sees their own scoped view)
    if (item.id === 'renewal' && _userTemplate === 'affiliate_partner') return false
    if (item.id === 'commissions') {
      return ['owner', 'ops_manager', 'sales_agent', 'affiliate_partner'].includes(_userTemplate)
        || useAuthStore.getState().hasPermission('is_admin')
    }
    return true
  })

  const [view, setView]                     = useState('leads')
  // WA-AUTO-1: keep wa_automation orgs on screens they own (WEB-ONLY-1b: and web_chat orgs).
  useEffect(() => {
    if (!isNoCrm) return
    if (!['conversations', 'knowledge', 'billing', 'admin'].includes(view)) { setView('conversations'); setActiveNav('conversations') }
  }, [isNoCrm, view])
  const [selectedLeadId, setSelectedLeadId] = useState(null)
  const [showNotif, setShowNotif]           = useState(false)
  const [unreadCount, setUnreadCount]       = useState(0)

  const [ariaOpen,     setAriaOpen]    = useState(false)
  const [ariaBriefing, setAriaBriefing] = useState(null)
  const [ariaBadge,    setAriaBadge]   = useState(false)
  const [ariaMinimised, setAriaMinimised] = useState(() => {
    try { return localStorage.getItem('aria_minimised') === '1' } catch { return false }
  })

  // ACCOUNT-PLANS AP-3: coming back from Paystack after paying for a plan (?plan=1) lands on Billing.
  useEffect(() => {
    try {
      if (new URLSearchParams(window.location.search).get('plan') && ['owner', 'ops_manager', 'admin'].includes(_userTemplate)) {
        setActiveNav('billing'); setView('billing')
      }
    } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
  const [isOOO, setIsOOO] = useState(user?.is_out_of_office ?? false)
  const [oooLoading, setOooLoading] = useState(false)

  const handleAvailabilityToggle = async () => {
    const newVal = !isOOO
    setIsOOO(newVal)
    setOooLoading(true)
    try {
      const token = useAuthStore.getState().token
      await axios.patch(
        `${BASE}/api/v1/auth/me/availability`,
        { is_out_of_office: newVal },
        { headers: { Authorization: `Bearer ${token}` } }
      )
    } catch {
      setIsOOO(!newVal)
    } finally {
      setOooLoading(false)
    }
  }

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

  // ── UI-REDESIGN-1 shell: light sidebar (no module numbers), light top bar, mobile bottom tab bar + More sheet ──
  const collapsed = !isMobile && sidebarCollapsed   // desktop-only collapse
  const [moreOpen, setMoreOpen] = useState(false)
  // The Setup checklist's floating tab is gone; the checklist opens from the Admin section instead.
  const [setupAvailable, setSetupAvailable] = useState(false)
  useEffect(() => {
    const sync = () => setSetupAvailable(window.__opsraSetupAvailable === true)
    sync()
    window.addEventListener('opsra:setup-state', sync)
    return () => window.removeEventListener('opsra:setup-state', sync)
  }, [])
  const [threadOpen, setThreadOpen] = useState(false)   // a conversation is open on a phone: hide the tab bar for the message box
  useEffect(() => {
    const sync = () => setThreadOpen(window.__opsraThreadOpen === true)
    sync()
    window.addEventListener('opsra:thread-state', sync)
    return () => window.removeEventListener('opsra:thread-state', sync)
  }, [])
  const hideTabs = isMobile && view === 'conversations' && threadOpen
  const canBilling = ['owner', 'ops_manager', 'admin'].includes(_userTemplate)
  const openSetup = () => { setMoreOpen(false); window.dispatchEvent(new Event('opsra:open-setup')) }
  const goTo = (id) => { setMoreOpen(false); setActiveNav(id); setView(id); setSelectedLeadId(null) }
  const NAV_INK = '#3C4352'

  const navRow = (key, label, Icon, isActive, onClick, disabled) => (
    <button
      key={key} type="button" onClick={onClick}
      title={disabled ? 'Coming soon' : (collapsed ? label : undefined)}
      aria-current={isActive ? 'page' : undefined}
      style={{
        display: 'flex', alignItems: 'center', gap: collapsed ? 0 : 12,
        justifyContent: collapsed ? 'center' : 'flex-start',
        width: 'calc(100% - 16px)', margin: '1px 8px', padding: collapsed ? 0 : '0 12px', minHeight: 42,
        borderRadius: 10, border: 'none', cursor: disabled ? 'default' : 'pointer',
        fontFamily: ds.fontDm, fontSize: 14.5, fontWeight: isActive ? 600 : 500, textAlign: 'left',
        color: isActive ? ds.tealDark : NAV_INK, background: isActive ? ds.mint : 'transparent',
        opacity: disabled ? 0.5 : 1, transition: 'background 0.15s',
      }}
    >
      {Icon && <Icon size={19} strokeWidth={isActive ? 2.2 : 1.8} style={{ flexShrink: 0 }} />}
      {!collapsed && <span style={{ flex: 1, lineHeight: 1.3 }}>{label}</span>}
    </button>
  )
  const groupLabel = (text) => (
    <div style={{ padding: '14px 20px 4px', fontSize: 11.5, fontWeight: 600, color: ds.gray, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{text}</div>
  )

  const sidebarContent = (
    <>
      <div style={{ paddingTop: 8 }}>
        {NAV_GROUPS.map(group => {
          const itemsInGroup = visibleNav.filter(item => item.group === group.id)
          if (itemsInGroup.length === 0) return null   // e.g. Insights entirely hidden for a role
          return (
            <div key={group.id}>
              {!collapsed && groupLabel(group.label)}
              {collapsed && group.id !== 'sales_marketing' && <div style={{ height: 1, background: ds.border, margin: '10px 12px 4px' }} />}
              {itemsInGroup.map(item => navRow(item.id, item.label, NAV_ICONS[item.id], activeNav === item.id, () => handleNavClick(item.id), !item.active))}
            </div>
          )
        })}
        {!collapsed && groupLabel('Admin')}
        {collapsed && <div style={{ height: 1, background: ds.border, margin: '14px 12px 4px' }} />}
        {canBilling && navRow('billing', 'Billing', CreditCard, activeNav === 'billing', () => goTo('billing'))}
        {navRow('admin', 'Admin Dashboard', Settings, activeNav === 'admin', () => goTo('admin'))}
        {setupAvailable && navRow('setup', 'Setup checklist', CheckSquare, false, openSetup)}
      </div>
      <div style={{ marginTop: 'auto', padding: 12 }}>
        <button
          type="button" onClick={toggleSidebarCollapsed}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          style={{ width: '100%', minHeight: 40, border: `1px solid ${ds.border}`, borderRadius: 10, background: 'white', color: NAV_INK, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, fontFamily: ds.fontDm, fontSize: 14, fontWeight: 600 }}
        >
          {collapsed ? <ChevronRight size={16} /> : <><ChevronLeft size={16} />Collapse menu</>}
        </button>
      </div>
    </>
  )

  // Mobile bottom tabs: the same modules the drawer showed, in the same role rules, with the rest under More.
  const TAB_ORDER = ['leads', 'conversations', 'tasks', 'support']
  const TAB_SHORT = { conversations: 'Chats', tasks: 'Tasks', support: 'Support', knowledge: 'Knowledge' }
  const tabItems = (isNoCrm ? visibleNav : TAB_ORDER.map(id => visibleNav.find(n => n.id === id))).filter(Boolean).slice(0, 4)
  const tabIds = tabItems.map(n => n.id)
  const moreActive = !tabIds.includes(activeNav)
  const tile = (key, label, Icon, onClick, tone) => (
    <button key={key} type="button" onClick={onClick} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, minHeight: 44, border: 'none', background: 'transparent', cursor: 'pointer', fontFamily: ds.fontDm, fontSize: 12.5, fontWeight: 600, color: ds.dark, textAlign: 'center', padding: 0 }}>
      <span style={{ width: 52, height: 52, borderRadius: 16, background: tone === 'admin' ? '#EFE6FB' : ds.mint, color: tone === 'admin' ? ds.purple : ds.tealDark, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Icon size={23} strokeWidth={1.9} /></span>
      <span style={{ lineHeight: 1.2 }}>{label}</span>
    </button>
  )

  const pillBtn = { ...topbarBtn }

  return (
    <div style={{ fontFamily: ds.fontDm, background: ds.light, minHeight: '100vh' }}>

      {/* ── Topbar ─────────────────────────────────────────────────────────── */}
      <header style={{
        position: 'fixed', top: 0, left: 0, right: 0,
        height: 60, background: 'white', zIndex: ds.z.topbar,
        borderBottom: `1px solid ${ds.border}`,
        display: 'flex', alignItems: 'center', padding: isMobile ? '0 8px 0 16px' : '0 20px', gap: 12,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontFamily: ds.fontSyne, fontWeight: 700, fontSize: isMobile ? 18 : 19, letterSpacing: '-0.03em', color: ds.dark, flex: isMobile ? 1 : undefined }}>
          <OpsraMark size={isMobile ? 28 : 32} />
          Opsra
        </div>

        <div style={{ marginLeft: isMobile ? 0 : 'auto', display: 'flex', alignItems: 'center', gap: isMobile ? 4 : 14 }}>
          {!isMobile && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{ width: 8, height: 8, background: ds.green, borderRadius: '50%', animation: 'pulse 2s infinite' }} />
                <span style={{ fontSize: 13, color: ds.gray }}>Live</span>
              </div>
              {isPlatformOrg && ['owner', 'ops_manager'].includes(_userTemplate) && (
                <button onClick={() => { setView('superadmin'); setActiveNav('') }} style={pillBtn}>Superadmin</button>
              )}
            </>
          )}

          {/* Notification bell — always visible */}
          <button
            onClick={() => setShowNotif(true)}
            aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : 'Notifications'}
            style={{ position: 'relative', background: 'white', border: isMobile ? 'none' : `1px solid ${ds.border}`, borderRadius: 999, cursor: 'pointer', color: NAV_INK, width: 44, height: 44, minWidth: 44, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >
            <Bell size={isMobile ? 22 : 19} />
            {unreadCount > 0 && (
              <span style={{ position: 'absolute', top: isMobile ? 4 : -4, right: isMobile ? 2 : -4, background: '#E53E3E', color: 'white', borderRadius: 9, minWidth: 18, height: 18, padding: '0 4px', boxSizing: 'border-box', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700 }}>
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
          </button>

          {/* Desktop: user + availability toggle + sign out */}
          {!isMobile && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                <div style={{ position: 'relative' }}>
                  <div style={{ width: 34, height: 34, borderRadius: '50%', background: isOOO ? '#6B7280' : ds.teal, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 700, color: 'white' }}>
                    {userInitial}
                  </div>
                  <div style={{ position: 'absolute', bottom: 0, right: 0, width: 10, height: 10, borderRadius: '50%', background: isOOO ? '#F59E0B' : ds.green, border: '2px solid white' }} />
                </div>
                <span style={{ fontSize: 14, color: NAV_INK, fontWeight: 500 }}>{userName}</span>
              </div>
              <button
                onClick={handleAvailabilityToggle}
                disabled={oooLoading}
                title={isOOO ? 'You are out of office — click to mark available' : 'Click to go out of office'}
                style={{ ...pillBtn, borderColor: isOOO ? '#F59E0B' : ds.border, color: isOOO ? '#B45309' : NAV_INK }}
              >
                {oooLoading ? '…' : isOOO ? 'OOO' : 'Available'}
              </button>
              <button onClick={handleLogout} disabled={loggingOut} style={pillBtn}>
                {loggingOut ? 'Signing out…' : 'Sign out'}
              </button>
            </>
          )}
        </div>
      </header>

      {/* ── Sidebar (desktop) ─────────────────────────────────────────────── */}
      {!isMobile && (
        <nav aria-label="Main" style={{
          position: 'fixed', top: 60, left: 0, bottom: 0,
          width: sidebarCollapsed ? SIDEBAR_W_CLOSED : SIDEBAR_W_OPEN,
          background: 'white',
          borderRight: `1px solid ${ds.border}`,
          overflowY: 'auto', overflowX: 'hidden', zIndex: ds.z.sidebar,
          display: 'flex', flexDirection: 'column',
          transition: 'width 0.2s ease',
        }}>
          {sidebarContent}
        </nav>
      )}

      {/* ── Mobile: bottom tab bar + More sheet ───────────────────────────── */}
      {isMobile && (
        <>
          <nav aria-label="Main" style={{
            position: 'fixed', left: 0, right: 0, bottom: 0, zIndex: ds.z.mobileDrawer - 1,
            background: 'white', borderTop: `1px solid ${ds.border}`,
            display: hideTabs ? 'none' : 'flex', padding: '6px 4px', paddingBottom: 'calc(6px + env(safe-area-inset-bottom))', boxSizing: 'border-box',
          }}>
            {tabItems.map(item => {
              const Icon = NAV_ICONS[item.id]
              const on = activeNav === item.id
              return (
                <button key={item.id} type="button" onClick={() => goTo(item.id)} aria-current={on ? 'page' : undefined}
                  style={{ flex: 1, minWidth: 0, minHeight: 56, border: 'none', background: 'transparent', cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 3, fontFamily: ds.fontDm, fontSize: 12, fontWeight: on ? 700 : 600, color: on ? ds.tealDark : ds.gray }}>
                  <span style={{ width: 56, height: 30, borderRadius: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', background: on ? ds.mint : 'transparent' }}>{Icon && <Icon size={22} strokeWidth={on ? 2.2 : 1.8} />}</span>
                  {TAB_SHORT[item.id] ?? item.label}
                </button>
              )
            })}
            <button type="button" onClick={() => setMoreOpen(true)} aria-label="More" aria-expanded={moreOpen}
              style={{ flex: 1, minWidth: 0, minHeight: 56, border: 'none', background: 'transparent', cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 3, fontFamily: ds.fontDm, fontSize: 12, fontWeight: moreActive ? 700 : 600, color: moreActive ? ds.tealDark : ds.gray }}>
              <span style={{ width: 56, height: 30, borderRadius: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', background: moreActive ? ds.mint : 'transparent' }}><Menu size={22} strokeWidth={moreActive ? 2.2 : 1.8} /></span>
              More
            </button>
          </nav>

          {moreOpen && (
            <>
              <div onClick={() => setMoreOpen(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(20,24,31,0.45)', zIndex: ds.z.mobileDrawer, animation: 'fadeIn 0.15s ease' }} />
              <div role="dialog" aria-label="All modules" style={{
                position: 'fixed', left: 0, right: 0, bottom: 0, zIndex: ds.z.mobileDrawer + 1,
                background: 'white', borderRadius: '24px 24px 0 0', maxHeight: '88vh', overflowY: 'auto',
                padding: '10px 16px', paddingBottom: 'calc(20px + env(safe-area-inset-bottom))', boxSizing: 'border-box',
                animation: 'fadeIn 0.2s ease',
              }}>
                <div style={{ width: 40, height: 5, borderRadius: 999, background: ds.border, margin: '0 auto 14px' }} />
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: '14px 6px' }}>
                  {visibleNav.map(item => tile(item.id, item.label, NAV_ICONS[item.id] ?? Settings, () => { if (item.active) goTo(item.id) }))}
                </div>
                <div style={{ fontSize: 11.5, fontWeight: 600, color: ds.gray, textTransform: 'uppercase', letterSpacing: '0.06em', margin: '18px 0 8px' }}>Admin</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: '14px 6px' }}>
                  {canBilling && tile('billing', 'Billing', CreditCard, () => goTo('billing'), 'admin')}
                  {tile('admin', 'Admin Dashboard', Settings, () => goTo('admin'), 'admin')}
                  {setupAvailable && tile('setup', 'Setup checklist', CheckSquare, openSetup, 'admin')}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 18, paddingTop: 14, borderTop: `1px solid ${ds.border}` }}>
                  <div style={{ position: 'relative', flexShrink: 0 }}>
                    <div style={{ width: 40, height: 40, borderRadius: '50%', background: isOOO ? '#6B7280' : ds.teal, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 15, fontWeight: 700, color: 'white' }}>{userInitial}</div>
                    <div style={{ position: 'absolute', bottom: 0, right: 0, width: 10, height: 10, borderRadius: '50%', background: isOOO ? '#F59E0B' : ds.green, border: '2px solid white' }} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 15, color: ds.dark, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{userName}</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, color: isOOO ? '#B45309' : '#176A3C', marginTop: 2 }}><Circle size={8} fill="currentColor" strokeWidth={0} />{isOOO ? 'Out of office' : 'Available'}</div>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                  <button type="button" onClick={handleAvailabilityToggle} disabled={oooLoading}
                    style={{ flex: 1, minHeight: 46, border: `1px solid ${isOOO ? '#F59E0B' : ds.border}`, borderRadius: 999, background: 'white', color: isOOO ? '#B45309' : NAV_INK, fontFamily: ds.fontDm, fontSize: 14.5, fontWeight: 600, cursor: 'pointer' }}>
                    {oooLoading ? '…' : isOOO ? 'Mark as Available' : 'Go Out of Office'}
                  </button>
                  <button type="button" onClick={handleLogout} disabled={loggingOut}
                    style={{ flex: 1, minHeight: 46, border: `1px solid ${ds.border}`, borderRadius: 999, background: 'white', color: NAV_INK, fontFamily: ds.fontDm, fontSize: 14.5, fontWeight: 600, cursor: 'pointer' }}>
                    {loggingOut ? 'Signing out…' : 'Sign out'}
                  </button>
                </div>
              </div>
            </>
          )}
        </>
      )}

      {/* ── Main content ──────────────────────────────────────────────────── */}
      <main style={{
        marginLeft:   isMobile ? 0 : (sidebarCollapsed ? SIDEBAR_W_CLOSED : SIDEBAR_W_OPEN),
        marginTop:    60,
        minHeight:    'calc(100vh - 60px)',
        transition:   isMobile ? undefined : 'margin-left 0.2s ease',
        // Bottom padding on mobile to not clip content behind potential bottom bars
        paddingBottom: isMobile ? (hideTabs ? 0 : 'calc(84px + env(safe-area-inset-bottom))') : 0,
      }}>
        <BillingBanner role={_userTemplate} onOpen={() => { setActiveNav('billing'); setView('billing') }} />
        <PlanNotice role={_userTemplate} onOpenBilling={() => { setActiveNav('billing'); setView('billing') }} />
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
        {view === 'business-activities' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><BusinessActivitiesModule user={user} /></div>
        )}
        {view === 'event-funnels' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><EventFunnelsModule user={user} onOpenLead={openLeadProfile} /></div>
        )}
        {view === 'sites' && isPlatformOrg && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><SitesModule user={user} /></div>
        )}
        {view === 'tasks' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><TaskBoard user={user} onOpenLead={(leadId) =>openLeadProfile(leadId)} /></div>
        )}
        {view === 'admin' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><AdminModule user={user} waOnly={isWaOnly} chatOnly={isChatOnly} /></div>
        )}
        {view === 'billing' && ['owner', 'ops_manager', 'admin'].includes(_userTemplate) && (
          <div style={{ animation: 'fadeIn 0.25s ease', padding: 24 }}><BillingModule onOpenAdmin={() => { setActiveNav('admin'); setView('admin') }} /></div>
        )}
        {view === 'knowledge' && isNoCrm && <KnowledgeModule />}
        {view === 'conversations' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}>
            {isWaOnly && waWizard === 'show'
              ? <WaSetupWizard onDone={() => setWaWizard('hide')} onSkip={() => setWaWizard('hide')} onOpenBilling={() => { setWaWizard('hide'); setActiveNav('billing'); setView('billing') }} />
              : <ConversationsModule user={user} simple={isNoCrm} onOpenBilling={() => { setActiveNav('billing'); setView('billing') }} onOpenAria={() => setAriaOpen(true)} />}
          </div>
        )}
        {view === 'commissions' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><CommissionsModule user={user} /></div>
        )}
        {view === 'reports' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><ReportsModule user={user} /></div>
        )}
        {view === 'project-planner' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><ProjectPlannerModule /></div>
        )}
        {view === 'performance' && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><PerformanceModule user={user} /></div>
        )}
        {(view === 'superadmin' || view === 'superadmin_health' || view === 'superadmin_create_org') && isPlatformOrg && (
          <div style={{ animation: 'fadeIn 0.25s ease' }}><SuperadminShell initial={view === 'superadmin_create_org' ? 'create' : 'health'} /></div>
        )}
        {!['leads', 'lead-profile', 'demo-queue', 'whatsapp', 'support', 'renewal', 'ops', 'tasks', 'admin', 'conversations', 'commissions', 'superadmin', 'superadmin_create_org', 'superadmin_health', 'reports', 'performance', 'project-planner', 'business-activities', 'event-funnels', 'sites', 'billing', 'knowledge'].includes(view) && (
          <ComingSoon navId={view} />
        )}
      </main>

      {/* Notifications drawer */}
      {showNotif && (
        <NotificationsDrawer onClose={() => setShowNotif(false)} onUnreadChange={setUnreadCount} />
      )}

      {/* Aria AI Assistant (M01-10b) */}
      {/* Floating Aria button removed (UI-REDESIGN-1). Aria opens from the conversation header's Ask Aria. */}
      {!isNoCrm && <AriaPanel open={ariaOpen} onClose={() => setAriaOpen(false)} briefing={ariaBriefing} onBadgeClear={() => { setAriaBadge(false); setAriaBriefing(null) }} />}

      {/* Onboarding Checklist (ORG-ONBOARDING-B) */}
      <IOSInstallBanner />
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
        <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'center' }}>{(() => { const Icon = NAV_ICONS[item?.id]; return Icon ? <Icon size={48} color={ds.teal} strokeWidth={1.5} /> : <Settings size={48} color={ds.teal} strokeWidth={1.5} /> })()}</div>
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
  display: 'block', fontSize: 14, fontWeight: 600,
  color: '#3C4352', marginBottom: 6,
}

const loginInput = {
  width: '100%', background: 'white', border: `1.5px solid ${ds.border}`,
  borderRadius: 14, padding: '15px 16px', fontSize: 16,
  color: ds.dark, fontFamily: ds.fontDm, outline: 'none',
  transition: 'border-color 0.2s', marginBottom: 20, boxSizing: 'border-box',
}

const loginBtn = (loading) => ({
  width: '100%', background: loading ? '#1F54B8' : ds.teal,
  color: 'white', border: 'none', borderRadius: 999, padding: 15,
  fontSize: 16, fontWeight: 600, fontFamily: ds.fontSyne,
  cursor: loading ? 'not-allowed' : 'pointer', transition: 'background 0.2s',
})

const topbarBtn = {
  background: 'white', border: `1px solid ${ds.border}`,
  borderRadius: 999, padding: '0 16px', minHeight: 40,
  fontSize: 13.5, fontWeight: 600, color: '#3C4352', cursor: 'pointer',
  transition: 'all 0.15s', fontFamily: ds.fontDm,
}
