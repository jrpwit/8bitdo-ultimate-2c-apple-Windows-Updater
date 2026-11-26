#!/usr/bin/env python3
"""Pure guard and packet logic for the 8BitDo Ultimate 2C BOOT interface.

This module performs no HID or file I/O. It is shared by the Windows
``boot_firmware.py`` tool and the offline regression tests, so every safety
boundary can be exercised without a controller attached.

The protocol facts and limits mirror the original macOS ``native/boot_firmware.m``
and are pinned to the exact v1.09 image documented in ``data/firmware.json``.
"""

from __future__ import annotations

# Flash map for the pinned controller firmware. All ends are exclusive.
APP_BASE = 0x6000
APP_SIZE = 0x12400
REGION_SIZE = 0x13000
UPDATE_BASE = 0x3F000
UPDATE_SIZE = 0x14000

DAT_SIZE = 74780
WRAPPER_SIZE = 28
IMAGE_SIZE = 0x12274

ORIGINAL_DAT_SHA = "87349e603bb92d6ae9ff6defb6f32b10de2f2d3252fe4e442fa7993f982f2a5a"
CANDIDATE_DAT_SHA = "e52216167e7f3f5e0a15d14b68b345b54a12a8b637b1052ddc1d595a0a57c88f"
BOOT_SHA = "d64d7096c29f0f4ee21981df4b3f738c7895f209cdbdeb81f941838820be340d"
TAIL_SHA = "1a7493ff2f2bde5f78405d46eb01abfeaea9b0a95fa5b6cec211b05faa0cf1d3"

# BOOT commands recovered from the pinned original BOOT region.
CMD_PROGRAM = 3
CMD_ERASE = 4
CMD_READ = 5
CMD_RESET = 7
CMD_IDENTITY = 8

MAX_CHUNK = 46


def u16(data, offset=0):
    return data[offset] | (data[offset + 1] << 8)


def u32(data, offset=0):
    return u16(data, offset) | (u16(data, offset + 2) << 16)


def p16(data, offset, value):
    data[offset] = value & 0xFF
    data[offset + 1] = (value >> 8) & 0xFF


def p32(data, offset, value):
    p16(data, offset, value & 0xFFFF)
    p16(data, offset + 2, (value >> 16) & 0xFFFF)


def crc16(data, count=None):
    """Modbus CRC16, initial 0xffff, as used by BOOT program packets."""
    if count is None:
        count = len(data)
    crc = 0xFFFF
    for index in range(count):
        crc ^= data[index]
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


def metadata_is_inactive(data):
    """True only for valid update metadata with no pending installation."""
    return (
        data is not None
        and len(data) >= 52
        and u16(data, 48) == crc16(data, 48)
        and u32(data, 24) == 0
        and u32(data, 32) == 0
    )


def image_header_is_valid(image):
    """Check the DAT wrapper and embedded Telink header of a v1.09 image."""
    if len(image) != WRAPPER_SIZE + APP_SIZE:
        return False
    app = image[WRAPPER_SIZE:]
    return (
        u32(image, 0) == 109
        and u32(image, 4) == APP_BASE
        and u32(image, 8) == APP_SIZE
        and u32(image, 12) == 0x301B
        and u16(app, 2) == 109
        and app[8:12] == b"KNLT"
        and u32(app, 24) == IMAGE_SIZE
    )


def request_is_allowed(command, address, count, total, payload=None):
    """Reject every BOOT request outside the reviewed flash footprint.

    ``payload`` is ``None`` for no data, or bytes-like data for command 3.
    """
    if command == CMD_ERASE:
        return (
            payload is None
            and count == 0
            and total == 0x1000
            and APP_BASE <= address < APP_BASE + REGION_SIZE
            and not (address & 0xFFF)
        )
    if command == CMD_PROGRAM:
        return (
            payload is not None
            and 0 < count <= MAX_CHUNK
            and len(payload) >= count
            and total == REGION_SIZE
            and APP_BASE <= address < APP_BASE + REGION_SIZE
            and count <= APP_BASE + REGION_SIZE - address
            and count <= 0x100 - (address & 0xFF)
        )
    if command == CMD_READ:
        in_boot_app = address < APP_BASE + REGION_SIZE and count <= APP_BASE + REGION_SIZE - address
        in_update = (
            UPDATE_BASE <= address < UPDATE_BASE + UPDATE_SIZE
            and count <= UPDATE_BASE + UPDATE_SIZE - address
        )
        return (
            payload is None
            and 0 < count <= MAX_CHUNK
            and total == count
            and (in_boot_app or in_update)
        )
    if command == CMD_IDENTITY:
        return payload is None and address == 0 and count == 4 and total == 4
    if command == CMD_RESET:
        return payload is None and address == 0 and count == 0 and total == 0
    return False


