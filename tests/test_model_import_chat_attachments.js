'use strict';
// Plain node tests: no server, browser, files from users, or real clocks required.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const Attachments = require('../static/facility_layout_chat_attachments.js');
const Transport = require('../static/facility_layout_transport.js');
const Workspace = require('../static/facility_layout_workspace.js');
const tests = [];
const test = (name, fn) => tests.push({ name, fn });
const id = n => 'mi-' + String(n).padStart(24, '0');
const referenceId = n => 'rf-' + String(n).padStart(24, '0');
const file = name => ({ name: name || 'bowl.glb', size: 1024 });
const record = (n, state, extra) => Object.assign({ id: id(n), state: state || 'ready' }, extra);
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }
function clock() {
    let now = 0, sequence = 0;
    const timers = new Map();
    return { now: () => now, setTimeout: (fn, delay) => { const id = ++sequence; timers.set(id, { fn, at: now + delay }); return id; },
        clearTimeout: id => timers.delete(id),
        advance: async delay => {
            now += delay;
            const due = Array.from(timers).filter(([, timer]) => timer.at <= now);
            due.forEach(([id, timer]) => { timers.delete(id); timer.fn(); }); await flush();
        }, size: () => timers.size };
}
function setup(transport, overrides) {
    const time = clock();
    const controller = Attachments.createController(Object.assign({}, time, overrides));
    const context = { conversationId: 'chat-a', siteId: 'site-a', layoutId: 'layout-a', enabled: true, transport };
    controller.sync(context);
    return { controller, time, context, chips: () => controller.snapshot().chips };
}
const response = (status, body) => ({ status, ok: status < 300, json: async () => body });

test('three files start two uploads; third waits and all three can be attached', async () => {
    const pending = [], progress = [];
    const h = setup({ importModel: (file, options) => { const d = deferred(); pending.push(d); progress.push(options.onProgress); return d.promise; } });
    assert.strictEqual(h.controller.add([file('a.glb'), file('b.zip'), file('c.glb'), file('d.glb')]), 3);
    assert.deepStrictEqual(h.chips().map(c => c.state), ['uploading', 'uploading', 'waiting']);
    progress[0](42); assert.strictEqual(h.chips()[0].progress, 42);
    assert.strictEqual(Attachments.buildPayload(h.chips(), 'place it').blocked, true);
    pending[0].resolve(record(1)); await flush();
    assert.strictEqual(pending.length, 3);
    pending[1].resolve(record(2)); pending[2].resolve(record(3)); await flush();
    const payload = Attachments.buildPayload(h.chips(), '');
    assert.strictEqual(payload.canSend, true); assert.strictEqual(payload.attachments.length, 3);
});

test('mixed chips share the three-file cap and send only ready reference IDs', async () => {
    const h = setup({ importModel: async () => record(1),
        importReferenceFile: async () => ({ referenceId: referenceId(2), state: 'processing' }),
        getReferenceFile: async () => ({ referenceId: referenceId(2), state: 'ready', kind: 'image', pages: 1 }) });
    assert.strictEqual(h.controller.add([file('part.glb'), { name: 'photo.png', type: 'image/png', size: 2048 },
        file('other.glb'), { name: 'extra.jpg', size: 100 }]), 3);
    await flush();
    assert.deepStrictEqual(h.chips().map(c => c.state), ['ready', 'checking', 'ready']);
    assert.strictEqual(Attachments.buildPayload(h.chips(), 'place these').blocked, true);
    await h.time.advance(1000);
    assert.deepStrictEqual(Attachments.buildPayload(h.chips(), '').attachments, [
        { kind: 'model-import', importId: id(1) },
        { kind: 'reference-file', referenceId: referenceId(2) },
        { kind: 'model-import', importId: id(1) },
    ]);
});

