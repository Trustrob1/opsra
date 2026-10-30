/**
 * frontend/src/pages/OwnerLandingPage.jsx
 * OWNER-LANDING-3 — public landing page + pricing for BUSINESS OWNERS (service businesses first).
 * Registered in App.jsx at `/business`. Standalone page (no AppShell, no staff auth).
 * Styles: OwnerLandingPage.css, scoped under `.ow`, every class prefixed `ow-`.
 * Replaces OWNER-LANDING-2 (git history has it). Design: Option A "Bright".
 *
 * THINGS TRUST EDITS (all at the top of this file):
 *   SALES_WA / DEMO_WA   international format, digits only. SALES_WA takes "Book a demo / Choose plan" messages,
 *                        DEMO_WA is the live demo number people message to try the bot.
 *   PLANS / ADDONS       monthly prices from, in naira. Setup fees are agreed separately and are NOT shown as numbers.
 *
 * IMAGES (frontend/public/images): usecase-coaches.jpg, usecase-counsellors.jpg, usecase-clinics.jpg,
 *   usecase-agencies.jpg, lead-center.jpg. The Lead Center screenshot shows real first names and amounts
 *   from a client org (used with that client's permission). Blur or replace it if that permission changes.
 *
 * No testimonials yet: the "founding clients" block replaces them. Add real quotes only when you have them.
 */
import { useEffect, useState } from "react";
import "./OwnerLandingPage.css";

const SALES_WA = "2348056055896";
const DEMO_WA = "14753274055";
const DEMO_DISPLAY = "+1 475 327 4055";

const waHref = (num, text) => `https://wa.me/${num}?text=${encodeURIComponent(text)}`;
const naira = (n) => `₦${n.toLocaleString("en-NG")}`;

const TITLE = "Opsra | Every enquiry answered. Every lead qualified.";
const DESC =
  "Opsra replies on WhatsApp the moment someone reaches out, asks the right questions, scores every lead and keeps your bookings and follow-ups moving. For coaches, counsellors, clinics, agencies and other service businesses.";

const PLANS = [
  {
    key: "starter",
    name: "Starter",
    line: "Never miss an enquiry",
    monthly: 50000,
    lead: "Included",
    items: [
      "Contact form on your website with an instant reply",
      "New WhatsApp messages saved as leads, with name and number",
      "See which page, product or button each lead came from",
      "An alert when a lead has waited too long for a reply",
      "A WhatsApp menu with set answers to common questions",
      "A simple page where you see all your leads",
    ],
  },
  {
    key: "growth",
    name: "Growth",
    line: "Turn more enquiries into sales",
    monthly: 100000,
    suggested: true,
    lead: "Everything in Starter, plus",
    items: [
      "Answers to common questions, written from your own information (monthly message limit applies)",
      "A few questions asked to each new lead, then scored hot, warm or cold",
      "Follow-up messages to people who go quiet",
      "Payment links sent inside the chat",
      "Your own WhatsApp number",
      "CRM to manage every lead and customer in one place",
      "A product catalog for your products and prices",
    ],
  },
  {
    key: "established",
    name: "Established",
    line: "Keep customers and run a team",
    monthly: 150000,
    lead: "Everything in Growth, plus",
    items: [
      "Both the product catalog and booking with reminders",
      "Bulk WhatsApp messaging to many customers at once, with opt-outs handled",
      "Review and repeat-purchase reminders",
      "A weekly summary of leads and sales sent to your WhatsApp",
      "Several staff replying from one shared inbox, with tasks and call logs",
    ],
  },
];

const ADDONS = [
  ["Support tickets", "₦15,000/month"],
  ["Renewals and win-back", "₦15,000/month"],
  ["Dashboard and ask-your-data", "₦10,000/month"],
  ["Extra staff member", "₦5,000/month each"],
  ["Extra WhatsApp number", "₦10,000/month"],
  ["Paid event or class funnel", "₦50,000 per event"],
];

const AUDIENCE = ["Coaches", "Counsellors", "Clinics", "Consultants", "Schools", "Agencies"];

