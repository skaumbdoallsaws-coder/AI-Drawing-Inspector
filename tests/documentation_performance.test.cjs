const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');
const before = '4669cd06834010b945f83dea84cac24795fab985';
const old = relative => execFileSync('git', ['show', before + ':' + relative], {cwd: root, windowsHide: true, encoding: 'utf8', maxBuffer: 32*1024*1024});
const fn = (source, name) => {
    let start = source.indexOf('        function ' + name + '(');
    if (start < 0) start = source.indexOf('        async function ' + name + '(');
    assert.notEqual(start, -1, name);
    const next = source.slice(start + 20).search(/\n        (?:async )?function /);
    return source.slice(start, next < 0 ? source.length : start + 20 + next);
};
const json = value => JSON.parse(JSON.stringify(value));

test('fitting preserves every old size and batches all geometry reads before font writes', () => {
    function run(source) {
        const events = [], cells = [];
        const element = (text, width, bold = false) => {
            const values = {};
            const node = {textContent: text, isContentEditable: false, style: new Proxy(values, {
                set(obj, key, value) { events.push([key, text]); obj[key] = value; return true; }
            }), getBoundingClientRect() { events.push(['read', text]); return {width}; }, bold};
            cells.push(node); return node;
        };
        const head = element('DESCRIPTION', 125, true);
        const rows = Array.from({length: 20}, (_, i) => ({style: {}, cells: [element('PART-' + i, 60),
            element('A long mounting component description ' + i, 125), element(String(i), 25)]}));
        const table = {tBodies: [{rows}], parentElement: {style: {height: '400'}}, querySelectorAll: () => [head]};
        const group = element('A very long group name', 90, true), header = element('Publication', 150);
        const surface = {isConnected: true, style: {width: '792'}, classList: {contains: () => false},
            getBoundingClientRect: () => ({width: 792}),
            querySelectorAll: selector => selector === '.documentation-page-bom' ? [table]
                : selector === '.documentation-page-group-row strong' ? [group] : [],
            querySelector: () => header};
        const context = {font: '', measureText(text) { return {width: text.length * parseFloat(this.font.match(/([\d.]+)px/)[1]) * .51}; }};
        const sandbox = vm.createContext({document: {createElement: () => ({getContext: () => context})},
            getComputedStyle: node => ({fontWeight: node.bold ? '800' : '400', fontStyle: 'normal', fontFamily: 'Arial',
                paddingLeft: '4', paddingRight: '4', borderLeftWidth: '1', borderRightWidth: '1'}),
            DocumentationPublicationCore: require('../static/documentation_publication_core.js'),
            _documentationPageElementOverride: () => ({style: {}})});
        vm.runInContext(fn(source, '_documentationFitPublicationText'), sandbox);
        sandbox._documentationFitPublicationText(surface, {});
        return {sizes: cells.map(n => json(n.style)), events};
    }
    const actual = run(html), expected = run(old('static/index.html'));
    assert.deepEqual(actual.sizes, expected.sizes);
    const first = actual.events.findIndex(e => e[0] === 'read');
    const last = actual.events.findLastIndex(e => e[0] === 'read');
    assert(!actual.events.slice(first, last + 1).some(e => ['fontSize','fontWeight','lineHeight'].includes(e[0])));
    assert(expected.events.slice(0, expected.events.findLastIndex(e => e[0] === 'read')).some(e => e[0] === 'fontSize'));
});

test('thumbnail key follows drawn page/theme/paper/capture/rich runs, not an unrelated edit binding', () => {
    const page = {pageId: 'one', title: 'First', renderRequest: {image: {status: 'ready', sha256: 'image1', url: '/image'}}};
    const payload = {revision: 'scene1', document: {product: {name: 'Machine'}, pageCount: 2, theme: {color: 'blue'},
        publicationLayout: {page: {width: 792, height: 612}}, pages: [page, {pageId: 'two'}]},
        richTextFields: [{pageId: 'one', targetId: 'text', text: 'note', richText: {doc: 'content'}, binding: {revision: 1}}]};
    const sandbox = vm.createContext({_documentationPayload: () => payload, _documentationApiBase: () => '/api/parts/A',
        state: {partsManualDocumentationPageId: 'one'}});
    vm.runInContext(fn(html, '_documentationThumbnailKey'), sandbox);
    const key = () => sandbox._documentationThumbnailKey(page), first = key();
    payload.revision = 'scene2'; payload.document.documentRevision = 'new';
    payload.document.pages[1].title = 'Changed elsewhere'; payload.richTextFields[0].binding.revision = 2;
    page.renderRequest.image.documentRevision = 'new';
    assert.equal(key(), first);
    for (const mutate of [() => page.title = 'Changed here', () => payload.document.theme.color = 'red',
        () => payload.document.publicationLayout.page.width = 841.89,
        () => page.renderRequest.image.sha256 = 'image2', () => payload.richTextFields[0].richText.doc = 'new marks']) {
        const previous = key(); mutate(); assert.notEqual(key(), previous);
    }
});

