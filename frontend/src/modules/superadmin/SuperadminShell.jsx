// frontend/src/modules/superadmin/SuperadminShell.jsx
// ACCOUNT-PLANS AP-8 — the Superadmin area: one sign-in, one left menu, one place for everything only Opsra staff can do.
// Replaces the old Health and + Org buttons. Shown to the Opsra organisation only (App.jsx), and every call underneath is
// still checked by the server with the superadmin login.
import { useEffect, useState } from "react";
import { Activity, Building2, Tag, Wallet, PlusCircle, LogOut, Lock } from "lucide-react";
import { superadminLogin, isSuperadminLoggedIn, clearSuperadminToken } from "../../services/superadmin.service";
import HealthDashboard from "./HealthDashboard.jsx";
import PlansAdminPanel from "./PlansAdminPanel.jsx";
import OpsraPricing from "./OpsraPricing.jsx";
import CreditsAdminPanel from "./CreditsAdminPanel.jsx";
import CreateOrg from "./CreateOrg.jsx";
import { ds } from "../../utils/ds";

const SECTIONS = [
  { id: "health", label: "Health", hint: "System status", Icon: Activity },
  { id: "businesses", label: "Businesses and plans", hint: "Who is on what", Icon: Building2 },
  { id: "pricing", label: "Opsra Pricing", hint: "Plans, prices, codes", Icon: Tag },
  { id: "credits", label: "Credits", hint: "Wallets and rates", Icon: Wallet },
  { id: "create", label: "Create business", hint: "New organisation", Icon: PlusCircle },
];

const STYLES = `
.sa-wrap{display:grid;grid-template-columns:232px minmax(0,1fr);min-height:calc(100vh - 120px);background:${ds.dark}}
.sa-nav{background:${ds.dark2};border-right:1px solid #1e3a4f;padding:16px 10px;display:flex;flex-direction:column;gap:4px}
.sa-item{display:flex;align-items:center;gap:10px;min-height:44px;padding:6px 10px;border-radius:9px;border:0;background:none;color:#9FB6C4;cursor:pointer;text-align:left;font-family:inherit;width:100%}
.sa-item:hover{background:rgba(255,255,255,.06);color:#fff}
.sa-item[aria-current="page"]{background:${ds.teal};color:#fff}
.sa-item:focus-visible,.sa-out:focus-visible{outline:2px solid ${ds.accent};outline-offset:2px}
.sa-item small{display:block;font-size:11px;opacity:.7;font-weight:400}
.sa-main{padding:24px 28px;min-width:0}
@media (max-width: 900px){
  .sa-wrap{grid-template-columns:1fr}
  .sa-nav{flex-direction:row;overflow-x:auto;border-right:0;border-bottom:1px solid #1e3a4f;padding:8px}
  .sa-item{width:auto;white-space:nowrap}
  .sa-item small{display:none}
  .sa-main{padding:16px}
}
`;

function Gate({ onAuthed }) {
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const go = async () => {
    if (!secret.trim()) return;
    setBusy(true); setErr("");
    try { await superadminLogin(secret.trim()); setSecret(""); onAuthed(); } catch (e) {
      const d = e?.response?.data?.detail;
      setErr(typeof d === "string" ? d : "That secret is not right. Try again.");
    }
    setBusy(false);
  };
  return (
    <div style={{ background: ds.dark, minHeight: "calc(100vh - 120px)", padding: 32, fontFamily: ds.fontDm }}>
      <div style={{ maxWidth: 380, background: ds.dark2, border: "1px solid #1e3a4f", borderRadius: 14, padding: 24 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#fff", marginBottom: 6 }}>
          <Lock size={18} aria-hidden="true" />
          <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 18, margin: 0 }}>Superadmin</h1>
        </div>
        <p style={{ fontSize: 13, color: "#9FB6C4", margin: "0 0 16px" }}>Enter your superadmin secret to continue.</p>
        <label htmlFor="sa-secret" style={{ fontSize: 12, color: "#9FB6C4" }}>Superadmin secret</label>
        <input id="sa-secret" type="password" value={secret} onChange={(e) => setSecret(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && go()} autoComplete="off"
          style={{ width: "100%", boxSizing: "border-box", margin: "6px 0 12px", minHeight: 44, background: ds.dark, border: "1.5px solid #1e3a4f", borderRadius: 10, padding: "0 14px", fontSize: 14, color: "#fff", fontFamily: ds.fontDm }} />
        <button type="button" onClick={go} disabled={busy}
          style={{ width: "100%", minHeight: 44, background: ds.teal, color: "#fff", border: 0, borderRadius: 10, fontSize: 14, fontWeight: 600, cursor: busy ? "not-allowed" : "pointer", fontFamily: ds.fontDm }}>
          {busy ? "Checking…" : "Unlock"}
        </button>
        {err && <div role="alert" style={{ marginTop: 12, fontSize: 13, color: "#FF9A9A" }}>{err}</div>}
      </div>
    </div>
  );
}

export default function SuperadminShell({ initial = "health" }) {
  const [authed, setAuthed] = useState(isSuperadminLoggedIn());
  const [section, setSection] = useState(initial);
  useEffect(() => { setSection(initial); }, [initial]);
  if (!authed) return <Gate onAuthed={() => setAuthed(true)} />;
  const out = () => { clearSuperadminToken(); setAuthed(false); };
  return (
    <div className="sa-wrap" style={{ fontFamily: ds.fontDm }}>
      <style>{STYLES}</style>
      <nav className="sa-nav" aria-label="Superadmin">
        {SECTIONS.map(({ id, label, hint, Icon }) => (
          <button key={id} type="button" className="sa-item" aria-current={section === id ? "page" : undefined} onClick={() => setSection(id)}>
            <Icon size={18} aria-hidden="true" />
            <span style={{ fontSize: 13.5, fontWeight: 600 }}>{label}<small>{hint}</small></span>
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <button type="button" className="sa-item sa-out" onClick={out}>
          <LogOut size={18} aria-hidden="true" /><span style={{ fontSize: 13.5, fontWeight: 600 }}>Sign out</span>
        </button>
      </nav>
      <main className="sa-main">
        {section === "health" && <HealthDashboard embedded />}
        {section === "businesses" && <PlansAdminPanel />}
        {section === "pricing" && <OpsraPricing />}
        {section === "credits" && <CreditsAdminPanel />}
        {section === "create" && <CreateOrg />}
      </main>
    </div>
  );
}
