(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProProcessMapSpatial = api;
})(typeof window !== 'undefined' ? window : (typeof self !== 'undefined' ? self : null), function () {
    'use strict';

    const SPATIAL_VERSION = 1;
    const CONTRACT_ID = 'process-map-spatial-contract-v1';
    const ROUTER_VERSION = 1;
    const SPATIAL_PROPOSAL_VERSION = 1;
    const ARRANGEMENT_POLICY_VERSION = 1;
    const DEFAULT_CONTRACT_URL = '/static/contracts/process-map-spatial-contract-v1.json';
    const ARRANGEMENT_HARD_PROBLEM_CODES = new Set([
        'node_overlap',
        'insufficient_node_clearance',
        'node_group_header_intersection',
        'edge_node_intersection',
        'edge_group_header_intersection',
    ]);

    function clone(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function finiteNumber(value) {
        return typeof value === 'number' && Number.isFinite(value);
    }

    function positiveNumber(value) {
        return finiteNumber(value) && value > 0;
    }

    function validateContract(contract) {
        if (!contract || typeof contract !== 'object' || Array.isArray(contract)) {
            throw new Error('the process-map spatial contract must be an object');
        }
        if (contract.contractId !== CONTRACT_ID) {
            throw new Error('unsupported process-map spatial contract id');
        }
        if (contract.contractVersion !== 1) {
            throw new Error('unsupported process-map spatial contract version');
        }
        if (contract.spatialVersion !== SPATIAL_VERSION) {
            throw new Error('unsupported process-map spatial version');
        }
        if (!contract.coordinateSpaces || contract.coordinateSpaces.persisted !== 'world') {
            throw new Error('the persisted coordinate space must be world');
        }
        const geometry = contract.geometry;
        const envelopes = geometry && geometry.nodeEnvelopes;
        if (!envelopes || !envelopes.default) {
            throw new Error('node envelopes require a default geometry');
        }
        Object.keys(envelopes).forEach(function (name) {
            const envelope = envelopes[name];
            if (!envelope || !positiveNumber(envelope.width) || !positiveNumber(envelope.height)) {
                throw new Error("invalid node envelope '" + name + "'");
            }
        });
        const junction = geometry.junction;
        if (!junction || !positiveNumber(junction.visualDiameter)
            || !positiveNumber(junction.hitDiameter)
            || junction.visualDiameter > junction.hitDiameter) {
            throw new Error('invalid junction geometry');
        }
        if (!positiveNumber(geometry.groupHeaderHeight)) {
            throw new Error('invalid group header height');
        }
        if (!Number.isInteger(geometry.legacyBezierSamplingSegments)
            || geometry.legacyBezierSamplingSegments < 8
            || geometry.legacyBezierSamplingSegments > 128) {
            throw new Error('invalid legacy Bezier sampling segment count');
        }
        const diagnostics = contract.diagnostics;
        ['regionColumns', 'regionRows'].forEach(function (field) {
            if (!diagnostics || !Number.isInteger(diagnostics[field])
                || diagnostics[field] < 1 || diagnostics[field] > 12) {
                throw new Error("invalid diagnostics field '" + field + "'");
            }
        });
        ['denseOccupancyThreshold', 'alignmentWarningThreshold', 'detourRatioThreshold']
            .forEach(function (field) {
                if (!diagnostics || !positiveNumber(diagnostics[field])) {
                    throw new Error("invalid diagnostics field '" + field + "'");
                }
            });
        if (diagnostics.denseOccupancyThreshold > 1) {
            throw new Error('dense occupancy threshold cannot exceed one');
        }
        if (!Array.isArray(contract.flowDirections)
            || contract.flowDirections.indexOf('left_to_right') < 0) {
            throw new Error('left_to_right must be a supported flow direction');
        }
        if (!Array.isArray(contract.routeModes)
            || contract.routeModes.indexOf('bezier_legacy') < 0) {
            throw new Error('bezier_legacy must be a supported route mode');
        }
        const limits = contract.limits;
        [
            'maximumNodes',
            'maximumEdges',
            'maximumGroups',
            'maximumCandidates',
            'maximumRoutePoints',
        ].forEach(function (field) {
            if (!limits || !Number.isInteger(limits[field]) || limits[field] <= 0) {
                throw new Error("invalid spatial limit '" + field + "'");
            }
        });
        return clone(contract);
    }

    function loadSpatialContract(url, fetchImpl) {
        const request = fetchImpl || (typeof fetch === 'function' ? fetch : null);
        if (!request) return Promise.reject(new Error('fetch is unavailable'));
        return Promise.resolve(request(url || DEFAULT_CONTRACT_URL)).then(function (response) {
            if (!response || response.ok === false || typeof response.json !== 'function') {
                throw new Error('failed to load the process-map spatial contract');
            }
            return response.json();
        }).then(validateContract);
    }

    function spatialContractForProcessMap(processMap, contract) {
        const active = validateContract(contract);
        const policy = processMap && processMap.layoutPolicy;
        if (!policy || typeof policy !== 'object' || Array.isArray(policy)) return active;
        const allowed = new Set([
            'flowDirection',
            'gridSize',
            'nodeClearance',
            'edgeClearance',
            'portLeadLength',
            'routeMode',
        ]);
        Object.keys(policy).forEach(function (field) {
            if (!allowed.has(field)) {
                throw new Error('the process-map layout policy contains unsupported fields');
            }
        });
        Object.assign(active.layoutPolicyDefaults, clone(policy));
        return validateContract(active);
    }

    function spatialContractForScene(scene, contract) {
        return spatialContractForProcessMap(
            { layoutPolicy: scene && scene.layoutPolicy },
            contract
        );
    }

    function point(value, field) {
        if (!value || typeof value !== 'object' || !finiteNumber(value.x) || !finiteNumber(value.y)) {
            throw new Error(field + ' requires finite x and y values');
        }
        return { x: Number(value.x), y: Number(value.y) };
    }

    function rect(value, field) {
        const origin = point(value, field);
        if (!finiteNumber(value.width) || !finiteNumber(value.height)) {
            throw new Error(field + ' requires finite width and height values');
        }
        if (value.width < 0 || value.height < 0) {
            throw new Error(field + ' width and height cannot be negative');
        }
        return {
            x: origin.x,
            y: origin.y,
            width: Number(value.width),
            height: Number(value.height),
        };
    }

    function normalizedTransform(value) {
        if (!value || typeof value !== 'object' || !finiteNumber(value.x)
            || !finiteNumber(value.y) || !positiveNumber(value.scale)) {
            throw new Error('transform requires finite x/y and a positive scale');
        }
        return { x: Number(value.x), y: Number(value.y), scale: Number(value.scale) };
    }

    function worldToViewport(sourcePoint, transform) {
        const source = point(sourcePoint, 'point');
        const view = normalizedTransform(transform);
        return {
            x: source.x * view.scale + view.x,
            y: source.y * view.scale + view.y,
        };
    }

    function viewportToWorld(sourcePoint, transform) {
        const source = point(sourcePoint, 'point');
        const view = normalizedTransform(transform);
        return {
            x: (source.x - view.x) / view.scale,
            y: (source.y - view.y) / view.scale,
        };
    }

    function worldRectToViewport(sourceRect, transform) {
        const source = rect(sourceRect, 'rect');
        const view = normalizedTransform(transform);
        const origin = worldToViewport(source, view);
        return {
            x: origin.x,
            y: origin.y,
            width: source.width * view.scale,
            height: source.height * view.scale,
        };
    }

    function viewportRectToWorld(sourceRect, transform) {
        const source = rect(sourceRect, 'rect');
        const view = normalizedTransform(transform);
        const origin = viewportToWorld(source, view);
        return {
            x: origin.x,
            y: origin.y,
            width: source.width / view.scale,
            height: source.height / view.scale,
        };
    }

    function worldToNormalized(sourcePoint, worldBounds) {
        const source = point(sourcePoint, 'point');
        const bounds = rect(worldBounds, 'worldBounds');
        if (bounds.width <= 0 || bounds.height <= 0) {
            throw new Error('worldBounds must have positive width and height');
        }
        return {
            x: (source.x - bounds.x) / bounds.width,
            y: (source.y - bounds.y) / bounds.height,
        };
    }

    function nodeOrientation(node) {
        return node && node.portOrientation === 'vertical' ? 'vertical' : 'horizontal';
    }

    function nodeOrder(node) {
        return node && node.portOrder === 'output_first' ? 'output_first' : 'input_first';
    }

    function portDirection(orientation, order, side) {
        const leading = order === 'output_first' ? side === 'out' : side === 'in';
        if (orientation === 'vertical') return { x: 0, y: leading ? -1 : 1 };
        return { x: leading ? -1 : 1, y: 0 };
    }

    function portAnchor(bounds, orientation, order, side) {
        const leading = order === 'output_first' ? side === 'out' : side === 'in';
        if (orientation === 'vertical') {
            return {
                x: bounds.x + bounds.width / 2,
                y: leading ? bounds.y : bounds.y + bounds.height,
            };
        }
        return {
            x: leading ? bounds.x : bounds.x + bounds.width,
            y: bounds.y + bounds.height / 2,
        };
    }

    function rectangleBounds(rectangles) {
        const values = Array.isArray(rectangles) ? rectangles : [];
        if (!values.length) return { x: 0, y: 0, width: 1, height: 1 };
        const minimumX = Math.min.apply(null, values.map(function (value) { return value.x; }));
        const minimumY = Math.min.apply(null, values.map(function (value) { return value.y; }));
        const maximumX = Math.max.apply(null, values.map(function (value) {
            return value.x + value.width;
        }));
        const maximumY = Math.max.apply(null, values.map(function (value) {
            return value.y + value.height;
        }));
        return {
            x: minimumX,
            y: minimumY,
            width: maximumX - minimumX,
            height: maximumY - minimumY,
        };
    }

    function pointBounds(points) {
        const values = Array.isArray(points) ? points : [];
        if (!values.length) return { x: 0, y: 0, width: 0, height: 0 };
        const minimumX = Math.min.apply(null, values.map(function (value) { return value.x; }));
        const minimumY = Math.min.apply(null, values.map(function (value) { return value.y; }));
        const maximumX = Math.max.apply(null, values.map(function (value) { return value.x; }));
        const maximumY = Math.max.apply(null, values.map(function (value) { return value.y; }));
        return {
            x: minimumX,
            y: minimumY,
            width: maximumX - minimumX,
            height: maximumY - minimumY,
        };
    }

    function sortedValues(values, idField) {
        return (Array.isArray(values) ? values.slice() : []).sort(function (left, right) {
            return String((left && left[idField]) || '').localeCompare(
                String((right && right[idField]) || '')
            );
        });
    }

    function rounded(value) {
        const result = Number(Number(value).toFixed(6));
        return Object.is(result, -0) ? 0 : result;
    }

    function rectIntersection(left, right) {
        const x = Math.max(left.x, right.x);
        const y = Math.max(left.y, right.y);
        const maximumX = Math.min(left.x + left.width, right.x + right.width);
        const maximumY = Math.min(left.y + left.height, right.y + right.height);
        if (maximumX <= x || maximumY <= y) return null;
        return { x, y, width: maximumX - x, height: maximumY - y };
    }

    function rectDistance(left, right) {
        const dx = Math.max(
            left.x - (right.x + right.width),
            right.x - (left.x + left.width),
            0
        );
        const dy = Math.max(
            left.y - (right.y + right.height),
            right.y - (left.y + left.height),
            0
        );
        return Math.hypot(dx, dy);
    }

    function expandedRect(bounds, amount) {
        return {
            x: bounds.x - amount,
            y: bounds.y - amount,
            width: bounds.width + amount * 2,
            height: bounds.height + amount * 2,
        };
    }

    function SpatialGridIndex(cellSize) {
        this.cellSize = Math.max(Number(cellSize), 1);
        this.cells = new Map();
    }

    SpatialGridIndex.prototype._keys = function (bounds) {
        const keys = [];
        const minimumX = Math.floor(bounds.x / this.cellSize);
        const minimumY = Math.floor(bounds.y / this.cellSize);
        const maximumX = Math.floor((bounds.x + Math.max(bounds.width, 0)) / this.cellSize);
        const maximumY = Math.floor((bounds.y + Math.max(bounds.height, 0)) / this.cellSize);
        for (let row = minimumY; row <= maximumY; row += 1) {
            for (let column = minimumX; column <= maximumX; column += 1) {
                keys.push(column + ':' + row);
            }
        }
        return keys;
    };

    SpatialGridIndex.prototype.insert = function (recordId, bounds) {
        this._keys(bounds).forEach(function (key) {
            if (!this.cells.has(key)) this.cells.set(key, new Set());
            this.cells.get(key).add(recordId);
        }, this);
    };

    SpatialGridIndex.prototype.query = function (bounds) {
        const matches = new Set();
        this._keys(bounds).forEach(function (key) {
            const values = this.cells.get(key);
            if (values) values.forEach(function (value) { matches.add(value); });
        }, this);
        return Array.from(matches).sort();
    };

    function legacyBezierControls(start, end, sourceDirection, targetDirection) {
        const defaultHorizontal = sourceDirection.x === 1 && sourceDirection.y === 0
            && targetDirection.x === -1 && targetDirection.y === 0;
        if (defaultHorizontal) {
            const control = Math.max(88, Math.abs(end.x - start.x) * 0.48);
            return [
                { x: start.x + control, y: start.y },
                { x: end.x - control, y: end.y },
            ];
        }
        const control = Math.max(88, Math.hypot(end.x - start.x, end.y - start.y) * 0.38);
        return [
            {
                x: start.x + sourceDirection.x * control,
                y: start.y + sourceDirection.y * control,
            },
            {
                x: end.x + targetDirection.x * control,
                y: end.y + targetDirection.y * control,
            },
        ];
    }

    function sampleCubicBezier(start, first, second, end, segments) {
        const values = [];
        for (let index = 0; index <= segments; index += 1) {
            const t = index / segments;
            const inverse = 1 - t;
            values.push({
                x: inverse ** 3 * start.x
                    + 3 * inverse ** 2 * t * first.x
                    + 3 * inverse * t ** 2 * second.x
                    + t ** 3 * end.x,
                y: inverse ** 3 * start.y
                    + 3 * inverse ** 2 * t * first.y
                    + 3 * inverse * t ** 2 * second.y
                    + t ** 3 * end.y,
            });
        }
        return values;
    }

    function edgePathPoints(edge, nodeById, segments) {
        const points = (edge.points || []).map(function (value) { return clone(value); });
        if (points.length < 2 || edge.routeMode !== 'bezier_legacy') return points;
        const source = nodeById.get(String(edge.fromNodeId || '')) || {};
        const target = nodeById.get(String(edge.toNodeId || '')) || {};
        const sourceDirection = source.ports && source.ports.output && source.ports.output.direction;
        const targetDirection = target.ports && target.ports.input && target.ports.input.direction;
        if (!sourceDirection || !targetDirection) return points;
        const controls = legacyBezierControls(
            points[0], points[points.length - 1], sourceDirection, targetDirection
        );
        return sampleCubicBezier(
            points[0], controls[0], controls[1], points[points.length - 1], segments
        );
    }

    function lineSegments(points) {
        const values = [];
        for (let index = 0; index < points.length - 1; index += 1) {
            values.push([points[index], points[index + 1]]);
        }
        return values;
    }

    function boundedSegments(points) {
        return lineSegments(points).map(function (segment) {
            const start = segment[0];
            const end = segment[1];
            return {
                start,
                end,
                minX: Math.min(start.x, end.x),
                minY: Math.min(start.y, end.y),
                maxX: Math.max(start.x, end.x),
                maxY: Math.max(start.y, end.y),
            };
        });
    }

    function boundedPolylineIntersectsRect(segments, bounds) {
        const maximumX = bounds.x + bounds.width;
        const maximumY = bounds.y + bounds.height;
        const epsilon = 1e-9;
        return segments.some(function (segment) {
            if (segment.maxX < bounds.x - epsilon
                || segment.minX > maximumX + epsilon
                || segment.maxY < bounds.y - epsilon
                || segment.minY > maximumY + epsilon) return false;
            return segmentIntersectsRect(segment.start, segment.end, bounds);
        });
    }

    function pointInRect(value, bounds) {
        const epsilon = 1e-9;
        return value.x >= bounds.x - epsilon
            && value.x <= bounds.x + bounds.width + epsilon
            && value.y >= bounds.y - epsilon
            && value.y <= bounds.y + bounds.height + epsilon;
    }

    function segmentIntersectsRect(start, end, bounds) {
        if (pointInRect(start, bounds) || pointInRect(end, bounds)) return true;
        const dx = end.x - start.x;
        const dy = end.y - start.y;
        const coefficients = [-dx, dx, -dy, dy];
        const distances = [
            start.x - bounds.x,
            bounds.x + bounds.width - start.x,
            start.y - bounds.y,
            bounds.y + bounds.height - start.y,
        ];
        let minimum = 0;
        let maximum = 1;
        for (let index = 0; index < coefficients.length; index += 1) {
            const coefficient = coefficients[index];
            const distance = distances[index];
            if (Math.abs(coefficient) <= 1e-12) {
                if (distance < 0) return false;
                continue;
            }
            const ratio = distance / coefficient;
            if (coefficient < 0) minimum = Math.max(minimum, ratio);
            else maximum = Math.min(maximum, ratio);
            if (minimum > maximum) return false;
        }
        return true;
    }

    function polylineIntersectsRect(points, bounds) {
        return lineSegments(points).some(function (segment) {
            return segmentIntersectsRect(segment[0], segment[1], bounds);
        });
    }

    function segmentCrossing(firstStart, firstEnd, secondStart, secondEnd) {
        const firstDx = firstEnd.x - firstStart.x;
        const firstDy = firstEnd.y - firstStart.y;
        const secondDx = secondEnd.x - secondStart.x;
        const secondDy = secondEnd.y - secondStart.y;
        const denominator = firstDx * secondDy - firstDy * secondDx;
        if (Math.abs(denominator) <= 1e-9) return null;
        const offsetX = secondStart.x - firstStart.x;
        const offsetY = secondStart.y - firstStart.y;
        const firstRatio = (offsetX * secondDy - offsetY * secondDx) / denominator;
        const secondRatio = (offsetX * firstDy - offsetY * firstDx) / denominator;
        const epsilon = 1e-8;
        if (firstRatio < -epsilon || firstRatio > 1 + epsilon
            || secondRatio < -epsilon || secondRatio > 1 + epsilon) return null;
        return {
            x: firstStart.x + firstRatio * firstDx,
            y: firstStart.y + firstRatio * firstDy,
        };
    }

    function polylineCrossing(first, second) {
        // Precompute segment bounds once per polyline. Rebuilding rectangle
        // objects for every segment pair made diagnostics scale poorly.
        const firstSegments = boundedSegments(first);
        const secondSegments = boundedSegments(second);
        const padding = 2e-7;
        for (let firstIndex = 0; firstIndex < firstSegments.length; firstIndex += 1) {
            const firstSegment = firstSegments[firstIndex];
            for (let secondIndex = 0; secondIndex < secondSegments.length; secondIndex += 1) {
                const secondSegment = secondSegments[secondIndex];
                if (firstSegment.maxX + padding <= secondSegment.minX
                    || secondSegment.maxX + padding <= firstSegment.minX
                    || firstSegment.maxY + padding <= secondSegment.minY
                    || secondSegment.maxY + padding <= firstSegment.minY) continue;
                const crossing = segmentCrossing(
                    firstSegment.start, firstSegment.end,
                    secondSegment.start, secondSegment.end
                );
                if (crossing) return crossing;
            }
        }
        return null;
    }

    function polylineLength(points) {
        return lineSegments(points).reduce(function (total, segment) {
            return total + Math.hypot(
                segment[1].x - segment[0].x,
                segment[1].y - segment[0].y
            );
        }, 0);
    }

    function routeBends(edge) {
        if (edge.routeMode === 'bezier_legacy') return 0;
        const points = edge.points || [];
        let bends = 0;
        for (let index = 1; index < points.length - 1; index += 1) {
            const left = points[index - 1];
            const middle = points[index];
            const right = points[index + 1];
            const cross = (middle.x - left.x) * (right.y - middle.y)
                - (middle.y - left.y) * (right.x - middle.x);
            if (Math.abs(cross) > 1e-8) bends += 1;
        }
        return bends;
    }

    function problem(code, severity, recordIds, details) {
        return Object.assign({
            problemId: [code].concat(recordIds).join(':'),
            severity,
            code,
        }, details || {});
    }

    function regionLocation(row, column, rows, columns) {
        const vertical = {
            1: ['center'],
            2: ['upper', 'lower'],
            3: ['upper', 'middle', 'lower'],
        };
        const horizontal = {
            1: ['center'],
            2: ['left', 'right'],
            3: ['left', 'center', 'right'],
            4: ['left', 'center-left', 'center-right', 'right'],
        };
        const rowName = vertical[rows] ? vertical[rows][row] : 'row-' + (row + 1);
        const columnName = horizontal[columns]
            ? horizontal[columns][column]
            : 'column-' + (column + 1);
        return rowName + '-' + columnName;
    }

    function compileSpatialScene(processMap, options) {
        if (!processMap || typeof processMap !== 'object' || Array.isArray(processMap)) {
            throw new Error('processMap must be an object');
        }
        const opts = options || {};
        const contract = spatialContractForProcessMap(processMap, opts.contract);
        const geometry = contract.geometry;
        const limits = contract.limits;
        const rawNodes = processMap.canvasNodes || [];
        const rawEdges = processMap.canvasEdges || [];
        const rawGroups = processMap.canvasGroups || [];
        if (!Array.isArray(rawNodes) || !Array.isArray(rawEdges) || !Array.isArray(rawGroups)) {
            throw new Error('canvasNodes, canvasEdges, and canvasGroups must be arrays');
        }
        if (rawNodes.length > limits.maximumNodes) throw new Error('process map exceeds the spatial node limit');
        if (rawEdges.length > limits.maximumEdges) throw new Error('process map exceeds the spatial edge limit');
        if (rawGroups.length > limits.maximumGroups) throw new Error('process map exceeds the spatial group limit');

        const membership = new Map();
        const headerHeight = geometry.groupHeaderHeight;
        const groups = sortedValues(rawGroups, 'groupId').map(function (group) {
            if (!group || typeof group.groupId !== 'string' || !group.groupId) {
                throw new Error('each canvas group requires a groupId');
            }
            const position = point(group.position, "group '" + group.groupId + "' position");
            const sizeValue = group.size;
            if (!sizeValue || typeof sizeValue !== 'object') {
                throw new Error("group '" + group.groupId + "' requires a positive size");
            }
            const bounds = rect({
                x: position.x,
                y: position.y,
                width: sizeValue.width,
                height: sizeValue.height,
            }, "group '" + group.groupId + "' size");
            if (bounds.width <= 0 || bounds.height <= 0) {
                throw new Error("group '" + group.groupId + "' requires a positive size");
            }
            const members = group.memberNodeIds || [];
            if (!Array.isArray(members) || members.some(function (nodeId) {
                return typeof nodeId !== 'string' || !nodeId;
            })) {
                throw new Error("group '" + group.groupId + "' has invalid members");
            }
            members.forEach(function (nodeId) {
                if (membership.has(nodeId)) throw new Error("node '" + nodeId + "' belongs to multiple groups");
                membership.set(nodeId, group.groupId);
            });
            return {
                groupId: group.groupId,
                rect: bounds,
                headerRect: {
                    x: bounds.x,
                    y: bounds.y - headerHeight,
                    width: bounds.width,
                    height: headerHeight,
                },
                memberNodeIds: members.slice().sort(),
            };
        });

        const nodeById = new Map();
        const envelopes = geometry.nodeEnvelopes;
        const nodes = sortedValues(rawNodes, 'nodeId').map(function (node) {
            if (!node || typeof node.nodeId !== 'string' || !node.nodeId) {
                throw new Error('each canvas node requires a nodeId');
            }
            if (nodeById.has(node.nodeId)) throw new Error("duplicate canvas node '" + node.nodeId + "'");
            const position = point(node.position, "node '" + node.nodeId + "' position");
            const kind = String(node.nodeKind || 'product_occurrence');
            const junction = kind === 'junction';
            let bounds;
            let center;
            let orientation;
            let order;
            let inputAnchor;
            let outputAnchor;
            if (junction) {
                const diameter = geometry.junction.hitDiameter;
                bounds = {
                    x: position.x - diameter / 2,
                    y: position.y - diameter / 2,
                    width: diameter,
                    height: diameter,
                };
                center = position;
                orientation = 'horizontal';
                order = 'input_first';
                inputAnchor = center;
                outputAnchor = center;
            } else {
                const envelope = envelopes[kind] || envelopes.default;
                bounds = {
                    x: position.x,
                    y: position.y,
                    width: envelope.width,
                    height: envelope.height,
                };
                center = {
                    x: bounds.x + bounds.width / 2,
                    y: bounds.y + bounds.height / 2,
                };
                orientation = nodeOrientation(node);
                order = nodeOrder(node);
                inputAnchor = portAnchor(bounds, orientation, order, 'in');
                outputAnchor = portAnchor(bounds, orientation, order, 'out');
            }
            const compiled = {
                nodeId: node.nodeId,
                kind: kind,
                rect: bounds,
                center: center,
                portOrientation: orientation,
                portOrder: order,
                ports: {
                    input: Object.assign({}, inputAnchor, {
                        direction: portDirection(orientation, order, 'in'),
                    }),
                    output: Object.assign({}, outputAnchor, {
                        direction: portDirection(orientation, order, 'out'),
                    }),
                },
                groupId: membership.get(node.nodeId) || null,
                locked: node.locked === true,
                positionMode: ['auto', 'manual', 'locked'].indexOf(node.positionMode) >= 0
                    ? node.positionMode : (node.locked === true ? 'locked' : 'auto'),
            };
            nodeById.set(node.nodeId, compiled);
            return compiled;
        });

        const danglingMembers = Array.from(membership.keys()).filter(function (nodeId) {
            return !nodeById.has(nodeId);
        }).sort();
        if (danglingMembers.length) throw new Error("group references unknown node '" + danglingMembers[0] + "'");

        const edges = sortedValues(rawEdges, 'edgeId').map(function (edge) {
            if (!edge || typeof edge.edgeId !== 'string' || !edge.edgeId) {
                throw new Error('each canvas edge requires an edgeId');
            }
            const sourceId = edge.from && edge.from.nodeId;
            const targetId = edge.to && edge.to.nodeId;
            if (!nodeById.has(sourceId) || !nodeById.has(targetId)) {
                throw new Error("edge '" + edge.edgeId + "' has a dangling endpoint");
            }
            const routing = edge.routing && typeof edge.routing === 'object' ? edge.routing : {};
            const routeMode = String(routing.mode || 'bezier_legacy');
            if (contract.routeModes.indexOf(routeMode) < 0) {
                throw new Error("edge '" + edge.edgeId + "' has an unsupported route mode");
            }
            const start = clone(nodeById.get(sourceId).ports.output);
            const end = clone(nodeById.get(targetId).ports.input);
            delete start.direction;
            delete end.direction;
            let waypoints = [];
            if (routeMode !== 'bezier_legacy') {
                const rawWaypoints = routing.waypoints || [];
                if (!Array.isArray(rawWaypoints) || rawWaypoints.length > limits.maximumRoutePoints) {
                    throw new Error("edge '" + edge.edgeId + "' has invalid route waypoints");
                }
                waypoints = rawWaypoints.map(function (waypoint) {
                    return point(waypoint, "edge '" + edge.edgeId + "' waypoint");
                });
            }
            const points = [start].concat(waypoints, [end]);
            return {
                edgeId: edge.edgeId,
                logicalConnectionId: String(edge.logicalConnectionId || edge.edgeId),
                kind: String(edge.kind || 'precedence'),
                fromNodeId: sourceId,
                toNodeId: targetId,
                routeMode: routeMode,
                points: points,
                bounds: pointBounds(points),
                boundsApproximate: routeMode === 'bezier_legacy',
            };
        });

        const worldRectangles = nodes.map(function (node) { return node.rect; })
            .concat(groups.map(function (group) { return group.rect; }))
            .concat(groups.map(function (group) { return group.headerRect; }))
            .concat(edges.map(function (edge) { return edge.bounds; }));
        const identity = {
            productId: String(processMap.productId || ''),
            mapId: String(processMap.mapId || ''),
            layoutVersion: processMap.layoutVersion,
        };
        if (Object.prototype.hasOwnProperty.call(opts, 'revision') && opts.revision != null) {
            identity.revision = String(opts.revision);
        }
        const scene = {
            spatialVersion: SPATIAL_VERSION,
            contractId: CONTRACT_ID,
            identity: identity,
            worldBounds: rectangleBounds(worldRectangles),
            nodes: nodes,
            groups: groups,
            edges: edges,
        };
        if (processMap.layoutPolicy && typeof processMap.layoutPolicy === 'object' && !Array.isArray(processMap.layoutPolicy)) {
            scene.layoutPolicy = clone(contract.layoutPolicyDefaults);
        }
        return scene;
    }

    function diagnoseSpatialScene(scene, options) {
        if (!scene || typeof scene !== 'object' || Array.isArray(scene)) {
            throw new Error('scene must be an object');
        }
        if (scene.spatialVersion !== SPATIAL_VERSION) {
            throw new Error('scene has an unsupported spatial version');
        }
        if (scene.contractId !== CONTRACT_ID) {
            throw new Error('scene has an unsupported spatial contract');
        }
        const opts = options || {};
        const contract = spatialContractForScene(scene, opts.contract);
        const policy = contract.layoutPolicyDefaults;
        const diagnosticsPolicy = contract.diagnostics;
        const geometry = contract.geometry;
        const limits = contract.limits;
        const nodes = sortedValues(scene.nodes || [], 'nodeId');
        const groups = sortedValues(scene.groups || [], 'groupId');
        const edges = sortedValues(scene.edges || [], 'edgeId');
        const nodeById = new Map(nodes.map(function (node) {
            return [String(node.nodeId || ''), node];
        }));
        const authoredNodes = nodes.filter(function (node) { return node.kind !== 'junction'; });
        const authoredById = new Map(authoredNodes.map(function (node) {
            return [String(node.nodeId), node];
        }));
        const nodeClearance = Number(policy.nodeClearance);
        const gridSize = Number(policy.gridSize);
        const broadPhaseSize = Math.max(
            gridSize * 8,
            Number(geometry.nodeEnvelopes.default.width)
        );
        const nodeIndex = new SpatialGridIndex(broadPhaseSize);
        authoredNodes.forEach(function (node) {
            nodeIndex.insert(String(node.nodeId), node.rect);
        });

        const problems = [];
        let nodeOverlapCount = 0;
        let clearanceViolationCount = 0;
        let minimumClearance = null;
        authoredNodes.forEach(function (node, index) {
            authoredNodes.slice(index + 1).forEach(function (other) {
                const clearance = rectDistance(node.rect, other.rect);
                minimumClearance = minimumClearance == null
                    ? clearance
                    : Math.min(minimumClearance, clearance);
            });
        });
        authoredNodes.forEach(function (node) {
            const nodeId = String(node.nodeId);
            nodeIndex.query(expandedRect(node.rect, nodeClearance)).forEach(function (otherId) {
                if (otherId <= nodeId) return;
                const other = authoredById.get(otherId);
                const overlap = rectIntersection(node.rect, other.rect);
                const clearance = overlap ? 0 : rectDistance(node.rect, other.rect);
                const pair = [nodeId, otherId];
                if (overlap) {
                    nodeOverlapCount += 1;
                    problems.push(problem('node_overlap', 'warning', pair, {
                        nodeIds: pair,
                        overlapArea: rounded(overlap.width * overlap.height),
                    }));
                } else if (clearance < nodeClearance) {
                    clearanceViolationCount += 1;
                    problems.push(problem('insufficient_node_clearance', 'warning', pair, {
                        nodeIds: pair,
                        clearance: rounded(clearance),
                    }));
                }
            });
        });

        let nodeGroupHeaderCount = 0;
        groups.forEach(function (group) {
            const groupId = String(group.groupId || '');
            nodeIndex.query(group.headerRect).forEach(function (nodeId) {
                const node = authoredById.get(nodeId);
                if (!rectIntersection(node.rect, group.headerRect)) return;
                nodeGroupHeaderCount += 1;
                problems.push(problem(
                    'node_group_header_intersection', 'warning', [groupId, nodeId], {
                        nodeIds: [nodeId],
                        groupIds: [groupId],
                    }
                ));
            });
        });

        const sampledEdges = [];
        let routeLength = 0;
        let totalRouteBends = 0;
        const detourRatios = [];
        let backwardCount = 0;
        let detourCount = 0;
        const samplingSegments = geometry.legacyBezierSamplingSegments;
        const flowDirection = String(policy.flowDirection);
        const backwardTolerance = gridSize / 2;
        edges.forEach(function (edge) {
            const pathPoints = edgePathPoints(edge, nodeById, samplingSegments);
            const pathBounds = pointBounds(pathPoints);
            const length = polylineLength(pathPoints);
            const direct = pathPoints.length >= 2
                ? Math.hypot(
                    pathPoints[pathPoints.length - 1].x - pathPoints[0].x,
                    pathPoints[pathPoints.length - 1].y - pathPoints[0].y
                )
                : 0;
            const ratio = direct > 1e-9 ? length / direct : 1;
            const edgeId = String(edge.edgeId || '');
            const compiled = {
                edge,
                edgeId,
                points: pathPoints,
                segments: boundedSegments(pathPoints),
                bounds: pathBounds,
                length,
                detourRatio: ratio,
            };
            sampledEdges.push(compiled);
            routeLength += length;
            totalRouteBends += routeBends(edge);
            detourRatios.push(ratio);
            if (ratio > diagnosticsPolicy.detourRatioThreshold) {
                detourCount += 1;
                problems.push(problem('route_detour', 'information', [edgeId], {
                    edgeIds: [edgeId],
                    detourRatio: rounded(ratio),
                }));
            }
            const source = nodeById.get(String(edge.fromNodeId || '')) || {};
            const target = nodeById.get(String(edge.toNodeId || '')) || {};
            const sourceCenter = source.center || pathPoints[0] || { x: 0, y: 0 };
            const targetCenter = target.center
                || pathPoints[pathPoints.length - 1]
                || { x: 0, y: 0 };
            const backward = (flowDirection === 'left_to_right'
                    && targetCenter.x < sourceCenter.x - backwardTolerance)
                || (flowDirection === 'right_to_left'
                    && targetCenter.x > sourceCenter.x + backwardTolerance)
                || (flowDirection === 'top_to_bottom'
                    && targetCenter.y < sourceCenter.y - backwardTolerance)
                || (flowDirection === 'bottom_to_top'
                    && targetCenter.y > sourceCenter.y + backwardTolerance);
            if (backward) {
                backwardCount += 1;
                problems.push(problem('backward_flow_edge', 'information', [edgeId], {
                    edgeIds: [edgeId],
                    nodeIds: [String(edge.fromNodeId || ''), String(edge.toNodeId || '')],
                }));
            }
        });

        let edgeNodeCount = 0;
        let edgeGroupHeaderCount = 0;
        sampledEdges.forEach(function (sampled) {
            const edge = sampled.edge;
            const endpointIds = new Set([
                String(edge.fromNodeId || ''),
                String(edge.toNodeId || ''),
            ]);
            nodeIndex.query(sampled.bounds).forEach(function (nodeId) {
                if (endpointIds.has(nodeId)) return;
                const node = authoredById.get(nodeId);
                if (!boundedPolylineIntersectsRect(sampled.segments, node.rect)) return;
                edgeNodeCount += 1;
                problems.push(problem('edge_node_intersection', 'warning', [sampled.edgeId, nodeId], {
                    edgeIds: [sampled.edgeId],
                    nodeIds: [nodeId],
                }));
            });
            groups.forEach(function (group) {
                const groupId = String(group.groupId || '');
                if (!boundedPolylineIntersectsRect(sampled.segments, group.headerRect)) return;
                edgeGroupHeaderCount += 1;
                problems.push(problem(
                    'edge_group_header_intersection',
                    'warning',
                    [sampled.edgeId, groupId],
                    { edgeIds: [sampled.edgeId], groupIds: [groupId] }
                ));
            });
        });

        const segmentCellSize = Math.max(gridSize * 4, Number(policy.edgeClearance) * 4);
        const segmentIndex = new SpatialGridIndex(segmentCellSize);
        const segmentByKey = new Map();
        sampledEdges.forEach(function (sampled, edgeOrder) {
            sampled.segments.forEach(function (segment, segmentOrder) {
                const segmentKey = String(edgeOrder).padStart(4, '0')
                    + ':' + String(segmentOrder).padStart(4, '0');
                const bounds = {
                    x: segment.minX,
                    y: segment.minY,
                    width: segment.maxX - segment.minX,
                    height: segment.maxY - segment.minY,
                };
                segmentByKey.set(segmentKey, {
                    edgeId: sampled.edgeId,
                    edge: sampled.edge,
                    start: segment.start,
                    end: segment.end,
                    bounds,
                });
                segmentIndex.insert(segmentKey, bounds);
            });
        });
        let edgeCrossingCount = 0;
        const crossedPairs = new Set();
        const ineligiblePairs = new Set();
        sampledEdges.forEach(function (sampled, edgeOrder) {
            const edge = sampled.edge;
            const endpointIds = new Set([
                String(edge.fromNodeId || ''),
                String(edge.toNodeId || ''),
            ]);
            sampled.segments.forEach(function (segment, segmentOrder) {
                const segmentKey = String(edgeOrder).padStart(4, '0')
                    + ':' + String(segmentOrder).padStart(4, '0');
                const queryBounds = {
                    x: segment.minX - 1e-7,
                    y: segment.minY - 1e-7,
                    width: segment.maxX - segment.minX + 2e-7,
                    height: segment.maxY - segment.minY + 2e-7,
                };
                segmentIndex.query(queryBounds).forEach(function (otherKey) {
                    if (otherKey <= segmentKey) return;
                    const other = segmentByKey.get(otherKey);
                    if (other.edgeId <= sampled.edgeId) return;
                    const pairKey = sampled.edgeId + '\u0000' + other.edgeId;
                    if (crossedPairs.has(pairKey) || ineligiblePairs.has(pairKey)) return;
                    const otherEdge = other.edge;
                    if (String(edge.logicalConnectionId || sampled.edgeId)
                        === String(otherEdge.logicalConnectionId || other.edgeId)) {
                        ineligiblePairs.add(pairKey);
                        return;
                    }
                    const otherEndpoints = [
                        String(otherEdge.fromNodeId || ''),
                        String(otherEdge.toNodeId || ''),
                    ];
                    if (otherEndpoints.some(function (nodeId) { return endpointIds.has(nodeId); })) {
                        ineligiblePairs.add(pairKey);
                        return;
                    }
                    const crossing = segmentCrossing(
                        segment.start, segment.end, other.start, other.end
                    );
                    if (!crossing) return;
                    crossedPairs.add(pairKey);
                    edgeCrossingCount += 1;
                    problems.push(problem(
                        'edge_crossing',
                        'information',
                        [sampled.edgeId, other.edgeId],
                        {
                            edgeIds: [sampled.edgeId, other.edgeId],
                            point: { x: rounded(crossing.x), y: rounded(crossing.y) },
                        }
                    ));
                });
            });
        });

        const alignmentValues = [];
        let alignmentWarningCount = 0;
        const alignmentThreshold = Number(diagnosticsPolicy.alignmentWarningThreshold);
        authoredNodes.forEach(function (node) {
            const remainderX = Math.abs(node.rect.x) % gridSize;
            const remainderY = Math.abs(node.rect.y) % gridSize;
            const dx = Math.min(remainderX, gridSize - remainderX);
            const dy = Math.min(remainderY, gridSize - remainderY);
            const deviation = (dx + dy) / 2;
            alignmentValues.push(deviation);
            if (deviation > alignmentThreshold) alignmentWarningCount += 1;
        });

        const diagnosticRectangles = nodes.map(function (node) { return node.rect; })
            .concat(groups.map(function (group) { return group.rect; }))
            .concat(groups.map(function (group) { return group.headerRect; }))
            .concat(sampledEdges.map(function (sampled) { return sampled.bounds; }));
        const worldBounds = rectangleBounds(diagnosticRectangles);
        const columns = diagnosticsPolicy.regionColumns;
        const rows = diagnosticsPolicy.regionRows;
        const regionWidth = worldBounds.width > 0 ? worldBounds.width / columns : 1;
        const regionHeight = worldBounds.height > 0 ? worldBounds.height / rows : 1;
        const denseThreshold = diagnosticsPolicy.denseOccupancyThreshold;
        const regions = [];
        let denseRegionCount = 0;
        let openRegionCount = 0;
        for (let row = 0; row < rows; row += 1) {
            for (let column = 0; column < columns; column += 1) {
                const regionRect = {
                    x: worldBounds.x + column * regionWidth,
                    y: worldBounds.y + row * regionHeight,
                    width: regionWidth,
                    height: regionHeight,
                };
                let occupiedArea = 0;
                const intersectingIds = [];
                authoredNodes.forEach(function (node) {
                    const overlap = rectIntersection(regionRect, node.rect);
                    if (!overlap) return;
                    intersectingIds.push(String(node.nodeId));
                    occupiedArea += overlap.width * overlap.height;
                });
                const area = Math.max(regionRect.width * regionRect.height, 1);
                const occupancy = Math.min(1, occupiedArea / area);
                let classification;
                if (!intersectingIds.length) {
                    classification = 'open';
                    openRegionCount += 1;
                } else if (occupancy >= denseThreshold || intersectingIds.length >= 3) {
                    classification = 'dense';
                    denseRegionCount += 1;
                } else {
                    classification = 'balanced';
                }
                regions.push({
                    regionId: 'region-r' + (row + 1) + '-c' + (column + 1),
                    relativeLocation: regionLocation(row, column, rows, columns),
                    normalizedBounds: {
                        x: rounded(column / columns),
                        y: rounded(row / rows),
                        width: rounded(1 / columns),
                        height: rounded(1 / rows),
                    },
                    nodeIds: intersectingIds.sort(),
                    occupancy: rounded(occupancy),
                    classification,
                });
            }
        }

        const severityOrder = { error: 0, warning: 1, information: 2 };
        problems.sort(function (left, right) {
            const severity = (severityOrder[left.severity] == null ? 9 : severityOrder[left.severity])
                - (severityOrder[right.severity] == null ? 9 : severityOrder[right.severity]);
            if (severity) return severity;
            const codeOrder = String(left.code || '').localeCompare(String(right.code || ''));
            return codeOrder || String(left.problemId || '').localeCompare(String(right.problemId || ''));
        });
        const problemCount = problems.length;
        const boundedProblems = problems.slice(0, limits.maximumCandidates);
        return {
            spatialVersion: SPATIAL_VERSION,
            layoutPolicy: {
                flowDirection,
                gridSize: rounded(gridSize),
                nodeClearance: rounded(nodeClearance),
                edgeClearance: rounded(Number(policy.edgeClearance)),
            },
            metrics: {
                nodeOverlaps: nodeOverlapCount,
                nodeClearanceViolations: clearanceViolationCount,
                minimumNodeClearance: minimumClearance == null ? null : rounded(minimumClearance),
                nodeGroupHeaderIntersections: nodeGroupHeaderCount,
                edgeNodeIntersections: edgeNodeCount,
                edgeGroupHeaderIntersections: edgeGroupHeaderCount,
                edgeCrossings: edgeCrossingCount,
                backwardEdges: backwardCount,
                routeLength: rounded(routeLength),
                routeBends: totalRouteBends,
                routeDetourOpportunities: detourCount,
                meanDetourRatio: rounded(detourRatios.length
                    ? detourRatios.reduce(function (total, value) { return total + value; }, 0)
                        / detourRatios.length
                    : 0),
                alignmentDeviation: rounded(alignmentValues.length
                    ? alignmentValues.reduce(function (total, value) { return total + value; }, 0)
                        / alignmentValues.length
                    : 0),
                alignmentWarnings: alignmentWarningCount,
                denseRegions: denseRegionCount,
                openRegions: openRegionCount,
                worldRegionCount: regions.length,
            },
            problems: boundedProblems,
            problemCount,
            truncatedProblems: Math.max(0, problemCount - boundedProblems.length),
            regions,
        };
    }

    const CANDIDATE_POLICY_VERSION = 1;

    function fingerprintStable(value) {
        if (typeof value === 'boolean') return value;
        if (typeof value === 'number') return (value === 0 ? 0 : value).toFixed(6);
        if (Array.isArray(value)) return value.map(fingerprintStable);
        if (value && typeof value === 'object') {
            const sorted = {};
            Object.keys(value).sort().forEach(function (key) {
                sorted[key] = fingerprintStable(value[key]);
            });
            return sorted;
        }
        return value;
    }

    function canonicalBytes(value) {
        return JSON.stringify(fingerprintStable(value));
    }

    const FNV64_OFFSET_BASIS = 14695981039346656037n;
    const FNV64_PRIME = 1099511628211n;
    const FNV64_MASK = (1n << 64n) - 1n;

    function utf8Bytes(text) {
        const bytes = [];
        for (let index = 0; index < text.length; index += 1) {
            const code = text.codePointAt(index);
            if (code < 0x80) {
                bytes.push(code);
            } else if (code < 0x800) {
                bytes.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
            } else if (code < 0x10000) {
                bytes.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
            } else {
                bytes.push(
                    0xf0 | (code >> 18), 0x80 | ((code >> 12) & 0x3f),
                    0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f)
                );
                index += 1;
            }
        }
        return bytes;
    }

    // Not a security boundary: staleness authority comes from the existing
    // sha256 map revision. FNV-1a-64 only needs to be stable and
    // collision-safe enough to detect geometry drift, with exact parity
    // against the Python mirror guaranteed by native big-integer arithmetic
    // on both sides rather than a hand-rolled cross-language SHA-256.
    function fnv1a64Hex(text) {
        let value = FNV64_OFFSET_BASIS;
        const bytes = utf8Bytes(text);
        for (let index = 0; index < bytes.length; index += 1) {
            value ^= BigInt(bytes[index]);
            value = (value * FNV64_PRIME) & FNV64_MASK;
        }
        return value.toString(16).padStart(16, '0');
    }

    function obstacleFingerprint(scene) {
        const payload = {
            nodes: sortedValues(scene.nodes || [], 'nodeId').map(function (node) {
                return { id: node.nodeId, rect: node.rect, locked: node.locked || false };
            }),
            groups: sortedValues(scene.groups || [], 'groupId').map(function (group) {
                return { id: group.groupId, rect: group.rect };
            }),
            edges: sortedValues(scene.edges || [], 'edgeId').map(function (edge) {
                return { id: edge.edgeId, kind: edge.kind, points: edge.points };
            }),
        };
        return fnv1a64Hex(canonicalBytes(payload));
    }

    function routeObstacleFingerprint(scene, edgeId) {
        const payload = {
            nodes: sortedValues(scene.nodes || [], 'nodeId').map(function (node) {
                return { id: node.nodeId, rect: node.rect, ports: node.ports || {} };
            }),
            groupHeaders: sortedValues(scene.groups || [], 'groupId').map(function (group) {
                return { id: group.groupId, rect: group.headerRect };
            }),
            edges: sortedValues(scene.edges || [], 'edgeId').filter(function (edge) {
                return edge.edgeId !== edgeId && edge.routeMode !== 'orthogonal_auto';
            }).map(function (edge) {
                return {
                    id: edge.edgeId,
                    from: edge.fromNodeId,
                    to: edge.toNodeId,
                    points: edge.points || [],
                };
            }),
        };
        return fnv1a64Hex(canonicalBytes(payload));
    }

    function normalizeOrthogonalPoints(points) {
        let normalized = [];
        (points || []).forEach(function (raw) {
            const pointValue = { x: rounded(Number(raw.x)), y: rounded(Number(raw.y)) };
            const previous = normalized[normalized.length - 1];
            if (previous && previous.x === pointValue.x && previous.y === pointValue.y) return;
            normalized.push(pointValue);
        });
        let changed = true;
        while (changed && normalized.length >= 3) {
            changed = false;
            const compacted = [normalized[0]];
            for (let index = 1; index < normalized.length - 1; index += 1) {
                const left = compacted[compacted.length - 1];
                const middle = normalized[index];
                const right = normalized[index + 1];
                const sameX = Math.abs(left.x - middle.x) <= 1e-8
                    && Math.abs(middle.x - right.x) <= 1e-8;
                const sameY = Math.abs(left.y - middle.y) <= 1e-8
                    && Math.abs(middle.y - right.y) <= 1e-8;
                if (sameX || sameY) {
                    changed = true;
                    continue;
                }
                compacted.push(middle);
            }
            compacted.push(normalized[normalized.length - 1]);
            normalized = compacted;
        }
        return normalized;
    }

    function isOrthogonalPath(points) {
        for (let index = 0; index < points.length - 1; index += 1) {
            if (Math.abs(points[index].x - points[index + 1].x) > 1e-8
                && Math.abs(points[index].y - points[index + 1].y) > 1e-8) return false;
        }
        return true;
    }

    function routeIntersectsObstacles(points, obstacles) {
        const pathBounds = pointBounds(points);
        return obstacles.some(function (obstacle) {
            if (!rectIntersection(expandedRect(pathBounds, 1e-7), obstacle.rect)) return false;
            return polylineIntersectsRect(points, obstacle.rect);
        });
    }

    function selectRouteLanes(values, midpoint, limit) {
        const safeLimit = limit || 32;
        const unique = Array.from(new Set(values.map(function (value) {
            return rounded(Number(value));
        }))).sort(function (left, right) { return left - right; });
        if (unique.length <= safeLimit) return unique;
        const chosen = new Set([unique[0], unique[unique.length - 1]]);
        unique.slice().sort(function (left, right) {
            return Math.abs(left - midpoint) - Math.abs(right - midpoint) || left - right;
        }).some(function (value) {
            chosen.add(value);
            return chosen.size >= safeLimit;
        });
        return Array.from(chosen).sort(function (left, right) { return left - right; });
    }

    function routeBendCount(points) {
        let bends = 0;
        for (let index = 1; index < points.length - 1; index += 1) {
            const leftHorizontal = Math.abs(points[index - 1].y - points[index].y) <= 1e-8;
            const rightHorizontal = Math.abs(points[index].y - points[index + 1].y) <= 1e-8;
            if (leftHorizontal !== rightHorizontal) bends += 1;
        }
        return bends;
    }

    function prepareRouteCrossings(scene, routedEdge, nodeById, samplingSegments, cellSize) {
        const endpointIds = new Set([String(routedEdge.fromNodeId || ''), String(routedEdge.toNodeId || '')]);
        const index = new SpatialGridIndex(cellSize);
        const segments = new Map();
        (scene.edges || []).forEach(function (other) {
            if (other.edgeId === routedEdge.edgeId) return;
            const otherEndpoints = [String(other.fromNodeId || ''), String(other.toNodeId || '')];
            if (otherEndpoints.some(function (nodeId) { return endpointIds.has(nodeId); })) return;
            const otherPoints = edgePathPoints(other, nodeById, samplingSegments);
            if (otherPoints.length < 2) return;
            boundedSegments(otherPoints).forEach(function (segment, segmentIndex) {
                const recordId = String(other.edgeId || '') + ':' + segmentIndex;
                const bounds = expandedRect({
                    x: segment.minX,
                    y: segment.minY,
                    width: segment.maxX - segment.minX,
                    height: segment.maxY - segment.minY,
                }, 1e-7);
                segments.set(recordId, {
                    edgeId: String(other.edgeId || ''),
                    start: segment.start,
                    end: segment.end,
                });
                index.insert(recordId, bounds);
            });
        });
        return { index: index, segments: segments };
    }

    function routeCrossingCount(points, prepared) {
        const crossedEdges = new Set();
        boundedSegments(points).forEach(function (candidate) {
            const bounds = expandedRect({
                x: candidate.minX,
                y: candidate.minY,
                width: candidate.maxX - candidate.minX,
                height: candidate.maxY - candidate.minY,
            }, 1e-7);
            prepared.index.query(bounds).some(function (recordId) {
                const other = prepared.segments.get(recordId);
                if (!other || crossedEdges.has(other.edgeId)) return false;
                if (segmentCrossing(candidate.start, candidate.end, other.start, other.end)) {
                    crossedEdges.add(other.edgeId);
                }
                return false;
            });
        });
        return crossedEdges.size;
    }

    function routeOrthogonalEdge(scene, edgeId, options) {
        const opts = options || {};
        if (!scene || scene.spatialVersion !== SPATIAL_VERSION) {
            throw new Error('scene has an unsupported spatial version');
        }
        const contract = spatialContractForScene(scene, opts.contract);
        const policy = contract.layoutPolicyDefaults;
        const geometry = contract.geometry;
        const edge = (scene.edges || []).find(function (item) { return item.edgeId === edgeId; });
        if (!edge) throw new Error("unknown edge '" + edgeId + "'");
        const nodeById = new Map((scene.nodes || []).map(function (node) {
            return [String(node.nodeId || ''), node];
        }));
        const source = nodeById.get(String(edge.fromNodeId || ''));
        const target = nodeById.get(String(edge.toNodeId || ''));
        if (!source || !target) throw new Error("edge '" + edgeId + "' has a dangling endpoint");

        const startPort = source.ports.output;
        const endPort = target.ports.input;
        const start = { x: Number(startPort.x), y: Number(startPort.y) };
        const end = { x: Number(endPort.x), y: Number(endPort.y) };
        const leadLength = Number(policy.portLeadLength);
        const startLead = {
            x: start.x + Number(startPort.direction.x) * leadLength,
            y: start.y + Number(startPort.direction.y) * leadLength,
        };
        const endLead = {
            x: end.x + Number(endPort.direction.x) * leadLength,
            y: end.y + Number(endPort.direction.y) * leadLength,
        };
        const clearance = Number(policy.edgeClearance);
        const endpointIds = new Set([source.nodeId, target.nodeId]);
        const obstacles = [];
        sortedValues(scene.nodes || [], 'nodeId').forEach(function (node) {
            if (endpointIds.has(node.nodeId)) return;
            obstacles.push({ id: 'node:' + node.nodeId, rect: expandedRect(node.rect, clearance) });
        });
        sortedValues(scene.groups || [], 'groupId').forEach(function (group) {
            obstacles.push({
                id: 'group-header:' + group.groupId,
                rect: expandedRect(group.headerRect, clearance),
            });
        });

        const world = scene.worldBounds || pointBounds([start, end]);
        const grid = Number(policy.gridSize);
        const laneOffset = 1;
        const xValues = [
            startLead.x, endLead.x,
            Number(world.x) - clearance - grid,
            Number(world.x) + Number(world.width) + clearance + grid,
        ];
        const yValues = [
            startLead.y, endLead.y,
            Number(world.y) - clearance - grid,
            Number(world.y) + Number(world.height) + clearance + grid,
        ];
        obstacles.forEach(function (obstacle) {
            xValues.push(obstacle.rect.x - laneOffset, obstacle.rect.x + obstacle.rect.width + laneOffset);
            yValues.push(obstacle.rect.y - laneOffset, obstacle.rect.y + obstacle.rect.height + laneOffset);
        });
        const midpointX = (startLead.x + endLead.x) / 2;
        const midpointY = (startLead.y + endLead.y) / 2;
        const xLanes = selectRouteLanes(xValues, midpointX, 32);
        const yLanes = selectRouteLanes(yValues, midpointY, 32);
        const middleCandidates = [
            [startLead, endLead],
            [startLead, { x: endLead.x, y: startLead.y }, endLead],
            [startLead, { x: startLead.x, y: endLead.y }, endLead],
        ];
        xLanes.forEach(function (lane) {
            middleCandidates.push([
                startLead,
                { x: lane, y: startLead.y },
                { x: lane, y: endLead.y },
                endLead,
            ]);
        });
        yLanes.forEach(function (lane) {
            middleCandidates.push([
                startLead,
                { x: startLead.x, y: lane },
                { x: endLead.x, y: lane },
                endLead,
            ]);
        });
        const nearX = xLanes.slice().sort(function (left, right) {
            return Math.abs(left - midpointX) - Math.abs(right - midpointX) || left - right;
        }).slice(0, 8);
        const nearY = yLanes.slice().sort(function (left, right) {
            return Math.abs(left - midpointY) - Math.abs(right - midpointY) || left - right;
        }).slice(0, 8);
        nearX.forEach(function (xLane) {
            nearY.forEach(function (yLane) {
                middleCandidates.push([
                    startLead,
                    { x: xLane, y: startLead.y },
                    { x: xLane, y: yLane },
                    { x: endLead.x, y: yLane },
                    endLead,
                ]);
                middleCandidates.push([
                    startLead,
                    { x: startLead.x, y: yLane },
                    { x: xLane, y: yLane },
                    { x: xLane, y: endLead.y },
                    endLead,
                ]);
            });
        });

        const samplingSegments = Number(geometry.legacyBezierSamplingSegments);
        const crossingData = prepareRouteCrossings(
            scene,
            edge,
            nodeById,
            samplingSegments,
            Math.max(grid * 8, 160)
        );
        const seen = new Set();
        const ranked = [];
        middleCandidates.forEach(function (middle) {
            const points = normalizeOrthogonalPoints([start].concat(middle, [end]));
            if (points.length < 2 || !isOrthogonalPath(points)) return;
            const identity = canonicalBytes(points);
            if (seen.has(identity)) return;
            seen.add(identity);
            if (routeIntersectsObstacles(points, obstacles)) return;
            const crossings = routeCrossingCount(points, crossingData);
            const bends = routeBendCount(points);
            const length = rounded(polylineLength(points));
            ranked.push({
                score: [crossings, bends, length, identity],
                points: points,
                metrics: { crossings: crossings, bends: bends, length: length },
            });
        });
        const obstacleFingerprintValue = routeObstacleFingerprint(scene, edgeId);
        const resultBase = {
            routerVersion: ROUTER_VERSION,
            edgeId: edgeId,
            mode: 'orthogonal_auto',
            obstacleFingerprint: obstacleFingerprintValue,
            evaluatedCount: seen.size,
        };
        if (!ranked.length) {
            return Object.assign({}, resultBase, {
                accepted: false,
                failureReason: 'no_obstacle_free_orthogonal_route',
                points: [],
                waypoints: [],
            });
        }
        ranked.sort(function (left, right) {
            for (let index = 0; index < left.score.length; index += 1) {
                if (left.score[index] < right.score[index]) return -1;
                if (left.score[index] > right.score[index]) return 1;
            }
            return 0;
        });
        const winner = ranked[0];
        const routeId = fnv1a64Hex(canonicalBytes({
            edgeId: edgeId,
            obstacles: obstacleFingerprintValue,
            points: winner.points,
        }));
        return Object.assign({}, resultBase, {
            accepted: true,
            failureReason: null,
            routeId: routeId,
            points: winner.points,
            waypoints: winner.points.slice(1, -1),
            bounds: pointBounds(winner.points),
            metrics: winner.metrics,
        });
    }

    function suggestedNodeId(suggestionId) {
        const value = String(suggestionId || '');
        const suffix = (value.indexOf('pms-') === 0 ? value.slice(4) : value).slice(0, 20);
        return 'pm-node-suggest-' + (suffix || 'target');
    }

    function spatialProposal(suggestion, edge, route, placement) {
        const suggestionId = String(suggestion.suggestionId || '');
        const evidenceFingerprint = String(suggestion.evidenceFingerprint || '');
        const identity = {
            proposalVersion: SPATIAL_PROPOSAL_VERSION,
            semanticSuggestionId: suggestionId,
            semanticEvidenceFingerprint: evidenceFingerprint,
            edge: edge,
            routeId: route.routeId || null,
            obstacleFingerprint: route.obstacleFingerprint || null,
            placement: placement || null,
        };
        const proposal = {
            proposalVersion: SPATIAL_PROPOSAL_VERSION,
            proposalId: 'pm-sp-' + fnv1a64Hex(canonicalBytes(identity)),
            semanticSuggestionId: suggestionId,
            semanticEvidenceFingerprint: evidenceFingerprint,
            spatialEngineVersion: SPATIAL_VERSION,
            routerVersion: ROUTER_VERSION,
            accepted: !!route.accepted,
            failureReason: route.failureReason || null,
            obstacleFingerprint: route.obstacleFingerprint || null,
            edge: clone(edge),
            route: {
                routeId: route.routeId || null,
                mode: route.mode || null,
                points: clone(route.points || []),
                waypoints: clone(route.waypoints || []),
                bounds: route.bounds ? clone(route.bounds) : null,
                metrics: route.metrics ? clone(route.metrics) : null,
            },
        };
        if (placement) proposal.placement = clone(placement);
        return proposal;
    }

    function appendSuggestionEdge(processMap, edge) {
        const nextMap = clone(processMap);
        if (!Array.isArray(nextMap.canvasEdges)) nextMap.canvasEdges = [];
        nextMap.canvasEdges.push(clone(edge));
        return nextMap;
    }

    function spatializeSemanticSuggestions(processMap, suggestions, options) {
        const opts = options || {};
        const contract = spatialContractForProcessMap(processMap, opts.contract);
        const original = clone(processMap);
        const nodeIds = new Set((original.canvasNodes || []).map(function (node) {
            return String(node && node.nodeId || '');
        }));
        const result = [];
        let routed = 0;
        let placed = 0;
        let unavailable = 0;

        (Array.isArray(suggestions) ? suggestions : []).forEach(function (raw) {
            const suggestion = clone(raw || {});
            delete suggestion.spatialProposal;
            if (suggestion.validation && suggestion.validation.wouldCreateCycle) {
                result.push(suggestion);
                return;
            }

            let edge = suggestion.edge;
            const placementRequest = suggestion.placement;
            let placement = null;
            let transient = original;

            if (placementRequest && typeof placementRequest === 'object') {
                const anchorId = String(placementRequest.anchorNodeId || '');
                const occurrenceId = String(placementRequest.sourceOccurrenceId || '');
                const direction = String(placementRequest.connectionDirection || 'outgoing');
                if (!anchorId || !nodeIds.has(anchorId) || !occurrenceId) {
                    result.push(suggestion);
                    unavailable += 1;
                    return;
                }
                const scene = compileSpatialScene(original, { contract: contract });
                const candidates = generatePlacementCandidates(scene, {
                    contract: contract,
                    targetKind: 'product_occurrence',
                    anchorNodeId: anchorId,
                    connectionDirection: direction,
                    limit: 1,
                });
                if (!candidates.candidates.length) {
                    result.push(suggestion);
                    unavailable += 1;
                    return;
                }
                const candidate = candidates.candidates[0];
                const nodeId = String(
                    placementRequest.nodeId || suggestedNodeId(suggestion.suggestionId)
                );
                if (nodeIds.has(nodeId)) {
                    result.push(suggestion);
                    unavailable += 1;
                    return;
                }
                const node = {
                    nodeId: nodeId,
                    nodeKind: 'product_occurrence',
                    sourceOccurrenceId: occurrenceId,
                    nameSnapshot: String(placementRequest.nameSnapshot || occurrenceId),
                    itemIdSnapshot: placementRequest.itemIdSnapshot || null,
                    position: clone(candidate.position),
                    portOrientation: candidate.portOrientation,
                    portOrder: candidate.portOrder,
                };
                transient = clone(original);
                if (!Array.isArray(transient.canvasNodes)) transient.canvasNodes = [];
                transient.canvasNodes.push(node);
                const edgeId = String(
                    placementRequest.edgeId
                    || ('pm-e-suggest-' + String(suggestion.suggestionId || '').slice(4, 20))
                );
                const fromId = direction === 'incoming' ? nodeId : anchorId;
                const toId = direction === 'incoming' ? anchorId : nodeId;
                edge = {
                    edgeId: edgeId,
                    from: { nodeId: fromId, port: 'out' },
                    to: { nodeId: toId, port: 'in' },
                    kind: String(placementRequest.edgeKind || 'precedence'),
                    logicalConnectionId: edgeId,
                };
                placement = {
                    node: node,
                    candidateId: candidate.candidateId,
                    obstacleFingerprint: candidates.obstacleFingerprint,
                    metricsAfter: clone(candidate.metricsAfter || {}),
                };
                placed += 1;
            }

            if (!edge || typeof edge !== 'object') {
                result.push(suggestion);
                return;
            }
            const fromId = String(edge.from && edge.from.nodeId || '');
            const toId = String(edge.to && edge.to.nodeId || '');
            const transientIds = new Set((transient.canvasNodes || []).map(function (node) {
                return String(node && node.nodeId || '');
            }));
            if (!fromId || !toId || !transientIds.has(fromId) || !transientIds.has(toId)) {
                result.push(suggestion);
                unavailable += 1;
                return;
            }
            transient = appendSuggestionEdge(transient, edge);
            let route;
            try {
                const scene = compileSpatialScene(transient, { contract: contract });
                route = routeOrthogonalEdge(scene, String(edge.edgeId || ''), { contract: contract });
            } catch (_) {
                result.push(suggestion);
                unavailable += 1;
                return;
            }
            const proposal = spatialProposal(suggestion, edge, route, placement);
            suggestion.spatialProposal = proposal;
            if (proposal.accepted) routed += 1;
            else unavailable += 1;
            result.push(suggestion);
        });

        return {
            proposalVersion: SPATIAL_PROPOSAL_VERSION,
            suggestions: result,
            summary: {
                spatialized: routed,
                placementProposals: placed,
                unavailable: unavailable,
            },
        };
    }

    function applyOrthogonalRoute(processMap, edgeId, options) {
        const opts = options || {};
        const contract = spatialContractForProcessMap(processMap, opts.contract);
        const scene = compileSpatialScene(processMap, { contract: contract });
        const proposal = routeOrthogonalEdge(scene, edgeId, { contract: contract });
        const nextMap = clone(processMap);
        if (!proposal.accepted) return { map: nextMap, route: proposal, accepted: false };
        const edge = (nextMap.canvasEdges || []).find(function (item) { return item.edgeId === edgeId; });
        if (!edge) throw new Error("unknown edge '" + edgeId + "'");
        edge.routing = {
            mode: 'orthogonal_auto',
            routerVersion: ROUTER_VERSION,
            waypoints: clone(proposal.waypoints),
            obstacleFingerprint: proposal.obstacleFingerprint,
        };
        nextMap.layoutVersion = Math.max(3, Number.isInteger(nextMap.layoutVersion) ? nextMap.layoutVersion : 0);
        return { map: nextMap, route: proposal, accepted: true };
    }

    function refreshOrthogonalAutoRoutes(processMap, options) {
        const opts = options || {};
        const contract = spatialContractForProcessMap(processMap, opts.contract);
        let nextMap = clone(processMap);
        const failures = [];
        const edgeIds = (nextMap.canvasEdges || []).filter(function (edge) {
            return edge && edge.edgeId && edge.routing && edge.routing.mode === 'orthogonal_auto';
        }).map(function (edge) { return String(edge.edgeId); }).sort();
        const scene = compileSpatialScene(nextMap, { contract: contract });
        const proposals = new Map(edgeIds.map(function (edgeId) {
            return [edgeId, routeOrthogonalEdge(scene, edgeId, { contract: contract })];
        }));
        const edgeById = new Map((nextMap.canvasEdges || []).filter(function (edge) {
            return edge && edge.edgeId;
        }).map(function (edge) { return [String(edge.edgeId), edge]; }));
        edgeIds.forEach(function (edgeId) {
            const proposal = proposals.get(edgeId);
            if (!proposal.accepted) {
                failures.push({ edgeId: edgeId, failureReason: proposal.failureReason });
                return;
            }
            edgeById.get(edgeId).routing = {
                mode: 'orthogonal_auto',
                routerVersion: ROUTER_VERSION,
                waypoints: clone(proposal.waypoints),
                obstacleFingerprint: proposal.obstacleFingerprint,
            };
        });
        if (edgeIds.length) {
            nextMap.layoutVersion = Math.max(
                3,
                Number.isInteger(nextMap.layoutVersion) ? nextMap.layoutVersion : 0
            );
        }
        return { map: nextMap, failures: failures };
    }

    const FLOW_AXES = {
        left_to_right: [{ x: 1, y: 0 }, { x: 0, y: 1 }],
        right_to_left: [{ x: -1, y: 0 }, { x: 0, y: 1 }],
        top_to_bottom: [{ x: 0, y: 1 }, { x: 1, y: 0 }],
        bottom_to_top: [{ x: 0, y: -1 }, { x: 1, y: 0 }],
    };

    function flowAxes(direction) {
        return FLOW_AXES[direction] || FLOW_AXES.left_to_right;
    }

    function snap(value, grid) {
        // Matches the Python mirror's explicit round-half-away-from-zero;
        // see the comment on the Python _snap() for why native rounding
        // (Math.round vs Python round) cannot be relied on here.
        const scaled = value / grid;
        const magnitude = Math.floor(Math.abs(scaled) + 0.5);
        const snapped = scaled >= 0 ? magnitude : -magnitude;
        return rounded(snapped * grid);
    }

    // Ranking-key rounding, coarser than the reported-value rounding; see
    // the matching comment on the Python mirror's _rounded_coarse().
    function roundedCoarse(value) {
        const result = Number(Number(value).toFixed(3));
        return Object.is(result, -0) ? 0 : result;
    }

    function candidateId(prefix, lane, row, orientation, order) {
        return 'cand-' + prefix + '-L' + lane + '-R' + row + '-' + orientation[0] + '-' + order[0];
    }

    function ringOffsets(maxRing) {
        const seen = new Set();
        const ordered = [];
        for (let ring = 0; ring <= maxRing; ring += 1) {
            const candidates = [];
            for (let row = -ring; row <= ring; row += 1) {
                for (let lane = -ring; lane <= ring; lane += 1) {
                    if (Math.max(Math.abs(lane), Math.abs(row)) !== ring) continue;
                    candidates.push([lane, row]);
                }
            }
            candidates.sort(function (left, right) {
                return Math.abs(left[1]) - Math.abs(right[1])
                    || right[0] - left[0]
                    || left[0] - right[0]
                    || left[1] - right[1];
            });
            candidates.forEach(function (item) {
                const key = item[0] + ':' + item[1];
                if (seen.has(key)) return;
                seen.add(key);
                ordered.push(item);
            });
        }
        return ordered;
    }

    function leastDenseRegionPoint(scene, contract) {
        const worldBounds = scene.worldBounds || { x: 0, y: 0, width: 0, height: 0 };
        if (!(worldBounds.width > 0 && worldBounds.height > 0)) {
            return { x: 0, y: 0 };
        }
        const diagnosticsPolicy = contract.diagnostics;
        const columns = Math.max(1, Number(diagnosticsPolicy.regionColumns));
        const rows = Math.max(1, Number(diagnosticsPolicy.regionRows));
        const regionWidth = worldBounds.width / columns;
        const regionHeight = worldBounds.height / rows;
        const denseThreshold = Number(diagnosticsPolicy.denseOccupancyThreshold);
        const authoredNodes = (scene.nodes || []).filter(function (node) {
            return node.kind !== 'junction';
        });
        const ranked = [];
        for (let row = 0; row < rows; row += 1) {
            for (let column = 0; column < columns; column += 1) {
                const regionRect = {
                    x: worldBounds.x + column * regionWidth,
                    y: worldBounds.y + row * regionHeight,
                    width: regionWidth,
                    height: regionHeight,
                };
                let occupiedArea = 0;
                let intersectingCount = 0;
                authoredNodes.forEach(function (node) {
                    const overlap = rectIntersection(regionRect, node.rect);
                    if (!overlap) return;
                    intersectingCount += 1;
                    occupiedArea += overlap.width * overlap.height;
                });
                const area = Math.max(regionWidth * regionHeight, 1);
                const occupancy = rounded(Math.min(1, occupiedArea / area));
                const classificationRank = intersectingCount === 0
                    ? 0
                    : (occupancy >= denseThreshold || intersectingCount >= 3 ? 2 : 1);
                ranked.push([
                    classificationRank,
                    occupancy,
                    'region-r' + (row + 1) + '-c' + (column + 1),
                    {
                        x: regionRect.x + regionWidth / 2,
                        y: regionRect.y + regionHeight / 2,
                    },
                ]);
            }
        }
        ranked.sort(function (left, right) {
            return left[0] - right[0]
                || left[1] - right[1]
                || String(left[2]).localeCompare(String(right[2]));
        });
        return ranked[0][3];
    }

    function leastDenseVisibleRegionPoint(scene, visibleWorldRect, contract) {
        const visible = rect(visibleWorldRect, 'visibleWorldRect');
        const columns = Math.max(1, Number(contract.diagnostics.regionColumns));
        const rows = Math.max(1, Number(contract.diagnostics.regionRows));
        const cellWidth = visible.width / columns;
        const cellHeight = visible.height / rows;
        const authoredCenters = (scene.nodes || []).filter(function (node) {
            return node.kind !== 'junction';
        }).map(function (node) { return node.center; });
        const ranked = [];
        for (let row = 0; row < rows; row += 1) {
            for (let column = 0; column < columns; column += 1) {
                const left = visible.x + column * cellWidth;
                const top = visible.y + row * cellHeight;
                const right = left + cellWidth;
                const bottom = top + cellHeight;
                const occupancy = authoredCenters.filter(function (center) {
                    return center.x >= left && center.x <= right
                        && center.y >= top && center.y <= bottom;
                }).length;
                ranked.push([
                    occupancy,
                    row,
                    column,
                    { x: left + cellWidth / 2, y: top + cellHeight / 2 },
                ]);
            }
        }
        ranked.sort(function (left, right) {
            return left[0] - right[0] || left[1] - right[1] || left[2] - right[2];
        });
        return ranked[0][3];
    }

    function candidateCompiledNode(source, rectangle, orientation, order) {
        const compiled = clone(source);
        const candidateRect = Object.assign({}, rectangle);
        const center = {
            x: candidateRect.x + candidateRect.width / 2,
            y: candidateRect.y + candidateRect.height / 2,
        };
        const inputAnchor = portAnchor(candidateRect, orientation, order, 'in');
        const outputAnchor = portAnchor(candidateRect, orientation, order, 'out');
        Object.assign(compiled, {
            rect: candidateRect,
            center: center,
            portOrientation: orientation,
            portOrder: order,
            ports: {
                input: Object.assign({}, inputAnchor, {
                    direction: portDirection(orientation, order, 'in'),
                }),
                output: Object.assign({}, outputAnchor, {
                    direction: portDirection(orientation, order, 'out'),
                }),
            },
        });
        return compiled;
    }

    function edgeWithCandidateEndpoints(edge, nodeById) {
        const source = nodeById.get(String(edge.fromNodeId || ''));
        const target = nodeById.get(String(edge.toNodeId || ''));
        const start = Object.assign({}, source.ports.output);
        const end = Object.assign({}, target.ports.input);
        delete start.direction;
        delete end.direction;
        const updated = clone(edge);
        const existing = (edge.points || []).map(function (point) { return Object.assign({}, point); });
        updated.points = existing.length >= 2
            ? [start].concat(existing.slice(1, -1), [end])
            : [start, end];
        return updated;
    }

    function generatePlacementCandidates(scene, options) {
        if (!scene || typeof scene !== 'object' || scene.spatialVersion !== SPATIAL_VERSION) {
            throw new Error('scene has an unsupported spatial version');
        }
        const opts = options || {};
        const contract = spatialContractForScene(scene, opts.contract);
        const geometry = contract.geometry;
        const policy = contract.layoutPolicyDefaults;
        const limits = contract.limits;
        const envelopes = geometry.nodeEnvelopes;

        const targetKind = String(opts.targetKind || '');
        const targetNodeId = opts.targetNodeId || null;
        const anchorNodeId = opts.anchorNodeId || null;
        const connectionDirection = opts.connectionDirection || null;
        const requiredGroupId = opts.requiredGroupId || null;
        const preferredFlowDirection = opts.preferredFlowDirection || 'left_to_right';
        const visibleWorldRect = opts.visibleWorldRect || null;
        const limit = Math.max(1, Math.min(Number(opts.limit) || 3, 3));

        const nodes = scene.nodes || [];
        const nodeById = new Map(nodes.map(function (node) { return [String(node.nodeId || ''), node]; }));
        const authoredById = new Map();
        nodeById.forEach(function (node, id) {
            if (node.kind !== 'junction') authoredById.set(id, node);
        });
        const groups = new Map((scene.groups || []).map(function (group) {
            return [String(group.groupId || ''), group];
        }));
        const edges = scene.edges || [];

        const maxEvaluated = Math.min(Number(limits.maximumCandidates), 96);
        const fingerprint = obstacleFingerprint(scene);
        const rejectionCounts = {};
        function reject(code) { rejectionCounts[code] = (rejectionCounts[code] || 0) + 1; }

        const resultBase = {
            spatialEngineVersion: SPATIAL_VERSION,
            candidatePolicyVersion: CANDIDATE_POLICY_VERSION,
            identity: clone(scene.identity || {}),
            obstacleFingerprint: fingerprint,
            target: { kind: targetKind, nodeId: targetNodeId },
            anchorNodeId: anchorNodeId,
            requiredGroupId: requiredGroupId,
        };

        if (!envelopes[targetKind] && targetKind !== 'default') {
            return Object.assign({}, resultBase, {
                candidates: [], evaluatedCount: 0, rejectionCounts: { invalid_geometry: 1 },
            });
        }

        let movingNode = null;
        if (targetNodeId != null) {
            movingNode = nodeById.get(targetNodeId) || null;
            if (!movingNode || movingNode.kind === 'junction') {
                return Object.assign({}, resultBase, {
                    candidates: [], evaluatedCount: 0, rejectionCounts: { invalid_topology: 1 },
                });
            }
            if (movingNode.positionMode === 'locked' || movingNode.locked === true) {
                return Object.assign({}, resultBase, {
                    candidates: [], evaluatedCount: 0, rejectionCounts: { locked_node_movement: 1 },
                });
            }
        }

        const anchor = anchorNodeId ? nodeById.get(anchorNodeId) || null : null;
        if (anchorNodeId && !anchor) {
            return Object.assign({}, resultBase, {
                candidates: [], evaluatedCount: 0, rejectionCounts: { invalid_topology: 1 },
            });
        }
        if (anchor && targetNodeId != null && anchorNodeId === targetNodeId) {
            return Object.assign({}, resultBase, {
                candidates: [], evaluatedCount: 0, rejectionCounts: { invalid_topology: 1 },
            });
        }
        if (requiredGroupId != null && !groups.has(requiredGroupId)) {
            return Object.assign({}, resultBase, {
                candidates: [], evaluatedCount: 0, rejectionCounts: { group_containment_violation: 1 },
            });
        }

        const envelope = envelopes[targetKind] || envelopes.default;
        const width = Number(envelope.width);
        const height = Number(envelope.height);
        if (!positiveNumber(width) || !positiveNumber(height)) {
            return Object.assign({}, resultBase, {
                candidates: [], evaluatedCount: 0, rejectionCounts: { invalid_geometry: 1 },
            });
        }

        const nodeClearance = Number(policy.nodeClearance);
        const gridSize = Number(policy.gridSize);
        const rectFn = rect;
        const axes = flowAxes(preferredFlowDirection);
        const forward = axes[0];
        const perpendicular = axes[1];
        const horizontalFlow = Math.abs(forward.x) === 1;
        const laneStep = (horizontalFlow ? width : height) + nodeClearance;
        const rowStep = (horizontalFlow ? height : width) + nodeClearance;

        let origin;
        let originKind;
        if (anchor) {
            origin = anchor.center;
            originKind = 'anchor';
        } else {
            origin = visibleWorldRect
                ? leastDenseVisibleRegionPoint(scene, visibleWorldRect, contract)
                : leastDenseRegionPoint(scene, contract);
            originKind = 'region';
        }

        const broadPhaseSize = Math.max(gridSize * 8, width, height);
        const obstacleIndex = new SpatialGridIndex(broadPhaseSize);
        authoredById.forEach(function (node, id) {
            if (targetNodeId != null && id === targetNodeId) return;
            obstacleIndex.insert(id, node.rect);
        });

        const headerRects = [];
        groups.forEach(function (group, groupId) {
            headerRects.push([groupId, group.headerRect]);
        });
        const edgeIndex = new SpatialGridIndex(broadPhaseSize);
        const samplingSegments = geometry.legacyBezierSamplingSegments;
        const sampledEdges = [];
        edges.forEach(function (edge) {
            if (targetNodeId != null && (edge.fromNodeId === targetNodeId || edge.toNodeId === targetNodeId)) return;
            const points = edgePathPoints(edge, nodeById, samplingSegments);
            const bounds = pointBounds(points);
            const edgeId = String(edge.edgeId || '');
            sampledEdges.push({ edge: edge, edgeId: edgeId, points: points, bounds: bounds });
            edgeIndex.insert(edgeId, bounds);
        });
        const sampledByEdgeId = new Map();
        sampledEdges.forEach(function (item) {
            sampledByEdgeId.set(item.edgeId, item);
        });

        const precedenceAdjacency = new Map();
        edges.forEach(function (edge) {
            if (edge.kind !== 'precedence') return;
            const fromId = String(edge.fromNodeId || '');
            if (!precedenceAdjacency.has(fromId)) precedenceAdjacency.set(fromId, new Set());
            precedenceAdjacency.get(fromId).add(String(edge.toNodeId || ''));
        });

        function wouldCreateCycle(fromId, toId) {
            if (fromId === toId) return true;
            const stack = [toId];
            const seen = new Set();
            while (stack.length) {
                const current = stack.pop();
                if (current === fromId) return true;
                if (seen.has(current)) continue;
                seen.add(current);
                (precedenceAdjacency.get(current) || new Set()).forEach(function (next) {
                    stack.push(next);
                });
            }
            return false;
        }

        const existingPrecedencePairs = new Set(
            edges.filter(function (edge) { return edge.kind === 'precedence'; })
                .map(function (edge) { return edge.fromNodeId + '->' + edge.toNodeId; })
        );

        const orientationOrders = [
            ['horizontal', 'input_first'],
            ['horizontal', 'output_first'],
            ['vertical', 'input_first'],
            ['vertical', 'output_first'],
        ];

        let evaluated = 0;
        const scored = [];
        const offsets = ringOffsets(4);
        for (let offsetIndex = 0; offsetIndex < offsets.length && evaluated < maxEvaluated; offsetIndex += 1) {
            const lane = offsets[offsetIndex][0];
            const row = offsets[offsetIndex][1];
            const center = {
                x: origin.x + lane * laneStep * forward.x + row * rowStep * perpendicular.x,
                y: origin.y + lane * laneStep * forward.y + row * rowStep * perpendicular.y,
            };
            for (let comboIndex = 0; comboIndex < orientationOrders.length && evaluated < maxEvaluated; comboIndex += 1) {
                const orientation = orientationOrders[comboIndex][0];
                const order = orientationOrders[comboIndex][1];
                evaluated += 1;
                const rect = {
                    x: snap(center.x - width / 2, gridSize),
                    y: snap(center.y - height / 2, gridSize),
                    width: width,
                    height: height,
                };
                if (!finiteNumber(rect.x) || !finiteNumber(rect.y)) {
                    reject('invalid_geometry');
                    continue;
                }

                let overlapFound = false;
                let clearanceOk = true;
                let minimumClearance = null;
                const nearby = obstacleIndex.query(expandedRect(rect, nodeClearance));
                for (let index = 0; index < nearby.length; index += 1) {
                    const other = authoredById.get(nearby[index]);
                    if (rectIntersection(rect, other.rect)) { overlapFound = true; break; }
                    const distance = rectDistance(rect, other.rect);
                    minimumClearance = minimumClearance == null ? distance : Math.min(minimumClearance, distance);
                    if (distance < nodeClearance) clearanceOk = false;
                }
                if (overlapFound) { reject('node_overlap'); continue; }
                if (!clearanceOk) { reject('insufficient_node_clearance'); continue; }

                if (requiredGroupId != null) {
                    const groupRect = groups.get(requiredGroupId).rect;
                    const contained = rect.x >= groupRect.x && rect.y >= groupRect.y
                        && rect.x + rect.width <= groupRect.x + groupRect.width
                        && rect.y + rect.height <= groupRect.y + groupRect.height;
                    if (!contained) { reject('group_containment_violation'); continue; }
                }

                let headerHit = false;
                for (let index = 0; index < headerRects.length; index += 1) {
                    if (rectIntersection(rect, headerRects[index][1])) { headerHit = true; break; }
                }
                if (headerHit) { reject('group_header_intersection'); continue; }

                const inputAnchor = portAnchor(rect, orientation, order, 'in');
                const outputAnchor = portAnchor(rect, orientation, order, 'out');

                const candidateIncidentRoutes = [];
                let incidentBlocked = false;
                if (movingNode) {
                    const candidateNodes = new Map(nodeById);
                    candidateNodes.set(
                        targetNodeId,
                        candidateCompiledNode(movingNode, rect, orientation, order)
                    );
                    for (let edgeIndexValue = 0; edgeIndexValue < edges.length; edgeIndexValue += 1) {
                        const edge = edges[edgeIndexValue];
                        if (edge.fromNodeId !== targetNodeId && edge.toNodeId !== targetNodeId) continue;
                        const candidateEdge = edgeWithCandidateEndpoints(edge, candidateNodes);
                        const points = edgePathPoints(candidateEdge, candidateNodes, samplingSegments);
                        const bounds = pointBounds(points);
                        const endpointIds = new Set([
                            String(edge.fromNodeId || ''),
                            String(edge.toNodeId || ''),
                        ]);
                        const nearbyForIncident = obstacleIndex.query(bounds);
                        for (let index = 0; index < nearbyForIncident.length; index += 1) {
                            const otherId = nearbyForIncident[index];
                            if (endpointIds.has(otherId)) continue;
                            if (polylineIntersectsRect(points, authoredById.get(otherId).rect)) {
                                incidentBlocked = true;
                                break;
                            }
                        }
                        if (incidentBlocked) break;
                        candidateIncidentRoutes.push({
                            points: points,
                            bounds: bounds,
                            endpointIds: endpointIds,
                        });
                    }
                }
                if (incidentBlocked) { reject('edge_node_intersection'); continue; }

                let requestedEdgePoints = null;
                let requestedBounds = null;
                let requestedFromId = null;
                let requestedToId = null;
                if (anchor && (connectionDirection === 'outgoing' || connectionDirection === 'incoming')) {
                    let fromId, toId, start, startDirection, end, endDirection;
                    if (connectionDirection === 'outgoing') {
                        fromId = anchorNodeId;
                        toId = targetNodeId || '__candidate__';
                        start = Object.assign({}, anchor.ports.output);
                        startDirection = start.direction;
                        delete start.direction;
                        end = Object.assign({}, inputAnchor);
                        endDirection = portDirection(orientation, order, 'in');
                    } else {
                        fromId = targetNodeId || '__candidate__';
                        toId = anchorNodeId;
                        start = Object.assign({}, outputAnchor);
                        startDirection = portDirection(orientation, order, 'out');
                        end = Object.assign({}, anchor.ports.input);
                        endDirection = end.direction;
                        delete end.direction;
                    }
                    if (fromId === toId) { reject('invalid_topology'); continue; }
                    if (existingPrecedencePairs.has(fromId + '->' + toId)) { reject('duplicate_connection'); continue; }
                    if (wouldCreateCycle(fromId, toId)) { reject('precedence_cycle'); continue; }
                    requestedFromId = fromId;
                    requestedToId = toId;

                    const controls = legacyBezierControls(start, end, startDirection, endDirection);
                    requestedEdgePoints = sampleCubicBezier(start, controls[0], controls[1], end, samplingSegments);
                    requestedBounds = pointBounds(requestedEdgePoints);
                    let blocked = false;
                    const nearbyForEdge = obstacleIndex.query(requestedBounds);
                    for (let index = 0; index < nearbyForEdge.length; index += 1) {
                        if (nearbyForEdge[index] === anchorNodeId) continue;
                        const other = authoredById.get(nearbyForEdge[index]);
                        if (polylineIntersectsRect(requestedEdgePoints, other.rect)) { blocked = true; break; }
                    }
                    if (blocked) { reject('edge_node_intersection'); continue; }
                }

                let unrelatedEdgeIntersections = 0;
                let wireCrossings = 0;
                const probeRoutes = candidateIncidentRoutes.slice();
                if (requestedEdgePoints) {
                    probeRoutes.push({
                        points: requestedEdgePoints,
                        bounds: requestedBounds,
                        endpointIds: new Set([String(requestedFromId), String(requestedToId)]),
                    });
                }
                // Broad-phase prune via edgeIndex before the exact polyline
                // checks: an edge whose overall bounds do not overlap the
                // query rect/bounds cannot possibly intersect or cross it,
                // so this cannot change the result, only how many pairs get
                // the exact check.
                edgeIndex.query(rect).forEach(function (edgeId) {
                    const sampled = sampledByEdgeId.get(edgeId);
                    if (polylineIntersectsRect(sampled.points, rect)) unrelatedEdgeIntersections += 1;
                });
                probeRoutes.forEach(function (probe) {
                    edgeIndex.query(probe.bounds).forEach(function (edgeId) {
                        const sampled = sampledByEdgeId.get(edgeId);
                        const sampledEndpoints = new Set([
                            String(sampled.edge.fromNodeId || ''),
                            String(sampled.edge.toNodeId || ''),
                        ]);
                        const sharesEndpoint = Array.from(probe.endpointIds).some(function (nodeId) {
                            return sampledEndpoints.has(nodeId);
                        });
                        if (sharesEndpoint) return;
                        if (polylineCrossing(probe.points, sampled.points)) {
                            wireCrossings += 1;
                        }
                    });
                });

                let forwardViolation = 0;
                if (anchor) {
                    const delta = (center.x - anchor.center.x) * forward.x + (center.y - anchor.center.y) * forward.y;
                    const isOutgoing = connectionDirection !== 'incoming';
                    if (isOutgoing && delta < -(gridSize / 2)) forwardViolation = 1;
                    else if (!isOutgoing && delta > gridSize / 2) forwardViolation = 1;
                }

                const routeLength = probeRoutes.reduce(function (total, probe) {
                    return total + polylineLength(probe.points);
                }, 0);
                const clearanceValue = minimumClearance == null ? nodeClearance * 4 : minimumClearance;
                const remainderX = Math.abs(rect.x) % gridSize;
                const remainderY = Math.abs(rect.y) % gridSize;
                const alignmentDeviation = (
                    Math.min(remainderX, gridSize - remainderX) + Math.min(remainderY, gridSize - remainderY)
                ) / 2;
                let anchorDistance = 0;
                if (anchor) {
                    const anchorDx = center.x - anchor.center.x;
                    const anchorDy = center.y - anchor.center.y;
                    // Explicit sqrt(dx*dx+dy*dy) rather than Math.hypot():
                    // see the matching comment on the Python mirror.
                    anchorDistance = Math.sqrt(anchorDx * anchorDx + anchorDy * anchorDy);
                }
                let movementDistance = 0;
                if (movingNode) {
                    const movementDx = rect.x - movingNode.rect.x;
                    const movementDy = rect.y - movingNode.rect.y;
                    movementDistance = Math.sqrt(
                        movementDx * movementDx + movementDy * movementDy
                    );
                }
                let regionViolation = 0;
                if (visibleWorldRect) {
                    const visible = rectFn(visibleWorldRect, 'visibleWorldRect');
                    const inside = rect.x >= visible.x && rect.y >= visible.y
                        && rect.x + rect.width <= visible.x + visible.width
                        && rect.y + rect.height <= visible.y + visible.height;
                    if (!inside) regionViolation = 1;
                }

                const id = candidateId(originKind, lane, row, orientation, order);
                const scoreKey = [
                    unrelatedEdgeIntersections,
                    wireCrossings,
                    forwardViolation,
                    roundedCoarse(routeLength),
                    roundedCoarse(-clearanceValue),
                    roundedCoarse(alignmentDeviation),
                    roundedCoarse(anchorDistance),
                    roundedCoarse(movementDistance),
                    regionViolation,
                    id,
                    snap(rect.y, gridSize),
                    snap(rect.x, gridSize),
                ];
                scored.push([scoreKey, {
                    candidateId: id,
                    position: { x: rect.x, y: rect.y },
                    portOrientation: orientation,
                    portOrder: order,
                    score: {
                        edgeCrossings: wireCrossings,
                        backwardEdges: forwardViolation,
                        routeBends: 0,
                        routeLength: roundedCoarse(routeLength),
                        minimumClearance: roundedCoarse(clearanceValue),
                        alignmentDeviation: rounded(alignmentDeviation),
                        existingNodeMovement: roundedCoarse(movementDistance),
                        anchorProximity: rounded(anchorDistance),
                        regionPreference: regionViolation === 0 ? 0 : 1,
                        edgeCardIntersections: unrelatedEdgeIntersections,
                    },
                    metricsAfter: {
                        nodeOverlaps: 0,
                        edgeCardIntersections: unrelatedEdgeIntersections,
                        edgeCrossings: wireCrossings,
                        minimumClearance: roundedCoarse(clearanceValue),
                    },
                }]);
            }
        }

        scored.sort(function (left, right) {
            const a = left[0];
            const b = right[0];
            for (let index = 0; index < a.length; index += 1) {
                if (a[index] < b[index]) return -1;
                if (a[index] > b[index]) return 1;
            }
            return 0;
        });
        const ranked = scored.slice(0, limit).map(function (item) { return item[1]; });
        return Object.assign({}, resultBase, {
            evaluatedCount: evaluated,
            rejectionCounts: rejectionCounts,
            candidates: ranked,
        });
    }

    function arrangementRanks(scene) {
        const nodeIds = (scene.nodes || []).filter(function (node) {
            return node && node.nodeId;
        }).map(function (node) { return String(node.nodeId); }).sort();
        const incoming = new Map(nodeIds.map(function (nodeId) { return [nodeId, 0]; }));
        const adjacency = new Map(nodeIds.map(function (nodeId) { return [nodeId, []]; }));
        sortedValues(scene.edges || [], 'edgeId').forEach(function (edge) {
            if (edge.kind !== 'precedence') return;
            const source = String(edge.fromNodeId || '');
            const target = String(edge.toNodeId || '');
            if (!incoming.has(source) || !incoming.has(target) || source === target) return;
            adjacency.get(source).push(target);
            incoming.set(target, incoming.get(target) + 1);
        });
        adjacency.forEach(function (targets) { targets.sort(); });
        const queue = nodeIds.filter(function (nodeId) { return incoming.get(nodeId) === 0; });
        const ranks = new Map(queue.map(function (nodeId) { return [nodeId, 0]; }));
        while (queue.length) {
            const nodeId = queue.shift();
            const nextRank = (ranks.get(nodeId) || 0) + 1;
            adjacency.get(nodeId).forEach(function (target) {
                ranks.set(target, Math.max(ranks.get(target) || 0, nextRank));
                incoming.set(target, incoming.get(target) - 1);
                if (incoming.get(target) === 0) {
                    queue.push(target);
                    queue.sort();
                }
            });
        }
        nodeIds.forEach(function (nodeId) {
            if (!ranks.has(nodeId)) ranks.set(nodeId, 0);
        });
        return ranks;
    }

    function arrangementMetrics(diagnostics) {
        const metrics = diagnostics.metrics || {};
        const hardIds = (diagnostics.problems || []).filter(function (problem) {
            return ARRANGEMENT_HARD_PROBLEM_CODES.has(problem.code);
        }).map(function (problem) { return String(problem.problemId || ''); }).sort();
        return {
            hardViolationCount: hardIds.length,
            hardViolationIds: hardIds,
            nodeOverlaps: Number(metrics.nodeOverlaps || 0),
            nodeClearanceViolations: Number(metrics.nodeClearanceViolations || 0),
            nodeGroupHeaderIntersections: Number(metrics.nodeGroupHeaderIntersections || 0),
            edgeNodeIntersections: Number(metrics.edgeNodeIntersections || 0),
            edgeGroupHeaderIntersections: Number(metrics.edgeGroupHeaderIntersections || 0),
            edgeCrossings: Number(metrics.edgeCrossings || 0),
            backwardEdges: Number(metrics.backwardEdges || 0),
            routeBends: Number(metrics.routeBends || 0),
            routeLength: roundedCoarse(Number(metrics.routeLength || 0)),
            alignmentDeviation: roundedCoarse(Number(metrics.alignmentDeviation || 0)),
        };
    }

    function arrangementQuality(metrics) {
        return [
            Number(metrics.hardViolationCount || 0),
            Number(metrics.edgeCrossings || 0),
            Number(metrics.backwardEdges || 0),
            Number(metrics.routeBends || 0),
            Number(metrics.routeLength || 0),
            Number(metrics.alignmentDeviation || 0),
        ];
    }

    function compareTuples(left, right) {
        const length = Math.max(left.length, right.length);
        for (let index = 0; index < length; index += 1) {
            if (left[index] < right[index]) return -1;
            if (left[index] > right[index]) return 1;
        }
        return 0;
    }

    function arrangementPortLayout(flowDirection) {
        if (flowDirection === 'right_to_left') return ['horizontal', 'output_first'];
        if (flowDirection === 'top_to_bottom') return ['vertical', 'input_first'];
        if (flowDirection === 'bottom_to_top') return ['vertical', 'output_first'];
        return ['horizontal', 'input_first'];
    }

    function rectInside(inner, outer) {
        return inner.x >= outer.x && inner.y >= outer.y
            && inner.x + inner.width <= outer.x + outer.width
            && inner.y + inner.height <= outer.y + outer.height;
    }

    function arrangementPosition(node, rectangle) {
        if (node.kind === 'junction') {
            return {
                x: rounded(rectangle.x + rectangle.width / 2),
                y: rounded(rectangle.y + rectangle.height / 2),
            };
        }
        return { x: rounded(rectangle.x), y: rounded(rectangle.y) };
    }

    function arrangementPlanBase(scene, scopeKind, scopeNodeIds, groupId, pinnedNodeIds, pinnedGroupIds) {
        return {
            spatialEngineVersion: SPATIAL_VERSION,
            arrangementPolicyVersion: ARRANGEMENT_POLICY_VERSION,
            identity: clone(scene.identity || {}),
            obstacleFingerprint: obstacleFingerprint(scene),
            scope: {
                kind: scopeKind,
                nodeIds: Array.from(new Set(scopeNodeIds)).sort(),
                groupId: groupId || null,
            },
            pinnedNodeIds: Array.from(new Set(pinnedNodeIds)).sort(),
            pinnedGroupIds: Array.from(new Set(pinnedGroupIds)).sort(),
        };
    }

    function generateArrangementPlan(processMap, options) {
        const opts = options || {};
        const scope = opts.scope || 'full_map';
        if (['selection', 'group', 'full_map'].indexOf(scope) < 0) {
            throw new Error('unsupported arrangement scope');
        }
        const contract = spatialContractForProcessMap(processMap, opts.contract);
        const scene = compileSpatialScene(processMap, {
            contract: contract,
            revision: opts.revision == null ? undefined : opts.revision,
        });
        const nodeById = new Map((scene.nodes || []).map(function (node) {
            return [String(node.nodeId || ''), node];
        }));
        const groupById = new Map((scene.groups || []).map(function (group) {
            return [String(group.groupId || ''), group];
        }));
        const allGroupIds = Array.from(groupById.keys()).sort();
        const explicitPinned = new Set((opts.pinnedNodeIds || []).map(String).filter(function (nodeId) {
            return nodeById.has(nodeId);
        }));
        const requestedPinnedGroups = new Set((opts.pinnedGroupIds || []).map(String).filter(function (value) {
            return groupById.has(value);
        }));
        let scopedIds;
        if (scope === 'selection') {
            scopedIds = new Set((opts.nodeIds || []).map(String).filter(function (nodeId) {
                return nodeById.has(nodeId);
            }));
        } else if (scope === 'group') {
            if (!opts.groupId || !groupById.has(opts.groupId)) {
                throw new Error('group arrangement requires a known groupId');
            }
            scopedIds = new Set(groupById.get(opts.groupId).memberNodeIds || []);
        } else {
            scopedIds = new Set(nodeById.keys());
        }
        const pinned = new Set(explicitPinned);
        scopedIds.forEach(function (nodeId) {
            const node = nodeById.get(nodeId);
            if (node.positionMode === 'locked' || node.locked === true
                || (opts.preserveManual !== false && node.positionMode === 'manual')) {
                pinned.add(nodeId);
            }
        });
        const movableIds = new Set(Array.from(scopedIds).filter(function (nodeId) {
            return !pinned.has(nodeId);
        }));
        const base = arrangementPlanBase(
            scene,
            scope,
            Array.from(scopedIds),
            opts.groupId || null,
            Array.from(pinned),
            allGroupIds.concat(Array.from(requestedPinnedGroups))
        );
        if (!movableIds.size) {
            return Object.assign({}, base, {
                accepted: false, failureReason: 'no_movable_nodes', planId: null, moves: [],
            });
        }

        const policy = contract.layoutPolicyDefaults;
        let flowDirection = String(policy.flowDirection || 'left_to_right');
        if (!FLOW_AXES[flowDirection]) flowDirection = 'left_to_right';
        const grid = Number(policy.gridSize);
        const clearance = Number(policy.nodeClearance);
        const edgeClearance = Number(policy.edgeClearance);
        const horizontal = flowDirection === 'left_to_right' || flowDirection === 'right_to_left';
        const portLayout = arrangementPortLayout(flowDirection);
        const orientation = portLayout[0];
        const order = portLayout[1];
        const ranks = arrangementRanks(scene);
        const partitions = new Map();
        Array.from(movableIds).sort().forEach(function (nodeId) {
            const node = nodeById.get(nodeId);
            const key = String(node.groupId || '');
            if (!partitions.has(key)) partitions.set(key, []);
            partitions.get(key).push(node);
        });
        const placed = new Map();
        nodeById.forEach(function (node, nodeId) {
            if (movableIds.has(nodeId)) return;
            placed.set(nodeId, { rect: clone(node.rect), junction: node.kind === 'junction' });
        });
        const proposedRects = new Map();

        function candidateAllowed(nodeId, candidate, partitionGroupId) {
            const ownGroup = groupById.get(partitionGroupId);
            if (ownGroup) {
                if (!rectInside(candidate, ownGroup.rect)) return false;
            } else {
                const groupValues = Array.from(groupById.values());
                for (let index = 0; index < groupValues.length; index += 1) {
                    if (rectIntersection(candidate, groupValues[index].rect)) return false;
                }
            }
            const groupValues = Array.from(groupById.values());
            for (let index = 0; index < groupValues.length; index += 1) {
                if (rectIntersection(candidate, groupValues[index].headerRect)) return false;
            }
            const obstacleValues = Array.from(placed.entries());
            for (let index = 0; index < obstacleValues.length; index += 1) {
                const otherId = obstacleValues[index][0];
                const obstacle = obstacleValues[index][1];
                if (otherId === nodeId) continue;
                if (rectIntersection(candidate, obstacle.rect)) return false;
                const minimum = obstacle.junction ? edgeClearance : clearance;
                if (rectDistance(candidate, obstacle.rect) < minimum) return false;
            }
            return true;
        }

        const partitionKeys = Array.from(partitions.keys()).sort(function (left, right) {
            if ((left === '') !== (right === '')) return left === '' ? 1 : -1;
            return left.localeCompare(right);
        });
        for (let partitionIndex = 0; partitionIndex < partitionKeys.length; partitionIndex += 1) {
            const partitionKey = partitionKeys[partitionIndex];
            const partitionNodes = partitions.get(partitionKey);
            const rankValues = Array.from(new Set(partitionNodes.map(function (node) {
                return ranks.get(String(node.nodeId)) || 0;
            }))).sort(function (left, right) { return left - right; });
            const compactRank = new Map(rankValues.map(function (value, index) { return [value, index]; }));
            const columns = new Map();
            partitionNodes.forEach(function (node) {
                const rank = compactRank.get(ranks.get(String(node.nodeId)) || 0);
                if (!columns.has(rank)) columns.set(rank, []);
                columns.get(rank).push(node);
            });
            columns.forEach(function (values) {
                values.sort(function (left, right) {
                    const leftValue = horizontal ? left.center.y : left.center.x;
                    const rightValue = horizontal ? right.center.y : right.center.x;
                    return leftValue - rightValue || String(left.nodeId).localeCompare(String(right.nodeId));
                });
            });
            const maximumWidth = Math.max.apply(null, partitionNodes.map(function (node) {
                return Number(node.rect.width);
            }));
            const maximumHeight = Math.max.apply(null, partitionNodes.map(function (node) {
                return Number(node.rect.height);
            }));
            const rankCount = Math.max(1, rankValues.length);
            const laneCount = Math.max.apply(null, Array.from(columns.values()).map(function (values) {
                return values.length;
            }));
            const layoutWidth = horizontal
                ? rankCount * maximumWidth + (rankCount - 1) * clearance
                : laneCount * maximumWidth + (laneCount - 1) * clearance;
            const layoutHeight = horizontal
                ? laneCount * maximumHeight + (laneCount - 1) * clearance
                : rankCount * maximumHeight + (rankCount - 1) * clearance;
            const currentBounds = rectangleBounds(partitionNodes.map(function (node) { return node.rect; }));
            const targetGroup = groupById.get(partitionKey);
            let originX;
            let originY;
            if (targetGroup) {
                const available = targetGroup.rect;
                const padding = grid;
                if (layoutWidth > available.width - 2 * padding
                    || layoutHeight > available.height - 2 * padding) {
                    return Object.assign({}, base, {
                        accepted: false, failureReason: 'group_capacity_exceeded', planId: null, moves: [],
                    });
                }
                originX = available.x + (available.width - layoutWidth) / 2;
                originY = available.y + (available.height - layoutHeight) / 2;
            } else {
                originX = currentBounds.x + (currentBounds.width - layoutWidth) / 2;
                originY = currentBounds.y + (currentBounds.height - layoutHeight) / 2;
            }
            const columnKeys = Array.from(columns.keys()).sort(function (left, right) { return left - right; });
            for (let columnIndex = 0; columnIndex < columnKeys.length; columnIndex += 1) {
                const rankIndex = columnKeys[columnIndex];
                const values = columns.get(rankIndex);
                const laneOffset = (laneCount - values.length) / 2;
                let displayRank = rankIndex;
                if (flowDirection === 'right_to_left' || flowDirection === 'bottom_to_top') {
                    displayRank = rankCount - rankIndex - 1;
                }
                for (let laneIndex = 0; laneIndex < values.length; laneIndex += 1) {
                    const node = values[laneIndex];
                    let slotX;
                    let slotY;
                    if (horizontal) {
                        slotX = originX + displayRank * (maximumWidth + clearance);
                        slotY = originY + (laneIndex + laneOffset) * (maximumHeight + clearance);
                    } else {
                        slotX = originX + (laneIndex + laneOffset) * (maximumWidth + clearance);
                        slotY = originY + displayRank * (maximumHeight + clearance);
                    }
                    const baseRect = {
                        x: snap(slotX + (maximumWidth - node.rect.width) / 2, grid),
                        y: snap(slotY + (maximumHeight - node.rect.height) / 2, grid),
                        width: Number(node.rect.width),
                        height: Number(node.rect.height),
                    };
                    let selectedCandidate = null;
                    let selectedKey = null;
                    let selectedRing = null;
                    const offsets = ringOffsets(12);
                    for (let offsetIndex = 0; offsetIndex < offsets.length; offsetIndex += 1) {
                        const laneDelta = offsets[offsetIndex][0];
                        const rowDelta = offsets[offsetIndex][1];
                        const ring = Math.max(Math.abs(laneDelta), Math.abs(rowDelta));
                        if (selectedRing != null && ring > selectedRing) break;
                        const candidate = Object.assign({}, baseRect, {
                            x: rounded(baseRect.x + laneDelta * grid),
                            y: rounded(baseRect.y + rowDelta * grid),
                        });
                        if (!candidateAllowed(String(node.nodeId), candidate, partitionKey)) continue;
                        const dx = candidate.x - node.rect.x;
                        const dy = candidate.y - node.rect.y;
                        const key = [dx * dx + dy * dy, candidate.y, candidate.x];
                        if (!selectedKey || compareTuples(key, selectedKey) < 0) {
                            selectedCandidate = candidate;
                            selectedKey = key;
                            selectedRing = ring;
                        }
                    }
                    if (!selectedCandidate) {
                        return Object.assign({}, base, {
                            accepted: false,
                            failureReason: 'no_collision_free_arrangement',
                            planId: null,
                            moves: [],
                        });
                    }
                    const nodeId = String(node.nodeId);
                    proposedRects.set(nodeId, selectedCandidate);
                placed.set(nodeId, {
                    rect: selectedCandidate,
                    junction: node.kind === 'junction',
                });
                }
            }
        }

        let nextMap = clone(processMap);
        const rawNodeById = new Map((nextMap.canvasNodes || []).filter(function (node) {
            return node && node.nodeId;
        }).map(function (node) { return [String(node.nodeId), node]; }));
        const moves = [];
        let movementDistance = 0;
        Array.from(proposedRects.keys()).sort().forEach(function (nodeId) {
            const compiled = nodeById.get(nodeId);
            const raw = rawNodeById.get(nodeId);
            const position = arrangementPosition(compiled, proposedRects.get(nodeId));
            const beforePosition = clone(raw.position || {});
            const beforeOrientation = String(raw.portOrientation || 'horizontal');
            const beforeOrder = String(raw.portOrder || 'input_first');
            raw.position = position;
            if (raw.nodeKind !== 'junction') {
                raw.portOrientation = orientation;
                raw.portOrder = order;
            }
            const dx = Number(position.x) - Number(beforePosition.x || 0);
            const dy = Number(position.y) - Number(beforePosition.y || 0);
            movementDistance += Math.sqrt(dx * dx + dy * dy);
            if (canonicalBytes(position) !== canonicalBytes(beforePosition)
                || orientation !== beforeOrientation || order !== beforeOrder) {
                moves.push({
                    nodeId: nodeId,
                    from: {
                        position: beforePosition,
                        portOrientation: beforeOrientation,
                        portOrder: beforeOrder,
                    },
                    to: {
                        position: position,
                        portOrientation: orientation,
                        portOrder: order,
                    },
                });
            }
        });
        if (!moves.length) {
            return Object.assign({}, base, {
                accepted: false, failureReason: 'layout_already_clean', planId: null, moves: [],
            });
        }
        const refreshed = refreshOrthogonalAutoRoutes(nextMap, { contract: contract });
        if (refreshed.failures.length) {
            return Object.assign({}, base, {
                accepted: false,
                failureReason: 'automatic_route_update_failed',
                planId: null,
                moves: [],
                routeFailures: refreshed.failures,
            });
        }
        nextMap = refreshed.map;
        const beforeDiagnostics = diagnoseSpatialScene(scene, { contract: contract });
        const afterScene = compileSpatialScene(nextMap, {
            contract: contract,
            revision: opts.revision == null ? undefined : opts.revision,
        });
        const afterDiagnostics = diagnoseSpatialScene(afterScene, { contract: contract });
        const beforeMetrics = arrangementMetrics(beforeDiagnostics);
        const afterMetrics = arrangementMetrics(afterDiagnostics);
        const beforeHard = new Set(beforeMetrics.hardViolationIds);
        const addedHard = afterMetrics.hardViolationIds.filter(function (problemId) {
            return !beforeHard.has(problemId);
        }).sort();
        if (addedHard.length) {
            return Object.assign({}, base, {
                accepted: false,
                failureReason: 'hard_violation_introduced',
                planId: null,
                moves: [],
                hardViolationsAdded: addedHard,
            });
        }
        if (compareTuples(arrangementQuality(afterMetrics), arrangementQuality(beforeMetrics)) >= 0) {
            return Object.assign({}, base, {
                accepted: false,
                failureReason: 'configured_metric_not_improved',
                planId: null,
                moves: [],
                metricsBefore: beforeMetrics,
                metricsAfter: afterMetrics,
            });
        }
        const originalEdges = new Map((processMap.canvasEdges || []).filter(function (edge) {
            return edge && edge.edgeId;
        }).map(function (edge) { return [String(edge.edgeId), edge]; }));
        const changedRoutes = sortedValues(nextMap.canvasEdges || [], 'edgeId').filter(function (edge) {
            const original = originalEdges.get(String(edge.edgeId)) || {};
            return canonicalBytes(edge.routing || {}) !== canonicalBytes(original.routing || {});
        }).map(function (edge) {
            return { edgeId: String(edge.edgeId), routing: clone(edge.routing || {}) };
        });
        const proposalIdentity = {
            policyVersion: ARRANGEMENT_POLICY_VERSION,
            obstacleFingerprint: base.obstacleFingerprint,
            scope: base.scope,
            moves: moves,
            routes: changedRoutes,
            metricsBefore: beforeMetrics,
            metricsAfter: afterMetrics,
        };
        const planId = 'pm-arr-' + fnv1a64Hex(canonicalBytes(proposalIdentity));
        return Object.assign({}, base, {
            accepted: true,
            failureReason: null,
            planId: planId,
            moves: moves,
            routes: changedRoutes,
            movementDistance: roundedCoarse(movementDistance),
            metricsBefore: beforeMetrics,
            metricsAfter: afterMetrics,
            hardViolationsAdded: [],
            proposedMap: nextMap,
        });
    }

    return {
        SPATIAL_VERSION: SPATIAL_VERSION,
        CONTRACT_ID: CONTRACT_ID,
        ROUTER_VERSION: ROUTER_VERSION,
        SPATIAL_PROPOSAL_VERSION: SPATIAL_PROPOSAL_VERSION,
        ARRANGEMENT_POLICY_VERSION: ARRANGEMENT_POLICY_VERSION,
        DEFAULT_CONTRACT_URL: DEFAULT_CONTRACT_URL,
        CANDIDATE_POLICY_VERSION: CANDIDATE_POLICY_VERSION,
        validateContract: validateContract,
        loadSpatialContract: loadSpatialContract,
        spatialContractForProcessMap: spatialContractForProcessMap,
        worldToViewport: worldToViewport,
        viewportToWorld: viewportToWorld,
        worldRectToViewport: worldRectToViewport,
        viewportRectToWorld: viewportRectToWorld,
        worldToNormalized: worldToNormalized,
        compileSpatialScene: compileSpatialScene,
        diagnoseSpatialScene: diagnoseSpatialScene,
        generatePlacementCandidates: generatePlacementCandidates,
        generateArrangementPlan: generateArrangementPlan,
        routeOrthogonalEdge: routeOrthogonalEdge,
        spatializeSemanticSuggestions: spatializeSemanticSuggestions,
        applyOrthogonalRoute: applyOrthogonalRoute,
        refreshOrthogonalAutoRoutes: refreshOrthogonalAutoRoutes,
    };
});
