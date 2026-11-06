import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { ORIENTATION_ORDERS, orientationRows, placementCenter } from './packaging.js';

export const PACKAGING_TOLERANCE_M = 1e-6;

export function orientationMatrix(index) {
  const r = orientationRows(index);
  return new THREE.Matrix4().set(r[0][0], r[0][1], r[0][2], 0, r[1][0], r[1][1], r[1][2], 0,
    r[2][0], r[2][1], r[2][2], 0, 0, 0, 0, 1);
}

export function sourceBounds(model, dimensions) {
  model.updateMatrixWorld(true);
  // Transformed local boxes overestimate angled parts; compare actual vertices.
  const box = new THREE.Box3().setFromObject(model, true), size = box.getSize(new THREE.Vector3());
  if (box.isEmpty() || size.toArray().some((n, i) => !Number.isFinite(n) || Math.abs(n - dimensions[i]) > Math.max(1e-5, dimensions[i] * .001))) {
    throw new Error('Source geometry bounds differ from the immutable source dimensions.');
  }
  return box;
}

export function displayMaterialSettings(mode, transparency, appearance = null) {
  if (!['shaded', 'edges', 'wireframe', 'appearance'].includes(mode) || !Number.isFinite(transparency) || transparency < 0 || transparency > 85) {
    throw new Error('Unsupported display settings.');
  }
  const visual = mode === 'appearance' ? appearance : null;
  const opacity = (visual?.opacity ?? 1) * (1 - transparency / 100);
  return { color: visual?.color ?? 0xb9bfc5, roughness: visual?.roughness ?? .72, metalness: visual?.metalness ?? .08, wireframe: mode === 'wireframe',
    opacity, transparent: opacity < 1, depthWrite: opacity === 1,
    side: THREE.DoubleSide, polygonOffset: mode === 'edges', polygonOffsetFactor: 1, polygonOffsetUnits: 1 };
}

// Mirror components.py's signed footprint distance; AABBs do not describe circular voids.
export function pocketFootprintDistance(a, b) {
  const [ax, , az] = a.position_m, [bx, , bz] = b.position_m;
  const [aw, , ad] = a.dimensions_m, [bw, , bd] = b.dimensions_m;
  if (a.shape === 'cylindrical' && b.shape === 'cylindrical') {
    return Math.hypot(ax + aw / 2 - bx - bw / 2, az + ad / 2 - bz - bd / 2) - (aw + bw) / 2;
  }
  if (a.shape === 'cylindrical' || b.shape === 'cylindrical') {
    const [circle, rectangle] = a.shape === 'cylindrical' ? [a, b] : [b, a];
    const radius = circle.dimensions_m[0] / 2, x = circle.position_m[0] + radius, z = circle.position_m[2] + radius;
    const [rx, , rz] = rectangle.position_m, [rw, , rd] = rectangle.dimensions_m;
    return Math.hypot(Math.max(rx - x, 0, x - rx - rw), Math.max(rz - z, 0, z - rz - rd)) - radius;
  }
  const dx = Math.max(ax - bx - bw, bx - ax - aw), dz = Math.max(az - bz - bd, bz - az - ad);
  return dx >= 0 || dz >= 0 ? Math.hypot(Math.max(dx, 0), Math.max(dz, 0)) : Math.max(dx, dz);
}

