(function (root, factory) {
    'use strict';

    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityRecorder = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
    'use strict';

    const API_VERSION = 1;
    const FORMAT_CANDIDATES = Object.freeze([
        Object.freeze({
            mimeType: 'video/mp4;codecs=avc1.42E01E',
            extension: 'mp4',
            label: 'MP4 (H.264)',
        }),
        Object.freeze({
            mimeType: 'video/mp4',
            extension: 'mp4',
            label: 'MP4',
        }),
        Object.freeze({
            mimeType: 'video/webm;codecs=vp9',
            extension: 'webm',
            label: 'WebM (VP9)',
        }),
        Object.freeze({
            mimeType: 'video/webm;codecs=vp8',
            extension: 'webm',
            label: 'WebM (VP8)',
        }),
        Object.freeze({
            mimeType: 'video/webm',
            extension: 'webm',
            label: 'WebM',
        }),
    ]);

    function finite(value, fallback) {
        const number = Number(value);
        return Number.isFinite(number) ? number : fallback;
    }

    function cleanString(value, fallback) {
        const text = String(value === undefined || value === null ? '' : value)
            .trim();
        return text || fallback;
    }

    function chooseRecordingFormat(MediaRecorderClass) {
        if (typeof MediaRecorderClass !== 'function') return null;
        const supports = typeof MediaRecorderClass.isTypeSupported === 'function'
            ? MediaRecorderClass.isTypeSupported.bind(MediaRecorderClass)
            : null;
        if (!supports) return Object.assign({}, FORMAT_CANDIDATES.at(-1));
        const selected = FORMAT_CANDIDATES.find(function (candidate) {
            try {
                return supports(candidate.mimeType) === true;
            } catch (error) {
                return false;
            }
        });
        return selected ? Object.assign({}, selected) : null;
    }

    function recordingDimensions(mode, sourceCanvas) {
        if (mode === '1080p') return { width: 1920, height: 1080 };
        if (mode === '720p') return { width: 1280, height: 720 };
        return {
            width: Math.max(2, Math.round(finite(
                sourceCanvas && (sourceCanvas.width || sourceCanvas.clientWidth),
                1280
            ))),
            height: Math.max(2, Math.round(finite(
                sourceCanvas && (sourceCanvas.height || sourceCanvas.clientHeight),
                720
            ))),
        };
    }

    function fittedFrame(sourceWidth, sourceHeight, targetWidth, targetHeight) {
        const safeSourceWidth = Math.max(1, finite(sourceWidth, 1));
        const safeSourceHeight = Math.max(1, finite(sourceHeight, 1));
        const scale = Math.min(
            targetWidth / safeSourceWidth,
            targetHeight / safeSourceHeight
        );
        const width = safeSourceWidth * scale;
        const height = safeSourceHeight * scale;
        return {
            x: (targetWidth - width) / 2,
            y: (targetHeight - height) / 2,
            width: width,
            height: height,
        };
    }

    function sanitizedFilename(value) {
        return cleanString(value, 'facility-walkthrough')
            .replace(/[^A-Za-z0-9._-]+/g, '-')
            .replace(/^-+|-+$/g, '')
            .slice(0, 90) || 'facility-walkthrough';
    }

    function createCanvasRecorder(inputOptions) {
        const options = inputOptions && typeof inputOptions === 'object'
            ? inputOptions : {};
        const documentRef = options.document || (root && root.document) || null;
        const MediaRecorderClass = options.MediaRecorder
            || (root && root.MediaRecorder);
        const BlobClass = options.Blob || (root && root.Blob);
        const urlApi = options.URL || (root && root.URL) || null;
        const navigatorRef = options.navigator || (root && root.navigator) || null;
        const requestFrame = options.requestAnimationFrame
            || (root && root.requestAnimationFrame
                ? root.requestAnimationFrame.bind(root) : function (callback) {
                    return setTimeout(callback, 16);
                });
        const cancelFrame = options.cancelAnimationFrame
            || (root && root.cancelAnimationFrame
                ? root.cancelAnimationFrame.bind(root) : clearTimeout);
        const setTimer = options.setInterval || setInterval;
        const clearTimer = options.clearInterval || clearInterval;
        const now = options.now || function () { return Date.now(); };
        const format = chooseRecordingFormat(MediaRecorderClass);
        let recorder = null;
        let outputCanvas = null;
        let outputContext = null;
        let outputStream = null;
        let microphoneStream = null;
        let frameHandle = null;
        let elapsedTimer = null;
        let chunks = [];
        let result = null;
        let stopPromise = null;
        let stopResolve = null;
        let disposed = false;
        let sourceCanvas = null;
        let activeSettings = null;
        let startedAt = 0;
        let pausedAt = 0;
        let pausedDuration = 0;
        let state = {
            status: format ? 'idle' : 'unsupported',
            elapsedMs: 0,
            paused: false,
            format: format,
            resolution: null,
            fps: null,
            error: format ? null : 'No supported MediaRecorder video format.',
        };

        function snapshot() {
            return {
                status: state.status,
                elapsedMs: state.elapsedMs,
                paused: state.paused,
                format: state.format ? Object.assign({}, state.format) : null,
                resolution: state.resolution
                    ? Object.assign({}, state.resolution) : null,
                fps: state.fps,
                error: state.error,
                hasPreview: Boolean(result && result.url),
                filename: result && result.filename || null,
            };
        }

        function notify() {
            if (typeof options.onStateChange === 'function') {
                options.onStateChange(snapshot());
            }
        }

        function elapsed() {
            if (!startedAt) return 0;
            const end = pausedAt || now();
            return Math.max(0, end - startedAt - pausedDuration);
        }

        function updateElapsed() {
            state.elapsedMs = elapsed();
            notify();
        }

        function stopTracks(stream) {
            if (!stream || typeof stream.getTracks !== 'function') return;
            stream.getTracks().forEach(function (track) {
                if (track && typeof track.stop === 'function') track.stop();
            });
        }

        function stopFrameLoop() {
            if (frameHandle !== null) cancelFrame(frameHandle);
            frameHandle = null;
            if (elapsedTimer !== null) clearTimer(elapsedTimer);
            elapsedTimer = null;
        }

        function drawFrame() {
            if (!outputContext || !outputCanvas || !sourceCanvas) return;
            if (activeSettings
                    && typeof activeSettings.prepareSourceFrame === 'function') {
                try {
                    const prepared = activeSettings.prepareSourceFrame();
                    if (prepared && typeof prepared === 'object') {
                        sourceCanvas = prepared;
                    }
                } catch (error) {
                    state.error = 'The 3D viewport could not be rendered.';
                }
            }
            const width = outputCanvas.width;
            const height = outputCanvas.height;
            outputContext.fillStyle = cleanString(
                activeSettings && activeSettings.background,
                '#dfe6eb'
            );
            outputContext.fillRect(0, 0, width, height);
            const frame = fittedFrame(
                sourceCanvas.width || sourceCanvas.clientWidth,
                sourceCanvas.height || sourceCanvas.clientHeight,
                width,
                height
            );
            try {
                outputContext.drawImage(
                    sourceCanvas,
                    frame.x,
                    frame.y,
                    frame.width,
                    frame.height
                );
            } catch (error) {
                state.error = 'The 3D viewport could not be copied.';
            }
            if (typeof activeSettings.overlayRenderer === 'function') {
                activeSettings.overlayRenderer({
                    context: outputContext,
                    width: width,
                    height: height,
                    frame: Object.assign({}, frame),
                    elapsedMs: elapsed(),
                    settings: Object.assign({}, activeSettings),
                });
            }
            if (state.status === 'recording' || state.status === 'paused') {
                frameHandle = requestFrame(drawFrame);
            }
        }

        function releasePreview() {
            if (result && result.url && urlApi
                    && typeof urlApi.revokeObjectURL === 'function') {
                urlApi.revokeObjectURL(result.url);
            }
            result = null;
        }

        function releaseLiveResources() {
            stopFrameLoop();
            stopTracks(outputStream);
            if (microphoneStream !== outputStream) stopTracks(microphoneStream);
            outputStream = null;
            microphoneStream = null;
            outputCanvas = null;
            outputContext = null;
            sourceCanvas = null;
            recorder = null;
        }

        function fail(error) {
            releaseLiveResources();
            state.status = 'error';
            state.error = error && error.message
                ? error.message : cleanString(error, 'Recording failed.');
            state.paused = false;
            notify();
            if (stopResolve) stopResolve(snapshot());
            stopResolve = null;
            stopPromise = null;
        }

        function finish() {
            stopFrameLoop();
            state.elapsedMs = elapsed();
            const blob = new BlobClass(chunks, { type: format.mimeType });
            const filenameBase = sanitizedFilename(
                activeSettings && activeSettings.filename
            );
            const url = urlApi && typeof urlApi.createObjectURL === 'function'
                ? urlApi.createObjectURL(blob) : null;
            result = {
                blob: blob,
                url: url,
                mimeType: format.mimeType,
                extension: format.extension,
                filename: filenameBase + '.' + format.extension,
                durationMs: state.elapsedMs,
                width: state.resolution.width,
                height: state.resolution.height,
                fps: state.fps,
            };
            releaseLiveResources();
            state.status = disposed ? 'disposed' : 'preview';
            state.paused = false;
            state.error = null;
            if (disposed) releasePreview();
            notify();
            if (stopResolve) stopResolve(snapshot());
            stopResolve = null;
            stopPromise = null;
        }

        async function start(input) {
            if (disposed) throw new Error('Facility recorder is disposed.');
            if (!format) throw new Error(state.error);
            if (!documentRef || typeof documentRef.createElement !== 'function') {
                throw new Error('A document is required for viewport recording.');
            }
            if (state.status === 'recording' || state.status === 'paused'
                    || state.status === 'stopping') {
                throw new Error('A viewport recording is already active.');
            }
            releasePreview();
            const settings = Object.assign({
                fps: 30,
                resolution: 'current',
                microphone: false,
                background: '#dfe6eb',
                filename: 'facility-walkthrough',
                videoBitsPerSecond: 8000000,
            }, input || {});
            sourceCanvas = settings.sourceCanvas;
            if (!sourceCanvas) throw new Error('The 3D viewport is unavailable.');
            outputCanvas = documentRef.createElement('canvas');
            const dimensions = recordingDimensions(settings.resolution, sourceCanvas);
            outputCanvas.width = dimensions.width;
            outputCanvas.height = dimensions.height;
            outputContext = outputCanvas.getContext
                ? outputCanvas.getContext('2d', { alpha: false }) : null;
            if (!outputContext || typeof outputCanvas.captureStream !== 'function') {
                releaseLiveResources();
                throw new Error('This browser cannot capture the 3D viewport.');
            }
            activeSettings = settings;
            state = {
                status: 'preparing',
                elapsedMs: 0,
                paused: false,
                format: format,
                resolution: dimensions,
                fps: settings.fps === 60 ? 60 : 30,
                error: null,
            };
            notify();
            try {
                outputStream = outputCanvas.captureStream(state.fps);
                if (settings.microphone) {
                    const mediaDevices = navigatorRef && navigatorRef.mediaDevices;
                    if (!mediaDevices
                            || typeof mediaDevices.getUserMedia !== 'function') {
                        throw new Error('Microphone capture is unavailable.');
                    }
                    microphoneStream = await mediaDevices.getUserMedia({ audio: true });
                    if (outputStream && typeof outputStream.addTrack === 'function') {
                        microphoneStream.getAudioTracks().forEach(function (track) {
                            outputStream.addTrack(track);
                        });
                    }
                }
                chunks = [];
                const recorderOptions = {
                    mimeType: format.mimeType,
                    videoBitsPerSecond: Math.max(
                        1000000,
                        Math.round(finite(settings.videoBitsPerSecond, 8000000))
                    ),
                };
                recorder = new MediaRecorderClass(outputStream, recorderOptions);
                recorder.ondataavailable = function (event) {
                    if (event && event.data && finite(event.data.size, 0) > 0) {
                        chunks.push(event.data);
                    }
                };
                recorder.onerror = function (event) {
                    fail(event && (event.error || event.message) || 'Recording failed.');
                };
                recorder.onstop = finish;
                startedAt = now();
                pausedAt = 0;
                pausedDuration = 0;
                state.status = 'recording';
                drawFrame();
                elapsedTimer = setTimer(updateElapsed, 250);
                recorder.start(1000);
                notify();
                return snapshot();
            } catch (error) {
                fail(error);
                throw error;
            }
        }

        function pause() {
            if (!recorder || state.status !== 'recording') return false;
            if (typeof recorder.pause === 'function') recorder.pause();
            pausedAt = now();
            state.status = 'paused';
            state.paused = true;
            updateElapsed();
            return true;
        }

        function resume() {
            if (!recorder || state.status !== 'paused') return false;
            if (typeof recorder.resume === 'function') recorder.resume();
            if (pausedAt) pausedDuration += Math.max(0, now() - pausedAt);
            pausedAt = 0;
            state.status = 'recording';
            state.paused = false;
            notify();
            return true;
        }

        function stop() {
            if (!recorder || (state.status !== 'recording'
                    && state.status !== 'paused')) {
                return Promise.resolve(snapshot());
            }
            if (state.status === 'paused') resume();
            state.status = 'stopping';
            state.paused = false;
            updateElapsed();
            if (!stopPromise) {
                stopPromise = new Promise(function (resolve) {
                    stopResolve = resolve;
                });
            }
            const pendingStop = stopPromise;
            recorder.stop();
            notify();
            return pendingStop;
        }

        function getResult() {
            return result ? Object.assign({}, result) : null;
        }

        function discard() {
            releasePreview();
            state.status = format ? 'idle' : 'unsupported';
            state.elapsedMs = 0;
            state.paused = false;
            state.resolution = null;
            state.fps = null;
            state.error = format ? null : 'No supported MediaRecorder video format.';
            notify();
            return snapshot();
        }

        function download() {
            if (!result || !result.url || !documentRef) return false;
            const link = documentRef.createElement('a');
            link.href = result.url;
            link.download = result.filename;
            if (documentRef.body && typeof documentRef.body.appendChild === 'function') {
                documentRef.body.appendChild(link);
            }
            if (typeof link.click === 'function') link.click();
            if (typeof link.remove === 'function') link.remove();
            return true;
        }

        function dispose() {
            if (disposed) return false;
            disposed = true;
            if (recorder && (state.status === 'recording'
                    || state.status === 'paused')) {
                stop().then(releasePreview);
            } else {
                releaseLiveResources();
                releasePreview();
                state.status = 'disposed';
                notify();
            }
            return true;
        }

        return Object.freeze({
            start: start,
            pause: pause,
            resume: resume,
            stop: stop,
            discard: discard,
            download: download,
            dispose: dispose,
            getState: snapshot,
            getResult: getResult,
        });
    }

    return Object.freeze({
        API_VERSION: API_VERSION,
        FORMAT_CANDIDATES: FORMAT_CANDIDATES,
        chooseRecordingFormat: chooseRecordingFormat,
        recordingDimensions: recordingDimensions,
        fittedFrame: fittedFrame,
        createCanvasRecorder: createCanvasRecorder,
    });
}));
