from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_assembly_viewer_defaults_to_reversible_neutral_gray_appearance() -> None:
    html = (ROOT / "static" / "index.html").read_text("utf-8")

    assert "assyAppearanceMode: 'neutral'" in html
    assert "const ASSEMBLY_NEUTRAL_COLOR = 0xaeb5bb" in html
    assert "const ASSEMBLY_NEUTRAL_HIGHLIGHT_COLOR = 0xffffff" in html
    assert "const ASSEMBLY_NEUTRAL_HIGHLIGHT_INTENSITY = 0.10" in html
    assert "function _captureAssemblySourceAppearance(material)" in html
    assert "function _applyAssemblyMaterialAppearance(material)" in html
    assert "function _assemblyHighlightEmissiveColor(sourceColor)" in html
    assert "function _assemblyHighlightEmissiveIntensity()" in html
    assert "material.map = useOriginal ? source.map : null" in html
    assert "material.emissiveMap = useOriginal ? source.emissiveMap : null" in html
    assert "_applyAssemblyMaterialAppearance(mat);" in html
    assert "const color = _assemblyHighlightEmissiveColor(partColorMap[pn]);" in html
    assert "const intensity = _assemblyHighlightEmissiveIntensity();" in html
    assert "{ id: 'neutral', label: 'Neutral gray' }" in html
    assert "{ id: 'original', label: 'Original colors' }" in html
    assert "appearanceSelect.id = 'assy-appearance-mode'" in html


