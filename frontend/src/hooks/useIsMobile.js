/**
 * frontend/src/hooks/useIsMobile.js
 *
 * Returns true when the viewport is narrower than `breakpoint` (default 768px).
 * Used across all PWA-1 mobile-responsive layouts.
 *
 * Usage:
 *   const isMobile = useIsMobile()
 *   // or with custom breakpoint:
 *   const isNarrow = useIsMobile(480)
 */
import { useState, useEffect } from 'react'

export function useIsMobile(breakpoint = 768) {
  const [isMobile, setIsMobile] = useState(
    typeof window !== 'undefined' ? window.innerWidth < breakpoint : false
  )

  useEffect(() => {
    const handler = () => setIsMobile(window.innerWidth < breakpoint)
    const mq = window.matchMedia(`(max-width: ${breakpoint - 1}px)`)

    // Use matchMedia listener when available (more efficient than resize)
    if (mq.addEventListener) {
      mq.addEventListener('change', handler)
      return () => mq.removeEventListener('change', handler)
    } else {
      // Fallback for older Safari
      window.addEventListener('resize', handler, { passive: true })
      return () => window.removeEventListener('resize', handler)
    }
  }, [breakpoint])

  return isMobile
}
