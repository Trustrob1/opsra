/**
 * Auth store — Zustand in-memory only.
 *
 * SECURITY (Technical Spec §11.1):
 *   - Token stored in React/Zustand memory only.
 *   - NEVER written to localStorage or sessionStorage.
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

const useAuthStore = create((set, get) => ({
  /** JWT access token — null when unauthenticated */
  token: null,

  /**
   * Full user profile returned by GET /api/v1/auth/me after login.
   * Shape (Phase 9+):
   *   { id, org_id, email, full_name, is_active, is_out_of_office,
   *     notification_prefs, roles: { template, permissions: { ... } } }
   *
   * roles.template values: owner | ops_manager | sales_agent |
   *   customer_success | support_agent | finance | read_only
   */
  user: null,

  /** Call after successful login — user should be the full auth/me response */
  setAuth: (token, user) => set({ token, user }),

  /** Call on logout or 401 */
  clearAuth: () => set({ token: null, user: null }),

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

export default useAuthStore
