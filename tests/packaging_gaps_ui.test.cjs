// Packaging UI helpers for the 2026-11-07 gaps: key mode, added masses, weighed cartons, contents basis,
// movement results, quote provenance and the reasons quoting is blocked. Pure functions only; no DOM, no network.
const assert = require('node:assert/strict');
const { test, before } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'static/packaging.js'), 'utf8');
let ui;

before(async () => {
  ui = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
});

// A stand-in for a form: named fields are { value } (or { checked } for checkboxes); missing names read as absent.
const form = fields => ({ elements: { namedItem: name => (name in fields
  ? (typeof fields[name] === 'object' ? fields[name] : { value: fields[name] }) : null) } });

test('contents keep a basis only once classified, and basis and evidence go together', () => {
  assert.deepEqual(ui.readContents(form({ contents: 'unconfirmed', contents_basis: 'test_assumption', contents_evidence: 'TEST' })),
    { contents: 'unconfirmed', contents_basis: '', contents_evidence: '' });
  assert.throws(() => ui.readContents(form({ contents: 'ordinary_nonhazardous', contents_basis: 'test_assumption', contents_evidence: ' ' })), /together/);
  assert.throws(() => ui.readContents(form({ contents: 'ordinary_nonhazardous', contents_basis: '', contents_evidence: 'TEST note' })), /together/);
  assert.deepEqual(ui.readContents(form({ contents: 'magnetized_material', contents_basis: 'product_declaration', contents_evidence: 'TEST supplier sheet' })),
    { contents: 'magnetized_material', contents_basis: 'product_declaration', contents_evidence: 'TEST supplier sheet' });
  // Without the basis fields (an older server) an ordinary declaration still reads.
  assert.deepEqual(ui.readContents(form({ contents: 'ordinary_nonhazardous' })),
    { contents: 'ordinary_nonhazardous', contents_basis: '', contents_evidence: '' });
  // Unset fields are left out as the server stores them, so an unchanged Apply is not an edit.
  assert.deepEqual(ui.compactConstraints({ contents: 'unconfirmed', contents_basis: '', contents_evidence: '', restraint: null, cushion: null }),
    { contents: 'unconfirmed' });
  assert.ok(ui.CONTENTS_OPTIONS.some(([value]) => value === 'magnetized_material'));
  assert.match(ui.CONTENTS_NOTICE, /never carrier acceptance/);
  assert.match(ui.CONTENTS_NOTICE, /cannot be quoted with a key recorded as production/);
  assert.match(ui.CONTENTS_NOTICE, /Only you can set or change the contents/);
});

test('a contents change the server refuses is resent only with the user\'s confirmation', async () => {
  const refused = Object.assign(new Error('This change sets the contents to Ordinary, non-hazardous; they are now Not confirmed.'),
    { code: 'contents_confirmation_required' });
  const calls = [], asked = [];
  const send = async confirmed => { calls.push(confirmed); if (!confirmed) throw refused; return 'saved'; };
  assert.equal(await ui.sendWithContentsConfirmation(send, message => { asked.push(message); return true; }), 'saved');
  assert.deepEqual(calls, [false, true]);
  assert.match(asked[0], /sets the contents to Ordinary, non-hazardous/);
  assert.match(asked[0], /Confirm this contents classification as your own\? Cancel leaves the change unsaved/);
  calls.length = 0;
  await assert.rejects(ui.sendWithContentsConfirmation(send, () => false), /not confirmed/);
  assert.deepEqual(calls, [false]);  // Cancelled: never resent.
  assert.equal(await ui.sendWithContentsConfirmation(async () => 'ok', () => assert.fail('asked')), 'ok');
  const other = Object.assign(new Error('The document changed.'), { code: 'revision_conflict' });
  await assert.rejects(ui.sendWithContentsConfirmation(async () => { throw other; }, () => assert.fail('asked')), /document changed/);
});

test('a movement requirement needs its reason; blank means none', () => {
  assert.equal(ui.readRestraint(form({ restraint_max: '', restraint_evidence: '' })), null);
  assert.equal(ui.readRestraint(form({})), null);
  assert.throws(() => ui.readRestraint(form({ restraint_max: '', restraint_evidence: 'TEST' })), /largest allowed clearance/);
  assert.throws(() => ui.readRestraint(form({ restraint_max: '2', restraint_evidence: '' })), /why/);
  assert.throws(() => ui.readRestraint(form({ restraint_max: '51', restraint_evidence: 'TEST' })), /between 0 and 50/);
  assert.deepEqual(ui.readRestraint(form({ restraint_max: '2', restraint_separate: { checked: false }, restraint_evidence: 'TEST spec' })),
    { max_travel_m: 0.002, separate_products: false, evidence: 'TEST spec' });
  assert.equal(ui.readRestraint(form({ restraint_max: '0', restraint_separate: { checked: true }, restraint_evidence: 'TEST' })).separate_products, true);
});

