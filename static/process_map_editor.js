(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProProcessMap = api;
})(typeof window !== 'undefined' ? window : null, function () {
    'use strict';

    const NODE_WIDTH = 310;
    const NODE_HEIGHT = 170;
    const COLUMN_GAP = 130;
    const ROW_GAP = 44;
    const WORLD_PADDING = 80;
    const MIN_SCALE = 0.28;
    const MAX_SCALE = 1.6;
    const JUNCTION_HIT_SIZE = 24;
    const JUNCTION_DOT_SIZE = 9;
    const WIRE_SNAP_THRESHOLD_PX = 14;
    const MAX_NODE_LABEL_LENGTH = 120;
    const MAX_NODE_NOTE_LENGTH = 2000;
    const MAX_REFERENCE_NAME_LENGTH = 160;
    const MAX_REFERENCE_IDENTIFIER_LENGTH = 120;
    const MAX_REFERENCE_REVISION_LENGTH = 80;
    const MAX_REFERENCE_CLAUSE_LENGTH = 120;
    const MAX_REFERENCE_DETAILS_LENGTH = 1000;
    const MAX_REFERENCES_PER_TARGET = 24;
    const MAX_REFERENCE_CATALOG_ITEMS = 500;
    const MAX_DISMISSED_SUGGESTIONS = 500;
    const MAX_SUGGESTION_ID_LENGTH = 128;
    const PROCESS_MAP_LAYOUT_VERSION = 2;
    const GROUP_COLOR_KEYS = [
        'orange', 'blue', 'green', 'purple', 'red', 'teal', 'gray', 'yellow',
    ];
    const MAX_GROUP_LABEL_LENGTH = 120;
    const MAX_GROUP_DESCRIPTION_LENGTH = 2000;
    const MIN_GROUP_WIDTH = 220;
    const MIN_GROUP_HEIGHT = 112;
    const DEFAULT_GROUP_WIDTH = 660;
    const DEFAULT_GROUP_HEIGHT = 390;
    const GROUP_HEADER_OVERHANG = 28;
    const REFERENCE_KINDS = ['machine', 'tool', 'requirement', 'standard'];
    const PORT_ORIENTATIONS = ['horizontal', 'vertical'];
    const PORT_ORDERS = ['input_first', 'output_first'];
    const PROCESS_STEP_TYPES = [
        'operation',
        'inspection',
        'decision',
        'input',
        'output',
    ];
    const NODE_TYPES = ['assembly', 'subassembly'].concat(PROCESS_STEP_TYPES);
    let instanceCounter = 0;
    let floatingToolbarWarningShown = false;

    function cloneMap(processMap) {
        return JSON.parse(JSON.stringify(processMap || { nodes: [], edges: [] }));
    }

    function isPlacementMap(processMap) {
        return !!(processMap && (
            processMap.schemaVersion === 3
            || Array.isArray(processMap.canvasNodes)
            || Array.isArray(processMap.canvasEdges)
        ));
    }

    function mapNodes(processMap) {
        if (isPlacementMap(processMap)) {
            return Array.isArray(processMap && processMap.canvasNodes)
                ? processMap.canvasNodes
                : [];
        }
        return Array.isArray(processMap && processMap.nodes) ? processMap.nodes : [];
    }

    function mapEdges(processMap) {
        if (isPlacementMap(processMap)) {
            return Array.isArray(processMap && processMap.canvasEdges)
                ? processMap.canvasEdges
                : [];
        }
        return Array.isArray(processMap && processMap.edges) ? processMap.edges : [];
    }

    function setMapNodes(processMap, nodes) {
        if (isPlacementMap(processMap)) processMap.canvasNodes = nodes;
        else processMap.nodes = nodes;
    }

    function setMapEdges(processMap, edges) {
        if (isPlacementMap(processMap)) processMap.canvasEdges = edges;
        else processMap.edges = edges;
    }

    function mapGroups(processMap) {
        if (!isPlacementMap(processMap)) return [];
        return Array.isArray(processMap && processMap.canvasGroups)
            ? processMap.canvasGroups
            : [];
    }

    function setMapGroups(processMap, groups) {
        if (!isPlacementMap(processMap)) return;
        processMap.canvasGroups = groups;
        processMap.layoutVersion = Math.max(
            PROCESS_MAP_LAYOUT_VERSION,
            Number.isInteger(processMap.layoutVersion) ? processMap.layoutVersion : 0
        );
    }

    function mapReferenceCatalog(processMap) {
        return Array.isArray(processMap && processMap.referenceCatalog)
            ? processMap.referenceCatalog
            : [];
    }

    function pruneUnusedProcessReferences(processMap) {
        const next = cloneMap(processMap);
        const used = new Set();
        mapNodes(next).concat(mapEdges(next)).forEach(function (record) {
            (Array.isArray(record && record.referenceIds) ? record.referenceIds : []).forEach(
                function (referenceId) { used.add(referenceId); }
            );
        });
        const catalog = mapReferenceCatalog(next).filter(function (reference) {
            return reference && used.has(reference.referenceId);
        });
        if (catalog.length) next.referenceCatalog = catalog;
        else delete next.referenceCatalog;
        return next;
    }

    function mapFingerprint(processMap) {
        return JSON.stringify(processMap || { nodes: [], edges: [] });
    }

    function isJunctionNode(node) {
        return !!node && node.nodeKind === 'junction';
    }

    function nodePortOrientation(node) {
        return node && PORT_ORIENTATIONS.indexOf(node.portOrientation) >= 0
            ? node.portOrientation
            : 'horizontal';
    }

    function nodePortOrder(node) {
        return node && PORT_ORDERS.indexOf(node.portOrder) >= 0
            ? node.portOrder
            : 'input_first';
    }

    function selectedNodeCommandStates(processMap, selectedNodeId, selectedEdgeId, uiState) {
        const state = uiState || {};
        const selected = mapNodes(processMap).find(function (node) {
            return node && node.nodeId === selectedNodeId;
        }) || null;
        const placementMap = isPlacementMap(processMap);
        const junction = isJunctionNode(selected);
        const locked = !!state.saving || !!state.conflict;
        const typeOptions = placementMap ? PROCESS_STEP_TYPES : NODE_TYPES;
        const selectedType = placementMap
            ? (selected && selected.nodeKind === 'process_step' ? selected.processType : '')
            : (selected && selected.type);
        return {
            node: selected,
            isJunction: junction,
            locked: locked,
            typeOptions: typeOptions.slice(),
            selectedType: selectedType || '',
            orientation: nodePortOrientation(selected),
            portOrder: nodePortOrder(selected),
            canDelete: (!!selected || !!selectedEdgeId) && !locked,
            canRetype: !!selected && !junction
                && (!placementMap || selected.nodeKind === 'process_step') && !locked,
            canChangePorts: !!selected && !junction && !locked,
            canAddConnectedStep: !!selected && !junction && placementMap && !locked,
            canEditLabel: !!selected && !junction && !locked,
            canEditNote: !!selected && !junction && !locked,
            canPreview: !!selected && !junction
                && selected.nodeKind === 'product_occurrence'
                && !!state.hasPreview && !locked,
        };
    }

    function hasPrecedenceCycle(processMap) {
        const adjacency = new Map();
        mapNodes(processMap).forEach(function (node) {
            if (node && node.nodeId) adjacency.set(node.nodeId, []);
        });
        mapEdges(processMap).forEach(function (edge) {
            if (!edge || String(edge.kind || 'precedence') !== 'precedence') return;
            const fromId = edge.from && edge.from.nodeId;
            const toId = edge.to && edge.to.nodeId;
            if (!adjacency.has(fromId) || !adjacency.has(toId)) return;
            adjacency.get(fromId).push(toId);
        });
        const colors = new Map();
        function visit(nodeId) {
            const color = colors.get(nodeId) || 0;
            if (color === 1) return true;
            if (color === 2) return false;
            colors.set(nodeId, 1);
            const targets = adjacency.get(nodeId) || [];
            for (let index = 0; index < targets.length; index += 1) {
                if (visit(targets[index])) return true;
            }
            colors.set(nodeId, 2);
            return false;
        }
        return Array.from(adjacency.keys()).some(visit);
    }

    function addEdge(processMap, edge) {
        const next = cloneMap(processMap);
        if (!edge || !edge.from || !edge.to) return next;
        const fromId = String(edge.from.nodeId || '');
        const toId = String(edge.to.nodeId || '');
        const kind = String(edge.kind || 'precedence');
        if (!fromId || !toId || fromId === toId) return next;
        const duplicate = mapEdges(next).some(function (item) {
            return item && item.from && item.to
                && item.from.nodeId === fromId
                && item.to.nodeId === toId
                && String(item.kind || 'precedence') === kind;
        });
        if (duplicate) return next;
        const edges = mapEdges(next).slice();
        if (edge.edgeId && edges.some(function (item) {
            return item && item.edgeId === edge.edgeId;
        })) return next;
        const candidate = cloneMap(edge);
        if (candidate.edgeId && !candidate.logicalConnectionId) {
            candidate.logicalConnectionId = candidate.edgeId;
        }
        edges.push(candidate);
        setMapEdges(next, edges);
        return next;
    }

    function mapDismissedSuggestions(processMap) {
        return Array.isArray(processMap && processMap.dismissedSuggestions)
            ? processMap.dismissedSuggestions
            : [];
    }

    function dismissSuggestion(processMap, suggestionId) {
        const next = cloneMap(processMap);
        const cleanId = typeof suggestionId === 'string' ? suggestionId.trim() : '';
        if (!cleanId || cleanId.length > MAX_SUGGESTION_ID_LENGTH) return next;
        const dismissed = mapDismissedSuggestions(next).slice();
        if (dismissed.indexOf(cleanId) >= 0 || dismissed.length >= MAX_DISMISSED_SUGGESTIONS) {
            return next;
        }
        dismissed.push(cleanId);
        next.dismissedSuggestions = dismissed;
        return next;
    }

    function acceptSuggestions(processMap, suggestions) {
        let next = cloneMap(processMap);
        const accepted = [];
        const skipped = [];
        (Array.isArray(suggestions) ? suggestions : []).forEach(function (suggestion) {
            const suggestionId = String(suggestion && suggestion.suggestionId || '');
            const edge = suggestion && suggestion.edge;
            if (!edge) {
                skipped.push({ suggestionId: suggestionId, reason: 'not_an_edge' });
                return;
            }
            if (suggestion.validation && suggestion.validation.wouldCreateCycle) {
                skipped.push({ suggestionId: suggestionId, reason: 'would_create_cycle' });
                return;
            }
            const candidate = addEdge(next, edge);
            if (mapFingerprint(candidate) === mapFingerprint(next)) {
                skipped.push({ suggestionId: suggestionId, reason: 'duplicate_or_invalid' });
                return;
            }
            if (String(edge.kind || 'precedence') === 'precedence'
                && hasPrecedenceCycle(candidate)) {
                skipped.push({ suggestionId: suggestionId, reason: 'would_create_cycle' });
                return;
            }
            next = candidate;
            accepted.push(suggestionId);
        });
        return { map: next, accepted: accepted, skipped: skipped };
    }

    function _junctionHasUserMetadata(node) {
        if (!node) return false;
        return ['label', 'name', 'description', 'metadata'].some(function (key) {
            const value = node[key];
            if (value == null || value === '') return false;
            if (Array.isArray(value)) return value.length > 0;
            if (typeof value === 'object') return Object.keys(value).length > 0;
            return true;
        });
    }

    function _uniqueEdgeId(edges, preferred) {
        const used = new Set((edges || []).map(function (edge) {
            return edge && edge.edgeId;
        }).filter(Boolean));
        const base = String(preferred || 'pm-e-merged');
        if (!used.has(base)) return base;
        let suffix = 2;
        while (used.has(base + '-' + suffix)) suffix += 1;
        return base + '-' + suffix;
    }

    function _removeNodeIdsFromGroups(processMap, nodeIds) {
        if (!isPlacementMap(processMap) || !nodeIds || !nodeIds.size) return processMap;
        setMapGroups(processMap, mapGroups(processMap).map(function (group) {
            const nextGroup = cloneMap(group);
            nextGroup.memberNodeIds = (Array.isArray(nextGroup.memberNodeIds)
                ? nextGroup.memberNodeIds
                : []).filter(function (nodeId) { return !nodeIds.has(nodeId); });
            return nextGroup;
        }));
        return processMap;
    }

    function collapseRedundantJunctions(processMap) {
        const next = cloneMap(processMap);
        let changed = true;
        while (changed) {
            changed = false;
            const nodes = mapNodes(next);
            const edges = mapEdges(next);
            const junction = nodes.find(function (node) {
                if (!isJunctionNode(node) || _junctionHasUserMetadata(node)) return false;
                const incident = edges.filter(function (edge) {
                    return edge && edge.from && edge.to
                        && (edge.from.nodeId === node.nodeId || edge.to.nodeId === node.nodeId);
                });
                if (incident.length !== 2) return false;
                const incoming = incident.filter(function (edge) { return edge.to.nodeId === node.nodeId; });
                const outgoing = incident.filter(function (edge) { return edge.from.nodeId === node.nodeId; });
                if (incoming.length !== 1 || outgoing.length !== 1) return false;
                return !!incoming[0].logicalConnectionId
                    && incoming[0].logicalConnectionId === outgoing[0].logicalConnectionId
                    && String(incoming[0].kind || 'precedence') === String(outgoing[0].kind || 'precedence')
                    && incoming[0].from.nodeId !== outgoing[0].to.nodeId;
            });
            if (!junction) continue;
            const incident = edges.filter(function (edge) {
                return edge.from.nodeId === junction.nodeId || edge.to.nodeId === junction.nodeId;
            });
            const incoming = incident.find(function (edge) { return edge.to.nodeId === junction.nodeId; });
            const outgoing = incident.find(function (edge) { return edge.from.nodeId === junction.nodeId; });
            const remaining = edges.filter(function (edge) {
                return incident.indexOf(edge) < 0;
            });
            const merged = cloneMap(incoming);
            merged.edgeId = _uniqueEdgeId(remaining, incoming.logicalConnectionId);
            merged.from = cloneMap(incoming.from);
            merged.to = cloneMap(outgoing.to);
            if (!Object.prototype.hasOwnProperty.call(merged, 'label')
                && Object.prototype.hasOwnProperty.call(outgoing, 'label')) {
                merged.label = outgoing.label;
            }
            remaining.push(merged);
            setMapEdges(next, remaining);
            setMapNodes(next, nodes.filter(function (node) { return node.nodeId !== junction.nodeId; }));
            _removeNodeIdsFromGroups(next, new Set([junction.nodeId]));
            changed = true;
        }
        return next;
    }

    function deleteEdge(processMap, edgeId) {
        const next = cloneMap(processMap);
        setMapEdges(next, mapEdges(next).filter(function (edge) {
            return edge && edge.edgeId !== edgeId;
        }));
        return pruneUnusedProcessReferences(collapseRedundantJunctions(next));
    }

    function splitEdgeWithJunction(processMap, options) {
        const request = options || {};
        const next = cloneMap(processMap);
        if (!isPlacementMap(next) || !_finitePlacementPosition(request.position)) return next;
        const nodes = mapNodes(next);
        const edges = mapEdges(next);
        const sourceNodeId = String(request.sourceNodeId || '');
        const junctionNodeId = String(request.junctionNodeId || '');
        const firstEdgeId = String(request.firstEdgeId || '');
        const secondEdgeId = String(request.secondEdgeId || '');
        const branchEdgeId = String(request.branchEdgeId || '');
        const targetEdge = edges.find(function (edge) {
            return edge && edge.edgeId === request.targetEdgeId;
        });
        if (!targetEdge || !targetEdge.from || !targetEdge.to
            || !sourceNodeId || !junctionNodeId || !firstEdgeId || !secondEdgeId || !branchEdgeId
            || sourceNodeId === targetEdge.from.nodeId || sourceNodeId === targetEdge.to.nodeId
            || !nodes.some(function (node) { return node && node.nodeId === sourceNodeId; })
            || nodes.some(function (node) { return node && node.nodeId === junctionNodeId; })) return next;
        const newIds = [firstEdgeId, secondEdgeId, branchEdgeId];
        if (new Set(newIds).size !== newIds.length || edges.some(function (edge) {
            return edge && newIds.indexOf(edge.edgeId) >= 0;
        })) return next;

        const logicalConnectionId = String(
            targetEdge.logicalConnectionId || targetEdge.edgeId || firstEdgeId
        );
        const junction = {
            nodeId: junctionNodeId,
            nodeKind: 'junction',
            junctionType: 'wire_branch',
            position: { x: request.position.x, y: request.position.y },
        };
        const first = cloneMap(targetEdge);
        first.edgeId = firstEdgeId;
        first.to = { nodeId: junctionNodeId, port: 'in' };
        first.logicalConnectionId = logicalConnectionId;
        const second = cloneMap(targetEdge);
        second.edgeId = secondEdgeId;
        second.from = { nodeId: junctionNodeId, port: 'out' };
        second.logicalConnectionId = logicalConnectionId;
        delete second.label;
        const branch = {
            edgeId: branchEdgeId,
            from: { nodeId: sourceNodeId, port: 'out' },
            to: { nodeId: junctionNodeId, port: 'in' },
            kind: String(request.kind || 'precedence'),
            logicalConnectionId: String(request.branchLogicalConnectionId || branchEdgeId),
        };
        setMapNodes(next, nodes.concat([junction]));
        setMapEdges(next, edges.filter(function (edge) {
            return edge.edgeId !== targetEdge.edgeId;
        }).concat([first, second, branch]));
        if (!hasPrecedenceCycle(processMap) && hasPrecedenceCycle(next)) return cloneMap(processMap);
        return next;
    }

    function addCanvasNode(processMap, node) {
        const next = cloneMap(processMap);
        if (!node || !node.nodeId || !_finitePlacementPosition(node.position)) return next;
        const nodes = mapNodes(next);
        if (nodes.some(function (item) { return item && item.nodeId === node.nodeId; })) return next;
        if (node.nodeKind === 'product_occurrence') {
            const sourceId = String(node.sourceOccurrenceId || '');
            if (!sourceId || nodes.some(function (item) {
                return item && item.nodeKind === 'product_occurrence'
                    && item.sourceOccurrenceId === sourceId;
            })) return next;
        }
        setMapNodes(next, nodes.concat([cloneMap(node)]));
        return next;
    }

    function deleteNode(processMap, nodeId) {
        const next = cloneMap(processMap);
        setMapNodes(next, mapNodes(next).filter(function (node) {
            return node && node.nodeId !== nodeId;
        }));
        setMapEdges(next, mapEdges(next).filter(function (edge) {
            return edge && edge.from && edge.to
                && edge.from.nodeId !== nodeId
                && edge.to.nodeId !== nodeId;
        }));
        _removeNodeIdsFromGroups(next, new Set([nodeId]));
        return pruneUnusedProcessReferences(collapseRedundantJunctions(next));
    }

    function _finitePlacementPosition(position) {
        return !!position && finiteNumber(position.x) && finiteNumber(position.y);
    }

    function moveNode(processMap, nodeId, position) {
        const next = cloneMap(processMap);
        const node = mapNodes(next).find(function (item) {
            return item && item.nodeId === nodeId;
        });
        if (node && position && finiteNumber(position.x) && finiteNumber(position.y)) {
            node.position = { x: position.x, y: position.y };
        }
        return next;
    }

    function _finiteGroupSize(size) {
        return !!size
            && finiteNumber(size.width)
            && finiteNumber(size.height)
            && size.width >= MIN_GROUP_WIDTH
            && size.height >= MIN_GROUP_HEIGHT;
    }

    function _validGroupPosition(position) {
        return !!position && finiteNumber(position.x) && finiteNumber(position.y);
    }

    function groupContainsPoint(group, point) {
        return !!group
            && _validGroupPosition(group.position)
            && _finiteGroupSize(group.size)
            && point
            && finiteNumber(point.x)
            && finiteNumber(point.y)
            && point.x >= group.position.x
            && point.x <= group.position.x + group.size.width
            && point.y >= group.position.y
            && point.y <= group.position.y + group.size.height;
    }

    function smallestContainingGroup(processMap, point) {
        return mapGroups(processMap).filter(function (group) {
            return groupContainsPoint(group, point);
        }).sort(function (left, right) {
            const leftArea = left.size.width * left.size.height;
            const rightArea = right.size.width * right.size.height;
            if (leftArea !== rightArea) return leftArea - rightArea;
            return String(left.groupId || '').localeCompare(String(right.groupId || ''));
        })[0] || null;
    }

    function addGroup(processMap, group) {
        const next = cloneMap(processMap);
        if (!isPlacementMap(next) || !group || typeof group !== 'object') return next;
        const groupId = typeof group.groupId === 'string' ? group.groupId.trim() : '';
        const label = typeof group.label === 'string' ? group.label.trim() : '';
        const description = typeof group.description === 'string'
            ? group.description.trim()
            : '';
        if (!groupId || !label || label.length > MAX_GROUP_LABEL_LENGTH
            || description.length > MAX_GROUP_DESCRIPTION_LENGTH
            || !_validGroupPosition(group.position)
            || !_finiteGroupSize(group.size)
            || GROUP_COLOR_KEYS.indexOf(group.colorKey) < 0
            || mapGroups(next).some(function (item) {
                return item && item.groupId === groupId;
            })) return next;
        const candidate = cloneMap(group);
        candidate.groupId = groupId;
        candidate.label = label;
        if (description) candidate.description = description;
        else delete candidate.description;
        candidate.position = { x: group.position.x, y: group.position.y };
        candidate.size = { width: group.size.width, height: group.size.height };
        candidate.colorKey = group.colorKey;
        candidate.memberNodeIds = [];
        candidate.collapsed = false;
        setMapGroups(next, mapGroups(next).concat([candidate]));
        return setGroupMembers(next, groupId, group.memberNodeIds || []);
    }

    function moveGroup(processMap, groupId, position, withMembers) {
        const next = cloneMap(processMap);
        const group = mapGroups(next).find(function (item) {
            return item && item.groupId === groupId;
        });
        if (!group || !_validGroupPosition(group.position) || !_validGroupPosition(position)) {
            return next;
        }
        const dx = position.x - group.position.x;
        const dy = position.y - group.position.y;
        group.position = { x: position.x, y: position.y };
        if (withMembers !== false && (dx || dy)) {
            const members = new Set(Array.isArray(group.memberNodeIds) ? group.memberNodeIds : []);
            mapNodes(next).forEach(function (node) {
                if (!node || !members.has(node.nodeId) || !_finitePlacementPosition(node.position)) return;
                node.position = { x: node.position.x + dx, y: node.position.y + dy };
            });
        }
        setMapGroups(next, mapGroups(next));
        return next;
    }

    function resizeGroup(processMap, groupId, geometry) {
        const next = cloneMap(processMap);
        const group = mapGroups(next).find(function (item) {
            return item && item.groupId === groupId;
        });
        const value = geometry || {};
        const position = value.position || (group && group.position);
        const size = value.size || (group && group.size);
        if (!group || !_validGroupPosition(position) || !_finiteGroupSize(size)) return next;
        group.position = { x: position.x, y: position.y };
        group.size = { width: size.width, height: size.height };
        setMapGroups(next, mapGroups(next));
        return next;
    }

    function renameGroup(processMap, groupId, label, description) {
        const next = cloneMap(processMap);
        const group = mapGroups(next).find(function (item) {
            return item && item.groupId === groupId;
        });
        const nextLabel = typeof label === 'string' ? label.trim() : '';
        const nextDescription = typeof description === 'string' ? description.trim() : null;
        if (!group || !nextLabel || nextLabel.length > MAX_GROUP_LABEL_LENGTH
            || (nextDescription != null && nextDescription.length > MAX_GROUP_DESCRIPTION_LENGTH)) {
            return next;
        }
        group.label = nextLabel;
        if (nextDescription) group.description = nextDescription;
        else if (nextDescription != null) delete group.description;
        setMapGroups(next, mapGroups(next));
        return next;
    }

    function recolorGroup(processMap, groupId, colorKey) {
        const next = cloneMap(processMap);
        const group = mapGroups(next).find(function (item) {
            return item && item.groupId === groupId;
        });
        if (!group || GROUP_COLOR_KEYS.indexOf(colorKey) < 0) return next;
        group.colorKey = colorKey;
        setMapGroups(next, mapGroups(next));
        return next;
    }

    function setGroupMembers(processMap, groupId, memberNodeIds) {
        const next = cloneMap(processMap);
        const groups = mapGroups(next);
        const target = groups.find(function (group) {
            return group && group.groupId === groupId;
        });
        if (!target || !Array.isArray(memberNodeIds)) return next;
        const knownNodeIds = new Set(mapNodes(next).map(function (node) {
            return node && node.nodeId;
        }).filter(Boolean));
        const desired = [];
        const desiredSet = new Set();
        memberNodeIds.forEach(function (nodeId) {
            if (typeof nodeId !== 'string' || !knownNodeIds.has(nodeId) || desiredSet.has(nodeId)) return;
            desiredSet.add(nodeId);
            desired.push(nodeId);
        });
        groups.forEach(function (group) {
            if (!group) return;
            if (group.groupId === groupId) group.memberNodeIds = desired.slice();
            else group.memberNodeIds = (Array.isArray(group.memberNodeIds)
                ? group.memberNodeIds
                : []).filter(function (nodeId) { return !desiredSet.has(nodeId); });
        });
        setMapGroups(next, groups);
        return next;
    }

    function resolveNodeGroupMembership(processMap, nodeId, center) {
        const next = cloneMap(processMap);
        if (!mapNodes(next).some(function (node) { return node && node.nodeId === nodeId; })) {
            return next;
        }
        const target = smallestContainingGroup(next, center);
        const groups = mapGroups(next);
        groups.forEach(function (group) {
            if (!group) return;
            const members = (Array.isArray(group.memberNodeIds) ? group.memberNodeIds : [])
                .filter(function (memberId) { return memberId !== nodeId; });
            if (target && group.groupId === target.groupId) members.push(nodeId);
            group.memberNodeIds = members;
        });
        setMapGroups(next, groups);
        return next;
    }

    function deleteGroup(processMap, groupId) {
        const next = cloneMap(processMap);
        if (!isPlacementMap(next)) return next;
        setMapGroups(next, mapGroups(next).filter(function (group) {
            return group && group.groupId !== groupId;
        }));
        return next;
    }

    function setNodeLabel(processMap, nodeId, value) {
        const next = cloneMap(processMap);
        const node = mapNodes(next).find(function (item) {
            return item && item.nodeId === nodeId;
        });
        if (!node || isJunctionNode(node) || typeof value !== 'string') return next;
        const label = value.trim();
        if (label.length > MAX_NODE_LABEL_LENGTH) return next;
        if (isPlacementMap(next) && node.nodeKind === 'product_occurrence') {
            if (label) node.labelOverride = label;
            else delete node.labelOverride;
        } else if (label) {
            node.name = label;
        }
        return next;
    }

    function setNodeNote(processMap, nodeId, value) {
        const next = cloneMap(processMap);
        const node = mapNodes(next).find(function (item) {
            return item && item.nodeId === nodeId;
        });
        if (!node || isJunctionNode(node) || typeof value !== 'string') return next;
        const note = value.trim();
        if (note.length > MAX_NODE_NOTE_LENGTH) return next;
        if (note) node.note = note;
        else delete node.note;
        return next;
    }

    function _trimmedReferenceField(value, maximum) {
        if (typeof value !== 'string') return '';
        const trimmed = value.trim();
        return trimmed.length <= maximum ? trimmed : '';
    }

    function normalizeProcessReference(reference) {
        const value = reference && typeof reference === 'object' ? reference : {};
        const kind = REFERENCE_KINDS.indexOf(value.kind) >= 0 ? value.kind : '';
        const name = _trimmedReferenceField(value.name, MAX_REFERENCE_NAME_LENGTH);
        const identifier = _trimmedReferenceField(
            value.identifier,
            MAX_REFERENCE_IDENTIFIER_LENGTH
        );
        const revision = _trimmedReferenceField(value.revision, MAX_REFERENCE_REVISION_LENGTH);
        const clause = _trimmedReferenceField(value.clause, MAX_REFERENCE_CLAUSE_LENGTH);
        const details = _trimmedReferenceField(value.details, MAX_REFERENCE_DETAILS_LENGTH);
        if (!kind || !name || (kind === 'standard' && !identifier)) return null;
        const normalized = {
            referenceId: String(value.referenceId || '').trim(),
            kind: kind,
            name: name,
        };
        if (identifier) normalized.identifier = identifier;
        if (revision) normalized.revision = revision;
        if (clause) normalized.clause = clause;
        if (details) normalized.details = details;
        return normalized;
    }

    function _referenceIdentity(reference) {
        return [
            reference && reference.kind,
            reference && reference.name,
            reference && reference.identifier,
            reference && reference.revision,
            reference && reference.clause,
        ].map(function (value) {
            return String(value || '').trim().toLowerCase();
        }).join('|');
    }

    function _targetReferenceRecords(processMap, targetType, targetId) {
        if (targetType === 'node') {
            const node = mapNodes(processMap).find(function (item) {
                return item && item.nodeId === targetId;
            });
            return node && !isJunctionNode(node) ? [node] : [];
        }
        if (targetType !== 'edge') return [];
        const target = mapEdges(processMap).find(function (edge) {
            return edge && edge.edgeId === targetId;
        });
        if (!target) return [];
        const logicalId = target.logicalConnectionId || target.edgeId;
        return mapEdges(processMap).filter(function (edge) {
            return edge && (edge.logicalConnectionId || edge.edgeId) === logicalId;
        });
    }

    function referenceItemsForTarget(processMap, targetType, targetId) {
        const records = _targetReferenceRecords(processMap, targetType, targetId);
        const ids = new Set();
        records.forEach(function (record) {
            (Array.isArray(record.referenceIds) ? record.referenceIds : []).forEach(function (id) {
                ids.add(id);
            });
        });
        return mapReferenceCatalog(processMap).filter(function (reference) {
            return reference && ids.has(reference.referenceId);
        });
    }

    function attachProcessReference(processMap, request) {
        const next = cloneMap(processMap);
        const options = request || {};
        const records = _targetReferenceRecords(next, options.targetType, options.targetId);
        if (!records.length) return next;
        let catalog = mapReferenceCatalog(next).slice();
        let reference = normalizeProcessReference(options.reference);
        if (!reference) return next;
        const requestedId = reference.referenceId;
        const existingById = requestedId && catalog.find(function (item) {
            return item && item.referenceId === requestedId;
        });
        const identity = _referenceIdentity(reference);
        const existingByIdentity = catalog.find(function (item) {
            return item && _referenceIdentity(item) === identity;
        });
        reference = existingById || existingByIdentity || reference;
        if (!reference.referenceId) return next;
        if (!existingById && !existingByIdentity) {
            if (catalog.length >= MAX_REFERENCE_CATALOG_ITEMS) return next;
            catalog.push(reference);
        }
        const referenceId = reference.referenceId;
        records.forEach(function (record) {
            const ids = Array.isArray(record.referenceIds) ? record.referenceIds.slice() : [];
            if (ids.indexOf(referenceId) < 0 && ids.length < MAX_REFERENCES_PER_TARGET) {
                ids.push(referenceId);
            }
            if (ids.length) record.referenceIds = ids;
        });
        next.referenceCatalog = catalog;
        return next;
    }

    function detachProcessReference(processMap, request) {
        const next = cloneMap(processMap);
        const options = request || {};
        const referenceId = String(options.referenceId || '').trim();
        const records = _targetReferenceRecords(next, options.targetType, options.targetId);
        if (!referenceId || !records.length) return next;
        records.forEach(function (record) {
            const ids = (Array.isArray(record.referenceIds) ? record.referenceIds : []).filter(
                function (id) { return id !== referenceId; }
            );
            if (ids.length) record.referenceIds = ids;
            else delete record.referenceIds;
        });
        const stillUsed = mapNodes(next).concat(mapEdges(next)).some(function (record) {
            return Array.isArray(record && record.referenceIds)
                && record.referenceIds.indexOf(referenceId) >= 0;
        });
        if (!stillUsed) {
            next.referenceCatalog = mapReferenceCatalog(next).filter(function (item) {
                return item && item.referenceId !== referenceId;
            });
        }
        if (!mapReferenceCatalog(next).length) delete next.referenceCatalog;
        return next;
    }

    function setEdgeLabel(processMap, edgeId, value) {
        const next = cloneMap(processMap);
        const edge = mapEdges(next).find(function (item) {
            return item && item.edgeId === edgeId;
        });
        if (!edge || typeof value !== 'string') return next;
        const label = value.trim();
        if (label.length > MAX_NODE_LABEL_LENGTH) return next;
        const logicalId = edge.logicalConnectionId || edge.edgeId;
        mapEdges(next).forEach(function (item) {
            if (item && (item.logicalConnectionId || item.edgeId) === logicalId) {
                delete item.label;
            }
        });
        if (label) edge.label = label;
        return next;
    }

    function logicalEdgeLabel(processMap, edgeId) {
        const edge = mapEdges(processMap).find(function (item) {
            return item && item.edgeId === edgeId;
        });
        if (!edge) return '';
        const logicalId = edge.logicalConnectionId || edge.edgeId;
        const owner = mapEdges(processMap).find(function (item) {
            return item && (item.logicalConnectionId || item.edgeId) === logicalId
                && typeof item.label === 'string' && item.label.trim();
        });
        return owner ? owner.label.trim() : '';
    }

    function referenceSummary(referenceItems) {
        const counts = { machine: 0, tool: 0, requirement: 0, standard: 0 };
        (Array.isArray(referenceItems) ? referenceItems : []).forEach(function (reference) {
            if (reference && Object.prototype.hasOwnProperty.call(counts, reference.kind)) {
                counts[reference.kind] += 1;
            }
        });
        return REFERENCE_KINDS.filter(function (kind) { return counts[kind] > 0; }).map(
            function (kind) { return { kind: kind, count: counts[kind] }; }
        );
    }

    function referenceKindShortLabel(kind) {
        return {
            machine: 'M',
            tool: 'T',
            requirement: 'Req',
            standard: 'Std',
        }[kind] || String(kind || '');
    }

    function _rectanglesOverlap(left, right, margin) {
        const gap = Number(margin) || 0;
        return left.x < right.x + right.width + gap
            && left.x + left.width + gap > right.x
            && left.y < right.y + right.height + gap
            && left.y + left.height + gap > right.y;
    }

    function connectedStepPosition(processMap, sourceNode) {
        const orientation = nodePortOrientation(sourceNode);
        const order = nodePortOrder(sourceNode);
        const direction = portDirection(orientation, order, 'out');
        const sourcePosition = sourceNode.position;
        const base = {
            x: sourcePosition.x + direction.x * (NODE_WIDTH + COLUMN_GAP),
            y: sourcePosition.y + direction.y * (NODE_HEIGHT + ROW_GAP + 50),
        };
        const occupied = mapNodes(processMap).filter(function (node) {
            return node && node.nodeId !== sourceNode.nodeId && _finitePlacementPosition(node.position);
        }).map(function (node) {
            return {
                x: node.position.x,
                y: node.position.y,
                width: isJunctionNode(node) ? JUNCTION_HIT_SIZE : NODE_WIDTH,
                height: isJunctionNode(node) ? JUNCTION_HIT_SIZE : NODE_HEIGHT,
            };
        });
        for (let attempt = 0; attempt < 16; attempt += 1) {
            const lane = attempt === 0 ? 0 : Math.ceil(attempt / 2) * (attempt % 2 ? 1 : -1);
            const candidate = {
                x: base.x + (orientation === 'vertical' ? lane * (NODE_WIDTH + 34) : 0),
                y: base.y + (orientation === 'horizontal' ? lane * (NODE_HEIGHT + 34) : 0),
            };
            const bounds = { x: candidate.x, y: candidate.y, width: NODE_WIDTH, height: NODE_HEIGHT };
            if (!occupied.some(function (rect) { return _rectanglesOverlap(bounds, rect, 24); })) {
                return candidate;
            }
        }
        return base;
    }

    function addConnectedProcessStep(processMap, request) {
        const next = cloneMap(processMap);
        const options = request || {};
        if (!isPlacementMap(next) || PROCESS_STEP_TYPES.indexOf(options.processType) < 0
            || !options.nodeId || !options.edgeId) return next;
        const source = mapNodes(next).find(function (node) {
            return node && node.nodeId === options.sourceNodeId;
        });
        if (!source || isJunctionNode(source) || !_finitePlacementPosition(source.position)
            || mapNodes(next).some(function (node) { return node && node.nodeId === options.nodeId; })
            || mapEdges(next).some(function (edge) { return edge && edge.edgeId === options.edgeId; })) {
            return next;
        }
        const label = options.processType.charAt(0).toUpperCase() + options.processType.slice(1);
        const node = {
            nodeId: options.nodeId,
            nodeKind: 'process_step',
            processType: options.processType,
            name: 'New ' + label,
            description: '',
            position: connectedStepPosition(next, source),
            portOrientation: nodePortOrientation(source),
            portOrder: nodePortOrder(source),
        };
        setMapNodes(next, mapNodes(next).concat([node]));
        setMapEdges(next, mapEdges(next).concat([{
            edgeId: options.edgeId,
            from: { nodeId: source.nodeId, port: 'out' },
            to: { nodeId: node.nodeId, port: 'in' },
            kind: 'precedence',
        }]));
        return next;
    }

    function setNodePortOrientation(processMap, nodeId, orientation) {
        const next = cloneMap(processMap);
        if (PORT_ORIENTATIONS.indexOf(orientation) < 0) return next;
        const node = mapNodes(next).find(function (item) {
            return item && item.nodeId === nodeId;
        });
        if (node && !isJunctionNode(node)) node.portOrientation = orientation;
        return next;
    }

    function setNodePortOrder(processMap, nodeId, order) {
        const next = cloneMap(processMap);
        if (PORT_ORDERS.indexOf(order) < 0) return next;
        const node = mapNodes(next).find(function (item) {
            return item && item.nodeId === nodeId;
        });
        if (node && !isJunctionNode(node)) node.portOrder = order;
        return next;
    }

    function retypeNode(processMap, nodeId, nodeType) {
        const next = cloneMap(processMap);
        const validTypes = isPlacementMap(next) ? PROCESS_STEP_TYPES : NODE_TYPES;
        if (validTypes.indexOf(nodeType) < 0) return next;
        const node = mapNodes(next).find(function (item) {
            return item && item.nodeId === nodeId;
        });
        if (node && (!isPlacementMap(next) || node.nodeKind === 'process_step')) {
            if (isPlacementMap(next)) node.processType = nodeType;
            else node.type = nodeType;
        }
        return next;
    }

    function SnapshotHistory(limit) {
        this.limit = Math.max(1, Number(limit) || 50);
        this.undoStack = [];
        this.redoStack = [];
    }

    SnapshotHistory.prototype.record = function (processMap) {
        this.undoStack.push(cloneMap(processMap));
        if (this.undoStack.length > this.limit) this.undoStack.shift();
        this.redoStack = [];
    };

    SnapshotHistory.prototype.undo = function (currentMap) {
        if (!this.undoStack.length) return null;
        this.redoStack.push(cloneMap(currentMap));
        return this.undoStack.pop();
    };

    SnapshotHistory.prototype.redo = function (currentMap) {
        if (!this.redoStack.length) return null;
        this.undoStack.push(cloneMap(currentMap));
        return this.redoStack.pop();
    };

    SnapshotHistory.prototype.clear = function () {
        this.undoStack = [];
        this.redoStack = [];
    };

    function finiteNumber(value) {
        return typeof value === 'number' && Number.isFinite(value);
    }

    function sortedNodes(nodes) {
        return (Array.isArray(nodes) ? nodes : []).slice().sort(function (left, right) {
            const leftOrder = finiteNumber(left && left.suggestedBuildOrder)
                ? left.suggestedBuildOrder
                : Number.MAX_SAFE_INTEGER;
            const rightOrder = finiteNumber(right && right.suggestedBuildOrder)
                ? right.suggestedBuildOrder
                : Number.MAX_SAFE_INTEGER;
            if (leftOrder !== rightOrder) return leftOrder - rightOrder;
            return String((left && left.nodeId) || '').localeCompare(String((right && right.nodeId) || ''));
        });
    }

    function scopedNodes(processMap, focusNodeId) {
        const nodes = mapNodes(processMap);
        if (isPlacementMap(processMap)) return sortedNodes(nodes);
        if (focusNodeId) {
            const children = sortedNodes(nodes.filter(function (node) {
                return node && node.parentNodeId === focusNodeId;
            }));
            if (children.length) return children;
            const focused = nodes.find(function (node) { return node && node.nodeId === focusNodeId; });
            return focused ? [focused] : [];
        }
        const levelNodes = sortedNodes(nodes.filter(function (node) {
            return node && node.level === 1;
        })).concat(sortedNodes(nodes.filter(function (node) {
            return node && node.level === 2;
        })));
        if (levelNodes.length) return levelNodes;

        const roots = nodes.filter(function (node) { return node && node.parentNodeId == null; });
        const rootIds = new Set(roots.map(function (node) { return node.nodeId; }));
        const firstLevel = nodes.filter(function (node) {
            return node && rootIds.has(node.parentNodeId);
        });
        const firstIds = new Set(firstLevel.map(function (node) { return node.nodeId; }));
        return sortedNodes(firstLevel.concat(nodes.filter(function (node) {
            return node && firstIds.has(node.parentNodeId);
        })));
    }

    function visibleEdges(processMap, visibleNodes) {
        const visibleIds = new Set((visibleNodes || []).map(function (node) { return node.nodeId; }));
        return mapEdges(processMap).filter(function (edge) {
            const fromId = edge && edge.from && edge.from.nodeId;
            const toId = edge && edge.to && edge.to.nodeId;
            return visibleIds.has(fromId) && visibleIds.has(toId);
        });
    }

    function layeredLayout(nodes, edges, options) {
        const opts = options || {};
        const width = finiteNumber(opts.nodeWidth) ? opts.nodeWidth : NODE_WIDTH;
        const height = finiteNumber(opts.nodeHeight) ? opts.nodeHeight : NODE_HEIGHT;
        const columnGap = finiteNumber(opts.columnGap) ? opts.columnGap : COLUMN_GAP;
        const rowGap = finiteNumber(opts.rowGap) ? opts.rowGap : ROW_GAP;
        const padding = finiteNumber(opts.padding) ? opts.padding : WORLD_PADDING;
        const list = sortedNodes(nodes);
        const byId = new Map(list.map(function (node) { return [node.nodeId, node]; }));
        const incoming = new Map(list.map(function (node) { return [node.nodeId, 0]; }));
        const adjacency = new Map(list.map(function (node) { return [node.nodeId, []]; }));
        let precedenceCount = 0;

        (Array.isArray(edges) ? edges : []).forEach(function (edge) {
            if (!edge || edge.kind !== 'precedence') return;
            const fromId = edge.from && edge.from.nodeId;
            const toId = edge.to && edge.to.nodeId;
            if (!byId.has(fromId) || !byId.has(toId) || fromId === toId) return;
            adjacency.get(fromId).push(toId);
            incoming.set(toId, incoming.get(toId) + 1);
            precedenceCount += 1;
        });

        const ranks = new Map();
        if (precedenceCount) {
            const queue = sortedNodes(list.filter(function (node) {
                return incoming.get(node.nodeId) === 0;
            }));
            queue.forEach(function (node) { ranks.set(node.nodeId, 0); });
            let cursor = 0;
            while (cursor < queue.length) {
                const node = queue[cursor++];
                const nextRank = (ranks.get(node.nodeId) || 0) + 1;
                adjacency.get(node.nodeId).slice().sort().forEach(function (targetId) {
                    ranks.set(targetId, Math.max(ranks.get(targetId) || 0, nextRank));
                    incoming.set(targetId, incoming.get(targetId) - 1);
                    if (incoming.get(targetId) === 0) queue.push(byId.get(targetId));
                });
            }
        }

        const numericLevels = list
            .map(function (node) { return finiteNumber(node.level) ? node.level : null; })
            .filter(function (level) { return level != null; });
        const minimumLevel = numericLevels.length ? Math.min.apply(null, numericLevels) : 0;
        list.forEach(function (node) {
            if (!ranks.has(node.nodeId)) {
                const level = finiteNumber(node.level) ? node.level : minimumLevel;
                ranks.set(node.nodeId, Math.max(0, level - minimumLevel));
            }
        });

        const columns = new Map();
        list.forEach(function (node) {
            const rank = ranks.get(node.nodeId) || 0;
            if (!columns.has(rank)) columns.set(rank, []);
            columns.get(rank).push(node);
        });

        const positions = {};
        Array.from(columns.keys()).sort(function (a, b) { return a - b; }).forEach(function (rank) {
            sortedNodes(columns.get(rank)).forEach(function (node, rowIndex) {
                const saved = node && node.position;
                const junction = isJunctionNode(node);
                positions[node.nodeId] = saved && finiteNumber(saved.x) && finiteNumber(saved.y)
                    ? {
                        x: saved.x,
                        y: saved.y,
                        width: junction ? 0 : width,
                        height: junction ? 0 : height,
                        isJunction: junction,
                        portOrientation: junction ? 'horizontal' : nodePortOrientation(node),
                        portOrder: junction ? 'input_first' : nodePortOrder(node),
                    }
                    : {
                        x: padding + rank * (width + columnGap) + (junction ? width / 2 : 0),
                        y: padding + rowIndex * (height + rowGap) + (junction ? height / 2 : 0),
                        width: junction ? 0 : width,
                        height: junction ? 0 : height,
                        isJunction: junction,
                        portOrientation: junction ? 'horizontal' : nodePortOrientation(node),
                        portOrder: junction ? 'input_first' : nodePortOrder(node),
                    };
            });
        });
        return positions;
    }

    function graphBounds(positions, groups) {
        const values = Object.keys(positions || {}).map(function (key) { return positions[key]; });
        (Array.isArray(groups) ? groups : []).forEach(function (group) {
            if (!group || !_validGroupPosition(group.position) || !_finiteGroupSize(group.size)) return;
            values.push({
                x: group.position.x,
                y: group.position.y - GROUP_HEADER_OVERHANG,
                width: group.size.width,
                height: group.size.height + GROUP_HEADER_OVERHANG,
            });
        });
        if (!values.length) return { x: 0, y: 0, width: 1, height: 1 };
        const minX = Math.min.apply(null, values.map(function (position) { return position.x; }));
        const minY = Math.min.apply(null, values.map(function (position) { return position.y; }));
        const maxX = Math.max.apply(null, values.map(function (position) {
            return position.x + position.width;
        }));
        const maxY = Math.max.apply(null, values.map(function (position) {
            return position.y + position.height;
        }));
        return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
    }

    function portAnchor(position, side) {
        if (position && position.isJunction) {
            return { x: position.x, y: position.y };
        }
        const leading = position && position.portOrder === 'output_first'
            ? side === 'out'
            : side === 'in';
        if (position && position.portOrientation === 'vertical') {
            return {
                x: position.x + position.width / 2,
                y: leading ? position.y : position.y + position.height,
            };
        }
        return {
            x: leading ? position.x : position.x + position.width,
            y: position.y + position.height / 2,
        };
    }

    function portDirection(orientation, order, side) {
        const leading = order === 'output_first' ? side === 'out' : side === 'in';
        if (orientation === 'vertical') return { x: 0, y: leading ? -1 : 1 };
        return { x: leading ? -1 : 1, y: 0 };
    }

    function bezierPath(start, end, startOrientation, endOrientation, startOrder, endOrder) {
        const fromOrientation = startOrientation === 'vertical' ? 'vertical' : 'horizontal';
        const toOrientation = endOrientation === 'vertical' ? 'vertical' : 'horizontal';
        const fromDirection = portDirection(fromOrientation, startOrder, 'out');
        const toDirection = portDirection(toOrientation, endOrder, 'in');
        const defaultHorizontal = fromDirection.x === 1 && fromDirection.y === 0
            && toDirection.x === -1 && toDirection.y === 0;
        if (!defaultHorizontal) {
            const control = Math.max(88, Math.hypot(end.x - start.x, end.y - start.y) * 0.38);
            const first = {
                x: start.x + fromDirection.x * control,
                y: start.y + fromDirection.y * control,
            };
            const second = {
                x: end.x + toDirection.x * control,
                y: end.y + toDirection.y * control,
            };
            return [
                'M', start.x, start.y,
                'C', first.x, first.y, second.x, second.y, end.x, end.y,
            ].join(' ');
        }
        const horizontal = end.x - start.x;
        const control = Math.max(88, Math.abs(horizontal) * 0.48);
        const firstX = start.x + control;
        const secondX = end.x - control;
        return [
            'M', start.x, start.y,
            'C', firstX, start.y, secondX, end.y, end.x, end.y,
        ].join(' ');
    }

    function clamp(value, minimum, maximum) {
        return Math.max(minimum, Math.min(maximum, value));
    }

    function svgElement(name, attributes) {
        const element = document.createElementNS('http://www.w3.org/2000/svg', name);
        Object.keys(attributes || {}).forEach(function (key) {
            element.setAttribute(key, String(attributes[key]));
        });
        return element;
    }

    function fallbackCard(node, onSelect) {
        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'pm-fallback-card';
        const name = document.createElement('strong');
        name.textContent = node.name || node.nodeId;
        const meta = document.createElement('span');
        meta.textContent = (node.partIds || []).length + ' part references';
        card.appendChild(name);
        card.appendChild(meta);
        card.addEventListener('click', function () { onSelect(node.nodeId); });
        return card;
    }

    function normalizeProductStructure(structure) {
        const value = structure && typeof structure === 'object' ? structure : {};
        return {
            schemaVersion: value.schemaVersion || 1,
            productId: value.productId || '',
            productName: value.productName || 'Product Structure',
            occurrences: Array.isArray(value.occurrences) ? cloneMap(value.occurrences) : [],
        };
    }

    function normalizeMapCatalog(value, currentMap) {
        const source = value && typeof value === 'object' ? value : {};
        const maps = Array.isArray(source.maps) ? source.maps.filter(function (item) {
            return item && typeof item.mapId === 'string' && item.mapId;
        }).map(cloneMap) : [];
        const currentId = String(currentMap && currentMap.mapId || 'default');
        if (!maps.some(function (item) { return item.mapId === currentId; })) {
            maps.push({
                mapId: currentId,
                displayName: String(currentMap && currentMap.displayName || 'Process Flow'),
                status: String(currentMap && currentMap.status || 'draft'),
                isDefault: currentId === String(source.defaultMapId || 'default'),
            });
        }
        maps.sort(function (left, right) {
            const byName = String(left.displayName || left.mapId).localeCompare(
                String(right.displayName || right.mapId), undefined, { sensitivity: 'base' }
            );
            return byName || String(left.mapId).localeCompare(String(right.mapId));
        });
        const templates = Array.isArray(source.templates) ? source.templates.filter(function (item) {
            return item && typeof item.templateId === 'string' && item.templateId;
        }).map(cloneMap) : [];
        templates.sort(function (left, right) {
            return String(left.displayName || left.templateId).localeCompare(
                String(right.displayName || right.templateId), undefined, { sensitivity: 'base' }
            );
        });
        return {
            defaultMapId: String(source.defaultMapId || 'default'),
            maps: maps,
            templates: templates,
        };
    }

    function occurrenceIndex(structure) {
        const byId = new Map();
        const children = new Map();
        (structure.occurrences || []).forEach(function (occurrence) {
            if (!occurrence || !occurrence.occurrenceId) return;
            byId.set(occurrence.occurrenceId, occurrence);
            const parentId = occurrence.parentOccurrenceId || null;
            if (!children.has(parentId)) children.set(parentId, []);
            children.get(parentId).push(occurrence);
        });
        children.forEach(function (items) { items.sort(function (left, right) {
            const leftOrder = finiteNumber(left.suggestedBuildOrder)
                ? left.suggestedBuildOrder : Number.MAX_SAFE_INTEGER;
            const rightOrder = finiteNumber(right.suggestedBuildOrder)
                ? right.suggestedBuildOrder : Number.MAX_SAFE_INTEGER;
            if (leftOrder !== rightOrder) return leftOrder - rightOrder;
            return String(left.name || left.occurrenceId).localeCompare(
                String(right.name || right.occurrenceId)
            );
        }); });
        byId.forEach(function (occurrence, occurrenceId) {
            occurrence.childOccurrenceCount = (children.get(occurrenceId) || []).length;
        });
        return { byId: byId, children: children };
    }

    function resolveCanvasNode(node, occurrences) {
        if (!node || node.nodeKind !== 'product_occurrence') {
            return node && node.nodeKind === 'process_step'
                ? Object.assign({}, node, {
                    type: node.processType || 'operation',
                    name: node.name || node.nodeId,
                    partIds: [],
                })
                : node;
        }
        const source = occurrences.get(node.sourceOccurrenceId);
        if (!source) {
            return Object.assign({}, node, {
                name: node.labelOverride || node.nameSnapshot || node.sourceOccurrenceId || node.nodeId,
                type: 'part',
                missingSource: true,
                partIds: [],
            });
        }
        return Object.assign({}, source, node, {
            nodeId: node.nodeId,
            name: node.labelOverride || source.name || node.nameSnapshot || node.nodeId,
            type: source.kind || 'part',
            level: source.level,
            partIds: Array.isArray(source.partIds) ? source.partIds : [],
            sourceOccurrenceId: source.occurrenceId,
            productKind: source.kind || 'part',
        });
    }

    function productIcon(kind) {
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', 'pm-tree-icon pm-tree-icon-' + kind);
        svg.setAttribute('viewBox', '1.5 1.5 21 21');
        svg.setAttribute('aria-hidden', 'true');
        const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
        const symbol = kind === 'assembly'
            ? '#ip-cad-icon-assembly'
            : (kind === 'subassembly' ? '#ip-cad-icon-feature-group' : '#ip-cad-icon-boss');
        use.setAttribute('href', symbol);
        svg.appendChild(use);
        return svg;
    }

    function ProcessMapEditor(host, options) {
        this.host = host;
        this.options = options || {};
        this.editable = !!this.options.editable;
        this.processMap = cloneMap(this.options.map || { nodes: [], edges: [] });
        this.mapCatalog = normalizeMapCatalog(this.options.mapCatalog, this.processMap);
        this.productStructure = normalizeProductStructure(this.options.productStructure);
        const catalog = occurrenceIndex(this.productStructure);
        this.occurrenceById = catalog.byId;
        this.occurrenceChildren = catalog.children;
        this.expandedOccurrenceIds = new Set();
        (this.occurrenceChildren.get(null) || []).forEach(function (rootOccurrence) {
            this.expandedOccurrenceIds.add(rootOccurrence.occurrenceId);
        }, this);
        this.treeFilter = '';
        this.savedMap = cloneMap(this.processMap);
        this.savedFingerprint = mapFingerprint(this.savedMap);
        this.revision = this.options.revision || null;
        this.findings = Array.isArray(this.options.findings) ? this.options.findings : [];
        this.focusNodeId = isPlacementMap(this.processMap) ? null : (this.options.focusNodeId || null);
        this.selectedNodeId = this.options.selectedNodeId || null;
        this.selectedEdgeId = null;
        this.selectedGroupId = null;
        this.transform = { x: 0, y: 0, scale: 1 };
        this.interaction = null;
        this.history = new SnapshotHistory(this.options.historyLimit || 50);
        this.dirty = false;
        this.saving = false;
        this.managementBusy = false;
        this.conflict = false;
        this.operationError = '';
        this.suggestions = [];
        this.suggestionsRevision = null;
        this.suggestionsLoading = false;
        this.suggestionsError = '';
        this.suggestionPanelOpen = false;
        this.suggestionRequestToken = 0;
        this.edgeCounter = 0;
        this.nodeCounter = 0;
        this.referenceCounter = 0;
        this.groupCounter = 0;
        this.groupMoveFrameOnly = false;
        this._suppressClick = false;
        this.instanceId = 'pm-arrow-' + (++instanceCounter);
        this.destroyed = false;
        this.cardToolbarEnabled = this.editable && this.options.cardToolbar === true;
        this.cardToolbarManager = null;
        this.cardToolbarElement = null;
        this.cardToolbarNodeId = null;
        this.cardToolbarEdgeId = null;
        this.cardToolbarGroupId = null;
        this.floatingDom = this.options.floatingDom
            || (typeof window !== 'undefined' ? window.FloatingUIDOM : null);
        this._build();
        this._initializeCardToolbar();
        this.renderGraph({ fit: true });
        this._scheduleSuggestionLoad();
    }

    ProcessMapEditor.prototype._build = function () {
        this.host.innerHTML = '';
        this.root = document.createElement('div');
        this.root.className = 'pm-editor';
        if (this.editable) this.root.classList.add('editable');
        this.root.setAttribute('data-process-flow-editor', 'true');

        this.toolbar = document.createElement('div');
        this.toolbar.className = 'pm-toolbar';
        this.toolbarLeft = document.createElement('div');
        this.toolbarLeft.className = 'pm-toolbar-copy';
        this.title = document.createElement('div');
        this.title.className = 'pm-toolbar-title';
        this.title.textContent = 'Process Flow';
        this.subtitle = document.createElement('div');
        this.subtitle.className = 'pm-toolbar-subtitle';
        this.toolbarLeft.appendChild(this.title);
        this.toolbarLeft.appendChild(this.subtitle);
        if (typeof this.options.onSwitchMap === 'function') {
            this.mapManager = document.createElement('div');
            this.mapManager.className = 'pm-map-manager';
            this.mapSelect = document.createElement('select');
            this.mapSelect.className = 'pm-map-select';
            this.mapSelect.setAttribute('aria-label', 'Process map');
            this.mapSelect.title = 'Switch process map';
            this.mapSelect.addEventListener('change', this.changeMapSelection.bind(this));
            this.mapActionSelect = document.createElement('select');
            this.mapActionSelect.className = 'pm-map-action-select';
            this.mapActionSelect.setAttribute('aria-label', 'Process map action');
            this.mapActionSelect.title = 'Create, duplicate, rename, archive, or use a template';
            this.mapActionSelect.addEventListener('change', this.changeMapAction.bind(this));
            this.mapManager.appendChild(this.mapSelect);
            this.mapManager.appendChild(this.mapActionSelect);
            this.toolbarLeft.appendChild(this.mapManager);
            this._renderMapCatalogControls();
        }

        this.toolbarActions = document.createElement('div');
        this.toolbarActions.className = 'pm-toolbar-actions';
        this.toolbarActions.appendChild(this._button('-', 'Zoom out', this.zoomBy.bind(this, 0.86)));
        this.toolbarActions.appendChild(this._button('+', 'Zoom in', this.zoomBy.bind(this, 1.16)));
        this.toolbarActions.appendChild(this._button('Fit', 'Fit flow to viewport', this.fit.bind(this)));
        if (typeof this.options.onAnalyze === 'function') {
            this.analyzeButton = this._button(
                'Analyze',
                'Ask Sage to analyze the saved process flow',
                this.analyze.bind(this)
            );
            this.toolbarActions.appendChild(this.analyzeButton);
        }
        if (typeof this.options.onLoadSuggestions === 'function') {
            this.suggestionButton = this._button(
                'Suggestions',
                'Review evidence-backed process-flow suggestions',
                this.toggleSuggestionPanel.bind(this)
            );
            this.toolbarActions.appendChild(this.suggestionButton);
        }
        if (this.editable) {
            this.undoButton = this._button('Undo', 'Undo process-map edit', this.undo.bind(this));
            this.redoButton = this._button('Redo', 'Redo process-map edit', this.redo.bind(this));
            this.deleteButton = this._button('Delete', 'Delete selected node or connection', this.deleteSelection.bind(this));
            this.previewButton = this._button(
                '3D',
                'Open selected card in the interactive 3D preview',
                this.openSelectedPreview.bind(this)
            );
            if (isPlacementMap(this.processMap)) {
                this.addStepButton = this._button(
                    '+ Step',
                    'Add an operation to the center of the process map',
                    this.addProcessStep.bind(this, 'operation')
                );
                this.addGroupButton = this._button(
                    '+ Group',
                    'Add a grouping frame to the center of the process map',
                    this.addCanvasGroup.bind(this)
                );
            }
            this.typeSelect = document.createElement('select');
            this.typeSelect.className = 'pm-type-select';
            this.typeSelect.setAttribute('aria-label', 'Selected node type');
            this.typeSelect.title = 'Change selected node type';
            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = 'Node type';
            this.typeSelect.appendChild(placeholder);
            (isPlacementMap(this.processMap) ? PROCESS_STEP_TYPES : NODE_TYPES).forEach(function (nodeType) {
                const option = document.createElement('option');
                option.value = nodeType;
                option.textContent = nodeType;
                this.typeSelect.appendChild(option);
            }, this);
            this.typeSelect.addEventListener('change', this.changeSelectedNodeType.bind(this));
            this.portOrientationSelect = document.createElement('select');
            this.portOrientationSelect.className = 'pm-port-orientation-select';
            this.portOrientationSelect.setAttribute('aria-label', 'Selected card connection layout');
            this.portOrientationSelect.title = 'Change where connections attach to the selected card';
            [
                { value: 'horizontal', label: 'Ports: left / right' },
                { value: 'vertical', label: 'Ports: top / bottom' },
            ].forEach(function (definition) {
                const option = document.createElement('option');
                option.value = definition.value;
                option.textContent = definition.label;
                this.portOrientationSelect.appendChild(option);
            }, this);
            this.portOrientationSelect.addEventListener(
                'change',
                this.changeSelectedPortOrientation.bind(this)
            );
            this.portOrderSelect = document.createElement('select');
            this.portOrderSelect.className = 'pm-port-order-select';
            this.portOrderSelect.setAttribute('aria-label', 'Selected card input position');
            this.portOrderSelect.title = 'Swap the input and output positions on the selected card';
            PORT_ORDERS.forEach(function (order) {
                const option = document.createElement('option');
                option.value = order;
                this.portOrderSelect.appendChild(option);
            }, this);
            this.portOrderSelect.addEventListener('change', this.changeSelectedPortOrder.bind(this));
            this.saveButton = this._button('Save', 'Save process map', this.save.bind(this));
            this.reloadButton = this._button('Reload', 'Reload the latest saved process map', this.reload.bind(this));
            this.reloadButton.hidden = true;
            this.toolbarActions.appendChild(this.undoButton);
            this.toolbarActions.appendChild(this.redoButton);
            if (this.addStepButton) this.toolbarActions.appendChild(this.addStepButton);
            if (this.addGroupButton) this.toolbarActions.appendChild(this.addGroupButton);
            this.toolbarActions.appendChild(this.deleteButton);
            this.toolbarActions.appendChild(this.previewButton);
            this.toolbarActions.appendChild(this.typeSelect);
            this.toolbarActions.appendChild(this.portOrientationSelect);
            this.toolbarActions.appendChild(this.portOrderSelect);
            this.toolbarActions.appendChild(this.saveButton);
            this.toolbarActions.appendChild(this.reloadButton);
        }
        this.backButton = this._button('<', 'Back one process scope', this.back.bind(this));
        this.backButton.classList.add('pm-back-button');
        if (isPlacementMap(this.processMap)) this.backButton.hidden = true;
        this.toolbarActions.appendChild(this.backButton);
        this.toolbarActions.appendChild(this._button(
            'Structure',
            'Return to product structure',
            this.exit.bind(this)
        ));
        this.toolbar.appendChild(this.toolbarLeft);
        this.toolbar.appendChild(this.toolbarActions);

        this.status = document.createElement('div');
        this.status.className = 'pm-editor-status';
        this.status.setAttribute('role', 'status');
        this.toolbarLeft.appendChild(this.status);

        this.workspace = document.createElement('div');
        this.workspace.className = 'pm-workspace';
        this.structureSidebar = document.createElement('aside');
        this.structureSidebar.className = 'pm-structure-sidebar';
        this.structureSidebar.setAttribute('aria-label', 'Product structure source catalog');
        const structureHeader = document.createElement('div');
        structureHeader.className = 'pm-structure-header';
        const structureTitle = document.createElement('div');
        structureTitle.className = 'pm-structure-title';
        structureTitle.textContent = this.productStructure.productName || 'Product Structure';
        const structureHint = document.createElement('div');
        structureHint.className = 'pm-structure-hint';
        structureHint.textContent = 'Drag an occurrence into the process map';
        this.treeSearch = document.createElement('input');
        this.treeSearch.type = 'search';
        this.treeSearch.className = 'pm-tree-search';
        this.treeSearch.placeholder = 'Search structure...';
        this.treeSearch.setAttribute('aria-label', 'Search product structure');
        this.treeSearch.addEventListener('input', function () {
            this.treeFilter = this.treeSearch.value.trim().toLowerCase();
            this.renderStructureTree();
        }.bind(this));
        structureHeader.appendChild(structureTitle);
        structureHeader.appendChild(structureHint);
        structureHeader.appendChild(this.treeSearch);
        this.structureTree = document.createElement('div');
        this.structureTree.className = 'pm-structure-tree';
        this.structureTree.setAttribute('role', 'tree');
        this.structureSidebar.appendChild(structureHeader);
        this.structureSidebar.appendChild(this.structureTree);

        this.viewport = document.createElement('div');
        this.viewport.className = 'pm-viewport';
        this.viewport.tabIndex = 0;
        this.viewport.setAttribute(
            'aria-label',
            this.editable ? 'Editable process flow canvas' : 'Read-only process flow canvas'
        );
        this.world = document.createElement('div');
        this.world.className = 'pm-world';
        this.groupLayer = document.createElement('div');
        this.groupLayer.className = 'pm-group-layer';
        this.edgeSvg = svgElement('svg', { class: 'pm-edge-layer' });
        if (!this.editable) this.edgeSvg.setAttribute('aria-hidden', 'true');
        this.nodeLayer = document.createElement('div');
        this.nodeLayer.className = 'pm-node-layer';
        this.world.appendChild(this.groupLayer);
        this.world.appendChild(this.edgeSvg);
        this.world.appendChild(this.nodeLayer);
        this.viewport.appendChild(this.world);
        this.emptyState = document.createElement('div');
        this.emptyState.className = 'pm-empty-state';
        this.emptyState.textContent = 'Drag an assembly, subassembly, or part from the structure tree to begin building the process map.';
        this.viewport.appendChild(this.emptyState);
        this.root.appendChild(this.toolbar);
        this.workspace.appendChild(this.structureSidebar);
        this.workspace.appendChild(this.viewport);
        if (this.suggestionButton) {
            this.suggestionPanel = document.createElement('aside');
            this.suggestionPanel.className = 'pm-suggestion-panel';
            this.suggestionPanel.setAttribute('aria-label', 'Process-flow suggestions');
            this.suggestionPanel.hidden = true;
            this.workspace.appendChild(this.suggestionPanel);
        }
        this.root.appendChild(this.workspace);
        this.host.appendChild(this.root);

        this._onPointerDown = this.pointerDown.bind(this);
        this._onPointerMove = this.pointerMove.bind(this);
        this._onPointerUp = this.pointerUp.bind(this);
        this._onWheel = this.wheel.bind(this);
        this._onKeyDown = this.keyDown.bind(this);
        this._onDragOver = this.dragOver.bind(this);
        this._onDragLeave = this.dragLeave.bind(this);
        this._onDrop = this.dropOccurrence.bind(this);
        this.viewport.addEventListener('pointerdown', this._onPointerDown);
        this.viewport.addEventListener('pointermove', this._onPointerMove);
        this.viewport.addEventListener('pointerup', this._onPointerUp);
        this.viewport.addEventListener('pointercancel', this._onPointerUp);
        this.viewport.addEventListener('wheel', this._onWheel, { passive: false });
        this.viewport.addEventListener('dragover', this._onDragOver);
        this.viewport.addEventListener('dragleave', this._onDragLeave);
        this.viewport.addEventListener('drop', this._onDrop);
        this.root.addEventListener('keydown', this._onKeyDown);
        this.renderStructureTree();
        this.updateEditControls();
    };

    ProcessMapEditor.prototype._appendSelectOption = function (select, value, label, disabled) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        option.disabled = !!disabled;
        select.appendChild(option);
        return option;
    };

    ProcessMapEditor.prototype._renderMapCatalogControls = function () {
        if (!this.mapSelect || !this.mapActionSelect) return;
        const currentId = String(this.processMap && this.processMap.mapId || 'default');
        this.mapSelect.textContent = '';
        this.mapCatalog.maps.forEach(function (item) {
            const status = item.status && item.status !== 'active' ? ' [' + item.status + ']' : '';
            const marker = item.isDefault ? ' (default)' : '';
            this._appendSelectOption(
                this.mapSelect,
                item.mapId,
                String(item.displayName || item.mapId) + marker + status,
                item.status === 'archived'
            );
        }, this);
        this.mapSelect.value = currentId;

        this.mapActionSelect.textContent = '';
        this._appendSelectOption(this.mapActionSelect, '', 'Map actions', false);
        if (typeof this.options.onCreateMap === 'function') {
            this._appendSelectOption(this.mapActionSelect, 'create', 'New blank map', false);
        }
        if (typeof this.options.onDuplicateMap === 'function') {
            this._appendSelectOption(this.mapActionSelect, 'duplicate', 'Duplicate current map', false);
        }
        if (typeof this.options.onRenameMap === 'function') {
            this._appendSelectOption(this.mapActionSelect, 'rename', 'Rename current map', false);
        }
        if (typeof this.options.onSaveAsTemplate === 'function') {
            this._appendSelectOption(this.mapActionSelect, 'save-template', 'Save as template', false);
        }
        if (typeof this.options.onArchiveMap === 'function') {
            this._appendSelectOption(
                this.mapActionSelect,
                'archive',
                'Archive current map',
                currentId === this.mapCatalog.defaultMapId
            );
        }
        if (typeof this.options.onCreateFromTemplate === 'function') {
            this.mapCatalog.templates.forEach(function (template) {
                this._appendSelectOption(
                    this.mapActionSelect,
                    'from-template:' + template.templateId,
                    'New from template: ' + String(template.displayName || template.templateId),
                    false
                );
            }, this);
        }
        this.mapActionSelect.value = '';
    };

    ProcessMapEditor.prototype.setMapCatalog = function (catalog) {
        this.mapCatalog = normalizeMapCatalog(catalog, this.processMap);
        this._renderMapCatalogControls();
    };

    ProcessMapEditor.prototype._promptValue = function (message, defaultValue) {
        const promptValue = typeof this.options.prompt === 'function'
            ? this.options.prompt(message, defaultValue)
            : (typeof window !== 'undefined' && typeof window.prompt === 'function'
                ? window.prompt(message, defaultValue)
                : null);
        if (promptValue == null) return null;
        const cleaned = String(promptValue).trim();
        return cleaned || null;
    };

    ProcessMapEditor.prototype._confirmManagementAction = function (message) {
        if (typeof this.options.confirmAction === 'function') {
            return this.options.confirmAction(message) !== false;
        }
        return typeof window !== 'undefined' && typeof window.confirm === 'function'
            ? window.confirm(message)
            : false;
    };

    ProcessMapEditor.prototype._activateMapResult = function (result, fit) {
        if (!result || result.ok === false || !result.map) return false;
        this._closeCardToolbar('map_changed', false);
        this.processMap = cloneMap(result.map);
        this.revision = result.revision || null;
        if (result.productStructure) this.setProductStructure(result.productStructure);
        this.findings = Array.isArray(result.findings) ? result.findings : [];
        this.savedMap = cloneMap(this.processMap);
        this.savedFingerprint = mapFingerprint(this.savedMap);
        this.history.clear();
        this._clearSuggestions();
        this.selectedNodeId = null;
        this.selectedEdgeId = null;
        this.selectedGroupId = null;
        this.conflict = false;
        this.operationError = '';
        this._setDirty(false);
        if (result.mapCatalog) this.setMapCatalog(result.mapCatalog);
        else this.setMapCatalog(this.mapCatalog);
        this._notifyMapChange();
        this.renderGraph({ fit: fit !== false });
        this._scheduleSuggestionLoad();
        return true;
    };

    ProcessMapEditor.prototype._runMapManagement = async function (callback, request, options) {
        const opts = options || {};
        if (this.managementBusy || typeof callback !== 'function') return false;
        if (opts.discardGuard && !this.confirmDiscard()) return false;
        if (opts.saveFirst && this.dirty) {
            const saved = await this.save();
            if (!saved) return false;
            request = Object.assign({}, request || {}, {
                mapId: String(this.processMap.mapId || 'default'),
                revision: this.revision,
            });
            if (Object.prototype.hasOwnProperty.call(request, 'map')) {
                request.map = cloneMap(this.processMap);
            }
        }
        this.managementBusy = true;
        this.updateEditControls();
        try {
            const result = await callback(request || {});
            if (!result || result.ok === false) {
                this.operationError = String(result && (result.error || result.detail) || 'Map operation failed.');
                return false;
            }
            if (result.mapCatalog) this.setMapCatalog(result.mapCatalog);
            if (result.map) return this._activateMapResult(result, opts.fit);
            this.operationError = '';
            this.updateEditControls();
            return true;
        } catch (error) {
            this.operationError = 'Map operation failed: '
                + (error && error.message ? error.message : String(error));
            return false;
        } finally {
            this.managementBusy = false;
            this._renderMapCatalogControls();
            this.updateEditControls();
        }
    };

    ProcessMapEditor.prototype.changeMapSelection = async function () {
        if (!this.mapSelect) return false;
        const currentId = String(this.processMap && this.processMap.mapId || 'default');
        const nextId = String(this.mapSelect.value || '');
        if (!nextId || nextId === currentId) return false;
        const changed = await this._runMapManagement(
            this.options.onSwitchMap,
            { mapId: nextId },
            { discardGuard: true, fit: true }
        );
        if (!changed) this.mapSelect.value = currentId;
        return changed;
    };

    ProcessMapEditor.prototype.changeMapAction = async function () {
        if (!this.mapActionSelect) return false;
        const action = String(this.mapActionSelect.value || '');
        this.mapActionSelect.value = '';
        if (!action) return false;
        const currentName = String(this.processMap.displayName || 'Process Map');
        if (action === 'create') {
            const displayName = this._promptValue('New process-map name', 'Untitled Process Map');
            return displayName && this._runMapManagement(
                this.options.onCreateMap,
                { displayName: displayName },
                { discardGuard: true, fit: true }
            );
        }
        if (action === 'duplicate') {
            const duplicateName = this._promptValue('Duplicate map name', currentName + ' Copy');
            return duplicateName && this._runMapManagement(
                this.options.onDuplicateMap,
                { sourceMapId: String(this.processMap.mapId || 'default'), displayName: duplicateName },
                { discardGuard: true, fit: true }
            );
        }
        if (action === 'rename') {
            const renamed = this._promptValue('Process-map name', currentName);
            return renamed && this._runMapManagement(
                this.options.onRenameMap,
                {
                    mapId: String(this.processMap.mapId || 'default'),
                    displayName: renamed,
                    map: cloneMap(this.processMap),
                    revision: this.revision,
                },
                { saveFirst: true, fit: false }
            );
        }
        if (action === 'save-template') {
            const templateName = this._promptValue('Template name', currentName + ' Template');
            return templateName && this._runMapManagement(
                this.options.onSaveAsTemplate,
                {
                    mapId: String(this.processMap.mapId || 'default'),
                    revision: this.revision,
                    displayName: templateName,
                },
                { saveFirst: true, fit: false }
            );
        }
        if (action === 'archive') {
            if (String(this.processMap.mapId || 'default') === this.mapCatalog.defaultMapId) return false;
            if (!this._confirmManagementAction('Archive this process map?')) return false;
            return this._runMapManagement(
                this.options.onArchiveMap,
                { mapId: String(this.processMap.mapId), revision: this.revision },
                { saveFirst: true, fit: true }
            );
        }
        if (action.indexOf('from-template:') === 0) {
            const templateId = action.slice('from-template:'.length);
            const template = this.mapCatalog.templates.find(function (item) {
                return item.templateId === templateId;
            });
            const templateMapName = this._promptValue(
                'New process-map name',
                String(template && template.displayName || 'Template') + ' Copy'
            );
            return templateMapName && this._runMapManagement(
                this.options.onCreateFromTemplate,
                { templateId: templateId, displayName: templateMapName },
                { discardGuard: true, fit: true }
            );
        }
        return false;
    };

    ProcessMapEditor.prototype._button = function (label, title, handler) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'pm-toolbar-button';
        button.textContent = label;
        button.title = title;
        button.setAttribute('aria-label', title);
        button.addEventListener('click', handler);
        return button;
    };

    ProcessMapEditor.prototype._initializeCardToolbar = function () {
        if (!this.cardToolbarEnabled || typeof document === 'undefined') return;
        const runtime = this.options.floatingSurfaceRuntime
            || (typeof window !== 'undefined' ? window.InspectorProFloating : null);
        if (!runtime || typeof runtime.createSurfaceManager !== 'function' || !this.floatingDom) {
            if (!floatingToolbarWarningShown && typeof console !== 'undefined') {
                floatingToolbarWarningShown = true;
                console.warn('Process-map card toolbar is unavailable; top toolbar controls remain active.');
            }
            return;
        }
        this.cardToolbarManager = runtime.createSurfaceManager({
            document: document,
            positioning: this.floatingDom,
        });
        if (!this.cardToolbarManager.available) this.cardToolbarManager = null;
    };

    ProcessMapEditor.prototype.selectedNodeCommandStates = function () {
        return selectedNodeCommandStates(
            this.processMap,
            this.selectedNodeId,
            this.selectedEdgeId,
            {
                saving: this.saving,
                conflict: this.conflict,
                hasPreview: typeof this.options.onOpenPreview === 'function',
            }
        );
    };

    ProcessMapEditor.prototype._closeCardToolbar = function (reason, restoreFocus) {
        if (!this.cardToolbarManager) return false;
        const closed = this.cardToolbarManager.close(reason || 'programmatic', {
            restoreFocus: restoreFocus !== false,
        });
        if (!closed) {
            this.cardToolbarElement = null;
            this.cardToolbarNodeId = null;
            this.cardToolbarEdgeId = null;
            this.cardToolbarGroupId = null;
        }
        return closed;
    };

    ProcessMapEditor.prototype._cardToolbarPlacement = function (node) {
        return nodePortOrientation(node) === 'vertical' ? 'right' : 'top';
    };

    ProcessMapEditor.prototype._cardToolbarMiddleware = function (node) {
        if (!this.floatingDom) return [];
        const vertical = nodePortOrientation(node) === 'vertical';
        return [
            this.floatingDom.offset(10),
            this.floatingDom.flip({
                boundary: this.viewport,
                fallbackPlacements: [vertical ? 'left' : 'bottom'],
            }),
            this.floatingDom.shift({ boundary: this.viewport, padding: 12 }),
        ];
    };

    ProcessMapEditor.prototype._cardToolbarButton = function (label, title, handler, className) {
        const button = this._button(label, title, handler);
        button.classList.add('pm-card-toolbar-button');
        if (className) button.classList.add(className);
        return button;
    };

    ProcessMapEditor.prototype._refreshCardToolbar = function () {
        const toolbar = this.cardToolbarElement;
        if (!toolbar) return;
        const states = this.selectedNodeCommandStates();
        const addSelect = toolbar.querySelector('[data-card-command="add-step"]');
        const labelButton = toolbar.querySelector('[data-card-command="edit-label"]');
        const noteButton = toolbar.querySelector('[data-card-command="edit-note"]');
        const referencesButton = toolbar.querySelector('[data-context-command="references"]');
        const previewButton = toolbar.querySelector('[data-card-command="preview"]');
        const deleteButton = toolbar.querySelector('[data-card-command="delete"]');
        if (addSelect) addSelect.disabled = !states.canAddConnectedStep;
        if (labelButton) labelButton.disabled = !states.canEditLabel;
        if (noteButton) {
            noteButton.disabled = !states.canEditNote;
            noteButton.classList.toggle('has-note', !!(states.node && states.node.note));
            noteButton.setAttribute('aria-pressed', !!(states.node && states.node.note) ? 'true' : 'false');
        }
        if (previewButton) previewButton.disabled = !states.canPreview;
        if (referencesButton) referencesButton.disabled = !!states.locked;
        if (deleteButton) deleteButton.disabled = !states.canDelete;
    };

    ProcessMapEditor.prototype._buildCardToolbar = function (node) {
        const states = this.selectedNodeCommandStates();
        const resolved = resolveCanvasNode(node, this.occurrenceById) || node;
        const toolbar = document.createElement('div');
        toolbar.className = 'ip-floating-surface pm-card-toolbar';
        toolbar.setAttribute('role', 'toolbar');
        toolbar.setAttribute('aria-orientation', 'horizontal');
        toolbar.setAttribute('aria-label', 'Card actions for ' + (resolved.name || node.nodeId));
        toolbar.setAttribute('data-node-id', node.nodeId);

        if (states.canAddConnectedStep) {
            const addSelect = document.createElement('select');
            addSelect.className = 'pm-card-toolbar-select pm-card-toolbar-add';
            addSelect.setAttribute('data-card-command', 'add-step');
            addSelect.setAttribute('aria-label', 'Add connected process step');
            addSelect.title = 'Add a connected process step';
            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = '+';
            addSelect.appendChild(placeholder);
            PROCESS_STEP_TYPES.forEach(function (nodeType) {
                const option = document.createElement('option');
                option.value = nodeType;
                option.textContent = '+ ' + nodeType.charAt(0).toUpperCase() + nodeType.slice(1);
                addSelect.appendChild(option);
            });
            addSelect.addEventListener('change', function () {
                const processType = addSelect.value;
                addSelect.value = '';
                if (processType) this.addConnectedStep(processType);
            }.bind(this));
            toolbar.appendChild(addSelect);
        }

        const labelButton = this._cardToolbarButton(
            'Aa',
            'Edit card label',
            this._openCardTextEditor.bind(this, 'label'),
            'pm-card-toolbar-label'
        );
        labelButton.setAttribute('data-card-command', 'edit-label');
        toolbar.appendChild(labelButton);

        const noteButton = this._cardToolbarButton(
            'N',
            'Add or edit card note',
            this._openCardTextEditor.bind(this, 'note'),
            'pm-card-toolbar-note'
        );
        noteButton.setAttribute('data-card-command', 'edit-note');
        toolbar.appendChild(noteButton);

        const referencesButton = this._cardToolbarButton(
            'Refs',
            'Add machines, tools, requirements, or standards',
            this._openReferenceEditor.bind(this),
            'pm-card-toolbar-references'
        );
        referencesButton.setAttribute('data-context-command', 'references');
        toolbar.appendChild(referencesButton);

        if (states.canPreview) {
            const previewButton = this._cardToolbarButton(
                '3D',
                'Open interactive 3D preview',
                this.openSelectedPreview.bind(this),
                'pm-card-toolbar-preview'
            );
            previewButton.setAttribute('data-card-command', 'preview');
            toolbar.appendChild(previewButton);
        }

        const deleteButton = this._cardToolbarButton(
            '\u00d7',
            'Delete card',
            this.deleteSelection.bind(this),
            'pm-card-toolbar-delete'
        );
        deleteButton.setAttribute('data-card-command', 'delete');
        toolbar.appendChild(deleteButton);

        const editor = document.createElement('div');
        editor.className = 'pm-card-toolbar-editor';
        editor.setAttribute('role', 'group');
        editor.hidden = true;
        toolbar.appendChild(editor);

        toolbar.addEventListener('keydown', function (event) {
            if (event.target && ['INPUT', 'TEXTAREA', 'SELECT'].indexOf(event.target.tagName) >= 0) return;
            if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
            const controls = Array.prototype.filter.call(
                toolbar.querySelectorAll('button:not(:disabled), select:not(:disabled)'),
                function (control) { return !control.hidden; }
            );
            const index = controls.indexOf(event.target);
            if (index < 0 || !controls.length) return;
            event.preventDefault();
            const direction = event.key === 'ArrowRight' ? 1 : -1;
            controls[(index + direction + controls.length) % controls.length].focus();
        });
        this.cardToolbarElement = toolbar;
        this._refreshCardToolbar();
        return toolbar;
    };

    ProcessMapEditor.prototype._edgePathElement = function (edgeId, hitPath) {
        const selector = hitPath ? '.pm-edge-hit[data-edge-id]' : '.pm-edge[data-edge-id]';
        return Array.prototype.find.call(this.edgeSvg.querySelectorAll(selector), function (path) {
            return path.getAttribute('data-edge-id') === edgeId;
        }) || null;
    };

    ProcessMapEditor.prototype._edgeToolbarReference = function (edgeId) {
        const editor = this;
        return {
            contextElement: this.viewport,
            getBoundingClientRect: function () {
                const path = editor._edgePathElement(edgeId, false);
                if (!path || typeof path.getTotalLength !== 'function') {
                    return { x: 0, y: 0, left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 };
                }
                const point = path.getPointAtLength(path.getTotalLength() / 2);
                const matrix = path.getScreenCTM();
                if (!matrix) {
                    return { x: 0, y: 0, left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 };
                }
                const x = matrix.a * point.x + matrix.c * point.y + matrix.e;
                const y = matrix.b * point.x + matrix.d * point.y + matrix.f;
                return { x: x, y: y, left: x, top: y, right: x, bottom: y, width: 0, height: 0 };
            },
        };
    };

    ProcessMapEditor.prototype._buildEdgeToolbar = function (edge) {
        const toolbar = document.createElement('div');
        toolbar.className = 'ip-floating-surface pm-card-toolbar pm-edge-toolbar';
        toolbar.setAttribute('role', 'toolbar');
        toolbar.setAttribute('aria-orientation', 'horizontal');
        toolbar.setAttribute('aria-label', 'Connection actions');
        toolbar.setAttribute('data-edge-id', edge.edgeId);

        const labelButton = this._cardToolbarButton(
            'Aa',
            'Edit connection label',
            this._openCardTextEditor.bind(this, 'edge-label'),
            'pm-edge-toolbar-label'
        );
        labelButton.setAttribute('data-card-command', 'edge-label');
        toolbar.appendChild(labelButton);

        const referencesButton = this._cardToolbarButton(
            'Refs',
            'Add machines, tools, requirements, or standards',
            this._openReferenceEditor.bind(this),
            'pm-card-toolbar-references'
        );
        referencesButton.setAttribute('data-context-command', 'references');
        toolbar.appendChild(referencesButton);

        const deleteButton = this._cardToolbarButton(
            '\u00d7',
            'Delete connection',
            this.deleteSelection.bind(this),
            'pm-card-toolbar-delete'
        );
        deleteButton.setAttribute('data-card-command', 'delete');
        toolbar.appendChild(deleteButton);

        const editor = document.createElement('div');
        editor.className = 'pm-card-toolbar-editor';
        editor.setAttribute('role', 'group');
        editor.hidden = true;
        toolbar.appendChild(editor);

        toolbar.addEventListener('keydown', function (event) {
            if (event.target && ['INPUT', 'TEXTAREA', 'SELECT'].indexOf(event.target.tagName) >= 0) return;
            if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
            const controls = Array.prototype.filter.call(
                toolbar.querySelectorAll('button:not(:disabled), select:not(:disabled)'),
                function (control) { return !control.hidden; }
            );
            const index = controls.indexOf(event.target);
            if (index < 0 || !controls.length) return;
            event.preventDefault();
            const direction = event.key === 'ArrowRight' ? 1 : -1;
            controls[(index + direction + controls.length) % controls.length].focus();
        });
        this.cardToolbarElement = toolbar;
        return toolbar;
    };

    ProcessMapEditor.prototype._buildGroupToolbar = function (group) {
        const toolbar = document.createElement('div');
        toolbar.className = 'ip-floating-surface pm-card-toolbar pm-group-toolbar';
        toolbar.setAttribute('role', 'toolbar');
        toolbar.setAttribute('aria-orientation', 'horizontal');
        toolbar.setAttribute('aria-label', 'Group actions for ' + group.label);
        toolbar.setAttribute('data-group-id', group.groupId);

        const renameButton = this._cardToolbarButton(
            'Aa',
            'Rename group',
            function () {
                const editor = toolbar.querySelector('.pm-card-toolbar-editor');
                if (!editor) return;
                editor.innerHTML = '';
                editor.hidden = false;
                toolbar.classList.add('editing');
                const input = document.createElement('input');
                input.type = 'text';
                input.className = 'pm-card-toolbar-field';
                input.maxLength = MAX_GROUP_LABEL_LENGTH;
                input.value = group.label || '';
                input.setAttribute('aria-label', 'Group label');
                const actions = document.createElement('div');
                actions.className = 'pm-card-toolbar-editor-actions';
                const cancel = this._button('Cancel', 'Cancel group rename', function () {
                    editor.hidden = true;
                    editor.innerHTML = '';
                    toolbar.classList.remove('editing');
                    renameButton.focus();
                    if (this.cardToolbarManager) this.cardToolbarManager.reposition();
                }.bind(this));
                const save = this._button('Save', 'Save group label', function () {
                    if (this.applyGroupLabel(input.value)) {
                        editor.hidden = true;
                        editor.innerHTML = '';
                        toolbar.classList.remove('editing');
                    }
                }.bind(this));
                cancel.classList.add('pm-card-editor-cancel');
                save.classList.add('pm-card-editor-save');
                actions.appendChild(cancel);
                actions.appendChild(save);
                editor.appendChild(input);
                editor.appendChild(actions);
                if (this.cardToolbarManager) this.cardToolbarManager.reposition();
                input.focus();
                input.select();
            }.bind(this),
            'pm-group-toolbar-rename'
        );
        renameButton.setAttribute('data-group-command', 'rename');
        toolbar.appendChild(renameButton);

        const colorSelect = document.createElement('select');
        colorSelect.className = 'pm-card-toolbar-select pm-group-color-select';
        colorSelect.setAttribute('aria-label', 'Group color');
        colorSelect.title = 'Change group color';
        GROUP_COLOR_KEYS.forEach(function (colorKey) {
            const option = document.createElement('option');
            option.value = colorKey;
            option.textContent = colorKey.charAt(0).toUpperCase() + colorKey.slice(1);
            colorSelect.appendChild(option);
        });
        colorSelect.value = group.colorKey;
        colorSelect.addEventListener('change', function () {
            this.applyGroupColor(colorSelect.value);
        }.bind(this));
        toolbar.appendChild(colorSelect);

        const moveOnlyButton = this._cardToolbarButton(
            'Frame',
            'Move frame only without moving its members',
            function () {
                this.groupMoveFrameOnly = !this.groupMoveFrameOnly;
                moveOnlyButton.setAttribute('aria-pressed', this.groupMoveFrameOnly ? 'true' : 'false');
                moveOnlyButton.classList.toggle('active', this.groupMoveFrameOnly);
                moveOnlyButton.title = this.groupMoveFrameOnly
                    ? 'Frame-only movement is active'
                    : 'Move frame only without moving its members';
            }.bind(this),
            'pm-group-toolbar-move-only'
        );
        moveOnlyButton.setAttribute('aria-pressed', this.groupMoveFrameOnly ? 'true' : 'false');
        moveOnlyButton.classList.toggle('active', this.groupMoveFrameOnly);
        toolbar.appendChild(moveOnlyButton);

        const deleteButton = this._cardToolbarButton(
            '\u00d7',
            'Delete group frame only',
            this.deleteSelection.bind(this),
            'pm-card-toolbar-delete'
        );
        deleteButton.setAttribute('data-group-command', 'delete');
        toolbar.appendChild(deleteButton);

        const editor = document.createElement('div');
        editor.className = 'pm-card-toolbar-editor';
        editor.setAttribute('role', 'group');
        editor.hidden = true;
        toolbar.appendChild(editor);
        this.cardToolbarElement = toolbar;
        return toolbar;
    };

    ProcessMapEditor.prototype._openGroupToolbar = function (group) {
        if (!this.cardToolbarManager || !group || this.conflict) return false;
        const frame = this.groupLayer.querySelector('[data-group-id="' + group.groupId + '"]');
        const header = frame && frame.querySelector('.pm-group-header');
        if (!frame || !header) return false;
        if (this.cardToolbarManager.isOpen() && this.cardToolbarGroupId === group.groupId) {
            this._syncCardToolbar();
            return true;
        }
        this._closeCardToolbar('selection_changed', false);
        const toolbar = this._buildGroupToolbar(group);
        this.cardToolbarNodeId = null;
        this.cardToolbarEdgeId = null;
        this.cardToolbarGroupId = group.groupId;
        const opened = this.cardToolbarManager.open({
            key: 'group:' + group.groupId,
            reference: header,
            floating: toolbar,
            placement: 'top',
            strategy: 'fixed',
            middleware: this._cardToolbarMiddleware({ portOrientation: 'horizontal' }),
            restoreFocusElement: header,
            shouldCloseOnEscape: function (event) {
                const target = event && event.target;
                return !(target && typeof target.closest === 'function'
                    && target.closest('.pm-card-toolbar-editor'));
            },
            shouldCloseOnOutsidePointerDown: function (event) {
                const target = event && event.target;
                return !(target && typeof target.closest === 'function'
                    && target.closest('.pm-group-header, .pm-group-border, .pm-group-resize'));
            },
            onClose: function () {
                if (this.cardToolbarElement === toolbar) {
                    this.cardToolbarElement = null;
                    this.cardToolbarGroupId = null;
                }
            }.bind(this),
        });
        if (!opened) {
            toolbar.remove();
            this.cardToolbarElement = null;
            this.cardToolbarGroupId = null;
        }
        return opened;
    };

    ProcessMapEditor.prototype.applyGroupLabel = function (value) {
        if (!this.selectedGroupId || this.conflict || typeof value !== 'string') return false;
        return this.commitMutation(renameGroup(this.processMap, this.selectedGroupId, value));
    };

    ProcessMapEditor.prototype.applyGroupColor = function (colorKey) {
        if (!this.selectedGroupId || this.conflict) return false;
        return this.commitMutation(recolorGroup(this.processMap, this.selectedGroupId, colorKey));
    };

    ProcessMapEditor.prototype._openEdgeToolbar = function (edge) {
        if (!this.cardToolbarManager || !edge || this.conflict) return false;
        const hit = this._edgePathElement(edge.edgeId, true);
        if (!hit) return false;
        if (this.cardToolbarManager.isOpen() && this.cardToolbarEdgeId === edge.edgeId) {
            this._syncCardToolbar();
            return true;
        }
        this._closeCardToolbar('selection_changed', false);
        const toolbar = this._buildEdgeToolbar(edge);
        const reference = this._edgeToolbarReference(edge.edgeId);
        this.cardToolbarNodeId = null;
        this.cardToolbarEdgeId = edge.edgeId;
        this.cardToolbarGroupId = null;
        const opened = this.cardToolbarManager.open({
            key: 'edge:' + edge.edgeId,
            reference: reference,
            floating: toolbar,
            placement: 'top',
            strategy: 'fixed',
            middleware: this._cardToolbarMiddleware({ portOrientation: 'horizontal' }),
            restoreFocusElement: hit,
            shouldCloseOnEscape: function (event) {
                const target = event && event.target;
                return !(target && typeof target.closest === 'function'
                    && target.closest('.pm-card-toolbar-editor'));
            },
            shouldCloseOnOutsidePointerDown: function (event) {
                const target = event && event.target;
                return !(target && typeof target.closest === 'function'
                    && target.closest('.pm-node, .pm-junction, .pm-port, .pm-edge-hit'));
            },
            onClose: function () {
                if (this.cardToolbarElement === toolbar) {
                    this.cardToolbarElement = null;
                    this.cardToolbarEdgeId = null;
                    this.cardToolbarGroupId = null;
                }
            }.bind(this),
        });
        if (!opened) {
            toolbar.remove();
            this.cardToolbarElement = null;
            this.cardToolbarEdgeId = null;
        }
        return opened;
    };

    ProcessMapEditor.prototype._closeCardTextEditor = function (restoreFocus) {
        const toolbar = this.cardToolbarElement;
        if (!toolbar) return false;
        const editor = toolbar.querySelector('.pm-card-toolbar-editor');
        if (!editor || editor.hidden) return false;
        const mode = editor.getAttribute('data-editor-mode');
        editor.hidden = true;
        editor.removeAttribute('data-editor-mode');
        editor.innerHTML = '';
        toolbar.classList.remove('editing');
        toolbar.classList.remove('editing-references');
        if (restoreFocus !== false) {
            let command = 'edit-label';
            if (mode === 'note') command = 'edit-note';
            else if (mode === 'edge-label') command = 'edge-label';
            else if (mode === 'references') command = 'references';
            const trigger = toolbar.querySelector(
                '[data-card-command="' + command + '"], '
                + '[data-context-command="' + command + '"]'
            );
            if (trigger && typeof trigger.focus === 'function') trigger.focus();
        }
        if (this.cardToolbarManager) this.cardToolbarManager.reposition();
        return true;
    };

    ProcessMapEditor.prototype._openCardTextEditor = function (mode) {
        const edgeMode = mode === 'edge-label';
        const states = this.selectedNodeCommandStates();
        const edge = edgeMode ? mapEdges(this.processMap).find(function (item) {
            return item && item.edgeId === this.selectedEdgeId;
        }, this) : null;
        if ((edgeMode && (!edge || this.saving || this.conflict))
            || (mode === 'label' && !states.canEditLabel)
            || (mode === 'note' && !states.canEditNote)
            || !this.cardToolbarElement) return false;
        const editor = this.cardToolbarElement.querySelector('.pm-card-toolbar-editor');
        if (!editor) return false;
        const resolved = edgeMode
            ? null
            : (resolveCanvasNode(states.node, this.occurrenceById) || states.node);
        editor.innerHTML = '';
        editor.hidden = false;
        editor.setAttribute('data-editor-mode', mode);
        editor.setAttribute(
            'aria-label',
            edgeMode ? 'Edit connection label' : (mode === 'label' ? 'Edit card label' : 'Edit card note')
        );
        this.cardToolbarElement.classList.add('editing');

        const field = document.createElement(mode === 'note' ? 'textarea' : 'input');
        field.className = 'pm-card-toolbar-field';
        field.setAttribute('data-card-editor-field', mode);
        field.setAttribute(
            'aria-label',
            edgeMode ? 'Connection label' : (mode === 'label' ? 'Card label' : 'Card note')
        );
        field.maxLength = mode === 'note' ? MAX_NODE_NOTE_LENGTH : MAX_NODE_LABEL_LENGTH;
        if (mode === 'note') {
            field.rows = 3;
            field.value = states.node.note || '';
            field.placeholder = 'Add an engineering or process note...';
        } else {
            field.type = 'text';
            field.value = edgeMode
                ? logicalEdgeLabel(this.processMap, edge.edgeId)
                : (resolved.name || '');
            field.placeholder = edgeMode ? 'Connection label' : 'Card label';
        }
        editor.appendChild(field);

        const actions = document.createElement('div');
        actions.className = 'pm-card-toolbar-editor-actions';
        const cancel = this._button('Cancel', 'Cancel editing', function () {
            this._closeCardTextEditor(true);
        }.bind(this));
        cancel.classList.add('pm-card-editor-cancel');
        const saveTitle = edgeMode
            ? 'Save connection label'
            : (mode === 'label' ? 'Save card label' : 'Save card note');
        const save = this._button('Save', saveTitle, function () {
            const value = field.value;
            this._closeCardTextEditor(false);
            if (edgeMode) this.applyEdgeLabel(value);
            else if (mode === 'label') this.applyNodeLabel(value);
            else this.applyNodeNote(value);
        }.bind(this));
        save.classList.add('pm-card-editor-save');
        actions.appendChild(cancel);
        actions.appendChild(save);
        editor.appendChild(actions);

        field.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                this._closeCardTextEditor(true);
            } else if ((mode === 'label' || edgeMode) && event.key === 'Enter') {
                event.preventDefault();
                save.click();
            } else if (mode === 'note' && event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                save.click();
            }
        }.bind(this));
        if (this.cardToolbarManager) this.cardToolbarManager.reposition();
        field.focus();
        if ((mode === 'label' || edgeMode) && typeof field.select === 'function') field.select();
        return true;
    };

    ProcessMapEditor.prototype._selectedReferenceTarget = function () {
        if (this.selectedNodeId) {
            const node = mapNodes(this.processMap).find(function (item) {
                return item && item.nodeId === this.selectedNodeId;
            }, this);
            if (node && !isJunctionNode(node)) {
                return { targetType: 'node', targetId: node.nodeId, target: node };
            }
        }
        if (this.selectedEdgeId) {
            const edge = mapEdges(this.processMap).find(function (item) {
                return item && item.edgeId === this.selectedEdgeId;
            }, this);
            if (edge) return { targetType: 'edge', targetId: edge.edgeId, target: edge };
        }
        return null;
    };

    ProcessMapEditor.prototype.applyEdgeLabel = function (value) {
        if (!this.selectedEdgeId || this.saving || this.conflict || typeof value !== 'string') {
            return false;
        }
        return this.commitMutation(setEdgeLabel(this.processMap, this.selectedEdgeId, value));
    };

    ProcessMapEditor.prototype.applyProcessReference = function (reference) {
        const target = this._selectedReferenceTarget();
        if (!target || this.saving || this.conflict) return false;
        return this.commitMutation(attachProcessReference(this.processMap, {
            targetType: target.targetType,
            targetId: target.targetId,
            reference: reference,
        }));
    };

    ProcessMapEditor.prototype.removeProcessReference = function (referenceId) {
        const target = this._selectedReferenceTarget();
        if (!target || this.saving || this.conflict) return false;
        return this.commitMutation(detachProcessReference(this.processMap, {
            targetType: target.targetType,
            targetId: target.targetId,
            referenceId: referenceId,
        }));
    };

    ProcessMapEditor.prototype._openReferenceEditor = function () {
        const target = this._selectedReferenceTarget();
        const toolbar = this.cardToolbarElement;
        if (!target || !toolbar || this.saving || this.conflict) return false;
        const editor = toolbar.querySelector('.pm-card-toolbar-editor');
        if (!editor) return false;
        const attached = referenceItemsForTarget(
            this.processMap,
            target.targetType,
            target.targetId
        );
        const attachedIds = new Set(attached.map(function (reference) {
            return reference.referenceId;
        }));
        editor.innerHTML = '';
        editor.hidden = false;
        editor.setAttribute('data-editor-mode', 'references');
        editor.setAttribute('aria-label', 'Engineering references');
        toolbar.classList.add('editing', 'editing-references');

        const title = document.createElement('div');
        title.className = 'pm-reference-editor-title';
        title.textContent = target.targetType === 'edge'
            ? 'Connection requirements and resources'
            : 'Card requirements and resources';
        editor.appendChild(title);

        const list = document.createElement('div');
        list.className = 'pm-reference-list';
        if (!attached.length) {
            const empty = document.createElement('span');
            empty.className = 'pm-reference-empty';
            empty.textContent = 'No references attached.';
            list.appendChild(empty);
        }
        attached.forEach(function (reference) {
            const row = document.createElement('div');
            row.className = 'pm-reference-row';
            row.setAttribute('data-reference-id', reference.referenceId);
            const kind = document.createElement('span');
            kind.className = 'pm-reference-kind pm-reference-kind-' + reference.kind;
            kind.textContent = reference.kind;
            const text = document.createElement('span');
            text.className = 'pm-reference-row-text';
            const detail = [reference.identifier, reference.revision, reference.clause]
                .filter(Boolean).join(' / ');
            text.textContent = reference.name + (detail ? ' - ' + detail : '');
            text.title = reference.details || text.textContent;
            const remove = this._button('\u00d7', 'Detach ' + reference.name, function () {
                if (this.removeProcessReference(reference.referenceId)) {
                    this._openReferenceEditor();
                }
            }.bind(this));
            remove.classList.add('pm-reference-remove');
            row.appendChild(kind);
            row.appendChild(text);
            row.appendChild(remove);
            list.appendChild(row);
        }, this);
        editor.appendChild(list);

        const available = mapReferenceCatalog(this.processMap).filter(function (reference) {
            return reference && !attachedIds.has(reference.referenceId);
        });
        if (available.length) {
            const reuse = document.createElement('select');
            reuse.className = 'pm-card-toolbar-field pm-reference-existing';
            reuse.setAttribute('aria-label', 'Attach an existing reference');
            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = 'Attach existing reference...';
            reuse.appendChild(placeholder);
            available.forEach(function (reference) {
                const option = document.createElement('option');
                option.value = reference.referenceId;
                option.textContent = reference.kind + ': ' + reference.name;
                reuse.appendChild(option);
            });
            reuse.addEventListener('change', function () {
                const selected = available.find(function (reference) {
                    return reference.referenceId === reuse.value;
                });
                if (selected && this.applyProcessReference(selected)) {
                    this._openReferenceEditor();
                }
            }.bind(this));
            editor.appendChild(reuse);
        }

        const form = document.createElement('form');
        form.className = 'pm-reference-form';
        const kindField = document.createElement('select');
        kindField.className = 'pm-card-toolbar-field';
        kindField.setAttribute('data-reference-kind', '');
        kindField.setAttribute('aria-label', 'Reference type');
        REFERENCE_KINDS.forEach(function (value) {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = value.charAt(0).toUpperCase() + value.slice(1);
            kindField.appendChild(option);
        });
        form.appendChild(kindField);

        function field(name, placeholder, maximum, tagName) {
            const control = document.createElement(tagName || 'input');
            control.className = 'pm-card-toolbar-field';
            control.setAttribute('data-reference-field', name);
            control.setAttribute('aria-label', placeholder);
            control.placeholder = placeholder;
            control.maxLength = maximum;
            if (tagName === 'textarea') control.rows = 2;
            return control;
        }
        const nameField = field('name', 'Name', MAX_REFERENCE_NAME_LENGTH);
        const identifierField = field(
            'identifier',
            'Asset, requirement, or standard ID',
            MAX_REFERENCE_IDENTIFIER_LENGTH
        );
        const revisionField = field('revision', 'Revision', MAX_REFERENCE_REVISION_LENGTH);
        const clauseField = field('clause', 'Clause or section', MAX_REFERENCE_CLAUSE_LENGTH);
        const detailsField = field(
            'details',
            'Application notes or constraints',
            MAX_REFERENCE_DETAILS_LENGTH,
            'textarea'
        );
        form.appendChild(nameField);
        form.appendChild(identifierField);
        form.appendChild(revisionField);
        form.appendChild(clauseField);
        form.appendChild(detailsField);

        const error = document.createElement('div');
        error.className = 'pm-reference-error';
        error.setAttribute('role', 'alert');
        form.appendChild(error);
        const actions = document.createElement('div');
        actions.className = 'pm-card-toolbar-editor-actions pm-reference-actions';
        const done = this._button('Done', 'Close reference editor', function () {
            this._closeCardTextEditor(true);
        }.bind(this));
        done.classList.add('pm-card-editor-cancel');
        const add = this._button('Add', 'Attach reference', function () {});
        add.type = 'submit';
        add.classList.add('pm-card-editor-save');
        function updateAddState() {
            add.disabled = !nameField.value.trim()
                || (kindField.value === 'standard' && !identifierField.value.trim());
        }
        form.addEventListener('input', updateAddState);
        form.addEventListener('change', updateAddState);
        updateAddState();
        actions.appendChild(done);
        actions.appendChild(add);
        form.appendChild(actions);
        form.addEventListener('submit', function (event) {
            event.preventDefault();
            error.textContent = '';
            if (!nameField.value.trim()) {
                error.textContent = 'Enter a reference name.';
                nameField.focus();
                return;
            }
            if (kindField.value === 'standard' && !identifierField.value.trim()) {
                error.textContent = 'Standards require an identifier.';
                identifierField.focus();
                return;
            }
            let referenceId;
            do {
                referenceId = 'pm-ref-' + kindField.value + '-'
                    + Date.now().toString(36) + '-' + (++this.referenceCounter);
            } while (mapReferenceCatalog(this.processMap).some(function (reference) {
                return reference && reference.referenceId === referenceId;
            }));
            const changed = this.applyProcessReference({
                referenceId: referenceId,
                kind: kindField.value,
                name: nameField.value,
                identifier: identifierField.value,
                revision: revisionField.value,
                clause: clauseField.value,
                details: detailsField.value,
            });
            if (changed) this._openReferenceEditor();
            else error.textContent = 'That reference is already attached or could not be added.';
        }.bind(this));
        editor.appendChild(form);

        if (this.cardToolbarManager) this.cardToolbarManager.reposition();
        nameField.focus();
        return true;
    };

    ProcessMapEditor.prototype._openCardToolbar = function (node) {
        if (!this.cardToolbarManager || !node || isJunctionNode(node) || this.conflict) return false;
        const wrapper = this.nodeLayer.querySelector('[data-node-id="' + node.nodeId + '"]');
        if (!wrapper) return false;
        if (this.cardToolbarManager.isOpen() && this.cardToolbarNodeId === node.nodeId) {
            this._syncCardToolbar();
            return true;
        }
        this._closeCardToolbar('selection_changed', false);
        const toolbar = this._buildCardToolbar(node);
        const card = wrapper.querySelector('.pm-node-card') || wrapper;
        this.cardToolbarNodeId = node.nodeId;
        this.cardToolbarEdgeId = null;
        this.cardToolbarGroupId = null;
        const opened = this.cardToolbarManager.open({
            key: node.nodeId,
            reference: wrapper,
            floating: toolbar,
            placement: this._cardToolbarPlacement(node),
            strategy: 'fixed',
            middleware: this._cardToolbarMiddleware(node),
            restoreFocusElement: card,
            shouldCloseOnEscape: function (event) {
                const target = event && event.target;
                return !(target && typeof target.closest === 'function'
                    && target.closest('.pm-card-toolbar-editor'));
            },
            shouldCloseOnOutsidePointerDown: function (event) {
                const target = event && event.target;
                return !(target && typeof target.closest === 'function'
                    && target.closest('.pm-node, .pm-junction, .pm-port, .pm-edge-hit'));
            },
            onClose: function () {
                if (this.cardToolbarElement === toolbar) {
                    this.cardToolbarElement = null;
                    this.cardToolbarNodeId = null;
                    this.cardToolbarEdgeId = null;
                    this.cardToolbarGroupId = null;
                }
            }.bind(this),
        });
        if (!opened) {
            toolbar.remove();
            this.cardToolbarElement = null;
            this.cardToolbarNodeId = null;
            this.cardToolbarGroupId = null;
            this.cardToolbarEdgeId = null;
        }
        return opened;
    };

    ProcessMapEditor.prototype._syncCardToolbar = function () {
        if (!this.cardToolbarManager || !this.cardToolbarManager.isOpen()) return false;
        if (this.cardToolbarGroupId) {
            const group = mapGroups(this.processMap).find(function (item) {
                return item && item.groupId === this.cardToolbarGroupId;
            }, this);
            if (!group || this.selectedGroupId !== this.cardToolbarGroupId) {
                this._closeCardToolbar('selection_unavailable', false);
                return false;
            }
            const frame = this.groupLayer.querySelector('[data-group-id="' + group.groupId + '"]');
            const header = frame && frame.querySelector('.pm-group-header');
            if (!header) {
                this._closeCardToolbar('anchor_unavailable', false);
                return false;
            }
            return this.cardToolbarManager.reanchor(header, {
                placement: 'top',
                middleware: this._cardToolbarMiddleware({ portOrientation: 'horizontal' }),
                restoreFocusElement: header,
            });
        }
        if (this.cardToolbarEdgeId) {
            const edge = mapEdges(this.processMap).find(function (item) {
                return item && item.edgeId === this.cardToolbarEdgeId;
            }, this);
            if (!edge || this.selectedEdgeId !== this.cardToolbarEdgeId) {
                this._closeCardToolbar('selection_unavailable', false);
                return false;
            }
            const hit = this._edgePathElement(edge.edgeId, true);
            if (!hit) {
                this._closeCardToolbar('anchor_unavailable', false);
                return false;
            }
            return this.cardToolbarManager.reanchor(this._edgeToolbarReference(edge.edgeId), {
                placement: 'top',
                middleware: this._cardToolbarMiddleware({ portOrientation: 'horizontal' }),
                restoreFocusElement: hit,
            });
        }
        const states = this.selectedNodeCommandStates();
        if (!states.node || states.isJunction || states.node.nodeId !== this.cardToolbarNodeId) {
            this._closeCardToolbar('selection_unavailable', false);
            return false;
        }
        const wrapper = this.nodeLayer.querySelector('[data-node-id="' + states.node.nodeId + '"]');
        if (!wrapper) {
            this._closeCardToolbar('anchor_unavailable', false);
            return false;
        }
        const card = wrapper.querySelector('.pm-node-card') || wrapper;
        this._refreshCardToolbar();
        return this.cardToolbarManager.reanchor(wrapper, {
            placement: this._cardToolbarPlacement(states.node),
            middleware: this._cardToolbarMiddleware(states.node),
            restoreFocusElement: card,
        });
    };

    ProcessMapEditor.prototype._focusCardToolbar = function (nodeId) {
        if (!this.cardToolbarManager || !this.cardToolbarManager.isOpen()
            || this.cardToolbarNodeId !== nodeId || !this.cardToolbarElement) return false;
        const control = this.cardToolbarElement.querySelector(
            'button:not(:disabled), select:not(:disabled)'
        );
        if (!control || typeof control.focus !== 'function') return false;
        control.focus();
        return true;
    };

    ProcessMapEditor.prototype._placedOccurrenceIds = function () {
        return new Set(mapNodes(this.processMap).filter(function (node) {
            return node && node.nodeKind === 'product_occurrence' && node.sourceOccurrenceId;
        }).map(function (node) { return node.sourceOccurrenceId; }));
    };

    ProcessMapEditor.prototype._occurrenceMatchesFilter = function (occurrence, memo) {
        if (!this.treeFilter) return true;
        if (memo.has(occurrence.occurrenceId)) return memo.get(occurrence.occurrenceId);
        const ownText = [occurrence.name, occurrence.itemId, occurrence.occurrenceId]
            .filter(Boolean).join(' ').toLowerCase();
        const childMatch = (this.occurrenceChildren.get(occurrence.occurrenceId) || []).some(
            function (child) { return this._occurrenceMatchesFilter(child, memo); }.bind(this)
        );
        const matches = ownText.indexOf(this.treeFilter) >= 0 || childMatch;
        memo.set(occurrence.occurrenceId, matches);
        return matches;
    };

    ProcessMapEditor.prototype.renderStructureTree = function () {
        if (!this.structureTree) return;
        this.structureTree.innerHTML = '';
        const roots = this.occurrenceChildren.get(null) || [];
        if (!roots.length) {
            const empty = document.createElement('div');
            empty.className = 'pm-tree-empty';
            empty.textContent = 'No product structure is available.';
            this.structureTree.appendChild(empty);
            return;
        }
        const placed = this._placedOccurrenceIds();
        const filterMemo = new Map();
        roots.forEach(function (occurrence) {
            this._renderStructureOccurrence(occurrence, 0, placed, filterMemo);
        }, this);
    };

    ProcessMapEditor.prototype._renderStructureOccurrence = function (
        occurrence,
        depth,
        placed,
        filterMemo
    ) {
        if (!this._occurrenceMatchesFilter(occurrence, filterMemo)) return;
        const children = this.occurrenceChildren.get(occurrence.occurrenceId) || [];
        const expanded = !!this.treeFilter || this.expandedOccurrenceIds.has(occurrence.occurrenceId);
        const row = document.createElement('div');
        row.className = 'pm-tree-row' + (placed.has(occurrence.occurrenceId) ? ' placed' : '');
        row.setAttribute('role', 'treeitem');
        row.setAttribute('data-occurrence-id', occurrence.occurrenceId);
        row.setAttribute('data-product-kind', occurrence.kind || 'part');
        row.style.setProperty('--pm-tree-depth', String(depth));
        row.tabIndex = 0;
        if (children.length) row.setAttribute('aria-expanded', expanded ? 'true' : 'false');

        const caret = document.createElement('button');
        caret.type = 'button';
        caret.draggable = false;
        caret.className = 'pm-tree-caret';
        caret.textContent = children.length ? (expanded ? '-' : '+') : '';
        caret.disabled = !children.length;
        caret.setAttribute('aria-label', expanded ? 'Collapse item' : 'Expand item');
        caret.addEventListener('pointerdown', function (event) { event.stopPropagation(); });
        caret.addEventListener('dragstart', function (event) {
            event.preventDefault();
            event.stopPropagation();
        });
        caret.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            if (!children.length) return;
            if (expanded) this.expandedOccurrenceIds.delete(occurrence.occurrenceId);
            else this.expandedOccurrenceIds.add(occurrence.occurrenceId);
            this.renderStructureTree();
        }.bind(this));
        row.appendChild(caret);
        row.appendChild(productIcon(occurrence.kind || 'part'));

        const copy = document.createElement('span');
        copy.className = 'pm-tree-copy';
        const name = document.createElement('span');
        name.className = 'pm-tree-name';
        name.textContent = occurrence.name || occurrence.occurrenceId;
        copy.appendChild(name);
        if (occurrence.itemId) {
            const itemId = document.createElement('span');
            itemId.className = 'pm-tree-item-id';
            itemId.textContent = occurrence.itemId;
            copy.appendChild(itemId);
        }
        row.appendChild(copy);
        if (placed.has(occurrence.occurrenceId)) {
            const badge = document.createElement('span');
            badge.className = 'pm-tree-placed';
            badge.textContent = 'Placed';
            row.appendChild(badge);
        }

        row.addEventListener('click', function () {
            Array.prototype.forEach.call(
                this.structureTree.querySelectorAll('.pm-tree-row.selected'),
                function (item) { item.classList.remove('selected'); }
            );
            row.classList.add('selected');
            if (typeof this.options.onSourceSelect === 'function') {
                this.options.onSourceSelect(occurrence.occurrenceId, occurrence);
            }
        }.bind(this));
        if (this.editable) {
            row.draggable = true;
            row.title = 'Drag into the process map';
            row.addEventListener('dragstart', function (event) {
                if (!event.dataTransfer) return;
                event.dataTransfer.effectAllowed = 'copy';
                event.dataTransfer.setData(
                    'application/x-inspectorpro-occurrence',
                    occurrence.occurrenceId
                );
                event.dataTransfer.setData('text/plain', occurrence.occurrenceId);
                row.classList.add('drag-source');
            });
            row.addEventListener('dragend', function () { row.classList.remove('drag-source'); });
        }
        this.structureTree.appendChild(row);

        if (children.length && expanded) {
            children.forEach(function (child) {
                this._renderStructureOccurrence(child, depth + 1, placed, filterMemo);
            }, this);
        }
    };

    ProcessMapEditor.prototype.dragOver = function (event) {
        if (!this.editable || this.conflict) return;
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
        this.viewport.classList.add('drop-target');
    };

    ProcessMapEditor.prototype.dragLeave = function (event) {
        if (!this.viewport || this.viewport.contains(event.relatedTarget)) return;
        this.viewport.classList.remove('drop-target');
    };

    ProcessMapEditor.prototype.dropOccurrence = function (event) {
        event.preventDefault();
        this.viewport.classList.remove('drop-target');
        if (!this.editable || this.conflict || !event.dataTransfer) return false;
        const occurrenceId = event.dataTransfer.getData('application/x-inspectorpro-occurrence')
            || event.dataTransfer.getData('text/plain');
        return this.addOccurrenceAt(occurrenceId, event.clientX, event.clientY);
    };

    ProcessMapEditor.prototype.addOccurrenceAt = function (occurrenceId, clientX, clientY) {
        const occurrence = this.occurrenceById.get(occurrenceId);
        if (!occurrence || !isPlacementMap(this.processMap)) return false;
        const existing = mapNodes(this.processMap).find(function (node) {
            return node && node.nodeKind === 'product_occurrence'
                && node.sourceOccurrenceId === occurrenceId;
        });
        if (existing) {
            this.select(existing.nodeId);
            const wrapper = this.nodeLayer.querySelector('[data-node-id="' + existing.nodeId + '"]');
            if (wrapper) {
                wrapper.classList.remove('duplicate-pulse');
                void wrapper.offsetWidth;
                wrapper.classList.add('duplicate-pulse');
            }
            this.operationError = 'This product occurrence is already on the map.';
            this.updateEditControls();
            return false;
        }
        const world = this.clientToWorld(clientX, clientY);
        let nodeId;
        do {
            nodeId = 'pm-n-' + Date.now().toString(36) + '-' + (++this.nodeCounter);
        } while (mapNodes(this.processMap).some(function (node) { return node.nodeId === nodeId; }));
        const placement = {
            nodeId: nodeId,
            nodeKind: 'product_occurrence',
            sourceOccurrenceId: occurrenceId,
            nameSnapshot: occurrence.name || occurrenceId,
            itemIdSnapshot: occurrence.itemId || null,
            position: {
                x: world.x - NODE_WIDTH / 2,
                y: world.y - NODE_HEIGHT / 2,
            },
        };
        let nextMap = addCanvasNode(this.processMap, placement);
        nextMap = resolveNodeGroupMembership(nextMap, nodeId, {
            x: placement.position.x + NODE_WIDTH / 2,
            y: placement.position.y + NODE_HEIGHT / 2,
        });
        const changed = this.commitMutation(nextMap);
        if (changed) this.select(nodeId);
        return changed;
    };

    ProcessMapEditor.prototype.addProcessStep = function (processType) {
        if (!this.editable || this.conflict || !isPlacementMap(this.processMap)
            || PROCESS_STEP_TYPES.indexOf(processType) < 0) return false;
        const rect = this.viewport.getBoundingClientRect();
        const world = this.clientToWorld(rect.left + rect.width / 2, rect.top + rect.height / 2);
        let nodeId;
        do {
            nodeId = 'pm-step-' + Date.now().toString(36) + '-' + (++this.nodeCounter);
        } while (mapNodes(this.processMap).some(function (node) { return node.nodeId === nodeId; }));
        const label = processType.charAt(0).toUpperCase() + processType.slice(1);
        const placement = {
            nodeId: nodeId,
            nodeKind: 'process_step',
            processType: processType,
            name: 'New ' + label,
            description: '',
            position: {
                x: world.x - NODE_WIDTH / 2,
                y: world.y - NODE_HEIGHT / 2,
            },
        };
        let nextMap = addCanvasNode(this.processMap, placement);
        nextMap = resolveNodeGroupMembership(nextMap, nodeId, world);
        const changed = this.commitMutation(nextMap);
        if (changed) this.select(nodeId);
        return changed;
    };

    ProcessMapEditor.prototype.addCanvasGroup = function () {
        if (!this.editable || this.conflict || !isPlacementMap(this.processMap)) return false;
        const rect = this.viewport.getBoundingClientRect();
        const center = this.clientToWorld(rect.left + rect.width / 2, rect.top + rect.height / 2);
        let groupId;
        do {
            groupId = 'pm-group-' + Date.now().toString(36) + '-' + (++this.groupCounter);
        } while (mapGroups(this.processMap).some(function (group) {
            return group && group.groupId === groupId;
        }));
        const changed = this.commitMutation(addGroup(this.processMap, {
            groupId: groupId,
            label: 'New group',
            position: {
                x: center.x - DEFAULT_GROUP_WIDTH / 2,
                y: center.y - DEFAULT_GROUP_HEIGHT / 2,
            },
            size: { width: DEFAULT_GROUP_WIDTH, height: DEFAULT_GROUP_HEIGHT },
            colorKey: 'orange',
            memberNodeIds: [],
            collapsed: false,
        }));
        if (changed) this.selectGroup(groupId);
        return changed;
    };

    ProcessMapEditor.prototype._edgeContextText = function (edge) {
        if (!edge) return '';
        const parts = [];
        const label = logicalEdgeLabel(this.processMap, edge.edgeId);
        if (label) parts.push(label);
        referenceSummary(referenceItemsForTarget(
            this.processMap,
            'edge',
            edge.edgeId
        )).forEach(function (item) {
            parts.push(referenceKindShortLabel(item.kind) + ' ' + item.count);
        });
        return parts.join(' | ');
    };

    ProcessMapEditor.prototype._renderEdgeContextLabel = function (edge) {
        const textValue = this._edgeContextText(edge);
        if (!textValue) return null;
        const width = clamp(textValue.length * 6.2 + 18, 48, 280);
        const group = svgElement('g', {
            class: 'pm-edge-context-label',
            'data-edge-context-id': edge.edgeId,
            'data-edge-context-width': width,
            'aria-hidden': 'true',
        });
        group.appendChild(svgElement('rect', {
            x: -width / 2,
            y: -10,
            width: width,
            height: 20,
            rx: 4,
        }));
        const textElement = svgElement('text', {
            x: 0,
            y: 0,
            'text-anchor': 'middle',
            'dominant-baseline': 'middle',
        });
        textElement.textContent = textValue;
        group.appendChild(textElement);
        const title = svgElement('title');
        title.textContent = textValue;
        group.appendChild(title);
        this.edgeSvg.appendChild(group);
        this._positionEdgeContextLabel(group);
        return group;
    };

    ProcessMapEditor.prototype._positionEdgeContextLabel = function (group) {
        if (!group) return false;
        const edgeId = group.getAttribute('data-edge-context-id');
        const path = this._edgePathElement(edgeId, false);
        if (!path || typeof path.getTotalLength !== 'function') return false;
        let point;
        try { point = path.getPointAtLength(path.getTotalLength() / 2); } catch (_) { return false; }
        group.setAttribute('transform', 'translate(' + point.x + ' ' + (point.y - 22) + ')');
        return true;
    };

    ProcessMapEditor.prototype._positionEdgeContextLabels = function () {
        Array.prototype.forEach.call(
            this.edgeSvg.querySelectorAll('.pm-edge-context-label'),
            this._positionEdgeContextLabel.bind(this)
        );
    };

    ProcessMapEditor.prototype._positionGroupElement = function (element, group) {
        if (!element || !group || !_validGroupPosition(group.position) || !_finiteGroupSize(group.size)) {
            return;
        }
        element.style.left = group.position.x + 'px';
        element.style.top = group.position.y + 'px';
        element.style.width = group.size.width + 'px';
        element.style.height = group.size.height + 'px';
    };

    ProcessMapEditor.prototype.renderGroups = function () {
        if (!this.groupLayer) return;
        this.groupLayer.innerHTML = '';
        this.groupPositions = {};
        mapGroups(this.processMap).forEach(function (sourceGroup) {
            const group = cloneMap(sourceGroup);
            if (!group || !group.groupId || !_validGroupPosition(group.position)
                || !_finiteGroupSize(group.size)) return;
            this.groupPositions[group.groupId] = group;
            const frame = document.createElement('section');
            frame.className = 'pm-group-frame pm-group-color-' + group.colorKey;
            if (group.groupId === this.selectedGroupId) frame.classList.add('selected');
            frame.setAttribute('data-group-id', group.groupId);
            frame.setAttribute('aria-label', 'Process group ' + group.label);
            this._positionGroupElement(frame, group);

            const header = document.createElement('button');
            header.type = 'button';
            header.className = 'pm-group-header';
            header.style.top = -GROUP_HEADER_OVERHANG + 'px';
            header.setAttribute('data-group-id', group.groupId);
            header.setAttribute('aria-label', 'Select and move group ' + group.label);
            const label = document.createElement('span');
            label.className = 'pm-group-label';
            label.textContent = group.label;
            const count = document.createElement('span');
            count.className = 'pm-group-member-count';
            const memberCount = Array.isArray(group.memberNodeIds) ? group.memberNodeIds.length : 0;
            count.textContent = memberCount + (memberCount === 1 ? ' item' : ' items');
            header.appendChild(label);
            header.appendChild(count);
            if (this.editable) {
                header.addEventListener('pointerdown', this.startGroupDrag.bind(this, group.groupId));
            }
            header.addEventListener('click', function (event) {
                if (this._suppressGroupClick) {
                    event.preventDefault();
                    this._suppressGroupClick = false;
                    return;
                }
                event.stopPropagation();
                this.selectGroup(group.groupId);
            }.bind(this));
            frame.appendChild(header);

            ['top', 'right', 'bottom', 'left'].forEach(function (side) {
                const border = document.createElement('button');
                border.type = 'button';
                border.className = 'pm-group-border pm-group-border-' + side;
                border.setAttribute('aria-label', 'Select group ' + group.label);
                border.addEventListener('pointerdown', function (event) { event.stopPropagation(); });
                border.addEventListener('click', function (event) {
                    event.stopPropagation();
                    this.selectGroup(group.groupId);
                }.bind(this));
                frame.appendChild(border);
            }, this);

            if (this.editable) {
                ['nw', 'ne', 'se', 'sw'].forEach(function (corner) {
                    const handle = document.createElement('button');
                    handle.type = 'button';
                    handle.className = 'pm-group-resize pm-group-resize-' + corner;
                    handle.setAttribute('aria-label', 'Resize group from ' + corner + ' corner');
                    handle.addEventListener(
                        'pointerdown',
                        this.startGroupResize.bind(this, group.groupId, corner)
                    );
                    frame.appendChild(handle);
                }, this);
            }

            const groupFindings = this.findings.filter(function (finding) {
                return finding && finding.groupId === group.groupId;
            });
            if (groupFindings.length) {
                const badge = document.createElement('span');
                const hasError = groupFindings.some(function (finding) {
                    return finding.severity === 'error';
                });
                badge.className = 'pm-group-finding ' + (hasError ? 'error' : 'warning');
                badge.textContent = String(groupFindings.length);
                badge.title = groupFindings.map(function (finding) {
                    return finding.message;
                }).join('\n');
                frame.appendChild(badge);
            }
            this.groupLayer.appendChild(frame);
        }, this);
    };

    ProcessMapEditor.prototype._renderGhostEdges = function () {
        if (this.suggestionsRevision !== String(this.revision || '')) return;
        this.suggestions.forEach(function (suggestion) {
            const edge = suggestion && suggestion.edge;
            if (!edge || !edge.from || !edge.to) return;
            const fromPosition = this.positions[edge.from.nodeId];
            const toPosition = this.positions[edge.to.nodeId];
            if (!fromPosition || !toPosition) return;
            const pathValue = bezierPath(
                portAnchor(fromPosition, 'out'),
                portAnchor(toPosition, 'in'),
                fromPosition.portOrientation,
                toPosition.portOrientation,
                fromPosition.portOrder,
                toPosition.portOrder
            );
            const invalid = !!(
                suggestion.validation && suggestion.validation.wouldCreateCycle
            );
            const suggestionId = String(suggestion.suggestionId || '');
            const hit = svgElement('path', {
                d: pathValue,
                class: 'pm-ghost-edge-hit',
                'data-suggestion-id': suggestionId,
                tabindex: '0',
                role: 'button',
                'aria-label': invalid
                    ? 'Review blocked connection suggestion'
                    : 'Review connection suggestion',
            });
            hit.addEventListener('click', function (event) {
                event.preventDefault();
                event.stopPropagation();
                this.focusSuggestion(suggestionId);
            }.bind(this));
            hit.addEventListener('keydown', function (event) {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    this.focusSuggestion(suggestionId);
                }
            }.bind(this));
            this.edgeSvg.appendChild(hit);
            const path = svgElement('path', {
                d: pathValue,
                class: 'pm-edge pm-edge-ghost' + (invalid ? ' invalid' : ''),
                'marker-end': 'url(#' + this.instanceId + ')',
                'data-suggestion-id': suggestionId,
            });
            const title = svgElement('title');
            title.textContent = String(suggestion.explanation || 'Proposed connection');
            path.appendChild(title);
            this.edgeSvg.appendChild(path);
        }, this);
    };

    ProcessMapEditor.prototype.renderGraph = function (renderOptions) {
        const opts = renderOptions || {};
        const placements = scopedNodes(this.processMap, this.focusNodeId);
        const nodes = placements.map(function (node) {
            return resolveCanvasNode(node, this.occurrenceById);
        }, this);
        const edges = visibleEdges(this.processMap, placements);
        this.positions = layeredLayout(nodes, edges);
        this.bounds = graphBounds(this.positions, mapGroups(this.processMap));
        this.nodeLayer.innerHTML = '';
        this.edgeSvg.innerHTML = '';
        if (this.emptyState) this.emptyState.hidden = nodes.length > 0 || mapGroups(this.processMap).length > 0;

        const defs = svgElement('defs');
        const marker = svgElement('marker', {
            id: this.instanceId,
            markerWidth: 8,
            markerHeight: 8,
            refX: 7,
            refY: 4,
            orient: 'auto',
            markerUnits: 'strokeWidth',
        });
        marker.appendChild(svgElement('path', { d: 'M 0 0 L 8 4 L 0 8 z', class: 'pm-arrow-head' }));
        defs.appendChild(marker);
        this.edgeSvg.appendChild(defs);

        const worldWidth = Math.max(900, this.bounds.x + this.bounds.width + WORLD_PADDING);
        const worldHeight = Math.max(620, this.bounds.y + this.bounds.height + WORLD_PADDING);
        this.world.style.width = worldWidth + 'px';
        this.world.style.height = worldHeight + 'px';
        this.edgeSvg.setAttribute('width', worldWidth);
        this.edgeSvg.setAttribute('height', worldHeight);
        this.edgeSvg.setAttribute('viewBox', '0 0 ' + worldWidth + ' ' + worldHeight);
        this.renderGroups();
        this._renderGhostEdges();

        const labeledLogicalConnections = new Set();
        edges.forEach(function (edge) {
            const fromPosition = this.positions[edge.from.nodeId];
            const toPosition = this.positions[edge.to.nodeId];
            if (!fromPosition || !toPosition) return;
            const pathValue = bezierPath(
                portAnchor(fromPosition, 'out'),
                portAnchor(toPosition, 'in'),
                fromPosition.portOrientation,
                toPosition.portOrientation,
                fromPosition.portOrder,
                toPosition.portOrder
            );
            const edgeFindings = this.findings.filter(function (finding) {
                return finding && finding.edgeId === edge.edgeId;
            });
            const classes = [
                'pm-edge',
                'pm-edge-' + String(edge.kind || 'precedence'),
            ];
            if (edge.edgeId === this.selectedEdgeId) classes.push('selected');
            if (edgeFindings.some(function (finding) { return finding.severity === 'error'; })) {
                classes.push('invalid');
            }
            if (this.editable) {
                const hit = svgElement('path', {
                    d: pathValue,
                    class: 'pm-edge-hit',
                    'data-edge-id': edge.edgeId || '',
                    tabindex: '0',
                    role: 'button',
                    'aria-label': 'Select connection from ' + edge.from.nodeId + ' to ' + edge.to.nodeId,
                });
                hit.addEventListener('click', function (event) {
                    event.preventDefault();
                    event.stopPropagation();
                    this.selectEdge(edge.edgeId);
                }.bind(this));
                hit.addEventListener('keydown', function (event) {
                    if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        this.selectEdge(edge.edgeId);
                    }
                }.bind(this));
                this.edgeSvg.appendChild(hit);
            }
            const path = svgElement('path', {
                d: pathValue,
                class: classes.join(' '),
                'marker-end': 'url(#' + this.instanceId + ')',
                'data-edge-id': edge.edgeId || '',
            });
            if (edgeFindings.length) {
                const title = svgElement('title');
                title.textContent = edgeFindings.map(function (finding) {
                    return finding.message;
                }).join('\n');
                path.appendChild(title);
            }
            this.edgeSvg.appendChild(path);
            const logicalId = edge.logicalConnectionId || edge.edgeId;
            if (!labeledLogicalConnections.has(logicalId)) {
                labeledLogicalConnections.add(logicalId);
                this._renderEdgeContextLabel(edge);
            }
        }, this);

        nodes.forEach(function (node) {
            if (isJunctionNode(node)) this.renderJunction(node);
            else this.renderNode(node);
        }, this);
        this.updateHeader(nodes, edges);
        this.renderStructureTree();
        this._syncCardToolbar();
        this.applyTransform();
        this.updateEditControls();
        if (opts.fit && nodes.length) {
            const schedule = typeof requestAnimationFrame === 'function'
                ? requestAnimationFrame
                : function (callback) { return setTimeout(callback, 0); };
            schedule(this.fit.bind(this));
        }
    };

    ProcessMapEditor.prototype._positionNodeElement = function (element, position) {
        if (!element || !position) return;
        const left = position.isJunction ? position.x - JUNCTION_HIT_SIZE / 2 : position.x;
        const top = position.isJunction ? position.y - JUNCTION_HIT_SIZE / 2 : position.y;
        element.style.left = left + 'px';
        element.style.top = top + 'px';
    };

    ProcessMapEditor.prototype.renderJunction = function (node) {
        const position = this.positions[node.nodeId];
        if (!position) return;
        const wrapper = document.createElement('div');
        wrapper.className = 'pm-junction';
        if (node.nodeId === this.selectedNodeId) wrapper.classList.add('selected');
        this._positionNodeElement(wrapper, position);
        wrapper.style.width = JUNCTION_HIT_SIZE + 'px';
        wrapper.style.height = JUNCTION_HIT_SIZE + 'px';
        wrapper.setAttribute('data-node-id', node.nodeId);
        wrapper.setAttribute('data-node-kind', 'junction');
        wrapper.setAttribute('role', 'button');
        wrapper.setAttribute('aria-label', 'Wire junction');
        wrapper.tabIndex = 0;
        wrapper.title = 'Wire junction - drag to route or use the handle to branch';

        const dot = document.createElement('span');
        dot.className = 'pm-junction-dot';
        dot.style.width = JUNCTION_DOT_SIZE + 'px';
        dot.style.height = JUNCTION_DOT_SIZE + 'px';
        wrapper.appendChild(dot);

        if (this.editable) {
            const handle = document.createElement('button');
            handle.type = 'button';
            handle.className = 'pm-port pm-junction-handle';
            handle.textContent = '+';
            handle.setAttribute('data-node-id', node.nodeId);
            handle.setAttribute('data-port-side', 'out');
            handle.setAttribute('aria-label', 'Start a connection from this junction');
            handle.title = 'Start branch from junction';
            handle.addEventListener('pointerdown', this.startWire.bind(this, node.nodeId));
            wrapper.appendChild(handle);
            wrapper.addEventListener('pointerdown', this.startNodeDrag.bind(this, node.nodeId));
            wrapper.addEventListener('click', function (event) {
                if (this._suppressClick) {
                    event.preventDefault();
                    event.stopImmediatePropagation();
                    this._suppressClick = false;
                    return;
                }
                this.select(node.nodeId);
            }.bind(this));
        }
        wrapper.addEventListener('keydown', function (event) {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                this.select(node.nodeId);
            }
        }.bind(this));
        this.nodeLayer.appendChild(wrapper);
    };

    ProcessMapEditor.prototype.renderNode = function (node) {
        const position = this.positions[node.nodeId];
        if (!position) return;
        const wrapper = document.createElement('div');
        wrapper.className = 'pm-node pm-node-type-' + String(node.type || 'unknown')
            + ' pm-node-ports-' + nodePortOrientation(node)
            + ' pm-node-port-order-' + nodePortOrder(node);
        if (node.nodeId === this.selectedNodeId) wrapper.classList.add('selected');
        this._positionNodeElement(wrapper, position);
        wrapper.style.width = position.width + 'px';
        wrapper.style.height = position.height + 'px';
        wrapper.setAttribute('data-node-id', node.nodeId);
        wrapper.setAttribute('data-node-type', node.type || 'unknown');

        const type = document.createElement('span');
        type.className = 'pm-node-type';
        type.textContent = String(node.type || 'unknown').replace(/_/g, ' ');
        wrapper.appendChild(type);

        const nodeFindings = this.findings.filter(function (finding) {
            return finding && finding.nodeId === node.nodeId;
        });
        if (nodeFindings.length) {
            const badge = document.createElement('span');
            const hasError = nodeFindings.some(function (finding) { return finding.severity === 'error'; });
            badge.className = 'pm-node-finding ' + (hasError ? 'error' : 'warning');
            badge.textContent = String(nodeFindings.length);
            badge.title = nodeFindings.map(function (finding) { return finding.message; }).join('\n');
            wrapper.appendChild(badge);
        }

        if (node.note) {
            const note = document.createElement('span');
            note.className = 'pm-node-note-indicator';
            note.textContent = 'N';
            note.title = node.note;
            note.setAttribute('aria-label', 'Card note: ' + node.note);
            wrapper.appendChild(note);
        }

        const references = referenceItemsForTarget(this.processMap, 'node', node.nodeId);
        const referenceCounts = referenceSummary(references);
        if (referenceCounts.length) {
            const badges = document.createElement('div');
            badges.className = 'pm-reference-badges';
            badges.setAttribute('aria-hidden', 'true');
            referenceCounts.forEach(function (item) {
                const badge = document.createElement('span');
                badge.className = 'pm-reference-badge pm-reference-badge-' + item.kind;
                badge.textContent = referenceKindShortLabel(item.kind) + ' ' + item.count;
                badge.title = references.filter(function (reference) {
                    return reference.kind === item.kind;
                }).map(function (reference) { return reference.name; }).join('\n');
                badges.appendChild(badge);
            });
            wrapper.appendChild(badges);
        }

        const inputPort = document.createElement(this.editable ? 'button' : 'span');
        inputPort.className = 'pm-port pm-port-in';
        inputPort.textContent = '+';
        inputPort.setAttribute('data-node-id', node.nodeId);
        inputPort.setAttribute('data-port-side', 'in');
        if (this.editable) {
            inputPort.type = 'button';
            inputPort.setAttribute('aria-label', 'Connect into ' + (node.name || node.nodeId));
            inputPort.title = 'Connection input';
        } else {
            inputPort.setAttribute('aria-hidden', 'true');
        }
        const outputPort = document.createElement(this.editable ? 'button' : 'span');
        outputPort.className = 'pm-port pm-port-out';
        outputPort.textContent = '+';
        outputPort.setAttribute('data-node-id', node.nodeId);
        outputPort.setAttribute('data-port-side', 'out');
        if (this.editable) {
            outputPort.type = 'button';
            outputPort.setAttribute('aria-label', 'Connect from ' + (node.name || node.nodeId));
            outputPort.title = 'Drag to another node input';
            outputPort.addEventListener('pointerdown', this.startWire.bind(this, node.nodeId));
        } else {
            outputPort.setAttribute('aria-hidden', 'true');
        }
        wrapper.appendChild(inputPort);
        wrapper.appendChild(outputPort);

        const onSelect = this.select.bind(this);
        const card = typeof this.options.createNodeCard === 'function'
            ? this.options.createNodeCard(node, {
                selected: node.nodeId === this.selectedNodeId,
                onSelect: onSelect,
            })
            : fallbackCard(node, onSelect);
        card.classList.add('pm-node-card');
        card.addEventListener('keydown', function (event) {
            if (event.key !== 'Tab' || event.shiftKey) return;
            if (!this._focusCardToolbar(node.nodeId)) return;
            event.preventDefault();
        }.bind(this));
        wrapper.appendChild(card);
        if (this.editable) {
            wrapper.addEventListener('dragstart', function (event) {
                event.preventDefault();
            });
            wrapper.addEventListener('pointerdown', this.startNodeDrag.bind(this, node.nodeId));
            wrapper.addEventListener('click', function (event) {
                if (!this._suppressClick) return;
                event.preventDefault();
                event.stopImmediatePropagation();
                this._suppressClick = false;
            }.bind(this), true);
        }
        wrapper.addEventListener('dblclick', function (event) {
            if (this._suppressClick) return;
            event.preventDefault();
            event.stopPropagation();
            this.focus(node.nodeId);
        }.bind(this), true);
        this.nodeLayer.appendChild(wrapper);
    };

    ProcessMapEditor.prototype.updateHeader = function (nodes, edges) {
        const focus = this.focusNodeId && mapNodes(this.processMap).find(function (node) {
            return node && node.nodeId === this.focusNodeId;
        }, this);
        this.title.textContent = focus
            ? (focus.name || focus.nodeId)
            : String(this.processMap.displayName || 'Process Flow');
        const groups = mapGroups(this.processMap).length;
        this.subtitle.textContent = nodes.length + ' nodes / ' + edges.length
            + ' visible precedence connections / ' + groups + (groups === 1 ? ' group' : ' groups')
            + ' / ' + (this.editable ? 'editing' : 'read only');
        this.backButton.disabled = !this.focusNodeId;
    };

    ProcessMapEditor.prototype.select = function (nodeId, selectOptions) {
        const opts = selectOptions || {};
        this.selectedNodeId = nodeId;
        this.selectedEdgeId = null;
        this.selectedGroupId = null;
        Array.prototype.forEach.call(this.groupLayer.querySelectorAll('.pm-group-frame'), function (group) {
            group.classList.remove('selected');
        });
        Array.prototype.forEach.call(this.nodeLayer.querySelectorAll('.pm-node, .pm-junction'), function (node) {
            node.classList.toggle('selected', node.getAttribute('data-node-id') === nodeId);
        });
        Array.prototype.forEach.call(this.edgeSvg.querySelectorAll('.pm-edge'), function (edge) {
            edge.classList.remove('selected');
        });
        this.updateEditControls();
        const selectedNode = mapNodes(this.processMap).find(function (node) {
            return node && node.nodeId === nodeId;
        });
        if (!isJunctionNode(selectedNode) && typeof this.options.onSelect === 'function') {
            this.options.onSelect(
                nodeId,
                resolveCanvasNode(selectedNode, this.occurrenceById)
            );
        }
        if (isJunctionNode(selectedNode)) {
            this._closeCardToolbar('junction_selected', false);
        } else if (opts.openToolbar !== false) {
            this._openCardToolbar(selectedNode);
        }
    };

    ProcessMapEditor.prototype.selectEdge = function (edgeId) {
        this._closeCardToolbar('edge_selected', false);
        this.selectedEdgeId = edgeId;
        this.selectedNodeId = null;
        this.selectedGroupId = null;
        if (this.viewport && typeof this.viewport.focus === 'function') {
            this.viewport.focus({ preventScroll: true });
        }
        Array.prototype.forEach.call(this.nodeLayer.querySelectorAll('.pm-node, .pm-junction'), function (node) {
            node.classList.remove('selected');
        });
        Array.prototype.forEach.call(this.groupLayer.querySelectorAll('.pm-group-frame'), function (group) {
            group.classList.remove('selected');
        });
        Array.prototype.forEach.call(this.edgeSvg.querySelectorAll('.pm-edge'), function (edge) {
            edge.classList.toggle('selected', edge.getAttribute('data-edge-id') === edgeId);
        });
        this.updateEditControls();
        const edge = mapEdges(this.processMap).find(function (item) {
            return item && item.edgeId === edgeId;
        });
        this._openEdgeToolbar(edge);
    };

    ProcessMapEditor.prototype.selectGroup = function (groupId) {
        const group = mapGroups(this.processMap).find(function (item) {
            return item && item.groupId === groupId;
        });
        if (!group) return false;
        this._closeCardToolbar('group_selected', false);
        this.selectedGroupId = groupId;
        this.selectedNodeId = null;
        this.selectedEdgeId = null;
        Array.prototype.forEach.call(this.nodeLayer.querySelectorAll('.pm-node, .pm-junction'), function (node) {
            node.classList.remove('selected');
        });
        Array.prototype.forEach.call(this.edgeSvg.querySelectorAll('.pm-edge'), function (edge) {
            edge.classList.remove('selected');
        });
        Array.prototype.forEach.call(this.groupLayer.querySelectorAll('.pm-group-frame'), function (frame) {
            frame.classList.toggle('selected', frame.getAttribute('data-group-id') === groupId);
        });
        this.updateEditControls();
        this._openGroupToolbar(group);
        return true;
    };

    ProcessMapEditor.prototype.focus = function (nodeId) {
        if (isPlacementMap(this.processMap)) return;
        const children = mapNodes(this.processMap).filter(function (node) {
            return node && node.parentNodeId === nodeId;
        });
        if (!children.length) return;
        this.focusNodeId = nodeId;
        if (typeof this.options.onFocusChange === 'function') {
            this.options.onFocusChange(this.focusNodeId);
        }
        this.renderGraph({ fit: true });
    };

    ProcessMapEditor.prototype.back = function () {
        if (!this.focusNodeId) return;
        const focused = mapNodes(this.processMap).find(function (node) {
            return node && node.nodeId === this.focusNodeId;
        }, this);
        const parent = focused && focused.parentNodeId
            ? mapNodes(this.processMap).find(function (node) {
                return node && node.nodeId === focused.parentNodeId;
            })
            : null;
        this.focusNodeId = parent && parent.level >= 1 ? parent.nodeId : null;
        if (typeof this.options.onFocusChange === 'function') {
            this.options.onFocusChange(this.focusNodeId);
        }
        this.renderGraph({ fit: true });
    };

    ProcessMapEditor.prototype.exit = function () {
        if (!this.confirmDiscard()) return;
        this._closeCardToolbar('editor_exit', false);
        if (typeof this.options.onExit === 'function') this.options.onExit();
    };

    ProcessMapEditor.prototype.hasStructuralErrors = function () {
        return this.findings.some(function (finding) {
            return finding && finding.severity === 'error';
        });
    };

    ProcessMapEditor.prototype.updateEditControls = function () {
        if (!this.editable || !this.status) return;
        const commandStates = this.selectedNodeCommandStates();
        const canDeleteGroup = !!this.selectedGroupId && !this.saving && !this.conflict;
        if (this.undoButton) this.undoButton.disabled = !this.history.undoStack.length || this.saving || this.conflict;
        if (this.redoButton) this.redoButton.disabled = !this.history.redoStack.length || this.saving || this.conflict;
        if (this.deleteButton) this.deleteButton.disabled = !commandStates.canDelete && !canDeleteGroup;
        if (this.addStepButton) this.addStepButton.disabled = this.saving || this.conflict;
        if (this.addGroupButton) this.addGroupButton.disabled = this.saving || this.conflict;
        if (this.previewButton) this.previewButton.disabled = !commandStates.canPreview;
        if (this.analyzeButton) {
            this.analyzeButton.disabled = this.saving || this.conflict || this.hasStructuralErrors();
        }
        if (this.suggestionButton) {
            const suggestionCount = this.suggestions.length;
            this.suggestionButton.textContent = this.suggestionsLoading
                ? 'Suggestions...'
                : ('Suggestions' + (suggestionCount ? ' ' + suggestionCount : ''));
            this.suggestionButton.disabled = this.saving || this.conflict || !this.revision
                || (this.dirty && !suggestionCount);
            this.suggestionButton.classList.toggle('active', this.suggestionPanelOpen);
        }
        if (this.saveButton) {
            this.saveButton.disabled = !this.dirty || this.saving || this.conflict || this.hasStructuralErrors();
            this.saveButton.textContent = this.saving ? 'Saving...' : 'Save';
        }
        if (this.reloadButton) this.reloadButton.hidden = !this.conflict;
        if (this.mapSelect) this.mapSelect.disabled = this.saving || this.managementBusy;
        if (this.mapActionSelect) this.mapActionSelect.disabled = this.saving || this.managementBusy || this.conflict;
        if (this.typeSelect) {
            this.typeSelect.disabled = !commandStates.canRetype;
            this.typeSelect.value = commandStates.typeOptions.indexOf(commandStates.selectedType) >= 0
                ? commandStates.selectedType : '';
        }
        if (this.portOrientationSelect) {
            this.portOrientationSelect.disabled = !commandStates.canChangePorts;
            this.portOrientationSelect.value = commandStates.orientation;
        }
        if (this.portOrderSelect) {
            const orientation = commandStates.orientation;
            this.portOrderSelect.options[0].textContent = orientation === 'vertical'
                ? 'Input: top'
                : 'Input: left';
            this.portOrderSelect.options[1].textContent = orientation === 'vertical'
                ? 'Input: bottom'
                : 'Input: right';
            this.portOrderSelect.disabled = !commandStates.canChangePorts;
            this.portOrderSelect.value = commandStates.portOrder;
        }
        if (this.conflict) {
            this._closeCardToolbar('revision_conflict', false);
            this.status.textContent = 'A newer saved revision is available. Reload before editing further.';
            this.status.className = 'pm-editor-status conflict';
        } else if (this.managementBusy) {
            this.status.textContent = 'Updating process maps...';
            this.status.className = 'pm-editor-status';
        } else if (this.saving) {
            this.status.textContent = 'Saving process map...';
            this.status.className = 'pm-editor-status';
        } else if (this.hasStructuralErrors()) {
            this.status.textContent = 'Resolve structural errors before saving.';
            this.status.className = 'pm-editor-status error';
        } else if (this.operationError) {
            this.status.textContent = this.operationError;
            this.status.className = 'pm-editor-status error';
        } else if (this.dirty) {
            this.status.textContent = 'Unsaved changes';
            this.status.className = 'pm-editor-status dirty';
        } else {
            this.status.textContent = 'Saved';
            this.status.className = 'pm-editor-status';
        }
        this._refreshCardToolbar();
        this._renderSuggestionPanel();
    };

    ProcessMapEditor.prototype._setDirty = function (dirty) {
        const next = !!dirty;
        if (this.dirty === next) return;
        this.dirty = next;
        if (typeof this.options.onDirtyChange === 'function') {
            this.options.onDirtyChange(this.dirty);
        }
    };

    ProcessMapEditor.prototype._notifyMapChange = function () {
        if (typeof this.options.onMapChange === 'function') {
            this.options.onMapChange(cloneMap(this.processMap));
        }
    };

    ProcessMapEditor.prototype.commitMutation = function (nextMap, mutationOptions) {
        const opts = mutationOptions || {};
        if (!this.editable || this.conflict
            || mapFingerprint(nextMap) === mapFingerprint(this.processMap)) return false;
        this.history.record(this.processMap);
        this.processMap = cloneMap(nextMap);
        if (!opts.preserveSuggestions) this._clearSuggestions();
        this.findings = [];
        this.conflict = false;
        this.operationError = '';
        this._setDirty(mapFingerprint(this.processMap) !== this.savedFingerprint);
        this._notifyMapChange();
        this.renderGraph({ fit: false });
        return true;
    };

    ProcessMapEditor.prototype.applyNodeType = function (value) {
        const states = this.selectedNodeCommandStates();
        if (!states.canRetype || states.typeOptions.indexOf(value) < 0) return false;
        return this.commitMutation(retypeNode(this.processMap, this.selectedNodeId, value));
    };

    ProcessMapEditor.prototype.changeSelectedNodeType = function () {
        if (!this.typeSelect) return false;
        return this.applyNodeType(this.typeSelect.value);
    };

    ProcessMapEditor.prototype.applyNodeLabel = function (value) {
        const states = this.selectedNodeCommandStates();
        if (!states.canEditLabel || typeof value !== 'string') return false;
        return this.commitMutation(setNodeLabel(
            this.processMap,
            this.selectedNodeId,
            value
        ));
    };

    ProcessMapEditor.prototype.applyNodeNote = function (value) {
        const states = this.selectedNodeCommandStates();
        if (!states.canEditNote || typeof value !== 'string') return false;
        return this.commitMutation(setNodeNote(
            this.processMap,
            this.selectedNodeId,
            value
        ));
    };

    ProcessMapEditor.prototype.addConnectedStep = function (processType) {
        const states = this.selectedNodeCommandStates();
        if (!states.canAddConnectedStep || PROCESS_STEP_TYPES.indexOf(processType) < 0) {
            return false;
        }
        let nodeId;
        do {
            nodeId = 'pm-step-' + Date.now().toString(36) + '-' + (++this.nodeCounter);
        } while (mapNodes(this.processMap).some(function (node) {
            return node && node.nodeId === nodeId;
        }));
        let edgeId;
        do {
            edgeId = 'pm-edge-' + Date.now().toString(36) + '-' + (++this.edgeCounter);
        } while (mapEdges(this.processMap).some(function (edge) {
            return edge && edge.edgeId === edgeId;
        }));
        let nextMap = addConnectedProcessStep(this.processMap, {
            sourceNodeId: this.selectedNodeId,
            nodeId: nodeId,
            edgeId: edgeId,
            processType: processType,
        });
        const addedNode = mapNodes(nextMap).find(function (node) {
            return node && node.nodeId === nodeId;
        });
        if (addedNode && _finitePlacementPosition(addedNode.position)) {
            nextMap = resolveNodeGroupMembership(nextMap, nodeId, {
                x: addedNode.position.x + NODE_WIDTH / 2,
                y: addedNode.position.y + NODE_HEIGHT / 2,
            });
        }
        const changed = this.commitMutation(nextMap);
        if (changed) this.select(nodeId);
        return changed;
    };

    ProcessMapEditor.prototype.applyPortOrientation = function (value) {
        const states = this.selectedNodeCommandStates();
        if (!states.canChangePorts || PORT_ORIENTATIONS.indexOf(value) < 0) return false;
        return this.commitMutation(setNodePortOrientation(
            this.processMap,
            this.selectedNodeId,
            value
        ));
    };

    ProcessMapEditor.prototype.changeSelectedPortOrientation = function () {
        if (!this.portOrientationSelect) return false;
        return this.applyPortOrientation(this.portOrientationSelect.value);
    };

    ProcessMapEditor.prototype.applyPortOrder = function (value) {
        const states = this.selectedNodeCommandStates();
        if (!states.canChangePorts || PORT_ORDERS.indexOf(value) < 0) return false;
        return this.commitMutation(setNodePortOrder(
            this.processMap,
            this.selectedNodeId,
            value
        ));
    };

    ProcessMapEditor.prototype.changeSelectedPortOrder = function () {
        if (!this.portOrderSelect) return false;
        return this.applyPortOrder(this.portOrderSelect.value);
    };

    ProcessMapEditor.prototype.openSelectedPreview = function () {
        const states = this.selectedNodeCommandStates();
        if (!states.canPreview) return false;
        const wrapper = this.nodeLayer.querySelector(
            '[data-node-id="' + states.node.nodeId + '"]'
        );
        if (!wrapper) return false;
        const sourceElement = wrapper.querySelector('.pm-node-card') || wrapper;
        const previewNode = resolveCanvasNode(states.node, this.occurrenceById);
        this._closeCardToolbar('preview', false);
        this.options.onOpenPreview(previewNode, sourceElement);
        return true;
    };

    ProcessMapEditor.prototype.deleteSelection = function () {
        this._closeCardToolbar('delete_selection', false);
        if (this.selectedGroupId) {
            const groupId = this.selectedGroupId;
            this.selectedGroupId = null;
            return this.commitMutation(deleteGroup(this.processMap, groupId));
        }
        if (this.selectedNodeId) {
            const nodeId = this.selectedNodeId;
            this.selectedNodeId = null;
            return this.commitMutation(deleteNode(this.processMap, nodeId));
        }
        if (this.selectedEdgeId) {
            const edgeId = this.selectedEdgeId;
            this.selectedEdgeId = null;
            return this.commitMutation(deleteEdge(this.processMap, edgeId));
        }
        return false;
    };

    ProcessMapEditor.prototype.undo = function () {
        const previous = this.history.undo(this.processMap);
        if (!previous) return false;
        this.processMap = previous;
        this.findings = [];
        this.conflict = false;
        this.operationError = '';
        this.selectedEdgeId = null;
        this.selectedNodeId = null;
        this.selectedGroupId = null;
        this._clearSuggestions();
        this._setDirty(mapFingerprint(this.processMap) !== this.savedFingerprint);
        this._notifyMapChange();
        this.renderGraph({ fit: false });
        if (!this.dirty) this._scheduleSuggestionLoad();
        return true;
    };

    ProcessMapEditor.prototype.redo = function () {
        const next = this.history.redo(this.processMap);
        if (!next) return false;
        this.processMap = next;
        this.findings = [];
        this.conflict = false;
        this.operationError = '';
        this.selectedEdgeId = null;
        this.selectedNodeId = null;
        this.selectedGroupId = null;
        this._clearSuggestions();
        this._setDirty(mapFingerprint(this.processMap) !== this.savedFingerprint);
        this._notifyMapChange();
        this.renderGraph({ fit: false });
        if (!this.dirty) this._scheduleSuggestionLoad();
        return true;
    };

    ProcessMapEditor.prototype.markSaved = function (result) {
        const payload = result || {};
        if (payload.map) this.processMap = cloneMap(payload.map);
        if (payload.revision) this.revision = payload.revision;
        if (payload.productStructure) this.setProductStructure(payload.productStructure);
        if (payload.mapCatalog) this.setMapCatalog(payload.mapCatalog);
        else this.setMapCatalog(this.mapCatalog);
        this.findings = Array.isArray(payload.findings) ? payload.findings : [];
        this.savedMap = cloneMap(this.processMap);
        this.savedFingerprint = mapFingerprint(this.savedMap);
        this.history.clear();
        this._clearSuggestions();
        this.conflict = false;
        this.operationError = '';
        this._setDirty(false);
        this._notifyMapChange();
        this.renderGraph({ fit: false });
        this._scheduleSuggestionLoad();
    };

    ProcessMapEditor.prototype.save = async function () {
        if (!this.editable || !this.dirty || this.saving || this.hasStructuralErrors()) return false;
        if (typeof this.options.onSave !== 'function') return false;
        this.saving = true;
        this.updateEditControls();
        try {
            const result = await this.options.onSave(cloneMap(this.processMap), this.revision);
            if (result && result.ok === false) {
                this.findings = Array.isArray(result.findings) ? result.findings : this.findings;
                this.conflict = result.status === 409 || result.error === 'revision_conflict';
                this.operationError = this.conflict ? '' : 'Save failed. Review the validation results.';
                this.renderGraph({ fit: false });
                return false;
            }
            this.markSaved(result || {});
            return true;
        } catch (error) {
            this.operationError = 'Save failed: '
                + (error && error.message ? error.message : String(error));
            return false;
        } finally {
            this.saving = false;
            this.updateEditControls();
            if (!this.dirty) this._scheduleSuggestionLoad();
        }
    };

    ProcessMapEditor.prototype._clearSuggestions = function () {
        this.suggestionRequestToken += 1;
        this.suggestions = [];
        this.suggestionsRevision = null;
        this.suggestionsLoading = false;
        this.suggestionsError = '';
        this.focusedSuggestionId = null;
    };

    ProcessMapEditor.prototype._scheduleSuggestionLoad = function () {
        if (this.destroyed || this.dirty || this.saving || this.conflict
            || !this.revision || typeof this.options.onLoadSuggestions !== 'function') return;
        const schedule = typeof setTimeout === 'function'
            ? setTimeout
            : function (callback) { callback(); };
        schedule(function () {
            if (!this.destroyed) this.loadSuggestions();
        }.bind(this), 0);
    };

    ProcessMapEditor.prototype.loadSuggestions = async function () {
        if (this.destroyed || this.dirty || this.saving || this.conflict
            || !this.revision || typeof this.options.onLoadSuggestions !== 'function') {
            return false;
        }
        const revision = String(this.revision);
        const requestToken = ++this.suggestionRequestToken;
        this.suggestionsLoading = true;
        this.suggestionsError = '';
        this.updateEditControls();
        try {
            const payload = await this.options.onLoadSuggestions({
                productId: String(this.processMap.productId || ''),
                mapId: String(this.processMap.mapId || 'default'),
                revision: revision,
            });
            if (this.destroyed || requestToken !== this.suggestionRequestToken
                || this.dirty || String(this.revision || '') !== revision) return false;
            if (!payload || payload.ok === false) {
                this.suggestions = [];
                this.suggestionsRevision = null;
                if (payload && payload.status === 409) {
                    this.conflict = true;
                    this.suggestionsError = 'The saved map changed. Reload before reviewing suggestions.';
                } else {
                    this.suggestionsError = 'Suggestions are temporarily unavailable.';
                }
                return false;
            }
            if (String(payload.revision || '') !== revision) {
                this.suggestions = [];
                this.suggestionsRevision = null;
                this.suggestionsError = 'Suggestions were returned for a different map revision.';
                return false;
            }
            this.suggestions = Array.isArray(payload.suggestions)
                ? cloneMap(payload.suggestions)
                : [];
            this.suggestionsRevision = revision;
            this.suggestionsError = '';
            this.renderGraph({ fit: false });
            return true;
        } catch (error) {
            if (requestToken === this.suggestionRequestToken) {
                this.suggestions = [];
                this.suggestionsRevision = null;
                this.suggestionsError = 'Suggestions are temporarily unavailable.';
            }
            return false;
        } finally {
            if (requestToken === this.suggestionRequestToken) {
                this.suggestionsLoading = false;
                this.updateEditControls();
            }
        }
    };

    ProcessMapEditor.prototype.toggleSuggestionPanel = function () {
        if (!this.suggestionPanel) return false;
        this.suggestionPanelOpen = !this.suggestionPanelOpen;
        this._renderSuggestionPanel();
        if (this.suggestionPanelOpen && !this.suggestions.length
            && !this.suggestionsLoading && !this.dirty) {
            this.loadSuggestions();
        }
        return true;
    };

    ProcessMapEditor.prototype.focusSuggestion = function (suggestionId) {
        if (!this.suggestionPanel) return false;
        this.focusedSuggestionId = suggestionId;
        this.suggestionPanelOpen = true;
        this._renderSuggestionPanel();
        const item = this.suggestionPanel.querySelector(
            '[data-suggestion-id="' + suggestionId + '"]'
        );
        if (item && typeof item.scrollIntoView === 'function') {
            item.scrollIntoView({ block: 'nearest' });
        }
        return true;
    };

    ProcessMapEditor.prototype._renderSuggestionPanel = function () {
        if (!this.suggestionPanel) return;
        this.suggestionPanel.hidden = !this.suggestionPanelOpen;
        this.suggestionPanel.innerHTML = '';
        if (!this.suggestionPanelOpen) return;

        const header = document.createElement('div');
        header.className = 'pm-suggestion-panel-header';
        const heading = document.createElement('div');
        heading.className = 'pm-suggestion-panel-title';
        heading.textContent = 'Flow suggestions';
        const close = this._button('x', 'Close suggestions', function () {
            this.suggestionPanelOpen = false;
            this._renderSuggestionPanel();
        }.bind(this));
        header.appendChild(heading);
        header.appendChild(close);
        this.suggestionPanel.appendChild(header);

        if (this.suggestionsLoading) {
            const loading = document.createElement('div');
            loading.className = 'pm-suggestion-empty';
            loading.textContent = 'Reviewing saved flow evidence...';
            this.suggestionPanel.appendChild(loading);
            return;
        }
        if (this.suggestionsError) {
            const error = document.createElement('div');
            error.className = 'pm-suggestion-empty error';
            error.textContent = this.suggestionsError;
            this.suggestionPanel.appendChild(error);
            return;
        }
        if (!this.suggestions.length) {
            const empty = document.createElement('div');
            empty.className = 'pm-suggestion-empty';
            empty.textContent = 'No evidence-backed suggestions for this saved revision.';
            this.suggestionPanel.appendChild(empty);
            return;
        }

        const edgeSuggestions = this.suggestions.filter(function (suggestion) {
            return suggestion && suggestion.edge
                && !(suggestion.validation && suggestion.validation.wouldCreateCycle);
        });
        if (edgeSuggestions.length > 1 && this.editable && !this.dirty) {
            const acceptAll = this._button(
                'Accept all safe',
                'Accept every currently valid connection suggestion',
                this.acceptAllSuggestions.bind(this)
            );
            acceptAll.classList.add('pm-suggestion-accept-all');
            this.suggestionPanel.appendChild(acceptAll);
        }

        const list = document.createElement('div');
        list.className = 'pm-suggestion-list';
        this.suggestions.forEach(function (suggestion) {
            const item = document.createElement('section');
            item.className = 'pm-suggestion-item';
            if (suggestion.suggestionId === this.focusedSuggestionId) {
                item.classList.add('focused');
            }
            item.setAttribute('data-suggestion-id', suggestion.suggestionId || '');
            const meta = document.createElement('div');
            meta.className = 'pm-suggestion-meta';
            const kind = suggestion.edge ? 'Connection' : 'Resource review';
            meta.textContent = kind + ' / ' + String(suggestion.confidence || 'review') + ' confidence';
            const explanation = document.createElement('div');
            explanation.className = 'pm-suggestion-explanation';
            explanation.textContent = String(suggestion.explanation || 'Review this suggestion.');
            item.appendChild(meta);
            item.appendChild(explanation);
            if (suggestion.validation && suggestion.validation.wouldCreateCycle) {
                const warning = document.createElement('div');
                warning.className = 'pm-suggestion-warning';
                warning.textContent = 'Not applicable: this connection would create a precedence cycle.';
                item.appendChild(warning);
            }
            const provenance = document.createElement('div');
            provenance.className = 'pm-suggestion-provenance';
            (Array.isArray(suggestion.provenance) ? suggestion.provenance : []).forEach(
                function (evidence) {
                    const tag = document.createElement('span');
                    tag.textContent = String(evidence.source || 'evidence').replaceAll('_', ' ');
                    provenance.appendChild(tag);
                }
            );
            item.appendChild(provenance);
            const actions = document.createElement('div');
            actions.className = 'pm-suggestion-actions';
            if (suggestion.edge) {
                const accept = this._button(
                    'Accept',
                    'Add this proposed connection',
                    this.acceptSuggestion.bind(this, suggestion.suggestionId)
                );
                accept.disabled = !this.editable || !!(
                    suggestion.validation && suggestion.validation.wouldCreateCycle
                );
                actions.appendChild(accept);
            }
            const dismiss = this._button(
                'Dismiss',
                'Hide this exact evidence-backed suggestion',
                this.dismissProcessSuggestion.bind(this, suggestion.suggestionId)
            );
            dismiss.disabled = !this.editable;
            actions.appendChild(dismiss);
            item.appendChild(actions);
            list.appendChild(item);
        }, this);
        this.suggestionPanel.appendChild(list);
    };

    ProcessMapEditor.prototype.acceptSuggestion = function (suggestionId) {
        const suggestion = this.suggestions.find(function (item) {
            return item && item.suggestionId === suggestionId;
        });
        if (!suggestion) return false;
        const result = acceptSuggestions(this.processMap, [suggestion]);
        if (!result.accepted.length) {
            this.operationError = result.skipped.length
                ? 'This suggestion is no longer valid for the current map.'
                : 'No connection was added.';
            this.updateEditControls();
            return false;
        }
        return this.commitMutation(result.map);
    };

    ProcessMapEditor.prototype.acceptAllSuggestions = function () {
        const result = acceptSuggestions(this.processMap, this.suggestions);
        if (!result.accepted.length) {
            this.operationError = 'No valid connection suggestions are available.';
            this.updateEditControls();
            return false;
        }
        const changed = this.commitMutation(result.map);
        if (changed && result.skipped.length) {
            this.operationError = result.skipped.length + ' suggestion(s) were skipped by validation.';
            this.updateEditControls();
        }
        return changed;
    };

    ProcessMapEditor.prototype.dismissProcessSuggestion = function (suggestionId) {
        const nextMap = dismissSuggestion(this.processMap, suggestionId);
        if (mapFingerprint(nextMap) === mapFingerprint(this.processMap)) return false;
        this.suggestions = this.suggestions.filter(function (item) {
            return item && item.suggestionId !== suggestionId;
        });
        this.focusedSuggestionId = null;
        return this.commitMutation(nextMap, { preserveSuggestions: true });
    };

    ProcessMapEditor.prototype.analyze = async function () {
        if (this.saving || this.conflict || this.hasStructuralErrors()) return false;
        if (this.dirty) {
            const saved = await this.save();
            if (!saved) return false;
        }
        if (typeof this.options.onAnalyze !== 'function' || !this.revision) return false;
        return this.options.onAnalyze({
            productId: String(this.processMap.productId || ''),
            mapId: String(this.processMap.mapId || 'default'),
            revision: String(this.revision),
        }) !== false;
    };

    ProcessMapEditor.prototype.reload = async function () {
        if (this.saving || typeof this.options.onReload !== 'function') return false;
        this.saving = true;
        this.updateEditControls();
        try {
            const result = await this.options.onReload();
            if (!result || result.ok === false || !result.map) return false;
            this.processMap = cloneMap(result.map);
            this.revision = result.revision || null;
            if (result.productStructure) this.setProductStructure(result.productStructure);
            if (result.mapCatalog) this.setMapCatalog(result.mapCatalog);
            else this.setMapCatalog(this.mapCatalog);
            this.findings = Array.isArray(result.findings) ? result.findings : [];
            this.savedMap = cloneMap(this.processMap);
            this.savedFingerprint = mapFingerprint(this.savedMap);
            this.history.clear();
            this._clearSuggestions();
            this.conflict = false;
            this.operationError = '';
            this._setDirty(false);
            this._notifyMapChange();
            this.renderGraph({ fit: true });
            return true;
        } finally {
            this.saving = false;
            this.updateEditControls();
            if (!this.dirty) this._scheduleSuggestionLoad();
        }
    };

    ProcessMapEditor.prototype.discardChanges = function () {
        if (!this.dirty) return;
        this.processMap = cloneMap(this.savedMap);
        this.history.clear();
        this._clearSuggestions();
        this.findings = [];
        this.conflict = false;
        this.operationError = '';
        this._setDirty(false);
        this._notifyMapChange();
        this.renderGraph({ fit: false });
        this._scheduleSuggestionLoad();
    };

    ProcessMapEditor.prototype.setProductStructure = function (structure) {
        this.productStructure = normalizeProductStructure(structure);
        const catalog = occurrenceIndex(this.productStructure);
        this.occurrenceById = catalog.byId;
        this.occurrenceChildren = catalog.children;
        this.renderStructureTree();
    };

    ProcessMapEditor.prototype.confirmDiscard = function () {
        if (!this.dirty) return true;
        const confirmDiscard = typeof this.options.confirmDiscard === 'function'
            ? this.options.confirmDiscard
            : function () {
                return typeof window === 'undefined'
                    ? false
                    : window.confirm('Discard unsaved process-map changes?');
            };
        if (!confirmDiscard()) return false;
        this.discardChanges();
        return true;
    };

    ProcessMapEditor.prototype.applyTransform = function () {
        this.world.style.transform = 'translate(' + this.transform.x + 'px, '
            + this.transform.y + 'px) scale(' + this.transform.scale + ')';
        if (this.cardToolbarManager && this.cardToolbarManager.isOpen()) {
            this.cardToolbarManager.reposition();
        }
    };

    ProcessMapEditor.prototype.fit = function () {
        if (this.destroyed || !this.viewport) return;
        const rect = this.viewport.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        const margin = 54;
        const scale = clamp(
            Math.min(
                (rect.width - margin * 2) / Math.max(1, this.bounds.width),
                (rect.height - margin * 2) / Math.max(1, this.bounds.height)
            ),
            MIN_SCALE,
            1.15
        );
        this.transform.scale = scale;
        this.transform.x = (rect.width - this.bounds.width * scale) / 2 - this.bounds.x * scale;
        this.transform.y = (rect.height - this.bounds.height * scale) / 2 - this.bounds.y * scale;
        this.applyTransform();
    };

    ProcessMapEditor.prototype.zoomBy = function (factor) {
        if (!this.viewport) return;
        const rect = this.viewport.getBoundingClientRect();
        this.zoomAt(rect.width / 2, rect.height / 2, factor);
    };

    ProcessMapEditor.prototype.zoomAt = function (x, y, factor) {
        const previous = this.transform.scale;
        const next = clamp(previous * factor, MIN_SCALE, MAX_SCALE);
        if (next === previous) return;
        const worldX = (x - this.transform.x) / previous;
        const worldY = (y - this.transform.y) / previous;
        this.transform.scale = next;
        this.transform.x = x - worldX * next;
        this.transform.y = y - worldY * next;
        this.applyTransform();
    };

    ProcessMapEditor.prototype.wheel = function (event) {
        event.preventDefault();
        const rect = this.viewport.getBoundingClientRect();
        this.zoomAt(
            event.clientX - rect.left,
            event.clientY - rect.top,
            event.deltaY < 0 ? 1.1 : 0.9
        );
    };

    ProcessMapEditor.prototype.clientToWorld = function (clientX, clientY) {
        const rect = this.viewport.getBoundingClientRect();
        return {
            x: (clientX - rect.left - this.transform.x) / this.transform.scale,
            y: (clientY - rect.top - this.transform.y) / this.transform.scale,
        };
    };

    ProcessMapEditor.prototype.startGroupDrag = function (groupId, event) {
        if (!this.editable || this.conflict || event.button !== 0) return;
        const group = this.groupPositions && this.groupPositions[groupId];
        if (!group) return;
        event.preventDefault();
        event.stopPropagation();
        this.selectGroup(groupId);
        const members = new Set(Array.isArray(group.memberNodeIds) ? group.memberNodeIds : []);
        const memberStarts = {};
        members.forEach(function (nodeId) {
            const position = this.positions[nodeId];
            if (position) memberStarts[nodeId] = { x: position.x, y: position.y };
        }, this);
        this.interaction = {
            mode: 'group',
            pointerId: event.pointerId,
            groupId: groupId,
            clientX: event.clientX,
            clientY: event.clientY,
            startX: group.position.x,
            startY: group.position.y,
            memberStarts: memberStarts,
            withMembers: !(event.altKey || this.groupMoveFrameOnly),
            moved: false,
            captured: false,
        };
    };

    ProcessMapEditor.prototype.startGroupResize = function (groupId, corner, event) {
        if (!this.editable || this.conflict || event.button !== 0) return;
        const group = this.groupPositions && this.groupPositions[groupId];
        if (!group) return;
        event.preventDefault();
        event.stopPropagation();
        this.selectGroup(groupId);
        this.interaction = {
            mode: 'group-resize',
            pointerId: event.pointerId,
            groupId: groupId,
            corner: corner,
            clientX: event.clientX,
            clientY: event.clientY,
            startX: group.position.x,
            startY: group.position.y,
            startWidth: group.size.width,
            startHeight: group.size.height,
            moved: false,
        };
        this.viewport.setPointerCapture(event.pointerId);
    };

    ProcessMapEditor.prototype.startNodeDrag = function (nodeId, event) {
        if (!this.editable || this.conflict || event.button !== 0
            || event.target.closest('.pm-port, select')) return;
        const position = this.positions[nodeId];
        if (!position) return;
        event.stopPropagation();
        this.interaction = {
            mode: 'node',
            pointerId: event.pointerId,
            nodeId: nodeId,
            clientX: event.clientX,
            clientY: event.clientY,
            startX: position.x,
            startY: position.y,
            moved: false,
            captured: false,
        };
    };

    ProcessMapEditor.prototype.startWire = function (nodeId, event) {
        if (!this.editable || this.conflict || event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        const position = this.positions[nodeId];
        if (!position) return;
        this._closeCardToolbar('wire_started', false);
        this.select(nodeId, { openToolbar: false });
        this.interaction = {
            mode: 'wire',
            pointerId: event.pointerId,
            fromId: nodeId,
            start: portAnchor(position, 'out'),
            startOrientation: position.portOrientation,
            startOrder: position.portOrder,
            snapTarget: null,
        };
        this.pendingPath = svgElement('path', {
            class: 'pm-edge pm-edge-pending',
            d: bezierPath(
                this.interaction.start,
                this.interaction.start,
                this.interaction.startOrientation,
                this.interaction.startOrientation,
                this.interaction.startOrder,
                this.interaction.startOrder
            ),
        });
        this.edgeSvg.appendChild(this.pendingPath);
        this.viewport.setPointerCapture(event.pointerId);
    };

    ProcessMapEditor.prototype._directWireTargetAt = function (clientX, clientY, fromId) {
        if (typeof document === 'undefined' || typeof document.elementFromPoint !== 'function') return null;
        const target = document.elementFromPoint(clientX, clientY);
        const port = target && target.closest ? target.closest('.pm-port-in') : null;
        if (port && this.root.contains(port)) {
            const nodeId = port.getAttribute('data-node-id');
            const position = this.positions[nodeId];
            if (nodeId && nodeId !== fromId && position) {
                return {
                    kind: 'node',
                    nodeId: nodeId,
                    element: port,
                    point: portAnchor(position, 'in'),
                    portOrientation: position.portOrientation,
                    portOrder: position.portOrder,
                    distance: 0,
                };
            }
        }
        const junction = target && target.closest ? target.closest('.pm-junction') : null;
        if (junction && this.root.contains(junction)) {
            const nodeId = junction.getAttribute('data-node-id');
            const position = this.positions[nodeId];
            if (nodeId && nodeId !== fromId && position) {
                return {
                    kind: 'junction',
                    nodeId: nodeId,
                    element: junction,
                    point: portAnchor(position, 'in'),
                    distance: 0,
                };
            }
        }
        return null;
    };

    ProcessMapEditor.prototype._nearestPointOnPath = function (path, world) {
        let length;
        try { length = path.getTotalLength(); } catch (_) { return null; }
        if (!finiteNumber(length) || length <= 0) return null;
        const sampleCount = clamp(Math.ceil(length * this.transform.scale / 8), 16, 180);
        const step = length / sampleCount;
        let bestLength = 0;
        let bestPoint = path.getPointAtLength(0);
        let bestDistance = Math.hypot(bestPoint.x - world.x, bestPoint.y - world.y);
        for (let index = 1; index <= sampleCount; index += 1) {
            const cursor = Math.min(length, index * step);
            const point = path.getPointAtLength(cursor);
            const distance = Math.hypot(point.x - world.x, point.y - world.y);
            if (distance < bestDistance) {
                bestDistance = distance;
                bestLength = cursor;
                bestPoint = point;
            }
        }
        let low = Math.max(0, bestLength - step);
        let high = Math.min(length, bestLength + step);
        for (let pass = 0; pass < 8; pass += 1) {
            const firstLength = low + (high - low) / 3;
            const secondLength = high - (high - low) / 3;
            const first = path.getPointAtLength(firstLength);
            const second = path.getPointAtLength(secondLength);
            const firstDistance = Math.hypot(first.x - world.x, first.y - world.y);
            const secondDistance = Math.hypot(second.x - world.x, second.y - world.y);
            if (firstDistance <= secondDistance) high = secondLength;
            else low = firstLength;
        }
        bestLength = (low + high) / 2;
        bestPoint = path.getPointAtLength(bestLength);
        bestDistance = Math.hypot(bestPoint.x - world.x, bestPoint.y - world.y);
        return {
            point: { x: bestPoint.x, y: bestPoint.y },
            length: bestLength,
            totalLength: length,
            distance: bestDistance * this.transform.scale,
        };
    };

    ProcessMapEditor.prototype._nearestWireTarget = function (clientX, clientY, fromId) {
        const direct = this._directWireTargetAt(clientX, clientY, fromId);
        if (direct) return direct;
        const world = this.clientToWorld(clientX, clientY);
        let nearestJunction = null;
        mapNodes(this.processMap).forEach(function (node) {
            if (!isJunctionNode(node) || node.nodeId === fromId) return;
            const position = this.positions[node.nodeId];
            if (!position) return;
            const distance = Math.hypot(position.x - world.x, position.y - world.y)
                * this.transform.scale;
            if (distance <= WIRE_SNAP_THRESHOLD_PX
                && (!nearestJunction || distance < nearestJunction.distance)) {
                nearestJunction = {
                    kind: 'junction',
                    nodeId: node.nodeId,
                    element: this.nodeLayer.querySelector('[data-node-id="' + node.nodeId + '"]'),
                    point: { x: position.x, y: position.y },
                    distance: distance,
                };
            }
        }, this);
        if (nearestJunction) return nearestJunction;

        let best = null;
        Array.prototype.forEach.call(this.edgeSvg.querySelectorAll('.pm-edge-hit'), function (path) {
            const edgeId = path.getAttribute('data-edge-id');
            const edge = mapEdges(this.processMap).find(function (item) {
                return item && item.edgeId === edgeId;
            });
            if (!edge || !edge.from || !edge.to
                || edge.from.nodeId === fromId || edge.to.nodeId === fromId) return;
            const nearest = this._nearestPointOnPath(path, world);
            if (!nearest || nearest.distance > WIRE_SNAP_THRESHOLD_PX) return;
            const fromPosition = this.positions[edge.from.nodeId];
            const toPosition = this.positions[edge.to.nodeId];
            if (!fromPosition || !toPosition) return;
            const start = portAnchor(fromPosition, 'out');
            const end = portAnchor(toPosition, 'in');
            const startDistance = Math.hypot(start.x - world.x, start.y - world.y)
                * this.transform.scale;
            const endDistance = Math.hypot(end.x - world.x, end.y - world.y)
                * this.transform.scale;
            let candidate;
            if (Math.min(startDistance, endDistance) <= WIRE_SNAP_THRESHOLD_PX) {
                const useStart = startDistance <= endDistance;
                candidate = {
                    kind: 'endpoint',
                    edgeId: edgeId,
                    nodeId: useStart ? edge.from.nodeId : edge.to.nodeId,
                    point: useStart ? start : end,
                    distance: Math.min(startDistance, endDistance),
                };
            } else {
                candidate = {
                    kind: 'edge',
                    edgeId: edgeId,
                    point: nearest.point,
                    distance: nearest.distance,
                };
            }
            if (!best || candidate.distance < best.distance) best = candidate;
        }, this);
        return best;
    };

    ProcessMapEditor.prototype._markEdgeBranchTarget = function (edgeId, active) {
        Array.prototype.forEach.call(this.edgeSvg.querySelectorAll('[data-edge-id]'), function (path) {
            if (path.getAttribute('data-edge-id') === edgeId) {
                path.classList.toggle('branch-target', !!active);
            }
        });
    };

    ProcessMapEditor.prototype._clearWireTarget = function (action) {
        const target = action && action.snapTarget;
        if (target && target.element) target.element.classList.remove('snap-target');
        if (target && target.edgeId) this._markEdgeBranchTarget(target.edgeId, false);
        if (this.junctionPreview) this.junctionPreview.remove();
        this.junctionPreview = null;
        if (action) action.snapTarget = null;
    };

    ProcessMapEditor.prototype._setWireTarget = function (target) {
        const action = this.interaction;
        if (!action || action.mode !== 'wire') return;
        this._clearWireTarget(action);
        action.snapTarget = target || null;
        if (!target) return;
        if (target.element) target.element.classList.add('snap-target');
        if (target.edgeId) this._markEdgeBranchTarget(target.edgeId, true);
        if (target.kind === 'edge') {
            this.junctionPreview = svgElement('circle', {
                class: 'pm-junction-preview',
                cx: target.point.x,
                cy: target.point.y,
                r: JUNCTION_DOT_SIZE / 2,
            });
            this.edgeSvg.appendChild(this.junctionPreview);
        }
    };

    ProcessMapEditor.prototype._updateEdgeGeometry = function () {
        Array.prototype.forEach.call(
            this.edgeSvg.querySelectorAll('[data-edge-id]'),
            function (path) {
                const edgeId = path.getAttribute('data-edge-id');
                const edge = mapEdges(this.processMap).find(function (item) {
                    return item && item.edgeId === edgeId;
                });
                if (!edge || !edge.from || !edge.to) return;
                const fromPosition = this.positions[edge.from.nodeId];
                const toPosition = this.positions[edge.to.nodeId];
                if (!fromPosition || !toPosition) return;
                path.setAttribute('d', bezierPath(
                    portAnchor(fromPosition, 'out'),
                    portAnchor(toPosition, 'in'),
                    fromPosition.portOrientation,
                    toPosition.portOrientation,
                    fromPosition.portOrder,
                    toPosition.portOrder
                ));
            }.bind(this)
        );
        this._positionEdgeContextLabels();
        if (this.cardToolbarManager && this.cardToolbarManager.isOpen()
            && this.cardToolbarEdgeId) {
            this.cardToolbarManager.reposition();
        }
    };

    ProcessMapEditor.prototype.pointerDown = function (event) {
        if (event.button !== 0 || event.target.closest(
            '.pm-node, .pm-junction, button, .pm-edge-hit, .pm-ghost-edge-hit'
        )) return;
        this.interaction = {
            mode: 'pan',
            pointerId: event.pointerId,
            clientX: event.clientX,
            clientY: event.clientY,
            startX: this.transform.x,
            startY: this.transform.y,
        };
        this.viewport.setPointerCapture(event.pointerId);
        this.viewport.classList.add('panning');
    };

    ProcessMapEditor.prototype.pointerMove = function (event) {
        const action = this.interaction;
        if (!action || event.pointerId !== action.pointerId) return;
        if (action.mode === 'pan') {
            this.transform.x = action.startX + event.clientX - action.clientX;
            this.transform.y = action.startY + event.clientY - action.clientY;
            this.applyTransform();
            return;
        }
        if (action.mode === 'group') {
            const dx = (event.clientX - action.clientX) / this.transform.scale;
            const dy = (event.clientY - action.clientY) / this.transform.scale;
            if (!action.moved && Math.hypot(dx, dy) < 4) return;
            action.moved = true;
            if (!action.captured) {
                this.viewport.setPointerCapture(event.pointerId);
                action.captured = true;
            }
            const group = this.groupPositions && this.groupPositions[action.groupId];
            const frame = this.groupLayer.querySelector('[data-group-id="' + action.groupId + '"]');
            if (!group || !frame) return;
            group.position.x = action.startX + dx;
            group.position.y = action.startY + dy;
            this._positionGroupElement(frame, group);
            frame.classList.add('dragging');
            if (action.withMembers) {
                Object.keys(action.memberStarts).forEach(function (nodeId) {
                    const position = this.positions[nodeId];
                    const start = action.memberStarts[nodeId];
                    const wrapper = this.nodeLayer.querySelector('[data-node-id="' + nodeId + '"]');
                    if (!position || !start || !wrapper) return;
                    position.x = start.x + dx;
                    position.y = start.y + dy;
                    this._positionNodeElement(wrapper, position);
                }, this);
                this._updateEdgeGeometry();
            }
            if (this.cardToolbarManager && this.cardToolbarManager.isOpen()
                && this.cardToolbarGroupId === action.groupId) {
                this.cardToolbarManager.reposition();
            }
            return;
        }
        if (action.mode === 'group-resize') {
            const dx = (event.clientX - action.clientX) / this.transform.scale;
            const dy = (event.clientY - action.clientY) / this.transform.scale;
            if (!action.moved && Math.hypot(dx, dy) < 3) return;
            action.moved = true;
            const right = action.startX + action.startWidth;
            const bottom = action.startY + action.startHeight;
            let x = action.startX;
            let y = action.startY;
            let width = action.startWidth;
            let height = action.startHeight;
            if (action.corner.indexOf('e') >= 0) width = Math.max(MIN_GROUP_WIDTH, action.startWidth + dx);
            if (action.corner.indexOf('s') >= 0) height = Math.max(MIN_GROUP_HEIGHT, action.startHeight + dy);
            if (action.corner.indexOf('w') >= 0) {
                x = Math.min(right - MIN_GROUP_WIDTH, action.startX + dx);
                width = right - x;
            }
            if (action.corner.indexOf('n') >= 0) {
                y = Math.min(bottom - MIN_GROUP_HEIGHT, action.startY + dy);
                height = bottom - y;
            }
            const group = this.groupPositions && this.groupPositions[action.groupId];
            const frame = this.groupLayer.querySelector('[data-group-id="' + action.groupId + '"]');
            if (!group || !frame) return;
            group.position = { x: x, y: y };
            group.size = { width: width, height: height };
            this._positionGroupElement(frame, group);
            frame.classList.add('resizing');
            if (this.cardToolbarManager && this.cardToolbarManager.isOpen()
                && this.cardToolbarGroupId === action.groupId) {
                this.cardToolbarManager.reposition();
            }
            return;
        }
        if (action.mode === 'node') {
            const dx = (event.clientX - action.clientX) / this.transform.scale;
            const dy = (event.clientY - action.clientY) / this.transform.scale;
            if (!action.moved && Math.hypot(dx, dy) < 4) return;
            action.moved = true;
            if (!action.captured) {
                this.viewport.setPointerCapture(event.pointerId);
                action.captured = true;
            }
            const position = this.positions[action.nodeId];
            const wrapper = this.nodeLayer.querySelector('[data-node-id="' + action.nodeId + '"]');
            if (!position || !wrapper) return;
            position.x = action.startX + dx;
            position.y = action.startY + dy;
            this._positionNodeElement(wrapper, position);
            wrapper.classList.add('dragging');
            this._updateEdgeGeometry();
            if (this.cardToolbarManager && this.cardToolbarManager.isOpen()
                && this.cardToolbarNodeId === action.nodeId) {
                this.cardToolbarManager.reposition();
            }
            return;
        }
        if (action.mode === 'wire') {
            const world = this.clientToWorld(event.clientX, event.clientY);
            const target = this._nearestWireTarget(event.clientX, event.clientY, action.fromId);
            this._setWireTarget(target);
            if (this.pendingPath) {
                this.pendingPath.setAttribute('d', bezierPath(
                    action.start,
                    target && target.point ? target.point : world,
                    action.startOrientation,
                    target && target.portOrientation,
                    action.startOrder,
                    target && target.portOrder
                ));
            }
        }
    };

    ProcessMapEditor.prototype.pointerUp = function (event) {
        const action = this.interaction;
        if (!action || event.pointerId !== action.pointerId) return;
        try { this.viewport.releasePointerCapture(event.pointerId); } catch (_) {}
        this.interaction = null;
        this.viewport.classList.remove('panning');
        if (action.mode === 'group') {
            const frame = this.groupLayer.querySelector('[data-group-id="' + action.groupId + '"]');
            if (frame) frame.classList.remove('dragging');
            if (action.moved && event.type !== 'pointercancel') {
                const group = this.groupPositions && this.groupPositions[action.groupId];
                this._suppressGroupClick = true;
                setTimeout(function () { this._suppressGroupClick = false; }.bind(this), 0);
                if (group) this.commitMutation(moveGroup(
                    this.processMap,
                    action.groupId,
                    group.position,
                    action.withMembers
                ));
            } else if (event.type === 'pointercancel') {
                this.renderGraph({ fit: false });
            }
            return;
        }
        if (action.mode === 'group-resize') {
            const frame = this.groupLayer.querySelector('[data-group-id="' + action.groupId + '"]');
            if (frame) frame.classList.remove('resizing');
            if (action.moved && event.type !== 'pointercancel') {
                const group = this.groupPositions && this.groupPositions[action.groupId];
                if (group) this.commitMutation(resizeGroup(this.processMap, action.groupId, {
                    position: group.position,
                    size: group.size,
                }));
            } else if (event.type === 'pointercancel') {
                this.renderGraph({ fit: false });
            }
            return;
        }
        if (action.mode === 'node') {
            const wrapper = this.nodeLayer.querySelector('[data-node-id="' + action.nodeId + '"]');
            if (wrapper) wrapper.classList.remove('dragging');
            if (action.moved && event.type !== 'pointercancel') {
                const position = this.positions[action.nodeId];
                this._suppressClick = true;
                setTimeout(function () { this._suppressClick = false; }.bind(this), 0);
                let nextMap = moveNode(this.processMap, action.nodeId, position);
                const center = position.isJunction
                    ? { x: position.x, y: position.y }
                    : {
                        x: position.x + position.width / 2,
                        y: position.y + position.height / 2,
                    };
                nextMap = resolveNodeGroupMembership(nextMap, action.nodeId, center);
                this.commitMutation(nextMap);
            } else if (event.type === 'pointercancel') {
                this.renderGraph({ fit: false });
            }
            return;
        }
        if (action.mode === 'wire') {
            const target = event.type === 'pointercancel'
                ? null
                : (action.snapTarget || this._nearestWireTarget(
                    event.clientX,
                    event.clientY,
                    action.fromId
                ));
            this._clearWireTarget(action);
            if (this.pendingPath) this.pendingPath.remove();
            this.pendingPath = null;
            if (!target) return;
            if (target.kind === 'edge') {
                const stamp = Date.now().toString(36);
                const junctionId = 'pm-j-' + stamp + '-' + (++this.nodeCounter);
                const firstEdgeId = 'pm-e-' + stamp + '-' + (++this.edgeCounter);
                const secondEdgeId = 'pm-e-' + stamp + '-' + (++this.edgeCounter);
                const branchEdgeId = 'pm-e-' + stamp + '-' + (++this.edgeCounter);
                let next = splitEdgeWithJunction(this.processMap, {
                    sourceNodeId: action.fromId,
                    targetEdgeId: target.edgeId,
                    position: target.point,
                    junctionNodeId: junctionId,
                    firstEdgeId: firstEdgeId,
                    secondEdgeId: secondEdgeId,
                    branchEdgeId: branchEdgeId,
                    kind: 'precedence',
                });
                next = resolveNodeGroupMembership(next, junctionId, target.point);
                if (this.commitMutation(next)) this.select(junctionId);
                else {
                    this.operationError = 'That branch would create an invalid process connection.';
                    this.updateEditControls();
                }
                return;
            }
            const toId = target.nodeId;
            if (!toId || toId === action.fromId) return;
            const edgeId = 'pm-e-' + Date.now().toString(36) + '-' + (++this.edgeCounter);
            if (!this.commitMutation(addEdge(this.processMap, {
                edgeId: edgeId,
                from: { nodeId: action.fromId, port: 'out' },
                to: { nodeId: toId, port: 'in' },
                kind: 'precedence',
            }))) {
                this.operationError = 'That process connection already exists or is not valid.';
                this.updateEditControls();
            }
        }
    };

    ProcessMapEditor.prototype.keyDown = function (event) {
        if (!this.editable) return;
        if (event.key === 'Escape' && this._closeCardToolbar('escape', true)) {
            event.preventDefault();
            return;
        }
        const targetName = String(event.target && event.target.tagName || '').toLowerCase();
        if (['input', 'select', 'textarea'].indexOf(targetName) >= 0) return;
        const modifier = event.ctrlKey || event.metaKey;
        if (modifier && event.key.toLowerCase() === 'z') {
            event.preventDefault();
            if (event.shiftKey) this.redo();
            else this.undo();
            return;
        }
        if (modifier && event.key.toLowerCase() === 'y') {
            event.preventDefault();
            this.redo();
            return;
        }
        if (event.key === 'Delete' || event.key === 'Backspace') {
            event.preventDefault();
            this.deleteSelection();
        }
    };

    ProcessMapEditor.prototype.destroy = function () {
        this.destroyed = true;
        this._clearSuggestions();
        this.suggestionPanelOpen = false;
        if (this.cardToolbarManager) {
            this.cardToolbarManager.destroy();
            this.cardToolbarManager = null;
            this.cardToolbarElement = null;
            this.cardToolbarNodeId = null;
            this.cardToolbarEdgeId = null;
            this.cardToolbarGroupId = null;
        }
        if (!this.viewport) return;
        this.viewport.removeEventListener('pointerdown', this._onPointerDown);
        this.viewport.removeEventListener('pointermove', this._onPointerMove);
        this.viewport.removeEventListener('pointerup', this._onPointerUp);
        this.viewport.removeEventListener('pointercancel', this._onPointerUp);
        this.viewport.removeEventListener('wheel', this._onWheel);
        this.viewport.removeEventListener('dragover', this._onDragOver);
        this.viewport.removeEventListener('dragleave', this._onDragLeave);
        this.viewport.removeEventListener('drop', this._onDrop);
        if (this.root) this.root.removeEventListener('keydown', this._onKeyDown);
        if (this.pendingPath) this.pendingPath.remove();
        this._clearWireTarget(this.interaction);
        this.interaction = null;
        if (this.host && this.host.__processMapEditor === this) {
            this.host.__processMapEditor = null;
        }
    };

    function mount(host, options) {
        if (!host || typeof document === 'undefined') return null;
        if (host.__processMapEditor && typeof host.__processMapEditor.destroy === 'function') {
            host.__processMapEditor.destroy();
        }
        const editor = new ProcessMapEditor(host, options || {});
        host.__processMapEditor = editor;
        return editor;
    }

    return {
        NODE_TYPES: NODE_TYPES,
        PROCESS_STEP_TYPES: PROCESS_STEP_TYPES,
        PORT_ORIENTATIONS: PORT_ORIENTATIONS,
        PORT_ORDERS: PORT_ORDERS,
        NODE_WIDTH: NODE_WIDTH,
        NODE_HEIGHT: NODE_HEIGHT,
        JUNCTION_HIT_SIZE: JUNCTION_HIT_SIZE,
        WIRE_SNAP_THRESHOLD_PX: WIRE_SNAP_THRESHOLD_PX,
        MAX_NODE_LABEL_LENGTH: MAX_NODE_LABEL_LENGTH,
        MAX_NODE_NOTE_LENGTH: MAX_NODE_NOTE_LENGTH,
        MAX_REFERENCE_CATALOG_ITEMS: MAX_REFERENCE_CATALOG_ITEMS,
        MAX_REFERENCES_PER_TARGET: MAX_REFERENCES_PER_TARGET,
        MAX_DISMISSED_SUGGESTIONS: MAX_DISMISSED_SUGGESTIONS,
        REFERENCE_KINDS: REFERENCE_KINDS,
        PROCESS_MAP_LAYOUT_VERSION: PROCESS_MAP_LAYOUT_VERSION,
        GROUP_COLOR_KEYS: GROUP_COLOR_KEYS,
        MIN_GROUP_WIDTH: MIN_GROUP_WIDTH,
        MIN_GROUP_HEIGHT: MIN_GROUP_HEIGHT,
        SnapshotHistory: SnapshotHistory,
        addEdge: addEdge,
        acceptSuggestions: acceptSuggestions,
        addCanvasNode: addCanvasNode,
        addGroup: addGroup,
        addConnectedProcessStep: addConnectedProcessStep,
        bezierPath: bezierPath,
        cloneMap: cloneMap,
        collapseRedundantJunctions: collapseRedundantJunctions,
        deleteEdge: deleteEdge,
        deleteNode: deleteNode,
        deleteGroup: deleteGroup,
        graphBounds: graphBounds,
        hasPrecedenceCycle: hasPrecedenceCycle,
        isJunctionNode: isJunctionNode,
        layeredLayout: layeredLayout,
        mapFingerprint: mapFingerprint,
        mapEdges: mapEdges,
        mapDismissedSuggestions: mapDismissedSuggestions,
        mapGroups: mapGroups,
        mapNodes: mapNodes,
        mapReferenceCatalog: mapReferenceCatalog,
        pruneUnusedProcessReferences: pruneUnusedProcessReferences,
        mount: mount,
        moveNode: moveNode,
        moveGroup: moveGroup,
        normalizeMapCatalog: normalizeMapCatalog,
        connectedStepPosition: connectedStepPosition,
        portAnchor: portAnchor,
        portDirection: portDirection,
        nodePortOrientation: nodePortOrientation,
        nodePortOrder: nodePortOrder,
        selectedNodeCommandStates: selectedNodeCommandStates,
        retypeNode: retypeNode,
        setNodePortOrientation: setNodePortOrientation,
        setNodePortOrder: setNodePortOrder,
        setNodeLabel: setNodeLabel,
        setNodeNote: setNodeNote,
        resizeGroup: resizeGroup,
        renameGroup: renameGroup,
        recolorGroup: recolorGroup,
        setGroupMembers: setGroupMembers,
        resolveNodeGroupMembership: resolveNodeGroupMembership,
        groupContainsPoint: groupContainsPoint,
        smallestContainingGroup: smallestContainingGroup,
        setEdgeLabel: setEdgeLabel,
        logicalEdgeLabel: logicalEdgeLabel,
        normalizeProcessReference: normalizeProcessReference,
        referenceItemsForTarget: referenceItemsForTarget,
        attachProcessReference: attachProcessReference,
        detachProcessReference: detachProcessReference,
        dismissSuggestion: dismissSuggestion,
        referenceSummary: referenceSummary,
        scopedNodes: scopedNodes,
        splitEdgeWithJunction: splitEdgeWithJunction,
        visibleEdges: visibleEdges,
    };
});
