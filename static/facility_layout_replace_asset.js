(function(root,factory){
    const dialogs=typeof module==='object'&&module.exports?require('./facility_layout_authoring_dialog.js'):root.InspectorProFacilityAuthoringDialog;
    const api=factory(dialogs);
    if(typeof module==='object'&&module.exports)module.exports=api;
    if(root)root.InspectorProFacilityReplaceAsset=api;
}(typeof globalThis!=='undefined'?globalThis:this,function(dialogs){
    'use strict';
    function bounds(entry){
        const source=entry?.source||entry,def=source&&(source.definition||source.assetDefinition||source),geometry=def?.geometry;
        if(geometry?.aabb)return geometry.aabb;
        const points=geometry?.footprintPolygons?.flat(),height=geometry?.heightInterval;
        if(!points?.length||!height)return null;
        return {minimum:{x:Math.min(...points.map(p=>p.x)),y:height.minimumY,z:Math.min(...points.map(p=>p.z))},
            maximum:{x:Math.max(...points.map(p=>p.x)),y:height.maximumY,z:Math.max(...points.map(p=>p.z))}};
    }
    function dimensions(entry,scale=1){
        const b=bounds(entry);if(!b)return null;
        const result={};for(const axis of ['x','y','z']){result[axis]=(b.maximum[axis]-b.minimum[axis])*scale;if(!Number.isFinite(result[axis])||result[axis]<=0)return null;}return result;
    }
    function open(workspace){
        const state=workspace.session.getState(),selected=state.layout.placements.filter(p=>state.selection.includes(p.placementId));
        if(selected.length!==1)throw new Error('Select one asset to replace.');
        const original=selected[0],catalog=workspace.assetCatalog||[],old=catalog.find(e=>e.assetId===original.assetId&&e.assetDefinitionRevision===original.assetDefinitionRevision);
        const candidates=catalog.filter(e=>(e.assetId!==original.assetId||e.assetDefinitionRevision!==original.assetDefinitionRevision)&&dimensions(e));
        let verified=null,sequence=0;
        const ui=dialogs.open(workspace,'Replace Asset',async()=>{
            const op=operation();if(JSON.stringify(op)!==verified)throw new Error('Check the replacement placement first.');
            await workspace.session.replaceAsset(original.placementId,op);
        });
        ui.disable(true);
        const search=ui.field('Search library','search','');
        const model=ui.field('Replacement asset','select','',[]);
        const keep=ui.field('Keep object color','checkbox');keep.checked=true;
        const canvas=ui.el('canvas',{width:600,height:450,'aria-label':'Current and replacement footprint comparison'});ui.body.append(canvas);
        const summary=ui.el('output');ui.body.append(summary);
        const check=ui.el('button',{type:'button'},'Check placement');ui.body.append(check);
        function entry(){return model.value===''?null:candidates[Number(model.value)];}
        function operation(){const e=entry();if(!e)throw new Error('Choose a library asset with measured dimensions.');return {assetId:e.assetId,assetDefinitionRevision:e.assetDefinitionRevision,keepAppearance:keep.checked};}
        function draw(){
            sequence++;verified=null;ui.disable(true);ui.message('');
            const replacement=entry(),scale=original.transform.scale||1,a=dimensions(old,scale),b=dimensions(replacement,scale);
            check.disabled=!b;const c=canvas.getContext('2d');c.clearRect(0,0,600,450);c.fillStyle='#e4e8eb';c.fillRect(0,0,600,450);
            const all=[old,replacement].filter(v=>bounds(v));
            if(all.length){
                const minX=Math.min(...all.map(v=>bounds(v).minimum.x)),maxX=Math.max(...all.map(v=>bounds(v).maximum.x));
                const minZ=Math.min(...all.map(v=>bounds(v).minimum.z)),maxZ=Math.max(...all.map(v=>bounds(v).maximum.z));
                const s=Math.min(520/Math.max(.01,maxX-minX),350/Math.max(.01,maxZ-minZ));
                function rect(e,color,dash){const b=bounds(e);if(!b)return;c.strokeStyle=color;c.lineWidth=3;c.setLineDash(dash);c.strokeRect(40+(b.minimum.x-minX)*s,40+(b.minimum.z-minZ)*s,(b.maximum.x-b.minimum.x)*s,(b.maximum.z-b.minimum.z)*s);}
                rect(old,'#697780',[8,5]);rect(replacement,'#0878d1',[]);
            }
            const text=d=>d?d.x.toFixed(2)+' x '+d.z.toFixed(2)+' x '+d.y.toFixed(2)+' m':'Unavailable';
            summary.textContent='Current: '+text(a)+' | Replacement: '+text(b);
        }
        function filter(){const previous=model.value,term=search.value.trim().toLowerCase();model.replaceChildren();
            candidates.forEach((e,i)=>{const label=e.label||e.displayName||e.definition?.displayName||e.assetId;if(!term||label.toLowerCase().includes(term))model.append(ui.el('option',{value:i},label));});
            if(Array.from(model.options).some(o=>o.value===previous))model.value=previous;draw();}
        model.addEventListener('change',draw);search.addEventListener('input',filter);keep.addEventListener('change',draw);
        check.addEventListener('click',async()=>{
            if(!ui.fresh())return;const seq=++sequence;check.disabled=true;ui.message('Checking placement...');
            try{const op=operation();await workspace.session.previewAssetReplacement(original.placementId,op);
                if(seq!==sequence||!ui.fresh())return;verified=JSON.stringify(op);ui.disable(false);ui.message('Placement checked.');
            }catch(e){if(seq===sequence){ui.message(e.message);ui.disable(true);}}
            finally{if(seq===sequence)check.disabled=false;}
        });filter();
        if(!candidates.length)ui.message('No alternative library assets with measured dimensions are available.');
    }
    return {bounds,dimensions,open};
}));
