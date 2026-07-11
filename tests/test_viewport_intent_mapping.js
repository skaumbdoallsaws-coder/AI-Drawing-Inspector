// Deterministic tests for the frontend half of the hybrid intent layer:
// classifier output -> validated ui_actions. Loads the REAL resolver/mapping
// code extracted from static/index.html plus the REAL motion package summary.
// Run: node tests/test_viewport_intent_mapping.js
// NOTE: no 'use strict' -- the extracted functions are installed into this
// module's scope via sloppy-mode eval().
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');

const lines = fs.readFileSync(path.join(ROOT, 'static', 'index.html'), 'utf8').split('\n');
const start = lines.findIndex(l => l.includes('function _normalizeAssemblyDisplayText'));
const end = lines.findIndex(l => l.includes('function shouldSuppressAssistantResponseForToolCalls'));
if (start < 0 || end <= start) throw new Error('extraction markers not found');
const src = lines.slice(start, end).join('\n');

const summary = JSON.parse(fs.readFileSync(
    path.join(ROOT, 'generated', 'engine_motion', 'motion', 'engine4cyl_crank_cycle_summary.json'), 'utf8'));
const authorizationFixture = JSON.parse(fs.readFileSync(
    path.join(ROOT, 'tests', 'fixtures', 'viewport_authorization_cases.json'), 'utf8'));

let state = { activeTab: 'assembly', motionPkgInfo: { summary }, partExplorerAgentParts: new Set() };
const assemblyContext = { part_color_legend: [
    { part_number: '100001', description: 'Engine Block Upper' },
    { part_number: '100002', description: 'Engine Block Lower' },
    { part_number: '100003', description: 'Crankshaft' },
    { part_number: '100004', description: 'Connecting Rod' },
    { part_number: '100005', description: 'Connecting Rod Cap' },
    { part_number: '100006', description: 'Piston' },
    { part_number: '100007', description: 'Piston Pin' },
    { part_number: '100008', description: 'Piston Ring' },
    { part_number: '100009', description: 'Socket Head Cap Screw' },
]};

eval(src);

let passed = 0, failed = 0;
function check(name, cond, detail) {
    if (cond) { passed++; console.log('PASS ' + name); }
    else { failed++; console.log('FAIL ' + name + (detail ? ' :: ' + detail : '')); }
}
function actionsOf(result) {
    const tc = (result.toolCalls || []).find(c => c && c._classifiedIntent);
    return tc ? tc.args.actions : [];
}
function allUiActionsOf(result) {
    return (result.toolCalls || [])
        .filter(c => c && c.name === 'ui_actions' && c.args && Array.isArray(c.args.actions))
        .flatMap(c => c.args.actions);
}
function vi(overrides) {
    return Object.assign({
        intent_kind: 'none', workflow: 'assembly', targets: [],
        motion: { requested: false, speed: null, rpm: null },
        display: { hidden: null, opacity: null },
        mode: null, confidence: 0.9, needs_clarification: false,
        clarification_question: null,
    }, overrides);
}
const target = (kind, extra) => Object.assign(
    { kind, label: '', part_numbers: [], feature_ids: [], motion_group_id: null }, extra);

// Phase 0 shared authorization vectors. The Python/server test consumes the
// same JSON fixture, so either implementation drifting fails the same cases.
for (const item of authorizationFixture.cases || []) {
    const expected = item.expected || {};
    const actual = {
        explicit_action: _messageExplicitlyRequestsViewportChange(item.message),
        state_question: _isViewportStateQuestion(item.message),
        allow_additive: _viewportWriteAuthorized(item.message, false),
        allow_destructive: _viewportWriteAuthorized(item.message, true),
    };
    check(`AUTH ${item.id}`,
        actual.explicit_action === expected.explicit_action
        && actual.state_question === expected.state_question
        && actual.allow_additive === expected.allow_additive
        && actual.allow_destructive === expected.allow_destructive,
        JSON.stringify({ expected, actual }));
}

// 1. "show the pin joint" -> highlight only, no play_motion
{
    const r = _applyClassifiedViewportIntentToToolCalls('show the pin joint', [], vi({
        intent_kind: 'highlight',
        targets: [target('part', { part_numbers: ['100006', '100007', '100004'], label: 'pin joint' })],
        mode: 'replace',
    }));
    const a = actionsOf(r);
    check('1 highlight applies', r.applied === true);
    check('1 set_part_highlight only', a.length === 1 && a[0].type === 'set_part_highlight'
        && a[0].part_numbers.join() === '100006,100007,100004', JSON.stringify(a));
    check('1 no play_motion', !a.some(x => x.type === 'play_motion'));
}

