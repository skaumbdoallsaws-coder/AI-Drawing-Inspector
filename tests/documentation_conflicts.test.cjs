const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const review = require('../static/documentation_conflicts.js');

const item = {conflictId:'c1', targetId:'cell1', pageId:'p2', owner:'scene', revision:7,
    conflictHash:'hash1', targetKind:'cell', texts:{B:'Old',C:'Mine',N:'New'}};
const read = {documentId:'doc', revision:99, restoreTargets:[]};

test('review is sorted by page and stable target, independent of undo append order', () => {
    const items = [{...item, targetId:'z'}, {...item, pageId:'p1'}, {...item, targetId:'a'}];
    assert.deepEqual(review.sorted(items, [{pageId:'p1'},{pageId:'p2'}]).map(x => x.pageId + x.targetId),
        ['p1cell1','p2a','p2z']);
    assert.equal(items[0].targetId, 'z');
});
test('resolution uses the item owner revision, conflict hash and one explicit choice', () => {
    assert.deepEqual(review.resolutionBody(read, item, 'keep_manual', {}, 'r1'), {
        documentId:'doc', expectedRevision:7, requestId:'r1',
        resolutions:[{conflictId:'c1', expectedConflictHash:'hash1', choice:'keep_manual'}]});
    assert.equal(review.resolutionBody(read,{...item,owner:'slots',revision:21},'use_generated',{},'r2').expectedRevision,21);
});
test('merge is nonempty and keeps the exact entered text', () => {
    assert.throws(() => review.resolutionBody(read,item,'merge_text',{mergedText:'  '},'r'), /Enter merged/);
    assert.equal(review.resolutionBody(read,item,'merge_text',{mergedText:' Mine + new '},'r').resolutions[0].mergedText,' Mine + new ');
});
test('restore requires an explicit same-owner same-kind target and current hash', () => {
    const targets = [{owner:'scene',kind:'cell',targetId:'a',contentHash:'h'},
        {owner:'slots',kind:'cell',targetId:'b',contentHash:'h'}, {owner:'scene',kind:'block',targetId:'c',contentHash:'h'}];
    const state = {...read,restoreTargets:targets};
    assert.deepEqual(review.destinations(item,targets),[targets[0]]);
    assert.throws(() => review.resolutionBody(state,item,'restore',{},'r'),/Choose/);
    assert.throws(() => review.resolutionBody(state,item,'restore',{targetId:'a',expectedContentHash:'old'},'r'),/Choose/);
    assert.equal(review.resolutionBody(state,item,'restore',{targetId:'a',expectedContentHash:'h'},'r').resolutions[0].targetId,'a');
});
test('evidence comparison ignores object key ordering but keeps changed refs', () => {
    assert.equal(review.canonical({sources:['a'],claims:['b']}),review.canonical({claims:['b'],sources:['a']}));
    assert.notEqual(review.canonical({sources:['a']}),review.canonical({sources:['b']}));
});
test('markers follow stable and row identities through read aliases', () => {
    const payload = {document:{aliasMap:{p2:{'table.r0.c1':{targetId:'cell1',ownerId:'row1'}}}}};
    assert.equal(review.targetMatches(item,'p2','table.r0.c1',payload),true);
    assert.equal(review.targetMatches({...item,targetId:'row1'},'p2','table.r0.c1',payload),true);
    assert.equal(review.targetMatches(item,'p2','table.r1.c1',payload),false);
    assert.equal(review.targetMatches({...item,targetId:'slot:title'},'p2','slot:title',payload),true);
});
test('refresh summaries combine both specification owners', () => {
    assert.equal(review.receiptText({refreshReceipt:{counts:{adopted:2,kept:1}},
        slotRefreshReceipt:{counts:{conflicts:1,preserved:3,orphans:2}}}),
        'Refresh: adopted 2 | preserved 3 | kept 1 | conflicts 1 | orphans 2');
    assert.equal(review.receiptText({refreshReceipt:null}),'');
});

