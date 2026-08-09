"""Unit tests for the pure Moonside command builders."""

from __future__ import annotations

import pytest

from custom_components.moonside.commands import (
    NotEnoughColorsError,
    UnknownThemeError,
    backled_command,
    brightness_to_pct,
    color_command,
    pixel_command,
    theme_command,
)


@pytest.mark.parametrize(
    ("brightness", "expected"),
    [
        (0, 10),  # clamped up to the device minimum
        (3, 10),  # 1% rounds below the floor -> clamped
        (128, 50),
        (191, 75),
        (255, 100),
    ],
)
def test_brightness_to_pct(brightness: int, expected: int) -> None:
    assert brightness_to_pct(brightness) == expected


def test_color_command_pads_each_channel() -> None:
    assert color_command((255, 147, 0)) == "COLOR255147000"
    assert color_command((0, 0, 0)) == "COLOR000000000"


def test_pixel_command() -> None:
    assert pixel_command(42, (255, 0, 128)) == "PIXEL,42,255000128,"
    assert pixel_command(0, (1, 2, 3)) == "PIXEL,0,001002003,"


def test_backled_command_has_unused_middle_field() -> None:
    assert backled_command(1, (50, 50, 50)) == "BACKLED1,0,050050050,"
    assert backled_command(2, (255, 0, 0)) == "BACKLED2,0,255000000,"


def test_theme_colourless_uses_fixed_param() -> None:
    assert theme_command("FIRE1") == "THEME.FIRE1.0,"
    assert theme_command("RAINBOW3") == "THEME.RAINBOW3.0,"


def test_theme_speed_only() -> None:
    assert theme_command("RAINBOW1") == "THEME.RAINBOW1.20,"  # default speed
    assert theme_command("RAINBOW2", speed=5) == "THEME.RAINBOW2.5,"


def test_theme_with_colours() -> None:
    assert (
        theme_command("GRADIENT1", [(255, 0, 0), (0, 0, 255)])
        == "THEME.GRADIENT1.255,0,0,0,0,255,"
    )


def test_theme_ignores_extra_colours() -> None:
    # GRADIENT1 needs 2; the third colour is dropped.
    assert (
        theme_command("GRADIENT1", [(1, 1, 1), (2, 2, 2), (9, 9, 9)])
        == "THEME.GRADIENT1.1,1,1,2,2,2,"
    )


def test_theme_skips_none_slots() -> None:
    # Optional slots passed as None must not count or shift the colours.
    assert (
        theme_command("GRADIENT1", [None, (1, 1, 1), None, (2, 2, 2)])
        == "THEME.GRADIENT1.1,1,1,2,2,2,"
    )


def test_theme_normalises_code() -> None:
    assert theme_command(" gradient1 ", [(1, 1, 1), (2, 2, 2)]).startswith(
        "THEME.GRADIENT1."
    )


def test_theme_unknown_raises() -> None:
    with pytest.raises(UnknownThemeError):
        theme_command("NOPE1", [(1, 1, 1), (2, 2, 2)])


def test_theme_too_few_colours_raises() -> None:
    with pytest.raises(NotEnoughColorsError) as excinfo:
        theme_command("GRADIENT2", [(1, 2, 3)])
    assert excinfo.value.needed == 3
    assert excinfo.value.given == 1


@pytest.mark.parametrize("code", ["FIRE1", "RAINBOW1", "GRADIENT1", "PIXEL"])
def test_all_builders_end_with_trailing_comma_where_documented(code: str) -> None:
    # Themes, pixels and back-LEDs use a trailing comma; COLOR does not.
    assert pixel_command(0, (0, 0, 0)).endswith(",")
    assert backled_command(1, (0, 0, 0)).endswith(",")
    assert not color_command((0, 0, 0)).endswith(",")
