from __future__ import annotations

import logging
import pickle
from pathlib import Path

from app.models import WeatherSnapshot

LOGGER = logging.getLogger(__name__)

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

    def predict(self, snapshot: WeatherSnapshot, store) -> dict[str, float | dict[str, object]]:
        """Return binary positive probabilities or multiclass class/probability payloads."""
        if not self.models:
            return {}
            
        # Build feature vector
        try:
            import pandas as pd
            import numpy as np
            import math
            
            timestamp = pd.to_datetime(snapshot.timestamp)
            hour_sin = np.sin(2.0 * math.pi * timestamp.hour / 24.0)
            hour_cos = np.cos(2.0 * math.pi * timestamp.hour / 24.0)
            month_sin = np.sin(2.0 * math.pi * timestamp.month / 12.0)
            month_cos = np.cos(2.0 * math.pi * timestamp.month / 12.0)
            
            row = {
                "temp_c": snapshot.temperature_c,
                "humidex": snapshot.humidex,
                "wind_chill": snapshot.wind_chill_c,
                "dew_point_c": snapshot.temperature_c - (100 - snapshot.humidity_pct)/5 if snapshot.temperature_c and snapshot.humidity_pct else None,
                "rel_hum_pct": snapshot.humidity_pct,
                "wind_speed_kmh": snapshot.wind_speed_kmh,
                "station_pressure_hpa": snapshot.pressure_hpa,
                "dew_point_spread_c": (100 - snapshot.humidity_pct)/5 if snapshot.humidity_pct else None,
                "temp_c_delta_3h": store.temp_delta(3),
                "temp_c_delta_6h": store.temp_delta(6),
                "station_pressure_hpa_delta_3h": store.pressure_delta(3),
                "station_pressure_hpa_delta_6h": store.pressure_delta(6),
                "wind_speed_kmh_rolling_mean_3h": store.wind_speed_mean(3),
                "wind_speed_kmh_rolling_std_3h": store.wind_speed_std(3),
                "hour_sin": hour_sin,
                "hour_cos": hour_cos,
                "month_sin": month_sin,
                "month_cos": month_cos
            }
            
            df = pd.DataFrame([row])
            # If any features are missing, ML fails to predict cleanly, so fillna or abort
            df = df.fillna(0.0) # naive impute
            
            results = {}
            for name, model in self.models.items():
                features = self.model_features.get(name, [])
                probs = model.predict_proba(df[features])
                classes = list(model.classes_)
                if self.model_kinds.get(name) != "multiclass" and len(classes) <= 2:
                    positive_index = classes.index(1) if 1 in classes else len(classes) - 1
                    results[name] = float(probs[0][positive_index])
                else:
                    best_index = int(np.argmax(probs[0]))
                    results[name] = {
                        "class": int(classes[best_index]),
                        "probability": float(probs[0][best_index]),
                        "probabilities": {str(int(cls)): float(probs[0][idx]) for idx, cls in enumerate(classes)},
                    }
            return results
        except Exception as e:
            LOGGER.error(f"ML inference failed: {e}")
            return {}