test('page activation only marks rail items; thumbnails render on an isolated root', () => {
    const body = fn(html, '_documentationActivatePage');
    assert(!body.includes('_documentationRenderPageRail('));
    assert(body.includes('_documentationSelectRailPage('));
    const build = fn(html, '_documentationBuildPageThumbnail');
    assert(build.includes('surface: clone'));
    assert(!build.includes('_documentationRenderPublicationPage(page, { thumbnail: true })'));
    const rail = fn(html, '_documentationRenderPageRail');
    assert(!rail.includes("list.innerHTML = ''"));
    assert(rail.includes('IntersectionObserver'));
    const queue = fn(html, '_documentationQueueRailThumbnails');
    for (const guard of ['DocumentationRichText?.active', 'documentationObjectCrop', 'documentationObjectInFlight',
        'partsManualDocumentationObjectDrag', 'partsManualDocumentationResizeDrag']) assert(queue.includes(guard), guard);
});

test('disposing a mount releases its loop, observers, controls, registries and both rendering contexts', () => {
    const calls = [];
    // Supervisor (P5a-3): the cached model's geometry, materials and textures are shared by its meshes and
    // outlive the mount. Each is released once, before the renderer goes, so the renderer's listeners on
    // them (the reference that kept every closed viewer's WebGL context alive) are taken off.
    const resource = name => ({dispose: () => calls.push(name)});
    const geometry = resource('geometry'), map = {...resource('map'), isTexture: true},
        uniformMap = {...resource('uniformMap'), isTexture: true},
        material = {...resource('material'), map, color: {}}, shader = {...resource('shader'), uniforms: {tint: {value: uniformMap}, size: {value: 2}}},
        instanced = {...resource('instanced'), isInstancedMesh: true, geometry, material};
    const objects = [{}, {geometry, material}, {geometry, material: [material, shader]}, instanced, {geometry: {}}];
    const scene = {userData: {_cadViewportBackgroundTexture: {dispose: () => calls.push('background')}}, background: {},
            traverse: visit => objects.forEach(visit)},
        renderer = {dispose: () => calls.push('renderer'), forceContextLoss: () => calls.push('context'),
            domElement: {remove: () => calls.push('canvas')}};
    const state = {_assyMountToken: 4, assyAnimationId: 10, _assyCameraAnimId: 11, assyScene: scene, assyRenderer: renderer,
        _assyMountDispose: () => calls.push('observer'), assyControls: {dispose: () => calls.push('controls')},
        _assyGizmo: {dispose: () => calls.push('gizmo')}, assyLabelRenderer: {domElement: {remove: () => calls.push('labels')}},
        assyGltfScene: {retained: true}};
    const window = {__themedScenes: new Set([scene]), __themedRenderers: new Set([renderer])};
    const sandbox = vm.createContext({state, window, cancelAnimationFrame: id => calls.push(id),
        _partsManualDisposeDocumentationTechnicalPass: () => calls.push('technical'),
        _disposeViewerDisplayPass: () => calls.push('display')});
    vm.runInContext(fn(html, '_materialList'), sandbox);
    vm.runInContext(fn(html, '_releaseSceneGpuResources'), sandbox);
    vm.runInContext(fn(html, '_disposeAssembly3DMount'), sandbox);
    sandbox._disposeAssembly3DMount();
    assert.deepEqual(calls, [10,11,'observer','controls','gizmo','technical','display',
        'geometry','map','material','uniformMap','shader','instanced',
        'background','renderer','context','canvas','labels']);
    assert.equal(window.__themedScenes.size, 0); assert.equal(window.__themedRenderers.size, 0);
    assert.equal(state.assyRenderer, null); assert.equal(scene.background, null);
    assert.equal(state.assyGltfScene.retained, true);
    sandbox._disposeAssembly3DMount(); // Safe after a previous close already released the mount.
    assert.equal(calls.filter(x => x === 'context').length, 1);
});

