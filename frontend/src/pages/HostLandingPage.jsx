/**
 * frontend/src/pages/HostLandingPage.jsx
 * HOST-1 - public "Host with Opsra" page at /host, for people who build websites outside Opsra and only want hosting.
 *
 * Sign in or create an account here (the same passwordless builder accounts as /sites), then the builder portal opens on
 * "Host a site" where the upload happens. Nothing can be uploaded before signing in, so the drop area on this page is a
 * button that takes you to the sign-in box (and says so).
 *
 * The sign-in link arrives in WhatsApp or email and opens /b/login in the portal. To land on the right screen we leave a
 * small, non-secret note in localStorage (opsra_entry=host) that the portal reads once. If storage is blocked the person
 * lands on My sites, which has the same "Host a site" tab.
 *
 * Styles: SiteLandingPage.css (scoped under .sl) plus HostLandingPage.css (classes prefixed sl-h-).
 * Prices: the table comes from the same pricing engine as the checkout (GET /api/v1/public/host/pricing), never typed here.
 */
import { useEffect, useRef } from "react";
import { AuthPanel } from "./SiteLandingPage";
import { DomainChecker, PricingTable, usePricing } from "./HostDomainPricing";
import "./SiteLandingPage.css";
import "./HostLandingPage.css";

const TITLE = "Host your website with Opsra | Upload, preview, go live";
const DESC =
  "Built your website somewhere else? Upload the finished files to Opsra, preview them, then put the site on your own domain with hosting that renews simply.";

const STEPS = [
  ["01", "Sort out your domain", "Want a new address? Check it is free right here, no account needed. Already own one at QServers or elsewhere? Skip the check."],
  ["02", "Create your account", "Enter your name, email and WhatsApp number. No password: we send a one-time code or link."],
  ["03", "Drop in your files", "Upload a .zip (with index.html inside) or one .html file. We check it and show you a preview straight away."],
  ["04", "Pay and go live", "Enter your domain, see the exact price, pay securely. If you own the domain, add one DNS record and your site goes live on it."],
];

const WHAT = [
  ["One page per site", "A single-page website: index.html plus its images, styles, scripts and fonts."],
  ["Up to 25 MB", "A .zip of up to 25 MB, or a single .html file."],
  ["Your scripts work", "JavaScript runs on your own domain. We block risky patterns, like code that sends visitors’ data elsewhere."],
  ["Preview before paying", "You see it exactly as visitors will, on phone and desktop, before you spend anything."],
];

const FAQ = [
  [
    "Do I have to build my site on Opsra?",
    "No. This is for sites you made yourself, or had made, in any tool. You upload the finished files and Opsra hosts them.",
  ],
  [
    "What can I upload?",
    "A single-page website as a .zip with index.html at the top, or one .html file. Images, CSS, JavaScript and fonts are fine. Multi-page sites are not supported yet.",
  ],
  [
    "Will my JavaScript work?",
    "Yes, on your live domain. During the preview, scripts run in a locked box that cannot touch your account. If something is unsafe, such as hidden code that sends data to another site, we tell you what to fix and nothing is saved.",
  ],
  [
    "How much does it cost?",
    "The same hosting and domain pricing as any Opsra site, shown in the price table above: domain, hosting with SSL and DNS management, and a setup fee where one applies. You see the exact total for your own domain before you pay.",
  ],
  [
    "I already bought my domain somewhere else. Do I still have to check it?",
    "No. The availability check is only for a new domain. If you own yours, choose I already own my domain at checkout. You pay for hosting only, then add one DNS record where you manage the domain. Your site goes live once it points to us, and your registrar keeps renewing the domain.",
  ],
  [
    "Do you have discount codes?",
    "Yes. If you have a code, type it into the Discount code box on the checkout screen, after your preview is ready and before you pay. The new total shows at once. A code takes money off your first payment and does not apply to renewals.",
  ],
  [
    "Can I change the site later?",
    "Yes. Upload new files for the same site at any time. Before it is paid for, the new version replaces the preview straight away. After it is live, your update is saved and our team publishes it.",
  ],
  [
    "Is this only for people who build websites for clients?",
    "No. It works for your own site too. The account you create is the same builder account Opsra uses everywhere.",
  ],
];

