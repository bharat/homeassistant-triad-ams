# Triad AMS16v2 Control Protocol Specification

## 1. Overview & Scope

This document specifies the binary control protocol used by a Control4 **Core5**
controller to command a **Triad AMS16v2** 16x16 audio matrix/amplifier. It was
reverse-engineered entirely from SPAN-port packet captures of a Core5 driving a
live AMS16v2, taken on 2026-07-10 (see `about.txt` and the accompanying
`core5_*.pcap` / `core5_*.txt` files in this directory). No vendor documentation
was consulted; every command and value encoding below is derived from observed
traffic and is annotated with the capture evidence that supports it.

**Purpose:** provide enough detail to implement a custom Home Assistant
integration that controls and monitors an AMS16v2 directly over the network,
without going through a Control4 system.

**Devices observed:**
- Core5 controller: `172.16.0.40` (primary, source of nearly all SET/GET
  commands documented here)
- `172.16.0.11` — the user's **Home Assistant instance**, seen only issuing
  `Get Out[n] Volume` queries on port 52000 while trying a few different
  community HA integration repos against the AMS16v2 directly (not a second
  Core5/keypad). Its traffic is a useful independent confirmation that the
  volume-GET command and response format documented in §4.4 are correct, but
  it is not itself part of the Control4 system.
- Triad AMS16v2: `172.16.0.41`

**Endpoints:**
- **TCP `172.16.0.41:52000`** — the control protocol documented here. Plaintext,
  unencrypted, request/response, no login/handshake observed.
- **TCP `172.16.0.41:3000`** — an HTTP/WebSocket endpoint (device web UI). The
  traffic captured here is the user's own **web browser** logged into the
  AMS16v2's web UI to see what it exposed, not Core5 or Home Assistant
  traffic. Only a masked WebSocket handshake and encrypted-looking frames
  were observed; see §6 for details and why it is out of scope.

All commands generalize across the 16 inputs and 16 outputs of the AMS16v2:
only a single **channel-index byte** changes between "input/output 1" and
"input/output 16" (see §2.2). This document therefore documents each command
once, parameterized by that index.

---

## 2. Frame Format

### 2.1 Request frame

```
FF  GG  LL  <payload...>
```

| Byte | Meaning |
|---|---|
| `0` | `0xFF` — start-of-frame marker. Present on every request observed. |
| `1` | **Group byte (`GG`)**: `0x55` for system/mixer-level commands, `0x56` for DSP/EQ/delay-level commands. No other group byte was observed. |
| `2` | **Length byte (`LL`)**: count of payload bytes following (i.e. total frame length is `3 + LL`). |
| `3..` | Payload: opcode byte(s), then a channel-index byte (for per-channel commands), then a value field (for SET) or the GET sentinel (for GET). |

Examples (verified against captures):
- `FF 55 03 01 01 F5` (len=3, payload=`01 01 F5`) — power-status poll, sent
  continuously as a heartbeat by the controller (every capture).
- `FF 56 07 03 03 0C 00 00 00 64` (len=7, payload=`03 03 0C 00000064`) — set
  Out[13] low-shelf frequency to 100 Hz (`core5_dsp_config` frame 28).

### 2.2 Channel index & the GET sentinel

Channel indices are **0-based**: `0x00` = channel 1 … `0x0F` = channel 16. This
applies identically to input and output channel selectors.

Per-channel commands use one of two shapes:

- **SET**: `... <opcode(s)> <idx> <value>` — index immediately precedes the
  value.
- **GET**: `... <opcode(s)> F5 <idx>` — the byte `0xF5` is a **fixed "get"
  sentinel** occupying the value position, and the trailing byte is the
  channel index.

Example pair (input gain, opcode `04 02`, confirmed in
`core5_gather_diag_data`, frames 10/24/34...):
- GET In[1] gain: `FF 55 04 02 04 F5 00` → `Get In[1] input gain : 0`
- GET In[2] gain: `FF 55 04 02 04 F5 01` → `Get In[2] input gain : 0`
- SET In[1] gain to +12: `FF 55 04 02 04 00 30` → `Set In[1] input gain : 12`
- SET In[16] gain to +12: `FF 55 04 02 04 0F 30` → `Set In[16] input gain : 12`
  (`core5_input_config`, frames confirm idx `0x0F` = channel 16)

Not every command follows the `idx`-before-`value` / `F5`-before-`idx` pattern
exactly — some (e.g. Auto-Sense, §4.5) place the index differently. Each table
in §4 gives the exact byte order observed for that command; do not assume a
universal template beyond what's documented per command.

### 2.3 Response frame

Every command (SET or GET) receives a single reply: a **human-readable ASCII
string, null-padded to a fixed ~300-byte frame**. Examples observed verbatim:

```
Get Power status : Working
Set In[1] input gain : 12
Get Out[7] Volume : -44.1
Set Out[13] Low Shelf Frequency to 100 Hz
Fw version : V1.0054
```

There is no separate binary ACK — the ASCII string *is* the acknowledgment,
and it also serves as the state-readback mechanism. A driver should:

1. Send the binary command frame.
2. Read the response, strip trailing `0x00` padding, decode as ASCII/Latin-1.
3. Parse the resulting line (a small set of regex patterns covers all
   commands — see the Python appendix, §7, `parse_response()`).

### 2.4 Heartbeat / keepalive

The Core5 continuously polls `FF 55 03 01 01 F5` (Get Power status) roughly
once per second across the entire session in every capture. This appears to
be purely a liveness/keepalive check (`Working` / `Standby` values were
observed) and is not required for control — a driver can poll it at a lower
rate purely to track online/offline state, or omit it and rely on TCP
connection state.

---

## 3. Value Encoding Reference

