# Triad AMS16v2 — Feature Gaps: Spec vs. Vendor Driver

## Purpose

`TRIAD_AMS16V2_PROTOCOL_SPEC.md` was built entirely from SPAN-port packet
captures of a live Core5 controlling an AMS16v2. This document cross-checks
that spec against the **actual vendor driver source** found in
`../TriadAMSv2_Driver/extracted/driver.lua` (the unpacked Control4 `.c4z`
driver package, a 6300-line Lua file containing the real `ariel_protocol`
implementation — the `ariel_*.lua` stub files in that directory are empty;
all logic lives in `driver.lua`).

This is a **read-only comparison**. No files in `pcap_captures/` or
`TriadAMSv2_Driver/` were modified to produce it. It lists only:

1. Protocol commands/features that are real and used by the official driver
   but were **never observed in any packet capture**, so they're entirely
   absent from the spec (the actual gaps).
2. A couple of places where the spec's capture-based *inference* turned out
   to be backwards once checked against the driver source (corrections).

Anything already correctly documented in the spec, or already correctly
flagged there as an unresolved gap, is not repeated here except where the
driver source newly confirms or resolves it.

---

## 1. Commands with zero capture evidence — completely missing from the spec

These exist in `ariel_commands` / `ariel_protocol.*` in `driver.lua` but
never appeared in any `.pcap` file, so the spec has no record of them at all.

| Feature | Frame (from driver source) | Driver evidence |
|---|---|---|
| **Power On** | `FF 55 02 01 01` | `ariel_commands.powerOn`, called by `ariel_protocol.powerOn()` |
| **Power Off** | `FF 55 02 01 02` | `ariel_commands.powerOff` — driver comment notes it's defined but **unused** ("power on delay is TOO big... requires physically rebooting") |
| **Power Toggle** | `FF 55 02 01 03` | `ariel_commands.powerToggle` — comment: "Unknown, probably same" (never called anywhere in the driver) |
| **Get MAC Address** | `FF 55 03 08 80 F5` | `ariel_commands.getMACAddress`; issued as the last command in the diagnostic sequence — its response is literally used as the "diagnostics complete" end marker (`EndDiagnosticCapture()` fires when `"Get MAC Add"` is seen) |
| **Network Standby On** | `FF 55 03 08 83 01` | `ariel_commands.networkStandbyOn` — **confirms** the spec's §4.1 best-guess (`FF 55 03 08 83 01`) was exactly correct; can be promoted from "unverified" to confirmed |
| **Get Web-UI Credentials** | `FF 56 03 06 02 F5` | `ariel_commands.getCredentials` — queries whether/what login credentials are set for the device's own web UI (port 3000) |
| **Set Web-UI Credentials** | `FF 56 <len> 06 02 <ulen 1B> <username> <plen 1B> <password>` | `ariel_protocol.setCredentials(username, password)`. `total_len = ulen+plen+4`. Validates: username/password non-blank, password 8-32 chars, password charset limited to alphanumerics + `-_!@#$%^&*().?+`. **This means the web UI login (the port-3000 traffic flagged as out-of-scope in spec §6) is actually configurable over the documented port-52000 protocol** — a driver could set/rotate the AMS16's web UI credentials without ever touching port 3000. |
| **Get IP assignment method** | `FF 55 03 08 81 F5` | `ariel_commands.getIpMethod` (comment: "OK in 1.0047+") |
| **Set IP to DHCP** | `FF 55 02 08 81` | `ariel_commands.setIpAddressDHCP` |
| **Set static IP** | `FF 55 0E 08 82 <4B ip> <4B subnet mask> <4B gateway>` | `ariel_commands.setIpAddressStatic` / `ariel_protocol.setIpAddressStatic(ip, mask, gateway)`; each octet is one raw byte (`StringIpToHexBytes`) |
| **Auto-Sense off-delay** | `FF 55 04 0A A3 00 <delay byte>` | `ariel_commands.audioSenseOffDelay` / `ariel_protocol.setAudioSenseOffDelay(delay)` — a *second* Auto-Sense parameter beyond the on/off flag already in spec §4.3: how long (in whatever unit the device uses) audio must be absent before Auto-Sense reports "lost". Comment notes the protocol technically supports a 2-byte delay value but the driver only ever sends the low byte. |
| **Firmware push over the control port** | `FF 56 <len> 06 01 <URL string>` | `FirmwareUpdate(filename)` builds `cmd_data = 0x06 0x01 <url>` and sends it as a normal `0x56`-group frame. The *driver* hosts the `.bin`/`.zip` at `http://<C4-controller-ip>/driver/<name>/firmware/<file>` and tells the AMS16 to fetch it via this command — the AMS pulls the firmware itself over HTTP from the controller. Not a capture gap so much as a whole undocumented subsystem (firmware self-update, `www/firmware/firmware_data.json` in the driver package lists available versions). |

