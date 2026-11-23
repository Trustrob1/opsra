/**
 * frontend/src/catalog/fetchRetry.js
 * LOAD-RETRY-1: the public catalog must never sit on a spinner when a visitor's connection drops. A request that does not answer
 * in time is given up on and tried again (twice), and the page shows a "taking longer" line with a retry button.
 * Pure helpers (the sleep and the clock are passed in) so they can be tested without a browser.
 */
export const REQUEST_TIMEOUT_MS = 12000
export const RETRY_DELAYS_MS = [600, 1800]
export const SLOW_AFTER_MS = 8000

/** Retry only what a second try can fix: no answer, a timeout, or a server error. A 404 or any other 4xx is final. */
export function shouldRetry(err) {
  if (!err) return false
  if (typeof err.status === 'number') return err.status >= 500 || err.status === 429
  return true
}

/** Runs fn(); on a retryable failure waits and runs it again, up to delays.length more times. Throws the last error. */
export async function withRetry(fn, { delays = RETRY_DELAYS_MS, sleep = (ms) => new Promise((r) => setTimeout(r, ms)) } = {}) {
  let last
  for (let i = 0; i <= delays.length; i++) {
    try {
      return await fn(i)
    } catch (err) {
      last = err
      if (!shouldRetry(err) || i === delays.length) throw err
      await sleep(delays[i])
    }
  }
  throw last
}

/** fetch() that gives up after timeoutMs (the error has no status, so it counts as retryable). */
export async function fetchWithTimeout(url, opts = {}, timeoutMs = REQUEST_TIMEOUT_MS, fetchImpl = (typeof fetch !== 'undefined' ? fetch : null)) {
  const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null
  const timer = setTimeout(() => ctl && ctl.abort(), timeoutMs)
  try {
    return await fetchImpl(url, { ...opts, ...(ctl ? { signal: ctl.signal } : {}) })
  } finally {
    clearTimeout(timer)
  }
}
