/**
 * frontend/src/modules/sites/SectionThumb.jsx
 * SITE-1C-2a — a small wireframe picture of one section in one layout, so staff and builders
 * can see what "Collage" or "Featured" means without guessing.
 */
const INK = '#b7c1cd'
const SOFT = '#dde3ea'
const IMG = '#8fcbd2'
const DARK = '#3f6a72'

const R = (x, y, w, h, fill, r = 2, k) => <rect key={k || `${x}-${y}-${w}-${h}`} x={x} y={y} width={w} height={h} rx={r} fill={fill} />
const lines = (x, y, w, n = 3, gap = 5, fill = INK) => Array.from({ length: n }, (_, i) => R(x, y + i * gap, i === n - 1 ? w * 0.6 : w, 2.4, fill, 1.2, `l${x}-${y}-${i}`))

function shapes(section, variant) {
  switch (`${section}:${variant}`) {
    case 'hero:fullbleed': return [R(3, 4, 74, 44, DARK, 3), ...lines(9, 26, 34, 2, 5, '#fff'), R(9, 38, 18, 5, IMG, 2.5)]
    case 'hero:collage': return [...lines(7, 12, 30, 3, 5), R(7, 34, 18, 5, IMG, 2.5), R(44, 6, 15, 19, IMG, 2), R(61, 6, 15, 19, DARK, 2), R(44, 27, 15, 19, DARK, 2), R(61, 27, 15, 19, IMG, 2)]
    case 'hero:centered': return [R(3, 4, 74, 44, SOFT, 3), R(26, 11, 28, 3, INK, 1.5), R(18, 18, 44, 2.6, INK, 1.3), R(22, 24, 36, 2.6, INK, 1.3), R(29, 33, 22, 6, IMG, 3)]
    case 'items:grid': return [0, 1, 2].flatMap((i) => [R(5 + i * 24, 8, 21, 22, IMG, 2), R(5 + i * 24, 34, 21, 2.4, INK, 1.2), R(5 + i * 24, 39, 12, 2.4, SOFT, 1.2)])
    case 'items:rows': return [0, 1, 2].flatMap((i) => [R(6, 5 + i * 15, 16, 12, IMG, 2), R(26, 7 + i * 15, 34, 2.4, INK, 1.2), R(26, 12 + i * 15, 20, 2.4, SOFT, 1.2), R(64, 8 + i * 15, 10, 5, DARK, 2.5)])
    case 'items:featured': return [R(5, 6, 42, 40, IMG, 3), R(51, 6, 24, 18, IMG, 2), R(51, 28, 24, 18, DARK, 2)]
    case 'about:left': return [R(6, 7, 28, 38, IMG, 3), ...lines(40, 12, 34, 5, 6)]
    case 'about:right': return [R(46, 7, 28, 38, IMG, 3), ...lines(6, 12, 34, 5, 6)]
    case 'about:quote': return [<text key="q" x="40" y="24" textAnchor="middle" fontSize="26" fontWeight="700" fill={IMG} fontFamily="Georgia, serif">&ldquo;</text>, R(14, 28, 52, 2.6, INK, 1.3), R(20, 34, 40, 2.6, INK, 1.3), R(30, 41, 20, 2.4, SOFT, 1.2)]
    case 'reviews:cards': return [0, 1, 2].flatMap((i) => [R(4 + i * 25, 9, 22, 34, SOFT, 3), ...lines(7 + i * 25, 15, 16, 3, 5), R(7 + i * 25, 35, 10, 2.4, IMG, 1.2)])
    case 'reviews:spotlight': return [R(10, 6, 60, 40, SOFT, 4), <text key="q" x="40" y="26" textAnchor="middle" fontSize="22" fontWeight="700" fill={IMG} fontFamily="Georgia, serif">&ldquo;</text>, R(20, 29, 40, 2.6, INK, 1.3), R(27, 35, 26, 2.6, INK, 1.3)]
    case 'reviews:list': return [0, 1, 2].flatMap((i) => [<circle key={`c${i}`} cx="10" cy={13 + i * 13} r="4" fill={IMG} />, R(19, 10 + i * 13, 50, 2.6, INK, 1.3), R(19, 15 + i * 13, 32, 2.4, SOFT, 1.2)])
    case 'categories:tiles': return [0, 1, 2].flatMap((i) => [R(5 + i * 25, 7, 22, 30, IMG, 3), R(8 + i * 25, 41, 16, 2.6, INK, 1.3)])
    case 'categories:chips': return [R(6, 14, 20, 8, IMG, 4), R(30, 14, 24, 8, SOFT, 4), R(58, 14, 16, 8, SOFT, 4), R(6, 28, 26, 8, SOFT, 4), R(36, 28, 18, 8, SOFT, 4)]
    case 'order:steps': return [<line key="ln" x1="16" y1="24" x2="64" y2="24" stroke={SOFT} strokeWidth="2" />, ...[0, 1, 2].flatMap((i) => [<circle key={`s${i}`} cx={16 + i * 24} cy="24" r="8" fill={i === 0 ? DARK : IMG} />, R(9 + i * 24, 38, 14, 2.4, INK, 1.2)])]
    default: return [R(6, 6, 68, 40, SOFT, 3)]
  }
}

export default function SectionThumb({ section, variant, width = 80, active = false }) {
  return (
    <svg viewBox="0 0 80 52" width={width} height={(width * 52) / 80} role="img" aria-label={`${section} ${variant || ''} layout`}
      style={{ display: 'block', background: '#fff', border: `1px solid ${active ? '#0d7f8a' : '#e1e6ec'}`, borderRadius: 6 }}>
      {shapes(section, variant)}
    </svg>
  )
}
