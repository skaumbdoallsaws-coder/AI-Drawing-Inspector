'use strict';
const http = require('node:http');
const net = require('node:net');
const dns = require('node:dns/promises');
const { publicIPv4, researchURL } = require('./research-policy.cjs');

async function resolvePublicTarget(authority, lookup = dns.lookup) {
  if (typeof authority !== 'string' || !/^[a-z0-9.-]+:443$/i.test(authority)) throw new Error('research_proxy_target_rejected');
  const url = new URL(researchURL('https://' + authority + '/'));
  const host = url.hostname;
  const records = net.isIP(host) ? [{ address: host, family: 4 }] : await lookup(host, { all: true, family: 4, verbatim: true });
  if (!records.length || records.some(item => item.family !== 4 || !publicIPv4(item.address))) throw new Error('research_proxy_private_target');
  return { host, address: records[0].address, port: 443 };
}

async function createResearchProxy() {
  const sockets = new Set();
  let stopped = false, resolving = 0;
  const counts = { connected: 0, rejected: 0 };
  const server = http.createServer((_request, response) => { response.writeHead(403, { Connection: 'close' }); response.end(); });
  server.maxHeadersCount = 32;
  server.headersTimeout = 10000;
  server.requestTimeout = 10000;
  server.on('connection', socket => {
    if (stopped || sockets.size >= 64) { socket.destroy(); return; }
    sockets.add(socket); socket.on('close', () => sockets.delete(socket)); socket.on('error', () => {});
    socket.setTimeout(120000, () => socket.destroy());
  });
  server.on('clientError', (_error, socket) => socket.destroy());
  server.on('connect', async (request, client, head) => {
    if (stopped || resolving >= 16) { counts.rejected++; client.destroy(); return; }
    resolving++;
    let timer, upstream;
    try {
      const target = await Promise.race([resolvePublicTarget(request.url), new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('research_dns_timeout')), 5000);
      })]);
      if (stopped || client.destroyed) return;
      // Connect to the validated address, not the hostname. Chromium's DNS or
      // a later DNS rebinding cannot turn an approved public host into localhost.
      upstream = net.connect({ host: target.address, port: target.port, family: 4 });
      sockets.add(upstream);
      const connectTimer = setTimeout(() => upstream.destroy(), 10000);
      upstream.on('close', () => { clearTimeout(connectTimer); sockets.delete(upstream); client.destroy(); });
      upstream.on('error', () => client.destroy());
      client.on('close', () => upstream.destroy());
      upstream.once('connect', () => {
        clearTimeout(connectTimer);
        if (stopped || client.destroyed || !publicIPv4(upstream.remoteAddress)) { upstream.destroy(); return; }
        counts.connected++;
        client.write('HTTP/1.1 200 Connection Established\r\n\r\n');
        if (head.length) upstream.write(head);
        client.pipe(upstream); upstream.pipe(client);
      });
    } catch (_) { counts.rejected++; client.destroy(); upstream?.destroy(); }
    finally { clearTimeout(timer); resolving--; }
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject); server.listen(0, '127.0.0.1', resolve);
  });
  return { port: server.address().port, evidence: () => ({ ...counts, activeSockets: sockets.size }),
    async close() {
      stopped = true;
      for (const socket of sockets) socket.destroy();
      await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    } };
}
module.exports = { resolvePublicTarget, createResearchProxy };
