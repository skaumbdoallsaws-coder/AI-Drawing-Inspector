# InspectorPro Premium Documentation Icon System

An original CAD-inspired icon family for the InspectorPro Documentation ribbon. The set uses dimensional surfaces, crisp technical outlines, and restrained functional color—without copying SolidWorks artwork.

## Included

- `svg/light/` — light-ribbon icons
- `svg/dark/` — dark-ribbon icons
- `svg/themeable/` — inline SVGs using CSS custom properties for linework
- `png/<theme>/<size>/` — 24, 32, and 48 px raster exports
- `preview/` — icon boards and full ribbon mockups
- `manifest.json` — IDs, labels, themes, and available sizes

## Recommended ribbon sizing

- Major commands (`Generate Manual`, `Export PDF`): 32–40 px displayed size
- Standard commands: 24–28 px
- Do not scale the 24 px PNG upward; use SVG or the 32/48 px export.

## Theme use

Use the explicit `light` and `dark` files when the icons are loaded with `<img>`. Use `themeable` only when SVG markup is inserted inline. The themeable files accept:

```css
--ip-icon-ink: #193847;
--ip-icon-ink-soft: #426273;
--ip-icon-paper-top: #ffffff;
--ip-icon-paper-bottom: #dce9ef;
```

## Interaction states

Keep the artwork unchanged and apply UI-level treatment:

- Hover: a subtle cyan-tinted tile behind the icon
- Active/selected: cyan tile plus 1 px accent border
- Disabled: `opacity: .38; filter: saturate(.45);`
- Avoid recoloring the entire icon on hover; the functional red, blue, orange, and cyan cues should remain stable.
