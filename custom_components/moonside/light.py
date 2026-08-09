"""Light platform for the Moonside integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .commands import (
    NotEnoughColorsError,
    UnknownThemeError,
    backled_command,
    brightness_to_pct,
    color_command,
    pixel_command,
    theme_command,
)
from .const import BACKLED_SECTIONS, DOMAIN, EFFECTS, PIXEL_MAX_INDEX
from .device import MoonsideDevice

RGB = vol.All(
    cv.ensure_list,
    [vol.All(vol.Coerce(int), vol.Range(min=0, max=255))],
    vol.Length(min=3, max=3),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Moonside light and its custom services."""
    device: MoonsideDevice = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MoonsideLight(device, entry)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "send_command",
        {vol.Required("command"): cv.string},
        "async_send_command",
    )
    platform.async_register_entity_service(
        "set_theme",
        {
            vol.Required("theme"): cv.string,
            vol.Optional("color"): RGB,
            vol.Optional("color2"): RGB,
            vol.Optional("color3"): RGB,
            vol.Optional("color4"): RGB,
            vol.Optional("color5"): RGB,
            vol.Optional("color6"): RGB,
            vol.Optional("speed"): vol.Coerce(int),
        },
        "async_set_theme",
    )
    platform.async_register_entity_service(
        "set_pixel",
        {
            vol.Required("index"): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=PIXEL_MAX_INDEX)
            ),
            vol.Required("color"): RGB,
        },
        "async_set_pixel",
    )
    platform.async_register_entity_service(
        "set_backled",
        {
            vol.Required("section"): vol.All(vol.Coerce(int), vol.In(BACKLED_SECTIONS)),
            vol.Required("color"): RGB,
        },
        "async_set_backled",
    )


class MoonsideLight(LightEntity, RestoreEntity):
    """A write-only, optimistic Moonside light."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_assumed_state = True
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = list(EFFECTS)

    def __init__(self, device: MoonsideDevice, entry: ConfigEntry) -> None:
        self._device = device
        self._attr_unique_id = entry.unique_id or entry.data[CONF_ADDRESS]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            connections={(CONNECTION_BLUETOOTH, device.address)},
            manufacturer="Moonside",
            name=entry.title,
        )
        self._attr_is_on = False
        self._attr_brightness = 255
        self._attr_rgb_color = (255, 255, 255)
        self._attr_effect = None

    async def async_added_to_hass(self) -> None:
        """Restore the last assumed state and track Bluetooth presence.

        The lamp keeps its own state while Home Assistant is down, so restoring
        only realigns HA's optimistic view — no command is sent to the device.
        """
        await super().async_added_to_hass()
        self._async_setup_availability()

        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == STATE_ON
            if (brightness := last.attributes.get(ATTR_BRIGHTNESS)) is not None:
                self._attr_brightness = brightness
            if (rgb := last.attributes.get(ATTR_RGB_COLOR)) is not None:
                self._attr_rgb_color = tuple(rgb)
            self._attr_effect = last.attributes.get(ATTR_EFFECT)

    @callback
    def _async_setup_availability(self) -> None:
        """Mark the entity available while a proxy can see the lamp.

        The lamp gives no feedback, so availability follows Bluetooth presence:
        an advertisement marks it available, and the unavailability tracker
        (fired when no proxy has seen it for a while) marks it unavailable.
        """
        address = self._device.address
        self._attr_available = bluetooth.async_address_present(
            self.hass, address, connectable=True
        )
        self.async_on_remove(
            bluetooth.async_register_callback(
                self.hass,
                self._async_bluetooth_seen,
                BluetoothCallbackMatcher(address=address, connectable=True),
                BluetoothScanningMode.ACTIVE,
            )
        )
        self.async_on_remove(
            bluetooth.async_track_unavailable(
                self.hass, self._async_bluetooth_unavailable, address, connectable=True
            )
        )

    @callback
    def _async_bluetooth_seen(
        self, service_info: BluetoothServiceInfoBleak, change: BluetoothChange
    ) -> None:
        if not self._attr_available:
            self._attr_available = True
            self.async_write_ha_state()

    @callback
    def _async_bluetooth_unavailable(
        self, service_info: BluetoothServiceInfoBleak
    ) -> None:
        self._attr_available = False
        self.async_write_ha_state()

    async def _reset_before_theme(self) -> None:
        """Power off before applying a theme so the previous state doesn't bleed.

        A theme applied while the lamp is on is tinted or blended by whatever it
        is showing -- a static colour or another running theme -- while applying
        it from an off lamp is clean (confirmed on-device). So briefly power off
        first whenever the lamp is already on.
        """
        if self._attr_is_on:
            await self._device.send("LEDOFF")

    async def async_turn_on(self, **kwargs: Any) -> None:
        effect = kwargs.get(ATTR_EFFECT)
        rgb = kwargs.get(ATTR_RGB_COLOR)
        brightness = kwargs.get(ATTR_BRIGHTNESS)

        if effect is not None and effect in EFFECTS:
            await self._reset_before_theme()
            await self._device.send(EFFECTS[effect])
            self._attr_effect = effect
        elif rgb is not None:
            await self._device.send(color_command(rgb))
            self._attr_rgb_color = tuple(rgb)
            self._attr_effect = None
        elif not self._attr_is_on:
            await self._device.send("LEDON")

        if brightness is not None:
            await self._device.send(f"BRIGH{brightness_to_pct(brightness)}")
            self._attr_brightness = brightness

        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._device.send("LEDOFF")
        self._attr_is_on = False
        self.async_write_ha_state()

    # --- Custom services -------------------------------------------------

    async def async_send_command(self, command: str) -> None:
        """Send a raw ASCII command to the lamp."""
        await self._device.send(command)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_set_pixel(self, index: int, color: list[int]) -> None:
        """Set one addressable LED (PIXEL command)."""
        await self._device.send(pixel_command(index, color))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_set_backled(self, section: int, color: list[int]) -> None:
        """Set a back-light section (BACKLED command)."""
        await self._device.send(backled_command(section, color))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_set_theme(
        self,
        theme: str,
        color: list[int] | None = None,
        color2: list[int] | None = None,
        color3: list[int] | None = None,
        color4: list[int] | None = None,
        color5: list[int] | None = None,
        color6: list[int] | None = None,
        speed: int | None = None,
    ) -> None:
        """Run a theme with user-chosen colours, validated against the catalog."""
        try:
            command = theme_command(
                theme, [color, color2, color3, color4, color5, color6], speed
            )
        except UnknownThemeError as err:
            raise ServiceValidationError(
                f"Onbekend thema '{theme}'. Zie de themacatalogus in const.py."
            ) from err
        except NotEnoughColorsError as err:
            raise ServiceValidationError(
                f"Thema {err.code} vereist {err.needed} kleuren; "
                f"{err.given} opgegeven."
            ) from err

        await self._reset_before_theme()
        await self._device.send(command)
        self._attr_effect = None
        self._attr_is_on = True
        self.async_write_ha_state()
