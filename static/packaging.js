export const ORIENTATION_ORDERS = [[0, 1, 2], [1, 0, 2], [1, 2, 0], [2, 1, 0], [2, 0, 1], [0, 2, 1]];
export const ORIENTATION_LABELS = ['XYZ', 'YXZ', 'YZX', 'ZYX', 'ZXY', 'XZY'];
export const PANEL_COMMANDS = [
  { id: 'product', label: 'Product', icon: 'cube', group: 'editor-tabs' },
  { id: 'carton', label: 'Carton', icon: 'bounding-box', group: 'editor-tabs' },
  { id: 'contents', label: 'Contents', icon: 'stack', group: 'editor-tabs' },
  { id: 'arrange', label: 'Arrange', icon: 'grid-four', group: 'editor-tabs' },
  { id: 'appearance', label: 'Appearance', icon: 'sphere', group: 'editor-tabs' },
  { id: 'graphics', label: 'Graphics', icon: 'rectangle', group: 'editor-tabs' },
  { id: 'validation', label: 'Validation', icon: 'cube-focus', group: 'review-tabs' },
  { id: 'rates', label: 'Rates', icon: 'navigation-arrow', group: 'review-tabs' },
];
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
    constraints: { clearance_m: .02, gap_m: .01, allowed_orientations: [0], contents: 'unconfirmed' },
    packages: [] };
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

export async function request(path, { method = 'GET', body, raw = false, contentType = 'model/gltf-binary', responseType = 'json', keepalive = false, idempotencyKey } = {}) {
  const headers = { 'X-InspectorPro-Request': 'packaging' };
  if (idempotencyKey !== undefined) headers['Idempotency-Key'] = idempotencyKey;
  if (body !== undefined) headers['Content-Type'] = raw ? contentType : 'application/json';
  const response = await fetch(`/api/packaging${path}`, { method, headers, credentials: 'same-origin', cache: 'no-store', keepalive,
    signal: AbortSignal.timeout(90000),
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
  if (!dirty && quote.revision === revision && quote.stale_reason === 'account_changed') return 'Stale: carrier account changed';
  if (!dirty && quote.revision === revision && quote.stale_reason === 'account_removed') return 'Stale: carrier account removed';
  if (dirty || quote.stale || quote.revision !== revision) return 'Stale: package changed';
  if (!scenarioMatches) return 'Stale: address scenario changed or not loaded';
  return 'Current saved revision';
}

export function priceText(currency, amount) {
  return amount == null ? '-' : `${currency || ''} ${amount}`.trim();
}

export function scenarioComplete(addresses) {
  const filled = a => Boolean(a) && ['street1', 'city', 'state', 'zip'].every(key => String(a[key] ?? '').trim());
  const destinations = addresses?.destinations || [];
  return filled(addresses?.origin) && destinations.length > 0 && destinations.every(filled);
}

export function scenarioLabel(scenario) {
  const places = (scenario.destinations || []).map(d => `${d.city}, ${d.state} ${d.zip}${d.residential ? ' (residential)' : ''}`).join('; ');
  const parts = [places || 'No destinations', (scenario.modes || []).join('/') || 'mode unknown', `${scenario.quotes} quote(s)`, `latest ${scenario.quoted_at}`];
  if (!scenario.current_account) parts.push('other carrier account');
  return parts.join(' | ');
}

export function differenceText(value, currency) {
  if (value == null) return '-';
  const n = Number(value);
  return `${currency} ${n > 0 ? '+' : ''}${value} ${n < 0 ? '(lower)' : n > 0 ? '(higher)' : '(same)'}`;
}

export const CAVEAT_LABELS = { test_mode: 'Test mode', materials_unknown: 'Materials unknown', payload_unknown: 'Payload unknown',
  parcel_sum: 'Parcel sum', currency_differs: 'Currency differs', quote_dates_differ: 'Quoted over 24 h apart' };

export function comparisonCells(row, comparison) {
  const currency = comparison.service?.currency || '';
  const status = row.baseline ? (comparison.baseline.ready ? 'Baseline' : 'Baseline (not ready)') : row.eligible ? 'Compared' : 'Not compared';
  const labels = row.caveats.map(code => CAVEAT_LABELS[code] || code).join(', ');
  const notes = [...row.reasons.map(code => comparison.reasons[code] || code), labels].filter(Boolean).join(' ');
  return [row.name, status, String(row.package_count), row.gross_kg == null ? 'Unknown' : `${Number(row.gross_kg).toFixed(3)} kg`,
    priceText(currency, row.shipping_total), priceText('USD', row.materials_usd), priceText(currency, row.total),
    differenceText(row.shipping_difference, currency), notes];
}

export function comparisonOrder(comparison) {
  const ranked = new Map(comparison.ranking.map((ref, i) => [ref, i]));
  const place = row => ranked.has(row.ref) ? ranked.get(row.ref) : comparison.ranking.length + row.order;
  return [...comparison.rows].sort((a, b) => place(a) - place(b));
}

export function quoteBody(revision, addresses, accounts, options, refresh) {
  const chosen = {};
  if (options.delivery_confirmation) chosen.delivery_confirmation = options.delivery_confirmation;
  if (options.saturday_delivery) chosen.saturday_delivery = true;
  return { expected_revision: revision, ...addresses, carrier_accounts: [...accounts], options: chosen, refresh: refresh === true };
}

// The scenario a user lets Sage quote: the Rates panel body without revision or refresh, plus a budget and time limit.
export function scenarioBody(addresses, accounts, options, shipments, minutes) {
  const { expected_revision: _revision, refresh: _refresh, ...scenario } = quoteBody(0, addresses, accounts, options, false);
  return { ...scenario, sage_shipments: shipments, minutes };
}

// What Sage sees of an address: never a name, street or ZIP code.
export const sagePlace = address => `${address.city}, ${address.state}${address.residential ? ' (residential)' : ''}`;

const EVIDENCE_KINDS = { carton_sku: 'Carton SKU', material_density: 'Material density', cushioning_guidance: 'Cushioning guidance', comparable_packaging: 'Comparable packaging' };

// What a research record states and how it was found: a quoted page passage or the provider's summary of the page.
export function evidenceFacts(record) {
  const facts = [record.claim_basis === 'source_quote' ? 'Quoted from the page' : 'Provider summary of the page, not a quotation'];
  if (record.value != null) facts.push(`Value ${record.value}${record.unit ? ` ${record.unit}` : ''}`);
  else if (record.unit) facts.push(`Unit ${record.unit}`);
  if (record.sku_or_grade) facts.push(`SKU/grade ${record.sku_or_grade}`);
  if (record.effective_date) facts.push(`Effective ${record.effective_date}`);
  facts.push(`Sage confidence: ${record.confidence}`);
  facts.push(record.review_status === 'accepted' ? 'Accepted by you' : record.review_status === 'rejected' ? 'Rejected by you' : 'Unreviewed');
  return facts;
}

// Only public web links open; anything else is shown as text.
export const evidenceLink = url => /^https?:\/\//i.test(String(url || '')) ? String(url) : null;

export function messageSummary(messages) {
  const seen = new Set(), lines = [];
  for (const m of messages || []) {
    const key = `${m.carrier || ''}|${m.category}`;
    if (!seen.has(key)) { seen.add(key); lines.push(`${m.carrier || 'Carrier'}: ${m.help}`); }
  }
  return lines;
}

export function rateAccountLabel(rate) {
  return `Account: ${String(rate.account_id ?? '').trim() || 'not provided'}`;
}

export function providerNotice(provider) {
  if (!provider) return 'Provider status unavailable.';
  if (provider.notice) return String(provider.notice);
  if (provider.validation === 'unavailable') return 'Carrier account access is unavailable.';
  if (!provider.configured) return 'No carrier account configured.';
  if (provider.validation === 'not_validated') return 'Account saved; provider access has not been verified.';
  return 'Rate estimates only. Shipment purchases are disabled.';
}

export const PACKAGING_BRIDGE = 'inspectorpro:packaging-editor-v1';
const bridgeId = value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,160}$/.test(value);
const bridgeHostId = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$/.test(value);
const bridgeRevision = value => Number.isSafeInteger(value) && value >= 0;

export class PackagingEditorAdmission {
  constructor({ snapshot, lock, accept, api = request, invalidate = () => {},
    schedule = (...args) => globalThis.setTimeout(...args),
    unschedule = (...args) => globalThis.clearTimeout(...args) }) {
    Object.assign(this, { snapshot, lock, accept, api, invalidate, schedule, unschedule });
    this.locked = false; this.admission = null; this.timer = null; this.closing = null;
  }
  summary() {
    const current = this.snapshot();
    return { admission_id: this.admission?.admission_id || null, document_id: current.document_id,
      revision: current.revision, state: this.locked ? 'locked' : 'idle' };
  }
  clean(current) {
    return bridgeId(current.document_id) && bridgeRevision(current.revision)
      && current.dirty === false && current.conflict === false && current.pending_operations === 0;
  }
  async prepare(identity) {
    const current = this.snapshot();
    if (this.locked || !this.clean(current)) throw new Error('Save or reload the packaging document and finish pending operations before sending.');
    if (!bridgeHostId(identity?.session_id) || !bridgeHostId(identity?.conversation_id)) throw new Error('An active chat session is required.');
    this.locked = true; this.lock(true);
    this.binding = { ...current, session_id: identity.session_id, conversation_id: identity.conversation_id, active_mode: 'packaging_shipping' };
    try {
      const result = await this.api('/editor', { method: 'POST', body: this.binding });
      if (!bridgeId(result?.admission_id) || !bridgeId(result?.selection_id) || !Number.isFinite(result.expires_in) || result.expires_in <= 0) {
        throw new Error('The packaging editor admission was not acknowledged.');
      }
      this.admission = result;
      this.renew();
      return this.summary();
    } catch (error) {
      this.locked = false; this.lock(false);
      throw error;
    }
  }
  renew() {
    this.unschedule(this.timer);
    const admitted = this.admission;
    if (!admitted || this.closing) return;
    this.timer = this.schedule(async () => {
      try {
        const current = this.snapshot();
        if (!this.clean(current) || current.document_id !== this.binding.document_id || current.revision !== this.binding.revision) {
          throw new Error('The packaging editor changed during the response.');
        }
        await this.api(`/editor/${encodeURIComponent(admitted.admission_id)}/heartbeat`, {
          method: 'POST', body: { ...this.binding, selection_id: admitted.selection_id }
        });
        if (this.admission === admitted && !this.closing) this.renew();
      } catch (error) {
        if (error?.code === 'editor_turn_finished') return;
        if (this.admission === admitted && !this.closing) this.invalidate(error);
      }
    }, Math.max(1000, Math.min(10000, admitted.expires_in * 1000 / 3)));
  }
  finish(terminal = {}) {
    if (this.closing) return this.closing;
    this.unschedule(this.timer);
    this.closing = this.reconcile(terminal).finally(() => { this.closing = null; });
    return this.closing;
  }
  async reconcile(terminal) {
    const admitted = this.admission;
    if (admitted) {
      await this.api(`/editor/${encodeURIComponent(admitted.admission_id)}/revoke`, {
        method: 'POST', body: { selection_id: admitted.selection_id }
      });
      const before = this.snapshot();
      if (!this.clean(before) || before.document_id !== this.binding.document_id || before.revision !== this.binding.revision) {
        throw new Error('The selected packaging document changed. Its draft was retained; reload to reconcile.');
      }
      const saved = await this.api(`/documents/${encodeURIComponent(before.document_id)}`);
      const after = this.snapshot();
      const expected = terminal.documentId === before.document_id && bridgeRevision(terminal.revision)
        ? Math.max(before.revision, terminal.revision) : before.revision;
      if (!this.clean(after) || after.document_id !== before.document_id || after.revision !== before.revision
          || saved?.id !== before.document_id || !bridgeRevision(saved.revision) || saved.revision < expected) {
        throw new Error('The saved packaging revision could not be reconciled. Your draft was not replaced.');
      }
      await this.accept(saved);
    }
    this.admission = null; this.locked = false; this.lock(false);
    return this.summary();
  }
  unload() {
    this.unschedule(this.timer);
    if (this.admission) void this.api(`/editor/${encodeURIComponent(this.admission.admission_id)}/revoke`, {
      method: 'POST', body: { selection_id: this.admission.selection_id }, keepalive: true
    }).catch(() => {});
  }
}

export class PackagingHostBridge {
  constructor({ hostWindow, frame, invalidate = () => {} }) {
    this.window = hostWindow; this.frame = frame; this.invalidate = invalidate;
    this.pending = new Map(); this.admitted = null; this.preparing = false;
    this.listener = event => this.receive(event);
    hostWindow.addEventListener('message', this.listener);
  }
  receive(event) {
    const data = event.data;
    if (event.origin !== this.window.location.origin || event.source !== this.frame()?.contentWindow
        || data?.type !== PACKAGING_BRIDGE) return;
    if (data.action === 'invalidate' || data.action === 'release-request') { this.invalidate(); return; }
    const pending = this.pending.get(data.request_id);
    if (!pending || pending.source !== event.source || data.action !== 'result') return;
    this.pending.delete(data.request_id); clearTimeout(pending.timer);
    if (data.ok !== true) { pending.reject(new Error(typeof data.error === 'string' ? data.error.slice(0, 500) : 'Packaging bridge failed.')); return; }
    const value = data.value;
    if (!value || Object.keys(value).some(key => !['admission_id', 'document_id', 'revision', 'state'].includes(key))
        || !['locked', 'idle'].includes(value.state) || (value.document_id !== null && !bridgeId(value.document_id))
        || (value.revision !== null && !bridgeRevision(value.revision))
        || (value.admission_id !== null && !bridgeId(value.admission_id))) {
      pending.reject(new Error('Invalid packaging bridge acknowledgement.')); return;
    }
    pending.resolve(value);
  }
  command(action, payload = {}) {
    const source = this.frame()?.contentWindow;
    if (!source) return Promise.reject(new Error('Open the packaging editor before sending.'));
    const request_id = crypto.randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(request_id); reject(new Error('Packaging editor acknowledgement timed out. The editor may remain locked.')); }, 45000);
      this.pending.set(request_id, { source, resolve, reject, timer });
      source.postMessage({ type: PACKAGING_BRIDGE, action, request_id, payload }, this.window.location.origin);
    });
  }
  async prepare(identity) {
    if (this.preparing || this.admitted) throw new Error('A packaging turn is already active.');
    this.preparing = true;
    try {
      const value = await this.command('prepare', identity);
      if (value.state !== 'locked' || !value.admission_id) throw new Error('Packaging editor did not lock and acknowledge admission.');
      this.admitted = value; return value;
    } finally { this.preparing = false; }
  }
  async finish(terminal = {}) {
    const safe = {};
    if (bridgeId(terminal?.documentId)) safe.documentId = terminal.documentId;
    if (bridgeRevision(terminal?.revision)) safe.revision = terminal.revision;
    const value = await this.command('finish', safe);
    if (value.state !== 'idle') throw new Error('Packaging editor did not release its lock.');
    this.admitted = null; return value;
  }
  async release() {
    const value = await this.command('release');
    if (value.state !== 'idle') throw new Error('Packaging editor did not release its lock.');
    this.admitted = null; return value;
  }
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
  editor: 'product', review: 'validation', panel: null, packageId: null, componentId: null, appearanceTarget: 'product', graphicId: null, scene: null,
  alternatives: [defaultCarton()], alternativeIndex: 0, maxPackages: 3, candidates: null, candidateRevision: null, candidateConfig: null,
  provider: null, providerError: '', quotes: [], quoteIndex: 0, quoteScenario: null, quoteError: '',
  quoteAccounts: [], quoteOptions: { delivery_confirmation: null, saturday_delivery: false }, quoteRules: null, quoteAttempts: null,
  addresses: { origin: blankAddress(), destinations: [blankAddress()] }, quoteForm: null,
  section: false, exploded: false, displayMode: 'edges', transparency: 0,
  mutationReceipt: null, lastDirtySignal: null, lastRibbonSignal: null, sage: null, conflict: false,
  capabilities: [], catalog: null, alternativeReceipt: null, scenarios: [], evidence: [], evidenceNotice: ''
};

