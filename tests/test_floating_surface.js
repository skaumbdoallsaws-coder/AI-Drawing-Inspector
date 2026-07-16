'use strict';

const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const runtime = require(path.join(ROOT, 'static', 'floating_surface.js'));

class FakeElement {
    constructor(document, name) {
        this.ownerDocument = document;
        this.name = name || 'element';
        this.parentNode = null;
        this.children = [];
        this.style = {};
        this.attributes = {};
        this.focusCount = 0;
        this.rect = { x: 0, y: 0, left: 0, top: 0, width: 20, height: 20, right: 20, bottom: 20 };
    }

    appendChild(child) {
        if (child.parentNode) child.parentNode.removeChild(child);
        child.parentNode = this;
        this.children.push(child);
        return child;
    }

    removeChild(child) {
        const index = this.children.indexOf(child);
        if (index >= 0) this.children.splice(index, 1);
        child.parentNode = null;
        return child;
    }

    remove() {
        if (this.parentNode) this.parentNode.removeChild(this);
    }

    contains(target) {
        if (target === this) return true;
        return this.children.some(child => child.contains(target));
    }

    getBoundingClientRect() {
        return this.rect;
    }

    setAttribute(name, value) {
        this.attributes[name] = String(value);
    }

    focus() {
        this.focusCount += 1;
    }

    get isConnected() {
        let cursor = this;
        while (cursor) {
            if (cursor === this.ownerDocument.body) return true;
            cursor = cursor.parentNode;
        }
        return false;
    }
}

class FakeDocument {
    constructor() {
        this.listeners = new Map();
        this.body = new FakeElement(this, 'body');
    }

    createElement(name) {
        return new FakeElement(this, name);
    }

    addEventListener(type, handler) {
        if (!this.listeners.has(type)) this.listeners.set(type, new Set());
        this.listeners.get(type).add(handler);
    }

    removeEventListener(type, handler) {
        const handlers = this.listeners.get(type);
        if (handlers) handlers.delete(handler);
    }

    dispatch(type, fields) {
        const event = Object.assign({
            type,
            target: null,
            key: '',
            prevented: false,
            stopped: false,
            preventDefault() { this.prevented = true; },
            stopPropagation() { this.stopped = true; },
        }, fields || {});
        const handlers = this.listeners.get(type);
        if (handlers) Array.from(handlers).forEach(handler => handler(event));
        return event;
    }

    listenerCount(type) {
        const handlers = this.listeners.get(type);
        return handlers ? handlers.size : 0;
    }
}

function createPositioning() {
    const state = {
        computeCalls: [],
        autoUpdateCalls: [],
        cleanupCount: 0,
        result: { x: 12, y: 34, placement: 'top', strategy: 'fixed', middlewareData: {} },
        computePosition(reference, floating, options) {
            state.computeCalls.push({ reference, floating, options });
            return Promise.resolve(state.result);
        },
        autoUpdate(reference, floating, update, options) {
            const call = { reference, floating, update, options, cleaned: false };
            state.autoUpdateCalls.push(call);
            update();
            return function () {
                if (call.cleaned) return;
                call.cleaned = true;
                state.cleanupCount += 1;
            };
        },
    };
    return state;
}

function fixture() {
    const document = new FakeDocument();
    const positioning = createPositioning();
    const warnings = [];
    const manager = runtime.createSurfaceManager({
        document,
        positioning,
        logger: { warn: (...args) => warnings.push(args) },
    });
    return { document, positioning, warnings, manager };
}

function nextTurn() {
    return new Promise(resolve => setTimeout(resolve, 0));
}

let checks = 0;
async function check(name, fn) {
    await fn();
    checks += 1;
    process.stdout.write(`PASS ${name}\n`);
}

