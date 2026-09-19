'use strict';
const $ = id => document.getElementById(id);
let state = { tabs: [], activeId: null };
function action(name, extra = {}) {
  return window.research.command({ action: name, tabId: state.activeId, ...extra }).then(render).catch(error => {
    $('status').textContent = String(error.message || 'Research action failed').replace(/^.*Error: /, '');
  });
}
function render(next) {
  if (!next || !Array.isArray(next.tabs)) return;
  const focus = document.activeElement;
  const restore = focus?.dataset?.key;
  state = next;
  const tab = state.tabs.find(item => item.id === state.activeId);
  $('tabs').replaceChildren(...state.tabs.map(item => {
    const row = document.createElement('div'); row.className = 'tab' + (item.id === state.activeId ? ' active' : '');
    const select = document.createElement('button');
    const favicon=document.createElement('span');favicon.className='tab-favicon';favicon.setAttribute('aria-hidden','true');
    if(item.favicon){
      const img=document.createElement('img');img.src=item.favicon;img.alt='';img.width=16;img.height=16;
      favicon.classList.add('has-image');img.addEventListener('error',()=>{img.remove();favicon.classList.remove('has-image');});favicon.append(img);
    }
    const title=document.createElement('span');title.className='tab-title';title.textContent=item.loading&&item.title==='New tab'?'Loading...':item.title;
    select.append(favicon,title);
    select.title = item.title; select.setAttribute('role', 'tab'); select.setAttribute('aria-selected', String(item.id === state.activeId));
    select.dataset.key = item.id; select.addEventListener('click', () => action('activate', { tabId: item.id }));
    const close = document.createElement('button'); close.textContent = '\u00d7'; close.title = 'Close ' + item.title;
    close.setAttribute('aria-label', close.title); close.dataset.key = item.id + '-close';
    close.addEventListener('click', () => action('close', { tabId: item.id })); row.append(select, close); return row;
  }));
  if (restore) [...$('tabs').querySelectorAll('button')].find(button => button.dataset.key === restore)?.focus();
  if (focus !== $('address')) $('address').value = tab?.url || '';
  $('back').disabled = !tab?.canGoBack; $('forward').disabled = !tab?.canGoForward;
  $('more').disabled = !tab?.url;
  $('more').querySelector('[value="external"]').disabled = tab?.kind === 'document';
  $('detach').hidden = !state.canDetach;
  $('detach').title = state.detached ? 'Dock browser in InspectorPro' : 'Open in separate window';
  $('detach').setAttribute('aria-label', $('detach').title);
  $('expand').hidden = state.detached;
  $('expand').title = state.expanded ? 'Restore split view' : 'Expand browser';
  $('expand').setAttribute('aria-label', $('expand').title);
  $('reload').textContent = tab?.loading ? '\u00d7' : '\u21bb';
  $('reload').title = tab?.loading ? 'Stop loading' : 'Reload'; $('reload').setAttribute('aria-label', $('reload').title);
  $('new').disabled = state.tabs.length >= state.maximumTabs;
  $('status').textContent = tab?.error || (state.download ? state.download.name + ': ' + state.download.state : tab?.loading ? 'Loading...' : '');
  $('cancel-downloads').hidden = !['paused', 'in-progress'].includes(state.download?.state);
}
for (const name of ['new', 'back', 'forward', 'expand', 'hide', 'detach', 'downloads', 'cancel-downloads']) $(name).addEventListener('click', () => action(name));
$('more').addEventListener('change', () => { const name = $('more').value; $('more').value = ''; if (name) void action(name); });
$('reload').addEventListener('click', () => action(state.tabs.find(tab => tab.id === state.activeId)?.loading ? 'stop' : 'reload'));
$('address-form').addEventListener('submit', event => { event.preventDefault(); void action('navigate', { value: $('address').value }); $('address').blur(); });
document.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'l') { event.preventDefault(); $('address').focus(); $('address').select(); }
  if ((event.ctrlKey || event.metaKey) && ['t','w'].includes(event.key.toLowerCase())) { event.preventDefault(); void action(event.key.toLowerCase() === 't' ? 'new' : 'close'); }
  if (event.key === 'Escape') { event.preventDefault(); void action('hide'); }
});
window.research.subscribe(render);
window.research.onAddressFocus(() => { $('address').focus(); $('address').select(); });
void action('state');
