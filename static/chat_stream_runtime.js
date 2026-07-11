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

    return { parseEventLine, createEventGate, SseDecoder };
});
