"""Anthropic API wrapper with per-run token accounting.

Every call goes through LLM.parse() (structured output via pydantic) so usage
is tracked centrally. A run summary is appended to data/usage.jsonl and printed
at the end of each pipeline run — the cost guardrail from the project brief.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

import anthropic
from pydantic import BaseModel

USAGE_LOG = Path("data/usage.jsonl")

# Rough $/MTok (input, output) for cost estimates only — not authoritative.
PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (3.0, 15.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

T = TypeVar("T", bound=BaseModel)


class LLM:
    def __init__(self, model: str) -> None:
        # Resolves credentials from ANTHROPIC_API_KEY / auth profile automatically.
        self.client = anthropic.Anthropic()
        self.model = model
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def parse(
        self,
        *,
        system: str,
        user: str,
        output_format: type[T],
        max_tokens: int = 4096,
    ) -> T:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=output_format,
        )
        self.calls += 1
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens
        if response.parsed_output is None:
            raise RuntimeError(
                f"Model returned no parseable {output_format.__name__} "
                f"(stop_reason={response.stop_reason})"
            )
        return response.parsed_output

    def estimated_cost_usd(self) -> float | None:
        for prefix, (in_price, out_price) in PRICING.items():
            if self.model.startswith(prefix):
                return (
                    self.input_tokens * in_price + self.output_tokens * out_price
                ) / 1_000_000
        return None

    def log_run(self, label: str) -> str:
        cost = self.estimated_cost_usd()
        record = {
            "at": datetime.now(UTC).isoformat(),
            "label": label,
            "model": self.model,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": round(cost, 4) if cost is not None else None,
        }
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_LOG.open("a") as f:
            f.write(json.dumps(record) + "\n")
        cost_str = f"~${cost:.2f}" if cost is not None else "unknown cost"
        return (
            f"LLM usage: {self.calls} calls, {self.input_tokens} in / "
            f"{self.output_tokens} out tokens ({cost_str})"
        )
