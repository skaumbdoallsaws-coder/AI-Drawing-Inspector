/* One authored region; all persistence goes through the scene command callback. */
const core = window.DocumentationRichTextCore;
let kit = null;
let active = null;
let ready = null;
const api = {
    get ready() { return loadEditor(); },
    status: null,
    get active() { return active; },
    get mountedCount() { return active ? 1 : 0; },
    mount,
    dispose() { active?.dispose(); },
    // Navigation saves an open draft first; resolves true once no editor is mounted.
    finish() { return active ? active.finish() : Promise.resolve(true); },
    render,
};
window.DocumentationRichText = api;
// A static import would prevent ready from resolving when the bundle fails to load.
// Consume named exports only, from the reviewed self-contained module.
function loadEditor() {
    if (ready) return ready;
    ready = import('/static/vendor/tiptap/tiptap.bundle.js?v=c36fd989775f').then(
    ({ Editor, Extension, Mark, StarterKit, TextStyle, Color, FontFamily, FontSize,
        Highlight, Subscript, Superscript, TextAlign, Table, TableRow, TableCell, TableHeader }) => {
        if (!core || !Editor || !Extension || !StarterKit || !TextStyle || !Color) {
            return { ok: false, reason: 'The rich text editor is unavailable.' };
        }
        kit = { Editor, Extension, Mark, StarterKit, TextStyle, Color, FontFamily, FontSize,
            Highlight, Subscript, Superscript, TextAlign, Table, TableRow, TableCell, TableHeader };
        return { ok: true, reason: '' };
    }, () => ({ ok: false, reason: 'The rich text editor could not load. This field is read-only.' })
).then(status => {
    api.status = status;
    return status;
});
    return ready;
}

function applyBoxStyle(element, style = {}) {
    element.style.fontFamily = core.font(style.fontFamily).canvas;
    for (const name of ['fontSize', 'fontStyle', 'color', 'textAlign']) {
        if (style[name] != null) element.style[name] = String(style[name]) + (name === 'fontSize' ? 'px' : '');
    }
    // The exports draw a weight of 600 or more as bold (rich_layout content_model). Above 700, Windows Arial
    // resolves to Arial Black, so the canvas uses the same two weights (supervisor P3a-3).
    if (style.fontWeight != null) element.style.fontWeight = style.fontWeight === 'bold' || Number(style.fontWeight) >= 600 ? '700' : '400';
    element.style.lineHeight = String(core.baseLineHeight(style));
}

// Only the validated read envelope is rendered here. No HTML strings or URL navigation.
function render(element, envelope, boxStyle = {}) {
    const tags = { paragraph: 'p', bulletList: 'ul', orderedList: 'ol', listItem: 'li', hardBreak: 'br', table: 'table', tableRow: 'tr', tableCell: 'td', tableHeader: 'th' };
    // This wrapper maps legacy rich box families without changing the box font
    // selector or the style of any plain object. The caller sets box styles later.
    const root = document.createElement('div');
    root.className = 'documentation-rich-content';
    root.dataset.schemaVersion = String(envelope.schemaVersion);
    applyBoxStyle(root, boxStyle);
    function node(value) {
        if (value.type === 'text' || value.type === 'hardBreak') {
            let child = document.createElement(value.type === 'text' ? 'span' : 'br');
            if (value.type === 'text') child.textContent = value.text;
            const marks = [...(value.marks || [])].sort((a, b) => core.RENDER_MARKS.indexOf(a.type) - core.RENDER_MARKS.indexOf(b.type));
            const schema2 = envelope.schemaVersion >= 2;
            if (schema2 && (marks.some(m => m.type === 'link') || boxStyle.textDecoration === 'underline')
                && !marks.some(m => m.type === 'underline')) {
                // Keep the link outermost; link and box underlines use each run's size.
                marks.push({ type: 'underline' });
                marks.sort((a, b) => core.RENDER_MARKS.indexOf(a.type) - core.RENDER_MARKS.indexOf(b.type));
            }
            for (const mark of marks) {
                const tag = { bold: 'strong', italic: 'em', underline: 'u', strike: 's', subscript: 'sub', superscript: 'sup', highlight: 'mark', textStyle: 'span', link: 'a' }[mark.type];
                if (!tag) continue;
                const wrapper = document.createElement(tag);
                if (mark.type === 'textStyle') {
                    wrapper.style.color = core.color(mark.attrs?.color) || '';
                    if (mark.attrs?.color) wrapper.dataset.richColor = mark.attrs.color;
                    if (mark.attrs?.fontFamily) wrapper.dataset.richFontFamily = mark.attrs.fontFamily;
                    if (mark.attrs?.fontFamily) wrapper.style.fontFamily = core.font(mark.attrs.fontFamily).canvas;
                    if (mark.attrs?.fontSize != null) wrapper.style.fontSize = mark.attrs.fontSize + 'px';
                }
                if (mark.type === 'highlight') wrapper.style.backgroundColor = core.color(mark.attrs?.color) || '';
                if (mark.type === 'link') {
                    const href = core.href(mark.attrs?.href);
                    if (!href) continue;
                    if (schema2) wrapper.style.textDecoration = 'none';
                    wrapper.href = href;
                    wrapper.target = core.LINK.target;
                    wrapper.rel = core.LINK.rel;
                    const suppress = event => { event.preventDefault(); event.stopPropagation(); };
                    wrapper.addEventListener('click', suppress);
                    wrapper.addEventListener('auxclick', suppress);
                    wrapper.addEventListener('pointerdown', event => event.preventDefault());
                }
                wrapper.appendChild(child); child = wrapper;
            }
            return child;
        }
        const result = document.createElement(value.type === 'heading' ? 'h' + value.attrs.level : tags[value.type] || 'div');
        if (value.attrs?.id) result.dataset.richId = value.attrs.id;
        if (value.type === 'table') {
            result.dataset.tableStyle = value.attrs.style;
            const cols = document.createElement('colgroup');
            for (const column of value.attrs.columns) {
                const col = document.createElement('col'); col.dataset.richId = column.id;
                col.style.width = (column.width / 10) + '%'; cols.appendChild(col);
            }
            result.appendChild(cols);
        }
        if (['tableCell', 'tableHeader'].includes(value.type)) {
            result.colSpan = value.attrs.colspan || 1; result.rowSpan = value.attrs.rowspan || 1;
            result.style.verticalAlign = value.attrs.verticalAlign || 'top';
            result.style.backgroundColor = value.attrs.fill || (value.type === 'tableHeader' ? '#e9eef2' : 'transparent');
        }
        if (value.type === 'orderedList') result.start = value.attrs.start;
        result.style.whiteSpace = 'pre-wrap';
        if (['paragraph', 'heading', 'bulletList', 'orderedList'].includes(value.type)) result.style.margin = '0';
        if (['paragraph', 'heading'].includes(value.type)) {
            const attrs = value.attrs || {};
            if (attrs.namedStyle) result.dataset.namedStyle = attrs.namedStyle;
            for (const name of core.PARAGRAPH_ATTRS) if (attrs[name] != null && name !== 'namedStyle') {
                result.setAttribute('data-rich-' + name.replace(/[A-Z]/g, c => '-' + c.toLowerCase()), String(attrs[name]));
            }
            if (attrs.textAlign) result.style.textAlign = attrs.textAlign;
            if (attrs.indent != null) result.style.marginInlineStart = attrs.indent + 'px';
            if (attrs.spaceBefore != null) result.style.paddingTop = attrs.spaceBefore + 'px';
            if (attrs.spaceAfter != null) result.style.paddingBottom = attrs.spaceAfter + 'px';
            if (attrs.lineHeight != null) result.style.lineHeight = String(attrs.lineHeight);
        }
        if (value.type === 'paragraph' && !value.content?.length) result.appendChild(document.createElement('br'));
        for (const child of value.content || []) result.appendChild(node(child));
        return result;
    }
    for (const child of envelope.doc.content || []) root.appendChild(node(child));
    if (boxStyle.signalWord && root.firstElementChild?.tagName === 'P') {
        const signal = document.createElement('span');
        signal.className = 'documentation-rich-signal';
        signal.contentEditable = 'false';
        signal.textContent = boxStyle.signalWord;
        root.firstElementChild.prepend(signal);
    }
    element.replaceChildren(root);
}