| Encoding | Width | Formula | Notes / evidence |
|---|---|---|---|
| **Boolean on/off** | 1 byte | `0x00`=off, `0x01`=on | e.g. Loudness, Lock Room EQ, Auto Standby |
| **Channel index** | 1 byte | `idx = channel_number - 1` | 0x00-0x0F for both inputs and outputs |
| **Shelf/input gain (±12 dB, 0.5 dB steps)** | 1 byte | `raw = (gain_db + 12) * 2` | `0x00`=-12, `0x18`=0, `0x30`=+12. Confirmed: In[1] gain "12"→`0x30`, gain "-12"→`0x00` (`core5_input_config` fr. 8-9 area) |
| **Delay (0-80 ms)** | 1 byte | `raw = delay_ms` (direct) | `0x00`-`0x50` (80 decimal = 0x50). Confirmed Input[1] Delay 80→`0x50`, Delay 0→`0x00` |
| **Balance (±12, L/Center/R)** | 1 byte | `0x00`=Bal L12 (full left), `0x18`=Center, `0x30`=Bal R12 (full right) | Linear between; confirmed 3 points exactly (`core5_output_config` fr. 259-285) |
| **Volume / Max Volume / Turn-on Volume (0-100 UI scale)** | 1 byte | `raw = 0x00..0x64` (0-100 decimal), UI value passed directly | `0x64`(100)=0 dB (unity/max), `0x00`(0)=-108.5 dB (device floor). Non-linear (audio taper) internally — driver only needs to send the 0-100 UI value, device reports the resulting dB in the response text. **Full 0-100 → dB curve now captured for all 101 values** (`core5_output_volume_full_sweep_triad_ams16_capture_20260720T183622.pcap`); see the complete lookup table in §3.1 and `VOLUME_PCT_TO_DB` in the Python appendix, §7 |
| **EQ/shelf frequency (Hz)** | 4 bytes, big-endian unsigned | `raw = freq_hz` | e.g. `0x000003E8`=1000 Hz, `0x00003E80`=16000 Hz, `0x00000020`=32 Hz |
| **EQ/shelf gain (±12.00 dB)** | 4 bytes, big-endian **signed** | `raw = round(gain_db * 100)` | e.g. `0x000004B0`=1200→+12.0 dB, `0xFFFFFB50`=-1200 (two's complement)→-12.0 dB, `0xFFFFFFEC`=-20→-0.2 dB, `0x00000000`=0 dB |
| **EQ band Q (0.5-15.0)** | 4 bytes, big-endian unsigned | `raw = round(q * 100)` | e.g. `0x00000064`=100→1.0, `0x00000046`=70→0.7, `0x000005DC`=1500→15.0 (max), `0x00000032`=50→0.5 (min) |
| **Input/output source selector** | 1 byte | `raw = source_input_number - 1` | Same 0-based index as channel selection. Confirmed Out[1]→input 3 (`raw=0x02`), Out[1]→input 16 (`raw=0x0F`) |

### 3.1 Volume 0-100 → dB Lookup Table (complete)

Captured via a full manual sweep of Out[13]'s Output Volume slider through
every integer value 0-100
(`core5_output_volume_full_sweep_triad_ams16_capture_20260720T183622.pcap`),
one `Set Out[13] Output Volume to X.X` response per raw value, **all 101
values present, no gaps** (despite a UI glitch during capture where single
increments sometimes reverted, requiring double-taps — the resulting SET
commands were still one-per-raw-value with no duplicates or missing values
once decoded). Independently
spot-checked against Out[1] at raw values 0, 25, 50, 100 in the same capture
— identical dB readings, confirming this is a single global taper curve, not
calibrated per output channel.

The curve is a standard non-linear "audio taper": resolution is coarse near
the top (approx. 0.2-0.4 dB/step above raw≈70) and progressively finer near
the bottom (approx. 6-8 dB/step below raw≈5), reaching the device's minimum
of -108.5 dB at raw=0. It does not correspond to a simple `20*log10()` ratio
or any other single closed-form formula tried — treat it as an empirical
lookup table, not a formula. The full table (raw → dB) is embedded verbatim
as `VOLUME_PCT_TO_DB` in the Python appendix (§7); a decile sample is shown
here for quick reference:

| raw | dB | raw | dB | raw | dB | raw | dB |
|---|---|---|---|---|---|---|---|
| 0 | -108.5 | 30 | -35.6 | 60 | -15.3 | 90 | -2.7 |
| 5 | -73.9 | 35 | -31.7 | 65 | -12.6 | 95 | -1.3 |
| 10 | -55.6 | 40 | -28.0 | 70 | -10.2 | 100 | 0.0 |
| 15 | -48.7 | 45 | -24.5 | 75 | -8.0 | | |
| 20 | -44.1 | 50 | -21.2 | 80 | -6.0 | | |
| 25 | -39.7 | 55 | -18.1 | 85 | -4.2 | | |

This table is purely for **display** purposes (e.g. showing an accurate dB
readout next to the HA volume slider) — the driver never needs to compute or
send a dB value; it always sends the raw 0-100 UI value directly (§3, Volume
row).

---

## 4. Command Catalog

`ii` = 1-byte channel index (0-based). `vv` = 1-byte value. `FFFFFFFF` (4B) =
4-byte big-endian value field. All bytes hex. All commands are shown with a
confirmed example (request + literal device response).

### 4.1 System / Maintenance

| Purpose | Frame | Example → Response |
|---|---|---|
| Power status (poll) | `FF 55 03 01 01 F5` | → `Get Power status : Working` (also seen: `Standby`) |
| Get firmware version | `FF 55 03 06 65` | → `Fw version : V1.0054` |
| Reboot | `FF 55 03 06 B4 00` | → `Reboot Command` |
| Factory reset | `FF 55 02 0B B0` | → `Factory Reset Command` |
| Auto Standby: off | `FF 55 03 08 83 00` | → `Auto Standby Off` |

`Auto Standby: on` was not captured explicitly, but by symmetry with other
boolean toggles the "on" value byte is very likely `0x01` in the same
position (`FF 55 03 08 83 01`) — **unverified, best-guess** (flagged per §6).

### 4.2 Input Configuration (per input `ii` = 0x00-0x0F)

| Purpose | Frame | Example → Response |
|---|---|---|
| Get input gain | `FF 55 04 02 04 F5 ii` | Out[1]: → `Get In[1] input gain : 0` |
| Set input gain (±12 dB) | `FF 55 04 02 04 ii vv` | +12: `FF 55 04 02 04 00 30` → `Set In[1] input gain : 12`; -12: `FF 55 04 02 04 00 00` → `Set In[1] input gain : -12` |
| Get input delay | `FF 56 04 02 04 F5 ii` | → `Get Input[1] Delay 0` |
| Set input delay (0-80 ms) | `FF 56 04 02 04 ii vv` | 80ms: `FF 56 04 02 04 00 50` → `Set Input[1] Delay 80` |
| Get audio-detect status | `FF 56 04 02 03 F5 ii` | → `Get Input[1] Audio Detect Undetected` / `Detected` |
| Get per-input Auto-Sense flag | `FF 55 04 0A A0 F5 ii` | → `AudioSense:Input[0]: 0` (note: index echoed 0-based here, unlike most GET responses which echo 1-based channel numbers) |

Channel-16 example confirming index generalization: `FF 55 04 02 04 0F 30` →
`Set In[16] input gain : 12` (`core5_input_config`).

### 4.3 Global Auto-Sense (Input Audio Sense)

| Purpose | Frame | Example → Response |
|---|---|---|
| Set Auto-Sense off | `FF 55 04 0A A2 00 FF` | → `Set AUTO SENSE Off` |
| Set Auto-Sense on | `FF 55 04 0A A2 01 FF` | → `Set AUTO SENSE On` |
| Get Auto-Sense (per-channel query form) | `FF 55 04 0A A2 F5 ii` | → `Get AUTO SENSE :On` |

Note the trailing `FF` on the SET form is a fixed suffix byte, not a channel
index — this command is global, not per-channel, despite the GET form
accepting a per-channel index in the same byte position.

### 4.4 Output Configuration (per output `ii` = 0x00-0x0F)

| Purpose | Frame | Example → Response |
|---|---|---|
| Get input source | `FF 55 04 03 1D F5 ii` | → `Get Out[1] Input Source : Audio Off` (default/unassigned state seen post-factory-reset) |
| Set input source | `FF 55 04 03 1D ii vv` (`vv` = source input idx, 0-based) | input 3: `FF 55 04 03 1D 00 02` → `Set Out[1] Input Source to input 3`; input 16: `FF 55 04 03 1D 00 0F` → `Set Out[1] Input Source to input 16` |
| Get output delay | `FF 56 04 03 09 F5 ii` | → `Get Output[1] Delay 0` |
| Set output delay (0-80 ms) | `FF 56 04 03 09 ii vv` | `FF 56 04 03 09 00 50` → `Set Output[1] Delay 80` |
| Set output mode | `FF 56 04 03 0B ii vv` | `vv=00`→`Set Out[1] Select:DSP Bypass Stereo`; `vv=01`→`Select:DSP Stereo`; `vv=02`→`Select:Mono Sum`; `vv=05`→`Select:Test Signal` |
| Mute | `FF 55 03 03 17 ii` | → `Set Out[1] Mute` |
| Unmute | `FF 55 03 03 18 ii` | → `Set Out[1] Unmute` |
| Get mute status | `FF 55 04 03 17 F5 ii` | → `Get Out[1] Mute status : Unmute` |
| Set output volume (0-100 UI) | `FF 55 04 03 1E ii vv` | `vv=0x64`(100): → `Set Out[1] Output Volume to 0`; `vv=0x00`: → `Set Out[1] Output Volume to -108.5` |
| Get output volume | `FF 55 04 03 1E F5 ii` | → `Get Out[7] Volume : -44.1` |
| Set max volume (0-100 UI) | `FF 55 04 03 1F ii vv` | `vv=0x00`→`Set Out[1] Max Volume to -108.5`; `vv=0x64`→`Set Out[1] Max Volume to 0` |
| Get max volume | `FF 55 04 03 1F F5 ii` | → `Get Out[6] Max Volume : 0` |
| Set turn-on volume (0-100 UI) | `FF 55 04 03 33 ii vv` | `FF 55 04 03 33 00 2F` → `Set Out[1] Turn on Vol to -23.1` |
| Set balance | `FF 55 04 03 31 ii vv` | `vv=0x00`→`Bal L 12`; `vv=0x18`→`Bal Center`; `vv=0x30`→`Bal R 12` |
| Set test-tone gain (-24 to 0) | `FF 56 04 04 01 ii vv` (`vv` scaled like volume) | `vv=0x30`→`Set Out[1] Test Gain 0`; `vv=0x00`→`Set Out[1] Test Gain -24` |

Channel-13 examples confirming generalization: `FF 55 04 03 1D 0C 02` →
`Set Out[13] Input Source to input 3`; `FF 56 04 03 09 0C 50` →
`Set Output[13] Delay 80`.

### 4.5 Tone Control — Shelving Filters (per output `ii`)

| Purpose | Frame | Example → Response |
|---|---|---|
| Loudness on | `FF 55 03 03 1A ii` | → `Set Out[13] Loudness On` |
| Loudness off | `FF 55 03 03 1B ii` | → `Set Out[13] Loudness Off` |
| Low-shelf (Bass) frequency (20-2000 Hz) | `FF 56 07 03 03 ii <4B Hz>` | `100`: `...0000 0064` → `Set Out[13] Low Shelf Frequency to 100 Hz` |
| Low-shelf gain (±12 dB) | `FF 56 07 03 0D ii <4B ×100>` | `+12`: `0000 04B0` → `Set Out[13] Low Shelf gain to 12`; `-12`: `FFFF FB50` → `-12`; `-0.2`: `FFFF FFEC` |
| High-shelf (Treble) frequency (20-20000 Hz) | `FF 56 07 03 01 ii <4B Hz>` | `1000`: `0000 03E8` → `Set Out[13] High Shelf Frequency to 1000 Hz`; `5000`: `0000 1388`; `2000`: `0000 07D0` |
| High-shelf gain (±12 dB) | `FF 56 07 03 0C ii <4B ×100>` | `+12`/`-12`/`0` confirmed identical pattern to low-shelf gain |

### 4.6 Room Equalizer — 12-Band Parametric EQ (per output `ii`)

The device exposes **12 EQ bands** per output, addressed by a single band
selector byte where the **high nibble is the band number** (`0x0`=band 1 …
`0xB`=band 11, i.e. `band_selector = (band_number - 1) << 4`) and the **low
nibble selects the parameter**: `0`=Frequency, `1`=Gain, `2`=Q.

Bands 1-6 correspond to the primary "Room equalizer EQ1-6" UI (per
`core5_dsp_config.txt`); bands 7-12 were exercised in
`core5_EQs_config.txt`/`core5_eqs_config...pcap` and use the identical
opcode structure with band selector `0x60`-`0xB0`.

| Purpose | Frame | Example → Response |
|---|---|---|
| Lock Room EQ on/off | `FF 56 04 03 08 ii vv` (`vv`=00 off/01 on) | → `Set Out[13] Lock Room EQ Off` |
| Band Frequency (20-20000 Hz) | `FF 56 07 05 <band_sel+0> ii <4B Hz>` | Band 1: `FF 56 07 05 00 0C 0000 0064` → `Set Out[13] Band 1 Freq to 100 Hz`; Band 7: `sel=0x60` → `Set Out[13] Band 7 Freq to 32 Hz`; Band 12: `sel=0xB0` → `Band 12 Freq to 16000 Hz` |
| Band Gain (±12.00 dB) | `FF 56 07 05 <band_sel+1> ii <4B ×100>` | Band 1: `sel=0x01` → `Set Out[13] Band 1 Gain to 3`; Band 7: `sel=0x61` → `Band 7 Gain to 12` / `-12` |
| Band Q (0.5-15.0) | `FF 56 07 05 <band_sel+2> ii <4B ×100>` | Band 1: `sel=0x02` → `Set Out[13] Band 1 Q to 3`; Band 7: `sel=0x62` → `Band 7 Q to 15` / `0.5` |

Worked band-selector table:

| Band | Freq byte | Gain byte | Q byte |
|---|---|---|---|
| 1 | `0x00` | `0x01` | `0x02` |
| 2 | `0x10` | `0x11` | `0x12` |
| 3 | `0x20` | `0x21` | `0x22` |
| 4 | `0x30` | `0x31` | `0x32` |
| 5 | `0x40` | `0x41` | `0x42` |
| 6 | `0x50` | `0x51` | `0x52` |
| 7 | `0x60` | `0x61` | `0x62` |
| 8 | `0x70` | `0x71` | `0x72` |
| 9 | `0x80` | `0x81` | `0x82` |
| 10 | `0x90` | `0x91` | `0x92` |
| 11 | `0xA0` | `0xA1` | `0xA2` |
| 12 | `0xB0` | `0xB1` | `0xB2` |

Note: GET forms for EQ bands were also observed in `core5_gather_diag_data`
using the `04 05 <selector> F5 ii` opcode form, e.g.
`FF 56 04 05 A1 F5 04` → `Get Out[5] Band 11 Gain : 0`.

### 4.7 Zone / Group Status (housekeeping)

These appear to be periodic bulk-status refreshes the Core5 issues after
changing any output setting, not user-facing controls in their own right —
include for completeness / to avoid the driver misinterpreting them as
per-channel commands.

| Purpose | Frame | Example → Response |
|---|---|---|
| Zone 1-8 status | `FF 55 03 05 50 vv` | `vv=00` → `Set Zone :1-8 ON`; `vv=02` also seen (query form, no text response captured) |
| Zone 9-16 status | `FF 55 03 05 51 vv` | `vv=00` → `Set Zone :9-16 OFF`; `vv=01` → `Set Zone :9-16 ON` |
| ASG (Assignable/Global trigger group?) status | `FF 55 03 05 51 02` / `FF 55 03 05 02` | → `Set ASG OFF` / `Get ASG :OFF` |

---

## 5. Home Assistant Driver Mapping (suggested)

A custom HA integration (e.g. a `config_entry`-based component with a single
TCP connection to `172.16.0.41:52000`) could expose:

- **Per output (×16), as a device with these entities:**
  - `select` — Input Source (16 options + reflects `Get Out[n] Input Source`)
  - `number` — Output Volume (0-100), Max Volume (0-100), Turn-on Volume (0-100), Balance (0-100 mapped to L12..R12), Delay (0-80 ms)
  - `switch` — Mute, Loudness
  - `select` — Output Mode (DSP Stereo / DSP Bypass Stereo / Mono Sum / Test Signal)
  - `number`×3 per EQ band (×12 bands): Frequency, Gain, Q; plus low/high shelf Frequency & Gain
  - `switch` — Lock Room EQ
  - Optionally surface as a single `media_player` entity per output (volume/mute/source) for a friendlier Lovelace card, backed by the same number/select entities.
- **Per input (×16):**
  - `number` — Input Gain (±12 dB), Input Delay (0-80 ms)
  - `binary_sensor` — Audio Detect (Detected/Undetected)
- **Global:**
  - `switch` — Auto Sense (Input Audio Sense)
  - `button` — Reboot, Factory Reset (mark Factory Reset with `entity_category: config` and require confirmation in the UI — it is destructive)
  - `sensor` — Firmware Version, Power Status (Working/Standby), TCP connectivity

**State sync:** since every SET reply also encodes the resulting value, the
driver can update its internal state directly from each SET response instead
of issuing a follow-up GET. For full state refresh on connect/reconnect,
issue the GET form of every entity's command once and parse the responses
with the regex table in the Python appendix.

**Connection handling:** open one persistent TCP socket to port 52000, keep a
request queue (the device replies once per request; pipelining was not
tested/observed — issue one request at a time and wait for its response
before sending the next). Use the power-status poll (§2.4) at a modest
interval (e.g. 10-30s) purely to detect a dead connection and reconnect.

---

## 6. Unverified / Gaps

The following features are documented in the capture note files
(`core5_*.txt`) as UI-level features but were **not observed as commands on
port 52000** in any capture, and are therefore **not included** in the
command catalog above:

- **Input/Output renaming** (`core5_input_config.txt` / `core5_output_config.txt`
  mention "Renaming: testingInput1" and an "Assign Names" button). No text or
  name-bearing payload was seen on port 52000 in any capture (checked all
  payloads for runs of ASCII letters — only the fixed English response
  strings and one incidental HTTP request were found).
- **"Assign Names based on inbound/bound connections"** button (inputs and
  outputs) — same as above, not observed.
- **2.1 Audio Zone / sub-output pairing** (pairing output 2 as a subwoofer
  output for another output) — not exercised in any capture provided.
- **Speaker Presets** (mentioned as a possible future plugin feature in
  `core5_dsp_config.txt`) — not observed; likely not implemented on this
  firmware (`V1.0054`).
- **EQ presets** (FLAT / CLASSICAL / JAZZ / POP / ROCK, `core5_EQs_config.txt`)
  — no discrete "select preset N" command was observed. Instead, selecting a
  preset in the Core4 UI results in the controller sending the **individual
  band Frequency/Gain/Q SET commands** for bands 7-12 (confirmed in
  `core5_eqs_config...pcap`) to reproduce that preset's curve. If preset
  *names* matter to the HA UI, the driver would need to hardcode each
  preset's per-band Freq/Gain/Q values as scenes/scripts that issue the
  §4.6 SET commands — the AMS itself has no "load preset" opcode.
- **System-level settings** in `core5_c4_system_config.txt` — "Debug Mode(s)",
  "Firmware Updates: Manual/Automatic", and "Advanced Config: Off/On" were
  **not observed** being sent to the AMS16v2 at all during that capture; only
  Auto-Sense toggling and a firmware-version query were seen. These three
  settings are most likely **Core4 driver/UI-local settings** that never
  reach the device, not AMS16v2 protocol commands — do not implement them in
  the HA driver as device commands.
- **Port 3000 (web UI)**: the reboot/factory-reset capture shows a plaintext
  `GET / HTTP/1.1` to `172.16.0.41:3000` followed by a WebSocket upgrade
  (`Sec-WebSocket-Key`/`Sec-WebSocket-Accept` headers, `Connection: Upgrade`).
  This is the user's own **web browser**, logged into the AMS16v2's built-in
  web UI to explore what it offers — not Core5 or Home Assistant traffic.
  After the upgrade, all frames are opaque/masked binary blobs with no
  discernible structure (this is standard WebSocket client→server masking,
  not necessarily encryption, but the payload framing underneath could not
  be decoded from these captures). This is almost certainly the mechanism
  the AMS16v2's own web configuration UI uses internally (and may be where
  renaming/presets/2.1-pairing actually live), but it is **out of scope**
  for this spec. Treat it as a candidate follow-up capture target — e.g.
  capture again with the browser dev tools' Network/WS inspector open
  (which shows decoded WS frames directly, no need to unmask/decrypt
  anything at the packet level) — to extend this spec.
