#!/usr/bin/env python3
"""Windows port of the guarded 8BitDo Ultimate 2C BOOT firmware writer.

Behavior is intentionally identical to ``native/boot_firmware.m``:

* Accepts only the pinned stock or patched v1.09 DAT.
* Requires all four user-created snapshots and refuses if any pinned hash,
  stock application image, update metadata or protocol vector is wrong.
* Talks only to USB ``2dc8:3208``, usage page ``0x008c`` / usage ``1``.
* Erases only differing 4-KiB application sectors (all sectors for --restore),
  verifies every erased byte is 0xff, programs within 46-byte and 256-byte page
  limits, then reads back the complete app/tail, BOOT and update regions.
* Sends the explicit reset only after that full verification succeeds. Any
  failure stops without an automatic retry or reset.

There is deliberately no --force option.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

from boot_protocol import (
    APP_BASE,
    APP_SIZE,
    BOOT_SHA,
    CANDIDATE_DAT_SHA,
    CMD_ERASE,
    CMD_IDENTITY,
    CMD_PROGRAM,
    CMD_READ,
    CMD_RESET,
    DAT_SIZE,
    MAX_CHUNK,
    ORIGINAL_DAT_SHA,
    REGION_SIZE,
    TAIL_SHA,
    UPDATE_BASE,
    UPDATE_SIZE,
    BootResponse,
    build_request,
    crc16,
    image_header_is_valid,
    image_part,
    metadata_is_inactive,
    replace_sector,
    u16,
    u32,
)

BOOT_VENDOR_ID = 0x2DC8
BOOT_PRODUCT_ID = 0x3208
BOOT_USAGE_PAGE = 0x008C
BOOT_USAGE = 1

ARTIFACT_NAMES = {
    "original": "original-v1.09-restore.dat",
    "application": "original-application-v1.09.bin",
    "boot": "original-boot-region.bin",
    "tail": "original-application-sector-tail.bin",
    "update": "original-update-metadata-and-staging.bin",
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def load(path, length, expected_sha=None):
    """Load an exact-size artifact and optionally pin its SHA-256."""
    try:
        if not path.is_file():
            raise FileNotFoundError
        data = path.read_bytes()
    except OSError:
        print(f"Missing/wrong-size artifact: {path}")
        return None
    if len(data) != length or (expected_sha is not None and sha256(data) != expected_sha):
        print(f"Artifact read/SHA-256 mismatch: {path}")
        return None
    return data


class BootSession:
    """Send guarded BOOT commands over a packet transport.

    ``transport`` must provide ``write(packet: bytes)`` for a 64-byte protocol
    packet and ``read(max_length: int, timeout_ms: int) -> bytes``. The Windows
    backend adds the Win32 report-ID prefix; the fake transport in the tests
    receives the packet exactly as built by :func:`build_request`.
    """

    def __init__(self, transport):
        self.transport = transport
        self.response = BootResponse()

    def exchange(self, command, address, count, total, payload=None):
        try:
            packet = build_request(command, address, count, total, payload)
        except ValueError as exc:
            print(f"Refusing command {command} at 0x{address:x}: {exc}")
            return False
        self.response.expect(command, address, count, total)
        try:
            self.transport.write(packet)
        except Exception as exc:
            print(f"Transport error: command {command} address 0x{address:x}: {exc}")
            return False

        timeout = 10.0 if command == CMD_ERASE else 3.0
        deadline = time.monotonic() + timeout
        while not self.response.ready and time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            try:
                # Wait up to the command deadline without repeatedly cancelling
                # the read; a slow first identity response must not be lost.
                report = self.transport.read(64, remaining_ms)
            except Exception as exc:
                print(f"Transport read error: command {command} address 0x{address:x}: {exc}")
                return False
            if not report:
                continue
            self.response.accept(report)
        if not self.response.ready or self.response.status != 0:
            print(f"Rejected/timed-out command {command} at 0x{address:x}; no retry.")
            return False
        if command == CMD_IDENTITY:
            if (u16(self.response.data, 6) != 2 or u32(self.response.data, 10) != 2
                    or u16(self.response.data, 18) != 0x301B):
                print("BOOT application identity mismatch.")
                return False
        return True

    def identity(self):
        return self.exchange(CMD_IDENTITY, 0, 4, 4)

    def compare_range(self, address, expected):
        offset = 0
        while offset < len(expected):
            chunk = min(MAX_CHUNK, len(expected) - offset)
            if not self.exchange(CMD_READ, address + offset, chunk, chunk):
                return False
            if self.response.payload[:chunk] != expected[offset:offset + chunk]:
                print(f"Readback differs at 0x{address + offset:x}.")
                return False
            offset += chunk
        return True

    def compare_image(self, app, tail):
        return (
            self.compare_range(APP_BASE, app)
            and self.compare_range(APP_BASE + APP_SIZE, tail)
        )

    def reset(self):
        return self.exchange(CMD_RESET, 0, 0, 0)


def program_application(session, target, padding, original, restore=False):
    """Erase, blank-check and program selected application sectors.

    ``target`` and ``original`` are 0x12400-byte application regions; ``padding``
    is the 0xc00-byte preserved final-sector tail. Flash mode writes only
    differing sectors. ``restore=True`` deliberately rewrites all 19 sectors so
    a damaged application can be repaired. Nothing outside
    ``[0x6000, 0x19000)`` is ever touched.
    """
    for sector in range(0, REGION_SIZE, 0x1000):
        if not replace_sector(restore, sector, target, original):
            continue
        if not session.exchange(CMD_ERASE, APP_BASE + sector, 0, 0x1000):
            return False
        # Erase acknowledgement is not proof of erase: verify all 4096 bytes.
        offset = 0
        while offset < 0x1000:
            chunk = min(MAX_CHUNK, 0x1000 - offset)
            if not session.exchange(CMD_READ, APP_BASE + sector + offset, chunk, chunk):
                return False
            if any(byte != 0xFF for byte in session.response.payload[:chunk]):
                print(f"Erase readback is not blank at 0x{APP_BASE + sector + offset:x}.")
                return False
            offset += chunk

        offset = sector
        while offset < sector + 0x1000:
            part, available = image_part(target, padding, offset)
            if part is None:
                print(f"Image plan ended unexpectedly at 0x{APP_BASE + offset:x}.")
                return False
            count = min(
                MAX_CHUNK,
                available,
                sector + 0x1000 - offset,
                0x100 - ((APP_BASE + offset) & 0xFF),
            )
            if count <= 0:
                print(f"Invalid program length at 0x{APP_BASE + offset:x}.")
                return False
            data = bytes(part[:count])
            if not session.exchange(CMD_PROGRAM, APP_BASE + offset, count, REGION_SIZE, data):
                return False
            offset += count
        print(f"Programmed application sector 0x{APP_BASE + sector:x}; "
              "full verification follows.")
    return True


class WindowsBootTransport:
    """Exclusive Windows BOOT interface with protocol report framing."""

    def __init__(self):
        from windows_hid import open_exclusive_hid, select_device

        info = select_device(
            BOOT_VENDOR_ID, BOOT_PRODUCT_ID, BOOT_USAGE_PAGE, BOOT_USAGE, "BOOT"
        )
        self.device = open_exclusive_hid(info)
        try:
            caps = self.device.get_caps()
            if caps.UsagePage != BOOT_USAGE_PAGE or caps.Usage != BOOT_USAGE:
                raise RuntimeError(
                    f"BOOT usage mismatch: got 0x{caps.UsagePage:04x}/0x{caps.Usage:02x}, "
                    f"expected 0x{BOOT_USAGE_PAGE:04x}/0x{BOOT_USAGE:02x}."
                )
            if caps.OutputReportByteLength == 65:
                self.prefix = b"\x00"
            elif caps.OutputReportByteLength == 64:
                self.prefix = b""
            else:
                raise RuntimeError(
                    "Refusing: BOOT output report length is "
                    f"{caps.OutputReportByteLength} bytes, expected 64 or 65."
                )
            # ReadFile requires a buffer at least as large as the Windows input
            # report length, which may include an extra zero report-ID byte.
            self.input_length = max(64, caps.InputReportByteLength)
            print("BOOT interface opened exclusively; "
                  f"Windows input/output report length "
                  f"{caps.InputReportByteLength}/{caps.OutputReportByteLength} bytes.")
        except Exception:
            self.device.close()
            raise

    def write(self, packet):
        if len(packet) != 64:
            raise ValueError("BOOT protocol packet must be exactly 64 bytes")
        self.device.write(self.prefix + packet, timeout_ms=3000)

    def read(self, max_length=64, timeout_ms=50):
        return self.device.read(max(64, self.input_length, max_length), timeout_ms)

    def close(self):
        self.device.close()


def verify_static_inputs(image_path, action):
    """Load and validate the image plus all four snapshots.

    Returns a context dict on success or ``None`` on failure. This function
    never opens HID hardware.
    """
    directory = image_path.parent if str(image_path.parent) else Path(".")
    image = load(image_path, DAT_SIZE)
    if image is None:
        return None
    stock = sha256(image) == ORIGINAL_DAT_SHA
    patched = sha256(image) == CANDIDATE_DAT_SHA
    if ((action == "--check-image" and not stock and not patched)
            or (action == "--flash" and not patched)
            or (action in ("--restore", "--verify-reset") and not stock)):
        print("Unsupported image SHA-256 for requested action.")
        return None

    original = image if stock else load(
        directory / ARTIFACT_NAMES["original"], DAT_SIZE, ORIGINAL_DAT_SHA
    )
    saved_app = load(directory / ARTIFACT_NAMES["application"], APP_SIZE)
    boot = load(directory / ARTIFACT_NAMES["boot"], 0x6000, BOOT_SHA)
    tail = load(directory / ARTIFACT_NAMES["tail"], 0xC00, TAIL_SHA)
    update = load(directory / ARTIFACT_NAMES["update"], UPDATE_SIZE)
    if None in (original, saved_app, boot, tail, update):
        return None

    if (not image_header_is_valid(image) or not image_header_is_valid(original)
            or saved_app != original[28:28 + APP_SIZE]
            or crc16(b"123456789") != 0x4B37):
        print("Fixed image/header/protocol or stock application backup checks failed.")
        return None
    if not metadata_is_inactive(update):
        print("Update metadata corrupt or pending installation present; "
              "refusing every hardware action.")
        return None

    print("Verified known image, exact stock backup, pinned BOOT/tail and inactive update snapshot.")
    return {
        "image": image,
        "stock": stock,
        "original": original,
        "saved_app": saved_app,
        "boot": boot,
        "tail": tail,
        "update": update,
        "target_app": image[28:28 + APP_SIZE],
        "old_app": original[28:28 + APP_SIZE],
    }


def run(action, image_path, transport_factory=None):
    """Execute one action. ``transport_factory`` is injectable for tests."""
    context = verify_static_inputs(image_path, action)
    if context is None:
        return 1
    if action == "--check-image":
        print("Image-only check completed; no hardware accessed.")
        return 0

    if transport_factory is None:
        transport_factory = WindowsBootTransport
    try:
        transport = transport_factory()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    session = BootSession(transport)
    result = 1
    try:
        valid = (
            session.identity()
            and session.compare_range(0, context["boot"])
            and session.compare_range(UPDATE_BASE, context["update"])
        )
        # Restoration must accept a damaged application/tail.
        if valid and action != "--restore":
            valid = session.compare_image(context["old_app"], context["tail"])
        if valid and action != "--verify-reset":
            print("BOOT and inactive update storage verified. "
                  "Beginning application-only sector replacement.")
            valid = program_application(
                session,
                context["target_app"],
                context["tail"],
                context["old_app"],
                restore=(action == "--restore"),
            )
        if valid:
            valid = (
                session.compare_image(context["target_app"], context["tail"])
                and session.compare_range(0, context["boot"])
                and session.compare_range(UPDATE_BASE, context["update"])
            )
        if valid:
            print("Complete app/tail, BOOT and update storage match; "
                  "sending explicit reset.")
            valid = session.reset()
            if valid:
                print("Reset acknowledged. Normal USB/Bluetooth behavior and "
                      "BOOT reentry must be observed separately.")
                result = 0
        if result != 0:
            print("STOPPED: no automatic retry/reset. Keep BOOT available; "
                  "use guarded --restore after resolving the failure.")
        return result
    finally:
        try:
            transport.close()
        except Exception:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Guarded Windows writer for the exact 8BitDo Ultimate 2C "
                    "v1.09 BOOT protocol.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--check-image", dest="action", action="store_const", const="--check-image",
        help="offline image check; no hardware is opened",
    )
    group.add_argument(
        "--verify-reset", dest="action", action="store_const", const="--verify-reset",
        help="recovery identity/readback check followed by an explicit reset",
    )
    group.add_argument(
        "--flash", dest="action", action="store_const", const="--flash",
        help="erase/program only the differing patched sectors",
    )
    group.add_argument(
        "--restore", dest="action", action="store_const", const="--restore",
        help="rewrite all application sectors from the pinned stock image",
    )
    parser.add_argument("image", type=Path, metavar="IMAGE.dat",
                        help="pinned v1.09 DAT (patched for --flash)")
    args = parser.parse_args(argv)
    return run(args.action, args.image)


if __name__ == "__main__":
    sys.exit(main())
