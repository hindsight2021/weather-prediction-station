"""Long-running verifier loop for the Pi docker deployment.

Every cycle (default hourly): poll ECCC CAP alerts, rebuild the scoreboard
from the prediction/snapshot logs, and publish headline metrics to MQTT.
Equivalent to the systemd-timer deployment described in the roadmap, packaged
as a docker-compose service so the whole stack ships together.
"""

from __future__ import annotations

import logging
import os
import time

from verification import report

LOGGER = logging.getLogger("verification.runner")

INTERVAL_SECONDS = int(os.environ.get("VERIFY_INTERVAL_SECONDS", "3600"))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    publish = os.environ.get("VERIFY_PUBLISH_MQTT", "1") not in ("0", "false", "False")
    argv = ["--poll-alerts"] + (["--publish-mqtt"] if publish else [])
    while True:
        try:
            report.main(argv)
        except Exception:  # noqa: BLE001 - the loop must survive feed/broker hiccups
            LOGGER.exception("Verification cycle failed; retrying next interval")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
