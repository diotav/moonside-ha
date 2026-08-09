"""Pure builders for the Moonside BLE command strings.

Kept free of Home Assistant imports so the protocol logic can be unit-tested in
isolation. See the command set at developer.moonside.design.
"""

from __future__ import annotations

from collections.abc import Sequence

from .const import (
    THEME_COLORS,
    THEME_DEFAULT_SPEED,
    THEME_NO_COLOR_PARAM,
    THEME_SPEED_ONLY,
)

RGB = Sequence[int]


class UnknownThemeError(ValueError):
    """Raised when a theme code is not in the catalog."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class NotEnoughColorsError(ValueError):
    """Raised when fewer colours are given than a theme requires."""

    def __init__(self, code: str, needed: int, given: int) -> None:
        self.code = code
        self.needed = needed
        self.given = given
        super().__init__(f"{code} needs {needed} colours, got {given}")


def brightness_to_pct(brightness: int) -> int:
    """Map HA brightness (0-255) to the device's 10-100 range."""
    return max(10, min(100, round(brightness / 255 * 100)))


def color_command(rgb: RGB) -> str:
    """COLOR RRRGGGBBB, each channel padded to three decimal digits."""
    r, g, b = rgb
    return f"COLOR{r:03d}{g:03d}{b:03d}"


def pixel_command(index: int, rgb: RGB) -> str:
    """PIXEL,index,RRRGGGBBB, for one addressable LED."""
    r, g, b = rgb
    return f"PIXEL,{index},{r:03d}{g:03d}{b:03d},"


def backled_command(section: int, rgb: RGB) -> str:
    """BACKLEDn,0,RRRGGGBBB, for a back-light section (middle field unused)."""
    r, g, b = rgb
    return f"BACKLED{section},0,{r:03d}{g:03d}{b:03d},"


def theme_command(
    theme: str,
    colors: Sequence[RGB | None] = (),
    speed: int | None = None,
) -> str:
    """Build ``THEME.CODE.payload,`` for a theme, validated against the catalog.

    ``colors`` is an ordered list of RGB triplets; ``None`` entries are skipped so
    callers can pass optional slots straight through. Speed-only themes use
    ``speed`` (or the default) instead of colours; colourless themes take a fixed
    parameter. Raises :class:`UnknownThemeError` or :class:`NotEnoughColorsError`.
    """
    code = theme.strip().upper()
    needed = THEME_COLORS.get(code)
    if needed is None:
        raise UnknownThemeError(code)

    if code in THEME_SPEED_ONLY:
        payload = str(speed if speed is not None else THEME_DEFAULT_SPEED)
    elif needed == 0:
        payload = THEME_NO_COLOR_PARAM
    else:
        given = [c for c in colors if c is not None]
        if len(given) < needed:
            raise NotEnoughColorsError(code, needed, len(given))
        params: list[int] = []
        for c in given[:needed]:
            params += list(c)
        payload = ",".join(str(v) for v in params)

    return f"THEME.{code}.{payload},"
