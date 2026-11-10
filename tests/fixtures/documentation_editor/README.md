# Documentation editor fixtures

`scene-v2-mmle-excerpt.json` is reduced from the authorized local MMLE-50D
schema-2 scene. It retains three real cover rotation commands and two successive
part-description overrides. The retained projection is the replay of those five
commands. Source/plan revisions, command IDs, timestamps and the part-definition
identifier are sanitized. No assets, private paths or full local files are included.

The source scene contains 43 commands. This excerpt deliberately omits unrelated
CAD transforms and the later reset of the selected description, so the fixture
exercises a visible saved override and a nonempty history together.

The repository ignores JSON globally. Claude must explicitly include this small
reviewed fixture if committing it; no ignore rules were changed by the builder.