def test_assembly_ribbon_exposes_parts_manual_review_workflow() -> None:
    html = (ROOT / "static" / "index.html").read_text("utf-8")

    assert "_ribbonIconBtn('partsManual', 'Parts Manual')" in html
    assert "partsManualBtn.addEventListener('click', () => _openDocumentationWorkflow())" in html
    assert "function _showPartsManualPanel()" in html
    assert "function _partsManualApplyIsolation(" in html
    assert "function _partsManualExplodeSection(" in html
    assert "function _partsManualCreateItemCallouts(" in html
    assert "function _partsManualResetVisualization(" in html
    assert "partsManualDraftOccurrenceIds" in html
    assert "manualScopedBomOverlay" in html
    assert "manualDocumentPreviewOverlay" in html
    assert "function _showPartsManualDocumentPreview(" in html
    assert "function _partsManualCaptureCurrentView(" in html
    assert "imageRequest.allowAutomaticCameraSelection === true" in html
    assert "function _partsManualWaitForRenderPose(" in html
    assert "window.setTimeout(check, 16)" in html
    assert "() => finish(resolve)" in html
    assert "PARTS_MANUAL_ILLUSTRATION_STYLE" in html
    assert "function _partsManualCreateHiddenLinesRemovedPass(" in html
    assert "const PARTS_MANUAL_FEATURE_EDGE_CACHE = new WeakMap()" in html
    assert "PARTS_MANUAL_TOPOLOGY_EDGE_TRIANGLE_BUDGET = 8000" in html
    assert "function _partsManualTopologyEdgeBudget(meshes)" in html
    assert "if (topologyEdges.enabled)" in html
    assert "PARTS_MANUAL_FEATURE_EDGE_CACHE.get(sourceGeometry)" in html
    assert "sourceGeometry.addEventListener?.('dispose', disposeCachedEdges)" in html
    assert "featureLines.forEach(line => featureScene.remove(line))" in html
    assert "new THREE.WebGLRenderTarget(" in html
    assert "normalDepthTexture" in html
    assert "gl_FragCoord.z" in html
    assert "normalEdgeStart: { value: Number(options.normalEdgeStart) || 0.12 }" in html
    assert "normalEdgeEnd: { value: Number(options.normalEdgeEnd) || 0.28 }" in html
    assert "depthEdgeStart: { value: Number(options.depthEdgeStart) || 0.004 }" in html
    assert "depthEdgeEnd: { value: Number(options.depthEdgeEnd) || 0.012 }" in html
    assert "PARTS_MANUAL_EXACT_ROUTE_CANDIDATE_LIMIT = 2" in html
    assert "PARTS_MANUAL_MAX_BRANCHED_INSTANCES = 3" in html
    assert "PARTS_MANUAL_MAX_ROWS_FOR_BRANCHED_CALLOUTS = 12" in html
    assert "candidates.length >= PARTS_MANUAL_EXACT_ROUTE_CANDIDATE_LIMIT" in html
    assert "const densePage = transformedBalloons.length > 12" in html
    assert "if (evaluateRoute(route)) break" in html
    assert "return presentation.metrics.hardFailureCount === 0" in html
    assert "candidate.leaderBalloonCollisionCount === 0" in html
    assert "row.leaderBalloonCollisionCount === 0" in html
    assert "candidate.detourRatio <= PARTS_MANUAL_CALLOUT_QUALITY.maximumDetourRatio" in html
    assert "function _partsManualBalloonAttachment(row)" in html
    assert "function _partsManualRouteCalloutsStraightFirst(rows, options = {})" in html
    assert "['straight-first', () => _partsManualRouteCalloutsStraightFirst" in html
    assert "balloonAttachment: _partsManualBalloonAttachment" in html
    assert "const complexityExplodeScale = groups.length >= 36" in html
    assert "function _partsManualDefinitionExplodeClusters(section, groups)" in html
    assert "function _partsManualRepairOccludedExplodeClusters(" in html
    assert "function _partsManualExplodeClusterNesting(" in html
    assert "nested_service_item" in html
    assert "maximumOverlapRatio" in html
    assert "const explodeClusters = _partsManualDefinitionExplodeClusters(section, groups)" in html
    assert "explodeClusters.length > 1 ? distance : 0" in html
    assert "function _partsManualProcessExplodeDirection(index, cameraPreset = 'isometric')" in html
    assert "const processSequenceDistanceScale =" in html
    assert "const needsAlternativeSearch = primaryEvaluation.obstructingItems.size > 0" in html
    assert "candidate.obstructingItems.size === 0" in html
    assert "const requiresInteriorRaycast = point => potentialRegions.some" in html
    assert "HIDDEN_LINES_REMOVED" in html
    assert "function _partsManualSetDocumentationPreviewResolution(enabled)" in html
    assert "2 * displayScale" in html
    assert "now - technical.lastRenderedAt < 1000 / 30" in html
    assert "_partsManualSetDocumentationPreviewResolution(true);" in html
    assert "_partsManualSetDocumentationPreviewResolution(false);" in html
    assert "function _partsManualProjectedCalloutGeometry(" in html
    assert "function _partsManualCalloutVisibilityContext(" in html
    assert "function _partsManualPrepareRaycastAcceleration(" in html
    assert "window.MeshBVHLib" in html
    assert "library.computeBoundsTree.call(geometry, { maxLeafTris: 12 })" in html
    assert "raycaster.firstHitOnly = visibilityContext?.acceleratedRaycast === true" in html
    assert "/static/vendor/three-mesh-bvh/0.5.23/three-mesh-bvh.umd.js" in html
    assert "Object.freeze([9, 21])" in html
    assert "visibilityContext?.candidatesAt(point) || pageMeshes" in html
    assert "routingContext.visibilityContext?.candidatesAt(point)" in html
    assert "visibilityContext: calloutVisibilityContext" in html
    assert "let projectedPointCount = 0" in html
    assert "projectedLeft = Math.min(projectedLeft, x)" in html
    assert "Math.min(...points.map(point => point.x))" not in html
    assert "frontmost_camera_raycast" in html
    assert "function _partsManualRouteCallouts(" in html
    assert "function _partsManualRouteCalloutsLocal(" in html
    assert "function _partsManualCalloutLayoutMetrics(" in html
    assert "function _partsManualAllCalloutSegments(row)" in html
    assert "_partsManualAllCalloutSegments(row).some(segment" in html
    assert "branch.leaderBalloonCollisionCount === 0" in html
    assert "leaderBalloonCollisionCount" in html
    assert "nearParallelCongestionCount" in html
    assert "maximumDetourRatio" in html
    assert "function _partsManualSeparateBalloonOverlaps(" in html
    assert "_partsManualSeparateBalloonOverlaps(composed.routed)" in html
    assert "leaderStyle: 'orthogonal'" in html
    assert "geometryIntersectionCount" in html
    assert "leaderCrossingCount" in html
    assert "function _partsManualApplyRepeatedCalloutStrategy(" in html
    assert "calloutType = 'branched'" in html
    assert "calloutType = 'representative_with_count'" in html
    assert "anchorScope: 'manual_group'" in html
    assert "function _partsManualCaptureAndStorePage(" in html
    assert "PARTS_MANUAL_CAPTURE_HEAP_CEILING_BYTES = 768 * 1024 * 1024" in html
    assert "function _documentationCaptureMemorySample(stage, page = null)" in html
    assert "function _documentationYieldAfterTechnicalCapture(page)" in html
    assert "Technical capture paused at ${usedMb} MB of browser heap" in html
    assert "canvas.width = 1" in html
    assert "canvas.height = 1" in html
    assert "form.append('renderPipelineVersion'" in html
    assert "occupancy: widthFraction * heightFraction" in html
    assert "occupancyMetric: 'bounding_box_area'" in html
    assert "Math.sqrt(observedArea / targetAreaOccupancy)" in html
    assert "imageRequest.maximumForegroundAxisOccupancy" in html
    assert "measurementIsAxisConstrained" in html
    assert "axisConstrainedOccupancyPolicy" in html
    assert "Math.sqrt(\n                safeTarget * canvas.width * canvas.height" in html
    assert "function _partsManualLoadProposal(" in html
    assert "function _partsManualApproveProposal(" in html
    assert "Suggest Structure" in html
    assert "Sage Structure Proposal" in html
    assert "/proposal`" in html
    assert "proposal.proposalRevision" in html
    assert "propose_parts_manual_structure:" in html
    assert "readOnly: true" in html
    assert "_partsManualButton('Explode'" in html
    assert "_partsManualButton('Preview Pages'" in html
    assert "Recapture All 3D Views" in html
    assert "Generate PDF" in html
    assert "/pdf`" in html
    assert "function _showDocumentationWorkspace(options = {})" in html
    assert "function _documentationDispatchCommand(" in html
    assert "function _documentationMoveHistory(" in html
    assert "function _documentationAttachCanvasInteractions(" in html
    assert "function _documentationArrangeSelection(" in html
    assert "function _documentationRotateSelection(" in html
    assert "function _documentationSetView(" in html
    assert "function _documentationAdjustExplode(" in html
    assert "function _documentationResetActivePage(" in html
    assert "function _documentationBeginPageElementResize(" in html
    assert "function _documentationSelectedTargets(" in html
    assert "function _partsManualApplyDocumentationComposition(" in html
    assert "function _partsManualApplyDocumentationCalloutOverrides(" in html
    assert "function _documentationRefreshLiveCallouts(" in html
    assert "function _documentationBeginCalloutDrag(" in html
    assert "documentation-callout-handle" in html
    assert "balloonOverrides" in html
    assert "leaderOverrides" in html
    assert "anchorSide" in html
    assert "documentation-scene/commands`" in html
    assert "documentation-scene/${direction}`" in html
    assert "partsManualDocumentationSelection" in html
    assert "CAD-grounded composition" not in html
    assert "_partsManualButton(\n                'Documentation'" in html
    assert "edit_parts_manual_composition:" in html
    assert "{ actor: 'sage' }" in html
    assert "generate_and_publish_parts_manual:" in html
    assert "generate_parts_manual_draft:" in html
    assert "function _partsManualTrustedProposalAssessment(" in html
    assert "async function _partsManualGenerateAndPublish(" in html
    assert "freshCapturePassed" in html
    assert "forceFigureCapture: true" in html
    assert "currentImage.renderPipelineVersion === documentModel.renderPipelineVersion" in html
    assert "reused: false" in html
    assert "async function _partsManualCapturePageWithRetries(" in html
    assert "PARTS_MANUAL_TRUSTED_PROPOSAL_MIN_CONFIDENCE = 0.80" in html
    assert "stage: 'awaiting_review'" in html
    assert "stage: 'published'" in html
    assert "captureReceipts" in html
    assert "sizeBytes: Number(artifact.byteLength || 0)" in html
    assert "function _partsManualOpenPublishedPdf(" in html
    assert "manual-published-pdf-overlay" in html
    assert "generate_and_publish_parts_manual: 1800000" in html


