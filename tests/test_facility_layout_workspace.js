'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const MODULE_PATH = path.join(ROOT, 'static', 'facility_layout_workspace.js');
const workspaceModule = require(MODULE_PATH);
const patternModule = require(path.join(
    ROOT,
    'static',
    'facility_layout_patterns.js'
));
const navigationAuthoringModule = require(path.join(
    ROOT,
    'static',
    'facility_layout_navigation_authoring.js'
));
const SPATIAL_FIXTURE = JSON.parse(fs.readFileSync(path.join(
    ROOT,
    'tests',
    'fixtures',
    'facility_layout',
    'spatial',
    'p6-browser-advisory.json'
), 'utf8'));

let checks = 0;
async function check(name, fn) {
    await fn();
    checks += 1;
    process.stdout.write(`PASS ${name}\n`);
}

function clone(value) {
    if (value === undefined) return undefined;
    return JSON.parse(JSON.stringify(value));
}

function selectorMatcher(selector) {
    const attribute = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
    if (attribute) {
        return element => {
            const value = element.getAttribute(attribute[1]);
            return value !== null && (
                attribute[2] === undefined || value === attribute[2]
            );
        };
    }
    const className = selector.match(/^\.([A-Za-z0-9_-]+)$/);
    if (className) {
        return element => String(element.className || '')
            .split(/\s+/).includes(className[1]);
    }
    return element => String(element.nodeName || '').toLowerCase()
        === selector.toLowerCase();
}

class FakeElement {
    constructor(documentRef, name) {
        this.ownerDocument = documentRef;
        this.nodeName = String(name).toUpperCase();
        this.parentNode = null;
        this.children = [];
        this.attributes = {};
        this.dataset = {};
        this.listeners = new Map();
        this.captureListeners = new Map();
        this.className = '';
        this.textContent = '';
        this.hidden = false;
        this.disabled = false;
        this.value = '';
        this.clientWidth = 900;
        this.clientHeight = 600;
        this.isContentEditable = false;
        this.capturedPointers = new Set();
        this.focusCount = 0;
        this.style = {
            left: '',
            top: '',
            right: '',
            gridTemplateRows: '',
            properties: {},
            setProperty(name, value) {
                this.properties[name] = String(value);
            },
            getPropertyValue(name) {
                return this.properties[name] || '';
            },
        };
    }

    appendChild(child) {
        if (child.parentNode) child.parentNode.removeChild(child);
        child.parentNode = this;
        this.children.push(child);
        return child;
    }

    removeChild(child) {
        const index = this.children.indexOf(child);
        if (index >= 0) this.children.splice(index, 1);
        child.parentNode = null;
        return child;
    }

    remove() {
        if (this.parentNode) this.parentNode.removeChild(this);
    }

    get firstChild() {
        return this.children[0] || null;
    }

    setAttribute(name, value) {
        const text = String(value);
        this.attributes[name] = text;
        if (name === 'class') this.className = text;
        if (name === 'value') this.value = text;
        if (name === 'disabled') this.disabled = true;
        if (name === 'hidden') this.hidden = true;
        if (name === 'draggable') this.draggable = text === 'true';
    }

    getAttribute(name) {
        if (name === 'class' && this.className) return this.className;
        return Object.prototype.hasOwnProperty.call(this.attributes, name)
            ? this.attributes[name]
            : null;
    }

    removeAttribute(name) {
        delete this.attributes[name];
        if (name === 'disabled') this.disabled = false;
        if (name === 'hidden') this.hidden = false;
    }

    addEventListener(type, handler, options) {
        const capture = options === true || Boolean(options && options.capture);
        const map = capture ? this.captureListeners : this.listeners;
        if (!map.has(type)) map.set(type, new Set());
        map.get(type).add(handler);
        FakeElement.listenerCount += 1;
    }

    removeEventListener(type, handler, options) {
        const capture = options === true || Boolean(options && options.capture);
        const handlers = (capture ? this.captureListeners : this.listeners).get(type);
        if (handlers && handlers.delete(handler)) FakeElement.listenerCount -= 1;
    }

    contains(node) {
        let current = node;
        while (current) {
            if (current === this) return true;
            current = current.parentNode;
        }
        return false;
    }

    setPointerCapture(pointerId) {
        this.capturedPointers.add(Number(pointerId));
    }

    hasPointerCapture(pointerId) {
        return this.capturedPointers.has(Number(pointerId));
    }

    releasePointerCapture(pointerId) {
        this.capturedPointers.delete(Number(pointerId));
    }

    getBoundingClientRect() {
        return {
            left: 0,
            top: 0,
            width: this.clientWidth,
            height: this.clientHeight,
        };
    }

    focus() {
        this.focusCount += 1;
        this.ownerDocument.activeElement = this;
    }

    descendants() {
        const result = [];
        this.children.forEach(child => {
            result.push(child);
            result.push(...child.descendants());
        });
        return result;
    }

    querySelector(selector) {
        return this.querySelectorAll(selector)[0] || null;
    }

    querySelectorAll(selector) {
        const match = selectorMatcher(selector);
        return this.descendants().filter(match);
    }

    dispatch(type, input) {
        const source = input || {};
        const event = Object.assign({
            type,
            target: this,
            currentTarget: this,
            relatedTarget: null,
            ctrlKey: false,
            metaKey: false,
            shiftKey: false,
            defaultPrevented: false,
            propagationStopped: false,
            immediateStopped: false,
            preventDefault() { this.defaultPrevented = true; },
            stopPropagation() { this.propagationStopped = true; },
            stopImmediatePropagation() { this.propagationStopped = true; this.immediateStopped = true; },
        }, source);
        if (!event.target) event.target = this;
        const path = [];
        for (let current = this; current; current = current.parentNode) path.push(current);
        const run = (node, map) => {
            event.currentTarget = node;
            const handlers = map.get(type);
            if (!handlers) return;
            for (const handler of Array.from(handlers)) {
                handler(event);
                if (event.immediateStopped) return;
            }
        };
        // As the DOM does: capturing listeners from the top down (at the target before its other listeners), then
        // the target's and its ancestors' own.
        for (let index = path.length - 1; index >= 0 && !event.propagationStopped; index -= 1) {
            run(path[index], path[index].captureListeners);
        }
        for (let index = 0; index < path.length && !event.propagationStopped; index += 1) {
            run(path[index], path[index].listeners);
        }
        return event;
    }
}
FakeElement.listenerCount = 0;

class FakeDocument {
    constructor() {
        this.activeElement = null;
    }

    createElement(name) {
        return new FakeElement(this, name);
    }

    createTextNode(text) {
        const node = new FakeElement(this, '#text');
        node.nodeType = 3;
        node.textContent = String(text);
        return node;
    }
}

class FakeSurfaceManager {
    constructor() {
        this.available = true;
        this.active = null;
        this.openCalls = [];
        this.closeCalls = [];
        this.repositionCount = 0;
        this.destroyCount = 0;
    }

    open(config) {
        if (this.active) this.close('replaced');
        this.active = config;
        this.openCalls.push(config);
        return true;
    }

    close(reason) {
        if (!this.active) return false;
        const active = this.active;
        this.active = null;
        this.closeCalls.push(reason);
        if (typeof active.onClose === 'function') active.onClose(reason);
        return true;
    }

    destroy() {
        this.destroyCount += 1;
        this.close('destroyed');
    }

    reanchor(reference) {
        if (!this.active) return false;
        this.active.reference = reference;
        return true;
    }

    reposition() {
        this.repositionCount += 1;
        return Promise.resolve(Boolean(this.active));
    }

    isOpen() {
        return Boolean(this.active);
    }

    getActive() {
        return this.active;
    }
}

function fakeFloatingDom() {
    return {
        offset(value) { return { name: 'offset', value }; },
        flip(value) { return { name: 'flip', value }; },
        shift(value) { return { name: 'shift', value }; },
    };
}

class FakeDataTransfer {
    constructor() {
        this.data = {};
        this.effectAllowed = '';
        this.dropEffect = '';
    }

    setData(type, value) {
        this.data[type] = String(value);
    }

    getData(type) {
        return this.data[type] || '';
    }
}

function placement(id, assetId, x, z, mode) {
    return {
        placementId: id,
        assetId,
        assetDefinitionRevision: `revision-${assetId}`,
        transform: {
            position: { x, y: 0, z },
            quaternion: { x: 0, y: 0, z: 0, w: 1 },
            scale: 1,
        },
        positionMode: mode || 'auto',
        snapRelationship: null,
        metadata: { instanceLabel: id },
    };
}

function zone(id) {
    return {
        zoneId: id,
        zoneType: 'workcell',
        label: 'Assembly cell',
        boundary: [
            { x: 0, z: 0 },
            { x: 4, z: 0 },
            { x: 4, z: 3 },
            { x: 0, z: 3 },
        ],
        floorElevation: 0,
        anchors: [],
        evidence: [],
    };
}

function floorMarking(id, type) {
    return {
        markingId: id,
        markingType: type || 'keep_clear',
        label: 'Keep Clear',
        semanticRole: 'keep_clear',
        transform: {
            position: { x: 4, y: 0, z: 3 },
            rotationDegrees: 0,
        },
        width: 4,
        depth: 2,
        fillColor: '#facc15',
        strokeColor: '#111827',
        opacity: 1,
        text: 'KEEP CLEAR',
        positionMode: 'manual',
        metadata: { authoredIn: 'facility_plan' },
        evidence: [],
    };
}

function layout() {
    return {
        schemaVersion: 1,
        layoutId: 'fl-workspace',
        displayName: 'Workspace test',
        status: 'draft',
        association: { siteId: 'site-a' },
        coordinateFrame: {
            units: 'm',
            handedness: 'right',
            upAxis: '+Y',
            floorAxes: ['+X', '+Z'],
            datumId: 'site-origin',
            floorElevation: 0,
        },
        sourceShellRef: {
            shellId: 'shell-a',
            shellRevision: 'a'.repeat(64),
            coordinateFrameFingerprint: 'b'.repeat(64),
        },
        policySetRef: {
            policySetId: 'policy-a',
            policySetRevision: 'c'.repeat(64),
        },
        zones: [zone('zn-a')],
        floorMarkings: [],
        placements: [
            placement('pl-a', 'asset-rack', 1, 1, 'auto'),
            placement('pl-b', 'asset-forklift', 5, 2, 'manual'),
        ],
        routes: [],
        utilityNetworks: [],
        processBindings: [],
        dismissedSuggestions: [],
        createdAt: '2026-07-29T00:00:00Z',
        updatedAt: '2026-07-29T00:00:00Z',
    };
}

function selectedRecord(document, id) {
    return document.placements.find(item => item.placementId === id)
        || document.zones.find(item => item.zoneId === id)
        || (document.floorMarkings || []).find(item => item.markingId === id)
        || (document.routes || []).find(item => item.routeId === id);
}

class FakeSession {
    constructor() {
        this.listeners = new Set();
        this.calls = [];
        this.idSequence = 0;
        this.state = {
            apiVersion: 1,
            loaded: true,
            baseRevision: 'rev-1',
            baseLayout: layout(),
            layout: layout(),
            operations: [],
            history: [],
            historyCursor: 0,
            canUndo: false,
            canRedo: false,
            dirty: false,
            busy: false,
            conflict: null,
            selection: [],
            camera: null,
            ghostPlacement: null,
            placementAlternatives: null,
            layoutProposal: null,
            lastError: null,
        };
    }

    _notify() {
        const snapshot = this.getState();
        this.listeners.forEach(listener => listener(snapshot));
    }

    _gesture(name, operationCount) {
        this.state.dirty = true;
        this.state.history.push({
            label: name,
            operationCount: operationCount || 1,
            applied: true,
        });
        this.state.historyCursor = this.state.history.length;
        this.state.canUndo = true;
        this.state.canRedo = false;
        this._notify();
        return Promise.resolve(this.getState());
    }

    getState() {
        return clone(this.state);
    }

    subscribe(listener) {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    select(id, options) {
        this.calls.push(['select', id, clone(options || {})]);
        if (!selectedRecord(this.state.layout, id)) return this.getState();
        if (options && options.toggle) {
            this.state.selection = this.state.selection.includes(id)
                ? this.state.selection.filter(item => item !== id)
                : this.state.selection.concat([id]);
        } else if (options && options.additive) {
            if (!this.state.selection.includes(id)) this.state.selection.push(id);
        } else {
            this.state.selection = [id];
        }
        this._notify();
        return this.getState();
    }

    async setSelectedAppearance(color) {
        this.calls.push(['setSelectedAppearance', color]);
        this.state.layout.placements.filter(p => this.state.selection.includes(p.placementId)).forEach(p => {
            if (color === null) delete p.appearance;
            else p.appearance = {color};
        });
        return this._gesture('Appearance');
    }

    selectMany(ids, options) {
        this.calls.push(['selectMany', clone(ids), clone(options || {})]);
        const valid = ids.filter(id => selectedRecord(this.state.layout, id));
        this.state.selection = options && options.additive
            ? Array.from(new Set(this.state.selection.concat(valid)))
            : Array.from(new Set(valid));
        this._notify();
        return this.getState();
    }

    clearSelection() {
        this.calls.push(['clearSelection']);
        this.state.selection = [];
        this._notify();
        return this.getState();
    }

    beginGhostPlacement(asset) {
        this.calls.push(['beginGhostPlacement', clone(asset)]);
        this.state.ghostPlacement = {
            assetId: asset.assetId,
            assetDefinitionRevision: asset.assetDefinitionRevision,
            worldPosition: null,
            valid: true,
            metadata: clone(asset.metadata || {}),
        };
        this._notify();
        return clone(this.state.ghostPlacement);
    }

    updateGhostPlacement(worldPosition, valid) {
        this.calls.push(['updateGhostPlacement', clone(worldPosition), valid]);
        this.state.ghostPlacement.worldPosition = clone(worldPosition);
        this.state.ghostPlacement.valid = valid !== false;
        this._notify();
        return clone(this.state.ghostPlacement);
    }

    cancelGhostPlacement() {
        this.calls.push(['cancelGhostPlacement']);
        this.state.ghostPlacement = null;
        this._notify();
        return this.getState();
    }

    installPlacementAlternatives(receipt) {
        this.calls.push(['installPlacementAlternatives', clone(receipt)]);
        this.state.placementAlternatives = {
            authority: 'server-authoritative',
            authoritative: true,
            baseRevision: receipt.baseRevision,
            selectedIndex: 0,
            candidates: clone(receipt.candidates),
        };
        const candidate = this.state.placementAlternatives.candidates[0];
        this.state.ghostPlacement = {
            assetId: candidate.operations[0].placement.assetId,
            assetDefinitionRevision:
                candidate.operations[0].placement.assetDefinitionRevision,
            worldPosition: clone(candidate.transform.position),
            valid: true,
            metadata: {
                previewKind: 'authoritative-placement-candidate',
                candidateId: candidate.candidateId,
                candidateIndex: 0,
                candidateCount: receipt.candidates.length,
                family: candidate.family,
                safetyStatus: candidate.safetyStatus,
                findings: clone(candidate.findings || []),
                metrics: clone(candidate.metrics || {}),
            },
        };
        this._notify();
        return this.getState();
    }

    requestPlacementAlternatives(request) {
        this.calls.push(['requestPlacementAlternatives', clone(request)]);
        return Promise.resolve(
            this.installPlacementAlternatives(
                clone(SPATIAL_FIXTURE.candidateReceipt)
            )
        );
    }

    cyclePlacementAlternative(offset) {
        this.calls.push(['cyclePlacementAlternative', offset]);
        const proposal = this.state.placementAlternatives;
        const count = proposal.candidates.length;
        proposal.selectedIndex = (
            (proposal.selectedIndex + offset) % count + count
        ) % count;
        const candidate = proposal.candidates[proposal.selectedIndex];
        this.state.ghostPlacement.worldPosition =
            clone(candidate.transform.position);
        this.state.ghostPlacement.metadata.candidateId =
            candidate.candidateId;
        this.state.ghostPlacement.metadata.candidateIndex =
            proposal.selectedIndex;
        this.state.ghostPlacement.metadata.family = candidate.family;
        this.state.ghostPlacement.metadata.safetyStatus =
            candidate.safetyStatus;
        this.state.ghostPlacement.metadata.findings =
            clone(candidate.findings || []);
        this.state.ghostPlacement.metadata.metrics =
            clone(candidate.metrics || {});
        this._notify();
        return this.getState();
    }

    dismissPlacementAlternatives() {
        this.calls.push(['dismissPlacementAlternatives']);
        this.state.placementAlternatives = null;
        this.state.ghostPlacement = null;
        this._notify();
        return this.getState();
    }

    acceptPlacementAlternative() {
        this.calls.push(['acceptPlacementAlternative']);
        const proposal = this.state.placementAlternatives;
        const candidate = proposal.candidates[proposal.selectedIndex];
        const placed = clone(candidate.operations[0].placement);
        this.state.layout.placements.push(placed);
        this.state.selection = [placed.placementId];
        this.state.placementAlternatives = null;
        this.state.ghostPlacement = null;
        return this._gesture('Accept placement alternative');
    }

    requestLayoutProposal(request) {
        this.calls.push(['requestLayoutProposal', clone(request)]);
        const first = clone(this.state.baseLayout);
        const second = clone(this.state.baseLayout);
        first.placements[0].transform.position.x = 12;
        second.placements[0].transform.position.x = 24;
        first.placements = first.placements.slice(0, 1);
        second.placements = second.placements.slice(0, 1);
        first.placements.push(placement(
            'pl-proposed',
            'asset-machine',
            9,
            4,
            'auto'
        ));
        second.placements.push(placement(
            'pl-proposed',
            'asset-machine',
            18,
            4,
            'auto'
        ));
        function alternative(index, strategy, ghostLayout) {
            return {
                proposalId: 'proposal-' + index,
                alternativeId: 'alternative-' + index,
                strategy,
                operations: [],
                ghostPreview: {
                    layout: ghostLayout,
                    routeProposals: [],
                },
                metrics: {
                    placementCollisions: 0,
                    movedAutoCount: 1,
                    spatialErrorCount: 0,
                    spatialWarningCount: 1,
                    spatialUnverifiedCount: 2,
                    clearanceConflicts: 1,
                    baselineClearanceConflicts: 3,
                },
                findings: [{
                    severity: 'warning',
                    code: 'fixture-warning',
                    message: 'Fixture review warning.',
                }],
                newHardFindingIds: [],
                transactionBinding: {
                    target: {
                        domain: 'facility-layout',
                        scopeId: 'site-a',
                        resourceId: 'fl-workspace',
                    },
                    baseRevision: 'rev-1',
                    diffHash: 'd'.repeat(64),
                    dependencyFingerprint: 'e'.repeat(64),
                },
                createdAt: '2026-07-29T00:00:00Z',
                expiresAt: '2026-07-29T00:10:00Z',
            };
        }
        this.state.layoutProposal = {
            authority: 'server-authoritative',
            previewPure: true,
            baseRevision: 'rev-1',
            request: clone(request),
            selectedIndex: 0,
            alternatives: [
                alternative(1, 'compact_rows', first),
                alternative(2, 'balanced_grid', second),
            ],
        };
        this.state.placementAlternatives = null;
        this.state.ghostPlacement = null;
        this._notify();
        return Promise.resolve(this.getState());
    }

    cycleLayoutProposal(offset) {
        this.calls.push(['cycleLayoutProposal', offset]);
        const proposal = this.state.layoutProposal;
        proposal.selectedIndex = (
            (proposal.selectedIndex + offset) % proposal.alternatives.length
                + proposal.alternatives.length
        ) % proposal.alternatives.length;
        this._notify();
        return this.getState();
    }

    dismissLayoutProposal() {
        this.calls.push(['dismissLayoutProposal']);
        this.state.layoutProposal = null;
        this._notify();
        return Promise.resolve(this.getState());
    }

    approveAndApplyLayoutProposal() {
        this.calls.push(['approveAndApplyLayoutProposal']);
        const selected = this.state.layoutProposal.alternatives[
            this.state.layoutProposal.selectedIndex
        ];
        this.state.layout = clone(selected.ghostPreview.layout);
        this.state.baseLayout = clone(selected.ghostPreview.layout);
        this.state.baseRevision = 'rev-2';
        this.state.layoutProposal = null;
        this.state.dirty = false;
        this._notify();
        return Promise.resolve({
            state: this.getState(),
            receipt: {
                layout: clone(this.state.layout),
                revision: 'rev-2',
            },
        });
    }

    commitGhostPlacement() {
        this.calls.push(['commitGhostPlacement']);
        const ghost = clone(this.state.ghostPlacement);
        this.idSequence += 1;
        const id = `pl-new-${this.idSequence}`;
        this.state.layout.placements.push(placement(
            id,
            ghost.assetId,
            ghost.worldPosition.x,
            ghost.worldPosition.z,
            'manual'
        ));
        this.state.layout.placements[
            this.state.layout.placements.length - 1
        ].assetDefinitionRevision = ghost.assetDefinitionRevision;
        this.state.selection = [id];
        this.state.ghostPlacement = null;
        return this._gesture('Place asset');
    }

    placeAssets(requests) {
        this.calls.push(['placeAssets', clone(requests)]);
        const created = requests.map(request => {
            this.idSequence += 1;
            const id = `pl-browser-${this.idSequence}`;
            const value = placement(
                id,
                request.assetId,
                request.worldPosition.x,
                request.worldPosition.z,
                request.positionMode || 'manual'
            );
            value.assetDefinitionRevision = request.assetDefinitionRevision;
            value.transform.position.y = request.worldPosition.y || 0;
            value.metadata = clone(request.metadata || {});
            this.state.layout.placements.push(value);
            return id;
        });
        this.state.selection = created;
        return this._gesture(
            requests.length === 1 ? 'Add asset' : 'Add assets',
            requests.length
        );
    }

    moveSelected(delta) {
        this.calls.push(['moveSelected', clone(delta)]);
        this.state.selection.forEach(id => {
            const value = this.state.layout.placements.find(
                item => item.placementId === id
            ) || (this.state.layout.floorMarkings || []).find(
                item => item.markingId === id
            );
            if (!value) return;
            value.transform.position.x += delta.x || 0;
            value.transform.position.y += delta.y || 0;
            value.transform.position.z += delta.z || 0;
            if (value.positionMode === 'auto') value.positionMode = 'manual';
        });
        return this._gesture('Move selection');
    }

    movePlacements(updates, label) {
        this.calls.push(['movePlacements', clone(updates), label]);
        updates.forEach(update => {
            const value = this.state.layout.placements.find(
                item => item.placementId === update.placementId
            );
            if (!value) return;
            value.transform.position = clone(update.position);
            if (value.positionMode === 'auto') value.positionMode = 'manual';
        });
        return this._gesture(label || 'Position placements');
    }

    rotateSelected90(turns) {
        this.calls.push(['rotateSelected90', turns]);
        const q = workspaceModule.quarterTurnQuaternion(
            turns === undefined ? 1 : turns
        );
        this.state.selection.forEach(id => {
            const value = this.state.layout.placements.find(
                item => item.placementId === id
            );
            if (value) value.transform.quaternion = clone(q);
            const marking = (this.state.layout.floorMarkings || []).find(
                item => item.markingId === id
            );
            if (marking) {
                marking.transform.rotationDegrees += 90
                    * (turns === undefined ? 1 : turns);
            }
        });
        return this._gesture('Rotate selection');
    }

    _duplicatePlacements(placementIds, offset) {
        const created = [];
        placementIds.forEach(placementId => {
            const source = this.state.layout.placements.find(
                item => item.placementId === placementId
            );
            if (!source) return;
            this.idSequence += 1;
            const duplicate = clone(source);
            duplicate.placementId = `pl-copy-${this.idSequence}`;
            duplicate.transform.position.x += offset.x;
            duplicate.transform.position.z += offset.z;
            duplicate.positionMode = 'manual';
            this.state.layout.placements.push(duplicate);
            created.push(duplicate.placementId);
        });
        this.state.selection = created;
        return this._gesture('Duplicate selection');
    }

    duplicatePlacements(placementIds, offset) {
        this.calls.push([
            'duplicatePlacements',
            clone(placementIds),
            clone(offset),
        ]);
        return this._duplicatePlacements(placementIds, offset);
    }

    _duplicateItems(itemIds, offset) {
        const created = [];
        itemIds.forEach(id => {
            const placement = this.state.layout.placements.find(
                item => item.placementId === id
            );
            if (placement) {
                this.idSequence += 1;
                const copy = clone(placement);
                copy.placementId = `pl-copy-${this.idSequence}`;
                copy.transform.position.x += offset.x;
                copy.transform.position.z += offset.z;
                copy.positionMode = 'manual';
                this.state.layout.placements.push(copy);
                created.push(copy.placementId);
                return;
            }
            const marking = (this.state.layout.floorMarkings || []).find(
                item => item.markingId === id
            );
            if (!marking) return;
            this.idSequence += 1;
            const copy = clone(marking);
            copy.markingId = `fm-copy-${this.idSequence}`;
            copy.transform.position.x += offset.x;
            copy.transform.position.z += offset.z;
            copy.positionMode = 'manual';
            this.state.layout.floorMarkings.push(copy);
            created.push(copy.markingId);
        });
        this.state.selection = created;
        return this._gesture('Duplicate selection');
    }

    duplicateItems(itemIds, offset) {
        this.calls.push(['duplicateItems', clone(itemIds), clone(offset)]);
        return this._duplicateItems(itemIds, offset);
    }

    duplicateSelected(offset) {
        this.calls.push(['duplicateSelected', clone(offset)]);
        return this._duplicateItems(this.state.selection.slice(), offset);
    }

    applyPattern(result, label) {
        this.calls.push(['applyPattern', clone(result), label]);
        const created = [];
        (result.copies || []).forEach(copy => {
            const placement = this.state.layout.placements.find(
                item => item.placementId === copy.sourceId
            );
            if (placement && copy.kind === 'placement') {
                this.idSequence += 1;
                const value = clone(placement);
                value.placementId = `pl-pattern-${this.idSequence}`;
                value.transform.position = clone(copy.position);
                value.positionMode = 'manual';
                this.state.layout.placements.push(value);
                created.push(value.placementId);
                return;
            }
            const marking = (this.state.layout.floorMarkings || []).find(
                item => item.markingId === copy.sourceId
            );
            if (marking && copy.kind === 'floor-marking') {
                this.idSequence += 1;
                const value = clone(marking);
                value.markingId = `fm-pattern-${this.idSequence}`;
                value.transform.position = clone(copy.position);
                value.transform.rotationDegrees = copy.rotationDegrees;
                value.positionMode = 'manual';
                this.state.layout.floorMarkings.push(value);
                created.push(value.markingId);
                return;
            }
            const zone = this.state.layout.zones.find(
                item => item.zoneId === copy.sourceId
            );
            if (zone && copy.kind === 'zone') {
                this.idSequence += 1;
                const value = clone(zone);
                value.zoneId = `zn-pattern-${this.idSequence}`;
                value.boundary = clone(copy.boundary);
                this.state.layout.zones.push(value);
                created.push(value.zoneId);
            }
        });
        (result.moves || []).forEach(move => {
            const value = selectedRecord(this.state.layout, move.sourceId);
            if (!value) return;
            if (value.zoneId) {
                value.boundary = clone(move.boundary);
                return;
            }
            value.transform.position = clone(move.position);
            if (value.markingId) {
                value.transform.rotationDegrees = move.rotationDegrees;
            }
            if (value.positionMode === 'auto') value.positionMode = 'manual';
        });
        if (created.length) this.state.selection = created;
        return this._gesture(label || 'Create pattern',
            (result.copies || []).length + (result.moves || []).length);
    }

    setPlanSettings(settings) {
        this.calls.push(['setPlanSettings', clone(settings)]);
        this.state.layout.extensions = this.state.layout.extensions || {};
        this.state.layout.extensions.facilityPlan = clone(settings);
        return this._gesture('Resize facility plan');
    }

    clearLayout() {
        this.calls.push(['clearLayout']);
        this.state.layout.placements = [];
        this.state.layout.zones = [];
        this.state.layout.floorMarkings = [];
        this.state.layout.routes = [];
        this.state.layout.utilityNetworks = [];
        this.state.layout.processBindings = [];
        this.state.layout.dismissedSuggestions = [];
        this.state.selection = [];
        return this._gesture('Clear facility layout');
    }

    deleteSelected() {
        this.calls.push(['deleteSelected']);
        const selected = new Set(this.state.selection);
        this.state.layout.placements = this.state.layout.placements.filter(
            item => !selected.has(item.placementId)
        );
        this.state.layout.zones = this.state.layout.zones.filter(
            item => !selected.has(item.zoneId)
        );
        this.state.layout.floorMarkings = (
            this.state.layout.floorMarkings || []
        ).filter(item => !selected.has(item.markingId));
        this.state.selection = [];
        return this._gesture('Delete selection');
    }

    lockSelected() {
        this.calls.push(['lockSelected']);
        this.state.selection.forEach(id => {
            const value = this.state.layout.placements.find(
                item => item.placementId === id
            ) || (this.state.layout.floorMarkings || []).find(
                item => item.markingId === id
            );
            if (value) value.positionMode = 'locked';
        });
        return this._gesture('Lock selection');
    }

    unlockSelected() {
        this.calls.push(['unlockSelected']);
        this.state.selection.forEach(id => {
            const value = this.state.layout.placements.find(
                item => item.placementId === id
            ) || (this.state.layout.floorMarkings || []).find(
                item => item.markingId === id
            );
            if (value) value.positionMode = 'manual';
        });
        return this._gesture('Unlock selection');
    }

    createRectangleZone(start, end, options) {
        this.calls.push(['createRectangleZone', clone(start), clone(end), clone(options)]);
        this.idSequence += 1;
        const id = `zn-new-${this.idSequence}`;
        this.state.layout.zones.push({
            zoneId: id,
            zoneType: options.zoneType,
            label: options.label,
            boundary: [
                { x: Math.min(start.x, end.x), z: Math.min(start.z, end.z) },
                { x: Math.max(start.x, end.x), z: Math.min(start.z, end.z) },
                { x: Math.max(start.x, end.x), z: Math.max(start.z, end.z) },
                { x: Math.min(start.x, end.x), z: Math.max(start.z, end.z) },
            ],
            floorElevation: 0,
            anchors: [],
            evidence: [],
        });
        this.state.selection = [id];
        return this._gesture('Create rectangle zone');
    }

    createZones(requests) {
        this.calls.push(['createZones', clone(requests)]);
        const created = [];
        requests.forEach(request => {
            this.idSequence += 1;
            const id = `zn-bulk-${this.idSequence}`;
            this.state.layout.zones.push({
                zoneId: id,
                zoneType: request.zoneType,
                label: request.label,
                boundary: [
                    { x: request.minX, z: request.minZ },
                    { x: request.minX + request.width, z: request.minZ },
                    {
                        x: request.minX + request.width,
                        z: request.minZ + request.depth,
                    },
                    { x: request.minX, z: request.minZ + request.depth },
                ],
                floorElevation: 0,
                anchors: [],
                evidence: [],
                extensions: clone(request.extensions || {}),
            });
            created.push(id);
        });
        this.state.selection = created;
        return this._gesture('Create facility zones');
    }

    createCellGroup(request) {
        this.calls.push(['createCellGroup', clone(request)]);
        this.idSequence += 1;
        const id = `zn-cell-${this.idSequence}`;
        const sequence = String(request.start).padStart(
            request.numberPadding,
            '0'
        );
        this.state.layout.zones.push({
            zoneId: id,
            zoneType: 'workcell',
            label: request.baseName + ' ' + request.prefix + sequence,
            boundary: [
                { x: request.minX, z: request.minZ },
                { x: request.minX + request.width, z: request.minZ },
                {
                    x: request.minX + request.width,
                    z: request.minZ + request.depth,
                },
                { x: request.minX, z: request.minZ + request.depth },
            ],
            floorElevation: 0,
            anchors: [],
            evidence: [],
            extensions: Object.assign({}, clone(request.extensions || {}), {
                cellGroup: {
                    schemaVersion: 1,
                    groupKind: 'manufacturing_cell',
                    membership: 'geometric',
                    envelopePadding: request.envelopePadding,
                    autoNumber: {
                        seriesId: request.seriesId,
                        baseName: request.baseName,
                        prefix: request.prefix,
                        start: request.start,
                        padding: request.numberPadding,
                        sequence: request.start,
                    },
                    functionalInterfaces: clone(
                        request.functionalInterfaces || {}
                    ),
                },
            }),
        });
        this.state.selection = [id];
        return this._gesture('Create manufacturing cell');
    }

    ungroupCell(zoneId) {
        this.calls.push(['ungroupCell', zoneId]);
        this.state.layout.zones = this.state.layout.zones.filter(
            zone => zone.zoneId !== zoneId
        );
        this.state.selection = [];
        return this._gesture('Ungroup manufacturing cell');
    }

    createPolygonZone(points, options) {
        this.calls.push(['createPolygonZone', clone(points), clone(options)]);
        this.idSequence += 1;
        const id = `zn-poly-${this.idSequence}`;
        this.state.layout.zones.push({
            zoneId: id,
            zoneType: options.zoneType,
            label: options.label,
            boundary: clone(points),
            floorElevation: 0,
            anchors: [],
            evidence: [],
        });
        this.state.selection = [id];
        return this._gesture('Create polygon zone');
    }

    createFloorMarking(request) {
        this.calls.push(['createFloorMarking', clone(request)]);
        this.idSequence += 1;
        const value = Object.assign(
            floorMarking(`fm-new-${this.idSequence}`, request.markingType),
            clone(request)
        );
        this.state.layout.floorMarkings.push(value);
        this.state.selection = [value.markingId];
        return this._gesture('Create floor marking');
    }

    editFloorMarking(markingId, patch) {
        this.calls.push(['editFloorMarking', markingId, clone(patch)]);
        const value = (this.state.layout.floorMarkings || []).find(
            item => item.markingId === markingId
        );
        if (!value) return Promise.reject(new Error('Unknown floor marking'));
        Object.assign(value, clone(patch));
        return this._gesture('Edit floor marking');
    }

    createAisle(request) {
        this.calls.push(['createAisle', clone(request)]);
        this.idSequence += 1;
        const id = `rt-aisle-${this.idSequence}`;
        this.state.layout.routes.push({
            routeId: id,
            label: request.label,
            routeKind: request.aisleKind === 'forklift'
                ? 'forklift' : 'material',
            sourceEndpoint: {
                kind: 'world_point',
                position: clone(request.centerline[0]),
            },
            targetEndpoint: {
                kind: 'world_point',
                position: clone(request.centerline.at(-1)),
            },
            routingMode: request.aisleKind === 'forklift'
                ? 'vehicle' : 'polyline',
            centerline: clone(request.centerline),
            corridorWidth: request.corridorWidth,
            requirements: [],
            evidence: [],
            extensions: {
                facilityAisle: {
                    schemaVersion: 1,
                    aisleKind: request.aisleKind,
                    direction: request.direction,
                    color: request.color,
                    clearanceEvidenceStatus:
                        request.clearanceEvidenceStatus,
                },
            },
        });
        this.state.selection = [id];
        return this._gesture('Create facility aisle');
    }

    editAisle(routeId, patch) {
        this.calls.push(['editAisle', routeId, clone(patch)]);
        const route = this.state.layout.routes.find(
            item => item.routeId === routeId
        );
        if (!route) return Promise.reject(new Error('Unknown facility aisle'));
        if (patch.label !== undefined) route.label = patch.label;
        if (patch.corridorWidth !== undefined) {
            route.corridorWidth = patch.corridorWidth;
        }
        const aisle = route.extensions.facilityAisle;
        ['aisleKind', 'direction', 'color', 'clearanceEvidenceStatus']
            .forEach(key => {
                if (patch[key] !== undefined) aisle[key] = patch[key];
            });
        return this._gesture('Edit facility aisle');
    }

    setFacilityNavigation(facilityNavigation) {
        this.calls.push(['setFacilityNavigation', clone(facilityNavigation)]);
        this.state.layout.extensions = Object.assign(
            {},
            this.state.layout.extensions || {},
            { facilityNavigation: clone(facilityNavigation) }
        );
        this.state.operations.push({
            op: 'set_facility_navigation',
            facilityNavigation: clone(facilityNavigation),
            authoringSource: 'plan_pointer',
        });
        return this._gesture('Author motion path');
    }

    editZoneDimensions(id, dimensions) {
        this.calls.push(['editZoneDimensions', id, clone(dimensions)]);
        const value = this.state.layout.zones.find(item => item.zoneId === id);
        const center = workspaceModule.zoneDimensions(value).center;
        const halfWidth = dimensions.width / 2;
        const halfDepth = dimensions.depth / 2;
        value.boundary = [
            { x: center.x - halfWidth, z: center.z - halfDepth },
            { x: center.x + halfWidth, z: center.z - halfDepth },
            { x: center.x + halfWidth, z: center.z + halfDepth },
            { x: center.x - halfWidth, z: center.z + halfDepth },
        ];
        return this._gesture('Resize zone');
    }

    editZoneLabel(id, label) {
        this.calls.push(['editZoneLabel', id, label]);
        const value = this.state.layout.zones.find(item => item.zoneId === id);
        if (value) value.label = label;
        return this._gesture('Rename zone');
    }

    editZoneType(id, zoneType) {
        this.calls.push(['editZoneType', id, zoneType]);
        const value = this.state.layout.zones.find(item => item.zoneId === id);
        if (value) value.zoneType = zoneType;
        return this._gesture('Change zone purpose');
    }

    undo() {
        this.calls.push(['undo']);
        this.state.canUndo = false;
        this.state.canRedo = true;
        this._notify();
        return Promise.resolve(this.getState());
    }

    redo() {
        this.calls.push(['redo']);
        this.state.canUndo = true;
        this.state.canRedo = false;
        this._notify();
        return Promise.resolve(this.getState());
    }

    save() {
        this.calls.push(['save']);
        this.state.dirty = false;
        this.state.history = [];
        this.state.historyCursor = 0;
        this.state.canUndo = false;
        this._notify();
        return Promise.resolve({ state: this.getState(), receipt: { revision: 'rev-2' } });
    }
}

class FakeAdapter {
    constructor(type) {
        this.type = type;
        this.selectionHandler = null;
        this.selections = [];
        this.layouts = [];
        this.mounted = false;
        this.suspended = false;
        this.disposed = false;
        this.invalidations = 0;
        this.camera = null;
        this.ghost = null;
        this.proposalPreviews = [];
        this.transientPlacementMoves = [];
        this.transientPlacementDuplicates = [];
        this.transientZonePreviews = [];
        this.transientFloorMarkingPreviews = [];
        this.transientAislePreviews = [];
        this.transientPatternPreviews = [];
        this.navigationModes = [];
        this.zoomFactors = [];
        this.gridVisibility = [];
        this.layerVisibility = [];
        this.visualSettings = [];
        this.environmentSettings = [];
        this.scaleAtCalls = [];
        this.walkthrough = {
            supported: true,
            active: false,
            locked: false,
            reason: null,
            route: {
                active: false,
                reason: null,
            },
        };
        this.walkthroughEntries = [];
        this.walkthroughExits = [];
        this.walkthroughNavigations = [];
        this.walkthroughNavigationCancels = [];
        this.walkthroughHandler = null;
        this.walkthroughContextHandler = null;
        this.cameraOrientationHandler = null;
        this.cameraOrientation = {
            headingDegrees: 0,
            screenTop: { x: 0, z: 1 },
            northAxis: '+Z',
            eastAxis: '+X',
        };
        this.walkthroughContextFocus = null;
        this.drone = {
            supported: true,
            active: false,
            locked: false,
            assistedFlight: true,
            altitude: 0,
            currentSpeed: 0,
            nearestObstacleDistance: null,
            reason: null,
        };
        this.droneEntries = [];
        this.droneExits = [];
        this.immersiveSwitches = [];
        this.droneHandler = null;
        this.cameraView = {
            position: { x: 8, y: 7, z: 6 },
            quaternion: { x: 0, y: 0, z: 0, w: 1 },
            up: { x: 0, y: 1, z: 0 },
            target: { x: 2, y: 0, z: 3 },
            near: 0.01,
            far: 1000,
            navigationMode: 'orbit',
        };
        this.appliedCameraViews = [];
        this.fitFacilityCount = 0;
        this.fitLayoutCount = 0;
        this.frontViewCount = 0;
        this.topViewCount = 0;
        this.rightViewCount = 0;
        this.isometricCount = 0;
        this.viewportHandler = null;
        this.viewPreferences = { displayUnit: 'm', showGrid: true };
        this.viewportState = {
            projection: {
                width: 900,
                height: 600,
                scale: 20,
                offsetX: 50,
                offsetY: 20,
                minX: 0,
                minZ: 0,
                maxX: 40,
                maxZ: 30,
            },
            worldBounds: { minX: 0, minZ: 0, maxX: 40, maxZ: 30 },
            grid: { spacing: 1, majorSpacing: 5 },
            displayUnit: 'm',
            showGrid: true,
        };
        this.recordingCanvas = {
            width: 900,
            height: 600,
            captureStream() { return {}; },
        };
        this.motionPresentations = [];
        this.motionSnapshots = [];
        this.motionClearCount = 0;
        this.motionState = {
            loaded: false,
            playing: false,
            playbackRateMultiplier: 1,
        };
        this.motionStateHandler = null;
        this.activityPresentations = [];
        this.activitySnapshots = [];
        this.activityClearCount = 0;
        this.activityStateHandler = null;
        this.activityState = {
            loaded: false,
            playing: false,
            playbackRateMultiplier: 1,
            actors: [],
        };
        this.activity = {
            load: (payload, activeRevision) => {
                const scenario = payload.scenario || {};
                this.activityState = {
                    loaded: true,
                    scenarioId: scenario.scenarioId,
                    label: scenario.label,
                    status: 'ready',
                    playing: false,
                    elapsedSeconds: 0,
                    durationSeconds: Number(
                        scenario.cycleDurationSeconds || 0
                    ),
                    playbackRateMultiplier: 1,
                    actors: clone(scenario.actors || []),
                    visibleActorTypes: {
                        vehicle: true,
                        operator: true,
                        mobile_equipment: true,
                    },
                    pathsVisible: true,
                    prototypeMode: scenario.prototypeMode === true,
                    qualification: scenario.qualification,
                    activeRevision,
                };
                if (this.activityStateHandler) {
                    this.activityStateHandler(clone(this.activityState));
                }
                return clone(this.activityState);
            },
            play: () => {
                this.activityState.playing = true;
                if (this.activityStateHandler) {
                    this.activityStateHandler(clone(this.activityState));
                }
                return clone(this.activityState);
            },
            pause: () => {
                this.activityState.playing = false;
                if (this.activityStateHandler) {
                    this.activityStateHandler(clone(this.activityState));
                }
                return clone(this.activityState);
            },
            dispose: reason => {
                this.activityState = {
                    loaded: false,
                    playing: false,
                    statusReason: reason || null,
                    actors: [],
                };
                if (this.activityStateHandler) {
                    this.activityStateHandler(clone(this.activityState));
                }
                return true;
            },
            getState: () => clone(this.activityState),
        };
        this.motion = {
            load: (payload, activeRevision) => {
                const movement = payload.package.movement;
                this.motionState = {
                    loaded: true,
                    packageId: payload.package.packageId,
                    outcome: movement.outcome,
                    playing: false,
                    elapsedSeconds: 0,
                    durationSeconds: Number(
                        movement.estimatedTravelSeconds || 0
                    ),
                    distanceMeters: 0,
                    totalDistanceMeters: Number(
                        movement.totalDistanceMeters || 0
                    ),
                    sampleSpacingMeters: movement.clearance
                        && movement.clearance.sampleSpacingMeters || null,
                    clearanceAtValidatedSample: movement.clearance
                        && movement.clearance.samples[0] || null,
                    qualification: payload.package.qualification,
                    disclosure: 'fixture disclosure',
                    activeRevision: activeRevision,
                    playbackRateMultiplier: 1,
                };
                if (this.motionStateHandler) {
                    this.motionStateHandler(clone(this.motionState));
                }
                return clone(this.motionState);
            },
            play: () => {
                this.motionState.playing = true;
                if (this.motionStateHandler) {
                    this.motionStateHandler(clone(this.motionState));
                }
                return clone(this.motionState);
            },
            pause: () => {
                this.motionState.playing = false;
                if (this.motionStateHandler) {
                    this.motionStateHandler(clone(this.motionState));
                }
                return clone(this.motionState);
            },
            seek: value => {
                this.motionState.elapsedSeconds = Number(value || 0);
                if (this.motionStateHandler) {
                    this.motionStateHandler(clone(this.motionState));
                }
                return clone(this.motionState);
            },
            setRate: value => {
                this.motionState.playbackRateMultiplier = Number(value || 1);
                if (this.motionStateHandler) {
                    this.motionStateHandler(clone(this.motionState));
                }
                return clone(this.motionState);
            },
            dispose: reason => {
                this.motionState = {
                    loaded: false,
                    playing: false,
                    statusReason: reason || null,
                };
                if (this.motionStateHandler) {
                    this.motionStateHandler(clone(this.motionState));
                }
                return true;
            },
            getState: () => clone(this.motionState),
            setStateHandler: handler => {
                this.motionStateHandler = typeof handler === 'function'
                    ? handler : null;
                return Boolean(this.motionStateHandler);
            },
        };
    }

    mount(host) {
        this.host = host;
        this.mounted = true;
    }

    setSelectionHandler(handler) {
        this.selectionHandler = handler;
    }

    setSelection(value) {
        this.selections.push(clone(value));
    }

    setSelections(value) {
        this.selections.push(clone(value));
    }

    setLayout(value) {
        this.layouts.push(clone(value));
        if (this.viewportHandler) this.viewportHandler(this.getViewportState());
    }

    setViewportChangeHandler(handler) {
        this.viewportHandler = typeof handler === 'function' ? handler : null;
        if (this.viewportHandler) this.viewportHandler(this.getViewportState());
    }

    getViewportState() {
        return clone(this.viewportState);
    }

    setViewPreferences(value) {
        this.viewPreferences = Object.assign({}, this.viewPreferences, value || {});
        this.viewportState.displayUnit = this.viewPreferences.displayUnit;
        this.viewportState.showGrid = this.viewPreferences.showGrid;
        if (this.viewportHandler) this.viewportHandler(this.getViewportState());
        return true;
    }

    setEnvironmentSettings(value) {
        const settings = clone(value || {});
        this.environmentSettings.push(settings);
        if (settings.worldBounds) {
            this.viewportState.worldBounds = clone(settings.worldBounds);
            Object.assign(
                this.viewportState.projection,
                settings.worldBounds
            );
        }
        if (Number.isFinite(settings.floorGridSpacing)) {
            this.viewportState.grid.spacing = settings.floorGridSpacing;
        }
        if (Number.isFinite(settings.floorMajorGridSpacing)) {
            this.viewportState.grid.majorSpacing =
                settings.floorMajorGridSpacing;
        }
        if (this.viewportHandler) this.viewportHandler(this.getViewportState());
        return true;
    }

    setScaleAt(event, scale) {
        this.scaleAtCalls.push({ event: clone(event), scale });
        this.viewportState.projection.scale = scale;
        if (this.viewportHandler) this.viewportHandler(this.getViewportState());
        return true;
    }

    setGhostPlacement(value) {
        this.ghost = clone(value);
        return true;
    }

    setProposalPreview(value) {
        this.proposalPreviews.push(clone(value));
        return true;
    }

    setMotionPresentation(value) {
        this.motionPresentations.push(clone(value));
        return true;
    }

    updateMotionSnapshot(value) {
        this.motionSnapshots.push(clone(value));
        return true;
    }

    clearMotionPresentation() {
        this.motionClearCount += 1;
        return true;
    }

    setActivityPresentation(value) {
        this.activityPresentations.push(clone(value));
        return true;
    }

    updateActivitySnapshot(value) {
        this.activitySnapshots.push(clone(value));
        return true;
    }

    clearActivityPresentation() {
        this.activityClearCount += 1;
        return true;
    }

    setActivityStateHandler(handler) {
        this.activityStateHandler = typeof handler === 'function'
            ? handler : null;
        return Boolean(this.activityStateHandler);
    }

    getActivityState() {
        return clone(this.activityState);
    }

    setTransientPlacementMove(ids, delta) {
        this.transientPlacementMoves.push({
            ids: clone(ids),
            delta: clone(delta),
        });
        return true;
    }

    setTransientPlacementDuplicate(ids, delta) {
        this.transientPlacementDuplicates.push({
            ids: clone(ids),
            delta: clone(delta),
        });
        return true;
    }

    setTransientZonePreview(points, options) {
        this.transientZonePreviews.push({
            points: clone(points),
            options: clone(options),
        });
        return true;
    }

    setTransientFloorMarkingPreview(marking) {
        this.transientFloorMarkingPreviews.push(clone(marking));
        return true;
    }

    setTransientAislePreview(preview) {
        this.transientAislePreviews.push(clone(preview));
        return true;
    }

    setTransientPatternPreview(preview) {
        this.transientPatternPreviews.push(clone(preview));
        return true;
    }

    clientToWorld(event) {
        return event && event.world || { x: 0, y: 0, z: 0 };
    }

    worldPointOnFloor(event) {
        return event && event.world || null;
    }

    panByPixels(x, y) {
        this.lastPan = { x, y };
        if (this.viewportHandler) this.viewportHandler(this.getViewportState());
        return true;
    }

    zoomAt(event, factor) {
        this.lastZoom = { event, factor };
        this.viewportState.projection.scale *= factor;
        if (this.viewportHandler) this.viewportHandler(this.getViewportState());
        return true;
    }

    resolveMarquee() {
        return ['pl-a'];
    }

    setScene(input) {
        this.layouts.push(clone(input.layout));
        return Promise.resolve();
    }

    fit() {
        this.fitCount = (this.fitCount || 0) + 1;
        return { fitted: true };
    }

    fitFacility() {
        this.fitFacilityCount += 1;
        return true;
    }

    fitLayout() {
        this.fitLayoutCount += 1;
        return true;
    }

    frontView() {
        this.frontViewCount += 1;
        return true;
    }

    topView() {
        this.topViewCount += 1;
        return true;
    }

    rightView() {
        this.rightViewCount += 1;
        return true;
    }

    isometricView() {
        this.isometricCount += 1;
        return true;
    }

    setNavigationMode(mode) {
        this.navigationModes.push(mode);
        return true;
    }

    setWalkthroughStateHandler(handler) {
        this.walkthroughHandler = typeof handler === 'function' ? handler : null;
        if (this.walkthroughHandler) {
            this.walkthroughHandler(this.getWalkthroughState());
        }
        return Boolean(this.walkthroughHandler);
    }

    setMotionStateHandler(handler) {
        return this.motion.setStateHandler(handler);
    }

    setDroneStateHandler(handler) {
        this.droneHandler = typeof handler === 'function' ? handler : null;
        if (this.droneHandler) this.droneHandler(this.getDroneState());
        return Boolean(this.droneHandler);
    }

    setWalkthroughContextHandler(handler) {
        this.walkthroughContextHandler = typeof handler === 'function'
            ? handler : null;
        if (this.walkthroughContextHandler) {
            this.walkthroughContextHandler(clone(this.walkthroughContextFocus));
        }
        return Boolean(this.walkthroughContextHandler);
    }

    setCameraOrientationHandler(handler) {
        this.cameraOrientationHandler = typeof handler === 'function'
            ? handler : null;
        if (this.cameraOrientationHandler) {
            this.cameraOrientationHandler(clone(this.cameraOrientation));
        }
        return Boolean(this.cameraOrientationHandler);
    }

    emitCameraOrientation(value) {
        this.cameraOrientation = clone(value);
        if (this.cameraOrientationHandler) {
            this.cameraOrientationHandler(clone(this.cameraOrientation));
        }
    }

    getWalkthroughContextFocus() {
        return clone(this.walkthroughContextFocus);
    }

    getRecordingCanvas() {
        return this.mounted && !this.suspended ? this.recordingCanvas : null;
    }

    emitWalkthroughContext(value) {
        this.walkthroughContextFocus = clone(value || null);
        if (this.walkthroughContextHandler) {
            this.walkthroughContextHandler(
                clone(this.walkthroughContextFocus)
            );
        }
    }

    setWalkthroughCameraMode(mode) {
        this.walkthrough.cameraMode = mode;
        if (this.walkthroughHandler) this.walkthroughHandler(this.getWalkthroughState());
        return true;
    }

    getWalkthroughState() {
        return clone(this.walkthrough);
    }

    getDroneState() {
        return clone(this.drone);
    }

    enterDrone(value) {
        this.droneEntries.push(clone(value || {}));
        this.drone = Object.assign({}, this.drone, {
            active: true,
            locked: true,
            altitude: 12.5,
            currentSpeed: 5,
            nearestObstacleDistance: 2.75,
            reason: 'active',
        });
        if (this.droneHandler) this.droneHandler(this.getDroneState());
        return this.getDroneState();
    }

    exitDrone(reason) {
        this.droneExits.push(reason || null);
        this.drone = Object.assign({}, this.drone, {
            active: false,
            locked: false,
            currentSpeed: 0,
            reason: reason || 'exited',
        });
        if (this.droneHandler) this.droneHandler(this.getDroneState());
        return true;
    }

    enterWalkthrough(value) {
        this.walkthroughEntries.push(clone(value || {}));
        this.walkthrough = Object.assign({}, this.walkthrough, {
            active: true,
            locked: true,
            reason: 'active',
        });
        if (this.walkthroughHandler) {
            this.walkthroughHandler(this.getWalkthroughState());
        }
        return this.getWalkthroughState();
    }

    exitWalkthrough(reason) {
        this.walkthroughExits.push(reason || null);
        this.walkthrough = Object.assign({}, this.walkthrough, {
            active: false,
            locked: false,
            reason: reason || 'exited',
        });
        if (this.walkthroughHandler) {
            this.walkthroughHandler(this.getWalkthroughState());
        }
        return true;
    }

    switchImmersiveMode(mode) {
        this.immersiveSwitches.push(mode);
        if (mode === 'walkthrough') {
            this.drone = Object.assign({}, this.drone, {
                active: false,
                locked: false,
            });
            if (this.droneHandler) this.droneHandler(this.getDroneState());
            return this.enterWalkthrough({ immersiveHandoff: true });
        }
        this.walkthrough = Object.assign({}, this.walkthrough, {
            active: false,
            locked: false,
        });
        if (this.walkthroughHandler) {
            this.walkthroughHandler(this.getWalkthroughState());
        }
        return this.enterDrone({ immersiveHandoff: true });
    }

    navigateWalkthroughToPlacement(placementId) {
        this.walkthroughNavigations.push(placementId);
        this.walkthrough = Object.assign({}, this.walkthrough, {
            active: true,
            locked: true,
            reason: 'navigating',
            route: {
                active: true,
                reason: 'navigating',
                targetPlacementId: placementId,
            },
        });
        if (this.walkthroughHandler) {
            this.walkthroughHandler(this.getWalkthroughState());
        }
        return { ok: true, reason: 'routed' };
    }

    cancelWalkthroughNavigation(reason) {
        this.walkthroughNavigationCancels.push(reason || null);
        this.walkthrough = Object.assign({}, this.walkthrough, {
            route: {
                active: false,
                reason: reason || 'cancelled',
            },
        });
        if (this.walkthroughHandler) {
            this.walkthroughHandler(this.getWalkthroughState());
        }
        return true;
    }

    getCameraView() {
        return clone(this.cameraView);
    }

    applyCameraView(value) {
        this.appliedCameraViews.push(clone(value));
        this.cameraView = clone(value);
        return true;
    }

    zoomBy(factor) {
        this.zoomFactors.push(factor);
        return true;
    }

    setGridVisible(visible) {
        this.gridVisibility.push(Boolean(visible));
        return true;
    }

    setLayerVisibility(value) {
        const visibility = clone(value);
        this.layerVisibility.push(visibility);
        return visibility;
    }

    setVisualSettings(value) {
        const settings = clone(value);
        this.visualSettings.push(settings);
        return settings;
    }

    invalidate() {
        this.invalidations += 1;
    }

    suspend() {
        if (this.suspended) return false;
        this.suspended = true;
        return true;
    }

    resume() {
        if (!this.suspended) return false;
        this.suspended = false;
        return true;
    }

    getDiagnostics() {
        return { mounted: this.mounted && !this.suspended };
    }

    emitSelection(id, event) {
        if (this.selectionHandler) this.selectionHandler(id, this, event);
    }

    dispose() {
        this.disposed = true;
        this.viewportHandler = null;
    }
}

class FakeRecordingController {
    constructor(options) {
        this.options = options;
        this.calls = [];
        this.result = null;
        this.state = {
            status: 'idle',
            elapsedMs: 0,
            paused: false,
            format: {
                mimeType: 'video/webm;codecs=vp8',
                extension: 'webm',
                label: 'WebM (VP8)',
            },
            error: null,
        };
        this.disposed = false;
    }

    _emit() {
        if (this.options.onStateChange) {
            this.options.onStateChange(clone(this.state));
        }
    }

    start(settings) {
        this.calls.push(['start', settings]);
        this.state = Object.assign({}, this.state, {
            status: 'recording',
            elapsedMs: 0,
            paused: false,
            resolution: settings.resolution === '1080p'
                ? { width: 1920, height: 1080 }
                : { width: 900, height: 600 },
            fps: settings.fps,
        });
        this._emit();
        return Promise.resolve(this.getState());
    }

    pause() {
        this.calls.push(['pause']);
        this.state.status = 'paused';
        this.state.paused = true;
        this.state.elapsedMs = 2500;
        this._emit();
        return true;
    }

    resume() {
        this.calls.push(['resume']);
        this.state.status = 'recording';
        this.state.paused = false;
        this._emit();
        return true;
    }

    stop() {
        this.calls.push(['stop']);
        this.result = {
            url: 'blob:workspace-recording',
            filename: 'Workspace-test-walkthrough.webm',
            extension: 'webm',
            mimeType: 'video/webm;codecs=vp8',
            width: 1920,
            height: 1080,
            fps: 60,
            durationMs: 4500,
        };
        this.state.status = 'preview';
        this.state.paused = false;
        this.state.elapsedMs = 4500;
        this.state.filename = this.result.filename;
        this._emit();
        return Promise.resolve(this.getState());
    }

    discard() {
        this.calls.push(['discard']);
        this.result = null;
        this.state.status = 'idle';
        this.state.elapsedMs = 0;
        this.state.filename = null;
        this._emit();
        return this.getState();
    }

    download() {
        this.calls.push(['download']);
        return Boolean(this.result);
    }

    getState() {
        return clone(this.state);
    }

    getResult() {
        return clone(this.result);
    }

    dispose() {
        this.calls.push(['dispose']);
        this.disposed = true;
        return true;
    }
}

function fakeRecordingRuntime() {
    const runtime = {
        controllers: [],
        chooseRecordingFormat() {
            return {
                mimeType: 'video/webm;codecs=vp8',
                extension: 'webm',
                label: 'WebM (VP8)',
            };
        },
        createCanvasRecorder(options) {
            const controller = new FakeRecordingController(options);
            runtime.controllers.push(controller);
            return controller;
        },
    };
    return runtime;
}

class FakeController {
    constructor(adapters, initialCatalog) {
        this.adapters = adapters;
        this.layouts = [];
        this.catalogs = [clone(initialCatalog || [])];
        this.selections = [];
        this.fitCount = 0;
        this.fitFacilityCount = 0;
        this.fitLayoutCount = 0;
        this.topViewCount = 0;
        this.disposeCount = 0;
        this.suspendCount = 0;
        this.resumeCount = 0;
    }

    setAssetCatalog(value) {
        this.catalogs.push(clone(value));
    }

    setLayout(value) {
        this.layouts.push(clone(value));
        this.adapters.forEach(adapter => {
            if (adapter.setLayout) adapter.setLayout(value);
            else if (adapter.setScene) adapter.setScene({ layout: value });
        });
    }

    select(id) {
        this.selections.push(id);
        this.adapters.forEach(adapter => adapter.setSelection(id));
        return true;
    }

    clearSelection() {
        this.selections.push(null);
        this.adapters.forEach(adapter => adapter.setSelection(null));
    }

    fit() {
        return this.fitFacility();
    }

    fitFacility() {
        this.fitCount += 1;
        this.fitFacilityCount += 1;
        this.adapters.forEach(adapter => {
            if (typeof adapter.fitFacility === 'function') {
                adapter.fitFacility();
            } else if (typeof adapter.fit === 'function') adapter.fit();
        });
    }

    fitLayout() {
        this.fitLayoutCount += 1;
        this.adapters.forEach(adapter => {
            if (typeof adapter.fitLayout === 'function') adapter.fitLayout();
            else if (typeof adapter.fit === 'function') adapter.fit();
        });
    }

    topView() {
        this.topViewCount += 1;
        this.adapters.forEach(adapter => {
            if (typeof adapter.topView === 'function') adapter.topView();
        });
    }

    suspend() {
        this.suspendCount += 1;
        this.adapters.forEach(adapter => adapter.suspend());
        return true;
    }

    resume() {
        this.resumeCount += 1;
        this.adapters.forEach(adapter => adapter.resume());
        return true;
    }

    dispose() {
        this.disposeCount += 1;
        this.adapters.forEach(adapter => adapter.dispose());
    }
}

class FakeSpatialAdvisor {
    constructor() {
        this.requests = [];
        this.active = null;
        this.cancelCount = 0;
        this.destroyCount = 0;
    }

    request(payload) {
        if (this.active) this.cancel('superseded');
        this.requests.push(clone(payload));
        return new Promise((resolve, reject) => {
            this.active = { resolve, reject };
        });
    }

    cancel(reason) {
        if (!this.active) return false;
        this.cancelCount += 1;
        const error = new Error(reason || 'cancelled');
        error.name = 'AbortError';
        this.active.reject(error);
        this.active = null;
        return true;
    }

    resolve(advisory) {
        const active = this.active;
        this.active = null;
        active.resolve(clone(advisory));
    }

    destroy() {
        this.destroyCount += 1;
        this.cancel('destroyed');
        return true;
    }
}

function catalog() {
    return [
        {
            assetId: 'asset-rack',
            assetDefinitionRevision: 'revision-asset-rack',
            displayName: 'Pallet Rack',
            category: 'Storage',
        },
        {
            assetId: 'asset-forklift',
            assetDefinitionRevision: 'revision-asset-forklift',
            displayName: 'Electric Forklift',
            category: 'Material Handling',
        },
        {
            assetId: 'asset-machine',
            assetDefinitionRevision: 'revision-asset-machine',
            displayName: 'CNC Mill',
            category: 'Machines',
            manufacturer: 'InspectorPro Fixture Works',
            contextCard: {
                processStep: 'Machine the fixture plate',
                cycleTime: '4.8 min',
                throughput: '12 parts/hour',
                ppe: ['Eye protection', 'Safety footwear'],
                maintenanceNotes: ['Inspect way covers before service'],
                trainingNotes: ['Verify the work offset before cycle start'],
                qualityNotes: ['Confirm the first-piece inspection record'],
            },
        },
    ];
}

// Sage's 3D shots (SV1) in the fixture: animation frames that run themselves (an error in one is caught, as a browser
// reports it), a 3D view that is drawn and can be copied, waits that end at once or on a gate, and a JPEG encoder that
// notes what each shot saw. kit.onWait(milliseconds, count) runs as each wait starts.
function sageShotsFixture(options) {
    const data = fixture();
    const workspace = data.workspace;
    const three = data.three;
    let time = 0;
    const kit = { data, workspace, three, waits: [], shots: [], frameErrors: [], gates: [], onWait: null };
    data.documentRef.defaultView = Object.assign({
        requestAnimationFrame(callback) {
            setImmediate(() => {
                try { callback(time += 100); } catch (error) { kit.frameErrors.push(error); }
            });
            return 1;
        },
        cancelAnimationFrame() {},
        matchMedia() { return { matches: false }; },
    }, options && options.view);
    three.getDiagnostics = () => ({ mounted: true, status: 'ready', pendingLoads: 0 });
    three.renderRecordingFrame = () => three.getRecordingCanvas();
    workspace._sageShotWait = milliseconds => {
        kit.waits.push(milliseconds);
        if (kit.onWait) kit.onWait(milliseconds, kit.waits.length);
        return kit.gates.length ? kit.gates.shift() : Promise.resolve();
    };
    workspace._encodeSageShot = async () => {
        kit.shots.push({ camera: clone(three.cameraView), roof: workspace.layerVisibility.overhead });
        return { blob: { type: 'image/jpeg' }, width: 1280, height: 720 };
    };
    kit.views = [
        { label: 'Assembly Cell A06', from: 'south', roofHidden: false,
            camera: { position: { x: 20, y: 5, z: 10 }, target: { x: 20, y: 0.7, z: 18 }, fov: 50 } },
        { label: 'Dock Door S1', from: 'east', roofHidden: true,
            camera: { position: { x: 60, y: 30, z: 0 }, target: { x: 40, y: 1, z: 0 }, fov: 50 } },
    ];
    kit.request = extra => Object.assign({ siteId: 'site-a', layoutId: 'fl-workspace', revision: 'rev-1',
        views: kit.views }, extra);
    kit.gate = () => {
        let open = null;
        kit.gates.push(new Promise(resolve => { open = resolve; }));
        return open;
    };
    return kit;
}

// PROMISE, or a failure naming LABEL if it has not ended in MILLISECONDS (a capture stranded for good).
function within(promise, label, milliseconds = 3000) {
    let timer = null;
    return Promise.race([promise, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(label + ' never ended')), milliseconds);
    })]).finally(() => clearTimeout(timer));
}

async function until(predicate, rounds = 400) {
    for (let round = 0; round < rounds && !predicate(); round += 1) {
        await new Promise(resolve => setImmediate(resolve));
    }
}

function fixture(options) {
    const documentRef = new FakeDocument();
    const root = documentRef.createElement('div');
    const motionPanelHost = options && options.externalMotionPanel
        ? documentRef.createElement('aside') : null;
    const session = new FakeSession();
    const top = new FakeAdapter('top-plan');
    top.mounted = true;
    const three = options && options.noThree ? null : new FakeAdapter('three');
    const recordingRuntime = options && options.recordingRuntime
        || fakeRecordingRuntime();
    let controller = null;
    const layoutRuntime = {
        createTopPlanAdapter(host) {
            top.host = host;
            return top;
        },
        createEditor(config) {
            controller = new FakeController(config.adapters, config.assetCatalog);
            return controller;
        },
    };
    let projectedPoint = { x: 12.24, y: 0, z: -3.26 };
    const workspace = workspaceModule.createWorkspace({
        root,
        session,
        layoutRuntime,
        threeAdapter: three,
        recordingRuntime,
        patternRuntime: patternModule,
        navigationRuntime: options && options.navigationRuntime
            || navigationAuthoringModule,
        recordingCountdownSeconds: options
            && options.recordingCountdownSeconds,
        assetCatalog: options && options.assetCatalog || catalog(),
        loadAssetCatalog: options && options.loadAssetCatalog,
        externalCommandSurface: Boolean(
            options && options.externalCommandSurface
        ),
        motionPanelHost,
        gridSize: 0.5,
        planPreferenceStorage: options && options.planPreferenceStorage,
        eventToWorld(event) {
            return event && event.world
                ? event.world
                : projectedPoint;
        },
        marqueeResolver: options && options.marqueeResolver,
        keyboardPlacementPoint: options && options.keyboardPlacementPoint,
        spatialAdvisor: options && options.spatialAdvisor,
        motionTransport: options && options.motionTransport,
        designTransport: options && options.designTransport,
        capabilities: options && options.capabilities,
        ownsSpatialAdvisor: options && options.ownsSpatialAdvisor,
        useAuthoritativePlacementCandidates: Boolean(
            options && options.useAuthoritativePlacementCandidates
        ),
        onCommandStateChange: options && options.onCommandStateChange,
        floatingSurfaceRuntime: options && options.floatingSurfaceRuntime,
        floatingDom: options && options.floatingDom,
    });
    return {
        documentRef,
        root,
        motionPanelHost,
        session,
        top,
        three,
        recordingRuntime,
        get controller() { return controller; },
        workspace,
        setProjectedPoint(value) { projectedPoint = value; },
    };
}

function toolbarButton(data, command) {
    return data.root.querySelector(`[data-command="${command}"]`);
}

function planCard(data, placementId, rect) {
    const card = data.documentRef.createElement('g');
    card.setAttribute('class', 'ip-flw-plan-card');
    card.setAttribute('data-placement-id', placementId);
    card.getBoundingClientRect = function () {
        return Object.assign({}, rect, {
            right: rect.left + rect.width,
            bottom: rect.top + rect.height,
        });
    };
    data.workspace.planView.appendChild(card);
    return card;
}

function planZone(data, zoneId, rect) {
    const zoneNode = data.documentRef.createElement('polygon');
    zoneNode.setAttribute('data-zone-id', zoneId);
    zoneNode.getBoundingClientRect = function () {
        return Object.assign({}, rect, {
            right: rect.left + rect.width,
            bottom: rect.top + rect.height,
        });
    };
    data.workspace.planView.appendChild(zoneNode);
    return zoneNode;
}

function planFloorMarking(data, markingId, rect) {
    const node = data.documentRef.createElement('g');
    node.setAttribute('data-floor-marking-id', markingId);
    node.getBoundingClientRect = function () {
        return Object.assign({}, rect, {
            right: rect.left + rect.width,
            bottom: rect.top + rect.height,
        });
    };
    data.workspace.planView.appendChild(node);
    return node;
}

function assetRow(data, assetId) {
    return data.root.querySelector(`[data-asset-id="${assetId}"]`);
}

function assetAction(data, assetId, action) {
    const card = assetRow(data, assetId);
    return card && card.querySelector(
        `[data-asset-browser-action="${action}"]`
    );
}

function externalAssetTransfer(assetId) {
    const transfer = new FakeDataTransfer();
    transfer.setData(
        workspaceModule.ASSET_MIME,
        workspaceModule.createAssetDragPayload({
            assetId,
            assetDefinitionRevision: `revision-${assetId}`,
        }, 'external-drag-001')
    );
    return transfer;
}

async function main() {
    await check('resolved session error leaves the visible status bar', async () => {
        const data = fixture();
        // The real session returns Error references without JSON cloning.
        data.session.getState = function () {
            return Object.assign(clone(this.state), { lastError: this.state.lastError });
        };
        const interruption = new Error('Managed backend restart interrupted the held acknowledgment');
        data.session.state.lastError = interruption;
        data.session._notify();
        data.session._notify();
        assert.ok(data.workspace.statusText.textContent.includes(interruption.message));
        data.session.state.lastError = null;
        data.session._notify();
        assert.strictEqual(data.workspace.lastError, null);
        assert.ok(!data.workspace.statusText.textContent.includes(interruption.message));
        assert.ok(!data.workspace.statusText.textContent.includes('Error:'));
        data.workspace.destroy();
    });

    await check('resolving a session error preserves a newer workspace error', async () => {
        const data = fixture();
        data.session.getState = function () {
            return Object.assign(clone(this.state), { lastError: this.state.lastError });
        };
        data.session.state.lastError = new Error('Interrupted transaction');
        data.session._notify();
        const newer = new Error('Current workspace failure');
        data.workspace._setError(newer);
        data.session.state.lastError = null;
        data.session._notify();
        assert.strictEqual(data.workspace.lastError, newer);
        assert.ok(data.workspace.statusText.textContent.includes(newer.message));
        assert.ok(!data.workspace.statusText.textContent.includes('Interrupted transaction'));
        data.workspace.destroy();
    });

    await check('exports UMD and CommonJS API with pure helpers', async () => {
        assert.strictEqual(workspaceModule.API_VERSION, 1);
        assert.strictEqual(typeof workspaceModule.createWorkspace, 'function');
        const source = fs.readFileSync(MODULE_PATH, 'utf8');
        const browser = {};
        vm.runInNewContext(source, { globalThis: browser });
        assert.strictEqual(browser.InspectorProFacilityWorkspace.API_VERSION, 1);
        assert.strictEqual(
            typeof browser.InspectorProFacilityWorkspace.createWorkspace,
            'function'
        );
    });

    await check('drag payload is stable, minimal, and strictly parseable', async () => {
        const text = workspaceModule.createAssetDragPayload({
            assetId: 'asset-rack',
            assetDefinitionRevision: 'revision-rack',
            ignored: 'not serialized',
        }, 'drag-17');
        assert.deepStrictEqual(JSON.parse(text), {
            assetId: 'asset-rack',
            assetDefinitionRevision: 'revision-rack',
            dragSessionId: 'drag-17',
        });
        assert.deepStrictEqual(workspaceModule.parseAssetDragPayload(text), {
            assetId: 'asset-rack',
            assetDefinitionRevision: 'revision-rack',
            dragSessionId: 'drag-17',
        });
        assert.strictEqual(workspaceModule.parseAssetDragPayload('{bad'), null);
        assert.strictEqual(workspaceModule.parseAssetDragPayload(
            JSON.stringify({ assetId: 'x' })
        ), null);
    });

    await check('selection toolbar command sets stay compact and contextual',
        async () => {
            assert.deepStrictEqual(
                workspaceModule.selectionToolbarCommands(0),
                []
            );
            assert.deepStrictEqual(
                workspaceModule.selectionToolbarCommands(1),
                [
                    'rotate', 'offset', 'duplicate', 'vertical-stack',
                    'mirror', 'lock', 'delete',
                ]
            );
            assert.deepStrictEqual(
                workspaceModule.selectionToolbarCommands(2),
                [
                    'align', 'relative', 'distance', 'offset',
                    'duplicate', 'surface-stack', 'mirror', 'lock', 'delete',
                ]
            );
            assert.deepStrictEqual(
                workspaceModule.selectionToolbarCommands(3),
                [
                    'align', 'distribute', 'relative', 'offset',
                    'duplicate', 'surface-stack', 'mirror', 'lock', 'delete',
                ]
            );
        });

    await check('grid snap and quarter-turn quaternion are deterministic', async () => {
        assert.deepStrictEqual(
            workspaceModule.snapWorldPoint({ x: 1.24, y: 4, z: -1.26 }, 0.5),
            { x: 1, y: 4, z: -1.5 }
        );
        const q = workspaceModule.quarterTurnQuaternion(1);
        assert.ok(Math.abs(q.y - Math.SQRT1_2) < 1e-12);
        assert.ok(Math.abs(q.w - Math.SQRT1_2) < 1e-12);
        assert.deepStrictEqual(
            workspaceModule.quarterTurnQuaternion(4),
            { x: 0, y: 0, z: 0, w: 1 }
        );
    });

    await check('floor marking resize keeps the opposite rotated corner fixed',
        async () => {
            const marking = floorMarking('fm-resize', 'direction_arrow');
            marking.transform.rotationDegrees = 90;
            const resized = workspaceModule.resizeFloorMarkingFromHandle(
                marking,
                2,
                { x: 7, y: 0, z: -1 },
                0.5
            );
            assert.strictEqual(resized.width, 6);
            assert.strictEqual(resized.depth, 4);
            assert.deepStrictEqual(
                resized.transform.position,
                { x: 5, y: 0, z: 2 }
            );
            assert.strictEqual(resized.transform.rotationDegrees, 90);
            assert.strictEqual(resized.positionMode, 'manual');
        });

    await check('precision positioning helpers use real footprint edges', async () => {
        const precisionLayout = layout();
        precisionLayout.placements = [
            placement('pl-a', 'asset-a', 0, 0, 'manual'),
            placement('pl-b', 'asset-b', 5, 1, 'manual'),
            placement('pl-c', 'asset-c', 12, 2, 'manual'),
        ];
        const precisionCatalog = [
            {
                assetId: 'asset-a',
                assetDefinitionRevision: 'revision-asset-a',
                dimensions: { width: 2, depth: 2, height: 1 },
            },
            {
                assetId: 'asset-b',
                assetDefinitionRevision: 'revision-asset-b',
                dimensions: { width: 4, depth: 2, height: 1 },
            },
            {
                assetId: 'asset-c',
                assetDefinitionRevision: 'revision-asset-c',
                dimensions: { width: 2, depth: 2, height: 1 },
            },
        ];
        const aligned = workspaceModule.buildAlignmentUpdates(
            precisionLayout,
            precisionCatalog,
            ['pl-a', 'pl-b'],
            'left',
            'pl-a'
        );
        assert.deepStrictEqual(aligned.updates, [{
            placementId: 'pl-b',
            position: { x: 1, y: 0, z: 1 },
        }]);

        const distributed = workspaceModule.buildDistributionUpdates(
            precisionLayout,
            precisionCatalog,
            ['pl-a', 'pl-b', 'pl-c'],
            'x',
            'equal-gap'
        );
        assert.strictEqual(distributed.clearGap, 3);
        assert.deepStrictEqual(distributed.updates, [{
            placementId: 'pl-b',
            position: { x: 6, y: 0, z: 1 },
        }]);

        const relative = workspaceModule.buildRelativePositionUpdates(
            precisionLayout,
            precisionCatalog,
            ['pl-b'],
            'pl-a',
            'north',
            2,
            'center'
        );
        assert.deepStrictEqual(relative.updates, [{
            placementId: 'pl-b',
            position: { x: 0, y: 0, z: 4 },
        }]);

        assert.strictEqual(workspaceModule.measurePlacementDistance(
            precisionLayout,
            precisionCatalog,
            'pl-a',
            'pl-b',
            'horizontal-gap'
        ), 2);
        const distance = workspaceModule.buildDistanceUpdate(
            precisionLayout,
            precisionCatalog,
            'pl-a',
            'pl-b',
            'horizontal-gap',
            4
        );
        assert.deepStrictEqual(distance.updates, [{
            placementId: 'pl-b',
            position: { x: 7, y: 0, z: 1 },
        }]);
    });

    await check('precision positioning refuses to move locked equipment', async () => {
        const precisionLayout = layout();
        precisionLayout.placements = [
            placement('pl-a', 'asset-rack', 0, 0, 'manual'),
            placement('pl-b', 'asset-rack', 4, 1, 'locked'),
        ];
        assert.throws(() => workspaceModule.buildAlignmentUpdates(
            precisionLayout,
            catalog(),
            ['pl-a', 'pl-b'],
            'left',
            'pl-a'
        ), /Unlock/);
    });

    await check('asset browser placement helper is deterministic and collision-free',
        async () => {
            const source = layout();
            source.zones = [];
            const before = JSON.stringify(source);
            const selected = [{
                assetId: 'asset-rack',
                assetDefinitionRevision: 'revision-asset-rack',
                quantity: 2,
            }, {
                assetId: 'asset-machine',
                assetDefinitionRevision: 'revision-asset-machine',
                quantity: 1,
            }];
            const first = workspaceModule.buildAssetBatchPlacementRequests(
                selected,
                source,
                catalog(),
                { x: 10, y: 0, z: 8 },
                {
                    gridSize: 0.5,
                    worldBounds: { minX: 0, minZ: 0, maxX: 40, maxZ: 30 },
                }
            );
            const repeated = workspaceModule.buildAssetBatchPlacementRequests(
                selected,
                source,
                catalog(),
                { x: 10, y: 0, z: 8 },
                {
                    gridSize: 0.5,
                    worldBounds: { minX: 0, minZ: 0, maxX: 40, maxZ: 30 },
                }
            );
            assert.deepStrictEqual(first, repeated);
            assert.strictEqual(first.length, 3);
            assert.strictEqual(
                new Set(first.map(item => JSON.stringify(item.worldPosition))).size,
                3
            );
            assert.ok(first.every(item => item.positionMode === 'manual'));
            assert.strictEqual(JSON.stringify(source), before);
        });

    await check('asset browser places equipment in the nearest operational zone',
        async () => {
            const source = layout();
            source.placements = [];
            source.zones = [{
                zoneId: 'zn-receiving',
                zoneType: 'receiving',
                label: 'Receiving',
                boundary: [
                    { x: 24, z: 18 },
                    { x: 38, z: 18 },
                    { x: 38, z: 28 },
                    { x: 24, z: 28 },
                ],
                floorElevation: 0,
                anchors: [],
                evidence: [],
            }];
            const requests = workspaceModule.buildAssetBatchPlacementRequests(
                [{
                    assetId: 'asset-rack',
                    assetDefinitionRevision: 'revision-asset-rack',
                    quantity: 1,
                }],
                source,
                catalog(),
                { x: 10, y: 0, z: 8 },
                {
                    gridSize: 0.5,
                    worldBounds: { minX: 0, minZ: 0, maxX: 40, maxZ: 30 },
                }
            );
            assert.strictEqual(requests.length, 1);
            assert.ok(requests[0].worldPosition.x >= 24.6);
            assert.ok(requests[0].worldPosition.x <= 37.4);
            assert.ok(requests[0].worldPosition.z >= 18.4);
            assert.ok(requests[0].worldPosition.z <= 27.6);
        });

    await check('Auto Arrange request is declarative and preserves ownership',
        async () => {
            const state = new FakeSession().getState();
            const request = workspaceModule.buildAutoArrangeRequest(
                state,
                catalog(),
                'request-auto-arrange-001'
            );
            assert.strictEqual(request.objective, 'place_and_cleanup');
            assert.deepStrictEqual(
                request.assetSet.map(item => item.existingPlacementId),
                ['pl-a', 'pl-b']
            );
            assert.deepStrictEqual(
                request.cleanup.movableManualPlacementIds,
                []
            );
            assert.strictEqual(request.cleanup.moveAuto, true);
            assert.strictEqual(
                request.sourceRevisions.shell,
                state.baseLayout.sourceShellRef.shellRevision
            );
            const serialized = JSON.stringify(request);
            ['"x"', '"y"', '"z"', '"position"', '"transform"',
                '"quaternion"'].forEach(key => {
                assert.strictEqual(serialized.includes(key), false);
            });

            const empty = clone(state);
            empty.baseLayout.placements = [];
            empty.layout.placements = [];
            const seeded = workspaceModule.buildAutoArrangeRequest(
                empty,
                catalog(),
                'request-seed-001'
            );
            assert.strictEqual(seeded.assetSet.length, 3);
            assert.ok(seeded.assetSet.every(
                item => item.existingPlacementId === undefined
            ));
        });

    await check('a proposal that adds walls says so: interior walls by id, the outer walls as one', async () => {
        const wall = (id, x) => ({ wallId: id, start: { x, z: 5 }, end: { x, z: 9 }, thicknessMeters: 0.2,
            heightMeters: 3 });
        const outline = { settings: { boundary: [{ x: 5, z: 5 }, { x: 35, z: 5 }, { x: 35, z: 25 }],
            heightMeters: 6, thicknessMeters: 0.3 } };
        const saved = layout();
        const converted = clone(saved);
        converted.extensions = Object.assign({}, converted.extensions, {
            facilityInteriorWalls: { version: 1, walls: [wall('iw-a', 15), wall('iw-b', 20)] },
            facilityPerimeterWalls: clone(outline),
        });
        converted.zones = (converted.zones || []).concat([{ zoneId: 'zn-office', label: 'Office' }]);
        const added = workspaceModule.buildLayoutProposalReview(saved, converted);
        assert.deepStrictEqual([added.wallChanges, added.outerWallChange],
            [{ added: 2, changed: 0, removed: 0 }, 'added']);
        assert.strictEqual(workspaceModule.proposalPlainChangeSummary(added, {}),
            'Changes: new outer walls, 2 new walls, 1 new zone.');
        const moved = clone(converted);
        moved.extensions.facilityInteriorWalls.walls[0].end.z = 10;
        moved.extensions.facilityPerimeterWalls.settings.heightMeters = 7;
        moved.extensions.facilityInteriorWalls.walls.pop();
        assert.strictEqual(workspaceModule.proposalPlainChangeSummary(
            workspaceModule.buildLayoutProposalReview(converted, moved), {}),
        'Changes: changed outer walls, 1 changed wall, 1 removed wall.');
        const bare = clone(moved);
        delete bare.extensions.facilityPerimeterWalls;
        assert.strictEqual(workspaceModule.proposalPlainChangeSummary(
            workspaceModule.buildLayoutProposalReview(moved, bare), {}), 'Changes: removed outer walls.');
        assert.strictEqual(workspaceModule.proposalPlainChangeSummary(
            workspaceModule.buildLayoutProposalReview(saved, clone(saved)), {}),
        'No items, walls, zones or aisles change.');
    });

    await check('proposal review diff is stable-ID based and remains pure',
        async () => {
            const saved = layout();
            const proposed = clone(saved);
            proposed.placements[0].transform.position.x = 11;
            proposed.placements.pop();
            proposed.placements.push(placement(
                'pl-new',
                'asset-machine',
                7,
                3,
                'auto'
            ));
            const savedBefore = JSON.stringify(saved);
            const proposedBefore = JSON.stringify(proposed);
            const review = workspaceModule.buildLayoutProposalReview(
                saved,
                proposed
            );
            assert.deepStrictEqual(review.newPlacementIds, ['pl-new']);
            assert.deepStrictEqual(review.movedPlacementIds, ['pl-a']);
            assert.deepStrictEqual(review.removedPlacementIds, ['pl-b']);
            assert.deepStrictEqual(
                review.beforePlacements.map(item => item.placementId),
                ['pl-a', 'pl-b']
            );
            assert.deepStrictEqual(
                review.proposedPlacements.map(item => item.placementId),
                ['pl-a', 'pl-new']
            );
            assert.strictEqual(JSON.stringify(saved), savedBefore);
            assert.strictEqual(JSON.stringify(proposed), proposedBefore);
            assert.deepStrictEqual(review.removedWalks, []);
            assert.deepStrictEqual(review.removedNames, ['pl-b']);
            assert.strictEqual(
                workspaceModule.proposalPlainChangeSummary(review, {}),
                'Changes: 1 new item, 1 moved item, 1 removed item. Removes pl-b.'
            );
            // A cleared zone (the user, 2026-11-02): its floor markings count,
            // and what goes is named, by label where it has one.
            const marked = clone(saved);
            marked.placements[1].metadata = { instanceLabel: 'A05 kit cart' };
            marked.floorMarkings = [
                { markingId: 'fm-bay', label: 'A05 kit cart bay', text: 'KIT CART' },
                { markingId: 'fm-text', text: 'A05' },
                { markingId: 'fm-stays', label: 'Aisle edge' },
            ];
            const cleared = clone(marked);
            cleared.placements.pop();
            cleared.floorMarkings = [{ markingId: 'fm-stays', label: 'Aisle edge' }];
            const clearReview = workspaceModule.buildLayoutProposalReview(marked, cleared);
            assert.deepStrictEqual(clearReview.removedNames, [
                'A05 kit cart', 'A05 kit cart bay (floor marking)', 'A05 (floor marking)']);
            assert.strictEqual(
                workspaceModule.proposalPlainChangeSummary(clearReview, {}),
                'Changes: 1 removed item, 2 removed floor markings. Removes A05 kit cart, '
                    + 'A05 kit cart bay (floor marking) and A05 (floor marking).'
            );
            const many = clone(saved);
            many.floorMarkings = Array.from({ length: 26 }, function (unused, index) {
                return { markingId: 'fm-' + index, label: 'Line ' + index };
            });
            const manyText = workspaceModule.proposalPlainChangeSummary(
                workspaceModule.buildLayoutProposalReview(many, saved), {});
            assert.ok(manyText.startsWith(
                'Changes: 26 removed floor markings. Removes Line 0 (floor marking), '));
            assert.ok(manyText.endsWith('Line 23 (floor marking) and 2 more.'));
            // A saved walk that goes is named (the user, 2026-11-01): its
            // walker and the places it stops at; a walk that stays is not.
            function walk(id, walker, stops) {
                return {
                    movementProgramId: id,
                    actorPlacementId: walker,
                    orderedStops: stops.map(function (anchor, index) {
                        return { stopId: 'nst-' + id + '-' + index, navigationAnchorId: anchor };
                    }),
                };
            }
            const walked = clone(saved);
            walked.extensions = { facilityNavigation: { movementPrograms: [
                walk('nmp-a', 'pl-a', ['na-home', 'na-b', 'na-home', 'na-c', 'na-d']),
                walk('nmp-b', 'pl-b', ['na-e']),
                walk('nmp-gone', 'pl-gone', ['na-f', 'na-g']),
            ] } };
            const unwalked = clone(proposed);
            unwalked.extensions = { facilityNavigation: { movementPrograms: [
                walk('nmp-b', 'pl-b', ['na-e']),
            ] } };
            const walkReview = workspaceModule.buildLayoutProposalReview(walked, unwalked);
            assert.deepStrictEqual(walkReview.removedWalks, [
                "the pl-a's saved walk (4 stops)",
                'saved walk nmp-gone (2 stops)',
            ]);
            assert.strictEqual(
                workspaceModule.proposalPlainChangeSummary(walkReview, {}),
                'Changes: 1 new item, 1 moved item, 1 removed item. Removes pl-b. Also removes '
                    + "the pl-a's saved walk (4 stops) and saved walk nmp-gone (2 stops)."
            );
            const noBaseline = workspaceModule.proposalDiagnosticSummary({
                metrics: { clearanceConflicts: 2 },
            });
            assert.ok(noBaseline.includes('baseline comparison unavailable'));
            assert.ok(noBaseline.includes(
                'new-hard-finding comparison not reported'
            ));
        });

    await check('builds accessible CAD workspace with transient asset browser',
        async () => {
            const data = fixture();
            assert.strictEqual(
                data.root.getAttribute('aria-label'),
                'Facility layout workspace'
            );
            assert.strictEqual(
                data.root.querySelector('[role="toolbar"]').getAttribute('aria-label'),
                'Facility layout tools'
            );
            assert.ok(data.root.textContent === '' || data.root.children.length > 0);
            assert.strictEqual(data.root.querySelectorAll('.ip-flw-assets').length, 0);
            assert.strictEqual(data.workspace.shell.children.length, 3);
            assert.strictEqual(data.workspace.designPanel.hidden, true);
            assert.strictEqual(data.workspace.assetBrowser.hidden, true);
            assert.strictEqual(
                data.workspace.assetBrowser.getAttribute('role'),
                'dialog'
            );
            assert.strictEqual(
                data.workspace.assetGrid.querySelectorAll(
                    '.ip-flw-asset-card'
                ).length,
                3
            );
            // The standing advisory line was removed: it kept the warning strip
            // lit over the viewport at all times. The strip itself stays in the
            // tree because the placement-alternative controls live in it, and is
            // shown only while those controls are on offer.
            assert.strictEqual(
                data.root.querySelector('.ip-flw-advisory-authority'),
                null
            );
            assert.strictEqual(data.workspace.validationNotice.hidden, true);
            assert.strictEqual(
                data.workspace.advisoryLiveRegion.getAttribute('aria-live'),
                'polite'
            );
            assert.strictEqual(
                data.workspace.ghostOverlay.getAttribute('aria-hidden'),
                'true'
            );
            assert.strictEqual(
                data.root.querySelector('[data-view="plan"]').getAttribute('aria-selected'),
                'true'
            );
            assert.strictEqual(
                toolbarButton(data, 'delete').getAttribute('aria-label'),
                'Delete'
            );
            assert.strictEqual(
                toolbarButton(data, 'assets').getAttribute('aria-label'),
                'Open asset library'
            );
            assert.strictEqual(data.workspace.threeTab.disabled, false);
            assert.strictEqual(
                toolbarButton(data, 'select').getAttribute('aria-pressed'),
                'true'
            );
            assert.strictEqual(
                toolbarButton(data, 'delete').getAttribute('aria-pressed'),
                null
            );
            assert.strictEqual(
                data.workspace.getCommandStates().select.active,
                true
            );
            data.workspace.destroy();
        });

    await check('publishes ribbon-ready command state for external command surfaces',
        async () => {
            const updates = [];
            const data = fixture({
                onCommandStateChange(states) { updates.push(states); },
            });
            assert.ok(updates.length > 0);
            assert.strictEqual(data.workspace.getCommandStates().select.active, true);
            await data.workspace.executeCommand('pan');
            let states = data.workspace.getCommandStates();
            assert.strictEqual(states.select.active, false);
            assert.strictEqual(states.pan.active, true);
            data.session.select('pl-a');
            states = data.workspace.getCommandStates();
            assert.strictEqual(states.duplicate.disabled, false);
            await data.workspace.executeCommand('lock');
            await data.workspace.whenIdle();
            states = data.workspace.getCommandStates();
            assert.strictEqual(states.lock.active, true);
            assert.strictEqual(states.lock.label, 'Unlock');
            assert.ok(updates.at(-1).lock.active);
            data.workspace.destroy();
        });

    await check('external command surface structurally removes the local toolbar row',
        async () => {
            const data = fixture({ externalCommandSurface: true });
            assert.strictEqual(data.workspace.toolbar.hidden, true);
            assert.strictEqual(
                data.workspace.toolbar.getAttribute('aria-hidden'),
                'true'
            );
            assert.strictEqual(
                data.workspace.toolbar.getAttribute('style'),
                'display:none'
            );
            assert.ok(data.root.className.includes(
                'ip-flw-external-command-surface'
            ));
            assert.strictEqual(
                data.workspace.getCommandStates().select.active,
                true
            );
            data.workspace.destroy();
        });

    await check('U-cell preview rearranges a heterogeneous selected cell atomically',
        async () => {
            const data = fixture({ externalCommandSurface: true });
            const marking = floorMarking('fm-cell', 'direction_arrow');
            marking.transform.position = { x: 3, y: 0, z: 1.5 };
            data.session.state.layout.floorMarkings.push(marking);
            data.session.selectMany(['pl-a', 'pl-b', 'fm-cell']);

            await data.workspace.executeCommand('cell-layout');
            assert.strictEqual(data.workspace.patternDialog.hidden, false);
            assert.strictEqual(
                data.root.getAttribute('data-pattern-open'),
                'true'
            );
            assert.strictEqual(data.workspace.getState().viewMode, 'plan');
            let preview = data.top.transientPatternPreviews.at(-1);
            assert.strictEqual(preview.mode, 'cell-layout');
            assert.strictEqual(preview.shape, 'u');
            assert.strictEqual(preview.seedCount, 3);
            assert.strictEqual(preview.moves.length, 3);
            assert.strictEqual(preview.copies.length, 0);

            const width = data.workspace.patternBody.querySelector(
                '[data-pattern-field="width"]'
            );
            const depth = data.workspace.patternBody.querySelector(
                '[data-pattern-field="depth"]'
            );
            width.value = '20';
            width.dispatch('input');
            width.dispatch('change');
            assert.strictEqual(
                data.workspace.patternBody.querySelector(
                    '[data-pattern-field="depth"]'
                ),
                depth
            );
            depth.value = '16';
            depth.dispatch('input');
            depth.dispatch('change');
            preview = data.top.transientPatternPreviews.at(-1);
            assert.strictEqual(preview.guide.width, 20);
            assert.strictEqual(preview.guide.depth, 16);

            const invert = data.workspace.patternBody.querySelector(
                '[data-pattern-field="invertU"]'
            );
            invert.checked = true;
            invert.dispatch('change');
            preview = data.top.transientPatternPreviews.at(-1);
            assert.strictEqual(preview.inverted, true);
            assert.strictEqual(preview.guide.inverted, true);

            const shape = data.workspace.patternBody.querySelector(
                '[data-pattern-field="shape"]'
            );
            shape.value = 'serpentine';
            shape.dispatch('change');
            preview = data.top.transientPatternPreviews.at(-1);
            assert.strictEqual(preview.shape, 'serpentine');
            assert.strictEqual(preview.moves.length, 3);

            data.workspace.patternApply.dispatch('click');
            await data.workspace.whenIdle();
            const calls = data.session.calls.filter(function (call) {
                return call[0] === 'applyPattern';
            });
            assert.strictEqual(calls.length, 1);
            assert.strictEqual(calls[0][1].mode, 'cell-layout');
            assert.strictEqual(calls[0][1].shape, 'serpentine');
            assert.strictEqual(data.session.state.history.length, 1);
            assert.strictEqual(data.workspace.patternDialog.hidden, true);
            assert.strictEqual(data.top.transientPatternPreviews.at(-1), null);
            data.workspace.destroy();
        });

    await check('linear pattern propagates a selected named cell and its contents',
        async () => {
            const data = fixture({ externalCommandSurface: true });
            const marking = floorMarking('fm-cell', 'direction_arrow');
            marking.transform.position = { x: 2, y: 0, z: 2 };
            data.session.state.layout.floorMarkings.push(marking);
            data.session.select('zn-a');

            await data.workspace.executeCommand('linear-pattern');
            let preview = data.top.transientPatternPreviews.at(-1);
            assert.strictEqual(preview.mode, 'linear');
            assert.strictEqual(preview.seedCount, 3);
            assert.deepStrictEqual(
                Array.from(new Set(preview.copies.map(item => item.kind))).sort(),
                ['floor-marking', 'placement', 'zone']
            );
            const count = data.workspace.patternBody.querySelector(
                '[data-pattern-field="count"]'
            );
            count.focus();
            count.value = '4';
            count.dispatch('input');
            preview = data.top.transientPatternPreviews.at(-1);
            assert.strictEqual(preview.count, 4);
            assert.strictEqual(preview.copies.length, 9);
            assert.strictEqual(data.documentRef.activeElement, count);

            data.workspace.patternApply.dispatch('click');
            await data.workspace.whenIdle();
            const state = data.session.getState();
            assert.strictEqual(state.layout.placements.length, 5);
            assert.strictEqual(state.layout.floorMarkings.length, 4);
            assert.strictEqual(state.layout.zones.length, 4);
            assert.strictEqual(state.selection.length, 9);
            assert.strictEqual(state.history.length, 1);
            assert.strictEqual(state.history[0].operationCount, 9);
            assert.strictEqual(data.workspace.patternDialog.hidden, true);
            data.workspace.destroy();
        });

    await check('surface placement exposes and uses a catalog-defined worktop',
        async () => {
            const records = catalog();
            Object.assign(records[0], {
                width: 3,
                depth: 2,
                height: 1,
                supportSurfaces: [{
                    surfaceId: 'worktop',
                    label: 'Worktop',
                    localFrame: {
                        origin: { x: 0, y: 0.9, z: 0 },
                        xAxis: { x: 1, y: 0, z: 0 },
                        zAxis: { x: 0, y: 0, z: 1 },
                        normal: { x: 0, y: 1, z: 0 },
                    },
                    bounds: {
                        minimumX: -1.4,
                        maximumX: 1.4,
                        minimumZ: -0.9,
                        maximumZ: 0.9,
                    },
                    allowedSides: ['above'],
                    evidenceStatus: 'derived',
                }],
            });
            Object.assign(records[1], { width: 0.5, depth: 0.4, height: 0.6 });
            const data = fixture({
                externalCommandSurface: true,
                assetCatalog: records,
            });
            data.session.selectMany(['pl-a', 'pl-b']);

            await data.workspace.executeCommand('surface-stack');
            const surface = data.workspace.patternBody.querySelector(
                '[data-pattern-field="surfaceId"]'
            );
            const side = data.workspace.patternBody.querySelector(
                '[data-pattern-field="surfaceSide"]'
            );
            const preview = data.top.transientPatternPreviews.at(-1);
            assert.strictEqual(surface.value, 'worktop');
            assert.strictEqual(side.value, 'above');
            assert.strictEqual(preview.guide.surfaceId, 'worktop');
            assert.strictEqual(
                preview.relationships[0].snapRelationship.surfaceSource,
                'asset_definition'
            );
            assert.strictEqual(
                preview.relationships[0].snapRelationship.evidenceStatus,
                'derived'
            );
            data.workspace.closePatternDialog(false);
            data.workspace.destroy();
        });

    await check('perimeter pattern previews and creates independent guarding',
        async () => {
            const data = fixture({ externalCommandSurface: true });
            data.session.select('pl-a');
            await data.workspace.executeCommand('perimeter-pattern');
            assert.strictEqual(data.workspace.patternDialog.hidden, false);
            let preview = data.top.transientPatternPreviews.at(-1);
            assert.strictEqual(preview.mode, 'perimeter');
            const widthCount = data.workspace.patternBody.querySelector(
                '[data-pattern-field="perimeterWidthCount"]'
            );
            const depthCount = data.workspace.patternBody.querySelector(
                '[data-pattern-field="perimeterDepthCount"]'
            );
            const gap = data.workspace.patternBody.querySelector(
                '[data-pattern-field="perimeterClearGap"]'
            );
            widthCount.value = '3';
            widthCount.dispatch('input');
            depthCount.value = '2';
            depthCount.dispatch('input');
            gap.value = '0';
            gap.dispatch('input');
            preview = data.top.transientPatternPreviews.at(-1);
            assert.strictEqual(preview.count, 10);
            assert.strictEqual(preview.copies.length, 9);
            assert.strictEqual(preview.guide.clearGap, 0);

            data.workspace.patternApply.dispatch('click');
            await data.workspace.whenIdle();
            assert.strictEqual(data.session.state.layout.placements.length, 11);
            assert.strictEqual(data.session.state.selection.length, 9);
            assert.strictEqual(data.session.state.history.length, 1);
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'applyPattern')
                    .at(-1)[1].mode,
                'perimeter'
            );
            data.workspace.destroy();
        });

    await check('Swap exchanges two complete selected cell zones', async () => {
        const data = fixture({ externalCommandSurface: true });
        data.session.state.layout.zones.push({
            zoneId: 'zn-b',
            zoneType: 'workcell',
            label: 'Finishing cell',
            boundary: [
                { x: 4, z: 0 }, { x: 8, z: 0 },
                { x: 8, z: 3 }, { x: 4, z: 3 },
            ],
            floorElevation: 0,
            anchors: [],
            evidence: [],
        });
        data.session.selectMany(['zn-a', 'zn-b']);
        assert.strictEqual(data.workspace.getCommandStates().swap.disabled, false);
        await data.workspace.executeCommand('swap');
        let preview = data.top.transientPatternPreviews.at(-1);
        assert.strictEqual(preview.mode, 'swap');
        assert.strictEqual(preview.moves.length, 4);
        data.workspace.patternApply.dispatch('click');
        await data.workspace.whenIdle();
        assert.strictEqual(
            data.session.state.layout.placements.find(
                item => item.placementId === 'pl-a'
            ).transform.position.x,
            5
        );
        assert.strictEqual(
            data.session.state.layout.placements.find(
                item => item.placementId === 'pl-b'
            ).transform.position.x,
            1
        );
        assert.deepStrictEqual(data.session.state.layout.zones[0].boundary[0], {
            x: 4,
            z: 0,
        });
        assert.strictEqual(data.session.state.history.length, 1);
        data.workspace.destroy();
    });

    await check('Clear All confirms once and preserves facility plan settings',
        async () => {
            const data = fixture({ externalCommandSurface: true });
            data.session.state.layout.extensions = {
                facilityPlan: {
                    widthMeters: 40,
                    depthMeters: 30,
                    minorGridMeters: 1,
                    majorGridMeters: 5,
                },
            };
            const settings = clone(data.session.state.layout.extensions);
            assert.strictEqual(
                data.workspace.getCommandStates()['clear-all'].disabled,
                false
            );
            await data.workspace.executeCommand('clear-all');
            assert.strictEqual(data.workspace.clearAllDialog.hidden, false);
            data.workspace.clearAllDialog.querySelector(
                '[data-clear-all-action="cancel"]'
            ).dispatch('click');
            assert.strictEqual(data.session.state.layout.placements.length, 2);
            assert.strictEqual(data.session.calls.filter(
                call => call[0] === 'clearLayout'
            ).length, 0);

            await data.workspace.executeCommand('clear-all');
            data.workspace.clearAllDialog.querySelector(
                '[data-clear-all-action="apply"]'
            ).dispatch('click');
            await data.workspace.whenIdle();
            assert.strictEqual(data.session.state.layout.placements.length, 0);
            assert.strictEqual(data.session.state.layout.zones.length, 0);
            assert.deepStrictEqual(data.session.state.layout.extensions, settings);
            assert.strictEqual(data.session.state.history.length, 1);
            assert.strictEqual(data.workspace.clearAllDialog.hidden, true);
            assert.strictEqual(
                data.workspace.getCommandStates()['clear-all'].disabled,
                true
            );
            data.workspace.destroy();
        });

    await check('mirror previews and copies a complete cell across a picked axis',
        async () => {
            const data = fixture({ externalCommandSurface: true });
            const marking = floorMarking('fm-cell', 'direction_arrow');
            marking.transform.position = { x: 2, y: 0, z: 2 };
            data.session.state.layout.floorMarkings.push(marking);
            data.session.select('zn-a');

            await data.workspace.executeCommand('mirror');
            assert.strictEqual(data.workspace.patternDialog.hidden, false);
            let preview = data.top.transientPatternPreviews.at(-1);
            assert.strictEqual(preview.mode, 'mirror');
            assert.strictEqual(preview.seedCount, 3);
            assert.deepStrictEqual(
                Array.from(new Set(preview.copies.map(item => item.kind))).sort(),
                ['floor-marking', 'placement', 'zone']
            );

            data.workspace.patternBody.querySelector(
                '[data-pattern-action="pick-mirror-axis"]'
            ).dispatch('click');
            data.workspace.planView.dispatch('pointerdown', {
                world: { x: 10.24, y: 0, z: 2 },
                pointerId: 1,
            });
            preview = data.top.transientPatternPreviews.at(-1);
            assert.strictEqual(preview.guide.start.x, 10);
            assert.strictEqual(preview.guide.end.x, 10);

            const axisMode = data.workspace.patternBody.querySelector(
                '[data-pattern-field="mirrorAxisMode"]'
            );
            axisMode.value = 'two-point';
            axisMode.dispatch('change');
            data.workspace.patternBody.querySelector(
                '[data-pattern-action="pick-mirror-axis"]'
            ).dispatch('click');
            data.workspace.planView.dispatch('pointerdown', {
                world: { x: 7.1, y: 0, z: 1.2 },
                pointerId: 2,
            });
            data.workspace.planView.dispatch('pointerdown', {
                world: { x: 9.1, y: 0, z: 4.2 },
                pointerId: 3,
            });
            preview = data.top.transientPatternPreviews.at(-1);
            assert.deepStrictEqual(preview.guide.start, { x: 7, z: 1 });
            assert.deepStrictEqual(preview.guide.end, { x: 9, z: 4 });
            assert.strictEqual(
                data.root.getAttribute('data-mirror-axis-picking'),
                null
            );

            data.workspace.patternApply.dispatch('click');
            await data.workspace.whenIdle();
            const calls = data.session.calls.filter(function (call) {
                return call[0] === 'applyPattern';
            });
            assert.strictEqual(calls.length, 1);
            assert.strictEqual(calls[0][1].mode, 'mirror');
            assert.strictEqual(calls[0][1].copies.length, 3);
            assert.strictEqual(data.session.state.layout.placements.length, 3);
            assert.strictEqual(data.session.state.layout.floorMarkings.length, 2);
            assert.strictEqual(data.session.state.layout.zones.length, 2);
            assert.strictEqual(data.session.state.history.length, 1);
            data.workspace.destroy();
        });

    await check('Position panel aligns a multi-selection in one gesture',
        async () => {
            const data = fixture({ externalCommandSurface: true });
            data.session.selectMany(['pl-a', 'pl-b']);
            let states = data.workspace.getCommandStates();
            assert.strictEqual(states.align.disabled, false);
            assert.strictEqual(states.distribute.disabled, true);
            await data.workspace.executeCommand('align');
            assert.strictEqual(data.workspace.precisionDialog.hidden, false);
            assert.strictEqual(
                data.root.getAttribute('data-precision-open'),
                'true'
            );
            states = data.workspace.getCommandStates();
            assert.strictEqual(states.align.active, true);
            data.workspace.precisionApply.dispatch('click');
            await data.workspace.whenIdle();
            const calls = data.session.calls.filter(function (call) {
                return call[0] === 'movePlacements';
            });
            assert.strictEqual(calls.length, 1);
            assert.strictEqual(calls[0][1].length, 1);
            assert.deepStrictEqual(calls[0][1][0], {
                placementId: 'pl-b',
                position: { x: 1, y: 0, z: 2 },
            });
            assert.strictEqual(data.workspace.precisionDialog.hidden, true);
            assert.strictEqual(data.session.state.history.length, 1);
            data.workspace.destroy();
        });

    await check('command panels move by title bar within workspace bounds',
        async () => {
            const data = fixture({ externalCommandSurface: true });
            const before = JSON.stringify(data.session.getState().layout);
            [
                data.workspace.precisionDialog,
                data.workspace.patternDialog,
                data.workspace.planSettingsDialog,
                data.workspace.clearAllDialog,
            ].forEach(function (dialog) {
                const handle = dialog.querySelector(
                    '.ip-flw-precision-header'
                );
                assert.strictEqual(
                    handle.getAttribute('data-dialog-drag-handle'),
                    'true'
                );
                assert.strictEqual(handle.getAttribute('tabindex'), '0');
                assert.ok(handle.getAttribute('aria-label').startsWith('Move '));
            });

            data.root.getBoundingClientRect = function () {
                return {
                    left: 0, top: 0, right: 1000, bottom: 700,
                    width: 1000, height: 700,
                };
            };
            data.workspace.shell.getBoundingClientRect = function () {
                return {
                    left: 0, top: 80, right: 1000, bottom: 660,
                    width: 1000, height: 580,
                };
            };
            const dialog = data.workspace.patternDialog;
            dialog.hidden = false;
            dialog.getBoundingClientRect = function () {
                const left = Number.parseFloat(dialog.style.left) || 600;
                const top = Number.parseFloat(dialog.style.top) || 120;
                return {
                    left: left,
                    top: top,
                    right: left + 350,
                    bottom: top + 260,
                    width: 350,
                    height: 260,
                };
            };
            const handle = dialog.querySelector('.ip-flw-precision-header');

            handle.dispatch('pointerdown', {
                target: data.workspace.patternClose,
                button: 0,
                pointerId: 1,
                clientX: 930,
                clientY: 135,
            });
            assert.strictEqual(data.workspace.movableDialogDrag, null);

            const down = handle.dispatch('pointerdown', {
                target: handle,
                button: 0,
                pointerId: 2,
                clientX: 650,
                clientY: 140,
            });
            assert.strictEqual(down.defaultPrevented, true);
            assert.strictEqual(handle.hasPointerCapture(2), true);
            assert.strictEqual(
                dialog.getAttribute('data-dialog-dragging'),
                'true'
            );
            handle.dispatch('pointermove', {
                target: handle,
                pointerId: 2,
                clientX: 100,
                clientY: 600,
            });
            assert.strictEqual(dialog.style.left, '50px');
            assert.strictEqual(dialog.style.top, '392px');
            assert.strictEqual(dialog.style.right, 'auto');
            assert.strictEqual(dialog.getAttribute('data-dialog-left'), '50');
            assert.strictEqual(dialog.getAttribute('data-dialog-top'), '392');

            handle.dispatch('pointerup', {
                target: handle,
                pointerId: 2,
                clientX: 100,
                clientY: 600,
            });
            assert.strictEqual(data.workspace.movableDialogDrag, null);
            assert.strictEqual(handle.hasPointerCapture(2), false);
            assert.strictEqual(
                dialog.getAttribute('data-dialog-dragging'),
                null
            );

            const keyEvent = handle.dispatch('keydown', {
                target: handle,
                key: 'ArrowRight',
                shiftKey: true,
            });
            assert.strictEqual(keyEvent.defaultPrevented, true);
            assert.strictEqual(dialog.style.left, '60px');
            assert.strictEqual(dialog.style.top, '392px');
            assert.strictEqual(
                JSON.stringify(data.session.getState().layout),
                before
            );
            data.workspace.destroy();
        });

    await check('floating card toolbar follows selection and delegates commands',
        async () => {
            const manager = new FakeSurfaceManager();
            const data = fixture({
                externalCommandSurface: true,
                floatingSurfaceRuntime: {
                    createSurfaceManager() { return manager; },
                },
                floatingDom: fakeFloatingDom(),
            });
            planCard(data, 'pl-a', {
                left: 100, top: 160, width: 120, height: 80,
            });
            planCard(data, 'pl-b', {
                left: 280, top: 220, width: 100, height: 60,
            });
            planZone(data, 'zn-a', {
                left: 420, top: 140, width: 260, height: 180,
            });

            data.session.select('pl-a');
            assert.strictEqual(manager.isOpen(), true);
            let toolbar = data.workspace.selectionToolbarElement;
            assert.strictEqual(
                toolbar.getAttribute('aria-label'),
                'Selected equipment actions'
            );
            assert.deepStrictEqual(
                toolbar.querySelectorAll('[data-selection-command]').map(
                    item => item.getAttribute('data-selection-command')
                ),
                [
                    'rotate', 'offset', 'duplicate', 'vertical-stack',
                    'mirror', 'lock', 'delete',
                ]
            );
            toolbar.querySelector(
                '[data-selection-command="rotate"]'
            ).dispatch('click');
            await data.workspace.whenIdle();
            assert.strictEqual(
                data.session.calls.filter(
                    call => call[0] === 'rotateSelected90'
                ).length,
                1
            );

            data.session.selectMany(['pl-a', 'pl-b']);
            toolbar = data.workspace.selectionToolbarElement;
            assert.strictEqual(manager.openCalls.length, 2);
            assert.strictEqual(
                toolbar.querySelector('.ip-flw-selection-count').textContent,
                '2'
            );
            assert.deepStrictEqual(
                toolbar.querySelectorAll('[data-selection-command]').map(
                    item => item.getAttribute('data-selection-command')
                ),
                [
                    'align', 'relative', 'distance', 'offset',
                    'duplicate', 'surface-stack', 'mirror', 'lock', 'delete',
                ]
            );
            assert.deepStrictEqual(
                manager.getActive().reference.getBoundingClientRect(),
                {
                    x: 100,
                    y: 160,
                    left: 100,
                    top: 160,
                    right: 380,
                    bottom: 280,
                    width: 280,
                    height: 120,
                }
            );

            toolbar.querySelector(
                '[data-selection-command="distance"]'
            ).dispatch('click');
            assert.strictEqual(data.workspace.precisionState.open, true);
            assert.strictEqual(manager.isOpen(), false);
            data.workspace.closePrecisionDialog(false);
            assert.strictEqual(manager.isOpen(), true);
            data.workspace._setViewMode('3d');
            assert.strictEqual(manager.isOpen(), false);
            data.workspace._setViewMode('plan');
            assert.strictEqual(manager.isOpen(), true);
            data.session.select('zn-a');
            assert.strictEqual(manager.isOpen(), true);
            toolbar = data.workspace.selectionToolbarElement;
            assert.strictEqual(
                toolbar.getAttribute('data-facility-zone-toolbar'),
                'zn-a'
            );
            const name = toolbar.querySelector('[data-zone-name]');
            assert.strictEqual(name.value, 'Assembly cell');
            name.value = 'Lathe Cell';
            name.dispatch('keydown', { key: 'Enter' });
            await data.workspace.whenIdle();
            assert.deepStrictEqual(
                data.session.calls.filter(
                    call => call[0] === 'editZoneLabel'
                ).pop(),
                ['editZoneLabel', 'zn-a', 'Lathe Cell']
            );
            assert.strictEqual(
                data.session.getState().layout.zones[0].label,
                'Lathe Cell'
            );
            await data.workspace.executeCommand('polygon-zone');
            assert.strictEqual(manager.isOpen(), false);
            assert.strictEqual(
                data.workspace.getState().toolMode,
                'polygon-zone'
            );
            data.workspace.destroy();
            assert.strictEqual(manager.destroyCount, 1);
        });

    await check('bounded suspension detaches and restores one workspace without rebuilding',
        async () => {
            const data = fixture();
            const listenerCount = FakeElement.listenerCount;
            const children = data.root.children.slice();
            for (let index = 0; index < 20; index += 1) {
                assert.strictEqual(data.workspace.suspend(), true);
                assert.strictEqual(data.workspace.suspend(), false);
                assert.strictEqual(data.workspace.getState().suspended, true);
                assert.strictEqual(data.root.children.length, 0);
                assert.strictEqual(
                    data.root.getAttribute('data-facility-workspace'),
                    null
                );
                assert.strictEqual(data.top.suspended, true);
                assert.strictEqual(data.three.suspended, true);
                assert.strictEqual(data.workspace.resume(data.root), true);
                assert.strictEqual(data.workspace.resume(data.root), false);
                assert.strictEqual(data.workspace.getState().suspended, false);
                assert.deepStrictEqual(data.root.children, children);
                assert.strictEqual(data.top.suspended, false);
                assert.strictEqual(data.three.suspended, false);
            }
            assert.strictEqual(data.controller.suspendCount, 20);
            assert.strictEqual(data.controller.resumeCount, 20);
            assert.strictEqual(data.controller.disposeCount, 0);
            assert.strictEqual(FakeElement.listenerCount, listenerCount);
            data.workspace.destroy();
            assert.strictEqual(data.controller.disposeCount, 1);
        });

    await check('latest drag advisory is visible and never controls validity',
        async () => {
            const advisor = new FakeSpatialAdvisor();
            const data = fixture({ spatialAdvisor: advisor });
            const transfer = externalAssetTransfer('asset-machine');
            data.workspace.viewportStack.dispatch('dragover', {
                dataTransfer: transfer,
                world: { x: 3, y: 0, z: 3 },
            });
            data.workspace.viewportStack.dispatch('dragover', {
                dataTransfer: transfer,
                world: { x: 7, y: 0, z: 3 },
            });
            assert.strictEqual(advisor.requests.length, 2);
            assert.ok(advisor.cancelCount >= 1);
            assert.strictEqual(
                data.workspace.ghostOverlay.getAttribute(
                    'data-advisory-state'
                ),
                'pending'
            );
            advisor.resolve({
                authority: 'browser-advisory',
                authoritative: false,
                status: 'attention',
                summary: 'Possible overlap with one placed object.',
                overlapPlacementIds: ['pl-a'],
            });
            await Promise.resolve();
            await Promise.resolve();
            assert.strictEqual(
                data.workspace.ghostOverlay.getAttribute(
                    'data-advisory-state'
                ),
                'attention'
            );
            assert.ok(data.workspace.ghostOverlay.textContent.includes(
                'Advisory: Possible overlap'
            ));
            assert.ok(data.workspace.advisoryLiveRegion.textContent.includes(
                'Placement advisory: Possible overlap'
            ));
            assert.strictEqual(
                data.session.getState().ghostPlacement.valid,
                true
            );
            assert.strictEqual(data.workspace.getState().dragAdvisory.authoritative,
                false);
            data.workspace.destroy();
        });

    await check('authoritative alternatives cycle, dismiss, and accept from controls',
        async () => {
            const data = fixture();
            const before = JSON.stringify(data.session.getState().layout);
            data.session.installPlacementAlternatives(
                SPATIAL_FIXTURE.candidateReceipt
            );
            assert.strictEqual(data.workspace.candidateControls.hidden, false);
            assert.ok(data.workspace.candidateSummary.textContent.includes(
                'Authoritatively validated'
            ));
            assert.ok(!data.workspace.candidateSummary.textContent.includes(
                'Server validated'
            ));
            assert.strictEqual(
                data.workspace.candidateControls.getAttribute(
                    'data-safety-status'
                ),
                'safe'
            );
            assert.strictEqual(
                data.workspace.ghostOverlay.getAttribute(
                    'data-advisory-state'
                ),
                'server-authoritative'
            );
            data.workspace.candidateControls.querySelector(
                '[data-candidate-action="next"]'
            ).dispatch('click');
            assert.strictEqual(
                data.session.getState().placementAlternatives.selectedIndex,
                1
            );
            assert.strictEqual(JSON.stringify(data.session.getState().layout), before);
            data.workspace.candidateControls.querySelector(
                '[data-candidate-action="dismiss"]'
            ).dispatch('click');
            assert.strictEqual(data.workspace.candidateControls.hidden, true);
            assert.strictEqual(JSON.stringify(data.session.getState().layout), before);

            data.session.installPlacementAlternatives(
                SPATIAL_FIXTURE.candidateReceipt
            );
            data.workspace.candidateControls.querySelector(
                '[data-candidate-action="accept"]'
            ).dispatch('click');
            await data.workspace.whenIdle();
            assert.ok(data.session.getState().layout.placements.some(
                item => item.placementId === 'pl-candidate-grid'
            ));
            assert.strictEqual(
                data.session.calls.filter(
                    call => call[0] === 'acceptPlacementAlternative'
                ).length,
                1
            );
            data.workspace.destroy();
        });

    await check('a single proposal reads plainly and offers no option paging',
        async () => {
            // Agent previews arrive as one option named exact-operations-v1, which
            // used to fill the card with internal metrics, hashes and "not reported".
            const data = fixture();
            await data.workspace.executeCommand('auto-arrange');
            await data.workspace.whenIdle();
            const proposal = data.session.state.layoutProposal;
            proposal.alternatives = proposal.alternatives.slice(0, 1);
            Object.assign(proposal.alternatives[0], {
                strategy: 'exact-operations-v1',
                findings: [],
                metrics: { spatialErrorCount: 0, spatialWarningCount: 0, placementCollisions: 0 },
            });
            data.session._notify();
            await data.workspace.whenIdle();
            assert.strictEqual(data.workspace.candidateSummary.textContent,
                'Proposed change. Not saved yet.');
            assert.strictEqual(data.workspace.proposalCheckText.textContent,
                'Checks: no problems found.');
            assert.strictEqual(
                data.workspace.proposalCheckText.getAttribute('data-check-status'), 'ok');
            ['previous', 'next'].forEach(action => assert.strictEqual(
                data.workspace.candidateControls.querySelector(
                    '[data-candidate-action="' + action + '"]'
                ).hidden, true));
            // Agent previews carry the server's check counts; a blocked aisle is a problem.
            proposal.alternatives[0].validationSummary = {
                noNewErrors: true, errorCount: 0, warningCount: 0, placementCollisions: 0,
                shellObstacleCollisions: 0, clearanceConflicts: 0, obstructedAisleCount: 1,
                blockedRouteCount: 0, routingErrorCount: 0,
            };
            data.session._notify();
            await data.workspace.whenIdle();
            assert.strictEqual(data.workspace.proposalCheckText.textContent,
                'Checks: 1 blocked aisle.');
            assert.strictEqual(
                data.workspace.proposalCheckText.getAttribute('data-check-status'), 'error');
            // Without any check results the card must not claim there were no problems.
            Object.assign(proposal.alternatives[0].validationSummary, {
                obstructedAisleCount: 0, siteFindingCount: 7,
            });
            proposal.alternatives[0].operations = [{ op: 'set_building_pose' }];
            data.session._notify();
            await data.workspace.whenIdle();
            assert.strictEqual(data.workspace.proposalCheckText.textContent,
                'Checks: 7 site findings.');
            assert.strictEqual(
                data.workspace.proposalCheckText.getAttribute('data-check-status'), 'warning');
            assert.ok(data.workspace.proposalChangeText.textContent.includes('1 site edit'));
            // A change to the floor-plan drawing (its placement or layer roles) is named, not hidden.
            proposal.alternatives[0].operations = [{ op: 'upsert_floor_plan_reference' }];
            data.session._notify();
            await data.workspace.whenIdle();
            assert.ok(data.workspace.proposalChangeText.textContent.includes('1 floor plan edit.'),
                data.workspace.proposalChangeText.textContent);
            proposal.alternatives[0].operations = [{ op: 'set_building_pose' }];
            delete proposal.alternatives[0].validationSummary;
            proposal.alternatives[0].metrics = {};
            data.session._notify();
            await data.workspace.whenIdle();
            assert.strictEqual(data.workspace.proposalCheckText.textContent,
                'Checks: no results came with this preview.');
            assert.strictEqual(
                data.workspace.proposalCheckText.getAttribute('data-check-status'), 'unknown');
            data.workspace.destroy();
        });

    await check('full-layout preview renders in plan and 3D without dirtying',
        async () => {
            const data = fixture();
            const siteFrames = [];
            data.workspace.siteView = { element: data.workspace.document.createElement('div'),
                render: (layout, options) => siteFrames.push({ layout: clone(layout), options }),
                show() {}, hide() {}, destroy() {} };
            const saved = clone(data.session.getState().layout);
            const autoArrange = toolbarButton(data, 'auto-arrange');
            autoArrange.focus();
            await data.workspace.executeCommand('auto-arrange');
            await data.workspace.whenIdle();
            let state = data.session.getState();
            const requestCall = data.session.calls.find(
                call => call[0] === 'requestLayoutProposal'
            );
            assert.ok(requestCall);
            assert.strictEqual(
                JSON.stringify(requestCall[1]).includes('"position"'),
                false
            );
            assert.strictEqual(state.dirty, false);
            assert.deepStrictEqual(state.layout, saved);
            assert.strictEqual(siteFrames.at(-1).options.readOnly, true);
            assert.deepStrictEqual(siteFrames.at(-1).layout, state.layoutProposal.alternatives[state.layoutProposal.selectedIndex].ghostPreview.layout);
            assert.strictEqual(
                data.root.getAttribute('data-full-layout-preview'),
                'true'
            );
            assert.ok(data.workspace.candidateSummary.textContent.includes(
                'Not saved yet'
            ));
            assert.ok(data.workspace.candidateSummary.textContent.includes(
                'option 1 of'
            ));
            assert.ok(!/Metrics|affectedCount|exact-operations/.test(
                data.workspace.candidateSummary.textContent
            ));
            assert.strictEqual(
                data.workspace.candidateControls.getAttribute(
                    'data-preview-kind'
                ),
                'full-layout'
            );
            assert.strictEqual(data.workspace.proposalReview.hidden, false);
            // Reviewers read plain changes and a check result; the bindings and the
            // full diagnostics sit in the collapsed technical details.
            assert.ok(data.workspace.proposalChangeText.textContent.includes(
                '1 new item, 1 moved item, 1 removed item'
            ));
            assert.ok(/^Checks: /.test(
                data.workspace.proposalCheckText.textContent
            ));
            assert.ok(['ok', 'warning', 'error'].includes(
                data.workspace.proposalCheckText.getAttribute('data-check-status')
            ));
            assert.strictEqual(data.workspace.proposalBindingText.parentNode,
                data.workspace.proposalDetails);
            assert.strictEqual(data.workspace.proposalDiagnosticText.parentNode,
                data.workspace.proposalDetails);
            assert.strictEqual(data.workspace.candidateControls.querySelector(
                '[data-candidate-action="next"]'
            ).hidden, false);
            assert.ok(data.workspace.proposalBindingText.textContent.includes(
                'Proposal binding: map rev-1'
            ));
            assert.ok(data.workspace.proposalBindingText.textContent.includes(
                'dependency eeeeeeeeee...'
            ));
            assert.ok(data.workspace.proposalDiagnosticText.textContent.includes(
                'clearance conflicts 1 (difference -2)'
            ));
            assert.ok(data.workspace.proposalDiagnosticText.textContent.includes(
                'new hard findings 0'
            ));
            assert.ok(data.workspace.proposalDiagnosticText.textContent.length
                <= 360);
            const topPreview = data.top.proposalPreviews.at(-1);
            const threePreview = data.three.proposalPreviews.at(-1);
            assert.deepStrictEqual(topPreview, threePreview);
            assert.deepStrictEqual(topPreview.newPlacementIds, ['pl-proposed']);
            assert.deepStrictEqual(topPreview.movedPlacementIds, ['pl-a']);
            assert.deepStrictEqual(topPreview.removedPlacementIds, ['pl-b']);
            assert.strictEqual(topPreview.beforePlacements.length, 2);
            assert.strictEqual(
                data.controller.layouts.at(-1)
                    .placements[0].transform.position.x,
                12
            );
            assert.strictEqual(
                data.top.layouts.at(-1).placements[0].transform.position.x,
                12
            );
            assert.strictEqual(
                data.three.layouts.at(-1).placements[0].transform.position.x,
                12
            );

            data.workspace.candidateControls.querySelector(
                '[data-candidate-action="next"]'
            ).dispatch('click');
            state = data.session.getState();
            assert.strictEqual(state.layoutProposal.selectedIndex, 1);
            assert.deepStrictEqual(state.layout, saved);
            assert.strictEqual(
                data.controller.layouts.at(-1)
                    .placements[0].transform.position.x,
                24
            );
            assert.strictEqual(
                data.top.layouts.at(-1).placements[0].transform.position.x,
                24
            );
            assert.strictEqual(
                data.three.layouts.at(-1).placements[0].transform.position.x,
                24
            );
            assert.strictEqual(
                data.top.proposalPreviews.at(-1)
                    .proposedPlacements[0].transform.position.x,
                24
            );

            const dismiss = data.workspace.candidateControls.querySelector(
                '[data-candidate-action="dismiss"]'
            );
            dismiss.focus();
            dismiss.dispatch('click');
            await data.workspace.whenIdle();
            assert.strictEqual(data.session.getState().layoutProposal, null);
            assert.deepStrictEqual(data.session.getState().layout, saved);
            assert.strictEqual(
                data.root.getAttribute('data-full-layout-preview'),
                null
            );
            assert.strictEqual(
                data.controller.layouts.at(-1)
                    .placements[0].transform.position.x,
                saved.placements[0].transform.position.x
            );
            assert.strictEqual(data.top.proposalPreviews.at(-1), null);
            assert.strictEqual(data.three.proposalPreviews.at(-1), null);
            assert.strictEqual(data.documentRef.activeElement, autoArrange);
            await data.workspace.executeCommand('auto-arrange');
            const escape = data.root.dispatch('keydown', {
                key: 'Escape',
                target: data.root,
            });
            await data.workspace.whenIdle();
            assert.strictEqual(escape.defaultPrevented, true);
            assert.strictEqual(data.session.getState().layoutProposal, null);
            assert.strictEqual(data.documentRef.activeElement, autoArrange);
            assert.ok(data.controller.fitCount >= 4);
            data.workspace.destroy();
        });

    await check('proposal approval restores focus after controls disappear',
        async () => {
            const data = fixture();
            const autoArrange = toolbarButton(data, 'auto-arrange');
            autoArrange.focus();
            await data.workspace.executeCommand('auto-arrange');
            await data.workspace.whenIdle();
            const approve = data.workspace.candidateControls.querySelector(
                '[data-candidate-action="accept"]'
            );
            approve.focus();
            approve.dispatch('click');
            await data.workspace.whenIdle();
            assert.strictEqual(data.session.getState().layoutProposal, null);
            assert.strictEqual(data.workspace.candidateControls.hidden, true);
            assert.strictEqual(data.documentRef.activeElement, autoArrange);
            assert.strictEqual(
                data.session.getState().layout.placements[0]
                    .transform.position.x,
                12
            );
            data.workspace.destroy();
        });

    await check('proposal approval restores focus to the external app ribbon',
        async () => {
            const data = fixture();
            const ribbonCommand = data.documentRef.createElement('button');
            ribbonCommand.setAttribute(
                'data-facility-ribbon-command',
                'auto-arrange'
            );
            ribbonCommand.focus();
            await data.workspace.executeCommand('auto-arrange');
            await data.workspace.whenIdle();
            const approve = data.workspace.candidateControls.querySelector(
                '[data-candidate-action="accept"]'
            );
            approve.dispatch('click');
            await data.workspace.whenIdle();
            assert.strictEqual(data.documentRef.activeElement, ribbonCommand);
            data.workspace.destroy();
        });

    await check('candidate safety copy is distinct and summary stays bounded',
        async () => {
            const data = fixture();
            const unverified = clone(SPATIAL_FIXTURE.candidateReceipt);
            unverified.candidates[0].safe = false;
            unverified.candidates[0].safetyStatus = 'unverified';
            unverified.candidates[0].findings = [
                { code: 'missing-egress', message: 'Egress evidence missing' },
                { code: 'missing-load', message: 'Floor load not verified' },
                { code: 'missing-power', message: 'Power drop not verified' },
                { code: 'missing-air', message: 'Air supply not verified' },
            ];
            unverified.candidates[0].metrics = {
                errorCount: 0,
                unverifiedCount: 4,
                warningCount: 1,
                physicalCollisions: 0,
                clearanceConflicts: 0,
            };
            data.session.installPlacementAlternatives(unverified);
            const summary = data.workspace.candidateSummary.textContent;
            assert.ok(summary.includes('Engineering evidence incomplete'));
            assert.ok(summary.includes('Egress evidence missing'));
            assert.ok(summary.includes('Floor load not verified'));
            assert.ok(summary.includes('+2 more'));
            assert.ok(summary.includes('errorCount 0'));
            assert.ok(summary.includes('unverifiedCount 4'));
            assert.ok(summary.includes('warningCount 1'));
            assert.ok(!summary.includes('physicalCollisions'));
            assert.strictEqual(
                data.workspace.candidateControls.querySelector(
                    '[data-candidate-action="accept"]'
                ).disabled,
                false
            );

            const unsafe = clone(SPATIAL_FIXTURE.candidateReceipt);
            unsafe.candidates[0].safe = false;
            unsafe.candidates[0].valid = false;
            unsafe.candidates[0].safetyStatus = 'unsafe';
            unsafe.candidates[0].findings = [{
                code: 'placement_collision',
                message: 'Placement intersects an existing machine',
            }];
            data.session.installPlacementAlternatives(unsafe);
            assert.ok(data.workspace.candidateSummary.textContent.includes(
                'Invalid placement'
            ));
            assert.strictEqual(
                data.workspace.candidateControls.getAttribute(
                    'data-safety-status'
                ),
                'unsafe'
            );
            assert.strictEqual(
                data.workspace.candidateControls.querySelector(
                    '[data-candidate-action="accept"]'
                ).disabled,
                true
            );
            data.workspace.destroy();
        });

    await check('opt-in drop requests server candidates instead of direct commit',
        async () => {
            const data = fixture({
                useAuthoritativePlacementCandidates: true,
            });
            const transfer = externalAssetTransfer('asset-machine');
            data.workspace.viewportStack.dispatch('drop', {
                dataTransfer: transfer,
                world: { x: 7, y: 0, z: 3 },
            });
            await data.workspace.whenIdle();
            assert.strictEqual(
                data.session.calls.filter(
                    call => call[0] === 'requestPlacementAlternatives'
                ).length,
                1
            );
            assert.strictEqual(
                data.session.calls.filter(
                    call => call[0] === 'commitGhostPlacement'
                ).length,
                0
            );
            assert.ok(data.session.getState().placementAlternatives);
            data.workspace.destroy();
        });

    await check('asset browser search and categories filter cards without changing catalog',
        async () => {
            const data = fixture();
            toolbarButton(data, 'assets').dispatch('click');
            const search = data.workspace.assetBrowserSearch;
            search.value = 'forklift';
            search.dispatch('input');
            assert.strictEqual(
                data.workspace.assetGrid.querySelectorAll(
                    '.ip-flw-asset-card'
                ).length,
                1
            );
            assert.strictEqual(
                data.workspace.assetGrid.querySelector(
                    '.ip-flw-asset-card'
                ).getAttribute('data-asset-id'),
                'asset-forklift'
            );
            search.value = '';
            search.dispatch('input');
            data.workspace.assetCategoryNav.querySelector(
                '[data-asset-category="Storage"]'
            ).dispatch('click');
            assert.strictEqual(
                data.workspace.assetGrid.querySelectorAll(
                    '.ip-flw-asset-card'
                ).length,
                1
            );
            assert.strictEqual(
                data.workspace.assetGrid.querySelector(
                    '.ip-flw-asset-card'
                ).getAttribute('data-asset-id'),
                'asset-rack'
            );
            assert.strictEqual(data.workspace.assetCatalog.length, 3);
            data.workspace.destroy();
        });

    await check('drop remains world-stable after arbitrary camera changes and delegates once',
        async () => {
            const data = fixture();
            const transfer = externalAssetTransfer('asset-rack');
            const payload = JSON.parse(transfer.getData(workspaceModule.ASSET_MIME));
            assert.deepStrictEqual(payload, {
                assetId: 'asset-rack',
                assetDefinitionRevision: 'revision-asset-rack',
                dragSessionId: 'external-drag-001',
            });
            data.top.camera = { panX: 700, panY: -420, zoom: 0.18 };
            data.three.camera = { x: 80, y: 60, z: -120, zoom: 2.6 };
            data.workspace.viewportStack.dispatch('dragover', {
                dataTransfer: transfer,
                world: { x: 12.24, y: 0, z: -3.26 },
            });
            assert.deepStrictEqual(
                data.session.getState().ghostPlacement.worldPosition,
                { x: 12, y: 0, z: -3.5 }
            );
            data.workspace.viewportStack.dispatch('drop', {
                dataTransfer: transfer,
                world: { x: 12.24, y: 0, z: -3.26 },
            });
            await data.workspace.whenIdle();
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'commitGhostPlacement').length,
                1
            );
            const created = data.session.getState().layout.placements.find(
                item => item.placementId === 'pl-new-1'
            );
            assert.deepStrictEqual(created.transform.position, { x: 12, y: 0, z: -3.5 });
            assert.strictEqual(data.session.getState().ghostPlacement, null);
            assert.strictEqual(
                data.session.getState().placementAlternatives,
                null
            );
            assert.strictEqual(data.workspace.candidateControls.hidden, true);
            assert.strictEqual(data.workspace.ghostOverlay.hidden, true);
            data.workspace.destroy();
        });

    await check('ghost cancel is transient and never commits layout', async () => {
        const data = fixture();
        const transfer = externalAssetTransfer('asset-machine');
        data.workspace.viewportStack.dispatch('dragover', {
            dataTransfer: transfer,
            world: { x: 8, y: 0, z: 7 },
        });
        const before = data.session.getState().layout.placements.length;
        data.workspace.viewportStack.dispatch('dragleave', {
            dataTransfer: transfer,
            relatedTarget: null,
        });
        assert.strictEqual(data.session.getState().ghostPlacement, null);
        assert.strictEqual(data.session.getState().layout.placements.length, before);
        assert.strictEqual(
            data.session.calls.filter(call => call[0] === 'commitGhostPlacement').length,
            0
        );
        data.workspace.destroy();
    });

    await check('Ctrl selection is additive and propagates across controller views',
        async () => {
            const data = fixture();
            data.workspace.handleViewSelection('pl-a');
            data.workspace.handleViewSelection('pl-b', { ctrlKey: true });
            assert.deepStrictEqual(data.session.getState().selection, ['pl-a', 'pl-b']);
            assert.deepStrictEqual(
                data.three.selections[data.three.selections.length - 1],
                ['pl-a', 'pl-b']
            );
            assert.strictEqual(
                data.controller.selections[data.controller.selections.length - 1],
                'pl-a'
            );
            data.workspace.handleViewSelection('pl-a', { ctrlKey: true });
            assert.deepStrictEqual(data.session.getState().selection, ['pl-b']);
            data.workspace.destroy();
        });

    await check('zones select directly without starting a marquee', async () => {
        const data = fixture();
        const target = data.documentRef.createElement('polygon');
        target.setAttribute('data-zone-id', 'zn-a');
        data.workspace.planView.appendChild(target);
        target.dispatch('pointerdown', {
            pointerId: 31,
            world: { x: 2, y: 0, z: 2 },
        });
        target.dispatch('pointerup', {
            pointerId: 31,
            world: { x: 2, y: 0, z: 2 },
        });
        assert.deepStrictEqual(data.session.getState().selection, ['zn-a']);
        assert.strictEqual(data.workspace.getState().session.history.length, 0);
        assert.strictEqual(
            data.session.calls.filter(call => call[0] === 'selectMany').length,
            0
        );
        data.workspace.destroy();
    });

    await check('plan marquee hook selects resolved IDs once with additive behavior',
        async () => {
            let resolverCalls = 0;
            const data = fixture({
                marqueeResolver(input) {
                    resolverCalls += 1;
                    assert.deepStrictEqual(input.start, { x: 0, y: 0, z: 0 });
                    assert.deepStrictEqual(input.end, { x: 6, y: 0, z: 4 });
                    return ['pl-a', 'pl-b'];
                },
            });
            data.workspace.planView.dispatch('pointerdown', {
                world: { x: 0, y: 0, z: 0 },
            });
            data.workspace.planView.dispatch('pointerup', {
                world: { x: 6, y: 0, z: 4 },
                ctrlKey: true,
            });
            assert.strictEqual(resolverCalls, 1);
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'selectMany').length,
                1
            );
            assert.deepStrictEqual(data.session.getState().selection, ['pl-a', 'pl-b']);
            data.workspace.destroy();
        });

    await check('placement pointer move is one delegated gesture and marks auto manual',
        async () => {
            const data = fixture();
            const target = data.documentRef.createElement('polygon');
            target.setAttribute('data-placement-id', 'pl-a');
            data.workspace.planView.appendChild(target);
            target.dispatch('pointerdown', {
                world: { x: 1, y: 0, z: 1 },
            });
            target.dispatch('pointermove', {
                world: { x: 3.2, y: 0, z: 0.2 },
            });
            assert.deepStrictEqual(
                data.top.transientPlacementMoves.at(-1),
                {
                    ids: ['pl-a'],
                    delta: { x: 2, y: 0, z: -1 },
                }
            );
            target.dispatch('pointerup', {
                world: { x: 3.2, y: 0, z: 0.2 },
            });
            await data.workspace.whenIdle();
            const calls = data.session.calls.filter(call => call[0] === 'moveSelected');
            assert.strictEqual(calls.length, 1);
            assert.deepStrictEqual(calls[0][1], { x: 2, y: 0, z: -1 });
            const moved = data.session.getState().layout.placements.find(
                item => item.placementId === 'pl-a'
            );
            assert.strictEqual(moved.positionMode, 'manual');
            assert.deepStrictEqual(
                data.top.transientPlacementMoves.at(-1),
                { ids: [], delta: null }
            );
            data.workspace.destroy();
        });

    await check('placement preview stays at the drop point until the move settles',
        async () => {
            const data = fixture();
            const moveSelected = data.session.moveSelected.bind(data.session);
            let releaseMove = null;
            data.session.moveSelected = delta => new Promise((resolve, reject) => {
                releaseMove = () => Promise.resolve(moveSelected(delta)).then(resolve, reject);
            });
            const target = data.documentRef.createElement('polygon');
            target.setAttribute('data-placement-id', 'pl-a');
            data.workspace.planView.appendChild(target);
            target.dispatch('pointerdown', {
                world: { x: 1, y: 0, z: 1 },
            });
            target.dispatch('pointermove', {
                world: { x: 3, y: 0, z: 2 },
            });
            target.dispatch('pointerup', {
                world: { x: 3, y: 0, z: 2 },
            });
            await Promise.resolve();
            await Promise.resolve();
            assert.strictEqual(typeof releaseMove, 'function');
            assert.deepStrictEqual(
                data.top.transientPlacementMoves.at(-1),
                {
                    ids: ['pl-a'],
                    delta: { x: 2, y: 0, z: 1 },
                }
            );
            releaseMove();
            await data.workspace.whenIdle();
            assert.deepStrictEqual(
                data.top.transientPlacementMoves.at(-1),
                { ids: [], delta: null }
            );
            data.workspace.destroy();
        });

    await check('Ctrl-drag duplicates one placement at the drop point', async () => {
        const data = fixture();
        data.session.select('pl-b');
        const sourceBefore = clone(data.session.getState().layout.placements.find(
            item => item.placementId === 'pl-a'
        ));
        const target = data.documentRef.createElement('polygon');
        target.setAttribute('data-placement-id', 'pl-a');
        data.workspace.planView.appendChild(target);
        target.dispatch('pointerdown', {
            pointerId: 51,
            ctrlKey: true,
            clientX: 10,
            clientY: 10,
            world: { x: 1, y: 0, z: 1 },
        });
        assert.deepStrictEqual(data.session.getState().selection, ['pl-b']);
        target.dispatch('pointermove', {
            pointerId: 51,
            ctrlKey: true,
            clientX: 40,
            clientY: 30,
            world: { x: 4, y: 0, z: 3 },
        });
        assert.deepStrictEqual(
            data.top.transientPlacementDuplicates.at(-1),
            {
                ids: ['pl-a'],
                delta: { x: 3, y: 0, z: 2 },
            }
        );
        assert.deepStrictEqual(
            data.session.getState().layout.placements.find(
                item => item.placementId === 'pl-a'
            ),
            sourceBefore
        );
        target.dispatch('pointerup', {
            pointerId: 51,
            ctrlKey: true,
            clientX: 40,
            clientY: 30,
            world: { x: 4, y: 0, z: 3 },
        });
        await data.workspace.whenIdle();
        const calls = data.session.calls.filter(
            call => call[0] === 'duplicateItems'
        );
        assert.strictEqual(calls.length, 1);
        assert.deepStrictEqual(calls[0][1], ['pl-a']);
        assert.deepStrictEqual(calls[0][2], { x: 3, y: 0, z: 2 });
        const state = data.session.getState();
        assert.strictEqual(state.layout.placements.length, 3);
        const duplicate = state.layout.placements.find(
            item => item.placementId === state.selection[0]
        );
        assert.deepStrictEqual(duplicate.transform.position, { x: 4, y: 0, z: 3 });
        assert.strictEqual(duplicate.positionMode, 'manual');
        assert.deepStrictEqual(
            data.top.transientPlacementDuplicates.at(-1),
            { ids: [], delta: null }
        );
        data.workspace.destroy();
    });

    await check('Ctrl-drag duplicates the complete selected equipment group',
        async () => {
            const data = fixture();
            data.session.selectMany(['pl-a', 'pl-b']);
            const originals = clone(data.session.getState().layout.placements);
            const target = data.documentRef.createElement('polygon');
            target.setAttribute('data-placement-id', 'pl-a');
            data.workspace.planView.appendChild(target);
            target.dispatch('pointerdown', {
                pointerId: 53,
                ctrlKey: true,
                clientX: 10,
                clientY: 10,
                world: { x: 1, y: 0, z: 1 },
            });
            target.dispatch('pointermove', {
                pointerId: 53,
                ctrlKey: true,
                clientX: 35,
                clientY: 30,
                world: { x: 3, y: 0, z: 4 },
            });
            assert.deepStrictEqual(
                data.top.transientPlacementDuplicates.at(-1),
                {
                    ids: ['pl-a', 'pl-b'],
                    delta: { x: 2, y: 0, z: 3 },
                }
            );
            target.dispatch('pointerup', {
                pointerId: 53,
                ctrlKey: true,
                clientX: 35,
                clientY: 30,
                world: { x: 3, y: 0, z: 4 },
            });
            await data.workspace.whenIdle();
            const calls = data.session.calls.filter(
                call => call[0] === 'duplicateItems'
            );
            assert.strictEqual(calls.length, 1);
            assert.deepStrictEqual(calls[0][1], ['pl-a', 'pl-b']);
            assert.deepStrictEqual(calls[0][2], { x: 2, y: 0, z: 3 });
            const state = data.session.getState();
            assert.deepStrictEqual(state.layout.placements.slice(0, 2), originals);
            assert.strictEqual(state.layout.placements.length, 4);
            assert.deepStrictEqual(state.selection, ['pl-copy-1', 'pl-copy-2']);
            assert.deepStrictEqual(
                state.layout.placements.slice(2).map(
                    item => item.transform.position
                ),
                [
                    { x: 3, y: 0, z: 4 },
                    { x: 7, y: 0, z: 5 },
                ]
            );
            assert.strictEqual(state.history.length, 1);
            assert.deepStrictEqual(
                data.top.transientPlacementDuplicates.at(-1),
                { ids: [], delta: null }
            );
            data.workspace.destroy();
        });

    await check('stationary Ctrl-click remains additive selection', async () => {
        const data = fixture();
        const target = data.documentRef.createElement('polygon');
        target.setAttribute('data-placement-id', 'pl-a');
        data.workspace.planView.appendChild(target);
        target.dispatch('pointerdown', {
            pointerId: 52,
            ctrlKey: true,
            clientX: 10,
            clientY: 10,
            world: { x: 1, y: 0, z: 1 },
        });
        target.dispatch('pointerup', {
            pointerId: 52,
            ctrlKey: true,
            clientX: 10,
            clientY: 10,
            world: { x: 1, y: 0, z: 1 },
        });
        assert.deepStrictEqual(data.session.getState().selection, ['pl-a']);
        assert.strictEqual(
            data.session.calls.filter(
                call => call[0] === 'duplicateItems'
            ).length,
            0
        );
        data.workspace.destroy();
    });

    await check('Ctrl-drag duplicates an unselected floor marking at the drop point',
        async () => {
            const data = fixture();
            const marking = floorMarking('fm-arrow', 'direction_arrow');
            data.session.state.layout.floorMarkings.push(marking);
            data.session.select('pl-b');
            const sourceBefore = clone(marking);
            const target = data.documentRef.createElement('g');
            target.setAttribute('data-floor-marking-id', 'fm-arrow');
            data.workspace.planView.appendChild(target);
            target.dispatch('pointerdown', {
                pointerId: 54,
                ctrlKey: true,
                clientX: 10,
                clientY: 10,
                world: { x: 4, y: 0, z: 3 },
            });
            target.dispatch('pointermove', {
                pointerId: 54,
                ctrlKey: true,
                clientX: 40,
                clientY: 30,
                world: { x: 6, y: 0, z: 4 },
            });
            assert.deepStrictEqual(
                data.top.transientPlacementDuplicates.at(-1),
                {
                    ids: ['fm-arrow'],
                    delta: { x: 2, y: 0, z: 1 },
                }
            );
            target.dispatch('pointerup', {
                pointerId: 54,
                ctrlKey: true,
                clientX: 40,
                clientY: 30,
                world: { x: 6, y: 0, z: 4 },
            });
            await data.workspace.whenIdle();
            const calls = data.session.calls.filter(
                call => call[0] === 'duplicateItems'
            );
            assert.deepStrictEqual(calls, [[
                'duplicateItems',
                ['fm-arrow'],
                { x: 2, y: 0, z: 1 },
            ]]);
            const state = data.session.getState();
            assert.deepStrictEqual(state.layout.floorMarkings[0], sourceBefore);
            assert.strictEqual(state.layout.floorMarkings.length, 2);
            assert.deepStrictEqual(
                state.layout.floorMarkings[1].transform.position,
                { x: 6, y: 0, z: 4 }
            );
            assert.strictEqual(state.layout.floorMarkings[1].positionMode, 'manual');
            data.workspace.destroy();
        });

    await check('dragging a floor marking corner previews and commits one resize',
        async () => {
            const data = fixture();
            const marking = floorMarking('fm-resize', 'direction_arrow');
            data.session.state.layout.floorMarkings.push(marking);
            data.session.select('fm-resize');
            const handle = data.documentRef.createElement('rect');
            handle.setAttribute('data-floor-marking-id', 'fm-resize');
            handle.setAttribute('data-floor-marking-resize-handle', '2');
            data.workspace.planView.appendChild(handle);
            handle.dispatch('pointerdown', {
                pointerId: 55,
                clientX: 10,
                clientY: 10,
                world: { x: 6, y: 0, z: 4 },
            });
            handle.dispatch('pointermove', {
                pointerId: 55,
                clientX: 50,
                clientY: 40,
                world: { x: 8, y: 0, z: 6 },
            });
            const preview = data.top.transientFloorMarkingPreviews.at(-1);
            assert.strictEqual(preview.width, 6);
            assert.strictEqual(preview.depth, 4);
            assert.deepStrictEqual(
                preview.transform.position,
                { x: 5, y: 0, z: 4 }
            );
            handle.dispatch('pointerup', {
                pointerId: 55,
                clientX: 50,
                clientY: 40,
                world: { x: 8, y: 0, z: 6 },
            });
            await data.workspace.whenIdle();
            const calls = data.session.calls.filter(
                call => call[0] === 'editFloorMarking'
            );
            assert.strictEqual(calls.length, 1);
            assert.strictEqual(calls[0][1], 'fm-resize');
            assert.strictEqual(calls[0][2].width, 6);
            assert.strictEqual(calls[0][2].depth, 4);
            assert.deepStrictEqual(
                calls[0][2].transform.position,
                { x: 5, y: 0, z: 4 }
            );
            const resized = data.session.getState().layout.floorMarkings[0];
            assert.strictEqual(resized.width, 6);
            assert.strictEqual(resized.depth, 4);
            assert.strictEqual(resized.positionMode, 'manual');
            assert.strictEqual(
                data.top.transientFloorMarkingPreviews.at(-1),
                null
            );
            data.workspace.destroy();
        });

    await check('pointer capture keeps a move gesture owned by the plan view',
        async () => {
            const data = fixture();
            const target = data.documentRef.createElement('polygon');
            target.setAttribute('data-placement-id', 'pl-a');
            data.workspace.planView.appendChild(target);
            target.dispatch('pointerdown', {
                pointerId: 42,
                world: { x: 1, y: 0, z: 1 },
            });
            assert.strictEqual(
                data.workspace.planView.hasPointerCapture(42),
                true
            );
            data.workspace.planView.dispatch('pointerup', {
                pointerId: 42,
                world: { x: 2, y: 0, z: 2 },
            });
            await data.workspace.whenIdle();
            assert.strictEqual(
                data.workspace.planView.hasPointerCapture(42),
                false
            );
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'moveSelected').length,
                1
            );
            data.workspace.destroy();
        });

    await check('dragging one member of a multi-selection moves the full selection once',
        async () => {
            const data = fixture();
            data.session.selectMany(['pl-a', 'pl-b']);
            const target = data.documentRef.createElement('polygon');
            target.setAttribute('data-placement-id', 'pl-a');
            data.workspace.planView.appendChild(target);
            target.dispatch('pointerdown', {
                world: { x: 1, y: 0, z: 1 },
            });
            assert.deepStrictEqual(data.session.getState().selection, ['pl-a', 'pl-b']);
            target.dispatch('pointerup', {
                world: { x: 2, y: 0, z: 2 },
            });
            await data.workspace.whenIdle();
            const calls = data.session.calls.filter(call => call[0] === 'moveSelected');
            assert.strictEqual(calls.length, 1);
            assert.deepStrictEqual(data.session.getState().selection, ['pl-a', 'pl-b']);
            assert.deepStrictEqual(data.top.selections[data.top.selections.length - 1],
                ['pl-a', 'pl-b']);
            data.workspace.destroy();
        });

    await check('Plan navigation overlays track view state without mutating layout',
        async () => {
            const stored = {};
            const storage = {
                getItem(key) { return stored[key] || null; },
                setItem(key, value) { stored[key] = String(value); },
            };
            const data = fixture({ planPreferenceStorage: storage });
            const layoutBefore = clone(data.session.getState().layout);
            assert.ok(data.workspace.planTopRuler.children.length > 0);
            assert.ok(data.workspace.planLeftRuler.children.length > 0);
            assert.strictEqual(data.workspace.planScaleLabel.textContent, '5 m');
            assert.strictEqual(
                data.workspace.planCompass.getAttribute('aria-label'),
                'Facility orientation: north is positive Z and east is positive X'
            );
            const zoomIn = data.workspace.planNavigation.querySelector(
                '[data-plan-command="zoom-in"]'
            );
            zoomIn.dispatch('click');
            assert.strictEqual(data.top.lastZoom.factor, 1.25);
            const unit = data.workspace.planNavigation.querySelector(
                '[data-plan-command="unit"]'
            );
            unit.dispatch('click');
            assert.strictEqual(data.workspace.getState().planPreferences.unit, 'ft');
            assert.strictEqual(data.top.viewPreferences.displayUnit, 'ft');
            assert.strictEqual(unit.textContent, 'ft');
            assert.ok(data.workspace.planScaleLabel.textContent.endsWith(' ft'));
            const grid = data.workspace.planNavigation.querySelector(
                '[data-plan-command="grid"]'
            );
            grid.dispatch('click');
            assert.strictEqual(data.workspace.getState().planPreferences.showGrid, false);
            assert.strictEqual(data.top.viewPreferences.showGrid, false);
            const snap = data.workspace.planNavigation.querySelector(
                '[data-plan-command="snap"]'
            );
            snap.dispatch('click');
            assert.strictEqual(
                data.workspace.getState().planPreferences.snapToGrid,
                false
            );
            assert.deepStrictEqual(
                data.workspace._worldDelta(
                    { x: 0, y: 0, z: 0 },
                    { x: 0.37, y: 0, z: 0.41 }
                ),
                { x: 0.37, y: 0, z: 0.41 }
            );
            assert.deepStrictEqual(data.session.getState().layout, layoutBefore);
            assert.ok(stored[data.workspace.planPreferenceKey]);
            data.workspace.destroy();

            const reopened = fixture({ planPreferenceStorage: storage });
            assert.deepStrictEqual(reopened.workspace.getState().planPreferences, {
                unit: 'ft',
                showGrid: false,
                snapToGrid: false,
            });
            reopened.workspace.destroy();
        });

    await check('double-click edits persisted facility dimensions grid and view scale',
        async () => {
            const data = fixture({ externalCommandSurface: true });
            const originalRulerCount = data.workspace.planTopRuler.children.length;
            const caption = data.documentRef.createElement('span');
            caption.setAttribute('data-plan-settings-trigger', 'dimensions');
            data.workspace.planView.appendChild(caption);
            caption.dispatch('dblclick');
            assert.strictEqual(data.workspace.planSettingsDialog.hidden, false);
            assert.strictEqual(
                data.root.getAttribute('data-plan-settings-open'),
                'true'
            );

            const width = data.workspace.planSettingsBody.querySelector(
                '[data-plan-settings-field="widthMeters"]'
            );
            const depth = data.workspace.planSettingsBody.querySelector(
                '[data-plan-settings-field="depthMeters"]'
            );
            const grid = data.workspace.planSettingsBody.querySelector(
                '[data-plan-settings-field="gridSpacingMeters"]'
            );
            width.value = '55';
            width.dispatch('input');
            depth.value = '36';
            depth.dispatch('input');
            grid.value = '2';
            grid.dispatch('input');
            const environment = data.top.environmentSettings.at(-1);
            assert.deepStrictEqual(environment.worldBounds, {
                minX: 0, minZ: 0, maxX: 55, maxZ: 36, floorY: 0,
            });
            assert.strictEqual(environment.floorGridSpacing, 2);
            assert.strictEqual(environment.floorMajorGridSpacing, 10);
            assert.deepStrictEqual(
                data.three.environmentSettings.at(-1),
                environment
            );
            assert.notStrictEqual(
                data.workspace.planTopRuler.children.length,
                originalRulerCount
            );

            data.workspace.planSettingsDialog.querySelector(
                '[data-plan-settings-action="apply"]'
            ).dispatch('click');
            await data.workspace.whenIdle();
            assert.deepStrictEqual(
                data.session.calls.filter(call => call[0] === 'setPlanSettings'),
                [[
                    'setPlanSettings',
                    {
                        widthMeters: 55,
                        depthMeters: 36,
                        gridSpacingMeters: 2,
                        majorGridSpacingMeters: 10,
                    },
                ]]
            );
            assert.deepStrictEqual(data.workspace.getState().planSettings, {
                widthMeters: 55,
                depthMeters: 36,
                gridSpacingMeters: 2,
                majorGridSpacingMeters: 10,
            });

            data.workspace.planScaleBar.dispatch('dblclick');
            const scale = data.workspace.planSettingsBody.querySelector(
                '[data-plan-settings-field="scaleDistanceMeters"]'
            );
            assert.strictEqual(data.documentRef.activeElement, scale);
            scale.value = '10';
            scale.dispatch('input');
            assert.strictEqual(data.top.scaleAtCalls.at(-1).scale, 13);
            data.workspace.planSettingsDialog.querySelector(
                '[data-plan-settings-action="apply"]'
            ).dispatch('click');
            await data.workspace.whenIdle();
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'setPlanSettings').length,
                1
            );
            assert.strictEqual(data.session.state.history.length, 1);
            data.workspace.destroy();
        });

    await check('appearance swatches custom color reset mixed selection and stale guards', async () => {
        const data = fixture();
        data.session.selectMany(['pl-a', 'pl-b']);
        data.session.state.layout.placements[0].appearance = {color:'#112233'};
        data.session._notify();
        assert.equal(data.workspace.openAppearanceDialog(), true);
        let dialog = data.workspace.appearanceDialog;
        assert.equal(dialog.querySelector('.ip-flw-appearance-value').textContent, 'Mixed colors');
        dialog.querySelector('[data-appearance-swatch="#2478bc"]').dispatch('click');
        dialog.querySelector('[data-appearance-apply]').dispatch('click');
        await new Promise(resolve => setImmediate(resolve));
        assert.deepEqual(data.session.calls.filter(c => c[0] === 'setSelectedAppearance'), [['setSelectedAppearance','#2478bc']]);
        data.workspace.openAppearanceDialog();
        dialog = data.workspace.appearanceDialog;
        const picker = dialog.querySelector('[data-appearance-color]');
        picker.value='#112233'; picker.dispatch('change');
        assert.equal(dialog.querySelector('.ip-flw-appearance-value').textContent, '#112233');
        dialog.querySelector('[data-appearance-reset]').dispatch('click');
        assert.equal(dialog.querySelector('.ip-flw-appearance-value').textContent, 'Default');
        data.session.select('pl-a');
        assert.equal(dialog.querySelector('[data-appearance-apply]').disabled, true);
        dialog.querySelector('[data-appearance-apply]').dispatch('click');
        assert.equal(data.session.calls.filter(c => c[0] === 'setSelectedAppearance').length, 1);
        for (const key of ['generatedDraft','designProposalDraft','layoutProposal','conflict']) {
            data.workspace.state[key]={};
            assert.equal(data.workspace.openAppearanceDialog(), false);
            data.workspace.state[key]=null;
        }
        data.workspace.suspend();
        assert.equal(data.workspace.appearanceDialog, null);
        data.workspace.destroy();
    });

    await check('3D heads-up toolbar includes appearance alongside camera and display controls',
        async () => {
            const data = fixture();
            const before = clone(data.session.getState().layout);
            data.workspace._setViewMode('3d');
            const controls = data.workspace.threeNavigation.querySelectorAll(
                '[data-three-command]'
            );
            assert.strictEqual(controls.length, 18);
            assert.deepStrictEqual(controls.map(button => (
                button.getAttribute('data-three-command')
            )), [
                'fit-layout',
                'zoom-out',
                'zoom-in',
                'pan',
                'view-orientation',
                'display-settings',
                'appearance',
                'layers',
                'orbit',
                'walkthrough',
                'avatar-view',
                'drone',
                'switch-immersive',
                'walk-to-selected',
                'viewpoints',
                'record',
                'fit-facility',
                'grid',
            ]);
            assert.strictEqual(
                data.workspace.threeNavigation.getAttribute('aria-label'),
                '3D viewport navigation'
            );
            controls.forEach(button => {
                const commandName = button.getAttribute('data-three-command');
                const icon = button.querySelector('img');
                if (commandName === 'record') {
                    assert.ok(button.querySelector('.ip-flw-record-symbol'));
                    assert.strictEqual(
                        button.getAttribute('data-icon-source'),
                        'record-symbol'
                    );
                } else if (commandName === 'view-orientation') {
                    assert.ok(icon);
                    const source = icon.getAttribute('src');
                    assert.ok(source.endsWith('/view-iso.png'));
                } else {
                    assert.ok(icon);
                    const source = icon.getAttribute('src');
                    assert.ok(source.endsWith('.svg'));
                }
                assert.ok(button.getAttribute('title'));
            });
            const command = name => data.workspace.threeNavigation.querySelector(
                '[data-three-command="' + name + '"]'
            );
            command('pan').dispatch('click');
            assert.strictEqual(data.workspace.getState().threeNavigation.mode, 'pan');
            assert.strictEqual(command('pan').getAttribute('aria-pressed'), 'true');
            assert.strictEqual(data.three.navigationModes.at(-1), 'pan');
            command('zoom-in').dispatch('click');
            command('zoom-out').dispatch('click');
            assert.deepStrictEqual(data.three.zoomFactors, [1.25, 0.8]);
            command('fit-layout').dispatch('click');
            command('fit-facility').dispatch('click');
            assert.strictEqual(data.three.fitLayoutCount, 1);
            assert.strictEqual(data.three.fitFacilityCount, 1);
            assert.strictEqual(command('walk-to-selected').disabled, true);
            data.session.select('pl-a');
            assert.strictEqual(command('walk-to-selected').disabled, false);
            command('walk-to-selected').dispatch('click');
            assert.deepStrictEqual(data.three.walkthroughNavigations, ['pl-a']);
            assert.strictEqual(
                data.workspace.threeWalkthroughTitle.textContent,
                'Navigating'
            );
            data.three.exitWalkthrough('navigation_test_complete');
            command('walkthrough').dispatch('click');
            assert.deepStrictEqual(data.three.walkthroughEntries.at(-1), {
                placementId: 'pl-a',
            });
            assert.strictEqual(
                data.workspace.getState().threeNavigation.walkthrough.active,
                true
            );
            assert.strictEqual(command('walkthrough').getAttribute('aria-pressed'), 'true');
            command('avatar-view').dispatch('click');
            assert.strictEqual(data.three.walkthrough.cameraMode, 'third-person');
            assert.strictEqual(command('avatar-view').getAttribute('aria-pressed'), 'true');
            assert.strictEqual(command('avatar-view').getAttribute('title'), 'Use first-person Walkthrough (C)');
            command('avatar-view').dispatch('click');
            assert.strictEqual(data.three.walkthrough.cameraMode, 'first-person');
            assert.strictEqual(command('avatar-view').getAttribute('aria-pressed'), 'false');
            assert.strictEqual(data.workspace.threeWalkthroughHud.hidden, false);
            command('walkthrough').dispatch('click');
            assert.strictEqual(data.three.walkthroughExits.at(-1), 'toolbar_exit');
            assert.strictEqual(data.workspace.threeWalkthroughHud.hidden, true);
            command('drone').dispatch('click');
            assert.deepStrictEqual(data.three.droneEntries.at(-1), {
                placementId: 'pl-a',
            });
            assert.strictEqual(
                data.workspace.getState().threeNavigation.drone.active,
                true
            );
            assert.strictEqual(command('drone').getAttribute('aria-pressed'), 'true');
            assert.strictEqual(data.workspace.threeDroneHud.hidden, false);
            assert.strictEqual(
                data.workspace.threeDroneAltitude.textContent,
                'ALT 12.5 m'
            );
            assert.strictEqual(
                data.workspace.threeDroneSpeed.textContent,
                'SPD 5 m/s'
            );
            assert.strictEqual(
                data.workspace.threeDroneObstacle.textContent,
                'OBS 2.75 m'
            );
            assert.strictEqual(command('switch-immersive').disabled, false);
            command('switch-immersive').dispatch('click');
            assert.strictEqual(data.three.immersiveSwitches.at(-1), 'walkthrough');
            assert.strictEqual(data.workspace.threeWalkthrough.active, true);
            command('switch-immersive').dispatch('click');
            assert.strictEqual(data.three.immersiveSwitches.at(-1), 'drone');
            assert.strictEqual(data.workspace.threeDrone.active, true);
            command('drone').dispatch('click');
            assert.strictEqual(data.three.droneExits.at(-1), 'toolbar_exit');
            assert.strictEqual(data.workspace.threeDroneHud.hidden, true);

            const orientation = command('view-orientation');
            const viewOption = name => data.workspace.threeNavigation.querySelector(
                '[data-three-view="' + name + '"]'
            );
            assert.strictEqual(
                data.workspace.threeViewOrientationMenu.querySelectorAll(
                    '[data-three-view]'
                ).length,
                4
            );
            ['front', 'top', 'right', 'iso'].forEach(name => {
                orientation.dispatch('click');
                assert.strictEqual(
                    orientation.getAttribute('aria-expanded'),
                    'true'
                );
                assert.strictEqual(
                    data.workspace.threeViewOrientationMenu.hidden,
                    false
                );
                viewOption(name).dispatch('click');
                assert.strictEqual(
                    data.workspace.threeViewOrientationMenu.hidden,
                    true
                );
            });
            assert.strictEqual(data.three.frontViewCount, 1);
            assert.strictEqual(data.three.topViewCount, 1);
            assert.strictEqual(data.three.rightViewCount, 1);
            assert.strictEqual(data.three.isometricCount, 1);
            assert.strictEqual(
                data.workspace.getState().threeNavigation.orientation,
                'iso'
            );
            assert.ok(
                orientation.querySelector('img').getAttribute('src')
                    .endsWith('/view-iso.png')
            );
            command('grid').dispatch('click');
            assert.strictEqual(
                data.workspace.getState().threeNavigation.gridVisible,
                false
            );
            assert.strictEqual(data.three.gridVisibility.at(-1), false);
            assert.strictEqual(command('grid').getAttribute('aria-pressed'), 'false');
            assert.strictEqual(command('grid').getAttribute('title'), 'Show floor grid');
            command('layers').dispatch('click');
            assert.strictEqual(data.workspace.layerPanel.hidden, false);
            assert.strictEqual(
                data.workspace.getState().layers.panelOpen,
                true
            );
            const routesLayer = data.workspace.layerPanel.querySelector(
                '[data-facility-layer="routes"]'
            );
            routesLayer.checked = false;
            routesLayer.dispatch('change');
            assert.strictEqual(
                data.workspace.getState().layers.visibility.routes,
                false
            );
            assert.strictEqual(data.top.layerVisibility.at(-1).routes, false);
            assert.strictEqual(data.three.layerVisibility.at(-1).routes, false);
            data.workspace.layerPanel.querySelector(
                '[data-layer-action="show-all"]'
            ).dispatch('click');
            assert.strictEqual(
                data.workspace.getState().layers.visibility.routes,
                true
            );
            command('display-settings').dispatch('click');
            assert.strictEqual(data.workspace.threeSettingsPanel.hidden, false);
            assert.strictEqual(data.workspace.threeViewOrientationMenu.hidden, true);
            assert.strictEqual(
                command('display-settings').getAttribute('aria-expanded'),
                'true'
            );
            assert.deepStrictEqual(
                data.workspace.getState().threeNavigation.visualSettings,
                {
                    ambient: 1.55,
                    directional: 2,
                    exposure: 1.22,
                    contrast: 1.02,
                    metalness: 0.04,
                    roughness: 0.7,
                    autoRotate: false,
                    wireframe: false,
                    background: 'auto',
                }
            );
            const exposure = data.workspace.threeSettingsPanel.querySelector(
                '[data-three-setting="exposure"]'
            );
            exposure.value = '1.4';
            exposure.dispatch('input');
            assert.strictEqual(
                data.three.visualSettings.at(-1).exposure,
                1.4
            );
            const autoRotate = data.workspace.threeSettingsPanel.querySelector(
                '[data-three-setting="autoRotate"]'
            );
            autoRotate.checked = true;
            autoRotate.dispatch('input');
            assert.strictEqual(
                data.workspace.getState().threeNavigation.visualSettings
                    .autoRotate,
                true
            );
            assert.deepStrictEqual(data.session.getState().layout, before);
            data.workspace.destroy();
        });

    await check('3D compass follows camera heading without changing layout state',
        async () => {
            const data = fixture();
            const before = clone(data.session.getState().layout);
            const compass = data.workspace.threeCompass;
            assert.ok(compass);
            assert.strictEqual(compass.parentNode, data.workspace.threeView);
            assert.strictEqual(
                compass.getAttribute('data-three-overlay'),
                'compass'
            );
            assert.strictEqual(
                compass.getAttribute('data-heading-cardinal'),
                'north'
            );
            assert.strictEqual(
                data.workspace.getState().threeNavigation.compass.cardinal,
                'north'
            );

            data.three.emitCameraOrientation({
                headingDegrees: 90,
                screenTop: { x: 1, z: 0 },
                northAxis: '+Z',
                eastAxis: '+X',
            });
            assert.strictEqual(
                compass.getAttribute('data-heading-degrees'),
                '90.0'
            );
            assert.strictEqual(
                compass.getAttribute('data-heading-cardinal'),
                'east'
            );
            assert.ok(compass.getAttribute('aria-label').includes(
                'top of the view points east'
            ));
            assert.strictEqual(
                data.workspace.getState().threeNavigation.compass
                    .headingDegrees,
                90
            );
            assert.deepStrictEqual(data.session.getState().layout, before);
            data.workspace.destroy();
            assert.strictEqual(data.three.cameraOrientationHandler, null);
        });

    await check('walkthrough context cards stay grounded and intentional',
        async () => {
            const data = fixture();
            const machine = data.session.state.layout.placements[0];
            machine.assetId = 'asset-machine';
            machine.assetDefinitionRevision = 'revision-asset-machine';
            machine.metadata = {
                instanceLabel: 'CNC Mill 04',
            };
            data.session._notify();
            data.workspace._setViewMode('3d');
            data.three.enterWalkthrough({ placementId: 'pl-a' });
            data.three.emitWalkthroughContext({
                placementId: 'pl-a',
                distanceMeters: 2.35,
                lineOfSight: true,
                focusSource: 'center_ray',
            });

            assert.strictEqual(data.workspace.walkthroughContextPrompt.hidden, false);
            assert.strictEqual(
                data.workspace.walkthroughContextPromptName.textContent,
                'CNC Mill 04'
            );
            assert.strictEqual(
                data.workspace.walkthroughContextPromptHint.textContent,
                'E  Details  2.4 m'
            );
            const openEvent = data.root.dispatch('keydown', { key: 'e' });
            assert.strictEqual(openEvent.defaultPrevented, true);
            assert.strictEqual(openEvent.propagationStopped, true);
            assert.strictEqual(data.workspace.walkthroughContextCard.hidden, false);
            assert.strictEqual(
                data.workspace.walkthroughContextTitle.textContent,
                'CNC Mill 04'
            );
            const renderedContextText = () => (
                data.workspace.walkthroughContextBody.descendants()
                    .map(item => item.textContent)
                    .join(' ')
            );
            assert.ok(renderedContextText().includes('Machine the fixture plate'));
            assert.ok(renderedContextText().includes('4.8 min'));

            data.workspace.walkthroughContextMode.value = 'safety';
            data.workspace.walkthroughContextMode.dispatch('change');
            assert.ok(renderedContextText().includes('Eye protection'));
            const pin = data.workspace.walkthroughContextCard.querySelector(
                '[data-walkthrough-context-action="pin"]'
            );
            pin.dispatch('click');
            data.three.emitWalkthroughContext(null);
            assert.strictEqual(data.workspace.walkthroughContextCard.hidden, false);
            assert.strictEqual(pin.getAttribute('aria-pressed'), 'true');

            const dismissEvent = data.root.dispatch('keydown', { key: 'Escape' });
            assert.strictEqual(dismissEvent.defaultPrevented, true);
            assert.strictEqual(dismissEvent.propagationStopped, true);
            assert.strictEqual(data.workspace.walkthroughContextCard.hidden, true);
            assert.strictEqual(
                data.workspace.getState().threeNavigation.contextCard.expanded,
                false
            );

            data.three.emitWalkthroughContext({
                placementId: 'pl-a',
                distanceMeters: 1.5,
            });
            data.workspace.walkthroughContextPrompt.dispatch('click');
            data.workspace.walkthroughContextCard.querySelector(
                '[data-walkthrough-context-action="select"]'
            ).dispatch('click');
            assert.strictEqual(data.workspace.getState().viewMode, 'plan');
            assert.deepStrictEqual(data.session.getState().selection, ['pl-a']);
            assert.strictEqual(
                data.three.walkthroughExits.at(-1),
                'context_select'
            );
            data.workspace.destroy();
            assert.strictEqual(data.three.walkthroughContextHandler, null);
        });

    await check('Drone mode reuses grounded machine context cards',
        async () => {
            const data = fixture();
            const machine = data.session.state.layout.placements[0];
            machine.assetId = 'asset-machine';
            machine.assetDefinitionRevision = 'revision-asset-machine';
            machine.metadata = { instanceLabel: 'CNC Mill 04' };
            data.session._notify();
            data.workspace._setViewMode('3d');
            data.three.enterDrone({ placementId: 'pl-a' });
            data.three.emitWalkthroughContext({
                placementId: 'pl-a',
                distanceMeters: 8.2,
                lineOfSight: true,
                focusSource: 'center_ray',
            });
            assert.strictEqual(data.workspace.walkthroughContextPrompt.hidden, false);
            const openEvent = data.root.dispatch('keydown', { key: 'e' });
            assert.strictEqual(openEvent.defaultPrevented, true);
            assert.strictEqual(data.workspace.walkthroughContextCard.hidden, false);
            data.workspace.walkthroughContextCard.querySelector(
                '[data-walkthrough-context-action="select"]'
            ).dispatch('click');
            assert.strictEqual(data.workspace.getState().viewMode, 'plan');
            assert.strictEqual(data.three.droneExits.at(-1), 'context_select');
            data.workspace.destroy();
            assert.strictEqual(data.three.droneHandler, null);
        });

    await check('3D viewport recording configures, monitors, previews, and exports',
        async () => {
            const data = fixture({ recordingCountdownSeconds: 0 });
            data.workspace._setViewMode('3d');
            const record = data.workspace.threeNavigation.querySelector(
                '[data-three-command="record"]'
            );
            assert.strictEqual(record.disabled, false);
            record.dispatch('click');
            assert.strictEqual(data.workspace.threeRecordingPanel.hidden, false);
            assert.ok(
                data.workspace.recordingFormatText.textContent.includes('WebM')
            );

            data.workspace.recordingPresentationInput.value = 'training';
            data.workspace.recordingPresentationInput.dispatch('change');
            assert.strictEqual(data.workspace.recordingHudInput.checked, true);
            assert.strictEqual(data.workspace.recordingCursorInput.checked, true);
            assert.strictEqual(data.workspace.recordingHudInput.disabled, false);
            data.workspace.recordingResolutionInput.value = '1080p';
            data.workspace.recordingResolutionInput.dispatch('change');
            data.workspace.recordingFpsInput.value = '60';
            data.workspace.recordingFpsInput.dispatch('change');
            data.workspace.recordingMicrophoneInput.checked = true;
            data.workspace.recordingMicrophoneInput.dispatch('change');

            data.workspace.threeRecordingPanel.querySelector(
                '[data-recording-action="start"]'
            ).dispatch('click');
            await Promise.resolve();
            const controller = data.recordingRuntime.controllers[0];
            assert.ok(controller);
            assert.strictEqual(controller.calls[0][0], 'start');
            assert.strictEqual(controller.calls[0][1].resolution, '1080p');
            assert.strictEqual(controller.calls[0][1].fps, 60);
            assert.strictEqual(controller.calls[0][1].microphone, true);
            assert.strictEqual(controller.calls[0][1].includeHud, true);
            assert.strictEqual(controller.calls[0][1].includeCursor, true);
            assert.strictEqual(data.workspace.threeRecordingMonitor.hidden, false);
            assert.strictEqual(record.getAttribute('aria-pressed'), 'true');

            data.workspace.threeRecordingMonitor.querySelector(
                '[data-recording-action="pause"]'
            ).dispatch('click');
            assert.strictEqual(
                data.workspace.getState().recording.status,
                'paused'
            );
            assert.strictEqual(
                data.workspace.threeRecordingMonitor.querySelector(
                    '[data-recording-action="pause"]'
                ).textContent,
                'Resume'
            );
            data.workspace.threeRecordingMonitor.querySelector(
                '[data-recording-action="stop"]'
            ).dispatch('click');
            assert.strictEqual(data.workspace.threeRecordingPreview.hidden, false);
            assert.strictEqual(
                data.workspace.recordingPreviewVideo.getAttribute('src'),
                'blob:workspace-recording'
            );
            assert.ok(
                data.workspace.recordingPreviewSummary.textContent
                    .includes('1920 x 1080')
            );
            data.workspace.threeRecordingPreview.querySelector(
                '[data-recording-action="download"]'
            ).dispatch('click');
            assert.strictEqual(controller.calls.at(-1)[0], 'download');
            data.workspace.threeRecordingPreview.querySelector(
                '[data-recording-action="discard"]'
            ).dispatch('click');
            assert.strictEqual(data.workspace.threeRecordingPreview.hidden, true);
            assert.strictEqual(
                data.workspace.getState().recording.status,
                'idle'
            );
            data.workspace.destroy();
            assert.strictEqual(controller.disposed, true);
        });

    await check('named 3D viewpoints persist and restore camera state only',
        async () => {
            const stored = {};
            const storage = {
                getItem(key) { return stored[key] || null; },
                setItem(key, value) { stored[key] = String(value); },
            };
            const data = fixture({ planPreferenceStorage: storage });
            const layoutBefore = clone(data.session.getState().layout);
            data.workspace._setViewMode('3d');
            const trigger = data.workspace.threeNavigation.querySelector(
                '[data-three-command="viewpoints"]'
            );
            trigger.dispatch('click');
            assert.strictEqual(data.workspace.threeViewpointPanel.hidden, false);
            data.workspace.threeViewpointInput.value = 'Receiving overview';
            data.workspace.threeViewpointPanel.querySelector(
                '[data-viewpoint-action="save"]'
            ).dispatch('click');
            assert.strictEqual(
                data.workspace.getState().threeNavigation.viewpoints.length,
                1
            );
            assert.ok(stored[data.workspace.threeViewpointKey]);
            assert.deepStrictEqual(data.session.getState().layout, layoutBefore);
            data.workspace.destroy();

            const reopened = fixture({ planPreferenceStorage: storage });
            reopened.workspace._setViewMode('3d');
            const reopenedTrigger = reopened.workspace.threeNavigation.querySelector(
                '[data-three-command="viewpoints"]'
            );
            reopenedTrigger.dispatch('click');
            const go = reopened.workspace.threeViewpointPanel.querySelector(
                '[data-viewpoint-action="apply"]'
            );
            assert.strictEqual(go.textContent, 'Receiving overview');
            reopened.three.cameraView.position.x = 99;
            go.dispatch('click');
            assert.strictEqual(
                reopened.three.appliedCameraViews.at(-1).position.x,
                8
            );
            assert.strictEqual(reopened.workspace.threeViewpointPanel.hidden, true);
            reopenedTrigger.dispatch('click');
            reopened.workspace.threeViewpointPanel.querySelector(
                '[data-viewpoint-action="delete"]'
            ).dispatch('click');
            assert.strictEqual(
                reopened.workspace.getState().threeNavigation.viewpoints.length,
                0
            );
            assert.deepStrictEqual(reopened.session.getState().layout, layoutBefore);
            reopened.workspace.destroy();
        });

    await check('painting models keeps the 3D view where it is; moving one fits the view again',
        async () => {
            const data = fixture();
            const reenter3d = async function (change) {
                const next = clone(data.session.state.layout);
                change(next);
                data.session.state.layout = next;
                data.session._notify();
                data.workspace._setViewMode('plan');
                data.workspace._setViewMode('3d');
                await data.workspace.whenIdle();
                await Promise.resolve();
                await Promise.resolve();
            };
            data.workspace._setViewMode('3d');
            await data.workspace.whenIdle();
            await Promise.resolve();
            await Promise.resolve();
            const fitted = data.three.fitLayoutCount;
            assert.strictEqual(fitted, 1);
            await reenter3d(next => {
                next.placements[0].componentMaterials = {
                    representation: 'overview',
                    overrides: [{ key: 'p:body#0', color: '#1565c0' }],
                };
            });
            assert.strictEqual(data.three.fitLayoutCount, fitted);
            await reenter3d(next => { next.placements[0].transform.position.x += 2; });
            assert.strictEqual(data.three.fitLayoutCount, fitted + 1);
            data.workspace.destroy();
        });

    await check('a review that only repaints keeps the views; one that moves something fits them',
        async () => {
            const data = fixture();
            data.workspace._setViewMode('3d');
            await data.workspace.whenIdle();
            const stage = function (change, operations) {
                const ghost = clone(data.session.state.layout);
                change(ghost);
                data.session.state.layoutProposal = {
                    authority: 'server-authoritative', previewPure: true, baseRevision: 'rev-1', selectedIndex: 0,
                    alternatives: [{ proposalId: 'proposal-look', alternativeId: 'alternative-look', operations,
                        ghostPreview: { layout: ghost, routeProposals: [] }, metrics: {}, findings: [],
                        newHardFindingIds: [] }],
                };
                data.session._notify();
            };
            const close = function () {
                data.session.state.layoutProposal = null;
                data.session._notify();
            };
            const paint = { representation: 'overview', overrides: [{ key: 'p:body#0', color: '#1565c0' }] };
            const before = data.controller.fitCount;
            stage(ghost => { ghost.placements[0].componentMaterials = paint; },
                [{ op: 'set_component_materials', placementId: 'pl-a', materials: paint, visualSha256: 'a'.repeat(64) }]);
            assert.strictEqual(data.controller.fitCount, before);
            close();
            assert.strictEqual(data.controller.fitCount, before);
            stage(ghost => { ghost.placements[0].transform.position.x += 3; },
                [{ op: 'move_placement', placementId: 'pl-a' }]);
            assert.strictEqual(data.controller.fitCount, before + 1);
            close();
            assert.strictEqual(data.controller.fitCount, before + 2);
            data.workspace.destroy();
        });

    await check('a Sage review opens in the view that shows it: a building step leaves the site photo for the plan',
        async () => {
            const data = fixture();
            data.workspace.siteView = { element: data.workspace.document.createElement('div'),
                render() {}, show() {}, hide() {}, destroy() {} };
            data.workspace.siteTab = data.workspace.document.createElement('button');
            data.workspace._setViewMode('site');
            await data.workspace.whenIdle();
            let staged = 0;
            const stage = function (operations) {
                const ghost = clone(data.session.state.layout);
                ghost.placements[0].transform.position.x += 0.5 + staged++;
                data.session.state.layoutProposal = {
                    authority: 'server-authoritative', previewPure: true, baseRevision: 'rev-1', selectedIndex: 0,
                    alternatives: [{ proposalId: 'proposal-view', alternativeId: 'alternative-view', operations,
                        ghostPreview: { layout: ghost, routeProposals: [] }, metrics: {}, findings: [],
                        newHardFindingIds: [] }],
                };
                data.session._notify();
            };
            const close = function () {
                data.session.state.layoutProposal = null;
                data.session._notify();
            };
            const settle = () => new Promise(resolve => setTimeout(resolve, 0));
            stage([{ op: 'add_zone', zone: { zoneId: 'zn-receiving' } }]);  // a building step: the 2D plan
            await settle();
            assert.strictEqual(data.workspace.viewMode, 'plan');
            close();
            stage([{ op: 'upsert_site_area', area: { areaId: 'area-truck-court' } }]);  // the docks: the site photo
            await settle();
            assert.strictEqual(data.workspace.viewMode, 'site');
            close();
            stage([{ op: 'place_asset', placement: { placementId: 'pl-forklift-01' } }]);  // models, from the site: 3D
            await settle();
            assert.strictEqual(data.workspace.viewMode, '3d');
            close();
            stage([{ op: 'add_zone', zone: { zoneId: 'zn-storage' } }]);  // Plan and 3D stay the user's choice
            await settle();
            assert.strictEqual(data.workspace.viewMode, '3d');
            close();
            data.workspace.destroy();
        });

    await check('a step applied directly (Apply Directly mode) moves the view as its review would have',
        async () => {
            const data = fixture();
            data.workspace.siteView = { element: data.workspace.document.createElement('div'),
                render() {}, show() {}, hide() {}, destroy() {} };
            data.workspace.siteTab = data.workspace.document.createElement('button');
            data.workspace._setViewMode('site');
            await data.workspace.whenIdle();
            let receipts = 0;
            const applied = function (operationNames) {
                data.session.state.lastApprovedOperationCommit = { receiptId: 'receipt-' + ++receipts,
                    directApply: true, operationNames };
                data.session._notify();
            };
            const settle = () => new Promise(resolve => setTimeout(resolve, 0));
            let buildingFits = 0;
            data.workspace._fitPlanToBuilding = function () { buildingFits += 1; };
            applied(['set_plan_settings', 'set_building_pose', 'set_perimeter_walls']);  // the building: the 2D plan
            await settle();
            await settle();
            assert.strictEqual(data.workspace.viewMode, 'plan');
            assert.strictEqual(buildingFits, 1);  // shown large in the plan
            applied(['add_zone', 'add_floor_marking']);  // the next building step, in the plan: shown large again
            await settle();
            await settle();
            assert.strictEqual(buildingFits, 2);
            applied(['edit_perimeter_walls', 'add_zone', 'set_site_context', 'upsert_site_area']);  // docks: the photo
            await settle();
            assert.strictEqual(data.workspace.viewMode, 'site');
            applied(['place_asset_array', 'place_asset', 'upsert_interior_wall']);  // contents: 3D
            await settle();
            assert.strictEqual(data.workspace.viewMode, '3d');
            applied(['edit_perimeter_walls', 'set_ground', 'set_component_materials']);  // paint stays in 3D
            await settle();
            assert.strictEqual(data.workspace.viewMode, '3d');
            applied(['add_zone', 'set_site_context', 'upsert_site_area', 'add_aisle']);  // the car park, from 3D: 3D
            await settle();
            assert.strictEqual(data.workspace.viewMode, '3d');
            applied(['upsert_site_reference', 'upsert_site_reference']);  // reference points show on the photo only
            await settle();
            assert.strictEqual(data.workspace.viewMode, 'site');
            data.session._notify();  // the same commit again moves nothing
            data.workspace._setViewMode('plan');
            data.session._notify();
            await settle();
            assert.strictEqual(data.workspace.viewMode, 'plan');
            data.workspace.destroy();
        });

    await check('toolbar commands delegate exactly once and Fit changes only view',
        async () => {
            const data = fixture();
            data.session.select('pl-a');
            const layoutBeforeFit = clone(data.session.getState().layout);
            await data.workspace.executeCommand('fit');
            assert.strictEqual(data.controller.fitCount, 1);
            assert.strictEqual(data.controller.fitFacilityCount, 1);
            await data.workspace.executeCommand('fit-layout');
            assert.strictEqual(data.controller.fitLayoutCount, 1);
            await data.workspace.executeCommand('top-view');
            assert.strictEqual(data.controller.topViewCount, 1);
            assert.strictEqual(data.workspace.getState().viewMode, '3d');
            assert.deepStrictEqual(data.session.getState().layout, layoutBeforeFit);
            for (const command of ['rotate', 'duplicate', 'lock', 'undo', 'redo', 'save']) {
                await data.workspace.executeCommand(command);
                await data.workspace.whenIdle();
            }
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'rotateSelected90').length,
                1
            );
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'duplicateSelected').length,
                1
            );
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'lockSelected').length,
                1
            );
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'undo').length,
                1
            );
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'redo').length,
                1
            );
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'save').length,
                1
            );
            data.workspace.destroy();
        });

    await check('bulk zone editor creates exact named zones in one gesture', async () => {
        const data = fixture({ externalCommandSurface: true });
        await data.workspace.executeCommand('bulk-zones');
        assert.strictEqual(data.workspace.bulkZoneDialog.hidden, false);
        data.workspace.bulkZoneDialog.querySelector(
            '[data-bulk-zone-action="add-row"]'
        ).dispatch('click');
        const labels = data.workspace.bulkZoneDialog.querySelectorAll(
            '[data-bulk-zone-field="label"]'
        );
        const widths = data.workspace.bulkZoneDialog.querySelectorAll(
            '[data-bulk-zone-field="width"]'
        );
        labels[0].value = 'Machining Hall';
        labels[0].dispatch('input');
        widths[0].value = '30';
        widths[0].dispatch('input');
        labels[1].value = 'Assembly Hall';
        labels[1].dispatch('input');
        data.workspace.bulkZoneDialog.querySelector(
            '[data-bulk-zone-action="apply"]'
        ).dispatch('click');
        await data.workspace.whenIdle();
        const calls = data.session.calls.filter(
            call => call[0] === 'createZones'
        );
        assert.strictEqual(calls.length, 1);
        assert.strictEqual(calls[0][1].length, 2);
        assert.strictEqual(calls[0][1][0].label, 'Machining Hall');
        assert.strictEqual(calls[0][1][0].width, 30);
        assert.strictEqual(calls[0][1][1].label, 'Assembly Hall');
        assert.strictEqual(data.session.state.history.length, 1);
        assert.strictEqual(data.workspace.bulkZoneDialog.hidden, true);
        data.workspace.destroy();
    });

    await check('manufacturing cell panel persists a named group and can ungroup it',
        async () => {
            const data = fixture({ externalCommandSurface: true });
            data.session.selectMany(['pl-a', 'pl-b']);
            await data.workspace.executeCommand('create-cell-group');
            assert.strictEqual(data.workspace.cellGroupDialog.hidden, false);
            const name = data.workspace.cellGroupDialog.querySelector(
                '[data-cell-group-field="baseName"]'
            );
            const prefix = data.workspace.cellGroupDialog.querySelector(
                '[data-cell-group-field="prefix"]'
            );
            const gate = data.workspace.cellGroupDialog.querySelector(
                '[data-cell-group-field="gateSide"]'
            );
            const loading = data.workspace.cellGroupDialog.querySelector(
                '[data-cell-group-field="loadingSide"]'
            );
            const service = data.workspace.cellGroupDialog.querySelector(
                '[data-cell-group-field="serviceSide"]'
            );
            name.value = 'Robot Cell';
            name.dispatch('input');
            prefix.value = 'R';
            prefix.dispatch('input');
            gate.value = 'south';
            gate.dispatch('change');
            loading.value = 'east';
            loading.dispatch('change');
            service.value = 'north';
            service.dispatch('change');
            data.workspace.cellGroupDialog.querySelector(
                '[data-cell-group-action="apply"]'
            ).dispatch('click');
            await data.workspace.whenIdle();
            const calls = data.session.calls.filter(
                call => call[0] === 'createCellGroup'
            );
            assert.strictEqual(calls.length, 1);
            assert.strictEqual(calls[0][1].baseName, 'Robot Cell');
            assert.strictEqual(calls[0][1].prefix, 'R');
            assert.ok(calls[0][1].width > 0);
            assert.ok(calls[0][1].depth > 0);
            assert.deepStrictEqual(calls[0][1].functionalInterfaces, {
                gate: 'south',
                loading: 'east',
                service: 'north',
            });
            const cellId = data.session.state.selection[0];
            assert.strictEqual(
                data.session.state.layout.zones.find(
                    zone => zone.zoneId === cellId
                ).extensions.cellGroup.membership,
                'geometric'
            );
            assert.deepStrictEqual(
                data.session.state.layout.zones.find(
                    zone => zone.zoneId === cellId
                ).extensions.cellGroup.functionalInterfaces,
                calls[0][1].functionalInterfaces
            );
            assert.strictEqual(
                data.workspace.getCommandStates()['ungroup-cell'].disabled,
                false
            );
            await data.workspace.executeCommand('ungroup-cell');
            await data.workspace.whenIdle();
            assert.strictEqual(data.session.calls.filter(
                call => call[0] === 'ungroupCell'
            ).length, 1);
            assert.strictEqual(
                data.session.state.layout.zones.some(
                    zone => zone.zoneId === cellId
                ),
                false
            );
            data.workspace.destroy();
        });

    await check('semantic aisle tool draws one validated native route', async () => {
        const data = fixture({ externalCommandSurface: true });
        await data.workspace.executeCommand('aisle');
        assert.strictEqual(data.workspace.aisleDialog.hidden, false);
        const name = data.workspace.aisleDialog.querySelector(
            '[data-aisle-field="label"]'
        );
        const kind = data.workspace.aisleDialog.querySelector(
            '[data-aisle-field="aisleKind"]'
        );
        const direction = data.workspace.aisleDialog.querySelector(
            '[data-aisle-field="direction"]'
        );
        const width = data.workspace.aisleDialog.querySelector(
            '[data-aisle-field="corridorWidth"]'
        );
        name.value = 'Main Forklift Boulevard';
        name.dispatch('input');
        kind.value = 'forklift';
        kind.dispatch('change');
        direction.value = 'two_way';
        direction.dispatch('change');
        width.value = '3.5';
        width.dispatch('input');
        data.workspace.aisleDialog.querySelector(
            '[data-aisle-action="draw"]'
        ).dispatch('click');
        data.workspace.planView.dispatch('pointerdown', {
            world: { x: 2, y: 0, z: 3 },
        });
        data.workspace.planView.dispatch('pointermove', {
            world: { x: 12, y: 0, z: 3 },
        });
        assert.deepStrictEqual(data.top.transientAislePreviews.at(-1), {
            points: [
                { x: 2, y: 0, z: 3 },
                { x: 12, y: 0, z: 3 },
            ],
            corridorWidth: 3.5,
            color: '#d9a514',
        });
        data.workspace.planView.dispatch('pointerup', {
            world: { x: 12, y: 0, z: 3 },
        });
        await data.workspace.whenIdle();
        const calls = data.session.calls.filter(
            call => call[0] === 'createAisle'
        );
        assert.strictEqual(calls.length, 1);
        assert.strictEqual(calls[0][1].label, 'Main Forklift Boulevard');
        assert.strictEqual(calls[0][1].corridorWidth, 3.5);
        assert.strictEqual(calls[0][1].direction, 'two_way');
        assert.strictEqual(
            calls[0][1].clearanceEvidenceStatus,
            'unverified'
        );
        assert.strictEqual(data.session.state.layout.routes.length, 1);
        assert.deepStrictEqual(
            data.session.state.layout.routes[0].centerline,
            [
                { x: 2, y: 0, z: 3 },
                { x: 12, y: 0, z: 3 },
            ]
        );
        data.workspace.destroy();
    });

    await check('the Scenes pane draws a light area on the plan: one rectangle, then back to 3D', async () => {
        const data = fixture();
        const context = data.workspace.appearanceLibraryContext();
        data.workspace._setViewMode('3d');
        const drawn = [];
        const draw = () => context.drawLightArea(value => drawn.push(value));
        assert.strictEqual(draw(), true);
        assert.strictEqual(data.workspace.viewMode, 'plan');
        data.workspace.planView.dispatch('pointerdown', { world: { x: 1, y: 0, z: 1 } });
        data.workspace.planView.dispatch('pointermove', { world: { x: 5.5, y: 0, z: 4 } });
        assert.deepStrictEqual(data.top.transientZonePreviews.at(-1), {
            points: [{ x: 1, z: 1 }, { x: 5.5, z: 1 }, { x: 5.5, z: 4 }, { x: 1, z: 4 }],
            options: { kind: 'rectangle', closed: true },
        });
        data.workspace.planView.dispatch('pointerup', { world: { x: 5.5, y: 0, z: 4 } });
        assert.deepStrictEqual(drawn, [{ minX: 1, minZ: 1, maxX: 5.5, maxZ: 4 }], 'plan metres, on the grid');
        assert.strictEqual(data.workspace.viewMode, '3d', 'back to 3D');
        assert.deepStrictEqual(data.top.transientZonePreviews.at(-1), { points: [], options: {} });
        await data.workspace.whenIdle();
        assert.strictEqual(data.session.calls.filter(call => call[0] === 'createRectangleZone').length, 0, 'no zone made');
        // A click without a drag (snapped to the same grid point) waits for a real rectangle; Esc goes back to 3D.
        draw();
        data.workspace.planView.dispatch('pointerdown', { world: { x: 2, y: 0, z: 2 } });
        data.workspace.planView.dispatch('pointerup', { world: { x: 2.05, y: 0, z: 2 } });
        assert.strictEqual(drawn.length, 1);
        assert.strictEqual(data.workspace.viewMode, 'plan');
        data.root.dispatch('keydown', { key: 'Escape', target: data.root });
        assert.deepStrictEqual(drawn.slice(1), [null]);
        assert.strictEqual(data.workspace.viewMode, '3d');
        // Picking a tool or another view ends it and leaves that choice alone.
        await data.workspace.executeCommand('pan');
        draw();
        assert.strictEqual(data.workspace.toolMode, 'select', 'drawing starts from Select');
        await data.workspace.executeCommand('rectangle-zone');
        assert.deepStrictEqual(drawn.slice(2), [null]);
        assert.strictEqual(data.workspace.toolMode, 'rectangle-zone');
        assert.strictEqual(data.workspace.viewMode, 'plan');
        draw();
        data.workspace._setViewMode('3d');
        assert.deepStrictEqual(drawn.slice(3), [null]);
        assert.strictEqual(data.workspace.viewMode, '3d');
        data.workspace.destroy();
    });

    await check('rectangle and polygon zone tools commit one gesture each', async () => {
        const data = fixture();
        await data.workspace.executeCommand('rectangle-zone');
        data.workspace.planView.dispatch('pointerdown', {
            world: { x: 1, y: 0, z: 1 },
        });
        data.workspace.planView.dispatch('pointermove', {
            world: { x: 5, y: 0, z: 4 },
        });
        assert.deepStrictEqual(data.top.transientZonePreviews.at(-1), {
            points: [
                { x: 1, z: 1 },
                { x: 5, z: 1 },
                { x: 5, z: 4 },
                { x: 1, z: 4 },
            ],
            options: { kind: 'rectangle', closed: true },
        });
        data.workspace.planView.dispatch('pointerup', {
            world: { x: 5, y: 0, z: 4 },
        });
        await data.workspace.whenIdle();
        assert.strictEqual(
            data.session.calls.filter(call => call[0] === 'createRectangleZone').length,
            1
        );
        assert.deepStrictEqual(
            data.top.transientZonePreviews.at(-1),
            { points: [], options: {} }
        );
        await data.workspace.executeCommand('polygon-zone');
        [
            { x: 0, y: 0, z: 0 },
            { x: 3, y: 0, z: 0 },
            { x: 2, y: 0, z: 2 },
        ].forEach(world => data.workspace.planView.dispatch('click', { world }));
        assert.deepStrictEqual(data.top.transientZonePreviews.at(-1), {
            points: [
                { x: 0, y: 0, z: 0 },
                { x: 3, y: 0, z: 0 },
                { x: 2, y: 0, z: 2 },
            ],
            options: { kind: 'polygon', closed: false },
        });
        data.root.dispatch('keydown', {
            key: 'Enter',
            target: data.root,
        });
        await data.workspace.whenIdle();
        assert.strictEqual(
            data.session.calls.filter(call => call[0] === 'createPolygonZone').length,
            1
        );
        assert.deepStrictEqual(
            data.top.transientZonePreviews.at(-1),
            { points: [], options: {} }
        );
        data.workspace.destroy();
    });

    await check('clicks that belong to floor-plan picks never reach the polygon zone tool', async () => {
        const data = fixture();
        await data.workspace.executeCommand('polygon-zone');
        let owned = true;
        const synced = [];
        const told = [];
        data.workspace.floorPlan = {
            picking: null,
            ownsClick() { return owned; },
            ownsDoubleClick() { return owned; },
            forgetPress() { told.push('press'); },
            toolChosen() { told.push('tool'); },
            cancelPicking() { told.push('cancel'); this.picking = null; },
            handlePointerDown() { return false; },
            handlePointerMove() { return false; },
            sync(layout, options) { synced.push(options); },
            dispose() {},
        };
        const before = data.top.transientZonePreviews.length;
        [{ x: 0, y: 0, z: 0 }, { x: 3, y: 0, z: 0 }].forEach(world => data.workspace.planView.dispatch('click',
            { world }));
        data.workspace.planView.dispatch('dblclick', { world: { x: 3, y: 0, z: 0 } });
        await data.workspace.whenIdle();
        assert.strictEqual(data.top.transientZonePreviews.length, before, 'no corner was added');
        assert.strictEqual(data.session.calls.filter(call => call[0] === 'createPolygonZone').length, 0);
        owned = false;  // a later click is the tool's again
        data.workspace.planView.dispatch('click', { world: { x: 1, y: 0, z: 1 } });
        assert.deepStrictEqual(data.top.transientZonePreviews.at(-1).points, [{ x: 1, y: 0, z: 1 }]);
        data.workspace._updateController();
        assert.deepStrictEqual(synced.at(-1), { preview: false }, 'the plan says whether it shows a preview');
        // Every press is announced; a tool the user chooses, and Escape, are the user's choice.
        told.length = 0;
        data.workspace.planView.dispatch('pointerdown', { button: 0, world: { x: 2, y: 0, z: 2 } });
        assert.strictEqual(told[0], 'press');
        data.workspace._cancelPointerGesture();
        told.length = 0;
        await data.workspace.executeCommand('select');
        assert.deepStrictEqual(told, ['tool']);
        // Escape ends floor-plan picks first, and leaves the tool as it is.
        told.length = 0;
        data.workspace.floorPlan.picking = { mode: 'align', points: [] };
        await data.workspace.executeCommand('polygon-zone');
        told.length = 0;
        data.root.dispatch('keydown', { key: 'Escape', target: data.root });
        assert.deepStrictEqual(told, ['cancel']);
        assert.strictEqual(data.workspace.toolMode, 'polygon-zone');
        // Before any panel: with Motion path's panel open, the first Escape ends the picks and leaves the panel.
        told.length = 0;
        data.workspace.floorPlan.picking = { mode: 'measure', points: [] };
        data.workspace.navigationState.open = true;
        data.root.dispatch('keydown', { key: 'Escape', target: data.root });
        assert.deepStrictEqual(told, ['cancel']);
        assert.strictEqual(data.workspace.navigationState.open, true);
        data.workspace.navigationState.open = false;
        data.root.dispatch('keydown', { key: 'Escape', target: data.root });
        assert.deepStrictEqual(told, ['cancel', 'tool']);
        assert.strictEqual(data.workspace.toolMode, 'select');
        // From a field in a workspace panel (the Motion path one) too: the picks end before the panel or the field
        // sees the key.
        await data.workspace.executeCommand('polygon-zone');
        data.workspace.floorPlan.picking = { mode: 'align', points: [] };
        const field = data.workspace.document.createElement('input');
        data.workspace.navigationDialog.appendChild(field);
        const seen = [];
        const panelSaw = () => seen.push('panel');
        data.workspace.navigationDialog.addEventListener('keydown', panelSaw);
        told.length = 0;
        const escape = field.dispatch('keydown', { key: 'Escape' });
        assert.deepStrictEqual(told, ['cancel']);
        assert.deepStrictEqual(seen, [], 'the panel never saw it');
        assert.strictEqual(escape.defaultPrevented, true);
        assert.strictEqual(data.workspace.toolMode, 'polygon-zone', 'the tool stays');
        field.dispatch('keydown', { key: 'Escape' });
        assert.deepStrictEqual(seen, ['panel'], 'the next Escape is the panel one');
        data.workspace.navigationDialog.removeEventListener('keydown', panelSaw);
        data.workspace.navigationDialog.removeChild(field);
        data.workspace.closeNavigationDialog(true);
        // Every way of choosing a tool reaches the picks: a key (M opens Floor marking), a panel's Draw, a light
        // area. Only the picks' own switches and a tool put back on resume do not.
        const picksSee = async (label, act, expected) => {
            data.workspace.floorPlan.picking = { mode: 'measure', points: [] };
            told.length = 0;
            await act();
            assert.deepStrictEqual(told, expected, label);
        };
        await picksSee('M', () => data.root.dispatch('keydown', { key: 'm', target: data.root }), ['tool']);
        assert.strictEqual(data.workspace.toolMode, 'floor-marking');
        data.workspace.closeFloorMarkingPalette(true);
        await picksSee('a panel switching its tool on', () => data.workspace._setToolMode('aisle'), ['tool']);
        await picksSee('the picks\' own switch', () => data.workspace._setToolMode('select', { keepPicks: true }), []);
        await picksSee('a light area', () => data.workspace._drawLightArea(() => {}), ['tool']);
        data.workspace._endLightAreaDraw(null, false);
        await picksSee('a tool put back on resume', () => {
            data.workspace.suspend();
            data.workspace.resume();
        }, []);
        // Picks are points on the plan: leaving it ends them, and Escape elsewhere is not theirs.
        await picksSee('the 3D view', () => data.workspace._setViewMode('3d'), ['cancel']);
        data.workspace.floorPlan.picking = { mode: 'measure', points: [] };
        told.length = 0;
        const elsewhere = data.root.dispatch('keydown', { key: 'Escape', target: data.root });
        assert.ok(!told.includes('cancel'), 'Escape in the 3D view is not the picks\'');
        assert.strictEqual(elsewhere.defaultPrevented, true, 'the 3D view handles it as before');
        data.workspace.floorPlan.picking = null;
        data.workspace._setViewMode('plan');
        data.workspace.destroy();
    });

    await check('floor marking palette creates and edits one semantic object',
        async () => {
            const manager = new FakeSurfaceManager();
            const data = fixture({
                externalCommandSurface: true,
                floatingSurfaceRuntime: {
                    createSurfaceManager() { return manager; },
                },
                floatingDom: fakeFloatingDom(),
            });
            await data.workspace.executeCommand('floor-marking');
            assert.strictEqual(data.workspace.floorMarkingPalette.hidden, false);
            assert.strictEqual(
                data.workspace.getCommandStates()['floor-marking'].active,
                true
            );
            const keepClear = data.workspace.floorMarkingPalette.querySelector(
                '[data-floor-marking-type="keep_clear"]'
            );
            keepClear.dispatch('click');
            assert.strictEqual(data.workspace.floorMarkingPalette.hidden, true);
            data.workspace.planView.dispatch('pointerdown', {
                world: { x: 2, y: 0, z: 2 },
            });
            data.workspace.planView.dispatch('pointermove', {
                world: { x: 6, y: 0, z: 4 },
            });
            assert.strictEqual(
                data.top.transientFloorMarkingPreviews.at(-1).markingType,
                'keep_clear'
            );
            data.workspace.planView.dispatch('pointerup', {
                world: { x: 6, y: 0, z: 4 },
            });
            await data.workspace.whenIdle();
            const createCall = data.session.calls.find(
                call => call[0] === 'createFloorMarking'
            );
            assert(createCall);
            assert.strictEqual(createCall[1].semanticRole, 'keep_clear');
            assert.deepStrictEqual(createCall[1].transform.position, {
                x: 4, y: 0, z: 3,
            });
            assert.strictEqual(
                data.top.transientFloorMarkingPreviews.at(-1),
                null
            );
            const markingId = data.session.getState().selection[0];
            planFloorMarking(data, markingId, {
                left: 200, top: 200, width: 160, height: 80,
            });
            await data.workspace.executeCommand('select');
            data.session.select(markingId);
            assert.strictEqual(manager.isOpen(), true);
            const toolbar = data.workspace.selectionToolbarElement;
            assert.strictEqual(
                toolbar.getAttribute('data-facility-floor-marking-toolbar'),
                markingId
            );
            const textInput = toolbar.querySelector('[data-floor-marking-text]');
            textInput.value = 'CNC KEEP CLEAR';
            textInput.dispatch('keydown', { key: 'Enter' });
            await data.workspace.whenIdle();
            const editCall = data.session.calls.filter(
                call => call[0] === 'editFloorMarking'
            ).at(-1);
            assert.strictEqual(editCall[1], markingId);
            assert.strictEqual(editCall[2].label, 'CNC KEEP CLEAR');
            assert.strictEqual(editCall[2].text, 'CNC KEEP CLEAR');
            data.workspace.destroy();
        });

    await check('session updates controller and adapter selections return to session',
        async () => {
            const data = fixture();
            const initialLayoutCount = data.controller.layouts.length;
            data.session.select('pl-b');
            assert.strictEqual(data.controller.layouts.length, initialLayoutCount);
            assert.strictEqual(
                data.controller.selections[data.controller.selections.length - 1],
                'pl-b'
            );
            data.three.emitSelection('pl-a');
            assert.deepStrictEqual(data.session.getState().selection, ['pl-a']);
            assert.ok(data.controller.catalogs.length > 0);
            data.workspace.destroy();
        });

    await check('a Ctrl or Cmd click in 3D adds to the selection and a second one removes it',
        async () => {
            const data = fixture();
            data.three.emitSelection('pl-a', { ctrlKey: false });
            data.three.emitSelection('pl-b', { ctrlKey: true });
            assert.deepStrictEqual(data.session.getState().selection, ['pl-a', 'pl-b']);
            data.three.emitSelection('pl-a', { metaKey: true });
            assert.deepStrictEqual(data.session.getState().selection, ['pl-b']);
            data.three.emitSelection('pl-a', {});
            assert.deepStrictEqual(data.session.getState().selection, ['pl-a']);
            data.workspace.destroy();
        });

    await check('Plan and 3D segmented modes switch without framing scene state',
        async () => {
            const data = fixture();
            assert.strictEqual(data.workspace.getState().viewMode, 'plan');
            data.workspace.threeTab.dispatch('click');
            assert.strictEqual(data.workspace.getState().viewMode, '3d');
            assert.strictEqual(data.workspace.planView.hidden, true);
            assert.strictEqual(data.workspace.threeView.hidden, false);
            assert.strictEqual(data.three.invalidations, 1);
            data.workspace.planTab.dispatch('click');
            assert.strictEqual(data.workspace.getState().viewMode, 'plan');
            const noThree = fixture({ noThree: true });
            noThree.workspace.threeTab.dispatch('click');
            assert.strictEqual(noThree.workspace.getState().viewMode, 'plan');
            assert.strictEqual(noThree.workspace.threeTab.disabled, true);
            data.workspace.destroy();
            noThree.workspace.destroy();
        });

    await check('motion evidence loads the same package in Plan and 3D without editing',
        async () => {
            const calls = [];
            const packageId = 'fmp-' + 'a'.repeat(64);
            const motionPayload = {
                prototypeMode: true,
                prototypeLabel: 'Prototype fixture on reference factory',
                package: {
                    packageId,
                    qualification: 'revision-bound fixture evidence',
                    movement: {
                        outcome: 'accepted',
                        totalDistanceMeters: 20,
                        estimatedTravelSeconds: 10,
                        clearance: {
                            sampleSpacingMeters: 0.1,
                            samples: [{
                                distanceMeters: 0,
                                clearanceMeters: 1.25,
                            }],
                        },
                    },
                },
                facilityMotionEnvelope: {},
                vehicleProfile: {},
            };
            const motionTransport = {
                async createMotionPackage(value) {
                    calls.push(['create', clone(value)]);
                    return {
                        packageId,
                        layoutRevision: 'rev-motion',
                        summary: {
                            packageId,
                            outcome: 'accepted',
                            routeId: 'rt-main',
                            distanceMeters: 20,
                            plannerDurationEstimateSeconds: 10,
                            sampleSpacingMeters: 0.1,
                            qualification: 'revision-bound fixture evidence',
                        },
                    };
                },
                async getMotionPackage(value) {
                    calls.push(['get', clone(value)]);
                    return clone(motionPayload);
                },
            };
            const data = fixture({ motionTransport });
            const before = data.session.getState();
            const summary = await data.workspace.startMotionPlayback({
                routeId: 'rt-main',
                vehicleProfileRef: {
                    vehicleProfileId: 'profile-forklift',
                    vehicleProfileRevision: 'b'.repeat(64),
                },
                travelDirection: 'forward',
            });
            assert.strictEqual(summary.outcome, 'accepted');
            assert.deepStrictEqual(calls[0][1], {
                baseRevision: 'rev-1',
                operations: [],
                request: {
                    routeId: 'rt-main',
                    vehicleProfileRef: {
                        vehicleProfileId: 'profile-forklift',
                        vehicleProfileRevision: 'b'.repeat(64),
                    },
                    travelDirection: 'forward',
                },
            });
            assert.deepStrictEqual(calls[1][1], {
                packageId,
                activeRevision: 'rev-motion',
            });
            assert.deepStrictEqual(
                data.top.motionPresentations[0],
                motionPayload
            );
            assert.strictEqual(data.three.motionState.packageId, packageId);
            assert.strictEqual(
                data.workspace.getState().motion.packageId,
                packageId
            );
            assert.strictEqual(data.workspace.motionPanel.hidden, false);
            assert.strictEqual(
                data.workspace.motionTitle.textContent,
                'Motion playback - prototype fixture'
            );
            assert.ok(data.workspace.motionEvidence.textContent.includes(
                'Prototype fixture on reference factory'
            ));
            const after = data.session.getState();
            assert.deepStrictEqual(after.layout, before.layout);
            assert.deepStrictEqual(after.operations, before.operations);
            assert.strictEqual(after.dirty, false);
            data.workspace.clearMotionPlayback('test_complete');
            assert.strictEqual(data.top.motionClearCount, 1);
            assert.strictEqual(data.workspace.motionPanel.hidden, true);
            data.workspace.destroy();
        });

    await check('navigation activity plans existing programs and stays read only',
        async () => {
            const calls = [];
            const scenarioPayload = {
                scenario: {
                    scenarioId: 'fas-nav-one',
                    label: 'Navigation activity',
                    prototypeMode: true,
                    cycleDurationSeconds: 12,
                    qualification: 'deterministic navigation presentation',
                    actors: [{
                        actorId: 'actor-nav-one',
                        actorType: 'operator',
                        label: 'Operator One',
                    }],
                },
                actorPayloads: {},
                navigationPresentation: {},
            };
            const motionTransport = {
                async compileNavigationSnapshot(value) {
                    calls.push(['compile', clone(value)]);
                    return {
                        summary: { navigationPackageId: 'navpkg-one' },
                    };
                },
                async planActorJourney(value) {
                    calls.push(['plan', clone(value)]);
                    return {
                        summary: {
                            journeySolutionId: 'njs-one',
                            outcome: 'accepted',
                        },
                    };
                },
                async buildNavigationActivityScenario(value) {
                    calls.push(['build', clone(value)]);
                    return {
                        scenarioId: 'fas-nav-one',
                        layoutRevision: 'rev-1',
                        summary: {
                            actorCount: 1,
                            qualification: 'deterministic navigation presentation',
                        },
                    };
                },
                async getActivityScenario(value) {
                    calls.push(['get', clone(value)]);
                    return clone(scenarioPayload);
                },
            };
            const data = fixture({ motionTransport });
            const before = data.session.getState();
            const summary = await data.workspace.startNavigationActivityPlayback({
                movementProgramIds: ['nmp-one'],
                prototypeMode: true,
                scenarioLabel: 'Navigation activity',
            });
            assert.strictEqual(summary.scenarioId, 'fas-nav-one');
            assert.deepStrictEqual(summary.journeySolutionIds, ['njs-one']);
            assert.strictEqual(summary.plannedJourneyCount, 1);
            assert.strictEqual(calls.length, 4);
            assert.strictEqual(calls[0][1].request.movementProgramId, 'nmp-one');
            assert.strictEqual(calls[1][1].request.navigationPackageId, 'navpkg-one');
            assert.deepStrictEqual(
                calls[2][1].request.journeySolutionIds,
                ['njs-one']
            );
            assert.deepStrictEqual(
                data.top.activityPresentations[0],
                scenarioPayload
            );
            assert.strictEqual(data.three.activityState.scenarioId, 'fas-nav-one');
            assert.strictEqual(data.workspace.motionPanel.hidden, false);
            assert.deepStrictEqual(data.session.getState().layout, before.layout);
            assert.deepStrictEqual(data.session.getState().operations, before.operations);
            assert.strictEqual(data.session.getState().dirty, false);
            data.workspace.destroy();
        });

    await check('saved movement choices preserve complete groups and never truncate', async () => {
        const actors = Array.from({length: 65}, (_, i) => ({placementId: 'p' + i, metadata: {instanceLabel: 'Person ' + i}}));
        const programs = actors.map((p, i) => ({movementProgramId: 'nmp-' + i, actorPlacementId: p.placementId}));
        const context = {state: {selection: ['p1'], layout: {placements: actors, extensions: {
            facilityNavigation: {movementPrograms: programs},
            facilityProcessPresentation: {schemaVersion: 1, groups: [
                null, 'invalid metadata',
                {label: 'Good group', movementProgramIds: ['nmp-0', 'nmp-1']},
                {label: 'Too many', movementProgramIds: programs.map(p => p.movementProgramId)},
                {label: 'Missing', movementProgramIds: ['nmp-missing']},
                {label: 'Duplicate', movementProgramIds: ['nmp-0', 'nmp-0']},
            ]},
        }}}};
        const choices = workspaceModule.Workspace.prototype.savedMovementChoices.call(context);
        assert.deepStrictEqual(choices[0], {label: 'Selected actors', movementProgramIds: ['nmp-1']});
        assert.deepStrictEqual(choices[1], {label: 'Good group', movementProgramIds: ['nmp-0', 'nmp-1']});
        assert.strictEqual(choices.length, 67);
        assert(!choices.some(c => ['Too many', 'Missing', 'Duplicate'].includes(c.label)));
        assert(!choices.some(c => c.label.startsWith('All saved movement')));
    });

    for (const cancelled of [false, true]) {
    await check('all saved movement defaults to all and respects cancellation: ' + cancelled, async () => {
        const data = fixture();
        const w = data.workspace;
        const actors = Array.from({length:40}, (_,i) => ({placementId:'p'+i}));
        const ids = actors.map((p,i) => 'nmp-'+i);
        w.state.layout = {placements:actors, extensions:{facilityNavigation:{movementPrograms:
            actors.map((p,i) => ({movementProgramId:ids[i],actorPlacementId:p.placementId}))}}};
        let finish, started=0, request;
        w.startNavigationActivityPlayback = input => { request=input; return new Promise(resolve => {finish=resolve;}); };
        w.threeAdapter.activity.play = () => { started++; };
        assert.strictEqual(w.savedMovementChoices()[0].label,'All saved movement (40 actors)');
        assert.strictEqual(w.openSavedMovementDialog(),true);
        const play = w.savedMovementDialog.querySelector('[data-saved-movement-prepare]');
        assert.strictEqual(play.textContent,'Play movement');
        play.dispatch('click');
        assert.deepStrictEqual(request.movementProgramIds,ids);
        assert.strictEqual(started,0);
        if (cancelled) w.savedMovementDialog.dispatch('keydown', {key:'Escape'});
        finish({}); await new Promise(resolve => setImmediate(resolve));
        assert.strictEqual(started,cancelled ? 0 : 1);
        assert.strictEqual(w.savedMovementDialog,null);
        w.destroy();
    });
    }

    await check('saved movement publishes enabled state to the external ribbon', async () => {
        const data = fixture({externalCommandSurface: true});
        const w = data.workspace;
        assert.strictEqual(w.getCommandStates()['saved-movement'].disabled, true);
        const actor = w.state.layout.placements[0];
        w.state.layout.extensions = {facilityNavigation: {movementPrograms: [
            {movementProgramId: 'nmp-saved', actorPlacementId: actor.placementId},
        ]}};
        w._renderToolbarState();
        assert.strictEqual(w.getCommandStates()['saved-movement'].disabled, false);
        w.constructionPreview = {proposal: {}};
        w._renderToolbarState();
        assert.strictEqual(w.getCommandStates()['saved-movement'].disabled, true);
        assert.strictEqual(w.openSavedMovementDialog(), false);
        w.constructionPreview = null;
        w.capabilities.navigationMultiActor = false;
        w._renderToolbarState();
        assert.strictEqual(w.getCommandStates()['saved-movement'].disabled, true);
        w.destroy();
    });

    for (const outcome of ['loaded', 'refused', 'cancelled']) {
        await check('saved movement restores ribbon availability after ' + outcome, async () => {
            const abort = new AbortController();
            let data;
            const motionTransport = {
                async compileNavigationSnapshot() {},
                async planActorJourney() {},
                async buildNavigationActivityScenario() {
                    const w = data.workspace;
                    assert.strictEqual(w.activityRequestPending, true);
                    // Camera/selection updates can publish command state during preparation.
                    w._renderToolbarState();
                    assert.strictEqual(w.getCommandStates()['saved-movement'].disabled, true);
                    if (outcome === 'refused') throw new Error('Journey refused');
                    if (outcome === 'cancelled') abort.abort();
                    return {scenarioId: 'fas-nav-one', layoutRevision: 'rev-1'};
                },
                async getActivityScenario() {
                    return {scenario: {scenarioId: 'fas-nav-one', label: 'Saved movement',
                        prototypeMode: true, cycleDurationSeconds: 12, actors: []},
                        actorPayloads: {}, navigationPresentation: {}};
                },
            };
            data = fixture({externalCommandSurface: true, motionTransport});
            const w = data.workspace;
            w.state.layout.extensions = {facilityNavigation: {movementPrograms: [
                {movementProgramId: 'nmp-one', actorPlacementId: w.state.layout.placements[0].placementId},
            ]}};
            w._renderToolbarState();
            const pending = w.startNavigationActivityPlayback({
                journeySolutionIds: ['njs-one'], prototypeMode: true, signal: abort.signal,
            });
            if (outcome === 'loaded') await pending;
            else await assert.rejects(pending, outcome === 'refused' ? /Journey refused/ : /cancelled/);
            assert.strictEqual(w.activityRequestPending, false);
            assert.strictEqual(w.getCommandStates()['saved-movement'].disabled, false);
            assert.strictEqual(w.openSavedMovementDialog(), true);
            w.destroy();
        });
    }

    for (const reason of ['abort-before', 'abort-after-compile', 'stale-after-compile', 'destroy-after-compile']) {
        await check('saved movement rejects ' + reason + ' before installing a result', async () => {
            const abort = new AbortController();
            let compiled = 0, planned = 0;
            let data;
            const transport = {
                async compileNavigationSnapshot() {
                    compiled += 1;
                    if (reason === 'abort-after-compile') abort.abort();
                    if (reason === 'stale-after-compile') data.workspace.session.getState = () => ({baseRevision: 'other', layout: {}, operations: []});
                    if (reason === 'destroy-after-compile') data.workspace.destroyed = true;
                    return {summary: {navigationPackageId: 'navpkg-one'}};
                },
                async planActorJourney() { planned += 1; },
                async buildNavigationActivityScenario() { throw Error('Must not build'); },
                async getActivityScenario() { throw Error('Must not fetch'); },
            };
            data = fixture({motionTransport: transport});
            if (reason === 'abort-before') abort.abort();
            await assert.rejects(data.workspace.startNavigationActivityPlayback({
                movementProgramIds: ['nmp-one'], prototypeMode: true, signal: abort.signal,
            }), error => error.code === (reason.startsWith('stale')
                ? 'facility_navigation_activity_stale' : 'facility_navigation_activity_cancelled'));
            assert.strictEqual(compiled, reason === 'abort-before' ? 0 : 1);
            assert.strictEqual(planned, 0);
            assert.strictEqual(data.top.activityPresentations.length, 0);
            assert.strictEqual(data.workspace.activityRequestPending, false);
            data.workspace.destroyed = false;
            data.workspace.destroy();
        });
    }

    await check('navigation activity rollout flag fails closed before transport',
        async () => {
            let called = false;
            const data = fixture({
                capabilities: { navigationMultiActor: false },
                motionTransport: {
                    async compileNavigationSnapshot() {
                        called = true;
                    },
                    async planActorJourney() {},
                    async buildNavigationActivityScenario() {},
                    async getActivityScenario() {},
                },
            });
            await assert.rejects(
                data.workspace.startNavigationActivityPlayback({
                    movementProgramIds: ['nmp-one'],
                    prototypeMode: true,
                }),
                error => error && error.code === 'facility_feature_disabled'
            );
            assert.strictEqual(called, false);
            data.workspace.destroy();
        });

    await check('manual path validates before one unsaved navigation gesture',
        async () => {
            const validationCalls = [];
            let accepted = false;
            const motionTransport = {
                async validateManualNavigationPath(value) {
                    validationCalls.push(clone(value));
                    return accepted ? {
                        valid: true,
                        invalidSegmentIndexes: [],
                        findings: [],
                        validationFingerprint: 'f'.repeat(64),
                    } : {
                        valid: false,
                        invalidSegmentIndexes: [0],
                        findings: [{
                            code: 'facility_navigation_manual_segment_blocked',
                            message: 'The first segment intersects a machine.',
                        }],
                        validationFingerprint: 'e'.repeat(64),
                    };
                },
            };
            const data = fixture({ motionTransport });
            const baseRevision = 'd'.repeat(64);
            data.session.state.baseRevision = baseRevision;
            data.session.select('pl-b');
            assert.strictEqual(data.workspace.openNavigationDialog(), true);
            Object.assign(data.workspace.navigationState, {
                actorProfileId: 'vehicle-profile-forklift',
                actorProfileRevision: 'a'.repeat(64),
                points: [{ x: 5, z: 2 }, { x: 10, z: 2 }],
                loopMode: 'one_way',
                direction: 'forward',
                constraintMode: 'complete_override',
            });

            assert.strictEqual(
                await data.workspace._applyNavigationPath(),
                false
            );
            assert.strictEqual(
                data.workspace.navigationState.validationStatus,
                'invalid'
            );
            assert.deepStrictEqual(
                data.workspace.navigationState.validation
                    .invalidSegmentIndexes,
                [0]
            );
            assert.strictEqual(
                data.session.calls.some(call => (
                    call[0] === 'setFacilityNavigation'
                )),
                false
            );

            accepted = true;
            assert.strictEqual(
                await data.workspace._applyNavigationPath(),
                true
            );
            assert.strictEqual(
                data.workspace.navigationState.validationStatus,
                'validated'
            );
            const authored = data.session.calls.filter(call => (
                call[0] === 'setFacilityNavigation'
            ));
            assert.strictEqual(authored.length, 1);
            assert.strictEqual(
                authored[0][1].manualPathConstraints[0].reviewStatus,
                'pending'
            );
            assert.strictEqual(validationCalls.length, 2);
            assert.strictEqual(validationCalls[1].baseRevision, baseRevision);
            assert.deepStrictEqual(validationCalls[1].operations, []);
            assert.strictEqual(
                validationCalls[1].request.prototypeMode,
                false
            );
            assert.deepStrictEqual(
                validationCalls[1].request.actorProfileRef,
                {
                    profileKind: 'vehicle',
                    profileId: 'vehicle-profile-forklift',
                    profileRevision: 'a'.repeat(64),
                }
            );
            data.workspace.destroy();
        });

    await check('Plan and 3D tabs support manual-activation arrow navigation',
        async () => {
            const data = fixture();
            data.workspace.planTab.focus();
            const right = data.workspace.planTab.dispatch('keydown', {
                key: 'ArrowRight',
            });
            assert.strictEqual(right.defaultPrevented, true);
            assert.strictEqual(
                data.workspace.planTab.ownerDocument.activeElement,
                data.workspace.threeTab
            );
            assert.strictEqual(data.workspace.getState().viewMode, 'plan');
            data.workspace.threeTab.dispatch('click');
            assert.strictEqual(data.workspace.getState().viewMode, '3d');
            data.workspace.threeTab.dispatch('keydown', { key: 'ArrowLeft' });
            assert.strictEqual(
                data.workspace.planTab.ownerDocument.activeElement,
                data.workspace.planTab
            );
            data.workspace.planTab.dispatch('keydown', { key: 'End' });
            assert.strictEqual(
                data.workspace.planTab.ownerDocument.activeElement,
                data.workspace.threeTab
            );
            data.workspace.threeTab.dispatch('keydown', { key: 'Home' });
            assert.strictEqual(
                data.workspace.planTab.ownerDocument.activeElement,
                data.workspace.planTab
            );
            const noThree = fixture({ noThree: true });
            noThree.workspace.planTab.focus();
            const disabled = noThree.workspace.planTab.dispatch('keydown', {
                key: 'ArrowRight',
            });
            assert.strictEqual(disabled.defaultPrevented, false);
            assert.strictEqual(
                noThree.workspace.planTab.ownerDocument.activeElement,
                noThree.workspace.planTab
            );
            data.workspace.destroy();
            noThree.workspace.destroy();
        });

    await check('placement transform fields and zone dimensions delegate authoritative edits',
        async () => {
            const data = fixture();
            data.session.select('pl-a');
            const xInput = data.workspace.propertiesBody.querySelector(
                '[data-property="x"]'
            );
            xInput.value = '3.5';
            xInput.dispatch('change');
            await data.workspace.whenIdle();
            assert.deepStrictEqual(
                data.session.calls.filter(call => call[0] === 'moveSelected').pop()[1],
                { x: 2.5, y: 0, z: 0 }
            );
            const rotation = data.workspace.propertiesBody.querySelector(
                '[data-property="rotation"]'
            );
            rotation.value = '90';
            rotation.dispatch('change');
            await data.workspace.whenIdle();
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'rotateSelected90').pop()[1],
                1
            );
            data.session.select('zn-a');
            const width = data.workspace.propertiesBody.querySelector(
                '[data-property="width"]'
            );
            const depth = data.workspace.propertiesBody.querySelector(
                '[data-property="depth"]'
            );
            width.value = '8';
            depth.value = '6';
            width.dispatch('change');
            await data.workspace.whenIdle();
            const zoneCall = data.session.calls.filter(
                call => call[0] === 'editZoneDimensions'
            ).pop();
            assert.deepStrictEqual(zoneCall.slice(1), ['zn-a', { width: 8, depth: 6 }]);
            const label = data.workspace.propertiesBody.querySelector(
                '[data-property="label"]'
            );
            label.value = 'Machine Cell';
            label.dispatch('change');
            await data.workspace.whenIdle();
            assert.deepStrictEqual(
                data.session.calls.filter(
                    call => call[0] === 'editZoneLabel'
                ).pop(),
                ['editZoneLabel', 'zn-a', 'Machine Cell']
            );
            const purpose = data.workspace.propertiesBody.querySelector(
                '[data-property="zoneType"]'
            );
            assert.ok(purpose);
            purpose.value = 'service';
            purpose.dispatch('change');
            await data.workspace.whenIdle();
            assert.deepStrictEqual(
                data.session.calls.filter(
                    call => call[0] === 'editZoneType'
                ).pop(),
                ['editZoneType', 'zn-a', 'service']
            );
            data.workspace.destroy();
        });

    await check('keyboard shortcuts are accessible and ignore active form fields',
        async () => {
            const data = fixture();
            data.session.select('pl-a');
            data.root.dispatch('keydown', { key: 'r', target: data.root });
            data.root.dispatch('keydown', { key: 'l', target: data.root });
            data.root.dispatch('keydown', {
                key: 'z',
                ctrlKey: true,
                target: data.root,
            });
            data.root.dispatch('keydown', {
                key: 'y',
                ctrlKey: true,
                target: data.root,
            });
            data.root.dispatch('keydown', { key: 'f', target: data.root });
            data.root.dispatch('keydown', {
                key: 'F',
                shiftKey: true,
                target: data.root,
            });
            data.root.dispatch('keydown', { key: 't', target: data.root });
            await data.workspace.whenIdle();
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'rotateSelected90').length,
                1
            );
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'lockSelected').length,
                1
            );
            assert.strictEqual(data.controller.fitCount, 1);
            assert.strictEqual(data.controller.fitLayoutCount, 1);
            assert.strictEqual(data.controller.topViewCount, 1);
            const input = data.documentRef.createElement('input');
            data.root.dispatch('keydown', { key: 'Delete', target: input });
            await data.workspace.whenIdle();
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'deleteSelected').length,
                0
            );
            data.workspace.destroy();
        });

    await check('asset browser batches quantities into one placement gesture',
        async () => {
            const data = fixture({
                keyboardPlacementPoint: { x: 14.24, y: 0, z: 10.26 },
            });
            data.session.state.baseLayout.zones = [];
            data.session.state.layout.zones = [];
            data.session._notify();
            toolbarButton(data, 'assets').dispatch('click');
            assert.strictEqual(data.workspace.assetBrowser.hidden, false);
            assert.strictEqual(
                data.workspace.shell.getAttribute('aria-hidden'),
                'true'
            );
            assert.strictEqual(toolbarButton(data, 'delete').disabled, true);
            assetAction(data, 'asset-rack', 'toggle').dispatch('click');
            assetAction(data, 'asset-rack', 'increment').dispatch('click');
            assetAction(data, 'asset-machine', 'toggle').dispatch('click');
            assert.ok(data.workspace.assetBrowserSelectionStatus.textContent.includes(
                '3 total items'
            ));
            data.workspace.assetBrowserAdd.dispatch('click');
            await data.workspace.whenIdle();
            await Promise.resolve();
            const calls = data.session.calls.filter(
                call => call[0] === 'placeAssets'
            );
            assert.strictEqual(calls.length, 1);
            assert.strictEqual(calls[0][1].length, 3);
            assert.strictEqual(
                new Set(calls[0][1].map(
                    request => JSON.stringify(request.worldPosition)
                )).size,
                3
            );
            const state = data.session.getState();
            assert.strictEqual(state.selection.length, 3);
            assert.deepStrictEqual(state.history[state.history.length - 1], {
                label: 'Add assets',
                operationCount: 3,
                applied: true,
            });
            assert.strictEqual(data.workspace.assetBrowser.hidden, true);
            assert.strictEqual(
                data.workspace.getState().assetBrowser.selectionOrder.length,
                0
            );
            assert.strictEqual(toolbarButton(data, 'delete').disabled, false);
            data.workspace.destroy();
        });

    await check('asset browser uses the active 3D floor point and reports submission progress',
        async () => {
            const data = fixture();
            data.session.state.baseLayout.zones = [];
            data.session.state.layout.zones = [];
            data.session._notify();
            let projectedInput = null;
            data.three.worldPointOnFloor = input => {
                projectedInput = clone(input);
                return { x: 18.24, y: 0, z: 11.26 };
            };
            data.workspace._setViewMode('3d');
            toolbarButton(data, 'assets').dispatch('click');
            assetAction(data, 'asset-machine', 'toggle').dispatch('click');
            data.workspace.assetBrowserAdd.dispatch('click');

            assert.strictEqual(data.workspace.assetBrowserAdd.disabled, true);
            assert.strictEqual(
                data.workspace.assetBrowserAdd.textContent,
                'Adding...'
            );
            assert.strictEqual(
                data.workspace.assetBrowserAdd.getAttribute('aria-busy'),
                'true'
            );
            assert.ok(data.workspace.assetBrowserSelectionStatus.textContent
                .includes('Adding 1 asset'));

            await data.workspace.whenIdle();
            await Promise.resolve();
            const call = data.session.calls.find(item => item[0] === 'placeAssets');
            assert(call);
            assert.deepStrictEqual(projectedInput, {
                clientX: 450,
                clientY: 300,
            });
            assert.deepStrictEqual(call[1][0].worldPosition, {
                x: 18,
                y: 0,
                z: 11.5,
            });
            assert.strictEqual(data.workspace.assetBrowser.hidden, true);
            assert.strictEqual(data.workspace.assetBrowserSubmitting, false);
            assert.strictEqual(data.workspace.assetBrowserAdd.textContent,
                'Add to Layout');
            assert.strictEqual(data.controller.fitCount, 1);
            data.workspace.destroy();
        });

    await check('asset browser cancel is pure and Escape preserves a pending selection',
        async () => {
            const data = fixture();
            const before = JSON.stringify(data.session.getState().layout);
            toolbarButton(data, 'assets').dispatch('click');
            assetAction(data, 'asset-forklift', 'toggle').dispatch('click');
            data.workspace.assetBrowser.dispatch('keydown', {
                key: 'Escape',
                target: data.workspace.assetBrowser,
            });
            assert.strictEqual(data.workspace.assetBrowser.hidden, true);
            assert.strictEqual(
                data.workspace.getState().assetBrowser.selected['asset-forklift'],
                1
            );
            toolbarButton(data, 'assets').dispatch('click');
            data.workspace.assetBrowserCancel.dispatch('click');
            assert.strictEqual(data.workspace.assetBrowser.hidden, true);
            assert.strictEqual(
                Object.keys(data.workspace.getState().assetBrowser.selected).length,
                0
            );
            assert.strictEqual(JSON.stringify(data.session.getState().layout), before);
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'placeAssets').length,
                0
            );
            data.workspace.destroy();
        });

    await check('motion controls can dock outside the layout viewport',
        async () => {
            const css = fs.readFileSync(path.join(ROOT, 'static', 'facility_layout_workspace.css'), 'utf8');
            const docked = css.match(/\.ip-flw-motion-panel\[data-motion-docked="true"\] \{([^}]+)\}/)[1];
            assert.match(docked, /--ip-flw-panel-alt:\s*var\(--bg-input,/);
            assert.doesNotMatch(docked, /--bg-secondary/);
            const data = fixture({ externalMotionPanel: true });
            assert.strictEqual(
                data.workspace.motionPanel.parentNode,
                data.motionPanelHost
            );
            assert.strictEqual(
                data.workspace.motionPanel.getAttribute('data-motion-docked'),
                'true'
            );
            assert.strictEqual(
                data.workspace.viewportStack.querySelector(
                    '.ip-flw-motion-panel'
                ),
                null
            );
            data.workspace.destroy();
            assert.strictEqual(data.motionPanelHost.children.length, 0);
        });

    await check('a brief correction cancels and cannot be overwritten by an older preview',
        async () => {
            let resolveContinuation;
            const cancelled = [];
            const designTransport = {
                continueDesignPreview() {
                    return new Promise(resolve => {
                        resolveContinuation = resolve;
                    });
                },
                cancelDesignPreview(payload) {
                    cancelled.push(clone(payload));
                    return Promise.resolve({ status: 'cancelled' });
                },
                updateDesignBrief() {
                    return Promise.resolve({
                        brief: {
                            briefId: 'brief-one',
                            briefRevision: 'b'.repeat(64),
                            semanticBody: {
                                objective: { summary: 'Reduce loaded travel' },
                                hardConstraints: [],
                                preferences: [],
                            },
                        },
                    });
                },
            };
            const data = fixture({ designTransport });
            data.workspace.designState.brief = {
                briefId: 'brief-one',
                briefRevision: 'a'.repeat(64),
                semanticBody: {
                    objective: { summary: 'Reduce loaded travel' },
                    hardConstraints: [],
                    preferences: [],
                },
            };
            data.workspace.designState.run = {
                runId: 'run-old',
                runRevision: 'c'.repeat(64),
                briefRevision: 'a'.repeat(64),
            };

            const oldPreview = data.workspace.runDesignPreview({
                run_id: 'run-old',
            });
            await Promise.resolve();
            const corrected = await data.workspace.updateDesignBriefFromIntent({
                schema_version: 'facility-design-intent-v1',
                operation: 'add_geometry_locks',
                target_labels: ['Main Boulevard'],
            });
            assert.strictEqual(corrected.brief.briefRevision, 'b'.repeat(64));
            assert.deepStrictEqual(cancelled, [{ runId: 'run-old' }]);

            resolveContinuation({
                status: 'completed',
                continuationRequired: false,
                proposalRefs: [],
            });
            await assert.rejects(oldPreview, error => (
                error.code === 'facility_design_preview_superseded'
            ));
            assert.strictEqual(
                data.workspace.designState.brief.briefRevision,
                'b'.repeat(64)
            );
            assert.strictEqual(data.workspace.designState.run, null);
            assert.deepStrictEqual(data.workspace.designState.proposals, []);
            assert.strictEqual(data.workspace.designState.error, null);
            assert.strictEqual(data.workspace.designState.status, 'brief_ready');
            data.workspace.destroy();
        });

    await check('preview-only design capability compares but exposes no Apply command',
        async () => {
            const designTransport = {
                startDesignPreview() {
                    return Promise.resolve({
                        runId: 'run-preview-only',
                        runRevision: 'c'.repeat(64),
                        briefRevision: 'a'.repeat(64),
                        status: 'preview_ready',
                        continuationRequired: false,
                        proposalRefs: [{
                            artifactId: 'proposal-preview-only',
                            artifactRevision: 'b'.repeat(64),
                        }],
                    });
                },
                inspectDesignProposal() {
                    return Promise.resolve({
                        proposal: {
                            proposalId: 'proposal-preview-only',
                            proposalRevision: 'b'.repeat(64),
                            resultLayoutRevision: 'd'.repeat(64),
                            diffHash: 'e'.repeat(64),
                            classification: { preferred: true },
                        },
                        evaluation: {
                            metrics: [{
                                metricId: 'loadedRouteDistanceMeters',
                                value: 24,
                            }],
                        },
                    });
                },
            };
            const data = fixture({
                designTransport,
                capabilities: {
                    designBrief: true,
                    designLoopPreview: true,
                    designLoopApply: true,
                    agentWrite: false,
                },
            });
            data.workspace.designState.active = true;
            data.workspace.designState.brief = {
                briefId: 'brief-preview-only',
                briefRevision: 'a'.repeat(64),
                semanticBody: {
                    objective: { targetRefs: [] },
                    hardConstraints: [],
                    preferences: [],
                },
            };

            const compared = await data.workspace.runDesignPreview({});

            assert.strictEqual(compared.proposals.length, 1);
            assert.strictEqual(
                data.root.querySelector('.ip-flw-design-apply'),
                null
            );
            await assert.rejects(
                data.workspace.applySelectedDesignProposal(),
                error => error.code === 'facility_feature_disabled'
            );
            data.workspace.destroy();
        });

    await check('design preview follows bounded continuation responses to terminal state',
        async () => {
            let continuationCalls = 0;
            const designTransport = {
                startDesignPreview() {
                    return Promise.resolve({
                        runId: 'run-continuation',
                        runRevision: 'c'.repeat(64),
                        briefRevision: 'a'.repeat(64),
                        status: 'active',
                        continuationRequired: true,
                        proposalRefs: [],
                    });
                },
                continueDesignPreview() {
                    continuationCalls += 1;
                    if (continuationCalls === 1) {
                        return Promise.resolve({
                            runId: 'run-continuation',
                            status: 'active',
                            continuationRequired: true,
                            proposalRefs: [],
                        });
                    }
                    return Promise.resolve({
                        runId: 'run-continuation',
                        status: 'preview_ready',
                        continuationRequired: false,
                        proposalRefs: [{
                            artifactId: 'proposal-continuation',
                            artifactRevision: 'b'.repeat(64),
                        }],
                    });
                },
                inspectDesignProposal() {
                    return Promise.resolve({
                        proposal: {
                            proposalId: 'proposal-continuation',
                            proposalRevision: 'b'.repeat(64),
                            resultLayoutRevision: 'd'.repeat(64),
                            diffHash: 'e'.repeat(64),
                            classification: { preferred: true },
                        },
                        evaluation: { metrics: [] },
                    });
                },
            };
            const data = fixture({ designTransport });
            data.workspace.designState.active = true;
            data.workspace.designState.brief = {
                briefId: 'brief-continuation',
                briefRevision: 'a'.repeat(64),
                semanticBody: {
                    objective: { targetRefs: [] },
                    hardConstraints: [],
                    preferences: [],
                },
            };

            const result = await data.workspace.runDesignPreview({});

            assert.strictEqual(continuationCalls, 2);
            assert.strictEqual(result.summary.status, 'preview_ready');
            assert.strictEqual(result.proposals.length, 1);
            data.workspace.destroy();
        });

    await check('design comparison exposes its exact source and one shared Plan and 3D overlay',
        async () => {
            const candidateLayout = layout();
            candidateLayout.placements[0].transform.position.x = 3;
            const designTransport = {
                startDesignPreview() {
                    return Promise.resolve({
                        runId: 'run-overlay',
                        runRevision: 'c'.repeat(64),
                        briefRevision: 'a'.repeat(64),
                        status: 'preview_ready',
                        continuationRequired: false,
                        objectiveEndpoints: {
                            source: {
                                entityKind: 'placement',
                                entityId: 'pl-a',
                                connectorId: 'output',
                            },
                            target: {
                                entityKind: 'placement',
                                entityId: 'pl-b',
                                connectorId: 'input',
                            },
                        },
                        proposalRefs: [{
                            artifactId: 'proposal-overlay',
                            artifactRevision: 'b'.repeat(64),
                        }],
                        baseline: {
                            baselineId: 'baseline-overlay',
                            baselineRevision: 'f'.repeat(64),
                            layoutRevision: 'd'.repeat(64),
                            feasible: true,
                            metrics: [{
                                metricId: 'loadedRouteDistanceMeters',
                                value: 40,
                            }],
                        },
                    });
                },
                inspectDesignProposal() {
                    return Promise.resolve({
                        proposal: {
                            proposalId: 'proposal-overlay',
                            proposalRevision: 'b'.repeat(64),
                            resultLayoutRevision: 'd'.repeat(64),
                            diffHash: 'e'.repeat(64),
                            classification: { preferred: true },
                        },
                        evaluation: {
                            metrics: [{
                                metricId: 'loadedRouteDistanceMeters',
                                value: 24,
                            }],
                        },
                        candidate: { candidateLayout },
                    });
                },
            };
            const data = fixture({ designTransport });
            data.workspace.designState.active = true;
            data.workspace.designState.brief = {
                briefId: 'brief-overlay',
                briefRevision: 'a'.repeat(64),
                semanticBody: {
                    baseStateRef: {
                        baseId: 'base-overlay',
                        baseRevision: '1'.repeat(64),
                        baseKind: 'editor_draft',
                        layoutId: 'fl-workspace',
                        layoutRevision: '2'.repeat(64),
                    },
                    objective: {
                        targetRefs: [
                            { entityKind: 'placement', entityId: 'pl-b' },
                            { entityKind: 'placement', entityId: 'pl-a' },
                        ],
                    },
                    hardConstraints: [{
                        status: 'active',
                        targetRefs: [{
                            entityKind: 'placement',
                            entityId: 'pl-b',
                        }],
                    }],
                    preferences: [],
                },
            };

            await data.workspace.runDesignPreview({});

            const topPreview = data.top.proposalPreviews.at(-1);
            const threePreview = data.three.proposalPreviews.at(-1);
            assert.strictEqual(topPreview.proposalId, 'proposal-overlay');
            assert.deepStrictEqual(topPreview.movedPlacementIds, ['pl-a']);
            assert.deepStrictEqual(topPreview.preservedPlacementIds, ['pl-b']);
            assert.deepStrictEqual(threePreview, topPreview);
            assert.strictEqual(
                data.workspace.designState.proposalPreviewVisible,
                true
            );
            assert.strictEqual(
                data.workspace.designSource.children[0].textContent,
                'Unsaved editor draft'
            );
            assert.strictEqual(
                data.workspace.designObjective.children[1].textContent,
                'pl-a to pl-b'
            );
            assert.strictEqual(data.workspace.designLegend.children.length, 2);
            data.workspace.destroy();
        });

    await check('ambiguous and stale design failures name and highlight exact affected IDs',
        async () => {
            const ambiguous = new Error('Choose one exact transfer point.');
            ambiguous.code = 'facility_design_referent_ambiguous';
            ambiguous.details = {
                candidates: [
                    { entityKind: 'placement', entityId: 'pl-a' },
                    { entityKind: 'placement', entityId: 'pl-b' },
                ],
            };
            const designTransport = {
                updateDesignBrief() {
                    if (!this.returnStale) return Promise.reject(ambiguous);
                    const stale = new Error('The design brief changed.');
                    stale.code = 'facility_design_brief_revision_conflict';
                    stale.details = { currentBriefRevision: 'f'.repeat(64) };
                    return Promise.reject(stale);
                },
            };
            const data = fixture({ designTransport });
            data.workspace.designState.brief = {
                briefId: 'brief-ambiguous',
                briefRevision: 'a'.repeat(64),
                semanticBody: {
                    objective: { targetRefs: [] },
                    hardConstraints: [],
                    preferences: [],
                },
            };
            await assert.rejects(
                data.workspace.updateDesignBriefFromIntent({}),
                error => error.code === 'facility_design_referent_ambiguous'
            );
            assert.strictEqual(data.workspace.designState.attentionKind, 'ambiguous');
            assert.deepStrictEqual(
                data.session.getState().selection,
                ['pl-a', 'pl-b']
            );
            assert.strictEqual(
                data.root.getAttribute('data-design-attention'),
                'ambiguous'
            );
            assert.strictEqual(
                data.workspace.designProposalList.querySelectorAll(
                    '[data-design-attention-entity]'
                ).length,
                2
            );

            data.workspace.designState.brief = {
                briefId: 'brief-stale',
                briefRevision: 'a'.repeat(64),
                semanticBody: {
                    objective: {
                        targetRefs: [{
                            entityKind: 'placement',
                            entityId: 'pl-a',
                        }],
                    },
                    hardConstraints: [],
                    preferences: [],
                },
            };
            designTransport.returnStale = true;
            await assert.rejects(
                data.workspace.updateDesignBriefFromIntent({}),
                error => error.code === 'facility_design_brief_revision_conflict'
            );
            assert.strictEqual(data.workspace.designState.attentionKind, 'stale');
            assert.deepStrictEqual(data.session.getState().selection, ['pl-a']);
            assert.strictEqual(
                data.root.getAttribute('data-design-attention'),
                'stale'
            );
            data.workspace.destroy();
        });

    await check('construction bridge loads once, delegates explicitly and respects workspace availability', async () => {
        const originalFetch = global.fetch;
        const originalAdapter = global.InspectorProFacilityCommandAdapter;
        const contract = require('../static/contracts/facility-construction-commands-v1.json');
        const calls = [];
        let fetches = 0;
        let data;
        let disabled;
        try {
            global.fetch = async url => {
                assert.strictEqual(url, '/static/contracts/facility-construction-commands-v1.json');
                fetches++;
                return { ok: true, json: async () => contract };
            };
            global.InspectorProFacilityCommandAdapter = { createAdapter(schema, patterns, session, getCatalog) {
                assert.deepStrictEqual(schema, contract);
                assert.strictEqual(patterns, patternModule);
                assert.strictEqual(session, data.session);
                assert.deepStrictEqual(getCatalog(), data.workspace.assetCatalog);
                return { execute: async request => { calls.push(request); return { requestId: request.requestId }; } };
            } };
            data = fixture();
            const request = { requestId: 'explicit-targets', commandId: 'linear-pattern',
                expectedDraftRevision: 'revision', arguments: { seedIds: ['pl-a'] } };
            assert.deepStrictEqual(await data.workspace.executeConstructionCommand(request), { requestId: request.requestId });
            await data.workspace.executeConstructionCommand(request);
            assert.strictEqual(fetches, 1);
            assert.deepStrictEqual(calls, [request, request]);
            disabled = fixture({ capabilities: { manualAuthoring: false } });
            await assert.rejects(disabled.workspace.executeConstructionCommand(request), /unavailable/);
            data.workspace.destroy();
            await assert.rejects(data.workspace.executeConstructionCommand(request), /unavailable/);
            assert.strictEqual(fetches, 1);
        } finally {
            if (data) data.workspace.destroy();
            if (disabled) disabled.workspace.destroy();
            global.fetch = originalFetch;
            global.InspectorProFacilityCommandAdapter = originalAdapter;
        }
    });

    await check('construction preview renders candidate without editing; partial and stale results cannot apply', async () => {
        let proposal;
        let applied = 0;
        const data = fixture({capabilities: {constructionPreview: true, constructionApply: true, agentWrite: true},
            designTransport: {getConstructionPreview: async () => clone(proposal),
                approveConstructionPreview: async () => { applied++; return {}; }}});
        data.session.state.draftRevision = 'a'.repeat(64);
        data.session.state.editorGenerationId = 'frame-a';
        data.session._notify();
        const original = clone(data.session.state.layout);
        const candidate = clone(original);
        candidate.placements[0].transform.position.x += 2;
        proposal = {proposalId: 'fcp-' + 'b'.repeat(64), baseRevision: 'a'.repeat(64),
            candidateRevision: 'c'.repeat(64), commandCount: 1, candidateLayout: candidate, validationScope: 'Prototype checks'};
        await data.workspace.showConstructionPreview({...proposal, partial: true});
        assert.deepStrictEqual(data.session.state.layout, original);
        assert.strictEqual(data.workspace.lastLayoutFingerprint, JSON.stringify(candidate));
        assert.ok(data.root.querySelector('[data-construction-action="apply"]').disabled);
        await assert.rejects(data.workspace.applyConstructionPreview(), /unavailable/);
        data.workspace.dismissConstructionPreview();
        assert.strictEqual(data.workspace.lastLayoutFingerprint, JSON.stringify(original));
        await data.workspace.showConstructionPreview(proposal);
        data.session.state.editorGenerationId = 'frame-new';
        data.session._notify();
        await assert.rejects(data.workspace.applyConstructionPreview(), /editor changed/);
        assert.strictEqual(data.workspace.lastLayoutFingerprint, JSON.stringify(original));
        assert.strictEqual(applied, 0);
        data.workspace.destroy();
    });

    await check('construction preview rejects superseded asynchronous responses', async () => {
        let resolve;
        const data = fixture({capabilities: {constructionPreview: true},
            designTransport: {getConstructionPreview: () => new Promise(done => { resolve = done; })}});
        data.session.state.draftRevision = 'a'.repeat(64);
        data.session.state.editorGenerationId = 'frame-a';
        data.session._notify();
        const summary = {proposalId: 'fcp-' + 'b'.repeat(64), baseRevision: 'a'.repeat(64), candidateRevision: 'c'.repeat(64)};
        const pending = data.workspace.showConstructionPreview(summary);
        data.workspace.dismissConstructionPreview();
        resolve({...summary, candidateLayout: layout()});
        await assert.rejects(pending, /superseded/);
        assert.strictEqual(data.workspace.constructionPreview, null);
        data.workspace.destroy();
    });

    await check('generation preview shares Plan/3D, blocks edits and restores the untouched editor', async () => {
        const source = {artifactKind: 'generation-source-context', artifactId: 'b'.repeat(64), artifactRevision: 'c'.repeat(64)};
        let proposal;
        const data = fixture({capabilities: {generationPlanning: true}, designTransport: {sessionId: 'test',
            listGenerationPlanningSources: async () => ({sources: [{sourceContextRef: source, displayName: 'Reviewed', contextId: 'context'}]}),
            inspectGenerationPlanningPreview: async () => clone(proposal)}});
        data.session.state.draftRevision = 'a'.repeat(64);
        data.session.state.editorGenerationId = 'frame-a';
        data.session._notify();
        const original = clone(data.session.getState());
        const view = data.workspace.generationPlanningView;
        await view.open();
        view.select(source);
        view.begin('turn-1');
        const candidate = clone(original.layout);
        candidate.placements[0].transform.position.x += 2;
        proposal = {previewId: 'd'.repeat(64), previewRevision: 'e'.repeat(64), baseRevision: 'a'.repeat(64),
            candidateRevision: 'f'.repeat(64), ledgerRevision: '1'.repeat(64), candidateLayout: candidate,
            counts: {placements: candidate.placements.length, zones: candidate.zones.length}};
        await view.show({...proposal, workspaceId: 'planning-test', clientTurnId: 'turn-1', sourceContextRef: source});
        assert.deepStrictEqual(data.session.getState(), original);
        assert.strictEqual(data.workspace.lastLayoutFingerprint, JSON.stringify(candidate));
        data.workspace._setViewMode('3d');
        assert.strictEqual(data.workspace.lastLayoutFingerprint, JSON.stringify(candidate));
        await assert.rejects(data.workspace.executeCommand('rectangle-zone'), /Exit.*preview/);
        await assert.rejects(data.workspace.executeCommand('save'), /Exit.*preview/);
        assert.ok(!data.root.querySelector('[data-construction-action="apply"]'));
        view.close();
        assert.strictEqual(data.workspace.lastLayoutFingerprint, JSON.stringify(original.layout));
        assert.deepStrictEqual(data.session.getState(), original);
        data.workspace.destroy();
    });

    await check('brief-first planning adopts provisional context and shows only safe evidence links', async () => {
        const source = {artifactKind: 'generation-provisional-context', artifactId: 'b'.repeat(64), artifactRevision: 'c'.repeat(64)};
        let proposal;
        const data = fixture({capabilities: {generationPlanning: true}, designTransport: {sessionId: 'test',
            listGenerationPlanningSources: async () => ({sources: []}),
            inspectGenerationPlanningPreview: async () => clone(proposal)}});
        data.session.state.draftRevision = 'a'.repeat(64);
        data.session.state.editorGenerationId = 'frame-a';
        data.session._notify();
        const original = clone(data.session.getState());
        const view = data.workspace.generationPlanningView;
        await view.open();
        assert.strictEqual(view.reference().sourceContextRef, null);
        view.begin('brief-turn');
        proposal = {previewId: 'd'.repeat(64), previewRevision: 'e'.repeat(64), baseRevision: 'a'.repeat(64),
            candidateRevision: 'f'.repeat(64), ledgerRevision: '1'.repeat(64), candidateLayout: clone(original.layout),
            counts: {placements: 2, zones: 3}, planningNotes: {assumptions: ['Provisional count'], unknowns: ['Cycle time'],
                sources: [{url: 'https://maker.example/manual', title: 'Manual'}, {url: 'javascript:alert(1)', title: 'Unsafe'}]}};
        await view.show({...proposal, workspaceId: 'planning-test', clientTurnId: 'brief-turn', sourceContextRef: source});
        assert.deepStrictEqual(view.reference().sourceContextRef, source);
        const links = data.root.querySelectorAll('a');
        assert.strictEqual(links.length, 1);
        assert.strictEqual(links[0].getAttribute('href'), 'https://maker.example/manual');
        assert.strictEqual(links[0].getAttribute('rel'), 'noopener noreferrer');
        assert.deepStrictEqual(data.session.getState(), original);
        view.close();
        assert.strictEqual(view.reference(), null);
        data.workspace.destroy();
    });

    await check('generation preview rejects late responses after correction, source change and destruction', async () => {
        for (const action of ['correction', 'source', 'destroy', 'editor']) {
            const source = {artifactKind: 'generation-source-context', artifactId: 'b'.repeat(64), artifactRevision: 'c'.repeat(64)};
            let resolve;
            const data = fixture({capabilities: {generationPlanning: true}, designTransport: {sessionId: 'test',
                listGenerationPlanningSources: async () => ({sources: [{sourceContextRef: source, displayName: 'Reviewed', contextId: 'ctx'}]}),
                inspectGenerationPlanningPreview: () => new Promise(done => { resolve = done; })}});
            data.session.state.draftRevision = 'a'.repeat(64);
            data.session.state.editorGenerationId = 'frame-a';
            data.session._notify();
            const view = data.workspace.generationPlanningView;
            await view.open(); view.select(source); view.begin('turn-1');
            const summary = {previewId: 'd'.repeat(64), previewRevision: 'e'.repeat(64), baseRevision: 'a'.repeat(64),
                candidateRevision: 'f'.repeat(64), ledgerRevision: '1'.repeat(64), workspaceId: 'planning-test',
                clientTurnId: 'turn-1', sourceContextRef: source};
            const pending = view.show(summary);
            if (action === 'correction') view.begin('turn-2');
            else if (action === 'source') view.select(null);
            else if (action === 'destroy') data.workspace.destroy();
            else data.session.state.editorGenerationId = 'frame-b';
            resolve({...summary, candidateLayout: layout()});
            await assert.rejects(pending, /superseded/);
            assert.strictEqual(view.activeLayout(), null);
            data.workspace.destroy();
        }
    });

    await check('destroy removes listeners, subscription, adapters, and DOM exactly once',
        async () => {
            const baseline = FakeElement.listenerCount;
            const data = fixture();
            assert.ok(FakeElement.listenerCount > baseline);
            assert.strictEqual(
                data.root.className.split(/\s+/).filter(
                    item => item === 'ip-flw-root'
                ).length,
                1
            );
            const controller = data.controller;
            const subscriptionCount = data.session.listeners.size;
            assert.strictEqual(subscriptionCount, 1);
            assert.strictEqual(data.workspace.destroy(), true);
            assert.strictEqual(data.workspace.destroy(), false);
            assert.strictEqual(data.session.listeners.size, 0);
            assert.strictEqual(controller.disposeCount, 1);
            assert.strictEqual(data.root.children.length, 0);
            assert.strictEqual(data.root.className.includes('ip-flw-root'), false);
            assert.strictEqual(FakeElement.listenerCount, baseline);
            data.session.select('pl-a');
            assert.strictEqual(controller.disposeCount, 1);
        });

    await check('lighting coverage shows in the plan and 3D with its legend and goes when the layout changes',
        async () => {
            const data = fixture();
            const views = [];
            data.top.setLightCoverage = value => { views.push(['plan', value]); return true; };
            data.three.setLightCoverage = value => { views.push(['3d', value]); return true; };
            const values = Buffer.alloc(4);
            values.writeUInt16LE(5, 0);
            values.writeUInt16LE(65535, 2);
            const reply = { summary: { label: 'Estimate, not a lighting design. No code-compliance claims.',
                area: { label: 'the car parks and truck yards', sizeSquareMeters: 1 },
                estimatedLux: { minimum: 0.5, mean: 0.5, maximum: 0.5 }, darkSpots: { listed: [] } },
            grid: { originX: 0, originZ: 0, cellMeters: 1, cols: 2, rows: 1, encoding: 'uint16le-tenths',
                values: values.toString('base64') }, spots: [] };
            let release = null;
            data.session.lightingCoverage = () => {
                const sent = { baseRevision: data.session.state.baseRevision,
                    operations: clone(data.session.state.operations) };
                return new Promise(resolve => { release = () => resolve(Object.assign({ result: reply }, sent)); });
            };
            const textOf = node => String(node.textContent || '') + node.children.map(textOf).join('');
            const shown = data.workspace._showLightCoverage({ lot: true }, 'lot');
            release();
            const pane = await shown;
            assert.strictEqual(pane.choice, 'lot');
            assert.deepStrictEqual(views.map(view => view[0]), ['plan', '3d']);
            assert.deepStrictEqual([views[0][1].minX, views[0][1].maxX, views[0][1].maxZ], [0, 2, 1]);
            assert.strictEqual(views[1][1].parts.length, 1, 'one band; the cell outside the area is left out');
            const legend = data.workspace.lightCoverageLegend;
            assert.strictEqual(legend.hidden, false);
            assert.ok(textOf(legend).includes('Estimated lux: The car parks and truck yards'), textOf(legend));
            assert.ok(textOf(legend).includes('Estimate, not a lighting design. No code-compliance claims.'));
            assert.strictEqual(data.workspace.appearanceLibraryContext().lightCoverage.token, pane.token);
            // An unsaved edit drops it, in both views.
            data.session.state.operations = [{ op: 'rename_layout', name: 'B' }];
            data.session._notify();
            assert.deepStrictEqual(views.slice(2), [['plan', null], ['3d', null]]);
            assert.strictEqual(legend.hidden, true);
            assert.strictEqual(data.workspace.appearanceLibraryContext().lightCoverage, null);
            // A reply for a layout that changed meanwhile is not drawn.
            const stale = data.workspace._showLightCoverage({ lot: true }, 'lot');
            data.session.state.operations = [];
            data.session._notify();
            release();
            await assert.rejects(stale, /The layout changed during the estimate/);
            // Hide drops a reply still on its way.
            const dropped = data.workspace._showLightCoverage({ lot: true }, 'lot');
            assert.strictEqual(data.workspace._hideLightCoverage(), false, 'nothing on show yet');
            release();
            assert.strictEqual(await dropped, null);
            assert.strictEqual(views.length, 4, 'nothing more drawn');
            data.workspace.destroy();
        });

    await check('Sage\'s coverage check shows the same estimate for the layout it read, and the legend hides it',
        async () => {
            const data = fixture();
            const views = [];
            data.top.setLightCoverage = value => { views.push(['plan', value]); return true; };
            data.three.setLightCoverage = value => { views.push(['3d', value]); return true; };
            const values = Buffer.alloc(2);
            values.writeUInt16LE(80, 0);
            const reply = { summary: { label: 'Estimate, not a lighting design. No code-compliance claims.',
                area: { label: 'Truck Yard', sizeSquareMeters: 1 },
                estimatedLux: { minimum: 8, mean: 8, maximum: 8 }, darkSpots: { listed: [] } },
            grid: { originX: 0, originZ: 0, cellMeters: 1, cols: 1, rows: 1, encoding: 'uint16le-tenths',
                values: values.toString('base64') }, spots: [] };
            const asked = [];
            data.session.lightingCoverage = area => {
                asked.push(clone(area));
                return Promise.resolve({ baseRevision: data.session.state.baseRevision,
                    operations: clone(data.session.state.operations), result: reply });
            };
            let notified = 0;
            const stop = data.workspace.subscribeStructure(() => { notified += 1; });
            const read = { siteId: 'site-a', layoutId: 'fl-workspace', revision: 'rev-1',
                area: { zoneId: 'zn-yard', darkBelowLux: 5 } };
            // Not the layout this view holds: another revision, another layout, another site, or unsaved edits.
            for (const other of [{ revision: 'rev-0' }, { layoutId: 'fl-other' }, { siteId: 'site-b' }]) {
                assert.strictEqual(await data.workspace.showSageLightCoverage(Object.assign({}, read, other)), null);
            }
            data.session.state.dirty = true;
            data.session._notify();
            assert.strictEqual(await data.workspace.showSageLightCoverage(read), null);
            data.session.state.dirty = false;
            data.session._notify();
            assert.deepStrictEqual([asked.length, views.length], [0, 0]);
            notified = 0;
            const pane = await data.workspace.showSageLightCoverage(read);
            assert.deepStrictEqual(asked, [{ zoneId: 'zn-yard', darkBelowLux: 5 }], 'the area and level Sage used');
            assert.strictEqual(pane.choice, 'zone:zn-yard', 'the Scenes pane shows it as its own');
            assert.deepStrictEqual(views.map(view => view[0]), ['plan', '3d']);
            assert.strictEqual(data.workspace.appearanceLibraryContext().lightCoverage.token, pane.token);
            assert.ok(notified >= 1, 'the Scenes pane is told');
            const legend = data.workspace.lightCoverageLegend;
            const find = (node, test) => test(node) ? node
                : node.children.reduce((found, child) => found || find(child, test), null);
            const hide = find(legend, node => node.getAttribute && node.getAttribute('data-light-coverage') === 'hide');
            assert.ok(hide && hide.nodeName === 'BUTTON' && hide.textContent === 'Hide');
            notified = 0;
            hide.dispatch('click');
            assert.deepStrictEqual(views.slice(2), [['plan', null], ['3d', null]]);
            assert.strictEqual(legend.hidden, true);
            assert.strictEqual(data.workspace.appearanceLibraryContext().lightCoverage, null);
            assert.ok(notified >= 1, 'the Scenes pane follows');
            // A rectangle (Sage only) has no choice in the pane; the lot and a floor area do.
            const choices = [];
            for (const area of [{ rectangle: { minX: 0, minZ: 0, maxX: 2, maxZ: 2 } }, { lot: true },
                { floorAreaId: 'fs-a' }]) {
                choices.push((await data.workspace.showSageLightCoverage(Object.assign({}, read, { area }))).choice);
            }
            assert.deepStrictEqual(choices, [null, 'lot', 'floor:fs-a']);
            stop();
            data.workspace.destroy();
        });

    await check('Sage moves the 3D view: a glide in frames from plan, the roof off only while it flies or looks down '
        + 'through it, and Back returns', async () => {
            const data = fixture();
            const workspace = data.workspace;
            const frames = [];
            const cancelled = [];
            let still = false;
            data.documentRef.defaultView = {
                requestAnimationFrame(callback) { frames.push(callback); return frames.length; },
                cancelAnimationFrame(id) { cancelled.push(id); },
                matchMedia(query) { return { matches: still && query === '(prefers-reduced-motion: reduce)' }; },
            };
            const run = (from, to) => {
                const at = [];
                for (let time = from; frames.length; time += 100) {
                    frames.shift()(time);
                    at.push(time);
                    if (to !== undefined && time >= to) break;
                }
                return at;
            };
            workspace._setViewMode('plan');
            workspace.lastThreeFitFingerprint = null;   // a 3D view not fitted yet
            const userCamera = clone(data.three.cameraView);
            const userLayers = clone(workspace.layerVisibility);
            assert.strictEqual(userLayers.overhead, true);
            const back = workspace.sageViewBackButton;
            assert.ok(back && back.nodeName === 'BUTTON' && back.textContent === 'Back' && back.hidden);
            const view = { siteId: 'site-a', layoutId: 'fl-workspace', revision: 'rev-1', label: 'Assembly Cell A06',
                from: 'south', roofHidden: false,
                camera: { position: { x: 20, y: 5, z: 10 }, target: { x: 20, y: 0.7, z: 18 }, fov: 50 } };
            // Not this layout, or not a camera above its target: nothing moves.
            for (const other of [{ layoutId: 'fl-other' }, { siteId: 'site-b' },
                { camera: { position: { x: 0, y: 0, z: 0 }, target: { x: 0, y: 1, z: 0 }, fov: 50 } }]) {
                assert.strictEqual(await workspace.showSageView(Object.assign({}, view, other)), false);
            }
            assert.deepStrictEqual([workspace.viewMode, data.three.appliedCameraViews.length], ['plan', 0]);

            assert.strictEqual(await workspace.showSageView(view), true);
            assert.strictEqual(workspace.viewMode, '3d', 'from Plan it switches to 3D');
            assert.strictEqual(back.hidden, false, 'Back shows on the 3D view');
            assert.strictEqual(workspace.layerVisibility.overhead, false, 'no roof in the way while it flies');
            await new Promise(resolve => setImmediate(resolve));
            assert.strictEqual(data.three.fitLayoutCount, 0, 'entering 3D does not fit the layout over the glide');
            const times = run(1000);
            const seen = data.three.appliedCameraViews;
            assert.ok(seen.length >= 40 && times.length === seen.length, 'about 5 s of frames at 10 a second');
            assert.deepStrictEqual(seen[0].position, userCamera.position, 'it starts where the user was');
            const last = seen[seen.length - 1];
            assert.deepStrictEqual([last.position, last.target, last.fov],
                [view.camera.position, view.camera.target, 50], 'it settles on Sage\'s view');
            // Halfway it is on the fly-over: higher, farther out and 50 degrees round from where it settles.
            const half = seen[Math.round((seen.length - 1) / 2)];
            const heading = point => Math.atan2(point.x - 20, point.z - 18) * 180 / Math.PI;
            const turned = Math.abs(((heading(half.position) - heading(view.camera.position)) + 540) % 360 - 180);
            assert.ok(Math.abs(turned - 50) < 6, `halfway round the sweep (${turned.toFixed(1)} degrees)`);
            assert.ok(half.position.y > 5 && Math.hypot(half.position.x - 20, half.position.z - 18) > 8);
            assert.strictEqual(workspace.layerVisibility.overhead, true, 'the roof comes back: the view is under it');
            assert.strictEqual(workspace.sageGlide, null);

            // A second move keeps the first Back; a view down through the roof leaves the roof off.
            assert.strictEqual(await workspace.showSageView(Object.assign({}, view, { roofHidden: true,
                camera: { position: { x: 20, y: 30, z: -20 }, target: { x: 20, y: 0.7, z: 18 }, fov: 50 } })), true);
            run(1000);
            assert.strictEqual(workspace.layerVisibility.overhead, false, 'it looks down through the roof');
            back.dispatch('click');
            assert.deepStrictEqual(data.three.appliedCameraViews[data.three.appliedCameraViews.length - 1], userCamera,
                'Back returns to the camera before Sage\'s first move');
            assert.deepStrictEqual([workspace.viewMode, workspace.layerVisibility.overhead,
                workspace.layerVisibility.roofSheeting], ['plan', true, userLayers.roofSheeting]);
            assert.strictEqual(back.hidden, true);
            assert.strictEqual(workspace.sageViewBack, null);
            assert.strictEqual(workspace.lastThreeFitFingerprint, null, 'the next switch to 3D fits as before');

            // The user takes over: a press on the 3D view stops the glide where it is and the roof settles.
            assert.strictEqual(await workspace.showSageView(view), true);
            run(1000, 1300);
            const applied = data.three.appliedCameraViews.length;
            workspace.threeView.dispatch('pointerdown');
            assert.strictEqual(workspace.sageGlide, null);
            assert.ok(cancelled.length >= 1, 'its next frame is cancelled');
            run(2000);
            assert.strictEqual(data.three.appliedCameraViews.length, applied, 'nothing more moves');
            assert.strictEqual(workspace.layerVisibility.overhead, true);

            // From far across the plant it climbs over what stands between, then comes down onto the sweep.
            back.dispatch('click');
            data.three.cameraView = Object.assign(clone(userCamera), { position: { x: 220, y: 5, z: 10 },
                target: { x: 220, y: 0, z: 18 } });
            const from = data.three.appliedCameraViews.length;
            assert.strictEqual(await workspace.showSageView(view), true);
            run(1000);
            const crossing = data.three.appliedCameraViews.slice(from);
            const top = Math.max.apply(null, crossing.map(item => item.position.y));
            assert.ok(top > 45 && top < 100, `it climbs over the plant (${top.toFixed(1)} m)`);
            assert.deepStrictEqual(crossing[crossing.length - 1].position, view.camera.position);
            data.three.cameraView = clone(userCamera);

            // Reduced motion: it goes straight there.
            still = true;
            frames.length = 0;
            assert.strictEqual(await workspace.showSageView(view), true);
            assert.strictEqual(frames.length, 0);
            const jumped = data.three.appliedCameraViews[data.three.appliedCameraViews.length - 1];
            assert.deepStrictEqual([jumped.position, jumped.target], [view.camera.position, view.camera.target]);
            assert.strictEqual(workspace.layerVisibility.overhead, true);
            workspace.destroy();
        });

    await check('Sage takes its 3D shots in this window (SV1): a glide to the main view, each view settled and '
        + 'copied with the roof off, it ends on the main view, and Back returns', async () => {
            const data = fixture();
            const workspace = data.workspace;
            const three = data.three;
            let time = 0;
            data.documentRef.defaultView = {
                requestAnimationFrame(callback) { setImmediate(() => callback(time += 100)); return 1; },
                cancelAnimationFrame() {},
                matchMedia() { return { matches: false }; },
            };
            let loading = 0;
            const diagnostics = [];
            three.getDiagnostics = () => {
                diagnostics.push(loading);
                const value = { mounted: true, status: loading ? 'loading' : 'ready', pendingLoads: loading };
                if (loading) loading -= 1;
                return value;
            };
            three.renderRecordingFrame = () => three.getRecordingCanvas();
            let gate = null;
            const waits = [];
            workspace._sageShotWait = milliseconds => { waits.push(milliseconds); return gate || Promise.resolve(); };
            const shot = [];
            workspace._encodeSageShot = async canvas => {
                const pill = workspace.sageShotsStatus;
                shot.push({ camera: clone(three.cameraView), roof: workspace.layerVisibility.overhead,
                    status: pill.hidden ? null : pill.textContent, modal: pill.getAttribute('aria-modal'),
                    canvas: canvas === three.recordingCanvas });
                return { blob: { type: 'image/jpeg' }, width: 1280, height: 720 };
            };
            workspace._setViewMode('plan');
            const userCamera = clone(three.cameraView);
            const userLayers = clone(workspace.layerVisibility);
            const back = workspace.sageViewBackButton;
            const base = { siteId: 'site-a', layoutId: 'fl-workspace', revision: 'rev-1' };
            const views = [
                { label: 'Assembly Cell A06', from: 'south', roofHidden: false,
                    camera: { position: { x: 20, y: 5, z: 10 }, target: { x: 20, y: 0.7, z: 18 }, fov: 50 } },
                { label: 'Dock Door S1', from: 'east', roofHidden: true,
                    camera: { position: { x: 60, y: 30, z: 0 }, target: { x: 40, y: 1, z: 0 }, fov: 50 } },
            ];
            // Not this layout, or no usable view: no shots, and nothing moves.
            for (const [other, reason] of [[{ layoutId: 'fl-other' }, 'layout_not_open'],
                [{ siteId: 'site-b' }, 'layout_not_open'], [{ views: [] }, 'no_views'],
                [{ views: [{ label: 'below', camera: { position: { x: 0, y: 0, z: 0 },
                    target: { x: 0, y: 1, z: 0 }, fov: 50 } }] }, 'no_views']]) {
                const refused = await workspace.captureSageViews(Object.assign({ views }, base, other));
                assert.deepStrictEqual([refused.shots, refused.complete, refused.reason], [[], false, reason]);
            }
            assert.deepStrictEqual([workspace.viewMode, three.appliedCameraViews.length], ['plan', 0]);

            loading = 3;   // the first view still loads models after it is applied
            const result = await workspace.captureSageViews(Object.assign({ views }, base));
            assert.deepStrictEqual([result.complete, result.reason, result.shots.length], [true, null, 2]);
            assert.deepStrictEqual(result.shots.map(item => [item.index, item.label, item.from, item.roofHidden]),
                [[0, 'Assembly Cell A06', 'south', false], [1, 'Dock Door S1', 'east', true]]);
            assert.deepStrictEqual(result.shots.map(item => [item.image.width, item.image.height, item.image.blob.type]),
                [[1280, 720, 'image/jpeg'], [1280, 720, 'image/jpeg']]);
            assert.strictEqual(workspace.viewMode, '3d', 'from Plan it switches to 3D');
            const applied = three.appliedCameraViews;
            assert.deepStrictEqual(applied[0].position, userCamera.position, 'it glides from where the user was');
            assert.ok(applied.length > 20, 'a glide in frames, not a jump');
            assert.deepStrictEqual(shot.map(item => [item.camera.position, item.camera.target, item.camera.fov]),
                views.map(view => [view.camera.position, view.camera.target, 50]), 'each shot is its view');
            assert.deepStrictEqual(shot.map(item => [item.roof, item.status, item.modal, item.canvas]),
                [[false, 'Sage is taking 3D shots: 1 of 2', 'true', true],
                    [false, 'Sage is taking 3D shots: 2 of 2', 'true', true]],
                'the roof is off and the pill (aria-modal: the in-app browser hides) shows for each shot');
            assert.deepStrictEqual(waits.slice(0, 4), [1200, 250, 250, 250],
                'it draws 1.2 s, then waits while models load');
            assert.deepStrictEqual(waits.slice(4), [1200], 'a view with nothing loading draws 1.2 s');
            const last = applied[applied.length - 1];
            assert.deepStrictEqual([last.position, last.target], [views[0].camera.position, views[0].camera.target],
                'it ends on the main view, not where the user was');
            assert.deepStrictEqual([workspace.layerVisibility.overhead, workspace.sageShotsStatus.hidden, back.hidden],
                [true, true, false], 'the roof as the main view needs it, the pill gone, Back shown');
            back.dispatch('click');
            assert.deepStrictEqual(applied[applied.length - 1], userCamera, 'Back returns to the user\'s camera');
            assert.deepStrictEqual([workspace.viewMode, workspace.layerVisibility.overhead,
                workspace.layerVisibility.roofSheeting], ['plan', userLayers.overhead, userLayers.roofSheeting]);

            // A main view down through the roof leaves the roof off at the end.
            const down = await workspace.captureSageViews(Object.assign({ views: [views[1], views[0]] }, base));
            assert.deepStrictEqual([down.complete, workspace.layerVisibility.overhead], [true, false]);
            back.dispatch('click');

            // One at a time; Back during the shots stops them, and the view stays where Back put it.
            let release = null;
            gate = new Promise(resolve => { release = resolve; });
            shot.length = 0;
            const running = workspace.captureSageViews(Object.assign({ views }, base));
            for (let i = 0; i < 200 && !waits.length; i += 1) await new Promise(resolve => setImmediate(resolve));
            waits.length = 0;
            for (let i = 0; i < 400 && !waits.length; i += 1) await new Promise(resolve => setImmediate(resolve));
            assert.ok(waits.length, 'the first view is drawing');
            assert.strictEqual((await workspace.captureSageViews(Object.assign({ views }, base))).reason, 'busy');
            back.dispatch('click');
            release();
            gate = null;
            const stopped = await running;
            assert.deepStrictEqual([stopped.complete, stopped.reason, stopped.shots.length], [false, 'interrupted', 0]);
            assert.deepStrictEqual(applied[applied.length - 1], userCamera, 'Back still wins');
            assert.deepStrictEqual([workspace.viewMode, workspace.sageShotsStatus.hidden, workspace.sageCapture],
                ['plan', true, null]);
            workspace.destroy();
        });

    await check('Back returns to the view right before Sage\'s latest move once the user moved the view in between; '
        + 'moves in a row keep the view before the first, and the roof comes back as the user had it (SV3b, SV5)',
        async () => {
            const data = fixture();
            const workspace = data.workspace;
            const three = data.three;
            let time = 0;
            data.documentRef.defaultView = {
                requestAnimationFrame(callback) { setImmediate(() => callback(time += 100)); return 1; },
                cancelAnimationFrame() {},
                matchMedia() { return { matches: false }; },
            };
            three.getDiagnostics = () => ({ mounted: true, status: 'ready', pendingLoads: 0 });
            three.renderRecordingFrame = () => three.getRecordingCanvas();
            workspace._sageShotWait = () => Promise.resolve();
            workspace._encodeSageShot = async () => ({ blob: { type: 'image/jpeg' }, width: 1280, height: 720 });
            workspace._setViewMode('3d');
            const userLayers = clone(workspace.layerVisibility);
            assert.strictEqual(userLayers.overhead, true);
            const back = workspace.sageViewBackButton;
            const applied = three.appliedCameraViews;
            const base = { siteId: 'site-a', layoutId: 'fl-workspace', revision: 'rev-1' };
            const view = (label, x, z, roofHidden) => ({ label, from: 'south', roofHidden,
                camera: { position: { x, y: roofHidden ? 40 : 5, z: z - 10 }, target: { x, y: 0.7, z }, fov: 50 } });
            const shots = (...args) => workspace.captureSageViews(Object.assign({ views: [view(...args)] }, base));

            // "show me what you changed", then "show me the dock doors": moves in a row keep the view before the first.
            const first = clone(three.cameraView);
            assert.strictEqual((await shots('Assembly Cell A06', 20, 18, false)).complete, true);
            assert.strictEqual((await shots('Dock Wall + Door Openings', 60, 0, true)).complete, true);
            assert.strictEqual(workspace.layerVisibility.overhead, false, 'the dock view looks down through the roof');
            back.dispatch('click');
            assert.deepStrictEqual(applied[applied.length - 1], first, 'Back: the view before the first move');
            assert.strictEqual(workspace.layerVisibility.overhead, true, 'with the user\'s roof');

            // SV5: a move down through the roof, then the user's own overview (the roof still off), then "show me
            // Inspection Q04": Back returns to that overview, and the roof comes back.
            assert.strictEqual((await shots('Dock Wall + Door Openings', 60, 0, true)).complete, true);
            assert.strictEqual(workspace.layerVisibility.overhead, false);
            const overview = Object.assign(clone(three.cameraView), { position: { x: 110, y: 160, z: -90 },
                target: { x: 110, y: 0, z: 60 } });
            three.cameraView = clone(overview);   // the user orbits and zooms out
            assert.strictEqual((await shots('Inspection Q04', 213.5, 76, true)).complete, true);
            const onQ04 = applied[applied.length - 1];
            assert.deepStrictEqual([onQ04.target, workspace.layerVisibility.overhead], [{ x: 213.5, y: 0.7, z: 76 }, false],
                'the view is left on Q04, looking down through the roof');
            back.dispatch('click');
            assert.deepStrictEqual(applied[applied.length - 1], overview, 'Back: the view right before Q04');
            assert.deepStrictEqual([workspace.viewMode, workspace.layerVisibility.overhead, back.hidden],
                ['3d', true, true], 'with the user\'s own roof, which only Sage had hidden');

            // A click on a shot moves the view; the user goes to Plan; Sage's next shots: Back returns to Plan.
            assert.strictEqual(await workspace.showSageView(Object.assign(view('Assembly Cell A02', 113, 17, false),
                base)), true);
            for (let i = 0; i < 400 && workspace.sageGlide; i += 1) await new Promise(resolve => setImmediate(resolve));
            assert.strictEqual(workspace.sageGlide, null, 'the glide landed');
            workspace._setViewMode('plan');
            assert.strictEqual((await shots('Assembly Cell A02', 113, 17, false)).complete, true);
            assert.strictEqual(workspace.viewMode, '3d');
            back.dispatch('click');
            assert.deepStrictEqual([workspace.viewMode, workspace.sageViewBack, back.hidden], ['plan', null, true],
                'Back: Plan, where the user was right before');

            // Sage's next move cuts into its own glide part way: still moves in a row, so Back keeps Plan.
            const inPlan = clone(three.cameraView);
            assert.strictEqual((await shots('Assembly Cell A06', 20, 18, false)).complete, true);
            const fromA06 = clone(three.cameraView);
            assert.strictEqual(await workspace.showSageView(Object.assign(view('Dock Wall + Door Openings', 60, 0,
                true), base)), true);
            for (let i = 0; i < 6; i += 1) await new Promise(resolve => setImmediate(resolve));
            assert.ok(workspace.sageGlide && Math.hypot(three.cameraView.position.x - fromA06.position.x,
                three.cameraView.position.z - fromA06.position.z) > 1, 'part way there');
            assert.strictEqual((await shots('Inspection Q04', 213.5, 76, true)).complete, true);
            back.dispatch('click');
            assert.deepStrictEqual([workspace.viewMode, applied[applied.length - 1]], ['plan', inPlan],
                'Back: Plan and the camera before the first of these moves');

            // Shots that never moved the view (the 3D view could not take a camera) leave the user's move to count.
            assert.strictEqual((await shots('Assembly Cell A06', 20, 18, false)).complete, true);
            three.cameraView = clone(overview);   // the user orbits away again
            three.applyCameraView = undefined;
            const failed = await shots('Inspection Q04', 213.5, 76, true);
            delete three.applyCameraView;
            assert.deepStrictEqual([failed.complete, failed.reason, three.cameraView], [false, 'no_3d_view', overview]);
            assert.strictEqual((await shots('Inspection Q04', 213.5, 76, true)).complete, true);
            back.dispatch('click');
            assert.deepStrictEqual([workspace.viewMode, applied[applied.length - 1]], ['3d', overview],
                'Back: the overview the user went to, right before Q04');

            // Shots that moved the view and stopped part way (the second could not be copied) end on Sage's view:
            // the next move is still one in a row, and Back keeps the view before the stopped shots.
            three.renderRecordingFrame = () => (three.cameraView.target.x === 60 ? null : three.getRecordingCanvas());
            const partial = await workspace.captureSageViews(Object.assign({ views: [view('Assembly Cell A06', 20, 18,
                false), view('Dock Wall + Door Openings', 60, 0, true)] }, base));
            three.renderRecordingFrame = () => three.getRecordingCanvas();
            assert.deepStrictEqual([partial.complete, partial.reason, partial.shots.length, three.cameraView.target.x],
                [false, 'no_canvas', 1, 60], 'stopped on the second view');
            assert.strictEqual((await shots('Inspection Q04', 213.5, 76, true)).complete, true);
            back.dispatch('click');
            assert.deepStrictEqual(applied[applied.length - 1], overview, 'Back: the view before the stopped shots');

            // The chat stops the shots part way (Stop): the same, the view stays on Sage's second view.
            let release = null;
            const gate = new Promise(resolve => { release = resolve; });
            workspace._sageShotWait = () => (three.cameraView.target.x === 60 ? gate : Promise.resolve());
            const stopping = workspace.captureSageViews(Object.assign({ requestId: 'stop-me', views: [
                view('Assembly Cell A06', 20, 18, false), view('Dock Wall + Door Openings', 60, 0, true)] }, base));
            for (let i = 0; i < 400 && three.cameraView.target.x !== 60; i += 1) {
                await new Promise(resolve => setImmediate(resolve));
            }
            assert.strictEqual(workspace.stopSageCapture('stop-me'), true);
            release();
            const stopped = await stopping;
            workspace._sageShotWait = () => Promise.resolve();
            assert.deepStrictEqual([stopped.complete, stopped.shots.length, three.cameraView.target.x], [false, 1, 60]);
            assert.strictEqual((await shots('Inspection Q04', 213.5, 76, true)).complete, true);
            back.dispatch('click');
            assert.deepStrictEqual(applied[applied.length - 1], overview, 'Back: the view before the stopped shots');
            workspace.destroy();
        });

    await check('Back stays as it was when Sage\'s next move ends before it changed the view, and the view the user '
        + 'moved to still counts for the move after (final round 7)', async () => {
            const data = fixture();
            const workspace = data.workspace;
            const three = data.three;
            const frames = [];
            data.documentRef.defaultView = {
                requestAnimationFrame(callback) { frames.push(callback); return frames.length; },
                cancelAnimationFrame() {},
                matchMedia() { return { matches: false }; },
            };
            const run = () => {
                for (let time = 1000; frames.length; time += 100) frames.shift()(time);
            };
            three.getDiagnostics = () => ({ mounted: true, status: 'ready', pendingLoads: 0 });
            three.renderRecordingFrame = () => three.getRecordingCanvas();
            workspace._sageShotWait = () => Promise.resolve();
            workspace._encodeSageShot = async () => ({ blob: { type: 'image/jpeg' }, width: 1280, height: 720 });
            workspace._setViewMode('3d');
            const back = workspace.sageViewBackButton;
            const applied = three.appliedCameraViews;
            const base = { siteId: 'site-a', layoutId: 'fl-workspace', revision: 'rev-1' };
            const view = (label, x, z) => Object.assign({ label, from: 'south', roofHidden: false,
                camera: { position: { x, y: 5, z: z - 10 }, target: { x, y: 0.7, z }, fov: 50 } }, base);
            const moved = (x, z) => Object.assign(clone(three.cameraView), { position: { x, y: 160, z: z - 150 },
                target: { x, y: 0, z } });

            // One move that lands, then the user's own view; Sage's next move is stopped before its first frame.
            const first = clone(three.cameraView);
            assert.strictEqual(await workspace.showSageView(view('Assembly Cell A06', 20, 18)), true);
            run();
            const overview = moved(110, 60);
            three.cameraView = clone(overview);
            const count = applied.length;
            assert.strictEqual(await workspace.showSageView(view('Inspection Q04', 213.5, 76)), true);
            workspace.threeView.dispatch('pointerdown');
            frames.length = 0;
            assert.deepStrictEqual([applied.length, three.cameraView], [count, overview], 'the view never moved');
            assert.deepStrictEqual(workspace.sageViewBack.camera, first, 'Back keeps its view');
            // The move after it moves the view: Back returns to the overview, the view right before it.
            assert.strictEqual(await workspace.showSageView(view('Inspection Q04', 213.5, 76)), true);
            run();
            back.dispatch('click');
            assert.deepStrictEqual(applied[applied.length - 1], overview, 'Back: the overview');

            // The same with shots the chat stops before their glide's first frame.
            assert.strictEqual(await workspace.showSageView(view('Assembly Cell A06', 20, 18)), true);
            run();
            const elsewhere = moved(40, 120);
            three.cameraView = clone(elsewhere);
            const taking = workspace.captureSageViews(Object.assign({ requestId: 'never-moved',
                views: [view('Inspection Q04', 213.5, 76)] }, base));
            await new Promise(resolve => setImmediate(resolve));
            assert.strictEqual(workspace.stopSageCapture('never-moved'), true);
            const stopped = await taking;
            frames.length = 0;
            assert.deepStrictEqual([stopped.complete, three.cameraView], [false, elsewhere], 'the shots never moved it');
            assert.deepStrictEqual(workspace.sageViewBack.camera, overview, 'Back keeps its view');
            assert.strictEqual(await workspace.showSageView(view('Inspection Q04', 213.5, 76)), true);
            run();
            back.dispatch('click');
            assert.deepStrictEqual(applied[applied.length - 1], elsewhere, 'Back: the view right before the move');

            // Shots whose glide never ran (animation frames paused in a hidden window) move the view with their
            // first shot: from there, the view the user moved to is Back's.
            const playing = data.documentRef.defaultView;
            assert.strictEqual(await workspace.showSageView(view('Assembly Cell A06', 20, 18)), true);
            run();
            const third = moved(170, 30);
            three.cameraView = clone(third);
            data.documentRef.defaultView = {
                requestAnimationFrame() { return 1; },
                cancelAnimationFrame() {},
                setTimeout(callback) { setImmediate(callback); return 9; },
                clearTimeout() {},
                matchMedia() { return { matches: false }; },
            };
            const paused = await workspace.captureSageViews(Object.assign({ views: [view('Inspection Q04', 213.5,
                76)] }, base));
            data.documentRef.defaultView = playing;
            assert.deepStrictEqual([paused.complete, workspace.sageGlide], [true, null]);
            back.dispatch('click');
            assert.deepStrictEqual(applied[applied.length - 1], third, 'Back: the view right before the shots');

            // From Plan, a move stopped before its first frame has already switched to 3D: Back returns to Plan.
            assert.strictEqual(await workspace.showSageView(view('Assembly Cell A06', 20, 18)), true);
            run();
            workspace._setViewMode('plan');
            assert.strictEqual(await workspace.showSageView(view('Inspection Q04', 213.5, 76)), true);
            assert.strictEqual(workspace.viewMode, '3d');
            workspace.threeView.dispatch('pointerdown');
            frames.length = 0;
            back.dispatch('click');
            assert.deepStrictEqual([workspace.viewMode, back.hidden], ['plan', true], 'Back: Plan');
            workspace.destroy();
        });

    const glidingFixture = () => {
        const data = fixture();
        const frames = [];
        data.documentRef.defaultView = {
            requestAnimationFrame(callback) { frames.push(callback); return frames.length; },
            cancelAnimationFrame() {},
            matchMedia() { return { matches: false }; },
        };
        data.workspace._setViewMode('3d');
        const base = { siteId: 'site-a', layoutId: 'fl-workspace', revision: 'rev-1' };
        return Object.assign(data, { frames,
            run: () => { for (let time = 1000; frames.length; time += 100) frames.shift()(time); },
            view: (label, x, z, roofHidden) => Object.assign({ label, from: 'south', roofHidden: roofHidden === true,
                camera: { position: { x, y: 5, z: z - 10 }, target: { x, y: 0.7, z }, fov: 50 } }, base),
            moved: (x, z) => Object.assign(clone(data.three.cameraView), { position: { x, y: 160, z: z - 150 },
                target: { x, y: 0, z } }) });
    };

    await check('A first move stopped before it changed the view leaves no Back, and the move after takes the view '
        + 'the user moved to (Sage 3D shots later list, Codex on 139b1e7)', async () => {
            const data = glidingFixture();
            const { workspace, three, view, moved, run, frames } = data;
            const back = workspace.sageViewBackButton;
            const applied = three.appliedCameraViews;
            const first = clone(three.cameraView);
            const count = applied.length;
            assert.strictEqual(await workspace.showSageView(view('Assembly Cell A06', 20, 18)), true);
            workspace.threeView.dispatch('pointerdown');
            frames.length = 0;
            assert.deepStrictEqual([applied.length, three.cameraView], [count, first], 'the view never moved');
            assert.deepStrictEqual([workspace.sageViewBack, back.hidden], [null, true],
                'no Back yet (139b1e7 kept the view before this move)');
            // The user moves the view; Sage's next move lands: Back returns to the user's view, not the first.
            const overview = moved(110, 60);
            three.cameraView = clone(overview);
            assert.strictEqual(await workspace.showSageView(view('Inspection Q04', 213.5, 76)), true);
            assert.strictEqual(back.hidden, true, 'Back shows once the move changes the view');
            run();
            assert.strictEqual(back.hidden, false);
            back.dispatch('click');
            assert.deepStrictEqual(applied[applied.length - 1], overview, 'Back: the view the user moved to');
            workspace.destroy();
        });

    await check('A roof layer the user switches between Sage\'s moves is the roof Back brings back; Sage\'s own '
        + 'hiding never is (Sage 3D shots later list, Codex on 4c274e3)', async () => {
            const data = glidingFixture();
            const { workspace, three, view, moved, run } = data;
            const back = workspace.sageViewBackButton;
            const layer = key => workspace.layerPanel.querySelector('[data-facility-layer="' + key + '"]');
            assert.strictEqual(workspace.layerVisibility.roofSheeting, false);
            assert.strictEqual(await workspace.showSageView(view('Assembly Cell A06', 20, 18)), true);
            run();
            // The user switches roof sheeting on and moves the view; Sage's next move lands; then Back.
            layer('roofSheeting').checked = true;
            layer('roofSheeting').dispatch('change');
            three.cameraView = clone(moved(110, 60));
            assert.strictEqual(await workspace.showSageView(view('Inspection Q04', 213.5, 76)), true);
            run();
            back.dispatch('click');
            assert.strictEqual(workspace.layerVisibility.roofSheeting, true,
                'the user\'s roof sheeting (4c274e3 turned it off again)');
            // A move that looks down lands with the roof off; the user switches another layer; Back: the user's roof.
            assert.strictEqual(await workspace.showSageView(view('Assembly Cell A06', 20, 18, true)), true);
            run();
            assert.strictEqual(workspace.layerVisibility.roofSheeting, false, 'Sage looks down through the roof');
            layer('routes').checked = false;
            layer('routes').dispatch('change');
            back.dispatch('click');
            assert.deepStrictEqual([workspace.layerVisibility.roofSheeting, workspace.layerVisibility.routes],
                [true, false], 'the user\'s roof, not Sage\'s hiding, and the routes as the user left them');
            workspace.destroy();
        });

    await check('A 3D shot is the frame scaled to fit 1280 x 720, as a JPEG, copied at once', async () => {
        const drawn = [];
        const made = [];
        const documentRef = {
            createElement(tag) {
                const node = {
                    tag,
                    getContext(kind) { return kind === '2d' ? { drawImage(...args) { drawn.push(args.slice(1)); } } : null; },
                    toBlob(callback, type, quality) { made.push([this.width, this.height, type, quality]);
                        callback({ type }); },
                };
                return node;
            },
        };
        const encode = canvas => workspaceModule.Workspace.prototype._encodeSageShot.call(
            { document: documentRef }, canvas);
        const wide = await encode({ width: 2560, height: 1440 });
        const narrow = await encode({ width: 1000, height: 700 });
        const tall = await encode({ width: 1400, height: 1400 });
        assert.deepStrictEqual([wide.width, wide.height, narrow.width, narrow.height, tall.width, tall.height],
            [1280, 720, 1000, 700, 720, 720]);
        assert.deepStrictEqual(made.map(item => item[2]), ['image/jpeg', 'image/jpeg', 'image/jpeg']);
        assert.deepStrictEqual(drawn[0], [0, 0, 1280, 720]);
        assert.strictEqual(await encode({ width: 0, height: 0 }), null);
    });

    await check('A Sage glide that fails or never lands ends the shots instead of leaving them busy (SV1 round 2)',
        async () => {
            // A glide frame that throws (a lost 3D context, say): the capture ends at once, and the next one runs.
            const kit = sageShotsFixture();
            const { workspace, three } = kit;
            const own = clone(workspace.layerVisibility);
            assert.strictEqual(own.overhead, true);
            const apply = three.applyCameraView.bind(three);
            let glideFrames = 0;
            three.applyCameraView = value => {
                if (workspace.sageGlide && ++glideFrames === 3) throw new Error('lost context');
                return apply(value);
            };
            const failed = await within(workspace.captureSageViews(kit.request()), 'a capture whose glide failed');
            assert.deepStrictEqual([failed.complete, failed.reason, failed.shots.length], [false, 'no_3d_view', 0]);
            assert.deepStrictEqual([workspace.sageCapture, workspace.sageGlide, workspace.sageShotsStatus.hidden],
                [null, null, true]);
            assert.deepStrictEqual([workspace.layerVisibility.overhead, workspace.layerVisibility.roofSheeting],
                [own.overhead, own.roofSheeting], 'the user\'s roof is back');
            const next = await within(workspace.captureSageViews(kit.request()), 'the next capture');
            assert.deepStrictEqual([next.complete, next.reason], [true, null], 'not left busy');
            workspace.destroy();

            // Animation frames that never come (a hidden window): the glide is stopped after its time, and the
            // shots go on from each view's own camera.
            const timeouts = [];
            const paused = sageShotsFixture({ view: {
                requestAnimationFrame() { return 1; },
                setTimeout(callback, milliseconds) { timeouts.push(milliseconds); setImmediate(callback); return 9; },
                clearTimeout() {},
            } });
            const done = await within(paused.workspace.captureSageViews(paused.request()),
                'a capture whose glide never landed');
            assert.deepStrictEqual([done.complete, done.shots.length, paused.workspace.sageGlide], [true, 2, null]);
            assert.ok(timeouts[0] > 3000, 'it gave the glide its time and 3 s more');
            assert.deepStrictEqual(timeouts.slice(1), [10000, 10000], 'each JPEG has its own limit (SV1 round 4)');
            assert.deepStrictEqual(paused.shots.map(item => item.camera.position),
                paused.views.map(view => view.camera.position));
            paused.workspace.destroy();
        });

    await check('Each 3D shot waits until every model big enough on screen is drawn in full, as of its last camera '
        + '(SV1 round 2)', async () => {
            const kit = sageShotsFixture();
            const { workspace, three } = kit;
            const log = [];
            const apply = three.applyCameraView.bind(three);
            three.applyCameraView = value => { log.push('apply'); return apply(value); };
            // The first view: 2 models still drawn as footprints after the settle, then 1, then none.
            const left = [2, 1, 0];
            three.loadVisibleDetail = () => {
                const value = left.length ? left.shift() : 0;
                log.push('detail ' + value);
                return value;
            };
            three.renderRecordingFrame = () => { log.push('copy'); return three.getRecordingCanvas(); };
            const result = await within(workspace.captureSageViews(kit.request()), 'the capture');
            assert.deepStrictEqual([result.complete, result.reason], [true, null]);
            assert.deepStrictEqual(kit.waits, [1200, 250, 250, 1200], 'it waits while models are left to draw');
            const copies = log.reduce((found, item, index) => (item === 'copy' ? found.concat(index) : found), []);
            assert.deepStrictEqual(copies.map(index => log.slice(index - 3, index)),
                [['apply', 'detail 0', 'apply'], ['apply', 'detail 0', 'apply']],
                'each copy follows a camera that left nothing to draw, put back once more right before it');
            assert.ok(log.indexOf('detail 2') < log.indexOf('detail 1') && log.indexOf('detail 1') < copies[0]);
            workspace.destroy();
        });

    await check('Shots that stop part way or fail give the user their own roof back, in any view (SV1 round 2)',
        async () => {
            // Plan, chosen while the first view draws.
            const kit = sageShotsFixture();
            const { workspace } = kit;
            const own = clone(workspace.layerVisibility);
            assert.strictEqual(own.overhead, true);
            kit.onWait = (milliseconds, count) => { if (count === 1) workspace._setViewMode('plan'); };
            const stopped = await within(workspace.captureSageViews(kit.request()), 'the capture');
            assert.deepStrictEqual([stopped.complete, stopped.reason, workspace.viewMode], [false, 'interrupted', 'plan']);
            assert.deepStrictEqual([workspace.layerVisibility.overhead, workspace.layerVisibility.roofSheeting],
                [own.overhead, own.roofSheeting]);
            workspace.destroy();

            // A 3D view that cannot be copied, with a main view that looks down through the roof.
            const broken = sageShotsFixture();
            broken.three.renderRecordingFrame = () => null;
            const before = clone(broken.workspace.layerVisibility);
            const failed = await within(broken.workspace.captureSageViews(
                broken.request({ views: [broken.views[1], broken.views[0]] })), 'the capture');
            assert.deepStrictEqual([failed.complete, failed.reason], [false, 'no_canvas']);
            assert.deepStrictEqual([broken.workspace.layerVisibility.overhead,
                broken.workspace.layerVisibility.roofSheeting], [before.overhead, before.roofSheeting],
                'not the main view\'s roof: that is for shots that all came out');
            broken.workspace.destroy();
        });

    await check('An older capture winding down never hides a newer one\'s status pill (SV1 round 2)', async () => {
        const kit = sageShotsFixture();
        const { workspace } = kit;
        const pill = workspace.sageShotsStatus;
        const openA = kit.gate();
        const runningA = workspace.captureSageViews(kit.request());
        await until(() => kit.waits.length === 1);
        assert.strictEqual(kit.waits.length, 1, 'A\'s first view is drawing');
        workspace.sageViewBackButton.dispatch('click');
        assert.strictEqual(pill.hidden, true, 'Back hides A\'s pill at once');
        const openB = kit.gate();
        const runningB = workspace.captureSageViews(kit.request());
        await until(() => kit.waits.length === 2);
        assert.deepStrictEqual([pill.hidden, pill.textContent], [false, 'Sage is taking 3D shots: 1 of 2']);
        openA();
        const a = await within(runningA, 'A');
        assert.deepStrictEqual([a.complete, a.reason], [false, 'interrupted']);
        assert.deepStrictEqual([pill.hidden, pill.textContent], [false, 'Sage is taking 3D shots: 1 of 2'],
            'B\'s pill stays while B runs');
        openB();
        const b = await within(runningB, 'B');
        assert.deepStrictEqual([b.complete, pill.hidden], [true, true]);
        workspace.destroy();
    });

    await check('Shots stopped by a switch to another layout leave that layout\'s camera alone (SV1 round 2)',
        async () => {
            const kit = sageShotsFixture();
            const { workspace, data, three } = kit;
            let applied = null;
            kit.onWait = (milliseconds, count) => {
                if (count !== 1) return;
                data.session.state.layout = Object.assign(clone(data.session.state.layout), { layoutId: 'fl-other' });
                data.session._notify();
                applied = three.appliedCameraViews.length;
            };
            const result = await within(workspace.captureSageViews(kit.request()), 'the capture');
            assert.deepStrictEqual([result.complete, result.reason], [false, 'interrupted']);
            await until(() => false, 40);
            assert.strictEqual(three.appliedCameraViews.length, applied, 'no camera of the old layout on the new one');
            workspace.destroy();
        });

    await check('While Sage takes shots no other request moves the 3D view, and after them it does (SV1 round 2)',
        async () => {
            const kit = sageShotsFixture();
            const { workspace, three } = kit;
            const open = kit.gate();
            const running = workspace.captureSageViews(kit.request());
            await until(() => kit.waits.length === 1);
            const other = Object.assign({ siteId: 'site-a', layoutId: 'fl-workspace' }, kit.views[1]);
            assert.strictEqual(await workspace.showSageView(other), false, 'refused while the shots are taken');
            assert.strictEqual(workspace.sageGlide, null);
            open();
            const result = await within(running, 'the capture');
            assert.strictEqual(result.complete, true);
            await until(() => false, 40);   // a glide, had one started, would have moved on by now
            assert.deepStrictEqual(three.appliedCameraViews.at(-1).position, kit.views[0].camera.position,
                'it ends on its main view');
            assert.strictEqual(await workspace.showSageView(other), true, 'after the shots the view moves again');
            workspace.destroy();
        });

    await check('Shots are taken only of the saved revision Sage read, with nothing unsaved or staged over it '
        + '(SV1 round 2)', async () => {
            const kit = sageShotsFixture();
            const { workspace, data } = kit;
            const refused = async (extra, label) => {
                const result = await within(workspace.captureSageViews(kit.request(extra)), label);
                assert.deepStrictEqual([result.reason, result.shots.length, workspace.viewMode],
                    ['revision_differs', 0, 'plan'], label);
            };
            workspace._setViewMode('plan');
            await refused({ revision: 'rev-2' }, 'another revision');
            await refused({ revision: undefined }, 'no revision');
            data.session.state.dirty = true;
            data.session._notify();
            await workspace.whenIdle();
            await refused({}, 'unsaved edits');
            data.session.state.dirty = false;
            const ghost = clone(data.session.state.layout);
            data.session.state.layoutProposal = {
                authority: 'server-authoritative', previewPure: true, baseRevision: 'rev-1', selectedIndex: 0,
                alternatives: [{ proposalId: 'proposal-look', alternativeId: 'alternative-look', operations: [],
                    ghostPreview: { layout: ghost, routeProposals: [] }, metrics: {}, findings: [],
                    newHardFindingIds: [] }],
            };
            data.session._notify();
            await workspace.whenIdle();
            await refused({}, 'a review drawn in place of the saved layout');
            data.session.state.layoutProposal = null;
            data.session._notify();
            await workspace.whenIdle();

            // An edit while the first view draws stops the shots.
            kit.onWait = (milliseconds, count) => {
                if (count !== 1) return;
                data.session.state.dirty = true;
                data.session._notify();
            };
            const stopped = await within(workspace.captureSageViews(kit.request()), 'the capture');
            assert.deepStrictEqual([stopped.complete, stopped.reason, stopped.shots.length], [false, 'interrupted', 0]);
            workspace.destroy();
        });

    await check('No shots over placement alternatives or the placement ghost, and either one appearing stops them '
        + '(SV1 round 3)', async () => {
            const kit = sageShotsFixture();
            const { workspace, data } = kit;
            const refused = async label => {
                await workspace.whenIdle();
                const result = await within(workspace.captureSageViews(kit.request()), label);
                assert.deepStrictEqual([result.reason, result.shots.length], ['revision_differs', 0], label);
            };
            data.session.beginGhostPlacement(catalog()[0]);
            await refused('equipment being placed');
            data.session.cancelGhostPlacement();
            data.session.installPlacementAlternatives(SPATIAL_FIXTURE.candidateReceipt);
            data.session.state.ghostPlacement = null;
            data.session._notify();
            await refused('placement alternatives');
            data.session.dismissPlacementAlternatives();
            await workspace.whenIdle();

            // The ghost appears during the glide to the main view: no view is drawn.
            const apply = kit.three.applyCameraView.bind(kit.three);
            let frames = 0;
            kit.three.applyCameraView = value => {
                frames += 1;
                if (frames === 2) data.session.beginGhostPlacement(catalog()[0]);
                return apply(value);
            };
            const own = clone(workspace.layerVisibility);
            const glided = await within(workspace.captureSageViews(kit.request()), 'the glide');
            assert.deepStrictEqual([glided.complete, glided.reason, glided.shots.length, kit.waits.length],
                [false, 'interrupted', 0, 0]);
            assert.deepStrictEqual([workspace.layerVisibility.overhead, workspace.layerVisibility.roofSheeting],
                [own.overhead, own.roofSheeting], 'the user\'s own roof comes back');
            kit.three.applyCameraView = apply;
            data.session.cancelGhostPlacement();
            await workspace.whenIdle();

            // Alternatives appear while the first view draws.
            kit.onWait = (milliseconds, count) => {
                if (count === 1) {   // the first wait of this kit: no capture before it drew
                    data.session.installPlacementAlternatives(SPATIAL_FIXTURE.candidateReceipt);
                }
            };
            const drawn = await within(workspace.captureSageViews(kit.request()), 'the capture');
            assert.deepStrictEqual([drawn.complete, drawn.reason, drawn.shots.length], [false, 'interrupted', 0]);
            workspace.destroy();
        });

    await check('A change or Back while the last shot is encoded ends the shots stopped, never complete '
        + '(SV1 round 3)', async () => {
            // A new revision saved while the second shot is encoded.
            const kit = sageShotsFixture();
            const { workspace, data, three } = kit;
            const own = clone(workspace.layerVisibility);
            const encode = workspace._encodeSageShot;
            let applied = null;
            workspace._encodeSageShot = async canvas => {
                const image = await encode(canvas);
                if (kit.shots.length === 2) {
                    data.session.state.baseRevision = 'rev-2';
                    data.session._notify();
                    applied = three.appliedCameraViews.length;
                }
                return image;
            };
            const saved = await within(workspace.captureSageViews(kit.request()), 'the capture');
            assert.deepStrictEqual([saved.complete, saved.reason, saved.shots.length], [false, 'interrupted', 1],
                'the shot encoded across the change does not count');
            await until(() => false, 40);
            assert.strictEqual(three.appliedCameraViews.length, applied, 'no main view put on the new revision');
            assert.deepStrictEqual([workspace.layerVisibility.overhead, workspace.layerVisibility.roofSheeting],
                [own.overhead, own.roofSheeting]);
            workspace.destroy();

            // Back while the second shot is encoded.
            const other = sageShotsFixture();
            const otherEncode = other.workspace._encodeSageShot;
            let backAt = null;
            other.workspace._encodeSageShot = async canvas => {
                const image = await otherEncode(canvas);
                if (other.shots.length === 2) {
                    other.workspace.sageViewBackButton.dispatch('click');
                    backAt = other.three.appliedCameraViews.length;
                }
                return image;
            };
            const back = await within(other.workspace.captureSageViews(other.request()), 'the capture');
            assert.deepStrictEqual([back.complete, back.reason], [false, 'interrupted']);
            await until(() => false, 40);
            assert.strictEqual(other.three.appliedCameraViews.length, backAt, 'Back leaves the view where it put it');
            other.workspace.destroy();
        });

    await check('A roof turned on while a view draws is off again in the shot (SV1 round 3)', async () => {
        const kit = sageShotsFixture();
        const { workspace, three } = kit;
        const copied = [];
        three.renderRecordingFrame = () => {
            copied.push([workspace.layerVisibility.overhead, three.layerVisibility.at(-1).overhead]);
            return three.getRecordingCanvas();
        };
        kit.onWait = () => {   // the user ticks Roof in the layers panel while each view draws
            const roof = workspace.layerPanel.querySelector('[data-facility-layer="overhead"]');
            roof.checked = true;
            roof.dispatch('change');
            assert.strictEqual(three.layerVisibility.at(-1).overhead, true);
        };
        const result = await within(workspace.captureSageViews(kit.request()), 'the capture');
        assert.strictEqual(result.complete, true);
        assert.deepStrictEqual(copied, [[false, false], [false, false]]);
        workspace.destroy();
    });

    // The 3D view's scene as the three adapter reports it (sceneState), for the round 4 checks.
    const sageScene = (three, scene) => {
        three.sceneState = () => ({ requested: scene.requested, installed: scene.installed,
            status: scene.lost ? 'degraded' : 'ready', mounted: true, suspended: false, degraded: Boolean(scene.lost),
            contextLost: Boolean(scene.lost), disposed: false });
        return scene;
    };

    await check('Shots wait for the window\'s layout to be built into the 3D scene, and a newer scene stops them '
        + '(SV1 round 4)', async () => {
            // The new layout is still on its way in (the 3D view waits for the appearance library): the old scene is
            // drawn and reads as ready.
            const kit = sageShotsFixture();
            const { workspace, three } = kit;
            const scene = sageScene(three, { requested: 2, installed: 1 });
            const copied = [];
            three.renderRecordingFrame = () => {
                copied.push(scene.installed);
                return three.getRecordingCanvas();
            };
            kit.onWait = (milliseconds, count) => { if (count === 3) scene.installed = 2; };
            const result = await within(workspace.captureSageViews(kit.request()), 'the capture');
            assert.deepStrictEqual([result.complete, copied], [true, [2, 2]], 'both shots of the new scene');
            assert.deepStrictEqual(kit.waits, [250, 250, 250, 1200, 1200], 'it waited for the scene first');
            workspace.destroy();

            // A newer scene asked for while a view draws (another layout on its way in): the shots stop.
            const newer = sageShotsFixture();
            const next = sageScene(newer.three, { requested: 1, installed: 1 });
            newer.onWait = (milliseconds, count) => { if (count === 1) next.requested = 2; };
            const stopped = await within(newer.workspace.captureSageViews(newer.request()), 'the capture');
            assert.deepStrictEqual([stopped.complete, stopped.reason, stopped.shots.length], [false, 'interrupted', 0]);
            newer.workspace.destroy();

            // A scene that is never built: the shots end, and the window is not left busy.
            const never = sageShotsFixture();
            sageScene(never.three, { requested: 2, installed: 1 });
            const own = clone(never.workspace.layerVisibility);
            const failed = await within(never.workspace.captureSageViews(never.request()), 'the capture');
            assert.deepStrictEqual([failed.complete, failed.reason, failed.shots.length], [false, 'no_3d_view', 0]);
            assert.strictEqual(never.waits.length, 80, '20 s of the capture\'s own 250 ms waits');
            assert.deepStrictEqual([never.workspace.sageCapture, never.workspace.sageShotsStatus.hidden,
                never.workspace.layerVisibility.overhead], [null, true, own.overhead]);
            never.workspace.destroy();
        });

    await check('Every wait of a capture ends: a held JPEG encoder or 3D start, or Back while one is held, ends the '
        + 'shots (SV1 round 4)', async () => {
            // A JPEG encoder that never answers.
            const kit = sageShotsFixture();
            const { workspace } = kit;
            workspace.sageLimits = Object.assign({}, workspace.sageLimits, { encodeMs: 30 });
            workspace._encodeSageShot = () => new Promise(() => {});
            const held = await within(workspace.captureSageViews(kit.request()), 'a capture with a held encoder');
            assert.deepStrictEqual([held.complete, held.reason, held.shots.length], [false, 'no_canvas', 0]);
            assert.deepStrictEqual([workspace.sageCapture, workspace.sageShotsStatus.hidden], [null, true],
                'the pill and the busy guard are released');
            workspace.destroy();

            // Back while the encoder is held: the capture ends at once, not when the encoder answers.
            const back = sageShotsFixture();
            back.workspace._encodeSageShot = () => {
                setImmediate(() => back.workspace.sageViewBackButton.dispatch('click'));
                return new Promise(() => {});
            };
            const stopped = await within(back.workspace.captureSageViews(back.request()), 'a capture stopped by Back');
            assert.deepStrictEqual([stopped.complete, stopped.reason, stopped.shots.length], [false, 'interrupted', 0]);
            back.workspace.destroy();

            // A 3D view opened for the first time that never starts.
            const start = sageShotsFixture();
            start.workspace.sageLimits = Object.assign({}, start.workspace.sageLimits, { readyMs: 30 });
            start.three.getCameraView = () => null;
            start.workspace.controller.ready = () => new Promise(() => {});
            const never = await within(start.workspace.captureSageViews(start.request()), 'a capture of a held 3D start');
            assert.deepStrictEqual([never.complete, never.reason], [false, 'no_3d_view']);
            assert.deepStrictEqual([start.workspace.sageCapture, start.workspace.sageShotsStatus.hidden], [null, true]);
            start.workspace.destroy();

            // The same with Back first: Back ends the wait.
            const early = sageShotsFixture();
            early.three.getCameraView = () => null;
            early.workspace.controller.ready = () => {
                setImmediate(() => early.workspace.sageViewBackButton.dispatch('click'));
                return new Promise(() => {});
            };
            const left = await within(early.workspace.captureSageViews(early.request()), 'a held 3D start and Back');
            assert.deepStrictEqual([left.complete, left.reason], [false, 'interrupted']);
            early.workspace.destroy();
        });

    await check('A WebGL context lost while a shot encodes ends the shots failed, with the user\'s own roof '
        + '(SV1 round 4)', async () => {
            const kit = sageShotsFixture();
            const { workspace, three } = kit;
            const scene = sageScene(three, { requested: 1, installed: 1 });
            const own = clone(workspace.layerVisibility);
            const encode = workspace._encodeSageShot;
            workspace._encodeSageShot = async canvas => {
                const image = await encode(canvas);
                if (kit.shots.length === 2) scene.lost = true;
                return image;
            };
            // The main view looks down through the roof, so a finished capture would leave the roof off.
            const result = await within(workspace.captureSageViews(kit.request({ views: [kit.views[1], kit.views[0]] })),
                'the capture');
            assert.deepStrictEqual([result.complete, result.reason, result.shots.length], [false, 'no_3d_view', 1]);
            assert.deepStrictEqual([workspace.layerVisibility.overhead, workspace.layerVisibility.roofSheeting],
                [own.overhead, own.roofSheeting], 'the user\'s own roof comes back');
            workspace.destroy();
        });

    await check('The chat stops a capture it no longer waits for (Stop, or the tool\'s wait over): at once, with the '
        + 'user\'s own roof, and the next capture is not busy (SV2/SV3 round 2)', async () => {
            const kit = sageShotsFixture();
            const { workspace } = kit;
            const own = clone(workspace.layerVisibility);
            const open = kit.gate();   // the first view's settle wait, held
            const id = 'cd'.repeat(16);
            const taking = workspace.captureSageViews(kit.request({ requestId: id }));
            await until(() => kit.waits.length === 1);
            assert.strictEqual(workspace.layerVisibility.overhead, false, 'the roof is off for the shot');
            assert.strictEqual(workspace.stopSageCapture('ef'.repeat(16)), false, 'another request: not this one');
            assert.strictEqual(workspace.stopSageCapture(id), true);
            assert.deepStrictEqual([workspace.sageCapture, workspace.sageShotsStatus.hidden,
                workspace.layerVisibility.overhead], [null, true, own.overhead], 'released at once, the user\'s roof');
            const stopped = await within(taking, 'a stopped capture');
            assert.deepStrictEqual([stopped.complete, stopped.reason, stopped.shots.length], [false, 'interrupted', 0]);
            open();
            assert.strictEqual(workspace.sageViewBackButton.hidden, false, 'Back still returns to the user\'s view');
            const next = await within(workspace.captureSageViews(kit.request()), 'the next capture');
            assert.deepStrictEqual([next.complete, next.reason], [true, null], 'not busy');
            assert.strictEqual(workspace.stopSageCapture(id), false, 'nothing left to stop');
            workspace.destroy();
        });

    await check('a layout placing an asset this page has not heard of loads the catalog again, once per asset '
        + '(basic shapes BS2)', async () => {
            const bollard = { assetId: 'asset-authored-bollard-1200mm-0123456789',
                assetDefinitionRevision: 'revision-asset-authored-bollard-1200mm-0123456789',
                displayName: 'Bollard 1.2 m', category: 'Safety' };
            const tank = { assetId: 'asset-authored-tank-2000mm-0123456789',
                assetDefinitionRevision: 'revision-asset-authored-tank-2000mm-0123456789',
                displayName: 'Tank 2 m', category: 'Utilities' };
            const loads = [];
            const data = fixture({
                loadAssetCatalog() {
                    return new Promise((resolve, reject) => loads.push({ resolve, reject }));
                },
            });
            const show = function (...placements) {
                const next = clone(data.session.state.layout);
                next.placements = next.placements.concat(placements);
                data.session.state.layout = next;
                data.session._notify();
            };
            const cards = () => data.workspace.assetGrid.querySelectorAll('.ip-flw-asset-card')
                .map(card => card.getAttribute('data-asset-id'));
            const older = Object.assign(placement('pl-rack-old', 'asset-rack', 3, 3),
                { assetDefinitionRevision: 'revision-older' });
            show(older);
            await until(() => data.workspace.assetCatalogRefresh === null);
            assert.strictEqual(loads.length, 0, 'a known asset at an older revision is no reason to load');
            show(placement('pl-bollard-1', bollard.assetId, 6, 1));
            await until(() => loads.length === 1);
            show(placement('pl-tank-1', tank.assetId, 8, 1));
            show(placement('pl-bollard-2', bollard.assetId, 6, 2));
            await Promise.resolve();
            assert.strictEqual(loads.length, 1, 'one load at a time');
            loads[0].resolve(catalog().concat([bollard]));
            await until(() => loads.length === 2);
            assert.ok(data.workspace.assetCatalog.some(record => record.assetId === bollard.assetId));
            assert.deepStrictEqual(data.controller.catalogs[data.controller.catalogs.length - 1].map(row => row.assetId),
                ['asset-rack', 'asset-forklift', 'asset-machine', bollard.assetId], 'the 2D and 3D views have it');
            assert.ok(cards().includes(bollard.assetId), 'and so has the asset browser');
            const warnings = [];
            const warn = console.warn;
            console.warn = (...args) => warnings.push(args.join(' '));
            try {
                loads[1].reject(new Error('offline'));
                await until(() => data.workspace.assetCatalogRefresh === null);
            } finally {
                console.warn = warn;
            }
            assert.deepStrictEqual(warnings, ['The asset catalog could not be loaded again: Error: offline']);
            assert.ok(!data.workspace.assetCatalog.some(record => record.assetId === tank.assetId));
            show(placement('pl-bollard-3', bollard.assetId, 6, 3));
            await until(() => loads.length === 3);
            loads[2].resolve(catalog().concat([bollard, tank]));
            await until(() => data.workspace.assetCatalogRefresh === null);
            assert.ok(cards().includes(tank.assetId), 'a failed load is tried again with the next layout');
            show(placement('pl-gone', 'asset-removed-from-the-library', 9, 9));
            await until(() => loads.length === 4);
            loads[3].resolve(catalog().concat([bollard, tank]));
            await until(() => data.workspace.assetCatalogRefresh === null);
            show(placement('pl-gone-2', 'asset-removed-from-the-library', 9, 8));
            await until(() => data.workspace.assetCatalogRefresh === null);
            assert.strictEqual(loads.length, 4, 'an asset the server does not have either is asked for once');
            data.workspace.destroy();
        });

    process.stdout.write(`${checks}/${checks} facility layout workspace checks passed\n`);
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