// 1b. If the classifier over-classifies a plain target request as
// highlight_motion, the executor downgrades it to highlight only and strips
// any model-supplied playback. "Show X" must not mean "animate X".
{
    const modelCalls = [{ name: 'ui_actions', args: { workspace: 'assembly', actions: [
        { type: 'play_motion', motion_id: 'engine4cyl_crank_cycle', rpm: 30, loop: true },
    ] } }];
    const r = _applyClassifiedViewportIntentToToolCalls('show the pin joint', modelCalls, vi({
        intent_kind: 'highlight_motion',
        targets: [target('motion_group', { motion_group_id: 'pin_bore_fai_affected', label: 'pin joint' })],
        motion: { requested: true, speed: 'normal', rpm: null },
    }));
    const a = actionsOf(r);
    const all = allUiActionsOf(r);
    check('1b overclassified plain joint applies', r.applied === true);
    check('1b downgraded to highlight action', a.length === 1 && a[0].type === 'set_part_highlight'
        && a[0].part_numbers.join() === '100004,100005,100006,100007', JSON.stringify(a));
    check('1b no playback survives', !all.some(x => x.type === 'play_motion'), JSON.stringify(all));
}

// 1c. Feature/joint labels from the classifier can be narrower than the
// semantic package. Resolve joint/interface feature labels against declared
// motion groups so "pin joint" highlights the joint context, not just the pin.
{
    const r = _applyClassifiedViewportIntentToToolCalls('show the pin joint', [], vi({
        intent_kind: 'highlight',
        targets: [target('feature', { label: 'pin joint', part_numbers: ['100007'] })],
        motion: { requested: false, speed: null, rpm: null },
        mode: 'replace',
    }));
    const a = actionsOf(r);
    check('1c feature joint resolves to semantic group', r.applied === true);
    check('1c group parts highlighted', a.length === 1 && a[0].type === 'set_part_highlight'
        && a[0].part_numbers.join() === '100004,100005,100006,100007', JSON.stringify(a));
    check('1c still no play_motion', !a.some(x => x.type === 'play_motion'), JSON.stringify(a));
    const savedAgentParts = state.partExplorerAgentParts;
    state.partExplorerAgentParts = new Set(['100004', '100005', '100006', '100007']);
    const line = _viewportExecutionStatusLine({
        kind: 'highlight',
        labels: [],
        partNumbers: ['100004', '100005', '100006', '100007'],
        rpm: null,
        motionName: null,
        groupLabel: 'Pin bore affected motion group',
    });
    state.partExplorerAgentParts = savedAgentParts;
    check('1c status confirms applied group highlight',
        line === 'Highlighted Pin bore affected motion group in the assembly viewport.',
        line);
}

// 2. "show the pin joint in motion slowly" -> highlight_motion at 30 RPM
{
    const r = _applyClassifiedViewportIntentToToolCalls('show the pin joint in motion slowly', [], vi({
        intent_kind: 'highlight_motion',
        targets: [target('motion_group', { motion_group_id: 'pin_bore_fai_affected', label: 'pin joint' })],
        motion: { requested: true, speed: 'slow', rpm: null },
    }));
    const a = actionsOf(r);
    const play = a.find(x => x.type === 'play_motion');
    const hl = a.find(x => x.type === 'set_part_highlight');
    check('2 applies', r.applied === true);
    check('2 group parts highlighted', hl && hl.part_numbers.join() === '100004,100005,100006,100007', JSON.stringify(hl));
    check('2 play at 30 rpm', play && play.rpm === 30 && play.motion_id === 'engine4cyl_crank_cycle', JSON.stringify(play));
}

// 3. typo phrasing ending in "?" must still execute (non-destructive kind)
{
    const r = _applyClassifiedViewportIntentToToolCalls('can you the show the affected motion?', [], vi({
        intent_kind: 'highlight_motion',
        targets: [target('motion_group', { motion_group_id: 'pin_bore_fai_affected', label: 'affected motion' })],
        motion: { requested: true, speed: 'slow', rpm: null },
    }));
    const a = actionsOf(r);
    check('3 typo question applies', r.applied === true);
    check('3 play_motion present', a.some(x => x.type === 'play_motion' && x.rpm === 30), JSON.stringify(a));
}

