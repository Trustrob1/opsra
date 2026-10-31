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
 * No testimonials yet: the "Set up with you" + live demo block stands in. Add real quotes only when you have them.
 * MOBILE (max-width 820px): full-screen photo hero with animated notifications, marquee strip, swipe cards,
 *   2x2 photo tiles, lead-journey animation, plan tabs. All CSS-driven from the same markup.
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
      "Both the product catalog and booking with reminders (500 bookings a month included)",
      "Bulk WhatsApp messaging to many customers at once, with opt-outs handled",
      "Review and repeat-purchase reminders",
      "A weekly summary of leads and sales sent to your WhatsApp",
      "Several staff replying from one shared inbox, with tasks and call logs",
    ],
  },
];

const ADDONS = [
  ["Booking with reminders", "\u20a625,000", "per month", "Includes 100 bookings a month, then \u20a6100 for each extra. Included in Established (500 a month)."],
  ["Support tickets", "\u20a615,000", "per month", ""],
  ["Extra user", "\u20a65,000", "per month, each", "2 users are included in every plan"],
  ["Extra WhatsApp number", "\u20a610,000", "per month", ""],
  ["Paid event or class funnel", "\u20a650,000", "per event", ""],
];

// Costs billed on top of the plan. They come out of a prepaid credit balance the business tops up.
const CREDIT_USES = [
  ["Confirmations and reminders", "Booking messages to your clients", "At Meta\u2019s price", "blue", "Meta\u2019s price"],
  ["Broadcasts and follow-ups", "Marketing messages cost more with Meta", "Meta\u2019s price + small fee", "purple", "Meta\u2019s price + fee"],
  ["AI replies", "Each reply the AI writes for you", "Small amount per reply", "grey", "Small credit each"],
];
const CREDIT_PACKS = [[5000, 0, "\u20a65k"], [10000, 0, "\u20a610k"], [25000, 2, "\u20a625k"], [50000, 5, "\u20a650k"]];

const AUDIENCE = ["Coaches", "Counsellors", "Clinics", "Consultants", "Schools", "Agencies"];
const AUDIENCE_ICONS = {
  Coaches: (<><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="4.5" /><circle cx="12" cy="12" r="1" fill="currentColor" /></>),
  Counsellors: <path d="M4 6a2 2 0 012-2h12a2 2 0 012 2v8a2 2 0 01-2 2h-7l-4 4v-4H6a2 2 0 01-2-2z" />,
  Clinics: <path d="M12 5v14M5 12h14" />,
  Consultants: (<><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2M3 13h18" /></>),
  Schools: (<><path d="M2 9l10-5 10 5-10 5z" /><path d="M6 11v5c0 1.5 3 3 6 3s6-1.5 6-3v-5" /></>),
  Agencies: (<><path d="M12 3l9 5-9 5-9-5z" /><path d="M3 13l9 5 9-5" /></>),
};

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
    "Yes. WhatsApp message fees are set by Meta, not by Opsra, and they are not part of the plan price. You pay them from a prepaid credit balance that you top up (from ₦5,000), and AI replies use that credit too. Booking messages are passed on at Meta’s price; marketing messages carry a small Opsra fee.",
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

const ONE_ICONS = {
  chat: <path d="M5 5h14v10H10l-5 4z" />,
  sheet: <><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M4 10h16M4 15h16M10 4v16" /></>,
  cal: <><rect x="3" y="5" width="18" height="16" rx="3" /><path d="M8 3v4M16 3v4M3 10h18" /></>,
  note: <><path d="M6 4h12v12l-4 4H6z" /><path d="M14 20v-4h4" /></>,
  card: <><rect x="3" y="6" width="18" height="13" rx="3" /><path d="M3 11h18" /></>,
}
// [icon, tint, ink, title, before-caption, after-caption]
const ONE = [
  ['chat', '#E4EDFD', '#2467E3', 'Messages', 'in a chat app', ['Chat', 'Welcome menu answered']],
  ['sheet', '#DDF3E6', '#176A3C', 'Leads', 'in a spreadsheet', ['Lead', 'Scored Hot, with their answers']],
  ['cal', '#FDE9DD', '#A4430F', 'Bookings', 'in a calendar', ['Booking', 'Consultation, Fri 3:00pm']],
  ['note', '#EFE6FB', '#5E1BB8', 'Follow-ups', 'in your head', ['Follow-up', 'Reminder sent automatically']],
  ['card', '#FDE3E3', '#A32020', 'Payments', 'somewhere else', ['Payment', 'Link sent in the chat']],
]
const ONE_OFF = [0, 70, 20, 90, 40]
function OneIcon({ k, col, size }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={col} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ONE_ICONS[k]}</svg>
  )
}

