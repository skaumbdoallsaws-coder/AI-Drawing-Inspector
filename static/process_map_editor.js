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
    let instanceCounter = 0;

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
        const nodes = Array.isArray(processMap && processMap.nodes) ? processMap.nodes : [];
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
        return (Array.isArray(processMap && processMap.edges) ? processMap.edges : []).filter(function (edge) {
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
                positions[node.nodeId] = saved && finiteNumber(saved.x) && finiteNumber(saved.y)
                    ? { x: saved.x, y: saved.y, width: width, height: height }
                    : {
                        x: padding + rank * (width + columnGap),
                        y: padding + rowIndex * (height + rowGap),
                        width: width,
                        height: height,
                    };
            });
        });
        return positions;
    }

    function graphBounds(positions) {
        const values = Object.keys(positions || {}).map(function (key) { return positions[key]; });
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
        return {
            x: side === 'out' ? position.x + position.width : position.x,
            y: position.y + position.height / 2,
        };
    }

    function bezierPath(start, end) {
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

    function ProcessMapEditor(host, options) {
        this.host = host;
        this.options = options || {};
        this.processMap = this.options.map || { nodes: [], edges: [] };
        this.findings = Array.isArray(this.options.findings) ? this.options.findings : [];
        this.focusNodeId = this.options.focusNodeId || null;
        this.selectedNodeId = this.options.selectedNodeId || null;
        this.transform = { x: 0, y: 0, scale: 1 };
        this.drag = null;
        this.instanceId = 'pm-arrow-' + (++instanceCounter);
        this.destroyed = false;
        this._build();
        this.renderGraph();
    }

    ProcessMapEditor.prototype._build = function () {
        this.host.innerHTML = '';
        this.root = document.createElement('div');
        this.root.className = 'pm-editor';
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

        this.toolbarActions = document.createElement('div');
        this.toolbarActions.className = 'pm-toolbar-actions';
        this.toolbarActions.appendChild(this._button('-', 'Zoom out', this.zoomBy.bind(this, 0.86)));
        this.toolbarActions.appendChild(this._button('+', 'Zoom in', this.zoomBy.bind(this, 1.16)));
        this.toolbarActions.appendChild(this._button('Fit', 'Fit flow to viewport', this.fit.bind(this)));
        this.backButton = this._button('<', 'Back one process scope', this.back.bind(this));
        this.backButton.classList.add('pm-back-button');
        this.toolbarActions.appendChild(this.backButton);
        this.toolbarActions.appendChild(this._button(
            'Structure',
            'Return to product structure',
            this.exit.bind(this)
        ));
        this.toolbar.appendChild(this.toolbarLeft);
        this.toolbar.appendChild(this.toolbarActions);

        this.viewport = document.createElement('div');
        this.viewport.className = 'pm-viewport';
        this.viewport.tabIndex = 0;
        this.viewport.setAttribute('aria-label', 'Read-only process flow canvas');
        this.world = document.createElement('div');
        this.world.className = 'pm-world';
        this.edgeSvg = svgElement('svg', { class: 'pm-edge-layer', 'aria-hidden': 'true' });
        this.nodeLayer = document.createElement('div');
        this.nodeLayer.className = 'pm-node-layer';
        this.world.appendChild(this.edgeSvg);
        this.world.appendChild(this.nodeLayer);
        this.viewport.appendChild(this.world);
        this.root.appendChild(this.toolbar);
        this.root.appendChild(this.viewport);
        this.host.appendChild(this.root);

        this._onPointerDown = this.pointerDown.bind(this);
        this._onPointerMove = this.pointerMove.bind(this);
        this._onPointerUp = this.pointerUp.bind(this);
        this._onWheel = this.wheel.bind(this);
        this.viewport.addEventListener('pointerdown', this._onPointerDown);
        this.viewport.addEventListener('pointermove', this._onPointerMove);
        this.viewport.addEventListener('pointerup', this._onPointerUp);
        this.viewport.addEventListener('pointercancel', this._onPointerUp);
        this.viewport.addEventListener('wheel', this._onWheel, { passive: false });
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

    ProcessMapEditor.prototype.renderGraph = function () {
        const nodes = scopedNodes(this.processMap, this.focusNodeId);
        const edges = visibleEdges(this.processMap, nodes);
        this.positions = layeredLayout(nodes, edges);
        this.bounds = graphBounds(this.positions);
        this.nodeLayer.innerHTML = '';
        this.edgeSvg.innerHTML = '';

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

        edges.forEach(function (edge) {
            const fromPosition = this.positions[edge.from.nodeId];
            const toPosition = this.positions[edge.to.nodeId];
            if (!fromPosition || !toPosition) return;
            const pathValue = bezierPath(
                portAnchor(fromPosition, 'out'),
                portAnchor(toPosition, 'in')
            );
            const path = svgElement('path', {
                d: pathValue,
                class: 'pm-edge pm-edge-' + String(edge.kind || 'precedence'),
                'marker-end': 'url(#' + this.instanceId + ')',
                'data-edge-id': edge.edgeId || '',
            });
            this.edgeSvg.appendChild(path);
        }, this);

        nodes.forEach(function (node) { this.renderNode(node); }, this);
        this.updateHeader(nodes, edges);
        this.applyTransform();
        const schedule = typeof requestAnimationFrame === 'function'
            ? requestAnimationFrame
            : function (callback) { return setTimeout(callback, 0); };
        schedule(this.fit.bind(this));
    };

    ProcessMapEditor.prototype.renderNode = function (node) {
        const position = this.positions[node.nodeId];
        if (!position) return;
        const wrapper = document.createElement('div');
        wrapper.className = 'pm-node pm-node-type-' + String(node.type || 'unknown');
        if (node.nodeId === this.selectedNodeId) wrapper.classList.add('selected');
        wrapper.style.left = position.x + 'px';
        wrapper.style.top = position.y + 'px';
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

        const inputPort = document.createElement('span');
        inputPort.className = 'pm-port pm-port-in';
        inputPort.textContent = '+';
        inputPort.setAttribute('aria-hidden', 'true');
        const outputPort = document.createElement('span');
        outputPort.className = 'pm-port pm-port-out';
        outputPort.textContent = '+';
        outputPort.setAttribute('aria-hidden', 'true');
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
        wrapper.appendChild(card);
        wrapper.addEventListener('dblclick', function (event) {
            event.preventDefault();
            event.stopPropagation();
            this.focus(node.nodeId);
        }.bind(this));
        this.nodeLayer.appendChild(wrapper);
    };

    ProcessMapEditor.prototype.updateHeader = function (nodes, edges) {
        const focus = this.focusNodeId && (this.processMap.nodes || []).find(function (node) {
            return node && node.nodeId === this.focusNodeId;
        }, this);
        this.title.textContent = focus ? (focus.name || focus.nodeId) : 'Process Flow';
        this.subtitle.textContent = nodes.length + ' nodes / ' + edges.length
            + ' visible precedence connections / read only';
        this.backButton.disabled = !this.focusNodeId;
    };

    ProcessMapEditor.prototype.select = function (nodeId) {
        this.selectedNodeId = nodeId;
        Array.prototype.forEach.call(this.nodeLayer.querySelectorAll('.pm-node'), function (node) {
            node.classList.toggle('selected', node.getAttribute('data-node-id') === nodeId);
        });
        if (typeof this.options.onSelect === 'function') this.options.onSelect(nodeId);
    };

    ProcessMapEditor.prototype.focus = function (nodeId) {
        const children = (this.processMap.nodes || []).filter(function (node) {
            return node && node.parentNodeId === nodeId;
        });
        if (!children.length) return;
        this.focusNodeId = nodeId;
        if (typeof this.options.onFocusChange === 'function') {
            this.options.onFocusChange(this.focusNodeId);
        }
        this.renderGraph();
    };

    ProcessMapEditor.prototype.back = function () {
        if (!this.focusNodeId) return;
        const focused = (this.processMap.nodes || []).find(function (node) {
            return node && node.nodeId === this.focusNodeId;
        }, this);
        const parent = focused && focused.parentNodeId
            ? (this.processMap.nodes || []).find(function (node) {
                return node && node.nodeId === focused.parentNodeId;
            })
            : null;
        this.focusNodeId = parent && parent.level >= 1 ? parent.nodeId : null;
        if (typeof this.options.onFocusChange === 'function') {
            this.options.onFocusChange(this.focusNodeId);
        }
        this.renderGraph();
    };

    ProcessMapEditor.prototype.exit = function () {
        if (typeof this.options.onExit === 'function') this.options.onExit();
    };

    ProcessMapEditor.prototype.applyTransform = function () {
        this.world.style.transform = 'translate(' + this.transform.x + 'px, '
            + this.transform.y + 'px) scale(' + this.transform.scale + ')';
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

    ProcessMapEditor.prototype.pointerDown = function (event) {
        if (event.button !== 0 || event.target.closest('.pm-node, button')) return;
        this.drag = {
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
        if (!this.drag || event.pointerId !== this.drag.pointerId) return;
        this.transform.x = this.drag.startX + event.clientX - this.drag.clientX;
        this.transform.y = this.drag.startY + event.clientY - this.drag.clientY;
        this.applyTransform();
    };

    ProcessMapEditor.prototype.pointerUp = function (event) {
        if (!this.drag || event.pointerId !== this.drag.pointerId) return;
        try { this.viewport.releasePointerCapture(event.pointerId); } catch (_) {}
        this.drag = null;
        this.viewport.classList.remove('panning');
    };

    ProcessMapEditor.prototype.destroy = function () {
        this.destroyed = true;
        if (!this.viewport) return;
        this.viewport.removeEventListener('pointerdown', this._onPointerDown);
        this.viewport.removeEventListener('pointermove', this._onPointerMove);
        this.viewport.removeEventListener('pointerup', this._onPointerUp);
        this.viewport.removeEventListener('pointercancel', this._onPointerUp);
        this.viewport.removeEventListener('wheel', this._onWheel);
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
        NODE_WIDTH: NODE_WIDTH,
        NODE_HEIGHT: NODE_HEIGHT,
        bezierPath: bezierPath,
        graphBounds: graphBounds,
        layeredLayout: layeredLayout,
        mount: mount,
        portAnchor: portAnchor,
        scopedNodes: scopedNodes,
        visibleEdges: visibleEdges,
    };
});
