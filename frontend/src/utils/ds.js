/**
 * Design-system constants — mirrors the demo CSS variables exactly.
 * Import { ds } and use ds.teal, ds.fontSyne, etc. throughout UI files.
 * Never hardcode colour hex values in components — always use these.
 */
export const ds = {
  // Colours
  teal:      '#2467E3',
  tealLight: '#4C86EE',
  tealDark:  '#1F54B8',
  mint:      '#E4EDFD',
  dark:      '#1B1F28',
  dark2:     '#1B2029',
  accent:    '#F4A261',
  green:     '#27AE60',
  red:       '#E05252',
  purple:    '#5E1BB8',
  gray:      '#5B6270',
  light:     '#F6F7FA',
  white:     '#FFFFFF',
  border:    '#E1E5EC',

  // Typography
  fontSyne: "'Hanken Grotesk', system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif",
  fontDm:   "'Hanken Grotesk', system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif",

  // Shadows
  cardShadow:  '0 2px 12px rgba(36,103,227,0.05)',
  hoverShadow: '0 3px 12px rgba(36,103,227,0.15)',
  modalShadow: '0 24px 60px rgba(0,0,0,0.25)',

  // Radii
  radius: { sm: 8, md: 9, lg: 12, xl: 14, xxl: 16 },

  // Z-index layers
  z: { sidebar: 50, topbar: 100, modal: 500, mobileDrawer: 200 },

  // PWA-1: responsive breakpoint (mobile-first)
  breakpoint: '768px',
}

/** Score badge appearance — matches demo tag-hot / tag-warm / tag-cold classes */
export const SCORE_STYLE = {
  hot:      { bg: '#FFE8E8', color: '#C0392B', label: 'Hot' },
  warm:     { bg: '#FFF3E0', color: '#E07B3A', label: 'Warm' },
  cold:     { bg: '#EAF0F2', color: '#6B7C8E', label: 'Cold' },
  unscored: { bg: '#F0F0F0', color: '#9E9E9E', label: '— Unscored' },
}

/** Pipeline stages in declaration order */
export const STAGES = [
  { key: 'new',           label: 'New',           dot: '#6B7C8E' },
  { key: 'contacted',     label: 'Contacted',     dot: '#2467E3' },
  { key: 'meeting_done',  label: 'Demo Done',     dot: '#7B2FBE' },
  { key: 'proposal_sent', label: 'Proposal Sent', dot: '#F4A261' },
  { key: 'converted',     label: 'Converted',     dot: '#27AE60' },
  { key: 'lost',          label: 'Lost',          dot: '#E05252' },
  { key: 'not_ready',     label: 'Not Ready',     dot: '#D4AC0D' },
]

/** Stage badge colours (used on LeadProfile) */
export const STAGE_STYLE = {
  new:           { bg: '#EAF0F2', color: '#6B7C8E' },
  contacted:     { bg: '#E4EDFD', color: '#1F54B8' },
  meeting_done:  { bg: '#EDE0FF', color: '#5B1E9C' },
  proposal_sent: { bg: '#FFF3E0', color: '#C05A00' },
  converted:     { bg: '#E8F8EE', color: '#1A7A40' },
  lost:          { bg: '#FFE8E8', color: '#C0392B' },
  not_ready:     { bg: '#FFF9E0', color: '#A07C00' },
}

export const SOURCE_LABELS = {
  facebook_ad:       'Facebook Ad',
  instagram_ad:      'Instagram Ad',
  landing_page:      'Landing Page',
  whatsapp_inbound:  'WhatsApp Inbound',
  manual_phone:      'Manual (Phone)',
  manual_referral:   'Manual (Referral)',
  import:            'Import',
}

export const SOURCE_SHORT = {
  facebook_ad:       'FB Ad',
  instagram_ad:      'IG Ad',
  landing_page:      'Landing',
  whatsapp_inbound:  'WhatsApp',
  manual_phone:      'Phone',
  manual_referral:   'Referral',
  import:            'Import',
}

export const LOST_REASON_LABELS = {
  not_ready:     'Not Ready',
  price:         'Price',
  competitor:    'Competitor',
  wrong_size:    'Wrong Size',
  wrong_contact: 'Wrong Contact',
  other:         'Other',
}

/** PAY-LINK-1 — payment_links.status badge appearance */
export const PAYMENT_STATUS_STYLE = {
  pending:   { bg: '#FFF3E0', color: '#C05A00', label: 'Pending' },
  paid:      { bg: '#E8F8EE', color: '#1A7A40', label: 'Paid' },
  failed:    { bg: '#FFE8E8', color: '#C0392B', label: 'Failed' },
  expired:   { bg: '#EAF0F2', color: '#6B7C8E', label: 'Expired' },
  cancelled: { bg: '#EAF0F2', color: '#6B7C8E', label: 'Cancelled' },
}

export const TIMELINE_ICONS = {
  lead_created:  '',
  stage_changed: '',
  message_sent:  '',
  call_logged:   '',
  score_updated: '',
  task_created:  '',
  note_added:    '',
}

export const BRANCHES_OPTIONS = ['1', '2-3', '4-10', '10+']