export default function HostLandingPage() {
  const inputRef = useRef(null);
  const pricing = usePricing();

  useEffect(() => {
    try {
      window.localStorage.setItem("opsra_entry", "host");
    } catch {
      /* storage blocked: the portal still has a Host a site tab */
    }
    const prevTitle = document.title;
    document.title = TITLE;
    const meta = document.querySelector('meta[name="description"]');
    const prevDesc = meta ? meta.getAttribute("content") : null;
    if (meta) meta.setAttribute("content", DESC);
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href =
      "https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap";
    document.head.appendChild(link);
    if (window.location.hash === "#signin") goSignIn();
    return () => {
      document.title = prevTitle;
      if (meta && prevDesc !== null) meta.setAttribute("content", prevDesc);
      link.remove();
    };
  }, []);

  // Owners of a domain skip the availability check; the portal's checkout opens on "I already own my domain".
  function useOwnDomain() {
    try {
      window.localStorage.setItem("opsra_host_mode", "own");
    } catch {
      /* storage blocked: they can still pick the option at checkout */
    }
    goSignIn();
  }

  function goSignIn() {
    window.setTimeout(() => {
      const el = document.getElementById("start");
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      if (inputRef.current) inputRef.current.focus({ preventScroll: true });
    }, 50);
  }

  return (
    <div className="sl">
      <a className="sl-skip" href="#main">
        Skip to content
      </a>
      <header className="sl-nav sl-solid">
        <div className="sl-wrap">
          <a className="sl-mark" href="/host" aria-label="Opsra, host your website">
            <i aria-hidden="true"></i>opsra<small>Hosting</small>
          </a>
          <nav aria-label="Main">
            <ul>
              <li>
                <a href="#domain">Check domain</a>
              </li>
              <li>
                <a href="#how">How it works</a>
              </li>
              <li>
                <a href="#pricing">Pricing</a>
              </li>
              <li>
                <a href="#what">What we host</a>
              </li>
              <li>
                <a href="#faq">Questions</a>
              </li>
              <li>
                <a href="/sites">Build with Opsra</a>
              </li>
            </ul>
          </nav>
          <div className="sl-right">
            <a className="sl-btn sl-teal sl-sm" href="#start" onClick={goSignIn}>
              Sign in to upload
            </a>
          </div>
        </div>
      </header>

      <main id="main">
        <section className="sl-hero" id="top">
          <div className="sl-wrap">
            <span className="sl-badge">
              <i aria-hidden="true"></i>For websites you built somewhere else
            </span>
            <h1>
              Already built it? <span className="sl-accent">We’ll host it.</span>
            </h1>
            <p className="sl-lede">
              Upload your finished website, check it in a live preview, then put it on your own domain. No rebuilding, no new
              tools to learn.
            </p>

            <button type="button" className="sl-h-drop" onClick={goSignIn} aria-label="Sign in to upload your website">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M12 16V4M7 9l5-5 5 5M4 20h16" />
              </svg>
              <b>Drop your website here</b>
              <span>.zip or .html · you’ll sign in first, then upload in one step</span>
            </button>

            <p className="sl-h-callout">
              <b>Want a new domain?</b> Check it is free below, with no account. <b>Already own one?</b> No check needed, you just point it to us.
            </p>
            <div className="sl-prompt-row" style={{ justifyContent: "center", marginTop: 22 }}>
              <a className="sl-btn sl-teal" href="#domain">
                Check my domain
              </a>
              <a className="sl-btn sl-light sl-h-outline" href="#start" onClick={goSignIn}>
                Sign in or create an account
              </a>
            </div>
            <div className="sl-meta">
              <span>Preview before you pay</span>
              <span>Your own domain</span>
              <span>No password</span>
            </div>
          </div>
        </section>

        <section className="sl-sites" id="domain">
          <div className="sl-wrap">
            <div className="sl-head">
              <span className="sl-label">Step 1</span>
              <h2>Is your domain name free?</h2>
              <p>Check it before you upload. If it’s taken, we’ll suggest names that are free.</p>
            </div>
            <DomainChecker endings={pricing.data ? pricing.data.endings.map((e) => e.tld) : null} />
          </div>
        </section>

        <section className="sl-how" id="how">
          <div className="sl-wrap">
            <div className="sl-head">
              <span className="sl-label">Four steps</span>
              <h2>From finished files to a live site.</h2>
            </div>
            <ol className="sl-h-steps">
              {STEPS.map(([n, h, p]) => (
                <li key={n}>
                  <span className="sl-label">{n}</span>
                  <h3>{h}</h3>
                  <p>{p}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="sl-pricing" id="pricing">
          <div className="sl-wrap">
            <div className="sl-head">
              <span className="sl-label">Pricing</span>
              <h2>What it costs, line by line.</h2>
              <p>Domain, hosting, SSL and DNS in one price. Got a discount code? Use it at checkout. Nothing hidden.</p>
            </div>
            <PricingTable data={pricing.data} error={pricing.error} onUseOwn={useOwnDomain} />
          </div>
        </section>

        <section className="sl-sites" id="what">
          <div className="sl-wrap">
            <div className="sl-head">
              <span className="sl-label">What we host</span>
              <h2>Simple, and clear about the limits.</h2>
            </div>
            <div className="sl-h-grid">
              {WHAT.map(([h, p]) => (
                <div key={h} className="sl-h-card">
                  <h3>{h}</h3>
                  <p>{p}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="sl-faq" id="faq">
          <div className="sl-wrap">
            <h2>Good questions.</h2>
            <div className="sl-faq-list">
              {FAQ.map(([q, a]) => (
                <details key={q}>
                  <summary>{q}</summary>
                  <p>{a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section className="sl-signin" id="start" aria-labelledby="hsih">
          <div className="sl-wrap sl-signin-grid">
            <div>
              <span className="sl-label">Ready when you are</span>
              <h2 id="hsih">Sign in and upload your site.</h2>
              <p className="sl-sub">
                New here? Create an account in a minute. Already have one? Sign in with your email and we send you a code,
                or use your WhatsApp number instead. You’ll land on the upload screen.
              </p>
            </div>
            <div className="sl-box-in" id="signin">
              <span className="sl-label">Your account</span>
              <h3>Sign in or create your account.</h3>
              <AuthPanel inputRef={inputRef} />
            </div>
          </div>
        </section>
      </main>

      <footer className="sl-foot">
        <div className="sl-wrap sl-foot-row">
          <span className="sl-foot-mark">opsra</span>
          <span>© {new Date().getFullYear()} Opsra</span>
          <div>
            <a href="/privacy">Privacy</a>
            <a href="/terms">Terms</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
