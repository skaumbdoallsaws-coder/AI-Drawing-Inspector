'use strict';
const {app, dialog, screen} = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');
const {TourControl, verifyArrival, withTimeout} = require('./control.cjs');
const profileFile = process.argv[process.argv.indexOf('--profile-file') + 1];
const out = path.dirname(profileFile);
const root = path.resolve(__dirname, '../..');
const current = 'window._trainFacilityLayoutAuthoringApp';
const adapter = current + '.workspace.threeAdapter';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const event = (name, details = {}) => fs.appendFile(path.join(out, 'events.jsonl'),
    JSON.stringify({time: new Date().toISOString(), event: name, ...details}) + '\n');
const originalDialog = dialog.showMessageBox.bind(dialog);
dialog.showMessageBox = async (...args) => {
    if (args.at(-1).title !== 'InspectorPro startup') return originalDialog(...args);
    await event('startup-error', args.at(-1));
    return {response: 0, checkboxChecked: false};
};

async function rehearse(window) {
    const profile = JSON.parse(await fs.readFile(profileFile, 'utf8'));
    const options = JSON.parse(await fs.readFile(path.join(out, 'tour.json'), 'utf8'));
    assert.equal(profile.profileId, 'factory02-tour');
    assert.equal(path.resolve(profile.facilityRoot), path.join(out, 'store'));
    const relative = 'layouts/local/site-local/layouts/fl-independent-factory-20260928.json';
    const saved = path.join(profile.facilityRoot, relative);
    const live = path.join(root, '.runtime/facility-layout', relative);
    const expected = JSON.parse(await fs.readFile(saved, 'utf8'));
    const report = {status: 'running', scope: options.verifyReady ? 'ready-check' : options.planOnly ? 'plan' : options.full ? 'full' : 'short',
        started: new Date().toISOString(), checkpoints: [], walks: [], blockedWrites: [], errors: []};
    report.sourceHashes = {};
    for (const name of ['tools/factory02_tour/tour.cjs', 'tools/factory02_tour/control.cjs', 'static/facility_layout_three_adapter.js']) {
        report.sourceHashes[name] = sha(await fs.readFile(path.join(root, name)));
    }
    const control = new TourControl(options.waitForCue);
    const persist = () => fs.writeFile(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
    const js = code => withTimeout(window.webContents.executeJavaScript(code, true), 'Renderer command');
    let currentShot = 'Preparing';
    let commandTimer;
    let commandBusy = false;
    let pausedForFocus = false;
    let focusLossTime = null;

    async function paint() {
        await js(`(()=>{const e=document.getElementById('factory-tour-status');if(e)e.textContent=${JSON.stringify(currentShot)};
            const b=document.getElementById('factory-tour-pause');if(b){b.textContent=${JSON.stringify(!control.started ? 'Start tour' : control.paused ? 'Resume' : 'Pause')};b.title='Start, pause or resume tour (F8)';}})()`);
    }
    async function command(value) {
        if (value === 'stop') control.stop();
        else control.toggle();
        await js(`${adapter}?.cancelWalkthroughNavigation('tour_paused')`);
        await event('control', {value, paused: control.paused, stopped: control.stopped});
        await paint();
    }
    const key = (e, input) => {
        if (input.type !== 'keyDown' || input.isAutoRepeat || !['F8', 'F9'].includes(input.key)) return;
        e.preventDefault();
        pausedForFocus = false;
        void command(input.key === 'F9' ? 'stop' : 'pause').catch(error => report.errors.push(error.message));
    };
    window.webContents.on('before-input-event', key);
    const blur = () => {
        focusLossTime = Date.now();
        if (!control.paused && !control.stopped) {
            pausedForFocus = true;
            void command('pause').catch(error => report.errors.push(error.message));
        }
    };
    const focus = () => {
        if (pausedForFocus && control.paused && !control.stopped) {
            pausedForFocus = false;
            void command('pause').catch(error => report.errors.push(error.message));
        }
    };
    window.on('blur', blur);
    window.on('focus', focus);
    // A second guard prevents accidental Save in the disposable session as well.
    window.webContents.session.webRequest.onBeforeRequest({urls: [profile.origin + '/api/facility-layout*']}, (details, callback) => {
        const blocked = !['GET', 'HEAD', 'OPTIONS'].includes(details.method);
        if (blocked) report.blockedWrites.push({method: details.method, url: details.url});
        callback({cancel: blocked});
    });
    async function gate() {
        control.check();
        while (control.paused) {
            await sleep(100); control.check();
            if (control.pauseTimedOut()) throw new Error('Tour paused for five minutes; restart when ready');
        }
        if (focusLossTime !== null) {
            const lostAt = focusLossTime;
            focusLossTime = null;
            const snapshot = await js('window.__factoryTourWalkSnapshot || null');
            if (snapshot && snapshot.time >= lostAt - 1000) {
                const restored = await js(`(()=>{const a=${adapter},s=${JSON.stringify(snapshot)};
                    if(!a.getWalkthroughState().active){a.applyCameraView(s.camera);a.enterWalkthrough({worldPoint:s.state.position,ignoreSelection:true});}
                    else a.enterWalkthrough({ignoreSelection:true});
                    const q=s.camera.quaternion,p=s.state.position,y=p.y+s.state.eyeHeight;
                    a.lookWalkthroughAt({x:p.x-20*(q.x*q.z+q.w*q.y),y:y-20*(q.y*q.z-q.w*q.x),z:p.z+10*(2*(q.x*q.x+q.y*q.y)-1)});
                    return a.getWalkthroughState();})()`);
                assert.ok(restored.active, 'Could not restore paused walkthrough');
                assert.ok(Math.hypot(restored.position.x-snapshot.state.position.x,
                    restored.position.y-snapshot.state.position.y,
                    restored.position.z-snapshot.state.position.z) < 0.001, 'Resume would change walking position');
                await until(`${adapter}.getWalkthroughState().locked`, 5000);
                if (snapshot.state.cameraMode === 'first-person') {
                    const actual = await js(`${adapter}.getCameraView().quaternion`), expected = snapshot.camera.quaternion;
                    assert.ok(Math.abs(['x','y','z','w'].reduce((sum,k)=>sum+actual[k]*expected[k],0)) > .99999, 'Resume changed first-person gaze');
                }
                report.focusRestores = report.focusRestores || [];
                report.focusRestores.push({before: snapshot.state.position, after: restored.position});
                await persist();
            }
        }
    }
    async function hold(ms) {
        const end = control.now() + ms;
        while (control.now() < end) {
            await gate();
            await sleep(Math.max(1, Math.min(100, end - control.now())));
        }
    }
    async function until(code, timeout = 150000) {
        const deadline = Date.now() + timeout;
        while (Date.now() < deadline) {
            control.check();
            if (await js(code)) return;
            await sleep(200);
        }
        throw new Error('Timed out: ' + code);
    }
    async function unchanged() {
        assert.deepEqual(await js(`${current}.session.getState().layout`), expected);
        assert.equal(await js(`${current}.session.getState().dirty`), false);
        assert.equal(sha(await fs.readFile(saved)), options.originalHash);
        assert.equal(sha(await fs.readFile(live)), options.originalHash);
    }
    async function capture(name) {
        await unchanged();
        await js('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
        const shot = await withTimeout(window.webContents.capturePage(), 'Screenshot', 15000);
        assert.ok(!shot.isEmpty());
        const bitmap = shot.toBitmap(), colors = new Set();
        for (let i = 0; i + 4 <= bitmap.length; i += 116) colors.add(bitmap.readUInt32LE(i));
        assert.ok(colors.size > 80, 'Blank capture');
        await fs.writeFile(path.join(out, name + '.png'), shot.toPNG());
        const diagnostic = await js(`${adapter}?.getDiagnostics()`);
        report.checkpoints.push({name, time: new Date().toISOString(), colors: colors.size,
            rendering: diagnostic?.rendering, performance: diagnostic?.performance,
            camera: diagnostic?.camera});
        await persist();
    }
    async function label(name) {
        await gate();
        currentShot = name.replace(/^\d+-/, '').replace(/-/g, ' ');
        currentShot = currentShot.charAt(0).toUpperCase() + currentShot.slice(1);
        await paint(); await event('stage', {name});
    }
    async function camera(position, target, duration = 0) {
        const start = await js(`(()=>{const a=${adapter},v=a.getCameraView();
            if(a.getWalkthroughState().active||a.getDroneState().active){
                const q=v.quaternion,p=v.position;
                v.target={x:p.x-20*(q.x*q.z+q.w*q.y),y:p.y-20*(q.y*q.z-q.w*q.x),z:p.z+10*(2*(q.x*q.x+q.y*q.y)-1)};
                a.exitWalkthrough('tour_aerial');a.exitDrone('tour_aerial');a.applyCameraView(v);
            }return v;})()`);
        const started = control.now();
        do {
            await gate();
            const t = duration ? Math.min(1, (control.now() - started) / duration) : 1;
            const u = t * t * (3 - 2 * t);
            const mix = (a, b) => Object.fromEntries(['x','y','z'].map(k => [k, a[k] + (b[k] - a[k]) * u]));
            await js(`(()=>{const a=${adapter},v=a.getCameraView();v.position=${JSON.stringify(mix(start.position, position))};
                v.target=${JSON.stringify(mix(start.target, target))};v.up={x:0,y:1,z:0};v.fov=55;a.applyCameraView(v);})()`);
            if (t === 1) break;
            await hold(40);
        } while (true);
        await hold(600);
    }
    async function models(ids) {
        await until(`(()=>{const d=${adapter}.getDiagnostics();return !d.degraded&&${JSON.stringify(ids)}.every(id=>d.representationGroups.some(g=>g.assetId===id&&['overview','detail'].includes(g.representation)));})()`);
    }
    async function walk(name, x, z) {
        await label(name);
        const destination = {x, z};
        const start = await js(`${adapter}.getWalkthroughState()`);
        let epoch = -1, plan, lookingAt = -1;
        const started = Date.now();
        const activeStarted = control.now();
        while (true) {
            await gate();
            if (epoch !== control.epoch) {
                assert.ok(await js(`${adapter}.getWalkthroughState().active`), 'Walkthrough exited without a recoverable focus snapshot');
                await js(`${adapter}.enterWalkthrough({ignoreSelection:true})`);
                await until(`${adapter}.getWalkthroughState().locked`, 5000);
                plan = await js(`${adapter}.navigateWalkthroughToPoint(${JSON.stringify(destination)})`);
                await event('route', {name, destination, plan});
                assert.ok(plan.ok, name + ': ' + JSON.stringify(plan));
                epoch = control.epoch;
                lookingAt = -1;
                if (!options.waitForCue && !options.recording && !report.pauseVerified) {
                    await sleep(800);
                    await command('pause');
                    const paused = await js(`${adapter}.getWalkthroughState()`);
                    await sleep(700);
                    const held = await js(`${adapter}.getWalkthroughState()`);
                    assert.deepEqual(held.position, paused.position);
                    assert.equal(held.route.active, false);
                    report.pauseVerified = true;
                    await command('pause');
                    continue;
                }
            }
            const state = await js(`${adapter}.getWalkthroughState()`);
            if (control.paused || epoch !== control.epoch) continue;
            if (state.route.reason === 'window_blurred' && !window.isFocused()) {blur(); continue;}
            if (!state.active || !state.locked) throw new Error(name + ': walkthrough lost control');
            if (!state.route.active) {verifyArrival(state, destination); break;}
            if (state.route.pointIndex !== lookingAt) {
                const next = plan.points[state.route.pointIndex];
                if (next) await js(`${adapter}.lookWalkthroughAt({x:${next.x},y:${state.position.y + state.eyeHeight},z:${next.z}})`);
                lookingAt = state.route.pointIndex;
            }
            await hold(150);
            if (control.now() - activeStarted > 180000) throw new Error(name + ': route timed out');
        }
        const end = await js(`${adapter}.getWalkthroughState()`);
        report.walks.push({name, from: start.position, to: end.position, destination,
            elapsedMs: Date.now() - started, collisions: end.collisionCount - start.collisionCount,
            performance: end.performance});
        await persist(); await hold(600);
    }
    async function treeRow(id, expand = false) {
        await js(`(()=>{const row=[...document.querySelectorAll('#structureTreeHost .ip-fst-row')].find(r=>r.dataset.rowId===${JSON.stringify(id)});
            if(!row)throw Error('Missing tree row '+${JSON.stringify(id)});row.scrollIntoView({block:'nearest'});
            if(${expand}&&row.getAttribute('aria-expanded')==='true')return;
            row.childNodes[${expand ? 0 : 2}].dispatchEvent(new MouseEvent('click',{bubbles:true}));})()`);
    }
    try {
        await persist();
        window.maximize();
        await until(`${current}?.session?.getState().loaded`);
        await unchanged();
        await js(`(()=>{window.__factoryTourCommands=[];const p=document.createElement('div');p.id='factory-tour-controls';
            p.hidden=true;p.setAttribute('aria-hidden','true');p.style.display='none';
            p.innerHTML='<span id="factory-tour-status">Preparing</span><button id="factory-tour-pause">Pause</button><button id="factory-tour-stop" title="Stop tour (F9)">Stop</button>';
            document.body.appendChild(p);p.querySelector('#factory-tour-pause').onclick=()=>window.__factoryTourCommands.push('pause');
            p.querySelector('#factory-tour-stop').onclick=()=>window.__factoryTourCommands.push('stop');})()`);
        await js(`(()=>{const remember=()=>{const a=${adapter},state=a.getWalkthroughState();
            if(state.active)window.__factoryTourWalkSnapshot={time:Date.now(),state,camera:a.getCameraView()};};
            window.addEventListener('blur',remember,true);
            document.addEventListener('pointerlockchange',()=>{if(!document.pointerLockElement)remember();},true);})()`);
        commandTimer = setInterval(async () => {
            if (commandBusy) return;
            commandBusy = true;
            try {for (const value of await js('window.__factoryTourCommands.splice(0)')) await command(value);}
            catch (error) {report.errors.push(error.message);}
            finally {commandBusy = false;}
        }, 150);
        await js(`${current}.workspace._setViewMode('plan');window._setLeftPanelContent('structure',{reveal:true})`);
        currentShot = control.started ? 'Preparing tour' : 'Ready to record';
        await paint();
        report.window = {maximized: window.isMaximized(), bounds: window.getBounds(),
            workArea: screen.getDisplayMatching(window.getBounds()).workArea};
        report.waitingForCue = !control.started;
        await persist();
        await event('ready', {waitingForCue: !control.started, maximized: window.isMaximized()});
        if (options.verifyReady) {
            assert.ok(window.isMaximized(), 'Tour window is not maximized');
            const selection = await js(`${current}.workspace.structureSource().selection`);
            await sleep(1500);
            blur(); focus();
            await sleep(500);
            assert.equal(control.paused, true, 'Focus change started the tour');
            assert.equal(control.started, false);
            assert.equal(report.walks.length, 0);
            assert.equal(report.checkpoints.length, 0);
            assert.deepEqual(await js(`${current}.workspace.structureSource().selection`), selection);
            assert.equal(await js("document.getElementById('factory-tour-pause').textContent"), 'Start tour');
            assert.equal(await js("document.getElementById('factory-tour-controls').getClientRects().length"), 0);
            await capture('00-ready');
            window.focus();
            window.webContents.sendInputEvent({type:'keyDown',keyCode:'F8'});
            window.webContents.sendInputEvent({type:'keyUp',keyCode:'F8'});
            const cueDeadline = Date.now() + 5000;
            while (!control.started && Date.now() < cueDeadline) await sleep(50);
            assert.equal(control.started, true, 'F8 did not accept the explicit cue');
            await command('stop');
            report.overlayHiddenVerified = true;
            report.readyGateVerified = true;
            report.status = 'passed';
            return;
        }
        await label('2D overview');
        await hold(1500); await capture('01-plan');
        await label('Structure: manufacturing zones');
        await treeRow('zn-independent-automation'); await hold(1500); await capture('02-zone-selection');
        assert.deepEqual(await js(`${current}.workspace.structureSource().selection`), ['zn-independent-automation']);
        await treeRow('zn-parking-office-extension', true);
        await treeRow('zn-parking-office-office', true);
        const group = await js(`(()=>{const w=${current}.workspace,m=window.InspectorProFacilityStructure.deriveStructure(w.structureSource().layout);
            return m.zones['zn-parking-office-office'].groups.find(g=>g.placementIds.includes('pl-parking-office-cubicle-04'));})()`);
        assert.ok(group);
        if (group.placementIds.length > 1) await treeRow(group.rowId, true);
        await treeRow(group.placementIds.length > 1 ? 'pl-parking-office-cubicle-04' : group.rowId);
        assert.deepEqual(await js(`${current}.workspace.structureSource().selection`), ['pl-parking-office-cubicle-04']);
        await label('Structure: office cubicle selection');
        // Selection opens the inspector; let its resize-triggered fit settle first.
        await hold(1200);
        const selectionScale = await js(`${current}.workspace.topAdapter.getViewportState().projection.scale`);
        await js(`(()=>{const a=${current}.workspace.topAdapter,position={x:317,z:14.7};
            for(const factor of [4,3]){const p=a.worldToClient(position);a.zoomAt({clientX:p.x,clientY:p.y},factor);}
            const p=a.worldToClient(position),r=a.svg.getBoundingClientRect();a.panByPixels(r.left+r.width/2-p.x,r.top+r.height/2-p.y);
            a.setSelections(${current}.workspace.structureSource().selection);})()`);
        await hold(1500);
        report.selectionZoom = await js(`(()=>{const a=${current}.workspace.topAdapter,p=a.worldToClient({x:317,z:14.7}),r=a.svg.getBoundingClientRect();
            return {scale:a.getViewportState().projection.scale,centerError:Math.hypot(p.x-r.left-r.width/2,p.y-r.top-r.height/2)};})()`);
        assert.ok(report.selectionZoom.scale >= selectionScale * 8, 'Plan selection zoom was reset');
        assert.ok(report.selectionZoom.centerError < 2, 'Selected cubicle is not centered');
        await capture('03-asset-selection');
        if (options.planOnly) {
            assert.equal(report.blockedWrites.length, 0);
            report.status = 'passed';
            return;
        }
        await label('3D top view');
        await js(`${current}.session.selectMany([]);${current}.workspace.topAdapter.fitFacility();${current}.workspace._setViewMode('3d')`);
        await until(`!!${current}.workspace.lastLayoutFingerprint&&${current}.workspace.lastThreeFitFingerprint===${current}.workspace.lastLayoutFingerprint`);
        await js(`${adapter}.topView()`); await hold(2500); await capture('04-top');
        await label('Concept Car');
        await js(`if(document.getElementById('structureTreeHost').offsetParent)window._toggleLeftPanel()`);
        await camera({x: 347.4, y: 2.1, z: 38.8}, {x: 344.4, y: .8, z: 34.9}, 3000);
        await models(['asset-vehicle-collection-concept']); await capture('05-concept-car');
        await js(`${adapter}.setWalkthroughCameraMode('third-person');${adapter}.setWalkthroughCameraSettings({distance:5,height:.5});
            ${adapter}.enterWalkthrough({worldPoint:{x:347.4,z:38.8},ignoreSelection:true})`);
        await until(`${adapter}.getWalkthroughState().locked`, 5000);
        await walk('Parking to office entrance', 326.5, 19);
        await walk('Office doorway', 323, 19);
        await walk('Shared lunchroom entrance', 313.5, 27);
        await walk('Cafe entrance', 313.5, 30.5);
        await capture('06-cafe-entrance');
        if (!options.waitForCue && !options.recording) {
            await js(`${adapter}.setWalkthroughCameraMode('first-person');${adapter}.lookWalkthroughAt({x:313.5,y:1.1,z:44})`);
            const before = await js(`${adapter}.getWalkthroughState().position`);
            await js('document.exitPointerLock()');
            blur(); await sleep(800); focus(); await gate();
            assert.deepEqual(await js(`${adapter}.getWalkthroughState().position`), before);
            report.focusRecoveryVerified = true;
            await capture('06b-focus-recovery');
        }
        if (options.full) await fullTour({walk, label, capture, camera, models, js, hold, adapter, expected});
        await unchanged();
        const d = await js(`${adapter}.getDiagnostics()`);
        report.audit = {missing: d.placementTransformAudit.missingPlacementCount,
            mismatches: d.placementTransformAudit.transformMismatchCount, degraded: d.degraded};
        assert.deepEqual(report.audit, {missing: 0, mismatches: 0, degraded: false});
        assert.equal(report.blockedWrites.length, 0);
        report.status = 'passed';
    } catch (error) {
        report.status = control.stopped ? 'stopped' : 'failed';
        report.error = error.stack;
        await capture('failure').catch(() => {});
    } finally {
        clearInterval(commandTimer);
        window.webContents.removeListener('before-input-event', key);
        window.removeListener('blur', blur);
        window.removeListener('focus', focus);
        await js(`${adapter}?.cancelWalkthroughNavigation('tour_finished');${adapter}?.exitWalkthrough('tour_finished')`).catch(() => {});
        try {await unchanged(); report.savedStateUnchanged = true;}
        catch (error) {report.savedStateUnchanged = false; report.status = 'failed'; report.errors.push(error.message);}
        report.finished = new Date().toISOString();
        await persist();
        app.quit();
    }
}

async function fullTour({walk, label, capture, camera, models, js, hold, adapter, expected}) {
    async function detail(name, target, placementIds = []) {
        await label(name);
        await js(`${adapter}.setWalkthroughCameraMode('first-person');${adapter}.lookWalkthroughAt(${JSON.stringify(target)})`);
        const ids = [...new Set(placementIds.map(id => {
            const placement = expected.placements.find(p => p.placementId === id);
            assert.ok(placement, 'Missing tour subject: ' + id);
            return placement.assetId;
        }))];
        if (ids.length) await models(ids);
        await hold(2000); await capture(name);
    }
    await walk('Lunchroom central aisle', 313.5, 44);
    await detail('07-lunchroom', {x: 307, y: 1, z: 38}, ['pl-independent-cafeteria-table-5']);
    await walk('Coffee station approach', 324, 54.47);
    await detail('08-coffee-station', {x: 327.54, y: 1.15, z: 54.47},
        ['pl-breakroom-coffee-pot', 'pl-breakroom-microwave', 'pl-independent-cafeteria-kitchen']);
    await walk('Lunchroom exit', 313.5, 59);
    await walk('Shared corridor', 313.5, 62.3);
    await walk('Gym access corridor', 331, 62.3);
    await walk('Gym entrance', 331, 84);
    await walk('Inside gym', 325.5, 84);
    await detail('09-gym-strength', {x: 319, y: 1.2, z: 79.3}, ['pl-gym-squat-rack-02', 'pl-gym-multi-gym']);
    await walk('Gym central aisle', 314, 84);
    await detail('10-gym-equipment', {x: 315, y: 1.2, z: 89}, ['pl-gym-bench-press-01', 'pl-gym-dumbbell-rack-01']);
    await walk('Leave gym', 331, 84);
    await walk('Return to shared corridor', 331, 62.3);
    await walk('Lunchroom doorway', 313.5, 62.3);
    await walk('Lunchroom main aisle', 313.5, 59);
    await walk('Return to office', 313.5, 30.5);
    await walk('Office shared doorway', 313.5, 27);
    await walk('Office central aisle', 317, 19);
    await detail('11-office-workstations', {x: 316.33, y: 1.15, z: 14.03},
        ['pl-parking-office-cubicle-04', 'pl-cubicle-04-monitor', 'pl-parking-office-chair-04']);
    await walk('Office to lunchroom', 313.5, 30.5);
    await walk('Lunchroom to meeting rooms', 313.5, 59);
    await walk('Conference corridor', 313.5, 62.3);
    await walk('Boardroom door', 303.5, 62.3);
    await walk('Boardroom interior', 303.5, 66);
    await detail('12-boardroom', {x: 305.75, y: 1.4, z: 73.8}, ['pl-conference-boardroom-table-1']);
    await walk('Boardroom exit', 303.5, 62.3);
    await walk('Conference 02 door', 311.2, 62.3);
    await walk('Conference 02 interior', 311.2, 65.7);
    await detail('13-conference-02', {x: 312.7, y: 1.4, z: 70.7}, ['pl-conference-meeting-a-table-1']);
    await walk('Conference 02 exit', 311.2, 62.3);
    await walk('Conference 03 door', 317.4, 62.3);
    await walk('Conference 03 interior', 317.4, 65.7);
    await detail('14-conference-03', {x: 318.9, y: 1.4, z: 70.7}, ['pl-conference-meeting-b-table-1']);
    await walk('Conference 03 exit', 317.4, 62.3);
    await walk('Annex access', 331, 62.3);
    await walk('Factory east approach', 331, 98);
    await js(`${adapter}.setWalkthroughCameraMode('third-person')`);
    await walk('Factory east entrance', 297, 98);
    await walk('Factory main aisle east', 194, 98);
    await walk('Factory main aisle west', 72, 98);
    await walk('Receiving approach', 63, 114);
    await walk('Receiving racks', 63, 138);
    await detail('15-receiving', {x: 38, y: 1.8, z: 153});
    await walk('Machining approach', 77, 138);
    await walk('CNC operator aisle', 86, 141);
    await detail('16-machining', {x: 88, y: 1.3, z: 146}, ['pl-independent-0677']);
    await walk('Machining production aisle', 181, 141);
    await walk('Robot cell approach', 194, 111);
    await walk('Robot cell R01', 211, 111);
    await detail('17-robotic-production', {x: 211, y: 1.3, z: 122}, ['pl-independent-0035']);
    await walk('Main aisle crossing', 211, 98);
    await walk('Inspection approach', 211, 86);
    await detail('18-inspection-packing', {x: 224, y: 1, z: 73});
    await walk('Assembly crossing', 194, 98);
    await walk('Assembly approach', 181, 78);
    await walk('Assembly cell aisle', 166, 74);
    await detail('19-assembly-kitting', {x: 164.5, y: 1, z: 68}, ['pl-independent-0781']);
    await walk('Assembly to logistics', 72, 98);
    await walk('Finished goods approach', 63, 87);
    await walk('Finished goods racks', 63, 62);
    await detail('20-finished-goods', {x: 38, y: 1.8, z: 52});
    await walk('Shipping dock approach', 63, 98);
    await walk('Factory side of dock opening', 3, 98);
    await detail('21-shipping-dock', {x: -20, y: 1, z: 77});
    await label('Docks and lowered truck yard');
    // Lift vertically through the roofless opening, then cross above the walls.
    await camera({x: 3, y: 25, z: 98}, {x: -20, y: 0, z: 77}, 4000);
    await camera({x: -65, y: 42, z: 44}, {x: -5, y: -1.35, z: 60}, 6000);
    await capture('22-shipping-yard');
    await camera({x: -65, y: 42, z: 156}, {x: -5, y: -1.35, z: 153}, 8000);
    await capture('23-receiving-docks');
    await label('Return over factory to employee parking');
    await camera({x: 150, y: 100, z: 150}, {x: 245, y: 0, z: 145}, 10000);
    await camera({x: 352, y: 40, z: 185}, {x: 338, y: 0, z: 145}, 10000);
    await models(['asset-import-car-93', 'asset-import-tesla-roadster', 'asset-vehicle-collection-concept']);
    await capture('24-employee-parking');
    await camera({x: 369, y: 1.65, z: 188}, {x: 352, y: 1.1, z: 181}, 8000);
    await js(`${adapter}.enterWalkthrough({worldPoint:{x:369,z:188},ignoreSelection:true});${adapter}.setWalkthroughCameraMode('third-person')`);
    await walk('Employee parking closing walk', 369, 177);
    await detail('25-parking-close', {x: 344, y: 1.1, z: 169});
    await label('Factory 02 closing overview');
    await camera({x: 390, y: 125, z: 230}, {x: 175, y: 0, z: 100}, 10000);
    await capture('26-factory-overview');
}

app.once('browser-window-created', (_e, window) => {
    window.maximize();
    window.webContents.once('dom-ready', () => {
        void rehearse(window).catch(async error => {
            await event('driver-error', {error: error.stack}); app.quit();
        });
    });
});
require('../../desktop/src/entry.cjs');
