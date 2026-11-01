(function(root,factory){
    const dialogs=typeof module==='object'&&module.exports?require('./facility_layout_authoring_dialog.js'):root.InspectorProFacilityAuthoringDialog;
    const api=factory(dialogs);
    if(typeof module==='object'&&module.exports)module.exports=api;
    if(root)root.InspectorProFacilityComponentMaterials=api;
}(typeof globalThis!=='undefined'?globalThis:this,function(dialogs){
    'use strict';
    // Each part (mesh primitive) has two keys: the legacy traversal key mN-sN,
    // valid only for the representation it was authored on, and the stable
    // p:<node path>#<primitive> key tagged on load from the glTF node names.
    function slots(object){
        const result=[];let index=0;
        object.traverse(node=>{
            if(!node.isMesh||!node.material)return;
            const mesh=index++;
            (Array.isArray(node.material)?node.material:[node.material]).forEach((material,slot)=>{
                if(!material||!material.color)return;
                const stable=node.userData&&node.userData.facilityPartKey;
                const legacyKey='m'+mesh+'-s'+slot;
                result.push({key:stable&&slot===0?stable:legacyKey,legacyKey,node,material,slot,
                    label:(node.userData&&node.userData.facilityPartLabel||node.name||'Mesh '+(mesh+1))+' / '+String(material.name||'Material '+(slot+1)).replace(/:FacilityNeutral$/,'')});
            });
        });
        return result;
    }
    // A finished part keeps the depth offset of the material it replaces. Authored
    // surfaces draw pulled slightly forward; a part that lost the offset sank behind
    // its neighbours (a lamp lens 1.5 cm under its housing vanished from below).
    function keepDepthOffset(from,to){
        if(!from||!to||!from.polygonOffset)return to;
        to.polygonOffset=true;to.polygonOffsetFactor=from.polygonOffsetFactor;to.polygonOffsetUnits=from.polygonOffsetUnits;
        return to;
    }
    // A model can name a library finish for one of its parts: its material's glTF
    // extras.facilityDefaultFinish (a light's lens that comes lit). Record them on a
    // freshly loaded model, before any finish replaces a material; copies keep them.
    // Parts can share extras.facilityFinishGroup (a stack light's three lamps, one of
    // which shows the cell's state): a default in a group shows only while no part of
    // that group has a finish of its own.
    function recordDefaults(object){
        const parts=[],groups=[];
        slots(object).forEach(item=>{
            const data=item.material.userData||{};
            const id=data.facilityDefaultFinish,group=typeof data.facilityFinishGroup==='string'&&data.facilityFinishGroup?data.facilityFinishGroup:null;
            if(!item.key.startsWith('p:'))return;
            if(group&&!groups.some(v=>v.key===item.key))groups.push({key:item.key,legacyKey:item.legacyKey,group});
            if(typeof id==='string'&&id&&!parts.some(v=>v.key===item.key))parts.push(group?{key:item.key,appearanceId:id,group}:{key:item.key,appearanceId:id});
        });
        object.userData=object.userData||{};
        object.userData.facilityDefaultParts=parts;
        object.userData.facilityFinishGroups=groups;
        return parts;
    }
    function defaults(object){
        const parts=object&&object.userData&&object.userData.facilityDefaultParts;
        return Array.isArray(parts)?parts:[];
    }
    // Precedence: a part override beats the model's default for that part, which
    // beats the placement's finish, which beats the asset's own material.
    // `finishes.materialFor(override, mesh)` builds library finishes; without it,
    // appearance overrides are skipped rather than guessed.
    function apply(object,config,representation,finishes){
        const own=config&&Array.isArray(config.overrides)?config.overrides:[];
        const parts=defaults(object);
        if(!own.length&&!parts.length)return [];
        const sameRepresentation=Boolean(config)&&config.representation===representation;
        const byKey=new Map(own.filter(v=>sameRepresentation||!/^m\d/.test(v.key)).map(v=>[v.key,v]));
        const groups=Array.isArray(object.userData&&object.userData.facilityFinishGroups)?object.userData.facilityFinishGroups:[];
        const set=new Set(groups.filter(v=>byKey.has(v.key)||(sameRepresentation&&byKey.has(v.legacyKey))).map(v=>v.group));
        const byDefault=new Map(parts.filter(v=>!v.group||!set.has(v.group)).map(v=>[v.key,v]));
        const applied=[];
        slots(object).forEach(item=>{
            const v=byKey.get(item.key)||(sameRepresentation?byKey.get(item.legacyKey):null)||byDefault.get(item.key);if(!v)return;
            if(v.appearanceId){
                const material=finishes&&finishes.materialFor(v,item.node);
                if(!material)return;
                keepDepthOffset(item.material,material);
                material.userData=material.userData||{};material.userData.facilityComponentOverride=true;
                if(Array.isArray(item.node.material)){const list=item.node.material.slice();list[item.slot]=material;item.node.material=list;}
                else item.node.material=material;
                applied.push(v.key);return;
            }
            let m=item.material;
            // A placement finish shares one material across its parts; copy it so
            // the override changes only this part.
            if(m.userData&&m.userData.facilityAppearanceFinish&&typeof m.clone==='function'){
                m=m.clone();m.userData=Object.assign({},item.material.userData,{facilityAppearanceFinish:false});
                if(Array.isArray(item.node.material)){const list=item.node.material.slice();list[item.slot]=m;item.node.material=list;}
                else item.node.material=m;
            }
            m.color.set(v.color);m.roughness=v.roughness;m.metalness=v.metalness;
            m.userData=m.userData||{};m.userData.facilityComponentOverride=true;
            applied.push(v.key);
        });
        return applied;
    }
    // Percent-encode every UTF-8 byte outside [A-Za-z0-9._-]; must match the
    // server's component inventory so agents and the browser agree on keys.
    function encodeName(name){
        const bytes=typeof TextEncoder==='function'?Array.from(new TextEncoder().encode(name)):Array.from(unescape(encodeURIComponent(name))).map(c=>c.charCodeAt(0));
        return bytes.map(b=>(b>=48&&b<=57)||(b>=65&&b<=90)||(b>=97&&b<=122)||b===46||b===95||b===45?String.fromCharCode(b):'%'+b.toString(16).toUpperCase().padStart(2,'0')).join('');
    }
    function nodePaths(json){
        const nodes=json.nodes||[],scenes=json.scenes||[],paths=new Map();
        const roots=(scenes[json.scene||0]||{}).nodes||[];
        function visit(children,prefix){
            const names=children.map(i=>nodes[i]&&typeof nodes[i].name==='string'&&nodes[i].name?nodes[i].name:null);
            const counts=new Map(),seen=new Map();
            names.forEach(n=>{if(n!==null)counts.set(n,(counts.get(n)||0)+1);});
            children.forEach((index,i)=>{
                if(paths.has(index)||!nodes[index])return;
                const name=names[i];let segment;
                if(name===null)segment='@'+index;
                else{const ordinal=seen.get(name)||0;seen.set(name,ordinal+1);segment=encodeName(name)+(counts.get(name)>1?'~'+ordinal:'');}
                const path=prefix?prefix+'/'+segment:segment;
                paths.set(index,{path,label:nodes[index].name||('Node '+index)});
                visit(nodes[index].children||[],path);
            });
        }
        visit(roots,'');
        return paths;
    }
    // Tag every mesh in a freshly loaded glTF with its stable part key. Must run
    // before the scene is cloned: the loader's associations do not survive clones.
    function annotatePartKeys(gltf){
        const parser=gltf&&gltf.parser,scene=gltf&&gltf.scene;
        if(!parser||!parser.json||!parser.associations||!scene)return 0;
        const paths=nodePaths(parser.json);let count=0;
        scene.traverse(object=>{
            if(!object.isMesh)return;
            const own=parser.associations.get(object)||{};
            const nodeIndex=own.nodes!==undefined?own.nodes:(parser.associations.get(object.parent)||{}).nodes;
            if(nodeIndex===undefined||!paths.has(nodeIndex))return;
            const primitive=own.primitives!==undefined?own.primitives:0;
            let key='p:'+paths.get(nodeIndex).path+'#'+primitive;
            if(key.length>512)key='p:@'+nodeIndex+'#'+primitive;
            object.userData=object.userData||{};
            object.userData.facilityPartKey=key;
            object.userData.facilityPartLabel=paths.get(nodeIndex).label;
            count+=1;
        });
        return count;
    }
    async function open(workspace){
        const state=workspace.session.getState(),ids=state.selection||[];
        const selected=state.layout.placements.filter(p=>ids.includes(p.placementId));
        if(selected.length!==1)throw new Error('Select one asset to edit its components.');
        const placement=selected[0],adapter=workspace.threeAdapter;
        if(!adapter||!adapter.getComponentMaterials)throw new Error('Component materials require the 3D renderer.');
        let model=null,overrides=new Map();
        const ui=dialogs.open(workspace,'Component Materials',async()=>{
            const values=Array.from(overrides.values());
            await workspace.session.setComponentMaterials(placement.placementId,values.length?{representation:model.representation,overrides:values}:null);
        });
        ui.disable(true);ui.message('Loading model components...');
        ui.cleanup(()=>adapter.highlightComponent(null));
        try{
            workspace._setViewMode('3d');await workspace.controller.ready();
            model=await adapter.getComponentMaterials(placement.placementId);
            if(!ui.fresh())return;
            if(!model.slots.length)throw new Error('No editable components are available in this model.');
            const saved=placement.componentMaterials;
            if(saved&&saved.representation!==model.representation)throw new Error('The loaded model representation differs from its saved finish. Load the original representation first.');
            overrides=new Map((saved?saved.overrides:[]).map(v=>[v.key,{...v}]));
            const component=ui.field('Component','select',model.slots[0].key,model.slots.map(v=>({value:v.key,label:v.label})));
            const color=ui.field('Component color','color','#c99b39'),roughness=ui.field('Roughness','range',.6),metalness=ui.field('Metalness','range',.2);
            const reset=ui.el('button',{type:'button',title:'Restore this component','aria-label':'Restore this component'});
            reset.append(ui.el('img',{src:'/static/assets/facility-layout-ribbon-icons/svg/arrow-u-up-left.svg',alt:'',width:18,height:18}));ui.body.append(reset);
            function selectedValue(){return model.slots.find(v=>v.key===component.value);}
            function show(){const v=overrides.get(component.value)||selectedValue();color.value=v.color;roughness.value=v.roughness;metalness.value=v.metalness;adapter.highlightComponent(placement.placementId,component.value);}
            component.addEventListener('change',show);
            [color,roughness,metalness].forEach(n=>n.addEventListener('input',()=>overrides.set(component.value,{key:component.value,color:color.value,roughness:Number(roughness.value),metalness:Number(metalness.value)})));
            reset.addEventListener('click',()=>{overrides.delete(component.value);show();});
            ui.message('');ui.disable(false);show();
        }catch(e){ui.message(e.message);ui.disable(true);}
    }
    return {slots,apply,recordDefaults,defaults,keepDepthOffset,open,encodeName,nodePaths,annotatePartKeys};
}));
