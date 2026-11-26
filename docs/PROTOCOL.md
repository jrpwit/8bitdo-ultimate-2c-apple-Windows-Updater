# Protocol and patch rationale

All addresses/offsets below are for the pinned Ultimate 2C Wireless **controller** firmware v1.09. These are not generic 8BitDo commands. Range ends are exclusive. Raw vendor firmware and Apple controller-database files are deliberately not included.

## Why an identity patch was sufficient

The stock unit paired and delivered changing Bluetooth LE HID reports, but the Mac's native GameController API exposed no controller. The firmware's Bluetooth PnP identity was `2dc8:301b`, revision `0001`. Button/stick transmission itself was present.

Apple's local controller database uses identity-dependent input profiles. Two unsuccessful compatibility identities explained why simply getting a recognized controller was insufficient:

| Attempt | What was found |
|---|---|
| Ultimate 2 Wireless profile, `2dc8:6012/r1` | Selected a profile with 22 required elements; two required inputs were absent from this controller's normalized descriptor. Native model preparation failed. |
| SN30 Pro for Android profile, `2dc8:2101/r0100` | Required elements matched and native recognition worked, but stick expressions assumed 16-bit samples. The controller transmits 8-bit samples; a neutral raw value of 127 was interpreted near a corner. |
| SN30 Pro+ profile, `2dc8:6002/r1` | Uses the HID descriptor's logical ranges. The unchanged report format produced full signed native stick travel, centered release and cardinal D-pad events. Apple TV success was user-confirmed after fresh pairing. |

The final Apple profile was located under `GameControllers-SDL.bundle/Personalities/v11720/p24578/r1/8BitDo_SN30_Pro+/Default.plist` on the tested Mac. This is a lookup observation, not a redistributed profile or an assertion that every OS includes the same database.

The patch changes the internal Bluetooth PnP product ID to select that profile. It does **not** change the advertised Bluetooth name: the controller still appears as **8BitDo Ultimate 2C Wireless** on Windows and Apple TV.

The reference signed-axis normalization is `2 * raw / 255 - 1` (Y polarity inverted for conventional up-positive coordinates). Apple's runtime additionally applies its own input processing; actual native released axes were measured as zero. The correction selects the matching existing profile rather than rewriting firmware input values or inventing missing buttons.

## Unchanged Bluetooth report contract

The live descriptor was 116 bytes and matched the stock image byte-for-byte, SHA-256:

`faf72db6502aec039db8e5c163c3f01e6f2c16486439d1dece7b91b140e32a58`

Observed input report, including report ID: **11 bytes**.

| Byte(s) | Meaning |
|---|---|
| 0 | Report ID `01` |
| 1 | Hat low nibble: 0 up, 2 right, 4 down, 6 left; odd values are diagonals; null `0f` |
| 2, 3 | Left stick X, Y, unsigned 8-bit |
| 4, 5 | Right stick X, Y, unsigned 8-bit |
| 6, 7 | Right trigger, left trigger, unsigned 8-bit |
| 8–9 | Sixteen button bits, little-endian |
| 10 | Descriptor-declared battery byte; zero in the displayed captured packets. Do not infer battery behavior from that byte alone. |

Known button bit indices: A=0, B=1, X=3, Y=4, left shoulder=6, right shoulder=7, Options=10, Menu=11, Home=12, left-stick click=13, right-stick click=14. These facts describe the original wire contract; they do not promise every physical extra button has an independent report bit.

## Binary patch

The DAT wrapper has seven little-endian 32-bit words, length 28 bytes. Its pinned values are recorded in [the manifest](../data/firmware.json). It identifies the original controller family; it is **not** changed to SN30 firmware.

The seven-byte GATT PnP ID at DAT offset `0x113dc` changes from `02 c8 2d 1b 30 01 00` to `02 c8 2d 02 60 01 00`. Only its two product-ID bytes differ. GATT handle `000e` identifies UUID `2a50`; its descriptor/pointer layout is checked before patching.

The stored CRC word at DAT `0x1228c` changes from `0xa8be5c24` to `0xa204a342`. It is computed as:

```python
(~zlib.crc32(dat[0x1c:0x1228c])) & 0xffffffff
```