// 4. "hide the lower block" -> set_part_display only; model stop/clear stripped
{
    const modelCalls = [{ name: 'ui_actions', args: { workspace: 'assembly', actions: [
        { type: 'set_part_display', part_numbers: ['100002'], hidden: true },
        { type: 'stop_motion' },
        { type: 'clear_part_highlight', all: true },
    ] } }];
    const r = _applyClassifiedViewportIntentToToolCalls('hide the lower block', modelCalls, vi({
        intent_kind: 'hide',
        targets: [target('part', { part_numbers: ['100002'], label: 'lower block' })],
        display: { hidden: true, opacity: null },
    }));
    const a = actionsOf(r);
    const allActions = (r.toolCalls || [])
        .filter(c => c && c.name === 'ui_actions')
        .flatMap(c => c.args.actions);
    check('4 hide applies', r.applied === true);
    check('4 injected hide only', a.length === 1 && a[0].type === 'set_part_display' && a[0].hidden === true);
    check('4 no stop_motion survives', !allActions.some(x => x.type === 'stop_motion'), JSON.stringify(allActions));
    check('4 no clear_part_highlight survives', !allActions.some(x => x.type === 'clear_part_highlight'));
}

// 5. "bring all hidden parts back" -> restore = both clears
{
    const r = _applyClassifiedViewportIntentToToolCalls('bring everything back', [], vi({
        intent_kind: 'restore',
        targets: [target('all', { label: 'everything' })],
    }));
    const a = actionsOf(r);
    check('5 restore applies', r.applied === true);
    check('5 clear display all', a.some(x => x.type === 'clear_part_display' && x.all === true));
    check('5 clear highlight all', a.some(x => x.type === 'clear_part_highlight' && x.all === true));
}

// 5b. A named part can be invisible because an existing highlight set is
// isolating other parts. "Bring/show crankshaft" must add it to that set,
// not merely clear display overrides.
{
    const savedAgentParts = state.partExplorerAgentParts;
    state.partExplorerAgentParts = new Set(['100004', '100005', '100006', '100007']);
    const r = _applyClassifiedViewportIntentToToolCalls('bring the crankshaft', [], vi({
        intent_kind: 'show',
        targets: [target('part', { part_numbers: ['100003'], label: 'crankshaft' })],
    }));
    const a = actionsOf(r);
    check('5b named show applies under active highlight', r.applied === true);
    check('5b clears display and adds highlight',
        a.some(x => x.type === 'clear_part_display' && x.part_numbers.join() === '100003')
        && a.some(x => x.type === 'set_part_highlight' && x.mode === 'add' && x.part_numbers.join() === '100003'),
        JSON.stringify(a));

    const fallback = _applyAssemblyDisplayIntentToToolCalls('bring the crankshaft', []);
    const fa = allUiActionsOf(fallback);
    check('5b fallback also adds named part to highlight',
        fa.some(x => x.type === 'clear_part_display' && x.part_numbers.join() === '100003')
        && fa.some(x => x.type === 'set_part_highlight' && x.mode === 'add' && x.part_numbers.join() === '100003'),
        JSON.stringify(fa));

    state.partExplorerAgentParts = new Set(['100004', '100005', '100006', '100007', '100003']);
    const line = _viewportExecutionStatusLine({
        kind: 'show',
        labels: [],
        partNumbers: ['100003'],
        rpm: null,
        motionName: null,
        groupLabel: null,
    });
    check('5b status confirms restored visible part',
        line === 'Restored Crankshaft (100003).',
        line);
    state.partExplorerAgentParts = savedAgentParts;
}

// 6. "rotate the view" -> rotate_view only, no motion
{
    const r = _applyClassifiedViewportIntentToToolCalls('rotate the view', [], vi({
        intent_kind: 'rotate',
    }));
    const a = actionsOf(r);
    check('6 rotate applies', r.applied === true);
    check('6 rotate_view only', a.length === 1 && a[0].type === 'rotate_view' && a[0].direction === 'right');
    check('6 no play_motion', !a.some(x => x.type === 'play_motion'));
}

