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
