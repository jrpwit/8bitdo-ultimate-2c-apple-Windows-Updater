# 8BitDo Ultimate 2C Wireless — Windows updater for Apple Compatibility

An experimental, identity-only firmware patch for the **8BitDo Ultimate 2C Wireless Controller** (the Windows/Android model).

You run this installer from a **Windows PC**. After patching, the controller presents the Bluetooth identity of an **SN30 Pro+**, so **macOS and Apple TV** recognize its existing input reports. No Mac is required to install or flash the controller.

> **Windows is only the flashing host.** This patch does **not** install a Windows driver and does not promise better Windows behavior. It does **not** install SN30 Pro+ firmware, add rumble, or add motion support. After patching, Windows may label the Bluetooth controller as an SN30 Pro+; that is expected.

> **Firmware flashing can brick a controller.** Power loss, a different hardware variant, or a protocol difference can leave it unusable. The guarded tools, backups, and LB+RB recovery mode reduce the risk; they do not eliminate it. There is deliberately no `--force` option.

## What this patch changes

## About

This repository is a **Windows-native updater and guarded toolchain** for the 8BitDo Ultimate 2C Wireless Controller. It reads and patches the exact official firmware v1.09 so **macOS and Apple TV** recognize the controller's Bluetooth input reports.

Windows is used only as the computer that performs the backup and flash. The firmware target is Apple compatibility, not a Windows driver. The same workflow also supports restoring the original stock firmware from your own backups.

The original macOS tools remain in `native/`; this project adds the Windows HID backend, Python tools, batch wrappers, safety checks, tests, and step-by-step Windows guide.

Only **six bytes** of the exact official firmware v1.09:

- two bytes: Bluetooth PnP product ID `2dc8:301b` → `2dc8:6002` (SN30 Pro+ compatibility identity);
- four bytes: the firmware's internal Telink CRC.

Everything else stays unchanged: executable code, the 116-byte Bluetooth report descriptor, report layout, radio stack, button scanning, and the USB identity.

The patch was selected because the SN30 Pro+ profile understands this controller's report ranges. Apple TV operation was confirmed by the original tester after fresh pairing. This is not an official 8BitDo update, not Apple certification, and not a universal compatibility guarantee.

## What the Windows port adds

This repository now contains a Windows-native implementation of the original macOS tools:

| macOS original | Windows equivalent |
|---|---|
| `native/read_firmware.m` | `tools/read_firmware.py` + `tools/windows_hid.py` |
| `native/boot_firmware.m` | `tools/boot_firmware.py` + `tools/boot_protocol.py` |
| `native/observe_controller.m` | `tools/observe_controller.py` |
| `make` + Xcode tools | `windows\setup.bat` + a private `.venv` |
| `ioreg` check | `windows\list-devices.bat` |

Additional Windows-specific work includes:

- native Win32 exclusive HID access for BOOT writes;
- handling of Windows' 65-byte BOOT reports, including the real `00 00 05 ...` reply shape;
- a read-only identity diagnostic: `windows\boot-probe.bat`;
- `windows\collect-evidence.bat` for safe Windows logs;
- a setup script that selects a supported 64-bit Python and replaces an incompatible `.venv`;
- regression tests for the Windows report-ID framing.

## Supported hardware — check before doing anything

This workflow supports **only**:

- **8BitDo Ultimate 2C Wireless Controller** — the Windows/Android model;
- **official firmware v1.09 only** (the tool reads the real firmware version, not the USB `bcdDevice` value);
- USB **data** cable, Windows 10 or 11 (64-bit).

It does **not** support:

- Ultimate 2C **Bluetooth** (Switch) model;
- Ultimate 2 / Ultimate 2 Wireless;
- a 2.4 GHz receiver/dongle;
- another 8BitDo model or firmware version.

If your controller is not exactly this model and firmware, **stop**.

## What you need

- Windows 10/11 64-bit.
- **64-bit x64 CPython 3.10–3.14.** Python **3.12** is recommended.
  Python 3.15, 32-bit Python, and ARM64 Python are not supported because
  `hidapi` has no matching Windows wheel and will try to compile from source.
- USB **data** cable.
- The controller, powered off and ready.
- AC power for the Windows PC during flashing.
- No Mac required.

