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
 * FT2 scope: read-only. Selection arrives in FT3 through onSelect.
 */
(function (root, factory) {
    'use strict';

    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityStructureTree = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const API_VERSION = 1;

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
     * @param {function} [options.onSelect]  FT3; (rowKind, payload, event)
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

        // expansion[namespace] = { rowId: true }
        const expansion = Object.create(null);
        let current = null;      // { model, view, readOnly }
        let destroyed = false;

        function expandedSet() {
            const key = namespaceOf(current && current.view);
            if (!expansion[key]) expansion[key] = Object.create(null);
            return expansion[key];
        }

        function isExpanded(rowId) {
            return Boolean(expandedSet()[rowId]);
        }

        function setExpanded(rowId, value) {
            const set = expandedSet();
            if (value) set[rowId] = true;
            else delete set[rowId];
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
            });
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
            host.appendChild(rowNode({
                rowId: group.rowId,
                kind: 'group',
                depth: depth,
                label: displayName(group.assetId, group.assetDefinitionRevision),
                meta: count > 1 ? '\u00d7' + count : '',
                icon: 'asset',
                expandable: count > 1,
                expanded: expanded,
            }));
            if (!expanded) return;
            group.placementIds.forEach(function (placementId, index) {
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
                }));
            });
        }

        function appendUnzoned() {
            const unzoned = current.model.unzoned;
            if (!unzoned || unzoned.directCount === 0) return;
            const expanded = isExpanded(unzoned.rowId);
            const row = rowNode({
                rowId: unzoned.rowId,
                kind: 'unzoned',
                depth: 0,
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
                appendGroup(group, 1);
            });
        }

        function draw() {
            if (destroyed || !current) return;
            const focusedRowId = (function () {
                const active = doc.activeElement;
                if (!active || !host.contains(active)) return null;
                return active.getAttribute('data-row-id');
            }());

            clear(host);
            const model = current.model;
            if (!model || model.counts.zones === 0 && model.counts.placements === 0) {
                host.appendChild(element(doc, 'div', {
                    className: 'ip-fst-empty',
                }, 'No zones or equipment yet. Draw a zone or place equipment to see it here.'));
                return;
            }
            model.roots.forEach(function (zoneId) { appendZone(zoneId, 0); });
            appendUnzoned();

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
            if (onSelect) onSelect(kind, rowId, event);
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
            } else if (event.key === 'Enter' || event.key === ' ') {
                if (expandable) {
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
        host.addEventListener('keydown', handleKeydown);

        return {
            API_VERSION: API_VERSION,

            /** @param {object} next { model, view, readOnly } */
            render: function (next) {
                if (destroyed) return;
                current = next || null;
                draw();
            },

            /** Expansion for the current view; exposed for tests. */
            expandedRowIds: function () {
                return Object.keys(expandedSet()).sort();
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
                host.removeEventListener('keydown', handleKeydown);
                clear(host);
            },
        };
    }

    return {
        API_VERSION: API_VERSION,
        createStructureTree: createStructureTree,
        namespaceOf: namespaceOf,
    };
}));
