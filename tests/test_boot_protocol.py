"""Offline regression tests for the Windows BOOT protocol implementation.

These tests port the original ``tests/test_boot_protocol.m`` checks and add a
stateful fake BOOT transport. No HID hardware is touched and no real firmware
is required.
"""

import contextlib
import hashlib
import io
import struct
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import boot_protocol as bp  # noqa: E402
import boot_firmware  # noqa: E402
import read_firmware  # noqa: E402
import windows_hid  # noqa: E402


def make_ack(command, count, total, address, payload=b"", status=0):
    """Build a 64-byte macOS/IOKit-style BOOT response (leading report ID 0)."""
    ack = bytearray(64)
    ack[0] = 0
    ack[1] = 5
    bp.p16(ack, 2, status)
    bp.p16(ack, 4, command)
    bp.p16(ack, 6, count)
    bp.p32(ack, 10, total)
    bp.p32(ack, 14, address)
    ack[18:18 + len(payload)] = payload
    return bytes(ack)


def make_read_ack(count, address, payload=b"", status=0):
    """Build a 64-byte normal-mode read response (report ID 0x02 first)."""
    ack = bytearray(64)
    ack[0] = 0x02
    ack[1] = 5
    bp.p16(ack, 2, status)
    bp.p16(ack, 4, 5)
    bp.p16(ack, 6, count)
    bp.p32(ack, 10, count)
    bp.p32(ack, 14, address)
    ack[18:18 + len(payload)] = payload
    return bytes(ack)


class AcknowledgementTests(unittest.TestCase):
    def test_erase_ack_with_cleared_total(self):
        response = bp.BootResponse()
        response.expect(bp.CMD_ERASE, 0x6000, 0, 0x1000)
        self.assertTrue(response.accept(make_ack(bp.CMD_ERASE, 0, 0, 0x6000)))
        self.assertEqual(response.status, 0)

    def test_matching_rejection_is_surfaced(self):
        response = bp.BootResponse()
        response.expect(bp.CMD_ERASE, 0x6000, 0, 0x1000)
        self.assertTrue(response.accept(make_ack(bp.CMD_ERASE, 0, 0, 0x6000, status=1)))
        self.assertEqual(response.status, 1)

    def test_stale_erase_ack_from_another_sector_is_ignored(self):
        response = bp.BootResponse()
        response.expect(bp.CMD_ERASE, 0x6000, 0, 0x1000)
        self.assertFalse(response.accept(make_ack(bp.CMD_ERASE, 0, 0, 0x7000)))

    def test_ack_for_another_operation_is_ignored(self):
        response = bp.BootResponse()
        response.expect(bp.CMD_ERASE, 0x6000, 0, 0x1000)
        self.assertFalse(response.accept(make_ack(bp.CMD_PROGRAM, 0, 0, 0x6000)))

    def test_truncated_or_malformed_report_is_ignored(self):
        response = bp.BootResponse()
        response.expect(bp.CMD_ERASE, 0x6000, 0, 0x1000)
        full = make_ack(bp.CMD_ERASE, 0, 0, 0x6000)
        self.assertFalse(response.accept(full[:17]))
        self.assertFalse(response.accept(b"\x02" + full[1:]))
        self.assertFalse(response.accept(None))

    def test_program_ack_retains_request_bounds(self):
        response = bp.BootResponse()
        response.expect(bp.CMD_PROGRAM, 0x17000, 46, bp.REGION_SIZE)
        self.assertTrue(response.accept(
            make_ack(bp.CMD_PROGRAM, 46, bp.REGION_SIZE, 0x17000)
        ))
        response.ready = False
        self.assertFalse(response.accept(
            make_ack(bp.CMD_PROGRAM, 46, 0, 0x17000)
        ))

    def test_read_ack_in_update_range_and_wrong_count(self):
        response = bp.BootResponse()
        response.expect(bp.CMD_READ, bp.UPDATE_BASE, 46, 46)
        self.assertTrue(response.accept(
            make_ack(bp.CMD_READ, 46, 46, bp.UPDATE_BASE)
        ))
        response.ready = False
        self.assertFalse(response.accept(
            make_ack(bp.CMD_READ, 45, 46, bp.UPDATE_BASE)
        ))

    def test_windows_unnumbered_report_is_normalized(self):
        # 64-byte unnumbered payload: 0x05 marker and no leading report-ID byte.
        payload = make_ack(bp.CMD_READ, 46, 46, 0x6000)[1:] + b"\x00"
        self.assertEqual(len(payload), 64)
        normalized = bp.normalize_boot_report(payload)
        self.assertEqual(len(normalized), 64)
        self.assertEqual(normalized[:2], b"\x00\x05")
        self.assertEqual(normalized[2:18], payload[1:17])
        self.assertEqual(normalized[18:64], payload[17:63])
        # 65-byte Windows buffer with an explicit zero report ID is canonical.
        self.assertEqual(bp.normalize_boot_report(b"\x00" + payload), normalized)
        self.assertIsNone(bp.normalize_boot_report(b"\x05" * 10))

        response = bp.BootResponse()
        response.expect(bp.CMD_READ, 0x6000, 46, 46)
        self.assertTrue(response.accept(payload))
        self.assertEqual(response.status, 0)
        self.assertEqual(response.payload[:46], bytes(46))

    def test_real_windows_identity_report_shape(self):
        # Captured from Windows: report ID 0 + controller payload 00 05 ...
        raw = bytes.fromhex(
            "000005000008000200000002000000000000001b300000000000000000000000"
            "0000000000000000000000000000000000000000000000000000000000000000"
            "00"
        )
        self.assertEqual(len(raw), 65)
        self.assertEqual(bp.normalize_boot_report(raw)[:2], b"\x00\x05")

        response = bp.BootResponse()
        response.expect(bp.CMD_IDENTITY, 0, 4, 4)
        self.assertTrue(response.accept(raw))
        self.assertEqual(response.status, 0)
        self.assertEqual(bp.u16(response.data, 6), 2)
        self.assertEqual(bp.u32(response.data, 10), 2)
        self.assertEqual(bp.u16(response.data, 18), 0x301B)


