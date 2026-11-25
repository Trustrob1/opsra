/**
 * frontend/src/services/invoices.service.js
 * INV-2 — quotes and invoices for a business's own customers (backend: routers/invoices.py).
 * Uses the shared api instance (JWT). org_id is never sent; the server takes it from the token.
 */
import api from './api'

const d = (res) => res.data?.data

export const apiError = (e, fallback = 'Something went wrong. Please try again.') =>
  e?.response?.data?.detail?.code === 'PLAN_REQUIRED'
    ? 'Quotes and invoices are not included in your plan. Open Billing to see the plans.'
    : (e?.response?.data?.error?.message ?? e?.response?.data?.detail?.message
      ?? (typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : null) ?? fallback)

export const isPlanBlocked = (e) => e?.response?.data?.detail?.code === 'PLAN_REQUIRED'

// Settings
export const getInvoiceSettings  = () => api.get('/api/v1/invoices/settings').then(d)
export const saveInvoiceSettings = (body) => api.put('/api/v1/invoices/settings', body).then(d)
export const uploadInvoiceLogo   = (file) => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/api/v1/invoices/settings/logo', form).then(d)
}
export const removeInvoiceLogo   = () => api.delete('/api/v1/invoices/settings/logo').then(d)

// Pickers + summary
export const getInvoiceSummary   = () => api.get('/api/v1/invoices/summary').then(d)
export const pickProducts        = (q) => api.get('/api/v1/invoices/products', { params: q ? { q } : {} }).then(d)
export const pickContacts        = (q) => api.get('/api/v1/invoices/contacts', { params: q ? { q } : {} }).then(d)

// Documents
export const listDocs   = (params = {}) => api.get('/api/v1/invoices', { params }).then(d)
export const getDoc     = (id) => api.get(`/api/v1/invoices/${id}`).then(d)
export const createDoc  = (body) => api.post('/api/v1/invoices', body).then(d)
export const updateDoc  = (id, body) => api.patch(`/api/v1/invoices/${id}`, body).then(d)
export const deleteDoc  = (id) => api.delete(`/api/v1/invoices/${id}`).then(d)
export const issueDoc   = (id) => api.post(`/api/v1/invoices/${id}/issue`).then(d)
export const voidDoc    = (id, reason) => api.post(`/api/v1/invoices/${id}/void`, { reason }).then(d)
export const acceptQuote  = (id) => api.post(`/api/v1/invoices/${id}/accept`).then(d)
export const declineQuote = (id) => api.post(`/api/v1/invoices/${id}/decline`).then(d)
export const convertQuote = (id) => api.post(`/api/v1/invoices/${id}/convert`).then(d)
// INV-3: send to the customer
export const getSendOptions = (id) => api.get(`/api/v1/invoices/${id}/send-options`).then(d)
export const sendDoc = (id, channel, email) => api.post(`/api/v1/invoices/${id}/send`, { channel, ...(email ? { email } : {}) }).then(d)

// INV-4: payments and receipts
export const recordPayment = (id, body) => api.post(`/api/v1/invoices/${id}/payments`, body).then(d)
export const listReceipts = (params = {}) => api.get('/api/v1/receipts', { params }).then(d)
export const createReceipt = (body) => api.post('/api/v1/receipts', body).then(d)
export const voidReceipt = (id, reason) => api.post(`/api/v1/receipts/${id}/void`, { reason }).then(d)
export const getReceiptSendOptions = (id) => api.get(`/api/v1/receipts/${id}/send-options`).then(d)
export const sendReceipt = (id, channel, email) => api.post(`/api/v1/receipts/${id}/send`, { channel, ...(email ? { email } : {}) }).then(d)
export const downloadReceiptPdf = (id, filename) => savePdf(`/api/v1/receipts/${id}/pdf`, filename)

// INV-SALES-2: regions (Data Sources) and the part-paid card on Sales Record
export const getInvoiceRegions = () => api.get('/api/v1/invoices/regions').then(d)
export const getPartPaid = (params) => api.get('/api/v1/invoices/part-paid', { params }).then(d)

// INV-5: report, receipts CSV, AI lines from the chat
export const getInvoiceReport = (start, end) => api.get('/api/v1/invoices/report', { params: { start, end } }).then(d)
export const downloadReceiptsCsv = (start, end) => savePdf(`/api/v1/invoices/report/receipts.csv?start=${start}&end=${end}`)
export const aiDraftLines = (leadId) => api.post('/api/v1/invoices/ai-draft', { lead_id: leadId }).then(d)

// STOCK-2: mark goods on a paid invoice as delivered (lines: [{ item_id, quantity }])
export const deliverInvoice = (id, lines, note) => api.post(`/api/v1/invoices/${id}/deliver`, { lines, ...(note ? { note } : {}) }).then(d)

/** Fetch the PDF with the login token and save it (a plain link can't carry the token). */
export const downloadDocPdf = (id, filename) => savePdf(`/api/v1/invoices/${id}/pdf`, filename)

async function savePdf(path, filename) {
  const res = await api.get(path, { responseType: 'blob' })
  const url = URL.createObjectURL(res.data)
  const name = filename || (/filename="([^"]+)"/.exec(res.headers?.['content-disposition'] || '')?.[1]) || 'document.pdf'
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10000)
}
