Triad AMS for Home Assistant [![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
============================

A custom Home Assistant integration for controlling a Triad AMS 8x8 audio matrix switch over TCP. The integration exposes one media player entity per active output zone and lets you select a routed input, adjust volume, and optionally mirror metadata from an upstream media player entity.

Attribution: The device protocol and command bytes used by this integration were derived from the excellent work by Tim Weiler — https://github.com/tim-weiler/triad-audio-matrix. Thank you Tim!

Status
------
- Supported hardware: Triad AMS 8x8 (Audio Matrix Switch)
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
  - Choose which outputs and inputs are active
  - Optionally set a link for each input
- Safe device handling
  - Serialized command writes
  - Trigger zone on when the first output is routed; off when the last output disconnects
  - Remembers and restores the last input when a zone is turned back on

Installation (HACS)
-------------------
This repository is designed to be installed via HACS as a custom repository.

- HACS quick‑add link:
  - https://my.home-assistant.io/redirect/hacs_repository/?owner=bharat&repository=homeassistant-triad-ams&category=integration
- Or, in Home Assistant:
  1. HACS → Integrations → “+” → Three‑dot menu → “Custom repositories”
  2. URL: https://github.com/bharat/homeassistant-triad-ams • Category: Integrations → Add
  3. Search for “Triad AMS” → Install
  4. Restart Home Assistant if prompted

Manual install (without HACS)
-----------------------------
- Copy the `custom_components/triad_ams` folder from this repository into your Home Assistant `config/custom_components/` directory
- Restart Home Assistant

Configuration
-------------
1. Settings → Devices & Services → “Add Integration” → search for “Triad AMS”
2. Enter the Triad AMS host/IP and port (default 52000)
3. In the next step:
   - Active Outputs: select which zones you want entities for
   - Active Inputs: select which inputs are usable as sources
   - Optional “link_input_<n>”: choose a `media_player` entity to mirror metadata when that input is routed
4. Save. The entry reloads and entities are created for active outputs only

Notes
-----
- You can rename outputs (zones) and set areas from each entity’s settings page
- If you later change the active lists or links in Options, the integration reloads and updates entities automatically

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
