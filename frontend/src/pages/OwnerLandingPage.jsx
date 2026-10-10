/**
 * frontend/src/pages/OwnerLandingPage.jsx
 * OWNER-LANDING-1 (+ OWNER-LANDING-2 visual redesign) — public landing page + pricing for BUSINESS OWNERS.
 * Registered in App.jsx at `/business`. Standalone page (no AppShell, no staff auth).
 * Styles: OwnerLandingPage.css, scoped under `.ow`, every class prefixed `ow-`.
 *
 * ONE page on purpose: the only action is "Message us on WhatsApp", so the pricing
 * sits inside the page (#plans). Share https://<host>/business#plans.
 *
 * ---------------------------------------------------------------------------
 * HERO PHOTO: save the image as  frontend/public/images/owner-hero.jpg  (about 1600px wide,
 * under 300 KB). Until the file exists the hero shows a branded panel instead (no broken image).
 * The photo is an AI-generated illustration, not a real client; the page says so beside it.
 *
 * THINGS TRUST EDITS (all at the top of this file):
 *   WHATSAPP_NUMBER   international format, digits only.
 *   WEBSITES / PLANS / ADDONS   PLACEHOLDER PRICES. Provisional, to be adjusted.
 *   SHOW_SAMPLE_QUOTE  false = no testimonial shown. A made-up SAMPLE quote exists
 *                      only to preview the layout. NEVER ship it as a real quote:
 *                      replace QUOTE with a real customer's words and set REAL_QUOTE true.
 * ---------------------------------------------------------------------------
 */
import { useEffect, useRef, useState } from "react";
import "./OwnerLandingPage.css";

const WHATSAPP_NUMBER = "2348056055896";

const waHref = (text) =>
  `https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(text)}`;

const TITLE = "Opsra | Never lose a customer message again";
const DESC =
  "We set up your website and your WhatsApp so every enquiry is answered, followed up and counted. Plans for shops, salons, schools and other Nigerian businesses.";

/* ---- PLACEHOLDER PRICES (naira). Provisional. Change here only. ---- */
const WEBSITES = [
  {
    name: "Starter website",
    price: 80000,
    note: "Domain and one year of hosting included",
    body: "One page with your products or services, a WhatsApp button and a live address of your own.",
  },
  {
    name: "Standard website",
    price: 150000,
    note: "Domain and one year of hosting included",
    body: "Everything in Starter, plus up to 24 products in categories, customer reviews and Google set-up.",
  },
];
const RENEWAL = { price: 50000, label: "Domain and hosting renewal, from year two, per year" };

const PLANS = [
  {
    key: "capture",
    name: "Capture",
    line: "Never miss an enquiry",
    setup: 0,
    monthly: 15000,
    lead: "Included",
    items: [
      "Contact form on your website with an instant reply",
      "New WhatsApp messages saved as leads, with name and number",
      "See which page, product or button each lead came from",
      "An alert when a lead has waited too long for a reply",
      "A WhatsApp menu with set answers to common questions",
      "A simple page where you see all your leads",
    ],
    msg: "Hi, I'm interested in the Capture plan.",
  },
  {
    key: "convert",
    name: "Convert",
    line: "Turn more enquiries into sales",
    setup: 50000,
    monthly: 40000,
    suggested: true,
    lead: "Everything in Capture, plus",
    items: [
      "Answers to common questions, written from your own information (monthly message limit applies)",
      "A few questions asked to each new lead, then scored hot, warm or cold",
      "Follow-up messages to people who go quiet",
      "Payment links sent inside the chat",
      "Leads from Facebook and Instagram ads, tagged by ad",
      "Your own WhatsApp number",
      "Your choice of a product catalog, or booking with reminders",
    ],
    msg: "Hi, I'm interested in the Convert plan.",
  },
  {
    key: "grow",
    name: "Grow",
    line: "Keep customers and run a team",
    setup: 100000,
    monthly: 90000,
    lead: "Everything in Convert, plus",
    items: [
      "Both the product catalog and booking with reminders",
      "Messages to many customers at once, with opt-outs handled",
      "Review and repeat-purchase reminders",
      "A weekly summary of leads and sales sent to your WhatsApp",
      "Several staff replying from one shared inbox, with tasks and call logs",
    ],
    msg: "Hi, I'm interested in the Grow plan.",
  },
];

