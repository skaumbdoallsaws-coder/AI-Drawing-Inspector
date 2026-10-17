(function(root,factory){
    const dialogs=typeof module==='object'&&module.exports?require('./facility_layout_authoring_dialog.js'):root.InspectorProFacilityAuthoringDialog;
    const api=factory(dialogs);
    if(typeof module==='object'&&module.exports)module.exports=api;
    if(root)root.InspectorProFacilityComponentMaterials=api;
}(typeof globalThis!=='undefined'?globalThis:this,function(dialogs){
    'use strict';
    function slots(object){
        const result=[];let index=0;
        object.traverse(node=>{
            if(!node.isMesh||!node.material)return;
            const mesh=index++;
            (Array.isArray(node.material)?node.material:[node.material]).forEach((material,slot)=>{
                if(!material||!material.color)return;
                result.push({key:'m'+mesh+'-s'+slot,node,material,slot,
                    label:(node.name||'Mesh '+(mesh+1))+' / '+(material.name||'Material '+(slot+1))});
            });
        });
        return result;
    }
    function apply(object,config,representation){
        if(!config||config.representation!==representation)return;
        const byKey=new Map(config.overrides.map(v=>[v.key,v]));
        slots(object).forEach(item=>{
            const v=byKey.get(item.key);if(!v)return;
            const m=item.material;m.color.set(v.color);m.roughness=v.roughness;m.metalness=v.metalness;
            m.userData=m.userData||{};m.userData.facilityComponentOverride=true;
        });
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
    return {slots,apply,open};
}));
