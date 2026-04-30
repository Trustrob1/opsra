/**
 * ErrorBoundary.jsx — Global React error boundary (9E-H / H3)
 *
 * Catches any unhandled render error in the component tree.
 * Shows a clean fallback UI in production.
 * Captures errors to Sentry in production.
 * Shows full stack trace in development only.
 *
 * Usage in App.jsx:
 *   import ErrorBoundary from './components/ErrorBoundary'
 *   // Wrap the root render:
 *   <ErrorBoundary>
 *     <App />
 *   </ErrorBoundary>
 *
 * Note: Must be a class component — React's error boundary API requires
 * componentDidCatch / getDerivedStateFromError, which have no Hook equivalent.
 */
import { Component } from 'react'

const IS_PROD = import.meta.env.PROD === true || import.meta.env.MODE === 'production'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, errorId: null }
  }

  static getDerivedStateFromError() {
    // Update state so the next render shows the fallback UI
    return { hasError: true }
  }

  componentDidCatch(error, info) {
    // Capture to Sentry in production — stack traces never shown in prod UI
    if (IS_PROD && typeof window !== 'undefined' && window.Sentry) {
      const eventId = window.Sentry.captureException(error, {
        contexts: { react: { componentStack: info.componentStack } },
      })
      this.setState({ errorId: eventId })
    }

    // Always log to console for debugging (visible in dev tools, not in UI)
    if (!IS_PROD) {
      console.error('[ErrorBoundary] Uncaught render error:', error)
      console.error('[ErrorBoundary] Component stack:', info.componentStack)
    }
  }

  handleReload() {
    window.location.reload()
  }

  handleReset() {
    this.setState({ hasError: false, errorId: null })
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div style={{
        position: 'fixed', inset: 0,
        background: '#0a1929',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: "'DM Sans', system-ui, sans-serif",
        zIndex: 9999,
      }}>
        <div style={{
          background: '#0d2137',
          border: '1px solid #1e3a4f',
          borderRadius: 16,
          padding: '48px 44px',
          width: 420,
          textAlign: 'center',
          boxShadow: '0 32px 80px rgba(0,0,0,0.5)',
        }}>
          {/* Icon */}
          <div style={{
            width: 56, height: 56,
            background: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            borderRadius: 14,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 26, margin: '0 auto 24px',
          }}>
            ⚠️
          </div>

          <h2 style={{
            fontFamily: "'Syne', system-ui, sans-serif",
            fontWeight: 700, fontSize: 22,
            color: 'white', margin: '0 0 12px',
          }}>
            Something went wrong
          </h2>

          <p style={{ fontSize: 14, color: '#7A9BAD', lineHeight: 1.6, margin: '0 0 28px' }}>
            An unexpected error occurred. Your data is safe — refreshing the page will restore everything.
          </p>

          {/* Error ID for support — only shown in production when Sentry captured it */}
          {IS_PROD && this.state.errorId && (
            <p style={{
              fontSize: 11, color: '#3a5a6a',
              fontFamily: 'monospace', marginBottom: 20,
              background: 'rgba(0,0,0,0.2)', borderRadius: 6,
              padding: '6px 10px', wordBreak: 'break-all',
            }}>
              Error ref: {this.state.errorId}
            </p>
          )}

          {/* Dev-only stack trace hint */}
          {!IS_PROD && (
            <p style={{ fontSize: 12, color: '#EF4444', marginBottom: 20, lineHeight: 1.5 }}>
              Development mode: check the browser console for the full stack trace.
            </p>
          )}

          <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
            <button
              onClick={this.handleReload}
              style={{
                background: '#016b7a', color: 'white',
                border: 'none', borderRadius: 9,
                padding: '12px 24px', fontSize: 14,
                fontWeight: 600, cursor: 'pointer',
                transition: 'background 0.2s',
                fontFamily: "'Syne', system-ui, sans-serif",
              }}
            >
              Refresh page
            </button>

            <button
              onClick={() => this.handleReset()}
              style={{
                background: 'none',
                color: '#7A9BAD',
                border: '1px solid #2a4a5a',
                borderRadius: 9,
                padding: '12px 24px',
                fontSize: 14,
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
            >
              Try again
            </button>
          </div>
        </div>
      </div>
    )
  }
}