def build_request(command, address, count, total, payload=None):
    """Build the 64-byte BOOT host packet (without the report-ID prefix).

    The Windows backend prepends the unnumbered report ID byte (0x00) when it
    writes the packet. The macOS tool passes this same 64-byte packet to IOKit.
    """
    if not request_is_allowed(command, address, count, total, payload):
        raise ValueError("Refusing to build an out-of-policy BOOT request")
    packet = bytearray(64)
    packet[0] = 5
    p16(packet, 1, command)
    p16(packet, 5, count)
    p16(packet, 7, crc16(payload, count) if payload is not None else 0)
    p32(packet, 9, total)
    p32(packet, 13, address)
    if payload is not None:
        packet[17:17 + count] = payload[:count]
    return bytes(packet)


def normalize_boot_report(report):
    """Normalize a raw BOOT input report to the 64-byte IOKit-style layout.

    The controller's 64-byte BOOT payload can itself begin with a zero byte
    (the IOKit layout), and Windows may then prepend its own zero report-ID
    byte. A real Windows identity reply was observed as the 65-byte shape
    ``00 00 05 ...``; dropping only the Windows ID leaves the canonical
    ``00 05 ...`` layout. Other stacks omit the Windows ID or the device's
    leading zero, so all observed shapes are accepted.
    """
    if report is None:
        return None
    data = bytes(report)
    if len(data) >= 65 and data[0] == 0 and data[1] == 0 and data[2] == 5:
        # Windows report ID + the controller's own leading zero + marker.
        return data[1:65]
    if len(data) >= 64 and data[0] == 0 and data[1] == 5:
        # No extra Windows ID byte; already the desired layout.
        return data[:64]
    if len(data) >= 64 and data[0] == 5:
        # Windows omitted its report ID and the controller omitted the leading
        # zero; insert one. The 64th protocol byte is unused.
        return b"\x00" + data[:63]
    return None


class BootResponse:
    """Match one outstanding BOOT request against incoming reports.

    Mirrors the original callback contract: erase acknowledgements clear the
    count/total fields, while program/read acknowledgements echo them.
    """

    def __init__(self):
        self.command = 0
        self.count = 0
        self.address = 0
        self.total = 0
        self.ready = False
        self.data = bytes(64)

    def expect(self, command, address, count, total):
        self.command = command
        self.count = count
        self.address = address
        self.total = total
        self.ready = False
        self.data = bytes(64)

    def accept(self, report):
        """Return True when ``report`` is a matching, well-formed response."""
        data = normalize_boot_report(report)
        if data is None:
            return False
        if data[0] != 0 or data[1] != 5:
            return False
        if u16(data, 4) != self.command:
            return False
        count = 0 if self.command == CMD_ERASE else self.count
        total = 0 if self.command == CMD_ERASE else self.total
        if self.command != CMD_IDENTITY:
            if u16(data, 6) != count or u32(data, 10) != total or u32(data, 14) != self.address:
                return False
        self.data = data
        self.ready = True
        return True

    @property
    def status(self):
        return u16(self.data, 2)

    @property
    def payload(self):
        return self.data[18:]


def image_part(app, tail, offset):
    """Return (memoryview at ``offset``, available bytes in that part).

    The application is ``app`` (0x12400 bytes) and the preserved final-sector
    tail is ``tail`` (0xc00 bytes). A byte outside the 0x13000 footprint is
    rejected with (None, 0).
    """
    if offset >= REGION_SIZE:
        return None, 0
    if offset < APP_SIZE:
        return memoryview(app)[offset:], APP_SIZE - offset
    return memoryview(tail)[offset - APP_SIZE:], REGION_SIZE - offset


def replace_sector(restore, sector, target, original):
    """Decide whether a 4-KiB application sector must be erased/programmed.

    ``target`` and ``original`` are the raw 0x12400-byte application regions.
    Flash mode writes only differing sectors. Restore mode deliberately
    rewrites all 19 application/tail sectors. The saved tail is identical on
    both sides, so only application bytes are compared.
    """
    if sector >= REGION_SIZE or (sector & 0xFFF):
        return False
    count = min(APP_SIZE - sector, 0x1000)
    if count <= 0:
        return False
    return bool(restore) or target[sector:sector + count] != original[sector:sector + count]
