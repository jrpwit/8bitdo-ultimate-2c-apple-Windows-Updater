# 8BitDo Ultimate 2C Wireless — Bluetooth on Mac and Apple TV

An experimental, identity-only firmware patch for the **8BitDo Ultimate 2C Wireless Controller** (the Windows/Android model). It makes Apple select an existing controller profile that understands this controller's input reports.

**Result:** native Bluetooth input was measured on one Mac; the same controller's owner confirmed that it works correctly on Apple TV after fresh pairing. This is not an official 8BitDo update, Apple certification, or a guarantee for other hardware/OS versions. See [measured results and limitations](docs/VALIDATION.md).

> **Windows users:** a complete Windows-native port of the reader, writer and observer lives in this repository, with one-click `.bat` wrappers and a step-by-step guide. Start at **[WINDOWS.md](WINDOWS.md)**. The firmware patch, hashes, flash boundaries and every safety guard are identical; the original macOS sources remain unchanged. Windows is the computer used to flash — the patch still targets macOS and Apple TV, not Windows drivers.

## What changes

Only **six bytes** of the exact official controller firmware v1.09:

- Two bytes: Bluetooth PnP product ID `2dc8:301b` → `2dc8:6002` (SN30 Pro+ compatibility profile).
- Four bytes: the firmware's internal Telink CRC.

PnP version remains `0001`. The original executable code, 116-byte HID report descriptor, report layout, radio stack, button scanning and USB identity stay unchanged. **This does not install SN30 Pro+ firmware.** It does not add rumble, motion support, or separate extra-button reports.

The final profile was selected because it uses the descriptor's logical stick range. An earlier profile recognized the controller but treated its 8-bit stick samples as 16-bit values. Controller recognition alone was not enough. [Technical details](docs/PROTOCOL.md).

## Scope and risk — read before proceeding

- **Only this model and exact v1.09 image.** NOT Ultimate 2C Bluetooth (Switch), Ultimate 2, Ultimate 2 Wireless, a receiver/dongle, or another 8BitDo model.
- The **macOS** workflow requires a Mac, USB data cable, Xcode Command Line Tools, and Python 3.10+. The **Windows** workflow requires Windows 10/11 (64-bit), a USB data cable, and Python 3.10+; see [WINDOWS.md](WINDOWS.md). Native tooling was exercised on an Apple Silicon Mac; the Windows port is checked offline and awaits first independent hardware validation.
- **Firmware flashing can brick a controller.** Power loss, hardware variants, or protocol differences remain risks. A backup and recovery mode reduce risk; they do not eliminate it.
- The public tools are adapted from the tested experiment for a **stock v1.09 starting point**. The adapted tools are checked offline; the working controller was not reflashed merely to test publication. See the validation boundary below.
- Guarded commands pin the known image, bootloader and sector-tail hashes and require your own snapshots. If a check fails, **stop**. There is intentionally no `--force` option.
- No vendor firmware, Apple database files, device dumps, compiled executables or private logs are distributed. Firmware is obtained from its vendor and patched locally. The source license does **not** license vendor firmware.
- Do not use an updater to install firmware intended for the impersonated SN30 Pro+. Use only this exact-model workflow or the original controller's supported vendor recovery process.

## 1. Get and build the tools

```sh
git clone https://github.com/vomba/8bitdo-ultimate-2c-apple.git
cd 8bitdo-ultimate-2c-apple
make
mkdir -p work
```

If development tools are absent, install Apple's Command Line Tools first (`xcode-select --install`). Python must be available as `python3`.

On Windows there is no `make` step: run `windows\setup.bat` instead and follow **[WINDOWS.md](WINDOWS.md)** from section 4 onward.

`make` only compiles local source; it never contacts a controller. Keep `work/` private and backed up. `.gitignore` excludes firmware and dumps, but do not rely on that when sharing files manually.

## 2. Obtain the exact original firmware and generate the patch

```sh
python3 tools/fetch_firmware.py work/original-v1.09-restore.dat
python3 tools/patch_identity.py \
  work/original-v1.09-restore.dat work/patched-v1.09-BLE6002-r0001.dat
```

The vendor's observed download endpoint uses plain HTTP. The downloader accepts only **74,780 bytes with the pinned SHA-256**, checks before creating the output, and refuses to overwrite files. A changed/unavailable endpoint is a failure, not permission to use another image. You may instead obtain the exact official image yourself and supply it to the patch generator.

| Image | SHA-256 |
|---|---|
| Original v1.09 DAT | `87349e603bb92d6ae9ff6defb6f32b10de2f2d3252fe4e442fa7993f982f2a5a` |
| Patched v1.09 DAT | `e52216167e7f3f5e0a15d14b68b345b54a12a8b637b1052ddc1d595a0a57c88f` |

Generating a file does **not** flash anything. Machine-readable offsets, hashes and identities are in [data/firmware.json](data/firmware.json).

## 3. Read and preserve YOUR controller's stock state

Connect the controller directly by USB in normal mode; close other controller/updater applications. Connect only one matching controller. It must expose USB `2dc8:310a`, including the vendor HID interface. Read its actual firmware version:

```sh
./build/read_firmware
```

**Required: actual firmware v1.09.** USB `bcdDevice`/reported device version `1.14` was not the firmware version on the tested unit. If your firmware differs, stop; do not force these commands or assume that installing/downgrading firmware is safe.

Save all four snapshots to new filenames:

```sh
./build/read_firmware --backup work/original-application-v1.09.bin
./build/read_firmware --backup-boot work/original-boot-region.bin
./build/read_firmware --backup-padding work/original-application-sector-tail.bin
./build/read_firmware --backup-update work/original-update-metadata-and-staging.bin
./build/boot_firmware --check-image work/patched-v1.09-BLE6002-r0001.dat
```

