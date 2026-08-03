from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

from .model import ScanResult, Usage


FRACTION_BLOCKS = " ▁▂▃▄▅▆▇█"


@dataclass(frozen=True)
class ChartBucket:
    start: date
    end: date
    total_tokens: int
    partial: bool


@dataclass(frozen=True)
class VerticalChart:
    lines: list[str]
    buckets: list[ChartBucket]
    bucket_days: int
    partial: bool
    selected_index: int | None


@dataclass(frozen=True)
class HourChartBucket:
    day: date
    hour: int
    total_tokens: int


@dataclass(frozen=True)
class HourlyVerticalChart:
    lines: list[str]
    buckets: list[HourChartBucket]
    partial: bool
    selected_index: int | None


@dataclass(frozen=True)
class DailySpan:
    start: date
    end: date
    totals: dict[date, int]
    partial: set[date]


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text)


def clip_display(text: str, width: int) -> str:
    if width <= 0:
        return ""
    result: list[str] = []
    used = 0
    for char in text:
        char_width = 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        if used + char_width > width:
            break
        result.append(char)
        used += char_width
    return "".join(result)


def compact_number(value: int, language: str) -> str:
    if language == "en":
        if value >= 1_000_000_000:
            return f"{value / 1_000_000_000:.2f}B"
        if value >= 1_000_000:
            return f"{value / 1_000_000:.2f}M"
        if value >= 1_000:
            return f"{value / 1_000:.2f}K"
        return f"{value:,}"
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f} 亿"
    if value >= 10_000:
        return f"{value / 10_000:.2f} 万"
    return f"{value:,}"


def partial_days(result: ScanResult) -> set[str]:
    partial: set[str] = set()
    if result.window.start is not None:
        start = result.window.start.astimezone(result.window.timezone)
        if start.hour or start.minute or start.second or start.microsecond:
            partial.add(start.date().isoformat())
    end = result.window.end.astimezone(result.window.timezone)
    if end.hour or end.minute or end.second or end.microsecond:
        partial.add(end.date().isoformat())
    return partial


def single_local_day(result: ScanResult) -> date | None:
    if result.window.start is None or result.window.label.startswith("rolling "):
        return None
    start = result.window.start.astimezone(result.window.timezone)
    end = result.window.end.astimezone(result.window.timezone)
    if any((start.hour, start.minute, start.second, start.microsecond)):
        return None
    if any((end.hour, end.minute, end.second, end.microsecond)):
        return None
    if end.date() != start.date() + timedelta(days=1):
        return None
    return start.date()


def _date_bounds(result: ScanResult) -> tuple[date, date] | None:
    if not result.daily:
        return None
    if result.window.start is None:
        return date.fromisoformat(min(result.daily)), date.fromisoformat(max(result.daily))

    start = result.window.start.astimezone(result.window.timezone).date()
    local_end = result.window.end.astimezone(result.window.timezone)
    end = local_end.date() if any(
        (local_end.hour, local_end.minute, local_end.second, local_end.microsecond)
    ) else local_end.date() - timedelta(days=1)
    return start, max(start, end)


def _daily_span(result: ScanResult) -> DailySpan | None:
    bounds = _date_bounds(result)
    if bounds is None:
        return None
    start, end = bounds
    totals = {
        date.fromisoformat(day): usage.total_tokens
        for day, usage in result.daily.items()
        if start <= date.fromisoformat(day) <= end
    }
    partial = {date.fromisoformat(day) for day in partial_days(result)}
    return DailySpan(start=start, end=end, totals=totals, partial=partial)


