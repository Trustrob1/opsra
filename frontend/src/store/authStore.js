/**
 * Auth store — Zustand, persisted for "stay signed in" (AUTH-SESSION-1).
 *
 * SECURITY (Technical Spec §11.1 — knowingly relaxed, see helpers below):
 *   - Token lives in Zustand and is mirrored to localStorage (keep me signed
 *     in) or sessionStorage (tab only) so a refresh/restart does not sign out.
 *   - Cleared on logout or 401 response.
 *   - org_id is derived server-side from JWT — never stored here for API use.
 *
 * Phase 9 (TEMP-1 fix):
 *   The login flow now calls GET /api/v1/auth/me immediately after login and
 *   stores the full user object — including roles.template and permissions.
 *   Three new read-only helpers allow components to check roles without
 *   duplicating the roles.template lookup logic everywhere.
 */
import { create } from 'zustand'

// ── Session persistence helpers ───────────────────────────────────────────
// AUTH-SESSION-1 (deliberate deviation from Spec §11.1, accepted by the owner):
// "Keep me signed in" (default ON at login) stores the session in localStorage
// so the user stays signed in across browser restarts, like everyday
// productivity apps. When it is switched off the session lives in
// sessionStorage and ends when the tab/window closes.
// The refresh token is kept too, so the 1-hour access token renews silently
// (see services/api.js). Future hardening: move the refresh token into an
// HttpOnly cookie once the app and API share a domain.
const _SESSION_KEY = 'opsra_session'
const KEEP_IDLE_MS = 30 * 24 * 60 * 60 * 1000   // signed out after 30 days unused
const KEEP_MAX_MS  = 90 * 24 * 60 * 60 * 1000   // and always after 90 days
const TAB_IDLE_MS  = 12 * 60 * 60 * 1000        // "keep" off: 12 hours idle
const TOUCH_EVERY  = 60 * 1000                  // throttle activity writes

function _expired(p, now = Date.now()) {
  if (!p) return true
  const last = p.last ?? p.start ?? now
  if (p.keep) return (now - last > KEEP_IDLE_MS) || (now - (p.start ?? now) > KEEP_MAX_MS)
  return now - last > TAB_IDLE_MS
}

function _readFrom(store) {
  try {
    const raw = store.getItem(_SESSION_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

function _loadSession() {
  let p = null
  try { p = _readFrom(localStorage) } catch {}
  if (!p) { try { p = _readFrom(sessionStorage) } catch {} }
  if (!p || !p.token) return null
  if (_expired(p)) { _clearSession(); return null }
  return p
}

function _saveSession(p) {
  try {
    const json = JSON.stringify(p)
    if (p.keep) {
      localStorage.setItem(_SESSION_KEY, json)
      try { sessionStorage.removeItem(_SESSION_KEY) } catch {}
    } else {
      sessionStorage.setItem(_SESSION_KEY, json)
      try { localStorage.removeItem(_SESSION_KEY) } catch {}
    }
  } catch {}
}

function _clearSession() {
  try { sessionStorage.removeItem(_SESSION_KEY) } catch {}
  try { localStorage.removeItem(_SESSION_KEY) } catch {}
}

const _persisted = _loadSession()
let _meta = {
  refresh: _persisted?.refresh ?? null,
  keep:    _persisted?.keep ?? false,
  start:   _persisted?.start ?? null,
  last:    _persisted?.last ?? null,
}

const useAuthStore = create((set, get) => ({
  /** JWT access token — null when unauthenticated */
  token: _persisted?.token ?? null,
  user: _persisted?.user ?? null,
  /** Call after successful login — user should be the full auth/me response */
  setAuth: (token, user, refresh, keep) => {
    const now = Date.now()
    const fresh = refresh !== undefined || keep !== undefined   // a real sign-in
    _meta = {
      refresh: refresh !== undefined ? refresh : _meta.refresh,
      keep:    keep !== undefined ? !!keep : _meta.keep,
      start:   fresh && keep !== undefined ? now : (_meta.start ?? now),
      last:    now,
    }
    _saveSession({ token, user, ..._meta })
    set({ token, user })
  },
  /** Call on logout or 401 */
  clearAuth: () => {
    _clearSession()
    _meta = { refresh: null, keep: false, start: null, last: null }
    set({ token: null, user: null })
  },
  /** Stored refresh token (null if none) — used by services/api.js */
  getRefreshToken: () => _meta.refresh,
  /** Whether this sign-in is the long-lived "keep me signed in" kind */
  getKeep: () => _meta.keep,
  /**
   * Record user activity (throttled). Writes the timestamp only — no re-render.
   */
  touchActivity: () => {
    const now = Date.now()
    if (!get().token || (_meta.last && now - _meta.last < TOUCH_EVERY)) return
    _meta.last = now
    const p = _readFrom(_meta.keep ? localStorage : sessionStorage)
    if (p) { p.last = now; _saveSession(p) }
  },
  /**
   * True when the session has been unused too long (or is past its hard cap).
   * Timestamp-based: setTimeout cannot hold 30 days and sleeps with the laptop.
   */
  isSessionExpired: () => get().token ? _expired(_meta) : false,
  /**
   * Another tab may have renewed or ended the session. Adopt the stored copy.
   * Returns the token now in effect (null if signed out).
   */
  syncFromStorage: () => {
    const p = _loadSession()
    if (!p) { if (get().token) set({ token: null, user: null }); return null }
    _meta = { refresh: p.refresh ?? null, keep: !!p.keep, start: p.start ?? null, last: p.last ?? null }
    if (p.token !== get().token) set({ token: p.token, user: p.user })
    return p.token
  },
  /** Convenience getter — used outside React components (e.g. in services) */
  getToken: () => get().token,

  // ── Role helpers (Phase 9 — TEMP-1 fix) ─────────────────────────────────

  /**
   * Returns the current user's role template string, or null if not loaded yet.
   * e.g. "owner" | "ops_manager" | "sales_agent" | null
   */
  getRoleTemplate: () => get().user?.roles?.template ?? null,

  /**
   * Returns true if the current user has the given permission key.
   * Owner template always returns true. is_admin flag also grants all perms.
   * Falls back to false if roles are not yet loaded (e.g. pre-auth/me).
   *
   * @param {string} key — e.g. "view_revenue", "manage_tasks", "manage_users"
   */
  hasPermission: (key) => {
    const user = get().user
    if (!user?.roles) return false
    const { template, permissions } = user.roles
    if (template === 'owner')              return true
    if (permissions?.is_admin === true)    return true
    return permissions?.[key] === true
  },

  /**
   * Returns true if the current user is a manager (can access team views,
   * reassign tasks, see team-wide data).
   *
   * Manager = owner OR ops_manager template, OR manage_tasks permission granted.
   * Matches the backend _is_manager() check in task_service.py (Pattern 37).
   */
  isManager: () => {
    const user = get().user
    if (!user?.roles) return false
    const { template, permissions } = user.roles
    return (
      template === 'owner' ||
      template === 'ops_manager' ||
      permissions?.manage_tasks === true
    )
  },
}))

// Keep tabs in step: renewed tokens, sign-out in one tab signs out all.
try {
  window.addEventListener('storage', (e) => {
    if (e.key === _SESSION_KEY) useAuthStore.getState().syncFromStorage()
  })
} catch {}

export default useAuthStore
