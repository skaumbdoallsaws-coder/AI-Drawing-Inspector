import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { ORIENTATION_ORDERS, orientationRows, placementCenter } from './packaging.js';

export function orientationMatrix(index) {
  const r = orientationRows(index);
  return new THREE.Matrix4().set(r[0][0], r[0][1], r[0][2], 0, r[1][0], r[1][1], r[1][2], 0,
    r[2][0], r[2][1], r[2][2], 0, 0, 0, 0, 1);
}

export class PackagingScene {
  constructor(host, { onStatus = () => {}, onSelect = () => {} } = {}) {
    this.host = host; this.onStatus = onStatus; this.onSelect = onSelect;
    this.disposed = false; this.section = false; this.exploded = false; this.design = null;
    this.packageId = null; this.componentId = null; this.sourceKey = null; this.sourceModel = null;
    this.sourceError = ''; this.sourceLoading = false; this.loadVersion = 0; this.viewKey = null;
    this.resources = new Set(); this.pickable = []; this.frame = 0;
    this.scene = new THREE.Scene(); this.scene.background = new THREE.Color(0x303438);
    this.camera = new THREE.PerspectiveCamera(40, 1, .0001, 1000);
    this.camera.position.set(1, .8, 1.2);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping; this.renderer.toneMappingExposure = 1.25;
    this.renderer.domElement.tabIndex = 0;
    this.renderer.domElement.setAttribute('aria-label', '3D package model. Orbit and zoom controls.');
    this.renderer.domElement.setAttribute('role', 'img');
    host.prepend(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = false; this.controls.screenSpacePanning = true; this.controls.maxPolarAngle = Math.PI;
    this.controls.addEventListener('change', () => this.invalidate());
    this.scene.add(new THREE.HemisphereLight(0xf1f7ff, 0x737873, 2.5));
    const key = new THREE.DirectionalLight(0xffffff, 3.2); key.position.set(2, 4, 3); this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xd9efff, 1.5); fill.position.set(-3, 1, -2); this.scene.add(fill);
    this.content = new THREE.Group(); this.scene.add(this.content);
    this.bounds = new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(.4, .3, .25));
    this.resizeObserver = new ResizeObserver(() => this.fit()); this.resizeObserver.observe(host);
    this.pointerDown = event => { this.pointerStart = [event.clientX, event.clientY]; };
    this.pointerUp = event => {
      if (event.button !== 0 || !this.pointerStart || Math.hypot(event.clientX - this.pointerStart[0], event.clientY - this.pointerStart[1]) > 4) return;
      const rect = this.renderer.domElement.getBoundingClientRect();
      const point = new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
      const raycaster = new THREE.Raycaster(); raycaster.setFromCamera(point, this.camera);
      const hit = raycaster.intersectObjects(this.pickable, true).find(h => !this.section || h.point.y <= this.cutHeight);
      if (hit) { let node = hit.object; while (node && !node.userData.componentId) node = node.parent; if (node) this.onSelect(node.userData.componentId); }
    };
    this.contextLost = event => { event.preventDefault(); this.onStatus('3D graphics context lost. Reload to restore the view; unsaved document changes are retained.'); };
    this.renderer.domElement.addEventListener('pointerdown', this.pointerDown);
    this.renderer.domElement.addEventListener('pointerup', this.pointerUp);
    this.renderer.domElement.addEventListener('webglcontextlost', this.contextLost);
    this.resize();
  }

  own(resource) { this.resources.add(resource); return resource; }

  resize() {
    if (this.disposed) return;
    const width = Math.max(1, this.host.clientWidth), height = Math.max(1, this.host.clientHeight);
    this.renderer.setSize(width, height, false); this.camera.aspect = width / height; this.camera.updateProjectionMatrix();
    this.invalidate();
  }

  invalidate() {
    if (this.frame || this.disposed) return;
    this.frame = requestAnimationFrame(() => { this.frame = 0; if (!this.disposed) this.renderer.render(this.scene, this.camera); });
  }

  setDesign(design, packageId, componentId) {
    this.design = design; this.packageId = packageId; this.componentId = componentId;
    const product = design.product, sourceKey = product?.source_id ? `${product.source_id}:${product.source_revision}` : null;
    if (sourceKey !== this.sourceKey) {
      this.loadVersion++; this.abortController?.abort(); this.disposeSource(); this.sourceKey = sourceKey; this.sourceError = '';
      this.sourceLoading = !!sourceKey;
      if (sourceKey) this.loadSource(product, this.loadVersion);
    }
    const carton = design.packages.find(p => p.id === packageId)?.carton;
    const key = `${packageId || 'unpacked'}:${sourceKey || (product ? product.dimensions_m.join(',') : 'empty')}:${carton?.inner_m.join(',') || ''}`;
    const changedView = key !== this.viewKey; this.viewKey = key;
    this.rebuild(); if (changedView) this.view('iso');
  }

  async loadSource(product, version) {
    this.abortController = new AbortController();
    let loaded;
    try {
      const response = await fetch(`/api/packaging/sources/${encodeURIComponent(product.source_id)}.glb`, {
        headers: { 'X-InspectorPro-Request': 'packaging' }, credentials: 'same-origin', cache: 'no-store', signal: this.abortController.signal
      });
      if (!response.ok) throw new Error(`Source GLB unavailable (HTTP ${response.status}).`);
      const data = await response.arrayBuffer();
      loaded = (await new GLTFLoader().parseAsync(data, '')).scene;
      if (this.disposed || version !== this.loadVersion) { this.disposeTree(loaded); return; }
      loaded.updateMatrixWorld(true);
      const box = new THREE.Box3().setFromObject(loaded), size = box.getSize(new THREE.Vector3());
      if (box.isEmpty() || size.toArray().some((n, i) => !Number.isFinite(n) || Math.abs(n - product.dimensions_m[i]) > Math.max(1e-5, product.dimensions_m[i] * .001))) {
        throw new Error('Source geometry bounds differ from the immutable source dimensions.');
      }
      // The server converts source units to meters. Only center here; never rescale to a carton.
      const center = box.getCenter(new THREE.Vector3()), centered = new THREE.Group();
      loaded.position.sub(center); centered.add(loaded); centered.updateMatrixWorld(true);
      this.sourceModel = centered; this.sourceLoading = false; this.rebuild(); this.fit();
    } catch (error) {
      if (loaded && !this.sourceModel) this.disposeTree(loaded);
      if (this.disposed || version !== this.loadVersion) return;
      this.sourceLoading = false; this.sourceError = error.message; this.rebuild();
    }
  }

  disposeTree(root) {
    const geometries = new Set(), materials = new Set(), textures = new Set();
    root?.traverse(node => {
      if (node.geometry) geometries.add(node.geometry);
      for (const material of Array.isArray(node.material) ? node.material : node.material ? [node.material] : []) {
        materials.add(material); for (const value of Object.values(material)) if (value?.isTexture) textures.add(value);
      }
    });
    for (const resource of [...geometries, ...materials, ...textures]) resource.dispose();
  }

  disposeSource() { if (this.sourceModel) this.disposeTree(this.sourceModel); this.sourceModel = null; }

  clear() {
    this.content.clear(); for (const resource of this.resources) resource.dispose(); this.resources.clear(); this.pickable = [];
  }

  box(dimensions, center, color, opacity = 1) {
    const geometry = this.own(new THREE.BoxGeometry(...dimensions));
    const material = this.own(new THREE.MeshStandardMaterial({ color, roughness: .7, metalness: .04,
      transparent: opacity < 1, opacity, depthWrite: opacity >= 1, side: THREE.DoubleSide }));
    const mesh = new THREE.Mesh(geometry, material); mesh.position.fromArray(center); return mesh;
  }

  outline(dimensions, center, color, dashed = false) {
    const box = new THREE.BoxGeometry(...dimensions), edges = this.own(new THREE.EdgesGeometry(box)); box.dispose();
    const span = Math.max(...dimensions);
    const material = this.own(dashed ? new THREE.LineDashedMaterial({ color, dashSize: span / 20, gapSize: span / 35 }) : new THREE.LineBasicMaterial({ color, transparent: true, opacity: .85 }));
    const line = new THREE.LineSegments(edges, material); line.position.fromArray(center); if (dashed) line.computeLineDistances(); return line;
  }

  label(text, position, size, color = '#e4edf0') {
    const canvas = document.createElement('canvas'); canvas.width = 512; canvas.height = 64;
    const context = canvas.getContext('2d'); context.clearRect(0, 0, 512, 64);
    context.font = '26px Segoe UI, sans-serif'; context.fillStyle = color; context.textAlign = 'center'; context.textBaseline = 'middle';
    context.fillText(text, 256, 32, 500);
    const texture = this.own(new THREE.CanvasTexture(canvas)); texture.colorSpace = THREE.SRGBColorSpace;
    const material = this.own(new THREE.SpriteMaterial({ map: texture, depthTest: false, transparent: true }));
    const sprite = new THREE.Sprite(material); sprite.position.fromArray(position); sprite.scale.set(size, size / 8, 1); this.content.add(sprite);
  }

  rebuild() {
    if (!this.design || this.disposed) return;
    this.clear();
    const product = this.design.product, pkg = this.design.packages.find(p => p.id === this.packageId);
    const dims = pkg?.carton.inner_m || product?.dimensions_m || [.4, .3, .25];
    const extent = Math.max(...dims), originCenter = dims.map(x => x / 2);
    if (pkg) {
      this.content.add(this.box(pkg.carton.outer_m, originCenter, 0xcbd0c9, .07), this.outline(pkg.carton.outer_m, originCenter, 0x9ba59d), this.outline(dims, originCenter, 0x74b8d2));
      const clearance = this.design.constraints.clearance_m;
      if (clearance > 0 && dims.every(x => x > 2 * clearance)) this.content.add(this.outline(dims.map(x => x - 2 * clearance), originCenter, 0x737f87, true));
    }
    const placements = pkg?.placements || (product ? [{ id: null, position_m: [0, 0, 0], orientation: 0 }] : []);
    if (product) placements.forEach((placement, index) => {
      const oriented = ORIENTATION_ORDERS[placement.orientation].map(i => product.dimensions_m[i]);
      const position = placementCenter(product.dimensions_m, placement);
      if (this.exploded && pkg) position[1] += extent * (.35 + index * .12);
      const group = new THREE.Group(); group.userData.componentId = placement.id;
      if (product.source_id && this.sourceModel) {
        const rotation = new THREE.Group(); rotation.setRotationFromMatrix(orientationMatrix(placement.orientation));
        rotation.add(this.sourceModel.clone(true)); rotation.position.fromArray(position); group.add(rotation);
      } else {
        group.add(this.box(oriented, position, product.source_id ? 0x77838d : 0x4f94bd, product.source_id ? .16 : .7));
      }
      const selected = placement.id && placement.id === this.componentId;
      group.add(this.outline(oriented, position, selected ? 0xf1cd67 : 0x72b5d9, !!product.source_id && !this.sourceModel));
      this.content.add(group); if (placement.id) this.pickable.push(group);
      if (!product.source_id && (selected || index === 0)) this.label('Manual geometry', [position[0], position[1] + oriented[1] / 2 + extent * .035, position[2]], extent * .6);
    });
    pkg?.inserts.forEach((pad, index) => {
      const center = pad.position_m.map((p, i) => p + pad.dimensions_m[i] / 2);
      if (this.exploded) { center[0] += extent * .5; center[1] += extent * (.1 + index * .12); }
      const group = new THREE.Group(); group.userData.componentId = pad.id;
      group.add(this.box(pad.dimensions_m, center, 0x67b59b, .8), this.outline(pad.dimensions_m, center, this.componentId === pad.id ? 0xf1cd67 : 0x82d8bd));
      this.content.add(group); this.pickable.push(group);
    });
    this.bounds = new THREE.Box3().setFromObject(this.content);
    if (this.bounds.isEmpty()) this.bounds.set(new THREE.Vector3(), new THREE.Vector3(...dims));
    const grid = new THREE.GridHelper(extent * 3, 20, 0x737e85, 0x424b51); grid.position.set(dims[0] / 2, -extent * .015, dims[2] / 2);
    this.own(grid.geometry); for (const material of Array.isArray(grid.material) ? grid.material : [grid.material]) this.own(material);
    this.content.add(grid);
    const axisLength = extent * .23;
    const axes = new THREE.AxesHelper(axisLength); this.own(axes.geometry); this.own(axes.material); this.content.add(axes);
    this.label('X', [axisLength * 1.12, 0, 0], extent * .19, '#f4a4a4');
    this.label('Y', [0, axisLength * 1.12, 0], extent * .19, '#b5dfad');
    this.label('Z', [0, 0, axisLength * 1.12], extent * .19, '#9ecdf5');
    this.cutHeight = dims[1] / 2;
    this.applySection();
    this.onStatus(this.sourceLoading ? 'Loading imported source geometry...' : this.sourceError ? `${this.sourceError} Only the source envelope is shown.` :
      !product ? 'No product selected' : pkg && !pkg.placements.length ? 'No product instances in this carton' : '');
    this.invalidate();
  }

  applySection() {
    this.renderer.clippingPlanes = this.section ? [new THREE.Plane(new THREE.Vector3(0, -1, 0), this.cutHeight)] : [];
    this.invalidate();
  }

  setSection(enabled) { this.section = enabled; this.applySection(); }
  setExploded(enabled) { this.exploded = enabled; this.rebuild(); }

  fit(direction) {
    if (this.disposed) return;
    this.resize();
    const center = this.bounds.getCenter(new THREE.Vector3()), size = this.bounds.getSize(new THREE.Vector3());
    const radius = Math.max(size.length() / 2, .001);
    const vFov = THREE.MathUtils.degToRad(this.camera.fov), hFov = 2 * Math.atan(Math.tan(vFov / 2) * this.camera.aspect);
    const distance = radius / Math.sin(Math.min(vFov, hFov) / 2) * 1.18;
    const vector = direction || this.camera.position.clone().sub(this.controls.target).normalize();
    if (vector.lengthSq() === 0) vector.set(1, .75, 1);
    this.camera.position.copy(center).addScaledVector(vector.normalize(), distance);
    this.camera.near = Math.max(.00001, radius / 1000); this.camera.far = Math.max(100, distance * 50);
    this.camera.updateProjectionMatrix(); this.controls.target.copy(center);
    this.controls.minDistance = radius * .03; this.controls.maxDistance = distance * 30; this.controls.update(); this.invalidate();
  }

  view(name) {
    const views = { iso: [1, .8, 1.15], top: [0, 1, .000001], front: [0, 0, 1], side: [1, 0, 0] };
    this.fit(new THREE.Vector3(...(views[name] || views.iso)));
  }

  dispose() {
    this.disposed = true; this.loadVersion++; this.abortController?.abort(); cancelAnimationFrame(this.frame);
    this.resizeObserver.disconnect(); this.controls.dispose(); this.clear(); this.disposeSource();
    this.renderer.domElement.removeEventListener('pointerdown', this.pointerDown);
    this.renderer.domElement.removeEventListener('pointerup', this.pointerUp);
    this.renderer.domElement.removeEventListener('webglcontextlost', this.contextLost);
    this.renderer.dispose(); this.renderer.domElement.remove();
  }
}