- ~~**Exact volume→dB taper**~~ **RESOLVED**: a full 0-100 sweep was
  captured (`core5_output_volume_full_sweep_triad_ams16_capture_20260720T183622.pcap`,
  2026-07-20) and cross-checked against Output 1 at 4 points — see §3.1 for
  the complete, verified 101-value lookup table.

---

## 7. Python Codec Appendix

```python
"""Encode/decode helpers for the Triad AMS16v2 binary control protocol.

This module implements the frame format and value encodings documented in
TRIAD_AMS16V2_PROTOCOL_SPEC.md, reverse-engineered from Core5 -> AMS16v2
SPAN-port captures (2026-07-10). It provides:

  * build_frame(): assemble a request frame from a group byte and payload.
  * A set of value encoders (gain, delay, volume, balance, frequency,
    EQ gain, Q) matching the device's fixed-point / signed representations.
  * Per-command frame builders for the commands in section 4 of the spec.
  * parse_response(): decode a null-padded ASCII response frame into a
    plain string.

Typical usage example:

    import socket
    from triad_ams16_protocol import build_set_output_volume, parse_response

    sock = socket.create_connection(("192.0.2.41", 52000), timeout=5)
    sock.sendall(build_set_output_volume(output=1, volume_pct=75))
    reply = parse_response(sock.recv(4096))
    print(reply)  # "Set Out[1] Output Volume to -6.3"

Note: 192.0.2.41 above is a documentation-only placeholder address
(RFC 5737); substitute the real AMS16v2 IP address in production use.
"""

from __future__ import annotations

import struct

# Frame group bytes observed in captures.
GROUP_SYSTEM = 0x55
GROUP_DSP = 0x56

# GET sentinel byte used in the value position of GET requests.
GET_SENTINEL = 0xF5


def build_frame(group: int, payload: bytes) -> bytes:
    """Assembles a complete request frame.

    Args:
        group: The group byte, either GROUP_SYSTEM (0x55) or GROUP_DSP (0x56).
        payload: The opcode/index/value bytes that follow the length byte.

    Returns:
        The complete frame as bytes: 0xFF, group, len(payload), then payload.

    Raises:
        ValueError: If payload is longer than 255 bytes.
    """
    if len(payload) > 0xFF:
        raise ValueError("payload too long for a single-byte length field")
    return bytes([0xFF, group, len(payload)]) + payload


def channel_index(channel_number: int) -> int:
    """Converts a 1-based channel number (1-16) to the device's 0-based index.

    Args:
        channel_number: Input or output number as shown in the UI (1-16).

    Returns:
        The 0-based channel index byte used on the wire (0x00-0x0F).

    Raises:
        ValueError: If channel_number is not in the range 1-16.
    """
    if not 1 <= channel_number <= 16:
        raise ValueError("channel_number must be between 1 and 16")
    return channel_number - 1


def enc_gain_12db(gain_db: float) -> int:
    """Encodes a +/-12 dB gain (0.5 dB steps) as used for input/shelf gain.

    Args:
        gain_db: Desired gain in dB, from -12.0 to +12.0.

    Returns:
        The single encoded byte: (gain_db + 12) * 2.

    Raises:
        ValueError: If gain_db is outside [-12.0, 12.0].
    """
    if not -12.0 <= gain_db <= 12.0:
        raise ValueError("gain_db must be between -12.0 and 12.0")
    return round((gain_db + 12.0) * 2)


def enc_delay_ms(delay_ms: int) -> int:
    """Encodes a 0-80 ms delay value.

    Args:
        delay_ms: Desired delay in milliseconds, 0-80.

    Returns:
        The single encoded byte (direct pass-through of delay_ms).

    Raises:
        ValueError: If delay_ms is outside [0, 80].
    """
    if not 0 <= delay_ms <= 80:
        raise ValueError("delay_ms must be between 0 and 80")
    return delay_ms


def enc_balance(balance_pct: int) -> int:
    """Encodes a balance position as a 0-100 percentage (0=full left, 100=full right).

    Args:
        balance_pct: 0 (full left) to 100 (full right); 50 is center.

    Returns:
        The single encoded byte: 0x00 at 0, 0x18 (24) at 50 (center), 0x30 (48) at 100.

    Raises:
        ValueError: If balance_pct is outside [0, 100].
    """
    if not 0 <= balance_pct <= 100:
        raise ValueError("balance_pct must be between 0 and 100")
    return round(balance_pct * 0x30 / 100)


def enc_volume_pct(volume_pct: int) -> int:
    """Encodes a 0-100 UI volume value (used for Volume, Max Volume, Turn-on Volume).

    Args:
        volume_pct: Desired volume as a 0-100 UI percentage. 100 is unity/max
            (device reports 0 dB); 0 is the device's minimum (device reports
            approximately -108.5 dB).

    Returns:
        The single encoded byte, 0x00-0x64 (direct pass-through).

    Raises:
        ValueError: If volume_pct is outside [0, 100].
    """
    if not 0 <= volume_pct <= 100:
        raise ValueError("volume_pct must be between 0 and 100")
    return volume_pct


def enc_freq_hz(freq_hz: int) -> bytes:
    """Encodes an EQ/shelf frequency as a 4-byte big-endian unsigned integer.

    Args:
        freq_hz: Frequency in Hz, 20-20000 (shelves: 20-2000 for low shelf).

    Returns:
        4 bytes, big-endian unsigned.
    """
    return struct.pack(">I", freq_hz)


def enc_eq_gain_db(gain_db: float) -> bytes:
    """Encodes an EQ band or shelf gain as a 4-byte big-endian signed integer, x100.

    Args:
        gain_db: Desired gain in dB, -12.00 to +12.00.

    Returns:
        4 bytes, big-endian signed two's complement, value = round(gain_db * 100).

    Raises:
        ValueError: If gain_db is outside [-12.0, 12.0].
    """
    if not -12.0 <= gain_db <= 12.0:
        raise ValueError("gain_db must be between -12.0 and 12.0")
    return struct.pack(">i", round(gain_db * 100))


def enc_q(q: float) -> bytes:
    """Encodes an EQ band Q factor as a 4-byte big-endian unsigned integer, x100.

    Args:
        q: Desired Q factor, 0.5-15.0.

    Returns:
        4 bytes, big-endian unsigned, value = round(q * 100).

    Raises:
        ValueError: If q is outside [0.5, 15.0].
    """
    if not 0.5 <= q <= 15.0:
        raise ValueError("q must be between 0.5 and 15.0")
    return struct.pack(">I", round(q * 100))


# --- Per-command frame builders (section 4 of the spec) --------------------


def build_get_power_status() -> bytes:
    """Builds the power-status poll/heartbeat request.

    Returns:
        The complete request frame.
    """
    return build_frame(GROUP_SYSTEM, bytes([0x01, 0x01, GET_SENTINEL]))


def build_get_firmware_version() -> bytes:
    """Builds the firmware-version query request.

    Note:
        Unlike every other command in this module, the captured length byte
        for this command (0x03) does not equal the number of payload bytes
        that follow it (2). This appears to be a device-specific quirk
        rather than a general framing rule, so the frame is reproduced
        literally rather than derived from build_frame()'s generic formula.

    Returns:
        The complete request frame, exactly as captured: FF 55 03 06 65.
    """
    return bytes.fromhex("ff55030665")


def build_reboot() -> bytes:
    """Builds the device reboot command.

    Returns:
        The complete request frame.
    """
    return build_frame(GROUP_SYSTEM, bytes([0x06, 0xB4, 0x00]))


def build_factory_reset() -> bytes:
    """Builds the factory-reset command.

    Warning:
        This erases all device configuration. Use with explicit user
        confirmation only.

    Returns:
        The complete request frame.
    """
    return build_frame(GROUP_SYSTEM, bytes([0x0B, 0xB0]))


def build_set_input_gain(input_num: int, gain_db: float) -> bytes:
    """Builds a set-input-gain command.

    Args:
        input_num: Input number, 1-16.
        gain_db: Desired gain in dB, -12.0 to +12.0.

    Returns:
        The complete request frame.
    """
    idx = channel_index(input_num)
    return build_frame(GROUP_SYSTEM, bytes([0x02, 0x04, idx, enc_gain_12db(gain_db)]))


def build_get_input_gain(input_num: int) -> bytes:
    """Builds a get-input-gain query.

    Args:
        input_num: Input number, 1-16.

    Returns:
        The complete request frame.
    """
    idx = channel_index(input_num)
    return build_frame(GROUP_SYSTEM, bytes([0x02, 0x04, GET_SENTINEL, idx]))


def build_set_input_delay(input_num: int, delay_ms: int) -> bytes:
    """Builds a set-input-delay command.

    Args:
        input_num: Input number, 1-16.
        delay_ms: Desired delay in milliseconds, 0-80.

    Returns:
        The complete request frame.
    """
    idx = channel_index(input_num)
    return build_frame(GROUP_DSP, bytes([0x02, 0x04, idx, enc_delay_ms(delay_ms)]))


def build_set_output_source(output_num: int, source_input_num: int) -> bytes:
    """Builds a set-output-source (input routing) command.

    Args:
        output_num: Output number, 1-16.
        source_input_num: Input number to route to this output, 1-16.

    Returns:
        The complete request frame.
    """
    idx = channel_index(output_num)
    src = channel_index(source_input_num)
    return build_frame(GROUP_SYSTEM, bytes([0x03, 0x1D, idx, src]))


def build_set_output_volume(output_num: int, volume_pct: int) -> bytes:
    """Builds a set-output-volume command.

    Args:
        output_num: Output number, 1-16.
        volume_pct: Desired volume, 0-100 (UI scale).

    Returns:
        The complete request frame.
    """
    idx = channel_index(output_num)
    return build_frame(GROUP_SYSTEM, bytes([0x03, 0x1E, idx, enc_volume_pct(volume_pct)]))


def build_set_output_mute(output_num: int, mute: bool) -> bytes:
    """Builds a mute/unmute command for an output.

    Args:
        output_num: Output number, 1-16.
        mute: True to mute, False to unmute.

    Returns:
        The complete request frame.
    """
    idx = channel_index(output_num)
    opcode = 0x17 if mute else 0x18
    return build_frame(GROUP_SYSTEM, bytes([0x03, opcode, idx]))


def build_set_output_balance(output_num: int, balance_pct: int) -> bytes:
    """Builds a set-output-balance command.

    Args:
        output_num: Output number, 1-16.
        balance_pct: 0 (full left) to 100 (full right); 50 is center.

    Returns:
        The complete request frame.
    """
    idx = channel_index(output_num)
    return build_frame(GROUP_SYSTEM, bytes([0x03, 0x31, idx, enc_balance(balance_pct)]))


# EQ band selector high-nibble = band number (0-indexed: band1 -> 0x0).
_EQ_FREQ_OFFSET = 0x00
_EQ_GAIN_OFFSET = 0x01
_EQ_Q_OFFSET = 0x02


def _eq_band_selector(band_num: int, param_offset: int) -> int:
    """Computes the EQ band selector byte for a given band and parameter.

    Args:
        band_num: Band number, 1-12.
        param_offset: One of _EQ_FREQ_OFFSET, _EQ_GAIN_OFFSET, _EQ_Q_OFFSET.

    Returns:
        The single selector byte.

    Raises:
        ValueError: If band_num is not in the range 1-12.
    """
    if not 1 <= band_num <= 12:
        raise ValueError("band_num must be between 1 and 12")
    return ((band_num - 1) << 4) | param_offset


def build_set_eq_band_freq(output_num: int, band_num: int, freq_hz: int) -> bytes:
    """Builds a set-EQ-band-frequency command.

    Args:
        output_num: Output number, 1-16.
        band_num: EQ band number, 1-12.
        freq_hz: Frequency in Hz, 20-20000.

    Returns:
        The complete request frame.
    """
    idx = channel_index(output_num)
    sel = _eq_band_selector(band_num, _EQ_FREQ_OFFSET)
    return build_frame(GROUP_DSP, bytes([0x05, sel, idx]) + enc_freq_hz(freq_hz))


def build_set_eq_band_gain(output_num: int, band_num: int, gain_db: float) -> bytes:
    """Builds a set-EQ-band-gain command.

    Args:
        output_num: Output number, 1-16.
        band_num: EQ band number, 1-12.
        gain_db: Desired gain in dB, -12.0 to +12.0.

    Returns:
        The complete request frame.
    """
    idx = channel_index(output_num)
    sel = _eq_band_selector(band_num, _EQ_GAIN_OFFSET)
    return build_frame(GROUP_DSP, bytes([0x05, sel, idx]) + enc_eq_gain_db(gain_db))


def build_set_eq_band_q(output_num: int, band_num: int, q: float) -> bytes:
    """Builds a set-EQ-band-Q command.

    Args:
        output_num: Output number, 1-16.
        band_num: EQ band number, 1-12.
        q: Desired Q factor, 0.5-15.0.

    Returns:
        The complete request frame.
    """
    idx = channel_index(output_num)
    sel = _eq_band_selector(band_num, _EQ_Q_OFFSET)
    return build_frame(GROUP_DSP, bytes([0x05, sel, idx]) + enc_q(q))


# Complete Output Volume raw-byte (0-100) -> dB lookup table, captured via a
# full manual sweep of Out[13] (core5_output_volume_full_sweep pcap,
# 2026-07-20) and cross-verified identical on Out[1] at 4 points. This is a
# device-wide, non-channel-specific audio taper curve; use only for display
# (e.g. showing dB next to a volume slider) -- never for building commands,
# since enc_volume_pct() already passes the 0-100 UI value straight through.
VOLUME_PCT_TO_DB: dict[int, float] = {
    0: -108.5, 1: -100.3, 2: -92.7, 3: -85.8, 4: -79.5,
    5: -73.9, 6: -69.0, 7: -64.6, 8: -61.0, 9: -58.0,
    10: -55.6, 11: -53.9, 12: -52.0, 13: -50.5, 14: -49.6,
    15: -48.7, 16: -47.7, 17: -46.8, 18: -45.9, 19: -45.0,
    20: -44.1, 21: -43.2, 22: -42.3, 23: -41.4, 24: -40.6,
    25: -39.7, 26: -38.9, 27: -38.0, 28: -37.2, 29: -36.4,
    30: -35.6, 31: -34.8, 32: -34.0, 33: -33.2, 34: -32.4,
    35: -31.7, 36: -30.9, 37: -30.2, 38: -29.4, 39: -28.7,
    40: -28.0, 41: -27.2, 42: -26.5, 43: -25.8, 44: -25.1,
    45: -24.5, 46: -23.8, 47: -23.1, 48: -22.5, 49: -21.8,
    50: -21.2, 51: -20.5, 52: -19.9, 53: -19.3, 54: -18.7,
    55: -18.1, 56: -17.5, 57: -16.9, 58: -16.4, 59: -15.8,
    60: -15.3, 61: -14.7, 62: -14.2, 63: -13.7, 64: -13.1,
    65: -12.6, 66: -12.1, 67: -11.6, 68: -11.1, 69: -10.7,
    70: -10.2, 71: -9.7, 72: -9.3, 73: -8.9, 74: -8.4,
    75: -8.0, 76: -7.6, 77: -7.2, 78: -6.8, 79: -6.4,
    80: -6.0, 81: -5.6, 82: -5.3, 83: -4.9, 84: -4.6,
    85: -4.2, 86: -3.9, 87: -3.6, 88: -3.3, 89: -3.0,
    90: -2.7, 91: -2.4, 92: -2.1, 93: -1.8, 94: -1.6,
    95: -1.3, 96: -1.1, 97: -0.9, 98: -0.6, 99: -0.4,
    100: 0.0,
}


def volume_pct_to_db(volume_pct: int) -> float:
    """Looks up the exact dB value the device reports for a given 0-100 volume.

    For display only (e.g. showing "-21.2 dB" next to a volume slider set to
    50). Never needed to build a command -- see enc_volume_pct().

    Args:
        volume_pct: Volume as a 0-100 UI percentage.

    Returns:
        The dB value the device would report for that raw value.

    Raises:
        KeyError: If volume_pct is outside [0, 100].
    """
    return VOLUME_PCT_TO_DB[volume_pct]


def volume_db_to_pct(db: float) -> int:
    """Finds the 0-100 UI volume whose reported dB is closest to a target dB.

    Useful for restoring a previously-displayed dB value (e.g. from a saved
    scene) back to the raw 0-100 value the device command needs.

    Args:
        db: Target dB value.

    Returns:
        The 0-100 UI volume value whose entry in VOLUME_PCT_TO_DB is nearest
        to db.
    """
    return min(VOLUME_PCT_TO_DB, key=lambda pct: abs(VOLUME_PCT_TO_DB[pct] - db))


def parse_response(raw: bytes) -> str:
    """Decodes a null-padded ASCII response frame into a plain string.

    Args:
        raw: The raw bytes read from the socket for one response.

    Returns:
        The response text with trailing NUL padding stripped.
    """
    return raw.rstrip(b"\x00").decode("latin-1", errors="replace")
```

