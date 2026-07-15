# Releasing to the Pi and Home Assistant

Every step is a plain, human-readable command (roadmap guardrail: no opaque
encoded deployment steps). Current release: Phase 0 (verification harness) +
Phase 1 (correctness fixes), merged to `main`.

## 1. On the Pi (CodexPi)

```bash
cd ~/weather-prediction-station        # or wherever the repo is cloned
git pull origin main
docker compose up -d --build
```

This rebuilds and restarts three services:

| Service | What it does |
|---|---|
| `weather-brain` | prediction engine; now also logs every prediction to `data/predictions.jsonl` |
| `ha-bridge` | HA websocket -> MQTT bridge (unchanged) |
| `verifier` | **new** — hourly: polls ECCC CAP alerts, scores predictions, writes `data/verification/scoreboard.{json,md}`, publishes to `weather_brain/verification/#` |

Optional `.env` additions (defaults shown):

```bash
ECCC_CAP_AREA_MATCH=Fredericton   # CAP areaDesc substring(s), comma-separated
ECCC_CAP_OFFICES=CWHX             # Atlantic Storm Prediction Centre
VERIFY_INTERVAL_SECONDS=3600
```

Check it worked:

```bash
docker compose ps
docker compose logs verifier --tail 20
tail -1 data/predictions.jsonl
```

## 2. In Home Assistant

The feedback helpers changed from one label dropdown to per-hazard controls
(hazard + verdict + severity), so the package files must be re-copied:

1. Copy `home-assistant/packages/weather_brain_helpers.yaml` and
   `home-assistant/packages/weather_brain_automations.yaml` into your HA
   `config/packages/` directory.
2. Copy `home-assistant/dashboards/weather_brain_dashboard.yaml` over the old
   dashboard (adds the new feedback controls).
3. Restart Home Assistant (or reload automations + helpers).

Validation checklist:

- `sensor.weather_brain_*` entities still update after the restart.
- New helpers exist: `input_select.weather_brain_feedback_hazard`,
  `input_select.weather_brain_feedback_verdict`,
  `input_select.weather_brain_feedback_severity`.
- Submitting feedback publishes to `ha_bridge/feedback/weather_brain` with
  `hazard` and `severity` fields (check MQTT explorer).
- After the first verifier cycle, `weather_brain/verification/#` topics appear.

## 3. What changes in behavior

- Heat risk no longer over-fires: humidex 34–35 publishes ~36–40
  ("elevated"), not 65+. Score >= 65 now means the ECCC warning criterion
  (humidex >= 36) is met or imminent.
- If a sensor feed dies and there is no 24h history to impute from, ML models
  are skipped and confidence is capped at 60 instead of feeding the model
  zeros.
- Feedback from HA now trains only the hazard you name.

## 4. The scoreboard clock starts now

Per the roadmap, the accuracy baseline requires **~14 days of live logging**.
After that, on the Pi:

```bash
docker compose exec weather-brain python -m verification.report
cat data/verification/scoreboard.md
```

No accuracy claim is valid before that scoreboard exists. Phase 2 (real ECCC
alert labels for training) should not start until the baseline row is
recorded.
