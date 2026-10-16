#import <Foundation/Foundation.h>
#import <IOKit/hid/IOHIDLib.h>
#import <CommonCrypto/CommonDigest.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

// BOOT only: 2dc8:3208. Protocol traced in the pinned original BOOT region:
// router 0x3fe4, erase 0x3b90, program 0x3c74, read 0x3e14, reset 0x3f70.
// Modify only [0x6000,0x19000), preserving the original final-sector tail.
// Any transfer/verification failure stops without an automatic retry or reset.
static const uint32_t APP_BASE = 0x6000, APP_SIZE = 0x12400, REGION_SIZE = 0x13000;
static const uint32_t UPDATE_BASE = 0x3f000, UPDATE_SIZE = 0x14000;
static const char *ORIGINAL_DAT_SHA = "87349e603bb92d6ae9ff6defb6f32b10de2f2d3252fe4e442fa7993f982f2a5a";
static const char *CANDIDATE_DAT_SHA = "e52216167e7f3f5e0a15d14b68b345b54a12a8b637b1052ddc1d595a0a57c88f";
static const char *BOOT_SHA = "d64d7096c29f0f4ee21981df4b3f738c7895f209cdbdeb81f941838820be340d";
static const char *TAIL_SHA = "1a7493ff2f2bde5f78405d46eb01abfeaea9b0a95fa5b6cec211b05faa0cf1d3";
static uint16_t u16(const uint8_t *p) { return p[0] | ((uint16_t)p[1] << 8); }
static uint32_t u32(const uint8_t *p) { return u16(p) | ((uint32_t)u16(p + 2) << 16); }
static void p16(uint8_t *p, uint16_t n) { p[0] = n; p[1] = n >> 8; }
static void p32(uint8_t *p, uint32_t n) { p16(p, n); p16(p + 2, n >> 16); }
static uint16_t crc16(const uint8_t *p, uint16_t count) {
    uint16_t crc = 0xffff;
    for (uint16_t i = 0; i < count; ++i) {
        crc ^= p[i];
        for (unsigned bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ ((crc & 1) ? 0xa001 : 0);
    }
    return crc;
}
static BOOL hashIs(NSData *data, const char *expected) {
    unsigned char digest[CC_SHA256_DIGEST_LENGTH]; char text[65];
    if (data.length > UINT32_MAX) return NO;
    CC_SHA256(data.bytes, (CC_LONG)data.length, digest);
    for (unsigned i = 0; i < sizeof(digest); ++i) snprintf(text + 2 * i, 3, "%02x", digest[i]);
    return strcmp(text, expected) == 0;
}
static NSData *load(NSString *path, NSUInteger length, const char *hash) {
    NSError *error = nil;
    NSDictionary *attributes = [[NSFileManager defaultManager] attributesOfItemAtPath:path error:&error];
    if (!attributes || [attributes fileSize] != length) { printf("Missing/wrong-size artifact: %s\n", path.fileSystemRepresentation); return nil; }
    NSData *data = [[NSData alloc] initWithContentsOfFile:path options:0 error:&error];
    if (!data || data.length != length || (hash && !hashIs(data, hash))) { printf("Artifact read/SHA-256 mismatch: %s\n", path.fileSystemRepresentation); return nil; }
    return data;
}
static BOOL metadataIsInactive(const uint8_t *bytes, size_t length) {
    return bytes && length >= 52 && u16(bytes + 48) == crc16(bytes, 48) &&
        u32(bytes + 24) == 0 && u32(bytes + 32) == 0;
}
static BOOL imageHeaderIsValid(NSData *image) {
    if (image.length != 28 + APP_SIZE) return NO;
    const uint8_t *dat = image.bytes, *app = dat + 28;
    return u32(dat) == 109 && u32(dat + 4) == APP_BASE && u32(dat + 8) == APP_SIZE &&
        u32(dat + 12) == 0x301b && u16(app + 2) == 109 &&
        memcmp(app + 8, "KNLT", 4) == 0 && u32(app + 24) == 0x12274;
}
static struct {
    uint16_t command, count; uint32_t address, total;
    BOOL ready; uint8_t bytes[64];
} response;
static void input(void *context, IOReturn status, void *sender, IOHIDReportType type, uint32_t reportID, uint8_t *bytes, CFIndex size) {
    (void)context; (void)sender; (void)type;
    if (status != kIOReturnSuccess || reportID != 0 || size != 64 || bytes[0] != 0 || bytes[1] != 5) return;
    if (u16(bytes + 4) != response.command) return;
    // Erase clears length/total at 0x3c24..0x3c30; program/read echo them.
    uint16_t count = response.command == 4 ? 0 : response.count;
    uint32_t total = response.command == 4 ? 0 : response.total;
    if (response.command != 8 && (u16(bytes + 6) != count || u32(bytes + 10) != total || u32(bytes + 14) != response.address)) return;
    memcpy(response.bytes, bytes, 64); response.ready = YES;
}
static BOOL requestIsAllowed(uint16_t command, uint32_t address, uint16_t count, uint32_t total, const uint8_t *payload) {
    if (command == 4) {
        return !payload && count == 0 && total == 0x1000 && address >= APP_BASE && address < APP_BASE + REGION_SIZE && !(address & 0xfff);
    }
    if (command == 3) {
        return payload && count > 0 && count <= 46 && total == REGION_SIZE && address >= APP_BASE && address < APP_BASE + REGION_SIZE && count <= APP_BASE + REGION_SIZE - address && count <= 0x100 - (address & 0xff);
    }
    if (command == 5) {
        BOOL inBootApp = address < APP_BASE + REGION_SIZE && count <= APP_BASE + REGION_SIZE - address;
        BOOL inUpdate = address >= UPDATE_BASE && address < UPDATE_BASE + UPDATE_SIZE && count <= UPDATE_BASE + UPDATE_SIZE - address;
        return !payload && count > 0 && count <= 46 && total == count && (inBootApp || inUpdate);
    }
    if (command == 8) return !payload && address == 0 && count == 4 && total == 4;
    if (command == 7) return !payload && address == 0 && count == 0 && total == 0;
    return NO;
}
static BOOL exchange(IOHIDDeviceRef device, uint16_t command, uint32_t address, uint16_t count, uint32_t total, const uint8_t *payload) {
    if (!requestIsAllowed(command, address, count, total, payload)) return NO;
    uint8_t packet[64] = {0}; packet[0] = 5;
    p16(packet + 1, command); p16(packet + 5, count);
    p16(packet + 7, payload ? crc16(payload, count) : 0);
    p32(packet + 9, total); p32(packet + 13, address);
    if (payload) memcpy(packet + 17, payload, count);
    response.command = command; response.count = count; response.address = address; response.total = total; response.ready = NO;
    IOReturn status = IOHIDDeviceSetReport(device, kIOHIDReportTypeOutput, 0, packet, sizeof(packet));
    if (status != kIOReturnSuccess) { printf("Transport error 0x%08x: command %u address 0x%x\n", status, command, address); return NO; }
    CFAbsoluteTime deadline = CFAbsoluteTimeGetCurrent() + (command == 4 ? 10 : 3);
    while (!response.ready && CFAbsoluteTimeGetCurrent() < deadline) CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.05, true);
    if (!response.ready || u16(response.bytes + 2) != 0) { printf("Rejected/timed-out command %u at 0x%x; no retry.\n", command, address); return NO; }
    if (command == 8 && (u16(response.bytes + 6) != 2 || u32(response.bytes + 10) != 2 || u16(response.bytes + 18) != 0x301b)) { puts("BOOT application identity mismatch."); return NO; }
    return YES;
}
static BOOL compareRange(IOHIDDeviceRef device, uint32_t address, const uint8_t *expected, uint32_t count) {
    for (uint32_t offset = 0; offset < count;) {
        uint16_t chunk = count - offset < 46 ? (uint16_t)(count - offset) : 46;
        if (!exchange(device, 5, address + offset, chunk, chunk, NULL)) return NO;
        if (memcmp(response.bytes + 18, expected + offset, chunk) != 0) { printf("Readback differs at 0x%x.\n", address + offset); return NO; }
        offset += chunk;
    }
    return YES;
}
static const uint8_t *imagePart(const uint8_t *app, const uint8_t *tail, uint32_t offset, uint32_t *available) {
    if (offset >= REGION_SIZE) { *available = 0; return NULL; }
    if (offset < APP_SIZE) { *available = APP_SIZE - offset; return app + offset; }
    *available = REGION_SIZE - offset; return tail + (offset - APP_SIZE);
}
static BOOL compareImage(IOHIDDeviceRef device, const uint8_t *app, const uint8_t *tail) {
    return compareRange(device, APP_BASE, app, APP_SIZE) && compareRange(device, APP_BASE + APP_SIZE, tail, REGION_SIZE - APP_SIZE);
}
static BOOL replaceSector(BOOL restore, uint32_t sector, const uint8_t *target, const uint8_t *original) {
    if (sector >= REGION_SIZE || (sector & 0xfff)) return NO;
    uint32_t count = APP_SIZE - sector;
    if (count > 0x1000) count = 0x1000;
    // The saved tail is identical on both sides. Compare only actual app bytes.
    return restore || memcmp(target + sector, original + sector, count) != 0;
}
int main(int argc, char **argv) {
    @autoreleasepool {
        setbuf(stdout, NULL);
        const char *usage = "Usage: boot_firmware --check-image|--verify-reset|--flash|--restore IMAGE.dat\n";
        if (argc != 3) { fputs(usage, stderr); return 2; }
        BOOL check = strcmp(argv[1], "--check-image") == 0;
        BOOL verifyReset = strcmp(argv[1], "--verify-reset") == 0;
        BOOL restore = strcmp(argv[1], "--restore") == 0;
        BOOL flash = strcmp(argv[1], "--flash") == 0;
        if (!check && !verifyReset && !restore && !flash) { fputs(usage, stderr); return 2; }
        NSString *imagePath = [NSString stringWithUTF8String:argv[2]];
        if (!imagePath.length) { fputs(usage, stderr); return 2; }
        NSString *directory = [imagePath stringByDeletingLastPathComponent];
        if (!directory.length) directory = @".";
        NSData *image = load(imagePath, 74780, NULL);
        if (!image) return 1;
        BOOL stockImage = hashIs(image, ORIGINAL_DAT_SHA), patchedImage = hashIs(image, CANDIDATE_DAT_SHA);
        if ((check && !stockImage && !patchedImage) || (flash && !patchedImage) || ((restore || verifyReset) && !stockImage)) { puts("Unsupported image SHA-256 for requested action."); return 1; }
        NSData *original = stockImage ? image : load([directory stringByAppendingPathComponent:@"original-v1.09-restore.dat"], 74780, ORIGINAL_DAT_SHA);
        NSData *savedApp = load([directory stringByAppendingPathComponent:@"original-application-v1.09.bin"], APP_SIZE, NULL);
        NSData *boot = load([directory stringByAppendingPathComponent:@"original-boot-region.bin"], 0x6000, BOOT_SHA);
        NSData *tail = load([directory stringByAppendingPathComponent:@"original-application-sector-tail.bin"], 0xc00, TAIL_SHA);
        NSData *update = load([directory stringByAppendingPathComponent:@"original-update-metadata-and-staging.bin"], UPDATE_SIZE, NULL);
        if (!original || !savedApp || !boot || !tail || !update) return 1;
        const uint8_t *target = (const uint8_t *)image.bytes + 28, *oldApp = (const uint8_t *)original.bytes + 28, *padding = tail.bytes;
        if (!imageHeaderIsValid(image) || !imageHeaderIsValid(original) || memcmp(savedApp.bytes, oldApp, APP_SIZE) != 0 || crc16((const uint8_t *)"123456789", 9) != 0x4b37) { puts("Fixed image/header/protocol or stock application backup checks failed."); return 1; }
        if (!metadataIsInactive(update.bytes, update.length)) { puts("Update metadata corrupt or pending installation present; refusing every hardware action."); return 1; }
        puts("Verified known image, exact stock backup, pinned BOOT/tail and inactive update snapshot.");
        if (check) { puts("Image-only check completed; no hardware accessed."); return 0; }
        IOHIDManagerRef manager = IOHIDManagerCreate(kCFAllocatorDefault, 0);
        if (!manager) { puts("HID manager creation failed."); return 1; }
        NSDictionary *match = @{@kIOHIDVendorIDKey:@0x2dc8, @kIOHIDProductIDKey:@0x3208, @kIOHIDPrimaryUsagePageKey:@0x8c, @kIOHIDPrimaryUsageKey:@1};
        IOHIDManagerSetDeviceMatching(manager, (__bridge CFDictionaryRef)match);
        IOReturn status = IOHIDManagerOpen(manager, 0);
        if (status != kIOReturnSuccess) { printf("HID manager open failed: 0x%08x\n", status); CFRelease(manager); return 1; }
        NSSet *devices = CFBridgingRelease(IOHIDManagerCopyDevices(manager));
        if (devices.count != 1) { printf("Refusing: expected exactly one BOOT interface, found %lu.\n", (unsigned long)devices.count); IOHIDManagerClose(manager, 0); CFRelease(manager); return 1; }
        IOHIDDeviceRef device = (__bridge IOHIDDeviceRef)devices.anyObject;
        CFRetain(device);
        NSString *transport = (__bridge id)IOHIDDeviceGetProperty(device, CFSTR(kIOHIDTransportKey));
        NSNumber *size = (__bridge id)IOHIDDeviceGetProperty(device, CFSTR(kIOHIDMaxOutputReportSizeKey));
        if (![transport isEqualToString:@"USB"] || size.unsignedIntValue != 64) { puts("Unexpected BOOT interface shape."); CFRelease(device); IOHIDManagerClose(manager, 0); CFRelease(manager); return 1; }
        status = IOHIDDeviceOpen(device, kIOHIDOptionsTypeSeizeDevice);
        if (status != kIOReturnSuccess) { printf("Exclusive BOOT interface open failed: 0x%08x\n", status); CFRelease(device); IOHIDManagerClose(manager, 0); CFRelease(manager); return 1; }
        uint8_t inputBuffer[64] = {0};
        IOHIDDeviceRegisterInputReportCallback(device, inputBuffer, sizeof(inputBuffer), input, NULL);
        IOHIDDeviceScheduleWithRunLoop(device, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode);
        int result = 1;
        BOOL valid = exchange(device, 8, 0, 4, 4, NULL) && compareRange(device, 0, boot.bytes, 0x6000) && compareRange(device, UPDATE_BASE, update.bytes, UPDATE_SIZE);
        // Restoration must accept a damaged app/tail after an interrupted write.
        if (valid && !restore) valid = compareImage(device, oldApp, padding);
        if (valid && !verifyReset) {
            puts("BOOT and inactive update storage verified. Beginning application-only sector replacement.");
            for (uint32_t sector = 0; valid && sector < REGION_SIZE; sector += 0x1000) {
                if (!replaceSector(restore, sector, target, oldApp)) continue;
                valid = exchange(device, 4, APP_BASE + sector, 0, 0x1000, NULL);
                // ACK is not proof of erase: verify every byte of this sector.
                for (uint32_t off = 0; valid && off < 0x1000;) {
                    uint16_t chunk = 0x1000 - off < 46 ? (uint16_t)(0x1000 - off) : 46;
                    valid = exchange(device, 5, APP_BASE + sector + off, chunk, chunk, NULL);
                    for (uint16_t i = 0; valid && i < chunk; ++i) if (response.bytes[18 + i] != 0xff) { printf("Erase readback is not blank at 0x%x.\n", APP_BASE + sector + off + i); valid = NO; }
                    off += chunk;
                }
                for (uint32_t off = sector; valid && off < sector + 0x1000;) {
                    uint32_t available; const uint8_t *data = imagePart(target, padding, off, &available);
                    uint32_t count = 46;
                    if (count > available) count = available;
                    if (count > sector + 0x1000 - off) count = sector + 0x1000 - off;
                    uint32_t pageRemaining = 0x100 - ((APP_BASE + off) & 0xff);
                    if (count > pageRemaining) count = pageRemaining;
                    valid = exchange(device, 3, APP_BASE + off, (uint16_t)count, REGION_SIZE, data);
                    off += count;
                }
                if (valid) printf("Programmed application sector 0x%x; full verification follows.\n", APP_BASE + sector);
            }
        }
        if (valid) valid = compareImage(device, target, padding) && compareRange(device, 0, boot.bytes, 0x6000) && compareRange(device, UPDATE_BASE, update.bytes, UPDATE_SIZE);
        if (valid) {
            puts("Complete app/tail, BOOT and update storage match; sending explicit reset.");
            valid = exchange(device, 7, 0, 0, 0, NULL);
            if (valid) { puts("Reset acknowledged. Normal USB/Bluetooth behavior and BOOT reentry must be observed separately."); result = 0; }
        }
        if (result != 0) puts("STOPPED: no automatic retry/reset. Keep BOOT available; use guarded --restore after resolving the failure.");
        IOHIDDeviceUnscheduleFromRunLoop(device, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode);
        IOHIDDeviceClose(device, kIOHIDOptionsTypeNone);
        CFRelease(device);
        IOHIDManagerClose(manager, 0); CFRelease(manager);
        return result;
    }
}
