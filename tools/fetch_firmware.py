#!/usr/bin/env python3
"""Download only the pinned official Ultimate 2C Wireless v1.09 DAT.

The vendor URL uses plain HTTP: it does not authenticate the server or protect
traffic. No credentials or authentication are used. The independently pinned
SHA-256 authenticates the exact expected firmware bytes, not the HTTP server.
A changed vendor image is rejected, never accepted as an automatic update.

The download is bounded and validated before creating the output. Existing
paths, including dangling symlinks, are refused. This tool does not access or
update any controller. Keep downloaded vendor firmware private; this repository
does not redistribute it.
"""

import argparse
import hashlib
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request


OFFICIAL_URL = "http://dl.8bitdo.com:8080/firmwareFile/upload/3652c29e-7b6c-4521-9426-abf153e7298b.dat"
FILE_SIZE = 74780
SHA256 = "87349e603bb92d6ae9ff6defb6f32b10de2f2d3252fe4e442fa7993f982f2a5a"
TIMEOUT_SECONDS = 30


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, metavar="OUTPUT.dat", help="new private stock firmware file")
    args = parser.parse_args(argv)
    try:
        if os.path.lexists(args.output):
            raise ValueError("Output already exists; refusing to overwrite it")
        with urllib.request.urlopen(OFFICIAL_URL, timeout=TIMEOUT_SECONDS) as response:
            data = response.read(FILE_SIZE + 1)
        if len(data) != FILE_SIZE:
            raise ValueError(f"Firmware size mismatch: expected {FILE_SIZE} bytes, received {len(data)}")
        if hashlib.sha256(data).hexdigest() != SHA256:
            raise ValueError("Firmware SHA-256 mismatch; vendor bytes changed or download is corrupt")
        # Validate first; exclusive creation refuses races and dangling symlinks.
        with args.output.open("xb") as output_file:
            output_file.write(data)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Downloaded exact pinned official v1.09 firmware over plain HTTP; SHA-256 verified.")
    print(f"SHA-256: {SHA256}")
    print(f"Created: {args.output}")
    print("No controller was accessed or updated. Keep this vendor firmware file private.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
