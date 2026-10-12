"""BLE connection handling for a Moonside lamp (write-only)."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later

from .const import (
    IDLE_DISCONNECT_SECONDS,
    MIN_WRITE_INTERVAL,
    UART_READ_CHAR_UUID,
    UART_WRITE_CHAR_UUID,
)

_LOGGER = logging.getLogger(__name__)

# One reconnect after a failed write. Write-without-response gives no
# acknowledgement, so a failure here is a transport error (link dropped, or the
# ATT MTU not negotiated yet), not a device reply.
WRITE_ATTEMPTS = 2


class MoonsideDevice:
    """Manages a lazy, reused BLE connection to a Moonside lamp.

    The lamp gives no acknowledgement on writes, so this class only sends
    ASCII commands. The connection is opened on the first write, reused for
    subsequent writes, and dropped after a period of inactivity so the
    proxy's connection slot is freed.
    """

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        self._hass = hass
        self._address = address
        self._client: BleakClientWithServiceCache | None = None
        self._lock = asyncio.Lock()
        self._cancel_disconnect: CALLBACK_TYPE | None = None
        self._last_write = 0.0

    @property
    def address(self) -> str:
        return self._address

    async def _ensure_connected(self) -> BleakClientWithServiceCache:
        if self._client is not None and self._client.is_connected:
            return self._client

        ble_device = bluetooth.async_ble_device_from_address(
            self._hass, self._address, connectable=True
        )
        if ble_device is None:
            raise RuntimeError(
                f"Moonside {self._address} niet binnen bereik van een "
                "bluetooth proxy"
            )

        # use_services_cache=False: wait for BlueZ to report ServicesResolved
        # before returning. With the cache, connect() returns as soon as the
        # link is up, before bluetoothd has negotiated the ATT MTU; a command
        # longer than 20 bytes (every multi-colour THEME) written in that
        # window fails with "[org.bluez.Error.Failed] Failed to initiate
        # write". Service discovery costs ~1-2 s once per connection.
        self._client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            self._address,
            disconnected_callback=self._on_disconnected,
            use_services_cache=False,
        )
        _LOGGER.debug("Verbonden met Moonside %s", self._address)
        return self._client

    @callback
    def _on_disconnected(self, _client: BleakClientWithServiceCache) -> None:
        """Forget the client when BlueZ reports the link went away."""
        _LOGGER.debug("Moonside %s disconnected", self._address)
        self._client = None
        if self._cancel_disconnect is not None:
            self._cancel_disconnect()
            self._cancel_disconnect = None

    async def _drop_client(self) -> None:
        """Best-effort disconnect; the next write reconnects."""
        client, self._client = self._client, None
        if client is None:
            return
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001 - best effort cleanup
            _LOGGER.debug("Fout bij verbreken", exc_info=True)

    async def send(self, command: str) -> None:
        """Connect if needed and write one ASCII command.

        The docs (developer.moonside.design) note that the device sends no
        acknowledgement on writes and that "rapid writes can interrupt
        animation transitions", so we write without a response and space
        consecutive writes out with MIN_WRITE_INTERVAL.

        A failed write drops the connection and is retried once on a fresh
        one; a second failure is raised as HomeAssistantError so automations
        see it in the trace (and in the log) instead of silently losing it.
        """
        payload = command.encode("ascii")
        async with self._lock:
            for attempt in range(1, WRITE_ATTEMPTS + 1):
                client = await self._ensure_connected()

                gap = MIN_WRITE_INTERVAL - (monotonic() - self._last_write)
                if gap > 0:
                    await asyncio.sleep(gap)

                _LOGGER.debug("Halo %s <- %s", self._address, command)
                try:
                    await client.write_gatt_char(
                        UART_WRITE_CHAR_UUID, payload, response=False
                    )
                except BleakError as err:
                    await self._drop_client()
                    if attempt < WRITE_ATTEMPTS:
                        _LOGGER.warning(
                            "Write to Moonside %s failed (%s), reconnecting",
                            self._address,
                            err,
                        )
                        continue
                    raise HomeAssistantError(
                        f"Moonside {self._address}: write of {len(payload)} "
                        f"bytes failed after reconnect: {err}"
                    ) from err

                self._last_write = monotonic()
                self._schedule_disconnect()
                return

    async def read_version(self) -> str | None:
        """Read the 'version|mac' string from the read characteristic."""
        async with self._lock:
            client = await self._ensure_connected()
            raw = await client.read_gatt_char(UART_READ_CHAR_UUID)
            self._schedule_disconnect()
        return bytes(raw).decode("ascii", errors="replace").strip()

    @callback
    def _schedule_disconnect(self) -> None:
        if self._cancel_disconnect is not None:
            self._cancel_disconnect()
        self._cancel_disconnect = async_call_later(
            self._hass, IDLE_DISCONNECT_SECONDS, self._trigger_disconnect
        )

    @callback
    def _trigger_disconnect(self, _now=None) -> None:
        self._cancel_disconnect = None
        self._hass.async_create_task(self.disconnect())

    async def disconnect(self) -> None:
        async with self._lock:
            if self._cancel_disconnect is not None:
                self._cancel_disconnect()
                self._cancel_disconnect = None
            await self._drop_client()