test('added masses keep the server field order, and unknown items keep no mass', () => {
  const items = ui.readMassItems([
    { id: 'magnets', name: ' TEST magnets ', basis: 'unknown', mass: '12', evidence: '' },
    { id: 'glue', name: 'TEST adhesive', basis: 'estimate', mass: '0.004', evidence: 'TEST bead length x density' }]);
  assert.equal(JSON.stringify(items), JSON.stringify([
    { id: 'magnets', name: 'TEST magnets', mass_kg: null, basis: 'unknown', evidence: '' },
    { id: 'glue', name: 'TEST adhesive', mass_kg: 0.004, basis: 'estimate', evidence: 'TEST bead length x density' }]));
  assert.deepEqual(ui.readMassItems([]), []);
  assert.throws(() => ui.readMassItems([{ id: 'a', name: '', basis: 'unknown' }]), /Name each/);
  assert.throws(() => ui.readMassItems([{ id: 'a', name: 'TEST', basis: 'user_measured', mass: '', evidence: 'TEST scale' }]), /Enter the mass/);
  assert.throws(() => ui.readMassItems([{ id: 'a', name: 'TEST', basis: 'user_measured', mass: '0.01', evidence: ' ' }]), /source/);
  assert.throws(() => ui.readMassItems(Array.from({ length: 13 }, (_, i) => ({ id: `m${i}`, name: 'TEST', basis: 'unknown' }))), /at most 12/);
});

test('a weighed carton needs its weighing record, and never one without the other', () => {
  assert.equal(ui.readWeighed(form({ measured_gross: '', measured_gross_evidence: '' })), null);
  assert.equal(ui.readWeighed(form({})), null);
  assert.throws(() => ui.readWeighed(form({ measured_gross: '2.9', measured_gross_evidence: '' })), /together/);
  assert.throws(() => ui.readWeighed(form({ measured_gross: '', measured_gross_evidence: 'TEST scale' })), /together/);
  assert.throws(() => ui.readWeighed(form({ measured_gross: '0', measured_gross_evidence: 'TEST scale' })), /more than 0/);
  assert.deepEqual(ui.readWeighed(form({ measured_gross: '2.93', measured_gross_evidence: 'TEST bench scale' })),
    { measured_gross_kg: 2.93, measured_gross_evidence: 'TEST bench scale' });
});

test('the key mode line never infers a mode and says a mismatch cannot undo the first request', () => {
  assert.equal(ui.accountModeText({ configured: false }), null);
  const unrecorded = ui.accountModeText({ configured: true, account_alias: 'EasyPost Test', declared_mode: null, secure_store_enabled: true });
  assert.equal(unrecorded.level, 'warning');
  assert.match(unrecorded.text, /not recorded/);
  assert.match(unrecorded.text, /alias is only a label/);
  assert.match(unrecorded.text, /under Carrier account/);
  assert.doesNotMatch(unrecorded.text, /Recorded as/);
  const recorded = ui.accountModeText({ configured: true, declared_mode: 'test', observed_mode: null });
  assert.match(recorded.text, /Recorded as a test key, from your check\. EasyPost has not answered/);
  assert.match(recorded.text, /after the first request has been sent/);
  const mismatch = ui.accountModeText({ configured: true, declared_mode: 'test', observed_mode: 'production' });
  assert.equal(mismatch.level, 'error');
  assert.match(mismatch.text, /already sent and cannot be undone/);
  assert.equal(ui.accountModeText({ configured: true, declared_mode: 'production', observed_mode: 'test', mode_mismatch: true }).level, 'error');
});

const ready = { design: { constraints: { contents: 'ordinary_nonhazardous' } }, assessment: { rate_ready: true, findings: [] } };

