// Offline regression: no IOHID manager/device calls or mock device I/O.
// Erase ACK fixture derives from BOOT handler 0x3c24..0x3c5e: status=0,
// original command=4, length/total cleared, address retained.
#define main boot_program_main
#include "../native/boot_firmware.m"
#undef main

static int failures;
static void expect(BOOL condition, const char *message) {
    if (!condition) { printf("FAIL: %s\n", message); ++failures; }
}
static void prepareErase(void) {
    memset(&response, 0, sizeof(response));
    response.command = 4; response.count = 0; response.total = 0x1000; response.address = 0x6000;
}
static void testAcknowledgements(void) {
    uint8_t ack[64] = {0x00,0x05,0x00,0x00,0x04,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x60,0x00,0x00};
    prepareErase();
    input(NULL, kIOReturnSuccess, NULL, kIOHIDReportTypeInput, 0, ack, sizeof(ack));
    expect(response.ready && u16(response.bytes + 2) == 0, "accept erase ACK with cleared total despite request total=4096");
    prepareErase(); ack[2] = 1;
    input(NULL, kIOReturnSuccess, NULL, kIOHIDReportTypeInput, 0, ack, sizeof(ack));
    expect(response.ready && u16(response.bytes + 2) == 1, "surface matching rejection rather than ignoring it");
    prepareErase(); ack[2] = 0; ack[15] = 0x70;
    input(NULL, kIOReturnSuccess, NULL, kIOHIDReportTypeInput, 0, ack, sizeof(ack));
    expect(!response.ready, "ignore stale erase ACK from another sector");
    prepareErase(); ack[15] = 0x60; ack[4] = 3;
    input(NULL, kIOReturnSuccess, NULL, kIOHIDReportTypeInput, 0, ack, sizeof(ack));
    expect(!response.ready, "ignore ACK for another operation");
    prepareErase(); ack[4] = 4;
    input(NULL, kIOReturnSuccess, NULL, kIOHIDReportTypeInput, 0, ack, 17);
    expect(!response.ready, "ignore truncated report before header access");
    input(NULL, kIOReturnSuccess, NULL, kIOHIDReportTypeInput, 2, ack, sizeof(ack));
    expect(!response.ready, "ignore wrong report ID");
    input(NULL, kIOReturnError, NULL, kIOHIDReportTypeInput, 0, ack, sizeof(ack));
    expect(!response.ready, "ignore transport error");

    // Program ACK retains request lengths (handler 0x3c74..0x3d02).
    uint8_t programmed[64] = {0x00,0x05,0x00,0x00,0x03,0x00,0x2e,0x00,0x00,0x00,0x00,0x30,0x01,0x00,0x00,0x70,0x01,0x00};
    memset(&response, 0, sizeof(response));
    response.command = 3; response.count = 46; response.total = REGION_SIZE; response.address = 0x17000;
    input(NULL, kIOReturnSuccess, NULL, kIOHIDReportTypeInput, 0, programmed, sizeof(programmed));
    expect(response.ready, "accept program ACK with retained count/total");
    response.ready = NO; programmed[11] = 0; programmed[12] = 0;
    input(NULL, kIOReturnSuccess, NULL, kIOHIDReportTypeInput, 0, programmed, sizeof(programmed));
    expect(!response.ready, "do not apply erase cleared-total contract to program");

    uint8_t read[64] = {0};
    read[1] = 5; p16(read + 4, 5); p16(read + 6, 46);
    p32(read + 10, 46); p32(read + 14, UPDATE_BASE);
    memset(&response, 0, sizeof(response));
    response.command = 5; response.count = 46; response.total = 46; response.address = UPDATE_BASE;
    input(NULL, kIOReturnSuccess, NULL, kIOHIDReportTypeInput, 0, read, sizeof(read));
    expect(response.ready, "accept read ACK in metadata range");
    response.ready = NO; p16(read + 6, 45);
    input(NULL, kIOReturnSuccess, NULL, kIOHIDReportTypeInput, 0, read, sizeof(read));
    expect(!response.ready, "reject read ACK with wrong count");
}
static void testRanges(void) {
    uint8_t payload[46] = {0};
    expect(requestIsAllowed(4, 0x6000, 0, 0x1000, NULL), "erase first app sector");
    expect(requestIsAllowed(4, 0x18000, 0, 0x1000, NULL), "erase last app sector");
    expect(!requestIsAllowed(4, 0x5000, 0, 0x1000, NULL), "cannot erase BOOT");
    expect(!requestIsAllowed(4, 0x19000, 0, 0x1000, NULL), "cannot erase beyond footprint");
    expect(!requestIsAllowed(4, 0x6001, 0, 0x1000, NULL), "cannot erase unaligned sector");
    expect(!requestIsAllowed(4, UPDATE_BASE, 0, 0x1000, NULL), "cannot erase metadata/staging");
    expect(!requestIsAllowed(4, 0x6000, 0, 0x2000, NULL), "cannot erase multiple sectors");
    expect(requestIsAllowed(3, 0x60d2, 46, REGION_SIZE, payload), "program exactly to page edge");
    expect(!requestIsAllowed(3, 0x60d3, 46, REGION_SIZE, payload), "program cannot cross page edge");
    expect(requestIsAllowed(3, 0x18fff, 1, REGION_SIZE, payload), "program final footprint byte");
    expect(!requestIsAllowed(3, 0x18fff, 2, REGION_SIZE, payload), "program cannot cross footprint edge");
    expect(!requestIsAllowed(3, 0x5fff, 1, REGION_SIZE, payload), "cannot program BOOT");
    expect(!requestIsAllowed(3, UPDATE_BASE, 1, REGION_SIZE, payload), "cannot program metadata");
    expect(!requestIsAllowed(3, 0x6000, 47, REGION_SIZE, payload), "program payload limited to 46");
    expect(!requestIsAllowed(3, 0x6000, 1, APP_SIZE, payload), "program uses full erase footprint total");
    expect(requestIsAllowed(5, 0, 46, 46, NULL), "read BOOT");
    expect(requestIsAllowed(5, 0x18fff, 1, 1, NULL), "read final app/tail byte");
    expect(!requestIsAllowed(5, 0x18fff, 2, 2, NULL), "read cannot cross app/tail edge");
    expect(!requestIsAllowed(5, 0x19000, 1, 1, NULL), "cannot read unreviewed gap");
    expect(requestIsAllowed(5, UPDATE_BASE, 46, 46, NULL), "read update metadata");
    expect(requestIsAllowed(5, 0x52fff, 1, 1, NULL), "read final update byte");
    expect(!requestIsAllowed(5, 0x52fff, 2, 2, NULL), "read cannot cross update edge");
    expect(!requestIsAllowed(5, UINT32_MAX, 1, 1, NULL), "reject wrapping address");
    expect(!requestIsAllowed(5, 0, 0, 0, NULL), "reject zero-byte read");
    expect(!requestIsAllowed(5, 0, 47, 47, NULL), "read limited to 46");
    expect(!requestIsAllowed(5, 0, 1, 2, NULL), "read total must equal count");
    expect(requestIsAllowed(8, 0, 4, 4, NULL), "allow identity request");
    expect(requestIsAllowed(7, 0, 0, 0, NULL), "allow explicit reset request");
    expect(!requestIsAllowed(7, 1, 0, 0, NULL), "reject malformed reset");
    expect(!requestIsAllowed(6, 0, 0, 0, NULL), "reject unreviewed command");
}
static void testImagePlan(void) {
    uint8_t app[0x12400] = {0}, tail[0xc00] = {0};
    app[0] = 0x11; app[0x123ff] = 0x22; tail[0] = 0x33; tail[0xbff] = 0x44;
    uint32_t available = 0;
    const uint8_t *part = imagePart(app, tail, 0, &available);
    expect(part == app && available == 0x12400 && *part == 0x11, "application first byte");
    part = imagePart(app, tail, 0x123ff, &available);
    expect(part == app + 0x123ff && available == 1 && *part == 0x22, "application last byte");
    part = imagePart(app, tail, 0x12400, &available);
    expect(part == tail && available == 0xc00 && *part == 0x33, "exact app-to-preserved-tail boundary");
    part = imagePart(app, tail, 0x12fff, &available);
    expect(part == tail + 0xbff && available == 1 && *part == 0x44, "last footprint byte");
    part = imagePart(app, tail, 0x13000, &available);
    expect(!part && available == 0, "reject byte outside footprint");
    uint8_t original[0x12400] = {0};
    memset(app, 0, sizeof(app));
    app[0x113c3] = 1; app[0x12270] = 2;
    unsigned flashSectors = 0, restoreSectors = 0;
    for (uint32_t sector = 0; sector < REGION_SIZE; sector += 0x1000) {
        BOOL selected = replaceSector(NO, sector, app, original);
        expect(selected == (sector == 0x11000 || sector == 0x12000), "flash selects only changed sectors");
        flashSectors += selected;
        restoreSectors += replaceSector(YES, sector, app, original);
    }
    expect(flashSectors == 2 && restoreSectors == 19, "minimal flash does not narrow damaged-image restoration");
    app[0] = 1;
    expect(replaceSector(NO, 0, app, original), "changed earlier sector is not silently skipped");
    expect(!replaceSector(NO, REGION_SIZE, app, original), "reject out-of-range sector");
    expect(!replaceSector(YES, 1, app, original), "reject unaligned restore sector");
    memset(app, 0, sizeof(app));
    expect(!replaceSector(NO, 0x12000, app, original), "unchanged partial last app sector does not force a write");
}
static void testMetadata(void) {
    uint8_t metadata[52] = {0};
    p16(metadata + 48, crc16(metadata, 48));
    expect(crc16((const uint8_t *)"123456789", 9) == 0x4b37, "CRC16 Modbus known vector");
    expect(metadataIsInactive(metadata, sizeof(metadata)), "valid inactive metadata accepted");
    expect(!metadataIsInactive(metadata, 51), "truncated metadata rejected before access");
    expect(!metadataIsInactive(NULL, 52), "missing metadata rejected");
    p32(metadata + 24, 0x12345678); p16(metadata + 48, crc16(metadata, 48));
    expect(!metadataIsInactive(metadata, sizeof(metadata)), "pending magic alone blocks reset and flash");
    p32(metadata + 24, 0); p32(metadata + 32, 0x12400); p16(metadata + 48, crc16(metadata, 48));
    expect(!metadataIsInactive(metadata, sizeof(metadata)), "pending length alone blocks reset and flash");
    p32(metadata + 24, 0x12345678); p16(metadata + 48, crc16(metadata, 48));
    expect(!metadataIsInactive(metadata, sizeof(metadata)), "fully active valid-CRC metadata rejected");
    p32(metadata + 24, 0); p32(metadata + 32, 0); p16(metadata + 48, crc16(metadata, 48));
    metadata[0] ^= 1;
    expect(!metadataIsInactive(metadata, sizeof(metadata)), "corrupt metadata body rejected");
    metadata[0] ^= 1; metadata[48] ^= 1;
    expect(!metadataIsInactive(metadata, sizeof(metadata)), "corrupt stored checksum rejected");
}
int main(void) {
    @autoreleasepool {
        testAcknowledgements(); testRanges(); testImagePlan(); testMetadata();
        if (failures) return 1;
        puts("Offline ACK, range/page, image-boundary, sector-plan and metadata guard checks passed; no hardware accessed.");
        return 0;
    }
}
