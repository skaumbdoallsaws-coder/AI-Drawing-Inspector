(function(root,factory){
    const api=factory();
    if(typeof module==='object'&&module.exports)module.exports=api;
    if(root)root.InspectorProFacilityLettering=api;
}(typeof globalThis!=='undefined'?globalThis:this,function(){
    'use strict';
    function validate(value){
        if(!value || typeof value.text!=='string' || !value.text.trim() || value.text.length>1000
            || value.text.split('\n').length>16 || typeof value.reference!=='string' || value.reference.length>160
            || /[\x00-\x09\x0b-\x1f]/.test(value.text+value.reference))throw new Error('Enter up to 1,000 characters and 16 lines.');
        if(!['Arial','Georgia'].includes(value.font)||!['left','center','right'].includes(value.align)
            || !/^#[a-f0-9]{6}$/i.test(value.color))throw new Error('Choose a font, alignment, and color.');
        return {...value,text:value.text.trim(),reference:value.reference.trim()};
    }
    function wrap(ctx,text,width){
        const lines=[];
        text.split('\n').forEach(paragraph=>{
            let line='';
            for(const word of paragraph.split(/\s+/)){
                const next=line?line+' '+word:word;
                if(line && ctx.measureText(next).width>width){lines.push(line);line=word;}else line=next;
            }
            lines.push(line);
        });
        return lines;
    }
    function render(document,settings,aspect){
        const v=validate(settings),canvas=document.createElement('canvas');
        aspect=Math.max(.125,Math.min(8,Number(aspect)||2));
        canvas.width=Math.round(Math.min(3072,2048*aspect));canvas.height=Math.round(canvas.width/aspect);
        const ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height,pad=32;
        let size=Math.min(180,h*.35),lines=[];
        for(;size>=8;size-=1){
            ctx.font='bold '+size+'px '+v.font;lines=wrap(ctx,v.text,w-pad*2);
            if(lines.every(line=>ctx.measureText(line).width<=w-pad*2)
                && lines.length*size*1.2+(v.reference?size*.95:0)<=h-pad*2)break;
        }
        if(size<8)throw new Error('Text is too dense for this wall region. Use fewer words or a larger region.');
        ctx.fillStyle=v.color;ctx.textAlign=v.align;ctx.textBaseline='top';
        const x=v.align==='left'?pad:v.align==='right'?w-pad:w/2;
        let y=(h-lines.length*size*1.2-(v.reference?size*.95:0))/2;
        lines.forEach(line=>{ctx.fillText(line,x,y);y+=size*1.2;});
        if(v.reference){
            let refSize=size*.48;
            do {ctx.font=refSize+'px '+v.font;refSize-=1;}while(ctx.measureText(v.reference).width>w-pad*2 && refSize>6);
            ctx.fillText(v.reference.replace(/\n/g,' '),x,y+size*.25);
        }
        return canvas;
    }
    return {validate,wrap,render};
}));
