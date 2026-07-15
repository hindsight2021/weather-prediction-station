"""Derive ground-truth outcomes for past predictions.

Two truth sources (roadmap §3.1):

1. The station's own snapshot log (``data/weather_snapshots.jsonl``): did a
   gust/rain/humidex/wind-chill event actually occur in the 1h/24h window
   after each prediction.
2. ECCC CAP alerts polled from the MSC Datamart
   (``https://dd.weather.gc.ca/today/alerts/cap/``) and archived to
   ``data/alerts/alerts.jsonl``. These are the authoritative labels for
   warning-level events.

Run ``python -m verification.outcome_logger`` hourly (systemd timer or the
bundled verifier docker service).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from verification.hazards import hazard_for_alert_event

LOGGER = logging.getLogger("verification.outcome_logger")

CAP_NS = "{urn:oasis:names:tc:emergency:cap:1.2}"

DEFAULT_CAP_BASE = os.environ.get(
    "ECCC_CAP_BASE", "https://dd.weather.gc.ca/today/alerts/cap"
)
# CWHX = ECCC Atlantic Storm Prediction Centre (issues NB public alerts).
DEFAULT_CAP_OFFICES = tuple(
    office.strip()
    for office in os.environ.get("ECCC_CAP_OFFICES", "CWHX").split(",")
    if office.strip()
)
# Case-insensitive substrings matched against CAP <areaDesc>.
DEFAULT_AREA_MATCHES = tuple(
    area.strip().lower()
    for area in os.environ.get("ECCC_CAP_AREA_MATCH", "Fredericton").split(",")
    if area.strip()
)

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
ALERTS_PATH = DATA_DIR / "alerts" / "alerts.jsonl"
SEEN_FILES_PATH = DATA_DIR / "alerts" / "seen_cap_files.json"

HREF_RE = re.compile(r'href="([^"?][^"]*)"')


def _http_get(url: str, timeout: float = 30.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "kcr-weather-brain-verifier"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _list_links(url: str) -> list[str]:
    try:
        html = _http_get(url)
    except Exception as exc:  # noqa: BLE001 - directory may not exist yet today
        LOGGER.debug("Could not list %s: %s", url, exc)
        return []
    return HREF_RE.findall(html)


def parse_cap_document(xml_text: str, area_matches: tuple[str, ...]) -> list[dict]:
    """Extract normalized alert rows from one CAP 1.2 document.

    Returns one row per matched English-language <info> block, or an empty
    list when no area matches the configured region substrings.
    """
    root = ET.fromstring(xml_text)
    identifier = root.findtext(f"{CAP_NS}identifier", default="")
    sent = root.findtext(f"{CAP_NS}sent", default="")
    status = root.findtext(f"{CAP_NS}status", default="")
    msg_type = root.findtext(f"{CAP_NS}msgType", default="")

    rows: list[dict] = []
    for info in root.findall(f"{CAP_NS}info"):
        language = info.findtext(f"{CAP_NS}language", default="en-CA")
        if not language.lower().startswith("en"):
            continue
        matched_areas = [
            area.findtext(f"{CAP_NS}areaDesc", default="")
            for area in info.findall(f"{CAP_NS}area")
            if any(
                needle in (area.findtext(f"{CAP_NS}areaDesc", default="") or "").lower()
                for needle in area_matches
            )
        ]
        if not matched_areas:
            continue
        event = info.findtext(f"{CAP_NS}event", default="")
        rows.append(
            {
                "identifier": identifier,
                "sent": sent,
                "status": status,
                "msg_type": msg_type,
                "event": event,
                "hazard": hazard_for_alert_event(event),
                "severity": info.findtext(f"{CAP_NS}severity", default=""),
                "urgency": info.findtext(f"{CAP_NS}urgency", default=""),
                "certainty": info.findtext(f"{CAP_NS}certainty", default=""),
                "headline": info.findtext(f"{CAP_NS}headline", default=""),
                "onset": info.findtext(f"{CAP_NS}onset", default="")
                or info.findtext(f"{CAP_NS}effective", default=""),
                "expires": info.findtext(f"{CAP_NS}expires", default=""),
                "areas": matched_areas,
            }
        )
    return rows


def poll_cap_alerts(
    alerts_path: Path = ALERTS_PATH,
    seen_path: Path = SEEN_FILES_PATH,
    base_url: str = DEFAULT_CAP_BASE,
    offices: tuple[str, ...] = DEFAULT_CAP_OFFICES,
    area_matches: tuple[str, ...] = DEFAULT_AREA_MATCHES,
    now: datetime | None = None,
) -> int:
    """Fetch new CAP files for today/yesterday and archive matching alerts.

    Returns the number of alert rows appended.
    """
    now = now or datetime.now(timezone.utc)
    seen: set[str] = set()
    if seen_path.exists():
        seen = set(json.loads(seen_path.read_text(encoding="utf-8")))

    appended = 0
    alerts_path.parent.mkdir(parents=True, exist_ok=True)
    for day in (now - timedelta(days=1), now):
        date_str = day.strftime("%Y%m%d")
        for office in offices:
            office_url = f"{base_url}/{date_str}/{office}"
            for hour_link in _list_links(office_url):
                hour = hour_link.strip("/")
                if not hour.isdigit():
                    continue
                hour_url = f"{office_url}/{hour}"
                for file_link in _list_links(hour_url):
                    if not file_link.endswith(".cap"):
                        continue
                    file_key = f"{date_str}/{office}/{hour}/{file_link}"
                    if file_key in seen:
                        continue
                    seen.add(file_key)
                    try:
                        xml_text = _http_get(f"{hour_url}/{file_link}")
                        rows = parse_cap_document(xml_text, area_matches)
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.warning("Failed to process %s: %s", file_key, exc)
                        continue
                    if rows:
                        with alerts_path.open("a", encoding="utf-8") as handle:
                            for row in rows:
                                row["source_file"] = file_key
                                handle.write(json.dumps(row) + "\n")
                                appended += 1

    seen_path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the seen-set bounded to roughly a week of files.
    seen_path.write_text(json.dumps(sorted(seen)[-20000:]), encoding="utf-8")
    if appended:
        LOGGER.info("Archived %d new alert rows to %s", appended, alerts_path)
    return appended


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def alert_active_in_window(alert: dict, start: datetime, end: datetime) -> bool:
    onset = parse_timestamp(alert.get("onset"))
    expires = parse_timestamp(alert.get("expires"))
    if onset is None:
        return False
    if expires is None:
        expires = onset
    return onset <= end and expires >= start


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-alerts", action="store_true", help="Skip the ECCC CAP poll (offline runs).")
    args = parser.parse_args(argv)
    if not args.skip_alerts:
        poll_cap_alerts()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