test('reference refusals show server text and never enter the chat payload', async () => {
    const pdf = setup({ importReferenceFile: async () => { throw Object.assign(
        new Error('PDF reading is not enabled; attach a screenshot of the page.'), { status: 422 }); } });
    pdf.controller.add([{ name: 'sheet.pdf', type: 'application/pdf', size: 100 }]); await flush();
    assert.strictEqual(pdf.chips()[0].state, 'refused');
    assert.match(pdf.chips()[0].reason, /screenshot/);
    assert.deepStrictEqual(Attachments.buildPayload(pdf.chips(), 'hello').attachments, []);
    const gif = setup({ importReferenceFile: async () => { throw Object.assign(new Error('Use one image frame.'), { status: 422 }); } });
    gif.controller.add([{ name: 'animation.gif', type: 'image/gif', size: 200 }]); await flush();
    assert.strictEqual(gif.chips()[0].state, 'refused');
    assert.match(Attachments.chipLabel ? Attachments.chipLabel(gif.chips()[0]) : gif.chips()[0].reason, /frame/);
});

test('drop classification uses image MIME or extension and ignores late reference responses', async () => {
    assert.strictEqual(Attachments.fileKind({ name: 'misnamed.bin', type: 'image/png' }), 'reference-file');
    assert.strictEqual(Attachments.fileKind({ name: 'sheet.PDF', type: '' }), 'reference-file');
    assert.strictEqual(Attachments.fileKind({ name: 'animation.gif', type: 'image/gif' }), 'reference-file');
    assert.strictEqual(Attachments.fileKind({ name: 'part.glb', type: '' }), 'model-import');
    for (const changed of [{ layoutId: 'another-layout' }, { conversationId: 'another-chat' }]) {
        const pending = deferred();
        const h = setup({ importReferenceFile: () => pending.promise });
        h.controller.add([{ name: 'photo.webp', size: 100 }]);
        h.controller.sync(Object.assign({}, h.context, changed));
        pending.resolve({ referenceId: referenceId(1), state: 'processing' }); await flush();
        assert.deepStrictEqual(h.chips(), []);
    }
});

test('first reference provider note is remembered once and never blocks on storage', () => {
    const values = new Map();
    const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
    assert.strictEqual(Attachments.firstReferenceNote(storage), true);
    assert.strictEqual(Attachments.firstReferenceNote(storage), false);
    assert.strictEqual(Attachments.firstReferenceNote({ getItem: () => { throw new Error('disabled'); } }), true);
});

test('chat omits attachments for a plain turn and keeps mixed retry identities', () => {
    const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
    const send = html.slice(html.indexOf('async function handleAgentSend('), html.indexOf('// === Scout Browser Search'));
    assert.ok(send.includes('...(modelAttachments.length ? { attachments: modelAttachments } : {})'));
    assert.ok(send.includes("attachment.referenceId === chip.referenceId"));
    assert.ok(html.includes('id="agentReferenceFileInput"'));
    assert.ok(html.includes('20261117-reference-files-1'));
});

test('reference transport uses raw scoped routes, encoded name, progress and refusal text', async () => {
    const calls = []; let status = 202;
    const transport = Transport.createHttpTransport({ siteId: 'site a', layoutId: 'layout/b',
        fetch: async (url, init) => { calls.push({ url, init }); return response(status,
            status === 422 ? { error: { code: 'reference_pdf_disabled', message: 'Attach a screenshot.' } }
                : { referenceId: referenceId(1), state: 'processing' }); } });
    const source = { name: 'phone photo.jpg', type: 'image/jpeg', size: 1234 };
    await transport.importReferenceFile(source); await transport.getReferenceFile(referenceId(1));
    assert.strictEqual(calls[0].url, '/api/facility-layouts/site%20a/layout%2Fb/reference-files');
    assert.strictEqual(calls[0].init.body, source);
    assert.strictEqual(calls[0].init.headers['X-Reference-Name'], 'phone%20photo.jpg');
    assert.ok(calls[1].url.endsWith('/reference-files/' + referenceId(1)));
    assert.throws(() => transport.getReferenceFile('../bad'), /id is required/);
    status = 422;
    await assert.rejects(transport.importReferenceFile(source), error => error.status === 422 && error.message === 'Attach a screenshot.');
});

