# Triad AMS16v2 — Compiled Command Reference

A single, dense reference table of every command frame the Core5/driver
sends to the Triad AMS16v2 over TCP port 52000, compiled from all resources
in this project:

- **pcap** — SPAN-port packet captures in `pcap_captures/*.pcap` (see
  `TRIAD_AMS16V2_PROTOCOL_SPEC.md` for full decode methodology and worked
  examples)
- **driver.lua** — the vendor's own Lua implementation, unpacked from
  `../TriadAMSv2_Driver/triad_ams16.c4z` into
  `../TriadAMSv2_Driver/extracted/driver.lua` (`ariel_commands` table,
  roughly lines 508-730, plus the `ariel_protocol.*` functions that use it)

Each row cites where it came from. `pcap+driver` means both agree exactly.
`driver only` means it was never exercised in a capture — see
`TRIAD_AMS16V2_FEATURE_GAPS.md` for the analysis of those. This file is a
flat reference; for encodings, framing rules, and worked examples, see
`TRIAD_AMS16V2_PROTOCOL_SPEC.md`.

**Frame shape:** `FF <GG> <LL> <payload>` — `GG`=`0x55` or `0x56` group
byte, `LL`=payload length, `ii`=0-based channel index, `vv`=1-byte value,
`F5`=GET sentinel, `<4B>`=4-byte big-endian value field. Response column
shows the literal (or templated) ASCII text the device replies with, where
known.

---

## Power / Network / System

