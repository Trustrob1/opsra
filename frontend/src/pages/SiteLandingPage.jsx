/**
 * frontend/src/pages/SiteLandingPage.jsx
 * SITE-LANDING — public landing page for Opsra Sites, with passwordless sign-in.
 * Registered in App.jsx at `/sites` and `/builders`, and also shown at `/b/login`
 * when a builder arrives without a magic-link token.
 *
 * Standalone page (no AppShell, no staff auth), same family as BuilderPortalPage /
 * SiteBriefFormPage. Styles live in SiteLandingPage.css, scoped under `.sl` with
 * every class prefixed `sl-`, so nothing leaks into or out of the staff app.
 * Images are in /public/sites-landing/ (real renders from the site engine).
 *
 * POSITIONING: "If you can use WhatsApp, you can build a website." Two audiences:
 * people launching their own brand (full control, no developer) and people who
 * want to earn by building and selling sites without technical skills.
 *
 * SIGN-IN: builders have no password. They type the WhatsApp number they registered
 * with and the server sends a single-use link to THEIR OWN WhatsApp and email
 * (POST /api/v1/builder/auth/request-link). The link never comes back to this page
 * and the reply is identical for unknown numbers.
 *
 * No animation libraries: the sticky-device steps use IntersectionObserver, the
 * manifesto fades on scroll, the hero reveals with CSS. Everything is readable
 * with JS off and with prefers-reduced-motion.
 *
 * OWNER SETTINGS: set VITE_BUILDER_JOIN_URL (a wa.me link to the Site Builder
 * WhatsApp number) so "Start building" opens WhatsApp. Unset, it scrolls to the
 * sign-in box.
 */
import { useEffect, useId, useRef, useState } from "react";
import { requestBuilderLink, errorMessage } from "../services/builder_portal.service";
import "./SiteLandingPage.css";

const JOIN_URL = import.meta.env.VITE_BUILDER_JOIN_URL || "";
const START_HREF = JOIN_URL || "#start";
const START_ATTRS = JOIN_URL ? { target: "_blank", rel: "noopener noreferrer" } : {};

const TITLE = "Opsra Sites | Build a website on WhatsApp";
const DESC =
  "If you can use WhatsApp or fill in a simple form, you can build a website. Launch your own brand, or build sites for others and get paid. No developer, no code.";

const FAQ = [
  [
    "Do I need to know how to code or design?",
    "No. If you can send a WhatsApp message or fill in an online form, you can build a website. The technical side is taken care of.",
  ],
  [
    "Can I do everything on WhatsApp?",
    "Yes. You can start a site, send photos and answer every question in a WhatsApp chat, or use the simple online form instead.",
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
      <button className="sl-btn sl-onblue" type="submit" disabled={stage === "sending"}>
        <span>{stage === "sending" ? "Sending…" : "Send my sign-in link"}</span>
        {ARROW}
      </button>
    </form>
  );
}

