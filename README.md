# KCR Weather Brain

Local Home Assistant weather intelligence sidecar for Kingsclear-style microclimate prediction.

This project is designed to consume weather data that already exists in Home Assistant and MQTT, build normalized weather snapshots, run deterministic risk scoring now, and provide a clean path toward regional ML training with ECCC/MSC data, local Atlas calibration, Monte Carlo uncertainty, and KNN feedback learning.

## Current scope

This starter repo gives you:

- Dockerized Python service
- MQTT input/output layer
- Configurable topic mapping
- Rule-based risk scoring baseline
- MQTT discovery publishing for Home Assistant
- Training pipeline placeholders for ECCC/MSC regional history
- Local scaler/calibration placeholders
- KNN example store placeholder
- Home Assistant helper/package examples
- GitHub Actions lint/test workflow

## Architecture

```text
Atlas / RTL_433 / lightning / barometer / radar MQTT topics
        ↓
KCR Weather Brain Python service
        ↓
Weather snapshot normalization
        ↓
Risk scoring baseline now
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