// Small DOM adapter exercises the actual controller and fetch flow without a
// browser or third-party dependency. Visual/layout behavior belongs to the smoke.
class Element {
    constructor(tag) { this.tagName=tag; this.children=[]; this.dataset={}; this.attributes={}; this.events={}; this.hidden=false; this.value=''; }
    set textContent(value) { this.text=String(value); this.children=[]; }
    get textContent() { return (this.text || '') + this.children.map(x=>x.textContent).join(''); }
    append(...nodes) { for(const node of nodes){node.parent=this;this.children.push(node);} }
    replaceChildren(...nodes) { for(const node of this.children)node.parent=null;this.children=[];this.text='';this.append(...nodes); }
    setAttribute(key,value) { this.attributes[key]=value; }
    removeAttribute(key) { delete this.attributes[key]; }
    hasAttribute(key) { return key in this.attributes; }
    addEventListener(name,fn) { (this.events[name] ||= []).push(fn); }
    async fire(name) { for(const fn of this.events[name] || [])await fn({target:this}); }
    async click() { if(!this.disabled)await this.fire('click'); }
    get isConnected() { return this.tagName === 'document' || !!this.parent?.isConnected; }
    remove() { if(this.parent)this.parent.children=this.parent.children.filter(x=>x!==this);this.parent=null; }
    showModal() { this.open=true; }
    close() { this.open=false; void this.fire('close'); }
    querySelectorAll(selector) {
        const match = n => selector.split(',').some(part=>{
            part=part.trim();
            if(part.startsWith('#'))return n.id === part.slice(1);
            if(part.startsWith('.'))return (n.className || '').split(' ').includes(part.slice(1));
            if(part.startsWith('['))return false; // surface in these controller tests has no page nodes
            return n.tagName === part;
        });
        const found=[];
        for(const node of this.children){if(match(node))found.push(node);found.push(...node.querySelectorAll(selector));}
        return found;
    }
    querySelector(s) { return this.querySelectorAll(s)[0] || null; }
    get classList() {
        const names=()=>(this.className || '').split(' ').filter(Boolean), write=list=>{this.className=list.join(' ');};
        return {contains:name=>names().includes(name),
            add:(...list)=>write([...new Set([...names(),...list])]),
            remove:(...list)=>write(names().filter(name=>!list.includes(name))),
            toggle:(name,force)=>{const on=force===undefined ? !names().includes(name) : !!force;
                write(on ? [...new Set([...names(),name])] : names().filter(x=>x!==name));return on;}};
    }
}
function harness(handler, payload = {}) {
    const document = new Element('document');
    document.head=new Element('head'); document.body=new Element('body'); document.append(document.head,document.body);
    document.createElement=tag=>new Element(tag); document.getElementById=id=>document.querySelector('#'+id);
    const workspace=new Element('main');workspace.id='documentationWorkspace';document.body.append(workspace);
    const status=new Element('div');status.className='documentation-status-center';workspace.append(status);
    const surface=new Element('div');surface.id='documentationPublicationSurface';workspace.append(surface);
    const calls=[];let uuid=0,reloads=0,clears=0;
    const ticks=[];
    const window={document,crypto:{randomUUID:()=> 'request-'+(++uuid)},setInterval:fn=>ticks.push(fn)};
    const context={kind:'product_specification_sheet',number:'MMLE-50D',payload:{revision:'a',...payload},pageId:'p2'};
    vm.runInNewContext(fs.readFileSync(require.resolve('../static/documentation_conflicts.js'),'utf8'),{
        window,MutationObserver:class{observe(){} disconnect(){}},
        fetch:async(url,options)=>{
            const body=options?.body ? JSON.parse(options.body) : undefined;calls.push({url,body});
            const result=await handler(url,body);
            return {ok:result.success !== false,json:async()=>result};
        }
    });
    const host={context:()=>context,focus:async()=>{},clearSelection:()=>{clears++;},reload:async()=>{reloads++;context.payload.revision+='b';window.DocumentationConflicts.sync(host);}};
    window.DocumentationConflicts.sync(host);
    const allButtons=()=>document.querySelectorAll('button');
    return {api:window.DocumentationConflicts,document,calls,context,host,
        button:label=>allButtons().find(x=>x.textContent===label),tick:()=>ticks[0](),get reloads(){return reloads;},get clears(){return clears;}};
}
const response = (extra={}) => ({...read,sceneEditRevision:7,openConflictCount:1,orphanCount:0,conflicts:[item],
    orphans:[],resolutionHistory:[],totals:{conflicts:1,orphans:0,resolutionHistory:0,restoreTargets:0},...extra});
const flush = async()=>{for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));};

