CC := xcrun clang
PYTHON ?= python3
CFLAGS ?= -O2
OBJCFLAGS := -fobjc-arc -Wall -Wextra
FRAMEWORKS := -framework Foundation -framework IOKit

.PHONY: all test
all: build/read_firmware build/boot_firmware build/observe_controller

build:
	mkdir -p build

build/read_firmware: native/read_firmware.m | build
	$(CC) $(CFLAGS) $(OBJCFLAGS) $(FRAMEWORKS) $< -o $@

build/boot_firmware: native/boot_firmware.m | build
	$(CC) $(CFLAGS) $(OBJCFLAGS) $(FRAMEWORKS) $< -o $@

build/observe_controller: native/observe_controller.m | build
	$(CC) $(CFLAGS) $(OBJCFLAGS) $(FRAMEWORKS) -framework GameController $< -o $@

build/test_boot_protocol: tests/test_boot_protocol.m native/boot_firmware.m | build
	$(CC) -O1 -g $(OBJCFLAGS) -fsanitize=address,undefined $(FRAMEWORKS) $< -o $@

test: build/test_boot_protocol
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v
	./build/test_boot_protocol
