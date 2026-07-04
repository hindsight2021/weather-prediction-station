#!/usr/bin/env python3
"""Download NOAA ISD Lite historical weather files for optional augmentation.

NOAA ISD Lite is a fixed-width, hourly-derived product with common observations.
This script filters the ISD station history file to a bounding box and downloads
yearly station files from NOAA's public HTTPS archive.

Example:
    python scripts/download_noaa_isd_lite.py --start-year 1995 --end-year 2025
"""

from __future__ import annotations

import argparse
import gzip
import io
import logging
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


LOGGER = logging.getLogger("download_noaa_isd_lite")

ISD_HISTORY_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"
ISD_LITE_BASE_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-lite"

DEFAULT_OUTPUT_DIR = Path("data/raw/noaa/isd-lite")
DEFAULT_INVENTORY_DIR = Path("data/inventory")
DEFAULT_NAME_PATTERN = (
    r"FREDERICTON|MONCTON|SAINT JOHN|MIRAMICHI|BATHURST|EDMUNDSTON|"
    r"CHARLO|GAGETOWN|WOODSTOCK|GRAND MANAN|ST STEPHEN|YARMOUTH|HALIFAX"
)


@dataclass(frozen=True)
class IsdStation:
    usaf: str
    wban: str
    name: str
    country: str
    latitude: float | None
    longitude: float | None
    begin: int | None
    end: int | None

    @property
    def station_key(self) -> str:
        return f"{self.usaf}-{self.wban}"


def _request_bytes(url: str, timeout: int = 90) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "weather-prediction-station/0.1 historical-data-builder",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _safe_float(text: str) -> float | None:
    value = text.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _safe_yyyymmdd(text: str) -> int | None:
    value = text.strip()
    if not value:
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None


def download_station_history(inventory_dir: Path) -> Path:
    inventory_dir.mkdir(parents=True, exist_ok=True)
    output_path = inventory_dir / "noaa_isd_history.csv"
    output_path.write_bytes(_request_bytes(ISD_HISTORY_URL))
    LOGGER.info("Saved %s", output_path)
    return output_path


def parse_station_history(path: Path) -> list[IsdStation]:
    import csv

    stations: list[IsdStation] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            usaf = row.get("USAF", "").strip()
            wban = row.get("WBAN", "").strip()
            name = row.get("STATION NAME", "").strip()
            country = row.get("CTRY", "").strip()

            if not usaf or not wban or not name:
                continue

            stations.append(
                IsdStation(
                    usaf=usaf,
                    wban=wban,
                    name=name,
                    country=country,
                    latitude=_safe_float(row.get("LAT", "")),
                    longitude=_safe_float(row.get("LON", "")),
                    begin=_safe_yyyymmdd(row.get("BEGIN", "")),
                    end=_safe_yyyymmdd(row.get("END", "")),
                )
            )

    return stations


def filter_stations(
    stations: Iterable[IsdStation],
    start_year: int,
    end_year: int,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    name_pattern: str,
    country: str,
    max_stations: int,
) -> list[IsdStation]:
    compiled = re.compile(name_pattern, flags=re.IGNORECASE)
    selected: list[IsdStation] = []

    for station in stations:
        if country and station.country.upper() != country.upper():
            continue
        if station.latitude is None or station.longitude is None:
            continue
        if not (min_lat <= station.latitude <= max_lat):
            continue
        if not (min_lon <= station.longitude <= max_lon):
            continue
        if station.begin is not None and station.begin > end_year:
            continue
        if station.end is not None and station.end < start_year:
            continue
        if name_pattern and not compiled.search(station.name):
            continue
        selected.append(station)

    selected.sort(key=lambda item: (item.name, item.begin or 9999, item.station_key))
    return selected[:max_stations]


def write_selected_stations(stations: list[IsdStation], output_path: Path) -> None:
    import csv

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "usaf",
                "wban",
                "station_key",
                "name",
                "country",
                "latitude",
                "longitude",
                "begin_year",
                "end_year",
            ],
        )
        writer.writeheader()
        for station in stations:
            writer.writerow(
                {
                    "usaf": station.usaf,
                    "wban": station.wban,
                    "station_key": station.station_key,
                    "name": station.name,
                    "country": station.country,
                    "latitude": station.latitude,
                    "longitude": station.longitude,
                    "begin_year": station.begin,
                    "end_year": station.end,
                }
            )


def download_station_year(station: IsdStation, year: int, output_dir: Path, overwrite: bool) -> bool:
    station_slug = re.sub(r"[^A-Za-z0-9]+", "_", station.name).strip("_").lower()
    station_dir = output_dir / f"{station.station_key}_{station_slug}"
    station_dir.mkdir(parents=True, exist_ok=True)

    output_path = station_dir / f"{station.station_key}-{year}.gz"
    if output_path.exists() and not overwrite:
        return False

    url = f"{ISD_LITE_BASE_URL}/{year}/{station.usaf}-{station.wban}-{year}.gz"

    try:
        content = _request_bytes(url)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            LOGGER.warning("HTTP %s for %s %s", exc.code, station.station_key, year)
        return False
    except urllib.error.URLError as exc:
        LOGGER.warning("Network error for %s %s: %s", station.station_key, year, exc)
        return False

    try:
        with gzip.GzipFile(fileobj=io.BytesIO(content)) as test_file:
            test_file.read(64)
    except Exception:
        LOGGER.warning("Downloaded file did not look like gzip: %s", url)
        return False

    output_path.write_bytes(content)
    LOGGER.info("Saved %s", output_path)
    return True


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=1995)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--inventory-dir", type=Path, default=DEFAULT_INVENTORY_DIR)
    parser.add_argument("--min-lat", type=float, default=44.0)
    parser.add_argument("--max-lat", type=float, default=48.5)
    parser.add_argument("--min-lon", type=float, default=-69.5)
    parser.add_argument("--max-lon", type=float, default=-63.0)
    parser.add_argument("--name-pattern", default=DEFAULT_NAME_PATTERN)
    parser.add_argument("--country", default="CA")
    parser.add_argument("--max-stations", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--inventory-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)

    if args.start_year > args.end_year:
        raise SystemExit("--start-year must be less than or equal to --end-year")

    history_path = download_station_history(args.inventory_dir)
    stations = parse_station_history(history_path)
    selected = filter_stations(
        stations=stations,
        start_year=args.start_year,
        end_year=args.end_year,
        min_lat=args.min_lat,
        max_lat=args.max_lat,
        min_lon=args.min_lon,
        max_lon=args.max_lon,
        name_pattern=args.name_pattern,
        country=args.country,
        max_stations=args.max_stations,
    )

    if not selected:
        raise SystemExit("No NOAA ISD Lite stations matched the requested filters")

    write_selected_stations(selected, args.inventory_dir / "selected_noaa_isd_lite_stations.csv")

    if args.inventory_only:
        return 0

    saved_count = 0
    for station in selected:
        station_start = max(args.start_year, station.begin or args.start_year)
        station_end = min(args.end_year, station.end or args.end_year)
        for year in range(station_start, station_end + 1):
            if download_station_year(station, year, args.output_dir, args.overwrite):
                saved_count += 1
            if args.sleep_seconds > 0:
                time.sleep(args.sleep_seconds)

    LOGGER.info("Saved %d NOAA ISD Lite station-year files", saved_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