class RangeTests(unittest.TestCase):
    def setUp(self):
        self.payload = bytes(46)

    def test_erase_ranges(self):
        self.assertTrue(bp.request_is_allowed(4, 0x6000, 0, 0x1000))
        self.assertTrue(bp.request_is_allowed(4, 0x18000, 0, 0x1000))
        self.assertFalse(bp.request_is_allowed(4, 0x5000, 0, 0x1000))
        self.assertFalse(bp.request_is_allowed(4, 0x19000, 0, 0x1000))
        self.assertFalse(bp.request_is_allowed(4, 0x6001, 0, 0x1000))
        self.assertFalse(bp.request_is_allowed(4, bp.UPDATE_BASE, 0, 0x1000))
        self.assertFalse(bp.request_is_allowed(4, 0x6000, 0, 0x2000))

    def test_program_ranges(self):
        self.assertTrue(bp.request_is_allowed(3, 0x60D2, 46, bp.REGION_SIZE, self.payload))
        self.assertFalse(bp.request_is_allowed(3, 0x60D3, 46, bp.REGION_SIZE, self.payload))
        self.assertTrue(bp.request_is_allowed(3, 0x18FFF, 1, bp.REGION_SIZE, self.payload))
        self.assertFalse(bp.request_is_allowed(3, 0x18FFF, 2, bp.REGION_SIZE, self.payload))
        self.assertFalse(bp.request_is_allowed(3, 0x5FFF, 1, bp.REGION_SIZE, self.payload))
        self.assertFalse(bp.request_is_allowed(3, bp.UPDATE_BASE, 1, bp.REGION_SIZE, self.payload))
        self.assertFalse(bp.request_is_allowed(3, 0x6000, 47, bp.REGION_SIZE, self.payload))
        self.assertFalse(bp.request_is_allowed(3, 0x6000, 1, bp.APP_SIZE, self.payload))
        self.assertFalse(bp.request_is_allowed(3, 0x6000, 1, bp.REGION_SIZE, None))

    def test_read_ranges(self):
        self.assertTrue(bp.request_is_allowed(5, 0, 46, 46))
        self.assertTrue(bp.request_is_allowed(5, 0x18FFF, 1, 1))
        self.assertFalse(bp.request_is_allowed(5, 0x18FFF, 2, 2))
        self.assertFalse(bp.request_is_allowed(5, 0x19000, 1, 1))
        self.assertTrue(bp.request_is_allowed(5, bp.UPDATE_BASE, 46, 46))
        self.assertTrue(bp.request_is_allowed(5, 0x52FFF, 1, 1))
        self.assertFalse(bp.request_is_allowed(5, 0x52FFF, 2, 2))
        self.assertFalse(bp.request_is_allowed(5, 0xFFFFFFFF, 1, 1))
        self.assertFalse(bp.request_is_allowed(5, 0, 0, 0))
        self.assertFalse(bp.request_is_allowed(5, 0, 47, 47))
        self.assertFalse(bp.request_is_allowed(5, 0, 1, 2))

    def test_identity_reset_and_unknown(self):
        self.assertTrue(bp.request_is_allowed(8, 0, 4, 4))
        self.assertTrue(bp.request_is_allowed(7, 0, 0, 0))
        self.assertFalse(bp.request_is_allowed(7, 1, 0, 0))
        self.assertFalse(bp.request_is_allowed(6, 0, 0, 0))


