/**
 * frontend/src/pages/TermsOfService.jsx
 * Terms of Service — Opsra by Ovaloop Technologies
 *
 * Static page — linked from:
 *   1. Login page footer
 *   2. Onboarding flow
 *
 * Audience: Organisations (businesses) subscribing to Opsra.
 * Governing law: Federal Republic of Nigeria.
 */
import React, { useEffect } from "react";

const LEGAL_EMAIL = "legal@ovaloop.com";

export default function TermsOfService() {
  useEffect(() => {
    document.body.style.background = "#ffffff";
    return () => { document.body.style.background = ""; };
  }, []);

  return (
    <div
      style={{
        maxWidth: 720,
        margin: "0 auto",
        padding: "48px 24px",
        fontFamily: "Inter, system-ui, sans-serif",
        color: "#1a1a2e",
        lineHeight: 1.7,
        background: "#ffffff",
        minHeight: "100vh",
      }}
    >
      {/* Header */}
      <div style={{ marginBottom: 40 }}>
        <p style={{ fontSize: 13, color: "#6b7280", marginBottom: 8 }}>
          Legal — Opsra by Ovaloop Technologies
        </p>
        <h1 style={{ fontSize: 28, fontWeight: 700, margin: "0 0 8px" }}>
          Terms of Service
        </h1>
        <p style={{ fontSize: 14, color: "#6b7280" }}>
          Last updated:{" "}
          {new Date().toLocaleDateString("en-NG", {
            year: "numeric",
            month: "long",
            day: "numeric",
          })}
        </p>
      </div>

      <Section title="1. About These Terms">
        <p>
          These Terms of Service ("Terms") govern your organisation's access to and
          use of Opsra, a CRM and customer engagement platform developed and operated
          by Ovaloop Technologies ("we", "us", or "Opsra"). By accessing or using
          Opsra, your organisation agrees to be bound by these Terms.
        </p>
        <p>
          If you are accepting these Terms on behalf of an organisation, you confirm
          that you have the authority to bind that organisation. These Terms apply to
          all users within your organisation who access Opsra.
        </p>
      </Section>

      <Section title="2. The Service">
        <p>
          Opsra provides a cloud-based CRM platform that includes lead management,
          WhatsApp Business messaging, support ticketing, renewal tracking, task
          management, and operations analytics. The platform is provided on a
          subscription basis.
        </p>
        <p>
          We reserve the right to modify, suspend, or discontinue any part of the
          service at any time with reasonable notice. We will not be liable to you or
          any third party for any modification, suspension, or discontinuation of the
          service.
        </p>
      </Section>

      <Section title="3. Accounts and Access">
        <p>
          Your organisation is responsible for maintaining the security of all user
          accounts created under your subscription. You must ensure that:
        </p>
        <ul>
          <li>All account credentials are kept confidential and not shared externally.</li>
          <li>Only authorised personnel within your organisation access the platform.</li>
          <li>You notify us immediately of any suspected unauthorised access.</li>
          <li>All users comply with these Terms and applicable law.</li>
        </ul>
        <p>
          We reserve the right to suspend or terminate accounts where we have
          reasonable grounds to suspect misuse, fraud, or breach of these Terms.
        </p>
      </Section>

      <Section title="4. Subscription and Payment">
        <p>
          Access to Opsra is provided on a paid subscription basis. Subscription
          fees, billing cycles, and payment terms are agreed at the time of
          onboarding and may be updated with 30 days' written notice.
        </p>
        <ul>
          <li>Fees are non-refundable except where required by applicable law or agreed otherwise in writing.</li>
          <li>Failure to pay subscription fees may result in suspension or termination of access.</li>
          <li>All fees are quoted and payable in Nigerian Naira (NGN) unless otherwise agreed.</li>
          <li>We reserve the right to adjust pricing with 30 days' advance notice to your registered contact.</li>
        </ul>
      </Section>

      <Section title="5. Acceptable Use">
        <p>
          You agree to use Opsra only for lawful business purposes. You must not use
          the platform to:
        </p>
        <ul>
          <li>Send unsolicited, misleading, or harassing messages to contacts.</li>
          <li>Violate any applicable law, regulation, or third-party rights.</li>
          <li>Transmit malware, spam, or any content that disrupts the platform.</li>
          <li>Reverse engineer, copy, or resell any part of the Opsra platform.</li>
          <li>Use the platform in a manner that exceeds your subscription tier or granted permissions.</li>
          <li>Store or process sensitive personal data categories (e.g. health, financial, biometric data) without explicit written consent from us.</li>
        </ul>
        <p>
          Violation of this section may result in immediate suspension of your
          account without refund.
        </p>
      </Section>

      <Section title="6. WhatsApp Messaging">
        <p>
          Opsra connects to the WhatsApp Business API via Meta's approved partner
          infrastructure. By using the WhatsApp messaging features, you agree to:
        </p>
        <ul>
          <li>Comply with Meta's WhatsApp Business Policy and Terms of Service at all times.</li>
          <li>Only message contacts who have consented to receive communications from your organisation.</li>
          <li>Honour opt-out requests (STOP) immediately and not re-engage opted-out contacts without fresh consent.</li>
          <li>Take full responsibility for the content of messages sent through the platform.</li>
        </ul>
        <p>
          We are not liable for any suspension of your WhatsApp Business Account by
          Meta resulting from your misuse of the messaging features.
        </p>
      </Section>

      <Section title="7. Data and Privacy">
        <p>
          You retain ownership of all data you input into Opsra ("Your Data"). By
          using the platform, you grant us a limited licence to store, process, and
          transmit Your Data solely to provide the service.
        </p>
        <p>
          As the Data Controller under Nigeria's National Data Protection Regulation
          (NDPR), you are responsible for ensuring your use of Opsra complies with
          applicable data protection law, including obtaining valid consent from your
          contacts before processing their personal data.
        </p>
        <p>
          Opsra acts as a Data Processor on your behalf. Our data processing
          practices are described in our{" "}
          <a href="/privacy" style={{ color: "#4f46e5" }}>
            Privacy Notice
          </a>
          .
        </p>
      </Section>

      <Section title="8. Intellectual Property">
        <p>
          All intellectual property in the Opsra platform — including software,
          design, trademarks, and documentation — is owned by Ovaloop Technologies.
          Nothing in these Terms transfers any intellectual property rights to you.
        </p>
        <p>
          You retain full ownership of Your Data and any content your organisation
          creates within the platform.
        </p>
      </Section>

      <Section title="9. Confidentiality">
        <p>
          Each party agrees to keep confidential any non-public information received
          from the other party in connection with Opsra ("Confidential Information"),
          and not to disclose it to third parties without prior written consent.
          This obligation survives termination of these Terms for a period of three
          years.
        </p>
      </Section>

      <Section title="10. Limitation of Liability">
        <p>
          To the maximum extent permitted by applicable law, Ovaloop Technologies
          shall not be liable for any indirect, incidental, special, or consequential
          damages arising from your use of Opsra, including but not limited to loss
          of revenue, data, or business opportunity.
        </p>
        <p>
          Our total aggregate liability to you for any claims arising under these
          Terms shall not exceed the total fees paid by your organisation to Opsra in
          the three months preceding the claim.
        </p>
      </Section>

      <Section title="11. Termination">
        <p>
          Either party may terminate the subscription with 30 days' written notice.
          We may terminate immediately if you breach these Terms materially and fail
          to remedy the breach within 7 days of written notice.
        </p>
        <p>
          Upon termination, your access to the platform will cease and Your Data will
          be retained for 30 days before being permanently deleted, unless you
          request an earlier export or deletion.
        </p>
      </Section>

      <Section title="12. Governing Law">
        <p>
          These Terms are governed by the laws of the Federal Republic of Nigeria.
          Any disputes arising under these Terms shall be subject to the exclusive
          jurisdiction of the courts of Lagos State, Nigeria.
        </p>
      </Section>

      <Section title="13. Changes to These Terms">
        <p>
          We may update these Terms from time to time. We will notify your
          organisation's registered contact by email at least 14 days before material
          changes take effect. Continued use of Opsra after the effective date
          constitutes acceptance of the updated Terms.
        </p>
      </Section>

      <Section title="14. Contact Us">
        <p>
          For questions about these Terms, please contact our legal team at{" "}
          <a href={`mailto:${LEGAL_EMAIL}`} style={{ color: "#4f46e5" }}>
            {LEGAL_EMAIL}
          </a>
          .
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
          These Terms of Service apply to all organisations accessing Opsra, a
          product of <strong>Ovaloop Technologies</strong>. Registered in Nigeria.
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
