(function (root, factory) {
    const walls = typeof module === 'object' && module.exports
        ? require('./facility_layout_walls.js') : root.InspectorProFacilityWalls;
    const lettering = typeof module === 'object' && module.exports
        ? require('./facility_layout_lettering.js') : root.InspectorProFacilityLettering;
    const api = factory(walls, lettering);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityDecals = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (walls, lettering) {
    'use strict';
    const clone = value => JSON.parse(JSON.stringify(value));
    const sameTarget = (a, b) => a.placementId === b.placementId && a.face === b.face
        && a.edge === b.edge && a.side === b.side && a.wallId === b.wallId;
    function records(layout) { return layout.extensions && layout.extensions.facilityDecals
        ? layout.extensions.facilityDecals.artworks : []; }

    function targets(layout, catalog) {
        const result = [], perimeter = walls.data(layout), settings = perimeter && perimeter.settings;
        if (settings) {
            const plan = layout.extensions.facilityPlan;
            const boundary = settings.boundarySource === 'polygon' ? settings.boundary
                : [{x:0,z:0},{x:plan.widthMeters,z:0},{x:plan.widthMeters,z:plan.depthMeters},{x:0,z:plan.depthMeters}];
            boundary.forEach((a, edge) => {
                const b = boundary[(edge + 1) % boundary.length], length = Math.hypot(b.x-a.x, b.z-a.z);
                const spans = []; let cursor = 0;
                (settings.openings || []).filter(o => o.edge === edge).sort((a,b) => a.startMeters-b.startMeters).forEach(o => {
                    if (o.startMeters > cursor) spans.push([cursor, o.startMeters]);
                    cursor = o.endMeters;
                });
                if (cursor < length) spans.push([cursor, length]);
                ['interior', 'exterior'].forEach(side => spans.forEach(([start, end]) => {
                    if (end-start < .05) return;
                    result.push({target:{edge, side}, width:length, height:settings.heightMeters, start, end,
                        color: side === 'interior' ? settings.interiorColor : settings.exteriorFinish && settings.exteriorFinish.color,
                        label:'Perimeter ' + (edge+1) + ' / ' + side + ' / ' + start.toFixed(2) + '-' + end.toFixed(2) + ' m'});
                }));
            });
        }
        walls.interiorWalls(layout).forEach(wall=>{
            const length=Math.hypot(wall.end.x-wall.start.x,wall.end.z-wall.start.z),spans=[];let cursor=0;
            wall.openings.forEach(o=>{if(o.startMeters>cursor)spans.push([cursor,o.startMeters]);cursor=o.endMeters;});
            if(cursor<length)spans.push([cursor,length]);
            ['left','right'].forEach(side=>spans.forEach(([start,end])=>result.push({target:{wallId:wall.wallId,side},
                width:length,height:wall.heightMeters,start,end,color:wall.color,label:wall.label+' / '+side+' / '+start.toFixed(2)+'-'+end.toFixed(2)+' m'})));
        });
        (layout.placements || []).forEach(placement => {
            const entry = (catalog || []).find(e => e.assetId === placement.assetId
                && e.assetDefinitionRevision === placement.assetDefinitionRevision);
            if (!walls.isWallAsset(entry)) return;
            const source = entry.source || entry;
            const definition = source.definition || source.assetDefinition || source;
            const bounds = definition.geometry && definition.geometry.aabb;
            if (!bounds) return;
            const scale = placement.transform && placement.transform.scale || 1;
            const size = axis => (bounds.maximum[axis]-bounds.minimum[axis]) * (typeof scale === 'number' ? scale : scale[axis]);
            ['positive_z','negative_z','positive_x','negative_x'].forEach(face => {
                const width = size(face.endsWith('_z') ? 'x' : 'z'), height = size('y');
                if (![width,height].every(n => Number.isFinite(n) && n >= .05)) return;
                result.push({target:{placementId:placement.placementId,face}, width, height, start:0, end:width,
                    color:placement.appearance && placement.appearance.color,
                    label:(placement.metadata && placement.metadata.instanceLabel || placement.displayName || placement.label || entry.label || entry.displayName || placement.placementId)
                        + ' / ' + face.replace('positive_', '+').replace('negative_', '-').toUpperCase()});
            });
        });
        return result;
    }

    function makeRecord(surface, values, imported, id) {
        if (!surface) throw new Error('No supported wall face is available.');
        if (!imported || !imported.imagePath) throw new Error('Choose an image first.');
        const {width, height, offset, bottom} = values;
        if (![width,height,offset,bottom].every(Number.isFinite) || width <= 0 || height <= 0
                || offset < surface.start-1e-6 || offset+width > surface.end+1e-6
                || bottom < 0 || bottom+height > surface.height+1e-6) {
            throw new Error('The decal must fit inside the selected wall section.');
        }
        const fractions = [offset/surface.width,bottom/surface.height,(offset+width)/surface.width,(bottom+height)/surface.height]
            .map(n => Math.max(0, Math.min(1, n)));
        if (fractions[2]-fractions[0] < .001 || fractions[3]-fractions[1] < .001) throw new Error('The decal region is too small.');
        const label = String(values.label || '').trim();
        if (!label || label.length > 120) throw new Error('Enter a decal name (up to 120 characters).');
        return {artworkId:id, label, imagePath:imported.imagePath,
            uv:values.trim ? imported.uv.slice() : [0,0,1,1], target:clone(surface.target), region:fractions, coverage:1};
    }

    function closeDialog(workspace) { if (workspace.decalDialogClose) workspace.decalDialogClose(); }
    // `prefill` comes from the appearance library: an already-imported sign
    // image ({ imported, label }) and optionally the wall it was dropped on.
    function openDialog(workspace, mode, prefill) {
        const isText = mode === 'lettering', title = isText ? 'Wall lettering' : 'Wall decals';
        const state = workspace.session.getState();
        if (!walls.canEdit(workspace, state)) throw new Error('Finish the active preview or operation before editing decals.');
        if (workspace.decalDialog) { workspace.decalDialog.focus(); return; }
        const document = workspace.document, layout = clone(state.layout), baseRevision = state.draftRevision;
        const available = targets(layout, workspace.assetCatalog), entries = clone(records(layout));
        const previousFocus = document.activeElement, abort = new AbortController();
        let closed = false, applying = false, uploading = false, stale = false, imported = null, bitmap = null;
        let editingId = null, loadSequence = 0, unsubscribe = null;
        function el(tag, attrs, text) {
            const node = document.createElement(tag);
            Object.entries(attrs || {}).forEach(([k,v]) => node.setAttribute(k,v));
            if (text !== undefined) node.textContent = text;
            return node;
        }
        function button(name, icon) {
            const node = el('button', {type:'button', title:name, 'aria-label':name});
            if (icon) node.appendChild(el('img', {src:'/static/assets/facility-layout-ribbon-icons/svg/'+icon+'.svg',alt:'',width:18,height:18}));
            else node.textContent='Close';
            return node;
        }
        const dialog = el('dialog', {class:'ip-flw-decal-dialog', 'aria-label':title});
        workspace.decalDialog = dialog;
        const form = el('form'), header = el('header'), heading = el('h2', {}, title);
        const dismiss = button('Close decals'); header.append(heading,dismiss);form.append(header);
        const body = el('div', {class:'ip-flw-decal-body'}), fields = el('fieldset', {class:'ip-flw-decal-fields'});
        const preview = el('div', {class:'ip-flw-decal-preview'}), canvas = el('canvas', {width:880,height:520,'aria-label':'Wall elevation preview'});
        const dimensions = el('output'); preview.append(canvas,dimensions);body.append(fields,preview);form.append(body);
        function field(label, control) { const node = el('label', {}, label);node.append(control);fields.append(node);return control; }
        const selected = field('Decal', el('select', {'aria-label':'Decal'}));
        selected.append(el('option', {value:''}, 'New decal'));
        entries.filter(art => Boolean(art.lettering) === isText).forEach(art => selected.append(el('option', {value:art.artworkId}, art.label)));
        const name = field('Name', el('input', {type:'text',maxlength:120,'aria-label':'Decal name'}));
        const file = field('Image', el('input', {type:'file',accept:'image/png,image/jpeg','aria-label':'Decal image'}));
        file.parentElement.hidden = isText;
        const text = field('Text', el('textarea', {rows:4,maxlength:1000,'aria-label':'Lettering text'}));
        const reference = field('Reference', el('input', {maxlength:160,'aria-label':'Lettering reference'}));
        const font = field('Font', el('select', {'aria-label':'Lettering font'}));
        ['Arial','Georgia'].forEach(v => font.append(el('option',{value:v},v)));
        const align = field('Alignment', el('select', {'aria-label':'Lettering alignment'}));
        ['center','left','right'].forEach(v => align.append(el('option',{value:v},v)));
        const color = field('Color', el('input', {type:'color',value:'#c99b39','aria-label':'Lettering color'}));
        [text,reference,font,align,color].forEach(n => n.parentElement.hidden = !isText);
        const surface = field('Wall face / section', el('select', {'aria-label':'Wall face'}));
        available.forEach((item,index) => surface.append(el('option', {value:index}, item.label)));
        if (!available.length) surface.append(el('option', {}, 'No wall faces available'));
        const sizeGrid = el('div', {class:'ip-flw-decal-numbers'});fields.append(sizeGrid);
        function number(label) {
            const node = el('label',{},label), input = el('input',{type:'number',step:'any','aria-label':label});
            node.append(input);sizeGrid.append(node);return input;
        }
        const width = number('Max width (m)'), height = number('Max height (m)'), offset = number('From wall start (m)'), bottom = number('Bottom (m)');
        const trimLabel = el('label',{class:'ip-flw-decal-check'}), trim = el('input',{type:'checkbox','aria-label':'Trim transparent margins'});
        trim.checked = true;trimLabel.append(trim,document.createTextNode('Trim transparent margins'));fields.append(trimLabel);
        trimLabel.hidden = isText;
        const status = el('div', {'role':'status','aria-live':'polite',class:'ip-flw-decal-status'});
        const error = el('div', {role:'alert',class:'ip-flw-wall-error'});form.append(status,error);
        const footer = el('footer'), remove = button('Delete decal','trash'), cancel = el('button',{type:'button'},'Cancel');
        const apply = el('button',{type:'submit',class:'ip-flw-primary-action'},'Apply');footer.append(remove,cancel,apply);form.append(footer);dialog.append(form);
        workspace.root.append(dialog);
        function currentSurface() { return available[Number(surface.value)]; }
        function fresh() {
            const current = workspace.session.getState();
            return !closed && !stale && !workspace.destroyed && walls.canEdit(workspace,current)
                && current.layout.layoutId === layout.layoutId && current.draftRevision === baseRevision;
        }
        function close() {
            if (closed) return;
            closed = true; abort.abort();loadSequence++;
            if (unsubscribe) unsubscribe();
            dialog.remove();workspace.decalDialog = null;workspace.decalDialogClose = null;
            if (previousFocus && previousFocus.isConnected) previousFocus.focus();
        }
        workspace.decalDialogClose = close;
        function values() { return {label:name.value,width:Number(width.value),height:Number(height.value),offset:Number(offset.value),bottom:Number(bottom.value),trim:trim.checked}; }
        function textSettings() { return {text:text.value,reference:reference.value,font:font.value,align:align.value,color:color.value}; }
        function candidate() {
            const art = makeRecord(currentSurface(), values(), imported, editingId || 'preview');
            if(isText)art.lettering=lettering.validate(textSettings());
            return art;
        }
        function draw() {
            const ctx = canvas.getContext('2d'), s = currentSurface();
            ctx.clearRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#e4e8eb';ctx.fillRect(0,0,canvas.width,canvas.height);
            if (!s) { dimensions.textContent = ''; return; }
            const scale = Math.min(800/s.width,420/s.height), w=s.width*scale, h=s.height*scale;
            const x=(canvas.width-w)/2, y=(canvas.height-h)/2;
            ctx.fillStyle=s.color || '#45484b';ctx.fillRect(x,y,w,h);
            ctx.fillStyle='#e4e8eb';
            if (s.target.edge !== undefined) {
                const settings = walls.data(layout).settings;
                settings.openings.filter(o=>o.edge===s.target.edge).forEach(o=>ctx.fillRect(x+o.startMeters*scale,y,(o.endMeters-o.startMeters)*scale,h));
            }
            if(s.target.wallId){
                const wall=walls.interiorWalls(layout).find(w=>w.wallId===s.target.wallId);
                wall.openings.forEach(o=>ctx.fillRect(x+o.startMeters*scale,y,(o.endMeters-o.startMeters)*scale,h));
            }
            ctx.strokeStyle='#0878d1';ctx.lineWidth=2;ctx.strokeRect(x+s.start*scale,y,(s.end-s.start)*scale,h);
            dimensions.textContent=s.width.toFixed(2)+' m x '+s.height.toFixed(2)+' m';
            if (!bitmap || !imported) return;
            try {
                const art = candidate(), r=art.region, uv=art.uv;
                const pw=w*(r[2]-r[0]), ph=h*(r[3]-r[1]);
                const bw=bitmap.naturalWidth || bitmap.width,bh=bitmap.naturalHeight || bitmap.height;
                const frame=walls.fittedArtworkFrame(pw,ph,bw,bh,uv);
                ctx.drawImage(bitmap,uv[0]*bw,(1-uv[3])*bh,
                    (uv[2]-uv[0])*bw,(uv[3]-uv[1])*bh,
                    x+r[0]*w+frame.x*pw,y+(1-r[3])*h+frame.y*ph,frame.width*pw,frame.height*ph);
            } catch (_) { /* Field validation supplies the visible error. */ }
        }
        function refresh() {
            let message = '';
            fields.disabled = applying || uploading;
            if(isText && !applying){
                try {
                    bitmap=lettering.render(document,textSettings(),Number(width.value)/Number(height.value));
                    imported={imagePath:'lettering-preview',uv:[0,0,1,1]};
                } catch(e){bitmap=null;imported=null;message=e.message;}
            }
            if (stale || !fresh()) message='The layout changed. Close and reopen Decals before applying.';
            else if (!available.length) message='No wall faces are available in this layout.';
            else if (imported) { try { candidate(); } catch(e) { message=e.message; } }
            error.textContent=message;
            apply.disabled=Boolean(message) || !bitmap || uploading || applying;
            cancel.disabled=applying;dismiss.disabled=applying;
            remove.disabled=!editingId || uploading || applying || !fresh();
            file.disabled=!available.length || uploading || applying || !fresh();
            draw();
        }
        function defaults() {
            const s=currentSurface();if(!s)return;
            width.value=((s.end-s.start)*.9).toFixed(4);height.value=(s.height*.85).toFixed(4);
            offset.value=(s.start+(s.end-s.start)*.05).toFixed(4);bottom.value=(s.height*.075).toFixed(4);
        }
        async function loadImage(info) {
            const sequence=++loadSequence;bitmap=null;refresh();
            const img=new document.defaultView.Image();
            await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=()=>reject(new Error('The decal image could not be loaded.'));img.src=info.imagePath;});
            if (closed || sequence!==loadSequence) return;
            bitmap=img;refresh();
        }
        selected.addEventListener('change', async () => {
            loadSequence++;bitmap=null;imported=null;file.value='';editingId=selected.value || null;
            const art=entries.find(a=>a.artworkId===editingId);
            if (art) {
                const index=available.findIndex(s=>sameTarget(s.target,art.target)
                    && art.region[0]*s.width>=s.start-1e-5 && art.region[2]*s.width<=s.end+1e-5);
                if(index<0){status.textContent='This decal needs a valid wall section.';refresh();return;}
                surface.value=String(index);const s=currentSurface(),r=art.region;
                name.value=art.label;width.value=(r[2]-r[0])*s.width;height.value=(r[3]-r[1])*s.height;
                offset.value=r[0]*s.width;bottom.value=r[1]*s.height;trim.checked=true;imported=clone(art);
                if(isText){const v=art.lettering;text.value=v.text;reference.value=v.reference;font.value=v.font;align.value=v.align;color.value=v.color;}
                else try { await loadImage(imported); } catch(e) { if(!closed)status.textContent=e.message; }
            } else { name.value='';defaults();status.textContent=''; }
            refresh();
        });
        file.addEventListener('change',async()=>{
            if (!file.files[0] || !fresh()) return;
            const chosen=file.files[0];uploading=true;bitmap=null;imported=null;status.textContent='Importing image...';refresh();
            selected.disabled=true;
            try {
                const info=await workspace.session.importDecalImage(chosen,{signal:abort.signal});
                if(!fresh())return;
                imported=info;if(!name.value)name.value=chosen.name.replace(/\.[^.]+$/,'').slice(0,120);
                trim.checked=true;await loadImage(info);
                if(!closed)status.textContent='';
            } catch(e) { if(!closed)status.textContent=e.message; }
            finally { uploading=false;selected.disabled=false;if(!closed)refresh(); }
        });
        surface.addEventListener('change',()=>{defaults();refresh();});
        [name,width,height,offset,bottom,trim,text,reference,font,align,color].forEach(node=>node.addEventListener('input',refresh));
        async function commit(next) {
            if (!fresh() || uploading || applying) { refresh();return; }
            applying=true;refresh();
            try { await workspace.session.setDecals({version:1,artworks:next});close(); }
            catch(e) { status.textContent=e.message; }
            finally { applying=false;if(!closed)refresh(); }
        }
        form.addEventListener('submit',async event=>{
            event.preventDefault();if(apply.disabled)return;
            try {
                const art=candidate();art.artworkId=editingId || 'decal-'+document.defaultView.crypto.randomUUID();
                if(isText){
                    uploading=true;refresh();
                    const image=await new Promise(resolve=>bitmap.toBlob(resolve,'image/png'));
                    if(!image)throw new Error('Lettering image could not be created.');
                    const info=await workspace.session.importDecalImage(image,{signal:abort.signal});
                    if(!fresh())return;
                    art.imagePath=info.imagePath;art.uv=[0,0,1,1];uploading=false;
                }
                await commit(entries.filter(a=>a.artworkId!==editingId).concat([art]));
            } catch(e) { status.textContent=e.message; }
            finally { uploading=false;if(!closed)refresh(); }
        });
        remove.addEventListener('click',()=>{if(!remove.disabled)commit(entries.filter(a=>a.artworkId!==editingId));});
        cancel.addEventListener('click',close);dismiss.addEventListener('click',close);
        dialog.addEventListener('cancel',event=>{event.preventDefault();if(!applying)close();});
        if (typeof workspace.session.subscribe==='function') unsubscribe=workspace.session.subscribe(current=>{
            if(applying || closed)return;
            if(current.layout && current.layout.layoutId!==layout.layoutId){close();return;}
            if(current.draftRevision!==baseRevision)stale=true;
            refresh();
        });
        const selection=state.selection || [];
        const first=available.findIndex(s=>selection.includes(s.target.placementId));
        if(first>=0)surface.value=String(first);
        if(prefill&&prefill.target){
            const chosen=available.findIndex(s=>sameTarget(s.target,prefill.target));
            if(chosen>=0)surface.value=String(chosen);
        }
        defaults();
        if(prefill&&prefill.imported&&!isText){
            imported=clone(prefill.imported);name.value=String(prefill.label||'').slice(0,120);
            if(prefill.aspect>0){
                const s=currentSurface();
                if(s){const w=Math.min((s.end-s.start)*.9,Number(prefill.widthMeters)||.3,s.height*.85*prefill.aspect);
                    width.value=w.toFixed(4);height.value=(w/prefill.aspect).toFixed(4);}
            }
            loadImage(imported).catch(e=>{if(!closed)status.textContent=e.message;});
        }
        refresh();dialog.showModal();name.focus();
    }
    return {records, targets, makeRecord, sameTarget, openDialog, closeDialog};
}));
