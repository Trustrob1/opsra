// frontend/src/modules/superadmin/HealthDashboard.jsx
// SA-2B — Superadmin Health Dashboard.
// 7 panels: summary, integrations, errors, jobs, Claude usage, webhooks, orgs.
// Filter bar: org selector + time range. Auto-refresh every 2min on summary + integrations.
// Pattern 26: display:none not conditional render for tab-like panels.
// Pattern 51: full rewrite.
// Pattern 11: no browser storage — superadmin JWT in memory via superadmin.service.js.

import { useState, useEffect, useCallback, useRef } from "react";
import {
  isSuperadminLoggedIn,
  superadminLogin,
  clearSuperadminToken,
  getHealthSummary,
  getHealthIntegrations,
  getHealthErrors,
  getHealthJobs,
  getHealthClaudeUsage,
  getHealthWebhooks,
  getHealthOrgs,
} from "../../services/superadmin.service";
import { ds } from "../../utils/ds";

// ─── Constants ────────────────────────────────────────────────────────────────

const TIME_RANGES = [
  { label: "24h",  value: "24h"  },
  { label: "7d",   value: "7d"   },
  { label: "30d",  value: "30d"  },
  { label: "MTD",  value: "mtd"  },
];

const PANELS = [
  { id: "summary",      label: "Summary"       },
  { id: "integrations", label: "Integrations"  },
  { id: "errors",       label: "Errors"        },
  { id: "jobs",         label: "Jobs"          },
  { id: "claude",       label: "Claude Usage"  },
  { id: "webhooks",     label: "Webhooks"      },
  { id: "orgs",         label: "Org Health"    },
];

function sinceFromRange(range) {
  const now = new Date();
  if (range === "24h")  { now.setHours(now.getHours() - 24);       return now.toISOString(); }
  if (range === "7d")   { now.setDate(now.getDate() - 7);           return now.toISOString(); }
  if (range === "30d")  { now.setDate(now.getDate() - 30);          return now.toISOString(); }
  if (range === "mtd")  { now.setDate(1); now.setHours(0,0,0,0);   return now.toISOString(); }
  return now.toISOString();
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const card = {
  background: ds.dark2,
  border: "1px solid #1e3a4f",
  borderRadius: 12,
  padding: "20px 22px",
  marginBottom: 16,
};

const sectionTitle = {
  fontFamily: ds.fontSyne,
  fontWeight: 700,
  fontSize: 14,
  color: "white",
  margin: "0 0 14px",
  letterSpacing: "0.3px",
};

const labelStyle = {
  fontSize: 11,
  fontWeight: 600,
  color: "#3a5a6a",
  textTransform: "uppercase",
  letterSpacing: "1px",
};

const valueStyle = {
  fontFamily: ds.fontSyne,
  fontWeight: 700,
  fontSize: 26,
  color: "white",
  lineHeight: 1.1,
};

const rowStyle = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "10px 14px",
  borderRadius: 8,
  marginBottom: 6,
  background: "rgba(255,255,255,0.03)",
  border: "1px solid #1a2f3f",
  fontSize: 12,
  color: "#A0BDC8",
};

const badge = (color) => ({
  display: "inline-flex",
  alignItems: "center",
  padding: "2px 8px",
  borderRadius: 20,
  fontSize: 11,
  fontWeight: 600,
  background: color + "22",
  color: color,
  border: `1px solid ${color}44`,
});

const STATUS_COLORS = {
  ok:           "#22d3a5",
  error:        "#ef4444",
  unconfigured: "#f59e0b",
  passed:       "#22d3a5",
  partial:      "#f59e0b",
  failed:       "#ef4444",
  skipped:      "#6b7280",
};

// ─── Login Gate ───────────────────────────────────────────────────────────────

