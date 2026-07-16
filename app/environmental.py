from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

ECCC_API = "https://api.weather.gc.ca/collections"
NB_BURN_API = "https://gis-erd-der.gnb.ca/gisserver/rest/services/FireWeather/BurnCategories/MapServer/0/query"
NB_FIRE_API = "https://gis-erd-der.gnb.ca/gisserver/rest/services/New_Brunswick_Fires/New_Brunswick_Fire_Locations/MapServer/0/query"


def _get(url: str, params: dict[str, object]) -> dict:
    request = Request(f"{url}?{urlencode(params)}", headers={"User-Agent": "KCR-Weather-Brain/2.0"})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


class EnvironmentalClient:
    """Fetch authoritative Canadian hazards. Failures preserve the last good reading."""

    def __init__(self, latitude: float, longitude: float):
        self.latitude, self.longitude = latitude, longitude
        self.last: dict[str, float | str] = {}

    def fetch(self) -> dict[str, float | str]:
        result = dict(self.last)
        for loader in (self._alerts, self._aqhi, self._nb_fire):
            try:
                result.update(loader())
            except Exception as exc:
                LOGGER.warning("Environmental feed failed (%s): %s", loader.__name__, exc)
        self.last = result
        return result

    def _alerts(self) -> dict[str, float | str]:
        pad = 0.35
        data = _get(f"{ECCC_API}/weather-alerts/items", {
            "f": "json", "bbox": f"{self.longitude-pad},{self.latitude-pad},{self.longitude+pad},{self.latitude+pad}", "limit": 100
        })
        now = datetime.now(timezone.utc)
        active = []
        ranks = {"statement": 1, "advisory": 1, "watch": 2, "warning": 3}
        for feature in data.get("features", []):
            p = feature.get("properties", {})
            expiry = p.get("expiration_datetime")
            try:
                expires = datetime.fromisoformat(expiry.replace("Z", "+00:00")) if expiry else now
            except ValueError:
                expires = now
            if str(p.get("status_en", "")).lower() == "active" and expires >= now:
                active.append(p)
        best = max(active, key=lambda p: ranks.get(str(p.get("alert_type", "")).lower(), 0), default={})
        level = str(best.get("alert_type", "none")).lower()
        return {
            "official_alert_severity": float(ranks.get(level, 0)),
            "official_alert_count": float(len(active)),
            "official_alert_level": level,
            "official_alert_summary": str(best.get("alert_name_en", "No active ECCC alert.")),
        }

    def _aqhi(self) -> dict[str, float]:
        pad = 0.6
        bbox = f"{self.longitude-pad},{self.latitude-pad},{self.longitude+pad},{self.latitude+pad}"
        obs = _get(f"{ECCC_API}/aqhi-observations-realtime/items", {"f": "json", "bbox": bbox, "limit": 100})
        fcst = _get(f"{ECCC_API}/aqhi-forecasts-realtime/items", {"f": "json", "bbox": bbox, "limit": 200})
        observations = [float(f["properties"]["aqhi"]) for f in obs.get("features", []) if f.get("properties", {}).get("aqhi") is not None]
        forecasts = [float(f["properties"]["aqhi"]) for f in fcst.get("features", []) if f.get("properties", {}).get("aqhi") is not None]
        current = max(observations, default=0.0)
        peak = max(forecasts, default=current)
        # AQHI >= 7 is high; nearby fires increase smoke concern without pretending to measure PM2.5.
        return {"aqhi_current": current, "aqhi_forecast_max_24h": peak, "aqhi_forecast_max_48h": peak}

    def _nb_fire(self) -> dict[str, float | str]:
        common = {"where": "1=1", "outFields": "*", "f": "geojson", "outSR": 4326}
        burn = _get(NB_BURN_API, common)
        category = 0
        for feature in burn.get("features", []):
            if "YORK" in str(feature.get("properties", {}).get("NAME", "")).upper():
                category = int(feature["properties"].get("PUBLICCATEGORY") or 0)
                break
        fires = _get(NB_FIRE_API, common)
        nearby = 0
        nearest_km: float | None = None
        for feature in fires.get("features", []):
            p = feature.get("properties", {})
            if str(p.get("FIELD_STAGE_OF_CONTROL", "")).upper() == "EX":
                continue
            lat, lon = p.get("FIELD_LAT"), p.get("FIELD_LONG")
            if lat is None or lon is None:
                continue
            distance = _distance_km(self.latitude, self.longitude, float(lat), float(lon))
            if distance <= 150:
                nearby += 1
            if nearest_km is None or distance < nearest_km:
                nearest_km = distance
        labels = {1: "no_burn", 2: "restricted_20h_to_08h", 3: "burn_permitted"}
        return {
            "nb_burn_category": float(category),
            "nb_burn_status": labels.get(category, "unknown"),
            "active_fires_nearby": float(nearby),
            # 999 = no active fire anywhere in the NB feed (sentinel keeps the sensor numeric).
            "nearest_fire_km": round(nearest_km, 1) if nearest_km is not None else 999.0,
        }


BURN_CATEGORY_LABELS = {0: "unknown", 1: "no_burn", 2: "restricted_20h_to_08h", 3: "burn_permitted"}


def fetch_fire_map_data(latitude: float, longitude: float) -> dict:
    """Full NB wildfire picture for the fire-warden console: county burn-category
    polygons and every active fire with distance from home. Pulled from the same
    GNB ERD feeds the prediction engine uses — no third-party map embeds."""
    common = {"where": "1=1", "outFields": "*", "f": "geojson", "outSR": 4326}
    burn = _get(NB_BURN_API, common)
    counties = []
    for feature in burn.get("features", []):
        properties = feature.get("properties", {})
        counties.append(
            {
                "name": str(properties.get("NAME", "")).title(),
                "category": int(properties.get("PUBLICCATEGORY") or 0),
                "geometry": feature.get("geometry"),
            }
        )

    fires_raw = _get(NB_FIRE_API, common)
    fires = []
    for feature in fires_raw.get("features", []):
        p = feature.get("properties", {})
        lat, lon = p.get("FIELD_LAT"), p.get("FIELD_LONG")
        if lat is None or lon is None:
            continue
        stage = str(p.get("FIELD_STAGE_OF_CONTROL", "")).upper()
        fires.append(
            {
                "name": str(p.get("FIELD_FIRE_NAME") or p.get("FIRE_NAME") or p.get("FIELD_FIRE_NUMBER") or "Fire"),
                "lat": float(lat),
                "lon": float(lon),
                "stage": stage,
                "size_ha": p.get("FIELD_FIRE_SIZE") or p.get("FIELD_CURRENT_SIZE"),
                "detected": p.get("FIELD_DETECTED_DATE") or p.get("FIELD_REPORT_DATE"),
                "distance_km": round(_distance_km(latitude, longitude, float(lat), float(lon)), 1),
            }
        )
    fires.sort(key=lambda fire: fire["distance_km"])

    york = next((c for c in counties if "YORK" in c["name"].upper()), None)
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "home": {"lat": latitude, "lon": longitude},
        "counties": counties,
        "fires": fires,
        "york_burn_category": york["category"] if york else 0,
        "york_burn_status": BURN_CATEGORY_LABELS.get(york["category"] if york else 0, "unknown"),
        "active_fire_count": sum(1 for fire in fires if fire["stage"] != "EX"),
        "nearest_active_km": next((fire["distance_km"] for fire in fires if fire["stage"] != "EX"), None),
    }
