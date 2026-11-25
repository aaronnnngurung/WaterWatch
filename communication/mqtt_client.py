
"""Secure MQTT communication client for WaterWatch."""

import json
import logging
import ssl
import threading
import time

import paho.mqtt.client as mqtt


logger = logging.getLogger("WaterWatch.MQTT")

TELEMETRY_TOPIC = "v1/devices/me/telemetry"


class WaterWatchMQTT:
    """Manage a secure MQTT connection to one ThingsBoard device."""

    def __init__(
        self,
        node_name,
        access_token,
        host="mqtt.eu.thingsboard.cloud",
        port=8883,
        ca_certs=None,
        keepalive=60
    ):
        if not access_token:
            raise ValueError(
                f"Missing MQTT access token for {node_name}"
            )

        self.node_name = node_name
        self.access_token = access_token
        self.host = host
        self.port = port
        self.keepalive = keepalive
        self.ca_certs = ca_certs

        self.connected = threading.Event()
        self.connection_failed = threading.Event()
        self.last_error = None

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"WaterWatch_{node_name}",
            protocol=mqtt.MQTTv311
        )

        # ThingsBoard uses the device access token as the username.
        self.client.username_pw_set(self.access_token)

        # Enable TLS certificate verification.
        self.client.tls_set(
            ca_certs=self.ca_certs,
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS_CLIENT
        )

        self.client.tls_insecure_set(False)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_publish = self._on_publish

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """Handle successful or failed MQTT connection."""

        if reason_code.is_failure:
            self.last_error = reason_code
            self.connection_failed.set()

            logger.error(
                "MQTT CONNECTION FAILED | node=%s | reason=%s",
                self.node_name,
                reason_code
            )

            return

        self.last_error = None
        self.connection_failed.clear()
        self.connected.set()

        logger.info(
            "MQTT CONNECTED | node=%s | broker=%s:%s",
            self.node_name,
            self.host,
            self.port
        )

    def _on_disconnect(
        self,
        client,
        userdata,
        disconnect_flags,
        reason_code,
        properties
    ):
        """Handle MQTT disconnection."""

        self.connected.clear()

        if reason_code.is_failure:
            logger.warning(
                "MQTT NETWORK DISCONNECTED | node=%s | reason=%s",
                self.node_name,
                reason_code
            )
        else:
            logger.info(
                "MQTT DISCONNECTED | node=%s",
                self.node_name
            )

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        """Log MQTT publish acknowledgement."""

        if reason_code.is_failure:
            logger.error(
                "MQTT PUBLISH REJECTED | node=%s | mid=%s | reason=%s",
                self.node_name,
                mid,
                reason_code
            )

    def connect(self, timeout=15):
        """Connect to ThingsBoard and wait for the connection result."""

        self.connected.clear()
        self.connection_failed.clear()
        self.last_error = None

        try:
            self.client.connect(
                self.host,
                self.port,
                self.keepalive
            )

            self.client.loop_start()

        except (ssl.SSLError, OSError) as error:
            logger.error(
                "MQTT NETWORK/TLS ERROR | node=%s | %s",
                self.node_name,
                error
            )
            return False

        if not self.connected.wait(timeout):
            if self.connection_failed.is_set():
                logger.error(
                    "MQTT AUTHENTICATION/CONNECTION FAILURE | node=%s",
                    self.node_name
                )
            else:
                logger.error(
                    "MQTT CONNECTION TIMEOUT | node=%s",
                    self.node_name
                )

            self.disconnect()
            return False

        return True

    def publish_reading(self, payload, timeout=10):
        """
        Publish a timestamped telemetry reading.

        The original acquisition timestamp is preserved using
        ThingsBoard's explicit timestamped telemetry format.
        """

        if not self.connected.is_set():
            logger.warning(
                "MQTT OFFLINE | node=%s | reading not published",
                self.node_name
            )
            return False

        if "ts" not in payload:
            raise ValueError("Telemetry payload must contain 'ts'.")

        timestamp_ms = int(payload["ts"])

        values = {
            key: value
            for key, value in payload.items()
            if key != "ts"
        }

        message = {
            "ts": timestamp_ms,
            "values": values
        }

        try:
            result = self.client.publish(
                TELEMETRY_TOPIC,
                json.dumps(message),
                qos=1,
                retain=False
            )

            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                logger.error(
                    "MQTT PUBLISH FAILED | node=%s | rc=%s",
                    self.node_name,
                    result.rc
                )
                return False

            # Wait for the broker's QoS 1 acknowledgement.
            result.wait_for_publish(timeout=timeout)

            if not result.is_published():
                logger.error(
                    "MQTT DELIVERY TIMEOUT | node=%s",
                    self.node_name
                )
                return False

            logger.info(
                "MQTT DELIVERED | node=%s | timestamp=%s",
                self.node_name,
                timestamp_ms
            )

            return True

        except (ValueError, RuntimeError, OSError) as error:
            logger.error(
                "MQTT PUBLISH ERROR | node=%s | %s",
                self.node_name,
                error
            )
            return False

    def disconnect(self):
        """Disconnect cleanly from the MQTT broker."""

        try:
            self.client.disconnect()
            self.client.loop_stop()
        finally:
            self.connected.clear()
