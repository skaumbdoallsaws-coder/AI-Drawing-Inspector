'use strict';

// Sage's 3D shots in the app page (docs/sage-basic-shapes-plan.md, SV1 to SV3): the running step of
// show_facility_views asks this window for the shots; the page has the workspace take them and posts them to the
// server, or posts at once why it cannot. The chat shows them as a row of pictures (chat_rich_content.js): a click
// moves the 3D view there, a second opens the shot full size. The page's functions are taken from static/index.html
// as they ship.
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const rich = require('../static/chat_rich_content.js');

const page = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8').replace(/\r\n/g, '\n');

function slice(startText, endText) {
    const start = page.indexOf(startText);
    assert.ok(start >= 0, 'missing ' + startText);
    const end = page.indexOf(endText, start);
    assert.ok(end > start, 'no end for ' + startText);
    return page.slice(start, end + endText.length);
}

const source = slice('        const _trainFacilitySageCaptures = new Set();', '\n')
    + slice('        function _trainFacilityCaptureFromStep(step, signal) {', '\n        }\n')
    + slice('        function _trainFacilityShowShot(view) {', '\n        }\n');

class FakeFormData {
    constructor() { this.entries = []; }
    append(name, value, fileName) { this.entries.push([name, value, fileName]); }
}

// The page's two functions, with APP as _trainFacilityLayoutAuthoringApp; fetch and console.warn are noted.
function load(app) {
    const posts = [];
    const warnings = [];
    const fetch = (url, init) => {
        posts.push({ url, init });
        return Promise.resolve({ ok: true });
    };
    const consoleRef = { warn: (...args) => warnings.push(args) };
    const made = new Function('_trainFacilityLayoutAuthoringApp', 'FormData', 'fetch', 'console',
        source + '\nreturn { capture: _trainFacilityCaptureFromStep, show: _trainFacilityShowShot };');
    return Object.assign(made(app, FakeFormData, fetch, consoleRef), { posts, warnings });
}

// A small DOM for the shots block: elements with children, attributes and listeners, a body, and key presses.
function shotsDocument() {
    const keys = new Map();
    const make = tag => ({
        tagName: tag, children: [], attributes: {}, listeners: {}, parentNode: null, focused: false,
        setAttribute(key, value) { this.attributes[key] = String(value); },
        getAttribute(key) {
            return Object.prototype.hasOwnProperty.call(this.attributes, key) ? this.attributes[key] : null;
        },
        appendChild(child) {
            child.parentNode = this;
            this.children.push(child);
            return child;
        },
        removeChild(child) {
            this.children = this.children.filter(item => item !== child);
            child.parentNode = null;
        },
        addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
        click() { (this.listeners.click || []).forEach(fn => fn({ target: this })); },
        focus() { this.focused = true; },
    });
    return {
        createElement: make,
        createTextNode: text => ({ text }),
        body: make('body'),
        defaultView: {
            addEventListener(type, fn) { keys.set(fn, type); },
            removeEventListener(type, fn) { keys.delete(fn); },
            key(name) { Array.from(keys.keys()).forEach(fn => fn({ key: name })); },
            listening() { return keys.size; },
        },
    };
}

function find(node, test) {
    if (test(node)) return node;
    for (const child of node.children || []) {
        const found = find(child, test);
        if (found) return found;
    }
    return null;
}

const ID = 'ab'.repeat(16);
const URL = '/api/facility-layouts/site-local/fl-a/sage-shots/' + ID;
const SHOT_URL = URL + '/';
const SHOT_CAMERA = { position: { x: 20, y: 5, z: 10 }, target: { x: 20, y: 0.7, z: 18 }, fov: 50 };
const settle = () => new Promise(resolve => setImmediate(resolve));
let passed = 0;

async function check(name, fn) {
    try {
        await fn();
        passed += 1;
        console.log('PASS ' + name);
    } catch (error) {
        console.error('FAIL ' + name + ': ' + error.message);
        process.exitCode = 1;
    }
}

