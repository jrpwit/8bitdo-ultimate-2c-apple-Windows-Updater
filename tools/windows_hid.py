#!/usr/bin/env python3
"""Windows HID helpers for the 8BitDo Ultimate 2C tools.

The public ``hid`` Python package (``pip install hidapi``) is used for device
enumeration and for the non-exclusive normal-mode reader. The BOOT writer uses
the same enumerated path but performs raw Win32 overlapped I/O with an
exclusive handle, matching the original macOS tool's exclusive BOOT access.

No function here decides whether a flash command is safe; that policy lives in
``boot_protocol.py``.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

USB_BUS_TYPE = 1
HID_API_BUS_NAMES = {0: "unknown", 1: "USB", 2: "Bluetooth", 3: "I2C", 4: "SPI"}


class HidError(RuntimeError):
    pass


def _hid_module():
    try:
        import hid  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on installation
        raise HidError(
            "The 'hidapi' Python package is not installed.\n"
            "Run windows\\setup.bat once, or install it with:\n"
            "  .venv\\Scripts\\python.exe -m pip install hidapi"
        ) from exc
    return hid


def enumerate_devices(vendor_id=None, product_id=None):
    hid = _hid_module()
    try:
        return list(hid.enumerate(vendor_id, product_id) if vendor_id is not None
                    else hid.enumerate())
    except OSError as exc:
        raise HidError(f"Windows HID enumeration failed: {exc}") from exc


def _path_text(path):
    if isinstance(path, bytes):
        return path.rstrip(b"\x00").decode("utf-8", errors="replace")
    return str(path).rstrip("\x00")


def describe_device(info):
    """One-line human-readable description used by diagnostics and errors."""
    vendor = info.get("vendor_id") or 0
    product = info.get("product_id") or 0
    bus = info.get("bus_type")
    bus_name = HID_API_BUS_NAMES.get(bus, str(bus)) if bus is not None else "?"
    product_name = info.get("product_string") or "(no product string)"
    usage_page = info.get("usage_page")
    usage = info.get("usage")
    usage_text = (
        f"usage_page=0x{usage_page:04x} usage=0x{usage:02x}"
        if usage_page is not None and usage is not None
        else "usage_page=? usage=?"
    )
    interface = info.get("interface_number")
    return (
        f"{vendor:04x}:{product:04x} bus={bus_name} {usage_text} "
        f"interface={interface if interface is not None else '?'} "
        f"product={product_name!r}"
    )


def format_device_table(devices):
    if not devices:
        return "  (no matching HID devices found)"
    return "\n".join(f"  - {describe_device(info)}" for info in devices)


def select_device(vendor_id, product_id, usage_page, usage, label):
    """Return exactly one USB HID interface matching the pinned identity.

    The original Objective-C tools refuse anything except exactly one matching
    vendor interface. The Windows port keeps that rule and prints every
    candidate it saw so a mismatch is diagnosable without guessing.
    """
    devices = enumerate_devices(vendor_id, product_id)
    if not devices:
        raise HidError(
            f"No {label} HID interface found for USB {vendor_id:04x}:{product_id:04x}.\n"
            "Check that the controller is connected directly by a USB data cable,\n"
            "that it is in the required normal/BOOT mode, and that no other\n"
            "controller application has it open. Run windows\\list-devices.bat\n"
            "to see every 8BitDo HID interface Windows exposes."
        )
    exact = [
        info for info in devices
        if info.get("usage_page") == usage_page and info.get("usage") == usage
    ]
    if len(exact) != 1:
        raise HidError(
            f"Refusing: expected exactly one {label} interface "
            f"(usage page 0x{usage_page:04x}, usage 0x{usage:02x}), "
            f"found {len(exact)}.\nEvery {vendor_id:04x}:{product_id:04x} interface seen:\n"
            f"{format_device_table(devices)}\n"
            "Close 8BitDo Ultimate Software, Steam, DS4Windows and other controller\n"
            "tools, then reconnect the controller."
        )
    info = exact[0]
    bus = info.get("bus_type")
    if bus is not None and int(bus) != USB_BUS_TYPE:
        raise HidError(
            f"Refusing: the selected {label} interface is not on the USB bus "
            f"({describe_device(info)})."
        )
    return info


def open_hid_device(info):
    """Open an enumerated HID device non-exclusively through hidapi."""
    hid = _hid_module()
    device = hid.device()
    try:
        device.open_path(info["path"])
        device.set_nonblocking(0)
    except (OSError, ValueError) as exc:
        raise HidError(
            "Could not open the HID interface. Close 8BitDo Ultimate Software,\n"
            "Steam, DS4Windows and any other controller/updater application first.\n"
            f"Windows/HIDAPI error: {exc}"
        ) from exc
    return device


def output_report_length(descriptor, report_id):
    """Return an output report's total byte length (including report ID).

    ``descriptor`` is the raw HID report descriptor (list of byte values). HID
    main items Input/Output/Feature accumulate their Report Size * Report Count
    bits under the current Report ID global item.
    """
    if not descriptor:
        return None
    descriptor = bytes(descriptor)
    sizes = {}
    report_size = 0
    report_count = 0
    current_report_id = 0
    stack = []
    index = 0
    while index < len(descriptor):
        prefix = descriptor[index]
        index += 1
        if prefix == 0xFE:  # long item
            if index + 2 > len(descriptor):
                return None
            data_length = descriptor[index]
            index += 2 + data_length
            continue
        length = (0, 1, 2, 4)[prefix & 0x03]
        item_type = (prefix >> 2) & 0x03
        tag = (prefix >> 4) & 0x0F
        if index + length > len(descriptor):
            return None
        data = int.from_bytes(descriptor[index:index + length], "little") if length else 0
        index += length
        if item_type == 1:  # global
            if tag == 0x7:
                report_size = data
            elif tag == 0x8:
                current_report_id = data
            elif tag == 0x9:
                report_count = data
            elif tag == 0xA:
                stack.append((report_size, report_count, current_report_id))
            elif tag == 0xB and stack:
                report_size, report_count, current_report_id = stack.pop()
        elif item_type == 0 and tag in (0x8, 0x9, 0xB):  # main
            kind = {0x8: "input", 0x9: "output", 0xB: "feature"}[tag]
            sizes[(current_report_id, kind)] = (
                sizes.get((current_report_id, kind), 0) + report_size * report_count
            )
    bits = sizes.get((report_id, "output"))
    if not bits:
        return None
    return (bits + 7) // 8 + (1 if report_id else 0)


def verify_output_report_shape(device, report_id, expected_total_bytes, label):
    """Check the live descriptor's output-report size when available.

    A parsed mismatch is always fatal. If Windows refuses to expose the raw
    descriptor, the VID/PID/usage match is still required; a warning is printed
    because the fixed packet sizes are separately bounded by the protocol.
    """
    try:
        descriptor = device.get_report_descriptor()
    except (OSError, ValueError) as exc:
        print(f"WARNING: could not read the {label} report descriptor ({exc}).")
        print("Continuing because VID/PID/usage already matched; packet lengths remain pinned.")
        return
    length = output_report_length(descriptor, report_id)
    if length is None:
        print(f"WARNING: {label} descriptor has no observable report ID 0x{report_id:02x} output.")
        print("Continuing because VID/PID/usage already matched; packet lengths remain pinned.")
        return
    if length != expected_total_bytes:
        raise HidError(
            f"Refusing: {label} output report length is {length} bytes, "
            f"expected {expected_total_bytes}. This is not the reviewed interface."
        )


# --------------------------------------------------------------------------
# Raw Win32 exclusive HID I/O (BOOT writer)
# --------------------------------------------------------------------------

if sys.platform == "win32":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _hid_dll = ctypes.WinDLL("hid", use_last_error=True)

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    FILE_FLAG_OVERLAPPED = 0x40000000
    ERROR_IO_PENDING = 997
    ERROR_OPERATION_ABORTED = 995
    ERROR_NOT_FOUND = 1168
    WAIT_OBJECT_0 = 0
    WAIT_TIMEOUT = 0x102
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    HIDP_STATUS_SUCCESS = 0x00110000

    class _OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_void_p),
            ("InternalHigh", ctypes.c_void_p),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.CreateEventW.argtypes = [
        wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR,
    ]
    _kernel32.CreateEventW.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.ReadFile.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(_OVERLAPPED),
    ]
    _kernel32.ReadFile.restype = wintypes.BOOL
    _kernel32.WriteFile.argtypes = [
        wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(_OVERLAPPED),
    ]
    _kernel32.WriteFile.restype = wintypes.BOOL
    _kernel32.GetOverlappedResult.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_OVERLAPPED),
        ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
    ]
    _kernel32.GetOverlappedResult.restype = wintypes.BOOL
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(_OVERLAPPED)]
    _kernel32.CancelIoEx.restype = wintypes.BOOL
    _kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
    _kernel32.ResetEvent.restype = wintypes.BOOL

    class _HIDP_CAPS(ctypes.Structure):
        _fields_ = [
            ("Usage", wintypes.USHORT),
            ("UsagePage", wintypes.USHORT),
            ("InputReportByteLength", wintypes.USHORT),
            ("OutputReportByteLength", wintypes.USHORT),
            ("FeatureReportByteLength", wintypes.USHORT),
            ("Reserved", wintypes.USHORT * 17),
            ("NumberLinkCollectionNodes", wintypes.USHORT),
            ("NumberInputButtonCaps", wintypes.USHORT),
            ("NumberInputValueCaps", wintypes.USHORT),
            ("NumberInputDataIndices", wintypes.USHORT),
            ("NumberOutputButtonCaps", wintypes.USHORT),
            ("NumberOutputValueCaps", wintypes.USHORT),
            ("NumberOutputDataIndices", wintypes.USHORT),
            ("NumberFeatureButtonCaps", wintypes.USHORT),
            ("NumberFeatureValueCaps", wintypes.USHORT),
            ("NumberFeatureDataIndices", wintypes.USHORT),
        ]

    _hid_dll.HidD_GetPreparsedData.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p),
    ]
    _hid_dll.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
    _hid_dll.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
    _hid_dll.HidD_FreePreparsedData.restype = wintypes.BOOLEAN
    _hid_dll.HidP_GetCaps.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_HIDP_CAPS),
    ]
    _hid_dll.HidP_GetCaps.restype = wintypes.LONG

    class WindowsExclusiveHid:
        """Exclusive overlapped HID handle opened directly with CreateFileW."""

        def __init__(self, device_path):
            self._handle = _kernel32.CreateFileW(
                device_path,
                GENERIC_READ | GENERIC_WRITE,
                0,  # no sharing: matches macOS kIOHIDOptionsTypeSeizeDevice
                None,
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OVERLAPPED,
                None,
            )
            if self._handle in (None, 0, INVALID_HANDLE_VALUE):
                error = ctypes.get_last_error()
                if error == 32:  # ERROR_SHARING_VIOLATION
                    raise HidError(
                        "The BOOT interface is already open by another application.\n"
                        "Close 8BitDo Ultimate Software, Steam, DS4Windows and every other\n"
                        "controller/updater tool, then re-enter LB+RB recovery mode."
                    )
                raise HidError(
                    f"Could not open the BOOT HID interface exclusively "
                    f"(Windows error {error}: {ctypes.FormatError(error)})."
                )
            self._event = _kernel32.CreateEventW(None, True, False, None)
            if not self._event:
                error = ctypes.get_last_error()
                _kernel32.CloseHandle(self._handle)
                raise HidError(f"Could not create the HID I/O event (Windows error {error}).")
            self._closed = False

        def _overlapped(self):
            overlapped = _OVERLAPPED()
            overlapped.hEvent = self._event
            _kernel32.ResetEvent(self._event)
            return overlapped

        def get_caps(self):
            """Return the live HIDP_CAPS (usage page, usage, report lengths)."""
            preparsed = ctypes.c_void_p()
            if not _hid_dll.HidD_GetPreparsedData(self._handle, ctypes.byref(preparsed)):
                error = ctypes.get_last_error()
                raise HidError(
                    f"Could not read HID capabilities (Windows error {error}: "
                    f"{ctypes.FormatError(error)})."
                )
            try:
                caps = _HIDP_CAPS()
                status = _hid_dll.HidP_GetCaps(preparsed, ctypes.byref(caps))
                if status not in (0, HIDP_STATUS_SUCCESS):
                    raise HidError(f"HidP_GetCaps failed with status 0x{status & 0xFFFFFFFF:08x}.")
                return caps
            finally:
                _hid_dll.HidD_FreePreparsedData(preparsed)

        def write(self, data, timeout_ms=3000):
            if self._closed:
                raise HidError("HID device is closed")
            payload = bytes(data)
            buffer = ctypes.create_string_buffer(payload, len(payload))
            transferred = wintypes.DWORD(0)
            overlapped = self._overlapped()
            ok = _kernel32.WriteFile(
                self._handle, buffer, len(payload), ctypes.byref(transferred),
                ctypes.byref(overlapped),
            )
            if not ok:
                error = ctypes.get_last_error()
                if error != ERROR_IO_PENDING:
                    raise HidError(
                        f"HID write failed (Windows error {error}: {ctypes.FormatError(error)})."
                    )
                wait = _kernel32.WaitForSingleObject(self._event, timeout_ms)
                if wait == WAIT_TIMEOUT:
                    _kernel32.CancelIoEx(self._handle, ctypes.byref(overlapped))
                    _kernel32.WaitForSingleObject(self._event, 1000)
                    raise HidError("HID write timed out; no automatic retry was attempted.")
                if wait != WAIT_OBJECT_0:
                    raise HidError("HID write wait failed; no automatic retry was attempted.")
                if not _kernel32.GetOverlappedResult(
                    self._handle, ctypes.byref(overlapped), ctypes.byref(transferred), False
                ):
                    error = ctypes.get_last_error()
                    raise HidError(
                        f"HID write completion failed (Windows error {error}: "
                        f"{ctypes.FormatError(error)})."
                    )
            return transferred.value

        def read(self, max_length=64, timeout_ms=50):
            """Return bytes, or b'' on timeout. Errors raise HidError."""
            if self._closed:
                raise HidError("HID device is closed")
            buffer = ctypes.create_string_buffer(max_length)
            transferred = wintypes.DWORD(0)
            overlapped = self._overlapped()
            ok = _kernel32.ReadFile(
                self._handle, buffer, max_length, ctypes.byref(transferred),
                ctypes.byref(overlapped),
            )
            if not ok:
                error = ctypes.get_last_error()
                if error != ERROR_IO_PENDING:
                    raise HidError(
                        f"HID read failed (Windows error {error}: {ctypes.FormatError(error)})."
                    )
                wait = _kernel32.WaitForSingleObject(self._event, timeout_ms)
                if wait == WAIT_TIMEOUT:
                    # Cancel and reap the request before returning to the caller,
                    # otherwise the next read could race an outstanding I/O.
                    _kernel32.CancelIoEx(self._handle, ctypes.byref(overlapped))
                    wait = _kernel32.WaitForSingleObject(self._event, 1000)
                    if wait != WAIT_OBJECT_0:
                        raise HidError(
                            "HID read timed out and cancellation did not complete; "
                            "device state is unknown, no retry was attempted."
                        )
                    if not _kernel32.GetOverlappedResult(
                        self._handle, ctypes.byref(overlapped),
                        ctypes.byref(transferred), False
                    ):
                        error = ctypes.get_last_error()
                        if error not in (ERROR_OPERATION_ABORTED, ERROR_NOT_FOUND):
                            raise HidError(
                                "HID read cancellation failed (Windows error "
                                f"{error}: {ctypes.FormatError(error)})."
                            )
                        return b""
                    # The report completed at the timeout boundary; use it
                    # instead of discarding a valid response.
                    return buffer.raw[:transferred.value]
                if wait != WAIT_OBJECT_0:
                    raise HidError("HID read wait failed.")
                if not _kernel32.GetOverlappedResult(
                    self._handle, ctypes.byref(overlapped), ctypes.byref(transferred), False
                ):
                    error = ctypes.get_last_error()
                    raise HidError(
                        f"HID read completion failed (Windows error {error}: "
                        f"{ctypes.FormatError(error)})."
                    )
            return buffer.raw[:transferred.value]

        def close(self):
            if not self._closed:
                self._closed = True
                if self._event:
                    _kernel32.CloseHandle(self._event)
                _kernel32.CloseHandle(self._handle)


def open_exclusive_hid(info):
    if sys.platform != "win32":
        raise HidError("Exclusive Win32 HID access is only available on Windows.")
    return WindowsExclusiveHid(_path_text(info["path"]))
