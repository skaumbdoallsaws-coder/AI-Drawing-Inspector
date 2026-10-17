# Private Gym APEX Court

Date: 2026-10-08. User-directed appearance update, followed by removal of the blue player from the center wall.

## Final Scope

- Side wall paint: `#292D32`; center/back wall paint: `#45484B`.
- Metallic gold accent material: `#C99B39`, with authored roughness and metalness preserved by the renderer.
- Two transparent-background side players; the center wall has only the supplied APEX GYM / HIGHER EVERYDAY branding, centered above the unchanged hoop.
- Six local, warm spotlights and slim luminous wall strips. Preview intensity was reduced from 95 to 8 to avoid harsh hotspots. This is presentation lighting, not a lighting-design qualification.
- All 106 placement transforms, floor geometry, court markings, hoop height and physical wall envelopes are unchanged. Outside-facing charcoal finishes remain unchanged.
- The court remains open-air. There was no ceiling to recolor. Adding a canopy was raised as a clarification and was not authorized; `#151719` has not been applied to nonexistent geometry.

## Artifacts

The supplied red player and APEX logo retain their original PNG bytes and alpha channels. The supplied blue player was used in the initial theme and then removed at the user's request. The original yellow/purple player poster was background-extracted with the built-in image-generation tool; its source poster remains untouched.

Project assets are under `generated/industrial_assets/private_gym/apex-court/`: `left/player.png`, `right/player.png`, and `back/branding-only/centered/apex-logo.png`. The current center-wall GLB is `back/branding-only/centered/model.glb`; it contains exactly one embedded image, the logo. Earlier revisions remain available rather than destructively replacing saved asset identities.

The October 8 centering follow-up uses local wall X=0, aligned with the court centerline. The original 3:1 PNG is fitted to 4.95 x 1.65 m, with its center at 4.525 m elevation, above the retained backboard. The supplied reference has no visible hoop; the authored layout keeps its actual hoop, wall height and attachment geometry rather than removing them to match the illustration.

Background-extraction prompt: "Produce a genuinely transparent RGBA PNG cutout containing ONLY the foreground illustrated basketball player wearing the yellow and purple uniform and holding the basketball. Preserve his exact face, muscular body, pose, limbs, clothes, colors, basketball, and comic illustration style. Remove ALL background elements: the giant background face, paint splashes, crown, stadium, lights, crowd, hoop, net, and lettering. Do not change the player or add any new content. Keep clean antialiased cutout edges, no rectangular background, no glow, no drop shadow, no checkerboard drawn into the image. Portrait composition with the entire existing foreground player's visible silhouette retained. Intended for a wall mural in a 3D gym."

This is an image-generation edit, not a claim of pixel-exact extraction. The two final supplied source files were not regenerated.

## Implementation

- `tools/gym_theme_wall.py`: same-envelope GLB construction with alpha artwork, gold trim and `KHR_lights_punctual` spotlights.
- `tools/style_private_gym_apex_court.py`: staged validation/publication and revision-bound Save. `--branding-only` limits the follow-up to the center-wall asset plus its required support and exterior-face revision bindings.
- `static/facility_layout_three_adapter.js`: preserves explicitly authored finish materials, keeps light-bearing models out of mesh-only instancing, and reports actual rendered light counts. Ordinary asset appearance and selection behavior remain covered by the existing suite.

## Verification

- 108/108 JavaScript adapter checks passed, including source finishes, instanced finishes, selection reset and repeated light-bearing assets.
- 50 Python checks passed across themed wall envelopes, alpha artwork, center-player removal, centered logo bounds, attachments and exterior finishes.
- Normal desktop previews verified transparent artwork, readable branding, gold accents and six actual rendered lights. Before/after assertions preserve geometry and unrelated saved layouts.
- Evidence: `.runtime/private-gym-apex-court-20261007/`, `.runtime/private-gym-apex-branding-only-20261008/` and final `.runtime/private-gym-apex-centered-20261008/`, including native screenshots and saved-reload receipts.
- A separate Playwright Electron launch failed before obtaining a window. Desktop screenshots and pixel checks use the native capture harness; compact/mobile screenshots are not qualified by that attempt. No authentication or desktop security controls were bypassed.
