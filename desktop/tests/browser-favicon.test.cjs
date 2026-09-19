'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { loadFavicon, rasterType, isFaviconDataURL, MAX_BYTES } = require('../src/browser-favicon.cjs');
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aEZoAAAAASUVORK5CYII=', 'base64');
const data = 'data:image/png;base64,' + png.toString('base64');
const response = () => new Response(png, { headers: { 'content-type': 'image/png' } });

test('favicon formats are bounded raster images, not HTML or SVG', () => {
  assert.equal(rasterType(png), 'image/png');
  assert.equal(isFaviconDataURL(data), true);
  for (const value of ['data:image/svg+xml;base64,PHN2Zz4=', 'https://example.com/icon.png', 'data:text/html;base64,PHN2Zz4=', 'data:image/png;base64,' + Buffer.alloc(MAX_BYTES + 1).toString('base64')]) assert.equal(isFaviconDataURL(value), false);
  const large = Buffer.from(png); large.writeUInt32BE(10000, 16); assert.equal(rasterType(large), null);
  assert.equal(rasterType(Buffer.from('<html>not an icon</html>')), null);
  const ico = Buffer.alloc(22 + png.length); ico.writeUInt32LE(65536, 0); ico.writeUInt16LE(1, 4);
  ico[6] = 1; ico[7] = 1; ico.writeUInt32LE(png.length, 14); ico.writeUInt32LE(22, 18); png.copy(ico, 22);
  assert.equal(rasterType(ico), 'image/x-icon');
  ico.writeUInt32LE(100000, 18); assert.equal(rasterType(ico), null);
});

test('favicon fetch uses the isolated session without credentials and falls back to the site root', async () => {
  const calls = [];
  const session = { async fetch(url, options) { calls.push({ url, options }); return url.endsWith('/favicon.ico') ? response() : new Response('<html>missing</html>'); } };
  assert.equal(await loadFavicon({ session, pageURL: 'https://example.com/path', urls: ['https://example.com/broken.png'] }), data);
  assert.deepEqual(calls.map(c => c.url), ['https://example.com/broken.png', 'https://example.com/favicon.ico']);
  assert.ok(calls.every(c => c.options.credentials === 'omit' && c.options.redirect === 'manual'));
});

test('favicon URLs and redirects cannot reach local services', async () => {
  const calls = [];
  const session = { async fetch(url) { calls.push(url); return url.endsWith('/redirect') ? new Response(null, { status: 302, headers: { location: 'http://127.0.0.1/private' } }) : response(); } };
  assert.equal(await loadFavicon({ session, pageURL: 'http://127.0.0.1/', urls: [] }), null);
  assert.equal(await loadFavicon({ session, pageURL: 'https://example.com/', urls: ['http://127.0.0.1/icon', 'file:///secret', 'https://example.com/redirect'] }), data);
  assert.deepEqual(calls, ['https://example.com/redirect', 'https://example.com/favicon.ico']);
});

test('oversized streamed bodies, declared sizes and redirect loops return no icon', async () => {
  for (const fetch of [
    async () => new Response(Buffer.alloc(MAX_BYTES + 1)),
    async () => new Response(png, { headers: { 'content-length': String(MAX_BYTES + 1) } }),
    async () => new Response(null, { status: 302, headers: { location: '/again' } })
  ]) assert.equal(await loadFavicon({ session: { fetch }, pageURL: 'https://example.com/', urls: [] }), null);
});

test('embedded raster icons require no fetch; aborted work never starts a fetch', async () => {
  const session = { fetch() { throw Error('unexpected fetch'); } };
  assert.equal(await loadFavicon({ session, pageURL: 'https://example.com/', urls: [data] }), data);
  const controller = new AbortController(); controller.abort();
  assert.equal(await loadFavicon({ session, pageURL: 'https://example.com/', urls: [data], signal: controller.signal }), null);
});
