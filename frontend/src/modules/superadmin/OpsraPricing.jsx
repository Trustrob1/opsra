// frontend/src/modules/superadmin/OpsraPricing.jsx
// ACCOUNT-PLANS AP-8 — Opsra Pricing: what every business on Opsra is sold. Plans (Capture / Convert / Grow), what each
// ticks, add-ons including the extra-user price, billing rules and discount codes. Superadmin sign-in only.
// Reuses the plan and discount cards that used to sit in Sites > Settings; they now save through the superadmin calls.
import { useEffect, useState } from "react";
import {
  getPricingContext, getPricingSettings, getPricingCatalog, savePricingSettings,
  listPricingCodes, createPricingCode, updatePricingCode, deletePricingCode,
} from "../../services/superadmin.service";
import TiersCard from "../sites/TiersCard";
import DiscountCodesCard from "../sites/DiscountCodesCard";
import { ds } from "../../utils/ds";

// Defined once so the cards' load effects stay stable.
const TIERS_API = { catalog: getPricingCatalog, save: async (p) => savePricingSettings(p) };
const CODES_API = { list: listPricingCodes, create: createPricingCode, update: updatePricingCode, remove: deletePricingCode };

const toast = (setMsg) => (m) => { setMsg(m); setTimeout(() => setMsg(""), 3500); };

export default function OpsraPricing() {
  const [ctx, setCtx] = useState(null);
  const [pricing, setPricing] = useState(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const [c, s] = await Promise.all([getPricingContext(), getPricingSettings()]);
        if (live) { setCtx(c); setPricing(s?.pricing ?? {}); }
      } catch (e) {
        const d = e?.response?.data?.detail;
        if (live) setErr(typeof d === "string" ? d : "Could not load Opsra Pricing. Please try again.");
      }
    })();
    return () => { live = false; };
  }, []);

  const showToast = toast(setMsg);
  return (
    <div style={{ fontFamily: ds.fontDm }}>
      <h1 style={{ fontFamily: ds.fontSyne, fontWeight: 700, fontSize: 22, color: "white", margin: "0 0 4px" }}>Opsra Pricing</h1>
      <p style={{ fontSize: 13, color: "#7A9BAD", margin: "0 0 18px", maxWidth: 680 }}>
        The plans, prices and discount codes every business on Opsra is sold. Only you can change these.
        {ctx?.org_name ? ` Stored with ${ctx.org_name}.` : ""}
      </p>
      {err && <div role="alert" style={{ color: "#FF9A9A", fontSize: 13, marginBottom: 12 }}>{err}</div>}
      {msg && <div role="status" style={{ color: "#7ee3c8", fontSize: 13, marginBottom: 12 }}>{msg}</div>}
      {pricing && (
        <div style={{ background: ds.light, borderRadius: 14, padding: 18, maxWidth: 1100 }}>
          <TiersCard api={TIERS_API} pricing={pricing} canEdit showToast={showToast}
            onSaved={(row) => setPricing(row?.pricing ?? {})} />
          <DiscountCodesCard api={CODES_API} isActive canEdit showToast={showToast} />
        </div>
      )}
    </div>
  );
}
