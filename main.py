"""Console MVP for the KorдонPlan border crossing planner."""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

from analytics import (
    average_wait_by_crossing_day_month,
    build_load_profile,
    recommend_trip,
    summarise_dataset,
)
from data_loader import (
    DATA_DIR,
    RESOURCE_PAGES,
    download_archive_resources,
    download_current_resources,
    list_csv_files,
    load_records,
    normalise_direction,
)
from report import (
    REPORTS_DIR,
    create_bar_chart,
    format_average_table,
    format_load_profile,
    format_recommendations,
    format_summary,
    save_csv_table,
    save_text_report,
)


def print_menu() -> None:
    print("\n=== КордонПлан: коли їхати на кордон? ===")
    print("1. Завантажити CSV з data/")
    print("2. Скачати поточні CSV з data.gov.ua")
    print("3. Скачати архівні ревізії CSV")
    print("4. Показати підсумок даних")
    print("5. Середній час: пункт x день x місяць")
    print("6. Рекомендація пункту та оптимального дня")
    print("7. Профіль завантаженості")
    print("8. Зберегти останній звіт")
    print("9. Побудувати PNG-чарт")
    print("0. Вихід")


def read_input(prompt: str) -> str:
    """Read user input and tolerate PowerShell-piped UTF-16 null bytes."""
    return input(prompt).replace("\x00", "").replace("\ufeff", "").strip()


def configure_console() -> None:
    """Use UTF-8 output so crossing names with symbols like >= print safely."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def prompt_direction() -> str | None:
    value = read_input("Напрямок (1 - виїзд, 2 - в'їзд, Enter - усі): ").lower()
    if value == "1":
        return "виїзд"
    if value == "2":
        return "в'їзд"
    return normalise_direction(value) if value else None


def prompt_vehicle_group() -> str | None:
    value = read_input("Тип транспорту (1 - вантажівка, 2 - автобус, Enter - усі): ").lower()
    if value == "1":
        return "вантажівка"
    if value == "2":
        return "автобус"
    if value in {"вантажівка", "автобус"}:
        return value
    return None


def prompt_date() -> date:
    while True:
        value = read_input("Дата поїздки YYYY-MM-DD: ")
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            print("Невірний формат. Приклад: 2026-06-15")


# noinspection PyTypeChecker
def prompt_int(prompt: str, default_value: int, min_value: int, max_value: int) -> int:
    """Prompt for an integer in a bounded range."""
    while True:
        value = read_input(prompt)
        if not value:
            return default_value
        try:
            number = int(value)
        except ValueError:
            print("Невірне число. Введіть ціле значення.")
            continue
        if number < min_value or number > max_value:
            print(f"Діапазон: {min_value}-{max_value}.")
            continue
        return number


def prompt_resource_name() -> str | None:
    value = read_input("Ресурс (queue / busQueue, Enter - queue): ") or "queue"
    if value not in RESOURCE_PAGES:
        print("Невідомий ресурс. Доступні: queue, busQueue.")
        return None
    return value


def ensure_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    if records:
        return records

    csv_files = list_csv_files(DATA_DIR)
    if not csv_files:
        print("У data/ немає CSV. Оберіть пункт 2 або додайте файли вручну.")
        return []

    print("Зчитую CSV з data/ ...")
    loaded = load_records(DATA_DIR)
    print(f"Завантажено записів: {len(loaded)}")
    return loaded


def main() -> None:
    records: list[dict[str, object]] = []
    last_report = ""
    last_average_rows: list[dict[str, object]] = []

    while True:
        print_menu()
        choice = read_input("Ваш вибір: ")

        if choice == "0":
            print("До зустрічі.")
            break

        if choice == "1":
            records = load_records(DATA_DIR)
            last_report = format_summary(summarise_dataset(records))
            print(last_report)

        elif choice == "2":
            print("Скачую поточні CSV. Це може зайняти кілька хвилин.")
            downloaded = download_current_resources(DATA_DIR)
            records = load_records(DATA_DIR)
            last_report = "Завантажено файли:\n" + "\n".join(str(path) for path in downloaded)
            print(last_report)

        elif choice == "3":
            resource = prompt_resource_name()
            if not resource:
                continue
            limit = prompt_int("Скільки архівних ревізій скачати (1-12, Enter - 6): ", 6, 1, 12)
            print("Скачую архівні CSV. Обсяг може бути великим.")
            downloaded = download_archive_resources(resource, DATA_DIR, limit=limit)
            records = load_records(DATA_DIR)
            last_report = "Завантажено архіви:\n" + "\n".join(str(path) for path in downloaded)
            print(last_report)

        elif choice == "4":
            records = ensure_records(records)
            if not records:
                continue
            last_report = format_summary(summarise_dataset(records))
            print(last_report)

        elif choice == "5":
            records = ensure_records(records)
            if not records:
                continue
            direction = prompt_direction()
            vehicle_group = prompt_vehicle_group()
            rows = average_wait_by_crossing_day_month(records, direction=direction, vehicle_group=vehicle_group)
            last_average_rows = rows
            last_report = format_average_table(rows, limit=30)
            print(last_report)
            csv_path = save_csv_table(
                rows,
                REPORTS_DIR / "average_wait_table.csv",
                [
                    "month_name",
                    "weekday_name",
                    "crossing",
                    "avg_wait_hours",
                    "min_wait_hours",
                    "max_wait_hours",
                    "samples",
                ],
            )
            print(f"CSV-таблицю збережено: {csv_path}")

        elif choice == "6":
            records = ensure_records(records)
            if not records:
                continue
            direction = prompt_direction() or "виїзд"
            vehicle_group = prompt_vehicle_group()
            target_date = prompt_date()
            days_ahead = prompt_int("Шукати оптимальний день у наступні N днів (Enter - 7): ", 7, 1, 31)
            recommendations = recommend_trip(
                records,
                direction=direction,
                target_date=target_date,
                vehicle_group=vehicle_group,
                days_ahead=days_ahead,
            )
            last_report = format_recommendations(recommendations)
            print(last_report)

        elif choice == "7":
            records = ensure_records(records)
            if not records:
                continue
            direction = prompt_direction()
            vehicle_group = prompt_vehicle_group()
            crossing = read_input("Назва або частина назви пункту (Enter - усі): ") or None
            profile = build_load_profile(
                records,
                direction=direction,
                crossing_query=crossing,
                vehicle_group=vehicle_group,
            )
            last_report = format_load_profile(profile)
            print(last_report)

        elif choice == "8":
            if not last_report:
                print("Ще немає звіту для збереження.")
                continue
            path = save_text_report(last_report)
            print(f"Звіт збережено: {path}")

        elif choice == "9":
            records = ensure_records(records)
            if not records:
                continue
            if not last_average_rows:
                direction = prompt_direction()
                vehicle_group = prompt_vehicle_group()
                last_average_rows = average_wait_by_crossing_day_month(
                    records,
                    direction=direction,
                    vehicle_group=vehicle_group,
                )
            try:
                path = create_bar_chart(
                    last_average_rows,
                    Path(REPORTS_DIR) / "average_wait_chart.png",
                    "Найбільше середнє очікування за пунктами",
                )
                print(f"Чарт збережено: {path}")
            except RuntimeError as error:
                print(error)

        else:
            print("Невідомий пункт меню.")


if __name__ == "__main__":
    configure_console()
    main()
