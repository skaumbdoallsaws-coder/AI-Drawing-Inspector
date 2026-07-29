'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const MODULE_PATH = path.join(ROOT, 'static', 'facility_layout_session.js');
const facilitySession = require(MODULE_PATH);
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
            if (operation.position) source.transform.position = clone(operation.position);
            if (operation.quaternion) source.transform.quaternion = clone(operation.quaternion);
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
        case 'set_position_mode':
            findPlacement(document, operation.placementId).positionMode =
                operation.positionMode;
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
        default:
            throw operationError('unknown_operation', operation.op);
        }
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

async function main() {
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

    process.stdout.write(`${checks}/${checks} facility layout session checks passed\n`);
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
