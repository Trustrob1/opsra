/**
 * frontend/src/pages/SiteLandingPage.jsx
 * SITE-LANDING-2 — public landing page for Opsra Sites, with passwordless sign-in.
 * Registered in App.jsx at `/sites` and `/builders`, and also shown at `/b/login`
 * when a builder arrives without a magic-link token.
 *
 * Standalone page (no AppShell, no staff auth). Styles live in SiteLandingPage.css,
 * scoped under `.sl` with every class prefixed `sl-`, so nothing leaks into or out
 * of the staff app. Images are in /public/sites-landing/ (real renders from the site engine).
 *
 * SITE-LANDING-2 redesign: warm paper background, bold sans headline, pill buttons,
 * a prompt-style hero with audience tabs, real-site gallery in browser frames.
 * The sections for customer quotes and live numbers are NOT shown until real ones
 * exist: add entries to REAL_SITES / QUOTES / STATS below and they render by themselves.
 *
 * POSITIONING: "If you can use WhatsApp, you can build a website." Two audiences:
 * people launching their own brand and people who want to earn by building and selling sites.
 *
 * SIGN-IN: builders have no password. They type the WhatsApp number they registered
 * with and the server sends a single-use link to THEIR OWN WhatsApp and email
 * (POST /api/v1/builder/auth/request-link). The link never comes back to this page
 * and the reply is identical for unknown numbers.
 *
 * OWNER SETTINGS: set VITE_BUILDER_JOIN_URL (a wa.me link to the Site Builder
 * WhatsApp number) so "Start building" opens WhatsApp. Unset, it scrolls to the sign-in box.
 */
import { useEffect, useId, useRef, useState } from "react";
import { requestBuilderLink, errorMessage, whatsappLink } from "../services/builder_portal.service";
import SiteSignUpForm from "./SiteSignUpForm";
import "./SiteLandingPage.css";

const JOIN_URL = import.meta.env.VITE_BUILDER_JOIN_URL || "";
const START_HREF = JOIN_URL || "#start";
const START_ATTRS = JOIN_URL ? { target: "_blank", rel: "noopener noreferrer" } : {};

const TITLE = "Opsra Sites | Build a website on WhatsApp";
const DESC =
  "If you can use WhatsApp or fill in a simple form, you can build a website. Launch your own brand, or build sites for others and get paid. No developer, no code.";

/* Hero tabs: the example shown in the box above them. */
const TABS = [
  {
    label: "My own brand",
    text: "I run a coaching business in Lagos. I want a website with my story, my prices and a WhatsApp button.",
  },
  {
    label: "For my clients",
    text: "I want to build a website for a client, a small clinic. I'll send them a form link to fill in on their phone.",
  },
  {
    label: "A shop",
    text: "I sell fashion from my phone. I need a simple site where people can see my items and message me to order.",
  },
  {
    label: "A school or firm",
    text: "Our school needs a proper website with admissions information, a gallery and a contact page.",
  },
];

/* Sites shown in browser frames. Each one is loaded LIVE in an iframe (so it is the real site, not a picture)
   and the whole card links to it. Shape: { name, kind, url (shown in the address bar), href, tag? }.
   Set SITES_SAMPLE to true only to fall back to the engine sample renders (d / m files in /public/sites-landing). */
const SITES_SAMPLE = false;
const REAL_SITES = [
  {
    name: "Alfa Diva",
    kind: "African clothing for women, made in Lagos",
    url: "trustrobert.com/websites/alfa-diva",
    href: "https://trustrobert.com/websites/alfa-diva/",
  },
  {
    name: "Veltro Aria",
    kind: "Luxury car website",
    tag: "Concept",
    url: "trustrobert.com/portfolio-carsite.html",
    href: "https://trustrobert.com/portfolio-carsite.html",
  },
  {
    name: "Keel Wealth",
    kind: "Fintech website",
    tag: "Concept",
    url: "trustrobert.com/websites/keel",
    href: "https://trustrobert.com/websites/keel/",
  },
  {
    name: "Trust Robert",
    kind: "AI automation and workflow strategist",
    url: "trustrobert.com",
    href: "https://trustrobert.com/",
  },
];

