from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass, field
from pathlib import Path

from app.models import WeatherSnapshot
from features.transforms import DELTA_FEATURES, LEVEL_FEATURES, build_inference_row, magnus_dew_point

LOGGER = logging.getLogger(__name__)

# Snapshot fields backing each level feature, used for rolling-median
# imputation from recent history (roadmap §4.4: never impute levels with 0).
LEVEL_FEATURE_SNAPSHOT_FIELD = {
    "temp_c": "temperature_c",
    "rel_hum_pct": "humidity_pct",
    "wind_speed_kmh": "wind_speed_kmh",
    "station_pressure_hpa": "pressure_hpa",
}

IMPUTE_WINDOW_HOURS = 24.0


@dataclass
class MLPredictionResult:
    probabilities: dict[str, float | dict[str, object]] = field(default_factory=dict)
    # True when one or more models were skipped because a level feature had
    # no live value and no recent history to impute from.
    degraded: bool = False
    skipped_models: list[str] = field(default_factory=list)


class MLPredictor:
    def __init__(self, models_dir: Path = Path("models")):
        self.models_dir = models_dir
        self.models = {}
        self.model_features = {}
        self.model_kinds = {}
        self._load_models()

    def _load_models(self):
        if not self.models_dir.exists():
            return

        for pkl_file in self.models_dir.glob("*.pkl"):
            try:
                with pkl_file.open("rb") as f:
                    data = pickle.load(f)
                    name = pkl_file.stem
                    self.models[name] = data["model"]
                    self.model_features[name] = data["features"]
                    self.model_kinds[name] = data.get("kind", "binary")
                LOGGER.info(f"Loaded ML model: {name}")
            except Exception as e:
                LOGGER.warning(f"Failed to load model {pkl_file}: {e}")

    def _impute_levels(self, row: dict[str, float | None], store) -> dict[str, float | None]:
        """Fill missing level features with the rolling 24h median; recompute
        the dew-point derivations if their inputs were imputed."""
        imputed = dict(row)
        for feature_name, snapshot_field in LEVEL_FEATURE_SNAPSHOT_FIELD.items():
            if imputed.get(feature_name) is None:
                imputed[feature_name] = store.field_median(snapshot_field, IMPUTE_WINDOW_HOURS)
        if imputed.get("dew_point_c") is None:
            imputed["dew_point_c"] = magnus_dew_point(
                imputed.get("temp_c"), imputed.get("rel_hum_pct")
            )
        if imputed.get("dew_point_spread_c") is None and imputed.get("dew_point_c") is not None:
            imputed["dew_point_spread_c"] = imputed["temp_c"] - imputed["dew_point_c"]
        return imputed

    def predict(self, snapshot: WeatherSnapshot, store) -> MLPredictionResult:
        """Run every loadable model whose inputs are trustworthy.

        Level features (pressure, temperature, ...) are imputed with the
        rolling 24h median from the snapshot store; if one is still missing,
        the models needing it are skipped and the result is flagged degraded
        instead of feeding the model an impossible 0.0. Delta/rolling features
        default to 0 (no recent change).
        """
        result = MLPredictionResult()
        if not self.models:
            return result

        try:
            import numpy as np
            import pandas as pd

            row = self._impute_levels(build_inference_row(snapshot, store), store)
            for feature_name in DELTA_FEATURES:
                if row.get(feature_name) is None:
                    row[feature_name] = 0.0
            frame = pd.DataFrame([row])

            for name, model in self.models.items():
                features = self.model_features.get(name, [])
                missing_levels = [
                    feature
                    for feature in features
                    if feature in LEVEL_FEATURES and row.get(feature) is None
                ]
                if missing_levels:
                    result.degraded = True
                    result.skipped_models.append(name)
                    LOGGER.warning(
                        "Skipping model %s: no live value or 24h history for %s",
                        name,
                        ", ".join(missing_levels),
                    )
                    continue
                probs = model.predict_proba(frame[features])
                classes = list(model.classes_)
                if self.model_kinds.get(name) != "multiclass" and len(classes) <= 2:
                    positive_index = classes.index(1) if 1 in classes else len(classes) - 1
                    result.probabilities[name] = float(probs[0][positive_index])
                else:
                    best_index = int(np.argmax(probs[0]))
                    result.probabilities[name] = {
                        "class": int(classes[best_index]),
                        "probability": float(probs[0][best_index]),
                        "probabilities": {
                            str(int(cls)): float(probs[0][idx]) for idx, cls in enumerate(classes)
                        },
                    }
            return result
        except Exception as e:
            LOGGER.error(f"ML inference failed: {e}")
            return MLPredictionResult(degraded=bool(self.models))
