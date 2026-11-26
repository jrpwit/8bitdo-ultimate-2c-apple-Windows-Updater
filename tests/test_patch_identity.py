"""Offline safety tests; set EIGHTBITDO_STOCK_DAT for exact real-image coverage.

No vendor firmware fixture is included. Generated files live in temporary
folders outside the repository. These tests never access controller hardware
or download firmware.
"""

import contextlib
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch as mock_patch


TOOLS = Path(__file__).resolve().parents[1] / "tools"


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


patch_identity = load_tool("patch_identity")
fetch_firmware = load_tool("fetch_firmware")


def run_cli(tool, *arguments):
    """Exercise CLI behavior without a subprocess or terminal output."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return tool.main([str(argument) for argument in arguments])


class PatchRejectionTests(unittest.TestCase):
    def test_rejects_wrong_sizes(self):
        for size in (0, patch_identity.FILE_SIZE - 1, patch_identity.FILE_SIZE + 1):
            with self.subTest(size=size):
                with self.assertRaisesRegex(ValueError, "size"):
                    patch_identity.patch(bytes(size))

    def test_rejects_unknown_correct_sized_image(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            patch_identity.patch(bytes(patch_identity.FILE_SIZE))

    def test_invalid_input_creates_no_output_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.dat"
            output = Path(directory) / "patched.dat"
            source.write_bytes(b"not vendor firmware")
            self.assertEqual(run_cli(patch_identity, source, output), 1)
            self.assertFalse(os.path.lexists(output))
            self.assertEqual(source.read_bytes(), b"not vendor firmware")



class FetchOutputSafetyTests(unittest.TestCase):
    def test_refuses_existing_output_without_downloading(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.dat"
            output.write_bytes(b"preserve existing output")
            with mock_patch.object(fetch_firmware.urllib.request, "urlopen",
                                   side_effect=AssertionError("Existing output must be rejected before network access")):
                self.assertEqual(run_cli(fetch_firmware, output), 1)
            self.assertEqual(output.read_bytes(), b"preserve existing output")

    def test_refuses_dangling_output_without_downloading(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "missing.dat"
            output = Path(directory) / "dangling.dat"
            try:
                output.symlink_to(target)
            except (OSError, NotImplementedError) as exc:
                # Windows needs Developer Mode or admin rights to create
                # symlinks. The production check is os.path.lexists(); the
                # path-exists case and the dangling case cannot both be
                # exercised without symlink support, so skip only this fixture.
                self.skipTest(f"cannot create a test symlink here: {exc}")
            with mock_patch.object(fetch_firmware.urllib.request, "urlopen",
                                   side_effect=AssertionError("Dangling output must be rejected before network access")):
                self.assertEqual(run_cli(fetch_firmware, output), 1)
            self.assertTrue(output.is_symlink())
            self.assertFalse(target.exists())


@unittest.skipUnless(os.environ.get("EIGHTBITDO_STOCK_DAT"),
                     "Set EIGHTBITDO_STOCK_DAT to the private pinned official v1.09 DAT")
class RealFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_path = Path(os.environ["EIGHTBITDO_STOCK_DAT"])
        cls.stock = cls.source_path.read_bytes()

    def test_exact_six_changes_and_all_other_bytes_preserved(self):
        result, before_sha, changed_offsets = patch_identity.patch(self.stock)
        expected_offsets = [0x113DF, 0x113E0, 0x1228C, 0x1228D, 0x1228E, 0x1228F]
        self.assertEqual(len(result), 74780)
        self.assertEqual(before_sha, "87349e603bb92d6ae9ff6defb6f32b10de2f2d3252fe4e442fa7993f982f2a5a")
        self.assertEqual(hashlib.sha256(result).hexdigest(),
                         "e52216167e7f3f5e0a15d14b68b345b54a12a8b637b1052ddc1d595a0a57c88f")
        self.assertEqual(changed_offsets, expected_offsets)
        actual_changes = [(offset, before, after)
                          for offset, (before, after) in enumerate(zip(self.stock, result))
                          if before != after]
        self.assertEqual(actual_changes, [
            (0x113DF, 0x1B, 0x02), (0x113E0, 0x30, 0x60),
            (0x1228C, 0x24, 0x42), (0x1228D, 0x5C, 0xA3),
            (0x1228E, 0xBE, 0x04), (0x1228F, 0xA8, 0xA2),
        ])
        # Each complementary span must match, not merely the reported diff list.
        start = 0
        for offset in expected_offsets + [len(self.stock)]:
            self.assertEqual(result[start:offset], self.stock[start:offset])
            start = offset + 1
        descriptor = result[0x11368:0x11368 + 116]
        self.assertEqual(hashlib.sha256(descriptor).hexdigest(),
                         "faf72db6502aec039db8e5c163c3f01e6f2c16486439d1dece7b91b140e32a58")
        self.assertEqual(self.source_path.read_bytes(), self.stock)

    def test_mutable_source_is_not_modified(self):
        source = bytearray(self.stock)
        patch_identity.patch(source)
        self.assertEqual(source, self.stock)

    def test_cli_output_hash_source_preservation_and_overwrite_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "patched.dat"
            self.assertEqual(run_cli(patch_identity, self.source_path, output), 0)
            generated = output.read_bytes()
            self.assertEqual(hashlib.sha256(generated).hexdigest(),
                             "e52216167e7f3f5e0a15d14b68b345b54a12a8b637b1052ddc1d595a0a57c88f")
            self.assertEqual(run_cli(patch_identity, self.source_path, output), 1)
            self.assertEqual(output.read_bytes(), generated)
            self.assertEqual(self.source_path.read_bytes(), self.stock)

    def test_real_source_refuses_dangling_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "missing.dat"
            output = Path(directory) / "dangling.dat"
            output.symlink_to(target)
            self.assertEqual(run_cli(patch_identity, self.source_path, output), 1)
            self.assertTrue(output.is_symlink())
            self.assertFalse(target.exists())
            self.assertEqual(self.source_path.read_bytes(), self.stock)

    def test_real_source_refuses_itself_as_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "original.dat"
            source.write_bytes(self.stock)
            self.assertEqual(run_cli(patch_identity, source, source), 1)
            self.assertEqual(source.read_bytes(), self.stock)

    def test_rejects_one_byte_changed_vendor_image(self):
        changed = bytearray(self.stock)
        changed[0] ^= 1
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            patch_identity.patch(changed)


if __name__ == "__main__":
    unittest.main()
