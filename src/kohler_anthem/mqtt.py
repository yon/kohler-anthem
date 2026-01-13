"""Azure IoT Hub MQTT client for Kohler Anthem real-time updates."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)


class KohlerMqttClient:
    """MQTT client for Azure IoT Hub real-time state updates."""

    def __init__(self, iot_hub_settings: dict[str, Any]) -> None:
        """Initialize the MQTT client.

        Args:
            iot_hub_settings: IoT Hub settings from register_mobile_device() containing:
                - ioTHub: IoT Hub hostname (e.g., prd-hub.azure-devices.net)
                - deviceId: MQTT client ID
                - username: MQTT username
                - password: SAS token for authentication
        """
        self._host = iot_hub_settings.get("ioTHub", "")
        self._device_id = iot_hub_settings.get("deviceId", "")
        self._username = iot_hub_settings.get("username", "")
        self._password = iot_hub_settings.get("password", "")
        self._client: mqtt.Client | None = None
        self._callbacks: list[Callable[[str, bytes | bytearray], None]] = []
        self._connected = False
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_connected(self) -> bool:
        """Return True if connected to IoT Hub."""
        return self._connected

    def add_callback(self, callback: Callable[[str, bytes | bytearray], None]) -> None:
        """Add a callback for incoming messages.

        Args:
            callback: Function called with (topic, payload) for each message
        """
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[str, bytes | bytearray], None]) -> None:
        """Remove a previously added callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    async def connect(self) -> bool:
        """Connect to Azure IoT Hub via MQTT.

        Returns:
            True if connection successful, False otherwise
        """
        if not self._host or not self._device_id:
            _LOGGER.error("Missing IoT Hub settings, cannot connect")
            return False

        self._loop = asyncio.get_event_loop()

        try:
            # Create MQTT client with Azure IoT Hub compatible settings
            self._client = mqtt.Client(
                client_id=self._device_id,
                protocol=mqtt.MQTTv311,
                transport="tcp",
            )

            # Set authentication
            self._client.username_pw_set(self._username, self._password)

            # Configure TLS (required for Azure IoT Hub)
            ssl_context = ssl.create_default_context()
            self._client.tls_set_context(ssl_context)

            # Set callbacks
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message = self._on_message

            _LOGGER.debug("Connecting to Azure IoT Hub: %s", self._host)

            # Connect (non-blocking)
            self._client.connect_async(self._host, 8883, keepalive=60)

            # Start the MQTT loop in a background thread
            self._client.loop_start()

            # Wait for connection with timeout
            for _ in range(30):  # 3 second timeout
                if self._connected:
                    return True
                await asyncio.sleep(0.1)

            _LOGGER.warning("MQTT connection timeout")
            return False

        except Exception as e:
            _LOGGER.error("Failed to connect to IoT Hub: %s", e)
            return False

    async def disconnect(self) -> None:
        """Disconnect from Azure IoT Hub."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
        self._connected = False

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: dict[str, Any],
        rc: int,
    ) -> None:
        """Handle MQTT connection callback."""
        if rc == 0:
            _LOGGER.info("Connected to Azure IoT Hub successfully")
            self._connected = True

            # Subscribe to device-bound messages (cloud to device)
            # Azure IoT Hub topic format
            topic = f"devices/{self._device_id}/messages/devicebound/#"
            client.subscribe(topic, qos=1)
            _LOGGER.debug("Subscribed to: %s", topic)

            # Also subscribe to direct method invocations
            client.subscribe("$iothub/methods/POST/#", qos=1)
        else:
            _LOGGER.error("Failed to connect to IoT Hub, return code: %d", rc)
            self._connected = False

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        rc: int,
    ) -> None:
        """Handle MQTT disconnection callback."""
        self._connected = False
        if rc != 0:
            _LOGGER.warning("Unexpected disconnect from IoT Hub, rc=%d", rc)
        else:
            _LOGGER.info("Disconnected from IoT Hub")

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        msg: mqtt.MQTTMessage,
    ) -> None:
        """Handle incoming MQTT message."""
        _LOGGER.debug("IoT Hub message received: %s", msg.topic)

        # Handle Direct Method invocations - need to send response
        if msg.topic.startswith("$iothub/methods/POST/"):
            self._handle_direct_method(client, msg)

        # Call all registered callbacks
        for callback in self._callbacks:
            try:
                if self._loop:
                    # Schedule callback in the event loop
                    self._loop.call_soon_threadsafe(callback, msg.topic, msg.payload)
                else:
                    callback(msg.topic, msg.payload)
            except Exception as e:
                _LOGGER.error("Error in MQTT callback: %s", e)

    def _handle_direct_method(
        self,
        client: mqtt.Client,
        msg: mqtt.MQTTMessage,
    ) -> None:
        """Respond to Direct Method invocation from IoT Hub."""
        # Topic format: $iothub/methods/POST/{method_name}/?$rid={request_id}
        try:
            # Extract request ID from topic
            if "?$rid=" in msg.topic:
                rid = msg.topic.split("?$rid=")[1]
                # Send success response (status 200)
                response_topic = f"$iothub/methods/res/200/?$rid={rid}"
                # Response can be empty or echo back acknowledgment
                response_payload = b'{"status":"received"}'
                client.publish(response_topic, response_payload, qos=1)
                _LOGGER.debug("Sent Direct Method response to: %s", response_topic)
        except Exception as e:
            _LOGGER.warning("Failed to respond to Direct Method: %s", e)

    def parse_state_update(self, payload: bytes) -> dict[str, Any] | None:
        """Parse a state update message from IoT Hub.

        Args:
            payload: Raw message payload

        Returns:
            Parsed state dictionary or None if parsing fails
        """
        try:
            data: dict[str, Any] = json.loads(payload.decode("utf-8"))
            return data
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            _LOGGER.debug("Failed to parse IoT Hub message: %s", e)
            return None
