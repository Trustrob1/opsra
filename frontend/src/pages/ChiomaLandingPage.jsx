/**
 * frontend/src/pages/ChiomaLandingPage.jsx
 * CHIOMA-LANDING-1 — public landing page for Chioma, Opsra's web chat assistant. Registered in App.jsx at `/chioma`.
 * Standalone page (no AppShell, no staff auth). Styles: ChiomaLandingPage.css, scoped under `.ch`, every class prefixed `ch-`.
 * Look follows /business (OwnerLandingPage): indigo hero, Hanken Grotesk, pastel cards, dark section, rounded CTA band.
 *
 * THINGS TRUST EDITS (all at the top of this file):
 *   SALES_WA, DEMO_WA     international format, digits only.
 *   DEMO_KEY              the web chat key (wc_...) of the business whose chat the "Chat with Chioma now" button opens.
 *                         Empty = the button opens the WhatsApp demo instead. Use a dedicated demo business, not a customer's.
 *   START_HREF            where "Start free" goes: the public sign-up page /start/chat (WEB-ONLY-1b).
 *   PRICES                the plan figures shown. Change here, nowhere else.
 *
 * IMAGES (frontend/public/images): chioma.jpg (new), usecase-*.jpg and lead-center.jpg (shared with /business).
 * The Lead Center screenshot shows real first names from a client org (used with permission; see OwnerLandingPage).
 * The chat in the hero is an EXAMPLE conversation, labelled as such. It loops and stops for reduced-motion visitors.
 */
import { useEffect, useState } from "react";
import "./ChiomaLandingPage.css";

const SALES_WA = "2348056055896";
const DEMO_WA = "14753274055";
const DEMO_KEY = "";

const waHref = (num, text) => `https://wa.me/${num}?text=${encodeURIComponent(text)}`;
const START_HREF = "/start/chat";

const PRICES = {
  freeCredit: "₦2,000",
  freeChats: "About 100 web chats",
  monthly: "₦15,000",
  includedChats: 300,
  includedAi: 300,
  perChat: "₦20",
  perAi: "about ₦12",
  chatBasic: "₦40,000",
};

const TITLE = "Chioma | A front desk for your website that never closes";
const DESC =
  "Chioma is a web chat assistant for your website. She greets visitors, answers from your own information, asks for a WhatsApp number in the chat and hands warm leads to your team. Start free.";

// The example chat. kind: u = visitor, c = Chioma, t = typing dots (start, end in seconds). One loop = LOOP seconds.
const LOOP = 30;
const CHAT = [
  ["u", 1.0, "Do you deliver to Abuja?"],
  ["t", 2.0, 3.4],
  ["c", 3.4, "Yes, we do. Delivery takes 2 to 3 days. Want me to check the Orthopaedic Mattress for you?"],
  ["u", 6.5, "Yes please"],
  ["t", 7.5, 9.0],
  ["c", 9.0, "It is in stock. Can I have your first name so the team can confirm the delivery fee?"],
  ["u", 12.5, "Tunde"],
  ["t", 13.5, 14.9],
  ["c", 14.9, "Thanks, Tunde. What is your WhatsApp number?"],
  ["u", 18.0, "My WhatsApp number (ends 567)"],
  ["t", 19.0, 20.4],
  ["c", 20.4, "Done. Our team will message you on WhatsApp shortly."],
];
const HOLD_UNTIL = 27.5;
const pc = (x) => Math.round((x / LOOP) * 100000) / 1000;

function chatKeyframes() {
  return CHAT.map((e, i) => {
    if (e[0] === "t") {
      const [, s, en] = e;
      return `@keyframes chm${i}{0%,${pc(s)}%{max-height:0;opacity:0}${pc(s + 0.25)}%,${pc(en - 0.2)}%{max-height:44px;opacity:1}${pc(en)}%,100%{max-height:0;opacity:0}}`;
    }
    const s = e[1];
    return `@keyframes chm${i}{0%,${pc(s)}%{max-height:0;opacity:0;transform:translateY(10px)}${pc(s + 0.35)}%,${pc(HOLD_UNTIL)}%{max-height:130px;opacity:1;transform:none}${pc(HOLD_UNTIL + 1.2)}%,100%{max-height:0;opacity:0}}`;
  }).join("\n");
}

