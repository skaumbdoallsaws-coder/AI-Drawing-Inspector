"""Turn-bound public-research policy in the existing generation repository.

The model interprets the user's clause. This module validates its provenance and
enforces the resulting policy; quote matching is not semantic verification.
"""
from copy import deepcopy

from .design_brief import design_revision
from .design_repository import _exists, _read_json
from .errors import FacilityConflictError, FacilityValidationError
from .generation_admission import _closed

POLICY_TOOL = "record_generation_research_policy"
POLICY_KIND = "generation_research_policy_v1"
MAX_POLICY_TURNS = 64


class GenerationResearchPolicy:
    def __init__(self, repository):
        self.repository = repository

    def _path(self, tenant_id, site_id, ledger_id):
        return self.repository._ledger_root(tenant_id, site_id, ledger_id) / "research-policy.json"

    def get(self, tenant_id, site_id, ledger_id):
        path = self._path(tenant_id, site_id, ledger_id)
        if not _exists(path):
            return None
        record = _read_json(path, missing_code="generation_research_policy_not_found")
        body = {key: value for key, value in record.items() if key != "revision"}
        if (set(record) != {"recordKind", "ledgerId", "decisions", "revision"}
                or record["recordKind"] != POLICY_KIND or record["ledgerId"] != ledger_id
                or not isinstance(record["decisions"], list) or not 1 <= len(record["decisions"]) <= MAX_POLICY_TURNS
                or record["revision"] != design_revision(body)):
            raise FacilityValidationError("generation_research_policy_corrupt", "Research policy failed integrity checks.")
        return record

    def overview(self, tenant_id, binding, *, turn=None, message=None):
        record = self.get(tenant_id, binding["siteId"], binding["ledgerId"])
        latest = record["decisions"][-1] if record else None
        return {"policyRevision": record["revision"] if record else None,
                "mode": latest["mode"] if latest else "allow",
                "currentTurnRecorded": bool(latest and latest["turnId"] == turn
                    and latest["messageRevision"] == design_revision(message)),
                "decision": deepcopy(latest),
                "scope": "New public search/read calls, including cached tool responses. Retained evidence is not revoked.",
                "default": "Public research permitted by application policy, subject to current user restrictions."}

    def record(self, principal, binding, arguments, message, turn):
        _closed(arguments, {"expectedPolicyRevision", "decision", "sourceText"}, "research policy")
        decision, quote = arguments["decision"], arguments["sourceText"]
        if decision not in ("inherit", "allow", "deny", "clarify"):
            raise FacilityValidationError("generation_research_policy_invalid", "Choose inherit, allow, deny or clarify.")
        if decision == "inherit":
            valid = quote is None
        else:
            valid = (isinstance(quote, str) and bool(quote.strip()) and len(quote) <= 8000
                     and message.count(quote) == 1)
        if not valid:
            raise FacilityValidationError("generation_research_policy_quote_invalid",
                "An explicit policy decision needs an exact unique current-user clause; inherit needs null sourceText.")
        path = self._path(principal.tenant_id, binding["siteId"], binding["ledgerId"])
        signature = design_revision({"turn": turn, "message": message, "arguments": arguments})
        with self.repository._write_lock(principal.tenant_id, binding["siteId"]):
            prior = self.get(principal.tenant_id, binding["siteId"], binding["ledgerId"])
            decisions = deepcopy(prior["decisions"]) if prior else []
            previous = next((item for item in decisions if item["turnId"] == turn), None)
            if previous:
                if previous["requestSignature"] != signature:
                    raise FacilityConflictError("generation_research_policy_retry_conflict",
                        "This turn's policy is already recorded. Changed authority needs a new user turn.")
                if previous != decisions[-1]:
                    raise FacilityConflictError("generation_research_policy_stale", "A newer turn superseded this policy.")
                return self.overview(principal.tenant_id, binding, turn=turn, message=message)
            if arguments["expectedPolicyRevision"] != (prior["revision"] if prior else None):
                raise FacilityConflictError("generation_research_policy_revision_conflict", "Inspect the current research policy before recording.")
            if len(decisions) >= MAX_POLICY_TURNS:
                raise FacilityValidationError("generation_research_policy_budget_exceeded", "Research policy history is full; start a new planning workspace.")
            mode = (decisions[-1]["mode"] if decisions else "allow") if decision == "inherit" else decision
            decisions.append({"turnId": turn, "messageRevision": design_revision(message), "decision": decision,
                              "mode": mode, "sourceText": quote, "requestSignature": signature,
                              "expectedPolicyRevision": arguments["expectedPolicyRevision"]})
            body = {"recordKind": POLICY_KIND, "ledgerId": binding["ledgerId"], "decisions": decisions}
            self.repository._atomic_write(path, {**body, "revision": design_revision(body)})
        return self.overview(principal.tenant_id, binding, turn=turn, message=message)

    def require_research(self, principal, binding, turn, message):
        policy = self.overview(principal.tenant_id, binding, turn=turn, message=message)
        if not policy["currentTurnRecorded"]:
            raise FacilityConflictError("generation_research_policy_required",
                "Record this actual user turn's research policy before any search or read.")
        if policy["mode"] != "allow":
            raise FacilityValidationError("generation_research_forbidden",
                "Public research is blocked by the retained user policy. Use local information or ask for clarification.")
        # A permission change does not silently erase an already recorded brief.
        from .design_repository import FacilityDesignRepositoryNotFoundError
        try:
            ledger = self.repository.get_ledger(principal.tenant_id, binding["siteId"], binding["ledgerId"])["ledger"]
        except FacilityDesignRepositoryNotFoundError as exc:
            if exc.code != "generation_ledger_not_found":
                raise
            ledger = None
        if any(item["disposition"] == "represented" and item["predicate"]["kind"] == "research_policy"
               and not item["predicate"]["parameters"]["publicWebAllowed"] for item in (ledger or {}).get("requirements", [])):
            raise FacilityConflictError("generation_research_ledger_restricted",
                "Record the explicit policy correction in the retained requirements before researching.")
        return policy["policyRevision"]
