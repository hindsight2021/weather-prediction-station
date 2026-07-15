#!/usr/bin/env python3
"""Pull real historical hourly climate data for the Fredericton Int'l Airport
station from Environment and Climate Change Canada's MSC GeoMet API and save
it as a raw dataset for feature engineering (see training/build_features.py).

Station: FREDERICTON INTL A, STN_ID=48568, CLIMATE_IDENTIFIER=8101505
(the same station referenced by sensor.fredericton_barometric_pressure and
sensor.fredericton_wind_gust in Home Assistant, so live sensors and training
history are calibrated against the same ground truth).

API docs: https://eccc-msc.github.io/open-data/msc-data/climate_obs/readme_climateobs-datamart_en/
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

LOGGER = logging.getLogger("build_station_dataset")

GEOMET_URL = "https://api.weather.gc.ca/collections/climate-hourly/items"
STATION_ID = 48568
STATION_NAME = "FREDERICTON INTL A"
CLIMATE_IDENTIFIER = "8101505"
LATITUDE = 45.86888888888889
LONGITUDE = -66.53722222222223

DEFAULT_START_YEAR = 2011
DEFAULT_OUTPUT = Path("data/raw/eccc_hourly_fredericton.csv.gz")

REQUIRED_COLUMNS = [
    "timestamp",
    "station_id",
    "latitude",
    "longitude",
    "temperature_c",
    "humidity_pct",
    "pressure_hpa",
    "wind_speed_kmh",
    "wind_gust_kmh",
    "rain_mm",
]


def fetch_month(year: int, month: int, session: requests.Session, retries: int = 3) -> pd.DataFrame:
    params = {
        "STN_ID": STATION_ID,
        "LOCAL_YEAR": year,
        "LOCAL_MONTH": month,
        "f": "json",
        "limit": 900,
    }
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(GEOMET_URL, params=params, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            break
        except (requests.RequestException, ValueError) as exc:
            LOGGER.warning("Fetch failed for %s-%02d (attempt %d/%d): %s", year, month, attempt, retries, exc)
            if attempt == retries:
                return pd.DataFrame()
            time.sleep(2 * attempt)

    rows = [feature["properties"] for feature in payload.get("features", [])]
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=None, help="overrides incremental detection, forces a full refresh from this year")
    parser.add_argument("--start-month", type=int, default=1)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sleep", type=float, default=0.2, help="seconds between requests, be polite to the API")
    args = parser.parse_args(argv)

    existing: pd.DataFrame | None = None
    if args.start_year is not None:
        start_year, start_month = args.start_year, args.start_month
    elif args.output.exists():
        # Incremental refresh: re-fetch from one month before the newest data
        # we already have (ECCC sometimes revises the most recent month), and
        # merge rather than re-downloading the full history every run.
        existing = pd.read_csv(args.output)
        existing["LOCAL_DATE"] = pd.to_datetime(existing["LOCAL_DATE"])
        last_date = existing["LOCAL_DATE"].max()
        overlap = last_date.replace(day=1) - pd.Timedelta(days=1)
        start_year, start_month = overlap.year, overlap.month
        LOGGER.info("Existing dataset found (%d rows, up to %s) — incremental refresh from %d-%02d", len(existing), last_date, start_year, start_month)
    else:
        start_year, start_month = DEFAULT_START_YEAR, 1

    today = date.today()
    months: list[tuple[int, int]] = []
    year, month = start_year, start_month
    while (year, month) <= (today.year, today.month):
        months.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1

    LOGGER.info("Fetching %d months of hourly data for %s (STN_ID=%s)", len(months), STATION_NAME, STATION_ID)

    session = requests.Session()
    frames: list[pd.DataFrame] = []
    for i, (y, m) in enumerate(months, start=1):
        frame = fetch_month(y, m, session)
        if not frame.empty:
            frames.append(frame)
        if i % 12 == 0 or i == len(months):
            LOGGER.info("Progress: %d/%d months fetched (%d rows so far)", i, len(months), sum(len(f) for f in frames))
        time.sleep(args.sleep)

    if not frames:
        LOGGER.error("No data fetched. Aborting without touching existing output.")
        return 1

    fetched = pd.concat(frames, ignore_index=True)
    fetched["LOCAL_DATE"] = pd.to_datetime(fetched["LOCAL_DATE"])

    if existing is not None:
        raw = pd.concat([existing, fetched], ignore_index=True)
    else:
        raw = fetched
    raw = raw.sort_values("LOCAL_DATE").drop_duplicates(subset=["LOCAL_DATE"], keep="last")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw.to_csv(args.output, index=False, compression="gzip")
    LOGGER.info(
        "Wrote %d hourly rows (%s to %s) to %s",
        len(raw),
        raw["LOCAL_DATE"].min(),
        raw["LOCAL_DATE"].max(),
        args.output,
    )
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
