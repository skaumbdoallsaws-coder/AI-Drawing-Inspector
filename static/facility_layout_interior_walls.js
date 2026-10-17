(function(root,factory){
    const dialogs=typeof module==='object'&&module.exports?require('./facility_layout_authoring_dialog.js'):root.InspectorProFacilityAuthoringDialog;
    const api=factory(dialogs);
    if(typeof module==='object'&&module.exports)module.exports=api;
    if(root)root.InspectorProFacilityInteriorWalls=api;
}(typeof globalThis!=='undefined'?globalThis:this,function(dialogs){
    'use strict';
    function settings(layout){return (layout.extensions?.facilityInteriorWalls?.walls||[]).map(w=>{const v={...w};delete v.panels;return v;});}
    function open(workspace){
        const state=workspace.session.getState(),layout=state.layout,plan=layout.extensions?.facilityPlan;
        if(!plan)throw new Error('Set the facility plan dimensions first.');
        const entries=settings(layout);let rows=[],nextEnd=false;
        const ui=dialogs.open(workspace,'Interior Walls',()=>{
            const wall=value();return workspace.session.setInteriorWalls({version:1,walls:entries.filter(w=>w.wallId!==selected.value).concat(wall)});
        });
        const selected=ui.field('Wall','select','',[{value:'',label:'New wall'},...entries.map(w=>({value:w.wallId,label:w.label}))]);
        const name=ui.field('Wall name','text','Partition');name.maxLength=120;
        const canvas=ui.el('canvas',{width:600,height:450,'aria-label':'Interior wall plan preview'});ui.body.append(canvas);
        const x1=ui.field('Start X (m)','number',5),z1=ui.field('Start Z (m)','number',5);
        const x2=ui.field('End X (m)','number',5),z2=ui.field('End Z (m)','number',Math.min(15,plan.depthMeters-1));
        const height=ui.field('Wall height (m)','number',3),thickness=ui.field('Wall thickness (m)','number',.2);
        const elevation=ui.field('Base elevation (m)','number',layout.coordinateFrame?.floorElevation||0);
        const color=ui.field('Wall color','color','#45484b');
        const dimensions=ui.el('div',{class:'ip-flw-authoring-dimensions'});
        [x1,z1,x2,z2,height,thickness,elevation,color].forEach(input=>dimensions.append(input.parentElement));ui.body.append(dimensions);
        const openings=ui.el('div',{class:'ip-flw-authoring-fields'});ui.body.append(openings);
        const add=ui.el('button',{type:'button'},'Add opening');ui.body.append(add);
        const remove=ui.el('button',{type:'button','aria-label':'Delete wall',title:'Delete wall'});
        remove.append(ui.el('img',{src:'/static/assets/facility-layout-ribbon-icons/svg/trash.svg',width:18,height:18,alt:''}));ui.body.append(remove);
        function addOpening(v){
            const row=ui.el('div',{class:'ip-flw-wall-opening'}),start=ui.el('input',{type:'number',step:'any','aria-label':'Door start (m)'}),end=ui.el('input',{type:'number',step:'any','aria-label':'Door end (m)'});
            start.value=v.startMeters;end.value=v.endMeters;
            const del=ui.el('button',{type:'button','aria-label':'Remove door opening',title:'Remove door opening'});
            del.append(ui.el('img',{src:'/static/assets/facility-layout-ribbon-icons/svg/trash.svg',alt:'',width:18,height:18}));
            const item={start,end};rows.push(item);del.addEventListener('click',()=>{rows=rows.filter(r=>r!==item);row.remove();draw();});
            [start,end].forEach((n,i)=>{n.addEventListener('input',draw);const label=ui.el('label',{},i?'To (m)':'From (m)');label.append(n);row.append(label);});row.append(del);openings.append(row);
        }
        function value(){return {wallId:selected.value||'iw-'+workspace.document.defaultView.crypto.randomUUID(),label:name.value,
            start:{x:Number(x1.value),z:Number(z1.value)},end:{x:Number(x2.value),z:Number(z2.value)},heightMeters:Number(height.value),
            thicknessMeters:Number(thickness.value),baseElevation:Number(elevation.value),color:color.value,
            openings:rows.map(r=>({startMeters:Number(r.start.value),endMeters:Number(r.end.value)}))};}
        function draw(){
            const c=canvas.getContext('2d'),scale=Math.min(560/plan.widthMeters,410/plan.depthMeters);
            c.clearRect(0,0,600,450);c.fillStyle='#e4e8eb';c.fillRect(20,20,plan.widthMeters*scale,plan.depthMeters*scale);
            function line(w,ink){c.strokeStyle=ink;c.lineWidth=Math.max(2,w.thicknessMeters*scale);c.beginPath();c.moveTo(20+w.start.x*scale,20+w.start.z*scale);c.lineTo(20+w.end.x*scale,20+w.end.z*scale);c.stroke();}
            entries.filter(w=>w.wallId!==selected.value).forEach(w=>line(w,'#89949b'));
            const w=value();line(w,w.color);
            const length=Math.hypot(w.end.x-w.start.x,w.end.z-w.start.z);
            if(length>0)w.openings.forEach(o=>line({...w,start:{x:w.start.x+(w.end.x-w.start.x)*o.startMeters/length,z:w.start.z+(w.end.z-w.start.z)*o.startMeters/length},end:{x:w.start.x+(w.end.x-w.start.x)*o.endMeters/length,z:w.start.z+(w.end.z-w.start.z)*o.endMeters/length}},'#e4e8eb'));
            remove.disabled=!selected.value;
        }
        canvas.addEventListener('click',event=>{
            const rect=canvas.getBoundingClientRect(),scale=Math.min(560/plan.widthMeters,410/plan.depthMeters);
            const x=Math.max(0,Math.min(plan.widthMeters,((event.clientX-rect.left)*600/rect.width-20)/scale));
            const z=Math.max(0,Math.min(plan.depthMeters,((event.clientY-rect.top)*450/rect.height-20)/scale));
            (nextEnd?x2:x1).value=x.toFixed(2);(nextEnd?z2:z1).value=z.toFixed(2);nextEnd=!nextEnd;draw();
        });
        selected.addEventListener('change',()=>{
            const w=entries.find(w=>w.wallId===selected.value)||{label:'Partition',start:{x:5,z:5},end:{x:5,z:15},heightMeters:3,thicknessMeters:.2,baseElevation:layout.coordinateFrame?.floorElevation||0,color:'#45484b',openings:[]};
            name.value=w.label;x1.value=w.start.x;z1.value=w.start.z;x2.value=w.end.x;z2.value=w.end.z;height.value=w.heightMeters;thickness.value=w.thicknessMeters;elevation.value=w.baseElevation;color.value=w.color;
            rows=[];openings.replaceChildren();w.openings.forEach(addOpening);draw();
        });
        add.addEventListener('click',()=>{addOpening({startMeters:1,endMeters:2.2});draw();});
        remove.addEventListener('click',()=>ui.commit(()=>workspace.session.setInteriorWalls({version:1,walls:entries.filter(w=>w.wallId!==selected.value)})));
        [x1,z1,x2,z2,thickness,color].forEach(n=>n.addEventListener('input',draw));draw();
    }
    return {settings,open};
}));
