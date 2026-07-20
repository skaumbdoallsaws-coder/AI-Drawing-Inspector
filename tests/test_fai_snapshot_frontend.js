const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'static', 'index.html'), 'utf8');
let passed = 0;

function check(name, condition) {
  if (!condition) throw new Error(`FAIL ${name}`);
  passed += 1;
  process.stdout.write(`PASS ${name}\n`);
}

check('table and row revisions live in shared application state',
  html.includes('faiTableRevision: 0') && html.includes('faiRowRevisions: {}'));
check('measured input commits on input instead of blur only',
  html.includes("input.addEventListener('input', (e) => {")
    && html.includes("_commitFaiInputValue(c, 'measured', e.target.value)"));
check('focused FAI input becomes the selected characteristic',
  html.includes("input.addEventListener('focus', () => _faiSelectCharacteristic(c.key))"));
check('send flushes table editors before request construction',
  html.indexOf('_flushPendingFaiEdits();', html.indexOf('async function handleAgentSend()'))
    < html.indexOf('const inspCtx = buildInspectionContext();', html.indexOf('async function handleAgentSend()')));
check('inspection attachment carries one immutable FAI snapshot',
  html.includes('att.inspection.fai_snapshot = faiSnapshot')
    && html.includes('att.inspection.fai_characteristics = faiSnapshot.rows'));
check('snapshot contains selection revisions changes and new failures',
  ['table_revision', 'previous_sage_revision', 'selected_characteristic_id',
    'newly_failed_characteristic_ids', 'changed_since_last_response',
    'previous_target_characteristic_ids'].every(token => html.includes(token)));
check('successful Sage response acknowledges only the sent snapshot',
  html.includes('_acknowledgeFaiSnapshot(sentFaiSnapshot, data)'));
check('stale answers disclose their table revision',
  html.includes('The FAI table changed while this answer was generated'));

process.stdout.write(`${passed} passed, 0 failed\n`);