test('reference XHR sends the raw file and reports byte progress', async () => {
    const instances = [];
    class Xhr {
        constructor() { this.upload = {}; this.headers = {}; instances.push(this); }
        open(method, url) { this.method = method; this.url = url; }
        setRequestHeader(key, value) { this.headers[key] = value; }
        send(body) { this.body = body; this.upload.onprogress({ lengthComputable: true, loaded: 512, total: 1024 });
            this.status = 202; this.responseText = JSON.stringify({ referenceId: referenceId(1), state: 'processing' }); this.onload(); }
    }
    const progress = [], source = { name: 'photo.png', type: 'image/png', size: 1024 };
    const transport = Transport.createHttpTransport({ siteId: 's', layoutId: 'l', XMLHttpRequest: Xhr,
        fetch: () => { throw new Error('No fetch upload expected'); } });
    await transport.importReferenceFile(source, { onProgress: value => progress.push(value) });
    assert.deepStrictEqual(progress, [50]);
    assert.strictEqual(instances[0].body, source);
    assert.ok(instances[0].url.endsWith('/reference-files'));
});

test('429 admission automatically retries at 2/4/8 seconds then busy; explicit retry recovers', async () => {
    let attempts = 0;
    const h = setup({ importModel: async () => { attempts++; if (attempts < 5) throw Object.assign(new Error('Queue full'), { status: 429 }); return record(1); } });
    h.controller.add([file()]); await flush();
    for (const delay of [2000, 4000, 8000]) {
        assert.strictEqual(h.chips()[0].state, 'waiting');
        const before = attempts; await h.time.advance(delay - 1); assert.strictEqual(attempts, before);
        await h.time.advance(1); assert.strictEqual(attempts, before + 1);
    }
    assert.strictEqual(attempts, 4); assert.strictEqual(h.chips()[0].state, 'busy');
    assert.deepStrictEqual(Attachments.buildPayload(h.chips(), 'hello').attachments, []);
    h.controller.retry(h.chips()[0].id); await flush(); assert.strictEqual(h.chips()[0].state, 'ready');
});

test('worker failure shows reason, does not send, and retries the existing import route', async () => {
    const retries = [];
    const h = setup({ importModel: async () => record(1, 'queued'),
        getModelImport: async () => record(1, 'failed', { refusal: { code: 'interrupted', message: 'The check was interrupted.' } }),
        retryModelImport: async importId => { retries.push(importId); return record(1); } });
    h.controller.add([file()]); await flush(); assert.strictEqual(h.chips()[0].state, 'checking');
    await h.time.advance(1000); assert.strictEqual(h.chips()[0].state, 'failed');
    assert.match(h.chips()[0].reason, /interrupted/);
    assert.strictEqual(Attachments.buildPayload(h.chips(), '').canSend, false);
    h.controller.retry(h.chips()[0].id); await flush();
    assert.deepStrictEqual(retries, [id(1)]); assert.strictEqual(h.chips()[0].state, 'ready');
});

test('retry-route 429 uses the same bounded admission retry policy', async () => {
    let retries = 0;
    const h = setup({ importModel: async () => record(1, 'failed'), retryModelImport: async () => {
        retries++; throw Object.assign(new Error('Busy'), { status: 429 });
    } });
    h.controller.add([file()]); await flush(); h.controller.retry(h.chips()[0].id); await flush();
    for (const delay of [2000, 4000, 8000]) await h.time.advance(delay);
    assert.strictEqual(retries, 4); assert.strictEqual(h.chips()[0].state, 'busy');
});

test('refused imports retain their reason and are sent to Sage', async () => {
    const h = setup({ importModel: async () => record(1, 'refused', { refusal: { message: 'Skins are not supported.' } }) });
    h.controller.add([file()]); await flush();
    assert.match(h.chips()[0].reason, /Skins/);
    assert.deepStrictEqual(Attachments.buildPayload(h.chips(), '').attachments, [{ kind: 'model-import', importId: id(1) }]);
});

