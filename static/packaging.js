export const ORIENTATION_ORDERS = [[0, 1, 2], [1, 0, 2], [1, 2, 0], [2, 1, 0], [2, 0, 1], [0, 2, 1]];
export const ORIENTATION_LABELS = ['XYZ', 'YXZ', 'YZX', 'ZYX', 'ZXY', 'XZY'];
export const clone = value => structuredClone(value);
export const mmToM = value => Number(value) / 1000;
export const mToMm = value => Number((value * 1000).toFixed(6));

// Odd permutations need a sign reversal to remain rigid rotations, not reflections.
export function orientationRows(index) {
  const order = ORIENTATION_ORDERS[index];
  if (!order) throw new Error('Unsupported orientation.');
  const inversions = order.reduce((n, a, i) => n + order.slice(i + 1).filter(b => a > b).length, 0);
  return order.map((source, axis) => [0, 1, 2].map(k => k === source ? (axis === 0 && inversions % 2 ? -1 : 1) : 0));
}

export function placementCenter(dimensions, placement) {
  return ORIENTATION_ORDERS[placement.orientation].map((axis, i) => placement.position_m[i] + dimensions[axis] / 2);
}

export function emptyDesign() {
  return { name: 'Untitled package', product: null, quantity: 1,
    constraints: { clearance_m: .02, gap_m: .01, allowed_orientations: [0], contents: 'unconfirmed' }, packages: [] };
}

export function defaultCarton() {
  return { name: 'Carton', inner_m: [.4, .3, .25], outer_m: [.41, .31, .26], tare_kg: null,
    tare_evidence: '', max_payload_kg: null, cost_usd: null };
}

export class DraftDocument {
  constructor() { this.reset(); }
  reset() { this.document = null; this.design = emptyDesign(); this.past = []; this.future = []; }
  accept(document) {
    this.document = clone(document); this.design = clone(document.design); this.past = []; this.future = [];
  }
  get dirty() { return JSON.stringify(this.design) !== JSON.stringify(this.document?.design ?? emptyDesign()); }
  edit(change) {
    const next = clone(this.design);
    change(next);
    if (JSON.stringify(next) === JSON.stringify(this.design)) return false;
    this.past = [...this.past, clone(this.design)].slice(-30);
    this.future = []; this.design = next;
    return true;
  }
  undo() {
    if (!this.past.length) return false;
    this.future.push(clone(this.design)); this.design = this.past.pop(); return true;
  }
  redo() {
    if (!this.future.length) return false;
    this.past.push(clone(this.design)); this.design = this.future.pop(); return true;
  }
}

export function errorMessage(body, status) {
  if (body?.error?.message) return String(body.error.message);
  if (typeof body?.detail === 'string') return body.detail;
  if (Array.isArray(body?.detail)) return body.detail.map(x => `${(x.loc || []).join('.')}: ${x.msg}`).join('; ');
  return `Packaging request failed (HTTP ${status}).`;
}

export async function request(path, { method = 'GET', body, raw = false, responseType = 'json' } = {}) {
  const headers = { 'X-InspectorPro-Request': 'packaging' };
  if (body !== undefined) headers['Content-Type'] = raw ? 'model/gltf-binary' : 'application/json';
  const response = await fetch(`/api/packaging${path}`, { method, headers, credentials: 'same-origin', cache: 'no-store',
    body: body === undefined ? undefined : raw ? body : JSON.stringify(body) });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const error = new Error(errorMessage(payload, response.status));
    error.status = response.status; error.code = payload?.error?.code;
    throw error;
  }
  return responseType === 'blob' ? response.blob() : response.json();
}

export function quoteFreshness(quote, revision, dirty, scenarioMatches) {
  if (!quote) return 'No quotes';
  if (dirty || quote.stale || quote.revision !== revision) return 'Stale: package changed';
  if (!scenarioMatches) return 'Stale: address scenario changed or not loaded';
  return 'Current saved revision';
}

export function rateAccountLabel(rate) {
  return `Account: ${String(rate.account_id ?? '').trim() || 'not provided'}`;
}

const $ = id => document.getElementById(id);
const uid = prefix => `${prefix}_${crypto.randomUUID().replaceAll('-', '')}`;
const numberText = (value, digits = 3) => value == null ? 'Unknown' : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
const massText = value => value == null ? 'Unknown' : `${numberText(value)} kg`;
const dimensionText = dims => dims.map(mToMm).join(' x ') + ' mm';

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function icon(name) {
  const span = element('span', null, 'icon');
  span.style.setProperty('--icon', `url('/static/assets/facility-layout-ribbon-icons/svg/${name}.svg')`);
  span.setAttribute('aria-hidden', 'true');
  return span;
}

function button(label, handler, { symbol, compact = false, primary = false, disabled = false, danger = false } = {}) {
  const node = element('button', null, [compact ? 'icon-button' : '', primary ? 'primary' : '', danger ? 'danger' : ''].join(' '));
  node.type = 'button'; node.title = label; node.setAttribute('aria-label', label); node.disabled = disabled;
  if (symbol) node.append(icon(symbol));
  if (!compact) node.append(document.createTextNode(label));
  node.addEventListener('click', () => invoke(handler));
  return node;
}

function field(parent, label, name, value = '', options = {}) {
  const wrapper = element('label', label);
  const input = element(options.options ? 'select' : options.multiline ? 'textarea' : 'input');
  input.name = name;
  if (options.options) for (const [val, text] of options.options) {
    const option = element('option', text); option.value = val; input.append(option);
  }
  else if (!options.multiline) input.type = options.type || 'text';
  for (const key of ['min', 'max', 'step', 'maxLength', 'required', 'readOnly', 'pattern', 'placeholder', 'accept']) {
    if (options[key] !== undefined) input[key] = options[key];
  }
  if (input.type === 'number') { input.step = options.step ?? 'any'; input.inputMode = 'decimal'; }
  if (input.type !== 'file') input.value = value ?? '';
  input.autocomplete = options.autocomplete || 'off';
  wrapper.append(input); parent.append(wrapper);
  return input;
}

function vector(parent, title, prefix, values, { position = false, readOnly = false } = {}) {
  const group = element('fieldset'); group.append(element('legend', title));
  const row = element('div', null, 'vector');
  ['X', 'Y', 'Z'].forEach((axis, i) => field(row, `${axis} (mm)`, `${prefix}_${i}`, mToMm(values[i]),
    { type: 'number', min: position ? 0 : .000001, max: position ? 10000000 : 5000, required: true, readOnly }));
  group.append(row); parent.append(group);
}

function checkbox(parent, label, checked, handler) {
  const wrapper = element('label', null, 'check'); const input = element('input'); input.type = 'checkbox'; input.checked = checked;
  input.addEventListener('change', () => handler(input.checked)); wrapper.append(input, document.createTextNode(label)); parent.append(wrapper);
  return input;
}

