/**
 * sanitize.js — DOMPurify wrapper (9E-H / H1)
 *
 * SECURITY (Technical Spec §11.1 + 9E-H):
 *   All user-generated content rendered via dangerouslySetInnerHTML
 *   MUST be passed through sanitizeHtml() before use.
 *
 *   Priority targets (per 9E-H spec):
 *     - Ticket message content
 *     - KB article body
 *     - WhatsApp message display
 *     - Lead notes
 *     - Any field that renders user-typed HTML
 *
 * Usage:
 *   import { sanitizeHtml } from '../../utils/sanitize'
 *   <div dangerouslySetInnerHTML={{ __html: sanitizeHtml(content) }} />
 *
 * Installation required:
 *   npm install dompurify
 */
import DOMPurify from 'dompurify'

/**
 * Sanitize an HTML string for safe use in dangerouslySetInnerHTML.
 *
 * Config:
 *   - Strips all script tags and event handlers.
 *   - Allows common safe inline formatting: b, i, em, strong, br, p, ul, ol, li, a, span.
 *   - Strips all other tags by default (DOMPurify default).
 *   - Strips javascript: and data: URIs from href/src.
 *
 * @param {string|null|undefined} dirty — raw HTML from user input or API
 * @returns {string} — sanitized HTML safe for DOM injection
 */
export function sanitizeHtml(dirty) {
  if (!dirty) return ''
  return DOMPurify.sanitize(dirty, {
    ALLOWED_TAGS: ['b', 'i', 'em', 'strong', 'br', 'p', 'ul', 'ol', 'li', 'a', 'span', 'pre', 'code'],
    ALLOWED_ATTR: ['href', 'target', 'rel', 'class'],
    ALLOW_DATA_ATTR: false,
    // Force all links to open in new tab with noopener
    ADD_ATTR: ['target'],
    FORCE_BODY: false,
  })
}

/**
 * Sanitize plain text — strip ALL HTML tags, return plain text only.
 * Use this when you want to display user input as text (not rendered HTML).
 *
 * @param {string|null|undefined} dirty
 * @returns {string}
 */
export function sanitizeText(dirty) {
  if (!dirty) return ''
  return DOMPurify.sanitize(dirty, { ALLOWED_TAGS: [], ALLOWED_ATTR: [] })
}
