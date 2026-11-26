# Windows guide — 8BitDo Ultimate 2C Apple compatibility patch

This is a complete Windows-native port of the macOS tools in this repository.
The firmware patch, hashes, flash boundaries, recovery checks and safety rules
are unchanged. The original `native/*.m` files and macOS instructions are left
in place; Windows uses Python equivalents under `tools/` and the wrappers under
`windows/`.

> **Read this first:** Windows is the **computer used to flash the controller**.
> The patch itself still exists to make **macOS and Apple TV** recognize the
> controller. It is **not** a Windows driver, and it does not promise better
> Windows behavior. The firmware uses the SN30 Pro+ compatibility profile
> internally, but the advertised Bluetooth name remains
> **8BitDo Ultimate 2C Wireless** on Windows and Apple TV. The controller's USB
> identity is unchanged.

> **Firmware flashing can brick a controller.** Power loss, a different hardware
> variant or a protocol difference can leave it unusable. The guarded tools,
> backups and LB+RB recovery mode reduce this risk; they do not eliminate it.
> Follow every check. There is deliberately no `--force` option.

## Supported hardware — check before doing anything

This workflow supports **only**:

- **8BitDo Ultimate 2C Wireless Controller** — the Windows/Android model.
- **Official firmware v1.09 only** (the tool reads and verifies the real
  firmware version, not the USB `bcdDevice` value).
- USB **data** cable, Windows 10 or 11 (64-bit).

It does **not** support:

- Ultimate 2C **Bluetooth** (Switch) model
- Ultimate 2 / Ultimate 2 Wireless
- A 2.4 GHz receiver/dongle
- Any other 8BitDo model or firmware version

If your controller is not exactly this model and firmware, **stop**.

Use Windows' built-in HID driver. **Do not install Zadig, libusb, or a custom
USB driver** for this project; the tools use the normal Windows HID stack, and a
replaced driver can hide the interfaces the tools need.

### At a glance

1. Install 64-bit Python 3.12 and allow `python` in PATH.
2. Extract the project and run `windows\setup.bat` once.
3. Download the official v1.09 DAT and generate the patched DAT.
4. In **normal USB mode**, confirm `2dc8:310a`, read firmware `1.09`, and save
   all four snapshots.
5. In **LB+RB BOOT mode**, confirm `2dc8:3208` and pass `--verify-reset`.
6. Still in BOOT mode, run `--flash` and let full verification finish.
7. Pair fresh on the Apple TV and test every input; Windows observation is
   optional.

---

## 1. Install Python 3.12 (64-bit)

1. Open <https://www.python.org/downloads/windows/>.
2. Download **Python 3.12.x — Windows installer (64-bit)**.
3. Run the installer and tick **“Add python.exe to PATH”** before clicking
   **Install Now**.
4. Open **Command Prompt** (press `Win`, type `cmd`, press Enter) and check:

   ```bat
   py -0p
   python --version
   python -c "import platform; print(platform.machine())"
   ```

   You need **64-bit x64 CPython 3.10–3.14**. The architecture line must say
   `AMD64`, and `3.12.x` is the most reliable for all optional packages.
   **Python 3.15, 32-bit Python, and ARM64 Python are not supported** because
   `hidapi` has no matching Windows wheel; they try to compile from source and
   ask for Microsoft Visual C++.

`windows\setup.bat` now searches for `py -3.12-64` first, validates the
architecture and version, and replaces an old incompatible `.venv` (renamed to
`.venv.old-<number>`) instead of reusing it.

If `python` opens the Microsoft Store instead, install python.org Python and
turn off **Settings → Apps → Advanced app settings → App execution aliases →
python.exe / python3.exe**, then reopen Command Prompt.

## 2. Get this project

**Option A — ZIP (easiest):**

1. On the GitHub page click **Code → Download ZIP**.
2. Right-click the ZIP → **Extract All…**.
3. Open the extracted folder. It must contain `README.md`, `tools`, and
   `windows`.

**Option B — Git:**

```bat
git clone https://github.com/vomba/8bitdo-ultimate-2c-apple.git
cd 8bitdo-ultimate-2c-apple
```

Open Command Prompt **inside the project folder**. Tip: click the File Explorer
address bar, type `cmd`, and press Enter. All commands below are run from this
folder; the `.bat` wrappers also change to it automatically.

