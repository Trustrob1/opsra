/**
 * frontend/src/catalog/storefront/useStorefrontCart.js
 * STORE-4: the Storefront cart. It is the web chat shop's own cart and Paystack checkout (same endpoints, same
 * rules): the visitor gets a chat session when they first add something, the cart lives on that session, prices
 * are re-read on the server at every add and at checkout. Nothing here is trusted for a price.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import * as chat from '../../services/webchat.service'
import {
  EMPTY_CART, normaliseCart, cartErrorText, askedForContact, isSessionExpired, readToken, writeToken, clearToken, MAX_QTY,
} from './storefrontCart'

export default function useStorefrontCart({ shop, source, api = chat }) {
  const key = (shop && shop.key) || null
  const [cart, setCart] = useState(EMPTY_CART)
  const [hasContact, setHasContact] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const tokenRef = useRef(null)

  const forget = useCallback(() => { tokenRef.current = null; if (key) clearToken(key) }, [key])

  // Show the number on the cart button for someone coming back in the same tab. No session is started here.
  useEffect(() => {
    if (!key) return undefined
    const saved = readToken(key)
    if (!saved) return undefined
    let alive = true
    api.getChatCart(key, saved)
      .then((d) => {
        if (!alive) return null
        tokenRef.current = saved
        setCart(normaliseCart(d))
        return api.resumeChat(key, saved)
      })
      .then((snap) => { if (alive && snap) setHasContact(!!snap.has_contact) })
      .catch(() => { if (alive) clearToken(key) })
    return () => { alive = false }
  }, [key, api])

  const ensureToken = useCallback(async () => {
    if (tokenRef.current) return tokenRef.current
    const saved = readToken(key)
    if (saved) {
      try {
        const snap = await api.resumeChat(key, saved)
        tokenRef.current = saved
        setHasContact(!!(snap && snap.has_contact))
        return saved
      } catch { clearToken(key) }
    }
    const snap = await api.startChat(key, { source: source || undefined })
    tokenRef.current = snap.token
    writeToken(key, snap.token)
    setHasContact(!!snap.has_contact)
    return snap.token
  }, [key, source, api])

  // One call with a session; if the session has ended, start a fresh one and try once more.
  const call = useCallback(async (fn) => {
    let token = await ensureToken()
    try { return await fn(token) } catch (err) {
      if (!isSessionExpired(err)) throw err
      forget()
      token = await ensureToken()
      return fn(token)
    }
  }, [ensureToken, forget])

  const guarded = useCallback(async (fn) => {
    setBusy(true); setError('')
    try { return await fn() } catch (err) { setError(cartErrorText(err)); return null } finally { setBusy(false) }
  }, [])

  const add = useCallback(({ item, variantId, qty = 1 }) => guarded(async () => {
    const d = await call((t) => api.changeChatCart(key, t, { action: 'add', product_id: String(item.id), variant_id: variantId || undefined, qty }))
    setCart(normaliseCart(d))
    return true
  }).then((r) => !!r), [guarded, call, api, key])

  const remove = useCallback((line) => guarded(async () => {
    const d = await call((t) => api.changeChatCart(key, t, { action: 'remove', product_id: line.pid, variant_id: line.vid || undefined }))
    setCart(normaliseCart(d))
    return true
  }).then((r) => !!r), [guarded, call, api, key])

  // The server can add and remove, so a change of quantity is "add the difference" or "remove, then add the new amount".
  const setQty = useCallback((line, qty) => guarded(async () => {
    const want = Math.max(0, Math.min(MAX_QTY, qty))
    if (want === line.qty) return true
    const base = { product_id: line.pid, variant_id: line.vid || undefined }
    let d
    if (want > line.qty) {
      d = await call((t) => api.changeChatCart(key, t, { action: 'add', ...base, qty: want - line.qty }))
    } else {
      d = await call((t) => api.changeChatCart(key, t, { action: 'remove', ...base }))
      if (want > 0) d = await call((t) => api.changeChatCart(key, t, { action: 'add', ...base, qty: want }))
    }
    setCart(normaliseCart(d))
    return true
  }).then((r) => !!r), [guarded, call, api, key])

  const submitContact = useCallback((payload) => guarded(async () => {
    await call((t) => api.sendContact(key, t, payload))
    setHasContact(true)
    return true
  }).then((r) => !!r), [guarded, call, api, key])

  /** {ok:true, url} (go and pay), {ok:true, human:true} (a person will finish the order) or {ok:false, askContact?, message}. */
  const checkout = useCallback(async () => {
    setBusy(true); setError('')
    try {
      const d = await call((t) => api.chatCheckout(key, t))
      setCart(normaliseCart(d && d.cart))
      return d && d.checkout_url ? { ok: true, url: d.checkout_url } : { ok: true, human: true }
    } catch (err) {
      const message = cartErrorText(err)
      setError(message)
      return { ok: false, askContact: askedForContact(err), message }
    } finally { setBusy(false) }
  }, [call, api, key])

  return { enabled: !!key, cart, hasContact, busy, error, clearError: () => setError(''), add, remove, setQty, submitContact, checkout }
}
