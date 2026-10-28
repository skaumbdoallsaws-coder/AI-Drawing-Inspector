(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityFinishes = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    // Library finishes for Facility models: texture coordinates in meters,
    // materials and a shared texture cache.
    //
    // CAD-derived library models almost never carry UVs, so textured finishes
    // project their own. Coordinates are object-space meters, which keeps a
    // texture's physical size the same on a 0.5 m bin and a 12 m rack; the
    // material's texture repeat is 1 / tile size. The texture's U axis follows
    // the chosen grain axis (length, width or height of the object), so wood
    // grain and brushing run along a rack's length.

    const FINISH_FLAG = 'facilityAppearanceFinish';
    const LIBRARY_TEXTURE_FLAG = 'facilityLibraryTexture';
    const AXES = ['x', 'y', 'z'];
    // Above this, splitting vertices per face would cost too much memory; such
    // meshes project per vertex instead and accept seams on curved faces.
    const MAX_SPLIT_TRIANGLES = 1500000;

    function axisIndex(axis) { return AXES.indexOf(axis); }

    // 'part' means each mesh's own long side; callers resolve it per mesh
    // (see partAxis). Here it falls back to the object's length.
    function grainAxis(bounds, grain) {
        if (grain === 'height') return 'y';
        const size = function (axis) {
            return bounds ? Math.abs(Number(bounds.max[axis]) - Number(bounds.min[axis])) || 0 : 0;
        };
        const longer = size('x') >= size('z') ? 'x' : 'z';
        if (grain === 'width') return longer === 'x' ? 'z' : 'x';
        return longer;
    }

    // Axes of the projection plane for a face whose normal is dominant on
    // `dominant`, with U along the grain wherever the grain lies in the plane.
    function planeAxes(dominant, grain) {
        if (dominant !== grain) {
            const v = AXES.find(function (axis) { return axis !== dominant && axis !== grain; });
            return [grain, v];
        }
        // End grain: keep a stable, non-mirrored choice.
        if (grain === 'x') return ['z', 'y'];
        if (grain === 'z') return ['x', 'y'];
        return ['x', 'z'];
    }

    // positions: Float32Array of triangle-ordered vertices (x, y, z) in meters.
    function boxUVs(positions, grain) {
        const count = Math.floor(positions.length / 9);
        const uv = new Float32Array(count * 6);
        for (let t = 0; t < count; t += 1) {
            const o = t * 9;
            const ax = positions[o + 3] - positions[o], ay = positions[o + 4] - positions[o + 1], az = positions[o + 5] - positions[o + 2];
            const bx = positions[o + 6] - positions[o], by = positions[o + 7] - positions[o + 1], bz = positions[o + 8] - positions[o + 2];
            const nx = Math.abs(ay * bz - az * by), ny = Math.abs(az * bx - ax * bz), nz = Math.abs(ax * by - ay * bx);
            const dominant = nx >= ny && nx >= nz ? 'x' : (ny >= nz ? 'y' : 'z');
            const pair = planeAxes(dominant, grain);
            const u = axisIndex(pair[0]), v = axisIndex(pair[1]);
            for (let k = 0; k < 3; k += 1) {
                uv[t * 6 + k * 2] = positions[o + k * 3 + u];
                uv[t * 6 + k * 2 + 1] = positions[o + k * 3 + v];
            }
        }
        return uv;
    }

    // U runs along the axis (meters); V is the arc length around it, so the
    // grain follows a pipe or rod. Triangles that straddle the seam unwrap.
    function cylindricalUVs(positions, axis, center, radius) {
        const count = Math.floor(positions.length / 9);
        const uv = new Float32Array(count * 6);
        const a = axisIndex(axis);
        const others = AXES.filter(function (name) { return name !== axis; }).map(axisIndex);
        const r = Math.max(0.001, Number(radius) || 0.001);
        const angles = [0, 0, 0];
        for (let t = 0; t < count; t += 1) {
            const o = t * 9;
            for (let k = 0; k < 3; k += 1) {
                const p = o + k * 3;
                angles[k] = Math.atan2(positions[p + others[1]] - center[others[1]], positions[p + others[0]] - center[others[0]]);
            }
            if (Math.max(angles[0], angles[1], angles[2]) - Math.min(angles[0], angles[1], angles[2]) > Math.PI) {
                for (let k = 0; k < 3; k += 1) if (angles[k] < 0) angles[k] += Math.PI * 2;
            }
            for (let k = 0; k < 3; k += 1) {
                uv[t * 6 + k * 2] = positions[o + k * 3 + a];
                uv[t * 6 + k * 2 + 1] = angles[k] * r;
            }
        }
        return uv;
    }

    function transformedPositions(THREE, attribute, matrix) {
        const output = new Float32Array(attribute.count * 3);
        const vector = new THREE.Vector3();
        for (let i = 0; i < attribute.count; i += 1) {
            vector.fromBufferAttribute(attribute, i);
            if (matrix) vector.applyMatrix4(matrix);
            output[i * 3] = vector.x; output[i * 3 + 1] = vector.y; output[i * 3 + 2] = vector.z;
        }
        return output;
    }

    // Per-vertex projection for very large indexed meshes: no vertex splitting,
    // so a face whose vertices disagree on the dominant axis may stretch.
    function vertexBoxUVs(THREE, geometry, matrix, grain) {
        const position = geometry.attributes.position, normal = geometry.attributes.normal;
        const points = transformedPositions(THREE, position, matrix);
        const normalMatrix = new THREE.Matrix3();
        if (matrix) normalMatrix.getNormalMatrix(matrix);
        const vector = new THREE.Vector3();
        const uv = new Float32Array(position.count * 2);
        for (let i = 0; i < position.count; i += 1) {
            let dominant = 'y';
            if (normal) {
                vector.fromBufferAttribute(normal, i).applyMatrix3(normalMatrix);
                const x = Math.abs(vector.x), y = Math.abs(vector.y), z = Math.abs(vector.z);
                dominant = x >= y && x >= z ? 'x' : (y >= z ? 'y' : 'z');
            }
            const pair = planeAxes(dominant, grain);
            uv[i * 2] = points[i * 3 + axisIndex(pair[0])];
            uv[i * 2 + 1] = points[i * 3 + axisIndex(pair[1])];
        }
        return uv;
    }

    // A copy of `geometry` with a `uv` attribute in meters. `matrix` places the
    // mesh in the asset's own space; positions and normals stay untouched.
    function finishGeometry(THREE, geometry, matrix, options) {
        const settings = options || {};
        const mapping = settings.mapping || 'box';
        if (mapping === 'uv' && geometry.attributes.uv) return geometry;
        const grain = settings.axis || 'x';
        const position = geometry.attributes && geometry.attributes.position;
        if (!position) return geometry;
        const triangles = geometry.index ? geometry.index.count / 3 : position.count / 3;
        let result;
        if (triangles > MAX_SPLIT_TRIANGLES && geometry.index) {
            result = geometry.clone();
            result.setAttribute('uv', new THREE.Float32BufferAttribute(vertexBoxUVs(THREE, geometry, matrix, grain), 2));
        } else {
            result = geometry.index ? geometry.toNonIndexed() : geometry.clone();
            const points = transformedPositions(THREE, result.attributes.position, matrix);
            const uv = mapping === 'cylindrical'
                ? cylindricalUVs(points, grain, settings.center || [0, 0, 0], settings.radius)
                : boxUVs(points, grain);
            result.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
        }
        // Models exported without normals (bare bounding boxes) render black
        // under a finish's normal map; the finish copy gets normals of its own.
        if (!result.attributes.normal && typeof result.computeVertexNormals === 'function') result.computeVertexNormals();
        result.userData = Object.assign({}, result.userData, { facilityFinishGeometry: true });
        return result;
    }

    function createTextureCache(THREE, options) {
        const settings = options || {};
        const entries = new Map();
        function loader() {
            return settings.textureLoader || (typeof THREE.TextureLoader === 'function' ? new THREE.TextureLoader() : null);
        }
        function entry(url, colorSpace) {
            const key = url + '|' + colorSpace;
            if (entries.has(key)) return entries.get(key);
            const record = { url: url, status: 'loading', base: null, clones: new Set(), waiters: [] };
            entries.set(key, record);
            const textureLoader = loader();
            if (!textureLoader) {
                record.status = 'failed';
                return record;
            }
            record.base = textureLoader.load(url, function () {
                record.status = 'ready';
                record.clones.forEach(function (texture) { texture.needsUpdate = true; });
                record.waiters.splice(0).forEach(function (waiter) { waiter.resolve(true); });
                if (settings.onChange) settings.onChange();
            }, undefined, function () {
                record.status = 'failed';
                record.waiters.splice(0).forEach(function (waiter) { waiter.resolve(false); });
                if (settings.onChange) settings.onChange();
                if (settings.onError) settings.onError(url);
            });
            record.base.colorSpace = colorSpace;
            record.base.userData = Object.assign({}, record.base.userData, { [LIBRARY_TEXTURE_FLAG]: true });
            return record;
        }
        // A per-material copy sharing the image, so each use can carry its own
        // repeat, rotation and offset while the pixels upload once.
        function instance(url, colorSpace, transform, onFailed) {
            const record = entry(url, colorSpace);
            if (record.status === 'failed' || !record.base) return null;
            const texture = record.base.clone();
            texture.userData = Object.assign({}, texture.userData, { [LIBRARY_TEXTURE_FLAG]: true });
            if (THREE.RepeatWrapping !== undefined) texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
            if (transform) {
                texture.repeat.set(transform.repeat, transform.repeat);
                texture.rotation = transform.rotation || 0;
                texture.offset.set(transform.offset[0], transform.offset[1]);
            }
            if (settings.anisotropy) texture.anisotropy = settings.anisotropy;
            if (record.status === 'ready') texture.needsUpdate = true;
            record.clones.add(texture);
            if (record.status === 'loading' && onFailed) {
                record.waiters.push({ resolve: function (ok) { if (!ok) onFailed(texture); } });
            }
            return texture;
        }
        function whenSettled() {
            return Promise.all(Array.from(entries.values()).map(function (record) {
                if (record.status !== 'loading') return record.status === 'ready';
                return new Promise(function (resolve) { record.waiters.push({ resolve: resolve }); });
            }));
        }
        function forget(texture) {
            entries.forEach(function (record) { record.clones.delete(texture); });
        }
        function dispose() {
            entries.forEach(function (record) {
                record.clones.forEach(function (texture) { texture.dispose(); });
                if (record.base) record.base.dispose();
            });
            entries.clear();
        }
        function stats() {
            let clones = 0, failed = 0, ready = 0;
            entries.forEach(function (record) {
                clones += record.clones.size;
                if (record.status === 'failed') failed += 1;
                if (record.status === 'ready') ready += 1;
            });
            return { images: entries.size, ready: ready, failed: failed, uses: clones };
        }
        return { instance: instance, whenSettled: whenSettled, forget: forget, dispose: dispose, stats: stats };
    }

    function colorSpaces(THREE) {
        return { color: THREE.SRGBColorSpace || 'srgb', data: THREE.NoColorSpace || '' };
    }

    // One material for one resolved finish. Missing textures fall back to the
    // finish's tint, so a project still opens and reads correctly offline.
    function createFinishMaterial(THREE, resolved, context) {
        const settings = context || {};
        const physical = resolved.model === 'physical' && typeof THREE.MeshPhysicalMaterial === 'function';
        const Type = physical ? THREE.MeshPhysicalMaterial : THREE.MeshStandardMaterial;
        const fallbackFlags = [];
        if (resolved.missing) {
            const neutral = new THREE.MeshStandardMaterial({ color: 0x9aa2a9, roughness: 0.7, metalness: 0.04 });
            neutral.name = 'FacilityFinish:missing:' + resolved.appearanceId;
            neutral.userData = { [FINISH_FLAG]: true, appearanceId: resolved.appearanceId, fallback: ['appearance_missing'] };
            return neutral;
        }
        const opacity = Number.isFinite(resolved.opacity) ? resolved.opacity : 1;
        const parameters = {
            color: resolved.color || '#ffffff',
            roughness: Number.isFinite(resolved.roughness) ? resolved.roughness : 0.6,
            metalness: Number.isFinite(resolved.metalness) ? resolved.metalness : 0,
            transparent: opacity < 0.999,
            opacity: opacity,
            depthWrite: opacity >= 0.999,
        };
        if (physical) {
            ['transmission', 'ior', 'thickness', 'clearcoat', 'clearcoatRoughness'].forEach(function (key) {
                if (Number.isFinite(resolved[key])) parameters[key] = resolved[key];
            });
        }
        const material = new Type(parameters);
        material.name = 'FacilityFinish:' + resolved.appearanceId;
        material.userData = { [FINISH_FLAG]: true, appearanceId: resolved.appearanceId, fallback: fallbackFlags };
        const texture = resolved.texture;
        if (texture && texture.maps && settings.textures) {
            const scale = Number(settings.scale) || 1;
            const size = Math.max(0.01, Number(texture.sizeMeters) || Number(texture.tileMeters) || 1);
            const strength = Number.isFinite(texture.strength) ? texture.strength : 1;
            const offset = texture.offsetMeters || [0, 0];
            const transform = {
                repeat: scale / size,
                rotation: (Number(texture.rotationDegrees) || 0) * Math.PI / 180,
                offset: [offset[0] / size, offset[1] / size],
            };
            const spaces = colorSpaces(THREE);
            const maps = texture.maps;
            const drop = function (slot, reason) {
                return function () {
                    material[slot] = null;
                    material.needsUpdate = true;
                    if (fallbackFlags.indexOf(reason) < 0) fallbackFlags.push(reason);
                };
            };
            const colorUrl = maps.color || maps.detail;
            if (colorUrl) material.map = settings.textures.instance(colorUrl, spaces.color, transform, drop('map', 'color_texture_missing'));
            if (maps.normal) {
                material.normalMap = settings.textures.instance(maps.normal, spaces.data, transform, drop('normalMap', 'normal_texture_missing'));
                if (material.normalScale) material.normalScale.set(strength, strength);
            }
            if (maps.roughness) {
                material.roughnessMap = settings.textures.instance(maps.roughness, spaces.data, transform, drop('roughnessMap', 'roughness_texture_missing'));
                // The roughness value is the finish's average roughness; the map
                // multiplies it, so divide by the map's own average.
                const mean = Number(texture.roughnessMean) > 0.02 ? Number(texture.roughnessMean) : 1;
                if (material.roughnessMap) material.roughness = Math.min(4, parameters.roughness / mean);
            }
            if (maps.ao) {
                material.aoMap = settings.textures.instance(maps.ao, spaces.data, transform, drop('aoMap', 'ao_texture_missing'));
                material.aoMapIntensity = strength;
            }
            [['map', 'color_texture_missing'], ['normalMap', 'normal_texture_missing'],
                ['roughnessMap', 'roughness_texture_missing'], ['aoMap', 'ao_texture_missing']].forEach(function (pair) {
                const wanted = pair[0] === 'map' ? colorUrl : maps[{ normalMap: 'normal', roughnessMap: 'roughness', aoMap: 'ao' }[pair[0]]];
                if (wanted && !material[pair[0]] && fallbackFlags.indexOf(pair[1]) < 0) fallbackFlags.push(pair[1]);
            });
        }
        if (settings.envMap) {
            material.envMap = settings.envMap;
            material.envMapIntensity = Number.isFinite(settings.envMapIntensity) ? settings.envMapIntensity : 0.7;
        }
        material.needsUpdate = true;
        return material;
    }

    function isFinishMaterial(material) {
        return Boolean(material && material.userData && material.userData[FINISH_FLAG] === true);
    }

    function isLibraryTexture(texture) {
        return Boolean(texture && texture.userData && texture.userData[LIBRARY_TEXTURE_FLAG] === true);
    }

    function boundsOf(THREE, object) {
        const box = new THREE.Box3();
        if (typeof box.setFromObject === 'function') box.setFromObject(object);
        if (box.isEmpty && box.isEmpty()) return null;
        return { min: { x: box.min.x, y: box.min.y, z: box.min.z }, max: { x: box.max.x, y: box.max.y, z: box.max.z } };
    }

    // Mapping parameters for one object: the grain axis comes from the object's
    // bounds, so "length" means the long horizontal side of this asset.
    function mappingFor(THREE, object, resolved, explicitBounds) {
        const texture = resolved && resolved.texture;
        if (!texture) return null;
        const bounds = explicitBounds || boundsOf(THREE, object);
        const grain = texture.grain || 'length';
        const axis = grainAxis(bounds, grain);
        const center = bounds ? AXES.map(function (name) { return (bounds.min[name] + bounds.max[name]) / 2; }) : [0, 0, 0];
        const others = AXES.filter(function (name) { return name !== axis; });
        const radius = bounds ? others.reduce(function (sum, name) {
            return sum + Math.abs(bounds.max[name] - bounds.min[name]) / 4;
        }, 0) : 1;
        return { mapping: texture.mapping || 'box', axis: axis, center: center, radius: radius, perPart: grain === 'part' };
    }

    // The long side of one mesh as placed in the asset: a table leg is
    // vertical, its top runs along the table, a rack beam along the rack.
    function partAxis(THREE, geometry, matrix) {
        if (!geometry.boundingBox && typeof geometry.computeBoundingBox === 'function') geometry.computeBoundingBox();
        if (!geometry.boundingBox) return 'x';
        const box = geometry.boundingBox.clone();
        if (matrix) box.applyMatrix4(matrix);
        const x = box.max.x - box.min.x, y = box.max.y - box.min.y, z = box.max.z - box.min.z;
        return x >= y && x >= z ? 'x' : (y >= z ? 'y' : 'z');
    }

    function meshMapping(THREE, geometry, matrix, mapping) {
        if (!mapping || !mapping.perPart) return mapping;
        return Object.assign({}, mapping, { axis: partAxis(THREE, geometry, matrix) });
    }

    // Cache key for one projected geometry: source geometry, its placement in
    // the asset, and every mapping input that changes the coordinates.
    function geometryKey(geometry, matrix, mapping) {
        const elements = matrix && matrix.elements ? Array.from(matrix.elements).map(function (n) { return n.toFixed(5); }).join(',') : 'identity';
        const cylinder = mapping.mapping === 'cylindrical'
            ? '|' + mapping.center.map(function (n) { return Number(n).toFixed(4); }).join(',') + ',' + Number(mapping.radius).toFixed(4) : '';
        return geometry.uuid + '|' + elements + '|' + mapping.mapping + '|' + mapping.axis + cylinder;
    }

    function cachedFinishGeometry(THREE, cache, geometry, matrix, mapping) {
        if (!mapping || !geometry) return geometry;
        const effective = meshMapping(THREE, geometry, matrix, mapping);
        const key = geometryKey(geometry, matrix, effective);
        if (!cache.has(key)) cache.set(key, finishGeometry(THREE, geometry, matrix, effective));
        return cache.get(key);
    }

    // Give every mesh under `object` the finish. `geometryCache` lets clones of
    // one prototype share the projected geometry. Authored surfaces (printed
    // artwork) keep their own materials.
    function applyFinishToObject(THREE, object, material, mapping, options) {
        const settings = options || {};
        const cache = settings.geometryCache || new Map();
        if (typeof object.updateMatrixWorld === 'function') object.updateMatrixWorld(true);
        const rootInverse = new THREE.Matrix4();
        if (object.matrixWorld) rootInverse.copy(object.matrixWorld).invert();
        const replaced = [];
        object.traverse(function (mesh) {
            if (!mesh.isMesh || !mesh.geometry || !mesh.material || mesh.isInstancedMesh) return;
            const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
            if (materials.some(function (item) { return settings.skip && settings.skip(item, mesh); })) return;
            if (mapping) {
                const relative = new THREE.Matrix4().multiplyMatrices(rootInverse, mesh.matrixWorld);
                mesh.geometry = cachedFinishGeometry(THREE, cache, mesh.geometry, relative, mapping);
            }
            replaced.push(mesh.material);
            mesh.material = material;
        });
        return replaced;
    }

    return {
        FINISH_FLAG: FINISH_FLAG,
        LIBRARY_TEXTURE_FLAG: LIBRARY_TEXTURE_FLAG,
        MAX_SPLIT_TRIANGLES: MAX_SPLIT_TRIANGLES,
        grainAxis: grainAxis,
        planeAxes: planeAxes,
        boxUVs: boxUVs,
        cylindricalUVs: cylindricalUVs,
        finishGeometry: finishGeometry,
        createTextureCache: createTextureCache,
        createFinishMaterial: createFinishMaterial,
        isFinishMaterial: isFinishMaterial,
        isLibraryTexture: isLibraryTexture,
        mappingFor: mappingFor,
        partAxis: partAxis,
        geometryKey: geometryKey,
        cachedFinishGeometry: cachedFinishGeometry,
        applyFinishToObject: applyFinishToObject,
    };
}));