const CARDS = [
  ["Greet", "ch-t-blue", "Knows the page they are on", "Looking at a product? Chioma opens with that product, then offers a menu you set."],
  ["Answer", "ch-t-purple", "Answers from your own information", "Prices, stock, sizes and delivery come from your catalog and notes, not guesses."],
  ["Capture", "ch-t-orange", "Asks for a WhatsApp number in the chat", "Name, number and a clear yes. Then it is a lead in your list, with the chat attached."],
  ["Hand over", "ch-t-green", "Your team steps in live", "Your team sees when the visitor is typing and replies in the same chat."],
];

const USECASES = [
  ["Coaches", "ch-c-blue", "Discovery calls, booked", "Turn curious visitors into scheduled conversations.", "/images/usecase-coaches.jpg", "A coach taking notes during a session"],
  ["Counsellors", "ch-c-purple", "Gentle, careful intake", "Welcome new clients warmly and pass sensitive chats to a person.", "/images/usecase-counsellors.jpg", "A counsellor speaking with a client"],
  ["Clinics", "ch-c-green", "Fewer missed enquiries", "Capture requests at any hour, even after closing.", "/images/usecase-clinics.jpg", "A doctor smiling with a patient"],
  ["Agencies", "ch-c-orange", "Qualified before the first call", "Ask the right questions so every briefing starts with facts.", "/images/usecase-agencies.jpg", "Two colleagues reviewing work on a tablet"],
];

const STEPS = [
  ["01", "Asks only when it helps", "After a question the AI cannot answer, or when someone wants a call-back or a booking."],
  ["02", "Gets consent first", "The visitor agrees to be contacted on WhatsApp before anything is saved."],
  ["03", "Finds existing customers", "A number you already have joins the same record, so nothing is duplicated."],
  ["04", "Never loses the thread", "Returning visitors a day later get a fresh view, with the earlier chat tucked away."],
];

const CAPS = [
  ["Menu you control", "Set the buttons visitors see. A default menu is ready on day one."],
  ["Shared team inbox", "Web chats sit with your WhatsApp conversations, so nobody checks two places."],
  ["Product cards in chat", "Show price, photo and stock inside the conversation. Visitors tap to order."],
  ["Hands off to a person", "Anything sensitive or unclear goes to your team, with the full history."],
  ["One line to install", "Paste a small script into your site. Shops built on Opsra have it built in."],
  ["Your data stays yours", "Each business has its own private workspace and customer records."],
];

const FAQ = [
  ["Do I need WhatsApp to use Chioma?", "No. Chioma works on your website on its own. Add a WhatsApp number later by upgrading to Chat Basic, and your chats and leads come with you."],
  ["How do I add it to my website?", "Paste one line of code into your site. Shops built on Opsra have it built in."],
  ["Will it say things that are not true?", "Chioma answers from your catalog and notes. When she does not know, she says so and passes the chat to your team."],
  ["Can my team reply in the same chat?", "Yes. Replies from your team appear in the visitor's chat, and you can see when the visitor is typing."],
  ["What does it cost after the free credit?", `${PRICES.monthly} a month includes ${PRICES.includedChats} web chats and ${PRICES.includedAi} AI answers. After that it is ${PRICES.perChat} a chat and ${PRICES.perAi} an AI answer, taken from your credit.`],
];

function Logo({ light }) {
  return (
    <a className={`ch-mark${light ? " ch-mark-light" : ""}`} href="/business" aria-label="Opsra home">
      <svg width="34" height="34" viewBox="0 0 34 34" fill="none" aria-hidden="true">
        <rect x="1" y="1" width="32" height="32" rx="10" fill={light ? "#2467E3" : "#fff"} />
        <path d="M17 8c5 0 9 3.4 9 7.8 0 4.4-4 7.8-9 7.8-1 0-2-.1-2.9-.4L10 25l1-3.4C9.4 20.2 8 18.1 8 15.8 8 11.4 12 8 17 8z" stroke={light ? "#fff" : "#3E56B4"} strokeWidth="2.2" strokeLinejoin="round" />
      </svg>
      Opsra
    </a>
  );
}

function ChatLoop() {
  return (
    <>
      {CHAT.map((e, i) =>
        e[0] === "t" ? (
          <div key={i} className="ch-mw" style={{ animationName: `chm${i}` }}><div className="ch-tp"><i /><i /><i /></div></div>
        ) : (
          <div key={i} className="ch-mw" style={{ animationName: `chm${i}` }}><div className={e[0] === "u" ? "ch-bu" : "ch-bc"}>{e[2]}</div></div>
        )
      )}
    </>
  );
}