function blankAddress() { return { name: '', street1: '', street2: '', city: '', state: '', zip: '', country: 'US', residential: false }; }
const selectedPackage = () => state.draft.design.packages.find(p => p.id === state.packageId);
const docPath = () => `/documents/${encodeURIComponent(state.draft.document.id)}`;
const hasDraft = () => state.draft.dirty || state.formDirty;
const hasAddressInputs = () => JSON.stringify(captureAddresses()) !== JSON.stringify({ origin: blankAddress(), destinations: [blankAddress()] });
const hasSelectedFiles = () => [...document.querySelectorAll('input[type="file"]')].some(input => input.files?.length);
const hasNavigationChanges = () => hasDraft() || hasAddressInputs() || hasSelectedFiles();

function notify(message, error = false) {
  $('message').textContent = message; $('message').className = `message${error ? ' error' : ''}`; $('message').hidden = !message;
  $('message').setAttribute('role', error ? 'alert' : 'status');
}

async function invoke(action) {
  if (state.busy) return;
  if (state.sage?.locked) { notify('The editor is locked for the active response. Resume editing to stop and reconcile it.', true); return; }
  try { await action(); }
  catch (error) {
    if (error.code === 'revision_conflict') state.conflict = true;
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

function edit(change) {
  if (state.sage?.locked) throw new Error('The packaging editor is locked for the active response.');
  state.draft.edit(change);
}

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
  if (state.formDirty && state.editorForm) {
    state.panel = state.editor; updatePanel();
    state.editorForm.apply();
  }
}

function openPanel(id, { toggle = true, focus = true } = {}) {
  const command = PANEL_COMMANDS.find(item => item.id === id);
  if (!command) throw new Error('Unknown packaging panel.');
  if (toggle && state.panel === id) { closePanel(); return; }
  if (command.group === 'editor-tabs' && state.editor !== id) {
    if ($('editor').querySelector('input[type="file"]')?.files?.length) throw new Error('Import or clear the selected source file first.');
    flushEditor(); state.editor = id; renderEditor(); refreshScene();
  } else if (command.group === 'review-tabs') state.review = id;
  state.panel = id; updatePanel(); updateHeader(); renderValidation();
  if (focus) $('tool-panel').focus({ preventScroll: true });
}

function closePanel() {
  const previous = state.panel;
  state.panel = null; updatePanel();
  if (previous && document.documentElement.dataset.embedded === 'true') {
    window.parent.postMessage({ type: 'inspectorpro:packaging-focus', command: previous }, window.location.origin);
  } else if (previous) $(`command-${previous}`)?.focus({ preventScroll: true });
}

function updatePanel() {
  const panel = $('tool-panel'); if (!panel) return;
  const command = PANEL_COMMANDS.find(item => item.id === state.panel);
  panel.hidden = !command; $('workspace').classList.toggle('panel-open', !!command);
  $('panel-title').textContent = command?.label || 'Product';
  $('panel-state').textContent = state.sage?.locked ? 'Locked for chat' : state.busy ? 'Working...'
    : state.formDirty ? 'Unapplied fields' : state.draft.dirty ? 'Unsaved changes' : state.draft.document ? `Saved revision ${state.draft.document.revision}` : 'New document';
  $('editor').hidden = !command || command.group !== 'editor-tabs';
  $('validation-panel').hidden = state.panel !== 'validation'; $('rates-panel').hidden = state.panel !== 'rates';
  for (const item of PANEL_COMMANDS) {
    const control = $(`command-${item.id}`);
    if (control) { control.setAttribute('aria-expanded', String(state.panel === item.id)); control.disabled = state.busy || !!state.sage?.locked; }
  }
  if ($('close-panel')) $('close-panel').disabled = state.busy || !!state.sage?.locked;
  publishRibbonState();
}

// Both ribbons dispatch to the same controls, so admission locks and draft checks
// cannot be bypassed by the host UI.
const DOCUMENT_COMMANDS = ['new', 'open', 'save', 'undo', 'redo', 'reload', 'pdf'];
function commandControl(id) {
  if (PANEL_COMMANDS.some(item => item.id === id)) return $(`command-${id}`);
  if (DOCUMENT_COMMANDS.includes(id)) return $(`document-${id}`);
  if (id === 'resume') return $('packaging-resume-editing');
  return null;
}

function ribbonState() {
  const modal = !!document.querySelector('dialog[open]');
  const commands = {};
  for (const id of [...PANEL_COMMANDS.map(item => item.id), ...DOCUMENT_COMMANDS, 'resume']) {
    const node = commandControl(id);
    commands[id] = { enabled: !!node && !node.disabled && !modal && (id === 'resume' || (!state.busy && !state.sage?.locked)), active: state.panel === id };
  }
  return { commands, locked: !!state.sage?.locked };
}

function publishRibbonState() {
  if (window.parent === window) return;
  const signal = JSON.stringify(ribbonState());
  if (signal === state.lastRibbonSignal) return;
  state.lastRibbonSignal = signal;
  window.parent.postMessage({ type: 'inspectorpro:packaging-ribbon' }, window.location.origin);
}

function executeRibbonCommand(id) {
  if (!ribbonState().commands[id]?.enabled) return false;
  commandControl(id).click();
  return true;
}

function updateHeader() {
  const draft = state.draft, doc = draft.document;
  $('document-status').textContent = `${doc ? `Revision ${doc.revision}` : 'New document'} | ${state.sage?.locked ? 'Locked for chat' : state.busy ? 'Working...' : hasDraft() ? 'Unsaved changes' : doc ? 'Saved' : 'Not saved'}`;
  const actions = $('document-actions'); actions.replaceChildren();
  actions.append(
    button('New', newDocument), button('Open', openDocuments),
    button('Save', saveDocument, { symbol: 'floppy-disk', primary: true, disabled: state.busy || (!!doc && !hasDraft()) }),
    button('Undo', () => historyAction('undo'), { symbol: 'arrow-u-up-left', compact: true, disabled: !state.formDirty && !draft.past.length && !doc?.can_undo }),
    button('Redo', () => historyAction('redo'), { symbol: 'arrow-u-up-right', compact: true, disabled: state.formDirty || (!draft.future.length && (draft.dirty || !doc?.can_redo)) }),
    button('Reload saved document', reloadDocument, { symbol: 'arrow-clockwise', compact: true, disabled: !doc }),
    button('Download PDF', downloadPDF, { symbol: 'file-export', compact: true, disabled: !doc || hasDraft() })
  );
  [...actions.children].forEach((node, index) => { node.id = `document-${DOCUMENT_COMMANDS[index]}`; });
  if (state.busy || state.sage?.locked) for (const node of actions.querySelectorAll('button')) node.disabled = true;
  if (state.sage?.locked) {
    const resume = element('button', 'Resume editing'); resume.id = 'packaging-resume-editing'; resume.type = 'button';
    resume.addEventListener('click', () => window.parent.postMessage({ type: PACKAGING_BRIDGE, action: 'release-request' }, window.location.origin));
    actions.append(resume);
  }
  $('document-name').disabled = state.busy || !!state.sage?.locked;
  $('workspace').inert = !!state.sage?.locked;
  document.documentElement.dataset.packagingLocked = String(!!state.sage?.locked);
  updatePanel();
  const provider = state.provider;
  $('provider-status').textContent = state.providerError || (provider ? `${provider.provider}: ${provider.configured ? 'configured | quote only' : 'not configured'}` : 'Checking rate provider...');
  const dirtySignal = JSON.stringify({ dirty: hasNavigationChanges() || state.busy, documentId: doc?.id || null, revision: doc?.revision ?? null });
  if (dirtySignal !== state.lastDirtySignal) {
    state.lastDirtySignal = dirtySignal;
    if (window.parent !== window) window.parent.postMessage({ type: 'inspectorpro:packaging-dirty', ...JSON.parse(dirtySignal) }, window.location.origin);
  }
}

function renderTabs() {
  for (const [index, command] of PANEL_COMMANDS.entries()) {
    if ($(`command-${command.id}`)) continue;
    const b = button(command.label, () => openPanel(command.id), { symbol: command.icon });
    b.id = `command-${command.id}`; b.classList.add('ribbon-command');
    b.setAttribute('aria-controls', 'tool-panel'); b.setAttribute('aria-haspopup', 'dialog');
    b.addEventListener('keydown', event => {
      if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? PANEL_COMMANDS.length - 1
        : (index + (event.key === 'ArrowRight' ? 1 : -1) + PANEL_COMMANDS.length) % PANEL_COMMANDS.length;
      $(`command-${PANEL_COMMANDS[next].id}`).focus();
    });
    $(command.group).append(b);
  }
  updatePanel();
}

function render() {
  if (!selectedPackage()) state.packageId = state.draft.design.packages[0]?.id ?? null;
  $('document-name').value = state.draft.design.name;
  updateHeader(); renderTabs(); renderPackages(); renderEditor(); renderValidation(); renderQuoteResults();
  refreshScene(); updatePanel();
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
      state.packageId = id; state.editor = 'carton'; state.panel = 'carton'; render(); state.scene?.fit();
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
  ({ product: renderProduct, carton: renderCarton, contents: renderContents, arrange: renderArrange, appearance: renderAppearance, graphics: renderGraphics })[state.editor](host);
}

function section(host, heading) {
  const group = element('section', null, 'editor-section'); group.append(element('h2', heading)); host.append(group); return group;
}

function resourceDialog(title, build, { wide = false } = {}) {
  notify('');
  let dialog = $('resource-dialog');
  if (!dialog) {
    dialog = element('dialog'); dialog.id = 'resource-dialog'; document.body.append(dialog);
    dialog.addEventListener('close', () => { dialog.replaceChildren(); updateHeader(); });
    dialog.addEventListener('cancel', event => { if (state.busy) event.preventDefault(); });
  }
  dialog.replaceChildren(); dialog.setAttribute('aria-labelledby', 'resource-title'); dialog.classList.toggle('wide', wide);
  const header = element('div', null, 'dialog-header'), heading = element('h2', title); heading.id = 'resource-title';
  const close = button('Close dialog', () => dialog.close(), { compact: true }); close.append(element('span', '\u00d7'));
  header.append(heading, close); const body = element('div', null, 'resource-body'); dialog.append(header, body);
  build(body, dialog); if (!dialog.open) dialog.showModal(); updateHeader();
}

async function getCatalog() {
  if (!state.catalog) state.catalog = await request('/catalog');
  return state.catalog;
}

export function productFromSource(meta, previous = {}) {
  return { ...clone(previous), name: meta.name, dimensions_m: clone(meta.dimensions_m), mass_kg: null,
    mass_basis: 'unknown', mass_evidence: '', mass_calculation: null, source_id: meta.id, source_revision: meta.source_revision };
}

async function openSources() {
  flushEditor();
  const data = await working('Loading product sources...', () => request('/sources'));
  resourceDialog('Product sources', (body, dialog) => {
    if (!data.sources.length) body.append(element('p', 'No imported sources.', 'notice'));
    for (const meta of data.sources) {
      const row = element('div', null, 'document-row'), info = element('div');
      info.append(element('strong', meta.name), element('p', dimensionText(meta.dimensions_m)), element('code', meta.id));
      if (meta.volume_m3) info.append(element('p', `Solid volume: ${numberText(meta.volume_m3 * 1e6)} cm3`));
      row.append(info, button('Use source', () => {
        if (state.draft.design.product && !confirm('Replace the product in every placement and reset its mass evidence?')) return;
        edit(d => { d.product = productFromSource(meta, d.product || {}); }); dialog.close(); render(); state.scene?.fit();
      })); body.append(row);
    }
  });
}

async function openMassEstimate() {
  flushEditor(); render();
  const product = state.draft.design.product;
  const data = await working('Loading physical material evidence...', async () => ({
    meta: await request(`/sources/${encodeURIComponent(product.source_id)}`), catalog: await getCatalog()
  }));
  if (data.meta.format !== 'step' || data.meta.physical_evidence?.volume_basis !== 'closed_solid_brep') throw new Error('This source has no trusted closed-solid STEP volume.');
  resourceDialog('Volume and density estimate', (body, dialog) => {
    body.append(element('p', `STEP solid volume: ${numberText(data.meta.volume_m3 * 1e6)} cm3`, 'metadata'));
    const form = element('form', null, 'form-grid'); form.addEventListener('submit', event => event.preventDefault()); body.append(form);
    const calculation = product.mass_calculation;
    field(form, 'Material name', 'estimate_material', calculation?.material.name || '', { required: true, maxLength: 160 });
    field(form, 'Density (kg/m3)', 'estimate_density', calculation?.material.density_kg_m3 || '', { type: 'number', min: .000001, max: 25000, required: true });
    field(form, 'Density evidence', 'estimate_evidence', calculation?.material.evidence || '', { multiline: true, required: true, maxLength: 500 });
    materialCatalogField(form, data.catalog.materials, 'product', ['estimate_material', 'estimate_density', 'estimate_evidence']);
    field(form, 'Exclusions / assumptions', 'estimate_exclusions', calculation?.exclusions || '', { multiline: true, required: true, maxLength: 500 });
    form.append(button('Calculate estimate', async () => {
      if (!form.reportValidity()) return;
      const result = await working('Calculating mass estimate...', () => request(`/sources/${encodeURIComponent(product.source_id)}/mass-estimate`, { method: 'POST', body: {
        source_revision: product.source_revision, material: { name: textValue(form, 'estimate_material'), density_kg_m3: numeric(form, 'estimate_density'), evidence: textValue(form, 'estimate_evidence') },
        exclusions: textValue(form, 'estimate_exclusions')
      } }));
      if (result.product.source_id !== product.source_id || result.product.source_revision !== product.source_revision
        || JSON.stringify(result.product.dimensions_m) !== JSON.stringify(product.dimensions_m)) throw new Error('Estimated product does not match the selected source.');
      state.editorForm.stageMass(result.product); dialog.close(); notify('Mass estimate staged. Product changes are not yet applied.');
    }, { primary: true }));
  });
}

function materialCatalogField(form, materials, use, names, { parent = form, name = 'material_catalog' } = {}) {
  const entries = materials.filter(item => item.use === use || item.use === 'both');
  const select = field(parent, 'Material catalog', name, '', { options: [['', 'Custom material'], ...entries.map(item => [item.id, item.material.name])] });
  select.addEventListener('change', () => {
    const selected = entries.find(item => item.id === select.value)?.material; if (!selected) return;
    [selected.name, selected.density_kg_m3, selected.evidence].forEach((value, index) => { form.elements.namedItem(names[index]).value = value; });
    form.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

function renderProduct(host) {
  const product = state.draft.design.product;
  const source = section(host, 'Product source');
  const upload = element('form', null, 'form-grid');
  const stepEnabled = state.capabilities.includes('step_import');
  const file = field(upload, stepEnabled ? 'Source GLB / STEP' : 'Source GLB', 'source_file', '', { type: 'file', accept: stepEnabled ? '.glb,.step,.stp' : '.glb,model/gltf-binary', required: true });
  const units = field(upload, 'Stored coordinate units', 'source_units', '1', { options: [['1', 'Meters'], ['0.001', 'Millimeters'], ['0.0254', 'Inches']] });
  const importButton = button('Import GLB', () => {
    if (!upload.reportValidity()) return;
    return importSource(file.files[0], Number(textValue(upload, 'source_units')));
  }, { symbol: 'file-export' }); upload.append(importButton);
  file.addEventListener('change', () => {
    const step = /\.(step|stp)$/i.test(file.files[0]?.name || ''); units.disabled = step;
    importButton.replaceChildren(element('span', step ? 'Import STEP' : 'Import GLB'));
    importButton.setAttribute('aria-label', step ? 'Import STEP' : 'Import GLB');
  });
  upload.addEventListener('submit', event => event.preventDefault()); source.append(upload);
  if (state.capabilities.includes('saved_alternatives')) source.append(button('Imported sources', openSources, { symbol: 'stack' }));
  if (product?.source_id) {
    const meta = element('div', null, 'metadata');
    meta.append(element('span', 'Imported source | dimensions locked'), element('code', product.source_id), element('span', 'Source revision'), element('code', product.source_revision));
    source.append(meta, button('Replace with manual geometry', () => {
      if (!confirm('Replace the imported model with editable manual bounding geometry?')) return;
      flushEditor(); edit(d => { d.product.source_id = null; d.product.source_revision = ''; d.product.mass_calculation = null; }); render();
    }, { symbol: 'bounding-box' }));
  } else source.append(element('p', product ? 'Manual geometry: bounding box only.' : 'No product selected.', 'notice'));

  const group = section(host, product ? 'Product properties' : 'Manual product');
  const p = product || { name: 'Product', dimensions_m: [.1, .1, .1], mass_kg: null, mass_basis: 'unknown', mass_evidence: '', source_id: null, source_revision: '' };
  let estimatedProduct = null;
  const { form, actions } = createForm(form => {
    const basis = textValue(form, 'mass_basis');
    const updated = { ...clone(p), name: textValue(form, 'product_name'),
      dimensions_m: p.source_id ? clone(p.dimensions_m) : readVector(form, 'product_dim'), mass_basis: basis,
      mass_kg: basis === 'unknown' ? null : numeric(form, 'product_mass'), mass_evidence: basis === 'unknown' ? '' : textValue(form, 'mass_evidence') };
    const estimate = estimatedProduct || p;
    if (estimatedProduct || 'mass_calculation' in updated) updated.mass_calculation = basis === 'estimate' && updated.mass_kg === estimate.mass_kg ? clone(estimate.mass_calculation || null) : null;
    const allowed = [...form.querySelectorAll('[name="orientation"]:checked')].map(x => Number(x.value));
    if (!allowed.length) throw new Error('Allow at least one product orientation.');
    const protection = readProtection(form);
    edit(d => {
      d.product = updated; d.quantity = numeric(form, 'quantity');
      // Spread first: constraint fields this form does not edit must survive an Apply.
      d.constraints = compactConstraints({ ...d.constraints, clearance_m: mmToM(numeric(form, 'clearance')), gap_m: mmToM(numeric(form, 'gap')),
        allowed_orientations: allowed, contents: textValue(form, 'contents'), ...protection });
    });
  }, product ? 'Apply product' : 'Add manual product');
  field(form, 'Product name', 'product_name', p.name, { maxLength: 160, required: true });
  vector(form, 'Source dimensions', 'product_dim', p.dimensions_m, { readOnly: !!p.source_id });
  field(form, 'Total product quantity', 'quantity', state.draft.design.quantity, { type: 'number', min: 1, max: 48, step: 1, required: true });
  const basis = field(form, 'Mass basis', 'mass_basis', p.mass_basis, { options: [['unknown', 'Unknown'], ['user_measured', 'Measured'], ['estimate', 'Estimate'], ...(p.mass_basis === 'cad' ? [['cad', 'CAD record']] : [])] });
  const mass = field(form, 'Mass per product (kg)', 'product_mass', p.mass_kg, { type: 'number', min: .000001, max: 1000 });
  const evidence = field(form, 'Mass evidence', 'mass_evidence', p.mass_evidence, { multiline: true, maxLength: 500 });
  const updateMass = () => {
    mass.disabled = evidence.disabled = basis.value === 'unknown'; mass.required = evidence.required = basis.value !== 'unknown';
    mass.readOnly = evidence.readOnly = basis.value === 'cad';
  };
  basis.addEventListener('change', updateMass); updateMass();
  const calculation = element('p', p.mass_calculation ? `Volume: ${numberText(p.mass_calculation.volume_m3 * 1e6)} cm3 | ${p.mass_calculation.material.name} | ${p.mass_calculation.material.density_kg_m3} kg/m3 | ${p.mass_calculation.exclusions}` : '', 'metadata');
  form.append(calculation);
  state.editorForm.stageMass = estimated => {
    estimatedProduct = clone(estimated); basis.value = estimated.mass_basis; mass.value = estimated.mass_kg; evidence.value = estimated.mass_evidence; updateMass();
    calculation.textContent = `Volume: ${numberText(estimated.mass_calculation.volume_m3 * 1e6)} cm3 | ${estimated.mass_calculation.material.name} | ${estimated.mass_calculation.material.density_kg_m3} kg/m3 | ${estimated.mass_calculation.exclusions}`;
    state.formDirty = true; updateHeader(); updateFreshness();
  };
  if (p.source_id && state.capabilities.includes('cad_volume_density_estimate')) form.append(button('Estimate from volume and density', openMassEstimate, { symbol: 'cube' }));
  form.append(element('h3', 'Packing restrictions'));
  const dims = element('div', null, 'two-cols');
  field(dims, 'Wall clearance (mm)', 'clearance', mToMm(state.draft.design.constraints.clearance_m), { type: 'number', min: 0, max: 200, required: true });
  field(dims, 'Product gap (mm)', 'gap', mToMm(state.draft.design.constraints.gap_m), { type: 'number', min: 0, max: 200, required: true }); form.append(dims);
  const orientations = element('fieldset'); orientations.append(element('legend', 'Allowed dimension orders'));
  const checks = element('div', null, 'checks');
  ORIENTATION_LABELS.forEach((label, i) => { const input = checkbox(checks, label, state.draft.design.constraints.allowed_orientations.includes(i), () => {}); input.name = 'orientation'; input.value = i; });
  orientations.append(checks); form.append(orientations);
  field(form, 'Contents declaration', 'contents', state.draft.design.constraints.contents, { options: [['unconfirmed', 'Unconfirmed'], ['ordinary_nonhazardous', 'Ordinary, non-hazardous'], ['special_handling', 'Special handling required']] });
  protectionFields(form, state.draft.design.constraints);
  form.append(element('h3', 'No-contact regions'));
  const regions = state.draft.design.constraints.no_contact || [];
  form.append(element('p', regions.length ? regions.map(regionText).join('; ') : 'No regions set.', 'metadata'));
  form.append(button('Edit no-contact regions', openNoContact, { symbol: 'cube-focus' }));
  form.append(actions); group.append(form);
}

function protectionFields(form, constraints) {
  const cushion = constraints.cushion || null, rule = constraints.package_allowance || null;
  form.append(element('h3', 'Protection kept by proposals'));
  form.append(element('p', 'Generated arrangements rebuild this foam lining in every carton, and refuse to drop existing pads without it. Leave every thickness at 0 for no requirement. Geometry only, not a cushioning-performance rating.', 'notice'));
  const pads = element('div', null, 'two-cols');
  field(pads, 'Floor cushion (mm)', 'cushion_floor', mToMm(cushion?.floor_m ?? 0), { type: 'number', min: 0, max: 200, required: true });
  field(pads, 'Top cushion (mm)', 'cushion_top', mToMm(cushion?.top_m ?? 0), { type: 'number', min: 0, max: 200, required: true });
  field(pads, 'Side cushion (mm)', 'cushion_sides', mToMm(cushion?.sides_m ?? 0), { type: 'number', min: 0, max: 200, required: true });
  form.append(pads);
  const material = element('div');
  field(material, 'Cushion material', 'cushion_material', cushion?.material.name ?? '', { maxLength: 160 });
  field(material, 'Cushion density (kg/m3)', 'cushion_density', cushion?.material.density_kg_m3 ?? '', { type: 'number', min: .000001, max: 25000 });
  field(material, 'Cushion density evidence', 'cushion_material_evidence', cushion?.material.evidence ?? '', { multiline: true, maxLength: 500 });
  form.append(material);
  if (state.capabilities.includes('material_catalog')) {
    const catalogButton = button('Cushion material catalog', async () => {
      const catalog = await working('Loading material catalog...', getCatalog);
      materialCatalogField(form, catalog.materials, 'insert', ['cushion_material', 'cushion_density', 'cushion_material_evidence'], { parent: material, name: 'cushion_catalog' });
      catalogButton.remove();
    }, { symbol: 'stack' }); form.append(catalogButton);
  }
  field(form, 'Why these thicknesses', 'cushion_evidence', cushion?.evidence ?? '', { multiline: true, maxLength: 500 });
  field(form, 'Packing allowance per package (kg)', 'allowance_rule', rule?.allowance_kg ?? '', { type: 'number', min: 0, max: 20 });
  field(form, 'Allowance evidence', 'allowance_rule_evidence', rule?.evidence ?? '', { multiline: true, maxLength: 500 });
}

export function readProtection(form) {
  const thickness = ['cushion_floor', 'cushion_top', 'cushion_sides'].map(name => mmToM(numeric(form, name)));
  let cushion = null;
  if (thickness.some(x => x > 0)) {
    const name = textValue(form, 'cushion_material'), evidence = textValue(form, 'cushion_material_evidence'), reason = textValue(form, 'cushion_evidence');
    if (!name || !evidence || !reason) throw new Error('Give the cushion material, the source of its density and why these thicknesses are required.');
    cushion = { floor_m: thickness[0], top_m: thickness[1], sides_m: thickness[2],
      material: { name, density_kg_m3: numeric(form, 'cushion_density'), evidence }, evidence: reason };
  }
  const allowance = numeric(form, 'allowance_rule', true), allowanceEvidence = textValue(form, 'allowance_rule_evidence');
  if (allowance !== null && !allowanceEvidence) throw new Error('Record what the per-package allowance includes, even when zero.');
  return { cushion, package_allowance: allowance === null ? null : { allowance_kg: allowance, evidence: allowanceEvidence } };
}

export function preservationText(preservation) {
  if (!preservation) return 'packing allowance and pads require review';
  const cushion = preservation.cushion === 'rebuilt_from_requirement' ? 'foam lining rebuilt from the cushion requirement' : 'no cushion requirement';
  const allowance = { rule: 'allowance from the design rule', carried_forward: 'allowance carried from the saved packages' }[preservation.allowance] || 'allowance unknown';
  const graphics = preservation.carton_graphics === 'not_carried' || preservation.insert_graphics_dropped ? ' | some graphics not carried' : '';
  const regions = preservation.no_contact === 'air_gap_reserved' ? ' | no-contact air gaps kept clear' : '';
  return `${cushion} | ${allowance}${regions}${graphics}`;
}

export const FACE_LABELS = { x_min: 'X min face', x_max: 'X max face', y_min: 'Y min face (bottom when upright)',
  y_max: 'Y max face (top when upright)', z_min: 'Z min face', z_max: 'Z max face' };
// The two product axes an area runs along on each face, in X, Y, Z order (u, then v).
export const FACE_AXES = { x: ['Y', 'Z'], y: ['X', 'Z'], z: ['X', 'Y'] };

// The server leaves unset optional protections out of a design; match it so an unchanged Apply is not an edit.
export function compactConstraints(constraints) {
  const next = { ...constraints };
  for (const key of ['cushion', 'package_allowance']) if (next[key] == null) delete next[key];
  if (!next.no_contact?.length) delete next.no_contact;
  return next;
}

export function regionText(region) {
  const [u, v] = FACE_AXES[region.face[0]];
  const area = region.area ? `${u} ${mToMm(region.area.u_m[0])}-${mToMm(region.area.u_m[1])} mm, ${v} ${mToMm(region.area.v_m[0])}-${mToMm(region.area.v_m[1])} mm`
    : 'whole face';
  return `${region.name}: ${FACE_LABELS[region.face]}, ${area}, air gap ${mToMm(region.air_gap_m)} mm`;
}

export function readRegion(form, existing) {
  const name = textValue(form, 'region_name'), face = textValue(form, 'region_face'), evidence = textValue(form, 'region_evidence');
  if (!name || !evidence) throw new Error('Name the region and record why it must not be touched.');
  if (!FACE_LABELS[face]) throw new Error('Choose a product face.');
  const range = ['region_u0', 'region_u1', 'region_v0', 'region_v1'].map(key => numeric(form, key, true));
  let area = null;
  if (range.some(value => value !== null)) {
    if (range.some(value => value === null)) throw new Error('Give all four area limits, or leave them all blank for the whole face.');
    const [u0, u1, v0, v1] = range.map(mmToM);
    if (u0 < 0 || v0 < 0 || u0 >= u1 || v0 >= v1) throw new Error('Each area range needs a start of 0 or more, below its end.');
    area = { u_m: [u0, u1], v_m: [v0, v1] };
  }
  const ids = new Set(existing.map(region => region.id));
  let n = existing.length + 1; while (ids.has(`nc_${n}`)) n += 1;
  return { id: `nc_${n}`, name, face, area, air_gap_m: mmToM(numeric(form, 'region_gap')), evidence };
}

function openNoContact() {
  flushEditor();
  resourceDialog('No-contact regions', body => {
    body.append(element('p', "Faces use the product's own axes, before any packing orientation. No packing material, carton wall or other product may come within a region's air gap, measured straight out from the face. Generated arrangements keep these gaps clear. Geometry only, not a protective-performance rating.", 'notice'));
    const list = element('div'); body.append(list);
    const setRegions = change => edit(d => { d.constraints = compactConstraints({ ...d.constraints, no_contact: change(d.constraints.no_contact || []) }); });
    const draw = () => {
      list.replaceChildren();
      const regions = state.draft.design.constraints.no_contact || [];
      if (!regions.length) list.append(element('p', 'No regions set.', 'notice'));
      for (const region of regions) {
        const row = element('div', null, 'document-row'), info = element('div');
        info.append(element('strong', regionText(region)), element('p', region.evidence));
        row.append(info, button(`Remove ${region.name}`, () => {
          setRegions(regions => regions.filter(item => item.id !== region.id)); render(); draw();
          notify('No-contact region removed from the draft. Save to keep the change.');
        }, { danger: true })); list.append(row);
      }
    };
    const form = element('form', null, 'form-grid'); form.append(element('h3', 'Add a region'));
    field(form, 'Region name', 'region_name', '', { maxLength: 160, required: true });
    const face = field(form, 'Product face', 'region_face', 'y_max', { options: Object.entries(FACE_LABELS) });
    field(form, 'Air gap (mm)', 'region_gap', 5, { type: 'number', min: 1, max: 200, required: true });
    const area = element('fieldset'); area.append(element('legend', 'Area on the face (optional; blank for the whole face)'));
    const axes = element('p', null, 'metadata'), spans = element('div', null, 'two-cols');
    for (const [key, label] of [['region_u0', 'First axis from (mm)'], ['region_u1', 'First axis to (mm)'], ['region_v0', 'Second axis from (mm)'], ['region_v1', 'Second axis to (mm)']]) {
      field(spans, label, key, '', { type: 'number', min: 0, max: 5000 });
    }
    const describe = () => { const [u, v] = FACE_AXES[face.value[0]]; axes.textContent = `Measured from the face's low corner: first axis ${u}, second axis ${v}.`; };
    face.addEventListener('change', describe); describe();
    area.append(axes, spans); form.append(area);
    field(form, 'Why this region must not be touched', 'region_evidence', '', { multiline: true, maxLength: 500, required: true });
    form.addEventListener('submit', event => { event.preventDefault(); invoke(() => {
      if (!form.reportValidity()) throw new Error('Check the highlighted fields.');
      const region = readRegion(form, state.draft.design.constraints.no_contact || []);
      setRegions(regions => [...regions, region]);
      for (const key of ['region_name', 'region_evidence', 'region_u0', 'region_u1', 'region_v0', 'region_v1']) form.elements.namedItem(key).value = '';
      render(); draw();
      notify('No-contact region added to the draft. Save to keep the change.');
    }); });
    form.append(button('Add region', () => form.requestSubmit(), { primary: true }));
    body.append(form); draw();
  });
}

async function importSource(file, unit) {
  flushEditor();
  const step = /\.(step|stp)$/i.test(file?.name || '');
  if (!file || (!step && !/\.glb$/i.test(file.name))) throw new Error('Choose a GLB or STEP file.');
  if (step && !state.capabilities.includes('step_import')) throw new Error('STEP import is not configured in this host.');
  if (!step && file.size > 24 * 1024 * 1024) throw new Error('GLB import is limited to 24 MiB.');
  if (state.draft.design.product && !confirm('Replace the product for every existing placement? Mass provenance will be reset.')) return;
  await working('Importing source geometry...', async () => {
    const path = step ? `/sources/step?name=${encodeURIComponent(file.name.slice(0, 160))}` : `/sources?name=${encodeURIComponent(file.name.slice(0, 160))}&meters_per_unit=${unit}`;
    const meta = await request(path, { method: 'POST', body: file, raw: true, contentType: step ? 'application/step' : 'model/gltf-binary' });
    edit(d => { d.product = productFromSource(meta, d.product || {}); });
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
  const method = field(form, 'Carton mass basis', 'tare_method', carton.board_blank ? 'blank' : 'manual', { options: [['manual', 'Entered tare'], ['blank', 'Full board blank estimate']] });
  const blank = element('fieldset', null, 'form-grid'); blank.append(element('legend', 'Full blank, including flaps and overlaps'));
  const b = carton.board_blank;
  field(blank, 'Blank width (mm)', 'blank_width', b ? mToMm(b.dimensions_m[0]) : '', { type: 'number', min: .000001, max: 5000 });
  field(blank, 'Blank length (mm)', 'blank_length', b ? mToMm(b.dimensions_m[1]) : '', { type: 'number', min: .000001, max: 5000 });
  field(blank, 'Blank quantity', 'blank_quantity', b?.quantity ?? 1, { type: 'number', min: 1, max: 20, step: 1 });
  field(blank, 'Board mass per area (kg/m2)', 'blank_basis_weight', b?.mass_per_area_kg_m2 ?? '', { type: 'number', min: .000001, max: 25 });
  field(blank, 'Blank / board evidence', 'blank_evidence', b?.evidence ?? '', { multiline: true, maxLength: 500 });
  const calculate = () => {
    const enabled = method.value === 'blank'; blank.hidden = !enabled; blank.disabled = !enabled;
    for (const input of blank.querySelectorAll('input, textarea')) input.required = enabled;
    tare.readOnly = evidence.readOnly = enabled;
    if (enabled) {
      const values = ['blank_width', 'blank_length', 'blank_quantity', 'blank_basis_weight'].map(name => Number(textValue(form, name)));
      tare.value = values.every(value => Number.isFinite(value) && value > 0) ? String(values[0] * values[1] / 1e6 * values[2] * values[3]) : '';
      evidence.value = textValue(form, 'blank_evidence');
    }
    check();
  };
  form.append(blank); method.addEventListener('change', calculate); blank.addEventListener('input', calculate); calculate();
}

function readCarton(form, original = {}) {
  const inner = readVector(form, 'inner'), outer = readVector(form, 'outer');
  if (outer.some((x, i) => x <= inner[i])) throw new Error('External dimensions must exceed internal dimensions on every axis.');
  const result = { ...clone(original), name: textValue(form, 'carton_name'), inner_m: inner, outer_m: outer, tare_kg: numeric(form, 'tare', true),
    tare_evidence: textValue(form, 'tare_evidence'), max_payload_kg: numeric(form, 'payload', true), cost_usd: numeric(form, 'carton_cost', true) };
  const method = textValue(form, 'tare_method');
  if (method === 'manual') result.board_blank = null;
  if (method === 'blank') {
    const b = { dimensions_m: [mmToM(numeric(form, 'blank_width')), mmToM(numeric(form, 'blank_length'))], quantity: numeric(form, 'blank_quantity'),
      mass_per_area_kg_m2: numeric(form, 'blank_basis_weight'), evidence: textValue(form, 'blank_evidence') };
    result.board_blank = b; result.tare_kg = b.dimensions_m[0] * b.dimensions_m[1] * b.quantity * b.mass_per_area_kg_m2; result.tare_evidence = b.evidence;
  }
  return result;
}

function renderCarton(host) {
  const p = selectedPackage();
  if (!p) { host.append(element('p', 'No carton selected.', 'notice')); return; }
  const group = section(host, 'Selected carton');
  if (state.capabilities.includes('material_catalog')) group.append(button('Carton catalog', () => openCartonCatalog(false), { symbol: 'stack' }));
  const { form, actions } = createForm(form => {
    const carton = readCarton(form, p.carton), allowance = numeric(form, 'allowance', true), evidence = textValue(form, 'allowance_evidence');
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
      density_kg_m3: numeric(form, 'density'), material_evidence: textValue(form, 'material_evidence'), cost_usd: numeric(form, 'pad_cost', true),
      minimum_wall_m: mmToM(numeric(form, 'minimum_wall')), minimum_floor_m: mmToM(numeric(form, 'minimum_floor')),
      pockets: [...form.querySelectorAll('[data-pocket-id]')].map(node => ({ id: node.dataset.pocketId,
        shape: textValue(form, `${node.dataset.pocketId}_shape`), dimensions_m: readVector(form, `${node.dataset.pocketId}_dim`),
        position_m: readVector(form, `${node.dataset.pocketId}_pos`) })) });
    else next.orientation = numeric(form, 'item_orientation');
    const destination = textValue(form, 'target_package');
    edit(d => {
      const from = d.packages.find(x => x.id === p.id), to = d.packages.find(x => x.id === destination);
      const key = isPad ? 'inserts' : 'placements';
      if (from.id !== to.id || isNew) {
        if (to[key].length >= (isPad ? 32 : 48)) throw new Error('The target package has reached its component limit.');
      }
      from[key] = from[key].filter(x => x.id !== item.id); to[key].push(next);
      if (isPad && from.id !== to.id) {
        const graphics = (from.graphics || []).filter(graphic => graphic.target_id === item.id);
        if ((to.graphics || []).length + graphics.length > 16) throw new Error('The target package has reached its graphic limit.');
        from.graphics = (from.graphics || []).filter(graphic => graphic.target_id !== item.id);
        to.graphics = [...(to.graphics || []), ...graphics];
      }
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
    if (state.capabilities.includes('material_catalog')) {
      const catalogButton = button('Material catalog', async () => {
        const catalog = await working('Loading material catalog...', getCatalog);
        materialCatalogField(form, catalog.materials, 'insert', ['material', 'density', 'material_evidence']); catalogButton.remove();
      }, { symbol: 'stack' }); form.append(catalogButton);
    }
    field(form, 'Pad cost (USD)', 'pad_cost', item.cost_usd, { type: 'number', min: 0, max: 10000 });
    if (!(item.pockets || []).length) editor.append(element('p', `Solid pad mass: ${massText(item.dimensions_m.reduce((a, b) => a * b, 1) * item.density_kg_m3)}`, 'notice'));
    else editor.append(element('p', 'Pocketed insert mass is assessed from the saved net volume.', 'notice'));
    const limits = element('div', null, 'two-cols');
    field(limits, 'Minimum wall (mm)', 'minimum_wall', mToMm(item.minimum_wall_m ?? .005), { type: 'number', min: 1, max: 200, required: true });
    field(limits, 'Minimum floor (mm)', 'minimum_floor', mToMm(item.minimum_floor_m ?? .005), { type: 'number', min: 0, max: 200, required: true }); form.append(limits);
    pocketFields(form, item);
  } else field(form, 'Orientation (dimension order)', 'item_orientation', item.orientation, { options: ORIENTATION_LABELS.map((label, i) => [String(i), label + (state.draft.design.constraints.allowed_orientations.includes(i) ? '' : ' (restricted)')]) });
  field(form, 'Package', 'target_package', p.id, { options: state.draft.design.packages.map((x, i) => [x.id, `${i + 1}. ${x.carton.name}`]) });
  if (!isNew) applyActions.append(button('Remove component', () => {
    state.formDirty = false; edit(d => {
      const box = d.packages.find(x => x.id === p.id); const key = isPad ? 'inserts' : 'placements'; box[key] = box[key].filter(x => x.id !== item.id);
      if (isPad) box.graphics = (box.graphics || []).filter(graphic => graphic.target_id !== item.id);
    });
    state.componentId = null; render();
  }, { symbol: 'trash', danger: true }));
  form.append(applyActions); editor.append(form);
}

function pocketFields(form, item) {
  const host = element('div', null, 'pocket-list'); host.append(element('h3', 'Top-opening pockets (Y+)'));
  const list = element('div', null, 'pocket-entries'); host.append(list);
  const markDirty = () => { state.formDirty = true; updateHeader(); updateFreshness(); };
  const add = button('Add pocket', () => {
    const dimensions = readVector(form, 'pad_dim'), floor = Math.max(mmToM(numeric(form, 'minimum_floor')), dimensions[1] / 2);
    append({ id: uid('pocket'), shape: 'rectangular', dimensions_m: [dimensions[0] / 2, Math.max(.000001, dimensions[1] - floor), dimensions[2] / 2],
      position_m: [dimensions[0] / 4, Math.min(floor, dimensions[1] - .000001), dimensions[2] / 4] }, true);
    markDirty();
  }, { symbol: 'rectangle', disabled: (item.pockets || []).length >= 16 });
  function append(pocket, open = false) {
    const group = element('details', null, 'pocket-entry'); group.dataset.pocketId = pocket.id; group.open = open;
    group.append(element('summary', `Pocket ${list.children.length + 1}`));
    const body = element('div', null, 'form-grid');
    const shape = field(body, 'Shape', `${pocket.id}_shape`, pocket.shape, { options: [['rectangular', 'Rectangular'], ['cylindrical', 'Cylindrical (Y axis)']] });
    vector(body, 'Pocket dimensions', `${pocket.id}_dim`, pocket.dimensions_m);
    vector(body, 'Local minimum-corner position', `${pocket.id}_pos`, pocket.position_m, { position: true });
    const x = body.querySelector(`[name="${pocket.id}_dim_0"]`), z = body.querySelector(`[name="${pocket.id}_dim_2"]`);
    const circular = () => { z.readOnly = shape.value === 'cylindrical'; if (z.readOnly) z.value = x.value; };
    shape.addEventListener('change', circular); x.addEventListener('input', circular); circular();
    body.append(button('Remove pocket', () => {
      group.remove(); add.disabled = list.children.length >= 16;
      [...list.children].forEach((node, i) => { node.querySelector('summary').textContent = `Pocket ${i + 1}`; }); markDirty();
    }, { symbol: 'trash', danger: true }));
    group.append(body); list.append(group); add.disabled = list.children.length >= 16;
  }
  for (const pocket of item.pockets || []) append(pocket);
  host.append(add); form.append(host);
}

function renderAppearance(host) {
  const pkg = selectedPackage(), product = state.draft.design.product;
  const targets = [...(product ? [['product', 'Product']] : []), ...(pkg ? [['carton', 'Selected carton'], ...pkg.inserts.map(item => [item.id, item.name])] : [])];
  if (!targets.length) { host.append(element('p', 'No product or carton selected.', 'notice')); return; }
  if (!targets.some(([id]) => id === state.appearanceTarget)) state.appearanceTarget = targets[0][0];
  const select = field(host, 'Surface', 'appearance_target', state.appearanceTarget, { options: targets });
  select.addEventListener('change', () => invoke(() => { const next = select.value; flushEditor(); state.appearanceTarget = next; renderEditor(); updatePanel(); }));
  const id = state.appearanceTarget;
  const target = id === 'product' ? product : id === 'carton' ? pkg.carton : pkg.inserts.find(item => item.id === id);
  const appearance = target.appearance || { color: '#9BA1A6', roughness: .55, metalness: 0, opacity: 1 };
  const update = (design, value) => {
    if (id === 'product') design.product.appearance = value;
    else {
      const box = design.packages.find(item => item.id === pkg.id);
      (id === 'carton' ? box.carton : box.inserts.find(item => item.id === id)).appearance = value;
    }
  };
  const group = section(host, 'Surface appearance');
  const { form, actions } = createForm(form => {
    edit(design => update(design, { color: textValue(form, 'appearance_color'), roughness: numeric(form, 'appearance_roughness'),
      metalness: numeric(form, 'appearance_metalness'), opacity: numeric(form, 'appearance_opacity') }));
    setDisplayMode('appearance');
  }, 'Apply appearance');
  field(form, 'Color', 'appearance_color', appearance.color, { type: 'color' });
  for (const [key, label, min] of [['roughness', 'Roughness', 0], ['metalness', 'Metalness', 0], ['opacity', 'Opacity', .05]]) {
    const input = field(form, label, `appearance_${key}`, appearance[key], { type: 'range', min, max: 1, step: .05 });
    const output = element('output', String(appearance[key])); input.parentElement.append(output); input.addEventListener('input', () => { output.value = input.value; });
  }
  actions.append(button('Reset appearance', () => { state.formDirty = false; edit(design => update(design, null)); render(); }, { symbol: 'arrow-clockwise' }));
  form.append(actions); group.append(form);
}

function renderGraphics(host) {
  const pkg = selectedPackage();
  if (!pkg) { host.append(element('p', 'No carton selected.', 'notice')); return; }
  const graphics = pkg.graphics || [], list = section(host, 'Surface graphics');
  list.append(button('Add lettering', () => { flushEditor(); state.graphicId = 'new_graphic'; renderEditor(); updatePanel(); }, { symbol: 'rectangle', disabled: graphics.length >= 16 }));
  if (state.capabilities.includes('surface_graphics')) {
    const upload = element('form', null, 'form-grid'); upload.addEventListener('submit', event => event.preventDefault());
    const file = field(upload, 'Image artwork', 'graphic_file', '', { type: 'file', accept: '.png,.jpg,.jpeg,image/png,image/jpeg', required: true });
    upload.append(button('Add image', async () => {
      if (!upload.reportValidity()) return;
      flushEditor(); const image = file.files[0];
      if (!image || !/\.(png|jpe?g)$/i.test(image.name) || image.size > 10 * 1024 * 1024) throw new Error('Choose a PNG or JPEG image up to 10 MiB.');
      const metadata = await working('Importing image artwork...', () => request('/images', { method: 'POST', body: image, raw: true, contentType: /\.png$/i.test(image.name) ? 'image/png' : 'image/jpeg' }));
      const id = uid('graphic'); edit(d => {
        const box = d.packages.find(item => item.id === pkg.id);
        box.graphics = [...(box.graphics || []), { id, target: 'carton', target_id: null, face: 'y+', kind: 'image', text: '', image_id: metadata.id,
          color: '#17191C', u: .5, v: .5, width_fraction: .7, height_fraction: .3, rotation_degrees: 0 }];
      });
      state.graphicId = id; setDisplayMode('appearance'); render(); notify('Image added to draft.');
    }, { symbol: 'file-export', disabled: graphics.length >= 16 })); list.append(upload);
  }
  const entries = element('div', null, 'item-list');
  for (const graphic of graphics) {
    const b = button(graphic.kind === 'text' ? graphic.text.slice(0, 60) : 'Image graphic', () => { flushEditor(); state.graphicId = graphic.id; renderEditor(); updatePanel(); });
    b.setAttribute('aria-pressed', String(state.graphicId === graphic.id)); entries.append(b);
  }
  if (!graphics.length) entries.append(element('p', 'No surface graphics.', 'notice')); list.append(entries);
  const isNew = state.graphicId === 'new_graphic';
  const graphic = isNew ? { id: uid('graphic'), target: 'carton', target_id: null, face: 'y+', kind: 'text', text: '', image_id: null,
    color: '#17191C', u: .5, v: .5, width_fraction: .7, height_fraction: .3, rotation_degrees: 0 } : graphics.find(item => item.id === state.graphicId);
  if (!graphic) return;
  const group = section(host, isNew ? 'New lettering' : 'Graphic properties');
  const { form, actions } = createForm(form => {
    const target = textValue(form, 'graphic_target');
    const next = { ...clone(graphic), target: target === 'carton' ? 'carton' : 'insert', target_id: target === 'carton' ? null : target,
      face: textValue(form, 'graphic_face'), text: graphic.kind === 'text' ? textValue(form, 'graphic_text') : '',
      color: textValue(form, 'graphic_color'), u: numeric(form, 'graphic_u') / 100, v: numeric(form, 'graphic_v') / 100,
      width_fraction: numeric(form, 'graphic_width') / 100, height_fraction: numeric(form, 'graphic_height') / 100,
      rotation_degrees: numeric(form, 'graphic_rotation') };
    if (next.u - next.width_fraction / 2 < -1e-9 || next.u + next.width_fraction / 2 > 1 + 1e-9
      || next.v - next.height_fraction / 2 < -1e-9 || next.v + next.height_fraction / 2 > 1 + 1e-9) throw new Error('Keep the graphic fit region within the face.');
    edit(design => {
      const box = design.packages.find(item => item.id === pkg.id);
      box.graphics = [...(box.graphics || []).filter(item => item.id !== next.id), next];
    });
    state.graphicId = next.id; setDisplayMode('appearance');
  }, isNew ? 'Add lettering' : 'Apply graphic');
  field(form, 'Target surface', 'graphic_target', graphic.target === 'carton' ? 'carton' : graphic.target_id,
    { options: [['carton', 'Carton exterior'], ...pkg.inserts.map(item => [item.id, item.name])] });
  field(form, 'Face', 'graphic_face', graphic.face, { options: [['y+', 'Top (Y+)'], ['y-', 'Bottom (Y-)'], ['x+', 'Right (X+)'], ['x-', 'Left (X-)'], ['z+', 'Front (Z+)'], ['z-', 'Back (Z-)']] });
  if (graphic.kind === 'text') field(form, 'Lettering', 'graphic_text', graphic.text, { multiline: true, required: true, maxLength: 500 });
  else group.append(element('p', `Image: ${graphic.image_id}`, 'metadata'));
  const color = field(form, 'Color', 'graphic_color', graphic.color, { type: 'color' });
  color.parentElement.hidden = graphic.kind !== 'text';
  const region = element('div', null, 'two-cols');
  for (const [key, label, value, min] of [['u', 'Horizontal center (%)', graphic.u, 0], ['v', 'Vertical center (%)', graphic.v, 0],
    ['width', 'Fit width (%)', graphic.width_fraction, .1], ['height', 'Fit height (%)', graphic.height_fraction, .1]]) {
    field(region, label, `graphic_${key}`, value * 100, { type: 'number', min, max: 100, required: true });
  }
  form.append(region);
  field(form, 'Rotation', 'graphic_rotation', graphic.rotation_degrees, { options: [[0, '0 degrees'], [90, '90 degrees'], [180, '180 degrees'], [270, '270 degrees']] });
  if (!isNew) actions.append(button('Remove graphic', () => {
    state.formDirty = false; edit(design => { const box = design.packages.find(item => item.id === pkg.id); box.graphics = box.graphics.filter(item => item.id !== graphic.id); });
    state.graphicId = null; render();
  }, { symbol: 'trash', danger: true }));
  form.append(actions); group.append(form);
}

function renderArrange(host) {
  if (state.capabilities.includes('saved_alternatives')) host.append(button('Saved designs', openAlternatives, { symbol: 'stack', disabled: !state.draft.document }));
  const group = section(host, 'Carton alternatives');
  if (state.capabilities.includes('material_catalog')) group.append(button('Carton catalog', () => openCartonCatalog(true), { symbol: 'stack' }));
  const select = field(group, 'Alternative', 'alternative', state.alternativeIndex, { options: state.alternatives.map((c, i) => [String(i), `${i + 1}. ${c.name}`]) });
  select.addEventListener('change', () => invoke(() => { flushEditor(); state.alternativeIndex = Number(select.value); renderEditor(); updateHeader(); }));
  const toolbar = element('div', null, 'actions');
  toolbar.append(button('Add alternative', () => { flushEditor(); state.alternatives.push(defaultCarton()); state.alternativeIndex = state.alternatives.length - 1; state.candidates = null; renderEditor(); updateHeader(); }, { symbol: 'copy', disabled: state.alternatives.length >= 6 }),
    button('Use selected carton', () => { flushEditor(); state.alternatives[state.alternativeIndex] = clone(selectedPackage().carton); state.candidates = null; renderEditor(); updateHeader(); }, { symbol: 'cube', disabled: !selectedPackage() }),
    button('Remove alternative', () => { state.formDirty = false; state.alternatives.splice(state.alternativeIndex, 1); state.alternativeIndex = 0; state.candidates = null; renderEditor(); updateHeader(); }, { symbol: 'trash', compact: true, disabled: state.alternatives.length <= 1 }));
  group.append(toolbar);
  const { form, actions } = createForm(form => {
    state.alternatives[state.alternativeIndex] = readCarton(form, state.alternatives[state.alternativeIndex]); state.maxPackages = numeric(form, 'max_packages'); state.candidates = null;
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
      element('p', `${candidate.assessment.findings.filter(f => f.severity === 'error').length} validation errors | ${preservationText(state.candidates.preservation)}`, 'notice'),
      button('Apply candidate', () => {
        flushEditor();
        if (!state.candidates || hasDraft() || state.candidateRevision !== state.draft.document?.revision || state.candidateConfig !== JSON.stringify([state.alternatives, state.maxPackages])) throw new Error('Save changes and regenerate candidates first.');
        if (!confirm('Replace all package arrangements, pads, graphics and allowances with this candidate? This change can be undone.')) return;
        edit(d => { d.packages = clone(candidate.design.packages); });
        state.componentId = null; state.packageId = null; state.editor = 'carton'; state.panel = 'carton'; render(); state.scene?.fit(); notify('Candidate applied to draft. Review packing materials before saving.');
      }, { disabled: stale, primary: true }));
    results.append(row);
  });
  if (state.candidates.notice) results.append(element('p', state.candidates.notice, 'notice'));
}

async function openCartonCatalog(forArrangement) {
  flushEditor();
  const catalog = await working('Loading carton catalog...', getCatalog);
  resourceDialog('Carton catalog', (body, dialog) => {
    body.append(element('p', catalog.notice || '', 'notice'));
    for (const entry of catalog.cartons) {
      const carton = entry.carton, row = element('div', null, 'document-row'), info = element('div');
      info.append(element('strong', carton.name), element('p', `Internal ${dimensionText(carton.inner_m)} | External ${dimensionText(carton.outer_m)}`),
        element('p', `${massText(carton.tare_kg)} tare | Payload ${massText(carton.max_payload_kg)}`), element('p', carton.tare_evidence, 'metadata'));
      row.append(info, button('Use carton', () => {
        if (forArrangement) { state.alternatives[state.alternativeIndex] = clone(carton); state.candidates = null; }
        else {
          if (!confirm('Replace the selected carton? Existing contents remain at their current positions.')) return;
          edit(d => { d.packages.find(item => item.id === state.packageId).carton = clone(carton); });
        }
        dialog.close(); render();
      })); body.append(row);
    }
  });
}

async function setBaseline(ref) {
  const result = await working('Saving the comparison baseline...', () => request(`${docPath()}/comparison/baseline`, { method: 'PUT', body: { baseline: ref } }));
  notify(ref === 'current' ? 'The current design is the comparison baseline.' : 'Saved design set as the comparison baseline.');
  return result.baseline;
}

async function quoteSavedDesign(alternative) {
  state.addresses = captureAddresses(); state.quoteOptions = captureQuoteOptions();
  if (!state.provider?.configured) throw new Error('Carrier provider is not configured. No rates are available.');
  if (!scenarioComplete(state.addresses)) throw new Error('Enter the origin and destinations in Rates first. Saved designs are quoted under the same scenario as the current design.');
  if (!alternative.assessment.rate_ready) throw new Error('This saved design has validation errors and cannot be rated.');
  const shipments = alternative.design.packages.length * state.addresses.destinations.length;
  if (!confirm(`Request rates for "${alternative.name}"? Unless this exact scenario was already priced, this creates ${shipments} provider shipment(s) for rating, which can be billed for a production account. No postage is purchased.`)) return;
  const result = await working('Requesting carrier estimates for the saved design...', () => request(`${docPath()}/alternatives/${encodeURIComponent(alternative.id)}/quotes`, {
    method: 'POST', body: quoteBody(state.draft.document.revision, state.addresses, state.quoteAccounts, state.quoteOptions, false) }));
  await loadQuoteAttempts();
  notify(result.reused ? 'This saved design was already priced for this scenario. No provider request was made.'
    : `Carrier quote received for the saved design (${result.provider_shipments_created ?? 0} provider shipment(s) created). No postage was purchased.`);
}

async function openComparison() {
  flushEditor();
  if (!state.draft.document || hasDraft()) throw new Error('Save the document before comparing costs.');
  const base = `${docPath()}/comparison`;
  const listing = await working('Loading saved quotes...', () => request(base));
  resourceDialog('Compare costs', body => {
    body.append(element('p', 'Reads saved quotes only. No provider request is made.', 'metadata'));
    if (!listing.scenarios.length) {
      body.append(element('p', 'No comparable quotes yet. Quote the current design in Rates, then quote saved designs under the same scenario.', 'notice'));
      return;
    }
    const form = element('form', null, 'form-grid'); form.addEventListener('submit', event => event.preventDefault());
    const scenario = field(form, 'Scenario', 'comparison_scenario', listing.scenarios[0].scenario_hash,
      { options: listing.scenarios.map(item => [item.scenario_hash, scenarioLabel(item)]) });
    const services = element('div'), results = element('div');
    form.append(services); body.append(form, results);
    let chosen = null;
    const key = item => JSON.stringify([item.carrier, item.service, item.account_id, item.currency]);
    const draw = comparison => {
      services.replaceChildren(); results.replaceChildren();
      if (comparison.services.length) {
        const select = field(services, 'Service (the same for every design)', 'comparison_service', comparison.service ? key(comparison.service) : '',
          { options: comparison.services.map(item => [key(item), `${item.carrier} ${item.service} | ${rateAccountLabel(item)} | baseline ${item.currency} ${item.baseline_amount}`]) });
        select.addEventListener('change', () => { const [carrier, service, account_id, currency] = JSON.parse(select.value); chosen = { carrier, service, account_id, currency }; invoke(load); });
      }
      const ready = comparison.baseline.ready;
      results.append(element('p', `Baseline: ${comparison.baseline.name}${ready ? '' : ' - cannot be compared: ' + comparison.baseline.reasons.map(code => comparison.reasons[code] || code).join(' ')}`, ready ? 'metadata' : 'warning'));
      const wrap = element('div', null, 'rate-table-wrap'), table = element('table', null, 'comparison-table'); table.setAttribute('aria-label', 'Design cost comparison');
      const head = element('thead'), hr = element('tr');
      for (const title of ['Design', 'Status', 'Packages', 'Gross', 'Shipping', 'Materials', 'Known total', 'Shipping vs baseline', 'Notes']) {
        const th = element('th', title); th.scope = 'col'; hr.append(th);
      }
      head.append(hr); const rows = element('tbody');
      for (const row of comparisonOrder(comparison)) {
        const tr = element('tr');
        comparisonCells(row, comparison).forEach((text, i) => tr.append(element('td', text, i === 8 ? 'notes' : i >= 1 ? 'rate-amount' : '')));
        rows.append(tr);
      }
      table.append(head, rows); wrap.append(table); results.append(wrap);
      for (const [code, text] of Object.entries(comparison.caveats)) results.append(element('p', `${CAVEAT_LABELS[code] || code}: ${text}`, 'metadata'));
      if (comparison.savings_claimed) {
        const claims = comparison.rows.filter(row => row.claim);
        if (!claims.length) results.append(element('p', 'No compared design is cheaper than the baseline for this service.', 'notice'));
        for (const row of claims) results.append(element('p', row.claim.text, 'notice'));
      } else results.append(element('p', 'No saving is claimed: savings are stated only for production-mode quotes against a ready baseline.', 'warning'));
      results.append(element('p', comparison.notice, 'notice'));
    };
    const load = async () => {
      const params = new URLSearchParams({ scenario_hash: scenario.value });
      if (chosen) for (const [name, value] of Object.entries(chosen)) params.set(name, value);
      const data = await working('Comparing saved quotes...', () => request(`${base}?${params}`));
      draw(data.comparison);
      notify(`Compared ${data.comparison.rows.length} designs from saved quotes. No provider request was made.`);
    };
    scenario.addEventListener('change', () => { chosen = null; invoke(load); });
    invoke(load);
  }, { wide: true });
}

async function openAlternatives() {
  flushEditor();
  if (!state.draft.document || hasDraft()) throw new Error('Save the document before opening saved designs.');
  const path = `${docPath()}/alternatives`, revision = state.draft.document.revision;
  const [data, compared] = await working('Loading saved designs...', () => Promise.all([request(path), request(`${docPath()}/comparison`).catch(() => null)]));
  let baseline = compared?.baseline?.baseline || 'current';
  resourceDialog('Saved designs', (body, dialog) => {
    const form = element('form', null, 'form-grid'); form.addEventListener('submit', event => event.preventDefault());
    field(form, 'Snapshot name', 'alternative_name', '', { required: true, maxLength: 160 });
    form.append(button('Save snapshot', async () => {
      if (!form.reportValidity()) return;
      const name = textValue(form, 'alternative_name'), fingerprint = JSON.stringify([path, revision, name]);
      if (state.alternativeReceipt?.fingerprint !== fingerprint) state.alternativeReceipt = { fingerprint, id: uid('snapshot') };
      const saved = await working('Saving immutable design snapshot...', () => request(path, { method: 'POST', body: {
        expected_revision: revision, request_id: state.alternativeReceipt.id, name
      } }));
      state.alternativeReceipt = null; if (!data.alternatives.some(item => item.id === saved.id)) data.alternatives.push(saved);
      form.reset(); draw(); notify('Design snapshot saved.');
    }, { primary: true })); body.append(form);
    const tools = element('div', null, 'actions'), baselineText = element('p', null, 'metadata');
    tools.append(button('Compare costs', () => { dialog.close(); return openComparison(); }, { symbol: 'stack' }),
      button('Use current design as baseline', async () => { baseline = await setBaseline('current'); draw(); }));
    body.append(tools, baselineText);
    const list = element('div'); body.append(list);
    const draw = () => {
      list.replaceChildren();
      const named = data.alternatives.find(item => item.id === baseline);
      baselineText.textContent = `Comparison baseline: ${named ? named.name : 'current design'}`;
      if (!data.alternatives.length) list.append(element('p', 'No saved design snapshots.', 'notice'));
      for (const alternative of data.alternatives) {
        const row = element('div', null, 'document-row'), info = element('div'), c = alternative.comparison;
        info.append(element('strong', alternative.name), element('p', `Revision ${alternative.base_revision} | ${c.carton_count} cartons | ${massText(c.total_gross_kg)} gross`),
          element('p', `${numberText(c.outer_volume_m3 * 1000)} L exterior | Materials ${c.materials_cost_usd == null ? 'unknown' : 'USD ' + numberText(c.materials_cost_usd, 2)}${alternative.id === baseline ? ' | Baseline' : ''}`, 'notice'),
          element('p', `${alternative.assessment.status} | ${alternative.assessment.findings.length} findings`, 'notice'));
        row.append(info, button('Apply saved design', async () => {
          if (hasDraft() || state.draft.document.revision !== revision) throw new Error('Document changed. Reopen saved designs after saving or reloading.');
          if (!confirm('Replace the full document with this saved design? The saved edit can be undone.')) return;
          edit(d => Object.assign(d, clone(alternative.design))); state.componentId = null; state.graphicId = null;
          state.candidates = null; dialog.close(); await saveDocument(); state.scene?.fit();
        }), button('Quote this design', () => quoteSavedDesign(alternative), { symbol: 'arrow-clockwise', disabled: !alternative.assessment.rate_ready }),
        button('Set as baseline', async () => { baseline = await setBaseline(alternative.id); draw(); }, { disabled: alternative.id === baseline })); list.append(row);
      }
    }; draw();
  });
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
        state.editor = state.componentId ? 'contents' : 'carton'; state.panel = state.editor; render(); state.scene?.fit();
      }
    }));
    list.append(row);
  }); findings.append(list);
  renderEvidence(host);
}