const FEATURES = [
  ["01", "Greets every new contact", "A branded menu opens the conversation, even at 2am."],
  ["02", "Asks the right questions", "Five short questions capture what you need to know."],
  ["03", "Scores and sorts", "Hot, warm and cold leads land in the right pipeline stage."],
  ["04", "Books the consultation", "Confirmation and reminder messages go out on their own."],
  ["05", "Follows up for you", "Quiet leads get timely check-ins until they reply."],
  ["06", "Hands over when it matters", "You step in with the full conversation in front of you."],
];

const CAPS = [
  ["Hand off to a human", "Sensitive or complex? The conversation passes to you or your team with the full history attached.", "M5 5h14v10H10l-5 4z"],
  ["Lead scoring you control", "Define what a hot lead looks like for your business, and Opsra applies it to every enquiry.", "M4 19V9M10 19V5M16 19v-7M22 19H2"],
  ["Confirmations and reminders", "Approved WhatsApp templates confirm every booking and remind clients before the session.", "M3 8a3 3 0 013-3h12a3 3 0 013 3v10a3 3 0 01-3 3H6a3 3 0 01-3-3zM8 3v4M16 3v4M3 10h18"],
  ["Automatic nurture", "Check-ins, tips and stories go out on a schedule to leads who are not ready yet.", "M12 3a6 6 0 00-6 6c0 5-2 6-2 6h16s-2-1-2-6a6 6 0 00-6-6zM10 19a2 2 0 004 0"],
  ["Built for your team", "Assign leads, share one inbox and see who is handling what, with roles for each person.", "M9 12a4 4 0 100-8 4 4 0 000 8zM2 21c0-4 3-6 7-6s7 2 7 6M17 11a3 3 0 100-6M22 21c0-3-2-5-4-5.6"],
  ["Your data stays yours", "Each business has its own private workspace, number and customer records.", "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM9 12l2 2 4-4"],
];

const USECASES = [
  ["Coaches", "ow-c-blue", "Discovery calls, booked", "Turn curious messages into scheduled conversations without the back and forth.", "/images/usecase-coaches.jpg", "A coach taking notes during a one-to-one session", 547, 365],
  ["Counsellors", "ow-c-purple", "Gentle, careful intake", "Welcome new clients warmly, and hand sensitive messages to a person straight away.", "/images/usecase-counsellors.jpg", "A counsellor speaking with a young client in a calm room", 678, 452],
  ["Clinics", "ow-c-green", "Fewer missed appointments", "Capture requests at any hour and remind patients before they are due.", "/images/usecase-clinics.jpg", "A doctor smiling with a patient during a consultation", 638, 480],
  ["Agencies", "ow-c-orange", "Qualified before the first call", "Ask the right questions up front so every briefing starts with the facts.", "/images/usecase-agencies.jpg", "Two colleagues reviewing work on a tablet", 738, 414],
];

const CARDS = [
  ["Respond", "ow-t-blue", "Instant replies, 24/7", "A friendly menu greets every new contact, so nobody waits until morning to hear back."],
  ["Qualify", "ow-t-purple", "Smart questions, scored leads", "Short, friendly questions sort every lead into hot, warm or cold before you ever reply."],
  ["Book", "ow-t-orange", "Bookings that show up", "Confirmations and reminders go out automatically, so fewer sessions end in a no-show."],
  ["Follow up", "ow-t-green", "Nobody goes quiet", "Gentle check-ins nudge people who stopped replying, and hand back to you when they respond."],
];

const FAQ = [
  [
    "Does it cost extra when WhatsApp sends messages?",
    "WhatsApp charges per conversation for messages that you start. Each plan includes a starting allowance of these messages, and anything above it is billed at WhatsApp’s own price with no mark-up.",
  ],
  [
    "How long does set-up take?",
    "A full set-up takes about a week. Growth and Established also need Meta to approve your own WhatsApp number, and that can take longer.",
  ],
  [
    "What do I need to start?",
    "A phone number that can receive a WhatsApp code, your prices or services, and a few photos. We do the rest with you.",
  ],
  [
    "Can I stop?",
    "Plans run month to month after the first three months. Your website and your customer details stay yours.",
  ],
  [
    "Are my customers’ details mixed with other businesses?",
    "No. Each business is kept completely separate from every other business.",
  ],
  [
    "Does a person still talk to my customers?",
    "Yes. Hard questions go to you or your staff, and you choose how much is sent automatically and how much you approve first.",
  ],
];

function WaIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor" width="20" height="20">
      <path d="M12.04 2a9.9 9.9 0 0 0-8.5 14.95L2 22l5.2-1.5A9.9 9.9 0 1 0 12.04 2Zm5.8 14.1c-.25.7-1.4 1.3-1.95 1.35-.5.05-1.1.07-1.75-.1-.4-.12-.9-.3-1.55-.58-2.7-1.17-4.45-3.9-4.6-4.08-.13-.18-1.1-1.46-1.1-2.8 0-1.33.7-1.98.95-2.25.25-.27.55-.33.73-.33l.53.01c.17 0 .4-.06.62.48.25.57.84 1.98.9 2.12.08.15.12.32.02.5-.1.2-.15.32-.3.5l-.45.52c-.15.15-.3.31-.13.6.18.3.78 1.28 1.67 2.07 1.14 1 2.1 1.32 2.4 1.46.3.15.47.12.65-.07.18-.2.75-.87.95-1.17.2-.3.4-.25.67-.15.27.1 1.7.8 2 .95.3.15.5.22.57.35.07.12.07.7-.18 1.4Z" />
    </svg>
  );
}

function Logo({ light }) {
  return (
    <a className={`ow-mark${light ? " ow-mark-light" : ""}`} href="/business" aria-label="Opsra home">
      <svg width="34" height="34" viewBox="0 0 34 34" fill="none" aria-hidden="true">
        <rect x="1" y="1" width="32" height="32" rx="10" fill={light ? "#2467E3" : "#fff"} />
        <path d="M17 8c5 0 9 3.4 9 7.8 0 4.4-4 7.8-9 7.8-1 0-2-.1-2.9-.4L10 25l1-3.4C9.4 20.2 8 18.1 8 15.8 8 11.4 12 8 17 8z" stroke={light ? "#fff" : "#3E56B4"} strokeWidth="2.2" strokeLinejoin="round" />
      </svg>
      Opsra
    </a>
  );
}