// 7. "turn the crankshaft" -> mechanism motion when a package exists
{
    const r = _applyClassifiedViewportIntentToToolCalls('turn the crankshaft', [], vi({
        intent_kind: 'motion',
        targets: [target('motion_group', { motion_group_id: 'crankshaft_drive', label: 'crankshaft' })],
        motion: { requested: true, speed: null, rpm: null },
    }));
    const a = actionsOf(r);
    const play = a.find(x => x.type === 'play_motion');
    check('7 motion applies', r.applied === true);
    // Group-focused playback defaults to the detail-view rate (30 RPM,
    // the slow end of the contract's 30-40 window), not default_rpm.
    check('7 play_motion group-focused rpm', play && play.rpm === 30, JSON.stringify(play));

    // 7b. Same intent with NO motion package -> must NOT apply (falls back)
    const saved = state.motionPkgInfo;
    state.motionPkgInfo = null;
    const r2 = _applyClassifiedViewportIntentToToolCalls('turn the crankshaft', [], vi({
        intent_kind: 'motion',
        targets: [target('motion_group', { motion_group_id: 'crankshaft_drive' })],
        motion: { requested: true, speed: null, rpm: null },
    }));
    state.motionPkgInfo = saved;
    check('7b no package -> not applied', r2.applied === false);
}

// 7c. Whole-assembly motion must not isolate a semantic subgroup, even if
// the classifier over-targets one. Keep all parts visible and just play.
{
    const r = _applyClassifiedViewportIntentToToolCalls('show me how this assembly moves', [], vi({
        intent_kind: 'highlight_motion',
        targets: [target('motion_group', { motion_group_id: 'reciprocating_group', label: 'reciprocating components' })],
        motion: { requested: true, speed: 'normal', rpm: null },
    }));
    const a = actionsOf(r);
    check('7c whole assembly applies', r.applied === true);
    check('7c clears agent highlights only', a.some(x => x.type === 'clear_part_highlight' && x.all === false), JSON.stringify(a));
    check('7c no subgroup highlight', !a.some(x => x.type === 'set_part_highlight'), JSON.stringify(a));
    check('7c plays motion at visual rate', a.some(x => x.type === 'play_motion' && x.rpm === 30), JSON.stringify(a));

    const legacy = _resolveMotionGroupIntent('show me how this assembly moves');
    check('7c legacy whole assembly has no highlighted parts',
        legacy && legacy.partNumbers.length === 0 && legacy.clearAgentHighlights === true,
        JSON.stringify(legacy));
    const legacyMapped = _applyMotionGroupIntentToToolCalls('show me how this assembly moves', []);
    const legacyActions = allUiActionsOf(legacyMapped);
    check('7c legacy maps to clear + play only',
        legacyActions.some(x => x.type === 'clear_part_highlight' && x.all === false)
        && legacyActions.some(x => x.type === 'play_motion')
        && !legacyActions.some(x => x.type === 'set_part_highlight'),
        JSON.stringify(legacyActions));
}

// 8. State questions never destroy state, even if the classifier misfires
{
    const r = _applyClassifiedViewportIntentToToolCalls('what is hidden?', [], vi({ intent_kind: 'none' }));
    check('8 none -> not applied', r.applied === false);
    const rBad = _applyClassifiedViewportIntentToToolCalls('did you clear highlights?', [], vi({
        intent_kind: 'clear_highlight', confidence: 0.95,
    }));
    check('8 destructive misfire blocked by question guard', rBad.applied === false);
    const rBad2 = _applyClassifiedViewportIntentToToolCalls('is the lower block hidden?', [], vi({
        intent_kind: 'hide',
        targets: [target('part', { part_numbers: ['100002'] })],
    }));
    check('8 hide misfire blocked on question', rBad2.applied === false);
}

