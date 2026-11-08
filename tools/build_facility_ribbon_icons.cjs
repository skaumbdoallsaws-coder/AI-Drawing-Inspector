// Deterministic small-size companions to the generated primary ribbon artwork.
// Familiar symbols reuse the existing licensed Phosphor geometry.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'static/assets/facility-ribbon-dimensional');
const source = path.join(root, 'static/assets/facility-layout-ribbon-icons/svg');
const colors = {
    teal: ['#c1f7e9', '#37b5a1', '#147469'],
    gold: ['#fff1b0', '#edb645', '#a66b20'],
    silver: ['#ffffff', '#c1cbd1', '#647784'],
    blue: ['#c3ecff', '#429edc', '#185da5'],
    green: ['#ddf4a5', '#89be50', '#447c2c'],
    red: ['#ffc7ba', '#e87669', '#a93234'],
    plum: ['#eed7ec', '#b081b2', '#754675'],
};
const defs = '<defs>' + Object.entries(colors).map(([name, c]) =>
    `<linearGradient id="${name}" x1="0" y1="0" x2=".8" y2="1" gradientUnits="objectBoundingBox"><stop stop-color="${c[0]}"/><stop offset=".42" stop-color="${c[1]}"/><stop offset="1" stop-color="${c[2]}"/></linearGradient>`).join('') + '</defs>';
