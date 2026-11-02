// frontend/src/modules/superadmin/WaSetupRequestsCard.jsx
// WA-AUTO-6 — businesses that asked Opsra to connect their WhatsApp number. Waiting ones first; "Mark connected" when done.
import { useCallback, useEffect, useState } from "react";
import { getWaSetupRequests, markWaSetupDone } from "../../services/superadmin.service";
import { ds } from "../../utils/ds";

const card = { background: ds.dark2, border: "1px solid #1e3a4f", borderRadius: 12, padding: "18px 20px", marginBottom: 16 };
const th = { textAlign: "left", fontSize: 11, fontWeight: 600, color: "#3a5a6a", textTransform: "uppercase", letterSpacing: "1px", padding: "6px 8px" };
const td = { fontSize: 13, color: "#A0BDC8", padding: "8px", borderTop: "1px solid #1a2f3f", verticalAlign: "top" };
const when = (v) => (v ? new Date(v).toLocaleString("en-NG", { dateStyle: "medium", timeStyle: "short" }) : "—");

export default function WaSetupRequestsCard() {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const load = useCallback(() => getWaSetupRequests().then(setRows).catch(() => setErr("Could not load the requests.")), []);
  useEffect(() => { load(); }, [load]);
  const done = async (orgId) => {
    setBusy(orgId); setErr("");
    try { await markWaSetupDone(orgId); await load(); } catch { setErr("Could not mark that one. Please try again."); } finally { setBusy(""); }
  };
  if (!rows) return <div style={{ ...card, color: "#7A9BAD", fontSize: 13 }}>{err || "Loading…"}</div>;
  const waiting = rows.filter((r) => !r.done).length;
  return (
    <div style={card}>
      <div style={{ color: "white", fontWeight: 600, marginBottom: 4 }}>Connect-WhatsApp requests {waiting > 0 && <span style={{ background: ds.teal, borderRadius: 10, padding: "1px 8px", fontSize: 12, marginLeft: 6 }}>{waiting} waiting</span>}</div>
      {err && <p role="alert" style={{ color: "#f87171", fontSize: 13 }}>{err}</p>}
      {rows.length === 0 ? <p style={{ color: "#7A9BAD", fontSize: 13, margin: 0 }}>No requests yet.</p> : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr><th style={th}>Business</th><th style={th}>Their number</th><th style={th}>Note</th><th style={th}>Asked</th><th style={th}>Status</th><th style={th} /></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.org_id}>
                  <td style={{ ...td, color: "white" }}>{r.business}</td>
                  <td style={td}>{r.phone}</td>
                  <td style={td}>{r.note || "—"}</td>
                  <td style={td}>{when(r.requested_at)}</td>
                  <td style={td}>{r.done ? `Connected ${when(r.done_at)}` : r.number_linked ? "Number linked, not marked" : "Waiting"}</td>
                  <td style={td}>{!r.done && <button type="button" disabled={busy === r.org_id} onClick={() => done(r.org_id)} style={{ background: ds.teal, color: "white", border: "none", borderRadius: 7, padding: "6px 12px", fontSize: 12, fontWeight: 600, cursor: "pointer", minHeight: 32 }}>Mark connected</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