// Paste reads inline authored values only. Computed margins and inherited foreign CSS never enter the model.
function cssColor(value) {
    const direct = core.color(value);
    if (direct || !value || !CSS.supports('color', value) || /^(inherit|initial|unset|revert|currentcolor)$/i.test(value)) return direct;
    const probe = document.createElement('span');
    probe.style.color = value; probe.hidden = true;
    document.body.appendChild(probe);
    const result = core.color(getComputedStyle(probe).color);
    probe.remove();
    return result;
}

function extensions(capabilities, sink, toggleList, boxUnderline, signalWord) {
    const { Extension, Mark, StarterKit, TextStyle, Color, FontFamily, FontSize, Highlight, Subscript, Superscript, TextAlign, Table, TableRow, TableCell, TableHeader } = kit;
    const allows = name => capabilities.features.includes(name);
    // Preserve the static renderer's outer link/color precedence. A presentation
    // mark at the leaf supplies each link's underline at the run's own size.
    const priorities = { textStyle: 120, highlight: 110, subscript: 100, superscript: 100,
        strike: 90, underline: 80, italic: 70, bold: 60, link: 200 };
    const starter = StarterKit.extend({
        addExtensions() {
            return this.parent().map(extension => {
                if (extension.name === 'paragraph' && signalWord) return extension.extend({
                    // The signal belongs to the frame, outside ProseMirror's contentDOM. Backspace, selection,
                    // copy and JSON serialization cannot edit it. CSS displays it on the first paragraph only.
                    renderHTML({ HTMLAttributes }) { return ['p', HTMLAttributes,
                        ['span', { class: 'documentation-rich-signal', contenteditable: 'false' }, signalWord],
                        ['span', { 'data-rich-copy': '' }, 0]]; },
                    parseHTML() { return [{ tag: 'p', contentElement: node => node.querySelector('[data-rich-copy]') || node }]; },
                });
                if (extension.type !== 'mark') return extension;
                if (extension.name === 'link') return extension.extend({ priority: priorities.link,
                    renderHTML(args) {
                        const output = this.parent(args);
                        output[1] = { ...output[1], style: 'text-decoration: none' };
                        return output;
                    },
                });
                return extension.extend({ priority: priorities[extension.name] || 100 });
            });
        },
    }).configure({
        code: false, codeBlock: false, blockquote: false, horizontalRule: false, trailingNode: false,
        bold: allows('bold') ? {} : false, italic: allows('italic') ? {} : false,
        underline: allows('underline') ? {} : false, strike: allows('strike') ? {} : false,
        heading: allows('heading') ? { levels: [1, 2, 3] } : false,
        bulletList: allows('bulletList') ? {} : false, orderedList: allows('orderedList') ? {} : false,
        listItem: allows('bulletList') || allows('orderedList') ? {} : false,
        listKeymap: allows('bulletList') || allows('orderedList') ? {} : false,
        link: allows('link') ? { openOnClick: false, autolink: false, linkOnPaste: false,
            isAllowedUri: value => Boolean(core.href(value)), HTMLAttributes: core.LINK } : false,
    });
    const result = [starter];

    if (allows('table') && capabilities.schemaVersions.includes(3)) {
        result.push(Table.extend({
            addAttributes() {
                return { ...(this.parent?.() || {}), ownership: { default: 'authored' },
                    style: { default: 'grid' }, columns: { default: null } };
            },
            renderHTML({ node }) {
                return ['table', { 'data-rich-id': node.attrs.id, 'data-table-style': node.attrs.style,
                    style: 'white-space: pre-wrap' },
                ['colgroup', ...(node.attrs.columns || []).map(column => ['col', {
                    'data-rich-id': column.id, style: 'width: ' + column.width / 10 + '%' }])],
                ['tbody', 0]];
            },
            addKeyboardShortcuts() {
                return { ...this.parent(),
                    Tab: () => {
                        if (!this.editor.isActive('table')) return false;
                        this.editor.commands.goToNextCell();
                        return true; // The last cell never grows a row or moves focus out.
                    },
                    'Shift-Tab': () => {
                        if (!this.editor.isActive('table')) return false;
                        this.editor.commands.goToPreviousCell(); return true;
                    },
                };
            },
        }).configure({ resizable: false, View: null }),
        TableRow.extend({ renderHTML({ node }) { return ['tr', { 'data-rich-id': node.attrs.id,
            style: 'white-space: pre-wrap' }, 0]; } }));
        for (const [extension, tag] of [[TableCell, 'td'], [TableHeader, 'th']]) result.push(extension.extend({
            content: 'paragraph+',
            addAttributes() {
                const { colspan, rowspan, colwidth } = this.parent();
                return { colspan, rowspan, colwidth, fill: { default: null }, verticalAlign: { default: 'top' } };
            },
            renderHTML({ node }) {
                return [tag, { 'data-rich-id': node.attrs.id, colspan: node.attrs.colspan,
                    rowspan: node.attrs.rowspan, style: 'white-space: pre-wrap; vertical-align: '
                        + (node.attrs.verticalAlign || 'top') + '; background-color: '
                        + (node.attrs.fill || (tag === 'th' ? '#e9eef2' : 'transparent')) }, 0];
            },
        }));
    }

    if (boxUnderline || allows('link')) result.push(Mark.create({ name: 'documentationInheritedUnderline', priority: 45,
        parseHTML() { return []; }, renderHTML() { return ['u', { 'data-rich-inherited-underline': '' }, 0]; },
    }));
    if (['color', 'fontFamily', 'fontSize'].some(allows)) result.push(TextStyle.extend({ priority: priorities.textStyle }));
    if (allows('color')) result.push(Color.extend({ addGlobalAttributes() {
        return [{ types: ['textStyle'], attributes: { color: { default: null,
            parseHTML: node => cssColor(node.style.color),
            renderHTML: attrs => attrs.color ? { style: 'color: ' + attrs.color, 'data-rich-color': attrs.color } : {},
        } } }];
    } }));
    if (allows('fontFamily')) result.push(FontFamily.extend({ addGlobalAttributes() {
        return [{ types: ['textStyle'], attributes: { fontFamily: { default: null,
            parseHTML: node => core.pasteFontFamily(node.getAttribute('data-rich-font-family') || node.style.fontFamily),
            renderHTML: attrs => attrs.fontFamily ? { style: 'font-family: ' + core.font(attrs.fontFamily).canvas,
                'data-rich-font-family': attrs.fontFamily } : {},
        } } }];
    } }));
    if (allows('fontSize')) result.push(FontSize.extend({ addGlobalAttributes() {
        return [{ types: ['textStyle'], attributes: { fontSize: { default: null,
            parseHTML: node => { const size = core.pasteFontSize(node.style.fontSize); return size == null ? null : size + 'px'; },
            renderHTML: attrs => attrs.fontSize ? { style: 'font-size: ' + attrs.fontSize } : {},
        } } }];
    } }));
    if (allows('subscript')) result.push(Subscript.extend({ priority: priorities.subscript, excludes: allows('superscript') ? 'superscript' : '' }));
    if (allows('superscript')) result.push(Superscript.extend({ priority: priorities.superscript, excludes: allows('subscript') ? 'subscript' : '' }));
    if (allows('highlight')) result.push(Highlight.extend({ priority: priorities.highlight,
        addAttributes() { return { color: { default: '#ffff00',
            parseHTML: node => { const value = node.style.backgroundColor || node.getAttribute('data-color'); return value ? cssColor(value) : '#ffff00'; },
            renderHTML: attrs => attrs.color ? { 'data-color': attrs.color, style: 'background-color: ' + attrs.color + '; color: inherit' } : {},
        } }; },
    }).configure({ multicolor: true }));
    if (allows('textAlign')) result.push(TextAlign.configure({ types: ['paragraph', 'heading'],
        alignments: ['left', 'center', 'right'], defaultAlignment: null }));
    const properties = { indent: 'margin-inline-start', spaceBefore: 'padding-top', spaceAfter: 'padding-bottom', lineHeight: 'line-height' };
    result.push(Extension.create({ name: 'documentationParagraphTypography', priority: 1000,
        addGlobalAttributes() {
            const attributes = {};
            for (const [name, property] of Object.entries(properties)) if (allows(name)) {
                const data = 'data-rich-' + name.replace(/[A-Z]/g, c => '-' + c.toLowerCase());
                attributes[name] = { default: null,
                    parseHTML: node => core.paragraphValue(name, (node.getAttribute(data) ?? node.style.getPropertyValue(property)) || null, true),
                    renderHTML: attrs => attrs[name] == null ? {} : { [data]: String(attrs[name]),
                        style: property + ': ' + attrs[name] + (name === 'lineHeight' ? '' : 'px') },
                };
            }
            const groups = [{ types: ['paragraph', ...(allows('heading') ? ['heading'] : [])], attributes }];
            if (allows('namedStyle')) groups.push({ types: ['paragraph'], attributes: { namedStyle: { default: null,
                parseHTML: node => node.closest('li') ? null : core.paragraphValue('namedStyle', node.getAttribute('data-named-style'), true),
                renderHTML: attrs => attrs.namedStyle ? { 'data-named-style': attrs.namedStyle } : {},
            } } });
            return groups;
        },
        addKeyboardShortcuts() {
            const keys = {};
            if (allows('bulletList') || allows('orderedList')) keys.Tab = () => this.editor.isActive('listItem') ? sink() : false;
            if (allows('bulletList')) keys['Mod-Shift-8'] = () => toggleList('toggleBulletList');
            if (allows('orderedList')) keys['Mod-Shift-7'] = () => toggleList('toggleOrderedList');
            return keys;
        },
    }));
    return result;
}

