(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    root.InspectorProFacilityGround = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    function surfaces(layout) {
        return layout && layout.extensions && layout.extensions.facilityGround
            ? layout.extensions.facilityGround.surfaces : null;
    }
    function bounds(rows) {
        if (!rows || !rows.length) return null;
        return { minimum: {x: Math.min(...rows.map(s => s.minX)),
            y: Math.min(...rows.map(s => Math.min(s.startElevation, s.endElevation))),
            z: Math.min(...rows.map(s => s.minZ))},
        maximum: {x: Math.max(...rows.map(s => s.maxX)),
            y: Math.max(...rows.map(s => Math.max(s.startElevation, s.endElevation))),
            z: Math.max(...rows.map(s => s.maxZ))} };
    }
    function height(s, p) {
        const t = s.slopeAxis === 'x' ? (p.x-s.minX)/(s.maxX-s.minX) : (p.z-s.minZ)/(s.maxZ-s.minZ);
        return s.startElevation + Math.max(0, Math.min(1, t)) * (s.endElevation-s.startElevation);
    }
    function sample(rows, p, preferredY) {
        const found = (rows || []).filter(s => p.x >= s.minX-1e-8 && p.x <= s.maxX+1e-8 && p.z >= s.minZ-1e-8 && p.z <= s.maxZ+1e-8);
        found.sort((a,b) => Math.abs(height(a,p)-preferredY)-Math.abs(height(b,p)-preferredY) || a.surfaceId.localeCompare(b.surfaceId));
        return found.length ? {y: height(found[0],p), surface: found[0]} : null;
    }
    function move(rows, start, end) {
        const distance = Math.hypot(end.x-start.x,end.z-start.z);
        const steps = Math.max(1,Math.ceil(distance/.05));
        let previous = {x:start.x,y:start.y,z:start.z};
        for (let i=1;i<=steps;i++) {
            const p = {x:start.x+(end.x-start.x)*i/steps,z:start.z+(end.z-start.z)*i/steps};
            const ground = sample(rows,p,previous.y);
            // Permit continuous ramps (up to 1:4), never teleport over a dock edge.
            if (!ground || Math.abs(ground.y-previous.y) > .005 + .25*distance/steps) return {position:previous,collided:true};
            previous = {x:p.x,y:ground.y,z:p.z};
        }
        return {position:previous,collided:false};
    }
    function vertices(s, thickness, baseElevation) {
        const top = [[s.minX,0,s.minZ],[s.maxX,0,s.minZ],[s.maxX,0,s.maxZ],[s.minX,0,s.maxZ]];
        top.forEach(v=>{v[1]=height(s,{x:v[0],z:v[2]});});
        const bottom = Number.isFinite(baseElevation) ? baseElevation : Math.min(s.startElevation,s.endElevation)-thickness;
        const points = top.concat(top.map(v=>[v[0],bottom,v[2]]));
        return {positions: points.flat(), indices:[0,2,1,0,3,2,4,5,6,4,6,7,0,1,5,0,5,4,1,2,6,1,6,5,2,3,7,2,7,6,3,0,4,3,4,7]};
    }
    return {surfaces,bounds,height,sample,move,vertices};
});
