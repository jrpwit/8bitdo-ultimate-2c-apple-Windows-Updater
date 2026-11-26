#!/usr/bin/env python3
"""Windows port of the read-only 8BitDo Ultimate 2C USB snapshot tool.

Matches the original macOS tool's identity, bounds and behavior:

* USB ``2dc8:310a``, usage page ``0xff7a`` / usage ``1``, output report ID
  ``0x81``. Only the read command (5) is ever issued.
* Reads are bounded to the reviewed BOOT/application/update regions.
* A backup command refuses to overwrite an existing file and leaves an
  explicitly reported incomplete file if a read fails.

This tool never erases, programs or resets the controller.
"""

from __future__ import annotations

import argparse
import sys
import time

from boot_protocol import MAX_CHUNK, p16, p32, u16, u32

VENDOR_ID = 0x2DC8
PRODUCT_ID = 0x310A
USAGE_PAGE = 0xFF7A
USAGE = 1
OUTPUT_REPORT_ID = 0x81
READ_COMMAND = 5
READ_TIMEOUT_SECONDS = 3.0

# name: (flash base, length)
REGIONS = {
    "--backup": (0x6000, 0x12400, "application"),
    "--backup-boot": (0x0000, 0x6000, "boot"),
    "--backup-padding": (0x18400, 0x0C00, "application-sector-tail"),
    "--backup-update": (0x3F000, 0x14000, "update-metadata-and-staging"),
}


def normalize_read_report(report):
    """Return a 64-byte normal-mode report with report ID 0x02 first.

    Windows HIDAPI normally returns numbered reports with the report ID byte,
    exactly like IOKit. A 63-byte payload without the ID is accepted defensively.
    """
    if report is None:
        return None
    data = bytes(report)
    if len(data) == 65 and data[0] == 0x02:
        data = data[:64]
    if len(data) == 64 and data[0] == 0x02:
        return data
    if len(data) == 63 and data[0] == 0x05:
        return b"\x02" + data
    return None


def read_request_packet(address, count):
    """Build the pinned 64-byte normal-mode read request (report ID included)."""
    if not (0 < count <= MAX_CHUNK):
        raise ValueError("read length outside the reviewed 1..46 byte range")
    in_boot_app = address < 0x19000 and count <= 0x19000 - address
    in_update = 0x3F000 <= address < 0x53000 and count <= 0x53000 - address
    if not in_boot_app and not in_update:
        raise ValueError("read address outside the reviewed saved regions")
    packet = bytearray(64)
    packet[0] = OUTPUT_REPORT_ID
    packet[1] = READ_COMMAND
    p16(packet, 2, READ_COMMAND)
    p16(packet, 6, count)
    p32(packet, 10, count)
    p32(packet, 14, address)
    return bytes(packet)


def read_data(device, address, count):
    """Issue exactly one bounded read command and return its payload.

    No retry is attempted. A timeout or malformed response returns ``None``.
    """
    try:
        packet = read_request_packet(address, count)
    except ValueError as exc:
        print(f"Refusing read: {exc}")
        return None
    try:
        device.write(packet)
    except Exception as exc:  # HidError, OSError, ValueError
        print(f"Read failed at 0x{address:08x}, length {count}: {exc}")
        return None

    deadline = time.monotonic() + READ_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        try:
            # Windows may prepend a report-ID byte, so ask for more than the
            # 64-byte protocol report and normalize down to exactly 64 bytes.
            raw = device.read(256, remaining_ms)
        except Exception as exc:
            print(f"Read failed at 0x{address:08x}, length {count}: {exc}")
            return None
        report = normalize_read_report(raw)
        if report is None:
            continue
        if len(report) < 18 or report[0] != 0x02 or report[1] != 0x05:
            continue
        if u16(report, 2) != 0 or u16(report, 4) != READ_COMMAND:
            continue
        if (u16(report, 6) != count or u32(report, 10) != count
                or u32(report, 14) != address or len(report) < 18 + count):
            continue
        return report[18:18 + count]
    print(f"Read failed at 0x{address:08x}, length {count}; no matching response, no retry.")
    return None


def open_reader():
    """Open the single matching normal-mode vendor HID interface."""
    from windows_hid import open_hid_device, select_device, verify_output_report_shape

    info = select_device(VENDOR_ID, PRODUCT_ID, USAGE_PAGE, USAGE, "normal-mode vendor")
    device = open_hid_device(info)
    try:
        verify_output_report_shape(device, OUTPUT_REPORT_ID, 64, "normal-mode vendor")
    except Exception:
        device.close()
        raise
    return device


def read_version_and_validate(device):
    header = read_data(device, 0x6000, 32)
    if header is None or header[8:12] != b"KNLT":
        print("No validated Telink application header; no version inferred.")
        return False
    version = u16(header, 2)
    print(f"Telink image header. Installed firmware version: {version // 100}.{version % 100:02d} "
          f"(raw {version}).")
    if version != 109 or u32(header, 24) != 0x12274:
        print("Refusing: these flash bounds have only been established for the v1.09 header.")
        return False
    return True


def backup_region(device, output_path, base, length, region):
    try:
        output = open(output_path, "xb")
    except FileExistsError:
        print(f"Error: output already exists; refusing to overwrite it: {output_path}",
              file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Error creating backup without overwrite: {exc}", file=sys.stderr)
        return 1

    result = 0
    done = 0
    try:
        with output:
            while done < length:
                count = min(MAX_CHUNK, length - done)
                chunk = read_data(device, base + done, count)
                if chunk is None or len(chunk) != count:
                    result = 1
                    break
                output.write(chunk)
                done += count
                if done // 4096 != (done - count) // 4096 or done == length:
                    print(f"Read {done} / {length} {region} bytes", flush=True)
    except OSError as exc:
        print(f"Error writing backup: {exc}", file=sys.stderr)
        result = 1

    state = "Complete" if result == 0 and done == length else "INCOMPLETE"
    print(f"{state} {region}-region backup: {output_path} ({done} / {length} bytes).")
    print("A readback snapshot does not establish recovery entry or prove restoration.")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read the 8BitDo Ultimate 2C normal-mode firmware version or save "
                    "bounded snapshots. This tool never writes flash.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--backup", metavar="FILE", help="save the application region")
    group.add_argument("--backup-boot", metavar="FILE", help="save the boot region")
    group.add_argument("--backup-padding", metavar="FILE", help="save the application sector tail")
    group.add_argument("--backup-update", metavar="FILE",
                       help="save update metadata and staging")
    args = parser.parse_args(argv)

    try:
        device = open_reader()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        if not read_version_and_validate(device):
            return 1
        for flag, (base, length, region) in REGIONS.items():
            if getattr(args, flag[2:].replace("-", "_")) is not None:
                return backup_region(device, getattr(args, flag[2:].replace("-", "_")),
                                     base, length, region)
        return 0
    finally:
        device.close()


if __name__ == "__main__":
    sys.exit(main())
