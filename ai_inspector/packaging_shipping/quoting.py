"""One path for every carrier request; the manual Rates panel and Sage share it.

QuoteDesk owns provider selection, the account reference used for staleness, the single provider
lock, quote reuse and the attempt audit. Scenarios hold the addresses a user entered for this
session in server memory only (never stored), so the user can let Sage quote by scenario ID within
a provider-shipment budget and time limit. Sage sees city, state and residential status, never a
name, street or ZIP code.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import secrets
import threading
import time

from .destinations import check_address
from .geometry import digest
from .models import QuoteRequest, ScenarioAuthorization
from .rating import EasyPostRating
from .service import PackagingError

SCENARIOS_PER_DOCUMENT = 8
SCENARIOS_TOTAL = 200
MODE_UNCONFIRMED = ("Record whether the saved EasyPost key is a test or production key before requesting anything from "
                    "EasyPost. Check the key in the EasyPost dashboard; the account alias is only a label. No request was sent.")


def place(address):
    """City-level label for an Address or a saved quote destination; no name, street or ZIP code."""
    get = address.get if isinstance(address, dict) else (lambda key: getattr(address, key))
    return f"{get('city')}, {get('state')}" + (" (residential)" if get("residential") else "")


@dataclass
class Scenario:
    id: str
    scope: str
    document_id: str
    principal_id: str
    authorization: ScenarioAuthorization
    scenario_hash: str
    created_at: float
    expires_at: float
    used_shipments: int = 0

    def public(self, now):
        a = self.authorization
        return {"id": self.id, "scenario_hash": self.scenario_hash, "origin": place(a.origin),
                "destinations": [place(d) for d in a.destinations], "sage_shipments": a.sage_shipments,
                "shipments_remaining": max(0, a.sage_shipments - self.used_shipments),
                "expires_in_s": max(0, round(self.expires_at - now))}

    def request(self, revision, refresh=False):
        fields = self.authorization.model_dump(exclude={"sage_shipments", "minutes"})
        return QuoteRequest.model_validate({**fields, "expected_revision": revision, "refresh": refresh})


class ScenarioStore:
    """In-memory scenario authorizations, each owned by one user and document; a restart or expiry forgets them."""

    def __init__(self, clock=time.time):
        self._items: dict[str, Scenario] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def _prune(self, now):
        for key in [k for k, v in self._items.items() if v.expires_at <= now]:
            del self._items[key]

    def _find(self, scope, document_id, principal_id, scenario_id):
        item = self._items.get(scenario_id)
        if item is None or (item.scope, item.document_id, item.principal_id) != (scope, document_id, principal_id):
            raise PackagingError("scenario_not_found", "That quote scenario is not authorized for you on this document. "
                                 "It may have expired or been revoked.", 404)
        return item

    def create(self, scope, document_id, principal_id, authorization: ScenarioAuthorization):
        # Refuse what rating would refuse before anything is held or offered to Sage.
        if authorization.ship_date is not None:
            raise PackagingError("ship_date_unsupported", "A specific ship date is not supported: EasyPost does not document that "
                                 "rates honor a later date. Leave the ship date empty to rate as of today.", 422)
        check_address(authorization.origin, "origin")
        for i, destination in enumerate(authorization.destinations):
            check_address(destination, f"destination {i + 1}")
        now = self._clock()
        with self._lock:
            self._prune(now)
            mine = [v for v in self._items.values() if (v.scope, v.document_id, v.principal_id) == (scope, document_id, principal_id)]
            if len(mine) >= SCENARIOS_PER_DOCUMENT or len(self._items) >= SCENARIOS_TOTAL:
                raise PackagingError("scenario_limit", "Revoke an older quote scenario before authorizing another.", 409)
            item = Scenario("scn_" + secrets.token_hex(12), scope, document_id, principal_id, authorization,
                            digest(authorization.scenario()), now, now + authorization.minutes * 60)
            self._items[item.id] = item
            return item.public(now)

    def list(self, scope, document_id, principal_id):
        now = self._clock()
        with self._lock:
            self._prune(now)
            return [v.public(now) for v in sorted(self._items.values(), key=lambda v: v.created_at)
                    if (v.scope, v.document_id, v.principal_id) == (scope, document_id, principal_id)]

    def get(self, scope, document_id, principal_id, scenario_id) -> Scenario:
        now = self._clock()
        with self._lock:
            self._prune(now)
            return self._find(scope, document_id, principal_id, scenario_id)

    def remaining(self, scope, document_id, principal_id, scenario_id) -> int:
        try:
            return self.get(scope, document_id, principal_id, scenario_id).public(self._clock())["shipments_remaining"]
        except PackagingError:
            return 0

    def revoke(self, scope, document_id, principal_id, scenario_id):
        with self._lock:
            self._find(scope, document_id, principal_id, scenario_id)
            del self._items[scenario_id]
        return {"revoked": scenario_id}

    def reserve(self, scope, document_id, principal_id, scenario_id, shipments):
        """Take provider shipments from a scenario's budget before any provider request is sent.

        A failed or interrupted attempt keeps its reservation: spending is counted, never refunded on a guess.
        """
        now = self._clock()
        with self._lock:
            self._prune(now)
            item = self._find(scope, document_id, principal_id, scenario_id)
            left = item.authorization.sage_shipments - item.used_shipments
            if shipments > left:
                raise PackagingError("scenario_budget_exhausted", f"This quote needs {shipments} provider shipment(s); the scenario "
                                     f"allows {left} more. Ask the user to authorize a new scenario.", 409)
            item.used_shipments += shipments


class QuoteDesk:
    def __init__(self, service, *, rating=None, credential_factory=None, clock=time.time):
        self.service = service
        self.provider = rating or EasyPostRating()
        self.credential_factory = credential_factory
        self.lock = asyncio.Lock()
        self.scenarios = ScenarioStore(clock)
        # account_ref -> the mode EasyPost last reported in this process, so a contradiction blocks later
        # requests even if writing it to the credential store failed.
        self.observed = {}

    def account(self, resolved):
        if self.credential_factory is None:
            raise PackagingError("carrier_secure_store_disabled", "This host has not enabled local carrier account storage.", 403)
        return self.credential_factory(resolved)

    def current_provider(self, resolved):
        """A fresh provider for each request when a credential store is configured, never cached."""
        if self.credential_factory is None:
            return self.provider, None
        credential = self.account(resolved).resolve()
        return EasyPostRating(key=credential.api_key.get_secret_value(), account_ref=credential.account_ref,
                              declared_mode=credential.declared_mode), credential

    def require_mode(self, selected, credential):
        """Every provider request needs a recorded key mode that EasyPost has not contradicted. A contradiction is
        known only from a response, so this refuses the requests after it, never the one that revealed it."""
        declared = credential.declared_mode if credential else selected.declared_mode
        if credential:
            observed = self.observed.get(credential.account_ref) or credential.observed_mode
        else:
            observed = selected.observed_mode
        if declared is None and selected.status().get("configured"):
            raise PackagingError("account_mode_unconfirmed", MODE_UNCONFIRMED, 409)
        if declared is not None and observed is not None and observed != declared:
            raise PackagingError("account_mode_mismatch", f"EasyPost last answered this key in {observed} mode, but it is recorded as "
                                 f"a {declared} key. Check the key in the EasyPost dashboard, then record its mode again or replace "
                                 "the key. No request was sent.", 409)

    def observe(self, resolved, selected, credential):
        """Keep the mode EasyPost reported, so a contradicted record blocks later requests. Never masks the outcome
        and never stops the attempt audit: if the store cannot be written its record stays as it was, and this process
        still refuses later requests from its own record of the observation."""
        if credential is None or selected.observed_mode is None:
            return  # The direct provider keeps its last observed mode itself.
        if credential.account_ref:
            self.observed[credential.account_ref] = selected.observed_mode
        try:
            self.account(resolved).observe_mode(credential.account_ref, selected.observed_mode)
        except Exception:
            pass

    def current_account(self, resolved):
        """(account_ref, known) for staleness; unknown when the store cannot be read."""
        if self.credential_factory is None:
            return self.provider.account_ref, True
        try:
            status = self.account(resolved).status()
        except PackagingError:
            return None, False
        return status.get("account_ref"), status.get("source") != "unavailable"

    def status(self, resolved):
        return self.account(resolved).status() if self.credential_factory else self.provider.status()

    def busy(self):
        if self.lock.locked():
            raise PackagingError("quote_in_progress", "A quote request is already running. Wait before retrying.", 429)

    async def price(self, scope, doc_id, revision, design, assessment, body, resolved, find, save, *, reserve=None):
        """Reuse an identical saved quote unless refresh is asked for; otherwise rate and audit the attempt.

        reserve(shipments), when given, is charged before any provider request (Sage scenario budgets).
        """
        self.busy()
        async with self.lock:
            selected, credential = self.current_provider(resolved)
            if credential:
                credential.check()
            self.require_mode(selected, credential)
            selected.preflight(design, assessment, body)
            fingerprint = selected.fingerprint(assessment, body)
            if not body.refresh:
                # The identical scenario was already priced for this design and account: no new shipments.
                saved = find(fingerprint)
                if saved is not None:
                    return {**saved, "reused": True}
            if reserve is not None:
                reserve(len(design.packages) * len(body.destinations))
            attempt_id = self.service.begin_quote_attempt(scope, doc_id, revision, fingerprint)
            counts, outcome, error_code, quote_id = {}, "failed", None, None
            try:
                result = await selected.quote(design, assessment, body, counts)
                if credential:
                    credential.check()
                saved = save(result)
                outcome, quote_id = "saved", saved["id"]
                return {**saved, "reused": False}
            except PackagingError as exc:
                error_code = exc.code
                raise
            except asyncio.CancelledError:
                outcome = "cancelled"
                raise
            finally:
                self.observe(resolved, selected, credential)
                self.service.finish_quote_attempt(scope, doc_id, attempt_id, outcome, counts, error_code=error_code, quote_id=quote_id)

    async def carrier_accounts(self, resolved):
        self.busy()
        async with self.lock:
            selected, credential = self.current_provider(resolved)
            if credential:
                credential.check()
            self.require_mode(selected, credential)
            return await selected.carrier_accounts()
