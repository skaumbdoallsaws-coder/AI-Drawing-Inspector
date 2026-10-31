'use strict';

const assert = require('assert');
const rich = require('../static/chat_rich_content.js');

let passed = 0;
function test(name, fn) {
    try {
        fn();
        passed += 1;
        console.log('PASS ' + name);
    } catch (error) {
        console.error('FAIL ' + name + ': ' + error.message);
        process.exitCode = 1;
    }
}

test('markdown supports engineering tables and common formatting', () => {
    const html = rich.renderMarkdownHtml([
        '## Results',
        '',
        '| Feature | Value |',
        '| --- | ---: |',
        '| Bore | **25 mm** |',
        '',
        '- Verified',
        '- Traceable',
        '',
        '`M12`',
    ].join('\n'));
    assert(html.includes('<h2>Results</h2>'));
    assert(html.includes('<table>'));
    assert(html.includes('<strong>25 mm</strong>'));
    assert(html.includes('<ul>'));
    assert(html.includes('<code>M12</code>'));
});

test('markdown escapes raw HTML and rejects script URLs', () => {
    const html = rich.renderMarkdownHtml(
        '<script>globalThis.pwned=true</script> [unsafe](javascript:alert(1))'
    );
    assert(html.includes('&lt;script&gt;'));
    assert(!html.includes('<script>'));
    assert(!html.includes('javascript:'));
    assert(html.includes('unsafe'));
});

test('engineering exponents are typeset outside code literals', () => {
    const html = rich.renderMarkdownHtml(
        'Area is 60 m^2 and volume is 8 ft^3. Use `m^2` in the API.'
    );
    assert(html.includes('60 m\u00B2'));
    assert(html.includes('8 ft\u00B3'));
    assert(html.includes('<code>m^2</code>'));
    assert.strictEqual(rich.formatEngineeringUnit('m2'), 'm\u00B2');
    assert.strictEqual(rich.formatEngineeringUnit('kg/m2'), 'kg/m\u00B2');
});

test('URL policy rejects unqualified and unsafe values', () => {
    assert.strictEqual(rich.safeUrl('supplier.example/product'), null);
    assert.strictEqual(rich.safeUrl('data:text/html,bad'), null);
    assert.strictEqual(rich.safeUrl('/api/drawing'), '/api/drawing');
    assert.strictEqual(rich.safeUrl('https://example.com/a'), 'https://example.com/a');
});

test('source normalization adds registered identity and bounds specifications', () => {
    const source = rich.normalizeSource({
        title: '6205 bearing',
        url: 'https://www.skf.com/products/6205',
        specifications: Object.fromEntries(
            Array.from({ length: 12 }, (_, index) => ['k' + index, index])
        ),
    }, 0);
    assert.strictEqual(source.publisher, 'SKF');
    assert.strictEqual(source.domain, 'skf.com');
    assert(source.iconUrl.endsWith('/favicon.ico'));
    assert.strictEqual(Object.keys(source.specifications).length, 8);
});

test('structured blocks reject unknown blocks and arbitrary actions', () => {
    const blocks = rich.normalizeBlocks([
        { type: 'unknown', html: '<b>bad</b>' },
        { type: 'actions', actions: [
            { actionId: 'run_arbitrary_code', entityId: 'x' },
            { actionId: 'show_in_3d', entityId: 'asset_cnc_04', label: 'Show in 3D' },
        ] },
    ]);
    assert.strictEqual(blocks.length, 1);
    assert.strictEqual(blocks[0].actions.length, 1);
    assert.strictEqual(blocks[0].actions[0].actionId, 'show_in_3d');
});

test('visualization specs are bounded and restricted', () => {
    assert.strictEqual(rich.normalizeVisualization({ type: 'javascript', data: [{}] }), null);
    const chart = rich.normalizeVisualization({
        type: 'pareto',
        title: 'Scrap by reason',
        data: Array.from({ length: 240 }, (_, index) => ({ reason: 'R' + index, count: index })),
        encoding: { x: 'reason', y: 'count' },
    });
    assert.strictEqual(chart.type, 'pareto');
    assert.strictEqual(chart.data.length, 200);
});

test('chart labels wrap within their category slots', () => {
    const automation = rich.chartLabelLines(
        'Automation + Robot cells',
        51,
        3
    );
    const finishedGoods = rich.chartLabelLines(
        'Inspection + Packing + Finished goods',
        51,
        3
    );
    assert(automation.length > 1 && automation.length <= 3);
    assert(finishedGoods.length > 1 && finishedGoods.length <= 3);
    assert(automation.every(line => line.length <= 12));
    assert(finishedGoods.every(line => line.length <= 12));
});