function LoginGate({ onAuthed }) {
  const [secret, setSecret] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleLogin = async () => {
    if (!secret.trim()) return;
    setLoading(true);
    setError(null);
    try {
      await superadminLogin(secret.trim());
      setSecret("");
      onAuthed();
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Invalid secret.");
    }
    setLoading(false);
  };

  return (
    <div style={{ padding: 32 }}>
      <div style={{ maxWidth: 380, ...card }}>
        <h2 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, color: "white", margin: "0 0 6px" }}>
          Superadmin Access
        </h2>
        <p style={{ fontSize: 13, color: "#7A9BAD", marginBottom: 18 }}>
          Enter your superadmin secret to access the health dashboard.
        </p>
        <input
          type="password"
          placeholder="Superadmin secret"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleLogin()}
          style={{
            width: "100%", background: ds.dark, border: "1.5px solid #1e3a4f",
            borderRadius: 10, padding: "11px 14px", fontSize: 13, color: "white",
            fontFamily: ds.fontDm, outline: "none", marginBottom: 12, boxSizing: "border-box",
          }}
        />
        <button
          onClick={handleLogin}
          disabled={loading}
          style={{
            width: "100%", background: loading ? "#015F6B" : ds.teal,
            color: "white", border: "none", borderRadius: 10, padding: "12px",
            fontSize: 14, fontWeight: 600, fontFamily: ds.fontSyne,
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Verifying…" : "Unlock"}
        </button>
        {error && <div style={{ marginTop: 12, fontSize: 13, color: "#FF9A9A" }}>❌ {error}</div>}
      </div>
    </div>
  );
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────

export default function HealthDashboard() {
  const [authed, setAuthed] = useState(isSuperadminLoggedIn());
  const [activePanel, setActivePanel] = useState("summary");
  const [timeRange, setTimeRange] = useState("24h");
  const [filterOrgId, setFilterOrgId] = useState("");
  const [orgList, setOrgList] = useState([]);

  // Panel data
  const [summary,      setSummary]      = useState(null);
  const [integrations, setIntegrations] = useState(null);
  const [errors,       setErrors]       = useState(null);
  const [jobs,         setJobs]         = useState(null);
  const [claudeUsage,  setClaudeUsage]  = useState(null);
  const [webhooks,     setWebhooks]     = useState(null);
  const [orgs,         setOrgs]         = useState(null);

  // Loading states
  const [loading, setLoading] = useState({});

  const setLoad = (key, val) => setLoading(prev => ({ ...prev, [key]: val }));

  const params = useCallback(() => {
    const p = { since: sinceFromRange(timeRange) };
    if (filterOrgId) p.org_id = filterOrgId;
    return p;
  }, [timeRange, filterOrgId]);

  // ── Fetch functions ──────────────────────────────────────────────────────

  const fetchSummary = useCallback(async () => {
    setLoad("summary", true);
    try { setSummary((await getHealthSummary(params())).data); } catch {}
    setLoad("summary", false);
  }, [params]);

  const fetchIntegrations = useCallback(async () => {
    setLoad("integrations", true);
    try { setIntegrations((await getHealthIntegrations()).data); } catch {}
    setLoad("integrations", false);
  }, []);

  const fetchErrors = useCallback(async () => {
    setLoad("errors", true);
    try { setErrors((await getHealthErrors(params())).data); } catch {}
    setLoad("errors", false);
  }, [params]);

  const fetchJobs = useCallback(async () => {
    setLoad("jobs", true);
    try { setJobs((await getHealthJobs(params())).data); } catch {}
    setLoad("jobs", false);
  }, [params]);

  const fetchClaude = useCallback(async () => {
    setLoad("claude", true);
    try { setClaudeUsage((await getHealthClaudeUsage(params())).data); } catch {}
    setLoad("claude", false);
  }, [params]);

  const fetchWebhooks = useCallback(async () => {
    setLoad("webhooks", true);
    try { setWebhooks((await getHealthWebhooks(params())).data); } catch {}
    setLoad("webhooks", false);
  }, [params]);

  const fetchOrgs = useCallback(async () => {
    setLoad("orgs", true);
    try {
      const data = (await getHealthOrgs(params())).data;
      setOrgs(data);
      // Populate org selector from orgs panel on first load
      if (data?.items?.length && !orgList.length) {
        setOrgList(data.items);
      }
    } catch {}
    setLoad("orgs", false);
  }, [params, orgList.length]);

  const fetchAll = useCallback(() => {
    fetchSummary();
    fetchIntegrations();
    fetchErrors();
    fetchJobs();
    fetchClaude();
    fetchWebhooks();
    fetchOrgs();
  }, [fetchSummary, fetchIntegrations, fetchErrors, fetchJobs, fetchClaude, fetchWebhooks, fetchOrgs]);

  // Initial load + refetch on filter change
  useEffect(() => {
    if (!authed) return;
    fetchAll();
  }, [authed, timeRange, filterOrgId]);

  // Auto-refresh summary + integrations every 2 min
  useEffect(() => {
    if (!authed) return;
    const id = setInterval(() => {
      fetchSummary();
      fetchIntegrations();
    }, 120_000);
    return () => clearInterval(id);
  }, [authed, fetchSummary, fetchIntegrations]);

  if (!authed) {
    return <LoginGate onAuthed={() => { setAuthed(true); }} />;
  }

  const handleOrgClick = (orgId) => {
    setFilterOrgId(orgId === filterOrgId ? "" : orgId);
  };

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: "24px 28px", fontFamily: ds.fontDm }}>

      {/* ── Page header ───────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 22 }}>
        <div>
          <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: "white", margin: "0 0 4px" }}>
            System Health
          </h1>
          <p style={{ fontSize: 13, color: "#7A9BAD", margin: 0 }}>
            Platform monitoring across all organisations
          </p>
        </div>
        <button
          onClick={() => { clearSuperadminToken(); setAuthed(false); }}
          style={{
            background: "transparent", border: "1px solid #1e3a4f",
            borderRadius: 8, padding: "6px 14px", fontSize: 12,
            color: "#7A9BAD", cursor: "pointer", fontFamily: ds.fontDm,
          }}
        >
          Log out
        </button>
      </div>

      {/* ── Filter bar ────────────────────────────────────────────── */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        marginBottom: 22, flexWrap: "wrap",
      }}>
        {/* Time range */}
        <div style={{ display: "flex", gap: 4 }}>
          {TIME_RANGES.map(t => (
            <button
              key={t.value}
              onClick={() => setTimeRange(t.value)}
              style={{
                background: timeRange === t.value ? ds.teal : "transparent",
                color: timeRange === t.value ? "white" : "#7A9BAD",
                border: `1px solid ${timeRange === t.value ? ds.teal : "#1e3a4f"}`,
                borderRadius: 7, padding: "5px 12px", fontSize: 12,
                fontWeight: 600, cursor: "pointer", fontFamily: ds.fontDm,
                transition: "all 0.15s",
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Org filter */}
        <select
          value={filterOrgId}
          onChange={(e) => setFilterOrgId(e.target.value)}
          style={{
            background: ds.dark2, border: "1px solid #1e3a4f", borderRadius: 7,
            padding: "5px 12px", fontSize: 12, color: filterOrgId ? "white" : "#7A9BAD",
            cursor: "pointer", fontFamily: ds.fontDm, outline: "none",
          }}
        >
          <option value="">All organisations</option>
          {orgList.map(o => (
            <option key={o.id} value={o.id}>{o.name}</option>
          ))}
        </select>

        {filterOrgId && (
          <button
            onClick={() => setFilterOrgId("")}
            style={{
              background: "transparent", border: "1px solid #1e3a4f",
              borderRadius: 7, padding: "5px 10px", fontSize: 12,
              color: "#7A9BAD", cursor: "pointer",
            }}
          >
            ✕ Clear filter
          </button>
        )}

        <button
          onClick={fetchAll}
          style={{
            marginLeft: "auto", background: "transparent", border: "1px solid #1e3a4f",
            borderRadius: 7, padding: "5px 14px", fontSize: 12,
            color: "#7A9BAD", cursor: "pointer", fontFamily: ds.fontDm,
          }}
        >
          ↻ Refresh
        </button>
      </div>

      {/* ── Summary metrics row ────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 22 }}>
        {[
          { label: "Total Orgs",      value: summary?.total_orgs        ?? "—", accent: ds.teal    },
          { label: "Errors",          value: summary?.errors_since       ?? "—", accent: "#ef4444"  },
          { label: "Failed Jobs",     value: summary?.failed_jobs_since  ?? "—", accent: "#f59e0b"  },
          { label: "Webhook Errors",  value: summary?.webhook_errors_since ?? "—", accent: "#a78bfa" },
        ].map(m => (
          <div key={m.label} style={{ ...card, marginBottom: 0, borderLeft: `3px solid ${m.accent}` }}>
            <div style={labelStyle}>{m.label}</div>
            <div style={{ ...valueStyle, color: m.accent, marginTop: 6 }}>
              {loading.summary ? <Spinner /> : m.value}
            </div>
          </div>
        ))}
      </div>

      {/* ── Panel tabs ────────────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 4, marginBottom: 18, flexWrap: "wrap" }}>
        {PANELS.map(p => (
          <button
            key={p.id}
            onClick={() => setActivePanel(p.id)}
            style={{
              background: activePanel === p.id ? ds.teal : "transparent",
              color: activePanel === p.id ? "white" : "#7A9BAD",
              border: `1px solid ${activePanel === p.id ? ds.teal : "#1e3a4f"}`,
              borderRadius: 7, padding: "6px 14px", fontSize: 12,
              fontWeight: 500, cursor: "pointer", fontFamily: ds.fontDm,
              transition: "all 0.15s",
            }}
          >
            {p.label}
            {p.id === "errors" && (errors?.count > 0) && (
              <span style={{ marginLeft: 6, ...badge("#ef4444"), padding: "1px 6px", fontSize: 10 }}>
                {errors.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Panels — Pattern 26: display:none not unmount ────────── */}

      {/* INTEGRATIONS */}
      <div style={{ display: activePanel === "integrations" ? "block" : "none" }}>
        <div style={card}>
          <h3 style={sectionTitle}>Integration Status</h3>
          {loading.integrations && !integrations ? <PanelLoader /> : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
              {integrations && Object.entries(integrations).map(([name, info]) => (
                <div key={name} style={{
                  background: "rgba(255,255,255,0.03)", border: "1px solid #1a2f3f",
                  borderRadius: 10, padding: "14px 16px",
                  borderLeft: `3px solid ${STATUS_COLORS[info.status] ?? "#6b7280"}`,
                }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: "white", textTransform: "capitalize" }}>{name}</span>
                    <span style={badge(STATUS_COLORS[info.status] ?? "#6b7280")}>{info.status}</span>
                  </div>
                  {info.detail && <div style={{ fontSize: 11, color: "#7A9BAD" }}>{info.detail}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ERRORS */}
      <div style={{ display: activePanel === "errors" ? "block" : "none" }}>
        <div style={card}>
          <h3 style={sectionTitle}>Error Log {errors?.count > 0 && `— ${errors.count} errors`}</h3>
          {loading.errors && !errors ? <PanelLoader /> : (
            errors?.items?.length === 0
              ? <Empty text="No errors in this time range." />
              : errors?.items?.map((e, i) => (
                <div key={i} style={{ ...rowStyle, flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, width: "100%" }}>
                    <span style={badge("#ef4444")}>{e.error_type}</span>
                    {e.http_status && <span style={badge("#f59e0b")}>{e.http_status}</span>}
                    {e.org_slug && <span style={{ fontSize: 11, color: "#7A9BAD" }}>org: {e.org_slug}</span>}
                    <span style={{ marginLeft: "auto", fontSize: 11, color: "#3a5a6a" }}>{fmtTime(e.occurred_at)}</span>
                  </div>
                  <div style={{ fontSize: 12, color: "#A0BDC8" }}>{e.error_message}</div>
                  {e.file_path && (
                    <div style={{ fontSize: 11, color: "#3a6a7a", fontFamily: "monospace" }}>
                      {e.file_path}{e.function_name ? ` → ${e.function_name}` : ""}{e.line_number ? `:${e.line_number}` : ""}
                    </div>
                  )}
                  {e.fix_hint && (
                    <div style={{
                      fontSize: 12, color: "#22d3a5", background: "rgba(34,211,165,0.07)",
                      border: "1px solid rgba(34,211,165,0.15)", borderRadius: 6,
                      padding: "6px 10px", marginTop: 2,
                    }}>
                      💡 {e.fix_hint}
                    </div>
                  )}
                </div>
              ))
          )}
        </div>
      </div>

      {/* JOBS */}
      <div style={{ display: activePanel === "jobs" ? "block" : "none" }}>
        <div style={card}>
          <h3 style={sectionTitle}>Background Job History</h3>
          {loading.jobs && !jobs ? <PanelLoader /> : (
            jobs?.items?.length === 0
              ? <Empty text="No job runs in this time range." />
              : (
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                  <thead>
                    <tr style={{ color: "#3a5a6a", textAlign: "left" }}>
                      {["Worker", "Status", "Processed", "Failed", "Skipped", "Duration", "Started"].map(h => (
                        <th key={h} style={{ padding: "6px 10px", fontWeight: 600, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.8px", borderBottom: "1px solid #1a2f3f" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {jobs?.items?.map((j, i) => (
                      <tr key={i} style={{ borderBottom: "1px solid #0e1f2a" }}>
                        <td style={{ padding: "9px 10px", color: "white", fontWeight: 500 }}>{j.worker_name}</td>
                        <td style={{ padding: "9px 10px" }}><span style={badge(STATUS_COLORS[j.status] ?? "#6b7280")}>{j.status}</span></td>
                        <td style={{ padding: "9px 10px", color: "#A0BDC8" }}>{j.items_processed}</td>
                        <td style={{ padding: "9px 10px", color: j.items_failed > 0 ? "#ef4444" : "#A0BDC8" }}>{j.items_failed}</td>
                        <td style={{ padding: "9px 10px", color: "#A0BDC8" }}>{j.items_skipped}</td>
                        <td style={{ padding: "9px 10px", color: "#A0BDC8" }}>{j.run_duration_ms ? `${j.run_duration_ms}ms` : "—"}</td>
                        <td style={{ padding: "9px 10px", color: "#3a5a6a" }}>{fmtTime(j.started_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
          )}
        </div>
      </div>

      {/* CLAUDE USAGE */}
      <div style={{ display: activePanel === "claude" ? "block" : "none" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
          <div style={{ ...card, marginBottom: 0, borderLeft: `3px solid ${ds.teal}` }}>
            <div style={labelStyle}>Total Cost</div>
            <div style={{ ...valueStyle, color: ds.teal, marginTop: 6 }}>
              {loading.claude && !claudeUsage ? <Spinner /> : `$${(claudeUsage?.total_cost ?? 0).toFixed(4)}`}
            </div>
          </div>
          <div style={{ ...card, marginBottom: 0, borderLeft: "3px solid #a78bfa" }}>
            <div style={labelStyle}>Total Tokens</div>
            <div style={{ ...valueStyle, color: "#a78bfa", marginTop: 6 }}>
              {loading.claude && !claudeUsage ? <Spinner /> : fmtNum(claudeUsage?.total_tokens ?? 0)}
            </div>
          </div>
        </div>
        <div style={card}>
          <h3 style={sectionTitle}>By Function</h3>
          {loading.claude && !claudeUsage ? <PanelLoader /> : (
            claudeUsage?.by_function?.length === 0
              ? <Empty text="No Claude calls in this time range." />
              : (
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                  <thead>
                    <tr style={{ color: "#3a5a6a", textAlign: "left" }}>
                      {["Function", "Calls", "Tokens", "Est. Cost"].map(h => (
                        <th key={h} style={{ padding: "6px 10px", fontWeight: 600, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.8px", borderBottom: "1px solid #1a2f3f" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {claudeUsage?.by_function?.sort((a, b) => b.total_cost - a.total_cost).map((f, i) => (
                      <tr key={i} style={{ borderBottom: "1px solid #0e1f2a" }}>
                        <td style={{ padding: "9px 10px", color: "white", fontFamily: "monospace", fontSize: 12 }}>{f.function_name}</td>
                        <td style={{ padding: "9px 10px", color: "#A0BDC8" }}>{f.calls}</td>
                        <td style={{ padding: "9px 10px", color: "#A0BDC8" }}>{fmtNum(f.total_tokens)}</td>
                        <td style={{ padding: "9px 10px", color: ds.teal, fontWeight: 600 }}>${f.total_cost.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
          )}
        </div>
      </div>

      {/* WEBHOOKS */}
      <div style={{ display: activePanel === "webhooks" ? "block" : "none" }}>
        <div style={card}>
          <h3 style={sectionTitle}>Webhook Request Log</h3>
          {loading.webhooks && !webhooks ? <PanelLoader /> : (
            webhooks?.items?.length === 0
              ? <Empty text="No webhook hits in this time range." />
              : (
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                  <thead>
                    <tr style={{ color: "#3a5a6a", textAlign: "left" }}>
                      {["Route", "Topic", "Org", "Status", "Duration", "Time"].map(h => (
                        <th key={h} style={{ padding: "6px 10px", fontWeight: 600, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.8px", borderBottom: "1px solid #1a2f3f" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {webhooks?.items?.map((w, i) => (
                      <tr key={i} style={{ borderBottom: "1px solid #0e1f2a" }}>
                        <td style={{ padding: "9px 10px", color: "white", fontFamily: "monospace", fontSize: 11 }}>{w.route}</td>
                        <td style={{ padding: "9px 10px", color: "#7A9BAD" }}>{w.topic || "—"}</td>
                        <td style={{ padding: "9px 10px", color: "#7A9BAD", fontSize: 11, fontFamily: "monospace" }}>{w.org_id ? w.org_id.slice(0, 8) + "…" : "—"}</td>
                        <td style={{ padding: "9px 10px" }}>
                          <span style={badge(w.response_status >= 400 ? "#ef4444" : "#22d3a5")}>{w.response_status}</span>
                        </td>
                        <td style={{ padding: "9px 10px", color: "#A0BDC8" }}>{w.processing_ms != null ? `${w.processing_ms}ms` : "—"}</td>
                        <td style={{ padding: "9px 10px", color: "#3a5a6a" }}>{fmtTime(w.received_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
          )}
        </div>
      </div>

      {/* ORG HEALTH */}
      <div style={{ display: activePanel === "orgs" ? "block" : "none" }}>
        <div style={card}>
          <h3 style={sectionTitle}>Per-Organisation Health</h3>
          {loading.orgs && !orgs ? <PanelLoader /> : (
            orgs?.items?.length === 0
              ? <Empty text="No organisations found." />
              : orgs?.items?.map((o, i) => (
                <div
                  key={i}
                  onClick={() => handleOrgClick(o.id)}
                  style={{
                    ...rowStyle,
                    cursor: "pointer",
                    borderLeft: o.needs_attention ? "3px solid #ef4444" : "3px solid #1a2f3f",
                    background: filterOrgId === o.id ? "rgba(0,187,150,0.08)" : "rgba(255,255,255,0.03)",
                    transition: "all 0.15s",
                  }}
                >
                  <div style={{ flex: 1 }}>
                    <span style={{ color: "white", fontWeight: 600, fontSize: 13 }}>{o.name}</span>
                    <span style={{ marginLeft: 10, fontSize: 11, color: "#3a5a6a" }}>{o.slug}</span>
                  </div>
                  <span style={badge(o.subscription_status === "active" || o.subscription_status === "trial" ? "#22d3a5" : "#ef4444")}>
                    {o.subscription_status}
                  </span>
                  {o.error_count > 0 && <span style={badge("#ef4444")}>{o.error_count} errors</span>}
                  {o.failed_jobs_count > 0 && <span style={badge("#f59e0b")}>{o.failed_jobs_count} failed jobs</span>}
                  {o.needs_attention && <span style={badge("#ef4444")}>⚠ Needs attention</span>}
                  {!o.needs_attention && <span style={badge("#22d3a5")}>✓ Healthy</span>}
                  {filterOrgId === o.id && <span style={{ fontSize: 11, color: ds.teal }}>← filtering</span>}
                </div>
              ))
          )}
        </div>
      </div>

      {/* SUMMARY panel */}
      <div style={{ display: activePanel === "summary" ? "block" : "none" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <div style={card}>
            <h3 style={sectionTitle}>Recent Errors</h3>
            {loading.errors && !errors ? <PanelLoader /> : (
              errors?.items?.slice(0, 5).length === 0
                ? <Empty text="No errors." />
                : errors?.items?.slice(0, 5).map((e, i) => (
                  <div key={i} style={{ ...rowStyle, flexDirection: "column", alignItems: "flex-start", gap: 4 }}>
                    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <span style={badge("#ef4444")}>{e.error_type}</span>
                      <span style={{ fontSize: 11, color: "#3a5a6a" }}>{fmtTime(e.occurred_at)}</span>
                    </div>
                    <div style={{ fontSize: 12, color: "#A0BDC8" }}>{e.error_message?.slice(0, 120)}</div>
                  </div>
                ))
            )}
          </div>
          <div style={card}>
            <h3 style={sectionTitle}>Recent Job Runs</h3>
            {loading.jobs && !jobs ? <PanelLoader /> : (
              jobs?.items?.slice(0, 5).length === 0
                ? <Empty text="No job runs." />
                : jobs?.items?.slice(0, 5).map((j, i) => (
                  <div key={i} style={rowStyle}>
                    <span style={{ flex: 1, color: "white", fontSize: 12 }}>{j.worker_name}</span>
                    <span style={badge(STATUS_COLORS[j.status] ?? "#6b7280")}>{j.status}</span>
                    <span style={{ fontSize: 11, color: "#3a5a6a" }}>{fmtTime(j.started_at)}</span>
                  </div>
                ))
            )}
          </div>
          <div style={card}>
            <h3 style={sectionTitle}>Integration Status</h3>
            {loading.integrations && !integrations ? <PanelLoader /> : (
              integrations && Object.entries(integrations).map(([name, info]) => (
                <div key={name} style={rowStyle}>
                  <span style={{ flex: 1, color: "white", fontSize: 12, textTransform: "capitalize" }}>{name}</span>
                  <span style={badge(STATUS_COLORS[info.status] ?? "#6b7280")}>{info.status}</span>
                </div>
              ))
            )}
          </div>
          <div style={card}>
            <h3 style={sectionTitle}>Orgs Needing Attention</h3>
            {loading.orgs && !orgs ? <PanelLoader /> : (
              orgs?.items?.filter(o => o.needs_attention).length === 0
                ? <Empty text="All orgs healthy." />
                : orgs?.items?.filter(o => o.needs_attention).map((o, i) => (
                  <div key={i} style={{ ...rowStyle, cursor: "pointer" }} onClick={() => handleOrgClick(o.id)}>
                    <span style={{ flex: 1, color: "white", fontSize: 12 }}>{o.name}</span>
                    {o.error_count > 0 && <span style={badge("#ef4444")}>{o.error_count} errors</span>}
                    {o.failed_jobs_count > 0 && <span style={badge("#f59e0b")}>{o.failed_jobs_count} jobs</span>}
                  </div>
                ))
            )}
          </div>
        </div>
      </div>

    </div>
  );
}

// ─── Micro components ─────────────────────────────────────────────────────────

function Spinner() {
  return (
    <span style={{
      display: "inline-block", width: 16, height: 16,
      border: "2px solid rgba(255,255,255,0.15)",
      borderTopColor: ds.teal, borderRadius: "50%",
      animation: "spin 0.7s linear infinite",
    }} />
  );
}

function PanelLoader() {
  return (
    <div style={{ display: "flex", justifyContent: "center", padding: "32px 0" }}>
      <Spinner />
    </div>
  );
}

function Empty({ text }) {
  return (
    <div style={{ textAlign: "center", padding: "28px 0", fontSize: 13, color: "#3a5a6a" }}>
      {text}
    </div>
  );
}

// ─── Formatters ───────────────────────────────────────────────────────────────

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}

function fmtNum(n) {
  if (n == null) return "—";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "k";
  return String(n);
}