def test_documentation_capture_temporarily_takes_over_the_live_viewport() -> None:
    html = (ROOT / "static" / "index.html").read_text("utf-8")

    assert "function _documentationBeginFigureCaptureTakeover(page)" in html
    assert "function _documentationUpdateFigureCaptureTakeover(page, stage, detail = {})" in html
    assert "function _documentationEndFigureCaptureTakeover(" in html
    assert "documentation-figure-capture-takeover" in html
    assert "documentation-capture-takeover-viewport" in html
    assert "Parts Manual | Live CAD capture" in html
    assert "Operations Manual | Live CAD capture" in html
    assert "Real assembly scene | revision-bound technical capture" in html
    assert "figure_capture_takeover_started" in html
    assert "figure_capture_takeover_finished" in html

    capture = html[
        html.index("async function _partsManualCaptureAndStorePage("):
        html.index("const DOCUMENTATION_ICON_ROOT")
    ]
    assert "_documentationBeginFigureCaptureTakeover(page)" in capture
    assert "_partsManualViewDocumentPage(payload, page)" in capture
    assert "_partsManualWaitForRenderPose()" in capture
    assert "_documentationEndFigureCaptureTakeover(takeover" in capture
    assert "documentModel.documentType" in capture
    assert "operations_and_maintenance_manual" in capture
    assert capture.index("_documentationBeginFigureCaptureTakeover(page)") < capture.index(
        "_partsManualViewDocumentPage(payload, page)"
    )
    assert capture.index("_documentationEndFigureCaptureTakeover(takeover") > capture.index(
        "return result.artifact"
    )


