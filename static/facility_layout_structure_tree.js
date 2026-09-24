/**
 * Facility Layout structure tree renderer.
 *
 * Renders the hierarchy produced by facility_layout_structure.js into a host
 * element. Holds no layout state of its own: it is handed a derived model and
 * a view descriptor, and it draws them.
 *
 * Two identities, deliberately separate (plan section 6):
 *   - the caller invalidates on { kind, proposalId, layoutId, revision }
 *   - expansion is namespaced by { kind, proposalId, layoutId }
 * so an ordinary edit rebuilds rows without collapsing what the user opened,
 * while a preview keeps its own expanded set.
 *
 * Selection (FT3) is reported through onSelect and displayed from the
 * selection array handed to render(); the tree stores no selection of its own,
 * so the session stays the single source of truth in both directions.
 */
(function (root, factory) {
    'use strict';

    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityStructureTree = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const API_VERSION = 1;
    // The layout row stands for the document, which has no entity ID of
    // its own. A reserved constant keeps it out of any real ID's way.
    const LAYOUT_ROW_ID = '\u0000layout';

    function namespaceOf(view) {
        const source = view || {};
        return [
            source.kind || 'draft',
            source.proposalId || '',
            source.layoutId || '',
        ].join('\u0000');
    }

    function element(doc, tag, attributes, textContent) {
        const node = doc.createElement(tag);
        const attrs = attributes || {};
        Object.keys(attrs).forEach(function (key) {
            const value = attrs[key];
            if (value === null || value === undefined || value === false) return;
            if (key === 'className') node.className = value;
            else if (value === true) node.setAttribute(key, '');
            else node.setAttribute(key, String(value));
        });
        if (textContent !== undefined && textContent !== null) {
            node.textContent = String(textContent);
        }
        return node;
    }

    function clear(node) {
        while (node.firstChild) node.removeChild(node.firstChild);
    }

    /**
     * @param {object} options
     * @param {Document} options.document
     * @param {Element}  options.host        where rows are drawn
     * @param {function} [options.onSelect]  (rowKind, payload, event) where
     *        payload is { rowId, ids, additive }. `ids` carries every entity
     *        the row stands for - one for a zone or placement, all members for
     *        a group - so a group acts as a unit.
     * @param {function} [options.displayName] (assetId, revision) -> label
     */
    function createStructureTree(options) {
        const settings = options || {};
        const doc = settings.document;
        const host = settings.host;
        const onSelect = typeof settings.onSelect === 'function' ? settings.onSelect : null;
        const displayName = typeof settings.displayName === 'function'
            ? settings.displayName
            : function (assetId) { return assetId; };
        const onRename = typeof settings.onRename === 'function' ? settings.onRename : null;

        // expansion[namespace] = { rowId: true }
        const expansion = Object.create(null);
        let current = null;      // { model, view, readOnly, selection }
        let destroyed = false;
        // Rebuilt by every draw(): the row's own selectable entity IDs, so a
        // click resolves to IDs without re-deriving the model.
        let rowTargets = Object.create(null);
        let drawSelection = Object.create(null);
        // Ancestors are opened when the selection changes, not on every draw:
        // re-revealing would fight a user who collapsed a branch.
        let revealedKey = null;

        function expandedSet() {
            const key = namespaceOf(current && current.view);
            if (!expansion[key]) expansion[key] = Object.create(null);
            return expansion[key];
        }

        /**
         * @param {string} rowId
         * @param {boolean} [fallback] value when the user has never touched it
         */
        function isExpanded(rowId, fallback) {
            const set = expandedSet();
            if (Object.prototype.hasOwnProperty.call(set, rowId)) {
                return Boolean(set[rowId]);
            }
            return Boolean(fallback);
        }

        // A collapse is stored as false rather than deleted, so a row with a
        // default of open can tell "never touched" from "closed on purpose".
        function setExpanded(rowId, value) {
            expandedSet()[rowId] = Boolean(value);
        }

        function selectionSet() {
            const ids = (current && current.selection) || [];
            const set = Object.create(null);
            for (let index = 0; index < ids.length; index += 1) set[ids[index]] = true;
            return set;
        }

        /**
         * Selection state for a group row: every member, some, or none.
         * Partial is displayed, never produced by a group gesture.
         */
        function groupSelectionState(group, selected) {
            let hit = 0;
            for (let index = 0; index < group.placementIds.length; index += 1) {
                if (selected[group.placementIds[index]]) hit += 1;
            }
            if (hit === 0) return 'none';
            return hit === group.placementIds.length ? 'all' : 'partial';
        }

        /**
         * Open the path down to anything selected, so a canvas selection is
         * visible in the tree rather than hidden inside a collapsed branch.
         */
        function revealSelection() {
            const model = current && current.model;
            const selected = selectionSet();
            if (!model || !Object.keys(selected).length) return;
            const open = [];
            model.zoneOrder.forEach(function (zoneId) {
                const node = model.zones[zoneId];
                let wanted = Boolean(selected[zoneId]);
                if (!wanted) {
                    for (let index = 0; index < node.groups.length; index += 1) {
                        const group = node.groups[index];
                        if (groupSelectionState(group, selected) !== 'none') {
                            // Open the group too when only some members are hit,
                            // so the selected occurrence is actually reachable.
                            if (groupSelectionState(group, selected) === 'partial') {
                                open.push(group.rowId);
                            }
                            wanted = true;
                        }
                    }
                }
                if (!wanted) return;
                // Ancestors, not the row itself: a selected zone need not open.
                let cursor = selected[zoneId] ? node.parentZoneId : zoneId;
                while (cursor) {
                    open.push(cursor);
                    cursor = model.zones[cursor].parentZoneId;
                }
            });
            const unzoned = model.unzoned;
            if (unzoned) {
                unzoned.groups.forEach(function (group) {
                    if (groupSelectionState(group, selected) !== 'none') {
                        open.push(unzoned.rowId);
                    }
                });
            }
            open.forEach(function (rowId) { setExpanded(rowId, true); });
        }

        function rowNode(spec) {
            const row = element(doc, 'div', {
                className: 'ip-fst-row',
                role: 'treeitem',
                tabindex: '-1',
                'data-row-id': spec.rowId,
                'data-row-kind': spec.kind,
                'aria-level': String(spec.depth + 1),
                'aria-expanded': spec.expandable
                    ? (spec.expanded ? 'true' : 'false')
                    : null,
                'aria-selected': spec.selection === 'all' ? 'true' : 'false',
                'data-selection': spec.selection || 'none',
                style: '--ip-fst-depth:' + spec.depth,
            });

            const caret = element(doc, 'span', {
                className: 'ip-fst-caret',
                'data-caret': spec.expandable ? 'true' : 'false',
                'aria-hidden': 'true',
            }, spec.expandable ? (spec.expanded ? '\u25be' : '\u25b8') : '');
            row.appendChild(caret);

            row.appendChild(element(doc, 'span', {
                className: 'ip-fst-icon',
                'data-icon': spec.icon,
                'aria-hidden': 'true',
            }));

            row.appendChild(element(doc, 'span', {
                className: 'ip-fst-label',
                title: spec.label,
            }, spec.label));

            if (spec.meta) {
                row.appendChild(element(doc, 'span', {
                    className: 'ip-fst-meta',
                }, spec.meta));
            }
            return row;
        }

        function appendZone(zoneId, depth) {
            const model = current.model;
            const node = model.zones[zoneId];
            if (!node) return;
            const hasChildren = node.childZoneIds.length > 0 || node.groups.length > 0;
            const expanded = hasChildren && isExpanded(node.rowId);
            const row = rowNode({
                rowId: node.rowId,
                kind: 'zone',
                depth: depth,
                label: node.label,
                meta: node.totalCount ? String(node.totalCount) : '',
                icon: node.geometryValid ? 'zone' : 'zone-invalid',
                expandable: hasChildren,
                expanded: expanded,
                selection: drawSelection[zoneId] ? 'all' : 'none',
            });
            rowTargets[node.rowId] = [zoneId];
            if (!node.geometryValid) {
                // Rule 5: the failure is reported in place, not swallowed.
                row.setAttribute('data-geometry', 'invalid');
                row.setAttribute(
                    'title',
                    node.label + ' - zone geometry could not be evaluated'
                );
            }
            host.appendChild(row);

            // Lazy: descendants are only built once the branch is open.
            if (!expanded) return;
            node.childZoneIds.forEach(function (childId) {
                appendZone(childId, depth + 1);
            });
            node.groups.forEach(function (group) {
                appendGroup(group, depth + 1);
            });
        }

        function appendGroup(group, depth) {
            const count = group.placementIds.length;
            const expanded = count > 1 && isExpanded(group.rowId);
            const state = groupSelectionState(group, drawSelection);
            rowTargets[group.rowId] = group.placementIds.slice();
            host.appendChild(rowNode({
                rowId: group.rowId,
                kind: 'group',
                depth: depth,
                label: displayName(group.assetId, group.assetDefinitionRevision),
                meta: count > 1 ? '\u00d7' + count : '',
                icon: 'asset',
                expandable: count > 1,
                expanded: expanded,
                // 'partial' is displayed, never produced by a group gesture:
                // it appears when members are selected one at a time or on
                // the canvas.
                selection: state === 'all' ? 'all' : (state === 'partial' ? 'partial' : 'none'),
            }));
            if (!expanded) return;
            group.placementIds.forEach(function (placementId, index) {
                rowTargets[placementId] = [placementId];
                host.appendChild(rowNode({
                    rowId: placementId,
                    kind: 'placement',
                    depth: depth + 1,
                    label: displayName(group.assetId, group.assetDefinitionRevision)
                        + ' ' + (index + 1),
                    meta: '',
                    icon: 'placement',
                    expandable: false,
                    expanded: false,
                    selection: drawSelection[placementId] ? 'all' : 'none',
                }));
            });
        }

        function appendUnzoned(depth) {
            const unzoned = current.model.unzoned;
            if (!unzoned || unzoned.directCount === 0) return;
            const expanded = isExpanded(unzoned.rowId);
            const row = rowNode({
                rowId: unzoned.rowId,
                kind: 'unzoned',
                depth: depth,
                label: 'Unzoned',
                meta: String(unzoned.directCount),
                icon: 'unzoned',
                expandable: true,
                expanded: expanded,
            });
            // Not an error: placing before a zone exists is ordinary authoring.
            row.setAttribute('data-tone', 'notice');
            host.appendChild(row);
            if (!expanded) return;
            unzoned.groups.forEach(function (group) {
                appendGroup(group, depth + 1);
            });
        }

        /**
         * The layout document itself, as the single root every zone hangs
         * under. It is not a derived fact - the derivation only knows geometry
         * - so it is drawn from the view descriptor.
         *
         * Open unless the user has closed it: a tree whose only visible row is
         * the layout name would be useless on arrival.
         */
        function appendLayout() {
            const model = current.model;
            const label = (current.view && current.view.displayName) || 'Facility layout';
            const total = model.counts ? model.counts.placements : 0;
            const expanded = isExpanded(LAYOUT_ROW_ID, true);
            const row = rowNode({
                rowId: LAYOUT_ROW_ID,
                kind: 'layout',
                depth: 0,
                label: label,
                meta: total ? String(total) : '',
                icon: 'layout',
                expandable: true,
                expanded: expanded,
            });
            if (onRename && !(current && current.readOnly)) {
                row.setAttribute('data-editable', 'true');
                row.setAttribute('title', label + ' - double-click to rename');
            }
            host.appendChild(row);
            if (!expanded) return;
            model.roots.forEach(function (zoneId) { appendZone(zoneId, 1); });
            appendUnzoned(1);
        }

        /**
         * Inline rename of the layout row. Enter commits, Escape cancels, and
         * losing focus commits, which is what a text field in a tree is
         * expected to do. The tree does not apply the new name itself: it asks
         * the host, and redraws when the session comes back round.
         */
        function beginRename(row) {
            if (!onRename || (current && current.readOnly)) return;
            if (row.querySelector('.ip-fst-rename')) return;
            const labelNode = row.querySelector('.ip-fst-label');
            if (!labelNode) return;
            const original = labelNode.textContent;
            const input = element(doc, 'input', {
                className: 'ip-fst-rename',
                type: 'text',
                'aria-label': 'Facility layout name',
            });
            input.value = original;
            row.replaceChild(input, labelNode);
            input.focus();
            if (typeof input.select === 'function') input.select();

            let settled = false;
            const finish = function (commit) {
                if (settled) return;
                settled = true;
                const next = String(input.value || '').trim();
                if (commit && next && next !== original) onRename(next);
                else draw();
            };
            input.addEventListener('keydown', function (event) {
                if (event.key === 'Enter') { finish(true); }
                else if (event.key === 'Escape') { finish(false); }
                else { return; }
                if (typeof event.stopPropagation === 'function') event.stopPropagation();
                if (typeof event.preventDefault === 'function') event.preventDefault();
            });
            input.addEventListener('blur', function () { finish(true); });
        }

        function draw() {
            if (destroyed || !current) return;
            const focusedRowId = (function () {
                const active = doc.activeElement;
                if (!active || !host.contains(active)) return null;
                return active.getAttribute('data-row-id');
            }());

            clear(host);
            rowTargets = Object.create(null);
            drawSelection = selectionSet();
            const key = namespaceOf(current.view) + ''
                + Object.keys(drawSelection).sort().join('');
            if (key !== revealedKey) {
                revealSelection();
                revealedKey = key;
            }
            const model = current.model;
            if (!model) return;
            // The layout row is drawn even when the layout is empty, so its
            // name is always present and always renameable.
            appendLayout();
            if (model.counts.zones === 0 && model.counts.placements === 0) {
                host.appendChild(element(doc, 'div', {
                    className: 'ip-fst-empty',
                }, 'No zones or equipment yet. Draw a zone or place equipment to see it here.'));
            }

            // Focus survives a rebuild when its row still exists (FT5 requirement).
            if (focusedRowId) {
                const again = host.querySelector(
                    '[data-row-id="' + cssEscape(focusedRowId) + '"]'
                );
                if (again) again.focus();
            }
        }

        function cssEscape(value) {
            return String(value).replace(/["\\]/g, '\\$&');
        }

        function rowFromEvent(event) {
            let node = event.target;
            while (node && node !== host) {
                if (node.getAttribute && node.getAttribute('data-row-id') !== null) return node;
                node = node.parentNode;
            }
            return null;
        }

        function handleClick(event) {
            const row = rowFromEvent(event);
            if (!row) return;
            const rowId = row.getAttribute('data-row-id');
            const kind = row.getAttribute('data-row-kind');
            const onCaret = Boolean(
                event.target.getAttribute
                && event.target.getAttribute('data-caret') === 'true'
            );
            // The caret expands; the label selects (plan section 3a).
            if (onCaret) {
                if (row.getAttribute('aria-expanded') !== null) {
                    setExpanded(rowId, row.getAttribute('aria-expanded') !== 'true');
                    draw();
                }
                return;
            }
            if (current && current.readOnly) return;
            if (!onSelect) return;
            const ids = rowTargets[rowId];
            // 'unzoned' is a scope header, not an entity: nothing to select.
            if (!ids || !ids.length) return;
            onSelect(kind, {
                rowId: rowId,
                ids: ids.slice(),
                // Ctrl/Meta toggles. Shift is left to the canvas; the tree has
                // no range gesture yet.
                additive: Boolean(event.ctrlKey || event.metaKey),
            }, event);
        }

        function handleDoubleClick(event) {
            const row = rowFromEvent(event);
            if (!row || row.getAttribute('data-row-kind') !== 'layout') return;
            beginRename(row);
        }

        function handleKeydown(event) {
            const row = rowFromEvent(event);
            if (!row) return;
            const rows = Array.prototype.slice.call(
                host.querySelectorAll('.ip-fst-row')
            );
            const index = rows.indexOf(row);
            const rowId = row.getAttribute('data-row-id');
            const expandable = row.getAttribute('aria-expanded') !== null;
            const expanded = row.getAttribute('aria-expanded') === 'true';

            if (event.key === 'ArrowDown' && index < rows.length - 1) {
                rows[index + 1].focus();
            } else if (event.key === 'ArrowUp' && index > 0) {
                rows[index - 1].focus();
            } else if (event.key === 'ArrowRight' && expandable && !expanded) {
                setExpanded(rowId, true);
                draw();
            } else if (event.key === 'ArrowLeft' && expandable && expanded) {
                setExpanded(rowId, false);
                draw();
            } else if (event.key === 'F2' && row.getAttribute('data-row-kind') === 'layout') {
                beginRename(row);
            } else if (event.key === 'Enter' && row.getAttribute('data-row-kind') === 'layout') {
                beginRename(row);
            } else if (event.key === 'Enter' || event.key === ' ') {
                const ids = rowTargets[rowId];
                if (ids && ids.length && onSelect && !(current && current.readOnly)) {
                    onSelect(row.getAttribute('data-row-kind'), {
                        rowId: rowId,
                        ids: ids.slice(),
                        additive: Boolean(event.ctrlKey || event.metaKey),
                    }, event);
                } else if (expandable) {
                    // Nothing to select (the Unzoned header): fall back to
                    // opening the branch so the key is never inert.
                    setExpanded(rowId, !expanded);
                    draw();
                }
            } else {
                return;
            }
            if (typeof event.preventDefault === 'function') event.preventDefault();
        }

        host.setAttribute('role', 'tree');
        host.setAttribute('aria-label', 'Facility layout structure');
        host.addEventListener('click', handleClick);
        host.addEventListener('dblclick', handleDoubleClick);
        host.addEventListener('keydown', handleKeydown);

        return {
            API_VERSION: API_VERSION,

            /** @param {object} next { model, view, readOnly, selection }
             *  `selection` is the session's selected entity IDs. */
            render: function (next) {
                if (destroyed) return;
                current = next || null;
                draw();
            },

            /** Expansion for the current view; exposed for tests. */
            expandedRowIds: function () {
                const set = expandedSet();
                return Object.keys(set).filter(function (rowId) {
                    return set[rowId] === true;
                }).sort();
            },

            /** Test-only. Requires a prior render: expansion is namespaced by
             *  the current view, so setting it before one exists would file it
             *  under a namespace no later render reads. Loud rather than
             *  silent, because that failure looks like "the tree ignored me". */
            setExpandedForTest: function (rowId, value) {
                if (!current) {
                    throw new Error(
                        'setExpandedForTest requires a prior render(): expansion '
                        + 'is namespaced by the current view'
                    );
                }
                setExpanded(rowId, value);
            },

            namespaceKey: function (view) {
                return namespaceOf(view || (current && current.view));
            },

            destroy: function () {
                if (destroyed) return;
                destroyed = true;
                host.removeEventListener('click', handleClick);
                host.removeEventListener('dblclick', handleDoubleClick);
                host.removeEventListener('keydown', handleKeydown);
                clear(host);
            },
        };
    }

    return {
        API_VERSION: API_VERSION,
        LAYOUT_ROW_ID: LAYOUT_ROW_ID,
        createStructureTree: createStructureTree,
        namespaceOf: namespaceOf,
    };
}));
