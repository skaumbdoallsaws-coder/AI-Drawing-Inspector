(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProChatRichContent = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
    'use strict';

    const BLOCK_TYPES = new Set([
        'markdown',
        'sources',
        'facts',
        'visualization',
        'table',
        'entity_reference',
        'actions',
    ]);
    const SOURCE_TYPES = new Set([
        'manufacturer',
        'supplier',
        'standard',
        'technical-document',
        'web',
    ]);
    const VISUALIZATION_TYPES = new Set([
        'bar',
        'donut',
        'heatmap',
        'line',
        'scatter',
        'histogram',
        'pareto',
        'pie',
        'kpi',
    ]);
    const ACTION_IDS = new Set([
        'highlight_asset',
        'locate_in_plan',
        'show_in_3d',
        'open_drawing',
        'open_inspection',
        'open_process_map',
        'highlight_feature',
    ]);

    const REGISTERED_SOURCE_IDENTITIES = Object.freeze({
        'skf.com': { publisher: 'SKF', accent: '#005eb8' },
        'mcmaster.com': { publisher: 'McMaster-Carr', accent: '#d71920' },
        'misumi-ec.com': { publisher: 'MISUMI', accent: '#0068b7' },
        'misumiusa.com': { publisher: 'MISUMI', accent: '#0068b7' },
        'grainger.com': { publisher: 'Grainger', accent: '#c8102e' },
        'siemens.com': { publisher: 'Siemens', accent: '#009999' },
        'festo.com': { publisher: 'Festo', accent: '#0066b3' },
        'smcworld.com': { publisher: 'SMC', accent: '#005bac' },
        'traceparts.com': { publisher: 'TraceParts', accent: '#e6501e' },
        '3dcontentcentral.com': { publisher: '3D ContentCentral', accent: '#e31837' },
    });
    const sourceIdentityCache = new Map();

    function cleanText(value, maximum) {
        return String(value == null ? '' : value).trim().slice(0, maximum || 4000);
    }

    function formatEngineeringText(value) {
        const superscript = { 2: '\u00B2', 3: '\u00B3' };
        return String(value == null ? '' : value).replace(
            /\b(mm|cm|km|in|ft|yd|m)\s*\^\s*([23])\b/gi,
            (_, unit, exponent) => unit + superscript[exponent]
        );
    }

    function formatEngineeringUnit(value) {
        const superscript = { 2: '\u00B2', 3: '\u00B3' };
        let unit = formatEngineeringText(cleanText(value, 80));
        unit = unit.replace(
            /^(mm|cm|km|in|ft|yd|m)([23])$/i,
            (_, base, exponent) => base + superscript[exponent]
        );
        return unit.replace(
            /\/(mm|cm|km|in|ft|yd|m)([23])\b/gi,
            (_, base, exponent) => '/' + base + superscript[exponent]
        );
    }

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function safeUrl(value, baseOrigin) {
        const input = cleanText(value, 2048);
        if (!input) return null;
        if (/^(?:\/|#)/.test(input) && !/^\/\//.test(input)) return input;
        if (!/^[A-Za-z][A-Za-z0-9+.-]*:/.test(input)) return null;
        try {
            const base = baseOrigin || 'http://localhost/';
            const parsed = new URL(input, base);
            if (!['http:', 'https:', 'mailto:'].includes(parsed.protocol)) return null;
            return parsed.href;
        } catch (_) {
            return null;
        }
    }

    function sourceIdentity(domain, sourceUrl, explicitIconUrl) {
        const cleanDomain = cleanText(domain || sourceDomain(sourceUrl), 160).toLowerCase();
        const explicit = safeUrl(explicitIconUrl || '');
        const cacheKey = cleanDomain + '|' + String(explicit || '');
        if (sourceIdentityCache.has(cacheKey)) return sourceIdentityCache.get(cacheKey);
        const registeredKey = Object.keys(REGISTERED_SOURCE_IDENTITIES).find(key => (
            cleanDomain === key || cleanDomain.endsWith('.' + key)
        ));
        const registered = registeredKey
            ? REGISTERED_SOURCE_IDENTITIES[registeredKey] : null;
        let faviconUrl = explicit;
        if (!faviconUrl && cleanDomain) {
            faviconUrl = 'https://' + cleanDomain + '/favicon.ico';
        }
        const identity = Object.freeze({
            publisher: registered ? registered.publisher : '',
            accent: registered ? registered.accent : '',
            iconUrl: faviconUrl,
        });
        sourceIdentityCache.set(cacheKey, identity);
        return identity;
    }

    function sourceDomain(value) {
        const url = safeUrl(value);
        if (!url || /^(?:\/|#)/.test(url)) return '';
        try {
            return new URL(url).hostname.replace(/^www\./i, '').toLowerCase();
        } catch (_) {
            return '';
        }
    }

    function renderInline(input) {
        const value = String(input == null ? '' : input);
        let output = '';
        let index = 0;
        while (index < value.length) {
            if (value[index] === '`') {
                const end = value.indexOf('`', index + 1);
                if (end > index + 1) {
                    output += '<code>' + escapeHtml(value.slice(index + 1, end)) + '</code>';
                    index = end + 1;
                    continue;
                }
            }
            if (value[index] === '[') {
                const match = value.slice(index).match(/^\[([^\]]+)\]\(([^)]+)\)/);
                if (match) {
                    const href = safeUrl(match[2]);
                    if (href) {
                        const external = /^https?:/i.test(href);
                        output += '<a href="' + escapeHtml(href) + '"'
                            + (external ? ' target="_blank" rel="noopener noreferrer"' : '')
                            + '>' + renderInline(match[1]) + '</a>';
                    } else {
                        output += renderInline(match[1]);
                    }
                    index += match[0].length;
                    continue;
                }
            }
            if (value.slice(index, index + 2) === '**') {
                const end = value.indexOf('**', index + 2);
                if (end > index + 2) {
                    output += '<strong>' + renderInline(value.slice(index + 2, end)) + '</strong>';
                    index = end + 2;
                    continue;
                }
            }
            if (value[index] === '*' || value[index] === '_') {
                const marker = value[index];
                const end = value.indexOf(marker, index + 1);
                const prior = index > 0 ? value[index - 1] : ' ';
                const next = index + 1 < value.length ? value[index + 1] : ' ';
                if (end > index + 1 && !(marker === '_' && /\w/.test(prior + next))) {
                    output += '<em>' + renderInline(value.slice(index + 1, end)) + '</em>';
                    index = end + 1;
                    continue;
                }
            }
            const nextSpecial = value.slice(index + 1).search(/[`[*_]/);
            const end = nextSpecial < 0 ? value.length : index + nextSpecial + 1;
            output += escapeHtml(formatEngineeringText(value.slice(index, end)));
            index = end;
        }
        return output;
    }

    function splitTableRow(line) {
        return String(line || '')
            .trim()
            .replace(/^\||\|$/g, '')
            .split('|')
            .map(cell => cell.trim());
    }

    function isTableDivider(line) {
        const cells = splitTableRow(line);
        return cells.length > 0 && cells.every(cell => /^:?-{3,}:?$/.test(cell));
    }

    function startsBlock(lines, index) {
        const line = lines[index] || '';
        if (!line.trim()) return true;
        if (/^\s*```/.test(line)) return true;
        if (/^#{1,4}\s+/.test(line)) return true;
        if (/^\s*>\s?/.test(line)) return true;
        if (/^\s*(?:[-+*]\s+|\d+[.)]\s+)/.test(line)) return true;
        if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) return true;
        return index + 1 < lines.length && line.includes('|') && isTableDivider(lines[index + 1]);
    }

    function renderMarkdownHtml(markdown) {
        const lines = String(markdown == null ? '' : markdown)
            .replace(/\r\n?/g, '\n')
            .split('\n');
        const output = [];
        let index = 0;
        while (index < lines.length) {
            const line = lines[index];
            if (!line.trim()) {
                index += 1;
                continue;
            }
            const fence = line.match(/^\s*```\s*([A-Za-z0-9_-]{0,32})\s*$/);
            if (fence) {
                const code = [];
                index += 1;
                while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) {
                    code.push(lines[index]);
                    index += 1;
                }
                if (index < lines.length) index += 1;
                const language = fence[1] ? ' class="language-' + escapeHtml(fence[1]) + '"' : '';
                output.push('<pre><code' + language + '>' + escapeHtml(code.join('\n')) + '</code></pre>');
                continue;
            }
            const heading = line.match(/^(#{1,4})\s+(.+)$/);
            if (heading) {
                const level = heading[1].length;
                output.push('<h' + level + '>' + renderInline(heading[2]) + '</h' + level + '>');
                index += 1;
                continue;
            }
            if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
                output.push('<hr>');
                index += 1;
                continue;
            }
            if (/^\s*>\s?/.test(line)) {
                const quoted = [];
                while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
                    quoted.push(lines[index].replace(/^\s*>\s?/, ''));
                    index += 1;
                }
                output.push('<blockquote>' + renderMarkdownHtml(quoted.join('\n')) + '</blockquote>');
                continue;
            }
            if (index + 1 < lines.length && line.includes('|') && isTableDivider(lines[index + 1])) {
                const headers = splitTableRow(line);
                const rows = [];
                index += 2;
                while (index < lines.length && lines[index].includes('|') && lines[index].trim()) {
                    rows.push(splitTableRow(lines[index]));
                    index += 1;
                }
                output.push('<div class="agent-markdown-table-wrap"><table><thead><tr>'
                    + headers.map(cell => '<th>' + renderInline(cell) + '</th>').join('')
                    + '</tr></thead><tbody>'
                    + rows.map(row => '<tr>' + headers.map((_, cellIndex) => (
                        '<td>' + renderInline(row[cellIndex] || '') + '</td>'
                    )).join('') + '</tr>').join('')
                    + '</tbody></table></div>');
                continue;
            }
            const listMatch = line.match(/^\s*(?:(- |\+ |\* )|(\d+)[.)]\s+)(.+)$/);
            if (listMatch) {
                const ordered = !!listMatch[2];
                const items = [];
                const pattern = ordered
                    ? /^\s*\d+[.)]\s+(.+)$/
                    : /^\s*[-+*]\s+(.+)$/;
                while (index < lines.length) {
                    const item = lines[index].match(pattern);
                    if (!item) break;
                    items.push(item[1]);
                    index += 1;
                }
                const tag = ordered ? 'ol' : 'ul';
                output.push('<' + tag + '>'
                    + items.map(item => '<li>' + renderInline(item) + '</li>').join('')
                    + '</' + tag + '>');
                continue;
            }
            const paragraph = [line];
            index += 1;
            while (index < lines.length && !startsBlock(lines, index)) {
                paragraph.push(lines[index]);
                index += 1;
            }
            output.push('<p>' + paragraph.map(renderInline).join('<br>') + '</p>');
        }
        return output.join('');
    }

    function primitive(value) {
        return value == null || ['string', 'number', 'boolean'].includes(typeof value);
    }

    function normalizeSource(raw, index) {
        if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
        const url = safeUrl(raw.url || raw.sourceUrl);
        if (!url) return null;
        const links = Array.isArray(raw.links) ? raw.links.slice(0, 4).map(link => {
            if (!link || typeof link !== 'object') return null;
            const linkUrl = safeUrl(link.url);
            if (!linkUrl) return null;
            return {
                label: cleanText(link.label || 'Open', 60),
                url: linkUrl,
                kind: cleanText(link.kind || 'source', 32),
            };
        }).filter(Boolean) : [];
        const specs = {};
        if (raw.specifications && typeof raw.specifications === 'object') {
            Object.entries(raw.specifications).slice(0, 8).forEach(([key, value]) => {
                if (primitive(value)) specs[cleanText(key, 80)] = cleanText(value, 160);
            });
        }
        const sourceType = SOURCE_TYPES.has(raw.sourceType) ? raw.sourceType : 'web';
        const domain = cleanText(raw.domain || sourceDomain(url), 160);
        const inferIdentity = raw.inferIdentity !== false;
        const identity = inferIdentity ? sourceIdentity(domain, url, raw.iconUrl || raw.favicon || '')
            : { publisher: '', iconUrl: safeUrl(raw.iconUrl || raw.favicon), accent: '' };
        return {
            id: cleanText(raw.id || ('source_' + (index + 1)), 120),
            title: cleanText(raw.title || raw.name || url, 240),
            url,
            domain,
            publisher: cleanText(
                raw.publisher || raw.supplier || raw.manufacturer || identity.publisher || '',
                160
            ),
            sourceType,
            inferIdentity,
            retrievedAt: cleanText(raw.retrievedAt || '', 64),
            description: cleanText(raw.description || '', 500),
            partNumber: cleanText(raw.partNumber || raw.part_number || raw.sku || '', 120),
            price: cleanText(raw.price || '', 80),
            availability: cleanText(raw.availability || '', 80),
            iconUrl: identity.iconUrl,
            accent: identity.accent,
            specifications: specs,
            links,
        };
    }

    function normalizeAction(raw) {
        if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
        const actionId = cleanText(raw.actionId || raw.action_id, 80);
        if (!ACTION_IDS.has(actionId)) return null;
        const entityId = cleanText(raw.entityId || raw.entity_id || '', 160);
        const entityType = cleanText(raw.entityType || raw.entity_type || '', 80);
        if (!entityId && actionId !== 'open_drawing' && actionId !== 'open_inspection') return null;
        return {
            actionId,
            label: cleanText(raw.label || actionId.replace(/_/g, ' '), 80),
            entityId,
            entityType,
        };
    }

    function normalizeVisualization(raw) {
        if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
        const type = cleanText(raw.type, 32).toLowerCase();
        if (!VISUALIZATION_TYPES.has(type)) return null;
        const encoding = raw.encoding && typeof raw.encoding === 'object'
            ? raw.encoding : {};
        const data = Array.isArray(raw.data) ? raw.data.slice(0, 200).map(row => {
            if (!row || typeof row !== 'object' || Array.isArray(row)) return null;
            const cleaned = {};
            Object.entries(row).slice(0, 20).forEach(([key, value]) => {
                if (primitive(value)) cleaned[cleanText(key, 80)] = value;
            });
            return cleaned;
        }).filter(Boolean) : [];
        if (!data.length) return null;
        const options = raw.options && typeof raw.options === 'object'
            ? raw.options : {};
        const optionalBoolean = key => typeof options[key] === 'boolean'
            ? options[key] : null;
        return {
            type,
            title: formatEngineeringText(cleanText(raw.title || '', 160)),
            subtitle: formatEngineeringText(cleanText(raw.subtitle || '', 240)),
            data,
            encoding: {
                x: cleanText(encoding.x || encoding.label || '', 80),
                y: cleanText(encoding.y || encoding.value || '', 80),
                color: cleanText(encoding.color || '', 80),
                entityId: cleanText(encoding.entityId || encoding.entity_id || '', 80),
            },
            options: {
                showValues: optionalBoolean('showValues'),
                showPercentages: optionalBoolean('showPercentages'),
                showLegend: optionalBoolean('showLegend'),
            },
            unit: formatEngineeringUnit(raw.unit || ''),
        };
    }

    function normalizeTable(raw) {
        if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
        const columns = (Array.isArray(raw.columns) ? raw.columns : [])
            .slice(0, 12)
            .map(column => {
                if (!column || typeof column !== 'object') return null;
                const label = cleanText(column.label, 120);
                return label ? {
                    label,
                    unit: formatEngineeringUnit(column.unit || ''),
                } : null;
            })
            .filter(Boolean);
        if (!columns.length) return null;
        const rows = (Array.isArray(raw.rows) ? raw.rows : [])
            .slice(0, 200)
            .map(row => {
                if (!row || typeof row !== 'object' || !Array.isArray(row.cells)) {
                    return null;
                }
                const cells = row.cells.slice(0, columns.length)
                    .map(value => cleanText(value, 240));
                while (cells.length < columns.length) cells.push('');
                return {
                    cells,
                    entityId: cleanText(row.entityId || row.entity_id || '', 160),
                };
            })
            .filter(Boolean);
        if (!rows.length) return null;
        return {
            title: cleanText(raw.title || '', 160),
            subtitle: cleanText(raw.subtitle || '', 240),
            columns,
            rows,
        };
    }

    function normalizeBlock(raw) {
        if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
        const type = cleanText(raw.type, 40).toLowerCase();
        if (!BLOCK_TYPES.has(type)) return null;
        if (type === 'markdown') {
            const text = cleanText(raw.text, 50000);
            return text ? { type, text } : null;
        }
        if (type === 'sources') {
            const sources = (Array.isArray(raw.sources) ? raw.sources : [])
                .slice(0, 20)
                .map(normalizeSource)
                .filter(Boolean);
            return sources.length ? {
                type,
                title: cleanText(raw.title || 'Sources', 120),
                sources,
            } : null;
        }
        if (type === 'facts') {
            const facts = (Array.isArray(raw.facts) ? raw.facts : [])
                .slice(0, 40)
                .map(item => {
                    if (!item || typeof item !== 'object') return null;
                    const label = cleanText(item.label, 120);
                    const value = cleanText(item.value, 240);
                    if (!label || !value) return null;
                    const provenance = ['source', 'derived', 'agent'].includes(item.provenance)
                        ? item.provenance : 'agent';
                    return {
                        label,
                        value: formatEngineeringText(value),
                        unit: formatEngineeringUnit(item.unit || ''),
                        sourceId: cleanText(item.sourceId || item.source_id || '', 120),
                        provenance,
                    };
                })
                .filter(Boolean);
            return facts.length ? {
                type,
                title: cleanText(raw.title || 'Evidence', 120),
                facts,
            } : null;
        }
        if (type === 'visualization') {
            const spec = normalizeVisualization(raw.spec || raw.visualization || raw);
            return spec ? { type, spec } : null;
        }
        if (type === 'table') {
            const table = normalizeTable(raw.table || raw);
            return table ? { type, table } : null;
        }
        if (type === 'entity_reference') {
            const entity = raw.entity && typeof raw.entity === 'object' ? raw.entity : raw;
            const entityId = cleanText(entity.id || entity.entityId || entity.entity_id || '', 160);
            const label = cleanText(entity.label || entity.name || '', 180);
            if (!entityId || !label) return null;
            return {
                type,
                entity: {
                    id: entityId,
                    entityType: cleanText(entity.entityType || entity.entity_type || 'entity', 80),
                    label,
                    subtitle: cleanText(entity.subtitle || '', 240),
                },
                actions: (Array.isArray(raw.actions) ? raw.actions : [])
                    .slice(0, 6).map(normalizeAction).filter(Boolean),
            };
        }
        const actions = (Array.isArray(raw.actions) ? raw.actions : [])
            .slice(0, 8).map(normalizeAction).filter(Boolean);
        return actions.length ? { type: 'actions', actions } : null;
    }

    function normalizeBlocks(value) {
        return (Array.isArray(value) ? value : [])
            .slice(0, 24)
            .map(normalizeBlock)
            .filter(Boolean);
    }

    function element(documentRef, tag, className, text) {
        const node = documentRef.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function initials(source) {
        const value = cleanText(source.publisher || source.domain || source.title || '?', 80);
        return value.split(/\s+/).filter(Boolean).slice(0, 2)
            .map(token => token[0].toUpperCase()).join('') || '?';
    }

    function appendActionButtons(documentRef, parent, actions, options) {
        if (!actions.length) return;
        const wrap = element(documentRef, 'div', 'agent-rich-actions');
        actions.forEach(action => {
            const button = element(documentRef, 'button', 'agent-rich-action', action.label);
            button.type = 'button';
            button.dataset.chatAction = action.actionId;
            button.addEventListener('click', () => {
                if (options && typeof options.onAction === 'function') {
                    options.onAction(action);
                }
            });
            wrap.appendChild(button);
        });
        parent.appendChild(wrap);
    }

    function renderSources(documentRef, block) {
        const section = element(documentRef, 'section', 'agent-rich-block agent-source-block');
        const heading = element(documentRef, 'div', 'agent-rich-block-title');
        heading.appendChild(element(documentRef, 'span', '', block.title));
        heading.appendChild(element(documentRef, 'span', 'agent-rich-count', String(block.sources.length)));
        section.appendChild(heading);
        const list = element(documentRef, 'div', 'agent-source-list');
        block.sources.forEach(source => {
            const card = element(documentRef, 'article', 'agent-source-card');
            const identity = element(documentRef, 'div', 'agent-source-identity', initials(source));
            if (source.accent) identity.style.setProperty('--source-accent', source.accent);
            if (source.iconUrl) {
                const image = documentRef.createElement('img');
                image.src = source.iconUrl;
                image.alt = '';
                image.loading = 'lazy';
                image.referrerPolicy = 'no-referrer';
                image.hidden = true;
                image.addEventListener('load', () => { image.hidden = false; });
                image.addEventListener('error', () => image.remove());
                identity.appendChild(image);
            }
            card.appendChild(identity);
            const body = element(documentRef, 'div', 'agent-source-body');
            const overline = element(documentRef, 'div', 'agent-source-overline');
            overline.appendChild(element(documentRef, 'span', '', source.publisher || source.domain));
            overline.appendChild(element(documentRef, 'span', 'agent-source-type', source.sourceType.replace(/-/g, ' ')));
            body.appendChild(overline);
            const title = documentRef.createElement('a');
            title.className = 'agent-source-title';
            title.textContent = source.title;
            title.href = source.url;
            title.target = '_blank';
            title.rel = 'noopener noreferrer';
            body.appendChild(title);
            const meta = [source.partNumber, source.price, source.availability].filter(Boolean);
            if (meta.length) body.appendChild(element(documentRef, 'div', 'agent-source-meta', meta.join(' | ')));
            const specEntries = Object.entries(source.specifications || {}).slice(0, 4);
            if (specEntries.length) {
                const specs = element(documentRef, 'dl', 'agent-source-specs');
                specEntries.forEach(([key, value]) => {
                    specs.appendChild(element(documentRef, 'dt', '', key));
                    specs.appendChild(element(documentRef, 'dd', '', value));
                });
                body.appendChild(specs);
            }
            const links = [{ label: 'View source', url: source.url }, ...source.links].slice(0, 4);
            const actions = element(documentRef, 'div', 'agent-source-links');
            links.forEach(link => {
                const anchor = element(documentRef, 'a', '', link.label);
                anchor.href = link.url;
                anchor.target = '_blank';
                anchor.rel = 'noopener noreferrer';
                actions.appendChild(anchor);
            });
            body.appendChild(actions);
            card.appendChild(body);
            list.appendChild(card);
        });
        section.appendChild(list);
        return section;
    }

    function renderFacts(documentRef, block) {
        const section = element(documentRef, 'section', 'agent-rich-block agent-facts-block');
        section.appendChild(element(documentRef, 'div', 'agent-rich-block-title', block.title));
        const table = element(documentRef, 'div', 'agent-facts-table');
        block.facts.forEach(fact => {
            const row = element(documentRef, 'div', 'agent-fact-row');
            row.appendChild(element(documentRef, 'div', 'agent-fact-label', fact.label));
            const value = element(documentRef, 'div', 'agent-fact-value', fact.value + (fact.unit ? ' ' + fact.unit : ''));
            const badge = element(documentRef, 'span', 'agent-provenance-badge is-' + fact.provenance,
                fact.sourceId || fact.provenance);
            value.appendChild(badge);
            row.appendChild(value);
            table.appendChild(row);
        });
        section.appendChild(table);
        return section;
    }

    function chartFields(spec) {
        const first = spec.data[0] || {};
        const keys = Object.keys(first);
        const numeric = keys.filter(key => spec.data.some(row => Number.isFinite(Number(row[key]))));
        return {
            x: spec.encoding.x || keys.find(key => !numeric.includes(key)) || keys[0],
            y: spec.encoding.y || numeric[0] || keys[1] || keys[0],
            color: spec.encoding.color || 'series',
            entityId: spec.encoding.entityId || 'entityId',
        };
    }

    function paretoCumulativeRatios(values) {
        const normalized = (Array.isArray(values) ? values : []).map(value => {
            const numeric = Number(value);
            return Number.isFinite(numeric) ? Math.max(0, numeric) : 0;
        });
        const total = normalized.reduce((sum, value) => sum + value, 0);
        if (total <= 0) return normalized.map(() => 0);
        let cumulative = 0;
        return normalized.map(value => {
            cumulative += value;
            return cumulative / total;
        });
    }

    function pieSliceRatios(values) {
        const normalized = (Array.isArray(values) ? values : []).map(value => {
            const numeric = Number(value);
            return Number.isFinite(numeric) ? Math.max(0, numeric) : 0;
        });
        const total = normalized.reduce((sum, value) => sum + value, 0);
        return total > 0 ? normalized.map(value => value / total) : normalized.map(() => 0);
    }

    function heatmapMatrix(spec) {
        const fields = chartFields(spec);
        const xLabels = [];
        const seriesLabels = [];
        const cells = new Map();
        (spec && Array.isArray(spec.data) ? spec.data : []).forEach(row => {
            const x = cleanText(row[fields.x], 120);
            const series = cleanText(row[fields.color], 120) || 'Value';
            const numeric = Number(row[fields.y]);
            if (!x || !Number.isFinite(numeric)) return;
            if (!xLabels.includes(x)) xLabels.push(x);
            if (!seriesLabels.includes(series)) seriesLabels.push(series);
            cells.set(series + '\u0000' + x, {
                value: numeric,
                row,
                entityId: cleanText(row[fields.entityId] || '', 160),
            });
        });
        return { xLabels, seriesLabels, cells };
    }

    const CHART_COLORS = Object.freeze([
        '#1687d9', '#2e9d63', '#e39a22', '#d55c5c', '#27a8a8',
        '#7d6ab7', '#5f83c2', '#91a13a', '#c96f34', '#3c9cc5',
        '#a45d8f', '#6f8f72',
    ]);

    function chartOption(spec, key, defaultValue) {
        const options = spec && spec.options && typeof spec.options === 'object'
            ? spec.options : {};
        return typeof options[key] === 'boolean' ? options[key] : defaultValue;
    }

    function appendEntityInteraction(node, entityId, row, spec, options) {
        if (!entityId) return;
        node.setAttribute('tabindex', '0');
        node.setAttribute('data-entity-id', entityId);
        node.addEventListener('click', () => options && options.onEntitySelect
            && options.onEntitySelect({ entityId, row, spec }));
    }

    function renderPieChart(documentRef, section, spec, options) {
        const namespace = 'http://www.w3.org/2000/svg';
        const svg = documentRef.createElementNS(namespace, 'svg');
        svg.setAttribute('class', 'agent-chart-svg agent-chart-pie');
        svg.setAttribute('data-chart-type', spec.type);
        svg.setAttribute('viewBox', '0 0 420 230');
        svg.setAttribute('role', 'img');
        svg.setAttribute('aria-label', spec.title || (spec.type + ' chart'));
        const fields = chartFields(spec);
        const rows = spec.data.slice(0, 12).filter(row => {
            const value = Number(row[fields.y]);
            return Number.isFinite(value) && value >= 0;
        });
        const values = rows.map(row => Number(row[fields.y]));
        const ratios = pieSliceRatios(values);
        const total = values.reduce((sum, value) => sum + value, 0);
        const showValues = chartOption(spec, 'showValues', true);
        const showPercentages = chartOption(spec, 'showPercentages', false);
        const showLegend = chartOption(spec, 'showLegend', true);
        const cx = showLegend ? 94 : 210;
        const cy = 108;
        const radius = 76;
        let angle = -Math.PI / 2;

        rows.forEach((row, index) => {
            const ratio = ratios[index];
            if (ratio <= 0) return;
            const end = angle + ratio * Math.PI * 2;
            const entityId = cleanText(row[fields.entityId] || '', 160);
            let mark;
            if (ratio >= 0.999999) {
                mark = documentRef.createElementNS(namespace, 'circle');
                mark.setAttribute('cx', String(cx));
                mark.setAttribute('cy', String(cy));
                mark.setAttribute('r', String(radius));
            } else {
                const x1 = cx + Math.cos(angle) * radius;
                const y1 = cy + Math.sin(angle) * radius;
                const x2 = cx + Math.cos(end) * radius;
                const y2 = cy + Math.sin(end) * radius;
                mark = documentRef.createElementNS(namespace, 'path');
                mark.setAttribute('d', [
                    'M', cx, cy,
                    'L', x1, y1,
                    'A', radius, radius, 0, ratio > 0.5 ? 1 : 0, 1, x2, y2,
                    'Z',
                ].join(' '));
            }
            mark.setAttribute('class', 'agent-chart-slice');
            mark.setAttribute('fill', CHART_COLORS[index % CHART_COLORS.length]);
            appendEntityInteraction(mark, entityId, row, spec, options);
            const title = documentRef.createElementNS(namespace, 'title');
            title.textContent = cleanText(row[fields.x], 100) + ': ' + values[index]
                + (spec.unit ? ' ' + spec.unit : '')
                + ' (' + Math.round(ratio * 1000) / 10 + '%)';
            mark.appendChild(title);
            svg.appendChild(mark);
            angle = end;
        });

        if (spec.type === 'donut') {
            const hole = documentRef.createElementNS(namespace, 'circle');
            hole.setAttribute('cx', String(cx));
            hole.setAttribute('cy', String(cy));
            hole.setAttribute('r', '39');
            hole.setAttribute('class', 'agent-chart-donut-hole');
            svg.appendChild(hole);
            const totalLabel = documentRef.createElementNS(namespace, 'text');
            totalLabel.setAttribute('x', String(cx));
            totalLabel.setAttribute('y', String(cy + 3));
            totalLabel.setAttribute('text-anchor', 'middle');
            totalLabel.setAttribute('class', 'agent-chart-total');
            totalLabel.textContent = String(total);
            svg.appendChild(totalLabel);
        }

        if (showLegend) {
            rows.forEach((row, index) => {
                const y = 22 + index * 16;
                const swatch = documentRef.createElementNS(namespace, 'rect');
                swatch.setAttribute('x', '190');
                swatch.setAttribute('y', String(y - 8));
                swatch.setAttribute('width', '9');
                swatch.setAttribute('height', '9');
                swatch.setAttribute('rx', '1');
                swatch.setAttribute('fill', CHART_COLORS[index % CHART_COLORS.length]);
                svg.appendChild(swatch);
                const label = documentRef.createElementNS(namespace, 'text');
                label.setAttribute('x', '205');
                label.setAttribute('y', String(y));
                label.setAttribute('class', 'agent-chart-legend-label');
                const details = [];
                if (showValues) details.push(String(values[index]));
                if (showPercentages) details.push((ratios[index] * 100).toFixed(1) + '%');
                label.textContent = cleanText(row[fields.x], 22)
                    + (details.length ? '  ' + details.join(' / ') : '');
                svg.appendChild(label);
            });
        }
        section.appendChild(svg);
    }

    function renderHeatmap(documentRef, section, spec, options) {
        const namespace = 'http://www.w3.org/2000/svg';
        const matrix = heatmapMatrix(spec);
        const columns = matrix.xLabels.slice(0, 8);
        const series = matrix.seriesLabels.slice(0, 12);
        const left = 126;
        const top = 48;
        const cellWidth = 48;
        const cellHeight = 22;
        const width = left + columns.length * cellWidth + 12;
        const height = top + series.length * cellHeight + 30;
        const svg = documentRef.createElementNS(namespace, 'svg');
        svg.setAttribute('class', 'agent-chart-svg agent-chart-heatmap');
        svg.setAttribute('data-chart-type', 'heatmap');
        svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
        svg.setAttribute('role', 'img');
        svg.setAttribute('aria-label', spec.title || 'Heatmap');
        const values = [];
        series.forEach(seriesLabel => columns.forEach(column => {
            const cell = matrix.cells.get(seriesLabel + '\u0000' + column);
            values.push(cell ? Math.max(0, Number(cell.value)) : 0);
        }));
        const maximum = Math.max(1, ...values);
        const showValues = chartOption(spec, 'showValues', true);

        columns.forEach((column, columnIndex) => {
            const label = documentRef.createElementNS(namespace, 'text');
            label.setAttribute('x', String(left + columnIndex * cellWidth + cellWidth / 2));
            label.setAttribute('y', '38');
            label.setAttribute('text-anchor', 'middle');
            label.setAttribute('class', 'agent-chart-heat-label');
            label.textContent = cleanText(column, 11);
            const title = documentRef.createElementNS(namespace, 'title');
            title.textContent = column;
            label.appendChild(title);
            svg.appendChild(label);
        });

        series.forEach((seriesLabel, rowIndex) => {
            const y = top + rowIndex * cellHeight;
            const rowLabel = documentRef.createElementNS(namespace, 'text');
            rowLabel.setAttribute('x', String(left - 7));
            rowLabel.setAttribute('y', String(y + cellHeight * 0.68));
            rowLabel.setAttribute('text-anchor', 'end');
            rowLabel.setAttribute('class', 'agent-chart-heat-label');
            rowLabel.textContent = cleanText(seriesLabel, 18);
            const rowTitle = documentRef.createElementNS(namespace, 'title');
            rowTitle.textContent = seriesLabel;
            rowLabel.appendChild(rowTitle);
            svg.appendChild(rowLabel);
            columns.forEach((column, columnIndex) => {
                const cell = matrix.cells.get(seriesLabel + '\u0000' + column);
                const value = cell ? Math.max(0, Number(cell.value)) : 0;
                const ratio = value / maximum;
                const rect = documentRef.createElementNS(namespace, 'rect');
                rect.setAttribute('x', String(left + columnIndex * cellWidth + 1));
                rect.setAttribute('y', String(y + 1));
                rect.setAttribute('width', String(cellWidth - 2));
                rect.setAttribute('height', String(cellHeight - 2));
                rect.setAttribute('rx', '2');
                rect.setAttribute('class', 'agent-chart-heat-cell');
                rect.setAttribute('fill-opacity', String(0.08 + ratio * 0.84));
                appendEntityInteraction(rect, cell && cell.entityId, cell && cell.row, spec, options);
                const title = documentRef.createElementNS(namespace, 'title');
                title.textContent = column + ' / ' + seriesLabel + ': ' + value
                    + (spec.unit ? ' ' + spec.unit : '');
                rect.appendChild(title);
                svg.appendChild(rect);
                if (showValues) {
                    const count = documentRef.createElementNS(namespace, 'text');
                    count.setAttribute('x', String(left + columnIndex * cellWidth + cellWidth / 2));
                    count.setAttribute('y', String(y + cellHeight * 0.68));
                    count.setAttribute('text-anchor', 'middle');
                    count.setAttribute('class', 'agent-chart-heat-value');
                    count.textContent = String(value);
                    svg.appendChild(count);
                }
            });
        });
        section.appendChild(svg);
    }

    function renderKpi(documentRef, section, spec) {
        const grid = element(documentRef, 'div', 'agent-kpi-grid');
        const fields = chartFields(spec);
        spec.data.slice(0, 6).forEach(row => {
            const item = element(documentRef, 'div', 'agent-kpi-item');
            item.appendChild(element(documentRef, 'div', 'agent-kpi-label', cleanText(row[fields.x], 80)));
            item.appendChild(element(documentRef, 'div', 'agent-kpi-value', cleanText(row[fields.y], 80) + (spec.unit ? ' ' + spec.unit : '')));
            grid.appendChild(item);
        });
        section.appendChild(grid);
    }

    function chartLabelLines(value, slotWidth, maximumLines) {
        const label = cleanText(value, 120).replace(/\s+/g, ' ');
        if (!label) return [''];
        const lineLimit = Math.max(1, Math.min(3, Number(maximumLines) || 2));
        const characterLimit = Math.max(5, Math.floor(Number(slotWidth || 0) / 4.2));
        const words = label.split(' ');
        const lines = [];
        let current = '';

        function shortened(text) {
            if (text.length <= characterLimit) return text;
            if (characterLimit <= 3) return text.slice(0, characterLimit);
            return text.slice(0, characterLimit - 3).trimEnd() + '...';
        }

        for (let index = 0; index < words.length; index += 1) {
            const candidate = current ? current + ' ' + words[index] : words[index];
            if (candidate.length <= characterLimit) {
                current = candidate;
                continue;
            }
            if (lines.length < lineLimit - 1) {
                if (current) lines.push(shortened(current));
                current = words[index];
                continue;
            }
            const remainder = [current, ...words.slice(index)].filter(Boolean).join(' ');
            lines.push(shortened(remainder));
            return lines;
        }
        if (current) lines.push(shortened(current));
        return lines.slice(0, lineLimit);
    }

    function renderSvgChart(documentRef, section, spec, options) {
        const namespace = 'http://www.w3.org/2000/svg';
        const svg = documentRef.createElementNS(namespace, 'svg');
        svg.setAttribute('class', 'agent-chart-svg');
        svg.setAttribute('data-chart-type', spec.type);
        svg.setAttribute('role', 'img');
        svg.setAttribute('aria-label', spec.title || (spec.type + ' chart'));
        const fields = chartFields(spec);
        let rows = spec.data.slice(0, spec.type === 'line' || spec.type === 'scatter' ? 40 : 14);
        if (spec.type === 'pareto') {
            rows = rows.slice().sort((left, right) => Number(right[fields.y]) - Number(left[fields.y]));
        }
        const maximumLabelLines = rows.length <= 8 ? 3 : 2;
        svg.setAttribute('viewBox', '0 0 360 ' + (maximumLabelLines === 3 ? 222 : 212));
        const values = rows.map(row => Number(row[fields.y])).map(value => Number.isFinite(value) ? value : 0);
        const maximum = Math.max(1, ...values);
        const paretoRatios = spec.type === 'pareto'
            ? paretoCumulativeRatios(values)
            : [];
        const paretoPoints = [];
        const left = 38;
        const top = 16;
        const width = 306;
        const height = 150;
        const axisColor = 'currentColor';
        const axis = documentRef.createElementNS(namespace, 'path');
        axis.setAttribute('d', 'M' + left + ',' + top + 'V' + (top + height) + 'H' + (left + width));
        axis.setAttribute('fill', 'none');
        axis.setAttribute('stroke', axisColor);
        axis.setAttribute('opacity', '0.28');
        svg.appendChild(axis);
        const points = [];
        rows.forEach((row, index) => {
            const value = values[index];
            const x = left + (index + 0.5) * width / Math.max(1, rows.length);
            const y = top + height - value / maximum * height;
            const entityId = cleanText(row[fields.entityId] || '', 160);
            if (spec.type === 'bar' || spec.type === 'histogram' || spec.type === 'pareto') {
                const barWidth = Math.max(5, width / Math.max(1, rows.length) * 0.68);
                const rect = documentRef.createElementNS(namespace, 'rect');
                rect.setAttribute('x', String(x - barWidth / 2));
                rect.setAttribute('y', String(y));
                rect.setAttribute('width', String(barWidth));
                rect.setAttribute('height', String(top + height - y));
                rect.setAttribute('rx', '2');
                rect.setAttribute('class', 'agent-chart-mark');
                if (entityId) {
                    rect.setAttribute('tabindex', '0');
                    rect.setAttribute('data-entity-id', entityId);
                    rect.addEventListener('click', () => options && options.onEntitySelect
                        && options.onEntitySelect({ entityId, row, spec }));
                }
                const title = documentRef.createElementNS(namespace, 'title');
                title.textContent = cleanText(row[fields.x], 80) + ': ' + value + (spec.unit ? ' ' + spec.unit : '');
                rect.appendChild(title);
                svg.appendChild(rect);
                if (spec.type === 'pareto' && paretoRatios[index] > 0) {
                    const cumulativeRatio = paretoRatios[index];
                    paretoPoints.push([
                        x,
                        top + height - cumulativeRatio * height,
                        cumulativeRatio,
                    ]);
                }
            } else {
                points.push([x, y, entityId, row]);
            }
            const fullLabel = cleanText(row[fields.x], 120);
            const label = documentRef.createElementNS(namespace, 'text');
            label.setAttribute('x', String(x));
            label.setAttribute('y', '182');
            label.setAttribute('text-anchor', 'middle');
            label.setAttribute('class', 'agent-chart-label');
            label.setAttribute('aria-label', fullLabel);
            chartLabelLines(
                fullLabel,
                width / Math.max(1, rows.length),
                maximumLabelLines
            ).forEach((line, lineIndex) => {
                const span = documentRef.createElementNS(namespace, 'tspan');
                span.setAttribute('x', String(x));
                if (lineIndex > 0) span.setAttribute('dy', '10');
                span.textContent = line;
                label.appendChild(span);
            });
            const labelTitle = documentRef.createElementNS(namespace, 'title');
            labelTitle.textContent = fullLabel;
            label.appendChild(labelTitle);
            svg.appendChild(label);
        });
        if (spec.type === 'line' && points.length) {
            const polyline = documentRef.createElementNS(namespace, 'polyline');
            polyline.setAttribute('points', points.map(point => point[0] + ',' + point[1]).join(' '));
            polyline.setAttribute('class', 'agent-chart-line');
            svg.appendChild(polyline);
        }
        if (spec.type === 'pareto' && paretoPoints.length) {
            const cumulativeLine = documentRef.createElementNS(namespace, 'polyline');
            cumulativeLine.setAttribute('points', paretoPoints
                .map(point => point[0] + ',' + point[1]).join(' '));
            cumulativeLine.setAttribute('class', 'agent-chart-pareto-line');
            svg.appendChild(cumulativeLine);
            paretoPoints.forEach(([x, y, ratio]) => {
                const point = documentRef.createElementNS(namespace, 'circle');
                point.setAttribute('cx', String(x));
                point.setAttribute('cy', String(y));
                point.setAttribute('r', '3');
                point.setAttribute('class', 'agent-chart-pareto-point');
                const title = documentRef.createElementNS(namespace, 'title');
                title.textContent = 'Cumulative: ' + Math.round(ratio * 100) + '%';
                point.appendChild(title);
                svg.appendChild(point);
            });
            [0, 0.5, 1].forEach(ratio => {
                const label = documentRef.createElementNS(namespace, 'text');
                label.setAttribute('x', '358');
                label.setAttribute('y', String(top + height - ratio * height + 3));
                label.setAttribute('text-anchor', 'end');
                label.setAttribute('class', 'agent-chart-percent-label');
                label.textContent = Math.round(ratio * 100) + '%';
                svg.appendChild(label);
            });
            const legendLine = documentRef.createElementNS(namespace, 'line');
            legendLine.setAttribute('x1', String(left + width - 82));
            legendLine.setAttribute('x2', String(left + width - 62));
            legendLine.setAttribute('y1', '8');
            legendLine.setAttribute('y2', '8');
            legendLine.setAttribute('class', 'agent-chart-pareto-line');
            svg.appendChild(legendLine);
            const legend = documentRef.createElementNS(namespace, 'text');
            legend.setAttribute('x', String(left + width - 58));
            legend.setAttribute('y', '11');
            legend.setAttribute('class', 'agent-chart-percent-label');
            legend.textContent = 'Cumulative %';
            svg.appendChild(legend);
        }
        if (spec.type === 'line' || spec.type === 'scatter') {
            points.forEach(([x, y, entityId, row], index) => {
                const circle = documentRef.createElementNS(namespace, 'circle');
                circle.setAttribute('cx', String(x));
                circle.setAttribute('cy', String(y));
                circle.setAttribute('r', '4');
                circle.setAttribute('class', 'agent-chart-mark');
                if (entityId) {
                    circle.setAttribute('tabindex', '0');
                    circle.setAttribute('data-entity-id', entityId);
                    circle.addEventListener('click', () => options && options.onEntitySelect
                        && options.onEntitySelect({ entityId, row, spec }));
                }
                const title = documentRef.createElementNS(namespace, 'title');
                title.textContent = cleanText(row[fields.x], 80) + ': ' + values[index]
                    + (spec.unit ? ' ' + spec.unit : '');
                circle.appendChild(title);
                svg.appendChild(circle);
            });
        }
        section.appendChild(svg);
    }

    function renderVisualization(documentRef, block, options) {
        const section = element(documentRef, 'section', 'agent-rich-block agent-chart-block');
        if (block.spec.title) section.appendChild(element(documentRef, 'div', 'agent-rich-block-title', block.spec.title));
        if (block.spec.subtitle) section.appendChild(element(documentRef, 'div', 'agent-rich-block-subtitle', block.spec.subtitle));
        if (block.spec.type === 'kpi') renderKpi(documentRef, section, block.spec);
        else if (block.spec.type === 'pie' || block.spec.type === 'donut') {
            renderPieChart(documentRef, section, block.spec, options);
        } else if (block.spec.type === 'heatmap') {
            renderHeatmap(documentRef, section, block.spec, options);
        } else renderSvgChart(documentRef, section, block.spec, options);
        return section;
    }

    function renderTable(documentRef, block, options) {
        const spec = block.table;
        const section = element(
            documentRef,
            'section',
            'agent-rich-block agent-table-block agent-markdown'
        );
        if (spec.title) {
            section.appendChild(element(
                documentRef,
                'div',
                'agent-rich-block-title',
                spec.title
            ));
        }
        if (spec.subtitle) {
            section.appendChild(element(
                documentRef,
                'div',
                'agent-rich-block-subtitle',
                spec.subtitle
            ));
        }
        const wrap = element(documentRef, 'div', 'agent-markdown-table-wrap');
        const table = documentRef.createElement('table');
        const head = documentRef.createElement('thead');
        const headRow = documentRef.createElement('tr');
        spec.columns.forEach(column => {
            const label = column.label + (column.unit ? ' (' + column.unit + ')' : '');
            headRow.appendChild(element(documentRef, 'th', '', label));
        });
        head.appendChild(headRow);
        table.appendChild(head);
        const body = documentRef.createElement('tbody');
        spec.rows.forEach(row => {
            const tableRow = documentRef.createElement('tr');
            if (row.entityId) {
                tableRow.tabIndex = 0;
                tableRow.dataset.entityId = row.entityId;
                tableRow.addEventListener('click', () => {
                    if (options && typeof options.onEntitySelect === 'function') {
                        options.onEntitySelect({ entityId: row.entityId, row, spec });
                    }
                });
            }
            row.cells.forEach(value => {
                tableRow.appendChild(element(documentRef, 'td', '', value));
            });
            body.appendChild(tableRow);
        });
        table.appendChild(body);
        wrap.appendChild(table);
        section.appendChild(wrap);
        return section;
    }

    function renderBlock(documentRef, rawBlock, options) {
        const block = normalizeBlock(rawBlock);
        if (!block) return null;
        if (block.type === 'markdown') {
            const node = element(documentRef, 'div', 'agent-msg assistant agent-markdown');
            node.innerHTML = renderMarkdownHtml(block.text);
            return node;
        }
        if (block.type === 'sources') return renderSources(documentRef, block);
        if (block.type === 'facts') return renderFacts(documentRef, block);
        if (block.type === 'visualization') return renderVisualization(documentRef, block, options);
        if (block.type === 'table') return renderTable(documentRef, block, options);
        if (block.type === 'entity_reference') {
            const node = element(documentRef, 'section', 'agent-rich-block agent-entity-reference');
            const type = element(documentRef, 'div', 'agent-entity-type', block.entity.entityType.replace(/_/g, ' '));
            const label = element(documentRef, 'div', 'agent-entity-label', block.entity.label);
            node.appendChild(type);
            node.appendChild(label);
            if (block.entity.subtitle) node.appendChild(element(documentRef, 'div', 'agent-entity-subtitle', block.entity.subtitle));
            appendActionButtons(documentRef, node, block.actions, options);
            return node;
        }
        const node = element(documentRef, 'section', 'agent-rich-block agent-actions-block');
        appendActionButtons(documentRef, node, block.actions, options);
        return node;
    }

    function renderMarkdownInto(elementRef, markdown) {
        elementRef.classList.add('agent-markdown');
        elementRef.innerHTML = renderMarkdownHtml(markdown);
        return elementRef;
    }

    return {
        BLOCK_TYPES: Array.from(BLOCK_TYPES),
        SOURCE_TYPES: Array.from(SOURCE_TYPES),
        VISUALIZATION_TYPES: Array.from(VISUALIZATION_TYPES),
        ACTION_IDS: Array.from(ACTION_IDS),
        escapeHtml,
        safeUrl,
        sourceDomain,
        renderInline,
        renderMarkdownHtml,
        renderMarkdownInto,
        formatEngineeringText,
        formatEngineeringUnit,
        chartLabelLines,
        normalizeSource,
        normalizeVisualization,
        normalizeTable,
        paretoCumulativeRatios,
        pieSliceRatios,
        heatmapMatrix,
        normalizeBlock,
        normalizeBlocks,
        renderBlock,
    };
});
