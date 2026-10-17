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

console.log(passed + ' passed, ' + (process.exitCode ? 1 : 0) + ' failed');