def test_documentation_is_a_first_class_workflow_with_its_own_ribbon() -> None:
    html = (ROOT / "static" / "index.html").read_text("utf-8")

    assert "{ value: 'documentation',  label: 'Documentation',               icon: 'documentation.svg' }" in html
    assert "function _renderDocumentationWorkflowTab(" in html
    assert "function _renderDocumentationWorkflowRibbon(" in html
    assert "_renderDocumentationWorkflowRibbon(ribbon)" in html
    assert "_showDocumentationWorkspace({ workflowMode: true, startBlank: true })" in html
    assert "+ (options.workflowMode ? ' workflow-mode' : '')" in html
    assert "documentation-canvas-stage" in html
    assert "function _documentationGenerateBaseline(" in html
    assert "function _documentationPreparePageGeneration(" in html
    assert "function _documentationRevealPagesSequentially(" in html
    assert "function _documentationBeginSageWork(" in html
    assert "function _documentationCancelSageWork(" in html
    assert "documentation-sage-briefing" in html
    assert "documentation-page-generating" in html
    assert "documentation-page-entering" in html
    assert "workspace.classList.toggle('documentation-empty', visiblePages.length === 0)" in html
    assert "workspace.classList.toggle('sage-working', active)" in html
    assert "_documentationRenderPageRail({ lightweight: true })" in html
    assert "Boolean(state.partsManualDocumentationSageWork?.active)" in html
    assert "documentationGenerationSnapshot" in html
    assert "function _documentationCaptureAllPages(" in html
    assert "function _documentationPublishPdf(" in html
    assert "Refreshing ${pending.length} technical figure" in html
    assert "await _documentationCaptureAllPages({" in html
    assert "throwOnError: true" in html
    assert "documentationBaselineRibbon" in html
    assert "documentationUndoRibbon" in html
    assert "documentationCaptureAllRibbon" in html
    assert "documentationResetPageRibbon" in html
    assert "DOCUMENTATION_RIBBON_TABS" not in html
    assert "documentation-ribbon-tabbar" not in html
    assert "documentationInspectorRibbon" in html
    assert "function _documentationToggleInspector(" in html
    assert "function _documentationAttachStagePageNavigation(" in html
    assert "stage.dataset.pageWheelNavigation = 'true'" in html
    assert "stage.addEventListener('wheel', onWheel, { passive: false, capture: true })" in html
    assert "documentation-ribbon-menu" in html
    assert "documentation-ribbon-stack" in html
    assert "documentation-ribbon-secondary-stack" in html
    assert "documentationOverflowMenuRibbon" in html
    assert "container-name: documentation-ribbon" in html
    assert "@container documentation-ribbon (max-width: 1450px)" in html
    assert "{ primary: true, size: 'large' }" in html
    assert "{ compact: true, size: 'compact' }" in html
    assert "'capture', specification ? 'Capture Product' : 'Capture'" in html
    assert "'documentationCaptureRibbon', () => _documentationCaptureActivePage()" in html
    assert "'fit', 'Fit to Page'" in html
    assert "documentationAlignMenuRibbon" in html
    assert "documentationViewMenuRibbon" in html
    assert "documentationArrangeMenuRibbon" in html
    assert "documentationBalloonMenuRibbon" in html
    assert "documentationLeaderMenuRibbon" in html
    assert "documentationShapesMenuRibbon" in html
    assert "documentationInsertImageRibbon" in html
    assert "documentationInsertLogoRibbon" in html
    assert "documentationThemeRibbon" in html
    assert "documentationView${name}Ribbon" in html
    assert "documentationExplodeLessRibbon" in html
    assert "documentationExplodeMoreRibbon" in html
    assert "documentationRotateLeftRibbon" in html
    assert "documentationAlignLeftRibbon" in html
    assert "documentationAlignTopRibbon" in html
    assert "documentationDistributeHorizontalRibbon" in html
    assert "documentationPublishRibbon" in html
    assert "documentationPublicationSurface" in html
    assert "_documentationRenderPublicationPage(" in html
    assert "function _documentationRenderAcceptedCapture(" in html
    assert "documentation-accepted-capture" in html
    assert "function _documentationBuildCalloutSvg(" in html
    assert "documentation-publication-callouts" in html
    assert "Edit the live CAD composition" in html
    assert "DOCUMENTATION_FALLBACK_PUBLICATION_LAYOUT" in html
    assert "pageElementOverrides" in html
    assert "_documentationBeginPageElementDrag(" in html
    assert "function _documentationPages()" in html
    assert "documentationPageStaticContent" in html
    assert "documentation-page-thumbnail" in html
    assert "documentation-resize-handle" in html
    assert "documentation-snap-guide" in html
    assert "documentation-rail-splitter" in html
    assert "documentation-properties-splitter" in html
    assert "documentationZoomRange" in html
    assert "function _documentationSetZoom(" in html
    assert "function _documentationNudgeSelection(" in html
    assert "/static/assets/documentation-ribbon-icons/" in html
    assert "_documentationTheme().annotation?.leaderColor || '#111820'" in html

    icon_root = ROOT / "static" / "assets" / "documentation-ribbon-icons"
    for icon in (
        "documentation.svg",
        "ai-arrange.svg",
        "align-distribute.svg",
        "view-style.svg",
        "balloon.svg",
        "leader-anchor.svg",
        "shapes.svg",
        "publish-pdf.svg",
    ):
        assert (icon_root / icon).is_file()

    bvh_root = ROOT / "static" / "vendor" / "three-mesh-bvh" / "0.5.23"
    assert (bvh_root / "three-mesh-bvh.umd.js").stat().st_size > 100_000
    assert (bvh_root / "LICENSE").is_file()


