# InspectorPro facility tree icons

Four coordinated vector icons rebuilt from the approved visual concept. These are simplified, implementation-ready vector interpretations rather than crops from the concept image. Every asset uses the same cube.

## Mapping

| Node kind | Icon file | Meaning |
|---|---|---|
| Layout | `svg/facility-layout.svg` | Complete floor plan |
| Zone | `svg/zone.svg` | Bounded area / department |
| Cell | `svg/manufacturing-cell.svg` | Group of assets |
| Asset | `svg/asset.svg` | Any individual asset |

Map icons using the existing node type, not display names. Map all equipment categories and CAD instances to `asset.svg`. Do not infer types from words in labels, and do not change the underlying tree hierarchy to fit the icons.

## Recommended sizes

| Use | CSS icon size | Suggested row height |
|---|---|---|
| Default tree (recommended) | **20 x 20 px** | **28 px** |
| Compact tree | 16 x 16 px | 24 px |
| Comfortable tree | 24 x 24 px | 32 px |

Use the same size for all four levels. Indent each level by 18 px and leave about 6 px between icon and text. Keep existing disclosure arrows; icons identify types and are not checkboxes. These are desktop layout recommendations; retain suitable touch targets if the app supports touch.

Prefer SVG in the app. Each SVG defaults to 20 x 20 and has a 64 x 64 viewBox. Set both CSS width and height; do not change viewBox. Transparent backgrounds, flat two-tone faces, no raster images, fonts, scripts, external dependencies, gradients, or filters. The supplied palette is designed primarily for the current light InspectorPro tree. On dark surfaces, inspect contrast in the target application and use a neutral light icon backing if necessary.

PNG folders contain transparent 16, 20, 24, 32, 40, 48, 64, and 128 px exports. For a 20 CSS px icon at 2x pixel density use the 40 px PNG; for a 16 CSS px icon use 32 px, and for 24 CSS px use 48 px. SVG handles pixel density automatically. Prefer native SVG rendering over enlarging a small PNG.

## Integration example

Copy `svg/` to your app's public assets directory, for example `/icons/facility/`.

```tsx
type FacilityNodeKind = 'layout' | 'zone' | 'cell' | 'asset';

const iconByKind: Record<FacilityNodeKind, string> = {
  layout: '/icons/facility/facility-layout.svg',
  zone: '/icons/facility/zone.svg',
  cell: '/icons/facility/manufacturing-cell.svg',
  asset: '/icons/facility/asset.svg',
};

// Use beside the existing visible node label.
<img
  className="facility-tree-icon"
  src={iconByKind[node.kind]}
  width={20}
  height={20}
  alt=""
  aria-hidden="true"
  draggable={false}
/>
```

```css
.facility-tree-icon {
  display: block;
  width: 20px;
  height: 20px;
  flex: 0 0 20px;
  object-fit: contain;
  user-select: none;
}
```

Adapt the type mapping to your app's existing data model. Retain keyboard navigation, focus styles, selection, expansion and visibility behavior. Use the existing row background for selection; keep icon identity unchanged. If icons are used without visible labels, provide accessible names. Preserve colored fills; CSS masks would turn them into single-color silhouettes.

## Package contents

- `svg/`: four master vector icons, preferred for implementation.
- `png/<size>/`: four transparent PNGs in each export size.
- `preview.png`: enlarged icons plus true 16/20/24/32 px samples.
- `manifest.json`: machine-readable mappings and size recommendations.
- `README.md`: this handoff guide.

The icons are original artwork created for this request. No third-party icon package is required. Validate appearance in your running app before shipping; the app itself was not modified by this package.