const ADDONS = [
  ["Support tickets", "Every complaint gets an owner and a deadline", "₦15,000 a month"],
  ["Renewals and win-back", "Reminders before customers lapse, and messages to bring them back", "₦15,000 a month"],
  ["Dashboard and ask-your-data", "See your numbers and ask questions in plain English", "₦10,000 a month"],
  ["Extra staff member", "Another person on the shared inbox", "₦5,000 a month each"],
  ["Extra WhatsApp number", "A second number for another branch or team", "₦10,000 a month"],
  ["Paid event or class funnel", "Registration, payment and reminders on one WhatsApp number", "₦50,000 per event"],
];
/* ---- end placeholder prices ---- */

const naira = (n) => `₦${Number(n).toLocaleString("en-NG")}`;

const PROBLEMS = [
  ["“How much is this?”", "The fifth time today, typed out again by hand."],
  ["“I’ll get back to you.”", "Then nobody does, and the customer goes elsewhere."],
  ["“Which ad brought this customer?”", "No idea. The money is spent either way."],
  ["“How did the week go?”", "You would have to count it yourself."],
];

const STEPS = [
  ["A customer messages you", "From your website, WhatsApp or an ad. Their name, number and where they came from are saved."],
  ["They get an answer straight away", "A menu and set answers, or replies written from your own information."],
  ["Nobody goes quiet", "People who stop replying get a follow-up. You get an alert when one is waiting."],
  ["You see what happened", "A weekly summary on your WhatsApp: leads, where they came from, and sales."],
];

/* Example chat shown in the phone. Clearly labelled “Example” on the page. */
const SCREENS = [
  [
    ["in", "Hi, how much is the red ankara dress?"],
    ["note", "New lead saved · Amaka · Source: website, Dresses page"],
  ],
  [
    ["in", "Hi, how much is the red ankara dress?"],
    ["out", "Hello Amaka! The red dress is ₦25,000. Want a payment link or to see more colours?"],
  ],
  [
    ["out", "Hi Amaka, still thinking about the red dress? Reply YES and we will hold it for you today."],
    ["in", "YES please"],
  ],
  [
    ["note", "Your week"],
    ["out", "18 new leads · 7 hot · 4 sales\nBest source: Instagram ad"],
  ],
];