export default function OwnerLandingPage() {
  const [solid, setSolid] = useState(false);
  const [plan, setPlan] = useState("growth");
  const [menu, setMenu] = useState(false);

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
        <img className="ow-hero-bg" src="/images/usecase-coaches.jpg" alt="" aria-hidden="true" width="547" height="365" />
        <div className="ow-hero-tint" aria-hidden="true" />
        <header className={`ow-nav${solid ? " ow-solid" : ""}`}>
          <div className="ow-wrap ow-nav-row">
            <Logo />
            <button type="button" className="ow-burger" aria-label={menu ? "Close menu" : "Open menu"} aria-expanded={menu} onClick={() => setMenu((m) => !m)}>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                {menu ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
              </svg>
            </button>
            <nav aria-label="Main" className={`ow-nav-links${menu ? " ow-open" : ""}`} onClick={() => setMenu(false)}>
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
              <span className="ow-lede-long">
                Opsra replies on WhatsApp the moment someone reaches out, asks the right questions, and hands
                you warm leads with a booking in the diary.
              </span>
              <span className="ow-lede-short">Instant WhatsApp replies that turn messages into booked consultations.</span>
            </p>
            <div className="ow-cta-row">
              <a className="ow-btn ow-btn-white" href={demo} target="_blank" rel="noopener noreferrer">See it on WhatsApp</a>
              <a className="ow-btn ow-btn-ghost ow-hide-m" href={walkthrough} target="_blank" rel="noopener noreferrer">Book a 15-minute walkthrough</a>
            </div>
          </div>
          <div className="ow-notifs" aria-hidden="true">
            <div className="ow-nt ow-nt1">
              <span className="ow-nt-ic ow-ic-blue"><i className="ow-ring" /><svg width="22" height="22" viewBox="0 0 24 24" fill="#fff"><path d="M13 2L4 14h6l-1 8 9-12h-6z" /></svg></span>
              <div><small>New enquiry</small><b>Ada O. messaged you</b></div>
              <em>Hot</em>
            </div>
            <div className="ow-nt ow-nt2">
              <span className="ow-nt-ic ow-ic-purple"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round"><rect x="3" y="5" width="18" height="16" rx="3" /><path d="M8 3v4M16 3v4M3 10h18" /></svg></span>
              <div><small>Booked</small><b>Consultation, Fri 3:00pm</b></div>
            </div>
            <div className="ow-nt ow-nt3">
              <span className="ow-nt-ic ow-ic-green"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7" /></svg></span>
              <div><small>Reminder sent</small><b>Ada confirmed for Friday</b></div>
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
        {/* ---------------- AUDIENCE MARQUEE (phones) ---------------- */}
        <section className="ow-marq" aria-label="Who Opsra is for">
          <p className="ow-marq-eye">Built for service businesses</p>
          <ul className="ow-marq-grid">
            {AUDIENCE.map((a) => (
              <li key={a}>
                <span className="ow-marq-ic">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{AUDIENCE_ICONS[a]}</svg>
                </span>
                {a}
              </li>
            ))}
          </ul>
        </section>

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

        {/* ---------------- ONE PLACE ---------------- */}
        <section className="ow-wrap ow-sec ow-one-sec" aria-labelledby="one-h">
          <div className="ow-one">
            <div className="ow-one-head">
              <p className="ow-eyebrow ow-c-blue">One place</p>
              <h2 id="one-h">Your business shouldn&apos;t live in <s>five apps</s>.</h2>
              <p>Messages in a chat app. Leads in a spreadsheet. Bookings in a calendar. Follow-ups in your head. Payments somewhere else. Opsra puts it all in one place.</p>
            </div>
            <div className="ow-one-stage">
              <p className="ow-eyebrow ow-one-lbl ow-one-lbl-l">Before</p>
              <p className="ow-eyebrow ow-one-lbl ow-one-lbl-r ow-c-blue">With Opsra</p>
              <div className="ow-one-tiles">
                {ONE.map(([k, bg, col, t, sub], n) => (
                  <div key={k} className="ow-one-tilewrap" style={{ '--off': ONE_OFF[n] + 'px', '--rot': [-2, 1.5, -1.5, 2, -1][n] + 'deg' }}>
                    <div className="ow-one-tile" style={{ '--d': n * 0.12 + 's', '--dot': col }}>
                      <span className="ow-one-ic" style={{ background: bg }}><OneIcon k={k} col={col} size={20} /></span>
                      <span><b>{t}</b><span>{sub}</span></span>
                    </div>
                  </div>
                ))}
              </div>
              <svg className="ow-one-lines" viewBox="0 0 100 438" preserveAspectRatio="none" aria-hidden="true">
                {ONE.map(([k, , col], n) => {
                  const y1 = 33 + 92 * n
                  const y2 = 105 + 58 * n
                  return <path key={k} d={`M0 ${y1} C55 ${y1} 45 ${y2} 100 ${y2}`} stroke={col} strokeWidth="2.2" strokeDasharray="6 9" strokeLinecap="round" fill="none" opacity=".75" vectorEffect="non-scaling-stroke" />
                })}
              </svg>
              <div className="ow-one-arrow" aria-hidden="true">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M6 13l6 6 6-6" /></svg>
              </div>
              <div className="ow-one-card">
                <div className="ow-one-who"><b>Ada O.</b><span>Hot</span></div>
                {ONE.map(([k, bg, col, , , [t, sub]], n) => (
                  <div key={k} className="ow-one-row" style={{ '--d': n * 0.12 + 's' }}>
                    <span className="ow-one-ic ow-one-ic-s" style={{ background: bg }}><OneIcon k={k} col={col} size={18} /></span>
                    <span><b>{t}</b><span>{sub}</span></span>
                    <svg width="19" height="19" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M4 10.5l4 4 8-9" stroke="#2467E3" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                  </div>
                ))}
                <p className="ow-one-foot">One record. Everything in it.</p>
              </div>
            </div>
            <p className="ow-one-note">You still decide who gets a call.</p>
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
              <div className="ow-journey" aria-hidden="true">
                <div className="ow-j-stages"><span className="ow-j1">New</span><span className="ow-j2">Qualified</span><span className="ow-j3">Booked</span><span className="ow-j4">Enrolled</span></div>
                <div className="ow-j-track">
                  <div className="ow-j-card"><b>Ada O.</b><small>Wants coaching</small><em>Hot</em></div>
                </div>
              </div>
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
          <div className="ow-tabs" role="tablist" aria-label="Plans">
            {PLANS.map((p) => (
              <button key={p.key} type="button" role="tab" aria-selected={plan === p.key} className={plan === p.key ? "ow-tab-on" : ""} onClick={() => setPlan(p.key)}>{p.name}</button>
            ))}
          </div>
          <div className="ow-plans">
            {PLANS.map((p) => (
              <article key={p.key} className={`ow-plan${p.suggested ? " ow-plan-hi" : ""}${plan === p.key ? " ow-plan-on" : ""}`}>
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
            <ul className="ow-addon-grid">
              {ADDONS.map(([n, price, unit, note]) => (
                <li key={n}>
                  <span className="ow-addon-n">{n}</span>
                  <b className="ow-addon-p">{price}</b>
                  <span className="ow-addon-u">{unit}</span>
                  {note ? <span className="ow-addon-note">{note}</span> : null}
                </li>
              ))}
            </ul>
          </div>
          <div className="ow-credit" id="usage-costs">
            <div className="ow-credit-l">
              <p className="ow-credit-eye">Billed separately</p>
              <h3>The plan is a fixed fee. Messages and AI run on credit.</h3>
              <p className="ow-credit-sub ow-d">WhatsApp messaging and AI replies are usage costs, so they are not part of the plan price. You top up a prepaid balance and they come out of it.</p>
              <p className="ow-credit-sub ow-m">These usage costs are not in the plan price. You top up a prepaid balance and they come out of it.</p>
              <ol className="ow-credit-steps">
                <li><span>1</span>Top up credit, from {naira(5000)}</li>
                <li><span>2</span>Messages and AI replies draw from it</li>
                <li><span>3</span>Watch your balance, set a monthly limit, top up when you need to</li>
              </ol>
            </div>
            <div className="ow-credit-r">
              <div className="ow-credit-card">
                <p className="ow-credit-cap">What uses credit</p>
                {CREDIT_USES.map(([n, d, tag, tone, short]) => (
                  <div className="ow-credit-row" key={n}>
                    <div><b>{n}</b><span className="ow-d">{d}</span></div>
                    <em className={`ow-tag ow-tag-${tone}`}><span className="ow-d">{tag}</span><span className="ow-m">{short}</span></em>
                  </div>
                ))}
              </div>
              <p className="ow-credit-cap ow-m ow-credit-cap2">Top up credit</p>
              <ul className="ow-packs" aria-label="Credit top-ups">
                {CREDIT_PACKS.map(([amt, bonus, short]) => (
                  <li key={amt} className={bonus ? "ow-pack-bonus" : ""}>
                    <b><span className="ow-d">{naira(amt)}</span><span className="ow-m">{short}</span></b>
                    <span><span className="ow-d">{bonus ? `+${bonus}% bonus` : "Top-up"}</span><span className="ow-m">{bonus ? `+${bonus}%` : "\u00a0"}</span></span>
                  </li>
                ))}
              </ul>
              <p className="ow-credit-note ow-d">A business with many bookings and conversations will use more credit than a small one, because it sends more messages.</p>
              <p className="ow-credit-note ow-m">Busy businesses send more messages, so they use more credit. Set a monthly limit any time.</p>
            </div>
          </div>
          <p className="ow-fine">
            Prices are in naira and may change before you start. Every plan includes 2 users (one admin and one staff member); extra users are &#8358;5,000 per month each.
            WhatsApp message fees are set by Meta and paid from your credit balance, and AI replies also use credit. Domain and hosting fees, if you order a website, are billed separately.
          </p>
        </section>

        {/* ---------------- SETUP + DEMO ---------------- */}
        <section className="ow-wrap ow-sec ow-sec-tight" aria-labelledby="found-h">
          <h2 id="found-h" className="ow-h2 ow-center">Set up with you, not left to you.</h2>
          <p className="ow-sub ow-center-block">Every business gets a setup built around how it actually works, and a team to call when something needs changing.</p>
          <div className="ow-found">
            <article className="ow-found-card ow-found-blue">
              <p className="ow-eyebrow ow-t-blue">Done with you</p>
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
              <a className="ow-btn ow-btn-ghost ow-hide-m" href={walkthrough} target="_blank" rel="noopener noreferrer">Book a walkthrough</a>
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
            WhatsApp is a trademark of Meta Platforms, Inc. Opsra is not affiliated with or endorsed by Meta.
          </p>
        </div>
      </footer>
    </div>
  );
}
