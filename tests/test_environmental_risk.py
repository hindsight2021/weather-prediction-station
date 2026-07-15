from app.feature_builder import SnapshotStore
from app.models import WeatherSnapshot
from app.risk_rules import score_weather


def test_official_watch_is_never_low():
    snapshot = WeatherSnapshot(official_alert_severity=2, official_alert_count=1)
    store = SnapshotStore(maxlen=10)
    store.add(snapshot)
    prediction = score_weather(snapshot, store, {})
    assert prediction.level == "watch"
    assert prediction.storm_risk_1h >= 70
    assert prediction.storm_risk_24h >= 75


def test_official_warning_is_warning():
    snapshot = WeatherSnapshot(official_alert_severity=3)
    store = SnapshotStore(maxlen=10)
    store.add(snapshot)
    prediction = score_weather(snapshot, store, {})
    assert prediction.level == "warning"
    assert prediction.storm_risk_1h >= 90


def test_heat_outlook_does_not_restate_current_heat():
    snapshot = WeatherSnapshot(humidex=36, forecast_temp_max_24h=36)
    store = SnapshotStore(maxlen=10)
    store.add(snapshot)
    prediction = score_weather(snapshot, store, {})
    assert prediction.heat_risk_24h <= 25
    assert prediction.heat_severity == "ongoing"


def test_aqhi_and_fire_outputs():
    snapshot = WeatherSnapshot(aqhi_current=4, aqhi_forecast_max_24h=8, active_fires_nearby=3, nb_burn_category=1)
    store = SnapshotStore(maxlen=10)
    store.add(snapshot)
    prediction = score_weather(snapshot, store, {})
    assert prediction.air_quality_risk_24h == 80
    assert prediction.smoke_risk_24h == 24
    assert prediction.nb_burn_status == "no_burn"