class ImagePlanTests(unittest.TestCase):
    def test_image_part_boundaries(self):
        app = bytearray(bp.APP_SIZE)
        tail = bytearray(0xC00)
        app[0] = 0x11
        app[0x123FF] = 0x22
        tail[0] = 0x33
        tail[0xBFF] = 0x44
        part, available = bp.image_part(app, tail, 0)
        self.assertEqual((part[0], available), (0x11, bp.APP_SIZE))
        part, available = bp.image_part(app, tail, 0x123FF)
        self.assertEqual((part[0], available), (0x22, 1))
        part, available = bp.image_part(app, tail, 0x12400)
        self.assertEqual((part[0], available), (0x33, 0xC00))
        part, available = bp.image_part(app, tail, 0x12FFF)
        self.assertEqual((part[0], available), (0x44, 1))
        part, available = bp.image_part(app, tail, 0x13000)
        self.assertIsNone(part)
        self.assertEqual(available, 0)

    def test_sector_selection_and_restore_plan(self):
        app = bytearray(bp.APP_SIZE)
        original = bytearray(bp.APP_SIZE)
        app[0x113C3] = 1
        app[0x12270] = 2
        flash_sectors = 0
        restore_sectors = 0
        for sector in range(0, bp.REGION_SIZE, 0x1000):
            selected = bp.replace_sector(False, sector, app, original)
            self.assertEqual(selected, sector in (0x11000, 0x12000))
            flash_sectors += selected
            restore_sectors += bp.replace_sector(True, sector, app, original)
        self.assertEqual((flash_sectors, restore_sectors), (2, 19))
        app[0] = 1
        self.assertTrue(bp.replace_sector(False, 0, app, original))
        self.assertFalse(bp.replace_sector(False, bp.REGION_SIZE, app, original))
        self.assertFalse(bp.replace_sector(True, 1, app, original))
        app = bytearray(bp.APP_SIZE)
        self.assertFalse(bp.replace_sector(False, 0x12000, app, original))