def _bucket_values(
    span: DailySpan,
    *,
    max_buckets: int,
) -> tuple[list[ChartBucket], int]:
    total_days = (span.end - span.start).days + 1
    bucket_days = max(1, math.ceil(total_days / max(1, max_buckets)))
    bucket_count = math.ceil(total_days / bucket_days)
    totals = [0] * bucket_count
    partial = [False] * bucket_count
    for day, value in span.totals.items():
        totals[(day - span.start).days // bucket_days] += value
    for day in span.partial:
        if span.start <= day <= span.end:
            partial[(day - span.start).days // bucket_days] = True
    buckets = [
        ChartBucket(
            start=span.start + timedelta(days=index * bucket_days),
            end=min(span.end, span.start + timedelta(days=(index + 1) * bucket_days - 1)),
            total_tokens=totals[index],
            partial=partial[index],
        )
        for index in range(bucket_count)
    ]
    return buckets, bucket_days


def _pad_left(text: str, width: int) -> str:
    return " " * max(0, width - display_width(text)) + text


def _bar_slot(glyph: str, column_width: int, *, selected: bool) -> str:
    if glyph == " ":
        return " " * column_width
    if selected:
        glyph = "▓"
    bar_width = 1 if column_width < 3 else min(2, column_width - 1)
    left = (column_width - bar_width) // 2
    right = column_width - bar_width - left
    return " " * left + glyph * bar_width + " " * right


def _date_label(value: date, *, partial: bool, column_width: int) -> str:
    marker = "*" if partial else ""
    if column_width >= 6 or value.day == 1:
        return f"{value.month}/{value.day}{marker}"
    return f"{value.day}{marker}"


def bucket_range_label(bucket: ChartBucket) -> str:
    if bucket.start == bucket.end:
        return bucket.start.isoformat()
    return f"{bucket.start.isoformat()}~{bucket.end.isoformat()}"


def hour_bucket_range_label(bucket: HourChartBucket) -> str:
    end_hour = bucket.hour + 1
    return f"{bucket.day.isoformat()} {bucket.hour:02d}:00~{end_hour:02d}:00"


def _label_axis(buckets: list[ChartBucket], column_width: int) -> str:
    total_width = len(buckets) * column_width
    canvas = [" "] * total_width
    occupied = [False] * total_width
    label_gap = 0
    stride = max(1, math.ceil(5 / column_width))
    indexes = set(range(0, len(buckets), stride))
    indexes.update((0, len(buckets) - 1))
    indexes.update(index for index, bucket in enumerate(buckets) if bucket.start.day == 1)

    for index in sorted(indexes):
        bucket = buckets[index]
        label = _date_label(bucket.start, partial=bucket.partial, column_width=column_width)
        center = index * column_width + column_width // 2
        start = max(0, min(total_width - len(label), center - len(label) // 2))
        end = min(total_width, start + len(label))
        if any(occupied[max(0, start - label_gap) : min(total_width, end + label_gap)]):
            continue
        for position, char in enumerate(label[: end - start], start=start):
            canvas[position] = char
            occupied[position] = True
    return "".join(canvas).rstrip()


def _hour_axis(buckets: list[HourChartBucket], column_width: int) -> str:
    total_width = len(buckets) * column_width
    canvas = [" "] * total_width
    occupied = [False] * total_width
    indexes = {0, 6, 12, 18, len(buckets) - 1}
    if column_width >= 4:
        indexes.update(range(0, len(buckets), 3))

    for index in sorted(indexes):
        label = f"{buckets[index].hour:02d}"
        center = index * column_width + column_width // 2
        start = max(0, min(total_width - len(label), center - len(label) // 2))
        end = min(total_width, start + len(label))
        if any(occupied[max(0, start - 1) : min(total_width, end + 1)]):
            continue
        for position, char in enumerate(label[: end - start], start=start):
            canvas[position] = char
            occupied[position] = True
    return "".join(canvas).rstrip()


def build_daily_vertical_chart(
    result: ScanResult,
    *,
    width: int,
    height: int,
    language: str = "zh",
    selected_index: int | None = None,
) -> VerticalChart | None:
    span = _daily_span(result)
    if span is None or width < 24 or height < 3:
        return None

    provisional_columns = max(1, width - 12)
    buckets, bucket_days = _bucket_values(span, max_buckets=provisional_columns)
    maximum = max((bucket.total_tokens for bucket in buckets), default=0)
    scale_max = max(1, maximum)
    top_label = compact_number(maximum, language)
    middle_label = compact_number(maximum // 2, language)
    axis_width = max(display_width(top_label), display_width(middle_label), 1)
    plot_width = max(1, width - axis_width - 2)

    if len(buckets) > plot_width:
        buckets, bucket_days = _bucket_values(span, max_buckets=plot_width)
        maximum = max((bucket.total_tokens for bucket in buckets), default=0)
        scale_max = max(1, maximum)
        top_label = compact_number(maximum, language)
        middle_label = compact_number(maximum // 2, language)
        axis_width = max(display_width(top_label), display_width(middle_label), 1)
        plot_width = max(1, width - axis_width - 2)

    column_width = max(1, min(6, plot_width // len(buckets)))
    if selected_index is not None:
        if selected_index < 0:
            selected_index = len(buckets) + selected_index
        selected_index = max(0, min(len(buckets) - 1, selected_index))
    units = [
        0
        if bucket.total_tokens == 0
        else max(1, round(bucket.total_tokens / scale_max * height * 8))
        for bucket in buckets
    ]
    if selected_index is not None and units[selected_index] == 0:
        units[selected_index] = 1
    middle_row = height // 2
    lines: list[str] = []
    for row in range(height):
        if row == 0:
            label = top_label
            axis = "┤"
        elif row == middle_row:
            label = middle_label
            axis = "┤"
        else:
            label = ""
            axis = "│"
        row_floor = (height - row - 1) * 8
        slots: list[str] = []
        for index, value in enumerate(units):
            fill = max(0, min(8, value - row_floor))
            slots.append(
                _bar_slot(
                    FRACTION_BLOCKS[fill],
                    column_width,
                    selected=index == selected_index,
                )
            )
        lines.append(f"{_pad_left(label, axis_width)} {axis}{''.join(slots)}")

    plot_line_width = len(buckets) * column_width
    lines.append(f"{_pad_left('0', axis_width)} └{'─' * plot_line_width}")
    lines.append(f"{' ' * (axis_width + 2)}{_label_axis(buckets, column_width)}")
    return VerticalChart(
        lines=lines,
        buckets=buckets,
        bucket_days=bucket_days,
        partial=any(bucket.partial for bucket in buckets),
        selected_index=selected_index,
    )


def build_hourly_vertical_chart(
    result: ScanResult,
    *,
    width: int,
    height: int,
    language: str = "zh",
    selected_index: int | None = None,
) -> HourlyVerticalChart | None:
    selected_day = single_local_day(result)
    if selected_day is None or width < 36 or height < 3:
        return None

    totals = [
        result.hourly.get(f"{selected_day.isoformat()}T{hour:02d}", Usage()).total_tokens
        for hour in range(24)
    ]
    buckets = [
        HourChartBucket(day=selected_day, hour=hour, total_tokens=totals[hour])
        for hour in range(24)
    ]
    local_generated = result.generated_at.astimezone(result.window.timezone)
    in_progress = (
        selected_day == local_generated.date()
        and result.window.start is not None
        and result.window.start <= result.generated_at < result.window.end
    )

    maximum = max(totals, default=0)
    scale_max = max(1, maximum)
    top_label = compact_number(maximum, language)
    middle_label = compact_number(maximum // 2, language)
    axis_width = max(display_width(top_label), display_width(middle_label), 1)
    plot_width = max(1, width - axis_width - 2)
    column_width = max(1, min(4, plot_width // len(buckets)))

    if selected_index is not None:
        if selected_index < 0:
            selected_index = local_generated.hour if in_progress else len(buckets) - 1
        selected_index = max(0, min(len(buckets) - 1, selected_index))

    units = [
        0 if value == 0 else max(1, round(value / scale_max * height * 8))
        for value in totals
    ]
    if selected_index is not None and units[selected_index] == 0:
        units[selected_index] = 1
    middle_row = height // 2
    lines: list[str] = []
    for row in range(height):
        if row == 0:
            label = top_label
            axis = "┤"
        elif row == middle_row:
            label = middle_label
            axis = "┤"
        else:
            label = ""
            axis = "│"
        row_floor = (height - row - 1) * 8
        slots: list[str] = []
        for index, value in enumerate(units):
            fill = max(0, min(8, value - row_floor))
            slots.append(
                _bar_slot(
                    FRACTION_BLOCKS[fill],
                    column_width,
                    selected=index == selected_index,
                )
            )
        lines.append(f"{_pad_left(label, axis_width)} {axis}{''.join(slots)}")

    plot_line_width = len(buckets) * column_width
    lines.append(f"{_pad_left('0', axis_width)} └{'─' * plot_line_width}")
    lines.append(f"{' ' * (axis_width + 2)}{_hour_axis(buckets, column_width)}")
    return HourlyVerticalChart(
        lines=lines,
        buckets=buckets,
        partial=in_progress,
        selected_index=selected_index,
    )