const textValue = (form, name) => String(form.elements.namedItem(name)?.value ?? '').trim();
function numeric(form, name, optional = false) {
  const raw = textValue(form, name);
  if (optional && raw === '') return null;
  const value = Number(raw);
  if (raw === '' || !Number.isFinite(value)) throw new Error(`Enter a valid value for ${name.replaceAll('_', ' ')}.`);
  return value;
}
const readVector = (form, prefix) => [0, 1, 2].map(i => mmToM(numeric(form, `${prefix}_${i}`)));

const state = {
  draft: new DraftDocument(), busy: false, formDirty: false, editorForm: null,
  editor: 'product', review: 'validation', packageId: null, componentId: null, scene: null,
  alternatives: [defaultCarton()], alternativeIndex: 0, maxPackages: 3, candidates: null, candidateRevision: null, candidateConfig: null,
  provider: null, providerError: '', quotes: [], quoteIndex: 0, quoteScenario: null, quoteError: '',
  addresses: { origin: blankAddress(), destinations: [blankAddress()] }, quoteForm: null,
  section: false, exploded: false, mutationReceipt: null, lastDirtySignal: null
};

function blankAddress() { return { name: '', street1: '', street2: '', city: '', state: '', zip: '', country: 'US', residential: false }; }
const selectedPackage = () => state.draft.design.packages.find(p => p.id === state.packageId);
const docPath = () => `/documents/${encodeURIComponent(state.draft.document.id)}`;
const hasDraft = () => state.draft.dirty || state.formDirty;
const hasAddressInputs = () => JSON.stringify(captureAddresses()) !== JSON.stringify({ origin: blankAddress(), destinations: [blankAddress()] });
const hasNavigationChanges = () => hasDraft() || hasAddressInputs();

function notify(message, error = false) {
  $('message').textContent = message; $('message').className = `message${error ? ' error' : ''}`; $('message').hidden = !message;
  $('message').setAttribute('role', error ? 'alert' : 'status');
}

async function invoke(action) {
  if (state.busy) return;
  try { await action(); }
  catch (error) {
    const suffix = error.code === 'revision_conflict' ? ' Your draft is retained. Reload the document to reconcile with the server.' : '';
    notify(error.message + suffix, true);
  }
}

async function working(message, action) {
  state.busy = true; notify(message); updateHeader();
  const disabled = [...document.querySelectorAll('input, select, textarea, button')].map(node => [node, node.disabled]);
  disabled.forEach(([node]) => { node.disabled = true; });
  $('workspace').setAttribute('aria-busy', 'true');
  try { return await action(); }
  finally {
    state.busy = false; disabled.forEach(([node, wasDisabled]) => { if (node.isConnected) node.disabled = wasDisabled; });
    $('workspace').setAttribute('aria-busy', 'false'); updateHeader(); updateFreshness();
  }
}

function edit(change) { state.draft.edit(change); }

function createForm(onApply, label = 'Apply changes') {
  const form = element('form', null, 'form-grid');
  const apply = () => {
    for (const input of form.querySelectorAll('input[required], textarea[required]')) {
      if (input.type === 'text' || input.tagName === 'TEXTAREA') {
        input.setCustomValidity(input.value.trim() ? '' : 'Enter a value, not only spaces.');
        input.addEventListener('input', () => input.setCustomValidity(''), { once: true });
      }
    }
    if (!form.reportValidity()) throw new Error('Check the highlighted fields.');
    onApply(form); state.formDirty = false; return true;
  };
  state.editorForm = { form, apply };
  form.addEventListener('input', () => { state.formDirty = true; updateHeader(); updateFreshness(); });
  form.addEventListener('change', () => { state.formDirty = true; updateHeader(); updateFreshness(); });
  form.addEventListener('submit', event => { event.preventDefault(); invoke(() => { apply(); render(); notify('Changes applied to draft.'); }); });
  const actions = element('div', null, 'actions');
  const submit = button(label, () => form.requestSubmit(), { primary: true });
  actions.append(submit, button('Reset fields', () => { state.formDirty = false; renderEditor(); updateHeader(); updateFreshness(); }));
  return { form, actions };
}

function flushEditor() {
  if (state.formDirty && state.editorForm) state.editorForm.apply();
}

function setEditor(tab) { flushEditor(); state.editor = tab; render(); }

function updateHeader() {
  const draft = state.draft, doc = draft.document;
  $('document-status').textContent = `${doc ? `Revision ${doc.revision}` : 'New document'} | ${state.busy ? 'Working...' : hasDraft() ? 'Unsaved changes' : doc ? 'Saved' : 'Not saved'}`;
  const actions = $('document-actions'); actions.replaceChildren();
  actions.append(
    button('New', newDocument), button('Open', openDocuments),
    button('Save', saveDocument, { symbol: 'floppy-disk', primary: true, disabled: state.busy || (!!doc && !hasDraft()) }),
    button('Undo', () => historyAction('undo'), { symbol: 'arrow-u-up-left', compact: true, disabled: !state.formDirty && !draft.past.length && !doc?.can_undo }),
    button('Redo', () => historyAction('redo'), { symbol: 'arrow-u-up-right', compact: true, disabled: state.formDirty || (!draft.future.length && (draft.dirty || !doc?.can_redo)) }),
    button('Reload saved document', reloadDocument, { symbol: 'arrow-clockwise', compact: true, disabled: !doc }),
    button('Download PDF', downloadPDF, { symbol: 'file-export', compact: true, disabled: !doc || hasDraft() })
  );
  if (state.busy) for (const node of actions.querySelectorAll('button')) node.disabled = true;
  $('document-name').disabled = state.busy;
  const provider = state.provider;
  $('provider-status').textContent = state.providerError || (provider ? `${provider.provider}: ${provider.configured ? 'configured | quote only' : 'not configured'}` : 'Checking rate provider...');
  const dirtySignal = JSON.stringify({ dirty: hasNavigationChanges() || state.busy, documentId: doc?.id || null, revision: doc?.revision ?? null });
  if (dirtySignal !== state.lastDirtySignal) {
    state.lastDirtySignal = dirtySignal;
    if (window.parent !== window) window.parent.postMessage({ type: 'inspectorpro:packaging-dirty', ...JSON.parse(dirtySignal) }, window.location.origin);
  }
}

