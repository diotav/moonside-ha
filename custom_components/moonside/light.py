"""Light platform for the Moonside integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

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
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN,
    EFFECTS,
    THEME_COLORS,
    THEME_DEFAULT_SPEED,
    THEME_NO_COLOR_PARAM,
    THEME_SPEED_ONLY,
)
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


def _brightness_to_pct(brightness: int) -> int:
    """Map HA brightness (0-255) to the device's 10-100 range."""
    return max(10, min(100, round(brightness / 255 * 100)))


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
        """Restore the last assumed state across restarts.

        The lamp keeps its own state while Home Assistant is down, so this only
        realigns HA's optimistic view — no command is sent to the device.
        """
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is None:
            return

        self._attr_is_on = last.state == STATE_ON
        if (brightness := last.attributes.get(ATTR_BRIGHTNESS)) is not None:
            self._attr_brightness = brightness
        if (rgb := last.attributes.get(ATTR_RGB_COLOR)) is not None:
            self._attr_rgb_color = tuple(rgb)
        self._attr_effect = last.attributes.get(ATTR_EFFECT)

    async def async_turn_on(self, **kwargs: Any) -> None:
        effect = kwargs.get(ATTR_EFFECT)
        rgb = kwargs.get(ATTR_RGB_COLOR)
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        was_on = self._attr_is_on

        setting_effect = effect is not None and effect in EFFECTS
        setting_color = not setting_effect and rgb is not None
        rgb = tuple(rgb) if rgb is not None else None

        # Turn the lamp on explicitly only when nothing below will do so
        # implicitly (a COLOR or theme write already powers it on).
        if not was_on and not setting_effect and not setting_color:
            await self._device.send("LEDON")

        # Brightness goes out before colour so the colour fade is always the
        # last write. A BRIGH landing mid-transition makes the firmware abort
        # the fade at the wrong hue (e.g. orange -> yellow). Re-sending a value
        # the lamp already holds would restart that fade for nothing, so skip
        # writes that match the current assumed state.
        if brightness is not None:
            if not was_on or brightness != self._attr_brightness:
                await self._device.send(f"BRIGH{_brightness_to_pct(brightness)}")
            self._attr_brightness = brightness

        if setting_effect:
            if not was_on or effect != self._attr_effect:
                await self._device.send(EFFECTS[effect])
            self._attr_effect = effect
        elif setting_color:
            if not was_on or rgb != self._attr_rgb_color:
                r, g, b = rgb
                await self._device.send(f"COLOR{r:03d}{g:03d}{b:03d}")
            self._attr_rgb_color = rgb
            self._attr_effect = None

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
        code = theme.strip().upper()
        needed = THEME_COLORS.get(code)
        if needed is None:
            raise ServiceValidationError(
                f"Onbekend thema '{theme}'. Zie de themacatalogus in const.py."
            )

        if code in THEME_SPEED_ONLY:
            payload = str(speed if speed is not None else THEME_DEFAULT_SPEED)
        elif needed == 0:
            payload = THEME_NO_COLOR_PARAM
        else:
            given = [
                c
                for c in (color, color2, color3, color4, color5, color6)
                if c is not None
            ]
            if len(given) < needed:
                raise ServiceValidationError(
                    f"Thema {code} vereist {needed} kleuren; "
                    f"{len(given)} opgegeven."
                )
            params: list[int] = []
            for c in given[:needed]:
                params += list(c)
            payload = ",".join(str(v) for v in params)

        await self._device.send(f"THEME.{code}.{payload},")
        self._attr_effect = None
        self._attr_is_on = True
        self.async_write_ha_state()