test('an accepted picture pauses the covered mount but capture and live editing can render', () => {
    let workspace = {}, image = true, takeover = false;
    const container = {isConnected: true}, page = {pageId: 'p', renderRequest: {}};
    const state = {partsManualDocumentationLiveEditPageId: null};
    const sandbox = vm.createContext({state, document: {hidden: false, getElementById: id => id === 'documentationWorkspace'
        ? workspace : {contains: () => true, querySelector: () => image}}, _documentationActivePage: () => page,
        _documentationFigureCaptureTakeoverIsActive: () => takeover});
    vm.runInContext(fn(html, '_assemblyMountIsCovered'), sandbox);
    assert.equal(sandbox._assemblyMountIsCovered(container), true);
    takeover = true; assert.equal(sandbox._assemblyMountIsCovered(container), false);
    takeover = false; state.partsManualDocumentationLiveEditPageId = 'p'; assert.equal(sandbox._assemblyMountIsCovered(container), false);
    state.partsManualDocumentationLiveEditPageId = null; image = false; assert.equal(sandbox._assemblyMountIsCovered(container), false);
    page.renderRequest = null; assert.equal(sandbox._assemblyMountIsCovered(container), true);
    workspace = null; assert.equal(sandbox._assemblyMountIsCovered(container), false);
});

test('the Tiptap import starts on the first readiness request, once, and failure still resolves', async () => {
    let imports = 0;
    const source = fs.readFileSync(path.join(root, 'static/documentation_rich_text.js'), 'utf8')
        .replace("import('/static/vendor/tiptap/tiptap.bundle.js?v=c36fd989775f')", 'loadBundle()');
    const window = {DocumentationRichTextCore: {}};
    const sandbox = vm.createContext({window, loadBundle: () => { imports++; return Promise.reject(new Error('offline')); }});
    vm.runInContext(source, sandbox);
    assert.equal(imports, 0);
    const first = window.DocumentationRichText.ready;
    assert.equal(first, window.DocumentationRichText.ready);
    assert.equal((await first).ok, false);
    assert.equal(imports, 1);
});

test('the editing strip exposes every row and responsive groups have More proxies', () => {
    const css = fs.readFileSync(path.join(root, 'static/documentation_rich_text.css'), 'utf8');
    assert(!css.includes('max-height: 106px'));
    assert(css.includes('overflow: visible;'));
    const overflow = fn(html, '_documentationRibbonOverflowMenu');
    for (const name of ['object', 'content', 'edit', 'figure', 'annotate', 'values-history']) {
        assert(overflow.includes("'" + name + "'"));
        assert(html.includes('[data-overflow-group="' + name + '"]'));
    }
});