const p = (d, color = 'silver', extra = '') => `<path d="${d}" fill="url(#${color})" stroke="#273b45" stroke-width="1.2" stroke-linejoin="round" ${extra}/>`;
const line = (d, color = '#dce5e9', width = 3, extra = '') => `<path d="${d}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" ${extra}/>`;
const cube = (x, y, w = 18, h = 15, color = 'teal') => {
    const a = w / 2, b = w / 4;
    return p(`M${x} ${y+b}l${a} -${b} ${a} ${b}-${a} ${b}Z`, color)
        + p(`M${x} ${y+b}l${a} ${b}v${h}l-${a}-${b}Z`, color)
        + p(`M${x+a} ${y+2*b}l${a}-${b}v${h}l-${a} ${b}Z`, color)
        + line(`M${x+1} ${y+b}l${a-1}-${b-1} ${a-1} ${b-1}`, '#ffffff', 1.4);
};
const tile = (x, y, color) => p(`M${x} ${y}l14-8 14 8-14 8Z`, color);
const mini = {};
const native = {
    select: ['cursor-click', 'silver'], pan: ['hand', 'silver'],
    'motion-path': ['person-simple-walk', 'teal'],
    'saved-movement': ['person-simple-walk', 'plum'],
    rotate: ['arrow-clockwise', 'teal'], duplicate: ['copy', 'blue'],
    delete: ['trash', 'red'], 'clear-all': ['clear-all', 'red'],
    lock: ['lock-simple', 'gold'],
    undo: ['arrow-u-up-left', 'blue'], redo: ['arrow-u-up-right', 'green'],
    fit: ['corners-out', 'teal'], mirror: ['mirror', 'plum'], swap: ['swap', 'teal'],
    'auto-arrange': ['magic-wand', 'plum'], save: ['floppy-disk', 'blue'],
};
function phosphor(name, color) {
    const svg = fs.readFileSync(path.join(source, name + '.svg'), 'utf8');
    const body = svg.slice(svg.indexOf('>') + 1, svg.lastIndexOf('</svg>'));
    return `<g transform="translate(3 3) scale(.2265625)" fill="url(#${color})">${body.replaceAll('currentColor', `url(#${color})`)}</g>`;
}
for (const [key, [name, color]] of Object.entries(native)) mini[key] = phosphor(name, color);
mini['rectangle-zone'] = p('M6 27L34 10 58 26 30 44Z', 'teal')
    + [[6,27],[34,10],[58,26],[30,44]].map(([x,y]) => `<rect x="${x-3}" y="${y-3}" width="6" height="6" fill="url(#silver)" stroke="#436268"/>`).join('');
mini['polygon-zone'] = p('M7 22L31 8 56 22 44 29 55 36 32 51 8 37Z', 'teal') + line('M10 23L31 11 52 23', '#e4fff5', 2);
mini['bulk-zones'] = tile(4, 24, 'teal') + tile(30, 24, 'gold') + tile(4, 42, 'silver') + tile(30, 42, 'blue');
mini.aisle = p('M6 42L38 10 58 28 26 58Z') + line('M14 42L38 18M26 50L50 28', '#edb645', 4) + line('M28 39L40 27M32 27H40V35', '#fff', 3);
mini['floor-marking'] = p('M6 34L34 12 59 30 30 53Z', 'silver') + line('M14 33L35 18M22 39L43 24M30 45L51 30', '#de9b23', 5);
mini.appearance = p('M16 53V11H29V53Z', 'red') + p('M18 53L27 9 40 13 31 55Z', 'gold') + p('M20 54L39 13 50 21 31 58Z', 'teal') + p('M23 54L51 25 59 36 32 60Z', 'blue');
mini['component-materials'] = cube(6, 13, 34, 26, 'silver') + cube(30, 31, 28, 17, 'gold');
mini.decals = p('M7 15L53 9 57 48 10 55Z', 'silver') + p('M12 20L48 15 51 44 15 49Z', 'blue') + p('M15 43L27 28 34 36 41 26 51 44 15 49Z', 'green') + '<circle cx="41" cy="22" r="4" fill="#ffe2a0"/>';
mini.lettering = p('M6 15L54 9V49L6 56Z', 'silver') + p('M18 43L27 20 34 19 45 40 37 41 35 36 25 37 23 43ZM28 31L32 31 30 26Z', 'gold', 'fill-rule="evenodd"');
mini['interior-walls'] = p('M5 24L31 8 57 24V52L31 39 5 55Z', 'silver') + p('M12 30L22 24V43L12 49Z', 'teal') + line('M31 9V39', '#75848b', 2);
mini['floor-surfaces'] = tile(4, 24, 'silver') + tile(31, 24, 'silver') + tile(4, 41, 'silver') + tile(31, 41, 'gold');
mini['floor-plan'] = p('M12 5H43L54 17V58H12Z', 'silver') + line('M20 48V24H45V48H33V35H20M43 5V17H54', '#2982ab', 3);
mini.columns = cube(8, 8, 18, 37, 'silver') + '<path d="M36 15V51C36 59 54 59 54 51V15Z" fill="url(#silver)" stroke="#637782" stroke-width="1.2"/><ellipse cx="45" cy="15" rx="9" ry="5" fill="url(#silver)" stroke="#637782"/>';
mini['replace-asset'] = cube(4, 8, 23, 18, 'silver') + cube(35, 30, 24, 18, 'teal') + line('M32 12H51V25M43 18L51 25 58 18', '#eab448', 4);
mini.align = p('M8 18H22V49H8Z', 'teal') + p('M33 31H47V49H33Z', 'teal') + line('M5 54H57', '#dce5e9', 4) + line('M54 13V40M49 34L54 40 59 34', '#edb645', 3);
mini.distribute = [7, 26, 45].map(x => p(`M${x} 17H${x+12}V44H${x}Z`, 'teal')).join('') + line('M7 53H57M7 49V57M26 49V57M45 49V57M57 49V57', '#edb645', 2);
mini.relative = cube(6, 29, 23, 17, 'silver') + cube(35, 7, 23, 17, 'teal') + line('M18 24V15H29M24 10L29 15 24 20', '#edb645', 3);
mini.distance = line('M10 10V53M54 10V53', '#dce5e9', 3) + line('M13 32H51M20 25L13 32 20 39M44 25L51 32 44 39', '#edb645', 4);
mini.offset = p('M8 10H38V42H8Z', 'silver') + p('M24 25H54V57H24Z', 'teal') + line('M45 8H57V20M49 14L57 8', '#edb645', 3);
mini['linear-pattern'] = [5, 25, 45].map(x => cube(x, 12, 15, 18, 'gold')).join('') + line('M9 51H55M48 45L55 51 48 57', '#dce5e9', 3);
mini['circular-pattern'] = '<circle cx="32" cy="32" r="18" fill="none" stroke="#dce5e9" stroke-width="2"/>' + [[24,3],[43,23],[24,42],[3,23]].map(([x,y]) => cube(x,y,16,10,'gold')).join('');
mini['perimeter-pattern'] = line('M13 15H51V48H13Z', '#dce5e9', 2) + [[4,6],[43,6],[4,39],[43,39]].map(([x,y]) => cube(x,y,16,10,'gold')).join('');
mini['cell-layout'] = cube(6, 9, 19, 14) + cube(38, 9, 19, 14) + cube(6, 35, 19, 14, 'gold') + line('M31 48H49V35', '#c1cbd1', 3);
mini['create-cell-group'] = mini['cell-layout'] + line('M4 4H60V59H4Z', '#89be50', 2);
mini['ungroup-cell'] = cube(4, 8, 22, 16) + cube(38, 36, 22, 16, 'gold') + line('M35 18L53 5M44 5H53V14M10 41L27 27M10 32V41H19', '#dce5e9', 3);
mini['vertical-stack'] = p('M5 42L32 27 59 42 32 58Z', 'plum')
    + p('M5 30L32 15 59 30 32 46Z', 'teal')
    + p('M5 18L32 3 59 18 32 34Z', 'silver');
mini['surface-stack'] = p('M4 39L33 21 61 39 31 58Z', 'silver') + cube(17, 10, 28, 20, 'teal');
mini['export-pdf'] = p('M12 5H42L54 17V59H12Z', 'silver') + line('M42 6V17H53', '#718793', 2) + '<rect x="4" y="33" width="54" height="21" rx="2" fill="url(#red)"/>' + '<text x="31" y="49" text-anchor="middle" fill="white" font-family="Arial,sans-serif" font-weight="bold" font-size="17">PDF</text>';
mini.more = p('M42 7A13 13 0 0 0 27 24L7 45A7 7 0 0 0 18 56L39 35A13 13 0 0 0 57 19L47 28 37 18Z', 'silver') + line('M13 49L29 33', '#2b8fa3', 4);
fs.mkdirSync(out, { recursive: true });
fs.copyFileSync(path.join(source, '../LICENSE.txt'), path.join(out, 'PHOSPHOR-LICENSE.txt'));
for (const [name, body] of Object.entries(mini)) {
    fs.writeFileSync(path.join(out, name + '.svg'), `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">${defs}${body}</svg>\n`);
}
console.log(`Built ${Object.keys(mini).length} transparent small-size Facility icons.`);

// Viewport companions share the ribbon's materials, but use simpler silhouettes.
const viewport = {};
viewport.select = '<style>#select path[opacity]{opacity:1;fill:url(#silver)}#select path:not([opacity]){fill:url(#teal)}</style>'
    + '<g id="select">' + phosphor('cursor-click', 'silver') + '</g>';
viewport['reset-view'] = mini.rotate;
viewport.snap = p('M8 8H22V33C22 47 42 47 42 33V8H56V33C56 64 8 64 8 33Z', 'gold')
    + p('M8 8H22V21H8Z', 'silver') + p('M42 8H56V21H42Z', 'silver')
    + '<rect x="29" y="13" width="6" height="6" rx="1" fill="url(#teal)"/>'
    + line('M13 25V33C13 58 51 58 51 33V25', '#fff1b0', 1.4);
const brackets = line('M5 19V6H18M46 6H59V19M59 45V58H46M18 58H5V45', '#8aa5ac', 4);
viewport['fit-layout'] = brackets + cube(13, 23, 18, 18, 'teal') + cube(34, 15, 17, 26, 'silver');
for (const command of ['zoom-in', 'zoom-out']) {
    viewport[command] = line('M44 44L57 57', '#283d49', 11)
        + line('M44 44L57 57', 'url(#silver)', 7)
        + '<circle cx="27" cy="27" r="22" fill="url(#silver)" stroke="#647a88" stroke-width="1.5"/>'
        + '<circle cx="27" cy="27" r="16" fill="#e5f2f7" stroke="#558caa" stroke-width="2"/>'
        + line('M18 27H36' + (command === 'zoom-in' ? 'M27 18V36' : ''), '#25566a', 4)
        + line('M12 20A17 17 0 0 1 24 11', '#ffffff', 2);
}
viewport.pan = p('M32 4L42 15H36V28H49V22L60 32 49 42V36H36V49H42L32 60 22 49H28V36H15V42L4 32 15 22V28H28V15H22Z', 'silver')
    + line('M30 16V30H16M36 30H48', '#eaf8ff', 1.5);
viewport['display-settings'] = line('M9 16H55M9 32H55M9 48H55', '#869da9', 5)
    + [ [20,16],[44,32],[27,48] ].map(([x,y]) => `<rect x="${x-5}" y="${y-7}" width="10" height="14" rx="2" fill="url(#gold)" stroke="#805f28" stroke-width="1.2"/>`).join('');
viewport.layers = mini['vertical-stack'];
viewport.orbit = '<ellipse cx="32" cy="32" rx="27" ry="12" transform="rotate(-28 32 32)" fill="none" stroke="#2c746d" stroke-width="5"/>'
    + '<ellipse cx="32" cy="32" rx="27" ry="12" transform="rotate(-28 32 32)" fill="none" stroke="url(#teal)" stroke-width="3"/>'
    + '<circle cx="32" cy="32" r="10" fill="url(#silver)" stroke="#5c7381" stroke-width="1.5"/>'
    + p('M50 10L61 14 53 23Z', 'teal');
viewport.walkthrough = '<style>#walk path{fill:url(#green);opacity:1}</style>'
    + '<g id="walk">' + phosphor('person-simple-walk', 'green') + '</g>';
viewport['avatar-view'] = p('M7 19H18L22 12H42L46 19H57V54H7Z', 'silver')
    + '<circle cx="32" cy="29" r="6" fill="url(#teal)"/>'
    + p('M20 47V43C20 31 44 31 44 43V47Z', 'teal');
viewport.drone = '<style>#drone g[stroke]{stroke:url(#silver);stroke-width:12}#drone [fill="#56a9d2"],#drone [fill="#d9a64c"]{fill:url(#gold);opacity:1}</style>'
    + '<g id="drone" transform="translate(-8 -10) scale(1.25)">' + phosphor('drone', 'gold') + '</g>';
viewport['switch-immersive'] = p('M8 14H43V7L58 20 43 33V25H8Z', 'gold')
    + p('M56 39H21V31L6 44 21 57V50H56Z', 'green');
viewport['walk-to-selected'] = p('M9 53L28 13 34 31 53 36Z', 'green')
    + '<circle cx="49" cy="15" r="10" fill="none" stroke="url(#gold)" stroke-width="4"/>'
    + '<circle cx="49" cy="15" r="3" fill="#f4c766"/>';
viewport['camera-settings'] = p('M7 18H17L21 11H39L43 18H55V49H7Z', 'silver')
    + '<circle cx="29" cy="33" r="11" fill="url(#teal)" stroke="#3b6570" stroke-width="2"/>'
    + line('M44 37H61M44 46H61M44 55H61', '#557581', 3)
    + line('M50 34V40M56 43V49M49 52V58', '#edb645', 4);
viewport.viewpoints = '<style>#pin [fill="#d9a64c"]{fill:url(#gold);opacity:1}#pin [stroke]{stroke:#70522b;stroke-width:10}</style>'
    + '<g id="pin">' + phosphor('map-pin', 'gold') + '</g>';
viewport['fit-facility'] = brackets + p('M13 33L33 21 52 33 32 46Z', 'silver')
    + line('M20 29L39 41M26 25L45 37M20 37L38 26M26 41L45 30', '#64868b', 1.5);
viewport.grid = p('M4 30L32 11 60 30 32 51Z', 'silver')
    + line('M11 25L39 46M18 20L46 41M25 16L53 36M11 35L39 16M18 40L46 21M25 46L53 26', '#547c83', 2.5);
const viewportOut = path.join(root, 'static/assets/facility-viewport-icons');
fs.mkdirSync(viewportOut, { recursive: true });
fs.copyFileSync(path.join(source, '../LICENSE.txt'), path.join(viewportOut, 'PHOSPHOR-LICENSE.txt'));
for (const [name, body] of Object.entries(viewport)) {
    fs.writeFileSync(path.join(viewportOut, name + '.svg'), `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">${defs}${body}</svg>\n`);
}
console.log(`Built ${Object.keys(viewport).length} transparent Facility viewport icons.`);
