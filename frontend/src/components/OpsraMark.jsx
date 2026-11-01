/**
 * The Opsra logo mark: white speech bubble on Opsra blue.
 * Same artwork as the /business site logo and the app icons.
 */
export default function OpsraMark({ size = 32, ...rest }) {
  return (
    <svg width={size} height={size} viewBox="0 0 34 34" fill="none" aria-hidden="true" style={{ flexShrink: 0, display: 'block' }} {...rest}>
      <rect x="1" y="1" width="32" height="32" rx="10" fill="#2467E3" />
      <path
        d="M17 8c5 0 9 3.4 9 7.8 0 4.4-4 7.8-9 7.8-1 0-2-.1-2.9-.4L10 25l1-3.4C9.4 20.2 8 18.1 8 15.8 8 11.4 12 8 17 8z"
        stroke="#fff"
        strokeWidth="2.2"
        strokeLinejoin="round"
      />
    </svg>
  )
}
