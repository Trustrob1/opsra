/**
 * Design-system constants — mirrors the demo CSS variables exactly.
 * Import { ds } and use ds.teal, ds.fontSyne, etc. throughout UI files.
 * Never hardcode colour hex values in components — always use these.
 */
export const ds = {
  // Colours
  teal:      '#028090',
  tealLight: '#00A896',
  tealDark:  '#015F6B',
  mint:      '#E0F4F6',
  dark:      '#0D1B2A',
  dark2:     '#112233',
  accent:    '#F4A261',
  green:     '#27AE60',
  red:       '#E05252',
  purple:    '#7B2FBE',
  gray:      '#6B7C8E',
  light:     '#F5FAFB',
  white:     '#FFFFFF',
  border:    '#D6E8EC',

  // Typography
  fontSyne: "'Syne', sans-serif",
  fontDm:   "'DM Sans', sans-serif",

  // Shadows
  cardShadow:  '0 2px 12px rgba(2,128,144,0.05)',
  hoverShadow: '0 3px 12px rgba(2,128,144,0.15)',
  modalShadow: '0 24px 60px rgba(0,0,0,0.25)',

  // Radii
  radius: { sm: 8, md: 9, lg: 12, xl: 14, xxl: 16 },

  // Z-index layers
  z: { sidebar: 50, topbar: 100, modal: 500 },
}

/** Score badge appearance — matches demo tag-hot / tag-warm / tag-cold classes */
export const SCORE_STYLE = {
  hot:      { bg: '#FFE8E8', color: '#C0392B', label: '🔥 Hot' },
  warm:     { bg: '#FFF3E0', color: '#E07B3A', label: '☀️ Warm' },
  cold:     { bg: '#EAF0F2', color: '#6B7C8E', label: '❄️ Cold' },
  unscored: { bg: '#F0F0F0', color: '#9E9E9E', label: '— Unscored' },
}

/** Pipeline stages in declaration order */
export const STAGES = [
  { key: 'new',           label: 'New',           dot: '#6B7C8E' },
  { key: 'contacted',     label: 'Contacted',     dot: '#028090' },
  { key: 'meeting_done',  label: 'Demo Done',     dot: '#7B2FBE' },
  { key: 'proposal_sent', label: 'Proposal Sent', dot: '#F4A261' },
  { key: 'converted',     label: 'Converted',     dot: '#27AE60' },
  { key: 'lost',          label: 'Lost',          dot: '#E05252' },
  { key: 'not_ready',     label: 'Not Ready',     dot: '#D4AC0D' },
]

/** Stage badge colours (used on LeadProfile) */
export const STAGE_STYLE = {
  new:           { bg: '#EAF0F2', color: '#6B7C8E' },
  contacted:     { bg: '#E0F4F6', color: '#015F6B' },
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

export const TIMELINE_ICONS = {
  lead_created:  '🌱',
  stage_changed: '🔄',
  message_sent:  '💬',
  call_logged:   '📞',
  score_updated: '🤖',
  task_created:  '✅',
  note_added:    '📝',
}

export const BRANCHES_OPTIONS = ['1', '2-3', '4-10', '10+']
