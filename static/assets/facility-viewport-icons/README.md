# Facility Viewport Icons

These transparent SVG companions use the same upper-left material gradients as
the Facility ribbon. Regenerate both sets with:

`node tools/build_facility_ribbon_icons.cjs`

Both Plan and 3D share the same navigation assets at 24px. Display settings uses amber sliders,
appearance reuses the approved Packaging swatches, and orientation retains the
existing face-specific cube images and menu. Grid is a single lattice plane;
Layers is a silver/teal/plum stack. Walkthrough is green, Drone is amber, and
Record retains its conventional red indicator.

Plan also uses a silver/teal pointer, a teal reset arrow, and an amber magnet
for snapping. Its metre/feet control retains the current unit as text.

Familiar walking, drone and location symbols reuse the existing Phosphor
geometry. Its MIT license is included. The source generator maintains the
remaining command-specific geometry; no generated bitmap edits were used.

Only Facility's Plan and 3D toolbars consume this set. Assembly and other
shared viewer consumers are unchanged. Both toolbars use 28px buttons;
commands, order, tooltips, selected state and availability still come from
the workspace.