/* Leave empty until they are real. Shape: { text, who, role }. */
const QUOTES = [];
/* Leave empty until they are real. Shape: { value, label }. */
const STATS = [];

const CHIPS = [
  "Your own domain",
  "Hosting",
  "A WhatsApp button",
  "Photos from your camera roll",
  "Matched to your business",
  "Ask for another design",
  "Undo your last 20 changes",
  "Edit any word or colour",
  "Client form links",
  "No Opsra branding on previews",
];

const FAQ = [
  [
    "Do I need to know how to code or design?",
    "No. If you can send a WhatsApp message or fill in an online form, you can build a website. The technical side is taken care of.",
  ],
  [
    "Can I do everything on WhatsApp?",
    "Yes. You can start a site, send photos and answer every question in a WhatsApp chat, or use the simple online form instead. Both lead to the same website.",
  ],
  [
    "Can I change the site after it is made?",
    "Yes. You can change words, photos, colours and layout yourself, ask for another design, and undo your last 20 changes.",
  ],
  [
    "Can I build websites for other people and sell them?",
    "Yes. Build a site for a client, or send them a form link to fill in on their own phone. Your portal shows the trade price and a suggested client price before you pay.",
  ],
  ["Whose name is the domain in?", "The site owner’s: you for your own brand, or your client for a site you sold."],
];

const STEPS = [
  [
    "01 · Start",
    "Message us, or open the form.",
    "Reply with a number to choose what you want to do. Answer on WhatsApp, fill the form yourself, or get a link to hand to your client.",
  ],
  [
    "02 · Tell us",
    "Answer a few easy questions.",
    "Your business name, what you sell, a few photos from your phone. The form saves as you go, so you can come back to it.",
  ],
  [
    "03 · Make it yours",
    "See your site, then change anything.",
    "Words, photos, colours, layout. Don’t love the look? Ask for another design. Every site is matched to the business, so yours won’t look like anyone else’s.",
  ],
  [
    "04 · Go live",
    "Put your name on the internet.",
    "Choose when to launch. Your website gets its own address, and you’re in charge of it from the first day.",
  ],
];