const FAQ = [
  [
    "Does it cost extra when WhatsApp sends messages?",
    "WhatsApp charges per conversation for messages that you start. Each plan includes a starting allowance of these messages, and anything above it is billed at WhatsApp’s own price with no mark-up.",
  ],
  [
    "How long does set-up take?",
    "A full set-up takes about a week. Convert and Grow also need Meta to approve your own WhatsApp number, and that can take longer.",
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

/* Testimonial. Hidden by default. See the note at the top of this file. */
const SHOW_SAMPLE_QUOTE = false;
const REAL_QUOTE = false;
const QUOTE = {
  text: "[Replace with a real customer’s words.]",
  who: "[Customer name]",
  role: "[Business, city]",
};

const HERO_IMG = "/images/owner-hero.jpg";
const TICKER = ["Fashion shops", "Salons and barbers", "Schools and tutors", "Clinics and pharmacies", "Restaurants and bakers", "Real estate agents", "Electronics and phones", "Event planners", "Gyms and studios"];

/* Example numbers for the demo strip and chart. Labelled “Example” on the page. */
const EXAMPLE_WEEK = [
  [18, "new leads"],
  [7, "hot leads"],
  [4, "sales"],
  [0, "left unanswered"],
];
const CHART = [3, 5, 4, 8, 7, 12, 18];
const BOARD = [
  ["Hot", "ow-hot", [["Amaka", "Red ankara dress · website"], ["Tunde", "Ready to pay · Instagram ad"]]],
  ["Warm", "ow-warm", [["Ngozi", "Asked about delivery · WhatsApp"], ["Bayo", "Comparing prices · website"]]],
  ["Cold", "ow-cold", [["Hauwa", "Just browsing · Facebook ad"]]],
];

function Wa({ className = "", children, text = "Hi, I'd like to know more about your plans." }) {
  return (
    <a className={`ow-btn ow-wa ${className}`} href={waHref(text)} target="_blank" rel="noopener noreferrer">
      <svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
        <path d="M12.04 2a9.9 9.9 0 0 0-8.5 14.95L2 22l5.2-1.5A9.9 9.9 0 1 0 12.04 2Zm5.8 14.1c-.25.7-1.4 1.3-1.95 1.35-.5.05-1.1.07-1.75-.1-.4-.12-.9-.3-1.55-.58-2.7-1.17-4.45-3.9-4.6-4.08-.13-.18-1.1-1.46-1.1-2.8 0-1.33.7-1.98.95-2.25.25-.27.55-.33.73-.33l.53.01c.17 0 .4-.06.62.48.25.57.84 1.98.9 2.12.08.15.12.32.02.5-.1.2-.15.32-.3.5l-.45.52c-.15.15-.3.31-.13.6.18.3.78 1.28 1.67 2.07 1.14 1 2.1 1.32 2.4 1.46.3.15.47.12.65-.07.18-.2.75-.87.95-1.17.2-.3.4-.25.67-.15.27.1 1.7.8 2 .95.3.15.5.22.57.35.07.12.07.7-.18 1.4Z" />
      </svg>
      {children}
    </a>
  );
}

/* Illustrated profile picture for the example chat (a drawing, not a real person). */
function Avatar() {
  return (
    <svg className="ow-ph-av" viewBox="0 0 40 40" aria-hidden="true">
      <rect width="40" height="40" fill="#F4D9C6" />
      <path d="M4 40c1-9 8-13 16-13s15 4 16 13z" fill="#0E6E7A" />
      <rect x="16.5" y="21" width="7" height="8" rx="3" fill="#8A5A3C" />
      <ellipse cx="20" cy="16.5" rx="7.4" ry="8.6" fill="#9A6644" />
      <path d="M11.4 15.5c0-7.2 4.2-10.8 8.8-10.8s8.4 3.6 8.4 10.8c-1.6-3.2-4.6-4.9-8.4-4.9s-7 1.7-8.8 4.9z" fill="#E4572E" />
      <path d="M12 12.5c3-4 13-4.6 16.4-.4" stroke="#F2B544" strokeWidth="1.6" fill="none" strokeLinecap="round" />
      <circle cx="17.2" cy="17" r=".9" fill="#2A1A12" />
      <circle cx="22.8" cy="17" r=".9" fill="#2A1A12" />
      <path d="M17.4 20.6q2.6 2 5.2 0" stroke="#2A1A12" strokeWidth="1" fill="none" strokeLinecap="round" />
      <circle cx="12.6" cy="19.2" r="1.3" fill="#F2B544" />
      <circle cx="27.4" cy="19.2" r="1.3" fill="#F2B544" />
    </svg>
  );
}

function Phone({ step }) {
  let t = 0.25;
  const rows = [];
  SCREENS[step].forEach(([kind, text], i) => {
    if (kind === "out") {
      rows.push(<span key={`t${i}`} className="ow-typing" style={{ "--d": `${t}s` }}><b /><b /><b /></span>);
      t += 0.95;
    }
    rows.push(
      <p key={`m${i}`} className={`ow-m ow-m-${kind}`} style={{ "--d": `${t}s` }}>
        {text}
        <i>{kind === "in" ? "9:41 ✓✓" : "9:41"}</i>
      </p>
    );
    t += kind === "out" ? 1.0 : 0.9;
  });
  return (
    <div role="img" aria-label="Example WhatsApp chat on a phone">
      <div className="ow-ph" aria-hidden="true">
        <div className="ow-ph-screen">
          <span className="ow-ph-island" />
          <div className="ow-ph-head">
            <div className="ow-ph-status">
              <span>9:41</span>
              <svg viewBox="0 0 34 12" fill="#fff"><rect x="0" y="7" width="3" height="5" rx="1" /><rect x="5" y="5" width="3" height="7" rx="1" /><rect x="10" y="2.5" width="3" height="9.5" rx="1" /><rect x="15" y="0" width="3" height="12" rx="1" /><rect x="21" y="1" width="12" height="10" rx="3" fill="none" stroke="#fff" strokeWidth="1.2" /><rect x="22.6" y="2.6" width="8" height="6.8" rx="1.6" /></svg>
            </div>
            <div className="ow-ph-bar">
              <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M15 5l-7 7 7 7" /></svg>
              <Avatar />
              <span className="ow-ph-name"><b>Your business</b><small>online</small></span>
              <em className="ow-ph-ex">Example</em>
            </div>
          </div>
          <div className="ow-ph-chat">{rows}</div>
          <div className="ow-ph-input">
            <span className="ow-ph-field">Message</span>
            <span className="ow-ph-mic"><svg viewBox="0 0 24 24" fill="#fff"><path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.9V22h2v-3.1A7 7 0 0 0 19 12h-2Z" /></svg></span>
          </div>
          <div className="ow-ph-home" />
        </div>
      </div>
    </div>
  );
}

/* A chat drawn onto the blank phone screen in the hero photo. The numbers are the screen's corners
   in the photo's own pixels (1536 x 1024); the viewBox is the part of the photo the 4:5 panel shows
   (object-position 70%). If you replace the photo, re-measure these or delete <PhoneScreen />. */
function PhoneScreen() {
  return (
    <svg className="ow-screen" viewBox="501.8 0 819.2 1024" aria-hidden="true" focusable="false">
      <defs>
        <clipPath id="ow-sc"><rect width="100" height="240" rx="10" /></clipPath>
      </defs>
      <g transform="matrix(0.81 -0.11 0.3375 0.9083 775 502)" clipPath="url(#ow-sc)">
        <rect width="100" height="240" fill="#EFEAE2" />
        <rect width="100" height="30" fill="#015F6B" />
        <circle cx="14" cy="15" r="6" fill="#fff" />
        <text x="26" y="19" fontSize="11" fontWeight="700" fill="#fff">Shop</text>
        <g className="ow-b ow-b1">
          <rect x="22" y="44" width="72" height="26" rx="7" fill="#D9FDD3" />
          <text x="29" y="61" fontSize="12" fill="#0B1B2B">How much?</text>
        </g>
        <g className="ow-b ow-b2">
          <rect x="6" y="80" width="76" height="46" rx="7" fill="#fff" />
          <text x="13" y="102" fontSize="17" fontWeight="800" fill="#0B1B2B">₦25,000</text>
          <text x="13" y="118" fontSize="11" fill="#4A5B6B">Pay link ›</text>
        </g>
        <g className="ow-b ow-b3">
          <rect x="40" y="136" width="54" height="24" rx="7" fill="#D9FDD3" />
          <text x="48" y="152" fontSize="12" fill="#0B1B2B">Yes please</text>
        </g>
      </g>
    </svg>
  );
}

/* Counts up once when scrolled into view. Shows the final number straight away if motion is reduced. */
function Count({ to }) {
  const ref = useRef(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    const el = ref.current;
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !("IntersectionObserver" in window) || to === 0) { setN(to); return undefined; }
    let raf = 0;
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return;
      io.disconnect();
      const t0 = performance.now();
      const tick = (t) => {
        const k = Math.min(1, (t - t0) / 1200);
        setN(Math.round(to * (1 - Math.pow(1 - k, 3))));
        if (k < 1) raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    }, { threshold: 0.6 });
    io.observe(el);
    return () => { io.disconnect(); cancelAnimationFrame(raf); };
  }, [to]);
  return <span ref={ref}>{n}</span>;
}