class MetadataTests(unittest.TestCase):
    def test_metadata_guards(self):
        metadata = bytearray(52)
        bp.p16(metadata, 48, bp.crc16(metadata, 48))
        self.assertEqual(bp.crc16(b"123456789"), 0x4B37)
        self.assertTrue(bp.metadata_is_inactive(metadata))
        self.assertFalse(bp.metadata_is_inactive(metadata[:51]))
        self.assertFalse(bp.metadata_is_inactive(None))

        bp.p32(metadata, 24, 0x12345678)
        bp.p16(metadata, 48, bp.crc16(metadata, 48))
        self.assertFalse(bp.metadata_is_inactive(metadata))

        bp.p32(metadata, 24, 0)
        bp.p32(metadata, 32, bp.APP_SIZE)
        bp.p16(metadata, 48, bp.crc16(metadata, 48))
        self.assertFalse(bp.metadata_is_inactive(metadata))

        bp.p32(metadata, 24, 0x12345678)
        bp.p16(metadata, 48, bp.crc16(metadata, 48))
        self.assertFalse(bp.metadata_is_inactive(metadata))

        bp.p32(metadata, 24, 0)
        bp.p32(metadata, 32, 0)
        bp.p16(metadata, 48, bp.crc16(metadata, 48))
        metadata[0] ^= 1
        self.assertFalse(bp.metadata_is_inactive(metadata))
        metadata[0] ^= 1
        metadata[48] ^= 1
        self.assertFalse(bp.metadata_is_inactive(metadata))


class FakeBootTransport:
    """Stateful simulated BOOT interface for the programming workflow."""

    def __init__(self, flash=None, boot_identity=0x301B):
        self.flash = bytearray(flash if flash is not None else b"\xff" * 0x53000)
        self.boot_identity = boot_identity
        self.pending = b""
        self.erases = []
        self.programs = []
        self.resets = 0

    def write(self, packet):
        if len(packet) != 64:
            raise AssertionError("wrong packet length")
        command = bp.u16(packet, 1)
        count = bp.u16(packet, 5)
        total = bp.u32(packet, 9)
        address = bp.u32(packet, 13)
        if command == bp.CMD_IDENTITY:
            identity = bytearray(2)
            bp.p16(identity, 0, self.boot_identity)
            self.pending = make_ack(8, 2, 2, 0, identity)
        elif command == bp.CMD_READ:
            payload = bytes(self.flash[address:address + count])
            self.pending = make_ack(5, count, total, address, payload)
        elif command == bp.CMD_ERASE:
            self.erases.append(address)
            self.flash[address:address + 0x1000] = b"\xff" * 0x1000
            self.pending = make_ack(4, 0, 0, address)
        elif command == bp.CMD_PROGRAM:
            self.programs.append((address, count))
            expected_crc = bp.crc16(packet[17:17 + count], count)
            if bp.u16(packet, 7) != expected_crc:
                self.pending = make_ack(3, count, total, address, status=1)
                return
            self.flash[address:address + count] = packet[17:17 + count]
            self.pending = make_ack(3, count, total, address)
        elif command == bp.CMD_RESET:
            self.resets += 1
            self.pending = make_ack(7, 0, 0, 0)
        else:
            self.pending = make_ack(command, count, total, address, status=1)

    def read(self, max_length=64, timeout_ms=50):
        data, self.pending = self.pending, b""
        return data

    def close(self):
        pass


