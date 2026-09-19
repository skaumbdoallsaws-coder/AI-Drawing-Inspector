(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProProcessMap = api;
})(typeof window !== 'undefined' ? window : null, function () {
    'use strict';

    const NODE_WIDTH = 270;
    const NODE_HEIGHT = 146;
    const COLUMN_GAP = 130;
    const ROW_GAP = 44;
    const WORLD_PADDING = 80;
    const MIN_SCALE = 0.1;
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
    const PROCESS_MAP_LAYOUT_VERSION = 3;
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
    const SPATIAL_TELEMETRY_METRIC_KEYS = [
        'hardViolationCount',
        'nodeOverlaps',
        'nodeClearanceViolations',
        'nodeGroupHeaderIntersections',
        'edgeNodeIntersections',
        'edgeGroupHeaderIntersections',
        'edgeCrossings',
        'backwardEdges',
        'routeBends',
        'routeLength',
        'alignmentDeviation',
    ];
    const DEFAULT_PANE_WIDTH = 300;
    const MIN_PANE_WIDTH = 220;
    const MAX_PANE_WIDTH = 480;
    const MIN_VIEWPORT_WIDTH = 320;
    const PANE_RESIZE_STEP = 12;
    const MARQUEE_DRAG_THRESHOLD_PX = 4;
    const MAX_TREE_MULTI_DRAG_ITEMS = 200;
    const BATCH_CARD_GAP_X = 34;
    const BATCH_CARD_GAP_Y = 34;
    const BATCH_CARD_CLEARANCE = 24;
    const BATCH_PLACEMENT_SEARCH_RINGS = 24;
    const REFERENCE_KINDS = ['machine', 'tool', 'requirement', 'standard'];
    const PORT_ORIENTATIONS = ['horizontal', 'vertical'];
    const PORT_ORDERS = ['input_first', 'output_first'];
    const EDGE_DRAW_MODES = ['bezier_legacy', 'orthogonal_auto', 'polyline_manual'];
    const AGENT_FOCUS_DIRECTIONS = ['target', 'upstream', 'downstream', 'both'];
    const MAX_MANUAL_ROUTE_WAYPOINTS = 128;
    const PROCESS_STEP_TYPES = [
        'operation',
        'inspection',
        'decision',
        'input',
        'output',
    ];
    const JUNCTION_TYPES = ['wire_branch', 'parallel_and', 'merge', 'split'];
    const JUNCTION_INSERT_TYPES = ['operation_stage', 'parallel_and', 'merge', 'split'];
    const JUNCTION_DEFINITIONS = {
        operation_stage: {
            label: 'Operation / Stage',
            description: 'Manufacturing or assembly step with multiple inputs and one output',
            iconKey: 'processStageOperation',
        },
        parallel_and: {
            label: 'Parallel / AND',
            description: 'All incoming branches must be complete before the flow continues',
            iconKey: 'processJunctionParallel',
        },
        merge: {
            label: 'Merge',
            description: 'Merge multiple process paths without adding an operation',
            iconKey: 'processJunctionMerge',
        },
        split: {
            label: 'Split',
            description: 'Branch one process path into multiple outgoing paths',
            iconKey: 'processJunctionSplit',
        },
    };
    const PROCESS_STEP_PROPERTY_FIELDS = [
        { key: 'description', label: 'Description', maximum: 2000, multiline: true },
        { key: 'duration', label: 'Duration', maximum: 80, placeholder: 'For example, 12 min' },
        { key: 'fastenersConsumables', label: 'Fasteners / consumables', maximum: 1000, multiline: true },
        { key: 'torqueRequirements', label: 'Torque / requirements', maximum: 1000, multiline: true },
        { key: 'inspectionRequirements', label: 'Inspection requirements', maximum: 1000, multiline: true },
        { key: 'constraints', label: 'Constraints', maximum: 1000, multiline: true },
    ];
    const NODE_TYPES = ['assembly', 'subassembly'].concat(PROCESS_STEP_TYPES);
    let instanceCounter = 0;
    let floatingToolbarWarningShown = false;

    function processMapSpatialRuntime() {
        return typeof window !== 'undefined' && window.InspectorProProcessMapSpatial
            ? window.InspectorProProcessMapSpatial
            : null;
    }

    function cloneMap(processMap) {
        return JSON.parse(JSON.stringify(processMap || { nodes: [], edges: [] }));
    }

    function normalizedRect(firstX, firstY, secondX, secondY) {
        return {
            left: Math.min(firstX, secondX),
            top: Math.min(firstY, secondY),
            right: Math.max(firstX, secondX),
            bottom: Math.max(firstY, secondY),
        };
    }

    function rectsIntersect(first, second) {
        return !!first && !!second
            && first.left <= second.right
            && first.right >= second.left
            && first.top <= second.bottom
            && first.bottom >= second.top;
    }

    function pointInRect(point, rect) {
        return !!point && !!rect
            && point.x >= rect.left && point.x <= rect.right
            && point.y >= rect.top && point.y <= rect.bottom;
    }

    function _pointOnSegment(point, start, end) {
        return point.x >= Math.min(start.x, end.x) && point.x <= Math.max(start.x, end.x)
            && point.y >= Math.min(start.y, end.y) && point.y <= Math.max(start.y, end.y);
    }

    function _segmentOrientation(first, second, third) {
        const value = (second.y - first.y) * (third.x - second.x)
            - (second.x - first.x) * (third.y - second.y);
        if (Math.abs(value) < 0.000001) return 0;
        return value > 0 ? 1 : 2;
    }

    function _segmentsIntersect(firstStart, firstEnd, secondStart, secondEnd) {
        const firstOrientation = _segmentOrientation(firstStart, firstEnd, secondStart);
        const secondOrientation = _segmentOrientation(firstStart, firstEnd, secondEnd);
        const thirdOrientation = _segmentOrientation(secondStart, secondEnd, firstStart);
        const fourthOrientation = _segmentOrientation(secondStart, secondEnd, firstEnd);
        if (firstOrientation !== secondOrientation && thirdOrientation !== fourthOrientation) {
            return true;
        }
        return (firstOrientation === 0 && _pointOnSegment(secondStart, firstStart, firstEnd))
            || (secondOrientation === 0 && _pointOnSegment(secondEnd, firstStart, firstEnd))
            || (thirdOrientation === 0 && _pointOnSegment(firstStart, secondStart, secondEnd))
            || (fourthOrientation === 0 && _pointOnSegment(firstEnd, secondStart, secondEnd));
    }

    function segmentIntersectsRect(start, end, rect) {
        if (!start || !end || !rect) return false;
        if (pointInRect(start, rect) || pointInRect(end, rect)) return true;
        const topLeft = { x: rect.left, y: rect.top };
        const topRight = { x: rect.right, y: rect.top };
        const bottomRight = { x: rect.right, y: rect.bottom };
        const bottomLeft = { x: rect.left, y: rect.bottom };
        return _segmentsIntersect(start, end, topLeft, topRight)
            || _segmentsIntersect(start, end, topRight, bottomRight)
            || _segmentsIntersect(start, end, bottomRight, bottomLeft)
            || _segmentsIntersect(start, end, bottomLeft, topLeft);
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

    function hasProcessMapCanvasContent(processMap) {
        return mapNodes(processMap).length > 0
            || mapEdges(processMap).length > 0
            || mapGroups(processMap).length > 0
            || mapReferenceCatalog(processMap).length > 0
            || mapDismissedSuggestions(processMap).length > 0;
    }

    function clearProcessMapCanvas(processMap) {
        const next = cloneMap(processMap);
        setMapNodes(next, []);
        setMapEdges(next, []);
        setMapGroups(next, []);
        delete next.referenceCatalog;
        delete next.dismissedSuggestions;
        delete next.processPlanImports;
        return next;
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
        const positionLocked = nodePositionLocked(selected);
        const typeOptions = placementMap ? PROCESS_STEP_TYPES : NODE_TYPES;
        const selectedType = placementMap
            ? (selected && selected.nodeKind === 'process_step' ? selected.processType : '')
            : (selected && selected.type);
        return {
            node: selected,
            isJunction: junction,
            locked: locked,
            positionLocked: positionLocked,
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
            canEditProperties: !!selected && selected.nodeKind === 'process_step' && !locked,
            canPreview: !!selected && !junction
                && (
                    selected.nodeKind === 'product_occurrence'
                    || selected.nodeKind === 'process_step'
                )
                && !!state.hasPreview && !locked,
            canLockPosition: !!selected && !junction && !locked && !positionLocked,
            canUnlockPosition: !!selected && !junction && !locked && positionLocked,
            canSuggestPosition: !!selected && !junction && !locked && !positionLocked
                && !!state.spatialPlacementEnabled,
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

    function mergeManagedProposalPreview(processMap, preview) {
        const next = cloneMap(processMap);
        const source = preview && typeof preview === 'object' ? preview : {};
        function merge(previewCollection, mapCollection, key, setter) {
            const records = Array.isArray(source[previewCollection]) ? source[previewCollection] : [];
            if (!records.length) return;
            const merged = new Map((next[mapCollection] || []).filter(Boolean).map(function (item) {
                return [String(item[key] || ''), cloneMap(item)];
            }));
            records.forEach(function (item) {
                if (!item || !item[key]) return;
                merged.set(String(item[key]), cloneMap(item));
            });
            setter(next, Array.from(merged.values()));
        }
        merge('nodes', 'canvasNodes', 'nodeId', setMapNodes);
        merge('edges', 'canvasEdges', 'edgeId', setMapEdges);
        merge('groups', 'canvasGroups', 'groupId', setMapGroups);
        return next;
    }

    function unionGraphBounds(first, second) {
        const left = Math.min(first.x, second.x);
        const top = Math.min(first.y, second.y);
        const right = Math.max(first.x + first.width, second.x + second.width);
        const bottom = Math.max(first.y + first.height, second.y + second.height);
        return {
            x: left,
            y: top,
            width: right - left,
            height: bottom - top,
        };
    }

    function managedProposalGeometry(processMap, preview, occurrenceById) {
        const previewMap = mergeManagedProposalPreview(processMap, preview);
        const nodes = mapNodes(previewMap).map(function (node) {
            return resolveCanvasNode(node, occurrenceById);
        });
        const edges = mapEdges(previewMap);
        const positions = layeredLayout(nodes, edges);
        const inputPortLayout = processStepInputPortLayout(nodes, edges, positions);
        const edgeGeometries = {};
        edges.forEach(function (edge) {
            const geometry = edgeGeometry(edge, positions, {
                routingEnabled: true,
                inputPortSlots: inputPortLayout.byEdge,
            });
            if (geometry) edgeGeometries[edge.edgeId] = geometry;
        });
        return {
            map: previewMap,
            nodes: nodes,
            edges: edges,
            positions: positions,
            inputPortLayout: inputPortLayout,
            edgeGeometries: edgeGeometries,
            bounds: graphBounds(
                positions,
                mapGroups(previewMap),
                edgeGeometries
            ),
        };
    }

    function managedProposalRevealSequence(preview) {
        const source = preview && typeof preview === 'object' ? preview : {};
        const nodeById = new Map();
        (Array.isArray(source.nodes) ? source.nodes : []).forEach(function (node) {
            const nodeId = String(node && node.nodeId || '');
            if (nodeId && !nodeById.has(nodeId)) nodeById.set(nodeId, node);
        });
        const edgeById = new Map();
        (Array.isArray(source.edges) ? source.edges : []).forEach(function (edge) {
            const edgeId = String(edge && edge.edgeId || '');
            if (edgeId && !edgeById.has(edgeId)) edgeById.set(edgeId, edge);
        });
        const nodeIds = Array.from(nodeById.keys());
        const edgeIds = Array.from(edgeById.keys());
        const lexicalOrder = function (left, right) {
            return left < right ? -1 : (left > right ? 1 : 0);
        };
        const nodeOrder = function (leftId, rightId) {
            const left = nodeById.get(leftId) || {};
            const right = nodeById.get(rightId) || {};
            const leftPosition = left.position || {};
            const rightPosition = right.position || {};
            const leftY = finiteNumber(Number(leftPosition.y))
                ? Number(leftPosition.y) : 0;
            const rightY = finiteNumber(Number(rightPosition.y))
                ? Number(rightPosition.y) : 0;
            if (leftY !== rightY) return leftY - rightY;
            const leftX = finiteNumber(Number(leftPosition.x))
                ? Number(leftPosition.x) : 0;
            const rightX = finiteNumber(Number(rightPosition.x))
                ? Number(rightPosition.x) : 0;
            if (leftX !== rightX) return leftX - rightX;
            return lexicalOrder(leftId, rightId);
        };
        const edgeOrder = function (leftId, rightId) {
            const left = edgeById.get(leftId) || {};
            const right = edgeById.get(rightId) || {};
            const leftFrom = String(left.from && left.from.nodeId || '');
            const rightFrom = String(right.from && right.from.nodeId || '');
            const sourceOrder = nodeOrder(leftFrom, rightFrom);
            if (sourceOrder) return sourceOrder;
            const leftTo = String(left.to && left.to.nodeId || '');
            const rightTo = String(right.to && right.to.nodeId || '');
            const targetOrder = nodeOrder(leftTo, rightTo);
            return targetOrder || lexicalOrder(leftId, rightId);
        };
        const indegree = new Map(nodeIds.map(function (nodeId) {
            return [nodeId, 0];
        }));
        const outgoing = new Map(nodeIds.map(function (nodeId) {
            return [nodeId, []];
        }));
        edgeById.forEach(function (edge) {
            const fromId = String(edge && edge.from && edge.from.nodeId || '');
            const toId = String(edge && edge.to && edge.to.nodeId || '');
            if (!nodeById.has(fromId) || !nodeById.has(toId) || fromId === toId) return;
            outgoing.get(fromId).push(toId);
            indegree.set(toId, indegree.get(toId) + 1);
        });
        outgoing.forEach(function (targets) {
            targets.sort(nodeOrder);
        });

        const sequence = [];
        const revealedNodeIds = new Set();
        const revealedEdgeIds = new Set();
        const revealReadyEdges = function () {
            const readyEdgeIds = edgeIds.filter(function (edgeId) {
                if (revealedEdgeIds.has(edgeId)) return false;
                const edge = edgeById.get(edgeId) || {};
                const fromId = String(edge.from && edge.from.nodeId || '');
                const toId = String(edge.to && edge.to.nodeId || '');
                const fromReady = !nodeById.has(fromId) || revealedNodeIds.has(fromId);
                const toReady = !nodeById.has(toId) || revealedNodeIds.has(toId);
                return fromReady && toReady;
            }).sort(edgeOrder);
            if (!readyEdgeIds.length) return;
            readyEdgeIds.forEach(function (edgeId) {
                revealedEdgeIds.add(edgeId);
            });
            sequence.push({ kind: 'edges', ids: readyEdgeIds });
        };
        let frontier = nodeIds.filter(function (nodeId) {
            return indegree.get(nodeId) === 0;
        }).sort(nodeOrder);
        while (frontier.length) {
            const nextFrontier = [];
            frontier.forEach(function (nodeId) {
                if (revealedNodeIds.has(nodeId)) return;
                revealedNodeIds.add(nodeId);
                sequence.push({ kind: 'node', ids: [nodeId] });
                revealReadyEdges();
                outgoing.get(nodeId).forEach(function (targetId) {
                    indegree.set(targetId, indegree.get(targetId) - 1);
                    if (indegree.get(targetId) === 0) nextFrontier.push(targetId);
                });
            });
            frontier = nextFrontier.sort(nodeOrder);
        }
        nodeIds.filter(function (nodeId) {
            return !revealedNodeIds.has(nodeId);
        }).sort(nodeOrder).forEach(function (nodeId) {
            revealedNodeIds.add(nodeId);
            sequence.push({ kind: 'node', ids: [nodeId] });
            revealReadyEdges();
        });
        revealReadyEdges();
        const remainingEdgeIds = edgeIds.filter(function (edgeId) {
            return !revealedEdgeIds.has(edgeId);
        }).sort(edgeOrder);
        if (remainingEdgeIds.length) {
            sequence.push({ kind: 'edges', ids: remainingEdgeIds });
        }
        return sequence;
    }

    function edgeFromSpatialProposal(suggestion) {
        const proposal = suggestion && suggestion.spatialProposal;
        if (!proposal || proposal.accepted !== true
            || proposal.semanticSuggestionId !== suggestion.suggestionId
            || proposal.semanticEvidenceFingerprint !== suggestion.evidenceFingerprint
            || !proposal.edge || !proposal.route) return null;
        const edge = cloneMap(proposal.edge);
        edge.routing = {
            mode: 'orthogonal_auto',
            routerVersion: Number(proposal.routerVersion) || 1,
            waypoints: cloneMap(proposal.route.waypoints || []),
            obstacleFingerprint: proposal.obstacleFingerprint,
        };
        return edge;
    }

    function acceptSpatialSuggestions(processMap, suggestions) {
        let next = cloneMap(processMap);
        const accepted = [];
        const skipped = [];
        (Array.isArray(suggestions) ? suggestions : []).forEach(function (suggestion) {
            const suggestionId = String(suggestion && suggestion.suggestionId || '');
            const edge = edgeFromSpatialProposal(suggestion);
            if (!edge) {
                skipped.push({ suggestionId: suggestionId, reason: 'missing_spatial_proposal' });
                return;
            }
            let candidateMap = cloneMap(next);
            const placement = suggestion.spatialProposal.placement;
            if (placement && placement.node) {
                const beforeNode = mapFingerprint(candidateMap);
                candidateMap = addCanvasNode(candidateMap, placement.node);
                if (mapFingerprint(candidateMap) === beforeNode) {
                    skipped.push({ suggestionId: suggestionId, reason: 'placement_rejected' });
                    return;
                }
            }
            const candidateNodeIds = new Set(mapNodes(candidateMap).map(function (node) {
                return node && node.nodeId;
            }));
            const fromId = edge.from && edge.from.nodeId;
            const toId = edge.to && edge.to.nodeId;
            if (!candidateNodeIds.has(fromId) || !candidateNodeIds.has(toId)) {
                skipped.push({ suggestionId: suggestionId, reason: 'dangling_endpoint' });
                return;
            }
            const candidate = addEdge(candidateMap, edge);
            if (mapFingerprint(candidate) === mapFingerprint(candidateMap)) {
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

    function acceptPlacementCandidate(processMap, plan) {
        // plan.nodeId is always caller-supplied (fresh, collision-checked id
        // for a new card, or the existing id for a repositioned one), the
        // same convention addOccurrenceAt/addProcessStep already use for id
        // generation -- this stays a pure function with no Date.now()/random.
        if (!plan || !plan.nodeId || !_finitePlacementPosition(plan.position)) {
            return { map: cloneMap(processMap), nodeId: null, accepted: false, reason: 'invalid_plan' };
        }
        let next = cloneMap(processMap);
        if (plan.isNew) {
            const placement = {
                nodeId: plan.nodeId,
                nodeKind: plan.nodeKind,
                position: { x: plan.position.x, y: plan.position.y },
                positionMode: 'auto',
            };
            if (plan.nodeKind === 'product_occurrence') {
                placement.sourceOccurrenceId = plan.sourceOccurrenceId;
                placement.nameSnapshot = plan.nameSnapshot;
                placement.itemIdSnapshot = plan.itemIdSnapshot || null;
            } else if (plan.nodeKind === 'process_step') {
                placement.processType = plan.processType;
                placement.name = plan.name;
                placement.description = '';
            } else {
                return { map: cloneMap(processMap), nodeId: null, accepted: false, reason: 'invalid_plan' };
            }
            const before = next;
            next = addCanvasNode(next, placement);
            if (mapFingerprint(next) === mapFingerprint(before)) {
                return { map: cloneMap(processMap), nodeId: null, accepted: false, reason: 'placement_rejected' };
            }
        } else {
            const existing = mapNodes(next).find(function (item) {
                return item && item.nodeId === plan.nodeId;
            });
            if (!existing || isJunctionNode(existing) || nodePositionLocked(existing)) {
                return { map: cloneMap(processMap), nodeId: null, accepted: false, reason: 'target_unavailable' };
            }
            next = moveNode(next, plan.nodeId, plan.position);
            const moved = mapNodes(next).find(function (item) {
                return item && item.nodeId === plan.nodeId;
            });
            if (moved) moved.positionMode = 'auto';
        }
        if (PORT_ORIENTATIONS.indexOf(plan.portOrientation) >= 0) {
            next = setNodePortOrientation(next, plan.nodeId, plan.portOrientation);
        }
        if (PORT_ORDERS.indexOf(plan.portOrder) >= 0) {
            next = setNodePortOrder(next, plan.nodeId, plan.portOrder);
        }
        next = resolveNodeGroupMembership(next, plan.nodeId, {
            x: plan.position.x + (plan.envelopeWidth || NODE_WIDTH) / 2,
            y: plan.position.y + (plan.envelopeHeight || NODE_HEIGHT) / 2,
        });
        if (plan.connection && plan.connection.anchorNodeId) {
            const outgoing = plan.connection.direction !== 'incoming';
            const fromId = outgoing ? plan.connection.anchorNodeId : plan.nodeId;
            const toId = outgoing ? plan.nodeId : plan.connection.anchorNodeId;
            const kind = plan.connection.kind || 'precedence';
            const before = next;
            next = addEdge(next, {
                edgeId: plan.connection.edgeId || ('pm-e-' + plan.nodeId + '-' + plan.connection.anchorNodeId),
                from: { nodeId: fromId, port: 'out' },
                to: { nodeId: toId, port: 'in' },
                kind: kind,
            });
            const connectionApplied = mapFingerprint(next) !== mapFingerprint(before);
            const cycleIntroduced = kind === 'precedence' && hasPrecedenceCycle(next);
            if (!connectionApplied || cycleIntroduced) {
                return { map: cloneMap(processMap), nodeId: null, accepted: false, reason: 'connection_rejected' };
            }
        }
        return { map: next, nodeId: plan.nodeId, accepted: true, reason: '' };
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
                if (!isJunctionNode(node) || node.junctionType !== 'wire_branch'
                    || _junctionHasUserMetadata(node)) return false;
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

    function clearEdgeRouting(processMap, edgeId) {
        const next = cloneMap(processMap);
        const edge = mapEdges(next).find(function (item) {
            return item && item.edgeId === edgeId;
        });
        if (!edge || !edge.routing) return next;
        delete edge.routing;
        return next;
    }

    function normalizeManualRouteWaypoints(waypoints) {
        return (Array.isArray(waypoints) ? waypoints : []).filter(function (point) {
            return point && finiteNumber(point.x) && finiteNumber(point.y);
        }).slice(0, MAX_MANUAL_ROUTE_WAYPOINTS).map(function (point) {
            return { x: Number(point.x), y: Number(point.y) };
        });
    }

    function setManualEdgeWaypoints(processMap, edgeId, waypoints) {
        const next = cloneMap(processMap);
        const edge = mapEdges(next).find(function (item) {
            return item && item.edgeId === edgeId;
        });
        if (!edge) return next;
        edge.routing = {
            mode: 'polyline_manual',
            routerVersion: 1,
            waypoints: normalizeManualRouteWaypoints(waypoints),
        };
        next.layoutVersion = Math.max(3, Number(next.layoutVersion) || 1);
        return next;
    }

    function addManualEdgeWaypoint(processMap, edgeId, insertionIndex, point) {
        const edge = mapEdges(processMap).find(function (item) {
            return item && item.edgeId === edgeId;
        });
        if (!edge || !point || !finiteNumber(point.x) || !finiteNumber(point.y)) {
            return cloneMap(processMap);
        }
        const waypoints = normalizeManualRouteWaypoints(
            edge.routing && edge.routing.mode === 'polyline_manual'
                ? edge.routing.waypoints : []
        );
        if (waypoints.length >= MAX_MANUAL_ROUTE_WAYPOINTS) return cloneMap(processMap);
        const index = clamp(
            Number.isInteger(insertionIndex) ? insertionIndex : waypoints.length,
            0,
            waypoints.length
        );
        waypoints.splice(index, 0, { x: Number(point.x), y: Number(point.y) });
        return setManualEdgeWaypoints(processMap, edgeId, waypoints);
    }

    function removeManualEdgeWaypoint(processMap, edgeId, waypointIndex) {
        const edge = mapEdges(processMap).find(function (item) {
            return item && item.edgeId === edgeId;
        });
        const waypoints = normalizeManualRouteWaypoints(
            edge && edge.routing && edge.routing.mode === 'polyline_manual'
                ? edge.routing.waypoints : []
        );
        if (!Number.isInteger(waypointIndex)
            || waypointIndex < 0 || waypointIndex >= waypoints.length) {
            return cloneMap(processMap);
        }
        waypoints.splice(waypointIndex, 1);
        return setManualEdgeWaypoints(processMap, edgeId, waypoints);
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
            positionMode: 'manual',
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

    function addJunctionNode(processMap, request) {
        const next = cloneMap(processMap);
        const options = request || {};
        const junctionType = String(options.junctionType || 'wire_branch');
        const nodeId = String(options.nodeId || '').trim();
        if (!isPlacementMap(next) || JUNCTION_TYPES.indexOf(junctionType) < 0
            || !nodeId || !_finitePlacementPosition(options.position)
            || mapNodes(next).some(function (node) { return node && node.nodeId === nodeId; })) {
            return next;
        }
        setMapNodes(next, mapNodes(next).concat([{
            nodeId: nodeId,
            nodeKind: 'junction',
            junctionType: junctionType,
            position: { x: options.position.x, y: options.position.y },
            positionMode: 'manual',
        }]));
        return next;
    }

    function copyProcessLogicSelection(processMap, nodeIds) {
        const selectedIds = new Set(Array.isArray(nodeIds) ? nodeIds.filter(Boolean) : []);
        const nodes = mapNodes(processMap).filter(function (node) {
            return node && selectedIds.has(node.nodeId)
                && (node.nodeKind === 'process_step' || node.nodeKind === 'junction');
        });
        const copiedIds = new Set(nodes.map(function (node) { return node.nodeId; }));
        const edges = mapEdges(processMap).filter(function (edge) {
            return edge && edge.from && edge.to
                && copiedIds.has(edge.from.nodeId)
                && copiedIds.has(edge.to.nodeId);
        });
        const groupIdByNode = {};
        mapGroups(processMap).forEach(function (group) {
            (Array.isArray(group && group.memberNodeIds) ? group.memberNodeIds : [])
                .forEach(function (nodeId) {
                    if (copiedIds.has(nodeId)) groupIdByNode[nodeId] = group.groupId;
                });
        });
        return {
            nodes: cloneMap(nodes),
            edges: cloneMap(edges),
            groupIdByNode: groupIdByNode,
        };
    }

    function pasteProcessLogicSelection(processMap, clipboard, request) {
        const next = cloneMap(processMap);
        const payload = clipboard && typeof clipboard === 'object' ? clipboard : {};
        const options = request && typeof request === 'object' ? request : {};
        const copiedNodes = Array.isArray(payload.nodes) ? payload.nodes : [];
        if (!isPlacementMap(next) || !copiedNodes.length) {
            return { accepted: false, map: next, nodeIds: [], edgeIds: [] };
        }
        const nodeIdMap = options.nodeIdMap && typeof options.nodeIdMap === 'object'
            ? options.nodeIdMap : {};
        const edgeIdMap = options.edgeIdMap && typeof options.edgeIdMap === 'object'
            ? options.edgeIdMap : {};
        const logicalIdMap = options.logicalConnectionIdMap
            && typeof options.logicalConnectionIdMap === 'object'
            ? options.logicalConnectionIdMap : {};
        const offset = options.offset && finiteNumber(options.offset.x) && finiteNumber(options.offset.y)
            ? options.offset : { x: 28, y: 28 };
        const existingNodeIds = new Set(mapNodes(next).map(function (node) {
            return node && node.nodeId;
        }).filter(Boolean));
        const existingEdgeIds = new Set(mapEdges(next).map(function (edge) {
            return edge && edge.edgeId;
        }).filter(Boolean));
        const sourceIds = new Set(copiedNodes.map(function (node) {
            return node && node.nodeId;
        }).filter(Boolean));
        const addedNodes = [];
        for (let index = 0; index < copiedNodes.length; index += 1) {
            const source = copiedNodes[index];
            const nextId = String(nodeIdMap[source.nodeId] || '').trim();
            if (!source || !sourceIds.has(source.nodeId) || !nextId
                || existingNodeIds.has(nextId)
                || (source.nodeKind !== 'process_step' && source.nodeKind !== 'junction')
                || !_finitePlacementPosition(source.position)) {
                return { accepted: false, map: cloneMap(processMap), nodeIds: [], edgeIds: [] };
            }
            existingNodeIds.add(nextId);
            const node = cloneMap(source);
            node.nodeId = nextId;
            node.position = {
                x: source.position.x + offset.x,
                y: source.position.y + offset.y,
            };
            addedNodes.push(node);
        }
        const copiedEdges = Array.isArray(payload.edges) ? payload.edges : [];
        const addedEdges = [];
        for (let edgeIndex = 0; edgeIndex < copiedEdges.length; edgeIndex += 1) {
            const sourceEdge = copiedEdges[edgeIndex];
            const nextEdgeId = String(edgeIdMap[sourceEdge.edgeId] || '').trim();
            const fromId = sourceEdge && sourceEdge.from
                ? nodeIdMap[sourceEdge.from.nodeId] : null;
            const toId = sourceEdge && sourceEdge.to
                ? nodeIdMap[sourceEdge.to.nodeId] : null;
            if (!sourceEdge || !nextEdgeId || existingEdgeIds.has(nextEdgeId)
                || !fromId || !toId) {
                return { accepted: false, map: cloneMap(processMap), nodeIds: [], edgeIds: [] };
            }
            existingEdgeIds.add(nextEdgeId);
            const edge = cloneMap(sourceEdge);
            edge.edgeId = nextEdgeId;
            edge.from.nodeId = fromId;
            edge.to.nodeId = toId;
            const sourceLogicalId = String(sourceEdge.logicalConnectionId || sourceEdge.edgeId || '');
            edge.logicalConnectionId = String(logicalIdMap[sourceLogicalId] || nextEdgeId);
            delete edge.routing;
            addedEdges.push(edge);
        }
        setMapNodes(next, mapNodes(next).concat(addedNodes));
        setMapEdges(next, mapEdges(next).concat(addedEdges));
        const groupIdByNode = payload.groupIdByNode && typeof payload.groupIdByNode === 'object'
            ? payload.groupIdByNode : {};
        const groups = mapGroups(next);
        Object.keys(nodeIdMap).forEach(function (sourceNodeId) {
            const groupId = groupIdByNode[sourceNodeId];
            const targetNodeId = nodeIdMap[sourceNodeId];
            const group = groups.find(function (item) {
                return item && item.groupId === groupId;
            });
            if (!group || !targetNodeId) return;
            const members = Array.isArray(group.memberNodeIds) ? group.memberNodeIds.slice() : [];
            if (members.indexOf(targetNodeId) < 0) members.push(targetNodeId);
            group.memberNodeIds = members;
        });
        setMapGroups(next, groups);
        if (!hasPrecedenceCycle(processMap) && hasPrecedenceCycle(next)) {
            return { accepted: false, map: cloneMap(processMap), nodeIds: [], edgeIds: [] };
        }
        return {
            accepted: true,
            map: next,
            nodeIds: addedNodes.map(function (node) { return node.nodeId; }),
            edgeIds: addedEdges.map(function (edge) { return edge.edgeId; }),
        };
    }

    function duplicateCanvasCard(processMap, sourceNodeId, request) {
        const next = cloneMap(processMap);
        const options = request && typeof request === 'object' ? request : {};
        const source = mapNodes(next).find(function (node) {
            return node && node.nodeId === sourceNodeId;
        });
        const nodeId = String(options.nodeId || '').trim();
        const position = options.position;
        if (!isPlacementMap(next) || !source || isJunctionNode(source) || !nodeId
            || !_finitePlacementPosition(position)
            || mapNodes(next).some(function (node) { return node && node.nodeId === nodeId; })) {
            return { accepted: false, map: next, nodeId: null, reason: 'invalid_duplicate' };
        }

        const duplicate = cloneMap(source);
        duplicate.nodeId = nodeId;
        duplicate.position = { x: position.x, y: position.y };
        duplicate.positionMode = 'manual';
        delete duplicate.locked;

        if (source.nodeKind === 'product_occurrence') {
            const occurrence = options.replacementOccurrence;
            const occurrenceId = String(occurrence && occurrence.occurrenceId || '').trim();
            const sourceItemId = String(options.sourceItemId || source.itemIdSnapshot || '').trim();
            const replacementItemId = String(occurrence && occurrence.itemId || '').trim();
            const alreadyPlaced = mapNodes(next).some(function (node) {
                return node && node.nodeKind === 'product_occurrence'
                    && node.sourceOccurrenceId === occurrenceId;
            });
            if (!occurrenceId || occurrenceId === source.sourceOccurrenceId || alreadyPlaced
                || !sourceItemId || replacementItemId !== sourceItemId) {
                return {
                    accepted: false,
                    map: cloneMap(processMap),
                    nodeId: null,
                    reason: 'no_matching_product_occurrence',
                };
            }
            duplicate.sourceOccurrenceId = occurrenceId;
            duplicate.nameSnapshot = String(
                occurrence.name || source.nameSnapshot || occurrenceId
            );
            duplicate.itemIdSnapshot = replacementItemId;
        } else if (source.nodeKind !== 'process_step') {
            return {
                accepted: false,
                map: cloneMap(processMap),
                nodeId: null,
                reason: 'unsupported_card_kind',
            };
        }

        setMapNodes(next, mapNodes(next).concat([duplicate]));
        const center = options.center && finiteNumber(options.center.x)
            && finiteNumber(options.center.y)
            ? options.center
            : {
                x: position.x + NODE_WIDTH / 2,
                y: position.y + NODE_HEIGHT / 2,
            };
        return {
            accepted: true,
            map: resolveNodeGroupMembership(next, nodeId, center),
            nodeId: nodeId,
            reason: null,
        };
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

    function deleteCanvasSelection(processMap, nodeIds, edgeIds) {
        const selectedNodes = new Set(Array.isArray(nodeIds) ? nodeIds.filter(Boolean) : []);
        const selectedEdges = new Set(Array.isArray(edgeIds) ? edgeIds.filter(Boolean) : []);
        if (!selectedNodes.size && !selectedEdges.size) return cloneMap(processMap);
        const next = cloneMap(processMap);
        setMapNodes(next, mapNodes(next).filter(function (node) {
            return node && !selectedNodes.has(node.nodeId);
        }));
        setMapEdges(next, mapEdges(next).filter(function (edge) {
            return edge && edge.from && edge.to
                && !selectedEdges.has(edge.edgeId)
                && !selectedNodes.has(edge.from.nodeId)
                && !selectedNodes.has(edge.to.nodeId);
        }));
        _removeNodeIdsFromGroups(next, selectedNodes);
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
            node.positionMode = 'manual';
            delete node.locked;
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

    function setProcessStepProperties(processMap, nodeId, value) {
        const next = cloneMap(processMap);
        const node = mapNodes(next).find(function (item) {
            return item && item.nodeId === nodeId;
        });
        if (!node || node.nodeKind !== 'process_step' || !value || typeof value !== 'object') {
            return next;
        }
        const properties = {};
        PROCESS_STEP_PROPERTY_FIELDS.forEach(function (definition) {
            const raw = value[definition.key];
            if (typeof raw !== 'string') return;
            const cleaned = raw.trim();
            if (cleaned && cleaned.length <= definition.maximum) {
                properties[definition.key] = cleaned;
            }
        });
        if (Object.keys(properties).length) node.properties = properties;
        else delete node.properties;
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
        const knowledgeStatus = _trimmedReferenceField(value.knowledgeStatus, 40);
        if (['authored', 'derived', 'inferred', 'unknown', 'illustrative'].indexOf(knowledgeStatus) >= 0) {
            normalized.knowledgeStatus = knowledgeStatus;
        }
        if (typeof value.demoData === 'boolean') normalized.demoData = value.demoData;
        [
            ['sourcePlanId', 160],
            ['sourceRevision', 80],
            ['sourcePlanHash', 128],
            ['sourceRequirementId', 160],
            ['sourceResourceId', 160],
            ['populatedBy', 80],
            ['populatedAt', 64],
        ].forEach(function (definition) {
            const cleaned = _trimmedReferenceField(value[definition[0]], definition[1]);
            if (cleaned) normalized[definition[0]] = cleaned;
        });
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

    function _batchPlacementObstacles(processMap) {
        const obstacles = [];
        mapNodes(processMap).forEach(function (node) {
            if (!node || !_finitePlacementPosition(node.position)) return;
            const junction = isJunctionNode(node);
            obstacles.push({
                x: junction ? node.position.x - JUNCTION_HIT_SIZE / 2 : node.position.x,
                y: junction ? node.position.y - JUNCTION_HIT_SIZE / 2 : node.position.y,
                width: junction ? JUNCTION_HIT_SIZE : NODE_WIDTH,
                height: junction ? JUNCTION_HIT_SIZE : NODE_HEIGHT,
            });
        });
        mapGroups(processMap).forEach(function (group) {
            if (!group || !_validGroupPosition(group.position) || !_finiteGroupSize(group.size)) {
                return;
            }
            obstacles.push({
                x: group.position.x,
                y: group.position.y - GROUP_HEADER_OVERHANG,
                width: group.size.width,
                height: GROUP_HEADER_OVERHANG,
            });
        });
        return obstacles;
    }

    function _normalizedBatchBounds(value) {
        if (!value || !finiteNumber(value.x) || !finiteNumber(value.y)
            || !finiteNumber(value.width) || !finiteNumber(value.height)
            || value.width < NODE_WIDTH || value.height < NODE_HEIGHT) return null;
        return {
            x: value.x,
            y: value.y,
            width: value.width,
            height: value.height,
        };
    }

    function _intersectBatchBounds(first, second) {
        if (!first) return second;
        if (!second) return first;
        const left = Math.max(first.x, second.x);
        const top = Math.max(first.y, second.y);
        const right = Math.min(first.x + first.width, second.x + second.width);
        const bottom = Math.min(first.y + first.height, second.y + second.height);
        return _normalizedBatchBounds({
            x: left,
            y: top,
            width: right - left,
            height: bottom - top,
        });
    }

    function _batchColumnCount(count, bounds) {
        const preferred = Math.ceil(Math.sqrt(count));
        if (!bounds) return preferred;
        const usableWidth = Math.max(0, bounds.width - BATCH_CARD_CLEARANCE * 2);
        const usableHeight = Math.max(0, bounds.height - BATCH_CARD_CLEARANCE * 2);
        const maximumColumns = Math.max(1, Math.min(
            count,
            Math.floor((usableWidth + BATCH_CARD_GAP_X) / (NODE_WIDTH + BATCH_CARD_GAP_X))
        ));
        const fitting = [];
        for (let columns = 1; columns <= maximumColumns; columns += 1) {
            const rows = Math.ceil(count / columns);
            const width = columns * NODE_WIDTH + Math.max(0, columns - 1) * BATCH_CARD_GAP_X;
            const height = rows * NODE_HEIGHT + Math.max(0, rows - 1) * BATCH_CARD_GAP_Y;
            if (width <= usableWidth && height <= usableHeight) fitting.push(columns);
        }
        if (!fitting.length) return maximumColumns;
        return fitting.sort(function (left, right) {
            const leftDistance = Math.abs(left - preferred);
            const rightDistance = Math.abs(right - preferred);
            return leftDistance - rightDistance || right - left;
        })[0];
    }

    function _batchGridPositions(count, center, shiftX, shiftY, columns, bounds) {
        const rows = Math.ceil(count / columns);
        const width = columns * NODE_WIDTH + Math.max(0, columns - 1) * BATCH_CARD_GAP_X;
        const height = rows * NODE_HEIGHT + Math.max(0, rows - 1) * BATCH_CARD_GAP_Y;
        let left = center.x - width / 2 + shiftX;
        let top = center.y - height / 2 + shiftY;
        if (bounds) {
            const minimumLeft = bounds.x + BATCH_CARD_CLEARANCE;
            const maximumLeft = bounds.x + bounds.width - BATCH_CARD_CLEARANCE - width;
            const minimumTop = bounds.y + BATCH_CARD_CLEARANCE;
            const maximumTop = bounds.y + bounds.height - BATCH_CARD_CLEARANCE - height;
            if (maximumLeft >= minimumLeft) {
                left = Math.max(minimumLeft, Math.min(left, maximumLeft));
            }
            if (maximumTop >= minimumTop) {
                top = Math.max(minimumTop, Math.min(top, maximumTop));
            }
        }
        const positions = [];
        for (let index = 0; index < count; index += 1) {
            positions.push({
                x: left + (index % columns) * (NODE_WIDTH + BATCH_CARD_GAP_X),
                y: top + Math.floor(index / columns) * (NODE_HEIGHT + BATCH_CARD_GAP_Y),
            });
        }
        return positions;
    }

    function planOccurrenceBatchPositions(processMap, count, center, layoutOptions) {
        const requested = Math.floor(Number(count));
        if (!isPlacementMap(processMap) || !center || !finiteNumber(center.x)
            || !finiteNumber(center.y) || requested < 1
            || requested > MAX_TREE_MULTI_DRAG_ITEMS) return [];
        const options = layoutOptions || {};
        const visibleBounds = _normalizedBatchBounds(options.visibleWorldRect);
        const containmentBounds = _normalizedBatchBounds(options.containmentRect);
        const intersectedBounds = _intersectBatchBounds(visibleBounds, containmentBounds);
        const layoutBounds = intersectedBounds || containmentBounds || visibleBounds;
        const columns = _batchColumnCount(requested, layoutBounds);
        const rows = Math.ceil(requested / columns);
        const batchWidth = columns * NODE_WIDTH
            + Math.max(0, columns - 1) * BATCH_CARD_GAP_X;
        const batchHeight = rows * NODE_HEIGHT
            + Math.max(0, rows - 1) * BATCH_CARD_GAP_Y;
        const enforceBounds = !!layoutBounds
            && batchWidth + BATCH_CARD_CLEARANCE * 2 <= layoutBounds.width
            && batchHeight + BATCH_CARD_CLEARANCE * 2 <= layoutBounds.height;
        const obstacles = _batchPlacementObstacles(processMap);
        const stepX = NODE_WIDTH + BATCH_CARD_GAP_X;
        const stepY = NODE_HEIGHT + BATCH_CARD_GAP_Y;
        for (let ring = 0; ring <= BATCH_PLACEMENT_SEARCH_RINGS; ring += 1) {
            for (let gridY = -ring; gridY <= ring; gridY += 1) {
                for (let gridX = -ring; gridX <= ring; gridX += 1) {
                    if (ring && Math.max(Math.abs(gridX), Math.abs(gridY)) !== ring) continue;
                    const positions = _batchGridPositions(
                        requested,
                        center,
                        gridX * stepX,
                        gridY * stepY,
                        columns,
                        enforceBounds ? layoutBounds : null
                    );
                    const clear = positions.every(function (position) {
                        const candidateBounds = {
                            x: position.x,
                            y: position.y,
                            width: NODE_WIDTH,
                            height: NODE_HEIGHT,
                        };
                        const inside = !enforceBounds || (
                            position.x >= layoutBounds.x + BATCH_CARD_CLEARANCE
                            && position.y >= layoutBounds.y + BATCH_CARD_CLEARANCE
                            && position.x + NODE_WIDTH
                                <= layoutBounds.x + layoutBounds.width - BATCH_CARD_CLEARANCE
                            && position.y + NODE_HEIGHT
                                <= layoutBounds.y + layoutBounds.height - BATCH_CARD_CLEARANCE
                        );
                        return inside && !obstacles.some(function (obstacle) {
                            return _rectanglesOverlap(
                                candidateBounds,
                                obstacle,
                                BATCH_CARD_CLEARANCE
                            );
                        });
                    });
                    if (clear) return positions;
                }
            }
        }
        return [];
    }

    function addOccurrenceBatch(processMap, request) {
        const next = cloneMap(processMap);
        const options = request || {};
        const result = {
            map: next,
            addedNodeIds: [],
            skippedOccurrenceIds: [],
            targetGroupId: null,
            reason: null,
        };
        if (!isPlacementMap(next) || !options.dropPoint
            || !finiteNumber(options.dropPoint.x) || !finiteNumber(options.dropPoint.y)) {
            result.reason = 'invalid_drop_point';
            return result;
        }
        const entries = Array.isArray(options.entries)
            ? options.entries.slice(0, MAX_TREE_MULTI_DRAG_ITEMS)
            : [];
        const existingSources = new Set(mapNodes(next).filter(function (node) {
            return node && node.nodeKind === 'product_occurrence' && node.sourceOccurrenceId;
        }).map(function (node) { return node.sourceOccurrenceId; }));
        const existingNodeIds = new Set(mapNodes(next).map(function (node) {
            return node && node.nodeId;
        }).filter(Boolean));
        const seenSources = new Set();
        const acceptedEntries = [];
        entries.forEach(function (entry) {
            const sourceOccurrenceId = String(entry && entry.sourceOccurrenceId || '').trim();
            const nodeId = String(entry && entry.nodeId || '').trim();
            if (!sourceOccurrenceId || !nodeId || seenSources.has(sourceOccurrenceId)
                || existingNodeIds.has(nodeId)) return;
            seenSources.add(sourceOccurrenceId);
            if (existingSources.has(sourceOccurrenceId)) {
                result.skippedOccurrenceIds.push(sourceOccurrenceId);
                return;
            }
            acceptedEntries.push({
                nodeId: nodeId,
                sourceOccurrenceId: sourceOccurrenceId,
                nameSnapshot: String(entry.nameSnapshot || sourceOccurrenceId),
                itemIdSnapshot: entry.itemIdSnapshot || null,
            });
        });
        if (!acceptedEntries.length) {
            result.reason = result.skippedOccurrenceIds.length ? 'already_placed' : 'no_valid_entries';
            return result;
        }
        const targetGroup = smallestContainingGroup(next, options.dropPoint);
        const positions = planOccurrenceBatchPositions(
            next,
            acceptedEntries.length,
            options.dropPoint,
            {
                visibleWorldRect: options.visibleWorldRect || null,
                containmentRect: targetGroup ? {
                    x: targetGroup.position.x,
                    y: targetGroup.position.y,
                    width: targetGroup.size.width,
                    height: targetGroup.size.height,
                } : null,
            }
        );
        if (positions.length !== acceptedEntries.length) {
            result.reason = 'no_open_batch_position';
            return result;
        }
        const additions = acceptedEntries.map(function (entry, index) {
            return {
                nodeId: entry.nodeId,
                nodeKind: 'product_occurrence',
                sourceOccurrenceId: entry.sourceOccurrenceId,
                nameSnapshot: entry.nameSnapshot,
                itemIdSnapshot: entry.itemIdSnapshot,
                position: positions[index],
                positionMode: 'manual',
            };
        });
        setMapNodes(next, mapNodes(next).concat(additions));
        result.addedNodeIds = additions.map(function (node) { return node.nodeId; });
        if (targetGroup) {
            result.map = setGroupMembers(
                next,
                targetGroup.groupId,
                (targetGroup.memberNodeIds || []).concat(result.addedNodeIds)
            );
            result.targetGroupId = targetGroup.groupId;
        } else {
            result.map = next;
        }
        return result;
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
            positionMode: 'manual',
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

    function setNodePositionLocked(processMap, nodeId, locked) {
        const next = cloneMap(processMap);
        const node = mapNodes(next).find(function (item) {
            return item && item.nodeId === nodeId;
        });
        if (node) {
            node.positionMode = locked ? 'locked' : 'manual';
            if (locked) node.locked = true;
            else delete node.locked;
        }
        return next;
    }

    function nodePositionMode(node) {
        if (!node) return 'manual';
        if (node.positionMode === 'auto'
            || node.positionMode === 'manual'
            || node.positionMode === 'locked') return node.positionMode;
        return node.locked === true ? 'locked' : 'manual';
    }

    function nodePositionLocked(node) {
        return nodePositionMode(node) === 'locked';
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

    function normalizeAgentFocusRequest(value) {
        const source = value && typeof value === 'object' ? value : {};
        function normalizedIds(values, singular) {
            const result = [];
            const sourceValues = Array.isArray(values) ? values : [];
            [singular].concat(sourceValues).forEach(function (value) {
                const token = String(value || '').trim();
                if (token && result.indexOf(token) < 0 && result.length < 8) {
                    result.push(token);
                }
            });
            return result;
        }
        const targetNodeIds = normalizedIds(
            source.targetNodeIds || source.target_node_ids,
            source.targetNodeId || source.target_node_id
        );
        const targetOccurrenceIds = normalizedIds(
            source.targetOccurrenceIds || source.target_occurrence_ids,
            source.targetOccurrenceId || source.target_occurrence_id
        );
        if (!targetNodeIds.length && !targetOccurrenceIds.length) return null;
        const labels = (Array.isArray(source.labels) ? source.labels : [])
            .map(function (label) {
                return String(label || '').trim().slice(0, 160);
            })
            .filter(Boolean)
            .slice(0, 8);
        const label = String(source.label || '').trim().slice(0, 160);
        if (!labels.length && label) labels.push(label);
        const requestedDirection = String(source.direction || '').trim();
        return {
            targetNodeId: targetNodeIds.length === 1 && !targetOccurrenceIds.length
                ? targetNodeIds[0] : null,
            targetOccurrenceId: targetOccurrenceIds.length === 1 && !targetNodeIds.length
                ? targetOccurrenceIds[0] : null,
            targetNodeIds: targetNodeIds,
            targetOccurrenceIds: targetOccurrenceIds,
            labels: labels,
            label: label,
            direction: AGENT_FOCUS_DIRECTIONS.indexOf(requestedDirection) >= 0
                ? requestedDirection : 'upstream',
            includeRoutes: source.includeRoutes === undefined
                ? source.include_routes !== false
                : source.includeRoutes !== false,
            fitView: source.fitView === undefined
                ? source.fit_view !== false
                : source.fitView !== false,
            dimOthers: source.dimOthers === undefined
                ? source.dim_others !== false
                : source.dimOthers !== false,
        };
    }

    function resolveProcessMapFocus(processMap, value, productStructure) {
        const request = normalizeAgentFocusRequest(value);
        if (!request) return null;
        const nodes = mapNodes(processMap).filter(function (node) {
            return node && node.nodeId;
        });
        const nodeById = new Map(nodes.map(function (node) {
            return [String(node.nodeId), node];
        }));
        const requestedTargets = request.targetNodeIds.map(function (targetNodeId, index) {
            return {
                targetNodeId: targetNodeId,
                targetOccurrenceId: null,
                label: request.labels[index] || '',
            };
        });
        const occurrenceLabelOffset = requestedTargets.length;
        request.targetOccurrenceIds.forEach(function (targetOccurrenceId, index) {
            requestedTargets.push({
                targetNodeId: null,
                targetOccurrenceId: targetOccurrenceId,
                label: request.labels[occurrenceLabelOffset + index] || '',
            });
        });

        const targetDetails = [];
        const targetNodeIdSet = new Set();
        const scopeMemberNodeIdSet = new Set();
        requestedTargets.forEach(function (requested) {
            let directTargets = [];
            let scopeMemberNodeIds = [];
            let resolution = 'exact';
            if (requested.targetNodeId && nodeById.has(requested.targetNodeId)) {
                directTargets = [nodeById.get(requested.targetNodeId)];
            } else if (requested.targetOccurrenceId) {
                directTargets = nodes.filter(function (node) {
                    return node.nodeKind === 'product_occurrence'
                        && String(node.sourceOccurrenceId || '')
                            === requested.targetOccurrenceId;
                });
            }
            if (!directTargets.length && requested.targetOccurrenceId && productStructure) {
                const scope = resolveRequiredOccurrenceScope(
                    productStructure,
                    requested.targetOccurrenceId
                );
                if (scope) {
                    const occurrenceIds = new Set(
                        [scope.scopeOccurrenceId].concat(scope.requiredOccurrenceIds)
                    );
                    scopeMemberNodeIds = nodes.filter(function (node) {
                        return node.nodeKind === 'product_occurrence'
                            && occurrenceIds.has(String(node.sourceOccurrenceId || ''));
                    }).map(function (node) {
                        return String(node.nodeId);
                    }).sort();
                    resolution = scopeMemberNodeIds.length
                        ? 'placed_scope_members' : 'not_placed';
                }
            }
            const directTargetNodeIds = directTargets.map(function (node) {
                return String(node.nodeId);
            }).sort();
            directTargetNodeIds.forEach(function (nodeId) {
                targetNodeIdSet.add(nodeId);
            });
            scopeMemberNodeIds.forEach(function (nodeId) {
                scopeMemberNodeIdSet.add(nodeId);
            });
            if (directTargetNodeIds.length || scopeMemberNodeIds.length) {
                targetDetails.push({
                    targetNodeId: requested.targetNodeId,
                    targetOccurrenceId: requested.targetOccurrenceId,
                    targetNodeIds: directTargetNodeIds,
                    memberNodeIds: scopeMemberNodeIds,
                    label: requested.label,
                    resolution: resolution,
                });
            }
        });
        if (targetDetails.length !== requestedTargets.length) return null;

        const targetNodeIds = Array.from(targetNodeIdSet).sort();
        const scopeMemberNodeIds = Array.from(scopeMemberNodeIdSet).sort();
        const focusedNodeIds = new Set(
            targetNodeIds.concat(scopeMemberNodeIds)
        );
        const focusedEdgeIds = new Set();
        const edges = mapEdges(processMap).filter(function (edge) {
            return edge && edge.edgeId && edge.from && edge.to
                && nodeById.has(String(edge.from.nodeId || ''))
                && nodeById.has(String(edge.to.nodeId || ''));
        });

        if (targetNodeIds.length && request.direction !== 'target') {
            const incoming = new Map();
            const outgoing = new Map();
            edges.forEach(function (edge) {
                const fromId = String(edge.from.nodeId);
                const toId = String(edge.to.nodeId);
                if (!incoming.has(toId)) incoming.set(toId, []);
                if (!outgoing.has(fromId)) outgoing.set(fromId, []);
                incoming.get(toId).push(edge);
                outgoing.get(fromId).push(edge);
            });
            incoming.forEach(function (items) {
                items.sort(function (left, right) {
                    return String(left.edgeId).localeCompare(String(right.edgeId));
                });
            });
            outgoing.forEach(function (items) {
                items.sort(function (left, right) {
                    return String(left.edgeId).localeCompare(String(right.edgeId));
                });
            });
            const queue = targetNodeIds.slice();
            const expanded = new Set();
            while (queue.length) {
                const nodeId = queue.shift();
                if (expanded.has(nodeId)) continue;
                expanded.add(nodeId);
                let candidates = [];
                if (request.direction === 'upstream' || request.direction === 'both') {
                    candidates = candidates.concat((incoming.get(nodeId) || []).map(function (edge) {
                        return { edge: edge, adjacentId: String(edge.from.nodeId) };
                    }));
                }
                if (request.direction === 'downstream' || request.direction === 'both') {
                    candidates = candidates.concat((outgoing.get(nodeId) || []).map(function (edge) {
                        return { edge: edge, adjacentId: String(edge.to.nodeId) };
                    }));
                }
                candidates.sort(function (left, right) {
                    return String(left.edge.edgeId).localeCompare(String(right.edge.edgeId))
                        || left.adjacentId.localeCompare(right.adjacentId);
                });
                candidates.forEach(function (candidate) {
                    focusedEdgeIds.add(String(candidate.edge.edgeId));
                    if (!focusedNodeIds.has(candidate.adjacentId)) {
                        focusedNodeIds.add(candidate.adjacentId);
                        queue.push(candidate.adjacentId);
                    }
                });
            }
        }
        if (scopeMemberNodeIds.length && request.includeRoutes) {
            edges.forEach(function (edge) {
                const fromId = String(edge.from.nodeId);
                const toId = String(edge.to.nodeId);
                if (focusedNodeIds.has(fromId) && focusedNodeIds.has(toId)) {
                    focusedEdgeIds.add(String(edge.edgeId));
                }
            });
        }

        const resolutions = Array.from(new Set(targetDetails.map(function (target) {
            return target.resolution;
        })));
        const labels = targetDetails.map(function (target) {
            return target.label;
        }).filter(Boolean);
        return {
            targetNodeId: request.targetNodeId,
            targetOccurrenceId: request.targetOccurrenceId,
            targetNodeIds: targetNodeIds,
            targetOccurrenceIds: request.targetOccurrenceIds.slice(),
            targets: targetDetails,
            nodeIds: Array.from(focusedNodeIds).sort(),
            edgeIds: request.includeRoutes ? Array.from(focusedEdgeIds).sort() : [],
            labels: labels,
            label: request.label || labels.join(', '),
            direction: request.direction,
            includeRoutes: request.includeRoutes,
            fitView: request.fitView,
            dimOthers: request.dimOthers,
            resolution: resolutions.length === 1 ? resolutions[0] : 'mixed',
        };
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
                        nodeKind: node && node.nodeKind || null,
                        portOrientation: junction ? 'horizontal' : nodePortOrientation(node),
                        portOrder: junction ? 'input_first' : nodePortOrder(node),
                    }
                    : {
                        x: padding + rank * (width + columnGap) + (junction ? width / 2 : 0),
                        y: padding + rowIndex * (height + rowGap) + (junction ? height / 2 : 0),
                        width: junction ? 0 : width,
                        height: junction ? 0 : height,
                        isJunction: junction,
                        nodeKind: node && node.nodeKind || null,
                        portOrientation: junction ? 'horizontal' : nodePortOrientation(node),
                        portOrder: junction ? 'input_first' : nodePortOrder(node),
                    };
            });
        });
        return positions;
    }

    function graphBounds(positions, groups, edgeGeometries) {
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
        const geometries = Array.isArray(edgeGeometries)
            ? edgeGeometries
            : Object.keys(edgeGeometries || {}).map(function (key) { return edgeGeometries[key]; });
        geometries.forEach(function (geometry) {
            const bounds = geometry && geometry.bounds;
            if (!bounds || !finiteNumber(bounds.x) || !finiteNumber(bounds.y)
                || !finiteNumber(bounds.width) || !finiteNumber(bounds.height)) return;
            values.push(bounds);
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

    function portAnchor(position, side, slotIndex, slotCount) {
        if (position && position.isJunction) {
            return { x: position.x, y: position.y };
        }
        const count = Number.isInteger(slotCount) && slotCount > 1 ? slotCount : 1;
        const index = Number.isInteger(slotIndex)
            ? clamp(slotIndex, 0, count - 1)
            : 0;
        const slotRatio = count > 1 ? (index + 1) / (count + 1) : 0.5;
        const leading = position && position.portOrder === 'output_first'
            ? side === 'out'
            : side === 'in';
        if (position && position.portOrientation === 'vertical') {
            return {
                x: position.x + position.width * slotRatio,
                y: leading ? position.y : position.y + position.height,
            };
        }
        return {
            x: leading ? position.x : position.x + position.width,
            y: position.y + position.height * slotRatio,
        };
    }

    function processStepInputPortLayout(nodes, edges, positions) {
        const byId = new Map((Array.isArray(nodes) ? nodes : []).filter(Boolean).map(function (node) {
            return [node.nodeId, node];
        }));
        const grouped = new Map();
        (Array.isArray(edges) ? edges : []).forEach(function (edge) {
            if (!edge || !edge.edgeId || !edge.from || !edge.to) return;
            const targetNode = byId.get(edge.to.nodeId);
            const targetPosition = positions && positions[edge.to.nodeId];
            if (!targetNode || targetNode.nodeKind !== 'process_step' || !targetPosition) return;
            if (!grouped.has(edge.to.nodeId)) grouped.set(edge.to.nodeId, []);
            const sourcePosition = positions && positions[edge.from.nodeId];
            const vertical = targetPosition.portOrientation === 'vertical';
            const sourceAxis = sourcePosition
                ? (vertical
                    ? sourcePosition.x + sourcePosition.width / 2
                    : sourcePosition.y + sourcePosition.height / 2)
                : 0;
            grouped.get(edge.to.nodeId).push({
                edgeId: edge.edgeId,
                sourceAxis: sourceAxis,
            });
        });

        const byEdge = {};
        const byNode = {};
        Array.from(grouped.keys()).sort().forEach(function (nodeId) {
            const entries = grouped.get(nodeId).slice().sort(function (left, right) {
                if (left.sourceAxis !== right.sourceAxis) return left.sourceAxis - right.sourceAxis;
                return String(left.edgeId).localeCompare(String(right.edgeId));
            });
            const count = entries.length;
            byNode[nodeId] = entries.map(function (entry, index) {
                const slot = { edgeId: entry.edgeId, index: index, count: count };
                byEdge[entry.edgeId] = slot;
                return slot;
            });
        });
        return { byEdge: byEdge, byNode: byNode };
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

    function polylinePath(points) {
        if (!Array.isArray(points) || points.length < 2) return '';
        const values = ['M', points[0].x, points[0].y];
        for (let index = 1; index < points.length; index += 1) {
            values.push('L', points[index].x, points[index].y);
        }
        return values.join(' ');
    }

    function nearestPointOnPolyline(points, target) {
        const clean = (Array.isArray(points) ? points : []).filter(function (point) {
            return point && finiteNumber(point.x) && finiteNumber(point.y);
        });
        if (clean.length < 2 || !target
            || !finiteNumber(target.x) || !finiteNumber(target.y)) return null;
        let best = null;
        for (let index = 0; index < clean.length - 1; index += 1) {
            const start = clean[index];
            const end = clean[index + 1];
            const dx = end.x - start.x;
            const dy = end.y - start.y;
            const lengthSquared = dx * dx + dy * dy;
            const ratio = lengthSquared > 0
                ? clamp(
                    ((target.x - start.x) * dx + (target.y - start.y) * dy)
                        / lengthSquared,
                    0,
                    1
                )
                : 0;
            const point = {
                x: start.x + dx * ratio,
                y: start.y + dy * ratio,
            };
            const distance = Math.hypot(target.x - point.x, target.y - point.y);
            if (!best || distance < best.distance) {
                best = {
                    point: point,
                    segmentIndex: index,
                    distance: distance,
                };
            }
        }
        return best;
    }

    function edgePointBounds(points) {
        if (!Array.isArray(points) || !points.length) {
            return { x: 0, y: 0, width: 0, height: 0 };
        }
        const xs = points.map(function (point) { return point.x; });
        const ys = points.map(function (point) { return point.y; });
        const minimumX = Math.min.apply(null, xs);
        const maximumX = Math.max.apply(null, xs);
        const minimumY = Math.min.apply(null, ys);
        const maximumY = Math.max.apply(null, ys);
        return {
            x: minimumX,
            y: minimumY,
            width: maximumX - minimumX,
            height: maximumY - minimumY,
        };
    }

    function edgeGeometryFromAnchors(start, end, source, target, routing, routingEnabled) {
        const route = routing && typeof routing === 'object' ? routing : {};
        const mode = routingEnabled !== false && (
            route.mode === 'orthogonal_auto'
            || route.mode === 'orthogonal_manual'
            || route.mode === 'polyline_manual'
        ) ? route.mode : 'bezier_legacy';
        if (mode !== 'bezier_legacy') {
            const waypoints = Array.isArray(route.waypoints) ? route.waypoints.filter(function (point) {
                return point && finiteNumber(point.x) && finiteNumber(point.y);
            }).map(function (point) { return { x: point.x, y: point.y }; }) : [];
            const points = [start].concat(waypoints, [end]);
            return {
                mode: mode,
                points: points,
                path: polylinePath(points),
                bounds: edgePointBounds(points),
                obstacleFingerprint: route.obstacleFingerprint || null,
                routerVersion: route.routerVersion || null,
            };
        }
        const points = [start, end];
        return {
            mode: 'bezier_legacy',
            points: points,
            path: bezierPath(
                start,
                end,
                source && source.portOrientation,
                target && target.portOrientation,
                source && source.portOrder,
                target && target.portOrder
            ),
            bounds: edgePointBounds(points),
            obstacleFingerprint: null,
            routerVersion: null,
        };
    }

    function edgeGeometry(edge, positions, options) {
        const opts = options || {};
        if (!edge || !edge.from || !edge.to) return null;
        const source = positions && positions[edge.from.nodeId];
        const target = positions && positions[edge.to.nodeId];
        if (!source || !target) return null;
        const inputSlot = opts.inputPortSlots && opts.inputPortSlots[edge.edgeId];
        return edgeGeometryFromAnchors(
            portAnchor(source, 'out'),
            portAnchor(
                target,
                'in',
                inputSlot && inputSlot.index,
                inputSlot && inputSlot.count
            ),
            source,
            target,
            edge.routing,
            opts.routingEnabled
        );
    }

    function routeGeometryFindings(edge, geometry, positions, groups) {
        if (!edge || !geometry || geometry.mode === 'bezier_legacy'
            || !Array.isArray(geometry.points) || geometry.points.length < 2) return [];
        const findings = [];
        const segments = [];
        for (let index = 0; index < geometry.points.length - 1; index += 1) {
            const start = geometry.points[index];
            const end = geometry.points[index + 1];
            segments.push([start, end]);
            if (geometry.mode.indexOf('orthogonal_') === 0
                && start.x !== end.x && start.y !== end.y) {
                findings.push({
                    severity: 'warning',
                    code: 'route_diagonal_segment',
                    edgeId: edge.edgeId,
                    message: 'This routed connection contains a diagonal segment and needs repair.',
                });
                break;
            }
        }
        const endpointIds = new Set([edge.from && edge.from.nodeId, edge.to && edge.to.nodeId]);
        Object.keys(positions || {}).sort().some(function (nodeId) {
            const position = positions[nodeId];
            if (!position || endpointIds.has(nodeId) || position.isJunction) return false;
            const rectangle = {
                left: position.x,
                top: position.y,
                right: position.x + position.width,
                bottom: position.y + position.height,
            };
            if (!segments.some(function (segment) {
                return segmentIntersectsRect(segment[0], segment[1], rectangle);
            })) return false;
            findings.push({
                severity: 'warning',
                code: 'route_card_intersection',
                edgeId: edge.edgeId,
                nodeId: nodeId,
                message: 'This routed connection crosses a card and needs repair.',
            });
            return true;
        });
        (Array.isArray(groups) ? groups : []).some(function (group) {
            if (!group || !_validGroupPosition(group.position) || !_finiteGroupSize(group.size)) {
                return false;
            }
            const rectangle = {
                left: group.position.x,
                top: group.position.y - GROUP_HEADER_OVERHANG,
                right: group.position.x + group.size.width,
                bottom: group.position.y,
            };
            if (!segments.some(function (segment) {
                return segmentIntersectsRect(segment[0], segment[1], rectangle);
            })) return false;
            findings.push({
                severity: 'warning',
                code: 'route_group_header_intersection',
                edgeId: edge.edgeId,
                groupId: group.groupId,
                message: 'This routed connection crosses a group header and needs repair.',
            });
            return true;
        });
        return findings;
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

    function normalizePaneWidth(value, minimum, maximum, fallback) {
        const lower = Number.isFinite(Number(minimum)) ? Number(minimum) : MIN_PANE_WIDTH;
        const upper = Math.max(
            lower,
            Number.isFinite(Number(maximum)) ? Number(maximum) : MAX_PANE_WIDTH
        );
        const fallbackWidth = Number.isFinite(Number(fallback))
            ? Number(fallback)
            : DEFAULT_PANE_WIDTH;
        const numeric = Number.isFinite(Number(value)) ? Number(value) : fallbackWidth;
        return Math.round(clamp(numeric, lower, upper));
    }

    function PaneDivider(options) {
        this.options = options || {};
        this.workspace = this.options.workspace;
        this.pane = this.options.pane;
        this.minimumWidth = Number(this.options.minimumWidth) || MIN_PANE_WIDTH;
        this.maximumConfiguredWidth = Number(this.options.maximumWidth) || MAX_PANE_WIDTH;
        this.minimumViewportWidth = Number(this.options.minimumViewportWidth)
            || MIN_VIEWPORT_WIDTH;
        this.width = normalizePaneWidth(
            this.options.width,
            this.minimumWidth,
            this.maximumConfiguredWidth,
            DEFAULT_PANE_WIDTH
        );
        this.collapsed = !!this.options.collapsed;
        this.resizeState = null;
        this.toggleDragState = null;
        this.toggleDragged = false;

        this.element = document.createElement('div');
        this.element.className = 'ip-pane-divider';
        this.resizeHandle = document.createElement('div');
        this.resizeHandle.className = 'ip-pane-divider-resize';
        this.resizeHandle.tabIndex = 0;
        this.resizeHandle.setAttribute('role', 'separator');
        this.resizeHandle.setAttribute('aria-orientation', 'vertical');
        this.resizeHandle.setAttribute(
            'aria-label',
            this.options.resizeLabel || 'Resize pane'
        );

        this.toggle = document.createElement('button');
        this.toggle.type = 'button';
        this.toggle.className = 'ip-pane-divider-toggle';
        if (this.pane && this.pane.id) {
            this.toggle.setAttribute('aria-controls', this.pane.id);
        }
        const icon = svgElement('svg', {
            class: 'ip-pane-divider-toggle-icon',
            viewBox: '0 0 24 24',
            'aria-hidden': 'true',
        });
        icon.appendChild(svgElement('path', {
            d: 'M14.5 7.5L10 12l4.5 4.5',
            fill: 'none',
            stroke: 'currentColor',
            'stroke-width': '2',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        }));
        this.toggle.appendChild(icon);
        this.icon = icon;
        this.element.appendChild(this.resizeHandle);
        this.element.appendChild(this.toggle);

        this._onResizePointerDown = this._resizePointerDown.bind(this);
        this._onResizePointerMove = this._resizePointerMove.bind(this);
        this._onResizePointerUp = this._resizePointerUp.bind(this);
        this._onResizeKeyDown = this._resizeKeyDown.bind(this);
        this._onTogglePointerDown = this._togglePointerDown.bind(this);
        this._onTogglePointerMove = this._togglePointerMove.bind(this);
        this._onTogglePointerUp = this._togglePointerUp.bind(this);
        this._onTogglePointerCancel = this._togglePointerCancel.bind(this);
        this._onToggleClick = this._toggleClick.bind(this);
        this.resizeHandle.addEventListener('pointerdown', this._onResizePointerDown);
        this.resizeHandle.addEventListener('pointermove', this._onResizePointerMove);
        this.resizeHandle.addEventListener('pointerup', this._onResizePointerUp);
        this.resizeHandle.addEventListener('pointercancel', this._onResizePointerUp);
        this.resizeHandle.addEventListener('keydown', this._onResizeKeyDown);
        this.toggle.addEventListener('pointerdown', this._onTogglePointerDown);
        this.toggle.addEventListener('pointermove', this._onTogglePointerMove);
        this.toggle.addEventListener('pointerup', this._onTogglePointerUp);
        this.toggle.addEventListener('pointercancel', this._onTogglePointerCancel);
        this.toggle.addEventListener('click', this._onToggleClick);
        this.sync(this.collapsed, this.width);
    }

    PaneDivider.prototype._availableMaximumWidth = function () {
        if (!this.workspace || typeof this.workspace.getBoundingClientRect !== 'function') {
            return this.maximumConfiguredWidth;
        }
        const workspaceWidth = this.workspace.getBoundingClientRect().width;
        if (!Number.isFinite(workspaceWidth) || workspaceWidth <= 0) {
            return this.maximumConfiguredWidth;
        }
        return Math.max(
            this.minimumWidth,
            Math.min(
                this.maximumConfiguredWidth,
                Math.floor(workspaceWidth - this.minimumViewportWidth)
            )
        );
    };

    PaneDivider.prototype._normalizedWidth = function (value) {
        return normalizePaneWidth(
            value,
            this.minimumWidth,
            this._availableMaximumWidth(),
            this.width
        );
    };

    PaneDivider.prototype.sync = function (collapsed, width) {
        this.collapsed = !!collapsed;
        this.width = this._normalizedWidth(width);
        if (this.workspace) {
            this.workspace.style.setProperty('--pm-structure-width', this.width + 'px');
        }
        this.element.classList.toggle('is-collapsed', this.collapsed);
        this.toggle.setAttribute('aria-expanded', this.collapsed ? 'false' : 'true');
        const label = this.collapsed ? 'Expand pane' : 'Collapse pane';
        this.toggle.setAttribute('aria-label', label);
        this.toggle.title = label;
        this.resizeHandle.tabIndex = this.collapsed ? -1 : 0;
        this.resizeHandle.setAttribute('aria-disabled', this.collapsed ? 'true' : 'false');
        this.resizeHandle.setAttribute('aria-valuemin', String(this.minimumWidth));
        this.resizeHandle.setAttribute('aria-valuemax', String(this._availableMaximumWidth()));
        this.resizeHandle.setAttribute('aria-valuenow', String(this.width));
    };

    PaneDivider.prototype._requestWidth = function (value) {
        const next = this._normalizedWidth(value);
        let applied = next;
        if (typeof this.options.onResize === 'function') {
            const result = this.options.onResize(next);
            if (Number.isFinite(Number(result))) applied = Number(result);
        }
        this.sync(this.collapsed, applied);
        return this.width;
    };

    PaneDivider.prototype._resizePointerDown = function (event) {
        if (this.collapsed || event.button !== 0) return;
        event.preventDefault();
        this.resizeState = {
            pointerId: event.pointerId,
            startX: event.clientX,
            startWidth: this.width,
        };
        this.element.classList.add('is-resizing');
        if (this.workspace) this.workspace.classList.add('is-resizing-pane');
        if (typeof this.resizeHandle.setPointerCapture === 'function') {
            this.resizeHandle.setPointerCapture(event.pointerId);
        }
    };

    PaneDivider.prototype._resizePointerMove = function (event) {
        if (!this.resizeState || this.resizeState.pointerId !== event.pointerId) return;
        event.preventDefault();
        this._requestWidth(
            this.resizeState.startWidth + event.clientX - this.resizeState.startX
        );
    };

    PaneDivider.prototype._resizePointerUp = function (event) {
        if (!this.resizeState || this.resizeState.pointerId !== event.pointerId) return;
        this.resizeState = null;
        this.element.classList.remove('is-resizing');
        if (this.workspace) this.workspace.classList.remove('is-resizing-pane');
        if (
            typeof this.resizeHandle.hasPointerCapture === 'function'
            && this.resizeHandle.hasPointerCapture(event.pointerId)
        ) {
            this.resizeHandle.releasePointerCapture(event.pointerId);
        }
    };

    PaneDivider.prototype._resizeKeyDown = function (event) {
        if (this.collapsed) return;
        let next = null;
        if (event.key === 'ArrowLeft') next = this.width - PANE_RESIZE_STEP;
        else if (event.key === 'ArrowRight') next = this.width + PANE_RESIZE_STEP;
        else if (event.key === 'Home') next = this.minimumWidth;
        else if (event.key === 'End') next = this._availableMaximumWidth();
        if (next === null) return;
        event.preventDefault();
        this._requestWidth(next);
    };

    PaneDivider.prototype._togglePointerDown = function (event) {
        if (event.button !== 0) return;
        event.stopPropagation();
        this.toggleDragged = false;
        this.toggleDragState = {
            pointerId: event.pointerId,
            startX: event.clientX,
            startY: event.clientY,
        };
        if (typeof this.toggle.setPointerCapture === 'function') {
            this.toggle.setPointerCapture(event.pointerId);
        }
    };

    PaneDivider.prototype._togglePointerMove = function (event) {
        const state = this.toggleDragState;
        if (!state || state.pointerId !== event.pointerId) return;
        if (Math.hypot(event.clientX - state.startX, event.clientY - state.startY) > 5) {
            this.toggleDragged = true;
        }
    };

    PaneDivider.prototype._togglePointerUp = function (event) {
        const state = this.toggleDragState;
        if (!state || state.pointerId !== event.pointerId) return;
        this.toggleDragState = null;
        if (
            typeof this.toggle.hasPointerCapture === 'function'
            && this.toggle.hasPointerCapture(event.pointerId)
        ) {
            this.toggle.releasePointerCapture(event.pointerId);
        }
        setTimeout(function () { this.toggleDragged = false; }.bind(this), 0);
    };

    PaneDivider.prototype._togglePointerCancel = function () {
        this.toggleDragState = null;
        this.toggleDragged = false;
    };

    PaneDivider.prototype._toggleClick = function (event) {
        event.preventDefault();
        event.stopPropagation();
        if (this.toggleDragged) return;
        if (typeof this.options.onToggle === 'function') {
            this.options.onToggle(!this.collapsed);
        }
    };

    PaneDivider.prototype.destroy = function () {
        this.resizeState = null;
        this.toggleDragState = null;
        if (this.workspace) this.workspace.classList.remove('is-resizing-pane');
        this.resizeHandle.removeEventListener('pointerdown', this._onResizePointerDown);
        this.resizeHandle.removeEventListener('pointermove', this._onResizePointerMove);
        this.resizeHandle.removeEventListener('pointerup', this._onResizePointerUp);
        this.resizeHandle.removeEventListener('pointercancel', this._onResizePointerUp);
        this.resizeHandle.removeEventListener('keydown', this._onResizeKeyDown);
        this.toggle.removeEventListener('pointerdown', this._onTogglePointerDown);
        this.toggle.removeEventListener('pointermove', this._onTogglePointerMove);
        this.toggle.removeEventListener('pointerup', this._onTogglePointerUp);
        this.toggle.removeEventListener('pointercancel', this._onTogglePointerCancel);
        this.toggle.removeEventListener('click', this._onToggleClick);
    };

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

    function resolveRequiredOccurrenceScope(structure, scopeOccurrenceId) {
        const normalized = normalizeProductStructure(structure);
        const catalog = occurrenceIndex(normalized);
        const scopeId = String(scopeOccurrenceId || '').trim();
        const scope = catalog.byId.get(scopeId);
        if (!scope) return null;

        const requiredOccurrenceIds = [];
        const visited = new Set();
        function collect(occurrence) {
            if (!occurrence || visited.has(occurrence.occurrenceId)) return;
            visited.add(occurrence.occurrenceId);
            if (String(occurrence.kind || '').toLowerCase() === 'part') {
                requiredOccurrenceIds.push(occurrence.occurrenceId);
                return;
            }
            (catalog.children.get(occurrence.occurrenceId) || []).forEach(collect);
        }
        collect(scope);

        const expandedOccurrenceIds = new Set();
        const parentMatchCounts = {};
        requiredOccurrenceIds.forEach(function (occurrenceId) {
            let current = catalog.byId.get(occurrenceId);
            const parentGuard = new Set();
            while (current && current.parentOccurrenceId) {
                const parentId = String(current.parentOccurrenceId);
                if (parentGuard.has(parentId)) break;
                parentGuard.add(parentId);
                expandedOccurrenceIds.add(parentId);
                parentMatchCounts[parentId] = (parentMatchCounts[parentId] || 0) + 1;
                current = catalog.byId.get(parentId);
            }
        });

        return {
            scopeOccurrenceId: scopeId,
            scopeName: String(scope.name || scope.itemId || scopeId),
            requiredOccurrenceIds: requiredOccurrenceIds,
            expandedOccurrenceIds: Array.from(expandedOccurrenceIds),
            parentMatchCounts: parentMatchCounts,
        };
    }

    function normalizeRequiredOccurrenceSelection(structure, value) {
        if (!value || typeof value !== 'object') return null;
        const resolved = resolveRequiredOccurrenceScope(
            structure,
            value.scopeOccurrenceId || value.scope_occurrence_id
        );
        if (!resolved || !resolved.requiredOccurrenceIds.length) return null;
        const requestedCurrent = String(
            value.currentOccurrenceId || value.current_occurrence_id || ''
        );
        resolved.label = resolved.scopeName;
        resolved.currentOccurrenceId = resolved.requiredOccurrenceIds.indexOf(requestedCurrent) >= 0
            ? requestedCurrent
            : resolved.requiredOccurrenceIds[0];
        return resolved;
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

    function processMapCardPreviewDescriptors(processMap, productStructure) {
        const catalog = occurrenceIndex(normalizeProductStructure(productStructure));
        const nodeById = new Map();
        mapNodes(processMap).forEach(function (node) {
            if (node && node.nodeId) nodeById.set(node.nodeId, node);
        });
        const incoming = new Map();
        mapEdges(processMap).forEach(function (edge) {
            if (!edge || !edge.from || !edge.to || !edge.from.nodeId || !edge.to.nodeId) return;
            if (!incoming.has(edge.to.nodeId)) incoming.set(edge.to.nodeId, []);
            incoming.get(edge.to.nodeId).push(edge.from.nodeId);
        });
        incoming.forEach(function (values) { values.sort(); });

        const occurrenceLeaves = new Map();
        function leafOccurrences(occurrenceId, visiting) {
            if (occurrenceLeaves.has(occurrenceId)) {
                return new Set(occurrenceLeaves.get(occurrenceId));
            }
            const occurrence = catalog.byId.get(occurrenceId);
            if (!occurrence) return new Set();
            if (occurrence.kind === 'part') {
                occurrenceLeaves.set(occurrenceId, [occurrenceId]);
                return new Set([occurrenceId]);
            }
            const active = visiting || new Set();
            if (active.has(occurrenceId)) return new Set();
            active.add(occurrenceId);
            const result = new Set();
            (catalog.children.get(occurrenceId) || []).forEach(function (child) {
                leafOccurrences(child.occurrenceId, active).forEach(function (id) {
                    result.add(id);
                });
            });
            active.delete(occurrenceId);
            if (!result.size && occurrenceId) result.add(occurrenceId);
            const sorted = Array.from(result).sort();
            occurrenceLeaves.set(occurrenceId, sorted);
            return new Set(sorted);
        }

        function collectUpstream(nodeId, stopAtStage, visiting) {
            const active = visiting || new Set();
            if (active.has(nodeId)) return new Set();
            active.add(nodeId);
            const result = new Set();
            (incoming.get(nodeId) || []).forEach(function (sourceId) {
                const source = nodeById.get(sourceId);
                if (!source) return;
                if (source.nodeKind === 'product_occurrence') {
                    leafOccurrences(source.sourceOccurrenceId).forEach(function (id) {
                        result.add(id);
                    });
                    return;
                }
                if (source.nodeKind === 'process_step' && stopAtStage) return;
                collectUpstream(sourceId, stopAtStage, active).forEach(function (id) {
                    result.add(id);
                });
            });
            active.delete(nodeId);
            return result;
        }

        const descriptors = [];
        mapNodes(processMap).forEach(function (node) {
            if (!node || !node.nodeId || isJunctionNode(node)) return;
            if (node.nodeKind === 'product_occurrence') {
                const occurrenceIds = Array.from(
                    leafOccurrences(node.sourceOccurrenceId)
                ).sort();
                if (!occurrenceIds.length) return;
                descriptors.push({
                    previewId: node.nodeId,
                    kind: 'occurrence',
                    occurrenceIds: occurrenceIds,
                    directOccurrenceIds: [],
                });
                return;
            }
            if (node.nodeKind !== 'process_step') return;
            const cumulative = collectUpstream(node.nodeId, false);
            const direct = collectUpstream(node.nodeId, true);
            if (!cumulative.size) return;
            descriptors.push({
                previewId: node.nodeId,
                kind: 'stage',
                occurrenceIds: Array.from(cumulative).sort(),
                directOccurrenceIds: Array.from(direct).filter(function (id) {
                    return cumulative.has(id);
                }).sort(),
            });
        });
        return descriptors.sort(function (left, right) {
            return left.previewId.localeCompare(right.previewId);
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
        this.stageDetailOperationIds = new Set(
            (Array.isArray(this.options.stageDetailOperationIds)
                ? this.options.stageDetailOperationIds : [])
                .map(function (value) { return String(value || '').trim(); })
                .filter(Boolean)
        );
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
        this.selectedOccurrenceIds = new Set();
        this.treeDragPreviewElement = null;
        this.treeFilter = '';
        this.requiredOccurrenceSelection = normalizeRequiredOccurrenceSelection(
            this.productStructure,
            this.options.requiredOccurrenceSelection
        );
        this.agentExpandedOccurrenceIds = new Set(
            this.requiredOccurrenceSelection
                ? this.requiredOccurrenceSelection.expandedOccurrenceIds
                : []
        );
        this.requiredOccurrenceIds = new Set(
            this.requiredOccurrenceSelection
                ? this.requiredOccurrenceSelection.requiredOccurrenceIds
                : []
        );
        this.savedMap = cloneMap(this.processMap);
        this.savedFingerprint = mapFingerprint(this.savedMap);
        this.revision = this.options.revision || null;
        this.findings = Array.isArray(this.options.findings) ? this.options.findings : [];
        this.focusNodeId = isPlacementMap(this.processMap) ? null : (this.options.focusNodeId || null);
        this.selectedNodeId = this.options.selectedNodeId || null;
        this.selectedEdgeId = null;
        this.selectedGroupId = null;
        this.selectedNodeIds = new Set(this.selectedNodeId ? [this.selectedNodeId] : []);
        this.selectedEdgeIds = new Set();
        this.agentFocusRequest = normalizeAgentFocusRequest(this.options.agentFocus);
        this.agentFocus = this.agentFocusRequest
            ? resolveProcessMapFocus(
                this.processMap,
                this.agentFocusRequest,
                this.productStructure
            )
            : null;
        this.canvasInteractionMode = (
            !this.editable || this.options.canvasInteractionMode === 'pan'
        ) ? 'pan' : 'select';
        this.spacePanActive = false;
        this.transform = { x: 0, y: 0, scale: 1 };
        this.inputPortLayout = { byEdge: {}, byNode: {} };
        this.structureCollapsed = !!this.options.structureCollapsed;
        this.structureWidth = normalizePaneWidth(
            this.options.structureWidth,
            MIN_PANE_WIDTH,
            MAX_PANE_WIDTH,
            DEFAULT_PANE_WIDTH
        );
        this.structurePaneDivider = null;
        this.interaction = null;
        this.wireSketch = null;
        this.selectedWaypoint = null;
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
        this.processLogicClipboard = null;
        this.processLogicPasteCount = 0;
        this.groupMoveFrameOnly = false;
        this.lastJunctionType = 'operation_stage';
        try {
            const savedJunctionType = window.localStorage.getItem('inspectorpro.processMap.lastJunctionType');
            if (JUNCTION_INSERT_TYPES.indexOf(savedJunctionType) >= 0) {
                this.lastJunctionType = savedJunctionType;
            }
        } catch (_error) {}
        this.junctionMenuElement = null;
        this.junctionMenuOutsideHandler = null;
        this.junctionMenuKeyHandler = null;
        this.spatialAnalysisEnabled = !!this.options.spatialAnalysisEnabled;
        this.spatialPlacementEnabled = !!this.options.spatialPlacementEnabled;
        this.autoRoutingEnabled = !!this.options.autoRoutingEnabled;
        this.newEdgeRouteMode = 'bezier_legacy';
        this.newEdgeRoutingLoading = false;
        this.newEdgeRoutingRequestToken = 0;
        try {
            const savedEdgeRouteMode = window.localStorage.getItem(
                'inspectorpro.processMap.newEdgeRouteMode'
            );
            if (EDGE_DRAW_MODES.indexOf(savedEdgeRouteMode) >= 0
                && (savedEdgeRouteMode !== 'orthogonal_auto' || this.autoRoutingEnabled)) {
                this.newEdgeRouteMode = savedEdgeRouteMode;
            }
        } catch (_error) {}
        this.agentLayoutWriteEnabled = !!this.options.agentLayoutWriteEnabled;
        this.managedProposalWriteEnabled = this.options.managedProposalWriteEnabled === undefined
            ? this.agentLayoutWriteEnabled
            : !!this.options.managedProposalWriteEnabled;
        this.placementPlan = null;
        this.placementPlanRequestToken = 0;
        this.batchPlacementPlan = null;
        this.routePlan = null;
        this.routePlanRequestToken = 0;
        this.managedProposalPlan = null;
        this.managedProposalBusy = false;
        this.managedProposalGeometry = null;
        this.managedProposalReveal = null;
        this.managedProposalRevealTimer = null;
        this.managedProposalRevealFrame = null;
        this.cardPreviews = new Map();
        this.cardPreviewDescriptors = new Map();
        this.cardPreviewFingerprint = '';
        this.cardPreviewPendingFingerprint = '';
        this.cardPreviewRequestToken = 0;
        this.arrangementPlan = null;
        this.arrangementPlanRequestToken = 0;
        this.arrangementPlanning = false;
        this._arrangementPlanningStartedAt = 0;
        this._arrangementPlanningRequest = null;
        this._arrangementWorker = null;
        this._arrangementWorkerPending = null;
        this._suppressClick = false;
        this.instanceId = 'pm-arrow-' + (++instanceCounter);
        this.destroyed = false;
        this.cardToolbarEnabled = this.editable && this.options.cardToolbar === true;
        this.cardToolbarManager = null;
        this.cardToolbarElement = null;
        this.cardToolbarNodeId = null;
        this.cardToolbarEdgeId = null;
        this.cardToolbarGroupId = null;
        this.cardToolbarOwner = null;
        this.floatingDom = this.options.floatingDom
            || (typeof window !== 'undefined' ? window.FloatingUIDOM : null);
        this._build();
        this._initializeCardToolbar();
        this.renderGraph({ fit: true });
        this._scheduleSuggestionLoad();
        if (this.newEdgeRouteMode === 'orthogonal_auto') {
            this.setNewEdgeRouteMode('orthogonal_auto');
        }
        if (this.autoRoutingEnabled && mapEdges(this.processMap).some(function (edge) {
            return edge && edge.routing && edge.routing.mode === 'orthogonal_auto';
        })) {
            this._ensureSpatialContract().then(function () {
                if (this.destroyed) return;
                const refreshed = this._refreshAutoRoutes(this.processMap);
                if (!refreshed.failures.length
                    && mapFingerprint(refreshed.map) !== mapFingerprint(this.processMap)) {
                    this.processMap = refreshed.map;
                    this._setDirty(mapFingerprint(this.processMap) !== this.savedFingerprint);
                    this._notifyMapChange();
                }
                this.renderGraph({ fit: false });
            }.bind(this)).catch(function () {});
        }
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
            this.stageDetailNav = document.createElement('div');
            this.stageDetailNav.className = 'pm-stage-detail-nav';
            this.stageDetailNav.hidden = true;
            this.stageDetailBackButton = this._button(
                '<',
                'Back to the parent process map',
                this.back.bind(this)
            );
            this.stageDetailBackButton.classList.add('pm-stage-detail-back');
            this.stageDetailBreadcrumb = document.createElement('span');
            this.stageDetailBreadcrumb.className = 'pm-stage-detail-breadcrumb';
            this.stageDetailNav.appendChild(this.stageDetailBackButton);
            this.stageDetailNav.appendChild(this.stageDetailBreadcrumb);
            this.mapManager.appendChild(this.stageDetailNav);
            this.mapManager.appendChild(this.mapSelect);
            this.mapManager.appendChild(this.mapActionSelect);
            this.toolbarLeft.appendChild(this.mapManager);
            this._renderMapCatalogControls();
        }

        this.toolbarActions = document.createElement('div');
        this.toolbarActions.className = 'pm-toolbar-actions';
        this.zoomOutButton = this._button('-', 'Zoom out', this.zoomBy.bind(this, 0.86));
        this.zoomInButton = this._button('+', 'Zoom in', this.zoomBy.bind(this, 1.16));
        this.fitButton = this._button('Fit', 'Fit flow to viewport', this.fit.bind(this));
        this.toolbarActions.appendChild(this.zoomOutButton);
        this.toolbarActions.appendChild(this.zoomInButton);
        this.toolbarActions.appendChild(this.fitButton);
        if (typeof this.options.onAnalyze === 'function') {
            this.analyzeButton = this._button(
                'Analyze',
                'Ask Sage to analyze the saved process flow',
                this.analyze.bind(this)
            );
            this.toolbarActions.appendChild(this.analyzeButton);
        }
        if (typeof this.options.onAnalyzeLayout === 'function') {
            this.analyzeLayoutButton = this._button(
                'Analyze Layout',
                'Ask Sage to analyze card and wire layout',
                this.analyzeLayout.bind(this)
            );
            this.toolbarActions.appendChild(this.analyzeLayoutButton);
        }
        if (typeof this.options.onReviewKnowledge === 'function') {
            this.reviewKnowledgeButton = this._button(
                'Review',
                'Review grounded assembly knowledge and inferred process claims',
                this.reviewKnowledge.bind(this)
            );
            this.toolbarActions.appendChild(this.reviewKnowledgeButton);
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
            this.deleteButton = this._button(
                'Delete',
                'Delete selected card, connection, or group',
                this.deleteSelection.bind(this)
            );
            this.clearMapButton = this._button(
                'Clear Map',
                'Clear all cards, connections, junctions, and groups',
                this.clearMap.bind(this)
            );
            this.previewButton = this._button(
                '3D',
                'Open selected card in the interactive 3D preview',
                this.openSelectedPreview.bind(this)
            );
            if (typeof this.options.onOpenStageDetail === 'function') {
                this.stageDetailButton = this._button(
                    'Open Details',
                    'Select a high-level stage to open its detailed process',
                    this.openSelectedStageDetail.bind(this)
                );
            }
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
                this.cleanUpButton = this._button(
                    'Clean Map',
                    'Preview a cleaner arrangement without moving locked cards or group frames',
                    this.previewArrangement.bind(this)
                );
                this.addJunctionButton = this._button(
                    '+ Junction',
                    'Add the last-used operation stage or junction type',
                    function () { this.addJunctionChoice(this.lastJunctionType); }.bind(this)
                );
                this.addJunctionMenuButton = this._button(
                    '',
                    'Choose operation stage or junction type',
                    this.toggleJunctionMenu.bind(this)
                );
                this.groupSelect = document.createElement('select');
                this.groupSelect.className = 'pm-group-select';
                this.groupSelect.setAttribute('aria-label', 'Select group frame');
                this.groupSelect.title = 'Select a group frame to edit or delete';
                this.groupSelect.addEventListener('change', this.changeGroupSelection.bind(this));
                this._renderGroupSelect();
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
            if (this.addJunctionButton) this.toolbarActions.appendChild(this.addJunctionButton);
            if (this.groupSelect) this.toolbarActions.appendChild(this.groupSelect);
            this.toolbarActions.appendChild(this.deleteButton);
            this.toolbarActions.appendChild(this.clearMapButton);
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
        this.toolbar.appendChild(this.toolbarLeft);
        this.toolbar.appendChild(this.toolbarActions);

        this.status = document.createElement('div');
        this.status.className = 'pm-editor-status';
        this.status.setAttribute('role', 'status');
        this.status.setAttribute('aria-live', 'polite');
        this.status.setAttribute('aria-atomic', 'true');
        this.toolbarLeft.appendChild(this.status);

        this.workspace = document.createElement('div');
        this.workspace.className = 'pm-workspace';
        this.structureSidebar = document.createElement('aside');
        this.structureSidebar.className = 'pm-structure-sidebar';
        this.structureSidebar.id = 'pm-structure-sidebar-' + this.instanceId;
        this.structureSidebar.setAttribute('aria-label', 'Product structure source catalog');
        const structureHeader = document.createElement('div');
        structureHeader.className = 'pm-structure-header';
        const structureTitle = document.createElement('div');
        structureTitle.className = 'pm-structure-title';
        structureTitle.textContent = this.productStructure.productName || 'Product Structure';
        this.structureHint = document.createElement('div');
        this.structureHint.className = 'pm-structure-hint';
        this.structureHint.textContent = 'Ctrl-click to select multiple, then drag into the map';
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
        structureHeader.appendChild(this.structureHint);
        structureHeader.appendChild(this.treeSearch);
        this.requiredSummary = document.createElement('section');
        this.requiredSummary.className = 'pm-required-summary';
        this.requiredSummary.hidden = true;
        this.requiredSummary.setAttribute('aria-label', 'Agent identified parts');
        this.requiredSummaryTitle = document.createElement('div');
        this.requiredSummaryTitle.className = 'pm-required-summary-title';
        this.requiredSummaryProgress = document.createElement('div');
        this.requiredSummaryProgress.className = 'pm-required-summary-progress';
        this.requiredSummaryActions = document.createElement('div');
        this.requiredSummaryActions.className = 'pm-required-summary-actions';
        this.requiredPreviousButton = this._button(
            '<',
            'Previous required part',
            this.focusRequiredOccurrence.bind(this, -1)
        );
        this.requiredPreviousButton.classList.add('pm-required-summary-button');
        this.requiredNextButton = this._button(
            '>',
            'Next required part',
            this.focusRequiredOccurrence.bind(this, 1)
        );
        this.requiredNextButton.classList.add('pm-required-summary-button');
        this.requiredArrangeButton = this._button(
            'Arrange',
            'Preview all remaining required parts in an organized layout',
            this.previewRequiredOccurrencesBatch.bind(this)
        );
        this.requiredArrangeButton.classList.add(
            'pm-required-summary-button',
            'pm-required-summary-arrange'
        );
        this.requiredClearButton = this._button(
            'x',
            'Clear required-part highlights',
            this.clearRequiredOccurrenceScope.bind(this)
        );
        this.requiredClearButton.classList.add('pm-required-summary-button');
        this.requiredSummaryActions.appendChild(this.requiredPreviousButton);
        this.requiredSummaryActions.appendChild(this.requiredNextButton);
        this.requiredSummaryActions.appendChild(this.requiredArrangeButton);
        this.requiredSummaryActions.appendChild(this.requiredClearButton);
        this.requiredSummary.appendChild(this.requiredSummaryTitle);
        this.requiredSummary.appendChild(this.requiredSummaryProgress);
        this.requiredSummary.appendChild(this.requiredSummaryActions);
        this.structureTree = document.createElement('div');
        this.structureTree.className = 'pm-structure-tree';
        this.structureTree.setAttribute('role', 'tree');
        this.structureTree.setAttribute('aria-multiselectable', 'true');
        this.structureSidebar.appendChild(structureHeader);
        this.structureSidebar.appendChild(this.requiredSummary);
        this.structureSidebar.appendChild(this.structureTree);
        this.structurePaneDivider = new PaneDivider({
            workspace: this.workspace,
            pane: this.structureSidebar,
            width: this.structureWidth,
            collapsed: this.structureCollapsed,
            resizeLabel: 'Resize assembly tree pane',
            onResize: function (width) {
                return this.setStructureWidth(width, true);
            }.bind(this),
            onToggle: this.setStructureCollapsed.bind(this),
        });
        this.structureDivider = this.structurePaneDivider.element;
        this.structureDivider.classList.add('pm-structure-divider');
        this.structureToggle = this.structurePaneDivider.toggle;
        this.structureToggle.classList.add('pm-structure-toggle');

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
        this.placementGhostLayer = document.createElement('div');
        this.placementGhostLayer.className = 'pm-placement-ghost-layer';
        this.placementGhostLayer.setAttribute('aria-hidden', 'true');
        this.placementGhostWireSvg = svgElement('svg', { class: 'pm-placement-ghost-wire-layer' });
        this.world.appendChild(this.groupLayer);
        this.world.appendChild(this.edgeSvg);
        this.world.appendChild(this.nodeLayer);
        this.world.appendChild(this.placementGhostWireSvg);
        this.world.appendChild(this.placementGhostLayer);
        this.viewport.appendChild(this.world);
        this.agentFocusBanner = document.createElement('section');
        this.agentFocusBanner.className = 'pm-agent-focus-banner';
        this.agentFocusBanner.hidden = true;
        this.agentFocusBanner.setAttribute('role', 'status');
        this.agentFocusBanner.setAttribute('aria-live', 'polite');
        this.agentFocusMarker = document.createElement('span');
        this.agentFocusMarker.className = 'pm-agent-focus-marker';
        this.agentFocusMarker.setAttribute('aria-hidden', 'true');
        this.agentFocusCopy = document.createElement('span');
        this.agentFocusCopy.className = 'pm-agent-focus-copy';
        this.agentFocusClearButton = this._button(
            'x',
            'Clear Process Map highlight',
            this.clearAgentFocus.bind(this)
        );
        this.agentFocusClearButton.classList.add('pm-agent-focus-clear');
        this.agentFocusBanner.appendChild(this.agentFocusMarker);
        this.agentFocusBanner.appendChild(this.agentFocusCopy);
        this.agentFocusBanner.appendChild(this.agentFocusClearButton);
        this.viewport.appendChild(this.agentFocusBanner);
        this.emptyState = document.createElement('div');
        this.emptyState.className = 'pm-empty-state';
        this.emptyState.textContent = 'Drag an assembly, subassembly, or part from the structure tree to begin building the process map.';
        this.viewport.appendChild(this.emptyState);
        if (this.editable) {
            this.managedProposalReview = document.createElement('div');
            this.managedProposalReview.className = 'pm-managed-proposal-review';
            this.managedProposalReview.hidden = true;
            this.managedProposalReview.setAttribute('role', 'region');
            this.managedProposalReview.setAttribute('aria-label', 'Agent layout proposal review');
            this.managedProposalCopy = document.createElement('div');
            this.managedProposalCopy.className = 'pm-managed-proposal-copy';
            this.managedProposalShowAllButton = this._button(
                'Show all',
                'Skip the progressive build and show the complete proposal',
                this.showAllManagedProposal.bind(this)
            );
            this.managedProposalShowAllButton.classList.add(
                'pm-managed-proposal-show-all'
            );
            this.managedProposalShowAllButton.hidden = true;
            this.managedProposalVisualButton = this._button(
                'Visual check',
                'Review occurrence-level assembly validation',
                this._openManagedProposalVisualValidation.bind(this)
            );
            this.managedProposalVisualButton.classList.add(
                'pm-managed-proposal-visual'
            );
            this.managedProposalVisualButton.hidden = true;
            this.managedProposalApproveButton = this._button(
                'Approve',
                'Approve and apply this exact process-map proposal',
                this.approveManagedProposal.bind(this)
            );
            this.managedProposalApproveButton.classList.add('pm-managed-proposal-approve');
            this.managedProposalDismissButton = this._button(
                'Dismiss',
                'Dismiss this proposal without changing the map',
                this.dismissManagedProposal.bind(this)
            );
            this.managedProposalDismissButton.classList.add('pm-managed-proposal-dismiss');
            this.managedProposalReview.appendChild(this.managedProposalCopy);
            this.managedProposalReview.appendChild(
                this.managedProposalShowAllButton
            );
            this.managedProposalReview.appendChild(
                this.managedProposalVisualButton
            );
            this.managedProposalReview.appendChild(this.managedProposalApproveButton);
            this.managedProposalReview.appendChild(this.managedProposalDismissButton);
            this.viewport.appendChild(this.managedProposalReview);
        }
        if (this.editable) {
            this.selectionMarquee = document.createElement('div');
            this.selectionMarquee.className = 'pm-selection-marquee';
            this.selectionMarquee.hidden = true;
            this.selectionMarquee.setAttribute('aria-hidden', 'true');
            this.viewport.appendChild(this.selectionMarquee);

            this.canvasModeControls = document.createElement('div');
            this.canvasModeControls.className = 'pm-canvas-mode-controls';
            this.canvasModeControls.setAttribute('role', 'toolbar');
            this.canvasModeControls.setAttribute('aria-label', 'Canvas and connection modes');
            const createModeButton = function (mode, label, paths, handler) {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'pm-canvas-mode-button';
                if (mode) button.setAttribute('data-canvas-mode', mode);
                button.setAttribute('aria-label', label);
                button.title = label;
                const icon = svgElement('svg', {
                    viewBox: '0 0 24 24',
                    'aria-hidden': 'true',
                });
                paths.forEach(function (definition) {
                    icon.appendChild(svgElement('path', definition));
                });
                button.appendChild(icon);
                button.addEventListener(
                    'click',
                    handler || this.setCanvasInteractionMode.bind(this, mode)
                );
                return button;
            }.bind(this);
            this.selectModeButton = createModeButton('select', 'Select items (V)', [{
                d: 'M4 3.5 11.3 21l2.4-7.1 7.3-2.5L4 3.5Z',
                fill: 'none',
                stroke: 'currentColor',
                'stroke-width': '1.8',
                'stroke-linecap': 'round',
                'stroke-linejoin': 'round',
            }]);
            this.panModeButton = createModeButton('pan', 'Pan viewport (H or hold Space)', [
                {
                    d: 'M8 11V6.5a1.7 1.7 0 0 1 3.4 0V11',
                    fill: 'none', stroke: 'currentColor', 'stroke-width': '1.7',
                    'stroke-linecap': 'round', 'stroke-linejoin': 'round',
                },
                {
                    d: 'M11.4 10V4.8a1.7 1.7 0 0 1 3.4 0V10',
                    fill: 'none', stroke: 'currentColor', 'stroke-width': '1.7',
                    'stroke-linecap': 'round', 'stroke-linejoin': 'round',
                },
                {
                    d: 'M14.8 10V6.2a1.7 1.7 0 0 1 3.4 0v6.2',
                    fill: 'none', stroke: 'currentColor', 'stroke-width': '1.7',
                    'stroke-linecap': 'round', 'stroke-linejoin': 'round',
                },
                {
                    d: 'M8 10.8 6.5 9.4a1.8 1.8 0 0 0-2.6 2.5l4.9 6.2A5 5 0 0 0 12.7 20h1.8a5 5 0 0 0 5-5v-3.2a1.7 1.7 0 0 0-3.4 0',
                    fill: 'none', stroke: 'currentColor', 'stroke-width': '1.7',
                    'stroke-linecap': 'round', 'stroke-linejoin': 'round',
                },
            ]);
            this.canvasModeControls.appendChild(this.selectModeButton);
            this.canvasModeControls.appendChild(this.panModeButton);
            this.edgeRouteModeDivider = document.createElement('span');
            this.edgeRouteModeDivider.className = 'pm-canvas-mode-divider';
            this.edgeRouteModeDivider.setAttribute('aria-hidden', 'true');
            this.canvasModeControls.appendChild(this.edgeRouteModeDivider);
            this.edgeRouteModeButtons = {};
            [
                {
                    mode: 'bezier_legacy',
                    label: 'New connections: Curved',
                    paths: [{
                        d: 'M3.5 17.5C8 6.5 16 6.5 20.5 17.5',
                        fill: 'none',
                        stroke: 'currentColor',
                        'stroke-width': '1.8',
                        'stroke-linecap': 'round',
                    }],
                },
                {
                    mode: 'orthogonal_auto',
                    label: 'New connections: Orthogonal',
                    paths: [{
                        d: 'M3.5 17.5H9V7.5h11.5',
                        fill: 'none',
                        stroke: 'currentColor',
                        'stroke-width': '1.8',
                        'stroke-linecap': 'round',
                        'stroke-linejoin': 'round',
                    }],
                },
                {
                    mode: 'polyline_manual',
                    label: 'Sketch connection with fixed points',
                    paths: [{
                        d: 'M3.5 18 8.5 11.5 13.5 15 20.5 6M2.5 17h2v2h-2zM7.5 10.5h2v2h-2zM12.5 14h2v2h-2zM19.5 5h2v2h-2z',
                        fill: 'none',
                        stroke: 'currentColor',
                        'stroke-width': '1.6',
                        'stroke-linecap': 'round',
                        'stroke-linejoin': 'round',
                    }],
                },
            ].forEach(function (definition) {
                const button = createModeButton(
                    null,
                    definition.label,
                    definition.paths,
                    this.setNewEdgeRouteMode.bind(this, definition.mode)
                );
                button.classList.add('pm-edge-route-mode-button');
                button.setAttribute('data-edge-route-mode', definition.mode);
                this.edgeRouteModeButtons[definition.mode] = button;
                this.canvasModeControls.appendChild(button);
            }, this);
            this.viewport.appendChild(this.canvasModeControls);
            this._syncNewEdgeRouteModeControl();
            this.wireSketchHelp = document.createElement('div');
            this.wireSketchHelp.className = 'pm-wire-sketch-help';
            this.wireSketchHelp.hidden = true;
            this.wireSketchHelp.setAttribute('role', 'status');
            this.wireSketchHelp.textContent = 'Click to place a fixed point | Click an input to finish | Backspace removes a point | Esc cancels';
            this.viewport.appendChild(this.wireSketchHelp);
        }
        this.connectionLegend = document.createElement('div');
        this.connectionLegend.className = 'pm-connection-legend';
        this.connectionLegend.setAttribute('role', 'group');
        this.connectionLegend.setAttribute('aria-label', 'Connection legend');
        [
            {
                className: 'pm-connection-legend-line applied',
                label: 'Applied connection',
            },
            {
                className: 'pm-connection-legend-line proposal',
                label: 'Agent proposal',
            },
            {
                className: 'pm-connection-legend-line route-preview',
                label: 'Route preview',
            },
            {
                className: 'pm-connection-legend-line route-warning',
                label: 'Route needs review',
            },
        ].forEach(function (definition) {
            const item = document.createElement('div');
            item.className = 'pm-connection-legend-item';
            const swatch = document.createElement('span');
            swatch.className = definition.className;
            swatch.setAttribute('aria-hidden', 'true');
            const copy = document.createElement('span');
            copy.textContent = definition.label;
            item.appendChild(swatch);
            item.appendChild(copy);
            this.connectionLegend.appendChild(item);
        }, this);
        this.viewport.appendChild(this.connectionLegend);
        this.root.appendChild(this.toolbar);
        this.workspace.appendChild(this.structureSidebar);
        this.workspace.appendChild(this.structureDivider);
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
        this._onKeyUp = this.keyUp.bind(this);
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
        this.root.addEventListener('keyup', this._onKeyUp);
        this._syncCanvasInteractionMode();
        this._syncStructureCollapsedState();
        this.renderStructureTree();
        this.updateEditControls();
    };

    ProcessMapEditor.prototype._effectiveCanvasInteractionMode = function () {
        return this.spacePanActive ? 'pan' : this.canvasInteractionMode;
    };

    ProcessMapEditor.prototype._syncCanvasInteractionMode = function () {
        if (!this.viewport) return;
        const effectiveMode = this._effectiveCanvasInteractionMode();
        this.viewport.classList.toggle('mode-select', effectiveMode === 'select');
        this.viewport.classList.toggle('mode-pan', effectiveMode === 'pan');
        this.viewport.setAttribute('data-canvas-mode', effectiveMode);
        if (this.selectModeButton) {
            this.selectModeButton.classList.toggle('active', effectiveMode === 'select');
            this.selectModeButton.setAttribute(
                'aria-pressed', effectiveMode === 'select' ? 'true' : 'false'
            );
        }
        if (this.panModeButton) {
            this.panModeButton.classList.toggle('active', effectiveMode === 'pan');
            this.panModeButton.setAttribute(
                'aria-pressed', effectiveMode === 'pan' ? 'true' : 'false'
            );
        }
    };

    ProcessMapEditor.prototype.setCanvasInteractionMode = function (mode) {
        if (!this.editable || ['select', 'pan'].indexOf(mode) < 0 || this.interaction) {
            return false;
        }
        if (this.wireSketch) this._cancelWireSketch();
        this.canvasInteractionMode = mode;
        this.spacePanActive = false;
        this._syncCanvasInteractionMode();
        if (this.viewport && typeof this.viewport.focus === 'function') {
            this.viewport.focus({ preventScroll: true });
        }
        return true;
    };

    ProcessMapEditor.prototype._syncNewEdgeRouteModeControl = function () {
        const buttons = this.edgeRouteModeButtons || {};
        Object.keys(buttons).forEach(function (mode) {
            const button = buttons[mode];
            const active = this.newEdgeRouteMode === mode;
            const loading = mode === 'orthogonal_auto' && this.newEdgeRoutingLoading;
            const baseLabel = mode === 'orthogonal_auto'
                ? 'New connections: Orthogonal'
                : (mode === 'polyline_manual'
                    ? 'Sketch connection with fixed points'
                    : 'New connections: Curved');
            const label = loading ? 'Loading orthogonal routing' : baseLabel;
            button.setAttribute('aria-label', label);
            button.setAttribute('aria-pressed', active ? 'true' : 'false');
            button.title = label;
            button.classList.toggle('active', active);
            button.disabled = this.saving || this.conflict || loading
                || (mode === 'orthogonal_auto' && !this.autoRoutingEnabled);
        }, this);
    };

    ProcessMapEditor.prototype.setNewEdgeRouteMode = async function (mode) {
        if (!this.editable || EDGE_DRAW_MODES.indexOf(mode) < 0) return false;
        if (this.wireSketch && mode !== 'polyline_manual') {
            this._cancelWireSketch();
        }
        if (mode === 'orthogonal_auto' && !this.autoRoutingEnabled) {
            this.operationError = 'Orthogonal routing is disabled.';
            this.updateEditControls();
            return false;
        }
        const requestToken = ++this.newEdgeRoutingRequestToken;
        if (mode === 'orthogonal_auto' && !this._spatialContractCache) {
            this.newEdgeRoutingLoading = true;
            this._syncNewEdgeRouteModeControl();
            try {
                await this._ensureSpatialContract();
            } catch (_error) {
                if (requestToken === this.newEdgeRoutingRequestToken) {
                    this.newEdgeRoutingLoading = false;
                    this.operationError = 'Orthogonal routing is temporarily unavailable.';
                    this.updateEditControls();
                }
                return false;
            }
        }
        if (requestToken !== this.newEdgeRoutingRequestToken || this.destroyed) return false;
        this.newEdgeRoutingLoading = false;
        this.newEdgeRouteMode = mode;
        this.operationError = '';
        try {
            window.localStorage.setItem(
                'inspectorpro.processMap.newEdgeRouteMode',
                mode
            );
        } catch (_error) {}
        this._syncNewEdgeRouteModeControl();
        this.updateEditControls();
        return true;
    };

    ProcessMapEditor.prototype.toggleNewEdgeRouteMode = function () {
        const currentIndex = EDGE_DRAW_MODES.indexOf(this.newEdgeRouteMode);
        const nextMode = EDGE_DRAW_MODES[(currentIndex + 1) % EDGE_DRAW_MODES.length];
        return this.setNewEdgeRouteMode(nextMode);
    };

    ProcessMapEditor.prototype._applyGraphSelectionClasses = function () {
        const selectedNodes = this.selectedNodeIds || new Set();
        const selectedEdges = this.selectedEdgeIds || new Set();
        Array.prototype.forEach.call(
            this.nodeLayer.querySelectorAll('.pm-node, .pm-junction'),
            function (node) {
                const selected = selectedNodes.has(node.getAttribute('data-node-id'));
                node.classList.toggle('selected', selected);
                node.setAttribute('aria-selected', selected ? 'true' : 'false');
            }
        );
        Array.prototype.forEach.call(this.edgeSvg.querySelectorAll('.pm-edge'), function (edge) {
            const selected = selectedEdges.has(edge.getAttribute('data-edge-id'));
            edge.classList.toggle('selected', selected);
        });
        this._renderSelectedManualRouteWaypoints();
    };

    ProcessMapEditor.prototype._renderSelectedManualRouteWaypoints = function () {
        if (!this.edgeSvg) return;
        Array.prototype.forEach.call(
            this.edgeSvg.querySelectorAll('.pm-edge-waypoint'),
            function (handle) { handle.remove(); }
        );
        if (!this.editable || !this.selectedEdgeId || this.selectedEdgeIds.size !== 1) {
            this.selectedWaypoint = null;
            return;
        }
        const edge = mapEdges(this.processMap).find(function (item) {
            return item && item.edgeId === this.selectedEdgeId;
        }, this);
        if (!edge || !edge.routing || edge.routing.mode !== 'polyline_manual') {
            this.selectedWaypoint = null;
            return;
        }
        const waypoints = normalizeManualRouteWaypoints(edge.routing.waypoints);
        if (this.selectedWaypoint && (
            this.selectedWaypoint.edgeId !== edge.edgeId
            || this.selectedWaypoint.index >= waypoints.length
        )) this.selectedWaypoint = null;
        waypoints.forEach(function (point, index) {
            const selected = this.selectedWaypoint
                && this.selectedWaypoint.edgeId === edge.edgeId
                && this.selectedWaypoint.index === index;
            const handle = svgElement('circle', {
                class: 'pm-edge-waypoint' + (selected ? ' selected' : ''),
                cx: point.x,
                cy: point.y,
                r: 6,
                tabindex: '0',
                role: 'button',
                'data-edge-id': edge.edgeId,
                'data-waypoint-index': index,
                'aria-label': 'Route point ' + (index + 1)
                    + '. Drag to move; Delete removes it.',
            });
            handle.addEventListener('pointerdown', this.startWaypointDrag.bind(
                this,
                edge.edgeId,
                index
            ));
            handle.addEventListener('click', function (event) {
                event.preventDefault();
                event.stopPropagation();
                this.selectedWaypoint = { edgeId: edge.edgeId, index: index };
                this._renderSelectedManualRouteWaypoints();
            }.bind(this));
            this.edgeSvg.appendChild(handle);
        }, this);
    };

    ProcessMapEditor.prototype._resetGraphSelectionState = function () {
        this.selectedNodeIds.clear();
        this.selectedEdgeIds.clear();
        this.selectedNodeId = null;
        this.selectedEdgeId = null;
        this.selectedGroupId = null;
        this.selectedWaypoint = null;
    };

    ProcessMapEditor.prototype._clearGraphSelection = function (reason) {
        this._clearRoutePlan();
        this._closeCardToolbar(reason || 'selection_cleared', false);
        this._resetGraphSelectionState();
        Array.prototype.forEach.call(this.groupLayer.querySelectorAll('.pm-group-frame'), function (group) {
            group.classList.remove('selected');
        });
        this._applyGraphSelectionClasses();
        this.updateEditControls();
    };

    ProcessMapEditor.prototype.setGraphSelection = function (nodeIds, edgeIds) {
        this._clearRoutePlan();
        this._closeCardToolbar('marquee_selection', false);
        this.selectedWaypoint = null;
        this.selectedNodeIds = new Set(Array.isArray(nodeIds) ? nodeIds.filter(Boolean) : []);
        this.selectedEdgeIds = new Set(Array.isArray(edgeIds) ? edgeIds.filter(Boolean) : []);
        this.selectedNodeId = this.selectedNodeIds.size === 1 && !this.selectedEdgeIds.size
            ? Array.from(this.selectedNodeIds)[0] : null;
        this.selectedEdgeId = this.selectedEdgeIds.size === 1 && !this.selectedNodeIds.size
            ? Array.from(this.selectedEdgeIds)[0] : null;
        this.selectedGroupId = null;
        Array.prototype.forEach.call(this.groupLayer.querySelectorAll('.pm-group-frame'), function (group) {
            group.classList.remove('selected');
        });
        this._applyGraphSelectionClasses();
        this.updateEditControls();
        return this.selectedNodeIds.size + this.selectedEdgeIds.size;
    };

    ProcessMapEditor.prototype._syncStructureCollapsedState = function () {
        if (!this.root || !this.structureSidebar || !this.structureToggle) return;
        const collapsed = !!this.structureCollapsed;
        this.root.classList.toggle('structure-collapsed', collapsed);
        this.structureSidebar.setAttribute('aria-hidden', collapsed ? 'true' : 'false');
        if (collapsed) this.structureSidebar.setAttribute('inert', '');
        else this.structureSidebar.removeAttribute('inert');
        if (this.structurePaneDivider) {
            this.structurePaneDivider.sync(collapsed, this.structureWidth);
            this.structureWidth = this.structurePaneDivider.width;
        }
    };

    ProcessMapEditor.prototype.setStructureWidth = function (width, notify) {
        const previous = this.structureWidth;
        this.structureWidth = normalizePaneWidth(
            width,
            MIN_PANE_WIDTH,
            MAX_PANE_WIDTH,
            previous || DEFAULT_PANE_WIDTH
        );
        if (this.structurePaneDivider) {
            this.structurePaneDivider.sync(this.structureCollapsed, this.structureWidth);
            this.structureWidth = this.structurePaneDivider.width;
        } else if (this.workspace) {
            this.workspace.style.setProperty(
                '--pm-structure-width',
                this.structureWidth + 'px'
            );
        }
        if (
            notify !== false
            && this.structureWidth !== previous
            && typeof this.options.onStructureWidthChange === 'function'
        ) {
            this.options.onStructureWidthChange(this.structureWidth);
        }
        if (this.cardToolbarManager && this.cardToolbarManager.isOpen()) {
            this.cardToolbarManager.reposition();
        }
        return this.structureWidth;
    };

    ProcessMapEditor.prototype.setStructureCollapsed = function (collapsed) {
        const next = !!collapsed;
        if (this.structureCollapsed === next) return false;
        if (next && this.structureSidebar.contains(document.activeElement)) {
            this.structureToggle.focus();
        }
        this.structureCollapsed = next;
        this._syncStructureCollapsedState();
        if (typeof this.options.onStructureCollapsedChange === 'function') {
            this.options.onStructureCollapsedChange(next);
        }
        if (this.cardToolbarManager && this.cardToolbarManager.isOpen()) {
            this.cardToolbarManager.reposition();
        }
        return true;
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
            const association = item.association && typeof item.association === 'object'
                ? item.association : {};
            const parent = association.relation === 'stage_detail'
                ? this.mapCatalog.maps.find(function (candidate) {
                    return candidate && String(candidate.mapId || '')
                        === String(association.parentMapId || '');
                }) : null;
            const mapLabel = parent
                ? String(parent.displayName || parent.mapId) + ' > '
                    + String(item.displayName || item.mapId)
                : String(item.displayName || item.mapId);
            this._appendSelectOption(
                this.mapSelect,
                item.mapId,
                mapLabel + marker + status,
                item.status === 'archived'
            );
        }, this);
        this.mapSelect.value = currentId;
        const currentOption = this.mapSelect.options[this.mapSelect.selectedIndex];
        this.mapSelect.title = currentOption
            ? currentOption.textContent : 'Switch process map';

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
        if (Array.isArray(result.stageDetailIndex)) {
            this.stageDetailOperationIds = new Set(
                result.stageDetailIndex
                    .filter(function (item) {
                        return item && item.available !== false;
                    })
                    .map(function (item) {
                        return String(item.stageOperationId || '').trim();
                    })
                    .filter(Boolean)
            );
        }
        this.processMap = cloneMap(result.map);
        this.revision = result.revision || null;
        if (result.productStructure) this.setProductStructure(result.productStructure);
        this.findings = Array.isArray(result.findings) ? result.findings : [];
        this.savedMap = cloneMap(this.processMap);
        this.savedFingerprint = mapFingerprint(this.savedMap);
        this.history.clear();
        this._clearSuggestions();
        this._clearPlacementPlan();
        this._clearRoutePlan();
        this._clearManagedProposal();
        this._resetGraphSelectionState();
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

    ProcessMapEditor.prototype._setCommandButtonLabel = function (button, label) {
        if (!button) return;
        const labelElement = button.querySelector('.ribbon-btn-label');
        if (labelElement) labelElement.textContent = label;
        else button.textContent = label;
    };

    ProcessMapEditor.prototype._decorateRibbonButton = function (
        button,
        iconKey,
        label,
        icons,
        commandKey
    ) {
        if (!button) return button;
        button.className = 'ribbon-btn ribbon-btn-iconic pm-ribbon-command';
        button.setAttribute('data-process-map-command', commandKey || iconKey);
        button.textContent = '';
        const icon = document.createElement('span');
        icon.className = 'ribbon-btn-icon';
        icon.setAttribute('aria-hidden', 'true');
        icon.innerHTML = icons && icons[iconKey] ? icons[iconKey] : '';
        const copy = document.createElement('span');
        copy.className = 'ribbon-btn-label';
        copy.textContent = label;
        button.appendChild(icon);
        button.appendChild(copy);
        return button;
    };

    ProcessMapEditor.prototype._decorateRibbonPicker = function (control, iconKey, label, icons) {
        if (!control) return null;
        const picker = document.createElement('div');
        picker.className = 'pm-ribbon-command-picker';
        picker.setAttribute('data-process-map-command', iconKey);
        picker.setAttribute('role', 'group');
        picker.setAttribute('aria-label', label);
        const icon = document.createElement('span');
        icon.className = 'ribbon-btn-icon';
        icon.setAttribute('aria-hidden', 'true');
        icon.innerHTML = icons && icons[iconKey] ? icons[iconKey] : '';
        picker.appendChild(icon);
        picker.appendChild(control);
        return picker;
    };

    ProcessMapEditor.prototype._junctionRibbonControl = function (icons) {
        if (!this.addJunctionButton || !this.addJunctionMenuButton) return null;
        const split = document.createElement('div');
        split.className = 'pm-ribbon-split-command';
        split.setAttribute('role', 'group');
        split.setAttribute('aria-label', 'Add operation stage or junction');
        this._decorateRibbonButton(
            this.addJunctionButton,
            'processJunction',
            'Add Junction',
            icons
        );
        this.addJunctionButton.classList.add('pm-ribbon-split-main');
        this.addJunctionMenuButton.className = 'pm-ribbon-split-toggle';
        this.addJunctionMenuButton.textContent = '';
        this.addJunctionMenuButton.setAttribute('aria-haspopup', 'menu');
        this.addJunctionMenuButton.setAttribute('aria-expanded', 'false');
        const caret = document.createElement('span');
        caret.className = 'pm-ribbon-split-caret';
        caret.setAttribute('aria-hidden', 'true');
        this.addJunctionMenuButton.appendChild(caret);
        split.appendChild(this.addJunctionButton);
        split.appendChild(this.addJunctionMenuButton);
        return split;
    };

    ProcessMapEditor.prototype._ribbonGroup = function (label) {
        const group = document.createElement('div');
        group.className = 'ribbon-group pm-ribbon-group';
        group.setAttribute(
            'data-process-map-ribbon-group',
            String(label || '').toLowerCase().replace(/\s+/g, '-')
        );
        const groupLabel = document.createElement('div');
        groupLabel.className = 'ribbon-group-label';
        groupLabel.textContent = label;
        group.appendChild(groupLabel);
        return group;
    };

    ProcessMapEditor.prototype._ribbonSeparator = function () {
        const separator = document.createElement('div');
        separator.className = 'ribbon-sep';
        return separator;
    };

    ProcessMapEditor.prototype.attachRibbon = function (host, ribbonOptions) {
        if (!host || typeof document === 'undefined') return false;
        const options = ribbonOptions || {};
        const icons = options.icons || {};
        this.ribbonIcons = icons;
        host.textContent = '';
        host.className = 'pm-ribbon-surface';
        this.ribbonHost = host;
        this.root.classList.add('pm-external-command-surface');
        if (this.toolbar && this.toolbar.parentNode) this.toolbar.parentNode.removeChild(this.toolbar);

        const mapGroup = this._ribbonGroup('Map');
        mapGroup.classList.add('pm-ribbon-map-group');
        const mapIcon = document.createElement('span');
        mapIcon.className = 'pm-ribbon-map-icon';
        mapIcon.setAttribute('aria-hidden', 'true');
        mapIcon.innerHTML = icons.processMapActions || '';
        const mapCopy = document.createElement('div');
        mapCopy.className = 'pm-ribbon-map-copy';
        mapCopy.appendChild(this.title);
        mapCopy.appendChild(this.subtitle);
        if (this.mapManager) {
            this.mapManager.appendChild(this.status);
            mapGroup.appendChild(mapIcon);
            mapGroup.appendChild(this.mapManager);
        } else {
            mapCopy.insertBefore(mapIcon, mapCopy.firstChild);
            mapCopy.appendChild(this.status);
            mapGroup.appendChild(mapCopy);
        }
        host.appendChild(mapGroup);

        const editing = this._ribbonGroup('Editing');
        this._decorateRibbonButton(this.undoButton, 'processUndo', 'Undo', icons);
        this._decorateRibbonButton(this.redoButton, 'processRedo', 'Redo', icons);
        this._decorateRibbonButton(this.deleteButton, 'processDelete', 'Delete', icons);
        this._decorateRibbonButton(this.clearMapButton, 'processClear', 'Clear Map', icons);
        const groupPicker = this._decorateRibbonPicker(
            this.groupSelect,
            'processSelectGroup',
            'Select Group',
            icons
        );
        if (this.undoButton) editing.appendChild(this.undoButton);
        if (this.redoButton) editing.appendChild(this.redoButton);
        if (this.deleteButton) editing.appendChild(this.deleteButton);
        if (groupPicker) editing.appendChild(groupPicker);
        if (this.clearMapButton) editing.appendChild(this.clearMapButton);
        host.appendChild(this._ribbonSeparator());
        host.appendChild(editing);

        const elements = this._ribbonGroup('Map Elements');
        this._decorateRibbonButton(this.addStepButton, 'processStep', 'Add Step', icons);
        this._decorateRibbonButton(this.addGroupButton, 'processGroup', 'Add Group', icons);
        this._decorateRibbonButton(this.cleanUpButton, 'processCleanUp', 'Clean Map', icons);
        const junctionControl = this._junctionRibbonControl(icons);
        this._decorateRibbonButton(this.suggestionButton, 'processSuggestions', 'Suggestions', icons);
        this._decorateRibbonButton(this.analyzeButton, 'processAnalyze', 'Analyze', icons);
        this._decorateRibbonButton(
            this.analyzeLayoutButton,
            'processAnalyzeLayout',
            'Layout',
            icons
        );
        this._decorateRibbonButton(
            this.reviewKnowledgeButton,
            'processAnalyze',
            'Review',
            icons,
            'assemblyKnowledgeReview'
        );
        if (this.addStepButton) elements.appendChild(this.addStepButton);
        if (this.addGroupButton) elements.appendChild(this.addGroupButton);
        if (this.cleanUpButton) elements.appendChild(this.cleanUpButton);
        if (junctionControl) elements.appendChild(junctionControl);
        if (this.suggestionButton) elements.appendChild(this.suggestionButton);
        if (this.analyzeButton) elements.appendChild(this.analyzeButton);
        if (this.analyzeLayoutButton) elements.appendChild(this.analyzeLayoutButton);
        if (this.reviewKnowledgeButton) elements.appendChild(this.reviewKnowledgeButton);
        host.appendChild(this._ribbonSeparator());
        host.appendChild(elements);

        if (this.stageDetailButton) {
            const stage = this._ribbonGroup('Stage');
            this._decorateRibbonButton(
                this.stageDetailButton,
                'processStep',
                'Open Details',
                icons,
                'openStageDetail'
            );
            stage.appendChild(this.stageDetailButton);
            host.appendChild(this._ribbonSeparator());
            host.appendChild(stage);
        }

        if (this.editable) {
            const configuration = this._ribbonGroup('Node Configuration');
            configuration.classList.add('pm-ribbon-config-group');
            [
                { control: this.typeSelect, label: 'Node Type', iconKey: 'processNodeType' },
                { control: this.portOrientationSelect, label: 'Ports', iconKey: 'processPorts' },
                { control: this.portOrderSelect, label: 'Input', iconKey: 'processInput' },
            ].forEach(function (definition) {
                if (!definition.control) return;
                const field = document.createElement('label');
                field.className = 'pm-ribbon-field';
                const fieldLabel = document.createElement('span');
                fieldLabel.className = 'pm-ribbon-field-label';
                fieldLabel.textContent = definition.label;
                const fieldIcon = document.createElement('span');
                fieldIcon.className = 'pm-ribbon-field-icon';
                fieldIcon.setAttribute('aria-hidden', 'true');
                fieldIcon.innerHTML = icons[definition.iconKey] || '';
                field.appendChild(fieldIcon);
                field.appendChild(fieldLabel);
                field.appendChild(definition.control);
                configuration.appendChild(field);
            });
            host.appendChild(this._ribbonSeparator());
            host.appendChild(configuration);
        }

        const visualization = this._ribbonGroup('Visualization');
        this._decorateRibbonButton(this.zoomOutButton, 'processZoomOut', 'Zoom Out', icons);
        this._decorateRibbonButton(this.zoomInButton, 'processZoomIn', 'Zoom In', icons);
        this._decorateRibbonButton(this.fitButton, 'processFit', 'Fit', icons);
        this._decorateRibbonButton(this.previewButton, 'process3d', '3D', icons, '3dmodel');
        this._decorateRibbonButton(this.backButton, 'processBack', 'Back', icons);
        this.backButton.classList.add('pm-back-button');
        const zoomStack = document.createElement('div');
        zoomStack.className = 'pm-ribbon-zoom-stack';
        this.zoomOutButton.classList.add('pm-ribbon-compact-command');
        this.zoomInButton.classList.add('pm-ribbon-compact-command');
        zoomStack.appendChild(this.zoomInButton);
        zoomStack.appendChild(this.zoomOutButton);
        visualization.appendChild(zoomStack);
        visualization.appendChild(this.fitButton);
        if (this.previewButton) visualization.appendChild(this.previewButton);
        visualization.appendChild(this.backButton);
        host.appendChild(this._ribbonSeparator());
        host.appendChild(visualization);

        if (this.editable) {
            const file = this._ribbonGroup('File');
            this._decorateRibbonButton(this.saveButton, 'processSave', 'Save', icons);
            this._decorateRibbonButton(this.reloadButton, 'processReload', 'Reload', icons);
            file.appendChild(this.saveButton);
            file.appendChild(this.reloadButton);
            host.appendChild(this._ribbonSeparator());
            host.appendChild(file);
        }
        this.updateEditControls();
        return true;
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
                spatialPlacementEnabled: this.spatialPlacementEnabled && !this.placementPlan,
            }
        );
    };

    ProcessMapEditor.prototype.setCapabilities = function (capabilities) {
        const next = capabilities || {};
        const spatialAnalysisEnabled = !!next.spatialAnalysisEnabled;
        const spatialPlacementEnabled = !!next.spatialPlacementEnabled;
        const autoRoutingEnabled = !!next.autoRoutingEnabled;
        const agentLayoutWriteEnabled = !!next.agentLayoutWriteEnabled;
        const managedProposalWriteEnabled = next.managedProposalWriteEnabled === undefined
            ? agentLayoutWriteEnabled
            : !!next.managedProposalWriteEnabled;
        if (this.spatialAnalysisEnabled === spatialAnalysisEnabled
            && this.spatialPlacementEnabled === spatialPlacementEnabled
            && this.autoRoutingEnabled === autoRoutingEnabled
            && this.agentLayoutWriteEnabled === agentLayoutWriteEnabled
            && this.managedProposalWriteEnabled === managedProposalWriteEnabled) return false;
        const routingWasEnabled = this.autoRoutingEnabled;
        this.spatialAnalysisEnabled = spatialAnalysisEnabled;
        this.spatialPlacementEnabled = spatialPlacementEnabled;
        this.autoRoutingEnabled = autoRoutingEnabled;
        this.agentLayoutWriteEnabled = agentLayoutWriteEnabled;
        this.managedProposalWriteEnabled = managedProposalWriteEnabled;
        if (!this.spatialPlacementEnabled) this._clearArrangementPlan();
        this.updateEditControls();
        this._renderManagedProposalReview();
        this.renderGraph({ fit: false });
        if (!routingWasEnabled && this.autoRoutingEnabled
            && mapEdges(this.processMap).some(function (edge) {
                return edge && edge.routing && edge.routing.mode === 'orthogonal_auto';
            })) {
            this._ensureSpatialContract().then(function () {
                if (this.destroyed || !this.autoRoutingEnabled) return;
                const refreshed = this._refreshAutoRoutes(this.processMap);
                if (!refreshed.failures.length
                    && mapFingerprint(refreshed.map) !== mapFingerprint(this.processMap)) {
                    this.processMap = refreshed.map;
                    this._setDirty(mapFingerprint(this.processMap) !== this.savedFingerprint);
                    this._notifyMapChange();
                    this.renderGraph({ fit: false });
                }
            }.bind(this)).catch(function () {});
        }
        return true;
    };

    ProcessMapEditor.prototype._closeCardToolbar = function (reason, restoreFocus) {
        if (!this.cardToolbarManager) return false;
        const closed = this.cardToolbarManager.close(reason || 'programmatic', {
            restoreFocus: restoreFocus !== false,
        });
        if (!closed || !this.cardToolbarManager.isOpen()) {
            this.cardToolbarElement = null;
            this.cardToolbarNodeId = null;
            this.cardToolbarEdgeId = null;
            this.cardToolbarGroupId = null;
            this.cardToolbarOwner = null;
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
        const propertiesButton = toolbar.querySelector('[data-card-command="edit-properties"]');
        const referencesButton = toolbar.querySelector('[data-context-command="references"]');
        const previewButton = toolbar.querySelector('[data-card-command="preview"]');
        const stageDetailButton = toolbar.querySelector(
            '[data-card-command="open-stage-detail"]'
        );
        const deleteButton = toolbar.querySelector('[data-card-command="delete"]');
        if (addSelect) addSelect.disabled = !states.canAddConnectedStep;
        if (labelButton) labelButton.disabled = !states.canEditLabel;
        if (noteButton) {
            noteButton.disabled = !states.canEditNote;
            noteButton.classList.toggle('has-note', !!(states.node && states.node.note));
            noteButton.setAttribute('aria-pressed', !!(states.node && states.node.note) ? 'true' : 'false');
        }
        if (propertiesButton) {
            propertiesButton.disabled = !states.canEditProperties;
            propertiesButton.classList.toggle(
                'has-properties',
                !!(states.node && states.node.properties
                    && Object.keys(states.node.properties).length)
            );
        }
        if (previewButton) previewButton.disabled = !states.canPreview;
        if (stageDetailButton) {
            stageDetailButton.disabled = !this._canOpenStageDetail(states.node);
        }
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

        if (this._canOpenStageDetail(node)) {
            const stageDetailButton = this._cardToolbarButton(
                'Open',
                'Open the evidence-bound detailed process for this stage',
                this.openStageDetail.bind(this, node),
                'pm-card-toolbar-stage-detail'
            );
            stageDetailButton.setAttribute(
                'data-card-command',
                'open-stage-detail'
            );
            toolbar.appendChild(stageDetailButton);
        }

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

        if (states.canEditProperties) {
            const propertiesButton = this._cardToolbarButton(
                'Details',
                'Edit manufacturing details for this process step',
                this._openStagePropertiesEditor.bind(this),
                'pm-card-toolbar-properties'
            );
            propertiesButton.setAttribute('data-card-command', 'edit-properties');
            toolbar.appendChild(propertiesButton);
        }

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

        if (states.canSuggestPosition) {
            const suggestButton = this._cardToolbarButton(
                'Pos',
                'Suggest a clean position for this card',
                this.suggestSelectedNodePlacement.bind(this),
                'pm-card-toolbar-suggest'
            );
            suggestButton.setAttribute('data-card-command', 'suggest-position');
            toolbar.appendChild(suggestButton);
        }

        if (states.canLockPosition || states.canUnlockPosition) {
            const lockButton = this._cardToolbarButton(
                states.positionLocked ? 'Unlock' : 'Lock',
                states.positionLocked ? 'Unlock card position' : 'Lock card position',
                states.positionLocked
                    ? this.unlockSelectedPosition.bind(this)
                    : this.lockSelectedPosition.bind(this),
                'pm-card-toolbar-lock'
            );
            lockButton.setAttribute('data-card-command', states.positionLocked ? 'unlock-position' : 'lock-position');
            toolbar.appendChild(lockButton);
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

        if (this.autoRoutingEnabled) {
            if (this.routePlan && this.routePlan.edgeId === edge.edgeId) {
                const acceptRouteButton = this._cardToolbarButton(
                    'Apply',
                    'Apply the previewed obstacle-aware route',
                    this.acceptRoutePlan.bind(this),
                    'pm-edge-toolbar-route-accept'
                );
                acceptRouteButton.setAttribute('data-card-command', 'accept-route');
                toolbar.appendChild(acceptRouteButton);
                const dismissRouteButton = this._cardToolbarButton(
                    'Cancel',
                    'Discard the route preview',
                    this.dismissRoutePlan.bind(this),
                    'pm-edge-toolbar-route-dismiss'
                );
                dismissRouteButton.setAttribute('data-card-command', 'dismiss-route');
                toolbar.appendChild(dismissRouteButton);
            } else if (edge.routing && (
                edge.routing.mode === 'orthogonal_auto'
                || edge.routing.mode === 'orthogonal_manual'
            )) {
                const curveButton = this._cardToolbarButton(
                    'Curve',
                    'Use a curved Bezier connection',
                    this.useSelectedEdgeCurve.bind(this),
                    'pm-edge-toolbar-curve'
                );
                curveButton.setAttribute('data-card-command', 'curve');
                toolbar.appendChild(curveButton);
            } else {
                const routeButton = this._cardToolbarButton(
                    'Route',
                    'Preview an obstacle-aware orthogonal route',
                    this.previewSelectedEdgeRoute.bind(this),
                    'pm-edge-toolbar-route'
                );
                routeButton.setAttribute('data-card-command', 'route');
                toolbar.appendChild(routeButton);
            }
        }
        if (edge.routing && edge.routing.mode === 'polyline_manual') {
            const curveButton = this._cardToolbarButton(
                'Curve',
                'Use a curved Bezier connection',
                this.useSelectedEdgeCurve.bind(this),
                'pm-edge-toolbar-curve'
            );
            curveButton.setAttribute('data-card-command', 'curve');
            toolbar.appendChild(curveButton);
        } else {
            const sketchButton = this._cardToolbarButton(
                'Sketch',
                'Use a manual route; double-click the line to add fixed points',
                this.useSelectedEdgeManual.bind(this),
                'pm-edge-toolbar-sketch'
            );
            sketchButton.setAttribute('data-card-command', 'sketch');
            toolbar.appendChild(sketchButton);
        }

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
        this.cardToolbarOwner = 'group';
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
                    this.cardToolbarOwner = null;
                }
            }.bind(this),
        });
        if (!opened) {
            toolbar.remove();
            this.cardToolbarElement = null;
            this.cardToolbarGroupId = null;
            this.cardToolbarOwner = null;
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
        this.cardToolbarOwner = 'edge';
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
                    this.cardToolbarOwner = null;
                }
            }.bind(this),
        });
        if (!opened) {
            toolbar.remove();
            this.cardToolbarElement = null;
            this.cardToolbarEdgeId = null;
            this.cardToolbarOwner = null;
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
        toolbar.classList.remove('editing-stage-properties');
        if (restoreFocus !== false) {
            let command = 'edit-label';
            if (mode === 'note') command = 'edit-note';
            else if (mode === 'stage-properties') command = 'edit-properties';
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
            const demo = reference.demoData === true
                ? document.createElement('span')
                : null;
            if (demo) {
                row.classList.add('has-demo');
                demo.className = 'pm-reference-demo';
                demo.textContent = 'Demo';
                demo.title = 'Illustrative demo data; verify before production use';
            }
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
            if (demo) row.appendChild(demo);
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
        this.cardToolbarOwner = 'node';
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
                    this.cardToolbarOwner = null;
                }
            }.bind(this),
        });
        if (!opened) {
            toolbar.remove();
            this.cardToolbarElement = null;
            this.cardToolbarNodeId = null;
            this.cardToolbarGroupId = null;
            this.cardToolbarEdgeId = null;
            this.cardToolbarOwner = null;
        }
        return opened;
    };

    ProcessMapEditor.prototype._syncCardToolbar = function () {
        if (!this.cardToolbarManager || !this.cardToolbarManager.isOpen()) return false;
        if (this.cardToolbarOwner === 'placement') return false;
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

    ProcessMapEditor.prototype.getAgentFocus = function () {
        if (!this.agentFocus) return null;
        return Object.assign({}, cloneMap(this.agentFocus), {
            mapId: String(this.processMap && this.processMap.mapId || 'default'),
            revision: String(this.revision || 'unsaved'),
        });
    };

    ProcessMapEditor.prototype._notifyAgentFocusChange = function () {
        if (typeof this.options.onAgentFocusChange !== 'function') return;
        const focus = this.getAgentFocus();
        this.options.onAgentFocusChange(focus ? cloneMap(focus) : null);
    };

    ProcessMapEditor.prototype._renderAgentFocusBanner = function () {
        if (!this.agentFocusBanner || !this.agentFocusCopy) return;
        const focus = this.agentFocus;
        this.agentFocusBanner.hidden = !focus;
        if (!focus) {
            this.agentFocusCopy.textContent = '';
            this.agentFocusBanner.removeAttribute('title');
            return;
        }
        const nodeCount = focus.nodeIds.length;
        const edgeCount = focus.edgeIds.length;
        const targetCount = Array.isArray(focus.targets)
            ? focus.targets.length
            : Math.max(1, focus.targetNodeIds.length);
        const targetLabels = Array.isArray(focus.labels)
            ? focus.labels.filter(Boolean)
            : [];
        const label = focus.label || (
            focus.targetNodeIds.length
                ? String(
                    (resolveCanvasNode(
                        mapNodes(this.processMap).find(function (node) {
                            return node && node.nodeId === focus.targetNodeIds[0];
                        }),
                        this.occurrenceById
                    ) || {}).name || focus.targetNodeIds[0]
                )
                : 'Requested scope'
        );
        this.agentFocusBanner.title = targetLabels.length
            ? targetLabels.join(' | ') : label;
        if (targetCount > 1) {
            this.agentFocusCopy.textContent = targetCount + ' scopes | '
                + nodeCount + ' card' + (nodeCount === 1 ? '' : 's')
                + ' | ' + edgeCount + ' route' + (edgeCount === 1 ? '' : 's');
            return;
        }
        if (focus.resolution === 'placed_scope_members') {
            this.agentFocusCopy.textContent = label + ' card is not placed; showing '
                + nodeCount + ' placed member' + (nodeCount === 1 ? '' : 's') + '.';
            return;
        }
        this.agentFocusCopy.textContent = label + ' | ' + nodeCount + ' card'
            + (nodeCount === 1 ? '' : 's') + ' | ' + edgeCount + ' route'
            + (edgeCount === 1 ? '' : 's');
    };

    ProcessMapEditor.prototype._applyAgentFocusClasses = function () {
        if (!this.root || !this.nodeLayer || !this.edgeSvg) return;
        const focus = this.agentFocus;
        const focusedNodes = new Set(focus ? focus.nodeIds : []);
        const targetNodes = new Set(focus ? focus.targetNodeIds : []);
        const focusedEdges = new Set(focus ? focus.edgeIds : []);
        const dimOthers = !!(focus && focus.dimOthers);
        this.root.classList.toggle('agent-focus-active', !!focus);
        Array.prototype.forEach.call(
            this.nodeLayer.querySelectorAll('.pm-node, .pm-junction'),
            function (node) {
                const nodeId = node.getAttribute('data-node-id');
                const target = !!focus && targetNodes.has(nodeId);
                const upstream = !!focus && focusedNodes.has(nodeId) && !target;
                const muted = dimOthers && !target && !upstream;
                node.classList.toggle('agent-focus-target', target);
                node.classList.toggle('agent-focus-upstream', upstream);
                node.classList.toggle('agent-focus-muted', muted);
                if (target) node.setAttribute('aria-current', 'true');
                else node.removeAttribute('aria-current');
            }
        );
        Array.prototype.forEach.call(
            this.edgeSvg.querySelectorAll('.pm-edge[data-edge-id]'),
            function (edge) {
                const focused = !!focus
                    && focusedEdges.has(edge.getAttribute('data-edge-id'));
                edge.classList.toggle('agent-focus-route', focused);
                edge.classList.toggle('agent-focus-muted', dimOthers && !focused);
            }
        );
        Array.prototype.forEach.call(
            this.edgeSvg.querySelectorAll('.pm-edge-context-label'),
            function (label) {
                const focused = !!focus && focusedEdges.has(
                    label.getAttribute('data-edge-context-id')
                );
                label.classList.toggle('agent-focus-route', focused);
                label.classList.toggle('agent-focus-muted', dimOthers && !focused);
            }
        );
        this._renderAgentFocusBanner();
    };

    ProcessMapEditor.prototype._refreshAgentFocus = function () {
        if (!this.agentFocusRequest) {
            this.agentFocus = null;
            return null;
        }
        const refreshed = resolveProcessMapFocus(
            this.processMap,
            this.agentFocusRequest,
            this.productStructure
        );
        if (!refreshed) {
            this.agentFocusRequest = null;
            this.agentFocus = null;
            this._notifyAgentFocusChange();
            return null;
        }
        this.agentFocus = refreshed;
        return refreshed;
    };

    ProcessMapEditor.prototype.fitAgentFocus = function () {
        if (this.destroyed || !this.viewport || !this.agentFocus) return false;
        const positions = {};
        this.agentFocus.nodeIds.forEach(function (nodeId) {
            const position = this.positions && this.positions[nodeId];
            if (!position) return;
            positions[nodeId] = position.isJunction
                ? Object.assign({}, position, {
                    x: position.x - JUNCTION_HIT_SIZE / 2,
                    y: position.y - JUNCTION_HIT_SIZE / 2,
                    width: JUNCTION_HIT_SIZE,
                    height: JUNCTION_HIT_SIZE,
                })
                : position;
        }, this);
        const geometries = this.agentFocus.edgeIds.map(function (edgeId) {
            return this.edgeGeometries && this.edgeGeometries[edgeId];
        }, this).filter(Boolean);
        const bounds = graphBounds(positions, [], geometries);
        const rect = this.viewport.getBoundingClientRect();
        if (!rect.width || !rect.height) return false;
        const margin = 72;
        const scale = clamp(
            Math.min(
                (rect.width - margin * 2) / Math.max(1, bounds.width),
                (rect.height - margin * 2) / Math.max(1, bounds.height)
            ),
            MIN_SCALE,
            1.15
        );
        this.transform.scale = scale;
        this.transform.x = (rect.width - bounds.width * scale) / 2 - bounds.x * scale;
        this.transform.y = (rect.height - bounds.height * scale) / 2 - bounds.y * scale;
        this.applyTransform();
        return true;
    };

    ProcessMapEditor.prototype.setAgentFocus = function (value) {
        const request = normalizeAgentFocusRequest(value);
        const resolved = request
            ? resolveProcessMapFocus(this.processMap, request, this.productStructure)
            : null;
        if (!request || !resolved) {
            this.operationError = 'The requested card is not placed on this Process Map.';
            this.updateEditControls();
            return false;
        }
        this.agentFocusRequest = request;
        this.agentFocus = resolved;
        this.operationError = '';
        this._applyAgentFocusClasses();
        this._notifyAgentFocusChange();
        this.updateEditControls();
        if (request.fitView) {
            const schedule = typeof requestAnimationFrame === 'function'
                ? requestAnimationFrame
                : function (callback) { return setTimeout(callback, 0); };
            schedule(this.fitAgentFocus.bind(this));
        }
        return true;
    };

    ProcessMapEditor.prototype.clearAgentFocus = function () {
        this.agentFocusRequest = null;
        this.agentFocus = null;
        this._applyAgentFocusClasses();
        this._notifyAgentFocusChange();
        return true;
    };

    ProcessMapEditor.prototype.getRequiredOccurrenceSelection = function () {
        const selection = this.requiredOccurrenceSelection;
        if (!selection) return null;
        const placed = this._placedOccurrenceIds();
        const required = selection.requiredOccurrenceIds.slice();
        const placedCount = required.filter(function (occurrenceId) {
            return placed.has(occurrenceId);
        }).length;
        return {
            scopeOccurrenceId: selection.scopeOccurrenceId,
            scopeName: selection.scopeName,
            label: selection.label,
            requiredOccurrenceIds: required,
            currentOccurrenceId: selection.currentOccurrenceId,
            total: required.length,
            placed: placedCount,
            remaining: required.length - placedCount,
        };
    };

    ProcessMapEditor.prototype._notifyRequiredOccurrenceSelectionChange = function () {
        if (typeof this.options.onRequiredOccurrenceSelectionChange !== 'function') return;
        const selection = this.getRequiredOccurrenceSelection();
        this.options.onRequiredOccurrenceSelectionChange(
            selection ? JSON.parse(JSON.stringify(selection)) : null
        );
    };

    ProcessMapEditor.prototype._scrollToRequiredOccurrence = function (occurrenceId) {
        if (!this.structureTree || !occurrenceId) return;
        const schedule = typeof requestAnimationFrame === 'function'
            ? requestAnimationFrame
            : function (callback) { return setTimeout(callback, 0); };
        schedule(function () {
            if (!this.structureTree) return;
            const rows = this.structureTree.querySelectorAll('[data-occurrence-id]');
            const row = Array.prototype.find.call(rows, function (item) {
                return item.getAttribute('data-occurrence-id') === occurrenceId;
            });
            if (row && typeof row.scrollIntoView === 'function') {
                row.scrollIntoView({ block: 'nearest' });
            }
        }.bind(this));
    };

    ProcessMapEditor.prototype.setRequiredOccurrenceScope = function (scopeOccurrenceId, label) {
        const selection = normalizeRequiredOccurrenceSelection(this.productStructure, {
            scopeOccurrenceId: scopeOccurrenceId,
            label: label,
        });
        if (!selection) return false;
        if (this.batchPlacementPlan) this._clearPlacementPlan();
        this.requiredOccurrenceSelection = selection;
        this.agentExpandedOccurrenceIds = new Set(selection.expandedOccurrenceIds);
        this.requiredOccurrenceIds = new Set(selection.requiredOccurrenceIds);
        if (this.treeFilter) {
            this.treeFilter = '';
            if (this.treeSearch) this.treeSearch.value = '';
        }
        if (this.structureCollapsed) this.setStructureCollapsed(false);
        this.renderStructureTree();
        this._notifyRequiredOccurrenceSelectionChange();
        this._scrollToRequiredOccurrence(selection.currentOccurrenceId);
        return true;
    };

    ProcessMapEditor.prototype.clearRequiredOccurrenceScope = function () {
        if (this.batchPlacementPlan) this._clearPlacementPlan();
        this.requiredOccurrenceSelection = null;
        this.agentExpandedOccurrenceIds.clear();
        this.requiredOccurrenceIds.clear();
        this.renderStructureTree();
        this._notifyRequiredOccurrenceSelectionChange();
        return true;
    };

    ProcessMapEditor.prototype.focusRequiredOccurrence = function (direction) {
        const selection = this.requiredOccurrenceSelection;
        if (!selection || !selection.requiredOccurrenceIds.length) return false;
        const placed = this._placedOccurrenceIds();
        const remaining = selection.requiredOccurrenceIds.filter(function (occurrenceId) {
            return !placed.has(occurrenceId);
        });
        const candidates = remaining.length ? remaining : selection.requiredOccurrenceIds;
        const currentIndex = candidates.indexOf(selection.currentOccurrenceId);
        const delta = Number(direction) < 0 ? -1 : 1;
        const nextIndex = currentIndex < 0
            ? 0
            : (currentIndex + delta + candidates.length) % candidates.length;
        selection.currentOccurrenceId = candidates[nextIndex];
        this.renderStructureTree();
        this._notifyRequiredOccurrenceSelectionChange();
        this._scrollToRequiredOccurrence(selection.currentOccurrenceId);
        return true;
    };

    ProcessMapEditor.prototype._renderRequiredOccurrenceSummary = function () {
        if (!this.requiredSummary) return;
        const state = this.getRequiredOccurrenceSelection();
        this.requiredSummary.hidden = !state;
        if (!state) return;
        this.requiredSummaryTitle.textContent = state.label;
        this.requiredSummaryProgress.textContent = state.placed + ' of ' + state.total
            + ' added to the process map; ' + state.remaining + ' remaining';
        const multiple = state.total > 1;
        this.requiredPreviousButton.disabled = !multiple;
        this.requiredNextButton.disabled = !multiple;
        this.requiredArrangeButton.disabled = !this.spatialPlacementEnabled
            || state.remaining < 1 || !!this.placementPlan || !!this.batchPlacementPlan;
        this.requiredSummary.setAttribute('data-required-total', String(state.total));
        this.requiredSummary.setAttribute('data-required-placed', String(state.placed));
        this.requiredSummary.setAttribute('data-required-remaining', String(state.remaining));
    };

    ProcessMapEditor.prototype._placedOccurrenceIds = function () {
        return new Set(mapNodes(this.processMap).filter(function (node) {
            return node && node.nodeKind === 'product_occurrence' && node.sourceOccurrenceId;
        }).map(function (node) { return node.sourceOccurrenceId; }));
    };

    ProcessMapEditor.prototype._updateStructureSelectionHint = function () {
        if (!this.structureHint) return;
        const count = this.selectedOccurrenceIds.size;
        if (count > 1) {
            this.structureHint.textContent = count
                + ' items selected - drag any selected item into the map';
        } else if (count === 1) {
            this.structureHint.textContent = '1 item selected - Ctrl-click to add more';
        } else {
            this.structureHint.textContent = 'Ctrl-click to select multiple, then drag into the map';
        }
    };

    ProcessMapEditor.prototype._syncStructureSelectionRows = function () {
        if (!this.structureTree) return;
        Array.prototype.forEach.call(
            this.structureTree.querySelectorAll('.pm-tree-row[data-occurrence-id]'),
            function (row) {
                const selected = this.selectedOccurrenceIds.has(
                    row.getAttribute('data-occurrence-id')
                );
                row.classList.toggle('selected', selected);
                row.setAttribute('aria-selected', selected ? 'true' : 'false');
            }.bind(this)
        );
        this._updateStructureSelectionHint();
    };

    ProcessMapEditor.prototype._setOccurrenceSelection = function (
        occurrenceId,
        additive
    ) {
        if (!this.occurrenceById.has(occurrenceId)) return false;
        if (additive) {
            if (this.selectedOccurrenceIds.has(occurrenceId)) {
                this.selectedOccurrenceIds.delete(occurrenceId);
            } else if (this.selectedOccurrenceIds.size < MAX_TREE_MULTI_DRAG_ITEMS) {
                this.selectedOccurrenceIds.add(occurrenceId);
            }
        } else {
            this.selectedOccurrenceIds = new Set([occurrenceId]);
        }
        this._syncStructureSelectionRows();
        return this.selectedOccurrenceIds.has(occurrenceId);
    };

    ProcessMapEditor.prototype._selectedOccurrencesInTreeOrder = function (originOccurrenceId) {
        if (!this.selectedOccurrenceIds.has(originOccurrenceId)) {
            this.selectedOccurrenceIds = new Set([originOccurrenceId]);
            this._syncStructureSelectionRows();
        }
        const ordered = [];
        const visit = function (occurrence) {
            if (!occurrence) return;
            if (this.selectedOccurrenceIds.has(occurrence.occurrenceId)) {
                ordered.push(occurrence.occurrenceId);
            }
            (this.occurrenceChildren.get(occurrence.occurrenceId) || []).forEach(visit);
        }.bind(this);
        (this.occurrenceChildren.get(null) || []).forEach(visit);
        return ordered.slice(0, MAX_TREE_MULTI_DRAG_ITEMS);
    };

    ProcessMapEditor.prototype._removeTreeDragPreview = function () {
        if (this.treeDragPreviewElement && this.treeDragPreviewElement.parentNode) {
            this.treeDragPreviewElement.parentNode.removeChild(this.treeDragPreviewElement);
        }
        this.treeDragPreviewElement = null;
        if (!this.structureTree) return;
        Array.prototype.forEach.call(
            this.structureTree.querySelectorAll('.pm-tree-row.drag-source'),
            function (row) { row.classList.remove('drag-source'); }
        );
    };

    ProcessMapEditor.prototype._setTreeDragPreview = function (event, occurrenceIds) {
        this._removeTreeDragPreview();
        if (!event.dataTransfer || occurrenceIds.length < 2) return;
        const preview = document.createElement('div');
        preview.className = 'pm-tree-drag-preview';
        preview.setAttribute('data-tree-drag-count', String(occurrenceIds.length));
        const stack = document.createElement('span');
        stack.className = 'pm-tree-drag-preview-stack';
        stack.setAttribute('aria-hidden', 'true');
        const label = document.createElement('span');
        label.textContent = occurrenceIds.length + ' items';
        preview.appendChild(stack);
        preview.appendChild(label);
        document.body.appendChild(preview);
        this.treeDragPreviewElement = preview;
        try { event.dataTransfer.setDragImage(preview, 18, 18); } catch (_) {}
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
        const placed = this._placedOccurrenceIds();
        this._renderRequiredOccurrenceSummary();
        const roots = this.occurrenceChildren.get(null) || [];
        if (!roots.length) {
            const empty = document.createElement('div');
            empty.className = 'pm-tree-empty';
            empty.textContent = 'No product structure is available.';
            this.structureTree.appendChild(empty);
            return;
        }
        const filterMemo = new Map();
        roots.forEach(function (occurrence) {
            this._renderStructureOccurrence(occurrence, 0, placed, filterMemo);
        }, this);
        this._updateStructureSelectionHint();
    };

    ProcessMapEditor.prototype._renderStructureOccurrence = function (
        occurrence,
        depth,
        placed,
        filterMemo
    ) {
        if (!this._occurrenceMatchesFilter(occurrence, filterMemo)) return;
        const children = this.occurrenceChildren.get(occurrence.occurrenceId) || [];
        const selection = this.requiredOccurrenceSelection;
        const isRequired = !!selection
            && this.requiredOccurrenceIds.has(occurrence.occurrenceId);
        const isRequiredPlaced = isRequired && placed.has(occurrence.occurrenceId);
        const requiredChildCount = selection
            ? Number(selection.parentMatchCounts[occurrence.occurrenceId] || 0)
            : 0;
        const expanded = !!this.treeFilter
            || this.expandedOccurrenceIds.has(occurrence.occurrenceId)
            || this.agentExpandedOccurrenceIds.has(occurrence.occurrenceId);
        const row = document.createElement('div');
        const rowClasses = ['pm-tree-row'];
        if (this.selectedOccurrenceIds.has(occurrence.occurrenceId)) rowClasses.push('selected');
        if (placed.has(occurrence.occurrenceId)) rowClasses.push('placed');
        if (isRequired && !isRequiredPlaced) rowClasses.push('agent-required');
        if (isRequiredPlaced) rowClasses.push('agent-required-complete');
        if (requiredChildCount) rowClasses.push('agent-required-parent');
        if (selection && selection.currentOccurrenceId === occurrence.occurrenceId) {
            rowClasses.push('agent-required-current');
        }
        row.className = rowClasses.join(' ');
        row.setAttribute('role', 'treeitem');
        row.setAttribute('data-occurrence-id', occurrence.occurrenceId);
        row.setAttribute('data-product-kind', occurrence.kind || 'part');
        row.setAttribute(
            'aria-selected',
            this.selectedOccurrenceIds.has(occurrence.occurrenceId) ? 'true' : 'false'
        );
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
        if (isRequired && !isRequiredPlaced) {
            const badge = document.createElement('span');
            badge.className = 'pm-tree-required';
            badge.textContent = 'Required';
            row.appendChild(badge);
        } else if (isRequiredPlaced) {
            const badge = document.createElement('span');
            badge.className = 'pm-tree-required-complete';
            badge.textContent = 'Added';
            row.appendChild(badge);
        } else if (requiredChildCount) {
            const badge = document.createElement('span');
            badge.className = 'pm-tree-required-count';
            badge.textContent = String(requiredChildCount);
            badge.title = requiredChildCount + ' required part'
                + (requiredChildCount === 1 ? '' : 's') + ' in this branch';
            row.appendChild(badge);
        } else if (placed.has(occurrence.occurrenceId)) {
            const badge = document.createElement('span');
            badge.className = 'pm-tree-placed';
            badge.textContent = 'Placed';
            row.appendChild(badge);
        }

        if (this.editable && this.spatialPlacementEnabled && !placed.has(occurrence.occurrenceId)) {
            const suggestButton = document.createElement('button');
            suggestButton.type = 'button';
            suggestButton.className = 'pm-tree-suggest-position';
            suggestButton.textContent = 'Pos';
            suggestButton.title = 'Suggest a clean position for this item';
            suggestButton.setAttribute('aria-label', 'Suggest a position for ' + (occurrence.name || occurrence.occurrenceId));
            suggestButton.addEventListener('pointerdown', function (event) { event.stopPropagation(); });
            suggestButton.addEventListener('dragstart', function (event) {
                event.preventDefault();
                event.stopPropagation();
            });
            suggestButton.addEventListener('click', function (event) {
                event.preventDefault();
                event.stopPropagation();
                this.previewOccurrencePlacement(occurrence.occurrenceId);
            }.bind(this));
            row.appendChild(suggestButton);
        }

        row.addEventListener('click', function (event) {
            const selected = this._setOccurrenceSelection(
                occurrence.occurrenceId,
                !!(event.ctrlKey || event.metaKey)
            );
            if (selected && typeof this.options.onSourceSelect === 'function') {
                this.options.onSourceSelect(occurrence.occurrenceId, occurrence);
            }
        }.bind(this));
        row.addEventListener('keydown', function (event) {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            event.stopPropagation();
            const selected = this._setOccurrenceSelection(
                occurrence.occurrenceId,
                !!(event.ctrlKey || event.metaKey)
            );
            if (selected && typeof this.options.onSourceSelect === 'function') {
                this.options.onSourceSelect(occurrence.occurrenceId, occurrence);
            }
        }.bind(this));
        if (this.editable) {
            row.draggable = true;
            row.title = 'Drag into the process map';
            row.addEventListener('dragstart', function (event) {
                if (!event.dataTransfer) return;
                const occurrenceIds = this._selectedOccurrencesInTreeOrder(
                    occurrence.occurrenceId
                );
                event.dataTransfer.effectAllowed = 'copy';
                event.dataTransfer.setData(
                    'application/x-inspectorpro-occurrences',
                    JSON.stringify(occurrenceIds)
                );
                event.dataTransfer.setData(
                    'application/x-inspectorpro-occurrence',
                    occurrence.occurrenceId
                );
                event.dataTransfer.setData('text/plain', occurrence.occurrenceId);
                this._setTreeDragPreview(event, occurrenceIds);
                Array.prototype.forEach.call(
                    this.structureTree.querySelectorAll('.pm-tree-row[data-occurrence-id]'),
                    function (item) {
                        item.classList.toggle(
                            'drag-source',
                            occurrenceIds.indexOf(item.getAttribute('data-occurrence-id')) >= 0
                        );
                    }
                );
            }.bind(this));
            row.addEventListener('dragend', this._removeTreeDragPreview.bind(this));
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
        this._removeTreeDragPreview();
        if (!this.editable || this.conflict || !event.dataTransfer) return false;
        let occurrenceIds = [];
        const multiPayload = event.dataTransfer.getData(
            'application/x-inspectorpro-occurrences'
        );
        if (multiPayload) {
            try {
                const parsed = JSON.parse(multiPayload);
                if (Array.isArray(parsed)) occurrenceIds = parsed;
            } catch (_) {}
        }
        const occurrenceId = event.dataTransfer.getData('application/x-inspectorpro-occurrence')
            || event.dataTransfer.getData('text/plain');
        if (!occurrenceIds.length && occurrenceId) occurrenceIds = [occurrenceId];
        if (occurrenceIds.length <= 1) {
            return this.addOccurrenceAt(occurrenceIds[0], event.clientX, event.clientY);
        }
        return this.addOccurrencesAt(occurrenceIds, event.clientX, event.clientY);
    };

    ProcessMapEditor.prototype.addOccurrencesAt = function (
        occurrenceIds,
        clientX,
        clientY
    ) {
        if (!this.editable || this.conflict || !isPlacementMap(this.processMap)) return false;
        const uniqueIds = [];
        const seen = new Set();
        (Array.isArray(occurrenceIds) ? occurrenceIds : []).forEach(function (value) {
            const occurrenceId = String(value || '').trim();
            if (!occurrenceId || seen.has(occurrenceId)
                || !this.occurrenceById.has(occurrenceId)
                || uniqueIds.length >= MAX_TREE_MULTI_DRAG_ITEMS) return;
            seen.add(occurrenceId);
            uniqueIds.push(occurrenceId);
        }, this);
        if (!uniqueIds.length) return false;

        const existingByOccurrence = new Map();
        mapNodes(this.processMap).forEach(function (node) {
            if (node && node.nodeKind === 'product_occurrence' && node.sourceOccurrenceId) {
                existingByOccurrence.set(node.sourceOccurrenceId, node.nodeId);
            }
        });
        const entries = uniqueIds.filter(function (occurrenceId) {
            return !existingByOccurrence.has(occurrenceId);
        }).map(function (occurrenceId) {
            const occurrence = this.occurrenceById.get(occurrenceId);
            return {
                nodeId: this._freshPlacementNodeId(),
                sourceOccurrenceId: occurrenceId,
                nameSnapshot: occurrence.name || occurrenceId,
                itemIdSnapshot: occurrence.itemId || null,
            };
        }, this);
        const world = this.clientToWorld(clientX, clientY);
        const result = addOccurrenceBatch(this.processMap, {
            entries: entries,
            dropPoint: world,
            visibleWorldRect: this._visibleWorldRect(),
        });
        if (!result.addedNodeIds.length) {
            const existingNodeIds = uniqueIds.map(function (occurrenceId) {
                return existingByOccurrence.get(occurrenceId);
            }).filter(Boolean);
            if (existingNodeIds.length) {
                this.setGraphSelection(existingNodeIds, []);
                existingNodeIds.forEach(function (nodeId) {
                    const wrapper = this.nodeLayer.querySelector(
                        '[data-node-id="' + nodeId + '"]'
                    );
                    if (!wrapper) return;
                    wrapper.classList.remove('duplicate-pulse');
                    void wrapper.offsetWidth;
                    wrapper.classList.add('duplicate-pulse');
                }, this);
                this.operationError = existingNodeIds.length === 1
                    ? 'This product occurrence is already on the map.'
                    : 'These product occurrences are already on the map.';
            } else {
                this.operationError = result.reason === 'no_open_batch_position'
                    ? 'No clear area was found for this group of cards.'
                    : 'The selected product occurrences could not be added.';
            }
            this.updateEditControls();
            return false;
        }
        if (!this.commitMutation(result.map)) return false;
        const selectedNodeIds = mapNodes(this.processMap).filter(function (node) {
            return node && node.nodeKind === 'product_occurrence'
                && uniqueIds.indexOf(node.sourceOccurrenceId) >= 0;
        }).map(function (node) { return node.nodeId; });
        this.setGraphSelection(selectedNodeIds, []);
        return true;
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
            positionMode: 'manual',
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
        const addOptions = arguments.length > 1 && arguments[1] ? arguments[1] : {};
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
            name: String(addOptions.name || ('New ' + label)).trim().slice(0, MAX_NODE_LABEL_LENGTH),
            description: '',
            positionMode: 'manual',
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

    ProcessMapEditor.prototype._rememberJunctionType = function (junctionType) {
        if (JUNCTION_INSERT_TYPES.indexOf(junctionType) < 0) return false;
        this.lastJunctionType = junctionType;
        try {
            window.localStorage.setItem('inspectorpro.processMap.lastJunctionType', junctionType);
        } catch (_error) {}
        return true;
    };

    ProcessMapEditor.prototype._openStagePropertiesEditor = function () {
        const states = this.selectedNodeCommandStates();
        if (!states.canEditProperties || !this.cardToolbarElement) return false;
        const editor = this.cardToolbarElement.querySelector('.pm-card-toolbar-editor');
        if (!editor) return false;
        editor.innerHTML = '';
        editor.hidden = false;
        editor.setAttribute('data-editor-mode', 'stage-properties');
        editor.setAttribute('aria-label', 'Edit manufacturing details');
        this.cardToolbarElement.classList.add('editing', 'editing-stage-properties');
        const fields = {};
        const current = states.node.properties && typeof states.node.properties === 'object'
            ? states.node.properties
            : {};
        const grid = document.createElement('div');
        grid.className = 'pm-stage-properties-grid';
        PROCESS_STEP_PROPERTY_FIELDS.forEach(function (definition) {
            const label = document.createElement('label');
            label.className = 'pm-stage-property-field';
            const copy = document.createElement('span');
            copy.textContent = definition.label;
            const field = document.createElement(definition.multiline ? 'textarea' : 'input');
            field.className = 'pm-card-toolbar-field';
            field.maxLength = definition.maximum;
            field.value = typeof current[definition.key] === 'string' ? current[definition.key] : '';
            field.setAttribute('data-stage-property', definition.key);
            field.setAttribute('aria-label', definition.label);
            if (definition.placeholder) field.placeholder = definition.placeholder;
            if (definition.multiline) field.rows = definition.key === 'description' ? 2 : 1;
            label.appendChild(copy);
            label.appendChild(field);
            grid.appendChild(label);
            fields[definition.key] = field;
        });
        editor.appendChild(grid);
        const hint = document.createElement('p');
        hint.className = 'pm-stage-properties-hint';
        hint.textContent = 'Machines, tools, requirements, and standards are managed with Refs.';
        editor.appendChild(hint);
        const actions = document.createElement('div');
        actions.className = 'pm-card-toolbar-editor-actions';
        const cancel = this._button('Cancel', 'Cancel manufacturing detail edits', function () {
            this._closeCardTextEditor(true);
        }.bind(this));
        const save = this._button('Save', 'Save manufacturing details', function () {
            const properties = {};
            PROCESS_STEP_PROPERTY_FIELDS.forEach(function (definition) {
                properties[definition.key] = fields[definition.key].value;
            });
            this._closeCardTextEditor(false);
            this.applyProcessStepProperties(properties);
        }.bind(this));
        cancel.classList.add('pm-card-editor-cancel');
        save.classList.add('pm-card-editor-save');
        actions.appendChild(cancel);
        actions.appendChild(save);
        editor.appendChild(actions);
        grid.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                cancel.click();
            } else if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                save.click();
            }
        });
        if (this.cardToolbarManager) this.cardToolbarManager.reposition();
        const first = grid.querySelector('textarea, input');
        if (first) first.focus();
        return true;
    };

    ProcessMapEditor.prototype.addJunctionChoice = function (junctionType) {
        if (!this._rememberJunctionType(junctionType)) return false;
        this.closeJunctionMenu();
        if (junctionType === 'operation_stage') {
            return this.addProcessStep('operation', { name: 'New Operation / Stage' });
        }
        if (!this.editable || this.conflict || !isPlacementMap(this.processMap)
            || JUNCTION_TYPES.indexOf(junctionType) < 0) return false;
        const rect = this.viewport.getBoundingClientRect();
        const center = this.clientToWorld(rect.left + rect.width / 2, rect.top + rect.height / 2);
        let nodeId;
        do {
            nodeId = 'pm-j-' + Date.now().toString(36) + '-' + (++this.nodeCounter);
        } while (mapNodes(this.processMap).some(function (node) { return node.nodeId === nodeId; }));
        let nextMap = addJunctionNode(this.processMap, {
            nodeId: nodeId,
            junctionType: junctionType,
            position: center,
        });
        nextMap = resolveNodeGroupMembership(nextMap, nodeId, center);
        const changed = this.commitMutation(nextMap);
        if (changed) this.select(nodeId);
        return changed;
    };

    ProcessMapEditor.prototype.closeJunctionMenu = function (restoreFocus) {
        const menu = this.junctionMenuElement;
        if (!menu) return false;
        this.junctionMenuElement = null;
        if (this.junctionMenuOutsideHandler) {
            document.removeEventListener('pointerdown', this.junctionMenuOutsideHandler, true);
            this.junctionMenuOutsideHandler = null;
        }
        if (this.junctionMenuKeyHandler) {
            document.removeEventListener('keydown', this.junctionMenuKeyHandler, true);
            this.junctionMenuKeyHandler = null;
        }
        menu.remove();
        if (this.addJunctionMenuButton) {
            this.addJunctionMenuButton.setAttribute('aria-expanded', 'false');
            if (restoreFocus && typeof this.addJunctionMenuButton.focus === 'function') {
                this.addJunctionMenuButton.focus();
            }
        }
        return true;
    };

    ProcessMapEditor.prototype.toggleJunctionMenu = function (event) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        if (this.junctionMenuElement) return this.closeJunctionMenu(true);
        if (!this.addJunctionMenuButton || this.addJunctionMenuButton.disabled) return false;
        const menu = document.createElement('div');
        menu.className = 'pm-junction-menu';
        menu.setAttribute('role', 'menu');
        menu.setAttribute('aria-label', 'Operation stage and junction types');
        JUNCTION_INSERT_TYPES.forEach(function (junctionType) {
            const definition = JUNCTION_DEFINITIONS[junctionType];
            const item = document.createElement('button');
            item.type = 'button';
            item.className = 'pm-junction-menu-item';
            item.setAttribute('role', 'menuitem');
            item.setAttribute('data-junction-type', junctionType);
            const icon = document.createElement('span');
            icon.className = 'pm-junction-menu-icon';
            icon.setAttribute('aria-hidden', 'true');
            icon.innerHTML = this.ribbonIcons && this.ribbonIcons[definition.iconKey]
                ? this.ribbonIcons[definition.iconKey]
                : '';
            const copy = document.createElement('span');
            copy.className = 'pm-junction-menu-copy';
            const label = document.createElement('strong');
            label.textContent = definition.label;
            const description = document.createElement('small');
            description.textContent = definition.description;
            copy.appendChild(label);
            copy.appendChild(description);
            item.appendChild(icon);
            item.appendChild(copy);
            if (junctionType === this.lastJunctionType) item.classList.add('last-used');
            item.addEventListener('click', function () {
                this.addJunctionChoice(junctionType);
            }.bind(this));
            menu.appendChild(item);
        }, this);
        document.body.appendChild(menu);
        const anchor = this.addJunctionMenuButton.getBoundingClientRect();
        const menuRect = menu.getBoundingClientRect();
        const left = Math.max(8, Math.min(anchor.right - menuRect.width, window.innerWidth - menuRect.width - 8));
        const top = Math.min(anchor.bottom + 5, window.innerHeight - menuRect.height - 8);
        menu.style.left = Math.round(left) + 'px';
        menu.style.top = Math.round(Math.max(8, top)) + 'px';
        this.junctionMenuElement = menu;
        this.addJunctionMenuButton.setAttribute('aria-expanded', 'true');
        this.junctionMenuOutsideHandler = function (outsideEvent) {
            if (menu.contains(outsideEvent.target)
                || this.addJunctionMenuButton.contains(outsideEvent.target)) return;
            this.closeJunctionMenu(false);
        }.bind(this);
        this.junctionMenuKeyHandler = function (keyEvent) {
            const items = Array.prototype.slice.call(menu.querySelectorAll('[role="menuitem"]'));
            const index = items.indexOf(document.activeElement);
            if (keyEvent.key === 'Escape') {
                keyEvent.preventDefault();
                this.closeJunctionMenu(true);
            } else if ((keyEvent.key === 'ArrowDown' || keyEvent.key === 'ArrowUp') && items.length) {
                keyEvent.preventDefault();
                const direction = keyEvent.key === 'ArrowDown' ? 1 : -1;
                items[(index + direction + items.length) % items.length].focus();
            }
        }.bind(this);
        setTimeout(function () {
            if (!this.junctionMenuElement) return;
            document.addEventListener('pointerdown', this.junctionMenuOutsideHandler, true);
            document.addEventListener('keydown', this.junctionMenuKeyHandler, true);
            const first = menu.querySelector('[role="menuitem"]');
            if (first) first.focus();
        }.bind(this), 0);
        return true;
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
            const proposal = suggestion && suggestion.spatialProposal;
            if (suggestion && suggestion.placement) return;
            if (!edge || !edge.from || !edge.to) return;
            const fromPosition = this.positions[edge.from.nodeId];
            const toPosition = this.positions[edge.to.nodeId];
            if (!fromPosition || !toPosition) return;
            const proposalIsCurrent = proposal && proposal.accepted === true
                && proposal.semanticSuggestionId === suggestion.suggestionId
                && proposal.semanticEvidenceFingerprint === suggestion.evidenceFingerprint
                && proposal.route && Array.isArray(proposal.route.points)
                && proposal.route.points.length >= 2;
            const pathValue = proposalIsCurrent
                ? polylinePath(proposal.route.points)
                : edgeGeometryFromAnchors(
                    portAnchor(fromPosition, 'out'),
                    portAnchor(toPosition, 'in'),
                    fromPosition,
                    toPosition,
                    null,
                    false
                ).path;
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
                class: 'pm-edge pm-edge-ghost'
                    + (proposalIsCurrent ? ' spatialized' : '')
                    + (invalid ? ' invalid' : ''),
                'marker-end': 'url(#' + this.instanceId + ')',
                'data-suggestion-id': suggestionId,
            });
            const title = svgElement('title');
            title.textContent = String(suggestion.explanation || 'Proposed connection');
            path.appendChild(title);
            this.edgeSvg.appendChild(path);
        }, this);
    };

    ProcessMapEditor.prototype._edgeGeometry = function (edge) {
        return edgeGeometry(edge, this.positions, {
            routingEnabled: this.autoRoutingEnabled,
            inputPortSlots: this.inputPortLayout && this.inputPortLayout.byEdge,
        });
    };

    ProcessMapEditor.prototype._cardPreviewSourceMap = function () {
        return this.managedProposalPlan && this.managedProposalPlan.preview
            ? mergeManagedProposalPreview(
                this.processMap,
                this.managedProposalPlan.preview
            )
            : this.processMap;
    };

    ProcessMapEditor.prototype._scheduleCardPreviewLoad = function () {
        if (typeof this.options.resolveCardPreviews !== 'function' || this.destroyed) return;
        const descriptors = processMapCardPreviewDescriptors(
            this._cardPreviewSourceMap(),
            this.productStructure
        );
        this.cardPreviewDescriptors = new Map(descriptors.map(function (item) {
            return [item.previewId, item];
        }));
        const fingerprint = JSON.stringify(descriptors);
        if (!descriptors.length) {
            const changed = this.cardPreviews.size > 0;
            this.cardPreviews = new Map();
            this.cardPreviewFingerprint = fingerprint;
            this.cardPreviewPendingFingerprint = '';
            if (changed) {
                const schedule = typeof requestAnimationFrame === 'function'
                    ? requestAnimationFrame
                    : function (callback) { return setTimeout(callback, 0); };
                schedule(function () {
                    if (!this.destroyed) this.renderGraph({ fit: false });
                }.bind(this));
            }
            return;
        }
        if (
            fingerprint === this.cardPreviewFingerprint
            || fingerprint === this.cardPreviewPendingFingerprint
        ) return;
        this.cardPreviewPendingFingerprint = fingerprint;
        const requestToken = ++this.cardPreviewRequestToken;
        Promise.resolve(this.options.resolveCardPreviews({
            previews: descriptors,
        })).then(function (result) {
            if (this.destroyed || requestToken !== this.cardPreviewRequestToken) return;
            this.cardPreviewPendingFingerprint = '';
            this.cardPreviewFingerprint = fingerprint;
            const values = result && Array.isArray(result.previews)
                ? result.previews : [];
            const next = new Map();
            values.forEach(function (item) {
                if (item && item.previewId && item.url) {
                    next.set(item.previewId, item);
                }
            });
            const changed = JSON.stringify(Array.from(this.cardPreviews.entries()))
                !== JSON.stringify(Array.from(next.entries()));
            this.cardPreviews = next;
            if (changed) this.renderGraph({ fit: false });
        }.bind(this)).catch(function () {
            if (this.destroyed || requestToken !== this.cardPreviewRequestToken) return;
            this.cardPreviewPendingFingerprint = '';
            this.cardPreviewFingerprint = fingerprint;
        }.bind(this));
    };

    ProcessMapEditor.prototype._previewNode = function (node) {
        const resolved = resolveCanvasNode(node, this.occurrenceById) || node;
        const descriptor = this.cardPreviewDescriptors.get(node.nodeId) || null;
        const preview = this.cardPreviews.get(node.nodeId) || null;
        return Object.assign({}, resolved, {
            cardPreview: preview,
            cardPreviewDescriptor: descriptor,
            previewOccurrenceIds: descriptor
                ? descriptor.occurrenceIds.slice() : [],
            previewDirectOccurrenceIds: descriptor
                ? descriptor.directOccurrenceIds.slice() : [],
        });
    };

    ProcessMapEditor.prototype._openNodePreview = function (node, sourceElement) {
        if (
            !node
            || !sourceElement
            || typeof this.options.onOpenPreview !== 'function'
        ) return false;
        this._closeCardToolbar('preview', false);
        return this.options.onOpenPreview(
            this._previewNode(node),
            sourceElement
        ) !== false;
    };

    ProcessMapEditor.prototype._appendNodeCardPreview = function (card, node) {
        const preview = this.cardPreviews.get(node.nodeId);
        if (!card || !preview || !preview.url) return false;
        const media = document.createElement('span');
        media.className = 'pm-card-visual pm-card-visual-' + String(preview.kind || 'occurrence');
        media.setAttribute('data-card-preview-id', node.nodeId);
        media.title = node.nodeKind === 'process_step'
            ? 'Open this assembly stage in the interactive 3D viewer'
            : 'Open this occurrence in the interactive 3D viewer';
        const image = document.createElement('img');
        image.loading = 'lazy';
        image.alt = (node.name || node.nodeId) + ' 3D assembly preview';
        image.src = preview.url;
        media.appendChild(image);
        if (preview.kind === 'stage') {
            const legend = document.createElement('span');
            legend.className = 'pm-card-visual-legend';
            legend.setAttribute('aria-label', 'Cyan is inherited; orange is added at this stage');
            const inherited = document.createElement('span');
            inherited.className = 'pm-card-visual-key inherited';
            inherited.title = 'Inherited assembly state';
            const direct = document.createElement('span');
            direct.className = 'pm-card-visual-key direct';
            direct.title = 'Parts added at this stage';
            legend.appendChild(inherited);
            legend.appendChild(direct);
            media.appendChild(legend);
        }
        media.addEventListener('pointerdown', function (event) {
            event.stopPropagation();
        });
        let previewTimer = null;
        media.addEventListener('dblclick', function (event) {
            if (previewTimer !== null) {
                window.clearTimeout(previewTimer);
                previewTimer = null;
            }
            event.preventDefault();
            event.stopPropagation();
        });
        media.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            this.select(node.nodeId, { openToolbar: false });
            if (!this._canOpenStageDetail(node)) {
                this._openNodePreview(node, media);
                return;
            }
            if (previewTimer !== null) window.clearTimeout(previewTimer);
            previewTimer = window.setTimeout(function () {
                previewTimer = null;
                this._openNodePreview(node, media);
            }.bind(this), 450);
        }.bind(this));
        image.addEventListener('error', function () {
            media.remove();
            card.classList.remove('has-card-preview');
        });
        card.classList.add('has-card-preview');
        card.insertBefore(media, card.firstChild);
        return true;
    };

    ProcessMapEditor.prototype.renderGraph = function (renderOptions) {
        if (this.wireSketch) this._cancelWireSketch();
        const opts = renderOptions || {};
        this._refreshAgentFocus();
        const placements = scopedNodes(this.processMap, this.focusNodeId);
        const nodes = placements.map(function (node) {
            return resolveCanvasNode(node, this.occurrenceById);
        }, this);
        const edges = visibleEdges(this.processMap, placements);
        this.positions = layeredLayout(nodes, edges);
        this.inputPortLayout = processStepInputPortLayout(nodes, edges, this.positions);
        this.edgeGeometries = {};
        edges.forEach(function (edge) {
            const geometry = this._edgeGeometry(edge);
            if (geometry) this.edgeGeometries[edge.edgeId] = geometry;
        }, this);
        this.bounds = graphBounds(
            this.positions,
            mapGroups(this.processMap),
            Object.keys(this.edgeGeometries).map(function (edgeId) {
                return this.edgeGeometries[edgeId];
            }, this)
        );
        this.managedProposalGeometry = this.managedProposalPlan
            ? managedProposalGeometry(
                this.processMap,
                this.managedProposalPlan.preview,
                this.occurrenceById
            )
            : null;
        if (this.managedProposalGeometry) {
            this.bounds = unionGraphBounds(
                this.bounds,
                this.managedProposalGeometry.bounds
            );
        }
        this.nodeLayer.innerHTML = '';
        this.edgeSvg.innerHTML = '';
        const hasPlacementPreview = !!this.managedProposalPlan
            || !!this.arrangementPlan
            || !!this.placementPlan
            || !!this.batchPlacementPlan
            || this.suggestions.some(function (suggestion) {
                return suggestion && suggestion.spatialProposal
                    && suggestion.spatialProposal.placement;
            });
        if (this.emptyState) this.emptyState.hidden = nodes.length > 0
            || mapGroups(this.processMap).length > 0 || hasPlacementPreview;

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
        this.placementGhostWireSvg.setAttribute('width', worldWidth);
        this.placementGhostWireSvg.setAttribute('height', worldHeight);
        this.placementGhostWireSvg.setAttribute(
            'viewBox',
            '0 0 ' + worldWidth + ' ' + worldHeight
        );
        this.renderGroups();
        this._renderGhostEdges();

        const labeledLogicalConnections = new Set();
        edges.forEach(function (edge) {
            const fromPosition = this.positions[edge.from.nodeId];
            const toPosition = this.positions[edge.to.nodeId];
            if (!fromPosition || !toPosition) return;
            const geometry = this.edgeGeometries[edge.edgeId] || this._edgeGeometry(edge);
            if (!geometry || !geometry.path) return;
            const pathValue = geometry.path;
            const routeFindings = routeGeometryFindings(
                edge,
                geometry,
                this.positions,
                mapGroups(this.processMap)
            );
            const edgeFindings = this.findings.filter(function (finding) {
                return finding && finding.edgeId === edge.edgeId;
            }).concat(routeFindings);
            const classes = [
                'pm-edge',
                'pm-edge-' + String(edge.kind || 'precedence'),
                'pm-edge-route-' + geometry.mode.replace(/_/g, '-'),
            ];
            if (this.selectedEdgeIds.has(edge.edgeId)) classes.push('selected');
            if (this.routePlan && this.routePlan.edgeId === edge.edgeId) {
                classes.push('route-preview-source');
            }
            if (edgeFindings.some(function (finding) { return finding.severity === 'error'; })) {
                classes.push('invalid');
            }
            if (routeFindings.length) classes.push('route-needs-repair');
            if (this.editable) {
                const hit = svgElement('path', {
                    d: pathValue,
                    class: 'pm-edge-hit',
                    'data-edge-id': edge.edgeId || '',
                    tabindex: '0',
                    role: 'button',
                    'aria-label': 'Select connection from ' + edge.from.nodeId + ' to ' + edge.to.nodeId
                        + (routeFindings.length ? '; route needs repair' : ''),
                });
                hit.addEventListener('click', function (event) {
                    if (this._suppressClick) {
                        event.preventDefault();
                        event.stopImmediatePropagation();
                        this._suppressClick = false;
                        return;
                    }
                    event.preventDefault();
                    event.stopPropagation();
                    this.selectEdge(edge.edgeId);
                }.bind(this));
                if (geometry.mode === 'polyline_manual') {
                    hit.addEventListener('dblclick', function (event) {
                        event.preventDefault();
                        event.stopPropagation();
                        if (this.selectedEdgeId !== edge.edgeId) this.selectEdge(edge.edgeId);
                        this._insertManualWaypointAtClient(
                            edge.edgeId,
                            event.clientX,
                            event.clientY
                        );
                    }.bind(this));
                }
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
        this._renderRouteGhost();

        nodes.forEach(function (node) {
            if (isJunctionNode(node)) this.renderJunction(node);
            else this.renderNode(node);
        }, this);
        this._renderSelectedManualRouteWaypoints();
        this._renderPlacementGhost();
        this._applyAgentFocusClasses();
        this.updateHeader(nodes, edges);
        this.renderStructureTree();
        this._syncCardToolbar();
        this._syncPlacementGhostToolbar();
        this.applyTransform();
        this.updateEditControls();
        this._scheduleCardPreviewLoad();
        if (opts.fit && (nodes.length || this.managedProposalGeometry)) {
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
        const junctionType = JUNCTION_TYPES.indexOf(node.junctionType) >= 0
            ? node.junctionType
            : 'wire_branch';
        const junctionLabels = {
            wire_branch: 'Wire branch',
            parallel_and: 'Parallel AND junction',
            merge: 'Merge junction',
            split: 'Split junction',
        };
        const wrapper = document.createElement('div');
        wrapper.className = 'pm-junction pm-junction-type-' + junctionType;
        if (this.selectedNodeIds.has(node.nodeId)) wrapper.classList.add('selected');
        this._positionNodeElement(wrapper, position);
        wrapper.style.width = JUNCTION_HIT_SIZE + 'px';
        wrapper.style.height = JUNCTION_HIT_SIZE + 'px';
        wrapper.setAttribute('data-node-id', node.nodeId);
        wrapper.setAttribute('data-node-kind', 'junction');
        wrapper.setAttribute('role', 'button');
        wrapper.setAttribute('aria-label', junctionLabels[junctionType]);
        wrapper.tabIndex = 0;
        wrapper.title = junctionLabels[junctionType] + ' - drag to position or use the handle to connect';

        const dot = document.createElement('span');
        dot.className = 'pm-junction-dot';
        const semanticJunction = junctionType !== 'wire_branch';
        dot.style.width = (semanticJunction ? 20 : JUNCTION_DOT_SIZE) + 'px';
        dot.style.height = (semanticJunction ? 20 : JUNCTION_DOT_SIZE) + 'px';
        const symbolText = {
            parallel_and: 'AND',
            merge: 'M',
            split: 'S',
        }[junctionType] || '';
        if (symbolText) {
            const symbol = document.createElement('span');
            symbol.className = 'pm-junction-symbol';
            symbol.textContent = symbolText;
            dot.appendChild(symbol);
        }
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

    ProcessMapEditor.prototype._createProcessStepCard = function (node, onSelect) {
        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'pm-stage-card pm-stage-card-' + String(node.processType || 'operation');
        const kind = document.createElement('span');
        kind.className = 'pm-stage-card-kind';
        kind.textContent = node.processType === 'operation'
            ? 'Operation / Stage'
            : String(node.processType || 'process step').replace(/_/g, ' ');
        const name = document.createElement('strong');
        name.className = 'pm-stage-card-name';
        name.textContent = node.name || node.nodeId;
        const details = document.createElement('span');
        details.className = 'pm-stage-card-details';
        const properties = node.properties && typeof node.properties === 'object'
            ? node.properties
            : {};
        const detailParts = [];
        if (properties.duration) detailParts.push(properties.duration);
        const detailCount = Object.keys(properties).filter(function (key) {
            return key !== 'duration' && properties[key];
        }).length;
        if (detailCount) detailParts.push(detailCount + (detailCount === 1 ? ' detail' : ' details'));
        details.textContent = detailParts.length ? detailParts.join(' | ') : 'Process logic';
        card.appendChild(kind);
        card.appendChild(name);
        card.appendChild(details);
        card.addEventListener('click', function () { onSelect(node.nodeId); });
        return card;
    };

    ProcessMapEditor.prototype.renderNode = function (node) {
        const position = this.positions[node.nodeId];
        if (!position) return;
        const wrapper = document.createElement('div');
        wrapper.className = 'pm-node pm-node-type-' + String(node.type || 'unknown')
            + ' pm-node-kind-' + String(node.nodeKind || 'legacy')
            + ' pm-node-ports-' + nodePortOrientation(node)
            + ' pm-node-port-order-' + nodePortOrder(node);
        if (this.selectedNodeIds.has(node.nodeId)) wrapper.classList.add('selected');
        if (nodePositionLocked(node)) wrapper.classList.add('position-locked');
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

        if (nodePositionLocked(node)) {
            const lockIndicator = document.createElement('span');
            lockIndicator.className = 'pm-node-lock-indicator';
            lockIndicator.textContent = 'L';
            lockIndicator.title = 'Position locked';
            lockIndicator.setAttribute('aria-label', 'Card position is locked');
            wrapper.appendChild(lockIndicator);
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
            if (references.some(function (reference) { return reference.demoData === true; })) {
                const demoBadge = document.createElement('span');
                demoBadge.className = 'pm-reference-badge pm-reference-badge-demo';
                demoBadge.textContent = 'Demo';
                demoBadge.title = 'Contains illustrative demo requirements';
                badges.appendChild(demoBadge);
            }
            wrapper.appendChild(badges);
        }

        const authoredInputSlots = node.nodeKind === 'process_step'
            && this.inputPortLayout && this.inputPortLayout.byNode
            ? (this.inputPortLayout.byNode[node.nodeId] || [])
            : [];
        const renderedInputSlots = authoredInputSlots.length
            ? authoredInputSlots
            : [{ edgeId: '', index: 0, count: 1 }];
        renderedInputSlots.forEach(function (slot) {
            const inputPort = document.createElement(this.editable ? 'button' : 'span');
            inputPort.className = 'pm-port pm-port-in';
            inputPort.textContent = '+';
            inputPort.setAttribute('data-node-id', node.nodeId);
            inputPort.setAttribute('data-port-side', 'in');
            inputPort.setAttribute('data-port-slot-index', String(slot.index));
            inputPort.setAttribute('data-port-slot-count', String(slot.count));
            if (slot.edgeId) inputPort.setAttribute('data-edge-id', slot.edgeId);
            inputPort.style.setProperty(
                '--pm-port-slot-position',
                ((slot.index + 1) / (slot.count + 1) * 100) + '%'
            );
            if (this.editable) {
                inputPort.type = 'button';
                const positionLabel = slot.count > 1
                    ? ' input ' + (slot.index + 1) + ' of ' + slot.count
                    : ' input';
                inputPort.setAttribute(
                    'aria-label',
                    'Connect into' + positionLabel + ' for ' + (node.name || node.nodeId)
                );
                inputPort.title = slot.count > 1
                    ? 'Connection input ' + (slot.index + 1) + ' of ' + slot.count
                    : 'Connection input';
            } else {
                inputPort.setAttribute('aria-hidden', 'true');
            }
            wrapper.appendChild(inputPort);
        }, this);
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
        wrapper.appendChild(outputPort);

        const onSelect = this.select.bind(this);
        const card = node.nodeKind === 'process_step'
            ? this._createProcessStepCard(node, onSelect)
            : (typeof this.options.createNodeCard === 'function'
            ? this.options.createNodeCard(node, {
                selected: this.selectedNodeIds.has(node.nodeId),
                onSelect: onSelect,
                onPreview: function () {
                    if (typeof this.options.onOpenPreview !== 'function') return false;
                    this.select(node.nodeId);
                    return this.openSelectedPreview();
                }.bind(this),
            })
            : fallbackCard(node, onSelect));
        card.classList.add('pm-node-card');
        this._appendNodeCardPreview(card, node);
        card.addEventListener('keydown', function (event) {
            if (event.key !== 'Tab' || event.shiftKey) return;
            if (!this._focusCardToolbar(node.nodeId)) return;
            event.preventDefault();
        }.bind(this));
        wrapper.appendChild(card);
        if (this._canOpenStageDetail(node)) {
            wrapper.classList.add('has-stage-detail');
            const stageDetailAction = document.createElement('button');
            stageDetailAction.type = 'button';
            stageDetailAction.className = 'pm-stage-detail-action';
            stageDetailAction.setAttribute(
                'aria-label',
                'Open detailed process for ' + String(node.name || node.nodeId)
            );
            stageDetailAction.title = 'Open the evidence-bound detailed process';
            const actionIcon = document.createElement('img');
            actionIcon.src = '/static/assets/process-map-ribbon-icons/svg/stage-operation.svg';
            actionIcon.alt = '';
            actionIcon.draggable = false;
            stageDetailAction.appendChild(actionIcon);
            stageDetailAction.appendChild(document.createTextNode('Open details'));
            stageDetailAction.addEventListener('pointerdown', function (event) {
                event.stopPropagation();
            });
            stageDetailAction.addEventListener('click', function (event) {
                event.preventDefault();
                event.stopPropagation();
                this.select(node.nodeId, { openToolbar: false });
                this.openStageDetail(node);
            }.bind(this));
            wrapper.appendChild(stageDetailAction);
        }
        if (this.editable) {
            wrapper.addEventListener('dragstart', function (event) {
                event.preventDefault();
            });
            wrapper.addEventListener('pointerdown', function (event) {
                if (!(event.ctrlKey || event.metaKey)) return;
                this.startNodeDrag(node.nodeId, event);
            }.bind(this), true);
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
            if (this._canOpenStageDetail(node)) {
                this.openStageDetail(node);
                return;
            }
            this.focus(node.nodeId);
        }.bind(this), true);
        this.nodeLayer.appendChild(wrapper);
    };

    ProcessMapEditor.prototype.updateHeader = function (nodes, edges) {
        const focus = this.focusNodeId && mapNodes(this.processMap).find(function (node) {
            return node && node.nodeId === this.focusNodeId;
        }, this);
        const association = this.processMap && this.processMap.association;
        const parentMapId = association && association.relation === 'stage_detail'
            ? String(association.parentMapId || '') : '';
        const parentMap = parentMapId && this.mapCatalog
            ? (this.mapCatalog.maps || []).find(function (item) {
                return item && String(item.mapId || '') === parentMapId;
            }) : null;
        const currentTitle = focus
            ? (focus.name || focus.nodeId)
            : String(this.processMap.displayName || 'Process Flow');
        this.title.textContent = parentMap
            ? String(parentMap.displayName || 'Main Process') + ' > ' + currentTitle
            : currentTitle;
        if (this.stageDetailNav) {
            this.stageDetailNav.hidden = !parentMapId;
        }
        if (this.stageDetailBreadcrumb) {
            const breadcrumb = parentMap
                ? String(parentMap.displayName || 'Main Process') + ' > ' + currentTitle
                : '';
            this.stageDetailBreadcrumb.textContent = breadcrumb;
            this.stageDetailBreadcrumb.title = breadcrumb;
        }
        const groups = mapGroups(this.processMap).length;
        this.subtitle.textContent = nodes.length + ' nodes / ' + edges.length
            + ' visible precedence connections / ' + groups + (groups === 1 ? ' group' : ' groups')
            + ' / ' + (this.editable ? 'editing' : 'read only');
        const showParentBack = !!parentMapId;
        const showBack = showParentBack || !isPlacementMap(this.processMap);
        this.backButton.hidden = !showBack;
        this.backButton.style.display = showBack ? '' : 'none';
        this.backButton.disabled = showParentBack ? false : !this.focusNodeId;
        this.backButton.title = showParentBack
            ? 'Back to the parent process map'
            : 'Back one process scope';
    };

    ProcessMapEditor.prototype.select = function (nodeId, selectOptions) {
        const opts = selectOptions || {};
        this._clearRoutePlan();
        this.selectedNodeId = nodeId;
        this.selectedEdgeId = null;
        this.selectedWaypoint = null;
        this.selectedGroupId = null;
        this.selectedNodeIds = new Set(nodeId ? [nodeId] : []);
        this.selectedEdgeIds.clear();
        Array.prototype.forEach.call(this.groupLayer.querySelectorAll('.pm-group-frame'), function (group) {
            group.classList.remove('selected');
        });
        this._applyGraphSelectionClasses();
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
        if (this.routePlan && this.routePlan.edgeId !== edgeId) this._clearRoutePlan();
        this._closeCardToolbar('edge_selected', false);
        if (!this.selectedWaypoint || this.selectedWaypoint.edgeId !== edgeId) {
            this.selectedWaypoint = null;
        }
        this.selectedEdgeId = edgeId;
        this.selectedNodeId = null;
        this.selectedGroupId = null;
        this.selectedNodeIds.clear();
        this.selectedEdgeIds = new Set(edgeId ? [edgeId] : []);
        if (this.viewport && typeof this.viewport.focus === 'function') {
            this.viewport.focus({ preventScroll: true });
        }
        Array.prototype.forEach.call(this.groupLayer.querySelectorAll('.pm-group-frame'), function (group) {
            group.classList.remove('selected');
        });
        this._applyGraphSelectionClasses();
        this.updateEditControls();
        const edge = mapEdges(this.processMap).find(function (item) {
            return item && item.edgeId === edgeId;
        });
        this._openEdgeToolbar(edge);
    };

    ProcessMapEditor.prototype._renderGroupSelect = function () {
        if (!this.groupSelect) return;
        const groups = mapGroups(this.processMap).slice().sort(function (left, right) {
            const byLabel = String(left && left.label || '').localeCompare(
                String(right && right.label || ''), undefined, { sensitivity: 'base' }
            );
            return byLabel || String(left && left.groupId || '').localeCompare(
                String(right && right.groupId || '')
            );
        });
        this.groupSelect.textContent = '';
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = groups.length ? 'Select group' : 'Group: None';
        this.groupSelect.appendChild(placeholder);
        groups.forEach(function (group) {
            if (!group || !group.groupId) return;
            const option = document.createElement('option');
            option.value = group.groupId;
            option.textContent = group.label || group.groupId;
            this.groupSelect.appendChild(option);
        }, this);
        this.groupSelect.value = groups.some(function (group) {
            return group && group.groupId === this.selectedGroupId;
        }, this) ? this.selectedGroupId : '';
    };

    ProcessMapEditor.prototype.changeGroupSelection = function () {
        if (!this.groupSelect || !this.groupSelect.value) return false;
        return this.selectGroup(this.groupSelect.value);
    };

    ProcessMapEditor.prototype.selectGroup = function (groupId) {
        const group = mapGroups(this.processMap).find(function (item) {
            return item && item.groupId === groupId;
        });
        if (!group) return false;
        this._clearRoutePlan();
        this._closeCardToolbar('group_selected', false);
        this.selectedGroupId = groupId;
        this.selectedNodeId = null;
        this.selectedEdgeId = null;
        this.selectedWaypoint = null;
        this.selectedNodeIds.clear();
        this.selectedEdgeIds.clear();
        this._applyGraphSelectionClasses();
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
        const association = this.processMap && this.processMap.association;
        const parentMapId = association && association.relation === 'stage_detail'
            ? String(association.parentMapId || '') : '';
        if (parentMapId && typeof this.options.onSwitchMap === 'function') {
            return this._runMapManagement(
                this.options.onSwitchMap,
                { mapId: parentMapId },
                { discardGuard: true, fit: true }
            );
        }
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

    ProcessMapEditor.prototype._canOpenStageDetail = function (node) {
        if (!node || node.nodeKind !== 'process_step') return false;
        if (typeof this.options.onOpenStageDetail !== 'function') return false;
        const semantic = node.semantic && typeof node.semantic === 'object'
            ? node.semantic : {};
        const semanticRef = String(semantic.semanticRef || '');
        return semantic.stageDetailAvailable === true
            || this.stageDetailOperationIds.has(semanticRef);
    };

    ProcessMapEditor.prototype.openSelectedStageDetail = function () {
        const node = mapNodes(this.processMap).find(function (item) {
            return item && item.nodeId === this.selectedNodeId;
        }, this);
        return this.openStageDetail(node);
    };

    ProcessMapEditor.prototype.openStageDetail = async function (node) {
        if (!this._canOpenStageDetail(node) || this.managementBusy || this.conflict) {
            return false;
        }
        if (this.dirty) {
            const saved = await this.save();
            if (!saved) return false;
        }
        const semantic = node.semantic || {};
        const stageOperationId = String(semantic.semanticRef || '');
        this.managementBusy = true;
        this.operationError = '';
        this.updateEditControls();
        try {
            const result = await this.options.onOpenStageDetail({
                mapId: String(this.processMap.mapId || 'default'),
                revision: this.revision,
                stageOperationId: stageOperationId,
                stageLabel: String(node.name || stageOperationId),
            });
            if (!result || result.ok === false || !result.map) {
                this.operationError = String(
                    result && (result.error || result.detail)
                    || 'Stage detail could not be opened.'
                );
                return false;
            }
            if (result.mapCatalog) this.setMapCatalog(result.mapCatalog);
            if (!this._activateMapResult(result, true)) return false;
            if (result.proposalId && !this.showManagedProposal(result)) {
                this.operationError = 'Stage-detail preview could not be displayed.';
                return false;
            }
            return true;
        } catch (error) {
            this.operationError = 'Stage detail failed: '
                + (error && error.message ? error.message : String(error));
            return false;
        } finally {
            this.managementBusy = false;
            this._renderMapCatalogControls();
            this.updateEditControls();
        }
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
        const canDeleteGraphSelection = !!(
            this.selectedNodeIds.size || this.selectedEdgeIds.size
        ) && !this.saving && !this.conflict;
        if (this.undoButton) this.undoButton.disabled = !this.history.undoStack.length || this.saving || this.conflict;
        if (this.redoButton) this.redoButton.disabled = !this.history.redoStack.length || this.saving || this.conflict;
        if (this.deleteButton) {
            this.deleteButton.disabled = !commandStates.canDelete
                && !canDeleteGroup
                && !canDeleteGraphSelection;
        }
        if (this.addStepButton) this.addStepButton.disabled = this.saving || this.conflict;
        if (this.addGroupButton) this.addGroupButton.disabled = this.saving || this.conflict;
        if (this.cleanUpButton) {
            const cleanupLabel = this.arrangementPlanning
                ? 'Cancel'
                : (this.selectedGroupId
                    ? 'Clean Group'
                    : (this.selectedNodeIds.size ? 'Clean Selection' : 'Clean Map'));
            this._setCommandButtonLabel(this.cleanUpButton, cleanupLabel);
            this.cleanUpButton.title = this.arrangementPlanning
                ? 'Cancel layout cleanup'
                : (this.selectedGroupId
                    ? 'Preview a cleaner arrangement inside the selected group'
                    : (this.selectedNodeIds.size
                        ? 'Preview a cleaner arrangement for the selected cards'
                        : 'Preview a cleaner arrangement for the full process map'));
            this.cleanUpButton.setAttribute('aria-label', this.cleanUpButton.title);
            this.cleanUpButton.classList.toggle('active', this.arrangementPlanning);
            this.cleanUpButton.disabled = this.saving || this.conflict
                || this.hasStructuralErrors() || !this.spatialPlacementEnabled
                || (!this.arrangementPlanning
                    && (!!this.arrangementPlan || mapNodes(this.processMap).length === 0));
        }
        if (this.addJunctionButton) this.addJunctionButton.disabled = this.saving || this.conflict;
        if (this.addJunctionMenuButton) this.addJunctionMenuButton.disabled = this.saving || this.conflict;
        if (this.clearMapButton) {
            this.clearMapButton.disabled = this.saving || this.conflict
                || !hasProcessMapCanvasContent(this.processMap);
        }
        this._syncNewEdgeRouteModeControl();
        if (this.groupSelect) {
            this._renderGroupSelect();
            this.groupSelect.disabled = this.saving || this.conflict
                || mapGroups(this.processMap).length === 0;
        }
        if (this.previewButton) this.previewButton.disabled = !commandStates.canPreview;
        if (this.stageDetailButton) {
            const selectedNode = mapNodes(this.processMap).find(function (node) {
                return node && node.nodeId === this.selectedNodeId;
            }, this);
            const canOpenStageDetail = this._canOpenStageDetail(selectedNode)
                && !this.saving && !this.managementBusy && !this.conflict;
            this.stageDetailButton.disabled = !canOpenStageDetail;
            this.stageDetailButton.title = canOpenStageDetail
                ? 'Open the evidence-bound detailed process for the selected stage'
                : 'Select a high-level stage with detailed process data';
            this.stageDetailButton.setAttribute(
                'aria-label', this.stageDetailButton.title
            );
        }
        if (this.analyzeButton) {
            this.analyzeButton.disabled = this.saving || this.conflict || this.hasStructuralErrors();
        }
        if (this.analyzeLayoutButton) {
            this.analyzeLayoutButton.disabled = !this.spatialAnalysisEnabled
                || this.saving || this.conflict || this.hasStructuralErrors();
            this.analyzeLayoutButton.title = this.spatialAnalysisEnabled
                ? 'Ask Sage to analyze card and wire layout'
                : 'Spatial layout analysis is disabled';
            this.analyzeLayoutButton.setAttribute('aria-label', this.analyzeLayoutButton.title);
        }
        if (this.reviewKnowledgeButton) {
            this.reviewKnowledgeButton.disabled = this.saving || this.conflict;
        }
        if (this.suggestionButton) {
            const suggestionCount = this.suggestions.length;
            this._setCommandButtonLabel(this.suggestionButton, this.suggestionsLoading
                ? 'Suggestions...'
                : ('Suggestions' + (suggestionCount ? ' ' + suggestionCount : '')));
            this.suggestionButton.disabled = this.saving || this.conflict || !this.revision
                || (this.dirty && !suggestionCount);
            this.suggestionButton.classList.toggle('active', this.suggestionPanelOpen);
        }
        if (this.saveButton) {
            this.saveButton.disabled = !this.dirty || this.saving || this.conflict || this.hasStructuralErrors();
            this._setCommandButtonLabel(this.saveButton, this.saving ? 'Saving...' : 'Save');
        }
        if (this.reloadButton) {
            this.reloadButton.hidden = !this.conflict;
            this.reloadButton.style.display = this.conflict ? '' : 'none';
        }
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
        } else if (this.arrangementPlanning) {
            this.status.textContent = 'Planning a cleaner layout. Use Cancel to stop.';
            this.status.className = 'pm-editor-status';
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

    ProcessMapEditor.prototype._refreshAutoRoutes = function (processMap) {
        if (!this.autoRoutingEnabled || !this._spatialContractCache) {
            return { map: cloneMap(processMap), failures: [] };
        }
        if (!mapEdges(processMap).some(function (edge) {
            return edge && edge.routing && edge.routing.mode === 'orthogonal_auto';
        })) return { map: cloneMap(processMap), failures: [] };
        const runtime = processMapSpatialRuntime();
        if (!runtime || typeof runtime.refreshOrthogonalAutoRoutes !== 'function') {
            return {
                map: cloneMap(processMap),
                failures: [{ edgeId: '', failureReason: 'spatial_router_unavailable' }],
            };
        }
        return runtime.refreshOrthogonalAutoRoutes(processMap, {
            contract: this._spatialContractCache,
        });
    };

    ProcessMapEditor.prototype.commitMutation = function (nextMap, mutationOptions) {
        const opts = mutationOptions || {};
        const refreshed = this._refreshAutoRoutes(nextMap);
        if (refreshed.failures.length) {
            this.operationError = 'A connected route could not be updated without crossing a card.';
            this.updateEditControls();
            return false;
        }
        const candidateMap = refreshed.map;
        if (!this.editable || this.conflict
            || mapFingerprint(candidateMap) === mapFingerprint(this.processMap)) return false;
        this.history.record(this.processMap);
        this.processMap = cloneMap(candidateMap);
        this._clearArrangementPlan();
        this._clearManagedProposal();
        if (!opts.preserveSuggestions) this._clearSuggestions();
        this._clearPlacementPlan();
        this._clearRoutePlan();
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

    ProcessMapEditor.prototype.lockSelectedPosition = function () {
        const states = this.selectedNodeCommandStates();
        if (!states.canLockPosition) return false;
        return this.commitMutation(setNodePositionLocked(this.processMap, this.selectedNodeId, true));
    };

    ProcessMapEditor.prototype.unlockSelectedPosition = function () {
        const states = this.selectedNodeCommandStates();
        if (!states.canUnlockPosition) return false;
        return this.commitMutation(setNodePositionLocked(this.processMap, this.selectedNodeId, false));
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

    ProcessMapEditor.prototype.applyProcessStepProperties = function (value) {
        const states = this.selectedNodeCommandStates();
        if (!states.canEditProperties || !value || typeof value !== 'object') return false;
        return this.commitMutation(setProcessStepProperties(
            this.processMap,
            this.selectedNodeId,
            value
        ));
    };

    ProcessMapEditor.prototype.copyProcessLogicSelection = function () {
        if (!this.editable || this.conflict) return false;
        const clipboard = copyProcessLogicSelection(
            this.processMap,
            Array.from(this.selectedNodeIds || [])
        );
        if (!clipboard.nodes.length) {
            this.operationError = 'Select an operation, stage, or junction to copy.';
            this.updateEditControls();
            return false;
        }
        this.processLogicClipboard = clipboard;
        this.processLogicPasteCount = 0;
        this.operationError = '';
        this.updateEditControls();
        return true;
    };

    ProcessMapEditor.prototype.pasteProcessLogicSelection = function () {
        if (!this.editable || this.conflict || !this.processLogicClipboard) return false;
        const stamp = Date.now().toString(36) + '-' + (++this.nodeCounter);
        const pasteIndex = ++this.processLogicPasteCount;
        const nodeIdMap = {};
        const edgeIdMap = {};
        const logicalConnectionIdMap = {};
        this.processLogicClipboard.nodes.forEach(function (node, index) {
            nodeIdMap[node.nodeId] = 'pm-copy-' + stamp + '-n' + index;
        });
        this.processLogicClipboard.edges.forEach(function (edge, index) {
            edgeIdMap[edge.edgeId] = 'pm-copy-' + stamp + '-e' + index;
            const logicalId = String(edge.logicalConnectionId || edge.edgeId || '');
            if (!logicalConnectionIdMap[logicalId]) {
                logicalConnectionIdMap[logicalId] = 'pm-copy-' + stamp + '-l' + index;
            }
        });
        const result = pasteProcessLogicSelection(this.processMap, this.processLogicClipboard, {
            nodeIdMap: nodeIdMap,
            edgeIdMap: edgeIdMap,
            logicalConnectionIdMap: logicalConnectionIdMap,
            offset: { x: 28 * pasteIndex, y: 28 * pasteIndex },
        });
        if (!result.accepted || !this.commitMutation(result.map)) {
            this.operationError = 'The copied process logic could not be pasted here.';
            this.updateEditControls();
            return false;
        }
        this.setGraphSelection(result.nodeIds, result.edgeIds);
        return true;
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
        return this._openNodePreview(states.node, sourceElement);
    };

    ProcessMapEditor.prototype.clearMap = function () {
        if (!this.editable || this.saving || this.conflict
            || !hasProcessMapCanvasContent(this.processMap)) return false;
        if (!this._confirmManagementAction(
            'Clear all cards, connections, junctions, groups, and references from this process map? This can be undone.'
        )) return false;
        this._closeCardToolbar('clear_map', false);
        this._resetGraphSelectionState();
        this.groupMoveFrameOnly = false;
        return this.commitMutation(clearProcessMapCanvas(this.processMap));
    };

    ProcessMapEditor.prototype.deleteSelection = function () {
        this._closeCardToolbar('delete_selection', false);
        if (this.selectedGroupId) {
            const groupId = this.selectedGroupId;
            this.selectedGroupId = null;
            return this.commitMutation(deleteGroup(this.processMap, groupId));
        }
        if (this.selectedNodeIds.size || this.selectedEdgeIds.size) {
            const nodeIds = Array.from(this.selectedNodeIds);
            const edgeIds = Array.from(this.selectedEdgeIds);
            this._resetGraphSelectionState();
            return this.commitMutation(deleteCanvasSelection(this.processMap, nodeIds, edgeIds));
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
        this._resetGraphSelectionState();
        this._clearSuggestions();
        this._clearPlacementPlan();
        this._clearArrangementPlan();
        this._clearRoutePlan();
        this._clearManagedProposal();
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
        this._resetGraphSelectionState();
        this._clearSuggestions();
        this._clearPlacementPlan();
        this._clearArrangementPlan();
        this._clearRoutePlan();
        this._clearManagedProposal();
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
        this._clearPlacementPlan();
        this._clearArrangementPlan();
        this._clearRoutePlan();
        this._clearManagedProposal();
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
            return suggestion && (suggestion.edge || suggestion.placement)
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
            const kind = suggestion.placement
                ? 'Next card'
                : (suggestion.edge ? 'Connection' : 'Resource review');
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
            if (suggestion.edge || suggestion.placement) {
                const accept = this._button(
                    'Accept',
                    suggestion.placement
                        ? 'Place this evidence-backed next card and connection'
                        : 'Add this proposed connection',
                    this.acceptSuggestion.bind(this, suggestion.suggestionId)
                );
                accept.disabled = !this.editable || !!(
                    suggestion.validation && suggestion.validation.wouldCreateCycle
                ) || !!(suggestion.placement && !(
                    suggestion.spatialProposal && suggestion.spatialProposal.accepted
                ));
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

    ProcessMapEditor.prototype._revalidateSpatialSuggestions = async function (suggestions) {
        const values = Array.isArray(suggestions) ? suggestions : [];
        if (!this.spatialPlacementEnabled || !this.autoRoutingEnabled) return cloneMap(values);
        const runtime = processMapSpatialRuntime();
        if (!runtime || typeof runtime.spatializeSemanticSuggestions !== 'function') {
            throw new Error('spatial_suggestion_runtime_unavailable');
        }
        const contract = await this._ensureSpatialContract();
        const result = runtime.spatializeSemanticSuggestions(this.processMap, values, {
            contract: contract,
        });
        return result.suggestions;
    };

    ProcessMapEditor.prototype.acceptSuggestion = async function (suggestionId) {
        const suggestion = this.suggestions.find(function (item) {
            return item && item.suggestionId === suggestionId;
        });
        if (!suggestion) return false;
        let fresh = suggestion;
        if (suggestion.spatialProposal || suggestion.placement) {
            try {
                fresh = (await this._revalidateSpatialSuggestions([suggestion]))[0];
            } catch (_) {
                this.operationError = 'This layout suggestion could not be revalidated.';
                this.updateEditControls();
                return false;
            }
            const expected = suggestion.spatialProposal;
            const actual = fresh && fresh.spatialProposal;
            if (!actual || !actual.accepted || (expected && expected.proposalId !== actual.proposalId)) {
                this.operationError = 'The map changed since this layout was suggested. Reload suggestions.';
                this._clearSuggestions();
                this.renderGraph({ fit: false });
                return false;
            }
        }
        const result = fresh && fresh.spatialProposal
            ? acceptSpatialSuggestions(this.processMap, [fresh])
            : acceptSuggestions(this.processMap, [fresh]);
        if (!result.accepted.length) {
            this.operationError = result.skipped.length
                ? 'This suggestion is no longer valid for the current map.'
                : 'No connection was added.';
            this.updateEditControls();
            return false;
        }
        return this.commitMutation(result.map);
    };

    ProcessMapEditor.prototype.acceptAllSuggestions = async function () {
        let freshSuggestions;
        try {
            freshSuggestions = await this._revalidateSpatialSuggestions(this.suggestions);
        } catch (_) {
            this.operationError = 'These layout suggestions could not be revalidated.';
            this.updateEditControls();
            return false;
        }
        const expectedById = new Map(this.suggestions.map(function (suggestion) {
            return [suggestion.suggestionId, suggestion.spatialProposal || null];
        }));
        const stale = freshSuggestions.some(function (suggestion) {
            const expected = expectedById.get(suggestion.suggestionId);
            const actual = suggestion.spatialProposal || null;
            return !!expected && (!actual || expected.proposalId !== actual.proposalId);
        });
        if (stale) {
            this.operationError = 'The map changed since these layouts were suggested. Reload suggestions.';
            this._clearSuggestions();
            this.renderGraph({ fit: false });
            return false;
        }
        const spatial = freshSuggestions.filter(function (suggestion) {
            return suggestion && suggestion.spatialProposal;
        });
        const legacy = freshSuggestions.filter(function (suggestion) {
            return suggestion && suggestion.edge && !suggestion.spatialProposal;
        });
        const spatialResult = acceptSpatialSuggestions(this.processMap, spatial);
        const legacyResult = acceptSuggestions(spatialResult.map, legacy);
        const result = {
            map: legacyResult.map,
            accepted: spatialResult.accepted.concat(legacyResult.accepted),
            skipped: spatialResult.skipped.concat(legacyResult.skipped),
        };
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

    ProcessMapEditor.prototype.analyzeLayout = async function () {
        if (!this.spatialAnalysisEnabled
            || this.saving || this.conflict || this.hasStructuralErrors()) return false;
        if (this.dirty) {
            const saved = await this.save();
            if (!saved) return false;
        }
        if (typeof this.options.onAnalyzeLayout !== 'function' || !this.revision) return false;
        return this.options.onAnalyzeLayout({
            productId: String(this.processMap.productId || ''),
            mapId: String(this.processMap.mapId || 'default'),
            revision: String(this.revision),
        }) !== false;
    };

    ProcessMapEditor.prototype.reviewKnowledge = function () {
        if (this.saving || this.conflict) return false;
        if (typeof this.options.onReviewKnowledge !== 'function') return false;
        return this.options.onReviewKnowledge({
            productId: String(this.processMap.productId || ''),
            mapId: String(this.processMap.mapId || 'default'),
            revision: String(this.revision || ''),
        }) !== false;
    };

    ProcessMapEditor.prototype._spatialMetricSummary = function (metrics) {
        const source = metrics || {};
        const result = {};
        SPATIAL_TELEMETRY_METRIC_KEYS.forEach(function (key) {
            const value = source[key];
            if (typeof value === 'number' && Number.isFinite(value)) result[key] = value;
        });
        return result;
    };

    ProcessMapEditor.prototype._recordSpatialEvent = function (operation, outcome, details) {
        if (typeof this.options.onSpatialTelemetry !== 'function') return false;
        const values = details || {};
        const payload = {
            productId: String(this.processMap.productId || ''),
            mapId: String(this.processMap.mapId || 'default'),
            revision: String(this.revision || 'unsaved'),
            operation: String(operation || ''),
            outcome: String(outcome || ''),
            scope: String(values.scope || 'map'),
            spatialEngineVersion: Number.isInteger(values.spatialEngineVersion)
                ? values.spatialEngineVersion : null,
            policyVersion: Number.isInteger(values.policyVersion)
                ? values.policyVersion : null,
            nodeCount: mapNodes(this.processMap).length,
            edgeCount: mapEdges(this.processMap).length,
            scopedNodeCount: Math.max(0, Number(values.scopedNodeCount) || 0),
            scopedEdgeCount: Math.max(0, Number(values.scopedEdgeCount) || 0),
            candidatesEvaluated: Math.max(0, Number(values.candidatesEvaluated) || 0),
            movedNodeCount: Math.max(0, Number(values.movedNodeCount) || 0),
            latencyMs: Math.max(0, Number(values.latencyMs) || 0),
            rejectionCounts: values.rejectionCounts && typeof values.rejectionCounts === 'object'
                ? cloneMap(values.rejectionCounts) : {},
            metricsBefore: this._spatialMetricSummary(values.metricsBefore),
            metricsAfter: this._spatialMetricSummary(values.metricsAfter),
            fallbackReason: values.fallbackReason ? String(values.fallbackReason) : null,
        };
        try {
            const result = this.options.onSpatialTelemetry(payload);
            if (result && typeof result.catch === 'function') result.catch(function () {});
        } catch (_error) {}
        return true;
    };

    // -- Phase 7: explicit selection, group, and full-map cleanup previews --

    ProcessMapEditor.prototype._arrangementRequest = function () {
        if (this.selectedGroupId) {
            return {
                scope: 'group',
                groupId: this.selectedGroupId,
                nodeIds: [],
            };
        }
        if (this.selectedNodeIds && this.selectedNodeIds.size) {
            return {
                scope: 'selection',
                groupId: null,
                nodeIds: Array.from(this.selectedNodeIds).sort(),
            };
        }
        return { scope: 'full_map', groupId: null, nodeIds: [] };
    };

    ProcessMapEditor.prototype._stopArrangementWorker = function () {
        const worker = this._arrangementWorker;
        const pending = this._arrangementWorkerPending;
        this._arrangementWorker = null;
        this._arrangementWorkerPending = null;
        if (worker && typeof worker.terminate === 'function') worker.terminate();
        if (pending && typeof pending.resolve === 'function') {
            pending.resolve({ cancelled: true, result: null, error: null });
        }
        return !!worker || !!pending;
    };

    ProcessMapEditor.prototype._setArrangementPlanning = function (active) {
        this.arrangementPlanning = !!active;
        if (this.root) {
            if (this.arrangementPlanning) this.root.setAttribute('aria-busy', 'true');
            else this.root.removeAttribute('aria-busy');
        }
    };

    ProcessMapEditor.prototype._runArrangementPlanner = function (processMap, options, requestToken) {
        const runtime = processMapSpatialRuntime();
        const WorkerCtor = this.options.spatialWorkerFactory
            || (typeof window !== 'undefined' ? window.Worker : null);
        if (!WorkerCtor || this.options.spatialWorkerEnabled === false) {
            try {
                return Promise.resolve({
                    cancelled: false,
                    result: runtime.generateArrangementPlan(processMap, options),
                    error: null,
                });
            } catch (error) {
                return Promise.resolve({ cancelled: false, result: null, error: error });
            }
        }
        this._stopArrangementWorker();
        return new Promise(function (resolve) {
            let worker;
            try {
                worker = new WorkerCtor(
                    this.options.spatialWorkerUrl || '/static/process_map_spatial_worker.js'
                );
            } catch (error) {
                resolve({ cancelled: false, result: null, error: error });
                return;
            }
            const requestId = this.instanceId + '-arrangement-' + requestToken;
            this._arrangementWorker = worker;
            this._arrangementWorkerPending = { requestId: requestId, resolve: resolve };
            worker.addEventListener('message', function (event) {
                const payload = event && event.data ? event.data : {};
                if (payload.requestId !== requestId) return;
                worker.terminate();
                if (this._arrangementWorker === worker) this._arrangementWorker = null;
                if (this._arrangementWorkerPending
                    && this._arrangementWorkerPending.requestId === requestId) {
                    this._arrangementWorkerPending = null;
                }
                resolve({
                    cancelled: false,
                    result: payload.ok ? payload.result : null,
                    error: payload.ok ? null : new Error(
                        payload.error || 'arrangement planning failed'
                    ),
                });
            }.bind(this));
            worker.addEventListener('error', function (event) {
                worker.terminate();
                if (this._arrangementWorker === worker) this._arrangementWorker = null;
                if (this._arrangementWorkerPending
                    && this._arrangementWorkerPending.requestId === requestId) {
                    this._arrangementWorkerPending = null;
                }
                resolve({
                    cancelled: false,
                    result: null,
                    error: new Error(event && event.message
                        ? event.message : 'arrangement worker failed'),
                });
            }.bind(this));
            worker.postMessage({
                requestId: requestId,
                operation: 'arrangement',
                processMap: cloneMap(processMap),
                options: cloneMap(options),
            });
        }.bind(this));
    };

    ProcessMapEditor.prototype.cancelArrangementPlanning = function () {
        if (!this.arrangementPlanning) return false;
        const request = this._arrangementPlanningRequest || {};
        const latency = this._arrangementPlanningStartedAt
            ? Date.now() - this._arrangementPlanningStartedAt : 0;
        this.arrangementPlanRequestToken += 1;
        this._stopArrangementWorker();
        this._setArrangementPlanning(false);
        this._arrangementPlanningStartedAt = 0;
        this._arrangementPlanningRequest = null;
        this.operationError = '';
        this._recordSpatialEvent('arrangement', 'cancelled', {
            scope: request.scope || 'full_map',
            scopedNodeCount: Array.isArray(request.nodeIds) ? request.nodeIds.length : 0,
            latencyMs: latency,
        });
        this.updateEditControls();
        return true;
    };

    ProcessMapEditor.prototype._clearArrangementPlan = function () {
        this.arrangementPlanRequestToken += 1;
        const hadPlan = !!this.arrangementPlan;
        const wasPlanning = this.arrangementPlanning;
        this._stopArrangementWorker();
        this._setArrangementPlanning(false);
        this._arrangementPlanningStartedAt = 0;
        this._arrangementPlanningRequest = null;
        if (!hadPlan) return wasPlanning;
        this.arrangementPlan = null;
        this._arrangementGhostElement = null;
        if (this.cardToolbarOwner === 'arrangement') {
            this._closeCardToolbar('arrangement_plan_cleared', false);
        }
        return true;
    };

    ProcessMapEditor.prototype._arrangementFailureMessage = function (reason) {
        const messages = {
            no_movable_nodes: 'Every card in this scope is locked, so there is nothing to move.',
            layout_already_clean: 'This scope is already clean.',
            configured_metric_not_improved: 'No safer arrangement improves the current layout.',
            group_capacity_exceeded: 'The selected group is too small for a clean arrangement.',
            no_collision_free_arrangement: 'No collision-free arrangement is available in this scope.',
            hard_violation_introduced: 'The proposed arrangement would introduce a layout conflict.',
            automatic_route_update_failed: 'A connected automatic route could not be updated safely.',
        };
        return messages[reason] || 'A clean arrangement is not available for this scope.';
    };

    ProcessMapEditor.prototype.previewArrangement = async function () {
        if (this.arrangementPlanning) return this.cancelArrangementPlanning();
        if (!this.spatialPlacementEnabled || !this.editable || this.saving || this.conflict
            || this.hasStructuralErrors() || !isPlacementMap(this.processMap)) return false;
        const runtime = processMapSpatialRuntime();
        if (!runtime || typeof runtime.generateArrangementPlan !== 'function') {
            this.operationError = 'Layout cleanup is unavailable.';
            this.updateEditControls();
            return false;
        }
        this._clearPlacementPlan();
        this._clearRoutePlan();
        this._clearManagedProposal();
        this._clearArrangementPlan();
        const request = this._arrangementRequest();
        const sourceFingerprint = mapFingerprint(this.processMap);
        const requestToken = ++this.arrangementPlanRequestToken;
        this._setArrangementPlanning(true);
        this._arrangementPlanningStartedAt = Date.now();
        this._arrangementPlanningRequest = cloneMap(request);
        this.operationError = '';
        this.updateEditControls();
        let contract;
        try {
            contract = await this._ensureSpatialContract();
        } catch (_error) {
            if (requestToken === this.arrangementPlanRequestToken) {
                this._setArrangementPlanning(false);
                this._recordSpatialEvent('arrangement', 'failed', {
                    scope: request.scope,
                    scopedNodeCount: request.nodeIds.length,
                    latencyMs: Date.now() - this._arrangementPlanningStartedAt,
                    fallbackReason: 'contract_unavailable',
                });
                this._arrangementPlanningStartedAt = 0;
                this._arrangementPlanningRequest = null;
                this.operationError = 'Layout cleanup is temporarily unavailable.';
                this.updateEditControls();
            }
            return false;
        }
        if (requestToken !== this.arrangementPlanRequestToken || this.destroyed || this.conflict) {
            return false;
        }
        const execution = await this._runArrangementPlanner(this.processMap, {
            contract: contract,
            revision: this.revision,
            scope: request.scope,
            nodeIds: request.nodeIds,
            groupId: request.groupId,
        }, requestToken);
        if (requestToken !== this.arrangementPlanRequestToken || execution.cancelled) return false;
        this._setArrangementPlanning(false);
        const latencyMs = this._arrangementPlanningStartedAt
            ? Date.now() - this._arrangementPlanningStartedAt : 0;
        this._arrangementPlanningStartedAt = 0;
        this._arrangementPlanningRequest = null;
        if (execution.error) {
            this._recordSpatialEvent('arrangement', 'failed', {
                scope: request.scope,
                scopedNodeCount: request.nodeIds.length,
                latencyMs: latencyMs,
                fallbackReason: 'planner_error',
            });
            this.operationError = execution.error && execution.error.message
                ? execution.error.message : 'Unable to calculate a clean arrangement.';
            this.updateEditControls();
            return false;
        }
        const plan = execution.result;
        if (requestToken !== this.arrangementPlanRequestToken
            || sourceFingerprint !== mapFingerprint(this.processMap)) return false;
        if (!plan || !plan.accepted || !plan.proposedMap) {
            this._recordSpatialEvent('arrangement', 'failed', {
                scope: request.scope,
                scopedNodeCount: plan && plan.scope && Array.isArray(plan.scope.nodeIds)
                    ? plan.scope.nodeIds.length : request.nodeIds.length,
                latencyMs: latencyMs,
                spatialEngineVersion: plan && plan.spatialEngineVersion,
                policyVersion: plan && plan.arrangementPolicyVersion,
                metricsBefore: plan && plan.metricsBefore,
                metricsAfter: plan && plan.metricsAfter,
                fallbackReason: plan && plan.failureReason || 'no_plan',
            });
            this.operationError = this._arrangementFailureMessage(plan && plan.failureReason);
            this.updateEditControls();
            return false;
        }
        this.arrangementPlan = {
            request: request,
            sourceFingerprint: sourceFingerprint,
            plan: plan,
        };
        this.operationError = '';
        this._recordSpatialEvent('arrangement', 'previewed', {
            scope: plan.scope && plan.scope.kind || request.scope,
            scopedNodeCount: plan.scope && Array.isArray(plan.scope.nodeIds)
                ? plan.scope.nodeIds.length : request.nodeIds.length,
            movedNodeCount: Array.isArray(plan.moves) ? plan.moves.length : 0,
            latencyMs: latencyMs,
            spatialEngineVersion: plan.spatialEngineVersion,
            policyVersion: plan.arrangementPolicyVersion,
            metricsBefore: plan.metricsBefore,
            metricsAfter: plan.metricsAfter,
        });
        this.renderGraph({ fit: false });
        this._openArrangementToolbar();
        return true;
    };

    ProcessMapEditor.prototype.dismissArrangementPlan = function () {
        if (!this.arrangementPlan) return false;
        const plan = this.arrangementPlan.plan || {};
        this._recordSpatialEvent('arrangement', 'dismissed', {
            scope: plan.scope && plan.scope.kind || 'full_map',
            scopedNodeCount: plan.scope && Array.isArray(plan.scope.nodeIds)
                ? plan.scope.nodeIds.length : 0,
            movedNodeCount: Array.isArray(plan.moves) ? plan.moves.length : 0,
            spatialEngineVersion: plan.spatialEngineVersion,
            policyVersion: plan.arrangementPolicyVersion,
            metricsBefore: plan.metricsBefore,
            metricsAfter: plan.metricsAfter,
        });
        this._clearArrangementPlan();
        this.operationError = '';
        this.renderGraph({ fit: false });
        return true;
    };

    ProcessMapEditor.prototype.acceptArrangementPlan = async function () {
        const state = this.arrangementPlan;
        if (!state || this.conflict || this.saving) return false;
        const runtime = processMapSpatialRuntime();
        if (!runtime || typeof runtime.generateArrangementPlan !== 'function') return false;
        const requestToken = ++this.arrangementPlanRequestToken;
        let contract;
        try {
            contract = await this._ensureSpatialContract();
        } catch (_error) {
            return false;
        }
        if (requestToken !== this.arrangementPlanRequestToken || !this.arrangementPlan) return false;
        let fresh;
        try {
            fresh = runtime.generateArrangementPlan(this.processMap, {
                contract: contract,
                revision: this.revision,
                scope: state.request.scope,
                nodeIds: state.request.nodeIds,
                groupId: state.request.groupId,
            });
        } catch (_error) {
            fresh = null;
        }
        if (!fresh || !fresh.accepted || fresh.planId !== state.plan.planId
            || state.sourceFingerprint !== mapFingerprint(this.processMap)) {
            this._recordSpatialEvent('arrangement', 'stale', {
                scope: state.plan.scope && state.plan.scope.kind || state.request.scope,
                scopedNodeCount: state.plan.scope && Array.isArray(state.plan.scope.nodeIds)
                    ? state.plan.scope.nodeIds.length : 0,
                movedNodeCount: Array.isArray(state.plan.moves) ? state.plan.moves.length : 0,
                spatialEngineVersion: state.plan.spatialEngineVersion,
                policyVersion: state.plan.arrangementPolicyVersion,
                fallbackReason: 'map_or_plan_changed',
            });
            this.operationError = 'The map changed since this cleanup was previewed. Preview it again.';
            this._clearArrangementPlan();
            this.renderGraph({ fit: false });
            return false;
        }
        this._recordSpatialEvent('arrangement', 'accepted', {
            scope: fresh.scope && fresh.scope.kind || state.request.scope,
            scopedNodeCount: fresh.scope && Array.isArray(fresh.scope.nodeIds)
                ? fresh.scope.nodeIds.length : 0,
            movedNodeCount: Array.isArray(fresh.moves) ? fresh.moves.length : 0,
            spatialEngineVersion: fresh.spatialEngineVersion,
            policyVersion: fresh.arrangementPolicyVersion,
            metricsBefore: fresh.metricsBefore,
            metricsAfter: fresh.metricsAfter,
        });
        this._clearArrangementPlan();
        return this.commitMutation(fresh.proposedMap);
    };

    // -- Phase 3: deterministic incremental placement and ghost previews --
    //
    // Candidate generation runs entirely client-side against the byte-
    // parity-tested static/process_map_spatial.js engine: no model call,
    // no network round trip beyond a one-time contract fetch. The model
    // (Sage/Builder) is never involved in Phase 3 and never authors
    // coordinates -- that integration is explicitly deferred to a later,
    // separately-approved phase.

    ProcessMapEditor.prototype._ensureSpatialContract = function () {
        const runtime = processMapSpatialRuntime();
        if (!runtime) return Promise.reject(new Error('spatial runtime unavailable'));
        if (this._spatialContractCache) return Promise.resolve(this._spatialContractCache);
        if (this._spatialContractPromise) return this._spatialContractPromise;
        this._spatialContractPromise = runtime.loadSpatialContract(
            this.options.spatialContractUrl,
            this.options.spatialContractFetch
        ).then(function (contract) {
            this._spatialContractCache = contract;
            this._spatialContractPromise = null;
            return contract;
        }.bind(this)).catch(function (error) {
            this._spatialContractPromise = null;
            throw error;
        }.bind(this));
        return this._spatialContractPromise;
    };

    ProcessMapEditor.prototype._routeNewEdges = function (processMap, edgeIds) {
        if (this.newEdgeRouteMode !== 'orthogonal_auto') {
            return { accepted: true, map: processMap };
        }
        const runtime = processMapSpatialRuntime();
        if (!this.autoRoutingEnabled || !this._spatialContractCache || !runtime
            || typeof runtime.applyOrthogonalRoute !== 'function') {
            return { accepted: false, map: processMap, reason: 'router_unavailable' };
        }
        let nextMap = processMap;
        const orderedEdgeIds = Array.isArray(edgeIds) ? edgeIds.filter(Boolean) : [];
        for (let index = 0; index < orderedEdgeIds.length; index += 1) {
            const result = runtime.applyOrthogonalRoute(nextMap, orderedEdgeIds[index], {
                contract: this._spatialContractCache,
            });
            if (!result || !result.accepted) {
                return {
                    accepted: false,
                    map: processMap,
                    reason: result && result.route && result.route.failureReason
                        || 'no_route',
                };
            }
            nextMap = result.map;
        }
        return { accepted: true, map: nextMap };
    };

    ProcessMapEditor.prototype._pendingWirePath = function (action, end, target) {
        if (this.newEdgeRouteMode !== 'orthogonal_auto') {
            return edgeGeometryFromAnchors(
                action.start,
                end,
                {
                    portOrientation: action.startOrientation,
                    portOrder: action.startOrder,
                },
                {
                    portOrientation: target && target.portOrientation,
                    portOrder: target && target.portOrder,
                },
                null,
                false
            ).path;
        }
        const points = [action.start];
        if (action.startOrientation === 'vertical') {
            const middleY = (action.start.y + end.y) / 2;
            points.push(
                { x: action.start.x, y: middleY },
                { x: end.x, y: middleY }
            );
        } else {
            const middleX = (action.start.x + end.x) / 2;
            points.push(
                { x: middleX, y: action.start.y },
                { x: middleX, y: end.y }
            );
        }
        points.push(end);
        return polylinePath(points);
    };

    ProcessMapEditor.prototype._clearRoutePlan = function () {
        this.routePlanRequestToken += 1;
        const hadPlan = !!this.routePlan;
        this.routePlan = null;
        if (hadPlan && this.cardToolbarEdgeId) {
            this._closeCardToolbar('route_plan_cleared', false);
        }
        return hadPlan;
    };

    ProcessMapEditor.prototype.useSelectedEdgeCurve = function () {
        if (!this.selectedEdgeId || this.saving || this.conflict) return false;
        this.selectedWaypoint = null;
        return this.commitMutation(clearEdgeRouting(
            this.processMap,
            this.selectedEdgeId
        ));
    };

    ProcessMapEditor.prototype.useSelectedEdgeManual = function () {
        if (!this.selectedEdgeId || this.saving || this.conflict) return false;
        const edge = mapEdges(this.processMap).find(function (item) {
            return item && item.edgeId === this.selectedEdgeId;
        }, this);
        if (!edge) return false;
        const waypoints = edge.routing && edge.routing.mode !== 'bezier_legacy'
            ? edge.routing.waypoints : [];
        this.selectedWaypoint = null;
        return this.commitMutation(setManualEdgeWaypoints(
            this.processMap,
            this.selectedEdgeId,
            waypoints
        ));
    };

    ProcessMapEditor.prototype.previewSelectedEdgeRoute = async function () {
        if (!this.autoRoutingEnabled || !this.selectedEdgeId || this.conflict) return false;
        const startedAt = Date.now();
        const runtime = processMapSpatialRuntime();
        if (!runtime || typeof runtime.routeOrthogonalEdge !== 'function') {
            this.operationError = 'Obstacle-aware routing is unavailable.';
            this.updateEditControls();
            return false;
        }
        const edgeId = this.selectedEdgeId;
        const requestToken = ++this.routePlanRequestToken;
        let contract;
        try {
            contract = await this._ensureSpatialContract();
        } catch (error) {
            if (requestToken === this.routePlanRequestToken) {
                this.operationError = error && error.message ? error.message : 'Unable to load routing policy.';
                this.updateEditControls();
            }
            return false;
        }
        if (requestToken !== this.routePlanRequestToken || this.destroyed || this.conflict) return false;
        let route;
        try {
            const scene = runtime.compileSpatialScene(this.processMap, { contract: contract });
            route = runtime.routeOrthogonalEdge(scene, edgeId, { contract: contract });
        } catch (error) {
            this.operationError = error && error.message ? error.message : 'Unable to calculate a route.';
            this.updateEditControls();
            return false;
        }
        if (requestToken !== this.routePlanRequestToken || this.selectedEdgeId !== edgeId) return false;
        if (!route.accepted) {
            this._recordSpatialEvent('route', 'failed', {
                scope: 'edge',
                scopedEdgeCount: 1,
                latencyMs: Date.now() - startedAt,
                spatialEngineVersion: route.spatialEngineVersion,
                policyVersion: route.routerVersion,
                fallbackReason: route.failureReason || 'no_route',
            });
            this.operationError = 'No obstacle-free orthogonal route is available for this connection.';
            this.updateEditControls();
            return false;
        }
        this.routePlan = {
            edgeId: edgeId,
            mapFingerprint: mapFingerprint(this.processMap),
            route: route,
        };
        this.operationError = '';
        this._recordSpatialEvent('route', 'previewed', {
            scope: 'edge',
            scopedEdgeCount: 1,
            latencyMs: Date.now() - startedAt,
            spatialEngineVersion: route.spatialEngineVersion,
            policyVersion: route.routerVersion,
            fallbackReason: route.fallbackReason || null,
        });
        this.renderGraph({ fit: false });
        this._closeCardToolbar('route_preview_changed', false);
        this._openEdgeToolbar(mapEdges(this.processMap).find(function (edge) {
            return edge && edge.edgeId === edgeId;
        }));
        return true;
    };

    ProcessMapEditor.prototype.dismissRoutePlan = function () {
        const edgeId = this.routePlan && this.routePlan.edgeId;
        if (this.routePlan && this.routePlan.route) {
            this._recordSpatialEvent('route', 'dismissed', {
                scope: 'edge',
                scopedEdgeCount: 1,
                spatialEngineVersion: this.routePlan.route.spatialEngineVersion,
                policyVersion: this.routePlan.route.routerVersion,
                fallbackReason: this.routePlan.route.fallbackReason || null,
            });
        }
        if (!this._clearRoutePlan()) return false;
        this.renderGraph({ fit: false });
        if (edgeId && this.selectedEdgeId === edgeId) {
            this._closeCardToolbar('route_preview_changed', false);
            this._openEdgeToolbar(mapEdges(this.processMap).find(function (edge) {
                return edge && edge.edgeId === edgeId;
            }));
        }
        return true;
    };

    ProcessMapEditor.prototype.acceptRoutePlan = async function () {
        const plan = this.routePlan;
        if (!plan || this.conflict || plan.mapFingerprint !== mapFingerprint(this.processMap)) {
            this._recordSpatialEvent('route', 'stale', {
                scope: 'edge',
                scopedEdgeCount: 1,
                fallbackReason: 'map_changed',
            });
            this.operationError = 'The map changed. Preview the route again.';
            this._clearRoutePlan();
            this.renderGraph({ fit: false });
            return false;
        }
        const runtime = processMapSpatialRuntime();
        let contract;
        try {
            contract = await this._ensureSpatialContract();
            const scene = runtime.compileSpatialScene(this.processMap, { contract: contract });
            const fresh = runtime.routeOrthogonalEdge(scene, plan.edgeId, { contract: contract });
            if (!fresh.accepted
                || fresh.routeId !== plan.route.routeId
                || fresh.obstacleFingerprint !== plan.route.obstacleFingerprint
                || JSON.stringify(fresh.points) !== JSON.stringify(plan.route.points)) {
                this._recordSpatialEvent('route', 'stale', {
                    scope: 'edge',
                    scopedEdgeCount: 1,
                    spatialEngineVersion: fresh.spatialEngineVersion,
                    policyVersion: fresh.routerVersion,
                    fallbackReason: 'route_changed',
                });
                this.operationError = 'The route is stale. Preview it again.';
                this._clearRoutePlan();
                this.renderGraph({ fit: false });
                return false;
            }
            const result = runtime.applyOrthogonalRoute(this.processMap, plan.edgeId, {
                contract: contract,
            });
            if (!result.accepted) {
                this._recordSpatialEvent('route', 'failed', {
                    scope: 'edge',
                    scopedEdgeCount: 1,
                    fallbackReason: result.failureReason || 'apply_failed',
                });
                this.operationError = 'The route could not be applied.';
                return false;
            }
            this._recordSpatialEvent('route', 'accepted', {
                scope: 'edge',
                scopedEdgeCount: 1,
                spatialEngineVersion: fresh.spatialEngineVersion,
                policyVersion: fresh.routerVersion,
                fallbackReason: fresh.fallbackReason || null,
            });
            return this.commitMutation(result.map);
        } catch (error) {
            this.operationError = error && error.message ? error.message : 'The route could not be applied.';
            this.updateEditControls();
            return false;
        }
    };

    ProcessMapEditor.prototype._renderRouteGhost = function () {
        if (!this.routePlan || !this.routePlan.route || !this.routePlan.route.accepted) return;
        const points = this.routePlan.route.points || [];
        const pathValue = polylinePath(points);
        if (!pathValue) return;
        const path = svgElement('path', {
            d: pathValue,
            class: 'pm-edge pm-edge-route-preview',
            'data-route-preview-edge-id': this.routePlan.edgeId,
            'marker-end': 'url(#' + this.instanceId + ')',
            'aria-hidden': 'true',
        });
        this.edgeSvg.appendChild(path);
    };

    ProcessMapEditor.prototype._freshPlacementNodeId = function () {
        let nodeId;
        do {
            nodeId = 'pm-n-' + Date.now().toString(36) + '-' + (++this.nodeCounter);
        } while (mapNodes(this.processMap).some(function (node) { return node.nodeId === nodeId; }));
        return nodeId;
    };

    ProcessMapEditor.prototype._activePlacementCandidate = function () {
        if (!this.placementPlan) return null;
        return this.placementPlan.candidates[this.placementPlan.activeIndex] || null;
    };

    ProcessMapEditor.prototype._cancelManagedProposalRevealSchedule = function () {
        if (this.managedProposalRevealTimer !== null) {
            window.clearTimeout(this.managedProposalRevealTimer);
            this.managedProposalRevealTimer = null;
        }
        if (this.managedProposalRevealFrame !== null) {
            window.cancelAnimationFrame(this.managedProposalRevealFrame);
            this.managedProposalRevealFrame = null;
        }
    };

    ProcessMapEditor.prototype._prepareManagedProposalReveal = function (proposal) {
        this._cancelManagedProposalRevealSchedule();
        if (!proposal || proposal.managedProposalType !== 'semantic_process_map') {
            return null;
        }
        const preview = proposal.preview || {};
        const nodeIds = Array.from(new Set(
            (Array.isArray(preview.nodes) ? preview.nodes : [])
            .map(function (node) { return String(node && node.nodeId || ''); })
            .filter(Boolean)
        ));
        const edgeIds = Array.from(new Set(
            (Array.isArray(preview.edges) ? preview.edges : [])
            .map(function (edge) { return String(edge && edge.edgeId || ''); })
            .filter(Boolean)
        ));
        const sequence = managedProposalRevealSequence(preview);
        const reducedMotion = typeof window.matchMedia === 'function'
            && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        const reveal = {
            proposalId: String(proposal.proposalId || ''),
            sequence: sequence,
            index: reducedMotion ? sequence.length : 0,
            visibleNodeIds: new Set(reducedMotion ? nodeIds : []),
            visibleEdgeIds: new Set(reducedMotion ? edgeIds : []),
            nodeIds: nodeIds,
            edgeIds: edgeIds,
            active: !reducedMotion && sequence.length > 0,
            completed: reducedMotion || sequence.length === 0,
            reducedMotion: reducedMotion,
            startedAt: Date.now(),
        };
        return reveal;
    };

    ProcessMapEditor.prototype._managedProposalRevealDelay = function () {
        const reveal = this.managedProposalReveal;
        const stepCount = reveal && reveal.sequence
            ? reveal.sequence.length : 0;
        if (stepCount <= 12) return 220;
        if (stepCount <= 40) return 140;
        return 90;
    };

    ProcessMapEditor.prototype._applyManagedProposalRevealState = function (
        animate,
        newlyVisibleStep
    ) {
        const reveal = this.managedProposalReveal;
        if (!reveal || !this.placementGhostLayer || !this.placementGhostWireSvg) return;
        const newNodeIds = new Set(
            newlyVisibleStep && newlyVisibleStep.kind === 'node'
                ? newlyVisibleStep.ids : []
        );
        const newEdgeIds = new Set(
            newlyVisibleStep && newlyVisibleStep.kind === 'edges'
                ? newlyVisibleStep.ids : []
        );
        this.placementGhostLayer.querySelectorAll(
            '[data-managed-proposal-node-id], [data-managed-proposal-junction-id]'
        ).forEach(function (element) {
            const nodeId = String(
                element.getAttribute('data-managed-proposal-node-id')
                || element.getAttribute('data-managed-proposal-junction-id')
                || ''
            );
            const visible = reveal.visibleNodeIds.has(nodeId);
            element.classList.toggle('pm-managed-proposal-pending', !visible);
            element.classList.toggle('pm-managed-proposal-revealed', visible);
            if (!visible) {
                element.classList.remove('pm-managed-proposal-entering');
            } else if (animate && newNodeIds.has(nodeId)) {
                element.classList.add('pm-managed-proposal-entering');
            }
            element.setAttribute(
                'data-managed-proposal-reveal-state',
                visible ? 'revealed' : 'pending'
            );
        });
        this.placementGhostWireSvg.querySelectorAll(
            '[data-managed-proposal-edge-id]'
        ).forEach(function (element) {
            const edgeId = String(
                element.getAttribute('data-managed-proposal-edge-id') || ''
            );
            const visible = reveal.visibleEdgeIds.has(edgeId);
            const drawing = !!(animate && visible && newEdgeIds.has(edgeId));
            element.classList.toggle('pm-managed-proposal-pending', !visible);
            element.classList.toggle('pm-managed-proposal-revealed', visible);
            if (!visible) {
                element.classList.remove('pm-managed-proposal-wire-drawing');
            } else if (drawing) {
                element.classList.add('pm-managed-proposal-wire-drawing');
            }
            element.setAttribute(
                'data-managed-proposal-reveal-state',
                visible ? 'revealed' : 'pending'
            );
            if (drawing && typeof element.getTotalLength === 'function') {
                const pathLength = Math.max(1, Math.ceil(element.getTotalLength()));
                element.style.setProperty(
                    '--pm-managed-route-length',
                    pathLength + 'px'
                );
            } else if (!element.classList.contains(
                'pm-managed-proposal-wire-drawing'
            )) {
                element.style.removeProperty('--pm-managed-route-length');
            }
        });
    };

    ProcessMapEditor.prototype._completeManagedProposalReveal = function (skipped) {
        const reveal = this.managedProposalReveal;
        if (!reveal || reveal.completed) return false;
        this._cancelManagedProposalRevealSchedule();
        reveal.nodeIds.forEach(function (nodeId) {
            reveal.visibleNodeIds.add(nodeId);
        });
        reveal.edgeIds.forEach(function (edgeId) {
            reveal.visibleEdgeIds.add(edgeId);
        });
        reveal.index = reveal.sequence.length;
        reveal.active = false;
        reveal.completed = true;
        reveal.completedAt = Date.now();
        reveal.skipped = !!skipped;
        this._applyManagedProposalRevealState(false, null);
        this._renderManagedProposalReview();
        this._recordSpatialEvent(
            'agent_layout',
            skipped ? 'reveal_skipped' : 'reveal_completed',
            {
                scope: 'map',
                scopedNodeCount: reveal.nodeIds.length,
                scopedEdgeCount: reveal.edgeIds.length,
            }
        );
        return true;
    };

    ProcessMapEditor.prototype._advanceManagedProposalReveal = function () {
        const reveal = this.managedProposalReveal;
        const plan = this.managedProposalPlan;
        if (!reveal || !reveal.active || !plan
            || reveal.proposalId !== String(plan.proposalId || '')) return;
        if (reveal.index >= reveal.sequence.length) {
            this._completeManagedProposalReveal(false);
            return;
        }
        const step = reveal.sequence[reveal.index++];
        const target = step.kind === 'edges'
            ? reveal.visibleEdgeIds : reveal.visibleNodeIds;
        step.ids.forEach(function (itemId) {
            target.add(itemId);
        });
        this._applyManagedProposalRevealState(true, step);
        this._renderManagedProposalReview();
        if (reveal.index >= reveal.sequence.length) {
            this.managedProposalRevealTimer = window.setTimeout(function () {
                this.managedProposalRevealTimer = null;
                this._completeManagedProposalReveal(false);
            }.bind(this), 360);
            return;
        }
        this.managedProposalRevealTimer = window.setTimeout(function () {
            this.managedProposalRevealTimer = null;
            this._advanceManagedProposalReveal();
        }.bind(this), this._managedProposalRevealDelay());
    };

    ProcessMapEditor.prototype._startManagedProposalReveal = function () {
        const reveal = this.managedProposalReveal;
        if (!reveal || !reveal.active) {
            this._applyManagedProposalRevealState(false, null);
            this._renderManagedProposalReview();
            return false;
        }
        this._applyManagedProposalRevealState(false, null);
        this.managedProposalRevealFrame = window.requestAnimationFrame(function () {
            this.managedProposalRevealFrame = null;
            this.managedProposalRevealTimer = window.setTimeout(function () {
                this.managedProposalRevealTimer = null;
                this._advanceManagedProposalReveal();
            }.bind(this), 160);
        }.bind(this));
        return true;
    };

    ProcessMapEditor.prototype.showAllManagedProposal = function () {
        const reveal = this.managedProposalReveal;
        if (!reveal || !reveal.active || this.managedProposalBusy) return false;
        return this._completeManagedProposalReveal(true);
    };

    ProcessMapEditor.prototype._clearManagedProposal = function () {
        if (!this.managedProposalPlan && !this.managedProposalBusy
            && !this.managedProposalReveal) return false;
        this._cancelManagedProposalRevealSchedule();
        this.managedProposalPlan = null;
        this.managedProposalBusy = false;
        this.managedProposalGeometry = null;
        this.managedProposalReveal = null;
        if (this.managedProposalReview) this.managedProposalReview.hidden = true;
        return true;
    };

    ProcessMapEditor.prototype.showManagedProposal = function (proposal) {
        const preview = proposal && proposal.preview;
        const managedProposalType = String(
            proposal && proposal.managedProposalType || ''
        );
        const trustedProposal = !!(proposal && proposal.spatialBindingHash)
            || !!(proposal && proposal.semanticBindingHash)
            || managedProposalType === 'process_metadata';
        const hasPreview = preview && (
            (Array.isArray(preview.nodes) && preview.nodes.length)
            || (Array.isArray(preview.edges) && preview.edges.length)
            || (Array.isArray(preview.groups) && preview.groups.length)
        );
        if (!this.editable || this.dirty || this.saving || this.conflict
            || !proposal || !proposal.proposalId || !trustedProposal
            || proposal.baseRevision !== this.revision || !hasPreview) {
            this.operationError = this.dirty
                ? 'Save or discard local changes before reviewing an agent proposal.'
                : 'The agent proposal does not match this saved process map.';
            this.updateEditControls();
            return false;
        }
        this._clearPlacementPlan();
        this._clearRoutePlan();
        this._closeCardToolbar('managed_proposal_opened', false);
        this.managedProposalPlan = cloneMap(proposal);
        this.managedProposalBusy = false;
        this.managedProposalReveal = this._prepareManagedProposalReveal(
            this.managedProposalPlan
        );
        this.operationError = '';
        this._recordSpatialEvent('agent_layout', 'previewed', {
            scope: 'map',
            scopedNodeCount: Array.isArray(preview.nodes) ? preview.nodes.length : 0,
            scopedEdgeCount: Array.isArray(preview.edges) ? preview.edges.length : 0,
        });
        this.renderGraph({ fit: true });
        this._startManagedProposalReveal();
        return true;
    };

    ProcessMapEditor.prototype.dismissManagedProposal = function () {
        const preview = this.managedProposalPlan && this.managedProposalPlan.preview || {};
        if (this.managedProposalPlan) {
            this._recordSpatialEvent('agent_layout', 'dismissed', {
                scope: 'map',
                scopedNodeCount: Array.isArray(preview.nodes) ? preview.nodes.length : 0,
                scopedEdgeCount: Array.isArray(preview.edges) ? preview.edges.length : 0,
            });
        }
        if (!this._clearManagedProposal()) return false;
        this.renderGraph({ fit: true });
        return true;
    };

    ProcessMapEditor.prototype._openManagedProposalVisualValidation = function () {
        const report = this.managedProposalPlan
            && this.managedProposalPlan.visualValidation;
        const url = report && report.artifact && report.artifact.url;
        if (!url) return false;
        const opened = window.open(String(url), '_blank', 'noopener,noreferrer');
        if (opened) opened.opener = null;
        return true;
    };

    ProcessMapEditor.prototype.approveManagedProposal = async function () {
        const plan = this.managedProposalPlan;
        const requiresSpatialWrite = !!(
            plan && (plan.spatialBindingHash || plan.semanticBindingHash)
        );
        const writeEnabled = this.managedProposalWriteEnabled
            && (!requiresSpatialWrite || this.agentLayoutWriteEnabled);
        if (!plan || this.managedProposalBusy || this.dirty || this.conflict
            || (this.managedProposalReveal && this.managedProposalReveal.active)
            || !writeEnabled
            || plan.baseRevision !== this.revision
            || typeof this.options.onApproveManagedProposal !== 'function') return false;
        this.managedProposalBusy = true;
        this.updateEditControls();
        this._renderManagedProposalReview();
        try {
            const before = cloneMap(this.processMap);
            const result = await this.options.onApproveManagedProposal(cloneMap(plan));
            if (!result || result.ok === false || !result.map) {
                this._recordSpatialEvent('agent_layout', result && result.status === 409
                    ? 'stale' : 'failed', {
                    scope: 'map',
                    fallbackReason: result && result.status === 409
                        ? 'revision_conflict' : 'apply_failed',
                });
                this.operationError = String(result && (result.error || result.detail)
                    || 'The agent proposal could not be applied.');
                this.conflict = !!(result && result.status === 409);
                if (this.conflict) this._clearManagedProposal();
                this.renderGraph({ fit: false });
                return false;
            }
            this.processMap = cloneMap(result.map);
            this.revision = result.revision || this.revision;
            if (result.productStructure) this.setProductStructure(result.productStructure);
            if (result.mapCatalog) this.setMapCatalog(result.mapCatalog);
            this.findings = Array.isArray(result.findings) ? result.findings : [];
            this.savedMap = cloneMap(this.processMap);
            this.savedFingerprint = mapFingerprint(this.savedMap);
            this.history.clear();
            this.history.record(before);
            this._clearSuggestions();
            this._clearPlacementPlan();
            this._clearArrangementPlan();
            this._clearRoutePlan();
            this._clearManagedProposal();
            this._resetGraphSelectionState();
            this.conflict = false;
            this.operationError = '';
            this._setDirty(false);
            this._notifyMapChange();
            this.renderGraph({ fit: false });
            if (typeof this.options.onManagedProposalReceipt === 'function') {
                this.options.onManagedProposalReceipt(cloneMap(result.receipt || {}));
            }
            this._scheduleSuggestionLoad();
            this._recordSpatialEvent('agent_layout', 'accepted', {
                scope: 'map',
            });
            return true;
        } catch (error) {
            this.operationError = error && error.message
                ? error.message : 'The agent proposal could not be applied.';
            this.renderGraph({ fit: false });
            return false;
        } finally {
            this.managedProposalBusy = false;
            this.updateEditControls();
            this._renderManagedProposalReview();
        }
    };

    ProcessMapEditor.prototype._renderManagedProposalReview = function () {
        if (!this.managedProposalReview) return;
        const plan = this.managedProposalPlan;
        this.managedProposalReview.hidden = !plan;
        if (!plan) return;
        const preview = plan.preview || {};
        const nodeCount = Array.isArray(preview.nodes) ? preview.nodes.length : 0;
        const edgeCount = Array.isArray(preview.edges) ? preview.edges.length : 0;
        const message = plan.summary && plan.summary.message
            ? String(plan.summary.message) : 'Review the exact agent layout proposal.';
        const isMetadata = plan.managedProposalType === 'process_metadata';
        const isSemantic = plan.managedProposalType === 'semantic_process_map';
        const reveal = isSemantic ? this.managedProposalReveal : null;
        const revealActive = !!(reveal && reveal.active);
        const revealProgress = revealActive
            ? (
                'Building preview: '
                + reveal.visibleNodeIds.size + ' of ' + reveal.nodeIds.length
                + ' elements, '
                + reveal.visibleEdgeIds.size + ' of ' + reveal.edgeIds.length
                + ' routes. '
            )
            : '';
        const requiresSpatialWrite = !!(
            plan.spatialBindingHash || plan.semanticBindingHash
        );
        const writeEnabled = this.managedProposalWriteEnabled
            && (!requiresSpatialWrite || this.agentLayoutWriteEnabled);
        if (isMetadata) {
            const summary = plan.summary || {};
            this.managedProposalCopy.textContent = message + ' '
                + Number(summary.nodeRequirementSetsPopulated || 0) + ' card requirement sets, '
                + Number(summary.routeNamesPopulated || 0) + ' route names, and '
                + Number(summary.routeRequirementSetsPopulated || 0) + ' routing requirement sets.'
                + (summary.unresolvedCount
                    ? ' ' + Number(summary.unresolvedCount) + ' unresolved items will be left unchanged.'
                    : ' All targets matched.')
                + ' Demo data is not production-approved.'
                + (writeEnabled ? '' : ' Review only; Builder writes are disabled.');
        } else if (isSemantic) {
            const summary = plan.summary || {};
            const visual = plan.visualValidation || null;
            let visualCopy = '';
            if (visual && visual.status === 'corrected') {
                visualCopy = ' Visual validation applied '
                    + Number(visual.correctionCount || 0)
                    + ' inferred '
                    + (Number(visual.correctionCount || 0) === 1
                        ? 'correction.' : 'corrections.');
            } else if (visual && visual.status === 'passed') {
                visualCopy = ' Visual validation found no occurrence-grouping conflicts.';
            } else if (visual && visual.status === 'needs_review') {
                visualCopy = ' Visual validation left '
                    + Number((visual.unresolvedItems || []).length)
                    + ' '
                    + (Number((visual.unresolvedItems || []).length) === 1
                        ? 'item' : 'items')
                    + ' for review.';
            } else if (visual && visual.status === 'unavailable') {
                visualCopy = ' Automated visual validation was unavailable; review the contact sheet.';
            }
            this.managedProposalCopy.textContent = revealActive
                ? (
                    revealProgress
                    + 'Elements and routes are appearing in process order. '
                    + 'Nothing is saved until approval.'
                )
                : (
                    message + ' '
                    + Number(summary.requiredOccurrenceCount || 0) + ' required parts, '
                    + Number(summary.operationCount || 0) + ' stages, '
                    + Number(summary.connectionCount || 0) + ' connections, and '
                    + Number(summary.assumptionCount || 0) + ' assumptions.'
                    + (summary.unresolvedCount
                        ? ' ' + Number(summary.unresolvedCount) + ' unresolved items remain.'
                        : ' No unresolved items.')
                    + visualCopy
                    + (writeEnabled
                        ? '' : ' Review only; agent layout writes are disabled.')
                );
        } else {
            this.managedProposalCopy.textContent = message + ' '
                + nodeCount + (nodeCount === 1 ? ' card' : ' cards') + ', '
                + edgeCount + (edgeCount === 1 ? ' connection' : ' connections') + ' changed.'
                + (writeEnabled ? '' : ' Review only; agent layout writes are disabled.');
        }
        this.managedProposalReview.setAttribute(
            'aria-busy',
            revealActive ? 'true' : 'false'
        );
        this.managedProposalApproveButton.disabled = this.managedProposalBusy
            || revealActive || !writeEnabled;
        this.managedProposalApproveButton.title = revealActive
            ? 'Wait for the progressive build to finish or choose Show all'
            : (writeEnabled
                ? 'Approve and apply this exact process-map proposal'
                : (isMetadata ? 'Builder writes are disabled' : 'Agent layout writes are disabled'));
        if (this.managedProposalShowAllButton) {
            this.managedProposalShowAllButton.hidden = !revealActive;
            this.managedProposalShowAllButton.disabled = (
                this.managedProposalBusy || !revealActive
            );
        }
        this.managedProposalDismissButton.disabled = this.managedProposalBusy;
        if (this.managedProposalVisualButton) {
            const visualUrl = plan.visualValidation
                && plan.visualValidation.artifact
                && plan.visualValidation.artifact.url;
            this.managedProposalVisualButton.hidden = !visualUrl || revealActive;
            this.managedProposalVisualButton.disabled = (
                this.managedProposalBusy || revealActive || !visualUrl
            );
        }
    };

    ProcessMapEditor.prototype._renderManagedProposalPreview = function () {
        this._managedProposalGhostElement = null;
        this._renderManagedProposalReview();
        const plan = this.managedProposalPlan;
        if (!plan) return false;
        const isMetadata = plan.managedProposalType === 'process_metadata';
        const layout = this.managedProposalGeometry || managedProposalGeometry(
            this.processMap,
            plan.preview,
            this.occurrenceById
        );
        const previewNodes = layout.nodes;
        const positions = layout.positions;
        const changedNodeIds = new Set((plan.preview.nodes || []).map(function (node) {
            return node && node.nodeId;
        }));
        previewNodes.forEach(function (node) {
            if (!node || !changedNodeIds.has(node.nodeId)) return;
            const position = positions[node.nodeId];
            if (!position) return;
            if (isJunctionNode(node)) {
                const junctionType = JUNCTION_TYPES.indexOf(node.junctionType) >= 0
                    ? node.junctionType : 'wire_branch';
                const wrapper = document.createElement('div');
                wrapper.className = 'pm-junction pm-junction-type-' + junctionType
                    + ' pm-managed-proposal-junction';
                this._positionNodeElement(wrapper, position);
                wrapper.style.width = JUNCTION_HIT_SIZE + 'px';
                wrapper.style.height = JUNCTION_HIT_SIZE + 'px';
                wrapper.setAttribute('data-managed-proposal-junction-id', node.nodeId);
                wrapper.setAttribute('aria-hidden', 'true');
                const dot = document.createElement('span');
                dot.className = 'pm-junction-dot';
                dot.style.width = '20px';
                dot.style.height = '20px';
                const symbol = document.createElement('span');
                symbol.className = 'pm-junction-symbol';
                symbol.textContent = {
                    parallel_and: 'AND',
                    merge: 'M',
                    split: 'S',
                }[junctionType] || '';
                if (symbol.textContent) dot.appendChild(symbol);
                wrapper.appendChild(dot);
                this.placementGhostLayer.appendChild(wrapper);
                if (!this._managedProposalGhostElement) {
                    this._managedProposalGhostElement = wrapper;
                }
                return;
            }
            const processStep = node.nodeKind === 'process_step';
            const semanticStatus = String(
                node.semantic && node.semantic.knowledgeStatus || ''
            );
            const ghost = this._appendPlacementGhostCard({
                position: position,
                portOrientation: nodePortOrientation(node),
                portOrder: nodePortOrder(node),
                previewNode: node,
                className: 'pm-managed-proposal-ghost '
                    + (processStep
                        ? 'pm-managed-proposal-stage'
                        : 'pm-managed-proposal-part'),
                dataAttribute: { name: 'data-managed-proposal-node-id', value: node.nodeId },
                label: node.name || node.nameSnapshot || node.labelOverride || node.nodeId,
                meta: isMetadata
                    ? 'Illustrative requirements'
                    : (processStep ? 'Operation / Stage' : 'Required part'),
                summary: isMetadata
                    ? 'Pending approval'
                    : (semanticStatus === 'inferred'
                        ? 'Inferred - pending approval'
                        : 'Not applied'),
            });
            if (!this._managedProposalGhostElement) this._managedProposalGhostElement = ghost;
        }, this);
        (plan.preview.edges || []).forEach(function (edge) {
            if (!edge || !edge.edgeId) return;
            const geometry = layout.edgeGeometries[edge.edgeId]
                || edgeGeometry(edge, positions, {
                    routingEnabled: true,
                    inputPortSlots: layout.inputPortLayout.byEdge,
                });
            if (!geometry || !geometry.path) return;
            this.placementGhostWireSvg.appendChild(svgElement('path', {
                d: geometry.path,
                class: 'pm-edge pm-placement-ghost-wire pm-managed-proposal-wire',
                'data-managed-proposal-edge-id': edge.edgeId,
                'marker-end': 'url(#' + this.instanceId + ')',
                'aria-hidden': 'true',
            }));
        }, this);
        this._applyManagedProposalRevealState(false, null);
        return true;
    };

    ProcessMapEditor.prototype._clearPlacementPlan = function () {
        this.placementPlanRequestToken += 1;
        if (!this.placementPlan && !this.batchPlacementPlan) return;
        this.placementPlan = null;
        this.batchPlacementPlan = null;
        this._placementGhostElement = null;
        this._batchPlacementGhostElement = null;
        this._closeCardToolbar('placement_plan_cleared', false);
    };

    ProcessMapEditor.prototype._buildPlacementScene = function (contract) {
        const runtime = processMapSpatialRuntime();
        return runtime.compileSpatialScene(this.processMap, {
            contract: contract,
            revision: this.revision,
        });
        (Array.isArray(edgeGeometries) ? edgeGeometries : []).forEach(function (geometry) {
            if (!geometry || !geometry.bounds) return;
            values.push(geometry.bounds);
        });
    };

    ProcessMapEditor.prototype._visibleWorldRect = function () {
        if (!this.viewport) return null;
        const bounds = this.viewport.getBoundingClientRect();
        if (!bounds.width || !bounds.height || !(this.transform.scale > 0)) return null;
        const topLeft = this.clientToWorld(bounds.left, bounds.top);
        const bottomRight = this.clientToWorld(bounds.right, bounds.bottom);
        return {
            x: topLeft.x,
            y: topLeft.y,
            width: bottomRight.x - topLeft.x,
            height: bottomRight.y - topLeft.y,
        };
    };

    ProcessMapEditor.prototype._revealPlacementCandidate = function () {
        const candidate = this._activePlacementCandidate();
        if (!candidate || !this.viewport || !(this.transform.scale > 0)) return false;
        const viewport = this.viewport.getBoundingClientRect();
        if (!viewport.width || !viewport.height) return false;
        const padding = 32;
        const scale = this.transform.scale;
        const left = this.transform.x + candidate.position.x * scale;
        const top = this.transform.y + candidate.position.y * scale;
        const right = left + NODE_WIDTH * scale;
        const bottom = top + NODE_HEIGHT * scale;
        let deltaX = 0;
        let deltaY = 0;
        if (left < padding) deltaX = padding - left;
        else if (right > viewport.width - padding) deltaX = viewport.width - padding - right;
        if (top < padding) deltaY = padding - top;
        else if (bottom > viewport.height - padding) deltaY = viewport.height - padding - bottom;
        if (!deltaX && !deltaY) return false;
        this.transform.x += deltaX;
        this.transform.y += deltaY;
        this.applyTransform();
        return true;
    };

    ProcessMapEditor.prototype._runPlacementPlanner = async function (planInput) {
        if (!this.spatialPlacementEnabled || !this.editable || this.conflict
            || !isPlacementMap(this.processMap)) {
            return false;
        }
        const runtime = processMapSpatialRuntime();
        if (!runtime || typeof runtime.generatePlacementCandidates !== 'function') return false;
        const startedAt = Date.now();
        if (this.batchPlacementPlan) this._clearPlacementPlan();
        const requestToken = ++this.placementPlanRequestToken;
        let contract;
        try {
            contract = await this._ensureSpatialContract();
        } catch (error) {
            if (requestToken === this.placementPlanRequestToken) {
                this.operationError = 'Position suggestions are temporarily unavailable.';
                this.updateEditControls();
            }
            return false;
        }
        if (requestToken !== this.placementPlanRequestToken || this.destroyed || this.conflict) return false;
        let scene;
        let result;
        try {
            scene = this._buildPlacementScene(contract);
            result = runtime.generatePlacementCandidates(scene, {
                contract: contract,
                targetKind: planInput.targetKind,
                targetNodeId: planInput.targetNodeId || null,
                anchorNodeId: planInput.anchorNodeId || null,
                connectionDirection: planInput.connectionDirection || null,
                requiredGroupId: planInput.requiredGroupId || null,
                preferredFlowDirection: 'left_to_right',
                visibleWorldRect: planInput.visibleWorldRect || null,
                limit: 3,
            });
        } catch (error) {
            if (requestToken === this.placementPlanRequestToken) {
                this._recordSpatialEvent('placement', 'failed', {
                    scope: planInput.targetNodeId ? 'node' : 'map',
                    scopedNodeCount: 1,
                    latencyMs: Date.now() - startedAt,
                    fallbackReason: 'planner_error',
                });
                this.operationError = 'This layout cannot be planned automatically right now.';
                this.updateEditControls();
            }
            return false;
        }
        if (requestToken !== this.placementPlanRequestToken || this.destroyed || this.conflict) return false;
        if (!result.candidates.length) {
            this._recordSpatialEvent('placement', 'failed', {
                scope: planInput.targetNodeId ? 'node' : 'map',
                scopedNodeCount: 1,
                candidatesEvaluated: result.evaluatedCount,
                rejectionCounts: result.rejectionCounts,
                latencyMs: Date.now() - startedAt,
                spatialEngineVersion: result.spatialEngineVersion,
                policyVersion: result.candidatePolicyVersion,
                fallbackReason: 'no_candidate',
            });
            this.operationError = 'No clean position was found for this card.';
            this.updateEditControls();
            return false;
        }
        this.placementPlan = {
            isNew: !!planInput.isNew,
            nodeKind: planInput.targetKind,
            nodeId: planInput.isNew ? this._freshPlacementNodeId() : planInput.targetNodeId,
            sourceOccurrenceId: planInput.sourceOccurrenceId || null,
            nameSnapshot: planInput.nameSnapshot || null,
            itemIdSnapshot: planInput.itemIdSnapshot || null,
            processType: planInput.processType || null,
            name: planInput.name || null,
            connection: planInput.anchorNodeId
                ? {
                    anchorNodeId: planInput.anchorNodeId,
                    direction: planInput.connectionDirection || 'outgoing',
                    kind: 'precedence',
                }
                : null,
            candidates: result.candidates,
            activeIndex: 0,
            mapRevision: this.revision,
            mapFingerprint: mapFingerprint(this.processMap),
            obstacleFingerprint: result.obstacleFingerprint,
            spatialEngineVersion: result.spatialEngineVersion,
            candidatePolicyVersion: result.candidatePolicyVersion,
            candidatesEvaluated: result.evaluatedCount,
            rejectionCounts: cloneMap(result.rejectionCounts || {}),
            previewLatencyMs: Date.now() - startedAt,
            plannerRequest: {
                targetKind: planInput.targetKind,
                targetNodeId: planInput.targetNodeId || null,
                anchorNodeId: planInput.anchorNodeId || null,
                connectionDirection: planInput.connectionDirection || null,
                requiredGroupId: planInput.requiredGroupId || null,
                preferredFlowDirection: 'left_to_right',
                visibleWorldRect: planInput.visibleWorldRect
                    ? cloneMap(planInput.visibleWorldRect)
                    : null,
            },
        };
        this.operationError = '';
        this._recordSpatialEvent('placement', 'previewed', {
            scope: planInput.targetNodeId ? 'node' : 'map',
            scopedNodeCount: 1,
            candidatesEvaluated: result.evaluatedCount,
            rejectionCounts: result.rejectionCounts,
            latencyMs: Date.now() - startedAt,
            spatialEngineVersion: result.spatialEngineVersion,
            policyVersion: result.candidatePolicyVersion,
        });
        this.renderGraph({ fit: false });
        this._revealPlacementCandidate();
        this._openPlacementGhostToolbar();
        return true;
    };

    ProcessMapEditor.prototype.previewOccurrencePlacement = function (occurrenceId, anchorNodeId, connectionDirection) {
        const occurrence = this.occurrenceById.get(occurrenceId);
        if (!occurrence || !isPlacementMap(this.processMap)) return false;
        const alreadyPlaced = mapNodes(this.processMap).some(function (node) {
            return node && node.nodeKind === 'product_occurrence' && node.sourceOccurrenceId === occurrenceId;
        });
        if (alreadyPlaced) return false;
        return this._runPlacementPlanner({
            isNew: true,
            targetKind: 'product_occurrence',
            sourceOccurrenceId: occurrenceId,
            nameSnapshot: occurrence.name || occurrenceId,
            itemIdSnapshot: occurrence.itemId || null,
            anchorNodeId: anchorNodeId || null,
            connectionDirection: connectionDirection || null,
            visibleWorldRect: this._visibleWorldRect(),
        }) !== false;
    };

    ProcessMapEditor.prototype.suggestSelectedNodePlacement = function () {
        const states = this.selectedNodeCommandStates();
        if (!states.canSuggestPosition) return false;
        const node = states.node;
        return this._runPlacementPlanner({
            isNew: false,
            targetKind: node.nodeKind,
            targetNodeId: node.nodeId,
            visibleWorldRect: this._visibleWorldRect(),
        }) !== false;
    };

    ProcessMapEditor.prototype.cyclePlacementAlternative = function () {
        if (!this.placementPlan || this.placementPlan.candidates.length < 2) return false;
        this.placementPlan.activeIndex = (this.placementPlan.activeIndex + 1) % this.placementPlan.candidates.length;
        this._recordSpatialEvent('placement', 'alternative_selected', {
            scope: this.placementPlan.isNew ? 'map' : 'node',
            scopedNodeCount: 1,
            candidatesEvaluated: this.placementPlan.candidatesEvaluated,
            rejectionCounts: this.placementPlan.rejectionCounts,
            spatialEngineVersion: this.placementPlan.spatialEngineVersion,
            policyVersion: this.placementPlan.candidatePolicyVersion,
        });
        this.renderGraph({ fit: false });
        this._revealPlacementCandidate();
        this._syncPlacementGhostToolbar();
        return true;
    };

    ProcessMapEditor.prototype._computeRequiredBatchPlacement = function (definition, contract) {
        const runtime = processMapSpatialRuntime();
        if (!runtime || typeof runtime.generatePlacementCandidates !== 'function') {
            throw new Error('spatial_placement_runtime_unavailable');
        }
        let transient = cloneMap(this.processMap);
        const entries = [];
        let evaluatedCount = 0;
        const rejectionCounts = {};
        let anchorNodeId = definition.anchorNodeId || null;
        for (let index = 0; index < definition.occurrenceIds.length; index += 1) {
            const occurrenceId = definition.occurrenceIds[index];
            const occurrence = this.occurrenceById.get(occurrenceId);
            if (!occurrence) throw new Error('unknown_required_occurrence');
            const scene = runtime.compileSpatialScene(transient, {
                contract: contract,
                revision: this.revision,
            });
            const candidates = runtime.generatePlacementCandidates(scene, {
                contract: contract,
                targetKind: 'product_occurrence',
                anchorNodeId: anchorNodeId,
                connectionDirection: null,
                preferredFlowDirection: 'left_to_right',
                visibleWorldRect: index === 0 ? definition.visibleWorldRect : null,
                limit: 1,
            });
            evaluatedCount += Number(candidates.evaluatedCount) || 0;
            Object.keys(candidates.rejectionCounts || {}).forEach(function (code) {
                rejectionCounts[code] = (rejectionCounts[code] || 0)
                    + (Number(candidates.rejectionCounts[code]) || 0);
            });
            if (!candidates.candidates.length) throw new Error('no_clean_batch_position');
            const candidate = candidates.candidates[0];
            const nodeId = definition.nodeIds[index];
            const accepted = acceptPlacementCandidate(transient, {
                nodeId: nodeId,
                isNew: true,
                nodeKind: 'product_occurrence',
                sourceOccurrenceId: occurrenceId,
                nameSnapshot: occurrence.name || occurrenceId,
                itemIdSnapshot: occurrence.itemId || null,
                position: candidate.position,
                portOrientation: candidate.portOrientation,
                portOrder: candidate.portOrder,
                connection: null,
            });
            if (!accepted.accepted) throw new Error('batch_placement_rejected');
            transient = accepted.map;
            entries.push({
                nodeId: nodeId,
                sourceOccurrenceId: occurrenceId,
                nameSnapshot: occurrence.name || occurrenceId,
                itemIdSnapshot: occurrence.itemId || null,
                candidate: candidate,
                obstacleFingerprint: candidates.obstacleFingerprint,
            });
            anchorNodeId = nodeId;
        }
        return {
            map: transient,
            entries: entries,
            evaluatedCount: evaluatedCount,
            rejectionCounts: rejectionCounts,
        };
    };

    ProcessMapEditor.prototype.previewRequiredOccurrencesBatch = async function () {
        const selection = this.requiredOccurrenceSelection;
        if (!selection || !this.spatialPlacementEnabled || this.saving || this.conflict) return false;
        const placed = this._placedOccurrenceIds();
        const occurrenceIds = selection.requiredOccurrenceIds.filter(function (occurrenceId) {
            return !placed.has(occurrenceId);
        });
        if (!occurrenceIds.length) return false;
        const startedAt = Date.now();
        this._clearPlacementPlan();
        this._clearManagedProposal();
        const token = ++this.placementPlanRequestToken;
        const nodeIds = occurrenceIds.map(function () { return this._freshPlacementNodeId(); }, this);
        const selectedAnchor = mapNodes(this.processMap).some(function (node) {
            return node && node.nodeId === this.selectedNodeId && !isJunctionNode(node);
        }, this) ? this.selectedNodeId : null;
        const definition = {
            scopeOccurrenceId: selection.scopeOccurrenceId,
            occurrenceIds: occurrenceIds,
            nodeIds: nodeIds,
            anchorNodeId: selectedAnchor,
            visibleWorldRect: this._visibleWorldRect(),
        };
        let contract;
        let computed;
        try {
            contract = await this._ensureSpatialContract();
            computed = this._computeRequiredBatchPlacement(definition, contract);
        } catch (_) {
            if (token === this.placementPlanRequestToken) {
                this._recordSpatialEvent('batch_placement', 'failed', {
                    scope: 'required_parts',
                    scopedNodeCount: occurrenceIds.length,
                    latencyMs: Date.now() - startedAt,
                    fallbackReason: 'no_clean_batch',
                });
                this.operationError = 'The remaining required parts could not be arranged without overlap.';
                this.updateEditControls();
            }
            return false;
        }
        if (this.destroyed || token !== this.placementPlanRequestToken || this.conflict) return false;
        this.batchPlacementPlan = {
            definition: definition,
            entries: computed.entries,
            mapRevision: this.revision,
            mapFingerprint: mapFingerprint(this.processMap),
            scopeOccurrenceId: selection.scopeOccurrenceId,
            candidatesEvaluated: computed.evaluatedCount,
            rejectionCounts: computed.rejectionCounts,
        };
        this.operationError = '';
        this._recordSpatialEvent('batch_placement', 'previewed', {
            scope: 'required_parts',
            scopedNodeCount: occurrenceIds.length,
            candidatesEvaluated: computed.evaluatedCount,
            rejectionCounts: computed.rejectionCounts,
            latencyMs: Date.now() - startedAt,
        });
        this.renderGraph({ fit: false });
        this._openBatchPlacementToolbar();
        return true;
    };

    ProcessMapEditor.prototype.dismissBatchPlacementPlan = function () {
        if (!this.batchPlacementPlan) return false;
        this._recordSpatialEvent('batch_placement', 'dismissed', {
            scope: 'required_parts',
            scopedNodeCount: this.batchPlacementPlan.entries.length,
            candidatesEvaluated: this.batchPlacementPlan.candidatesEvaluated,
            rejectionCounts: this.batchPlacementPlan.rejectionCounts,
        });
        this._clearPlacementPlan();
        this.renderGraph({ fit: false });
        return true;
    };

    ProcessMapEditor.prototype.acceptBatchPlacementPlan = async function () {
        const plan = this.batchPlacementPlan;
        if (!plan || this.saving || this.conflict) return false;
        if (String(this.revision || '') !== String(plan.mapRevision || '')
            || mapFingerprint(this.processMap) !== plan.mapFingerprint
            || !this.requiredOccurrenceSelection
            || this.requiredOccurrenceSelection.scopeOccurrenceId !== plan.scopeOccurrenceId) {
            this._recordSpatialEvent('batch_placement', 'stale', {
                scope: 'required_parts',
                scopedNodeCount: plan.entries.length,
                candidatesEvaluated: plan.candidatesEvaluated,
                fallbackReason: 'map_or_scope_changed',
            });
            this.operationError = 'The map or required-parts result changed. Preview the batch again.';
            this._clearPlacementPlan();
            this.renderGraph({ fit: false });
            return false;
        }
        let computed;
        try {
            const contract = await this._ensureSpatialContract();
            computed = this._computeRequiredBatchPlacement(plan.definition, contract);
        } catch (_) {
            this.operationError = 'The batch could not be revalidated without overlap.';
            this.updateEditControls();
            return false;
        }
        if (JSON.stringify(computed.entries) !== JSON.stringify(plan.entries)) {
            this._recordSpatialEvent('batch_placement', 'stale', {
                scope: 'required_parts',
                scopedNodeCount: plan.entries.length,
                candidatesEvaluated: computed.evaluatedCount,
                rejectionCounts: computed.rejectionCounts,
                fallbackReason: 'batch_changed',
            });
            this.operationError = 'The layout changed since this batch was previewed. Try again.';
            this._clearPlacementPlan();
            this.renderGraph({ fit: false });
            return false;
        }
        this._recordSpatialEvent('batch_placement', 'accepted', {
            scope: 'required_parts',
            scopedNodeCount: plan.entries.length,
            candidatesEvaluated: computed.evaluatedCount,
            rejectionCounts: computed.rejectionCounts,
        });
        this._clearPlacementPlan();
        return this.commitMutation(computed.map);
    };

    ProcessMapEditor.prototype.dismissPlacementPlan = function () {
        if (!this.placementPlan) return false;
        this._recordSpatialEvent('placement', 'dismissed', {
            scope: this.placementPlan.isNew ? 'map' : 'node',
            scopedNodeCount: 1,
            candidatesEvaluated: this.placementPlan.candidatesEvaluated,
            rejectionCounts: this.placementPlan.rejectionCounts,
            spatialEngineVersion: this.placementPlan.spatialEngineVersion,
            policyVersion: this.placementPlan.candidatePolicyVersion,
        });
        this._clearPlacementPlan();
        this.renderGraph({ fit: false });
        return true;
    };

    ProcessMapEditor.prototype.acceptPlacementPlan = async function () {
        const plan = this.placementPlan;
        const candidate = this._activePlacementCandidate();
        if (!plan || !candidate || this.saving || this.conflict) return false;
        const runtime = processMapSpatialRuntime();
        if (!runtime) return false;

        // Revalidate immediately before acceptance: the map may have
        // changed since the plan was computed (another edit, a save/
        // reload, or simply time passing). Fail closed on any mismatch
        // rather than trust a stale plan.
        if (String(this.revision || '') !== String(plan.mapRevision || '')
            || mapFingerprint(this.processMap) !== plan.mapFingerprint) {
            this._recordSpatialEvent('placement', 'stale', {
                scope: plan.isNew ? 'map' : 'node',
                scopedNodeCount: 1,
                candidatesEvaluated: plan.candidatesEvaluated,
                spatialEngineVersion: plan.spatialEngineVersion,
                policyVersion: plan.candidatePolicyVersion,
                fallbackReason: 'map_changed',
            });
            this.operationError = 'The map changed since this position was suggested. Try again.';
            this._clearPlacementPlan();
            this.renderGraph({ fit: false });
            return false;
        }
        let contract;
        let freshScene;
        try {
            contract = await this._ensureSpatialContract();
            freshScene = this._buildPlacementScene(contract);
        } catch (error) {
            this.operationError = 'This suggestion could not be revalidated.';
            this.updateEditControls();
            return false;
        }
        const request = plan.plannerRequest || {};
        const freshResult = runtime.generatePlacementCandidates(freshScene, {
            contract: contract,
            targetKind: request.targetKind,
            targetNodeId: request.targetNodeId,
            anchorNodeId: request.anchorNodeId,
            connectionDirection: request.connectionDirection,
            requiredGroupId: request.requiredGroupId,
            preferredFlowDirection: request.preferredFlowDirection,
            visibleWorldRect: request.visibleWorldRect,
            limit: 3,
        });
        const freshCandidate = freshResult.candidates.find(function (item) {
            return item && item.candidateId === candidate.candidateId;
        });
        const candidateMatches = freshCandidate
            && JSON.stringify(freshCandidate) === JSON.stringify(candidate);
        if (freshResult.obstacleFingerprint !== plan.obstacleFingerprint
            || freshResult.spatialEngineVersion !== plan.spatialEngineVersion
            || freshResult.candidatePolicyVersion !== plan.candidatePolicyVersion
            || !candidateMatches) {
            this._recordSpatialEvent('placement', 'stale', {
                scope: plan.isNew ? 'map' : 'node',
                scopedNodeCount: 1,
                candidatesEvaluated: freshResult.evaluatedCount,
                rejectionCounts: freshResult.rejectionCounts,
                spatialEngineVersion: freshResult.spatialEngineVersion,
                policyVersion: freshResult.candidatePolicyVersion,
                fallbackReason: 'candidate_changed',
            });
            this.operationError = 'The layout changed since this position was suggested. Try again.';
            this._clearPlacementPlan();
            this.renderGraph({ fit: false });
            return false;
        }

        const result = acceptPlacementCandidate(this.processMap, {
            nodeId: plan.nodeId,
            isNew: plan.isNew,
            nodeKind: plan.nodeKind,
            sourceOccurrenceId: plan.sourceOccurrenceId,
            nameSnapshot: plan.nameSnapshot,
            itemIdSnapshot: plan.itemIdSnapshot,
            processType: plan.processType,
            name: plan.name,
            position: freshCandidate.position,
            portOrientation: freshCandidate.portOrientation,
            portOrder: freshCandidate.portOrder,
            connection: plan.connection,
        });
        if (!result.accepted) {
            this._recordSpatialEvent('placement', 'failed', {
                scope: plan.isNew ? 'map' : 'node',
                scopedNodeCount: 1,
                fallbackReason: result.failureReason || 'apply_failed',
            });
            this.operationError = 'This suggestion could no longer be applied.';
            this._clearPlacementPlan();
            this.renderGraph({ fit: false });
            return false;
        }
        this._recordSpatialEvent('placement', 'accepted', {
            scope: plan.isNew ? 'map' : 'node',
            scopedNodeCount: 1,
            candidatesEvaluated: freshResult.evaluatedCount,
            rejectionCounts: freshResult.rejectionCounts,
            movedNodeCount: plan.isNew ? 0 : 1,
            spatialEngineVersion: freshResult.spatialEngineVersion,
            policyVersion: freshResult.candidatePolicyVersion,
        });
        this._clearPlacementPlan();
        const committed = this.commitMutation(result.map);
        if (committed) this.select(result.nodeId, { openToolbar: false });
        return committed;
    };

    ProcessMapEditor.prototype._appendPlacementGhostPreview = function (ghost, node) {
        const preview = node && this.cardPreviews.get(node.nodeId);
        if (!ghost || !preview || !preview.url) return false;
        const media = document.createElement('span');
        media.className = 'pm-placement-ghost-visual pm-card-visual-'
            + String(preview.kind || 'occurrence');
        const image = document.createElement('img');
        image.alt = '';
        image.loading = 'lazy';
        image.src = preview.url;
        media.appendChild(image);
        if (preview.kind === 'stage') {
            const legend = document.createElement('span');
            legend.className = 'pm-card-visual-legend';
            legend.setAttribute('aria-hidden', 'true');
            const inherited = document.createElement('span');
            inherited.className = 'pm-card-visual-key inherited';
            const direct = document.createElement('span');
            direct.className = 'pm-card-visual-key direct';
            legend.appendChild(inherited);
            legend.appendChild(direct);
            media.appendChild(legend);
        }
        image.addEventListener('error', function () {
            media.remove();
        });
        ghost.appendChild(media);
        ghost.classList.add('has-card-preview');
        return true;
    };

    ProcessMapEditor.prototype._appendPlacementGhostCard = function (config) {
        const ghost = document.createElement('div');
        ghost.className = 'pm-placement-ghost pm-node-ports-' + config.portOrientation
            + ' pm-node-port-order-' + config.portOrder
            + (config.className ? (' ' + config.className) : '');
        ghost.style.left = config.position.x + 'px';
        ghost.style.top = config.position.y + 'px';
        ghost.style.width = NODE_WIDTH + 'px';
        ghost.style.height = NODE_HEIGHT + 'px';
        if (config.dataAttribute) {
            ghost.setAttribute(config.dataAttribute.name, config.dataAttribute.value);
        }
        this._appendPlacementGhostPreview(ghost, config.previewNode);
        const label = document.createElement('div');
        label.className = 'pm-placement-ghost-label';
        label.textContent = config.label;
        ghost.appendChild(label);
        const meta = document.createElement('div');
        meta.className = 'pm-placement-ghost-meta';
        meta.textContent = config.meta;
        ghost.appendChild(meta);
        if (config.summary) {
            const summary = document.createElement('div');
            summary.className = 'pm-placement-ghost-metrics';
            summary.textContent = config.summary;
            ghost.appendChild(summary);
        }
        ['in', 'out'].forEach(function (side) {
            const port = document.createElement('span');
            port.className = 'pm-port pm-placement-ghost-port pm-port-' + side;
            port.setAttribute('aria-hidden', 'true');
            ghost.appendChild(port);
        });
        this.placementGhostLayer.appendChild(ghost);
        return ghost;
    };

    ProcessMapEditor.prototype._renderBatchPlacementGhosts = function () {
        this._batchPlacementGhostElement = null;
        if (!this.batchPlacementPlan) return;
        const total = this.batchPlacementPlan.entries.length;
        this.batchPlacementPlan.entries.forEach(function (entry, index) {
            const candidate = entry.candidate;
            const ghost = this._appendPlacementGhostCard({
                position: candidate.position,
                portOrientation: candidate.portOrientation,
                portOrder: candidate.portOrder,
                className: 'pm-batch-placement-ghost',
                dataAttribute: { name: 'data-batch-placement-ghost', value: entry.nodeId },
                label: entry.nameSnapshot,
                meta: 'Organized preview ' + (index + 1) + ' of ' + total,
                summary: '0 overlaps',
            });
            if (!this._batchPlacementGhostElement) this._batchPlacementGhostElement = ghost;
        }, this);
    };

    ProcessMapEditor.prototype._renderSpatialSuggestionPlacementGhosts = function () {
        if (this.suggestionsRevision !== String(this.revision || '')) return;
        this.suggestions.forEach(function (suggestion) {
            const proposal = suggestion && suggestion.spatialProposal;
            const placement = proposal && proposal.placement;
            const node = placement && placement.node;
            if (!suggestion.placement || !proposal || !proposal.accepted || !node
                || proposal.semanticSuggestionId !== suggestion.suggestionId
                || proposal.semanticEvidenceFingerprint !== suggestion.evidenceFingerprint) return;
            const metrics = proposal.route && proposal.route.metrics || {};
            this._appendPlacementGhostCard({
                position: node.position,
                portOrientation: node.portOrientation || 'horizontal',
                portOrder: node.portOrder || 'input_first',
                className: 'pm-semantic-placement-ghost',
                dataAttribute: {
                    name: 'data-semantic-suggestion-id',
                    value: String(suggestion.suggestionId || ''),
                },
                label: node.nameSnapshot || node.sourceOccurrenceId || 'Next card',
                meta: 'Evidence-backed next card',
                summary: String(metrics.crossings || 0) + ' crossings | '
                    + String(metrics.bends || 0) + ' bends',
            });
            const points = proposal.route && proposal.route.points;
            if (Array.isArray(points) && points.length >= 2) {
                this.placementGhostWireSvg.appendChild(svgElement('path', {
                    d: polylinePath(points),
                    class: 'pm-edge pm-placement-ghost-wire pm-semantic-placement-ghost-wire',
                    'data-semantic-suggestion-id': String(suggestion.suggestionId || ''),
                }));
            }
        }, this);
    };

    ProcessMapEditor.prototype._renderArrangementPreview = function () {
        this._arrangementGhostElement = null;
        const state = this.arrangementPlan;
        const plan = state && state.plan;
        if (!plan || !plan.accepted || !plan.proposedMap) return false;
        const previewNodes = mapNodes(plan.proposedMap).map(function (node) {
            return resolveCanvasNode(node, this.occurrenceById);
        }, this);
        const previewEdges = mapEdges(plan.proposedMap);
        const positions = layeredLayout(previewNodes, previewEdges);
        const movedIds = new Set((plan.moves || []).map(function (move) {
            return move && move.nodeId;
        }));
        const before = plan.metricsBefore || {};
        const after = plan.metricsAfter || {};
        const summary = String(before.hardViolationCount || 0) + ' to '
            + String(after.hardViolationCount || 0) + ' conflicts | '
            + String(plan.moves.length) + (plan.moves.length === 1 ? ' card moved' : ' cards moved');
        const scopeLabel = plan.scope && plan.scope.kind === 'selection'
            ? 'Selection cleanup preview'
            : (plan.scope && plan.scope.kind === 'group'
                ? 'Group cleanup preview' : 'Full-map cleanup preview');
        previewNodes.forEach(function (node) {
            if (!node || !movedIds.has(node.nodeId) || isJunctionNode(node)) return;
            const position = positions[node.nodeId];
            if (!position) return;
            const ghost = this._appendPlacementGhostCard({
                position: position,
                portOrientation: nodePortOrientation(node),
                portOrder: nodePortOrder(node),
                className: 'pm-arrangement-ghost',
                dataAttribute: { name: 'data-arrangement-ghost', value: node.nodeId },
                label: node.name || node.nameSnapshot || node.labelOverride || node.nodeId,
                meta: scopeLabel,
                summary: summary,
            });
            if (!this._arrangementGhostElement) this._arrangementGhostElement = ghost;
        }, this);
        previewEdges.forEach(function (edge) {
            if (!edge || !edge.from || !edge.to
                || (!movedIds.has(edge.from.nodeId) && !movedIds.has(edge.to.nodeId))) return;
            const geometry = edgeGeometry(edge, positions, { routingEnabled: true });
            if (!geometry || !geometry.path) return;
            this.placementGhostWireSvg.appendChild(svgElement('path', {
                d: geometry.path,
                class: 'pm-edge pm-placement-ghost-wire pm-arrangement-ghost-wire',
                'data-arrangement-ghost-edge': edge.edgeId || '',
                'marker-end': 'url(#' + this.instanceId + ')',
                'aria-hidden': 'true',
            }));
        }, this);
        return !!this._arrangementGhostElement;
    };

    ProcessMapEditor.prototype._renderPlacementGhost = function () {
        if (!this.placementGhostLayer || !this.placementGhostWireSvg) return;
        this.placementGhostLayer.innerHTML = '';
        this.placementGhostWireSvg.innerHTML = '';
        if (this._renderManagedProposalPreview()) return;
        if (this._renderArrangementPreview()) return;
        this._renderSpatialSuggestionPlacementGhosts();
        this._renderBatchPlacementGhosts();
        const candidate = this._activePlacementCandidate();
        if (!candidate) return;
        const width = NODE_WIDTH;
        const height = NODE_HEIGHT;
        const total = this.placementPlan.candidates.length;
        const metrics = candidate.metricsAfter || {};
        const score = candidate.score || {};
        let summaryText = [
            String(metrics.nodeOverlaps || 0) + ' overlaps',
            String(metrics.edgeCrossings || 0) + ' crossings',
            String(score.routeBends || 0) + ' bends',
            String(this.placementPlan.isNew ? 0 : 1) + ' moved',
        ].join(' | ');
        if ((metrics.edgeCardIntersections || 0) > 0) {
            summaryText += ' | route review';
        }
        const ghost = this._appendPlacementGhostCard({
            position: candidate.position,
            portOrientation: candidate.portOrientation,
            portOrder: candidate.portOrder,
            dataAttribute: { name: 'data-placement-ghost', value: 'true' },
            label: this.placementPlan.nameSnapshot || this.placementPlan.name || 'New card',
            meta: total > 1
                ? ('Option ' + (this.placementPlan.activeIndex + 1) + ' of ' + total)
                : 'Suggested position',
            summary: summaryText,
        });
        this._placementGhostElement = ghost;

        const connection = this.placementPlan.connection;
        if (connection) {
            const anchorPosition = this.positions[connection.anchorNodeId];
            if (anchorPosition) {
                const rect = { x: candidate.position.x, y: candidate.position.y, width: width, height: height, portOrientation: candidate.portOrientation, portOrder: candidate.portOrder };
                const outgoing = connection.direction !== 'incoming';
                const fromPosition = outgoing ? anchorPosition : rect;
                const toPosition = outgoing ? rect : anchorPosition;
                const pathValue = edgeGeometryFromAnchors(
                    portAnchor(fromPosition, 'out'),
                    portAnchor(toPosition, 'in'),
                    fromPosition,
                    toPosition,
                    null,
                    false
                ).path;
                const path = svgElement('path', {
                    d: pathValue,
                    class: 'pm-edge pm-placement-ghost-wire',
                });
                this.placementGhostWireSvg.appendChild(path);
            }
        }
    };

    ProcessMapEditor.prototype._buildPlacementGhostToolbar = function () {
        const toolbar = document.createElement('div');
        toolbar.className = 'ip-floating-surface pm-card-toolbar pm-placement-ghost-toolbar';
        toolbar.setAttribute('role', 'toolbar');
        toolbar.setAttribute('aria-orientation', 'horizontal');
        toolbar.setAttribute('aria-label', 'Suggested placement actions');

        const acceptButton = this._cardToolbarButton(
            'Accept',
            'Place the card at this position',
            this.acceptPlacementPlan.bind(this),
            'pm-placement-ghost-accept'
        );
        toolbar.appendChild(acceptButton);

        if (this.placementPlan && this.placementPlan.candidates.length > 1) {
            const altButton = this._cardToolbarButton(
                'Alternative',
                'Cycle to the next suggested position',
                this.cyclePlacementAlternative.bind(this),
                'pm-placement-ghost-alternative'
            );
            toolbar.appendChild(altButton);
        }

        const dismissButton = this._cardToolbarButton(
            'Dismiss',
            'Discard this suggestion without changing the map',
            this.dismissPlacementPlan.bind(this),
            'pm-placement-ghost-dismiss'
        );
        toolbar.appendChild(dismissButton);
        return toolbar;
    };

    ProcessMapEditor.prototype._buildArrangementToolbar = function () {
        const toolbar = document.createElement('div');
        toolbar.className = 'ip-floating-surface pm-card-toolbar pm-placement-ghost-toolbar';
        toolbar.setAttribute('role', 'toolbar');
        toolbar.setAttribute('aria-orientation', 'horizontal');
        toolbar.setAttribute('aria-label', 'Layout cleanup preview actions');
        toolbar.appendChild(this._cardToolbarButton(
            'Apply',
            'Apply this exact arrangement as one undoable change',
            this.acceptArrangementPlan.bind(this),
            'pm-arrangement-accept'
        ));
        toolbar.appendChild(this._cardToolbarButton(
            'Dismiss',
            'Discard this arrangement without changing the map',
            this.dismissArrangementPlan.bind(this),
            'pm-arrangement-dismiss'
        ));
        return toolbar;
    };

    ProcessMapEditor.prototype._openArrangementToolbar = function () {
        if (!this.cardToolbarManager || !this._arrangementGhostElement || !this.arrangementPlan) {
            return false;
        }
        this._closeCardToolbar('arrangement_plan_opened', false);
        const toolbar = this._buildArrangementToolbar();
        this._placementGhostToolbarElement = toolbar;
        this.cardToolbarOwner = 'arrangement';
        const opened = this.cardToolbarManager.open({
            key: 'arrangement-ghost',
            reference: this._arrangementGhostElement,
            floating: toolbar,
            placement: 'top',
            strategy: 'fixed',
            middleware: this._cardToolbarMiddleware({ portOrientation: 'horizontal' }),
            restoreFocusElement: this._arrangementGhostElement,
            shouldCloseOnEscape: function () { return true; },
            shouldCloseOnOutsidePointerDown: function (event) {
                const target = event && event.target;
                return !(target && typeof target.closest === 'function'
                    && target.closest('[data-arrangement-ghost]'));
            },
            onClose: function (reason) {
                if (this._placementGhostToolbarElement === toolbar) {
                    this._placementGhostToolbarElement = null;
                }
                if (this.cardToolbarOwner === 'arrangement') this.cardToolbarOwner = null;
                if (reason === 'escape' || reason === 'outside_pointerdown') {
                    this.dismissArrangementPlan();
                }
            }.bind(this),
        });
        if (!opened) {
            toolbar.remove();
            this._placementGhostToolbarElement = null;
            this.cardToolbarOwner = null;
        }
        return opened;
    };

    ProcessMapEditor.prototype._buildBatchPlacementToolbar = function () {
        const toolbar = document.createElement('div');
        toolbar.className = 'ip-floating-surface pm-card-toolbar pm-placement-ghost-toolbar';
        toolbar.setAttribute('role', 'toolbar');
        toolbar.setAttribute('aria-orientation', 'horizontal');
        toolbar.setAttribute('aria-label', 'Organized batch placement actions');
        toolbar.appendChild(this._cardToolbarButton(
            'Add all',
            'Add every previewed required part as one undoable change',
            this.acceptBatchPlacementPlan.bind(this),
            'pm-batch-placement-accept'
        ));
        toolbar.appendChild(this._cardToolbarButton(
            'Dismiss',
            'Discard the organized preview without changing the map',
            this.dismissBatchPlacementPlan.bind(this),
            'pm-batch-placement-dismiss'
        ));
        return toolbar;
    };

    ProcessMapEditor.prototype._openBatchPlacementToolbar = function () {
        if (!this.cardToolbarManager || !this._batchPlacementGhostElement) return false;
        this._closeCardToolbar('batch_placement_plan_opened', false);
        const toolbar = this._buildBatchPlacementToolbar();
        this._placementGhostToolbarElement = toolbar;
        this.cardToolbarOwner = 'batch-placement';
        const opened = this.cardToolbarManager.open({
            key: 'batch-placement-ghost',
            reference: this._batchPlacementGhostElement,
            floating: toolbar,
            placement: 'top',
            strategy: 'fixed',
            middleware: this._cardToolbarMiddleware({ portOrientation: 'horizontal' }),
            restoreFocusElement: this._batchPlacementGhostElement,
            shouldCloseOnEscape: function () { return true; },
            shouldCloseOnOutsidePointerDown: function () { return true; },
            onClose: function (reason) {
                if (this._placementGhostToolbarElement === toolbar) {
                    this._placementGhostToolbarElement = null;
                }
                if (this.cardToolbarOwner === 'batch-placement') this.cardToolbarOwner = null;
                if (reason === 'escape' || reason === 'outside_pointerdown') {
                    this.dismissBatchPlacementPlan();
                }
            }.bind(this),
        });
        if (!opened) {
            toolbar.remove();
            this._placementGhostToolbarElement = null;
            this.cardToolbarOwner = null;
        }
        return opened;
    };

    ProcessMapEditor.prototype._openPlacementGhostToolbar = function () {
        if (!this.cardToolbarManager || !this._placementGhostElement) return false;
        this._closeCardToolbar('placement_plan_opened', false);
        const toolbar = this._buildPlacementGhostToolbar();
        this._placementGhostToolbarElement = toolbar;
        this.cardToolbarOwner = 'placement';
        const opened = this.cardToolbarManager.open({
            key: 'placement-ghost',
            reference: this._placementGhostElement,
            floating: toolbar,
            placement: 'top',
            strategy: 'fixed',
            middleware: this._cardToolbarMiddleware({ portOrientation: 'horizontal' }),
            restoreFocusElement: this._placementGhostElement,
            shouldCloseOnEscape: function () { return true; },
            shouldCloseOnOutsidePointerDown: function (event) {
                const target = event && event.target;
                return !(target && typeof target.closest === 'function'
                    && target.closest('[data-placement-ghost]'));
            },
            onClose: function (reason) {
                if (this._placementGhostToolbarElement === toolbar) {
                    this._placementGhostToolbarElement = null;
                }
                if (this.cardToolbarOwner === 'placement') this.cardToolbarOwner = null;
                if (reason === 'escape' || reason === 'outside_pointerdown') {
                    this.dismissPlacementPlan();
                }
            }.bind(this),
        });
        if (!opened) {
            toolbar.remove();
            this._placementGhostToolbarElement = null;
            this.cardToolbarOwner = null;
        }
        return opened;
    };

    ProcessMapEditor.prototype._syncPlacementGhostToolbar = function () {
        if (this.cardToolbarManager && this.cardToolbarManager.isOpen()
            && this.cardToolbarOwner === 'arrangement'
            && this.arrangementPlan && this._arrangementGhostElement) {
            return this.cardToolbarManager.reanchor(this._arrangementGhostElement, {
                placement: 'top',
                middleware: this._cardToolbarMiddleware({ portOrientation: 'horizontal' }),
                restoreFocusElement: this._arrangementGhostElement,
            });
        }
        if (this.cardToolbarManager && this.cardToolbarManager.isOpen()
            && this.cardToolbarOwner === 'batch-placement'
            && this.batchPlacementPlan && this._batchPlacementGhostElement) {
            return this.cardToolbarManager.reanchor(this._batchPlacementGhostElement, {
                placement: 'top',
                middleware: this._cardToolbarMiddleware({ portOrientation: 'horizontal' }),
                restoreFocusElement: this._batchPlacementGhostElement,
            });
        }
        if (!this.cardToolbarManager || !this.cardToolbarManager.isOpen()
            || this.cardToolbarOwner !== 'placement'
            || !this.placementPlan || !this._placementGhostElement) return false;
        // renderGraph() always tears down and rebuilds the ghost layer, so
        // the manager's held reference element is stale after every cycle;
        // reanchor to the freshly rendered element, matching the same
        // pattern _syncCardToolbar() uses for real cards.
        return this.cardToolbarManager.reanchor(this._placementGhostElement, {
            placement: 'top',
            middleware: this._cardToolbarMiddleware({ portOrientation: 'horizontal' }),
            restoreFocusElement: this._placementGhostElement,
        });
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
            this._clearPlacementPlan();
            this._clearRoutePlan();
            this._clearManagedProposal();
            this._resetGraphSelectionState();
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
        this._clearPlacementPlan();
        this._clearArrangementPlan();
        this._clearRoutePlan();
        this._clearManagedProposal();
        this._resetGraphSelectionState();
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
        this.requiredOccurrenceSelection = normalizeRequiredOccurrenceSelection(
            this.productStructure,
            this.requiredOccurrenceSelection
        );
        this.agentExpandedOccurrenceIds = new Set(
            this.requiredOccurrenceSelection
                ? this.requiredOccurrenceSelection.expandedOccurrenceIds
                : []
        );
        this.requiredOccurrenceIds = new Set(
            this.requiredOccurrenceSelection
                ? this.requiredOccurrenceSelection.requiredOccurrenceIds
                : []
        );
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
        const spatial = processMapSpatialRuntime();
        const world = spatial && typeof spatial.viewportToWorld === 'function'
            ? spatial.viewportToWorld(
                { x: x, y: y },
                { x: this.transform.x, y: this.transform.y, scale: previous }
            )
            : {
                x: (x - this.transform.x) / previous,
                y: (y - this.transform.y) / previous,
            };
        this.transform.scale = next;
        this.transform.x = x - world.x * next;
        this.transform.y = y - world.y * next;
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
        const viewportPoint = {
            x: clientX - rect.left,
            y: clientY - rect.top,
        };
        const spatial = processMapSpatialRuntime();
        if (spatial && typeof spatial.viewportToWorld === 'function') {
            return spatial.viewportToWorld(viewportPoint, this.transform);
        }
        return {
            x: (viewportPoint.x - this.transform.x) / this.transform.scale,
            y: (viewportPoint.y - this.transform.y) / this.transform.scale,
        };
    };

    ProcessMapEditor.prototype.startGroupDrag = function (groupId, event) {
        if (!this.editable || this.conflict || event.button !== 0
            || this._effectiveCanvasInteractionMode() !== 'select') return;
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
        if (!this.editable || this.conflict || event.button !== 0
            || this._effectiveCanvasInteractionMode() !== 'select') return;
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

    ProcessMapEditor.prototype._matchingUnplacedOccurrence = function (node) {
        if (!node || node.nodeKind !== 'product_occurrence') return null;
        const source = this.occurrenceById.get(node.sourceOccurrenceId);
        const itemId = String(source && source.itemId || node.itemIdSnapshot || '').trim();
        if (!itemId) return null;
        const placed = this._placedOccurrenceIds();
        return (this.productStructure.occurrences || []).find(function (occurrence) {
            return occurrence && occurrence.occurrenceId
                && !placed.has(occurrence.occurrenceId)
                && String(occurrence.itemId || '').trim() === itemId
                && String(occurrence.kind || '') === String(source && source.kind || '');
        }) || null;
    };

    ProcessMapEditor.prototype._removeDuplicateDragGhost = function (action) {
        if (!action) return;
        if (action.duplicateGhostElement) action.duplicateGhostElement.remove();
        action.duplicateGhostElement = null;
        const source = this.nodeLayer && this.nodeLayer.querySelector(
            '[data-node-id="' + action.nodeId + '"]'
        );
        if (source) source.classList.remove('duplicate-source');
    };

    ProcessMapEditor.prototype.startNodeDrag = function (nodeId, event) {
        if (this.interaction || !this.editable || this.conflict || event.button !== 0
            || this._effectiveCanvasInteractionMode() !== 'select'
            || event.target.closest('.pm-port, select')) return;
        const position = this.positions[nodeId];
        if (!position) return;
        const node = mapNodes(this.processMap).find(function (item) {
            return item && item.nodeId === nodeId;
        });
        const duplicateRequested = !!(event.ctrlKey || event.metaKey) && !isJunctionNode(node);
        const replacementOccurrence = node && node.nodeKind === 'product_occurrence'
            ? this._matchingUnplacedOccurrence(node)
            : null;
        const duplicateAllowed = !!node && (
            node.nodeKind === 'process_step'
            || (node.nodeKind === 'product_occurrence' && !!replacementOccurrence)
        );
        if (duplicateRequested && !duplicateAllowed) {
            event.preventDefault();
            event.stopPropagation();
            this.operationError = node && node.nodeKind === 'product_occurrence'
                ? 'No additional unplaced occurrence of this product item is available.'
                : 'Only product and operation cards can be duplicated.';
            this.updateEditControls();
            return;
        }
        if (nodePositionLocked(node) && !duplicateRequested) return;
        if (duplicateRequested) {
            event.preventDefault();
            this._closeCardToolbar('duplicate_drag_started', false);
        }
        event.stopPropagation();
        this.interaction = {
            mode: 'node',
            pointerId: event.pointerId,
            nodeId: nodeId,
            clientX: event.clientX,
            clientY: event.clientY,
            startX: position.x,
            startY: position.y,
            duplicate: duplicateRequested,
            duplicateAllowed: duplicateAllowed,
            replacementOccurrence: replacementOccurrence,
            sourceItemId: String(
                this.occurrenceById.get(node && node.sourceOccurrenceId)
                    && this.occurrenceById.get(node.sourceOccurrenceId).itemId
                || node && node.itemIdSnapshot
                || ''
            ),
            duplicateLabel: String(
                (resolveCanvasNode(node, this.occurrenceById) || {}).name
                || node && node.name
                || nodeId
            ),
            moved: false,
            captured: false,
        };
    };

    ProcessMapEditor.prototype.startWire = function (nodeId, event) {
        if (!this.editable || this.conflict || event.button !== 0
            || this.interaction
            || this._effectiveCanvasInteractionMode() !== 'select') return;
        if (this.newEdgeRouteMode === 'orthogonal_auto' && !this._spatialContractCache) {
            this.operationError = this.newEdgeRoutingLoading
                ? 'Orthogonal routing is still loading.'
                : 'Orthogonal routing is unavailable. Switch new connections to curved.';
            this.updateEditControls();
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        const position = this.positions[nodeId];
        if (!position) return;
        this._closeCardToolbar('wire_started', false);
        this.select(nodeId, { openToolbar: false });
        if (this.newEdgeRouteMode === 'polyline_manual') {
            this._cancelWireSketch();
            this.wireSketch = {
                fromId: nodeId,
                start: portAnchor(position, 'out'),
                startOrientation: position.portOrientation,
                startOrder: position.portOrder,
                waypoints: [],
                snapTarget: null,
                cursorPoint: portAnchor(position, 'out'),
            };
            this.pendingPath = svgElement('path', {
                class: 'pm-edge pm-edge-pending pm-edge-sketch-pending',
                d: polylinePath([this.wireSketch.start, this.wireSketch.cursorPoint]),
            });
            this.edgeSvg.appendChild(this.pendingPath);
            this.viewport.classList.add('sketching-wire');
            if (this.wireSketchHelp) this.wireSketchHelp.hidden = false;
            return;
        }
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
            d: this._pendingWirePath(
                this.interaction,
                this.interaction.start,
                {
                    portOrientation: this.interaction.startOrientation,
                    portOrder: this.interaction.startOrder,
                }
            ),
        });
        this.edgeSvg.appendChild(this.pendingPath);
        this.viewport.setPointerCapture(event.pointerId);
    };

    ProcessMapEditor.prototype._removeWireSketchPreviewPoints = function () {
        if (!this.edgeSvg) return;
        Array.prototype.forEach.call(
            this.edgeSvg.querySelectorAll('.pm-wire-sketch-point'),
            function (point) { point.remove(); }
        );
    };

    ProcessMapEditor.prototype._renderWireSketchPreviewPoints = function () {
        this._removeWireSketchPreviewPoints();
        if (!this.wireSketch) return;
        this.wireSketch.waypoints.forEach(function (point, index) {
            const marker = svgElement('circle', {
                class: 'pm-wire-sketch-point',
                cx: point.x,
                cy: point.y,
                r: 4,
                'data-sketch-waypoint-index': index,
            });
            this.edgeSvg.appendChild(marker);
        }, this);
    };

    ProcessMapEditor.prototype._cancelWireSketch = function () {
        if (!this.wireSketch && !this.pendingPath) return false;
        this._clearWireTarget(this.wireSketch);
        if (this.pendingPath) this.pendingPath.remove();
        this.pendingPath = null;
        this._removeWireSketchPreviewPoints();
        this.wireSketch = null;
        if (this.viewport) this.viewport.classList.remove('sketching-wire');
        if (this.wireSketchHelp) this.wireSketchHelp.hidden = true;
        return true;
    };

    ProcessMapEditor.prototype._updateWireSketch = function (clientX, clientY) {
        const sketch = this.wireSketch;
        if (!sketch) return false;
        const target = this._directWireTargetAt(clientX, clientY, sketch.fromId);
        this._clearWireTarget(sketch);
        sketch.snapTarget = target || null;
        if (target && target.element) target.element.classList.add('snap-target');
        sketch.cursorPoint = target && target.point
            ? { x: target.point.x, y: target.point.y }
            : this.clientToWorld(clientX, clientY);
        sketch.clientX = clientX;
        sketch.clientY = clientY;
        if (this.pendingPath) {
            this.pendingPath.setAttribute('d', polylinePath(
                [sketch.start].concat(sketch.waypoints, [sketch.cursorPoint])
            ));
        }
        return true;
    };

    ProcessMapEditor.prototype._finishWireSketch = function (target) {
        const sketch = this.wireSketch;
        if (!sketch || !target || !target.nodeId || target.nodeId === sketch.fromId) {
            return false;
        }
        const edgeId = 'pm-e-' + Date.now().toString(36) + '-' + (++this.edgeCounter);
        let next = addEdge(this.processMap, {
            edgeId: edgeId,
            from: { nodeId: sketch.fromId, port: 'out' },
            to: { nodeId: target.nodeId, port: 'in' },
            kind: 'precedence',
        });
        if (mapFingerprint(next) === mapFingerprint(this.processMap)) {
            this.operationError = 'That process connection already exists or is not valid.';
            this._cancelWireSketch();
            this.updateEditControls();
            return false;
        }
        next = setManualEdgeWaypoints(next, edgeId, sketch.waypoints);
        this._cancelWireSketch();
        if (!this.commitMutation(next)) {
            this.operationError = 'That process connection could not be added.';
            this.updateEditControls();
            return false;
        }
        this.selectEdge(edgeId);
        return true;
    };

    ProcessMapEditor.prototype._manualEdgeGeometry = function (edge, waypoints) {
        if (!edge) return null;
        const previewEdge = Object.assign({}, edge, {
            routing: {
                mode: 'polyline_manual',
                routerVersion: 1,
                waypoints: normalizeManualRouteWaypoints(waypoints),
            },
        });
        return this._edgeGeometry(previewEdge);
    };

    ProcessMapEditor.prototype._previewManualEdgeWaypoints = function (edgeId, waypoints) {
        const edge = mapEdges(this.processMap).find(function (item) {
            return item && item.edgeId === edgeId;
        });
        const geometry = this._manualEdgeGeometry(edge, waypoints);
        if (!geometry) return false;
        this.edgeGeometries[edgeId] = geometry;
        Array.prototype.forEach.call(
            this.edgeSvg.querySelectorAll('[data-edge-id]'),
            function (path) {
                if (path.getAttribute('data-edge-id') === edgeId) {
                    path.setAttribute('d', geometry.path);
                }
            }
        );
        normalizeManualRouteWaypoints(waypoints).forEach(function (point, index) {
            const handle = Array.prototype.find.call(
                this.edgeSvg.querySelectorAll('.pm-edge-waypoint'),
                function (item) {
                    return item.getAttribute('data-edge-id') === edgeId
                        && Number(item.getAttribute('data-waypoint-index')) === index;
                }
            );
            if (handle) {
                handle.setAttribute('cx', point.x);
                handle.setAttribute('cy', point.y);
            }
        }, this);
        this._positionEdgeContextLabels();
        return true;
    };

    ProcessMapEditor.prototype.startWaypointDrag = function (edgeId, waypointIndex, event) {
        if (!this.editable || this.conflict || this.interaction || this.wireSketch
            || event.button !== 0) return false;
        const edge = mapEdges(this.processMap).find(function (item) {
            return item && item.edgeId === edgeId;
        });
        const waypoints = normalizeManualRouteWaypoints(
            edge && edge.routing && edge.routing.mode === 'polyline_manual'
                ? edge.routing.waypoints : []
        );
        if (!Number.isInteger(waypointIndex)
            || waypointIndex < 0 || waypointIndex >= waypoints.length) return false;
        event.preventDefault();
        event.stopPropagation();
        this.selectedWaypoint = { edgeId: edgeId, index: waypointIndex };
        this._closeCardToolbar('waypoint_drag_started', false);
        this.interaction = {
            mode: 'edge-waypoint',
            pointerId: event.pointerId,
            edgeId: edgeId,
            waypointIndex: waypointIndex,
            clientX: event.clientX,
            clientY: event.clientY,
            startPoint: {
                x: waypoints[waypointIndex].x,
                y: waypoints[waypointIndex].y,
            },
            waypoints: waypoints,
            moved: false,
        };
        this.viewport.setPointerCapture(event.pointerId);
        Array.prototype.forEach.call(
            this.edgeSvg.querySelectorAll('.pm-edge-waypoint'),
            function (handle) {
                handle.classList.toggle(
                    'selected',
                    handle.getAttribute('data-edge-id') === edgeId
                        && Number(handle.getAttribute('data-waypoint-index')) === waypointIndex
                );
            }
        );
        return true;
    };

    ProcessMapEditor.prototype._insertManualWaypointAtClient = function (
        edgeId,
        clientX,
        clientY
    ) {
        const edge = mapEdges(this.processMap).find(function (item) {
            return item && item.edgeId === edgeId;
        });
        if (!edge || !edge.routing || edge.routing.mode !== 'polyline_manual') return false;
        const geometry = this.edgeGeometries[edgeId] || this._edgeGeometry(edge);
        const nearest = nearestPointOnPolyline(
            geometry && geometry.points,
            this.clientToWorld(clientX, clientY)
        );
        if (!nearest) return false;
        this.selectedWaypoint = { edgeId: edgeId, index: nearest.segmentIndex };
        const committed = this.commitMutation(addManualEdgeWaypoint(
            this.processMap,
            edgeId,
            nearest.segmentIndex,
            nearest.point
        ));
        if (committed) this._applyGraphSelectionClasses();
        return committed;
    };

    ProcessMapEditor.prototype.deleteSelectedWaypoint = function () {
        const selection = this.selectedWaypoint;
        if (!selection || this.conflict) return false;
        const next = removeManualEdgeWaypoint(
            this.processMap,
            selection.edgeId,
            selection.index
        );
        this.selectedWaypoint = null;
        return this.commitMutation(next);
    };

    ProcessMapEditor.prototype._handleWireSketchPointerDown = function (event) {
        const sketch = this.wireSketch;
        if (!sketch || event.button !== 0) return false;
        event.preventDefault();
        event.stopPropagation();
        const target = this._directWireTargetAt(event.clientX, event.clientY, sketch.fromId);
        if (target) return this._finishWireSketch(target);
        const element = event.target && event.target.closest ? event.target : null;
        if (element && element.closest(
            '.pm-node, .pm-junction, button, input, select, textarea, .pm-group-header, .pm-group-resize'
        )) {
            return false;
        }
        if (sketch.waypoints.length >= MAX_MANUAL_ROUTE_WAYPOINTS) {
            this.operationError = 'A manual connection can contain at most '
                + MAX_MANUAL_ROUTE_WAYPOINTS + ' fixed points.';
            this.updateEditControls();
            return false;
        }
        const point = this.clientToWorld(event.clientX, event.clientY);
        const previous = sketch.waypoints.length
            ? sketch.waypoints[sketch.waypoints.length - 1] : sketch.start;
        if (Math.hypot(point.x - previous.x, point.y - previous.y)
            <= 2 / this.transform.scale) {
            return false;
        }
        sketch.waypoints.push({ x: point.x, y: point.y });
        this._renderWireSketchPreviewPoints();
        this._updateWireSketch(event.clientX, event.clientY);
        return true;
    };

    ProcessMapEditor.prototype._directWireTargetAt = function (clientX, clientY, fromId) {
        if (typeof document === 'undefined' || typeof document.elementFromPoint !== 'function') return null;
        const target = document.elementFromPoint(clientX, clientY);
        const port = target && target.closest ? target.closest('.pm-port-in') : null;
        if (port && this.root.contains(port)) {
            const nodeId = port.getAttribute('data-node-id');
            const position = this.positions[nodeId];
            if (nodeId && nodeId !== fromId && position) {
                const slotIndex = Number(port.getAttribute('data-port-slot-index'));
                const slotCount = Number(port.getAttribute('data-port-slot-count'));
                return {
                    kind: 'node',
                    nodeId: nodeId,
                    element: port,
                    point: portAnchor(position, 'in', slotIndex, slotCount),
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
            const inputSlot = this.inputPortLayout && this.inputPortLayout.byEdge
                ? this.inputPortLayout.byEdge[edgeId]
                : null;
            const end = portAnchor(
                toPosition,
                'in',
                inputSlot && inputSlot.index,
                inputSlot && inputSlot.count
            );
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
                const geometry = this._edgeGeometry(edge);
                if (!geometry) return;
                this.edgeGeometries[edgeId] = geometry;
                path.setAttribute('d', geometry.path);
            }.bind(this)
        );
        this._positionEdgeContextLabels();
        if (this.cardToolbarManager && this.cardToolbarManager.isOpen()
            && this.cardToolbarEdgeId) {
            this.cardToolbarManager.reposition();
        }
    };

    ProcessMapEditor.prototype._updateSelectionMarquee = function (action, clientX, clientY) {
        if (!action || action.mode !== 'marquee' || !this.selectionMarquee) return null;
        const viewportRect = this.viewport.getBoundingClientRect();
        const currentX = clamp(clientX, viewportRect.left, viewportRect.right);
        const currentY = clamp(clientY, viewportRect.top, viewportRect.bottom);
        const screenRect = normalizedRect(action.clientX, action.clientY, currentX, currentY);
        action.screenRect = screenRect;
        action.moved = action.moved || Math.hypot(
            currentX - action.clientX,
            currentY - action.clientY
        ) >= MARQUEE_DRAG_THRESHOLD_PX;
        if (!action.moved) return screenRect;
        this.selectionMarquee.hidden = false;
        this.selectionMarquee.style.left = (screenRect.left - viewportRect.left) + 'px';
        this.selectionMarquee.style.top = (screenRect.top - viewportRect.top) + 'px';
        this.selectionMarquee.style.width = (screenRect.right - screenRect.left) + 'px';
        this.selectionMarquee.style.height = (screenRect.bottom - screenRect.top) + 'px';
        this.viewport.classList.add('selecting');
        return screenRect;
    };

    ProcessMapEditor.prototype._edgePathIntersectsScreenRect = function (path, screenRect) {
        if (!path || !screenRect) return false;
        const pathRect = path.getBoundingClientRect();
        if (!rectsIntersect(screenRect, {
            left: pathRect.left,
            top: pathRect.top,
            right: pathRect.right,
            bottom: pathRect.bottom,
        })) return false;
        let length;
        try { length = path.getTotalLength(); } catch (_) { return false; }
        if (!finiteNumber(length) || length <= 0) return false;
        const matrix = typeof path.getScreenCTM === 'function' ? path.getScreenCTM() : null;
        if (!matrix) return false;
        const sampleCount = clamp(Math.ceil(length * this.transform.scale / 6), 8, 240);
        const toScreen = function (point) {
            return {
                x: matrix.a * point.x + matrix.c * point.y + matrix.e,
                y: matrix.b * point.x + matrix.d * point.y + matrix.f,
            };
        };
        let previous = toScreen(path.getPointAtLength(0));
        if (pointInRect(previous, screenRect)) return true;
        for (let index = 1; index <= sampleCount; index += 1) {
            const current = toScreen(path.getPointAtLength(length * index / sampleCount));
            if (segmentIntersectsRect(previous, current, screenRect)) return true;
            previous = current;
        }
        return false;
    };

    ProcessMapEditor.prototype._finishSelectionMarquee = function (action, cancelled) {
        if (this.selectionMarquee) {
            this.selectionMarquee.hidden = true;
            this.selectionMarquee.removeAttribute('style');
        }
        this.viewport.classList.remove('selecting');
        if (cancelled) return false;
        if (!action.moved || !action.screenRect) {
            this._clearGraphSelection('canvas_clicked');
            return true;
        }
        const screenRect = action.screenRect;
        const nodeIds = [];
        const edgeIds = [];
        Array.prototype.forEach.call(
            this.nodeLayer.querySelectorAll('.pm-node[data-node-id], .pm-junction[data-node-id]'),
            function (wrapper) {
                const bounds = wrapper.getBoundingClientRect();
                if (rectsIntersect(screenRect, {
                    left: bounds.left,
                    top: bounds.top,
                    right: bounds.right,
                    bottom: bounds.bottom,
                })) nodeIds.push(wrapper.getAttribute('data-node-id'));
            }
        );
        Array.prototype.forEach.call(
            this.edgeSvg.querySelectorAll('.pm-edge-hit[data-edge-id]'),
            function (path) {
                if (this._edgePathIntersectsScreenRect(path, screenRect)) {
                    edgeIds.push(path.getAttribute('data-edge-id'));
                }
            }.bind(this)
        );
        this.setGraphSelection(nodeIds, edgeIds);
        return true;
    };

    ProcessMapEditor.prototype.pointerDown = function (event) {
        if (this.wireSketch) {
            if (event.button === 0) this._handleWireSketchPointerDown(event);
            return;
        }
        if (this.interaction || (event.button !== 0 && event.button !== 1)) return;
        const effectiveMode = this._effectiveCanvasInteractionMode();
        const target = event.target && event.target.closest ? event.target : null;
        if (event.button === 0 && effectiveMode === 'select' && target && target.closest(
            '.pm-node, .pm-junction, button, .pm-edge-hit, .pm-ghost-edge-hit'
        )) return;
        if (event.button === 0 && effectiveMode === 'pan' && target) {
            const control = target.closest('button, input, select, textarea');
            if (control && !control.closest(
                '.pm-node-card, .pm-junction, .pm-group-header, .pm-group-resize'
            )) return;
        }
        event.preventDefault();
        if (event.button === 0 && effectiveMode === 'select' && this.editable) {
            this.interaction = {
                mode: 'marquee',
                pointerId: event.pointerId,
                clientX: event.clientX,
                clientY: event.clientY,
                screenRect: null,
                moved: false,
            };
            this.viewport.setPointerCapture(event.pointerId);
            return;
        }
        this.interaction = {
            mode: 'pan',
            pointerId: event.pointerId,
            clientX: event.clientX,
            clientY: event.clientY,
            startX: this.transform.x,
            startY: this.transform.y,
            moved: false,
        };
        this.viewport.setPointerCapture(event.pointerId);
        this.viewport.classList.add('panning');
    };

    ProcessMapEditor.prototype.pointerMove = function (event) {
        if (this.wireSketch && !this.interaction) {
            this._updateWireSketch(event.clientX, event.clientY);
            return;
        }
        const action = this.interaction;
        if (!action || event.pointerId !== action.pointerId) return;
        if (action.mode === 'pan') {
            action.moved = action.moved || Math.hypot(
                event.clientX - action.clientX,
                event.clientY - action.clientY
            ) >= MARQUEE_DRAG_THRESHOLD_PX;
            this.transform.x = action.startX + event.clientX - action.clientX;
            this.transform.y = action.startY + event.clientY - action.clientY;
            this.applyTransform();
            return;
        }
        if (action.mode === 'marquee') {
            this._updateSelectionMarquee(action, event.clientX, event.clientY);
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
        if (action.mode === 'edge-waypoint') {
            const dx = (event.clientX - action.clientX) / this.transform.scale;
            const dy = (event.clientY - action.clientY) / this.transform.scale;
            if (!action.moved && Math.hypot(dx, dy) < 2) return;
            action.moved = true;
            action.waypoints[action.waypointIndex] = {
                x: action.startPoint.x + dx,
                y: action.startPoint.y + dy,
            };
            this._previewManualEdgeWaypoints(action.edgeId, action.waypoints);
            return;
        }
        if (action.mode === 'node') {
            const dx = (event.clientX - action.clientX) / this.transform.scale;
            const dy = (event.clientY - action.clientY) / this.transform.scale;
            if (!action.moved && !action.duplicate && (event.ctrlKey || event.metaKey)) {
                if (!action.duplicateAllowed) {
                    this.operationError = 'This card has no valid duplicate available.';
                    this.updateEditControls();
                    return;
                }
                action.duplicate = true;
                this._closeCardToolbar('duplicate_drag_started', false);
            }
            if (!action.moved && Math.hypot(dx, dy) < 4) return;
            action.moved = true;
            if (!action.captured) {
                this.viewport.setPointerCapture(event.pointerId);
                action.captured = true;
            }
            if (action.duplicate) {
                const duplicatePosition = {
                    x: action.startX + dx,
                    y: action.startY + dy,
                };
                action.duplicatePosition = duplicatePosition;
                if (!action.duplicateGhostElement) {
                    action.duplicateGhostElement = this._appendPlacementGhostCard({
                        position: duplicatePosition,
                        portOrientation: nodePortOrientation(mapNodes(this.processMap).find(
                            function (node) { return node && node.nodeId === action.nodeId; }
                        )),
                        portOrder: nodePortOrder(mapNodes(this.processMap).find(
                            function (node) { return node && node.nodeId === action.nodeId; }
                        )),
                        className: 'pm-duplicate-drag-ghost',
                        dataAttribute: { name: 'data-duplicate-drag-ghost', value: action.nodeId },
                        label: action.duplicateLabel,
                        meta: 'Duplicate card',
                    });
                    const source = this.nodeLayer.querySelector(
                        '[data-node-id="' + action.nodeId + '"]'
                    );
                    if (source) source.classList.add('duplicate-source');
                } else {
                    action.duplicateGhostElement.style.left = duplicatePosition.x + 'px';
                    action.duplicateGhostElement.style.top = duplicatePosition.y + 'px';
                }
                return;
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
                this.pendingPath.setAttribute('d', this._pendingWirePath(
                    action,
                    target && target.point ? target.point : world,
                    {
                        portOrientation: target && target.portOrientation,
                        portOrder: target && target.portOrder,
                    }
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
        if (action.mode === 'pan') {
            this._suppressClick = true;
            this._suppressGroupClick = true;
            setTimeout(function () {
                this._suppressClick = false;
                this._suppressGroupClick = false;
            }.bind(this), 0);
            return;
        }
        if (action.mode === 'marquee') {
            this._finishSelectionMarquee(action, event.type === 'pointercancel');
            return;
        }
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
        if (action.mode === 'edge-waypoint') {
            if (action.moved && event.type !== 'pointercancel') {
                this.commitMutation(setManualEdgeWaypoints(
                    this.processMap,
                    action.edgeId,
                    action.waypoints
                ));
            } else if (event.type === 'pointercancel') {
                this.renderGraph({ fit: false });
            } else {
                this._renderSelectedManualRouteWaypoints();
                const edge = mapEdges(this.processMap).find(function (item) {
                    return item && item.edgeId === action.edgeId;
                });
                this._openEdgeToolbar(edge);
            }
            return;
        }
        if (action.mode === 'node') {
            const wrapper = this.nodeLayer.querySelector('[data-node-id="' + action.nodeId + '"]');
            if (wrapper) wrapper.classList.remove('dragging');
            if (action.duplicate) {
                this._removeDuplicateDragGhost(action);
                if (action.moved && event.type !== 'pointercancel' && action.duplicatePosition) {
                    this._suppressClick = true;
                    setTimeout(function () { this._suppressClick = false; }.bind(this), 0);
                    let nodeId;
                    do {
                        nodeId = 'pm-copy-' + Date.now().toString(36) + '-'
                            + (++this.nodeCounter);
                    } while (mapNodes(this.processMap).some(function (node) {
                        return node && node.nodeId === nodeId;
                    }));
                    const sourcePosition = this.positions[action.nodeId];
                    const center = {
                        x: action.duplicatePosition.x
                            + (sourcePosition && sourcePosition.width || NODE_WIDTH) / 2,
                        y: action.duplicatePosition.y
                            + (sourcePosition && sourcePosition.height || NODE_HEIGHT) / 2,
                    };
                    const result = duplicateCanvasCard(this.processMap, action.nodeId, {
                        nodeId: nodeId,
                        position: action.duplicatePosition,
                        center: center,
                        replacementOccurrence: action.replacementOccurrence,
                        sourceItemId: action.sourceItemId,
                    });
                    if (result.accepted && this.commitMutation(result.map)) {
                        this.select(result.nodeId, { openToolbar: false });
                    } else {
                        this.operationError = result.reason === 'no_matching_product_occurrence'
                            ? 'No additional unplaced occurrence of this product item is available.'
                            : 'The card could not be duplicated here.';
                        this.updateEditControls();
                    }
                }
                return;
            }
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
                const routedSplit = this._routeNewEdges(
                    next,
                    [firstEdgeId, secondEdgeId, branchEdgeId]
                );
                if (!routedSplit.accepted) {
                    this.operationError = 'No obstacle-free orthogonal route is available. '
                        + 'Switch new connections to curved and try again.';
                    this.updateEditControls();
                } else if (this.commitMutation(routedSplit.map)) {
                    this.select(junctionId);
                }
                else {
                    this.operationError = 'That branch would create an invalid process connection.';
                    this.updateEditControls();
                }
                return;
            }
            const toId = target.nodeId;
            if (!toId || toId === action.fromId) return;
            const edgeId = 'pm-e-' + Date.now().toString(36) + '-' + (++this.edgeCounter);
            const next = addEdge(this.processMap, {
                edgeId: edgeId,
                from: { nodeId: action.fromId, port: 'out' },
                to: { nodeId: toId, port: 'in' },
                kind: 'precedence',
            });
            if (mapFingerprint(next) === mapFingerprint(this.processMap)) {
                this.operationError = 'That process connection already exists or is not valid.';
                this.updateEditControls();
                return;
            }
            const routed = this._routeNewEdges(next, [edgeId]);
            if (!routed.accepted) {
                this.operationError = 'No obstacle-free orthogonal route is available. '
                    + 'Switch new connections to curved and try again.';
                this.updateEditControls();
                return;
            }
            if (!this.commitMutation(routed.map)) {
                this.operationError = 'That process connection could not be added.';
                this.updateEditControls();
            }
        }
    };

    ProcessMapEditor.prototype.keyDown = function (event) {
        if (!this.editable) return;
        if (this.wireSketch && event.key === 'Escape') {
            this._cancelWireSketch();
            event.preventDefault();
            return;
        }
        if (this.wireSketch && event.key === 'Backspace') {
            if (this.wireSketch.waypoints.length) {
                this.wireSketch.waypoints.pop();
                this._renderWireSketchPreviewPoints();
                if (finiteNumber(this.wireSketch.clientX)
                    && finiteNumber(this.wireSketch.clientY)) {
                    this._updateWireSketch(
                        this.wireSketch.clientX,
                        this.wireSketch.clientY
                    );
                } else if (this.pendingPath) {
                    this.pendingPath.setAttribute('d', polylinePath(
                        [this.wireSketch.start].concat(
                            this.wireSketch.waypoints,
                            [this.wireSketch.cursorPoint]
                        )
                    ));
                }
            }
            event.preventDefault();
            return;
        }
        if (event.key === 'Escape' && this.arrangementPlan) {
            this.dismissArrangementPlan();
            event.preventDefault();
            return;
        }
        if (event.key === 'Escape' && this.managedProposalPlan) {
            this.dismissManagedProposal();
            event.preventDefault();
            return;
        }
        if (event.key === 'Escape' && this.routePlan) {
            this._clearRoutePlan();
            this._closeCardToolbar('escape', true);
            this.renderGraph({ fit: false });
            event.preventDefault();
            return;
        }
        if (event.key === 'Escape' && this._closeCardToolbar('escape', true)) {
            event.preventDefault();
            return;
        }
        const targetName = String(event.target && event.target.tagName || '').toLowerCase();
        if (['a', 'button', 'input', 'select', 'textarea'].indexOf(targetName) >= 0
            || (event.target && event.target.isContentEditable)) return;
        const modifier = event.ctrlKey || event.metaKey;
        if (event.key === 'Escape') {
            if (this.interaction && this.interaction.mode === 'marquee') {
                const action = this.interaction;
                this.interaction = null;
                try { this.viewport.releasePointerCapture(action.pointerId); } catch (_) {}
                this._finishSelectionMarquee(action, true);
            } else {
                this._clearGraphSelection('escape');
            }
            event.preventDefault();
            return;
        }
        if (!modifier && !event.altKey && event.code === 'Space') {
            if (!this.spacePanActive) {
                this.spacePanActive = true;
                this._syncCanvasInteractionMode();
            }
            event.preventDefault();
            return;
        }
        if (!modifier && !event.altKey && event.key.toLowerCase() === 'v') {
            event.preventDefault();
            this.setCanvasInteractionMode('select');
            return;
        }
        if (!modifier && !event.altKey && event.key.toLowerCase() === 'h') {
            event.preventDefault();
            this.setCanvasInteractionMode('pan');
            return;
        }
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
        if (modifier && event.key.toLowerCase() === 'c') {
            event.preventDefault();
            this.copyProcessLogicSelection();
            return;
        }
        if (modifier && event.key.toLowerCase() === 'v') {
            event.preventDefault();
            this.pasteProcessLogicSelection();
            return;
        }
        if (event.key === 'Delete' || event.key === 'Backspace') {
            event.preventDefault();
            if (!this.deleteSelectedWaypoint()) this.deleteSelection();
        }
    };

    ProcessMapEditor.prototype.keyUp = function (event) {
        if (!this.editable || event.code !== 'Space' || !this.spacePanActive) return;
        this.spacePanActive = false;
        this._syncCanvasInteractionMode();
        event.preventDefault();
    };

    ProcessMapEditor.prototype.destroy = function () {
        this.destroyed = true;
        this.cardPreviewRequestToken += 1;
        this._cancelWireSketch();
        this._removeTreeDragPreview();
        this.closeJunctionMenu(false);
        this._clearSuggestions();
        this._clearPlacementPlan();
        this._clearArrangementPlan();
        this._clearRoutePlan();
        this._clearManagedProposal();
        this.suggestionPanelOpen = false;
        if (this.structurePaneDivider) {
            this.structurePaneDivider.destroy();
            this.structurePaneDivider = null;
        }
        if (this.cardToolbarManager) {
            this.cardToolbarManager.destroy();
            this.cardToolbarManager = null;
            this.cardToolbarElement = null;
            this.cardToolbarNodeId = null;
            this.cardToolbarEdgeId = null;
            this.cardToolbarGroupId = null;
            this.cardToolbarOwner = null;
        }
        if (this.ribbonHost) {
            this.ribbonHost.textContent = '';
            this.ribbonHost = null;
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
        if (this.root) {
            this.root.removeEventListener('keydown', this._onKeyDown);
            this.root.removeEventListener('keyup', this._onKeyUp);
        }
        if (this.pendingPath) this.pendingPath.remove();
        this._clearWireTarget(this.interaction);
        this._removeDuplicateDragGhost(this.interaction);
        this.interaction = null;
        if (this.host && this.host.__processMapEditor === this) {
            this.host.__processMapEditor = null;
        }
    };

    ProcessMapEditor.prototype.getAgentState = function () {
        const proposal = this.managedProposalPlan || null;
        return {
            dirty: !!this.dirty,
            conflict: !!this.conflict,
            editable: !!this.editable,
            selection: {
                nodeIds: Array.from(this.selectedNodeIds || []).sort(),
                edgeIds: Array.from(this.selectedEdgeIds || []).sort(),
            },
            agentFocus: this.getAgentFocus(),
            activeProposal: proposal && proposal.proposalId ? {
                proposalId: proposal.proposalId,
                type: String(proposal.managedProposalType || ''),
                visualValidationStatus: (
                    proposal.visualValidation
                    && proposal.visualValidation.status
                ) || null,
                visualCorrectionCount: Number(
                    proposal.visualValidation
                    && proposal.visualValidation.correctionCount
                    || 0
                ),
                visualUnresolvedCount: Number(
                    proposal.visualValidation
                    && Array.isArray(
                        proposal.visualValidation.unresolvedItems
                    )
                    ? proposal.visualValidation.unresolvedItems.length
                    : 0
                ),
                reveal: this.managedProposalReveal ? {
                    status: this.managedProposalReveal.active
                        ? 'building' : 'complete',
                    visibleNodeCount:
                        this.managedProposalReveal.visibleNodeIds.size,
                    totalNodeCount: this.managedProposalReveal.nodeIds.length,
                    visibleEdgeCount:
                        this.managedProposalReveal.visibleEdgeIds.size,
                    totalEdgeCount: this.managedProposalReveal.edgeIds.length,
                } : null,
            } : null,
        };
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
        JUNCTION_TYPES: JUNCTION_TYPES,
        JUNCTION_INSERT_TYPES: JUNCTION_INSERT_TYPES,
        PROCESS_STEP_PROPERTY_FIELDS: PROCESS_STEP_PROPERTY_FIELDS,
        PORT_ORIENTATIONS: PORT_ORIENTATIONS,
        PORT_ORDERS: PORT_ORDERS,
        EDGE_DRAW_MODES: EDGE_DRAW_MODES,
        AGENT_FOCUS_DIRECTIONS: AGENT_FOCUS_DIRECTIONS,
        NODE_WIDTH: NODE_WIDTH,
        NODE_HEIGHT: NODE_HEIGHT,
        JUNCTION_HIT_SIZE: JUNCTION_HIT_SIZE,
        WIRE_SNAP_THRESHOLD_PX: WIRE_SNAP_THRESHOLD_PX,
        MAX_NODE_LABEL_LENGTH: MAX_NODE_LABEL_LENGTH,
        MAX_NODE_NOTE_LENGTH: MAX_NODE_NOTE_LENGTH,
        MAX_REFERENCE_CATALOG_ITEMS: MAX_REFERENCE_CATALOG_ITEMS,
        MAX_REFERENCES_PER_TARGET: MAX_REFERENCES_PER_TARGET,
        MAX_DISMISSED_SUGGESTIONS: MAX_DISMISSED_SUGGESTIONS,
        MAX_TREE_MULTI_DRAG_ITEMS: MAX_TREE_MULTI_DRAG_ITEMS,
        REFERENCE_KINDS: REFERENCE_KINDS,
        PROCESS_MAP_LAYOUT_VERSION: PROCESS_MAP_LAYOUT_VERSION,
        GROUP_COLOR_KEYS: GROUP_COLOR_KEYS,
        MIN_GROUP_WIDTH: MIN_GROUP_WIDTH,
        MIN_GROUP_HEIGHT: MIN_GROUP_HEIGHT,
        DEFAULT_PANE_WIDTH: DEFAULT_PANE_WIDTH,
        MIN_PANE_WIDTH: MIN_PANE_WIDTH,
        MAX_PANE_WIDTH: MAX_PANE_WIDTH,
        PaneDivider: PaneDivider,
        SnapshotHistory: SnapshotHistory,
        addEdge: addEdge,
        acceptSuggestions: acceptSuggestions,
        acceptSpatialSuggestions: acceptSpatialSuggestions,
        addCanvasNode: addCanvasNode,
        addOccurrenceBatch: addOccurrenceBatch,
        addJunctionNode: addJunctionNode,
        copyProcessLogicSelection: copyProcessLogicSelection,
        pasteProcessLogicSelection: pasteProcessLogicSelection,
        addGroup: addGroup,
        addConnectedProcessStep: addConnectedProcessStep,
        bezierPath: bezierPath,
        edgeGeometry: edgeGeometry,
        edgeGeometryFromAnchors: edgeGeometryFromAnchors,
        edgePointBounds: edgePointBounds,
        routeGeometryFindings: routeGeometryFindings,
        polylinePath: polylinePath,
        nearestPointOnPolyline: nearestPointOnPolyline,
        cloneMap: cloneMap,
        clearProcessMapCanvas: clearProcessMapCanvas,
        clearEdgeRouting: clearEdgeRouting,
        setManualEdgeWaypoints: setManualEdgeWaypoints,
        addManualEdgeWaypoint: addManualEdgeWaypoint,
        removeManualEdgeWaypoint: removeManualEdgeWaypoint,
        collapseRedundantJunctions: collapseRedundantJunctions,
        deleteCanvasSelection: deleteCanvasSelection,
        deleteEdge: deleteEdge,
        deleteNode: deleteNode,
        deleteGroup: deleteGroup,
        duplicateCanvasCard: duplicateCanvasCard,
        graphBounds: graphBounds,
        hasProcessMapCanvasContent: hasProcessMapCanvasContent,
        hasPrecedenceCycle: hasPrecedenceCycle,
        isJunctionNode: isJunctionNode,
        layeredLayout: layeredLayout,
        mapFingerprint: mapFingerprint,
        mergeManagedProposalPreview: mergeManagedProposalPreview,
        managedProposalRevealSequence: managedProposalRevealSequence,
        mapEdges: mapEdges,
        mapDismissedSuggestions: mapDismissedSuggestions,
        mapGroups: mapGroups,
        mapNodes: mapNodes,
        mapReferenceCatalog: mapReferenceCatalog,
        pruneUnusedProcessReferences: pruneUnusedProcessReferences,
        mount: mount,
        moveNode: moveNode,
        moveGroup: moveGroup,
        normalizePaneWidth: normalizePaneWidth,
        normalizeMapCatalog: normalizeMapCatalog,
        planOccurrenceBatchPositions: planOccurrenceBatchPositions,
        processMapCardPreviewDescriptors: processMapCardPreviewDescriptors,
        processStepInputPortLayout: processStepInputPortLayout,
        normalizedRect: normalizedRect,
        rectsIntersect: rectsIntersect,
        connectedStepPosition: connectedStepPosition,
        portAnchor: portAnchor,
        portDirection: portDirection,
        nodePortOrientation: nodePortOrientation,
        nodePortOrder: nodePortOrder,
        selectedNodeCommandStates: selectedNodeCommandStates,
        retypeNode: retypeNode,
        setNodePortOrientation: setNodePortOrientation,
        setNodePortOrder: setNodePortOrder,
        setNodePositionLocked: setNodePositionLocked,
        nodePositionMode: nodePositionMode,
        nodePositionLocked: nodePositionLocked,
        acceptPlacementCandidate: acceptPlacementCandidate,
        setNodeLabel: setNodeLabel,
        setNodeNote: setNodeNote,
        setProcessStepProperties: setProcessStepProperties,
        resizeGroup: resizeGroup,
        renameGroup: renameGroup,
        recolorGroup: recolorGroup,
        setGroupMembers: setGroupMembers,
        resolveNodeGroupMembership: resolveNodeGroupMembership,
        resolveRequiredOccurrenceScope: resolveRequiredOccurrenceScope,
        resolveProcessMapFocus: resolveProcessMapFocus,
        segmentIntersectsRect: segmentIntersectsRect,
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