test('the faster word reader retains clipped glyphs, wraps, inline joins, case, exclusions and Unicode exactly', () => {
    const script = source => source.split('P4B_SURFACE_WORDS_JS = r"""')[1].split('"""')[0];
    function run(source) {
        const reads = {styles: 0, boxes: 0, ranges: 0, glyphs: 0};
        const rect = (left=0, top=0, right=500, bottom=500) => ({left,top,right,bottom,width:right-left,height:bottom-top});
        const element = (parent, cls='', css={}, bounds=rect()) => ({parentElement:parent, tagName:'SPAN', className:cls,
            css:{display:'inline',visibility:'visible',opacity:'1',overflowX:'visible',overflowY:'visible',textTransform:'none',...css},
            getBoundingClientRect() { reads.boxes++; return bounds; }, getAttribute() { return cls; },
            closest(selectors) { const names=selectors.split(',').map(s=>s.trim().slice(1)); let n=this;
                while(n) { if(names.includes(n.className)) return n; n=n.parentElement; } return null; },
            contains(child) { for(let n=child;n;n=n.parentElement) if(n===this)return true; return false; }});
        const root = element(null,'root',{display:'block'}); root.style={width:'500'};
        const live = element(root,'live'); root.querySelector=()=>live;
        const nodes = [];
        function add(parent,text,x,y,wrap=Infinity) {
            const boxes=[]; let col=0,row=0;
            for(const ch of text) {
                if(col===wrap) { col=0;row++; }
                const r=rect(x+col*7,y+row*12,x+(col+1)*7,y+row*12+10);
                for(let i=0;i<ch.length;i++)boxes.push(r);
                col++;
            }
            const node={parentElement:parent,textContent:text,boxes}; nodes.push(node); return node;
        }
        const paragraph=element(root,'paragraph',{display:'block'}), inline=element(paragraph);
        add(inline,'feeler-gauge',10,10,7); add(inline,' tested',38,22);
        add(element(root,'caps',{display:'block',textTransform:'uppercase'}),'Field',10,40);
        add(element(root,'clip',{display:'block',overflowX:'hidden'},rect(10,60,32,70)),'ABCDEFGHIJ',10,60);
        add(element(root,'unicode',{display:'block'}),'Con\ufb01rm \ud83d\ude42 e\u0301',10,80);
        add(element(root,'hidden',{opacity:'0'}),'hidden',10,100);
        add(element(live),'duplicate balloons',10,120);
        add(element(root,'ui'),'Edit',10,140);
        add(element(root,'exception'),'Counted exception',10,160);
        const breakNode=add(inline,'after break',10,180); breakNode.previousSibling={nodeName:'BR'};
        const union = list => rect(Math.min(...list.map(r=>r.left)),Math.min(...list.map(r=>r.top)),
            Math.max(...list.map(r=>r.right)),Math.max(...list.map(r=>r.bottom)));
        const document = {querySelector:()=>root, createTreeWalker:()=>{let i=0;return {nextNode:()=>nodes[i++]};},
            createRange() { reads.ranges++; let n,a=0,b=0; return {
                selectNodeContents(node) { n=node;a=0;b=n.textContent.length; },
                setStart(node,start) { n=node;a=start; },setEnd(node,end) { n=node;b=end; },
                getBoundingClientRect() { reads.glyphs++;return union(n.boxes.slice(a,b)); },
                getClientRects() { const groups=new Map(); for(const r of n.boxes.slice(a,b)) {
                    if(!groups.has(r.top))groups.set(r.top,[]);groups.get(r.top).push(r); }
                    return [...groups.values()].map(union); }
            }; }};
        const context=vm.createContext({document,NodeFilter:{SHOW_TEXT:4},getComputedStyle:n=>{reads.styles++;return n.css;}});
        const result=vm.runInContext('('+script(source)+')',context)({ui:['.ui'],
            exceptions:[{selector:'.exception',name:'named'}],capture:{liveCovered:true,contract:true}});
        return {result:json(result),reads};
    }
    const actual=run(fs.readFileSync(path.join(root,'tests/smoke_documentation_editor.py'),'utf8')),
        expected=run(old('tests/smoke_documentation_editor.py'));
    assert.deepEqual(actual.result,expected.result);
    assert(actual.reads.glyphs < expected.reads.glyphs);
    assert(actual.reads.styles < expected.reads.styles);
    assert.equal(actual.reads.ranges,1);
});

