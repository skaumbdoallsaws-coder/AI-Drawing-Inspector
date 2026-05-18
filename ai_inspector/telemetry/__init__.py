"""Runtime telemetry for InspectorPro.

Phase 1 of docs/usage-cost-dashboard-plan.md: storage foundation +
pricing table + helpers. Call-site instrumentation lands in Phase 2;
this module ships unwired to keep the change reviewable.

Public surface:

    TelemetryEvent              dataclass with the §3 field set
    TelemetryStore              SQLite-backed store
    default_db_path()           where the default store writes
    ENV_VAR                     "INSPECTORPRO_METRICS_DB" override

    PRICING_TABLE               dict keyed by (provider, model)
    PricingEntry                one row of the table
    lookup_pricing(p, m)        Optional[PricingEntry]
    compute_cost(...)           (cost_usd, confidence) tuple

    record_event(event)         soft-fail write (never raises)
    record_provider_call(...)   convenience: build + record in one call
    new_event_id() / new_request_id()
    time_block()                context manager → elapsed ms
    get_default_store()         process-wide default
    reset_default_store_for_tests()
"""

from .models import TelemetryEvent
from .store import (
    TelemetryStore,
    default_db_path,
    ENV_VAR,
    SCHEMA_VERSION,
    SCHEMA_SQL,
)
from .pricing import (
    PricingEntry,
    PRICING_TABLE,
    lookup_pricing,
    compute_cost,
    CONFIDENCE_VERIFIED,
    CONFIDENCE_ESTIMATED,
    CONFIDENCE_UNKNOWN,
)
from .instrumentation import (
    new_event_id,
    new_request_id,
    record_event,
    record_provider_call,
    record_anthropic_call,
    record_openai_call,
    record_openai_transcription,
    record_endpoint_event,
    record_workflow_stage,
    classify_exception_status,
    time_block,
    get_default_store,
    reset_default_store_for_tests,
)

__all__ = [
    "TelemetryEvent",
    "TelemetryStore",
    "default_db_path",
    "ENV_VAR",
    "SCHEMA_VERSION",
    "SCHEMA_SQL",
    "PricingEntry",
    "PRICING_TABLE",
    "lookup_pricing",
    "compute_cost",
    "CONFIDENCE_VERIFIED",
    "CONFIDENCE_ESTIMATED",
    "CONFIDENCE_UNKNOWN",
    "new_event_id",
    "new_request_id",
    "record_event",
    "record_provider_call",
    "record_anthropic_call",
    "record_openai_call",
    "record_openai_transcription",
    "record_endpoint_event",
    "record_workflow_stage",
    "classify_exception_status",
    "time_block",
    "get_default_store",
    "reset_default_store_for_tests",
]
