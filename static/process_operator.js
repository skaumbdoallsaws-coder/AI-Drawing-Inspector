(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProProcessOperator = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    const offsets = { standing: [0], crouching: [0, -.4], kneeling: [-.2, 0, .2], crawling: [-.75, -.4, 0, .35] };
    function poseFits(helper, geometry, point, posture, heading) {
        const scale = geometry.modelScale;
        for (const offset of offsets[posture] || []) {
            const result = helper.resolveWalkthroughPostureChange({
                posture, postures: geometry.postureProfiles,
                point: { x: point.x + Math.sin(heading) * offset * scale,
                    z: point.z + Math.cos(heading) * offset * scale },
                elevation: point.y, bounds: geometry.bounds,
                supportClearance: geometry.supportClearance,
                maximumClimbElevation: point.y + geometry.maximumStepUp,
                obstacleVolumes: geometry.obstacleVolumes,
            });
            if (!result.ok) return result;
        }
        return offsets[posture] ? { ok: true } : { ok: false, reason: 'unknown_posture' };
    }
    function movementInput(g, position, delta, posture = 'standing') {
        return { start: { x: position.x, z: position.z, elevation: position.y }, delta,
            ...g.postureProfiles[posture], bounds: g.bounds, surfaces: g.walkSurfaces,
            obstacleVolumes: g.obstacleVolumes, maximumStepUp: g.maximumStepUp,
            maximumStepDown: g.maximumStepDown, supportClearance: g.supportClearance };
    }
    function transitionFits(helper,g,point,from,to,oldHeading,heading) {
        const a=g.postureProfiles[from],b=g.postureProfiles[to];
        if(!a||!b)return {ok:false,reason:'unknown_posture'};
        if(from==='standing'&&to==='standing')return poseFits(helper,g,point,to,heading);
        const profiles={...g.postureProfiles};
        for(const key of [from,to])profiles[key]={...profiles[key],bodyHeight:Math.max(a.bodyHeight,b.bodyHeight)};
        const geometry={...g,postureProfiles:profiles};
        const turn=Math.atan2(Math.sin(heading-oldHeading),Math.cos(heading-oldHeading));
        const samples=Math.max(1,Math.ceil(Math.abs(turn)/.15));
        for(let i=0;i<=samples;i++)for(const posture of [from,to]) {
            const result=poseFits(helper,geometry,point,posture,oldHeading+turn*i/samples);
            if(!result.ok)return result;
        }
        return {ok:true};
    }
    function validatePath(helper, g, start, points) {
        let position = { ...start };
        const checked = [];
        for (const point of points) {
            const result = helper.resolveMultiLevelWalkthroughMovement(movementInput(g, position,
                { x: point.x-position.x, z: point.z-position.z }));
            if (Math.hypot(result.position.x-point.x, result.position.z-point.z) > .025*g.modelScale
                    || !Number.isFinite(result.elevation)) return { ok: false, reason: 'operator_route_blocked' };
            position = { ...result.position, y: result.elevation };
            checked.push(position);
        }
        return { ok: true, points: checked, end: position };
    }
    const groundObstacleCache = new WeakMap();
    function groundObstacles(polygons) {
        if (groundObstacleCache.has(polygons)) return groundObstacleCache.get(polygons);
        // CAD sparse cells often sit inside an already-solid platform footprint.
        // Remove only exact containment by rectangles; keep every gap and use full volumes for final validation.
        const rows=polygons.map((polygon,index)=>{
            const xs=polygon.map(p=>p.x),zs=polygon.map(p=>p.z);
            const minX=Math.min(...xs),maxX=Math.max(...xs),minZ=Math.min(...zs),maxZ=Math.max(...zs);
            const rectangle=polygon.length===4 && new Set(polygon.map(p=>p.x+':'+p.z)).size===4
                && polygon.every((p,i)=>{
                    const q=polygon[(i+1)%4];return (p.x===minX||p.x===maxX)&&(p.z===minZ||p.z===maxZ)
                        && (p.x===q.x||p.z===q.z);
                });
            return {polygon,index,minX,maxX,minZ,maxZ,rectangle,area:(maxX-minX)*(maxZ-minZ)};
        }).sort((a,b)=>b.area-a.area||a.index-b.index);
        const kept=[];
        for(const row of rows)if(!kept.some(b=>b.rectangle && row.minX>=b.minX && row.maxX<=b.maxX
            && row.minZ>=b.minZ && row.maxZ<=b.maxZ))kept.push(row);
        const result=kept.map(row=>row.polygon);
        groundObstacleCache.set(polygons,result);
        return result;
    }
    function groundRoute(helper, g, start, goal) {
        if (Math.abs(start.y-g.floorY) > .05*g.modelScale) return { ok: false, reason: 'operator_start_not_ground' };
        const route = helper.planWalkthroughRoute({ start, goal, bounds: g.bounds, obstacles: groundObstacles(g.obstacles),
            radius: g.radius, gridSpacing: .5*g.modelScale, maximumNodes: 6000 });
        return route.ok ? validatePath(helper, g, start, route.points.slice(1)) : route;
    }
    function approach(helper, g, start, box, posture = 'standing') {
        if (!box || !box.min || !box.max) return { ok: false, reason: 'operator_target_missing' };
        const x = (box.min.x+box.max.x)/2, z = (box.min.z+box.max.z)/2, pad = 1.2*g.modelScale;
        const candidates = [{ x: box.min.x-pad, z }, { x: box.max.x+pad, z },
            { x, z: box.min.z-pad }, { x, z: box.max.z+pad }]
            .sort((a,b) => Math.hypot(a.x-start.x,a.z-start.z)-Math.hypot(b.x-start.x,b.z-start.z));
        for (const p of candidates) {
            const heading = Math.atan2(p.x-x, p.z-z);
            if (!poseFits(helper,g,{...p,y:g.floorY},posture,heading).ok) continue;
            const route = groundRoute(helper,g,start,p);
            if (route.ok) return { ...route, heading };
        }
        return { ok: false, reason: 'operator_no_supported_approach' };
    }
    function stairRoute(helper, g, start) {
        const stairs = g.walkSurfaces.filter(s => s.kind === 'stair').sort((a,b) => a.elevation-b.elevation);
        if (!g.stairEntry || !stairs.length) return { ok: false, reason: 'operator_stairs_unavailable' };
        const entry = groundRoute(helper,g,start,g.stairEntry);
        if (!entry.ok) return entry;
        const center = s => ({ x:s.polygon.reduce((v,p)=>v+p.x,0)/s.polygon.length,
            z:s.polygon.reduce((v,p)=>v+p.z,0)/s.polygon.length });
        const points = stairs.map(center), last = points[points.length-1];
        const first = points[0], length = Math.hypot(last.x-first.x,last.z-first.z);
        if (length < .01) return { ok:false, reason:'operator_stair_direction_missing' };
        const landing = { x:last.x+(last.x-first.x)/length*.5*g.modelScale,
            z:last.z+(last.z-first.z)/length*.5*g.modelScale };
        const surface = helper.walkthroughSurfaceAtPoint({ point:landing,
            currentElevation:stairs[stairs.length-1].elevation, maximumStepUp:g.maximumStepUp,
            maximumStepDown:g.maximumStepDown, surfaces:g.walkSurfaces });
        if (!surface || surface.kind !== 'platform') return { ok:false, reason:'operator_landing_unavailable' };
        const climb = validatePath(helper,g,entry.end,[...points,landing]);
        return climb.ok ? { ...climb, points:[...entry.points,...climb.points], descent:[...points].reverse().concat(g.stairEntry) } : climb;
    }
    function createTimeline(actions) {
        let index=0, pointIndex=0, elapsed=0, stalled=0, status='playing', reason=null;
        return {
            pause() { if(status==='playing')status='paused'; },
            resume() { if(status==='paused')status='playing'; },
            cancel() { status='cancelled'; },
            snapshot() { return { status, reason, index, pointIndex, elapsed, count:actions.length }; },
            tick(dt, host) {
                if(status!=='playing')return;
                const action=actions[index];
                if(!action){status='complete';return;}
                const fail = message => {status='blocked';reason=message;};
                if(action.kind==='move') {
                    if(!host.posture('standing'))return fail('operator_cannot_stand');
                    const target=action.points[pointIndex];
                    if(!target){index++;pointIndex=0;return;}
                    const p=host.position(), dx=target.x-p.x,dz=target.z-p.z,d=Math.hypot(dx,dz);
                    if(d<.025*host.scale){pointIndex++;stalled=0;return;}
                    const step=Math.min(d,dt*host.speed);
                    if(host.face(Math.atan2(-dx,-dz))===false)return fail('operator_turn_blocked');
                    const travelled=host.move({x:dx/d*step,z:dz/d*step});
                    stalled=travelled<.0001?stalled+dt:0;
                    if(stalled>1)return fail('operator_route_blocked');
                } else {
                    if(Number.isFinite(action.heading) && host.face(action.heading)===false)return fail('operator_turn_blocked');
                    if(!host.posture(action.posture||'standing'))return fail('operator_pose_blocked');
                    host.point(!!action.pointing);
                    elapsed+=dt;
                    if(elapsed>=(action.seconds||3)){elapsed=0;index++;host.point(false);}
                }
            },
        };
    }
    return Object.freeze({ poseFits, transitionFits, movementInput, validatePath, groundObstacles, groundRoute, approach, stairRoute, createTimeline });
}));
