/**
 * frontend/src/modules/performance/PerformanceModule.jsx
 *
 * Top-level Performance & Operations Hub shell.
 * Handles role-based view routing:
 *   owner / ops_manager → Scorecard (default) or any sub-view
 *   all other staff     → My Performance only
 *
 * Pattern 13 — Zustand view-state, no react-router.
 * Pattern 26 — mount-and-hide tabs (never conditional render).
 * Pattern 56 — authStore: user id at user?.id, roles at user?.roles?.template.
 */
import { useState, useEffect } from 'react'
import { Link, X, Check, Lock, Unlock, AlertTriangle, Lightbulb, BarChart2, TrendingUp } from 'lucide-react'
import useAuthStore from '../../store/authStore'
import { ds } from '../../utils/ds'
import ScorecardView      from './ScorecardView'
import StaffProfileView   from './StaffProfileView'
import MyPerformanceView  from './MyPerformanceView'
import KpiTemplateManager from './KpiTemplateManager'
import BusinessGoalsTab   from './BusinessGoalsTab'
import {
  getOwnerDashboardSetup,
  setOwnerDashboardPin,
} from '../../services/performance.service'

const _MANAGER_ROLES = ['owner', 'ops_manager']

// ── Owner Dashboard Settings Drawer ────────────────────────────────────────

