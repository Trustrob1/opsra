/**
 * frontend/src/pages/OwnerLandingPage.jsx
 * OWNER-LANDING-1 — public landing page + pricing for BUSINESS OWNERS.
 * Registered in App.jsx at `/business`. Standalone page (no AppShell, no staff auth).
 * Styles: OwnerLandingPage.css, scoped under `.ow`, every class prefixed `ow-`.
 *
 * ONE page on purpose: the only action is "Message us on WhatsApp", so the pricing
 * sits inside the page (#plans). Share https://<host>/business#plans.
 *
 * ---------------------------------------------------------------------------
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

function Phone({ step }) {
  return (
    <div className="ow-phone" role="img" aria-label="Example WhatsApp chat">
      <div className="ow-phone-top">
        <i className="ow-dot" />
        <span>Your business</span>
        <em>Example</em>
      </div>
      <div className="ow-chat">
        {SCREENS[step].map(([kind, text], i) => (
          <p key={`${step}-${i}`} className={`ow-msg ow-${kind}`}>
            {text}
          </p>
        ))}
      </div>
    </div>
  );
}

export default function OwnerLandingPage() {
  const rootRef = useRef(null);
  const [solid, setSolid] = useState(false);
  const [step, setStep] = useState(0);
  const [open, setOpen] = useState(0);
  const stepRefs = useRef([]);

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

    const onScroll = () => setSolid(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });

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

    return () => {
      document.title = prevTitle;
      if (metaDesc && prevDesc !== null) metaDesc.setAttribute("content", prevDesc);
      link.remove();
      ld.remove();
      window.removeEventListener("scroll", onScroll);
      if (io) io.disconnect();
    };
  }, []);

  return (
    <div className="ow" ref={rootRef}>
      <a className="ow-skip" href="#plans">Skip to the plans</a>

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
          <div className="ow-wrap ow-hero-grid">
            <div>
              <p className="ow-label">For shops, salons, schools and more</p>
              <h1>Never lose a customer message again.</h1>
              <p className="ow-lede">
                We set up your website and your WhatsApp so every enquiry is answered, followed up and
                counted. You keep running the business.
              </p>
              <div className="ow-cta-row">
                <Wa>Message us on WhatsApp</Wa>
                <a className="ow-link" href="#plans">See the plans &rarr;</a>
              </div>
            </div>
            <div className="ow-hero-phone"><Phone step={1} /></div>
          </div>
        </section>

        <section className="ow-problem" aria-labelledby="problem-h">
          <div className="ow-wrap">
            <p className="ow-label">Sound familiar?</p>
            <h2 id="problem-h" className="ow-h2">Four things owners say every week.</h2>
            <ul className="ow-rows">
              {PROBLEMS.map(([q, a]) => (
                <li key={q}><strong>{q}</strong><span>{a}</span></li>
              ))}
            </ul>
          </div>
        </section>

        <section id="how" className="ow-how" aria-labelledby="how-h">
          <div className="ow-wrap">
            <div className="ow-head">
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
              <div className="ow-how-phone"><Phone step={step} /></div>
            </div>
          </div>
        </section>

        <section id="plans" className="ow-plans" aria-labelledby="plans-h">
          <div className="ow-wrap">
            <div className="ow-head">
              <p className="ow-label">Plans and prices</p>
              <h2 id="plans-h" className="ow-h2">Start with a website. Add the rest when you are ready.</h2>
              <p className="ow-sub">Prices are in naira and may change before you start.</p>
            </div>

            <div className="ow-sites">
              {WEBSITES.map((w) => (
                <article key={w.name} className="ow-site">
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
              {PLANS.map((p) => (
                <article key={p.key} className={`ow-card${p.suggested ? " ow-suggested" : ""}`}>
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

            <div className="ow-addons">
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
            <div>
              <p className="ow-label">Questions</p>
              <h2 id="faq-h" className="ow-h2">Before you message us.</h2>
            </div>
            <div className="ow-acc">
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
          <div className="ow-wrap">
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