test('conversation switch during polling ignores old results and clears timers', async () => {
    const poll = deferred();
    const h = setup({ importModel: async () => record(1, 'queued'), getModelImport: () => poll.promise });
    h.controller.add([file()]); await flush(); await h.time.advance(1000);
    h.controller.sync(Object.assign({}, h.context, { conversationId: 'chat-b' }));
    poll.resolve(record(1)); await flush(); assert.deepStrictEqual(h.chips(), []); assert.strictEqual(h.time.size(), 0);
    h.controller.sync(h.context); assert.deepStrictEqual(h.chips(), []);
});

test('site/layout switch and loss of permission clear chips and automatic retries', async () => {
    for (const changed of [{ siteId: 'site-b' }, { layoutId: 'layout-b' }, { enabled: false }]) {
        const h = setup({ importModel: async () => { throw Object.assign(new Error('Busy'), { status: 429 }); } });
        h.controller.add([file()]); await flush();
        h.controller.sync(Object.assign({}, h.context, changed));
        assert.deepStrictEqual(h.chips(), []); assert.strictEqual(h.time.size(), 0);
    }
});

test('removing an active upload keeps its slot until it finishes; late completion never revives it', async () => {
    const pending = [];
    const h = setup({ importModel: () => { const d = deferred(); pending.push(d); return d.promise; } });
    h.controller.add([file(), file()]); h.controller.remove(h.chips()[0].id); h.controller.add([file()]);
    assert.strictEqual(pending.length, 2); assert.strictEqual(h.chips()[1].state, 'waiting');
    pending[0].resolve(record(1)); await flush(); assert.strictEqual(pending.length, 3);
    assert.strictEqual(h.chips().length, 2); assert.ok(!h.chips().some(c => c.importId === id(1)));
    pending[1].resolve(record(2)); pending[2].resolve(record(3)); await flush();
});

test('returning to a conversation does not exceed its still active upload slots', async () => {
    const pending = [];
    const h = setup({ importModel: () => { const d = deferred(); pending.push(d); return d.promise; } });
    h.controller.add([file(), file()]); h.controller.sync(Object.assign({}, h.context, { layoutId: 'other' }));
    h.controller.add([file()]); assert.strictEqual(pending.length, 2);
    pending[0].resolve(record(1)); await flush(); assert.strictEqual(pending.length, 3);
    pending[1].resolve(record(2)); pending[2].resolve(record(3)); await flush();
    assert.deepStrictEqual(h.chips().map(c => c.importId), [id(3)]);
});

test('poll network failure resumes GET instead of re-queueing a potentially live worker', async () => {
    let polls = 0;
    const h = setup({ importModel: async () => record(1, 'queued'), getModelImport: async () => {
        if (++polls === 1) throw new Error('Offline'); return record(1);
    }, retryModelImport: () => { throw new Error('Must not re-queue a live check'); } });
    h.controller.add([file()]); await flush(); await h.time.advance(1000);
    assert.strictEqual(h.chips()[0].state, 'failed'); h.controller.retry(h.chips()[0].id); await flush();
    assert.strictEqual(h.chips()[0].state, 'ready'); assert.strictEqual(polls, 2);
});

test('send rules block every pending state; only ready/refused IDs enter the payload', () => {
    for (const state of ['waiting', 'uploading', 'checking']) {
        const result = Attachments.buildPayload([{ state }], 'text', true);
        assert.strictEqual(result.blocked, true); assert.strictEqual(result.canSend, false);
    }
    const chips = ['ready', 'refused', 'failed', 'busy'].map((state, n) => ({ state, importId: id(n) }));
    const result = Attachments.buildPayload(chips, '  ');
    assert.strictEqual(result.message, ''); assert.strictEqual(result.canSend, true);
    assert.deepStrictEqual(result.attachments, [0, 1].map(n => ({ kind: 'model-import', importId: id(n) })));
    assert.strictEqual(Attachments.buildPayload([], 'hello').canSend, true);
    assert.strictEqual(Attachments.buildPayload([], '', true).canSend, true);
    assert.strictEqual(Attachments.buildPayload([], '').canSend, false);
    assert.strictEqual(Attachments.buildPayload([{ state: 'ready', importId: '../bad' }], '').canSend, false);
});

