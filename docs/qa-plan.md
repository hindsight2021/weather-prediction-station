# QA Plan

This project has three QA layers: unit tests, integration smoke checks, and operational validation inside Home Assistant.

## 1. Unit tests

Run locally:

```bash
python -m compileall app training calibration inference tests
pytest -q
```

Covered now:

- Snapshot time-window feature math
- Pressure delta calculations
- Recent wind and rain maximums
- Quiet-weather scoring
- Severe-weather scoring
- MQTT discovery payload structure
- Prediction state publish payload

## 2. Integration smoke checks

Before deploying to Home Assistant, verify:

- `.env` points to the correct MQTT broker
- `config/weather_brain.yaml` maps to real MQTT topics
- `docker compose up --build` starts without import/config errors
- MQTT discovery topics appear under `homeassistant/sensor/weather_brain/+/config`
- Prediction state appears under `weather_brain/prediction/state`

## 3. Home Assistant validation

After deployment, confirm these entities exist:

- `sensor.weather_brain_storm_risk_1h`
- `sensor.weather_brain_storm_risk_24h`
- `sensor.weather_brain_wind_risk_1h`
- `sensor.weather_brain_rain_risk_1h`
- `sensor.weather_brain_lightning_risk_1h`
- `sensor.weather_brain_confidence`
- `sensor.weather_brain_alert_level`
- `sensor.weather_brain_explanation`

## 4. Data QA checks

Check for these common issues:

- Pressure units are hPa, not inHg
- Wind units are km/h, not mph
- Rain rate is mm/h, not daily total
- Lightning distance is km
- Radar precipitation is numeric, where `0` means no nearby precipitation and positive values mean nearby precipitation
- Missing MQTT values do not crash the service

## 5. ML readiness gates

Do not train a neural model until these are true:

- At least 30 days of clean local snapshots exist
- Regional ECCC/MSC station data loader is working
- CAP alert labeler is working
- Local Atlas-to-ECCC scaler can be generated
- Baseline rule engine is producing sane risk ranges
- False positives and missed events can be labelled

## 6. Release checklist

For each meaningful change:

- Run `pytest -q`
- Run `python -m compileall app training calibration inference tests`
- Confirm Docker image builds
- Confirm README quick start remains accurate
- Confirm no secrets are committed
