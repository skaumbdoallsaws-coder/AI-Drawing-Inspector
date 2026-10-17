(function(root,factory){
    const walls=typeof module==='object'&&module.exports?require('./facility_layout_walls.js'):root.InspectorProFacilityWalls;
    const api=factory(walls);
    if(typeof module==='object'&&module.exports)module.exports=api;
    if(root)root.InspectorProFacilityAuthoringDialog=api;
}(typeof globalThis!=='undefined'?globalThis:this,function(walls){
    'use strict';
    function open(workspace,title,onApply){
        const state=workspace.session.getState();
        if(!walls.canEdit(workspace,state))throw new Error('Finish the active operation before editing.');
        close(workspace);
        const doc=workspace.document,revision=state.draftRevision,id=state.layout.layoutId;
        const focus=doc.activeElement,selection=JSON.stringify(state.selection);
        let applying=false,closed=false,invalid=false,cleanup=null;
        function el(tag,attrs,text){const n=doc.createElement(tag);Object.entries(attrs||{}).forEach(([k,v])=>n.setAttribute(k,v));if(text!==undefined)n.textContent=text;return n;}
        const dialog=el('dialog',{class:'ip-flw-authoring-dialog','aria-label':title}),form=el('form');
        const heading=el('h2',{},title),body=el('fieldset',{class:'ip-flw-authoring-fields'}),status=el('div',{role:'status','aria-live':'polite'});
        const scroll=el('div',{class:'ip-flw-authoring-scroll'});scroll.append(body);
        const footer=el('footer'),cancel=el('button',{type:'button'},'Cancel'),apply=el('button',{type:'submit',class:'ip-flw-primary-action'},'Apply');
        footer.append(cancel,apply);form.append(heading,scroll,status,footer);dialog.append(form);workspace.root.append(dialog);
        function fresh(){const s=workspace.session.getState();return !closed&&walls.canEdit(workspace,s)&&s.draftRevision===revision&&s.layout.layoutId===id&&JSON.stringify(s.selection)===selection;}
        function refresh(){apply.disabled=applying||invalid||!fresh();cancel.disabled=applying;body.disabled=applying;if(!applying&&!fresh())status.textContent='Selection or layout changed. Close and reopen this tool.';}
        const unsubscribe=workspace.session.subscribe(refresh);
        function dispose(){if(closed)return;closed=true;unsubscribe();if(cleanup)cleanup();dialog.remove();workspace.authoringDialogClose=null;if(focus&&focus.isConnected)focus.focus();}
        workspace.authoringDialogClose=dispose;
        async function commit(action=onApply){refresh();if(apply.disabled)return;applying=true;refresh();try{await action();dispose();}catch(e){status.textContent=e.message;}finally{applying=false;if(!closed)refresh();}}
        form.addEventListener('submit',event=>{event.preventDefault();commit();});
        cancel.addEventListener('click',dispose);dialog.addEventListener('cancel',event=>{event.preventDefault();if(!applying)dispose();});
        dialog.showModal();refresh();
        return {el,body,dialog,state,fresh,refresh,commit,close:dispose,
            cleanup(fn){cleanup=fn;},message(text){status.textContent=text;},disable(value){invalid=value;refresh();},
            field(label,type,value,options){
                const node=el(type==='select'?'select':type==='textarea'?'textarea':'input',{'aria-label':label});
                if(type!=='select'&&type!=='textarea')node.type=type;
                if(type==='number'){node.step='any';}
                if(type==='range'){node.min=0;node.max=1;node.step=.01;}
                (options||[]).forEach(v=>node.append(el('option',{value:v.value},v.label)));
                if(value!==undefined)node.value=value;
                const wrapper=el('label',{},label);wrapper.append(node);body.append(wrapper);return node;
            }};
    }
    function close(workspace){if(workspace.authoringDialogClose)workspace.authoringDialogClose();}
    return {open,close};
}));