test('failed sends retain chips; successful send clears its snapshot without erasing later attachments', async () => {
    let n = 0;
    const h = setup({ importModel: async () => record(++n) });
    h.controller.add([file()]); await flush(); const sent = h.controller.snapshot();
    // An error has no clear transition, and frozen payloads do not contain file objects.
    const frozen = JSON.parse(JSON.stringify(Attachments.buildPayload(sent.chips, '')));
    assert.strictEqual(h.chips().length, 1); assert.strictEqual(frozen.attachments[0].importId, id(1));
    h.controller.add([file()]); await flush(); h.controller.sent(sent);
    assert.deepStrictEqual(h.chips().map(c => c.importId), [id(2)]);
    h.controller.sync(Object.assign({}, h.context, { conversationId: 'new' }));
    h.controller.add([file()]); await flush(); h.controller.sent(sent);
    assert.deepStrictEqual(h.chips().map(c => c.importId), [id(3)]);
});

test('unsupported files and oversize models stay local; names are cleaned; transitions are pure', () => {
    assert.strictEqual(Attachments.newChip(file('chair.fbx'), 1).action, null);
    assert.strictEqual(Attachments.newChip({ name: 'huge.glb', size: 128 * 1024 * 1024 + 1 }, 1).state, 'failed');
    const chip = Object.freeze(Attachments.newChip(file('C:\\bad\\bowl\u0000.glb'), 1));
    assert.strictEqual(chip.name, 'bowl.glb');
    const next = Attachments.transition(chip, { type: 'start' });
    assert.strictEqual(chip.state, 'waiting'); assert.strictEqual(next.state, 'uploading');
});

test('transport uses scoped raw-body routes, encoded name, and structured HTTP errors', async () => {
    const calls = []; let status = 200;
    const transport = Transport.createHttpTransport({ siteId: 'site a', layoutId: 'layout/b',
        fetch: async (url, init) => { calls.push({ url, init }); return response(status, status === 429 ? { error: { message: 'Full', code: 'busy' } } : record(1)); } });
    const source = file('fruit bowl.glb'); await transport.importModel(source);
    await transport.getModelImport(id(1)); await transport.retryModelImport(id(1));
    assert.strictEqual(calls[0].url, '/api/facility-layouts/site%20a/layout%2Fb/model-imports');
    assert.strictEqual(calls[0].init.body, source); assert.strictEqual(calls[0].init.headers['X-Model-Name'], 'fruit%20bowl.glb');
    assert.strictEqual(calls[1].init.method, 'GET'); assert.strictEqual(calls[2].init.method, 'POST');
    assert.ok(calls[2].url.endsWith('/' + id(1) + '/retry'));
    assert.throws(() => transport.getModelImport('../bad'), /id is required/);
    status = 429; await assert.rejects(transport.importModel(source), error => error.status === 429 && error.message === 'Full');
});

test('XHR transport reports actual upload progress and preserves raw body', async () => {
    const instances = [];
    class Xhr {
        constructor() { this.upload = {}; this.headers = {}; instances.push(this); }
        open(method, url) { this.method = method; this.url = url; }
        setRequestHeader(key, value) { this.headers[key] = value; }
        send(body) { this.body = body; this.upload.onprogress({ lengthComputable: true, loaded: 512, total: 1024 });
            this.status = 200; this.responseText = JSON.stringify(record(1)); this.onload(); }
    }
    const progress = [], source = file();
    const transport = Transport.createHttpTransport({ siteId: 's', layoutId: 'l', XMLHttpRequest: Xhr, fetch: () => { throw new Error('No fetch upload expected'); } });
    await transport.importModel(source, { onProgress: p => progress.push(p) });
    assert.deepStrictEqual(progress, [50]); assert.strictEqual(instances[0].body, source);
});

