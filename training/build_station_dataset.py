from __future__ import annotations

from pathlib import Path

import pandas as pd


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


def validate_dataset(df: pd.DataFrame) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def main() -> None:
    output = Path("data/training/station_dataset.csv")
    output.parent.mkdir(parents=True, exist_ok=True)
    empty = pd.DataFrame(columns=REQUIRED_COLUMNS)
    empty.to_csv(output, index=False)
    print(f"Wrote starter dataset file to {output}")


if __name__ == "__main__":
    main()