function Words({ text }) {
  return text.split(" ").map((w, i) => (
    <span key={i}>
      <span className="ow-w"><span style={{ "--d": `${120 + i * 90}ms` }}>{w}</span></span>{" "}
    </span>
  ));
}

function Chart() {
  const W = 520, H = 200, P = 18, max = Math.max(...CHART);
  const pts = CHART.map((v, i) => [P + (i * (W - 2 * P)) / (CHART.length - 1), H - P - (v / max) * (H - 2 * P)]);
  const line = pts.map(([x, y]) => `${x},${y}`).join(" ");
  const area = `${P},${H - P} ${line} ${W - P},${H - P}`;
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  return (
    <svg className="ow-chart" viewBox={`0 0 ${W} ${H + 22}`} role="img" aria-label="Example chart: leads rising through the week">
      <defs>
        <linearGradient id="owg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#028090" stopOpacity=".35" />
          <stop offset="1" stopColor="#028090" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((f) => (
        <line key={f} x1={P} x2={W - P} y1={P + f * (H - 2 * P)} y2={P + f * (H - 2 * P)} className="ow-grid" />
      ))}
      <polygon points={area} fill="url(#owg)" className="ow-area" />
      <polyline points={line} pathLength="1" className="ow-draw" fill="none" />
      {pts.map(([x, y], i) => (
        <g key={i}>
          <circle cx={x} cy={y} r="5" className="ow-pt" style={{ "--d": `${0.9 + i * 0.12}s` }} />
          <text x={x} y={H + 14} textAnchor="middle" className="ow-day">{days[i]}</text>
        </g>
      ))}
    </svg>
  );
}

