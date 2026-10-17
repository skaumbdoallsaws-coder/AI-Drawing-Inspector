'use strict';
const assert = require('node:assert/strict');
const api = require('../static/walkthrough_camera_settings.js');
let raw = null;
const store = {getItem:()=>raw,setItem:(key,value)=>{assert.equal(key,api.KEY);raw=value;}};
assert.deepEqual(api.normalize({distance:Infinity,height:NaN}),api.PRESETS.standard);
assert.deepEqual(api.normalize({distance:999,height:-1}),{distance:14,height:0});
assert.deepEqual(api.normalize({distance:0,height:99}),{distance:2.5,height:3});
assert.deepEqual(api.normalize({distance:'9',height:null}),api.PRESETS.standard);
for(const [key,value] of Object.entries(api.PRESETS)) {
    assert.equal(api.preset(value),key);
    assert.deepEqual(api.save(value,store),value);
    assert.deepEqual(api.load(store),value);
}
assert.equal(api.preset({distance:8,height:1}),null);
assert.deepEqual(api.zoom(api.PRESETS.standard,{deltaY:100,ctrlKey:true}),api.PRESETS.standard);
assert.equal(api.zoom(api.PRESETS.standard,{deltaY:100}).distance,5.5);
assert.equal(api.zoom(api.PRESETS.standard,{deltaY:-3,deltaMode:1}).distance,4.76);
assert.equal(api.zoom(api.PRESETS.standard,{deltaY:1,deltaMode:2}).distance,6.5);
assert.equal(api.zoom({distance:14,height:0},{deltaY:9999}).distance,14);
assert.equal(api.zoom({distance:2.5,height:0},{deltaY:-9999}).distance,2.5);
raw='{broken'; assert.doesNotThrow(()=>api.load(store));
raw='null'; assert.deepEqual(api.load(store),api.PRESETS.standard);
const denied={getItem:()=>{throw Error('denied');},setItem:()=>{throw Error('quota');}};
assert.deepEqual(api.save(api.PRESETS.wide,denied),api.PRESETS.wide);
assert.deepEqual(api.load(denied),api.PRESETS.wide);
// Quota failure must not make a stale stored value override the session preference.
api.save(api.PRESETS.standard,store);
const quota={getItem:()=>raw,setItem:()=>{throw Error('quota');}};
api.save(api.PRESETS.wide,quota);
assert.deepEqual(api.load(quota),api.PRESETS.wide);
api.save(api.PRESETS.standard,store);
console.log('Camera settings: normalization, presets, persistence, unavailable storage and wheel bounds passed');
