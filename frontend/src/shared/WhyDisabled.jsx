/**
 * frontend/src/shared/WhyDisabled.jsx
 * HINT-1 — one short line next to a greyed-out button saying what is still missing ("Choose the size to save").
 * Pass the reason, or nothing when the button can be pressed (or is greyed only because it is working).
 */
export default function WhyDisabled({ reason, style }) {
  if (!reason) return null
  return (
    <p role="status" aria-live="polite"
      style={{ margin: '6px 0 0', fontSize: 13, lineHeight: 1.4, color: '#6B7280', ...style }}>
      {reason}
    </p>
  )
}