test('stale refusal reloads review and never automatically resolves',async()=>{
    const h=harness(async(url,body)=>body ? {success:false,error:'stale_revision',message:'Changed'} : response());
    h.api.show();await flush();
    await h.button('Keep mine').click();await flush();
    assert.equal(h.calls.filter(x=>x.body).length,1);
    assert.equal(h.calls.find(x=>x.body).body.expectedRevision,7);
    assert.equal(h.reloads,1);
    assert.equal(h.document.getElementById('documentationConflictPane').hidden,false);
    assert.match(h.document.getElementById('documentationConflictPane').textContent,/Review the current values/);
});
test('transport retry reuses requestId; a later explicit choice gets a new ID',async()=>{
    let posts=0;
    const h=harness(async(url,body)=>{
        if(!body)return response();
        if(++posts===1)throw Error('offline');
        return {success:true,reload:true};
    });
    h.api.show();await flush();await h.button('Keep mine').click();await flush();
    assert.equal(posts,1);assert.equal(h.reloads,0);
    await h.button('Retry request').click();await flush();
    assert.deepEqual(h.calls.filter(x=>x.body).map(x=>x.body.requestId),['request-1','request-1']);
    await h.button('Use generated').click();await flush();
    assert.equal(h.calls.filter(x=>x.body).at(-1).body.requestId,'request-2');
});
test('pagination loads every restore destination and detects inconsistent owner revisions',async()=>{
    const h=harness(async url=>response(url.includes('from=100') ?
        {restoreTargets:[{targetId:'last'}],totals:{restoreTargets:101},conflicts:[]} :
        {restoreTargets:Array.from({length:100},(_,i)=>({targetId:String(i)})),totals:{restoreTargets:101}}));
    h.api.show();await flush();
    assert.equal(h.calls.length,2);assert.match(h.calls[1].url,/from=100/);
    const stale=harness(async url=>response({revision:url.includes('from=100')?100:99,totals:{restoreTargets:101}}));
    stale.api.show();await flush();
    assert.match(stale.document.getElementById('documentationConflictPane').textContent,/changed during review/);
    assert.equal(stale.button('Keep mine'),undefined);
});
test('reset requires a preview and sends the specification slot pair unchanged',async()=>{
    const h=harness(async(url,body)=>body ? {success:true} : url.endsWith('/reset') ? {
        expectedRevision:'scene-rev',previewHash:'scene-hash',affectedIds:['cell1'],
        slots:{expectedRevision:12,previewHash:'slot-hash',affectedIds:['slot:title']}
    } : response());
    await h.api.preview('reset');await flush();
    assert.equal(h.calls.filter(x=>x.body).length,0);
    assert.match(h.document.getElementById('documentationResetDialog').textContent,/2 affected targets.*recoverable copy/s);
    await h.button('Reset now').click();await flush();
    assert.deepEqual(h.calls.find(x=>x.body).body,{expectedRevision:'scene-rev',previewHash:'scene-hash',
        slots:{expectedRevision:12,previewHash:'slot-hash'}});
});
test('orphan restore starts with no destination selected and a disabled Restore button',async()=>{
    const h=harness(async()=>response({conflicts:[],orphans:[{...item,conflictId:undefined,orphanId:'o1'}],
        restoreTargets:[{owner:'scene',kind:'cell',targetId:'destination',contentHash:'h'}]}));
    h.api.show();await flush();
    assert.equal(h.document.querySelector('select').value,'');
    assert.equal(h.button('Restore').disabled,true);
    assert.match(h.document.getElementById('documentationConflictPane').textContent,/Unplaced manual content/);
});

test('named undo observation reloads the stored count and reopened conflict',async()=>{
    let version=99;
    const h=harness(async()=>response({revision:version,sceneEditRevision:version,
        conflicts:version===99 ? [] : [item],openConflictCount:version===99?0:1}));
    h.api.show();await flush();
    assert.equal(h.document.getElementById('documentationConflictCount').textContent,'0 conflicts');
    version=100;
    await h.tick();await flush();
    assert.equal(h.reloads,1);
    assert.equal(h.document.getElementById('documentationConflictCount').textContent,'1 conflict');
    assert.ok(h.button('Keep mine'));
});
test('parts refresh previews both bindings before it posts their exact revisions',async()=>{
    const h=harness(async(url,body)=>body ? {success:true,refreshReceipt:{counts:{preserved:1,conflicts:1}}}
        : url.endsWith('/refresh') ? {expectedRevision:'scene',expectedPlanRevision:'plan',fromBinding:{sourceRevision:'old'},
            toBinding:{sourceRevision:'new'},planCarried:true} : response());
    await h.api.preview('refresh');await flush();
    assert.equal(h.calls.filter(x=>x.body).length,0);
    assert.match(h.document.getElementById('documentationRefreshDialog').textContent,/carries to the new source/);
    await h.button('Refresh now').click();await flush();
    assert.deepEqual(h.calls.find(x=>x.body).body,{expectedRevision:'scene',expectedPlanRevision:'plan'});
    assert.match(h.document.getElementById('documentationRefreshReceipt').textContent,/preserved 1.*conflicts 1/);
});

test('an open review docks beside the page, clears the page selection and closes cleanly',async()=>{
    const h=harness(async()=>response());
    const workspace=h.document.getElementById('documentationWorkspace');
    assert.equal(workspace.classList.contains('documentation-review-open'),false);
    h.api.show();await flush();
    assert.equal(workspace.classList.contains('documentation-review-open'),true);
    assert.equal(h.clears,1);
    await h.button('Close review').click();
    assert.equal(h.document.getElementById('documentationConflictPane').hidden,true);
    assert.equal(workspace.classList.contains('documentation-review-open'),false);
    assert.equal(h.clears,1);
});
test('a closed review never polls; reopening resumes the change check',async()=>{
    const h=harness(async()=>response());
    h.api.show();await flush();
    await h.button('Close review').click();
    const closed=h.calls.length;
    await h.tick();await flush();
    assert.equal(h.calls.length,closed);
    h.api.show();await flush();
    const reopened=h.calls.length;
    await h.tick();await flush();
    assert.equal(h.calls.length,reopened+1);
    assert.match(h.calls.at(-1).url,/conflicts\?limit=1$/);
});
