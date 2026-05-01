// frontend/src/services/superadmin.service.js
// SA-2A — SD7: SUPERADMIN_SECRET removed from frontend.
// Auth is now backend-proxied: POST /superadmin/auth/login → JWT stored in memory only.
// Pattern 50: axios + _h() only, never fetch.
// Pattern 11: JWT in Zustand memory only, never localStorage/sessionStorage.

import axios from "axios";

const BASE = "/api/v1";

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
  const res = await axios.post(`${BASE}/superadmin/auth/login`, { secret });
  const token = res.data?.data?.token;
  if (token) setSuperadminToken(token);
  return res.data;
}

// ---------------------------------------------------------------------------
// Org provisioning (previously used X-Superadmin-Secret — now uses JWT)
// ---------------------------------------------------------------------------

export async function createOrganisation(payload) {
  const res = await axios.post(
    `${BASE}/superadmin/organisations`,
    payload,
    { headers: _h() }
  );
  return res.data;
}

// ---------------------------------------------------------------------------
// Health routes — SA-2A
// ---------------------------------------------------------------------------

export async function getHealthSummary(params = {}) {
  const res = await axios.get(`${BASE}/superadmin/health/summary`, {
    headers: _h(),
    params,
  });
  return res.data;
}

export async function getHealthIntegrations() {
  const res = await axios.get(`${BASE}/superadmin/health/integrations`, {
    headers: _h(),
  });
  return res.data;
}

export async function getHealthErrors(params = {}) {
  const res = await axios.get(`${BASE}/superadmin/health/errors`, {
    headers: _h(),
    params,
  });
  return res.data;
}

export async function getHealthJobs(params = {}) {
  const res = await axios.get(`${BASE}/superadmin/health/jobs`, {
    headers: _h(),
    params,
  });
  return res.data;
}

export async function getHealthClaudeUsage(params = {}) {
  const res = await axios.get(`${BASE}/superadmin/health/claude-usage`, {
    headers: _h(),
    params,
  });
  return res.data;
}

export async function getHealthWebhooks(params = {}) {
  const res = await axios.get(`${BASE}/superadmin/health/webhooks`, {
    headers: _h(),
    params,
  });
  return res.data;
}

export async function getHealthOrgs(params = {}) {
  const res = await axios.get(`${BASE}/superadmin/health/orgs`, {
    headers: _h(),
    params,
  });
  return res.data;
}
