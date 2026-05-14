/**
 * IOSInstallBanner.jsx
 * PWA-iOS: iOS Safari "Add to Home Screen" install guide.
 *
 * iOS Safari does not support the beforeinstallprompt event that Android
 * Chrome uses. Users must manually tap Share → "Add to Home Screen".
 * This banner detects when the app is running in iOS Safari (not already
 * installed) and shows a one-time guide explaining how to install.
 *
 * Detection logic:
 *   - iOS Safari: navigator.userAgent contains iPhone/iPad/iPod AND
 *     does NOT contain Chrome/CriOS/FxiOS (those have their own prompts)
 *   - Not already installed: window.navigator.standalone !== true
 *   - Not previously dismissed: localStorage 'opsra_ios_install_dismissed'
 *     not set (persists across sessions — banner never shows again once dismissed)
 *
 * Pattern 51: full rewrite required for any future edit.
 */

import { useState, useEffect } from 'react'
import { ds } from '../utils/ds'

function isIosSafari() {
  const ua = window.navigator.userAgent
  const isIos = /iPhone|iPad|iPod/.test(ua)
  // Exclude Chrome for iOS (CriOS), Firefox for iOS (FxiOS), Edge (EdgiOS)
  const isThirdPartyBrowser = /CriOS|FxiOS|EdgiOS|OPiOS/.test(ua)
  return isIos && !isThirdPartyBrowser
}

function isInStandaloneMode() {
  return (
    window.navigator.standalone === true ||
    window.matchMedia('(display-mode: standalone)').matches
  )
}

const DISMISSED_KEY = 'opsra_ios_install_dismissed'

export default function IOSInstallBanner() {
  const [visible, setVisible] = useState(false)
  const [step, setStep]       = useState(1) // 1 = main, 2 = detail guide

  useEffect(() => {
    // Only show on iOS Safari, not already installed, not previously dismissed
    if (
      isIosSafari() &&
      !isInStandaloneMode() &&
      !localStorage.getItem(DISMISSED_KEY)
    ) {
      // Small delay so it doesn't flash on initial load
      const t = setTimeout(() => setVisible(true), 2000)
      return () => clearTimeout(t)
    }
  }, [])

  const handleDismiss = () => {
    localStorage.setItem(DISMISSED_KEY, '1')
    setVisible(false)
  }

  if (!visible) return null

  return (
    <div
      style={{
        position:        'fixed',
        bottom:          0,
        left:            0,
        right:           0,
        zIndex:          9999,
        background:      '#fff',
        borderTop:       `3px solid ${ds.teal}`,
        boxShadow:       '0 -4px 24px rgba(0,0,0,0.13)',
        padding:         '18px 20px 28px',   // extra bottom padding for iOS home bar
        fontFamily:      ds.fontDm,
      }}
    >
      {step === 1 && (
        <>
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <img
                src="/icons/icon-192.png"
                alt="Opsra"
                style={{ width: 44, height: 44, borderRadius: 10, flexShrink: 0 }}
              />
              <div>
                <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: ds.dark }}>
                  Install Opsra
                </div>
                <div style={{ fontSize: 12.5, color: ds.gray, marginTop: 2 }}>
                  Add to your Home Screen for the best experience
                </div>
              </div>
            </div>
            <button
              onClick={handleDismiss}
              aria-label="Dismiss"
              style={{
                background:  'none',
                border:      'none',
                cursor:      'pointer',
                color:       ds.gray,
                fontSize:    20,
                lineHeight:  1,
                padding:     '2px 4px',
                minWidth:    36,
                minHeight:   44,
                display:     'flex',
                alignItems:  'center',
                justifyContent: 'center',
                flexShrink:  0,
              }}
            >
              ✕
            </button>
          </div>

          {/* Benefits */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
            {[
              { icon: '⚡', text: 'Faster loads' },
              { icon: '🔔', text: 'Push alerts' },
              { icon: '📱', text: 'Full screen' },
            ].map(({ icon, text }) => (
              <div
                key={text}
                style={{
                  flex:           1,
                  background:     ds.light,
                  borderRadius:   10,
                  padding:        '10px 6px',
                  textAlign:      'center',
                  fontSize:       11.5,
                  color:          ds.dark,
                  fontWeight:     500,
                }}
              >
                <div style={{ fontSize: 20, marginBottom: 4 }}>{icon}</div>
                {text}
              </div>
            ))}
          </div>

          {/* CTA */}
          <button
            onClick={() => setStep(2)}
            style={{
              width:        '100%',
              background:   ds.teal,
              color:        '#fff',
              border:       'none',
              borderRadius: 12,
              padding:      '14px 0',
              fontSize:     15,
              fontWeight:   700,
              fontFamily:   ds.fontSyne,
              cursor:       'pointer',
              minHeight:    48,
            }}
          >
            Show me how →
          </button>
        </>
      )}

      {step === 2 && (
        <>
          {/* Step-by-step guide */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <div style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 15, color: ds.dark }}>
              How to install
            </div>
            <button
              onClick={handleDismiss}
              aria-label="Dismiss"
              style={{
                background:  'none',
                border:      'none',
                cursor:      'pointer',
                color:       ds.gray,
                fontSize:    20,
                lineHeight:  1,
                padding:     '2px 4px',
                minWidth:    36,
                minHeight:   44,
                display:     'flex',
                alignItems:  'center',
              }}
            >
              ✕
            </button>
          </div>

          {[
            {
              n: '1',
              icon: '⬆️',
              text: 'Tap the Share button at the bottom of Safari',
              sub:  'It looks like a box with an arrow pointing up',
            },
            {
              n: '2',
              icon: '➕',
              text: 'Scroll down and tap "Add to Home Screen"',
              sub:  'You may need to scroll the share sheet to find it',
            },
            {
              n: '3',
              icon: '✅',
              text: 'Tap "Add" in the top right corner',
              sub:  'Opsra will appear on your Home Screen like any other app',
            },
          ].map(({ n, icon, text, sub }) => (
            <div
              key={n}
              style={{
                display:      'flex',
                gap:          14,
                marginBottom: 14,
                alignItems:   'flex-start',
              }}
            >
              <div
                style={{
                  width:           32,
                  height:          32,
                  borderRadius:    '50%',
                  background:      ds.teal,
                  color:           '#fff',
                  fontFamily:      ds.fontSyne,
                  fontWeight:      700,
                  fontSize:        14,
                  display:         'flex',
                  alignItems:      'center',
                  justifyContent:  'center',
                  flexShrink:      0,
                  marginTop:       2,
                }}
              >
                {n}
              </div>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: ds.dark, marginBottom: 2 }}>
                  {icon} {text}
                </div>
                <div style={{ fontSize: 12, color: ds.gray, lineHeight: 1.5 }}>{sub}</div>
              </div>
            </div>
          ))}

          <button
            onClick={handleDismiss}
            style={{
              width:        '100%',
              background:   ds.light,
              color:        ds.gray,
              border:       `1.5px solid ${ds.border}`,
              borderRadius: 12,
              padding:      '13px 0',
              fontSize:     14,
              fontWeight:   600,
              fontFamily:   ds.fontSyne,
              cursor:       'pointer',
              minHeight:    48,
              marginTop:    4,
            }}
          >
            Got it — dismiss
          </button>
        </>
      )}
    </div>
  )
}