function renderTabs() {
  for (const [id, entries, selected, handler] of [
    ['editor-tabs', [['product', 'Product'], ['carton', 'Carton'], ['contents', 'Contents'], ['arrange', 'Arrange']], state.editor, setEditor],
    ['review-tabs', [['validation', 'Validation'], ['rates', 'Rates']], state.review, tab => { state.review = tab; renderTabs(); }]
  ]) {
    const nav = $(id); nav.replaceChildren(); nav.setAttribute('role', 'tablist');
    entries.forEach(([value, label]) => {
      const b = button(label, () => handler(value)); b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', String(value === selected));
      b.setAttribute('aria-controls', id === 'editor-tabs' ? 'editor' : `${value}-panel`);
      b.tabIndex = value === selected ? 0 : -1;
      b.addEventListener('keydown', event => {
        if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const i = entries.findIndex(([v]) => v === value);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? entries.length - 1 : (i + (event.key === 'ArrowRight' ? 1 : -1) + entries.length) % entries.length;
        invoke(() => { handler(entries[next][0]); $(id).children[next].focus(); });
      });
      nav.append(b);
    });
  }
  $('validation-panel').hidden = state.review !== 'validation'; $('rates-panel').hidden = state.review !== 'rates';
}

function render() {
  if (!selectedPackage()) state.packageId = state.draft.design.packages[0]?.id ?? null;
  $('document-name').value = state.draft.design.name;
  updateHeader(); renderTabs(); renderPackages(); renderEditor(); renderValidation(); renderQuoteResults();
  refreshScene();
}

function renderPackages() {
  const select = $('package-select'); select.replaceChildren();
  if (!state.draft.design.packages.length) { const opt = element('option', 'No carton'); opt.value = ''; select.append(opt); }
  state.draft.design.packages.forEach((p, index) => {
    const opt = element('option', `${index + 1}. ${p.carton.name} (${p.placements.length} products)`); opt.value = p.id; select.append(opt);
  });
  select.value = state.packageId || ''; select.disabled = !state.draft.design.packages.length;
  $('package-actions').replaceChildren(
    button('Add carton', () => {
      flushEditor(); const id = uid('box');
      edit(d => d.packages.push({ id, carton: defaultCarton(), placements: [], inserts: [], allowance_kg: null, allowance_evidence: '' }));
      state.packageId = id; state.editor = 'carton'; render(); state.scene?.fit();
    }, { symbol: 'cube', disabled: state.draft.design.packages.length >= 10 }),
    button('Remove selected package', () => {
      if (!confirm('Remove this carton and all its products and pads?')) return;
      flushEditor(); edit(d => { d.packages = d.packages.filter(p => p.id !== state.packageId); }); state.componentId = null; render();
    }, { symbol: 'trash', compact: true, danger: true, disabled: !selectedPackage() })
  );
}

function renderEditor() {
  state.editorForm = null; state.formDirty = false;
  const host = $('editor'); host.replaceChildren();
  ({ product: renderProduct, carton: renderCarton, contents: renderContents, arrange: renderArrange })[state.editor](host);
}

function section(host, heading) {
  const group = element('section', null, 'editor-section'); group.append(element('h2', heading)); host.append(group); return group;
}

function renderProduct(host) {
  const product = state.draft.design.product;
  const source = section(host, 'Product source');
  const upload = element('form', null, 'form-grid');
  const file = field(upload, 'Source GLB', 'source_file', '', { type: 'file', accept: '.glb,model/gltf-binary', required: true });
  field(upload, 'Stored coordinate units', 'source_units', '1', { options: [['1', 'Meters'], ['0.001', 'Millimeters'], ['0.0254', 'Inches']] });
  upload.append(button('Import GLB', () => {
    if (!upload.reportValidity()) return;
    return importSource(file.files[0], Number(textValue(upload, 'source_units')));
  }, { symbol: 'file-export' }));
  upload.addEventListener('submit', event => event.preventDefault()); source.append(upload);
  if (product?.source_id) {
    const meta = element('div', null, 'metadata');
    meta.append(element('span', 'Imported GLB | dimensions locked'), element('code', product.source_id), element('span', 'Source revision'), element('code', product.source_revision));
    source.append(meta, button('Replace with manual geometry', () => {
      if (!confirm('Replace the imported model with editable manual bounding geometry?')) return;
      flushEditor(); edit(d => { d.product.source_id = null; d.product.source_revision = ''; }); render();
    }, { symbol: 'bounding-box' }));
  } else source.append(element('p', product ? 'Manual geometry: bounding box only.' : 'No product selected.', 'notice'));

  const group = section(host, product ? 'Product properties' : 'Manual product');
  const p = product || { name: 'Product', dimensions_m: [.1, .1, .1], mass_kg: null, mass_basis: 'unknown', mass_evidence: '', source_id: null, source_revision: '' };
  const { form, actions } = createForm(form => {
    const basis = textValue(form, 'mass_basis');
    const updated = { ...clone(p), name: textValue(form, 'product_name'),
      dimensions_m: p.source_id ? clone(p.dimensions_m) : readVector(form, 'product_dim'), mass_basis: basis,
      mass_kg: basis === 'unknown' ? null : numeric(form, 'product_mass'), mass_evidence: basis === 'unknown' ? '' : textValue(form, 'mass_evidence') };
    const allowed = [...form.querySelectorAll('[name="orientation"]:checked')].map(x => Number(x.value));
    if (!allowed.length) throw new Error('Allow at least one product orientation.');
    edit(d => {
      d.product = updated; d.quantity = numeric(form, 'quantity');
      d.constraints = { clearance_m: mmToM(numeric(form, 'clearance')), gap_m: mmToM(numeric(form, 'gap')),
        allowed_orientations: allowed, contents: textValue(form, 'contents') };
    });
  }, product ? 'Apply product' : 'Add manual product');
  field(form, 'Product name', 'product_name', p.name, { maxLength: 160, required: true });
  vector(form, 'Source dimensions', 'product_dim', p.dimensions_m, { readOnly: !!p.source_id });
  field(form, 'Total product quantity', 'quantity', state.draft.design.quantity, { type: 'number', min: 1, max: 48, step: 1, required: true });
  const basis = field(form, 'Mass basis', 'mass_basis', p.mass_basis, { options: [['unknown', 'Unknown'], ['user_measured', 'Measured'], ['estimate', 'Estimate']] });
  const mass = field(form, 'Mass per product (kg)', 'product_mass', p.mass_kg, { type: 'number', min: .000001, max: 1000 });
  const evidence = field(form, 'Mass evidence', 'mass_evidence', p.mass_evidence, { multiline: true, maxLength: 500 });
  const updateMass = () => { mass.disabled = evidence.disabled = basis.value === 'unknown'; mass.required = evidence.required = basis.value !== 'unknown'; };
  basis.addEventListener('change', updateMass); updateMass();
  form.append(element('h3', 'Packing restrictions'));
  const dims = element('div', null, 'two-cols');
  field(dims, 'Wall clearance (mm)', 'clearance', mToMm(state.draft.design.constraints.clearance_m), { type: 'number', min: 0, max: 200, required: true });
  field(dims, 'Product gap (mm)', 'gap', mToMm(state.draft.design.constraints.gap_m), { type: 'number', min: 0, max: 200, required: true }); form.append(dims);
  const orientations = element('fieldset'); orientations.append(element('legend', 'Allowed dimension orders'));
  const checks = element('div', null, 'checks');
  ORIENTATION_LABELS.forEach((label, i) => { const input = checkbox(checks, label, state.draft.design.constraints.allowed_orientations.includes(i), () => {}); input.name = 'orientation'; input.value = i; });
  orientations.append(checks); form.append(orientations);
  field(form, 'Contents declaration', 'contents', state.draft.design.constraints.contents, { options: [['unconfirmed', 'Unconfirmed'], ['ordinary_nonhazardous', 'Ordinary, non-hazardous'], ['special_handling', 'Special handling required']] });
  form.append(actions); group.append(form);
}

