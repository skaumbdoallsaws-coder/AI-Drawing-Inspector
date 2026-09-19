'use strict';

// Windows may register a newly shown native window after the renderer paints.
// Wait for that exact source; never substitute another window or a screen.
async function ownedWindowSource({ window, desktopCapturer, wait = ms => new Promise(resolve => setTimeout(resolve, ms)), attempts = 8 }) {
  const observations = [];
  for (let attempt = 0; attempt < attempts; attempt++) {
    if (window.isDestroyed()) throw new Error('Owned capture window was destroyed');
    const [width, height] = window.getSize();
    const expected = window.getMediaSourceId().split(':')[1];
    let timer;
    const sources = await Promise.race([
      desktopCapturer.getSources({ types: ['window'], thumbnailSize: { width: width * 2, height: height * 2 } }),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Owned window enumeration timed out')), 5000); }),
    ]).finally(() => clearTimeout(timer));
    const owned = sources.find(source => source.id.split(':')[1] === expected);
    observations.push({ attempt: attempt + 1, ownedPresent: !!owned, empty: owned ? owned.thumbnail.isEmpty() : null });
    if (owned && !owned.thumbnail.isEmpty()) return { image: owned.thumbnail, observations };
    if (attempt + 1 < attempts) await wait(250);
  }
  throw Object.assign(new Error('Owned window is not available for native capture'), { observations });
}

module.exports = { ownedWindowSource };
