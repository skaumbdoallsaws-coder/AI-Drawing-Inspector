(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityWalls = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    function data(layout) { return layout && layout.extensions && layout.extensions.facilityPerimeterWalls; }
    function interiorWalls(layout) { return layout?.extensions?.facilityInteriorWalls?.walls || []; }
    function volumes(layout, floorY=0) {
        const value=data(layout), result=value&&value.version===1?value.panels.map((polygon,index)=>({
            id:'layout-perimeter-wall-'+index,placementId:'layout-perimeter-wall-'+index,polygon,
            minimumY:floorY,maximumY:floorY+value.settings.heightMeters,color:'#b0bac1'})):[];
        interiorWalls(layout).forEach(wall=>wall.panels.forEach((polygon,index)=>{
            const id='layout-interior-wall-'+wall.wallId+'-'+index;
            result.push({id,placementId:id,polygon,minimumY:wall.baseElevation,maximumY:wall.baseElevation+wall.heightMeters,color:wall.color});
        }));
        return result;
    }
    function panels(layout) {
        const value=data(layout),perimeter=value&&value.version===1?value.panels:[];
        const interior=interiorWalls(layout).flatMap(w=>w.panels);
        return interior.length?perimeter.concat(interior):perimeter;
    }
    function exteriorSurfaces(layout) {
        const wall = data(layout), settings = wall && wall.settings;
        const finish = settings && settings.exteriorFinish;
        if (!settings || (!finish && !settings.interiorColor)) return [];
        const plan = layout.extensions.facilityPlan;
        const boundary = settings.boundarySource === 'polygon' ? settings.boundary
            : [{x:0,z:0},{x:plan.widthMeters,z:0},{x:plan.widthMeters,z:plan.depthMeters},{x:0,z:plan.depthMeters}];
        const area = boundary.reduce((sum, a, i) => {
            const b = boundary[(i + 1) % boundary.length]; return sum + a.x*b.z-b.x*a.z;
        }, 0);
        const side = area > 0 ? 1 : -1;
        const surfaces = [], thickness = settings.thicknessMeters / 2, height = settings.heightMeters;
        function rect(edge, start, width, bottom, h, color, offset = .003, extra = {}, facing = 'exterior') {
            const a = boundary[edge], b = boundary[(edge+1)%boundary.length];
            const length = Math.hypot(b.x-a.x,b.z-a.z), tx = (b.x-a.x)/length, tz = (b.z-a.z)/length;
            const direction = side * (facing === 'interior' ? -1 : 1);
            const nx = direction*tz, nz = -direction*tx;
            surfaces.push(Object.assign({x:a.x+tx*(start+width/2)+nx*(thickness+offset),
                z:a.z+tz*(start+width/2)+nz*(thickness+offset),y:bottom+h/2,
                width,height:h,nx,nz,color,edge},extra));
        }
        boundary.forEach((a, edge) => {
            const b=boundary[(edge+1)%boundary.length],length=Math.hypot(b.x-a.x,b.z-a.z);
            const openings=settings.openings.filter(o=>o.edge===edge).sort((a,b)=>a.startMeters-b.startMeters);
            const spans=[];let cursor=-thickness;
            openings.forEach(o=>{if(o.startMeters>cursor)spans.push([cursor,o.startMeters]);cursor=o.endMeters;});
            if(cursor<length+thickness)spans.push([cursor,length+thickness]);
            spans.forEach(([start,end])=>{
                if(settings.interiorColor)rect(edge,start,end-start,0,height,settings.interiorColor,.002,{},'interior');
                if(!finish)return;
                rect(edge,start,end-start,0,height,finish.jointColor,.001);
                const gap=finish.jointWidthMeters/2;
                for(let x=Math.floor(start/finish.panelWidthMeters)*finish.panelWidthMeters;x<end;x+=finish.panelWidthMeters) {
                    const left=Math.max(start,x)+gap,right=Math.min(end,x+finish.panelWidthMeters)-gap;
                    for(let y=0;y<height;y+=finish.panelHeightMeters) {
                        const top=Math.min(height,y+finish.panelHeightMeters)-gap;
                        if(right>left&&top>y+gap)rect(edge,left,right-left,y+gap,top-y-gap,finish.color);
                    }
                }
            });
        });
        if(!finish)return surfaces;
        (finish.accentStrips||[]).forEach(a=>rect(a.edge,a.startMeters,a.widthMeters,0,height,a.color,.006));
        (finish.artworks||[]).forEach(a=>{
            const facing = a.side || 'exterior';
            if(a.backingColor)rect(a.edge,a.startMeters,a.widthMeters,a.bottomMeters,a.heightMeters,a.backingColor,.009,{},facing);
            if(a.borderColor) {
                const t=.025;
                rect(a.edge,a.startMeters,t,a.bottomMeters,a.heightMeters,a.borderColor,.011,{},facing);
                rect(a.edge,a.startMeters+a.widthMeters-t,t,a.bottomMeters,a.heightMeters,a.borderColor,.011,{},facing);
                rect(a.edge,a.startMeters,a.widthMeters,a.bottomMeters,t,a.borderColor,.011,{},facing);
                rect(a.edge,a.startMeters,a.widthMeters,a.bottomMeters+a.heightMeters-t,t,a.borderColor,.011,{},facing);
            }
            rect(a.edge,a.startMeters,a.widthMeters,a.bottomMeters,a.heightMeters,'#ffffff',.014,{artwork:a},facing);
        });
        return surfaces;
    }
    function isWallAsset(entry) {
        if (!entry) return false;
        const source = entry.source || entry;
        const definition = source.definition || source.assetDefinition || source;
        const tags = [].concat(entry.tags || [], definition.tags || []);
        return definition.structureKind === 'wall' || entry.structureKind === 'wall'
            || (Array.isArray(tags) && tags.includes('wall'));
    }
    function fittedArtworkFrame(width, height, imageWidth, imageHeight, uv) {
        const ratio = imageWidth * (uv[2]-uv[0]) / (imageHeight * (uv[3]-uv[1]));
        if (![width,height,ratio].every(n=>Number.isFinite(n)&&n>0)) throw new Error('Invalid artwork size');
        const w = Math.min(width, height*ratio), h = w/ratio;
        return {x:(1-w/width)/2, y:(1-h/height)/2, width:w/width, height:h/height};
    }
    function fittedArtworks(layout) {
        const wall = data(layout), finish = wall && wall.settings && wall.settings.exteriorFinish;
        const decals = layout && layout.extensions && layout.extensions.facilityDecals;
        return [].concat(finish && finish.fittedArtworks || [], decals && decals.artworks || []);
    }
    function fittedArtworkSurfaces(layout, resolveWall) {
        const artworks = fittedArtworks(layout);
        if (!artworks.length) return [];
        const wall = data(layout), settings = wall && wall.settings;
        const plan = layout.extensions && layout.extensions.facilityPlan;
        const boundary = !settings ? [] : settings.boundarySource === 'polygon' ? settings.boundary
            : [{x:0,z:0},{x:plan.widthMeters,z:0},{x:plan.widthMeters,z:plan.depthMeters},{x:0,z:plan.depthMeters}];
        const winding = Math.sign(boundary.reduce((n,a,i)=>{
            const b=boundary[(i+1)%boundary.length]; return n+a.x*b.z-b.x*a.z;
        },0));
        return artworks.map(art=>{
            const t=art.target, r=art.region, coverage=art.coverage;
            const midU=(r[0]+r[2])/2, midV=(r[1]+r[3])/2;
            if(t.wallId){
                const w=interiorWalls(layout).find(w=>w.wallId===t.wallId);if(!w)return null;
                const dx=w.end.x-w.start.x,dz=w.end.z-w.start.z,length=Math.hypot(dx,dz),sign=t.side==='left'?1:-1;
                const nx=-dz/length*sign,nz=dx/length*sign;
                return {artwork:art,x:w.start.x+midU*dx+nx*(w.thicknessMeters/2+.014),
                    z:w.start.z+midU*dz+nz*(w.thicknessMeters/2+.014),
                    y:w.baseElevation-(layout.coordinateFrame?.floorElevation||0)+midV*w.heightMeters,nx,nz,
                    width:length*(r[2]-r[0])*coverage,height:w.heightMeters*(r[3]-r[1])*coverage};
            }
            if (Object.prototype.hasOwnProperty.call(t,'edge')) {
                const a=boundary[t.edge], b=boundary[(t.edge+1)%boundary.length];
                if (!a || !b) return null;
                const length=Math.hypot(b.x-a.x,b.z-a.z), tx=(b.x-a.x)/length, tz=(b.z-a.z)/length;
                const direction=winding*(t.side==='interior'?-1:1), nx=direction*tz, nz=-direction*tx;
                const start=r[0]*length, end=r[2]*length;
                if (settings.openings.some(o=>o.edge===t.edge&&start<o.endMeters-1e-6&&end>o.startMeters+1e-6)) return null;
                return {artwork:art, x:a.x+midU*(b.x-a.x)+nx*(settings.thicknessMeters/2+.014),
                    y:midV*settings.heightMeters,z:a.z+midU*(b.z-a.z)+nz*(settings.thicknessMeters/2+.014),
                    nx,nz,width:(end-start)*coverage,height:settings.heightMeters*(r[3]-r[1])*coverage};
            }
            const resolved=resolveWall && resolveWall(t.placementId);
            if (!resolved || !isWallAsset(resolved.entry) || !resolved.bounds) return null;
            const min=resolved.bounds.minimum,max=resolved.bounds.maximum;
            const normalX=t.face.endsWith('_x'), positive=t.face.startsWith('positive');
            const nx=normalX?(positive?1:-1):0,nz=normalX?0:(positive?1:-1);
            const tangent=normalX?'z':'x', normal=normalX?'x':'z';
            const length=max[tangent]-min[tangent], height=max.y-min.y;
            const p={x:0,y:min.y+midV*height,z:0};
            p[tangent]=min[tangent]+midU*length;
            p[normal]=positive?max[normal]+.014:min[normal]-.014;
            return Object.assign({artwork:art,placement:resolved.placement,nx,nz,
                width:length*(r[2]-r[0])*coverage,height:height*(r[3]-r[1])*coverage},p);
        }).filter(Boolean);
    }
    function canEdit(workspace, state = workspace.state || workspace.session.getState()) {
        return !workspace.destroyed && !workspace.suspended && workspace.capabilities.manualAuthoring && state.loaded
            && !state.busy && !state.conflict && !state.generatedDraft && !state.layoutProposal
            && !state.placementAlternatives && !state.designProposalDraft && !workspace.constructionPreview && !workspace.activityRequestPending
            && !(workspace.generationPlanningView && workspace.generationPlanningView.activeLayout());
    }
    function openDialog(workspace) {
        if (!canEdit(workspace)) throw new Error('Finish the active preview or operation before editing walls.');
        if (workspace.wallDialog) { workspace.wallDialog.focus(); return; }
        const document = workspace.document, state = workspace.session.getState();
        const baseRevision = state.draftRevision, layoutId = state.layout.layoutId;
        const previous = data(state.layout), selected = workspace._selectedZoneRecord();
        const catalog = Array.isArray(workspace.assetCatalog) ? workspace.assetCatalog : [];
        const legacyPerimeter = !previous && (state.layout.placements || []).some(placement => {
            const entry = catalog.find(item => item.assetId === placement.assetId);
            const definition = entry && (entry.definition || entry.assetDefinition || entry);
            return isWallAsset(entry) && [].concat(entry.tags || [], definition.tags || []).includes('perimeter');
        });
        const settings = previous ? previous.settings : { boundarySource: 'plan', heightMeters: 6, thicknessMeters: 0.25, openings: [] };
        const focusReturn = document.activeElement;
        function el(tag, attrs, text) {
            const node = document.createElement(tag);
            Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value));
            if (text !== undefined) node.textContent = text;
            return node;
        }
        const dialog = el('dialog', { class: 'ip-flw-wall-dialog', 'aria-label': 'Perimeter walls' });
        workspace.wallDialog = dialog;
        const form = el('form'); dialog.appendChild(form);
        form.appendChild(el('h2', {}, 'Perimeter walls'));
        const source = el('select', { 'aria-label': 'Wall boundary' });
        source.appendChild(el('option', { value: 'plan' }, 'Facility plan boundary'));
        if (settings.boundarySource === 'polygon') source.appendChild(el('option', { value: 'saved' }, 'Saved polygon boundary'));
        if (selected) source.appendChild(el('option', { value: 'selected' }, 'Boundary snapshot: ' + selected.label));
        source.value = settings.boundarySource === 'polygon' ? 'saved' : 'plan';
        function field(label, input) {
            const row = el('label', { class: 'ip-flw-wall-field' }, label);
            row.appendChild(input); form.appendChild(row); return input;
        }
        field('Boundary', source);
        function number(label, value, min, max) {
            const input = el('input', { type: 'number', step: '0.01', min, max, required: '', 'aria-label': label });
            input.value = value; return field(label, input);
        }
        const height = number('Height (m)', settings.heightMeters, 0.5, 30);
        const thickness = number('Thickness (m)', settings.thicknessMeters, 0.05, 2);
        const interior = el('input', {type:'checkbox','aria-label':'Interior paint'});
        interior.checked = Boolean(settings.interiorColor); field('Interior paint',interior);
        const interiorColor = el('input', {type:'color','aria-label':'Interior color'});
        interiorColor.value = settings.interiorColor || '#b0bac1';
        interiorColor.disabled = !interior.checked; field('Interior color',interiorColor);
        interior.addEventListener('change',()=>{interiorColor.disabled=!interior.checked;});
        const exterior = el('input', {type:'checkbox','aria-label':'Exterior finish'});
        exterior.checked = Boolean(settings.exteriorFinish); field('Exterior finish',exterior);
        const exteriorColor = el('input', {type:'color','aria-label':'Exterior color'});
        exteriorColor.value = settings.exteriorFinish ? settings.exteriorFinish.color : '#282b2d';
        exteriorColor.disabled = !exterior.checked; field('Exterior color',exteriorColor);
        exterior.addEventListener('change',()=>{exteriorColor.disabled=!exterior.checked;});
        form.appendChild(el('h3', {}, 'Openings'));
        const headings = el('div', { class: 'ip-flw-wall-opening ip-flw-wall-opening-headings' });
        ['Edge', 'From (m)', 'To (m)', ''].forEach(label => headings.appendChild(el('span', {}, label)));
        form.appendChild(headings);
        const rows = el('div', { class: 'ip-flw-wall-openings' }); form.appendChild(rows);
        let openings = [];
        function boundary() {
            if (source.value === 'saved') return settings.boundary;
            if (source.value === 'selected') return selected.boundary;
            const plan = state.layout.extensions && state.layout.extensions.facilityPlan;
            if (!plan) throw new Error('Set the facility plan dimensions first.');
            return [{x:0,z:0},{x:plan.widthMeters,z:0},{x:plan.widthMeters,z:plan.depthMeters},{x:0,z:plan.depthMeters}];
        }
        function addOpening(value) {
            if (openings.length >= 128) return;
            const points = boundary(), row = el('div', { class: 'ip-flw-wall-opening' });
            const edge = el('select', { 'aria-label': 'Opening edge' });
            points.forEach((a, i) => { const b = points[(i + 1) % points.length];
                edge.appendChild(el('option', { value: i }, `${i + 1}: (${a.x}, ${a.z}) to (${b.x}, ${b.z})`)); });
            edge.value = value.edge;
            const start = el('input', { type: 'number', min: 0, step: '0.01', required: '', 'aria-label': 'Opening start (m)' });
            const end = el('input', { type: 'number', min: 0, step: '0.01', required: '', 'aria-label': 'Opening end (m)' });
            start.value = value.startMeters; end.value = value.endMeters;
            function limit() { const a = points[Number(edge.value)], b = points[(Number(edge.value)+1)%points.length];
                start.max = end.max = Math.hypot(b.x-a.x,b.z-a.z); }
            limit(); edge.addEventListener('change', limit);
            const remove = el('button', { type: 'button', title: 'Remove opening', 'aria-label': 'Remove opening' }, 'x');
            const entry = { edge, start, end };
            remove.addEventListener('click', () => { openings = openings.filter(item => item !== entry); row.remove(); });
            row.append(edge, start, end, remove); rows.appendChild(row); openings.push(entry);
        }
        const add = el('button', { type: 'button' }, 'Add opening'); form.appendChild(add);
        const error = el('p', { role: 'alert', class: 'ip-flw-wall-error' }); form.appendChild(error);
        function showError(problem) { error.textContent = problem.message || String(problem); }
        add.addEventListener('click', () => { try { addOpening({edge:0,startMeters:1,endMeters:4}); } catch (problem) { showError(problem); } });
        source.addEventListener('change', () => { rows.replaceChildren(); openings = []; });
        settings.openings.forEach(addOpening);
        const footer = el('footer'); form.appendChild(footer);
        const removeWalls = el('button', { type: 'button' }, 'Remove perimeter walls');
        removeWalls.disabled = !previous; footer.appendChild(removeWalls);
        const cancel = el('button', { type: 'button' }, 'Cancel'); footer.appendChild(cancel);
        const apply = el('button', { type: 'submit' }, 'Apply'); footer.appendChild(apply);
        function close() { dialog.close(); dialog.remove(); workspace.wallDialog = null;
            if (focusReturn && focusReturn.isConnected) focusReturn.focus(); }
        cancel.addEventListener('click', close);
        dialog.addEventListener('cancel', event => { event.preventDefault(); if (!apply.disabled) close(); });
        async function commit(value) {
            try {
                const current = workspace.session.getState();
                if (!canEdit(workspace, current) || current.layout.layoutId !== layoutId || current.draftRevision !== baseRevision)
                    throw new Error('The layout changed. Close and reopen the wall settings.');
                apply.disabled = cancel.disabled = removeWalls.disabled = true;
                await workspace.session.setPerimeterWalls(value);
                workspace.layerVisibility.walls = true; workspace._applyLayerVisibility(); close();
            } catch (problem) {
                apply.disabled = cancel.disabled = false; removeWalls.disabled = !previous; showError(problem);
            }
        }
        removeWalls.addEventListener('click', () => commit(null));
        form.addEventListener('submit', event => {
            event.preventDefault();
            try {
                const value = { boundarySource: source.value === 'plan' ? 'plan' : 'polygon',
                    heightMeters: Number(height.value), thicknessMeters: Number(thickness.value),
                    openings: openings.map(item => ({edge:Number(item.edge.value),startMeters:Number(item.start.value),endMeters:Number(item.end.value)})) };
                if (legacyPerimeter && value.boundarySource === 'plan')
                    throw new Error('This layout already has placed perimeter walls. Remove those assets before creating another perimeter.');
                if (value.boundarySource === 'polygon') value.boundary = boundary();
                if (interior.checked) value.interiorColor = interiorColor.value;
                if (exterior.checked) value.exteriorFinish = Object.assign({},settings.exteriorFinish||{},{color:exteriorColor.value});
                commit(value);
            } catch (problem) { showError(problem); }
        });
        workspace.root.appendChild(dialog); dialog.showModal(); source.focus();
    }
    return { data, panels, volumes, interiorWalls, exteriorSurfaces, fittedArtworks, fittedArtworkSurfaces, fittedArtworkFrame, isWallAsset, canEdit, openDialog };
}));
