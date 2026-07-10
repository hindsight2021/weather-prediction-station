# KCR Weather Brain

Local Home Assistant weather intelligence sidecar for Kingsclear-style microclimate prediction.

This project consumes local observations plus Home Assistant hourly forecasts, builds normalized weather snapshots, and publishes separate 1-hour and 24-hour risks with imminent-event warnings. Regional ML models augment—not replace—the forecast and local-station evidence.

## Current scope

This starter repo gives you:

- Dockerized Python service
- MQTT input/output layer
- Configurable topic mapping
- Forecast-driven 1h/6h/24h risk scoring
- Imminent rain/severe-weather ETA and snapshot warnings
- MQTT discovery publishing for Home Assistant
- Training pipeline placeholders for ECCC/MSC regional history
- Local scaler/calibration placeholders
- KNN example store placeholder
- Home Assistant helper/package examples
- GitHub Actions test workflow
- Unit tests for feature windows, risk scoring, and MQTT discovery
- QA plan for local, CI, Home Assistant, and ML-readiness checks

## Architecture

```text
Local station / lightning / barometer observations
        + Home Assistant hourly forecasts
        ↓
KCR Weather Brain Python service
        ↓
Weather snapshot normalization
        ↓
Forecast/rule/ML ensemble
        ↓
Future ML model inference
        ↓
MQTT discovery + state topics
        ↓
Home Assistant sensors, dashboard, automations, feedback helpers
```

## Quick start

1. Copy `.env.example` to `.env`.
2. Edit MQTT host, user, password, and topic names in `config/weather_brain.yaml`.
3. Run:

```bash
docker compose up --build
```

4. Check Home Assistant for MQTT-discovered entities beginning with `sensor.weather_brain_`.

The Home Assistant bridge calls `weather.get_forecasts` for the entities in
`HA_WEATHER_ENTITIES` every 15 minutes and whenever those weather entities update.
Credentials must be supplied through `.env`; the application contains no password defaults.

## QA commands

Run the local QA suite before changing scoring, MQTT discovery, or model plumbing:

```bash
make qa
```

Or run the steps manually:

```bash
python -m compileall app training calibration inference tests
pytest -q
```

See `docs/qa-plan.md` for the broader validation checklist.

## Project phases

### Phase 1: Live rule engine

Use your current MQTT weather feed to publish useful risk sensors immediately.

### Phase 2: Historical dataset

Build a regional New Brunswick and Atlantic Canada dataset from ECCC/MSC station observations and CAP alerts.

### Phase 3: Local calibration

Compare Atlas sensor values against nearest ECCC station over matching timestamps and save a local scaler.

### Phase 4: ML inference

Train 1h and 24h models, load model artifacts locally, and publish probabilities back to Home Assistant.

### Phase 5: KNN feedback learning

Use Home Assistant helpers to label missed events and false positives without retraining the neural net.

## Important design decision

Home Assistant is not the ML runtime. Home Assistant remains the source of truth for entities, history, dashboards, and automations. This service is the local prediction engine beside Home Assistant.
