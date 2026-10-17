# Desktop Startup Stack Sampling

September 28, 2026. Bounded reliability fix; not general demo qualification.

## Finding

The normal managed backend armed `faulthandler.dump_traceback_later(20, repeat=True)`
around application import. The opt-in import diagnostic also used this C watchdog.
Native-14's replacement process exited with Windows `0xC0000005` while emitting
its timeout traceback. The installed interpreter is CPython 3.14.0, built October
7, 2025; no interpreter or Electron binary was changed.

A standalone frame-churn reproducer, without InspectorPro, network calls, or
application stores, crashed all eight disposable children with `0xC0000005` while
using the C watchdog. The same eight-child workload with cooperative Python
frame sampling completed successfully. Evidence is retained, including full
child diagnostics:

- `.runtime/probe_startup_watchdog.py`
- `.runtime/startup-watchdog-legacy-01/report.json` (8/8 crashed)
- `.runtime/startup-watchdog-cooperative-01/report.json` (8/8 completed)

This matches the failure class documented in CPython's
[invalid/freed-frame issue](https://github.com/python/cpython/issues/140815) and
[3.14 backport](https://github.com/python/cpython/pull/140981), both newer than this
interpreter build. Attribution of native-14 to that precise upstream defect is
an inference: no native crash dump identifies its faulting instruction. The
local reproduction does establish that the diagnostic could itself crash this
interpreter. It does not explain every historical slow import or timeout.

## Change

`desktop/runtime/startup_diagnostics.py` now samples retained Python frames from
a normal daemon thread. It records filenames, function names, and line numbers,
not source text, locals, arguments, or value representations. Thread/frame counts,
field lengths, and repetition are bounded. Both text and binary outputs work.
Cancellation precedes descriptor closure; a blocked writer preserves its handle
and reports that cancellation is incomplete rather than claiming safe closure.

Normal startup and the opt-in diagnostic share this sampler. Failures to create,
arm or stop normal startup diagnostics report a bounded error type without
replacing the primary application import error. Original failed-run evidence
is not overwritten. The parent startup deadline, process ownership, protected
backend identity, and cleanup checks remain unchanged.

Limitation: cooperative sampling requires interpreter progress. It cannot sample
through a native extension holding the GIL indefinitely. The parent's independent
startup deadline and termination checks remain responsible for that failure.

## Verification

The fresh normal-backend campaign used an isolated copy, without provider calls,
renderer, editing, or Save. All ten real start/restart cases passed with distinct
verified identities, confirmed cleanup, and unchanged original/copied layout
hashes. Startup times were 5535, 2599, 2432, 2407, 2489, 2446, 3422, 2583, 2483,
and 2540 ms. The normal application deadline remains 120,000 ms.

Campaign: `.runtime/demo-readiness-startup-01/check/report.json`.
Runner: `desktop/tools/application-startup-check.cjs`; it requires an isolated
profile from `desktop/tools/prepare-application-check.py` and a fresh output
directory. These are reliability samples, not a clean latency/p95 campaign:
part of the run overlapped focused local regression tests.

Native-15 subsequently passed actual Electron chat generation, a quantity-only
correction, real Plan/3D rendering, unsaved Apply, owned-backend restart and exact
Undo. Both owned backends closed gracefully. This closes that individual native
lifecycle checkpoint, not the performance gate. See the
[generation performance report](sage-generation-performance-reliability-pass.md).

Regression evidence:

- `.runtime/demo-startup-tests02.xml`: 23 Python tests and 27 subtests passed.
- `.runtime/demo-readiness-tests03.xml`: 217 Python tests and 30 subtests passed,
  including normal-startup diagnostic failure preservation and focused generation
  regressions. These suites overlap; counts are not additive.

Remaining: repeated native/provider workloads, latency, held-out semantic inputs,
and research-assisted generation. A passing startup campaign grants no new
manufacturing, safety, source-authority or Save permissions.
