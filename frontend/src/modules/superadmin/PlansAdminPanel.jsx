// frontend/src/modules/superadmin/PlansAdminPanel.jsx
// ACCOUNT-PLANS AP-3 — superadmin view of every business's own plan: who is on what, the enforcement switch,
// and staff actions (give a plan, pause / resume / cancel). Rendered inside HealthDashboard (same superadmin login).
import { useCallback, useEffect, useState } from "react";
import { getPlanOrgs, grantOrgPlan, setOrgPlanStatus, setOrgEnforced } from "../../services/superadmin.service";
import { ds } from "../../utils/ds";
import WaSignupSettingsCard from "./WaSignupSettingsCard.jsx";

const card = { background: ds.dark2, border: "1px solid #1e3a4f", borderRadius: 12, padding: "18px 20px", marginBottom: 16 };
const th = { textAlign: "left", fontSize: 11, fontWeight: 600, color: "#3a5a6a", textTransform: "uppercase", letterSpacing: "1px", padding: "6px 8px" };
const td = { fontSize: 13, color: "#A0BDC8", padding: "8px", borderTop: "1px solid #1a2f3f", verticalAlign: "middle" };
const btn = (on) => ({
  background: on ? ds.teal : "transparent", color: on ? "white" : "#7A9BAD", border: `1px solid ${on ? ds.teal : "#1e3a4f"}`,
  borderRadius: 7, padding: "6px 12px", fontSize: 12, fontWeight: 500, cursor: "pointer", fontFamily: ds.fontDm, minHeight: 32,
});
const field = {
  minHeight: 36, padding: "6px 10px", background: "#0b1a24", color: "white", border: "1px solid #1e3a4f",
  borderRadius: 7, fontSize: 13, fontFamily: ds.fontDm, boxSizing: "border-box",
};
const TIERS = [["capture", "Capture"], ["convert", "Convert"], ["grow", "Grow"], ["automate", "Automate (WhatsApp only)"]];
const errText = (e) => {
  const d = e?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d[0]?.msg) return d[0].msg;
  return "Something went wrong. Please try again.";
};
const day = (v) => (v ? String(v).slice(0, 10) : "—");

function Row({ o, onChanged, onError }) {
  const [open, setOpen] = useState(false);
  const [tier, setTier] = useState(o.tier || "capture");
  const [until, setUntil] = useState("");
  const [source, setSource] = useState("staff");
  const [busy, setBusy] = useState(false);

  const run = async (fn) => {
    setBusy(true); onError("");
    try { await fn(); setOpen(false); await onChanged(); } catch (e) { onError(errText(e)); } finally { setBusy(false); }
  };
  const grant = () => run(() => grantOrgPlan(o.org_id, {
    kind: "tier", key: tier, source, until: until ? new Date(`${until}T23:59:59Z`).toISOString() : null,
  }));
  const act = (action) => run(() => setOrgPlanStatus(o.org_id, { plan_id: o.plan_id, action }));
  const flip = () => run(() => setOrgEnforced(o.org_id, !o.enforced));

  return (
    <>
      <tr>
        <td style={td}>{o.name || o.slug}</td>
        <td style={td}>{o.tier || "—"}</td>
        <td style={td}>{o.status || "—"}{o.source ? ` (${o.source})` : ""}</td>
        <td style={td}>{day(o.paid_until)}</td>
        <td style={td}>
          <button type="button" style={btn(o.enforced)} disabled={busy} onClick={flip}
            title="When on, the plan decides what this business can use">{o.enforced ? "On" : "Off"}</button>
        </td>
        <td style={td}><button type="button" style={btn(false)} onClick={() => setOpen(!open)}>{open ? "Close" : "Manage"}</button></td>
      </tr>
      {open && (
        <tr>
          <td style={{ ...td, background: "#0b1a24" }} colSpan={6}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <select aria-label="Plan" style={field} value={tier} onChange={(e) => setTier(e.target.value)}>
                {TIERS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
              <select aria-label="Source" style={field} value={source} onChange={(e) => setSource(e.target.value)}>
                <option value="staff">Given by staff</option><option value="grandfathered">Grandfathered</option>
              </select>
              <input aria-label="Ends on (blank = no end date)" type="date" style={field} value={until} onChange={(e) => setUntil(e.target.value)} />
              <button type="button" style={btn(true)} disabled={busy} onClick={grant}>Give this plan</button>
              {o.plan_id && (
                <>
                  <button type="button" style={btn(false)} disabled={busy} onClick={() => act("pause")}>Pause</button>
                  <button type="button" style={btn(false)} disabled={busy} onClick={() => act("resume")}>Resume</button>
                  <button type="button" style={btn(false)} disabled={busy} onClick={() => act("cancel")}>Cancel plan</button>
                </>
              )}
            </div>
            <div style={{ fontSize: 11, color: "#7A9BAD", marginTop: 8 }}>
              Leave the end date blank for no end date. Switching enforcement on makes the plan decide what this business can use; off puts it back exactly as before.
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function PlansAdminPanel() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const load = useCallback(async () => {
    try { setData(await getPlanOrgs()); } catch (e) { setError(errText(e)); }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (!data) return <div style={{ color: "#7A9BAD", fontSize: 13 }}>{error || "Loading…"}</div>;
  const rows = data.orgs.filter((o) => `${o.name || ""} ${o.slug || ""}`.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <div>
      {error && <div role="alert" style={{ ...card, color: "#f87171", padding: 12 }}>{error}</div>}
      <WaSignupSettingsCard />
      <div style={{ ...card, display: "flex", gap: 24, flexWrap: "wrap" }}>
        <div><div style={{ fontSize: 11, color: "#3a5a6a" }}>BUSINESSES</div><div style={{ fontSize: 20, color: "white", fontWeight: 700 }}>{data.totals.businesses}</div></div>
        <div><div style={{ fontSize: 11, color: "#3a5a6a" }}>SWITCHED ON</div><div style={{ fontSize: 20, color: "white", fontWeight: 700 }}>{data.totals.enforced}</div></div>
        <div><div style={{ fontSize: 11, color: "#3a5a6a" }}>MONTHLY VALUE (PAID)</div><div style={{ fontSize: 20, color: "white", fontWeight: 700 }}>₦{Number(data.totals.monthly_value_ngn || 0).toLocaleString("en-NG")}</div></div>
      </div>
      <div style={card}>
        <input aria-label="Search businesses" placeholder="Search businesses" style={{ ...field, width: "100%", marginBottom: 10 }} value={q} onChange={(e) => setQ(e.target.value)} />
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr><th style={th}>Business</th><th style={th}>Plan</th><th style={th}>Status</th><th style={th}>Paid until</th><th style={th}>Enforced</th><th style={th} /></tr></thead>
            <tbody>{rows.map((o) => <Row key={o.org_id} o={o} onChanged={load} onError={setError} />)}</tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