function catalogWorkspace(loader) {
    const ws = Object.create(Workspace.Workspace.prototype);
    Object.assign(ws, { assetCatalog: [], assetCatalogLoader: loader, assetCatalogVersion: undefined,
        assetCatalogVersionCheck: null, assetCatalogVersionCheckAgain: false, destroyed: false,
        rendered: 0, _renderAssetBrowser() { this.rendered++; }, controller: { setAssetCatalog() {} } });
    return ws;
}
test('version changes refresh unplaced assets; unchanged checks avoid rendering', async () => {
    let version = 'one', calls = 0;
    const ws = catalogWorkspace(async () => { calls++; return { catalogVersion: version, assets: [{ assetId: version, assetDefinitionRevision: 'rev' }] }; });
    await ws.checkAssetCatalogVersion(); await ws.checkAssetCatalogVersion();
    assert.strictEqual(ws.rendered, 1); assert.strictEqual(calls, 2);
    version = 'two'; await ws.checkAssetCatalogVersion();
    assert.strictEqual(ws.rendered, 2); assert.strictEqual(ws.assetCatalog[0].assetId, 'two');
    await ws.refreshAssetCatalog(); assert.strictEqual(ws.rendered, 3);
});

test('turn completion during a catalog check queues another check; failures can be retried', async () => {
    const first = deferred(); let calls = 0;
    const ws = catalogWorkspace(() => ++calls === 1 ? first.promise : Promise.resolve({ catalogVersion: 'new', assets: [{ assetId: 'new', assetDefinitionRevision: 'rev' }] }));
    const pending = ws.checkAssetCatalogVersion(); await flush(); ws.checkAssetCatalogVersion();
    first.resolve({ catalogVersion: 'old', assets: [] }); await pending;
    assert.strictEqual(ws.assetCatalogVersion, 'new'); assert.strictEqual(calls, 2);
    ws.assetCatalogLoader = async () => { throw new Error('offline'); };
    await assert.rejects(ws.checkAssetCatalogVersion(), /offline/); assert.strictEqual(ws.assetCatalogVersionCheck, null);
    ws.assetCatalogLoader = async () => ({ catalogVersion: 'again', assets: [] }); await ws.checkAssetCatalogVersion();
    assert.strictEqual(ws.assetCatalogVersion, 'again');
});

test('catalog normalization preserves attribution independently of the source', () => {
    const attribution = { title: '<b>Bowl</b>', author: 'Artist', license: 'CC BY 4.0', sourceUrl: 'https://example.org/model' };
    const normalized = Workspace.normalizeCatalog([{ assetId: 'bowl', assetDefinitionRevision: 'rev', attribution }])[0];
    assert.deepStrictEqual(normalized.attribution, attribution); assert.notStrictEqual(normalized.attribution, attribution);
    assert.strictEqual(Workspace.normalizeCatalog([{ assetId: 'old', assetDefinitionRevision: 'rev' }])[0].attribution, null);
});

