"""Constants for the Moonside integration."""

from __future__ import annotations

DOMAIN = "moonside"

# Nordic UART Service (developer.moonside.design)
UART_WRITE_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
# Read characteristic returns "version|mac", e.g. "1.0|AA:BB:CC:DD:EE:FF".
UART_READ_CHAR_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

# Keep the BLE connection open this many seconds after the last write,
# then disconnect so the proxy connection slot is freed when idle.
IDLE_DISCONNECT_SECONDS = 30

# Minimum seconds between consecutive writes, kept as a small safety buffer.
# The real serialisation comes from writing with an ATT response (see
# MoonsideDevice.send); this only guards against the firmware needing a brief
# pause to settle an animation transition between commands.
MIN_WRITE_INTERVAL = 0.12

# Seconds to wait after the first COLOR write that replaces a running theme
# before re-sending it. A static colour applied over a live animation lands on
# the wrong hue (e.g. orange -> yellow); the animation needs a moment to stop
# before the colour sticks. Only used when switching away from an effect.
COLOR_SETTLE = 0.4

# Quick presets shown in the light card's effect list. Name -> full command.
# These use baked-in colours; use the moonside.set_theme service to pick your own.
EFFECTS: dict[str, str] = {
    "Rainbow": "THEME.RAINBOW1.20,",
    "Rainbow flow": "THEME.RAINBOW2.20,",
    "Rainbow cycle": "THEME.RAINBOW3.0,",
    "Fire": "THEME.FIRE1.0,",
    "Gradient": "THEME.GRADIENT1.255,80,0,0,120,255,",
    "Gradient trio": "THEME.GRADIENT2.255,80,0,0,120,255,255,255,255,",
    "Twinkle": "THEME.TWINKLE1.255,255,255,0,120,255,",
    "Pulse": "THEME.PULSING1.255,80,0,0,120,255,",
    "Wave": "THEME.WAVE1.255,80,0,0,120,255,",
    "Lava": "THEME.LAVA1.255,60,0,180,0,0,255,180,40,",
    "Palette": "THEME.PALETTE1.0,",
    "Music": "THEME.M9.255,140,0,255,0,128,",
}

# Number of RGB colour triplets each theme consumes, per the theme catalog
# at developer.moonside.design. 0 = theme takes no colour input.
THEME_COLORS: dict[str, int] = {
    "RAINBOW1": 0,
    "RAINBOW2": 0,
    "RAINBOW3": 0,
    "FIRE1": 0,
    "FIRE2": 4,
    "THEME1": 2,
    "THEME2": 2,
    "THEME3": 6,
    "THEME4": 2,
    "THEME5": 2,
    "COLORDROP1": 2,
    "GRADIENT1": 2,
    "GRADIENT2": 3,
    "GRADIENT3": 2,
    "TWINKLE1": 2,
    "PULSING1": 2,
    "PALETTE1": 0,
    "PALETTE2": 6,
    "BEAT1": 3,
    "BEAT2": 2,
    "BEAT3": 3,
    "WAVE1": 2,
    "LAVA1": 3,
    "M1": 2,
    "M2": 3,
    "M3": 2,
    "M4": 2,
    "M5": 2,
    "M6": 2,
    "M7": 2,
    "M8": 3,
    "M9": 2,
    "M10": 3,
    "M11": 3,
    "M12": 2,
}

# Themes whose single numeric parameter is an animation speed, not a colour.
THEME_SPEED_ONLY = {"RAINBOW1", "RAINBOW2"}

# Default trailing parameter for colourless themes (RAINBOW3/FIRE1/PALETTE1).
THEME_NO_COLOR_PARAM = "0"
# Default speed for the speed-only rainbow themes when none is given.
THEME_DEFAULT_SPEED = 20
