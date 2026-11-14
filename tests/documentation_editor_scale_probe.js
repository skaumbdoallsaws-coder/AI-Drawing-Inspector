/* P5a measurement instrumentation, injected by the isolated smoke only. */
(function (root) {
    'use strict';
    function summary(samples) {
        if (!samples.length || samples.some(x => !Number.isFinite(x) || x < 0)) throw Error('Missing measurement');
        const sorted = [...samples].sort((a, b) => a - b), n = sorted.length;
        return {median: n % 2 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2,
            p95: sorted[Math.ceil(n * .95) - 1], samples: [...samples]};
    }
    function contrast(foreground, background) {
        const luminance = color => color.slice(0, 3).map(x => x / 255)
            .map(x => x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4)
            .reduce((v, x, i) => v + x * [.2126, .7152, .0722][i], 0);
        const alpha = foreground[3] ?? 1;
        const rgb = foreground.slice(0, 3).map((x, i) => x * alpha + background[i] * (1 - alpha));
        const a = luminance(rgb), b = luminance(background);
        return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
    }
    if (typeof module === 'object' && module.exports) { module.exports = {summary, contrast}; return; }
    if (root.P5aProbe) return;
    const raf = () => new Promise(resolve => requestAnimationFrame(resolve));
    function until(test, timeout) {
        return new Promise((resolve, reject) => {
            let frame;
            const finish = (value, error) => {
                clearTimeout(deadline); cancelAnimationFrame(frame);
                if (error) reject(error); else resolve(value);
            };
            const deadline = setTimeout(() => finish(null,
                Error('P5a observed condition timed out: ' + test.toString().slice(0, 220))), timeout);
            const check = () => {
                try {
                    const value = test();
                    if (value) { finish(value); return; }
                    frame = requestAnimationFrame(check);
                } catch (error) { finish(null, error); }
            };
            check();
        });
    }
    const state = () => root.__compareDbg?.state;
    const payload = () => state()?.partsManualDocumentation;
    const surface = () => document.querySelector('#documentationPublicationSurface');
    const idle = () => !document.querySelector('#documentationWorkspace.busy');
    const drawn = () => idle() && surface()?.getBoundingClientRect().width > 0 && surface()?.innerText.trim();
    const status = () => document.querySelector('.documentation-status-message')?.textContent || '';
    const editor = () => surface()?.querySelector('.documentation-rich-editor [contenteditable="true"]');
    const mounted = () => root.DocumentationRichText?.mountedCount || 0;
    const frames = async () => { await raf(); await raf(); };
    const click = selector => {
        const control = document.querySelector(selector);
        if (!control || control.disabled) throw Error('Control unavailable: ' + selector);
        control.click();
    };
    const requests = [], announcements = [], contexts = [], seenContexts = new WeakSet(), responseObservers = new Set();
    const nativeContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (...args) {
        const value = nativeContext.apply(this, args);
        if (value && !seenContexts.has(value)) { seenContexts.add(value); contexts.push({ref: new WeakRef(value), kind: args[0],
            // Supervisor: who asked for the context (the frames above this hook).
            origin: (new Error().stack || '').split('\n').slice(2, 7).map(line => line.trim()
                .replace(/https?:\/\/[^/]+\/[^:)]*/, 'app').slice(0, 110)).join(' < ')}); }
        return value;
    };
    const nativeFetch = root.fetch;
    root.fetch = async function (resource, options) {
        const row = {url: typeof resource === 'string' ? resource : resource.url || resource.href || String(resource),
            method: options?.method || resource?.method || 'GET', start: performance.now()};
        requests.push(row); if (requests.length > 200) requests.shift();
        const response = await nativeFetch.apply(this, arguments); row.status = response.status;
        for (const method of ['json', 'text', 'arrayBuffer', 'blob']) {
            const original = response[method].bind(response);
            response[method] = async (...args) => {
                const value = await original(...args); row.end = performance.now();
                if (method === 'json' && (/\/pdf$/.test(row.url) || response.status >= 400)) row.result = value;
                responseObservers.forEach(observe => observe());
                return value;
            };
        }
        return response;
    };
    const statusObserver = new MutationObserver(() => {
        const text = status(); if (text && announcements.at(-1)?.text !== text) announcements.push({text, at: performance.now()});
    });
    function observeStatus() { statusObserver.observe(document.documentElement, {subtree: true, childList: true, characterData: true}); }
    if (document.documentElement) observeStatus(); else document.addEventListener('DOMContentLoaded', observeStatus, {once: true});
    function census(origins = false) {
        const live = contexts.filter(item => item.ref.deref()); contexts.splice(0, contexts.length, ...live);
        return {editors: mounted(), editorNodes: document.querySelectorAll('.documentation-rich-editor [contenteditable="true"]').length,
            surfaces: document.querySelectorAll('#documentationPublicationSurface').length,
            canvasNodes: document.querySelectorAll('canvas').length, contexts: live.length,
            webglContexts: live.filter(item => /webgl/.test(item.kind)).length,
            viewers: document.querySelectorAll('.documentation-canvas-host canvas, #assy-viewport canvas').length,
            // Supervisor: the live contexts by kind, by whether their canvas is in the document, and by origin.
            ...(origins ? {origins: Object.entries(live.reduce((all, item) => {
                const canvas = item.ref.deref()?.canvas;
                const key = item.kind + (canvas && canvas.isConnected ? ' in the document' : ' detached')
                    + (canvas ? ' ' + canvas.width + 'x' + canvas.height : '') + ' @ ' + item.origin;
                all[key] = (all[key] || 0) + 1; return all;
            }, {})).sort((a, b) => b[1] - a[1]).slice(0, 14).map(([origin, count]) => ({count, origin}))} : {})};
    }
    // Supervisor: the page never calls the driver. A driver call made from inside a pending evaluation
    // deadlocks Playwright's sync API. An observer is armed in one evaluation, the driver then sends the
    // trusted input, and another evaluation collects the result. The interval still starts at the trusted
    // event and ends at the observed condition, both inside the page.
    let pending = null, typing = null;
    function observe(type, accept, condition, timeout, paint, finish) {
        let down = null;
        const listener = event => { if (event.isTrusted && down === null && accept(event)) down = performance.now(); };
        window.addEventListener(type, listener, true);
        pending = (async () => {
            try {
                await until(() => down !== null && condition(), timeout);
                if (paint) await frames();
                return finish(performance.now() - down);
            } finally { window.removeEventListener(type, listener, true); }
        })();
        pending.catch(() => {});
    }
    function arm(spec) {
        const timeout = spec.timeout, start = performance.now(), before = payload()?.revision;
        const request = suffix => requests.find(r => r.start >= start && r.end && r.url.endsWith(suffix));
        if (spec.action === 'selection') {
            const node = surface().querySelector('[data-documentation-object-id="' + CSS.escape(spec.objectId) + '"]');
            if (!node) throw Error('Object not drawn');
            const r = node.getBoundingClientRect();
            // Supervisor: on a figure page the press lands on the page's interaction layer, so it is judged
            // by its position; the handles counted are the object's own.
            const own = '[data-documentation-object-id="' + CSS.escape(spec.objectId) + '"]';
            observe('pointerdown', event => event.clientX >= r.left && event.clientX <= r.right
                    && event.clientY >= r.top && event.clientY <= r.bottom,
                () => surface().querySelector(own)?.querySelectorAll('.documentation-object-handle').length === 8,
                timeout, false, ms => ({ms}));
            return {point: [r.x + r.width / 2, r.y + r.height / 2]};
        }
        if (spec.action === 'escape') {
            observe('keydown', event => event.key === 'Escape', () => !mounted() && drawn(), timeout, true,
                ms => ({ms, saved: payload().revision !== before, before, after: payload().revision, status: status()}));
            return {key: 'Escape'};
        }
        if (spec.action === 'nudge') {
            observe('keydown', event => event.key === 'ArrowRight',
                () => request('/objects') && payload().revision !== before && drawn(), timeout, true,
                ms => ({ms, requests: requests.filter(r => r.start >= start)}));
            return {key: 'ArrowRight'};
        }
        if (spec.action === 'typing') {
            const node = editor(); if (!node) throw Error('No editor for typing');
            const samples = []; let down = null;
            const key = event => { if (event.isTrusted) down = performance.now(); };
            const input = async event => {
                if (!event.isTrusted || down === null) return;
                const started = down; down = null;
                await frames(); samples.push(performance.now() - started);
            };
            node.addEventListener('keydown', key); node.addEventListener('input', input);
            typing = {samples, start, stop: () => { node.removeEventListener('keydown', key); node.removeEventListener('input', input); }};
            return {key: 'x', count: 50};
        }
        throw Error('Unknown driven P5a action');
    }
    const typed = (count, timeout) => until(() => typing && typing.samples.length >= count, timeout);
    async function collect(spec) {
        if (spec.action === 'typing') {
            const value = typing; typing = null;
            if (!value) throw Error('Typing was not armed');
            value.stop();
            return {samples: value.samples, elapsed: performance.now() - value.start};
        }
        const value = pending; pending = null;
        if (!value) throw Error('No armed P5a action');
        return await value;
    }
    function responseWhen(condition, timeout) {
        // PDF navigation can background the initiating tab. Response observation
        // does not depend on its animation frames continuing after the response.
        return new Promise((resolve, reject) => {
            const finish = () => {
                const value = condition();
                if (value) { clearTimeout(deadline); responseObservers.delete(finish); resolve(value); }
            };
            const deadline = setTimeout(() => { responseObservers.delete(finish); reject(Error('P5a response condition timed out')); }, timeout);
            responseObservers.add(finish); finish();
        });
    }
    async function run(spec) {
        const timeout = spec.timeout, start = performance.now(), before = payload()?.revision;
        const request = suffix => requests.find(r => r.start >= start && r.end && r.url.endsWith(suffix));
        let result;
        if (spec.action === 'open') {
            root.__compareDbg.openDocumentationWorkflow();
            await until(() => document.querySelector('#documentationRefreshRibbon') && idle(), timeout);
            if (state().documentationDocumentType !== spec.kind) {
                click('#documentationTypeRibbonTrigger'); click('#documentationTypeRibbonOption-' + spec.kind);
                await until(() => state().documentationDocumentType === spec.kind && document.querySelector('#documentationRefreshRibbon') && idle(), timeout);
            }
            // Refresh is the workspace's public load path for a newly selected fixture.
            // Supervisor: the workspace's own load of the chosen document, before the Refresh below.
            const opened = performance.now();
            result = {workspaceMs: opened - start,
                workspaceLoaded: Boolean(drawn() && payload()?.document?.pages?.length === spec.pages)};
            click('#documentationRefreshRibbon');
            await until(() => requests.find(r => r.start >= opened && r.end && r.url.endsWith('/documentation-scene'))
                && drawn() && payload().document.pages.length === spec.pages, timeout);
            const first = payload().document.pages[0].pageId;
            if (state().partsManualDocumentationPageId !== first) click('.documentation-page-item[data-page-id="' + CSS.escape(first) + '"]');
            await until(() => drawn() && state().partsManualDocumentationPageId === first, timeout);
        } else if (spec.action === 'page') {
            click('.documentation-page-item[data-page-id="' + CSS.escape(spec.pageId) + '"]');
            await until(() => state().partsManualDocumentationPageId === spec.pageId && drawn(), timeout);
        } else if (spec.action === 'reload') {
            click('#documentationRefreshRibbon');
            await until(() => request('/documentation-scene') && drawn(), timeout);
        } else if (spec.action === 'save' || spec.action === 'done') {
            click('[data-rich-action="done"]');
            await until(() => !mounted() && drawn(), timeout);
            if (spec.action === 'save') await until(() => payload().revision !== before && /saved/i.test(status()), timeout);
            result = {saved: payload().revision !== before, before, after: payload().revision, status: status()};
        } else if (spec.action === 'undo' || spec.action === 'redo') {
            click(spec.action === 'undo' ? '#documentationUndoRibbon' : '#documentationRedoRibbon');
            await until(() => request('/documentation-scene/' + spec.action) && payload().revision !== before && drawn(), timeout);
            if (spec.expected) await until(() => surface().innerText.includes(spec.expected), timeout);
        } else if (spec.action === 'pdf') {
            if (!document.querySelector('#documentationPublishRibbon:not(:disabled)')) {
                // Supervisor: say why (the conditions _documentationSyncWorkflowRibbon reads).
                const pages = payload()?.document?.pages || [];
                throw Error('PDF control unavailable: ' + JSON.stringify({status: payload()?.document?.status,
                    figures: pages.filter(p => p.renderRequest).length,
                    notReady: pages.filter(p => p.renderRequest && p.renderRequest.image?.status !== 'ready').map(p => p.pageId).slice(0, 6),
                    workflowMode: Boolean(state().partsManualDocumentationWorkflowMode),
                    revealAll: state().partsManualDocumentationGeneration?.revealAll ?? null,
                    generation: state().partsManualDocumentationGeneration?.status ?? null}));
            }
            const completed = responseWhen(() => request('/pdf'), timeout);
            click('#documentationPublishRibbon');
            result = await completed;
            return {ms: result.end - start, response: result.result, status: result.status,
                requests: requests.filter(r => r.start >= start)};
        } else throw Error('Unknown P5a action');
        await frames();
        return {ms: performance.now() - start, ...(result || {}), requests: requests.filter(r => r.start >= start)};
    }
    const visible = element => {
        const s = getComputedStyle(element);
        return element.getClientRects().length && s.visibility !== 'hidden' && s.display !== 'none';
    };
    function name(element) {
        const labelled = (element.getAttribute('aria-labelledby') || '').split(/\s+/)
            .map(id => document.getElementById(id)?.textContent || '').join(' ').trim();
        const labels = [...(element.labels || [])].map(label => label.textContent).join(' ').trim();
        const text = element.matches('input,select,textarea') ? '' : element.textContent.trim();
        const value = element.getAttribute('aria-label') || labelled || labels || text;
        return {name: value || element.title || '', titleOnly: !value && !!element.title};
    }
    const rgba = value => (value.match(/[\d.]+/g) || []).map(Number);
    function audit() {
        const controls = [...document.querySelectorAll('#contextRibbon button, #contextRibbon input, #contextRibbon select, .documentation-rich-controls button, .documentation-rich-controls input, .documentation-rich-controls select')]
            .filter((e, i, all) => !e.disabled && visible(e) && all.indexOf(e) === i);
        const nodes = [...new Set([...controls, ...document.querySelectorAll('.documentation-status-message, [data-ribbon-dropdown] button, [data-ribbon-dropdown] .documentation-menu-heading, .documentation-rich-controls label, .documentation-symbol-picker legend, .documentation-table-menu strong, .documentation-table-menu button, .documentation-theme-dialog label')])].filter(visible);
        const colors = nodes.map(element => {
            const style = getComputedStyle(element); let ancestor = element, bg;
            while (ancestor) {
                const color = rgba(getComputedStyle(ancestor).backgroundColor);
                if (color.length >= 3 && (color[3] ?? 1) === 1) { bg = color; break; }
                ancestor = ancestor.parentElement;
            }
            const large = parseFloat(style.fontSize) >= 24 || parseFloat(style.fontSize) >= 18.66 && Number(style.fontWeight) >= 700;
            return {id: element.id, ...name(element), foreground: style.color, background: bg || null,
                fontSize: style.fontSize, fontWeight: style.fontWeight, minimum: large ? 3 : 4.5,
                ratio: bg ? contrast(rgba(style.color), bg) : null};
        });
        return {theme: document.documentElement.dataset.theme,
            names: controls.map(e => ({id: e.id, tag: e.tagName, ...name(e)})), colors,
            panels: [...document.querySelectorAll('[data-ribbon-dropdown], .documentation-theme-dialog, .documentation-symbol-picker, .documentation-table-menu, .documentation-type-dropdown, #contextRibbon [role="listbox"]')]
                .filter(visible).map(e => ({className: e.className, role: e.getAttribute('role'),
                    name: e.getAttribute('aria-label') || (e.getAttribute('aria-labelledby') || '').split(/\s+/)
                        .map(id => document.getElementById(id)?.textContent || '').join(' ').trim()})),
            live: {role: document.querySelector('.documentation-status-message')?.getAttribute('role'),
                polite: document.querySelector('.documentation-status-message')?.getAttribute('aria-live')}};
    }
    function clipping() {
        const controls = [...document.querySelectorAll('#contextRibbon button, #contextRibbon input, #contextRibbon select')].filter(visible);
        const failures = [];
        controls.forEach(element => {
            const r = element.getBoundingClientRect(), label = name(element).name;
            if (r.left < -.5 || r.right > innerWidth + .5 || r.top < -.5 || r.bottom > innerHeight + .5)
                failures.push({label, kind: 'viewport', rect: r.toJSON(), viewport: [innerWidth, innerHeight]});
            for (let parent = element.parentElement; parent; parent = parent.parentElement) {
                const style = getComputedStyle(parent), p = parent.getBoundingClientRect();
                if (/(hidden|clip|auto|scroll)/.test(style.overflowX) && (r.left < p.left - .5 || r.right > p.right + .5)
                    || /(hidden|clip|auto|scroll)/.test(style.overflowY) && (r.top < p.top - .5 || r.bottom > p.bottom + .5)) {
                    failures.push({label, kind: 'ancestor', rect: r.toJSON(), parent: parent.className, clip: p.toJSON()}); break;
                }
            }
        });
        for (let i = 0; i < controls.length; i++) for (let j = i + 1; j < controls.length; j++) {
            if (controls[i].contains(controls[j]) || controls[j].contains(controls[i])) continue;
            const a = controls[i].getBoundingClientRect(), b = controls[j].getBoundingClientRect();
            if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1)
                failures.push({kind: 'overlap', first: name(controls[i]).name, second: name(controls[j]).name, a: a.toJSON(), b: b.toJSON()});
        }
        return {count: controls.length, failures};
    }
    async function corners() {
        const stage = document.querySelector('.documentation-canvas-stage'), results = [];
        const preset = document.querySelector('#documentationZoomPreset');
        preset.value = '200'; preset.dispatchEvent(new Event('change', {bubbles: true})); await frames();
        for (const [x, y] of [[0, 0], [1, 0], [1, 1], [0, 1]]) {
            stage.scrollLeft = x ? stage.scrollWidth : 0; stage.scrollTop = y ? stage.scrollHeight : 0; await frames();
            const a = stage.getBoundingClientRect(), b = surface().getBoundingClientRect();
            const point = [x ? b.right - 1 : b.left + 1, y ? b.bottom - 1 : b.top + 1];
            results.push({corner: [x,y], point, stage: a.toJSON(), surface: b.toJSON(),
                visible: point[0] >= a.left && point[0] <= a.left + stage.clientWidth && point[1] >= a.top && point[1] <= a.top + stage.clientHeight});
        }
        preset.value = 'fit_page'; preset.dispatchEvent(new Event('change', {bubbles: true})); await frames();
        return results;
    }
    root.P5aProbe = {summary, contrast, run, arm, collect, typed, until, census, audit, clipping, corners, announcements, requests, payload,
        idle, drawn, mounted, status, editor};
})(globalThis);
