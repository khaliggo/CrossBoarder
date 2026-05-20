"""Loading and normalising eQueue border crossing CSV files."""

from __future__ import annotations

import csv
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Iterable


DATA_DIR = Path("data")
DATASET_PAGE_URL = "https://data.gov.ua/dataset/a8909a08-4da6-49c5-9238-6ab227059c51"

RESOURCE_URLS = {
    "queue": "https://data.gov.ua/dataset/7dbe77fe-99a6-4e97-9193-c723945b549c/resource/15c33f10-7f90-4ddb-a2a9-f6162267c7ba/download/queues.csv",
    "busQueue": "https://data.gov.ua/dataset/7dbe77fe-99a6-4e97-9193-c723945b549c/resource/81168c27-7ab4-4881-8224-2af920d8ef7e/download/busqueue.csv",
}

RESOURCE_PAGES = {
    "queue": "https://data.gov.ua/dataset/a8909a08-4da6-49c5-9238-6ab227059c51/resource/15c33f10-7f90-4ddb-a2a9-f6162267c7ba",
    "busQueue": "https://data.gov.ua/dataset/a8909a08-4da6-49c5-9238-6ab227059c51/resource/81168c27-7ab4-4881-8224-2af920d8ef7e",
}

DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def list_csv_files(data_dir: Path | str = DATA_DIR) -> list[Path]:
    """Return CSV files from the data directory sorted by name."""
    directory = Path(data_dir)
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob("*.csv") if path.is_file())


def parse_datetime(value: str | None) -> datetime | None:
    """Parse datetimes used by the data.gov.ua CSV files."""
    if value is None:
        return None

    clean_value = value.strip().strip('"')
    if clean_value.upper() in {"", "NULL", "NONE", "N/A"}:
        return None

    for date_format in DATETIME_FORMATS:
        try:
            return datetime.strptime(clean_value, date_format)
        except ValueError:
            continue
    return None


def normalise_direction(status: str | None) -> str:
    """Convert source statuses into compact direction labels."""
    if not status:
        return "невідомо"

    value = status.strip().lower().replace("`", "'").replace("’", "'")
    if value.startswith("виїзд"):
        return "виїзд"
    if value.startswith("в'їзд") or value.startswith("вїзд"):
        return "в'їзд"
    if "контрол" in value:
        return "на контролі"
    if "скас" in value:
        return "скасовано"
    if "підтвердж" in value:
        return "підтверджено"
    return status.strip().lower()


def detect_vehicle_group(path: Path, row: dict[str, str]) -> str:
    """Detect whether a record describes trucks or buses."""
    file_name = path.name.lower()
    if "bus" in file_name or "автобус" in (row.get("vehicleType") or "").lower():
        return "автобус"
    return "вантажівка"


def normalise_row(row: dict[str, str], source_file: Path) -> dict[str, object]:
    """Map different CSV schemas to the internal record format."""
    crossing = (row.get("crossingName") or "").strip()
    status = (row.get("status") or "").strip()
    created_at = parse_datetime(row.get("createdDateTime"))
    exit_at = parse_datetime(row.get("exitDateTime"))

    return {
        "uid": (row.get("uid") or "").strip(),
        "crossing": crossing,
        "status": status,
        "direction": normalise_direction(status),
        "queue_type": (row.get("type") or "").strip(),
        "vehicle_group": detect_vehicle_group(source_file, row),
        "vehicle_type": (row.get("vehicleBodyType") or row.get("vehicleType") or "").strip(),
        "created_at": created_at,
        "approved_at": parse_datetime(row.get("aprovedDateTime")),
        "permit_at": parse_datetime(row.get("permitDateTime")),
        "entry_at": parse_datetime(row.get("entryDateTime")),
        "exit_at": exit_at,
        "cancelled_at": parse_datetime(row.get("cancellationDateTime")),
        "source_file": source_file.name,
    }


def read_queue_csv(path: Path | str) -> list[dict[str, object]]:
    """Read one queue CSV and return normalised records."""
    csv_path = Path(path)
    records: list[dict[str, object]] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            record = normalise_row(row, csv_path)
            if record["crossing"] and record["created_at"]:
                records.append(record)

    return records


def load_records(
    data_dir: Path | str = DATA_DIR,
    months: int | None = None,
    file_paths: Iterable[Path | str] | None = None,
) -> list[dict[str, object]]:
    """Load records from all CSV files or from explicitly provided paths."""
    paths = [Path(path) for path in file_paths] if file_paths else list_csv_files(data_dir)
    records: list[dict[str, object]] = []

    for path in paths:
        records.extend(read_queue_csv(path))

    if months:
        records = keep_last_months(records, months)

    return records


def keep_last_months(records: list[dict[str, object]], months: int) -> list[dict[str, object]]:
    """Keep records whose created date is within the latest N calendar months."""
    valid_dates = [record["created_at"] for record in records if isinstance(record.get("created_at"), datetime)]
    if not valid_dates:
        return records

    latest = max(valid_dates)
    latest_month_index = latest.year * 12 + latest.month
    earliest_month_index = latest_month_index - max(months, 1) + 1

    filtered: list[dict[str, object]] = []
    for record in records:
        created_at = record.get("created_at")
        if not isinstance(created_at, datetime):
            continue
        record_month_index = created_at.year * 12 + created_at.month
        if record_month_index >= earliest_month_index:
            filtered.append(record)

    return filtered


def download_file(url: str, destination: Path | str) -> Path:
    """Download a CSV file from data.gov.ua."""
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, destination_path)
    return destination_path


def download_current_resources(data_dir: Path | str = DATA_DIR) -> list[Path]:
    """Download current truck and bus CSV resources."""
    directory = Path(data_dir)
    downloaded: list[Path] = []

    for resource_name, url in RESOURCE_URLS.items():
        filename = "queue.csv" if resource_name == "queue" else "busQueue.csv"
        downloaded.append(download_file(url, directory / filename))

    return downloaded


def discover_revision_downloads(resource_page_url: str, limit: int = 6) -> list[str]:
    """Find revision download URLs from a data.gov.ua resource page."""
    with urllib.request.urlopen(resource_page_url, timeout=30) as response:
        html = response.read().decode("utf-8", errors="ignore")

    matches = re.findall(r'href="([^"]+/revision/\d+/download)"', html)
    urls: list[str] = []
    for match in matches:
        url = match if match.startswith("http") else f"https://data.gov.ua{match}"
        if url not in urls:
            urls.append(url)

    return urls[:limit]


def download_archive_resources(
    resource_name: str,
    data_dir: Path | str = DATA_DIR,
    limit: int = 6,
) -> list[Path]:
    """Download latest revision CSV files for one resource."""
    if resource_name not in RESOURCE_PAGES:
        raise ValueError(f"Unknown resource: {resource_name}")

    directory = Path(data_dir)
    downloaded: list[Path] = []
    revision_urls = discover_revision_downloads(RESOURCE_PAGES[resource_name], limit=limit)

    for index, url in enumerate(revision_urls, start=1):
        revision_id = re.search(r"/revision/(\d+)/download", url)
        suffix = revision_id.group(1) if revision_id else str(index)
        path = directory / f"{resource_name}_archive_{suffix}.csv"
        downloaded.append(download_file(url, path))

    return downloaded
