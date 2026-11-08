'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname,'..');
const read = file => fs.readFileSync(path.join(root,file),'utf8');
const commands = ['select','reset-view','snap','fit-layout','zoom-out','zoom-in','pan','display-settings','layers','orbit','walkthrough','avatar-view','drone','switch-immersive','walk-to-selected','camera-settings','viewpoints','fit-facility','grid'];

test('viewport symbols are individual transparent vector assets from the shared ribbon materials',()=>{
  const icons=commands.map(command=>read('static/assets/facility-viewport-icons/'+command+'.svg'));
  assert.equal(new Set(icons).size,commands.length);
  for(const icon of icons){
    assert.match(icon,/viewBox="0 0 64 64"/);
    assert.match(icon,/<linearGradient/);
    assert.doesNotMatch(icon,/<script|<image|<foreignObject|href=/);
  }
  assert.ok(fs.existsSync(path.join(root,'static/assets/facility-viewport-icons/PHOSPHOR-LICENSE.txt')));
});

test('three look-alike cubes are now orientation, amber display sliders, and approved appearance swatches',()=>{
  const source=read('static/facility_layout_workspace.js');
  assert.match(source,/packaging-ribbon-icons\/appearance-glossy-v1\.png/);
  assert.match(source,/THREE_DIMENSIONAL_ICON_COMMANDS\.has\(command\)/);
  assert.match(source,/src: threeViewIconSrc\(view\.key\)/);
  const icons=commands.filter(c=>c==='display-settings'||c==='layers'||c==='grid');
  assert.equal(new Set(icons.map(c=>read('static/assets/facility-viewport-icons/'+c+'.svg'))).size,3);
});

test('dimensional artwork keeps its own palette and toolbar dimensions stay compact',()=>{
  const css=read('static/facility_layout_workspace.css');
  assert.match(css,/\[data-icon-source="facility-dimensional"\] \.ip-flw-three-nav-icon img\s*\{\s*filter: none;/);
  assert.match(css,/\.ip-flw-three-nav-button\s*\{[^}]*height: 28px;/);
  assert.match(css,/\.ip-flw-three-nav-icon\s*\{[^}]*width: 24px;[^}]*height: 24px;/);
  assert.match(read('static/assets/facility-viewport-icons/walkthrough.svg'),/#walk path\{fill:url\(#green\);opacity:1\}/);
  assert.match(read('static/assets/facility-viewport-icons/drone.svg'),/#drone g\[stroke\]\{stroke:url\(#silver\)/);
  assert.match(read('static/assets/facility-viewport-icons/viewpoints.svg'),/#pin \[fill="#d9a64c"\]\{fill:url\(#gold\);opacity:1\}/);
});

test('Plan shares 3D navigation assets and dimensions without the old glowing filter',()=>{
  const source=read('static/facility_layout_workspace.js');
  const css=read('static/facility_layout_workspace.css');
  assert.match(source,/PLAN_DIMENSIONAL_ICON_COMMANDS\.has\(command\)\s*\? VIEWPORT_DIMENSIONAL_ICON_ROOT \+ command \+ '\.svg'/);
  assert.match(css,/\.ip-flw-plan-nav-button\s*\{[^}]*width: 28px;[^}]*height: 28px;/);
  assert.match(css,/\.ip-flw-plan-nav-icon\s*\{[^}]*width: 24px;[^}]*height: 24px;/);
  const artworkRule=css.match(/\.ip-flw-plan-nav-icon img\s*\{([^}]*)\}/)[1];
  assert.match(artworkRule,/filter: none;/);
  assert.doesNotMatch(artworkRule,/drop-shadow/);
});