async function newDocument() {
  if (hasNavigationChanges() && !confirm('Discard unsaved document changes and session-only addresses, and start a new document?')) return;
  state.draft.reset(); state.formDirty = false; resetDocumentState(); state.panel = 'product'; render(); renderRates(); notify('New packaging document.');
}

function resetDocumentState() {
  state.conflict = false;
  state.packageId = null; state.componentId = null; state.candidates = null; state.candidateRevision = null;
  state.alternatives = [defaultCarton()]; state.alternativeIndex = 0; state.maxPackages = 3; state.candidateConfig = null;
  state.quotes = []; state.quoteIndex = 0; state.quoteScenario = null; state.quoteError = ''; state.mutationReceipt = null;
  state.quoteAccounts = []; state.quoteOptions = { delivery_confirmation: null, saturday_delivery: false }; state.quoteAttempts = null;
  state.scenarios = []; state.evidence = []; state.evidenceNotice = '';
  state.addresses = { origin: blankAddress(), destinations: [blankAddress()] }; state.editor = 'product'; state.review = 'validation';
  state.panel = null;
  state.graphicId = null; state.appearanceTarget = 'product';
  state.alternativeReceipt = null;
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
    if (!state.draft.document) {
      const fingerprint = JSON.stringify({ create: state.draft.design });
      if (state.mutationReceipt?.fingerprint !== fingerprint) state.mutationReceipt = { fingerprint, id: uid('create') };
      result = await request('/documents', { method: 'POST', body: state.draft.design, idempotencyKey: state.mutationReceipt.id });
    }
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
    notify('PDF export requested.');
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

function captureQuoteOptions() {
  if (!state.quoteForm) return state.quoteOptions;
  return { delivery_confirmation: textValue(state.quoteForm, 'delivery_confirmation') || null,
    saturday_delivery: state.quoteForm.elements.namedItem('saturday_delivery')?.checked === true };
}

const quoteScenarioValue = () => JSON.stringify([captureAddresses(), state.quoteAccounts, captureQuoteOptions()]);

async function openCarrierAccounts() {
  if (!confirm('List the carrier accounts enabled for this EasyPost key? This contacts EasyPost but creates no shipment, and needs a production key.')) return;
  state.addresses = captureAddresses(); state.quoteOptions = captureQuoteOptions();
  const data = await working('Listing carrier accounts...', () => request('/account/carrier-accounts', { method: 'POST', body: {} }));
  resourceDialog('Carrier accounts', (body, dialog) => {
    body.append(element('p', data.notice || '', 'notice'));
    if (!data.carrier_accounts.length) body.append(element('p', 'No carrier accounts were listed.', 'warning'));
    const form = element('form', null, 'form-grid'); form.addEventListener('submit', event => event.preventDefault());
    const checks = data.carrier_accounts.map(account => {
      const input = checkbox(form, `${account.readable || account.type || 'Carrier'} | ${account.description || account.reference || account.id}`, state.quoteAccounts.includes(account.id), () => {});
      input.value = account.id; return input;
    });
    const actions = element('div', null, 'actions');
    actions.append(button('Rate selected accounts', () => { state.quoteAccounts = checks.filter(c => c.checked).map(c => c.value); dialog.close(); renderRates(); }, { primary: true }),
      button('Rate all enabled accounts', () => { state.quoteAccounts = []; dialog.close(); renderRates(); }));
    form.append(actions); body.append(form);
  });
}

async function loadQuoteAttempts() {
  try { state.quoteAttempts = await request(`${docPath()}/quote-attempts`); }
  catch { state.quoteAttempts = null; }
}

function renderRates() {
  const host = $('rates-panel'); host.replaceChildren();
  const provider = section(host, 'Rate provider');
  provider.append(element('p', state.providerError || `${state.provider?.provider || 'Provider'} | ${state.provider?.configured ? 'Configured' : 'Not configured'}`, state.provider?.configured ? 'notice' : 'warning'));
  provider.append(element('p', providerNotice(state.provider), 'notice'), button('Refresh provider status', refreshProvider, { symbol: 'arrow-clockwise' }));
  if (state.provider?.secure_store_enabled) provider.append(button('Carrier account', openCarrierAccount, { symbol: 'cube' }));
  if (state.provider?.account_alias) provider.append(element('p', `${state.provider.account_alias} | ${state.provider.validation || 'Not validated'}`, 'metadata'));
  if (state.quoteRules) {
    const rules = element('details'); rules.append(element('summary', 'Quote rules and provider fees'));
    for (const text of [state.quoteRules.ship_date, ...Object.values(state.quoteRules.destinations || {}), state.quoteRules.fees]) rules.append(element('p', text, 'notice'));
    provider.append(rules);
  }
  if (state.capabilities.includes('cost_comparison') && state.draft.document) provider.append(button('Compare costs', openComparison, { symbol: 'stack' }));
  if (state.capabilities.includes('carrier_account_discovery') && state.provider?.configured) {
    provider.append(button('Carrier accounts', openCarrierAccounts, { symbol: 'stack' }));
  }
  provider.append(element('p', state.quoteAccounts.length ? `Rating ${state.quoteAccounts.length} selected carrier account(s): ${state.quoteAccounts.join(', ')}` : 'Rating every carrier account enabled for this key.', 'metadata'));
  const form = element('form', null, 'form-grid'); state.quoteForm = form;
  addressFields(form, 'Origin', 'origin', state.addresses.origin);
  state.addresses.destinations.forEach((address, i) => addressFields(form, `Destination ${i + 1}`, `destination${i}`, address));
  const actions = element('div', null, 'actions');
  actions.append(button('Add destination', () => { state.addresses = captureAddresses(); state.addresses.destinations.push(blankAddress()); renderRates(); }, { disabled: state.addresses.destinations.length >= 3 }),
    button('Remove last destination', () => { state.addresses = captureAddresses(); state.addresses.destinations.pop(); renderRates(); }, { symbol: 'trash', compact: true, disabled: state.addresses.destinations.length <= 1 }));
  form.append(actions);
  const options = element('fieldset'); options.append(element('legend', 'Shipment options'));
  field(options, 'Delivery confirmation', 'delivery_confirmation', state.quoteOptions.delivery_confirmation || '',
    { options: [['', 'Carrier default'], ['NO_SIGNATURE', 'No signature'], ['SIGNATURE', 'Signature'], ['ADULT_SIGNATURE', 'Adult signature']] });
  const saturday = checkbox(options, 'Saturday delivery', state.quoteOptions.saturday_delivery, () => {}); saturday.name = 'saturday_delivery';
  form.append(options);
  form.append(element('p', 'Compare rates shows the saved quote when this exact scenario was already priced. Otherwise each package and destination creates one provider shipment for rating; production rating can be billed (see Quote rules). No postage is purchased.', 'metadata'));
  const quoteButton = button('Compare rates', () => requestQuotes(false), { primary: true }); quoteButton.id = 'quote-button'; form.append(quoteButton);
  const refreshButton = button('Refresh rates', () => requestQuotes(true), { symbol: 'arrow-clockwise' }); refreshButton.id = 'quote-refresh-button'; form.append(refreshButton);
  form.addEventListener('submit', event => { event.preventDefault(); invoke(() => requestQuotes(false)); });
  const addressChanged = () => { updateHeader(); updateFreshness(); };
  form.addEventListener('input', addressChanged); form.addEventListener('change', addressChanged); host.append(form);
  if (sageQuoting() && state.draft.document) renderScenarios(host);
  host.append(element('div', null, 'review-section')); host.lastChild.id = 'quote-results'; renderQuoteResults(); updateHeader();
}

const sageQuoting = () => state.capabilities.includes('sage_quote_scenarios') && state.capabilities.includes('sage_chat_execution');

async function loadScenarios() {
  if (!sageQuoting() || !state.draft.document) { state.scenarios = []; return; }
  try { state.scenarios = (await request(`${docPath()}/scenarios`)).scenarios; }
  catch { state.scenarios = null; }
}

function renderScenarios(host) {
  const box = element('div', null, 'review-section'); box.id = 'sage-scenarios';
  box.append(element('h3', 'Sage quoting'));
  box.append(element('p', 'Sage can request rates for these addresses only after you allow it here. Sage sees a scenario ID with city, state and residential status, never names, streets or ZIP codes. The addresses stay in server memory for this session only.', 'notice'));
  if (state.scenarios === null) box.append(element('p', 'Sage quote scenarios could not be loaded.', 'warning'));
  for (const s of state.scenarios || []) {
    const row = element('div', null, 'actions');
    row.append(element('p', `${s.id}: ${s.origin} to ${s.destinations.join('; ')} | ${s.shipments_remaining} of ${s.sage_shipments} provider shipment(s) left | expires in ${Math.ceil(s.expires_in_s / 60)} min`, 'metadata'),
      button(`Revoke ${s.id}`, () => revokeScenario(s.id), { symbol: 'trash', compact: true }));
    box.append(row);
  }
  const actions = element('div', null, 'actions');
  actions.append(button('Allow Sage to quote these addresses', openSageScenario, { symbol: 'lock-simple', disabled: hasDraft() }),
    button('Refresh quotes and Sage scenarios', async () => {
      await working('Refreshing quotes...', loadQuotes); state.addresses = captureAddresses(); renderRates();
      notify('Saved quotes and Sage scenarios refreshed. No provider request was made.');
    }, { symbol: 'arrow-clockwise', compact: true }));
  box.append(actions); host.append(box);
}

async function openSageScenario() {
  if (!state.quoteForm.reportValidity()) return;
  flushEditor();
  if (!state.draft.document || state.draft.dirty) { render(); throw new Error('Save the document before allowing Sage to quote.'); }
  if (!state.provider?.configured) throw new Error('Carrier provider is not configured. Sage cannot request rates.');
  state.addresses = captureAddresses(); state.quoteOptions = captureQuoteOptions();
  const addresses = state.addresses, accounts = [...state.quoteAccounts], options = { ...state.quoteOptions };
  const perQuote = state.draft.document.design.packages.length * addresses.destinations.length;
  resourceDialog('Allow Sage to quote', (body, dialog) => {
    body.append(element('p', 'Sage will see only:', 'metadata'));
    const seen = element('ul'); seen.append(element('li', `Origin: ${sagePlace(addresses.origin)}`));
    addresses.destinations.forEach((d, i) => seen.append(element('li', `Destination ${i + 1}: ${sagePlace(d)}`)));
    body.append(seen, element('p', `Each new quote sends these full addresses and the saved package to the carrier provider and creates ${perQuote} provider shipment(s) for rating, one per package and destination. Production rating can be billed (see Quote rules). A saved quote for the same design and scenario is reused without a new request. Sage cannot buy postage or labels.`, 'notice'));
    const form = element('form', null, 'form-grid'); form.addEventListener('submit', event => event.preventDefault());
    const budget = field(form, 'Provider shipments Sage may create', 'sage_shipments', String(Math.min(12, Math.max(1, perQuote))), { type: 'number', min: 1, max: 12, step: 1, required: true });
    const minutes = field(form, 'Allow for minutes', 'sage_minutes', '60', { type: 'number', min: 5, max: 240, step: 1, required: true });
    const failure = element('p', '', 'error'); failure.setAttribute('role', 'alert');
    const actions = element('div', null, 'actions');
    actions.append(button('Allow Sage', async () => {
      if (!form.reportValidity()) return;
      failure.textContent = '';
      try {
        const created = await working('Authorizing Sage quotes...', () => request(`${docPath()}/scenarios`, { method: 'POST',
          body: scenarioBody(addresses, accounts, options, Number(budget.value), Number(minutes.value)) }));
        dialog.close(); await loadScenarios(); renderRates();
        notify(`Sage may quote scenario ${created.id}: up to ${created.sage_shipments} provider shipment(s) for ${Math.round(created.expires_in_s / 60)} min. Nothing was sent yet.`);
      } catch (error) { failure.textContent = error.message; }
    }, { primary: true }), button('Cancel', () => dialog.close()));
    form.append(actions, failure); body.append(form);
  });
}

async function revokeScenario(id) {
  await working('Revoking Sage quote scenario...', () => request(`${docPath()}/scenarios/${encodeURIComponent(id)}`, { method: 'DELETE' }));
  await loadScenarios(); state.addresses = captureAddresses(); renderRates(); notify(`Sage can no longer quote scenario ${id}.`);
}

async function refreshProvider() {
  await working('Checking carrier provider...', async () => {
    try { const data = await request('/status'); state.provider = data.rating; state.capabilities = data.capabilities || []; state.quoteRules = data.quote_rules || null; state.providerError = ''; notify('Provider status updated.'); }
    catch (error) { state.provider = null; state.providerError = `Provider status unavailable: ${error.message}`; throw error; }
    finally { state.addresses = captureAddresses(); }
  }).finally(() => {
    renderRates();
    if (!state.formDirty && ![...$('editor').querySelectorAll('input[type="file"]')].some(input => input.files?.length)) renderEditor();
  });
}

async function openCarrierAccount() {
  const account = await working('Loading carrier account status...', () => request('/account'));
  resourceDialog('Carrier account', (body, dialog) => {
    body.append(element('p', `${account.account_alias || 'No account'} | ${account.validation || 'Not validated'}`, 'metadata'));
    const form = element('form', null, 'form-grid'); form.autocomplete = 'off'; form.addEventListener('submit', event => event.preventDefault());
    const alias = field(form, 'Account alias', 'carrier_alias', account.account_alias || '', { required: true, maxLength: 80 });
    const secret = field(form, 'EasyPost API key', 'carrier_key', '', { type: 'password', required: true, maxLength: 4096 }); secret.autocomplete = 'new-password';
    secret.spellcheck = false; alias.autocomplete = 'off';
    const failure = element('p', '', 'error'); failure.setAttribute('role', 'alert');
    const actions = element('div', null, 'actions');
    actions.append(button('Save account', async () => {
      if (!form.reportValidity()) return;
      const body = { api_key: secret.value, account_alias: alias.value.trim() }; secret.value = ''; failure.textContent = '';
      try {
        state.provider = await working('Updating carrier account...', () => request('/account', { method: 'PUT', body }));
        state.quoteScenario = null; dialog.close(); state.addresses = captureAddresses(); renderRates(); notify('Carrier account saved. No rate request was made.');
      } catch { failure.textContent = 'Carrier account could not be saved. Check the key, alias and secure-store availability.'; }
      finally { body.api_key = ''; secret.value = ''; }
    }, { primary: true }), button('Remove account', async () => {
      if (!confirm('Remove the configured carrier account for future requests?')) return;
      secret.value = ''; failure.textContent = '';
      try {
        state.provider = await working('Removing carrier account...', () => request('/account', { method: 'DELETE' }));
        state.quoteScenario = null; dialog.close(); state.addresses = captureAddresses(); renderRates(); notify('Carrier account removed.');
      } catch { failure.textContent = 'Carrier account could not be removed. Check secure-store availability.'; }
    }, { symbol: 'trash', danger: true, disabled: !account.configured }));
    form.append(actions, failure); body.append(form);
  });
}

async function loadQuotes() {
  try { const data = await request(`${docPath()}/quotes`); state.quotes = data.quotes; state.quoteIndex = 0; }
  catch (error) { state.quoteError = `Quote history unavailable: ${error.message}`; }
  await loadQuoteAttempts(); await loadScenarios(); await loadEvidence();
}

async function loadEvidence() {
  if (!state.draft.document || !state.capabilities.includes('research_evidence')) { state.evidence = []; return; }
  try { const data = await request(`${docPath()}/evidence`); state.evidence = data.evidence; state.evidenceNotice = data.notice; }
  catch { state.evidence = null; }
}

function renderEvidence(host) {
  const records = state.evidence;
  if (!(records === null || records?.length || state.capabilities.includes('sage_chat_execution'))) return;
  const group = section(host, `Research evidence (${records?.length ?? 0})`); group.id = 'research-evidence';
  group.append(element('p', state.evidenceNotice || 'Public-source evidence recorded by Sage is unreviewed until you accept it.', 'notice'));
  if (records === null) { group.append(element('p', 'Research evidence could not be loaded.', 'warning')); return; }
  if (!records.length) { group.append(element('p', 'No research evidence recorded. Ask Sage to research carton sizes, material densities or cushioning guidance; it records the sources it reads here.', 'notice')); return; }
  const list = element('ul', null, 'findings');
  records.forEach((record, index) => {
    const n = index + 1, row = element('li', null, `finding evidence ${record.review_status}`);
    row.append(element('strong', `${n}. ${EVIDENCE_KINDS[record.kind] || 'Evidence'}: ${record.subject}`), element('p', `Claim: ${record.claim}`));
    row.append(element('p', evidenceFacts(record).join(' | '), 'metadata'));
    const href = evidenceLink(record.source?.url), source = element('p', null, 'metadata');
    const link = element(href ? 'a' : 'span', record.source?.title || record.source?.url || 'Source');
    if (href) { link.href = href; link.target = '_blank'; link.rel = 'noopener noreferrer'; }
    source.append(document.createTextNode('Source: '), link,
      document.createTextNode(record.source?.retrieved_at ? ` | retrieved ${String(record.source.retrieved_at).slice(0, 10)} UTC` : ''));
    row.append(source);
    const actions = element('div', null, 'actions'), named = (node, label) => { node.title = label; node.setAttribute('aria-label', label); return node; };
    if (record.review_status === 'unreviewed') {
      actions.append(named(button('Accept', () => reviewEvidence(record, 'accepted')), `Accept evidence ${n}`),
        named(button('Reject', () => reviewEvidence(record, 'rejected')), `Reject evidence ${n}`));
    } else actions.append(named(button('Mark unreviewed', () => reviewEvidence(record, 'unreviewed')), `Mark evidence ${n} unreviewed`));
    actions.append(button(`Remove evidence ${n}`, () => removeEvidence(record), { symbol: 'trash', compact: true }));
    row.append(actions); list.append(row);
  });
  group.append(list);
}

async function reviewEvidence(record, status) {
  await working('Saving evidence review...', () => request(`${docPath()}/evidence/${encodeURIComponent(record.id)}/review`, { method: 'PUT', body: { status } }));
  await loadEvidence(); renderValidation();
  notify(status === 'accepted' ? `Accepted evidence: ${record.subject}. The design was not changed.`
    : status === 'rejected' ? `Rejected evidence: ${record.subject}. The design was not changed.` : `Evidence marked unreviewed: ${record.subject}.`);
}

async function removeEvidence(record) {
  if (!confirm(`Remove research evidence "${record.subject}"? It cannot be restored; Sage can record it again from a new read.`)) return;
  await working('Removing research evidence...', () => request(`${docPath()}/evidence/${encodeURIComponent(record.id)}`, { method: 'DELETE' }));
  await loadEvidence(); renderValidation(); notify(`Removed research evidence: ${record.subject}.`);
}

async function requestQuotes(refresh = false) {
  if (!state.quoteForm.reportValidity()) return;
  flushEditor();
  if (!state.draft.document || state.draft.dirty) { render(); throw new Error('Save the document before requesting rates.'); }
  if (!state.provider?.configured) throw new Error('Carrier provider is not configured. No rates are available.');
  if (!state.draft.document.assessment.rate_ready) throw new Error('Resolve the validation errors before requesting rates.');
  state.addresses = captureAddresses(); state.quoteOptions = captureQuoteOptions(); const scenario = quoteScenarioValue();
  const shipments = state.draft.document.design.packages.length * state.addresses.destinations.length;
  if (refresh && !confirm(`Request new rates? This creates ${shipments} new provider shipment(s) for rating, which can be billed for a production account. No postage is purchased.`)) return;
  await working(refresh ? 'Requesting new carrier estimates...' : 'Requesting carrier estimates...', async () => {
    try {
      const result = await request(`${docPath()}/quotes`, { method: 'POST', body: quoteBody(state.draft.document.revision, state.addresses, state.quoteAccounts, state.quoteOptions, refresh) });
      const existing = state.quotes.findIndex(q => q.id === result.id);
      if (existing >= 0) { state.quotes[existing] = { ...state.quotes[existing], ...result }; state.quoteIndex = existing; }
      else { state.quotes.unshift(result); state.quotes = state.quotes.slice(0, 10); state.quoteIndex = 0; }
      state.quoteScenario = { id: result.id, value: scenario }; state.quoteError = '';
      notify(result.reused ? 'Showing the saved quote for this exact scenario. No provider request was made; use Refresh rates for new rates.'
        : `Carrier quote response received (${result.provider_shipments_created ?? 0} provider shipment(s) created). No postage was purchased.`);
    } catch (error) { state.quoteError = `Latest request failed: ${error.message}`; throw error; }
    finally { await loadQuoteAttempts(); renderQuoteResults(); }
  });
}

function updateFreshness() {
  const quote = state.quotes[state.quoteIndex];
  const sameScenario = quote && state.quoteScenario?.id === quote.id && state.quoteScenario.value === quoteScenarioValue();
  const label = $('quote-freshness');
  if (label) {
    label.textContent = `${state.quoteError ? 'Previous quote | ' : ''}${quoteFreshness(quote, state.draft.document?.revision, hasDraft(), sameScenario)}`;
    label.className = !hasDraft() && sameScenario && quote?.revision === state.draft.document?.revision && !quote?.stale ? 'good' : 'warning';
  }
  for (const b of [$('quote-button'), $('quote-refresh-button')]) {
    if (b) b.disabled = state.busy || !state.provider?.configured || !state.draft.document?.assessment.rate_ready || hasDraft();
  }
  const assessment = $('validation-panel');
  if (assessment) assessment.setAttribute('data-stale', String(hasDraft()));
  renderValidation();
}

function rateTable(rates, total = false) {
  const wrap = element('div', null, 'rate-table-wrap'), table = element('table');
  table.setAttribute('aria-label', total ? 'All-package rate totals' : 'Individual parcel rates');
  const head = element('thead'), hr = element('tr');
  for (const title of ['Service', total ? 'Account rate sum' : 'Account rate', 'List', 'Retail', 'Mode']) { const th = element('th', title); th.scope = 'col'; hr.append(th); } head.append(hr);
  const body = element('tbody');
  rates.forEach(rate => {
    const row = element('tr'), service = element('td');
    service.append(element('strong', rate.carrier), element('div', rate.service), element('div', rateAccountLabel(rate), 'rate-account muted'));
    if (rate.delivery_days != null) service.append(element('div', `${rate.delivery_days} days`, 'muted'));
    row.append(service, element('td', priceText(rate.currency, rate.amount), 'rate-amount'),
      element('td', priceText(total ? rate.currency : rate.list_currency, rate.list_amount), 'rate-amount muted'),
      element('td', priceText(total ? rate.currency : rate.retail_currency, rate.retail_amount), 'rate-amount muted'),
      element('td', rate.mode === 'test' ? 'test (not live)' : rate.mode, rate.mode === 'test' ? 'warning' : ''));
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
  if (quote.mode) host.append(element('p', quote.mode === 'test' ? 'Test mode: these are not live carrier quotes.' : 'Production account rates.', quote.mode === 'test' ? 'warning' : 'notice'));
  if (quote.provider_shipments_created != null) host.append(element('p', `${quote.provider_shipments_created} provider shipment(s) were created to rate this quote. No postage was purchased.`, 'metadata'));
  if (quote.price_bases) host.append(element('p', Object.values(quote.price_bases).join(' '), 'metadata'));
  for (const note of quote.origin_notes || []) host.append(element('p', `Origin: ${note.message}`, 'warning'));
  for (const result of quote.results || []) {
    const block = element('section', null, 'review-section');
    block.append(element('h3', `${result.destination.city}, ${result.destination.state} ${result.destination.zip}`));
    for (const note of result.notes || []) block.append(element('p', note.message, 'warning'));
    if (result.totals.length) {
      block.append(rateTable(result.totals, true), element('p', 'Sum of separate parcel estimates, not a consolidated shipment quote.', 'notice'));
    } else block.append(element('p', 'No common service across every package. See individual parcel responses.', 'warning'));
    for (const parcel of result.parcels) {
      const details = element('details'); details.append(element('summary', `${parcel.package_id} | ${parcel.mode} | ${parcel.rates.length} rates${parcel.carrier_error_count ? ` | ${parcel.carrier_error_count} carrier messages` : ''}`));
      if (parcel.carrier_error_count) details.append(element('p', `${parcel.carrier_error_count} carrier messages reported. Some services may be unavailable.`, 'warning'));
      for (const line of messageSummary(parcel.carrier_messages)) details.append(element('p', line, 'warning'));
      if (parcel.excluded_rate_count) details.append(element('p', `${parcel.excluded_rate_count} rates outside the selected accounts or services were left out.`, 'notice'));
      details.append(parcel.rates.length ? rateTable(parcel.rates) : element('p', 'Provider returned no rates for this parcel.', 'warning')); block.append(details);
    }
    host.append(block);
  }
  if (quote.notice) host.append(element('p', quote.notice, 'notice'));
  if (quote.fees_notice) host.append(element('p', quote.fees_notice, 'notice'));
  const audit = state.quoteAttempts;
  if (audit) {
    host.append(element('p', `Quote requests for this document created ${audit.total_shipments_created} provider shipment(s) in ${audit.attempt_count} attempt(s).`, 'metadata'));
    const interrupted = audit.attempts.filter(a => a.outcome === 'interrupted').length;
    if (interrupted) host.append(element('p', `${interrupted} attempt(s) were interrupted; their provider shipments are unknown.`, 'warning'));
    if (audit.total_unconfirmed_requests) host.append(element('p', `${audit.total_unconfirmed_requests} provider request(s) got no response; the provider may still have created shipments for them.`, 'warning'));
  }
  updateFreshness();
}

function refreshScene() {
  const p = selectedPackage(), product = state.draft.design.product;
  $('scene-caption').textContent = `${product ? product.source_id ? product.name + ' | imported geometry' : product.name + ' | manual geometry' : 'No product selected'}${p ? ` | ${dimensionText(p.carton.inner_m)} internal` : ''}${state.exploded ? ' | exploded view, positions unchanged' : ''}`;
  state.scene?.setDesign(state.draft.design, state.packageId, state.componentId, state.graphicId);
}

function setDisplayMode(mode) {
  state.displayMode = mode; state.scene?.setDisplay(mode, state.transparency);
  for (const node of document.querySelectorAll('#view-actions [data-mode]')) node.setAttribute('aria-pressed', String(node.dataset.mode === mode));
}

async function initializeScene() {
  const controls = $('view-actions');
  const sharedIcon = (node, kind) => {
    let markup = '';
    try { markup = window.parent !== window ? window.parent.InspectorProPackagingHost?.viewportIcon?.(kind) : ''; }
    catch { /* Use local icons if the embedding host is not accessible. */ }
    if (markup) {
      const parsed = new DOMParser().parseFromString(markup, 'text/html');
      node.replaceChildren(...[...parsed.body.childNodes].map(child => document.importNode(child, true)));
    }
    return node;
  };
  const views = element('div', null, 'view-group'); views.setAttribute('role', 'group'); views.setAttribute('aria-label', 'Camera views');
  views.append(sharedIcon(button('Fit view', () => state.scene?.fit(), { symbol: 'corners-out', compact: true }), 'zoomfit'));
  for (const [view, label] of [['iso', 'Orbit'], ['top', 'Top'], ['front', 'Front'], ['side', 'Side']]) {
    const b = button(label, () => state.scene?.view(view), { compact: true });
    const img = element('img'); img.src = `/static/assets/view-toolbar-icons/view-${view === 'side' ? 'right' : view}.png`; img.alt = ''; b.append(img); views.append(b);
  }
  const inspection = element('div', null, 'view-group'); inspection.setAttribute('role', 'group'); inspection.setAttribute('aria-label', 'Inspection views');
  checkbox(inspection, 'Section', false, checked => { state.section = checked; state.scene?.setSection(checked); });
  checkbox(inspection, 'Exploded', false, checked => { state.exploded = checked; state.scene?.setExploded(checked); refreshScene(); state.scene?.fit(); });
  for (const [index, input] of [...inspection.querySelectorAll('input')].entries()) {
    const label = input.parentElement, title = index ? 'Exploded' : 'Section';
    label.title = title; label.classList.add('view-toggle'); input.setAttribute('aria-label', title);
    label.lastChild.remove();
    const symbol = icon(index ? 'stack' : 'cube-focus');
    sharedIcon(symbol, index ? 'explode' : 'section');
    if (symbol.children.length) symbol.classList.remove('icon');
    symbol.classList.add('toggle-symbol'); label.append(symbol);
  }
  const display = element('div', null, 'view-group'), modes = element('div', null, 'display-modes');
  modes.setAttribute('role', 'group'); modes.setAttribute('aria-label', 'Display mode');
  for (const [mode, label, symbol] of [['shaded', 'Gray shaded', 'sphere'], ['edges', 'Shaded with edges', 'cube'], ['wireframe', 'Wireframe', 'bounding-box'], ['appearance', 'Appearance colors', 'mirror']]) {
    const b = button(label, () => setDisplayMode(mode), { symbol, compact: true });
    sharedIcon(b, `display-${mode}`);
    b.dataset.mode = mode; b.setAttribute('aria-pressed', String(mode === state.displayMode)); modes.append(b);
  }
  const transparency = element('label', 'Transparency', 'transparency-control');
  const slider = element('input'); slider.id = 'display-transparency'; slider.type = 'range'; slider.min = '0'; slider.max = '85'; slider.step = '5'; slider.value = String(state.transparency);
  slider.setAttribute('aria-label', 'Display transparency');
  const value = element('output', `${state.transparency}%`); value.htmlFor = slider.id;
  slider.addEventListener('input', () => {
    state.transparency = slider.valueAsNumber; value.value = `${state.transparency}%`;
    state.scene?.setDisplay(state.displayMode, state.transparency);
  });
  transparency.append(slider, value); display.append(modes, transparency);
  controls.append(views, inspection, display);
  try {
    const { PackagingScene } = await import('./packaging_scene.js');
    state.scene = new PackagingScene($('viewport'), {
      onStatus: message => { $('scene-message').textContent = message; },
      onSelect: (id, kind) => invoke(() => {
        flushEditor();
        if (kind === 'graphic') { state.graphicId = id; state.editor = 'graphics'; }
        else { state.componentId = id; state.graphicId = null; state.editor = 'contents'; }
        state.panel = state.editor; render();
      })
    }); state.scene.setDisplay(state.displayMode, state.transparency); refreshScene();
  } catch (error) { $('scene-message').textContent = `3D unavailable: ${error.message}. Numeric editing remains available.`; }
}

function boot() {
  try { const theme = localStorage.getItem('inspectorpro.theme'); if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme; } catch { /* Storage may be restricted. */ }
  if (window.parent !== window && window.frameElement?.id === 'packagingWorkspaceFrame') {
    document.documentElement.dataset.embedded = 'true';
    document.querySelector('.package-toolbar').prepend(document.querySelector('.document-name'));
    $('document-name').setAttribute('aria-label', 'Document name');
    document.querySelector('.scene-footer').append(document.querySelector('.statusbar'));
  }
  const close = button('Close panel', closePanel, { compact: true }); close.id = 'close-panel';
  const cross = element('span', '\u00d7'); cross.setAttribute('aria-hidden', 'true'); cross.style.fontSize = '22px'; close.append(cross); $('panel-actions').append(close);
  $('document-name').addEventListener('input', () => {
    edit(d => { d.name = $('document-name').value; }); updateHeader(); updateFreshness(); renderValidation();
  });
  $('package-select').addEventListener('change', event => invoke(() => {
    const next = event.target.value;
    try { flushEditor(); state.packageId = next; state.componentId = null; render(); state.scene?.fit(); }
    catch (error) { event.target.value = state.packageId || ''; throw error; }
  }));
  $('close-open').addEventListener('click', () => $('open-dialog').close());
  state.sage = new PackagingEditorAdmission({
    snapshot: () => ({ document_id: state.draft.document?.id || null, revision: state.draft.document?.revision ?? null,
      dirty: hasNavigationChanges(),
      conflict: state.conflict, pending_operations: state.busy || document.querySelector('dialog[open]') ? 1 : 0 }),
    lock: () => updateHeader(),
    accept: async saved => {
      state.draft.accept(saved); state.formDirty = false; state.conflict = false; state.mutationReceipt = null;
      state.candidates = null; state.candidateRevision = null; state.candidateConfig = null;
      await loadQuotes(); render(); notify(`Reconciled saved revision ${saved.revision}. Undo is available for saved edits.`);
    },
    invalidate: error => {
      notify(`${error.message} Edits may remain. Waiting for the host to stop and reconcile.`, true);
      window.parent.postMessage({ type: PACKAGING_BRIDGE, action: 'invalidate' }, window.location.origin);
    }
  });
  let commands = Promise.resolve();
  const seen = new Set();
  window.addEventListener('message', event => {
    const data = event.data;
    if (window.parent === window || event.source !== window.parent || event.origin !== window.location.origin
        || data?.type !== PACKAGING_BRIDGE || !bridgeId(data.request_id)
        || !['prepare', 'finish', 'release'].includes(data.action) || seen.has(data.request_id)
        || !data.payload || typeof data.payload !== 'object' || Array.isArray(data.payload)) return;
    const allowed = data.action === 'prepare' ? ['session_id', 'conversation_id'] : data.action === 'finish' ? ['documentId', 'revision'] : [];
    if (Object.keys(data.payload).some(key => !allowed.includes(key))) return;
    seen.add(data.request_id); if (seen.size > 100) seen.delete(seen.values().next().value);
    commands = commands.catch(() => {}).then(async () => {
      try {
        const value = await (data.action === 'prepare' ? state.sage.prepare(data.payload) : state.sage.finish(data.payload));
        event.source.postMessage({ type: PACKAGING_BRIDGE, action: 'result', request_id: data.request_id, ok: true, value }, event.origin);
      } catch (error) {
        notify(error.message, true);
        event.source.postMessage({ type: PACKAGING_BRIDGE, action: 'result', request_id: data.request_id, ok: false, error: error.message.slice(0, 500) }, event.origin);
      }
    });
  });
  window.InspectorProPackaging = Object.freeze({
    getRibbonState: () => ribbonState(),
    executeCommand: id => executeRibbonCommand(id),
    getDesktopLifecycleObservation: () => ({
      loaded: true,
      dirty: hasNavigationChanges(),
      busy: !!(state.busy || state.sage.locked),
      pending: !!(state.conflict || state.sage.admission || state.sage.closing || document.querySelector('dialog[open]')),
    }),
    isLocked: () => state.sage.locked,
    hasUnsavedChanges: () => hasNavigationChanges() || state.busy,
    confirmNavigation: () => !(hasNavigationChanges() || state.busy) || confirm('Leave Packaging & Shipping? Unsaved changes, selected files, session-only addresses or an active request may be lost.')
  });
  // Dialogs can open without changing the document. Keep the outer ribbon
  // unavailable until the modal interaction has completed.
  const modalObserver = new MutationObserver(publishRibbonState);
  modalObserver.observe(document.body, { attributes: true, attributeFilter: ['open'], subtree: true });
  window.addEventListener('beforeunload', event => { if (hasNavigationChanges() || state.busy || state.sage.locked) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('pagehide', () => { modalObserver.disconnect(); state.sage.unload(); state.scene?.dispose(); });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && state.panel && !document.querySelector('dialog[open]') && !state.busy && !state.sage.locked) {
      event.preventDefault(); closePanel(); return;
    }
    if (!(event.ctrlKey || event.metaKey)) return;
    if (event.key.toLowerCase() === 's') { event.preventDefault(); invoke(saveDocument); }
    if (event.key.toLowerCase() === 'z' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)) {
      event.preventDefault(); invoke(() => historyAction(event.shiftKey ? 'redo' : 'undo'));
    }
  });
  render(); renderRates(); initializeScene(); invoke(refreshProvider);
}

if (typeof document !== 'undefined' && document.getElementById('document-actions') && document.getElementById('package-select')) boot();