test('Pareto cumulative series reaches 100 percent in sorted order', () => {
    const ratios = rich.paretoCumulativeRatios([60, 30, 10]);
    assert.deepStrictEqual(
        ratios.map(value => Math.round(value * 100)),
        [60, 90, 100]
    );
    assert.deepStrictEqual(rich.paretoCumulativeRatios([0, 0]), [0, 0]);
});

test('pie and heatmap specifications preserve their structured semantics', () => {
    assert(rich.VISUALIZATION_TYPES.includes('pie'));
    assert(rich.VISUALIZATION_TYPES.includes('donut'));
    assert(rich.VISUALIZATION_TYPES.includes('heatmap'));
    assert.deepStrictEqual(
        rich.pieSliceRatios([50, 30, 20]).map(value => Math.round(value * 100)),
        [50, 30, 20]
    );
    const heatmap = rich.normalizeVisualization({
        type: 'heatmap',
        data: [
            { label: 'Machining', value: 26, series: 'Machines' },
            { label: 'Assembly', value: 0, series: 'Machines' },
            { label: 'Assembly', value: 12, series: 'Workstations' },
        ],
        encoding: { x: 'label', y: 'value', color: 'series' },
        options: { showValues: true, showPercentages: false, showLegend: true },
    });
    const matrix = rich.heatmapMatrix(heatmap);
    assert.deepStrictEqual(matrix.xLabels, ['Machining', 'Assembly']);
    assert.deepStrictEqual(matrix.seriesLabels, ['Machines', 'Workstations']);
    assert.strictEqual(matrix.cells.get('Machines\u0000Machining').value, 26);
    assert.strictEqual(heatmap.options.showValues, true);
});

test('structured tables preserve ordered columns and bounded cells', () => {
    const table = rich.normalizeTable({
        title: 'Department comparison',
        columns: [
            { label: 'Department', unit: null },
            { label: 'Placements', unit: 'count' },
        ],
        rows: [
            {
                cells: ['Machining Hall', '32'],
                entity_id: 'zone-machining',
            },
            {
                cells: ['Automation + Robot cells', '492', 'discarded'],
                entity_id: 'zone-automation',
            },
        ],
    });
    assert.strictEqual(table.columns.length, 2);
    assert.deepStrictEqual(table.rows[1].cells, [
        'Automation + Robot cells',
        '492',
    ]);
    assert.strictEqual(table.rows[0].entityId, 'zone-machining');
});

test('retained research sources do not acquire inferred publishers or favicon URLs', () => {
    const raw = {title: '<script>not markup</script>', url: 'https://www.skf.com/product.pdf',
        publisher: '', iconUrl: null, inferIdentity: false,
        specifications: {Authority: 'Supporting', Review: 'Pending', Use: 'Not production approval'}};
    const once = rich.normalizeSource(raw, 0);
    const twice = rich.normalizeSource(once, 0);
    assert.strictEqual(twice.publisher, '');
    assert.strictEqual(twice.iconUrl, null);
    assert.strictEqual(twice.domain, 'skf.com');
    assert.strictEqual(twice.inferIdentity, false);
    assert.strictEqual(twice.title, raw.title);
    assert.deepStrictEqual(twice.specifications, raw.specifications);
});

test('a file card links only to an app file, opens it outside the chat and has a download button', () => {
    const [card] = rich.normalizeBlocks([{ type: 'file', fileName: 'Bayport warehouse - layout plan.pdf',
        url: '/api/facility-layouts/site-local/fl-a/plan.pdf?revision=r-1', mimeType: 'application/pdf',
        detail: 'PDF - 3 sheets' }]);
    assert.deepStrictEqual(card, { type: 'file', fileName: 'Bayport warehouse - layout plan.pdf',
        url: '/api/facility-layouts/site-local/fl-a/plan.pdf?revision=r-1', detail: 'PDF - 3 sheets',
        mimeType: 'application/pdf' });
    for (const url of ['https://example.com/a.pdf', '//example.com/a.pdf', 'javascript:alert(1)', '/generated/a.pdf']) {
        assert.strictEqual(rich.normalizeBlocks([{ type: 'file', fileName: 'a.pdf', url }]).length, 0);
    }
    const made = [];
    const node = tag => { const item = { tagName: tag, children: [], style: { setProperty() {} },
        setAttribute(key, value) { this[key] = value; }, appendChild(child) { this.children.push(child); return child; } };
        made.push(item); return item; };
    const rendered = rich.renderBlock({ createElement: node, createTextNode: text => ({ text }) }, card);
    assert.ok(rendered && rendered.className === 'agent-file-card' && rendered.tagName === 'div');
    const link = made.find(item => item.className === 'agent-file-open');
    assert.ok(link && link.href === card.url && link.target === '_blank' && link.rel === 'noopener');
    const save = made.find(item => item.className === 'agent-file-download');
    assert.ok(save && save.href === card.url && save.download === card.fileName && !save.target);
    assert.deepStrictEqual(rendered.children, [link, save]);
});

