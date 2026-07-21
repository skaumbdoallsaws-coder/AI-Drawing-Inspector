(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProUiActions = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    function clone(value) {
        return value == null ? value : JSON.parse(JSON.stringify(value));
    }

    function cleanField(value, rule) {
        const kind = rule && rule.type;
        if (kind === 'string') {
            if (typeof value !== 'string' || !value.trim()) return { error: 'must_be_nonempty_string' };
            return { value: value.trim().slice(0, Number(rule.max_length) || 240) };
        }
        if (kind === 'number') {
            if (typeof value !== 'number' || !Number.isFinite(value)) return { error: 'must_be_finite_number' };
            if (value < (rule.minimum ?? -Infinity) || value > (rule.maximum ?? Infinity)) {
                return { error: 'number_out_of_range' };
            }
            return { value };
        }
        if (kind === 'boolean') {
            return (typeof value === 'boolean') ? { value } : { error: 'must_be_boolean' };
        }
        if (kind === 'enum') {
            return Array.isArray(rule.values) && rule.values.includes(value)
                ? { value } : { error: 'invalid_enum' };
        }
        if (kind === 'string_array') {
            if (!Array.isArray(value)) return { error: 'must_be_string_array' };
            const out = [];
            for (const item of value) {
                if (typeof item !== 'string' || !item.trim()) return { error: 'must_be_string_array' };
                const token = item.trim().slice(0, 200);
                if (!out.includes(token)) out.push(token);
            }
            if (out.length > (Number(rule.max_items) || 30)) return { error: 'too_many_items' };
            return { value: out };
        }
        if (kind === 'object') {
            return value && typeof value === 'object' && !Array.isArray(value)
                ? { value: clone(value) } : { error: 'must_be_object' };
        }
        return { error: 'unknown_field_type' };
    }

    function validId(value, maxLength) {
        return typeof value === 'string'
            && value.length > 0
            && value.length <= (maxLength || 120)
            && /^[A-Za-z0-9._:-]+$/.test(value);
    }

    function validateBundle(contract, args) {
        if (!contract || contract.contract_version !== 1 || !contract.actions) {
            return { ok: false, errors: ['contract_unavailable'], bundle: null };
        }
        if (!args || typeof args !== 'object' || Array.isArray(args)) {
            return { ok: false, errors: ['bundle_invalid'], bundle: null };
        }
        const unknownBundleKeys = Object.keys(args).filter(k => !['workspace', 'actions'].includes(k));
        if (unknownBundleKeys.length) return { ok: false, errors: ['bundle_invalid_keys'], bundle: null };
        const workspace = String(args.workspace || 'assembly').trim();
        if (!Array.isArray(contract.workspaces) || !contract.workspaces.includes(workspace)) {
            return { ok: false, errors: ['workspace_not_allowed'], bundle: null };
        }
        if (!Array.isArray(args.actions) || args.actions.length === 0) {
            return { ok: false, errors: ['actions_required'], bundle: null };
        }
        if (args.actions.length > Number(contract.max_actions || 25)) {
            return { ok: false, errors: ['too_many_actions'], bundle: null };
        }
        const errors = [];
        const actions = [];
        const ids = new Set();
        args.actions.forEach((raw, index) => {
            const prefix = `action[${index}]`;
            if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
                errors.push(`${prefix}:must_be_object`);
                return;
            }
            const type = String(raw.type || '').trim();
            const spec = contract.actions[type];
            if (!spec) {
                errors.push(`${prefix}:unknown_type`);
                return;
            }
            const allowed = new Set(['type', 'action_id', ...Object.keys(spec.fields || {})]);
            if (Object.keys(raw).some(key => !allowed.has(key))) {
                errors.push(`${prefix}:unknown_fields`);
                return;
            }
            const actionId = String(raw.action_id || `a${index + 1}`).trim();
            if (!validId(actionId, 80) || ids.has(actionId)) {
                errors.push(`${prefix}:invalid_action_id`);
                return;
            }
            ids.add(actionId);
            const missing = (spec.required || []).find(field => !(field in raw));
            if (missing) {
                errors.push(`${prefix}:missing_${missing}`);
                return;
            }
            if ((spec.require_any || []).length && !spec.require_any.some(field => field in raw)) {
                errors.push(`${prefix}:missing_target`);
                return;
            }
            if ((spec.require_effect_any || []).length
                && !spec.require_effect_any.some(field => field in raw)) {
                errors.push(`${prefix}:missing_effect`);
                return;
            }
            const action = { type, action_id: actionId };
            for (const [field, value] of Object.entries(raw)) {
                if (field === 'type' || field === 'action_id') continue;
                const cleaned = cleanField(value, spec.fields[field]);
                if (cleaned.error) {
                    errors.push(`${prefix}:${field}:${cleaned.error}`);
                    return;
                }
                action[field] = cleaned.value;
            }
            actions.push(action);
        });
        if (errors.length) return { ok: false, errors, bundle: null };
        const types = new Set(actions.map(action => action.type));
        for (const conflict of (contract.conflicts || [])) {
            const conflictTypes = Array.isArray(conflict.types) ? conflict.types : [];
            if (conflictTypes.length && conflictTypes.every(type => types.has(type))) {
                errors.push(`conflict:${conflict.reason || 'conflicting_actions'}`);
            }
        }
        return errors.length
            ? { ok: false, errors, bundle: null }
            : { ok: true, errors: [], bundle: { workspace, actions } };
    }

    function stableDomainValue(domain, value) {
        const stable = clone(value ?? null);
        if (domain === 'motion' && stable && typeof stable === 'object') {
            delete stable.angle_deg;
        }
        return stable;
    }

    function equalDomain(domain, a, b) {
        return JSON.stringify(stableDomainValue(domain, a))
            === JSON.stringify(stableDomainValue(domain, b));
    }

    function targetParts(action) {
        const raw = Array.isArray(action.part_numbers)
            ? action.part_numbers : (action.part_number ? [action.part_number] : []);
        return raw.map(String);
    }

    function verifyPostcondition(contract, action, before, after, dispatchOk) {
        if (!dispatchOk) return { ok: false, error: 'dispatch_refused' };
        const spec = contract && contract.actions && contract.actions[action.type];
        if (!spec) return { ok: false, error: 'contract_action_missing' };
        for (const domain of (spec.preserves || [])) {
            if (!equalDomain(domain, before && before[domain], after && after[domain])) {
                return { ok: false, error: `unrelated_state_changed:${domain}` };
            }
        }
        const agentHighlights = new Set((after && after.highlight && after.highlight.agent) || []);
        const manualHighlights = new Set((after && after.highlight && after.highlight.manual) || []);
        const parts = targetParts(action);
        const overrides = (after && after.display && after.display.overrides) || {};
        const motion = (after && after.motion) || {};
        const rotation = (after && after.rotation) || {};
        const processMapSelection = after && after.process_map_selection;
        switch (action.type) {
            case 'set_process_map_part_scope':
                return processMapSelection
                    && processMapSelection.scope_occurrence_id === action.scope_occurrence_id
                    && Number(processMapSelection.total) > 0
                    ? { ok: true }
                    : { ok: false, error: 'process_map_scope_not_applied' };
            case 'clear_process_map_part_scope':
                return processMapSelection == null
                    ? { ok: true }
                    : { ok: false, error: 'process_map_scope_not_cleared' };
            case 'play_motion':
                return motion.playing ? { ok: true } : { ok: false, error: 'motion_not_playing' };
            case 'pause_motion':
            case 'stop_motion':
                return !motion.playing ? { ok: true } : { ok: false, error: 'motion_still_playing' };
            case 'set_motion_rpm':
                return Number.isFinite(Number(motion.rpm)) ? { ok: true } : { ok: false, error: 'rpm_not_applied' };
            case 'seek_motion':
                return Number.isFinite(Number(motion.angle_deg)) ? { ok: true } : { ok: false, error: 'seek_not_applied' };
            case 'set_part_highlight': {
                const mode = action.mode || 'replace';
                if (mode === 'remove') return parts.every(pn => !agentHighlights.has(pn))
                    ? { ok: true } : { ok: false, error: 'highlight_remove_failed' };
                if (mode === 'clear') return agentHighlights.size === 0
                    ? { ok: true } : { ok: false, error: 'highlight_clear_failed' };
                return parts.every(pn => agentHighlights.has(pn))
                    ? { ok: true } : { ok: false, error: 'highlight_not_applied' };
            }
            case 'clear_part_highlight':
                return agentHighlights.size === 0 && (action.all === false || manualHighlights.size === 0)
                    ? { ok: true } : { ok: false, error: 'highlight_clear_failed' };
            case 'set_part_display': {
                const hidden = action.hidden === true || action.visible === false
                    || ['hide', 'hidden'].includes(String(action.display || action.mode || ''));
                if (hidden) return parts.every(pn => overrides[pn] && overrides[pn].hidden === true)
                    ? { ok: true } : { ok: false, error: 'hide_not_applied' };
                if (typeof action.opacity === 'number') {
                    return parts.every(pn => overrides[pn]
                        && Math.abs(Number(overrides[pn].opacity) - action.opacity) < 0.001)
                        ? { ok: true } : { ok: false, error: 'opacity_not_applied' };
                }
                return parts.every(pn => !overrides[pn] || overrides[pn].hidden !== true)
                    ? { ok: true } : { ok: false, error: 'show_not_applied' };
            }
            case 'clear_part_display':
                return (action.all === true
                    ? Object.keys(overrides).length === 0
                    : parts.every(pn => !overrides[pn]))
                    ? { ok: true } : { ok: false, error: 'display_clear_failed' };
            case 'rotate_view': {
                const viewport = action.viewport === '3dmodel' || action.viewport === 'part'
                    ? 'part' : 'assembly';
                return rotation[viewport] === true
                    ? { ok: true } : { ok: false, error: 'rotation_not_started' };
            }
            case 'stop_rotate_view': {
                const viewport = action.viewport || 'current';
                const stopped = viewport === 'assembly' ? !rotation.assembly
                    : (viewport === '3dmodel' || viewport === 'part') ? !rotation.part
                    : (!rotation.assembly && !rotation.part);
                return stopped ? { ok: true } : { ok: false, error: 'rotation_still_active' };
            }
            case 'open_workspace':
                return (!action.tab || after.active_tab === action.tab)
                    ? { ok: true } : { ok: false, error: 'workspace_not_open' };
            default:
                return { ok: true };
        }
    }

    function makeReceipt(input) {
        const verification = input.verification || { ok: false, error: 'execution_failed' };
        const status = input.rejected ? 'rejected' : (verification.ok ? 'succeeded' : 'failed');
        return {
            contract_version: 1,
            receipt_id: String(input.receiptId),
            tool_call_id: String(input.toolCallId),
            action_id: String(input.action.action_id),
            tool_id: String(input.action.type),
            status,
            requested_args: clone(input.action),
            applied_args: clone(input.appliedArgs || {}),
            before: clone(input.before || {}),
            after: clone(input.after || {}),
            evidence: Array.isArray(input.evidence) ? input.evidence.slice(0, 12).map(String) : [],
            error: status === 'succeeded' ? null : String(input.error || verification.error || 'execution_failed').slice(0, 240),
            duration_ms: Math.max(0, Number(input.durationMs) || 0),
            timestamp: input.timestamp || new Date().toISOString(),
        };
    }

    return {
        validateBundle,
        verifyPostcondition,
        makeReceipt,
    };
});