export default function SiteLandingPage() {
  const rootRef = useRef(null);
  const sheetRef = useRef(null);
  const mainInputRef = useRef(null);
  const sheetInputRef = useRef(null);

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
      "https://api.fontshare.com/v2/css?f[]=clash-display@500,600,700&f[]=satoshi@400,500,700&display=swap",
      "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap",
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

    /* nav: solid after a little scroll, hides on the way down */
    const nav = root.querySelector(".sl-nav");
    let lastY = window.scrollY;
    const onScroll = () => {
      const y = window.scrollY;
      nav.classList.toggle("sl-solid", y > 40);
      nav.classList.toggle("sl-away", y > lastY && y > 400);
      lastY = y;
    };
    on(window, "scroll", onScroll, { passive: true });

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

    /* manifesto: words fade in as it scrolls past */
    const mf = root.querySelector("[data-scrub]");
    if (mf && !reduce) {
      if (!mf.dataset.split) {
        const split = (node) => {
          [...node.childNodes].forEach((n) => {
            if (n.nodeType === 3) {
              const f = document.createDocumentFragment();
              n.textContent.split(/(\s+)/).forEach((tok) => {
                if (!tok) return;
                if (/^\s+$/.test(tok)) f.appendChild(document.createTextNode(tok));
                else {
                  const s = document.createElement("span");
                  s.className = "sl-w";
                  s.textContent = tok;
                  f.appendChild(s);
                }
              });
              n.replaceWith(f);
            } else if (n.nodeType === 1) split(n);
          });
        };
        split(mf);
        mf.dataset.split = "1";
      }
      const words = [...mf.querySelectorAll(".sl-w")];
      let raf = 0;
      const paint = () => {
        raf = 0;
        const r = mf.getBoundingClientRect(),
          vh = window.innerHeight;
        const p = Math.min(1, Math.max(0, (vh * 0.75 - r.top) / (r.height + vh * 0.3)));
        words.forEach((w, i) => {
          w.style.opacity = String(0.22 + 0.78 * Math.min(1, Math.max(0, p * words.length * 1.15 - i)));
        });
      };
      const queue = () => {
        if (!raf) raf = requestAnimationFrame(paint);
      };
      on(window, "scroll", queue, { passive: true });
      on(window, "resize", queue);
      paint();
      undo.push(() => {
        if (raf) cancelAnimationFrame(raf);
      });
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
          <ul>
            <li>
              <a href="#ways">Two ways in</a>
            </li>
            <li>
              <a href="#how">How it works</a>
            </li>
            <li>
              <a href="#sites">Sample sites</a>
            </li>
            <li>
              <a href="#faq">Questions</a>
            </li>
          </ul>
          <div className="sl-right">
            <button className="sl-signin-link" type="button" data-open-signin>
              Sign in
            </button>
            <a className="sl-btn sl-blue sl-magnetic" href={START_HREF} {...START_ATTRS} data-start>
              Start building
            </a>
          </div>
        </div>
      </header>
      <main id="main">
        <section className="sl-hero" id="top">
          <div className="sl-wrap">
            <div className="sl-top">
              <span className="sl-label">Websites for people who aren’t developers</span>
              <span className="sl-label">WhatsApp · Simple form</span>
            </div>
            <h1>
              <span className="sl-l">
                <span>If you can use</span>
              </span>
              <span className="sl-l">
                <span>WhatsApp, you can</span>
              </span>
              <span className="sl-l">
                <span className="sl-blue">build a website.</span>
              </span>
            </h1>
            <div className="sl-hero-row">
              <div className="sl-hero-copy">
                <p className="sl-lede">
                  Answer a few questions in a chat, or fill in a simple form. The technical side is taken care of, so
                  you stay focused on the business, the brand or the clients.
                </p>
                <p className="sl-lede">
                  Launch your own brand with full control, or build websites for others and get paid for it.
                </p>
                <div className="sl-hero-cta">
                  <a className="sl-btn sl-blue sl-magnetic" href={START_HREF} {...START_ATTRS} data-start>
                    Start building{" "}
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
                  </a>
                  <a className="sl-tlink" href="#how">
                    See how it works
                  </a>
                </div>
                <div className="sl-hero-meta">
                  <span>No code</span>
                  <span>No developer</span>
                  <span>
                    <b>3</b> sites free to try
                  </span>
                </div>
              </div>
              <div className="sl-rig">
                <div
                  className="sl-laptop sl-lift"
                  role="img"
                  aria-label="A coaching business website built with Opsra, shown on a laptop"
                >
                  <div className="sl-lid">
                    <div className="sl-screen">
                      <div className="sl-chrome">
                        <i></i>
                        <i></i>
                        <i></i>
                        <span>brightpath.com.ng</span>
                      </div>
                      <div className="sl-shot sl-i-coach_d0"></div>
                    </div>
                  </div>
                  <div className="sl-base"></div>
                </div>
                <div className="sl-phone-w sl-lift">
                  <div
                    className="sl-phone"
                    role="img"
                    aria-label="A WhatsApp chat where a person sends a photo and finishes their brief"
                  >
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
              </div>
            </div>
          </div>
        </section>
        <section className="sl-manifesto" aria-labelledby="mf">
          <div className="sl-wrap">
            <p id="mf" data-scrub>
              You decide what it says, how it looks and who it’s for.{" "}
              <em>Nobody stands between you and your own website</em>, and you never have to learn a line of code.
            </p>
          </div>
        </section>
        <section className="sl-ways" id="ways">
          <div className="sl-wrap">
            <div className="sl-sec-head">
              <h2>Two ways to use it. One easy start.</h2>
              <span className="sl-label">Pick the one that sounds like you</span>
            </div>
            <div className="sl-ways-grid">
              <article className="sl-way">
                <div
                  className="sl-art sl-art-a"
                  role="img"
                  aria-label="A website for a business owner's own brand, on a laptop and a phone"
                >
                  <div className="sl-laptop sl-lift">
                    <div className="sl-lid">
                      <div className="sl-screen">
                        <div className="sl-shot sl-i-accounts_d1"></div>
                      </div>
                    </div>
                    <div className="sl-base"></div>
                  </div>
                  <div className="sl-phone-w sl-lift">
                    <div className="sl-phone">
                      <div className="sl-pscr">
                        <div className="sl-shot sl-i-coach_m1"></div>
                      </div>
                    </div>
                  </div>
                </div>
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
              </article>
              <article className="sl-way">
                <div className="sl-art sl-art-b" role="img" aria-label="Three different websites on three phones">
                  <div className="sl-phone-w sl-p1 sl-lift">
                    <div className="sl-phone">
                      <div className="sl-pscr">
                        <div className="sl-shot sl-i-coach_m0"></div>
                      </div>
                    </div>
                  </div>
                  <div className="sl-phone-w sl-p2 sl-lift">
                    <div className="sl-phone">
                      <div className="sl-pscr">
                        <div className="sl-shot sl-i-academy_m0"></div>
                      </div>
                    </div>
                  </div>
                  <div className="sl-phone-w sl-p3 sl-lift">
                    <div className="sl-phone">
                      <div className="sl-pscr">
                        <div className="sl-shot sl-i-accounts_m0"></div>
                      </div>
                    </div>
                  </div>
                </div>
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
              </article>
            </div>
          </div>
        </section>
        <section className="sl-how" id="how">
          <div className="sl-wrap">
            <div className="sl-sec-head">
              <h2>From a message to a website.</h2>
              <span className="sl-label">Four steps. Two of them are just answering questions.</span>
            </div>
            <div className="sl-how-grid">
              <div className="sl-steps" id="steps">
                <div
                  className="sl-step sl-on"
                  data-i="0"
                  tabIndex="0"
                  role="button"
                  aria-label="Show step 1: Start a chat"
                >
                  <span className="sl-label">01 · Start</span>
                  <h3>Message us, or open the form.</h3>
                  <p>
                    Reply with a number to choose what you want to do. Answer on WhatsApp, fill the form yourself, or
                    get a link to hand to your client.
                  </p>
                </div>
                <div
                  className="sl-step"
                  data-i="1"
                  tabIndex="0"
                  role="button"
                  aria-label="Show step 2: Answer a few questions"
                >
                  <span className="sl-label">02 · Tell us</span>
                  <h3>Answer a few easy questions.</h3>
                  <p>
                    Your business name, what you sell, a few photos from your phone. The form saves as you go, so you
                    can come back to it.
                  </p>
                </div>
                <div className="sl-step" data-i="2" tabIndex="0" role="button" aria-label="Show step 3: Make it yours">
                  <span className="sl-label">03 · Make it yours</span>
                  <h3>See your site, then change anything.</h3>
                  <p>
                    Words, photos, colours, layout. Don’t love the look? Ask for another design. Every site is matched
                    to the business, so yours won’t look like anyone else’s.
                  </p>
                </div>
                <div className="sl-step" data-i="3" tabIndex="0" role="button" aria-label="Show step 4: Go live">
                  <span className="sl-label">04 · Go live</span>
                  <h3>Put your name on the internet.</h3>
                  <p>
                    Choose when to launch. Your website gets its own address, and you’re in charge of it from the first
                    day.
                  </p>
                </div>
              </div>
              <div className="sl-dev" aria-hidden="true">
                <div className="sl-d sl-d-phone sl-on" data-s="0">
                  <div className="sl-phone sl-lift">
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
                  <div className="sl-phone sl-lift">
                    <div className="sl-pscr">
                      <div className="sl-form">
                        <span className="sl-tag">Saved just now</span>
                        <h4>Tell us about your business</h4>
                        <div className="sl-f">
                          <span>Business name</span>
                          <b>Bright Path</b>
                        </div>
                        <div className="sl-f">
                          <span>What do you offer?</span>
                          <div className="sl-row2">
                            <b>One-to-one coaching</b>
                            <b className="sl-ph">Price (₦)</b>
                          </div>
                        </div>
                        <div className="sl-f">
                          <span>Photos</span>
                          <b className="sl-ph">Add from your phone</b>
                        </div>
                        <span className="sl-pill">Send it in</span>
                      </div>
                    </div>
                  </div>
                </div>
                <div className="sl-d sl-d-laptop" data-s="2">
                  <div className="sl-laptop sl-lift">
                    <div className="sl-lid">
                      <div className="sl-screen">
                        <div className="sl-chrome">
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
                    </div>
                    <div className="sl-base"></div>
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
                <div className="sl-d sl-d-laptop" data-s="3">
                  <div className="sl-laptop sl-lift">
                    <div className="sl-lid">
                      <div className="sl-screen">
                        <div className="sl-chrome">
                          <i></i>
                          <i></i>
                          <i></i>
                          <span>clearwater.com.ng</span>
                        </div>
                        <div className="sl-shot sl-i-accounts_d0"></div>
                      </div>
                    </div>
                    <div className="sl-base"></div>
                  </div>
                  <p className="sl-cap">Live on its own address</p>
                </div>
              </div>
            </div>
          </div>
        </section>
        <section className="sl-gallery" id="sites">
          <div className="sl-wrap">
            <div className="sl-sec-head">
              <h2>Three businesses. Three looks. No two alike.</h2>
              <span className="sl-label">Sample sites</span>
            </div>
            <div className="sl-g-grid">
              <figure className="sl-g-item" style={{ margin: 0 }}>
                <div className="sl-g-art">
                  <div className="sl-laptop sl-lift" role="img" aria-label="Sample site for a coaching business">
                    <div className="sl-lid">
                      <div className="sl-screen">
                        <div className="sl-shot sl-i-coach_d0"></div>
                      </div>
                    </div>
                    <div className="sl-base"></div>
                  </div>
                  <div className="sl-phone-w sl-lift">
                    <div className="sl-phone">
                      <div className="sl-pscr">
                        <div className="sl-shot sl-i-coach_m0"></div>
                      </div>
                    </div>
                  </div>
                </div>
                <figcaption className="sl-g-cap">
                  <b>Bright Path</b>
                  <span>A coach, Lagos</span>
                </figcaption>
              </figure>
              <figure className="sl-g-item" style={{ margin: 0 }}>
                <div className="sl-g-art">
                  <div className="sl-laptop sl-lift" role="img" aria-label="Sample site for a training academy">
                    <div className="sl-lid">
                      <div className="sl-screen">
                        <div className="sl-shot sl-i-academy_d0"></div>
                      </div>
                    </div>
                    <div className="sl-base"></div>
                  </div>
                  <div className="sl-phone-w sl-lift">
                    <div className="sl-phone">
                      <div className="sl-pscr">
                        <div className="sl-shot sl-i-academy_m0"></div>
                      </div>
                    </div>
                  </div>
                </div>
                <figcaption className="sl-g-cap">
                  <b>Sparkhub</b>
                  <span>A school, Lagos</span>
                </figcaption>
              </figure>
              <figure className="sl-g-item" style={{ margin: 0 }}>
                <div className="sl-g-art">
                  <div className="sl-laptop sl-lift" role="img" aria-label="Sample site for an accounting firm">
                    <div className="sl-lid">
                      <div className="sl-screen">
                        <div className="sl-shot sl-i-accounts_d0"></div>
                      </div>
                    </div>
                    <div className="sl-base"></div>
                  </div>
                  <div className="sl-phone-w sl-lift">
                    <div className="sl-phone">
                      <div className="sl-pscr">
                        <div className="sl-shot sl-i-accounts_m0"></div>
                      </div>
                    </div>
                  </div>
                </div>
                <figcaption className="sl-g-cap">
                  <b>Clearwater</b>
                  <span>A firm, Lagos</span>
                </figcaption>
              </figure>
            </div>
            <p className="sl-g-note">
              These are sample businesses made with the same site builder you’ll use. Each one started as a short brief,
              and each got its own layout, colours and fonts.
            </p>
          </div>
        </section>
        <section className="sl-need sl-inv" id="need" aria-labelledby="nh">
          <div className="sl-wrap">
            <span className="sl-label">What you bring</span>
            <h2 id="nh">
              <span>A phone.</span>
              <span>Some photos.</span>
              <span>Your idea.</span>
            </h2>
            <div className="sl-need-rows">
              <div className="sl-need-row">
                <b>The phone</b>
                <span>A WhatsApp chat or a simple web form. Your pick.</span>
              </div>
              <div className="sl-need-row">
                <b>The photos</b>
                <span>Straight from your camera roll. No editing needed.</span>
              </div>
              <div className="sl-need-row">
                <b>The idea</b>
                <span>A sentence or two about what you do, and who it’s for.</span>
              </div>
            </div>
            <p className="sl-after">That’s the whole list. Code, design and hosting aren’t on it.</p>
          </div>
        </section>
        <section className="sl-charge" id="charge">
          <div className="sl-wrap">
            <div className="sl-sec-head" style={{ marginBottom: "var(--s8)" }}>
              <h2>You’re in charge of it.</h2>
              <span className="sl-label">From the first word to the final price</span>
            </div>
            <div className="sl-prow">
              <h3>Your words</h3>
              <p>Write them in a form or say them in a chat. Change them whenever you like, without asking anyone.</p>
            </div>
            <div className="sl-prow">
              <h3>Your look</h3>
              <p>
                Colours, fonts and layouts are matched to your business. Ask for another design, and undo your last 20
                changes.
              </p>
            </div>
            <div className="sl-prow">
              <h3>Your name</h3>
              <p>The domain is registered in the owner’s name, and previews you show carry no Opsra branding.</p>
            </div>
            <div className="sl-prow">
              <h3>Your income</h3>
              <p>
                Sell the sites you build. Your portal shows the trade price and a suggested client price before you pay.
              </p>
            </div>
          </div>
        </section>
        <section className="sl-price" id="pricing">
          <div className="sl-wrap">
            <div className="sl-price-box">
              <h2>
                Try it before<span className="sl-sub">you pay anything.</span>
              </h2>
              <div>
                <p>Build and preview 3 sites for free. Pay only when one goes live.</p>
                <p>Selling sites regularly? ₦5,000 a month keeps you building after your third.</p>
              </div>
            </div>
          </div>
        </section>
        <section className="sl-faq" id="faq">
          <div className="sl-wrap">
            <div className="sl-faq-grid">
              <h2>Good questions.</h2>
              <div>
                <details>
                  <summary>Do I need to know how to code or design?</summary>
                  <p>
                    No. If you can send a WhatsApp message or fill in an online form, you can build a website. The
                    technical side is taken care of.
                  </p>
                </details>
                <details>
                  <summary>Can I do everything on WhatsApp?</summary>
                  <p>
                    Yes. You can start a site, send photos and answer every question in the chat. Or use the simple
                    online form instead. Both lead to the same website.
                  </p>
                </details>
                <details>
                  <summary>Can I change the site after it’s made?</summary>
                  <p>
                    Yes. Change words, photos, colours and layout yourself. You can ask for another design, and undo
                    your last 20 changes.
                  </p>
                </details>
                <details>
                  <summary>Can I build websites for other people and sell them?</summary>
                  <p>
                    Yes. Build a site for a client, or send them a form link to fill in on their own phone. Your portal
                    shows the trade price and a suggested client price before you pay.
                  </p>
                </details>
                <details>
                  <summary>Whose name is the domain in?</summary>
                  <p>The site owner’s. That’s you for your own brand, or your client for a site you sold.</p>
                </details>
              </div>
            </div>
          </div>
        </section>
        <section className="sl-signin sl-inv" id="start" aria-labelledby="sih">
          <div className="sl-wrap">
            <div>
              <span className="sl-label">Ready when you are</span>
              <h2 id="sih">Start your website today.</h2>
              <p className="sl-sub">
                Begin on WhatsApp or with the form, and pick it up again whenever you like. Already building? Sign in on
                the right, with no password.
              </p>
              {JOIN_URL && (
                <div className="sl-cta">
                  <a className="sl-btn sl-onblue" href={JOIN_URL} target="_blank" rel="noopener noreferrer">
                    Start on WhatsApp{" "}
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
                  </a>
                </div>
              )}
            </div>
            <div className="sl-box-in" id="signin">
              <span className="sl-label">Already building?</span>
              <h3>Sign in with your WhatsApp number.</h3>
              <SignInForm inputRef={mainInputRef} />
            </div>
          </div>
        </section>
      </main>
      <footer className="sl-foot">
        <div className="sl-wrap">
          <div className="sl-word" aria-hidden="true">
            opsra
          </div>
          <div className="sl-row">
            <span>© {new Date().getFullYear()} Opsra</span>
            <div>
              <a href="/privacy">Privacy</a>
              <a href="/terms">Terms</a>
            </div>
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
          <span className="sl-label">Welcome back</span>
          <h2 id="sl-shh">Sign in.</h2>
          <SignInForm inputRef={sheetInputRef} />
        </div>
      </dialog>
    </div>
  );
}
