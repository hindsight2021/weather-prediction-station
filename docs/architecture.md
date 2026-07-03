# Architecture

KCR Weather Brain is a local sidecar service.

## Runtime flow

MQTT topics from Atlas, RTL_433, lightning, radar, and barometer flow into a Python subscriber, then into normalized snapshots, rule scoring, future ML inference, MQTT discovery, Home Assistant sensors, dashboards, and automations.

## Why this lives outside Home Assistant

Home Assistant remains the source of truth for entities, history, dashboards, and automations. The weather brain handles training jobs, future neural inference, KNN examples, Monte Carlo batches, and dataset building in a separate Python service.

## Future ML layers

1. Regional ECCC and MSC training data
2. ECCC CAP alert labels
3. Regional scaler
4. Kingsclear Atlas local scaler
5. 1h neural model
6. 24h neural model
7. Dropout Monte Carlo uncertainty
8. KNN feedback examples
9. Ratio-vs-none ensemble output
