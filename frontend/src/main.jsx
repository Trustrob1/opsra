/**
 * frontend/src/main.jsx
 *
 * PWA-1 additions:
 *   - Service worker registration (sw.js)
 *   - Push notification subscription after login
 *     (permission prompt + VAPID subscription → POST /api/v1/notifications/push-token)
 *
 * NOTE: The SW only activates in production builds.
 * In Vite dev mode (npm run dev), the registration call is made but the
 * navigator.serviceWorker.register() is a no-op because Vite serves from memory.
 * Test the full PWA flow with: npm run build → npm run preview
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

// ── Service worker registration ─────────────────────────────────────────────
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js', { scope: '/' })
      .then((registration) => {
        console.log('[SW] Registered, scope:', registration.scope)
      })
      .catch((err) => {
        console.warn('[SW] Registration failed:', err)
      })
  })
}

// ── Push notification subscription helper ───────────────────────────────────
// Called from App.jsx after successful login.
// Exposed on window so App.jsx can invoke it without importing here.

const VAPID_PUBLIC_KEY = import.meta.env.VITE_VAPID_PUBLIC_KEY
const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

/**
 * urlBase64ToUint8Array — converts VAPID public key from base64 to Uint8Array.
 * Required by pushManager.subscribe().
 */
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = atob(base64)
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)))
}

/**
 * subscribeToPush — requests notification permission, subscribes to push,
 * and POSTs the subscription to the backend.
 *
 * Called after a successful login in App.jsx.
 * Fails silently — push is non-critical, never blocks login flow.
 */
window.opsraSubscribeToPush = async function subscribeToPush(apiToken) {
  try {
    console.log('[Push] Token received, length:', apiToken?.length, 'starts:', apiToken?.substring(0, 20))
    if (!('Notification' in window) || !('serviceWorker' in navigator) || !VAPID_PUBLIC_KEY) return

    const permission = await Notification.requestPermission()
    if (permission !== 'granted') return

    const registration = await navigator.serviceWorker.ready
    if (!registration.pushManager) return

    // iOS 16.4+ supports push only when installed as a PWA (standalone mode).
    // In Safari browser (not installed), pushManager.subscribe() throws.
    // Guard: skip subscription if not in standalone mode on iOS.
    const isIos = /iPhone|iPad|iPod/.test(navigator.userAgent)
    const isStandalone = window.navigator.standalone === true ||
      window.matchMedia('(display-mode: standalone)').matches
    if (isIos && !isStandalone) return

    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly:      true,
      applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
    })

    await fetch(`${BASE}/api/v1/notifications/push-token`, {
      method:  'POST',
      headers: {
        'Content-Type':  'application/json',
        'Authorization': `Bearer ${apiToken}`,
      },
      body: JSON.stringify({
        token:    JSON.stringify(subscription),
        platform: 'web',
      }),
    })
  } catch (err) {
    // Non-critical — push failure must never interrupt login
    console.warn('[Push] Subscription failed (non-critical):', err)
  }
}

// ── In-app notification sound ───────────────────────────────────────────────
// Web Audio API generates a two-tone chime — no audio file required.
// AudioContext is pre-warmed on first pointer interaction to satisfy iOS autoplay policy.
// All failures are swallowed silently — sound is non-critical.

let _audioCtx = null

function _ensureAudioCtx() {
  try {
    if (!_audioCtx) {
      const Ctor = window.AudioContext || window.webkitAudioContext
      if (Ctor) _audioCtx = new Ctor()
    }
    if (_audioCtx?.state === 'suspended') _audioCtx.resume()
  } catch (_) {}
  return _audioCtx
}

// Warm up AudioContext on first tap/click — required by iOS autoplay policy
document.addEventListener('pointerdown', () => { _ensureAudioCtx() }, { once: true })

function playNotificationSound() {
  try {
    const ctx = _ensureAudioCtx()
    if (!ctx) return
    const now = ctx.currentTime
    // Two-tone descending chime: 880 Hz → 660 Hz
    ;[[0, 880], [0.18, 660]].forEach(([t, freq]) => {
      const osc  = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.type = 'sine'
      osc.frequency.value = freq
      gain.gain.setValueAtTime(0, now + t)
      gain.gain.linearRampToValueAtTime(0.25, now + t + 0.02)
      gain.gain.exponentialRampToValueAtTime(0.001, now + t + 0.28)
      osc.start(now + t)
      osc.stop(now + t + 0.3)
    })
  } catch (_) {}
}

// Listen for SW → client message (foreground push arrives, OS suppresses banner)
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.addEventListener('message', (event) => {
    if (event.data?.type === 'PLAY_NOTIFICATION_SOUND') {
      // If AudioContext exists but is suspended (common on desktop before
      // any user interaction), resume it first then play.
      // If it doesn't exist yet, _ensureAudioCtx() inside playNotificationSound
      // will attempt creation — may silently fail on iOS without a gesture,
      // but succeeds on desktop and Android PWA (push counts as interaction).
      if (_audioCtx && _audioCtx.state === 'suspended') {
        _audioCtx.resume().then(() => playNotificationSound()).catch(() => playNotificationSound())
      } else {
        playNotificationSound()
      }
    }
  })
}

// Poll for new unread notifications every 30 s — play sound when count rises.
// Covers the case where push is not set up or the tab regains focus after being idle.
let _lastUnreadCount = null

async function _pollUnread() {
  try {
    const { default: useAuthStore } = await import('./store/authStore.js')
    const token = useAuthStore.getState()?.token
    if (!token) { _lastUnreadCount = null; return }

    const res = await fetch(`${BASE}/api/v1/notifications?page=1&page_size=1`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) return
    const json = await res.json()
    const current = json?.data?.unread_count ?? 0

    if (_lastUnreadCount !== null && current > _lastUnreadCount) {
      playNotificationSound()
    }
    _lastUnreadCount = current
  } catch (_) {}
}

// Seed _lastUnreadCount immediately so the first interval tick
// doesn't false-trigger sound for pre-existing unread notifications.
// 2s delay gives the Zustand auth store time to rehydrate from localStorage.
setTimeout(async () => {
  await _pollUnread()
  setInterval(_pollUnread, 30_000)
}, 2000)

// ── React root ──────────────────────────────────────────────────────────────
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
