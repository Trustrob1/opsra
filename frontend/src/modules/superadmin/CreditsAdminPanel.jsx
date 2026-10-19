// frontend/src/modules/superadmin/CreditsAdminPanel.jsx
// CREDITS-3 — superadmin view of the credits system: per-business wallets with the metering switch,
// adjustments and refunds (a written reason is required), the margin report, and the reconcile check.
// Rendered inside HealthDashboard (same superadmin login).
import { useCallback, useEffect, useState } from "react";
import {
  getCreditOrgs, getCreditMargin, getCreditReconcile, setCreditMetering, adjustCredit,
} from "../../services/superadmin.service";
import { ds } from "../../utils/ds";

const card = { background: ds.dark2, border: "1px solid #1e3a4f", borderRadius: 12, padding: "18px 20px", marginBottom: 16 };
const th = { textAlign: "left", fontSize: 11, fontWeight: 600, color: "#3a5a6a", textTransform: "uppercase", letterSpacing: "1px", padding: "6px 8px" };
const td = { fontSize: 13, color: "#A0BDC8", padding: "8px", borderTop: "1px solid #1a2f3f", verticalAlign: "middle" };
const btn = (on) => ({
  background: on ? ds.teal : "transparent", color: on ? "white" : "#7A9BAD", border: `1px solid ${on ? ds.teal : "#1e3a4f"}`,
  borderRadius: 7, padding: "6px 12px", fontSize: 12, fontWeight: 500, cursor: "pointer", fontFamily: ds.fontDm, minHeight: 32,
});
const field = {
  width: "100%", minHeight: 36, padding: "6px 10px", background: "#0b1a24", color: "white", border: "1px solid #1e3a4f",
  borderRadius: 7, fontSize: 13, fontFamily: ds.fontDm, boxSizing: "border-box",
};
const lab = { display: "block", fontSize: 11, color: "#7A9BAD", margin: "8px 0 4px" };

const naira = (kobo) => `₦${(Number(kobo || 0) / 100).toLocaleString("en-NG", { maximumFractionDigits: 2 })}`;
const errText = (e) => {
  const d = e?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d[0]?.msg) return d[0].msg;
  return d?.message || "Something went wrong. Please try again.";
};