(async () => {
    await check('the running step that asks for shots has the workspace take them and posts them once', async () => {
        const requests = [];
        const app = { workspace: { captureSageViews: request => {
            requests.push(request);
            return Promise.resolve({ complete: true, reason: null, shots: [
                { index: 0, image: { blob: 'jpeg-0', width: 1045, height: 532 } },
                { index: 1, image: { blob: 'jpeg-1', width: 1045, height: 532 } }] });
        } } };
        const hook = load(app);
        const capture = { requestId: ID, url: URL, siteId: 'site-local', layoutId: 'fl-a', revision: 'r-1',
            views: [{ label: 'A' }, { label: 'B' }] };
        const step = { id: 3, kind: 'tool', state: 'running', label: 'Taking 3D shots of A', capture };
        hook.capture(step);
        hook.capture(step);   // the same step again: one capture
        await settle();
        await settle();
        assert.deepStrictEqual(requests, [capture]);
        assert.strictEqual(hook.posts.length, 1);
        const { url, init } = hook.posts[0];
        assert.deepStrictEqual([url, init.method, init.credentials], [URL, 'POST', 'same-origin']);
        const entries = init.body.entries;
        assert.deepStrictEqual(JSON.parse(entries[0][1]), { complete: true, reason: null, shots: [
            { index: 0, width: 1045, height: 532 }, { index: 1, width: 1045, height: 532 }] });
        assert.deepStrictEqual(entries.slice(1),
            [['shot', 'jpeg-0', 'shot-0.jpg'], ['shot', 'jpeg-1', 'shot-1.jpg']]);
    });

    await check('a window that cannot take the shots says why at once; other steps ask for nothing', async () => {
        const none = load(null);
        none.capture({ state: 'running', capture: { requestId: ID, url: URL } });
        await settle();
        assert.deepStrictEqual(JSON.parse(none.posts[0].init.body.entries[0][1]),
            { complete: false, reason: 'no_app', shots: [] });
        const broken = load({ workspace: { captureSageViews: () => { throw new Error('lost context'); } } });
        broken.capture({ state: 'running', capture: { requestId: ID, url: URL } });
        await settle();
        await settle();
        assert.deepStrictEqual(JSON.parse(broken.posts[0].init.body.entries[0][1]),
            { complete: false, reason: 'failed', shots: [] });
        assert.strictEqual(broken.warnings.length, 1);
        const quiet = load({ workspace: { captureSageViews: () => assert.fail('no capture') } });
        for (const step of [{ state: 'done', capture: { requestId: ID, url: URL } },
            { state: 'running', capture: { requestId: 'short', url: URL } },
            { state: 'running', capture: { requestId: ID, url: 'https://example.com/x' } },
            { state: 'running', capture: { requestId: ID, url: '/api/other/' + ID } },
            { state: 'running' }]) {
            quiet.capture(step);
        }
        await settle();
        assert.strictEqual(quiet.posts.length, 0);
    });

    await check('a shot in the chat moves the 3D view there, or says it cannot', async () => {
        const seen = [];
        const app = { workspace: { showSageView: view => {
            seen.push(view);
            return Promise.resolve(true);
        } } };
        assert.strictEqual(await load(app).show({ label: 'A' }), true);
        assert.deepStrictEqual(seen, [{ label: 'A' }]);
        assert.strictEqual(await load(null).show({ label: 'A' }), false);
        const failing = { workspace: { showSageView: () => Promise.reject(new Error('gone')) } };
        assert.strictEqual(await load(failing).show({ label: 'A' }), false);
    });

    await check('the page wires both: each agent step, and each shots block\'s click', async () => {
        assert.ok(page.includes('_trainFacilityShowFromStep(event.step);\n'
            + '                                    _trainFacilityCaptureFromStep(event.step, captureStop.signal);'));
        assert.ok(page.includes('onShotView: _trainFacilityShowShot,'));
        assert.ok(page.includes("'sources', 'facts', 'visualization', 'entity_reference', 'actions', 'shots',"));
    });

    await check('a shots block keeps only saved shots, each with its view\'s camera when that is sound', () => {
        const [block] = rich.normalizeBlocks([{ type: 'shots', siteId: 'site-local', layoutId: 'fl-a',
            revision: 'r-1', folded: true, shots: [
                { label: 'Dock Door S1', url: SHOT_URL + '0.jpg', from: 'east', roofHidden: true,
                    camera: SHOT_CAMERA, width: 1045, height: 532 },
                { label: 'Below', url: SHOT_URL + '1.jpg',
                    camera: Object.assign({}, SHOT_CAMERA, { position: { x: 0, y: 0, z: 0 } }) },
                { label: 'Elsewhere', url: 'https://example.com/a.jpg' },
                { label: '', url: SHOT_URL + '2.jpg' },
            ] }]);
        assert.deepStrictEqual(block, { type: 'shots', siteId: 'site-local', layoutId: 'fl-a', revision: 'r-1',
            folded: true, shots: [
                { label: 'Dock Door S1', url: SHOT_URL + '0.jpg', from: 'east', roofHidden: true,
                    camera: SHOT_CAMERA, width: 1045, height: 532 },
                { label: 'Below', url: SHOT_URL + '1.jpg', from: '', roofHidden: false, camera: null },
            ] });
        for (const url of ['/api/facility-layouts/site-local/fl-a/sage-shots/xyz/0.jpg', SHOT_URL + '6.jpg',
            SHOT_URL.replace('/api/', '/static/') + '0.jpg', SHOT_URL + '0.jpg?x=1', 'javascript:alert(1)']) {
            assert.strictEqual(rich.normalizeBlocks([{ type: 'shots', shots: [{ label: 'A', url }] }]).length, 0,
                url);
        }
    });

    await check('a click on a shot moves the 3D view there, a second opens it full size, and one the view cannot '
        + 'reach opens full size at once', async () => {
        const documentRef = shotsDocument();
        const asked = [];
        let reach = true;
        const block = { type: 'shots', siteId: 'site-local', layoutId: 'fl-a', revision: 'r-1', shots: [
            { label: 'Assembly Cell A06', url: SHOT_URL + '0.jpg', from: 'south', camera: SHOT_CAMERA },
            { label: 'Dock Door S1', url: SHOT_URL + '1.jpg', from: 'east', roofHidden: true,
                camera: SHOT_CAMERA }] };
        const section = rich.renderBlock(documentRef, block, { onShotView: view => {
            asked.push(view);
            return Promise.resolve(reach);
        } });
        assert.ok(section.className.includes('agent-shots'));
        const row = find(section, node => node.className === 'agent-shots-row');
        const [first, second] = row.children;
        assert.deepStrictEqual(row.children.map(button => [button.tagName, button.children[0].src,
            button.children[0].alt, button.children[1].textContent]), [
            ['button', SHOT_URL + '0.jpg', 'Assembly Cell A06', 'Assembly Cell A06'],
            ['button', SHOT_URL + '1.jpg', 'Dock Door S1', 'Dock Door S1']]);
        first.click();
        await settle();
        assert.deepStrictEqual(asked, [{ siteId: 'site-local', layoutId: 'fl-a', revision: 'r-1',
            label: 'Assembly Cell A06', from: 'south', roofHidden: false, camera: SHOT_CAMERA }]);
        assert.deepStrictEqual([first.getAttribute('aria-pressed'), second.getAttribute('aria-pressed'),
            documentRef.body.children.length], ['true', 'false', 0], 'the view moved; nothing opened');
        first.click();
        await settle();
        assert.strictEqual(asked.length, 1, 'a second click does not move it again');
        const overlay = documentRef.body.children[0];
        assert.deepStrictEqual([overlay.className, overlay.getAttribute('aria-modal'), overlay.children[0].src],
            ['agent-shot-full', 'true', SHOT_URL + '0.jpg']);
        documentRef.defaultView.key('Escape');
        assert.deepStrictEqual([documentRef.body.children.length, documentRef.defaultView.listening()], [0, 0]);
        reach = false;   // another layout in the window, say
        second.click();
        await settle();
        assert.strictEqual(asked.length, 2);
        assert.strictEqual(documentRef.body.children[0].children[0].src, SHOT_URL + '1.jpg', 'full size at once');
        find(documentRef.body.children[0], node => node.className === 'agent-shot-full-close').click();
        assert.strictEqual(documentRef.body.children.length, 0);
        assert.deepStrictEqual([first.getAttribute('aria-pressed'), second.getAttribute('aria-pressed')],
            ['true', 'false']);
    });

    await check('a set retaken after a fix is folded under "Earlier 3D shots"', () => {
        const documentRef = shotsDocument();
        const section = rich.renderBlock(documentRef, { type: 'shots', folded: true, shots: [
            { label: 'Assembly Cell A06', url: SHOT_URL + '0.jpg' }] }, {});
        const details = section.children[0];
        assert.deepStrictEqual([details.tagName, details.open, details.children[0].tagName,
            details.children[0].textContent], ['details', undefined, 'summary', 'Earlier 3D shots (1)']);
        assert.ok(find(details, node => node.className === 'agent-shots-row'));
    });

    await check('round 2: Stop or the end of the tool\'s wait stops the capture, and nothing is sent', async () => {
        // A capture that runs until it is stopped.
        const held = () => {
            const stops = [];
            let finish = null;
            const workspace = {
                captureSageViews: () => new Promise(resolve => { finish = resolve; }),
                stopSageCapture: requestId => {
                    stops.push(requestId);
                    finish({ complete: false, reason: 'interrupted', shots: [] });
                    return true;
                },
            };
            return { app: { workspace }, stops };
        };
        const step = extra => ({ state: 'running', capture: Object.assign({ requestId: ID, url: URL }, extra) });

        const stop = held();
        const hook = load(stop.app);
        const turn = new AbortController();
        hook.capture(step({ waitMs: 60000 }), turn.signal);
        await settle();
        turn.abort();   // the user pressed Stop
        await settle();
        await settle();
        assert.deepStrictEqual([stop.stops, hook.posts.length], [[ID], 0]);

        const late = held();
        const timed = load(late.app);
        timed.capture(step({ waitMs: 20 }), new AbortController().signal);
        await new Promise(resolve => setTimeout(resolve, 60));
        await settle();
        assert.deepStrictEqual([late.stops, timed.posts.length], [[ID], 0], 'the tool stopped waiting');

        const stopped = new AbortController();
        stopped.abort();
        const never = load({ workspace: { captureSageViews: () => assert.fail('no capture') } });
        never.capture(step({}), stopped.signal);
        await settle();
        assert.strictEqual(never.posts.length, 0, 'a turn already stopped asks for nothing');

        // A capture that ends in time posts with the turn's signal, so Stop also ends the upload.
        const quick = load({ workspace: { captureSageViews: () => Promise.resolve({ complete: true, reason: null,
            shots: [] }) } });
        const live = new AbortController();
        quick.capture(step({ waitMs: 60000 }), live.signal);
        await settle();
        await settle();
        assert.strictEqual(quick.posts.length, 1);
        assert.strictEqual(quick.posts[0].init.signal, live.signal);
    });

    await check('round 2: a shot link of the longest site and layout ids is kept; malformed shots are dropped', () => {
        const encoded = '/api/facility-layouts/s' + '%3A'.repeat(127) + '/l' + '%3A'.repeat(127) + '/sage-shots/'
            + ID + '/5.jpg';
        const plain = '/api/facility-layouts/' + 's'.repeat(128) + '/' + 'l'.repeat(128) + '/sage-shots/' + ID + '/0.jpg';
        assert.deepStrictEqual([plain.length, encoded.length], [329, 837]);
        for (const url of [plain, encoded]) {
            const [block] = rich.normalizeBlocks([{ type: 'shots', shots: [{ label: 'A', url }] }]);
            assert.strictEqual(block.shots[0].url, url);
        }
        assert.strictEqual(rich.normalizeBlocks([{ type: 'shots', shots: [{ label: 'A', url: encoded + 'x' }] }])
            .length, 0);
        for (const shots of [5, true, 'abc', { url: plain }, [null, 5, 'x', { label: 'A', url: 5 },
            { label: 'A', url: { toString: () => plain } }]]) {
            assert.strictEqual(rich.normalizeBlocks([{ type: 'shots', shots }]).length, 0, JSON.stringify(shots));
        }
    });

    console.log(passed + ' Sage shots page checks passed');
})();
