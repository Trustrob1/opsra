/**
 * frontend/src/modules/admin/CommerceSettings.jsx
 * COMM-1 — Commerce Settings admin panel.
 * Pattern 51 (full rewrite on edit). Pattern 50 (admin.service.js calls only).
 */
import { useState, useEffect, useCallback } from 'react'
import { getCommerceSettings, updateCommerceSettings } from '../../services/admin.service'

// ─── Icons ────────────────────────────────────────────────────────────────────

function IconCart() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M2.25 3h1.386c.51 0 .955.343 1.087.835l.383 1.437M7.5 14.25a3 3 0 00-3 3h15.75m-12.75-3h11.218c1.121-2.3 2.1-4.684 2.847-7.17a60.477 60.477 0 00-16.576-1.152l-.307-1.168A1.125 1.125 0 006.114 4.5H2.25" />
    </svg>
  )
}

function IconShopify() {
  return (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M15.337 23.979l7.216-1.561S19.691 7.47 19.67 7.33c-.022-.139-.144-.23-.263-.23-.12 0-2.168-.046-2.168-.046s-1.44-1.395-1.594-1.55v18.475zm-2.484.537L12.11 1.07s-.898-.09-1.196-.09c-.3 0-2.393 0-2.393 0S6.87.254 6.647.031C6.42-.19 5.882 0 5.882 0L4.13 23.59l8.722.926zm-4.7-13.647l-.698 2.068s-.615-.33-1.363-.33c-1.1 0-1.154.69-1.154.862 0 .945 2.462 1.307 2.462 3.52 0 1.74-1.102 2.86-2.592 2.86-1.783 0-2.692-1.11-2.692-1.11l.477-1.574s.937.806 1.726.806c.516 0 .726-.404.726-.7 0-1.228-2.022-1.284-2.022-3.312 0-1.704 1.22-3.354 3.68-3.354.946 0 1.45.27 1.45.27z"/>
    </svg>
  )
}

function IconCheck() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
  )
}

function IconWarning() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
    </svg>
  )
}

function IconInfo() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
    </svg>
  )
}

// ─── Toggle ───────────────────────────────────────────────────────────────────

function Toggle({ checked, onChange, disabled }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => !disabled && onChange(!checked)}
      className={[
        'relative inline-flex h-7 w-12 shrink-0 cursor-pointer rounded-full border-2 border-transparent',
        'transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2',
        checked ? 'bg-teal-600' : 'bg-gray-200',
        disabled ? 'opacity-50 cursor-not-allowed' : '',
      ].join(' ')}
    >
      <span
        className={[
          'pointer-events-none inline-block h-6 w-6 rounded-full bg-white shadow',
          'transform transition duration-200 ease-in-out',
          checked ? 'translate-x-5' : 'translate-x-0',
        ].join(' ')}
      />
    </button>
  )
}

// ─── Toast ────────────────────────────────────────────────────────────────────

