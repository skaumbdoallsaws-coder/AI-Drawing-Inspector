"""Verify feature #110 - cross-check instruction in INSPECTION_PROMPT."""
import sys
sys.path.insert(0, ".")

from ai_inspector.spatial.engine import INSPECTION_PROMPT

# Check 1: Prompt includes cross-check instruction
assert "inspection profile's feature type classification may occasionally be wrong" in INSPECTION_PROMPT, "Missing cross-check instruction"

# Check 2: Concrete examples - countersink vs counterbore
assert "Countersink" in INSPECTION_PROMPT and "Counterbore" in INSPECTION_PROMPT, "Missing countersink/counterbore examples"
assert "diameter + depth (no angle)" in INSPECTION_PROMPT, "Missing counterbore identification clue"
assert "diameter + angle (no depth)" in INSPECTION_PROMPT, "Missing countersink identification clue"

# Check 3: Through vs blind examples
assert "Through hole" in INSPECTION_PROMPT and "Blind hole" in INSPECTION_PROMPT, "Missing through/blind examples"
assert "depth dimension" in INSPECTION_PROMPT, "Missing blind hole identification clue"

# Check 4: Trust drawing callout instruction
assert "trust the" in INSPECTION_PROMPT and "drawing callout" in INSPECTION_PROMPT, "Missing trust-drawing instruction"

# Check 5: Note discrepancy in observation field
assert "Profile classifies this as" in INSPECTION_PROMPT, "Missing observation field instruction"
assert "callout indicates" in INSPECTION_PROMPT, "Missing callout indicates instruction"

# Check 6: Evaluate against correct type
assert "Evaluate the feature against the CORRECT feature type" in INSPECTION_PROMPT, "Missing evaluate-correct-type instruction"

# Check 7: Add to representation_gaps
assert "Profile misclassification" in INSPECTION_PROMPT, "Missing representation_gaps instruction"

# Check 8: Existing structure intact
assert "## Your Task" in INSPECTION_PROMPT, "Missing Your Task section"
assert "## Inspection Profile" in INSPECTION_PROMPT, "Missing Inspection Profile section"
assert "## Output" in INSPECTION_PROMPT, "Missing Output section"
assert "gap_summary" in INSPECTION_PROMPT, "Missing gap_summary in output"
assert "view_assessment" in INSPECTION_PROMPT, "Missing view_assessment in output"
assert "representation_score" in INSPECTION_PROMPT, "Missing representation_score"
assert "asme_compliance" in INSPECTION_PROMPT, "Missing asme_compliance"

# Check 9: When counterbore callout found for countersink profile, evaluate as counterbore
assert "evaluate against counterbore requirements" in INSPECTION_PROMPT, "Missing counterbore evaluation instruction"

sys.stdout.write("ALL CHECKS PASSED - Feature #110 verification complete\n")
sys.stdout.write(f"INSPECTION_PROMPT length: {len(INSPECTION_PROMPT)} chars\n")