async function importSource(file, unit) {
  flushEditor();
  if (!file || !/\.glb$/i.test(file.name)) throw new Error('Choose a self-contained GLB file.');
  if (file.size > 24 * 1024 * 1024) throw new Error('GLB import is limited to 24 MiB.');
  if (state.draft.design.product && !confirm('Replace the product for every existing placement? Mass provenance will be reset.')) return;
  await working('Importing source geometry...', async () => {
    const meta = await request(`/sources?name=${encodeURIComponent(file.name.slice(0, 160))}&meters_per_unit=${unit}`, { method: 'POST', body: file, raw: true });
    edit(d => { d.product = { name: meta.name, dimensions_m: clone(meta.dimensions_m), mass_kg: null, mass_basis: 'unknown', mass_evidence: '', source_id: meta.id, source_revision: meta.source_revision }; });
    notify('Source imported. Product mass is unknown.');
  });
  render(); state.scene?.fit();
}

function cartonFields(form, carton) {
  field(form, 'Carton name', 'carton_name', carton.name, { required: true, maxLength: 160 });
  vector(form, 'Internal dimensions', 'inner', carton.inner_m); vector(form, 'External dimensions', 'outer', carton.outer_m);
  field(form, 'Empty carton mass (kg)', 'tare', carton.tare_kg, { type: 'number', min: 0, max: 100 });
  const evidence = field(form, 'Carton mass evidence', 'tare_evidence', carton.tare_evidence, { multiline: true, maxLength: 500 });
  const tare = form.elements.namedItem('tare'); const check = () => { evidence.required = tare.value !== ''; };
  tare.addEventListener('input', check); check();
  const row = element('div', null, 'two-cols');
  field(row, 'Payload limit (kg)', 'payload', carton.max_payload_kg, { type: 'number', min: .000001, max: 1000 });
  field(row, 'Carton cost (USD)', 'carton_cost', carton.cost_usd, { type: 'number', min: 0, max: 10000 }); form.append(row);
}

function readCarton(form) {
  const inner = readVector(form, 'inner'), outer = readVector(form, 'outer');
  if (outer.some((x, i) => x <= inner[i])) throw new Error('External dimensions must exceed internal dimensions on every axis.');
  return { name: textValue(form, 'carton_name'), inner_m: inner, outer_m: outer, tare_kg: numeric(form, 'tare', true),
    tare_evidence: textValue(form, 'tare_evidence'), max_payload_kg: numeric(form, 'payload', true), cost_usd: numeric(form, 'carton_cost', true) };
}

function renderCarton(host) {
  const p = selectedPackage();
  if (!p) { host.append(element('p', 'No carton selected.', 'notice')); return; }
  const group = section(host, 'Selected carton');
  const { form, actions } = createForm(form => {
    const carton = readCarton(form), allowance = numeric(form, 'allowance', true), evidence = textValue(form, 'allowance_evidence');
    edit(d => { const target = d.packages.find(x => x.id === p.id); target.carton = carton; target.allowance_kg = allowance; target.allowance_evidence = evidence; });
  }, 'Apply carton');
  cartonFields(form, p.carton);
  form.append(element('h3', 'Other packing materials'));
  const allowance = field(form, 'Tape / packing allowance (kg)', 'allowance', p.allowance_kg, { type: 'number', min: 0, max: 20 });
  const evidence = field(form, 'Allowance evidence (including zero)', 'allowance_evidence', p.allowance_evidence, { multiline: true, maxLength: 500 });
  const check = () => { evidence.required = allowance.value !== ''; }; allowance.addEventListener('input', check); check();
  form.append(actions); group.append(form);
}