function Toast({ toast, onDismiss }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 3500)
    return () => clearTimeout(t)
  }, [onDismiss])

  return (
    <div
      className={[
        'flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg text-sm font-medium',
        'animate-[slide-in_0.2s_ease-out]',
        toast.type === 'success'
          ? 'bg-teal-600 text-white'
          : 'bg-red-500 text-white',
      ].join(' ')}
    >
      {toast.type === 'success' ? <IconCheck /> : <IconWarning />}
      {toast.message}
    </div>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function CommerceSettings() {
  const [loading, setLoading]     = useState(true)
  const [saving, setSaving]       = useState(false)
  const [toast, setToast]         = useState(null)

  // Server state
  const [shopifyConnected, setShopifyConnected] = useState(false)

  // Form state
  const [enabled, setEnabled]                   = useState(false)
  const [checkoutMessage, setCheckoutMessage]   = useState('')

  // Dirty tracking
  const [savedEnabled, setSavedEnabled]               = useState(false)
  const [savedCheckoutMessage, setSavedCheckoutMessage] = useState('')

  const isDirty =
    enabled !== savedEnabled || checkoutMessage !== savedCheckoutMessage

  const showToast = useCallback((message, type = 'success') => {
    setToast({ message, type })
  }, [])

  // ── Load ───────────────────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getCommerceSettings()
      .then(data => {
        if (cancelled) return
        const en  = data?.enabled          ?? false
        const msg = data?.checkout_message ?? 'Here\'s your checkout link:'
        const sc  = data?.shopify_connected ?? false
        setEnabled(en);         setSavedEnabled(en)
        setCheckoutMessage(msg); setSavedCheckoutMessage(msg)
        setShopifyConnected(sc)
      })
      .catch(() => {
        if (!cancelled) showToast('Failed to load commerce settings', 'error')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [showToast])

  // ── Save ───────────────────────────────────────────────────────────────────

  async function handleSave(e) {
    e.preventDefault()
    if (!isDirty || saving) return
    setSaving(true)
    try {
      await updateCommerceSettings({
        enabled,
        checkout_message: checkoutMessage.trim(),
      })
      setSavedEnabled(enabled)
      setSavedCheckoutMessage(checkoutMessage)
      showToast('Commerce settings saved')
    } catch (err) {
      const detail = err?.response?.data?.detail
      const msg =
        (typeof detail === 'object' ? detail?.message : detail)
        ?? 'Failed to save commerce settings'
      showToast(msg, 'error')
      // Revert toggle if backend rejected (e.g. Shopify not connected)
      setEnabled(savedEnabled)
    } finally {
      setSaving(false)
    }
  }

  function handleDiscard() {
    setEnabled(savedEnabled)
    setCheckoutMessage(savedCheckoutMessage)
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="w-8 h-8 rounded-full border-4 border-teal-600 border-t-transparent animate-spin" />
      </div>
    )
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6 pb-16">

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 right-6 z-50">
          <Toast toast={toast} onDismiss={() => setToast(null)} />
        </div>
      )}

      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-teal-50 text-teal-600">
          <IconCart />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Commerce Settings</h2>
          <p className="text-sm text-gray-500">
            WhatsApp-native shopping powered by Shopify
          </p>
        </div>
      </div>

      {/* Shopify not connected warning */}
      {!shopifyConnected && (
        <div className="flex gap-3 p-4 rounded-xl bg-amber-50 border border-amber-200 text-amber-800">
          <span className="shrink-0 mt-0.5 text-amber-500"><IconWarning /></span>
          <div className="text-sm">
            <p className="font-medium">Shopify not connected</p>
            <p className="mt-0.5 text-amber-700">
              Connect your Shopify store on the{' '}
              <span className="font-medium">Shopify tab</span> before enabling
              commerce. Products must be synced before contacts can browse.
            </p>
          </div>
        </div>
      )}

      {/* Form card */}
      <form onSubmit={handleSave} className="bg-white rounded-2xl border border-gray-100 shadow-sm divide-y divide-gray-100">

        {/* Enable toggle */}
        <div className="flex items-start justify-between gap-6 p-6">
          <div>
            <p className="font-medium text-gray-900">Enable commerce</p>
            <p className="mt-0.5 text-sm text-gray-500">
              Allow contacts to browse products and place orders directly in WhatsApp
            </p>
          </div>
          <Toggle
            checked={enabled}
            onChange={setEnabled}
            disabled={!shopifyConnected && !enabled}
          />
        </div>

        {/* Checkout message */}
        <div className="p-6 space-y-2">
          <label className="block font-medium text-gray-900" htmlFor="checkout-msg">
            Checkout message
          </label>
          <p className="text-sm text-gray-500">
            Sent to contacts immediately before their checkout link. Keep it short
            and friendly.
          </p>
          <div className="relative mt-2">
            <textarea
              id="checkout-msg"
              rows={3}
              maxLength={120}
              value={checkoutMessage}
              onChange={e => setCheckoutMessage(e.target.value)}
              placeholder="Here's your checkout link:"
              className={[
                'w-full rounded-xl border px-4 py-3 text-sm text-gray-900 resize-none',
                'placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent',
                'transition-colors',
                enabled ? 'border-gray-200 bg-white' : 'border-gray-100 bg-gray-50',
              ].join(' ')}
              disabled={!enabled}
            />
            <span className="absolute bottom-3 right-3 text-xs text-gray-400 select-none">
              {checkoutMessage.length}/120
            </span>
          </div>

          {/* Preview pill */}
          {enabled && checkoutMessage && (
            <div className="mt-3 rounded-xl bg-gray-50 border border-gray-100 p-3 text-xs text-gray-600 space-y-1">
              <p className="font-medium text-gray-400 uppercase tracking-wide text-[10px]">
                Preview — what contacts will receive
              </p>
              <p>{checkoutMessage}</p>
              <p className="text-teal-600 underline">https://checkout.myshopify.com/…</p>
              <p className="text-gray-400">Reply CANCEL to cancel your order.</p>
            </div>
          )}
        </div>

        {/* Info note */}
        <div className="flex gap-3 p-6 bg-gray-50 rounded-b-2xl">
          <span className="shrink-0 mt-0.5 text-teal-500"><IconInfo /></span>
          <p className="text-sm text-gray-600">
            To add a <span className="font-medium">"Buy Products"</span> option to
            your WhatsApp menu, go to the{' '}
            <span className="font-medium">Triage Config</span> tab and add a menu
            item with the <span className="font-medium">Commerce</span> action type.
          </p>
        </div>
      </form>

      {/* Shopify connection status badge */}
      <div className="flex items-center gap-2 text-sm">
        <span className="text-gray-400"><IconShopify /></span>
        {shopifyConnected ? (
          <span className="flex items-center gap-1.5 text-teal-700 font-medium">
            <span className="inline-block w-2 h-2 rounded-full bg-teal-500 animate-pulse" />
            Shopify connected
          </span>
        ) : (
          <span className="text-gray-400">Shopify not connected</span>
        )}
      </div>

      {/* Action bar */}
      {isDirty && (
        <div className="fixed bottom-0 inset-x-0 z-40 flex items-center justify-between gap-4 px-6 py-4 bg-white border-t border-gray-100 shadow-xl">
          <p className="text-sm text-gray-500">You have unsaved changes</p>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleDiscard}
              disabled={saving}
              className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100 transition-colors disabled:opacity-50"
            >
              Discard
            </button>
            <button
              type="submit"
              form="commerce-form"
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold text-white bg-teal-600 hover:bg-teal-700 transition-colors disabled:opacity-60 shadow-sm"
            >
              {saving ? (
                <>
                  <span className="w-4 h-4 rounded-full border-2 border-white border-t-transparent animate-spin" />
                  Saving…
                </>
              ) : (
                <>
                  <IconCheck />
                  Save changes
                </>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
