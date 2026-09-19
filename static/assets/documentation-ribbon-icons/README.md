# InspectorPro Documentation Icon Pack

Custom, original SVG command icons for the InspectorPro Documentation workflow. They are not copied from Microsoft PowerPoint, Fluent UI, or Lucide.

## Visual spec
- 24x24 viewBox
- 1.75px stroke
- round line caps / joins
- `currentColor` so the same SVG works in light, dark, disabled and accent states
- designed to read well at 18–24px in a dense desktop ribbon

## Recommended usage
- 20px icons for compact ribbon buttons
- 24px icons for normal ribbon buttons
- 28–32px only for one or two primary commands such as AI Arrange or Publish PDF
- do not mix these with filled/3D icon styles in the same ribbon
- apply InspectorPro blue through CSS rather than baking color into the SVG

## Ribbon mapping
See `manifest.json` for suggested command mappings. Generic commands (Undo, Redo, Save, Print) can use your existing application/system icon family; this pack focuses on Documentation-specific commands.

## Suggested dropdown trigger icons
- Arrange: `arrange.svg`
- Align / Distribute: `align-distribute.svg`
- Annotations: `annotations.svg`
- Shapes: `shapes.svg`
- View Style: `view-style.svg`

## Notes
Keep the ribbon icon family consistent. If the application adopts Fluent System Icons for common commands, use these custom SVGs only for domain-specific actions that do not have a good standard icon.
