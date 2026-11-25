// frontend/src/modules/superadmin/ChatSignupSettingsCard.jsx
// WEB-ONLY-1b — Trust opens or closes the public Chioma sign-up (/start/chat) and sets the starter credit and a daily cap.
// Separate from the WhatsApp sign-up switch. The plan price shown on the page is the Chioma price in the plan settings.
import { useEffect, useState } from "react";
import { getChatSignupSettings, saveChatSignupSettings } from "../../services/superadmin.service";
import { ds } from "../../utils/ds";

const card = { background: ds.dark2, border: "1px solid #E1E5EC", borderRadius: 12, padding: "18px 20px", marginBottom: 16 };
const field = { minHeight: 36, padding: "6px 10px", background: "#FFFFFF", color: '#1B1F28', border: "1px solid #E1E5EC", borderRadius: 7, fontSize: 13, fontFamily: ds.fontDm, boxSizing: "border-box", width: 120 };
const lab = { display: "block", fontSize: 12, color: "#5B6270", marginBottom: 4 };
const errText = (e) => {
  const d = e?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (d?.message) return d.message;
  return "Something went wrong. Please try again.";
};

export default function ChatSignupSettingsCard() {
  const [s, setS] = useState(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { getChatSignupSettings().then(setS).catch((e) => setMsg(errText(e))); }, []);
  if (!s) return <div style={{ ...card, color: "#5B6270", fontSize: 13 }}>{msg || "Loading…"}</div>;
  const num = (k) => (e) => setS({ ...s, [k]: e.target.value === "" ? "" : Number(e.target.value) });
  const save = async () => {
    setBusy(true); setMsg("");
    try { setS(await saveChatSignupSettings(s)); setMsg("Saved."); } catch (e) { setMsg(errText(e)); } finally { setBusy(false); }
  };
  return (
    <div style={card}>
      <div style={{ color: '#1B1F28', fontWeight: 600, marginBottom: 4 }}>Chioma sign-up page (/start/chat)</div>
      <p style={{ color: "#5B6270", fontSize: 12.5, margin: "0 0 12px" }}>New businesses get web chat only, on a free Chioma plan with no end date. They pay chats from the starter credit; there is no free monthly credit until they subscribe. This switch is separate from the WhatsApp sign-up.</p>
      <label style={{ display: "flex", gap: 8, alignItems: "center", color: '#1B1F28', fontSize: 13, marginBottom: 12 }}>
        <input type="checkbox" checked={!!s.is_open} onChange={(e) => setS({ ...s, is_open: e.target.checked })} /> Sign-up is open to the public
      </label>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <div><label style={lab} htmlFor="chat-credit">Starter credit ₦ (0–5,000)</label><input id="chat-credit" type="number" min="0" max="5000" style={field} value={s.starter_credit_ngn} onChange={num("starter_credit_ngn")} /></div>
        <div><label style={lab} htmlFor="chat-cap">Most sign-ups a day</label><input id="chat-cap" type="number" min="0" max="1000" style={field} value={s.daily_cap} onChange={num("daily_cap")} /></div>
      </div>
      <div style={{ marginTop: 14, display: "flex", gap: 12, alignItems: "center" }}>
        <button type="button" disabled={busy} onClick={save} style={{ background: ds.teal, color: "white", border: "none", borderRadius: 7, padding: "8px 16px", fontSize: 13, fontWeight: 600, cursor: "pointer", minHeight: 36 }}>{busy ? "Saving…" : "Save"}</button>
        {msg && <span role="status" style={{ color: msg === "Saved." ? "#4ade80" : "#f87171", fontSize: 13 }}>{msg}</span>}
      </div>
    </div>
  );
}
