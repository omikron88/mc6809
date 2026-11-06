"""ZX bitmap/attribute addressing and RGB rendering without Pygame. GPL-3.0."""
from functools import lru_cache

WIDTH, HEIGHT, BORDER = 256, 192, 32
DISPLAY_WIDTH, DISPLAY_HEIGHT = WIDTH + 2 * BORDER, HEIGHT + 2 * BORDER
PALETTE = tuple((level if i & 2 else 0, level if i & 4 else 0, level if i & 1 else 0)
                for level in (205, 255) for i in range(8))


def bitmap_offset(x_byte, y):
    return ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2) | x_byte


@lru_cache(maxsize=8192)
def pixel_row(pattern, attribute, flash):
    bright = (attribute >> 3) & 8
    ink = (attribute & 7) | bright
    paper = ((attribute >> 3) & 7) | bright
    if attribute & 128 and flash:
        ink, paper = paper, ink
    return bytes(component for bit in range(7, -1, -1)
                 for component in PALETTE[ink if pattern & (1 << bit) else paper])


def render_rgb(machine):
    """Return a 320x256 RGB frame. Border uses the last ULA colour of the frame."""
    rgb = bytearray(bytes(PALETTE[machine.border]) * (DISPLAY_WIDTH * DISPLAY_HEIGHT))
    flash = machine.flash_phase
    for y in range(HEIGHT):
        base = ((y + BORDER) * DISPLAY_WIDTH + BORDER) * 3
        attributes = 0x1800 + (y // 8) * 32
        for x in range(32):
            start = base + x * 24
            rgb[start:start+24] = pixel_row(machine.ram[bitmap_offset(x, y)],
                                            machine.ram[attributes + x], flash)
    return bytes(rgb)
