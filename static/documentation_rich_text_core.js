/* Schema-1 client boundary. No DOM, Tiptap or storage dependency. */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.DocumentationRichTextCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    const LIMITS = Object.freeze({ nodes: 512, lists: 3, depth: 12, bytes: 24 * 1024 });
    const ID = /^rt-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
    const BLOCKS = ['paragraph', 'heading', 'bulletList', 'orderedList'];
    const IDENTIFIED = [...BLOCKS, 'listItem', 'hardBreak'];
    const MARKS = ['bold', 'italic', 'underline', 'textStyle', 'link'];
    const INVALID_UNICODE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u;
    const LINK = Object.freeze({ target: '_blank', rel: 'noopener noreferrer nofollow', class: null });
    // Deliberately bounded CSS color subset. Unknown names/alpha colors are dropped.
    const COLORS = Object.freeze({ black: '#000000', white: '#ffffff', red: '#ff0000',
        green: '#008000', blue: '#0000ff', yellow: '#ffff00', orange: '#ffa500',
        purple: '#800080', gray: '#808080', grey: '#808080', silver: '#c0c0c0',
        maroon: '#800000', olive: '#808000', lime: '#00ff00', teal: '#008080',
        aqua: '#00ffff', cyan: '#00ffff', navy: '#000080', fuchsia: '#ff00ff', magenta: '#ff00ff',
        rebeccapurple: '#663399' });
    function fail(message, code = 'invalid_rich_text') {
        const error = new Error(message); error.code = code; throw error;
    }
    function color(value) {
        if (typeof value !== 'string') return null;
        const s = value.trim().toLowerCase();
        if (/^#[0-9a-f]{6}$/.test(s)) return s;
        if (/^#[0-9a-f]{3}$/.test(s)) return '#' + [...s.slice(1)].map(c => c + c).join('');
        if (Object.hasOwn(COLORS, s)) return COLORS[s];
        const match = /^rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$/.exec(s);
        if (!match || match.slice(1).some(n => Number(n) > 255)) return null;
        return '#' + match.slice(1).map(n => Number(n).toString(16).padStart(2, '0')).join('');
    }
    function href(value) {
        if (typeof value !== 'string' || !value || value.length > 2048 || INVALID_UNICODE.test(value)
            || /[\s\u0000-\u001f\u007f\\]/.test(value) || !/^https?:\/\/[^/?#]+/i.test(value)) return null;
        try {
            const url = new URL(value);
            if (!url.hostname || url.username || url.password || /@/.test(value.split('/')[2])) return null;
            return value;
        } catch (_) { return null; }
    }
    function allocate() { return 'rt-' + globalThis.crypto.randomUUID(); }
    function nodeIds(value) {
        const result = new Set(), pending = [value];
        let visited = 0;
        while (pending.length && visited++ < 8192) {
            const item = pending.pop();
            if (!item || typeof item !== 'object') continue;
            if (typeof item.attrs?.id === 'string') result.add(item.attrs.id);
            pending.push(...(Array.isArray(item) ? item : Object.values(item)));
        }
        return result;
    }
    function reservedIds(fields, field) {
        const result = new Set();
        for (const other of fields || []) {
            if (other.pageId === field.pageId && other.targetId === field.targetId) continue;
            for (const id of nodeIds(other.richText)) result.add(id);
        }
        return result;
    }
    function sorted(value) {
        if (Array.isArray(value)) return value.map(sorted);
        if (value && typeof value === 'object') return Object.fromEntries(
            Object.keys(value).sort().map(key => [key, sorted(value[key])]));
        return value;
    }
    function canonical(value) { return JSON.stringify(sorted(value)); }
    function normalize(value, options = {}) {
        const raw = value?.format === 'tiptap' ? value.doc : value;
        const used = new Set(options.reservedIds || []), makeId = options.idFactory || allocate;
        let count = 0;
        function identity(candidate) {
            if (typeof candidate === 'string' && ID.test(candidate) && !used.has(candidate)) {
                used.add(candidate); return candidate;
            }
            for (let attempt = 0; attempt < 1024; attempt++) {
                const id = makeId();
                if (ID.test(id) && !used.has(id)) { used.add(id); return id; }
            }
            fail('Could not allocate a unique text node ID. Your draft is still open.');
        }
        function marks(items) {
            if (!Array.isArray(items)) fail('Invalid text marks.');
            const found = new Map();
            for (const item of items) {
                if (!MARKS.includes(item?.type)) fail('This text contains an unsupported mark.');
                let mark = { type: item.type };
                if (item.type === 'textStyle') {
                    const c = color(item.attrs?.color);
                    if (!c) continue;
                    mark.attrs = { color: c };
                } else if (item.type === 'link') {
                    const link = href(item.attrs?.href);
                    if (!link) continue;
                    mark.attrs = { href: link };
                }
                found.set(item.type, mark);
            }
            return MARKS.filter(type => found.has(type)).map(type => found.get(type));
        }
        function node(item, depth = 0, lists = 0) {
            if (++count > LIMITS.nodes || depth > LIMITS.depth) {
                fail('Text is limited to 512 nodes and 12 levels. Shorten the draft before saving.', 'rich_text_too_large');
            }
            const type = item?.type;
            if (!['doc', 'text', ...IDENTIFIED].includes(type) || (type === 'doc') !== (depth === 0)) {
                fail('This text contains an unsupported node.');
            }
            const result = { type };
            if (IDENTIFIED.includes(type)) result.attrs = { id: identity(item.attrs?.id) };
            if (type === 'heading') {
                const level = item.attrs?.level;
                if (!Number.isInteger(level) || level < 1 || level > 3) fail('Use heading levels 1 to 3.');
                result.attrs.level = level;
            }
            if (type === 'orderedList') {
                const start = item.attrs?.start ?? 1;
                if (!Number.isInteger(start) || start < 1 || start > 9999) fail('List start must be 1 to 9999.');
                result.attrs.start = start;
            }
            if (type === 'text') {
                if (typeof item.text !== 'string' || !item.text || INVALID_UNICODE.test(item.text)) {
                    fail('Text must contain valid Unicode.');
                }
                result.text = item.text;
            }
            if (item.marks?.length) {
                if (!['text', 'hardBreak'].includes(type)) fail('Only inline text can carry marks.');
                const normalized = marks(item.marks);
                if (normalized.length) result.marks = normalized;
            }
            if (['text', 'hardBreak'].includes(type)) {
                if (item.content) fail('Inline nodes cannot contain children.');
                return result;
            }
            if (['bulletList', 'orderedList'].includes(type) && ++lists > LIMITS.lists) {
                fail('Lists are limited to three levels. Reduce nesting before saving.', 'rich_text_too_large');
            }
            if (item.content !== undefined && !Array.isArray(item.content)) fail('Invalid text children.');
            const children = (item.content || []).map(child => node(child, depth + 1, lists));
            const allowed = ['paragraph', 'heading'].includes(type) ? ['text', 'hardBreak']
                : ['bulletList', 'orderedList'].includes(type) ? ['listItem'] : BLOCKS;
            if (children.some(child => !allowed.includes(child.type))
                || (!children.length && ['doc', 'bulletList', 'orderedList', 'listItem'].includes(type))
                || (type === 'listItem' && children[0]?.type !== 'paragraph')) fail('Invalid text structure.');
            if (children.length) result.content = children;
            return result;
        }
        const envelope = { format: 'tiptap', schemaVersion: 1, doc: node(raw) };
        // Count the server's canonical representation, including its fixed link attributes.
        const stored = JSON.parse(JSON.stringify(envelope));
        (function links(item) {
            for (const mark of item.marks || []) if (mark.type === 'link') Object.assign(mark.attrs, LINK);
            (item.content || []).forEach(links);
        })(stored.doc);
        if (new TextEncoder().encode(canonical(stored)).length > LIMITS.bytes) {
            fail('Text is limited to 24 KiB. Shorten the draft before saving.', 'rich_text_too_large');
        }
        return envelope;
    }
    function fromPlain(text, options = {}) {
        if (typeof text !== 'string') fail('Plain text must be a string.');
        const content = [];
        text.split('\n').forEach((line, index) => {
            if (index) content.push({ type: 'hardBreak' });
            if (line) content.push({ type: 'text', text: line });
        });
        return normalize({ type: 'doc', content: [{ type: 'paragraph', content }] }, options);
    }
    function plainText(value) {
        function project(node) {
            if (node.type === 'text') return node.text;
            if (node.type === 'hardBreak') return '\n';
            return (node.content || []).map(project).join(['paragraph', 'heading'].includes(node.type) ? '' : '\n');
        }
        return project(value.doc || value);
    }
    return { LIMITS, ID, IDENTIFIED, LINK, color, href, nodeIds, reservedIds, canonical, normalize, fromPlain, plainText };
});