export function insertGeometries(insert) {
  const [width, height, length] = insert.dimensions_m, pockets = insert.pockets || [];
  for (const pocket of pockets) {
    if (!['rectangular', 'cylindrical'].includes(pocket.shape)
        || pocket.dimensions_m.some(value => !Number.isFinite(value) || value <= 0)
        || pocket.position_m.some((value, axis) => !Number.isFinite(value) || value < 0 || value + pocket.dimensions_m[axis] > insert.dimensions_m[axis] + PACKAGING_TOLERANCE_M)
        || Math.abs(pocket.position_m[1] + pocket.dimensions_m[1] - height) > PACKAGING_TOLERANCE_M
        || (pocket.shape === 'cylindrical' && Math.abs(pocket.dimensions_m[0] - pocket.dimensions_m[2]) > 1e-9)) {
      throw new Error('Pocket display requires contained top-opening cuts.');
    }
  }
  for (let i = 0; i < pockets.length; i++) for (let j = i + 1; j < pockets.length; j++) {
    if (pocketFootprintDistance(pockets[i], pockets[j]) < -PACKAGING_TOLERANCE_M) throw new Error('Overlapping pocket display is not supported.');
  }
  const levels = [...new Set([0, height, ...pockets.map(pocket => pocket.position_m[1])])].sort((a, b) => a - b);
  return levels.slice(1).map((high, index) => {
    const low = levels[index], outline = new THREE.Shape();
    outline.moveTo(0, 0); outline.lineTo(width, 0); outline.lineTo(width, length); outline.lineTo(0, length); outline.closePath();
    for (const pocket of pockets.filter(item => item.position_m[1] <= low)) {
      const [x, , z] = pocket.position_m, [dx, , dz] = pocket.dimensions_m, hole = new THREE.Path();
      if (pocket.shape === 'cylindrical') hole.absarc(x + dx / 2, z + dz / 2, dx / 2, 0, Math.PI * 2, true);
      else { hole.moveTo(x, z); hole.lineTo(x, z + dz); hole.lineTo(x + dx, z + dz); hole.lineTo(x + dx, z); hole.closePath(); }
      outline.holes.push(hole);
    }
    const geometry = new THREE.ExtrudeGeometry(outline, { depth: high - low, bevelEnabled: false, curveSegments: 48, steps: 1 });
    geometry.rotateX(Math.PI / 2); geometry.translate(0, high, 0); return geometry;
  });
}

export function graphicPlacement(dimensions, graphic, aspect) {
  const frames = {
    'x+': [[0, 0, -1], [0, 1, 0], [1, 0, 0], 2, 1, 0],
    'x-': [[0, 0, 1], [0, 1, 0], [-1, 0, 0], 2, 1, 0],
    'y+': [[1, 0, 0], [0, 0, -1], [0, 1, 0], 0, 2, 1],
    'y-': [[1, 0, 0], [0, 0, 1], [0, -1, 0], 0, 2, 1],
    'z+': [[1, 0, 0], [0, 1, 0], [0, 0, 1], 0, 1, 2],
    'z-': [[-1, 0, 0], [0, 1, 0], [0, 0, -1], 0, 1, 2],
  };
  const frame = frames[graphic.face];
  if (!frame || !Number.isFinite(aspect) || aspect <= 0 || ![0, 90, 180, 270].includes(graphic.rotation_degrees)) throw new Error('Invalid graphic placement.');
  const [u, v, normal, uIndex, vIndex, normalIndex] = frame;
  const maxWidth = dimensions[uIndex] * graphic.width_fraction, maxHeight = dimensions[vIndex] * graphic.height_fraction;
  const turned = graphic.rotation_degrees % 180 !== 0, rotatedAspect = turned ? 1 / aspect : aspect;
  const width = Math.min(maxWidth, maxHeight * rotatedAspect), height = width / rotatedAspect;
  const epsilon = Math.max(...dimensions) * .0001;
  const center = dimensions.map((value, axis) => value / 2 + u[axis] * (graphic.u - .5) * dimensions[uIndex]
    + v[axis] * (graphic.v - .5) * dimensions[vIndex] + normal[axis] * (dimensions[normalIndex] / 2 + epsilon));
  return { center, u, v, normal, width: turned ? height : width, height: turned ? width : height, fittedWidth: width, fittedHeight: height };
}

