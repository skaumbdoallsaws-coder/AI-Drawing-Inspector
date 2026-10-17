(function(root,factory){
    const dialogs=typeof module==='object'&&module.exports?require('./facility_layout_authoring_dialog.js'):root.InspectorProFacilityAuthoringDialog;
    const api=factory(dialogs);
    if(typeof module==='object'&&module.exports)module.exports=api;
    if(root)root.InspectorProFacilityFloorSurfaces=api;
}(typeof globalThis!=='undefined'?globalThis:this,function(dialogs){
    'use strict';
    const presets={concrete:{color:'#aeb2b4',roughness:.95},rubber:{color:'#35393e',roughness:.95},turf:{color:'#347a45',roughness:1},paving:{color:'#979b9e',roughness:.9},wood:{color:'#ad8655',roughness:.65},solid:{color:'#65787d',roughness:.8}};
    function records(layout){return layout?.extensions?.facilityFloorSurfaces?.surfaces||[];}
    function extent(layout){
        const ground=layout.extensions?.facilityGround?.surfaces||[],plan=layout.extensions?.facilityPlan;
        const rows=ground.length?ground:plan?[{minX:0,minZ:0,maxX:plan.widthMeters,maxZ:plan.depthMeters}]:[];
        if(!rows.length)return null;
        return {minX:Math.min(...rows.map(s=>s.minX)),minZ:Math.min(...rows.map(s=>s.minZ)),
            maxX:Math.max(...rows.map(s=>s.maxX)),maxZ:Math.max(...rows.map(s=>s.maxZ))};
    }
    function texture(THREE,document,type){
        if(type==='solid'||!document||!THREE.CanvasTexture)return null;
        const canvas=document.createElement('canvas');canvas.width=canvas.height=128;
        const c=canvas.getContext('2d');c.fillStyle='#eeeeee';c.fillRect(0,0,128,128);
        let seed=27;const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
        for(let i=0;i<1500;i++){const shade=Math.round(200+random()*55);c.fillStyle='rgb('+shade+','+shade+','+shade+')';c.fillRect(random()*128,random()*128,1,type==='turf'?3:1);}
        if(type==='paving'||type==='rubber'||type==='wood'){
            c.strokeStyle=type==='wood'?'#c0b9b0':'#b7b7b7';c.lineWidth=type==='paving'?2:1;
            c.strokeRect(0,0,128,128);
            if(type==='wood'){for(let y=32;y<128;y+=32){c.beginPath();c.moveTo(0,y);c.lineTo(128,y);c.stroke();}}
        }
        const map=new THREE.CanvasTexture(canvas);map.wrapS=map.wrapT=THREE.RepeatWrapping;map.colorSpace=THREE.SRGBColorSpace;return map;
    }
    function meshes(THREE,document,layout){
        return records(layout).map(surface=>{
            const shape=new THREE.Shape();surface.boundary.forEach((p,i)=>i?shape.lineTo(p.x,-p.z):shape.moveTo(p.x,-p.z));shape.closePath();
            const geometry=new THREE.ShapeGeometry(shape);geometry.rotateX(-Math.PI/2);
            const material=new THREE.MeshStandardMaterial({color:surface.color,roughness:surface.roughness,metalness:0,
                map:texture(THREE,document,surface.material),polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-1});
            const mesh=new THREE.Mesh(geometry,material);mesh.position.y=surface.elevation+.004;mesh.receiveShadow=true;
            mesh.name='FloorSurface:'+surface.surfaceId;mesh.userData.facilityFloorSurface=surface.surfaceId;return mesh;
        });
    }
    function open(workspace){
        const layout=workspace.session.getState().layout,bounds=extent(layout);
        if(!bounds)throw new Error('Set the facility plan dimensions or ground first.');
        const entries=records(layout),zone=workspace._selectedZoneRecord();let saved=null;
        const ui=dialogs.open(workspace,'Floor Surfaces',()=>workspace.session.setFloorSurfaces({version:1,surfaces:entries.filter(s=>s.surfaceId!==selected.value).concat(value())}));
        const selected=ui.field('Surface','select','',[{value:'',label:'New surface'},...entries.map(s=>({value:s.surfaceId,label:s.label}))]);
        const name=ui.field('Surface name','text','Floor finish');name.maxLength=120;
        const choices=[{value:'rectangle',label:'Rectangle'},{value:'saved',label:'Saved boundary'}];
        if(zone)choices.push({value:'zone',label:zone.label});
        const source=ui.field('Surface boundary','select',zone?'zone':'rectangle',choices);
        const x=ui.field('Origin X (m)','number',bounds.minX+1),z=ui.field('Origin Z (m)','number',bounds.minZ+1);
        const width=ui.field('Surface width (m)','number',Math.max(.1,Math.min(8,bounds.maxX-bounds.minX-2))),depth=ui.field('Surface depth (m)','number',Math.max(.1,Math.min(8,bounds.maxZ-bounds.minZ-2)));
        const elevation=ui.field('Floor elevation (m)','number',layout.coordinateFrame?.floorElevation||0);
        const material=ui.field('Floor material','select','concrete',Object.keys(presets).map(v=>({value:v,label:v[0].toUpperCase()+v.slice(1)})));
        const color=ui.field('Floor color','color',presets.concrete.color),roughness=ui.field('Floor roughness','range',presets.concrete.roughness);
        const canvas=ui.el('canvas',{width:600,height:450,'aria-label':'Floor surface plan preview'});ui.body.append(canvas);
        const remove=ui.el('button',{type:'button','aria-label':'Delete floor surface',title:'Delete floor surface'});
        remove.append(ui.el('img',{src:'/static/assets/facility-layout-ribbon-icons/svg/trash.svg',alt:'',width:18,height:18}));ui.body.append(remove);
        function boundary(){
            if(source.value==='zone')return zone.boundary;
            if(source.value==='saved'){if(!saved)throw new Error('Choose an existing surface first.');return saved.boundary;}
            const a=Number(x.value),b=Number(z.value),w=Number(width.value),d=Number(depth.value);
            if(w<=0||d<=0)throw new Error('Surface dimensions must be positive.');
            return [{x:a,z:b},{x:a+w,z:b},{x:a+w,z:b+d},{x:a,z:b+d}];
        }
        function value(){return {surfaceId:selected.value||'fs-'+workspace.document.defaultView.crypto.randomUUID(),label:name.value,
            boundary:boundary(),elevation:Number(elevation.value),material:material.value,color:color.value,roughness:Number(roughness.value)};}
        function draw(){
            const c=canvas.getContext('2d'),scale=Math.min(560/(bounds.maxX-bounds.minX),410/(bounds.maxZ-bounds.minZ));c.clearRect(0,0,600,450);
            c.fillStyle='#e4e8eb';c.fillRect(20,20,(bounds.maxX-bounds.minX)*scale,(bounds.maxZ-bounds.minZ)*scale);
            function fill(s){c.fillStyle=s.color;c.beginPath();s.boundary.forEach((p,i)=>i?c.lineTo(20+(p.x-bounds.minX)*scale,20+(p.z-bounds.minZ)*scale):c.moveTo(20+(p.x-bounds.minX)*scale,20+(p.z-bounds.minZ)*scale));c.closePath();c.fill();}
            entries.filter(s=>s.surfaceId!==selected.value).forEach(fill);
            try{fill(value());ui.disable(false);}catch(e){ui.message(e.message);ui.disable(true);}
            [x,z,width,depth].forEach(n=>n.disabled=source.value!=='rectangle');remove.disabled=!selected.value;
        }
        selected.addEventListener('change',()=>{
            saved=entries.find(s=>s.surfaceId===selected.value)||null;
            if(saved){name.value=saved.label;source.value='saved';material.value=saved.material;color.value=saved.color;roughness.value=saved.roughness;elevation.value=saved.elevation;}
            else{source.value='rectangle';name.value='Floor finish';}
            draw();
        });
        material.addEventListener('change',()=>{color.value=presets[material.value].color;roughness.value=presets[material.value].roughness;draw();});
        [source,x,z,width,depth,color].forEach(n=>n.addEventListener('input',draw));
        remove.addEventListener('click',()=>ui.commit(()=>workspace.session.setFloorSurfaces({version:1,surfaces:entries.filter(s=>s.surfaceId!==selected.value)})));draw();
    }
    return {records,extent,presets,texture,meshes,open};
}));
