/**
 * frontend/src/pages/chatSignupLogic.js - WEB-ONLY-1b
 * Plain functions behind the /start/chat sign-up page (so they can be tested without a browser).
 */

export const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s.]{2,}$/

export const naira = (n) => `₦${Number(n || 0).toLocaleString('en-NG')}`

/** The first problem with the details form, or '' when it is fine. */
export function validateDetails(form) {
  const f = form || {}
  const digits = String(f.phone || '').replace(/\D/g, '')
  if (String(f.business_name || '').trim().length < 2) return 'Please enter your business name.'
  if (String(f.full_name || '').trim().length < 2) return 'Please enter your name.'
  if (!EMAIL_RE.test(String(f.email || '').trim())) return 'Please enter a valid email address.'
  if (digits.length < 9 || digits.length > 15) return 'Enter your WhatsApp number, for example 0803 123 4567.'
  if (!f.accept_terms) return 'Please accept the terms to continue.'
  return ''
}

/** The first problem with the code and password step, or '' when it is fine. */
export function validateCode(code, password) {
  if (String(code || '').replace(/\D/g, '').length !== 6) return 'Enter the 6-digit code from your email.'
  if (String(password || '').length < 8) return 'Choose a password of at least 8 characters.'
  return ''
}

/** What the visitor gets for free. Comes from the Superadmin setting, never a fixed number. */
export function creditLine(info) {
  const c = Number(info?.starter_credit_ngn || 0)
  return c > 0 ? `Start free with ${naira(c)} of chat credit. No card, no time limit.` : 'Start free. No card needed.'
}

/** What happens when the free credit is used up. Empty until the plan has a price in Superadmin. */
export function planLine(plan) {
  const monthly = Number(plan?.monthly_ngn || 0)
  if (monthly <= 0) return 'When your credit runs out, you can top up whenever you like.'
  const extras = []
  const credit = Number(plan?.included_credit_ngn || 0)
  if (credit > 0) extras.push(`${naira(credit)} of chat credit`)
  if (Number(plan?.ai_messages || 0) > 0) extras.push(`${plan.ai_messages} AI answers`)
  const inc = extras.length ? `, which includes ${extras.join(' and ')} every month` : ''
  return `When your credit runs out, choose the ${plan?.label || 'Chioma'} plan at ${naira(monthly)} a month${inc}, or top up as you go.`
}
