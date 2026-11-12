const test = require('node:test');
const assert = require('node:assert/strict');
const core = require('../static/documentation_page_setup_core.js');

test('paper labels are derived from advertised dimensions', () => {
    for (const [paper, orientation, width, height, expected] of [
        ['Letter', 'landscape', 792, 612, 'Letter landscape (11 x 8.5 in)'],
        ['Letter', 'portrait', 612, 792, 'Letter portrait (8.5 x 11 in)'],
        ['A4', 'landscape', 841.89, 595.28, 'A4 landscape (297 x 210 mm)'],
        ['A4', 'portrait', 595.28, 841.89, 'A4 portrait (210 x 297 mm)'],
        ['Letter', 'landscape', 720, 576, 'Letter landscape (10 x 8 in)'],
    ]) assert.equal(core.label({paper, orientation, page: {width, height}}), expected);
    assert.equal(core.designLabel({width: 960, height: 540}), 'Design page (960 x 540 pt)');
    assert.equal(core.name(null), 'design page');
});

test('refusals use supplied names, bound context and at most three targets', () => {
    const value = {paper: 'A4', orientation: 'landscape'};
    const targets = [
        {pageId: 'a', reason: 'text_does_not_fit'}, {pageId: 'b', reason: 'column_too_narrow'},
        {pageId: 'c', reason: 'outside_page'}, {pageId: 'd', reason: 'row_too_small'},
    ];
    const describe = t => t.pageId === 'a' ? {pageNumber: 12, name: 'Paper fit'} : {pageNumber: 14};
    assert.equal(core.refusal(value, 'server', {count: 8, targets}, describe),
        'A4 landscape was not applied: 8 items do not fit (Page 12: Paper fit; Page 14: column too narrow; Page 14: outside the page; and 5 more).');
    assert.equal(core.refusal(null, 'compiler reason', {}, describe), 'compiler reason');
    assert.equal(core.refusal(null, 'server', {targets: targets.slice(3)}, describe),
        'Design page was not applied: 1 item does not fit (Page 14: row too small).');
});