export default function OwnerLandingPage() {
  const rootRef = useRef(null);
  const [solid, setSolid] = useState(false);
  const [step, setStep] = useState(0);
  const [open, setOpen] = useState(0);
  const [imgOk, setImgOk] = useState(true);
  const stepRefs = useRef([]);
  const phoneBox = useRef(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const prevTitle = document.title;
    document.title = TITLE;
    const metaDesc = document.querySelector('meta[name="description"]');
    const prevDesc = metaDesc ? metaDesc.getAttribute("content") : null;
    if (metaDesc) metaDesc.setAttribute("content", DESC);

    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href =
      "https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap";
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

    const root = rootRef.current;
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const bar = root.querySelector(".ow-progress i");
    const onScroll = () => {
      setSolid(window.scrollY > 8);
      const h = document.documentElement.scrollHeight - window.innerHeight;
      if (bar && h > 0) bar.style.transform = `scaleX(${Math.min(1, window.scrollY / h)})`;
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });

    /* Scroll reveal. Elements stay visible unless this script runs (class ow-js). */
    let rv = null;
    if ("IntersectionObserver" in window && !reduce) {
      root.classList.add("ow-js");
      rv = new IntersectionObserver(
        (entries) => entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("ow-vis"); rv.unobserve(e.target); } }),
        { threshold: 0.12, rootMargin: "0px 0px -6% 0px" }
      );
      root.querySelectorAll("[data-rv]").forEach((el) => rv.observe(el));
    }

    /* Buttons lean slightly toward the pointer. */
    const onMove = (e) => {
      if (reduce) return;
      const b = e.target.closest && e.target.closest(".ow-btn");
      if (!b) return;
      const r = b.getBoundingClientRect();
      b.style.setProperty("--mx", `${((e.clientX - r.left) / r.width - 0.5) * 8}px`);
      b.style.setProperty("--my", `${((e.clientY - r.top) / r.height - 0.5) * 6}px`);
    };
    const onLeave = (e) => {
      const b = e.target.closest && e.target.closest(".ow-btn");
      if (b) { b.style.setProperty("--mx", "0px"); b.style.setProperty("--my", "0px"); }
    };
    root.addEventListener("mousemove", onMove);
    root.addEventListener("mouseout", onLeave);

    let io = null;
    if ("IntersectionObserver" in window) {
      io = new IntersectionObserver(
        (entries) => {
          entries.forEach((e) => {
            if (e.isIntersecting) setStep(Number(e.target.dataset.i));
          });
        },
        { rootMargin: "-45% 0px -45% 0px" }
      );
      stepRefs.current.forEach((el) => el && io.observe(el));
    }

    let pio = null;
    if ("IntersectionObserver" in window && phoneBox.current) {
      pio = new IntersectionObserver(([en]) => {
        if (en.isIntersecting) { setTick((n) => n + 1); pio.disconnect(); }
      }, { threshold: 0.5 });
      pio.observe(phoneBox.current);
    }

    return () => {
      if (pio) pio.disconnect();
      document.title = prevTitle;
      if (metaDesc && prevDesc !== null) metaDesc.setAttribute("content", prevDesc);
      link.remove();
      ld.remove();
      window.removeEventListener("scroll", onScroll);
      root.removeEventListener("mousemove", onMove);
      root.removeEventListener("mouseout", onLeave);
      if (io) io.disconnect();
      if (rv) rv.disconnect();
    };
  }, []);

  return (
    <div className="ow" ref={rootRef}>
      <a className="ow-skip" href="#plans">Skip to the plans</a>
      <div className="ow-progress" aria-hidden="true"><i /></div>

      <header className={`ow-nav${solid ? " ow-solid" : ""}`}>
        <div className="ow-wrap ow-nav-row">
          <a className="ow-mark" href="/business" aria-label="Opsra home"><i />opsra</a>
          <nav aria-label="Main">
            <ul>
              <li><a href="#how">How it works</a></li>
              <li><a href="#plans">Plans</a></li>
              <li><a href="#questions">Questions</a></li>
            </ul>
          </nav>
          <Wa className="ow-sm ow-nav-cta" text="Hi, I'd like to know more about your plans.">Message us</Wa>
        </div>
      </header>

      <main>
        <section className="ow-hero">
          <div className="ow-glow" aria-hidden="true" />
          <div className="ow-wrap ow-hero-grid">
            <div className="ow-hero-copy">
              <p className="ow-label ow-fade" style={{ "--d": "0ms" }}>For shops, salons, schools and more</p>
              <h1><Words text="Never lose a customer message again." /></h1>
              <p className="ow-lede ow-fade" style={{ "--d": "700ms" }}>
                We set up your website and your WhatsApp so every enquiry is answered, followed up and
                counted. You keep running the business.
              </p>
              <div className="ow-cta-row ow-fade" style={{ "--d": "850ms" }}>
                <Wa>Message us on WhatsApp</Wa>
                <a className="ow-link" href="#plans">See the plans &rarr;</a>
              </div>
            </div>

            <div className="ow-stage ow-fade" style={{ "--d": "300ms" }}>
              <div className="ow-photo">
                {imgOk && (
                  <div className="ow-pan">
                    <img src={HERO_IMG} alt="A shop owner checking her phone at the counter of her boutique (AI-generated illustration)" width="1536" height="1024" fetchpriority="high" onError={() => setImgOk(false)} />
                    <PhoneScreen />
                  </div>
                )}
                {!imgOk && <div className="ow-photo-fallback" aria-hidden="true"><i /><i /><i /></div>}
              </div>
              <div className="ow-float ow-f1"><b>New lead saved</b><span>Amaka · Dresses page</span></div>
              <div className="ow-float ow-f2"><b>Replied straight away</b><span>“The red dress is ₦25,000…”</span></div>
              <div className="ow-float ow-f3"><b>Hot lead</b><span>Tunde · ready to pay</span></div>
              <p className="ow-credit">Illustration, not a real customer. Example messages.</p>
            </div>
          </div>
        </section>

        <div className="ow-ticker" aria-label="Kinds of business this suits">
          <div className="ow-track">
            {[...TICKER, ...TICKER].map((t, i) => (<span key={i} aria-hidden={i >= TICKER.length}>{t}</span>))}
          </div>
        </div>

        <section className="ow-problem" aria-labelledby="problem-h">
          <div className="ow-wrap">
            <p className="ow-label" data-rv>Sound familiar?</p>
            <h2 id="problem-h" className="ow-h2" data-rv>Four things owners say every week.</h2>
            <ul className="ow-rows">
              {PROBLEMS.map(([q, a], i) => (
                <li key={q} data-rv style={{ "--d": `${i * 90}ms` }}><strong>{q}</strong><span>{a}</span></li>
              ))}
            </ul>
          </div>
        </section>

        <section id="how" className="ow-how" aria-labelledby="how-h">
          <div className="ow-wrap">
            <div className="ow-head" data-rv>
              <p className="ow-label">How it works</p>
              <h2 id="how-h" className="ow-h2">From first message to a weekly summary.</h2>
            </div>
            <div className="ow-how-grid">
              <ol className="ow-steps">
                {STEPS.map(([t, d], i) => (
                  <li
                    key={t}
                    data-i={i}
                    ref={(el) => (stepRefs.current[i] = el)}
                    className={step === i ? "ow-on" : ""}
                  >
                    <button type="button" onClick={() => setStep(i)} aria-pressed={step === i}>
                      <span className="ow-num">{i + 1}</span>
                      <span><b>{t}</b><small>{d}</small></span>
                    </button>
                  </li>
                ))}
              </ol>
              <div className="ow-how-phone" ref={phoneBox}><Phone key={tick} step={step} /><p className="ow-ph-cap">Example chat</p></div>
            </div>
          </div>
        </section>

        <section className="ow-board" aria-labelledby="board-h">
          <div className="ow-wrap">
            <div className="ow-head" data-rv>
              <p className="ow-label">What you see</p>
              <h2 id="board-h" className="ow-h2">Every lead in one place, sorted for you.</h2>
              <p className="ow-sub">Example week for a small fashion shop. Your own numbers will differ.</p>
            </div>
            <ul className="ow-stats" data-rv>
              {EXAMPLE_WEEK.map(([n, l]) => (
                <li key={l}><b><Count to={n} /></b><span>{l}</span></li>
              ))}
            </ul>
            <div className="ow-board-grid">
              <div className="ow-cols" data-rv>
                {BOARD.map(([name, cls, cards]) => (
                  <div key={name} className={`ow-col ${cls}`}>
                    <h3>{name}</h3>
                    {cards.map(([who, what], i) => (
                      <p key={who} className="ow-lead-card" style={{ "--d": `${300 + i * 160}ms` }}><b>{who}</b><small>{what}</small></p>
                    ))}
                  </div>
                ))}
              </div>
              <div className="ow-chartbox" data-rv>
                <p className="ow-label">Leads this week · example</p>
                <Chart />
              </div>
            </div>
          </div>
        </section>

        <section id="plans" className="ow-plans" aria-labelledby="plans-h">
          <div className="ow-wrap">
            <div className="ow-head" data-rv>
              <p className="ow-label">Plans and prices</p>
              <h2 id="plans-h" className="ow-h2">Start with a website. Add the rest when you are ready.</h2>
              <p className="ow-sub">Prices are in naira and may change before you start.</p>
            </div>

            <div className="ow-sites">
              {WEBSITES.map((w, i) => (
                <article key={w.name} className="ow-site" data-rv style={{ "--d": `${i * 100}ms` }}>
                  <h3>{w.name}</h3>
                  <p className="ow-price"><b>{naira(w.price)}</b> <span>one time</span></p>
                  <p className="ow-note">{w.note}</p>
                  <p>{w.body}</p>
                  <Wa className="ow-sm ow-outline" text={`Hi, I'm interested in the ${w.name}.`}>Ask about this</Wa>
                </article>
              ))}
              <p className="ow-renew">{naira(RENEWAL.price)} &middot; {RENEWAL.label}</p>
            </div>

            <div className="ow-cards">
              {PLANS.map((p, i) => (
                <article key={p.key} className={`ow-card${p.suggested ? " ow-suggested" : ""}`} data-rv style={{ "--d": `${i * 130}ms` }}>
                  {p.suggested && <span className="ow-flag">Suggested starting point</span>}
                  <h3>{p.name}</h3>
                  <p className="ow-line">{p.line}</p>
                  <p className="ow-price"><b>{naira(p.monthly)}</b> <span>a month</span></p>
                  <p className="ow-setup">{p.setup === 0 ? "No set-up fee" : `${naira(p.setup)} set-up, one time`}</p>
                  <Wa className={`ow-sm ${p.suggested ? "" : "ow-outline"}`} text={p.msg}>Choose {p.name}</Wa>
                  <p className="ow-lead">{p.lead}</p>
                  <ul>
                    {p.items.map((it) => (<li key={it}>{it}</li>))}
                  </ul>
                </article>
              ))}
            </div>

            <div className="ow-addons" data-rv>
              <h3>Add what you need</h3>
              <ul>
                {ADDONS.map(([n, d, p]) => (
                  <li key={n}>
                    <span><b>{n}</b><small>{d}</small></span>
                    <em>{p}</em>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        {(SHOW_SAMPLE_QUOTE || REAL_QUOTE) && (
          <section className="ow-quote">
            <div className="ow-wrap">
              {!REAL_QUOTE && <p className="ow-sample">SAMPLE LAYOUT ONLY. Replace with a real customer quote before publishing.</p>}
              <blockquote>
                <p>“{QUOTE.text}”</p>
                <footer>{QUOTE.who}, {QUOTE.role}</footer>
              </blockquote>
            </div>
          </section>
        )}

        <section id="questions" className="ow-faq" aria-labelledby="faq-h">
          <div className="ow-wrap ow-faq-grid">
            <div data-rv>
              <p className="ow-label">Questions</p>
              <h2 id="faq-h" className="ow-h2">Before you message us.</h2>
            </div>
            <div className="ow-acc" data-rv>
              {FAQ.map(([q, a], i) => (
                <div key={q} className={`ow-qa${open === i ? " ow-open" : ""}`}>
                  <h3>
                    <button
                      type="button"
                      aria-expanded={open === i}
                      aria-controls={`qa-${i}`}
                      onClick={() => setOpen(open === i ? -1 : i)}
                    >
                      {q}<i aria-hidden="true" />
                    </button>
                  </h3>
                  <div id={`qa-${i}`} role="region" hidden={open !== i}><p>{a}</p></div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="ow-close" aria-labelledby="close-h">
          <div className="ow-glow ow-glow2" aria-hidden="true" />
          <div className="ow-wrap" data-rv>
            <h2 id="close-h">Tell us what you sell. We will show you how it would work.</h2>
            <Wa className="ow-big">Message us on WhatsApp</Wa>
          </div>
        </section>
      </main>

      <footer className="ow-foot">
        <div className="ow-wrap ow-foot-row">
          <span className="ow-foot-mark">opsra</span>
          <span>
            <a href="/privacy">Privacy</a> &middot; <a href="/terms">Terms</a>
          </span>
        </div>
      </footer>
    </div>
  );
}
