(function (root) {
    'use strict';
    const base = '/static/assets/facility-ribbon-dimensional/';
    const packaging = '/static/assets/packaging-ribbon-icons/';
    const primary = Object.freeze({
        'rectangle-zone': base + 'zones-v1.png',
        aisle: base + 'aisle-v1.png',
        'interior-walls': base + 'walls-v1.png',
        align: base + 'position-v1.png',
        'linear-pattern': base + 'patterns-v1.png',
        'cell-layout': base + 'cells-v1.png',
        'vertical-stack': base + 'stack-v1.png',
        appearance: packaging + 'appearance-glossy-v1.png',
        'auto-arrange': packaging + 'arrange-glossy-v1.png',
        undo: packaging + 'undo-glossy-v1.png',
        redo: packaging + 'redo-glossy-v1.png',
        save: packaging + 'save-glossy-v1.png',
    });
    const api = Object.freeze({
        primary,
        source(command, small = false) {
            return (!small && primary[command]) || base + command + '.svg';
        },
        apply(button, command, small = false) {
            const old = button.querySelector(':scope > .documentation-system-icon, :scope > .documentation-command-icon');
            if (!old) return;
            const icon = document.createElement('span');
            icon.className = 'documentation-system-icon facility-dimensional-icon';
            icon.dataset.facilityIcon = command;
            icon.setAttribute('aria-hidden', 'true');
            const img = document.createElement('img');
            img.src = api.source(command, small);
            img.alt = '';
            img.draggable = false;
            icon.appendChild(img);
            old.replaceWith(icon);
        },
    });
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.FacilityRibbonIcons = api;
})(typeof window !== 'undefined' ? window : globalThis);
