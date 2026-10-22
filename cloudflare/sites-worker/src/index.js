/**
 * opsra-sites Worker — serves every client site from the R2 bucket `opsra-sites`.
 *
 * The folder in the bucket is the visitor's domain WITHOUT a leading "www."
 * (`shop.com.ng/index.html`, `shop.com.ng/images/hero.jpg`), matching what
 * backend/app/services/site_publish_service.py uploads.
 */

const SECURITY = { 'X-Content-Type-Options': 'nosniff' };

// Normalise a Host header: lower-case, no port, no trailing dot, no leading "www."
export function hostFolder(host) {
  let h = String(host || '').toLowerCase().split(':')[0].replace(/\.$/, '');
  if (h.startsWith('www.')) h = h.slice(4);
  return /^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(h) ? h : null;
}

// URL path -> file path inside the site folder. "/" and "/dir/" map to index.html.
export function filePath(pathname) {
  let p;
  try { p = decodeURIComponent(pathname); } catch { return null; }
  if (p.includes('\0') || p.split('/').some((s) => s === '..')) return null;
  p = p.replace(/^\/+/, '');
  if (p === '' || p.endsWith('/')) p += 'index.html';
  return p;
}

// Unlisted reference pages (for example a sample site shown to prospects). They live in the bucket under
// `_showcase/<name>/`, outside every domain folder, so publishing a site never touches them. They are served
// only on SHOWCASE_HOSTS, only at /ref/<name>/ where <name> carries an unguessable token, and are never indexed.
// Nothing links to them: the only way in is the generated link.
export const SHOWCASE_HOSTS = ['velorastudio.com.ng'];
const SHOWCASE_RE = /^\/ref\/([A-Za-z0-9_-]{16,64})(\/.*)?$/;

export function showcaseKey(pathname) {
  const m = SHOWCASE_RE.exec(pathname);
  if (!m) return null;
  const rest = filePath(m[2] || '/');
  return rest === null ? null : { name: m[1], key: `_showcase/${m[1]}/${rest}`, bare: m[2] === undefined };
}

function plain(status, text) {
  return new Response(text, { status, headers: { 'Content-Type': 'text/plain; charset=utf-8', ...SECURITY } });
}

export default {
  async fetch(request, env) {
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('Method not allowed', { status: 405, headers: { Allow: 'GET, HEAD', ...SECURITY } });
    }
    const url = new URL(request.url);
    const folder = hostFolder(request.headers.get('Host') || url.hostname);
    const path = filePath(url.pathname);
    if (!folder || path === null) return plain(404, 'Not found');

    if (url.pathname.startsWith('/ref/') && SHOWCASE_HOSTS.includes(folder)) {
      const sc = showcaseKey(url.pathname);
      if (!sc) return plain(404, 'Not found');
      if (sc.bare) return new Response(null, { status: 301, headers: { Location: `${url.pathname}/${url.search}`, ...SECURITY } });
      const obj = await env.SITES.get(sc.key, { onlyIf: request.headers, range: request.headers });
      if (obj === null) return plain(404, 'Not found');
      const h = new Headers();
      if (obj.writeHttpMetadata) obj.writeHttpMetadata(h);
      if (obj.httpEtag) h.set('ETag', obj.httpEtag);
      for (const [k, v] of Object.entries(SECURITY)) h.set(k, v);
      h.set('X-Robots-Tag', 'noindex, nofollow, noarchive');
      h.set('Referrer-Policy', 'no-referrer');
      h.set('Cache-Control', 'private, max-age=300');
      if (!obj.body) return new Response(null, { status: 304, headers: h });
      const part = obj.range && request.headers.has('Range');
      return new Response(request.method === 'HEAD' ? null : obj.body, { status: part ? 206 : 200, headers: h });
    }

    // SITE_PREFIX is set only on the standby copy in the backup account ("live/"); the main Worker has none.
    const root = env.SITE_PREFIX || '';
    const key = `${root}${folder}/${path}`;
    const object = await env.SITES.get(key, {
      onlyIf: request.headers,
      range: request.headers,
    });

    if (object === null) {
      const page = await env.SITES.get(`${root}${folder}/404.html`);
      if (page && page.body) {
        const h = new Headers({ 'Content-Type': 'text/html; charset=utf-8', ...SECURITY });
        return new Response(request.method === 'HEAD' ? null : page.body, { status: 404, headers: h });
      }
      return plain(404, 'Not found');
    }

    const headers = new Headers();
    if (object.writeHttpMetadata) object.writeHttpMetadata(headers);
    if (object.httpEtag) headers.set('ETag', object.httpEtag);
    for (const [k, v] of Object.entries(SECURITY)) headers.set(k, v);

    // Conditional request satisfied: R2 returns the object without a body.
    if (!object.body) return new Response(null, { status: 304, headers });

    const partial = object.range && request.headers.has('Range');
    return new Response(request.method === 'HEAD' ? null : object.body, { status: partial ? 206 : 200, headers });
  },
};
