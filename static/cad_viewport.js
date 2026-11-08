/* Shared Assembly/Packaging viewport presentation; no model coordinates are changed. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.InspectorProCadViewport = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function cssColor(document, name, fallback) {
    try {
      return document.defaultView.getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
    } catch (_) { return fallback; }
  }

  function createBackgroundTexture(threeRuntime, document) {
    const isLight = document.documentElement.getAttribute('data-theme') === 'light';
    const canvas = document.createElement('canvas');
    canvas.width = 1024;
    canvas.height = 768;
    const ctx = canvas.getContext('2d');
    if (!ctx || typeof threeRuntime.CanvasTexture !== 'function') {
      return new threeRuntime.Color(cssColor(document, '--viewport-bg', isLight ? '#bbc5ce' : '#22272F'));
    }
    const center = cssColor(document, '--viewport-bg-center', isLight ? '#98a4af' : '#1c232c');
    const mid = cssColor(document, '--viewport-bg-mid', isLight ? '#c4ced7' : '#2b333e');
    const edge = cssColor(document, '--viewport-bg-edge', isLight ? '#f3f7fa' : '#343c47');

    // Assembly's existing studio band, side wash and light-theme radial falloff.
    const band = ctx.createLinearGradient(0, 0, 0, canvas.height);
    band.addColorStop(0.00, edge);
    band.addColorStop(0.27, mid);
    band.addColorStop(0.50, center);
    band.addColorStop(0.73, mid);
    band.addColorStop(1.00, edge);
    ctx.fillStyle = band;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const wash = ctx.createLinearGradient(0, 0, canvas.width, 0);
    wash.addColorStop(0.00, isLight ? 'rgba(255,255,255,0.20)' : 'rgba(255,255,255,0.04)');
    wash.addColorStop(0.50, 'rgba(255,255,255,0.00)');
    wash.addColorStop(1.00, isLight ? 'rgba(255,255,255,0.20)' : 'rgba(255,255,255,0.04)');
    ctx.fillStyle = wash;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    if (isLight) {
      const centerFalloff = ctx.createRadialGradient(
        canvas.width * 0.50, canvas.height * 0.43, canvas.width * 0.05,
        canvas.width * 0.50, canvas.height * 0.43, canvas.width * 0.55
      );
      centerFalloff.addColorStop(0.00, 'rgba(54,68,82,0.24)');
      centerFalloff.addColorStop(0.36, 'rgba(84,100,116,0.14)');
      centerFalloff.addColorStop(0.72, 'rgba(255,255,255,0.00)');
      ctx.fillStyle = centerFalloff;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    const texture = new threeRuntime.CanvasTexture(canvas);
    if (threeRuntime.SRGBColorSpace !== undefined) texture.colorSpace = threeRuntime.SRGBColorSpace;
    else if (threeRuntime.sRGBEncoding !== undefined) texture.encoding = threeRuntime.sRGBEncoding;
    texture.needsUpdate = true;
    return texture;
  }

  function createOrientationGizmo(THREE, container) {
    const document = container.ownerDocument;
    const size = 80;
    const canvas = document.createElement('canvas');
    canvas.className = 'orientation-gizmo';
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', 'XYZ view orientation');
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setClearColor(0x000000, 0);
    renderer.setPixelRatio(2);
    renderer.setSize(size, size, false);
    container.appendChild(canvas);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100);
    const quaternion = new THREE.Quaternion();
    const axes = new THREE.Group();
    const axisLen = 0.8;
    const colors = [0xff4444, 0x44ff44, 0x4488ff];
    const labels = ['X', 'Y', 'Z'];
    for (let axis = 0; axis < 3; axis++) {
      const end = new THREE.Vector3().setComponent(axis, axisLen);
      const geometry = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), end]);
      axes.add(new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: colors[axis], linewidth: 2 })));
      const label = document.createElement('canvas');
      label.width = 64; label.height = 64;
      const ctx = label.getContext('2d');
      ctx.font = 'bold 40px sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillStyle = '#' + colors[axis].toString(16).padStart(6, '0');
      ctx.fillText(labels[axis], 32, 32);
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(label), depthTest: false }));
      sprite.position.copy(end).setComponent(axis, axisLen + 0.15);
      sprite.scale.set(0.3, 0.3, 0.3);
      axes.add(sprite);
    }
    axes.add(new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 12), new THREE.MeshBasicMaterial({ color: 0x888888 })));
    scene.add(axes);
    let disposed = false;
    return {
      canvas,
      update(mainCamera) {
        if (disposed) return;
        // Only world rotation is copied. Pan, distance and model origin are irrelevant.
        mainCamera.getWorldQuaternion(quaternion);
        camera.quaternion.copy(quaternion);
        camera.position.set(0, 0, 3).applyQuaternion(quaternion);
        renderer.render(scene, camera);
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        axes.traverse(object => {
          // Sprite geometry belongs to Three.js and is shared across widgets.
          if (!object.isSprite) object.geometry?.dispose();
          if (object.material) {
            object.material.map?.dispose();
            object.material.dispose();
          }
        });
        renderer.dispose();
        canvas.remove();
      }
    };
  }

  return { createBackgroundTexture, createOrientationGizmo };
});