class BootSessionSimulationTests(unittest.TestCase):
    def test_identity_and_readback(self):
        flash = bytearray(b"\xff" * 0x53000)
        payload = bytes(range(46))
        flash[0x6000:0x6000 + 46] = payload
        transport = FakeBootTransport(flash)
        session = boot_firmware.BootSession(transport)
        self.assertTrue(session.identity())
        self.assertTrue(session.compare_range(0x6000, payload))

    def test_identity_mismatch_stops(self):
        transport = FakeBootTransport(boot_identity=0xAAAA)
        session = boot_firmware.BootSession(transport)
        self.assertFalse(session.identity())

    def test_flash_programs_only_changed_sectors_and_preserves_tail(self):
        original = bytearray(bp.APP_SIZE)
        target = bytearray(original)
        target[0x113C3] = 1
        target[0x12270] = 2
        tail = bytes((index & 0xFF) for index in range(0xC00))
        flash = bytearray(b"\xff" * 0x53000)
        flash[bp.APP_BASE:bp.APP_BASE + bp.APP_SIZE] = original
        flash[bp.APP_BASE + bp.APP_SIZE:bp.APP_BASE + bp.REGION_SIZE] = tail
        transport = FakeBootTransport(flash)
        session = boot_firmware.BootSession(transport)

        self.assertTrue(boot_firmware.program_application(session, target, tail, original))
        self.assertEqual(transport.erases, [0x17000, 0x18000])
        self.assertEqual(
            bytes(transport.flash[bp.APP_BASE:bp.APP_BASE + bp.APP_SIZE]), bytes(target)
        )
        self.assertEqual(
            bytes(transport.flash[bp.APP_BASE + bp.APP_SIZE:bp.APP_BASE + bp.REGION_SIZE]),
            tail,
        )
        # Every program request respects the 46-byte and page-boundary limits.
        for address, count in transport.programs:
            self.assertLessEqual(count, 46)
            self.assertLessEqual(count, 0x100 - (address & 0xFF))
            self.assertGreater(count, 0)

    def test_restore_rewrites_all_sectors_when_content_matches(self):
        app = bytearray(bp.APP_SIZE)
        tail = bytes(0xC00)
        flash = bytearray(b"\xff" * 0x53000)
        flash[bp.APP_BASE:bp.APP_BASE + bp.APP_SIZE] = app
        transport = FakeBootTransport(flash)
        session = boot_firmware.BootSession(transport)
        self.assertTrue(
            boot_firmware.program_application(session, app, tail, app, restore=True)
        )
        self.assertEqual(len(transport.erases), 19)


def make_dat(app):
    """Build a minimal DAT with a valid pinned-layout header for offline tests."""
    image = bytearray(28 + len(app))
    struct.pack_into(
        "<7I", image, 0, 109, bp.APP_BASE, bp.APP_SIZE, 0x301B, 0xA420DCC3, 0, 0
    )
    image[28:] = app
    return bytes(image)


