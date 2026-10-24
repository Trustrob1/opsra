// frontend/src/modules/superadmin/WaSignupSettingsCard.jsx
// WA-AUTO-5 — Trust opens or closes the public WhatsApp sign-up (/start/whatsapp) and sets trial length, starter credit and a daily cap.
import { useEffect, useState } from "react";
import { getWaSignupSettings, saveWaSignupSettings } from "../../services/superadmin.service";
import { ds } from "../../utils/ds";

const card = { background: ds.dark2, border: "1px solid #1e3a4f", borderRadius: 12, padding: "18px 20px", marginBottom: 16 };
const field = { minHeight: 36, padding: "6px 10px", background: "#0b1a24", color: "white", border: "1px solid #1e3a4f", borderRadius: 7, fontSize: 13, fontFamily: ds.fontDm, boxSizing: "border-box", width: 120 };
const lab = { display: "block", fontSize: 12, color: "#7A9BAD", marginBottom: 4 };
const errText = (e) => {
  const d = e?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (d?.message) return d.message;
  return "Something went wrong. Please try again.";
};

export default function WaSignupSettingsCard() {
  const [s, setS] = useState(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { getWaSignupSettings().then(setS).catch((e) => setMsg(errText(e))); }, []);
  if (!s) return <div style={{ ...card, color: "#7A9BAD", fontSize: 13 }}>{msg || "Loading…"}</div>;
  const num = (k) => (e) => setS({ ...s, [k]: e.target.value === "" ? "" : Number(e.target.value) });
  const save = async () => {
    setBusy(true); setMsg("");
    try { setS(await saveWaSignupSettings(s)); setMsg("Saved."); } catch (e) { setMsg(errText(e)); } finally { setBusy(false); }
  };
  return (
    <div style={card}>
      <div style={{ color: "white", fontWeight: 600, marginBottom: 4 }}>WhatsApp sign-up page (/start/whatsapp)</div>
      <p style={{ color: "#7A9BAD", fontSize: 12.5, margin: "0 0 12px" }}>New businesses get the Automate plan free for the trial days, with credits switched on. The price shown on the page is the Automate price in the plan settings.</p>
      <label style={{ display: "flex", gap: 8, alignItems: "center", color: "white", fontSize: 13, marginBottom: 12 }}>
        <input type="checkbox" checked={!!s.is_open} onChange={(e) => setS({ ...s, is_open: e.target.checked })} /> Sign-up is open to the public
      </label>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <div><label style={lab} htmlFor="wa-trial">Free trial days (1–30)</label><input id="wa-trial" type="number" min="1" max="30" style={field} value={s.trial_days} onChange={num("trial_days")} /></div>
        <div><label style={lab} htmlFor="wa-credit">Starter credit ₦ (0–5,000)</label><input id="wa-credit" type="number" min="0" max="5000" style={field} value={s.starter_credit_ngn} onChange={num("starter_credit_ngn")} /></div>
        <div><label style={lab} htmlFor="wa-cap">Most sign-ups a day</label><input id="wa-cap" type="number" min="0" max="1000" style={field} value={s.daily_cap} onChange={num("daily_cap")} /></div>
      </div>
      <div style={{ marginTop: 14, display: "flex", gap: 12, alignItems: "center" }}>
        <button type="button" disabled={busy} onClick={save} style={{ background: ds.teal, color: "white", border: "none", borderRadius: 7, padding: "8px 16px", fontSize: 13, fontWeight: 600, cursor: "pointer", minHeight: 36 }}>{busy ? "Saving…" : "Save"}</button>
        {msg && <span role="status" style={{ color: msg === "Saved." ? "#4ade80" : "#f87171", fontSize: 13 }}>{msg}</span>}
      </div>
    </div>
  );
}
