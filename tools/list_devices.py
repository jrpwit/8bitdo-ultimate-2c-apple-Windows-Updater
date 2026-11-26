#!/usr/bin/env python3
"""List Windows HID interfaces exposed by 8BitDo hardware.

Useful before and after entering LB+RB recovery mode:

    windows\\list-devices.bat

Expected normal mode: 2dc8:310a, usage_page 0xff7a, usage 1.
Expected BOOT mode:   2dc8:3208, usage_page 0x008c, usage 1.
Expected patched BLE: 2dc8:6002 (after fresh pairing).

Only enumeration is performed; no report is sent.
"""

from __future__ import annotations

import argparse
import sys

from windows_hid import describe_device, enumerate_devices


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="list every HID device, not only 8BitDo")
    args = parser.parse_args(argv)
    try:
        devices = enumerate_devices()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    selected = [
        info for info in devices
        if args.all or (info.get("vendor_id") or 0) == 0x2DC8
    ]
    if not selected:
        print("No 8BitDo HID interfaces found. Connect the controller directly by a USB "
              "data cable, then retry.")
        print("Use --all to list every HID device Windows exposes.")
        return 1
    print(f"{len(selected)} matching HID interface(s):")
    for info in selected:
        print(f"  - {describe_device(info)}")
        path = info.get("path")
        if path:
            print(f"    path={path!r}")
    print("\nExpected identities:")
    print("  normal USB mode : 2dc8:310a  usage_page=0xff7a usage=1")
    print("  BOOT/recovery   : 2dc8:3208  usage_page=0x008c usage=1  (hold LB+RB while plugging in)")
    print("  patched BLE     : 2dc8:6002  (after fresh Bluetooth pairing)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
