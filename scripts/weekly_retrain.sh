#!/usr/bin/env bash
# Weekly refresh of the ECCC training dataset and model retraining.
# Runs via cron (see crontab -l). Safe to run manually too:
#   ./scripts/weekly_retrain.sh
#
# Retraining is validation-gated (training/train_models.py): a new model
# only replaces the live one if it does not score worse on held-out data,
# so this is safe to run unattended.
set -euo pipefail

PROJECT_DIR="/home/pi/weather-prediction-station"
VENV="$PROJECT_DIR/.venv/bin"
LOG_FILE="$PROJECT_DIR/data/weekly_retrain.log"

cd "$PROJECT_DIR"
echo "=== Weekly retrain started: $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> "$LOG_FILE"

if "$VENV/python" -m training.build_station_dataset >> "$LOG_FILE" 2>&1; then
    echo "Dataset refresh OK" >> "$LOG_FILE"
else
    echo "Dataset refresh FAILED — aborting retrain, keeping existing models" >> "$LOG_FILE"
    exit 1
fi

if "$VENV/python" -m training.build_features >> "$LOG_FILE" 2>&1; then
    echo "Feature build OK" >> "$LOG_FILE"
else
    echo "Feature build FAILED — aborting retrain, keeping existing models" >> "$LOG_FILE"
    exit 1
fi

if "$VENV/python" -m training.train_models >> "$LOG_FILE" 2>&1; then
    echo "Training run OK" >> "$LOG_FILE"
else
    echo "Training run FAILED — keeping existing models" >> "$LOG_FILE"
    exit 1
fi

# Reload the running service so any promoted models take effect immediately.
docker restart kcr-weather-brain >> "$LOG_FILE" 2>&1

echo "=== Weekly retrain finished: $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> "$LOG_FILE"