test('inline scripts parse and send/restore/reconnect paths include model hooks', () => {
    const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
    const scripts = Array.from(html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi));
    for (const [, attributes, code] of scripts) {
        if (!code.trim() || /type=["'](?:module|importmap|application\/ld\+json)/.test(attributes)) continue;
        new vm.Script(code);
    }
    const send = html.slice(html.indexOf('async function handleAgentSend('), html.indexOf('// === Scout Browser Search'));
    assert.ok(send.includes('{ attachments: modelAttachments }'));
    assert.ok(send.indexOf('{ attachments: modelAttachments }') < send.indexOf('_chatMemoryRuntime.frozenRequest('));
    assert.ok(send.includes('if (modelSendSucceeded) _modelChatAttachments.sent(modelAttachmentSnapshot)'));
    assert.ok(send.includes('if (originFacilityApp) void _trainCheckFacilityAssetCatalog(originFacilityApp)'));
    assert.ok(html.includes("window.addEventListener('online'"));
    assert.ok(html.includes('function restoreSessionFromSnapshot(agentKey, rawSession) {\n                _modelChatAttachments?.clear();'));
});


test('older catalog responses cannot overwrite an immediate registration refresh', async () => {
    const old = deferred(); let calls = 0;
    const ws = catalogWorkspace(() => ++calls === 1 ? old.promise : Promise.resolve({
        catalogVersion: 'new', assets: [{ assetId: 'new', assetDefinitionRevision: 'rev' }] }));
    const checking = ws.checkAssetCatalogVersion(); await flush();
    await ws.refreshAssetCatalog(); old.resolve({ catalogVersion: 'old', assets: [] }); await checking;
    assert.strictEqual(ws.assetCatalogVersion, 'new'); assert.strictEqual(ws.assetCatalog[0].assetId, 'new');
    ws.destroyed = true; assert.strictEqual(await ws.refreshAssetCatalog(), false);
});

test('Credit line displays title, author and licence as text', () => {
    const elements = [];
    const document = { createElement: tag => {
        const node = { tag, children: [], setAttribute(key, value) { this[key] = value; },
            appendChild(child) { this.children.push(child); } };
        elements.push(node); return node;
    } };
    const context = { document, assetBrowserState: { selected: {} }, _assetBrowserTotals: () => ({ totalItems: 0 }) };
    const asset = Workspace.normalizeCatalog([{ assetId: 'bowl', assetDefinitionRevision: 'rev',
        attribution: { title: '<script>title</script>', author: 'Artist', license: 'CC BY' } }])[0];
    Workspace.Workspace.prototype._renderAssetBrowserCard.call(context, asset);
    const credit = elements.find(e => e.className === 'ip-flw-asset-card-credit');
    assert.strictEqual(credit.textContent, 'Credit: <script>title</script> | Artist | CC BY');
    assert.strictEqual(credit.innerHTML, undefined);
});

test('page eligibility requires Sage, Facility Layout, a loaded binding and edit capability', () => {
    const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
    const start = html.indexOf('            function _modelChatContext()');
    const end = html.indexOf('            _modelChatAttachments =', start);
    const sandbox = { _trainFacilityLayoutAuthoringApp: { session: { getState: () => ({ loaded: true, baseRevision: 'rev' }) },
        transport: { siteId: 'site', layoutId: 'layout' }, workspace: { capabilities: { manualAuthoring: true } } },
        _currentConversationId: 'chat', currentAgent: 'deviation-analyst', state: { activeTab: 'training' },
        _trainIsFacilityLayoutMode: () => true, _currentConversationIsLegacyArchive: () => false };
    vm.createContext(sandbox); vm.runInContext(html.slice(start, end), sandbox);
    assert.strictEqual(sandbox._modelChatContext().enabled, true);
    sandbox.currentAgent = 'inspector'; assert.strictEqual(sandbox._modelChatContext().enabled, false);
    sandbox.currentAgent = 'deviation-analyst'; sandbox.state.activeTab = '3dmodel';
    assert.strictEqual(sandbox._modelChatContext().enabled, false);
    sandbox.state.activeTab = 'training'; sandbox._trainFacilityLayoutAuthoringApp.workspace.capabilities.manualAuthoring = false;
    assert.strictEqual(sandbox._modelChatContext().enabled, false);
    sandbox._trainFacilityLayoutAuthoringApp.workspace.capabilities.manualAuthoring = true;
    sandbox._trainFacilityLayoutAuthoringApp.session.getState = () => ({ loaded: false });
    assert.strictEqual(sandbox._modelChatContext().enabled, false);
});

(async function () {
    let failures = 0;
    for (const { name, fn } of tests) {
        try { await fn(); console.log('PASS ' + name); }
        catch (error) { failures++; console.error('FAIL ' + name); console.error(error.stack || error); }
    }
    console.log((tests.length - failures) + '/' + tests.length + ' tests passed');
    if (failures) process.exitCode = 1;
}());
