'use strict';

const assert = require('assert');
const recorderRuntime = require('../static/facility_layout_recorder.js');

let checks = 0;
async function check(name, callback) {
    await callback();
    checks += 1;
    process.stdout.write('PASS ' + name + '\n');
}

class FakeTrack {
    constructor(kind) {
        this.kind = kind;
        this.stopped = false;
    }

    stop() {
        this.stopped = true;
    }
}

class FakeStream {
    constructor(tracks) {
        this.tracks = tracks || [];
    }

    addTrack(track) {
        this.tracks.push(track);
    }

    getTracks() {
        return this.tracks.slice();
    }

    getAudioTracks() {
        return this.tracks.filter(track => track.kind === 'audio');
    }
}

class FakeBlob {
    constructor(parts, options) {
        this.parts = parts || [];
        this.type = options && options.type || '';
        this.size = this.parts.reduce((total, part) => (
            total + Number(part && part.size || 0)
        ), 0);
    }
}

class FakeCanvas {
    constructor(width, height) {
        this.width = width || 640;
        this.height = height || 360;
        this.clientWidth = this.width;
        this.clientHeight = this.height;
        this.context = {
            fillStyle: '',
            frames: [],
            fillRect() {},
            drawImage(...args) { this.frames.push(args); },
        };
        this.stream = null;
    }

    getContext(kind) {
        return kind === '2d' ? this.context : null;
    }

    captureStream(fps) {
        this.stream = new FakeStream([new FakeTrack('video')]);
        this.stream.fps = fps;
        return this.stream;
    }
}

class FakeMediaRecorder {
    static isTypeSupported(value) {
        return value === 'video/webm;codecs=vp8';
    }

    constructor(stream, options) {
        this.stream = stream;
        this.options = options;
        this.state = 'inactive';
        FakeMediaRecorder.instances.push(this);
    }

    start(timeslice) {
        this.state = 'recording';
        this.timeslice = timeslice;
    }

    pause() {
        this.state = 'paused';
    }

    resume() {
        this.state = 'recording';
    }

    stop() {
        this.state = 'inactive';
        if (this.ondataavailable) {
            this.ondataavailable({ data: new FakeBlob([{ size: 24 }]) });
        }
        if (this.onstop) this.onstop();
    }
}
FakeMediaRecorder.instances = [];

function fixture() {
    let now = 1000;
    const canvases = [];
    const links = [];
    const revoked = [];
    const source = new FakeCanvas(900, 600);
    const microphoneTrack = new FakeTrack('audio');
    const document = {
        body: { appendChild() {} },
        createElement(kind) {
            if (kind === 'canvas') {
                const canvas = new FakeCanvas();
                canvases.push(canvas);
                return canvas;
            }
            const link = {
                clicked: false,
                removed: false,
                click() { this.clicked = true; },
                remove() { this.removed = true; },
            };
            links.push(link);
            return link;
        },
    };
    const URL = {
        createObjectURL() { return 'blob:facility-recording'; },
        revokeObjectURL(value) { revoked.push(value); },
    };
    const states = [];
    const controller = recorderRuntime.createCanvasRecorder({
        document,
        MediaRecorder: FakeMediaRecorder,
        Blob: FakeBlob,
        URL,
        navigator: {
            mediaDevices: {
                async getUserMedia() {
                    return new FakeStream([microphoneTrack]);
                },
            },
        },
        requestAnimationFrame() { return 7; },
        cancelAnimationFrame() {},
        setInterval() { return 8; },
        clearInterval() {},
        now() { return now; },
        onStateChange(value) { states.push(value); },
    });
    return {
        controller,
        source,
        canvases,
        links,
        revoked,
        states,
        microphoneTrack,
        advance(value) { now += value; },
    };
}

async function main() {
    await check('chooses the first genuinely supported recording format', async () => {
        assert.deepStrictEqual(
            recorderRuntime.chooseRecordingFormat(FakeMediaRecorder),
            {
                mimeType: 'video/webm;codecs=vp8',
                extension: 'webm',
                label: 'WebM (VP8)',
            }
        );
        assert.strictEqual(recorderRuntime.chooseRecordingFormat(null), null);
    });

    await check('uses exact preset dimensions and preserves current size', async () => {
        const source = new FakeCanvas(1001, 701);
        assert.deepStrictEqual(
            recorderRuntime.recordingDimensions('1080p', source),
            { width: 1920, height: 1080 }
        );
        assert.deepStrictEqual(
            recorderRuntime.recordingDimensions('720p', source),
            { width: 1280, height: 720 }
        );
        assert.deepStrictEqual(
            recorderRuntime.recordingDimensions('current', source),
            { width: 1001, height: 701 }
        );
    });

    await check('letterboxes a viewport without distorting its aspect ratio', async () => {
        assert.deepStrictEqual(
            recorderRuntime.fittedFrame(1000, 1000, 1920, 1080),
            { x: 420, y: 0, width: 1080, height: 1080 }
        );
    });

    await check('records, pauses, resumes, previews, and cleans media tracks', async () => {
        const data = fixture();
        let preparedFrames = 0;
        const started = await data.controller.start({
            sourceCanvas: data.source,
            prepareSourceFrame() {
                preparedFrames += 1;
                return data.source;
            },
            resolution: '720p',
            fps: 60,
            microphone: true,
            filename: 'Layout A review',
        });
        assert.strictEqual(started.status, 'recording');
        assert.deepStrictEqual(started.resolution, { width: 1280, height: 720 });
        assert.strictEqual(started.fps, 60);
        const media = FakeMediaRecorder.instances.at(-1);
        assert.strictEqual(media.options.mimeType, 'video/webm;codecs=vp8');
        assert.strictEqual(media.stream.getAudioTracks().length, 1);
        assert.strictEqual(data.canvases[0].context.frames.length, 1);
        assert.strictEqual(preparedFrames, 1);

        data.advance(1500);
        assert.strictEqual(data.controller.pause(), true);
        assert.strictEqual(data.controller.getState().status, 'paused');
        data.advance(500);
        assert.strictEqual(data.controller.resume(), true);
        data.advance(1500);
        const stopped = await data.controller.stop();
        assert.strictEqual(stopped.status, 'preview');
        const result = data.controller.getResult();
        assert.strictEqual(result.mimeType, 'video/webm;codecs=vp8');
        assert.strictEqual(result.filename, 'Layout-A-review.webm');
        assert.strictEqual(result.durationMs, 3000);
        assert.strictEqual(result.url, 'blob:facility-recording');
        assert.strictEqual(data.microphoneTrack.stopped, true);
        assert.ok(media.stream.getTracks().every(track => track.stopped));
    });

    await check('download uses the truthful extension and discard revokes preview', async () => {
        const data = fixture();
        await data.controller.start({ sourceCanvas: data.source });
        await data.controller.stop();
        assert.strictEqual(data.controller.download(), true);
        assert.strictEqual(data.links.at(-1).download, 'facility-walkthrough.webm');
        assert.strictEqual(data.links.at(-1).clicked, true);
        data.controller.discard();
        assert.deepStrictEqual(data.revoked, ['blob:facility-recording']);
        assert.strictEqual(data.controller.getResult(), null);
        assert.strictEqual(data.controller.getState().status, 'idle');
    });

    process.stdout.write(checks + '/' + checks
        + ' facility layout recorder checks passed\n');
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
