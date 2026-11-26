#!/usr/bin/env python3
"""Windows observation helper for a freshly paired Ultimate 2C (patched PID).

Replaces the macOS GameController observation tool with two independent views:

* Raw BLE HID reports for USB/Bluetooth identity ``2dc8:6002`` (read-only).
* SDL/pygame joystick samples for every connected gamepad, including axis
  travel, button press/release, and D-pad hats.

It sends no output reports and no firmware commands. Use it only for
measurement; it does not declare a compatibility verdict.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

VENDOR_ID = 0x2DC8
PRODUCT_ID = 0x6002


class JoystickObservation:
    def __init__(self, joystick):
        self.joystick = joystick
        self.name = joystick.get_name()
        self.guid = joystick.get_guid() if hasattr(joystick, "get_guid") else "?"
        self.instance_id = (
            joystick.get_instance_id() if hasattr(joystick, "get_instance_id") else None
        )
        self.axes = [0.0] * joystick.get_numaxes()
        self.axis_min = list(self.axes)
        self.axis_max = list(self.axes)
        self.axis_last = list(self.axes)
        self.buttons = [0] * joystick.get_numbuttons()
        self.button_min = list(self.buttons)
        self.button_max = list(self.buttons)
        self.button_last = list(self.buttons)
        self.pressed_seen = [False] * len(self.buttons)
        self.released_seen = [False] * len(self.buttons)
        self.hat_masks = set()
        self.samples = 0

    def sample(self):
        for index in range(len(self.axes)):
            value = self.joystick.get_axis(index)
            if self.samples == 0 or value < self.axis_min[index]:
                self.axis_min[index] = value
            if self.samples == 0 or value > self.axis_max[index]:
                self.axis_max[index] = value
            self.axis_last[index] = value
            self.axes[index] = value
        for index in range(len(self.buttons)):
            value = self.joystick.get_button(index)
            if self.samples == 0 or value < self.button_min[index]:
                self.button_min[index] = value
            if self.samples == 0 or value > self.button_max[index]:
                self.button_max[index] = value
            self.button_last[index] = value
            self.buttons[index] = value
            if value:
                self.pressed_seen[index] = True
            else:
                self.released_seen[index] = True
        mask = 0
        for index in range(self.joystick.get_numhats()):
            x, y = self.joystick.get_hat(index)
            mask |= 1 if x < 0 else 0
            mask |= 2 if x > 0 else 0
            mask |= 4 if y > 0 else 0
            mask |= 8 if y < 0 else 0
        self.hat_masks.add(mask)
        self.samples += 1

    def summary(self, number):
        print(f"NATIVE controller #{number} name={self.name!r} guid={self.guid} "
              f"samples={self.samples}")
        for index in range(len(self.axes)):
            print(f"NATIVE AXIS axis {index}: min={self.axis_min[index]:+.4f} "
                  f"max={self.axis_max[index]:+.4f} last={self.axis_last[index]:+.4f}")
        print("NATIVE D-PAD/hat masks observed "
              "(left=1 right=2 up=4 down=8; 0=neutral):"
              + "".join(f" 0x{mask:x}" for mask in sorted(self.hat_masks)))
        for index in range(len(self.buttons)):
            print(f"NATIVE BUTTON {index}: pressed-seen={int(self.pressed_seen[index])} "
                  f"released-seen={int(self.released_seen[index])} "
                  f"min={self.button_min[index]:.4f} max={self.button_max[index]:.4f} "
                  f"last={self.button_last[index]:.4f}")


def open_hid_observer():
    try:
        from windows_hid import enumerate_devices, open_hid_device
    except Exception as exc:
        print(f"Raw HID observation unavailable: {exc}")
        return None
    try:
        devices = enumerate_devices(VENDOR_ID, PRODUCT_ID)
    except Exception as exc:
        print(f"Raw HID enumeration failed: {exc}")
        return None
    print(f"Matched BLE HID devices={len(devices)} "
          "(raw observation only; no reports are sent)")
    if len(devices) != 1:
        if devices:
            print("More than one matching collection; raw HID observation skipped.")
        return None
    try:
        return open_hid_device(devices[0])
    except Exception as exc:
        print(f"Raw HID open failed (SDL observations continue): {exc}")
        return None


def init_pygame():
    try:
        import pygame  # type: ignore
    except ImportError:
        print("pygame is not installed; joystick measurements are unavailable.")
        print("Install it with: .venv\\Scripts\\python.exe -m pip install -r requirements-observe.txt")
        return None
    try:
        pygame.init()
        pygame.joystick.init()
    except Exception as exc:
        print(f"pygame joystick initialization failed: {exc}")
        return None
    return pygame


def scan_joysticks(pygame, observations, known_ids):
    for index in range(pygame.joystick.get_count()):
        try:
            joystick = pygame.joystick.Joystick(index)
            joystick.init()
            instance_id = (
                joystick.get_instance_id() if hasattr(joystick, "get_instance_id") else None
            )
            key = instance_id if instance_id is not None else (joystick.get_name(), index)
            if key in known_ids:
                continue
            observation = JoystickObservation(joystick)
            known_ids.add(key)
            observations.append(observation)
            print(f"SDL gamepad #{len(observations)} name={observation.name!r} "
                  f"axes={len(observation.axes)} buttons={len(observation.buttons)} "
                  f"hats={joystick.get_numhats()}")
        except Exception as exc:
            print(f"Could not read SDL gamepad index {index}: {exc}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Observe a paired patched controller for SECONDS (0 < seconds <= 180). "
                    "Read-only: no output reports or firmware commands are sent.",
    )
    parser.add_argument("seconds", nargs="?", type=float, default=10.0)
    args = parser.parse_args(argv)
    if not (0 < args.seconds <= 180):
        parser.error("SECONDS must be greater than 0 and at most 180")

    print(f"READY: observing {args.seconds:.2f} seconds; no output reports or firmware commands")
    start = time.monotonic()
    deadline = start + args.seconds

    pygame = init_pygame()
    observations = []
    known_ids = set()
    if pygame is not None:
        scan_joysticks(pygame, observations, known_ids)

    device = open_hid_observer()
    reports = 0
    changes = 0
    previous = None
    next_scan = start

    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            if pygame is not None:
                pygame.event.pump()
                if now >= next_scan:
                    scan_joysticks(pygame, observations, known_ids)
                    next_scan = now + 0.5
                for observation in list(observations):
                    try:
                        observation.sample()
                    except Exception as exc:
                        print(f"SDL gamepad {observation.name!r} stopped responding: {exc}")
                        observations.remove(observation)
            if device is not None:
                try:
                    report = bytes(device.read(256, 50))
                except Exception as exc:
                    print(f"Raw HID read stopped: {exc}")
                    device.close()
                    device = None
                    report = b""
                if report:
                    reports += 1
                    if report != previous:
                        previous = report
                        changes += 1
                        if changes <= 100:
                            print(f"HID change={changes} bytes={len(report)} data="
                                  + " ".join(f"{byte:02x}" for byte in report))
    except KeyboardInterrupt:
        print("Observation interrupted by user.")
    finally:
        if device is not None:
            device.close()

    elapsed = time.monotonic() - start
    print(f"RESULT elapsed={elapsed:.2f}s SDL controllers={len(observations)} "
          f"HID reports={reports} distinct consecutive reports={changes}")
    for number, observation in enumerate(observations, 1):
        observation.summary(number)
    if not observations:
        print("No SDL gamepads were observed. Pair the controller in Windows Settings, "
              "then run this tool again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