function Stat({ label, value, sub }) {
  return (
    <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid #1a2f3f", borderRadius: 10, padding: "12px 14px" }}>
      <div style={{ fontSize: 11, color: "#3a5a6a", textTransform: "uppercase", letterSpacing: "1px" }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: "white", marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "#7A9BAD", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function AdjustForm({ org, onDone, onCancel }) {
  const [kind, setKind] = useState("adjust");
  const [dir, setDir] = useState("add");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    const naira_ = Number(amount);
    if (!naira_ || naira_ <= 0) { setError("Enter an amount in naira."); return; }
    if (note.trim().length < 5) { setError("Write the reason (at least 5 characters)."); return; }
    setBusy(true); setError("");
    try {
      const kobo = Math.round(naira_ * 100) * (dir === "add" ? 1 : -1);
      await adjustCredit(org.org_id, { amount_kobo: kobo, note: note.trim(), kind, ref: `sa-${kind}-${org.org_id.slice(0, 8)}-${Date.now()}` });
      onDone();
    } catch (err) { setError(errText(err)); } finally { setBusy(false); }
  };

  return (
    <form onSubmit={submit} style={{ ...card, marginTop: 8, background: "#0e2230" }}>
      <div style={{ color: "white", fontWeight: 600, fontSize: 14 }}>Adjust or refund: {org.name}</div>
      <div style={{ fontSize: 12, color: "#7A9BAD", margin: "2px 0 6px" }}>Balance now {naira(org.balance_kobo)}. Every change is written to the ledger with your reason and cannot be edited later.</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
        <div>
          <label style={lab} htmlFor="ca-kind">Type</label>
          <select id="ca-kind" style={field} value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="adjust">Adjustment (goodwill, correction)</option>
            <option value="refund">Refund (money or credit given back)</option>
          </select>
        </div>
        <div>
          <label style={lab} htmlFor="ca-dir">Direction</label>
          <select id="ca-dir" style={field} value={dir} onChange={(e) => setDir(e.target.value)}>
            <option value="add">Add credit to the balance</option>
            <option value="remove">Take credit off the balance</option>
          </select>
        </div>
        <div>
          <label style={lab} htmlFor="ca-amt">Amount (₦)</label>
          <input id="ca-amt" style={field} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ""))} />
        </div>
      </div>
      <label style={lab} htmlFor="ca-note">Reason (required, shown in the ledger)</label>
      <input id="ca-note" style={field} value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Charged twice for the same chat on 18 Oct" />
      {error && <div role="alert" style={{ color: "#ef4444", fontSize: 12, marginTop: 8 }}>{error}</div>}
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button type="submit" style={btn(true)} disabled={busy}>{busy ? "Saving…" : dir === "add" ? "Add credit" : "Take credit off"}</button>
        <button type="button" style={btn(false)} onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function Businesses() {
  const [orgs, setOrgs] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);
  const [busyId, setBusyId] = useState("");

  const load = useCallback(async () => {
    try { setOrgs((await getCreditOrgs()).orgs); setError(""); } catch (e) { setError(errText(e)); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const toggle = async (o) => {
    const next = !o.metering_enabled;
    const msg = next
      ? `Start charging ${o.name}'s AI use to their credit balance? Their balance is ${naira(o.balance_kobo)}. When it runs out, AI replies stop and the chat falls back to menus.`
      : `Stop charging ${o.name}? AI use will be free for them again.`;
    if (!window.confirm(msg)) return;
    setBusyId(o.org_id);
    try { await setCreditMetering(o.org_id, next); await load(); } catch (e) { setError(errText(e)); } finally { setBusyId(""); }
  };

  if (!orgs && !error) return <div style={{ color: "#7A9BAD", fontSize: 13 }}>Loading…</div>;
  return (
    <div style={card}>
      {error && <div role="alert" style={{ color: "#ef4444", fontSize: 12, marginBottom: 8 }}>{error}</div>}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 760 }}>
          <thead><tr>
            <th style={th}>Business</th><th style={th}>Balance</th><th style={th}>Charging</th>
            <th style={th}>AI spend this month</th><th style={th}>Topped up (all time)</th><th style={th}></th>
          </tr></thead>
          <tbody>
            {(orgs || []).map((o) => (
              <tr key={o.org_id}>
                <td style={{ ...td, color: "white" }}>{o.name}</td>
                <td style={td}>{naira(o.balance_kobo)}</td>
                <td style={td}>
                  <button type="button" style={btn(o.metering_enabled)} disabled={busyId === o.org_id} onClick={() => toggle(o)}
                    aria-pressed={o.metering_enabled}>{o.metering_enabled ? "On" : "Off"}</button>
                </td>
                <td style={td}>{o.has_wallet ? naira(o.month_ai_spend_kobo) : "—"}</td>
                <td style={td}>{naira(o.topups_total_kobo)}</td>
                <td style={td}><button type="button" style={btn(false)} onClick={() => setOpen(open === o.org_id ? null : o.org_id)}>Adjust or refund</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {open && orgs && <AdjustForm org={orgs.find((o) => o.org_id === open)} onCancel={() => setOpen(null)} onDone={() => { setOpen(null); load(); }} />}
    </div>
  );
}

function Margin() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let dead = false;
    setData(null);
    getCreditMargin(days).then((d) => { if (!dead) { setData(d); setError(""); } }).catch((e) => { if (!dead) setError(errText(e)); });
    return () => { dead = true; };
  }, [days]);

  const t = data?.totals || {};
  const aiMargin = (t.ai_charged_kobo || 0) - (t.ai_cost_kobo || 0);
  return (
    <div>
      <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
        {[7, 30, 90, 365].map((d) => <button key={d} type="button" style={btn(days === d)} onClick={() => setDays(d)}>{d === 365 ? "1 year" : `${d} days`}</button>)}
      </div>
      {error && <div role="alert" style={{ color: "#ef4444", fontSize: 12 }}>{error}</div>}
      {!data && !error && <div style={{ color: "#7A9BAD", fontSize: 13 }}>Loading…</div>}
      {data && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10, marginBottom: 14 }}>
            <Stat label="Cash in (top-ups)" value={naira(t.cash_in_kobo)} />
            <Stat label="AI charged" value={naira(t.ai_charged_kobo)} sub={`${t.ai_calls || 0} calls`} />
            <Stat label="AI cost to us" value={naira(t.ai_cost_kobo)} />
            <Stat label="AI margin" value={naira(aiMargin)} sub={t.ai_cost_kobo ? `${Math.round((aiMargin / t.ai_cost_kobo) * 100)}% on cost` : null} />
            <Stat label="Automation fees" value={naira(t.fee_charged_kobo)} />
            <Stat label="Expired credit" value={naira(t.expired_kobo)} sub="counts as income" />
            <Stat label="Refunds and adjustments" value={naira((t.refunds_kobo || 0) + (t.adjustments_kobo || 0))} />
            <Stat label="Total margin" value={naira(t.margin_kobo)} />
          </div>
          <div style={card}>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 720 }}>
                <thead><tr>
                  <th style={th}>Business</th><th style={th}>Cash in</th><th style={th}>AI charged</th><th style={th}>AI cost</th>
                  <th style={th}>Fees</th><th style={th}>Expired</th><th style={th}>Margin</th>
                </tr></thead>
                <tbody>
                  {data.orgs.length === 0 && <tr><td style={td} colSpan={7}>No credit activity in this period.</td></tr>}
                  {data.orgs.map((o) => (
                    <tr key={o.org_id}>
                      <td style={{ ...td, color: "white" }}>{o.name || o.org_id.slice(0, 8)}</td>
                      <td style={td}>{naira(o.cash_in_kobo)}</td><td style={td}>{naira(o.ai_charged_kobo)}</td>
                      <td style={td}>{naira(o.ai_cost_kobo)}</td><td style={td}>{naira(o.fee_charged_kobo)}</td>
                      <td style={td}>{naira(o.expired_kobo)}</td><td style={{ ...td, color: "white" }}>{naira(o.margin_kobo)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul style={{ margin: "12px 0 0", paddingLeft: 18, fontSize: 12, color: "#7A9BAD" }}>
              {data.notes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}

function Checks() {
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async () => {
    setBusy(true); setError("");
    try { setRes(await getCreditReconcile()); } catch (e) { setError(errText(e)); } finally { setBusy(false); }
  };
  return (
    <div style={card}>
      <div style={{ color: "white", fontWeight: 600, fontSize: 14 }}>Balance check</div>
      <p style={{ fontSize: 12, color: "#7A9BAD", margin: "4px 0 10px" }}>Compares every wallet's balance with the sum of its ledger and its credit lots. This also runs nightly.</p>
      <button type="button" style={btn(true)} disabled={busy} onClick={run}>{busy ? "Checking…" : "Run check"}</button>
      {error && <div role="alert" style={{ color: "#ef4444", fontSize: 12, marginTop: 8 }}>{error}</div>}
      {res && (res.mismatches.length === 0
        ? <div style={{ color: "#22d3a5", fontSize: 13, marginTop: 10 }}>All wallets match their ledger and lots.</div>
        : <div style={{ marginTop: 10 }}>
            <div style={{ color: "#ef4444", fontSize: 13 }}>{res.mismatches.length} wallet(s) do not match:</div>
            {res.mismatches.map((m) => (
              <div key={m.org_id} style={{ fontSize: 12, color: "#A0BDC8", marginTop: 4 }}>
                {m.org_id}: balance {naira(m.balance)}, ledger {naira(m.ledger_sum)}, lots {naira(m.lots_sum)}
              </div>
            ))}
          </div>)}
    </div>
  );
}

export default function CreditsAdminPanel() {
  const [tab, setTab] = useState("businesses");
  return (
    <div>
      <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
        {[["businesses", "Businesses"], ["margin", "Margin report"], ["checks", "Checks"]].map(([id, label]) => (
          <button key={id} type="button" style={btn(tab === id)} onClick={() => setTab(id)}>{label}</button>
        ))}
      </div>
      {tab === "businesses" && <Businesses />}
      {tab === "margin" && <Margin />}
      {tab === "checks" && <Checks />}
    </div>
  );
}
