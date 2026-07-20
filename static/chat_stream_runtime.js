(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProChatStreamRuntime = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
    'use strict';

    function parseEventLine(line) {
        if (!String(line || '').startsWith('data: ')) return null;
        try {
            const parsed = JSON.parse(String(line).slice(6).trim());
            return parsed && parsed.v === 1 && parsed.event ? parsed : null;
        } catch (_) {
            return null;
        }
    }

    function createEventGate() {
        let responseId = null;
        let lastSeq = -1;
        let terminal = false;
        return {
            accept(event) {
                if (!event || terminal) return false;
                if (responseId && event.response_id !== responseId) return false;
                if (!responseId) responseId = event.response_id;
                if (!Number.isInteger(event.seq) || event.seq <= lastSeq) return false;
                lastSeq = event.seq;
                if (event.event === 'response_completed'
                    || event.event === 'response_cancelled'
                    || event.event === 'response_error') {
                    terminal = true;
                }
                return true;
            },
            get responseId() { return responseId; },
            get lastSeq() { return lastSeq; },
            get terminal() { return terminal; },
        };
    }

    class SseDecoder {
        constructor() {
            this.buffer = '';
        }

        push(text) {
            this.buffer += String(text || '');
            const lines = this.buffer.split(/\r?\n/);
            this.buffer = lines.pop() || '';
            return lines.map(parseEventLine).filter(Boolean);
        }

        finish() {
            const final = parseEventLine(this.buffer);
            this.buffer = '';
            return final ? [final] : [];
        }
    }

    function visualDisplayRate(pendingLength) {
        const length = Math.max(0, Number(pendingLength) || 0);
        if (length >= 2400) return 1500;
        if (length >= 1200) return 850;
        if (length >= 600) return 500;
        if (length >= 240) return 280;
        if (length >= 80) return 140;
        return 55;
    }

    function visualDisplayFrameCap(pendingLength) {
        const length = Math.max(0, Number(pendingLength) || 0);
        if (length >= 1200) return 64;
        if (length >= 600) return 32;
        if (length >= 240) return 16;
        if (length >= 80) return 8;
        return 4;
    }

    // Network chunks are intentionally kept intact here. This queue only
    // controls how quickly already-received text becomes visible to a person.
    function createVisualTextQueue() {
        let pending = '';
        let displayed = '';
        let credit = 0;
        let lastDrainAt = null;
        let disposed = false;

        function snapshot(changed, appended, rate) {
            return {
                changed: !!changed,
                appended: appended || '',
                text: displayed,
                pendingLength: pending.length,
                rate: rate || visualDisplayRate(pending.length),
            };
        }

        return {
            push(text) {
                if (disposed) return snapshot(false, '', 0);
                const value = String(text || '');
                if (!value) return snapshot(false, '', 0);
                pending += value;
                return snapshot(false, '', visualDisplayRate(pending.length));
            },

            drain(now) {
                if (disposed || !pending) return snapshot(false, '', 0);
                const timestamp = Number.isFinite(now) ? now : Date.now();
                let elapsed = 0;
                if (lastDrainAt === null) {
                    // Reveal the first character immediately so a live stream
                    // never looks stalled while the pacing clock starts.
                    credit = Math.max(credit, 1);
                } else {
                    // Do not turn a throttled background frame into a giant
                    // foreground text jump when the tab becomes visible again.
                    elapsed = Math.min(80, Math.max(0, timestamp - lastDrainAt));
                }
                lastDrainAt = timestamp;

                const rate = visualDisplayRate(pending.length);
                credit += rate * elapsed / 1000;
                let count = Math.floor(credit);
                if (count < 1) return snapshot(false, '', rate);
                count = Math.min(count, visualDisplayFrameCap(pending.length), pending.length);
                credit -= count;

                const appended = pending.slice(0, count);
                pending = pending.slice(count);
                displayed += appended;
                if (!pending) {
                    credit = 0;
                    lastDrainAt = null;
                }
                return snapshot(true, appended, rate);
            },

            revealFirstVisible() {
                if (disposed || !pending) return snapshot(false, '', 0);
                const firstVisible = pending.search(/\S/);
                if (firstVisible < 0) return snapshot(false, '', 0);
                const count = firstVisible + 1;
                const appended = pending.slice(0, count);
                pending = pending.slice(count);
                displayed += appended;
                credit = 0;
                lastDrainAt = null;
                return snapshot(true, appended, visualDisplayRate(pending.length));
            },

            replace(text) {
                if (disposed) return snapshot(false, '', 0);
                displayed = String(text || '');
                pending = '';
                credit = 0;
                lastDrainAt = null;
                return snapshot(true, displayed, 0);
            },

            flush() {
                if (disposed || !pending) return snapshot(false, '', 0);
                const appended = pending;
                displayed += pending;
                pending = '';
                credit = 0;
                lastDrainAt = null;
                return snapshot(true, appended, 0);
            },

            dispose() {
                disposed = true;
                pending = '';
                credit = 0;
                lastDrainAt = null;
            },

            get visibleText() { return displayed + pending; },
            get displayedText() { return displayed; },
            get pendingLength() { return pending.length; },
            get disposed() { return disposed; },
        };
    }

    return {
        parseEventLine,
        createEventGate,
        SseDecoder,
        visualDisplayRate,
        createVisualTextQueue,
    };
});
