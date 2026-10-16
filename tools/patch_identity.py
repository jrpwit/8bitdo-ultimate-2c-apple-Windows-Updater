#!/usr/bin/env python3
"""Create the experimental, single-unit-tested v1.09 BLE identity patch offline.

The tested model is the 8BitDo Ultimate 2C Wireless Controller in Bluetooth mode,
not the Ultimate 2C Bluetooth Controller, Ultimate 2, or a USB receiver. Native
Mac input was measured on one unit; the user confirmed tvOS operation after
fresh pairing. This is not a universal compatibility guarantee.

Only the BLE PnP product ID and Telink CRC change. The report descriptor and
executable code remain unchanged; this does not install SN30 Pro+ firmware.
This tool never accesses hardware, downloads firmware, or flashes a controller.
"""

import argparse
import hashlib
import os
from pathlib import Path
import struct
import sys
import zlib


BASE_SHA256 = "87349e603bb92d6ae9ff6defb6f32b10de2f2d3252fe4e442fa7993f982f2a5a"
PATCHED_SHA256 = "e52216167e7f3f5e0a15d14b68b345b54a12a8b637b1052ddc1d595a0a57c88f"
HEADER = (109, 0x6000, 0x12400, 0x301B, 0xA420DCC3, 0, 0)
WRAPPER_SIZE = 28
FILE_SIZE = WRAPPER_SIZE + HEADER[2]
IMAGE_SIZE = 0x12274
BASE_CRC = 0xA8BE5C24
PATCHED_CRC = 0xA204A342
GATT_TABLE_OFFSET = 0x11458
PNP_HANDLE = 0x0E
GATT_ENTRY = struct.Struct("<HBBIIIII")
PNP_ENTRY = (0, 1, 2, 7, 0x172AC, 0x173C0, 0, 0)
PNP_VALUE = bytes.fromhex("02 c8 2d 1b 30 01 00")
PNP_OFFSET = 0x113DC
DESCRIPTOR_OFFSET = 0x11368
DESCRIPTOR_SIZE = 116
DESCRIPTOR_SHA256 = "faf72db6502aec039db8e5c163c3f01e6f2c16486439d1dece7b91b140e32a58"
CHANGED_OFFSETS = (0x113DF, 0x113E0, 0x1228C, 0x1228D, 0x1228E, 0x1228F)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def patch(source):
    """Return (patched bytearray, original SHA-256, actual changed DAT offsets).

    Only the pinned official v1.09 image is supported. Failure never changes
    the supplied source; all validation happens before a CLI output is created.
    """
    require(len(source) == FILE_SIZE, "Input is not the exact official DAT size")
    before_sha = hashlib.sha256(source).hexdigest()
    require(before_sha == BASE_SHA256, "Input SHA-256 does not match the verified official v1.09 DAT")
    require(struct.unpack_from("<7I", source) == HEADER, "Official DAT header mismatch")
    require(source[WRAPPER_SIZE + 8:WRAPPER_SIZE + 12] == b"KNLT", "Telink signature mismatch")
    image_size = struct.unpack_from("<I", source, WRAPPER_SIZE + 0x18)[0]
    require(image_size == IMAGE_SIZE, "Telink image size mismatch")
    crc_offset = WRAPPER_SIZE + image_size - 4
    stored_crc = struct.unpack_from("<I", source, crc_offset)[0]
    computed_crc = (~zlib.crc32(memoryview(source)[WRAPPER_SIZE:crc_offset])) & 0xFFFFFFFF
    require(stored_crc == BASE_CRC and stored_crc == computed_crc, "Original Telink CRC verification failed")

    entry_offset = GATT_TABLE_OFFSET + PNP_HANDLE * GATT_ENTRY.size
    entry = GATT_ENTRY.unpack_from(source, entry_offset)
    require(entry == PNP_ENTRY, "Handle 0x000e GATT entry mismatch")
    uuid_offset = WRAPPER_SIZE + entry[4] - HEADER[1]
    value_offset = WRAPPER_SIZE + entry[5] - HEADER[1]
    require(source[uuid_offset:uuid_offset + 2] == b"\x50\x2a", "GATT UUID is not 0x2a50")
    require(value_offset == PNP_OFFSET, "GATT PnP value pointer mismatch")
    require(source[value_offset:value_offset + entry[3]] == PNP_VALUE, "Original seven-byte PnP value mismatch")
    descriptor = source[DESCRIPTOR_OFFSET:DESCRIPTOR_OFFSET + DESCRIPTOR_SIZE]
    require(hashlib.sha256(descriptor).hexdigest() == DESCRIPTOR_SHA256, "Original BLE report descriptor mismatch")

    result = bytearray(source)
    pid_offset = value_offset + 3
    struct.pack_into("<HH", result, pid_offset, 0x6002, 0x0001)
    new_crc = (~zlib.crc32(memoryview(result)[WRAPPER_SIZE:crc_offset])) & 0xFFFFFFFF
    require(new_crc == PATCHED_CRC, "Unexpected patched Telink CRC")
    struct.pack_into("<I", result, crc_offset, new_crc)

    changed_offsets = [offset for offset, (before, after) in enumerate(zip(source, result)) if before != after]
    require(len(result) == len(source), "Patch unexpectedly changed the file size")
    require(tuple(changed_offsets) == CHANGED_OFFSETS, "Patch must change exactly the six pinned PID/CRC bytes")
    require(result[value_offset:value_offset + 7] == bytes.fromhex("02 c8 2d 02 60 01 00"), "Patched PnP value mismatch")
    require(result[DESCRIPTOR_OFFSET:DESCRIPTOR_OFFSET + DESCRIPTOR_SIZE] == descriptor,
            "Patch changed the BLE report descriptor")
    require(struct.unpack_from("<I", result, crc_offset)[0] ==
            ((~zlib.crc32(memoryview(result)[WRAPPER_SIZE:crc_offset])) & 0xFFFFFFFF),
            "Patched Telink CRC verification failed")
    require(hashlib.sha256(result).hexdigest() == PATCHED_SHA256, "Patched SHA-256 does not match the tested image")
    return result, before_sha, changed_offsets


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="exact official v1.09 DAT (read-only)")
    parser.add_argument("output", type=Path, help="new patched DAT; existing paths are refused")
    args = parser.parse_args(argv)
    try:
        require(args.source.resolve() != args.output.resolve(), "Input and output must be different paths")
        require(not os.path.lexists(args.output), "Output already exists; refusing to overwrite it")
        with args.source.open("rb") as input_file:
            source = input_file.read(FILE_SIZE + 1)
        result, before_sha, changed_offsets = patch(source)
        # Exclusive creation also rejects symlinks and paths created after preflight.
        with args.output.open("xb") as output_file:
            output_file.write(result)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("WARNING: Experimental firmware tested on one unit; no universal compatibility guarantee.")
    print("Mac input was measured; tvOS operation was user-confirmed. No hardware was accessed or flashed.")
    print(f"Before SHA-256: {before_sha}")
    print(f"After  SHA-256: {PATCHED_SHA256}")
    print("Changed DAT byte offsets: " + ", ".join(f"0x{offset:x}" for offset in changed_offsets))
    print(f"Created: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
