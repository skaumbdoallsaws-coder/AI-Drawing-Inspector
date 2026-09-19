'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { publicIPv4, researchURL, addressOrSearch, researchHeaders, paneGeometry } = require('../src/research-policy.cjs');
const { resolvePublicTarget, createResearchProxy } = require('../src/research-proxy.cjs');
const net = require('node:net');
for (const raw of ['http://example.com', 'file:///a', 'javascript:alert(1)', 'https://localhost', 'https://foo.localhost',
  'https://0x7f000001', 'https://2130706433', 'https://127.1', 'https://[::1]', 'https://[::ffff:127.0.0.1]', 'https://host.local',
  'https://169.254.169.254', 'https://10.1.2.3', 'https://192.168.1.1', 'https://example.com:8000', 'https://example.com@127.0.0.1',
  'https://example.com\\@localhost', 'https://exam\nple.com', 'https://example.com%2f.localhost']) {
  test('research rejects ' + JSON.stringify(raw), () => assert.throws(() => researchURL(raw)));
}
test('HTTPS URL and search intent are explicit', () => {
  assert.equal(researchURL('https://example.com/a?q=kit#one'), 'https://example.com/a?q=kit#one');
  assert.equal(addressOrSearch('example.com/manual'), 'https://example.com/manual');
  assert.equal(addressOrSearch('forklift turning radius'), 'https://www.google.com/search?q=forklift%20turning%20radius');
  assert.throws(() => addressOrSearch('file:///manual'));
});
test('public address check excludes special ranges and IPv6', () => {
  for (const ip of ['0.0.0.0','100.64.0.1','198.18.0.1','192.0.0.1','198.51.100.1','203.0.113.1','224.1.2.3','::1']) assert.equal(publicIPv4(ip), false, ip);
  assert.equal(publicIPv4('8.8.8.8'), true);
});
test('proxy refuses private or mixed DNS answers and pins the chosen address', async () => {
  await assert.rejects(resolvePublicTarget('public.example.com:443', async () => [{address:'127.0.0.1',family:4}]));
  await assert.rejects(resolvePublicTarget('public.example.com:443', async () => [{address:'8.8.8.8',family:4},{address:'10.0.0.1',family:4}]));
  await assert.rejects(resolvePublicTarget('public.example.com:443', async () => []));
  const result = await resolvePublicTarget('public.example.com:443', async () => [{address:'8.8.8.8',family:4}]);
  assert.deepEqual(result, {host:'public.example.com',address:'8.8.8.8',port:443});
});
test('research strips application and proxy credentials, not isolated site cookies', () => {
  assert.deepEqual(researchHeaders({'X-InspectorPro-Desktop-Token':'secret','x-inspectorpro-session':'owner','Proxy-Authorization':'token', Cookie:'site=one'}), {Cookie:'site=one'});
});
test('native pane bounds never overlap the app region or escape the viewport', () => {
  for (const [width,height] of [[1440,816],[900,700],[1920,1080],[800,600]]) for (const expanded of [true,false]) {
    const result = paneGeometry(width,height,{visible:true,expanded});
    assert.equal(result.page.x + result.page.width,width); assert.equal(result.page.y + result.page.height,height);
    if (!result.obscuresApp) assert.equal(result.appWidth,result.page.x);
  }
  assert.equal(paneGeometry(1400,800).page.width,0);
  assert.throws(() => paneGeometry(Infinity,800));
});
test('real proxy refuses localhost CONNECT before any target connection', async () => {
  const proxy = await createResearchProxy();
  try {
    await new Promise((resolve,reject) => {
      const client = net.connect(proxy.port,'127.0.0.1',() => client.write('CONNECT 127.0.0.1:443 HTTP/1.1\r\nHost: 127.0.0.1:443\r\n\r\n'));
      client.on('error',reject); client.on('close',resolve); client.setTimeout(3000,() => { client.destroy(); reject(new Error('timeout')); });
    });
    assert.equal(proxy.evidence().connected,0); assert.equal(proxy.evidence().rejected,1);
  } finally { await proxy.close(); }
});