---

## 2. Legacy/parallel command paths — old opcodes still live, spec only has the "new" ones

The device apparently kept backward-compatible opcodes for tone control and
mono/stereo alongside the newer ones the pcaps happened to capture. None of
these legacy paths were exercised in any capture:

| Feature | Legacy frame | Notes |
|---|---|---|
| Old Stereo | `FF 55 03 03 10` | `setOutputStereo` |
| Old Mono | `FF 55 03 03 11` | `setOutputMono` |
| Old get Mono/Stereo | `FF 55 04 03 10 F5` | `getMonoStereo` |
| Old Bass (low shelf, single value) | `FF 55 04 03 2F <ii> <vv 00-30>` | `setOutputBass`/`getOutputBass` — a **flat gain-only** bass control (0x00=-12dB…0x18=0dB…0x30=+12dB, same encoding as spec's shelf-gain formula) that predates the frequency-adjustable Low Shelf commands already in spec §4.5 |
| Old Treble (high shelf, single value) | `FF 55 04 03 30 <ii> <vv 00-30>` | `setOutputTreble`/`getOutputTreble` — same idea for treble |

Also unused-but-defined opcodes the driver explicitly comments as dead code
(never called, but presumably still accepted by the device firmware):
`FF 55 03 03 19` (mute toggle), `FF 55 03 03 12` (mono toggle),
`FF 55 03 03 13`/`14`/`15`/`16` (volume up/down, up3/down3),
`FF 55 03 03 1C` (loudness toggle).

---

## 3. Missing parameter: Shelf Q (Low/High Shelf "Q Ratio")

Spec §4.5 (Tone Control — Shelving Filters) documents Frequency and Gain for
the low/high shelf but is **completely missing the Q parameter** — it was
never sent during the DSP-config capture session. The driver's Composer UI
action definitions (`driver.xml`, "Low Shelf Tone Control" / "High Shelf Tone
Control") explicitly include a "Q Ratio" field alongside Frequency and Gain:

| Feature | Frame | Notes |
|---|---|---|
| Set Low Shelf Q | `FF 56 07 03 04 <ii> <4B ×100>` | `ariel_commands.setLowShelf_Q`, same 4-byte ×100 encoding as Room EQ band Q (spec §3, EQ band Q row); default 0.58 (`DEFAULT_LOW_SHELF_Q`) |
| Get Low Shelf Q | `FF 56 07 03 04 F5 <ii>` | |
| Set High Shelf Q | `FF 56 07 03 02 <ii> <4B ×100>` | `ariel_commands.setHighShelf_Q`; default 0.58 (`DEFAULT_HIGH_SHELF_Q`) |
| Get High Shelf Q | `FF 56 04 03 02 F5 <ii>` | note the GET uses group `0x04` not `0x07` (single-byte-style GET prefix), unlike the SET which is `0x07` (4-byte payload) — same asymmetric pattern already documented for other 4-byte fields in the spec |

---

## 4. 2.1 Audio Zone / Sub-Output Pairing — spec correctly flagged as unobserved; driver confirms exactly how it works

Spec §6 lists this as unexercised in any capture. The driver source resolves
it completely — it's a mix of one real device feature and one purely
Composer-side feature:

- **Real device commands (2.1 crossover/sub level — a genuine protocol gap):**

  | Feature | Frame | Notes |
  |---|---|---|
  | Set crossover frequency | `FF 56 07 03 05 <ii> <4B Hz>` | `setCrossoverFrequency`; default 80 Hz |
  | Get crossover frequency | `FF 56 07 03 05 F5 <ii>` | |
  | Set crossover type/slope | `FF 56 04 03 06 <ii> <vv 0-5>` | `setCrossoverType`; `vv` = `CROSSOVER_TYPE` table: `0`=Butterworth 12dB, `1`=Butterworth 24dB, `2`=Butterworth 48dB, `3`=Linkwitz-Riley 12dB, `4`=Linkwitz-Riley 24dB, `5`=Linkwitz-Riley 48dB. Default is Linkwitz-Riley 24dB (`4`) |
  | Get crossover type/slope | `FF 56 04 03 06 F5 <ii>` | |
  | Set sub-output volume offset | `FF 56 04 03 07 <ii> <vv>` | `setSubVolumeOffset`; `vv = 24 + (offset_db * 2)`, i.e. identical ±12 dB / 0.5-step encoding used elsewhere in the spec (0x00=-12, 0x18=0/center, 0x30=+12); default offset 0 |
  | Get sub-output volume offset | `FF 56 04 03 07 F5 <ii>` | |

  These three are sent **to the primary output's channel index**, not the
  sub/paired output.

- **New Output Mode values (spec §4.4 only lists 4 of 6):**

  `OUTPUT_MODES = { ["DSP Bypass Stereo"]=0, Stereo=1, Mono=2, ["2.1 Stereo"]=3, ["2.1 Mono"]=4, Test=5 }`.
  The spec's `FF 56 04 03 0B <ii> <vv>` table only documents `vv` = 0, 1, 2, 5 (matching what
  the capture happened to exercise) — `vv=3` ("2.1 Stereo") and `vv=4`
  ("2.1 Mono") are missing entirely; selecting one of these is presumably
  what enables the crossover/sub-offset behavior above on that output.

- **The "pairing" itself is Composer-side, not a device command** — which
  output is the "sub" for which "primary" (`g_arielData.outputs[i].pairedOutput`)
  is driver-persisted state, never sent to the AMS16. When a pair is
  configured, the driver just fans out the *same* existing commands (volume,
  mute, loudness, max volume, input routing, disconnect) to both the primary
  and paired output index, applying the sub-offset to the paired output's
  volume in software (`SetPairsVolume`, `SetPairsMute`,
  `SetPairsOutputLoudness`, `SetPairsMaxVolume`, `SetPairsInputToOutput`,
  `SetPairsDisconnectOutput`). There is no "pair output X with Y" opcode to
  discover — this part of spec §6's gap entry can be considered resolved as
  "not a protocol feature," while the crossover/sub-offset commands above
  are the genuine missing piece.

---

## 5. Output disconnect — a real sentinel value, not just "set source"

Spec §4.4 documents `Set input source` as `FF 55 04 03 1D <ii> <vv>` with
`vv` = 0-based source input index, and separately shows a GET response of
`Get Out[1] Input Source : Audio Off` as an observed default/reset state —
but never documents how a driver would explicitly **cause** that "Audio
Off" state. The driver reveals it's the *same* opcode with an
out-of-range sentinel value: `ariel_protocol.disconnectOutput16(outputIndex)`
sends `FF 55 04 03 1D <ii> 10` (value `16` decimal) on 16-output models
(`disconnectOutput8` sends value `8` on 8-output models) — i.e. "set source
to (input count)" is the disconnect signal, since valid input indices only
go up to `input_count - 1` (0-based).

---

## 6. Corrections — spec's inference from captures was backwards

- **Room EQ vs. Speaker EQ band numbering is inverted.** Spec §4.6 states
  "Bands 1-6 correspond to the primary 'Room equalizer EQ1-6' UI... bands
  7-12 were exercised in `core5_EQs_config`". The driver source shows the
  opposite: `FIRST_SPEAKER_EQ = 1`, `FIRST_ROOM_EQ = 7`, and the diagnostic
  log labels confirm it explicitly — `DiagnosticsLogData()` prints
  `---------- Speaker EQs ----------` on seeing "Band 1 Freq :" and
  `---------- Room EQs ----------` on seeing "Band 7 Freq :". **Bands 1-6 are
  the Speaker EQ (used by Speaker Presets), bands 7-12 are the Room EQ (the
  user-adjustable "Room equalizer" graph feature mentioned in
  `core5_dsp_config.txt`)** — which also matches the pcap evidence better in
  hindsight, since `core5_EQs_config.txt`/its pcap (the one that actually
  exercises the FLAT/CLASSICAL/JAZZ/POP/ROCK-style adjustments) drove bands
  7-12, not 1-6. The band-selector byte formula itself
  (`((band-1)<<4) | {0=freq,1=gain,2=Q}`) is unaffected and confirmed
  correct by the driver source (`ariel_commands.NewEQ` is generated with the
  identical formula).

- **The Zone 1-8 / Zone 9-16 / ASG commands are real, settable 12V trigger
  relay outputs — not passive housekeeping.** Spec §4.7 describes these as
  "periodic bulk-status refreshes... not user-facing controls in their own
  right." The driver shows they are the actual protocol commands behind the
  Core4 "Assignable Trigger: Enable/Disable" output setting
  (`core5_output_config.txt`) — `ariel_protocol.setTrigger1to8/9to16/ASG(value)`
  drive both a physical 12V trigger relay (`C4:SendToProxy(...)`) *and* this
  exact device command, so they are genuinely controllable outputs, not
  read-only telemetry. Confirmed exact frames:

  | Feature | Frame |
  |---|---|
  | Zone 1-8 trigger ON | `FF 55 03 05 50 00` |
  | Zone 1-8 trigger OFF | `FF 55 03 05 51 00` |
  | Zone 9-16 trigger ON | `FF 55 03 05 50 01` |
  | Zone 9-16 trigger OFF | `FF 55 03 05 51 01` |
  | ASG trigger ON | `FF 55 03 05 50 02` |
  | ASG trigger OFF | `FF 55 03 05 51 02` |

  (matches the byte values already in spec §4.7, but the *meaning* — a
  settable output, not a query — was wrong).

---

## 7. Things the driver confirms the spec already got right (no action needed, noted for completeness)

- **Volume 0-100 → dB table**: the driver has its own hardcoded
  `g_dbVolMap` (dB → percent, the inverse direction of the spec's §3.1
  table) used by `volDBToPercent()`. Every one of its ~100 entries matches
  the spec's full-sweep-captured `VOLUME_PCT_TO_DB` table exactly (one
  cosmetic difference: the driver has both `-68` and `-69` mapping to raw
  `6`, a rounding-tolerance alias, not a conflict). The driver's own
  fallback formula (`((dbVol + 0.5) * 2 + 161) / 161 * 100`) is only used
  if a value is missing from the table and explicitly logs an error when it
  triggers — confirming the vendor itself treats this as a lookup table,
  not a formula, exactly as the spec concludes.
