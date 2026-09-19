"""Provider-neutral generation of untrusted structured continuity summaries."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Protocol, Sequence

from .models import canonical_json
from .repository import MemoryValidationError


SUMMARY_SYSTEM_PROMPT = """You maintain untrusted conversation continuity for an engineering assistant.
Return exactly one JSON object and no prose or Markdown.
Use only the previous summary and incremental conversation turns supplied here.
Never promote an assistant-only engineering value into userClaims.
User claims and continuity decisions have conversation-only authority.
Corrections must preserve audit history by marking replaced claims superseded and
linking them through supersededClaimIds or supersedesClaimId.
Every objective, claim, decision, assumption, correction, and open question must
cite one or more supplied source turn IDs.
Do not invent evidence IDs, entity IDs, approvals, measurements, or requirements.
The required schema is sage-continuity-summary-1.0 with exactly these top-level
keys: schemaVersion, summaryRevision, throughTurnSequence, objective, userClaims,
continuityDecisions, assumptions, corrections, openQuestions,
referencedEntities, sourceEvidenceRefs, warnings."""


class SummaryProviderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SummaryProviderResult:
    summary: Dict[str, Any]
    metadata: Dict[str, Any]


class ContinuitySummaryProvider(Protocol):
    async def generate(
        self,
        *,
        previous_summary: Optional[Mapping[str, Any]],
        turns: Sequence[Mapping[str, Any]],
        stable_scope: Mapping[str, Any],
        expected_summary_revision: int,
        through_turn_sequence: int,
    ) -> SummaryProviderResult:
        ...


@dataclass(frozen=True)
class SummaryProviderConfig:
    provider: str
    model: str
    maximum_output_tokens: int
    request_timeout_seconds: float

    @classmethod
    def from_environment(
        cls,
        environ: Optional[Mapping[str, str]] = None,
        *,
        maximum_output_tokens: int = 1200,
        request_timeout_seconds: float = 5.0,
    ) -> "SummaryProviderConfig":
        values = os.environ if environ is None else environ
        provider = str(
            values.get("INSPECTORPRO_MEMORY_SUMMARY_PROVIDER") or "anthropic"
        ).strip().lower()
        if provider not in {"anthropic", "openai"}:
            raise MemoryValidationError(
                "INSPECTORPRO_MEMORY_SUMMARY_PROVIDER must be anthropic or openai"
            )
        default_model = (
            "claude-haiku-4-5-20251001"
            if provider == "anthropic"
            else "gpt-5-mini"
        )
        model = str(
            values.get("INSPECTORPRO_MEMORY_SUMMARY_MODEL") or default_model
        ).strip()
        if not model:
            raise MemoryValidationError(
                "INSPECTORPRO_MEMORY_SUMMARY_MODEL must not be blank"
            )
        return cls(
            provider=provider,
            model=model,
            maximum_output_tokens=int(maximum_output_tokens),
            request_timeout_seconds=float(request_timeout_seconds),
        )


class ConfiguredContinuitySummaryProvider:
    """One pinned provider/model with no silent fallback."""

    def __init__(self, config: SummaryProviderConfig) -> None:
        self.config = config

    async def generate(
        self,
        *,
        previous_summary: Optional[Mapping[str, Any]],
        turns: Sequence[Mapping[str, Any]],
        stable_scope: Mapping[str, Any],
        expected_summary_revision: int,
        through_turn_sequence: int,
    ) -> SummaryProviderResult:
        request = {
            "expectedSummaryRevision": int(expected_summary_revision),
            "throughTurnSequence": int(through_turn_sequence),
            "stableScope": dict(stable_scope),
            "previousSummary": dict(previous_summary)
            if isinstance(previous_summary, Mapping)
            else None,
            "incrementalTurns": [dict(turn) for turn in turns],
        }
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(self._generate_sync, canonical_json(request)),
                timeout=self.config.request_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise SummaryProviderError(
                "summary_provider_timeout",
                "continuity summary provider exceeded its deadline",
            ) from exc
        except SummaryProviderError:
            raise
        except Exception as exc:
            raise SummaryProviderError(
                "summary_provider_failed",
                "continuity summary provider failed",
            ) from exc
        summary = _parse_json_object(raw)
        return SummaryProviderResult(
            summary=summary,
            metadata={
                "provider": self.config.provider,
                "model": self.config.model,
                "attempts": 1,
                "maximumOutputTokens": self.config.maximum_output_tokens,
                "schemaVersion": "sage-continuity-summary-1.0",
            },
        )

    def _generate_sync(self, request_json: str) -> str:
        if self.config.provider == "anthropic":
            return self._generate_anthropic(request_json)
        return self._generate_openai(request_json)

    def _generate_anthropic(self, request_json: str) -> str:
        try:
            import anthropic
        except ImportError as exc:
            raise SummaryProviderError(
                "summary_provider_unavailable", "Anthropic SDK is unavailable"
            ) from exc
        api_key = str(os.getenv("ANTHROPIC_API_KEY") or "").strip()
        if not api_key:
            raise SummaryProviderError(
                "summary_provider_unavailable", "Anthropic API key is unavailable"
            )
        response = anthropic.Anthropic(api_key=api_key).messages.create(
            model=self.config.model,
            max_tokens=self.config.maximum_output_tokens,
            temperature=0,
            system=SUMMARY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": request_json}],
            timeout=self.config.request_timeout_seconds,
        )
        return "".join(
            str(getattr(block, "text", ""))
            for block in getattr(response, "content", ())
            if getattr(block, "type", "") == "text"
        ).strip()

    def _generate_openai(self, request_json: str) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise SummaryProviderError(
                "summary_provider_unavailable", "OpenAI SDK is unavailable"
            ) from exc
        api_key = str(os.getenv("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise SummaryProviderError(
                "summary_provider_unavailable", "OpenAI API key is unavailable"
            )
        response = OpenAI(api_key=api_key).responses.create(
            model=self.config.model,
            instructions=SUMMARY_SYSTEM_PROMPT,
            input=request_json,
            max_output_tokens=self.config.maximum_output_tokens,
            timeout=self.config.request_timeout_seconds,
        )
        return str(getattr(response, "output_text", "") or "").strip()


def _parse_json_object(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().lower() in {"```", "```json"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SummaryProviderError(
            "summary_invalid_json", "continuity summary is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise SummaryProviderError(
            "summary_invalid_json", "continuity summary must be a JSON object"
        )
    return value


__all__ = [
    "ConfiguredContinuitySummaryProvider",
    "ContinuitySummaryProvider",
    "SUMMARY_SYSTEM_PROMPT",
    "SummaryProviderConfig",
    "SummaryProviderError",
    "SummaryProviderResult",
]
