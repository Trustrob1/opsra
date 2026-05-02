/**
 * frontend/public/sw.js
 * Opsra service worker — PWA-1
 *
 * Strategy:
 *   Static assets (JS, CSS, fonts, icons) → Cache-first
 *   API calls (/api/v1/*)                 → Network-first (never serve stale data)
 *   Offline fallback                       → /offline.html shown when network unreachable
 *
 * NOTE: In Vite dev mode, this service worker is bypassed.
 * Test installability via: npm run build → npm run preview (or on Render staging).
 */

const CACHE_NAME = 'opsra-static-v1'
const OFFLINE_URL = '/offline.html'

const STATIC_EXTENSIONS = ['.js', '.css', '.woff', '.woff2', '.ttf', '.png', '.svg', '.ico']

// ── Install: pre-cache the offline fallback page ────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.add(OFFLINE_URL))
  )
  self.skipWaiting()
})

// ── Activate: clean up old caches ──────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      )
    )
  )
  self.clients.claim()
})

// ── Fetch: route requests by strategy ──────────────────────────────────────
self.addEventListener('fetch', (event) => {
  const { request } = event
  const url = new URL(request.url)

  // Only handle same-origin and GET requests
  if (request.method !== 'GET') return
  if (url.origin !== location.origin) return

  // API calls → network-first (never cache)
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/webhooks/')) {
    event.respondWith(networkFirst(request))
    return
  }

  // Static assets → cache-first
  const isStatic = STATIC_EXTENSIONS.some((ext) => url.pathname.endsWith(ext))
  if (isStatic) {
    event.respondWith(cacheFirst(request))
    return
  }

  // Navigation requests (HTML pages) → network-first with offline fallback
  if (request.mode === 'navigate') {
    event.respondWith(networkFirstWithOfflineFallback(request))
    return
  }
})

// ── Push notifications ──────────────────────────────────────────────────────
self.addEventListener('push', (event) => {
  if (!event.data) return

  let payload
  try {
    payload = event.data.json()
  } catch {
    payload = { title: 'Opsra', body: event.data.text() }
  }

  const options = {
    body:    payload.body    || 'You have a new notification.',
    icon:    payload.icon    || '/icons/icon-192.png',
    badge:   payload.badge   || '/icons/icon-192.png',
    data:    payload.data    || {},
    tag:     payload.tag     || 'opsra-notification',
    renotify: true,
    actions: payload.actions || [],
  }

  event.waitUntil(
    self.registration.showNotification(payload.title || 'Opsra', options)
  )
})

// ── Notification click: focus or open app ──────────────────────────────────
self.addEventListener('notificationclick', (event) => {
  event.notification.close()

  const targetUrl = event.notification.data?.url || '/'

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      // If a window is already open, focus it
      for (const client of clientList) {
        if (client.url.includes(location.origin) && 'focus' in client) {
          client.postMessage({ type: 'NOTIFICATION_CLICK', data: event.notification.data })
          return client.focus()
        }
      }
      // Otherwise open a new window
      if (clients.openWindow) return clients.openWindow(targetUrl)
    })
  )
})

// ── Strategy helpers ────────────────────────────────────────────────────────

async function cacheFirst(request) {
  const cached = await caches.match(request)
  if (cached) return cached
  try {
    const response = await fetch(request)
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME)
      cache.put(request, response.clone())
    }
    return response
  } catch {
    return new Response('Asset unavailable offline.', { status: 503 })
  }
}

async function networkFirst(request) {
  try {
    return await fetch(request)
  } catch {
    return new Response(
      JSON.stringify({ success: false, error: 'You are offline. Please check your connection.' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } }
    )
  }
}

async function networkFirstWithOfflineFallback(request) {
  try {
    return await fetch(request)
  } catch {
    const cached = await caches.match(OFFLINE_URL)
    return cached || new Response('<h1>You are offline</h1>', { headers: { 'Content-Type': 'text/html' } })
  }
}