- **No "load EQ preset" device opcode exists.** `SetEQPreset()` in the
  driver confirms presets (Speaker or Room) are applied by sending the
  individual per-band Frequency/Q/Gain SET commands client-side — exactly
  what spec §6 already concludes about FLAT/CLASSICAL/JAZZ/POP/ROCK.
  (`www/EQ/SpeakerPresets.json` and `www/EQ/RoomEQPresets.json` in the
  driver package contain the actual preset value tables, if exact
  replication of Control4's stock presets is wanted for an HA port.)
- **Input/Output renaming is Composer-side only, confirmed conclusively.**
  `PRX_CMD.SET_ROOM_BINDING_NAME` stores the name directly into
  `g_arielData.outputs[i].roomName` (in-memory/persisted driver state) and
  never calls `send()`/`ariel_protocol.*` — there is no rename command to
  discover. Confirms spec §6's existing gap note; this can be considered
  resolved as "not a protocol feature" rather than an open gap.
- **Debug Mode, Firmware Updates (Manual/Automatic), Advanced Config**:
  confirmed Composer/driver-local only — their `ON_PROPERTY_CHANGED`
  handlers touch timers, UI refresh, and (for Firmware Updates) the
  HTTP-based `CheckFirmware()`/`FirmwareUpdate()` flow above; none send a
  device command. **Input Audio Sense** is the one property among these
  that *does* reach the device, via the already-documented Auto-Sense
  command (spec §4.3) — confirmed by `ON_PROPERTY_CHANGED.InputAudioSense()`
  calling `ariel_protocol.disableAudioSense()`.
- **"Web Config" Composer property** is just a clickable link
  (`C4:UpdateProperty("Web Config", "http://" .. device_ip)`) to the
  device's own web UI (port 3000, spec §6) — not a protocol command.
- **"Connect to OvrC"** is a standard Control4 platform property with no
  driver-specific code in `driver.lua` — out of scope for this protocol.
- **"Backup Device Data" / "Restore Device Data"** Composer actions exist
  but were not traced in this pass — likely operate on the driver's own
  persisted `g_arielData` (Composer/controller-side state), not a device
  opcode, consistent with the renaming/pairing findings above. Not
  confirmed either way; flagged here rather than asserted.

---

## 8. Source reference

All findings above come from
`TriadAMSv2_Driver/extracted/driver.lua` (specifically the `ariel_commands`
table definitions around lines 508-730, the `ariel_protocol.*` functions
following it, `g_dbVolMap` around line 1874, `SetEQPreset`/`SetEQ_*` around
line 1542, the `SetPairs*` functions around line 5759, and the
`ON_PROPERTY_CHANGED.*` handlers around line 5952) and
`TriadAMSv2_Driver/extracted/driver.xml` (Composer UI action/property
definitions). No files under `TriadAMSv2_Driver/` or `pcap_captures/` were
modified while producing this document.
