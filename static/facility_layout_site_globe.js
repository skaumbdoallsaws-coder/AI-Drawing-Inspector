/* Site tab: the globe flight to a newly placed site (presentation only).
 *
 * When a layout is placed at an address or coordinates, a globe of public imagery turns
 * to the place and dives in while the server fetches the aerial photo. It holds there
 * until the photo is ready, then fades into the Site view at the same framing. The
 * imagery is the USGS Imagery basemap (NASA Blue Marble, Landsat, NAIP; public domain),
 * relayed by the server like every other site request. Nothing here is stored.
 * MapLibre GL JS (BSD-3, vendored) draws the globe; it loads on the first flight, not
 * with the page.
 */
(function (root, factory) {
    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilitySiteGlobe = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
    'use strict';
    const LIBRARY = '/static/vendor/maplibre-gl/6.13.0/';
    const EARTH_CIRCUMFERENCE_METERS = 40075016.686;
    const TILE_MAX_ZOOM = 16;
    const DIVE_MS = 5000;
    const READY_WAIT_MS = 4000;
    const SETTLE_MS = 800;
    const FADE_MS = 700;
    const CREDIT = 'Globe: USGS The National Map (NASA Blue Marble, Landsat, NAIP), public domain';
    let library = null;

    // The MapLibre zoom for a ground resolution: at zoom 0 the Earth is 512 pixels around.
    function zoomForMetersPerPixel(metersPerPixel, latitude) {
        return Math.log2(EARTH_CIRCUMFERENCE_METERS * Math.cos(latitude * Math.PI / 180) / (512 * metersPerPixel));
    }

    // The whole Earth, about three quarters of the shorter side across.
    function globeZoom(width, height) {
        return Math.log2(0.75 * Math.max(64, Math.min(width, height)) * Math.PI / 512);
    }

    function arcDegrees(a, b) {
        const rad = Math.PI / 180;
        const cos = Math.sin(a.latitude * rad) * Math.sin(b.latitude * rad)
            + Math.cos(a.latitude * rad) * Math.cos(b.latitude * rad) * Math.cos((b.longitude - a.longitude) * rad);
        return Math.acos(Math.max(-1, Math.min(1, cos))) / rad;
    }

    // Start over the previous site, or a quarter turn away so the globe visibly turns.
    function startPoint(target, previous) {
        if (previous) return { latitude: previous.latitude, longitude: previous.longitude };
        return { latitude: 20, longitude: ((target.longitude + 80 + 540) % 360) - 180 };
    }

    function spinMilliseconds(degrees) {
        return Math.round(900 + 1300 * Math.min(1, Math.max(0, degrees) / 180));
    }

    function globeStyle(tileUrl) {
        return {
            version: 8,
            projection: { type: 'globe' },
            // 256-pixel tiles drawn at 512: a quarter of the requests, still sharp while moving.
            sources: { earth: { type: 'raster', tiles: [tileUrl], tileSize: 512, maxzoom: TILE_MAX_ZOOM } },
            layers: [{ id: 'ocean', type: 'background', paint: { 'background-color': '#0b1d33' } },
                { id: 'earth', type: 'raster', source: 'earth' }],
            sky: { 'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 1, 7, 0] },
            light: { anchor: 'map', position: [1.5, 90, 80] },
        };
    }

    // People who ask for less motion get the photo without the flight.
    function wanted(documentRef) {
        const view = documentRef && documentRef.defaultView;
        try {
            return !(view && view.matchMedia && view.matchMedia('(prefers-reduced-motion: reduce)').matches);
        } catch (error) {
            return true;
        }
    }

    function loadLibrary(documentRef) {
        if (!library) {
            const styles = new Promise(function (resolve) {
                const link = documentRef.createElement('link');
                link.rel = 'stylesheet';
                link.href = LIBRARY + 'maplibre-gl.css';
                link.onload = resolve;
                link.onerror = resolve;
                documentRef.head.appendChild(link);
            });
            library = Promise.all([import(LIBRARY + 'maplibre-gl.mjs'), styles]).then(function (loaded) { return loaded[0]; });
            library.catch(function () { library = null; });
        }
        return library;
    }

    function createFlight(options) {
        const documentRef = options.document;
        const host = options.host;
        let phase = 'flying';
        let map = null;
        let arrive = null;
        const arrived = new Promise(function (resolve) { arrive = resolve; });

        function node(tag, className, text) {
            const result = documentRef.createElement(tag);
            result.className = className;
            if (text) result.textContent = text;
            return result;
        }
        const overlay = node('div', 'ip-flw-site-globe');
        const canvasHost = node('div', 'ip-flw-site-globe-map');
        const skip = node('button', 'ip-flw-site-globe-skip', 'Skip');
        skip.type = 'button';
        skip.addEventListener('click', function () { end(); });
        overlay.appendChild(canvasHost);
        overlay.appendChild(skip);
        overlay.appendChild(node('div', 'ip-flw-site-globe-credit', CREDIT));

        function end() {
            if (phase === 'done') return;
            phase = 'done';
            arrive();
            if (map) {
                try { map.remove(); } catch (error) { /* already released */ }
                map = null;
            }
            if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
            if (options.onEnd) options.onEnd();
        }

        // Resolves when the camera stops, or a little after it should have.
        function move(method, camera) {
            return new Promise(function (resolve) {
                if (!map) { resolve(); return; }
                let settled = false;
                const done = function () { if (!settled) { settled = true; resolve(); } };
                map.once('moveend', done);
                setTimeout(done, (camera.duration || 0) + 1500);
                map[method](Object.assign({ essential: true }, camera));
            });
        }

        async function fly(target) {
            host.appendChild(overlay);
            let maplibre = null;
            try {
                maplibre = await (options.loadLibrary || loadLibrary)(documentRef);
            } catch (error) {
                end();
                return;
            }
            if (phase !== 'flying') return;
            const start = startPoint(target, target.previous);
            const zoom = globeZoom(host.clientWidth - target.padLeft, host.clientHeight);
            try {
                map = new maplibre.Map({
                    container: canvasHost, style: globeStyle(options.tileUrl),
                    center: [start.longitude, start.latitude], zoom: zoom,
                    interactive: false, attributionControl: false,
                    // Tiles passed on the way down stay as parents for the next zoom.
                    cancelPendingTileRequestsWhileZooming: false,
                });
            } catch (error) {
                end();  // no WebGL: the photo simply appears
                return;
            }
            map.on('error', function () { /* a missing tile leaves its parent showing */ });
            map.setPadding({ left: target.padLeft, right: 0, top: 0, bottom: 0 });
            await new Promise(function (resolve) {
                map.once('load', resolve);
                setTimeout(resolve, 8000);
            });
            if (phase !== 'flying') return;
            const place = [target.longitude, target.latitude];
            await move('easeTo', { center: place, zoom: zoom + 0.15, duration: spinMilliseconds(arcDegrees(start, target)) });
            if (phase !== 'flying') return;
            // Hover over the place until the server has the dive's tiles, but not for long.
            await Promise.race([Promise.resolve(target.ready).catch(function () {}),
                new Promise(function (resolve) { setTimeout(resolve, READY_WAIT_MS); })]);
            if (phase !== 'flying') return;
            await move('flyTo', { center: place, zoom: target.zoom - 0.35, duration: DIVE_MS });
            if (phase !== 'flying') return;
            phase = 'waiting';
            arrive();
        }

        async function leave() {
            if (phase === 'done') return;
            phase = 'leaving';
            overlay.classList.add('ip-flw-site-globe-leaving');
            await new Promise(function (resolve) { setTimeout(resolve, FADE_MS); });
            end();
        }

        // The photo is ready beneath: finish the dive, settle on its framing, fade into it.
        // Without a camera (the photo did not come) the globe fades out at once.
        async function land(camera) {
            if (!camera) return leave();
            await arrived;
            if (phase !== 'waiting') return undefined;
            phase = 'settling';
            await move('easeTo', { center: [camera.longitude, camera.latitude],
                zoom: zoomForMetersPerPixel(camera.metersPerPixel, camera.latitude), duration: SETTLE_MS });
            return leave();
        }

        return { fly: fly, land: land, cancel: end };
    }

    return {
        zoomForMetersPerPixel: zoomForMetersPerPixel,
        globeZoom: globeZoom,
        arcDegrees: arcDegrees,
        startPoint: startPoint,
        spinMilliseconds: spinMilliseconds,
        globeStyle: globeStyle,
        wanted: wanted,
        createFlight: createFlight,
    };
}));