class EndToEndSimulationTests(unittest.TestCase):
    def test_full_flash_action_against_fake_boot_device(self):
        stock_app = bytearray(bp.APP_SIZE)
        bp.p16(stock_app, 2, 109)
        stock_app[8:12] = b"KNLT"
        bp.p32(stock_app, 24, bp.IMAGE_SIZE)
        target_app = bytearray(stock_app)
        target_app[0x113C3] = 0xAA  # physical sector 0x17000
        target_app[0x12270] = 0xBB  # physical sector 0x18000
        stock_image = make_dat(stock_app)
        target_image = make_dat(target_app)
        boot = bytes((index * 7) & 0xFF for index in range(0x6000))
        tail = bytes((index * 11) & 0xFF for index in range(0xC00))
        update = bytearray(bp.UPDATE_SIZE)
        bp.p16(update, 48, bp.crc16(update, 48))
        update = bytes(update)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "patched-v1.09-BLE6002-r0001.dat"
            image_path.write_bytes(target_image)
            (root / boot_firmware.ARTIFACT_NAMES["original"]).write_bytes(stock_image)
            (root / boot_firmware.ARTIFACT_NAMES["application"]).write_bytes(bytes(stock_app))
            (root / boot_firmware.ARTIFACT_NAMES["boot"]).write_bytes(boot)
            (root / boot_firmware.ARTIFACT_NAMES["tail"]).write_bytes(tail)
            (root / boot_firmware.ARTIFACT_NAMES["update"]).write_bytes(update)

            flash = bytearray(b"\xff" * 0x53000)
            flash[0:0x6000] = boot
            flash[bp.APP_BASE:bp.APP_BASE + bp.APP_SIZE] = stock_app
            flash[bp.APP_BASE + bp.APP_SIZE:bp.APP_BASE + bp.REGION_SIZE] = tail
            flash[bp.UPDATE_BASE:bp.UPDATE_BASE + bp.UPDATE_SIZE] = update
            transport = FakeBootTransport(flash)

            def factory():
                return transport

            with mock.patch.multiple(
                boot_firmware,
                ORIGINAL_DAT_SHA=hashlib.sha256(stock_image).hexdigest(),
                CANDIDATE_DAT_SHA=hashlib.sha256(target_image).hexdigest(),
                BOOT_SHA=hashlib.sha256(boot).hexdigest(),
                TAIL_SHA=hashlib.sha256(tail).hexdigest(),
            ), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(boot_firmware.run("--check-image", image_path), 0)
                self.assertEqual(
                    boot_firmware.run("--flash", image_path, transport_factory=factory), 0
                )
            self.assertEqual(transport.erases, [0x17000, 0x18000])
            self.assertEqual(transport.resets, 1)
            self.assertEqual(
                bytes(transport.flash[bp.APP_BASE:bp.APP_BASE + bp.APP_SIZE]),
                bytes(target_app),
            )
            self.assertEqual(
                bytes(transport.flash[bp.APP_BASE + bp.APP_SIZE:
                                      bp.APP_BASE + bp.REGION_SIZE]),
                tail,
            )
            self.assertEqual(bytes(transport.flash[0:0x6000]), boot)
            self.assertEqual(
                bytes(transport.flash[bp.UPDATE_BASE:bp.UPDATE_BASE + bp.UPDATE_SIZE]),
                update,
            )
            text = output.getvalue()
            self.assertIn("Reset acknowledged", text)
            self.assertIn("Complete app/tail", text)

    def test_restore_repairs_damaged_application_and_preserves_other_regions(self):
        stock_app = bytearray(bp.APP_SIZE)
        bp.p16(stock_app, 2, 109)
        stock_app[8:12] = b"KNLT"
        bp.p32(stock_app, 24, bp.IMAGE_SIZE)
        stock_image = make_dat(stock_app)
        boot = bytes((index * 5) & 0xFF for index in range(0x6000))
        tail = bytes((index * 13) & 0xFF for index in range(0xC00))
        update = bytearray(bp.UPDATE_SIZE)
        bp.p16(update, 48, bp.crc16(update, 48))
        update = bytes(update)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "original-v1.09-restore.dat"
            image_path.write_bytes(stock_image)
            (root / boot_firmware.ARTIFACT_NAMES["application"]).write_bytes(bytes(stock_app))
            (root / boot_firmware.ARTIFACT_NAMES["boot"]).write_bytes(boot)
            (root / boot_firmware.ARTIFACT_NAMES["tail"]).write_bytes(tail)
            (root / boot_firmware.ARTIFACT_NAMES["update"]).write_bytes(update)

            damaged_app = bytearray(stock_app)
            damaged_app[0x100] = 0xAA
            damaged_app[0x7000] = 0xBB
            flash = bytearray(b"\xff" * 0x53000)
            flash[0:0x6000] = boot
            flash[bp.APP_BASE:bp.APP_BASE + bp.APP_SIZE] = damaged_app
            flash[bp.APP_BASE + bp.APP_SIZE:bp.APP_BASE + bp.REGION_SIZE] = tail
            flash[bp.UPDATE_BASE:bp.UPDATE_BASE + bp.UPDATE_SIZE] = update
            transport = FakeBootTransport(flash)

            def factory():
                return transport

            with mock.patch.multiple(
                boot_firmware,
                ORIGINAL_DAT_SHA=hashlib.sha256(stock_image).hexdigest(),
                CANDIDATE_DAT_SHA="unused",
                BOOT_SHA=hashlib.sha256(boot).hexdigest(),
                TAIL_SHA=hashlib.sha256(tail).hexdigest(),
            ), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    boot_firmware.run("--restore", image_path, transport_factory=factory), 0
                )

            self.assertEqual(
                transport.erases, [bp.APP_BASE + offset
                                   for offset in range(0, bp.REGION_SIZE, 0x1000)]
            )
            self.assertEqual(transport.resets, 1)
            self.assertEqual(
                bytes(transport.flash[bp.APP_BASE:bp.APP_BASE + bp.APP_SIZE]),
                bytes(stock_app),
            )
            self.assertEqual(
                bytes(transport.flash[bp.APP_BASE + bp.APP_SIZE:
                                      bp.APP_BASE + bp.REGION_SIZE]),
                tail,
            )
            self.assertEqual(bytes(transport.flash[0:0x6000]), boot)
            self.assertEqual(
                bytes(transport.flash[bp.UPDATE_BASE:bp.UPDATE_BASE + bp.UPDATE_SIZE]),
                update,
            )

    def test_check_image_fails_if_application_snapshot_does_not_match(self):
        app = bytearray(bp.APP_SIZE)
        bp.p16(app, 2, 109)
        app[8:12] = b"KNLT"
        bp.p32(app, 24, bp.IMAGE_SIZE)
        image = make_dat(app)
        boot = bytes(0x6000)
        tail = bytes(0xC00)
        update = bytearray(bp.UPDATE_SIZE)
        bp.p16(update, 48, bp.crc16(update, 48))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "original.dat"
            image_path.write_bytes(image)
            (root / boot_firmware.ARTIFACT_NAMES["application"]).write_bytes(b"\x00" * bp.APP_SIZE)
            (root / boot_firmware.ARTIFACT_NAMES["boot"]).write_bytes(boot)
            (root / boot_firmware.ARTIFACT_NAMES["tail"]).write_bytes(tail)
            (root / boot_firmware.ARTIFACT_NAMES["update"]).write_bytes(bytes(update))
            with mock.patch.multiple(
                boot_firmware,
                ORIGINAL_DAT_SHA=hashlib.sha256(image).hexdigest(),
                CANDIDATE_DAT_SHA="unused",
                BOOT_SHA=hashlib.sha256(boot).hexdigest(),
                TAIL_SHA=hashlib.sha256(tail).hexdigest(),
            ), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(boot_firmware.run("--check-image", image_path), 1)
            self.assertIn("checks failed", output.getvalue())


