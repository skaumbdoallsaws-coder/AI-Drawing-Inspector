'use strict';

const { isIP } = require('node:net');

const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '[::1]']);
const MAX_URL_LENGTH = 8192;

// Validate before WHATWG parsing: it otherwise repairs slashes, whitespace,
// credentials and alternative numeric IP spellings into plausible URLs.
function parseHttpUrl(raw) {
  if (typeof raw !== 'string' || raw.length === 0 || raw.length > MAX_URL_LENGTH ||
      /[\u0000-\u0020\u007f\\]/u.test(raw)) {
    throw new TypeError('URL must be an absolute HTTP(S) URL without whitespace or backslashes');
  }
  const match = /^(https?):\/\/([^/?#]+)(?:[/?#]|$)/i.exec(raw);
  if (!match || match[2].includes('@') || match[2].includes('%')) {
    throw new TypeError('URL scheme or authority is not permitted');
  }
  let parsed;
  try { parsed = new URL(raw); } catch { throw new TypeError('URL is invalid'); }
  if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname ||
      parsed.username || parsed.password || parsed.port === '0') {
    throw new TypeError('URL scheme, credentials or port is not permitted');
  }
  return { parsed, authority: match[2] };
}

function parseApplicationUrl(raw) {
  const { parsed, authority } = parseHttpUrl(raw);
  const hostMatch = /^(127\.0\.0\.1|localhost|\[::1\])(?::([1-9][0-9]{0,4}))?$/i.exec(authority);
  if (!hostMatch || !LOOPBACK_HOSTS.has(parsed.hostname) ||
      (hostMatch[2] && Number(hostMatch[2]) > 65535)) {
    throw new TypeError('Application URL must use canonical 127.0.0.1, localhost or [::1]');
  }
  return Object.freeze({
    url: parsed.href,
    origin: parsed.origin,
    hostname: parsed.hostname,
    port: Number(parsed.port || (parsed.protocol === 'https:' ? 443 : 80)),
  });
}

function validateApplicationOrigin(raw) {
  const result = parseApplicationUrl(raw);
  // Empty query/fragment delimiters are also rejected, although URL.search/hash
  // are empty for a trailing '?' or '#'. Profiles must contain an origin only.
  if (!/^https?:\/\/[^/?#]+\/?$/i.test(raw)) {
    throw new TypeError('Application origin must not contain a path, query or fragment');
  }
  return result.origin;
}

function isLocalLiteral(hostname) {
  const host = hostname.toLowerCase().replace(/\.$/, '');
  if (host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local') || !host.includes('.')) {
    return true;
  }
  const address = host.startsWith('[') ? host.slice(1, -1) : host;
  if (isIP(address) === 4) {
    const [a, b] = address.split('.').map(Number);
    return a === 0 || a === 10 || a === 127 || a >= 224 ||
      (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127);
  }
  // Direct IPv6 destinations are deliberately excluded from the initial
  // external-launch candidate policy. This is not a DNS/network firewall.
  return isIP(address) === 6;
}

function classifyNavigation(raw, applicationOrigin) {
  let origin;
  let parsed;
  try {
    origin = validateApplicationOrigin(applicationOrigin);
    ({ parsed } = parseHttpUrl(raw));
  } catch {
    return Object.freeze({ action: 'deny', reason: 'invalid-url-or-application-origin' });
  }
  if (parsed.origin === origin) {
    try { parseApplicationUrl(raw); } catch {
      return Object.freeze({ action: 'deny', reason: 'noncanonical-application-address' });
    }
    return Object.freeze({ action: 'allow-app', url: parsed.href });
  }
  if (isLocalLiteral(parsed.hostname)) {
    return Object.freeze({ action: 'deny', reason: 'other-local-address' });
  }
  // A caller must still require a deliberate action and separately choose to
  // launch the normal browser. This result never authorizes an embedded view.
  return Object.freeze({ action: 'external-browser', url: parsed.href });
}

module.exports = { parseApplicationUrl, validateApplicationOrigin, classifyNavigation };
