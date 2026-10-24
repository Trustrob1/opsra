/**
 * frontend/src/services/knowledge.service.js
 * WA-AUTO-4a - what the bot knows: files and typed answers.
 */
import api from './api'

export const listKnowledge = () => api.get('/api/v1/knowledge/sources').then((r) => r.data.data)
export const addKnowledgeFile = (file, title) => {
  const form = new FormData()
  form.append('file', file)
  if (title) form.append('title', title)
  return api.post('/api/v1/knowledge/sources/file', form).then((r) => r.data.data)
}
export const addKnowledgeText = (title, content) => api.post('/api/v1/knowledge/sources/text', { title, content }).then((r) => r.data.data)
export const addKnowledgeWebsite = (url) => api.post('/api/v1/knowledge/sources/url', { url }).then((r) => r.data.data)
export const addKnowledgeGdoc = (url) => api.post('/api/v1/knowledge/sources/gdoc', { url }).then((r) => r.data.data)
export const getKnowledgeSource = (id) => api.get(`/api/v1/knowledge/sources/${id}`).then((r) => r.data.data)
export const activateKnowledge = (id) => api.post(`/api/v1/knowledge/sources/${id}/activate`).then((r) => r.data.data)
export const removeKnowledge = (id) => api.delete(`/api/v1/knowledge/sources/${id}`).then((r) => r.data.data)

export const knowledgeError = (e, fallback = 'Something went wrong. Please try again.') => {
  const d = e?.response?.data?.detail
  if (typeof d === 'string') return d
  if (d?.message) return d.message
  if (Array.isArray(d) && d[0]?.msg) return d[0].msg
  return fallback
}
