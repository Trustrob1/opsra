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
    if (!('Notification' in window) || !('serviceWorker' in navigator) || !VAPID_PUBLIC_KEY) return

    const permission = await Notification.requestPermission()
    if (permission !== 'granted') return

    const registration = await navigator.serviceWorker.ready
    if (!registration.pushManager) return

    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly:      true,
      applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
    })

    await fetch('/api/v1/notifications/push-token', {
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

// ── React root ──────────────────────────────────────────────────────────────
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
