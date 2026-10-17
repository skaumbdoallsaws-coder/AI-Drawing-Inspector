(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProGenerationPlanningView = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    const clone = value => JSON.parse(JSON.stringify(value));
    const sameRef = (a, b) => !!a && !!b && ['artifactKind', 'artifactId', 'artifactRevision'].every(key => a[key] === b[key]);

    function create(workspace, element) {
        const transport = workspace.designTransport;
        let opened = false, briefMode = false, source = null, sources = null, turn = null, preview = null, body = null, error = null;
        let listRequest = null;
        let applying = false;
        let destinationRequest = null;
        let destinationForm = null;
        function editor() {
            const state = workspace.session.getState();
            return {baseRevision: state.baseRevision, draftRevision: state.draftRevision,
                dirty: !!state.dirty || !!(state.history && state.history.length), conflicted: !!state.conflict,
                pending: !!state.busy, generationRunId: state.generatedDraft && state.generatedDraft.runId || null,
                designTransactionId: state.designProposalDraft && state.designProposalDraft.transactionId || null};
        }
        function reference() {
            return source || briefMode ? {workspaceId: 'planning-' + String(transport.sessionId).replace(/[^A-Za-z0-9._:-]/g, '-').slice(0, 130),
                sourceContextRef: clone(source), editorContext: editor()} : null;
        }
        function refresh() {
            if (workspace.destroyed) return;
            workspace._renderDesignPanel();
            workspace._syncController();
        }
        function close() {
            opened = false; briefMode = false; source = null; preview = null; turn = null; listRequest = null;
            refresh();
        }
        function select(ref) {
            if (ref && !(sources || []).some(item => sameRef(item.sourceContextRef, ref))) throw new Error('Select a listed reviewed source');
            source = ref ? clone(ref) : null; briefMode = !ref; turn = null; preview = null;
            refresh();
        }
        async function open() {
            opened = true; error = null;
            if (!source) briefMode = true;
            workspace.designState.collapsed = false;
            const token = {}; listRequest = token;
            refresh();
            try {
                const listing = await transport.listGenerationPlanningSources();
                if (workspace.destroyed || listRequest !== token) return;
                sources = listing.sources;
                if (listing.truncated || listing.unavailableCount) error = 'Some source contexts are unavailable or omitted.';
            } catch (failure) { if (listRequest === token) error = failure.message; }
            refresh();
        }
        function begin(id) {
            if (!reference()) return;
            turn = {id: id, frame: workspace.session.getState()};
            preview = null; opened = true;
            refresh();
        }
        async function show(summary) {
            const pending = turn, ref = reference(), state = workspace.session.getState();
            const provisional = briefMode && summary.sourceContextRef && summary.sourceContextRef.artifactKind === 'generation-provisional-context';
            if (!ref || !pending || workspace.destroyed || pending.id !== summary.clientTurnId
                    || summary.workspaceId !== ref.workspaceId || (!provisional && !sameRef(source, summary.sourceContextRef))
                    || state.editorGenerationId !== pending.frame.editorGenerationId || state.draftRevision !== summary.baseRevision
                    || ref.editorContext.dirty || ref.editorContext.pending || ref.editorContext.conflicted) {
                throw new Error('A newer turn, source or editor state superseded this preview');
            }
            const candidate = await transport.inspectGenerationPlanningPreview(summary, ref.editorContext);
            const after = workspace.session.getState(), current = editor();
            if (workspace.destroyed || turn !== pending || after.editorGenerationId !== state.editorGenerationId
                    || after.draftRevision !== summary.baseRevision || current.dirty || current.pending || current.conflicted
                    || candidate.candidateRevision !== summary.candidateRevision || candidate.previewRevision !== summary.previewRevision
                    || candidate.previewId !== summary.previewId || candidate.ledgerRevision !== summary.ledgerRevision
                    || candidate.baseRevision !== summary.baseRevision) {
                throw new Error('A newer turn or editor state superseded the loaded preview');
            }
            workspace._cancelPointerGesture();
            if (provisional) source = clone(summary.sourceContextRef);
            preview = {candidate: candidate, frame: after};
            opened = true; workspace.designState.collapsed = false;
            if (workspace.assetBrowserState.open) workspace.closeAssetBrowser(false);
            refresh();
            workspace.controller.fit();
            return {candidateRevision: candidate.candidateRevision, editorChanged: false};
        }
        function activeLayout() {
            const state = workspace.session.getState();
            if (!preview) return null;
            if (state.editorGenerationId !== preview.frame.editorGenerationId || state.draftRevision !== preview.candidate.baseRevision
                    || state.dirty || state.conflict) {
                preview = null;
                return null;
            }
            return preview.candidate.candidateLayout;
        }
        /**
         * Identity of the preview activeLayout() would return, or null.
         * Read-only and additive: activeLayout() hands back a layout document
         * with no candidate identity on it, and a caller that has to tell one
         * candidate from another - such as the structure tree, which keys both
         * its rebuilds and its expansion state on it - cannot recover that
         * from the layout alone.
         */
        function activePreviewRef() {
            if (!preview || !activeLayout()) return null;
            return {
                candidateRevision: preview.candidate.candidateRevision,
                previewRevision: preview.candidate.previewRevision,
                baseRevision: preview.candidate.baseRevision,
            };
        }
        async function apply() {
            if (applying || !activeLayout()) return;
            if (!workspace.capabilities.designLoopApply || !workspace.capabilities.agentWrite) throw new Error('Draft application is disabled');
            const selected = preview, binding = reference(), before = workspace.session.getState();
            applying = true; error = null; refresh();
            try {
                const proposal = await transport.selectGenerationPlanningPreview(
                    Object.assign({workspaceId: binding.workspaceId}, selected.candidate), binding.editorContext);
                const after = workspace.session.getState();
                if (workspace.destroyed || preview !== selected || before.editorGenerationId !== after.editorGenerationId
                        || before.draftRevision !== after.draftRevision || editor().dirty || editor().pending || editor().conflicted) {
                    throw new Error('The selected preview or editor changed before Apply');
                }
                if (proposal.candidateRevision !== selected.candidate.candidateRevision) throw new Error('Selected candidate revision differs');
                await workspace.session.applyDesignProposal(proposal);
                close();
            } catch (failure) { error = failure.message; throw failure; }
            finally { applying = false; refresh(); }
        }
        async function createDestination(values) {
            const state = editor(), before = workspace.session.getState(), layoutId = transport.layoutId;
            if (applying || state.dirty || state.pending || state.conflicted) throw new Error('Resolve the current draft before opening another layout');
            const signature = JSON.stringify({values: values, baseRevision: state.baseRevision}), storageKey = 'ip-generation-destination:' + layoutId;
            const view = workspace.document.defaultView;
            if (!destinationRequest) {
                try { destinationRequest = JSON.parse(view.sessionStorage.getItem(storageKey)); } catch (_) {}
            }
            if (!destinationRequest || destinationRequest.signature !== signature) {
                destinationRequest = {signature: signature, request: Object.assign({}, values, {
                    expectedBaseRevision: state.baseRevision,
                    requestKey: 'destination-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2)})};
            }
            applying = true; error = null;
            try {
                view.sessionStorage.setItem(storageKey, JSON.stringify(destinationRequest));
                const created = await transport.createGenerationDestination(destinationRequest.request, state);
                const after = workspace.session.getState();
                if (workspace.destroyed || transport.layoutId !== layoutId || before.editorGenerationId !== after.editorGenerationId
                        || before.draftRevision !== after.draftRevision || editor().dirty || editor().pending || editor().conflicted) {
                    throw new Error('The current editor changed; the new concept is retained as ' + created.layoutId);
                }
                const url = new URL(view.location.href);
                url.searchParams.set('facilityLayoutId', created.layoutId);
                view.location.assign(url.href);
            } catch (failure) { error = failure.message; throw failure; }
            finally { applying = false; refresh(); }
        }
        function render() {
            workspace.root.setAttribute('data-generation-planning', opened ? 'true' : 'false');
            if (!opened) { if (body) body.hidden = true; return false; }
            workspace.designPanel.hidden = false;
            workspace.designPanelBody.hidden = true;
            if (workspace.constructionPanelBody) workspace.constructionPanelBody.hidden = true;
            workspace.designPanel.setAttribute('data-collapsed', workspace.designState.collapsed ? 'true' : 'false');
            workspace.root.setAttribute('data-design-pane-open', workspace.designState.collapsed ? 'collapsed' : 'true');
            workspace.designPanelToggle.textContent = workspace.designState.collapsed ? '<' : '>';
            workspace.designPanelTitle.querySelector('strong').textContent = 'Generation planning';
            workspace.designPanelTitle.querySelector('.ip-flw-design-status').textContent = preview ? 'Isolated preview' : 'Source context';
            if (!body) {
                body = element(workspace.document, 'div', {className: 'ip-flw-design-body ip-flw-generation-body'});
                workspace.designPanel.appendChild(body);
            }
            body.hidden = workspace.designState.collapsed;
            const focusedInput = destinationForm && destinationForm.section.contains(workspace.document.activeElement)
                ? workspace.document.activeElement : null;
            while (body.firstChild) body.removeChild(body.firstChild);
            const picker = element(workspace.document, 'select', {'aria-label': 'Reviewed generation source'});
            picker.style.maxWidth = '100%';
            picker.disabled = applying;
            const briefOption = element(workspace.document, 'option', {value: ''}, 'Start from your brief');
            briefOption.selected = briefMode;
            picker.appendChild(briefOption);
            (sources || []).forEach(function (item, index) {
                const option = element(workspace.document, 'option', {value: String(index)}, item.displayName + ' / ' + item.contextId);
                option.selected = sameRef(item.sourceContextRef, source);
                picker.appendChild(option);
            });
            picker.addEventListener('change', function () { select(picker.value === '' ? null : sources[Number(picker.value)].sourceContextRef); });
            body.appendChild(picker);
            if (sources && !sources.length) body.appendChild(element(workspace.document, 'p', {role: 'status'}, 'No eligible reviewed source contexts.'));
            if (error) body.appendChild(element(workspace.document, 'p', {role: 'alert'}, error));
            if (preview && activeLayout() && workspace.capabilities.designLoopApply && workspace.capabilities.agentWrite) {
                const install = element(workspace.document, 'button', {type: 'button'}, 'Apply unsaved');
                install.disabled = applying || editor().pending;
                install.addEventListener('click', function () { apply().catch(function () {}); });
                body.appendChild(install);
            }
            if (!preview && workspace.capabilities.designLoopApply && workspace.capabilities.agentWrite) {
                // Source-list completion and session notifications must not reset an in-progress form.
                if (!destinationForm) {
                    const section = element(workspace.document, 'details');
                    section.appendChild(element(workspace.document, 'summary', {}, 'New concept'));
                    const inputs = {};
                    [['displayName', 'Name', 'text', 'Facility concept'], ['widthMeters', 'Width (m)', 'number', '40'],
                        ['depthMeters', 'Depth (m)', 'number', '30']].forEach(function (spec) {
                        const label = element(workspace.document, 'label', {}, spec[1]);
                        const input = element(workspace.document, 'input', {type: spec[2], value: spec[3], 'aria-label': spec[1]});
                        input.style.width = '100%'; input.style.minWidth = '0';
                        if (spec[2] === 'number') { input.min = '5'; input.max = '10000'; input.step = '0.5'; }
                        label.appendChild(input); section.appendChild(label); inputs[spec[0]] = input;
                    });
                    const label = element(workspace.document, 'label');
                    const confirm = element(workspace.document, 'input', {type: 'checkbox'});
                    label.appendChild(confirm); label.appendChild(workspace.document.createTextNode('Conceptual dimensions, not surveyed site data'));
                    section.appendChild(label);
                    const create = element(workspace.document, 'button', {type: 'button'}, 'Create and open');
                    create.addEventListener('click', function () {
                        createDestination({displayName: inputs.displayName.value, widthMeters: Number(inputs.widthMeters.value),
                            depthMeters: Number(inputs.depthMeters.value), confirmConceptualFloor: confirm.checked}).catch(function () {});
                    });
                    section.appendChild(create);
                    destinationForm = {section, create};
                }
                destinationForm.create.disabled = applying || editor().dirty || editor().pending || editor().conflicted;
                body.appendChild(destinationForm.section);
            }
            if (preview && activeLayout()) {
                body.appendChild(element(workspace.document, 'p', {}, preview.candidate.counts.placements + ' placements; ' + preview.candidate.counts.zones + ' zones'));
                body.appendChild(element(workspace.document, 'p', {}, 'Prototype geometry. Not applied or saved.'));
                body.appendChild(element(workspace.document, 'strong', {}, 'Checks and limits'));
                body.appendChild(element(workspace.document, 'p', {},
                    'Manufacturing feasibility, station-to-station transfers and safety approval are not established.'));
                body.appendChild(element(workspace.document, 'p', {},
                    'Spacing is a geometric gap, not verified operating clearance.'));
                const notes = preview.candidate.planningNotes || {};
                ['assumptions', 'unknowns', 'historicalAssumptions'].forEach(function (key) {
                    if (!(notes[key] || []).length) return;
                    body.appendChild(element(workspace.document, 'strong', {}, key === 'assumptions' ? 'Current assumptions'
                        : key === 'historicalAssumptions' ? 'Original assumptions (not revalidated)' : 'Still unknown'));
                    const list = element(workspace.document, 'ul');
                    list.style.overflowWrap = 'anywhere';
                    notes[key].forEach(value => list.appendChild(element(workspace.document, 'li', {}, value)));
                    body.appendChild(list);
                });
                if ((notes.sources || []).length) {
                    body.appendChild(element(workspace.document, 'strong', {}, 'Sources consulted'));
                    const list = element(workspace.document, 'ul');
                    notes.sources.forEach(function (source) {
                        let url;
                        try { url = new URL(source.url); } catch (_) { return; }
                        if (!['https:', 'http:'].includes(url.protocol)) return;
                        const item = element(workspace.document, 'li');
                        item.appendChild(element(workspace.document, 'a', {href: url.href, target: '_blank', rel: 'noopener noreferrer'}, source.title));
                        list.appendChild(item);
                    });
                    body.appendChild(list);
                }
            }
            const exit = element(workspace.document, 'button', {type: 'button'}, 'Exit planning');
            exit.addEventListener('click', close);
            body.appendChild(exit);
            if (focusedInput && body.contains(focusedInput)) focusedInput.focus({preventScroll: true});
            return true;
        }
        return {open, close, select, reference, begin, show, activeLayout,
                activePreviewRef, render, apply, createDestination};
    }
    return Object.freeze({create: create});
}));
