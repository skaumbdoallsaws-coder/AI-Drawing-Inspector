(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilitySheets = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    const clone = value => JSON.parse(JSON.stringify(value));

    function blankLayout(source, layoutId, displayName) {
        if (!source || source.schemaVersion !== 1 || !/^fl-[A-Za-z0-9._-]{1,128}$/.test(layoutId)) {
            throw new Error('A supported facility layout is required.');
        }
        const name = String(displayName || '').trim();
        if (!name || name.length > 120) throw new Error('Enter a layout name of 1 to 120 characters.');
        const result = {
            schemaVersion: 1, layoutId, displayName: name, status: 'draft',
            createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(),
            zones: [], placements: [], routes: [], floorMarkings: [],
            utilityNetworks: [], processBindings: [], dismissedSuggestions: [], extensions: {},
        };
        // Share the authored site frame and policy, never the source's contents,
        // process bindings, generated provenance, navigation or cell identities.
        for (const key of ['association', 'coordinateFrame', 'sourceShellRef', 'policySetRef']) {
            if (!source[key]) throw new Error('Missing facility reference: ' + key);
            result[key] = clone(source[key]);
        }
        if (source.extensions?.facilityPlan) result.extensions.facilityPlan = clone(source.extensions.facilityPlan);
        return result;
    }

    function canonical(value) {
        if (Array.isArray(value)) return value.map(canonical);
        if (value && typeof value === 'object') return Object.fromEntries(
            Object.keys(value).sort().map(key => [key, canonical(value[key])]));
        return value;
    }
    function sameCreatedLayout(actual, expected) {
        const comparable = value => {
            const copy = clone(value);
            delete copy.createdAt; delete copy.updatedAt;
            return JSON.stringify(canonical(copy));
        };
        return comparable(actual) === comparable(expected);
    }

    function createSheets(options) {
        const apps = new Map();
        const summaries = new Map();
        const pendingCreations = new Map();
        const subscriptions = new Map();
        const pendingDeletions = new Map();
        let rows = [], activeId = '', busy = false;
        const changed = () => options.onChange?.();
        const state = () => {
            const merged = new Map(rows.map(row => [row.layoutId, row]));
            for (const [id, summary] of summaries) merged.set(id, { ...merged.get(id), ...summary });
            // The site registry is an inventory, not this window's open sheets.
            return { activeId, busy, pendingDeletions: Array.from(pendingDeletions.keys()), layouts: Array.from(summaries.values()),
                availableLayouts: Array.from(merged.values()) };
        };
        const register = app => {
            const id = app.session.getState().layout.layoutId;
            const update = current => {
                const summary = { layoutId: id, displayName: current.layout.displayName, dirty: current.dirty,
                    draftRevision: current.draftRevision };
                if (JSON.stringify(summaries.get(id)) === JSON.stringify(summary)) return;
                summaries.set(id, summary);
                changed();
            };
            if (!apps.has(id)) subscriptions.set(id, app.session.subscribe(update));
            apps.set(id, app);
            if (!rows.some(row => row.layoutId === id)) rows.push({ layoutId: id });
            activeId = id;
            update(app.session.getState());
            changed();
        };
        async function refresh() {
            const result = await options.transport.listLayouts();
            rows = result.layouts.filter(row => row.status !== 'archived');
            changed();
        }
        async function run(action, deletingSession) {
            if (busy) return false;
            options.assertSwitchable?.({ deletingSession });
            busy = true; changed();
            try { await action(); return true; }
            finally { busy = false; changed(); }
        }
        async function install(id, receipt, deletingSession) {
            const previous = apps.get(activeId);
            const next = await options.activate({ previous, retained: apps.get(id), receipt, layoutId: id, deletingSession });
            register(next);
        }
        function editable(id, expectedRevision) {
            if (!options.canCreate()) throw new Error('Layout editing is not enabled.');
            const app = apps.get(id);
            if (!app) throw new Error('Open the layout before editing its sheet.');
            const s = app.session.getState();
            if (s.draftRevision !== expectedRevision) throw new Error('The layout changed. Review it before continuing.');
            if (s.busy || s.designAuthorityState !== 'ready' || s.generatedDraft || s.designProposalDraft) {
                throw new Error('Finish the current operation and save or undo the pending proposal first.');
            }
            options.assertEditable?.(app);
            return app;
        }
        async function remove(id, expectedRevision) {
            const pending = pendingDeletions.get(id);
            return run(async () => {
                if (!options.canCreate()) throw new Error('Layout editing is not enabled.');
                const fallback = Array.from(apps.keys()).find(key => key !== id && !pendingDeletions.has(key));
                if (!fallback) throw new Error('Keep at least one layout sheet open.');
                const app = apps.get(id);
                if (!app) throw new Error('This layout sheet is no longer open.');
                let transaction = pending;
                if (!transaction) {
                    editable(id, expectedRevision);
                    const s = app.session.getState();
                    transaction = { base: s.baseLayout, revision: s.baseRevision,
                        release: app.session.beginSheetDeletion(expectedRevision), archived: false };
                    pendingDeletions.set(id, transaction);
                }
                if (!transaction.archived) {
                    try {
                        const receipt = await options.transport.archiveLayout(id, transaction.revision);
                        if (receipt.layout?.layoutId !== id || receipt.layout.status !== 'archived') {
                            throw new Error('The deletion receipt did not identify the archived layout.');
                        }
                        transaction.archived = true;
                    } catch (error) {
                        const current = await options.transport.getLayout(id).catch(() => null);
                        const expected = { ...transaction.base, status: 'archived' };
                        if (current && sameCreatedLayout(current.layout, expected)) transaction.archived = true;
                        else if (error.status >= 400 && error.status < 500) {
                            pendingDeletions.delete(id); transaction.release(); throw error;
                        } else {
                            throw new Error('Could not confirm deletion. Retry Delete layout to reconcile; this sheet is locked.');
                        }
                    }
                }
                // Keep the recovery handle if the replacement view fails to mount.
                if (activeId === id) await install(fallback, null, app.session);
                subscriptions.get(id)?.(); subscriptions.delete(id);
                apps.delete(id); summaries.delete(id); pendingCreations.delete(id);
                rows = rows.filter(row => row.layoutId !== id);
                pendingDeletions.delete(id);
                transaction.release(); app.destroy?.();
                changed();
            }, pending ? apps.get(id)?.session : undefined);
        }
        return {
            register, refresh, state,
            remove,
            rename: (id, name, expectedRevision) => run(async () => {
                const app = editable(id, expectedRevision);
                await app.session.renameLayout(name);
            }),
            apps: () => Array.from(apps.values()),
            activate: id => id === activeId ? Promise.resolve(false) : run(async () => {
                const receipt = apps.has(id) ? null : await options.transport.getLayout(id);
                // Fetching may take time; recheck before any UI or session change.
                options.assertSwitchable?.();
                await install(id, receipt);
            }),
            addBlank: () => run(async () => {
                if (!options.canCreate()) throw new Error('Layout creation is not enabled.');
                const sourceId = activeId;
                let pendingCreation = pendingCreations.get(sourceId);
                if (!pendingCreation) {
                    const names = new Set(state().availableLayouts.map(row => row.displayName.toLowerCase()));
                    let number = 1;
                    while (names.has('layout ' + number)) number++;
                    const source = apps.get(activeId).session.getState().baseLayout;
                    pendingCreation = blankLayout(source, options.newId(), 'Layout ' + number);
                    pendingCreations.set(sourceId, pendingCreation);
                }
                let receipt;
                try { receipt = await options.transport.createLayout(pendingCreation); }
                catch (error) {
                    // A lost POST reply is retried with the same layout identity.
                    // Only an exact blank document can stand in for that receipt.
                    const existing = await options.transport.getLayout(pendingCreation.layoutId).catch(() => null);
                    if (!existing || !sameCreatedLayout(existing.layout, pendingCreation)) throw error;
                    receipt = existing;
                }
                rows.push({ layoutId: receipt.layout.layoutId, displayName: receipt.layout.displayName, status: 'draft' });
                pendingCreations.delete(sourceId);
                options.assertSwitchable?.();
                await install(receipt.layout.layoutId, receipt);
            }),
            observation: () => {
                const documents = Array.from(apps.values()).map(app => {
                    const s = app.session.getState();
                    return { layoutId: s.layout.layoutId, dirty: s.dirty, busy: s.busy,
                        pending: s.designAuthorityState !== 'ready', draft: s.draftRevision,
                        history: s.commandJournalHash, proposal: s.designProposalDraft };
                });
                return { dirty: documents.some(s => s.dirty), busy: busy || documents.some(s => s.busy),
                    pending: pendingDeletions.size > 0 || documents.some(s => s.pending), documents };
            },
        };
    }
    function savedLayoutOptions(layouts) {
        const rows = layouts.filter(row => row && row.status !== 'archived');
        const counts = new Map();
        for (const row of rows) counts.set(row.displayName, (counts.get(row.displayName) || 0) + 1);
        return rows.map(row => ({ layoutId: row.layoutId,
            label: row.displayName + (counts.get(row.displayName) > 1 ? ' (' + row.layoutId + ')' : ''),
        })).sort((a, b) => a.label.localeCompare(b.label) || a.layoutId.localeCompare(b.layoutId));
    }
    function sheetDialog(host, layout, mode, submit, layouts = []) {
        const doc = host.ownerDocument;
        if (doc.querySelector('.ip-layout-sheet-dialog')) return;
        const dialog = doc.createElement('dialog');
        dialog.className = 'ip-layout-sheet-dialog';
        const titles = { rename: 'Rename layout', delete: 'Delete layout', open: 'Open layout' };
        dialog.setAttribute('aria-label', titles[mode]);
        const form = doc.createElement('form');
        const title = doc.createElement('h3');
        title.textContent = mode === 'delete' ? 'Delete layout sheet?' : titles[mode];
        form.appendChild(title);
        let input;
        if (mode === 'open') {
            const label = doc.createElement('label');
            label.textContent = 'Saved layout';
            input = doc.createElement('select'); input.required = true;
            input.setAttribute('data-open-layout-choice', 'true');
            const placeholder = doc.createElement('option');
            placeholder.value = ''; placeholder.textContent = 'Select a layout';
            placeholder.disabled = true; placeholder.selected = true; input.appendChild(placeholder);
            for (const row of savedLayoutOptions(layouts)) {
                const option = doc.createElement('option');
                option.value = row.layoutId; option.textContent = row.label; input.appendChild(option);
            }
            label.appendChild(input); form.appendChild(label);
        } else if (mode === 'rename') {
            const label = doc.createElement('label');
            label.textContent = 'Layout name';
            input = doc.createElement('input');
            input.type = 'text'; input.value = layout.displayName;
            input.maxLength = 120; input.required = true;
            label.appendChild(input); form.appendChild(label);
        } else {
            const message = doc.createElement('p');
            message.textContent = 'Delete "' + layout.displayName + '"? The saved layout will be archived and removed from the layout list. This cannot be undone here.'
                + (layout.dirty ? ' Unsaved changes to this sheet will be discarded.' : '');
            form.appendChild(message);
        }
        const actions = doc.createElement('div');
        actions.className = 'ip-layout-sheet-dialog-actions';
        const cancel = doc.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Cancel';
        const confirm = doc.createElement('button'); confirm.type = 'submit';
        confirm.textContent = mode === 'open' ? 'Open' : mode === 'rename' ? 'Rename' : 'Delete';
        actions.append(cancel, confirm); form.appendChild(actions); dialog.appendChild(form);
        const finish = () => { dialog.close(); dialog.remove();
            Array.from(host.querySelectorAll('[data-layout-id]')).find(tab => tab.dataset.layoutId === (layout?.layoutId || host.dataset.activeLayout))?.focus(); };
        cancel.addEventListener('click', finish);
        dialog.addEventListener('cancel', event => { event.preventDefault(); finish(); });
        form.addEventListener('submit', event => {
            event.preventDefault();
            if (input && !input.value.trim()) { input.setCustomValidity(mode === 'open' ? 'Select a layout.' : 'Enter a layout name.'); input.reportValidity(); return; }
            const name = input?.value.trim(); finish(); submit(name);
        });
        input?.addEventListener('input', () => input.setCustomValidity(''));
        doc.body.appendChild(dialog); dialog.showModal();
        if (input) { input.focus(); if (mode === 'rename') input.select(); } else cancel.focus();
    }
    function renderStrip(host, state, options) {
        const doc = host.ownerDocument;
        const activeChanged = host.dataset.activeLayout !== state.activeId;
        host.dataset.activeLayout = state.activeId;
        // Reuse keyed tab nodes so the first click of a double-click can switch
        // sheets without removing the target of the second click.
        let tabs = host.querySelector('.ip-layout-sheet-tabs');
        if (!tabs) {
            tabs = doc.createElement('div'); tabs.className = 'ip-layout-sheet-tabs';
            tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Facility layouts');
            host.appendChild(tabs);
        }
        const pending = state.pendingDeletions || [];
        const rename = layout => {
            if (state.busy || !options.canCreate || pending.includes(layout.layoutId)) return;
            sheetDialog(host, layout, 'rename', name => options.rename(layout.layoutId, name, layout.draftRevision));
        };
        const remove = layout => {
            if (state.busy || !options.canCreate || state.layouts.length < 2) return;
            if (pending.includes(layout.layoutId)) options.remove(layout.layoutId, layout.draftRevision);
            else sheetDialog(host, layout, 'delete', () => options.remove(layout.layoutId, layout.draftRevision));
        };
        for (const tab of Array.from(tabs.children)) {
            if (!state.layouts.some(row => row.layoutId === tab.dataset.layoutId)) tab.remove();
        }
        for (const layout of state.layouts) {
            let tab = Array.from(tabs.children).find(item => item.dataset.layoutId === layout.layoutId);
            if (!tab) {
                tab = doc.createElement('button'); tab.type = 'button'; tab.className = 'ip-layout-sheet-tab';
                tab.dataset.layoutId = layout.layoutId; tab.setAttribute('role', 'tab');
                const icon = doc.createElement('img');
                icon.src = '/static/assets/facility-tree-icons/facility-layout.svg';
                icon.alt = ''; icon.width = 18; icon.height = 18; icon.draggable = false;
                tab.append(icon, doc.createElement('span')); tabs.appendChild(tab);
            }
            tab.setAttribute('aria-selected', String(layout.layoutId === state.activeId));
            tab.tabIndex = layout.layoutId === state.activeId ? 0 : -1;
            tab.disabled = state.busy;
            tab.title = layout.displayName + (layout.dirty ? ' (unsaved)' : '') + ' - Double-click to rename';
            tab.lastElementChild.textContent = layout.displayName + (layout.dirty ? ' *' : '');
            tab.onclick = () => options.activate(layout.layoutId);
            tab.ondblclick = () => rename(layout);
            tab.onkeydown = event => {
                if (event.key === 'F2') { event.preventDefault(); event.stopPropagation(); rename(layout); return; }
                if (event.key === 'Delete') { event.preventDefault(); event.stopPropagation(); remove(layout); return; }
                const items = Array.from(tabs.children);
                let index = items.indexOf(tab);
                if (event.key === 'ArrowRight') index = (index + 1) % items.length;
                else if (event.key === 'ArrowLeft') index = (index + items.length - 1) % items.length;
                else if (event.key === 'Home') index = 0;
                else if (event.key === 'End') index = items.length - 1;
                else return;
                event.preventDefault(); event.stopPropagation(); items[index].focus();
            };
        }
        function control(className, title, callback) {
            let button = host.querySelector('.' + className);
            if (!button) { button = doc.createElement('button'); button.type = 'button'; button.className = className; host.appendChild(button); }
            button.title = title; button.setAttribute('aria-label', title); button.onclick = callback;
            button.disabled = state.busy || !options.canCreate;
            return button;
        }
        const add = control('ip-layout-sheet-add', 'Add blank layout', options.add); add.textContent = '+';
        const active = state.layouts.find(row => row.layoutId === state.activeId);
        const deleting = pending.includes(state.activeId);
        const trash = control('ip-layout-sheet-delete', deleting ? 'Retry Delete layout' : 'Delete layout', () => active && remove(active));
        trash.disabled ||= state.layouts.length < 2;
        if (!trash.firstChild) {
            const icon = doc.createElement('span'); icon.className = 'ip-layout-sheet-delete-icon';
            icon.setAttribute('aria-hidden', 'true'); trash.appendChild(icon);
        }
        if (activeChanged) Array.from(tabs.children).find(tab => tab.dataset.layoutId === state.activeId)
            ?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
    return Object.freeze({ blankLayout, sameCreatedLayout, createSheets, renderStrip, savedLayoutOptions,
        openLayoutDialog: (host, layouts, submit) => sheetDialog(host, null, 'open', submit, layouts) });
}));
