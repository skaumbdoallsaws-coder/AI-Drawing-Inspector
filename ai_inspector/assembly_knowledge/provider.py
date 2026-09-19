"""Narrow multimodal provider adapters for assembly enrichment.

Each ``invoke`` call performs exactly one provider request. Retry and schema
correction policy lives in the bounded enrichment orchestrator, where every
attempt can be counted against the approved request plan.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Protocol


class EnrichmentProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ):
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class MultimodalEnrichmentProvider(Protocol):
    provider_name: str
    model: str

    def invoke(self, request: Mapping[str, Any]) -> Dict[str, Any]:
        """Perform one provider request and return output + normalized usage."""


def _verified_image_payload(image: Mapping[str, Any]) -> tuple[str, str]:
    path = Path(str(image.get("absolutePath", "")))
    if not path.is_file():
        raise EnrichmentProviderError(
            "image_missing",
            f"Approved image is missing: {path}",
        )
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != image.get("assetHash"):
        raise EnrichmentProviderError(
            "image_hash_mismatch",
            f"Approved image changed before submission: {path.name}",
        )
    suffix = path.suffix.lower()
    media_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix)
    if media_type is None:
        raise EnrichmentProviderError(
            "unsupported_image_type",
            f"Unsupported enrichment image type: {suffix}",
        )
    return media_type, base64.b64encode(payload).decode("ascii")


def _classify_provider_exception(provider: str, exc: Exception) -> EnrichmentProviderError:
    name = type(exc).__name__
    lower = name.lower()
    retryable = any(
        token in lower
        for token in ("timeout", "connection", "ratelimit", "internalserver")
    )
    return EnrichmentProviderError(
        f"{provider}_{'transient' if retryable else 'request'}_error",
        f"{provider} enrichment request failed ({name}): {str(exc)[:500]}",
        retryable=retryable,
    )


class FixtureMultimodalProvider:
    """Deterministic test provider; it never accesses a network."""

    provider_name = "fixture"

    def __init__(
        self,
        responses: list[Any],
        *,
        model: str = "fixture-model-v1",
        errors: list[Exception | None] | None = None,
    ):
        self.model = model
        self._responses = list(responses)
        self._errors = list(errors or [])
        self.calls: list[Dict[str, Any]] = []

    def invoke(self, request: Mapping[str, Any]) -> Dict[str, Any]:
        self.calls.append(dict(request))
        call_index = len(self.calls) - 1
        if call_index < len(self._errors) and self._errors[call_index] is not None:
            error = self._errors[call_index]
            if isinstance(error, EnrichmentProviderError):
                raise error
            raise EnrichmentProviderError(
                "fixture_error",
                str(error),
                retryable=False,
            )
        if call_index >= len(self._responses):
            raise EnrichmentProviderError(
                "fixture_response_exhausted",
                "No fixture response remains.",
            )
        value = self._responses[call_index]
        return {
            "output": value,
            "usage": {
                "inputTokens": 100,
                "outputTokens": 50,
                "totalTokens": 150,
            },
            "providerResponseId": f"fixture-response-{call_index + 1}",
        }


class OpenAIMultimodalProvider:
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 90.0,
        client: Any = None,
    ):
        if not api_key:
            raise EnrichmentProviderError(
                "provider_key_missing",
                "OPENAI_API_KEY is required for OpenAI enrichment.",
            )
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, timeout=timeout_seconds)
        self.client = client
        self.model = model
        self.timeout_seconds = timeout_seconds

    def invoke(self, request: Mapping[str, Any]) -> Dict[str, Any]:
        content: list[Dict[str, Any]] = [
            {"type": "input_text", "text": str(request["userText"])}
        ]
        for image in request.get("images", []):
            media_type, encoded = _verified_image_payload(image)
            content.append(
                {
                    "type": "input_image",
                    "detail": "high",
                    "image_url": f"data:{media_type};base64,{encoded}",
                }
            )
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=str(request["systemPrompt"]),
                input=[{"role": "user", "content": content}],
                max_output_tokens=int(request["maximumOutputTokens"]),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "assembly_knowledge_enrichment",
                        "strict": True,
                        "schema": request["outputSchema"],
                    }
                },
                prompt_cache_key=str(request["cacheKey"]),
                store=False,
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            raise _classify_provider_exception("openai", exc) from exc
        raw = getattr(response, "output_text", None)
        if not isinstance(raw, str) or not raw.strip():
            raise EnrichmentProviderError(
                "openai_empty_output",
                "OpenAI returned no structured enrichment output.",
            )
        try:
            output = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EnrichmentProviderError(
                "openai_invalid_json",
                "OpenAI returned invalid enrichment JSON.",
            ) from exc
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        return {
            "output": output,
            "usage": {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "totalTokens": int(
                    getattr(usage, "total_tokens", input_tokens + output_tokens)
                    or input_tokens + output_tokens
                ),
            },
            "providerResponseId": str(getattr(response, "id", "") or ""),
        }


class AnthropicMultimodalProvider:
    provider_name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 90.0,
        client: Any = None,
    ):
        if not api_key:
            raise EnrichmentProviderError(
                "provider_key_missing",
                "ANTHROPIC_API_KEY is required for Anthropic enrichment.",
            )
        if client is None:
            import anthropic

            client = anthropic.Anthropic(
                api_key=api_key,
                timeout=timeout_seconds,
            )
        self.client = client
        self.model = model
        self.timeout_seconds = timeout_seconds

    def invoke(self, request: Mapping[str, Any]) -> Dict[str, Any]:
        content: list[Dict[str, Any]] = [
            {"type": "text", "text": str(request["userText"])}
        ]
        for image in request.get("images", []):
            media_type, encoded = _verified_image_payload(image)
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": encoded,
                    },
                }
            )
        try:
            response = self.client.messages.create(
                model=self.model,
                system=str(request["systemPrompt"]),
                messages=[{"role": "user", "content": content}],
                max_tokens=int(request["maximumOutputTokens"]),
                tools=[
                    {
                        "name": "submit_assembly_enrichment",
                        "description": (
                            "Submit the complete bounded assembly-enrichment "
                            "candidate object."
                        ),
                        "input_schema": request["outputSchema"],
                    }
                ],
                tool_choice={
                    "type": "tool",
                    "name": "submit_assembly_enrichment",
                },
                temperature=0,
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            raise _classify_provider_exception("anthropic", exc) from exc
        output = None
        for block in getattr(response, "content", []):
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_assembly_enrichment"
            ):
                output = getattr(block, "input", None)
                break
        if not isinstance(output, dict):
            raise EnrichmentProviderError(
                "anthropic_missing_tool_output",
                "Anthropic returned no structured enrichment tool input.",
            )
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        return {
            "output": output,
            "usage": {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "totalTokens": input_tokens + output_tokens,
            },
            "providerResponseId": str(getattr(response, "id", "") or ""),
        }
