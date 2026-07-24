from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, tzinfo
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
    diagnostics: dict[str, int] = field(default_factory=dict)
    warnings: dict[str, int] = field(default_factory=dict)

    def bump_diagnostic(self, code: str, amount: int = 1) -> None:
        self.diagnostics[code] = self.diagnostics.get(code, 0) + amount

    def warn(self, code: str, amount: int = 1) -> None:
        self.warnings[code] = self.warnings.get(code, 0) + amount

    def add_usage(self, usage: Usage, thread_type: str, day: str | None) -> None:
        self.usage.add(usage)
        self.by_thread_type.setdefault(thread_type, Usage()).add(usage)
        if day is not None:
            self.daily.setdefault(day, Usage()).add(usage)

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
