'use strict';
const { isIP } = require('node:net');
const fail = code => Object.assign(new Error(code), { code });

function publicIPv4(address) {
  if (isIP(address) !== 4) return false;
  const [a, b, c] = address.split('.').map(Number);
  return !(a === 0 || a === 10 || a === 127 || a >= 224 ||
    (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) || (a === 192 && (b === 0 || b === 168 || (b === 88 && c === 99))) ||
    (a === 198 && (b === 18 || b === 19 || (b === 51 && c === 100))) ||
    (a === 203 && b === 0 && c === 113));
}

function researchURL(raw) {
  if (typeof raw !== 'string' || raw.length > 8192 || /[\u0000-\u0020\u007f\\]/u.test(raw) || !/^https:\/\//i.test(raw)) throw fail('research_https_required');
  const authority = raw.match(/^https:\/\/([^/?#]+)/i)?.[1];
  if (!authority || /[@%]/.test(authority)) throw fail('research_address_rejected');
  let url;
  try { url = new URL(raw); } catch (_) { throw fail('research_address_rejected'); }
  const host = url.hostname.toLowerCase().replace(/\.$/, '');
  if (url.username || url.password || (url.port && url.port !== '443') ||
    host.startsWith('[') || !host.includes('.') || /(?:^|\.)(?:localhost|local|internal|test|invalid|example)$/.test(host) ||
    (isIP(host) && !publicIPv4(host))) throw fail('research_address_rejected');
  return url.href;
}

function addressOrSearch(value) {
  if (typeof value !== 'string' || !value.trim() || value.length > 8192) throw fail('research_address_required');
  const input = value.trim();
  if (/^[a-z][a-z0-9+.-]*:/i.test(input)) return researchURL(input);
  if (!/\s/.test(input) && /^[^/]+\.[^/]+(?:\/.*)?$/.test(input)) return researchURL('https://' + input);
  return 'https://www.google.com/search?q=' + encodeURIComponent(input);
}

function researchHeaders(headers) {
  // Cookies and site authorization stay in the separate research session.
  // Application credentials are never accepted, even if supplied by a page.
  return Object.fromEntries(Object.entries(headers || {}).filter(([key]) =>
    !key.toLowerCase().startsWith('x-inspectorpro-') && !['proxy-authorization', 'proxy-connection'].includes(key.toLowerCase())));
}

function paneGeometry(width, height, { visible = false, expanded = false, splitFraction = null } = {}) {
  if (![width, height].every(value => Number.isSafeInteger(value) && value > 0 && value <= 32768)) throw fail('research_bounds_invalid');
  if (splitFraction !== null && (!Number.isFinite(splitFraction) || splitFraction < 0.2 || splitFraction > 0.8)) throw fail('research_split_invalid');
  const paneWidth = visible ? (expanded || width < 1200 ? width : splitFraction === null
    ? Math.min(520, Math.floor(width * 0.4)) : Math.round(Math.max(384, Math.min(width - 480, width * splitFraction)))) : 0;
  const headerHeight = Math.min(116, height);
  return { appWidth: width - paneWidth || width, obscuresApp: visible && paneWidth === width,
    chrome: { x: width - paneWidth, y: 0, width: paneWidth, height: headerHeight },
    page: { x: width - paneWidth, y: headerHeight, width: paneWidth, height: Math.max(0, height - headerHeight) } };
}

module.exports = { publicIPv4, researchURL, addressOrSearch, researchHeaders, paneGeometry };
