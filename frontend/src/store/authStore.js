/**
 * Auth store — Zustand in-memory only.
 *
 * SECURITY (Technical Spec §11.1):
 *   - Token stored in React/Zustand memory only.
 *   - NEVER written to localStorage or sessionStorage.
 *   - Cleared on logout or 401 response.
 *   - org_id is derived server-side from JWT — never stored here for API use.
 */
import { create } from 'zustand'

const useAuthStore = create((set, get) => ({
  /** JWT access token — null when unauthenticated */
  token: null,
  /** Decoded user profile returned by POST /api/v1/auth/login */
  user: null,

  /** Call after successful login */
  setAuth: (token, user) => set({ token, user }),

  /** Call on logout or 401 */
  clearAuth: () => set({ token: null, user: null }),

  /** Convenience getter — used outside React components (e.g. in services) */
  getToken: () => get().token,
}))

export default useAuthStore
