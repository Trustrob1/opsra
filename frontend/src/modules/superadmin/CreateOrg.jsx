import { useState } from "react";
import { createOrganisation } from "../../services/superadmin.service";
import { ds } from "../../utils/ds";

export default function CreateOrg() {
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

  const handleChange = (e) => {
    const { name, value } = e.target;

    let updated = {
      ...form,
      [name]: value,
    };

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
      console.log("FULL ERROR:", err.response?.data);
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
      <h2
        style={{
          fontFamily: ds.fontSyne,
          fontWeight: 700,
          fontSize: 22,
          color: "white",
          margin: "0 0 6px",
        }}
      >
        Create Organisation
      </h2>

      <p
        style={{
          fontSize: 13,
          color: "#7A9BAD",
          marginBottom: 22,
        }}
      >
        Provision a new client workspace and owner account.
      </p>

      {/* Org Fields */}
      <SectionLabel text="Organisation Details" />

      <FormInput name="org_name" placeholder="Organisation Name" value={form.org_name} onChange={handleChange} />
      <FormInput name="slug" placeholder="Slug" value={form.slug} onChange={handleChange} disabled />
      <FormInput name="industry" placeholder="Industry" value={form.industry} onChange={handleChange} />
      <FormInput name="ticket_prefix" placeholder="Ticket Prefix" value={form.ticket_prefix} onChange={handleChange} disabled/>
      

      {/* Divider */}
      <div style={{ height: 1, background: "#1e3a4f", margin: "18px 0" }} />

      {/* Owner Fields */}
      <SectionLabel text="Owner Account" />

      <FormInput name="owner_full_name" placeholder="Owner Name" value={form.owner_full_name} onChange={handleChange} />
      <FormInput name="owner_email" placeholder="Owner Email" value={form.owner_email} onChange={handleChange} />
      <FormInput
        name="owner_password"
        type="password"
        placeholder="Password"
        value={form.owner_password}
        onChange={handleChange}
      />

      {/* Button */}
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

      {/* Success */}
      {success && (
        <div
          style={{
            marginTop: 16,
            fontSize: 13,
            color: "#7ee787",
          }}
        >
          ✅ Organisation created: <strong>{success.org_name}</strong>
        </div>
      )}

      {/* Error */}
      {error && (
        <div
          style={{
            marginTop: 16,
            fontSize: 13,
            color: "#FF9A9A",
          }}
        >
          ❌ {String(error)}
        </div>
      )}
    </div>
  </div>
);
}

const generateSlug = (name) =>
  name
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "");

const generatePrefix = (name) =>
  name
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "")
    .slice(0, 3);

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

function FormInput({
  name,
  value,
  onChange,
  placeholder,
  type = "text",
  disabled = false,
}) {
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

        // ✅ NEW additions
        opacity: disabled ? 0.6 : 1,
        cursor: disabled ? "not-allowed" : "text",
      }}
    />
  );
}