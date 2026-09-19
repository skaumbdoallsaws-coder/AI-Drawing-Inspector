'use strict';

// This deliberately moves focus on the controlled inert fixture only. Do not
// run it against InspectorPro: the fixture's parser-time baseline is essential
// to proving that the SVG was focusable before the preload applied its lock.
const FIXTURE_FOCUS_SCRIPT = `(() => {
  const htmlNamespace = 'http://www.w3.org/1999/xhtml';
  const svgNamespace = 'http://www.w3.org/2000/svg';
  const errors = [];
  const describe = node => node ? { tagName: node.tagName, namespaceURI: node.namespaceURI,
    id: node.id || '', connected: node.isConnected === true } : null;
  const baseline = window.__desktopFixtureFocusBaseline;
  const svgs = [...document.querySelectorAll('#desktop-fixture-svg')];
  const banners = [...document.querySelectorAll('#inspectorpro-desktop-spike-banner')];
  const svg = svgs.length === 1 ? svgs[0] : null;
  const banner = banners.length === 1 ? banners[0] : null;
  const closeButtons = banner ? [...banner.querySelectorAll('button')]
    .filter(node => node.textContent.trim() === 'Close preview') : [];
  const close = closeButtons.length === 1 ? closeButtons[0] : null;
  const parent = svg?.parentElement || null;
  let nativeParentInert = false;
  if (parent instanceof HTMLElement) {
    try {
      const getter = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'inert')?.get;
      nativeParentInert = typeof getter === 'function' && getter.call(parent) === true;
    } catch (error) { errors.push('Parent inert inspection: ' + String(error?.message || error)); }
  }
  const proof = { schemaVersion: 1,
    baseline: { svgFocusable: baseline?.svgFocusable === true,
      svgAttributeStillFocusable: baseline?.svgAttributeStillFocusable === true },
    svgCount: svgs.length, bannerCount: banners.length, closeButtonCount: closeButtons.length,
    svg: describe(svg), parent: describe(parent), banner: describe(banner), close: describe(close),
    expectedSvg: !!svg && svg instanceof SVGElement && svg.namespaceURI === svgNamespace
      && svg.localName === 'svg' && svg.isConnected === true,
    nativeHtmlParent: !!parent && parent instanceof HTMLElement && parent.namespaceURI === htmlNamespace
      && parent.isConnected === true && parent.parentElement === document.body,
    nativeParentInert, parentInertAttribute: !!parent && parent.hasAttribute('inert'),
    closeIsButton: !!close && close instanceof HTMLElement && close.namespaceURI === htmlNamespace
      && close.localName === 'button' && close.isConnected === true,
    svgFocusAttempted: false, svgFocusBlocked: false, closeFocusAttempted: false,
    closeFocusAllowed: false, errors };
  if (svg) {
    try {
      svg.blur();
      proof.svgFocusAttempted = true;
      svg.focus({ preventScroll: true });
      proof.svgFocusBlocked = document.activeElement !== svg;
    } catch (error) { errors.push('SVG focus: ' + String(error?.message || error)); }
    finally {
      try { svg.blur(); } catch (error) { errors.push('SVG blur: ' + String(error?.message || error)); }
    }
  }
  if (close) {
    try {
      close.blur();
      proof.closeFocusAttempted = true;
      close.focus({ preventScroll: true });
      proof.closeFocusAllowed = document.activeElement === close;
    } catch (error) { errors.push('Close focus: ' + String(error?.message || error)); }
    finally {
      try { close.blur(); } catch (error) { errors.push('Close blur: ' + String(error?.message || error)); }
    }
  }
  return proof;
})()`;

function assertFixtureFocusProof(evidence) {
  const required = ['expectedSvg', 'nativeHtmlParent', 'nativeParentInert', 'parentInertAttribute',
    'closeIsButton', 'svgFocusAttempted', 'svgFocusBlocked', 'closeFocusAttempted', 'closeFocusAllowed'];
  if (!evidence || evidence.schemaVersion !== 1 || evidence.baseline?.svgFocusable !== true
      || evidence.baseline?.svgAttributeStillFocusable !== true || evidence.svgCount !== 1
      || evidence.bannerCount !== 1 || evidence.closeButtonCount !== 1
      || required.some(key => evidence[key] !== true)
      || !Array.isArray(evidence.errors) || evidence.errors.length !== 0
      || evidence.svg?.id !== 'desktop-fixture-svg' || evidence.svg?.tagName !== 'svg'
      || evidence.svg?.namespaceURI !== 'http://www.w3.org/2000/svg' || evidence.svg?.connected !== true
      || evidence.parent?.namespaceURI !== 'http://www.w3.org/1999/xhtml' || evidence.parent?.connected !== true
      || evidence.banner?.id !== 'inspectorpro-desktop-spike-banner' || evidence.banner?.connected !== true
      || evidence.close?.tagName !== 'BUTTON' || evidence.close?.namespaceURI !== 'http://www.w3.org/1999/xhtml'
      || evidence.close?.connected !== true) {
    throw new Error('Inert fixture native focus proof is incomplete or failed');
  }
  return true;
}

module.exports = { FIXTURE_FOCUS_SCRIPT, assertFixtureFocusProof };
