/**
 * frontend/src/modules/sites/LookTick.jsx
 * SITE-1C-1b/1c — the small tick badge on a selected look tile, colour, font or option.
 */
import { Check } from 'lucide-react'
import { TEAL } from './lookKit'

export default function LookTick() {
  return (
    <span style={{ position: 'absolute', top: -7, right: -7, width: 20, height: 20, borderRadius: '50%', background: TEAL, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <Check size={13} strokeWidth={3.5} aria-hidden="true" />
    </span>
  )
}
