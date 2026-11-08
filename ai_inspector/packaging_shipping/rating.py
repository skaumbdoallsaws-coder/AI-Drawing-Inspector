"""Quote-only EasyPost adapter. There is deliberately no purchase endpoint.

Provider behaviour relied on here (EasyPost docs, checked 2026-11-06): rating
creates a Shipment, which is an external write even though nothing is bought.
Each Rate carries `rate` (the rate available to this account), `list_rate`
(published, non-negotiated) and `retail_rate` (in-store, no account). Carrier
failures arrive in `messages` as carrier free text. Negotiated rates appear only
in production mode; test-mode rates are not live carrier quotes. Parcel
dimensions are inches to one decimal place and weights are ounces (Parcel
docs). Listing carrier accounts needs a production key and returns credential
fields, which never leave this module.
"""
from __future__ import annotations

import asyncio
from decimal import ROUND_CEILING, Decimal, InvalidOperation
import hashlib
import os
import re
import httpx

from .credentials import ACCOUNT_MODES, MODE_ENVIRONMENT, account_reference
from .destinations import check_address
from .geometry import digest
from .provenance import contents_record, weight_basis
from .service import PackagingError, now

API = "https://api.easypost.com/v2"
ADAPTER = "easypost-quote-v2"
OUNCE_KG = .028349523125
INCH_M = .0254
MAX_RESPONSE_BYTES = 1000000
MAX_MESSAGES = 20
MAX_ACCOUNTS = 200

MESSAGE_CATEGORIES = (
    ("address", re.compile(r"address|zip|postal|city|street|residential|delivery area|remote|country", re.I)),
    ("package", re.compile(r"weight|dimension|length|width|height|girth|oversize|parcel|package|size", re.I)),
    ("account", re.compile(r"account|credential|auth|permission|disabled|not enabled|contract|negotiated", re.I)),
    ("service", re.compile(r"service|unavailable|not available|not supported|no rates|cannot be rated|not offered", re.I)),
)
MESSAGE_HELP = {
    "address": "The carrier could not rate one of the addresses. Check street, city, state and ZIP.",
    "package": "The carrier rejected the package size or weight for some services.",
    "account": "The carrier account could not rate this request. Check that it is enabled for these services.",
    "service": "Some services are not available for this route or package.",
    "other": "The carrier reported a problem without a recognised category.",
}
PRICE_BASES = {
    "amount": "Account rate: the rate EasyPost returned as available to this account (rate).",
    "list_amount": "Published list rate for an account holder, before negotiated discounts (list_rate).",
    "retail_amount": "Retail counter rate with no carrier account (retail_rate).",
}
SHIP_DATE_BASIS = ("Provider default: rated as of the request. Future ship dates are refused because EasyPost does "
                   "not document that rates honor a later date.")
FEES_NOTICE = ("Each package and destination creates one EasyPost shipment for rating. EasyPost's API addendum (v4.3) "
               "includes three rating calls per purchased label and charges $0.02 for each additional call. This workflow "
               "purchases no labels, so unless labels are bought elsewhere on the account, each production rating call "
               "costs $0.02. Test-mode rates are not live carrier quotes; negotiated rates appear only in production mode.")


def _round_up(value, step):
    exact = Decimal(repr(value)).quantize(Decimal("0.000000001"))  # Drop binary noise (10.000000000000002) first.
    return float(exact.quantize(Decimal(step), rounding=ROUND_CEILING))


def parcel_inches(metres):
    """A parcel dimension as EasyPost takes it: inches to one decimal place, rounded up, never smaller."""
    return _round_up(metres / INCH_M, "0.1")


def parcel_ounces(kilograms):
    """A parcel weight in ounces, rounded up at six decimals, so a parcel is never rated lighter."""
    return _round_up(kilograms / OUNCE_KG, "0.000001")


# Provider error codes named in EasyPost's error reference; the error message text is never read.
ERROR_HELP = (
    ("SHIPMENT.RATES.UNAVAILABLE", "No carrier offered a rate for this route and package."),
    ("SHIPMENT.INVALID", "The provider rejected the shipment details. Check addresses, carrier accounts and options."),
    ("PARCEL.PARAMETERS.INVALID", "Check the package dimensions and weight."),
    ("MODE.UNAUTHORIZED", "This key's mode (test or production) does not permit this request."),
    ("PAYMENT_REQUIRED", "The EasyPost account reports that payment setup is required. Funding or enrollment is the account owner's decision; nothing was purchased."),
)


