"""Analytical functions for KorдонPlan border queue recommendations."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Iterable


WEEKDAYS_UA = (
    "Понеділок",
    "Вівторок",
    "Середа",
    "Четвер",
    "П'ятниця",
    "Субота",
    "Неділя",
)

MONTHS_UA = (
    "",
    "січень",
    "лютий",
    "березень",
    "квітень",
    "травень",
    "червень",
    "липень",
    "серпень",
    "вересень",
    "жовтень",
    "листопад",
    "грудень",
)


def calculate_wait_hours(record: dict[str, object]) -> float | None:
    """Calculate queue waiting time as createdDateTime -> exitDateTime."""
    start = record.get("created_at")
    finish = record.get("exit_at") or record.get("entry_at")

    if not isinstance(start, datetime) or not isinstance(finish, datetime):
        return None
    if finish < start:
        return None
    if record.get("direction") == "скасовано" or record.get("cancelled_at"):
        return None

    return (finish - start).total_seconds() / 3600


def enrich_wait_times(records: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    """Return records that have a valid wait_hours value."""
    enriched: list[dict[str, object]] = []
    for record in records:
        wait_hours = calculate_wait_hours(record)
        if wait_hours is None:
            continue
        enriched_record = dict(record)
        enriched_record["wait_hours"] = wait_hours
        enriched.append(enriched_record)
    return enriched


def deduplicate_records(records: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    """Remove duplicate queue rows by UID and source file."""
    seen: set[tuple[str, str]] = set()
    unique_records: list[dict[str, object]] = []

    for record in records:
        uid = str(record.get("uid") or "")
        source_file = str(record.get("source_file") or "")
        key = (uid, source_file)
        if key in seen:
            continue
        seen.add(key)
        unique_records.append(record)

    return unique_records


def filter_records(
    records: Iterable[dict[str, object]],
    direction: str | None = None,
    crossing_query: str | None = None,
    vehicle_group: str | None = None,
    month: int | None = None,
    weekday: int | None = None,
) -> list[dict[str, object]]:
    """Filter records by direction, crossing text, vehicle group, month or weekday."""
    filtered: list[dict[str, object]] = []
    direction_value = direction.lower().strip() if direction else None
    crossing_value = crossing_query.lower().strip() if crossing_query else None
    vehicle_value = vehicle_group.lower().strip() if vehicle_group else None

    for record in records:
        created_at = record.get("created_at")
        if direction_value and str(record.get("direction", "")).lower() != direction_value:
            continue
        if crossing_value and crossing_value not in str(record.get("crossing", "")).lower():
            continue
        if vehicle_value and str(record.get("vehicle_group", "")).lower() != vehicle_value:
            continue
        if month and (not isinstance(created_at, datetime) or created_at.month != month):
            continue
        if weekday is not None and (not isinstance(created_at, datetime) or created_at.weekday() != weekday):
            continue
        filtered.append(record)

    return filtered


def summarise_dataset(records: Iterable[dict[str, object]]) -> dict[str, object]:
    """Return high-level dataset statistics."""
    records_list = list(records)
    crossings = {str(record.get("crossing")) for record in records_list if record.get("crossing")}
    directions = {str(record.get("direction")) for record in records_list if record.get("direction")}
    vehicle_groups = {str(record.get("vehicle_group")) for record in records_list if record.get("vehicle_group")}
    source_files = {str(record.get("source_file")) for record in records_list if record.get("source_file")}

    earliest: datetime | None = None
    latest: datetime | None = None
    for record in records_list:
        created_at = record.get("created_at")
        if not isinstance(created_at, datetime):
            continue
        if earliest is None or created_at < earliest:
            earliest = created_at
        if latest is None or created_at > latest:
            latest = created_at

    return {
        "records": len(records_list),
        "crossings": len(crossings),
        "directions": sorted(directions),
        "vehicle_groups": sorted(vehicle_groups),
        "source_files": sorted(source_files),
        "date_from": earliest.date() if earliest else None,
        "date_to": latest.date() if latest else None,
    }


def average_wait_by_crossing_day_month(
    records: Iterable[dict[str, object]],
    direction: str | None = None,
    vehicle_group: str | None = None,
) -> list[dict[str, object]]:
    """Calculate average wait for crossing x weekday x month."""
    working_records = filter_records(enrich_wait_times(records), direction=direction, vehicle_group=vehicle_group)
    groups: dict[tuple[str, int, int], list[float]] = defaultdict(list)

    for record in working_records:
        created_at = record.get("created_at")
        wait_hours = record.get("wait_hours")
        if not isinstance(created_at, datetime) or not isinstance(wait_hours, (int, float)):
            continue
        key = (str(record.get("crossing")), created_at.weekday(), created_at.month)
        groups[key].append(float(wait_hours))

    rows: list[dict[str, object]] = []
    for (crossing, weekday, month), waits in groups.items():
        rows.append(
            {
                "crossing": crossing,
                "weekday": weekday,
                "weekday_name": WEEKDAYS_UA[weekday],
                "month": month,
                "month_name": MONTHS_UA[month],
                "avg_wait_hours": mean(waits),
                "min_wait_hours": min(waits),
                "max_wait_hours": max(waits),
                "samples": len(waits),
            }
        )

    return sorted(rows, key=lambda item: (item["month"], item["weekday"], item["avg_wait_hours"]))


def rank_crossings(
    records: Iterable[dict[str, object]],
    direction: str | None = None,
    vehicle_group: str | None = None,
    month: int | None = None,
    weekday: int | None = None,
    min_samples: int = 5,
) -> list[dict[str, object]]:
    """Rank border crossings from fastest to slowest."""
    working_records = filter_records(
        enrich_wait_times(records),
        direction=direction,
        vehicle_group=vehicle_group,
        month=month,
        weekday=weekday,
    )
    groups: dict[str, list[float]] = defaultdict(list)

    for record in working_records:
        wait_hours = record.get("wait_hours")
        if isinstance(wait_hours, (int, float)):
            groups[str(record.get("crossing"))].append(float(wait_hours))

    rows: list[dict[str, object]] = []
    for crossing, waits in groups.items():
        if len(waits) < min_samples:
            continue
        rows.append(
            {
                "crossing": crossing,
                "avg_wait_hours": mean(waits),
                "samples": len(waits),
                "min_wait_hours": min(waits),
                "max_wait_hours": max(waits),
            }
        )

    return sorted(rows, key=lambda item: (item["avg_wait_hours"], -item["samples"]))


def recommend_trip(
    records: Iterable[dict[str, object]],
    direction: str,
    target_date: date,
    vehicle_group: str | None = None,
    days_ahead: int = 7,
    min_samples: int = 5,
) -> list[dict[str, object]]:
    """Recommend crossing and day for a requested direction and date."""
    recommendations: list[dict[str, object]] = []

    for offset in range(max(days_ahead, 1)):
        candidate_date = target_date + timedelta(days=offset)
        ranked = rank_crossings(
            records,
            direction=direction,
            vehicle_group=vehicle_group,
            month=candidate_date.month,
            weekday=candidate_date.weekday(),
            min_samples=min_samples,
        )

        fallback_used = False
        if not ranked:
            ranked = rank_crossings(
                records,
                direction=direction,
                vehicle_group=vehicle_group,
                weekday=candidate_date.weekday(),
                min_samples=max(1, min_samples // 2),
            )
            fallback_used = True

        if not ranked:
            continue

        best = dict(ranked[0])
        best["date"] = candidate_date
        best["weekday_name"] = WEEKDAYS_UA[candidate_date.weekday()]
        best["fallback_used"] = fallback_used
        recommendations.append(best)

    return sorted(recommendations, key=lambda item: (item["avg_wait_hours"], item["date"]))[:5]


def build_load_profile(
    records: Iterable[dict[str, object]],
    direction: str | None = None,
    crossing_query: str | None = None,
    vehicle_group: str | None = None,
) -> dict[str, object]:
    """Build peak and quiet periods for selected records."""
    working_records = filter_records(
        enrich_wait_times(records),
        direction=direction,
        crossing_query=crossing_query,
        vehicle_group=vehicle_group,
    )
    by_weekday: dict[int, list[float]] = defaultdict(list)
    by_month: dict[int, list[float]] = defaultdict(list)

    for record in working_records:
        created_at = record.get("created_at")
        wait_hours = record.get("wait_hours")
        if not isinstance(created_at, datetime) or not isinstance(wait_hours, (int, float)):
            continue
        by_weekday[created_at.weekday()].append(float(wait_hours))
        by_month[created_at.month].append(float(wait_hours))

    weekday_rows = [
        {"name": WEEKDAYS_UA[index], "avg_wait_hours": mean(waits), "samples": len(waits)}
        for index, waits in by_weekday.items()
        if waits
    ]
    month_rows = [
        {"name": MONTHS_UA[index], "avg_wait_hours": mean(waits), "samples": len(waits)}
        for index, waits in by_month.items()
        if waits
    ]

    return {
        "records": len(working_records),
        "weekday_profile": sorted(weekday_rows, key=lambda item: item["avg_wait_hours"], reverse=True),
        "month_profile": sorted(month_rows, key=lambda item: item["avg_wait_hours"], reverse=True),
        "peak_weekday": max(weekday_rows, key=lambda item: item["avg_wait_hours"]) if weekday_rows else None,
        "quiet_weekday": min(weekday_rows, key=lambda item: item["avg_wait_hours"]) if weekday_rows else None,
        "peak_month": max(month_rows, key=lambda item: item["avg_wait_hours"]) if month_rows else None,
        "quiet_month": min(month_rows, key=lambda item: item["avg_wait_hours"]) if month_rows else None,
    }
