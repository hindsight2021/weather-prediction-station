from datetime import datetime, timezone

from app.forecast import summarize_hourly_forecasts


def test_forecast_summary_uses_future_windows_without_double_counting_providers():
    now = datetime(2026, 7, 10, 12, 20, tzinfo=timezone.utc)
    response = {
        "weather.a": {"forecast": [
            {"datetime": "2026-07-10T13:00:00Z", "condition": "rainy",
             "precipitation_probability": 90, "precipitation": 3, "wind_gust_speed": 42,
             "temperature": 19},
            {"datetime": "2026-07-10T14:00:00Z", "condition": "lightning-rainy",
             "precipitation_probability": 80, "precipitation": 2, "wind_gust_speed": 70,
             "temperature": 18},
        ]},
        "weather.b": {"forecast": [
            {"datetime": "2026-07-10T13:00:00Z", "condition": "pouring",
             "precipitation_probability": 95, "precipitation": 4, "wind_gust_speed": 35,
             "temperature": 20},
        ]},
    }

    summary = summarize_hourly_forecasts(response, now)

    assert summary["forecast_precip_probability_1h"] == 95
    assert summary["forecast_precip_mm_24h"] == 5
    assert summary["forecast_wind_gust_max_24h"] == 70
    assert summary["forecast_next_precip_minutes"] == 40
    assert summary["forecast_next_severe_minutes"] == 40
    assert summary["forecast_source_count"] == 2