def _provider_error_code(response):
    """Only the provider's error code (for example SHIPMENT.INVALID), never its message."""
    if len(response.content) > MAX_RESPONSE_BYTES:
        return None
    try:
        raw = response.json()
    except ValueError:
        return None
    error = raw.get("error") if isinstance(raw, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_.]{0,63}", code) else None


def _rejection(status, code):
    help_text = next((text for known, text in ERROR_HELP if code == known),
                     "Verify addresses, account access and package eligibility.")
    return f"Carrier service rejected the request (HTTP {status}{', ' + code if code else ''}). {help_text}"


def quote_fingerprint(design_hash, scenario_hash, account_ref):
    return digest({"provider": "EasyPost", "adapter": ADAPTER, "design_hash": design_hash,
                   "scenario_hash": scenario_hash, "account_ref": account_ref})


def _provider_text(value, *, optional=False):
    if not isinstance(value, str) or len(value) > 100 or (not optional and not value.strip()):
        raise ValueError("provider text")
    return value


def _money(value):
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0 or amount > 1000000:
        raise ValueError("amount")
    return amount


def _currency(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError("currency")
    return value


def _rate(r, mode):
    if not isinstance(r, dict):
        raise ValueError("rate")
    amount = _money(r["rate"])
    if r.get("mode", mode) != mode:
        raise ValueError("rate mode")
    currency = _currency(r["currency"])
    days = r.get("delivery_days")
    if days is not None and (type(days) is not int or not 0 <= days <= 365):
        raise ValueError("delivery days")
    out = {"id": _provider_text(r["id"]), "carrier": _provider_text(r["carrier"]), "service": _provider_text(r["service"]),
           "account_id": _provider_text(r.get("carrier_account_id", ""), optional=True), "amount": str(amount),
           "currency": currency, "delivery_days": days, "mode": mode}
    for basis, key in (("list", "list_rate"), ("retail", "retail_rate")):
        value, unit = r.get(key), r.get(f"{basis}_currency")
        # A basis is reported only with its own explicit currency; it is never assumed.
        if value in (None, "") or unit in (None, ""):
            out[f"{basis}_amount"], out[f"{basis}_currency"] = None, None
        else:
            out[f"{basis}_amount"], out[f"{basis}_currency"] = str(_money(value)), _currency(unit)
    billing = r.get("billing_type")
    out["billing_type"] = billing if isinstance(billing, str) and re.fullmatch(r"[a-z_]{1,40}", billing) else None
    date = r.get("delivery_date")
    out["delivery_date"] = date if isinstance(date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}[0-9T:.+\- Z]{0,24}", date) else None
    guaranteed = r.get("delivery_date_guaranteed")
    out["delivery_date_guaranteed"] = guaranteed if type(guaranteed) is bool else None
    return out


def _message(raw):
    """Category only. Carrier free text can echo addresses or diagnostics and is never returned."""
    raw = raw if isinstance(raw, dict) else {}
    text = raw.get("message") if isinstance(raw.get("message"), str) else ""
    category = next((name for name, pattern in MESSAGE_CATEGORIES if pattern.search(text)), "other")
    carrier, account = raw.get("carrier"), raw.get("carrier_account_id")
    return {"carrier": carrier if isinstance(carrier, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}", carrier) else None,
            "carrier_account_id": account if isinstance(account, str) and re.fullmatch(r"ca_[A-Za-z0-9_]{1,64}", account) else None,
            "type": "rate_error" if raw.get("type") == "rate_error" else "other",
            "category": category, "help": MESSAGE_HELP[category]}


def _totals(parcels):
    """Per service, the cheapest account rate in every parcel; other bases only when complete."""
    common, lookup = None, []
    for parcel in parcels:
        by_service = {}
        for r in parcel["rates"]:
            key = (r["carrier"], r["service"], r["account_id"], r["currency"], r["mode"])
            if key not in by_service or Decimal(r["amount"]) < Decimal(by_service[key]["amount"]):
                by_service[key] = r
        lookup.append(by_service)
        common = set(by_service) if common is None else common & set(by_service)
    totals = []
    for key in sorted(common or ()):
        chosen = [p[key] for p in lookup]
        total = {"carrier": key[0], "service": key[1], "account_id": key[2], "currency": key[3], "mode": key[4],
                 "amount": str(sum((Decimal(r["amount"]) for r in chosen), Decimal(0))),
                 "basis": "Sum of separate parcel estimates; not a consolidated shipment quote"}
        for basis in ("list", "retail"):
            parts = [(r[f"{basis}_amount"], r[f"{basis}_currency"]) for r in chosen]
            complete = all(amount is not None and unit == key[3] for amount, unit in parts)
            total[f"{basis}_amount"] = str(sum((Decimal(a) for a, _ in parts), Decimal(0))) if complete else None
        days = [r["delivery_days"] for r in chosen]
        total["delivery_days"] = max(days) if all(d is not None for d in days) else None
        totals.append(total)
    totals.sort(key=lambda r: (r["currency"], Decimal(r["amount"])))
    return totals


def _label(value, limit=80):
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    if (not value or len(value) > limit or any(ord(c) < 32 or ord(c) > 126 for c in value)
            or re.search(r"EZ[AT]K", value, re.I)):
        return None
    return value


def _account(raw):
    """Allowlisted carrier-account fields; credentials, fields, logos and clones are discarded."""
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not re.fullmatch(r"ca_[A-Za-z0-9_]{1,64}", raw["id"]):
        return None
    kind, billing = raw.get("type"), raw.get("billing_type")
    return {"id": raw["id"],
            "type": kind if isinstance(kind, str) and re.fullmatch(r"[A-Za-z0-9]{1,60}", kind) else None,
            "readable": _label(raw.get("readable")), "description": _label(raw.get("description")),
            "reference": _label(raw.get("reference")),
            "billing_type": billing if isinstance(billing, str) and re.fullmatch(r"[a-z_]{1,40}", billing) else None}


TEST_ONLY_CONTENTS = ("This design's contents are a test assumption, so it can be quoted only with a key recorded as a test "
                      "key. No request was sent. Test-mode rates are not clearance to ship any product.")


def mode_mismatch(observed, declared):
    return PackagingError("account_mode_mismatch", f"EasyPost answered in {observed} mode, but this key is recorded as a {declared} "
                          "key. The request that returned this answer was already sent and created one provider shipment; "
                          "that cannot be undone, and a production shipment may be billed. Nothing was saved, no further "
                          "shipments were requested and nothing is retried. Check the key in the EasyPost dashboard, then "
                          "record its mode again or replace the key.", 409)


class EasyPostRating:
    def __init__(self, key=None, *, transport=None, account_ref=None, declared_mode=None):
        """declared_mode: the mode the user recorded for this key. When given, a response in another mode stops
        the quote at that response with no further request or retry. The request that revealed the mismatch was
        already sent; this cannot prevent or undo it. Without a credential store the development environment
        may record the mode in INSPECTORPRO_PACKAGING_EASYPOST_MODE."""
        self._key = key if key is not None else os.environ.get("INSPECTORPRO_PACKAGING_EASYPOST_KEY", "")
        self._transport = transport
        self._lock = asyncio.Lock()
        if account_ref is None and self._key:
            account_ref = account_reference("environment" if key is None else "direct",
                                            hashlib.sha256(self._key.encode()).hexdigest())
        self.account_ref = account_ref if self._key else None
        if declared_mode is None and key is None:
            environment = os.environ.get(MODE_ENVIRONMENT, "")
            declared_mode = environment if environment in ACCOUNT_MODES else None
        if declared_mode not in (None, *ACCOUNT_MODES):
            raise ValueError("declared_mode must be test, production or None")
        self.declared_mode = declared_mode if self._key else None
        self.observed_mode = None  # The mode of the last provider response, for the account record.

    def status(self):
        return {"provider": "EasyPost", "configured": bool(self._key), "purchases_enabled": False,
                "account_ref": self.account_ref, "declared_mode": self.declared_mode, "observed_mode": self.observed_mode,
                "mode_mismatch": bool(self.declared_mode and self.observed_mode and self.declared_mode != self.observed_mode),
                "notice": "Quotes need the key recorded as a test or production key. Each response's mode is checked against "
                          "that record; a mismatch stops further requests but cannot undo the request that revealed it. "
                          "No labels are purchased."}

    def fingerprint(self, assessment, request):
        return quote_fingerprint(assessment["design_hash"], digest(request.scenario()), self.account_ref)

    def _client(self):
        return httpx.AsyncClient(auth=(self._key, ""), timeout=20, transport=self._transport, follow_redirects=False)

    async def quote(self, design, assessment, request, attempt=None):
        """attempt, when given, is updated in place so callers can audit partial provider writes."""
        attempt = {} if attempt is None else attempt
        for key in ("requests_sent", "responses_received", "shipments_created"):
            attempt.setdefault(key, 0)
        try:
            return await asyncio.wait_for(self._quote(design, assessment, request, attempt), timeout=65)
        except TimeoutError as exc:
            raise PackagingError("quote_timeout", "Rating exceeded its time budget. No current quote was saved; some provider requests may already have completed.", 504) from exc

    def preflight(self, design, assessment, request):
        """Every check that can refuse a request before any provider shipment is created."""
        if not self._key:
            raise PackagingError("provider_not_configured", "Carrier credentials are not configured. Local packaging remains available.", 503)
        if not assessment["rate_ready"]:
            raise PackagingError("package_not_rate_ready", "Resolve the validation errors before requesting rates.", 422)
        if design.constraints.contents_basis == "test_assumption" and self.declared_mode != "test":
            # A synthetic parcel is never priced on a key recorded as production (or not recorded at all).
            raise PackagingError("test_assumption_needs_test_key", TEST_ONLY_CONTENTS, 409)
        if request.ship_date is not None:
            raise PackagingError("ship_date_unsupported", "A specific ship date is not supported: EasyPost does not document that rates honor a later date. Leave the ship date empty to rate as of today.", 422)
        origin_notes = check_address(request.origin, "origin")
        notes = [check_address(d, f"destination {i + 1}") for i, d in enumerate(request.destinations)]
        if len(design.packages) * len(request.destinations) > 12:
            raise PackagingError("quote_budget_exceeded", "Quote at most 12 package/destination combinations per request.", 422)
        return origin_notes, notes

    async def _quote(self, design, assessment, request, attempt):
        origin_notes, notes = self.preflight(design, assessment, request)
        if self._lock.locked():
            raise PackagingError("quote_in_progress", "A quote request is already running. Wait before retrying.", 429)
        accounts = list(request.carrier_accounts)
        options = request.options.provider_options()
        services = {(s.carrier, s.service) for s in request.services}
        output, modes = [], set()
        async with self._lock:
            async with self._client() as client:
                for destination, destination_notes in zip(request.destinations, notes):
                    parcels = []
                    for package, mass in zip(design.packages, assessment["packages"]):
                        dims = sorted(package.carton.outer_m, reverse=True)
                        parcel = {"length": parcel_inches(dims[0]), "width": parcel_inches(dims[1]),
                                  "height": parcel_inches(dims[2]), "weight": parcel_ounces(mass["gross_kg"])}
                        shipment = {"from_address": request.origin.model_dump(), "to_address": destination.model_dump(),
                                    "parcel": dict(parcel)}
                        if accounts:
                            shipment["carrier_accounts"] = accounts
                        if options:
                            shipment["options"] = dict(options)
                        try:
                            attempt["requests_sent"] += 1
                            response = await client.post(f"{API}/shipments", json={"shipment": shipment})
                            attempt["responses_received"] += 1
                            if 200 <= response.status_code < 300:
                                attempt["shipments_created"] += 1
                            if response.status_code >= 400:
                                raise PackagingError("carrier_request_failed", _rejection(response.status_code, _provider_error_code(response)), 502)
                            if len(response.content) > MAX_RESPONSE_BYTES:
                                raise PackagingError("carrier_response_invalid", "Carrier response exceeded the permitted size.", 502)
                            raw = response.json()
                            if not isinstance(raw, dict):
                                raise ValueError("shipment")
                            mode = raw.get("mode")
                            if mode not in ("test", "production"):
                                raise ValueError("mode")
                            self.observed_mode = mode
                            if self.declared_mode is not None and mode != self.declared_mode:
                                raise mode_mismatch(mode, self.declared_mode)
                            modes.add(mode)
                            if len(modes) > 1:
                                raise ValueError("mixed modes")
                            raw_rates, messages = raw.get("rates", []), raw.get("messages", [])
                            if not isinstance(raw_rates, list) or len(raw_rates) > 100 or not isinstance(messages, list):
                                raise ValueError("rates")
                            rates, excluded = [], 0
                            for entry in raw_rates:
                                parsed = _rate(entry, mode)
                                if (accounts and parsed["account_id"] not in accounts) or (
                                        services and (parsed["carrier"], parsed["service"]) not in services):
                                    excluded += 1
                                    continue
                                rates.append(parsed)
                            parcels.append({"package_id": package.id, "mode": mode, "rates": rates,
                                            "parcel_sent": {"length_in": parcel["length"], "width_in": parcel["width"],
                                                            "height_in": parcel["height"], "weight_oz": parcel["weight"]},
                                            "excluded_rate_count": excluded, "carrier_error_count": len(messages),
                                            "carrier_messages": [_message(m) for m in messages[:MAX_MESSAGES]],
                                            "provider_id": _provider_text(raw.get("id", ""), optional=True)})
                        except PackagingError:
                            raise
                        except (httpx.HTTPError, ValueError, TypeError, KeyError, InvalidOperation) as exc:
                            raise PackagingError("carrier_unavailable", "Carrier rates could not be verified. No current quote was saved; retry after checking provider access.", 502) from exc
                    output.append({"destination": {"city": destination.city, "state": destination.state, "zip": destination.zip,
                                                   "residential": destination.residential},
                                   "notes": destination_notes, "parcels": parcels, "totals": _totals(parcels)})
        scenario_hash = digest(request.scenario())
        return {"provider": "EasyPost", "adapter": ADAPTER, "quoted_at": now(), "design_hash": assessment["design_hash"],
                "scenario_hash": scenario_hash, "account_ref": self.account_ref, "mode": next(iter(modes), None),
                "fingerprint": quote_fingerprint(assessment["design_hash"], scenario_hash, self.account_ref),
                "request": {"carrier_accounts": sorted(accounts), "services": sorted([c, s] for c, s in services), "options": options},
                "price_bases": PRICE_BASES, "origin_notes": origin_notes, "results": output, "ship_date_basis": SHIP_DATE_BASIS,
                "provider_shipments_created": attempt["shipments_created"], "fees_notice": FEES_NOTICE,
                # What these rates rest on: the weight basis, the contents classification (never sent) and the key mode.
                "weight_basis": weight_basis(design, assessment), "contents": contents_record(design),
                "account_mode": {"declared": self.declared_mode, "observed": next(iter(modes), None)},
                "notice": "Estimates only. Carrier adjustments and API fees may apply. No postage was purchased."}

    async def carrier_accounts(self):
        """Sanitized carrier-account discovery. Production keys only, per EasyPost."""
        if not self._key:
            raise PackagingError("provider_not_configured", "Carrier credentials are not configured. Local packaging remains available.", 503)
        if self.declared_mode == "test":
            raise PackagingError("carrier_discovery_refused", "Carrier-account listing needs a production key, and this key is recorded "
                                 "as a test key, so no request was sent. Without a selection, rates are requested with no account filter.", 403)
        if self._lock.locked():
            raise PackagingError("quote_in_progress", "A provider request is already running. Wait before retrying.", 429)
        async with self._lock:
            try:
                async with self._client() as client:
                    response = await asyncio.wait_for(client.get(f"{API}/carrier_accounts"), timeout=25)
            except TimeoutError as exc:
                raise PackagingError("carrier_unavailable", "Carrier accounts could not be listed in time.", 504) from exc
            except httpx.HTTPError as exc:
                raise PackagingError("carrier_unavailable", "Carrier accounts could not be listed. Check provider access.", 502) from exc
        code = _provider_error_code(response) if response.status_code >= 400 else None
        if response.status_code == 403 or code == "MODE.UNAUTHORIZED":
            raise PackagingError("carrier_discovery_refused", "EasyPost refused to list carrier accounts for this key. Listing needs a production key. Without a selection, rates are requested with no account filter.", 403)
        if response.status_code == 401:
            raise PackagingError("carrier_credentials_invalid", "The carrier key was not accepted.", 502)
        if response.status_code != 200:
            raise PackagingError("carrier_request_failed", f"Carrier account listing failed (HTTP {response.status_code}{', ' + code if code else ''}).", 502)
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise PackagingError("carrier_response_invalid", "Carrier account listing exceeded the permitted size.", 502)
        try:
            raw = response.json()
        except ValueError as exc:
            raise PackagingError("carrier_response_invalid", "Carrier account listing was not valid JSON.", 502) from exc
        if not isinstance(raw, list) or len(raw) > MAX_ACCOUNTS:
            raise PackagingError("carrier_response_invalid", "Carrier account listing had an unexpected shape.", 502)
        accounts = [_account(entry) for entry in raw]
        kept = [a for a in accounts if a is not None]
        return {"provider": "EasyPost", "fetched_at": now(), "account_ref": self.account_ref,
                "carrier_accounts": kept, "skipped_count": len(accounts) - len(kept),
                "notice": "Only account IDs, carrier types, names and billing types are kept. Credential fields in the provider response are discarded and never stored, shown or sent to Sage."}
