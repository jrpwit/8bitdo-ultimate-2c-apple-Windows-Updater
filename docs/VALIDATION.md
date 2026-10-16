# Validation and limits

## Hardware result

One **8BitDo Ultimate 2C Wireless Controller**, actual firmware v1.09, was investigated and patched. Host: Apple Silicon Mac, macOS 26.6, build 25G83. USB descriptor `bcdDevice=0114` was observed, but it was not the installed firmware revision: the application header read from flash reported 109 / v1.09.

The final generated DAT SHA-256 was:

`e52216167e7f3f5e0a15d14b68b345b54a12a8b637b1052ddc1d595a0a57c88f`

### Recovery and installation directly observed

- Physical power-off / LB+RB / USB insertion produced BOOT `2dc8:3208` independently of the normal application.
- Identity/read/reset commands were exercised before writing; normal USB `2dc8:310a` return was separately observed.
- Original application readback matched the official v1.09 payload. Boot region, final-sector tail and update metadata/staging snapshots were preserved locally.
- The successful final identity revision programmed physical sectors `17000` and `18000`. Full target/application-tail readback matched; the boot region was unchanged. Reset acknowledged and normal USB startup was observed.
- A fresh Bluetooth connection exposed `2dc8:6002`, revision `0001`. Its live 116-byte HID descriptor exactly matched the original.

The final hardware flash transitioned from an earlier experimental `2101/r0100` identity, not directly from stock. The final image's unchanged-byte checks and hashes are independent of that starting point. The **public writer deliberately supports stock v1.09 as its starting baseline**, not those intermediate experiments.

### Native Mac input directly measured

A completed 180-second capture used Apple's GameController API and non-exclusive HID observation; no controller output/firmware commands were sent.

- One native controller, extended and micro profiles present.
- 1,219 native events; 20,863 HID input reports; 1,216 consecutive report changes.

| Native axis | Minimum | Maximum | Last value after release |
|---|---:|---:|---:|
| Left X | -1.0000 | +1.0000 | 0.0000 |
| Left Y | -1.0000 | +1.0000 | 0.0000 |
| Right X | -1.0000 | +1.0000 | 0.0000 |
| Right Y | -1.0000 | +1.0000 | 0.0000 |

The left and right stick callbacks contributed 556 and 543 samples respectively. Native D-pad right `(1,0)`, up `(0,1)`, left `(-1,0)`, down `(0,-1)` and neutral releases were captured.

The original observer printed only the first 100 native events. Do not infer final-revision face-button, trigger or diagonal proof from that log; later events were counted but not individually retained. The public observer summarizes those controls separately so later captures can provide that evidence.

### Apple TV: user-confirmed, not instrumented

After instructions to forget the old pairings, freshly pair with Apple TV and test menu navigation plus supported-game controls, the owner reported:

> it works perfectly

This is the acceptance report for the actual Apple TV. The exact tvOS version, Apple TV model and game name were **not recorded**. “Latest tvOS” was the user's description at the time, not an independently measured version. Do not convert this into an exact version or claim it establishes compatibility with every Apple device.

## Public-tool verification boundary

The repository contains a source-only adaptation of the host tools used during the investigation. It removes private paths and experimental-baseline dependencies, adds saved update-region checks, and packages a stock-to-patched workflow. The original controller was **not** reflashed or reset to validate publication.

Offline checks cover patch byte confinement/output identity, unsafe input/output handling, BOOT acknowledgements, erase/program boundaries, restoration sector selection, and saved metadata rejection. The real original firmware fixture is optional and local; it is never committed. Reproduce the checks with `make test`, supplying `EIGHTBITDO_STOCK_DAT` as explained in the README.

Publication checks completed on 2026-10-16:

- All three native tools compiled with Clang, ARC, `-Wall` and `-Wextra`.
- All **11 Python tests passed with zero skips**, using an actual pinned stock image downloaded to a private temporary directory.
- Native offline protocol/range/page/metadata tests passed under AddressSanitizer and UndefinedBehaviorSanitizer.
- The actual downloader → patch-generator → native `--check-image` workflow succeeded. The generated file matched the working image SHA-256; both stock and patched offline image checks passed.
- Six negative CLI scenarios rejected wrong image roles, missing tail, corrupted boot backup, non-stock application backup and valid-checksum pending-update metadata during artifact preflight, before device access.
- Independent static protocol and publication/host-security reviews found no blocking findings. These reviews and offline checks do not establish new hardware compatibility.


A successful build/unit test or generated image is not proof that another controller's recovery/flash/input works. Users must perform the documented non-flashing recovery check, keep their own backups, and measure their own input. Unsupported snapshots/hashes are rejected rather than relaxed.

## Not established

- Additional controller units, hardware revisions, other bootloaders or firmware releases.
- Exact minimum macOS/tvOS versions, Intel Mac builds, Windows/Linux flashing hosts.
- New rumble, motion sensing, battery reporting, or independent extra-button support.
- Behavior on Android or other Bluetooth hosts after identity impersonation.
- USB/2.4-GHz gaming compatibility beyond the observed normal USB startup.
- Recovery from arbitrary physical damage, bootloader damage, interrupted writes or a full-chip erase. No deliberate brick/damaged-image restore experiment was performed.

No raw firmware, device-specific dumps, private addresses or unredacted logs are included. The published measurements and [machine-readable facts](../data/firmware.json) preserve the evidence without those artifacts.
