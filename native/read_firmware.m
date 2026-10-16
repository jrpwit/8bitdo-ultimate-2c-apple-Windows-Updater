#import <Foundation/Foundation.h>
#import <IOKit/hid/IOHIDLib.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>

// Exact 2dc8:310a vendor-HID path. Only READ_DATA (5) is available, bounded
// to the reviewed v1.09 BOOT/application/update regions. No writes or reset.
static uint16_t u16(const uint8_t *p) { return p[0] | ((uint16_t)p[1] << 8); }
static uint32_t u32(const uint8_t *p) { return u16(p) | ((uint32_t)u16(p + 2) << 16); }
static void put16(uint8_t *p, uint16_t v) { p[0] = v; p[1] = v >> 8; }
static void put32(uint8_t *p, uint32_t v) { put16(p, v); put16(p + 2, v >> 16); }
static struct { BOOL received; uint8_t bytes[64]; uint32_t address; uint16_t count; } response;
static void input(void *context, IOReturn result, void *sender, IOHIDReportType type, uint32_t reportID, uint8_t *bytes, CFIndex length) {
    (void)context; (void)sender; (void)type;
    if (result != kIOReturnSuccess || reportID != 2 || length < 18 || length > 64) return;
    if (bytes[0] != 2 || bytes[1] != 5 || u16(bytes + 2) != 0 || u16(bytes + 4) != 5) return;
    if (u16(bytes + 6) != response.count || u32(bytes + 10) != response.count ||
        u32(bytes + 14) != response.address || length < 18 + response.count) return;
    memcpy(response.bytes, bytes, (size_t)length);
    response.received = YES;
}
static BOOL readData(IOHIDDeviceRef device, uint32_t address, uint16_t count, uint8_t *output) {
    if (count == 0 || count > 46) return NO;
    BOOL inBootApp = address < 0x19000 && count <= 0x19000 - address;
    BOOL inUpdate = address >= 0x3f000 && address < 0x53000 && count <= 0x53000 - address;
    if (!inBootApp && !inUpdate) return NO;
    response.received = NO; response.address = address; response.count = count;
    uint8_t packet[64] = {0};
    packet[0] = 0x81; packet[1] = 5;
    put16(packet + 2, 5); put16(packet + 6, count);
    put32(packet + 10, count); put32(packet + 14, address);
    IOReturn status = IOHIDDeviceSetReport(device, kIOHIDReportTypeOutput, 0x81, packet, sizeof(packet));
    CFAbsoluteTime deadline = CFAbsoluteTimeGetCurrent() + 3;
    while (status == kIOReturnSuccess && !response.received && CFAbsoluteTimeGetCurrent() < deadline)
        CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.05, true);
    if (!response.received) {
        printf("Read failed at 0x%08x, length %u, transport status 0x%08x; no retry.\n", address, count, status);
        return NO;
    }
    memcpy(output, response.bytes + 18, count);
    return YES;
}
int main(int argc, char **argv) {
    @autoreleasepool {
        setbuf(stdout, NULL);
        BOOL bootBackup = argc == 3 && strcmp(argv[1], "--backup-boot") == 0;
        BOOL updateBackup = argc == 3 && strcmp(argv[1], "--backup-update") == 0;
        BOOL paddingBackup = argc == 3 && strcmp(argv[1], "--backup-padding") == 0;
        if (argc != 1 && !(argc == 3 && (strcmp(argv[1], "--backup") == 0 || bootBackup || updateBackup || paddingBackup))) {
            fputs("Usage: read_firmware [--backup|--backup-boot|--backup-padding|--backup-update FILE]\n", stderr);
            return 2;
        }
        IOHIDManagerRef manager = IOHIDManagerCreate(kCFAllocatorDefault, kIOHIDOptionsTypeNone);
        if (!manager) { puts("HID manager creation failed."); return 1; }
        NSDictionary *match = @{@kIOHIDVendorIDKey:@0x2dc8, @kIOHIDProductIDKey:@0x310a, @kIOHIDPrimaryUsagePageKey:@0xff7a, @kIOHIDPrimaryUsageKey:@1};
        IOHIDManagerSetDeviceMatching(manager, (__bridge CFDictionaryRef)match);
        IOReturn status = IOHIDManagerOpen(manager, kIOHIDOptionsTypeNone);
        printf("Manager open: 0x%08x\n", status);
        if (status != kIOReturnSuccess) { CFRelease(manager); return 1; }
        NSSet *devices = CFBridgingRelease(IOHIDManagerCopyDevices(manager));
        if (devices.count != 1) {
            printf("Refusing: expected exactly one vendor HID interface, found %lu\n", (unsigned long)devices.count);
            IOHIDManagerClose(manager, 0); CFRelease(manager); return 1;
        }
        IOHIDDeviceRef device = (__bridge IOHIDDeviceRef)devices.anyObject;
        CFRetain(device);
        NSString *transport = (__bridge id)IOHIDDeviceGetProperty(device, CFSTR(kIOHIDTransportKey));
        NSNumber *size = (__bridge id)IOHIDDeviceGetProperty(device, CFSTR(kIOHIDMaxOutputReportSizeKey));
        if (![transport isEqualToString:@"USB"] || size.unsignedIntValue != 64) {
            puts("Refusing: interface transport/report size differs from reviewed protocol.");
            CFRelease(device); IOHIDManagerClose(manager, 0); CFRelease(manager); return 1;
        }
        status = IOHIDDeviceOpen(device, kIOHIDOptionsTypeNone);
        printf("Device open (non-exclusive): 0x%08x\n", status);
        if (status != kIOReturnSuccess) { CFRelease(device); IOHIDManagerClose(manager, 0); CFRelease(manager); return 1; }
        uint8_t inputBuffer[64] = {0};
        IOHIDDeviceRegisterInputReportCallback(device, inputBuffer, sizeof(inputBuffer), input, NULL);
        IOHIDDeviceScheduleWithRunLoop(device, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode);
        uint8_t header[32];
        int result = 1;
        if (readData(device, 0x6000, sizeof(header), header) && memcmp(header + 8, "KNLT", 4) == 0) {
            unsigned version = u16(header + 2);
            printf("Telink image header. Installed firmware version: %u.%02u (raw %u).\n", version / 100, version % 100, version);
            if (version != 109 || u32(header + 24) != 0x12274) {
                puts("Refusing: these flash bounds have only been established for the v1.09 header.");
            } else {
                result = 0;
                if (argc == 3) {
                    FILE *out = fopen(argv[2], "wx");
                    if (!out) { perror("Creating backup without overwrite"); result = 1; }
                    else {
                        const uint32_t imageLength = bootBackup ? 0x6000 : updateBackup ? 0x14000 : paddingBackup ? 0xc00 : 0x12400;
                        const uint32_t imageBase = bootBackup ? 0 : updateBackup ? 0x3f000 : paddingBackup ? 0x18400 : 0x6000;
                        const char *region = bootBackup ? "boot" : updateBackup ? "update-metadata-and-staging" : paddingBackup ? "application-sector-tail" : "application";
                        uint32_t done = 0;
                        uint8_t chunk[46];
                        while (done < imageLength) {
                            uint16_t count = imageLength - done < sizeof(chunk) ? (uint16_t)(imageLength - done) : sizeof(chunk);
                            if (!readData(device, imageBase + done, count, chunk) || fwrite(chunk, 1, count, out) != count) {
                                result = 1; break;
                            }
                            done += count;
                            if (done / 4096 != (done - count) / 4096 || done == imageLength)
                                printf("Read %u / %u %s bytes\n", done, imageLength, region);
                        }
                        if (fclose(out) != 0) { perror("Closing backup"); result = 1; }
                        printf("%s %s-region backup: %s (%u / %u bytes).\n", result == 0 ? "Complete" : "INCOMPLETE", region, argv[2], done, imageLength);
                        puts("A readback snapshot does not establish recovery entry or prove restoration.");
                    }
                }
            }
        } else puts("No validated Telink application header; no version inferred.");
        IOHIDDeviceUnscheduleFromRunLoop(device, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode);
        IOHIDDeviceClose(device, kIOHIDOptionsTypeNone);
        CFRelease(device);
        IOHIDManagerClose(manager, kIOHIDOptionsTypeNone);
        CFRelease(manager);
        return result;
    }
}
