const test = require('node:test');
const assert = require('node:assert/strict');
const core = require('../static/documentation_publication_core.js');

test('PDF width fitting keeps its margin, floor and original maximum', () => {
    assert.equal(core.fitFontSize(6.6, 200, 100), 6.6);
    assert.equal(core.fitFontSize(10, 100, 200), 4.8);
    assert.equal(core.fitFontSize(6.6, 8, 200), 4.5);
    assert.equal(core.fitFontSize(10, 100, 100), 9.6);
    assert.equal(core.fitFontSize(10, 100, 0), 10);
    assert.equal(core.fitFontSize(10, -1, 100), 4.5);
});
test('parts headings uppercase only the unedited non-figure default', () => {
    const page = {title: 'Table of Contents'};
    assert.equal(core.partsHeading(page), 'TABLE OF CONTENTS');
    assert.equal(core.partsHeading({...page, figureNumber: '2'}), 'FIGURE 2 - Table of Contents');
    assert.equal(core.partsHeading({...page, pageType: 'cover'}), 'ILLUSTRATED PARTS MANUAL');
    for (const value of ['Author Typed', '', 'mIxEd Case']) {
        assert.equal(core.partsHeading(page, {text: value}), value);
        assert.equal(core.partsHeading({...page, figureNumber: '2'}, {text: value}), value);
    }
    assert.deepEqual(page, {title: 'Table of Contents'});
});
