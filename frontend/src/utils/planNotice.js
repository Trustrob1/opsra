/**
 * frontend/src/utils/planNotice.js
 * ACCOUNT-PLANS AP-6 - one place that notices "your plan doesn't include this" from the API (HTTP 403, code PLAN_REQUIRED).
 *
 * Many services build their own axios instance, so this wraps axios.create once (import this file FIRST in main.jsx)
 * and adds a response interceptor to every instance. The error is passed on unchanged, so each screen still handles
 * it as before; this only also raises the 'opsra:plan-required' event that <PlanNotice /> shows.
 */
import axios from 'axios'

export const PLAN_EVENT = 'opsra:plan-required'
export const PLAN_FALLBACK = "Your plan doesn't include this. Open Billing to see the plans."

export function planMessage(error) {
  const res = error && error.response
  if (!res || res.status !== 403) return null
  const d = res.data && (res.data.detail || res.data.error || res.data)
  const code = d && typeof d === 'object' ? d.code : null
  if (code !== 'PLAN_REQUIRED') return null
  return (d && d.message) || PLAN_FALLBACK
}

function watch(instance) {
  if (!instance || !instance.interceptors || instance.__planWatched) return instance
  instance.__planWatched = true
  instance.interceptors.response.use(
    (r) => r,
    (error) => {
      try {
        const message = planMessage(error)
        if (message) window.dispatchEvent(new CustomEvent(PLAN_EVENT, { detail: { message } }))
      } catch (_) { /* never let a notice break a request */ }
      return Promise.reject(error)
    },
  )
  return instance
}

if (!axios.__planPatched) {
  axios.__planPatched = true
  const create = axios.create.bind(axios)
  axios.create = (...args) => watch(create(...args))
  watch(axios)
}

export default watch
