"""Quote-only EasyPost adapter. There is deliberately no purchase endpoint."""
from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation
import os
import re
import httpx

from .geometry import digest
from .service import PackagingError, now


def _provider_text(value, *, optional=False):
    if not isinstance(value, str) or len(value) > 100 or (not optional and not value.strip()):
        raise ValueError("provider text")
    return value


class EasyPostRating:
    def __init__(self, key=None, *, transport=None):
        self._key = key if key is not None else os.environ.get("INSPECTORPRO_PACKAGING_EASYPOST_KEY", "")
        self._transport = transport
        self._lock = asyncio.Lock()

    def status(self):
        return {"provider": "EasyPost", "configured": bool(self._key), "purchases_enabled": False,
                "notice": "Quotes use the configured account. Test/live mode comes from each provider response. No labels are purchased."}

    async def quote(self, design, assessment, request):
        try:
            return await asyncio.wait_for(self._quote(design, assessment, request), timeout=65)
        except TimeoutError as exc:
            raise PackagingError("quote_timeout", "Rating exceeded its time budget. No current quote was saved; some provider requests may already have completed.", 504) from exc

    async def _quote(self, design, assessment, request):
        if not self._key:
            raise PackagingError("provider_not_configured", "Carrier credentials are not configured. Local packaging remains available.", 503)
        if not assessment["rate_ready"]:
            raise PackagingError("package_not_rate_ready", "Resolve the validation errors before requesting rates.", 422)
        if len(design.packages) * len(request.destinations) > 12:
            raise PackagingError("quote_budget_exceeded", "Quote at most 12 package/destination combinations per request.", 422)
        if self._lock.locked():
            raise PackagingError("quote_in_progress", "A quote request is already running. Wait before retrying.", 429)
        output = []
        async with self._lock:
            async with httpx.AsyncClient(auth=(self._key, ""), timeout=20, transport=self._transport, follow_redirects=False) as client:
                for destination in request.destinations:
                    parcels = []
                    for package, mass in zip(design.packages, assessment["packages"]):
                        dims = sorted(package.carton.outer_m, reverse=True)
                        body = {"shipment": {"from_address": request.origin.model_dump(), "to_address": destination.model_dump(),
                            "parcel": {"length": round(dims[0] / .0254, 6), "width": round(dims[1] / .0254, 6),
                                       "height": round(dims[2] / .0254, 6), "weight": round(mass["gross_kg"] / .028349523125, 6)}}}
                        try:
                            response = await client.post("https://api.easypost.com/v2/shipments", json=body)
                            if response.status_code >= 400:
                                raise PackagingError("carrier_request_failed", f"Carrier service rejected the request (HTTP {response.status_code}). Verify addresses, account access and package eligibility.", 502)
                            if len(response.content) > 1000000:
                                raise PackagingError("carrier_response_invalid", "Carrier response exceeded the permitted size.", 502)
                            raw = response.json()
                            if not isinstance(raw, dict):
                                raise ValueError("shipment")
                            mode = raw.get("mode")
                            if mode not in ("test", "production"):
                                raise ValueError("mode")
                            rates = []
                            raw_rates, messages = raw.get("rates", []), raw.get("messages", [])
                            if not isinstance(raw_rates, list) or len(raw_rates) > 100 or not isinstance(messages, list):
                                raise ValueError("rates")
                            for r in raw_rates:
                                if not isinstance(r, dict):
                                    raise ValueError("rate")
                                amount = Decimal(str(r["rate"]))
                                if not amount.is_finite() or amount < 0 or amount > 1000000 or r.get("mode", mode) != mode:
                                    raise ValueError("rate")
                                currency = r["currency"]
                                if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
                                    raise ValueError("currency")
                                days = r.get("delivery_days")
                                if days is not None and (type(days) is not int or not 0 <= days <= 365):
                                    raise ValueError("delivery days")
                                rates.append({"id": _provider_text(r["id"]), "carrier": _provider_text(r["carrier"]), "service": _provider_text(r["service"]),
                                              "account_id": _provider_text(r.get("carrier_account_id", ""), optional=True), "amount": str(amount), "currency": currency,
                                              "delivery_days": days, "mode": mode})
                            parcels.append({"package_id": package.id, "mode": mode, "rates": rates,
                                            "carrier_error_count": len(messages), "provider_id": _provider_text(raw.get("id", ""), optional=True)})
                        except PackagingError:
                            raise
                        except (httpx.HTTPError, ValueError, TypeError, KeyError, InvalidOperation) as exc:
                            raise PackagingError("carrier_unavailable", "Carrier rates could not be verified. No current quote was saved; retry after checking provider access.", 502) from exc
                    common = None
                    lookup = []
                    for parcel in parcels:
                        by_service = {}
                        for r in parcel["rates"]:
                            key = (r["carrier"], r["service"], r["account_id"], r["currency"], r["mode"])
                            if key not in by_service or Decimal(r["amount"]) < Decimal(by_service[key]["amount"]):
                                by_service[key] = r
                        lookup.append(by_service)
                        common = set(by_service) if common is None else common & set(by_service)
                    totals = [{"carrier": k[0], "service": k[1], "account_id": k[2], "currency": k[3], "mode": k[4],
                               "amount": str(sum((Decimal(p[k]["amount"]) for p in lookup), Decimal(0))),
                               "basis": "Sum of separate parcel estimates; not a consolidated shipment quote"} for k in sorted(common or ())]
                    totals.sort(key=lambda r: (r["currency"], Decimal(r["amount"])))
                    output.append({"destination": {"city": destination.city, "state": destination.state, "zip": destination.zip}, "parcels": parcels, "totals": totals})
        return {"provider": "EasyPost", "quoted_at": now(), "design_hash": assessment["design_hash"],
                "scenario_hash": digest(request), "results": output, "ship_date_basis": "Provider default; future-date rating not supported in this pilot",
                "notice": "Estimates only. Carrier adjustments and API fees may apply. No postage was purchased."}