// 9. FAI explanation/disposition questions are prose-first. If the user did
// not explicitly ask to show/highlight/hide/animate/rotate, viewport actions
// from the model or classifier must be suppressed.
{
    const savedTab = state.activeTab;
    const savedFai = state.faiCharacteristics;
    state.activeTab = 'report';
    state.faiCharacteristics = [{ key: 'row5', charNumber: 5 }];
    check('9 FAI impact question suppresses implicit viewport',
        _shouldSuppressImplicitFaiViewportActions('For FAI item #5, what does this failure mean in the assembly?') === true);
    check('9 FAI show-meaning wording still suppresses implicit viewport',
        _shouldSuppressImplicitFaiViewportActions('show me what this failure means in the assembly') === true);
    check('9 explicit affected motion is allowed',
        _shouldSuppressImplicitFaiViewportActions('show the affected motion') === false);
    check('9 explicit affected parts is allowed',
        _shouldSuppressImplicitFaiViewportActions('highlight the affected parts in the assembly') === false);
    const stripped = _stripViewportDisruptiveToolCalls([
        { name: 'highlight_parts', args: { part_numbers: ['100006'] } },
        { name: 'highlight_features', args: { feature_ids: ['ice_cut_extrude1'] } },
        { name: 'fai_fill', args: { values: { '5': '30.100' } } },
        { name: 'ui_actions', args: { workspace: 'assembly', actions: [
            { type: 'set_part_highlight', part_numbers: ['100006'], mode: 'replace' },
            { type: 'play_motion', motion_id: 'engine4cyl_crank_cycle', rpm: 30, loop: true },
        ] } },
    ], {
        stripHighlightParts: true,
        stripFeatureHighlights: true,
        stripHighlightActions: true,
        stripDisplayActions: true,
        stripRotateStop: true,
        stripMotionStart: true,
    });
    check('9 strip keeps FAI table tools only',
        stripped.length === 1 && stripped[0].name === 'fai_fill',
        JSON.stringify(stripped));
    state.activeTab = savedTab;
    state.faiCharacteristics = savedFai;
}

// Validation extras: unknown parts / low confidence / clarification
{
    const rUnknown = _applyClassifiedViewportIntentToToolCalls('hide the flux capacitor', [], vi({
        intent_kind: 'hide',
        targets: [target('part', { part_numbers: ['999999'] })],
    }));
    check('V unknown part -> not applied', rUnknown.applied === false);

    const rLow = _applyClassifiedViewportIntentToToolCalls('show the pin joint', [], vi({
        intent_kind: 'highlight', confidence: 0.4,
        targets: [target('part', { part_numbers: ['100006'] })],
    }));
    check('V low confidence -> not applied', rLow.applied === false);

    const rClarify = _applyClassifiedViewportIntentToToolCalls('show the thing', [], vi({
        intent_kind: 'highlight', needs_clarification: true,
        targets: [target('part', { part_numbers: ['100006'] })],
    }));
    check('V needs_clarification -> not applied', rClarify.applied === false);

    const rRpm = _applyClassifiedViewportIntentToToolCalls('show the pin joint in motion at 2 rpm', [], vi({
        intent_kind: 'highlight_motion',
        targets: [target('motion_group', { motion_group_id: 'pin_bore_fai_affected' })],
        motion: { requested: true, speed: 'explicit', rpm: 2 },
    }));
    const playRpm = actionsOf(rRpm).find(x => x.type === 'play_motion');
    check('V explicit rpm clamped to range min', playRpm && playRpm.rpm === 10, JSON.stringify(playRpm));
}

// Classifier motion.requested keeps playback that regex would have stripped
{
    const calls = [{ name: 'ui_actions', args: { workspace: 'assembly', actions: [
        { type: 'play_motion', motion_id: 'engine4cyl_crank_cycle', rpm: 40, loop: true },
    ] } }];
    const kept = _stripUnrequestedMotionPlayback(calls, 'show the joint working', {
        motion: { requested: true, speed: null, rpm: null },
    });
    check('S classifier motion.requested preserves playback',
        kept.length === 1 && kept[0].args.actions.some(a => a.type === 'play_motion'));
    const skillKept = _stripUnrequestedMotionPlayback(calls, 'show it', null, {
        requested_effects: ['highlight_parts', 'play_motion'],
    });
    check('S resolved workflow motion preserves playback for explicit pronoun command',
        skillKept.length === 1 && skillKept[0].args.actions.some(a => a.type === 'play_motion'));
    const skillQuestion = _stripUnrequestedMotionPlayback(calls, 'what is it?', null, {
        requested_effects: ['highlight_parts', 'play_motion'],
    });
    check('S resolved workflow motion cannot bypass raw question veto',
        !(skillQuestion[0] && skillQuestion[0].args.actions.some(a => a.type === 'play_motion')));
    const stripped = _stripUnrequestedMotionPlayback(calls, 'show the pin joint', null);
    check('S unrequested playback still stripped without classifier',
        !(stripped[0] && stripped[0].args.actions.some(a => a.type === 'play_motion')));
}