function renderContents(host) {
  const p = selectedPackage();
  if (!p) { host.append(element('p', 'No carton selected.', 'notice')); return; }
  const group = section(host, 'Package contents');
  const actions = element('div', null, 'actions');
  actions.append(button('Add product', () => {
    flushEditor(); const id = uid('item');
    edit(d => { d.packages.find(x => x.id === p.id).placements.push({ id, position_m: [d.constraints.clearance_m, d.constraints.clearance_m, d.constraints.clearance_m], orientation: d.constraints.allowed_orientations[0] }); });
    state.componentId = id; render();
  }, { symbol: 'cube', disabled: !state.draft.design.product || p.placements.length >= 48 }),
  button('Add pad', () => {
    flushEditor(); state.componentId = 'new_pad'; render();
  }, { symbol: 'rectangle', disabled: p.inserts.length >= 32 }));
  group.append(actions);
  const list = element('div', null, 'item-list');
  [...p.placements.map((x, i) => [x, `Product ${i + 1} | ${ORIENTATION_LABELS[x.orientation]}`]), ...p.inserts.map(x => [x, x.name])].forEach(([item, name]) => {
    const b = button(name, () => { flushEditor(); state.componentId = item.id; render(); });
    b.setAttribute('aria-pressed', String(state.componentId === item.id)); list.append(b);
  });
  if (!list.children.length) list.append(element('p', 'No placed components.', 'notice')); group.append(list);
  let item = p.placements.find(x => x.id === state.componentId), isPad = false;
  if (!item) { item = p.inserts.find(x => x.id === state.componentId); isPad = true; }
  const isNew = state.componentId === 'new_pad';
  if (isNew) { isPad = true; item = { id: uid('pad'), name: 'Pad', dimensions_m: [.1, .01, .1], position_m: [0, 0, 0], material: 'Foam', density_kg_m3: 30, material_evidence: '', cost_usd: null }; }
  if (!item) return;
  const editor = section(host, isPad ? isNew ? 'New pad' : 'Pad properties' : 'Product placement');
  editor.append(element('p', 'Minimum-corner position | carton-local axes', 'notice'));
  const { form, actions: applyActions } = createForm(form => {
    const next = { ...clone(item), position_m: readVector(form, 'position') };
    if (isPad) Object.assign(next, { name: textValue(form, 'pad_name'), dimensions_m: readVector(form, 'pad_dim'), material: textValue(form, 'material'),
      density_kg_m3: numeric(form, 'density'), material_evidence: textValue(form, 'material_evidence'), cost_usd: numeric(form, 'pad_cost', true) });
    else next.orientation = numeric(form, 'item_orientation');
    const destination = textValue(form, 'target_package');
    edit(d => {
      const from = d.packages.find(x => x.id === p.id), to = d.packages.find(x => x.id === destination);
      const key = isPad ? 'inserts' : 'placements';
      if (from.id !== to.id || isNew) {
        if (to[key].length >= (isPad ? 32 : 48)) throw new Error('The target package has reached its component limit.');
      }
      from[key] = from[key].filter(x => x.id !== item.id); to[key].push(next);
    });
    state.packageId = destination; state.componentId = next.id;
  }, isNew ? 'Add pad' : 'Apply placement');
  if (isPad) {
    field(form, 'Pad name', 'pad_name', item.name, { required: true, maxLength: 160 });
    vector(form, 'Pad dimensions', 'pad_dim', item.dimensions_m);
  }
  vector(form, 'Position', 'position', item.position_m, { position: true });
  if (isPad) {
    field(form, 'Material', 'material', item.material, { required: true, maxLength: 160 });
    field(form, 'Density (kg/m3)', 'density', item.density_kg_m3, { type: 'number', min: .000001, max: 25000, required: true });
    field(form, 'Material / density evidence', 'material_evidence', item.material_evidence, { multiline: true, required: true, maxLength: 500 });
    field(form, 'Pad cost (USD)', 'pad_cost', item.cost_usd, { type: 'number', min: 0, max: 10000 });
    editor.append(element('p', `Pad mass: ${massText(item.dimensions_m.reduce((a, b) => a * b, 1) * item.density_kg_m3)}`, 'notice'));
  } else field(form, 'Orientation (dimension order)', 'item_orientation', item.orientation, { options: ORIENTATION_LABELS.map((label, i) => [String(i), label + (state.draft.design.constraints.allowed_orientations.includes(i) ? '' : ' (restricted)')]) });
  field(form, 'Package', 'target_package', p.id, { options: state.draft.design.packages.map((x, i) => [x.id, `${i + 1}. ${x.carton.name}`]) });
  if (!isNew) applyActions.append(button('Remove component', () => {
    state.formDirty = false; edit(d => { const box = d.packages.find(x => x.id === p.id); const key = isPad ? 'inserts' : 'placements'; box[key] = box[key].filter(x => x.id !== item.id); });
    state.componentId = null; render();
  }, { symbol: 'trash', danger: true }));
  form.append(applyActions); editor.append(form);
}

function renderArrange(host) {
  const group = section(host, 'Carton alternatives');
  const select = field(group, 'Alternative', 'alternative', state.alternativeIndex, { options: state.alternatives.map((c, i) => [String(i), `${i + 1}. ${c.name}`]) });
  select.addEventListener('change', () => invoke(() => { flushEditor(); state.alternativeIndex = Number(select.value); renderEditor(); updateHeader(); }));
  const toolbar = element('div', null, 'actions');
  toolbar.append(button('Add alternative', () => { flushEditor(); state.alternatives.push(defaultCarton()); state.alternativeIndex = state.alternatives.length - 1; state.candidates = null; renderEditor(); updateHeader(); }, { symbol: 'copy', disabled: state.alternatives.length >= 6 }),
    button('Use selected carton', () => { flushEditor(); state.alternatives[state.alternativeIndex] = clone(selectedPackage().carton); state.candidates = null; renderEditor(); updateHeader(); }, { symbol: 'cube', disabled: !selectedPackage() }),
    button('Remove alternative', () => { state.formDirty = false; state.alternatives.splice(state.alternativeIndex, 1); state.alternativeIndex = 0; state.candidates = null; renderEditor(); updateHeader(); }, { symbol: 'trash', compact: true, disabled: state.alternatives.length <= 1 }));
  group.append(toolbar);
  const { form, actions } = createForm(form => {
    state.alternatives[state.alternativeIndex] = readCarton(form); state.maxPackages = numeric(form, 'max_packages'); state.candidates = null;
  }, 'Apply alternative');
  cartonFields(form, state.alternatives[state.alternativeIndex]);
  field(form, 'Maximum packages', 'max_packages', state.maxPackages, { type: 'number', min: 1, max: 6, step: 1, required: true });
  form.append(actions); group.append(form);
  group.append(button('Generate candidates', generateCandidates, { symbol: 'magic-wand', primary: true, disabled: !state.draft.design.product }));
  const results = section(host, 'Candidates');
  if (!state.candidates) { results.append(element('p', 'No current candidate calculation.', 'notice')); return; }
  const stale = hasDraft() || state.candidateRevision !== state.draft.document?.revision || state.candidateConfig !== JSON.stringify([state.alternatives, state.maxPackages]);
  results.append(element('p', stale ? 'Stale: regenerate after saving changes.' : `${state.candidates.candidates.length} alternatives | ${state.candidates.algorithm} | ${state.candidates.elapsed_ms} ms`, stale ? 'warning' : 'notice'));
  if (state.candidates.truncated) results.append(element('p', 'Search reached its time limit. Results are partial.', 'warning'));
  if (!state.candidates.candidates.length) results.append(element('p', 'No feasible envelope arrangement found. Review cartons and restrictions.', 'notice'));
  state.candidates.candidates.forEach((candidate, i) => {
    const row = element('article', null, 'candidate');
    row.append(element('h3', `${i + 1}. ${candidate.design.packages[0]?.carton.name || 'Arrangement'}`),
      element('p', `${candidate.package_count} packages | ${numberText(candidate.shipping_volume_m3 * 1000)} L exterior volume`, 'notice'),
      element('p', `${candidate.assessment.findings.filter(f => f.severity === 'error').length} validation errors | packing allowance and pads require review`, 'notice'),
      button('Apply candidate', () => {
        flushEditor();
        if (!state.candidates || hasDraft() || state.candidateRevision !== state.draft.document?.revision || state.candidateConfig !== JSON.stringify([state.alternatives, state.maxPackages])) throw new Error('Save changes and regenerate candidates first.');
        if (!confirm('Replace all package arrangements, pads and allowances with this candidate? This change can be undone.')) return;
        edit(d => { d.packages = clone(candidate.design.packages); });
        state.componentId = null; state.packageId = null; state.editor = 'carton'; render(); state.scene?.fit(); notify('Candidate applied to draft. Review packing materials before saving.');
      }, { disabled: stale, primary: true }));
    results.append(row);
  });
  if (state.candidates.notice) results.append(element('p', state.candidates.notice, 'notice'));
}

