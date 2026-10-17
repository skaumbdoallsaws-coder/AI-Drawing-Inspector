"""Optional dependencies for the explicitly isolated Codex desktop test only."""
import os
import site

if os.environ.get("INSPECTORPRO_CODEX_DESKTOP_TEST_DEPS"):
    site.addsitedir(os.environ["INSPECTORPRO_CODEX_DESKTOP_TEST_DEPS"])
