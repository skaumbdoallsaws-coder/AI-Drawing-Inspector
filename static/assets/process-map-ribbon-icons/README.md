# InspectorPro Premium Ribbon Icons

A cohesive set of 28 original SVG icons designed for the InspectorPro Process Map ribbon.

## Format

- Standalone SVG files
- Transparent background
- `32 × 32` viewBox
- No fonts, raster images, or external dependencies
- Rounded geometry, restrained gradients, and subtle built-in shadows
- Designed to stay clear at approximately `24–32 px`

## Recommended ribbon mapping

### Type / Map
- `process-map.svg`
- `map-actions.svg`

### Editing
- `undo.svg`
- `redo.svg`
- `delete.svg`
- `clear-map.svg`

### Map Elements
- `add-step.svg`
- `add-group.svg`
- `add-junction.svg`
- `add-operation.svg`
- `suggestions.svg`
- `analyze.svg`
- `layout.svg`

### Node Configuration
- `node-type.svg`
- `ports.svg`
- `input.svg`

### Visualization
- `zoom-in.svg`
- `zoom-out.svg`
- `fit.svg`
- `view-3d.svg`

### File
- `save.svg`

### Junction / Stage menu
- `junction-generic.svg`
- `junction-parallel.svg`
- `junction-merge.svg`
- `junction-split.svg`
- `junction-decision.svg`
- `junction-milestone.svg`
- `stage-operation.svg`

## HTML usage

```html
<button class="ribbon-command" type="button">
  <img class="ribbon-icon" src="/icons/add-junction.svg" alt="" aria-hidden="true" />
  <span>Add Junction</span>
</button>
```

```css
.ribbon-icon {
  width: 30px;
  height: 30px;
  display: block;
  pointer-events: none;
}

.ribbon-command:hover .ribbon-icon {
  transform: translateY(-1px);
}

.ribbon-command:disabled .ribbon-icon {
  opacity: 0.38;
  filter: grayscale(0.75) saturate(0.35);
}
```

## React usage

```tsx
import addJunctionIcon from './icons/add-junction.svg';

export function AddJunctionButton() {
  return (
    <button type="button" aria-label="Add junction">
      <img src={addJunctionIcon} alt="" aria-hidden="true" width={30} height={30} />
      <span>Add Junction</span>
    </button>
  );
}
```

## UI guidance

Use the colored SVG as the normal enabled state. Handle hover, pressed, selected, and disabled states on the ribbon button container rather than swapping icon files. This keeps the icon set consistent and avoids unnecessary assets.
