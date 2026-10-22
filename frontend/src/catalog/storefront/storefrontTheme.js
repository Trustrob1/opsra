/**
 * frontend/src/catalog/storefront/storefrontTheme.js
 * STORE-2/3: colours, font and small hooks shared by the Storefront pages.
 */
import { useEffect } from 'react'

export const INK = '#14181B'
export const MUTED = '#5C6166'
export const LINE = '#E6E4DF'
export const TINTS = ['#E4E9E7', '#EAE6DE', '#E3E6EC', '#ECE4E4']
export const FONT = "'Manrope', system-ui, sans-serif"

export function placeholder(i, size = 16) {
  return `repeating-linear-gradient(135deg, ${TINTS[i % TINTS.length]} 0 ${size / 2}px, #F4F2EE ${size / 2}px ${size}px)`
}

export function useManrope() {
  useEffect(() => {
    if (document.getElementById('sf-manrope')) return
    const link = document.createElement('link')
    link.id = 'sf-manrope'
    link.rel = 'stylesheet'
    link.href = 'https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap'
    document.head.appendChild(link)
  }, [])
}
