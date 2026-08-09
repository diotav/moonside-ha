"""Diagnostic sensor for the Moonside integration."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import MoonsideDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Moonside diagnostic sensor."""
    device: MoonsideDevice = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MoonsideFirmwareSensor(device, entry)])


class MoonsideFirmwareSensor(SensorEntity):
    """Firmware version, read once from the lamp on connect."""

    _attr_has_entity_name = True
    _attr_name = "Firmware"
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chip"

    def __init__(self, device: MoonsideDevice, entry: ConfigEntry) -> None:
        self._device = device
        self._base_id = entry.unique_id or entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{self._base_id}_firmware"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._base_id)},
            connections={(CONNECTION_BLUETOOTH, device.address)},
            manufacturer="Moonside",
            name=entry.title,
        )
        self._attr_native_value = None

    async def async_added_to_hass(self) -> None:
        """Read the firmware version once when added."""
        await self._async_refresh()

    async def _async_refresh(self) -> None:
        try:
            raw = await self._device.read_version()
        except Exception:  # noqa: BLE001 - lamp may be out of range
            _LOGGER.debug("Kon firmwareversie niet lezen", exc_info=True)
            return
        if not raw:
            return

        version = raw.split("|", 1)[0]
        self._attr_native_value = version
        self.async_write_ha_state()

        # Also surface it on the device page as the firmware version.
        dev_reg = dr.async_get(self.hass)
        if device := dev_reg.async_get_device(identifiers={(DOMAIN, self._base_id)}):
            dev_reg.async_update_device(device.id, sw_version=version)
