/**
 * frontend/src/pages/HostDomainPricing.jsx
 * HOST-2 - the two public blocks of the /host page: the domain checker and the price table. No sign-in needed.
 * Data: GET /api/v1/public/host/pricing and /domain-check (routers/public_host.py). Every figure comes from the same pricing
 * engine as the checkout; nothing is typed in here. Styles: SiteLandingPage.css + HostLandingPage.css (.sl-h-*).
 * The domain the visitor liked is remembered in localStorage (opsra_host_domain, not secret) so the portal can remind them.
 */
import { useEffect, useState } from "react";
import { hostPublicPricing, hostPublicDomainCheck, errorMessage } from "../services/builder_portal.service";

const naira = (n) => `₦${Math.round(Number(n) || 0).toLocaleString("en-NG")}`;
const FALLBACK_ENDINGS = [".com.ng", ".ng", ".com"];

/* Plain-words meaning for the things the hosting price includes (matched on the name set in Settings). */
function explain(name) {
  const n = name.toLowerCase();
  if (n.includes("ssl")) return "SSL certificate: the padlock and https on your address";
  if (n.includes("dns")) return "DNS management: points your domain at your site and keeps it working";
  if (n.includes("protect") || n.includes("awps")) return "Website protection: scans and guards against attacks";
  if (n.includes("hosting")) return "Website hosting: your site stored and served fast, all year";
  return name;
}

export function usePricing() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    hostPublicPricing()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(errorMessage(e, "Prices could not be loaded just now.")));
    return () => {
      alive = false;
    };
  }, []);
  return { data, error };
}

export function DomainChecker({ endings }) {
  const list = endings && endings.length ? endings : FALLBACK_ENDINGS;
  const [label, setLabel] = useState("");
  const [tld, setTld] = useState(list[0]);
  const [state, setState] = useState("idle"); // idle | checking | done
  const [res, setRes] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!list.includes(tld)) setTld(list[0]);
  }, [list, tld]);

  async function run(domain) {
    setState("checking");
    setError("");
    setRes(null);
    try {
      const r = await hostPublicDomainCheck(domain);
      setRes(r);
      setState("done");
      if (r.status === "available") {
        try {
          window.localStorage.setItem("opsra_host_domain", r.domain);
        } catch {
          /* storage blocked */
        }
      }
    } catch (e) {
      setState("idle");
      setError(errorMessage(e, "We couldn’t check that just now. Please try again."));
    }
  }

  function submit(e) {
    e.preventDefault();
    const clean = label.trim().toLowerCase().replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/[/\s].*$/, "");
    if (!clean) return setError("Type the name you want, for example adaezestyles.");
    // allow people to paste a full domain such as adaezestyles.com.ng
    const full = clean.includes(".") ? clean : `${clean}${tld}`;
    setLabel(clean.includes(".") ? clean : clean);
    run(full);
  }

  const price = res && res.price;
  return (
    <div className="sl-h-check">
      <form onSubmit={submit} className="sl-h-checkrow" noValidate>
        <label htmlFor="hdc-name" className="sl-h-sr">
          Domain name
        </label>
        <input
          id="hdc-name"
          type="text"
          inputMode="url"
          autoComplete="off"
          autoCapitalize="none"
          spellCheck="false"
          placeholder="adaezestyles"
          value={label}
          onChange={(e) => {
            setLabel(e.target.value);
            setError("");
          }}
        />
        <label htmlFor="hdc-tld" className="sl-h-sr">
          Domain ending
        </label>
        <select id="hdc-tld" value={tld} onChange={(e) => setTld(e.target.value)}>
          {list.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <button className="sl-btn sl-teal" type="submit" disabled={state === "checking"}>
          {state === "checking" ? "Checking…" : "Check availability"}
        </button>
      </form>
      <div aria-live="polite">
        {error && <p className="sl-err">{error}</p>}
        {state === "done" && res && (
          <div className={`sl-h-res sl-h-${res.status}`}>
            {res.status === "available" && (
              <>
                <b>{res.domain} looks free.</b>
                {!res.confirmed && <span> We double-check with the registry just before we register it for you.</span>}
                {price && (
                  <span className="sl-h-resprice">
                    First year {naira(price.first_year.total)} · then {naira(price.renewal.total)} a year, domain and hosting together.
                  </span>
                )}
                <span className="sl-h-resnote">Write it down: you’ll enter it again when you go live.</span>
              </>
            )}
            {res.status === "taken" && (
              <>
                <b>{res.domain} is already taken.</b>
                {(res.alternatives || []).length > 0 && (
                  <span className="sl-h-alts">
                    Try:{" "}
                    {res.alternatives.map((a) => (
                      <button
                        key={a.domain}
                        type="button"
                        className="sl-h-alt"
                        onClick={() => {
                          setLabel(a.domain);
                          run(a.domain);
                        }}
                      >
                        {a.domain}
                        {a.status === "available" ? "" : " (taken)"}
                      </button>
                    ))}
                  </span>
                )}
              </>
            )}
            {res.status === "unknown" && (
              <>
                <b>We couldn’t tell for {res.domain}.</b>
                <span> The registry didn’t answer. Please try again in a minute.</span>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function PricingTable({ data, error }) {
  if (error) return <p className="sl-err">{error}</p>;
  if (!data) return <p className="sl-h-muted">Loading prices…</p>;
  if (!data.endings.length) return <p className="sl-h-muted">Prices are being updated. Please check back shortly.</p>;
  return (
    <>
      <div className="sl-h-tablewrap">
        <table className="sl-h-table">
          <caption className="sl-h-sr">Price per domain ending, in naira</caption>
          <thead>
            <tr>
              <th scope="col">What you pay for</th>
              {data.endings.map((e) => (
                <th scope="col" key={e.tld}>
                  {e.tld}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">Domain name (1 year)</th>
              {data.endings.map((e) => (
                <td key={e.tld}>{naira(e.first_year.domain)}</td>
              ))}
            </tr>
            <tr>
              <th scope="row">
                Hosting, SSL and DNS (1 year)
                <small>One price, everything below is included</small>
              </th>
              {data.endings.map((e) => (
                <td key={e.tld}>{naira(e.first_year.hosting)}</td>
              ))}
            </tr>
            {data.endings.some((e) => e.first_year.setup > 0) && (
              <tr>
                <th scope="row">
                  Setup fee
                  <small>Once, in the first year</small>
                </th>
                {data.endings.map((e) => (
                  <td key={e.tld}>{e.first_year.setup > 0 ? naira(e.first_year.setup) : "None"}</td>
                ))}
              </tr>
            )}
            <tr className="sl-h-total">
              <th scope="row">First year total</th>
              {data.endings.map((e) => (
                <td key={e.tld}>{naira(e.first_year.total)}</td>
              ))}
            </tr>
            <tr>
              <th scope="row">
                Every year after
                <small>Domain, hosting, SSL and DNS renewal</small>
              </th>
              {data.endings.map((e) => (
                <td key={e.tld}>{naira(e.renewal.total)}</td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      {data.includes.length > 0 && (
        <div className="sl-h-incl">
          <h3>What the hosting price includes</h3>
          <ul>
            {data.includes.map((n) => (
              <li key={n}>{explain(n)}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="sl-h-muted">
        Prices are in naira and are the same ones you’ll see at checkout. The exact total for your own domain shows before you pay.
      </p>
    </>
  );
}