def test_occurrence_identity_is_not_reduced_to_part_number_in_manual_isolation() -> None:
    html = (ROOT / "static" / "index.html").read_text("utf-8")

    assert "assyOccurrenceMeshMap" in html
    assert "occurrenceByExactName" in html
    assert "exactOccurrenceMap" in html
    assert "child.userData._manualOccurrenceId = occurrenceId" in html
    assert "meshes.filter(mesh => !claimedMeshes.has(mesh))" in html
    assert "row.occurrenceId" in html
    assert "row.occurrenceIds" in html
    assert "state.partsManualIsolatedOccurrenceIds = new Set(mapped)" in html


def test_documentation_authoring_chrome_follows_dark_theme_without_tinting_pages() -> None:
    html = (ROOT / "static" / "index.html").read_text("utf-8")

    assert ':root[data-theme="light"] .ribbon.documentation-workflow-ribbon' in html
    assert ':root[data-theme="dark"] .documentation-workspace.workflow-mode' in html
    assert ':root[data-theme="dark"] .ribbon.documentation-workflow-ribbon' in html
    assert "--documentation-chrome: #171e27" in html
    assert "--documentation-chrome-raised: #202a35" in html
    assert "--documentation-workspace-surface: #2a333d" in html
    assert "publication page and page thumbnails intentionally stay white" in html
    dark_theme_block = html.split(
        "publication page and page thumbnails intentionally stay white", 1
    )[1].split("@media (max-width: 900px)", 1)[0]
    assert ':root[data-theme="dark"] .documentation-page-thumbnail {' not in dark_theme_block
    assert ':root[data-theme="dark"] .documentation-viewport-guide {' not in dark_theme_block


