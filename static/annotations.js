// ============================================================
// InspectorPro - Annotation System v2
// Features: Callout shapes, selection/move/resize, color controls
// This file overrides the basic annotation system with full functionality
// ============================================================

(function() {
    'use strict';

    // Only initialize if annoState exists (from main script)
    if (typeof annoState === 'undefined') return;

    // ---- Upgrade annoState with new properties ----
    annoState.selectedId = null;
    annoState.nextId = 1;
    annoState.isDragging = false;
    annoState.dragOffsetX = 0;
    annoState.dragOffsetY = 0;
    annoState.isResizing = false;
    annoState.resizeHandle = null;
    annoState.resizeStart = null;
    annoState.editingId = null;

    // Convert shapes array to data-driven format
    // Old shapes stored DOM elements; new system uses data objects
    const oldShapes = annoState.shapes;
    annoState.shapes = [];

    // ---- Helper functions ----
    function isCalloutType(type) {
        return ['speech-bubble', 'line-callout', 'cloud-callout'].includes(type);
    }

    function getAnnoFill(fillMode, color) {
        if (fillMode === 'none') return 'none';
        if (fillMode === 'solid') return color;
        if (color && color.startsWith('#')) {
            const r = parseInt(color.slice(1, 3), 16);
            const g = parseInt(color.slice(3, 5), 16);
            const b = parseInt(color.slice(5, 7), 16);
            return `rgba(${r},${g},${b},0.25)`;
        }
        return color;
    }

    function getLayerPoint(e) {
        const layer = document.getElementById('annotationLayer');
        if (!layer) return { x: 0, y: 0 };
        const r = layer.getBoundingClientRect();
        return { x: e.clientX - r.left, y: e.clientY - r.top };
    }

    function hitTest(pt) {
        for (let i = annoState.shapes.length - 1; i >= 0; i--) {
            const s = annoState.shapes[i];
            const sx = Math.min(s.x, s.x + s.w);
            const sy = Math.min(s.y, s.y + s.h);
            const sw = Math.abs(s.w);
            const sh = Math.abs(s.h);
            if (pt.x >= sx - 6 && pt.x <= sx + sw + 6 &&
                pt.y >= sy - 6 && pt.y <= sy + sh + 6) {
                return s;
            }
        }
        return null;
    }

    // ---- Override createAnnotationLayer to use our event handlers ----
    const origCreateAnnotationLayer = window.createAnnotationLayer;
    window.createAnnotationLayer = function(drawingDiv) {
        // Feature #97: Allow annotation layer for ALL file types including PDFs
        // Custom annotation shapes (rectangles, arrows, callouts) coexist with PDF native tools
        // The SVG overlay uses pointer-events:none by default so PDF native tools remain accessible

        let layer = drawingDiv.querySelector('#annotationLayer');
        if (layer) {
            // Remove old handlers and add ours
            layer.removeEventListener('mousedown', window.onAnnotationMouseDown);
            layer.removeEventListener('mousemove', window.onAnnotationMouseMove);
            layer.removeEventListener('mouseup', window.onAnnotationMouseUp);
            return layer;
        }

        const svgNS = 'http://www.w3.org/2000/svg';
        layer = document.createElementNS(svgNS, 'svg');
        layer.setAttribute('class', 'annotation-layer');
        layer.id = 'annotationLayer';
        layer.setAttribute('xmlns', svgNS);

        // Our event handlers
        layer.addEventListener('mousedown', handleAnnoMouseDown);
        layer.addEventListener('mousemove', handleAnnoMouseMove);
        layer.addEventListener('mouseup', handleAnnoMouseUp);
        layer.addEventListener('dblclick', handleAnnoDblClick);

        drawingDiv.appendChild(layer);
        updateLayerCursor();
        return layer;
    };

    function updateLayerCursor() {
        const layer = document.getElementById('annotationLayer');
        if (!layer) return;
        if (annoState.activeTool === 'select') {
            // Feature #95: In select mode, layer itself is pointer-events:none
            // so pan/zoom works. Individual shapes get pointer-events via renderAllShapes.
            layer.classList.remove('drawing-active');
            layer.classList.add('selecting');
        } else if (annoState.activeTool) {
            // Drawing tool active: layer captures all events
            layer.classList.add('drawing-active');
            layer.classList.remove('selecting');
        }
    }

    // ---- Override selectAnnoTool to clear selection ----
    const origSelectAnnoTool = window.selectAnnoTool;
    window.selectAnnoTool = function(toolName) {
        annoState.selectedId = null;
        if (origSelectAnnoTool) origSelectAnnoTool(toolName);
        updateLayerCursor();
        renderAllShapes();
    };

    // ---- Override color swatch click to update selected shape ----
    document.querySelectorAll('.anno-color-swatch').forEach(swatch => {
        swatch.addEventListener('click', () => {
            if (annoState.selectedId !== null) {
                const s = annoState.shapes.find(sh => sh.id === annoState.selectedId);
                if (s) { s.color = annoState.strokeColor; renderAllShapes(); }
            }
        });
    });

    // ---- Override stroke width click to update selected shape ----
    document.querySelectorAll('.anno-stroke-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (annoState.selectedId !== null) {
                const s = annoState.shapes.find(sh => sh.id === annoState.selectedId);
                if (s) { s.strokeWidth = annoState.strokeWidth; renderAllShapes(); }
            }
        });
    });

    // ---- Override fill button click to update selected shape ----
    document.querySelectorAll('.anno-fill-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (annoState.selectedId !== null) {
                const s = annoState.shapes.find(sh => sh.id === annoState.selectedId);
                if (s) { s.fillMode = annoState.fillMode; renderAllShapes(); }
            }
        });
    });

    // ---- Mouse event handlers ----
    function handleAnnoMouseDown(e) {
        if (e.button !== 0) return;
        const pt = getLayerPoint(e);
        closeAnnoTextEditor();

        // Check resize handles first
        if (annoState.activeTool === 'select' && annoState.selectedId !== null) {
            const handleEl = e.target.closest('[data-anno-handle]');
            if (handleEl) {
                e.preventDefault();
                e.stopPropagation();
                annoState.isResizing = true;
                annoState.resizeHandle = handleEl.dataset.annoHandle;
                const shape = annoState.shapes.find(s => s.id === annoState.selectedId);
                annoState.resizeStart = {
                    x: pt.x, y: pt.y,
                    ox: shape.x, oy: shape.y,
                    ow: shape.w, oh: shape.h
                };
                return;
            }
        }

        // Select tool: hit test
        if (annoState.activeTool === 'select') {
            const shape = hitTest(pt);
            if (shape) {
                annoState.selectedId = shape.id;
                annoState.isDragging = true;
                annoState.dragOffsetX = pt.x - shape.x;
                annoState.dragOffsetY = pt.y - shape.y;
            } else {
                annoState.selectedId = null;
            }
            renderAllShapes();
            e.preventDefault();
            return;
        }

        // Drawing a new shape
        if (annoState.activeTool && annoState.activeTool !== 'select') {
            annoState.isDrawing = true;
            annoState.drawStartX = pt.x;
            annoState.drawStartY = pt.y;
            annoState.drawCurrentX = pt.x;
            annoState.drawCurrentY = pt.y;
            e.preventDefault();
            e.stopPropagation();
        }
    }

    function handleAnnoMouseMove(e) {
        const pt = getLayerPoint(e);

        // Resizing
        if (annoState.isResizing && annoState.selectedId !== null) {
            const s = annoState.shapes.find(sh => sh.id === annoState.selectedId);
            if (!s) return;
            const rs = annoState.resizeStart;
            const dx = pt.x - rs.x, dy = pt.y - rs.y;
            const h = annoState.resizeHandle;
            if (h === 'se') { s.w = Math.max(30, rs.ow + dx); s.h = Math.max(30, rs.oh + dy); }
            else if (h === 'sw') { s.x = rs.ox + dx; s.w = Math.max(30, rs.ow - dx); s.h = Math.max(30, rs.oh + dy); }
            else if (h === 'ne') { s.w = Math.max(30, rs.ow + dx); s.y = rs.oy + dy; s.h = Math.max(30, rs.oh - dy); }
            else if (h === 'nw') { s.x = rs.ox + dx; s.y = rs.oy + dy; s.w = Math.max(30, rs.ow - dx); s.h = Math.max(30, rs.oh - dy); }
            renderAllShapes();
            e.preventDefault();
            return;
        }

        // Dragging
        if (annoState.isDragging && annoState.selectedId !== null) {
            const s = annoState.shapes.find(sh => sh.id === annoState.selectedId);
            if (s) {
                s.x = pt.x - annoState.dragOffsetX;
                s.y = pt.y - annoState.dragOffsetY;
                renderAllShapes();
            }
            e.preventDefault();
            return;
        }

        // Drawing preview
        if (annoState.isDrawing) {
            annoState.drawCurrentX = pt.x;
            annoState.drawCurrentY = pt.y;
            renderAllShapes();
            e.preventDefault();
        }
    }

    function handleAnnoMouseUp(e) {
        if (annoState.isResizing) {
            annoState.isResizing = false;
            annoState.resizeHandle = null;
            annoState.resizeStart = null;
            return;
        }
        if (annoState.isDragging) {
            annoState.isDragging = false;
            return;
        }

        if (annoState.isDrawing) {
            const w = Math.abs(annoState.drawCurrentX - annoState.drawStartX);
            const h = Math.abs(annoState.drawCurrentY - annoState.drawStartY);
            if (w > 10 || h > 10) {
                const shape = {
                    id: annoState.nextId++,
                    type: annoState.activeTool,
                    x: Math.min(annoState.drawStartX, annoState.drawCurrentX),
                    y: Math.min(annoState.drawStartY, annoState.drawCurrentY),
                    w: w,
                    h: h,
                    color: annoState.strokeColor,
                    strokeWidth: annoState.strokeWidth,
                    fillMode: annoState.fillMode,
                    text: '',
                };
                annoState.shapes.push(shape);
                annoState.selectedId = shape.id;
            }
            annoState.isDrawing = false;
            renderAllShapes();
            e.preventDefault();
            e.stopPropagation();
        }
    }

    function handleAnnoDblClick(e) {
        const pt = getLayerPoint(e);
        const shape = hitTest(pt);
        if (shape && isCalloutType(shape.type)) {
            openAnnoTextEditor(shape);
            e.preventDefault();
            e.stopPropagation();
        }
    }

    // ---- Text editor ----
    function openAnnoTextEditor(shape) {
        closeAnnoTextEditor();
        annoState.editingId = shape.id;
        const drawingArea = document.getElementById('drawingArea');
        if (!drawingArea) return;

        const sx = Math.min(shape.x, shape.x + shape.w);
        const sy = Math.min(shape.y, shape.y + shape.h);
        const sw = Math.abs(shape.w);
        const sh = Math.abs(shape.h);

        const ta = document.createElement('textarea');
        ta.className = 'anno-text-editor';
        ta.id = 'annoTextEditor';
        ta.style.left = `${sx + 8}px`;
        ta.style.top = `${sy + 8}px`;
        ta.style.width = `${Math.max(40, sw - 16)}px`;
        ta.style.height = `${Math.max(20, sh * 0.55)}px`;
        ta.style.color = shape.color;
        ta.value = shape.text || '';

        ta.addEventListener('blur', () => {
            shape.text = ta.value;
            annoState.editingId = null;
            ta.remove();
            renderAllShapes();
        });
        ta.addEventListener('keydown', (ev) => {
            if (ev.key === 'Escape') {
                shape.text = ta.value;
                annoState.editingId = null;
                ta.remove();
                renderAllShapes();
            }
            ev.stopPropagation();
        });

        drawingArea.appendChild(ta);
        ta.focus();
    }

    function closeAnnoTextEditor() {
        const ed = document.getElementById('annoTextEditor');
        if (ed) {
            const s = annoState.shapes.find(sh => sh.id === annoState.editingId);
            if (s) s.text = ed.value;
            annoState.editingId = null;
            ed.remove();
        }
    }

    // ---- Keyboard shortcuts ----
    document.addEventListener('keydown', (e) => {
        if (annoState.editingId !== null) return;
        const tag = document.activeElement?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA') return;

        // Delete/Backspace removes selected shape
        if ((e.key === 'Delete' || e.key === 'Backspace') &&
            annoState.selectedId !== null && annoState.activeTool === 'select') {
            annoState.shapes = annoState.shapes.filter(s => s.id !== annoState.selectedId);
            annoState.selectedId = null;
            renderAllShapes();
            e.preventDefault();
        }
        // V for select tool
        if ((e.key === 'v' || e.key === 'V') &&
            document.getElementById('annotationToolbar')?.classList.contains('visible')) {
            window.selectAnnoTool('select');
        }
        // Escape deselects
        if (e.key === 'Escape' && annoState.selectedId !== null) {
            annoState.selectedId = null;
            renderAllShapes();
        }
    });

    // ---- Render all shapes (data-driven) ----
    function renderAllShapes() {
        const layer = document.getElementById('annotationLayer');
        if (!layer) return;

        layer.innerHTML = '';
        updateLayerCursor();

        const svgNS = 'http://www.w3.org/2000/svg';

        // Render each shape from data
        annoState.shapes.forEach(shape => {
            const g = document.createElementNS(svgNS, 'g');
            g.dataset.shapeId = shape.id;
            // Feature #95: Make individual shapes clickable even when layer is pointer-events:none
            g.style.pointerEvents = 'all';
            g.style.cursor = annoState.activeTool === 'select' ? 'move' : 'crosshair';

            const fill = getAnnoFill(shape.fillMode, shape.color);
            const x = Math.min(shape.x, shape.x + shape.w);
            const y = Math.min(shape.y, shape.y + shape.h);
            const w = Math.abs(shape.w);
            const h = Math.abs(shape.h);

            drawShape(g, shape.type, x, y, w, h, shape.color, shape.strokeWidth, fill);

            // Text label for callouts
            if (shape.text && isCalloutType(shape.type)) {
                drawText(g, shape.text, x, y, w, h, shape.color, shape.type);
            }

            layer.appendChild(g);

            // Selection handles
            if (shape.id === annoState.selectedId) {
                drawSelectionHandles(layer, x, y, w, h);
            }
        });

        // Preview shape while drawing
        if (annoState.isDrawing) {
            const px = Math.min(annoState.drawStartX, annoState.drawCurrentX);
            const py = Math.min(annoState.drawStartY, annoState.drawCurrentY);
            const pw = Math.abs(annoState.drawCurrentX - annoState.drawStartX);
            const ph = Math.abs(annoState.drawCurrentY - annoState.drawStartY);
            if (pw > 2 || ph > 2) {
                const pg = document.createElementNS(svgNS, 'g');
                pg.style.opacity = '0.5';
                const fill = getAnnoFill(annoState.fillMode, annoState.strokeColor);
                drawShape(pg, annoState.activeTool, px, py, pw, ph, annoState.strokeColor, annoState.strokeWidth, fill);
                layer.appendChild(pg);
            }
        }
    }

    // ---- Shape drawing dispatcher ----
    function drawShape(g, type, x, y, w, h, color, sw, fill) {
        switch (type) {
            case 'speech-bubble': drawSpeechBubble(g, x, y, w, h, color, sw, fill); break;
            case 'line-callout': drawLineCallout(g, x, y, w, h, color, sw, fill); break;
            case 'cloud-callout': drawCloudCallout(g, x, y, w, h, color, sw, fill); break;
            case 'line': drawLine(g, x, y, w, h, color, sw); break;
            case 'arrow': drawArrow(g, x, y, w, h, color, sw, false); break;
            case 'double-arrow': drawArrow(g, x, y, w, h, color, sw, true); break;
            case 'rectangle': drawRect(g, x, y, w, h, color, sw, fill, 0); break;
            case 'rounded-rectangle': drawRect(g, x, y, w, h, color, sw, fill, Math.min(w, h) * 0.15); break;
            case 'circle': drawEllipse(g, x, y, w, h, color, sw, fill); break;
            case 'triangle': drawPoly(g, `${x + w / 2},${y} ${x + w},${y + h} ${x},${y + h}`, color, sw, fill); break;
            case 'diamond': drawPoly(g, `${x + w / 2},${y} ${x + w},${y + h / 2} ${x + w / 2},${y + h} ${x},${y + h / 2}`, color, sw, fill); break;
            case 'block-arrow-right': drawBlockArrow(g, x, y, w, h, color, sw, fill, 'right'); break;
            case 'block-arrow-left': drawBlockArrow(g, x, y, w, h, color, sw, fill, 'left'); break;
            case 'block-arrow-up': drawBlockArrow(g, x, y, w, h, color, sw, fill, 'up'); break;
            case 'block-arrow-down': drawBlockArrow(g, x, y, w, h, color, sw, fill, 'down'); break;
            case 'block-arrow-chevron': drawChevron(g, x, y, w, h, color, sw, fill); break;
        }
    }

    // ---- Shape renderers ----
    const svgNS = 'http://www.w3.org/2000/svg';

    function svgEl(tag) { return document.createElementNS(svgNS, tag); }

    function drawSpeechBubble(g, x, y, w, h, color, sw, fill) {
        const bodyH = h * 0.75;
        const rx = Math.min(10, w / 4, bodyH / 4);
        const body = svgEl('rect');
        body.setAttribute('x', x); body.setAttribute('y', y);
        body.setAttribute('width', w); body.setAttribute('height', bodyH);
        body.setAttribute('rx', rx); body.setAttribute('fill', fill);
        body.setAttribute('stroke', color); body.setAttribute('stroke-width', sw);
        g.appendChild(body);

        // Tail pointer
        const tx1 = x + w * 0.15, tx2 = x + w * 0.35, ty = y + bodyH;
        const tipX = x + w * 0.05, tipY = y + h;
        const tail = svgEl('path');
        tail.setAttribute('d', `M${tx1},${ty} L${tipX},${tipY} L${tx2},${ty}`);
        tail.setAttribute('fill', fill === 'none' ? 'none' : fill);
        tail.setAttribute('stroke', color); tail.setAttribute('stroke-width', sw);
        tail.setAttribute('stroke-linejoin', 'round');
        g.appendChild(tail);

        // Cover line where tail meets body (for clean look)
        if (fill !== 'none') {
            const cover = svgEl('line');
            cover.setAttribute('x1', tx1 + 1); cover.setAttribute('y1', ty);
            cover.setAttribute('x2', tx2 - 1); cover.setAttribute('y2', ty);
            cover.setAttribute('stroke', fill); cover.setAttribute('stroke-width', sw + 1);
            g.appendChild(cover);
        }
    }

    function drawLineCallout(g, x, y, w, h, color, sw, fill) {
        const boxH = h * 0.6, boxX = x + w * 0.2, boxW = w * 0.8;
        const box = svgEl('rect');
        box.setAttribute('x', boxX); box.setAttribute('y', y);
        box.setAttribute('width', boxW); box.setAttribute('height', boxH);
        box.setAttribute('rx', 4); box.setAttribute('fill', fill);
        box.setAttribute('stroke', color); box.setAttribute('stroke-width', sw);
        g.appendChild(box);

        // Leader line
        const ln = svgEl('line');
        ln.setAttribute('x1', boxX); ln.setAttribute('y1', y + boxH);
        ln.setAttribute('x2', x); ln.setAttribute('y2', y + h);
        ln.setAttribute('stroke', color); ln.setAttribute('stroke-width', sw);
        g.appendChild(ln);

        // Dot at leader endpoint
        const dot = svgEl('circle');
        dot.setAttribute('cx', x); dot.setAttribute('cy', y + h);
        dot.setAttribute('r', Math.max(3, sw + 1)); dot.setAttribute('fill', color);
        g.appendChild(dot);
    }

    function drawCloudCallout(g, x, y, w, h, color, sw, fill) {
        const bodyH = h * 0.75;
        const cx = x + w / 2, cy = y + bodyH / 2;
        const rx = w / 2, ry = bodyH / 2;
        const bumps = 8;
        let d = '';
        for (let i = 0; i < bumps; i++) {
            const a1 = (i / bumps) * 2 * Math.PI;
            const a2 = ((i + 1) / bumps) * 2 * Math.PI;
            const x1 = cx + rx * Math.cos(a1), y1 = cy + ry * Math.sin(a1);
            const x2 = cx + rx * Math.cos(a2), y2 = cy + ry * Math.sin(a2);
            const ma = (a1 + a2) / 2;
            const cpx = cx + rx * 1.2 * Math.cos(ma);
            const cpy = cy + ry * 1.2 * Math.sin(ma);
            if (i === 0) d += `M${x1},${y1}`;
            d += ` Q${cpx},${cpy} ${x2},${y2}`;
        }
        d += 'Z';
        const cloud = svgEl('path');
        cloud.setAttribute('d', d); cloud.setAttribute('fill', fill);
        cloud.setAttribute('stroke', color); cloud.setAttribute('stroke-width', sw);
        g.appendChild(cloud);

        // Thought bubble tail
        const b1 = svgEl('circle');
        b1.setAttribute('cx', x + w * 0.2);
        b1.setAttribute('cy', y + bodyH + (h - bodyH) * 0.35);
        b1.setAttribute('r', Math.max(4, Math.min(w, h) * 0.06));
        b1.setAttribute('fill', fill === 'none' ? 'none' : fill);
        b1.setAttribute('stroke', color); b1.setAttribute('stroke-width', sw);
        g.appendChild(b1);

        const b2 = svgEl('circle');
        b2.setAttribute('cx', x + w * 0.2 - 4);
        b2.setAttribute('cy', y + h - 4);
        b2.setAttribute('r', Math.max(2, Math.min(w, h) * 0.03));
        b2.setAttribute('fill', fill === 'none' ? 'none' : fill);
        b2.setAttribute('stroke', color); b2.setAttribute('stroke-width', sw);
        g.appendChild(b2);
    }

    function drawLine(g, x, y, w, h, color, sw) {
        const ln = svgEl('line');
        ln.setAttribute('x1', x); ln.setAttribute('y1', y + h);
        ln.setAttribute('x2', x + w); ln.setAttribute('y2', y);
        ln.setAttribute('stroke', color); ln.setAttribute('stroke-width', sw);
        ln.setAttribute('stroke-linecap', 'round');
        g.appendChild(ln);
    }

    function drawArrow(g, x, y, w, h, color, sw, isDouble) {
        const ln = svgEl('line');
        ln.setAttribute('x1', x); ln.setAttribute('y1', y + h);
        ln.setAttribute('x2', x + w); ln.setAttribute('y2', y);
        ln.setAttribute('stroke', color); ln.setAttribute('stroke-width', sw);
        ln.setAttribute('stroke-linecap', 'round');
        g.appendChild(ln);

        // Arrowhead at end
        const angle = Math.atan2(-h, w);
        const headLen = Math.max(10, sw * 4);
        const ax = x + w, ay = y;
        const a1 = angle + Math.PI * 0.8, a2 = angle - Math.PI * 0.8;
        const ah = svgEl('polyline');
        ah.setAttribute('points',
            `${ax + headLen * Math.cos(a1)},${ay + headLen * Math.sin(a1)} ${ax},${ay} ${ax + headLen * Math.cos(a2)},${ay + headLen * Math.sin(a2)}`);
        ah.setAttribute('fill', 'none'); ah.setAttribute('stroke', color);
        ah.setAttribute('stroke-width', sw); ah.setAttribute('stroke-linecap', 'round');
        ah.setAttribute('stroke-linejoin', 'round');
        g.appendChild(ah);

        if (isDouble) {
            const angle2 = Math.atan2(h, -w);
            const bx = x, by = y + h;
            const b1 = angle2 + Math.PI * 0.8, b2 = angle2 - Math.PI * 0.8;
            const ah2 = svgEl('polyline');
            ah2.setAttribute('points',
                `${bx + headLen * Math.cos(b1)},${by + headLen * Math.sin(b1)} ${bx},${by} ${bx + headLen * Math.cos(b2)},${by + headLen * Math.sin(b2)}`);
            ah2.setAttribute('fill', 'none'); ah2.setAttribute('stroke', color);
            ah2.setAttribute('stroke-width', sw); ah2.setAttribute('stroke-linecap', 'round');
            ah2.setAttribute('stroke-linejoin', 'round');
            g.appendChild(ah2);
        }
    }

    function drawRect(g, x, y, w, h, color, sw, fill, rx) {
        const el = svgEl('rect');
        el.setAttribute('x', x); el.setAttribute('y', y);
        el.setAttribute('width', w); el.setAttribute('height', h);
        el.setAttribute('rx', rx); el.setAttribute('fill', fill);
        el.setAttribute('stroke', color); el.setAttribute('stroke-width', sw);
        g.appendChild(el);
    }

    function drawEllipse(g, x, y, w, h, color, sw, fill) {
        const el = svgEl('ellipse');
        el.setAttribute('cx', x + w / 2); el.setAttribute('cy', y + h / 2);
        el.setAttribute('rx', w / 2); el.setAttribute('ry', h / 2);
        el.setAttribute('fill', fill); el.setAttribute('stroke', color);
        el.setAttribute('stroke-width', sw);
        g.appendChild(el);
    }

    function drawPoly(g, points, color, sw, fill) {
        const el = svgEl('polygon');
        el.setAttribute('points', points); el.setAttribute('fill', fill);
        el.setAttribute('stroke', color); el.setAttribute('stroke-width', sw);
        el.setAttribute('stroke-linejoin', 'round');
        g.appendChild(el);
    }

    function drawBlockArrow(g, x, y, w, h, color, sw, fill, dir) {
        const s = 0.35;
        let pts;
        if (dir === 'right') { const hx = x + w * 0.65; pts = `${hx},${y} ${x + w},${y + h / 2} ${hx},${y + h} ${hx},${y + h * (1 - s)} ${x},${y + h * (1 - s)} ${x},${y + h * s} ${hx},${y + h * s}`; }
        else if (dir === 'left') { const hx = x + w * 0.35; pts = `${hx},${y} ${x},${y + h / 2} ${hx},${y + h} ${hx},${y + h * (1 - s)} ${x + w},${y + h * (1 - s)} ${x + w},${y + h * s} ${hx},${y + h * s}`; }
        else if (dir === 'up') { const hy = y + h * 0.35; pts = `${x},${hy} ${x + w / 2},${y} ${x + w},${hy} ${x + w * (1 - s)},${hy} ${x + w * (1 - s)},${y + h} ${x + w * s},${y + h} ${x + w * s},${hy}`; }
        else { const hy = y + h * 0.65; pts = `${x},${hy} ${x + w / 2},${y + h} ${x + w},${hy} ${x + w * (1 - s)},${hy} ${x + w * (1 - s)},${y} ${x + w * s},${y} ${x + w * s},${hy}`; }
        drawPoly(g, pts, color, sw, fill);
    }

    function drawChevron(g, x, y, w, h, color, sw, fill) {
        const notch = w * 0.35;
        drawPoly(g, `${x},${y} ${x + w - notch},${y} ${x + w},${y + h / 2} ${x + w - notch},${y + h} ${x},${y + h} ${x + notch},${y + h / 2}`, color, sw, fill);
    }

    // ---- Text rendering for callouts ----
    function drawText(g, text, x, y, w, h, color, type) {
        const textEl = svgEl('text');
        let centerY = type === 'line-callout' ? y + h * 0.3 : y + h * 0.38;
        textEl.setAttribute('x', x + w / 2);
        textEl.setAttribute('text-anchor', 'middle');
        textEl.setAttribute('dominant-baseline', 'middle');
        textEl.setAttribute('fill', color);
        textEl.setAttribute('font-size', '12');
        textEl.setAttribute('font-family', 'inherit');
        textEl.style.pointerEvents = 'none';

        const lines = text.split('\n');
        const lh = 15;
        const startY = centerY - ((lines.length - 1) * lh) / 2;
        lines.forEach((line, i) => {
            const ts = svgEl('tspan');
            ts.setAttribute('x', x + w / 2);
            ts.setAttribute('y', startY + i * lh);
            ts.textContent = line;
            textEl.appendChild(ts);
        });
        g.appendChild(textEl);
    }

    // ---- Selection handles ----
    function drawSelectionHandles(layer, x, y, w, h) {
        // Dashed selection rectangle
        const sel = svgEl('rect');
        sel.setAttribute('x', x - 2); sel.setAttribute('y', y - 2);
        sel.setAttribute('width', w + 4); sel.setAttribute('height', h + 4);
        sel.setAttribute('fill', 'none'); sel.setAttribute('stroke', '#4fc3f7');
        sel.setAttribute('stroke-width', '1'); sel.setAttribute('stroke-dasharray', '4 3');
        sel.style.pointerEvents = 'none';
        layer.appendChild(sel);

        // Corner handles
        [{ cx: x, cy: y, p: 'nw' }, { cx: x + w, cy: y, p: 'ne' },
         { cx: x, cy: y + h, p: 'sw' }, { cx: x + w, cy: y + h, p: 'se' }].forEach(hd => {
            const r = svgEl('rect');
            r.setAttribute('x', hd.cx - 4); r.setAttribute('y', hd.cy - 4);
            r.setAttribute('width', 8); r.setAttribute('height', 8);
            r.setAttribute('fill', '#4fc3f7'); r.setAttribute('stroke', '#fff');
            r.setAttribute('stroke-width', '1');
            r.style.cursor = (hd.p === 'nw' || hd.p === 'se') ? 'nwse-resize' : 'nesw-resize';
            r.style.pointerEvents = 'all';
            r.dataset.annoHandle = hd.p;
            layer.appendChild(r);
        });
    }

    // ---- Patch renderViewport to use our rendering ----
    const origRenderViewport = window.renderViewport;
    window.renderViewport = function() {
        origRenderViewport();
        window.updateAnnotationToolbarVisibility();
        // Feature #98: Only create annotation layer on Drawing Only tab, not Split View
        const drawingArea = document.getElementById('drawingArea');
        if (drawingArea && state.activeTab === 'drawing') {
            window.createAnnotationLayer(drawingArea);
            setTimeout(() => renderAllShapes(), 30);
        }
    };

    // Expose renderAllShapes for external use
    window.renderAnnotationShapes = renderAllShapes;

    // ---- Undo / Clear All (Feature #91) ----

    // Undo: remove last drawn shape
    function undoLastShape() {
        if (annoState.shapes.length === 0) return;
        annoState.shapes.pop();
        // If selected shape was removed, deselect
        if (annoState.selectedId !== null) {
            const stillExists = annoState.shapes.find(s => s.id === annoState.selectedId);
            if (!stillExists) annoState.selectedId = null;
        }
        renderAllShapes();
    }

    // Clear All: remove all annotations (with confirmation)
    function clearAllAnnotations(skipConfirm) {
        if (annoState.shapes.length === 0) return;
        if (!skipConfirm && !confirm('Clear all annotations? This cannot be undone.')) return;
        annoState.shapes = [];
        annoState.selectedId = null;
        renderAllShapes();
    }

    // Wire up Undo button
    const undoBtn = document.getElementById('annoUndoBtn');
    if (undoBtn) {
        undoBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            undoLastShape();
        });
    }

    // Wire up Clear All button
    const clearAllBtn = document.getElementById('annoClearAllBtn');
    if (clearAllBtn) {
        clearAllBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            clearAllAnnotations(false);
        });
    }

    // Keyboard shortcut: Ctrl+Z for undo
    document.addEventListener('keydown', (e) => {
        if (annoState.editingId !== null) return;
        const tag = document.activeElement?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA') return;

        if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
            // Only undo if annotation toolbar is visible (drawing loaded)
            const toolbar = document.getElementById('annotationToolbar');
            if (toolbar && toolbar.classList.contains('visible')) {
                e.preventDefault();
                undoLastShape();
            }
        }
    });

    // Expose for external use
    window.annoUndoLastShape = undoLastShape;
    window.annoClearAllAnnotations = clearAllAnnotations;

    console.log('InspectorPro Annotation System v2 loaded');
})();