// 10. Explanation questions NEVER execute, even when the classifier misfires
// with high confidence -- the deterministic action-verb gate is the
// authorization, not the classification.
{
    const misfire = () => vi({
        intent_kind: 'highlight_motion',
        targets: [target('motion_group', { motion_group_id: 'pin_bore_fai_affected', label: 'affected motion' })],
        motion: { requested: true, speed: 'slow', rpm: null },
        confidence: 0.95,
    });
    const r1 = _applyClassifiedViewportIntentToToolCalls(
        'what is the impact on the assembly of the failed dimension in the fai table?', [], misfire());
    check('10 FAI impact question -> not applied', r1.applied === false);
    const r2 = _applyClassifiedViewportIntentToToolCalls('what is the affected motion?', [], misfire());
    check('10 "what is the affected motion?" -> not applied', r2.applied === false);
    const r3 = _applyClassifiedViewportIntentToToolCalls('explain the assembly impact of #5', [], misfire());
    check('10 "explain the assembly impact" -> not applied', r3.applied === false);
    const r4 = _applyClassifiedViewportIntentToToolCalls('what motion will be affected?', [], misfire());
    check('10 "what motion will be affected?" -> not applied', r4.applied === false);

    // Mode-independent suppression: an interrogative FAI-subject turn on the
    // ASSEMBLY tab is still explanation-only.
    const savedTab = state.activeTab;
    state.activeTab = 'assembly';
    check('10 assembly-tab explanation question suppresses implicit viewport',
        _shouldSuppressImplicitFaiViewportActions('what is the affected motion?') === true);
    check('10 assembly-tab affected-motion wording suppresses implicit viewport',
        _shouldSuppressImplicitFaiViewportActions('what motion will be affected?') === true);
    check('10 assembly-tab action request not suppressed',
        _shouldSuppressImplicitFaiViewportActions('show the affected motion') === false);
    state.activeTab = savedTab;

    // Model playback on the explanation turn is stripped even though the
    // noun "motion" appears in the message.
    const calls = [{ name: 'ui_actions', args: { workspace: 'assembly', actions: [
        { type: 'play_motion', motion_id: 'engine4cyl_crank_cycle', rpm: 40, loop: true },
    ] } }];
    const kept = _stripUnrequestedMotionPlayback(calls, 'what is the affected motion?', null);
    check('10 model playback stripped on noun-only motion question',
        !kept.length || !kept[0].args.actions.some(a => a.type === 'play_motion'),
        JSON.stringify(kept));
    const kept2 = _stripUnrequestedMotionPlayback(calls, 'what motion will be affected?', null);
    check('10 model playback stripped on affected-motion wording',
        !kept2.length || !kept2[0].args.actions.some(a => a.type === 'play_motion'),
        JSON.stringify(kept2));

    const actionClaim = 'Highlighted the pin bore affected motion group showing the piston reciprocating mechanism.';
    const honest = _suppressedFaiViewportHonestyResponse('what motion will be affected?', actionClaim);
    check('10 stripped action claim becomes prose',
        typeof honest === 'string'
            && honest.includes('The affected motion is')
            && honest.includes('I did not change the viewport'),
        honest);
}