export function graphicPocketPaths(dimensions, graphic, aspect, pockets = []) {
  if (!['y+', 'y-'].includes(graphic.face)) return [];
  const placement = graphicPlacement(dimensions, graphic, aspect);
  const angle = THREE.MathUtils.degToRad(graphic.rotation_degrees), cos = Math.cos(angle), sin = Math.sin(angle);
  // Project local X/Z openings back through the artwork rotation into canvas UVs.
  const project = (x, z) => {
    const dx = x - placement.center[0], dz = z - placement.center[2];
    const u = dx * placement.u[0] + dz * placement.u[2], v = dx * placement.v[0] + dz * placement.v[2];
    return [.5 + (cos * u + sin * v) / placement.width, .5 - (-sin * u + cos * v) / placement.height];
  };
  return pockets.filter(pocket => graphic.face === 'y+' || pocket.position_m[1] <= 1e-9).map(pocket => {
    const [x, , z] = pocket.position_m, [width, , length] = pocket.dimensions_m;
    if (pocket.shape === 'cylindrical') return Array.from({ length: 96 }, (_, index) => {
      const angle = index / 96 * Math.PI * 2;
      return project(x + width / 2 + Math.cos(angle) * width / 2, z + length / 2 + Math.sin(angle) * length / 2);
    });
    return [[x, z], [x + width, z], [x + width, z + length], [x, z + length]].map(([px, pz]) => project(px, pz));
  });
}

export function maskGraphicPockets(canvas, dimensions, graphic, pockets) {
  const paths = graphicPocketPaths(dimensions, graphic, canvas.width / canvas.height, pockets);
  if (!paths.length) return;
  const context = canvas.getContext('2d'); context.save(); context.resetTransform();
  context.globalCompositeOperation = 'destination-out'; context.fillStyle = '#000000';
  for (const path of paths) {
    context.beginPath();
    path.forEach(([u, v], index) => context[index ? 'lineTo' : 'moveTo'](u * canvas.width, v * canvas.height));
    context.closePath(); context.fill();
  }
  context.restore();
}

export function imageCrop(metadata) {
  const { width, height, uv } = metadata;
  if (![width, height].every(value => Number.isInteger(value) && value > 0 && value <= 4096)
    || !Array.isArray(uv) || uv.length !== 4 || !uv.every(value => Number.isFinite(value) && value >= 0 && value <= 1)
    || uv[0] >= uv[2] || uv[1] >= uv[3]) throw new Error('Invalid image artwork metadata.');
  const x = Math.round(uv[0] * width), y = Math.round((1 - uv[3]) * height);
  const cropWidth = Math.round(uv[2] * width) - x, cropHeight = Math.round((1 - uv[1]) * height) - y;
  if (cropWidth < 1 || cropHeight < 1) throw new Error('Empty image artwork crop.');
  return { x, y, width: cropWidth, height: cropHeight };
}

