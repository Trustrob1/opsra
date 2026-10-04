/**
 * frontend/src/pages/SiteSignUpForm.jsx
 * SITE-WEB-1 - "Create account" on the /sites landing page. Two steps:
 *   1. details (name, email, WhatsApp number, who it is for, terms)  -> a 6-digit code is emailed
 *   2. the code -> the account is created and the browser opens /b/login?t=<token>, the same page a link from
 *      WhatsApp opens, so the session token is made there and never stored here.
 * Uses the landing page's own .sl-* styles (SiteLandingPage.css).
 */
import { useId, useState } from "react";
import { startSignup, verifySignup, errorMessage } from "../services/builder_portal.service";

const ARROW = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s.]{2,}$/;

export default function SiteSignUpForm() {
  const uid = useId();
  const [stage, setStage] = useState("details"); // details | sending | code | verifying
  const [form, setForm] = useState({ full_name: "", email: "", phone: "", account_type: "builder", accept_terms: false, website: "" });
  const [code, setCode] = useState("");
  const [requestId, setRequestId] = useState("");
  const [emailHint, setEmailHint] = useState("");
  const [error, setError] = useState("");

  const set = (k) => (e) => {
    const v = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [k]: v }));
    setError("");
  };

  async function submitDetails(e) {
    e.preventDefault();
    const digits = form.phone.replace(/\D/g, "");
    if (form.full_name.trim().length < 2) return setError("Please enter your name.");
    if (!EMAIL_RE.test(form.email.trim())) return setError("Please enter a valid email address.");
    if (digits.length < 9 || digits.length > 15) return setError("Enter your WhatsApp number, for example 0803 123 4567.");
    if (!form.accept_terms) return setError("Please accept the terms to continue.");
    setStage("sending");
    setError("");
    try {
      const res = await startSignup({ ...form, full_name: form.full_name.trim(), email: form.email.trim(), phone: form.phone.trim() });
      setRequestId(res.request_id);
      setEmailHint(res.email_hint || "");
      setStage("code");
    } catch (err) {
      setStage("details");
      setError(errorMessage(err, "We couldn’t start that just now. Please try again in a moment."));
    }
  }

  async function submitCode(e) {
    e.preventDefault();
    const digits = code.replace(/\D/g, "");
    if (digits.length !== 6) return setError("Enter the 6-digit code from your email.");
    setStage("verifying");
    setError("");
    try {
      const res = await verifySignup(requestId, digits);
      window.location.assign(`/b/login?t=${encodeURIComponent(res.token)}`);
    } catch (err) {
      setStage("code");
      setError(errorMessage(err, "That didn’t work. Check the code and try again."));
    }
  }

  if (stage === "code" || stage === "verifying") {
    return (
      <form className="sl-sform" onSubmit={submitCode} noValidate>
        <label htmlFor={`${uid}-code`}>Enter your code</label>
        <input
          id={`${uid}-code`}
          className="sl-code"
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={7}
          placeholder="000000"
          value={code}
          autoFocus
          onChange={(e) => {
            setCode(e.target.value);
            setError("");
          }}
        />
        <p className="sl-hint">
          We emailed a 6-digit code to {emailHint || "you"}. It works for 15 minutes. If it hasn’t arrived, check spam.
          Already have an account? We sent a sign-in link instead.
        </p>
        <div aria-live="polite">
          <p className="sl-err">{error}</p>
        </div>
        <button className="sl-btn sl-teal" type="submit" disabled={stage === "verifying"}>
          <span>{stage === "verifying" ? "Checking…" : "Create my account"}</span>
          {ARROW}
        </button>
        <button
          type="button"
          className="sl-linkbtn"
          onClick={() => {
            setStage("details");
            setCode("");
            setError("");
          }}
        >
          Use different details
        </button>
      </form>
    );
  }

  return (
    <form className="sl-sform" onSubmit={submitDetails} noValidate>
      <label htmlFor={`${uid}-name`}>Your name</label>
      <input id={`${uid}-name`} type="text" autoComplete="name" value={form.full_name} onChange={set("full_name")} />

      <label htmlFor={`${uid}-email`}>Email</label>
      <input id={`${uid}-email`} type="email" autoComplete="email" inputMode="email" value={form.email} onChange={set("email")} />

      <label htmlFor={`${uid}-phone`}>WhatsApp number</label>
      <input id={`${uid}-phone`} type="tel" autoComplete="tel" inputMode="tel" placeholder="0803 123 4567" value={form.phone} onChange={set("phone")} />

      <fieldset className="sl-radios" style={{ border: 0, padding: 0, margin: "6px 0 0" }}>
        <legend className="sl-legend">I’ll be building</legend>
        <label className="sl-radio">
          <input type="radio" name={`${uid}-type`} checked={form.account_type === "builder"} onChange={() => setForm((f) => ({ ...f, account_type: "builder" }))} />
          <span>
            Sites for clients
            <small>You make websites for other people and sell them.</small>
          </span>
        </label>
        <label className="sl-radio">
          <input type="radio" name={`${uid}-type`} checked={form.account_type === "owner"} onChange={() => setForm((f) => ({ ...f, account_type: "owner" }))} />
          <span>
            My own business site
            <small>You’re building the website for your own brand.</small>
          </span>
        </label>
      </fieldset>

      <label className="sl-check">
        <input type="checkbox" checked={form.accept_terms} onChange={set("accept_terms")} />
        <span>
          I agree to the <a href="/terms" target="_blank" rel="noopener noreferrer">terms</a> and{" "}
          <a href="/privacy" target="_blank" rel="noopener noreferrer">privacy policy</a>.
        </span>
      </label>

      {/* honeypot: real people never see or fill this */}
      <div className="sl-hp" aria-hidden="true">
        <label htmlFor={`${uid}-web`}>Website</label>
        <input id={`${uid}-web`} type="text" tabIndex={-1} autoComplete="off" value={form.website} onChange={set("website")} />
      </div>

      <p className="sl-hint">Your first 3 sites are free to build and preview. We’ll email a code to confirm it’s you.</p>
      <div aria-live="polite">
        <p className="sl-err">{error}</p>
      </div>
      <button className="sl-btn sl-teal" type="submit" disabled={stage === "sending"}>
        <span>{stage === "sending" ? "Sending your code…" : "Email me a code"}</span>
        {ARROW}
      </button>
    </form>
  );
}