| Command | Frame | Payload / Notes | Response | Source |
|---|---|---|---|---|
| Power On | `FF 55 02 01 01` | no params | — | driver only |
| Power Off | `FF 55 02 01 02` | defined but never called by driver (turn-on delay too long) | — | driver only |
| Power Toggle | `FF 55 02 01 03` | defined but never called by driver | — | driver only |
| Get Power Status (poll) | `FF 55 03 01 01 F5` | sent continuously as heartbeat | `Get Power status : Working` / `Standby` | pcap+driver |
| Network Standby On | `FF 55 03 08 83 01` | | `Auto Standby On` (inferred, unconfirmed text) | driver only (byte-confirms spec's prior best-guess) |
| Network Standby Off | `FF 55 03 08 83 00` | sent on every net connect | `Auto Standby Off` | pcap+driver |
| Get MAC Address | `FF 55 03 08 80 F5` | last command in diagnostic sequence; its reply ends the diag capture | contains `Get MAC Add...` | driver only |
| Get Firmware Version | `FF 55 03 06 65` | payload is only 2 bytes (`06 65`) despite `LL=03` — confirmed vendor quirk, not a capture artifact | `Fw version : V1.0054` | pcap+driver |
| Firmware Update (push) | `FF 56 <len> 06 01 <URL as ASCII>` | `len = 2 + strlen(url)`; device fetches the firmware file itself via HTTP GET from the given URL (hosted by the C4 controller) | — | driver only |
| Reboot | `FF 55 03 06 B4 00` | | `Reboot Command` | pcap+driver |
| Factory Reset | `FF 55 02 0B B0` | | `Factory Reset Command` | pcap+driver |
| Get Web-UI Credentials | `FF 56 03 06 02 F5` | global, no channel index | `Get Credentials: ... username->USER, passwd->PASS ...` (**plaintext password**) | driver only |
| Set Web-UI Credentials | `FF 56 <len> 06 02 <ulen:1B> <username> <plen:1B> <password>` | `len = ulen+plen+4`; password must be 8-32 chars, restricted charset | `set Credential success` | driver only |
| Get IP Assignment Method | `FF 55 03 08 81 F5` | | (unconfirmed; parsed as `DHCP ON` / `IP STATIC`-style text) | driver only |
| Set IP to DHCP | `FF 55 02 08 81` | | `DHCP ON`-style text | driver only |
| Set Static IP | `FF 55 0E 08 82 <4B ip> <4B mask> <4B gateway>` | each octet is 1 raw byte, no delimiters | `IP STATIC`-style text | driver only |
| Get IP Address (dead code) | *(references `ariel_commands.getIpAddress`, which is never assigned a value anywhere in `driver.lua`)* | `ariel_protocol.getIpAddress()` sends an undefined/nil command — appears to be dead/broken code, superseded by `getIpMethod` | — | driver only, **broken** |
| Get Auto-Sense (global) | `FF 55 04 0A A2 <00off/01on> FF` (SET) | trailing `FF` fixed suffix, not index | `Set AUTO SENSE On`/`Off` | pcap+driver |
| Get Auto-Sense (per-channel query form) | `FF 55 04 0A A2 F5 ii` | | `Get AUTO SENSE :On` | pcap+driver |
| Get per-input Auto-Sense flag | `FF 55 04 0A A0 F5 ii` | | `AudioSense:Input[n]: 0/1` | pcap+driver |
| Set Auto-Sense Off-Delay | `FF 55 04 0A A3 00 <delay:1B>` | 2nd byte would be a high byte of a 16-bit delay per comment, but driver only ever sends low byte | — | driver only |
| Poll Audio Sense | `FF 56 04 02 03 F5 ii` | queried for all inputs on connect | `Get Input[n] Audio Detect Detected`/`Undetected` | pcap+driver |

---

## Input Configuration (per input, `ii` = 0x00-0x0F)

| Command | Frame | Payload / Notes | Response | Source |
|---|---|---|---|---|
| Set Input Gain | `FF 55 04 02 04 ii vv` | `vv = (gain_dB + 12) * 2`, 0-48 (0x00-0x30) | `Set In[n] input gain : X` | pcap+driver |
| Get Input Gain | `FF 55 04 02 04 F5 ii` | | `Get In[n] input gain : X` | pcap+driver |
| Set Input Delay | `FF 56 04 02 04 ii vv` | `vv` = raw ms, 0-80 | `Set Input[n] Delay X` | pcap+driver |
| Get Input Delay | `FF 56 04 02 04 F5 ii` | | `Get Input[n] Delay X` | pcap+driver |

---

## Output Configuration (per output, `ii` = 0x00-0x0F)

| Command | Frame | Payload / Notes | Response | Source |
|---|---|---|---|---|
| Set Output Source | `FF 55 04 03 1D ii vv` | `vv` = 0-based source input index | `Set Out[n] Input Source to input X` | pcap+driver |
| Get Output Source | `FF 55 04 03 1D F5 ii` | | `Get Out[n] Input Source : ...` / `Audio Off` if disconnected | pcap+driver |
| Disconnect Output (16-output models) | `FF 55 04 03 1D ii 10` | same opcode as Set Output Source; value `16` (decimal) = disconnect sentinel | `Set Out[n] Input Source to input 16`-shaped text, drives to "Audio Off" state | driver only |
| Disconnect Output (8-output models) | `FF 55 04 03 1D ii 08` | value `8` (decimal) = disconnect sentinel on 8-output models | (same) | driver only |
| Set Output Delay | `FF 56 04 03 09 ii vv` | `vv` = raw ms, 0-80 | `Set Output[n] Delay X` | pcap+driver |
| Get Output Delay | `FF 56 04 03 09 F5 ii` | | `Get Output[n] Delay X` | pcap+driver |
| Set Output Mode | `FF 56 04 03 0B ii vv` | `vv`: `0`=DSP Bypass Stereo, `1`=Stereo, `2`=Mono, `3`=**2.1 Stereo**, `4`=**2.1 Mono**, `5`=Test Signal | `Set Out[n] Select:<mode>` | pcap (0,1,2,5)+driver; **3,4 driver only** |
| Get Output Mode | `FF 56 04 03 0B F5 ii` | | `Get Out[n] Select:<mode>` | driver only |
| Set Output Mute On | `FF 55 03 03 17 ii` | | `Set Out[n] Mute` | pcap+driver |
| Set Output Mute Off | `FF 55 03 03 18 ii` | | `Set Out[n] Unmute` | pcap+driver |
| Get Mute Status | `FF 55 04 03 17 F5 ii` | | `Get Out[n] Mute status : Mute/Unmute` | pcap+driver |
| Set Output Volume | `FF 55 04 03 1E ii vv` | `vv` = 0-100 (0x00-0x64) UI value; see full dB table in Protocol Spec §3.1 | `Set Out[n] Output Volume to X` | pcap+driver |
| Get Output Volume | `FF 55 04 03 1E F5 ii` | | `Get Out[n] Volume : X` | pcap+driver |
| Set Max Volume | `FF 55 04 03 1F ii vv` | 0-100 scale | `Set Out[n] Max Volume to X` | pcap+driver |
| Get Max Volume | `FF 55 04 03 1F F5 ii` | | `Get Out[n] Max Volume : X` | pcap+driver |
| Set Turn-On (Start) Volume | `FF 55 04 03 33 ii vv` | 0-100 scale | `Set Out[n] Turn on Vol to X` | pcap+driver |
| Get Turn-On (Start) Volume | `FF 55 04 03 33 F5 ii` | | `Get Out[n] Turn on Vol : X` | driver only |
| Set Output Balance | `FF 55 04 03 31 ii vv` | `vv` = 0x00 (L12) .. 0x18 (center) .. 0x30 (R12) | `Set Out[n] Balance to Bal L/R/Center` | pcap+driver |
| Get Output Balance | `FF 55 04 03 31 F5 ii` | | `Get Out[n] Balance : ...` | driver only |
| Set Output Loudness On | `FF 55 03 03 1A ii` | | `Set Out[n] Loudness On` | pcap+driver |
| Set Output Loudness Off | `FF 55 03 03 1B ii` | | `Set Out[n] Loudness Off` | pcap+driver |
| Get Output Loudness | `FF 55 04 03 1A F5 ii` | | `Get Out[n] Loudness : On/Off` | driver only |
| Set Test-Tone Volume | `FF 56 04 04 01 ii vv` | `vv` scaled like volume, -24 to 0 dB | `Set Out[n] Test Gain X` | pcap+driver |

---

## Legacy / Parallel Command Paths (superseded but device still accepts them)

| Command | Frame | Notes | Source |
|---|---|---|---|
| Old Set Stereo | `FF 55 03 03 10 ii` | pre-dates `setOutputMode` | driver only |
| Old Get Mono/Stereo | `FF 55 04 03 10 F5 ii` | | driver only |
| Old Set Mono | `FF 55 03 03 11 ii` | pre-dates `setOutputMode` | driver only |
| Old Set Bass (flat gain) | `FF 55 04 03 2F ii vv` | `vv` = 0x00(-12dB)-0x18(0dB)-0x30(+12dB); pre-dates frequency-adjustable Low Shelf | driver only |
| Old Get Bass | `FF 55 04 03 2F F5 ii` | | driver only |
| Old Set Treble (flat gain) | `FF 55 04 03 30 ii vv` | same encoding as old Bass; pre-dates High Shelf | driver only |
| Old Get Treble | `FF 55 04 03 30 F5 ii` | | driver only |

### Commented-out in driver source (dead code — documented, not sent by any shipped version)

| Command | Frame | Source |
|---|---|---|
| Toggle Output Mono | `FF 55 03 03 12 ii` | driver only, commented out |
| Toggle Output Mute | `FF 55 03 03 19 ii` | driver only, commented out |
| Volume Up (single step) | `FF 55 03 03 13 ii` | driver only, commented out |
| Volume Down (single step) | `FF 55 03 03 14 ii` | driver only, commented out |
| Volume Up ×3 | `FF 55 03 03 15 ii` | driver only, commented out |
| Volume Down ×3 | `FF 55 03 03 16 ii` | driver only, commented out |
| Toggle Output Loudness | `FF 55 03 03 1C ii` | driver only, commented out |

---

## Tone Control — Shelving Filters (per output, `ii`)

| Command | Frame | Payload / Notes | Response | Source |
|---|---|---|---|---|
| Set Low Shelf Frequency | `FF 56 07 03 03 ii <4B Hz>` | 20-2000 Hz | `Set Out[n] Low Shelf Frequency to X Hz` | pcap+driver |
| Get Low Shelf Frequency | `FF 56 04 03 03 F5 ii` | note GET uses group-`04` short form, not `07` | `Get Out[n] Low Shelf Frequency : X Hz` | driver only |
| Set Low Shelf Gain | `FF 56 07 03 0D ii <4B ×100>` | ±12.00 dB, signed | `Set Out[n] Low Shelf gain to X` | pcap+driver |
| Get Low Shelf Gain | `FF 56 07 03 0D F5 ii` | | `Get Out[n] Low Shelf gain : X` | driver only |
| Set Low Shelf Q | `FF 56 07 03 04 ii <4B ×100>` | 0.5-15.0; default 0.58 | — | **driver only, missing from spec** |
| Get Low Shelf Q | `FF 56 07 03 04 F5 ii` | | — | driver only |
| Set High Shelf Frequency | `FF 56 07 03 01 ii <4B Hz>` | 20-20000 Hz | `Set Out[n] High Shelf Frequency to X Hz` | pcap+driver |
| Get High Shelf Frequency | `FF 56 07 03 01 F5 ii` | | `Get Out[n] High Shelf Frequency : X Hz` | driver only |
| Set High Shelf Gain | `FF 56 07 03 0C ii <4B ×100>` | ±12.00 dB, signed | `Set Out[n] High Shelf gain to X` | pcap+driver |
| Get High Shelf Gain | `FF 56 07 03 0C F5 ii` | | `Get Out[n] High Shelf gain : X` | driver only |
| Set High Shelf Q | `FF 56 07 03 02 ii <4B ×100>` | 0.5-15.0; default 0.58 | — | **driver only, missing from spec** |
| Get High Shelf Q | `FF 56 04 03 02 F5 ii` | note GET uses group-`04` short form | — | driver only |

---

## 2.1 Audio Zone / Crossover (per **primary** output, `ii`)

Sent to the primary output's channel index, not the paired sub output. The
pairing relationship itself (which output is "sub" for which) is
Composer-side state, never sent to the device — only these three settings
are real device commands:

| Command | Frame | Payload / Notes | Source |
|---|---|---|---|
| Set Crossover Frequency | `FF 56 07 03 05 ii <4B Hz>` | default 80 Hz | driver only |
| Get Crossover Frequency | `FF 56 07 03 05 F5 ii` | | driver only |
| Set Crossover Type/Slope | `FF 56 04 03 06 ii vv` | `vv`: `0`=Butterworth 12dB, `1`=Butterworth 24dB, `2`=Butterworth 48dB, `3`=Linkwitz-Riley 12dB, `4`=Linkwitz-Riley 24dB (default), `5`=Linkwitz-Riley 48dB | driver only |
| Get Crossover Type/Slope | `FF 56 04 03 06 F5 ii` | | driver only |
| Set Sub-Output Volume Offset | `FF 56 04 03 07 ii vv` | `vv = 24 + (offset_dB * 2)`, same ±12dB/0.5-step encoding as balance; default 0 | driver only |
| Get Sub-Output Volume Offset | `FF 56 04 03 07 F5 ii` | | driver only |

---

## Room / Speaker Equalizer — 12 Bands (per output, `ii`)

Band selector byte = `((band_number - 1) << 4) | param`, `param`:
`0`=Freq, `1`=Gain, `2`=Q. **Bands 1-6 are the Speaker EQ** (used by Speaker
Presets); **bands 7-12 are the Room EQ** (the user-adjustable "Room
equalizer" graph) — confirmed by driver diagnostic-log section labels
(`---------- Speaker EQs ----------` triggers on "Band 1", `---------- Room
EQs ----------` triggers on "Band 7"). This is the reverse of what the
Protocol Spec's §4.6 narrative currently says (band-selector math itself is
correct and unaffected).

| Command | Frame | Payload / Notes | Response | Source |
|---|---|---|---|---|
| Set Band N Frequency | `FF 56 07 05 <sel+0> ii <4B Hz>` | 20-20000 Hz | `Set Out[n] Band N Freq to X Hz` | pcap+driver |
| Get Band N Frequency | `FF 56 04 05 <sel+0> F5 ii` | | `Get Out[n] Band N Freq : X Hz` | pcap+driver |
| Set Band N Gain | `FF 56 07 05 <sel+1> ii <4B ×100>` | ±12.00 dB, signed | `Set Out[n] Band N Gain to X` | pcap+driver |
| Get Band N Gain | `FF 56 04 05 <sel+1> F5 ii` | | `Get Out[n] Band N Gain : X` | pcap+driver |
| Set Band N Q | `FF 56 07 05 <sel+2> ii <4B ×100>` | 0.5-15.0 | `Set Out[n] Band N Q to X` | pcap+driver |
| Get Band N Q | `FF 56 04 05 <sel+2> F5 ii` | | `Get Out[n] Band N Q : X` | pcap+driver |
| Lock Room EQ | `FF 56 04 03 08 ii 01` | | `Set Out[n] Lock Room EQ On` | driver only (SET-locked form) |
| Unlock Room EQ | `FF 56 04 03 08 ii 00` | | `Set Out[n] Lock Room EQ Off` | pcap+driver |
| Query Room EQ Lock State | `FF 56 04 03 08 F5 ii` | | `Get Out[n] Lock Room EQ : On/Off` | driver only |

Band-selector byte table (`sel` above):

| Band | Freq | Gain | Q | EQ type |
|---|---|---|---|---|
| 1 | `0x00` | `0x01` | `0x02` | Speaker EQ |
| 2 | `0x10` | `0x11` | `0x12` | Speaker EQ |
| 3 | `0x20` | `0x21` | `0x22` | Speaker EQ |
| 4 | `0x30` | `0x31` | `0x32` | Speaker EQ |
| 5 | `0x40` | `0x41` | `0x42` | Speaker EQ |
| 6 | `0x50` | `0x51` | `0x52` | Speaker EQ |
| 7 | `0x60` | `0x61` | `0x62` | Room EQ |
| 8 | `0x70` | `0x71` | `0x72` | Room EQ |
| 9 | `0x80` | `0x81` | `0x82` | Room EQ |
| 10 | `0x90` | `0x91` | `0x92` | Room EQ |
| 11 | `0xA0` | `0xA1` | `0xA2` | Room EQ |
| 12 | `0xB0` | `0xB1` | `0xB2` | Room EQ |

**No "load preset" opcode exists.** FLAT/CLASSICAL/JAZZ/POP/ROCK-style
presets (both Speaker and Room EQ) are applied by the driver sending the
individual per-band Freq/Gain/Q SET commands above — confirmed by
`SetEQPreset()` in `driver.lua`. Preset value tables are in
`../TriadAMSv2_Driver/extracted/www/EQ/SpeakerPresets.json` and
`RoomEQPresets.json` if exact replication is wanted.

---

## Triggers / Zones (12V relay outputs — real, settable, not passive status)

| Command | Frame | Response | Source |
|---|---|---|---|
| Zone 1-8 Trigger ON | `FF 55 03 05 50 00` | `Set Zone :1-8 ON` | pcap+driver |
| Zone 1-8 Trigger OFF | `FF 55 03 05 51 00` | `Set Zone :1-8 OFF` | pcap+driver |
| Zone 9-16 Trigger ON | `FF 55 03 05 50 01` | `Set Zone :9-16 ON` | pcap+driver |
| Zone 9-16 Trigger OFF | `FF 55 03 05 51 01` | `Set Zone :9-16 OFF` | pcap+driver |
| ASG Trigger ON | `FF 55 03 05 50 02` | `Set ASG ON` | pcap+driver |
| ASG Trigger OFF | `FF 55 03 05 51 02` | `Set ASG OFF` | pcap+driver |

Note: on the 8-output model (`triad_ams8_v2`), the driver reuses the "Zone
9-16" byte pattern (`FF 55 03 05 50/51 01`) for its ASG trigger instead —
model-dependent remapping, per `TRIGGER_COMMANDS` table in `driver.lua`.

---

## Diagnostic Capture Sequence

`ariel_protocol.sendGetDiagnosticCommands()` fires this exact sequence of
already-listed GET commands for every input and output in turn (Get Input
Gain, Get Input Delay, Poll Audio Sense, per-input Auto-Sense query ×2 —
then for outputs: Get Output Source, Get Output Delay, plus the rest of the
per-output GET commands above), finishing with Get MAC Address as the
sentinel that ends the capture. No new opcodes here beyond what's already
listed above — included for completeness since it's the mechanism behind
the Core4 "Gather Diagnostic Data" button (`core5_gather_diag_data.txt` /
`.pcap`).

---

## Source Index

- `pcap_captures/*.pcap` — see `TRIAD_AMS16V2_PROTOCOL_SPEC.md` §1 for the
  full file list and capture provenance.
- `../TriadAMSv2_Driver/extracted/driver.lua` — `ariel_commands` table
  (~lines 508-730), `ariel_protocol.*` functions, `SetEQ_*`/`SetEQPreset`
  (~line 1542+), `updateTwoPointOneAudioZone`/`SetPairs*` (~line 3870,
  5759+), trigger functions (~line 1214+).
- No files under `pcap_captures/` or `TriadAMSv2_Driver/` were modified to
  produce this document.
