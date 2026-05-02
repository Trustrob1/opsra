/**
 * public/sw.js
 * Opsra PWA Service Worker — PWA-1
 *
 * Handles:
 *   - push events     → show system notification via showNotification()
 *   - notificationclick → focus existing tab or open new one
 *   - install/activate → skip waiting, claim clients immediately
 *
 * Payload format (from push_notifications.py):
 *   { title, body, data: { url?, ...custom } }
 */

const APP_ORIGIN = self.location.origin

// ---------------------------------------------------------------------------
// Install — skip waiting so new SW activates immediately
// ---------------------------------------------------------------------------
self.addEventListener('install', (event) => {
  self.skipWaiting()
})

// ---------------------------------------------------------------------------
// Activate — claim all clients so this SW controls open tabs right away
// ---------------------------------------------------------------------------
self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

// ---------------------------------------------------------------------------
// Push — receive payload and show system notification
// ---------------------------------------------------------------------------
self.addEventListener('push', (event) => {
  let payload = {}

  try {
    payload = event.data ? event.data.json() : {}
  } catch (e) {
    payload = { title: 'Opsra', body: event.data ? event.data.text() : 'You have a new notification' }
  }

  const title   = payload.title || 'Opsra'
  const options = {
    body:    payload.body  || '',
    icon:    '/icons/icon-192.png',
    badge:   '/icons/icon-192.png',
    data:    payload.data  || {},
    vibrate: [200, 100, 200],
    requireInteraction: false,
    tag:     payload.data?.tag || 'opsra-notification',  // replaces duplicate notifications
  }

  event.waitUntil(
    self.registration.showNotification(title, options)
  )
})

// ---------------------------------------------------------------------------
// Notification click — focus existing tab or open app
// ---------------------------------------------------------------------------
self.addEventListener('notificationclick', (event) => {
  event.notification.close()

  const targetUrl = event.notification.data?.url || APP_ORIGIN

  event.waitUntil(
    self.clients
      .matchAll({ type: 'window', includeUncontrolled: true })
      .then((clientList) => {
        // If there's already an open tab, focus it and navigate
        for (const client of clientList) {
          if (client.url.startsWith(APP_ORIGIN) && 'focus' in client) {
            client.focus()
            if (targetUrl !== APP_ORIGIN) {
              client.navigate(targetUrl)
            }
            return
          }
        }
        // No open tab — open a new one
        if (self.clients.openWindow) {
          return self.clients.openWindow(targetUrl)
        }
      })
  )
})
