# Packaging Ribbon Artwork

## Glossy Set V1

- Asset: `product-glossy-v1.png`, original transparent PNG.
- Created with the built-in image generation tool using the user's `Glossy 3D Packaging Toolbar.png` as a style reference.
- Scope: Packaging commands in the desktop ribbon and standalone workspace. Other workflows and viewport tools are unchanged.
- Preserve the existing icon dimensions; render in full color without the monochrome mask.
- Product approved by the user on 2026-11-07, followed by approval to complete the remaining icons in the same style.
- Individual transparent assets: Product, Carton, Contents, Arrange, Appearance, Graphics, Validation, Rates, Document, Undo, Redo and Save.
- Shared rendering: `static/packaging_ribbon_icons.css`. Original PNG alpha is preserved; no sprite sheet, backdrop or monochrome mask.
- `generation-prompts.json` records the exact prompts for the remaining assets. Each was created separately with the built-in image generation tool, using the approved Product and toolbar as references. Redo was refined against Undo to match its visual weight.
- More reuses Arrange; document menu entries reuse Document. Reload and the conditional Resume control retain their existing symbols.
- Readability polish: 10px desktop labels with a 13px line box; existing ribbon height and command order retained. Undo/Redo rows fit their 20px icons. Contents/Rates use a 33px background in the unchanged 32px slot, and Save uses 36px to compensate for its wider transparent margins. Source artwork is unchanged; alpha bounds are checked for clipping.

### Product Generation Prompt

Create ONE individual transparent-background PNG icon for InspectorPro's Packaging ribbon, using the supplied toolbar image only as a visual style reference. Product icon ONLY, no toolbar, no label, no text or numbers, no frame. Subject: a simple solid glossy BLUE CUBE in clean three-quarter isometric perspective, three visible faces, with silver-white double-headed dimension arrows indicating width and depth below it and height to its right. It must be unmistakably a cube, NOT a mechanical part, bracket, hollow box or carton. Match the reference Product icon's dimensional polish: restrained bevels, cyan edge highlights, rich cobalt-blue faces, subtle reflections, consistent soft studio lighting from upper left. Optimize for actual 32 px desktop ribbon display: bold clean silhouette, strong contrast, simple visible arrows with substantial arrowheads and line weight, no tiny intricate detailing. Cube fills most of the square; arrows stay separated from cube and fully inside canvas; tightly framed with only about 5 percent transparent padding. Genuine transparent alpha background, no checkerboard drawn into image, no ground plane, no background glow, no cast shadow outside the icon. The asset is a single standalone icon, not a mockup. Square PNG.