Thus the only changed DAT offsets are `0x113df`, `0x113e0`, and `0x1228c` through `0x1228f`. The generator pins the entire input and output SHA-256, verifies exact change confinement, and refuses unknown or already modified input. This also checks the original executable bytes and alignment padding remain unchanged, without claiming source equivalence from a decompiler.

## Flash layout and preserved state

| Flash range | Role | Procedure |
|---|---|---|
| `[00000,06000)` | Saved boot region | Pin and compare; never write |
| `[06000,18400)` | Application, 74,752 bytes | Flash only differing sectors; restore can repair entire application |
| `[18400,19000)` | 3,072-byte tail of final erase sector | Preserve and verify with application |
| `[3f000,40000)` | Update metadata sector | Save/validate; never write |
| `[40000,53000)` | Saved staging footprint | Save/compare; never write |

The patch changes data in physical sectors `17000` and `18000`, each 4 KiB. Programming requests never cross a 256-byte flash page and carry no more than 46 data bytes. Final verification includes the full `[06000,19000)` application/tail footprint, not just changed offsets.

This is **not a full-chip backup**. Regions outside these ranges, including any unrelated calibration or persistent state, are not reconstructed and must never be written by this workflow.

Update metadata has a Modbus CRC16 (initial `ffff`) over its first 48 bytes, stored at offset 48. Pending-install magic at byte 24 and length at byte 32 must both be zero. A structurally valid pending update is still a reason to stop: a restart must not unexpectedly apply a staged firmware image.

## Host transport differences

| Property | Normal application | BOOT |
|---|---|---|
| USB VID:PID | `2dc8:310a` | `2dc8:3208` |
| HID usage page/usage | `ff7a/1` | `008c/1` |
| Output report ID | `81` | `00` (unnumbered) |
| Host command offset | 2 | 1 |
| Host count offset | 6 | 5 |
| Host total offset | 10 | 9 |
| Host address offset | 14 | 13 |
| Host data offset | 18 | 17 |

Packets/reports are 64 bytes. The normal-mode reader sends **only read command 5**. Normal application and BOOT erase behavior differ; do not send a BOOT erase packet to an application-mode endpoint. The public writer only modifies the application while physically in BOOT.

BOOT command facts recovered and checked against this unit:

- `8`: identity query. The response names application family `301b`; this is not the patched BLE PID.
- `5`: flash read; host restricts addresses/lengths to the documented saved regions.
- `4`: erase **one aligned 4-KiB sector** per request. The host restricts it to the application/tail footprint.
- `3`: program; packet payload uses Modbus CRC16, bounded to a flash page.
- `7`: explicit reset, used only after successful verification.

For BOOT replies, bytes 2–3 are status; bytes 4–5 identify the requested command. Count is at 6, total at 10, address at 14 and data at 18. **Erase clears count and total in its acknowledgement**, whereas program/read retain the requested bounds. Treating all ACKs identically caused a host-side bug that was caught and regression-tested before the original flash. An ACK alone is not proof of erase/program success: the tool reads flash contents back.

Identity/read/reset, physical LB+RB recovery and normal USB return were exercised before writing. A software jump-to-boot request did not cause re-enumeration and is not part of the public workflow. On failure there is no automatic retry, re-entry or reset.

## Sources and legal boundary

- [Exact-model public research](https://github.com/Crazyawk/8bitdo-ultimate2c-macos-rumble), including its firmware/bootloader notes; [credits](../THIRD_PARTY.md).
- [8BitDo's official web updater](https://web.8bitdo.com/) supplied application read-command routing/framing evidence; the original unit was read back and its image matched the pinned vendor payload.
- [Official model](https://www.8bitdo.com/ultimate-2c-wireless-controller/) and [manual](https://download.8bitdo.com/Manual/Controller/Ultimate/Ultimate-2C-Wireless-Controller-EN.pdf).
- Apple's locally installed controller assets and native GameController runtime supplied the identity/profile and actual input observations.

Protocol facts and minimal patch offsets are published for reproducibility. No complete Apple profiles, firmware images, bootloader dumps, private network addresses or original raw diagnostic logs are distributed.
