/* Model imports stay local to the composer until sent. The pure transitions and
 * payload builder share the same rules with the asynchronous queue and DOM view. */
(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProModelImportAttachments = api;
}(typeof window !== 'undefined' ? window : null, function () {
    'use strict';
    const MAX_CHIPS = 3;
    const MAX_UPLOADS = 2;
    const MAX_BYTES = 128 * 1024 * 1024;
    const IMPORT_ID = /^mi-[0-9a-f]{24}$/;
    const RETRY_DELAYS = [2000, 4000, 8000];
    const BLOCKING = ['waiting', 'uploading', 'checking'];

    function cleanName(value) {
        return String(value || 'model.glb').split(/[\\/]/).pop()
            .replace(/[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]/g, '').slice(0, 80) || 'model.glb';
    }

    function newChip(file, id) {
        const chip = { id: id, name: cleanName(file.name), size: Number(file.size) || 0,
            state: 'waiting', progress: 0, importId: null, reason: '', retries: 0,
            retryAt: 0, action: 'upload' };
        if (!/\.(glb|zip)$/i.test(file.name || '')) {
            chip.state = 'failed'; chip.reason = 'Download the glTF or GLB version (.glb or .zip).';
            chip.action = null;
        } else if (chip.size > MAX_BYTES) {
            chip.state = 'failed'; chip.reason = 'The model is larger than 128 MiB.'; chip.action = null;
        }
        return chip;
    }

    // No timers, files, requests or DOM state are read by this transition function.
    function transition(chip, event) {
        const next = Object.assign({}, chip);
        if (event.type === 'start') {
            next.state = chip.action === 'upload' ? 'uploading' : 'checking';
            next.reason = ''; next.retryAt = 0;
        } else if (event.type === 'progress' && chip.state === 'uploading') {
            next.progress = Math.max(0, Math.min(100, Math.round(Number(event.progress) || 0)));
        } else if (event.type === 'record') {
            const record = event.record || {};
            const importId = record.id || record.importId || chip.importId;
            if (!IMPORT_ID.test(importId || '') || !['queued', 'checking', 'ready', 'refused', 'failed'].includes(record.state)) {
                return transition(chip, { type: 'error', error: new Error('The model check returned an invalid record.') });
            }
            next.importId = importId; next.progress = 100; next.retries = 0;
            next.state = record.state === 'queued' ? 'checking' : record.state;
            const reason = record.refusal || record.failure || record.error || {};
            next.reason = String(typeof reason === 'string' ? reason : reason.message || record.message || '');
            next.action = next.state === 'failed' ? 'retry' : 'poll';
        } else if (event.type === 'error') {
            const error = event.error || {};
            next.reason = String(error.message || 'The model request failed.');
            if (Number(error.status) === 429) {
                next.state = chip.retries < RETRY_DELAYS.length ? 'waiting' : 'busy';
                next.retryAt = next.state === 'waiting' ? event.now + RETRY_DELAYS[chip.retries] : 0;
                next.retries = chip.retries + (next.state === 'waiting' ? 1 : 0);
            } else {
                next.state = 'failed';
            }
        } else if (event.type === 'retry' && ['failed', 'busy'].includes(chip.state) && chip.action) {
            next.state = 'waiting'; next.retries = 0; next.retryAt = 0; next.reason = '';
        }
        return next;
    }

    function buildPayload(chips, text, hasImage) {
        const attachments = chips.filter(function (chip) {
            return ['ready', 'refused'].includes(chip.state) && IMPORT_ID.test(chip.importId || '');
        }).slice(0, MAX_CHIPS).map(function (chip) {
            return { kind: 'model-import', importId: chip.importId };
        });
        const message = String(text || '').trim();
        const blocked = chips.some(function (chip) { return BLOCKING.includes(chip.state); });
        return { attachments: attachments, message: message,
            blocked: blocked, canSend: !blocked && !!(message || hasImage || attachments.length) };
    }

    function contextKey(context) {
        return context && context.enabled && context.conversationId && context.siteId && context.layoutId
            ? JSON.stringify([context.conversationId, context.siteId, context.layoutId]) : '';
    }

    // Requests already uploading are allowed to finish after remove/switch. Their
    // slots stay occupied until completion; stale responses can never revive chips.
    function createController(options) {
        options = options || {};
        const schedule = options.setTimeout || setTimeout;
        const cancel = options.clearTimeout || clearTimeout;
        const now = options.now || Date.now;
        const timers = new Map(), jobs = new Set(), slots = new Map(), files = new Map();
        let context = null, key = '', epoch = 0, sequence = 0, chips = [];
        const snapshot = function () { return { key: key, epoch: epoch, chips: chips.map(c => Object.assign({}, c)) }; };
        const notify = function () { if (options.onChange) options.onChange(snapshot()); };
        const find = function (id) { return chips.find(c => c.id === id); };
        function change(id, event) {
            chips = chips.map(c => c.id === id ? transition(c, event) : c);
            notify();
        }
        function clear() {
            epoch += 1; chips = []; files.clear();
            timers.forEach(cancel); timers.clear(); notify();
        }
        function later(id, delay) {
            if (timers.has(id)) cancel(timers.get(id));
            timers.set(id, schedule(function () { timers.delete(id); pump(); }, delay));
        }
        async function execute(chip) {
            const id = chip.id, capturedEpoch = epoch, capturedKey = key;
            const transport = context.transport, conversationId = context.conversationId;
            const uploadSlot = chip.action !== 'poll';
            const file = files.get(id);
            jobs.add(id);
            if (uploadSlot) slots.set(conversationId, (slots.get(conversationId) || 0) + 1);
            const live = () => epoch === capturedEpoch && key === capturedKey && !!find(id);
            change(id, { type: 'start' });
            try {
                let record;
                if (chip.action === 'upload') {
                    record = await transport.importModel(file, { onProgress: progress => {
                        if (live()) change(id, { type: 'progress', progress: progress });
                    } });
                } else if (chip.action === 'retry') {
                    record = await transport.retryModelImport(chip.importId);
                } else {
                    record = await transport.getModelImport(chip.importId);
                }
                if (live()) change(id, { type: 'record', record: record });
            } catch (error) {
                if (live()) change(id, { type: 'error', error: error, now: now() });
            } finally {
                jobs.delete(id);
                if (uploadSlot) slots.set(conversationId, Math.max(0, (slots.get(conversationId) || 0) - 1));
                if (live() && find(id).state === 'checking') later(id, options.pollDelay || 1000);
                pump();
            }
        }
        function pump() {
            if (!key) return;
            chips.slice().forEach(function (chip) {
                if (jobs.has(chip.id) || timers.has(chip.id)) return;
                if (!['waiting', 'checking'].includes(chip.state)) return;
                if (chip.retryAt > now()) { later(chip.id, chip.retryAt - now()); return; }
                if (chip.action !== 'poll' && (slots.get(context.conversationId) || 0) >= MAX_UPLOADS) return;
                void execute(chip);
            });
        }
        return {
            snapshot: snapshot,
            sync: function (next) {
                const nextKey = contextKey(next);
                context = next;
                if (nextKey !== key) { key = nextKey; clear(); }
            },
            clear: clear,
            add: function (input) {
                if (!key) return 0;
                const accepted = Array.from(input || []).slice(0, MAX_CHIPS - chips.length);
                accepted.forEach(function (file) {
                    const id = ++sequence;
                    files.set(id, file); chips.push(newChip(file, id));
                });
                notify(); pump(); return accepted.length;
            },
            remove: function (id) {
                chips = chips.filter(c => c.id !== id); files.delete(id);
                if (timers.has(id)) cancel(timers.get(id));
                timers.delete(id); notify(); pump();
            },
            retry: function (id) { change(id, { type: 'retry' }); pump(); },
            sent: function (captured) {
                if (!captured || captured.key !== key || captured.epoch !== epoch) return;
                const ids = new Set(captured.chips.map(c => c.id));
                chips = chips.filter(c => !ids.has(c.id));
                ids.forEach(id => { files.delete(id); if (timers.has(id)) cancel(timers.get(id)); timers.delete(id); });
                notify(); pump();
            },
        };
    }

    function chipLabel(chip) {
        if (chip.state === 'uploading') return 'Uploading ' + chip.progress + '%';
        if (chip.state === 'busy') return 'Busy - retry';
        if (chip.state === 'waiting') return chip.retryAt ? 'Waiting - retrying shortly' : 'Waiting';
        if (chip.state === 'refused') return 'Refused: ' + (chip.reason || 'This model is not supported.');
        if (chip.state === 'failed') return 'Failed: ' + (chip.reason || 'The check failed.');
        return chip.state === 'ready' ? 'Ready' : 'Checking';
    }

    // The view only displays text supplied by the pure state machine. Filenames
    // and server reasons are never inserted as markup or interpreted as links.
    function mount(options) {
        const document = options.document, panel = options.panel, button = options.button;
        const host = options.host, menu = options.menu, input = options.input, drop = options.drop;
        let currentContext = null, dragDepth = 0;
        const controller = createController({ onChange: function (state) {
            host.replaceChildren();
            state.chips.forEach(function (chip) {
                const row = document.createElement('div'); row.className = 'agent-model-chip';
                row.dataset.state = chip.state;
                const copy = document.createElement('span'); copy.className = 'agent-model-chip-copy';
                const name = document.createElement('strong'); name.textContent = chip.name;
                const status = document.createElement('span');
                status.textContent = (chip.size / (1024 * 1024)).toFixed(1) + ' MiB - ' + chipLabel(chip);
                copy.append(name, status); row.append(copy);
                if (chip.state === 'uploading') {
                    const progress = document.createElement('progress'); progress.max = 100; progress.value = chip.progress;
                    progress.setAttribute('aria-label', 'Uploading ' + chip.name); row.append(progress);
                }
                if (['busy', 'failed'].includes(chip.state) && chip.action) {
                    const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = 'Retry';
                    retry.addEventListener('click', function () { sync(); controller.retry(chip.id); }); row.append(retry);
                }
                const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'x';
                remove.setAttribute('aria-label', 'Remove ' + chip.name);
                remove.addEventListener('click', function () { controller.remove(chip.id); }); row.append(remove);
                host.append(row);
            });
            host.hidden = !state.chips.length;
            if (options.onChange) options.onChange();
        } });
        function close() { menu.hidden = true; button.setAttribute('aria-expanded', 'false'); }
        function sync() {
            currentContext = options.getContext();
            const enabled = !!contextKey(currentContext);
            button.hidden = !enabled;
            if (!enabled) { close(); drop.hidden = true; dragDepth = 0; }
            controller.sync(currentContext);
            return enabled;
        }
        function add(files) {
            if (!sync()) return;
            const count = controller.add(files);
            if (count < files.length && options.onNotice) options.onNotice('Attach up to 3 models per message.');
        }
        function isFiles(event) { return Array.from(event.dataTransfer && event.dataTransfer.types || []).includes('Files'); }
        button.setAttribute('aria-haspopup', 'menu'); button.setAttribute('aria-controls', menu.id);
        button.addEventListener('click', function (event) {
            event.preventDefault(); event.stopPropagation();
            if (!sync()) return;
            menu.hidden = !menu.hidden; button.setAttribute('aria-expanded', String(!menu.hidden));
            if (!menu.hidden) menu.querySelector('button').focus();
        });
        menu.querySelector('button').addEventListener('click', function () { close(); if (sync()) input.click(); });
        input.addEventListener('change', function () { add(input.files); input.value = ''; });
        document.addEventListener('click', function (event) { if (!menu.contains(event.target)) close(); });
        panel.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') { const wasOpen = !menu.hidden; close(); drop.hidden = true; dragDepth = 0; if (wasOpen) button.focus(); }
        });
        panel.addEventListener('dragenter', function (event) {
            if (!isFiles(event) || !sync()) return;
            event.preventDefault(); event.stopPropagation(); dragDepth += 1; drop.hidden = false;
        }, true);
        panel.addEventListener('dragover', function (event) {
            if (!isFiles(event) || !sync()) return;
            event.preventDefault(); event.stopPropagation(); event.dataTransfer.dropEffect = 'copy'; drop.hidden = false;
        }, true);
        panel.addEventListener('dragleave', function (event) {
            if (!isFiles(event)) return;
            dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) drop.hidden = true;
        }, true);
        panel.addEventListener('drop', function (event) {
            if (!isFiles(event) || !sync()) return;
            event.preventDefault(); event.stopPropagation(); dragDepth = 0; drop.hidden = true; add(event.dataTransfer.files);
        }, true);
        document.addEventListener('dragend', function () { dragDepth = 0; drop.hidden = true; });
        return Object.assign({}, controller, { sync: sync });
    }

    return { newChip: newChip, transition: transition, buildPayload: buildPayload,
        contextKey: contextKey, createController: createController, mount: mount };
}));
