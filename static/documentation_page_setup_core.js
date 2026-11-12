/* Paper labels and refusal summaries: no DOM and no inferred capabilities. */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.DocumentationPageSetupCore = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
    'use strict';
    const number = value => String(Math.round(Number(value) * 100) / 100);
    function name(value) { return value ? value.paper + ' ' + value.orientation : 'design page'; }
    function label(preset) {
        const millimetres = preset.paper === 'A4';
        const unit = millimetres ? 25.4 / 72 : 1 / 72;
        const dimension = v => number(Math.round(v * unit * 10) / 10);
        return name(preset) + ' (' + dimension(preset.page.width) + ' x '
            + dimension(preset.page.height) + (millimetres ? ' mm)' : ' in)');
    }
    function designLabel(design) { return 'Design page (' + number(design.width) + ' x ' + number(design.height) + ' pt)'; }
    const reasons = {text_does_not_fit: 'text does not fit', outside_page: 'outside the page',
        column_too_narrow: 'column too narrow', row_too_small: 'row too small'};
    function refusal(value, message, details, describe) {
        const targets = details?.targets || [];
        if (!targets.length) return message;
        const count = Number(details.count) || targets.length;
        const names = targets.slice(0, 3).map(item => {
            const resolved = describe(item) || {};
            return 'Page ' + (resolved.pageNumber ?? item.pageNumber ?? item.pageId) + ': '
                + (resolved.name || reasons[item.reason] || item.reason);
        });
        return name(value).replace(/^design/, 'Design') + ' was not applied: ' + count
            + (count === 1 ? ' item does not fit (' : ' items do not fit (') + names.join('; ')
            + (count > names.length ? '; and ' + (count - names.length) + ' more' : '') + ').';
    }
    return {name, label, designLabel, refusal};
});