class BootCliTests(unittest.TestCase):
    def test_documented_flag_order_is_parsed(self):
        for flag in ("--check-image", "--verify-reset", "--flash", "--restore"):
            with mock.patch.object(boot_firmware, "run", return_value=0) as run:
                self.assertEqual(boot_firmware.main([flag, "work\\image.dat"]), 0)
                run.assert_called_once_with(flag, Path("work\\image.dat"))

    def test_no_action_is_rejected(self):
        with self.assertRaises(SystemExit) as context, \
                contextlib.redirect_stderr(io.StringIO()):
            boot_firmware.main(["image.dat"])
        self.assertEqual(context.exception.code, 2)


class ReadToolTests(unittest.TestCase):
    def test_read_request_layout(self):
        packet = read_firmware.read_request_packet(0x6000, 32)
        self.assertEqual(len(packet), 64)
        self.assertEqual(packet[0], 0x81)
        self.assertEqual(packet[1], 5)
        self.assertEqual(bp.u16(packet, 2), 5)
        self.assertEqual(bp.u16(packet, 6), 32)
        self.assertEqual(bp.u32(packet, 10), 32)
        self.assertEqual(bp.u32(packet, 14), 0x6000)

    def test_read_report_normalization(self):
        payload = bytes(range(46))
        ack = make_read_ack(46, 0x6000, payload)
        self.assertEqual(read_firmware.normalize_read_report(ack), ack)
        self.assertEqual(read_firmware.normalize_read_report(ack[1:]), ack)
        # Some Windows HID stacks return one extra trailing byte; trim it.
        self.assertEqual(read_firmware.normalize_read_report(ack + b"\x00"), ack)
        self.assertIsNone(read_firmware.normalize_read_report(b"\x00" * 64))

    def test_read_data_returns_payload(self):
        class FakeReader:
            def __init__(self):
                self.written = None
                self.response = make_read_ack(32, 0x6000, bytes(range(32)))

            def write(self, packet):
                self.written = packet

            def read(self, max_length=64, timeout_ms=50):
                data, self.response = self.response, b""
                return data

        device = FakeReader()
        self.assertEqual(read_firmware.read_data(device, 0x6000, 32), bytes(range(32)))
        self.assertEqual(device.written[0], 0x81)

    def test_read_bounds_are_refused(self):
        with self.assertRaises(ValueError):
            read_firmware.read_request_packet(0x19000, 1)
        with self.assertRaises(ValueError):
            read_firmware.read_request_packet(0x6000, 47)
        with self.assertRaises(ValueError):
            read_firmware.read_request_packet(0x6000, 0)


