from __future__ import annotations

import pandas as pd

from training.train_models import add_thermal_proxy_targets


def test_add_thermal_proxy_targets_labels_future_heat_and_cold_severity() -> None:
    frame = pd.DataFrame(
        {
            "station_name": ["test"] * 5,
            "temp_c": [20.0, 25.0, 30.0, -5.0, -15.0],
            "humidex": [20.0, 31.0, 41.0, None, None],
            "wind_chill": [20.0, 25.0, 30.0, -11.0, -31.0],
        }
    )

    result = add_thermal_proxy_targets(frame)

    assert result.loc[0, "proxy_heat_disturbance_24h"] == 3
    assert result.loc[2, "proxy_cold_disturbance_24h"] == 3
