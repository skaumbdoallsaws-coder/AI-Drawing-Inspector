"""Version identifiers for revision-bound parts-manual rendering."""


# Increment whenever browser rendering or server-side render QA changes in a
# way that makes previously accepted captures unsuitable for publication.
# v5: automatic repeated-part callouts became representative_with_count (one
# balloon, one leader, an nX badge) and automatic leaders terminate with a dot
# instead of an arrowhead. Captures made under v4 carry branched leaders and
# arrowheads, so they must not be reused for publication.
# v6: automatic leaders use the straight-first route policy, persist the exact
# balloon-circumference attachment point, and bound automatic orthogonal
# fallback to one elbow. Older captures cannot prove those route contracts.
PARTS_MANUAL_RENDER_PIPELINE_VERSION = 6

# Automatic parts-manual leaders terminate on a small solid dot. An arrowhead
# stays available per leader through an explicit user override; this constant is
# only the generated default. Work-instruction leaders are a separate contract
# and are not affected.
PARTS_MANUAL_DEFAULT_END_CONDITION = "dot"
