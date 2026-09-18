# Triad AMS TCP Protocol Reference

This documents the device protocol used by `custom_components/triad_ams`,
including the extended command set reverse-engineered from packet captures of
third-party control software communicating with a Triad AMS-16 (firmware
V1.0054). All commands travel over a plain TCP connection to port `52000`.

## Framing

Two frame families exist. Both start with a magic byte pair, followed by a
length byte that covers the remaining payload.

- `FF 55 <len> <group> <opcode> [args...]` — original commands with
  single-byte values.
- `FF 56 <len> <group> <opcode> [args...]` — extended commands. Setters
  carry a 32-bit big-endian **signed** value; gain and Q values are scaled
  by 100 on the wire (e.g. `+12.00 dB` → `0x000004B0`).

Queries append `F5` after the opcode, followed by the 0-based channel byte.
Responses are null-terminated ASCII strings (padded to 150 bytes on the
wire), e.g. `Set Out[13] Low Shelf gain to 12`.

Channels (inputs, outputs) are 0-based on the wire and 1-based in responses.

The device also emits unsolicited `AudioSense:Input[N]: 0|1` events (N is
0-based) when input signal detection changes.

### Value encodings

| Kind | Encoding | Range |
| --- | --- | --- |
| Volume-like (volume, max volume, turn-on volume) | 1 byte, `0x00`–`0x64` | 0–100 |
| ±12 dB offsets (input gain, balance, legacy bass/treble) | `(dB + 12) * 2` | `0x00`–`0x30`, `0x18` = 0 dB |
| Sub volume offset (−12..0 dB) | `(dB + 12) * 2` | `0x00`–`0x18` |
| Test tone volume (−24..0 dB) | `(dB + 24) * 2` | `0x00`–`0x30` |
| Delays | 1 byte, milliseconds | 0–80 |
| FF56 frequencies | int32, Hz | e.g. 20–20000 |
| FF56 gain / Q | int32, value × 100 | e.g. −1200..1200 |

## Command table

`out`/`in` are 0-based channel bytes; `v4` is a 4-byte big-endian signed
value. Get variants insert `F5` before the channel byte.

### Routing, volume, mute (previously known)

| Function | Set | Get |
| --- | --- | --- |
| Route output to input | `FF 55 04 03 1D out in` | `FF 55 04 03 1D F5 out` |
| Disconnect output | `FF 55 04 03 1D out <input_count>` | — |
| Output volume | `FF 55 04 03 1E out val` | `FF 55 04 03 1E F5 out` |
| Mute on / off | `FF 55 03 03 17 out` / `FF 55 03 03 18 out` | `FF 55 04 03 17 F5 out` |
| Volume step up / down | `FF 55 03 03 13/14 out` (large: `15/16`) | — |
| Trigger zones 1-8 / 9-16 / ASG on | `FF 55 03 05 50 00/01/02` | — |
| Trigger zones off | `FF 55 03 05 51 00/01/02` | — |

### Input settings (new)

| Function | Set | Get |
| --- | --- | --- |
| Input gain (±12 dB) | `FF 55 04 02 04 in val` | `FF 55 04 02 04 F5 in` |
| Input delay (0–80 ms) | `FF 56 04 02 04 in ms` | `FF 56 04 02 04 F5 in` |
| Audio sense (signal detect) | — | `FF 56 04 02 03 F5 in` |

### Output settings (new)

| Function | Set | Get |
| --- | --- | --- |
| Max volume | `FF 55 04 03 1F out val` | `FF 55 04 03 1F F5 out` |
| Turn-on (start) volume | `FF 55 04 03 33 out val` | `FF 55 04 03 33 F5 out` |
| Balance (±12 dB) | `FF 55 04 03 31 out val` | `FF 55 04 03 31 F5 out` |
| Loudness on / off | `FF 55 03 03 1A/1B out` | `FF 55 04 03 1A F5 out` |
| Output delay (0–80 ms) | `FF 56 04 03 09 out ms` | `FF 56 04 03 09 F5 out` |
| Output DSP mode | `FF 56 04 03 0B out mode` | `FF 56 04 03 0B F5 out` |
| Stereo / mono (legacy) | `FF 55 03 03 10 / 11 out` | `FF 55 04 03 10 F5 out` |
| Bass / treble (legacy, ±12 dB) | `FF 55 04 03 2F / 30 out val` | `... F5 out` |

Output DSP modes: `0` = DSP Bypass Stereo, `1` = Stereo, `2` = Mono,
`3` = 2.1 Stereo, `4` = 2.1 Mono, `5` = Test Signal.

### Shelf filters (bass / treble tone controls, new)

| Parameter | Low shelf | High shelf |
| --- | --- | --- |
| Frequency | `FF 56 07 03 03 out v4` | `FF 56 07 03 01 out v4` |
| Gain (×100) | `FF 56 07 03 0D out v4` | `FF 56 07 03 0C out v4` |
| Q (×100) | `FF 56 07 03 04 out v4` | `FF 56 07 03 02 out v4` |

Gets use `FF 56 04 03 <op> F5 out`.

### 12-band room EQ (new)

Sub-opcode = `(band - 1) * 0x10 + offset`, band 1–12, offset `0` =
frequency, `1` = gain (×100), `2` = Q (×100).

- Set: `FF 56 07 05 <sub> out v4`
- Get: `FF 56 04 05 <sub> F5 out`
- EQ lock: `FF 56 04 03 08 out 01|00`; query `FF 56 04 03 08 F5 out`

### 2.1 crossover (new)

| Function | Set | Get |
| --- | --- | --- |
| Crossover frequency | `FF 56 07 03 05 out v4` | `FF 56 04 03 05 F5 out` |
| Crossover type (0–5) | `FF 56 04 03 06 out val` | `FF 56 04 03 06 F5 out` |
| Sub volume offset | `FF 56 04 03 07 out val` | `FF 56 04 03 07 F5 out` |

Crossover types: `0/1/2` = Butterworth 12/24/48 dB/Oct, `3/4/5` =
Linkwitz-Riley 12/24/48 dB/Oct.

### Test tone (new)

- Volume (−24..0 dB): `FF 56 04 04 01 out val`
- The tone itself is enabled by selecting output mode `5` (Test Signal).

### Device-level (new)

| Function | Command | Response |
| --- | --- | --- |
| Reboot | `FF 55 03 06 B4 00` | `Reboot Command` |
| Factory reset (not exposed) | `FF 55 02 0B B0` | `Factory Reset Command` |
| Firmware version | `FF 55 03 06 65` | `Fw version : V1.0054` |
| MAC address | `FF 55 03 08 80 F5` | `Get MAC Add 00:0F:FF:xx:xx:xx` |
| Power status | `FF 55 03 01 01 F5` | `Get Power status : Working` |
| Power on / off | `FF 55 02 01 01 / 02` | (off requires physical reboot!) |

## Timing notes (observed)

- Minimum inter-command delay: 25 ms (the integration uses 150 ms).
- Routing (`set output to input`) wants ~100 ms before the next command.
- Output mode / crossover / sub offset commands want ~50 ms.
- Power off is avoided: recovering requires a physical power cycle. This
  integration does not send it.
