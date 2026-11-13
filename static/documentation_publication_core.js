/* Publication text rules shared by the canvas and static tests. No DOM or storage. */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.DocumentationPublicationCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    function fitFontSize(fontSize, available, measured) {
        // parts_manual.pdf._fit_text: the caller supplies rect.width minus 2 pt.
        return Math.max(4.5, fontSize * Math.min(1, Math.max(1, available) / Math.max(1, measured) * .96));
    }
    function partsHeading(page, override = {}) {
        if (Object.hasOwn(override, 'text')) return String(override.text ?? '');
        if (page.pageType === 'cover') return 'ILLUSTRATED PARTS MANUAL';
        const figure = String(page.figureNumber || '').trim(), title = String(page.title || '');
        return figure ? 'FIGURE ' + figure + ' - ' + title : title.toUpperCase();
    }
    return {fitFontSize, partsHeading};
});