async function generateCandidates() {
  flushEditor();
  if (!state.draft.document || state.draft.dirty) { render(); throw new Error('Save the document before generating candidates.'); }
  await working('Calculating carton arrangements...', async () => {
    const revision = state.draft.document.revision;
    state.candidates = await request(`${docPath()}/arrangements`, { method: 'POST', body: { expected_revision: revision, cartons: state.alternatives, max_packages: state.maxPackages } });
    state.candidateRevision = revision; state.candidateConfig = JSON.stringify([state.alternatives, state.maxPackages]); notify('Candidate calculation complete. No changes have been applied.');
  });
  render();
}

function renderValidation() {
  const host = $('validation-panel'); host.replaceChildren();
  const assessment = state.draft.document?.assessment;
  const pending = hasDraft();
  const summary = section(host, 'Mass & validation');
  if (!assessment) { summary.append(element('p', 'Not assessed. Save the document for server validation.', 'notice')); return; }
  summary.append(element('p', pending ? 'Stale assessment: unsaved changes' : `Saved revision ${state.draft.document.revision} | ${assessment.status.replaceAll('_', ' ')}`, pending ? 'warning' : 'notice'));
  const metric = element('div', null, 'metric'); metric.append(element('span', pending ? 'Last saved gross mass' : 'Total gross mass'), element('strong', massText(assessment.total_gross_kg))); summary.append(metric);
  summary.append(element('p', `${assessment.placed_quantity} / ${state.draft.document.design.quantity} products placed`, 'notice'));
  const mass = assessment.packages.find(x => x.package_id === state.packageId);
  if (mass) {
    const dl = element('dl', null, 'mass-grid');
    for (const [label, val] of [['Products', mass.product_kg], ['Pads / inserts', mass.insert_kg], ['Carton', mass.carton_kg], ['Packing allowance', mass.allowance_kg], ['Package gross', mass.gross_kg]]) dl.append(element('dt', label), element('dd', massText(val)));
    dl.append(element('dt', 'Materials cost'), element('dd', mass.materials_cost_usd == null ? 'Unknown' : `USD ${numberText(mass.materials_cost_usd, 2)}`));
    summary.append(dl);
  }
  summary.append(element('p', !pending && assessment.rate_ready ? 'Eligible for a rate request. Engineering review remains required.' : 'Rates require a saved, validated package.', !pending && assessment.rate_ready ? 'good' : 'notice'));
  const findings = section(host, `Findings (${assessment.findings.length})`), list = element('ul', null, 'findings');
  assessment.findings.forEach(f => {
    const row = element('li', null, `finding ${f.severity === 'error' ? 'error' : ''}`);
    row.append(element('strong', f.severity === 'error' ? 'Error' : 'Review'), element('p', f.message));
    if (f.entity_ids?.length) row.append(button('Select affected component', () => {
      flushEditor();
      const box = state.draft.design.packages.find(p => f.entity_ids.includes(p.id) || [...p.placements, ...p.inserts].some(x => f.entity_ids.includes(x.id)));
      if (box) {
        state.packageId = box.id; state.componentId = [...box.placements, ...box.inserts].find(x => f.entity_ids.includes(x.id))?.id ?? null;
        state.editor = state.componentId ? 'contents' : 'carton'; render(); state.scene?.fit();
      }
    }));
    list.append(row);
  }); findings.append(list);
}

async function newDocument() {
  if (hasNavigationChanges() && !confirm('Discard unsaved document changes and session-only addresses, and start a new document?')) return;
  state.draft.reset(); state.formDirty = false; resetDocumentState(); render(); renderRates(); notify('New packaging document.');
}

function resetDocumentState() {
  state.packageId = null; state.componentId = null; state.candidates = null; state.candidateRevision = null;
  state.alternatives = [defaultCarton()]; state.alternativeIndex = 0; state.maxPackages = 3; state.candidateConfig = null;
  state.quotes = []; state.quoteIndex = 0; state.quoteScenario = null; state.quoteError = ''; state.mutationReceipt = null;
  state.addresses = { origin: blankAddress(), destinations: [blankAddress()] }; state.editor = 'product'; state.review = 'validation';
}

async function openDocuments() {
  await working('Loading packaging documents...', async () => {
    const data = await request('/documents');
    const list = $('document-list'); list.replaceChildren();
    if (!data.documents.length) list.append(element('p', 'No saved packaging documents.', 'notice'));
    data.documents.forEach(doc => {
      const row = element('div', null, 'document-row'), desc = element('div');
      desc.append(element('strong', doc.name), element('p', `Revision ${doc.revision} | ${new Date(doc.updated_at).toLocaleString()}`));
      row.append(desc, button('Open', () => loadDocument(doc.id))); list.append(row);
    });
    notify('');
  });
  $('open-dialog').showModal();
}

async function loadDocument(id) {
  if (hasNavigationChanges() && !confirm('Discard unsaved document changes and session-only addresses, and open the saved document?')) return;
  await working('Opening document...', async () => {
    const data = await request(`/documents/${encodeURIComponent(id)}`);
    resetDocumentState(); state.draft.accept(data); state.formDirty = false;
    await loadQuotes(); notify('Document opened.');
  });
  $('open-dialog').close(); render(); renderRates(); state.scene?.fit();
}

async function reloadDocument() {
  if (!state.draft.document) return;
  return loadDocument(state.draft.document.id);
}

async function saveDocument() {
  flushEditor();
  if (!state.draft.design.name.trim()) throw new Error('Enter a document name.');
  if (state.draft.document && !state.draft.dirty) { render(); return; }
  await working('Saving and validating document...', async () => {
    let result;
    if (!state.draft.document) result = await request('/documents', { method: 'POST', body: state.draft.design });
    else {
      // Keep the receipt on network failure so an exact retry is idempotent.
      const fingerprint = JSON.stringify({ revision: state.draft.document.revision, design: state.draft.design });
      if (state.mutationReceipt?.fingerprint !== fingerprint) state.mutationReceipt = { fingerprint, id: uid('edit') };
      result = await request(docPath(), { method: 'PUT', body: { expected_revision: state.draft.document.revision, request_id: state.mutationReceipt.id, design: state.draft.design } });
    }
    state.draft.accept(result); state.mutationReceipt = null; state.quoteError = ''; notify(`Saved revision ${result.revision}.`);
  });
  render();
}

