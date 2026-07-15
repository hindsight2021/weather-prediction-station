#!/usr/bin/env python3
"""SUPERSEDED / UNUSED (2026-07-05): never actually run in production (no data
under data/raw/eccc/ ever existed). The live pipeline is now
training/build_station_dataset.py, which pulls the same station's hourly history
from ECCC's MSC GeoMet JSON API (station 48568, Fredericton Int'l Airport)
instead of scraping the legacy bulk_data_e.html CSV endpoint this script targets.
Kept for reference only; safe to delete once confirmed unneeded.

Original docstring below.

Download hourly Environment and Climate Change Canada historical weather data.

This script discovers candidate stations from the public ECCC station inventory,
filters them to the New Brunswick / Atlantic Canada region by default, and downloads
monthly hourly CSV files from the ECCC bulk climate endpoint.

It intentionally stores raw source CSVs without modifying them. Normalization and
feature engineering happen in scripts/build_weather_ml_dataset.py.

Example:
    python scripts/download_eccc_hourly.py --start-year 1995 --end-year 2025
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


LOGGER = logging.getLogger("download_eccc_hourly")

STATION_INVENTORY_URL = (
    "https://collaboration.cmc.ec.gc.ca/cmc/climate/"
    "Get_More_Data_Plus_de_donnees/Station%20Inventory%20EN.csv"
)

ECCC_BULK_URL = "https://climate.weather.gc.ca/climate_data/bulk_data_e.html"

DEFAULT_OUTPUT_DIR = Path("data/raw/eccc/hourly")
DEFAULT_INVENTORY_DIR = Path("data/inventory")

DEFAULT_NAME_PATTERN = (
    r"FREDERICTON|MONCTON|SAINT JOHN|ST JOHN|MIRAMICHI|BATHURST|EDMUNDSTON|"
    r"CHARLO|GAGETOWN|WOODSTOCK|GRAND MANAN|ST STEPHEN|POINT LEPREAU|"
    r"CHATHAM|BOUCTOUCHE|SUSSEX|MCADAM"
)


@dataclass(frozen=True)
class Station:
    station_id: str
    name: str
    climate_id: str
    latitude: float | None
    longitude: float | None
    first_year: int | None
    last_year: int | None


def _request_text(url: str, timeout: int = 60) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "weather-prediction-station/0.1 historical-data-builder",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _safe_int(value: object) -> int | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _safe_float(value: object) -> float | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def download_station_inventory(inventory_dir: Path) -> Path:
    inventory_dir.mkdir(parents=True, exist_ok=True)
    inventory_path = inventory_dir / "eccc_station_inventory_en.csv"

    LOGGER.info("Downloading ECCC station inventory")
    text = _request_text(STATION_INVENTORY_URL)
    inventory_path.write_text(text, encoding="utf-8")
    return inventory_path


def _first_existing_column(frame: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    normalized = {str(column).strip().lower(): column for column in frame.columns}
    for candidate in candidates:
        column = normalized.get(candidate.lower())
        if column is not None:
            return str(column)
    return None


def load_stations(inventory_path: Path) -> list[Station]:
    frame = pd.read_csv(inventory_path, skiprows=3)

    station_id_col = _first_existing_column(frame, ["Station ID", "StationID"])
    name_col = _first_existing_column(frame, ["Name", "Station Name"])
    climate_id_col = _first_existing_column(frame, ["Climate ID", "ClimateID"])
    lat_col = _first_existing_column(frame, ["Latitude (Decimal Degrees)", "Latitude"])
    lon_col = _first_existing_column(frame, ["Longitude (Decimal Degrees)", "Longitude"])
    first_year_col = _first_existing_column(frame, ["HLY First Year", "Hourly First Year"])
    last_year_col = _first_existing_column(frame, ["HLY Last Year", "Hourly Last Year"])

    required = {
        "Station ID": station_id_col,
        "Name": name_col,
    }
    missing = [name for name, column in required.items() if column is None]
    if missing:
        raise RuntimeError(f"Station inventory is missing required columns: {missing}")

    stations: list[Station] = []
    for _, row in frame.iterrows():
        station_id = str(row[station_id_col]).strip()
        name = str(row[name_col]).strip()

        if not station_id or station_id.lower() == "nan" or not name or name.lower() == "nan":
            continue

        stations.append(
            Station(
                station_id=station_id,
                name=name,
                climate_id=str(row[climate_id_col]).strip() if climate_id_col else "",
                latitude=_safe_float(row[lat_col]) if lat_col else None,
                longitude=_safe_float(row[lon_col]) if lon_col else None,
                first_year=_safe_int(row[first_year_col]) if first_year_col else None,
                last_year=_safe_int(row[last_year_col]) if last_year_col else None,
            )
        )

    return stations


def filter_stations(
    stations: Iterable[Station],
    start_year: int,
    end_year: int,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    name_pattern: str,
    max_stations: int,
) -> list[Station]:
    compiled = re.compile(name_pattern, flags=re.IGNORECASE)
    selected: list[Station] = []

    for station in stations:
        if station.latitude is None or station.longitude is None:
            continue
        if not (min_lat <= station.latitude <= max_lat):
            continue
        if not (min_lon <= station.longitude <= max_lon):
            continue
        if station.first_year is not None and station.first_year > end_year:
            continue
        if station.last_year is not None and station.last_year < start_year:
            continue
        if name_pattern and not compiled.search(station.name):
            continue
        selected.append(station)

    selected.sort(
        key=lambda item: (
            item.name,
            item.first_year if item.first_year is not None else 9999,
            item.station_id,
        )
    )
    return selected[:max_stations]


def build_bulk_url(station_id: str, year: int, month: int) -> str:
    query = {
        "format": "csv",
        "stationID": station_id,
        "Year": str(year),
        "Month": str(month),
        "Day": "14",
        "timeframe": "1",
        "submit": "Download Data",
    }
    return f"{ECCC_BULK_URL}?{urllib.parse.urlencode(query)}"


def looks_like_hourly_csv(text: str) -> bool:
    if not text.strip():
        return False
    head = text[:2000].lower()
    return "date/time" in head or "date/time (lst)" in head or "date/time (local" in head


def download_month(station: Station, year: int, month: int, output_dir: Path, overwrite: bool) -> bool:
    station_slug = re.sub(r"[^A-Za-z0-9]+", "_", station.name).strip("_").lower()
    station_dir = output_dir / f"{station.station_id}_{station_slug}"
    station_dir.mkdir(parents=True, exist_ok=True)
    output_path = station_dir / f"{station.station_id}_{year}_{month:02d}.csv"

    if output_path.exists() and not overwrite:
        return False

    url = build_bulk_url(station.station_id, year, month)

    try:
        text = _request_text(url)
    except urllib.error.HTTPError as exc:
        LOGGER.warning("HTTP %s for %s %04d-%02d", exc.code, station.name, year, month)
        return False
    except urllib.error.URLError as exc:
        LOGGER.warning("Network error for %s %04d-%02d: %s", station.name, year, month, exc)
        return False

    if not looks_like_hourly_csv(text):
        LOGGER.info("No hourly CSV returned for %s %04d-%02d", station.name, year, month)
        return False

    output_path.write_text(text, encoding="utf-8")
    LOGGER.info("Saved %s", output_path)
    return True


def write_selected_stations(stations: list[Station], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        [
            {
                "station_id": station.station_id,
                "name": station.name,
                "climate_id": station.climate_id,
                "latitude": station.latitude,
                "longitude": station.longitude,
                "hly_first_year": station.first_year,
                "hly_last_year": station.last_year,
            }
            for station in stations
        ]
    )
    frame.to_csv(output_path, index=False)


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
    parser.add_argument("--max-stations", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=0.25)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="Download inventory and selected station list without monthly climate files.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)

    if args.start_year > args.end_year:
        raise SystemExit("--start-year must be less than or equal to --end-year")

    inventory_path = download_station_inventory(args.inventory_dir)
    stations = load_stations(inventory_path)
    selected = filter_stations(
        stations=stations,
        start_year=args.start_year,
        end_year=args.end_year,
        min_lat=args.min_lat,
        max_lat=args.max_lat,
        min_lon=args.min_lon,
        max_lon=args.max_lon,
        name_pattern=args.name_pattern,
        max_stations=args.max_stations,
    )

    if not selected:
        raise SystemExit("No ECCC hourly stations matched the requested filters")

    selected_path = args.inventory_dir / "selected_eccc_hourly_stations.csv"
    write_selected_stations(selected, selected_path)
    LOGGER.info("Selected %d stations. See %s", len(selected), selected_path)

    if args.inventory_only:
        return 0

    saved_count = 0
    for station in selected:
        station_start = max(args.start_year, station.first_year or args.start_year)
        station_end = min(args.end_year, station.last_year or args.end_year)

        for year in range(station_start, station_end + 1):
            for month in range(1, 13):
                if download_month(station, year, month, args.output_dir, args.overwrite):
                    saved_count += 1
                if args.sleep_seconds > 0:
                    time.sleep(args.sleep_seconds)

    LOGGER.info("Saved %d monthly ECCC hourly files", saved_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
