// frontend/src/services/superadmin.service.js
// SA-2A — SD7: SUPERADMIN_SECRET removed from frontend.
// Auth is now backend-proxied: POST /superadmin/auth/login → JWT stored in memory only.
// Pattern 50: axios + _h() only, never fetch.
// Pattern 11: JWT in Zustand memory only, never localStorage/sessionStorage.
import axios from "axios";

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// ---------------------------------------------------------------------------
// In-memory JWT store — never touches localStorage or sessionStorage (Pattern 11)
// ---------------------------------------------------------------------------
let _saToken = null;

export function setSuperadminToken(token) {
  _saToken = token;
}
export function getSuperadminToken() {
  return _saToken;
}
export function clearSuperadminToken() {
  _saToken = null;
}
export function isSuperadminLoggedIn() {
  return !!_saToken;
}

function _h() {
  return { Authorization: `Bearer ${_saToken}` };
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export async function superadminLogin(secret) {
  const res = await axios.post(`${BASE}/api/v1/superadmin/auth/login`, { secret });
  const token = res.data?.data?.token;
  if (token) setSuperadminToken(token);
  return res.data;
}

// ---------------------------------------------------------------------------
// Org provisioning (previously used X-Superadmin-Secret — now uses JWT)
// ---------------------------------------------------------------------------

export async function createOrganisation(payload) {
  const res = await axios.post(
    `${BASE}/api/v1/superadmin/organisations`,
    payload,
    { headers: _h() }
  );
  return res.data;
}

// ---------------------------------------------------------------------------
// Health routes — SA-2A
// ---------------------------------------------------------------------------

export async function getHealthSummary(params = {}) {
  const res = await axios.get(`${BASE}/api/v1/superadmin/health/summary`, {
    headers: _h(),
    params,
  });
  return res.data;
}

export async function getHealthIntegrations() {
  const res = await axios.get(`${BASE}/api/v1/superadmin/health/integrations`, {
    headers: _h(),
  });
  return res.data;
}

export async function getHealthErrors(params = {}) {
  const res = await axios.get(`${BASE}/api/v1/superadmin/health/errors`, {
    headers: _h(),
    params,
  });
  return res.data;
}

export async function getHealthJobs(params = {}) {
  const res = await axios.get(`${BASE}/api/v1/superadmin/health/jobs`, {
    headers: _h(),
    params,
  });
  return res.data;
}

export async function getHealthClaudeUsage(params = {}) {
  const res = await axios.get(`${BASE}/api/v1/superadmin/health/claude-usage`, {
    headers: _h(),
    params,
  });
  return res.data;
}

export async function getHealthWebhooks(params = {}) {
  const res = await axios.get(`${BASE}/api/v1/superadmin/health/webhooks`, {
    headers: _h(),
    params,
  });
  return res.data;
}

export async function getHealthOrgs(params = {}) {
  const res = await axios.get(`${BASE}/api/v1/superadmin/health/orgs`, {
    headers: _h(),
    params,
  });
  return res.data;
}

// ---------------------------------------------------------------------------
// Credits — CREDITS-3
// ---------------------------------------------------------------------------

const CR = `${BASE}/api/v1/superadmin/credits`;

export async function getCreditOrgs() {
  const res = await axios.get(`${CR}/orgs`, { headers: _h() });
  return res.data.data;
}

export async function getCreditMargin(days = 30) {
  const res = await axios.get(`${CR}/margin`, { headers: _h(), params: { days } });
  return res.data.data;
}

export async function getCreditReconcile() {
  const res = await axios.get(`${CR}/reconcile`, { headers: _h() });
  return res.data.data;
}

export async function setCreditMetering(orgId, enabled) {
  const res = await axios.patch(`${CR}/orgs/${orgId}/wallet`, { metering_enabled: enabled }, { headers: _h() });
  return res.data.data;
}

export async function adjustCredit(orgId, payload) {
  const res = await axios.post(`${CR}/orgs/${orgId}/adjust`, payload, { headers: _h() });
  return res.data.data;
}

// ---------------------------------------------------------------------------
// Account plans — ACCOUNT-PLANS AP-3 (routes from AP-1)
// ---------------------------------------------------------------------------

const AP = `${BASE}/api/v1/superadmin/plans`;

export async function getPlanOrgs() {
  const res = await axios.get(`${AP}/orgs`, { headers: _h() });
  return res.data.data;
}

export async function grantOrgPlan(orgId, payload) {
  const res = await axios.post(`${AP}/orgs/${orgId}/grant`, payload, { headers: _h() });
  return res.data.data;
}

export async function setOrgPlanStatus(orgId, payload) {
  const res = await axios.post(`${AP}/orgs/${orgId}/status`, payload, { headers: _h() });
  return res.data.data;
}

export async function setOrgEnforced(orgId, enforced) {
  const res = await axios.patch(`${AP}/orgs/${orgId}/enforce`, { enforced }, { headers: _h() });
  return res.data.data;
}


// ---------------------------------------------------------------------------
// Opsra Pricing — ACCOUNT-PLANS AP-8 (plan prices, ticks, seat price, discount codes). Superadmin JWT only.
// ---------------------------------------------------------------------------
const PR = `${BASE}/api/v1/superadmin/pricing`;
const _d = (p) => p.then((r) => r.data?.data ?? r.data);

export const getPricingContext = () => _d(axios.get(`${PR}/context`, { headers: _h() }));
export const getPricingSettings = () => _d(axios.get(`${PR}/settings`, { headers: _h() }));
export const savePricingSettings = (payload) => _d(axios.patch(`${PR}/settings`, payload, { headers: _h() }));
export const getPricingCatalog = () => _d(axios.get(`${PR}/catalog`, { headers: _h() }));
export const listPricingCodes = () => _d(axios.get(`${PR}/discount-codes`, { headers: _h() }));
export const createPricingCode = (payload) => _d(axios.post(`${PR}/discount-codes`, payload, { headers: _h() }));
export const updatePricingCode = (id, payload) => _d(axios.patch(`${PR}/discount-codes/${id}`, payload, { headers: _h() }));
export const deletePricingCode = (id) => _d(axios.delete(`${PR}/discount-codes/${id}`, { headers: _h() }));

// WA-AUTO-5 - switches for the public WhatsApp sign-up
export async function getWaSignupSettings() {
  const res = await axios.get(`${BASE}/api/v1/superadmin/wa-signup/settings`, { headers: _h() });
  return res.data.data;
}

export async function saveWaSignupSettings(payload) {
  const res = await axios.put(`${BASE}/api/v1/superadmin/wa-signup/settings`, payload, { headers: _h() });
  return res.data.data;
}
