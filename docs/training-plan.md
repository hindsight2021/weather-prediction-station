# Training Plan

## Goal

Train regional models that answer:

- What severe weather class is likely in the next 1 hour?
- What severe weather class is likely in the next 24 hours?

## Regional data sources

Use Canadian data, not Illinois or NWS assumptions.

Recommended starting region:

- New Brunswick
- Nova Scotia
- Prince Edward Island
- Nearby Maine as optional supplemental data only

## Observations

Normalize station data to timestamp, station_id, latitude, longitude, temperature_c, humidity_pct, pressure_hpa, wind_speed_kmh, wind_gust_kmh, and rain_mm.

## Labels

Use ECCC and MSC CAP alerts where possible:

- none
- thunderstorm_watch
- thunderstorm_warning
- rainfall_warning
- wind_warning
- freezing_rain_warning
- snowfall_warning
- winter_storm_warning
- heat_warning
- cold_warning
- fog_advisory
- special_weather_statement

Also generate direct sensor threshold labels:

- heavy_rain_next_1h
- wind_gust_over_70_next_1h
- lightning_within_20km_next_1h
- freezing_next_24h

## First baseline

Before neural nets, train a RandomForestClassifier to verify that the dataset and labels work.

## Neural model target

Later model architecture:

- 48 hours of 5-minute observations
- 7 days of hourly observations
- two parallel 1D convolutional legs
- LSTM pooling
- attention layer
- dropout
- dense layers
- sigmoid or softmax outputs depending on final multi-label design

## Local calibration

Build a local scaler by comparing Atlas data against nearest ECCC station over matching timestamps.

## Convective features (in progress)

Surface obs (temp/pressure/humidity/wind) cannot see atmospheric instability,
which is the primary driver of thunderstorms — this is the biggest ceiling on
storm/lightning skill. As of the `storm-lightning-viability` work:

- **Live path (done):** `EnvironmentalClient._convective` pulls `cape`,
  `convective_inhibition`, and `lifted_index` from the Open-Meteo forecast API
  each cycle. They are logged into every snapshot and feed a convective-
  potential term in the live rule engine (`app/risk_rules._convective_potential`).
- **ML path (pipeline ready, data pending):** the models train on
  `features/transforms.FEATURES` (surface only) plus `CONVECTIVE_FEATURES`
  whenever the dataset actually carries them. `model_feature_columns()` folds
  the convective columns in automatically, `build_inference_row` always
  supplies them, each model bundle records the exact feature set it trained on,
  and the gradient-boosted trees tolerate NaN gaps -- so there is no flag day:
  the day the training data has CAPE, the models use it.
- **Sourcing CAPE for history (open):** the ECCC hourly archive has no CAPE,
  and -- verified 2026-07 -- Open-Meteo's ERA5 **archive**
  (`archive-api.open-meteo.com`) returns *null* CAPE/CIN/LI, so there is no
  drop-in historical backfill from it. The live engine now logs CAPE/CIN/LI
  into every snapshot, so the practical path is to train (or fine-tune) on the
  accumulating `data/weather_snapshots.jsonl` once it spans a convective
  season, or to add a genuine ERA5 CAPE source (Copernicus CDS
  `reanalysis-era5-single-levels`, variable `convective_available_potential_energy`,
  which requires a CDS API key) and join it by station/timestamp.