(async function run() {
    await check('vendored UMD files match their pins and expose browser globals', async () => {
        const vendorRoot = path.join(ROOT, 'static', 'vendor', 'floating-ui');
        const corePath = path.join(vendorRoot, 'floating-ui.core.umd.min.js');
        const domPath = path.join(vendorRoot, 'floating-ui.dom.umd.min.js');
        const licensePath = path.join(vendorRoot, 'LICENSE');
        const sha256 = filePath => crypto.createHash('sha256')
            .update(fs.readFileSync(filePath))
            .digest('hex')
            .toUpperCase();

        assert.strictEqual(
            sha256(corePath),
            'FC0CCA21A6CF2EF0C9C908FBEDE0614DCAF285E8EBFED20D0E144FAFC2EBF059'
        );
        assert.strictEqual(
            sha256(domPath),
            '214B5E019F70FDA36C7F0A35E5EB3AA84FA53448C0F8CAC4F7A4C1E26E71498C'
        );
        assert.strictEqual(
            sha256(licensePath),
            '0E4C9A9B6C71019CBBEA3BDC20B01223110A9035700F9C960C8FCBF78C2325CE'
        );

        const context = vm.createContext({ console });
        vm.runInContext(fs.readFileSync(corePath, 'utf8'), context, { filename: corePath });
        vm.runInContext(fs.readFileSync(domPath, 'utf8'), context, { filename: domPath });
        assert.strictEqual(typeof context.FloatingUICore.computePosition, 'function');
        assert.strictEqual(typeof context.FloatingUIDOM.computePosition, 'function');
        assert.strictEqual(typeof context.FloatingUIDOM.autoUpdate, 'function');
    });

    await check('open mounts and positions one surface', async () => {
        const { document, positioning, manager } = fixture();
        const reference = document.createElement('button');
        const floating = document.createElement('div');
        const clippedParent = document.createElement('div');
        document.body.appendChild(reference);
        document.body.appendChild(clippedParent);
        clippedParent.appendChild(floating);

        assert.strictEqual(manager.available, true);
        assert.strictEqual(manager.open({ reference, floating, key: 'card-a' }), true);
        await nextTurn();

        assert.strictEqual(manager.isOpen(), true);
        assert.strictEqual(floating.parentNode, document.body);
        assert.strictEqual(floating.style.position, 'fixed');
        assert.strictEqual(floating.style.left, '12px');
        assert.strictEqual(floating.style.top, '34px');
        assert.strictEqual(floating.attributes['data-placement'], 'top');
        assert.strictEqual(positioning.autoUpdateCalls.length, 1);
        assert.strictEqual(document.listenerCount('pointerdown'), 1);
        assert.strictEqual(document.listenerCount('keydown'), 1);
    });

    await check('synchronous positioning failures are contained', async () => {
        const { document, positioning, warnings, manager } = fixture();
        const reference = document.createElement('button');
        const floating = document.createElement('div');
        document.body.appendChild(reference);
        positioning.computePosition = function () {
            throw new Error('synthetic positioning failure');
        };

        assert.strictEqual(manager.open({ reference, floating }), true);
        assert.strictEqual(await manager.reposition(), false);
        assert.ok(warnings.length >= 1);
        assert.strictEqual(manager.isOpen(), true);
        manager.close('done');
    });

    await check('opening a second surface replaces and cleans the first', async () => {
        const { document, positioning, manager } = fixture();
        const firstReference = document.createElement('button');
        const secondReference = document.createElement('button');
        const firstSurface = document.createElement('div');
        const secondSurface = document.createElement('div');
        document.body.appendChild(firstReference);
        document.body.appendChild(secondReference);

        manager.open({ reference: firstReference, floating: firstSurface, key: 'first' });
        manager.open({ reference: secondReference, floating: secondSurface, key: 'second' });
        await nextTurn();

        assert.strictEqual(firstSurface.parentNode, null);
        assert.strictEqual(secondSurface.parentNode, document.body);
        assert.strictEqual(firstReference.focusCount, 0);
        assert.strictEqual(positioning.cleanupCount, 1);
        assert.strictEqual(manager.getActive().key, 'second');
        assert.strictEqual(document.listenerCount('pointerdown'), 1);
    });

    await check('close is idempotent and restores focus once', async () => {
        const { document, positioning, manager } = fixture();
        const reference = document.createElement('button');
        const floating = document.createElement('div');
        document.body.appendChild(reference);
        manager.open({ reference, floating });

        assert.strictEqual(manager.close('test'), true);
        assert.strictEqual(manager.close('again'), false);
        assert.strictEqual(reference.focusCount, 1);
        assert.strictEqual(positioning.cleanupCount, 1);
        assert.strictEqual(floating.parentNode, null);
        assert.strictEqual(document.listenerCount('pointerdown'), 0);
        assert.strictEqual(document.listenerCount('keydown'), 0);
    });

    await check('inside presses stay open and outside presses dismiss', async () => {
        const { document, manager } = fixture();
        const reference = document.createElement('button');
        const floating = document.createElement('div');
        const floatingChild = document.createElement('span');
        const outsider = document.createElement('div');
        document.body.appendChild(reference);
        document.body.appendChild(outsider);
        floating.appendChild(floatingChild);
        manager.open({ reference, floating });

        document.dispatch('pointerdown', { target: floatingChild });
        assert.strictEqual(manager.isOpen(), true);
        document.dispatch('pointerdown', { target: reference });
        assert.strictEqual(manager.isOpen(), true);
        document.dispatch('pointerdown', { target: outsider });
        assert.strictEqual(manager.isOpen(), false);
        assert.strictEqual(reference.focusCount, 1);
    });

    await check('an integration can retain a surface for managed canvas presses', async () => {
        const { document, manager } = fixture();
        const reference = document.createElement('button');
        const floating = document.createElement('div');
        const canvas = document.createElement('div');
        const canvasChild = document.createElement('span');
        const outsider = document.createElement('div');
        document.body.appendChild(reference);
        document.body.appendChild(canvas);
        document.body.appendChild(outsider);
        canvas.appendChild(canvasChild);
        manager.open({
            reference,
            floating,
            shouldCloseOnOutsidePointerDown: event => !canvas.contains(event.target),
        });

        document.dispatch('pointerdown', { target: canvasChild });
        assert.strictEqual(manager.isOpen(), true);
        document.dispatch('pointerdown', { target: outsider });
        assert.strictEqual(manager.isOpen(), false);
    });

    await check('Escape dismisses and consumes the key', async () => {
        const { document, manager } = fixture();
        const reference = document.createElement('button');
        const floating = document.createElement('div');
        document.body.appendChild(reference);
        manager.open({ reference, floating });

        const event = document.dispatch('keydown', { key: 'Escape', target: floating });
        assert.strictEqual(manager.isOpen(), false);
        assert.strictEqual(event.prevented, true);
        assert.strictEqual(event.stopped, true);
        assert.strictEqual(reference.focusCount, 1);
    });

    await check('an integration can consume Escape before the surface closes', async () => {
        const { document, manager } = fixture();
        const reference = document.createElement('button');
        const floating = document.createElement('div');
        const editorField = document.createElement('input');
        document.body.appendChild(reference);
        floating.appendChild(editorField);
        manager.open({
            reference,
            floating,
            shouldCloseOnEscape: event => event.target !== editorField,
        });

        const retained = document.dispatch('keydown', { key: 'Escape', target: editorField });
        assert.strictEqual(manager.isOpen(), true);
        assert.strictEqual(retained.prevented, false);
        assert.strictEqual(retained.stopped, false);
        const closed = document.dispatch('keydown', { key: 'Escape', target: floating });
        assert.strictEqual(manager.isOpen(), false);
        assert.strictEqual(closed.prevented, true);
        assert.strictEqual(closed.stopped, true);
    });

    await check('reanchor restarts observation without replacing the surface', async () => {
        const { document, positioning, manager } = fixture();
        const firstReference = document.createElement('button');
        const secondReference = document.createElement('button');
        const floating = document.createElement('div');
        document.body.appendChild(firstReference);
        document.body.appendChild(secondReference);
        manager.open({ reference: firstReference, floating });

        assert.strictEqual(manager.reanchor(secondReference, {
            placement: 'right',
            middleware: [{ name: 'synthetic' }],
            restoreFocusElement: secondReference,
        }), true);
        await nextTurn();

        assert.strictEqual(manager.getActive().reference, secondReference);
        assert.strictEqual(manager.getActive().floating, floating);
        assert.strictEqual(manager.getActive().placement, 'right');
        assert.strictEqual(positioning.autoUpdateCalls.length, 2);
        assert.strictEqual(positioning.cleanupCount, 1);
        manager.close('done');
        assert.strictEqual(positioning.cleanupCount, 2);
    });

    await check('stale asynchronous positioning cannot mutate a closed surface', async () => {
        const { document, positioning, manager } = fixture();
        const reference = document.createElement('button');
        const floating = document.createElement('div');
        document.body.appendChild(reference);
        let resolvePosition;
        positioning.computePosition = function () {
            return new Promise(resolve => { resolvePosition = resolve; });
        };
        manager.open({ reference, floating });
        manager.close('before_position');
        resolvePosition({ x: 99, y: 77, placement: 'bottom', strategy: 'fixed' });
        await nextTurn();

        assert.strictEqual(floating.style.left, undefined);
        assert.strictEqual(floating.style.top, undefined);
    });

    await check('latest asynchronous position request wins during rapid updates', async () => {
        const { document, positioning, manager } = fixture();
        const reference = document.createElement('button');
        const floating = document.createElement('div');
        const pending = [];
        document.body.appendChild(reference);
        positioning.computePosition = function () {
            return new Promise(resolve => pending.push(resolve));
        };
        manager.open({ reference, floating });
        const latest = manager.reposition();
        assert.strictEqual(pending.length, 2);

        pending[1]({ x: 44, y: 55, placement: 'top', strategy: 'fixed' });
        assert.strictEqual(await latest, true);
        pending[0]({ x: 3, y: 4, placement: 'bottom', strategy: 'fixed' });
        await nextTurn();

        assert.strictEqual(floating.style.left, '44px');
        assert.strictEqual(floating.style.top, '55px');
        assert.strictEqual(floating.attributes['data-placement'], 'top');
        manager.close('done');
    });

    await check('destroy prevents reuse and does not restore focus', async () => {
        const { document, manager } = fixture();
        const reference = document.createElement('button');
        const floating = document.createElement('div');
        document.body.appendChild(reference);
        manager.open({ reference, floating });
        manager.destroy();

        assert.strictEqual(manager.isOpen(), false);
        assert.strictEqual(reference.focusCount, 0);
        assert.strictEqual(manager.open({ reference, floating }), false);
    });

    await check('missing positioning runtime returns a safe disabled manager', async () => {
        const document = new FakeDocument();
        const warnings = [];
        const logger = { warn: (...args) => warnings.push(args) };
        const first = runtime.createSurfaceManager({ document, positioning: {}, logger });
        const second = runtime.createSurfaceManager({ document, positioning: {}, logger });

        assert.strictEqual(first.available, false);
        assert.strictEqual(first.open({}), false);
        assert.strictEqual(await first.reposition(), false);
        first.destroy();
        second.destroy();
        assert.strictEqual(warnings.length, 1);
    });

    process.stdout.write(`Floating surface checks passed: ${checks}\n`);
})().catch(error => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
});
