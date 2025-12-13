[![HACS](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration) [![Validate](https://github.com/bharat/homeassistant-triad-ams/actions/workflows/validate.yml/badge.svg?branch=main)](https://github.com/bharat/homeassistant-triad-ams/actions/workflows/validate.yml) [![Lint](https://github.com/bharat/homeassistant-triad-ams/actions/workflows/lint.yml/badge.svg?branch=main)](https://github.com/bharat/homeassistant-triad-ams/actions/workflows/lint.yml) [![Release](https://img.shields.io/github/v/release/bharat/homeassistant-triad-ams?sort=semver)](https://github.com/bharat/homeassistant-triad-ams/releases)

Triad AMS for Home Assistant
============================

A custom Home Assistant integration for controlling a Triad AMS 8x8 audio matrix switch over TCP. The integration exposes one media player entity per active output zone and lets you select a routed input, adjust volume, and optionally mirror metadata from an upstream media player entity.

Attribution: The device protocol and command bytes used by this integration were derived from the excellent work by Tim Weiler — https://github.com/tim-weiler/triad-audio-matrix. Thank you Tim!

Status
------
- Supported hardware:
  - Triad AMS 8x8 (Audio Matrix Switch)
  - Triad AMS 16x16 (Audio Matrix Switch)
  - Triad AMS 24x24 (Audio Matrix Switch)
- Transport: TCP (default port 52000)
- Discovery: Not implemented (manual host/port entry)

Features
--------
- One media player entity per active output (zone)
- Turn on/off a zone (routes/disconnects the source)
- Select source (routed input)
- Set volume per zone
- Optional input→entity linking
  - Link a Triad input to a Home Assistant `media_player` entity (e.g., Sonos)
  - Triad output entity proxies metadata (title/artist/album/artwork) from the linked player when that input is selected
- Simple config flow
  - Select device model (TS-AMS8, TS-AMS16, or TS-AMS24)
  - Choose which outputs and inputs are active
  - Optionally set a link for each input
- Safe device handling
  - Serialized command writes
  - Trigger zone on when the first output is routed; off when the last output disconnects
  - Remembers and restores the last input when a zone is turned back on

Installation (HACS)
-------------------
This integration is available directly in HACS under the Integration category.

1. In Home Assistant, go to HACS → Integrations.
2. Search for "Triad AMS" and install.
3. Restart Home Assistant when prompted

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=triad_ams)

Manual install (without HACS)
-----------------------------
- Copy the `custom_components/triad_ams` folder from this repository into your Home Assistant `config/custom_components/` directory
- Restart Home Assistant

Configuration
-------------
1. Settings → Devices & Services → “Add Integration” → search for “Triad AMS”
2. Enter the Triad AMS host/IP and port (default 52000), and select your device model (TS-AMS8, TS-AMS16, or TS-AMS24)
3. In the next step:
   - Active Outputs: select which zones you want entities for
   - Active Inputs: select which inputs are usable as sources
   - Optional “link_input_<n>”: choose a `media_player` entity to mirror metadata when that input is routed
4. Save. The entry reloads and entities are created for active outputs only

Notes
-----
- You can rename outputs (zones) and set areas from each entity’s settings page
- If you later change the active lists or links in Options, the integration reloads and updates entities automatically
- The device model selected during initial setup determines the number of available inputs and outputs

Limitations / Roadmap
---------------------
- Only tested with and officially supports the Triad AMS 8x8 model
- No automatic discovery (enter host/port manually)
- No push updates from the device; state is refreshed on demand and during actions
- Reconnect/backoff can be improved in future releases

Troubleshooting
---------------
- No inputs in the source list?
  - Make sure the inputs are marked active in Options
- Metadata not shown?
  - Set a `link_input_<n>` to the upstream player for that input; the Triad entity will proxy media fields only when linked and routed to that input
- Old output devices linger in the UI?
  - The integration prunes stale entities/devices on reload when outputs are deactivated. If you still see devices, check for disabled entities tied to them

Credits
-------
- Protocol reference and driver data: Tim Weiler — https://github.com/tim-weiler/triad-audio-matrix
- Integration author: @bharat (and contributors)

License
-------
This project inherits the license of this repository. See LICENSE for details.