class WindowsTransportFramingTests(unittest.TestCase):
    def make_transport(self, output_length, input_length):
        class FakeDevice:
            def __init__(self):
                self.writes = []
                self.read_lengths = []
                self.closed = False

            def get_caps(self):
                return types.SimpleNamespace(
                    UsagePage=boot_firmware.BOOT_USAGE_PAGE,
                    Usage=boot_firmware.BOOT_USAGE,
                    InputReportByteLength=input_length,
                    OutputReportByteLength=output_length,
                )

            def write(self, data, timeout_ms=3000):
                self.writes.append(bytes(data))
                return len(data)

            def read(self, max_length=64, timeout_ms=50):
                self.read_lengths.append(max_length)
                return b"\x00" * max_length

            def close(self):
                self.closed = True

        device = FakeDevice()
        info = {"path": b"fake"}
        with mock.patch.object(windows_hid, "select_device", return_value=info), \
                mock.patch.object(windows_hid, "open_exclusive_hid", return_value=device):
            transport = boot_firmware.WindowsBootTransport()
        return transport, device

    def test_unnumbered_windows_output_gets_zero_report_id(self):
        transport, device = self.make_transport(output_length=65, input_length=65)
        packet = bytes(range(64))
        transport.write(packet)
        self.assertEqual(device.writes, [b"\x00" + packet])
        self.assertEqual(transport.prefix, b"\x00")
        transport.read(64, 50)
        self.assertGreaterEqual(device.read_lengths[-1], 65)

    def test_already_64_byte_output_is_not_prefixed(self):
        transport, device = self.make_transport(output_length=64, input_length=64)
        packet = bytes(range(64))
        transport.write(packet)
        self.assertEqual(device.writes, [packet])
        self.assertEqual(transport.prefix, b"")


class DescriptorTests(unittest.TestCase):
    def test_numbered_output_report_length_includes_id(self):
        descriptor = bytes([
            0x06, 0x00, 0xFF,  # Usage Page (vendor)
            0x09, 0x01,        # Usage (1)
            0xA1, 0x01,        # Collection (Application)
            0x85, 0x81,        # Report ID (0x81)
            0x75, 0x08,        # Report Size (8)
            0x95, 0x3F,        # Report Count (63)
            0x09, 0x01,        # Usage (1)
            0x91, 0x02,        # Output (Data,Var,Abs)
            0xC0,              # End Collection
        ])
        self.assertEqual(windows_hid.output_report_length(descriptor, 0x81), 64)
        self.assertIsNone(windows_hid.output_report_length(descriptor, 0x82))

    def test_unnumbered_output_report_length(self):
        descriptor = bytes([
            0x06, 0x00, 0xFF,
            0x09, 0x01,
            0xA1, 0x01,
            0x75, 0x08,
            0x95, 0x40,        # 64 bytes
            0x09, 0x01,
            0x91, 0x02,
            0xC0,
        ])
        self.assertEqual(windows_hid.output_report_length(descriptor, 0), 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
