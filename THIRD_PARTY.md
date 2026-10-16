# Credits and redistribution boundaries

## Exact-model firmware and bootloader research

[Crazyawk/8bitdo-ultimate2c-macos-rumble](https://github.com/Crazyawk/8bitdo-ultimate2c-macos-rumble) supplied valuable exact-model Telink firmware-format, GATT and bootloader protocol research. Its rumble patch is a different feature and is not included here. This repository's host tools build on that protocol work and the subsequent USB readback, bootloader disassembly, Apple-profile investigation and hardware checks described in the documentation.

The upstream repository's [MIT license](https://github.com/Crazyawk/8bitdo-ultimate2c-macos-rumble/blob/main/LICENSE) is retained below for code derived from or adapted using its host-tool implementations. Its separate GPL-licensed historical downloader is **not** included; the downloader here independently retrieves one pinned URL and verifies exact bytes.

```text
MIT License

Copyright (c) 2026 Muhammad Ahmed

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Vendor firmware and Apple controller profiles

8BitDo firmware is not included, relicensed or claimed as project-authored software. Obtain the original from the vendor for your own device. Generated firmware and device snapshots remain local. This repository provides patch code, hashes, minimal identity/checksum offsets and protocol facts, not a redistributable firmware image.

Apple controller-database files/frameworks are not included. Their behavior was inspected on a local Mac. The published documentation records the relevant identity/range contract and observations rather than copying complete Apple profiles.

8BitDo, SN30 Pro+, Apple, Mac and Apple TV are their respective owners' names/trademarks. The compatibility identity is not a claim that this device is an actual SN30 Pro+ or officially supported by Apple/8BitDo.