function mount(element, options) {
    const readOnly = core?.readOnlyReason(options.field);
    if (readOnly) { options.onError?.(new Error(readOnly)); return null; }
    if (!kit || !core || active || !element) return null;
    const { Editor, Extension } = kit;
    const advertised = options.field.richTextCapabilities || core.FULL_CAPABILITIES;
    const schema2 = advertised.schemaVersions.includes(2);
    const capabilities = { ...advertised,
        features: advertised.features.filter(name => (schema2 || !core.SCHEMA2_FEATURES.includes(name))
            && (advertised.listDepth > 0 || !['bulletList', 'orderedList'].includes(name))),
        listDepth: Math.min(advertised.listDepth, schema2 ? 6 : 3),
    };
    const allows = name => capabilities.features.includes(name);
    const field = options.field;
    const originalHash = field.contentHash;
    let composing = false, pendingCommit = false, saving = false, disposed = false, conflict = false;
    let blurTimer = null, dirty = false, inflight = null, tableBusy = false, tableFlight = null;
    let initialJSON;
    const listeners = [];
    function listen(target, event, fn, capture = false) {
        target.addEventListener(event, fn, capture);
        listeners.push(() => target.removeEventListener(event, fn, capture));
    }
    const originalNodes = [...element.childNodes];
    const boxUnderline = options.boxStyle?.textDecoration === 'underline';
    const originalDecoration = element.style.textDecoration;
    if (boxUnderline) element.style.textDecoration = 'none';
    element.replaceChildren();
    element.classList.add('documentation-rich-mounted');
    const editorHost = document.createElement('div');
    editorHost.className = 'documentation-rich-editor documentation-rich-content';
    applyBoxStyle(editorHost, options.boxStyle);
    element.appendChild(editorHost);
    const panel = document.createElement('div');
    panel.className = 'documentation-rich-panel';
    panel.setAttribute('aria-label', 'Rich text draft');
    const message = document.createElement('div');
    message.className = 'documentation-rich-message';
    message.setAttribute('role', 'status');
    message.setAttribute('aria-live', 'polite');
    panel.appendChild(message);
    const actions = document.createElement('div');
    actions.className = 'documentation-rich-actions';
    panel.appendChild(actions);
    (options.noticeHost || element.parentElement).appendChild(panel);
    const toolbar = document.createElement('span');
    toolbar.className = 'documentation-rich-controls';
    toolbar.setAttribute('aria-label', 'Rich text formatting');
    toolbar.setAttribute('role', 'toolbar');
    function button(host, label, callback, name) {
        const result = document.createElement('button');
        result.type = 'button'; result.textContent = label;
        result.dataset.richAction = name || label.toLowerCase();
        result.title = label;
        listen(result, 'pointerdown', event => event.preventDefault());
        listen(result, 'click', callback);
        host.appendChild(result);
        return result;
    }
    function notice(text, isConflict = false) {
        conflict = isConflict;
        message.textContent = text;
        panel.dataset.conflict = String(conflict);
        discard.hidden = overwrite.hidden = !conflict;
    }
    const done = button(actions, 'Done', () => commit(false), 'done');
    const cancel = button(actions, 'Cancel', () => { if (!saving && !tableBusy) close(); }, 'cancel');
    const discard = button(actions, 'Discard draft and load current', async () => {
        try {
            const snapshot = await options.read();
            if (disposed) return;
            close(); options.apply(snapshot);
        } catch (error) { if (!disposed) notice(error.message, true); }
    }, 'discard');
    const overwrite = button(actions, 'Save draft over newer value', () => commit(true), 'overwrite');
    discard.hidden = overwrite.hidden = true;
    const identities = Extension.create({
        name: 'documentationAuthoredIds',
        addGlobalAttributes() {
            return [{ types: core.IDENTIFIED, attributes: {
                id: { default: null, parseHTML: node => node.getAttribute('data-rich-id'),
                    renderHTML: attrs => attrs.id ? { 'data-rich-id': attrs.id } : {} },
            } }];
        },
    });
    let editor, savedSelection = null;
    const stateControls = [];
    const blockTypes = ['paragraph', ...(allows('heading') ? ['heading'] : [])];
    try {
        editor = new Editor({
            element: editorHost,
            enableCoreExtensions: { textDirection: false },
            extensions: [...extensions(capabilities, () => changeIndent(1), toggleList, boxUnderline, options.boxStyle?.signalWord), identities],
            content: core.editorDocument(field.richText || core.fromPlain(field.text), { boxUnderline }),
            parseOptions: { preserveWhitespace: 'full' },
            editorProps: {
                attributes: { 'aria-label': 'Rich text editor', role: 'textbox', 'aria-multiline': 'true' },
                handlePaste(view, event) {
                    const html = event.clipboardData?.getData('text/html');
                    if (html && new DOMParser().parseFromString(html, 'text/html').querySelector('table')) {
                        event.preventDefault(); notice(core.TABLE_PASTE_NOTICE); return true;
                    }
                    if (html) return false;
                    const text = event.clipboardData?.getData('text/plain');
                    if (text === undefined) return false;
                    event.preventDefault();
                    try {
                        // LF => hardBreak in the current paragraph; CR, tabs and spaces stay literal.
                        const inline = core.fromPlain(text).doc.content[0].content || [];
                        if (inline.length) editor.commands.insertContent(inline);
                    } catch (error) { notice(error.message); }
                    return true;
                },
            },
            onSelectionUpdate() { refreshControls(); },
            onTransaction() { refreshControls(); },
            onUpdate() {
                dirty = JSON.stringify(editor.getJSON()) !== initialJSON;
                if (!conflict) message.textContent = dirty ? 'Draft not yet saved.' : 'Edit text, then choose Done.';
            },
        });
    } catch (error) {
        panel.remove(); element.classList.remove('documentation-rich-mounted');
        element.style.textDecoration = originalDecoration;
        element.replaceChildren(...originalNodes);
        options.onError?.(error);
        return null;
    }
    // Apply presentation and structural invariants in the original transaction:
    // typing, paste and keyboard commands get the same contract as the ribbon.
    const dispatch = editor.view.props.dispatchTransaction;
    editor.view.setProps({ dispatchTransaction(tr) {
        // Supervisor: selection-only transactions cannot change a table; skip the two serializations.
        const tableReason = tr.docChanged ? core.tableGuard(editor.state.doc.toJSON(), tr.doc.toJSON()) : null;
        if (tableReason) { notice(tableReason); editor.view.updateState(editor.state); return; }
        let deepest = 0;
        function lists(node, depth = 0) {
            if (['bulletList', 'orderedList'].includes(node.type.name)) depth++;
            deepest = Math.max(deepest, depth);
            node.forEach(child => lists(child, depth));
        }
        lists(tr.doc);
        if (deepest > capabilities.listDepth) {
            notice('Lists are limited to ' + capabilities.listDepth + ' levels.');
            editor.view.updateState(editor.state);
            return;
        }
        const inherited = editor.schema.marks.documentationInheritedUnderline;
        tr.doc.descendants((node, pos, parent) => {
            if (node.type.name === 'paragraph' && node.attrs.namedStyle && parent.type.name !== 'doc') {
                tr.setNodeMarkup(pos, undefined, { ...node.attrs, namedStyle: null });
            }
            if (!inherited || !node.isInline) return;
            const needed = boxUnderline || node.marks.some(mark => mark.type.name === 'link');
            if (needed && !inherited.isInSet(node.marks)) tr.addMark(pos, pos + node.nodeSize, inherited.create());
            if (!needed && inherited.isInSet(node.marks)) tr.removeMark(pos, pos + node.nodeSize, inherited);
        });
        dispatch(tr);
    } });
    initialJSON = JSON.stringify(editor.getJSON());
    const controller = {
        element, editor, pageId: field.pageId, targetId: field.targetId,
        get dirty() { return dirty; },
        get composing() { return composing; },
        get saving() { return saving || tableBusy; },
        controls() { return [toolbar]; },
        reconcile(snapshot) {
            if (disposed || saving || tableBusy) return;
            const current = options.findField(snapshot);
            if (!current || current.contentHash !== originalHash) {
                if (dirty || composing) notice('This field changed elsewhere. Your draft is kept. Choose how to continue.', true);
                else close();
            }
        },
        commit: () => commit(false),
        async finish() {
            // Leaving the page or document saves the draft first, like a blur. True once closed;
            // false keeps the draft open (conflict, error or IME composition) and the caller stays.
            if (tableFlight) { await tableFlight; return false; }
            if (inflight) { await inflight; return disposed; }
            if (!disposed && !conflict) await commit(false);
            return disposed;
        },
        cancel: () => { if (!tableBusy) close(); },
        notice,
        dispose: () => close(false),
        ownsFocus(target) { return element.contains(target) || panel.contains(target) || toolbar.contains(target); },
    };
    active = controller;
    function close(notify = true) {
        if (disposed) return;
        disposed = true;
        clearTimeout(blurTimer);
        listeners.splice(0).forEach(remove => remove());
        editor.destroy(); panel.remove(); toolbar.remove();
        element.style.textDecoration = originalDecoration;
        element.classList.remove('documentation-rich-mounted');
        element.replaceChildren(...originalNodes);
        if (active === controller) active = null;
        if (notify) options.onClose?.();
    }
    function commit(overwriteNewer = false) {
        if (tableBusy) return tableFlight || Promise.resolve(false);
        // One save at a time, so navigation can wait for a running blur save.
        if (!inflight) inflight = save(overwriteNewer).finally(() => { inflight = null; });
        return inflight;
    }
    async function save(overwriteNewer) {
        if (disposed || saving) return;
        if (composing || editor.view.composing) { pendingCommit = true; return; }
        if (conflict && !overwriteNewer) return;
        if (!dirty) { close(); return; }
        saving = true; done.disabled = overwrite.disabled = cancel.disabled = true;
        message.textContent = 'Saving text...';
        editor.setEditable(false, false);
        try {
            // Validate before doing I/O; the fresh read reserves IDs added since mount.
            core.normalize(editor.getJSON(), { reservedIds: core.reservedIds(options.snapshot.richTextFields, field), capabilities });
            const snapshot = await options.read();
            if (disposed) return;
            const current = options.findField(snapshot);
            if (!current || (!overwriteNewer && current.contentHash !== originalHash)) {
                notice('This field changed elsewhere. Your draft is kept. Choose how to continue.', true);
                return;
            }
            if (core.readOnlyReason(current)) { notice(core.readOnlyReason(current)); return; }
            if (!snapshot.documentationRichText || !current.capabilities?.includes('replace_rich_text')) {
                notice('This field is no longer editable. Your draft is kept.'); return;
            }
            const richText = core.normalize(editor.getJSON(), {
                reservedIds: core.reservedIds(snapshot.richTextFields, current),
                capabilities: current.richTextCapabilities || capabilities,
            });
            await options.commit(snapshot, current, richText);
            if (disposed) return;
            // The POST body is fully consumed before a GET or any teardown/reload.
            const fresh = await options.read();
            if (disposed) return;
            close(false); options.apply(fresh); options.onClose?.(); options.onSaved?.();
            return fresh;
        } catch (error) {
            if (disposed) return;
            const concurrent = ['content_hash_mismatch', 'revision_conflict', 'stale_document_revision',
                'stale_revision', 'documentation_revision_conflict'].includes(error.code)
                || /revision|changed|stale|hash/i.test(error.code || '');
            notice(concurrent ? 'This field changed elsewhere. Your draft is kept. Choose how to continue.'
                : error.message + ' Your draft is kept.', concurrent);
        } finally {
            saving = false;
            if (!disposed) editor.setEditable(true, false);
            done.disabled = overwrite.disabled = cancel.disabled = tableBusy;
        }
    }
    function selectedBlocks(state = editor.state) {
        const blocks = [];
        const { from, to, $from, empty } = state.selection;
        if (empty) {
            for (let depth = $from.depth; depth > 0; depth--) {
                if ($from.node(depth).isTextblock) { blocks.push({ node: $from.node(depth), pos: $from.before(depth) }); break; }
            }
        } else state.doc.nodesBetween(from, to, (node, pos) => { if (node.isTextblock) blocks.push({ node, pos }); });
        return blocks;
    }
    function insideList() {
        const { $from, from, to } = editor.state.selection;
        for (let depth = $from.depth; depth > 0; depth--) if ($from.node(depth).type.name === 'listItem') return true;
        let found = false;
        editor.state.doc.nodesBetween(from, to, node => { if (node.type.name === 'listItem') found = true; });
        return found;
    }
    function insideCell() {
        const { $from, from, to } = editor.state.selection;
        if (editor.state.selection.$anchorCell) return true;
        for (let depth = $from.depth; depth > 0; depth--)
            if (['tableCell', 'tableHeader'].includes($from.node(depth).type.name)) return true;
        let found = false;
        editor.state.doc.nodesBetween(from, to, node => {
            if (['tableCell', 'tableHeader'].includes(node.type.name)) found = true;
        });
        return found;
    }
    function selectedMarks() {
        const { from, to, $from, empty } = editor.state.selection;
        if (empty) return [editor.state.storedMarks || $from.marks()];
        const marks = [];
        editor.state.doc.nodesBetween(from, to, (node, pos) => {
            if (node.isInline && pos < to && pos + node.nodeSize > from) marks.push(node.marks);
        });
        return marks.length ? marks : [[]];
    }
    function shared(values) {
        return values.every(value => value === values[0]) ? values[0] : undefined;
    }
    function markValue(name, attr) {
        return shared(selectedMarks().map(marks => {
            const mark = marks.find(value => value.type.name === name);
            return attr ? mark?.attrs[attr] ?? null : Boolean(mark);
        }));
    }
    function blockValue(name) { return shared(selectedBlocks().map(({ node }) => node.attrs[name] ?? null)); }
    function refreshControls() {
        if (!editor || editor.isDestroyed) return;
        for (const update of stateControls) update();
    }
    function perform(build) {
        if (disposed || saving || tableBusy) return false;
        // The pinned bundle's closeHistory helper uses this PluginKey name but
        // does not export the helper. Each ribbon action starts one undo group.
        let chain = editor.chain().focus().setMeta('closeHistory$', true);
        if (savedSelection) chain = chain.setTextSelection(savedSelection);
        const ok = build(chain).run();
        savedSelection = null;
        refreshControls();
        return ok;
    }
    function mark(command, argument) { return perform(chain => chain[command](argument)); }
    function paragraph(name, value) {
        return perform(chain => {
            for (const type of blockTypes) chain = chain.updateAttributes(type, { [name]: value });
            return chain;
        });
    }
    function fieldControl(label, control, callback, value) {
        control.title = label; control.setAttribute('aria-label', label);
        control.dataset.richControl = label.toLowerCase().replaceAll(' ', '-');
        listen(control, 'pointerdown', () => {
            const { from, to } = editor.state.selection; savedSelection = { from, to };
        });
        listen(control, 'change', () => { if (callback(control.value) !== false) refreshControls(); });
        const wrapper = document.createElement('label');
        wrapper.textContent = label + ' '; wrapper.appendChild(control); toolbar.appendChild(wrapper);
        stateControls.push(() => {
            const current = value();
            control.dataset.mixed = String(current === undefined);
            control.value = current == null ? '' : String(current);
        });
        return control;
    }
    function select(label, values, callback, value) {
        const control = document.createElement('select');
        // Mixed selections have an empty value; it is never an implicit default.
        control.appendChild(new Option('', '', false, false));
        for (const [key, text] of values) control.appendChild(new Option(text, key));
        return fieldControl(label, control, callback, value);
    }
    function number(label, min, max, step, callback, value) {
        const control = document.createElement('input');
        control.type = 'number'; control.min = String(min); control.max = String(max); control.step = String(step);
        return fieldControl(label, control, input => {
            if (input !== '' && (!control.validity.valid || !Number.isFinite(Number(input)))) {
                notice('Enter a value from ' + min + ' to ' + max + ' in steps of ' + step + '.'); return;
            }
            callback(input === '' ? null : Number(input));
        }, value);
    }
    function toggle(label, feature, command) {
        if (!allows(feature)) return;
        const control = button(toolbar, label, () => mark(command));
        stateControls.push(() => {
            const value = markValue(feature);
            control.setAttribute('aria-pressed', value === undefined ? 'mixed' : String(value));
        });
    }
    if (allows('heading') || allows('namedStyle')) {
        const values = [];
        if (allows('namedStyle')) values.push(['title', 'Title']);
        if (allows('heading')) for (let level = 1; level <= 3; level++) values.push(['h' + level, 'Heading ' + level]);
        values.push(['body', 'Body']);
        if (allows('namedStyle')) values.push(['caption', 'Caption'], ['note', 'Note']);
        const style = select('Style', values, value => {
            if (!value || insideList() || insideCell()) return;
            perform(chain => chain.command(({ tr, state }) => {
                const heading = /^h[1-3]$/.test(value);
                const type = editor.schema.nodes[heading ? 'heading' : 'paragraph'];
                for (const { node, pos } of selectedBlocks(state)) {
                    const attrs = { ...node.attrs };
                    delete attrs.level; delete attrs.namedStyle;
                    if (heading) attrs.level = Number(value.slice(1));
                    else if (allows('namedStyle')) attrs.namedStyle = value === 'body' ? null : value;
                    tr.setNodeMarkup(pos, type, attrs);
                }
                return true;
            }));
        }, () => shared(selectedBlocks().map(({ node }) => node.type.name === 'heading' ? 'h' + node.attrs.level : node.attrs.namedStyle || 'body')));
        stateControls.push(() => { style.disabled = tableBusy || insideList() || insideCell(); style.setAttribute('aria-disabled', String(style.disabled)); });
    }
    if (allows('fontFamily')) select('Font', [['box', 'Box font'], ...Object.keys(core.FONT_MAP).map(name => [name, name])],
        value => { if (value) mark(value === 'box' ? 'unsetFontFamily' : 'setFontFamily', value); },
        () => { const value = markValue('textStyle', 'fontFamily'); return value === null ? 'box' : value; });
    if (allows('fontSize')) number('Size', 6, 48, .5,
        value => mark(value == null ? 'unsetFontSize' : 'setFontSize', value == null ? undefined : value + 'px'),
        () => { const value = markValue('textStyle', 'fontSize'); return value == null ? value : Number.parseFloat(value); });
    toggle('Bold', 'bold', 'toggleBold');
    toggle('Italic', 'italic', 'toggleItalic');
    toggle('Underline', 'underline', 'toggleUnderline');
    toggle('Strikethrough', 'strike', 'toggleStrike');
    toggle('Subscript', 'subscript', 'toggleSubscript');
    toggle('Superscript', 'superscript', 'toggleSuperscript');
    function colorControl(label, feature, markName, attr, command) {
        if (!allows(feature)) return;
        const input = document.createElement('input'); input.type = 'text'; input.placeholder = '#rrggbb';
        input.className = 'documentation-rich-color';
        const apply = value => {
            const color = cssColor(value);
            if (!color) { notice('Enter a color such as #336699.'); return; }
            mark(command, markName === 'highlight' ? { color } : color);
        };
        const value = () => markValue(markName, attr);
        fieldControl(label, input, apply, value);
        // A native picker sits beside the field (supervisor P3a-2): a pick applies one undoable change. It shows the
        // shared colour, and black when the selection has none or mixes colours; the field stays empty then.
        const picker = document.createElement('input'); picker.type = 'color';
        picker.className = 'documentation-rich-color-picker';
        picker.title = label + ' picker'; picker.setAttribute('aria-label', label + ' picker');
        picker.dataset.richControl = input.dataset.richControl + '-picker';
        listen(picker, 'pointerdown', () => {
            const { from, to } = editor.state.selection; savedSelection = { from, to };
        });
        listen(picker, 'change', () => { apply(picker.value); refreshControls(); });
        input.parentElement.appendChild(picker);
        stateControls.push(() => {
            const current = value();
            picker.dataset.mixed = String(current === undefined);
            picker.value = typeof current === 'string' ? current : '#000000';
        });
    }
    colorControl('Text color', 'color', 'textStyle', 'color', 'setColor');
    colorControl('Highlight color', 'highlight', 'highlight', 'color', 'setHighlight');
    if (allows('highlight')) button(toolbar, 'Remove highlight', () => mark('unsetHighlight'));
    if (allows('textAlign')) {
        for (const align of ['left', 'center', 'right']) {
            const control = button(toolbar, 'Align ' + align, () => paragraph('textAlign', align));
            stateControls.push(() => control.setAttribute('aria-pressed', blockValue('textAlign') === undefined ? 'mixed' : String(blockValue('textAlign') === align)));
        }
        const reset = button(toolbar, 'Box alignment', () => paragraph('textAlign', null));
        stateControls.push(() => reset.setAttribute('aria-pressed', blockValue('textAlign') === undefined ? 'mixed' : String(blockValue('textAlign') === null)));
    }
    function changeIndent(direction) {
        if (!editor || disposed || saving) return false;
        if (insideList()) {
            if (direction < 0) return mark('liftListItem', 'listItem');
            let deepest = 0;
            for (const { pos } of selectedBlocks()) {
                const resolved = editor.state.doc.resolve(pos + 1);
                let itemDepth = resolved.depth;
                while (itemDepth > 0 && resolved.node(itemDepth).type.name !== 'listItem') itemDepth--;
                if (!itemDepth) continue;
                let depth = 0;
                for (let i = 0; i < itemDepth; i++) if (['bulletList', 'orderedList'].includes(resolved.node(i).type.name)) depth++;
                function nested(node, extra = 0) {
                    if (['bulletList', 'orderedList'].includes(node.type.name)) extra++;
                    deepest = Math.max(deepest, depth + extra);
                    node.forEach(child => nested(child, extra));
                }
                nested(resolved.node(itemDepth));
            }
            if (deepest >= capabilities.listDepth) { notice('Lists are limited to ' + capabilities.listDepth + ' levels.'); return true; }
            return mark('sinkListItem', 'listItem');
        }
        if (!allows('indent')) return false;
        return perform(chain => chain.command(({ tr, state }) => {
            for (const { node, pos } of selectedBlocks(state)) {
                const indent = Math.max(0, Math.min(72, (node.attrs.indent || 0) + direction * 18));
                tr.setNodeMarkup(pos, undefined, { ...node.attrs, indent: indent || null });
            }
            return true;
        }));
    }
    if (allows('indent') || allows('bulletList') || allows('orderedList')) {
        for (const [direction, label] of [[-1, 'Decrease indent'], [1, 'Increase indent']]) {
            const control = button(toolbar, label, () => changeIndent(direction));
            stateControls.push(() => {
                const list = insideList(), current = blockValue('indent');
                control.disabled = !list && !allows('indent');
                control.dataset.indent = current === undefined ? '' : String(current || 0);
                control.setAttribute('aria-description', list ? 'Lift or sink the selected list item.'
                    : current === undefined ? 'Mixed paragraph indents.' : 'Paragraph indent: ' + (current || 0) + ' pt.');
            });
        }
    }
    for (const [name, label] of [['spaceBefore', 'Space before'], ['spaceAfter', 'Space after']]) if (allows(name)) {
        number(label, 0, 36, .5, value => paragraph(name, value || null), () => blockValue(name));
    }
    if (allows('lineHeight')) {
        const base = core.baseLineHeight(options.boxStyle);
        const values = [...new Set([1, 1.15, 1.2, 1.5, 2, base])].sort((a, b) => a - b);
        const spacing = select('Line spacing', values.map(value => [String(value), String(value) + (value === base ? ' (default)' : '')]),
            value => { if (value) paragraph('lineHeight', Number(value) === base ? null : Number(value)); },
            () => {
                const current = blockValue('lineHeight');
                if (current != null && ![...spacing.options].some(option => option.value === String(current))) spacing.add(new Option(String(current), String(current)));
                return current === null ? base : current;
            });
    }
    function toggleList(command) {
        if (insideCell()) return false;
        return perform(chain => {
            if (allows('namedStyle')) chain = chain.updateAttributes('paragraph', { namedStyle: null });
            return chain[command]();
        });
    }
    for (const [name, label, command] of [['bulletList', 'Bullets', 'toggleBulletList'], ['orderedList', 'Numbering', 'toggleOrderedList']]) if (allows(name)) {
        const control = button(toolbar, label, () => toggleList(command));
        stateControls.push(() => {
            control.disabled = tableBusy || insideCell(); control.setAttribute('aria-disabled', String(control.disabled));
            const value = shared(selectedBlocks().map(({ pos }) => {
                const parent = editor.state.doc.resolve(pos + 1);
                for (let depth = parent.depth; depth > 0; depth--) if (parent.node(depth).type.name === name) return true;
                return false;
            }));
            control.setAttribute('aria-pressed', value === undefined ? 'mixed' : String(value));
        });
    }
    if (allows('link')) {
        const link = document.createElement('input'); link.type = 'url'; link.placeholder = 'https://example.com';
        fieldControl('HTTP or HTTPS link', link, () => false, () => markValue('link', 'href'));
        button(toolbar, 'Link', () => {
            const href = core.href(link.value);
            if (!href) { notice('Enter an absolute http:// or https:// link.'); return; }
            mark('setLink', { href });
        });
        button(toolbar, 'Unlink', () => mark('unsetLink'));
    }
    button(toolbar, 'Clear formatting', () => perform(chain => chain.command(({ tr, commands }) => {
        // Every selected block becomes a plain body paragraph outside every list, keeping its durable ID, and the
        // selected text loses every mark; a caret clears its whole block. Tiptap's clearNodes lifts a nested list
        // only one level per node: it split a six-level list into five one-item lists (supervisor P3a-2). Each
        // selected block is lifted with the list command until it is in no list, so unselected items stay valid lists.
        // Every lift runs on a fresh state of the current document and its steps are replayed onto this transaction:
        // the list command maps positions through its transaction's whole mapping and the chain state caches its
        // selection, so a second lift inside one chain threw "Inconsistent open depths" (supervisor P3a-2).
        const EditorState = editor.state.constructor, lift = editor.extensionManager.commands.liftListItem('listItem');
        const start = tr.steps.length, caret = tr.selection.empty ? tr.selection.from : null;
        const from = caret == null ? tr.selection.from : tr.selection.$from.start();
        const to = caret == null ? tr.selection.to : tr.selection.$from.end();
        const mapping = () => tr.mapping.slice(start);
        const bounds = () => [mapping().map(from, -1), mapping().map(to, 1)];
        function inList(pos) {
            const $pos = tr.doc.resolve(pos);
            for (let depth = $pos.depth; depth > 0; depth--) if ($pos.node(depth).type.name === 'listItem') return true;
            return false;
        }
        // Each lift moves one block a level out, so the summed depth bounds the passes.
        for (let guard = 0; guard < core.LIMITS.nodes * core.LIMITS.lists; guard++) {
            let target = null;
            tr.doc.nodesBetween(...bounds(), (node, pos) => {
                if (target != null) return false;
                if (!node.isTextblock) return true;
                if (inList(pos + 1)) target = pos + 1;
                return false;
            });
            if (target == null) break;
            commands.setTextSelection(target);
            let lifted = null;
            const fresh = EditorState.create({ doc: tr.doc, selection: tr.selection });
            if (!lift({ state: fresh, dispatch: next => { lifted = next; } }) || !lifted) break;
            for (const step of lifted.steps) tr.step(step);
        }
        const [a, b] = bounds();
        tr.doc.nodesBetween(a, b, (node, pos) => {
            if (!node.isTextblock) return true;
            tr.setNodeMarkup(pos, editor.schema.nodes.paragraph, { id: node.attrs.id });
            return false;
        });
        tr.removeMark(a, b);
        commands.setTextSelection(caret == null ? { from: a, to: b } : mapping().map(caret));
        return true;
    })));
    // Where the focus was when the Symbol or Table panel was opened: in the text (a toolbar button pressed
    // with the pointer leaves the caret there) or on the panel's button (opened from the keyboard). Escape
    // closes the panel and puts the focus back there, also after the panel itself held it (Table's fields).
    let panelFromText = true;
    const notePanelOrigin = () => { panelFromText = element.contains(document.activeElement); };
    const leavePanel = toggle => { if (panelFromText) editor.commands.focus(); else toggle.focus(); };
    const symbols = document.createElement('span');
    symbols.className = 'documentation-symbol-picker'; symbols.hidden = true;
    symbols.setAttribute('role', 'dialog'); symbols.setAttribute('aria-label', 'Engineering symbols');
    const symbolToggle = button(toolbar, 'Symbol', () => {
        if (symbols.hidden && (!tablePanel || tablePanel.hidden)) notePanelOrigin();
        symbols.hidden = !symbols.hidden; symbolToggle.setAttribute('aria-expanded', String(!symbols.hidden));
        const rect = symbolToggle.getBoundingClientRect();
        symbols.style.top = Math.min(rect.bottom + 4, window.innerHeight - 370) + 'px';
        symbols.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - 380)) + 'px';
    });
    symbolToggle.setAttribute('aria-expanded', 'false');
    symbolToggle.setAttribute('aria-haspopup', 'dialog');
    for (const group of window.DocumentationSymbols || []) {
        const section = document.createElement('fieldset'), legend = document.createElement('legend');
        legend.textContent = group.group; section.appendChild(legend);
        for (const symbol of group.symbols) {
            const pick = button(section, symbol.text, () => {
                perform(chain => chain.command(({ tr }) => {
                    tr.replaceSelectionWith(editor.schema.text(symbol.text), true); return true;
                }));
                symbols.hidden = true; symbolToggle.setAttribute('aria-expanded', 'false');
            }, 'symbol-' + symbol.text.codePointAt(0).toString(16));
            pick.title = symbol.name; pick.setAttribute('aria-label', symbol.name);
        }
        symbols.appendChild(section);
    }
    toolbar.appendChild(symbols);

    let tablePanel = null, tableToggle = null;
    // Supervisor: every Table menu control asks for the context on every transaction. One answer per editor
    // state keeps typing in a large table from serializing the document about twenty times per key.
    let contextState = null, contextValue = null;
    function tableContext() {
        if (contextState !== editor.state) { contextValue = readTableContext(); contextState = editor.state; }
        return { ...contextValue };
    }
    function readTableContext() {
        const selection = editor.state.selection;
        const anchor = selection.$anchorCell || selection.$from;
        const topLevelIndex = anchor.index(0), doc = editor.getJSON();
        const table = doc.content?.[topLevelIndex];
        const context = { topLevelIndex, afterId: core.tableAfterId(doc, topLevelIndex) };
        if (table?.type !== 'table') return context;
        let cellId = selection.$anchorCell ? editor.state.doc.nodeAt(anchor.pos)?.attrs.id : null;
        let cellPos = selection.$anchorCell ? anchor.pos : null;
        for (let depth = anchor.depth; depth > 0 && !cellId; depth--) {
            if (['tableCell', 'tableHeader'].includes(anchor.node(depth).type.name)) {
                cellId = anchor.node(depth).attrs.id; cellPos = anchor.before(depth);
            }
        }
        const grid = core.tableCells(table);
        const entry = grid.cells.find(item => item.cell.attrs.id === cellId) || grid.cells[0];
        const selected = [];
        if (selection.$anchorCell && typeof selection.forEachCell === 'function')
            selection.forEachCell(cell => selected.push(cell.attrs.id));
        return { ...context, table, tableId: table.attrs.id, cellId: entry?.cell.attrs.id,
            row: entry?.row || 0, column: entry?.column || 0, rowId: entry?.rowId,
            columnId: table.attrs.columns[entry?.column || 0].id,
            offset: cellPos == null ? 2 : Math.max(2, selection.from - cellPos),
            cellIds: selected.length ? selected : entry ? [entry.cell.attrs.id] : [],
            cellSelection: selected.length >= 2 };
    }
    function restoreCaret(caret) {
        if (!caret) { editor.commands.focus('end'); return; }
        const json = editor.getJSON();
        const table = json.content?.find(node => node.type === 'table' && node.attrs.id === caret.tableId);
        if (table) {
            const { cells, grid } = core.tableCells(table);
            const found = cells.find(item => item.cell.attrs.id === caret.cellId)
                || grid[Math.min(caret.row || 0, grid.length - 1)]?.[Math.min(caret.column || 0, table.attrs.columns.length - 1)]
                || cells[0];
            let position = null;
            editor.state.doc.descendants((node, pos) => {
                if (node.attrs.id !== found?.cell.attrs.id) return;
                const offset = Math.min(caret.offset || 2, node.nodeSize - 2);
                const candidate = pos + Math.max(2, offset);
                position = editor.state.doc.resolve(candidate).parent.inlineContent ? candidate : pos + 2;
            });
            if (position != null) { editor.commands.focus(position); return; }
        }
        // A deleted table leaves its nearest following paragraph, or the preceding block's end.
        let position = 0;
        const index = Math.min(caret.topLevelIndex || 0, editor.state.doc.childCount);
        for (let i = 0; i < index; i++) position += editor.state.doc.child(i).nodeSize;
        editor.commands.focus(Math.min(position, editor.state.doc.content.size));
    }
    function lockTableAction(locked) {
        tableBusy = locked;
        done.disabled = cancel.disabled = overwrite.disabled = discard.disabled = locked;
        for (const control of toolbar.querySelectorAll('button,input,select')) control.disabled = locked;
        editor.setEditable(!locked, false);
        if (!locked) refreshControls();
    }
    async function runTableAction(build) {
        if (tableBusy || saving || disposed || composing || editor.view.composing) return;
        const caret = tableContext();
        lockTableAction(true);
        let fresh = null;
        try {
            if (dirty) {
                // Use the existing save path, including conflict handling and teardown.
                fresh = await save(false);
                if (!fresh) return;
            } else {
                fresh = await options.read();
                const current = options.findField(fresh);
                if (!current || current.contentHash !== originalHash) {
                    notice('This field changed elsewhere. Your draft is kept. Choose how to continue.', true);
                    return;
                }
            }
            const current = options.findField(fresh);
            if (!current || core.readOnlyReason(current) || !fresh.documentationRichText
                || !current.capabilities?.includes('replace_rich_text')) throw Error('This field is no longer editable.');
            // New paragraph IDs are allocated by save; insertion uses the freshly stored top-level ID.
            caret.afterId = core.tableAfterId(current.richText?.doc || {}, caret.topLevelIndex);
            const operation = build(caret);
            if (!disposed) message.textContent = 'Updating table...';
            const response = await options.tableOperation(fresh, current, operation);
            const identity = response.receipt?.operationResults?.[0]?.table;
            if (operation.operation === 'create_table' && identity) Object.assign(caret, {
                tableId: identity.tableId, cellId: identity.rows[0].cellIds[0], row: 0, column: 0, offset: 2 });
            fresh = await options.read();
            if (!disposed) close(false);
            await options.remount(fresh, caret);
        } catch (error) {
            if (disposed && fresh) await options.remount(fresh, caret, error.message);
            else if (!disposed) notice(error.message);
        } finally {
            if (!disposed) lockTableAction(false);
        }
    }
    function tableAction(build) {
        if (tableBusy) return;
        tableFlight = runTableAction(build).catch(error => options.onError?.(error))
            .finally(() => { tableFlight = null; });
    }
    if (allows('table') && capabilities.schemaVersions.includes(3)) {
        tablePanel = document.createElement('div');
        tablePanel.className = 'documentation-table-menu'; tablePanel.hidden = true;
        tablePanel.setAttribute('role', 'dialog'); tablePanel.setAttribute('aria-label', 'Table menu');
        tableToggle = button(toolbar, 'Table', () => {
            if (tableBusy) return;
            if (tablePanel.hidden && symbols.hidden) notePanelOrigin();
            tablePanel.hidden = !tablePanel.hidden; symbols.hidden = true;
            symbolToggle.setAttribute('aria-expanded', 'false');
            tableToggle.setAttribute('aria-expanded', String(!tablePanel.hidden));
            const rect = tableToggle.getBoundingClientRect();
            tablePanel.style.top = Math.max(8, Math.min(rect.bottom + 4, window.innerHeight - 450)) + 'px';
            tablePanel.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - 390)) + 'px';
            refreshControls();
            if (!tablePanel.hidden) rows.focus();
        });
        tableToggle.setAttribute('aria-expanded', 'false');
        tableToggle.setAttribute('aria-haspopup', 'dialog');
        const title = document.createElement('strong'); title.textContent = 'Insert table'; tablePanel.appendChild(title);
        function input(label, type, min, max, value) {
            const wrapper = document.createElement('label'), control = document.createElement('input');
            wrapper.textContent = label + ' '; control.type = type; control.setAttribute('aria-label', label);
            if (min != null) { control.min = String(min); control.max = String(max); control.step = '1'; }
            if (type === 'checkbox') control.checked = value; else control.value = String(value);
            wrapper.appendChild(control); tablePanel.appendChild(wrapper); return control;
        }
        const rows = input('Rows', 'number', 1, 50, 3), columns = input('Columns', 'number', 1, 12, 3);
        const header = input('Header row', 'checkbox', null, null, true);
        button(tablePanel, 'Insert', () => {
            if (!rows.checkValidity() || !columns.checkValidity() || !rows.value || !columns.value) {
                notice('Enter 1-50 rows and 1-12 columns.'); return;
            }
            const count = Number(rows.value), width = Number(columns.value), headerRow = header.checked;
            tableAction(context => ({ operation: 'create_table', rows: count, columns: width, headerRow,
                ...(context.afterId ? { afterId: context.afterId } : {}) }));
        }, 'insert-table');
        const current = document.createElement('div'); current.className = 'documentation-table-current';
        tablePanel.appendChild(current);
        const modify = (action, fields = () => ({})) => tableAction(context => ({
            operation: 'modify_table', tableId: context.tableId, action, ...fields(context) }));
        function command(label, action, fields, enabled = context => Boolean(context.table)) {
            const control = button(current, label, () => {
                if (enabled(tableContext())) modify(action, fields);
            });
            stateControls.push(() => {
                control.disabled = tableBusy || !enabled(tableContext());
                control.setAttribute('aria-disabled', String(control.disabled));
            });
            return control;
        }
        for (const [label, action, position] of [
            ['Insert row above', 'insert_row', 'before'], ['Insert row below', 'insert_row', 'after'],
            ['Insert column left', 'insert_column', 'before'], ['Insert column right', 'insert_column', 'after']])
            command(label, action, context => ({ [action === 'insert_row' ? 'rowId' : 'columnId']:
                action === 'insert_row' ? context.rowId : context.columnId, position }));
        command('Delete row', 'delete_row', context => ({ rowId: context.rowId }));
        command('Delete column', 'delete_column', context => ({ columnId: context.columnId }));
        command('Delete table', 'delete_table');
        command('Merge cells', 'merge_cells', context => ({ cellIds: context.cellIds }),
            context => context.cellSelection);
        command('Split cell', 'split_cells', context => ({ cellIds: [context.cellId] }),
            context => {
                const cell = context.table && core.tableCells(context.table).cells.find(c => c.cell.attrs.id === context.cellId)?.cell;
                return cell && ((cell.attrs.colspan || 1) > 1 || (cell.attrs.rowspan || 1) > 1);
            });
        function selectedCells(context) {
            return context.table ? core.tableCells(context.table).cells.filter(c => context.cellIds.includes(c.cell.attrs.id)).map(c => c.cell) : [];
        }
        const headerCell = command('Header cell', 'set_cell_style', context => ({
            cellIds: context.cellIds, style: { header: !selectedCells(context).every(cell => cell.type === 'tableHeader') } }));
        stateControls.push(() => headerCell.setAttribute('aria-pressed',
            String(selectedCells(tableContext()).length > 0 && selectedCells(tableContext()).every(c => c.type === 'tableHeader'))));
        const fill = input('Fill', 'color', null, null, '#e9eef2');
        current.appendChild(fill.parentElement);
        const fillText = input('Fill hex', 'text', null, null, '');
        current.appendChild(fillText.parentElement);
        function applyFill(value) {
            if (!/^#[0-9a-f]{6}$/i.test(value)) { notice('Enter a six-digit fill color such as #cceeff.'); return; }
            modify('set_cell_style', context => ({ cellIds: context.cellIds, style: { fill: value.toLowerCase() } }));
        }
        listen(fill, 'change', () => applyFill(fill.value));
        listen(fillText, 'change', () => applyFill(fillText.value));
        stateControls.push(() => {
            const cells = selectedCells(tableContext()), color = shared(cells.map(c => c.attrs.fill || null));
            fill.disabled = fillText.disabled = tableBusy || !cells.length; fill.value = color || '#e9eef2';
            if (document.activeElement !== fillText) fillText.value = color || '';
        });
        command('No fill', 'set_cell_style', context => ({ cellIds: context.cellIds, style: { fill: null } }));
        for (const align of ['top', 'middle', 'bottom']) {
            const control = command('Align ' + align, 'set_cell_style', context => ({
                cellIds: context.cellIds, style: { verticalAlign: align } }));
            stateControls.push(() => {
                const cells = selectedCells(tableContext());
                control.setAttribute('aria-pressed', String(cells.length > 0 && cells.every(c => (c.attrs.verticalAlign || 'top') === align)));
            });
        }
        const borders = command('Borders', 'set_table_style', context => ({
            style: context.table.attrs.style === 'grid' ? 'plain' : 'grid' }));
        stateControls.push(() => borders.setAttribute('aria-pressed', String(tableContext().table?.attrs.style === 'grid')));
        const percent = input('Column width', 'number', 1, 99, 33);
        current.appendChild(percent.parentElement);
        stateControls.push(() => {
            const context = tableContext();
            percent.disabled = tableBusy || !context.table;
            if (document.activeElement !== percent) percent.value = context.table
                ? String(Math.round(context.table.attrs.columns[context.column].width / 10)) : '';
        });
        command('Apply', 'set_widths', context => {
            if (!percent.value || !percent.checkValidity()) throw Error('Enter a whole percent from 1 to 99.');
            const widths = core.tableWidths(context.table.attrs.columns, context.columnId, Number(percent.value));
            return { widths: context.table.attrs.columns.map((c, i) => ({ columnId: c.id, width: widths[i] })) };
        });
        command('Equal widths', 'set_widths', context => {
            const widths = core.equalTableWidths(context.table.attrs.columns);
            return { widths: context.table.attrs.columns.map((c, i) => ({ columnId: c.id, width: widths[i] })) };
        });
        stateControls.push(() => { current.hidden = !tableContext().table; });
        toolbar.appendChild(tablePanel);
    }

    for (const host of [element, panel, toolbar]) {
        listen(host, 'keydown', event => {
            if (event.key === 'Escape') {
                event.preventDefault();
                if (tablePanel && !tablePanel.hidden) {
                    tablePanel.hidden = true; tableToggle.setAttribute('aria-expanded', 'false'); leavePanel(tableToggle);
                } else if (!symbols.hidden) {
                    symbols.hidden = true; symbolToggle.setAttribute('aria-expanded', 'false'); leavePanel(symbolToggle);
                } else if (!saving && !tableBusy) close();
            }
            event.stopPropagation();
        });
        listen(host, 'pointerdown', event => event.stopPropagation());
        listen(host, 'dblclick', event => event.stopPropagation());
        listen(host, 'focusout', () => {
            clearTimeout(blurTimer);
            blurTimer = setTimeout(() => {
                if (!disposed && !controller.ownsFocus(document.activeElement)) commit(false);
            }, 0);
        });
    }
    const surface = element.closest('#documentationPublicationSurface');
    if (surface) listen(surface, 'pointerdown', event => {
        if (element.contains(event.target)) return;
        // A press elsewhere on the page ends editing like Done (canvas convention) and does nothing
        // else: it never selects another object while keys still go to this editor.
        event.preventDefault();
        event.stopPropagation();
        void commit(false);
    }, true);
    listen(window, 'pagehide', () => close(false));
    listen(editorHost, 'compositionstart', () => { composing = true; });
    listen(editorHost, 'compositionend', () => {
        composing = false;
        // ProseMirror finishes the composition transaction before the pending save.
        if (pendingCommit) {
            pendingCommit = false;
            clearTimeout(blurTimer);
            blurTimer = setTimeout(() => commit(false), 30);
        }
    });
    notice('Edit text, then choose Done.');
    restoreCaret(options.restoreCaret);
    refreshControls();
    return controller;
}