> If you prefer **PowerShell**, local programs need a `.\` prefix:
> `.\windows\setup.bat`, `.\windows\read-firmware.bat`, and so on. For the
> optional environment variable use
> `$env:EIGHTBITDO_STOCK_DAT = "$PWD\work\original-v1.09-restore.dat"` instead
> of `set ...`. The rest of the commands are identical.

## 3. Run the one-time setup

```bat
windows\setup.bat
```

It creates a private `.venv` folder, installs the Windows HID library, tries to
install the optional joystick observer, and runs the offline test suite. No
controller is accessed.

Expected ending:

```text
Ran 44 tests in ...s

OK (skipped=6 or 7)
...
Setup complete. Offline tests passed.
```

Six of the skipped tests need the real stock DAT; they run automatically once
`EIGHTBITDO_STOCK_DAT` points at it (optional, see section 4). Windows also
skips one dangling-symlink fixture unless Developer Mode or admin rights allow
symlink creation. That skip is expected and does not affect the controller
tools. Everything else runs with no controller attached.

If the optional joystick observer could not be installed you will see a
warning. That only affects the optional observation step; reading, backup,
checking and flashing still work.

On Python 3.14 the setup uses `pygame-ce`, which is imported as `pygame` and has
a Windows wheel; older Pythons use upstream `pygame`. If the warning still
appears, install the observer manually:

```bat
.venv\Scripts\python.exe -m pip install --only-binary=:all: pygame-ce
```

You can also use `joy.cpl` instead (section 8).

If setup stops with `Python 3.10 or newer was not found`, fix section 1 and run
it again.

## 4. Download the exact official firmware and generate the patch

```bat
mkdir work
windows\fetch-firmware.bat work\original-v1.09-restore.dat
```

Expected:

```text
Downloaded exact pinned official v1.09 firmware over plain HTTP; SHA-256 verified.
SHA-256: 87349e603bb92d6ae9ff6defb6f32b10de2f2d3252fe4e442fa7993f982f2a5a
Created: work\original-v1.09-restore.dat
```

The vendor endpoint uses plain HTTP. The downloader accepts only **74,780
bytes** with that exact SHA-256 and refuses to overwrite an existing file. A
changed or unavailable endpoint is a failure; do not substitute another image.

Verify the file yourself if you wish:

```bat
certutil -hashfile work\original-v1.09-restore.dat SHA256
```

Now create the patched image:

```bat
windows\patch-firmware.bat work\original-v1.09-restore.dat work\patched-v1.09-BLE6002-r0001.dat
```

Expected patched SHA-256:

```text
e52216167e7f3f5e0a15d14b68b345b54a12a8b637b1052ddc1d595a0a57c88f
```

Only six bytes change: the two BLE PnP product-ID bytes and the four-byte
Telink CRC. This step does **not** touch the controller.

Optional: prove the whole toolchain against the real image by enabling the six
real-firmware tests. This still does not touch the controller:

```bat
set EIGHTBITDO_STOCK_DAT=%CD%\work\original-v1.09-restore.dat
windows\test.bat
```

Expected ending: `Ran 44 tests ... OK`. With Developer Mode disabled, the one
dangling-symlink fixture is expected to appear as `skipped` on Windows. Open a
new Command Prompt afterward (or run `set EIGHTBITDO_STOCK_DAT=`) to clear that
variable.

## 5. Update to official v1.09 — read this first

This project patches **only v1.09**. **As of 2025, v1.09 is the latest official
8BitDo firmware for the Ultimate 2C Wireless.** Controllers often ship with
older stock firmware, so update to v1.09 with Ultimate Software V2 before
making the section 6 backups. If `windows\read-firmware.bat` already reports
1.09, skip the vendor update and continue to section 6. A vendor update can
also overwrite the compatibility patch, so restore stock first if you update
after patching.

Use 8BitDo Ultimate Software V2:

```text
https://app.8bitdo.com/Ultimate-Software-V2/
```

Windows/macOS vendor procedure:

1. Install Ultimate Software V2; extract the ZIP first if needed.
2. Open the application with the controller unplugged.
3. Connect the controller by USB-C and turn it on. For the Ultimate 2C
   **Bluetooth** model, if it is not detected, turn it off, hold **L1 + R1**,
   and plug it in. That model is **not supported by this patch**.
4. Choose the firmware/update option, select the latest version, and click
   **Update**.
5. Keep the cable connected until the progress completes and the controller
   vibrates or confirms completion, then unplug it.

Afterward, run `windows\read-firmware.bat`. It must report **1.09**. If it does
not, do not use this repository's pinned `--flash`/`--restore` artifacts.

You can get the controller onto official v1.09 either with Ultimate Software V2
or with the pinned image downloaded by `windows\fetch-firmware.bat` in section
4. The patch itself always uses the pinned v1.09 DAT. If 8BitDo later releases
something newer than 1.09, this patch does not support it.

## 6. Read and preserve YOUR controller's stock state

1. Turn the controller fully off (hold **Home** for three seconds).
2. Connect it **directly** to the PC with a USB **data** cable. Do not hold any
   buttons for normal mode.
3. Close every controller/updater application: 8BitDo Ultimate Software (V1
   and V2), Steam, DS4Windows, JoyToKey, BetterJoy, vJoy, emulators, etc.
4. Remove any 2.4 GHz receiver/dongle and any other 8BitDo controller, then
   connect only this one controller. Prefer a rear motherboard USB port over a
   hub or front-panel extension.

Check what Windows sees:

```bat
windows\list-devices.bat
```

Expected normal-mode line includes:

```text
2dc8:310a ... usage_page=0xff7a usage=0x01
```

Then read the real firmware version:

```bat
windows\read-firmware.bat
```

Expected:

```text
Telink image header. Installed firmware version: 1.09 (raw 109).
```

> **Important:** USB device version `1.14` is not the firmware version. The
> reading above is the actual application version. If it is not **1.09**, stop
> and do not continue.

Save all four snapshots. Each command refuses to overwrite an existing file, so
use new filenames and check every result says `Complete`:

```bat
windows\read-firmware.bat --backup work\original-application-v1.09.bin
windows\read-firmware.bat --backup-boot work\original-boot-region.bin
windows\read-firmware.bat --backup-padding work\original-application-sector-tail.bin
windows\read-firmware.bat --backup-update work\original-update-metadata-and-staging.bin
```

Expected sizes:

| File | Bytes |
|---|---:|
| `original-application-v1.09.bin` | 74,752 |
| `original-boot-region.bin` | 24,576 |
| `original-application-sector-tail.bin` | 3,072 |
| `original-update-metadata-and-staging.bin` | 81,920 |

Keep these files and `original-v1.09-restore.dat` together in `work\`, and copy
them somewhere outside the PC. They are **your** controller's state; never use
another person's snapshots. These cover only the regions relevant to this
procedure, not the entire flash chip.

Now run the offline image check. It reads the files, not the controller, and it
requires all four snapshots beside the DAT (missing files are a hard failure):

```bat
windows\boot-firmware.bat --check-image work\patched-v1.09-BLE6002-r0001.dat
```

Expected ending:

```text
Verified known image, exact stock backup, pinned BOOT/tail and inactive update snapshot.
Image-only check completed; no hardware accessed.
```

If any hash, the stock application comparison, the bootloader/tail, or the
update metadata check fails, **stop**. Do not edit files to get past a check.

## 7. Validate recovery BEFORE flashing

This is the most important safety step.

1. Unplug USB and power the controller fully off (**hold Home** three seconds).
2. Hold **LB + RB** — the ordinary shoulder buttons, **not** LT/RT or L4/R4.
3. Reconnect the USB data cable while holding both buttons through enumeration.
4. Release them when Windows recognizes the device.

Check the recovery identity:

```bat
windows\list-devices.bat
```

Expected:

```text
2dc8:3208 ... usage_page=0x008c usage=0x01
```

It may appear as **8BitDo Boot** in Device Manager. Now run the non-flashing
recovery/reset check:

```bat
windows\boot-firmware.bat --verify-reset work\original-v1.09-restore.dat
```

Expected ending:

```text
Reset acknowledged. Normal USB/Bluetooth behavior and BOOT reentry must be observed separately.
```

If instead it prints `Rejected/timed-out command 8 at 0x0`, do not flash. Confirm
the recovery identity with `windows\list-devices.bat`, power-cycle, re-enter
LB+RB BOOT mode, and retry once. If it repeats, run the read-only diagnostic:

```bat
windows\boot-probe.bat
```

It sends only the identity command and prints the raw Windows reports for both
documented report framings. Do not continue to flashing if the probe cannot get
an identity response.

Then unplug/reconnect in **normal** mode and run `windows\list-devices.bat`
again. Confirm it returns to `2dc8:310a`. An acknowledgement alone is not proof
of normal startup; the controller must actually come back.

If recovery entry, reading, reset or normal startup fails, **stop without
flashing**. Do not try alternate boot packets.

## 8. Flash the patch (only after section 7 passed)

1. Power off completely.
2. Hold **LB + RB** and reconnect USB.
3. Confirm `2dc8:3208` with `windows\list-devices.bat`.
4. Keep the Windows PC on AC power. Do not sleep, close the lid, unplug, or
   start other controller software.

> **Do not disconnect USB or let the Windows PC sleep.** The writer checks the
> live stock baseline and preserved regions before erasing. It replaces only the
> two differing 4-KiB sectors, verifies erased bytes, respects 256-byte
> programming-page boundaries, and reads back the complete application, sector
> tail, bootloader and saved update regions before resetting.

```bat
windows\boot-firmware.bat --flash work\patched-v1.09-BLE6002-r0001.dat
```

The tool:

- opens the BOOT interface **exclusively**,
- verifies the BOOT identity and saved BOOT/update regions,
- verifies your current application matches your stock backup,
- erases only the two differing 4-KiB sectors,
- verifies every erased byte is blank,
- programs within 46-byte and 256-byte page limits,
- reads back the **complete** application/tail, BOOT and update regions,
- sends reset only after that succeeds.

Expected highlights:

```text
Verified known image, exact stock backup, pinned BOOT/tail and inactive update snapshot.
BOOT and inactive update storage verified. Beginning application-only sector replacement.
Programmed application sector 0x17000; full verification follows.
Programmed application sector 0x18000; full verification follows.
Complete app/tail, BOOT and update storage match; sending explicit reset.
Reset acknowledged. ...
```

If anything fails, the tool prints `STOPPED` and does **not** reset or retry.
Keep the controller in BOOT reach, preserve all snapshots, and read the reported
failure before doing anything. Do not blindly re-flash.

## 9. Fresh pairing and acceptance checks

### Apple TV (the actual target)

1. Forget the old controller pairing on the Apple TV:
   **Settings → Remotes and Devices → Bluetooth**.
2. On the controller, turn it on in **BT** mode and hold **Pair** for three
   seconds.
3. Pair it afresh. The advertised name remains
   **8BitDo Ultimate 2C Wireless**.
4. Test D-pad/left-stick menu navigation and a supported game: movement,
   right-stick camera, face buttons, shoulders and triggers.

### Optional Windows check

This only proves the controller still reports input to Windows; it does not
prove Apple behavior.

1. **Settings → Bluetooth & devices → Add device → Bluetooth**, hold **Pair**
   for three seconds, and select the controller.
2. Run:

   ```bat
   windows\observe-controller.bat 60
   ```

3. While it runs, press each D-pad direction and diagonal, sweep both sticks
   fully and release, press A/B/X/Y, and squeeze both triggers.
4. Look for near `-1.0000` / `+1.0000` axis travel, centered release, and
   `pressed-seen=1` / `released-seen=1` for each button. Raw HID changes are
   printed for the patched `2dc8:6002` device.

If the observer package was not installed, use the built-in tester instead: press `Win+R`,
type `joy.cpl`, press Enter, select the controller, and open **Properties**.

The firmware selects the **SN30 Pro+ compatibility profile internally**, but
the advertised Bluetooth name remains **8BitDo Ultimate 2C Wireless** on
Windows and Apple TV. The name is not changed to SN30 Pro+.

## Restore the original stock firmware

You need the original DAT and all four snapshots from section 6.

1. Power off, hold **LB + RB**, reconnect USB, confirm `2dc8:3208`.
2. Run:

   ```bat
   windows\boot-firmware.bat --restore work\original-v1.09-restore.dat
   ```

`--restore` deliberately rewrites all 19 application/tail sectors so a damaged
application can be repaired. It never writes the bootloader or update storage,
and it still refuses a mismatched bootloader or a changed saved update region.
It verifies before reset. Do not unplug during the restore.

Pair again from scratch after restoring. This is a recovery capability, not a
guarantee against every possible failure.

## Troubleshooting

| Symptom | What to do |
|---|---|
| `python` opens Microsoft Store | Install python.org Python 3.12 and disable the `python.exe` app execution alias. |
| `No module named hid` | Run `windows\setup.bat` again, or `.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-windows.txt`. |
| pip: `Microsoft Visual C++ 14.0 or greater is required` | No prebuilt `hidapi` wheel matched the interpreter. Run `py -0p`; install 64-bit Python 3.12 x64, rename/delete `.venv`, and rerun `windows\setup.bat`. Python 3.15, 32-bit, and ARM64 are unsupported. |
| `No normal-mode vendor HID interface found` | Use a USB **data** cable, power the controller off/on, close 8BitDo/Steam/DS4Windows, run `windows\list-devices.bat`. |
| `expected exactly one ... found 2` | More than one matching interface is present. Disconnect other controllers/updaters; reconnect one controller; inspect the printed table. |
| `already open by another application` | Close every updater/controller tool, unplug, re-enter BOOT mode, retry. If it persists, reboot and connect the controller only after Windows finishes starting. |
| `Refusing: ... output report length ...` | Windows exposed a different interface/shape. Stop; this is not the reviewed model/protocol. |
| `Refusing: these flash bounds ... v1.09` | Firmware is not v1.09. Stop; do not force or downgrade blindly. |
| `Artifact read/SHA-256 mismatch` | Wrong/corrupted DAT or snapshot. Re-download the exact firmware, redo backups; never edit or substitute files. |
| `Update metadata corrupt or pending installation present` | The controller has a staged/pending vendor update. Stop; do not flash. Resolve it with the vendor updater first. |
| `Rejected/timed-out command 8 at 0x0` | Identity did not answer. Confirm `windows\list-devices.bat` still shows `2dc8:3208 usage_page=0x008c usage=1`, power-cycle, re-enter LB+RB BOOT, and retry. If it repeats, run `windows\boot-probe.bat` and send its raw output. **Do not flash.** |
| `--verify-reset` fails | Do not flash. Keep LB+RB recovery reachable and re-check backups/recovery. |
| Flash/verification fails | Do not unplug/retry blindly. Keep BOOT reachable, read the exact error, then use guarded `--restore` only after understanding it. |
| Controller no longer enumerates | Re-enter LB+RB BOOT mode and restore stock; if BOOT is unavailable, use 8BitDo's official recovery process. |
| Antivirus blocks a `.bat` | Allow the project folder, or run the Python commands directly with `.venv\Scripts\python.exe`. Batch files do not need PowerShell execution-policy changes. |

## What changed in the Windows port (and what did not)

| macOS original | Windows equivalent |
|---|---|
| `native/read_firmware.m` | `tools/read_firmware.py` + `tools/windows_hid.py` |
| `native/boot_firmware.m` | `tools/boot_firmware.py` + `tools/boot_protocol.py` |
| `native/observe_controller.m` | `tools/observe_controller.py` (SDL + raw HID) |
| `Makefile` / Xcode CLT | `windows\setup.bat` / Python virtual environment |
| `ioreg` identity check | `windows\list-devices.bat` |
| GameController measurement | `observe-controller.bat` or `joy.cpl` |

Unchanged: controller model/firmware scope, DAT hashes, six-byte patch,
GATT/PnP offsets, Telink CRC, flash map, BOOT commands, 46-byte/page limits,
erase verification, full readback, snapshots and no-force policy. The macOS
source and documentation remain valid for macOS.

## Verification status

Checked in this port (offline, no controller required):

- Official v1.09 firmware downloads at 74,780 bytes with the pinned SHA-256.
- Patcher produces the pinned patched SHA-256 and exactly the six documented
  byte changes.
- 44 offline tests are defined. Six real-firmware checks run when
  `EIGHTBITDO_STOCK_DAT` is set; on Windows without symlink privilege one
  additional dangling-symlink fixture is skipped. The suite covers every
  original BOOT acknowledgement/range/image/metadata guard, documented CLI
  parsing, Windows report-ID framing, a full simulated `--flash` run that writes
  only the two changed sectors, preserves the tail/BOOT/update regions, and
  resets once, plus a simulated `--restore` that repairs a damaged application
  without touching BOOT/update storage.

### Capture Windows evidence

After running `windows\setup.bat`, collect the actual Windows results with:

```bat
windows\collect-evidence.bat
```

It is **read-only**: it runs the offline tests, lists HID interfaces, and reads
the firmware version without erasing, programming or resetting anything. It
writes `work\windows-evidence\environment.txt`, `tests.txt`, `devices.txt` and
`read-firmware.txt`. Keep those four small text logs together when reporting a
Windows problem; do not add firmware images, full dumps or Bluetooth addresses.

Hardware flashing itself still has to be performed manually by following
sections 6 and 7. The collector never writes to the controller.

The Windows HID I/O layer mirrors the original packet layout and the documented
Windows HID report-ID rules, but this repository's author has not flashed a
controller from a Windows PC. The original firmware work was measured on one
Mac. **Treat the first Windows hardware run as independent validation**, keep
all backups, and stop on any failed check.
