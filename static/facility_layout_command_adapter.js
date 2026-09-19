(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityCommandAdapter = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const units = Object.freeze({ m: 1, mm: 0.001, ft: 0.3048, in: 0.0254 });
    const angles = Object.freeze({ horizontal: 0, vertical: 90,
        east: 0, west: 180, north: 270, south: 90 });
    const clone = value => JSON.parse(JSON.stringify(value));

    function canonicalValue(value) {
        if (Array.isArray(value)) return value.map(canonicalValue);
        if (!value || typeof value !== 'object') return value;
        return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonicalValue(value[key])]));
    }

    function reject(message, code) {
        const error = new Error(message);
        error.code = code || 'facility_command_input_invalid';
        throw error;
    }

    // This interpreter supports exactly the schema keywords in the bundled
    // construction contract. Unknown validation keywords fail closed.
    function validate(schema, value, path) {
        const keywords = new Set(['type', 'properties', 'required', 'additionalProperties',
            'items', 'minItems', 'maxItems', 'uniqueItems', 'minimum', 'maximum',
            'exclusiveMinimum', 'minLength', 'maxLength', 'pattern', 'enum', 'description', 'default']);
        if (Object.keys(schema).some(key => !keywords.has(key))) reject('Unsupported schema keyword');
        const type = schema.type;
        const valid = type === 'object' ? value !== null && typeof value === 'object' && !Array.isArray(value)
            : type === 'array' ? Array.isArray(value)
            : type === 'integer' ? Number.isSafeInteger(value)
            : type === 'number' ? typeof value === 'number' && Number.isFinite(value)
            : typeof value === type;
        if (!valid) reject(path + ': expected ' + type);
        if (schema.enum && !schema.enum.includes(value)) reject(path + ': unsupported value');
        if (type === 'object') {
            if (Object.keys(value).some(key => !Object.hasOwn(schema.properties, key))) reject(path + ': unknown field');
            (schema.required || []).forEach(key => {
                if (!Object.hasOwn(value, key)) reject(path + '.' + key + ': required');
            });
            Object.keys(value).forEach(key => validate(schema.properties[key], value[key], path + '.' + key));
        } else if (type === 'array') {
            if (value.length < schema.minItems || value.length > schema.maxItems) reject(path + ': invalid count');
            if (schema.uniqueItems && new Set(value).size !== value.length) reject(path + ': duplicate IDs');
            value.forEach((item, index) => validate(schema.items, item, path + '[' + index + ']'));
        } else if (type === 'string') {
            if (value.length < schema.minLength || value.length > schema.maxLength
                    || (schema.pattern && !new RegExp(schema.pattern).test(value))) reject(path + ': invalid text');
        } else if (type === 'number' || type === 'integer') {
            if (value < schema.minimum || value > schema.maximum || value <= schema.exclusiveMinimum) reject(path + ': out of range');
        }
    }

    function normalize(contract, commandId, input) {
        if (!contract || contract.schemaVersion !== 1 || !contract.commands
                || !Object.hasOwn(contract.commands, commandId)) reject('Unsupported construction command');
        const schema = contract.commands[commandId];
        validate(schema, input, commandId);
        const result = clone(input);
        Object.entries(schema.properties).forEach(([key, spec]) => {
            if (!Object.hasOwn(result, key) && Object.hasOwn(spec, 'default')) result[key] = spec.default;
        });
        return result;
    }

    function entities(layout) {
        return new Map([['placements', 'placementId'], ['zones', 'zoneId'],
            ['floorMarkings', 'markingId'], ['routes', 'routeId']].flatMap(([collection, field]) =>
            (layout[collection] || []).map(item => [item[field], item])));
    }

    function prepare(contract, patterns, layout, catalog, commandId, input, requestId) {
        const args = normalize(contract, commandId, input);
        const factor = units[args.sourceUnit];
        const ids = args.seedIds || args.selectionIds || [args.supportId].concat(args.childIds);
        const index = entities(layout);
        if (new Set(ids).size !== ids.length) reject('Support cannot also be a child');
        ids.forEach(id => { if (!index.has(id)) reject('Unknown entity: ' + id); });
        if (ids.some(id => index.get(id).routeId)) reject('Routes cannot be pattern seeds');
        if (commandId !== 'linear-pattern' && ids.some(id => !index.get(id).placementId)) {
            reject('This command requires placement IDs');
        }
        if (commandId === 'linear-pattern') {
            ids.map(id => index.get(id)).filter(item => item.zoneId).forEach(zone => {
                if ((layout.zones || []).some(other => other.zoneId !== zone.zoneId && (
                    other.parentZoneId === zone.zoneId || (other.boundary || []).some(point =>
                        patterns.pointInPolygon(point, zone.boundary))
                ))) reject('Nested or intersecting zone patterns are unsupported');
            });
        }
        const seed = patterns.collectSelection(layout, catalog, ids, {
            expandZones: commandId === 'linear-pattern',
            includeZones: commandId === 'linear-pattern',
            strictGeometry: true,
        });
        const selected = new Set(seed.map(item => item.id));
        seed.forEach(item => {
            if (item.positionMode === 'locked') reject('Locked entity: ' + item.id);
            const relation = item.snapRelationship;
            if (relation && relation.family === 'vertical_stack') reject('Nested stack patterns are unsupported');
            if (relation && relation.supportPlacementId && !selected.has(relation.supportPlacementId)) {
                reject('Include the attached item\'s support: ' + relation.supportPlacementId);
            }
        });
        (layout.placements || []).forEach(item => {
            const relation = item.snapRelationship;
            if (relation && selected.has(relation.supportPlacementId) && !selected.has(item.placementId)) {
                reject('Include all attached children of a selected support');
            }
        });
        if (commandId === 'linear-pattern') {
            return { pattern: patterns.buildLinearPattern(seed, {
                count: args.count, pitch: args.spacing * factor, angleDegrees: angles[args.direction],
            }) };
        }
        if (commandId === 'cell-layout') {
            if (args.rows > seed.length) reject('Row count exceeds selected item count');
            if (seed.some(item => item.snapRelationship)) reject('Arrange supports before attaching children');
            return { pattern: patterns.buildCellLayout(seed, {
                shape: args.strategyId, width: args.targetBounds.width * factor,
                depth: args.targetBounds.depth * factor, gap: args.gap * factor,
                rows: args.rows, orientation: args.orientation,
                angleDegrees: args.angleDegrees, invertU: args.invertU,
            }) };
        }
        if (commandId === 'surface-stack') {
            const support = seed.find(item => item.id === args.supportId);
            if (!(support.supportSurfaces || []).some(surface => surface.surfaceId === args.surfaceId)) {
                reject('Published support surface is unavailable');
            }
            return { pattern: patterns.buildSurfaceStack(seed, {
                supportPlacementId: args.supportId, surfaceId: args.surfaceId,
                side: args.side === 'bottom' ? 'below' : 'above', gap: args.gap * factor,
                itemGap: args.itemGap * factor, inset: args.inset * factor,
            }) };
        }
        const bounds = patterns.selectionBounds(seed);
        const padding = args.envelopePadding * factor;
        const cell = { baseName: args.label, prefix: '', start: 1, numberPadding: 2,
            seriesId: 'command-cell-' + requestId, envelopePadding: padding,
            minX: bounds.minX - padding, minZ: bounds.minZ - padding,
            width: bounds.width + 2 * padding, depth: bounds.depth + 2 * padding };
        const boundary = [{ x: cell.minX, z: cell.minZ },
            { x: cell.minX + cell.width, z: cell.minZ },
            { x: cell.minX + cell.width, z: cell.minZ + cell.depth },
            { x: cell.minX, z: cell.minZ + cell.depth }];
        const occupants = patterns.collectSelection(Object.assign({}, layout, {
            zones: [{ zoneId: '__candidate_cell__', boundary, zoneType: 'workcell' }],
        }), catalog, ['__candidate_cell__'], { expandZones: true });
        if (occupants.some(item => item.kind !== 'zone' && !selected.has(item.id))) {
            reject('Cell envelope would capture unselected objects');
        }
        return { cell };
    }

    function fingerprint(state) {
        return JSON.stringify([state.draftRevision, state.commandJournalHash, state.editorGenerationId]);
    }

    function createAdapter(contract, patterns, session, getCatalog) {
        const receipts = new Map();
        let pending = false;
        return Object.freeze({
            async execute(request) {
                if (!request || Object.keys(request).some(key => !['commandId', 'arguments',
                    'expectedDraftRevision', 'requestId'].includes(key))) reject('Invalid command envelope');
                ['requestId', 'commandId', 'expectedDraftRevision'].forEach(key => {
                    if (typeof request[key] !== 'string' || !request[key].trim()) reject(key + ' is required');
                });
                if (!/^[A-Za-z0-9._:-]{1,100}$/.test(request.requestId)) reject('Invalid request ID');
                // Validate before JSON cloning so non-finite numbers cannot turn into null.
                normalize(contract, request.commandId, request.arguments);
                const signature = JSON.stringify(canonicalValue(request));
                const before = session.getState();
                if (receipts.has(request.requestId)) {
                    const prior = receipts.get(request.requestId);
                    if (prior.signature !== signature) reject('Request ID reused with different input', 'facility_command_idempotency_conflict');
                    if (prior.fingerprint !== fingerprint(before)) reject('Draft changed since command', 'facility_command_stale');
                    return clone(prior.receipt);
                }
                if (pending || before.busy) reject('Another edit is pending', 'facility_command_busy');
                if (before.draftRevision !== request.expectedDraftRevision) reject('Draft revision changed', 'facility_command_stale');
                if (receipts.size >= 128) reject('Command receipt budget exhausted');
                const catalog = getCatalog();
                const prepared = prepare(contract, patterns, before.layout, catalog,
                    request.commandId, request.arguments, request.requestId);
                pending = true;
                try {
                    if (prepared.cell) await session.createCellGroup(prepared.cell);
                    else await session.applyPattern(prepared.pattern, request.commandId);
                    const after = session.getState();
                    const oldEntities = entities(before.layout);
                    const newEntities = entities(after.layout);
                    const createdIds = Array.from(newEntities.keys()).filter(id => !oldEntities.has(id));
                    const changedIds = Array.from(newEntities.keys()).filter(id => oldEntities.has(id)
                        && JSON.stringify(oldEntities.get(id)) !== JSON.stringify(newEntities.get(id)));
                    const cells = (after.layout.zones || []).filter(zone =>
                        createdIds.includes(zone.zoneId) && zone.extensions && zone.extensions.cellGroup
                    ).map(zone => ({ cellId: zone.zoneId, memberIds: patterns.collectSelection(
                        after.layout, catalog, [zone.zoneId], { expandZones: true }
                    ).filter(item => item.kind !== 'zone').map(item => item.id) }));
                    const receipt = { commandId: request.commandId, requestId: request.requestId,
                        beforeDraftRevision: before.draftRevision, draftRevision: after.draftRevision,
                        createdIds, changedIds, cells, saved: false,
                        validationScope: 'existing session preview; not manufacturing or safety approval' };
                    receipts.set(request.requestId, { signature, fingerprint: fingerprint(after), receipt });
                    return clone(receipt);
                } finally { pending = false; }
            },
        });
    }

    return Object.freeze({ normalize, prepare, createAdapter });
}));
