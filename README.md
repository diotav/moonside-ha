# Moonside

Home Assistant integration for [Moonside](https://moonside.design) smart lighting
(Halo and other models), driven over Bluetooth LE using the documented Nordic UART
command set.

The integration is **write-only**: the lamp does not acknowledge commands, so the
state shown in Home Assistant is optimistic (`assumed_state`) — it reflects the last
command sent. If you also control the lamp with its physical buttons or the Moonside
app, Home Assistant's view can drift.

## Features

- A single `light` entity per lamp: on/off, brightness (HA 0–255 is scaled to the
  lamp's 10–100 range) and RGB colour.
- A quick **effect list** on the light card with baked-in colours (see `const.py`).
- Service **`moonside.set_theme`** — run any theme with your own colours. The number
  of colours each theme uses is validated against the catalog.
- Service **`moonside.send_command`** — send any raw ASCII command to the lamp.
- A diagnostic **firmware version** sensor, read once from the lamp on connect.

Colour and effect are mutually exclusive, just like on the device itself: choosing a
colour clears the active effect and vice versa.

## Requirements

- Home Assistant 2024.8 or newer.
- A working Bluetooth adapter or an ESPHome **Bluetooth proxy** within range of the
  lamp, with active connections enabled (the integration writes over BLE).
- The lamp advertises as `MOONSIDE-…`. It only advertises while **not** connected to
  another device, so disconnect any phone/app before adding it.

## Installation

### HACS (custom repository)

1. HACS → three-dot menu → **Custom repositories**.
2. Add this repository's URL with category **Integration**.
3. Install **Moonside** and restart Home Assistant.
4. **Settings → Devices & services**. The lamp is discovered automatically
   (`MOONSIDE-*`), or add it via **Add integration → Moonside**.

### Manual

Copy `custom_components/moonside/` into your Home Assistant `config/custom_components/`
folder and restart.

## Services

### `moonside.set_theme`

Run a theme with colours you choose. Target the light entity, pick a theme, and pass
as many colours as that theme uses.

```yaml
action: moonside.set_theme
target:
  entity_id: light.moonside_o101
data:
  theme: GRADIENT2
  color: [255, 0, 0]
  color2: [128, 0, 255]
  color3: [255, 255, 255]
```

Colours per theme:

| Colours | Themes |
| --- | --- |
| 0 (no colour) | `RAINBOW3`, `FIRE1`, `PALETTE1` |
| speed only | `RAINBOW1`, `RAINBOW2` (use the `speed` field) |
| 2 | `THEME1`, `THEME2`, `THEME4`, `THEME5`, `COLORDROP1`, `GRADIENT1`, `GRADIENT3`, `TWINKLE1`, `PULSING1`, `BEAT2`, `WAVE1`, `M1`, `M3`–`M7`, `M9`, `M12` |
| 3 | `GRADIENT2`, `BEAT1`, `BEAT3`, `LAVA1`, `M2`, `M8`, `M10`, `M11` |
| 4 | `FIRE2` |
| 6 | `THEME3`, `PALETTE2` |

Extra colours are ignored; too few returns an error.

### `moonside.send_command`

Send a raw ASCII command, for anything outside the structured service (or to
experiment with model-specific commands such as `PIXEL` / `BACKLED`).

```yaml
action: moonside.send_command
target:
  entity_id: light.moonside_o101
data:
  command: "THEME.GRADIENT1.255,0,0,128,0,255,"
```

## Notes and limitations

- **Write-only.** No acknowledgement or notification is returned, so state is
  assumed, not read back. The read characteristic only returns `version|mac`.
- **Colours are raw RGB.** There is no per-lamp calibration, gamma or white-balance
  correction, so a value that looks right on a calibrated lamp (e.g. Hue) will be
  close but rarely identical here.
- **Connection handling.** The BLE connection is opened on demand, reused, and
  dropped after 30 s idle so a shared proxy slot is freed. The first action after an
  idle period reconnects first, which can feel briefly unresponsive.
- **Not implemented.** `PIXEL` (per-LED array) and `BACKLED` (back sections) are
  documented as model-specific; use `send_command` to experiment.

## Protocol

Command set: <https://developer.moonside.design>. This project bundles no Moonside
artwork or assets; it only uses the publicly documented BLE command set and
nominative brand references.
