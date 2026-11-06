"""Original demo ROM; no Sinclair firmware is distributed. GPL-3.0."""
from .video import bitmap_offset


def demo_rom():
    rom = bytearray(16_384)
    # DI; LD SP,FFFF; copy a 6912-byte screen from ROM to RAM; IM 1; EI; HALT.
    program = bytes.fromhex('f3 31 ff ff 21 00 04 11 00 40 01 00 1b ed b0 ed 56 fb 76 c3 12 00')
    rom[:len(program)] = program
    # Frame ISR: read all keyboard rows, use pressed columns as border colour.
    # Speaker is a 25 Hz demonstration square wave, not a complete sound demo.
    handler = bytes.fromhex('c5 f5 db fe 2f e6 07 47 3a 00 5b ee 10 32 00 5b b0 d3 fe f1 c1 fb ed 4d')
    rom[0x38:0x38+len(handler)] = handler
    screen = bytearray(6912)
    for y in range(192):
        for x in range(32):
            screen[bitmap_offset(x, y)] = 0xAA if (y // 8 + x) & 1 else 0x55
    for y in range(24):
        for x in range(32):
            screen[6144 + y * 32 + x] = (x % 8) | ((y % 8) << 3) | (64 if x >= 16 else 0) | (128 if y >= 20 else 0)
    rom[0x400:0x400+len(screen)] = screen
    return bytes(rom)