test('quoting is blocked without a recorded mode, after a mismatch, for unsupported contents and for test assumptions on production', () => {
  const testKey = { configured: true, declared_mode: 'test' }, production = { configured: true, declared_mode: 'production' };
  assert.equal(ui.quoteBlock(testKey, null).code, 'unsaved');
  assert.equal(ui.quoteBlock({ configured: false }, ready).code, 'not_configured');
  assert.equal(ui.quoteBlock({ configured: true, declared_mode: null }, ready).code, 'mode_unrecorded');
  assert.equal(ui.quoteBlock({ ...testKey, observed_mode: 'production' }, ready).code, 'mode_mismatch');
  assert.equal(ui.quoteBlock(testKey, ready), null);
  assert.equal(ui.quoteBlock(production, ready), null);
  const magnetized = { design: { constraints: { contents: 'magnetized_material' } }, assessment: { rate_ready: false,
    findings: [{ code: 'contents_unsupported', severity: 'error', message: 'Magnetized material is not supported for rating.' }] } };
  assert.deepEqual(ui.quoteBlock(testKey, magnetized),
    { code: 'contents_unsupported', message: 'Quotes are blocked: Magnetized material is not supported for rating.' });
  assert.equal(ui.quoteBlock(testKey, { ...ready, assessment: { rate_ready: false, findings: [] } }).code, 'validation');
  const assumed = { ...ready, design: { constraints: { contents: 'ordinary_nonhazardous', contents_basis: 'test_assumption' } } };
  assert.equal(ui.quoteBlock(testKey, assumed), null);
  assert.deepEqual(ui.quoteBlock(production, assumed), { code: 'test_assumption', message: ui.TEST_ASSUMPTION_ONLY });
});

test('movement rows give the predicted clearance and what it meets, or that a face was not checked', () => {
  const row = { item_id: 'item', directions: { '-x': { travel_m: 0, stops: ['insert'] }, '+x': { travel_m: 0.0855, stops: ['product'] },
    '-y': { travel_m: 0, stops: ['carton_wall'] }, '+y': null, '-z': { travel_m: 0.002, stops: ['insert', 'carton_wall'] } } };
  assert.deepEqual(ui.movementRows(row).map(r => [r.direction, r.clearance, r.meets]), [
    ['-X', '0.0 mm', 'packing material'], ['+X', '85.5 mm', 'another product'], ['-Y', '0.0 mm', 'carton wall'],
    ['+Y', 'not checked', '-'], ['-Z', '2.0 mm', 'packing material / carton wall'], ['+Z', 'not checked', '-']]);
  assert.match(ui.MOVEMENT_NOTICE, /bounding-box model/);
  assert.match(ui.MOVEMENT_NOTICE, /Rotation, foam compression and shipping protection remain unverified/);
  assert.doesNotMatch(ui.MOVEMENT_NOTICE + source, /cannot move/);
});

test('each quote shows its weight basis, the contents at quote time and the key mode', () => {
  const quote = {
    weight_basis: { status: 'estimated', summary: 'Estimate: sum of component masses; excludes 1 item(s) of unknown mass: TEST magnets',
      packages: [{ package_id: 'box', basis: 'sum_of_components', rated_kg: 2.782, estimated_kg: 2.782 },
        { package_id: 'box2', basis: 'weighed_packed_carton', rated_kg: 2.9, estimated_kg: 2.93 }] },
    contents: { label: 'Ordinary, non-hazardous', basis: 'test_assumption',
      basis_label: 'test assumption (not a declaration about a real product; results are not shipping clearance)',
      notice: 'No contents or hazardous-materials information was sent to the carrier.' },
    account_mode: { declared: 'test', observed: 'test' } };
  const lines = ui.quoteProvenance(quote);
  assert.deepEqual(lines.map(line => line.level), ['warning', 'warning', 'metadata']);
  assert.equal(lines[0].text, 'Weight basis: Estimate: sum of component masses; excludes 1 item(s) of unknown mass: TEST magnets.');
  assert.match(lines[1].text, /^Contents at quote time: Ordinary, non-hazardous, test assumption/);
  assert.match(lines[1].text, /No contents or hazardous-materials information was sent/);
  assert.equal(lines[2].text, 'Key mode: recorded test; EasyPost answered test.');
  assert.deepEqual(ui.quoteProvenance({}).map(line => line.text), ['Weight basis: not recorded with this quote.']);
  assert.equal(ui.quoteProvenance({ account_mode: { declared: 'test', observed: 'production' } })[1].level, 'warning');
  assert.match(ui.parcelWeightText(quote, 'box'), /sum of component masses \(estimate\)/);
  assert.match(ui.parcelWeightText(quote, 'box2'), /from the weighed packed carton; component estimate/);
  assert.equal(ui.parcelWeightText(quote, 'missing'), null);
});
