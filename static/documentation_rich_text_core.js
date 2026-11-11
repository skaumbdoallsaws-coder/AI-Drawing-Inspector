/* Versioned rich-text boundary. No DOM, Tiptap or storage dependency. */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.DocumentationRichTextCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    const LIMITS = Object.freeze({ nodes: 512, lists: 6, depth: 14, bytes: 24 * 1024 });
    const ID = /^rt-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
    const BLOCKS = ['paragraph', 'heading', 'bulletList', 'orderedList'];
    const IDENTIFIED = [...BLOCKS, 'listItem', 'hardBreak'];
    const MARKS = ['bold', 'italic', 'underline', 'strike', 'subscript', 'superscript', 'highlight', 'textStyle', 'link'];
    const INVALID_UNICODE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u;
    const LINK = Object.freeze({ target: '_blank', rel: 'noopener noreferrer nofollow', class: null });
    // Opaque CSS named colors. Alpha/system/current colors cannot map exactly and are dropped.
    const COLORS = Object.freeze({ black: '#000000', white: '#ffffff', red: '#ff0000',
        green: '#008000', blue: '#0000ff', yellow: '#ffff00', orange: '#ffa500',
        purple: '#800080', gray: '#808080', grey: '#808080', silver: '#c0c0c0',
        maroon: '#800000', olive: '#808000', lime: '#00ff00', teal: '#008080',
        aqua: '#00ffff', cyan: '#00ffff', navy: '#000080', fuchsia: '#ff00ff', magenta: '#ff00ff',
        rebeccapurple: '#663399', aliceblue: '#f0f8ff', antiquewhite: '#faebd7', aquamarine: '#7fffd4', azure: '#f0ffff',
        beige: '#f5f5dc', bisque: '#ffe4c4', blanchedalmond: '#ffebcd', blueviolet: '#8a2be2', brown: '#a52a2a',
        burlywood: '#deb887', cadetblue: '#5f9ea0', chartreuse: '#7fff00', chocolate: '#d2691e', coral: '#ff7f50',
        cornflowerblue: '#6495ed', cornsilk: '#fff8dc', crimson: '#dc143c', darkblue: '#00008b', darkcyan: '#008b8b',
        darkgoldenrod: '#b8860b', darkgray: '#a9a9a9', darkgrey: '#a9a9a9', darkgreen: '#006400', darkkhaki: '#bdb76b',
        darkmagenta: '#8b008b', darkolivegreen: '#556b2f', darkorange: '#ff8c00', darkorchid: '#9932cc', darkred: '#8b0000',
        darksalmon: '#e9967a', darkseagreen: '#8fbc8f', darkslateblue: '#483d8b', darkslategray: '#2f4f4f', darkslategrey: '#2f4f4f',
        darkturquoise: '#00ced1', darkviolet: '#9400d3', deeppink: '#ff1493', deepskyblue: '#00bfff', dimgray: '#696969',
        dimgrey: '#696969', dodgerblue: '#1e90ff', firebrick: '#b22222', floralwhite: '#fffaf0', forestgreen: '#228b22',
        gainsboro: '#dcdcdc', ghostwhite: '#f8f8ff', gold: '#ffd700', goldenrod: '#daa520', greenyellow: '#adff2f',
        honeydew: '#f0fff0', hotpink: '#ff69b4', indianred: '#cd5c5c', indigo: '#4b0082', ivory: '#fffff0',
        khaki: '#f0e68c', lavender: '#e6e6fa', lavenderblush: '#fff0f5', lawngreen: '#7cfc00', lemonchiffon: '#fffacd',
        lightblue: '#add8e6', lightcoral: '#f08080', lightcyan: '#e0ffff', lightgoldenrodyellow: '#fafad2', lightgray: '#d3d3d3',
        lightgrey: '#d3d3d3', lightgreen: '#90ee90', lightpink: '#ffb6c1', lightsalmon: '#ffa07a', lightseagreen: '#20b2aa',
        lightskyblue: '#87cefa', lightslategray: '#778899', lightslategrey: '#778899', lightsteelblue: '#b0c4de', lightyellow: '#ffffe0',
        limegreen: '#32cd32', linen: '#faf0e6', mediumaquamarine: '#66cdaa', mediumblue: '#0000cd', mediumorchid: '#ba55d3',
        mediumpurple: '#9370db', mediumseagreen: '#3cb371', mediumslateblue: '#7b68ee', mediumspringgreen: '#00fa9a', mediumturquoise: '#48d1cc',
        mediumvioletred: '#c71585', midnightblue: '#191970', mintcream: '#f5fffa', mistyrose: '#ffe4e1', moccasin: '#ffe4b5',
        navajowhite: '#ffdead', oldlace: '#fdf5e6', olivedrab: '#6b8e23', orangered: '#ff4500', orchid: '#da70d6',
        palegoldenrod: '#eee8aa', palegreen: '#98fb98', paleturquoise: '#afeeee', palevioletred: '#db7093', papayawhip: '#ffefd5',
        peachpuff: '#ffdab9', peru: '#cd853f', pink: '#ffc0cb', plum: '#dda0dd', powderblue: '#b0e0e6',
        rosybrown: '#bc8f8f', royalblue: '#4169e1', saddlebrown: '#8b4513', salmon: '#fa8072', sandybrown: '#f4a460',
        seagreen: '#2e8b57', seashell: '#fff5ee', sienna: '#a0522d', skyblue: '#87ceeb', slateblue: '#6a5acd',
        slategray: '#708090', slategrey: '#708090', snow: '#fffafa', springgreen: '#00ff7f', steelblue: '#4682b4',
        tan: '#d2b48c', thistle: '#d8bfd8', tomato: '#ff6347', turquoise: '#40e0d0', violet: '#ee82ee',
        wheat: '#f5deb3', whitesmoke: '#f5f5f5', yellowgreen: '#9acd32' });
    // Keep this table in sync with documentation/rich_fonts.py. No font discovery.
    const arial = Object.freeze({ canvas: 'Arial', pdf: 'Helvetica', docx: 'Arial', ascent: .9053, descent: .2119,
        script_size: .6499, sub_offset: .1382, sup_offset: .4771 });
    const times = Object.freeze({ canvas: 'Times New Roman', pdf: 'Times', docx: 'Times New Roman', ascent: .8911, descent: .2163,
        script_size: .6499, sub_offset: .1431, sup_offset: .4531 });
    const courier = Object.freeze({ canvas: 'Courier New', pdf: 'Courier', docx: 'Courier New', ascent: .8325, descent: .3003,
        script_size: .6499, sub_offset: .1392, sup_offset: .4224 });
    const FONT_MAP = Object.freeze({ Arial: arial, Helvetica: arial, 'Times New Roman': times, 'Courier New': courier });
    const RENDER_MARKS = Object.freeze(['bold', 'italic', 'underline', 'strike', 'subscript', 'superscript', 'highlight', 'textStyle', 'link']);
    function font(value) {
        if (Object.hasOwn(FONT_MAP, value)) return FONT_MAP[value];
        const name = String(value || 'Arial').toLowerCase();
        return name.includes('courier') ? courier : /times|georgia/.test(name) ? times : arial;
    }
    const FEATURES = Object.freeze(['bold', 'italic', 'underline', 'strike', 'subscript', 'superscript', 'highlight', 'color',
        'fontFamily', 'fontSize', 'link', 'heading', 'bulletList', 'orderedList', 'textAlign', 'indent',
        'spaceBefore', 'spaceAfter', 'lineHeight', 'namedStyle']);
    const NAMED_STYLES = Object.freeze({ title: { scale: 2.25, bold: true },
        caption: { scale: .85, italic: true, color: '#5b6670' }, note: { scale: .9, color: '#5b6670' } });
    const PARAGRAPH_ATTRS = Object.freeze(['textAlign', 'indent', 'spaceBefore', 'spaceAfter', 'lineHeight', 'namedStyle']);
    const SCHEMA2_FEATURES = Object.freeze(['strike', 'subscript', 'superscript', 'highlight', 'fontFamily', 'fontSize', ...PARAGRAPH_ATTRS]);
    const FULL_CAPABILITIES = Object.freeze({ schemaVersions: [1, 2], features: FEATURES, listDepth: 6 });
    function usedFeatures(value) {
        const found = new Set(); let deepest = 0, count = 0;
        function walk(node, depth = 0) {
            if (++count > LIMITS.nodes) fail('Rich text exceeds its node bound.', 'rich_text_too_large');
            if (['bulletList', 'orderedList'].includes(node.type)) { depth++; deepest = Math.max(deepest, depth); }
            if (['heading', 'bulletList', 'orderedList'].includes(node.type)) found.add(node.type);
            for (const name of PARAGRAPH_ATTRS) if (node.attrs?.[name] != null) found.add(name);
            for (const mark of node.marks || []) {
                if (mark.type === 'textStyle') {
                    for (const key of Object.keys(mark.attrs || {})) if (mark.attrs[key] != null) found.add(key);
                } else found.add(mark.type);
            }
            for (const child of node.content || []) walk(child, depth);
        }
        walk(value.doc || value);
        return { features: [...found].sort(), listDepth: deepest };
    }
    function requireCapabilities(value, capabilities = FULL_CAPABILITIES) {
        const used = usedFeatures(value);
        const refused = used.features.filter(name => !(capabilities.features || []).includes(name));
        if (!(capabilities.schemaVersions || []).includes(value.schemaVersion)
            || used.listDepth > (capabilities.listDepth || 0) || refused.length) {
            fail('This target does not support this rich formatting.', 'unsupported_rich_text_feature');
        }
        return value;
    }
    function readOnlyReason(field) {
        if (field?.richTextError) return 'This rich text field is read-only: ' + field.richTextError;
        if (!field?.richText) return '';
        try {
            const value = normalize(field.richText);
            // A stored non-minimal version remains stored, and must also be supported.
            requireCapabilities({ ...value, schemaVersion: field.richText.schemaVersion }, field.richTextCapabilities || FULL_CAPABILITIES);
            return '';
        } catch (_) {
            return 'This formatting is not supported by this target. This field is read-only; nothing will be saved over it.';
        }
    }
    function pasteFontFamily(value) {
        if (typeof value !== 'string') return null;
        const first = value.split(',')[0].trim().replace(/^['"]|['"]$/g, '').toLowerCase();
        return Object.keys(FONT_MAP).find(token => token.toLowerCase() === first) || null;
    }
    function pasteFontSize(value) {
        if (typeof value !== 'string' || !/^(?:\d+(?:\.\d*)?|\.\d+)px$/i.test(value.trim())) return null;
        const size = Number.parseFloat(value);
        return size >= 6 && size <= 48 ? Math.round(size * 2) / 2 : null;
    }
    function paragraphValue(name, value, paste = false) {
        if (value == null) return null;
        let result = value;
        if (name === 'textAlign') {
            if (['left', 'center', 'right'].includes(value)) return value;
        } else if (name === 'namedStyle') {
            if (typeof value === 'string' && Object.hasOwn(NAMED_STYLES, value)) return value;
        } else {
            if (paste && typeof value === 'string' && /^(?:\d+(?:\.\d*)?|\.\d+)(?:px)?$/.test(value.trim())) result = Number.parseFloat(value);
            const [min, max, step] = name === 'lineHeight' ? [1, 2, .05] : [0, name === 'indent' ? 72 : 36, .5];
            if (typeof result === 'number' && Number.isFinite(result) && result >= min && result <= max
                && Math.abs(result / step - Math.round(result / step)) < 1e-9) return Math.round(result * 100) / 100;
        }
        if (paste) return null;
        fail('Typography value is outside its range or step.');
    }
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
        const envelopeInput = value && (Object.hasOwn(value, 'format') || Object.hasOwn(value, 'schemaVersion'));
        const editor = !envelopeInput || options.editor === true;
        const paste = options.paste === true || editor;
        function keys(object, allowed, required = []) {
            if (!object || typeof object !== 'object' || Array.isArray(object)
                || Object.keys(object).some(k => !allowed.includes(k)) || required.some(k => !Object.hasOwn(object, k))) {
                fail('Unsupported rich text keys or missing required keys.');
            }
        }
        if (envelopeInput) {
            keys(value, ['format', 'schemaVersion', 'doc'], ['format', 'schemaVersion', 'doc']);
            if (value.format !== 'tiptap' || !Number.isInteger(value.schemaVersion) || ![1, 2].includes(value.schemaVersion)) {
                fail('Unsupported rich text envelope.', 'unsupported_rich_text_schema');
            }
        }
        const raw = envelopeInput ? value.doc : value;
        const used = new Set(options.reservedIds || []), makeId = options.idFactory || allocate;
        let count = 0;
        function feature2() {
            if (envelopeInput && value.schemaVersion === 1) fail('Schema-2 formatting requires schemaVersion 2.', 'unsupported_rich_text_schema');
        }
        function identity(candidate) {
            if (typeof candidate === 'string' && ID.test(candidate) && !used.has(candidate)) { used.add(candidate); return candidate; }
            if (!editor) fail('Authored node IDs must be valid and unique.', used.has(candidate) ? 'rich_text_node_id_collision' : 'invalid_rich_text_node_id');
            for (let attempt = 0; attempt < 1024; attempt++) {
                const id = makeId();
                if (ID.test(id) && !used.has(id)) { used.add(id); return id; }
            }
            fail('Could not allocate a unique text node ID. Your draft is still open.');
        }
        function hex(value) {
            const result = editor ? color(value) : typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value) ? value.toLowerCase() : null;
            if (!result && !paste) fail('Color must be a six-digit hex color.');
            return result;
        }
        function marks(items) {
            if (!Array.isArray(items) || items.length > MARKS.length + (editor ? 1 : 0)) fail('Invalid rich text marks.');
            const found = new Map();
            let duplicate = false;
            for (const item of items) {
                keys(item, ['type', 'attrs'], ['type']);
                if (editor && item.type === 'documentationInheritedUnderline') { keys(item.attrs === undefined ? {} : item.attrs, []); continue; }
                if (!MARKS.includes(item.type)) fail('Unsupported rich text mark.');
                if (found.has(item.type)) duplicate = true;
                const attrs = item.attrs === undefined ? {} : item.attrs;
                if (['strike', 'subscript', 'superscript', 'highlight'].includes(item.type)) feature2();
                let mark = { type: item.type };
                if (item.type === 'textStyle') {
                    keys(attrs, ['color', 'fontFamily', 'fontSize']);
                    const clean = {};
                    for (const name of ['color', 'fontFamily', 'fontSize'].filter(key => Object.hasOwn(attrs, key))) {
                        const input = attrs[name];
                        if (editor && input == null) continue;
                        if (name === 'color') { const c = hex(input); if (c) clean.color = c; }
                        if (name === 'fontFamily') {
                            if (!editor) feature2();
                            const family = editor ? pasteFontFamily(input) : typeof input === 'string' && Object.hasOwn(FONT_MAP, input) ? input : null;
                            if (!family && !paste) fail('Unsupported rich text font family.');
                            if (family) { feature2(); clean.fontFamily = family; }
                        }
                        if (name === 'fontSize') {
                            if (!editor) feature2();
                            const size = editor && typeof input === 'string' ? pasteFontSize(input) : input;
                            if (typeof size !== 'number' || !Number.isFinite(size) || size < 6 || size > 48 || Math.abs(size * 2 - Math.round(size * 2)) > 1e-9) {
                                if (!paste) fail('Typography value is outside its range or step.');
                            } else { feature2(); clean.fontSize = Math.round(size * 2) / 2; }
                        }
                    }
                    if (!Object.keys(clean).length) { if (!editor) fail('Text style requires at least one attribute.'); continue; }
                    mark.attrs = clean;
                } else if (item.type === 'highlight') {
                    keys(attrs, ['color'], editor ? [] : ['color']);
                    const c = hex(attrs.color);
                    if (!c) continue;
                    mark.attrs = { color: c };
                } else if (item.type === 'link') {
                    if (!editor) keys(attrs, ['href', ...Object.keys(LINK)], ['href']);
                    const link = href(attrs.href);
                    if (!link) { if (paste) continue; fail('Links must be absolute HTTP or HTTPS URLs.', 'unsafe_rich_text_link'); }
                    mark.attrs = { href: link, ...LINK };
                } else keys(attrs, []);
                found.set(item.type, mark);
            }
            if (duplicate) fail('Duplicate rich text mark.');
            if (found.has('subscript') && found.has('superscript')) fail('Subscript and superscript cannot be combined.');
            return MARKS.filter(type => found.has(type)).map(type => found.get(type));
        }
        function node(item, depth = 0, lists = 0) {
            if (++count > LIMITS.nodes || depth > LIMITS.depth) fail('Rich text exceeds its node or depth bound.', 'rich_text_too_large');
            keys(item, ['type', 'attrs', 'content', 'text', 'marks'], ['type']);
            const type = item.type;
            if (!['doc', 'text', ...IDENTIFIED].includes(type) || (type === 'doc') !== (depth === 0)) fail('Unsupported rich text node.');
            const result = { type };
            const attrs = item.attrs === undefined ? {} : item.attrs;
            const allowed = ['paragraph', 'heading'].includes(type) ? [...PARAGRAPH_ATTRS, ...(type === 'heading' ? ['level'] : [])]
                : type === 'orderedList' ? ['start', ...(editor ? ['type'] : [])] : [];
            keys(attrs, [...allowed, ...(IDENTIFIED.includes(type) ? ['id'] : [])], !editor && IDENTIFIED.includes(type) ? ['id'] : []);
            if (IDENTIFIED.includes(type)) result.attrs = { id: identity(attrs.id) };
            for (const name of PARAGRAPH_ATTRS) if (Object.hasOwn(attrs, name)) {
                if (editor && attrs[name] == null) continue;
                feature2();
                const parsed = paragraphValue(name, attrs[name], paste);
                if (parsed == null) { if (!editor) fail('Invalid paragraph attribute.'); continue; }
                if (name === 'namedStyle' && (type !== 'paragraph' || depth !== 1)) fail('Named styles are allowed on top-level paragraphs only.');
                result.attrs[name] = parsed;
            }
            if (type === 'heading') {
                if (!Number.isInteger(attrs.level) || attrs.level < 1 || attrs.level > 3) fail('Heading levels are limited to 1-3.');
                result.attrs.level = attrs.level;
            }
            if (type === 'orderedList') {
                const start = editor ? attrs.start ?? 1 : Object.hasOwn(attrs, 'start') ? attrs.start : 1;
                if (!Number.isInteger(start) || start < 1 || start > 9999) fail('Ordered list start must be 1-9999.');
                result.attrs.start = start;
            }
            if (type === 'text') {
                if (Object.hasOwn(item, 'content') || typeof item.text !== 'string' || !item.text || INVALID_UNICODE.test(item.text)) fail('Text leaves require valid nonempty text and no children.');
                result.text = item.text;
            } else if (Object.hasOwn(item, 'text')) fail('Only text leaves contain text.');
            if (Object.hasOwn(item, 'marks')) {
                if (!['text', 'hardBreak'].includes(type)) fail('Invalid rich text marks.');
                const normalized = marks(item.marks);
                if (normalized.length) result.marks = normalized;
            }
            const children = item.content === undefined ? [] : item.content;
            if (!Array.isArray(children) || children.length > LIMITS.nodes) fail('Invalid rich text children.');
            if (['text', 'hardBreak'].includes(type)) {
                if (Object.hasOwn(item, 'content')) fail('Inline leaves cannot have children.');
            } else {
                if (['bulletList', 'orderedList'].includes(type)) {
                    if (++lists > LIMITS.lists) fail('List nesting exceeds six levels.', 'rich_text_too_large');
                    if (lists > 3) feature2();
                }
                const content = children.map(child => node(child, depth + 1, lists));
                const types = ['paragraph', 'heading'].includes(type) ? ['text', 'hardBreak']
                    : ['bulletList', 'orderedList'].includes(type) ? ['listItem'] : BLOCKS;
                if (content.some(child => !types.includes(child.type))
                    || (!content.length && ['doc', 'bulletList', 'orderedList', 'listItem'].includes(type))
                    || (type === 'listItem' && content[0]?.type !== 'paragraph')) fail('Invalid rich text child structure.');
                if (content.length) result.content = content;
            }
            return result;
        }
        const doc = node(raw);
        // Dropped paste attributes must not leave a phantom schema-2 envelope.
        const usedFeatures_ = usedFeatures({ doc });
        const v2 = usedFeatures_.listDepth > 3 || usedFeatures_.features.some(name =>
            SCHEMA2_FEATURES.includes(name));
        const result = { format: 'tiptap', schemaVersion: v2 ? 2 : 1, doc };
        if (new TextEncoder().encode(canonical(result)).length > LIMITS.bytes) fail('Rich text exceeds 24 KiB of canonical JSON.', 'rich_text_too_large');
        if (options.capabilities) requireCapabilities(result, options.capabilities);
        return result;
    }
    function baseLineHeight(style = {}) {
        const value = Number(style.baseLineHeight);
        return Number.isFinite(value) && value > 0 ? value : 1.2;
    }
    function editorDocument(value, { boxUnderline = false } = {}) {
        const doc = JSON.parse(JSON.stringify(value.doc));
        (function walk(node) {
            for (const mark of node.marks || []) if (mark.type === 'textStyle' && mark.attrs.fontSize != null) mark.attrs.fontSize += 'px';
            if ((boxUnderline || node.marks?.some(mark => mark.type === 'link')) && ['text', 'hardBreak'].includes(node.type)) {
                node.marks = [...(node.marks || []), { type: 'documentationInheritedUnderline' }];
            }
            (node.content || []).forEach(walk);
        })(doc);
        return doc;
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
    return { baseLineHeight, FEATURES, SCHEMA2_FEATURES, NAMED_STYLES, PARAGRAPH_ATTRS, FULL_CAPABILITIES, usedFeatures, requireCapabilities, pasteFontFamily, pasteFontSize, paragraphValue, editorDocument, FONT_MAP, RENDER_MARKS, font, readOnlyReason, LIMITS, ID, IDENTIFIED, LINK, color, href, nodeIds, reservedIds, canonical, normalize, fromPlain, plainText };
});