Each backup command only issues bounded reads and refuses an existing output. Do not proceed after an incomplete backup. The image check verifies that the raw application backup equals the official stock image, the bootloader/tail match the known supported variant, and saved update metadata has a valid checksum with no pending installation. These snapshots cover the regions relevant to this procedure, **not the entire flash chip**. Keep them and the stock DAT outside the computer as well; never substitute another person's snapshots.

## 4. Validate recovery BEFORE flashing

1. Unplug USB and power the controller off (hold Home for three seconds).
2. Hold **LB + RB**, the ordinary shoulder buttons — **not** LT/RT or L4/R4.
3. Reconnect the USB data cable while holding both through enumeration, then release.
4. It should appear as **8BitDo Boot**, USB `2dc8:3208`.

Run the non-flashing recovery check with an explicit reset:

```sh
./build/boot_firmware --verify-reset work/original-v1.09-restore.dat
```

It must verify the bootloader identity and saved stock state, then acknowledge reset. **Also observe the controller returning to normal USB mode**; an acknowledgement alone is not proof of normal startup. On macOS:

```sh
ioreg -r -n '8BitDo Ultimate 2C Wireless Controller' -l -w 0 -d 1
```

Confirm `idVendor = 11720` (`2dc8`) and `idProduct = 12554` (`310a`). If recovery, reads, reset or normal startup fails, stop without flashing. Do not try alternate boot packets.

## 5. Flash only after recovery validation

Repeat the physical **power off → hold LB+RB → connect USB** recovery sequence. Then:

```sh
./build/boot_firmware --flash work/patched-v1.09-BLE6002-r0001.dat
```

**Do not disconnect USB or let the computer sleep** — on Windows, the host is your Windows PC. The writer checks the live stock baseline and preserved regions before erasing. It replaces only the two differing 4-KiB sectors, verifies erased bytes, respects 256-byte programming-page boundaries, and reads back the complete application, sector tail, bootloader and saved update regions before resetting.

If a transfer/verification fails: **do not retry the flash or reset blindly**. The tool stops without automatic reset; preserve BOOT access and all backups. Read the reported failure before attempting recovery. The stock baseline check intentionally prevents rerunning `--flash` on an already patched controller.

## 6. Fresh Bluetooth pairing and acceptance checks

Unplug USB. Put the switch in **BT**, turn the controller on, and hold **Pair for three seconds**. Forget old pairings on each target before pairing again; cached identity/profile data can otherwise survive the firmware change. The advertised name can still be **8BitDo Ultimate 2C Wireless**.

### Mac

Disconnect other gamepads first: HID is matched by VID/PID, but native GameController observations enumerate all connected gamepads. The observer reports measurements rather than an automatic compatibility verdict.

Pair in System Settings → Bluetooth, then:

```sh
./build/observe_controller 60
```

While the observer is running, exercise each D-pad direction and diagonal, sweep both sticks fully and release them, press A/B/X/Y, and squeeze both triggers. Check native GameController events, four-axis full travel and centered release — not just Bluetooth's “Connected” status. The observer sends no output reports or firmware commands.

### Apple TV

1. Disconnect/forget the controller on any other computer (Mac or Windows) so it cannot reclaim the connection.
2. Apple TV: Settings → Remotes and Devices → Bluetooth → forget the old controller pairing.
3. Enter pairing mode and pair afresh.
4. Test D-pad/left-stick menu navigation and a controller-supported game, including movement, right-stick camera where supported, buttons and triggers.

Only local Mac-side measurements are instrumented here. Apple TV success was reported by the original user; repeat these checks on your own device. Other Bluetooth hosts and 2.4-GHz/USB behavior have not been newly validated by this patch.

## Restore stock firmware

Keep the original DAT and your own four snapshots. Enter physical LB+RB USB recovery, then:

```sh
./build/boot_firmware --restore work/original-v1.09-restore.dat
```

Restore is intentionally broader than the two-sector patch: it rewrites all 19 application/tail sectors so a damaged live application can be repaired. It still refuses a mismatched bootloader or changed saved update region and never writes bootloader/update storage. It verifies before reset. **This is a recovery capability, not a guarantee against every failure.** Full damaged-image restoration was not deliberately hardware-tested. Fresh Bluetooth pairing is needed again after restoration.

Official updates can overwrite the compatibility patch. Do not patch a new firmware version with these offsets. Restore stock before using normal vendor updates, and do not assume that these backups remain an appropriate downgrade after future vendor changes.

## Tests, support and credits

```sh
# Offline tests; the optional stock fixture remains local and untracked.
EIGHTBITDO_STOCK_DAT="$PWD/work/original-v1.09-restore.dat" make test
```

On Windows, run `windows\test.bat` instead. It runs the same offline suite; see [WINDOWS.md](WINDOWS.md) for the optional `EIGHTBITDO_STOCK_DAT` setting.

When reporting a problem, include the exact controller model, firmware version, OS version, failed command and non-sensitive error text. **Do not attach full dumps, Bluetooth addresses or private logs.** A different bootloader/hash is an unsupported variant, not a reason to disable checks.

- [Protocol and patch rationale](docs/PROTOCOL.md)
- [Validation evidence and unverified boundaries](docs/VALIDATION.md)
- [Third-party credits and license notices](THIRD_PARTY.md)
- [Original model and vendor support](https://www.8bitdo.com/ultimate-2c-wireless-controller/)
- [8BitDo's official Apple compatibility list](https://www.8bitdo.com/apple/)

MIT-licensed project source. Vendor firmware and Apple software remain their owners' property. Not affiliated with or endorsed by 8BitDo or Apple.
