from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt

from app.config import MqttSettings

LOGGER = logging.getLogger(__name__)


class WeatherMqttClient:
    def __init__(self, settings: MqttSettings) -> None:
        self.settings = settings
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=settings.client_id)
        if settings.username:
            self.client.username_pw_set(settings.username, settings.password)

    def connect(self, on_message: Callable[[str, str], None], topics: list[str]) -> None:
        def handle_connect(client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
            LOGGER.info("Connected to MQTT with reason_code=%s", reason_code)
            client.publish(self.settings.availability_topic, "online", retain=True)
            for topic in topics:
                LOGGER.info("Subscribing to %s", topic)
                client.subscribe(topic)

        def handle_message(client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
            payload = message.payload.decode("utf-8", errors="replace")
            on_message(message.topic, payload)

        self.client.on_connect = handle_connect
        self.client.on_message = handle_message
        self.client.connect(self.settings.host, self.settings.port, keepalive=60)
        self.client.loop_start()

    def publish_json(self, topic: str, payload: dict[str, Any], retain: bool = True) -> None:
        self.client.publish(topic, json.dumps(payload), retain=retain)

    def publish_text(self, topic: str, payload: str, retain: bool = True) -> None:
        self.client.publish(topic, payload, retain=retain)

    def stop(self) -> None:
        self.client.publish(self.settings.availability_topic, "offline", retain=True)
        self.client.loop_stop()
        self.client.disconnect()