async function historyAction(action) {
  flushEditor();
  if (state.draft[action]()) { render(); notify(action === 'undo' ? 'Draft edit undone.' : 'Draft edit restored.'); return; }
  if (!state.draft.document || state.draft.dirty) return;
  await working(`${action === 'undo' ? 'Undoing' : 'Redoing'} saved edit...`, async () => {
    const fingerprint = `${action}:${state.draft.document.id}:${state.draft.document.revision}`;
    if (state.mutationReceipt?.fingerprint !== fingerprint) state.mutationReceipt = { fingerprint, id: uid(action) };
    const result = await request(`${docPath()}/${action}`, { method: 'POST', body: { expected_revision: state.draft.document.revision, request_id: state.mutationReceipt.id } });
    state.draft.accept(result); state.mutationReceipt = null; notify(`Saved revision ${result.revision}.`);
  });
  render();
}

async function downloadPDF() {
  if (!state.draft.document || hasDraft()) throw new Error('Save all changes before downloading a report.');
  await working('Preparing PDF report...', async () => {
    const blob = await request(`${docPath()}/report.pdf?revision=${state.draft.document.revision}`, { responseType: 'blob' });
    const url = URL.createObjectURL(blob), link = element('a'); link.href = url; link.download = 'packaging-review.pdf';
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
    notify('PDF downloaded.');
  });
}

function addressFields(form, title, prefix, address) {
  const group = element('fieldset', null, 'address'); group.append(element('legend', title));
  field(group, 'Name / company', `${prefix}_name`, address.name, { maxLength: 100 });
  field(group, 'Street address', `${prefix}_street1`, address.street1, { required: true, maxLength: 150 });
  field(group, 'Suite / apartment', `${prefix}_street2`, address.street2, { maxLength: 150 });
  field(group, 'City', `${prefix}_city`, address.city, { required: true, maxLength: 100 });
  const row = element('div', null, 'two-cols');
  field(row, 'State (US)', `${prefix}_state`, address.state, { required: true, pattern: '[A-Za-z]{2}', maxLength: 2 });
  field(row, 'ZIP code', `${prefix}_zip`, address.zip, { required: true, pattern: '[0-9]{5}(-[0-9]{4})?', maxLength: 10 }); group.append(row);
  field(group, 'Country', `${prefix}_country`, 'US', { options: [['US', 'United States']] });
  const residential = checkbox(group, 'Residential address', address.residential, () => {}); residential.name = `${prefix}_residential`;
  form.append(group);
}

function captureAddresses() {
  if (!state.quoteForm) return state.addresses;
  const read = prefix => {
    const a = blankAddress();
    for (const key of Object.keys(a)) a[key] = key === 'residential' ? state.quoteForm.elements.namedItem(`${prefix}_${key}`).checked : textValue(state.quoteForm, `${prefix}_${key}`);
    a.state = a.state.toUpperCase(); return a;
  };
  return { origin: read('origin'), destinations: state.addresses.destinations.map((_, i) => read(`destination${i}`)) };
}

function renderRates() {
  const host = $('rates-panel'); host.replaceChildren();
  const provider = section(host, 'Rate provider');
  provider.append(element('p', state.providerError || `${state.provider?.provider || 'Provider'} | ${state.provider?.configured ? 'Configured' : 'Not configured'}`, state.provider?.configured ? 'notice' : 'warning'));
  provider.append(element('p', state.provider?.notice || 'Provider status unavailable.', 'notice'), button('Refresh provider status', refreshProvider, { symbol: 'arrow-clockwise' }));
  const form = element('form', null, 'form-grid'); state.quoteForm = form;
  addressFields(form, 'Origin', 'origin', state.addresses.origin);
  state.addresses.destinations.forEach((address, i) => addressFields(form, `Destination ${i + 1}`, `destination${i}`, address));
  const actions = element('div', null, 'actions');
  actions.append(button('Add destination', () => { state.addresses = captureAddresses(); state.addresses.destinations.push(blankAddress()); renderRates(); }, { disabled: state.addresses.destinations.length >= 3 }),
    button('Remove last destination', () => { state.addresses = captureAddresses(); state.addresses.destinations.pop(); renderRates(); }, { symbol: 'trash', compact: true, disabled: state.addresses.destinations.length <= 1 }));
  form.append(actions);
  const quoteButton = button('Compare rates', requestQuotes, { primary: true }); quoteButton.id = 'quote-button'; form.append(quoteButton);
  form.addEventListener('submit', event => { event.preventDefault(); invoke(requestQuotes); });
  const addressChanged = () => { updateHeader(); updateFreshness(); };
  form.addEventListener('input', addressChanged); form.addEventListener('change', addressChanged); host.append(form);
  host.append(element('div', null, 'review-section')); host.lastChild.id = 'quote-results'; renderQuoteResults(); updateHeader();
}

async function refreshProvider() {
  await working('Checking carrier provider...', async () => {
    try { const data = await request('/status'); state.provider = data.rating; state.providerError = ''; notify('Provider status updated.'); }
    catch (error) { state.provider = null; state.providerError = `Provider status unavailable: ${error.message}`; throw error; }
    finally { state.addresses = captureAddresses(); }
  }).finally(() => renderRates());
}

async function loadQuotes() {
  try { const data = await request(`${docPath()}/quotes`); state.quotes = data.quotes; state.quoteIndex = 0; }
  catch (error) { state.quoteError = `Quote history unavailable: ${error.message}`; }
}

async function requestQuotes() {
  if (!state.quoteForm.reportValidity()) return;
  flushEditor();
  if (!state.draft.document || state.draft.dirty) { render(); throw new Error('Save the document before requesting rates.'); }
  if (!state.provider?.configured) throw new Error('Carrier provider is not configured. No rates are available.');
  if (!state.draft.document.assessment.rate_ready) throw new Error('Resolve the validation errors before requesting rates.');
  state.addresses = captureAddresses(); const scenario = JSON.stringify(state.addresses);
  await working('Requesting carrier estimates...', async () => {
    try {
      const result = await request(`${docPath()}/quotes`, { method: 'POST', body: { expected_revision: state.draft.document.revision, ...state.addresses } });
      state.quotes.unshift(result); state.quotes = state.quotes.slice(0, 10); state.quoteIndex = 0;
      state.quoteScenario = { id: result.id, value: scenario }; state.quoteError = ''; notify('Carrier quote response received. No postage was purchased.');
    } catch (error) { state.quoteError = `Latest request failed: ${error.message}`; throw error; }
    finally { renderQuoteResults(); }
  });
}

function updateFreshness() {
  const quote = state.quotes[state.quoteIndex];
  const sameScenario = quote && state.quoteScenario?.id === quote.id && state.quoteScenario.value === JSON.stringify(captureAddresses());
  const label = $('quote-freshness');
  if (label) {
    label.textContent = `${state.quoteError ? 'Previous quote | ' : ''}${quoteFreshness(quote, state.draft.document?.revision, hasDraft(), sameScenario)}`;
    label.className = !hasDraft() && sameScenario && quote?.revision === state.draft.document?.revision && !quote?.stale ? 'good' : 'warning';
  }
  const b = $('quote-button');
  if (b) b.disabled = state.busy || !state.provider?.configured || !state.draft.document?.assessment.rate_ready || hasDraft();
  const assessment = $('validation-panel');
  if (assessment) assessment.setAttribute('data-stale', String(hasDraft()));
  renderValidation();
}

