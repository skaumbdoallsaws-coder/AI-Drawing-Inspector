/* Literal document search. All public positions are Unicode code points. */
(function (root) {
    'use strict';
    // The only UTF-16 adapter used by the find UI. Never slice source text with a code-point offset.
    const points = text => {
        const chars = Array.from(text);
        return { chars, length: chars.length, slice: (a, b) => chars.slice(a, b).join(''),
            toUTF16: offset => chars.slice(0, offset).join('').length,
            fromUTF16: offset => {
                let units = 0, count = 0;
                for (const char of chars) {
                    if (units === offset) return count;
                    units += char.length; count++;
                    if (units > offset) throw Error('Position splits a Unicode code point.');
                }
                if (units === offset) return count;
                throw Error('Position is outside the text.');
            } };
    };
    const hangul = n => (n >= 0x1100 && n <= 0x115f || n >= 0xa960 && n <= 0xa97c) ? 'L'
        : (n >= 0x1160 && n <= 0x11a7 || n >= 0xd7b0 && n <= 0xd7c6) ? 'V'
        : (n >= 0x11a8 && n <= 0x11ff || n >= 0xd7cb && n <= 0xd7fb) ? 'T'
        : n >= 0xac00 && n <= 0xd7a3 ? ((n - 0xac00) % 28 ? 'LVT' : 'LV') : '';
    // Mirrors search.boundary's documented UAX #29 subset, including its GB9c limitation and both tables.
    const EXTEND_OTHER = [0x200c, 0x0e33, 0x0eb3, 0xff9e, 0xff9f];
    const PREPEND = [[0x0600, 0x0605], [0x06dd, 0x06dd], [0x070f, 0x070f], [0x0890, 0x0891], [0x08e2, 0x08e2],
        [0x0d4e, 0x0d4e], [0x110bd, 0x110bd], [0x110cd, 0x110cd], [0x111c2, 0x111c3], [0x113d1, 0x113d1],
        [0x1193f, 0x1193f], [0x11941, 0x11941], [0x11a3a, 0x11a3a], [0x11a84, 0x11a89], [0x11d46, 0x11d46],
        [0x11f02, 0x11f02]];
    function boundary(chars, offset) {
        if (!Number.isInteger(offset) || offset < 0 || offset > chars.length) return false;
        if (offset === 0 || offset === chars.length) return true;
        const a = chars[offset - 1].codePointAt(0), b = chars[offset].codePointAt(0);
        if (/\p{M}/u.test(chars[offset]) || EXTEND_OTHER.includes(b) || b >= 0xfe00 && b <= 0xfe0f || b >= 0xe0100 && b <= 0xe01ef
            || b >= 0x1f3fb && b <= 0x1f3ff || b >= 0xe0020 && b <= 0xe007f
            || a === 0x200d || b === 0x200d || a === 13 && b === 10) return false;
        if (PREPEND.some(([low, high]) => a >= low && a <= high)) return false;
        const x = hangul(a), y = hangul(b);
        if (x === 'L' && ['L', 'V', 'LV', 'LVT'].includes(y) || ['LV', 'V'].includes(x) && ['V', 'T'].includes(y)
            || ['LVT', 'T'].includes(x) && y === 'T') return false;
        if (b >= 0x1f1e6 && b <= 0x1f1ff) {
            let count = 0;
            for (let i = offset - 1; i >= 0; i--) {
                const n = chars[i].codePointAt(0);
                if (n < 0x1f1e6 || n > 0x1f1ff) break;
                count++;
            }
            if (count % 2) return false;
        }
        return true;
    }
    function snippet(text, start, end) {
        const p = points(text);
        let a = Math.max(0, start - 40), b = Math.min(p.length, end + 40);
        while (a < start && !boundary(p.chars, a)) a++;
        while (b > end && !boundary(p.chars, b)) b--;
        return { before: p.slice(a, start), match: p.slice(start, end), after: p.slice(end, b) };
    }
    function groups(matches) {
        // Descending offsets keep pending pre-images intact when a target spans groups.
        const targets = new Map();
        for (const match of matches.filter(item => item.editable)) {
            if (!targets.has(match.targetId)) targets.set(match.targetId, []);
            targets.get(match.targetId).push(match);
        }
        const ordered = [...targets.values()].flatMap(items => [...items].sort((a, b) => b.start - a.start));
        const result = [];
        for (let i = 0; i < ordered.length; i += 100) result.push(ordered.slice(i, i + 100));
        return result;
    }
    function preview(matches) {
        const reasons = {};
        for (const item of matches.filter(item => !item.editable)) reasons[item.reason || 'read_only_derived_field'] =
            (reasons[item.reason || 'read_only_derived_field'] || 0) + 1;
        return { total: matches.length, replaceable: matches.filter(item => item.editable).length,
            readOnly: matches.filter(item => !item.editable).length, reasons, groups: groups(matches).length };
    }
    const operation = (match, text) => ({ operation: 'replace_range', targetId: match.targetId,
        expectedContentHash: match.contentHash, start: match.start, end: match.end, expectedText: match.match, text });
    // The panel lists at most this many matches (five reads of 200). Replace all needs the complete set.
    const SHOWN = 1000;
    const REASONS = { read_only_derived_field: 'typed, locked or derived value', manual_edit_conflict: 'open conflict' };
    const reason = code => REASONS[code] || code || REASONS.read_only_derived_field;
    const helpers = { points, boundary, snippet, groups, preview, operation, reason, SHOWN };
    if (typeof module !== 'undefined' && module.exports) module.exports = helpers;
    if (!root.document) return;
    const doc = root.document;
    let active = null, owner = null;
    function open(host) {
        if (active) { active.remove(); active = null; }
        const identity = host.context(); owner = { kind: identity.kind, number: identity.number };
        const panel = doc.createElement('section'); panel.className = 'documentation-find-panel';
        panel.setAttribute('aria-label', 'Find and Replace'); panel.tabIndex = -1;
        const el = (tag, text, parent = panel) => {
            const node = doc.createElement(tag); if (text != null) node.textContent = text;
            parent.appendChild(node); return node;
        };
        const field = (name, type = 'text') => {
            const label = el('label', name + ' '), input = el('input', null, label);
            input.type = type; input.setAttribute('aria-label', name); return input;
        };
        let busy = false, read = null, results = [], selected = -1, prepared = null, total = 0;
        const current = () => { const c = host.context();
            if (c.kind !== identity.kind || c.number !== identity.number) throw Error('The open document changed. Open Find again.');
        };
        const controls = [];
        const run = async action => {
            if (busy) return;
            busy = true; controls.forEach(control => { control.disabled = true; });
            try { current(); await action(); } catch (error) { status.textContent = error.message; }
            finally { busy = false; controls.forEach(control => { control.disabled = false; }); }
        };
        const button = (name, action, parent = panel) => {
            const node = el('button', name, parent); node.type = 'button'; node.setAttribute('aria-label', name);
            node.addEventListener('click', () => run(action)); controls.push(node); return node;
        };
        el('strong', 'Find and Replace');
        button('Close find', () => { panel.remove(); active = null; });
        const query = field('Find text'), matchCase = field('Match case', 'checkbox');
        const status = el('p', '', panel); status.setAttribute('role', 'status');
        const list = el('ol'); list.className = 'documentation-find-results';
        const select = async index => {
            if (!results.length) return;
            selected = (index + results.length) % results.length;
            [...list.children].forEach((row, i) => row.setAttribute('aria-current', String(i === selected)));
            await host.focus(results[selected]);
            list.children[selected]?.scrollIntoView({ block: 'nearest' });
        };
        async function find() {
            if (!await root.DocumentationRichText?.finish()) throw Error('Finish the open text draft before finding.');
            current(); prepared = null; confirm.hidden = true; results = []; selected = -1; total = 0;
            let cursor;
            do {
                const page = await host.request('find', { query: query.value, caseSensitive: matchCase.checked,
                    limit: 200, ...(cursor ? { cursor, documentId: read.documentId } : {}) });
                read = page; results.push(...page.matches); cursor = page.cursor; total = page.total;
            } while (cursor && results.length < SHOWN);
            list.replaceChildren();
            results.forEach((item, index) => {
                const row = el('li', null, list), pick = el('button', null, row); pick.type = 'button';
                pick.appendChild(doc.createTextNode(host.label(item) + ': ' + item.before));
                el('mark', item.match, pick); pick.appendChild(doc.createTextNode(item.after));
                if (!item.editable) el('small', ' Read-only: ' + reason(item.reason), row);
                pick.addEventListener('click', () => run(() => select(index)));
            });
            status.textContent = results.length < total
                ? 'Showing the first ' + results.length + ' of ' + total + ' matches. Narrow the search to replace all.'
                : results.length + ' matches.';
            if (results.length) await select(0);
        }
        button('Find', find); button('Previous', () => select(selected - 1)); button('Next', () => select(selected + 1));
        const replacement = field('Replace with');
        async function apply(planned) {
            if (/[\r\n]/.test(replacement.value)) throw Error('Replacement cannot contain line breaks.');
            const text = replacement.value; let applied = 0, failure = '';
            const hashes = new Map();
            try {
                for (let index = 0; index < planned.length; index++) {
                    current(); status.textContent = 'Applying group ' + (index + 1) + ' of ' + planned.length + '.';
                    const payload = { documentId: read.documentId,
                        sourceRevision: read.sourceRevision, manualPlanRevision: read.manualPlanRevision,
                        sceneRevision: read.sceneRevision, expectedRevision: read.rangeRevision ?? read.revision,
                        requestId: root.crypto.randomUUID(), operations: planned[index].map(item => operation(
                            { ...item, contentHash: hashes.get(item.targetId) || item.contentHash }, text)) };
                    let response;
                    try { response = await host.request('ranges', payload); } catch (error) {
                        if (error.code) throw error;
                        // Transport uncertainty: recover the receipt with exactly the same request.
                        response = await host.request('ranges', payload);
                    }
                    applied++;
                    if (!response.rangeBinding && index + 1 < planned.length)
                        throw Error('Recovered this group receipt. Find again before applying the remaining groups.');
                    // Only hashes produced by our committed write may rebind pending matches. Never adopt an unrelated edit.
                    read = { ...read, ...response.rangeBinding };
                    for (const [key, hash] of Object.entries(response.rangeBinding?.hashes || {})) hashes.set(key, hash);
                }
            } catch (error) { failure = error.message + (!error.code ? ' Only confirmed group receipts are counted.' : ''); }
            try { await host.reload(); await find(); } catch (error) { failure = failure || error.message; }
            status.textContent = 'Applied ' + applied + ' of ' + planned.length + (planned.length === 1 ? ' group.' : ' groups.')
                + (failure ? ' Stopped: ' + failure : '');
        }
        button('Replace', async () => {
            const item = results[selected]; if (!item?.editable) throw Error('Select a replaceable match.');
            await apply([[item]]);
        });
        button('Replace all', () => {
            if (results.length < total) throw Error('Replace all needs every match: ' + total + ' found, '
                + results.length + ' shown. Narrow the search.');
            const summary = preview(results); prepared = groups(results);
            status.textContent = summary.total + ' matches; ' + summary.replaceable + ' replaceable; '
                + summary.readOnly + ' read-only' + (summary.readOnly ? ' (' + Object.entries(summary.reasons)
                    .map(([code, count]) => reason(code) + ': ' + count).join(', ') + ')' : '')
                + '. ' + summary.groups + (summary.groups === 1 ? ' group' : ' groups')
                + ', one undo step per group. Review before applying.';
            confirm.hidden = !prepared.length;
        });
        const confirm = button('Apply replacement groups', async () => { if (prepared) await apply(prepared); }); confirm.hidden = true;
        for (const input of [query, matchCase, replacement]) {
            controls.push(input);
            input.addEventListener('input', () => { prepared = null; confirm.hidden = true;
                if (input !== replacement) { read = null; results = []; selected = -1; list.replaceChildren(); } });
        }
        query.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); void run(find); } });
        panel.addEventListener('keydown', event => { event.stopPropagation(); if (event.key === 'Escape' && !busy) { panel.remove(); active = null; } });
        // Inside the workspace element, so it is removed with it (another tab, another machine). The workspace is
        // a click-through overlay; the panel's CSS turns pointer events back on.
        (doc.getElementById('documentationWorkspace') || doc.body).appendChild(panel); active = panel; query.focus();
    }
    // Another document in the same workspace: the results belong to the old one.
    const close = () => { if (active) { active.remove(); active = null; } };
    const sync = context => { if (active && (context?.kind !== owner.kind || context?.number !== owner.number)) close(); };
    root.DocumentationSearch = { ...helpers, open, close, sync, isOpen: () => !!active?.isConnected };
})(typeof window === 'undefined' ? globalThis : window);
