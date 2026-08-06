"""BLE connection handling for a Moonside lamp (write-only)."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import (
    IDLE_DISCONNECT_SECONDS,
    MIN_WRITE_INTERVAL,
    UART_READ_CHAR_UUID,
    UART_WRITE_CHAR_UUID,
)

_LOGGER = logging.getLogger(__name__)


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

        self._client = await establish_connection(
            BleakClientWithServiceCache, ble_device, self._address
        )
        _LOGGER.debug("Verbonden met Moonside %s", self._address)
        return self._client

    async def send(self, command: str) -> None:
        """Connect if needed and write one ASCII command.

        Writes gaan met ATT-response: write_gatt_char keert dan pas terug
        zodra de BLE-stack de write bevestigt, niet zodra het pakket lokaal
        in de queue staat. Dat serialiseert opeenvolgende writes betrouwbaar
        -- ook door een Bluetooth-proxy heen -- en voorkomt dat een tweede
        write de eerste inhaalt of ermee versmelt (afgekapte commando's).
        MIN_WRITE_INTERVAL blijft als kleine vangnet-buffer staan.
        """
        async with self._lock:
            client = await self._ensure_connected()

            gap = MIN_WRITE_INTERVAL - (monotonic() - self._last_write)
            if gap > 0:
                await asyncio.sleep(gap)

            _LOGGER.debug("Halo %s <- %s", self._address, command)
            await client.write_gatt_char(
                UART_WRITE_CHAR_UUID, command.encode("ascii"), response=True
            )
            self._last_write = monotonic()
            self._schedule_disconnect()

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
            if self._client is not None:
                try:
                    await self._client.disconnect()
                except Exception:  # noqa: BLE001 - best effort cleanup
                    _LOGGER.debug("Fout bij verbreken", exc_info=True)
                finally:
                    self._client = None
