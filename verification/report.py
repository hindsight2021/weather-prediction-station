"""Write the verification scoreboard and optionally publish headlines to MQTT.

Usage:
    python -m verification.report                # score logs, write scoreboard
    python -m verification.report --poll-alerts  # also refresh the CAP archive
    python -m verification.report --publish-mqtt # push headline metrics to HA

``make verify`` runs the first form.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from verification.score import (
    DEFAULT_PREDICTIONS_PATH,
    DEFAULT_SNAPSHOTS_PATH,
    build_scoreboard,
)
from verification.outcome_logger import ALERTS_PATH, poll_cap_alerts

LOGGER = logging.getLogger("verification.report")

DEFAULT_OUTPUT_DIR = Path("data/verification")
MQTT_TOPIC_PREFIX = "weather_brain/verification"


def _format_number(value: float | None, digits: int = 4) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def render_markdown(scoreboard: dict) -> str:
    lines = [
        "# Weather Brain verification scoreboard",
        "",
        f"Generated: {scoreboard['generated_at']}  ",
        f"Rolling window: {scoreboard['window_days']} days",
        "",
        "| Hazard | n | Event rate | Brier | Climatology | Persistence | Raw forecast | BSS vs clim. | POD | FAR |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for hazard in scoreboard["hazards"]:
        tier = hazard["advisory_tier"]
        lines.append(
            "| {hazard} | {n} | {rate} | {brier} | {clim} | {persist} | {forecast} | {bss} | {pod} | {far} |".format(
                hazard=hazard["hazard"],
                n=hazard["n"],
                rate=_format_number(hazard["event_rate"], 3),
                brier=_format_number(hazard["brier"]),
                clim=_format_number(hazard["brier_climatology"]),
                persist=_format_number(hazard["brier_persistence"]),
                forecast=_format_number(hazard["brier_forecast"]),
                bss=_format_number(hazard["brier_skill_vs_climatology"], 3),
                pod=_format_number(tier["pod"], 3),
                far=_format_number(tier["far"], 3),
            )
        )
    lines += [
        "",
        "Brier: lower is better (0 = perfect). BSS vs climatology: 1 = perfect, ",
        "0 = no better than base rate, negative = worse than climatology.",
        "POD/FAR evaluated at the advisory tier (published risk >= 40).",
        "",
    ]
    return "\n".join(lines)


def publish_headlines(scoreboard: dict) -> None:
    """Publish per-hazard Brier and FAR so the scoreboard is visible in HA."""
    from dataclasses import replace

    from app.config import load_config
    from app.mqtt_client import WeatherMqttClient

    config = load_config()
    # Distinct client id: sharing the main service's id would make the broker
    # disconnect whichever client connected first.
    settings = replace(
        config.mqtt,
        client_id=f"{config.mqtt.client_id}-verifier",
        availability_topic=f"{MQTT_TOPIC_PREFIX}/status",
    )
    client = WeatherMqttClient(settings)
    client.connect(on_message=lambda topic, payload: None, topics=[])
    try:
        for hazard in scoreboard["hazards"]:
            payload = {
                "n": hazard["n"],
                "brier": hazard["brier"],
                "brier_climatology": hazard["brier_climatology"],
                "brier_skill_vs_climatology": hazard["brier_skill_vs_climatology"],
                "far_advisory": hazard["advisory_tier"]["far"],
                "pod_advisory": hazard["advisory_tier"]["pod"],
            }
            client.publish_json(f"{MQTT_TOPIC_PREFIX}/{hazard['hazard']}", payload, retain=True)
        client.publish_json(
            f"{MQTT_TOPIC_PREFIX}/meta",
            {"generated_at": scoreboard["generated_at"], "window_days": scoreboard["window_days"]},
            retain=True,
        )
    finally:
        client.stop()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS_PATH)
    parser.add_argument("--snapshots", type=Path, default=DEFAULT_SNAPSHOTS_PATH)
    parser.add_argument("--alerts", type=Path, default=ALERTS_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--poll-alerts", action="store_true")
    parser.add_argument("--publish-mqtt", action="store_true")
    args = parser.parse_args(argv)

    if args.poll_alerts:
        poll_cap_alerts(alerts_path=args.alerts)

    scoreboard = build_scoreboard(
        predictions_path=args.predictions,
        snapshots_path=args.snapshots,
        alerts_path=args.alerts,
        window_days=args.window_days,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "scoreboard.json"
    json_path.write_text(json.dumps(scoreboard, indent=2), encoding="utf-8")
    markdown_path = args.output_dir / "scoreboard.md"
    markdown_path.write_text(render_markdown(scoreboard), encoding="utf-8")
    LOGGER.info("Wrote %s and %s", json_path, markdown_path)

    if args.publish_mqtt:
        publish_headlines(scoreboard)

    scored = sum(hazard["n"] for hazard in scoreboard["hazards"])
    if scored == 0:
        LOGGER.warning(
            "No prediction/outcome pairs could be joined yet. "
            "The scoreboard becomes meaningful after ~14 days of live logging."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
