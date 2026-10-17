'use strict';
// Read-only Electron/Playwright rendering checks using the normal authenticated entry.
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const {createHash, randomUUID} = require('node:crypto');
process.env.PW_TEST_SCREENSHOT_NO_FONTS_READY = '1';
const {_electron} = require(path.join(process.env.APPDATA, 'Python/Python314/site-packages/playwright/driver/package'));
const root = path.resolve(__dirname, '..');
const output = path.join(root, '.runtime/private-gym-apex-court-20261007');
const folder = path.join(output, 'playwright');
const current = 'window._trainFacilityLayoutAuthoringApp';
const layoutFile = path.join(root, '.runtime/facility-layout/layouts/local/site-local/layouts/fl-private-gym-20261007.json');
const sha = value => createHash('sha256').update(value).digest('hex');

async function main() {
    await fs.mkdir(folder, {recursive:true});
    const before = await fs.readFile(layoutFile);
    const saved = JSON.parse(before);
    const profile = JSON.parse(await fs.readFile(path.join(output, 'profile.json'), 'utf8'));
    Object.assign(profile, {profileId:'private-gym-apex-viewport-check', origin:'http://127.0.0.1:8550',
        dataRoot:folder, backendId:randomUUID(), storeId:randomUUID()});
    const profilePath = path.join(folder, 'profile.json');
    await fs.writeFile(profilePath, JSON.stringify(profile, null, 2));
    let application;
    const result = {status:'running', captures:[], errors:[]};
    try {
        application = await _electron.launch({
            executablePath:path.join(root, 'desktop/node_modules/electron/dist/electron.exe'),
            args:[path.join(root, 'desktop/src/entry.cjs'), '--application', '--profile-file', profilePath, '--python', 'C:/Python314/python.exe'],
            cwd:root, timeout:120000, env:{...process.env, PW_TEST_SCREENSHOT_NO_FONTS_READY:'1'},
        });
        const page = await application.firstWindow({timeout:120000});
        page.on('pageerror', error => result.errors.push(String(error)));
        await page.waitForFunction(current + '?.session?.getState().loaded', null, {timeout:150000});
        assert.deepEqual(await page.evaluate(current + '.session.getState().layout'), saved);
        await page.evaluate(current + '.workspace._setViewMode("3d")');
        await page.waitForFunction(`(()=>{const d=${current}.workspace.threeAdapter?.getDiagnostics();return d?.pendingLoads===0&&d.representationGroups.filter(g=>g.assetId.startsWith('asset-private-gym-apex-court-')).reduce((n,g)=>n+(g.renderedLightCount||0),0)===6;})()`, null, {timeout:150000});
        for (const [width, height] of [[1440,900], [900,700], [390,844]]) {
            await page.setViewportSize({width,height});
            await page.evaluate(({width,height}) => {
                const adapter = window._trainFacilityLayoutAuthoringApp.workspace.threeAdapter;
                const view = adapter.getCameraView();
                const distance = Math.max(20, 20 * (1440 / 900) / (width / height));
                adapter.applyCameraView({...view, position:{x:71.5,y:4.4,z:36-distance},
                    target:{x:71.5,y:2.7,z:33}, up:{x:0,y:1,z:0}});
            }, {width,height});
            await page.waitForTimeout(1200);
            const rect = await page.evaluate(`(()=>{const r=${current}.workspace.threeAdapter.getRecordingCanvas().getBoundingClientRect();return{x:Math.max(0,r.x),y:Math.max(0,r.y),width:Math.min(r.width,innerWidth-r.x),height:Math.min(r.height,innerHeight-r.y)};})()`);
            assert.ok(rect.width > 100 && rect.height > 100, 'Canvas is not visible at this viewport');
            const raw = await page.screenshot({clip:rect, timeout:15000});
            await fs.writeFile(path.join(folder, `court-${width}.png`), raw);
            const counts = await application.evaluate(({nativeImage}, encoded) => {
                const bitmap = nativeImage.createFromBuffer(Buffer.from(encoded, 'base64')).toBitmap();
                const colors = new Set(); let yellow = 0;
                for (let i=0;i<bitmap.length;i+=4) {
                    const b=bitmap[i],g=bitmap[i+1],r=bitmap[i+2];
                    colors.add((r<<16)|(g<<8)|b);
                    if(r>110&&g>75&&b<g*.8)yellow++;
                }
                return {colors:colors.size,yellow};
            }, raw.toString('base64'));
            assert.ok(counts.colors > 1000 && counts.yellow > 50, 'Court artwork missing or blank');
            result.captures.push({width,height,rect,...counts});
        }
        assert.deepEqual(await page.evaluate(current + '.session.getState().layout'), saved);
        assert.equal(await page.evaluate(current + '.session.getState().dirty'), false);
        assert.equal(sha(await fs.readFile(layoutFile)), sha(before));
        result.status = 'passed';
        result.savedBytesUnchanged = true;
    } catch (error) {
        result.status = 'failed';
        result.error = error.stack;
        process.exitCode = 1;
    } finally {
        if (application) await application.close();
        await fs.writeFile(path.join(folder, 'result.json'), JSON.stringify(result, null, 2));
        console.log(JSON.stringify(result));
    }
}
main().catch(error => {console.error(error); process.exitCode=1;});
