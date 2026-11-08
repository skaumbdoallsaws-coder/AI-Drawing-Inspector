# Facility Ribbon Artwork

Seven generated transparent PNGs provide the primary Zones, Aisle, Walls/Floors,
Position, Patterns, Cells and Stack artwork. Generation prompts and provenance
are in `generation-prompts.json`. They were made with the built-in image tool,
using the approved sidebar cube as a lighting and finish reference.

Appearance, Auto Arrange, Save, Undo and Redo primary paths reuse approved
Packaging assets. Small controls and dropdowns use simplified transparent SVGs,
built with `node tools/build_facility_ribbon_icons.cjs`. The familiar editing
symbols derive from the existing Phosphor set; its MIT license is included.
Domain-specific geometry is maintained in the same generator.

`static/facility_ribbon_icons.js` maps command IDs to artwork only. Existing
command definitions, handlers, shortcuts and state validation remain in the
application. The companion CSS changes Facility ribbon presentation only.

The live renderer checks cover transparency, loading, ribbon height, label and
button bounds, command reachability at responsive widths, real menu activation,
selection states and unchanged geometry. They run in a disposable desktop
profile through `desktop/tools/facility-ribbon-check.cjs`.
