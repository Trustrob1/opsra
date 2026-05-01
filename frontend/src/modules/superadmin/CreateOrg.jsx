// frontend/src/modules/superadmin/CreateOrg.jsx
// SA-2A — SD7: Backend-proxied superadmin auth.
// Shows a login gate first. On success, stores JWT in memory via superadmin.service.js.
// Secret never appears in frontend JS bundle.
// Pattern 51: full rewrite.

import { useState } from "react";
import {
  createOrganisation,
  superadminLogin,
  isSuperadminLoggedIn,
  clearSuperadminToken,
} from "../../services/superadmin.service";
import { ds } from "../../utils/ds";

export default function CreateOrg() {
  // ── Auth state ────────────────────────────────────────────────────────────
  const [authed, setAuthed] = useState(isSuperadminLoggedIn());
  const [secret, setSecret] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);
  const [loginError, setLoginError] = useState(null);

  // ── Form state ────────────────────────────────────────────────────────────
  const [form, setForm] = useState({
    org_name: "",
    slug: "",
    industry: "",
    ticket_prefix: "",
    owner_email: "",
    owner_full_name: "",
    owner_password: "",
  });

  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(null);
  const [error, setError] = useState(null);

  // ── Handlers ──────────────────────────────────────────────────────────────
  const handleLogin = async () => {
    if (!secret.trim()) return;
    setLoginLoading(true);
    setLoginError(null);
    try {
      await superadminLogin(secret.trim());
      setSecret("");
      setAuthed(true);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setLoginError(
        typeof detail === "string" ? detail : "Invalid secret — access denied."
      );
    }
    setLoginLoading(false);
  };

  const handleLogout = () => {
    clearSuperadminToken();
    setAuthed(false);
    setSuccess(null);
    setError(null);
  };

  const handleChange = (e) => {
    const { name, value } = e.target;
    let updated = { ...form, [name]: value };
    if (name === "org_name") {
      updated.slug = generateSlug(value);
      updated.ticket_prefix = generatePrefix(value);
    }
    setForm(updated);
  };

  const handleSubmit = async () => {
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await createOrganisation(form);
      setSuccess(res.data);
      setForm({
        org_name: "",
        slug: "",
        industry: "",
        ticket_prefix: "",
        owner_email: "",
        owner_full_name: "",
        owner_password: "",
      });
    } catch (err) {
      // If JWT expired, drop back to login gate
      if (err.response?.status === 401 || err.response?.status === 403) {
        clearSuperadminToken();
        setAuthed(false);
        setError("Session expired — please log in again.");
        setLoading(false);
        return;
      }
      const detail = err.response?.data?.detail;
      let msg = "Something went wrong";
      if (Array.isArray(detail)) {
        msg = detail[0]?.msg || msg;
      } else if (typeof detail === "string") {
        msg = detail;
      }
      setError(msg);
    }
    setLoading(false);
  };

  // ── Login gate ────────────────────────────────────────────────────────────
  if (!authed) {
    return (
      <div style={{ padding: 28 }}>
        <div
          style={{
            maxWidth: 400,
            background: ds.dark2,
            border: "1px solid #1e3a4f",
            borderRadius: 14,
            padding: "28px 28px 32px",
            boxShadow: "0 20px 60px rgba(0,0,0,0.35)",
          }}
        >
          <h2
            style={{
              fontFamily: ds.fontSyne,
              fontWeight: 700,
              fontSize: 20,
              color: "white",
              margin: "0 0 6px",
            }}
          >
            Superadmin Access
          </h2>
          <p style={{ fontSize: 13, color: "#7A9BAD", marginBottom: 20 }}>
            Enter your superadmin secret to continue.
          </p>

          <input
            type="password"
            placeholder="Superadmin secret"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleLogin()}
            style={{
              width: "100%",
              background: ds.dark,
              border: "1.5px solid #1e3a4f",
              borderRadius: 10,
              padding: "12px 14px",
              fontSize: 13,
              color: "white",
              fontFamily: ds.fontDm,
              outline: "none",
              marginBottom: 12,
              boxSizing: "border-box",
            }}
          />

          <button
            onClick={handleLogin}
            disabled={loginLoading}
            style={{
              width: "100%",
              background: loginLoading ? "#015F6B" : ds.teal,
              color: "white",
              border: "none",
              borderRadius: 10,
              padding: "13px",
              fontSize: 14,
              fontWeight: 600,
              fontFamily: ds.fontSyne,
              cursor: loginLoading ? "not-allowed" : "pointer",
            }}
          >
            {loginLoading ? "Verifying…" : "Unlock"}
          </button>

          {loginError && (
            <div style={{ marginTop: 14, fontSize: 13, color: "#FF9A9A" }}>
              ❌ {loginError}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Main form (authed) ────────────────────────────────────────────────────
  return (
    <div style={{ padding: 28 }}>
      <div
        style={{
          maxWidth: 560,
          background: ds.dark2,
          border: "1px solid #1e3a4f",
          borderRadius: 14,
          padding: "28px 28px 32px",
          boxShadow: "0 20px 60px rgba(0,0,0,0.35)",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            marginBottom: 6,
          }}
        >
          <h2
            style={{
              fontFamily: ds.fontSyne,
              fontWeight: 700,
              fontSize: 22,
              color: "white",
              margin: 0,
            }}
          >
            Create Organisation
          </h2>
          <button
            onClick={handleLogout}
            style={{
              background: "transparent",
              border: "1px solid #1e3a4f",
              borderRadius: 8,
              padding: "5px 12px",
              fontSize: 12,
              color: "#7A9BAD",
              cursor: "pointer",
              fontFamily: ds.fontDm,
            }}
          >
            Log out
          </button>
        </div>

        <p style={{ fontSize: 13, color: "#7A9BAD", marginBottom: 22 }}>
          Provision a new client workspace and owner account.
        </p>

        {/* Org Fields */}
        <SectionLabel text="Organisation Details" />
        <FormInput name="org_name" placeholder="Organisation Name" value={form.org_name} onChange={handleChange} />
        <FormInput name="slug" placeholder="Slug" value={form.slug} onChange={handleChange} disabled />
        <FormInput name="industry" placeholder="Industry" value={form.industry} onChange={handleChange} />
        <FormInput name="ticket_prefix" placeholder="Ticket Prefix" value={form.ticket_prefix} onChange={handleChange} disabled />

        <div style={{ height: 1, background: "#1e3a4f", margin: "18px 0" }} />

        {/* Owner Fields */}
        <SectionLabel text="Owner Account" />
        <FormInput name="owner_full_name" placeholder="Owner Name" value={form.owner_full_name} onChange={handleChange} />
        <FormInput name="owner_email" placeholder="Owner Email" value={form.owner_email} onChange={handleChange} />
        <FormInput name="owner_password" type="password" placeholder="Password" value={form.owner_password} onChange={handleChange} />

        {/* Submit */}
        <button
          onClick={handleSubmit}
          disabled={loading}
          style={{
            width: "100%",
            marginTop: 18,
            background: loading ? "#015F6B" : ds.teal,
            color: "white",
            border: "none",
            borderRadius: 10,
            padding: "14px",
            fontSize: 14,
            fontWeight: 600,
            fontFamily: ds.fontSyne,
            cursor: loading ? "not-allowed" : "pointer",
            transition: "background 0.2s",
          }}
        >
          {loading ? "Creating…" : "Create Organisation"}
        </button>

        {success && (
          <div style={{ marginTop: 16, fontSize: 13, color: "#7ee787" }}>
            ✅ Organisation created: <strong>{success.org_name}</strong>
          </div>
        )}

        {error && (
          <div style={{ marginTop: 16, fontSize: 13, color: "#FF9A9A" }}>
            ❌ {String(error)}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const generateSlug = (name) =>
  name.toLowerCase().trim().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "");

const generatePrefix = (name) =>
  name.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 3);

function SectionLabel({ text }) {
  return (
    <p
      style={{
        fontSize: 11,
        fontWeight: 600,
        color: "#3a5a6a",
        textTransform: "uppercase",
        letterSpacing: "1px",
        marginBottom: 8,
      }}
    >
      {text}
    </p>
  );
}

function FormInput({ name, value, onChange, placeholder, type = "text", disabled = false }) {
  return (
    <input
      name={name}
      type={type}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      disabled={disabled}
      style={{
        width: "100%",
        background: ds.dark,
        border: "1.5px solid #1e3a4f",
        borderRadius: 10,
        padding: "12px 14px",
        fontSize: 13,
        color: "white",
        fontFamily: ds.fontDm,
        outline: "none",
        marginBottom: 12,
        boxSizing: "border-box",
        opacity: disabled ? 0.6 : 1,
        cursor: disabled ? "not-allowed" : "text",
      }}
    />
  );
}
