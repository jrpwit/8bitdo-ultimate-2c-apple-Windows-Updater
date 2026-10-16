#import <Foundation/Foundation.h>
#import <GameController/GameController.h>
#import <IOKit/hid/IOHIDLib.h>
#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// Read-only observation: HID matches 2dc8:6002; GameController enumerates all
// native controllers separately. Native profiles cannot be reliably associated
// with a VID/PID here, so disconnect other gamepads for an unambiguous result.
static unsigned reports, changes, gcEvents;
static uint8_t previous[256];
static CFIndex previousLength = -1;
@interface ControllerObservation : NSObject {
@public
    unsigned samples, dpadMasks;
    float axisMin[4], axisMax[4], axisLast[4];
    float buttonMin[6], buttonMax[6], buttonLast[6];
    BOOL pressedSeen[6], releasedSeen[6];
}
@property(nonatomic, strong) GCController *controller;
@end
@implementation ControllerObservation
@end
static NSMutableArray<ControllerObservation *> *observed;
static void recordGamepad(ControllerObservation *observation, GCExtendedGamepad *gamepad) {
    float axes[4] = {gamepad.leftThumbstick.xAxis.value, gamepad.leftThumbstick.yAxis.value,
        gamepad.rightThumbstick.xAxis.value, gamepad.rightThumbstick.yAxis.value};
    for (unsigned i = 0; i < 4; ++i) {
        if (!observation->samples || axes[i] < observation->axisMin[i]) observation->axisMin[i] = axes[i];
        if (!observation->samples || axes[i] > observation->axisMax[i]) observation->axisMax[i] = axes[i];
        observation->axisLast[i] = axes[i];
    }
    GCControllerButtonInput *buttons[6] = {gamepad.buttonA, gamepad.buttonB, gamepad.buttonX,
        gamepad.buttonY, gamepad.leftTrigger, gamepad.rightTrigger};
    for (unsigned i = 0; i < 6; ++i) {
        float value = buttons[i].value;
        if (!observation->samples || value < observation->buttonMin[i]) observation->buttonMin[i] = value;
        if (!observation->samples || value > observation->buttonMax[i]) observation->buttonMax[i] = value;
        observation->buttonLast[i] = value;
        if (buttons[i].isPressed) observation->pressedSeen[i] = YES;
        else observation->releasedSeen[i] = YES;
    }
    unsigned mask = (gamepad.dpad.left.isPressed ? 1 : 0) | (gamepad.dpad.right.isPressed ? 2 : 0) |
        (gamepad.dpad.up.isPressed ? 4 : 0) | (gamepad.dpad.down.isPressed ? 8 : 0);
    observation->dpadMasks |= 1u << mask;
    ++observation->samples;
}
static void reportCallback(void *context, IOReturn result, void *sender, IOHIDReportType type, uint32_t reportID, uint8_t *report, CFIndex length) {
    (void)context; (void)sender; (void)type;
    if (result != kIOReturnSuccess || length < 0 || (size_t)length > sizeof(previous)) return;
    reports++;
    if (length == previousLength && memcmp(previous, report, (size_t)length) == 0) return;
    memcpy(previous, report, (size_t)length); previousLength = length;
    changes++;
    if (changes <= 100) {
        printf("HID change=%u report=%u bytes=%ld data=", changes, reportID, (long)length);
        for (CFIndex i = 0; i < length; i++) printf("%02x%s", report[i], i + 1 == length ? "" : " ");
        puts("");
    }
}
static void inspectControllers(void) {
    for (GCController *controller in GCController.controllers) {
        BOOL known = NO;
        for (ControllerObservation *observation in observed) if (observation.controller == controller) { known = YES; break; }
        if (known) continue;
        ControllerObservation *observation = [ControllerObservation new];
        observation.controller = controller;
        [observed addObject:observation];
        printf("GC controller #%lu vendor=%s category=%s extended=%d micro=%d\n", (unsigned long)observed.count, controller.vendorName.UTF8String ?: "(nil)", controller.productCategory.UTF8String ?: "(nil)", controller.extendedGamepad != nil, controller.microGamepad != nil);
        GCExtendedGamepad *gamepad = controller.extendedGamepad;
        if (gamepad) recordGamepad(observation, gamepad);
        __weak ControllerObservation *weakObservation = observation;
        controller.physicalInputProfile.valueDidChangeHandler = ^(GCPhysicalInputProfile *profile, GCControllerElement *element) {
            (void)profile;
            ControllerObservation *current = weakObservation;
            if (!current) return;
            ++gcEvents;
            GCExtendedGamepad *currentGamepad = current.controller.extendedGamepad;
            // Measurements continue after the textual event log reaches its cap.
            if (currentGamepad) recordGamepad(current, currentGamepad);
            if (gcEvents <= 100) printf("GC event=%u element=%s\n", gcEvents, element.description.UTF8String);
        };
    }
}
static void printSummary(void) {
    const char *axisNames[] = {"Left X", "Left Y", "Right X", "Right Y"};
    const char *buttonNames[] = {"A", "B", "X", "Y", "Left trigger", "Right trigger"};
    unsigned index = 0;
    for (ControllerObservation *observation in observed) {
        printf("NATIVE controller #%u samples=%u (initial state plus value-change snapshots)\n", ++index, observation->samples);
        if (!observation->samples) { puts("No extended-gamepad measurements."); continue; }
        for (unsigned i = 0; i < 4; ++i)
            printf("NATIVE AXIS %s: min=%+.4f max=%+.4f last=%+.4f\n", axisNames[i], observation->axisMin[i], observation->axisMax[i], observation->axisLast[i]);
        printf("NATIVE D-PAD masks observed (left=1 right=2 up=4 down=8; 0=neutral):");
        for (unsigned mask = 0; mask < 16; ++mask) if (observation->dpadMasks & (1u << mask)) printf(" 0x%x", mask);
        puts("");
        for (unsigned i = 0; i < 6; ++i)
            printf("NATIVE BUTTON %s: pressed-seen=%d released-seen=%d min=%.4f max=%.4f last=%.4f\n", buttonNames[i], observation->pressedSeen[i], observation->releasedSeen[i], observation->buttonMin[i], observation->buttonMax[i], observation->buttonLast[i]);
        observation.controller.physicalInputProfile.valueDidChangeHandler = nil;
    }
}
int main(int argc, char **argv) {
    @autoreleasepool {
        setbuf(stdout, NULL);
        double duration = 10;
        if (argc > 2) { fputs("Usage: observe_controller [SECONDS (0 < seconds <= 180)]\n", stderr); return 2; }
        if (argc == 2) {
            char *end = NULL;
            errno = 0; duration = strtod(argv[1], &end);
            if (errno || end == argv[1] || *end || !isfinite(duration) || duration <= 0 || duration > 180) {
                fputs("Usage: observe_controller [SECONDS (0 < seconds <= 180)]\n", stderr); return 2;
            }
        }
        observed = [NSMutableArray array];
        GCController.shouldMonitorBackgroundEvents = YES;
        inspectControllers();
        IOHIDManagerRef manager = IOHIDManagerCreate(kCFAllocatorDefault, kIOHIDOptionsTypeNone);
        if (!manager) { puts("HID manager creation failed."); return 1; }
        NSDictionary *match = @{@kIOHIDVendorIDKey:@0x2dc8, @kIOHIDProductIDKey:@0x6002};
        IOHIDManagerSetDeviceMatching(manager, (__bridge CFDictionaryRef)match);
        IOReturn opened = IOHIDManagerOpen(manager, kIOHIDOptionsTypeNone);
        printf("HID manager open=0x%08x\n", opened);
        if (opened != kIOReturnSuccess) { CFRelease(manager); return 1; }
        NSSet *deviceSet = CFBridgingRelease(IOHIDManagerCopyDevices(manager));
        printf("Matched BLE HID devices=%lu; native GC observations include every connected gamepad.\n", (unsigned long)deviceSet.count);
        uint8_t reportBuffer[256] = {0};
        IOHIDDeviceRef device = NULL;
        BOOL deviceOpened = NO;
        if (deviceSet.count == 1) {
            device = (__bridge IOHIDDeviceRef)deviceSet.anyObject;
            CFRetain(device);
            IOReturn status = IOHIDDeviceOpen(device, kIOHIDOptionsTypeNone);
            printf("HID device open=0x%08x (non-exclusive)\n", status);
            deviceOpened = status == kIOReturnSuccess;
            if (deviceOpened) {
                IOHIDDeviceRegisterInputReportCallback(device, reportBuffer, sizeof(reportBuffer), reportCallback, NULL);
                IOHIDDeviceScheduleWithRunLoop(device, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode);
            }
        }
        printf("READY: observing %.2f seconds; no output reports or firmware commands\n", duration);
        CFAbsoluteTime deadline = CFAbsoluteTimeGetCurrent() + duration;
        while (CFAbsoluteTimeGetCurrent() < deadline) {
            CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.1, true);
            inspectControllers();
        }
        printf("RESULT GC controller connections observed=%lu GC events=%u HID reports=%u distinct consecutive reports=%u\n", (unsigned long)observed.count, gcEvents, reports, changes);
        printSummary();
        if (device) {
            if (deviceOpened) {
                IOHIDDeviceUnscheduleFromRunLoop(device, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode);
                IOHIDDeviceClose(device, kIOHIDOptionsTypeNone);
            }
            CFRelease(device);
        }
        IOHIDManagerClose(manager, kIOHIDOptionsTypeNone);
        CFRelease(manager);
    }
    return 0;
}