test('a link to a public page shows its text, an arrow and a chip with the site icon and domain', () => {
    const html = rich.renderMarkdownHtml('Read [the ST-30 specs](https://legacy-aem.haascnc.com/st-30.html?a=1&b=2), '
        + 'the [Review PDF](/api/specification-sheet/x/pdf) and [a trap](javascript:alert(1)).');
    assert.ok(html.includes('<a class="agent-link" href="https://legacy-aem.haascnc.com/st-30.html?a=1&amp;b=2" '
        + 'target="_blank" rel="noopener noreferrer">the ST-30 specs</a><span class="agent-link-arrow"'));
    // The icon comes from the link's own origin, never a third-party favicon service.
    assert.ok(html.includes('<img src="https://legacy-aem.haascnc.com/favicon.ico" alt="" referrerpolicy="no-referrer"'));
    assert.ok(html.includes('data-initial="L"') && html.includes('<span class="agent-link-site">legacy-aem.haascnc.com</span>'));
    // A host without its own icon tries its parent domain once, never a two-part public suffix.
    assert.ok(html.includes('data-next="https://haascnc.com/favicon.ico"'));
    assert.ok(!rich.renderMarkdownHtml('[x](https://www.m-sankyo.co.jp/a)').includes('data-next="https://co.jp'));
    assert.ok(html.includes('<a href="/api/specification-sheet/x/pdf">Review PDF</a>'));
    assert.strictEqual((html.match(/agent-link-chip/g) || []).length, 1);
    assert.ok(!html.includes('javascript:'));
});

test('a research source card shows its link as the same text, arrow and site chip, never a raw address', () => {
    const [block] = rich.normalizeBlocks([{ type: 'sources', title: 'Research sources (unreviewed)', sources: [
        { url: 'https://assets.mach4metal.com/machines/129/brochures/mori-seiki-cl-200-6882.pdf?id=642b',
          title: 'https://assets.mach4metal.com/machines/129/brochures/mori-seiki-cl-200-6882.pdf?id=642b',
          inferIdentity: false, specifications: { Retrieval: 'Search discovery only', Review: 'Pending' } },
        { url: 'https://www.haascnc.com/machines/lathes/st/models/st-30.html', title: 'ST-30 | Haas CNC',
          inferIdentity: false }] }]);
    const made = [];
    const node = tag => { const item = { tagName: tag, children: [], style: { setProperty() {} },
        setAttribute(key, value) { this[key] = value; }, appendChild(child) { this.children.push(child); return child; },
        addEventListener() {} };
        made.push(item); return item; };
    rich.renderBlock({ createElement: node, createTextNode: text => ({ text }) }, block);
    const titles = made.filter(item => item.className === 'agent-source-title').map(item => item.innerHTML);
    assert.strictEqual(titles.length, 2);
    assert.ok(titles[0].startsWith('<a class="agent-link" href="https://assets.mach4metal.com/machines/129/brochures/'
        + 'mori-seiki-cl-200-6882.pdf?id=642b" target="_blank" rel="noopener noreferrer">Mori seiki cl 200 6882 (PDF)</a>'));
    assert.ok(titles[0].includes('<span class="agent-link-site">assets.mach4metal.com</span>'));
    assert.ok(titles[1].includes('>ST-30 | Haas CNC</a>') && titles[1].includes('haascnc.com/favicon.ico'));
    // The chip is the link: no letter badge and no separate View source button.
    assert.ok(!made.some(item => item.className === 'agent-source-identity'));
    assert.ok(!made.some(item => item.textContent === 'View source'));
    assert.ok(made.some(item => item.tagName === 'dl' && item.className === 'agent-source-specs'));
    assert.strictEqual(rich.linkLabel('https://us.dmgmori.com/', 'https://us.dmgmori.com/'), 'us.dmgmori.com');
});

console.log(passed + ' passed, ' + (process.exitCode ? 1 : 0) + ' failed');