function OwnerDashboardDrawer({ onClose }) {
  const [setup,      setSetup]      = useState(null)
  const [loading,    setLoading]    = useState(true)
  const [pin,        setPin]        = useState('')
  const [pinConfirm, setPinConfirm] = useState('')
  const [pinLoading, setPinLoading] = useState(false)
  const [pinError,   setPinError]   = useState(null)
  const [pinSuccess, setPinSuccess] = useState(false)
  const [copied,     setCopied]     = useState(false)

  const dashboardUrl = setup?.token
    ? `${window.location.origin}/owner-dashboard/${setup.token}`
    : null

  useEffect(() => {
    getOwnerDashboardSetup()
      .then(data => setSetup(data))
      .catch(() => setPinError('Failed to load dashboard setup.'))
      .finally(() => setLoading(false))
  }, [])

  const handleCopy = () => {
    if (!dashboardUrl) return
    navigator.clipboard.writeText(dashboardUrl).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }).catch(() => {
      // Fallback for non-https or clipboard permission denied
      const el = document.createElement('textarea')
      el.value = dashboardUrl
      document.body.appendChild(el)
      el.select()
      document.execCommand('copy')
      document.body.removeChild(el)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const handleSetPin = async () => {
    if (!pin || pin.length < 4) { setPinError('PIN must be 4–6 digits.'); return }
    if (!/^\d{4,6}$/.test(pin))  { setPinError('PIN must be digits only.'); return }
    if (pin !== pinConfirm)       { setPinError('PINs do not match.'); return }
    setPinLoading(true)
    setPinError(null)
    try {
      await setOwnerDashboardPin(pin)
      setSetup(prev => ({ ...prev, pin_set: true }))
      setPinSuccess(true)
      setPin('')
      setPinConfirm('')
      setTimeout(() => setPinSuccess(false), 3000)
    } catch (e) {
      setPinError(e?.response?.data?.detail || 'Failed to set PIN.')
    } finally {
      setPinLoading(false)
    }
  }

  const INPUT = {
    width: '100%', border: '1px solid #e5e7eb', borderRadius: 8,
    padding: '10px 12px', fontSize: 13, fontFamily: 'inherit',
    boxSizing: 'border-box', outline: 'none',
  }
  const LBL = { fontSize: 12, color: '#6b7280', display: 'block', marginBottom: 4, fontWeight: 500 }

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
          zIndex: 200, animation: 'fadeIn 0.15s ease',
        }}
      />

      {/* Drawer */}
      <div style={{
        position: 'fixed', top: 0, right: 0, bottom: 0, width: '100%', maxWidth: 440,
        background: 'white', zIndex: 201, overflowY: 'auto',
        boxShadow: '-4px 0 32px rgba(0,0,0,0.12)',
        animation: 'slideInRight 0.25s cubic-bezier(0.4,0,0.2,1)',
        display: 'flex', flexDirection: 'column',
      }}>
        {/* Header */}
        <div style={{ padding: '20px 24px 16px', borderBottom: '1px solid #f3f4f6', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
          <div>
            <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 16, color: ds.dark }}>
              <span style={{display:"inline-flex",alignItems:"center",gap:7}}><Link size={16} />Owner Dashboard</span>
            </div>
            <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 2 }}>
              External view — accessible without logging into Opsra
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: '#6b7280', lineHeight: 1, padding: 4 }}
          ><X size={18} /></button>
        </div>

        <div style={{ padding: '20px 24px', flex: 1 }}>
          {loading && (
            <div style={{ textAlign: 'center', padding: 40, color: '#9ca3af', fontSize: 13 }}>Loading…</div>
          )}

          {!loading && (
            <>
              {/* How it works */}
              <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10, padding: '14px 16px', marginBottom: 24 }}>
                <div style={{ fontWeight: 600, fontSize: 13, color: '#065f46', marginBottom: 6 }}>How it works</div>
                <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: '#374151', lineHeight: 1.8 }}>
                  <li>Copy your unique dashboard link below</li>
                  <li>Open it on any device — no Opsra login needed</li>
                  <li>Enter your PIN to unlock the dashboard</li>
                  <li>View live org data: staff performance, tasks, tickets, goals</li>
                  <li>Approve or flag daily logs directly from the dashboard</li>
                </ol>
              </div>

              {/* Dashboard URL */}
              <div style={{ marginBottom: 24 }}>
                <label style={LBL}>Your dashboard link</label>
                {dashboardUrl ? (
                  <div style={{ display: 'flex', gap: 8 }}>
                    <div style={{
                      flex: 1, background: '#f9fafb', border: '1px solid #e5e7eb',
                      borderRadius: 8, padding: '10px 12px', fontSize: 12,
                      color: '#374151', wordBreak: 'break-all', lineHeight: 1.5,
                      fontFamily: 'monospace',
                    }}>
                      {dashboardUrl}
                    </div>
                    <button
                      onClick={handleCopy}
                      style={{
                        flexShrink: 0, background: copied ? '#d1fae5' : ds.teal,
                        color: copied ? '#065f46' : 'white', border: 'none',
                        borderRadius: 8, padding: '10px 14px', fontSize: 12,
                        fontWeight: 600, cursor: 'pointer', transition: 'all 0.2s',
                        minWidth: 70,
                      }}
                    >
                      {copied ? <span style={{display:'inline-flex',alignItems:'center',gap:4}}><Check size={13} />Copied</span> : 'Copy'}
                    </button>
                  </div>
                ) : (
                  <div style={{ fontSize: 13, color: '#9ca3af' }}>Generating link…</div>
                )}
                <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 6 }}>
                  Keep this link private. Anyone with the link + PIN can view your dashboard.
                </div>
              </div>

              {/* Open in new tab */}
              {dashboardUrl && (
                <a
                  href={dashboardUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    display: 'block', textAlign: 'center', background: '#f9fafb',
                    border: '1px solid #e5e7eb', borderRadius: 8, padding: '10px',
                    fontSize: 13, color: '#374151', textDecoration: 'none',
                    marginBottom: 24, fontWeight: 500,
                  }}
                >
                  ↗ Open dashboard in new tab
                </a>
              )}

              {/* Divider */}
              <div style={{ borderTop: '1px solid #f3f4f6', marginBottom: 24 }} />

              {/* PIN setup */}
              <div>
                <label style={{ ...LBL, fontSize: 13, color: ds.dark, fontWeight: 700 }}>
                  {setup?.pin_set ? <span style={{display:'inline-flex',alignItems:'center',gap:6}}><Lock size={13} />Update PIN</span> : <span style={{display:'inline-flex',alignItems:'center',gap:6}}><Unlock size={13} />Set a PIN</span>}
                </label>
                <p style={{ fontSize: 12, color: '#6b7280', marginBottom: 14, lineHeight: 1.6 }}>
                  {setup?.pin_set
                    ? 'Your PIN is set. Enter a new PIN below to change it.'
                    : 'You must set a PIN before the dashboard can be accessed. Use 4–6 digits.'}
                </p>

                {setup?.pin_set && (
                  <div style={{ background: '#d1fae5', border: '1px solid #6ee7b7', borderRadius: 7, padding: '8px 12px', marginBottom: 14, fontSize: 12, color: '#065f46' }}>
                    <span style={{display:"inline-flex",alignItems:"center",gap:5}}><Check size={13} />PIN is set — dashboard is accessible</span>
                  </div>
                )}

                {pinSuccess && (
                  <div style={{ background: '#d1fae5', border: '1px solid #6ee7b7', borderRadius: 7, padding: '8px 12px', marginBottom: 14, fontSize: 12, color: '#065f46' }}>
                    <span style={{display:"inline-flex",alignItems:"center",gap:5}}><Check size={13} />PIN updated successfully</span>
                  </div>
                )}

                {pinError && (
                  <div style={{ background: '#fee2e2', border: '1px solid #fca5a5', borderRadius: 7, padding: '8px 12px', marginBottom: 14, fontSize: 12, color: '#991b1b' }}>
                    <span style={{display:"inline-flex",alignItems:"center",gap:5}}><AlertTriangle size={13} />{pinError}</span>
                  </div>
                )}

                <label style={LBL}>New PIN (4–6 digits)</label>
                <input
                  type="password"
                  inputMode="numeric"
                  value={pin}
                  onChange={e => { setPin(e.target.value.replace(/\D/g, '').slice(0, 6)); setPinError(null) }}
                  placeholder="e.g. 1234"
                  maxLength={6}
                  style={{ ...INPUT, marginBottom: 12, letterSpacing: '0.3em', textAlign: 'center', fontSize: 18 }}
                />

                <label style={LBL}>Confirm PIN</label>
                <input
                  type="password"
                  inputMode="numeric"
                  value={pinConfirm}
                  onChange={e => { setPinConfirm(e.target.value.replace(/\D/g, '').slice(0, 6)); setPinError(null) }}
                  placeholder="Repeat PIN"
                  maxLength={6}
                  style={{ ...INPUT, marginBottom: 16, letterSpacing: '0.3em', textAlign: 'center', fontSize: 18 }}
                />

                <button
                  onClick={handleSetPin}
                  disabled={pinLoading || !pin || !pinConfirm}
                  style={{
                    width: '100%', background: pinLoading ? '#9ca3af' : ds.teal,
                    color: 'white', border: 'none', borderRadius: 8, padding: '12px',
                    fontSize: 13, fontWeight: 600, cursor: pinLoading ? 'not-allowed' : 'pointer',
                  }}
                >
                  {pinLoading ? 'Saving…' : setup?.pin_set ? 'Update PIN' : 'Set PIN'}
                </button>
              </div>

              {/* Divider */}
              <div style={{ borderTop: '1px solid #f3f4f6', margin: '24px 0' }} />

              {/* Bookmark tip */}
              <div style={{ background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 10, padding: '14px 16px' }}>
                <div style={{ fontWeight: 600, fontSize: 13, color: '#1e40af', marginBottom: 6 }}><span style={{display:"inline-flex",alignItems:"center",gap:5}}><Lightbulb size={13} />Tips</span></div>
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: '#374151', lineHeight: 1.8 }}>
                  <li>Bookmark the link on your phone for quick morning access</li>
                  <li>The dashboard auto-refreshes every 2 minutes</li>
                  <li>PIN sessions expire after 24 hours (closing the tab also clears the session)</li>
                  <li>Your link never changes — share it once and it works permanently</li>
                </ul>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  )
}

