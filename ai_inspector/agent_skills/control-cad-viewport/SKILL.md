---
name: control-cad-viewport
description: Control the CAD viewport for an explicit show, highlight, hide, restore, transparency, rotation, or motion command. Use only when the user requests a visible state change.
---

# Control CAD Viewport

Treat viewport state as persistent and change only what the user requested.

## Authorization

- Questions and explanations are read-only even when they mention affected parts or motion.
- Require an explicit display or motion command before requesting a viewport write.
- Use exact validated part, feature, motion, and viewport IDs from live context.
- If the target cannot be resolved, ask for clarification and request no action.

## State Rules

- Highlight changes selection focus; hide changes visibility. Do not substitute one for the other.
- Preserve motion, rotation, hidden parts, transparency, and unrelated highlights unless the user asks to change them.
- Add to existing highlights only when the user says `also`, `add`, `include`, `plus`, or equivalent.
- Start motion only when motion, movement, animation, playback, or an explicit RPM is requested.
- Treat RPM as a visualization rate and clamp it to the package range.
- Combine highlight and motion only when both are part of the requested visual result.

## Execution

Prefer one registered executor recipe with minimal typed inputs. The runtime resolves live IDs and emits the ordered action bundle. Do not invent action IDs or claim an action succeeded before the viewport confirms it.
