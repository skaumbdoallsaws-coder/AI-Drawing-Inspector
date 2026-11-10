/* Server-owned documentation conflict review. No storage or editor pick mode. */
(function (root) {
    'use strict';
    const collections = ['conflicts', 'orphans', 'resolutionHistory', 'restoreTargets'];
    const canonical = value => JSON.stringify(value, (_, v) => v && typeof v === 'object' && !Array.isArray(v)
        ? Object.fromEntries(Object.keys(v).sort().map(k => [k, v[k]])) : v);
    const itemId = item => item.conflictId || item.orphanId;
    const textValue = (item, side) => {
        const payload = item[side]?.payload;
        const value = item.texts?.[side] ?? payload?.text ?? payload?.value;
        return value == null ? (payload == null ? '(unavailable)' : JSON.stringify(payload, null, 2)) : String(value);
    };
    const sorted = (items, pages = []) => {
        const order = new Map(pages.map((p, i) => [p.pageId, i]));
        return [...items].sort((a, b) => (order.get(a.pageId) ?? 1e9) - (order.get(b.pageId) ?? 1e9)
            || String(a.pageId || '').localeCompare(String(b.pageId || ''))
            || String(a.targetId || '').localeCompare(String(b.targetId || ''))
            || String(itemId(a)).localeCompare(String(itemId(b))));
    };
    const destinations = (item, targets) => targets.filter(t => t.owner === item.owner && t.kind === item.targetKind);
    const resolutionBody = (read, item, choice, extra = {}, requestId = root.crypto.randomUUID()) => {
        if (choice === 'merge_text' && !String(extra.mergedText || '').trim()) throw Error('Enter merged text before saving.');
        if (choice === 'restore' && !destinations(item, read.restoreTargets).some(t =>
            t.targetId === extra.targetId && t.contentHash === extra.expectedContentHash)) throw Error('Choose a current destination.');
        return { documentId: read.documentId, expectedRevision: item.revision, requestId,
            resolutions: [{ conflictId: itemId(item), expectedConflictHash: item.conflictHash, choice, ...extra }] };
    };
    const receiptText = result => {
        const receipts = [result.refreshReceipt, result.slotRefreshReceipt].filter(Boolean);
        if (!receipts.length) return '';
        return 'Refresh: ' + ['adopted', 'preserved', 'kept', 'conflicts', 'orphans'].map(key =>
            key + ' ' + receipts.reduce((n, r) => n + Number(r.counts?.[key] || 0), 0)).join(' | ');
    };
    const targetMatches = (item, pageId, alias, payload) => {
        const entry = payload?.document?.aliasMap?.[pageId]?.[alias];
        const stable = typeof entry === 'string' ? entry : entry?.targetId || alias;
        const ownerId = entry?.ownerId;
        return Boolean(item.targetId === stable || item.scopeId === stable || item.targetId === alias
            || (item.pageId === pageId && item.alias === alias)
            || (ownerId && (ownerId === item.scopeId || ownerId === item.targetId)));
    };
    const helpers = { canonical, sorted, destinations, resolutionBody, receiptText, targetMatches, textValue };
    if (typeof module !== 'undefined' && module.exports) module.exports = helpers;
    if (!root.document) return;
    const doc = root.document;
    const el = (tag, text, cls) => {
        const node = doc.createElement(tag);
        if (text != null) node.textContent = text;
        if (cls) node.className = cls;
        return node;
    };
    const button = (label, action) => {
        const node = el('button', label); node.type = 'button'; node.addEventListener('click', action); return node;
    };
    const style = el('style');
    style.textContent = `
        .documentation-conflict-tools { display:flex; gap:8px; align-items:center; }
        .documentation-conflict-tools button { font:inherit; white-space:nowrap; }
        /* While open, the pane takes the workspace's right column: the canvas stage (and the inspector column)
           reserve its width, so the page and its conflicted targets are never hidden under the pane. */
        #documentationWorkspace.documentation-review-open { --documentation-review-width:min(430px,40vw);
            --documentation-properties-width:calc(var(--documentation-review-width) + 16px); }
        #documentationWorkspace.documentation-review-open .documentation-properties { visibility:hidden; }
        #documentationConflictPane { position:absolute; z-index:40; right:0; top:var(--documentation-toolbar-height,44px);
            bottom:var(--documentation-status-height,34px); width:var(--documentation-review-width,min(430px,40vw));
            box-sizing:border-box;
            pointer-events:auto; /* #documentationWorkspace is click-through (pointer-events:none). */
            overflow:auto; background:#f8fafc; color:#172a3a; border:1px solid #a4b4c1; padding:16px; box-shadow:-4px 0 18px #0003; }
        #documentationConflictPane[hidden] { display:none; }
        .documentation-conflict-card { background:white; border:1px solid #bac8d1; border-radius:5px; padding:12px; margin:12px 0; }
        .documentation-conflict-card.selected { border:2px solid #a45e00; }
        .documentation-conflict-card pre, .documentation-review-dialog pre { white-space:pre-wrap; overflow-wrap:anywhere; max-height:180px; overflow:auto; font:12px/1.5 sans-serif; }
        .documentation-conflict-card textarea { box-sizing:border-box; width:100%; min-height:74px; color:#172a3a; background:white; }
        .documentation-conflict-card select { width:100%; margin:8px 0; }
        .documentation-conflict-actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; }
        .documentation-conflict-card button, .documentation-review-dialog button, #documentationConflictPane > button { padding:6px 9px; }
        .documentation-conflict-message { white-space:pre-wrap; color:#803f00; }
        .documentation-conflict-receipt { background:#e7f2ec; color:#193d2b; padding:10px; white-space:pre-wrap; }
        #documentationPageConflictMarkers { position:absolute; z-index:30; top:8px; right:8px; max-width:45%; background:#fff0d0; color:#713a00; }
        #documentationPageConflictMarkers button { display:block; font:10px/1.4 sans-serif; margin:3px; }
        [data-documentation-conflict] { outline:2px solid #b96500 !important; outline-offset:1px; }
        [data-documentation-conflict]::before { content:"Conflict"; display:inline-block; background:#fff0d0; color:#713a00;
            font:bold 9px/1.2 sans-serif; padding:2px 4px; margin-right:4px; }
        .documentation-review-dialog { width:min(540px,90vw); max-height:85vh; overflow:auto; color:#172a3a; background:#fff; border:1px solid #a4b4c1; border-radius:6px; padding:20px; }
        .documentation-review-dialog::backdrop { background:#0006; }
    `;
    doc.head.append(style);
    let host, key = '', data, pane, counter, observer, surface, serial = 0, loadedStamp = '', pending = false;
    let message = '', receipt = '', selected = '', retry = null, watched = false, polling = false, deferredLoad = false;
    let loadingStamp = null; // stamp of the load in flight: every page render syncs, so loads must be single-flight
    const drafts = new Map();
    const context = () => host?.context();
    const contextKey = c => c ? c.kind + '/' + c.number : '';
    const endpoint = c => '/api/documentation/' + c.kind + '/' + encodeURIComponent(c.number);
    const current = c => contextKey(context()) === contextKey(c);
    const stamp = c => canonical([c?.payload?.revision, c?.payload?.scene?.editRevision, c?.payload?.slotBinding]);
    async function request(url, body) {
        let response;
        try {
            response = await fetch(url, body ? { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) } : {});
        } catch (error) { error.transport = true; throw error; }
        let result;
        try { result = await response.json(); } catch (_) {
            const error = Error('The server response could not be read.'); error.transport = true; throw error;
        }
        if (!response.ok || result.success === false || result.ok === false) {
            const error = Error(result.message || result.detail?.message || result.error || 'Request refused.');
            error.code = result.error || result.code; error.details = result.details || result.detail || {}; throw error;
        }
        return result;
    }
    function exposure() { return data || context()?.payload || {}; }
    const openItems = values => (values || []).filter(item => !item.status || item.status === 'open');
    function mark() {
        if (!surface) return;
        const c = context();
        const pageId = c?.pageId;
        const conflicts = openItems(exposure().conflicts);
        const placed = new Set();
        for (const node of surface.querySelectorAll('[data-documentation-edit-target], [data-spec-slot], [data-documentation-object-id]')) {
            const alias = node.dataset.documentationEditTarget || node.dataset.documentationObjectId || 'slot:' + node.dataset.specSlot;
            const item = conflicts.find(v => targetMatches(v, pageId, alias, c?.payload));
            if (item) {
                placed.add(itemId(item));
                node.dataset.documentationConflict = itemId(item);
                node.title = 'Open conflict review';
            } else if (node.hasAttribute('data-documentation-conflict')) {
                delete node.dataset.documentationConflict;
                node.removeAttribute('title');
            }
        }
        const unmarked = conflicts.filter(item => item.pageId === pageId && !placed.has(itemId(item)));
        let markers = surface.querySelector('#documentationPageConflictMarkers');
        if (!unmarked.length) { markers?.remove(); return; }
        const signature = canonical(unmarked.map(item => [itemId(item), item.conflictHash]));
        if (markers?.dataset.signature === signature) return;
        if (!markers) { markers = el('div'); markers.id = 'documentationPageConflictMarkers'; surface.append(markers); }
        markers.dataset.signature = signature;
        markers.replaceChildren(...unmarked.map(item => button('Conflict: ' + (item.label || item.alias || item.targetId),
            () => { show(itemId(item)); void host.focus(item); })));
    }
    function counts() {
        const state = exposure();
        const open = Number(state.openConflictCount || 0);
        if (counter) counter.textContent = open + (open === 1 ? ' conflict' : ' conflicts')
            + ((state.orphanCount ?? state.orphans?.length ?? 0) ? ' | ' + (state.orphanCount ?? state.orphans.length) + ' unplaced' : '');
        mark();
    }
    async function load() {
        const c = context(); if (!c || !pane?.isConnected) return;
        const ticket = ++serial;
        loadingStamp = stamp(c);
        data = null; render(); counts();
        try {
            const combined = { conflicts:[], orphans:[], resolutionHistory:[], restoreTargets:[] };
            let first, start = 0;
            do {
                const page = await request(endpoint(c) + '/conflicts?from=' + start + '&limit=100');
                if (!first) first = page;
                if (page.revision !== first.revision || page.sceneEditRevision !== first.sceneEditRevision)
                    throw Error('The document changed during review. Reload the review.');
                for (const name of collections) combined[name].push(...(page[name] || []));
                start += 100;
            } while (start < Math.max(...Object.values(first.totals || {})));
            if (ticket !== serial || !current(c)) return;
            data = { ...first, ...combined }; loadedStamp = stamp(c);
            render(); counts();
        } catch (error) {
            if (ticket === serial && current(c)) { message = error.message; render(); }
        } finally {
            if (ticket === serial) loadingStamp = null;
        }
    }
    function setOpen(open) {
        if (!pane) return;
        pane.hidden = !open;
        doc.getElementById('documentationWorkspace')?.classList.toggle('documentation-review-open', open);
        // A page selection's floating toolbar would sit over the pane; review never edits the target.
        if (open) host?.clearSelection?.();
    }
    function show(id) {
        if (!pane) return;
        selected = id || selected; watched = true; setOpen(true); render(); void load();
    }
    async function resolve(item, choice, extra) {
        if (pending || !data) return;
        let body;
        try { body = resolutionBody(data, item, choice, extra); }
        catch (error) { message = error.message; render(); return; }
        const c = context();
        const execute = async () => {
            pending = true; retry = null; message = ''; render();
            try {
                await request(endpoint(c) + '/conflicts/resolve', body);
                if (!current(c)) return;
                data = null;
                await host.reload();
                message = 'Resolution saved. Undo is available.';
                await load();
            } catch (error) {
                if (!current(c)) return;
                if (error.transport) {
                    message = 'Connection interrupted. Retry sends the same request safely.';
                    retry = execute;
                } else {
                    message = error.message + ' Review the current values before trying again.';
                    try { await host.reload(); await load(); } catch (_) { /* Preserve the refusal message. */ }
                }
            } finally { pending = false; if (current(c)) render(); }
        };
        await execute();
    }
    function render() {
        if (!pane) return;
        pane.replaceChildren(el('h2', 'Review manual changes'), button('Close review', () => setOpen(false)), button('Reload review', () => { if (!pending) void load(); }));
        const notice = el('p', message, 'documentation-conflict-message'); notice.setAttribute('role', 'status'); pane.append(notice);
        if (retry) pane.append(button('Retry request', retry));
        if (receipt) { const node = el('p', receipt, 'documentation-conflict-receipt'); node.id = 'documentationRefreshReceipt'; pane.append(node); }
        if (!data) { pane.append(el('p', 'Loading review...')); return; }
        const pages = context()?.payload?.document?.pages || [];
        const add = (item, orphan) => {
            const card = el('section', null, 'documentation-conflict-card' + (selected === itemId(item) ? ' selected' : ''));
            card.dataset.conflictId = itemId(item); card.dataset.owner = item.owner;
            const page = pages.find(p => p.pageId === item.pageId);
            const title = (host.label?.(item) || item.label || item.alias || item.targetId) + ' - ' + (page?.title || item.pageId || 'Unplaced');
            card.append(button(title, async () => {
                selected = itemId(item); await host.focus(item); render();
            }));
            for (const [side, label] of orphan ? [['C','Current manual content']] : [['C','Current (C)'],['B','Prior baseline (B)'],['N','Proposed generated (N)']]) {
                card.append(el('h4', label));
                const text = el('pre', textValue(item, side)); text.dataset.conflictSide = side; card.append(text);
            }
            const evidence = item.evidenceChanges || {};
            card.append(el('h4','Evidence'));
            card.append(el('pre', canonical(evidence.before) === canonical(evidence.after) ? 'unchanged'
                : 'Old source refs: ' + canonical(evidence.before || {}) + '\nNew source refs: ' + canonical(evidence.after || {})));
            const actions = el('div', null, 'documentation-conflict-actions');
            if (orphan) {
                card.append(el('p', item.reason || 'The original target is unavailable.'));
                const select = el('select'); select.setAttribute('aria-label', 'Restore destination');
                const placeholder = el('option', 'Choose a destination...'); placeholder.value = ''; select.append(placeholder);
                for (const target of destinations(item, data.restoreTargets)) {
                    const option = el('option', (target.pageId || '') + ' - ' + (target.label || target.targetId) + ' (' + target.targetId + ')');
                    option.value = target.targetId; select.append(option);
                }
                card.append(select);
                actions.append(button('Detach', () => resolve(item, 'detach')));
                const restore = button('Restore', () => {
                    const target = destinations(item, data.restoreTargets).find(t => t.targetId === select.value);
                    if (target) void resolve(item, 'restore', {targetId:target.targetId, expectedContentHash:target.contentHash});
                });
                restore.disabled = true;
                select.addEventListener('change', () => { restore.disabled = pending || !select.value; });
                actions.append(restore);
            } else {
                actions.append(button('Keep mine', () => resolve(item, 'keep_manual')), button('Use generated', () => resolve(item, 'use_generated')));
                const input = el('textarea'); input.setAttribute('aria-label', 'Merged text'); input.maxLength = 2000;
                input.value = drafts.get(itemId(item)) ?? textValue(item, 'C');
                input.addEventListener('input', () => { drafts.set(itemId(item), input.value); merge.disabled = pending || !input.value.trim(); });
                card.append(input);
                const merge = button('Merge', () => resolve(item, 'merge_text', {mergedText:input.value}));
                merge.disabled = !input.value.trim(); actions.append(merge);
            }
            card.append(actions);
            if (pending) card.querySelectorAll('button,textarea,select').forEach(n => { n.disabled = true; });
            pane.append(card);
        };
        const conflicts = openItems(data.conflicts);
        if (!conflicts.length) pane.append(el('p', 'No open conflicts.'));
        sorted(conflicts, pages).forEach(item => add(item, false));
        pane.append(el('h3', 'Unplaced manual content'));
        if (!data.orphans.length) pane.append(el('p','No unplaced manual content.'));
        sorted(data.orphans, pages).forEach(item => add(item, true));
    }
    function sync(nextHost) {
        host = nextHost;
        const c = context(), nextKey = contextKey(c);
        if (nextKey !== key) {
            key = nextKey; data = null; loadedStamp = ''; message = ''; receipt = ''; selected = ''; retry = null;
            drafts.clear(); watched = false; ++serial; setOpen(false);
        }
        const workspace = doc.getElementById('documentationWorkspace');
        if (!workspace) return;
        if (!pane?.isConnected) {
            pane = el('aside'); pane.id = 'documentationConflictPane'; pane.hidden = true; pane.setAttribute('aria-label','Review manual changes');
            workspace.append(pane);
            const tools = el('div', null, 'documentation-conflict-tools');
            counter = button('0 conflicts', () => show()); counter.id = 'documentationConflictCount';
            const reset = button('Reset to generated...', () => preview('reset')); reset.id = 'documentationResetGenerated';
            tools.append(counter, reset); workspace.querySelector('.documentation-status-center')?.append(tools);
        }
        let stale = workspace.querySelector('#documentationSourceChanged');
        if (c?.kind === 'illustrated_parts_manual' && c.sourceCurrent === false) {
            if (!stale) {
                stale = el('div', 'Source revision changed ', 'documentation-conflict-receipt');
                stale.id = 'documentationSourceChanged';
                const refresh = button('Refresh from source', () => host.refreshSource());
                stale.append(refresh);
                workspace.querySelector('.documentation-status-center')?.append(stale);
            }
        } else stale?.remove();
        const nextSurface = doc.getElementById('documentationPublicationSurface');
        if (surface !== nextSurface) {
            observer?.disconnect(); surface = nextSurface;
            observer = new MutationObserver(mark); if (surface) observer.observe(surface, {childList:true,subtree:true});
            surface?.addEventListener('dblclick', event => {
                const target = event.target.closest('[data-documentation-conflict]');
                if (target) { event.preventDefault(); event.stopImmediatePropagation(); show(target.dataset.documentationConflict); }
            }, true);
        }
        if (data && stamp(c) !== loadedStamp) data = null;
        counts();
        if ((watched || !pane.hidden) && !pending && !data && loadingStamp !== stamp(c)) {
            // A poll in flight would see the cleared data and stop without loading; it loads on finishing.
            if (polling) deferredLoad = true; else void load();
        }
    }
    function blockEdit(pageId, alias) {
        const item = openItems(exposure().conflicts).find(v => targetMatches(v, pageId, alias, context()?.payload));
        if (!item) return false;
        show(itemId(item)); return true;
    }
    function refreshed(result) {
        receipt = receiptText(result);
        counts();
        if (receipt || Number(result.openConflictCount || 0) > 0) { show(); render(); }
    }
    async function preview(mode, overrideHost) {
        const activeHost = overrideHost || host;
        const c = activeHost.context();
        const dialog = el('dialog', null, 'documentation-review-dialog');
        dialog.id = mode === 'reset' ? 'documentationResetDialog' : 'documentationRefreshDialog';
        dialog.append(el('h2', mode === 'reset' ? 'Reset to generated' : 'Refresh from source'));
        const detail = el('pre', 'Loading preview...'), errorText = el('p', '', 'documentation-conflict-message');
        const actions = el('div', null, 'documentation-conflict-actions');
        const cancel = button('Cancel', () => dialog.close()); actions.append(cancel); dialog.append(detail, errorText, actions);
        dialog.addEventListener('close', () => dialog.remove()); doc.body.append(dialog); dialog.showModal();
        const url = mode === 'reset' ? endpoint(c) + '/reset' : '/api/parts-manual/' + encodeURIComponent(c.number) + '/documentation-scene/refresh';
        try {
            const value = await request(url);
            if (!dialog.isConnected) return;
            let body;
            if (mode === 'reset') {
                const ids = [...(value.affectedIds || []), ...(value.slots?.affectedIds || [])];
                detail.textContent = ids.length + ' affected targets. A recoverable copy is kept.\n\n'
                    + ids.slice(0,20).join('\n') + (ids.length > 20 ? '\n... and ' + (ids.length - 20) + ' more' : '');
                body = {expectedRevision:value.expectedRevision,previewHash:value.previewHash};
                if (value.slots) body.slots = {expectedRevision:value.slots.expectedRevision,previewHash:value.slots.previewHash};
            } else {
                detail.textContent = 'From binding:\n' + JSON.stringify(value.fromBinding,null,2)
                    + '\nTo binding:\n' + JSON.stringify(value.toBinding,null,2)
                    + '\nApproved plan: ' + (value.planCarried ? 'carries to the new source.' : 'already current.');
                body = {expectedRevision:value.expectedRevision,expectedPlanRevision:value.expectedPlanRevision};
            }
            const execute = button(mode === 'reset' ? 'Reset now' : 'Refresh now', async () => {
                execute.disabled = true; cancel.disabled = true;
                try {
                    const result = await request(url, body);
                    dialog.close();
                    await activeHost.reload();
                    if (mode === 'refresh') refreshed(result);
                    else { message = 'Reset complete. A recoverable copy was kept.'; show(); }
                } catch (error) {
                    // Reset and refresh lack request IDs. Always preview again after any failure.
                    errorText.textContent = error.message + ' Close this dialog and preview again.';
                    cancel.disabled = false;
                }
            });
            actions.append(execute);
        } catch (error) {
            detail.textContent = '';
            const missing = error.details?.missingOccurrences;
            errorText.textContent = error.message + (missing ? ' Missing occurrences: ' + missing.length + '.' : '');
        }
    }
    // A named undo can arrive through Sage rather than a workspace button.
    // Observe only an actively reviewed workspace (pane open), and never interrupt inline editing.
    // Each poll recompiles the document on the server, so a closed pane never polls.
    root.setInterval?.(async () => {
        if (!watched || polling || pending || !data || !pane?.isConnected || pane.hidden || doc.hidden
            || doc.querySelector('#documentationWorkspace.busy')
            || surface?.querySelector('[contenteditable="true"]')) return;
        const c = context(), previous = data;
        polling = true;
        try {
            const latest = await request(endpoint(c) + '/conflicts?limit=1');
            if (!current(c) || data !== previous || pending) return;
            if (latest.revision !== previous.revision || latest.sceneEditRevision !== previous.sceneEditRevision) {
                await host.reload();
                await load();
            }
        } catch (_) { /* Explicit reload and resolution surface actionable failures. */ }
        finally {
            polling = false;
            if (deferredLoad) {
                deferredLoad = false;
                if (!data && !pending && pane?.isConnected && (watched || !pane.hidden)) void load();
            }
        }
    }, 5000);
    root.DocumentationConflicts = {sync, show, blockEdit, refreshed, preview, ...helpers};
})(typeof window !== 'undefined' ? window : globalThis);