export class PackagingScene {
  constructor(host, { onStatus = () => {}, onSelect = () => {} } = {}) {
    this.host = host; this.onStatus = onStatus; this.onSelect = onSelect;
    this.disposed = false; this.section = false; this.exploded = false; this.design = null;
    this.packageId = null; this.componentId = null; this.graphicId = null; this.sourceKey = null; this.sourceModel = null;
    this.sourceError = ''; this.sourceLoading = false; this.loadVersion = 0; this.viewKey = null;
    this.resources = new Set(); this.pickable = []; this.frame = 0;
    this.displayMode = 'edges'; this.transparency = 0; this.edgeCache = new Map();
    this.images = new Map(); this.imageQueue = Promise.resolve();
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
    this.controls.listenToKeyEvents(this.renderer.domElement);
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
      const hit = raycaster.intersectObjects(this.pickable, true).find(h => {
        if (!h.object.isMesh || (this.section && h.point.y > this.cutHeight)) return false;
        const canvas = h.object.userData.graphicCanvas;
        if (!canvas || !h.uv) return true;
        const x = Math.min(canvas.width - 1, Math.max(0, Math.floor(h.uv.x * canvas.width)));
        const y = Math.min(canvas.height - 1, Math.max(0, Math.floor((1 - h.uv.y) * canvas.height)));
        return canvas.getContext('2d').getImageData(x, y, 1, 1).data[3] > 2;
      });
      if (hit) {
        let node = hit.object;
        while (node && !node.userData.componentId && !node.userData.graphicId) node = node.parent;
        if (node) this.onSelect(node.userData.graphicId || node.userData.componentId, node.userData.graphicId ? 'graphic' : 'component');
      }
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

  setDesign(design, packageId, componentId, graphicId = null) {
    this.design = design; this.packageId = packageId; this.componentId = componentId; this.graphicId = graphicId;
    const product = design.product, sourceKey = product?.source_id ? `${product.source_id}:${product.source_revision}` : null;
    if (sourceKey !== this.sourceKey) {
      this.loadVersion++; this.abortController?.abort(); this.disposeSource(); this.sourceKey = sourceKey; this.sourceError = '';
      this.sourceLoading = !!sourceKey;
      if (sourceKey) this.loadSource(product, this.loadVersion);
    }
    const carton = design.packages.find(p => p.id === packageId)?.carton;
    const key = `${packageId || 'unpacked'}:${sourceKey || (product ? product.dimensions_m.join(',') : 'empty')}:${carton?.inner_m.join(',') || ''}`;
    const changedView = key !== this.viewKey; this.viewKey = key;
    this.syncImages(design.packages.find(p => p.id === packageId)?.graphics || []);
    this.rebuild(); if (changedView) this.view('iso');
  }

  syncImages(graphics) {
    const ids = new Set(graphics.filter(graphic => graphic.kind === 'image').map(graphic => graphic.image_id));
    for (const [id, entry] of this.images) if (!ids.has(id)) { entry.controller.abort(); this.images.delete(id); }
    for (const id of ids) if (!this.images.has(id)) {
      const entry = { controller: new AbortController(), canvas: null, error: '' }; this.images.set(id, entry);
      this.imageQueue = this.imageQueue.catch(() => {}).then(() => this.loadImage(id, entry));
    }
  }

  async loadImage(id, entry) {
    if (this.disposed || entry.controller.signal.aborted) return;
    let bitmap;
    try {
      if (!/^img_[a-f0-9]{32}$/.test(id)) throw new Error('Invalid image artwork reference.');
      const options = { headers: { 'X-InspectorPro-Request': 'packaging' }, credentials: 'same-origin', cache: 'no-store',
        signal: AbortSignal.any([entry.controller.signal, AbortSignal.timeout(30000)]) };
      const metaResponse = await fetch(`/api/packaging/images/${id}`, options);
      if (!metaResponse.ok) throw new Error(`Image metadata unavailable (HTTP ${metaResponse.status}).`);
      const metadata = await metaResponse.json(); if (metadata.id !== id) throw new Error('Image artwork identity differs.');
      const crop = imageCrop(metadata), response = await fetch(`/api/packaging/images/${id}.png`, options);
      if (!response.ok) throw new Error(`Image artwork unavailable (HTTP ${response.status}).`);
      bitmap = await createImageBitmap(await response.blob());
      if (bitmap.width !== metadata.width || bitmap.height !== metadata.height) throw new Error('Image dimensions differ from its metadata.');
      if (this.disposed || entry.controller.signal.aborted || this.images.get(id) !== entry) return;
      const canvas = document.createElement('canvas'), scale = Math.min(1, 2048 / crop.width, 2048 / crop.height);
      canvas.width = Math.max(1, Math.round(crop.width * scale)); canvas.height = Math.max(1, Math.round(crop.height * scale));
      canvas.getContext('2d').drawImage(bitmap, crop.x, crop.y, crop.width, crop.height, 0, 0, canvas.width, canvas.height);
      entry.canvas = canvas;
    } catch (error) { entry.error = error.message; }
    finally {
      bitmap?.close();
      if (!this.disposed && this.images.get(id) === entry) this.rebuild();
    }
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
      const box = sourceBounds(loaded, product.dimensions_m);
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
    this.edgeCache.clear();
  }

  styleComponent(root, appearance = null) {
    const meshes = []; root.traverse(node => { if (node.isMesh) meshes.push(node); });
    const material = this.own(new THREE.MeshStandardMaterial(displayMaterialSettings(this.displayMode, this.transparency, appearance)));
    const edgesMaterial = this.displayMode === 'edges' ? this.own(new THREE.LineBasicMaterial({ color: 0x293238, transparent: this.transparency > 0, opacity: 1 - this.transparency / 180 })) : null;
    for (const mesh of meshes) {
      mesh.material = material;
      if (edgesMaterial) {
        let edges = this.edgeCache.get(mesh.geometry);
        if (!edges) { edges = this.own(new THREE.EdgesGeometry(mesh.geometry, 25)); this.edgeCache.set(mesh.geometry, edges); }
        const lines = new THREE.LineSegments(edges, edgesMaterial); lines.userData.displayEdges = true; mesh.add(lines);
      }
    }
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

  lettering(graphic, dimensions, origin, pockets = []) {
    const canvas = document.createElement('canvas'), measure = canvas.getContext('2d');
    const lines = graphic.text.split(/\r?\n/); measure.font = '600 48px Segoe UI, sans-serif';
    const textWidth = Math.max(1, ...lines.map(line => measure.measureText(line).width)), textHeight = Math.max(60, lines.length * 60);
    const scale = Math.min(1, 2000 / textWidth, 2000 / textHeight);
    canvas.width = Math.ceil(textWidth * scale) + 16; canvas.height = Math.ceil(textHeight * scale) + 16;
    const context = canvas.getContext('2d'); context.scale(scale, scale); context.font = '600 48px Segoe UI, sans-serif';
    context.fillStyle = graphic.color; context.textBaseline = 'top';
    lines.forEach((line, index) => context.fillText(line, 8 / scale, 8 / scale + index * 60));
    this.artwork(canvas, graphic, dimensions, origin, pockets);
  }

  artwork(canvas, graphic, dimensions, origin, pockets = []) {
    maskGraphicPockets(canvas, dimensions, graphic, pockets);
    const texture = this.own(new THREE.CanvasTexture(canvas)); texture.colorSpace = THREE.SRGBColorSpace;
    const placement = graphicPlacement(dimensions, graphic, canvas.width / canvas.height);
    const geometry = this.own(new THREE.PlaneGeometry(placement.width, placement.height));
    const material = this.own(new THREE.MeshBasicMaterial({ map: texture, transparent: true, alphaTest: .01, depthWrite: false, opacity: 1 - this.transparency / 100 }));
    const mesh = new THREE.Mesh(geometry, material);
    const basis = new THREE.Matrix4().makeBasis(new THREE.Vector3(...placement.u), new THREE.Vector3(...placement.v), new THREE.Vector3(...placement.normal));
    mesh.setRotationFromMatrix(basis); mesh.rotateZ(THREE.MathUtils.degToRad(graphic.rotation_degrees));
    mesh.position.fromArray(placement.center.map((value, axis) => value + origin[axis]));
    mesh.userData.graphicId = graphic.id; mesh.userData.graphicCanvas = canvas;
    if (graphic.id === this.graphicId) {
      const outline = new THREE.LineSegments(this.own(new THREE.EdgesGeometry(geometry)), this.own(new THREE.LineBasicMaterial({ color: 0xf1cd67 })));
      mesh.add(outline);
    }
    this.content.add(mesh); this.pickable.push(mesh);
  }

  rebuild() {
    if (!this.design || this.disposed) return;
    this.clear();
    const product = this.design.product, pkg = this.design.packages.find(p => p.id === this.packageId);
    const dims = pkg?.carton.inner_m || product?.dimensions_m || [.4, .3, .25];
    const extent = Math.max(...dims), originCenter = dims.map(x => x / 2);
    if (pkg) {
      const appearance = this.displayMode === 'appearance' ? pkg.carton.appearance : null;
      const carton = this.box(pkg.carton.outer_m, originCenter, appearance?.color || 0xcbd0c9, (appearance?.opacity ?? .07) * (1 - this.transparency / 100));
      if (appearance) { carton.material.roughness = appearance.roughness; carton.material.metalness = appearance.metalness; }
      this.content.add(carton, this.outline(pkg.carton.outer_m, originCenter, 0x9ba59d), this.outline(dims, originCenter, 0x74b8d2));
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
        group.add(this.box(oriented, position, 0xb9bfc5));
      }
      const selected = placement.id && placement.id === this.componentId;
      this.styleComponent(group, product.appearance);
      if (selected || (product.source_id && !this.sourceModel)) group.add(this.outline(oriented, position, selected ? 0xf1cd67 : 0x72b5d9, !!product.source_id && !this.sourceModel));
      this.content.add(group); if (placement.id) this.pickable.push(group);
    });
    let pocketWarning = '';
    pkg?.inserts.forEach((pad, index) => {
      const center = pad.position_m.map((p, i) => p + pad.dimensions_m[i] / 2);
      if (this.exploded) { center[0] += extent * .5; center[1] += extent * (.1 + index * .12); }
      const group = new THREE.Group(); group.userData.componentId = pad.id;
      try {
        const material = this.own(new THREE.MeshStandardMaterial());
        for (const geometry of insertGeometries(pad)) {
          const mesh = new THREE.Mesh(this.own(geometry), material); mesh.position.fromArray(center.map((value, axis) => value - pad.dimensions_m[axis] / 2)); group.add(mesh);
        }
      } catch (error) {
        group.add(this.box(pad.dimensions_m, center, 0xb9bfc5)); pocketWarning = `${error.message} Only the insert envelope is shown. Save to review validation findings.`;
      }
      this.styleComponent(group, pad.appearance);
      if (this.componentId === pad.id) group.add(this.outline(pad.dimensions_m, center, 0xf1cd67));
      this.content.add(group); this.pickable.push(group);
    });
    let graphicWarning = '';
    if (this.displayMode !== 'wireframe') for (const graphic of pkg?.graphics || []) {
      const image = graphic.kind === 'image' ? this.images.get(graphic.image_id) : null;
      if (graphic.kind === 'image' && !image?.canvas) { graphicWarning = image?.error || 'Loading image artwork...'; continue; }
      let dimensions, origin, pockets;
      if (graphic.target === 'carton') {
        dimensions = pkg.carton.outer_m; origin = originCenter.map((value, axis) => value - dimensions[axis] / 2);
      } else {
        const index = pkg.inserts.findIndex(item => item.id === graphic.target_id), pad = pkg.inserts[index];
        if (!pad) continue;
        dimensions = pad.dimensions_m; origin = [...pad.position_m]; pockets = pad.pockets;
        if (this.exploded) { origin[0] += extent * .5; origin[1] += extent * (.1 + index * .12); }
      }
      if (graphic.kind === 'text') this.lettering(graphic, dimensions, origin, pockets);
      else {
        const canvas = document.createElement('canvas'); canvas.width = image.canvas.width; canvas.height = image.canvas.height;
        canvas.getContext('2d').drawImage(image.canvas, 0, 0); this.artwork(canvas, graphic, dimensions, origin, pockets);
      }
    }
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
    this.onStatus(this.sourceLoading ? 'Loading imported source geometry...' : this.sourceError ? `${this.sourceError} Only the source envelope is shown.` : pocketWarning || graphicWarning ? [pocketWarning, graphicWarning].filter(Boolean).join(' ') :
      !product ? 'No product selected' : pkg && !pkg.placements.length ? 'No product instances in this carton' : '');
    this.invalidate();
  }

  applySection() {
    this.renderer.clippingPlanes = this.section ? [new THREE.Plane(new THREE.Vector3(0, -1, 0), this.cutHeight)] : [];
    this.invalidate();
  }

  setSection(enabled) { this.section = enabled; this.applySection(); }
  setExploded(enabled) { this.exploded = enabled; this.rebuild(); }
  setDisplay(mode, transparency = this.transparency) {
    displayMaterialSettings(mode, transparency);
    if (mode === this.displayMode && transparency === this.transparency) return;
    this.displayMode = mode; this.transparency = transparency; this.rebuild();
  }

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
    for (const entry of this.images.values()) entry.controller.abort(); this.images.clear();
  }
}
