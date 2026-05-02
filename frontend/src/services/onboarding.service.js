/**
 * frontend/src/services/onboarding.service.js
 * Onboarding checklist API calls — Pattern 50: axios + _h() only.
 */
import axios from 'axios'
import useAuthStore from '../store/authStore'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const _h = () => ({ Authorization: `Bearer ${useAuthStore.getState().token}` })

export async function getChecklist() {
  const r = await axios.get(`${BASE}/api/v1/onboarding/checklist`, { headers: _h() })
  return r.data.data
}

export async function getGoLiveStatus() {
  const r = await axios.get(`${BASE}/api/v1/onboarding/go-live-status`, { headers: _h() })
  return r.data.data
}

export async function activateOrg() {
  const r = await axios.post(`${BASE}/api/v1/onboarding/activate`, {}, { headers: _h() })
  return r.data.data
}