export default function OwnerLandingPage() {
  const [solid, setSolid] = useState(false);

  useEffect(() => {
    const prevTitle = document.title;
    document.title = TITLE;
    let metaDesc = document.querySelector('meta[name="description"]');
    const prevDesc = metaDesc ? metaDesc.getAttribute("content") : null;
    if (!metaDesc) {
      metaDesc = document.createElement("meta");
      metaDesc.setAttribute("name", "description");
      document.head.appendChild(metaDesc);
    }
    metaDesc.setAttribute("content", DESC);

    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700&display=swap";
    document.head.appendChild(link);

    const ld = document.createElement("script");
    ld.type = "application/ld+json";
    ld.text = JSON.stringify({
      "@context": "https://schema.org",
      "@type": "FAQPage",
      mainEntity: FAQ.map(([q, a]) => ({
        "@type": "Question",
        name: q,
        acceptedAnswer: { "@type": "Answer", text: a },
      })),
    });
    document.head.appendChild(ld);

    const onScroll = () => setSolid(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });

    return () => {
      document.title = prevTitle;
      if (metaDesc && prevDesc !== null) metaDesc.setAttribute("content", prevDesc);
      link.remove();
      ld.remove();
      window.removeEventListener("scroll", onScroll);
    };
  }, []);

  const walkthrough = waHref(SALES_WA, "Hi, I'd like a 15-minute walkthrough of Opsra.");
  const demo = waHref(DEMO_WA, "Hi");

  return (
    <div className="ow">
      <a className="ow-skip" href="#plans">Skip to the plans</a>

      {/* ---------------- HERO ---------------- */}
      <div className="ow-hero">
        <header className={`ow-nav${solid ? " ow-solid" : ""}`}>
          <div className="ow-wrap ow-nav-row">
            <Logo />
            <nav aria-label="Main" className="ow-nav-links">
              <a href="#product">Product</a>
              <a href="#use-cases">Use cases</a>
              <a href="#plans">Pricing</a>
              <a href="#questions">Questions</a>
              <a className="ow-btn ow-btn-white ow-sm" href={walkthrough} target="_blank" rel="noopener noreferrer">Book a demo</a>
            </nav>
          </div>
        </header>

        <div className="ow-wrap ow-hero-grid">
          <div className="ow-hero-copy">
            <h1>Every enquiry answered. Every lead qualified.</h1>
            <p className="ow-lede">
              Opsra replies on WhatsApp the moment someone reaches out, asks the right questions, and hands
              you warm leads with a booking in the diary.
            </p>
            <div className="ow-cta-row">
              <a className="ow-btn ow-btn-white" href={demo} target="_blank" rel="noopener noreferrer">See it on WhatsApp</a>
              <a className="ow-btn ow-btn-ghost" href={walkthrough} target="_blank" rel="noopener noreferrer">Book a 15-minute walkthrough</a>
            </div>
          </div>
          <div className="ow-hero-phone" role="img" aria-label="Example WhatsApp conversation on a phone">
            <div className="ow-orb" aria-hidden="true" />
            <div className="ow-phone" aria-hidden="true">
              <div className="ow-screen">
                <div className="ow-ph-head">
                  <span className="ow-ph-av">YB</span>
                  <span><b>Your Business</b><small>Replies instantly</small></span>
                </div>
                <div className="ow-ph-body">
                  <p className="ow-b ow-b-out">Hello</p>
                  <p className="ow-b ow-b-in">Hi Ada! Welcome to Your Business. How can we help you today?</p>
                  <div className="ow-ph-opts">
                    <span>Book a free consultation</span>
                    <span>Our services</span>
                    <span>Something else</span>
                  </div>
                  <p className="ow-b ow-b-out">Book a free consultation</p>
                  <p className="ow-b ow-b-in">Great. First, which best describes you?</p>
                </div>
              </div>
            </div>
          </div>
        </div>
        <svg className="ow-curve" viewBox="0 0 1440 80" preserveAspectRatio="none" aria-hidden="true">
          <path d="M0 80V40C240 0 480 0 720 24s480 32 720 6V80z" fill="#fff" />
        </svg>
      </div>

      <main>
        {/* ---------------- AUDIENCE STRIP ---------------- */}
        <section className="ow-wrap ow-strip" aria-label="Who Opsra is for">
          <div>
            <p className="ow-eyebrow ow-eyebrow-mute">Built for service businesses</p>
            <ul className="ow-aud">
              {AUDIENCE.map((a) => <li key={a}>{a}</li>)}
            </ul>
          </div>
          <div className="ow-badge">
            <svg width="40" height="40" viewBox="0 0 40 40" fill="none" aria-hidden="true">
              <circle cx="20" cy="20" r="18" stroke="#2467E3" strokeWidth="2.5" />
              <path d="M12 20.5l5.5 5.5L28 15" stroke="#2467E3" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <div><b>Official WhatsApp Business API</b><span>Your number, your brand, your data</span></div>
          </div>
        </section>

        {/* ---------------- INSTANT CARDS ---------------- */}
        <section className="ow-wrap ow-sec" id="product" aria-labelledby="instant-h">
          <div className="ow-center">
            <h2 id="instant-h" className="ow-xl">No missed leads,<br /><span className="ow-purple">Go instant <i className="ow-toggle" aria-hidden="true"><b><svg width="22" height="22" viewBox="0 0 24 24" fill="#fff"><path d="M13 2L4 14h6l-1 8 9-12h-6z" /></svg></b></i></span></h2>
            <p className="ow-sub">One WhatsApp number that greets, qualifies, books and follows up, day and night, while you get on with the work.</p>
          </div>
          <div className="ow-cards">
            {CARDS.map(([k, tone, t, d]) => (
              <article key={k} className={`ow-card ${tone}`}>
                <p className="ow-eyebrow">{k}</p>
                <h3>{t}</h3>
                <p>{d}</p>
              </article>
            ))}
          </div>
        </section>

        {/* ---------------- USE CASES ---------------- */}
        <section className="ow-wrap ow-sec ow-sec-tight" id="use-cases" aria-labelledby="uc-h">
          <h2 id="uc-h" className="ow-h2">Made for people who sell time and trust.</h2>
          <div className="ow-uc">
            {USECASES.map(([label, tone, title, text, img, alt, w, h]) => (
              <article key={label} className="ow-uc-card">
                <img src={img} alt={alt} width={w} height={h} loading="lazy" />
                <div>
                  <p className={`ow-eyebrow ${tone}`}>{label}</p>
                  <h3>{title}</h3>
                  <p>{text}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        {/* ---------------- PIPELINE ---------------- */}
        <section className="ow-wrap ow-sec" aria-labelledby="pipe-h">
          <div className="ow-split">
            <div className="ow-split-l">
              <h2 id="pipe-h" className="ow-h2">A pipeline that runs itself.</h2>
              <p className="ow-sub ow-left">Every lead lands in one board with its score, its answers and its next step, so you always know who to talk to first.</p>
            </div>
            <ol className="ow-feat">
              {FEATURES.map(([n, t, d]) => (
                <li key={n}><span>{n}</span><div><b>{t}</b><p>{d}</p></div></li>
              ))}
            </ol>
          </div>
          <figure className="ow-shot">
            <div className="ow-shot-frame">
              <img src="/images/lead-center.jpg" alt="The Opsra Lead Center board showing leads by pipeline stage" width="1916" height="914" loading="lazy" />
            </div>
            <figcaption>The Lead Center: every enquiry, scored and staged.</figcaption>
          </figure>
        </section>

        {/* ---------------- DARK GRID ---------------- */}
        <section className="ow-dark" aria-labelledby="dark-h">
          <div className="ow-wrap ow-sec">
            <h2 id="dark-h" className="ow-h2 ow-light">More than a chatbot. A front desk that never closes.</h2>
            <div className="ow-caps">
              {CAPS.map(([t, d, path]) => (
                <article key={t}>
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#8FB0FF" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={path} /></svg>
                  <h3>{t}</h3>
                  <p>{d}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* ---------------- PRICING ---------------- */}
        <section className="ow-wrap ow-sec" id="plans" aria-labelledby="plans-h">
          <div className="ow-center">
            <p className="ow-eyebrow ow-t-blue">Plans and prices</p>
            <h2 id="plans-h" className="ow-h2">Start small. Grow when you are ready.</h2>
            <p className="ow-sub">Monthly plans in naira. Setup fees are agreed with you separately, based on what you need.</p>
          </div>
          <div className="ow-plans">
            {PLANS.map((p) => (
              <article key={p.key} className={`ow-plan${p.suggested ? " ow-plan-hi" : ""}`}>
                {p.suggested ? <span className="ow-pill">Suggested starting point</span> : <span className="ow-pill-gap" />}
                <h3>{p.name}</h3>
                <p className="ow-plan-line">{p.line}</p>
                <p className="ow-from">From</p>
                <p className="ow-price">{naira(p.monthly)}<small> / month</small></p>
                <p className="ow-setup">Setup fee negotiated separately</p>
                <a
                  className={`ow-btn ${p.suggested ? "ow-btn-blue" : "ow-btn-ink"}`}
                  href={waHref(SALES_WA, `Hi, I'm interested in the ${p.name} plan.`)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Choose {p.name}
                </a>
                <p className="ow-incl">{p.lead}</p>
                <ul>
                  {p.items.map((it) => (
                    <li key={it}>
                      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M4 10.5l4 4 8-9" stroke="#2467E3" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                      <span>{it}</span>
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
          <div className="ow-addons">
            <h3>Add what you need</h3>
            <ul>
              {ADDONS.map(([n, price]) => (
                <li key={n}><b>{n}</b> &middot; {price}</li>
              ))}
            </ul>
          </div>
          <p className="ow-fine">
            Prices are in naira and may change before you start. WhatsApp charges per conversation for messages you start.
            Each plan includes a starting allowance, and anything above it is billed at WhatsApp&rsquo;s own price with no mark-up.
          </p>
        </section>

        {/* ---------------- FOUNDING CLIENTS ---------------- */}
        <section className="ow-wrap ow-sec ow-sec-tight" aria-labelledby="found-h">
          <h2 id="found-h" className="ow-h2 ow-center">Be one of our first clients.</h2>
          <p className="ow-sub ow-center-block">We are onboarding a small group of founding clients and setting Opsra up for each of them personally.</p>
          <div className="ow-found">
            <article className="ow-found-card ow-found-blue">
              <p className="ow-eyebrow ow-t-blue">Founding client</p>
              <h3>We set it up with you.</h3>
              <ul>
                <li>A WhatsApp menu written in your voice</li>
                <li>Qualification questions and lead scoring built for your work</li>
                <li>Booking confirmations and reminders switched on</li>
                <li>Direct support from the team that built it</li>
              </ul>
              <a className="ow-btn ow-btn-blue" href={walkthrough} target="_blank" rel="noopener noreferrer">Book a walkthrough</a>
            </article>
            <article className="ow-found-card ow-found-purple">
              <p className="ow-eyebrow ow-t-purple">Live demo</p>
              <h3>Try it before you decide.</h3>
              <p>Send a message to our demo number and go through the same menu and questions your clients would.</p>
              <p className="ow-demo-num">{DEMO_DISPLAY}</p>
              <a className="ow-btn ow-btn-ink" href={demo} target="_blank" rel="noopener noreferrer">Open WhatsApp</a>
            </article>
          </div>
        </section>

        {/* ---------------- FAQ ---------------- */}
        <section className="ow-wrap ow-sec ow-sec-tight" id="questions" aria-labelledby="faq-h">
          <h2 id="faq-h" className="ow-h2 ow-center">Before you message us.</h2>
          <div className="ow-faq">
            {FAQ.map(([q, a]) => (
              <details key={q}>
                <summary>{q}</summary>
                <p>{a}</p>
              </details>
            ))}
          </div>
        </section>

        {/* ---------------- CTA BAND ---------------- */}
        <section className="ow-wrap ow-cta-sec" aria-labelledby="cta-h">
          <div className="ow-cta-band">
            <h2 id="cta-h">Message our demo. See your own front desk in 30 seconds.</h2>
            <div className="ow-cta-row ow-cta-center">
              <a className="ow-btn ow-btn-white" href={demo} target="_blank" rel="noopener noreferrer"><WaIcon />Open WhatsApp demo</a>
              <a className="ow-btn ow-btn-ghost" href={walkthrough} target="_blank" rel="noopener noreferrer">Book a walkthrough</a>
            </div>
          </div>
        </section>
      </main>

      {/* ---------------- FOOTER ---------------- */}
      <footer className="ow-foot">
        <div className="ow-wrap">
          <div className="ow-foot-row">
            <div>
              <Logo light />
              <p>WhatsApp-first enquiries, leads and bookings for service businesses.</p>
            </div>
            <div>
              <b>Product</b>
              <a href="#product">How it works</a>
              <a href="#plans">Pricing</a>
              <a href="#questions">Questions</a>
            </div>
            <div>
              <b>Company</b>
              <a href={walkthrough} target="_blank" rel="noopener noreferrer">Book a walkthrough</a>
              <a href={demo} target="_blank" rel="noopener noreferrer">Try the demo</a>
            </div>
            <div>
              <b>Legal</b>
              <a href="/privacy">Privacy</a>
              <a href="/terms">Terms</a>
            </div>
          </div>
          <p className="ow-legal">
            Opsra is a product of Ovaloop Technologies. WhatsApp is a trademark of Meta Platforms, Inc. Opsra is not affiliated with or endorsed by Meta.
          </p>
        </div>
      </footer>
    </div>
  );
}
