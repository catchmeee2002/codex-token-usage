from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from statistics import median
from typing import Any, Mapping


USAGE_COMPONENT_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)

CUMULATIVE_FIELDS = (*USAGE_COMPONENT_FIELDS, "total_tokens")


def _integer(mapping: Mapping[str, Any], field_name: str) -> int:
    value = mapping.get(field_name, 0)
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


@dataclass
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "Usage":
        return cls(**{name: _integer(mapping, name) for name in USAGE_COMPONENT_FIELDS})

    def validate(self) -> None:
        for name in USAGE_COMPONENT_FIELDS:
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached_input_tokens exceeds input_tokens")
        if self.reasoning_output_tokens > self.output_tokens:
            raise ValueError("reasoning_output_tokens exceeds output_tokens")

    def add(self, other: "Usage") -> None:
        for name in USAGE_COMPONENT_FIELDS:
            setattr(self, name, getattr(self, name) + getattr(other, name))

    @property
    def uncached_input_tokens(self) -> int:
        return self.input_tokens - self.cached_input_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "uncached_input_tokens": self.uncached_input_tokens,
            "cache_write_input_tokens": self.cache_write_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class EffortUsage:
    effort: str
    usage: Usage = field(default_factory=Usage)
    models: set[str] = field(default_factory=set)
    token_events: int = 0
    event_tokens: list[int] = field(default_factory=list)
    turn_tokens: dict[str, int] = field(default_factory=dict)
    turn_seconds: dict[str, float] = field(default_factory=dict)

    def add_event(self, usage: Usage, *, model: str | None, turn_key: str | None) -> None:
        self.usage.add(usage)
        if model:
            self.models.add(model)
        self.token_events += 1
        self.event_tokens.append(usage.total_tokens)
        if turn_key:
            self.turn_tokens[turn_key] = self.turn_tokens.get(turn_key, 0) + usage.total_tokens

    def add_turn_duration(self, turn_key: str, seconds: float) -> None:
        if seconds > 0:
            self.turn_seconds[turn_key] = seconds

    @property
    def turns(self) -> int:
        return len(self.turn_tokens)

    @property
    def model_label(self) -> str:
        if not self.models:
            return "unknown"
        if len(self.models) == 1:
            return next(iter(self.models))
        return "mixed"

    @property
    def median_event_tokens(self) -> int:
        return round(median(self.event_tokens)) if self.event_tokens else 0

    @property
    def median_turn_tokens(self) -> int:
        values = list(self.turn_tokens.values())
        return round(median(values)) if values else 0

    @property
    def worker_hours(self) -> float:
        return sum(self.turn_seconds.values()) / 3600

    @property
    def completed_turn_tokens(self) -> int:
        return sum(self.turn_tokens.get(key, 0) for key in self.turn_seconds)

    @property
    def tokens_per_worker_hour(self) -> float:
        hours = self.worker_hours
        return self.completed_turn_tokens / hours if hours else 0.0

    @property
    def cache_ratio(self) -> float:
        if not self.usage.input_tokens:
            return 0.0
        return self.usage.cached_input_tokens / self.usage.input_tokens

    @property
    def reasoning_ratio(self) -> float:
        if not self.usage.output_tokens:
            return 0.0
        return self.usage.reasoning_output_tokens / self.usage.output_tokens


def cumulative_signature(mapping: Mapping[str, Any]) -> tuple[int, ...]:
    return tuple(_integer(mapping, name) for name in CUMULATIVE_FIELDS)


@dataclass(frozen=True)
class ScanWindow:
    start: datetime | None
    end: datetime
    timezone: tzinfo
    timezone_name: str
    label: str

    def includes(self, timestamp: datetime) -> bool:
        return (self.start is None or timestamp >= self.start) and timestamp < self.end

    def as_dict(self) -> dict[str, str | None]:
        return {
            "label": self.label,
            "start": self.start.isoformat() if self.start else None,
            "end_exclusive": self.end.isoformat(),
            "timezone": self.timezone_name,
        }


@dataclass
class ScanResult:
    generated_at: datetime
    window: ScanWindow
    auth_mode: str | None
    usage: Usage = field(default_factory=Usage)
    by_thread_type: dict[str, Usage] = field(
        default_factory=lambda: {"root": Usage(), "subagent": Usage(), "unknown": Usage()}
    )
    daily: dict[str, Usage] = field(default_factory=dict)
    hourly: dict[str, Usage] = field(default_factory=dict)
    by_effort: dict[str, EffortUsage] = field(default_factory=dict)
    diagnostics: dict[str, int] = field(default_factory=dict)
    warnings: dict[str, int] = field(default_factory=dict)

    def bump_diagnostic(self, code: str, amount: int = 1) -> None:
        self.diagnostics[code] = self.diagnostics.get(code, 0) + amount

    def warn(self, code: str, amount: int = 1) -> None:
        self.warnings[code] = self.warnings.get(code, 0) + amount

    def add_usage(
        self,
        usage: Usage,
        thread_type: str,
        day: str | None,
        hour: str | None = None,
    ) -> None:
        self.usage.add(usage)
        self.by_thread_type.setdefault(thread_type, Usage()).add(usage)
        if day is not None:
            self.daily.setdefault(day, Usage()).add(usage)
        if hour is not None:
            self.hourly.setdefault(hour, Usage()).add(usage)

    def add_effort_usage(
        self,
        usage: Usage,
        *,
        effort: str | None,
        model: str | None,
        turn_key: str | None,
    ) -> None:
        key = effort or "unknown"
        self.by_effort.setdefault(key, EffortUsage(effort=key)).add_event(
            usage,
            model=model,
            turn_key=turn_key,
        )

    def add_effort_turn_duration(
        self,
        *,
        effort: str | None,
        turn_key: str,
        seconds: float,
    ) -> None:
        key = effort or "unknown"
        bucket = self.by_effort.get(key)
        if bucket is not None:
            bucket.add_turn_duration(turn_key, seconds)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "generated_at": self.generated_at.isoformat(),
            "window": self.window.as_dict(),
            "auth": {
                "current_mode": self.auth_mode or "unknown",
                "current_mode_is_api_key": self.auth_mode == "apikey",
                "historical_key_identity_available": False,
            },
            "usage": self.usage.as_dict(),
            "by_thread_type": {
                key: value.as_dict() for key, value in sorted(self.by_thread_type.items())
            },
            "daily": {key: value.as_dict() for key, value in sorted(self.daily.items())},
            "diagnostics": dict(sorted(self.diagnostics.items())),
            "warnings": dict(sorted(self.warnings.items())),
        }