def test_documentation_defaults_repeated_parts_to_one_counted_leader() -> None:
    """Automatic generation must never choose a branched leader on its own."""
    html = (ROOT / "static" / "index.html").read_text("utf-8")

    assert (
        "const PARTS_MANUAL_DEFAULT_REPEATED_PART_STRATEGY = 'representative_with_count';"
        in html
    )
    assert "const PARTS_MANUAL_REPEATED_PART_STRATEGIES = [" in html

    # The strategy comes from the page contract plus any explicit leader
    # override, never from whether branch routing happens to be feasible.
    assert "const requestedStrategyFor = row => {" in html
    assert "override?.repeatedPartStrategy" in html
    assert "calloutContract?.defaultRepeatedPartStrategy" in html
    assert "if (requestedStrategy !== 'branched') {" in html
    assert "applyRepresentative(null);" in html

    # An authored branch layout that will not validate degrades to the default
    # instead of emitting an invalid one, and records why.
    assert "applyRepresentative('branch_routing_failed');" in html
    assert "applyRepresentative('branch_budget_exceeded');" in html
    assert "strategyFallbackReason" in html

    # Route ranking must not reward candidates that produced fewer
    # representative_with_count callouts.
    assert "fallbacks: route.routed.filter(row =>" not in html
    assert "|| left.fallbacks - right.fallbacks" not in html
    assert "degraded: route.routed.filter(row =>" in html
    assert "row.repeatedPartStrategySource === 'override_fallback'" in html
    assert "|| left.degraded - right.degraded" in html


def test_documentation_selects_a_deterministic_representative_occurrence() -> None:
    """One repeated part, one anchor - chosen the same way every time."""
    html = (ROOT / "static" / "index.html").read_text("utf-8")

    assert "const representativeRegion = groupScoped || regions.length <= 1" in html
    assert "regionSalience(right) - regionSalience(left)" in html
    assert "|| right.samples.length - left.samples.length" in html
    assert (
        "|| String(left.occurrenceId).localeCompare(String(right.occurrenceId))" in html
    )

    # The aggregate anchor candidates are built from that one occurrence, so the
    # router cannot silently anchor on a different one.
    assert "const anchorSamples = groupScoped ? samples : representativeRegion.samples;" in html
    assert "center: serialize(selectCenter(anchorSamples))," in html
    assert "left: serialize(sideAnchor(anchorSamples, 'left'))," in html
    assert "representativeOccurrenceId: groupScoped" in html

    # A user may still ask for a branched leader per occurrence, from the leader
    # ribbon as well as through Sage.
    assert "function _documentationSetRepeatedPartStrategy(strategy, options = {})" in html
    assert "_documentationDispatchCommand('set_repeated_strategy', null, {" in html
    assert "id: 'documentationRepeatedCountedRibbon'," in html
    assert "id: 'documentationRepeatedBranchedRibbon'," in html
    assert "_documentationSetRepeatedPartStrategy('branched')" in html
    assert "_documentationSetRepeatedPartStrategy('representative_with_count')" in html


