'use strict';

const { fixture, BASELINE, syntheticLayout } = require('./facility_workspace_install_harness.js');

async function main() {
    const rounds = Number(process.env.INSTALL_BENCH_ROUNDS || 3);
    const review = process.argv.includes('--review');
    const flows = review ? ['preview', 'apply', 'undoPreview', 'undoApply'] : ['commit', 'undo'];
    const labels = process.argv.includes('--baseline-only') ? [true] : [true, false];
    const output = { scale: { placements: 2250, assets: 230, zones: 40, floorMarkings: 300,
        layoutBytes: Buffer.byteLength(JSON.stringify(syntheticLayout().layout)) },
        note: 'Node synthetic DOM; no browser layout/paint or 3D model work. selfMs excludes nested stages; ms includes them.', results: {} };
    for (const baseline of labels) {
        const samples = [];
        // One warmup, then measured runs. Keep only one workspace alive at a time.
        for (let i = -1; i < rounds; i++) {
            const f = await fixture(baseline);
            f.setDirect(!review);
            const sample = {};
            if (review) {
                sample.preview = await f.measure(f.commit);
                sample.apply = await f.measure(() => f.session.approveAndApplyLayoutProposal());
                sample.undoPreview = await f.measure(f.undo);
                sample.undoApply = await f.measure(() => f.session.approveAndApplyLayoutProposal());
            } else {
                sample.commit = await f.measure(f.commit);
                sample.undo = await f.measure(f.undo);
            }
            f.dispose();
            if (i >= 0) samples.push(sample);
        }
        const median = values => values.sort((a, b) => a - b)[Math.floor(values.length / 2)];
        output.results[baseline ? BASELINE : 'working-tree'] = Object.fromEntries(flows.map(flow => {
            const stages = Object.keys(samples[0][flow].stages);
            return [flow, { ms: median(samples.map(s => s[flow].ms)), renders: samples[0][flow].renders,
                stages: Object.fromEntries(stages.map(stage => [stage, {
                    calls: samples[0][flow].stages[stage].calls,
                    ms: median(samples.map(s => s[flow].stages[stage].ms)),
                    selfMs: median(samples.map(s => s[flow].stages[stage].selfMs)),
                }])) }];
        }));
    }
    console.log(JSON.stringify(output, null, 2));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
