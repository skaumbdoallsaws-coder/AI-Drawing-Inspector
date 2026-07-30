# Facility Layout Manual Screen-Reader Checklist

**Status: Pending**

This artifact is intentionally pending. The automated browser audit does not
perform, simulate, or claim a screen-reader audit.

## Test Record

- Tester:
- Date:
- InspectorPro commit:
- Browser and version:
- Screen reader and version:
- Windows version:
- Facility Layout evidence summary:

## Preconditions

- Use a clean browser profile.
- Enable the Facility Layout pilot flags.
- Load a layout containing at least one placement, one zone, and one route.
- Test once in light theme and once in dark theme.
- Do not use a mouse during the keyboard and screen-reader flows.

## Entry And Orientation

- Confirm the workspace is announced as "Facility layout workspace."
- Confirm the toolbar, asset catalog, plan/3D view tabs, properties pane, and
  status region can be discovered through landmarks or sequential navigation.
- Confirm the current view, selected tool, saved state, and selection count are
  understandable without looking at the screen.

## Keyboard Navigation

- Tab into and out of the workspace in both directions.
- Traverse every enabled toolbar command without a focus trap.
- Verify visible keyboard focus at every stop.
- Navigate between Plan and 3D tabs using the expected tab-list keys, then
  activate each view.
- Navigate the asset tree by keyboard and place an asset with Enter and Space.
- Use Undo, Redo, Fit, Select, Pan, Rotate, Lock, Duplicate, Delete, and Save
  where enabled.
- Press Escape during a placement preview and confirm focus and state recover.

## Names, Roles, And States

- Confirm every command has a concise name and correct role.
- Confirm disabled commands are announced as unavailable.
- Confirm selected tabs and pressed tool buttons expose their state.
- Confirm the workspace busy state changes while an operation is pending.
- Confirm plan and 3D surfaces have distinguishable names.
- Confirm selected placements expose enough identity and position information
  in the properties pane.

## Announcements

- Place an asset and confirm the working, selection, and unsaved-state changes
  are announced once and in a useful order.
- Undo the placement and confirm the restored state is announced.
- Trigger a valid placement alternative and confirm its authority and position
  are announced.
- Trigger an invalid or unavailable action and confirm the error is announced
  without moving focus unexpectedly.
- Open and dismiss a full-layout proposal and confirm focus returns to the
  originating command.

## 3D And Non-Visual Equivalence

- Confirm switching to 3D does not strand keyboard focus on the canvas.
- Confirm layout objects available visually in 3D remain discoverable through
  the tree, properties, status, or an equivalent structured surface.
- Confirm orbiting is not required to understand or approve a safety finding.
- Record any information available only through color, position, or motion.

## Completion Rule

Do not change the status to complete until a named human tester has executed
the checklist with a real screen reader and attached findings. Automated
evidence cannot satisfy this gate.
