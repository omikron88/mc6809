import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from zxspectrum import Spectrum48
from zxspectrum.audio import Beeper
from zxspectrum.demo import demo_rom
from zxspectrum.video import bitmap_offset, pixel_row, render_rgb, PALETTE, DISPLAY_WIDTH, DISPLAY_HEIGHT, BORDER


class SpectrumTests(unittest.TestCase):
    def test_rom_size_and_memory_map(self):
        with self.assertRaises(ValueError):
            Spectrum48(b'')
        m = Spectrum48(bytes([0x42]) * 16384)
        m.write(0, 0)
        self.assertEqual(m.read(0), 0x42)
        m.write(0x4000, 0x123)
        m.write(0xFFFF, 45)
        self.assertEqual(m.ram[0], 0x23)
        self.assertEqual(m.read(-1), 45)

    def test_keyboard_rows_and_multirow_scan(self):
        m = Spectrum48(bytes(16384))
        m.set_key('caps shift')
        m.set_key('S')
        self.assertEqual(m.input(0xFEFE) & 31, 30)
        self.assertEqual(m.input(0xFDFE) & 31, 29)
        self.assertEqual(m.input(0xFCFE) & 31, 28)
        self.assertEqual(m.input(0xFFFE), 255)
        self.assertEqual(m.input(0xFFFF), 255)
        m.set_key('S', False)
        self.assertEqual(m.input(0xFDFE), 255)
        m.ear = False
        self.assertEqual(m.input(0xFFFE), 0xBF)

    def test_all_40_keys_are_wired(self):
        m = Spectrum48(bytes(16384))
        for name, (row, bit) in m.KEY_POSITIONS.items():
            m.keys = {name}
            self.assertEqual(m.input((0xFF ^ (1 << row)) << 8 | 0xFE) & 31, 31 ^ (1 << bit))

    def test_port_aliases_border_and_speaker(self):
        m = Spectrum48(bytes(16384))
        m.output(0x12FC, 0x1B)
        self.assertEqual(m.border, 3)
        self.assertTrue(m.mic)
        self.assertTrue(m.speaker)
        self.assertEqual(m.beeper_events, [(0, True)])
        m.output(0xFE, 0x1B)
        self.assertEqual(len(m.beeper_events), 1)
        m.output(0xFF, 0)
        self.assertEqual(m.border, 3)

    def test_im1_interrupt_each_frame_and_halt(self):
        rom = bytearray(16384)
        handler = bytes.fromhex('f5 3a 00 80 3c 32 00 80 f1 fb ed 4d')
        rom[0x38:0x38+len(handler)] = handler
        rom[0x100:0x104] = bytes.fromhex('fb 76 18 fd')
        m = Spectrum48(rom)
        m.cpu.r.pc = 0x100
        m.cpu.im = 1
        for _ in range(3):
            m.run_frame()
        self.assertEqual(m.read(0x8000), 3)
        self.assertTrue(m.cpu.halted)

    def test_frame_overshoot_does_not_accumulate(self):
        rom = (bytes.fromhex('3e 00 c3 00 00') + bytes(16384))[:16384]
        m = Spectrum48(rom)
        for n in range(1, 11):
            m.run_frame()
            self.assertGreaterEqual(m.cpu.cycles, n * m.FRAME_CYCLES)
            self.assertLess(m.cpu.cycles, n * m.FRAME_CYCLES + 10)

    def test_flash_period_and_reset_retains_ram(self):
        m = Spectrum48(bytes(16384))
        m.cpu.cycles = 16 * m.FRAME_CYCLES
        self.assertTrue(m.flash_phase)
        m.cpu.cycles = 32 * m.FRAME_CYCLES
        self.assertFalse(m.flash_phase)
        m.ram[123] = 99
        m.set_key('A')
        m.reset()
        self.assertEqual(m.cpu.cycles, 0)
        self.assertEqual(m.keys, set())
        self.assertEqual(m.ram[123], 99)

    def test_demo_rom_executes_and_preserves_registers(self):
        m = Spectrum48(demo_rom())
        for _ in range(4):
            m.run_frame()
        self.assertEqual(m.ram[:6912], m.rom[0x400:0x400+6912])
        self.assertEqual(m.cpu.r.bc, 0)
        self.assertTrue(m.cpu.halted)
        m.keys = {'CAPS SHIFT'}
        for _ in range(2):
            m.run_frame()
        self.assertEqual(m.border, 1)


