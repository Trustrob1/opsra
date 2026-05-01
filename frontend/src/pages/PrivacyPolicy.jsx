/**
 * frontend/src/pages/PrivacyPolicy.jsx
 * 9E-I — I2: NDPR Privacy Notice
 *
 * Static page — linked from:
 *   1. Login page footer
 *   2. First-contact WhatsApp message footnote
 *
 * Content is intentionally written at the ORG level:
 * "the Organisation" = the business using Opsra, not Opsra/Ovaloop itself.
 * This is correct under NDPR — Opsra is a data processor; the org is the controller.
 */
import React from "react";

const PRIVACY_EMAIL = "privacy@ovaloop.com"; // Replace per org in production

export default function PrivacyPolicy() {
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
      {/* Header */}
      <div style={{ marginBottom: 40 }}>
        <p style={{ fontSize: 13, color: "#6b7280", marginBottom: 8 }}>
          Privacy Notice — Powered by Opsra
        </p>
        <h1 style={{ fontSize: 28, fontWeight: 700, margin: "0 0 8px" }}>
          How We Use Your Personal Data
        </h1>
        <p style={{ fontSize: 14, color: "#6b7280" }}>
          Last updated: {new Date().toLocaleDateString("en-NG", { year: "numeric", month: "long", day: "numeric" })}
        </p>
      </div>

      <Section title="Who is the Data Controller?">
        <p>
          The organisation you interacted with (the business that contacted you or
          whose product or service you enquired about) is the Data Controller
          responsible for your personal information. Opsra, a product of Ovaloop
          Technologies, provides the software platform they use — Opsra acts as a
          Data Processor on their behalf.
        </p>
      </Section>

      <Section title="What Data We Collect">
        <p>When you interact with an organisation using Opsra, the following
        personal data may be collected and stored:</p>
        <ul>
          <li><strong>Name</strong> — your full name as provided or captured from your WhatsApp profile.</li>
          <li><strong>Phone number</strong> — used to identify you and deliver messages.</li>
          <li><strong>WhatsApp number</strong> — used for outbound and inbound messaging.</li>
          <li><strong>Email address</strong> — if provided via web form or manually by staff.</li>
          <li><strong>Business details</strong> — business name, type, and location, where relevant.</li>
          <li><strong>WhatsApp messages</strong> — inbound and outbound message content is stored to
            maintain conversation history for the organisation's staff.</li>
          <li><strong>Interaction history</strong> — calls logged, notes added, and stage changes
            in the sales or support pipeline.</li>
        </ul>
      </Section>

      <Section title="How Your Data is Used">
        <p>Your data is used exclusively by the organisation you interacted with for the following purposes:</p>
        <ul>
          <li>Managing your enquiry or support request through their CRM system.</li>
          <li>Sending you WhatsApp messages related to your enquiry, account, or subscription.</li>
          <li>Automated follow-up messages and reminders relevant to your relationship with the organisation.</li>
          <li>Analytics and reporting to help the organisation improve their service.</li>
          <li>Renewal reminders, payment notifications, and account updates.</li>
        </ul>
        <p>
          Your data is <strong>never sold</strong> to third parties, and is not used for
          advertising outside the organisation's direct communications with you.
        </p>
      </Section>

      <Section title="Who Your Data is Shared With">
        <p>Your personal data may be shared with the following service providers
          who process it on behalf of the organisation:</p>
        <ul>
          <li><strong>Ovaloop Technologies / Opsra</strong> — the CRM platform provider.</li>
          <li><strong>Supabase</strong> — secure cloud database hosting.</li>
          <li><strong>Meta (WhatsApp)</strong> — WhatsApp Business API for message delivery.</li>
          <li><strong>Resend</strong> — email notification delivery.</li>
          <li><strong>Render</strong> — cloud hosting infrastructure.</li>
        </ul>
        <p>All service providers are bound by data processing agreements and are
        prohibited from using your data for their own purposes.</p>
      </Section>

      <Section title="How Long Your Data is Retained">
        <p>
          Your data is retained for as long as you have an active relationship with the
          organisation, and for a further period as configured by the organisation (typically
          up to 12 months after last interaction). After the retention period, data is
          automatically soft-deleted or anonymised.
        </p>
        <p>
          You may request earlier erasure at any time — see <em>Your Rights</em> below.
        </p>
      </Section>

      <Section title="Your Rights Under NDPR">
        <p>Under Nigeria's National Data Protection Regulation (NDPR) and applicable
          data protection law, you have the following rights:</p>
        <ul>
          <li>
            <strong>Right to access</strong> — request a copy of the personal data held about you.
          </li>
          <li>
            <strong>Right to rectification</strong> — ask for inaccurate data to be corrected.
          </li>
          <li>
            <strong>Right to erasure</strong> — request that your personal data be permanently deleted.
          </li>
          <li>
            <strong>Right to object</strong> — object to processing for marketing or automated
            follow-up purposes.
          </li>
          <li>
            <strong>Right to opt out of WhatsApp messages</strong> — reply{" "}
            <code style={{ background: "#f3f4f6", padding: "1px 6px", borderRadius: 4 }}>STOP</code>{" "}
            to any WhatsApp message to stop all future messages immediately. You can opt back in
            by replying{" "}
            <code style={{ background: "#f3f4f6", padding: "1px 6px", borderRadius: 4 }}>START</code>.
          </li>
        </ul>
      </Section>

      <Section title="How to Exercise Your Rights">
        <p>
          To exercise any of the rights above, contact the organisation directly. If you
          are unable to reach them, you may contact the Opsra data privacy team at{" "}
          <a href={`mailto:${PRIVACY_EMAIL}`} style={{ color: "#4f46e5" }}>
            {PRIVACY_EMAIL}
          </a>
          , referencing the organisation name and your phone number.
        </p>
        <p>
          We will respond to all verified requests within <strong>30 days</strong> in
          accordance with NDPR requirements.
        </p>
      </Section>

      <Section title="Contact the Data Controller">
        <p>
          For questions about how your data is used, contact the organisation whose
          product or service you enquired about directly. Their contact details were
          provided in the original communication you received.
        </p>
      </Section>

      {/* Footer */}
      <div
        style={{
          borderTop: "1px solid #e5e7eb",
          marginTop: 48,
          paddingTop: 24,
          fontSize: 13,
          color: "#9ca3af",
        }}
      >
        <p>
          This privacy notice was generated by{" "}
          <strong>Opsra by Coreai Cloud Tech</strong>. It covers data
          processing activities performed on behalf of the Data Controller
          (the organisation you interacted with). Opsra is a data processor,
          not the data controller.
        </p>
      </div>
    </div>
  );
}

/**
 * Reusable section wrapper.
 */
function Section({ title, children }) {
  return (
    <section style={{ marginBottom: 36 }}>
      <h2
        style={{
          fontSize: 18,
          fontWeight: 600,
          marginBottom: 12,
          paddingBottom: 8,
          borderBottom: "2px solid #e5e7eb",
        }}
      >
        {title}
      </h2>
      <div style={{ fontSize: 15 }}>{children}</div>
    </section>
  );
}
