/* Read-bound guards for the existing documentation workspace save routes. */
(function (root) {
    'use strict';
    function capture(payload, page, apiBase) {
        if (!payload?.scene) return null;
        return {
            apiBase,
            payload: { revision: payload.revision, scene: {
                assemblyNumber: payload.scene.assemblyNumber,
                sourceRevision: payload.scene.sourceRevision,
                manualPlanRevision: payload.scene.manualPlanRevision,
            } },
            page: page ? { pageId: page.pageId, title: page.title } : null,
            slotBinding: payload.slotBinding ? structuredClone(payload.slotBinding) : null,
        };
    }
    function isCurrent(bound, payload, apiBase) {
        return Boolean(bound && payload?.scene && bound.apiBase === apiBase
            && bound.payload.scene.assemblyNumber === payload.scene.assemblyNumber
            && bound.payload.revision === payload.revision
            && (!bound.slotBinding || bound.slotBinding.revision === payload.slotBinding?.revision));
    }
    function message(error) {
        const text = String(error?.message || 'The edit could not be saved.');
        return /revision|hash|conflict|stale|changed/i.test(text)
            ? 'This document changed after your read. Your draft is still visible. Reopen the document and review the newer text before retrying.'
            : text;
    }
    function slotRequest(bound, path, body) {
        const read = bound?.slotBinding;
        if (!read) return body;
        const keys = path === 'values' ? body.values.map(item => 'slot:' + item.slot) : ['@sheet'];
        if (keys.some(key => key.endsWith('.label'))) keys.push('@sheet');
        const hashes = Object.fromEntries(keys.map(key => [key, read.hashes[key]]));
        return { ...body, editBinding: {
            documentId: read.documentId, expectedRevision: read.revision,
            sourceRevision: read.sourceRevision, manualPlanRevision: read.manualPlanRevision,
            requestId: root.crypto.randomUUID(), hashes, payload: body,
        } };
    }
    const editedMarker = 'Edited - source does not verify this value';
    function mark(element, provenance) {
        if (!element) return;
        if (provenance?.evidenceStatus !== 'edited_unverified') {
            delete element.dataset.evidenceMarker;
            return;
        }
        element.dataset.evidenceMarker = editedMarker;
        element.title = editedMarker;
        if (!document.getElementById('documentationEvidenceStyle')) {
            const style = document.createElement('style');
            style.id = 'documentationEvidenceStyle';
            style.textContent = '[data-evidence-marker]:not([contenteditable="true"])::after {'
                + 'content:attr(data-evidence-marker);display:block;font:6.5px Arial;color:#993900;line-height:1.2;}';
            document.head.appendChild(style);
        }
    }
    function confirmationControl(container, model, reload, isCurrent) {
        if (model?.documentType === 'product_specification_sheet') return;
        const edited = (model?.provenanceTargets || []).filter(row =>
            row.provenance?.evidenceStatus === 'edited_unverified');
        if (!edited.length) return;
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = 'Confirm as entered by me';
        button.addEventListener('click', async event => {
            if (!event.isTrusted || !isCurrent()) return;
            button.disabled = true;
            try {
            const number = model.product?.assemblyNumber;
            const response = await fetch('/api/documentation/' + encodeURIComponent(model.documentType)
                + '/' + encodeURIComponent(number) + '/confirmation-targets');
            const read = await response.json();
            if (!response.ok) throw new Error(read.message || 'Could not load the current values.');
            if (!isCurrent()) return;
            const dialog = document.createElement('dialog');
            const heading = document.createElement('h3');
            heading.textContent = 'Review every affected value and its former source';
            dialog.appendChild(heading);
            const chosen = read.targets.slice(0, 12);
            for (const scope of chosen) {
                const section = document.createElement('section');
                const name = document.createElement('strong');
                name.textContent = scope.provenance.displayName || 'Edited value';
                const values = document.createElement('pre');
                values.textContent = Object.values(scope.values).join('\n');
                const sources = document.createElement('p');
                sources.textContent = 'Original source: ' + (scope.provenance.originalEvidence.sourceIds || [])
                    .map(id => read.sources.find(source => source.sourceId === id)?.title || id).join('; ');
                section.append(name, values, sources);
                dialog.appendChild(section);
            }
            const explanation = document.createElement('p');
            explanation.textContent = 'These sources will no longer be cited as verifying these values. '
                + 'Confirmation records them as entered by you. Existing engineering approval gates still apply.'
                + (read.targets.length > chosen.length ? ' This dialog covers ' + chosen.length
                    + ' of ' + read.targets.length + ' edited scopes; the others remain unconfirmed.' : '');
            const confirm = document.createElement('button');
            confirm.type = 'button';
            confirm.textContent = 'Confirm as entered by me';
            confirm.disabled = !chosen.length;
            confirm.addEventListener('click', async click => {
                if (!click.isTrusted || !isCurrent()) return;
                confirm.disabled = true;
                try {
                    const saved = await fetch('/api/documentation/' + encodeURIComponent(read.documentId) + '/confirm-values', {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ expectedRevision: read.revision, requestId: crypto.randomUUID(),
                            targets: chosen.map(scope => ({ targetId: scope.targetId, expectedContentHash: scope.contentHash })) }),
                    });
                    const result = await saved.json();
                    if (!saved.ok) throw new Error(result.message || 'Review the current values and retry.');
                    dialog.close();
                    if (isCurrent()) await reload();
                } catch (error) {
                    explanation.textContent = message(error);
                } finally { confirm.disabled = false; }
            });
            const cancel = document.createElement('button');
            cancel.type = 'button'; cancel.textContent = 'Cancel';
            cancel.addEventListener('click', () => dialog.close());
            dialog.append(explanation, confirm, cancel);
            dialog.addEventListener('close', () => dialog.remove());
            document.body.appendChild(dialog);
            dialog.showModal();
            } catch (error) {
                const failure = document.createElement('p');
                failure.textContent = message(error);
                container.appendChild(failure);
            } finally { button.disabled = false; }
        });
        container.appendChild(button);
    }
    root.DocumentationCommands = { capture, isCurrent, message, slotRequest, mark, confirmationControl };
})(globalThis);