class VideoTests(unittest.TestCase):
    def test_interleaved_bitmap_addresses(self):
        self.assertEqual([bitmap_offset(0, y) for y in (0, 1, 7, 8, 63, 64, 127, 128, 191)],
                         [0, 256, 1792, 32, 2016, 2048, 4064, 4096, 6112])
        self.assertEqual(len({bitmap_offset(x, y) for y in range(192) for x in range(32)}), 6144)

    def test_ink_paper_bright_and_flash(self):
        normal = pixel_row(0x80, 0x4A, False)  # bright red ink, blue paper
        self.assertEqual(normal[:3], bytes(PALETTE[10]))
        self.assertEqual(normal[3:6], bytes(PALETTE[9]))
        self.assertEqual(pixel_row(0x80, 0xCA, True)[:3], bytes(PALETTE[9]))
        self.assertEqual(pixel_row(0x80, 0x4A, True), normal)

    def test_full_rgb_frame_and_attribute_cells(self):
        m = Spectrum48(bytes(16384))
        m.border = 4
        m.ram[0] = 0x80
        m.ram[0x1800] = 2
        rgb = render_rgb(m)
        self.assertEqual(len(rgb), DISPLAY_WIDTH * DISPLAY_HEIGHT * 3)
        self.assertEqual(rgb[:3], bytes(PALETTE[4]))
        pixel = (BORDER * DISPLAY_WIDTH + BORDER) * 3
        self.assertEqual(rgb[pixel:pixel+3], bytes(PALETTE[2]))
        self.assertEqual(rgb[pixel+3:pixel+6], bytes(PALETTE[0]))


class AudioTests(unittest.TestCase):
    def test_speaker_transitions_and_fractional_samples(self):
        m = Spectrum48(bytes(16384))
        beeper = Beeper(rate=35000)  # one sample per 100 CPU cycles
        m.output(0xFE, 16)
        m.cpu.cycles = 150
        m.output(0xFE, 0)
        m.cpu.cycles = 300
        self.assertEqual(struct.unpack('<3h', beeper.render(m)), (6000, 6000, 0))
        self.assertEqual(m.beeper_events, [])
        self.assertEqual(beeper.render(m), b'')


class FrontendTests(unittest.TestCase):
    def test_cli_rejects_bad_rom_before_importing_pygame(self):
        with tempfile.TemporaryDirectory() as tmp:
            rom = Path(tmp) / 'bad.rom'
            rom.write_bytes(b'\0')
            result = subprocess.run([sys.executable, '-m', 'zxspectrum', '--rom', str(rom)],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn(b'16384', result.stderr)

    def test_pygame_dummy_display_and_audio(self):
        try:
            import pygame
        except ImportError:
            self.skipTest('optional Pygame dependency is not installed')
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / 'screen.png'
            env = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy', PYGAME_HIDE_SUPPORT_PROMPT='1')
            result = subprocess.run([sys.executable, '-m', 'zxspectrum', '--demo', '--frames', '4',
                                     '--scale', '1', '--no-limit', '--screenshot', str(png)],
                                    env=env, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(png.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
            image = pygame.image.load(str(png))
            self.assertEqual(image.get_size(), (320, 256))
            self.assertGreater(len(set(pygame.image.tobytes(image, 'RGB'))), 1)


if __name__ == '__main__':
    unittest.main()
