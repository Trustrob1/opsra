import test from 'node:test';
import assert from 'node:assert/strict';
import worker, { hostFolder, filePath } from './src/index.js';

function bucket(files) {
  return {
    async get(key, opts = {}) {
      if (!(key in files)) return null;
      const f = files[key];
      const etag = `"${key.length}"`;
      const h = opts.onlyIf;
      if (h && h.get && h.get('If-None-Match') === etag) return { httpEtag: etag, writeHttpMetadata() {} };
      return {
        httpEtag: etag, body: f.body, range: undefined,
        writeHttpMetadata(headers) { headers.set('Content-Type', f.type); headers.set('Cache-Control', f.cache || 'public, max-age=60'); },
      };
    },
  };
}
const env = { SITES: bucket({
  'shop.com.ng/index.html': { body: '<h1>hi</h1>', type: 'text/html; charset=utf-8' },
  'shop.com.ng/images/hero.jpg': { body: 'JPG', type: 'image/jpeg', cache: 'public, max-age=3600' },
  'shop.com.ng/robots.txt': { body: 'User-agent: *', type: 'text/plain' },
  'other.ng/index.html': { body: 'other', type: 'text/html' },
  'other.ng/404.html': { body: 'custom 404', type: 'text/html' },
}) };
const get = (url, init = {}) => worker.fetch(new Request(url, init), env);

test('hostFolder', () => {
  assert.equal(hostFolder('WWW.Shop.com.ng'), 'shop.com.ng');
  assert.equal(hostFolder('shop.com.ng:443'), 'shop.com.ng');
  assert.equal(hostFolder('shop.com.ng.'), 'shop.com.ng');
  assert.equal(hostFolder('localhost'), null);
  assert.equal(hostFolder('a/b.com'), null);
  assert.equal(hostFolder(''), null);
});

test('filePath', () => {
  assert.equal(filePath('/'), 'index.html');
  assert.equal(filePath('/images/hero.jpg'), 'images/hero.jpg');
  assert.equal(filePath('/menu/'), 'menu/index.html');
  assert.equal(filePath('/../secret'), null);
  assert.equal(filePath('/%2e%2e/secret'), null);
  assert.equal(filePath('/%E0%A4%A'), null);
});

test('serves index at root, with and without www', async () => {
  for (const u of ['https://shop.com.ng/', 'https://www.shop.com.ng/']) {
    const r = await get(u);
    assert.equal(r.status, 200);
    assert.equal(await r.text(), '<h1>hi</h1>');
    assert.equal(r.headers.get('content-type'), 'text/html; charset=utf-8');
    assert.equal(r.headers.get('x-content-type-options'), 'nosniff');
  }
});

test('serves images with their stored cache header', async () => {
  const r = await get('https://shop.com.ng/images/hero.jpg');
  assert.equal(r.status, 200);
  assert.equal(r.headers.get('content-type'), 'image/jpeg');
  assert.equal(r.headers.get('cache-control'), 'public, max-age=3600');
});

test('one site never serves another site\'s files', async () => {
  assert.equal((await get('https://other.ng/images/hero.jpg')).status, 404);
  assert.equal(await (await get('https://other.ng/')).text(), 'other');
});

test('unknown host and missing file are 404', async () => {
  assert.equal((await get('https://nobody.com/')).status, 404);
  assert.equal((await get('https://shop.com.ng/nope.html')).status, 404);
});

test('uses the site\'s own 404.html when it has one', async () => {
  const r = await get('https://other.ng/missing');
  assert.equal(r.status, 404);
  assert.equal(await r.text(), 'custom 404');
});

test('HEAD has no body; POST is refused', async () => {
  const h = await get('https://shop.com.ng/', { method: 'HEAD' });
  assert.equal(h.status, 200);
  assert.equal(await h.text(), '');
  const p = await get('https://shop.com.ng/', { method: 'POST' });
  assert.equal(p.status, 405);
  assert.equal(p.headers.get('allow'), 'GET, HEAD');
});

test('conditional request returns 304', async () => {
  const first = await get('https://shop.com.ng/');
  const etag = first.headers.get('etag');
  const r = await get('https://shop.com.ng/', { headers: { 'If-None-Match': etag } });
  assert.equal(r.status, 304);
});

test('path traversal is refused', async () => {
  assert.equal((await get('https://shop.com.ng/%2e%2e/other.ng/index.html')).status, 404);
});

test('standby copy reads from the SITE_PREFIX folder', async () => {
  const standby = { SITE_PREFIX: 'live/', SITES: bucket({ 'live/shop.com.ng/index.html': { body: 'standby', type: 'text/html' } }) };
  const r = await worker.fetch(new Request('https://shop.com.ng/'), standby);
  assert.equal(r.status, 200);
  assert.equal(await r.text(), 'standby');
  assert.equal((await worker.fetch(new Request('https://other.ng/'), standby)).status, 404);
});
