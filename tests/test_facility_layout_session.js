'use strict';

const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const MODULE_PATH = path.join(ROOT, 'static', 'facility_layout_session.js');
const facilitySession = require(MODULE_PATH);
const constructionAdapter = require('../static/facility_layout_command_adapter.js');
const constructionContract = require('../static/contracts/facility-construction-commands-v1.json');
const facilityPatterns = require(path.join(
    ROOT,
    'static',
    'facility_layout_patterns.js'
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
    return JSON.parse(JSON.stringify(value));
}

function canonicalValue(value) {
    if (Array.isArray(value)) return value.map(canonicalValue);
    if (!value || typeof value !== 'object') return value;
    const result = {};
    Object.keys(value).sort().forEach(key => {
        result[key] = canonicalValue(value[key]);
    });
    return result;
}

function canonicalHash(value) {
    return crypto.createHash('sha256')
        .update(JSON.stringify(canonicalValue(value)), 'utf8')
        .digest('hex');
}

function placement(placementId, assetId, x, z, positionMode) {
    return {
        placementId,
        assetId,
        assetDefinitionRevision: 'asset-revision-' + assetId,
        transform: {
            position: { x, y: 0, z },
            quaternion: { x: 0, y: 0, z: 0, w: 1 },
            scale: 1,
        },
        positionMode: positionMode || 'auto',
        snapRelationship: null,
        metadata: { instanceLabel: placementId },
    };
}

function layout() {
    return {
        schemaVersion: 1,
        layoutId: 'fl-session-test',
        displayName: 'Session Test',
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
        zones: [],
        floorMarkings: [],
        placements: [
            placement('pl-a', 'asset-a', 1, 1, 'auto'),
            placement('pl-b', 'asset-b', 4, 2, 'auto'),
            placement('pl-locked', 'asset-c', 8, 3, 'locked'),
        ],
        routes: [],
        utilityNetworks: [],
        processBindings: [],
        dismissedSuggestions: [],
        createdAt: '2026-07-29T00:00:00Z',
        updatedAt: '2026-07-29T00:00:00Z',
    };
}

function operationError(code, message, details) {
    const error = new Error(message);
    error.code = code;
    error.details = details || {};
    return error;
}

function generatedId(prefix, index) {
    return `${prefix}-server-${String(index).padStart(3, '0')}`;
}

function findPlacement(document, placementId) {
    const result = document.placements.find(item => item.placementId === placementId);
    if (!result) throw operationError('unknown_placement', 'Unknown placement');
    return result;
}

function findFloorMarking(document, markingId) {
    const result = (document.floorMarkings || []).find(
        item => item.markingId === markingId
    );
    if (!result) throw operationError('unknown_floor_marking', 'Unknown floor marking');
    return result;
}

function findRoute(document, routeId) {
    const result = (document.routes || []).find(item => item.routeId === routeId);
    if (!result) throw operationError('unknown_route', 'Unknown route');
    return result;
}

function applyFakeOperations(base, operations) {
    const document = clone(base);
    const createdIds = [];
    operations.forEach((operation, index) => {
        switch (operation.op) {
        case 'place_asset': {
            const value = clone(operation.placement);
            value.placementId = value.placementId || generatedId('pl', index);
            if (document.placements.some(item => item.placementId === value.placementId)) {
                throw operationError('duplicate_id', 'Duplicate placement');
            }
            document.placements.push(value);
            createdIds.push(value.placementId);
            break;
        }
        case 'move_placement': {
            const value = findPlacement(document, operation.placementId);
            if (value.positionMode === 'locked') {
                throw operationError('locked_placement_movement', 'Placement is locked');
            }
            value.transform.position = clone(operation.position);
            if (operation.movementKind === 'user' && value.positionMode === 'auto') {
                value.positionMode = 'manual';
            }
            break;
        }
        case 'rotate_placement': {
            const value = findPlacement(document, operation.placementId);
            if (value.positionMode === 'locked') {
                throw operationError('locked_placement_movement', 'Placement is locked');
            }
            value.transform.quaternion = clone(operation.quaternion);
            if (operation.movementKind === 'user' && value.positionMode === 'auto') {
                value.positionMode = 'manual';
            }
            break;
        }
        case 'duplicate_placement': {
            const source = clone(findPlacement(document, operation.sourcePlacementId));
            source.placementId = operation.newPlacementId || generatedId('pl', index);
            source.positionMode = operation.positionMode || 'manual';
            source.snapRelationship = null;
            if (Object.prototype.hasOwnProperty.call(
                operation, 'snapRelationship'
            )) {
                source.snapRelationship = clone(operation.snapRelationship);
            }
            if (operation.position) source.transform.position = clone(operation.position);
            if (operation.quaternion) source.transform.quaternion = clone(operation.quaternion);
            if (operation.layoutProvenance) {
                source.metadata = source.metadata || {};
                source.metadata.layoutProvenance = clone(
                    operation.layoutProvenance
                );
            }
            document.placements.push(source);
            createdIds.push(source.placementId);
            break;
        }
        case 'delete_placement':
            findPlacement(document, operation.placementId);
            document.placements = document.placements.filter(
                item => item.placementId !== operation.placementId
            );
            break;
        case 'set_appearance':
            operation.placementIds.forEach(id => {
                const p = findPlacement(document, id);
                if (operation.color === null) delete p.appearance;
                else p.appearance = {color: operation.color.toLowerCase()};
            });
            break;
        case 'set_position_mode':
            findPlacement(document, operation.placementId).positionMode =
                operation.positionMode;
            break;
        case 'set_snap_relationship':
            findPlacement(document, operation.placementId).snapRelationship =
                clone(operation.snapRelationship);
            break;
        case 'add_zone': {
            const zone = clone(operation.zone);
            zone.zoneId = zone.zoneId || generatedId('zn', index);
            document.zones.push(zone);
            createdIds.push(zone.zoneId);
            break;
        }
        case 'edit_zone': {
            const zone = document.zones.find(item => item.zoneId === operation.zoneId);
            if (!zone) throw operationError('unknown_zone', 'Unknown zone');
            Object.assign(zone, clone(operation.patch));
            break;
        }
        case 'delete_zone':
            if (!document.zones.some(item => item.zoneId === operation.zoneId)) {
                throw operationError('unknown_zone', 'Unknown zone');
            }
            document.zones = document.zones.filter(
                item => item.zoneId !== operation.zoneId
            );
            break;
        case 'add_floor_marking': {
            const value = clone(operation.floorMarking);
            value.markingId = value.markingId || generatedId('fm', index);
            document.floorMarkings = document.floorMarkings || [];
            document.floorMarkings.push(value);
            createdIds.push(value.markingId);
            break;
        }
        case 'edit_floor_marking': {
            const value = findFloorMarking(document, operation.markingId);
            Object.assign(value, clone(operation.patch));
            break;
        }
        case 'delete_floor_marking':
            findFloorMarking(document, operation.markingId);
            document.floorMarkings = document.floorMarkings.filter(
                item => item.markingId !== operation.markingId
            );
            break;
        case 'add_aisle': {
            const aisle = clone(operation.aisle);
            const routeId = operation.routeId || generatedId('rt', index);
            const routeKind = aisle.aisleKind === 'pedestrian'
                ? 'operator' : aisle.aisleKind;
            document.routes.push({
                routeId,
                label: aisle.label,
                routeKind,
                sourceEndpoint: {
                    kind: 'world_point',
                    position: clone(aisle.centerline[0]),
                },
                targetEndpoint: {
                    kind: 'world_point',
                    position: clone(aisle.centerline[aisle.centerline.length - 1]),
                },
                routingMode: aisle.aisleKind === 'forklift'
                    ? 'vehicle' : 'polyline',
                centerline: clone(aisle.centerline),
                corridorWidth: aisle.corridorWidth,
                routeFingerprint: 'f'.repeat(64),
                sourceRevisions: { layoutBaseRevision: 'a'.repeat(64) },
                requirements: [],
                evidence: [],
                extensions: {
                    facilityAisle: {
                        schemaVersion: 1,
                        aisleKind: aisle.aisleKind,
                        direction: aisle.direction,
                        color: aisle.color,
                        clearanceEvidenceStatus:
                            aisle.clearanceEvidenceStatus || 'unverified',
                    },
                },
            });
            createdIds.push(routeId);
            break;
        }
        case 'edit_aisle': {
            const route = findRoute(document, operation.routeId);
            const patch = clone(operation.patch);
            if (patch.label !== undefined) route.label = patch.label;
            if (patch.centerline !== undefined) {
                route.centerline = patch.centerline;
                route.sourceEndpoint.position = clone(patch.centerline[0]);
                route.targetEndpoint.position = clone(
                    patch.centerline[patch.centerline.length - 1]
                );
            }
            if (patch.corridorWidth !== undefined) {
                route.corridorWidth = patch.corridorWidth;
            }
            ['aisleKind', 'direction', 'color', 'clearanceEvidenceStatus']
                .forEach(key => {
                    if (patch[key] !== undefined) {
                        route.extensions.facilityAisle[key] = patch[key];
                    }
                });
            route.routeFingerprint = 'e'.repeat(64);
            break;
        }
        case 'delete_route':
            findRoute(document, operation.routeId);
            document.routes = document.routes.filter(
                item => item.routeId !== operation.routeId
            );
            break;
        case 'set_plan_settings':
            document.extensions = document.extensions || {};
            document.extensions.facilityPlan = clone(operation.planSettings);
            break;
        case 'set_facility_navigation':
            if (!['plan_pointer', 'sage_semantic'].includes(
                operation.authoringSource
            )) {
                throw operationError(
                    'facility_navigation_coordinate_authority_forbidden',
                    'Navigation coordinates require the Plan pointer surface'
                );
            }
            document.extensions = document.extensions || {};
            document.extensions.facilityNavigation = clone(
                operation.facilityNavigation
            );
            break;
        case 'clear_layout_contents':
            document.zones = [];
            document.floorMarkings = [];
            document.placements = [];
            document.routes = [];
            document.utilityNetworks = [];
            document.processBindings = [];
            document.dismissedSuggestions = [];
            break;
        default:
            throw operationError('unknown_operation', operation.op);
        }
        (operation.layoutProvenanceSeedEntityIds || []).forEach(entityId => {
            const placementValue = document.placements.find(
                item => item.placementId === entityId
            );
            const zoneValue = document.zones.find(
                item => item.zoneId === entityId
            );
            const markingValue = (document.floorMarkings || []).find(
                item => item.markingId === entityId
            );
            const target = placementValue || zoneValue || markingValue;
            if (!target) throw operationError('unknown_entity', 'Unknown entity');
            const container = zoneValue ? 'extensions' : 'metadata';
            target[container] = target[container] || {};
            target[container].layoutProvenance = clone(
                operation.layoutProvenance
            );
        });
    });
    return { document, createdIds };
}

function fakeAuthority(initialLayout, options) {
    const config = options || {};
    let canonical = clone(initialLayout);
    let revisionCounter = 1;
    let revision = 'rev-1';
    const previewCalls = [];
    const applyCalls = [];
    const reloadCalls = [];
    const candidatePreviewCalls = [];

    function receipt(document, createdIds, currentRevision, changed) {
        return {
            layout: clone(document),
            revision: currentRevision,
            changed: changed !== false,
            operationResult: {
                document: clone(document),
                createdIds: createdIds.slice(),
                affectedIds: [],
                findings: [],
            },
        };
    }

    return {
        previewCalls,
        applyCalls,
        reloadCalls,
        candidatePreviewCalls,
        get revision() { return revision; },
        get layout() { return clone(canonical); },
        makeSession() {
            return facilitySession.createSession({
                previewOperations: async (request) => {
                    previewCalls.push(clone(request));
                    if (request.baseRevision !== revision) {
                        throw operationError('revision_conflict', 'Stale preview', {
                            currentRevision: revision,
                        });
                    }
                    if (config.previewFailure) throw config.previewFailure;
                    const result = applyFakeOperations(canonical, request.operations);
                    return receipt(
                        result.document,
                        result.createdIds,
                        revision,
                        JSON.stringify(result.document) !== JSON.stringify(canonical)
                    );
                },
                applyOperations: async (request) => {
                    applyCalls.push(clone(request));
                    if (request.baseRevision !== revision) {
                        throw operationError('revision_conflict', 'Stale save', {
                            currentRevision: revision,
                        });
                    }
                    const result = applyFakeOperations(canonical, request.operations);
                    canonical = result.document;
                    revisionCounter += 1;
                    revision = 'rev-' + revisionCounter;
                    return receipt(canonical, result.createdIds, revision);
                },
                reloadLayout: async () => {
                    reloadCalls.push(true);
                    return receipt(canonical, [], revision);
                },
                placementCandidates: config.placementCandidates,
                createLayoutProposals: config.createLayoutProposals,
                getLayoutProposalPreview:
                    config.getLayoutProposalPreview,
                cancelLayoutProposal: config.cancelLayoutProposal,
                approveLayoutProposal: config.approveLayoutProposal,
                applyLayoutProposal: config.applyLayoutProposal,
                undoGenerationDraft: config.undoGenerationDraft,
                saveGenerationDraft: config.saveGenerationDraft,
                prepareDesignProposalApply:
                    config.prepareDesignProposalApply,
                commitDesignProposalApply:
                    config.commitDesignProposalApply,
                acknowledgeDesignProposalApply:
                    config.acknowledgeDesignProposalApply,
                recoverDesignProposalApply:
                    config.recoverDesignProposalApply,
                saveDesignProposalDraft:
                    config.saveDesignProposalDraft,
                prepareDesignUndo: config.prepareDesignUndo,
                acknowledgeDesignUndo: config.acknowledgeDesignUndo,
                loadDesignUndoRecovery: config.loadDesignUndoRecovery,
                persistDesignUndoRecovery:
                    config.persistDesignUndoRecovery,
                clearDesignUndoRecovery: config.clearDesignUndoRecovery,
                createIdempotencyKey: config.createIdempotencyKey,
                placementCandidatePreview: async request => {
                    candidatePreviewCalls.push(clone(request));
                    if (request.baseRevision !== revision) {
                        throw operationError(
                            'revision_conflict',
                            'Stale candidate preview',
                            { currentRevision: revision }
                        );
                    }
                    if (config.candidatePreviewFailure) {
                        throw config.candidatePreviewFailure;
                    }
                    if (typeof config.placementCandidatePreview === 'function') {
                        return config.placementCandidatePreview(
                            clone(request),
                            clone(canonical)
                        );
                    }
                    const sourceReceipt = clone(
                        config.candidateReceipt
                        || SPATIAL_FIXTURE.candidateReceipt
                    );
                    const sourceCandidate = sourceReceipt.candidates.find(
                        item => item.candidateId === request.candidateId
                    );
                    if (!sourceCandidate) {
                        throw operationError(
                            'spatial_candidate_stale',
                            'Candidate is unavailable'
                        );
                    }
                    const operationSource = sourceCandidate.operations
                        || SPATIAL_FIXTURE.candidateReceipt.candidates.find(
                            item => item.candidateId === request.candidateId
                        ).operations;
                    const operation = clone(operationSource[0]);
                    const candidate = clone(sourceCandidate);
                    delete candidate.operations;
                    const result = applyFakeOperations(
                        canonical,
                        request.operations.concat([operation])
                    );
                    return {
                        baseRevision: config.candidatePreviewRevision
                            || revision,
                        candidate,
                        operation,
                        preview: {
                            document: result.document,
                            createdIds: result.createdIds,
                            spatialDiagnostics: {
                                valid: true,
                                safetyStatus: candidate.safetyStatus,
                                findings: clone(candidate.findings || []),
                                metrics: clone(candidate.metrics || {}),
                            },
                        },
                    };
                },
            });
        },
        initialReceipt() {
            return receipt(canonical, [], revision);
        },
        externalSave(mutator) {
            canonical = clone(mutator(clone(canonical)));
            revisionCounter += 1;
            revision = 'rev-' + revisionCounter;
        },
    };
}

function byId(document, id) {
    return document.placements.find(item => item.placementId === id);
}

function layoutBinding(revision, suffix) {
    return {
        target: {
            domain: 'facility-layout',
            scopeId: 'site-a',
            resourceId: 'fl-session-test',
        },
        baseRevision: revision,
        diffHash: String(suffix || 'd').repeat(64),
        dependencyFingerprint: 'e'.repeat(64),
    };
}

function fullLayoutProposalReceipt(base, revision) {
    function alternative(index, strategy, x) {
        const previewLayout = clone(base);
        previewLayout.placements[0].transform.position.x = x;
        return {
            proposalId: 'proposal-' + index,
            alternativeId: 'alternative-' + index,
            strategy,
            operations: [{
                op: 'move_placement',
                placementId: 'pl-a',
                position: { x, y: 0, z: 1 },
                movementKind: 'automatic',
            }],
            ghostPreview: {
                layout: previewLayout,
                routeProposals: [],
            },
            metrics: {
                placementCollisions: 0,
                movedAutoCount: 1,
            },
            transactionBinding: layoutBinding(
                revision,
                index === 1 ? 'd' : 'c'
            ),
            createdAt: 1785283200,
            expiresAt: 1785283800,
        };
    }
    const alternatives = [
        alternative(1, 'compact_rows', 10),
        alternative(2, 'balanced_grid', 20),
    ];
    return {
        previewPure: true,
        layoutRevision: revision,
        selectedProposalId: alternatives[0].proposalId,
        alternatives,
    };
}

function replacementLayoutProposalReceipt(base, revision) {
    const previewLayout = clone(base);
    previewLayout.zones = [];
    previewLayout.floorMarkings = [];
    previewLayout.placements = [];
    previewLayout.routes = [];
    previewLayout.utilityNetworks = [];
    previewLayout.processBindings = [];
    previewLayout.dismissedSuggestions = [];
    const alternative = {
        proposalId: 'proposal-replacement-1',
        alternativeId: 'alternative-replacement-1',
        strategy: 'balanced_grid',
        operations: [{ op: 'clear_layout_contents' }],
        ghostPreview: {
            layout: previewLayout,
            routeProposals: [],
        },
        metrics: {
            placementCollisions: 0,
            movedAutoCount: 0,
        },
        transactionBinding: layoutBinding(revision, 'b'),
        createdAt: 1785283200,
        expiresAt: 1785283800,
    };
    return {
        previewPure: true,
        layoutRevision: revision,
        selectedProposalId: alternative.proposalId,
        alternatives: [alternative],
    };
}

function fullLayoutRequest() {
    return {
        schemaVersion: 1,
        requestId: 'request-full-layout-001',
        objective: 'place_and_cleanup',
        assetSet: [{
            itemId: 'existing-pl-a',
            assetId: 'asset-a',
            assetDefinitionRevision: 'asset-revision-asset-a',
            quantity: 1,
            stage: 0,
            existingPlacementId: 'pl-a',
        }],
        strategies: ['compact_rows', 'balanced_grid'],
        maximumAlternatives: 2,
        spacingMeters: 1,
        cleanup: {
            enabled: true,
            moveAuto: true,
            movableManualPlacementIds: [],
        },
        zoneSizing: [],
        routes: [],
        sourceRevisions: {},
    };
}

async function main() {
    await check('appearance is one multi-selection gesture with undo redo reset and no Save', async () => {
        const authority = fakeAuthority(layout());
        const session = authority.makeSession();
        session.load(authority.initialReceipt());
        const original = session.getState().layout;
        session.selectMany(['pl-a', 'pl-locked']);
        await session.setSelectedAppearance('#2478BC');
        const colored = session.getState();
        assert.equal(colored.history.length, 1);
        assert.equal(colored.dirty, true);
        assert.deepEqual(colored.selection, ['pl-a', 'pl-locked']);
        assert.equal(colored.layout.placements[0].appearance.color, '#2478bc');
        assert.equal(colored.layout.placements[2].appearance.color, '#2478bc');
        assert.deepEqual(colored.layout.placements[1], original.placements[1]);
        await session.undo();
        assert.deepEqual(session.getState().layout, original);
        await session.redo();
        assert.deepEqual(session.getState().layout, colored.layout);
        await session.setSelectedAppearance('#2478bc');
        assert.equal(session.getState().history.length, 1);
        await session.setSelectedAppearance(null);
        assert.deepEqual(session.getState().layout, original);
        await assert.rejects(session.setSelectedAppearance('red'), /six-digit/);
    });
    await check('sheet deletion locks mutation until resolved and preserves the prior draft', async () => {
        const authority = fakeAuthority(layout()), session = authority.makeSession();
        session.load(authority.initialReceipt());
        session.select('pl-a');
        await session.moveSelected({ x: 1, y: 0, z: 0 });
        const before = session.getState();
        assert.throws(() => session.beginSheetDeletion('stale'), /changed/);
        const release = session.beginSheetDeletion(before.draftRevision);
        assert.strictEqual(session.getState().busy, true);
        await assert.rejects(session.renameLayout('Blocked'), /busy/);
        await assert.rejects(session.save(), /busy/);
        await assert.rejects(session.undo(), /busy/);
        assert.throws(() => session.discard(), /busy/);
        release(); release();
        assert.deepStrictEqual(session.getState(), before);
    });
    await check('exports UMD and CommonJS API', async () => {
        assert.strictEqual(facilitySession.apiVersion, 1);
        assert.strictEqual(typeof facilitySession.createSession, 'function');
        const source = fs.readFileSync(MODULE_PATH, 'utf8');
        const browser = {};
        vm.runInNewContext(source, { window: browser });
        assert.strictEqual(browser.InspectorProFacilitySession.apiVersion, 1);
    });

    await check('load owns immutable base and draft copies', async () => {
        const authority = fakeAuthority(layout());
        const session = authority.makeSession();
        const input = authority.initialReceipt();
        session.load(input);
        input.layout.placements[0].transform.position.x = 999;
        const first = session.getState();
        first.layout.placements[0].transform.position.x = 888;
        assert.strictEqual(session.getState().layout.placements[0].transform.position.x, 1);
        assert.strictEqual(first.dirty, false);
        assert.strictEqual(first.baseRevision, 'rev-1');
    });

    await check('camera and selection remain outside layout and history', async () => {
        const authority = fakeAuthority(layout());
        const session = authority.makeSession();
        session.load(authority.initialReceipt());
        session.setCameraState({ panX: 80, panY: -20, zoom: 1.7 });
        session.select('pl-a');
        session.select('pl-b', { additive: true });
        const state = session.getState();
        assert.deepStrictEqual(state.selection, ['pl-a', 'pl-b']);
        assert.deepStrictEqual(state.camera, { panX: 80, panY: -20, zoom: 1.7 });
        assert.strictEqual(state.history.length, 0);
        assert.strictEqual(state.dirty, false);
        assert.strictEqual(JSON.stringify(state.layout).includes('panX'), false);
    });

    await check('placement uses world coordinates and backend stable ID after camera changes',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.setCameraState({ panX: 10, panY: 20, zoom: 0.5 });
            await session.placeAsset({
                assetId: 'asset-rack',
                assetDefinitionRevision: 'asset-rack-rev',
                worldPosition: { x: 12.5, y: 0, z: -3.25, screenX: 999 },
            });
            const first = session.getState();
            const createdId = first.selection[0];
            assert.strictEqual(createdId, 'pl-server-000');
            assert.deepStrictEqual(byId(first.layout, createdId).transform.position,
                { x: 12.5, y: 0, z: -3.25 });
            assert.strictEqual(first.operations[0].placement.placementId, undefined);
            assert.strictEqual(first.operations[0].placement.transform.position.screenX,
                undefined);
            await session.undo();
            session.setCameraState({ panX: -300, panY: 90, zoom: 2.5 });
            await session.redo();
            assert.deepStrictEqual(byId(session.getState().layout, createdId).transform.position,
                { x: 12.5, y: 0, z: -3.25 });
        });

    await check('asset browser batch placement is one atomic undoable gesture',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.placeAssets([
                {
                    assetId: 'asset-rack',
                    assetDefinitionRevision: 'asset-rack-rev',
                    worldPosition: { x: 8, y: 0, z: 7 },
                    metadata: { inputMethod: 'asset-browser' },
                },
                {
                    assetId: 'asset-machine',
                    assetDefinitionRevision: 'asset-machine-rev',
                    worldPosition: { x: 12, y: 0, z: 7 },
                    metadata: { inputMethod: 'asset-browser' },
                },
            ]);
            const state = session.getState();
            assert.strictEqual(state.history.length, 1);
            assert.strictEqual(state.history[0].label, 'Add assets');
            assert.strictEqual(state.history[0].operationCount, 2);
            assert.strictEqual(state.selection.length, 2);
            assert.strictEqual(state.operations.length, 2);
            assert.ok(state.operations.every(operation =>
                operation.op === 'place_asset'
                && operation.placement.metadata.inputMethod === 'asset-browser'
            ));
            await session.undo();
            assert.strictEqual(session.getState().layout.placements.length, 3);
            await session.redo();
            assert.strictEqual(session.getState().layout.placements.length, 5);
        });

    await check('ghost placement is transient and invalid cancellation changes nothing',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.beginGhostPlacement({
                assetId: 'asset-rack',
                assetDefinitionRevision: 'asset-rack-rev',
            });
            session.updateGhostPlacement({ x: 4, z: 7 }, false);
            const before = session.getState();
            assert.strictEqual(before.dirty, false);
            await session.commitGhostPlacement();
            const after = session.getState();
            assert.strictEqual(after.ghostPlacement, null);
            assert.strictEqual(after.history.length, 0);
            assert.strictEqual(authority.previewCalls.length, 0);
        });

    await check('authoritative alternatives cycle and dismiss byte-identically',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            const before = JSON.stringify(session.getState().layout);
            session.installPlacementAlternatives(
                SPATIAL_FIXTURE.candidateReceipt
            );
            let state = session.getState();
            assert.strictEqual(
                state.placementAlternatives.authority,
                'server-authoritative'
            );
            assert.strictEqual(
                state.ghostPlacement.metadata.candidateId,
                'fsc-grid'
            );
            session.cyclePlacementAlternative(1);
            state = session.getState();
            assert.strictEqual(
                state.ghostPlacement.metadata.candidateId,
                'fsc-boundary'
            );
            assert.strictEqual(JSON.stringify(state.layout), before);
            assert.strictEqual(state.history.length, 0);
            assert.strictEqual(state.dirty, false);
            session.dismissPlacementAlternatives();
            state = session.getState();
            assert.strictEqual(state.placementAlternatives, null);
            assert.strictEqual(state.ghostPlacement, null);
            assert.strictEqual(JSON.stringify(state.layout), before);
        });

    await check('selected candidate preview supplies one exact undoable gesture',
        async () => {
            const candidateReceipt = clone(SPATIAL_FIXTURE.candidateReceipt);
            candidateReceipt.candidates.forEach(candidate => {
                delete candidate.operations;
            });
            const authority = fakeAuthority(layout(), {
                candidateReceipt,
                placementCandidates: async () => clone(candidateReceipt),
            });
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.requestPlacementAlternatives({
                assetId: 'asset-machine',
                assetDefinitionRevision: 'revision-asset-machine',
                requestedPosition: { x: 7, y: 0, z: 3 },
                positionMode: 'manual',
            });
            session.cyclePlacementAlternative(1);
            await session.acceptPlacementAlternative();
            let state = session.getState();
            assert.strictEqual(authority.candidatePreviewCalls.length, 1);
            assert.deepStrictEqual(authority.candidatePreviewCalls[0], {
                baseRevision: 'rev-1',
                operations: [],
                request: {
                    assetId: 'asset-machine',
                    assetDefinitionRevision: 'revision-asset-machine',
                    requestedPosition: { x: 7, y: 0, z: 3 },
                    positionMode: 'manual',
                },
                candidateId: 'fsc-boundary',
            });
            assert.strictEqual(state.history.length, 1);
            assert.strictEqual(
                state.history[0].label,
                'Accept placement alternative'
            );
            assert.strictEqual(state.operations.length, 1);
            assert.strictEqual(state.operations[0].op, 'place_asset');
            assert.ok(byId(state.layout, 'pl-candidate-boundary'));
            assert.deepStrictEqual(state.selection, ['pl-candidate-boundary']);
            assert.strictEqual(state.placementAlternatives, null);
            assert.strictEqual(state.ghostPlacement, null);
            await session.undo();
            state = session.getState();
            assert.strictEqual(
                byId(state.layout, 'pl-candidate-boundary'),
                undefined
            );
            assert.strictEqual(state.history.length, 1);
            assert.strictEqual(state.historyCursor, 0);
        });

    await check('candidate lists may omit operations but supplied operations stay ordinary',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            const before = JSON.stringify(session.getState().layout);
            const stale = clone(SPATIAL_FIXTURE.candidateReceipt);
            stale.baseRevision = 'rev-stale';
            assert.throws(
                () => session.installPlacementAlternatives(stale),
                error => error.code === 'stale_revision'
            );
            const missingOperations = clone(
                SPATIAL_FIXTURE.candidateReceipt
            );
            missingOperations.candidates.forEach(candidate => {
                delete candidate.operations;
            });
            session.installPlacementAlternatives(
                missingOperations,
                {
                    assetId: 'asset-machine',
                    assetDefinitionRevision: 'revision-asset-machine',
                    requestedPosition: { x: 7, y: 0, z: 3 },
                }
            );
            assert.strictEqual(
                session.getState().placementAlternatives
                    .candidates[0].operations,
                null
            );
            session.dismissPlacementAlternatives();
            const candidateOnlyOperation = clone(
                SPATIAL_FIXTURE.candidateReceipt
            );
            candidateOnlyOperation.candidates[0].operations = [{
                op: 'accept_spatial_candidate',
                candidateId: 'fsc-grid',
            }];
            assert.throws(
                () => session.installPlacementAlternatives(
                    candidateOnlyOperation
                ),
                /ordinary operation/
            );
            assert.strictEqual(JSON.stringify(session.getState().layout), before);
            assert.strictEqual(session.getState().dirty, false);
        });

    await check('failed or stale candidate preview cannot mutate the draft',
        async () => {
            const candidateReceipt = clone(SPATIAL_FIXTURE.candidateReceipt);
            candidateReceipt.candidates.forEach(candidate => {
                delete candidate.operations;
            });
            for (const previewConfig of [
                {
                    candidateReceipt,
                    candidatePreviewFailure: operationError(
                        'spatial_preview_failed',
                        'Preview unavailable'
                    ),
                },
                {
                    candidateReceipt,
                    candidatePreviewRevision: 'rev-stale',
                },
            ]) {
                previewConfig.placementCandidates =
                    async () => clone(candidateReceipt);
                const authority = fakeAuthority(layout(), previewConfig);
                const session = authority.makeSession();
                session.load(authority.initialReceipt());
                await session.requestPlacementAlternatives({
                    assetId: 'asset-machine',
                    assetDefinitionRevision: 'revision-asset-machine',
                    requestedPosition: { x: 7, y: 0, z: 3 },
                });
                const before = session.getState();
                await assert.rejects(
                    session.acceptPlacementAlternative(),
                    error => error.code === 'spatial_preview_failed'
                        || error.code === 'stale_revision'
                );
                const after = session.getState();
                assert.strictEqual(
                    JSON.stringify(after.layout),
                    JSON.stringify(before.layout)
                );
                assert.deepStrictEqual(after.operations, before.operations);
                assert.deepStrictEqual(after.history, before.history);
                assert.strictEqual(after.historyCursor, before.historyCursor);
                assert.strictEqual(after.dirty, before.dirty);
                assert.strictEqual(authority.previewCalls.length, 0);
            }
        });

    await check('candidate request includes current unsaved operations and revision',
        async () => {
            const requests = [];
            const authority = fakeAuthority(layout(), {
                placementCandidates: async request => {
                    requests.push(clone(request));
                    return clone(SPATIAL_FIXTURE.candidateReceipt);
                },
            });
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.select('pl-a');
            await session.moveSelected({ x: 1, y: 0, z: 0 });
            await session.requestPlacementAlternatives({
                assetId: 'asset-machine',
                assetDefinitionRevision: 'revision-asset-machine',
                requestedPosition: { x: 7, y: 0, z: 3 },
            });
            assert.strictEqual(requests.length, 1);
            assert.strictEqual(requests[0].baseRevision, 'rev-1');
            assert.strictEqual(requests[0].operations.length, 1);
            assert.strictEqual(requests[0].operations[0].op, 'move_placement');
            assert.deepStrictEqual(requests[0].request, {
                assetId: 'asset-machine',
                assetDefinitionRevision: 'revision-asset-machine',
                requestedPosition: { x: 7, y: 0, z: 3 },
            });
            assert.ok(session.getState().placementAlternatives);
        });

    await check('one multi-move gesture is one undo entry and marks auto manual',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.selectMany(['pl-a', 'pl-b']);
            await session.moveSelected({ x: 2, y: 0, z: -1 });
            let state = session.getState();
            assert.strictEqual(state.busy, false);
            assert.strictEqual(state.history.length, 1);
            assert.strictEqual(state.operations.length, 2);
            assert.deepStrictEqual(byId(state.layout, 'pl-a').transform.position,
                { x: 3, y: 0, z: 0 });
            assert.deepStrictEqual(byId(state.layout, 'pl-b').transform.position,
                { x: 6, y: 0, z: 1 });
            assert.strictEqual(byId(state.layout, 'pl-a').positionMode, 'manual');
            await session.undo();
            state = session.getState();
            assert.strictEqual(byId(state.layout, 'pl-a').transform.position.x, 1);
            assert.strictEqual(state.canRedo, true);
            await session.redo();
            assert.strictEqual(byId(session.getState().layout, 'pl-a').transform.position.x, 3);
        });

    await check('precise per-placement positions commit as one undo entry',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.selectMany(['pl-a', 'pl-b']);
            await session.movePlacements([
                {
                    placementId: 'pl-a',
                    position: { x: 2.5, y: 0, z: 4 },
                },
                {
                    placementId: 'pl-b',
                    position: { x: 8, y: 0, z: 4 },
                },
            ], 'Align north edges');
            const state = session.getState();
            assert.deepStrictEqual(
                byId(state.layout, 'pl-a').transform.position,
                { x: 2.5, y: 0, z: 4 }
            );
            assert.deepStrictEqual(
                byId(state.layout, 'pl-b').transform.position,
                { x: 8, y: 0, z: 4 }
            );
            assert.strictEqual(state.history.length, 1);
            assert.strictEqual(state.history[0].operationCount, 2);
            assert.strictEqual(state.operations.length, 2);
            assert.ok(state.operations.every(function (operation) {
                return operation.op === 'move_placement'
                    && operation.movementKind === 'user';
            }));
        });

    await check('locked movement failure preserves draft history and selection',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.select('pl-locked');
            const before = session.getState();
            await assert.rejects(
                () => session.moveSelected({ x: 1, z: 0 }),
                error => error.code === 'locked_placement_movement'
            );
            const after = session.getState();
            assert.deepStrictEqual(after.layout, before.layout);
            assert.deepStrictEqual(after.history, before.history);
            assert.deepStrictEqual(after.selection, ['pl-locked']);
            assert.strictEqual(after.dirty, false);
        });

    await check('mixed locked selection rejects atomically', async () => {
        const authority = fakeAuthority(layout());
        const session = authority.makeSession();
        session.load(authority.initialReceipt());
        session.selectMany(['pl-a', 'pl-locked']);
        const before = session.getState();
        await assert.rejects(
            () => session.moveSelected({ x: 2, y: 0, z: 0 }),
            error => error.code === 'locked_placement_movement'
        );
        const after = session.getState();
        assert.deepStrictEqual(after.layout, before.layout);
        assert.deepStrictEqual(after.history, before.history);
        assert.deepStrictEqual(after.operations, before.operations);
        assert.deepStrictEqual(after.selection, ['pl-a', 'pl-locked']);
        assert.strictEqual(after.dirty, false);
    });

    await check('rejected placement clears transient ghost and changes nothing',
        async () => {
            const rejected = operationError(
                'placement_outside_shell',
                'Placement is outside the facility shell'
            );
            const authority = fakeAuthority(layout(), {
                previewFailure: rejected,
            });
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.beginGhostPlacement({
                assetId: 'asset-rack',
                assetDefinitionRevision: 'asset-rack-rev',
            });
            session.updateGhostPlacement({ x: 100, y: 0, z: 100 }, true);
            const before = session.getState().layout;
            await assert.rejects(
                () => session.commitGhostPlacement(),
                error => error.code === 'placement_outside_shell'
            );
            const after = session.getState();
            assert.strictEqual(after.ghostPlacement, null);
            assert.deepStrictEqual(after.layout, before);
            assert.strictEqual(after.history.length, 0);
            assert.strictEqual(after.dirty, false);
        });

    await check('authoritative no-op does not create dirty history', async () => {
        const authority = fakeAuthority(layout());
        const session = authority.makeSession();
        session.load(authority.initialReceipt());
        session.select('pl-locked');
        await session.lockSelected();
        const state = session.getState();
        assert.strictEqual(state.dirty, false);
        assert.strictEqual(state.history.length, 0);
        assert.strictEqual(state.operations.length, 0);
        assert.strictEqual(byId(state.layout, 'pl-locked').positionMode, 'locked');
    });

    await check('rotation, duplicate, lock, and unlock use authoritative operations',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.select('pl-a');
            await session.rotateSelected90();
            let rotated = byId(session.getState().layout, 'pl-a');
            assert.ok(Math.abs(rotated.transform.quaternion.y - Math.SQRT1_2) < 1e-9);
            assert.ok(Math.abs(rotated.transform.quaternion.w - Math.SQRT1_2) < 1e-9);
            await session.duplicateSelected({ x: 3, z: 0 });
            let state = session.getState();
            const duplicateId = state.selection[0];
            assert.strictEqual(duplicateId, 'pl-server-001');
            assert.strictEqual(byId(state.layout, duplicateId).transform.position.x, 4);
            await session.lockSelected();
            assert.strictEqual(byId(session.getState().layout, duplicateId).positionMode,
                'locked');
            await session.unlockSelected();
            assert.strictEqual(byId(session.getState().layout, duplicateId).positionMode,
                'manual');
            assert.strictEqual(session.getState().history.length, 4);
        });

    await check('targeted duplication copies the requested placement in one gesture',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.select('pl-b');
            await session.duplicatePlacements(['pl-a'], { x: 2, y: 0, z: 3 });
            const state = session.getState();
            const duplicateId = state.selection[0];
            assert.strictEqual(duplicateId, 'pl-server-000');
            assert.deepStrictEqual(
                byId(state.layout, duplicateId).transform.position,
                { x: 3, y: 0, z: 4 }
            );
            assert.deepStrictEqual(
                byId(state.layout, 'pl-a').transform.position,
                { x: 1, y: 0, z: 1 }
            );
            assert.strictEqual(state.history.length, 1);
            assert.strictEqual(state.history[0].operationCount, 1);
            assert.strictEqual(state.operations[0].op, 'duplicate_placement');
            assert.strictEqual(state.operations[0].sourcePlacementId, 'pl-a');
        });

    await check('group duplication creates all copies atomically', async () => {
        const authority = fakeAuthority(layout());
        const session = authority.makeSession();
        session.load(authority.initialReceipt());
        await session.duplicatePlacements(
            ['pl-a', 'pl-b'],
            { x: 2, y: 0, z: 3 }
        );
        const state = session.getState();
        assert.deepStrictEqual(
            state.selection,
            ['pl-server-000', 'pl-server-001']
        );
        assert.deepStrictEqual(
            state.selection.map(function (placementId) {
                return byId(state.layout, placementId).transform.position;
            }),
            [
                { x: 3, y: 0, z: 4 },
                { x: 6, y: 0, z: 5 },
            ]
        );
        assert.strictEqual(state.history.length, 1);
        assert.strictEqual(state.history[0].operationCount, 2);
        assert.deepStrictEqual(
            state.operations.map(function (operation) {
                return operation.sourcePlacementId;
            }),
            ['pl-a', 'pl-b']
        );
    });

    await check('delete selected handles placements and zones in one gesture',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.createRectangleZone(
                { x: 0, z: 0 },
                { x: 5, z: 4 },
                { label: 'Cell A' }
            );
            const zoneId = session.getState().selection[0];
            session.selectMany(['pl-a', zoneId]);
            await session.deleteSelected();
            const state = session.getState();
            assert.strictEqual(byId(state.layout, 'pl-a'), undefined);
            assert.strictEqual(state.layout.zones.length, 0);
            assert.deepStrictEqual(state.selection, []);
            assert.strictEqual(state.history[1].operationCount, 2);
        });

    await check('rectangle and polygon zones receive backend IDs and resize deterministically',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.createRectangleZone(
                { x: 4, z: 6 },
                { x: 0, z: 2 },
                { label: 'Assembly Cell', zoneType: 'workcell' }
            );
            const rectangleId = session.getState().selection[0];
            assert.strictEqual(rectangleId, 'zn-server-000');
            await session.editZoneLabel(rectangleId, 'Lathe Cell');
            assert.strictEqual(
                session.getState().layout.zones[0].label,
                'Lathe Cell'
            );
            assert.deepStrictEqual(
                session.getState().operations[1],
                {
                    op: 'edit_zone',
                    zoneId: rectangleId,
                    patch: { label: 'Lathe Cell' },
                }
            );
            await session.editZoneType(rectangleId, 'storage');
            assert.strictEqual(
                session.getState().layout.zones[0].zoneType,
                'storage'
            );
            assert.deepStrictEqual(
                session.getState().operations[2],
                {
                    op: 'edit_zone',
                    zoneId: rectangleId,
                    patch: { zoneType: 'storage' },
                }
            );
            await session.editZoneDimensions(rectangleId, { width: 10, depth: 8 });
            const resized = session.getState().layout.zones[0].boundary;
            assert.deepStrictEqual(resized, [
                { x: -3, z: 0 },
                { x: 7, z: 0 },
                { x: 7, z: 8 },
                { x: -3, z: 8 },
            ]);
            await session.createPolygonZone([
                { x: 0, z: 0 },
                { x: 0, z: 3 },
                { x: 2, z: 3 },
            ], { label: 'Staging', zoneType: 'staging' });
            assert.strictEqual(session.getState().selection.length, 1);
            const polygon = session.getState().layout.zones[1].boundary;
            const signedArea = polygon.reduce((sum, point, index) => {
                const next = polygon[(index + 1) % polygon.length];
                return sum + point.x * next.z - next.x * point.z;
            }, 0);
            assert.ok(signedArea > 0);
            const polygonId = session.getState().selection[0];
            await session.editZoneDimensions(polygonId, { width: 8, depth: 6 });
            const scaled = session.getState().layout.zones[1].boundary;
            assert.strictEqual(scaled.length, 3);
            const xs = scaled.map(point => point.x);
            const zs = scaled.map(point => point.z);
            assert.ok(Math.abs(Math.max(...xs) - Math.min(...xs) - 8) < 1e-9);
            assert.ok(Math.abs(Math.max(...zs) - Math.min(...zs) - 6) < 1e-9);
        });

    await check('bulk zones commit atomically with exact geometry and styling',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.createZones([
                {
                    label: 'Machining',
                    zoneType: 'workcell',
                    minX: 12,
                    minZ: 8,
                    width: 30,
                    depth: 20,
                    extensions: { style: { fillColor: '#336699' } },
                },
                {
                    label: 'Shipping',
                    zoneType: 'shipping',
                    minX: 50,
                    minZ: 8,
                    width: 15,
                    depth: 20,
                },
            ]);
            const state = session.getState();
            assert.strictEqual(state.layout.zones.length, 2);
            assert.strictEqual(state.history.length, 1);
            assert.strictEqual(state.history[0].operationCount, 2);
            assert.strictEqual(state.selection.length, 2);
            assert.deepStrictEqual(state.layout.zones[0].boundary, [
                { x: 12, z: 8 },
                { x: 42, z: 8 },
                { x: 42, z: 28 },
                { x: 12, z: 28 },
            ]);
            assert.strictEqual(
                state.layout.zones[0].extensions.style.fillColor,
                '#336699'
            );
            await session.undo();
            assert.strictEqual(session.getState().layout.zones.length, 0);
        });

    await check('persistent manufacturing cells duplicate and number as one unit',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.selectMany(['pl-a', 'pl-b']);
            await session.createCellGroup({
                baseName: 'Robot Cell',
                prefix: 'A',
                start: 1,
                numberPadding: 2,
                envelopePadding: 0.5,
                minX: 0,
                minZ: 0,
                width: 6,
                depth: 4,
                seriesId: 'cell-series-robot-a',
                functionalInterfaces: {
                    gate: 'south',
                    loading: 'east',
                    service: 'north',
                },
                extensions: { style: { fillColor: '#225588' } },
            });
            const originalZoneId = session.getState().selection[0];
            assert.strictEqual(
                session.getState().layout.zones[0].label,
                'Robot Cell A01'
            );
            assert.strictEqual(
                session.getState().layout.zones[0].extensions.cellGroup
                    .functionalInterfaces.gate.side,
                'south'
            );
            await session.duplicateSelected({ x: 10, y: 0, z: 0 });
            let state = session.getState();
            assert.strictEqual(state.layout.placements.length, 5);
            assert.strictEqual(state.layout.zones.length, 2);
            assert.strictEqual(state.layout.zones[1].label, 'Robot Cell A02');
            assert.strictEqual(
                state.layout.zones[1].extensions.cellGroup.membership,
                'geometric'
            );
            assert.deepStrictEqual(
                Object.fromEntries(Object.entries(
                    state.layout.zones[1].extensions.cellGroup
                        .functionalInterfaces
                ).map(function (entry) {
                    return [entry[0], entry[1].side];
                })),
                { gate: 'south', loading: 'east', service: 'north' }
            );
            assert.ok(Object.values(
                state.layout.zones[1].extensions.cellGroup.functionalInterfaces
            ).every(function (record) {
                return record.evidenceStatus === 'derived';
            }));
            session.select(originalZoneId);
            await session.deleteSelected();
            state = session.getState();
            assert.strictEqual(state.layout.zones.length, 1);
            assert.strictEqual(state.layout.placements.length, 3);
            assert.strictEqual(state.layout.zones[0].label, 'Robot Cell A02');
            await session.ungroupCell(state.layout.zones[0].zoneId);
            state = session.getState();
            assert.strictEqual(state.layout.zones.length, 0);
            assert.strictEqual(state.layout.placements.length, 3);
        });

    await check('floor markings persist as atomic semantic layout objects',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.createFloorMarking({
                markingType: 'keep_clear',
                label: 'Keep clear at CNC-04',
                semanticRole: 'keep_clear',
                transform: {
                    position: { x: 6, y: 0, z: 4 },
                    rotationDegrees: 0,
                },
                width: 3,
                depth: 2,
                fillColor: '#facc15',
                strokeColor: '#111827',
                opacity: 0.9,
                text: 'KEEP CLEAR',
                positionMode: 'manual',
                metadata: { authoredIn: 'facility_plan' },
                evidence: [],
            });
            const markingId = session.getState().selection[0];
            assert.strictEqual(markingId, 'fm-server-000');
            assert.strictEqual(
                session.getState().layout.floorMarkings[0].semanticRole,
                'keep_clear'
            );
            await session.editFloorMarking(markingId, {
                label: 'CNC loading clearance',
                text: 'KEEP CLEAR',
                fillColor: '#ef4444',
            });
            await session.rotateSelected90();
            let state = session.getState();
            assert.strictEqual(
                state.layout.floorMarkings[0].transform.rotationDegrees,
                90
            );
            assert.strictEqual(state.layout.floorMarkings[0].fillColor, '#ef4444');
            await session.duplicateItems([markingId], { x: 4, y: 0, z: 0 });
            state = session.getState();
            assert.strictEqual(state.layout.floorMarkings.length, 2);
            assert.strictEqual(state.history.at(-1).operationCount, 1);
            assert.deepStrictEqual(
                state.layout.floorMarkings[0].transform.position,
                { x: 6, y: 0, z: 4 }
            );
            assert.deepStrictEqual(
                state.layout.floorMarkings[1].transform.position,
                { x: 10, y: 0, z: 4 }
            );
            assert.strictEqual(state.layout.floorMarkings[1].positionMode, 'manual');
            await session.deleteSelected();
            state = session.getState();
            assert.strictEqual(state.layout.floorMarkings.length, 1);
            await session.save();
            assert.strictEqual(authority.layout.floorMarkings.length, 1);
            assert.strictEqual(session.getState().dirty, false);
        });

    await check('semantic aisles create, edit, select, and delete atomically',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.createAisle({
                label: 'Main Forklift Boulevard',
                aisleKind: 'forklift',
                direction: 'two_way',
                color: '#d9a514',
                corridorWidth: 10.668,
                centerline: [
                    { x: 0, y: 0, z: 12 },
                    { x: 40, y: 0, z: 12 },
                ],
                clearanceEvidenceStatus: 'unverified',
            });
            let state = session.getState();
            const routeId = state.selection[0];
            assert.strictEqual(routeId, 'rt-server-000');
            assert.strictEqual(state.layout.routes[0].label, 'Main Forklift Boulevard');
            assert.strictEqual(state.history[0].operationCount, 1);
            await session.editAisle(routeId, {
                corridorWidth: 12,
                direction: 'one_way',
            });
            state = session.getState();
            assert.strictEqual(state.layout.routes[0].corridorWidth, 12);
            assert.strictEqual(
                state.layout.routes[0].extensions.facilityAisle.direction,
                'one_way'
            );
            await session.deleteSelected();
            assert.strictEqual(session.getState().layout.routes.length, 0);
        });

    await check('manual navigation intent is one unsaved undoable gesture',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            const navigation = {
                schemaVersion: 1,
                anchors: [],
                movementPrograms: [],
                manualPathConstraints: [],
                handoffPrograms: [],
            };
            await session.setFacilityNavigation(navigation);
            let state = session.getState();
            assert.strictEqual(state.dirty, true);
            assert.strictEqual(state.history.length, 1);
            assert.strictEqual(state.history[0].operationCount, 1);
            assert.deepStrictEqual(
                state.layout.extensions.facilityNavigation,
                navigation
            );
            assert.strictEqual(
                authority.layout.extensions
                    && authority.layout.extensions.facilityNavigation,
                undefined
            );
            assert.deepStrictEqual(authority.previewCalls[0].operations, [{
                op: 'set_facility_navigation',
                authoringSource: 'plan_pointer',
                facilityNavigation: navigation,
            }]);
            await session.undo();
            state = session.getState();
            assert.strictEqual(state.dirty, false);
            assert.strictEqual(
                state.layout.extensions
                    && state.layout.extensions.facilityNavigation,
                undefined
            );
            await session.redo();
            await session.save();
            assert.deepStrictEqual(
                authority.layout.extensions.facilityNavigation,
                navigation
            );
            assert.strictEqual(session.getState().dirty, false);
        });

    await check('semantic navigation proposal is one unsaved exact Undo',
        async () => {
            const initial = layout();
            initial.extensions = {
                facilityNavigation: {
                    schemaVersion: 1,
                    anchors: [{
                        navigationAnchorId: 'na-existing-home',
                        localPosition: { x: 2, z: 3 },
                    }],
                    movementPrograms: [],
                    manualPathConstraints: [{
                        manualPathConstraintId: 'nmc-existing-guide',
                        authoredPolyline: [
                            { x: 2, z: 3 },
                            { x: 8, z: 3 },
                        ],
                    }],
                    handoffPrograms: [],
                },
            };
            const authority = fakeAuthority(initial);
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            const before = JSON.stringify(session.getState().layout);
            const proposal = clone(
                initial.extensions.facilityNavigation
            );
            proposal.movementPrograms.push({
                movementProgramId: 'nmp-sage-proposal',
                evidenceStatus: 'inferred',
                reviewStatus: 'pending',
            });

            await session.proposeFacilityNavigation(proposal);
            const proposed = session.getState();
            assert.strictEqual(proposed.dirty, true);
            assert.strictEqual(proposed.history.length, 1);
            assert.deepStrictEqual(authority.previewCalls[0].operations, [{
                op: 'set_facility_navigation',
                authoringSource: 'sage_semantic',
                facilityNavigation: proposal,
            }]);
            assert.deepStrictEqual(
                proposed.layout.extensions.facilityNavigation
                    .manualPathConstraints,
                initial.extensions.facilityNavigation.manualPathConstraints
            );
            await session.undo();
            assert.strictEqual(
                JSON.stringify(session.getState().layout),
                before
            );
            assert.strictEqual(session.getState().dirty, false);
        });

    await check('mixed equipment cell pattern is one atomic undoable gesture',
        async () => {
            const initial = layout();
            initial.floorMarkings.push({
                markingId: 'fm-flow',
                markingType: 'direction_arrow',
                label: 'Cell flow',
                semanticRole: 'material_flow',
                transform: {
                    position: { x: 2, y: 0, z: 2 },
                    rotationDegrees: 0,
                },
                width: 0.8,
                depth: 1.6,
                fillColor: '#facc15',
                strokeColor: '#111827',
                opacity: 1,
                text: '',
                positionMode: 'manual',
                metadata: {},
                evidence: [],
            });
            initial.zones.push({
                zoneId: 'zn-cell',
                zoneType: 'workcell',
                label: 'Machining cell',
                boundary: [
                    { x: 0, z: 0 },
                    { x: 5, z: 0 },
                    { x: 5, z: 4 },
                    { x: 0, z: 4 },
                ],
                floorElevation: 0,
                anchors: [{
                    anchorId: 'za-in',
                    anchorKind: 'material',
                    position: { x: 0, y: 0, z: 2 },
                    facing: { x: 1, y: 0, z: 0 },
                    allowedRouteKinds: ['material'],
                    evidence: [],
                }],
                evidence: [],
                extensions: {
                    cellGroup: {
                        schemaVersion: 1,
                        groupKind: 'manufacturing_cell',
                        membership: 'geometric',
                        envelopePadding: 0,
                        autoNumber: {
                            seriesId: 'cell-series-mirror',
                            baseName: 'Machining Cell',
                            prefix: 'A',
                            start: 1,
                            padding: 2,
                            sequence: 1,
                        },
                        functionalInterfaces: {
                            gate: {
                                side: 'east',
                                position: { x: 5, z: 2 },
                                accessEnvelope: [
                                    { x: 5, z: 1.5 },
                                    { x: 6, z: 1.5 },
                                    { x: 6, z: 2.5 },
                                    { x: 5, z: 2.5 },
                                ],
                                evidenceStatus: 'authored',
                            },
                        },
                    },
                },
            });
            const authority = fakeAuthority(initial);
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.applyPattern({
                mode: 'linear',
                copies: [{
                    sourceId: 'pl-a',
                    kind: 'placement',
                    position: { x: 11, y: 0, z: 1 },
                    rotationDegrees: 0,
                    rotationDeltaDegrees: 0,
                    sourceAnchor: { x: 2.5, z: 2 },
                    targetAnchor: { x: 12.5, z: 2 },
                }, {
                    sourceId: 'fm-flow',
                    kind: 'floor-marking',
                    position: { x: 12, y: 0, z: 2 },
                    rotationDegrees: 90,
                    rotationDeltaDegrees: 90,
                    sourceAnchor: { x: 2.5, z: 2 },
                    targetAnchor: { x: 12.5, z: 2 },
                }, {
                    sourceId: 'zn-cell',
                    kind: 'zone',
                    position: { x: 12.5, y: 0, z: 2 },
                    rotationDegrees: 90,
                    rotationDeltaDegrees: 90,
                    sourceAnchor: { x: 2.5, z: 2 },
                    targetAnchor: { x: 12.5, z: 2 },
                    boundary: [
                        { x: 10.5, z: 4.5 },
                        { x: 10.5, z: -0.5 },
                        { x: 14.5, z: -0.5 },
                        { x: 14.5, z: 4.5 },
                    ],
                }],
                moves: [],
            }, 'Linear cell pattern');
            let state = session.getState();
            assert.strictEqual(state.layout.placements.length, 4);
            assert.strictEqual(state.layout.floorMarkings.length, 2);
            assert.strictEqual(state.layout.zones.length, 2);
            assert.strictEqual(state.history.at(-1).operationCount, 3);
            assert.strictEqual(state.selection.length, 3);
            const copiedZone = state.layout.zones[1];
            assert.deepStrictEqual(
                copiedZone.anchors[0].position,
                { x: 12.5, y: 0, z: 4.5 }
            );
            assert.deepStrictEqual(
                copiedZone.anchors[0].facing,
                { x: 0, y: 0, z: -1 }
            );
            assert.strictEqual(
                copiedZone.extensions.cellGroup.functionalInterfaces.gate.side,
                'south'
            );
            assert.deepStrictEqual(
                copiedZone.extensions.cellGroup.functionalInterfaces.gate.position,
                { x: 12.5, z: -0.5 }
            );
            await session.undo();
            state = session.getState();
            assert.strictEqual(state.layout.placements.length, 3);
            assert.strictEqual(state.layout.floorMarkings.length, 1);
            assert.strictEqual(state.layout.zones.length, 1);
        });

    await check('cell pattern remaps copied surface children to copied supports',
        async () => {
            const initial = layout();
            const support = placement(
                'pl-support', 'asset-support', 2, 2, 'manual'
            );
            const child = placement(
                'pl-surface-child', 'asset-surface-child', 2, 2, 'manual'
            );
            child.transform.position.y = 1.2;
            child.snapRelationship = {
                family: 'surface_attachment',
                attachmentId: 'attachment-original',
                supportPlacementId: support.placementId,
                surfaceId: 'worktop',
                side: 'above',
                localPosition: { x: 0, y: 0, z: 0 },
                localRotationDegrees: 0,
                gap: 0,
            };
            initial.placements = [support, child];
            const authority = fakeAuthority(initial);
            const session = authority.makeSession();
            session.load(authority.initialReceipt());

            await session.applyPattern({
                mode: 'linear',
                copies: [{
                    sourceId: support.placementId,
                    kind: 'placement',
                    instanceIndex: 1,
                    position: { x: 12, y: 0, z: 2 },
                    rotationDegrees: 0,
                    rotationDeltaDegrees: 0,
                }, {
                    sourceId: child.placementId,
                    kind: 'placement',
                    instanceIndex: 1,
                    position: { x: 12, y: 1.2, z: 2 },
                    rotationDegrees: 0,
                    rotationDeltaDegrees: 0,
                }],
                moves: [],
            }, 'Linear surface-attached cell pattern');

            const state = session.getState();
            const copiedSupport = state.layout.placements.find(item => (
                item.assetId === support.assetId
                && item.placementId !== support.placementId
            ));
            const copiedChild = state.layout.placements.find(item => (
                item.assetId === child.assetId
                && item.placementId !== child.placementId
            ));
            assert.ok(copiedSupport);
            assert.ok(copiedChild);
            assert.notStrictEqual(
                copiedChild.snapRelationship.attachmentId,
                child.snapRelationship.attachmentId
            );
            assert.strictEqual(
                copiedChild.snapRelationship.supportPlacementId,
                copiedSupport.placementId
            );
            assert.notStrictEqual(
                copiedChild.snapRelationship.supportPlacementId,
                support.placementId
            );
            assert.strictEqual(state.history.at(-1).operationCount, 2);
        });

    await check('mirrored mixed cell is one atomic undoable gesture',
        async () => {
            const initial = layout();
            initial.floorMarkings.push({
                markingId: 'fm-flow',
                markingType: 'direction_arrow',
                label: 'Cell flow',
                semanticRole: 'material_flow',
                transform: {
                    position: { x: 2, y: 0, z: 2 },
                    rotationDegrees: 0,
                },
                width: 0.8,
                depth: 1.6,
                fillColor: '#facc15',
                strokeColor: '#111827',
                opacity: 1,
                text: '',
                positionMode: 'manual',
                metadata: {},
                evidence: [],
            });
            initial.zones.push({
                zoneId: 'zn-cell',
                zoneType: 'workcell',
                label: 'Machining cell',
                boundary: [
                    { x: 0, z: 0 },
                    { x: 6, z: 0 },
                    { x: 6, z: 5 },
                    { x: 0, z: 5 },
                ],
                floorElevation: 0,
                anchors: [{
                    anchorId: 'za-in',
                    anchorKind: 'material',
                    position: { x: 0, y: 0, z: 2 },
                    facing: { x: 1, y: 0, z: 0 },
                    allowedRouteKinds: ['material'],
                    evidence: [],
                }],
                evidence: [],
                extensions: {
                    cellGroup: {
                        schemaVersion: 1,
                        groupKind: 'manufacturing_cell',
                        membership: 'geometric',
                        envelopePadding: 0,
                        autoNumber: {
                            seriesId: 'cell-series-mirror',
                            baseName: 'Machining Cell',
                            prefix: 'A',
                            start: 1,
                            padding: 2,
                            sequence: 1,
                        },
                        functionalInterfaces: {
                            gate: {
                                side: 'east',
                                position: { x: 6, z: 2.5 },
                                accessEnvelope: [
                                    { x: 6, z: 2 },
                                    { x: 7, z: 2 },
                                    { x: 7, z: 3 },
                                    { x: 6, z: 3 },
                                ],
                                evidenceStatus: 'authored',
                            },
                        },
                    },
                },
            });
            const catalog = initial.placements.map(item => ({
                assetId: item.assetId,
                assetDefinitionRevision: item.assetDefinitionRevision,
                width: 2,
                depth: 2,
            }));
            const seed = facilityPatterns.collectSelection(
                initial,
                catalog,
                ['zn-cell'],
                { expandZones: true, includeZones: true }
            );
            const mirror = facilityPatterns.buildMirror(seed, {
                axisStart: { x: 10, z: 0 },
                axisEnd: { x: 10, z: 10 },
            });
            const authority = fakeAuthority(initial);
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.applyPattern(mirror, 'Mirror machining cell');
            let state = session.getState();
            assert.strictEqual(state.layout.placements.length, 5);
            assert.strictEqual(state.layout.floorMarkings.length, 2);
            assert.strictEqual(state.layout.zones.length, 2);
            assert.strictEqual(state.history.at(-1).operationCount, 4);
            assert.strictEqual(state.selection.length, 4);
            assert.strictEqual(state.layout.placements[3].transform.position.x, 19);
            assert.ok(Math.abs(state.layout.placements[3].transform.quaternion.y - 1) < 1e-6);
            assert.ok(Math.abs(state.layout.placements[3].transform.quaternion.w) < 1e-6);
            const copiedZone = state.layout.zones[1];
            assert.deepStrictEqual(
                copiedZone.anchors[0].position,
                { x: 20, y: 0, z: 2 }
            );
            assert.deepStrictEqual(
                copiedZone.anchors[0].facing,
                { x: -1, y: 0, z: 0 }
            );
            assert.strictEqual(
                copiedZone.extensions.cellGroup.functionalInterfaces.gate.side,
                'west'
            );
            assert.deepStrictEqual(
                copiedZone.extensions.cellGroup.functionalInterfaces.gate.position,
                { x: 14, z: 2.5 }
            );
            assert.deepStrictEqual(
                copiedZone.extensions.cellGroup.functionalInterfaces.gate
                    .accessEnvelope,
                [
                    { x: 14, z: 3 },
                    { x: 13, z: 3 },
                    { x: 13, z: 2 },
                    { x: 14, z: 2 },
                ]
            );
            await session.undo();
            state = session.getState();
            assert.strictEqual(state.layout.placements.length, 3);
            assert.strictEqual(state.layout.floorMarkings.length, 1);
            assert.strictEqual(state.layout.zones.length, 1);
        });

    await check('perimeter pattern creates independently editable guarding panels',
        async () => {
            const initial = layout();
            const catalog = initial.placements.map(item => ({
                assetId: item.assetId,
                assetDefinitionRevision: item.assetDefinitionRevision,
                width: 1,
                depth: 0.1,
            }));
            const seed = facilityPatterns.collectSelection(
                initial,
                catalog,
                ['pl-a'],
                { includeZones: false }
            );
            const perimeter = facilityPatterns.buildRectangularPerimeter(seed, {
                widthCount: 3,
                depthCount: 2,
                clearGap: 0,
            });
            const authority = fakeAuthority(initial);
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.applyPattern(perimeter, 'Guarding perimeter');
            let state = session.getState();
            assert.strictEqual(state.layout.placements.length, 12);
            assert.strictEqual(state.selection.length, 9);
            assert.strictEqual(state.history.at(-1).operationCount, 9);
            const removableId = state.selection[0];
            session.select(removableId);
            await session.deleteSelected();
            state = session.getState();
            assert.strictEqual(state.layout.placements.length, 11);
            await session.undo();
            assert.strictEqual(session.getState().layout.placements.length, 12);
        });

    await check('vertical stack is atomic movable duplicable and undoable',
        async () => {
            const initial = layout();
            const catalog = initial.placements.map(item => ({
                assetId: item.assetId,
                assetDefinitionRevision: item.assetDefinitionRevision,
                width: 1,
                depth: 1,
                height: 0.2,
            }));
            const seed = facilityPatterns.collectSelection(
                initial,
                catalog,
                ['pl-a'],
                { includeZones: false }
            );
            const stack = facilityPatterns.buildVerticalStack(seed, {
                count: 3,
                gap: 0,
                stackId: 'stack-session-a',
            });
            const authority = fakeAuthority(initial);
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.select('pl-a');
            await session.applyPattern(stack, 'Vertical stack');
            let state = session.getState();
            assert.strictEqual(state.layout.placements.length, 5);
            assert.deepStrictEqual(
                state.layout.placements.slice(0, 1).concat(
                    state.layout.placements.slice(3)
                ).map(item => item.transform.position.y),
                [0, 0.2, 0.4]
            );
            assert.ok(state.layout.placements.filter(item => (
                item.snapRelationship
                && item.snapRelationship.stackId === 'stack-session-a'
            )).every(item => item.snapRelationship.count === 3));
            await session.moveSelected({ x: 2, y: 0, z: 1 });
            state = session.getState();
            assert.deepStrictEqual(
                state.layout.placements.filter(item => (
                    item.snapRelationship
                    && item.snapRelationship.stackId === 'stack-session-a'
                )).map(item => item.transform.position.x),
                [3, 3, 3]
            );
            await session.duplicateSelected({ x: 4, y: 0, z: 0 });
            state = session.getState();
            assert.strictEqual(state.layout.placements.length, 8);
            const copied = state.layout.placements.filter(item => (
                item.snapRelationship
                && item.snapRelationship.stackId !== 'stack-session-a'
            ));
            assert.strictEqual(copied.length, 3);
            assert.strictEqual(new Set(copied.map(item => (
                item.snapRelationship.stackId
            ))).size, 1);
            await session.undo();
            assert.strictEqual(session.getState().layout.placements.length, 5);
        });

    await check('surface attachments move rotate edit and duplicate with their support',
        async () => {
            const initial = layout();
            const table = placement('pl-table', 'asset-table', 10, 10, 'manual');
            const computer = placement(
                'pl-computer', 'asset-computer', 0, 0, 'manual'
            );
            const keyboard = placement(
                'pl-keyboard', 'asset-keyboard', 0, 0, 'manual'
            );
            const mouse = placement('pl-mouse', 'asset-mouse', 0, 0, 'manual');
            initial.placements.push(table, computer, keyboard, mouse);
            const dimensions = {
                'asset-table': { width: 3.2, depth: 1.8, height: 0.8 },
                'asset-computer': { width: 0.45, depth: 0.35, height: 0.5 },
                'asset-keyboard': { width: 0.55, depth: 0.2, height: 0.04 },
                'asset-mouse': { width: 0.12, depth: 0.08, height: 0.04 },
            };
            const catalog = initial.placements.map(item => Object.assign({
                assetId: item.assetId,
                assetDefinitionRevision: item.assetDefinitionRevision,
            }, dimensions[item.assetId] || { width: 1, depth: 1, height: 1 }));
            const selected = [
                'pl-table', 'pl-computer', 'pl-keyboard', 'pl-mouse',
            ];
            const surface = facilityPatterns.buildSurfaceStack(
                facilityPatterns.collectSelection(
                    initial,
                    catalog,
                    selected,
                    { includeZones: false }
                ),
                {
                    supportPlacementId: 'pl-table',
                    side: 'above',
                    gap: 0,
                    itemGap: 0.1,
                    inset: 0.1,
                    attachmentId: 'surface-session-table',
                }
            );
            const authority = fakeAuthority(initial);
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.selectMany(selected);
            await session.applyPattern(surface, 'Place desktop equipment');
            let state = session.getState();
            const attached = state.layout.placements.filter(item => (
                item.snapRelationship
                && item.snapRelationship.family === 'surface_attachment'
            ));
            assert.strictEqual(attached.length, 3);
            assert.ok(attached.every(item => item.transform.position.y === 0.8));

            const originalLocal = clone(
                attached[0].snapRelationship.localPosition
            );
            session.select('pl-table');
            await session.moveSelected({ x: 2, y: 0, z: 1 });
            state = session.getState();
            assert.deepStrictEqual(
                byId(state.layout, attached[0].placementId)
                    .snapRelationship.localPosition,
                originalLocal
            );
            assert.strictEqual(
                byId(state.layout, attached[0].placementId).transform.position.x,
                attached[0].transform.position.x + 2
            );

            session.select('pl-table');
            await session.rotateSelected90();
            state = session.getState();
            const rotatedChild = byId(state.layout, attached[0].placementId);
            assert.deepStrictEqual(
                rotatedChild.snapRelationship.localPosition,
                originalLocal
            );

            session.select(rotatedChild.placementId);
            await session.movePlacements([{
                placementId: rotatedChild.placementId,
                position: Object.assign({}, rotatedChild.transform.position, {
                    x: rotatedChild.transform.position.x + 0.2,
                }),
            }]);
            state = session.getState();
            assert.notDeepStrictEqual(
                byId(state.layout, rotatedChild.placementId)
                    .snapRelationship.localPosition,
                originalLocal
            );

            session.select('pl-table');
            await session.duplicateSelected({ x: 5, y: 0, z: 0 });
            state = session.getState();
            assert.strictEqual(state.layout.placements.length, 11);
            const copied = state.layout.placements.filter(item => (
                item.snapRelationship
                && item.snapRelationship.family === 'surface_attachment'
                && item.snapRelationship.attachmentId !== 'surface-session-table'
            ));
            assert.strictEqual(copied.length, 3);
            assert.strictEqual(new Set(copied.map(item => (
                item.snapRelationship.supportPlacementId
            ))).size, 1);
            assert.notStrictEqual(
                copied[0].snapRelationship.supportPlacementId,
                'pl-table'
            );
        });

    await check('two complete cells swap positions in one atomic gesture',
        async () => {
            const initial = layout();
            initial.zones.push({
                zoneId: 'zn-left',
                zoneType: 'workcell',
                label: 'Left cell',
                boundary: [
                    { x: 0, z: 0 }, { x: 3, z: 0 },
                    { x: 3, z: 3 }, { x: 0, z: 3 },
                ],
                floorElevation: 0,
                anchors: [],
                evidence: [],
            }, {
                zoneId: 'zn-right',
                zoneType: 'workcell',
                label: 'Right cell',
                boundary: [
                    { x: 8, z: 0 }, { x: 11, z: 0 },
                    { x: 11, z: 3 }, { x: 8, z: 3 },
                ],
                floorElevation: 0,
                anchors: [],
                evidence: [],
            });
            initial.placements[0].transform.position = { x: 1, y: 0, z: 1 };
            initial.placements[1].transform.position = { x: 9, y: 0, z: 1 };
            initial.placements[2].transform.position = { x: 20, y: 0, z: 1 };
            const catalog = initial.placements.map(item => ({
                assetId: item.assetId,
                assetDefinitionRevision: item.assetDefinitionRevision,
                width: 1,
                depth: 1,
            }));
            const swap = facilityPatterns.buildSwap(
                initial,
                catalog,
                ['zn-left', 'zn-right']
            );
            const authority = fakeAuthority(initial);
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.applyPattern(swap, 'Swap cells');
            const state = session.getState();
            assert.strictEqual(state.history.at(-1).operationCount, 6);
            assert.strictEqual(
                state.layout.placements.find(item => item.placementId === 'pl-a')
                    .transform.position.x,
                9
            );
            assert.strictEqual(
                state.layout.placements.find(item => item.placementId === 'pl-b')
                    .transform.position.x,
                1
            );
            assert.deepStrictEqual(
                state.layout.zones.find(item => item.zoneId === 'zn-left')
                    .boundary[0],
                { x: 8, z: 0 }
            );
        });

    await check('plan settings are persisted as one undoable operation',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.setPlanSettings({
                widthMeters: 55,
                depthMeters: 36,
                minorGridMeters: 2,
                majorGridMeters: 10,
            });
            let state = session.getState();
            assert.deepStrictEqual(
                state.layout.extensions.facilityPlan,
                {
                    widthMeters: 55,
                    depthMeters: 36,
                    minorGridMeters: 2,
                    majorGridMeters: 10,
                }
            );
            assert.strictEqual(state.history.at(-1).operationCount, 1);
            await session.undo();
            state = session.getState();
            assert.strictEqual(state.layout.extensions, undefined);
        });

    await check('Clear All removes map content atomically and preserves plan settings',
        async () => {
            const initial = layout();
            initial.extensions = {
                facilityPlan: {
                    widthMeters: 40,
                    depthMeters: 30,
                    minorGridMeters: 1,
                    majorGridMeters: 5,
                },
            };
            initial.zones.push({
                zoneId: 'zn-clear',
                zoneType: 'workcell',
                label: 'Cell',
                boundary: [
                    { x: 0, z: 0 }, { x: 2, z: 0 },
                    { x: 2, z: 2 }, { x: 0, z: 2 },
                ],
                floorElevation: 0,
                anchors: [],
                evidence: [],
            });
            const authority = fakeAuthority(initial);
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.clearLayout();
            let state = session.getState();
            assert.deepStrictEqual(state.layout.placements, []);
            assert.deepStrictEqual(state.layout.zones, []);
            assert.deepStrictEqual(state.layout.extensions, initial.extensions);
            assert.deepStrictEqual(state.selection, []);
            assert.strictEqual(state.history.at(-1).operationCount, 1);
            await session.undo();
            state = session.getState();
            assert.strictEqual(state.layout.placements.length, 3);
            assert.strictEqual(state.layout.zones.length, 1);
            assert.deepStrictEqual(state.layout.extensions, initial.extensions);
        });

    await check('cell layout repositions mixed selected items atomically',
        async () => {
            const initial = layout();
            initial.floorMarkings.push({
                markingId: 'fm-flow',
                markingType: 'solid_line',
                label: 'Flow',
                semanticRole: 'material_flow',
                transform: {
                    position: { x: 3, y: 0, z: 3 },
                    rotationDegrees: 0,
                },
                width: 0.2,
                depth: 2,
                fillColor: '#ffffff',
                strokeColor: '#111827',
                opacity: 1,
                text: '',
                positionMode: 'manual',
                metadata: {},
                evidence: [],
            });
            const authority = fakeAuthority(initial);
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.selectMany(['pl-a', 'pl-b', 'fm-flow']);
            await session.applyPattern({
                mode: 'cell-layout',
                copies: [],
                moves: [{
                    sourceId: 'pl-a', kind: 'placement',
                    position: { x: 0, y: 0, z: 0 }, rotationDegrees: 90,
                }, {
                    sourceId: 'pl-b', kind: 'placement',
                    position: { x: 5, y: 0, z: 5 }, rotationDegrees: 180,
                }, {
                    sourceId: 'fm-flow', kind: 'floor-marking',
                    position: { x: 2.5, y: 0, z: 5 }, rotationDegrees: 90,
                }],
            }, 'U-cell layout');
            const state = session.getState();
            assert.strictEqual(state.history.at(-1).operationCount, 5);
            assert.deepStrictEqual(state.selection, ['pl-a', 'pl-b', 'fm-flow']);
            assert.deepStrictEqual(
                state.layout.placements[0].transform.position,
                { x: 0, y: 0, z: 0 }
            );
            assert.strictEqual(
                state.layout.floorMarkings[0].transform.rotationDegrees,
                90
            );
        });

    await check('new gesture after undo truncates redo history', async () => {
        const authority = fakeAuthority(layout());
        const session = authority.makeSession();
        session.load(authority.initialReceipt());
        session.select('pl-a');
        await session.moveSelected({ x: 1, z: 0 });
        await session.rotateSelected90();
        await session.undo();
        await session.lockSelected();
        const state = session.getState();
        assert.strictEqual(state.history.length, 2);
        assert.strictEqual(state.canRedo, false);
        assert.strictEqual(state.history[1].label, 'Lock selection');
    });

    await check('save sends one flattened batch and resets from canonical receipt',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.select('pl-a');
            await session.moveSelected({ x: 2, z: 0 });
            await session.rotateSelected90();
            const beforeSave = session.getState().layout;
            const result = await session.save();
            assert.strictEqual(authority.applyCalls.length, 1);
            assert.strictEqual(authority.applyCalls[0].baseRevision, 'rev-1');
            assert.strictEqual(authority.applyCalls[0].operations.length, 2);
            assert.strictEqual(result.state.baseRevision, 'rev-2');
            assert.strictEqual(result.state.busy, false);
            assert.strictEqual(result.state.dirty, false);
            assert.strictEqual(result.state.history.length, 0);
            assert.deepStrictEqual(result.state.layout, beforeSave);
            assert.deepStrictEqual(result.state.layout, authority.layout);
            await session.reload();
            assert.deepStrictEqual(session.getState().layout, authority.layout);
            assert.strictEqual(authority.reloadCalls.length, 1);
        });

    await check('discard resets local gestures without applying them', async () => {
        const authority = fakeAuthority(layout());
        const session = authority.makeSession();
        session.load(authority.initialReceipt());
        session.select('pl-a');
        await session.moveSelected({ x: 7, z: 0 });
        session.discard();
        const state = session.getState();
        assert.strictEqual(state.dirty, false);
        assert.strictEqual(state.history.length, 0);
        assert.strictEqual(byId(state.layout, 'pl-a').transform.position.x, 1);
        assert.strictEqual(authority.applyCalls.length, 0);
    });

    await check('stale save records conflict and preserves unsaved operations',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.select('pl-a');
            await session.moveSelected({ x: 1, z: 0 });
            authority.externalSave(document => {
                document.displayName = 'Externally renamed';
                return document;
            });
            await assert.rejects(
                () => session.save(),
                error => error.code === 'revision_conflict'
            );
            const state = session.getState();
            assert.strictEqual(state.dirty, true);
            assert.strictEqual(state.operations.length, 1);
            assert.deepStrictEqual(state.conflict, {
                code: 'revision_conflict',
                currentRevision: 'rev-2',
            });
            assert.strictEqual(state.baseRevision, 'rev-1');
        });

    await check('reload after conflict adopts latest canonical revision and clears history',
        async () => {
            const authority = fakeAuthority(layout());
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.select('pl-a');
            await session.moveSelected({ x: 1, z: 0 });
            authority.externalSave(document => {
                document.placements.push(placement(
                    'pl-external', 'asset-external', 20, 20, 'manual'
                ));
                return document;
            });
            await assert.rejects(() => session.save());
            await session.reload();
            const state = session.getState();
            assert.strictEqual(state.baseRevision, 'rev-2');
            assert.strictEqual(state.dirty, false);
            assert.strictEqual(state.layout.placements.length, 4);
            assert.strictEqual(state.conflict, null);
        });

    await check('full-layout alternatives are read-only and cycle without dirtying',
        async () => {
            const cancelled = [];
            const initial = layout();
            const proposalReceipt = fullLayoutProposalReceipt(
                initial,
                'rev-1'
            );
            const authority = fakeAuthority(initial, {
                createLayoutProposals: async () => clone(proposalReceipt),
                cancelLayoutProposal: async request => {
                    cancelled.push(request.proposalId);
                    return { cancelled: true };
                },
            });
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            const before = session.getState();
            await session.requestLayoutProposal(fullLayoutRequest());
            let state = session.getState();
            assert.strictEqual(state.layoutProposal.selectedIndex, 0);
            assert.strictEqual(
                state.layoutProposal.alternatives[0].createdAt,
                1785283200
            );
            assert.deepStrictEqual(state.layout, before.layout);
            assert.deepStrictEqual(state.baseLayout, before.baseLayout);
            assert.deepStrictEqual(state.operations, []);
            assert.deepStrictEqual(state.history, []);
            assert.strictEqual(state.dirty, false);
            assert.strictEqual(state.baseRevision, 'rev-1');
            session.cycleLayoutProposal(1);
            state = session.getState();
            assert.strictEqual(state.layoutProposal.selectedIndex, 1);
            assert.strictEqual(
                state.layoutProposal.alternatives[1]
                    .ghostPreview.layout.placements[0].transform.position.x,
                20
            );
            assert.deepStrictEqual(state.layout, before.layout);
            await session.dismissLayoutProposal();
            state = session.getState();
            assert.strictEqual(state.layoutProposal, null);
            assert.strictEqual(state.dirty, false);
            assert.deepStrictEqual(cancelled.sort(), [
                'proposal-1',
                'proposal-2',
            ]);
        });

    await check('replacement proposal overlays a dirty draft without mutating it',
        async () => {
            const initial = layout();
            const cancelled = [];
            const authority = fakeAuthority(initial, {
                cancelLayoutProposal: async request => {
                    cancelled.push(request.proposalId);
                    return { cancelled: true };
                },
            });
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.select('pl-a');
            await session.moveSelected({ x: 2, y: 0, z: 0 });
            const dirty = session.getState();
            const receipt = replacementLayoutProposalReceipt(
                initial,
                dirty.baseRevision
            );

            session.installLayoutProposal(receipt, {
                ...fullLayoutRequest(),
                cleanup: {
                    ...fullLayoutRequest().cleanup,
                    replaceExistingContents: true,
                },
            });
            let state = session.getState();
            assert.ok(state.layoutProposal);
            assert.strictEqual(state.dirty, true);
            assert.deepStrictEqual(state.layout, dirty.layout);
            assert.strictEqual(
                state.layoutProposal.alternatives[0]
                    .ghostPreview.layout.placements.length,
                0
            );

            await session.dismissLayoutProposal();
            state = session.getState();
            assert.strictEqual(state.layoutProposal, null);
            assert.strictEqual(state.dirty, true);
            assert.deepStrictEqual(state.layout, dirty.layout);
            assert.deepStrictEqual(cancelled, ['proposal-replacement-1']);
        });

    await check('full-layout approval revalidates and applies with one key',
        async () => {
            const calls = [];
            const initial = layout();
            const proposalReceipt = fullLayoutProposalReceipt(
                initial,
                'rev-1'
            );
            const selected = proposalReceipt.alternatives[0];
            const authority = fakeAuthority(initial, {
                createLayoutProposals: async request => {
                    calls.push(['create', clone(request)]);
                    return clone(proposalReceipt);
                },
                getLayoutProposalPreview: async request => {
                    calls.push(['preview', clone(request)]);
                    return {
                        proposalId: selected.proposalId,
                        alternative: clone(selected),
                        transactionBinding:
                            clone(selected.transactionBinding),
                        createdAt: selected.createdAt,
                        expiresAt: selected.expiresAt,
                        previewPure: true,
                    };
                },
                approveLayoutProposal: async request => {
                    calls.push(['approve', clone(request)]);
                    return { approvalToken: 'approval-token-001' };
                },
                applyLayoutProposal: async request => {
                    calls.push(['apply', clone(request)]);
                    return {
                        layout: clone(selected.ghostPreview.layout),
                        revision: 'rev-2',
                        operationResult: {
                            document: clone(selected.ghostPreview.layout),
                            createdIds: [],
                        },
                        receipt: { receiptId: 'receipt-one' },
                    };
                },
                createIdempotencyKey: () => 'layout-apply-001',
            });
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.requestLayoutProposal(fullLayoutRequest());
            const result = await session.approveAndApplyLayoutProposal();
            const state = session.getState();
            assert.strictEqual(result.idempotencyKey, 'layout-apply-001');
            assert.deepStrictEqual(calls.map(item => item[0]), [
                'create', 'preview', 'approve', 'apply',
            ]);
            assert.strictEqual(
                calls[2][1].idempotencyKey,
                calls[3][1].idempotencyKey
            );
            assert.strictEqual(calls[2][1].explicitApproval, true);
            assert.deepStrictEqual(
                calls[2][1].binding,
                selected.transactionBinding
            );
            assert.strictEqual(state.baseRevision, 'rev-2');
            assert.strictEqual(state.layoutProposal, null);
            assert.strictEqual(state.dirty, false);
            assert.deepStrictEqual(state.recentReceiptIds, ['receipt-one']);
            assert.deepStrictEqual(
                state.layout,
                selected.ghostPreview.layout
            );
            assert.deepStrictEqual(state.history, []);
        });

    await check('stale full-layout preview rejects without applying or dirtying',
        async () => {
            const initial = layout();
            const proposalReceipt = fullLayoutProposalReceipt(
                initial,
                'rev-1'
            );
            const selected = proposalReceipt.alternatives[0];
            let approvalCalls = 0;
            let applyCalls = 0;
            const authority = fakeAuthority(initial, {
                createLayoutProposals: async () => clone(proposalReceipt),
                getLayoutProposalPreview: async () => ({
                    proposalId: selected.proposalId,
                    alternative: {
                        ...clone(selected),
                        alternativeId: 'alternative-replaced',
                    },
                    transactionBinding:
                        clone(selected.transactionBinding),
                    createdAt: selected.createdAt,
                    expiresAt: selected.expiresAt,
                    previewPure: true,
                }),
                approveLayoutProposal: async () => {
                    approvalCalls += 1;
                    return { approvalToken: 'approval-token-001' };
                },
                applyLayoutProposal: async () => {
                    applyCalls += 1;
                    return {};
                },
            });
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.requestLayoutProposal(fullLayoutRequest());
            const before = session.getState();
            await assert.rejects(
                session.approveAndApplyLayoutProposal(),
                error => error.code === 'layout_proposal_stale'
            );
            const after = session.getState();
            assert.strictEqual(approvalCalls, 0);
            assert.strictEqual(applyCalls, 0);
            assert.deepStrictEqual(after.layout, before.layout);
            assert.deepStrictEqual(after.history, before.history);
            assert.strictEqual(after.dirty, false);
            assert.ok(after.layoutProposal);
        });

    await check('full-layout requests reject dirty, busy, and conflict states',
        async () => {
            let createCalls = 0;
            const dirtyAuthority = fakeAuthority(layout(), {
                createLayoutProposals: async () => {
                    createCalls += 1;
                    return fullLayoutProposalReceipt(layout(), 'rev-1');
                },
            });
            const dirtySession = dirtyAuthority.makeSession();
            dirtySession.load(dirtyAuthority.initialReceipt());
            dirtySession.select('pl-a');
            await dirtySession.moveSelected({ x: 1, y: 0, z: 0 });
            await assert.rejects(
                dirtySession.requestLayoutProposal(fullLayoutRequest()),
                error => error.code === 'layout_proposal_dirty'
            );
            assert.strictEqual(createCalls, 0);

            let resolveProposal;
            const busyAuthority = fakeAuthority(layout(), {
                createLayoutProposals: () => new Promise(resolve => {
                    resolveProposal = resolve;
                }),
            });
            const busySession = busyAuthority.makeSession();
            busySession.load(busyAuthority.initialReceipt());
            const pending = busySession.requestLayoutProposal(
                fullLayoutRequest()
            );
            await assert.rejects(
                busySession.requestLayoutProposal(fullLayoutRequest()),
                error => error.code === 'session_busy'
            );
            resolveProposal(fullLayoutProposalReceipt(layout(), 'rev-1'));
            await pending;

            const conflict = operationError(
                'revision_conflict',
                'Stale proposal request',
                { currentRevision: 'rev-2' }
            );
            conflict.status = 409;
            const conflictAuthority = fakeAuthority(layout(), {
                createLayoutProposals: async () => {
                    throw conflict;
                },
            });
            const conflictSession = conflictAuthority.makeSession();
            conflictSession.load(conflictAuthority.initialReceipt());
            await assert.rejects(
                conflictSession.requestLayoutProposal(fullLayoutRequest()),
                error => error.code === 'revision_conflict'
            );
            assert.ok(conflictSession.getState().conflict);
            await assert.rejects(
                conflictSession.requestLayoutProposal(fullLayoutRequest()),
                error => error.code === 'layout_proposal_conflict'
            );
        });

    await check('generated draft is review-only until exact Save or Undo',
        async () => {
            const base = layout();
            const generated = clone(base);
            generated.displayName = 'Generated Facility';
            generated.zones.push({
                zoneId: 'zone-generated-01',
                label: 'Assembly',
                zoneType: 'workcell',
                boundary: [
                    { x: 0, z: 0 },
                    { x: 10, z: 0 },
                    { x: 10, z: 10 },
                    { x: 0, z: 10 },
                ],
                metadata: {},
                extensions: {},
            });
            const saveCalls = [];
            const authority = fakeAuthority(base, {
                saveGenerationDraft: async request => {
                    saveCalls.push(clone(request));
                    return {
                        run: { status: 'saved' },
                        savedLayout: {
                            layout: clone(generated),
                            revision: 'rev-generated-2',
                        },
                        saveReceipt: {
                            saveReceiptId: 'save-generated-01',
                        },
                    };
                },
            });
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.installGenerationDraft({
                runId: 'fgr-generated-01',
                status: 'complete',
                currentStageId: null,
                completedStageId: 'review_and_save',
                baseLayoutRevision: 'rev-1',
                draftLayoutRevision: 'draft-generated-1',
                draftLayout: generated,
                cumulativeProposal: {
                    cumulativeDiffHash: 'a'.repeat(64),
                },
                saveEligibility: 'eligible',
                writable: true,
                prototypeMode: true,
                workflowScope: 'full_factory_generation',
                fullFactoryProgramRevision: 'b'.repeat(64),
                receiptChain: ['stage-receipt-1'],
            });
            const review = session.getState();
            assert.strictEqual(review.dirty, true);
            assert.strictEqual(review.canUndo, true);
            assert.strictEqual(review.canSave, true);
            assert.strictEqual(review.generatedDraft.runId, 'fgr-generated-01');
            assert.strictEqual(
                review.generatedDraft.workflowScope,
                'full_factory_generation'
            );
            assert.strictEqual(
                review.generatedDraft.fullFactoryProgramRevision,
                'b'.repeat(64)
            );
            assert.strictEqual(review.layout.zones.length, 1);
            await assert.rejects(
                session.createRectangleZone(
                    { x: 0, z: 0 },
                    { x: 2, z: 2 },
                    { label: 'Unapproved edit' }
                ),
                error => error.code === 'generated_draft_review_required'
            );
            const saved = await session.save();
            assert.strictEqual(saveCalls.length, 1);
            assert.deepStrictEqual(saveCalls[0], {
                runId: 'fgr-generated-01',
                cumulativeDiffHash: 'a'.repeat(64),
                explicitApproval: true,
            });
            assert.strictEqual(saved.state.dirty, false);
            assert.strictEqual(saved.state.generatedDraft, null);
            assert.strictEqual(saved.state.baseRevision, 'rev-generated-2');
        });

    await check('generated draft Undo restores the exact immutable base',
        async () => {
            const base = layout();
            const generated = clone(base);
            generated.displayName = 'Generated Facility';
            generated.zones = [{
                zoneId: 'zone-generated-01',
                label: 'Receiving',
                zoneType: 'receiving',
                boundary: [
                    { x: 0, z: 0 },
                    { x: 4, z: 0 },
                    { x: 4, z: 4 },
                    { x: 0, z: 4 },
                ],
                metadata: {},
                extensions: {},
            }];
            const undoCalls = [];
            const authority = fakeAuthority(base, {
                undoGenerationDraft: async request => {
                    undoCalls.push(clone(request));
                    return { restoredLayout: clone(base) };
                },
            });
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.installGenerationDraft({
                runId: 'fgr-generated-undo',
                status: 'running',
                currentStageId: 'primary_circulation',
                completedStageId: 'macro_departments',
                baseLayoutRevision: 'rev-1',
                draftLayoutRevision: 'draft-generated-2',
                draftLayout: generated,
                cumulativeProposal: null,
                saveEligibility: 'blocked',
                writable: true,
                prototypeMode: true,
                receiptChain: ['stage-receipt-1', 'stage-receipt-2'],
            });
            assert.strictEqual(session.getState().canSave, false);
            const undone = await session.undo();
            assert.deepStrictEqual(undoCalls, [
                { runId: 'fgr-generated-undo' },
            ]);
            assert.deepStrictEqual(undone.layout, base);
            assert.strictEqual(undone.dirty, false);
            assert.strictEqual(undone.generatedDraft, null);
        });

    await check('authority-lost design Undo restores local history and blocks Save or apply',
        async () => {
            let rootUndoFrame = null;
            let prepareApplyCalls = 0;
            let undoAcknowledgements = 0;
            const authority = fakeAuthority(layout(), {
                prepareDesignProposalApply: async request => {
                    prepareApplyCalls += 1;
                    rootUndoFrame = clone(request.rootUndoFrame);
                    const candidateLayout = clone(rootUndoFrame.draftLayout);
                    findPlacement(candidateLayout, 'pl-b').transform.position.x = 12;
                    const resultLayoutRevision = canonicalHash(candidateLayout);
                    const transactionBindingRevision = 'd'.repeat(64);
                    return {
                        transaction: {
                            transaction: {
                                transactionId: 'transaction-local-undo',
                                proposalBinding: { resultLayoutRevision },
                            },
                            transactionRevision: 'prepared-local-undo',
                        },
                        transactionBindingRevision,
                        candidateLayout,
                        candidateOperations: [{
                            op: 'move_placement',
                            placementId: 'pl-b',
                            position: { x: 12, y: 0, z: 2 },
                            movementKind: 'automatic',
                        }],
                        expectedInstallationFingerprint: canonicalHash({
                            commandJournalHash:
                                request.expectedResultCommandJournalHash,
                            draftRevision: resultLayoutRevision,
                            editorGenerationId:
                                request.expectedResultEditorGenerationId,
                            proposalId: request.proposalId,
                            proposalRevision: request.proposalRevision,
                            transactionBindingRevision,
                        }),
                        adoption: {
                            adoptionToken: 'adoption-local-undo',
                            adoption: { adoptionId: 'adoption-local-undo' },
                        },
                    };
                },
                commitDesignProposalApply: async () => ({
                    transaction: {
                        transaction: {
                            transactionId: 'transaction-local-undo',
                        },
                        transactionRevision: 'committed-local-undo',
                    },
                }),
                acknowledgeDesignProposalApply: async () => ({
                    transaction: { transactionRevision: 'active-local-undo' },
                }),
                recoverDesignProposalApply: async () => ({ recovered: true }),
                prepareDesignUndo: async () => ({
                    mode: 'local_only',
                    readiness: 'stale_local_restore',
                    rootUndoFrame: clone(rootUndoFrame),
                }),
                acknowledgeDesignUndo: async () => {
                    undoAcknowledgements += 1;
                },
            });
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.movePlacements([{
                placementId: 'pl-a',
                position: { x: 3, y: 0, z: 1 },
            }], 'Manual edit before proposal');
            await session.applyDesignProposal({
                proposalId: 'proposal-local-undo',
                proposalRevision: 'a'.repeat(64),
            });

            const restored = await session.undoDesignProposal();
            assert.strictEqual(byId(restored.layout, 'pl-a').transform.position.x, 3);
            assert.strictEqual(byId(restored.layout, 'pl-b').transform.position.x, 4);
            assert.strictEqual(restored.historyCursor, 1);
            assert.strictEqual(restored.designAuthorityState, 'stale_local_restore');
            assert.strictEqual(restored.canSave, false);
            assert.strictEqual(undoAcknowledgements, 0);
            await assert.rejects(
                session.save(),
                error => error.code === 'facility_design_base_rebind_required'
            );
            await assert.rejects(
                session.applyDesignProposal({
                    proposalId: 'proposal-after-authority-loss',
                    proposalRevision: 'b'.repeat(64),
                }),
                error => error.code === 'facility_design_base_rebind_required'
            );
            assert.strictEqual(prepareApplyCalls, 1);

            const nextUndo = await session.undo();
            assert.strictEqual(byId(nextUndo.layout, 'pl-a').transform.position.x, 1);
            assert.strictEqual(nextUndo.historyCursor, 0);
            assert.strictEqual(nextUndo.designAuthorityState, 'stale_local_restore');
        });

    await check('authority-lost proposal Undo makes restored generation Undo local-only',
        async () => {
            const base = layout();
            const generated = clone(base);
            generated.displayName = 'Expired generated Facility';
            let rootUndoFrame = null;
            const generationUndoCalls = [];
            const authority = fakeAuthority(base, {
                undoGenerationDraft: async request => {
                    generationUndoCalls.push(clone(request));
                },
                prepareDesignProposalApply: async request => {
                    rootUndoFrame = clone(request.rootUndoFrame);
                    const candidateLayout = clone(rootUndoFrame.draftLayout);
                    findPlacement(candidateLayout, 'pl-b').transform.position.x = 14;
                    const resultLayoutRevision = canonicalHash(candidateLayout);
                    const transactionBindingRevision = 'e'.repeat(64);
                    return {
                        transaction: {
                            transaction: {
                                transactionId: 'transaction-generated-local',
                                proposalBinding: { resultLayoutRevision },
                            },
                            transactionRevision: 'prepared-generated-local',
                        },
                        transactionBindingRevision,
                        candidateLayout,
                        candidateOperations: [{
                            op: 'move_placement',
                            placementId: 'pl-b',
                            position: { x: 14, y: 0, z: 2 },
                            movementKind: 'automatic',
                        }],
                        expectedInstallationFingerprint: canonicalHash({
                            commandJournalHash:
                                request.expectedResultCommandJournalHash,
                            draftRevision: resultLayoutRevision,
                            editorGenerationId:
                                request.expectedResultEditorGenerationId,
                            proposalId: request.proposalId,
                            proposalRevision: request.proposalRevision,
                            transactionBindingRevision,
                        }),
                        adoption: {
                            adoptionToken: 'adoption-generated-local',
                            adoption: { adoptionId: 'adoption-generated-local' },
                        },
                    };
                },
                commitDesignProposalApply: async () => ({
                    transaction: {
                        transaction: {
                            transactionId: 'transaction-generated-local',
                        },
                        transactionRevision: 'committed-generated-local',
                    },
                }),
                acknowledgeDesignProposalApply: async () => ({
                    transaction: { transactionRevision: 'active-generated-local' },
                }),
                recoverDesignProposalApply: async () => ({ recovered: true }),
                prepareDesignUndo: async () => ({
                    mode: 'local_only',
                    readiness: 'stale_local_restore',
                    rootUndoFrame: clone(rootUndoFrame),
                }),
            });
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            session.installGenerationDraft({
                runId: 'fgr-expired-before-local-undo',
                status: 'running',
                currentStageId: 'primary_circulation',
                completedStageId: 'macro_departments',
                baseLayoutRevision: authority.revision,
                draftLayoutRevision: canonicalHash(generated),
                draftLayout: generated,
                cumulativeProposal: null,
                saveEligibility: 'eligible',
                writable: true,
                prototypeMode: true,
                receiptChain: ['stage-receipt-local'],
            });
            await session.applyDesignProposal({
                proposalId: 'proposal-generated-local',
                proposalRevision: 'c'.repeat(64),
            });

            const restored = await session.undoDesignProposal();
            assert.strictEqual(restored.generatedDraft.authorityLost, true);
            assert.strictEqual(restored.canSave, false);
            const generationUndone = await session.undo();
            assert.deepStrictEqual(generationUndoCalls, []);
            assert.strictEqual(generationUndone.generatedDraft, null);
            assert.deepStrictEqual(generationUndone.layout, base);
            assert.strictEqual(
                generationUndone.designAuthorityState,
                'stale_local_restore'
            );
        });

    await check('explicit Save consumes an installed design transaction once',
        async () => {
            let candidateLayout = null;
            const saveCalls = [];
            const authority = fakeAuthority(layout(), {
                prepareDesignProposalApply: async request => {
                    candidateLayout = clone(request.rootUndoFrame.draftLayout);
                    findPlacement(candidateLayout, 'pl-b').transform.position.x = 16;
                    const resultLayoutRevision = canonicalHash(candidateLayout);
                    const transactionBindingRevision = 'f'.repeat(64);
                    return {
                        transaction: {
                            transaction: {
                                transactionId: 'transaction-design-save',
                                proposalBinding: { resultLayoutRevision },
                            },
                            transactionRevision: 'prepared-design-save',
                        },
                        transactionBindingRevision,
                        candidateLayout,
                        candidateOperations: [{
                            op: 'move_placement',
                            placementId: 'pl-b',
                            position: { x: 16, y: 0, z: 2 },
                            movementKind: 'automatic',
                        }],
                        expectedInstallationFingerprint: canonicalHash({
                            commandJournalHash:
                                request.expectedResultCommandJournalHash,
                            draftRevision: resultLayoutRevision,
                            editorGenerationId:
                                request.expectedResultEditorGenerationId,
                            proposalId: request.proposalId,
                            proposalRevision: request.proposalRevision,
                            transactionBindingRevision,
                        }),
                        adoption: {
                            adoptionToken: 'adoption-design-save',
                            adoption: { adoptionId: 'adoption-design-save' },
                        },
                    };
                },
                commitDesignProposalApply: async () => ({
                    transaction: {
                        transaction: {
                            transactionId: 'transaction-design-save',
                        },
                        transactionRevision: 'committed-design-save',
                    },
                }),
                acknowledgeDesignProposalApply: async () => ({
                    transaction: { transactionRevision: 'active-design-save' },
                }),
                recoverDesignProposalApply: async () => ({ recovered: true }),
                saveDesignProposalDraft: async request => {
                    saveCalls.push(clone(request));
                    return {
                        savedLayout: {
                            layout: clone(candidateLayout),
                            revision: 'saved-design-revision',
                        },
                        saveReceipt: {
                            receiptId: 'receipt-design-save',
                        },
                        transaction: {
                            transactionRevision: 'saved-design-transaction',
                        },
                    };
                },
            });
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            const applied = await session.applyDesignProposal({
                proposalId: 'proposal-design-save',
                proposalRevision: 'd'.repeat(64),
            });
            assert.strictEqual(applied.dirty, true);
            const expectedDraftRevision = applied.draftRevision;
            const expectedJournalHash = applied.commandJournalHash;

            const saved = await session.save();
            assert.deepStrictEqual(saveCalls, [{
                transactionId: 'transaction-design-save',
                expectedTransactionRevision: 'active-design-save',
                observedDraftRevision: expectedDraftRevision,
                observedCommandJournalHash: expectedJournalHash,
                explicitApproval: true,
            }]);
            assert.deepStrictEqual(authority.applyCalls, []);
            assert.strictEqual(saved.state.dirty, false);
            assert.strictEqual(saved.state.designProposalDraft, null);
            assert.strictEqual(saved.state.baseRevision, 'saved-design-revision');
            assert.strictEqual(byId(saved.state.layout, 'pl-b').transform.position.x, 16);
            assert.strictEqual(saved.receipt.receiptId, 'receipt-design-save');
        });

    for (const staged of [false, true]) {
    await check('design replacement failure restores A and exact Undo restores O history' + (staged ? ' with program batches' : ''),
        async () => {
            const preparedCalls = [];
            const commitCalls = [];
            const recoveryCalls = [];
            const undoAcknowledgements = [];
            let rootUndoFrame = null;
            let activeProposalId = null;
            const authority = fakeAuthority(layout(), {
                prepareDesignProposalApply: async request => {
                    preparedCalls.push(clone(request));
                    if (!rootUndoFrame) rootUndoFrame = clone(request.rootUndoFrame);
                    activeProposalId = request.proposalId;
                    const candidateLayout = clone(request.rootUndoFrame.draftLayout);
                    const targetX = request.proposalId === 'proposal-a' ? 11 : 21;
                    findPlacement(candidateLayout, 'pl-b').transform.position.x = targetX;
                    const resultLayoutRevision = canonicalHash(candidateLayout);
                    const transactionBindingRevision = request.proposalId === 'proposal-a'
                        ? 'binding-a' : 'binding-b';
                    const transactionId = request.transactionId || 'transaction-design-one';
                    const expectedInstallationFingerprint = canonicalHash({
                        commandJournalHash:
                            request.expectedResultCommandJournalHash,
                        draftRevision: resultLayoutRevision,
                        editorGenerationId:
                            request.expectedResultEditorGenerationId,
                        proposalId: request.proposalId,
                        proposalRevision: request.proposalRevision,
                        transactionBindingRevision,
                    });
                    return {
                        transaction: {
                            transaction: {
                                transactionId,
                                proposalBinding: { resultLayoutRevision },
                            },
                            transactionRevision: 'prepared-' + request.proposalId,
                        },
                        transactionBindingRevision,
                        candidateLayout,
                        ...(staged ? { candidateOperationBatches: [
                            { label: 'seed-stage', operations: [{ op: 'move_placement', placementId: 'pl-b',
                                position: { x: 8, y: 0, z: 2 }, movementKind: 'automatic' }] },
                            { label: 'cell-stage', operations: [{ op: 'move_placement', placementId: 'pl-b',
                                position: { x: targetX, y: 0, z: 2 }, movementKind: 'automatic' }] },
                        ] } : { candidateOperations: [{
                            op: 'move_placement',
                            placementId: 'pl-b',
                            position: { x: targetX, y: 0, z: 2 },
                            movementKind: 'automatic',
                        }] }),
                        expectedInstallationFingerprint,
                        adoption: {
                            adoptionToken: 'adoption-' + request.proposalId,
                            adoption: { adoptionId: 'adoption-' + request.proposalId },
                        },
                    };
                },
                commitDesignProposalApply: async request => {
                    commitCalls.push(clone(request));
                    return {
                        transaction: {
                            transaction: {
                                transactionId: request.transactionId,
                            },
                            transactionRevision: 'committed-' + activeProposalId,
                        },
                    };
                },
                acknowledgeDesignProposalApply: async () => {
                    if (activeProposalId === 'proposal-b') {
                        throw operationError(
                            'facility_design_browser_acknowledgement_failed',
                            'Injected proposal B installation failure'
                        );
                    }
                    return {
                        transaction: {
                            transactionRevision: 'active-proposal-a',
                        },
                    };
                },
                recoverDesignProposalApply: async request => {
                    recoveryCalls.push(clone(request));
                    return { recovered: true };
                },
                prepareDesignUndo: async request => ({
                    mode: 'coordinated',
                    rootUndoFrame: clone(rootUndoFrame),
                    transaction: {
                        transactionRevision: 'undo-prepared-one',
                    },
                    request: clone(request),
                }),
                acknowledgeDesignUndo: async request => {
                    undoAcknowledgements.push(clone(request));
                    return { undone: true };
                },
            });
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.movePlacements([{
                placementId: 'pl-a',
                position: { x: 2, y: 0, z: 1 },
            }], 'Manual edit one');
            await session.movePlacements([{
                placementId: 'pl-b',
                position: { x: 5, y: 0, z: 2 },
            }], 'Manual edit two');
            const frameO = session.captureDesignEditorFrame();
            assert.strictEqual(frameO.cursor, 2);

            const stateA = await session.applyDesignProposal({
                proposalId: 'proposal-a',
                proposalRevision: 'a'.repeat(64),
            });
            assert.strictEqual(byId(stateA.layout, 'pl-a').transform.position.x, 2);
            assert.strictEqual(byId(stateA.layout, 'pl-b').transform.position.x, 11);
            assert.strictEqual(stateA.operations.length, staged ? 4 : 3);
            if (staged) {
                const appliedFrame = session.captureDesignEditorFrame();
                assert.strictEqual(appliedFrame.cursor, 4);
                assert.deepStrictEqual(appliedFrame.batches.slice(2).map(b => b.label), ['seed-stage', 'cell-stage']);
            }
            assert.strictEqual(
                stateA.designProposalDraft.transactionRevision,
                'active-proposal-a'
            );

            await assert.rejects(
                session.applyDesignProposal({
                    proposalId: 'proposal-b',
                    proposalRevision: 'b'.repeat(64),
                }),
                error => error.code
                    === 'facility_design_browser_acknowledgement_failed'
            );
            const restoredA = session.getState();
            assert.strictEqual(byId(restoredA.layout, 'pl-b').transform.position.x, 11);
            assert.strictEqual(restoredA.operations.length, staged ? 4 : 3);
            assert.strictEqual(restoredA.designProposalDraft.proposalId, 'proposal-a');
            assert.strictEqual(recoveryCalls.length, 1);
            assert.strictEqual(preparedCalls[1].transactionId, 'transaction-design-one');

            const restoredO = await session.undoDesignProposal();
            assert.strictEqual(byId(restoredO.layout, 'pl-a').transform.position.x, 2);
            assert.strictEqual(byId(restoredO.layout, 'pl-b').transform.position.x, 5);
            assert.strictEqual(restoredO.operations.length, 2);
            assert.strictEqual(restoredO.designProposalDraft, null);
            assert.strictEqual(undoAcknowledgements.length, 1);
            assert.strictEqual(commitCalls.length, 2);

            const oneMoreUndo = await session.undo();
            assert.strictEqual(byId(oneMoreUndo.layout, 'pl-a').transform.position.x, 2);
            assert.strictEqual(byId(oneMoreUndo.layout, 'pl-b').transform.position.x, 4);
            assert.strictEqual(oneMoreUndo.operations.length, 1);
        });
    }

    await check('lost design Undo acknowledgment retains a retryable recovery handle',
        async () => {
            let rootUndoFrame = null;
            let recoveryRecord = null;
            let prepareUndoCalls = 0;
            let acknowledgeUndoCalls = 0;
            let serverUndoCompleted = false;
            const authority = fakeAuthority(layout(), {
                prepareDesignProposalApply: async request => {
                    rootUndoFrame = clone(request.rootUndoFrame);
                    const candidateLayout = clone(rootUndoFrame.draftLayout);
                    findPlacement(candidateLayout, 'pl-b').transform.position.x = 15;
                    const resultLayoutRevision = canonicalHash(candidateLayout);
                    const transactionBindingRevision = '9'.repeat(64);
                    return {
                        transaction: {
                            transaction: {
                                transactionId: 'transaction-undo-retry',
                                proposalBinding: { resultLayoutRevision },
                            },
                            transactionRevision: 'prepared-undo-retry',
                        },
                        transactionBindingRevision,
                        candidateLayout,
                        candidateOperations: [{
                            op: 'move_placement',
                            placementId: 'pl-b',
                            position: { x: 15, y: 0, z: 2 },
                            movementKind: 'automatic',
                        }],
                        expectedInstallationFingerprint: canonicalHash({
                            commandJournalHash:
                                request.expectedResultCommandJournalHash,
                            draftRevision: resultLayoutRevision,
                            editorGenerationId:
                                request.expectedResultEditorGenerationId,
                            proposalId: request.proposalId,
                            proposalRevision: request.proposalRevision,
                            transactionBindingRevision,
                        }),
                        adoption: {
                            adoptionToken: 'adoption-undo-retry',
                            adoption: { adoptionId: 'adoption-undo-retry' },
                        },
                    };
                },
                commitDesignProposalApply: async () => ({
                    transaction: {
                        transaction: { transactionId: 'transaction-undo-retry' },
                        transactionRevision: 'committed-undo-retry',
                    },
                }),
                acknowledgeDesignProposalApply: async () => ({
                    transaction: { transactionRevision: 'active-undo-retry' },
                }),
                recoverDesignProposalApply: async () => ({ recovered: true }),
                prepareDesignUndo: async request => {
                    prepareUndoCalls += 1;
                    if (serverUndoCompleted) {
                        return {
                            mode: 'already_undone',
                            readiness: 'ready',
                            rootUndoFrame: clone(rootUndoFrame),
                            transaction: {
                                transaction: {
                                    transactionId: request.transactionId,
                                    status: 'undone',
                                },
                                transactionRevision: 'undone-retry',
                            },
                        };
                    }
                    return {
                        mode: 'coordinated',
                        readiness: 'undo_acknowledgment_pending',
                        rootUndoFrame: clone(rootUndoFrame),
                        transaction: {
                            transaction: {
                                transactionId: request.transactionId,
                                proposalBinding: {
                                    proposalId: 'proposal-undo-retry',
                                    proposalRevision: 'a'.repeat(64),
                                },
                                installationBindingTransactionRevision:
                                    '9'.repeat(64),
                            },
                            transactionRevision: 'undo-pending-retry',
                        },
                    };
                },
                acknowledgeDesignUndo: async () => {
                    acknowledgeUndoCalls += 1;
                    if (acknowledgeUndoCalls === 1) {
                        serverUndoCompleted = true;
                        throw operationError(
                            'facility_design_undo_acknowledgment_failed',
                            'Injected lost Undo acknowledgment'
                        );
                    }
                    return { outcome: 'already_undone' };
                },
                persistDesignUndoRecovery: async record => {
                    recoveryRecord = clone(record);
                },
                loadDesignUndoRecovery: async () => clone(recoveryRecord),
                clearDesignUndoRecovery: async () => {
                    recoveryRecord = null;
                },
            });
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            await session.movePlacements([{
                placementId: 'pl-a',
                position: { x: 3, y: 0, z: 1 },
            }], 'Manual edit retained by Undo');
            await session.applyDesignProposal({
                proposalId: 'proposal-undo-retry',
                proposalRevision: 'a'.repeat(64),
            });

            await assert.rejects(
                session.undoDesignProposal(),
                error => error.code
                    === 'facility_design_undo_acknowledgment_failed'
            );
            const pending = session.getState();
            assert.strictEqual(byId(pending.layout, 'pl-a').transform.position.x, 3);
            assert.strictEqual(byId(pending.layout, 'pl-b').transform.position.x, 4);
            assert.strictEqual(pending.historyCursor, 1);
            assert.strictEqual(
                pending.designProposalDraft.status,
                'undo_acknowledgment_pending'
            );
            assert.strictEqual(
                pending.designAuthorityState,
                'undo_acknowledgment_pending'
            );
            assert.strictEqual(pending.canSave, false);
            assert.strictEqual(recoveryRecord.phase, 'acknowledgment_pending');

            const reloaded = authority.makeSession();
            reloaded.load(authority.initialReceipt());
            const completed = await reloaded.resumeDesignUndoRecovery();
            assert.strictEqual(completed.designProposalDraft, null);
            assert.strictEqual(completed.designAuthorityState, 'ready');
            assert.strictEqual(completed.historyCursor, 1);
            assert.strictEqual(
                byId(completed.layout, 'pl-a').transform.position.x,
                3
            );
            assert.strictEqual(
                byId(completed.layout, 'pl-b').transform.position.x,
                4
            );
            assert.strictEqual(recoveryRecord, null);
            assert.strictEqual(prepareUndoCalls, 2);
            assert.strictEqual(acknowledgeUndoCalls, 1);

            const priorUndo = await reloaded.undo();
            assert.strictEqual(byId(priorUndo.layout, 'pl-a').transform.position.x, 1);
            assert.strictEqual(priorUndo.historyCursor, 0);
        });

    await check('design proposal accepts the ordinary edit_route kernel operation',
        async () => {
            const base = layout();
            base.routes.push({
                routeId: 'rt-material',
                label: 'Material route',
                routeKind: 'material',
                sourceEndpoint: {
                    kind: 'world_point',
                    position: { x: 0, y: 0, z: 0 },
                },
                targetEndpoint: {
                    kind: 'world_point',
                    position: { x: 10, y: 0, z: 0 },
                },
                routingMode: 'polyline',
                centerline: [
                    { x: 0, y: 0, z: 0 },
                    { x: 10, y: 0, z: 0 },
                ],
                corridorWidth: 3,
                routeFingerprint: 'f'.repeat(64),
                sourceRevisions: { layoutBaseRevision: 'a'.repeat(64) },
                requirements: [],
                evidence: [],
                extensions: {},
            });
            const authority = fakeAuthority(base, {
                prepareDesignProposalApply: async request => {
                    const candidateLayout = clone(request.rootUndoFrame.draftLayout);
                    const route = findRoute(candidateLayout, 'rt-material');
                    route.centerline = [
                        { x: 0, y: 0, z: 0 },
                        { x: 5, y: 0, z: 2 },
                        { x: 10, y: 0, z: 0 },
                    ];
                    route.routeFingerprint = 'e'.repeat(64);
                    const resultLayoutRevision = canonicalHash(candidateLayout);
                    const transactionBindingRevision = 'binding-route';
                    return {
                        transaction: {
                            transaction: {
                                transactionId: 'transaction-route',
                                proposalBinding: { resultLayoutRevision },
                            },
                            transactionRevision: 'prepared-route',
                        },
                        transactionBindingRevision,
                        candidateLayout,
                        candidateOperations: [{
                            op: 'edit_route',
                            routeId: 'rt-material',
                            patch: {
                                centerline: clone(route.centerline),
                                routeFingerprint: route.routeFingerprint,
                            },
                        }],
                        expectedInstallationFingerprint: canonicalHash({
                            commandJournalHash:
                                request.expectedResultCommandJournalHash,
                            draftRevision: resultLayoutRevision,
                            editorGenerationId:
                                request.expectedResultEditorGenerationId,
                            proposalId: request.proposalId,
                            proposalRevision: request.proposalRevision,
                            transactionBindingRevision,
                        }),
                        adoption: {
                            adoptionToken: 'adoption-route',
                            adoption: { adoptionId: 'adoption-route' },
                        },
                    };
                },
                commitDesignProposalApply: async request => ({
                    transaction: {
                        transaction: { transactionId: request.transactionId },
                        transactionRevision: 'committed-route',
                    },
                }),
                acknowledgeDesignProposalApply: async () => ({
                    transaction: { transactionRevision: 'active-route' },
                }),
                recoverDesignProposalApply: async () => ({ recovered: true }),
            });
            const session = authority.makeSession();
            session.load(authority.initialReceipt());
            const applied = await session.applyDesignProposal({
                proposalId: 'proposal-route',
                proposalRevision: 'a'.repeat(64),
            });
            assert.strictEqual(applied.operations[0].op, 'edit_route');
            assert.strictEqual(applied.layout.routes[0].centerline.length, 3);
        });

    await check('approved construction installs once and exact Undo invalidates old approval', async () => {
        const initial = layout();
        const baseRevision = canonicalHash(initial);
        let saves = 0, previews = 0;
        const session = facilitySession.createSession({sessionId: 'browser-session',
            previewOperations: async request => {
                previews += 1;
                assert.strictEqual(request.baseRevision, baseRevision);
                const result = applyFakeOperations(initial, request.operations);
                return {document: result.document, revision: canonicalHash(result.document), createdIds: result.createdIds};
            }, applyOperations: async () => { saves += 1; throw new Error('Save forbidden'); },
        });
        session.load({layout: initial, revision: baseRevision});
        const before = session.getState();
        const operations = [{op: 'move_placement', placementId: 'pl-a', position: {x: 12, y: 0, z: 12}, movementKind: 'user'}];
        const candidate = applyFakeOperations(initial, operations).document;
        const approval = {approvalId: 'fca-' + 'a'.repeat(64), baseRevision,
            candidateRevision: canonicalHash(candidate), operations,
            binding: {expectedDraftRevision: baseRevision, editorGenerationId: before.editorGenerationId, sessionId: 'browser-session'}};
        const foreign = {...approval, binding: {...approval.binding, sessionId: 'another-session'}};
        await assert.rejects(session.installConstructionApproval(foreign), error => error.code === 'facility_command_stale');
        assert.strictEqual(previews, 0);
        await assert.rejects(session.installConstructionApproval({...approval, candidateRevision: 'b'.repeat(64)}),
            error => error.code === 'facility_command_stale');
        assert.deepStrictEqual(session.getState().layout, before.layout);
        assert.deepStrictEqual(session.getState().history, before.history);
        await session.installConstructionApproval(approval);
        assert.deepStrictEqual(session.getState().layout, candidate);
        assert.strictEqual(session.getState().history.length, 1);
        const after = session.getState(), count = previews;
        await session.installConstructionApproval(approval);
        assert.strictEqual(previews, count);
        assert.deepStrictEqual(session.getState(), after);
        await session.undo();
        assert.deepStrictEqual(session.getState().layout, before.layout);
        assert.strictEqual(session.getState().draftRevision, before.draftRevision);
        await assert.rejects(session.installConstructionApproval(approval), error => error.code === 'facility_command_stale');
        assert.strictEqual(saves, 0);
    });

    await check('explicit construction builds attaches groups repeats retries and undoes without saving', async () => {
        const initial = layout();
        initial.placements = [];
        initial.zones = [];
        initial.floorMarkings = [];
        const authority = fakeAuthority(initial);
        const session = authority.makeSession();
        session.load(authority.initialReceipt());
        const catalog = [
            { assetId: 'table', assetDefinitionRevision: 'rev-table', width: 3, depth: 2, height: 1,
                supportSurfaces: [{ surfaceId: 'worktop', allowedSides: ['above'],
                    localFrame: { origin: { x: 0, y: 1, z: 0 }, xAxis: { x: 1, y: 0, z: 0 },
                        zAxis: { x: 0, y: 0, z: 1 }, normal: { x: 0, y: 1, z: 0 } },
                    bounds: { minimumX: -1.5, maximumX: 1.5, minimumZ: -1, maximumZ: 1 } }] },
            { assetId: 'device', assetDefinitionRevision: 'rev-device', width: 0.3, depth: 0.3, height: 0.2 },
        ];
        // These are trusted fixture placements, not model-authored coordinates.
        await session.placeAssets([catalog[0], catalog[0], catalog[1]].map((asset, index) => ({
            assetId: asset.assetId, assetDefinitionRevision: asset.assetDefinitionRevision,
            worldPosition: { x: 10 + index * 5, y: 0, z: 10 },
        })));
        const [tableA, tableB, device] = session.getState().layout.placements.map(item => item.placementId);
        const executor = constructionAdapter.createAdapter(constructionContract, facilityPatterns, session, () => catalog);
        let sequence = 0;
        const run = (commandId, args) => executor.execute({ commandId, arguments: args,
            requestId: 'cell-test-' + (++sequence), expectedDraftRevision: session.getState().draftRevision });
        session.select(device); // Dialog selection must not determine the target.
        await run('cell-layout', { selectionIds: [tableA, tableB], strategyId: 'line',
            targetBounds: { width: 15, depth: 8 }, gap: 0.5, rows: 1, orientation: 'preserve',
            angleDegrees: 0, invertU: false, sourceUnit: 'm' });
        await run('surface-stack', { supportId: tableA, childIds: [device], surfaceId: 'worktop',
            itemGap: 0.05, inset: 0.05 });
        const group = await run('create-cell-group', { selectionIds: [tableA, tableB, device], label: 'Assembly', envelopePadding: 0.2 });
        assert.strictEqual(group.cells.length, 1);
        assert.strictEqual(group.cells[0].memberIds.length, 3);
        const beforePattern = clone(session.getState().layout);
        const request = { commandId: 'linear-pattern', arguments: { seedIds: [group.cells[0].cellId],
            count: 3, direction: 'north', spacing: 15, sourceUnit: 'm' },
            requestId: 'repeat-cell', expectedDraftRevision: session.getState().draftRevision };
        const receipt = await executor.execute(request);
        assert.strictEqual(receipt.cells.length, 2);
        assert.strictEqual(receipt.createdIds.length, 8);
        const repeated = clone(session.getState().layout);
        receipt.cells.forEach(cell => {
            assert.strictEqual(cell.memberIds.length, 3);
            const child = repeated.placements.find(item => cell.memberIds.includes(item.placementId) && item.assetId === 'device');
            assert.ok(cell.memberIds.includes(child.snapRelationship.supportPlacementId));
            assert.notStrictEqual(child.snapRelationship.supportPlacementId, tableA);
        });
        const previewCount = authority.previewCalls.length;
        assert.deepStrictEqual(await executor.execute(request), receipt);
        assert.strictEqual(authority.previewCalls.length, previewCount);
        await assert.rejects(executor.execute({ ...request, arguments: { ...request.arguments, count: 4 } }),
            error => error.code === 'facility_command_idempotency_conflict');
        await assert.rejects(executor.execute({ ...request, requestId: 'stale', expectedDraftRevision: 'stale' }),
            error => error.code === 'facility_command_stale');
        await session.undo();
        assert.deepStrictEqual(session.getState().layout, beforePattern);
        await assert.rejects(executor.execute(request), error => error.code === 'facility_command_stale');
        while (session.getState().canUndo) await session.undo();
        assert.deepStrictEqual(session.getState().layout, initial);
        assert.deepStrictEqual(authority.layout, initial);
        assert.strictEqual(authority.applyCalls.length, 0);
    });

    await check('construction retries ignore object key order but preserve ordered inputs', async () => {
        const authority = fakeAuthority(layout());
        const session = authority.makeSession();
        session.load(authority.initialReceipt());
        const catalog = session.getState().layout.placements.map(item => ({ assetId: item.assetId,
            assetDefinitionRevision: item.assetDefinitionRevision, width: 1, depth: 1, height: 1 }));
        const executor = constructionAdapter.createAdapter(constructionContract, facilityPatterns, session, () => catalog);
        const request = { commandId: 'cell-layout', requestId: 'ordered-cell',
            expectedDraftRevision: session.getState().draftRevision,
            arguments: { selectionIds: ['pl-a', 'pl-b'], strategyId: 'line',
                targetBounds: { width: 10, depth: 6 }, sourceUnit: 'm', gap: 1, rows: 1,
                orientation: 'preserve', angleDegrees: 0, invertU: false } };
        const receipt = await executor.execute(request);
        const after = session.getState();
        const previews = authority.previewCalls.length;
        const reordered = { arguments: { invertU: false, angleDegrees: 0, orientation: 'preserve',
            rows: 1, gap: 1, sourceUnit: 'm', targetBounds: { depth: 6, width: 10 },
            strategyId: 'line', selectionIds: ['pl-a', 'pl-b'] },
            expectedDraftRevision: request.expectedDraftRevision, requestId: request.requestId,
            commandId: request.commandId };
        assert.notStrictEqual(JSON.stringify(request), JSON.stringify(reordered));
        assert.deepStrictEqual(await executor.execute(reordered), receipt);
        for (const changed of [{ selectionIds: ['pl-b', 'pl-a'] }, { gap: 2 }]) {
            await assert.rejects(executor.execute({ ...reordered, arguments: { ...reordered.arguments, ...changed } }),
                error => error.code === 'facility_command_idempotency_conflict');
        }
        assert.deepStrictEqual(session.getState(), after);
        assert.strictEqual(authority.previewCalls.length, previews);
        assert.strictEqual(authority.applyCalls.length, 0);
    });

    await check('construction validation and preview failures preserve exact local draft', async () => {
        const initial = layout();
        const failures = {};
        const authority = fakeAuthority(initial, failures);
        const session = authority.makeSession();
        session.load(authority.initialReceipt());
        const catalog = initial.placements.map(item => ({ assetId: item.assetId,
            assetDefinitionRevision: item.assetDefinitionRevision, width: 1, depth: 1, height: 1 }));
        const executor = constructionAdapter.createAdapter(constructionContract, facilityPatterns, session, () => catalog);
        const request = { commandId: 'linear-pattern', requestId: 'failed-repeat', expectedDraftRevision: session.getState().draftRevision,
            arguments: { seedIds: [initial.placements[0].placementId], count: 3, direction: 'east', spacing: 5, sourceUnit: 'm' } };
        failures.previewFailure = operationError('spatial_conflict', 'Obstructed fixture');
        await assert.rejects(executor.execute(request));
        assert.deepStrictEqual(session.getState().layout, initial);
        assert.strictEqual(session.getState().historyCursor, 0);
        assert.strictEqual(authority.applyCalls.length, 0);
        delete failures.previewFailure;
        await executor.execute(request);
        assert.strictEqual(session.getState().historyCursor, 1);
    });

    process.stdout.write(`${checks}/${checks} facility layout session checks passed\n`);
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
