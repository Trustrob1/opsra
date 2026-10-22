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
 * Prices: the totals come from the same pricing engine as the checkout (GET /api/v1/public/host/pricing), never typed here.
 * UI-2: the full line-by-line breakdown lives in the portal (Pricing); this page shows totals only and says the domain is included.
 */
import { useEffect, useRef } from "react";
import { AuthPanel } from "./SiteLandingPage";
import { DomainChecker, usePricing } from "./HostDomainPricing";
import "./SiteLandingPage.css";
import "./HostLandingPage.css";

/** HOST-4: signed in on this browser before? Then the nav offers "Open my portal" (the portal restores the session itself). */
const SIGNED_IN = (() => { try { return window.localStorage.getItem("opsra_signed_in") === "1"; } catch { return false; } })();

const TITLE = "Host your website with Opsra | Upload, preview, go live";
const DESC =
  "Made your website with AI or a builder? Upload it to Opsra, preview it, then put it online on your own domain. Domain name, SSL and DNS are included.";

const INCLUDED = [
  ["Aa", "Domain name", "Your address on the internet, like brightpath.com.ng. It is what people type to find you.", "Renews yearly", "renew"],
  ["Hs", "Hosting", "The always-on computer where your site lives, so it is open day and night.", "Renews yearly", "renew"],
  ["Ss", "SSL padlock", "The little padlock in the browser. It tells visitors your site is safe to use.", "Free with hosting", "free"],
  ["Dn", "DNS", "The signpost that sends visitors from your address to your site. We set it up and look after it.", "Managed for you", "free"],
];

const STEPS = [
  ["01", "Pick your address", "Check a new one is free, or use one you already own."],
  ["02", "Create your account", "Just your email. No password to remember."],
  ["03", "Upload and preview", "Drop in your site and see it on phone and computer."],
  ["04", "Go live", "You see the exact price first. Pay, and your site is online."],
];

const FAQ = [
  [
    "What files can I upload?",
    "A single-page website as a .zip with index.html at the top, or one .html file. Images, CSS, JavaScript and fonts are fine. Multi-page sites are not supported yet.",
  ],
  [
    "Do I have to buy my address (domain) from Opsra?",
    "No. A new domain is included in your price, but if you already bought one somewhere else, choose I already own my domain at checkout. You pay for hosting only, then add one DNS record where you manage the domain.",
  ],
  [
    "What happens when it is time to renew?",
    "Your domain and hosting renew together once a year. We email and WhatsApp you before it is due, and you pay from your Opsra account. If you own your domain elsewhere, your registrar keeps renewing that part.",
  ],
  [
    "Will my JavaScript work?",
    "Yes, on your live domain. During the preview, scripts run in a locked box that cannot touch your account. If something is unsafe, we tell you what to fix and nothing is published.",
  ],
  [
    "Do you have discount codes?",
    "Yes. Type your code into the Discount code box at checkout, after your preview is ready and before you pay. The new total shows at once.",
  ],
  [
    "Can I change the site later?",
    "Yes. Upload new files for the same site at any time. Before it is paid for, the new version replaces the preview straight away. After it is live, your update is saved and our team publishes it.",
  ],
];