Before starting:

- close 8BitDo Ultimate Software, Steam, DS4Windows, JoyToKey, BetterJoy, vJoy, emulators, etc.;
- remove any 2.4 GHz receiver/dongle and other controllers;
- connect only this one controller;
- use a rear motherboard USB port rather than a hub;
- do **not** install Zadig, libusb, or a custom USB driver.

## Quick start checklist

1. Install 64-bit Python 3.12 (or use an existing supported 3.10–3.14 x64).
2. Extract the project; open Command Prompt in the project folder.
3. Run `windows\setup.bat`.
4. Download the official v1.09 DAT and generate the patched DAT.
5. In normal USB mode: confirm `2dc8:310a`, read firmware `1.09`, save four snapshots, run `--check-image`.
6. In LB+RB BOOT mode: confirm `2dc8:3208`, run `--verify-reset`, then confirm normal mode returns.
7. In BOOT mode again: run `--flash`.
8. Pair fresh on Apple TV and test every input.

---

## 1. Install Python

Download **Python 3.12.x — Windows installer (64-bit)** from:

```text
https://www.python.org/downloads/windows/
```

Tick **Add python.exe to PATH** before clicking **Install Now**.

Open Command Prompt and check:

```bat
py -0p
python --version
python -c "import platform; print(platform.machine())"
```

You want:

- version **3.10–3.14**;
- architecture **AMD64**;
- Python 3.12 is the safest for all optional packages.

If `python` opens the Microsoft Store, install python.org Python and turn off **Settings → Apps → Advanced app settings → App execution aliases → python.exe / python3.exe**, then reopen Command Prompt.

`windows\setup.bat` now searches for `py -3.12-64`, then 3.13, 3.14, 3.11, and 3.10. It validates the architecture and replaces an old incompatible `.venv` (renamed to `.venv.old-<number>`) instead of reusing it.

## 2. Get the project and open the right folder

**Option A — ZIP:**

1. On GitHub click **Code → Download ZIP**.
2. Extract it.
3. Open the extracted folder; it must contain `README.md`, `tools`, and `windows`.

**Option B — Git:**

```bat
git clone https://github.com/jrpwit/8bitdo-ultimate-2c-apple-Windows-installer.git
cd 8bitdo-ultimate-2c-apple-Windows-installer
```

Open **Command Prompt inside the project folder**. Tip: click the File Explorer address bar, type `cmd`, and press Enter.

> **Path rule:** every `.bat` wrapper changes to the project root before running Python. Even if your prompt is inside `windows\`, paths are interpreted from the project root. Use `work\...`, not `windows\work\...`.
>
> In PowerShell, local programs need `.\`: `.\windows\setup.bat`, `.\windows\read-firmware.bat`, etc.

## 3. Run setup once

```bat
windows\setup.bat
```

Expected:

```text
Locating a supported 64-bit Python (3.12 recommended) ...
[1/4] Using existing .venv ...
      Interpreter: 3.14.x AMD64
[2/4] Installing the Windows HID backend ...
[3/4] Installing optional joystick observation support ...
[4/4] Running offline safety tests ...

