'use strict';

class TourControl {
    constructor(waitForCue = true, clock = Date.now) {
        this.clock = clock;
        this.startedAt = clock();
        this.pausedAt = this.startedAt;
        this.pausedMilliseconds = 0;
        this.paused = waitForCue;
        this.started = !waitForCue;
        this.stopped = false;
        this.epoch = 0;
    }
    toggle() {
        if (this.stopped) return false;
        if (this.paused) this.pausedMilliseconds += this.clock() - this.pausedAt;
        else this.pausedAt = this.clock();
        this.paused = !this.paused;
        if (!this.paused) this.started = true;
        this.epoch += 1;
        return true;
    }
    stop() {
        this.stopped = true;
        this.epoch += 1;
    }
    check() {
        if (this.stopped) throw new Error('tour_stopped');
    }
    pauseTimedOut(milliseconds = 300000) {
        return this.started && this.paused && this.clock() - this.pausedAt > milliseconds;
    }
    now() {
        const time = this.clock();
        return time - this.startedAt - this.pausedMilliseconds - (this.paused ? time - this.pausedAt : 0);
    }
}

function verifyArrival(state, destination, tolerance = 0.15) {
    if (!state.active || state.route.active || state.route.reason !== 'arrived') {
        throw new Error('Walk did not arrive: ' + JSON.stringify(state));
    }
    const distance = Math.hypot(state.position.x - destination.x, state.position.z - destination.z);
    if (!Number.isFinite(distance) || distance > tolerance) throw new Error('Walk ended short of destination');
    return distance;
}

async function withTimeout(promise, label, milliseconds = 60000) {
    let timer;
    try {
        return await Promise.race([promise, new Promise((_, reject) => {
            timer = setTimeout(() => reject(new Error(label + ' timed out')), milliseconds);
        })]);
    } finally {
        clearTimeout(timer);
    }
}

module.exports = {TourControl, verifyArrival, withTimeout};