export default function ChiomaLandingPage() {
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
      mainEntity: FAQ.map(([q, a]) => ({ "@type": "Question", name: q, acceptedAnswer: { "@type": "Answer", text: a } })),
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

  // The live demo: Chioma's own launcher is loaded only when the visitor asks for it, from DEMO_KEY.
  const openDemo = (ev) => {
    if (!DEMO_KEY) return; // the link then opens the WhatsApp demo
    ev.preventDefault();
    const open = () => { try { window.OpsraChat && window.OpsraChat.open(); } catch { /* the launcher stays closed */ } };
    if (window.OpsraChat) { open(); return; }
    const s = document.createElement("script");
    s.src = "/widget.js";
    s.async = true;
    s.setAttribute("data-key", DEMO_KEY);
    s.setAttribute("data-source", "chioma-page");
    s.onload = () => setTimeout(open, 900);
    document.body.appendChild(s);
  };
  const demoHref = DEMO_KEY ? "#demo" : waHref(DEMO_WA, "Hi");
  const demoTarget = DEMO_KEY ? undefined : "_blank";

  return (
    <div className="ch">
      <style>{chatKeyframes()}</style>
      <a className="ch-skip" href="#price">Skip to pricing</a>

      {/* HERO */}
      <div className="ch-hero">
        <header className={`ch-nav${solid ? " ch-solid" : ""}`}>
          <div className="ch-wrap ch-nav-row">
            <Logo />
            <nav aria-label="Main" className="ch-nav-links">
              <a className="ch-hide-m" href="#how">How it works</a>
              <a className="ch-hide-m" href="#cap">What it does</a>
              <a className="ch-hide-m" href="#price">Pricing</a>
              <a className="ch-hide-m" href="#questions">Questions</a>
              <a className="ch-hide-m" href="/business">Opsra for WhatsApp</a>
              <a className="ch-btn ch-btn-white ch-sm" href={START_HREF}>Start free</a>
            </nav>
          </div>
        </header>
        <div className="ch-wrap ch-hero-grid">
          <div className="ch-hero-copy">
            <p className="ch-eyebrow ch-eyebrow-light ch-hide-m">Meet Chioma, your web chat assistant</p>
            <h1>
              <span className="ch-h-long">Your website gets a front desk that never closes.</span>
              <span className="ch-h-short">Every website visitor gets a reply, in seconds.</span>
            </h1>
            <p className="ch-lede">
              <span className="ch-h-long">Chioma greets every visitor, answers from your own information, and asks for a WhatsApp number the way a person would. Your team picks up warm leads, with the whole chat in front of them.</span>
              <span className="ch-h-short">Meet Chioma. She answers, asks for a WhatsApp number and hands warm leads to your team.</span>
            </p>
            <div className="ch-cta-row ch-hide-m">
              <a className="ch-btn ch-btn-white" href={START_HREF}>Start free</a>
              <a className="ch-btn ch-btn-ghost" href={demoHref} target={demoTarget} rel="noopener noreferrer" onClick={openDemo}>Chat with Chioma now</a>
            </div>
            <p className="ch-fine ch-hide-m">{PRICES.freeCredit} free credit. No card, no time limit.</p>
          </div>
          <div className="ch-hero-phone">
            <div className="ch-orb" aria-hidden="true" />
            <div className="ch-iphone" role="img" aria-label="Example chat between a visitor and Chioma">
              <i className="ch-sb ch-sb1" aria-hidden="true" /><i className="ch-sb ch-sb2" aria-hidden="true" /><i className="ch-sb ch-sb3" aria-hidden="true" /><i className="ch-sb ch-sb4" aria-hidden="true" />
              <div className="ch-frame"><div className="ch-bezel"><div className="ch-screen">
                <span className="ch-island" aria-hidden="true" />
                <div className="ch-ph-head">
                  <span className="ch-time" aria-hidden="true">9:41</span>
                  <img src="/images/chioma.jpg" alt="" width="40" height="40" />
                  <span><b>Chioma</b><small>Online · Virtual assistant</small></span>
                  <em className="ch-ex">Example</em>
                </div>
                <div className="ch-ph-body" aria-hidden="true"><ChatLoop /></div>
                <div className="ch-ph-input" aria-hidden="true">Type your message</div>
                <span className="ch-home" aria-hidden="true" />
              </div></div></div>
            </div>
            <p className="ch-cap ch-hide-m">Example conversation</p>
          </div>
          <div className="ch-cta-row ch-show-m">
            <a className="ch-btn ch-btn-white" href={START_HREF}>Start free</a>
            <a className="ch-btn ch-btn-ghost" href={demoHref} target={demoTarget} rel="noopener noreferrer" onClick={openDemo}>Chat with Chioma now</a>
          </div>
        </div>
      </div>

      <main>
        <div className="ch-wrap ch-strip">
          <p className="ch-eyebrow ch-mute">Works on any website</p>
          <div className="ch-aud"><span>Online stores</span><span>Service businesses</span><span>Landing pages</span><span>Catalog sites</span><span>Agencies</span></div>
        </div>

        {/* MEET CHIOMA */}
        <section className="ch-wrap ch-sec ch-meet" aria-labelledby="meet-h">
          <div className="ch-meet-img">
            <i aria-hidden="true" />
            <img src="/images/chioma.jpg" alt="Chioma, the virtual assistant" width="420" height="420" />
            <span className="ch-online"><b aria-hidden="true" />Online now</span>
          </div>
          <div className="ch-meet-copy">
            <p className="ch-eyebrow ch-c-blue">Meet Chioma</p>
            <h2 id="meet-h" className="ch-h2">The friendly face of your business, on every page.</h2>
            <p className="ch-sub ch-left">Visitors meet Chioma, not a blank form. She is warm, quick and always on, and she knows when to bring in a real person.</p>
            <div className="ch-pills"><span className="ch-p-purple">Replies in seconds</span><span className="ch-p-green">Speaks your catalog</span><span className="ch-p-orange">Hands over to your team</span></div>
          </div>
        </section>

        {/* ON YOUR WEBSITE */}
        <section className="ch-site-band" aria-labelledby="site-h">
          <div className="ch-wrap ch-site-row">
            <div className="ch-site-copy">
              <p className="ch-eyebrow ch-c-blue">On your website</p>
              <h2 id="site-h" className="ch-h2">One small face. Every page covered.</h2>
              <p className="ch-sub ch-left">Chioma waits in the corner of your site. She says hello, mentions the product they are looking at, and opens the chat when they are ready.</p>
            </div>
            <div className="ch-site" role="img" aria-label="A shop page with Chioma's chat launcher in the corner">
              <div className="ch-site-bar"><i /><i /><i /><span>yourstore.com/orthopaedic-mattress</span></div>
              <div className="ch-site-page">
                <div className="ch-site-nav"><b>Your Store</b><span><i>Mattresses</i><i>Pillows</i><i>Delivery</i><i>Contact</i></span></div>
                <div className="ch-site-hero"><div className="ch-site-img" /><div><p className="ch-site-h">Orthopaedic Mattress</p><p className="ch-site-p">Firm support for a better back.</p><span className="ch-site-btn">Order on WhatsApp</span></div></div>
                <div className="ch-site-cards"><div><s /><b>Orthopaedic Mattress</b></div><div><s /><b>Cloud 9 Mattress</b></div><div><s /><b>Pillow set</b></div></div>
              </div>
              <div className="ch-launch">
                <div className="ch-greet">Hi, I&apos;m Chioma. Looking at the Orthopaedic Mattress? I can tell you the price, sizes and delivery.</div>
                <div className="ch-lau"><img src="/images/chioma.jpg" alt="" width="68" height="68" /></div>
                <i className="ch-dot" aria-hidden="true" />
              </div>
            </div>
          </div>
        </section>

        {/* FOUR CARDS */}
        <section className="ch-wrap ch-sec" id="how" aria-labelledby="how-h">
          <h2 id="how-h" className="ch-h2 ch-wide">Every visitor gets a reply, not a form.</h2>
          <div className="ch-cards">
            {CARDS.map(([tag, tone, title, text]) => (
              <article key={tag} className={`ch-card ${tone}`}>
                <p className="ch-eyebrow">{tag}</p>
                <h3>{title}</h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
        </section>

        {/* USE CASES */}
        <section className="ch-wrap ch-sec ch-sec-tight" aria-labelledby="uc-h">
          <h2 id="uc-h" className="ch-h2 ch-wide">Made for people who sell time and trust.</h2>
          <div className="ch-uc">
            {USECASES.map(([tag, tone, title, text, img, alt]) => (
              <article key={tag} className="ch-uc-card">
                <img src={img} alt={alt} loading="lazy" />
                <div><p className={`ch-eyebrow ${tone}`}>{tag}</p><h3>{title}</h3><p>{text}</p></div>
              </article>
            ))}
          </div>
        </section>

        {/* LEADS */}
        <section className="ch-wrap ch-sec ch-sec-tight" aria-labelledby="lead-h">
          <div className="ch-split">
            <div className="ch-split-l">
              <h2 id="lead-h" className="ch-h2">A lead, created the polite way.</h2>
              <p className="ch-sub ch-left">No pop-up form in the way. Chioma asks one thing at a time, checks the number, and only saves the lead after the visitor says yes.</p>
            </div>
            <ol className="ch-feat">
              {STEPS.map(([n, t, d]) => (<li key={n}><span>{n}</span><div><b>{t}</b><p>{d}</p></div></li>))}
            </ol>
          </div>
          <figure className="ch-shot">
            <div className="ch-shot-frame"><img src="/images/lead-center.jpg" alt="The Opsra Lead Center, where web chat leads arrive" loading="lazy" /></div>
            <figcaption>Chioma&apos;s leads land in the Lead Center, with the chat attached.</figcaption>
          </figure>
        </section>

        {/* DARK */}
        <section className="ch-dark" id="cap" aria-labelledby="dark-h">
          <div className="ch-wrap ch-sec">
            <h2 id="dark-h" className="ch-h2 ch-light">More than a chat bubble. A front desk that never closes.</h2>
            <div className="ch-caps">
              {CAPS.map(([t, d]) => (<article key={t}><h3>{t}</h3><p>{d}</p></article>))}
            </div>
          </div>
        </section>

        {/* PRICING */}
        <section className="ch-wrap ch-sec" id="price" aria-labelledby="price-h">
          <h2 id="price-h" className="ch-h2 ch-center">Start free. Pay one simple monthly price.</h2>
          <p className="ch-sub ch-center-block">No WhatsApp number needed. Chioma works on your website from day one.</p>
          <div className="ch-prices">
            <article className="ch-price ch-t-blue">
              <p className="ch-eyebrow">Start free</p>
              <p className="ch-fig">{PRICES.freeCredit} <small>free credit</small></p>
              <p>No card and no time limit. {PRICES.freeChats}, so you can see Chioma work on real visitors.</p>
              <a className="ch-btn ch-btn-blue" href={START_HREF}>Start free</a>
            </article>
            <article className="ch-price ch-t-purple">
              <p className="ch-eyebrow">Chioma plan</p>
              <p className="ch-fig">{PRICES.monthly} <small>a month</small></p>
              <ul>
                <li>{PRICES.includedChats} web chats included</li>
                <li>{PRICES.includedAi} AI answers from your own information</li>
                <li>Menu, product catalog and shared team inbox</li>
                <li>Leads saved with the chat attached</li>
                <li>After that: {PRICES.perChat} a chat, {PRICES.perAi} an AI answer, from your credit</li>
              </ul>
            </article>
          </div>
          <p className="ch-note">Want WhatsApp too? Upgrade to Chat Basic at {PRICES.chatBasic} a month. Your chats and leads come with you. <a href="/business#plans">See the plans</a></p>
        </section>

        {/* FAQ */}
        <section className="ch-wrap ch-sec ch-sec-tight" id="questions" aria-labelledby="faq-h">
          <h2 id="faq-h" className="ch-h2 ch-center">Before you start.</h2>
          <div className="ch-faq">
            {FAQ.map(([q, a]) => (<details key={q}><summary>{q}</summary><p>{a}</p></details>))}
          </div>
        </section>

        {/* CTA */}
        <section className="ch-wrap ch-cta-sec" aria-labelledby="cta-h">
          <div className="ch-cta-band">
            <h2 id="cta-h">Start free. See Chioma greet your first visitor today.</h2>
            <div className="ch-cta-row ch-cta-center">
              <a className="ch-btn ch-btn-white" href={START_HREF}>Start free</a>
              <a className="ch-btn ch-btn-ghost" href={demoHref} target={demoTarget} rel="noopener noreferrer" onClick={openDemo}>Chat with Chioma now</a>
            </div>
          </div>
        </section>
      </main>

      <footer className="ch-foot">
        <div className="ch-wrap">
          <div className="ch-foot-row">
            <div><Logo light /><p>Chioma, the web chat assistant from Opsra.</p></div>
            <div><b>Product</b><a href="#how">How it works</a><a href="#price">Pricing</a><a href="#questions">Questions</a></div>
            <div><b>Opsra</b><a href="/business">Opsra for WhatsApp</a><a href="/">Log in</a></div>
            <div><b>Legal</b><a href="/privacy">Privacy</a><a href="/terms">Terms</a></div>
          </div>
        </div>
      </footer>
    </div>
  );
}