// ── Main module ─────────────────────────────────────────────────────────────

export default function PerformanceModule({ user }) {
  const roleTemplate = useAuthStore.getState().user?.roles?.template ?? ''
  const isManager    = _MANAGER_ROLES.includes(roleTemplate)
  const isOwner      = roleTemplate === 'owner'

  const [subView, setSubView]               = useState(isManager ? 'scorecard' : 'my-performance')
  const [selectedUserId, setSelectedUserId] = useState(null)
  const [selectedMonth, setSelectedMonth]   = useState(() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  })
  const [drawerOpen, setDrawerOpen] = useState(false)

  const openStaffProfile = (userId, month) => {
    setSelectedUserId(userId)
    if (month) setSelectedMonth(month)
    setSubView('staff-profile')
  }

  const backToScorecard = () => {
    setSelectedUserId(null)
    setSubView('scorecard')
  }

  const TAB_STYLE = (active) => ({
    padding: '8px 18px',
    borderRadius: 8,
    border: 'none',
    cursor: 'pointer',
    fontSize: 13,
    fontWeight: 500,
    fontFamily: ds.fontDm,
    background: active ? ds.teal : 'transparent',
    color: active ? 'white' : '#7A9BAD',
    transition: 'all 0.15s',
  })

  return (
    <div style={{ padding: '24px 28px', minHeight: '100vh', background: ds.light }}>

      {/* ── Header ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: ds.dark, margin: '0 0 4px' }}>
            <span style={{display:"inline-flex",alignItems:"center",gap:10}}><BarChart2 size={22} />Performance Hub</span>
          </h1>
          <p style={{ fontSize: 13, color: '#7A9BAD', margin: 0 }}>
            {isManager ? 'Org-wide performance tracking and KPI management' : 'Your personal performance and daily log'}
          </p>
        </div>

        {/* Owner-only buttons */}
        {isOwner && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0, flexWrap: 'wrap' }}>
            <button
              onClick={() => window.open('/ads-dashboard.html', '_blank')}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                background: 'white', border: '1px solid #e5e7eb',
                borderRadius: 9, padding: '8px 14px', fontSize: 13,
                fontWeight: 500, cursor: 'pointer', color: '#374151',
                boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
                transition: 'all 0.15s',
              }}
              onMouseEnter={e => e.currentTarget.style.borderColor = ds.teal}
              onMouseLeave={e => e.currentTarget.style.borderColor = '#e5e7eb'}
            >
              <span style={{display:"inline-flex",alignItems:"center",gap:6}}><TrendingUp size={14} />Ads Dashboard</span>
            </button>
            <button
              onClick={() => setDrawerOpen(true)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                background: 'white', border: '1px solid #e5e7eb',
                borderRadius: 9, padding: '8px 14px', fontSize: 13,
                fontWeight: 500, cursor: 'pointer', color: '#374151',
                boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
                transition: 'all 0.15s',
              }}
              onMouseEnter={e => e.currentTarget.style.borderColor = ds.teal}
              onMouseLeave={e => e.currentTarget.style.borderColor = '#e5e7eb'}
            >
              <span style={{display:"inline-flex",alignItems:"center",gap:6}}><Link size={14} />Owner Dashboard</span>
            </button>
          </div>
        )}
      </div>

      {/* ── Tab bar — managers only ── */}
      {isManager && subView !== 'staff-profile' && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 24, borderBottom: '1px solid #e5e7eb', paddingBottom: 16, flexWrap: 'wrap' }}>
          <button style={TAB_STYLE(subView === 'scorecard')}      onClick={() => setSubView('scorecard')}>Scorecard</button>
          <button style={TAB_STYLE(subView === 'my-performance')} onClick={() => setSubView('my-performance')}>My Performance</button>
          <button style={TAB_STYLE(subView === 'templates')}      onClick={() => setSubView('templates')}>KPI Templates</button>
          <button style={TAB_STYLE(subView === 'goals')}          onClick={() => setSubView('goals')}>Business Goals</button>
        </div>
      )}

      {/* ── Views — Pattern 26: mount-and-hide ── */}
      <div style={{ display: subView === 'scorecard' && isManager ? 'block' : 'none' }}>
        <ScorecardView onOpenProfile={openStaffProfile} />
      </div>

      <div style={{ display: subView === 'staff-profile' ? 'block' : 'none' }}>
        <StaffProfileView
          userId={selectedUserId}
          month={selectedMonth}
          onBack={backToScorecard}
          isManager={isManager}
        />
      </div>

      <div style={{ display: subView === 'my-performance' ? 'block' : 'none' }}>
        <MyPerformanceView user={user} />
      </div>

      <div style={{ display: subView === 'templates' && isManager ? 'block' : 'none' }}>
        <KpiTemplateManager />
      </div>

      <div style={{ display: subView === 'goals' && isManager ? 'block' : 'none' }}>
        <BusinessGoalsTab />
      </div>

      {/* ── Owner Dashboard Settings Drawer ── */}
      {drawerOpen && (
        <OwnerDashboardDrawer onClose={() => setDrawerOpen(false)} />
      )}
    </div>
  )
}