// Supervisor (P5a-3 gate): the measured pass that folds ribbon groups into More. The fake bar lays its children
// out in a row like the flex command bar: a folded group has no box, More has one only while something is folded.
function ribbonBar(width, groups, options = {}) {
    const attributes = new Map();
    const folded = () => (attributes.get('data-documentation-folded') || '').split(' ').filter(Boolean);
    const children = groups.map(([key, size]) => ({key, size}));
    if (options.more !== false) children.push({key: 'overflow', size: 60, more: true});
    const boxes = () => {
        let x = 0; const result = new Map();
        for (const child of children) {
            const visible = child.more ? folded().length > 0 : !folded().includes(child.key);
            if (visible) { result.set(child, {left: x, right: x + child.size}); x += child.size; }
        }
        return result;
    };
    for (const child of children) {
        child.getClientRects = () => boxes().has(child) ? [boxes().get(child)] : [];
        child.getBoundingClientRect = () => boxes().get(child) || {left: 0, right: 0};
    }
    const sections = new Set(options.sections || groups.map(([key]) => key));
    return {children, folded, width,
        getBoundingClientRect() { return {left: 0, right: this.width}; },
        setAttribute: (name, value) => attributes.set(name, value), removeAttribute: name => attributes.delete(name),
        querySelector: selector => {
            if (selector === '.documentation-ribbon-overflow-group') return children.find(child => child.more) || null;
            let match = /^\[data-documentation-ribbon-group="([^"]+)"\]$/.exec(selector);
            if (match) return children.find(child => child.key === match[1]) || null;
            match = /^\.documentation-overflow-section\[data-overflow-group="([^"]+)"\]$/.exec(selector);
            if (match) return sections.has(match[1]) ? {} : null;
            throw new Error('unexpected selector ' + selector);
        }};
}
const foldOrder = () => JSON.parse(/const DOCUMENTATION_RIBBON_FOLD_ORDER = (\[[^\]]+\]);/.exec(html)[1].replace(/'/g, '"'));
function fitRibbon(bar) {
    const sandbox = vm.createContext({document: {querySelector: () => bar}, DOCUMENTATION_RIBBON_FOLD_ORDER: foldOrder()});
    vm.runInContext(fn(html, '_documentationFitWorkflowRibbon') + ';_documentationFitWorkflowRibbon();', sandbox);
    return bar.folded();
}

test('the ribbon folds groups into More, least used first, only until Publish and More fit', () => {
    const groups = [['generate', 200], ['edit', 200], ['content', 190], ['figure', 220], ['format', 340], ['object', 200], ['publish', 150]];
    // Everything fits: nothing is folded and More stays away.
    assert.deepEqual(fitRibbon(ribbonBar(1500, groups)), []);
    // 1500 of content in 1400: Figure goes (More takes 60), and that is enough.
    assert.deepEqual(fitRibbon(ribbonBar(1400, groups)), ['figure']);
    // Narrower: Content follows, then Edit, then Object; Format and Publish are never folded.
    assert.deepEqual(fitRibbon(ribbonBar(1150, groups)), ['figure', 'content']);
    assert.deepEqual(fitRibbon(ribbonBar(960, groups)), ['figure', 'content', 'edit']);
    assert.deepEqual(fitRibbon(ribbonBar(700, groups)), ['figure', 'content', 'edit', 'object']);
    // A later pass on a wider bar unfolds again.
    const bar = ribbonBar(1150, groups); fitRibbon(bar); bar.width = 1500;
    assert.deepEqual(fitRibbon(bar), []);
    // A group More cannot show stays on the ribbon; a ribbon without More is left alone.
    assert.deepEqual(fitRibbon(ribbonBar(1400, groups, {sections: ['content', 'edit', 'object']})), ['content']);
    assert.deepEqual(fitRibbon(ribbonBar(700, groups, {more: false})), []);
});

test('every group the measured pass may fold has its fold and More rules in the stylesheet', () => {
    const order = foldOrder();
    assert.deepEqual(order, ['figure', 'annotate', 'values-history', 'content', 'edit', 'object']);
    for (const key of order) {
        const bar = '.documentation-ribbon-commandbar[data-documentation-folded~="' + key + '"]';
        for (const rule of [bar + ' [data-documentation-ribbon-group="' + key + '"]',
            bar + ' [data-documentation-separator-for="' + key + '"]',
            bar + ' .documentation-overflow-section[data-overflow-group="' + key + '"]']) assert(html.includes(rule), rule);
    }
    assert(html.includes('.documentation-ribbon-commandbar[data-documentation-folded] .documentation-ribbon-overflow-group { display: flex !important; }'));
    const render = fn(html, '_renderDocumentationWorkflowRibbon');
    assert(render.includes('_documentationFitWorkflowRibbon();') && render.includes('documentationRibbonFitObserver.observe(shell)'));
    // The observer's first report after observe() finds the width the render just fitted and does nothing.
    assert(render.includes('documentationRibbonFitWidth = shell.getBoundingClientRect().width;'));
    assert(render.includes('if (Math.abs(width - documentationRibbonFitWidth) <= 0.5) return;'));
});