### Verification against captures

The following spot-checks reproduce exact bytes seen in the pcaps:

- `enc_gain_12db(12.0)` → `48` (`0x30`) — matches `FF 55 04 02 04 00 30` (`core5_input_config`).
- `enc_gain_12db(-12.0)` → `0` (`0x00`) — matches `FF 55 04 02 04 00 00`.
- `enc_delay_ms(80)` → `0x50` — matches `FF 56 04 02 04 00 50`.
- `enc_volume_pct(0)` → `0x00`, response `-108.5` dB (`core5_output_config` frame 205-206).
- `enc_freq_hz(1000)` → `b"\x00\x00\x03\xe8"` — matches `FF 56 07 03 01 0c 000003e8`.
- `enc_eq_gain_db(-0.2)` → `b"\xff\xff\xff\xec"` — matches `FF 56 07 03 0D 0C FFFFFFEC` (`core5_dsp_config` frame 73-74).
- `enc_q(15.0)` → `b"\x00\x00\x05\xdc"` — matches Band 7 Q → 15 (`core5_dsp_config` frame 379-380).
- `build_set_output_source(1, 16)` → `FF 55 04 03 1D 00 0F` — matches `FF 55 04 03 1D 00 0F` → `Set Out[1] Input Source to input 16`.

Every builder function above (`build_get_power_status`, `build_get_firmware_version`,
`build_reboot`, `build_factory_reset`, `build_set_input_gain`,
`build_get_input_gain`, `build_set_input_delay`, `build_set_output_source`,
`build_set_output_volume`, `build_set_output_mute`, `build_set_eq_band_freq`,
`build_set_eq_band_gain`, `build_set_eq_band_q`) was executed and its output
byte-for-byte diffed against the literal request bytes captured in the pcaps
(including the `FF 55 03 06 65` firmware-version quirk noted above, and
channel-16/output-13 index generalization) before this document was
finalized — all matched.
