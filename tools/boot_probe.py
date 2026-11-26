#!/usr/bin/env python3
"""Read-only BOOT identity diagnostic for the 8BitDo Ultimate 2C.

This sends only command 8 (identity), never erase/program/reset. It is meant for
the case where ``boot_firmware.py --verify-reset`` opens the BOOT interface but
times out on the identity response. Two documented Windows report framings are
tried and every raw input report is printed so the correct shape can be seen.
"""

from __future__ import annotations

import sys
import time

from boot_firmware import (
    BOOT_PRODUCT_ID,
    BOOT_USAGE,
    BOOT_USAGE_PAGE,
    BOOT_VENDOR_ID,
)
from boot_protocol import CMD_IDENTITY, build_request, normalize_boot_report, u16, u32
from windows_hid import HidError, open_exclusive_hid, select_device


def main():
    try:
        info = select_device(
            BOOT_VENDOR_ID, BOOT_PRODUCT_ID, BOOT_USAGE_PAGE, BOOT_USAGE, "BOOT"
        )
    except HidError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        device = open_exclusive_hid(info)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        try:
            caps = device.get_caps()
        except Exception as exc:
            print(f"Could not read HID capabilities: {exc}", file=sys.stderr)
            return 1

        print("BOOT identity probe (command 8 only; no flash commands).")
        print(
            "Caps: usage_page=0x{:04x} usage=0x{:02x} "
            "input={} output={} feature={}".format(
                caps.UsagePage,
                caps.Usage,
                caps.InputReportByteLength,
                caps.OutputReportByteLength,
                caps.FeatureReportByteLength,
            )
        )
        packet = build_request(CMD_IDENTITY, 0, 4, 4)
        print(f"Protocol packet ({len(packet)} bytes): {packet[:32].hex()} ...")
        read_length = max(64, caps.InputReportByteLength)
        variants = [
            ("0x00 report ID + 64-byte packet", b"\x00" + packet),
            ("64-byte raw packet", packet),
        ]

        for label, outgoing in variants:
            print(f"\nSending {label} ({len(outgoing)} bytes) ...")
            try:
                written = device.write(outgoing, timeout_ms=3000)
                print(f"  write returned {written} bytes")
            except Exception as exc:
                print(f"  write failed: {exc}")
                continue

            deadline = time.monotonic() + 3.0
            reports = 0
            while time.monotonic() < deadline:
                remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
                try:
                    raw = device.read(read_length, remaining_ms)
                except Exception as exc:
                    print(f"  read failed: {exc}")
                    break
                if not raw:
                    continue
                reports += 1
                print(f"  report {reports}: {len(raw)} bytes: {raw.hex()}")

                normalized = normalize_boot_report(raw)
                if not normalized:
                    print("    not a recognized BOOT report shape")
                    continue
                print(
                    "    parsed: status={} command={} count={} total={} address=0x{:x}".format(
                        u16(normalized, 2),
                        u16(normalized, 4),
                        u16(normalized, 6),
                        u32(normalized, 10),
                        u32(normalized, 14),
                    )
                )
                if u16(normalized, 2) == 0 and u16(normalized, 4) == CMD_IDENTITY:
                    identity = u16(normalized, 18)
                    print(
                        f"    identity OK: application family 0x{identity:04x} "
                        f"(expected 0x301b)"
                    )
                    return 0

            print("  no matching identity report in 3 seconds")

        print(
            "\nNo identity response. Confirm the controller is in BOOT mode: "
            "USB 2dc8:3208, usage page 0x008c, usage 1."
        )
        return 1
    finally:
        device.close()


if __name__ == "__main__":
    sys.exit(main())