Ran 44 tests in ...s
OK (skipped=6 or 7)
...
Setup complete. Offline tests passed.
```

The six real-firmware tests are skipped until `EIGHTBITDO_STOCK_DAT` is set. On Windows without Developer Mode, one dangling-symlink fixture is also skipped; that is harmless.

If setup says `No supported 64-bit CPython 3.10-3.14 was found`, install Python 3.12 x64 and rerun. If pip says `Microsoft Visual C++ 14.0 or greater is required`, the `.venv` is using an unsupported Python build; rerun the current setup or remove `.venv` and run it again.

The `pygame` warning is optional only. On Python 3.14, setup uses `pygame-ce` (imported as `pygame`). If it still cannot install, install it manually:

```bat
.venv\Scripts\python.exe -m pip install --only-binary=:all: pygame-ce
```

Setup does **not** access or flash the controller.

## 4. Download the exact firmware and generate the patch

```bat
mkdir work
windows\fetch-firmware.bat work\original-v1.09-restore.dat
```

Expected size and hash:

```text
74,780 bytes
87349e603bb92d6ae9ff6defb6f32b10de2f2d3252fe4e442fa7993f982f2a5a
```

Verify it yourself:

```bat
certutil -hashfile work\original-v1.09-restore.dat SHA256
dir work\original-v1.09-restore.dat
```

The downloader accepts only the exact pinned bytes and refuses to overwrite an existing file. The vendor endpoint uses plain HTTP; the SHA-256 authenticates the expected firmware, not the server.

Create the patched image:

```bat
windows\patch-firmware.bat work\original-v1.09-restore.dat work\patched-v1.09-BLE6002-r0001.dat
```

Expected patched size and hash:

```text
74,780 bytes
e52216167e7f3f5e0a15d14b68b345b54a12a8b637b1052ddc1d595a0a57c88f
```

Only six bytes change. This step does **not** touch the controller.

> **Path rule:** both DAT files belong in `work\`. The 28-byte DAT wrapper explains why the DAT is 74,780 bytes while the raw application backup is 74,752 bytes. That size difference is normal.

Optional: run the patcher against the real image to prove the whole toolchain:

```bat
set EIGHTBITDO_STOCK_DAT=%CD%\work\original-v1.09-restore.dat
windows\test.bat
```

Expected: `Ran 44 tests ... OK`. Open a new Command Prompt afterward, or run `set EIGHTBITDO_STOCK_DAT=`, to clear the variable.

## 5. Read and preserve YOUR controller's stock state

1. Turn the controller fully off: hold **Home** for three seconds.
2. Connect it **directly** to the Windows PC with a USB **data** cable. Do not hold any other buttons for normal mode.
3. Close every controller/updater application.
4. Remove any 2.4 GHz receiver/dongle and other controllers. Connect only this controller. Use a rear motherboard USB port.

Check what Windows sees:

```bat
windows\list-devices.bat
```

Expected normal-mode line:

```text
2dc8:310a ... usage_page=0xff7a usage=0x01
```

Read the real firmware version:

```bat
windows\read-firmware.bat
```

Expected:

```text
Telink image header. Installed firmware version: 1.09 (raw 109).
```

> USB device version `1.14` is **not** the firmware version. The line above is the actual application version. If it is not **1.09**, stop.

Save all four snapshots. Each command refuses to overwrite an existing file, so use new filenames and check every result says `Complete`:

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

Keep these files and `original-v1.09-restore.dat` together in `work\`, and copy them somewhere outside the Windows PC as well. They are **your** controller's state; never use another person's snapshots. These cover only the regions relevant to this procedure, not the entire flash chip.

Now run the offline image check. It reads the files, not the controller, and it requires all four snapshots beside the DAT:

```bat
windows\boot-firmware.bat --check-image work\patched-v1.09-BLE6002-r0001.dat
```

Expected ending:

```text
Verified known image, exact stock backup, pinned BOOT/tail and inactive update snapshot.
Image-only check completed; no hardware accessed.
```

If any hash, stock application comparison, bootloader/tail, or update metadata check fails, **stop**. Do not edit files to get past a check.

## 6. Validate recovery BEFORE flashing

This is the most important safety step.

1. Unplug USB and power the controller fully off: hold **Home** three seconds.
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

It may appear as **8BitDo Boot** in Device Manager. Run the non-flashing recovery/reset check:

```bat
windows\boot-firmware.bat --verify-reset work\original-v1.09-restore.dat
```

Expected ending:

```text
Reset acknowledged. Normal USB/Bluetooth behavior and BOOT reentry must be observed separately.
```

If it prints `Rejected/timed-out command 8 at 0x0`, do not flash. Confirm `windows\list-devices.bat` still shows `2dc8:3208 usage_page=0x008c usage=0x01`, power-cycle, re-enter LB+RB BOOT mode, and retry once. If it repeats, run the read-only diagnostic:

```bat
windows\boot-probe.bat
```

It sends only the identity command and prints the raw Windows reports. Do not continue to flashing without an identity response.

Then unplug/reconnect in **normal** mode and run `windows\list-devices.bat` again. Confirm it returns to `2dc8:310a`. An acknowledgement alone is not proof of normal startup; the controller must actually come back.

If recovery entry, reading, reset, or normal startup fails, **stop without flashing**.

## 7. Flash the patch

Only after section 6 passed:

1. Power off completely.
2. Hold **LB + RB** and reconnect USB.
3. Confirm `2dc8:3208` again:

```bat
windows\list-devices.bat
```

4. Keep the Windows PC on AC power. Do not sleep, close the lid, unplug, or start other controller software.

> **Do not disconnect USB or let the Windows PC sleep.** The writer checks the live stock baseline and preserved regions before erasing. It replaces only the two differing 4-KiB sectors, verifies erased bytes, respects 256-byte programming-page boundaries, and reads back the complete application, sector tail, bootloader and saved update regions before resetting.

```bat
windows\boot-firmware.bat --flash work\patched-v1.09-BLE6002-r0001.dat
```

The tool:

- opens the BOOT interface **exclusively**;
- verifies the BOOT identity and saved BOOT/update regions;
- verifies your current application matches your stock backup;
- erases only the two differing 4-KiB sectors;
- verifies every erased byte is blank;
- programs within 46-byte and 256-byte page limits;
- reads back the **complete** application/tail, BOOT and update regions;
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

If anything fails, the tool prints `STOPPED` and does **not** reset or retry. Keep the controller in BOOT reach, preserve all snapshots, and read the reported failure before doing anything. Do not blindly re-flash.

## 8. Pair fresh and test

### Apple TV — the actual target

1. Forget the old controller pairing on the Apple TV:
   **Settings → Remotes and Devices → Bluetooth**.
2. Put the controller in **BT** mode and hold **Pair** for three seconds.
3. Pair it afresh. The advertised name can still be
   **8BitDo Ultimate 2C Wireless**.
4. Test D-pad/left-stick menu navigation and a supported game: movement,
   right-stick camera, face buttons, shoulders, and triggers.

### Optional Windows check

This only proves the controller still reports input to Windows; it does not prove Apple behavior.

1. Open **Settings → Bluetooth & devices → Add device → Bluetooth**, hold **Pair** for three seconds, and select the controller.
2. Run:

```bat
windows\observe-controller.bat 60
```

3. While it runs, press each D-pad direction and diagonal, sweep both sticks fully and release, press A/B/X/Y, and squeeze both triggers.
4. Look for near `-1.0000` / `+1.0000` axis travel, centered release, and `pressed-seen=1` / `released-seen=1` for each button.

If the observer package was not installed, use `joy.cpl` instead: press `Win+R`, type `joy.cpl`, press Enter, select the controller, and open **Properties**.

The patched Bluetooth identity is the SN30 Pro+ profile. Windows may label or map it differently from the stock controller. That is expected; the Apple target is what matters.

## Restore the original stock firmware

You need the original DAT and all four snapshots from section 5.

1. Power off, hold **LB + RB**, reconnect USB, and confirm `2dc8:3208`.
2. Run:

```bat
windows\boot-firmware.bat --restore work\original-v1.09-restore.dat
```

`--restore` deliberately rewrites all 19 application/tail sectors so a damaged application can be repaired. It never writes the bootloader or update storage, and it still refuses a mismatched bootloader or changed saved update region. It verifies before reset. Do not unplug during the restore.

Pair again from scratch after restoring. This is a recovery capability, not a guarantee against every possible failure.

Official updates can overwrite the compatibility patch. Do not patch a new firmware version with these offsets. Restore stock before using normal vendor updates.

## Troubleshooting

| Symptom | What to do |
|---|---|
| `python` opens Microsoft Store | Install python.org Python 3.12 and disable the `python.exe` app execution alias. |
| `No module named hid` | Run `windows\setup.bat` again, or `.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-windows.txt`. |
| pip: `Microsoft Visual C++ 14.0 or greater is required` | No prebuilt `hidapi` wheel matched the interpreter. Run `py -0p`; install 64-bit Python 3.12 x64, rename/delete `.venv`, and rerun `windows\setup.bat`. Python 3.15, 32-bit, and ARM64 are unsupported. |
| `No matching distribution found for pygame` | Optional observer only. The setup uses `pygame-ce` on Python 3.14; use `joy.cpl` or install `.venv\Scripts\python.exe -m pip install --only-binary=:all: pygame-ce`. |
| `Missing/wrong-size artifact` | Check the path and filename. All DAT/snapshot files must be in the same folder, normally `work\`. The DAT must be 74,780 bytes; the application backup 74,752 bytes. |
| `No normal-mode vendor HID interface found` | Use a USB **data** cable, power-cycle, close 8BitDo/Steam/DS4Windows, and run `windows\list-devices.bat`. |
| `expected exactly one ... found 2` | More than one matching interface is present. Disconnect other controllers/updaters and reconnect one controller. |
| `already open by another application` | Close every updater/controller tool, unplug, re-enter BOOT mode, retry. If it persists, reboot and connect the controller only after Windows starts. |
| `Rejected/timed-out command 8 at 0x0` | Confirm `2dc8:3208 usage_page=0x008c usage=1`, power-cycle, re-enter LB+RB BOOT, and retry. If it repeats, run `windows\boot-probe.bat` and send its raw output. **Do not flash.** |
| `HID write failed ... error 87` | The wrong report framing was used. This port handles the observed 65-byte `00 00 05 ...` reply; run `windows\boot-probe.bat` and do not flash until identity succeeds. |
| `Refusing: ... output report length ...` | Windows exposed a different interface shape. Stop; this is not the reviewed model/protocol. |
| `Refusing: these flash bounds ... v1.09` | Firmware is not v1.09. Stop; do not force or downgrade blindly. |
| `Artifact read/SHA-256 mismatch` | Wrong/corrupted DAT or snapshot. Re-download the exact firmware and redo backups; never edit or substitute files. |
| `Update metadata corrupt or pending installation present` | The controller has a staged/pending vendor update. Stop; do not flash. Resolve it with the vendor updater first. |
| `--verify-reset` fails | Do not flash. Keep LB+RB recovery reachable and re-check backups/recovery. |
| Flash/verification fails | Do not unplug/retry blindly. Keep BOOT reachable, read the exact error, then use guarded `--restore` only after understanding it. |
| Controller no longer enumerates | Re-enter LB+RB BOOT mode and restore stock; if BOOT is unavailable, use 8BitDo's official recovery process. |
| Antivirus blocks a `.bat` | Allow the project folder, or run the Python commands directly with `.venv\Scripts\python.exe`. |

### Capture Windows evidence

If you need help, run:

```bat
windows\collect-evidence.bat
```

This is read-only. It runs the offline tests, lists HID interfaces, and reads the firmware version without erasing, programming, or resetting. It writes:

```text
work\windows-evidence\environment.txt
work\windows-evidence\tests.txt
work\windows-evidence\devices.txt
work\windows-evidence\read-firmware.txt
```

Send those four small text logs and the exact failing command output. Do not upload firmware images, full flash dumps, or Bluetooth addresses.

## Verification status and limits

Checked for this Windows port:

- official v1.09 firmware downloads at 74,780 bytes with the pinned SHA-256;
- patcher produces the pinned patched SHA-256 and exactly six documented changes;
- 44 offline tests, including BOOT acknowledgement/range/image/metadata guards, Windows report-ID framing, a simulated full `--flash`, and a simulated `--restore`;
- the guarded Windows workflow was exercised on a real Windows PC through setup, normal-mode reads and backups, BOOT identity, `--verify-reset`, and flashing.

The underlying firmware patch was measured on one unit; Apple TV operation was user-confirmed after fresh pairing. This is not a universal compatibility guarantee.

## Files, credits, and legal boundary

- [Windows technical notes and diagnostics](WINDOWS.md)
- [Protocol and patch rationale](docs/PROTOCOL.md)
- [Validation evidence and unverified boundaries](docs/VALIDATION.md)
- [Third-party credits and licenses](THIRD_PARTY.md)
- [Original macOS sources](native/)
- [8BitDo Ultimate 2C Wireless product page](https://www.8bitdo.com/ultimate-2c-wireless-controller/)
- [8BitDo official Apple compatibility list](https://www.8bitdo.com/apple/)

The original macOS tools remain in `native/`. Vendor firmware and Apple software remain their owners' property. This repository does not redistribute firmware images or device backups.

This is an experimental community project, not an official 8BitDo or Apple product. Not affiliated with or endorsed by 8BitDo or Apple.