const naira = (n) => `₦${Math.round(Number(n) || 0).toLocaleString("en-NG")}`;

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

  const endings = pricing.data ? pricing.data.endings : null;
  const own = pricing.data ? pricing.data.own_domain : null;

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
                <a href="#included">What you get</a>
              </li>
              <li>
                <a href="#pricing">Pricing</a>
              </li>
              <li>
                <a href="#how">How it works</a>
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
            {SIGNED_IN ? (
              <a className="sl-btn sl-teal sl-sm" href="/b/login">
                Open my portal
              </a>
            ) : (
              <a className="sl-btn sl-teal sl-sm" href="#start" onClick={goSignIn}>
                Sign in to upload
              </a>
            )}
          </div>
        </div>
      </header>

      <main id="main">
        <section className="sl-hero sl-h2-hero" id="top">
          <div className="sl-wrap sl-h2-herogrid">
            <div className="sl-h2-copy">
              <span className="sl-badge">
                <i aria-hidden="true"></i>Made your website with AI or a builder?
              </span>
              <h1>
                Put it online. <span className="sl-accent">On your own domain.</span>
              </h1>
              <p className="sl-lede">
                Upload your finished site, see a preview, then go live. We take care of the technical parts. No coding needed.
              </p>
              <div className="sl-prompt-row">
                <a className="sl-btn sl-teal" href="#start" onClick={goSignIn}>
                  Sign in and upload
                </a>
                <a className="sl-btn sl-light sl-h-outline" href="#included">
                  What do I get?
                </a>
              </div>
              <ul className="sl-h2-checks">
                <li>Domain name included</li>
                <li>Preview before you pay</li>
                <li>Or use a domain you already own</li>
              </ul>
            </div>
            <div className="sl-h2-card" id="domain">
              <h2>Is your web address free?</h2>
              <p className="sl-h2-cardsub">Type the name you want. No account needed.</p>
              <DomainChecker endings={endings ? endings.map((e) => e.tld) : null} hidePrice />
              <p className="sl-h2-own">
                Already bought your address somewhere else? Skip this.{" "}
                <button type="button" className="sl-h2-link" onClick={useOwnDomain}>
                  Just host my site
                </button>
              </p>
            </div>
          </div>
        </section>

        <section className="sl-h2-included" id="included">
          <div className="sl-wrap">
            <div className="sl-head">
              <span className="sl-label">What you get</span>
              <h2>Four things that put your site online.</h2>
              <p>All included. Here is what each one means, in plain words.</p>
            </div>
            <ul className="sl-h2-tiles">
              {INCLUDED.map(([glyph, h, p, tag, tone]) => (
                <li key={h} className="sl-h2-tile">
                  <span className="sl-h2-ico" aria-hidden="true">
                    {glyph}
                  </span>
                  <h3>{h}</h3>
                  <p>{p}</p>
                  <span className={`sl-h2-tag sl-h2-${tone}`}>{tag}</span>
                </li>
              ))}
            </ul>
            <div className="sl-h2-why">
              <b>Why every year?</b>
              <p>
                Think of it like a shop. The address is registered one year at a time, and the building is kept running for you.
                Renew once a year and your site stays online. We remind you before it is due.
              </p>
            </div>
          </div>
        </section>

        <section className="sl-pricing" id="pricing">
          <div className="sl-wrap">
            <div className="sl-head">
              <span className="sl-label">Pricing</span>
              <h2>One price. Your domain name is included.</h2>
              <p>You do not buy the domain separately. It comes with your hosting package, along with SSL and DNS.</p>
            </div>
            {pricing.error && <p className="sl-err">{pricing.error}</p>}
            {!pricing.data && !pricing.error && <p className="sl-h-muted">Loading prices…</p>}
            {pricing.data && (
              <div className="sl-h2-prices">
                {endings.map((e) => (
                  <div key={e.tld} className="sl-h2-price">
                    <h3>{e.tld}</h3>
                    <b>{naira(e.first_year.total)}</b>
                    <span>first year · then {naira(e.renewal.total)} a year</span>
                    <span className="sl-h2-tag sl-h2-free">Domain name included</span>
                  </div>
                ))}
                {own && (
                  <div className="sl-h2-price sl-h2-priceown">
                    <h3>I own a domain</h3>
                    <b>{naira(own.first_year)}</b>
                    <span>first year · then {naira(own.renewal)} a year</span>
                    <p>Bought it elsewhere? Bring it. You only pay for hosting.</p>
                    <button type="button" className="sl-h2-link" onClick={useOwnDomain}>
                      Use my own domain
                    </button>
                  </div>
                )}
              </div>
            )}
            <p className="sl-h-muted">
              SSL padlock and DNS are included in every option. Got a discount code? Use it at checkout. The full breakdown is
              shown after you sign in.
            </p>
          </div>
        </section>

        <section className="sl-how" id="how">
          <div className="sl-wrap">
            <div className="sl-head">
              <span className="sl-label">How it works</span>
              <h2>Four simple steps.</h2>
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
              <h2 id="hsih">Ready to put your site online?</h2>
              <p className="sl-sub">
                New here? Create an account in a minute. Already have one? Sign in with your email and we send you a code,
                or use your WhatsApp number instead. You will see the exact price before you pay.
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

      <div className="sl-h2-sticky">
        <a className="sl-btn sl-teal" href="#start" onClick={goSignIn}>
          Sign in and upload
        </a>
      </div>
    </div>
  );
}
