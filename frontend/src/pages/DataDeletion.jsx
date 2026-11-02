/**
 * frontend/src/pages/DataDeletion.jsx
 * Public page: how to ask for personal data to be deleted.
 * Used as the "User data deletion" instructions URL in the Meta app settings.
 */
import React from "react";

const PRIVACY_EMAIL = "info@opsra.com.ng";

export default function DataDeletion() {
  return (
    <div
      style={{
        maxWidth: 720,
        margin: "0 auto",
        padding: "48px 24px",
        fontFamily: "Inter, system-ui, sans-serif",
        color: "#1a1a2e",
        lineHeight: 1.7,
      }}
    >
      <p style={{ fontSize: 13, color: "#6b7280", marginBottom: 8 }}>Opsra by Coreai Cloud Tech</p>
      <h1 style={{ fontSize: 28, fontWeight: 700, margin: "0 0 24px" }}>Delete your data</h1>

      <p>
        Opsra helps businesses reply to people on WhatsApp, Instagram and Messenger. If a business
        using Opsra holds your details and you want them deleted, here is how.
      </p>

      <h2 style={{ fontSize: 18, fontWeight: 600, marginTop: 32 }}>How to request deletion</h2>
      <ol>
        <li>
          Email{" "}
          <a href={`mailto:${PRIVACY_EMAIL}?subject=Data%20deletion%20request`} style={{ color: "#4f46e5" }}>
            {PRIVACY_EMAIL}
          </a>{" "}
          with the subject "Data deletion request".
        </li>
        <li>
          Tell us the name of the business you spoke to and the WhatsApp number or Instagram /
          Messenger account you used, so we can find your records.
        </li>
        <li>
          We may ask you to confirm it is you, for example by messaging from the same account.
        </li>
      </ol>

      <h2 style={{ fontSize: 18, fontWeight: 600, marginTop: 32 }}>What gets deleted</h2>
      <ul>
        <li>Your name, phone number and any other contact details we hold.</li>
        <li>Your message history with the business, including any files you sent.</li>
        <li>Notes, tags and bookings linked to you.</li>
      </ul>
      <p>
        We may keep limited records that the law requires us to keep, such as payment records.
        Backups are cleared on their normal cycle.
      </p>

      <h2 style={{ fontSize: 18, fontWeight: 600, marginTop: 32 }}>How long it takes</h2>
      <p>We complete verified requests within <strong>30 days</strong>.</p>

      <h2 style={{ fontSize: 18, fontWeight: 600, marginTop: 32 }}>Stop messages instead</h2>
      <p>
        To stop WhatsApp messages without deleting anything, reply{" "}
        <code style={{ background: "#f3f4f6", padding: "1px 6px", borderRadius: 4 }}>STOP</code> to any
        message. Read our <a href="/privacy" style={{ color: "#4f46e5" }}>privacy notice</a> for the full
        picture.
      </p>
    </div>
  );
}