const ARROW = (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

function SignInForm({ inputRef }) {
  const uid = useId();
  const [phone, setPhone] = useState("");
  const [touched, setTouched] = useState(false);
  const [stage, setStage] = useState("idle"); // idle | sending | sent
  const [error, setError] = useState("");
  const digits = phone.replace(/\D/g, "");
  const invalid = digits.length < 9 || digits.length > 15;
  const showErr = touched && invalid && phone.length > 0;
  const inputId = `${uid}-phone`;
  const hintId = `${uid}-hint`;

  async function submit(e) {
    e.preventDefault();
    setTouched(true);
    if (invalid) {
      setError("Enter the WhatsApp number you registered with, for example 0803 123 4567.");
      return;
    }
    setStage("sending");
    setError("");
    try {
      await requestBuilderLink(phone.trim());
      setStage("sent");
    } catch (err) {
      setStage("idle");
      setError(errorMessage(err, "We couldn’t send that just now. Please try again in a moment."));
    }
  }

  if (stage === "sent") {
    return (
      <div className="sl-sent" role="status" aria-live="polite">
        <h3>Check your WhatsApp and email.</h3>
        <p>
          If that number is registered, your sign-in link is on its way. It works once and expires in 60 minutes. Email
          is the surest place to look if you haven’t messaged us on WhatsApp today.
        </p>
        <button
          type="button"
          onClick={() => {
            setStage("idle");
            setPhone("");
            setTouched(false);
          }}
        >
          Use a different number
        </button>
      </div>
    );
  }
  return (
    <form className="sl-sform" onSubmit={submit} noValidate>
      <label htmlFor={inputId}>WhatsApp number</label>
      <input
        id={inputId}
        ref={inputRef}
        type="tel"
        inputMode="tel"
        autoComplete="tel"
        placeholder="0803 123 4567"
        value={phone}
        aria-invalid={showErr || undefined}
        aria-describedby={hintId}
        onChange={(e) => {
          setPhone(e.target.value);
          setError("");
        }}
        onBlur={() => setTouched(true)}
      />
      <p className="sl-hint" id={hintId}>
        We’ll send a one-time link to your WhatsApp and email. No password needed.
      </p>
      <div aria-live="polite">
        <p className="sl-err">{error || (showErr ? "That doesn’t look like a full phone number yet." : "")}</p>
      </div>
      <button className="sl-btn sl-teal" type="submit" disabled={stage === "sending"}>
        <span>{stage === "sending" ? "Sending…" : "Send my sign-in link"}</span>
        {ARROW}
      </button>
      {whatsappLink("EDIT") && (
        <>
          <p className="sl-hint">Prefer WhatsApp? Send us the word EDIT and we’ll reply with your link straight away.</p>
          <a className="sl-btn sl-wa" href={whatsappLink("EDIT")} target="_blank" rel="noopener noreferrer">
            <span>Sign in on WhatsApp</span>
          </a>
        </>
      )}
    </form>
  );
}

function AuthPanel({ inputRef }) {
  const [mode, setMode] = useState("signin"); // signin | signup
  return (
    <>
      <div className="sl-authtabs" role="tablist" aria-label="Sign in or create an account">
        <button type="button" role="tab" aria-selected={mode === "signin"} onClick={() => setMode("signin")}>
          Sign in
        </button>
        <button type="button" role="tab" aria-selected={mode === "signup"} onClick={() => setMode("signup")}>
          Create account
        </button>
      </div>
      {mode === "signin" ? <SignInForm inputRef={inputRef} /> : <SiteSignUpForm />}
    </>
  );
}

function Browser({ url, shot, label, live, title }) {
  return (
    <div className="sl-browser" role="img" aria-label={label}>
      <div className="sl-bar">
        <i></i>
        <i></i>
        <i></i>
        <span>{url}</span>
      </div>
      {live ? (
        <div className="sl-live">
          <iframe
            src={live}
            title={title || label}
            loading="lazy"
            tabIndex={-1}
            sandbox="allow-scripts allow-same-origin"
            referrerPolicy="no-referrer"
          ></iframe>
        </div>
      ) : (
        <div className={`sl-shot sl-i-${shot}`}></div>
      )}
    </div>
  );
}

export default function SiteLandingPage() {
  const rootRef = useRef(null);
  const sheetRef = useRef(null);
  const mainInputRef = useRef(null);
  const sheetInputRef = useRef(null);
  const [tab, setTab] = useState(0);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return undefined;
    const undo = [];
    const on = (el, ev, fn, opts) => {
      el.addEventListener(ev, fn, opts);
      undo.push(() => el.removeEventListener(ev, fn, opts));
    };
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    /* head: title, description, fonts, structured data */
    const prevTitle = document.title;
    document.title = TITLE;
    const metaDesc = document.querySelector('meta[name="description"]');
    const prevDesc = metaDesc ? metaDesc.getAttribute("content") : null;
    if (metaDesc) metaDesc.setAttribute("content", DESC);
    const added = [];
    [
      "https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap",
    ].forEach((href) => {
      const l = document.createElement("link");
      l.rel = "stylesheet";
      l.href = href;
      document.head.appendChild(l);
      added.push(l);
    });
    const ld = document.createElement("script");
    ld.type = "application/ld+json";
    ld.textContent = JSON.stringify({
      "@context": "https://schema.org",
      "@graph": [
        { "@type": "Organization", name: "Opsra" },
        { "@type": "WebPage", name: TITLE, description: DESC, inLanguage: "en" },
        {
          "@type": "FAQPage",
          mainEntity: FAQ.map(([q, a]) => ({
            "@type": "Question",
            name: q,
            acceptedAnswer: { "@type": "Answer", text: a },
          })),
        },
      ],
    });
    document.head.appendChild(ld);
    added.push(ld);
    undo.push(() => {
      document.title = prevTitle;
      if (metaDesc && prevDesc !== null) metaDesc.setAttribute("content", prevDesc);
      added.forEach((n) => n.remove());
    });

    /* nav: gets a border after a little scroll */
    const nav = root.querySelector(".sl-nav");
    const onScroll = () => nav.classList.toggle("sl-solid", window.scrollY > 16);
    on(window, "scroll", onScroll, { passive: true });
    onScroll();

    /* in-page links */
    root.querySelectorAll('a[href^="#"]').forEach((a) =>
      on(a, "click", (e) => {
        const id = a.getAttribute("href");
        if (!id || id.length < 2) return;
        const t = root.querySelector(id);
        if (!t) return;
        e.preventDefault();
        t.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      }),
    );

    /* sign-in sheet */
    const sheet = sheetRef.current;
    root.querySelectorAll("[data-open-signin]").forEach((b) =>
      on(b, "click", () => {
        if (sheet && typeof sheet.showModal === "function") {
          sheet.showModal();
          setTimeout(() => sheetInputRef.current && sheetInputRef.current.focus(), 50);
        } else {
          const s = root.querySelector("#start");
          if (s) s.scrollIntoView();
        }
      }),
    );

    /* steps drive the sticky device */
    const steps = [...root.querySelectorAll(".sl-step")];
    const screens = [...root.querySelectorAll(".sl-dev .sl-d")];
    const setStep = (i) => {
      steps.forEach((s, k) => s.classList.toggle("sl-on", k === i));
      screens.forEach((s, k) => s.classList.toggle("sl-on", k === i));
    };
    steps.forEach((s, i) => {
      on(s, "click", () => setStep(i));
      on(s, "keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setStep(i);
        }
      });
    });
    if ("IntersectionObserver" in window && window.matchMedia("(min-width: 981px)").matches) {
      const io = new IntersectionObserver(
        (entries) => {
          entries.forEach((en) => {
            if (en.isIntersecting) setStep(steps.indexOf(en.target));
          });
        },
        { rootMargin: "-50% 0px -50% 0px", threshold: 0 },
      );
      steps.forEach((s) => io.observe(s));
      undo.push(() => io.disconnect());
    }

    /* "try another design": three real renders of one business */
    const shots = [...root.querySelectorAll("#swap .sl-shot")];
    const btns = [...root.querySelectorAll(".sl-designs button")];
    btns.forEach((b, k) =>
      on(b, "click", () => {
        shots.forEach((s, i) => s.classList.toggle("sl-on", i === k));
        btns.forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
      }),
    );

    /* live site previews: render each iframe at 1280px wide and scale it to fit its frame */
    const lives = [...root.querySelectorAll(".sl-live")];
    const fit = () =>
      lives.forEach((box) => {
        const f = box.querySelector("iframe");
        if (f) f.style.transform = `scale(${box.clientWidth / 1280})`;
      });
    fit();
    if ("ResizeObserver" in window) {
      const ro = new ResizeObserver(fit);
      lives.forEach((b) => ro.observe(b));
      undo.push(() => ro.disconnect());
    } else {
      on(window, "resize", fit);
    }

    /* arriving from /sites#signin (logout, expired link) */
    let t = 0;
    if (window.location.hash === "#signin") {
      t = window.setTimeout(() => {
        const s = root.querySelector("#start");
        if (s) s.scrollIntoView();
        if (mainInputRef.current) mainInputRef.current.focus({ preventScroll: true });
      }, 300);
    }
    undo.push(() => window.clearTimeout(t));

    return () => undo.forEach((f) => f());
  }, []);

  return (
    <div className="sl" ref={rootRef}>
      <a className="sl-skip" href="#main">
        Skip to content
      </a>
      <header className="sl-nav" id="nav">
        <div className="sl-wrap">
          <a className="sl-mark" href="#top" aria-label="Opsra Sites, home">
            <i aria-hidden="true"></i>opsra<small>Sites</small>
          </a>
          <nav aria-label="Main">
            <ul>
              <li>
                <a href="#sites">Sites</a>
              </li>
              <li>
                <a href="#how">How it works</a>
              </li>
              <li>
                <a href="#ways">Two ways in</a>
              </li>
              <li>
                <a href="#pricing">Pricing</a>
              </li>
              <li>
                <a href="#faq">Questions</a>
              </li>
            </ul>
          </nav>
          <div className="sl-right">
            <button className="sl-signin-link" type="button" data-open-signin>
              Sign in
            </button>
            <a className="sl-btn sl-teal sl-sm" href={START_HREF} {...START_ATTRS} data-start>
              Start building
            </a>
          </div>
        </div>
      </header>

      <main id="main">
        <section className="sl-hero" id="top">
          <div className="sl-wrap">
            <span className="sl-badge">
              <i aria-hidden="true"></i>Websites for people who aren’t developers
            </span>
            <h1>
              The easiest way to get <span className="sl-accent">a real website online.</span>
            </h1>
            <p className="sl-lede">
              Answer a few questions on WhatsApp. Opsra builds it, hosts it and puts it on its own address, with no
              developer and no code.
            </p>

            <div className="sl-prompt">
              <span className="sl-label">An example of what you’d tell us</span>
              <p className="sl-prompt-text" aria-live="polite">
                {TABS[tab].text}
              </p>
              <div className="sl-prompt-row">
                <span className="sl-prompt-hint">Photos come straight from your phone</span>
                <a className="sl-btn sl-wa" href={START_HREF} {...START_ATTRS} data-start>
                  Start on WhatsApp
                </a>
                <a className="sl-btn sl-teal" href="#how">
                  See how it works
                </a>
              </div>
            </div>

            <div className="sl-tabs" role="group" aria-label="Who is it for?">
              {TABS.map((x, i) => (
                <button
                  key={x.label}
                  type="button"
                  aria-pressed={tab === i}
                  className={tab === i ? "sl-on" : ""}
                  onClick={() => setTab(i)}
                >
                  {x.label}
                </button>
              ))}
            </div>

            <div className="sl-meta">
              <span>No code</span>
              <span>No developer</span>
              <span>
                <b>3</b> sites free to try
              </span>
            </div>
          </div>
        </section>

        <section className="sl-sites" id="sites">
          <div className="sl-wrap">
            <div className="sl-head">
              <span className="sl-label">{SITES_SAMPLE ? "Sample sites" : "Live today"}</span>
              <h2>{SITES_SAMPLE ? "Three businesses. Three looks. No two alike." : "Real websites. Open them and see."}</h2>
              <p>
                {SITES_SAMPLE
                  ? "Made with the same site builder you’ll use. Each one started as a short brief, and each got its own layout, colours and fonts."
                  : "These are live, working sites, shown as they are right now and not as pictures. Click one to open it."}
              </p>
            </div>
            <div className="sl-site-grid">
              {REAL_SITES.map((s) => {
                const inner = (
                  <>
                    <Browser
                      url={s.url}
                      shot={s.d}
                      live={SITES_SAMPLE ? undefined : s.href}
                      title={`Live preview of ${s.name}`}
                      label={`Website for ${s.name}, ${s.kind}`}
                    />
                    <div className="sl-site-cap">
                      <div>
                        <b>
                          {s.name}
                          {s.tag ? <i className="sl-tag">{s.tag}</i> : null}
                        </b>
                        <span>{s.kind}</span>
                      </div>
                      {s.href ? <em>Visit site {ARROW}</em> : null}
                    </div>
                  </>
                );
                return s.href ? (
                  <a
                    key={s.name}
                    className="sl-site"
                    href={s.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`Open ${s.name} in a new tab`}
                  >
                    {inner}
                  </a>
                ) : (
                  <figure key={s.name} className="sl-site">
                    {inner}
                  </figure>
                );
              })}
            </div>
            {STATS.length > 0 && (
              <div className="sl-stats">
                {STATS.map((s) => (
                  <div key={s.label}>
                    <b>{s.value}</b>
                    <span>{s.label}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        <section className="sl-how" id="how">
          <div className="sl-wrap">
            <div className="sl-head">
              <span className="sl-label">From a message to a website</span>
              <h2>From idea to live site in four steps.</h2>
              <p>Two of them are just answering questions.</p>
            </div>
            <div className="sl-how-grid">
              <div className="sl-steps" id="steps">
                {STEPS.map(([lab, h, p], i) => (
                  <div
                    key={lab}
                    className={`sl-step${i === 0 ? " sl-on" : ""}`}
                    data-i={i}
                    tabIndex="0"
                    role="button"
                    aria-label={`Show step ${i + 1}: ${h}`}
                  >
                    <span className="sl-label">{lab}</span>
                    <h3>{h}</h3>
                    <p>{p}</p>
                  </div>
                ))}
              </div>
              <div className="sl-dev" aria-hidden="true">
                <div className="sl-d sl-d-phone sl-on" data-s="0">
                  <div className="sl-phone">
                    <div className="sl-pscr">
                      <div className="sl-chat">
                        <div className="sl-hd">
                          <span className="sl-av"></span>
                          <div>
                            <b>Opsra Site Builder</b>
                            <small>online</small>
                          </div>
                        </div>
                        <div className="sl-bd">
                          <div className="sl-msg sl-in">
                            {
                              "Hi Adaeze! What would you like to do?\n\n1. Start a new site\n2. My sites\n3. Talk to a person\n\nYou can also type MENU, MY SITES, STATUS or HUMAN at any time."
                            }
                          </div>
                          <div className="sl-msg sl-out">
                            1<em>09:38</em>
                          </div>
                          <div className="sl-msg sl-in">
                            {
                              "How would you like to start?\n\n1. Fill the form myself\n2. Get a link for my client to fill in\n3. Answer here on WhatsApp\n\nReply with 1, 2 or 3 (or MENU to go back)."
                            }
                          </div>
                          <div className="sl-msg sl-out">
                            3<em>09:39</em>
                          </div>
                        </div>
                        <div className="sl-composer">
                          <span>Message</span>
                          <i></i>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                <div className="sl-d sl-d-phone" data-s="1">
                  <div className="sl-phone">
                    <div className="sl-pscr">
                      <div className="sl-chat">
                        <div className="sl-hd">
                          <span className="sl-av"></span>
                          <div>
                            <b>Opsra Site Builder</b>
                            <small>online</small>
                          </div>
                        </div>
                        <div className="sl-bd">
                          <div className="sl-msg sl-in">
                            {
                              "How would you like to start?\n\n1. Fill the form myself\n2. Get a link for my client to fill in\n3. Answer here on WhatsApp"
                            }
                          </div>
                          <div className="sl-msg sl-out">
                            3<em>09:41</em>
                          </div>
                          <div className="sl-msg sl-out sl-ph">
                            <i className="sl-i-chat_photo"></i>
                            <span>Our team at work</span>
                          </div>
                          <div className="sl-msg sl-in">Got it! Send another, or reply DONE when finished.</div>
                          <div className="sl-msg sl-out">
                            DONE<em>09:43</em>
                          </div>
                          <div className="sl-msg sl-in">
                            That’s everything — thank you! Your brief is complete and our team will start building your
                            preview.
                          </div>
                        </div>
                        <div className="sl-composer">
                          <span>Message</span>
                          <i></i>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                <div className="sl-d sl-d-wide" data-s="2">
                  <div className="sl-browser">
                    <div className="sl-bar">
                      <i></i>
                      <i></i>
                      <i></i>
                      <span>Preview — not yet live</span>
                    </div>
                    <div className="sl-swap" id="swap">
                      <div className="sl-shot sl-on sl-i-coach_d0" data-k="0"></div>
                      <div className="sl-shot sl-i-coach_market_d0" data-k="1"></div>
                      <div className="sl-shot sl-i-coach_studio_d0" data-k="2"></div>
                    </div>
                  </div>
                  <div className="sl-designs" role="group" aria-label="Try another design">
                    <button type="button" aria-pressed="true" data-k="0">
                      Design one
                    </button>
                    <button type="button" aria-pressed="false" data-k="1">
                      Design two
                    </button>
                    <button type="button" aria-pressed="false" data-k="2">
                      Design three
                    </button>
                  </div>
                  <p className="sl-cap">Same business, three looks</p>
                </div>
                <div className="sl-d sl-d-wide" data-s="3">
                  <Browser url="clearwater.com.ng" shot="accounts_d0" label="A finished site on its own address" />
                  <p className="sl-cap">Live on its own address</p>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="sl-built" aria-labelledby="bh">
          <div className="sl-wrap">
            <div className="sl-built-box">
              <h2 id="bh">The hard parts are handled. You just run the business.</h2>
              <p>What you bring: a phone, some photos and your idea. Code, design and hosting aren’t on the list.</p>
              <ul>
                {CHIPS.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        <section className="sl-ways" id="ways">
          <div className="sl-wrap">
            <div className="sl-ways-grid">
              <article className="sl-way">
                <span className="sl-label">For your own brand</span>
                <h3>Launch it yourself. Keep every decision.</h3>
                <p>
                  You’ve got a business, a practice or a project that deserves a proper website. Build it today, in your
                  words, without waiting on a developer.
                </p>
                <ul>
                  <li>Change any word, photo or colour yourself, whenever you like</li>
                  <li>Not right yet? Ask for another design, and undo your last 20 changes</li>
                  <li>Your site sits on a domain registered in your name</li>
                  <li>Build and preview your first 3 sites free</li>
                </ul>
                <a className="sl-btn sl-teal" href={START_HREF} {...START_ATTRS} data-start>
                  Build my site {ARROW}
                </a>
              </article>
              <article className="sl-way sl-dark">
                <span className="sl-label">To earn from it</span>
                <h3>Build sites for others. Get paid for them.</h3>
                <p>
                  Know a shop, a clinic or a school that needs a website? You don’t need technical skills to be the
                  person who gets it done, only a phone.
                </p>
                <ul>
                  <li>Take their details on WhatsApp, or send a form link they fill in on their own phone</li>
                  <li>See the trade price and a suggested client price before you pay</li>
                  <li>The site goes live under your client’s name, with no Opsra branding on the preview</li>
                  <li>No code, no design skills, no hosting know-how</li>
                </ul>
                <a className="sl-btn sl-light" href={START_HREF} {...START_ATTRS} data-start>
                  Start earning {ARROW}
                </a>
              </article>
            </div>
          </div>
        </section>

        {QUOTES.length > 0 && (
          <section className="sl-quotes" aria-labelledby="qh">
            <div className="sl-wrap">
              <div className="sl-head">
                <h2 id="qh">Never built a website? Neither had they.</h2>
              </div>
              <div className="sl-quote-grid">
                {QUOTES.map((q) => (
                  <figure key={q.who} className="sl-quote">
                    <blockquote>{q.text}</blockquote>
                    <figcaption>
                      <b>{q.who}</b>
                      <span>{q.role}</span>
                    </figcaption>
                  </figure>
                ))}
              </div>
            </div>
          </section>
        )}

        <section className="sl-price" id="pricing">
          <div className="sl-wrap">
            <div className="sl-price-box">
              <h2>Try it before you pay anything.</h2>
              <p>Build and preview 3 sites for free. Pay only when one goes live.</p>
              <p>Selling sites regularly? ₦5,000 a month keeps you building after your third.</p>
              <a className="sl-btn sl-light" href={START_HREF} {...START_ATTRS} data-start>
                Build my first site free {ARROW}
              </a>
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

        <section className="sl-signin" id="start" aria-labelledby="sih">
          <div className="sl-wrap sl-signin-grid">
            <div>
              <span className="sl-label">Ready when you are</span>
              <h2 id="sih">Start your website today.</h2>
              <p className="sl-sub">
                Begin on WhatsApp or right here on the web, and pick it up again whenever you like. Already building?
                Sign in on the right, with no password.
              </p>
              {JOIN_URL && (
                <div className="sl-cta">
                  <a className="sl-btn sl-wa" href={JOIN_URL} target="_blank" rel="noopener noreferrer">
                    Start on WhatsApp {ARROW}
                  </a>
                </div>
              )}
            </div>
            <div className="sl-box-in" id="signin">
              <span className="sl-label">Your account</span>
              <h3>Sign in or create your account.</h3>
              <AuthPanel inputRef={mainInputRef} />
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

      <dialog
        className="sl-sheet"
        ref={sheetRef}
        aria-labelledby="sl-shh"
        onClick={(e) => {
          if (e.target === sheetRef.current) sheetRef.current.close();
        }}
      >
        <div className="sl-sheet-in">
          <button
            className="sl-x"
            type="button"
            aria-label="Close"
            onClick={() => sheetRef.current && sheetRef.current.close()}
          >
            ×
          </button>
          <span className="sl-label">Welcome</span>
          <h2 id="sl-shh">Sign in or sign up.</h2>
          <AuthPanel inputRef={sheetInputRef} />
        </div>
      </dialog>
    </div>
  );
}
