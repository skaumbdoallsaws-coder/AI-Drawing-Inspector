/* Authored object geometry in publication points; no DOM or storage dependency. */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.DocumentationObjectsCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    const HANDLES = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];
    const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
    const round = v => Math.round(v * 1e6) / 1e6;
    const signs = h => [h.includes('e') ? 1 : h.includes('w') ? -1 : 0,
        h.includes('s') ? 1 : h.includes('n') ? -1 : 0];
    function turn(x, y, degrees) {
        const a = degrees * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
        return [c*x-s*y, s*x+c*y];
    }
    function rounded(frame) {
        return Object.fromEntries(Object.entries(frame).map(([k,v]) => [k, round(v)]));
    }
    function valid(f) {
        return [f.x,f.y,f.width,f.height,f.rotation || 0].every(Number.isFinite)
            && f.x >= -1 && f.x <= 2 && f.y >= -1 && f.y <= 2
            && f.width >= .01 && f.width <= 2 && f.height >= .01 && f.height <= 2;
    }
    function same(a, b) {
        return ['x','y','width','height','rotation'].every(k => Math.abs((a[k] || 0)-(b[k] || 0)) < 1e-9);
    }
    function placement(value, size, pixels) {
        const [width,height] = size, [w,h] = pixels;
        const source = {...(value.crop || {x:0,y:0,width:1,height:1})};
        if (!value.crop && value.contentMode === 'cover') {
            if (w/h > width/height) {
                source.width = width/height/(w/h); source.x = (1-source.width)/2;
            } else {
                source.height = (w/h)/(width/height); source.y = (1-source.height)/2;
            }
        }
        const ratio = source.width*w/(source.height*h);
        const dw = Math.min(width,height*ratio), dh = Math.min(height,width/ratio);
        return [source, [(width-dw)/2,(height-dh)/2,dw,dh]];
    }
    function box(f, size) {
        const [pw,ph] = size, a = (f.rotation || 0)*Math.PI/180;
        const rw = Math.abs(f.width*pw*Math.cos(a))+Math.abs(f.height*ph*Math.sin(a));
        const rh = Math.abs(f.width*pw*Math.sin(a))+Math.abs(f.height*ph*Math.cos(a));
        return {x:(f.x*pw+f.width*pw/2-rw/2)/pw,y:(f.y*ph+f.height*ph/2-rh/2)/ph,width:rw/pw,height:rh/ph};
    }
    function resize(f, size, handle, delta, locked=false, shift=false) {
        const [pw,ph] = size, [sx,sy] = signs(handle);
        const [dx,dy] = turn(delta[0],delta[1],-(f.rotation || 0));
        const w = f.width*pw, h = f.height*ph, minW = Math.max(8,.01*pw), minH = Math.max(8,.01*ph);
        let nw = w+sx*dx, nh = h+sy*dy;
        if (locked || shift && sx && sy) {
            let scale = sx && sy ? (w*nw+h*nh)/(w*w+h*h) : sx ? nw/w : nh/h;
            scale = clamp(scale,Math.max(minW/w,minH/h),Math.min(2*pw/w,2*ph/h));
            nw = w*scale; nh = h*scale;
        } else {
            nw = sx ? clamp(nw,minW,2*pw) : w;
            nh = sy ? clamp(nh,minH,2*ph) : h;
        }
        const at = t => {
            const dw = (nw-w)*t, dh = (nh-h)*t;
            const [cx,cy] = turn(sx*dw/2,sy*dh/2,f.rotation || 0);
            return {...f,x:f.x+(cx-dw/2)/pw,y:f.y+(cy-dh/2)/ph,width:(w+dw)/pw,height:(h+dh)/ph};
        };
        if (valid(at(1))) return at(1);
        // Stop at a position limit, preserving the opposite point and the ratio.
        let lo=0,hi=1;
        for (let i=0;i<60;i++) { const mid=(lo+hi)/2; if(valid(at(mid)))lo=mid;else hi=mid; }
        return at(lo);
    }
    function move(frames, size, dx, dy) {
        const x = clamp(dx/size[0],Math.max(...frames.map(f=>-1-f.x)),Math.min(...frames.map(f=>2-f.x)));
        const y = clamp(dy/size[1],Math.max(...frames.map(f=>-1-f.y)),Math.min(...frames.map(f=>2-f.y)));
        return frames.map(f=>({...f,x:f.x+x,y:f.y+y}));
    }
    const nudge = (frames,size,horizontal,vertical,large=false) => move(frames,size,horizontal*(large?10:1),vertical*(large?10:1));
    function cursor(handle, rotation=0) {
        const [x,y]=signs(handle), angle=(Math.atan2(y,x)*180/Math.PI+rotation+360)%180;
        return ['ew-resize','nwse-resize','ns-resize','nesw-resize'][Math.round(angle/45)%4];
    }
    function cropLayout(value,size,pixels) {
        const f=value.frame, w=f.width*size[0], h=f.height*size[1];
        const [source,draw]=placement(value,[w,h],pixels);
        const kept={x:draw[0],y:draw[1],width:draw[2],height:draw[3]};
        const whole={x:kept.x-source.x*kept.width/source.width,y:kept.y-source.y*kept.height/source.height,
            width:kept.width/source.width,height:kept.height/source.height};
        return {frame:{...f},size:[...size],whole,kept,source,value};
    }
    function cropFrame(layout,rect) {
        const {frame:f,size}=layout;
        const [dx,dy]=turn(rect.x+rect.width/2-f.width*size[0]/2,
            rect.y+rect.height/2-f.height*size[1]/2,f.rotation || 0);
        return {...f,x:f.x+f.width/2+(dx-rect.width/2)/size[0],
            y:f.y+f.height/2+(dy-rect.height/2)/size[1],width:rect.width/size[0],height:rect.height/size[1]};
    }
    function cropDrag(layout,start,handle,delta) {
        const b=layout.whole, [dx,dy]=turn(delta[0],delta[1],-(layout.frame.rotation || 0));
        const minW=Math.max(8,b.width*.01,layout.size[0]*.01), minH=Math.max(8,b.height*.01,layout.size[1]*.01);
        // Very thin legacy pictures may have no crop rectangle that satisfies both bounds.
        if (b.width < minW || b.height < minH) return {...start};
        let r={...start};
        if(handle==='move') {
            r.x=clamp(r.x+dx,b.x,b.x+b.width-r.width); r.y=clamp(r.y+dy,b.y,b.y+b.height-r.height);
        } else {
            const [sx,sy]=signs(handle), right=r.x+r.width,bottom=r.y+r.height;
            if(sx<0) { r.x=clamp(r.x+dx,b.x,right-minW);r.width=right-r.x; }
            if(sx>0) r.width=clamp(r.width+dx,minW,b.x+b.width-r.x);
            if(sy<0) { r.y=clamp(r.y+dy,b.y,bottom-minH);r.height=bottom-r.y; }
            if(sy>0) r.height=clamp(r.height+dy,minH,b.y+b.height-r.y);
        }
        // A crop changes the saved frame too. Never preview a frame outside its bounds.
        if(valid(cropFrame(layout,r))) return r;
        let lo=0,hi=1;
        const at=t=>Object.fromEntries(['x','y','width','height'].map(k=>[k,start[k]+(r[k]-start[k])*t]));
        for(let i=0;i<60;i++){const mid=(lo+hi)/2;if(valid(cropFrame(layout,at(mid))))lo=mid;else hi=mid;}
        return at(lo);
    }
    function cropResult(layout,rect,reset=false) {
        const {value,whole}=layout;
        if(!reset && same(rect,layout.kept)) return [];
        const chosen=reset?whole:rect, frame=rounded(cropFrame(layout,chosen));
        if(!valid(frame)) throw new Error('The picture would exceed the object frame limits.');
        let crop={x:round((chosen.x-whole.x)/whole.width),y:round((chosen.y-whole.y)/whole.height),
            width:round(chosen.width/whole.width),height:round(chosen.height/whole.height)};
        crop.width=Math.min(crop.width,round(1-crop.x));crop.height=Math.min(crop.height,round(1-crop.y));
        if(same(crop,{x:0,y:0,width:1,height:1}))crop=null;
        const ops=[];
        if(!same(crop || {x:0,y:0,width:1,height:1},value.crop || {x:0,y:0,width:1,height:1}) || crop && value.contentMode==='cover')
            ops.push({operation:'set_image_crop',objectId:value.objectId,crop});
        if(!same(frame,value.frame)) ops.push({operation:'set_object_frame',objectId:value.objectId,
            x:frame.x,y:frame.y,width:frame.width,height:frame.height,aspectLock:!!value.aspectLock});
        return ops;
    }
    function cropMasks(layout,r) {
        const b=layout.whole;
        return [{x:b.x,y:b.y,width:b.width,height:r.y-b.y},
            {x:b.x,y:r.y+r.height,width:b.width,height:b.y+b.height-r.y-r.height},
            {x:b.x,y:r.y,width:r.x-b.x,height:r.height},
            {x:r.x+r.width,y:r.y,width:b.x+b.width-r.x-r.width,height:r.height}];
    }
    function arrangementChanges(values,size,kind) {
        const horizontal=kind.includes('horizontal') || ['align_left','align_right','align_center'].includes(kind);
        const axis=horizontal?'x':'y', extent=horizontal?'width':'height';
        const boxes=values.map(v=>box(v.frame,size)).sort((a,b)=>a[axis]-b[axis]);
        const samples=kind.startsWith('distribute') ? boxes.slice(1).map((b,i)=>b[axis]-boxes[i][axis]-boxes[i][extent])
            : boxes.map(b=>b[axis]+(kind==='align_center'||kind==='align_middle'?b[extent]/2:
                kind==='align_right'||kind==='align_bottom'?b[extent]:0));
        return Math.max(...samples)-Math.min(...samples)>1e-6;
    }
    function orderMoves(order,id) {
        const i=order.indexOf(id), exists=i>=0;
        return {front:exists&&i<order.length-1,forward:exists&&i<order.length-1,back:exists&&i>0,backward:exists&&i>0};
    }
    function insertedImage(size,pixels) {
        let w=.4*size[0],h=w*pixels[1]/pixels[0];
        if(h>.5*size[1]) {h=.5*size[1];w=h*pixels[0]/pixels[1];}
        // The old image frame was centred at (0.50, 0.38).
        return rounded({x:.5-w/size[0]/2,y:.38-h/size[1]/2,width:w/size[0],height:h/size[1],rotation:0});
    }
    return {HANDLES,turn,rounded,valid,same,placement,box,resize,move,nudge,cursor,cropLayout,cropFrame,cropDrag,cropResult,cropMasks,arrangementChanges,orderMoves,insertedImage};
});
