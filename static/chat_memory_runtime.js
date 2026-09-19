(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProChatMemoryRuntime = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
    'use strict';

    const MEMORY_SCHEMA_VERSION = '1.0';
    const REQUEST_HASH_VERSION = 1;
    const MEMORY_MODES = new Set(['off', 'shadow', 'compare', 'enforce']);
    const SEMANTIC_TARGET_FIELDS = [
        'partOccurrenceIds',
        'processMapNodeIds',
        'processMapEdgeIds',
        'facilityPlacementIds',
        'faiCharacteristicIds',
    ];

    const UI_AGENT_BY_SERVER_TYPE = Object.freeze({
        inspector: 'inspector',
        'deviation-analyst': 'deviation-analyst',
        'parts-finder': 'parts-finder',
    });

    function clone(value) {
        return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
    }

    function sortedStrings(values) {
        return Array.from(new Set((Array.isArray(values) ? values : [])
            .map(value => String(value || '').trim())
            .filter(Boolean))).sort();
    }

    function normalizeSemanticTargets(value) {
        const source = value && typeof value === 'object' ? value : {};
        const result = {};
        SEMANTIC_TARGET_FIELDS.forEach(field => {
            result[field] = sortedStrings(source[field]);
        });
        return result;
    }

    function semanticTargetsFromAttachments(attachments) {
        const source = attachments && typeof attachments === 'object'
            ? attachments : {};
        const processSelection = source.process_map
            && source.process_map.state
            && source.process_map.state.selection || {};
        const facilitySelection = source.facility_layout
            && source.facility_layout.state
            && source.facility_layout.state.selection || {};
        const inspection = source.inspection || {};
        const assembly = source.assembly || {};
        return normalizeSemanticTargets({
            partOccurrenceIds: assembly.selected_occurrence_ids,
            processMapNodeIds: processSelection.nodeIds,
            processMapEdgeIds: processSelection.edgeIds,
            facilityPlacementIds: facilitySelection.placementIds,
            faiCharacteristicIds: inspection.selected_characteristic_ids,
        });
    }

    function createClientTurnId(randomUUID, now) {
        const timestamp = Number.isFinite(Number(now)) ? Number(now) : Date.now();
        let suffix = '';
        if (typeof randomUUID === 'function') {
            try { suffix = String(randomUUID() || '').trim(); } catch (_) {}
        }
        if (!suffix) {
            suffix = Math.random().toString(36).slice(2)
                + Math.random().toString(36).slice(2);
        }
        return 'client-turn:' + timestamp.toString(36) + ':' + suffix;
    }

    function decoratePayload(payload, options) {
        const source = clone(payload || {});
        const config = options && typeof options === 'object' ? options : {};
        const conversationId = String(config.conversationId || '').trim();
        const agentSessionId = String(config.agentSessionId || '').trim();
        const clientTurnId = String(config.clientTurnId || '').trim();
        if (!conversationId || !agentSessionId || !clientTurnId) {
            throw new Error('server memory identity is incomplete');
        }
        source.conversation_id = conversationId;
        source.agent_session_id = agentSessionId;
        source.client_turn_id = clientTurnId;
        source.memory_schema_version = MEMORY_SCHEMA_VERSION;
        source.request_hash_version = REQUEST_HASH_VERSION;
        source.request_context = {
            semantic_targets: normalizeSemanticTargets(config.semanticTargets),
        };
        source.action_parameters = clone(config.actionParameters || {});
        return source;
    }

    function frozenRequest(payload) {
        const result = clone(payload || {});
        const freeze = value => {
            if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
            Object.keys(value).forEach(key => freeze(value[key]));
            return Object.freeze(value);
        };
        return freeze(result);
    }

    function memoryError(responseStatus, body) {
        const detail = body && typeof body === 'object' ? body.detail : null;
        const error = detail && typeof detail === 'object' ? detail.error : null;
        const code = String(error && error.code || '').trim()
            || (Number(responseStatus) === 503 ? 'memory_unavailable' : 'agent_request_failed');
        const message = String(error && error.message || detail || '').trim()
            || ('API returned ' + responseStatus);
        return { code, message, status: Number(responseStatus) || 0 };
    }

    function normalizeMemoryMode(value) {
        const mode = String(value || '').trim().toLowerCase();
        return MEMORY_MODES.has(mode) ? mode : 'unknown';
    }

    function serverTypeToUiAgent(value) {
        return UI_AGENT_BY_SERVER_TYPE[String(value || '').trim().toLowerCase()] || null;
    }

    function serverConversationSummary(value) {
        const source = value && typeof value === 'object' ? value : {};
        const id = String(source.conversationId || '').trim();
        if (!id) throw new Error('server conversation is missing conversationId');
        return {
            id,
            title: String(source.title || 'New conversation'),
            createdAt: Date.parse(source.createdAt || '') || Date.now(),
            updatedAt: Date.parse(source.updatedAt || '') || Date.now(),
            lastTurnSequence: Number(source.lastTurnSequence || 0),
            backing: 'server',
            readOnly: false,
            serverRecord: clone(source),
        };
    }

    function markLegacyArchive(conversation) {
        const result = clone(conversation || {});
        result.backing = 'legacy';
        result.readOnly = true;
        result.legacyArchive = true;
        return result;
    }

    return Object.freeze({
        MEMORY_SCHEMA_VERSION,
        REQUEST_HASH_VERSION,
        SEMANTIC_TARGET_FIELDS: Object.freeze(SEMANTIC_TARGET_FIELDS.slice()),
        clone,
        sortedStrings,
        normalizeSemanticTargets,
        semanticTargetsFromAttachments,
        createClientTurnId,
        decoratePayload,
        frozenRequest,
        memoryError,
        normalizeMemoryMode,
        serverTypeToUiAgent,
        serverConversationSummary,
        markLegacyArchive,
    });
});
