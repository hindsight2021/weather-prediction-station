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
