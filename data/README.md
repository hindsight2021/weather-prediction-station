# Historical weather data

This directory is intentionally kept light. Do not commit large raw historical downloads.

The ML pipeline pulls public hourly weather observations into:

```text
data/
  raw/
    eccc/hourly/          # Environment and Climate Change Canada monthly CSVs
    noaa/isd-lite/        # Optional NOAA ISD Lite yearly fixed-width files
  inventory/              # downloaded station inventory files
  processed/              # ML-ready CSV outputs
```

## Why the raw data is not committed

Thirty years of hourly observations across multiple Atlantic Canada stations can become large quickly. The repository should keep reproducible code, station filters, metadata, and small samples, while generated raw and processed files stay local.

## Primary source: ECCC hourly climate data

For Kingsclear / Fredericton / New Brunswick training, use Environment and Climate Change Canada hourly climate data first. The downloader uses the public station inventory and ECCC bulk CSV endpoint.

Default bounding box:

```text
lat 44.0 to 48.5
lon -69.5 to -63.0
```

That covers New Brunswick and nearby Atlantic Canada stations useful for regional ML.

## Optional source: NOAA ISD Lite

NOAA ISD Lite is included as a fallback or augmentation source. It is useful for longer regional history and for pressure, temperature, dew point, wind, and precipitation when ECCC coverage is sparse.

## Build commands

```bash
python scripts/download_eccc_hourly.py --start-year 1995 --end-year 2025
python scripts/build_weather_ml_dataset.py
```

Optional NOAA ISD Lite augmentation:

```bash
python scripts/download_noaa_isd_lite.py --start-year 1995 --end-year 2025
```

## Output

The default processed output is:

```text
data/processed/weather_features.csv.gz
```

It contains normalized hourly observations plus model-ready features such as:

- pressure tendency over 1, 3, 6, and 24 hours
- temperature tendency over 1, 3, 6, and 24 hours
- relative humidity tendency
- dew point spread
- rolling precipitation totals
- wind speed changes
- month, day-of-year, and hour cyclic encodings
- proxy severe-weather target columns for bootstrapping model work before official alert labels are wired in

## Alert labels

The first production model should eventually use official ECCC/MSC alert history as labels, not only meteorological proxies. The current pipeline creates proxy labels so model plumbing can be built and tested immediately.
