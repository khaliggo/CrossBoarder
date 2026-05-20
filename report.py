"""Text, CSV and chart reporting helpers."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable


REPORTS_DIR = Path("reports")


def format_hours(hours: float | int | None) -> str:
    """Format decimal hours as hours and minutes."""
    if hours is None:
        return "немає даних"
    minutes = round(float(hours) * 60)
    return f"{minutes // 60} год {minutes % 60:02d} хв"


def format_summary(summary: dict[str, object]) -> str:
    """Format dataset summary for console output."""
    lines = [
        "КордонПлан: підсумок даних",
        f"Записів: {summary.get('records', 0)}",
        f"Пунктів пропуску: {summary.get('crossings', 0)}",
        f"Період: {summary.get('date_from')} - {summary.get('date_to')}",
        f"Напрямки: {', '.join(summary.get('directions', []))}",
        f"Типи транспорту: {', '.join(summary.get('vehicle_groups', []))}",
        f"Файли: {', '.join(summary.get('source_files', []))}",
    ]
    return "\n".join(lines)


def format_recommendations(recommendations: list[dict[str, object]]) -> str:
    """Format trip recommendations."""
    if not recommendations:
        return "Недостатньо даних для рекомендації."

    lines = ["Рекомендовані варіанти:"]
    for index, item in enumerate(recommendations, start=1):
        fallback_note = " (fallback за днем тижня)" if item.get("fallback_used") else ""
        lines.append(
            f"{index}. {item.get('date')} ({item.get('weekday_name')}): "
            f"{item.get('crossing')} - середнє очікування {format_hours(item.get('avg_wait_hours'))}, "
            f"спостережень: {item.get('samples')}{fallback_note}"
        )
    return "\n".join(lines)


def format_average_table(rows: list[dict[str, object]], limit: int = 20) -> str:
    """Format average wait rows."""
    if not rows:
        return "Немає даних для таблиці середнього очікування."

    lines = [
        "Середній час очікування: пункт x день x місяць",
        "Місяць | День | Пункт | Середнє | Спостережень",
    ]
    for row in rows[:limit]:
        lines.append(
            f"{row.get('month_name')} | {row.get('weekday_name')} | {row.get('crossing')} | "
            f"{format_hours(row.get('avg_wait_hours'))} | {row.get('samples')}"
        )
    return "\n".join(lines)


def format_load_profile(profile: dict[str, object]) -> str:
    """Format peak and quiet periods."""
    peak_weekday = profile.get("peak_weekday") or {}
    quiet_weekday = profile.get("quiet_weekday") or {}
    peak_month = profile.get("peak_month") or {}
    quiet_month = profile.get("quiet_month") or {}

    lines = [
        "Профіль завантаженості",
        f"Записів у профілі: {profile.get('records', 0)}",
        f"Піковий день: {peak_weekday.get('name', 'немає даних')} - {format_hours(peak_weekday.get('avg_wait_hours'))}",
        f"Найтихіший день: {quiet_weekday.get('name', 'немає даних')} - {format_hours(quiet_weekday.get('avg_wait_hours'))}",
        f"Піковий місяць: {peak_month.get('name', 'немає даних')} - {format_hours(peak_month.get('avg_wait_hours'))}",
        f"Найтихіший місяць: {quiet_month.get('name', 'немає даних')} - {format_hours(quiet_month.get('avg_wait_hours'))}",
        "",
        "Дні тижня від піку до тихого:",
    ]

    for item in profile.get("weekday_profile", []):
        lines.append(f"- {item.get('name')}: {format_hours(item.get('avg_wait_hours'))}, n={item.get('samples')}")

    return "\n".join(lines)


def save_text_report(content: str, output_dir: Path | str = REPORTS_DIR, prefix: str = "report") -> Path:
    """Save text report with a timestamped filename."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = directory / f"{prefix}_{timestamp}.txt"
    path.write_text(content, encoding="utf-8")
    return path


def save_csv_table(
    rows: Iterable[dict[str, object]],
    output_path: Path | str,
    fieldnames: list[str] | None = None,
) -> Path:
    """Save a list of dictionaries to CSV."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_list = list(rows)
    if not rows_list:
        path.write_text("", encoding="utf-8")
        return path

    selected_fields = fieldnames or list(rows_list[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=selected_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows_list)
    return path


def create_bar_chart(rows: list[dict[str, object]], output_path: Path | str, title: str, top_n: int = 10) -> Path:
    """Create a horizontal bar chart with matplotlib when it is installed."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("Для PNG-чарту встановіть matplotlib: python -m pip install matplotlib") from exc

    chart_rows = sorted(rows, key=lambda item: item.get("avg_wait_hours", 0), reverse=True)[:top_n]
    labels = [str(row.get("crossing"))[:48] for row in chart_rows]
    values = [float(row.get("avg_wait_hours", 0)) for row in chart_rows]

    plt.figure(figsize=(12, max(6, len(chart_rows) * 0.55)))
    plt.barh(labels, values, color="#2f7d6d")
    plt.xlabel("Середнє очікування, год")
    plt.title(title)
    plt.gca().invert_yaxis()
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()
    return path
