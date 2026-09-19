'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
    path.resolve(__dirname, '..', 'static', 'index.html'),
    'utf8'
);
const blocks = Array.from(
    source.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/gi)
).filter(match => {
    const attributes = match[1] || '';
    if (/\bsrc\s*=/i.test(attributes)) return false;
    if (/\btype\s*=\s*["'](?:importmap|application\/json)["']/i.test(attributes)) {
        return false;
    }
    return match[2].trim().length > 0;
});

blocks.forEach((match, index) => {
    new vm.Script(match[2], { filename: `index-inline-${index}.js` });
});

console.log(`${blocks.length}/${blocks.length} inline scripts syntax-clean`);
