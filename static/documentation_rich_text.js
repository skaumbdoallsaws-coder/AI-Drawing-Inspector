/* One authored region; all persistence goes through the scene command callback. */
const core = window.DocumentationRichTextCore;
let kit = null;
let active = null;
const api = {
    ready: null,
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
api.ready = import('/static/vendor/tiptap/tiptap.bundle.js?v=c36fd989775f').then(
    ({ Editor, Extension, StarterKit, TextStyle, Color }) => {
        if (!core || !Editor || !Extension || !StarterKit || !TextStyle || !Color) {
            return { ok: false, reason: 'The rich text editor is unavailable.' };
        }
        kit = { Editor, Extension, StarterKit, TextStyle, Color };
        return { ok: true, reason: '' };
    }, () => ({ ok: false, reason: 'The rich text editor could not load. This field is read-only.' })
).then(status => {
    api.status = status;
    window.dispatchEvent(new CustomEvent('documentation-rich-ready'));
    return status;
});

// Only the validated read envelope is rendered here. No HTML strings or URL navigation.
function render(element, envelope) {
    const tags = { paragraph: 'p', bulletList: 'ul', orderedList: 'ol', listItem: 'li', hardBreak: 'br' };
    function node(value) {
        if (value.type === 'text') {
            let child = document.createElement('span');
            child.textContent = value.text;
            for (const mark of value.marks || []) {
                const tag = { bold: 'strong', italic: 'em', underline: 'u', textStyle: 'span', link: 'a' }[mark.type];
                if (!tag) continue;
                const wrapper = document.createElement(tag);
                if (mark.type === 'textStyle') wrapper.style.color = core?.color(mark.attrs?.color) || '';
                if (mark.type === 'link') {
                    const href = core?.href(mark.attrs?.href);
                    if (!href) continue;
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
        if (value.type === 'orderedList') result.start = value.attrs.start;
        result.style.whiteSpace = 'pre-wrap';
        if (['paragraph', 'heading', 'bulletList', 'orderedList'].includes(value.type)) result.style.margin = '0';
        if (value.type === 'paragraph' && !value.content?.length) result.appendChild(document.createElement('br'));
        for (const child of value.content || []) result.appendChild(node(child));
        return result;
    }
    element.replaceChildren();
    for (const child of envelope.doc.content || []) element.appendChild(node(child));
}

function mount(element, options) {
    if (!kit || !core || active || !element) return null;
    const { Editor, Extension, StarterKit, TextStyle, Color } = kit;
    const field = options.field;
    const originalHash = field.contentHash;
    let composing = false, pendingCommit = false, saving = false, disposed = false, conflict = false;
    let blurTimer = null, dirty = false, inflight = null;
    let initialJSON;
    const listeners = [];
    function listen(target, event, fn, capture = false) {
        target.addEventListener(event, fn, capture);
        listeners.push(() => target.removeEventListener(event, fn, capture));
    }
    const originalNodes = [...element.childNodes];
    element.replaceChildren();
    element.classList.add('documentation-rich-mounted');
    const editorHost = document.createElement('div');
    editorHost.className = 'documentation-rich-editor';
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
    const cancel = button(actions, 'Cancel', () => { if (!saving) close(); }, 'cancel');
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
    let editor;
    try {
        editor = new Editor({
            element: editorHost,
            extensions: [StarterKit.configure({
                code: false, codeBlock: false, blockquote: false, horizontalRule: false, strike: false,
                heading: { levels: [1, 2, 3] }, trailingNode: false,
                link: { openOnClick: false, autolink: false, linkOnPaste: false,
                    isAllowedUri: value => Boolean(core.href(value)), HTMLAttributes: core.LINK },
            }), TextStyle, Color, identities],
            content: field.richText?.doc || core.fromPlain(field.text).doc,
            parseOptions: { preserveWhitespace: 'full' },
            editorProps: {
                attributes: { 'aria-label': 'Rich text editor', role: 'textbox', 'aria-multiline': 'true' },
                handlePaste(view, event) {
                    if (event.clipboardData?.getData('text/html')) return false;
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
            onUpdate() {
                dirty = JSON.stringify(editor.getJSON()) !== initialJSON;
                if (!conflict) message.textContent = dirty ? 'Draft not yet saved.' : 'Edit text, then choose Done.';
            },
        });
    } catch (error) {
        panel.remove(); element.classList.remove('documentation-rich-mounted');
        element.replaceChildren(...originalNodes);
        options.onError?.(error);
        return null;
    }
    initialJSON = JSON.stringify(editor.getJSON());
    const controller = {
        element, editor, pageId: field.pageId, targetId: field.targetId,
        get dirty() { return dirty; },
        get composing() { return composing; },
        get saving() { return saving; },
        controls() { return [toolbar]; },
        reconcile(snapshot) {
            if (disposed || saving) return;
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
            if (inflight) { await inflight; return disposed; }
            if (!disposed && !conflict) await commit(false);
            return disposed;
        },
        cancel: () => close(),
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
        element.classList.remove('documentation-rich-mounted');
        element.replaceChildren(...originalNodes);
        if (active === controller) active = null;
        if (notify) options.onClose?.();
    }
    function commit(overwriteNewer = false) {
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
            core.normalize(editor.getJSON(), { reservedIds: core.reservedIds(options.snapshot.richTextFields, field) });
            const snapshot = await options.read();
            if (disposed) return;
            const current = options.findField(snapshot);
            if (!current || (!overwriteNewer && current.contentHash !== originalHash)) {
                notice('This field changed elsewhere. Your draft is kept. Choose how to continue.', true);
                return;
            }
            if (!snapshot.documentationRichText || !current.capabilities?.includes('replace_rich_text')) {
                notice('This field is no longer editable. Your draft is kept.'); return;
            }
            const richText = core.normalize(editor.getJSON(), {
                reservedIds: core.reservedIds(snapshot.richTextFields, current),
            });
            await options.commit(snapshot, current, richText);
            if (disposed) return;
            // The POST body is fully consumed before a GET or any teardown/reload.
            const fresh = await options.read();
            if (disposed) return;
            close(false); options.apply(fresh); options.onClose?.();
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
            done.disabled = overwrite.disabled = cancel.disabled = false;
        }
    }
    function mark(command, argument) {
        if (disposed || saving) return;
        editor.chain().focus()[command](argument).run();
    }
    button(toolbar, 'Bold', () => mark('toggleBold'));
    button(toolbar, 'Italic', () => mark('toggleItalic'));
    button(toolbar, 'Underline', () => mark('toggleUnderline'));
    const color = document.createElement('input');
    color.type = 'color'; color.title = 'Text color'; color.setAttribute('aria-label', 'Text color');
    listen(color, 'input', () => mark('setColor', color.value));
    toolbar.appendChild(color);
    for (let level = 1; level <= 3; level++) button(toolbar, 'H' + level, () => mark('toggleHeading', { level }));
    button(toolbar, 'Bullets', () => mark('toggleBulletList'));
    button(toolbar, 'Numbering', () => mark('toggleOrderedList'));
    const link = document.createElement('input');
    link.type = 'url'; link.placeholder = 'https://example.com'; link.setAttribute('aria-label', 'HTTP or HTTPS link');
    toolbar.appendChild(link);
    button(toolbar, 'Link', () => {
        const href = core.href(link.value);
        if (!href) { notice('Enter an absolute http:// or https:// link.'); return; }
        mark('setLink', { href });
    });
    button(toolbar, 'Unlink', () => mark('unsetLink'));
    for (const host of [element, panel, toolbar]) {
        listen(host, 'keydown', event => {
            if (event.key === 'Escape') { event.preventDefault(); if (!saving) close(); }
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
    editor.commands.focus('end');
    return controller;
}