def test_documentation_automatic_leaders_default_to_a_dot_endpoint() -> None:
    """No generated leader may fall back to an arrowhead."""
    html = (ROOT / "static" / "index.html").read_text("utf-8")

    assert "const PARTS_MANUAL_DEFAULT_END_CONDITION = 'dot';" in html
    # Every automatic fallback routes through the constant; a literal 'arrow'
    # default anywhere would let the viewport disagree with the PDF.
    assert "|| 'arrow'" not in html
    assert "|| PARTS_MANUAL_DEFAULT_END_CONDITION" in html

    # The dot itself: small, solid, near-black, matching the PDF annotation ink.
    assert ".documentation-callout-end-dot {" in html
    assert "background: #111820;" in html

    # All three endpoints stay user-selectable.
    assert "for (const endCondition of ['arrow', 'dot', 'none'])" in html
    assert "_documentationSetLeaderEndCondition('arrow')" in html


def test_exact_route_qa_can_select_a_complete_alternate_placement() -> None:
    """Exact raycast QA must be able to change the anchor and balloon together."""
    html = (ROOT / "static" / "index.html").read_text("utf-8")

    assert "function _partsManualCalloutPlacement(row)" in html
    assert "function _partsManualApplyEvaluatedRoute(row, evaluation)" in html
    assert "rowChoice._placementAlternatives = [];" in html
    assert "if (rowChoice._placementAlternatives.length >= 24) return;" in html
    assert "placements.push(...(row._placementAlternatives || []));" in html
    assert "delete row._placementAlternatives;" in html

    # Manual edits are exact authored geometry. Automatic QA may reject them,
    # but it must not silently replace the user's route with a generated one.
    assert "if (row.manualOverrideApplied === true) {" in html
    assert "authored._routeAlternatives = [authored.leaderPath];" in html

    # A small service item almost enclosed by a larger ring is separated before
    # routing. The bounded area-ratio guard excludes similarly sized assemblies.
    assert "maximumOverlapRatio >= 0.92 && areaRatio <= 0.65" in html


def test_direct_manipulation_does_not_recompose_the_exploded_view() -> None:
    """Ordinary annotation and CAD edits stay local to the edited objects."""
    html = (ROOT / "static" / "index.html").read_text("utf-8")

    assert "function _documentationCommandRefreshMode(command)" in html
    assert "return 'annotations_only';" in html
    assert "return 'local_cad';" in html
    assert "return 'recompose_figure';" in html
    assert "function _documentationRefreshAfterSceneCommand(" in html
    assert "function _documentationApplyLiveCadCommand(page, command, options = {})" in html

    dispatch = html.split(
        "async function _documentationDispatchCommand(", 1
    )[1].split("function _documentationNewObjectId", 1)[0]
    assert "const appliedCommand = result.command || body;" in dispatch
    assert "await _documentationRefreshAfterSceneCommand(" in dispatch
    assert "const requiresCadRefresh" not in dispatch
    assert "['figure', 'manual_group', 'occurrence', 'balloon', 'leader']" not in dispatch

    # Dragging a component previews only its selected meshes and associated
    # anchors. Saving that drag must not apply the same delta a second time.
    assert "calloutLayoutSnapshot: _documentationCloneCalloutLayout(" in html
    assert "calloutAnchorWorlds: _documentationCalloutAnchorWorldSnapshot()" in html
    assert "_documentationPreviewCadTranslation(" in html
    assert "localPreviewApplied: true" in html
    assert "calloutPreviewApplied: true" in html

    # Counted repeated parts follow only the occurrence carrying the actual
    # representative anchor, not every occurrence represented by the BOM row.
    assert "if (row.anchorOccurrenceId) {" in html
    assert "String(row.anchorOccurrenceId) === String(target.targetId)" in html

    history = html.split(
        "async function _documentationMoveHistory(", 1
    )[1].split("function _documentationCameraPlaneDelta", 1)[0]
    assert "const historyCommand = direction === 'undo'" in history
    assert "await _documentationRefreshAfterSceneCommand(" in history
    assert "_partsManualViewDocumentPage" not in history

    # Capture remains the deliberate point where the complete revision-bound
    # figure is rebuilt and validated.
    capture = html.split(
        "async function _partsManualCaptureAndStorePage(", 1
    )[1].split("const DOCUMENTATION_ICON_ROOT", 1)[0]
    assert "_partsManualViewDocumentPage(payload, page);" in capture