function rateTable(rates, total = false) {
  const wrap = element('div', null, 'rate-table-wrap'), table = element('table');
  table.setAttribute('aria-label', total ? 'All-package rate totals' : 'Individual parcel rates');
  const head = element('thead'), hr = element('tr');
  for (const title of ['Service', total ? 'Parcel sum' : 'Rate', 'Mode']) { const th = element('th', title); th.scope = 'col'; hr.append(th); } head.append(hr);
  const body = element('tbody');
  rates.forEach(rate => {
    const row = element('tr'), service = element('td');
    service.append(element('strong', rate.carrier), element('div', rate.service), element('div', rateAccountLabel(rate), 'rate-account muted'));
    if (rate.delivery_days != null) service.append(element('div', `${rate.delivery_days} days`, 'muted'));
    row.append(service, element('td', `${rate.currency} ${rate.amount}`, 'rate-amount'), element('td', rate.mode, rate.mode === 'test' ? 'warning' : ''));
    body.append(row);
  });
  table.append(head, body); wrap.append(table); return wrap;
}

function renderQuoteResults() {
  const host = $('quote-results'); if (!host) return; host.replaceChildren();
  host.append(element('h2', 'Carrier estimates'));
  if (state.quoteError) host.append(element('p', state.quoteError, 'error'));
  const quote = state.quotes[state.quoteIndex];
  if (!quote) { host.append(element('p', 'No verified carrier quote available.', 'notice')); updateFreshness(); return; }
  const select = field(host, 'Quote history', 'quote_history', state.quoteIndex, { options: state.quotes.map((q, i) => [String(i), `${new Date(q.quoted_at).toLocaleString()} | revision ${q.revision}`]) });
  select.addEventListener('change', () => { state.quoteIndex = Number(select.value); renderQuoteResults(); });
  const freshness = element('p'); freshness.id = 'quote-freshness'; host.append(freshness);
  host.append(element('p', `${quote.provider} | ${quote.ship_date_basis || ''}`, 'notice'));
  for (const result of quote.results || []) {
    const block = element('section', null, 'review-section');
    block.append(element('h3', `${result.destination.city}, ${result.destination.state} ${result.destination.zip}`));
    if (result.totals.length) {
      block.append(rateTable(result.totals, true), element('p', 'Sum of separate parcel estimates, not a consolidated shipment quote.', 'notice'));
    } else block.append(element('p', 'No common service across every package. See individual parcel responses.', 'warning'));
    for (const parcel of result.parcels) {
      const details = element('details'); details.append(element('summary', `${parcel.package_id} | ${parcel.mode} | ${parcel.rates.length} rates${parcel.carrier_error_count ? ` | ${parcel.carrier_error_count} carrier messages` : ''}`));
      if (parcel.carrier_error_count) details.append(element('p', `${parcel.carrier_error_count} carrier messages reported. Some services may be unavailable.`, 'warning'));
      details.append(parcel.rates.length ? rateTable(parcel.rates) : element('p', 'Provider returned no rates for this parcel.', 'warning')); block.append(details);
    }
    host.append(block);
  }
  if (quote.notice) host.append(element('p', quote.notice, 'notice')); updateFreshness();
}

function refreshScene() {
  const p = selectedPackage(), product = state.draft.design.product;
  $('scene-caption').textContent = `${product ? product.source_id ? product.name + ' | imported GLB' : product.name + ' | manual geometry' : 'No product selected'}${p ? ` | ${dimensionText(p.carton.inner_m)} internal` : ''}${state.exploded ? ' | exploded view, positions unchanged' : ''}`;
  state.scene?.setDesign(state.draft.design, state.packageId, state.componentId);
}

async function initializeScene() {
  const controls = $('view-actions');
  controls.append(button('Fit view', () => state.scene?.fit(), { symbol: 'corners-out', compact: true }));
  for (const [view, label] of [['iso', 'Orbit'], ['top', 'Top'], ['front', 'Front'], ['side', 'Side']]) {
    controls.append(button(label, () => state.scene?.view(view), { symbol: view === 'iso' ? 'cube' : undefined }));
  }
  checkbox(controls, 'Section', false, checked => { state.section = checked; state.scene?.setSection(checked); });
  checkbox(controls, 'Exploded', false, checked => { state.exploded = checked; state.scene?.setExploded(checked); refreshScene(); state.scene?.fit(); });
  try {
    const { PackagingScene } = await import('./packaging_scene.js');
    state.scene = new PackagingScene($('viewport'), {
      onStatus: message => { $('scene-message').textContent = message; },
      onSelect: id => invoke(() => { flushEditor(); state.componentId = id; state.editor = 'contents'; render(); })
    }); refreshScene();
  } catch (error) { $('scene-message').textContent = `3D unavailable: ${error.message}. Numeric editing remains available.`; }
}

function boot() {
  try { const theme = localStorage.getItem('inspectorpro.theme'); if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme; } catch { /* Storage may be restricted. */ }
  $('document-name').addEventListener('input', () => {
    edit(d => { d.name = $('document-name').value; }); updateHeader(); updateFreshness(); renderValidation();
  });
  $('package-select').addEventListener('change', event => invoke(() => {
    const next = event.target.value;
    try { flushEditor(); state.packageId = next; state.componentId = null; render(); state.scene?.fit(); }
    catch (error) { event.target.value = state.packageId || ''; throw error; }
  }));
  $('close-open').addEventListener('click', () => $('open-dialog').close());
  // The embedding workspace can consult this before removing its pilot iframe.
  window.InspectorProPackaging = Object.freeze({
    hasUnsavedChanges: () => hasNavigationChanges() || state.busy,
    confirmNavigation: () => !(hasNavigationChanges() || state.busy) || confirm('Leave Packaging & Shipping? Unsaved changes, session-only addresses or an active request may be lost.')
  });
  window.addEventListener('beforeunload', event => { if (hasNavigationChanges() || state.busy) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('pagehide', () => state.scene?.dispose());
  document.addEventListener('keydown', event => {
    if (!(event.ctrlKey || event.metaKey)) return;
    if (event.key.toLowerCase() === 's') { event.preventDefault(); invoke(saveDocument); }
    if (event.key.toLowerCase() === 'z' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)) {
      event.preventDefault(); invoke(() => historyAction(event.shiftKey ? 'redo' : 'undo'));
    }
  });
  render(); renderRates(); initializeScene(); invoke(refreshProvider);
}

if (typeof document !== 'undefined') boot();
