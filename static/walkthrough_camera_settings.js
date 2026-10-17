(function(root, factory) {
    'use strict';
    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProWalkthroughCamera = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function(root) {
    'use strict';
    const KEY = 'inspectorpro.walkthrough-camera.v1';
    const PRESETS = Object.freeze({
        close: Object.freeze({distance: 3, height: 0.15}),
        standard: Object.freeze({distance: 5, height: 0.5}),
        wide: Object.freeze({distance: 9, height: 1.5}),
    });
    let memory = {...PRESETS.standard};
    let sessionOnly = false;
    function number(value, min, max, fallback) {
        return typeof value === 'number' && Number.isFinite(value)
            ? Math.round(Math.max(min, Math.min(max, value))*100)/100 : fallback;
    }
    function normalize(value) {
        const v = value && typeof value === 'object' ? value : {};
        return {distance:number(v.distance, 2.5, 14, 5), height:number(v.height, 0, 3, 0.5)};
    }
    function storage() { try { return root.localStorage; } catch (_) { return null; } }
    function load(store = storage()) {
        if (sessionOnly) return {...memory};
        try {
            const value = store && store.getItem(KEY);
            if (value) memory = normalize(JSON.parse(value));
        } catch (_) { /* Restricted or corrupt storage must not disable walking. */ }
        return {...memory};
    }
    function save(value, store = storage()) {
        memory = normalize(value);
        try {
            if (store) store.setItem(KEY, JSON.stringify(memory));
            sessionOnly = !store;
        } catch (_) { sessionOnly = true; }
        return {...memory};
    }
    function zoom(value, event) {
        const v = normalize(value);
        if (!event || event.ctrlKey || !Number.isFinite(event.deltaY)) return v;
        const pixels = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 800 : 1);
        return normalize({...v, distance:v.distance + Math.max(-1.5, Math.min(1.5, pixels*.005))});
    }
    function preset(value) {
        const v = normalize(value);
        return Object.keys(PRESETS).find(k => PRESETS[k].distance === v.distance && PRESETS[k].height === v.height) || null;
    }
    function createControl({document:doc, button, onChange, onOpen}) {
        let value = load();
        let rendered = false;
        const panel = doc.createElement('section');
        panel.className = 'ip-walk-camera-panel';
        panel.hidden = true;
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-label', 'Walkthrough camera settings');
        panel.innerHTML = '<header><strong>Walkthrough camera</strong><button type="button" data-camera-reset title="Reset camera settings" aria-label="Reset camera settings">'
            + '<img src="/static/assets/facility-layout-ribbon-icons/svg/arrow-clockwise.svg" alt=""></button></header>'
            + '<div class="ip-walk-camera-presets" role="group" aria-label="Camera preset">'
            + ['close','standard','wide'].map(k => '<button type="button" data-camera-preset="'+k+'">'+k[0].toUpperCase()+k.slice(1)+'</button>').join('')+'</div>'
            + '<label>Follow distance <output data-camera-output="distance"></output><input aria-label="Follow distance" data-camera-field="distance" type="range" min="2.5" max="14" step="0.1"></label>'
            + '<label>Camera rise <output data-camera-output="height"></output><input aria-label="Camera rise" data-camera-field="height" type="range" min="0" max="3" step="0.05"></label>';
        doc.body.appendChild(panel);
        button.setAttribute('aria-haspopup', 'dialog');
        button.setAttribute('aria-expanded', 'false');
        function sync(next) {
            const normalized = normalize(next);
            if (rendered && normalized.distance === value.distance && normalized.height === value.height) return;
            value = normalized; rendered = true;
            panel.querySelectorAll('[data-camera-preset]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.cameraPreset === preset(value))));
            panel.querySelectorAll('[data-camera-field]').forEach(input => { input.value = value[input.dataset.cameraField]; });
            panel.querySelectorAll('[data-camera-output]').forEach(output => { output.textContent = value[output.dataset.cameraOutput].toFixed(2).replace(/0$/, '') + ' m'; });
        }
        function change(next) { sync(save(next)); onChange({...value}); }
        function close(focus) {
            panel.hidden = true; button.setAttribute('aria-expanded','false');
            if (focus) button.focus();
        }
        function position() {
            if (panel.hidden) return;
            const rect = button.getBoundingClientRect(), win = doc.defaultView;
            const width = panel.getBoundingClientRect().width;
            panel.style.left = Math.max(8, Math.min(rect.left, win.innerWidth-width-8))+'px';
            panel.style.top = Math.max(8, Math.min(rect.bottom+6, win.innerHeight-panel.getBoundingClientRect().height-8))+'px';
        }
        function toggle(event) {
            event.preventDefault(); event.stopPropagation();
            if (!panel.hidden) return close(true);
            if (onOpen) onOpen();
            sync(load()); panel.hidden=false; button.setAttribute('aria-expanded','true'); position();
            panel.querySelector('[data-camera-preset]').focus();
        }
        function click(event) {
            const p = event.target.closest('[data-camera-preset]');
            if (p) change(PRESETS[p.dataset.cameraPreset]);
            if (event.target.closest('[data-camera-reset]')) change(PRESETS.standard);
            event.stopPropagation();
        }
        function input(event) { if (event.target.dataset.cameraField) change({...value,[event.target.dataset.cameraField]:Number(event.target.value)}); }
        function outside(event) { if (!panel.contains(event.target) && !button.contains(event.target)) close(false); }
        function keys(event) {
            if (!panel.hidden && event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); close(true); }
        }
        button.addEventListener('click',toggle);
        panel.addEventListener('click',click); panel.addEventListener('input',input);
        doc.addEventListener('pointerdown',outside); doc.addEventListener('keydown',keys,true);
        doc.defaultView.addEventListener('resize',position);
        const observer = doc.defaultView.ResizeObserver ? new doc.defaultView.ResizeObserver(() => {
            if (!button.getClientRects().length) close(false); else position();
        }) : null;
        if (observer) observer.observe(button);
        sync(value);
        return {panel, sync, close, dispose() {
            button.removeEventListener('click',toggle);
            panel.removeEventListener('click',click); panel.removeEventListener('input',input);
            doc.removeEventListener('pointerdown',outside); doc.removeEventListener('keydown',keys,true);
            doc.defaultView.removeEventListener('resize',position);
            if (observer) observer.disconnect();
            panel.remove();
        }};
    }
    return {KEY, PRESETS, normalize, load, save, zoom, preset, createControl};
}));