// 11. "show/play the affected motion" -> highlight + play emitted TOGETHER,
// resolved from live group metadata (no group id or part number hardcoded
// in app code -- the linkage lives in the motion summary data).
{
    const r = _applyClassifiedViewportIntentToToolCalls('show the affected motion', [], vi({
        intent_kind: 'highlight_motion',
        targets: [target('motion_group', { motion_group_id: 'pin_bore_fai_affected', label: 'affected motion' })],
        motion: { requested: true, speed: null, rpm: null },
    }));
    const a = actionsOf(r);
    const hl = a.find(x => x.type === 'set_part_highlight');
    const play = a.find(x => x.type === 'play_motion');
    check('11 applies', r.applied === true);
    check('11 highlight and play together', !!hl && !!play, JSON.stringify(a));
    check('11 focused affected motion at 30 rpm', play && play.rpm === 30, JSON.stringify(play));

    // Classifier under-selected plain highlight: upgraded because the user
    // explicitly asked for motion, so highlight-without-playback cannot ship.
    const r2 = _applyClassifiedViewportIntentToToolCalls('show the affected motion', [], vi({
        intent_kind: 'highlight',
        targets: [target('motion_group', { motion_group_id: 'pin_bore_fai_affected', label: 'affected motion' })],
    }));
    const a2 = actionsOf(r2);
    check('11 highlight-only misclassification upgraded to highlight+play',
        a2.some(x => x.type === 'set_part_highlight') && a2.some(x => x.type === 'play_motion'),
        JSON.stringify(a2));

    // Classifier gave a label but no ids: the affected group resolves from
    // live group metadata (its id/label/function declare the FAI linkage).
    const r3 = _applyClassifiedViewportIntentToToolCalls('show the affected motion', [], vi({
        intent_kind: 'highlight_motion',
        targets: [target('motion_group', { label: 'the affected motion' })],
        motion: { requested: true, speed: null, rpm: null },
    }));
    const a3 = actionsOf(r3);
    check('11 label-only target resolves affected group from live data',
        r3.applied === true && a3.some(x => x.type === 'set_part_highlight'
            && x.part_numbers.join() === '100004,100005,100006,100007'),
        JSON.stringify(a3));

    // Legacy fallback (classifier abstained) resolves the same request.
    const legacy = _resolveMotionGroupIntent('show the affected motion');
    check('11 legacy resolves affected group at 30 rpm',
        legacy && legacy.groupId === 'pin_bore_fai_affected' && legacy.rpm === 30
        && legacy.partNumbers.join() === '100004,100005,100006,100007',
        JSON.stringify(legacy));
    const legacyPlay = _resolveMotionGroupIntent('play the affected motion');
    check('11 legacy resolves "play the affected motion"',
        legacyPlay && legacyPlay.groupId === 'pin_bore_fai_affected',
        JSON.stringify(legacyPlay));
    const explain = _resolveMotionGroupIntent('explain the affected motion');
    check('11 "explain the affected motion" stays prose-only', explain === null, JSON.stringify(explain));
}

// 12. Execution honesty: when playback did not actually start the status
// line says so; when it did, it confirms -- never the reverse.
{
    const summary = {
        kind: 'highlight_motion', labels: [],
        partNumbers: ['100004', '100005', '100006', '100007'],
        rpm: 30, motionName: 'Crank cycle', groupLabel: 'Pin bore affected',
    };
    const savedPlaying = state.motionPlaying;
    const savedPkgMode = state.motionPkgMode;
    const savedRpm = state.motionRpm;
    const savedAgent = state.partExplorerAgentParts;
    state.partExplorerAgentParts = new Set(summary.partNumbers);
    state.motionPlaying = false;
    state.motionPkgMode = false;
    const failLine = _viewportExecutionStatusLine(summary);
    check('12 failed playback reported honestly',
        typeof failLine === 'string' && failLine.includes('did not start'), failLine);
    state.motionPlaying = true;
    state.motionPkgMode = true;
    state.motionRpm = 30;
    const okLine = _viewportExecutionStatusLine(summary);
    check('12 successful playback confirmed',
        typeof okLine === 'string' && okLine.indexOf('Showing Pin bore affected at 30 RPM') === 0, okLine);
    state.motionPlaying = savedPlaying;
    state.motionPkgMode = savedPkgMode;
    state.motionRpm = savedRpm;
    state.partExplorerAgentParts = savedAgent;
}

// 13. "bring the crankshaft" while the affected motion runs: adds the part
// to the visible highlighted set and never stops playback.
{
    const savedAgent = state.partExplorerAgentParts;
    const savedPlaying = state.motionPlaying;
    state.partExplorerAgentParts = new Set(['100004', '100005', '100006', '100007']);
    state.motionPlaying = true;
    const modelCalls = [{ name: 'ui_actions', args: { workspace: 'assembly', actions: [
        { type: 'stop_motion' },
    ] } }];
    const r = _applyClassifiedViewportIntentToToolCalls('bring the crankshaft', modelCalls, vi({
        intent_kind: 'show',
        targets: [target('part', { part_numbers: ['100003'], label: 'crankshaft' })],
    }));
    const a = actionsOf(r);
    const all = allUiActionsOf(r);
    check('13 applies during motion', r.applied === true);
    check('13 adds crankshaft to highlight set',
        a.some(x => x.type === 'set_part_highlight' && x.mode === 'add' && x.part_numbers.join() === '100003'),
        JSON.stringify(a));
    check('13 no stop/pause motion survives',
        !all.some(x => x.type === 'stop_motion' || x.type === 'pause_motion'), JSON.stringify(all));
    state.partExplorerAgentParts = savedAgent;
    state.motionPlaying = savedPlaying;
}

console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
